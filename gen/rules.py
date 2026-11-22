"""
PDK rule tables and Magic layer maps for the EG-LOGIC generator.

All dimensions are in um. Contact sizes are the sizes of the Magic contact
*type* (what is painted in the .mag), not the GDS cut. GF180's Magic deck
paints contacts 0.23 um wide (CO.1 + 2*CO.6), sky130's paints licon 0.17.

Two routing layers are used, named by role:
  R1  local routing, lands directly on diff/poly contacts
      gf180: metal1      sky130: li1 (locali)
  R2  outline / pins
      gf180: metal2      sky130: met1
"""

PDKS = {
    'gf180mcuD': dict(
        tech='gf180mcuD', magscale='1 10',
        # devices (3.3 V)
        L=0.28, Wn=1.00, Wp=2.00, vdd=3.3,
        nfet='nfet_03v3', pfet='pfet_03v3', wl_unit='u',
        # diffusion / poly
        diff_w=0.22, diff_sp=0.28, poly_w=0.18, poly_sp=0.24,
        endcap=0.22, poly_diff_sp=0.10,
        # contacts (Magic contact type, R1 lands on it)
        ct=0.23, ct_sp=0.24, ct_diff_sur=0.07, ct_poly_sur=0.07,
        ct_gate_sp=0.15, pc_pdiff_sp=0.17, pc_ndiff_sp=0.17,
        tap_ct_sur=0.07,
        r1_ct_sur=0.06, r1_ct_ext=0.06,
        # R1 / via / R2
        r1_w=0.23, r1_sp=0.23, r1_area=0.1444,
        via=0.26, via_sp=0.26, r1_via_sur=0.06, r2_via_sur=0.06,
        r2_w=0.28, r2_sp=0.28, r2_area=0.1444,
        # wells
        nw_w=0.86, nw_pdiff_sur=0.43, nw_ndiff_sp=0.43,
        nw_ntap_sur=0.12, nw_ptap_sp=0.12,
        # look
        band_w=0.80, bubble_w=0.50,
        # Magic layer names
        lay=dict(nwell='nwell', pdiff='pdiff', ndiff='ndiff', pfet='pfet', nfet='nfet',
                 pdc='pdiffc', ndc='ndiffc', poly='poly', pc='polycontact',
                 ntap='nsubdiff', ptap='psubdiff', ntapc='nsubdiffcont', ptapc='psubdiffcont',
                 r1='metal1', via='via1', r2='metal2'),
    ),
    'sky130A': dict(
        tech='sky130A', magscale='1 2',
        L=0.15, Wn=0.65, Wp=1.00, vdd=1.8,
        nfet='sky130_fd_pr__nfet_01v8', pfet='sky130_fd_pr__pfet_01v8', wl_unit='',
        diff_w=0.15, diff_sp=0.27, poly_w=0.15, poly_sp=0.21,
        endcap=0.13, poly_diff_sp=0.075,
        ct=0.17, ct_sp=0.17, ct_diff_sur=0.06, ct_poly_sur=0.08,
        ct_gate_sp=0.055, pc_pdiff_sp=0.235, pc_ndiff_sp=0.19,
        tap_ct_sur=0.12,
        # li over licon: 0.08 in one direction -> straps run vertically past
        # the contacts; no sideways surround needed
        r1_ct_sur=0.0, r1_ct_ext=0.08,
        r1_w=0.17, r1_sp=0.17, r1_area=0.0561,
        via=0.17, via_sp=0.19, r1_via_sur=0.0, r2_via_sur=0.06,
        r2_w=0.14, r2_sp=0.14, r2_area=0.083,
        nw_w=0.84, nw_pdiff_sur=0.18, nw_ndiff_sp=0.34,
        nw_ntap_sur=0.18, nw_ptap_sp=0.13,
        band_w=0.70, bubble_w=0.40,
        lay=dict(nwell='nwell', pdiff='pdiff', ndiff='ndiff', pfet='pmos', nfet='nmos',
                 pdc='pdiffc', ndc='ndiffc', poly='poly', pc='polycont',
                 ntap='nsubdiff', ptap='psubdiff', ntapc='nsubdiffcont', ptapc='psubdiffcont',
                 r1='locali', via='viali', r2='metal1'),
    ),
}


def derived(R):
    """dimensions that follow from the rules (all snapped up to 5 nm)"""
    def up(v):
        return round(-(-round(v * 1e4) // 50) * 50 / 1e4, 4)
    D = {}
    D['strap_w'] = up(R['ct'] + 2 * R['r1_ct_sur'])                # R1 strap over diff contacts
    D['track_w'] = up(max(R['r1_w'], D['strap_w']))                # horizontal R1 track
    D['pc_pad'] = up(R['ct'] + 2 * R['ct_poly_sur'])               # poly pad under a poly contact
    D['pc_r1'] = up(R['ct'] + 2 * max(R['r1_ct_sur'], R['r1_ct_ext']))   # R1 pad on a poly contact
    D['via_r1'] = up(R['via'] + 2 * R['r1_via_sur'])
    D['via_r2'] = up(R['via'] + 2 * R['r2_via_sur'])
    # gate centre to contact centre
    D['d_norm'] = up(R['L'] / 2 + R['ct_gate_sp'] + R['ct'] / 2)
    # gate with a poly contact in the gap: its R1 pad must clear a neighbouring strap
    D['d_wide'] = up(max(D['d_norm'], D['pc_r1'] / 2 + R['r1_sp'] + D['strap_w'] / 2))
    # gate to gate with plain (uncontacted) diffusion between
    D['g_plain'] = up(R['L'] + R['poly_sp'])
    # gate with poly pad next to another gate
    D['g_pad'] = up(D['pc_pad'] / 2 + R['poly_sp'] + R['L'] / 2)
    # vertical pitch of R1 tracks in the P/N gap
    D['tp'] = up(max(D['pc_r1'], D['track_w']) / 2 + R['r1_sp'] + D['track_w'] / 2)
    D['ct_pitch'] = up(R['ct'] + R['ct_sp'])
    return D
