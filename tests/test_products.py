# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""Products and their model: one folder each, the Maker-5 shapes on every
save, proposals that only a person decides, and every saved state kept.
Every product and name here is invented."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from rdflib import Graph, URIRef

from maker_5_edge import inbox as ib
from maker_5_edge import products as pr
from maker_5_edge import revisions as rv
from maker_5_edge import selection as sel
from maker_5_edge.edge import knowledge as kn

PKG = Path(pr.__file__).parent


@pytest.fixture
def data(tmp_path, monkeypatch):
    root = tmp_path / "mydocs"
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(root))
    sel.set()
    yield root
    sel.set()


@pytest.fixture
def P(data):
    return pr.Products()


@pytest.fixture
def p(P):
    return P.new_product("Weather box")["product"]


def test_a_product_is_a_folder_with_its_model(data, P, p):
    assert re.fullmatch(r"p-[a-z0-9]{8}", p)
    assert (data / p / "model.ttl").is_file() and not (data / "abox").exists()
    assert (data / p).stat().st_mode & 0o777 == 0o700
    assert [x["product"] for x in P.products()] == [p]


def test_reserved_folders_are_never_products(data):
    kb = pr.ProductKB()
    for name in ("abox", "inbox", "files", "revisions"):
        with pytest.raises(ValueError):
            kb.load(name)
    (data / "inbox").mkdir(parents=True)
    (data / "inbox" / "model.ttl").write_text("")
    assert "inbox" not in kb.graphs()


def test_renaming_changes_the_title_not_the_folder(data, P, p):
    P.set_product(p, title="Weather box, rev B")
    assert P.products()[0]["title"] == "Weather box, rev B" and (data / p / "model.ttl").is_file()


def test_the_model_reads_back_what_was_added(P, p):
    b = P.add_block(p, "Sensor board", "electronic")["id"]
    P.add_block(p, "Enclosure", "mechanical")
    m = P.add_module(p, "Sensor firmware")["id"]
    i = P.add_interface(p, "I2C bus", [b, m])["id"]
    got = P.model(p)
    assert [x["name"] for x in got["blocks"]] == ["Enclosure", "Sensor board"]
    assert {x["kind"] for x in got["blocks"]} == {"electronic", "mechanical"}
    assert got["interfaces"][0]["id"] == i
    assert {c["id"] for c in got["interfaces"][0]["connects"]} == {b, m}
    assert P.products()[0] | {} == {**P.products()[0], "blocks": 2, "modules": 1}


def test_the_shapes_refuse_a_broken_model_and_nothing_is_saved(P, p):
    b = P.add_block(p, "Sensor board")["id"]
    before = P.model(p)
    with pytest.raises(kn.Invalid) as e:
        P.add_interface(p, "Half a bus", [b])
    assert any("at least two" in m for m in e.value.messages)
    assert P.model(p) == before
    with pytest.raises(ValueError):
        P.add_block(p, "Board", "hydraulic")


def test_a_connected_block_cannot_be_removed(P, p):
    b = P.add_block(p, "Sensor board")["id"]
    m = P.add_module(p, "Firmware")["id"]
    i = P.add_interface(p, "I2C bus", [b, m])["id"]
    with pytest.raises(ValueError, match="connected by I2C bus"):
        P.remove(p, b)
    P.remove(p, i)
    P.remove(p, b)
    assert P.model(p)["blocks"] == []


def test_a_proposal_waits_for_a_person_and_the_decision_is_prov(data, P, p):
    b = P.add_block(p, "Sensor board")["id"]
    pid = P.propose(p, "Add a humidity sensor", [b], agent="chat")["id"]
    got = P.model(p)["proposals"][0]
    assert got["state"] == "proposed" and got["by"] == "chat" and got["concerns"][0]["id"] == b
    assert P.products()[0]["open_proposals"] == 1
    P.decide(p, pid, "approved", note="fine")
    got = P.model(p)["proposals"][0]
    assert got["state"] == "approved" and got["decided"]["note"] == "fine" and got["decided"]["by"]
    with pytest.raises(ValueError, match="decided already"):
        P.decide(p, pid, "rejected")
    g = Graph().parse(data / p / "model.ttl")
    PROV = "http://www.w3.org/ns/prov#"
    acts = list(g.subjects(URIRef(PROV + "used"), None))
    assert len(acts) == 1 and (acts[0], URIRef(PROV + "wasAssociatedWith"), None) in g
    with pytest.raises(ValueError):
        P.decide(p, pid, "maybe")


def test_every_change_is_a_revision_and_restore_adds_one(P, p):
    P.add_block(p, "Sensor board")
    with rv.acting("mcp"):
        P.add_module(p, "Firmware")
    revs = P.revisions(p)
    assert [r["n"] for r in revs] == [3, 2, 1] and revs[0]["via"] == "mcp"
    assert revs[0]["summary"] == "+ SoftwareModule Firmware"
    P.tag_revision(p, "2", "Prototype A", frozen=True)
    with pytest.raises(ValueError):
        P.tag_revision(p, "3", "Prototype A")
    assert [a["label"] for a in P.diff(p, "Prototype A")["added"]] == ["Firmware"]
    assert P.restore(p, "Prototype A") == {"restored": 2, "revision": 4}
    assert P.model(p)["modules"] == [] and len(P.revisions(p)) == 4


def test_the_old_layout_moves_once(data):
    old = data / "abox"
    (old / ".sync" / "stage").mkdir(parents=True)
    P_old = pr.Products(kn.KnowledgeBase(old))
    p = P_old.new_product("Bench supply")["product"]
    (old / ".sync" / "stage" / f"{p}.json").write_text('{"version": 3}')
    assert pr.migrate_layout(data) == [p]
    assert (data / p / "model.ttl").is_file() and not old.exists()
    assert (data / ".sync" / "stage" / f"{p}.json").read_text() == '{"version": 3}'
    assert pr.migrate_layout(data) == []
    assert pr.Products().products()[0]["title"] == "Bench supply"


def test_files_given_with_a_product_open_go_into_its_folder(data, P, p):
    loose = ib.add("notes.txt", b"a loose note")
    sel.set(product=p)
    kept = ib.add("board.kicad_pcb", b'(kicad_pcb (version 20240108)\n (footprint "R_0603" ))')
    assert (data / p / "files" / kept["id"] / "file").is_file()
    assert kept["kind"] == "kicad" and "1 footprint" in kept["note"]
    assert {f["id"] for f in ib.files()} == {loose["id"], kept["id"]}
    sel.set()
    assert [f["id"] for f in ib.files()] == [loose["id"]]
    assert ib.meta(kept["id"])["name"] == "board.kicad_pcb"


def test_every_string_is_in_english_german_and_french():
    table = json.loads((PKG / "static" / "i18n.json").read_text())
    keys = set(table["en"])
    assert set(table["de"]) == keys and set(table["fr"]) == keys
    assert set(table["edge"]["de"]) == set(table["edge"]["fr"])
    for lang in ("de", "fr"):
        for k, v in table[lang].items():
            assert set(re.findall(r"\{(\w+)\}", v)) == set(re.findall(r"\{(\w+)\}", table["en"][k])), (lang, k)
    js = (PKG / "static" / "app.js").read_text() + (PKG / "static" / "canvas.js").read_text() + (PKG / "static" / "code.js").read_text()
    html = (PKG / "templates" / "index.html").read_text()
    used = set(re.findall(r'(?<![\w.$])t\("([\w.]+)"', js))
    used |= set(re.findall(r'data-(?:i18n(?:-title|-placeholder)?|help)="([\w.]+)"', html + js))
    for tmpl, values in ((r"model\.add\.", ("block", "module", "interface")), (r"model\.ph\.", ("block", "module", "interface")),
                         (r"help\.add\.", ("block", "module", "interface")), (r"h\.via\.", rv.VIA),
                         (r"state\.", ("proposed", "approved", "rejected")), (r"kind\.", ("electronic", "mechanical")),
                         (r"supply\.", ("there", "in-hand", "to-buy")), (r"role\.", ("power", "ground", "signal", "audio", "video", "data")),
                         (r"hw\.c\.", ("red", "black", "yellow", "white", "blue", "green", "orange", "purple"))):
        used |= {tmpl.replace("\\", "") + v for v in values}
    assert used and not used - keys, sorted(used - keys)
