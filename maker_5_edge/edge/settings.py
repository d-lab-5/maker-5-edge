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

# -- the chat (a local Claude Code with only this edge's MCP tools) -----------

# What a proposal from the chat may run on this edge's own API: (method, path
# regex). Nothing else can be proposed. Add the tool's own routes here.
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
    ("DELETE", r"/api/products/[a-z][a-z0-9-]{0,39}/items/(b|m|i|pr)-[a-z0-9]{8}"),
    ("POST", r"/api/products/[a-z][a-z0-9-]{0,39}/items/(b|m)-[a-z0-9]{8}/article"),
    # parts from the workspace's stock (ADR-0010 in maker-5-shared)
    ("POST", r"/api/products/[a-z][a-z0-9-]{0,39}/parts/(reserve|release|return)"),
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
share: stock() searches it
(articles with on hand, reserved, free), resolve_code() says what a scanned
code is. link_article() says which article a block or module is built from
and how many; bom() then lists what the product needs against what it took
and what is free. reserve_parts(), release_parts() and return_parts() take
parts for the product or give them back; each waits for Confirm, and the
cloud refuses what is not free. A product here is the cloud workspace of
the same name. Never invent an article id: take it from
stock(). Adding articles, receiving stock and printing labels are done by a
person on the cloud's Stock page.

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
