# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
migrate.py — a workspace's model into a new, empty workspace: from stage to
prod on this edge, or from the workspace's GitHub repository (ADR-0013 and
ADR-0017 in maker-5-shared, amended).

Stage and prod never share a file (ADR-0013). This is the one way across, and
it is a person's: started on the page, shown first as a dry run, one way,
once, into a workspace that holds nothing yet.

What moves is what a repository publishes (git_repo.public_model): the
product's description, its blocks, software modules, interfaces, pins and
wires, and the blocks' pictures (Fritzing and Wokwi references, drawings).
What stays is the cloud's: stock links and quantities (the other cloud's
stock), proposals and decisions, who did what, and the revisions. Ids are
kept, so a block is the same block in both; the destination keeps its own
product node and title.

    sources(p)               where workspace p can be filled from: the other
                             connections' workspaces here, and its repository
    plan(products, p, src)   what a copy would bring, without writing
    copy(products, p, src)   bring it, then sync p with its cloud

A source is {"profile": "stage", "product": "<workspace>"} or {"repo": true}.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rdflib import RDF, Graph

from . import git_repo as gr
from . import products as pr
from .edge import cloud, settings
from .edge import sync as edge_sync

M5 = pr.M5
COUNTED = (("blocks", M5.Block), ("modules", M5.SoftwareModule), ("interfaces", M5.Interface),
           ("pins", M5.Pin), ("wires", M5.Wire))


class MigrateError(ValueError):
    """The copy can't be made as asked: say why."""


def _counts(g: Graph) -> Dict[str, int]:
    return {k: len(set(g.subjects(RDF.type, cls))) for k, cls in COUNTED}


def _filled(g: Graph) -> bool:
    return any(_counts(g)[k] for k in ("blocks", "modules", "interfaces", "wires"))


def _other_products(profile: str) -> pr.Products:
    if not cloud.per_connection():
        raise MigrateError("this edge keeps one folder for every connection: there is nothing to copy across")
    try:
        name = cloud.check_profile(profile)
    except cloud.CloudError as e:
        raise MigrateError(str(e)) from e
    return pr.Products(pr.ProductKB(profile=name))


def sources(products: pr.Products, p: str) -> Dict[str, Any]:
    """Where p can be filled from, and whether it is empty enough to be."""
    here = cloud.active_profile() if cloud.per_connection() else ""
    out: List[Dict[str, Any]] = []
    if cloud.per_connection():
        for name in sorted(set(cloud.profiles()) | set(getattr(settings, "ENVIRONMENTS", {}))):
            if name == here:
                continue
            try:
                other = _other_products(name)
            except MigrateError:
                continue
            if not other.kb.dir.exists():
                continue
            for x in other.products():
                if x["blocks"] or x["modules"]:
                    out.append({"profile": name, "product": x["product"], "title": x["title"],
                                "blocks": x["blocks"], "modules": x["modules"]})
    repo = _repo_model(products, p)
    return {"product": p, "profile": here or None, "empty": not _filled(products._exists(p)),
            "connections": out, "repo": {"blocks": _counts(repo[0])["blocks"], "path": "hardware/model.ttl"} if repo else None}


def _repo_model(products: pr.Products, p: str) -> Optional[Tuple[Graph, Path]]:
    d = gr.repo_dir(products, p)
    f = d / "hardware" / "model.ttl"
    if not (d / ".git").exists() or not f.is_file():
        return None
    g = Graph()
    try:
        g.parse(data=f.read_text(encoding="utf-8"), format="turtle")
    except Exception as e:  # noqa: BLE001 - a broken file in a repository: say so, write nothing
        raise MigrateError(f"hardware/model.ttl in the repository is not Turtle: {e}") from e
    return g, f


def _source(products: pr.Products, p: str, src: Dict[str, Any]) -> Tuple[Graph, Dict[str, Any]]:
    """The source's open model, and what it is, for the report."""
    if src.get("repo"):
        got = _repo_model(products, p)
        if not got:
            raise MigrateError("this workspace has no repository with hardware/model.ttl: link one first")
        return gr.public_model(got[0]), {"repo": True, "path": "hardware/model.ttl"}
    profile, name = str(src.get("profile") or ""), str(src.get("product") or "")
    if cloud.per_connection() and profile == cloud.active_profile():
        raise MigrateError("the source is in this same connection: a copy goes from one connection to another")
    other = _other_products(profile)
    g = other._exists(name)
    return gr.public_model(g), {"profile": profile, "product": name, "title": pr._name(g, other._product_node(g))}


def _rewrite(src: Graph, dst: Graph) -> Graph:
    """src's statements for dst: its product node becomes dst's, whose name and
    status stay. Nothing else is renamed."""
    old = next(iter(src.subjects(RDF.type, M5.Product)), None)
    new = next(iter(dst.subjects(RDF.type, M5.Product)), None)
    if new is None:
        raise MigrateError("the workspace here has no product yet: open it once, so the cloud brings it")
    keep_own = {RDF.type, pr.SCHEMA.name, pr.SCHEMA.creativeWorkStatus}
    out = Graph()
    for s, pp, o in src:
        if s == old and pp in keep_own:
            continue
        out.add((new if s == old else s, pp, new if (old is not None and o == old) else o))
    return out


def plan(products: pr.Products, p: str, src: Dict[str, Any]) -> Dict[str, Any]:
    """What a copy would bring into p, and what it leaves behind; writes nothing."""
    dst = products._exists(p)
    full_src = _full(products, p, src)
    g, what = _source(products, p, src)
    brought = _rewrite(g, dst)
    left = len(full_src) - len(g) if full_src is not None else None
    report = {"product": p, "from": what, "brings": _counts(brought), "statements": len(brought),
              "left_behind": left, "empty": not _filled(dst), "dry_run": True}
    if _filled(dst):
        report["refused"] = "this workspace holds a model already: a copy goes only into an empty one"
    return report


def _full(products: pr.Products, p: str, src: Dict[str, Any]) -> Optional[Graph]:
    if src.get("repo"):
        got = _repo_model(products, p)
        return got[0] if got else None
    try:
        return _other_products(str(src.get("profile") or ""))._exists(str(src.get("product") or ""))
    except (MigrateError, pr.NotFound, ValueError):
        return None


def copy(products: pr.Products, p: str, src: Dict[str, Any], sync: bool = True) -> Dict[str, Any]:
    """Bring src's open model into the empty workspace p (validated by the
    shapes, saved as a revision), then sync p with its cloud."""
    report = plan(products, p, src)
    if report.get("refused"):
        raise MigrateError(report["refused"])
    g, _ = _source(products, p, src)

    def apply(dst: Graph) -> None:
        if _filled(dst):                                    # someone filled it meanwhile
            raise MigrateError("this workspace holds a model already: a copy goes only into an empty one")
        for t in _rewrite(g, dst):
            dst.add(t)
    products._change(p, apply)
    report["dry_run"] = False
    if sync and cloud.linked_profiles():
        try:
            report["sync"] = edge_sync.sync(products.kb, p).get("status")
        except cloud.CloudError as e:                       # it is saved here; the next sync takes it
            report["sync"] = f"not yet: {e}"
    return report

