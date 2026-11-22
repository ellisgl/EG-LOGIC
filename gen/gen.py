#!/usr/bin/env python3
"""
EG-LOGIC generator: CMOS logic gates for Magic whose layout is drawn as the
ANSI / IEEE 91 distinctive-shape symbol.

  outline of the symbol  = tap diffusion + R1 + R2 stacked in one band.
                           Top half: N-tap in the N-well, VDD.
                           Bottom half: P-tap, VSS. It is the supply rail and
                           the guard ring.
  N-well                 = top half of the symbol shape
  input lines            = poly. They pass under the outline and turn straight
                           into the transistor gates (A from the top, B from
                           the bottom, single inputs on the centre line)
  output line + bubble   = R1 on the centre line, out through the tip; the
                           bubble is an R1+R2 ring
  XOR's extra back arc   = R1+R2 arc (floating)

Usage: python3 gen.py <pdk> [cell ...]      pdk: gf180mcuD | sky130A
Writes <pdk>/<CELL>.mag, <CELL>_ref.spice, <CELL>_preview.png
"""
import os
import sys
import time
import numpy as np
from scipy import ndimage

from rules import PDKS, derived
from cells import CELLS, ORDER

G = 0.005          # raster grid = Magic internal unit (um)
BIG = 1000.0


def snap(v):
    return round(round(v / G) * G, 4)


def snap_up(v):
    return round(np.ceil(v / G - 1e-6) * G, 4)


# =============================================================== core
class Core:
    """transistor core in its own coordinates (x from 0, y = 0 on the centre line)"""

    def __init__(self, cell, R, D):
        self.R, self.D, self.cell = R, D, cell
        self.r = {k: [] for k in ('pdiff', 'ndiff', 'poly', 'pc', 'pc_pad', 'pdc', 'ndc',
                                  'r1', 'r1_up', 'r1_dn', 'lead_A', 'lead_B', 'out')}
        self.build()

    def build(self):
        R, D, cell = self.R, self.D, self.cell
        inputs = cell['inputs']
        single = len(inputs) == 1
        tracks = cell['track']
        three = any(abs(t) == 1 for t in tracks.values())
        tp = D['tp']
        ty = {0: 0.0, 1: tp, -1: -tp}
        hh = max(D['track_w'], D['pc_r1']) / 2
        top_t = tp if three else 0.0
        cds, ct = R['ct_diff_sur'], R['ct']
        # P/N gap
        g_p = max(R['nw_pdiff_sur'],
                  top_t + hh + R['r1_sp'] + R['r1_ct_ext'] - cds,
                  top_t + D['pc_pad'] / 2 + R['pc_pdiff_sp'],
                  R['L'] / 2 + R['poly_diff_sp'])
        g_n = max(R['nw_ndiff_sp'],
                  top_t + hh + R['r1_sp'] + R['r1_ct_ext'] - cds,
                  top_t + D['pc_pad'] / 2 + R['pc_ndiff_sp'],
                  R['L'] / 2 + R['poly_diff_sp'])
        g_p, g_n = snap_up(g_p), snap_up(g_n)
        Wp, Wn, L = R['Wp'], R['Wn'], R['L']
        self.g_p, self.g_n = g_p, g_n
        p_y = (g_p, g_p + Wp)
        n_y = (-g_n - Wn, -g_n)
        y_A = snap_up(p_y[1] + R['endcap'] + R['poly_sp'] + L / 2)
        y_B = -snap_up(-n_y[0] + R['endcap'] + R['poly_sp'] + L / 2)
        y_A = max(y_A, -y_B)
        y_B = -y_A
        self.y_A, self.y_B = (y_A, y_B) if not single else (0.0, None)

        def ct_ys(y0, y1):
            n = int((y1 - y0 - 2 * cds + R['ct_sp']) // D['ct_pitch'] + 1e-9)
            n = max(n, 1)
            span = n * ct + (n - 1) * R['ct_sp']
            s = snap(y0 + (y1 - y0 - span) / 2)
            return [snap(s + k * D['ct_pitch']) for k in range(n)]

        segs = {}         # (net, track) -> [xmin, xmax]

        def seg_add(net, t, x0, x1):
            k = (net, t)
            if k in segs:
                segs[k] = [min(segs[k][0], x0), max(segs[k][1], x1)]
            else:
                segs[k] = [x0, x1]

        x = 0.0
        colA, colB, y_straps = [], [], []
        self.x_left = 0.0
        for isl in cell['islands']:
            g, p, n = isl['g'], isl['p'], isl['n']
            assert len(p) == len(g) + 1 and len(n) == len(g) + 1
            assert p[0] and p[-1] and n[0] and n[-1], 'island ends must be contacted'
            is_pc = [gg not in inputs for gg in g]
            dG = [D['d_wide'] if pc else D['d_norm'] for pc in is_pc]
            xs = [snap(x + cds + ct / 2)]
            xg = []
            for i in range(len(g)):
                if i == 0:
                    xg.append(snap(xs[0] + dG[0]))
                    continue
                contacted = p[i] is not None or n[i] is not None
                if contacted:
                    xs.append(snap(xg[-1] + dG[i - 1]))
                    xg.append(snap(xs[-1] + dG[i]))
                else:
                    step = D['g_plain']
                    if is_pc[i - 1] or is_pc[i]:
                        step = max(step, D['g_pad'])
                    xs.append(snap(xg[-1] + step / 2))
                    xg.append(snap(xg[-1] + step))
            xs.append(snap(xg[-1] + dG[-1]))
            xr = snap(xs[-1] + ct / 2 + cds)
            self.r['pdiff'].append((x, xr, *p_y))
            self.r['ndiff'].append((x, xr, *n_y))
            # gates
            for gg, xc, pc in zip(g, xg, is_pc):
                top = p_y[1] + R['endcap']
                bot = n_y[0] - R['endcap']
                if gg == 'A' and not single:
                    top = y_A + L / 2
                    colA.append(xc)
                if gg == 'B':
                    bot = y_B - L / 2
                    colB.append(xc)
                if gg == 'A' and single:
                    colA.append(xc)
                self.r['poly'].append((xc - L / 2, xc + L / 2, bot, top))
                if pc:
                    t = tracks[gg]
                    yc = ty[t]
                    h = D['pc_pad'] / 2
                    self.r['pc_pad'].append((xc - h, xc + h, yc - h, yc + h))
                    self.r['pc'].append((snap(xc - ct / 2), snap(xc - ct / 2) + ct,
                                         snap(yc - ct / 2), snap(yc - ct / 2) + ct))
                    h = D['pc_r1'] / 2
                    self.r['r1'].append((xc - h, xc + h, yc - h, yc + h))
                    seg_add(gg, t, xc - h, xc + h)
            # diffusion contacts + straps
            sw = D['strap_w'] / 2
            for side, nets, (y0, y1), ctl in (('p', p, p_y, 'pdc'), ('n', n, n_y, 'ndc')):
                cys = ct_ys(y0, y1)
                for net, xc in zip(nets, xs):
                    if net is None:
                        continue
                    for cy in cys:
                        cx0 = snap(xc - ct / 2)
                        self.r[ctl].append((cx0, cx0 + ct, cy, cy + ct))
                    s0 = cys[0] - R['r1_ct_ext']
                    s1 = cys[-1] + ct + R['r1_ct_ext']
                    self.r['r1'].append((xc - sw, xc + sw, s0, s1))
                    if net == 'VDD':
                        assert side == 'p'
                        self.r['r1_up'].append((xc - sw, xc + sw, s1 - 0.01, BIG))
                    elif net == 'VSS':
                        assert side == 'n'
                        self.r['r1_dn'].append((xc - sw, xc + sw, -BIG, s0 + 0.01))
                    else:
                        t = tracks[net]
                        tw = D['track_w'] / 2
                        if side == 'p':
                            self.r['r1'].append((xc - sw, xc + sw, ty[t] - tw, s0))
                        else:
                            self.r['r1'].append((xc - sw, xc + sw, s1, ty[t] + tw))
                        seg_add(net, t, xc - sw, xc + sw)
                        if net == 'Y':
                            y_straps.append(xc)
            x = snap(xr + R['diff_sp'])
        self.x_right = xr
        # tracks
        for (net, t), (x0, x1) in segs.items():
            tw = D['track_w'] / 2
            self.r['r1'].append((x0, x1, ty[t] - tw, ty[t] + tw))
        # output: from the right-most Y strap, along y = 0, to the right.
        # every Y strap of the right-most slot crosses y = 0 by construction.
        tw = D['track_w'] / 2
        self.x_out0 = max(y_straps)
        self.r['out'].append((self.x_out0 - D['strap_w'] / 2, BIG, -tw, tw))
        # input poly tracks
        if single:
            xa = max(colA)
            self.r['lead_A'].append((-BIG, xa, -L / 2, L / 2))
        else:
            self.r['lead_A'].append((-BIG, max(colA) + L / 2, y_A - L / 2, y_A + L / 2))
            self.r['lead_B'].append((-BIG, max(colB) + L / 2, y_B - L / 2, y_B + L / 2))
        # extents of things that must stay inside the outline
        ys = [r[2] for k in ('poly', 'r1', 'pdiff', 'ndiff') for r in self.r[k]]
        ys += [r[3] for k in ('poly', 'r1', 'pdiff', 'ndiff') for r in self.r[k]]
        self.y_lo, self.y_hi = min(ys), max(ys)

    def keepout(self):
        """rects that must sit inside the outline's inner edge (core coords)"""
        out = []
        for k in ('pdiff', 'ndiff', 'poly', 'pc_pad', 'r1'):
            out += self.r[k]
        x0, x1 = self.x_left, self.x_right
        for k in ('lead_A', 'lead_B'):
            for (a, b, c, d) in self.r[k]:
                out.append((max(a, x0), b, c, d))
        return out


# =============================================================== shapes
def shape_params(kind, H):
    """symbol geometry for height H, back at x = 0 (body), centre y = 0"""
    p = dict(kind=kind, H=H)
    if kind == 'tri':
        p['tip'] = H * np.sqrt(3) / 2
        p['x_back'] = 0.0
    elif kind == 'and':
        p['tip'] = H
        p['x_back'] = 0.0
    elif kind in ('or', 'xor'):
        d = 0.15 * H                                    # depth of the back curve
        Rb = ((H / 2) ** 2 + d ** 2) / (2 * d)
        s = 0.20 * H if kind == 'xor' else 0.0          # body shift behind XOR's extra arc
        p.update(d=d, Rb=Rb, cx=d - Rb, s=s, xs=s + 0.30 * H)
        p['tip'] = p['xs'] + H * np.sqrt(0.75)
        p['x_back'] = 0.0
    return p


def shape_mask(p, X, Y):
    H, kind = p['H'], p['kind']
    h = H / 2
    if kind == 'tri':
        return (X >= 0) & (np.abs(Y) <= h * (1 - X / p['tip']))
    if kind == 'and':
        return (X >= 0) & (np.abs(Y) <= h) & ((X <= h) | ((X - h) ** 2 + Y ** 2 <= h * h))
    # or / xor
    ay = np.minimum(np.abs(Y), h)
    xb = p['s'] + p['cx'] + np.sqrt(p['Rb'] ** 2 - ay ** 2)
    xf = p['xs'] + np.sqrt(np.maximum(H * H - (ay + h) ** 2, 0))
    return (np.abs(Y) <= h) & (X >= xb) & (X <= xf)


def xor_arc_mask(p, X, Y, w):
    """XOR's extra back arc, centre line = the unshifted back curve"""
    r = np.hypot(X - p['cx'], Y)
    return (np.abs(r - p['Rb']) <= w / 2) & (np.abs(Y) <= p['H'] / 2) & (X < p['s'] + p['cx'] + p['Rb'])


def edt_in(m, g):
    return ndimage.distance_transform_edt(m) * g


# =============================================================== fit
def fit(core, kind, R, c_out, frac=0.35):
    """smallest symbol height H whose inner region holds the core; returns
    (H, x_off) with the core placed at x_off"""
    w = R['band_w']
    g = 0.02
    K = core.keepout()

    def feasible(H):
        p = shape_params(kind, H)
        xs = np.arange(-0.5 * H, p['tip'] + 0.5, g) + g / 2
        ys = np.arange(-H / 2 - 0.2, H / 2 + 0.2, g) + g / 2
        Xg, Yg = np.meshgrid(xs, ys)
        S = shape_mask(p, Xg, Yg)
        inner = edt_in(S, g) > w + g
        lo, hi = -np.inf, np.inf
        rows_x0 = np.full(len(ys), np.inf)
        rows_x1 = np.full(len(ys), -np.inf)
        for (a, b, c, d) in K:
            i0 = np.searchsorted(ys, c - c_out - g)
            i1 = np.searchsorted(ys, d + c_out + g)
            rows_x0[i0:i1] = np.minimum(rows_x0[i0:i1], a - c_out)
            rows_x1[i0:i1] = np.maximum(rows_x1[i0:i1], b + c_out)
        for i in np.nonzero(np.isfinite(rows_x0))[0]:
            row = np.nonzero(inner[i])[0]
            if len(row) == 0:
                return None
            ix0, ix1 = xs[row[0]], xs[row[-1]]
            lo = max(lo, ix0 - rows_x0[i] + g)
            hi = min(hi, ix1 - rows_x1[i] - g)
        if lo > hi:
            return None
        return lo + frac * (hi - lo)

    H0 = (core.y_hi - core.y_lo) + 2 * (w + c_out)
    lo, hi = H0, H0 * 4
    while feasible(hi) is None:
        hi *= 1.5
    for _ in range(18):
        mid = (lo + hi) / 2
        if feasible(mid) is None:
            lo = mid
        else:
            hi = mid
    H = np.ceil(hi * 10) / 10          # round up to 0.1 um
    x_off = snap(feasible(H))
    return H, x_off


# =============================================================== raster canvas
class Canvas:
    def __init__(self, x0, x1, y0, y1):
        self.x0, self.y0 = snap(x0), snap(y0)
        self.nx = int(round((x1 - self.x0) / G))
        self.ny = int(round((y1 - self.y0) / G))
        xs = (self.x0 + (np.arange(self.nx) + 0.5) * G).astype(np.float64)
        ys = (self.y0 + (np.arange(self.ny) + 0.5) * G).astype(np.float64)
        self.X, self.Y = np.meshgrid(xs, ys)
        self.xs, self.ys = xs, ys

    def z(self):
        return np.zeros((self.ny, self.nx), bool)

    def ij(self, x, y):
        return int(np.floor((y - self.y0) / G)), int(np.floor((x - self.x0) / G))

    def rect(self, m, x0, x1, y0, y1):
        j0 = max(int(round((x0 - self.x0) / G)), 0)
        j1 = min(int(round((x1 - self.x0) / G)), self.nx)
        i0 = max(int(round((y0 - self.y0) / G)), 0)
        i1 = min(int(round((y1 - self.y0) / G)), self.ny)
        if j1 > j0 and i1 > i0:
            m[i0:i1, j0:j1] = True
        return m

    def rects(self, lst, dx=0.0):
        m = self.z()
        for (a, b, c, d) in lst:
            self.rect(m, a + dx, b + dx, c, d)
        return m


def dil(m, r):
    """Euclidean dilation"""
    if r <= 0:
        return m.copy()
    return ndimage.distance_transform_edt(~m) * G <= r + 1e-9


def ero(m, r):
    return ~dil(~m, r)


def opening(m, r):
    return dil(ero(m, r), r)


def _k(r):
    return max(int(np.ceil(r / G - 1e-9)), 0)


def dil_sq(m, r):
    """Chebyshev (square) dilation: conservative for Magic's edge-based checks"""
    k = _k(r)
    if k == 0:
        return m.copy()
    u = ndimage.maximum_filter1d(m.view(np.uint8), 2 * k + 1, axis=0)
    return ndimage.maximum_filter1d(u, 2 * k + 1, axis=1).astype(bool)


def ero_sq(m, r):
    return ~dil_sq(~m, r)


def _box(m, n, op, second):
    """1-D box filter of exactly n pixels on both axes; `second` uses the
    reflected window so that op pairs form a true opening/closing"""
    if n <= 1:
        return m
    o = -1 if (second and n % 2 == 0) else 0
    f = ndimage.maximum_filter1d if op == 'max' else ndimage.minimum_filter1d
    u = f(m.view(np.uint8), n, axis=0, origin=o)
    return f(u, n, axis=1, origin=o).astype(bool)


def clean(m, w, sp):
    """make a mask pass Magic's width >= w and notch/slit spacing >= sp:
    a square closing of sp fills gaps narrower than sp, a square opening of w
    removes parts narrower than w"""
    nsp = int(np.ceil(sp / G - 1e-6))
    nw = int(np.ceil(w / G - 1e-6))
    m = _box(_box(m, nsp, 'max', False), nsp, 'min', True)
    return _box(_box(m, nw, 'min', False), nw, 'max', True)


def drop_small(m, amin):
    lab, n = ndimage.label(m)
    if n == 0:
        return m
    sizes = ndimage.sum(m, lab, range(1, n + 1)) * G * G
    keep = np.zeros(n + 1, bool)
    keep[1:] = sizes >= amin
    return keep[lab]


def sq_fit(m, half):
    """pixels where an axis-aligned square of half-size `half` centred there fits"""
    k = int(np.ceil(half / G - 1e-9))
    u = m.view(np.uint8)
    u = ndimage.minimum_filter1d(u, 2 * k + 1, axis=0)
    u = ndimage.minimum_filter1d(u, 2 * k + 1, axis=1)
    return u.astype(bool)


def place_squares(cv, ok, pts, size, pitch, avoid=None):
    """greedy placement of size x size squares centred on candidate points.
    ok: mask of allowed centres. Squares are snapped to the grid."""
    n = int(round(size / G))
    acc = []
    m = cv.z()
    for (x, y) in pts:
        i, j = cv.ij(x, y)
        if not (0 <= i < cv.ny and 0 <= j < cv.nx) or not ok[i, j]:
            continue
        if avoid is not None and avoid[i, j]:
            continue
        cx, cy = cv.xs[j], cv.ys[i]
        if any(max(abs(cx - qx), abs(cy - qy)) < pitch for qx, qy in acc):
            continue
        acc.append((cx, cy))
        i0, j0 = i - n // 2, j - n // 2
        m[i0:i0 + n, j0:j0 + n] = True
    return m, acc


def ring_points(mask_band, S_in_dist, w, cv, cen):
    """points on the centre line of a band (distance w/2 from the outer edge),
    ordered by angle around cen"""
    sel = mask_band & (np.abs(S_in_dist - w / 2) <= G * 0.75)
    ii, jj = np.nonzero(sel)
    xs, ys = cv.xs[jj], cv.ys[ii]
    ang = np.arctan2(ys - cen[1], xs - cen[0])
    o = np.argsort(ang)
    return list(zip(xs[o], ys[o]))


# =============================================================== build cell
def build(pdk, name):
    R = PDKS[pdk]
    D = derived(R)
    cell = CELLS[name]
    core = Core(cell, R, D)
    w = R['band_w']
    c_out = snap_up(max(R['diff_sp'], R['r1_sp'], R['r2_sp']) + 0.02)
    H, x_off = fit(core, cell['shape'], R, c_out)
    p = shape_params(cell['shape'], H)
    L = R['L']

    # ---- extents
    lead = max(1.5, 0.15 * H)
    x_back = -w / 2 if cell['shape'] == 'xor' else 0.0   # leftmost outline point
    pin = snap_up(max(D['via_r1'], D['via_r2'], np.sqrt(max(R['r1_area'], R['r2_area'])) + 0.02))
    x_in = snap(x_back - lead)                      # input poly ends here (poly contact)
    pin_off = snap_up(R['ct'] / 2 + R['via'] / 2 + 0.1)
    bw = R['bubble_w']
    rb = snap(max(0.09 * H, 2.4 * bw)) if cell['bubble'] else 0.0
    margin = 1.0
    cv = Canvas(x_in - pin_off - pin - margin, p['tip'] + 2 * rb + lead + 1.0 + pin + margin,
                -H / 2 - margin - 0.6, H / 2 + margin + 0.6)
    X, Y = cv.X, cv.Y

    # ---- outline
    S = shape_mask(p, X, Y)
    dS = edt_in(S, G)
    band = S & (dS <= w)
    h_split = snap_up(max(D['track_w'] / 2 + R['r1_sp'], R['r2_sp'] / 2, R['L'] / 2 + 0.1) + 0.02)
    mw = max(R['r1_w'], R['r2_w']) + 0.02
    msp = max(R['r1_sp'], R['r2_sp']) + 0.02
    band_t = clean(band & (Y >= h_split), mw, msp)
    band_b = clean(band & (Y <= -h_split), mw, msp)
    band_r = band_t | band_b

    # ---- core rasters (shifted by x_off)
    r = core.r
    M = {k: cv.rects(r[k], x_off) for k in r}
    poly = M['poly'] | M['pc_pad'] | (M['lead_A'] & (X >= x_in - D['pc_pad'] / 2)) \
        | (M['lead_B'] & (X >= x_in - D['pc_pad'] / 2))
    up = M['r1_up'] & S
    dn = M['r1_dn'] & S
    vdd_r1 = clean(band_t | up, R['r1_w'], R['r1_sp'] + 0.02)
    vss_r1 = clean(band_b | dn, R['r1_w'], R['r1_sp'] + 0.02)

    # ---- bubble + output
    tw = D['track_w'] / 2
    r1_out = M['out'].copy()
    hole = cv.z()
    ring = cv.z()
    if cell['bubble']:
        sp = max(R['r1_sp'], R['r2_sp']) + 0.03
        d_band = ndimage.distance_transform_edt(~band_r) * G
        gap = 0.0
        while True:
            cxb = p['tip'] + gap + rb
            rr = np.hypot(X - cxb, Y)
            ring = (rr <= rb) & (rr >= rb - bw)
            if d_band[ring].min() >= sp:
                break
            gap += 0.02
        ring = clean(ring, mw, msp)
        hole = (rr < rb) & ~ring
        x_end = cxb + rb + lead
    else:
        x_end = p['tip'] + lead
    x_pin_out = snap(x_end)
    pin_out = cv.rect(cv.z(), x_pin_out - pin / 2, x_pin_out + pin / 2, -pin / 2, pin / 2)
    r1_out = clean((r1_out & (X <= x_pin_out) & ~hole) | ring | pin_out, R['r1_w'], R['r1_sp'])

    # ---- input pins: poly contact at the lead end, via one step further out
    pins_in = {}
    pc_in, r1_in, r2_in = cv.z(), cv.z(), cv.z()
    lead_y = {'A': core.y_A} if len(cell['inputs']) == 1 else {'A': core.y_A, 'B': core.y_B}
    ct = R['ct']
    for nm, yy in lead_y.items():
        cx0, cy0 = snap(x_in - ct / 2), snap(yy - ct / 2)
        cv.rect(pc_in, cx0, cx0 + ct, cy0, cy0 + ct)
        h = D['pc_pad'] / 2
        cv.rect(poly, x_in - h, x_in + h, yy - h, yy + h)
        h = D['pc_r1'] / 2
        xv = x_in - pin_off
        cv.rect(r1_in, xv, x_in + h, yy - h, yy + h)
        cv.rect(r1_in, xv - pin / 2, xv + pin / 2, yy - pin / 2, yy + pin / 2)
        cv.rect(r2_in, xv - pin / 2, xv + pin / 2, yy - pin / 2, yy + pin / 2)
        pins_in[nm] = (xv, yy)

    # ---- wells and taps
    nwe = max(R['nw_ntap_sur'], R['nw_pdiff_sur']) + 0.05
    NW = dil(S, nwe) & (Y >= 0)
    NW = clean(NW, R['nw_w'] + 0.02, 1.3)
    pdiff, ndiff = M['pdiff'], M['ndiff']
    assert not (pdiff & ~ero_sq(NW, R['nw_pdiff_sur'])).any(), 'pdiff not enclosed by nwell'
    assert not (ndiff & dil_sq(NW, R['nw_ndiff_sp'])).any(), 'ndiff too close to nwell'
    ht = snap_up(max(h_split, R['nw_ntap_sur'], R['nw_ptap_sp']) + 0.05)
    polycut = dil_sq(poly, R['poly_diff_sp'] + 0.08)
    ntap = band & (Y >= ht) & ~polycut & ero_sq(NW, R['nw_ntap_sur'] + 0.01)
    ptap = band & (Y <= -ht) & ~polycut & ~dil_sq(NW, R['nw_ptap_sp'] + 0.01)
    amin = max(0.4, R['diff_w'] ** 2 * 4)
    dw, dsp = R['diff_w'] + 0.02, R['diff_sp'] + 0.02
    ntap = drop_small(clean(ntap, dw, dsp) & ero_sq(NW, R['nw_ntap_sur'] + 0.01), amin)
    ptap = drop_small(clean(ptap, dw, dsp) & ~dil_sq(NW, R['nw_ptap_sp'] + 0.01), amin)
    ntap = drop_small(clean(ntap, dw, dsp), amin)
    ptap = drop_small(clean(ptap, dw, dsp), amin)

    # ---- R1 / R2
    xarc = clean(xor_arc_mask(p, X, Y, w), mw, msp) if cell['shape'] == 'xor' else cv.z()
    R1 = vdd_r1 | vss_r1 | M['r1'] | r1_out | r1_in | pin_out
    R2 = band_r.copy() | r2_in | pin_out
    if cell['bubble']:
        R1 |= ring
        R2 |= ring
    R1 |= xarc
    R2 |= xarc

    # ---- contacts on the outline (taps) and vias (R1 band -> R2 band)
    cen = (p['tip'] / 2, 0.0)
    pts = ring_points(band, dS, w, cv, cen)
    tsur = max(R['tap_ct_sur'], R['ct_diff_sur'])
    r1sur = max(R['r1_ct_sur'], R['r1_ct_ext'])
    ok_n = sq_fit(ntap, ct / 2 + tsur) & sq_fit(band_r, ct / 2 + r1sur)
    ok_p = sq_fit(ptap, ct / 2 + tsur) & sq_fit(band_r, ct / 2 + r1sur)
    tpitch = 2 * D['ct_pitch']
    NTC, _ = place_squares(cv, ok_n, pts, ct, tpitch)
    PTC, _ = place_squares(cv, ok_p, pts, ct, tpitch)
    ok_v = sq_fit(band_r, D['via_r1'] / 2) & sq_fit(band_r, D['via_r2'] / 2)
    avoid = dil(NTC | PTC, max(R['via'], ct) / 2 + 0.06)
    VIA, _ = place_squares(cv, ok_v, pts, R['via'], 2 * snap_up(R['via'] + R['via_sp']), avoid)
    # vias on the bubble ring and the pins
    for (xv, yv) in list(pins_in.values()) + [(x_pin_out, 0.0)]:
        v0x, v0y = snap(xv - R['via'] / 2), snap(yv - R['via'] / 2)
        cv.rect(VIA, v0x, v0x + R['via'], v0y, v0y + R['via'])
    if cell['bubble']:
        okb = sq_fit(ring, max(D['via_r1'], D['via_r2']) / 2)
        th = np.linspace(-np.pi, np.pi, 720, endpoint=False)
        rm = rb - bw / 2
        bpts = list(zip(cxb + rm * np.cos(th), rm * np.sin(th)))
        BV, _ = place_squares(cv, okb, bpts, R['via'], 3 * snap_up(R['via'] + R['via_sp']))
        VIA |= BV

    # ---- final layer masks
    PDC = M['pdc']
    NDC = M['ndc']
    PC = M['pc'] | pc_in
    pfet = poly & pdiff
    nfet = poly & ndiff
    CT1 = PDC | NDC | PC | NTC | PTC          # contacts that carry R1
    lay = R['lay']
    layers = [
        (lay['nwell'], NW),
        (lay['pfet'], pfet),
        (lay['nfet'], nfet),
        (lay['pdiff'], pdiff & ~poly & ~PDC),
        (lay['ndiff'], ndiff & ~poly & ~NDC),
        (lay['pdc'], PDC),
        (lay['ndc'], NDC),
        (lay['poly'], poly & ~pdiff & ~ndiff & ~PC),
        (lay['pc'], PC),
        (lay['ntap'], ntap & ~NTC),
        (lay['ptap'], ptap & ~PTC),
        (lay['ntapc'], NTC),
        (lay['ptapc'], PTC),
        (lay['r1'], R1 & ~CT1 & ~VIA),
        (lay['via'], VIA),
        (lay['r2'], R2 & ~VIA),
    ]
    # sanity: every contact is covered by R1, every via by R1 and R2
    assert not (CT1 & ~R1).any(), 'contact without R1'
    assert not (VIA & ~(R1 & R2)).any(), 'via without R1/R2'

    # ---- labels (on R2)
    def lab(x, y, s=0.1):
        return (snap(x - s), snap(x + s), snap(y - s), snap(y + s))
    top_i = np.nonzero((band_r & (Y > 0)).any(axis=1))[0][-1]
    bot_i = np.nonzero((band_r & (Y < 0)).any(axis=1))[0][0]
    xc_t = cv.xs[np.nonzero(band_r[top_i - int(w / 2 / G)])[0]].mean()
    xc_b = cv.xs[np.nonzero(band_r[bot_i + int(w / 2 / G)])[0]].mean()
    labels = [('A', lab(*pins_in['A']))]
    if 'B' in pins_in:
        labels.append(('B', lab(*pins_in['B'])))
    labels += [('Y', lab(x_pin_out, 0.0)),
               ('VDD', lab(snap(xc_t), cv.ys[top_i] - w / 2)),
               ('VSS', lab(snap(xc_b), cv.ys[bot_i] + w / 2))]

    info = dict(H=H, x_off=x_off, W=cv.nx * G, Hc=cv.ny * G, y_A=core.y_A, y_B=core.y_B,
                n_ntc=int(NTC.sum() / (ct / G) ** 2), n_ptc=int(PTC.sum() / (ct / G) ** 2))
    masks = dict(NW=NW, pdiff=pdiff, ndiff=ndiff, poly=poly, ntap=ntap, ptap=ptap,
                 R1=R1, R2=R2, CT=CT1, VIA=VIA)
    return layers, labels, info, masks, cv


# =============================================================== writers
def to_rects(m):
    """row run-length + vertical merge -> list of (j0, i0, j1, i1) in pixels"""
    rects, open_ = [], {}
    for i in range(m.shape[0] + 1):
        runs = set()
        if i < m.shape[0]:
            row = np.concatenate([[0], m[i].astype(np.int8), [0]])
            d = np.diff(row)
            runs = set(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))
        nxt = {}
        for rr, i0 in open_.items():
            if rr in runs:
                nxt[rr] = i0
            else:
                rects.append((rr[0], i0, rr[1], i))
        for rr in runs:
            if rr not in nxt:
                nxt[rr] = i
        open_ = nxt
    return rects


def write_mag(fn, R, cv, layers, labels):
    ox = int(round(cv.x0 / G))
    oy = int(round(cv.y0 / G))
    with open(fn, 'w') as f:
        f.write(f"magic\ntech {R['tech']}\nmagscale {R['magscale']}\ntimestamp {int(time.time())}\n")
        for name, m in layers:
            if not m.any():
                continue
            f.write(f"<< {name} >>\n")
            for (j0, i0, j1, i1) in to_rects(m):
                f.write(f"rect {j0 + ox} {i0 + oy} {j1 + ox} {i1 + oy}\n")
        f.write("<< labels >>\n")
        c = lambda v: int(round(v / G))
        for k, (nm, (x0, x1, y0, y1)) in enumerate(labels):
            f.write(f"rlabel {R['lay']['r2']} {c(x0)} {c(y0)} {c(x1)} {c(y1)} 0 {nm}\n")
            f.write(f"port {k + 1} nsew\n")
        f.write("<< properties >>\nstring FIXED_BBOX "
                f"{ox} {oy} {ox + cv.nx} {oy + cv.ny}\n")
        f.write("<< end >>\n")


def write_ref(fn, pdk, name):
    """reference netlist built straight from the cell definition"""
    R = PDKS[pdk]
    cell = CELLS[name]
    ports = cell['inputs'] + ['Y', 'VDD', 'VSS']
    k = 0
    lines = [f"* {name} reference ({pdk})", f".subckt {name} {' '.join(ports)}"]
    for ii, isl in enumerate(cell['islands']):
        for side, nets, body, dev, W in (('p', isl['p'], 'VDD', R['pfet'], R['Wp']),
                                         ('n', isl['n'], 'VSS', R['nfet'], R['Wn'])):
            nn = [x if x is not None else f"{side}{ii}_{j}" for j, x in enumerate(nets)]
            for j, gname in enumerate(isl['g']):
                k += 1
                lines.append(f"X{k} {nn[j]} {gname} {nn[j + 1]} {body} {dev} "
                             f"w={W:g}{R['wl_unit']} l={R['L']:g}{R['wl_unit']}")
    lines.append(".ends")
    open(fn, 'w').write("\n".join(lines) + "\n")


COLORS = [('NW', (.75, .75, .55), .35), ('ntap', (.2, .55, .2), .8), ('ptap', (.55, .3, .1), .8),
          ('pdiff', (.95, .6, .2), .85), ('ndiff', (.2, .75, .25), .85),
          ('poly', (.85, .1, .1), .85), ('R1', (.45, .45, 1.0), .45),
          ('R2', (.55, .25, .75), .45), ('CT', (0, 0, 0), 1.0), ('VIA', (.2, .2, .2), .9)]


def preview(fn, title, masks, cv, st=4):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    shp = masks['R1'][::st, ::st].shape
    img = np.ones(shp + (3,))
    for k, c, a in COLORS:
        m = masks[k][::st, ::st][..., None]
        img = np.where(m, img * (1 - a) + np.array(c) * a, img)
    ext = [cv.x0, cv.x0 + cv.nx * G, cv.y0, cv.y0 + cv.ny * G]
    fig, ax = plt.subplots(figsize=(8, 8 * shp[0] / shp[1] + 0.4))
    ax.imshow(img, origin='lower', extent=ext, interpolation='nearest')
    ax.set_title(title, fontsize=9)
    ax.set_xlabel('um')
    plt.tight_layout()
    plt.savefig(fn, dpi=110)
    plt.close()


def main():
    pdk = sys.argv[1]
    names = sys.argv[2:] or ORDER
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', pdk)
    os.makedirs(out, exist_ok=True)
    for name in names:
        t0 = time.time()
        layers, labels, info, masks, cv = build(pdk, name)
        write_mag(os.path.join(out, f'{name}.mag'), PDKS[pdk], cv, layers, labels)
        write_ref(os.path.join(out, f'{name}_ref.spice'), pdk, name)
        preview(os.path.join(out, f'{name}_preview.png'), f'{name}  ({pdk})', masks, cv)
        np.savez_compressed(os.path.join(out, f'{name}_masks.npz'), x0=cv.x0, y0=cv.y0,
                            **{k: v for k, v in masks.items()})
        print(f"{pdk} {name:5s} H={info['H']:.1f} cell {info['W']:.2f} x {info['Hc']:.2f} um  "
              f"taps n{info['n_ntc']} p{info['n_ptc']}  ({time.time() - t0:.1f}s)")


if __name__ == '__main__':
    main()
