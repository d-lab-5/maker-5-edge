# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""parts.py — the pins a block gets when it is placed on the hardware canvas
(ADR-0014 in maker-5-shared), from parts/library.json: data, not code."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

LIBRARY = Path(__file__).with_name("parts") / "library.json"
GENERIC = [{"n": 1, "name": "1", "role": "signal"}, {"n": 2, "name": "2", "role": "signal"}]


@lru_cache(maxsize=1)
def library() -> List[Dict[str, Any]]:
    return json.loads(LIBRARY.read_text(encoding="utf-8"))["parts"]


def pins_for(name: str) -> Dict[str, Any]:
    """The first part of the library whose words are in the block's name, or two generic pins."""
    low = f" {(name or '').lower()} "
    for part in library():
        if any(w in low for w in part["match"]):
            return {"title": part["title"], "pins": [dict(x) for x in part["pins"]]}
    return {"title": "", "pins": [dict(x) for x in GENERIC]}
