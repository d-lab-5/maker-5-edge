# SPDX-License-Identifier: GPL-3.0-or-later
"""A workspace's model from stage into an empty prod workspace, or from its
repository (migrate.py; ADR-0013 and ADR-0017 in maker-5-shared, amended).
The cloud is a fake; every name is invented."""

from __future__ import annotations

import pytest
from rdflib import RDF

from maker_5_edge import app as web
from maker_5_edge import git_repo as gr
from maker_5_edge import migrate as mg
from maker_5_edge import products as pr
from maker_5_edge.edge import cloud, settings

M5 = pr.M5


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SYNC_SCOPE", "per-connection")
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "mymaker5docs"))
    monkeypatch.setattr(cloud, "linked_profiles", lambda: [])
    monkeypatch.setattr(cloud, "profiles", lambda: {"prod": {}, "stage": {}})
    monkeypatch.setattr(web, "_products", None)
    cloud.use_profile("stage")
    stage = pr.Products(pr.ProductKB(profile="stage"))
    src = stage.new_product("Door bell")["product"]
    pi = stage.add_block(src, "Raspberry Pi 1", "electronic")["id"]
    opto = stage.add_block(src, "Optocoupler PC817", "electronic")["id"]
    stage.add_module(src, "Ring listener")
    stage.add_interface(src, "Call line", [pi, opto])
    stage.link_article(src, pi, "a-23456789ab", 1)
    stage.propose(src, "Use a relay instead")
    cloud.use_profile("prod")
    prod = pr.Products(pr.ProductKB(profile="prod"))
    dst = prod.new_product("Door bell (prod)")["product"]
    return {"stage": stage, "src": src, "prod": prod, "dst": dst, "pi": pi}


def test_a_dry_run_says_what_comes_and_writes_nothing(env):
    got = mg.plan(env["prod"], env["dst"], {"profile": "stage", "product": env["src"]})
    assert got["dry_run"] and got["empty"] and "refused" not in got
    assert got["brings"]["blocks"] == 2 and got["brings"]["modules"] == 1 and got["brings"]["interfaces"] == 1
    assert got["left_behind"] > 0, "the stock link, the quantity and the proposal stay"
    assert not mg._filled(env["prod"]._exists(env["dst"]))


def test_a_copy_brings_the_open_model_and_leaves_the_clouds_own(env):
    mg.copy(env["prod"], env["dst"], {"profile": "stage", "product": env["src"]})
    g = env["prod"]._exists(env["dst"])
    assert len(set(g.subjects(RDF.type, M5.Block))) == 2
    assert pr._iri("block", env["pi"]) in set(g.subjects(RDF.type, M5.Block)), "ids are kept"
    assert not list(g.subjects(RDF.type, M5.Proposal)) and not list(g.triples((None, M5.usesArticle, None)))
    assert not list(g.triples((None, M5.quantity, None)))
    products = list(g.subjects(RDF.type, M5.Product))
    assert products == [pr._iri("product", env["dst"])], "the workspace keeps its own product"
    assert pr._name(g, products[0]) == "Door bell (prod)"
    assert all(o == products[0] for o in g.objects(None, M5.partOf)), "everything is part of it"


def test_a_copy_is_a_revision_of_its_own(env):
    before = len(env["prod"].revisions(env["dst"]))
    mg.copy(env["prod"], env["dst"], {"profile": "stage", "product": env["src"]})
    assert len(env["prod"].revisions(env["dst"])) == before + 1


def test_only_an_empty_workspace_takes_a_copy_and_only_once(env):
    src = {"profile": "stage", "product": env["src"]}
    mg.copy(env["prod"], env["dst"], src)
    assert mg.plan(env["prod"], env["dst"], src)["refused"]
    with pytest.raises(mg.MigrateError):
        mg.copy(env["prod"], env["dst"], src)


def test_a_copy_goes_across_never_within_one_connection(env):
    with pytest.raises(mg.MigrateError):
        mg.plan(env["prod"], env["dst"], {"profile": "prod", "product": env["dst"]})
    with pytest.raises(mg.MigrateError):
        mg.plan(env["prod"], env["dst"], {"profile": "../etc", "product": "x"})


def test_the_sources_are_the_other_connections_filled_workspaces(env):
    got = mg.sources(env["prod"], env["dst"])
    assert got["empty"] and got["repo"] is None
    assert [(s["profile"], s["product"], s["blocks"]) for s in got["connections"]] == [("stage", env["src"], 2)]


def test_the_page_asks_for_a_dry_run_first(env):
    web._products = env["prod"]
    c = web.app.test_client()
    src = {"profile": "stage", "product": env["src"]}
    r = c.post(f"/api/products/{env['dst']}/migrate", json={"from": src})
    assert r.status_code == 200 and r.get_json()["dry_run"]
    assert not mg._filled(env["prod"]._exists(env["dst"]))
    r = c.post(f"/api/products/{env['dst']}/migrate", json={"from": src, "dry_run": False})
    assert r.status_code == 200 and r.get_json()["brings"]["blocks"] == 2
    r = c.post(f"/api/products/{env['dst']}/migrate", json={"from": src, "dry_run": False})
    assert r.status_code == 409


def test_the_chat_cannot_propose_a_copy():
    import re
    assert not any(m == "POST" and re.fullmatch(rx, "/api/products/door-bell/migrate") for m, rx in settings.CHAT_ALLOWED)


def test_a_repository_fills_an_empty_workspace(env, tmp_path):
    published = gr.public_model(env["stage"]._exists(env["src"])).serialize(format="turtle")
    d = gr.repo_dir(env["prod"], env["dst"])
    (d / "hardware").mkdir(parents=True)
    (d / ".git").mkdir()
    (d / "hardware" / "model.ttl").write_text(published, encoding="utf-8")
    assert mg.sources(env["prod"], env["dst"])["repo"]["blocks"] == 2
    mg.copy(env["prod"], env["dst"], {"repo": True})
    g = env["prod"]._exists(env["dst"])
    assert len(set(g.subjects(RDF.type, M5.Block))) == 2
    assert pr._name(g, pr._iri("product", env["dst"])) == "Door bell (prod)"


def test_a_broken_repository_model_writes_nothing(env):
    d = gr.repo_dir(env["prod"], env["dst"])
    (d / "hardware").mkdir(parents=True)
    (d / ".git").mkdir()
    (d / "hardware" / "model.ttl").write_text("this is not turtle <", encoding="utf-8")
    with pytest.raises(mg.MigrateError):
        mg.copy(env["prod"], env["dst"], {"repo": True})
    assert not mg._filled(env["prod"]._exists(env["dst"]))
