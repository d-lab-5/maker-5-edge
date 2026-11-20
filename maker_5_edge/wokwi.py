# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
wokwi.py — breadboard pictures of common boards and parts from the Wokwi
elements (github.com/wokwi/wokwi-elements, MIT; ADR-0021 in maker-5-shared).

The elements are web components. scripts/wokwi-snapshot.mjs renders each one
once into a plain SVG with its pins, into parts/wokwi/, which ships with the
edge: nothing is fetched and no third-party JavaScript runs on the page.

    search(q)      [{name, title, pins}]
    part(name)     {name, title, pins: [{n, name, role, x, y}], license, source, ...}
    image(name)    the SVG, as bytes
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

FOLDER = Path(__file__).with_name("parts") / "wokwi"
NAME = re.compile(r"^[a-z0-9-]{1,60}$")


@lru_cache(maxsize=1)
def _index() -> Dict[str, Any]:
    f = FOLDER / "index.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"parts": [], "license": "MIT"}


def credit() -> Dict[str, str]:
    i = _index()
    return {"license": i.get("license", "MIT"), "source": i.get("source", "https://github.com/wokwi/wokwi-elements"),
            "version": i.get("version", ""), "copyright": i.get("copyright", "")}


def search(q: str, limit: int = 30) -> List[Dict[str, Any]]:
    words = [w for w in re.split(r"\W+", (q or "").lower()) if w]
    out = []
    for p in _index()["parts"]:
        hay = f"{p['title']} {p['name']}".lower()
        hits = sum(1 for w in words if w in hay)
        if not words or hits:
            out.append((-hits, p["title"].lower(), {"name": p["name"], "title": p["title"], "pins": len(p["pins"])}))
    out.sort(key=lambda x: x[:2])
    best = out[0][0] if out else 0
    return [x[2] for x in out if not words or x[0] <= best + 1][:max(1, min(int(limit), 100))]


def part(name: str) -> Dict[str, Any]:
    if not NAME.match(name or ""):
        raise ValueError(f"no element {name!r} in the Wokwi elements")
    p = next((x for x in _index()["parts"] if x["name"] == name), None)
    if p is None:
        raise ValueError(f"no element {name!r} in the Wokwi elements")
    return {**p, "pins": [dict(x) for x in p["pins"]], **credit()}


def image(name: str) -> bytes:
    part(name)
    return (FOLDER / f"{name}.svg").read_bytes()
