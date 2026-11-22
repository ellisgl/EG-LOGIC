#!/usr/bin/env python3
"""
Transient check of every extracted cell (layout netlist with parasitic caps)
in ngspice: full truth table plus propagation delay and rise/fall times.

usage: python3 run_sim.py [pdk ...]       writes sim/<pdk>_results.json/.md
"""
import itertools
import json
import os
import re
import subprocess
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'gen'))
from rules import PDKS          # noqa: E402
from cells import CELLS, ORDER  # noqa: E402

PDK_ROOT = os.environ.get('PDK_ROOT', os.path.expanduser('~/pdk'))
CLOAD = 10e-15                  # output load
TSTATE = {'gf180mcuD': 4e-9, 'sky130A': 2e-9}
TEDGE = 50e-12


def models(pdk):
    if pdk == 'gf180mcuD':
        d = f'{PDK_ROOT}/gf180mcuD/libs.tech/ngspice'
        return f'.include {d}/design.ngspice\n.lib {d}/sm141064.ngspice typical\n'
    return f'.lib {PDK_ROOT}/sky130A/libs.tech/ngspice/sky130.lib.spice tt\n'


def layout_netlist(pdk, cell):
    """extracted netlist; GF180's fets are .model cards, so X -> M"""
    txt = open(os.path.join(HERE, '..', pdk, f'{cell}.spice')).read()
    if pdk == 'gf180mcuD':
        txt = re.sub(r'^X(\S+)(.*\b[np]fet_03v3\b)', r'M\1\2', txt, flags=re.M)
    return txt


def pwl(bits, vdd, T):
    pts = [(0.0, bits[0] * vdd)]
    for k in range(1, len(bits)):
        t = k * T
        pts += [(t, bits[k - 1] * vdd), (t + TEDGE, bits[k] * vdd)]
    return 'PWL(' + ' '.join(f'{t:.4g} {v:.4g}' for t, v in pts) + ')'


def run(pdk, cell):
    R = PDKS[pdk]
    c = CELLS[cell]
    vdd, T = R['vdd'], TSTATE[pdk]
    nin = len(c['inputs'])
    # visit every input combination, and every single-input transition
    if nin == 1:
        seq = [(0,), (1,), (0,), (1,), (0,)]
    else:
        seq = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0), (0, 1), (1, 1), (1, 0), (0, 0)]
    cols = list(zip(*seq))
    work = os.path.join(HERE, 'out')
    os.makedirs(work, exist_ok=True)
    base = os.path.join(work, f'{pdk}_{cell}')
    src = '\n'.join(f'V{nm} {nm} 0 {pwl(cols[i], vdd, T)}' for i, nm in enumerate(c['inputs']))
    pins = ' '.join(c['inputs'] + ['Y', 'VDD', 'VSS'])
    tstop = len(seq) * T
    deck = f"""* {cell} {pdk}
{models(pdk)}
{layout_netlist(pdk, cell)}
XDUT {pins} {cell}
VDD VDD 0 {vdd}
VSS VSS 0 0
{src}
CL Y 0 {CLOAD}
.option method=gear
.control
tran 2p {tstop}
wrdata {base}.dat {' '.join(f'v({n})' for n in c['inputs'])} v(Y)
quit
.endc
.end
"""
    open(base + '.cir', 'w').write(deck)
    p = subprocess.run(['ngspice', '-b', base + '.cir'], capture_output=True, text=True)
    if not os.path.exists(base + '.dat'):
        raise RuntimeError(p.stdout[-2000:] + p.stderr[-2000:])
    d = np.loadtxt(base + '.dat')
    t = d[:, 0]
    vin = [d[:, 2 * k + 1] for k in range(nin)]
    vy = d[:, 2 * nin + 1]
    # truth table: sample at the end of each state
    ok = True
    table = []
    for k, bits in enumerate(seq):
        i = np.searchsorted(t, (k + 0.95) * T)
        want = c['fn'](*bits)
        got = vy[i] / vdd
        good = (got > 0.9) if want else (got < 0.1)
        ok &= bool(good)
        table.append((bits, want, round(float(got * vdd), 3)))
    # delays: 50% input edge -> 50% output edge, inside the same state
    tp = {'rise': [], 'fall': []}
    tr = {'rise': [], 'fall': []}
    for k in range(1, len(seq)):
        t0 = k * T + TEDGE / 2
        w = (t >= t0) & (t < (k + 1) * T)
        y = vy[w]
        tw = t[w]
        if (y[0] > vdd / 2) == (y[-1] > vdd / 2):
            continue
        rising = y[-1] > vdd / 2
        i50 = np.nonzero((y > vdd / 2) == rising)[0][0]
        t50 = np.interp(vdd / 2, *(([y[i50 - 1], y[i50]], [tw[i50 - 1], tw[i50]]) if rising
                                    else ([y[i50], y[i50 - 1]], [tw[i50], tw[i50 - 1]])))
        tp['rise' if rising else 'fall'].append(t50 - t0)
        lo, hi = 0.1 * vdd, 0.9 * vdd
        a, b = (lo, hi) if rising else (hi, lo)
        ia = np.nonzero((y > a) == rising)[0][0]
        ib = np.nonzero((y > b) == rising)[0][0]
        tr['rise' if rising else 'fall'].append(tw[ib] - tw[ia])
    f = lambda v: round(float(np.max(v)) * 1e12, 1) if v else None
    return dict(ok=ok, table=table, tplh=f(tp['rise']), tphl=f(tp['fall']),
                tr=f(tr['rise']), tf=f(tr['fall']))


def main():
    pdks = sys.argv[1:] or ['gf180mcuD', 'sky130A']
    for pdk in pdks:
        res = {}
        for cell in ORDER:
            res[cell] = run(pdk, cell)
            r = res[cell]
            print(f"{pdk:10s} {cell:5s} truth table {'PASS' if r['ok'] else 'FAIL'}  "
                  f"tpLH {r['tplh']} ps  tpHL {r['tphl']} ps  tr {r['tr']} ps  tf {r['tf']} ps")
        json.dump(res, open(os.path.join(HERE, f'{pdk}_results.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
