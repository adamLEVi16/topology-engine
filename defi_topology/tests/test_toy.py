#!/usr/bin/env python3
"""
Hand-checkable validation of the topology observables (blueprint §3-5 milestone:
"validate invariants on a hand-checkable toy complex").

Each case is a tiny nerve complex whose B0/B1/B2, 1-skeleton cycle rank and higher-order
gap can be worked out by hand; we assert the pipeline reproduces them. This pins down the
skeleton-vs-nerve decomposition independently of the live API.

Run:  python -m pytest test_toy.py -q      (or)     python test_toy.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline as P

# real mainnet addresses so the lp_vertex fork can be exercised
USDC, USDT, DAI = P.USDC, P.USDT, P.DAI
FRAX = "0x853d955acef822db058eb8505911ed77f175b99e"


def observ(pools, lp_mode="resolved"):
    """pools: list of token-name/address tuples. Equal shares, no dust cap."""
    tok = {i: list(p) for i, p in enumerate(pools)}
    shares = {i: 1.0 / len(pools) for i in range(len(pools))}
    st, verts, edges, n_ho, used = P.build_complex(shares, tok, minshare=0.0, lp_mode=lp_mode)
    st.make_filtration_non_decreasing()
    st.compute_persistence(persistence_dim_max=True)
    b = st.betti_numbers(); b += [0] * (3 - len(b))
    V, E, C = len(verts), len(edges), b[0]
    return dict(V=V, E=E, B0=b[0], B1=b[1], B2=b[2], skel=E - V + C, gap=(E - V + C) - b[1])


# (name, pools, expected-subset-dict)
CASES = [
    # hollow triangle: 3 pairwise pools, one genuine (pairwise) loop, no higher-order fill
    ("hollow_triangle", [("A", "B"), ("B", "C"), ("A", "C")],
     dict(V=3, E=3, B0=1, B1=1, B2=0, skel=1, gap=0)),
    # one 3-token pool: fills the triangle -> the single skeleton loop is higher-order
    ("filled_triangle", [("A", "B", "C")],
     dict(V=3, E=3, B0=1, B1=0, B2=0, skel=1, gap=1)),
    # hollow square: 4 pairwise pools, one pairwise loop
    ("hollow_square", [("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")],
     dict(V=4, E=4, B0=1, B1=1, B2=0, skel=1, gap=0)),
    # tetrahedron boundary (4 triangles) = S^2: a void (B2=1), all 3 skeleton loops filled
    ("tetra_boundary", [("A", "B", "C"), ("A", "B", "D"), ("A", "C", "D"), ("B", "C", "D")],
     dict(V=4, E=6, B0=1, B1=0, B2=1, skel=3, gap=3)),
    # solid tetrahedron (one 4-token pool): contractible, everything filled
    ("solid_tetra", [("A", "B", "C", "D")],
     dict(V=4, E=6, B0=1, B1=0, B2=0, skel=3, gap=3)),
    # two disconnected edges: B0=2, no loops
    ("two_edges", [("A", "B"), ("C", "D")],
     dict(V=4, E=2, B0=2, B1=0, B2=0, skel=0, gap=0)),
]


def test_cases():
    for name, pools, exp in CASES:
        got = observ(pools)
        for k, v in exp.items():
            assert got[k] == v, f"{name}: {k} expected {v} got {got[k]} (full {got})"


def test_lp_vertex_fork_collapses_metapool():
    """A FRAX/3CRV metapool is a filled tetrahedron under 'resolved' (base assets), but a
    single FRAX-3CRV edge under 'lp_vertex'. This is the whole point of the fork."""
    meta = [(FRAX, DAI, USDC, USDT)]
    res = observ(meta, "resolved")
    lpv = observ(meta, "lp_vertex")
    assert res == dict(V=4, E=6, B0=1, B1=0, B2=0, skel=3, gap=3), res
    assert lpv == dict(V=2, E=1, B0=1, B1=0, B2=0, skel=0, gap=0), lpv


def test_lp_vertex_keeps_bare_3pool():
    """The standalone 3pool {DAI,USDC,USDT} is NOT a metapool, so lp_vertex leaves it as a
    filled triangle (base set is not a STRICT subset of itself)."""
    threepool = [(DAI, USDC, USDT)]
    assert observ(threepool, "lp_vertex") == observ(threepool, "resolved")
    assert observ(threepool, "lp_vertex")["B1"] == 0  # filled triangle


def test_forward_fill_bridges_one_day_hole():
    """A one-day drop-out (absent sample or zero) between two positive days is filled;
    a leading absence and a long trailing gap are not."""
    raw = {"2023-03-01": 100, "2023-03-02": 0, "2023-03-03": 120,   # interior hole -> fill
           "2023-03-04": 0,                                          # trailing zero
           "2023-03-05": 0, "2023-03-06": 0, "2023-03-07": 0}
    filled = P.forward_fill(raw, max_gap=3)
    assert filled["2023-03-02"] == 100, filled          # bridged
    assert filled["2023-03-01"] == 100 and filled["2023-03-03"] == 120
    assert "2023-03-05" not in filled                    # active span ends at last positive


if __name__ == "__main__":
    test_cases()
    test_lp_vertex_fork_collapses_metapool()
    test_lp_vertex_keeps_bare_3pool()
    test_forward_fill_bridges_one_day_hole()
    for name, pools, exp in CASES:
        print(f"OK  {name:16s} {observ(pools)}")
    print("OK  lp_vertex fork:", observ([(FRAX, DAI, USDC, USDT)], "lp_vertex"))
    print("all toy-complex assertions passed")
