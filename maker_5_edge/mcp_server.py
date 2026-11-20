#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
mcp_server.py — MCP access to maker-5-edge.

Exposes the tool over stdio, so an agent can work on the same data a person has
open in the browser. The pure engine calls run in-process; everything that
touches files goes through the web server (core.mcp_bridge), which is started
on demand, so browser and agent never disagree about what is on disk.

    maker-5-edge-mcp                               # talks to 127.0.0.1:8773
    maker-5-edge-mcp --port 9000
    maker-5-edge-mcp --no-autostart                # fail instead of starting one
    python3 -m maker_5_edge.mcp_server            # the same, from a checkout

Register it in .mcp.json (a checkout already has one), or install the Claude
Code plugin, which brings this server and the skill together.

Nothing may be written to stdout: that is the MCP transport. Log to stderr.
"""

from __future__ import annotations

import argparse
import urllib.parse
from typing import List, Optional

from mcp.server.mcpserver import MCPServer

from .core import mcp_bridge as web

server = MCPServer(
    name="maker-5-edge",
    instructions=(
        "Maker-5 Edge keeps the products of a hardware-and-software maker on "
        "this workstation. Each product is one model graph (Maker-5 ontology): "
        "hardware blocks, software modules, the interfaces that connect them, "
        "and proposals for changes. Read with products(), model() and "
        "selection() (what the person has open). Change with new_product, "
        "add_block, add_module, add_interface, rename and remove; the person "
        "confirms each one. Record a larger idea as propose(): only the person "
        "approves or rejects a proposal, on the page. Every saved state is a "
        "revision: revisions(), diff(), tag_revision(), restore(). Files the "
        "person drops for you are in inbox(); read them with read_file(). "
        "Parts: stock(), resolve_code(), link_article(), bom(), "
        "reserve_parts(), release_parts(), return_parts(). Boxes (read "
        "only): boxes(), box(). A BOM in Markdown: import_bom(). Hardware "
        "wiring: canvas(), place(), set_pins(), wire(); remove a wire with remove(). "
        "Fritzing parts: fritzing_search(), fritzing_part(), fritzing_use()."
    ),)

web.add_core_tools(server)

from .edge.mcp_tools import act, add_edge_tools  # edge layer
add_edge_tools(server)


def _q(x: str) -> str:
    return urllib.parse.quote(x, safe="")


def _p(product: str) -> str:
    return f"/api/products/{_q(product)}"


def _get(path: str):
    web.ensure_server()
    return web.call("GET", path)


def _clean(**kw) -> dict:
    return {k: v for k, v in kw.items() if v is not None and v != ""}


# ------------------------------------------------------------- reading ----

@server.tool()
def selection() -> dict:
    """What the person has open on the page: a product, an item in it, and
    the file they last dropped for you (read it with read_file)."""
    return _get("/api/selection")


@server.tool()
def products() -> list:
    """Every product on this edge: its id, title, status, how many blocks and
    modules it has, and how many proposals wait for a decision."""
    return _get("/api/products")


@server.tool()
def model(product: str) -> dict:
    """One product's model: its blocks (with kind), software modules,
    interfaces (with the blocks and modules each connects) and proposals
    (state, who made them, who decided). Ids are what the change tools take."""
    return _get(_p(product))


@server.tool()
def inbox() -> list:
    """The files the person gave you: the open product's and the shared
    inbox's. Each has an id, a name, the kind found in its content (kicad,
    step, csv, xlsx, turtle, json, pdf, text) and a short note."""
    return _get("/api/inbox")


@server.tool()
def read_file(file: str, offset: int = 0, limit: int = 20000) -> dict:
    """The text of a file from inbox(), in slices: `more` says whether to read on
    from offset + limit."""
    return _get(f"/api/inbox/{_q(file)}?offset={int(offset)}&limit={int(limit)}")


# ------------------------------------------------------------- changing ----

@server.tool()
def new_product(title: str) -> dict:
    """Start a product on an edge without a cloud of its own. On this edge
    workspaces are made in the cloud by an admin and appear here by
    themselves (refused here: say so, and point to the cloud's Settings)."""
    return act(f"New product “{title}”", "POST", "/api/products", {"title": title})


@server.tool()
def set_product(product: str, title: str = "", status: str = "") -> dict:
    """Set a product's status: active, done or archived. Its name is the
    cloud workspace's and changes there (a rename here is refused); its id
    and folder never change."""
    return act(f"Update product {product}", "POST", _p(product), _clean(title=title, status=status))


@server.tool()
def add_block(product: str, name: str, kind: str = "") -> dict:
    """A hardware block: a board, an enclosure, a sensor. kind is electronic
    or mechanical (leave it empty when it is not known)."""
    return act(f"Add block “{name}”", "POST", _p(product) + "/blocks", _clean(name=name, kind=kind))


@server.tool()
def add_module(product: str, name: str) -> dict:
    """A software module: firmware, a driver, an app."""
    return act(f"Add software module “{name}”", "POST", _p(product) + "/modules", {"name": name})


@server.tool()
def add_interface(product: str, name: str, connects: List[str]) -> dict:
    """An interface (a bus, a connector, an API) between at least two blocks
    or modules, given by their ids from model()."""
    return act(f"Add interface “{name}”", "POST", _p(product) + "/interfaces",
               {"name": name, "connects": list(connects)})


@server.tool()
def connect(product: str, interface: str, connects: List[str]) -> dict:
    """Set what an interface joins, replacing what it joined (at least two ids)."""
    return act(f"Reconnect {interface}", "POST", _p(product) + f"/interfaces/{_q(interface)}/connects",
               {"connects": list(connects)})


@server.tool()
def rename(product: str, item: str, name: str) -> dict:
    """Rename a block, module, interface or proposal."""
    return act(f"Rename {item} to “{name}”", "POST", _p(product) + f"/items/{_q(item)}/rename", {"name": name})


@server.tool()
def remove(product: str, item: str) -> dict:
    """Remove an item. A block or module that an interface still connects is
    refused: remove or reconnect the interface first."""
    return act(f"Remove {item}", "DELETE", _p(product) + f"/items/{_q(item)}", {})


@server.tool()
def propose(product: str, title: str, concerns: Optional[List[str]] = None) -> dict:
    """Record a proposal: a change you suggest, attributed to you, that waits
    for the person. It changes nothing else. Only the person approves or
    rejects it, on the page; there is no tool for that."""
    return act(f"Propose “{title}”", "POST", _p(product) + "/proposals",
               _clean(title=title, concerns=list(concerns or []) or None))


# --------------------------------------------------------------- parts ----
# The organisation's stock lives in the cloud (ADR-0008, ADR-0010 in maker-5-shared).

@server.tool()
def stock(query: str = "", category: str = "") -> list:
    """The organisation's stock, shared by its workspaces: articles (id, name, category, maker, part
    number, place) with onHand, reserved and free. Search by words; a
    category is a code of catalogue(), a top one ("controllers") or a sub one
    ("controllers/sbc"); a top one holds its subs."""
    return _get("/api/stock?" + urllib.parse.urlencode(_clean(q=query, category=category)))


@server.tool()
def catalogue() -> list:
    """The stock's categories (two levels: code "top" or "top/sub", label in
    en, de, fr) with how many articles each has and how many are free. Look
    here first to see what the organisation has."""
    return _get("/api/catalogue")


@server.tool()
def free_parts(category: str = "") -> dict:
    """What a new design can use before anything is bought: articles with
    free stock in a category, and parts that passive workspaces hold
    (reserved, but no edge used that workspace in 14 days), which a person
    may release there and take here."""
    return _get("/api/catalogue/free?" + urllib.parse.urlencode(_clean(category=category)))


@server.tool()
def stock_article(article: str) -> dict:
    """One article of the stock: its units (serial, state, product, firmware),
    its codes, which products took it, and what happened to it."""
    return _get(f"/api/stock/{_q(article)}")


@server.tool()
def boxes(query: str = "", workspace: str = "") -> list:
    """The organisation's boxes (cartons, bags, drawers with a large label):
    name, kind, where it is (place, or the box it sits in), the workspace it
    is marked for, and how many links and files it keeps. Search by words;
    give a workspace (a product's title) for only its boxes."""
    return _get("/api/boxes?" + urllib.parse.urlencode(_clean(q=query, workspace=workspace)))


@server.tool()
def box(box: str) -> dict:
    """One box, by its id (x-…) or the code on its label: the boxes it sits
    in, what it holds (units with what is installed in them, counted parts,
    other boxes), its links (firmware, CAD, schematic, datasheet, docs, repo)
    and its files, and what happened to it. Read only: parts are checked in
    and out on a phone, at the box."""
    return _get(f"/api/boxes/{_q(box)}")


@server.tool()
def resolve_code(code: str) -> dict:
    """What a code points at: one of our labels (HTTPS://MAKER5.CLOUD/T/…),
    an EAN/GTIN, a GS1 DataMatrix (GTIN and serial), a manufacturer's QR
    text, a serial number, nfc:<uid>. Returns its status (article, unit, box,
    blank, unknown) and the id; a product's barcode names the article."""
    return _get("/api/codes/resolve?" + urllib.parse.urlencode({"code": code}))


@server.tool()
def link_article(product: str, item: str, article: str, quantity: int = 1) -> dict:
    """Say which article of the stock a block or module is built from, and
    how many one product needs. An empty article removes the link."""
    return act(f"Build {item} from {article or 'nothing'}" + (f" × {quantity}" if article and quantity != 1 else ""),
               "POST", _p(product) + f"/items/{_q(item)}/article", {"article": article, "quantity": int(quantity or 1)})


@server.tool()
def import_bom(product: str, file: str = "", text: str = "") -> dict:
    """Import a bill of materials written as Markdown (## Hardware / ##
    Software, ### groups, a table in each) into a product: a file the person
    gave you (its inbox id) or the text. Shows what it would make, then asks
    the person to confirm: blocks with their supply (there, in hand, to buy),
    software modules with versions, and the articles the stock lacks, which
    are proposed in the cloud for an admin to accept."""
    web.ensure_server()
    pv = web.call("POST", _p(product) + "/import/bom", {"inbox": file} if file else {"text": text})
    if not isinstance(pv, dict) or "blocks" not in pv:
        return pv
    n = len(pv["blocks"]) + len(pv["modules"])
    new = sum(1 for b in pv["blocks"] + pv["tools"] if b.get("propose") and b.get("include_article", True))
    return act(f"Import the BOM: {len(pv['blocks'])} blocks, {len(pv['modules'])} modules"
               + (f", propose {new} articles" if new else "") + (f"; skip {len(pv['skipped'])} already there" if pv["skipped"] else ""),
               "POST", _p(product) + "/import/bom/apply", {"preview": pv}) if n or new else {"nothing": "every row is in the model already", **pv}


@server.tool()
def canvas(product: str) -> dict:
    """The hardware canvas: each block's place and pins (ids <block>.<n>,
    names like GPIO17, roles), and the wires between pins."""
    return _get(_p(product) + "/canvas")


@server.tool()
def fritzing_search(q: str) -> list:
    """Parts of the Fritzing parts library whose name has every word: [{path,
    name, folder}], core parts first. The library is fetched from GitHub."""
    return _get("/api/fritzing/search?" + urllib.parse.urlencode({"q": q}))


@server.tool()
def fritzing_part(path: str) -> dict:
    """One Fritzing part: its title, authors, licence and pins [{n, name, role}]."""
    return _get("/api/fritzing/part?" + urllib.parse.urlencode({"path": path}))


@server.tool()
def fritzing_use(product: str, block: str, path: str) -> dict:
    """Propose that a block takes a Fritzing part: its pins replace the
    block's (a wired pin must stay) and the canvas shows its picture."""
    return act(f"Give {block} the Fritzing part {path}", "POST", _p(product) + "/canvas/fritzing",
               {"block": block, "path": path})


@server.tool()
def place(product: str, block: str, x: int, y: int) -> dict:
    """Propose where a block sits on the hardware canvas (x right, y down).
    Placed for the first time, it gets the pins of its part from the parts
    library. The person confirms it."""
    return act(f"Place {block} at {int(x)}, {int(y)}", "POST", _p(product) + "/canvas/place",
               {"block": block, "x": int(x), "y": int(y)})


@server.tool()
def wire(product: str, pin_from: str, pin_to: str, color: str = "", interface: str = "") -> dict:
    """Propose a wire between two pins (ids from canvas()), in a colour,
    optionally as part of an interface. The person confirms it."""
    return act(f"Wire {pin_from} → {pin_to}" + (f" ({color})" if color else ""), "POST", _p(product) + "/wires",
               {"from": pin_from, "to": pin_to, "color": color, "interface": interface})


@server.tool()
def set_pins(product: str, block: str, pins: List[Dict]) -> dict:
    """Propose a block's pins: [{n, name, role}] with role power, ground,
    signal, audio, video or data. A wired pin cannot be dropped."""
    return act(f"Set {len(pins)} pins on {block}", "POST", _p(product) + "/canvas/pins", {"block": block, "pins": pins})


@server.tool()
def bom(product: str) -> dict:
    """The product's parts list: per article, what the model needs, what the
    product reserved and used, how many are free, and what is missing."""
    return _get(_p(product) + "/bom")


def _parts(step: str, product: str, article: str, qty: int, unit: str, note: str) -> dict:
    what = f"unit {unit}" if unit else f"{int(qty or 1)} × {article}"
    return act(f"{step.capitalize()} {what} for {product}", "POST", _p(product) + f"/parts/{step}",
               _clean(article=article, qty=None if unit else int(qty or 1), unit=unit, note=note))


@server.tool()
def reserve_parts(product: str, article: str, qty: int = 1, unit: str = "", note: str = "") -> dict:
    """Put parts aside for the product: a quantity of a bulk article, or one
    unit of a serialised article. The cloud refuses what is not free."""
    return _parts("reserve", product, article, qty, unit, note)


@server.tool()
def release_parts(product: str, article: str, qty: int = 1, unit: str = "", note: str = "") -> dict:
    """Give a reservation back to the stock."""
    return _parts("release", product, article, qty, unit, note)


@server.tool()
def return_parts(product: str, article: str, qty: int = 1, unit: str = "", note: str = "") -> dict:
    """Give back parts the product used (taken out of a prototype)."""
    return _parts("return", product, article, qty, unit, note)


# ------------------------------------------------------------- history ----

@server.tool()
def revisions(product: str) -> list:
    """Every saved state of the model, newest first: number, when, who,
    through what (page, chat, mcp), a one-line summary, and its tags. A
    frozen tag is a baseline (e.g. "Prototype A")."""
    return _get(_p(product) + "/revisions")


@server.tool()
def diff(product: str, from_revision: str, to_revision: str = "latest") -> dict:
    """What changed between two revisions (numbers or tag names): nodes
    added, removed, and changed with each property's values before and after."""
    return _get(_p(product) + "/diff?" + urllib.parse.urlencode({"from": from_revision, "to": to_revision}))


@server.tool()
def tag_revision(product: str, revision: int, name: str, frozen: bool = False) -> dict:
    """Name a revision. frozen=True makes it a baseline that never moves:
    only for a state the person calls a prototype or a release."""
    return act(f"Tag revision {revision} of {product} \"{name}\"" + (" (baseline)" if frozen else ""), "POST",
               _p(product) + f"/revisions/{int(revision)}/tag", {"name": name, "frozen": bool(frozen)})


@server.tool()
def restore(product: str, revision: int) -> dict:
    """Make the model what it was at a revision. History is kept: this adds
    a new revision with that content."""
    return act(f"Restore {product} to revision {revision}", "POST",
               _p(product) + f"/revisions/{int(revision)}/restore", {})


def main() -> int:
    ap = argparse.ArgumentParser(prog="maker-5-edge-mcp",
                                 description=__doc__.strip().splitlines()[0])
    ap.add_argument("--url", help="web server base URL (overrides --port)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-autostart", action="store_true",
                    help="fail rather than start a web server that is not running")
    args = ap.parse_args()
    web.configure(port=args.port, url=args.url, autostart=not args.no_autostart)
    web.log(f"serving MCP over stdio, web server at {web.BASE}")
    web.start_heartbeat()
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
