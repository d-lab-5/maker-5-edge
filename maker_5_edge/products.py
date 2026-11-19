# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
products.py — the products on this edge and the model each one holds.

A *product* (a space in the cloud) is one A-Box of the Maker-5 ontology: the
product itself (m5:Product), its hardware blocks, software modules, the
interfaces between them, and the proposals made to change it. Everything is
written through edge.knowledge's change(), so the Maker-5 SHACL shapes
(edge/ontology/shapes) refuse a model that breaks them, and nothing is saved.

Each product has its own folder under its connection's folder (ADR-0003 and
ADR-0013 in maker-5-shared; <env> is prod or stage):

    <data>/<env>/<product>/model.ttl  its A-Box
    <data>/<env>/<product>/revisions/ every saved state (revisions.py, ADR-0004)
    <data>/<env>/<product>/files/<id>/ files given to the chat while it is open (inbox.py)

A product is a workspace of the cloud: it is made there, and adopt() gives
each workspace of the current connection its folder here.

ProductKB is the edge layer's KnowledgeBase with that layout, so the cloud
sync (edge/sync.py) works on it unchanged; migrate_layout() moves the
layer's own layout (<data>/abox/<name>.ttl) across once.

A proposal (m5:Proposal) is a change an agent suggests. It is attributed to
the agent (prov:wasAttributedTo) and starts as m5:Proposed. Only a person
decides it, on the page (ADR-0006): decide() sets m5:Approved or m5:Rejected
and records the decision as a prov:Activity that used the proposal and was
associated with the person. There is no MCP tool for it.

IRIs are https://maker-5.cloud/id/<kind>/<id>. Ids are minted, never made
from a name, so a rename changes nothing else.
"""

from __future__ import annotations

import getpass
import logging
import os
import re
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from rdflib import RDF, Graph, Literal, Namespace, URIRef
from rdflib.namespace import XSD

from . import revisions as rv
from .edge import knowledge as kn

M5 = Namespace("https://maker-5.cloud/ontology#")
ARTICLE_IRI = "https://maker-5.cloud/id/article/"
ARTICLE_ID = re.compile(r"^a-[23456789abcdefghjkmnpqrstuvwxyz]{10}$")
PROV = Namespace("http://www.w3.org/ns/prov#")
SCHEMA = Namespace("https://schema.org/")
ID = "https://maker-5.cloud/id/"

log = logging.getLogger(__name__)

# folders in the data dir that are not products
RESERVED = frozenset({"abox", "inbox", "files", "revisions"})
MODEL = "model.ttl"

BLOCK_KINDS = {"electronic": M5.Electronic, "mechanical": M5.Mechanical}
STATES = {"proposed": M5.Proposed, "approved": M5.Approved, "rejected": M5.Rejected}
STATUSES = ("active", "done", "archived")
# what each kind of item is, and its id prefix
KINDS = {"block": (M5.Block, "b"), "module": (M5.SoftwareModule, "m"),
         "interface": (M5.Interface, "i"), "proposal": (M5.Proposal, "pr")}


class NotFound(LookupError):
    pass


# ------------------------------------------------------------ the layout ----

class ProductKB(kn.KnowledgeBase):
    """The edge layer's KnowledgeBase, one folder per product:
    <data>/<name>/model.ttl. Everything else (validation on change, one
    writer at a time, the sync bases in <data>/.sync/) is the edge layer's."""

    def __init__(self, directory: Optional[Path] = None, profile: Optional[str] = None):
        super().__init__(Path(directory) if directory else kn.scope_dir(profile))

    def _path(self, name: str) -> Path:
        if not kn.GRAPH_NAME.fullmatch(name or "") or name in RESERVED:
            raise ValueError("a product id is lowercase letters, digits and -, "
                             f"and not one of {', '.join(sorted(RESERVED))}")
        return self.dir / name / MODEL

    def graphs(self) -> List[str]:
        names = sorted(p.parent.name for p in self.dir.glob(f"*/{MODEL}")
                       if p.parent.name not in RESERVED and kn.GRAPH_NAME.fullmatch(p.parent.name))
        return sorted(names or [kn.SHARED], key=lambda n: (n != kn.SHARED, n))

    def folder(self, name: str) -> Path:
        return self._path(name).parent

    def _save(self, name: str, g: Graph) -> None:
        folder = self.folder(name)
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder.mkdir(exist_ok=True, mode=0o700)
        os.chmod(folder, 0o700)
        before = self.load(name) if self._path(name).exists() else None
        g.bind("m5", M5)
        g.bind("prov", PROV)
        g.bind("schema", SCHEMA)
        super()._save(name, g)
        rv.History(folder).record(before, g)        # every saved state is kept

    def history(self, name: str) -> rv.History:
        return rv.History(self.folder(name))


def migrate_layout(root: Optional[Path] = None) -> List[str]:
    """Move <root>/abox/<name>.ttl to <root>/<name>/model.ttl and the sync
    bases <root>/abox/.sync/ to <root>/.sync/. Idempotent; never overwrites."""
    root = Path(root) if root else kn.scope_dir()
    old = root / "abox"
    done: List[str] = []
    if not old.is_dir():
        return done
    for p in sorted(old.glob("*.ttl")):
        target = root / p.stem / MODEL
        if p.stem in RESERVED or not kn.GRAPH_NAME.fullmatch(p.stem) or target.exists():
            log.warning("product layout: left %s where it is (%s exists or is not a product id)", p, target)
            continue
        target.parent.mkdir(exist_ok=True, mode=0o700)
        os.replace(p, target)
        done.append(p.stem)
    sync_old = old / ".sync"
    if sync_old.is_dir():
        for f in sorted(x for x in sync_old.rglob("*") if x.is_file()):
            dest = root / ".sync" / f.relative_to(sync_old)
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.replace(f, dest)
        for d in sorted((x for x in sync_old.rglob("*") if x.is_dir()), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        try:
            sync_old.rmdir()
        except OSError:
            pass
    try:
        old.rmdir()
    except OSError:
        log.warning("product layout: %s is not empty, kept", old)
    if done:
        log.info("product layout: moved %s into their own folders", ", ".join(done))
    return done


# ------------------------------------------------------------ helpers ----

def _mint(prefix: str) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return f"{prefix}-" + "".join(secrets.choice(alphabet) for _ in range(8))


def _iri(kind: str, ident: str) -> URIRef:
    return URIRef(f"{ID}{kind}/{ident}")


def _local(iri: Any) -> str:
    return re.split(r"[#/]", str(iri))[-1]


def _now() -> Literal:
    return Literal(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), datatype=XSD.dateTime)


def _who() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 — no user name is no reason to fail
        return "someone"


def _name(g: Graph, n: Any) -> str:
    v = g.value(n, SCHEMA.name)
    return str(v) if v is not None else _local(n)


def _key(name: Optional[str], allowed: Dict[str, Any], what: str) -> Any:
    k = (name or "").strip().lower()
    if k not in allowed:
        raise ValueError(f"{what} is one of {', '.join(allowed)}")
    return allowed[k]


# ------------------------------------------------------------ products ----

class Products:
    """The products of this edge and the model in each."""

    def __init__(self, kb: Optional[kn.KnowledgeBase] = None):
        self.kb = kb or ProductKB()

    def _product_node(self, g: Graph) -> Optional[URIRef]:
        return next(iter(g.subjects(RDF.type, M5.Product)), None)

    def _exists(self, p: str) -> Graph:
        if p not in self.kb.graphs() or not self.kb._path(p).exists():
            raise NotFound(f"no product {p}")
        return self.kb.load(p)

    def _change(self, p: str, apply: Callable[[Graph], Any]) -> Any:
        self._exists(p)
        return self.kb.change(p, apply)

    def _find(self, g: Graph, ident: str, *kinds: str) -> URIRef:
        for k in kinds or tuple(KINDS):
            cls, _ = KINDS[k]
            n = _iri(k, ident)
            if (n, RDF.type, cls) in g:
                return n
        raise NotFound(f"no {' or '.join(kinds or ('item',))} {ident}")

    def products(self) -> List[Dict]:
        """Every product here: its title, status, and how big its model is. A
        space synced from the cloud without an m5:Product is listed by its id."""
        out = []
        for name in self.kb.graphs():
            if not self.kb._path(name).exists():
                continue
            g = self.kb.load(name)
            node = self._product_node(g)
            proposed = [x for x in g.subjects(RDF.type, M5.Proposal)
                        if (x, M5.proposalState, M5.Proposed) in g]
            out.append({
                "product": name,
                "title": _name(g, node) if node is not None else name,
                "status": str(g.value(node, SCHEMA.creativeWorkStatus) or "active") if node is not None else "active",
                "blocks": len(set(g.subjects(RDF.type, M5.Block))),
                "modules": len(set(g.subjects(RDF.type, M5.SoftwareModule))),
                "open_proposals": len(proposed),
            })
        return sorted(out, key=lambda p: p["title"].lower())

    def adopt(self, spaces: List[Dict[str, Any]]) -> List[str]:
        """Give each workspace of the cloud (edge.sync.listing) its folder here,
        with its m5:Product named as the workspace, until the sync brings what
        the cloud holds. Returns the products it made."""
        made = []
        for s in spaces:
            g = s.get("graph")
            if s.get("gone") or not g or not kn.GRAPH_NAME.fullmatch(g) or g in RESERVED or self.kb._path(g).exists():
                continue
            node = _iri("product", g)
            title = s.get("title") or s.get("name") or g

            def apply(gr: Graph, node: URIRef = node, title: str = title) -> None:
                if self._product_node(gr) is None:
                    gr.add((node, RDF.type, M5.Product))
                    gr.add((node, SCHEMA.name, Literal(title)))
            self.kb.change(g, apply)
            made.append(g)
        return made

    def new_product(self, title: str) -> Dict:
        """A product with a minted id (p-xxxxxxxx) that never changes; its title can."""
        title = (title or "").strip()
        if not title:
            raise ValueError("a product needs a title")
        existing = set(self.kb.graphs())
        name = _mint("p")
        while name in existing:
            name = _mint("p")
        node = _iri("product", name)

        def apply(g: Graph) -> None:
            g.add((node, RDF.type, M5.Product))
            g.add((node, SCHEMA.name, Literal(title)))
        self.kb.change(name, apply)
        return {"product": name, "title": title}

    def set_product(self, p: str, title: Optional[str] = None, status: Optional[str] = None) -> Dict:
        if status and status not in STATUSES:
            raise ValueError(f"a status is one of {', '.join(STATUSES)}")

        def apply(g: Graph) -> None:
            node = self._product_node(g)
            if node is None:
                node = _iri("product", p)
                g.add((node, RDF.type, M5.Product))
                g.add((node, SCHEMA.name, Literal(title or p)))
            if title:
                g.set((node, SCHEMA.name, Literal(title.strip())))
            if status:
                g.set((node, SCHEMA.creativeWorkStatus, Literal(status)))
        self._change(p, apply)
        return self.model(p)["product"]

    # ------------------------------------------------------------ the model

    def _product(self, g: Graph) -> URIRef:
        node = self._product_node(g)
        if node is None:
            raise ValueError("this graph has no m5:Product yet: give it a title first")
        return node

    def _add(self, p: str, kind: str, name: str, extra: Callable[[Graph, URIRef], None]) -> Dict:
        name = (name or "").strip()
        if not name:
            raise ValueError(f"a {kind} needs a name")
        cls, prefix = KINDS[kind]
        ident = _mint(prefix)
        node = _iri(kind, ident)

        def apply(g: Graph) -> None:
            g.add((node, RDF.type, cls))
            g.add((node, SCHEMA.name, Literal(name)))
            extra(g, node)
        self._change(p, apply)
        return {"id": ident, "kind": kind, "name": name}

    def add_block(self, p: str, name: str, kind: str = "") -> Dict:
        """A hardware block (a board, an enclosure, a sensor), electronic or mechanical."""
        concept = _key(kind, BLOCK_KINDS, "a block's kind") if kind else None

        def extra(g: Graph, node: URIRef) -> None:
            g.add((node, M5.partOf, self._product(g)))
            if concept is not None:
                g.add((node, M5.blockType, concept))
        return self._add(p, "block", name, extra)

    def add_module(self, p: str, name: str) -> Dict:
        """A software module: firmware, a driver, an app."""
        return self._add(p, "module", name, lambda g, node: g.add((node, M5.partOf, self._product(g))))

    def add_interface(self, p: str, name: str, connects: List[str]) -> Dict:
        """Where blocks and modules meet (a bus, a connector, an API): at least two of them."""
        ids = [str(c).strip() for c in (connects or []) if str(c).strip()]

        def extra(g: Graph, node: URIRef) -> None:
            for c in ids:
                g.add((node, M5.connects, self._find(g, c, "block", "module")))
        return self._add(p, "interface", name, extra)

    def connect(self, p: str, interface: str, connects: List[str]) -> Dict:
        """Set what an interface joins (replacing what it joined)."""
        def apply(g: Graph) -> None:
            n = self._find(g, interface, "interface")
            g.remove((n, M5.connects, None))
            for c in connects or []:
                g.add((n, M5.connects, self._find(g, str(c).strip(), "block", "module")))
        self._change(p, apply)
        return {"id": interface, "connects": list(connects or [])}

    def rename(self, p: str, item: str, name: str) -> Dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("a name is needed")

        def apply(g: Graph) -> None:
            g.set((self._find(g, item), SCHEMA.name, Literal(name)))
        self._change(p, apply)
        return {"id": item, "name": name}

    def link_article(self, p: str, item: str, article: str = "", quantity: int = 1) -> Dict:
        """Say which article of the workspace's stock a block or module is
        built from, and how many one product needs (ADR-0010 in
        maker-5-shared). An empty article removes the link."""
        article = (article or "").strip()
        if article and not ARTICLE_ID.match(article):
            raise ValueError(f"not an article id: {article}")
        q = 1 if quantity is None or quantity == "" else int(quantity)
        if q < 1:
            raise ValueError("a quantity is at least 1")

        def apply(g: Graph) -> None:
            n = self._find(g, item, "block", "module")
            g.remove((n, M5.usesArticle, None))
            g.remove((n, M5.quantity, None))
            if article:
                g.add((n, M5.usesArticle, URIRef(ARTICLE_IRI + article)))
                if q != 1:
                    g.add((n, M5.quantity, Literal(q, datatype=XSD.integer)))
        self._change(p, apply)
        return {"id": item, "article": article, "quantity": q if article else 0}

    def remove(self, p: str, item: str) -> Dict:
        """Remove an item. A block or module that an interface still connects
        is refused: the interface would be left with one end."""
        def apply(g: Graph) -> None:
            n = self._find(g, item)
            users = [i for i in g.subjects(M5.connects, n)]
            if users:
                raise ValueError(f"{_name(g, n)} is connected by {', '.join(_name(g, u) for u in users)}: "
                                 "remove or reconnect that first")
            g.remove((n, None, None))
            g.remove((None, None, n))
        self._change(p, apply)
        return {"removed": item}

    # ------------------------------------------------------------ proposals

    def propose(self, p: str, title: str, concerns: Optional[List[str]] = None, agent: str = "chat") -> Dict:
        """A change an agent suggests. Recorded, attributed to the agent, and
        left for a person to decide; it changes nothing else."""
        agent_id = "a-" + "".join(ch for ch in (agent or "chat").lower() if ch.isalnum() or ch == "-")[:30]

        def extra(g: Graph, node: URIRef) -> None:
            g.add((node, M5.proposalState, M5.Proposed))
            g.add((node, PROV.wasAttributedTo, _iri("agent", agent_id)))
            g.add((node, PROV.generatedAtTime, _now()))
            for c in concerns or []:
                g.add((node, M5.concerns, self._find(g, str(c).strip())))
        return self._add(p, "proposal", title, extra)

    def decide(self, p: str, proposal: str, decision: str, note: str = "") -> Dict:
        """A person approves or rejects a proposal (the page only, ADR-0006).
        The decision is a prov:Activity that used the proposal."""
        state = _key(decision, {"approved": M5.Approved, "rejected": M5.Rejected}, "a decision")
        ident = _mint("d")
        act = _iri("decision", ident)

        def apply(g: Graph) -> None:
            n = self._find(g, proposal, "proposal")
            if (n, M5.proposalState, M5.Proposed) not in g:
                raise ValueError("this proposal was decided already")
            g.set((n, M5.proposalState, state))
            g.add((act, RDF.type, PROV.Activity))
            g.add((act, PROV.used, n))
            g.add((act, PROV.wasAssociatedWith, _iri("person", _who())))
            g.add((act, PROV.endedAtTime, _now()))
            if note.strip():
                g.add((act, SCHEMA.description, Literal(note.strip())))
        self._change(p, apply)
        return {"id": proposal, "state": decision.lower(), "decision": ident}

    # ------------------------------------------------------------ reading

    def model(self, p: str) -> Dict:
        """The product and everything in it, as the page and the chat read it."""
        g = self._exists(p)
        node = self._product_node(g)

        def items(cls: URIRef) -> List[URIRef]:
            return sorted(set(g.subjects(RDF.type, cls)), key=lambda n: _name(g, n).lower())

        def part(n: URIRef) -> Dict:
            a = g.value(n, M5.usesArticle)
            if a is None:
                return {"article": "", "quantity": 0}
            return {"article": _local(a), "quantity": int(g.value(n, M5.quantity) or 1)}

        blocks = [{"id": _local(n), "name": _name(g, n),
                   "kind": _local(g.value(n, M5.blockType)).lower() if g.value(n, M5.blockType) else "", **part(n)}
                  for n in items(M5.Block)]
        modules = [{"id": _local(n), "name": _name(g, n), **part(n)} for n in items(M5.SoftwareModule)]
        interfaces = [{"id": _local(n), "name": _name(g, n),
                       "connects": sorted(({"id": _local(c), "name": _name(g, c)} for c in g.objects(n, M5.connects)),
                                          key=lambda c: c["name"].lower())}
                      for n in items(M5.Interface)]
        decisions = {o: a for a, o in g.subject_objects(PROV.used) if (a, RDF.type, PROV.Activity) in g}
        proposals = []
        for n in items(M5.Proposal):
            state = g.value(n, M5.proposalState)
            d = decisions.get(n)
            proposals.append({
                "id": _local(n), "title": _name(g, n),
                "state": _local(state).lower() if state is not None else "",
                "by": _local(g.value(n, PROV.wasAttributedTo) or "").removeprefix("a-"),
                "at": str(g.value(n, PROV.generatedAtTime) or ""),
                "concerns": [{"id": _local(c), "name": _name(g, c)} for c in g.objects(n, M5.concerns)],
                "decided": None if d is None else {
                    "by": _local(g.value(d, PROV.wasAssociatedWith) or ""),
                    "at": str(g.value(d, PROV.endedAtTime) or ""),
                    "note": str(g.value(d, SCHEMA.description) or "")},
            })
        proposals.sort(key=lambda x: (x["state"] != "proposed", x["at"]), reverse=False)
        return {
            "product": {"product": p, "title": _name(g, node) if node is not None else p,
                        "status": str(g.value(node, SCHEMA.creativeWorkStatus) or "active") if node is not None else "active",
                        "has_node": node is not None},
            "blocks": blocks, "modules": modules, "interfaces": interfaces, "proposals": proposals,
            "triples": len(g),
        }

    def export(self, p: str) -> str:
        return self._exists(p).serialize(format="turtle")

    # ------------------------------------------------------------ history (ADR-0004)

    def _history(self, p: str) -> rv.History:
        g = self._exists(p)
        if not hasattr(self.kb, "folder"):
            raise NotFound("this knowledge base keeps no history")
        h = rv.History(self.kb.folder(p))
        if h.latest() == 0:                         # a model saved before history was kept
            h.record(None, g)
        return h

    def revisions(self, p: str) -> List[Dict]:
        """Every saved state, newest first, with its tags."""
        return self._history(p).list()

    def revision(self, p: str, ref: str) -> str:
        """One revision (a number, a tag, or latest) as Turtle."""
        try:
            return self._history(p).text(ref)
        except rv.RevisionError as exc:
            raise NotFound(str(exc)) from None

    def diff(self, p: str, a: str, b: str = "latest") -> Dict:
        """What changed from revision a to revision b (numbers or tags), node by node."""
        h = self._history(p)
        try:
            na, nb = h.resolve(a), h.resolve(b)
        except rv.RevisionError as exc:
            raise NotFound(str(exc)) from None
        return {"from": na, "to": nb, **rv.compare(h.graph(na), h.graph(nb))}

    def tag_revision(self, p: str, revision: str, name: str, frozen: bool = False) -> Dict:
        """Name a revision; a frozen name is a baseline and never moves."""
        try:
            return self._history(p).tag(revision, name, frozen)
        except rv.RevisionError as exc:
            raise ValueError(str(exc)) from None

    def untag_revision(self, p: str, name: str) -> Dict:
        try:
            self._history(p).untag(name)
        except rv.RevisionError as exc:
            raise ValueError(str(exc)) from None
        return {"untagged": name}

    def restore(self, p: str, revision: str) -> Dict:
        """Make the model what it was at `revision`, as a NEW revision:
        history is never rewritten."""
        h = self._history(p)
        try:
            n = h.resolve(revision)
        except rv.RevisionError as exc:
            raise NotFound(str(exc)) from None
        old = h.graph(n)

        def apply(g: Graph) -> None:
            g.remove((None, None, None))
            for t in old:
                g.add(t)
        with rv.noting(f"restored r{n}"):
            self._change(p, apply)
        return {"restored": n, "revision": h.latest()}
