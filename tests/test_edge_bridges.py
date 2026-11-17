# SPDX-License-Identifier: GPL-3.0-or-later
"""The bridge of this edge's kind (human) imports, and says when its
backbone is not there instead of failing."""

from __future__ import annotations

import importlib


def test_the_bridge_imports_without_its_backbone():
    importlib.import_module("maker_5_edge.edge.bridges")      # a human edge has none
