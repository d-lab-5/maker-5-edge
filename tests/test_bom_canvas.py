# SPDX-License-Identifier: GPL-3.0-or-later
"""A BOM in Markdown into the model, and the hardware canvas (ADR-0014 in
maker-5-shared). The BOM and the cloud are invented."""

from __future__ import annotations

import pytest

from maker_5_edge import app as web
from maker_5_edge import bom_import as bi
from maker_5_edge import materials as mt
from maker_5_edge import parts
from maker_5_edge import products as pr

BOM = """# Garden gate bell: bill of materials

## Hardware

### Already there

| Part | Notes |
|---|---|
| Gate station | 4 wires |
| Old enclosure | keep |

### In hand

| Part | Status |
|---|---|
| Raspberry Pi 1 Model B (512 MB, no Wi-Fi) | running |

### To buy or build

| Part | Purpose | Notes |
|---|---|---|
| Optocoupler PC817 | detects the call | depends on a measurement |
| Step-down 12 V to 5 V | powers the Pi | |
| Multimeter | for the measurements | tools, not parts |

## Software

### On the Pi (gate)

| Component | Version | Role |
|---|---|---|
| `gate` adapter (`index.js`) | 0.1 | rings |
| ffmpeg | 5.1 | pictures |
"""


@pytest.fixture
def P(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "mydocs"))
    pp = pr.Products()
    pp.new_product("Gate bell")
    return pp


@pytest.fixture
def cloud(monkeypatch):
    seen = {"proposed": []}
    stock = [{"id": "a-abcdefghjk", "name": "Step-down 12 V to 5 V"}]
    monkeypatch.setattr(mt, "stock", lambda q="", category="", profile=None: list(stock))

    def propose(articles, profile=None):
        seen["proposed"].extend(articles)
        return [{"id": f"a-{'mnpqrstuv'[i]}bcdefghjk", "name": a["name"], "status": "proposed"} for i, a in enumerate(articles)]
    monkeypatch.setattr(mt, "propose", propose)
    return seen


def product(P):
    return P.products()[0]["product"]


def test_a_bom_is_read_by_its_headings_and_tables():
    rows = bi.parse(BOM)
    assert [r["name"] for r in rows][:3] == ["Gate station", "Old enclosure", "Raspberry Pi 1 Model B (512 MB, no Wi-Fi)"]
    assert rows[-1]["section"] == "software" and rows[-1]["cols"]["version"] == "5.1"
    assert rows[-2]["name"] == "gate adapter (index.js)", "inline marks off"


def test_the_preview_writes_nothing_and_says_what_it_would_make(P, cloud):
    p = product(P)
    before = P.export(p)
    pv = bi.preview(P, p, BOM)
    assert P.export(p) == before
    b = {x["name"]: x for x in pv["blocks"]}
    assert b["Raspberry Pi 1 Model B"]["supply"] == "in-hand" and "512 MB" in b["Raspberry Pi 1 Model B"]["description"]
    assert b["Raspberry Pi 1 Model B"]["propose"]["tracking"] == "serial"
    assert b["Optocoupler PC817"]["supply"] == "to-buy" and b["Optocoupler PC817"]["propose"]["category"] == "components/semiconductors"
    assert b["Step-down 12 V to 5 V"]["article"]["id"] == "a-abcdefghjk" and b["Step-down 12 V to 5 V"]["propose"] is None
    assert b["Old enclosure"]["kind"] == "mechanical"
    assert b["Gate station"]["include_article"] is False, "a part already there is not proposed by default"
    assert [t["name"] for t in pv["tools"]] == ["Multimeter"] and "Multimeter" not in b
    assert {m["name"]: m["runs_on"] for m in pv["modules"]} == {"gate adapter (index.js)": "Raspberry Pi 1 Model B",
                                                                  "ffmpeg": "Raspberry Pi 1 Model B"}


def test_apply_proposes_articles_then_makes_one_revision_and_runs_again(P, cloud):
    p = product(P)
    before = max(r["n"] for r in P.revisions(p))
    out = bi.apply(P, p, bi.preview(P, p, BOM))
    assert sorted(a["name"] for a in cloud["proposed"]) == ["Multimeter", "Optocoupler PC817", "Raspberry Pi 1 Model B"]
    assert out["made"]["blocks"] and out["made"]["modules"] == ["gate adapter (index.js)", "ffmpeg"]
    assert max(r["n"] for r in P.revisions(p)) == before + 1, "one revision"
    m = P.model(p)
    blocks = {x["name"]: x for x in m["blocks"]}
    assert blocks["Step-down 12 V to 5 V"]["article"] == "a-abcdefghjk"
    assert blocks["Optocoupler PC817"]["article"].startswith("a-") and blocks["Optocoupler PC817"]["supply"] == "to-buy"
    assert {x["name"]: x["version"] for x in m["modules"]}["ffmpeg"] == "5.1"
    assert all(x["runs_on"] == blocks["Raspberry Pi 1 Model B"]["id"] for x in m["modules"])
    again = bi.preview(P, p, BOM)
    assert not again["blocks"] and not again["modules"] and len(again["skipped"]) == 7


def test_the_canvas_places_blocks_with_pins_and_wires_them(P, cloud):
    p = product(P)
    bi.apply(P, p, bi.preview(P, p, BOM))
    blocks = {x["name"]: x["id"] for x in P.model(p)["blocks"]}
    pi, opto = blocks["Raspberry Pi 1 Model B"], blocks["Optocoupler PC817"]
    client = web.app.test_client()
    web._products = P
    try:
        assert client.post(f"/api/products/{p}/canvas/place", json={"block": pi, "x": 40, "y": 80}).status_code == 200
        assert client.post(f"/api/products/{p}/canvas/place", json={"block": opto, "x": 400, "y": 80}).status_code == 200
        c = client.get(f"/api/products/{p}/canvas").get_json()
        got = {b["id"]: b for b in c["blocks"]}
        assert (got[pi]["x"], got[pi]["y"]) == (40, 80)
        assert next(x for x in got[pi]["pins"] if x["n"] == 11)["name"] == "GPIO17"
        assert [x["name"] for x in got[opto]["pins"]] == ["Anode", "Cathode", "Emitter", "Collector"]
        r = client.post(f"/api/products/{p}/wires", json={"from": f"{opto}.4", "to": f"{pi}.11", "color": "yellow"})
        assert r.status_code == 200, r.get_json()
        w = r.get_json()["id"]
        assert client.post(f"/api/products/{p}/wires", json={"from": f"{pi}.11", "to": f"{opto}.4"}).status_code == 400, "wired already"
        assert client.post(f"/api/products/{p}/wires", json={"from": f"{pi}.11", "to": f"{pi}.99"}).status_code == 404
        assert client.post(f"/api/products/{p}/wires", json={"from": f"{pi}.1", "to": f"{pi}.6", "color": "red;x"}).status_code == 400
        wires = client.get(f"/api/products/{p}/canvas").get_json()["wires"]
        assert len(wires) == 1 and wires[0]["color"] == "yellow"
        r = client.post(f"/api/products/{p}/canvas/pins", json={"block": opto, "pins": [{"n": 1, "name": "A"}]})
        assert r.status_code == 400 and "wired" in r.get_json()["errors"][0], "a wired pin stays"
        assert client.delete(f"/api/products/{p}/items/{w}").status_code == 200
        assert client.delete(f"/api/products/{p}/items/{opto}").status_code == 200
        c = client.get(f"/api/products/{p}/canvas").get_json()
        assert opto not in {b["id"] for b in c["blocks"]} and c["wires"] == []
        assert pr.ID + "pin/" + opto not in P.export(p), "its pins went with it"
    finally:
        web._products = None


def test_a_wire_on_a_removed_block_goes_with_it(P, cloud):
    p = product(P)
    bi.apply(P, p, bi.preview(P, p, BOM))
    blocks = {x["name"]: x["id"] for x in P.model(p)["blocks"]}
    pi, opto = blocks["Raspberry Pi 1 Model B"], blocks["Optocoupler PC817"]
    P.place(p, pi, 0, 0, parts.pins_for("Raspberry Pi 1 Model B")["pins"])
    P.place(p, opto, 300, 0, parts.pins_for("PC817")["pins"])
    P.add_wire(p, f"{opto}.3", f"{pi}.6", "black")
    P.remove(p, opto)
    assert P.canvas(p)["wires"] == []


def test_the_parts_library_knows_the_usual_parts():
    assert parts.pins_for("Raspberry Pi 1 Model B")["pins"][10]["name"] == "GPIO17"
    assert parts.pins_for("LM386 amplifier board")["title"].startswith("LM386")
    assert parts.pins_for("Something else")["pins"] == parts.GENERIC


def test_categories_are_guessed_in_two_levels():
    """ADR-0019: the first, most particular match wins."""
    from maker_5_edge.bom_import import CATEGORY_WORDS, _words
    guess = lambda n: _words(n, CATEGORY_WORDS)  # noqa: E731
    assert guess("USB sound card") == "media/audio", "not storage"
    assert guess("SanDisk 16 GB microSD card") == "controllers/storage"
    assert guess("Raspberry Pi 1 Model B") == "controllers/sbc"
    assert guess("Step-down 12 V to 5 V") == "power/converters"
    assert guess("Optocoupler PC817") == "components/semiconductors"
    assert guess("Multimeter") == "tools/measuring"
    assert guess("Terminal block, 2 way") == "cables/connectors"
