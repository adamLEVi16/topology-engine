#!/usr/bin/env python3
"""Verify a binary STL is a closed, consistently wound solid.

A slicer handed a non-manifold mesh will either silently "repair" it or print a
shell with holes, so this is worth checking before sending anything to a printer.

In a closed solid with consistent winding, every directed edge appears exactly
once and its reverse appears exactly once. That is a property of vertex order,
not of the stored normals -- a mesh can have every normal pointing correctly
outward and still not be closed.

Prints "<triangles> <unmatched> <duplicated>" and exits non-zero if not manifold.
"""

import struct
import sys
from collections import defaultdict


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: check_stl.py FILE.stl")

    data = open(sys.argv[1], "rb").read()
    if len(data) < 84:
        sys.exit("file is too short to be a binary STL")

    count = struct.unpack("<I", data[80:84])[0]
    if len(data) < 84 + count * 50:
        sys.exit(f"truncated: header claims {count} triangles")

    edges = defaultdict(int)
    for t in range(count):
        off = 84 + t * 50
        vals = struct.unpack("<12f", data[off:off + 48])
        # Round so that vertices shared between triangles compare equal despite
        # having been computed by different arithmetic paths.
        pts = [tuple(round(c, 4) for c in vals[3 + 3 * k:6 + 3 * k]) for k in range(3)]
        for a, b in ((pts[0], pts[1]), (pts[1], pts[2]), (pts[2], pts[0])):
            edges[(a, b)] += 1

    unmatched = sum(1 for (a, b), n in edges.items() if edges.get((b, a), 0) != n)
    duplicated = sum(1 for n in edges.values() if n != 1)

    print(f"{count} {unmatched} {duplicated}")
    sys.exit(0 if unmatched == 0 and duplicated == 0 else 1)


if __name__ == "__main__":
    main()
