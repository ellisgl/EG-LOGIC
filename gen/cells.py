"""
Cell definitions.

Every cell is a row of diffusion islands. Each island lists
  g : gate of each poly column, left to right
  p : net of each P-diffusion slot (len(g)+1); None = uncontacted series node
  n : net of each N-diffusion slot
Gates named 'A'/'B' are cell inputs: A enters as a poly line along the top of
the core, B along the bottom (single-input cells enter on the centre line).
Any other gate is an internal net and gets a poly contact in the P/N gap.

VDD slots strap up into the outline (top half = VDD), VSS slots strap down.
Other nets strap into the gap onto an R1 track: track 0 is the centre line
(y = 0), +1 is above it, -1 below. 'Y' is the output and leaves through the
tip of the symbol on the centre line.

XOR  = AOI21(A, B, NOR2(A, B))   -> Y = !(A.B + !(A+B))
XNOR = OAI21(A, B, NAND2(A, B))  -> Y = !((A+B) . !(A.B))
"""

INV_Y = dict(g=['x'], p=['VDD', 'Y'], n=['VSS', 'Y'])

CELLS = {
    'NOT': dict(shape='tri', bubble=True, inputs=['A'], fn=lambda a: 1 - a,
                islands=[dict(g=['A'], p=['VDD', 'Y'], n=['VSS', 'Y'])],
                track={'Y': 0}),
    'BUF': dict(shape='tri', bubble=False, inputs=['A'], fn=lambda a: a,
                islands=[dict(g=['A'], p=['VDD', 'x'], n=['VSS', 'x']), INV_Y],
                track={'x': 0, 'Y': 0}),
    'NAND': dict(shape='and', bubble=True, inputs=['A', 'B'], fn=lambda a, b: 1 - (a & b),
                 islands=[dict(g=['A', 'B'], p=['Y', 'VDD', 'Y'], n=['Y', None, 'VSS'])],
                 track={'Y': 0}),
    'AND': dict(shape='and', bubble=False, inputs=['A', 'B'], fn=lambda a, b: a & b,
                islands=[dict(g=['A', 'B'], p=['x', 'VDD', 'x'], n=['x', None, 'VSS']), INV_Y],
                track={'x': 0, 'Y': 0}),
    'NOR': dict(shape='or', bubble=True, inputs=['A', 'B'], fn=lambda a, b: 1 - (a | b),
                islands=[dict(g=['A', 'B'], p=['Y', None, 'VDD'], n=['Y', 'VSS', 'Y'])],
                track={'Y': 0}),
    'OR': dict(shape='or', bubble=False, inputs=['A', 'B'], fn=lambda a, b: a | b,
               islands=[dict(g=['A', 'B'], p=['x', None, 'VDD'], n=['x', 'VSS', 'x']), INV_Y],
               track={'x': 0, 'Y': 0}),
    'XOR': dict(shape='xor', bubble=False, inputs=['A', 'B'], fn=lambda a, b: a ^ b,
                islands=[dict(g=['A', 'B'], p=['c', None, 'VDD'], n=['c', 'VSS', 'c']),
                         dict(g=['A', 'B', 'c'], p=['p1', 'VDD', 'p1', 'Y'],
                              n=['Y', None, 'VSS', 'Y'])],
                track={'c': 0, 'p1': 1, 'Y': -1}),
    'XNOR': dict(shape='xor', bubble=True, inputs=['A', 'B'], fn=lambda a, b: 1 - (a ^ b),
                 islands=[dict(g=['A', 'B'], p=['c', 'VDD', 'c'], n=['c', None, 'VSS']),
                          dict(g=['A', 'B', 'c'], p=['Y', None, 'VDD', 'Y'],
                               n=['n1', 'VSS', 'n1', 'Y'])],
                 track={'c': 0, 'n1': -1, 'Y': 1}),
}

ORDER = ['BUF', 'NOT', 'AND', 'NAND', 'OR', 'NOR', 'XOR', 'XNOR']
