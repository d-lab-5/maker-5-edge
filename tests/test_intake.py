# SPDX-License-Identifier: GPL-3.0-or-later
"""The intake (ADR-0022 in maker-5-shared): what was scanned at the shelf,
listed and shown with its photos, described by the agent, checked in only by
a person on the page."""

from __future__ import annotations

import pytest

from maker_5_edge import materials as mt
from maker_5_edge.app import app

ITEM = "i-2222222222"
PHOTO = "0123456789ab"
BROWSER = {"User-Agent": "Mozilla/5.0"}
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKER5_EDGE_EDGE_STATE", str(tmp_path / "cloud.json"))
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "data"))
    calls = []
    item = {"id": ITEM, "code": {"kind": "m5", "value": "K7Q2M9"}, "family": "dhc", "placeName": "Shelf A",
            "photos": [{"id": PHOTO, "type": "image/jpeg", "size": len(JPEG)}], "status": "new"}

    def call(path, body, profile=None):
        calls.append((path, body))
        if path == "materials/intake/list":
            return {"items": [item]}
        if path == "materials/intake/get":
            return {"item": item, "photos": [{"id": PHOTO, "url": "https://bucket.s3.eu-west-1.amazonaws.com/intake/x?sig=1"}], "article": None}
        return {"ok": True, "kind": "unit"}
    monkeypatch.setattr(mt.cloud, "call", call)
    fetched = []
    monkeypatch.setattr(mt, "_fetch", lambda url: fetched.append(url) or JPEG)
    return {"calls": calls, "fetched": fetched}


def test_items_are_listed_and_their_photos_fetched_once(cloud):
    c = app.test_client()
    assert c.get("/api/intake").get_json()[0]["family"] == "dhc"
    got = c.get(f"/api/intake/{ITEM}").get_json()
    assert got["photos"] == [{"id": PHOTO, "type": "image/jpeg", "size": len(JPEG)}], "a local photo, no link"
    r = c.get(f"/api/intake/{ITEM}/photos/{PHOTO}.jpg")
    assert r.status_code == 200 and r.data == JPEG and r.mimetype == "image/jpeg"
    c.get(f"/api/intake/{ITEM}")
    assert len(cloud["fetched"]) == 1, "kept here after the first time"
    assert c.get(f"/api/intake/{ITEM}/photos/..%2Fx.jpg").status_code == 404


def test_a_photo_comes_from_the_organisations_storage_only():
    with pytest.raises(ValueError):
        mt._fetch("http://bucket.s3.amazonaws.com/x")
    with pytest.raises(ValueError):
        mt._fetch("https://evil.example.org/x.jpg")
    with pytest.raises(ValueError):
        mt.intake_item("../../etc")


def test_the_agent_describes_but_only_a_person_checks_in(cloud):
    c = app.test_client()
    s = {"what": "device", "article": {"name": "Mini PC", "category": "controllers/sbc"}}
    assert c.post(f"/api/intake/{ITEM}/describe", json={"suggestion": s}, headers={"X-Agent": "maker-5-edge-mcp"}).status_code == 200
    assert cloud["calls"][-1] == ("materials/intake/describe", {"id": ITEM, "suggestion": s})
    for path in ("checkin", "drop"):
        assert c.post(f"/api/intake/{ITEM}/{path}", json={}, headers={"X-Agent": "maker-5-edge-mcp"}).status_code == 403
    r = c.post(f"/api/intake/{ITEM}/checkin", json={"suggestion": s}, headers=BROWSER)
    assert r.status_code == 200
    assert cloud["calls"][-1] == ("materials/intake/checkin", {"id": ITEM, "suggestion": s})


def test_the_chat_cannot_propose_a_check_in():
    from maker_5_edge.edge import chat
    assert not chat.allowed("POST", f"/api/intake/{ITEM}/checkin")
    assert not chat.allowed("POST", f"/api/intake/{ITEM}/drop")


def test_the_agent_sees_the_photos(cloud, monkeypatch):
    from maker_5_edge import mcp_server
    from mcp.server.mcpserver.utilities.types import Image
    c = app.test_client()
    monkeypatch.setattr(mcp_server, "_get", lambda path: c.get(path).get_json())
    out = mcp_server.intake_item(ITEM)
    assert out[0]["item"]["id"] == ITEM
    assert isinstance(out[1], Image) and out[1].path.read_bytes() == JPEG
    assert "intake_describe" in (mcp_server.intake_skill())
