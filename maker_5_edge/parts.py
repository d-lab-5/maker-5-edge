# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""parts.py — the pins a block gets when it is placed on the hardware canvas
(ADR-0014 in maker-5-shared), from parts/library.json: data, not code."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

LIBRARY = Path(__file__).with_name("parts") / "library.json"
GENERIC = [{"n": 1, "name": "1", "role": "signal"}, {"n": 2, "name": "2", "role": "signal"}]


@lru_cache(maxsize=1)
def library() -> List[Dict[str, Any]]:
    return json.loads(LIBRARY.read_text(encoding="utf-8"))["parts"]


def _key(name: str) -> str:
    """A pin's name to compare: "GPIO 17" and "GPIO17 SDA" → "gpio17"."""
    name = (name or "").lower().split("/", 1)[0].strip()
    m = re.match(r"^([a-z]+)\s*(\d+)\b", name)
    return (m.group(1) + m.group(2)) if m else (name.split() or [""])[0]


def physical(pins: List[Dict[str, Any]], known: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A Fritzing part's pins numbered as the board is: Fritzing keeps no pin
    numbers, and a board's connectors come in any order. When the library here
    has the board and every pin name finds its pin there (GND, 5V and the like
    in turn), take its numbers and roles; else keep them as they are."""
    free: Dict[str, List[Dict[str, Any]]] = {}
    for k in known:
        free.setdefault(_key(k["name"]), []).append(k)
    out = []
    for p in pins:
        q = free.get(_key(p["name"]))
        if not q:
            return pins
        k = q.pop(0)
        out.append({**p, "n": k["n"], "role": k.get("role") or p.get("role")})
    return sorted(out, key=lambda p: p["n"])


PORT = re.compile(r"\b(usb|hdmi|ethernet|audio|video|jack|rj45|sd card|csi|dsi|camera|display|power in|5v in|dc in)\b", re.I)


def with_ports(pins: List[Dict[str, Any]], known: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A library part's pins and the board's ports. A Fritzing part models only
    the header; the USB, video, audio, Ethernet and power sockets the library
    here knows come after it, so cables can be wired to them."""
    used = {p["n"] for p in pins if p.get("n")}
    names = {_key(p["name"]) for p in pins}
    nxt = max(used or {0}) + 1
    out = [dict(p) for p in pins]
    for k in known:
        if not PORT.search(k["name"]) or _key(k["name"]) in names and not PORT.search(k["name"]):
            continue
        if any(o["name"] == k["name"] for o in out):
            continue
        n = k["n"] if k["n"] not in used else nxt
        used.add(n)
        nxt = max(used) + 1
        out.append({"side": "bottom", **k, "n": n})              # a board's ports below it
    return sorted(out, key=lambda p: p["n"])


def pins_for(name: str) -> Dict[str, Any]:
    """The first part of the library whose words are in the block's name, or two generic pins."""
    low = f" {(name or '').lower()} "
    for part in library():
        if any(w in low for w in part["match"]):
            return {"title": part["title"], "pins": [dict(x) for x in part["pins"]], "fritzing": part.get("fritzing", "")}
    return {"title": "", "pins": [dict(x) for x in GENERIC]}
