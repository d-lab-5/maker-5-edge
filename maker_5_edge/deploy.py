# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
deploy.py — a workspace's software/ onto its boards (ADR-0020 in maker-5-shared).

A target is a board of the model (a block) and how to reach it: a host, a
user and a folder over SSH with the person's own key, or this computer when
the edge runs on the board itself. Targets are kept beside the model in
deploy.json, on this edge only: host names and users are nobody else's
business, so they are never in the repository or the cloud.

    targets(products, p)              the targets, each with its last deployment
    save_target(products, p, t)       add or change one (the page only, never the chat)
    drop_target(products, p, id)
    deploy(products, p, id)           copy software/ there, run its restart
                                      command, read its log; record the commit
                                      on the block (m5:deployedCommit, m5:deployedAt)

Safety:
- SSH runs with BatchMode: the person's key or agent, never a password typed here.
- A folder is only written if it is new, empty, or one a deployment made
  (it holds .maker5-deploy); anything else is refused, so a wrong path never
  wipes a home folder.
- The restart and log commands are the person's own, set on the page.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from rdflib import Literal
from rdflib.namespace import XSD

from . import git_repo

MARKER = ".maker5-deploy"
MAX_OUT = 20_000
HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,252})$|^\[?[0-9a-fA-F:.]{2,45}\]?$")
USER = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}$")
PATH = re.compile(r"^[A-Za-z0-9_./~-]{1,200}$")
FORBIDDEN_PATHS = {"/", "~", "~/", ".", "..", "/home", "/root", "/etc", "/usr", "/var", "/opt", "/tmp", "/srv"}


class DeployError(RuntimeError):
    """The board could not be reached, or refused."""


def _file(products: Any, p: str) -> Path:
    return products.kb.folder(p) / "deploy.json"


def _load(products: Any, p: str) -> Dict[str, Any]:
    f = _file(products, p)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"targets": []}


def _save(products: Any, p: str, d: Dict[str, Any]) -> None:
    f = _file(products, p)
    f.write_text(json.dumps(d, indent=1), encoding="utf-8")
    f.chmod(0o600)


def targets(products: Any, p: str) -> List[Dict[str, Any]]:
    names = {b["id"]: b["name"] for b in products.model(p)["blocks"]}
    return [{**t, "block_name": names.get(t["block"], t["block"])} for t in _load(products, p)["targets"]]


def _clean(products: Any, p: str, t: Dict[str, Any]) -> Dict[str, Any]:
    blocks = {b["id"] for b in products.model(p)["blocks"]}
    block = str(t.get("block") or "")
    if block not in blocks:
        raise ValueError("a target is one of the workspace's blocks: the board the software runs on")
    host = str(t.get("host") or "").strip()
    user = str(t.get("user") or "").strip()
    path = str(t.get("path") or "").strip().rstrip("/")
    if host and not HOST.match(host):
        raise ValueError("a host is a name or an address, e.g. door-pi.local")
    if host and not USER.match(user):
        raise ValueError("a user is the account on the board, e.g. pi")
    if not PATH.match(path) or ".." in path.split("/") or path in FORBIDDEN_PATHS or path.rstrip("/") in FORBIDDEN_PATHS:
        raise ValueError("a folder of its own, e.g. ~/door-bell (no spaces, not a home or system folder)")
    port = int(t.get("port") or 22)
    if not 1 <= port <= 65535:
        raise ValueError("a port is 1 to 65535")
    cmds = {}
    for k in ("restart", "log"):
        v = str(t.get(k) or "").strip()
        if "\n" in v or len(v) > 300:
            raise ValueError(f"the {k} command is one line, at most 300 characters")
        cmds[k] = v
    return {"block": block, "host": host, "user": user if host else "", "port": port, "path": path, **cmds}


def save_target(products: Any, p: str, t: Dict[str, Any]) -> Dict[str, Any]:
    d = _load(products, p)
    clean = _clean(products, p, t)
    ident = str(t.get("id") or "")
    old = next((x for x in d["targets"] if x["id"] == ident), None) if ident else None
    if old:
        old.update(clean)
    else:
        if len(d["targets"]) >= 20:
            raise ValueError("at most 20 targets in a workspace")
        old = {"id": "t-" + uuid.uuid4().hex[:8], **clean, "last": None}
        d["targets"].append(old)
    _save(products, p, d)
    return old


def drop_target(products: Any, p: str, ident: str) -> Dict[str, Any]:
    d = _load(products, p)
    d["targets"] = [x for x in d["targets"] if x["id"] != ident]
    _save(products, p, d)
    return {"id": ident, "removed": True}


# ------------------------------------------------------------ running ----

def run(args: List[str], timeout: int = 180) -> str:
    """A command here (tests replace this). Fails with what it said."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError as e:
        raise DeployError(f"{args[0]} is not installed on this computer") from e
    except subprocess.TimeoutExpired as e:
        raise DeployError(f"{args[0]} took too long") from e
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        raise DeployError(out.strip()[-600:] or f"{args[0]} failed ({r.returncode})")
    return out


def _ssh(t: Dict[str, Any]) -> List[str]:
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-p", str(t["port"]), f"{t['user']}@{t['host']}"]


def _shell(t: Dict[str, Any], command: str) -> str:
    """A command on the board: over SSH, or here when the edge is on the board."""
    if t["host"]:
        return run(_ssh(t) + [command])
    return run(["sh", "-c", command])


def _q(path: str) -> str:
    """A folder for the shell: ~ stays the home folder, the rest quoted."""
    if path.startswith("~/"):
        return '"$HOME"/' + "'" + path[2:].replace("'", "'\\''") + "'"
    return "'" + path.replace("'", "'\\''") + "'"


def _ready(t: Dict[str, Any]) -> None:
    """The folder is new, empty, or ours; then it is made and marked."""
    d = _q(t["path"])
    check = (f"if [ -e {d} ] && [ ! -e {d}/{MARKER} ] && [ -n \"$(ls -A {d} 2>/dev/null)\" ]; "
             f"then echo NOT-OURS; else mkdir -p {d} && touch {d}/{MARKER} && echo OK; fi")
    if "NOT-OURS" in _shell(t, check):
        raise DeployError(f"{t['path']} holds files no deployment put there: choose a folder of its own")


def _copy(t: Dict[str, Any], src: Path) -> None:
    flags = ["-rlptz", "--delete", f"--exclude={MARKER}", "--exclude=__pycache__/"]
    if t["host"]:
        dest = t["path"] if not t["path"].startswith("~/") else t["path"][2:]
        run(["rsync", *flags, "-e", " ".join(_ssh(t)[:-1]), f"{src}/", f"{t['user']}@{t['host']}:{dest}/"], timeout=600)
    else:
        run(["rsync", *flags, f"{src}/", f"{Path(t['path']).expanduser()}/"], timeout=600)


def deploy(products: Any, p: str, ident: str) -> Dict[str, Any]:
    d = _load(products, p)
    t = next((x for x in d["targets"] if x["id"] == ident), None)
    if t is None:
        raise ValueError(f"no target {ident}")
    repo = git_repo._linked(products, p)
    src = repo / "software"
    if not src.is_dir():
        raise DeployError("the repository has no software/ yet")
    git_repo.prepare(products, p)                       # the pin map as the wiring is now
    commit = git_repo.git(repo, "rev-parse", "HEAD").strip()
    dirty = bool(git_repo.git(repo, "status", "--porcelain", "--", "software").strip())
    at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    steps: List[Dict[str, Any]] = []
    ok = True
    try:
        _ready(t)
        steps.append({"step": "folder", "ok": True})
        _copy(t, src)
        steps.append({"step": "copy", "ok": True})
        if t["restart"]:
            steps.append({"step": "restart", "ok": True, "out": _shell(t, t["restart"])[-MAX_OUT:]})
    except DeployError as e:
        ok = False
        steps.append({"step": "failed", "ok": False, "out": str(e)})
    if t["log"]:
        try:
            steps.append({"step": "log", "ok": True, "out": _shell(t, t["log"])[-MAX_OUT:]})
        except DeployError as e:
            steps.append({"step": "log", "ok": False, "out": str(e)})
    if ok:
        def apply(g):
            from .products import M5
            b = products._find(g, t["block"], "block")
            g.set((b, M5.deployedCommit, Literal(commit)))
            g.set((b, M5.deployedAt, Literal(at.isoformat().replace("+00:00", "Z"), datatype=XSD.dateTime)))
        products._change(p, apply)
    t["last"] = {"at": at.isoformat(), "commit": commit, "dirty": dirty, "ok": ok}
    _save(products, p, d)
    return {"target": ident, "ok": ok, "commit": commit, "dirty": dirty, "steps": steps}
