# SPDX-License-Identifier: GPL-3.0-or-later
"""prod and stage, each its own folder; workspaces come from the cloud
(ADR-0013 in maker-5-shared). The cloud is a fake; every name is invented."""

from __future__ import annotations

import pytest

from maker_5_edge import app as web
from maker_5_edge import products as pr
from maker_5_edge.edge import cloud, settings
from maker_5_edge.edge import knowledge as kn

SPACES = [{"id": "s-aaaaaaaaaa", "name": "Weather box", "kind": "private"},
          {"id": "s-bbbbbbbbbb", "name": "Shared", "kind": "shared"}]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SYNC_SCOPE", "per-connection")
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "mymaker5docs"))
    monkeypatch.setattr(cloud, "linked_profiles", lambda: ["prod"])
    monkeypatch.setattr(cloud, "tenant", lambda name=None, refresh=False: {"tenant": {"id": "t-x", "name": "Example"}, "spaces": list(SPACES)})
    monkeypatch.setattr(web, "_products", None)
    return tmp_path / "mymaker5docs"


def test_the_clouds_workspaces_get_their_folders_in_their_environment(env):
    got = web.app.test_client().get("/api/products").get_json()
    assert sorted(p["title"] for p in got) == ["Shared", "Weather box"]
    assert (env / "prod" / "weather-box" / pr.MODEL).is_file()
    cloud.use_profile("stage")
    web._switched()
    assert kn.scope_dir() == env / "stage"
    assert not (env / "stage" / "weather-box").exists(), "nothing passes from prod to stage"


def test_a_workspace_is_made_in_the_cloud_not_here(env):
    r = web.app.test_client().post("/api/products", json={"title": "Garden"})
    assert r.status_code == 409 and r.get_json()["site"] == "https://maker5.cloud"


def test_an_old_mydocs_becomes_prods(tmp_path):
    old, new = tmp_path / "mydocs", tmp_path / "mymaker5docs"
    (old / "p-abcdefgh").mkdir(parents=True)
    (old / "p-abcdefgh" / pr.MODEL).write_text("")
    web._move_old_folder(old, new)
    assert (new / "prod" / "p-abcdefgh" / pr.MODEL).is_file() and not old.exists()
    empty = tmp_path / "x" / "mydocs"
    empty.mkdir(parents=True)
    web._move_old_folder(empty, tmp_path / "x" / "mymaker5docs")
    assert not empty.exists() and not (tmp_path / "x" / "mymaker5docs").exists()
