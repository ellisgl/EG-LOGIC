#!/usr/bin/env python3
"""
Example: 74181 4-bit ALU built from the EG-LOGIC symbol cells.

The 70-cell netlist (alu181_netlist.py) is placed in order, left to right,
in rows no wider than ROW_W, then routed over the cells with the same
two-layer maze router, rails and straps as the ADD4 example.

usage: python3 make_alu181.py <pdk>  -> <pdk>/ALU181.mag, ALU181_ref.spice, ALU181_preview.png
"""
import os
import random
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'examples', 'adder4'))
from make_adder4 import UP, cell_info, Router, snap, write_mag, preview  # noqa: E402
from alu181_netlist import gates, INPUTS, OUTPUTS                        # noqa: E402

ROW_W = {'sky130A': 150.0, 'gf180mcuD': 190.0}     # max row width (cells only)
TOP = 'ALU181'


def build(pdk, seed=0):
    U = UP[pdk]
    p = U['pitch']
    G = gates()
    info = {n: cell_info(pdk, n) for n in set(c for c, *_ in G)}
    gx = 0.6
    rects = {k: [] for k in ('r2', 'v23', 'r3', 'v34', 'r4')}

    # --- rows
    up = np.ceil((max(i['pins']['VDD'][1] for i in info.values()) + 1.2) / p) * p
    dn = np.ceil((-min(i['pins']['VSS'][1] for i in info.values()) + 1.2) / p) * p
    row_pitch = np.ceil((up + dn + U['rail_w'] + 1.4) / p) * p
    x_cells = 8 * p
    rows, cur = [], []
    w = 0.0
    for gt in G:
        bb = info[gt[0]]['bbox']
        cw = bb[2] - bb[0]
        if cur and w + cw > ROW_W[pdk]:
            rows.append(cur)
            cur, w = [], 0.0
        cur.append(gt)
        w += cw + gx
    rows.append(cur)
    R = []
    for r, row in enumerate(rows):
        yc = snap(round((dn + U['rail_w'] / 2 + 2 * p + r * row_pitch) / p) * p)
        x = x_cells
        cells = []
        for gt in row:
            bb = info[gt[0]]['bbox']
            dx = snap(x - bb[0])
            cells.append((gt, dx))
            x += (bb[2] - bb[0]) + gx
        R.append(dict(yc=yc, vdd=snap(yc + up), vss=snap(yc - dn), cells=cells, x_end=x))
    x_end = max(r['x_end'] for r in R)
    x_right = snap(np.ceil((x_end + 8 * p) / p) * p)
    y_top = snap(R[-1]['vdd'] + U['rail_w'] / 2 + 2 * p)
    rt = Router(0.0, 0.0, int(round(x_right / p)) + 1, int(round(y_top / p)) + 1, p)

    # --- power
    vdd_x, vss_x = snap(2 * p), snap(x_right - 2 * p)
    pad34 = U['v34_w'] + 2 * max(U['v34_sur3'], U['v34_sur4'])
    keep = U['sp'] + pad34 / 2
    for r in R:
        for nm in ('vdd', 'vss'):
            y = r[nm]
            rects['r3'].append((vdd_x - U['strap_w'] / 2, vss_x + U['strap_w'] / 2,
                                y - U['rail_w'] / 2, y + U['rail_w'] / 2))
            rt.block_rect(0, 0, x_right, y - U['rail_w'] / 2 - keep, y + U['rail_w'] / 2 + keep)
            xs = vdd_x if nm == 'vdd' else vss_x
            for ox in (-0.3, 0.3):
                for oy in (-0.3, 0.3):
                    h = U['v34_w'] / 2
                    rects['v34'].append((xs + ox - h, xs + ox + h, y + oy - h, y + oy + h))
    for xs in (vdd_x, vss_x):
        rects['r4'].append((xs - U['strap_w'] / 2, xs + U['strap_w'] / 2,
                            R[0]['vss'] - U['rail_w'] / 2, R[-1]['vdd'] + U['rail_w'] / 2))
        rt.block_rect(1, xs - U['strap_w'] / 2 - keep, xs + U['strap_w'] / 2 + keep, 0, y_top)

    sw2 = max(U['v23_w'] + 2 * U['v23_sur2'], U['stub_w'])
    pad3 = U['v23_w'] + 2 * U['v23_sur3']
    h23 = U['v23_w'] / 2
    for r in R:
        for (gt, dx) in r['cells']:
            pins = info[gt[0]]['pins']
            for pn, rail in (('VDD', r['vdd']), ('VSS', r['vss'])):
                x, y = snap(pins[pn][0] + dx), snap(pins[pn][1] + r['yc'])
                y0, y1 = sorted((y, rail))
                rects['r2'].append((x - sw2 / 2, x + sw2 / 2, y0 - sw2 / 2, y1 + sw2 / 2))
                rects['v23'].append((x - h23, x + h23, rail - h23, rail + h23))

    # --- signal pins
    stubs = []
    def pin_node(x, y, side):
        minlen = sw2 / 2 + U['v23_w'] / 2 + 0.25
        i = int(np.floor((x - minlen) / p)) if side == 'L' else int(np.ceil((x + minlen) / p))
        j = int(round(y / p))
        stubs.append((x, y, i, j))
        return (0, i, j)

    nets = {}
    conn = []
    for r in R:
        for (gt, dx) in r['cells']:
            cell, inst, a, b, yn = gt
            pins = info[cell]['pins']
            pm = {'A': a, 'Y': yn}
            if b:
                pm['B'] = b
            conn.append((cell, inst, pm))
            for pn, net in pm.items():
                x, y = pins[pn][0] + dx, pins[pn][1] + r['yc']
                nets.setdefault(net, []).append(pin_node(x, y, 'R' if pn == 'Y' else 'L'))

    # --- edge terminals: inputs left, outputs right, on free grid rows
    used = set(nd for v in nets.values() for nd in v)
    terms = {}
    for names, xcol in ((INPUTS, 5 * p), (OUTPUTS, x_right - 5 * p)):
        i = int(round(xcol / p))
        for nm in names:
            jt = nets[nm][0][2]
            for d in sorted(range(-rt.ny, rt.ny), key=abs):
                j = jt + d
                if 0 <= j < rt.ny and rt.occ[0, i, j] == -1 and (0, i, j) not in used \
                        and all(abs(j - t[2]) >= 2 or t[1] != i for t in terms.values()):
                    terms[nm] = (0, i, j)
                    used.add(terms[nm])
                    break
            nets[nm].insert(0, terms[nm])

    ids = {n: k for k, n in enumerate(sorted(nets))}
    base = rt.occ.copy()
    for n, nodes in nets.items():
        for nd in nodes:
            assert base[nd] in (-1, ids[n]), f'pin node clash {n} {nd}'
            base[nd] = ids[n]

    # --- route, retrying with shuffled net order on failure
    def span(n):
        a = np.array([[q[1], q[2]] for q in nets[n]])
        return np.ptp(a[:, 0]) + np.ptp(a[:, 1])
    order = sorted(nets, key=span, reverse=True)
    rng = random.Random(seed)
    for attempt in range(20):
        rt.occ = base.copy()
        paths, failed = {}, None
        for n in order:
            nid = ids[n]
            tree = {nets[n][0]}
            segs = []
            rest = sorted(nets[n][1:], key=lambda q: abs(q[1] - nets[n][0][1]) + abs(q[2] - nets[n][0][2]))
            for dst in rest:
                if dst in tree:
                    continue
                path = rt.route(nid, tree, dst)
                if path is None:
                    failed = n
                    break
                for nd in path:
                    rt.occ[nd] = nid
                    tree.add(nd)
                segs.append(path)
            if failed:
                break
            paths[n] = segs
        if not failed:
            break
        print(f'  attempt {attempt}: {failed} unroutable, retrying')
        order.remove(failed)
        order.insert(0, failed)
        if attempt > 3:
            rng.shuffle(order)
    else:
        raise RuntimeError('routing failed')

    # --- draw stubs and routes
    for (x, y, i, j) in stubs:
        nxp, nyp = rt.xy(i, j)
        rects['r2'].append((min(x, nxp) - sw2 / 2, max(x, nxp) + sw2 / 2, y - sw2 / 2, y + sw2 / 2))
        rects['r2'].append((nxp - sw2 / 2, nxp + sw2 / 2, min(y, nyp) - sw2 / 2, max(y, nyp) + sw2 / 2))
        rects['v23'].append((nxp - h23, nxp + h23, nyp - h23, nyp + h23))
        rects['r3'].append((nxp - pad3 / 2, nxp + pad3 / 2, nyp - pad3 / 2, nyp + pad3 / 2))
    wd = {0: U['w3'], 1: U['w4']}
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
                hw = wd[a[0]] / 2
                rects[lk[a[0]]].append((min(xa, xb) - hw, max(xa, xb) + hw, min(ya, yb) - hw, max(ya, yb) + hw))
    labels = []
    for nm in INPUTS + OUTPUTS:
        _, i, j = terms[nm]
        x, y = rt.xy(i, j)
        rects['r3'].append((x - pad3 / 2, x + pad3 / 2, y - pad3 / 2, y + pad3 / 2))
        labels.append((nm, U['r3'], (x - 0.1, x + 0.1, y - 0.1, y + 0.1)))
    ym = (R[0]['vss'] + R[-1]['vdd']) / 2
    labels.append(('VDD', U['r4'], (vdd_x - 0.2, vdd_x + 0.2, ym - 0.2, ym + 0.2)))
    labels.append(('VSS', U['r4'], (vss_x - 0.2, vss_x + 0.2, ym - 0.2, ym + 0.2)))
    insts = [(gt[0], f'{gt[0]}_{gt[1]}', dx, r['yc']) for r in R for (gt, dx) in r['cells']]
    return dict(rects=rects, insts=insts, labels=labels, conn=conn, info=info,
                bbox=(0.0, 0.0, x_right, y_top), rows=R, paths=paths)


def write_ref(fn, pdk, L):
    out = [f'* {TOP} reference ({pdk})']
    for cn in sorted(set(c for c, _, _ in L['conn'])):
        out.append(open(os.path.join(ROOT, pdk, f'{cn}_ref.spice')).read())
    out.append(f".subckt {TOP} {' '.join(INPUTS + OUTPUTS)} VDD VSS")
    for cn, inst, pm in L['conn']:
        ins = [pm['A']] + ([pm['B']] if 'B' in pm else [])
        out.append(f"X{cn}_{inst} {' '.join(ins)} {pm['Y']} VDD VSS {cn}")
    out.append('.ends')
    open(fn, 'w').write('\n'.join(out) + '\n')


def main():
    pdk = sys.argv[1]
    U = UP[pdk]
    out = os.path.join(HERE, pdk)
    os.makedirs(out, exist_ok=True)
    L = build(pdk)
    write_mag(os.path.join(out, f'{TOP}.mag'), pdk, L, U)
    write_ref(os.path.join(out, f'{TOP}_ref.spice'), pdk, L)
    preview(os.path.join(out, f'{TOP}_preview.png'), pdk, L, U)
    x0, y0, x1, y1 = L['bbox']
    print(f'{pdk} {TOP} {x1 - x0:.1f} x {y1 - y0:.1f} um = {(x1 - x0) * (y1 - y0):.0f} um2, '
          f'{len(L["insts"])} cells in {len(L["rows"])} rows, {len(L["paths"])} routed nets')


if __name__ == '__main__':
    main()
