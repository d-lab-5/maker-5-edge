#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
app.py — the Maker-5 Edge page and its API: the products on this edge and
the model each holds (products.py), their history (revisions.py), and the
files given to the chat (inbox.py).

    maker-5-edge-web                       # http://127.0.0.1:8773
    maker-5-edge-web --port 9000
    python3 -m maker_5_edge.app            # the same, from a checkout

The page, stop, restart, update and the About box come from core.server; the
chat and the cloud link from the edge layer. Every change goes through
Products, so the Maker-5 shapes refuse a broken model (422).
"""

from __future__ import annotations

import argparse
import sys

from flask import abort, jsonify, render_template, request

from . import inbox as ib
from . import products as pr
from . import revisions as rv
from . import selection as sel
from .core import server
from .core import workspace as ws
from .edge import knowledge as kn

app = server.create_app(__name__)

from .edge import routes as edge_routes  # edge layer
edge_routes.install(app)
app.config["MAX_CONTENT_LENGTH"] = ib.MAX_BYTES + 1024 * 1024   # a STEP model can be large


def body() -> dict:
    data = request.get_json(silent=True)
    if data is None and not request.data:
        return {}
    if not isinstance(data, dict):
        abort(400, "expected a JSON object body")
    return data


def fields(*names: str) -> dict:
    b = body()
    return {k: b[k] for k in names if k in b}


# ------------------------------------------------------------------ page ----

@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/favicon.ico")
def favicon():
    """Browsers ask for this by name whatever the page links to."""
    return app.send_static_file("favicon.svg")


# -------------------------------------------------------------- products ----

_products = None


def products() -> pr.Products:
    global _products
    if _products is None:
        _products = pr.Products()
    return _products


def run(fn, *args, **kwargs):
    try:
        return jsonify(fn(*args, **kwargs))
    except (pr.NotFound, ib.NotFound) as e:
        return jsonify({"errors": [str(e)]}), 404
    except kn.Invalid as e:
        return jsonify({"errors": e.messages}), 422
    except (ValueError, TypeError) as e:
        return jsonify({"errors": [str(e)]}), 400


@app.before_request
def _revision_via() -> None:
    """Who a revision is made through: an agent names itself with X-Agent
    (core/mcp_bridge.py); a confirmed chat proposal is replayed through
    Flask's test client (edge/routes.py), whose requests carry Werkzeug's own
    User-Agent; everything else is the page."""
    if request.headers.get("X-Agent"):
        rv.set_via("mcp")
    elif request.headers.get("User-Agent", "").startswith("Werkzeug/"):
        rv.set_via("chat")
    else:
        rv.set_via("page")


@app.get("/api/selection")
def get_selection():
    return jsonify(sel.get())


@app.post("/api/selection")
def set_selection():
    return run(sel.set, **fields("product", "item", "file"))


@app.get("/api/products")
def list_products():
    return run(products().products)


@app.post("/api/products")
def new_product():
    return run(products().new_product, **fields("title"))


@app.get("/api/products/<p>")
def model(p: str):
    return run(products().model, p)


@app.post("/api/products/<p>")
def set_product(p: str):
    return run(products().set_product, p, **fields("title", "status"))


@app.post("/api/products/<p>/blocks")
def add_block(p: str):
    return run(products().add_block, p, **fields("name", "kind"))


@app.post("/api/products/<p>/modules")
def add_module(p: str):
    return run(products().add_module, p, **fields("name"))


@app.post("/api/products/<p>/interfaces")
def add_interface(p: str):
    return run(products().add_interface, p, **fields("name", "connects"))


@app.post("/api/products/<p>/interfaces/<item>/connects")
def connect(p: str, item: str):
    return run(products().connect, p, item, **fields("connects"))


@app.post("/api/products/<p>/items/<item>/rename")
def rename(p: str, item: str):
    return run(products().rename, p, item, **fields("name"))


@app.delete("/api/products/<p>/items/<item>")
def remove(p: str, item: str):
    return run(products().remove, p, item)


@app.post("/api/products/<p>/proposals")
def propose(p: str):
    b = fields("title", "concerns", "agent")
    if request.headers.get("X-Agent") and not b.get("agent"):
        b["agent"] = request.headers["X-Agent"]
    return run(products().propose, p, **b)


@app.post("/api/products/<p>/proposals/<item>/decide")
def decide(p: str, item: str):
    """A person's act on the page (ADR-0006 in maker-5-shared): refused from an agent, and
    absent from the chat's CHAT_ALLOWED, so no proposal can run it."""
    if request.headers.get("X-Agent") or request.headers.get("User-Agent", "").startswith("Werkzeug/"):
        return jsonify({"errors": ["a proposal is decided by a person, on the page"]}), 403
    return run(products().decide, p, item, **fields("decision", "note"))


@app.get("/api/products/<p>/export.ttl")
def export(p: str):
    try:
        ttl = products().export(p)
    except pr.NotFound:
        abort(404)
    return app.response_class(ttl, mimetype="text/turtle",
                              headers={"Content-Disposition": f'attachment; filename="{p}.ttl"'})


# ---- history: every saved state, tags and baselines, compare, restore

@app.get("/api/products/<p>/revisions")
def revisions(p: str):
    return run(products().revisions, p)


@app.get("/api/products/<p>/revisions/<ref>.ttl")
def revision(p: str, ref: str):
    try:
        ttl = products().revision(p, ref)
    except pr.NotFound:
        abort(404)
    return app.response_class(ttl, mimetype="text/turtle")


@app.get("/api/products/<p>/diff")
def diff(p: str):
    return run(products().diff, p, request.args.get("from", ""), request.args.get("to", "latest"))


@app.post("/api/products/<p>/revisions/<ref>/tag")
def tag_revision(p: str, ref: str):
    return run(products().tag_revision, p, ref, **fields("name", "frozen"))


@app.delete("/api/products/<p>/tags/<name>")
def untag_revision(p: str, name: str):
    return run(products().untag_revision, p, name)


@app.post("/api/products/<p>/revisions/<ref>/restore")
def restore_revision(p: str, ref: str):
    return run(products().restore, p, ref)


# --------------------------------------------------------------- inbox ----
#
# Files given to the chat (inbox.py). Uploading is the person's act on the
# page; the chat reads them and proposes what to do with them.

@app.get("/api/inbox")
def inbox_files():
    return jsonify(ib.files())


@app.post("/api/inbox")
def inbox_add():
    f = request.files.get("file")
    if f is None:
        return jsonify({"errors": ["send the file as multipart field 'file'"]}), 400

    def added():
        m = ib.add(f.filename or "", f.read())
        cur = sel.get()
        sel.set(cur.get("product", ""), cur.get("item", ""), m["id"])
        return m
    return run(added)


@app.get("/api/inbox/<fid>")
def inbox_read(fid: str):
    return run(ib.read, fid, request.args.get("offset", 0, type=int),
               request.args.get("limit", ib.TEXT_LIMIT, type=int))


@app.delete("/api/inbox/<fid>")
def inbox_remove(fid: str):
    return run(ib.remove, fid)


# ------------------------------------------------------------------ main ----

def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="maker-5-edge-web",
                                 description=__doc__.strip().splitlines()[0])
    server.add_server_args(ap)
    ap.add_argument("--dir", default=ws.FOLDERS[ws.USER].name,
                    help="where products and their files live (default: ./mydocs)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    ws.configure(user_dir=args.dir)
    # One folder per product (ADR-0003 in maker-5-shared): the edge layer's routes and first
    # start build kn.KnowledgeBase() when called, so binding it here gives
    # them the same layout as the products.
    pr.migrate_layout()
    kn.KnowledgeBase = pr.ProductKB
    lines = [f"  {f['label'].lower():<13} {f['path']}" for f in ws.folders()]
    edge_routes.start_background()  # edge layer
    return server.serve(app, args, lines=lines)


if __name__ == "__main__":
    raise SystemExit(main())
