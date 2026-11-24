# maker-5-edge

**v0.1.0** · GPL-3.0 · [releases](https://github.com/d-lab-5/maker-5-edge/releases)

Local workstation and lab-bench edge daemon for **Maker-5**. It syncs Git
repos, CAD/PCB artifacts and hardware telemetry with the cloud.

It runs on your workstation or lab bench and pairs securely with the Maker-5
cloud ([maker-5-cloud](https://github.com/d-lab-5/maker-5-cloud), at
maker-5.cloud) using the device flow: the edge shows a code, and an admin of
your workspace approves it. It then watches local Git repositories, CAD/PCB
schematics, firmware builds and connected test hardware, and syncs what it
learns with the cloud's semantic graph in both directions. The page and the
MCP server answer only to this machine, so your local environment is never
exposed.

Knowledge is one RDF A-Box per product, checked with the same Maker-5 SHACL
shapes as the cloud (`maker_5_edge/edge/ontology/`, copied from
`maker-5-cloud/packages/ontology`; CC BY 4.0). Decisions and the roadmap are in
[maker-5-shared](https://github.com/d-lab-5/maker-5-shared), published at
https://docs.dlab5.net/d-lab-5/maker-5/.

Made from [python-tool-template](https://github.com/ERP-LAB-5/python-tool-template)
and the [template-dlab5-edge](https://github.com/d-lab-5/template-dlab5-edge)
layer. `docs/edge.md` says which files belong to which.

## Use it

```bash
./run.sh                 # http://127.0.0.1:8773 (run.cmd or run.ps1 on Windows)
./run.sh --port 9000     # somewhere else
./run.sh --stop          # shut it down
```

The first run creates `.venv` and installs the requirements. Any other option
goes straight to the app, e.g. `./run.sh --no-update-check`.

The header has **About**, which shows the installed version, checks github.com
for a newer one and links to the repository. On a pip or pipx install it can
**update itself**: it runs pip against the latest tag, shows what pip said, and
restarts into the new version only if that worked. From a source checkout it
tells you to `git pull` instead. The check is one request for a text file. It
sends nothing about you, is cached for six hours, and is skipped silently when
there is no network. `--no-update-check` turns it off. **Restart** and **Stop**
are only accepted from this machine.

**Import BOM** on a workspace reads a bill of materials written in Markdown
(`## Hardware` / `## Software`, `###` groups, a table in each) into its model:
blocks with their supply (there, in hand, to buy), software modules with
their versions, and, after a preview, the articles the stock lacks, proposed
in the cloud for an admin to accept on Materials. The **Hardware** tab is the
canvas: place the blocks, which get the pins of their part
(`maker_5_edge/parts/library.json`, with a board's USB, video, audio,
Ethernet and power ports), and click two pins to wire them. **Image** beside
a block gives it a picture (ADR-0021):
- **Fritzing:** a part of the Fritzing parts library, with its real pins,
  fetched from GitHub when you pick it and kept in `mymaker5docs/fritzing/`.
  The library is CC BY-SA 3.0, so it is never part of this repository, and
  the canvas credits it.
- **Wokwi:** breadboard pictures of common boards and parts from the Wokwi
  elements (MIT), shipped in `maker_5_edge/parts/wokwi/` and made with
  `scripts/wokwi-snapshot.mjs`, so nothing is fetched.
- **From its pins:** a plain drawing of the block's own pins.
- **By the agent:** the chat draws it as SVG with the `part-image` skill
  (`maker_5_edge/skill/part-image.md`); each pin is checked before it is kept.

A library part brings its pins; a board's ports stay. **Pictures** in the canvas bar hides them all.

Wires find their own way around the parts (`static/route.js`, and
`maker_5_edge/route.py` for `hardware/wiring.svg`, the same rules): on a grid,
few bends, apart from each other, and a half-circle hop where two cross.
Click a part to select it: it is lit in the list and its wires stand out.
Right-click a part, or its name in the list, for its menu: picture, pins,
notes, rename, remove its wires, or take it off the canvas (its pins and wires stay).

A pin sits on the left, the right or the bottom of its part (`m5:pinSide`), in
the place it is listed there (`m5:pinPlace`): the pins window has a box for each
side. A pin with no side follows the old rule (a long header odd left and even
right). A board's ports go to the bottom. A block's notes are its
`schema:description`: rest on a part for a second to see them with its pins,
and *Save and ask the agent* writes them into the chat as a request. Pins,
wires and positions are in the model, so they sync and the chat can read and
propose them (ADR-0014 in maker-5-shared).

The **Code** tab keeps a workspace's design and code in its own GitHub
repository, open source (ADR-0017 in maker-5-shared). **Link to GitHub**
makes `maker-5-platform/<workspace>` with your own login (the GitHub CLI,
`gh auth login`) and clones it into the workspace's folder. `software/` is
yours and the agent's to write; `hardware/` (the model without stock links,
the wiring as SVG, a netlist and a parts list) is written from the model on
every push. **Review and push** shows everything a push publishes and
refuses tokens, keys and e-mail addresses. Stock, places, prices, people and
chats stay in the cloud, which keeps only the link. The chat finds free and
idle parts with `catalogue()` and `free_parts()` before it proposes buying
any (ADR-0018, ADR-0019).

If someone changes `hardware/model.ttl` on GitHub, **Pull** notices and the
Code tab offers to bring those statements into the model, or to keep the
model; no push goes out before. `software/generated/pins.py` is the pin map,
written from the wiring: a class per board and a constant per wired GPIO, for
the code to import. Under **Boards** you set where the software runs (a host
over SSH with your own key, or this computer); **Deploy** copies `software/`
there, runs the restart command, shows the log and records the commit on the
board's block (ADR-0020). Hosts and users stay on this edge.

**Intake** is what was scanned at the shelf (ADR-0022): on the phone, Scan →
Intake, the shelf or box first, then label after label (M5 for maker parts,
DHC for smart-home devices), with a photo or a note. **Describe with the
agent** asks the chat to look at the photos with the `intake` skill
(`maker_5_edge/skill/intake.md`), reuse articles of the stock and suggest
each item: a device, a box of parts or loose parts. You open an item, change
what is wrong and **Check in**: the cloud makes the article, the unit or the
box, binds the label and closes the item in one step. The agent cannot
check in or drop an item; the edge refuses both from it.

Your work lives in `mymaker5docs/`, which git ignores and which follows the
working directory: a folder per cloud, `mymaker5docs/prod/` and
`mymaker5docs/stage/`, each synced with its own cloud alone (ADR-0013 in
maker-5-shared). The left bar switches between them; one not linked yet
offers to link it, with only the cloud's site (maker5.cloud, or
stage.maker5.cloud). Workspaces are made in the cloud and appear here, each
with its own folder. An older `mydocs/` becomes `mymaker5docs/prod/` on the
first start.

## Installing without a clone

**A release tarball**: needs neither git nor pip.

```bash
curl -L https://github.com/d-lab-5/maker-5-edge/archive/refs/tags/v0.1.0.tar.gz | tar xz
cd maker-5-edge-0.1.0
./run.sh
```

**Or install it**, with no source tree to keep:

```bash
pipx install git+https://github.com/d-lab-5/maker-5-edge@v0.1.0
maker-5-edge-web                 # the page
maker-5-edge summarise note.json # the command line
maker-5-edge-mcp                 # the MCP server, for agents
maker-5-edge-skill --install     # the agent skill, into ~/.claude/skills
```

Every command has a `python3 -m` twin that needs nothing on PATH:

| command | the same thing as a module |
|---|---|
| `maker-5-edge` | `python3 -m maker_5_edge.engine` |
| `maker-5-edge-web` | `python3 -m maker_5_edge.app` |
| `maker-5-edge-mcp` | `python3 -m maker_5_edge.mcp_server` |
| `maker-5-edge-skill` | `python3 -m maker_5_edge.core.skill_install` |

## Updating an install

**From the page:** *About → Update and restart*.

**From the command line**, name the new tag. `--upgrade` alone will not move a
pinned tag:

```bash
pip install --upgrade git+https://github.com/d-lab-5/maker-5-edge@v0.1.0
pipx install --force git+https://github.com/d-lab-5/maker-5-edge@v0.1.0
```

If you copied the skill with `--install`, refresh it afterwards:
`maker-5-edge-skill --install --force`.

## For agents

**As a Claude Code plugin** you get the skill and the MCP server in one step:

```
/plugin marketplace add ERP-LAB-5/python-tool-template
/plugin install maker-5-edge@erp-lab-5
```

On first use the plugin installs the version it pins into its own venv under
`~/.local/share/dlab5-tools/maker-5-edge/` and runs the MCP server from there.
It needs `python3` on PATH.

**From a checkout**, `.mcp.json` registers the MCP server for this repository.

**For any other agent, press Agent** in the header. It writes the JSON for
Claude Code, VS Code (GitHub Copilot), Cursor or Claude Desktop with the real
paths already filled in — each client keeps the same server under a slightly
different key, in a different file — and either copies it or writes the file
for you, keeping any other servers already registered there. The panel also
shows whether an agent is currently working on this server.

MCP itself is the standard, so the server is written once and every client
speaks to it unchanged; only that small config file differs between them. What
no page can do is *start* one: a stdio server is spawned by its client, lives on
that client's pipes and dies with it, so there is nothing to start or stop from
the browser.

The MCP server starts the web server if it is not running, and both work on the
same files, so an agent's save shows up for the person at the browser.

[**The skill**](maker_5_edge/skill/SKILL.md) ships inside the package.
`maker-5-edge-skill --install` copies it to `~/.claude/skills` for agents
that don't use the plugin, and `--install --for vscode` writes it as
`.github/copilot-instructions.md` instead (`--for cursor` for Cursor's rules
folder). A checkout has identical copies in
`.claude/skills/maker-5-edge/` and `plugin/skills/maker-5-edge/`. They are
real files rather than symlinks, because symlinks don't survive a clone on
Windows. `maker-5-edge-skill --check` confirms they are in step, and
`--sync` rewrites them from the packaged copy.

## Development

```bash
./test.sh                # the suite, with ROS 2's PYTHONPATH kept out of it
```

This repository was generated from
[ERP-LAB-5/python-tool-template](https://github.com/ERP-LAB-5/python-tool-template).
`maker_5_edge/core/`, the launchers, `test.sh`, `tests/test_core.py`,
`scripts/release.py` and `plugin/bin/launch_mcp.py` belong to the template. Take its fixes with
`copier update` rather than editing them here. Everything else belongs to this tool.

Releasing:

```bash
python3 scripts/release.py 0.2.0 -F notes.txt --push
```

It bumps `VERSION` everywhere it appears, updates this README's pins, syncs the
skill copies, commits, tags, pushes, and creates the GitHub release.

## Licence

GPL-3.0-or-later, except `maker_5_edge/edge/ontology/`, which is CC BY 4.0. © 2026 D-LAB-5 — *Twin. Experiment. Automate.*
See [LICENSE](LICENSE).
