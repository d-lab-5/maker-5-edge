# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
materials.py — the organisation's stock, seen from this edge (ADR-0010 in
maker-5-shared).

The stock lives in the cloud (ADR-0008): articles with what is on hand,
reserved and free, units with their codes. This edge reads it through the
edge API and takes parts for a product, as the organisation's edge; it never
edits the catalogue (it only proposes articles), receives stock or prints codes (a person does that on
the site).

A product here is its workspace in the cloud: found by the id the sync keeps
for it (edge/sync.py), else by NAME (edge/cloud.py space_slug).

    stock(q)                 the catalogue, filtered
    bom(products, p)         what the model needs (m5:usesArticle × quantity)
                             against what the product took and what is free
    take(products, p, step, article, qty | unit)
                             reserve, release or return parts for the product
    propose(articles)        articles a BOM import needs, proposed for an admin
                             to accept (ADR-0014); the only catalogue write
    catalogue()              the categories (ADR-0019, two levels) with how
                             many articles each has and how many are free
    free_parts(category)     what a new design can use: articles with free
                             stock, and parts that passive workspaces hold
                             (ADR-0018), which a person may ask back
    boxes(q, workspace)      the organisation's boxes (ADR-0011), read only
    box(code_or_id)          what a box holds, where it is, its links and files

Boxes are checked in and out on a phone, at the shelf; this edge only reads
them, so the bench can ask where a part is and where its firmware is.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .edge import cloud
from .edge import sync as edge_sync

STEPS = ("reserve", "release", "return")


class NoSpace(LookupError):
    """The linked organisation has no workspace of the product's name."""


def stock(q: str = "", category: str = "", profile: Optional[str] = None) -> List[Dict[str, Any]]:
    return cloud.call("materials/list", {"q": q, "category": category}, profile).get("articles", [])


def catalogue(profile: Optional[str] = None) -> List[Dict[str, Any]]:
    """The categories, top then sub, each with articles and free counts; empty ones left out."""
    cats = cloud.call("materials/categories", {}, profile).get("categories", [])
    return [c for c in cats if c.get("articles")]


def free_parts(category: str = "", profile: Optional[str] = None) -> Dict[str, Any]:
    """What a design can take before anything is bought: free stock in the
    category, and what passive workspaces hold (reserved, not used lately)."""
    free = [{k: a.get(k) for k in ("id", "name", "category", "free", "unit", "location") if a.get(k) is not None}
            for a in stock("", category, profile) if (a.get("free") or 0) > 0 and not a.get("proposed")]
    held = cloud.call("materials/idle", {"category": category}, profile).get("parts", [])
    return {"free": free, "held_by_passive_workspaces": held}


def article(article_id: str, profile: Optional[str] = None) -> Dict[str, Any]:
    return cloud.call("materials/get", {"id": article_id}, profile)


def unit(unit_id: str, profile: Optional[str] = None) -> Dict[str, Any]:
    return cloud.call("materials/unit", {"id": unit_id}, profile)


def resolve(code: str, profile: Optional[str] = None) -> Dict[str, Any]:
    """What a scanned or typed code points at: one of our labels, an EAN, a maker's QR."""
    return cloud.call("materials/resolve", {"code": code}, profile)


def propose(articles: List[Dict[str, Any]], profile: Optional[str] = None) -> List[Dict[str, Any]]:
    """Articles a BOM import needs and the stock lacks (ADR-0014): made in the
    cloud with no stock, marked proposed until an admin accepts them. A name
    the stock has already gives the existing article."""
    return cloud.call("materials/propose", {"articles": articles}, profile).get("articles", [])


def boxes(q: str = "", workspace: str = "", profile: Optional[str] = None) -> List[Dict[str, Any]]:
    """The boxes, found by words; with a workspace (a product's title), only the ones marked for it."""
    space_id = space_of(workspace, profile)["id"] if workspace else ""
    return cloud.call("materials/boxes", {"q": q, "spaceId": space_id}, profile).get("boxes", [])


def box(code_or_id: str, profile: Optional[str] = None) -> Dict[str, Any]:
    """One box, by its id (x-…) or any code on its label."""
    ref = (code_or_id or "").strip()
    if not ref:
        raise ValueError("name a box: its id or the code on its label")
    if not ref.startswith("x-"):
        got = resolve(ref, profile)
        if got.get("status") != "box":
            raise ValueError(f"“{ref}” is not a box's code (it is {got.get('status', 'unknown')})")
        ref = got["id"]
    return cloud.call("materials/box", {"id": ref}, profile)


def space_of(title: str, profile: Optional[str] = None) -> Dict[str, Any]:
    space = cloud.space_by_slug(cloud.space_slug(title), profile)
    if space is None:
        raise NoSpace(f"the linked organisation has no workspace named “{title}”: create it there, "
                      "or give this one the same name")
    return space


def product_space(products: Any, p: str, profile: Optional[str] = None) -> Dict[str, Any]:
    """The cloud workspace a product here is: by the id the sync keeps, else by its title."""
    try:
        space, _ = edge_sync.space_of(products.kb, p, profile)
        if space:
            return space
    except (cloud.CloudError, AttributeError):
        pass
    return space_of(products.model(p)["product"]["title"], profile)


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
        space = product_space(products, p, profile)
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
    space = product_space(products, p, profile)
    body: Dict[str, Any] = {"spaceId": space["id"], "articleId": article_id, "note": note}
    if unit_id:
        body["unitId"] = unit_id
    else:
        body["qty"] = int(qty or 1)
    return cloud.call(f"materials/{step}", body, profile)
