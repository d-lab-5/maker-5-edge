# SPDX-License-Identifier: GPL-3.0-or-later
"""A block's picture (ADR-0021 in maker-5-shared): Wokwi elements shipped
with the edge, a drawing from the block's pins, and the agent's SVG, checked."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from maker_5_edge import app as web
from maker_5_edge import drawing
from maker_5_edge import products as pr
from maker_5_edge import wokwi

PINS = [{"n": 1, "name": "VCC", "role": "power"}, {"n": 2, "name": "IN", "role": "signal"}, {"n": 3, "name": "GND", "role": "ground"}]


def good(pins=(1, 2, 3), extra=""):
    marks = "".join(f'<circle data-pin="{n}" cx="{10 * n}" cy="10" r="3" fill="#cc0000"/>' for n in pins)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40"><rect width="100" height="40" fill="#225533"/>{marks}{extra}</svg>'


def test_the_wokwi_elements_ship_with_their_pins_and_licence():
    assert wokwi.credit()["license"] == "MIT"
    hits = wokwi.search("esp32")
    assert hits[0]["name"] == "esp32-devkit-v1"
    p = wokwi.part("esp32-devkit-v1")
    assert len(p["pins"]) == 30 and {"VIN", "GND.2"} <= {x["name"] for x in p["pins"]}
    ET.fromstring(wokwi.image("arduino-uno"))                     # well-formed XML, entities fixed
    with pytest.raises(ValueError):
        wokwi.part("../index")


def test_a_drawing_from_the_pins_marks_every_pin():
    svg = drawing.generated("Door relay", PINS)
    assert drawing.clean(svg, PINS) == svg.strip()                  # it passes its own check


@pytest.mark.parametrize("bad, why", [
    (good(extra="<script>alert(1)</script>"), "<script>"),
    (good(extra='<image href="https://example.org/x.png"/>'), "<image>"),
    (good().replace("<rect ", '<rect onload="x()" '), "onload"),
    ('<!DOCTYPE svg [<!ENTITY x "y">]>' + good(), "DOCTYPE"),
    (good().replace('fill="#225533"', "fill=\"url('https://example.org/a')\""), "external"),
    (good().replace('<rect ', '<rect style="fill:red" '), "style"),
    (good(pins=(1, 2)), "[3] are not in the drawing"),
    (good(pins=(1, 2, 3, 4)), "data-pin [4]"),
    (good(pins=(1, 2, 3, 3)), "more than once"),
    (good().replace(' viewBox="0 0 100 40"', ""), "viewBox"),
    ("<svg" + " " * 40_001 + "/>", "at most"),
])
def test_an_agents_drawing_is_refused_with_the_reason(bad, why):
    with pytest.raises(drawing.DrawingError, match=__import__("re").escape(why)):
        drawing.clean(bad, PINS)


def test_one_source_at_a_time_and_none_keeps_the_pins(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "data"))
    P = pr.Products()
    p = P.new_product("Gate bell")["product"]
    b = P.add_block(p, "Door relay")["id"]
    P.set_pins(p, b, PINS)
    web._products = P
    try:
        c = web.app.test_client()
        block = lambda: next(x for x in P.canvas(p)["blocks"] if x["id"] == b)  # noqa: E731
        assert c.post(f"/api/products/{p}/canvas/image", json={"block": b, "kind": "drawn"}).status_code == 200
        assert block()["image"] == {"kind": "drawn", "ref": ""}
        r = c.get(f"/api/products/{p}/blocks/{b}/image.svg")
        assert r.mimetype == "image/svg+xml" and "default-src 'none'" in r.headers["Content-Security-Policy"] and b'data-pin="3"' in r.data
        bad = c.post(f"/api/products/{p}/canvas/image", json={"block": b, "kind": "agent", "svg": good(pins=(1,))})
        assert bad.status_code == 400 and "not in the drawing" in bad.get_json()["errors"][0]
        assert c.post(f"/api/products/{p}/canvas/image", json={"block": b, "kind": "agent", "svg": good()}).status_code == 200
        assert block()["image"]["kind"] == "agent" and c.get(f"/api/products/{p}/blocks/{b}/image.svg").data.startswith(b"<svg")
        assert "partDrawing" in P.export(p) and "partImage" not in P.export(p), "one source at a time"
        assert c.post(f"/api/products/{p}/canvas/image", json={"block": b, "kind": "wokwi", "ref": "led"}).status_code == 200
        assert block()["image"] == {"kind": "wokwi", "ref": "led"} and [x["name"] for x in block()["pins"]] == ["A", "C"]
        assert "partDrawing" not in P.export(p)
        assert c.post(f"/api/products/{p}/canvas/image", json={"block": b, "kind": "none"}).status_code == 200
        assert block()["image"]["kind"] == "none" and len(block()["pins"]) == 2
        assert c.post(f"/api/products/{p}/canvas/image", json={"block": b, "kind": "photo"}).status_code == 400
    finally:
        web._products = None


def test_the_chat_may_propose_a_picture():
    import re
    from maker_5_edge.edge import settings
    assert any(m == "POST" and re.fullmatch(rx, "/api/products/p-abc/canvas/image") for m, rx in settings.CHAT_ALLOWED)
    from maker_5_edge import mcp_server
    assert "data-pin" in mcp_server.image_skill()
