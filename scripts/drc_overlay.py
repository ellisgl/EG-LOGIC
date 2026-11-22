#!/usr/bin/env python3
"""overlay Magic DRC boxes (from drc_dump.tcl -> drc_boxes.txt) on a cell's masks"""
import sys, numpy as np, matplotlib
matplotlib.use('Agg'); import matplotlib.pyplot as plt
cell, win = sys.argv[1], [float(v) for v in sys.argv[2:6]] if len(sys.argv) > 5 else None
d = np.load(f'{cell}_masks.npz'); G = 0.005
x0, y0 = float(d['x0']), float(d['y0'])
ny, nx = d['R1'].shape
img = np.ones((ny, nx, 3))
for k, c, a in [('NW', (.8, .8, .6), .4), ('ntap', (.2, .6, .2), .7), ('ptap', (.6, .3, .1), .7),
                ('pdiff', (1, .6, .2), .8), ('ndiff', (.2, .8, .3), .8), ('poly', (.9, .1, .1), .8),
                ('R1', (.4, .4, 1), .45), ('R2', (.6, .2, .8), .3), ('CT', (0, 0, 0), 1), ('VIA', (.3, .3, .3), .9)]:
    img = np.where(d[k][..., None], img * (1 - a) + np.array(c) * a, img)
fig, ax = plt.subplots(figsize=(12, 9))
ax.imshow(img, origin='lower', extent=[x0, x0 + nx * G, y0, y0 + ny * G], interpolation='nearest')
for ln in open('drc_boxes.txt'):
    why, b = ln.rsplit('|', 1)
    a = [float(v) * G for v in b.split()]
    ax.add_patch(plt.Rectangle((a[0], a[1]), max(a[2] - a[0], .02), max(a[3] - a[1], .02), fill=False, ec='r', lw=1.5))
if win: ax.set_xlim(win[0], win[1]); ax.set_ylim(win[2], win[3])
plt.savefig(f'{cell}_drc.png', dpi=100)
