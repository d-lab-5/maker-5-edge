# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
fritzing.py — parts from the Fritzing parts library for the hardware canvas
(ADR-0016 in maker-5-shared).

The library (github.com/fritzing/fritzing-parts) is CC BY-SA 3.0, which
GPL-3 code may not carry. So nothing of it is in this repository: the edge
fetches what the person picks, from the library itself, into its own cache
(<data>/fritzing/, shared by every environment), and shows each part's title,
authors and licence wherever it is used. The model keeps only the part's
file name (m5:fritzingPart), and the pins the part gave the block.

    search(q)        parts whose file name has every word (core first)
    part(path)       a part's title, authors, pins; fetched once, then cached
    image(path)      its breadboard picture (SVG), shown as an image only

The list of parts is the repository's file tree, one request, kept a week.
Only files in that list are ever fetched, from raw.githubusercontent.com.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

from .edge import knowledge as kn

REPO = "fritzing/fritzing-parts"
BRANCH = "develop"
TREE = f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
SOURCE = f"https://github.com/{REPO}"
LICENSE = "CC BY-SA 3.0"
FOLDERS = ("core", "contrib")
INDEX_DAYS = 7
MAX_FZP = 1_000_000
MAX_SVG = 3_000_000
PATH = re.compile(r"^(core|contrib)/[^/]{1,200}\.fzp$")


class FritzingError(RuntimeError):
    """The library could not be reached, or a part could not be read."""


def cache() -> Path:
    d = kn.data_dir() / "fritzing"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "maker-5-edge", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:   # noqa: S310 - fixed https hosts
            data = r.read(limit + 1)
    except (urllib.error.URLError, OSError) as e:
        raise FritzingError(f"the Fritzing library could not be reached: {e}") from e
    if len(data) > limit:
        raise FritzingError("that file of the Fritzing library is too large")
    return data


def _safe(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", path)


# ------------------------------------------------------------ the list ----

def index(refresh: bool = False) -> List[str]:
    """Every part file of the library's core and contrib folders."""
    f = cache() / "index.json"
    if f.exists() and not refresh:
        d = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - d.get("at", 0) < INDEX_DAYS * 86400:
            return d["parts"]
    tree = json.loads(_fetch(TREE, 20_000_000))
    parts = sorted(x["path"] for x in tree.get("tree", []) if x.get("type") == "blob" and PATH.match(x.get("path", "")))
    svgs = sorted(x["path"] for x in tree.get("tree", []) if x.get("type") == "blob"
                  and re.match(r"^svg/(core|contrib)/breadboard/[^/]+\.svg$", x.get("path", "")))
    f.write_text(json.dumps({"at": time.time(), "parts": parts, "svgs": svgs}), encoding="utf-8")
    return parts


def _svgs() -> set:
    index()
    return set(json.loads((cache() / "index.json").read_text(encoding="utf-8")).get("svgs", []))


def _label(path: str) -> str:
    """A readable name from a file name: "core/Raspberry_Pi_B(rev2).fzp" → "Raspberry Pi B(rev2)"."""
    name = path.split("/", 1)[1].rsplit(".", 1)[0]
    name = re.sub(r"_[0-9a-f]{32}(_\w+)*$", "", name)          # contrib's hash suffixes
    return re.sub(r"[_]+", " ", name).strip()


def search(q: str, limit: int = 30) -> List[Dict[str, str]]:
    words = [w for w in re.split(r"\W+", (q or "").lower()) if w]
    if not words:
        return []
    hits, near = [], []
    for p in index():
        name = _label(p)
        hay = name.lower()
        tokens = re.split(r"[^a-z0-9+]+", hay)
        whole = sum(1 for w in words if w in tokens)                # "b" as a word, not inside "board"
        hit = {"path": p, "name": name, "folder": p.split("/", 1)[0], "_rank": (-whole, p.split("/", 1)[0] != "core", len(name))}
        if all(w in hay for w in words):
            hits.append(hit)
        elif whole >= 2:
            near.append(hit)                                        # a block's whole name: most words first
    if not hits:
        best = min((h["_rank"][0] for h in near), default=0)
        hits = [h for h in near if h["_rank"][0] <= best + 1]
    hits.sort(key=lambda h: (*h["_rank"], h["name"].lower()))
    for h in hits:
        h.pop("_rank")
    return hits[:max(1, min(int(limit), 100))]


# ------------------------------------------------------------ one part ----

ROLE_WORDS = (("ground", r"^(gnd|ground|vss|v-|0v)\b|\bgnd\b"),
              ("power", r"^(vcc|vdd|vin|v\+|vbat|vbus|[0-9.]+ ?v[0-9]?|3v3|5v|12v|\+[0-9.]+v)\b|\bvcc\b|power"),
              ("data", r"\b(sda|scl|mosi|miso|sck|sclk|ce[01]|cs|txd?|rxd?|usb|d[+-]|uart|i2c|spi)\b"),
              ("audio", r"\b(audio|spk|speaker|mic|out[+-]|line)\b"),
              ("video", r"\b(video|cvbs|hdmi|composite)\b"))


def role(name: str) -> str:
    n = (name or "").lower()
    return next((r for r, rx in ROLE_WORDS if re.search(rx, n)), "signal")


def _pin_name(name: str, description: str) -> str:
    """A connector's name, or its description where the name only counts ("Pin 4" → "Collector")."""
    name, description = (name or "").strip(), (description or "").strip()
    if (not name or re.fullmatch(r"(pin\s*)?\d+", name, re.I)) and description and len(description) <= 30:
        return description
    return name or description


def parse(xml: bytes, path: str) -> Dict[str, Any]:
    """A part's title, authors, pins and breadboard picture, from its .fzp."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise FritzingError(f"{path} is no readable Fritzing part: {e}") from e
    text = lambda tag: (root.findtext(tag) or "").strip()  # noqa: E731
    pins = []
    for i, c in enumerate(root.iter("connector")):
        m = re.search(r"(\d+)$", c.get("id", ""))
        n = int(m.group(1)) + 1 if m else i + 1
        name = _pin_name(c.get("name", ""), c.findtext("description") or "")
        pins.append({"n": n, "name": name[:40] or str(n), "role": role(name)})
    seen: set = set()
    pins = [p for p in sorted(pins, key=lambda p: p["n"]) if not (p["n"] in seen or seen.add(p["n"]))]
    bb = root.find("./views/breadboardView/layers")
    image = bb.get("image", "") if bb is not None else ""
    folder = path.split("/", 1)[0]
    return {"path": path, "title": text("title") or _label(path), "author": text("author"),
            "module": root.get("moduleId", ""), "family": next((p.text or "" for p in root.iter("property")
                                                                if p.get("name") == "family"), ""),
            "pins": pins[:80], "image": f"svg/{folder}/{image}" if image else "",
            "license": LICENSE, "source": f"{SOURCE}/blob/{BRANCH}/{urllib.parse.quote(path)}"}


def part(path: str) -> Dict[str, Any]:
    if not PATH.match(path or "") or path not in set(index()):
        raise ValueError(f"no part {path} in the Fritzing library")
    f = cache() / "parts" / (_safe(path) + ".json")
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    p = parse(_fetch(RAW + urllib.parse.quote(path), MAX_FZP), path)
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps(p), encoding="utf-8")
    return p


def image(path: str) -> Optional[bytes]:
    """The part's breadboard picture, fetched once; None when it has none."""
    p = part(path)
    svg = p.get("image") or ""
    if not svg:
        return None
    if svg not in _svgs():
        return None
    f = cache() / "svg" / _safe(svg)
    if not f.exists():
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(_fetch(RAW + urllib.parse.quote(svg), MAX_SVG))
    return f.read_bytes()
