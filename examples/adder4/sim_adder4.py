#!/usr/bin/env python3
"""
Exhaustive transient test of the extracted ADD4 (all 512 A, B, Cin
combinations) in ngspice. Checks S[3:0] and Cout at the end of every state
and reports the worst-case settle time (input edge -> last output crossing
of VDD/2), i.e. the carry-ripple critical path.

usage: python3 sim_adder4.py <pdk>
"""
import os
import re
import subprocess
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'sim'))
sys.path.insert(0, os.path.join(ROOT, 'gen'))
from run_sim import models, pwl  # noqa: E402
from rules import PDKS           # noqa: E402

T = {'sky130A': 1.5e-9, 'gf180mcuD': 3e-9}
CLOAD = 10e-15


def main():
    pdk = sys.argv[1]
    vdd = PDKS[pdk]['vdd']
    d = os.path.join(HERE, pdk)
    net = open(os.path.join(d, 'ADD4.spice')).read()
    if pdk == 'gf180mcuD':
        net = re.sub(r'^X(\S+)(.*\b[np]fet_03v3\b)', r'M\1\2', net, flags=re.M)
    # visit the 512 vectors in Gray-code order so consecutive states differ by one input
    seq = [k ^ (k >> 1) for k in range(512)]
    bits = lambda v, k: (v >> k) & 1
    names = [f'A{i}' for i in range(4)] + [f'B{i}' for i in range(4)] + ['Cin']
    src = '\n'.join(f'V{n} {n} 0 {pwl([bits(v, k) for v in seq], vdd, T[pdk])}'
                    for k, n in enumerate(names))
    outs = [f'S{i}' for i in range(4)] + ['Cout']
    loads = '\n'.join(f'C{o} {o} 0 {CLOAD}' for o in outs)
    dat = os.path.join(d, 'ADD4_sim.dat')
    deck = f"""* ADD4 exhaustive test ({pdk})
{models(pdk)}
{net}
XDUT {' '.join(names)} {' '.join(outs)} VDD VSS ADD4
VDD VDD 0 {vdd}
VSS VSS 0 0
{src}
{loads}
.option method=gear
.control
tran 5p {len(seq) * T[pdk]}
wrdata {dat} {' '.join(f'v({o})' for o in outs)}
quit
.endc
.end
"""
    cir = os.path.join(d, 'ADD4_sim.cir')
    open(cir, 'w').write(deck)
    p = subprocess.run(['ngspice', '-b', cir], capture_output=True, text=True)
    if not os.path.exists(dat):
        sys.exit(p.stdout[-3000:] + p.stderr[-3000:])
    D = np.loadtxt(dat)
    t = D[:, 0]
    Y = D[:, 1::2]
    fails, settle = 0, []
    for k, v in enumerate(seq):
        a, b, c = v & 15, (v >> 4) & 15, v >> 8
        s = a + b + c
        want = [(s >> i) & 1 for i in range(4)] + [s >> 4]
        i_end = np.searchsorted(t, (k + 0.97) * T[pdk])
        got = Y[i_end] / vdd
        if any((g < 0.8) if w else (g > 0.2) for g, w in zip(got, want)):
            fails += 1
        if k:
            w = (t >= k * T[pdk]) & (t < (k + 1) * T[pdk])
            hi = Y[w] > vdd / 2
            ch = np.nonzero((hi[1:] != hi[:-1]).any(axis=1))[0]
            if len(ch):
                settle.append(t[w][ch[-1] + 1] - k * T[pdk])
    worst = max(settle)
    print(f'{pdk} ADD4: {512 - fails}/512 vectors correct, worst-case settle {worst * 1e12:.0f} ps '
          f'({CLOAD * 1e15:.0f} fF loads)')
    open(os.path.join(d, 'ADD4_sim.txt'), 'w').write(
        f'vectors_ok {512 - fails}/512\nworst_settle_ps {worst * 1e12:.0f}\n')
    os.remove(dat)


if __name__ == '__main__':
    main()
