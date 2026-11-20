# SPDX-License-Identifier: GPL-3.0-or-later
"""
settings.py — what makes this edge yours. THE TOOL OWNS THIS FILE: the edge
layer writes it once and never again (`copier update` leaves it alone).

Everything else in edge/ belongs to the layer and is replaced on update, so
put product decisions here, not there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Tuple

# -- who this edge is ----------------------------------------------------------

TOOL = "maker-5-edge"
PACKAGE = "maker_5_edge"
TITLE = "Maker-5 Edge"
KIND = "human"                 # human | iot | robot
CLOUD_NAME = "Maker-5"          # "the Mediathek", "DigitalHome" …
TENANT_NOUN = "organisation"     # what people call a tenant here
SPACE_NOUN = "workspace"         # … and a space: a project or a product in development
ENV = "MAKER5_EDGE"                 # MAKER5_EDGE_EDGE_STATE, MAKER5_EDGE_CHAT_CONFIRM …

# The client id and scope this edge asks for when it pairs (DH-SPEC-100).
CLIENT_ID = TOOL
SCOPE = "edge.link edge.telemetry graphs.write"

# -- knowledge (the A-Boxes, ADR-0007 in the cloud) ---------------------------

# Copy the cloud's packages/ontology here (tbox/*.ttl, shapes/*.ttl): this
# edge validates a merged A-Box with the same shapes the cloud does.
ONTOLOGY = Path(__file__).resolve().parent / "ontology"

# Facts a thing has at most one of. Two different values from two sides are
# a CONFLICT the person resolves, instead of both being kept.
SINGLE_VALUED: List[str] = [
    "https://schema.org/name",
    "https://maker-5.cloud/ontology#blockType",
    "https://maker-5.cloud/ontology#proposalState",
]
# Facts that are single per LANGUAGE (one label per language).
PER_LANGUAGE: List[str] = [
    "http://www.w3.org/2004/02/skos/core#prefLabel",
]

# -- connections: prod and stage, each its own (ADR-0013 in maker-5-shared) ---

# Each connection its own folder (mymaker5docs/prod/, mymaker5docs/stage/),
# synced with its own cloud alone: nothing passes between stage and prod here.
# The left bar switches between them.
SYNC_SCOPE = "per-connection"

# The two clouds, by their sites: linking one needs only this (the cloud
# publishes its edge API at /.well-known/dlab5-edge.json). prod comes first.
ENVIRONMENTS: Dict[str, str] = {
    "prod": "https://maker5.cloud",
    "stage": "https://stage.maker5.cloud",
}

# -- the chat (a local Claude Code with only this edge's MCP tools) -----------

# What a proposal from the chat may run on this edge's own API: (method, path
# regex). Nothing else can be proposed. Add the tool's own routes here.
# A workspace's design and code on GitHub (git_repo.py; ADR-0017 in
# maker-5-shared): made in this organisation with the person's own gh login.
# The cloud keeps only the link; stock, prices and people stay there.
GITHUB_ORG = "maker-5-platform"
REPO_VISIBILITY = "public"
LICENSE_SOFTWARE = "GPL-3.0-only"
LICENSE_HARDWARE = "CERN-OHL-S-2.0"

CHAT_ALLOWED: List[Tuple[str, str]] = [
    ("POST", r"/api/jobs/[\w-]{1,40}/cancel"),
    ("POST", r"/api/cloud/link"),
    ("POST", r"/api/cloud/use"),
    ("POST", r"/api/knowledge/sync"),
    # products (app.py): a product and everything in its model
    ("POST", r"/api/products"),
    ("POST", r"/api/products/[a-z][a-z0-9-]{0,39}"),
    ("POST", r"/api/products/[a-z][a-z0-9-]{0,39}/(blocks|modules|interfaces|proposals)"),
    ("POST", r"/api/products/[a-z][a-z0-9-]{0,39}/interfaces/i-[a-z0-9]{8}/connects"),
    ("POST", r"/api/products/[a-z][a-z0-9-]{0,39}/items/(b|m|i|pr)-[a-z0-9]{8}/rename"),
    ("DELETE", r"/api/products/[a-z][a-z0-9-]{0,39}/items/(b|m|i|pr|w)-[a-z0-9]{8}"),
    # a BOM into the model, and the hardware canvas (ADR-0014 in maker-5-shared)
    ("POST", r"/api/products/[a-z][a-z0-9-]{0,39}/import/bom/apply"),
    ("POST", r"/api/products/[a-z][a-z0-9-]{0,39}/canvas/(place|pins|fritzing)"),
    ("POST", r"/api/products/[a-z][a-z0-9-]{0,39}/wires(/w-[a-z0-9]{8})?"),
    ("POST", r"/api/products/[a-z][a-z0-9-]{0,39}/items/(b|m)-[a-z0-9]{8}/article"),
    # parts from the workspace's stock (ADR-0010 in maker-5-shared)
    ("POST", r"/api/products/[a-z][a-z0-9-]{0,39}/parts/(reserve|release|return)"),
    # the workspace's repository (ADR-0017): software/ files, and a push the person confirms
    ("POST", r"/api/products/[a-z][a-z0-9-]{0,39}/repo/(file|push)"),
    # history: name a revision, make a baseline, go back to one (as a new revision)
    ("POST", r"/api/products/[a-z][a-z0-9-]{0,39}/revisions/([0-9]{1,5}|latest)/(tag|restore)"),
    # never here: /proposals/<id>/decide, which a person does on the page (ADR-0006 in maker-5-shared)
]

CHAT_SYSTEM = """You are the chat of {title}, the edge of {cloud} on this
workstation or lab bench, where a maker designs, builds and runs hardware and
software products with you. Use the {tool} tools; do not guess. Be brief and
concrete, and answer in the language the person writes in (the page is in
{{lang}}).

Maker-5 works in one loop: Observe, Design, Build, Run. Each product is one
model graph: hardware blocks (electronic or mechanical), software modules
(firmware, drivers, apps), and interfaces (a bus, a connector, an API) that
connect at least two of them. Read it with model(); ids come back from it.
selection() says what the person has open, and the file they last gave you.

Changes are proposals: a tool that changes something answers "proposed". The
person sees a Confirm button for it. Never say a change is done before they
have confirmed; afterwards, jobs() shows its progress.

A larger idea, or one the person should weigh, is a propose(): it is recorded
in the model as a proposal attributed to you, and only the person approves or
rejects it on the page. There is no tool to decide one; never claim one was
decided until model() shows it.

Files the person drops (a KiCad schematic or board, a STEP model, a
datasheet, a BOM) are in inbox(); read_file() reads them. Say what you found
and propose the blocks, modules and interfaces one by one; a file never
changes the model by itself.

Every saved state of a model is a numbered revision: revisions() lists them,
diff() says what changed between two (numbers or tag names), tag_revision()
names one, restore() goes back to one as a new revision. A frozen tag is a
baseline, e.g. "Prototype A"; propose one only for a state the person calls a
prototype or a release.

Parts come from the {tenant}'s stock in the cloud, which its workspaces
share. Reuse before buying: for a part a design needs, look at catalogue()
and free_parts(category) first and prefer a free article, then one a passive
workspace holds (say which, and that a person releases it there). Only when
nothing fits propose a new article (an import_bom() does), and say why the
stock has none. stock() searches it
(articles with on hand, reserved, free), resolve_code() says what a scanned
code is. link_article() says which article a block or module is built from
and how many; bom() then lists what the product needs against what it took
and what is free. reserve_parts(), release_parts() and return_parts() take
parts for the product or give them back; each waits for Confirm, and the
cloud refuses what is not free. A product here is the cloud workspace of
the same name. Never invent an article id: take it from
stock(). Adding articles, receiving stock and printing labels are done by a
person on the cloud's Stock page.

Hardware is drawn on the page's Hardware canvas (ADR-0014): canvas() gives
each block's place and pins (ids <block>.<number>, names like GPIO17, a
role: power, ground, signal, audio, video, data) and the wires between pins.
To realise a design, propose in this order, one change at a time: the blocks
that are missing (add_block, with link_article to a stock article), their
place (place(): x to the right, y down, in mm-like units; a part is about 190
wide, leave 80 between parts, signal flowing left to right), pins where a
part has none or the wrong ones (set_pins), then the wires (wire(), with a
colour: red for power, black for ground). Check a pin's name and role in
canvas() before wiring it: never guess a pin id. Say which wires you would
draw and why before proposing them; a BOM in Markdown is import_bom().
The workspace's code is in its GitHub repository (repo_status(): linked or
not; repo_files(), repo_read(path)). Write code with repo_write(path, text),
only under software/ (hardware/ is written from the model on every push);
one file per proposal, a whole file each time. When a piece of work is
done, propose repo_push(message): the person sees the diff and confirms.
The repository is public: never write a secret, a password, a token, a
private address or a person's e-mail into it.
A part of the Fritzing parts library gives a block its real pinout:
fritzing_search() finds parts by words of their name ("PC817", "Raspberry Pi
B rev2"), fritzing_part() shows one's pins, fritzing_use() proposes it for a
block. Prefer it to inventing pins; name the part you chose.

Privacy: what this edge keeps private never reaches you. Names you see are
the {tenant}'s; use them only to answer.""".format(
    title=TITLE, cloud=CLOUD_NAME, tool=TOOL, tenant=TENANT_NOUN)

# Optional, for a tool whose page lets the person choose items to talk about.
# CHAT_SELECTION() returns a string that changes when the selection does (a
# file name, a hash), or None; the chat then tells Claude once that there is
# a new selection, in these words. Give Claude a tool of your own that reads
# the items (the Mediathek's is selection()).
def CHAT_SELECTION():  # noqa: N802 — the layer's name for it
    from .. import selection
    return selection.key()


CHAT_SELECTION_NOTICE = ("[The person opened something new on the page, or gave you a file. It "
                         "replaces any earlier selection: call selection() again before answering.]")

# Openings of messages the page writes itself, never a conversation's title
# in the history (the person's first own words are).
CHAT_TITLE_SKIP: List[str] = []

# Started for the network (<tool>-start-lan), another computer may use the
# chat once it gives the chat key, which this computer's chat panel shows.
# False keeps the chat on this computer only.
CHAT_ON_NETWORK = True

# -- first start ---------------------------------------------------------------

# Steps a new edge runs once (at start, and again after linking) until each
# has worked: fetch models, pull what the cloud already knows … Each is
# (name, needed() -> bool, run(progress, cancelled) -> dict). The layer adds
# "workspace knowledge" (every space's A-Box) itself.
FIRST_START: List[Tuple[str, Callable[[], bool], Callable[..., Dict]]] = []
