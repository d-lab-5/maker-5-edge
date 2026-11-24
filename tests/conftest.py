# SPDX-License-Identifier: GPL-3.0-or-later
"""Every test starts with one merged folder and no cloud, unless it asks for
the environments (settings.SYNC_SCOPE, ADR-0013 in maker-5-shared)."""

from __future__ import annotations

import pytest

from maker_5_edge.edge import cloud, settings


@pytest.fixture(autouse=True)
def _merged(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SYNC_SCOPE", "merged")
    monkeypatch.setenv("MAKER5_EDGE_EDGE_STATE", str(tmp_path / "cloud-state.json"))
    monkeypatch.setattr(cloud, "PROFILE", None)
