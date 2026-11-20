# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
route.py — wire routing for hardware/wiring.svg, the same as the canvas's
static/route.js, so the published picture and the page agree.

Each wire leaves its pin straight out for a stub, then finds its way on a
10-unit grid with A*: never through a part, few bends, and away from the
wires routed before it (running along one costs more than crossing it).
Short wires go first, so they stay straight. Where a horizontal stretch
still crosses a vertical one, it hops over it in a half circle.

A pin's side is -1 (left), 1 (right) or 0 (bottom: its stub goes down).

    route(ends, rects)    [[(x, y), ...] per wire]; ends: [((x, y, side), (x, y, side))];
                          rects (x, y, w, h[, bottom]): with bottom pins the room below is kept
    path(points, others)  an SVG path with the hops
"""

from __future__ import annotations

import heapq
import math
from typing import List, Optional, Sequence, Tuple

G, STUB, CLEAR, MARGIN, HOP = 10, 30, 8, 200, 5
SIDE = STUB - 8                       # in front of a part's pins the stubs need the room
BEND, ALONG, ACROSS, MAX_EXPAND = 4, 25, 2, 250_000
DX, DY = (1, 0, -1, 0), (0, 1, 0, -1)

Pin = Tuple[float, float, int]
Pt = Tuple[float, float]


def _round(v: float) -> int:
    """Rounding as JavaScript's Math.round does (halves up), so both agree."""
    return math.floor(v + 0.5)


def out(p: Pin) -> Tuple[int, int]:
    """Which way a pin leaves its part."""
    return (int(p[2]), 0) if p[2] else (0, 1)


def stub(p: Pin) -> Tuple[int, int]:
    dx, dy = out(p)
    return _round((p[0] + dx * STUB) / G) * G, _round((p[1] + dy * STUB) / G) * G


def simple(a: Pin, b: Pin) -> List[Pt]:
    (ax, ay), (bx, by) = out(a), out(b)
    sa, sb = (a[0] + ax * STUB, a[1] + ay * STUB), (b[0] + bx * STUB, b[1] + by * STUB)
    mx = (sa[0] + sb[0]) / 2
    return [(a[0], a[1]), sa, (mx, sa[1]), (mx, sb[1]), sb, (b[0], b[1])]


def corners(pts: Sequence[Pt]) -> List[Pt]:
    out: List[Pt] = []
    for p in pts:
        if out and out[-1] == p:
            continue
        if len(out) >= 2:
            q, r = out[-1], out[-2]
            if (r[0] == q[0] == p[0]) or (r[1] == q[1] == p[1]):
                out[-1] = p
                continue
        out.append(p)
    return out


def _fit(pts: List[Pt], a: Pin, b: Pin) -> List[Pt]:
    A, B = (a[0], a[1]), (b[0], b[1])
    if len(pts) == 2:
        if a[0] == b[0] or a[1] == b[1]:
            return corners([A, B])
        if not a[2] and not b[2]:
            my = _round((a[1] + b[1]) / 2 / G) * G
            return corners([A, (a[0], my), (b[0], my), B])
        if not a[2] or not b[2]:
            return corners([A, (b[0], a[1]) if a[2] else (a[0], b[1]), B])
        mx = _round((a[0] + b[0]) / 2 / G) * G
        return corners([A, (mx, a[1]), (mx, b[1]), B])
    pts = [list(p) for p in pts]
    n = len(pts) - 1

    def onto(i: int, j: int, p: Pin) -> None:
        k, o = (1, 0) if p[2] else (0, 1)
        pts[i][k] = p[k]
        if pts[j][o] != pts[i][o]:
            pts[j][k] = p[k]
    onto(0, 1, a)
    onto(n, n - 1, b)
    return corners([tuple(p) for p in pts])


def _astar(start: int, goal: int, dir0: int, cols: int, rows: int, blocked, used_h, used_v) -> Optional[List[int]]:
    gi, gj = goal % cols, goal // cols
    cost = {start * 4 + dir0: 0.0}
    came = {start * 4 + dir0: -1}
    heap = [(abs(start % cols - gi) + abs(start // cols - gj), 0, start * 4 + dir0)]
    tie, expanded = 0, 0
    while heap:
        _, _, s = heapq.heappop(heap)
        c, d = s >> 2, s & 3
        if c == goal:
            path = []
            while s != -1:
                path.append(s >> 2)
                s = came[s]
            return path[::-1]
        expanded += 1
        if expanded > MAX_EXPAND:
            return None
        ci, cj = c % cols, c // cols
        for nd in range(4):
            if nd == (d + 2) & 3:
                continue
            ni, nj = ci + DX[nd], cj + DY[nd]
            if not (0 <= ni < cols and 0 <= nj < rows):
                continue
            n = nj * cols + ni
            if blocked[n] and n != goal:
                continue
            horizontal = nd in (0, 2)
            step = 1 + (BEND if nd != d else 0) + (ALONG if (used_h if horizontal else used_v)[n] else 0) \
                + (ACROSS if (used_v if horizontal else used_h)[n] else 0)
            ns, nc = n * 4 + nd, cost[s] + step
            if nc < cost.get(ns, math.inf):
                cost[ns], came[ns] = nc, s
                tie += 1
                heapq.heappush(heap, (nc + abs(ni - gi) + abs(nj - gj), tie, ns))
    return None


def route(ends: Sequence[Tuple[Pin, Pin]], rects: Sequence[Tuple[float, ...]]) -> List[List[Pt]]:
    """rects: the parts as (x, y, w, h), and True fifth when it has bottom pins."""
    if not ends:
        return []
    xs = [v for r in rects for v in (r[0], r[0] + r[2])] + [p[0] for e in ends for p in e]
    ys = [v for r in rects for v in (r[1], r[1] + r[3])] + [p[1] for e in ends for p in e]
    x0 = math.floor((min(xs) - MARGIN) / G) * G
    y0 = math.floor((min(ys) - MARGIN) / G) * G
    cols = math.ceil((max(xs) + MARGIN - x0) / G) + 1
    rows = math.ceil((max(ys) + MARGIN - y0) / G) + 1
    if cols * rows > 400_000:
        return [simple(a, b) for a, b in ends]
    blocked = bytearray(cols * rows)
    for (rx, ry, rw, rh, *more) in rects:
        i0, i1 = math.ceil((rx - SIDE - x0) / G), math.floor((rx + rw + SIDE - x0) / G)
        j0, j1 = math.ceil((ry - CLEAR - y0) / G), math.floor((ry + rh + (SIDE if more and more[0] else CLEAR) - y0) / G)
        for j in range(max(0, j0), min(rows - 1, j1) + 1):
            for i in range(max(0, i0), min(cols - 1, i1) + 1):
                blocked[j * cols + i] = 1
    used_h, used_v = bytearray(cols * rows), bytearray(cols * rows)
    length = [abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in ends]
    out: List[List[Pt]] = [[] for _ in ends]
    for k in sorted(range(len(ends)), key=lambda k: (length[k], k)):
        a, b = ends[k]
        sa, sb = stub(a), stub(b)
        start = ((sa[1] - y0) // G) * cols + (sa[0] - x0) // G
        goal = ((sb[1] - y0) // G) * cols + (sb[0] - x0) // G
        found = _astar(start, goal, 0 if a[2] > 0 else 2 if a[2] < 0 else 1, cols, rows, blocked, used_h, used_v)
        if not found:
            out[k] = simple(a, b)
            continue
        for p, q in zip(found, found[1:]):
            used = used_h if abs(p - q) == 1 else used_v
            used[p] = used[q] = 1
        pts = [(x0 + (c % cols) * G, y0 + (c // cols) * G) for c in found]
        def at(p: Pin, s: Tuple[int, int]) -> Pt:
            return (p[0], s[1]) if p[2] else (s[0], p[1])
        out[k] = _fit(corners([at(a, sa), *pts, at(b, sb)]), a, b)
    return out


def _n(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def path(pts: Sequence[Pt], others: Sequence[Sequence[Pt]]) -> str:
    vertical = [(o[i - 1], o[i]) for o in others for i in range(1, len(o)) if o[i - 1][0] == o[i][0] and o[i - 1][1] != o[i][1]]
    d = f"M{_n(pts[0][0])},{_n(pts[0][1])}"
    for a, b in zip(pts, pts[1:]):
        if a[1] != b[1]:
            d += f" L{_n(b[0])},{_n(b[1])}"
            continue
        direction = 1 if b[0] >= a[0] else -1
        y = a[1]
        lo, hi = min(a[0], b[0]) + HOP + 2, max(a[0], b[0]) - HOP - 2
        xs = sorted({v[0][0] for v in vertical if lo < v[0][0] < hi
                     and min(v[0][1], v[1][1]) + HOP < y < max(v[0][1], v[1][1]) - HOP}, key=lambda x: direction * x)
        last = a[0] - direction * HOP * 3
        for x in xs:
            if direction * (x - last) < HOP * 2.5:
                continue
            d += (f" L{_n(x - direction * HOP)},{_n(y)} A{HOP},{HOP} 0 0 {1 if direction > 0 else 0} "
                  f"{_n(x + direction * HOP)},{_n(y)}")
            last = x
        d += f" L{_n(b[0])},{_n(b[1])}"
    return d
