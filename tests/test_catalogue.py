# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent's view of the stock (ADR-0018, ADR-0019 in maker-5-shared), with a fake cloud."""

from __future__ import annotations

from maker_5_edge import app as web
from maker_5_edge import materials as mt

CATS = [{"code": "controllers", "top": None, "articles": 2, "free": 1},
        {"code": "controllers/sbc", "top": "controllers", "articles": 2, "free": 1},
        {"code": "sensors", "top": None, "articles": 0, "free": 0}]
ARTICLES = [{"id": "a-2222222222", "name": "Example board", "category": "controllers/sbc", "free": 1, "unit": "pcs"},
            {"id": "a-3333333333", "name": "Spare board", "category": "controllers/sbc", "free": 0},
            {"id": "a-4444444444", "name": "New board", "category": "controllers/sbc", "free": 3, "proposed": {"by": "edge:x"}}]
IDLE = [{"workspace": {"id": "s-aaaaaaaaaa", "name": "Weather box", "edgeSeenAt": None},
         "article": {"id": "a-3333333333", "name": "Spare board", "category": "controllers/sbc"}, "reserved": 1}]


def fake(monkeypatch):
    calls = []

    def call(path, body, name=None):
        calls.append((path, body))
        return {"materials/categories": {"categories": CATS}, "materials/list": {"articles": ARTICLES},
                "materials/idle": {"parts": IDLE}}[path]
    monkeypatch.setattr(mt.cloud, "call", call)
    return calls


def test_the_catalogue_leaves_empty_categories_out(monkeypatch):
    fake(monkeypatch)
    assert [c["code"] for c in mt.catalogue()] == ["controllers", "controllers/sbc"]


def test_free_parts_are_free_stock_and_what_passive_workspaces_hold(monkeypatch):
    calls = fake(monkeypatch)
    got = mt.free_parts("controllers")
    assert [a["name"] for a in got["free"]] == ["Example board"], "no empty, no proposed"
    assert got["held_by_passive_workspaces"][0]["workspace"]["name"] == "Weather box"
    assert ("materials/idle", {"category": "controllers"}) in calls


def test_the_routes(monkeypatch):
    fake(monkeypatch)
    c = web.app.test_client()
    assert c.get("/api/catalogue").status_code == 200
    assert c.get("/api/catalogue/free?category=controllers/sbc").get_json()["free"][0]["id"] == "a-2222222222"
