# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
materials.py — the workspace's stock, seen from this edge (ADR-0010 in
maker-5-shared).

The stock lives in the cloud (ADR-0008): articles with what is on hand,
reserved and free, units with their codes. This edge reads it through the
edge API and takes parts for a product, as the workspace's edge; it never
edits the catalogue, receives stock or prints codes (a person does that on
the site).

A product here is matched to its space in the cloud by NAME, as the A-Box
sync does (edge/cloud.py space_slug): ids differ between clouds.

    stock(q)                 the catalogue, filtered
    bom(products, p)         what the model needs (m5:usesArticle × quantity)
                             against what the product took and what is free
    take(products, p, step, article, qty | unit)
                             reserve, release or return parts for the product
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .edge import cloud

STEPS = ("reserve", "release", "return")


class NoSpace(LookupError):
    """The product has no space of that name in the linked workspace."""


def stock(q: str = "", category: str = "", profile: Optional[str] = None) -> List[Dict[str, Any]]:
    return cloud.call("materials/list", {"q": q, "category": category}, profile).get("articles", [])


def article(article_id: str, profile: Optional[str] = None) -> Dict[str, Any]:
    return cloud.call("materials/get", {"id": article_id}, profile)


def unit(unit_id: str, profile: Optional[str] = None) -> Dict[str, Any]:
    return cloud.call("materials/unit", {"id": unit_id}, profile)


def resolve(code: str, profile: Optional[str] = None) -> Dict[str, Any]:
    """What a scanned or typed code points at: one of our labels, an EAN, a maker's QR."""
    return cloud.call("materials/resolve", {"code": code}, profile)


def space_of(title: str, profile: Optional[str] = None) -> Dict[str, Any]:
    space = cloud.space_by_slug(cloud.space_slug(title), profile)
    if space is None:
        raise NoSpace(f"the linked workspace has no product named “{title}”: create it there, "
                      "or give this product the same name")
    return space


def bom(products: Any, p: str, profile: Optional[str] = None) -> Dict[str, Any]:
    """The product's parts list: each article its blocks and modules are built
    from, how many the model needs, what the product took, and what is free."""
    m = products.model(p)
    need: Dict[str, Dict[str, Any]] = {}
    for item in m["blocks"] + m["modules"]:
        if item.get("article"):
            line = need.setdefault(item["article"], {"article": item["article"], "need": 0, "for": []})
            line["need"] += item["quantity"]
            line["for"].append({"id": item["id"], "name": item["name"], "quantity": item["quantity"]})
    out: Dict[str, Any] = {"product": p, "lines": [], "space": None, "linked": True, "error": ""}
    if not need:
        return out
    try:
        space = space_of(m["product"]["title"], profile)
        out["space"] = {"id": space["id"], "name": space.get("name")}
        catalogue = {a["id"]: a for a in stock(profile=profile)}
        took = {x["articleId"]: x for x in cloud.call("materials/product", {"spaceId": space["id"]}, profile).get("lines", [])}
    except (cloud.CloudError, NoSpace) as exc:
        catalogue, took = {}, {}
        out["linked"] = not isinstance(exc, cloud.NotLinked)
        out["error"] = ("This edge is not linked to a cloud yet: link it under Connections to see the stock."
                        if isinstance(exc, cloud.NotLinked) else str(exc))
    for aid, line in sorted(need.items(), key=lambda kv: kv[0]):
        a = catalogue.get(aid)
        t = took.get(aid, {})
        have = int(t.get("reserved", 0)) + int(t.get("consumed", 0))
        out["lines"].append({
            **line,
            "name": a["name"] if a else "", "tracking": a["tracking"] if a else "", "unit": a["unit"] if a else "",
            "free": int(a["free"]) if a else None, "reserved": int(t.get("reserved", 0)), "used": int(t.get("consumed", 0)),
            "missing": max(0, line["need"] - have), "known": bool(a),
            "units": [{"id": u["id"], "serial": u.get("serial"), "state": u["state"]} for u in t.get("units", [])],
        })
    return out


def take(products: Any, p: str, step: str, article_id: str, qty: Optional[int] = None,
         unit_id: Optional[str] = None, note: str = "", profile: Optional[str] = None) -> Dict[str, Any]:
    """Reserve, release or return parts for a product (the cloud refuses what
    is not free, or not taken)."""
    if step not in STEPS:
        raise ValueError(f"a step is one of {', '.join(STEPS)}")
    space = space_of(products.model(p)["product"]["title"], profile)
    body: Dict[str, Any] = {"spaceId": space["id"], "articleId": article_id, "note": note}
    if unit_id:
        body["unitId"] = unit_id
    else:
        body["qty"] = int(qty or 1)
    return cloud.call(f"materials/{step}", body, profile)
