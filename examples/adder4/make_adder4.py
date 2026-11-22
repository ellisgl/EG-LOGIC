#!/usr/bin/env python3
"""
Example: 4-bit ripple-carry adder built from the EG-LOGIC symbol cells.

One full adder per row, cells left to right:
    XOR(A,B)=x   AND(A,B)=g   XOR(x,C)=S   AND(x,C)=t   OR(g,t)=Cout
Bit 0 is the bottom row; each row's carry-out feeds the row above.

Routing sits above the cells, which only use R1/R2:
  R2 stubs  take each cell pin out to the routing grid (one via up)
  R3        horizontal routing + VDD/VSS rails (one pair per row)
  R4        vertical routing + one VDD strap (left) and one VSS strap (right)
  sky130: R3/R4 = met2/met3      gf180mcuD: R3/R4 = metal3/metal4
Neither PDK's routing touches met4/met5 on sky130 (Tiny Tapeout's layers).

usage: python3 make_adder4.py <pdk>   -> <pdk>/ADD4.mag, ADD4_ref.spice, ADD4_preview.png
"""
import heapq
import os
import re
import sys
import time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
G = 0.005

UP = {
    'sky130A': dict(r2='metal1', v23='via1', r3='metal2', v34='via2', r4='metal3',
                    v23_w=0.26, v23_sur2=0.03, v23_sur3=0.03,
                    v34_w=0.28, v34_sur3=0.05, v34_sur4=0.05,
                    w3=0.30, w4=0.30, sp=0.30, pitch=0.70, rail_w=1.20, strap_w=1.60, stub_w=0.32),
    'gf180mcuD': dict(r2='metal2', v23='via2', r3='metal3', v34='via3', r4='metal4',
                      v23_w=0.28, v23_sur2=0.05, v23_sur3=0.05,
                      v34_w=0.28, v34_sur3=0.05, v34_sur4=0.05,
                      w3=0.30, w4=0.30, sp=0.30, pitch=0.80, rail_w=1.20, strap_w=1.60, stub_w=0.40),
}

ROW = ['XOR', 'AND', 'XOR', 'AND', 'OR']


def snap(v):
    return round(round(v / G) * G, 4)


# ------------------------------------------------------------------ cell info
def cell_info(pdk, name):
    txt = open(os.path.join(ROOT, pdk, f'{name}.mag')).read()
    bb = [int(v) * G for v in re.search(r'FIXED_BBOX (\S+) (\S+) (\S+) (\S+)', txt).groups()]
    pins = {}
    for m in re.finditer(r'rlabel \S+ (\S+) (\S+) (\S+) (\S+) \d+ (\S+)', txt):
        x0, y0, x1, y1 = (int(v) * G for v in m.groups()[:4])
        pins[m.group(5)] = (snap((x0 + x1) / 2), snap((y0 + y1) / 2))
    # Power stubs attach where the outline's top (VDD) / bottom (VSS) edge is
    # highest / lowest, at the middle of that flat stretch: the band falls away
    # on both sides of the stub there, so no narrow notch can form.
    # Only the R2 shape under the cell's own VDD / VSS label counts (XOR's
    # floating back arc is taller than the body, for example).
    from scipy import ndimage
    r2 = UP[pdk]['r2']
    sec = re.search(rf'<< {r2} >>\n(.*?)(?=<<)', txt, re.S).group(1)
    rr = np.array([[int(v) for v in ln.split()[1:5]] for ln in sec.strip().splitlines()])
    ox, oy = rr[:, 0].min(), rr[:, 1].min()
    m = np.zeros((rr[:, 3].max() - oy, rr[:, 2].max() - ox), bool)
    for x0, y0, x1, y1 in rr:
        m[y0 - oy:y1 - oy, x0 - ox:x1 - ox] = True
    lab, _ = ndimage.label(m)
    for nm in ('VDD', 'VSS'):
        lx, ly = (int(round(v / G)) for v in pins[nm])
        # the label may sit on a via (a hole in R2 here): take the shape that
        # fills most of a small window around it
        k = int(0.3 / G)
        win = lab[max(ly - oy - k, 0):ly - oy + k, max(lx - ox - k, 0):lx - ox + k]
        ids, cnt = np.unique(win[win > 0], return_counts=True)
        assert len(ids), f'{name} {nm} label not on R2'
        comp = lab == ids[np.argmax(cnt)]
        rows = np.nonzero(comp.any(axis=1))[0]
        i = rows[-1] if nm == 'VDD' else rows[0]              # top / bottom row of the shape
        cols = np.nonzero(comp[i])[0]
        run = np.split(cols, np.nonzero(np.diff(cols) > 1)[0] + 1)[0]   # its first flat stretch
        xm = (ox + run[len(run) // 2]) * G
        ym = (oy + i + (1 if nm == 'VDD' else 0)) * G
        band = 0.25                                  # start the stub this far inside the band
        pins[nm] = (snap(xm), snap(ym - band if nm == 'VDD' else ym + band))
    return dict(bbox=bb, pins=pins)


# ------------------------------------------------------------------ router
class Router:
    """two-layer grid maze router (A*); layer 0 = R3 (horizontal), 1 = R4 (vertical)"""

    def __init__(self, x0, y0, nx, ny, pitch):
        self.x0, self.y0, self.nx, self.ny, self.p = x0, y0, nx, ny, pitch
        self.occ = np.full((2, nx, ny), -1, int)     # -1 free, -2 blocked, else net id

    def xy(self, i, j):
        return snap(self.x0 + i * self.p), snap(self.y0 + j * self.p)

    def ij(self, x, y):
        return int(round((x - self.x0) / self.p)), int(round((y - self.y0) / self.p))

    def block_rect(self, layer, x0, x1, y0, y1):
        i0, j0 = self.ij(x0, y0)
        i1, j1 = self.ij(x1, y1)
        for i in range(max(i0, 0), min(i1, self.nx - 1) + 1):
            for j in range(max(j0, 0), min(j1, self.ny - 1) + 1):
                x, y = self.xy(i, j)
                if x0 <= x <= x1 and y0 <= y <= y1 and self.occ[layer, i, j] == -1:
                    self.occ[layer, i, j] = -2

    def route(self, nid, src_set, dst):
        """A* from node dst (layer 0) to any node in src_set (the net's tree)"""
        tgt = np.array([[n[1], n[2]] for n in src_set])
        def h(i, j):
            return int(np.min(np.abs(tgt[:, 0] - i) + np.abs(tgt[:, 1] - j)))
        start = dst
        dist = {start: 0}
        prev = {}
        pq = [(h(start[1], start[2]), 0, start)]
        while pq:
            f, d, u = heapq.heappop(pq)
            if u in src_set:
                path = [u]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                return path[::-1]
            if d > dist.get(u, 1e18):
                continue
            l, i, j = u
            nbrs = []
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ii, jj = i + di, j + dj
                if 0 <= ii < self.nx and 0 <= jj < self.ny:
                    pref = (l == 0 and dj == 0) or (l == 1 and di == 0)
                    nbrs.append(((l, ii, jj), 1 if pref else 6))
            nbrs.append(((1 - l, i, j), 4))
            for v, c in nbrs:
                o = self.occ[v]
                if o != -1 and o != nid:
                    continue
                nd = d + c
                if nd < dist.get(v, 1e18):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd + h(v[1], v[2]), nd, v))
        return None


# ------------------------------------------------------------------ build
def build(pdk):
    U = UP[pdk]
    p = U['pitch']
    info = {n: cell_info(pdk, n) for n in set(ROW)}
    gx = 0.6                       # gap between cell bboxes in a row
    rects = {k: [] for k in ('r2', 'v23', 'r3', 'v34', 'r4')}
    insts = []                     # (cell, instname, dx, dy)
    nets = {}                      # net -> list of pin nodes (grid)
    pstubs = []                    # power stubs: (net, x, y_label, rail_y)

    # --- rows: centre lines on the grid, rails on the grid
    tops = {n: info[n]['pins']['VDD'][1] for n in info}
    bots = {n: info[n]['pins']['VSS'][1] for n in info}
    up = np.ceil((max(tops.values()) + 1.2) / p) * p          # rail offset from row centre
    dn = np.ceil((-min(bots.values()) + 1.2) / p) * p
    row_pitch = np.ceil((up + dn + U['rail_w'] + 2.0) / p) * p
    x_cells = 8 * p                 # left edge of the cells (room for straps + inputs)
    rows = []
    for r in range(4):
        yc = snap(dn + U['rail_w'] / 2 + 2 * p + r * row_pitch)
        yc = snap(round(yc / p) * p)
        x = x_cells
        row = []
        for k, cn in enumerate(ROW):
            bb = info[cn]['bbox']
            dx = snap(x - bb[0])
            insts.append((cn, f'{cn}_{r}_{k}', dx, yc))
            row.append((cn, dx))
            x += (bb[2] - bb[0]) + gx
        rows.append(dict(yc=yc, vdd=snap(yc + up), vss=snap(yc - dn), cells=row, x_end=x))
    x_end = max(r['x_end'] for r in rows)
    x_left = 0.0
    x_right = snap(np.ceil((x_end + 8 * p) / p) * p)
    y_top = snap(rows[-1]['vdd'] + U['rail_w'] / 2 + 2 * p)
    y_bot = 0.0

    rt = Router(x_left, y_bot, int(round((x_right - x_left) / p)) + 1,
                int(round((y_top - y_bot) / p)) + 1, p)

    # --- power: rails (R3), straps (R4), stubs from each cell's outline
    vdd_x, vss_x = snap(2 * p), snap(x_right - 2 * p)
    pad34 = U['v34_w'] + 2 * max(U['v34_sur3'], U['v34_sur4'])
    keep = U['sp'] + pad34 / 2
    for r in rows:
        for nm in ('vdd', 'vss'):
            y = r[nm]
            rects['r3'].append((vdd_x - U['strap_w'] / 2, vss_x + U['strap_w'] / 2,
                                y - U['rail_w'] / 2, y + U['rail_w'] / 2))
            rt.block_rect(0, x_left, x_right, y - U['rail_w'] / 2 - keep, y + U['rail_w'] / 2 + keep)
            xs = vdd_x if nm == 'vdd' else vss_x
            for ox in (-0.3, 0.3):                     # 2 x 2 vias per rail/strap crossing
                for oy in (-0.3, 0.3):
                    h = U['v34_w'] / 2
                    rects['v34'].append((xs + ox - h, xs + ox + h, y + oy - h, y + oy + h))
    for xs in (vdd_x, vss_x):
        rects['r4'].append((xs - U['strap_w'] / 2, xs + U['strap_w'] / 2,
                            rows[0]['vss'] - U['rail_w'] / 2, rows[-1]['vdd'] + U['rail_w'] / 2))
        rt.block_rect(1, xs - U['strap_w'] / 2 - keep, xs + U['strap_w'] / 2 + keep, y_bot, y_top)

    sw2 = max(U['v23_w'] + 2 * U['v23_sur2'], U['stub_w'])   # R2 stub width = cell pin pad
    pad3 = U['v23_w'] + 2 * U['v23_sur3']
    for r in rows:
        for cn, dx in r['cells']:
            pins = info[cn]['pins']
            for pn, rail in (('VDD', r['vdd']), ('VSS', r['vss'])):
                x, y = snap(pins[pn][0] + dx), snap(pins[pn][1] + r['yc'])
                y0, y1 = sorted((y, rail))
                rects['r2'].append((x - sw2 / 2, x + sw2 / 2, y0 - sw2 / 2, y1 + sw2 / 2))
                h = U['v23_w'] / 2
                rects['v23'].append((x - h, x + h, rail - h, rail + h))

    # --- signal pins: R2 stub out to a grid node, via up to R3
    def pin_node(x, y, side):
        minlen = sw2 / 2 + U['v23_w'] / 2 + 0.25
        if side == 'L':
            i = int(np.floor((x - minlen - rt.x0) / p))
        else:
            i = int(np.ceil((x + minlen - rt.x0) / p))
        j = int(round((y - rt.y0) / p))
        nxp, nyp = rt.xy(i, j)
        # R2: horizontal from the pin, then vertical to the node's y
        rects['r2'].append((min(x, nxp) - sw2 / 2, max(x, nxp) + sw2 / 2, y - sw2 / 2, y + sw2 / 2))
        rects['r2'].append((nxp - sw2 / 2, nxp + sw2 / 2, min(y, nyp) - sw2 / 2, max(y, nyp) + sw2 / 2))
        h = U['v23_w'] / 2
        rects['v23'].append((nxp - h, nxp + h, nyp - h, nyp + h))
        rects['r3'].append((nxp - pad3 / 2, nxp + pad3 / 2, nyp - pad3 / 2, nyp + pad3 / 2))
        return (0, i, j)

    conn = []
    for b, r in enumerate(rows):
        c_in = 'Cin' if b == 0 else f'c{b}'
        c_out = 'Cout' if b == 3 else f'c{b + 1}'
        pinmap = [dict(A=f'A{b}', B=f'B{b}', Y=f'x{b}'), dict(A=f'A{b}', B=f'B{b}', Y=f'g{b}'),
                  dict(A=f'x{b}', B=c_in, Y=f'S{b}'), dict(A=f'x{b}', B=c_in, Y=f't{b}'),
                  dict(A=f'g{b}', B=f't{b}', Y=c_out)]
        for k, ((cn, dx), pm) in enumerate(zip(r['cells'], pinmap)):
            conn.append((cn, f'{cn}_{b}_{k}', pm))
            pins = info[cn]['pins']
            for pn, net in pm.items():
                x, y = pins[pn][0] + dx, pins[pn][1] + r['yc']
                node = pin_node(x, y, 'R' if pn == 'Y' else 'L')
                nets.setdefault(net, []).append(node)
    # top-level terminals on the left / right edges
    terms = {}
    x_tin = snap(5 * p)
    x_tout = snap(x_right - 5 * p)
    for b, r in enumerate(rows):
        a_y = nets[f'A{b}'][0]
        b_y = nets[f'B{b}'][0]
        terms[f'A{b}'] = (0, rt.ij(x_tin, 0)[0], a_y[2])
        terms[f'B{b}'] = (0, rt.ij(x_tin, 0)[0], b_y[2])
        s = nets[f'S{b}'][0]
        terms[f'S{b}'] = (0, rt.ij(x_tout, 0)[0], s[2])
    terms['Cin'] = (0, rt.ij(x_tin, 0)[0], rt.ij(0, rows[0]['yc'])[1])
    terms['Cout'] = (0, rt.ij(x_tout, 0)[0], terms['S3'][2] + 3)
    for nm, t in terms.items():
        nets[nm].insert(0, t)

    # reserve every pin node for its net
    ids = {n: k for k, n in enumerate(sorted(nets))}
    for n, nodes in nets.items():
        for nd in nodes:
            assert rt.occ[nd] in (-1, ids[n]), f'pin node clash {n} {nd}'
            rt.occ[nd] = ids[n]

    # route: nets with the largest span first
    def span(n):
        pts = np.array([[a[1], a[2]] for a in nets[n]])
        return np.ptp(pts[:, 0]) + np.ptp(pts[:, 1])
    order = sorted(nets, key=span, reverse=True)
    paths = {}
    for n in order:
        nid = ids[n]
        tree = {nets[n][0]}
        segs = []
        rest = sorted(nets[n][1:], key=lambda a: abs(a[1] - nets[n][0][1]) + abs(a[2] - nets[n][0][2]))
        for dst in rest:
            if dst in tree:
                continue
            path = rt.route(nid, tree, dst)
            if path is None:
                raise RuntimeError(f'cannot route {n}')
            for nd in path:
                rt.occ[nd] = nid
                tree.add(nd)
            segs.append(path)
        paths[n] = segs

    # --- draw routes
    w = {0: U['w3'], 1: U['w4']}
    lk = {0: 'r3', 1: 'r4'}
    for n, segs in paths.items():
        for path in segs:
            for a, b in zip(path, path[1:]):
                xa, ya = rt.xy(a[1], a[2])
                xb, yb = rt.xy(b[1], b[2])
                if a[0] != b[0]:
                    h = U['v34_w'] / 2
                    rects['v34'].append((xa - h, xa + h, ya - h, ya + h))
                    rects['r3'].append((xa - pad34 / 2, xa + pad34 / 2, ya - pad34 / 2, ya + pad34 / 2))
                    rects['r4'].append((xa - pad34 / 2, xa + pad34 / 2, ya - pad34 / 2, ya + pad34 / 2))
                    continue
                hw = w[a[0]] / 2
                rects[lk[a[0]]].append((min(xa, xb) - hw, max(xa, xb) + hw,
                                        min(ya, yb) - hw, max(ya, yb) + hw))
    # terminal pads (R3) for the top-level ports
    labels = []
    for nm in ['A0', 'A1', 'A2', 'A3', 'B0', 'B1', 'B2', 'B3', 'Cin',
               'S0', 'S1', 'S2', 'S3', 'Cout']:
        l, i, j = terms[nm]
        x, y = rt.xy(i, j)
        rects['r3'].append((x - pad3 / 2, x + pad3 / 2, y - pad3 / 2, y + pad3 / 2))
        labels.append((nm, U['r3'], (x - 0.1, x + 0.1, y - 0.1, y + 0.1)))
    ym = (rows[0]['vss'] + rows[-1]['vdd']) / 2
    labels.append(('VDD', U['r4'], (vdd_x - 0.2, vdd_x + 0.2, ym - 0.2, ym + 0.2)))
    labels.append(('VSS', U['r4'], (vss_x - 0.2, vss_x + 0.2, ym - 0.2, ym + 0.2)))
    bbox = (x_left, y_bot, x_right, y_top)
    return dict(rects=rects, insts=insts, labels=labels, conn=conn, info=info, bbox=bbox,
                rows=rows, nets=nets, paths=paths)


# ------------------------------------------------------------------ writers
def write_mag(fn, pdk, L, U):
    from_root = os.path.relpath(os.path.join(ROOT, pdk), os.path.dirname(fn))
    tech = {'sky130A': ('sky130A', '1 2'), 'gf180mcuD': ('gf180mcuD', '1 10')}[pdk]
    c = lambda v: int(round(v / G))
    with open(fn, 'w') as f:
        f.write(f"magic\ntech {tech[0]}\nmagscale {tech[1]}\ntimestamp {int(time.time())}\n")
        for key in ('r2', 'v23', 'r3', 'v34', 'r4'):
            if not L['rects'][key]:
                continue
            f.write(f"<< {U[key]} >>\n")
            for (x0, x1, y0, y1) in L['rects'][key]:
                f.write(f"rect {c(x0)} {c(y0)} {c(x1)} {c(y1)}\n")
        for cn, inst, dx, dy in L['insts']:
            bb = L['info'][cn]['bbox']
            f.write(f"use {cn}  {inst} {from_root}\ntimestamp 0\n"
                    f"transform 1 0 {c(dx)} 0 1 {c(dy)}\n"
                    f"box {c(bb[0])} {c(bb[1])} {c(bb[2])} {c(bb[3])}\n")
        f.write("<< labels >>\n")
        for k, (nm, lay, (x0, x1, y0, y1)) in enumerate(L['labels']):
            f.write(f"rlabel {lay} {c(x0)} {c(y0)} {c(x1)} {c(y1)} 0 {nm}\nport {k + 1} nsew\n")
        x0, y0, x1, y1 = L['bbox']
        f.write(f"<< properties >>\nstring FIXED_BBOX {c(x0)} {c(y0)} {c(x1)} {c(y1)}\n<< end >>\n")


def write_ref(fn, pdk, L):
    ports = 'A0 A1 A2 A3 B0 B1 B2 B3 Cin S0 S1 S2 S3 Cout VDD VSS'
    out = [f'* ADD4 reference ({pdk})']
    for cn in sorted(set(ROW)):
        out.append(open(os.path.join(ROOT, pdk, f'{cn}_ref.spice')).read())
    out.append(f'.subckt ADD4 {ports}')
    for cn, inst, pm in L['conn']:
        out.append(f"X{inst} {pm['A']} {pm['B']} {pm['Y']} VDD VSS {cn}")
    out.append('.ends')
    open(fn, 'w').write('\n'.join(out) + '\n')


def preview(fn, pdk, L, U):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    st = 6
    x0, y0, x1, y1 = L['bbox']
    nx, ny = int((x1 - x0) / G / st) + 1, int((y1 - y0) / G / st) + 1
    img = np.ones((ny, nx, 3))
    cols = [('NW', (.75, .75, .55), .35), ('pdiff', (.95, .6, .2), .85), ('ndiff', (.2, .75, .25), .85),
            ('poly', (.85, .1, .1), .85), ('R1', (.45, .45, 1.0), .45), ('R2', (.55, .25, .75), .45)]
    for cn, inst, dx, dy in L['insts']:
        d = np.load(os.path.join(ROOT, pdk, f'{cn}_masks.npz'))
        cx0, cy0 = float(d['x0']) + dx, float(d['y0']) + dy
        j0, i0 = int(round((cx0 - x0) / G / st)), int(round((cy0 - y0) / G / st))
        for k, col, a in cols:
            m = d[k][::st, ::st]
            sub = img[i0:i0 + m.shape[0], j0:j0 + m.shape[1]]
            mm = m[:sub.shape[0], :sub.shape[1]][..., None]
            img[i0:i0 + m.shape[0], j0:j0 + m.shape[1]] = np.where(mm, sub * (1 - a) + np.array(col) * a, sub)
    fig, ax = plt.subplots(figsize=(14, 14 * ny / nx + 0.5))
    ax.imshow(img, origin='lower', extent=[x0, x1, y0, y1], interpolation='nearest')
    for key, col, a in (('r2', (.55, .25, .75), .6), ('r3', (0, .6, .7), .55), ('r4', (.9, .55, 0), .5)):
        for (a0, a1, b0, b1) in L['rects'][key]:
            ax.add_patch(plt.Rectangle((a0, b0), a1 - a0, b1 - b0, color=col, alpha=a, lw=0))
    for nm, lay, (a0, a1, b0, b1) in L['labels']:
        ax.text((a0 + a1) / 2, (b0 + b1) / 2, nm, fontsize=7, ha='center', va='center',
                bbox=dict(fc='w', ec='none', alpha=.7, pad=1))
    ax.set_title(f'{os.path.basename(fn).split("_preview")[0]} ({pdk})   cyan = {U["r3"]} (horizontal), orange = {U["r4"]} (vertical)', fontsize=9)
    ax.set_xlabel('um')
    plt.tight_layout()
    plt.savefig(fn, dpi=110)
    plt.close()


def main():
    pdk = sys.argv[1]
    U = UP[pdk]
    out = os.path.join(HERE, pdk)
    os.makedirs(out, exist_ok=True)
    L = build(pdk)
    write_mag(os.path.join(out, 'ADD4.mag'), pdk, L, U)
    write_ref(os.path.join(out, 'ADD4_ref.spice'), pdk, L)
    preview(os.path.join(out, 'ADD4_preview.png'), pdk, L, U)
    x0, y0, x1, y1 = L['bbox']
    print(f'{pdk} ADD4 {x1 - x0:.1f} x {y1 - y0:.1f} um = {(x1 - x0) * (y1 - y0):.0f} um2, '
          f'{len(L["insts"])} cells, {len(L["paths"])} routed nets')


if __name__ == '__main__':
    main()
