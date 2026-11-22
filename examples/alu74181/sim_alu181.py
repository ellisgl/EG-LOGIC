#!/usr/bin/env python3
"""
Transient test of the extracted ALU181 in ngspice.

Vectors: every S (16) x M (2) x Cn (2) combination with 4 random A/B pairs
(256 states), then the longest carry ripple (A plus B with A=1111, B=0000,
Cn toggling). All 8 outputs are checked at the end of each state against
the gate model, which itself matches the 74181 function table on all 2^14
inputs (alu181_netlist.py).

usage: python3 sim_alu181.py <pdk>
"""
import os
import random
import re
import subprocess
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'sim'))
sys.path.insert(0, os.path.join(ROOT, 'gen'))
from run_sim import models, pwl                      # noqa: E402
from rules import PDKS                               # noqa: E402
from alu181_netlist import INPUTS, OUTPUTS, evaluate  # noqa: E402

T = {'sky130A': 4e-9, 'gf180mcuD': 7e-9}
CLOAD = 10e-15


def vectors():
    rng = random.Random(181)
    seq = []
    for S in range(16):
        for M in (0, 1):
            for Cn in (1, 0):
                for _ in range(4):
                    seq.append(dict(A=rng.randrange(16), B=rng.randrange(16), S=S, M=M, Cn=Cn))
    for Cn in (1, 0, 1, 0):      # worst ripple: 1111 + 0000 + carry
        seq.append(dict(A=15, B=0, S=9, M=0, Cn=Cn))
    out = []
    for v in seq:
        d = {f'A{i}': (v['A'] >> i) & 1 for i in range(4)}
        d.update({f'B{i}': (v['B'] >> i) & 1 for i in range(4)})
        d.update({f'S{i}': (v['S'] >> i) & 1 for i in range(4)})
        d.update(M=v['M'], Cn=v['Cn'])
        out.append(d)
    return out


def main():
    pdk = sys.argv[1]
    vdd = PDKS[pdk]['vdd']
    d = os.path.join(HERE, pdk)
    net = open(os.path.join(d, 'ALU181.spice')).read()
    if pdk == 'gf180mcuD':
        net = re.sub(r'^X(\S+)(.*\b[np]fet_03v3\b)', r'M\1\2', net, flags=re.M)
    seq = vectors()
    src = '\n'.join(f'V{n} {n} 0 {pwl([v[n] for v in seq], vdd, T[pdk])}' for n in INPUTS)
    loads = '\n'.join(f'C{o} {o} 0 {CLOAD}' for o in OUTPUTS)
    dat = os.path.join(d, 'ALU181_sim.dat')
    deck = f"""* ALU181 test ({pdk})
{models(pdk)}
{net}
XDUT {' '.join(INPUTS + OUTPUTS)} VDD VSS ALU181
VDD VDD 0 {vdd}
VSS VSS 0 0
{src}
{loads}
.option method=gear
.control
tran 10p {len(seq) * T[pdk]}
wrdata {dat} {' '.join(f'v({o})' for o in OUTPUTS)}
quit
.endc
.end
"""
    cir = os.path.join(d, 'ALU181_sim.cir')
    open(cir, 'w').write(deck)
    p = subprocess.run(['ngspice', '-b', cir], capture_output=True, text=True)
    if not os.path.exists(dat):
        sys.exit(p.stdout[-3000:] + p.stderr[-3000:])
    D = np.loadtxt(dat)
    t, Y = D[:, 0], D[:, 1::2]
    fails, settle = [], []
    for k, v in enumerate(seq):
        want = [evaluate(v)[o] for o in OUTPUTS]
        got = Y[np.searchsorted(t, (k + 0.97) * T[pdk])] / vdd
        bad = [o for o, g, w in zip(OUTPUTS, got, want) if ((g < 0.8) if w else (g > 0.2))]
        if bad:
            fails.append((k, bad))
        if k:
            w = (t >= k * T[pdk]) & (t < (k + 1) * T[pdk])
            hi = Y[w] > vdd / 2
            ch = np.nonzero((hi[1:] != hi[:-1]).any(axis=1))[0]
            if len(ch):
                settle.append(t[w][ch[-1] + 1] - k * T[pdk])
    worst = max(settle)
    msg = (f'{pdk} ALU181: {len(seq) - len(fails)}/{len(seq)} vectors correct (all 8 outputs), '
           f'worst-case settle {worst * 1e12:.0f} ps ({CLOAD * 1e15:.0f} fF loads)')
    print(msg)
    for k, bad in fails[:10]:
        print('  FAIL state', k, seq[k], bad)
    open(os.path.join(d, 'ALU181_sim.txt'), 'w').write(msg + '\n')
    os.remove(dat)


if __name__ == '__main__':
    main()
