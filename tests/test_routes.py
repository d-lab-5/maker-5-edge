# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""The page's API: products, the model, proposals, history, files and the
selection, and what the chat may and may not run."""

from __future__ import annotations

import re

import pytest

from maker_5_edge import app as web
from maker_5_edge import products as pr
from maker_5_edge import selection as sel
from maker_5_edge.core import version
from maker_5_edge.edge import settings

PAGE = {"User-Agent": "Mozilla/5.0"}
AGENT = {"X-Agent": "maker-5-edge-mcp"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKER5_EDGE_EDGE_STATE", str(tmp_path / "cloud.json"))
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(version, "UPDATE_CHECK", False)
    monkeypatch.setattr(web, "_products", pr.Products(pr.ProductKB(tmp_path / "data")))
    sel.set()
    web.app.config["TESTING"] = True
    yield web.app.test_client()
    sel.set()


def test_the_page_renders_its_shell(client):
    html = client.get("/").get_data(as_text=True)
    for needed in ('id="ws-list"', 'data-tab="model"', 'data-tab="proposals"', 'data-tab="history"',
                   'data-tab="files"', 'id="help-on"', 'id="lang-pick"', 'id="btn-side"', 'id="edge-chat"',
                   "manifest.webmanifest", "i18n.js"):
        assert needed in html, needed
    assert client.get("/static/i18n.json").status_code == 200
    assert client.get("/static/icon.svg").status_code == 200


def test_a_product_from_start_to_history(client):
    p = client.post("/api/products", json={"title": "Weather box"}, headers=PAGE).get_json()["product"]
    b = client.post(f"/api/products/{p}/blocks", json={"name": "Sensor board", "kind": "electronic"}, headers=PAGE).get_json()["id"]
    m = client.post(f"/api/products/{p}/modules", json={"name": "Firmware"}, headers=AGENT).get_json()["id"]
    bad = client.post(f"/api/products/{p}/interfaces", json={"name": "Half", "connects": [b]}, headers=PAGE)
    assert bad.status_code == 422 and "at least two" in bad.get_json()["errors"][0]
    assert client.post(f"/api/products/{p}/interfaces", json={"name": "I2C", "connects": [b, m]}).status_code == 200
    got = client.get(f"/api/products/{p}").get_json()
    assert got["product"]["title"] == "Weather box" and len(got["interfaces"]) == 1
    revs = client.get(f"/api/products/{p}/revisions").get_json()
    assert [r["via"] for r in revs[1:3]] == ["mcp", "page"]
    assert client.post(f"/api/products/{p}/revisions/2/tag", json={"name": "Prototype A", "frozen": True}).status_code == 200
    assert b"Sensor board" in client.get(f"/api/products/{p}/revisions/Prototype A.ttl").data
    assert client.delete(f"/api/products/{p}/tags/Prototype A").status_code == 400
    assert client.post(f"/api/products/{p}/revisions/2/restore").get_json()["restored"] == 2
    assert client.get(f"/api/products/{p}/diff?from=nope").status_code == 404
    assert client.get("/api/products/p-nothere1").status_code == 404
    assert b"a m5:Product" in client.get(f"/api/products/{p}/export.ttl").data


def test_only_a_person_on_the_page_decides_a_proposal(client):
    p = client.post("/api/products", json={"title": "Bench supply"}).get_json()["product"]
    pid = client.post(f"/api/products/{p}/proposals", json={"title": "Add a fuse"}, headers=AGENT).get_json()["id"]
    assert client.get(f"/api/products/{p}").get_json()["proposals"][0]["by"] == "maker-5-edge-mcp"
    path = f"/api/products/{p}/proposals/{pid}/decide"
    assert client.post(path, json={"decision": "approved"}, headers=AGENT).status_code == 403
    assert client.post(path, json={"decision": "approved"}).status_code == 403        # Werkzeug: a chat replay
    assert not any(re.fullmatch(rx, path) for _, rx in settings.CHAT_ALLOWED)
    assert client.post(path, json={"decision": "approved", "note": "ok"}, headers=PAGE).status_code == 200
    assert client.get(f"/api/products/{p}").get_json()["proposals"][0]["state"] == "approved"


def test_the_chat_may_propose_the_model_changes():
    p = "p-abcdefgh"
    for method, path in (("POST", "/api/products"), ("POST", f"/api/products/{p}/blocks"),
                         ("POST", f"/api/products/{p}/interfaces/i-abcdefgh/connects"),
                         ("POST", f"/api/products/{p}/items/b-abcdefgh/rename"),
                         ("DELETE", f"/api/products/{p}/items/m-abcdefgh"),
                         ("POST", f"/api/products/{p}/revisions/3/restore")):
        assert any(m == method and re.fullmatch(rx, path) for m, rx in settings.CHAT_ALLOWED), path


def test_files_and_the_selection(client):
    p = client.post("/api/products", json={"title": "Weather box"}).get_json()["product"]
    client.post("/api/selection", json={"product": p})
    up = client.post("/api/inbox", data={"file": (__import__("io").BytesIO(b"ref;qty\nR1;1\n"), "bom.csv")},
                     content_type="multipart/form-data").get_json()
    assert up["kind"] == "csv" and up["product"] == p
    assert client.get("/api/selection").get_json() == {"product": p, "file": up["id"]}
    assert settings.CHAT_SELECTION() == f"{p}//{up['id']}"
    assert client.get(f"/api/inbox/{up['id']}").get_json()["text"].startswith("ref;qty")
    assert client.delete(f"/api/inbox/{up['id']}").status_code == 200
    assert client.get("/api/inbox").get_json() == []
