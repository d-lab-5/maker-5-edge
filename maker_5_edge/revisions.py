# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
revisions.py — every saved state of a product's model (ADR-0004 in maker-5-shared).

A product's model.ttl is overwritten on every change. Beside it, each save
that changes the graph also writes the new state as a numbered revision:

    <data>/<product>/revisions/r0001.ttl, r0002.ttl …     the whole model, as saved
    <data>/<product>/revisions/log.jsonl                   one line per revision:
                                                           {n, at, by, via, summary}
    <data>/<product>/revisions/tags.json                   {name: {n, frozen, at, by}}

A *baseline* is a frozen tag ("Prototype A"): it can neither be moved nor
removed. History is never rewritten: restoring revision n makes a new
revision with n's content. Revisions are compared statement by statement,
grouped by the node they describe.

Who and through what: `by` is the account running this edge; `via` is the
page, the chat (a confirmed proposal), an agent over MCP, or the cloud sync.
The web server sets it per request with `acting()`.
"""

from __future__ import annotations

import contextlib
import contextvars
import getpass
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

from rdflib import RDF, RDFS, Graph, Literal, URIRef
from rdflib.term import Node

DIR = "revisions"
LOG = "log.jsonl"
TAGS = "tags.json"
TAG_NAME = re.compile(r"[^\x00-\x1f]{1,80}")
VIA = ("page", "chat", "mcp", "sync", "edge")

_via: contextvars.ContextVar[str] = contextvars.ContextVar("revision_via", default="edge")
_note: contextvars.ContextVar[str] = contextvars.ContextVar("revision_note", default="")

Triple = Tuple[Node, Node, Node]
SCHEMA_NAME = URIRef("https://schema.org/name")      # Maker-5 names things with schema:name


class RevisionError(ValueError):
    pass


@contextlib.contextmanager
def acting(via: str) -> Iterator[None]:
    """Record changes made inside the block as made through `via`."""
    token = _via.set(via if via in VIA else "edge")
    try:
        yield
    finally:
        _via.reset(token)


@contextlib.contextmanager
def noting(text: str) -> Iterator[None]:
    """Put `text` in front of the summary of a revision made inside the block."""
    token = _note.set(text)
    try:
        yield
    finally:
        _note.reset(token)


def set_via(via: str) -> None:
    """For a request: the web server sets it before the view runs."""
    _via.set(via if via in VIA else "edge")


def _who() -> str:
    try:
        return getpass.getuser()
    except Exception:                    # no user name on this system
        return "edge"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _triples(g: Graph) -> Set[Triple]:
    return set(g)


def _short(term: Node) -> str:
    if isinstance(term, Literal):
        return str(term)
    s = str(term)
    return re.split(r"[#/]", s)[-1] if s.startswith("http") else s


class History:
    """The revisions of one product folder."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.dir = self.folder / DIR

    # ------------------------------------------------------------ reading

    def log(self) -> List[Dict]:
        path = self.dir / LOG
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def tags(self) -> Dict[str, Dict]:
        path = self.dir / TAGS
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def latest(self) -> int:
        entries = self.log()
        return entries[-1]["n"] if entries else 0

    def list(self) -> List[Dict]:
        """Newest first, each with the tags that point at it."""
        by_n: Dict[int, List[Dict]] = {}
        for name, t in self.tags().items():
            by_n.setdefault(t["n"], []).append({"name": name, "frozen": bool(t.get("frozen"))})
        return [{**e, "tags": sorted(by_n.get(e["n"], []), key=lambda t: t["name"])} for e in reversed(self.log())]

    def resolve(self, ref) -> int:
        """A revision number, a tag name, or "latest"."""
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            n = int(ref)
        elif ref in (None, "", "latest", "current"):
            n = self.latest()
        else:
            tag = self.tags().get(str(ref))
            if not tag:
                raise RevisionError(f"no revision or tag {ref}")
            n = tag["n"]
        if not self._file(n).exists():
            raise RevisionError(f"no revision {ref}")
        return n

    def _file(self, n: int) -> Path:
        return self.dir / f"r{n:04d}.ttl"

    def graph(self, ref) -> Graph:
        g = Graph()
        g.parse(self._file(self.resolve(ref)), format="turtle")
        return g

    def text(self, ref) -> str:
        return self._file(self.resolve(ref)).read_text(encoding="utf-8")

    # ------------------------------------------------------------ writing

    def _write(self, path: Path, data: str) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, path)

    def _append(self, entry: Dict) -> None:
        fd = os.open(self.dir / LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def record(self, before: Optional[Graph], after: Graph) -> Optional[int]:
        """Called by the product's save, under its lock: a new revision when
        the graph changed. A model saved before revisions existed becomes
        revision 1 first, so the first change can be compared with it."""
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        n = self.latest()
        if n == 0 and before is not None and len(before):
            self._write(self._file(1), before.serialize(format="turtle"))
            self._append({"n": 1, "at": _now(), "by": _who(), "via": "edge",
                          "summary": "the model as it was before history was kept"})
            n = 1
        last = self.graph(n) if n else (before if before is not None else Graph())
        if _triples(last) == _triples(after):
            return None
        n += 1
        self._write(self._file(n), after.serialize(format="turtle"))
        self._append({"n": n, "at": _now(), "by": _who(), "via": _via.get(),
                      "summary": ": ".join(x for x in (_note.get(), summary(compare(last, after))) if x)})
        return n

    def tag(self, ref, name: str, frozen: bool = False) -> Dict:
        name = str(name or "").strip()
        if not TAG_NAME.fullmatch(name):
            raise RevisionError("a tag is 1 to 80 characters")
        n = self.resolve(ref)
        tags = self.tags()
        old = tags.get(name)
        if old and old.get("frozen"):
            raise RevisionError(f"{name} is a baseline: it stays on revision {old['n']}")
        tags[name] = {"n": n, "frozen": bool(frozen), "at": _now(), "by": _who()}
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._write(self.dir / TAGS, json.dumps(tags, indent=1, ensure_ascii=False))
        return {"name": name, **tags[name]}

    def untag(self, name: str, withdrawn: bool = False) -> None:
        """Remove a tag. A baseline stays, unless `withdrawn` says the state
        it names was taken back."""
        tags = self.tags()
        if name not in tags:
            raise RevisionError(f"no tag {name}")
        if tags[name].get("frozen") and not withdrawn:
            raise RevisionError(f"{name} is a baseline and cannot be removed")
        del tags[name]
        self._write(self.dir / TAGS, json.dumps(tags, indent=1, ensure_ascii=False))


# ---------------------------------------------------------------- comparing

def _nodes(g: Graph) -> Dict[Node, Set[Tuple[Node, Node]]]:
    out: Dict[Node, Set[Tuple[Node, Node]]] = {}
    for s, p, o in g:
        out.setdefault(s, set()).add((p, o))
    return out


def _describe(s: Node, facts: Set[Tuple[Node, Node]]) -> Dict:
    label = next((str(o) for p, o in facts if p in (RDFS.label, SCHEMA_NAME)), "")
    kind = sorted(_short(o) for p, o in facts if p == RDF.type)
    return {"id": _short(s), "type": kind[0] if kind else "", "label": label}


def compare(a: Graph, b: Graph) -> Dict[str, List[Dict]]:
    """What changed from a to b, node by node: added, removed and changed
    nodes, and for a changed node each property's values before and after."""
    na, nb = _nodes(a), _nodes(b)
    added = [_describe(s, nb[s]) for s in nb if s not in na]
    removed = [_describe(s, na[s]) for s in na if s not in nb]
    changed = []
    for s in na:
        if s in nb and na[s] != nb[s]:
            props = sorted({p for p, _ in na[s] ^ nb[s]}, key=str)
            changes = [{
                "property": _short(p),
                "before": sorted(_short(o) for q, o in na[s] if q == p),
                "after": sorted(_short(o) for q, o in nb[s] if q == p),
            } for p in props]
            changed.append({**_describe(s, nb[s]), "changes": changes})
    key = lambda d: (d["type"], d["label"], d["id"])  # noqa: E731
    return {"added": sorted(added, key=key), "removed": sorted(removed, key=key), "changed": sorted(changed, key=key)}


def summary(diff: Dict[str, List[Dict]], limit: int = 3) -> str:
    """One line for the history: "+ Block Sensor board; ~ Interface I2C bus (connects)"."""
    parts = [f"+ {d['type']} {d['label'] or d['id']}".strip() for d in diff["added"]]
    parts += [f"− {d['type']} {d['label'] or d['id']}".strip() for d in diff["removed"]]
    parts += [f"~ {d['type']} {d['label'] or d['id']} ({', '.join(c['property'] for c in d['changes'])})".strip()
              for d in diff["changed"]]
    if not parts:
        return "no change"
    more = len(parts) - limit
    return "; ".join(parts[:limit]) + (f"; and {more} more" if more > 0 else "")
