---
name: maker-5-edge
description: Maker-5 Edge, the bench edge of Maker-5 on a workstation or lab bench. Model a hardware and software product as blocks (electronic, mechanical), software modules and the interfaces between them, record proposals that a person approves on the page, read the files a person gives you (KiCad schematics and boards, STEP models, datasheets, BOMs), and work with every saved revision of a model, through the maker-5-edge MCP tools or the browser page. Use when someone asks to work with maker-5-edge or a Maker-5 product on this computer, to model a product's hardware and software, or to read a schematic or BOM into a product.
---

# Maker-5 Edge

<!--
  Keep three things true: the frontmatter name stays "maker-5-edge", every
  `maker-5-edge <command>` line names a subcommand that exists
  (tests/test_core.py checks), and after editing, `maker-5-edge-skill --sync`
  copies this file to .claude/skills and plugin/skills. The packaged copy in
  maker_5_edge/skill/ is the source.
-->

The edge of Maker-5 on this computer. It keeps the person's **products**, one
folder each in `mydocs/<product>/`, and links to the Maker-5 cloud, where a
product is a space of the person's workspace.

## What a product's model is

One graph of the Maker-5 ontology (`maker_5_edge/edge/ontology/`):

- **blocks**: hardware, `electronic` or `mechanical` (a board, an enclosure, a sensor);
- **software modules**: firmware, a driver, an app;
- **interfaces**: a bus, a connector, an API, connecting **at least two** blocks or modules;
- **proposals**: a change an agent suggests, attributed to it, waiting for a person.

The SHACL shapes check every save; a change that breaks them is refused with
their message (an interface with one end, a block of an unknown kind), and
nothing is written.

## Working through MCP

The `maker-5-edge` MCP server starts the web server if it is not running, so
you and the person at the browser work on the same files.

- Read: `selection()` (what the person has open, and the file they last gave
  you), `products()`, `model(product)`, `inbox()`, `read_file(file)`.
- Change: `new_product`, `set_product`, `add_block`, `add_module`,
  `add_interface(product, name, connects=[ids])`, `connect`, `rename`,
  `remove`. Ids come from `model()`. In the edge's own chat panel each change
  is a proposal the person confirms; elsewhere your client asks first.
- Suggest: `propose(product, title, concerns=[ids])`. Only the person approves
  or rejects a proposal, on the page; there is no tool for it.
- History: `revisions`, `diff(product, from, to)`, `tag_revision` (frozen = a
  baseline such as "Prototype A"), `restore` (adds a new revision).
- The edge layer adds `connections`, `knowledge`, `sync_knowledge`, `jobs`;
  `server_url()` gives the page to hand to a person.

## A block's picture

The libraries first (`fritzing_search`, `wokwi_search`), then a drawing from
evidence: the rules are in [part-image.md](part-image.md), which the
`image_skill()` tool returns. A drawing marks each of the block's pins once
with `data-pin`, and `image_draw` refuses one that does not.

## Files

A file the person drops (on the Files tab, or on the chat with 📎) is kept in
the open product's `files/` folder. Its kind comes from its content: `kicad`,
`step`, `csv`, `xlsx`, `turtle`, `json`, `pdf`, `text`. Read it in slices with
`read_file(file, offset, limit)`. Say what you found, then add what it shows
one change at a time; a file never changes the model by itself.

## Without MCP

The page is `./run.sh` (http://127.0.0.1:8773), or `maker-5-edge-web` when
installed: products on the left, the Model, Proposals, History and Files tabs,
the chat on the right.

## Judgement

- Never invent a part, a value or a connection a file or the person did not give.
- After a change, say what changed in the person's words, not in ids.
- Propose a baseline only for a state the person calls a prototype or a release.
