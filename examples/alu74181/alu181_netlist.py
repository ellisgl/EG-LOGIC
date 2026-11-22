#!/usr/bin/env python3
"""
74181 4-bit ALU as a netlist of 2-input EG-LOGIC cells (active-high data).

The 74181 schematic uses 3- to 5-input AND / AND-OR-INVERT gates. This builds
the same logic function from the library's 2-input gates:

  per bit i:  p = A + B.S0 + !B.S1          (built as OR(A, NAND(NAND, NAND)))
              g = A.(!B.S2 + B.S3)
              h = p ^ g
              F = h ^ (M + c_i)              M = 1: logic, carries masked
              c_(i+1) = g + p.c_i            ripple carry, c_0 = !Cn
  Cn+4 = !c_4      P_N = !(p0.p1.p2.p3)      A=B = F0.F1.F2.F3
  G_N  = !(g3 + p3.(g2 + p2.(g1 + p1.g0)))

Run directly to check this netlist against the 74181 function table for all
2^14 input combinations.
"""

INPUTS = ['A0', 'A1', 'A2', 'A3', 'B0', 'B1', 'B2', 'B3', 'S0', 'S1', 'S2', 'S3', 'M', 'Cn']
OUTPUTS = ['F0', 'F1', 'F2', 'F3', 'AEQB', 'P_N', 'G_N', 'Cn4']


def gates():
    """list of (cell, instance, A, B, Y) in placement order (B is None for NOT)"""
    g = [('NOT', 'ncn', 'Cn', None, 'c0')]
    for i in range(4):
        A, B, c, cn = f'A{i}', f'B{i}', f'c{i}', f'c{i + 1}'
        g += [
            ('NOT', f'nb{i}', B, None, f'nB{i}'),
            ('NAND', f'a1_{i}', B, 'S0', f'a1_{i}'),
            ('NAND', f'a2_{i}', f'nB{i}', 'S1', f'a2_{i}'),
            ('NAND', f'u{i}', f'a1_{i}', f'a2_{i}', f'u{i}'),
            ('OR', f'p{i}', A, f'u{i}', f'p{i}'),
            ('NAND', f'a3_{i}', f'nB{i}', 'S2', f'a3_{i}'),
            ('NAND', f'a4_{i}', B, 'S3', f'a4_{i}'),
            ('NAND', f'v{i}', f'a3_{i}', f'a4_{i}', f'v{i}'),
            ('AND', f'g{i}', A, f'v{i}', f'g{i}'),
            ('XOR', f'h{i}', f'p{i}', f'g{i}', f'h{i}'),
            ('OR', f'k{i}', 'M', c, f'k{i}'),
            ('XOR', f'f{i}', f'h{i}', f'k{i}', f'F{i}'),
            ('AND', f'pc{i}', f'p{i}', c, f'pc{i}'),
            ('OR', f'cy{i}', f'g{i}', f'pc{i}', cn),
        ]
    g += [
        ('NOT', 'ncout', 'c4', None, 'Cn4'),
        ('AND', 'pp01', 'p0', 'p1', 'pp01'),
        ('AND', 'pp23', 'p2', 'p3', 'pp23'),
        ('NAND', 'pg', 'pp01', 'pp23', 'P_N'),
        ('AND', 'q1', 'p1', 'g0', 'q1'),
        ('OR', 'gr1', 'g1', 'q1', 'gr1'),
        ('AND', 'q2', 'p2', 'gr1', 'q2'),
        ('OR', 'gr2', 'g2', 'q2', 'gr2'),
        ('AND', 'q3', 'p3', 'gr2', 'q3'),
        ('NOR', 'gg', 'g3', 'q3', 'G_N'),
        ('AND', 'e01', 'F0', 'F1', 'e01'),
        ('AND', 'e23', 'F2', 'F3', 'e23'),
        ('AND', 'eq', 'e01', 'e23', 'AEQB'),
    ]
    return g


FN = {'NOT': lambda a, b: 1 - a, 'AND': lambda a, b: a & b, 'NAND': lambda a, b: 1 - (a & b),
      'OR': lambda a, b: a | b, 'NOR': lambda a, b: 1 - (a | b), 'XOR': lambda a, b: a ^ b,
      'BUF': lambda a, b: a, 'XNOR': lambda a, b: 1 - (a ^ b)}


def evaluate(v):
    """v: dict input -> bit. Returns dict of all nets."""
    n = dict(v)
    for cell, _, a, b, y in gates():
        n[y] = FN[cell](n[a], n[b] if b else 0)
    return n


def reference(A, B, S, M, Cn):
    """74181 datasheet function table, active-high data.
    Returns (F, Cn4, AEQB). Cn = 1 means no carry in; Cn4 = 1 means no carry out."""
    nB = ~B & 15
    logic = [~A, ~(A | B), ~A & B, 0, ~(A & B), ~B, A ^ B, A & nB,
             ~A | B, ~(A ^ B), B, A & B, 15, A | nB, A | B, A]
    # arithmetic: F = X plus Y (plus 1 when Cn = 0); "minus 1" is "plus 15"
    arith = [(A, 0), (A | B, 0), (A | nB, 0), (15, 0), (A, A & nB), (A | B, A & nB),
             (A, nB), (15, A & nB), (A, A & B), (A, B), (A | nB, A & B), (15, A & B),
             (A, A), (A | B, A), (A | nB, A), (15, A)]
    if M:
        F = logic[S] & 15
        cout = None
    else:
        x, y = arith[S]
        tot = x + y + (1 - Cn)
        F = tot & 15
        cout = 1 - (tot >> 4)
    return F, cout, int(F == 15)


def check():
    # SPICE names are case-insensitive: nets must stay distinct when lower-cased
    nets = INPUTS + [y for *_, y in gates()]
    assert len(set(n.lower() for n in nets)) == len(nets), 'net names collide ignoring case'
    bad = 0
    for k in range(1 << 14):
        v = {nm: (k >> i) & 1 for i, nm in enumerate(INPUTS)}
        A = sum(v[f'A{i}'] << i for i in range(4))
        B = sum(v[f'B{i}'] << i for i in range(4))
        S = sum(v[f'S{i}'] << i for i in range(4))
        n = evaluate(v)
        F = sum(n[f'F{i}'] << i for i in range(4))
        rF, rC, rE = reference(A, B, S, v['M'], v['Cn'])
        ok = F == rF and n['AEQB'] == rE
        if rC is not None:
            ok &= n['Cn4'] == rC
        # group outputs against the carry-lookahead identity c4 = G + P.c0
        P = 1 - n['P_N']
        G = 1 - n['G_N']
        ok &= (1 - n['Cn4']) == (G | (P & (1 - v['Cn'])))
        bad += not ok
    return bad


if __name__ == '__main__':
    bad = check()
    from collections import Counter
    cnt = Counter(c for c, *_ in gates())
    print(f'{len(gates())} cells {dict(cnt)}; mismatches vs 74181 table: {bad} / {1 << 14}')
