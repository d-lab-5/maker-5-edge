# SPDX-License-Identifier: GPL-3.0-or-later
"""Parts from the Fritzing library (ADR-0016 in maker-5-shared). The library
is a fake: the part and its picture are invented, nothing is fetched."""

from __future__ import annotations

import json

import pytest

from maker_5_edge import app as web
from maker_5_edge import fritzing as fz
from maker_5_edge import products as pr

FZP = b"""<?xml version='1.0' encoding='UTF-8'?>
<module moduleId="EXAMPLE_OPTO_1">
 <author>A. Maker</author>
 <title>Example optocoupler</title>
 <properties><property name="family">Optocoupler</property></properties>
 <views><breadboardView><layers image="breadboard/example_opto.svg"><layer layerId="breadboard"/></layers></breadboardView></views>
 <connectors>
  <connector id="connector0" name="Pin 1"><description>Anode</description></connector>
  <connector id="connector1" name="Pin 2"><description>Cathode</description></connector>
  <connector id="connector2" name="GND"><description>ground</description></connector>
  <connector id="connector3" name="VCC"><description>supply</description></connector>
 </connectors>
</module>"""
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="1in" height="1in"><rect width="10" height="10"/></svg>'
TREE = {"tree": [{"type": "blob", "path": "core/Example_Opto.fzp"}, {"type": "blob", "path": "obsolete/Example_Opto.fzp"},
                 {"type": "blob", "path": "contrib/Example_Opto_Board_0123456789abcdef0123456789abcdef_3.fzp"},
                 {"type": "blob", "path": "svg/core/breadboard/example_opto.svg"}]}


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "data"))
    got = []

    def fetch(url, limit):
        got.append(url)
        if url == fz.TREE:
            return json.dumps(TREE).encode()
        if url == fz.RAW + "core/Example_Opto.fzp":
            return FZP
        if url == fz.RAW + "svg/core/breadboard/example_opto.svg":
            return SVG
        raise fz.FritzingError(f"not in the fake: {url}")
    monkeypatch.setattr(fz, "_fetch", fetch)
    return got


def test_search_reads_the_tree_once_and_finds_by_words(lib):
    hits = fz.search("example opto")
    assert [h["path"] for h in hits] == ["core/Example_Opto.fzp",
                                         "contrib/Example_Opto_Board_0123456789abcdef0123456789abcdef_3.fzp"], "core first, no obsolete"
    assert hits[1]["name"] == "Example Opto Board", "a contrib part's hash is not its name"
    fz.search("opto")
    assert lib.count(fz.TREE) == 1, "the list is kept"


def test_a_part_gives_its_pins_with_names_and_roles(lib):
    p = fz.part("core/Example_Opto.fzp")
    assert p["title"] == "Example optocoupler" and p["author"] == "A. Maker" and p["license"] == "CC BY-SA 3.0"
    assert [(x["n"], x["name"], x["role"]) for x in p["pins"]] == [
        (1, "Anode", "signal"), (2, "Cathode", "signal"), (3, "GND", "ground"), (4, "VCC", "power")]
    fz.part("core/Example_Opto.fzp")
    assert lib.count(fz.RAW + "core/Example_Opto.fzp") == 1, "fetched once"
    assert fz.image("core/Example_Opto.fzp") == SVG


def test_only_parts_of_the_list_are_fetched(lib):
    for bad in ("obsolete/Example_Opto.fzp", "core/../x.fzp", "https://example.org/x.fzp", "core/Missing.fzp"):
        with pytest.raises(ValueError):
            fz.part(bad)
    assert all(u == fz.TREE for u in lib)


def test_a_block_takes_a_part_and_the_canvas_shows_it(lib, tmp_path):
    P = pr.Products()
    p = P.new_product("Gate bell")["product"]
    b = P.add_block(p, "Opto")["id"]
    web._products = P
    try:
        c = web.app.test_client()
        r = c.post(f"/api/products/{p}/canvas/fritzing", json={"block": b, "path": "core/Example_Opto.fzp"})
        assert r.status_code == 200, r.get_json()
        got = next(x for x in P.canvas(p)["blocks"] if x["id"] == b)
        assert got["fritzing"] == "core/Example_Opto.fzp" and [x["name"] for x in got["pins"]][:2] == ["Anode", "Cathode"]
        img = c.get("/api/fritzing/image?path=core/Example_Opto.fzp")
        assert img.status_code == 200 and img.mimetype == "image/svg+xml"
        assert "default-src 'none'" in img.headers["Content-Security-Policy"]
        assert c.get("/api/fritzing/image?path=core/../x.fzp").status_code == 404
        assert c.get("/api/fritzing/search?q=opto").get_json()[0]["path"] == "core/Example_Opto.fzp"
    finally:
        web._products = None


def test_the_library_out_of_reach_is_said(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "data"))

    def down(url, limit):
        raise fz.FritzingError("the Fritzing library could not be reached: offline")
    monkeypatch.setattr(fz, "_fetch", down)
    r = web.app.test_client().get("/api/fritzing/search?q=pi")
    assert r.status_code == 502 and "could not be reached" in r.get_json()["errors"][0]


def test_a_boards_pins_are_numbered_as_the_board_is():
    from maker_5_edge import parts
    known = parts.pins_for("Raspberry Pi 1 Model B")["pins"]
    fritz = [{"n": 16, "name": "GPIO 4", "role": "signal"}, {"n": 8, "name": "GPIO 14", "role": "signal"},
             {"n": 1, "name": "GND", "role": "ground"}, {"n": 2, "name": "GND", "role": "ground"}, {"n": 3, "name": "3V3", "role": "power"}]
    got = parts.physical(fritz, known)
    assert [(p["n"], p["name"]) for p in got] == [(1, "3V3"), (6, "GND"), (7, "GPIO 4"), (8, "GPIO 14"), (9, "GND")]
    assert parts.physical([{"n": 1, "name": "Nothing here", "role": "signal"}], known)[0]["n"] == 1, "unknown: kept"


def test_a_boards_ports_stay_when_it_takes_a_part():
    """A Fritzing part models only the header: the board's USB, video, audio,
    Ethernet and power sockets from the library come after it, for cables."""
    from maker_5_edge import parts
    known = parts.pins_for("Raspberry Pi 1 Model B")["pins"]
    header = parts.physical([{"n": 1, "name": "3V3", "role": "power"}, {"n": 2, "name": "GPIO 17", "role": "signal"}], known)
    got = parts.with_ports(header, known)
    assert [p["name"] for p in got] == ["3V3", "GPIO 17", "USB 1", "USB 2", "Ethernet", "Audio out", "Video out", "5V in (micro USB)"]
    assert [p["role"] for p in got if p["name"] in ("Video out", "Audio out", "USB 1")] == ["data", "audio", "video"]
    assert len({p["n"] for p in got}) == len(got), "numbers stay unique"


def test_the_part_the_library_names_for_a_block_comes_first(lib):
    hits = web.app.test_client().get("/api/fritzing/search?q=opto&for=Raspberry Pi 1 Model B").get_json()
    assert hits[0] == {"path": "core/Raspberry_Pi_B(rev2).fzp", "name": "Raspberry Pi B(rev2)", "folder": "core", "suggested": True}
    assert hits[1]["path"] == "core/Example_Opto.fzp"


def test_a_blocks_whole_name_finds_the_closest_parts(lib):
    assert [h["path"] for h in fz.search("example opto pc817 board")] == [
        "contrib/Example_Opto_Board_0123456789abcdef0123456789abcdef_3.fzp", "core/Example_Opto.fzp"]
