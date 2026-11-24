# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
drawing.py — a block's picture when no library has one (ADR-0021 in
maker-5-shared):

    generated(name, pins)   drawn from the block's own pins: always right
    clean(svg, pins)        the agent's drawing, checked before it is kept

An agent's drawing is SVG with shapes and text only. Each of the block's pins
is marked once, as data-pin="<n>" on the element at its place; nothing else
is marked. Anything that could fetch, run or point somewhere is refused, and
the refusal says why, so the agent can fix it and propose it again.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

MAX = 40_000
NS = "http://www.w3.org/2000/svg"
ELEMENTS = {"svg", "g", "rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "text", "tspan",
            "title", "desc", "defs", "lineargradient", "radialgradient", "stop"}
ATTRS = {"viewbox", "width", "height", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "d", "points",
         "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "opacity",
         "fill-opacity", "stroke-opacity", "transform", "font-size", "font-family", "font-weight", "text-anchor",
         "dominant-baseline", "id", "class", "offset", "stop-color", "stop-opacity", "gradientunits",
         "gradienttransform", "fx", "fy", "fr", "data-pin", "xmlns", "version", "preserveaspectratio"}
PAINT = re.compile(r"^(none|currentColor|#[0-9a-fA-F]{3,8}|[a-z]{3,20}|url\(#[A-Za-z][\w-]{0,40}\)|rgba?\([\d\s.,%]+\))$")
ROLE_COLOUR = {"power": "#d64545", "ground": "#3a3a3a", "signal": "#2f7fd1", "data": "#2f9d6a",
               "audio": "#b46ad6", "video": "#d6982f", "": "#888888"}


class DrawingError(ValueError):
    """The drawing is refused; the message says why."""


def _x(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generated(name: str, pins: List[Dict[str, Any]]) -> str:
    """A board as a rounded body with its pins along two edges, in order,
    named and coloured by role: drawn from the model, so never wrong."""
    pins = sorted(pins, key=lambda p: p["n"])
    half = (len(pins) + 1) // 2
    left, right = pins[:half], pins[half:]
    rows = max(len(left), len(right), 1)
    w, row, top = 200, 16, 34
    h = top + rows * row + 14
    out = [f'<svg xmlns="{NS}" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
           f'<title>{_x(name)}: drawn from its pins</title>',
           f'<rect x="14" y="4" width="{w - 28}" height="{h - 8}" rx="8" fill="#1f5f3f" stroke="#0f3d27" stroke-width="2"/>',
           f'<text x="{w / 2}" y="22" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="bold" fill="#ffffff">{_x(name[:30])}</text>']
    for side, group in ((0, left), (1, right)):
        for i, p in enumerate(group):
            y = top + i * row + 6
            cx = 14 if side == 0 else w - 14
            colour = ROLE_COLOUR.get(p.get("role") or "", ROLE_COLOUR[""])
            out.append(f'<circle data-pin="{p["n"]}" cx="{cx}" cy="{y}" r="5" fill="{colour}" stroke="#ffffff" stroke-width="1"/>')
            tx, anchor = (cx + 10, "start") if side == 0 else (cx - 10, "end")
            out.append(f'<text x="{tx}" y="{y + 3.5}" text-anchor="{anchor}" font-family="sans-serif" font-size="9" fill="#e8f3ec">'
                       f'{p["n"]} {_x(p["name"][:18])}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def clean(svg: str, pins: List[Dict[str, Any]]) -> str:
    """The agent's SVG if it is safe and shows exactly the block's pins; else DrawingError."""
    svg = (svg or "").strip()
    if not svg:
        raise DrawingError("the drawing is empty")
    if len(svg) > MAX:
        raise DrawingError(f"the drawing is {len(svg)} characters; at most {MAX}: simplify the shapes")
    if re.search(r"<!|<\?(?!xml)", svg):
        raise DrawingError("no DOCTYPE, entities or processing instructions: plain SVG only")
    if re.search(r"javascript:|url\(\s*['\"]?(?!#)|@import|expression\(", svg, re.I):
        raise DrawingError("no external references: url() only to a gradient in the same drawing (url(#id))")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        raise DrawingError(f"the drawing is not well-formed XML: {e}") from e
    if _local(root.tag) != "svg":
        raise DrawingError("the drawing starts with <svg>")
    if not root.get("viewBox"):
        raise DrawingError("give the <svg> a viewBox, so it scales")
    marked: Dict[int, int] = {}
    for el in root.iter():
        tag = _local(el.tag)
        if tag not in ELEMENTS:
            raise DrawingError(f"<{tag}> is not allowed; use only {', '.join(sorted(ELEMENTS))}")
        for k, v in el.attrib.items():
            name = _local(k)
            if name.startswith("on") or name not in ATTRS:
                raise DrawingError(f"the attribute {name} (on <{tag}>) is not allowed")
            if name in ("fill", "stroke", "stop-color") and not PAINT.match(v.strip()):
                raise DrawingError(f"{name}=\"{v[:40]}\" is not a colour")
            if name == "data-pin":
                if not re.fullmatch(r"\d{1,3}", v):
                    raise DrawingError(f"data-pin=\"{v[:20]}\" is a pin number")
                marked[int(v)] = marked.get(int(v), 0) + 1
    want = {int(p["n"]) for p in pins}
    twice = sorted(n for n, c in marked.items() if c > 1)
    missing, extra = sorted(want - set(marked)), sorted(set(marked) - want)
    if twice:
        raise DrawingError(f"pins marked more than once: {twice}")
    if missing:
        raise DrawingError(f"the block's pins {missing} are not in the drawing: mark each with data-pin")
    if extra:
        raise DrawingError(f"data-pin {extra} are not pins of the block")
    if not svg.startswith("<svg"):
        svg = svg[svg.index("<svg"):]
    return svg
