# SPDX-License-Identifier: GPL-3.0-or-later
"""Wire routing (route.py, the same as static/route.js): around the parts,
on the grid, no diagonals, and a hop where wires cross."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from maker_5_edge import route as rt

RECTS = [(0, 0, 190, 200), (400, 0, 190, 100), (200, 300, 100, 60)]
ENDS = [((190, 45, 1), (400, 62, -1)), ((300, 330, 1), (0, 100, -1)), ((190, 150, 1), (590, 80, 1)),
        ((245, 360, 0), (590, 40, 1))]                       # a bottom pin leaves downward
RECTS = [*RECTS[:2], (*RECTS[2], True)]                       # the third part has bottom pins


def _through(seg, rects):
    (ax, ay), (bx, by) = seg
    mx, my = (ax + bx) / 2, (ay + by) / 2
    return any(x + 1 < mx < x + w - 1 and y + 1 < my < y + h - 1 for x, y, w, h, *_ in rects)


def test_wires_go_around_the_parts_with_straight_runs():
    routes = rt.route(ENDS, RECTS)
    for pts, (a, b) in zip(routes, ENDS):
        assert pts[0] == (a[0], a[1]) and pts[-1] == (b[0], b[1])
        for p, q in zip(pts, pts[1:]):
            assert p[0] == q[0] or p[1] == q[1], f"diagonal {p} {q}"
            assert not _through((p, q), RECTS), f"through a part {p} {q}"
    assert routes[0] == [(190, 45), (370, 45), (370, 62), (400, 62)], "a short wire stays simple"
    down = routes[3]
    assert down[0] == (245, 360) and down[1][0] == 245 and down[1][1] >= 360 + rt.STUB - rt.G, "out of the bottom, down"


def test_a_crossing_hops_in_a_half_circle():
    across = [(0, 50), (100, 50)]
    down = [(50, 0), (50, 100)]
    d = rt.path(across, [down])
    assert "A5,5 0 0 1 55,50" in d and d.startswith("M0,50 L45,50")
    assert "A" not in rt.path(down, [across]), "the vertical one does not hop"
    assert "A" not in rt.path([(0, 50), (100, 50)], [[(50, 48), (50, 52)]]), "touching near an end is no crossing"


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_the_page_routes_the_same_way():
    js = Path(__file__).resolve().parent.parent / "maker_5_edge" / "static" / "route.js"
    ends = [[{"x": a[0], "y": a[1], "side": a[2]}, {"x": b[0], "y": b[1], "side": b[2]}] for a, b in ENDS]
    rects = [{"x": x, "y": y, "w": w, "h": h, "bottom": bool(more and more[0])} for x, y, w, h, *more in RECTS]
    code = (f"global.window={{}}; require({json.dumps(str(js))}); const R=window.wireRoute;"
            f"const r=R.route({json.dumps(ends)},{json.dumps(rects)});"
            f"console.log(JSON.stringify({{r:r.map(p=>p.map(q=>[q.x,q.y])), d:r.map((p,i)=>R.path(p,r.filter((_,j)=>j!==i)))}}))")
    got = json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)
    py = rt.route(ENDS, RECTS)
    assert got["r"] == [[list(p) for p in r] for r in py]
    assert got["d"] == [rt.path(r, [o for j, o in enumerate(py) if j != i]) for i, r in enumerate(py)]


def test_a_part_off_the_canvas_keeps_its_pins_and_wires(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "data"))
    from maker_5_edge import products as pr
    P = pr.Products()
    p = P.new_product("Gate bell")["product"]
    a, b = P.add_block(p, "Relay")["id"], P.add_block(p, "Button")["id"]
    P.place(p, a, 0, 0, [{"n": 1, "name": "IN", "role": "signal"}])
    P.place(p, b, 400, 0, [{"n": 1, "name": "A", "role": "signal"}])
    P.add_wire(p, f"{a}.1", f"{b}.1")
    P.unplace(p, a)
    got = next(x for x in P.canvas(p)["blocks"] if x["id"] == a)
    assert got["x"] is None and len(got["pins"]) == 1 and len(P.canvas(p)["wires"]) == 1


def test_pins_take_a_side_and_the_place_they_are_listed(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "data"))
    from maker_5_edge import git_repo, products as pr
    P = pr.Products()
    p = P.new_product("Gate bell")["product"]
    a = P.add_block(p, "Relay")["id"]
    P.place(p, a, 0, 0, [{"n": 1, "name": "IN"}])
    P.set_pins(p, a, [{"n": 3, "name": "C", "side": "left"}, {"n": 1, "name": "A", "side": "left"},
                      {"n": 2, "name": "B", "side": "bottom"}, {"n": 4, "name": "D", "side": "right"}])
    block = next(x for x in P.canvas(p)["blocks"] if x["id"] == a)
    sides = git_repo.pin_sides(block["pins"])
    assert [x["name"] for x in sides["left"]] == ["C", "A"], "as listed, not by number"
    assert [x["name"] for x in sides["bottom"]] == ["B"] and [x["name"] for x in sides["right"]] == ["D"]
    at = git_repo._layout(block)["at"]
    assert at[f"{a}.2"][2] == 0 and at[f"{a}.2"][1] == git_repo._layout(block)["h"], "on the bottom edge"
    assert at[f"{a}.3"][1] < at[f"{a}.1"][1]
    with pytest.raises(ValueError):
        P.set_pins(p, a, [{"n": 1, "name": "A", "side": "top"}])
    P.notes(p, a, "  Switches the gate. Check the coil is 5 V.  ")
    assert next(x for x in P.canvas(p)["blocks"] if x["id"] == a)["notes"] == "Switches the gate. Check the coil is 5 V."
    P.notes(p, a, "")
    assert next(x for x in P.canvas(p)["blocks"] if x["id"] == a)["notes"] == ""


def test_a_long_header_without_sides_is_odd_left_even_right():
    from maker_5_edge import git_repo
    pins = [{"id": f"b.{n}", "n": n, "name": f"P{n}"} for n in range(1, 27)] + [{"id": "b.27", "n": 27, "name": "USB 1", "side": "bottom"}]
    s = git_repo.pin_sides(pins)
    assert [x["n"] for x in s["left"]][:3] == [1, 3, 5] and [x["n"] for x in s["right"]][:3] == [2, 4, 6]
    assert [x["n"] for x in s["bottom"]] == [27]
