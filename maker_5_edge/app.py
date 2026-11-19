#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
app.py — the Maker-5 Edge page and its API: the products on this edge and
the model each holds (products.py), their history (revisions.py), and the
files given to the chat (inbox.py).

    maker-5-edge-web                       # http://127.0.0.1:8773
    maker-5-edge-web --port 9000
    maker-5-edge-web --dir ~/maker5        # where mymaker5docs/ would be

Each cloud connection has its own folder (ADR-0013 in maker-5-shared):
mymaker5docs/prod/ and mymaker5docs/stage/, switched in the left bar. The
workspaces are the cloud's; each gets its folder here when it is listed.
    python3 -m maker_5_edge.app            # the same, from a checkout

The page, stop, restart, update and the About box come from core.server; the
chat and the cloud link from the edge layer. Every change goes through
Products, so the Maker-5 shapes refuse a broken model (422).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from flask import abort, jsonify, render_template, request

from . import bom_import
from . import fritzing as fz
from . import inbox as ib
from . import materials as mt
from . import parts
from . import products as pr
from . import revisions as rv
from . import selection as sel
from .core import server
from .core import workspace as ws
from .edge import cloud
from .edge import knowledge as kn
from .edge import settings as edge_settings
from .edge import sync as edge_sync

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


def _switched() -> None:
    """Another connection is current: its own folder, nothing open from the last one."""
    global _products
    _products = None
    sel.set()
    try:
        pr.migrate_layout()
    except OSError:
        pass


edge_routes.ON_SWITCH.append(_switched)


def _cloud_site() -> str:
    name = cloud.active_profile()
    return str(cloud.load_state(name).get("site") or (getattr(edge_settings, "ENVIRONMENTS", {}) or {}).get(name) or "")


# How often the page's list asks the cloud for its workspaces again, so a
# rename or a new workspace there shows here without a restart.
TENANT_FRESH_S = 30
_tenant_seen: dict = {}


def cloud_title(space: dict) -> str:
    """A workspace's name as the cloud shows it: the shared one, while it keeps
    its default name, is "Shared" (the cloud translates it)."""
    name = space.get("name") or ""
    return "Shared" if space.get("kind") == "shared" and name in ("Everyone", "Shared") else name


def workspaces() -> list:
    """The products here, as the cloud's workspaces: each workspace of the
    current connection gets its folder (adopt), its title is the cloud's name
    (a label: the folder and every id stay), and a product whose workspace was
    removed in the cloud is marked gone (its files stay)."""
    pp = products()
    gone = set()
    name = cloud.active_profile()
    if cloud.per_connection() and name in cloud.linked_profiles():
        try:
            if time.time() - _tenant_seen.get(name, 0) > TENANT_FRESH_S:
                cloud.tenant(name, refresh=True)
                _tenant_seen[name] = time.time()
            listed = edge_sync.listing(pp.kb)
            pp.adopt(listed)
            gone = {s["graph"] for s in listed if s["gone"]}
            titles = {p["product"]: p["title"] for p in pp.products()}
            for s in listed:
                want = cloud_title(s)
                if not s["gone"] and want and s["graph"] in titles and titles[s["graph"]] != want:
                    pp.set_product(s["graph"], title=want)
        except cloud.CloudError:
            pass
    return [{**p, "gone": p["product"] in gone} for p in pp.products()]


def run(fn, *args, **kwargs):
    try:
        return jsonify(fn(*args, **kwargs))
    except (pr.NotFound, ib.NotFound) as e:
        return jsonify({"errors": [str(e)]}), 404
    except kn.Invalid as e:
        return jsonify({"errors": e.messages}), 422
    except mt.NoSpace as e:
        return jsonify({"errors": [str(e)]}), 409
    except cloud.NotLinked as e:
        return jsonify({"errors": [f"this edge is not linked to a cloud yet: {e}"]}), 409
    except cloud.CloudError as e:
        # the cloud refused (422: not free, not taken) or failed: say its words
        return jsonify({"errors": [str(e.payload.get("message") or e) if e.payload else str(e)]}), 422 if e.status == 422 else 502
    except fz.FritzingError as e:
        return jsonify({"errors": [str(e)]}), 502
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
    return run(workspaces)


@app.post("/api/products")
def new_product():
    if cloud.per_connection():
        site = _cloud_site()
        return jsonify({"errors": [f"a workspace is made in the cloud ({site or 'its Settings'}), by an admin "
                                   "of the organisation; it then appears here"], "site": site}), 409
    return run(products().new_product, **fields("title"))


@app.get("/api/products/<p>")
def model(p: str):
    return run(products().model, p)


@app.post("/api/products/<p>")
def set_product(p: str):
    b = fields("title", "status")
    if cloud.per_connection() and "title" in b:
        return jsonify({"errors": ["a workspace is renamed in the cloud; its new name shows here by itself"],
                        "site": _cloud_site()}), 409
    return run(products().set_product, p, **b)


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


@app.post("/api/products/<p>/items/<item>/article")
def link_article(p: str, item: str):
    """Which article of the stock a block or module is built from (ADR-0010)."""
    return run(products().link_article, p, item, **fields("article", "quantity"))


# ---- a BOM into the model, and the hardware canvas (ADR-0014)

def _bom_text() -> str:
    b = body()
    if b.get("inbox"):
        out, offset = [], 0
        while True:
            part = ib.read(str(b["inbox"]), offset)
            out.append(part["text"])
            offset += len(part["text"])
            if not part["more"] or offset > 400_000:
                return "".join(out)
    return str(b.get("text") or "")


@app.post("/api/products/<p>/import/bom")
def bom_preview(p: str):
    """What importing this BOM (text, or a file in the inbox) would make. Writes nothing."""
    return run(lambda: bom_import.preview(products(), p, _bom_text()))


@app.post("/api/products/<p>/import/bom/apply")
def bom_apply(p: str):
    """Make what a reviewed preview says: proposed articles in the cloud, then one revision."""
    return run(bom_import.apply, products(), p, body().get("preview") or {})


@app.get("/api/products/<p>/canvas")
def canvas(p: str):
    return run(products().canvas, p)


@app.post("/api/products/<p>/canvas/place")
def canvas_place(p: str):
    b = body()

    def placed():
        pp = products()
        block = str(b.get("block") or "")
        name = next((x["name"] for x in pp.model(p)["blocks"] if x["id"] == block), "")
        return pp.place(p, block, b.get("x", 0), b.get("y", 0), default_pins=parts.pins_for(name)["pins"])
    return run(placed)


@app.post("/api/products/<p>/canvas/pins")
def canvas_pins(p: str):
    b = body()
    return run(products().set_pins, p, str(b.get("block") or ""), b.get("pins") or [])


# ---- parts from the Fritzing library (fritzing.py; ADR-0016)

@app.get("/api/fritzing/search")
def fritzing_search():
    return run(fz.search, request.args.get("q", ""), request.args.get("limit", 30, type=int))


@app.get("/api/fritzing/part")
def fritzing_part():
    return run(fz.part, request.args.get("path", ""))


@app.get("/api/fritzing/image")
def fritzing_image():
    """A part's breadboard picture. The page shows it as an <image>, where an
    SVG runs nothing; the policy below says so to any other reader too."""
    try:
        svg = fz.image(request.args.get("path", ""))
    except (ValueError, fz.FritzingError):
        abort(404)
    if svg is None:
        abort(404)
    return app.response_class(svg, mimetype="image/svg+xml", headers={
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"})


@app.post("/api/products/<p>/canvas/fritzing")
def canvas_fritzing(p: str):
    """A block takes a Fritzing part: its pins (and the part's name in the model)."""
    b = body()

    def used():
        part = fz.part(str(b.get("path") or ""))
        known = parts.pins_for(part["title"])
        pins = parts.physical(part["pins"], known["pins"]) if known["title"] else part["pins"]
        return {**products().use_part(p, str(b.get("block") or ""), part["path"], pins),
                "title": part["title"], "author": part["author"], "license": part["license"]}
    return run(used)


@app.post("/api/products/<p>/wires")
def add_wire(p: str):
    b = body()
    return run(products().add_wire, p, str(b.get("from") or ""), str(b.get("to") or ""),
               str(b.get("color") or ""), str(b.get("interface") or ""))


@app.post("/api/products/<p>/wires/<wire>")
def set_wire(p: str, wire: str):
    return run(products().set_wire, p, wire, **fields("color", "interface"))


# ---- parts: the workspace's stock in the cloud (materials.py)

@app.get("/api/stock")
def stock():
    return run(mt.stock, request.args.get("q", ""), request.args.get("category", ""))


@app.get("/api/stock/<article_id>")
def stock_article(article_id: str):
    return run(mt.article, article_id)


@app.get("/api/boxes")
def stock_boxes():
    return run(mt.boxes, request.args.get("q", ""), request.args.get("workspace", ""))


@app.get("/api/boxes/<ref>")
def stock_box(ref: str):
    return run(mt.box, ref)


@app.get("/api/codes/resolve")
def resolve_code():
    return run(mt.resolve, request.args.get("code", ""))


@app.get("/api/products/<p>/bom")
def bom(p: str):
    return run(mt.bom, products(), p)


@app.post("/api/products/<p>/parts/<step>")
def take_parts(p: str, step: str):
    b = fields("article", "qty", "unit", "note")
    return run(mt.take, products(), p, step, str(b.get("article", "")), b.get("qty"), b.get("unit"), str(b.get("note", "")))


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


def _file_name(p: str) -> str:
    """A download's name: the workspace's title as a slug ("door-bell"), not
    its folder, which keeps the name it was first given."""
    try:
        title = next((x["title"] for x in products().products() if x["product"] == p), "")
    except Exception:  # noqa: BLE001 - a name is never worth a failed download
        title = ""
    return cloud.space_slug(title) if title else p


@app.get("/api/products/<p>/export.ttl")
def export(p: str):
    try:
        ttl = products().export(p)
    except pr.NotFound:
        abort(404)
    return app.response_class(ttl, mimetype="text/turtle",
                              headers={"Content-Disposition": f'attachment; filename="{_file_name(p)}.ttl"'})


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
    return app.response_class(ttl, mimetype="text/turtle",
                              headers={"Content-Disposition": f'inline; filename="{_file_name(p)}-r{ref}.ttl"'})


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

DATA_DIR = "mymaker5docs"


def _move_old_folder(old: Path, new: Path) -> None:
    """The products of an edge from before connections had their own folders
    (./mydocs/<product>/) are prod's now: ./mymaker5docs/prod/. Never
    overwrites; an empty old folder is just removed."""
    if not old.is_dir() or old.resolve() == new.resolve():
        return
    if not any(old.iterdir()):
        old.rmdir()
        return
    target = new / "prod"
    if target.exists():
        print(f"  {old}/ kept: {target}/ exists already, move what you need by hand", flush=True)
        return
    new.mkdir(parents=True, exist_ok=True)
    os.replace(old, target)
    print(f"  moved {old}/ to {target}/ (prod's folder)", flush=True)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="maker-5-edge-web",
                                 description=__doc__.strip().splitlines()[0])
    server.add_server_args(ap)
    ap.add_argument("--dir", default=DATA_DIR,
                    help=f"where products and their files live, a folder per connection (default: ./{DATA_DIR})")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    if args.dir == DATA_DIR:
        _move_old_folder(Path(ws.FOLDERS[ws.USER].name), Path(DATA_DIR))
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
