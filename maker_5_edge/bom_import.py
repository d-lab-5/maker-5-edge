# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
bom_import.py — a bill of materials, written as Markdown, into a product's
model (ADR-0014 in maker-5-shared).

    preview(products, p, text)     what an import would make; writes nothing
    apply(products, p, preview)    makes it: articles proposed in the cloud,
                                   then blocks and modules in one revision

The Markdown is the kind people write anyway: `## Hardware` and `## Software`
sections, `###` groups under them, and a table in each group. The first
column names the part; the others (Notes, Purpose, Status, Version, Role)
become its description.

- A hardware row becomes a block. Its group says whether the part is
  already there, in hand, or still to buy (m5:supplyState). It is linked to
  the stock article of the same name; one that has none gets a proposed
  article, which an admin accepts on the site's Materials page.
- A row of tools ("tools, not parts") becomes no block, only an article.
- A software row becomes a module, with its version; under "On the Pi" it
  runs on the block whose name says Pi (m5:runsOn).
- A row whose block or module exists already (by name) is skipped, so an
  import can be run again after the BOM grows.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import materials
from .edge import cloud

MAX_ROWS = 200

# a group heading, by its words, to a block's supply
SUPPLY_WORDS = (("to-buy", ("to buy", "to build", "buy", "order")),
                ("in-hand", ("in hand", "set up", "have")),
                ("there", ("already", "kept", "existing", "there")))
# a part's name, by its words, to an article category (ADR-0019: "top/sub",
# the ontology's m5:ArticleCategories). The first match wins, so the more
# particular words come first: a sound card is audio, not storage.
CATEGORY_WORDS = (("tools/measuring", ("multimeter", "oscilloscope", "logic analyser", "logic analyzer")),
                  ("tools/soldering", ("soldering iron", "soldering station", "hot air")),
                  ("tools/hand", ("tools", "screwdriver", "pliers", "crimp")),
                  ("media/displays", (" tv ", "old tv", "monitor", "display", "lcd", "oled", "e-paper")),
                  ("media/audio", ("sound card", "audio", "speaker", "amplifier", "lm386", "microphone", " mic ", "buzzer")),
                  ("media/video", ("video", "hdmi", "composite")),
                  ("media/lights", ("led strip", "neopixel", " led ", "lamp")),
                  ("sensors/vision", ("camera",)),
                  ("sensors/buttons", ("button", "push switch", "switch", "door station", "doorbell", "door bell", "keypad")),
                  ("sensors/environment", ("temperature", "humidity", "bme280", "dht", "pressure sensor", "light sensor")),
                  ("sensors/motion", ("pir", "accelerometer", "gyro", "imu", "ultrasonic", "encoder")),
                  ("controllers/storage", ("sd card", "microsd", "ssd", "usb stick", "flash drive", " hdd")),
                  ("controllers/mcu", ("arduino", "esp32", "esp8266", "pico", "stm32", "attiny")),
                  ("controllers/sbc", ("raspberry", "pi ", "jetson", "board pc", "computer")),
                  ("controllers/phones", ("phone", "tablet")),
                  ("communication/networking", ("router", "ethernet switch", "wi-fi dongle", "wifi dongle", "network")),
                  ("power/converters", ("step-down", "step down", "buck", "boost", "converter", "regulator")),
                  ("power/supplies", ("power supply", "psu", "adapter", "charger plug")),
                  ("power/batteries", ("battery", "batteries", "18650", "lipo")),
                  ("components/semiconductors", ("optocoupler", "pc817", "transistor", "diode", "mosfet")),
                  ("actuators/relays", ("relay",)),
                  ("actuators/motors", ("motor",)),
                  ("actuators/locks", ("solenoid", "door opener", "strike", "lock")),
                  ("components/passives", ("resistor", "capacitor", "inductor", "potentiometer")),
                  ("components/prototyping", ("perfboard", "breadboard", "stripboard", "jumper", "dupont")),
                  ("cables/connectors", ("terminal", "connector", "header", "plug", "socket")),
                  ("cables/cables", ("cable", "lead", "ethernet")),
                  ("cables/wire", ("wire",)),
                  ("chassis/enclosures", ("enclosure", "case", "box", "housing")),
                  ("mechanical/mounting", ("din rail", "mount", "bracket", "standoff")),
                  ("mechanical/fasteners", ("screw", "nut", "bolt")),
                  ("consumables/solder", ("solder",)),
                  ("consumables/tape", ("tape", "glue")),
                  ("consumables/heat-shrink", ("heat shrink",)),
                  ("components/ics", (" ic ", "chip")))
MECHANICAL = ("chassis", "mechanical")
SERIAL = ("controllers/sbc", "controllers/mcu", "controllers/phones", "tools/measuring")


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _plain(text: str) -> str:
    """Markdown inline marks off: `code`, **bold**, *em*, [link](url)."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"[`*_]", "", text).replace('"', "").strip()


def parse(text: str) -> List[Dict[str, Any]]:
    """The rows of every table, each with its section, group and columns."""
    rows: List[Dict[str, Any]] = []
    section = group = ""
    header: Optional[List[str]] = None
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("## ") and not s.startswith("### "):
            section, group, header = _plain(s[3:]).lower(), "", None
        elif s.startswith("### "):
            group, header = _plain(s[4:]), None
        elif s.startswith("|"):
            cells = [_plain(c) for c in _cells(s)]
            if header is None:
                header = [c.lower() for c in cells]
            elif all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c):
                continue
            elif cells and cells[0]:
                rows.append({"section": section, "group": group,
                             "cols": dict(zip(header, cells)), "name": cells[0]})
        else:
            header = None if s == "" else header
        if len(rows) > MAX_ROWS:
            raise ValueError(f"at most {MAX_ROWS} rows in one import")
    return rows


def _words(text: str, table) -> str:
    """The first key whose words appear in text as whole words ("lock" is not in "block")."""
    t = text.lower()
    has = lambda w: re.search(rf"(?<![a-z0-9]){re.escape(w.strip())}(?![a-z0-9])", t)  # noqa: E731
    return next((k for k, words in table if any(has(w) for w in words)), "")


def _split_name(name: str) -> Dict[str, str]:
    """"Raspberry Pi 1 Model B (512 MB, no Wi-Fi)" → the name, and the brackets as a note."""
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*(.*)$", name)
    if not m or not m.group(1):
        return {"name": name[:120], "note": ""}
    rest = " ".join(x for x in (m.group(3),) if x)
    return {"name": f"{m.group(1)} {rest}".strip()[:120], "note": m.group(2)}


def _description(cols: Dict[str, str], skip: str) -> str:
    return "; ".join(f"{k.capitalize()}: {v}" for k, v in cols.items() if k != skip and v and k != "version")


def _host(group: str) -> str:
    """"On the Pi (door)" → "pi"; "On the phone" → "phone"."""
    m = re.match(r"^on (?:the )?(.+?)(?:\s*\(.*\))?$", group.strip(), re.I)
    return m.group(1).strip().lower() if m else ""


def preview(products: Any, p: str, text: str, profile: Optional[str] = None) -> Dict[str, Any]:
    """What an import of this BOM would make in product p. Writes nothing."""
    m = products.model(p)
    have = {x["name"].lower() for x in m["blocks"] + m["modules"]}
    try:
        stock = {a["name"].lower(): a for a in materials.stock("", "", profile)}
        stock_error = ""
    except cloud.CloudError as e:
        stock, stock_error = {}, str(e)
    blocks: List[Dict[str, Any]] = []
    modules: List[Dict[str, Any]] = []
    tools: List[Dict[str, Any]] = []
    skipped: List[str] = []
    for row in parse(text):
        first = next(iter(row["cols"]), "")
        if "software" in row["section"]:
            name = row["name"][:120]
            if name.lower() in have:
                skipped.append(name)
                continue
            modules.append({"name": name, "version": row["cols"].get("version", "")[:80],
                            "description": _description(row["cols"], first), "host": _host(row["group"]),
                            "include": True})
            continue
        n = _split_name(row["name"])
        note = "; ".join(x for x in (n["note"], _description(row["cols"], first)) if x)
        category = _words(row["name"], CATEGORY_WORDS) or "components"
        is_tool = category.startswith("tools") or "tools, not parts" in note.lower()
        article = stock.get(n["name"].lower())
        line = {"name": n["name"], "description": note[:1000],
                "article": {"id": article["id"], "name": article["name"]} if article else None,
                "propose": None if article else {"name": n["name"], "category": category if category.startswith("tools") or not is_tool else "tools",
                                                 "tracking": "serial" if category in SERIAL else "bulk",
                                                 "note": note[:500]},
                "include": True}
        if is_tool:
            tools.append(line)
            continue
        if n["name"].lower() in have:
            skipped.append(n["name"])
            continue
        supply = _words(row["group"], SUPPLY_WORDS)
        line.update(kind="mechanical" if category.split("/")[0] in MECHANICAL or category.startswith("components/prototyping")
                    else "electronic", supply=supply)
        # a part already there (kept from an old kit) is often not in stock: propose it only if it is to hand
        if supply == "there" and line["propose"]:
            line["include_article"] = False
        else:
            line["include_article"] = True
        blocks.append(line)
    hosts = {b["name"].lower(): b["name"] for b in blocks} | {x["name"].lower(): x["name"] for x in m["blocks"]}
    for mod in modules:
        h = mod.pop("host")
        mod["runs_on"] = next((v for k, v in hosts.items() if h and re.search(rf"\b{re.escape(h)}\b", k)), "")
    return {"product": p, "blocks": blocks, "modules": modules, "tools": tools, "skipped": skipped,
            "stock_error": stock_error}


def apply(products: Any, p: str, pv: Dict[str, Any], profile: Optional[str] = None) -> Dict[str, Any]:
    """Make what a (reviewed) preview says: the articles to propose first, in
    the cloud, then every block and module in one revision of the model."""
    from rdflib import RDF, Literal, URIRef

    from .products import BLOCK_KINDS, KINDS, M5, SCHEMA, ARTICLE_IRI, _iri, _mint

    blocks = [b for b in pv.get("blocks") or [] if b.get("include", True)]
    modules = [x for x in pv.get("modules") or [] if x.get("include", True)]
    tools = [t for t in pv.get("tools") or [] if t.get("include", True)]
    if len(blocks) + len(modules) + len(tools) > MAX_ROWS:
        raise ValueError(f"at most {MAX_ROWS} rows in one import")
    wanted = [b["propose"] for b in blocks if b.get("propose") and b.get("include_article", True)]
    wanted += [t["propose"] for t in tools if t.get("propose")]
    proposed: Dict[str, str] = {}
    propose_error = ""
    if wanted:
        try:
            for i in range(0, len(wanted), 50):
                got = materials.propose(wanted[i:i + 50], profile)
                proposed.update({a["name"].lower(): a["id"] for a in got})
        except cloud.CloudError as e:
            propose_error = str(e)
    made: Dict[str, List[str]] = {"blocks": [], "modules": []}

    def write(g) -> None:
        product = products._product(g)
        have = {str(g.value(n, SCHEMA.name) or "").lower() for c in (M5.Block, M5.SoftwareModule)
                for n in g.subjects(RDF.type, c)}
        ids: Dict[str, str] = {}
        for b in blocks:
            name = str(b.get("name") or "").strip()[:120]
            if not name or name.lower() in have:
                continue
            ident = _mint(KINDS["block"][1])
            node = _iri("block", ident)
            g.add((node, RDF.type, M5.Block))
            g.add((node, SCHEMA.name, Literal(name)))
            g.add((node, M5.partOf, product))
            if b.get("kind") in BLOCK_KINDS:
                g.add((node, M5.blockType, BLOCK_KINDS[b["kind"]]))
            products._describe(g, node, b.get("description") or "", b.get("supply") or "", None, None)
            art = (b.get("article") or {}).get("id") or proposed.get(name.lower(), "")
            if art:
                g.add((node, M5.usesArticle, URIRef(ARTICLE_IRI + art)))
            ids[name.lower()] = ident
            have.add(name.lower())
            made["blocks"].append(name)
        for x in modules:
            name = str(x.get("name") or "").strip()[:120]
            if not name or name.lower() in have:
                continue
            node = _iri("module", _mint(KINDS["module"][1]))
            g.add((node, RDF.type, M5.SoftwareModule))
            g.add((node, SCHEMA.name, Literal(name)))
            g.add((node, M5.partOf, product))
            host = str(x.get("runs_on") or "").lower()
            host_id = ids.get(host) or next((str(n).rsplit("/", 1)[-1] for n in g.subjects(RDF.type, M5.Block)
                                            if str(g.value(n, SCHEMA.name) or "").lower() == host), "") if host else ""
            products._describe(g, node, x.get("description") or "", None, x.get("version") or "", host_id or None)
            have.add(name.lower())
            made["modules"].append(name)

    products._change(p, write)
    return {"made": made, "proposed": sorted(proposed), "propose_error": propose_error}
