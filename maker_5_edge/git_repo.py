# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
git_repo.py — a workspace's design and code in its own GitHub repository
(ADR-0017 in maker-5-shared).

The design is open, the business stays in the cloud. The repository holds
the software and the hardware as it is designed; the cloud keeps the stock,
places, prices, people, proposals and chats, and only a link to the
repository. The edge works with the person's own GitHub login (`gh` and
`git` on this computer), never with a token of ours.

    status(products, p)            linked?, the changes, ahead/behind
    link(products, p, existing)    make <org>/<workspace> on GitHub, or link
                                   one, clone it beside the model, scaffold it
    prepare(products, p)           write hardware/ and NOTICE from the model
    diff(products, p)              what a push would publish
    push(products, p, message)     prepare, check, commit, push, tell the cloud
    pull(products, p)              take what others pushed (fast-forward only)
    files / read / write           the repository's files; the agent writes
                                   only under software/

The repository, in <workspace folder>/repo/:

    software/              the code, written by the person and the agent
    software/generated/    pins.py and pins.json: the boards' wired pins and
                           their GPIO numbers, from the model (pin_map)
    hardware/model.ttl     the model without stock links, quantities,
                           proposals or who decided what
    hardware/wiring.svg    the hardware canvas
    hardware/images/       each block's picture as SVG (Fritzing, Wokwi, drawn)
    hardware/netlist.md    every wire, pin to pin
    hardware/bom.md        the parts by name and count; no stock, no prices
    NOTICE                 the Fritzing parts used, with their authors
    README.md, LICENSE (software), LICENSE-hardware, .gitignore

Before every push a guard reads what is staged and refuses tokens, keys,
private-key blocks, e-mail addresses (other than example ones), the edge's
cloud link and the inbox. A finding stops the push; nothing is sent.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from rdflib import RDF, Graph, URIRef
from rdflib.namespace import PROV

from .edge import cloud
from .edge import settings

ORG = getattr(settings, "GITHUB_ORG", "maker-5-platform")
VISIBILITY = getattr(settings, "REPO_VISIBILITY", "public")
LICENSE_SOFTWARE = getattr(settings, "LICENSE_SOFTWARE", "GPL-3.0-only")
LICENSE_HARDWARE = getattr(settings, "LICENSE_HARDWARE", "CERN-OHL-S-2.0")
WRITABLE = "software/"
MAX_FILE = 300_000
MAX_DIFF = 200_000
NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
FULL = re.compile(r"^(?:https://github\.com/)?([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$")


class RepoError(RuntimeError):
    """git or gh refused, or the repository is not in a state for this."""


# ------------------------------------------------------------ running ----

def _env() -> Dict[str, str]:
    env = dict(os.environ)
    env.update(GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", LC_ALL="C")
    return env


def _run(args: List[str], cwd: Optional[Path] = None, timeout: int = 120) -> str:
    try:
        r = subprocess.run(args, cwd=cwd, env=_env(), capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except FileNotFoundError as e:
        raise RepoError(f"{args[0]} is not installed on this computer") from e
    except subprocess.TimeoutExpired as e:
        raise RepoError(f"{args[0]} {args[1] if len(args) > 1 else ''} took too long") from e
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        raise RepoError(" ".join(msg[-3:])[:400] or f"{args[0]} failed")
    return r.stdout


def git(repo: Path, *args: str, timeout: int = 120) -> str:
    return _run(["git", "-C", str(repo), *args], timeout=timeout)


def gh(*args: str, timeout: int = 120) -> str:
    """The person's GitHub CLI (tests replace this)."""
    return _run(["gh", *args], timeout=timeout)


def clone_url(full: str) -> str:
    """Where a repository is cloned from (tests point this at a local bare repository)."""
    return f"https://github.com/{full}.git"


def web_url(full: str) -> str:
    return f"https://github.com/{full}"


def github_login() -> Dict[str, Any]:
    """Whether gh is here and signed in, and as whom."""
    if shutil.which("gh") is None and gh is _real_gh:
        return {"installed": False, "login": ""}
    try:
        return {"installed": True, "login": gh("api", "user", "--jq", ".login").strip()}
    except RepoError:
        return {"installed": True, "login": ""}


_real_gh = gh


# ------------------------------------------------------------ where ----

def repo_dir(products: Any, p: str) -> Path:
    return products.kb.folder(p) / "repo"


def _linked(products: Any, p: str) -> Path:
    d = repo_dir(products, p)
    if not (d / ".git").exists():
        raise RepoError("this workspace is not linked to GitHub yet: Link to GitHub")
    return d


def _full_of(repo: Path) -> str:
    """"owner/name" for a GitHub remote, else the remote as it is."""
    url = git(repo, "config", "--get", "remote.origin.url").strip()
    m = FULL.match(url) if url.startswith("https://github.com/") else None
    return f"{m.group(1)}/{m.group(2)}" if m else url


def _branch(repo: Path) -> str:
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()


# ------------------------------------------------------------ status ----

def status(products: Any, p: str) -> Dict[str, Any]:
    d = repo_dir(products, p)
    if not (d / ".git").exists():
        return {"linked": False, "org": ORG, "suggested": f"{ORG}/{cloud.space_slug(_title(products, p))}",
                "github": github_login(), "visibility": VISIBILITY}
    changes = [{"status": line[:2].strip() or "?", "path": line[3:]}
               for line in git(d, "status", "--porcelain=v1", "-uall").splitlines() if line.strip()]
    ahead = behind = 0
    try:
        counts = git(d, "rev-list", "--left-right", "--count", "HEAD...@{upstream}").split()
        ahead, behind = int(counts[0]), int(counts[1])
    except (RepoError, IndexError, ValueError):
        pass
    try:
        last = git(d, "log", "-1", "--format=%H%x09%cI%x09%s").strip().split("\t")
    except RepoError:
        last = []
    full = _full_of(d)
    github = "://" not in full and not full.startswith("/") and ":" not in full
    return {"linked": True, "incoming": (d / ".git" / INCOMING).exists(),
            "repo": full, "url": web_url(full) if github else full,
            "branch": _branch(d), "changes": changes, "ahead": ahead, "behind": behind,
            "last": {"commit": last[0], "at": last[1], "subject": last[2]} if len(last) == 3 else None}


def _title(products: Any, p: str) -> str:
    return products.model(p)["product"]["title"]


# ------------------------------------------------------------ link ----

def link(products: Any, p: str, existing: str = "", visibility: str = "", profile: Optional[str] = None) -> Dict[str, Any]:
    """Make <org>/<workspace> on GitHub (or take an existing repository),
    clone it beside the model and give it its layout. Nothing is pushed yet:
    the first push is the person's, after they have seen it."""
    d = repo_dir(products, p)
    if (d / ".git").exists():
        raise RepoError("this workspace is linked already")
    if d.exists() and any(d.iterdir()):
        raise RepoError(f"{d.name}/ beside the model is not empty")
    title = _title(products, p)
    if existing:
        m = FULL.match(existing.strip())
        if not m:
            raise ValueError("a repository is <owner>/<name> or its https://github.com/… address")
        full = f"{m.group(1)}/{m.group(2)}"
        gh("repo", "view", full, "--json", "name")                      # it exists and this login sees it
    else:
        name = cloud.space_slug(title)
        if not NAME.match(name):
            raise ValueError("the workspace's name gives no repository name")
        full = f"{ORG}/{name}"
        try:
            gh("repo", "view", full, "--json", "name")
            raise RepoError(f"{full} exists already: link it instead, or rename the workspace")
        except RepoError as e:
            if "exists already" in str(e):
                raise
        vis = visibility or VISIBILITY
        if vis not in ("public", "private"):
            raise ValueError("a repository is public or private")
        gh("repo", "create", full, f"--{vis}", "--license", "gpl-3.0",
           "--description", f"{title}: hardware and software, designed with Maker-5")
    d.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--quiet", clone_url(full), str(d)], timeout=300)
    # pushing goes through the person's gh login, for this repository only
    if shutil.which("gh"):
        git(d, "config", "--local", "credential.https://github.com.helper", "")
        git(d, "config", "--local", "--add", "credential.https://github.com.helper", f"!{shutil.which('gh')} auth git-credential")
    _scaffold(d, title)
    imported = None
    if existing:
        # An existing repository holds its design: an empty workspace takes it
        # from there first, else prepare() would write the empty model over it.
        from . import migrate
        there = migrate.sources(products, p)
        if there["empty"] and (there.get("repo") or {}).get("blocks"):
            imported = migrate.copy(products, p, {"repo": True})
    prepare(products, p)
    out = status(products, p)
    if imported:
        out["imported"] = imported
    return out


OLD_SITE_LINK = "[Maker-5](https://maker-5.cloud)"

GITIGNORE = """# never published (ADR-0017)
cloud.json
*.pem
*.key
.env
inbox/
__pycache__/
"""


def _scaffold(d: Path, title: str) -> None:
    (d / "software").mkdir(exist_ok=True)
    keep = d / "software" / "README.md"
    if not keep.exists():
        keep.write_text(f"# {title}: software\n\nThe code of {title}: what runs on its boards, and around them.\n",
                        encoding="utf-8")
    readme = d / "README.md"
    if readme.exists() and OLD_SITE_LINK in readme.read_text(encoding="utf-8"):     # the site's old address
        readme.write_text(readme.read_text(encoding="utf-8").replace(OLD_SITE_LINK, "[Maker-5](https://maker5.cloud)"), encoding="utf-8")
    if not (d / "README.md").exists() or (d / "README.md").read_text(encoding="utf-8").strip().startswith(f"# {d.name}"):
        (d / "README.md").write_text(f"""# {title}

Designed with [Maker-5](https://maker5.cloud): open hardware and software.

- `software/`: the code.
- `hardware/`: the design, written by the Maker-5 edge from its model, so
  it is changed there and not here: `model.ttl` (blocks, modules, pins and
  wires, in the Maker-5 ontology), `wiring.svg`, `netlist.md` and `bom.md`.

The software is licensed under {LICENSE_SOFTWARE} (`LICENSE`), the hardware
under {LICENSE_HARDWARE} (`LICENSE-hardware`). Parts drawn from the Fritzing
parts library keep their own licence; see `NOTICE`.
""", encoding="utf-8")
    if not (d / "LICENSE-hardware").exists():
        (d / "LICENSE-hardware").write_text(f"""SPDX-License-Identifier: {LICENSE_HARDWARE}

The hardware design in hardware/ is licensed under the CERN Open Hardware
Licence Version 2 - Strongly Reciprocal. The licence text:
https://ohwr.org/cern_ohl_s_v2.txt
""", encoding="utf-8")
    if not (d / ".gitignore").exists():
        (d / ".gitignore").write_text(GITIGNORE, encoding="utf-8")


# ------------------------------------------------------------ the public design ----

M5 = "https://maker-5.cloud/ontology#"
PUBLIC_TYPES = ("Product", "Block", "SoftwareModule", "Interface", "Pin", "Wire")
DROP = {M5 + "usesArticle", M5 + "quantity"}


def public_model(g: Graph) -> Graph:
    """What of a model is open: the product, its blocks, modules, interfaces,
    pins and wires, without stock links, quantities or provenance; no
    proposals, decisions or people."""
    keep = {s for t in PUBLIC_TYPES for s in g.subjects(RDF.type, URIRef(M5 + t))}
    out = Graph()
    for prefix, ns in g.namespaces():
        out.bind(prefix, ns)
    for s, pr, o in g:
        if s in keep and str(pr) not in DROP and not str(pr).startswith(str(PROV)):
            if isinstance(o, URIRef) and str(o).startswith("https://maker-5.cloud/id/") and o not in keep:
                continue                                   # a link to something not published
            out.add((s, pr, o))
    return out


W, HEAD, ROW, PAD, IMG, LABEL = 190, 28, 17, 8, 70, 58   # LABEL: room for the bottom pins' names
ROLE_COLOR = {"power": "red", "ground": "black", "signal": "blue", "audio": "purple", "video": "orange", "data": "green"}


def _has_image(b: Dict[str, Any]) -> bool:
    return bool(b.get("fritzing")) or (b.get("image") or {}).get("kind", "none") != "none"


def _layout(b: Dict[str, Any]) -> Dict[str, Any]:
    """The canvas's own layout (static/canvas.js layout()), so the picture matches the page."""
    sides = pin_sides(b["pins"])
    left, right, bottom = (sides[k] for k in ("left", "right", "bottom"))
    pic = _has_image(b)
    w = max(W + IMG if pic else W, PAD * 2 + len(bottom) * ROW)
    at = {x["id"]: (0, HEAD + PAD + i * ROW + ROW / 2, -1) for i, x in enumerate(left)}
    at.update({x["id"]: (w, HEAD + PAD + i * ROW + ROW / 2, 1) for i, x in enumerate(right)})
    body = HEAD + PAD * 2 + max(len(left), len(right), 3 if pic else 1) * ROW
    h = body + (LABEL if bottom else 0)
    x0 = (w - (len(bottom) - 1) * ROW) / 2
    at.update({x["id"]: (x0 + i * ROW, h, 0) for i, x in enumerate(bottom)})
    return {"at": at, "w": w, "h": h, "body": body, "bottom": bool(bottom)}


def pin_sides(pins: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Each pin on its side, in the order the person listed them (its place,
    else its number; static/canvas.js sides()). A pin with no side: a long
    header's odd pins left and even right, as on the board; otherwise the
    first half of them left."""
    header = len(pins) >= 20
    loose = [x for x in pins if x.get("side") not in ("left", "right", "bottom")]
    out: Dict[str, List[Dict[str, Any]]] = {"left": [], "right": [], "bottom": []}
    for x in sorted(pins, key=lambda x: (x.get("place") or 0, x["n"])):
        side = x.get("side")
        if side not in out:
            side = "left" if (x["n"] % 2 == 1 if header else loose.index(x) < (len(loose) + 1) // 2) else "right"
        out[side].append(x)
    return out


def _n(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _x(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def wiring_svg(canvas: Dict[str, Any], title: str) -> str:
    placed = [b for b in canvas["blocks"] if b.get("x") is not None]
    geo = {b["id"]: {"b": b, **_layout(b)} for b in placed}
    if not placed:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="60"><text x="10" y="35">{_x(title)}: no parts placed yet</text></svg>\n'
    x0 = min(b["x"] for b in placed) - 60
    y0 = min(b["y"] for b in placed) - 60
    x1 = max(b["x"] + geo[b["id"]]["w"] for b in placed) + 60
    y1 = max(b["y"] + geo[b["id"]]["h"] for b in placed) + 60
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {y0} {x1 - x0} {y1 - y0}" width="{x1 - x0}" height="{y1 - y0}" '
           f'font-family="sans-serif" font-size="11">',
           f'<title>{_x(title)}: wiring</title>', f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="#fff"/>']

    def point(pin: str, block: str):
        g = geo.get(block)
        if not g or pin not in g["at"]:
            return None
        ax, ay, side = g["at"][pin]
        return g["b"]["x"] + ax, g["b"]["y"] + ay, side
    from . import route as rt
    wired = [(w, [point(e["pin"], e["block"]) for e in w["ends"]]) for w in canvas["wires"]]
    wired = [(w, e) for w, e in wired if e[0] and e[1]]
    routes = rt.route([tuple(e) for _, e in wired], [(g["b"]["x"], g["b"]["y"], g["w"], g["h"], g["bottom"]) for g in geo.values()])
    for i, (w, _) in enumerate(wired):
        role = next((x.get("role") for x in geo[w["ends"][0]["block"]]["b"]["pins"] if x["id"] == w["ends"][0]["pin"]), "")
        color = w.get("color") or ROLE_COLOR.get(role or "", "gray")
        d = rt.path(routes[i], [r for j, r in enumerate(routes) if j != i])
        out.append(f'<path d="{d}" fill="none" stroke="{_x(color)}" stroke-width="2.5" stroke-linejoin="round"/>')
    for g in geo.values():
        b = g["b"]
        dash = ' stroke-dasharray="6 4"' if b.get("supply") == "to-buy" else ""
        out.append(f'<g transform="translate({b["x"]},{b["y"]})">'
                   f'<rect width="{g["w"]}" height="{g["h"]}" rx="6" fill="#f6f7f9" stroke="#556"{dash}/>'
                   f'<rect width="{g["w"]}" height="{HEAD}" rx="6" fill="#dde3ea" stroke="#556"/>'
                   f'<text x="10" y="18" font-weight="bold">{_x(b["name"][:40])}</text>')
        for x in b["pins"]:
            ax, ay, side = g["at"][x["id"]]
            dot = f'<circle cx="{_n(ax)}" cy="{ay}" r="4" fill="{ROLE_COLOR.get(x.get("role") or "", "#888")}"/>'
            if side:
                out.append(dot + f'<text x="{ax - side * 9}" y="{ay + 4}" text-anchor="{"start" if side < 0 else "end"}">{_x(x["name"][:14])}</text>')
            else:                                           # a bottom pin's name reads up from it
                out.append(dot + f'<text x="{_n(ax + 4)}" y="{ay - 9}" transform="rotate(-90 {_n(ax + 4)} {ay - 9})">{_x(x["name"][:9])}</text>')
        out.append("</g>")
    out.append("</svg>\n")
    return "\n".join(out)


def netlist_md(canvas: Dict[str, Any], title: str) -> str:
    blocks = {b["id"]: b for b in canvas["blocks"]}

    def end(e):
        b = blocks.get(e["block"], {"name": e["block"], "pins": []})
        pin = next((x for x in b["pins"] if x["id"] == e["pin"]), {"name": e["pin"], "n": "?"})
        return f'{b["name"]} · {pin["name"]} ({pin["n"]})'
    rows = sorted((end(w["ends"][0]), end(w["ends"][1]), w.get("color") or "") for w in canvas["wires"])
    lines = [f"# {title}: netlist", "", "Every wire of the hardware canvas, pin to pin. Written by the Maker-5 edge.", ""]
    if not rows:
        return "\n".join(lines + ["No wires yet.", ""])
    lines += ["| From | To | Colour |", "|---|---|---|"] + [f"| {a} | {b} | {c} |" for a, b, c in rows]
    return "\n".join(lines) + "\n"


def bom_md(model: Dict[str, Any], title: str) -> str:
    lines = [f"# {title}: parts", "", "The parts of the design, by name and count. Where they come from and what",
             "they cost is not part of the design. Written by the Maker-5 edge.", ""]
    blocks = model["blocks"]
    if blocks:
        lines += ["## Hardware", "", "| Part | Kind | Count | To buy |", "|---|---|---|---|"]
        lines += [f'| {b["name"]} | {b.get("kind") or ""} | {b.get("quantity") or 1} | {"yes" if b.get("supply") == "to-buy" else ""} |'
                  for b in blocks]
        lines.append("")
    mods = model["modules"]
    if mods:
        lines += ["## Software", "", "| Module | Version | Runs on |", "|---|---|---|"]
        names = {b["id"]: b["name"] for b in blocks}
        lines += [f'| {x["name"]} | {x.get("version") or ""} | {names.get(x.get("runs_on") or "", "")} |' for x in mods]
        lines.append("")
    return "\n".join(lines)


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def notice(canvas: Dict[str, Any]) -> str:
    from . import fritzing as fz
    used = sorted({b["fritzing"] for b in canvas["blocks"] if b.get("fritzing")})
    lines = ["This repository's design was made with Maker-5.", ""]
    if used:
        lines += ["Parts and their pinouts come from the Fritzing parts library,",
                  "https://github.com/fritzing/fritzing-parts, licensed CC BY-SA 3.0:", ""]
        for path in used:
            try:
                p = fz.part(path)
                who = EMAIL.sub("", p.get("author") or "").strip(" ,;<>()") or "the Fritzing community"
                lines.append(f"- {p.get('title') or path} ({path}), by {who}")
            except Exception:  # noqa: BLE001 - a credit without its title is still a credit
                lines.append(f"- {path}")
        lines.append("")
    wk = sorted({b["image"]["ref"] for b in canvas["blocks"] if (b.get("image") or {}).get("kind") == "wokwi"})
    if wk:
        from . import wokwi
        c = wokwi.credit()
        lines += ["Breadboard pictures and pinouts of these parts come from the Wokwi elements,",
                  f"{c['source']}, {c['copyright']}, licensed {c['license']}:", ""]
        lines += [f"- {wokwi.part(n)['title']} ({n})" for n in wk] + [""]
    drawn = sorted(b["name"] for b in canvas["blocks"] if (b.get("image") or {}).get("kind") in ("drawn", "agent"))
    if drawn:
        lines += ["These parts' pictures were drawn for this design, from their pins or by its",
                  "agent, and are licensed with the hardware (CERN-OHL-S-2.0): " + ", ".join(drawn) + ".", ""]
    return "\n".join(lines)


# ------------------------------------------------------------ the pin map ----

GENERATED = "software/generated/"


def _const(text: str) -> str:
    c = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    return ("P_" + c if c[:1].isdigit() else c) or "PIN"


def _gpio(name: str) -> Optional[int]:
    """"GPIO17", "GPIO 17", "GPIO 17/TXD", "D4", "IO5" → 17, 17, 17, None, 5."""
    m = re.match(r"^\s*(?:GPIO|IO|BCM)\s*(\d{1,3})\b", name or "", re.I)
    return int(m.group(1)) if m else None


def pin_map(products: Any, p: str) -> Dict[str, Any]:
    """Per board that software runs on (else per wired block): its wired pins,
    where each goes, and the GPIO number the code uses."""
    model, canvas = products.model(p), products.canvas(p)
    blocks = {b["id"]: b for b in canvas["blocks"]}
    hosts = {m["runs_on"] for m in model["modules"] if m.get("runs_on")}
    wired = {e["block"] for w in canvas["wires"] for e in w["ends"]}
    boards = []
    for bid in sorted(hosts or wired, key=lambda i: blocks.get(i, {}).get("name", i).lower()):
        b = blocks.get(bid)
        if not b:
            continue
        seen: Dict[str, int] = {}
        pins = []
        for x in b["pins"]:
            far = [next((f"{blocks[e['block']]['name']} · {pin['name']}" for pin in blocks.get(e["block"], {"pins": []})["pins"]
                         if pin["id"] == e["pin"]), e["pin"])
                   for w in canvas["wires"] if any(e["pin"] == x["id"] for e in w["ends"])
                   for e in w["ends"] if e["pin"] != x["id"]]
            if not far:
                continue
            name = _const(far[0].replace(" · ", "_")) if _gpio(x["name"]) is not None else _const(x["name"])
            seen[name] = seen.get(name, 0) + 1
            pins.append({"n": x["n"], "name": x["name"], "role": x.get("role") or "", "gpio": _gpio(x["name"]),
                         "to": far, "const": name if seen[name] == 1 else f"{name}_{seen[name]}"})
        boards.append({"block": bid, "name": b["name"], "class": _const(b["name"]).title().replace("_", ""), "pins": pins,
                       "modules": [m["name"] for m in model["modules"] if m.get("runs_on") == bid]})
    return {"boards": boards}


def pins_py(pm: Dict[str, Any], title: str) -> str:
    out = [f'"""The pins of {title}, from its hardware model.', "",
           "GENERATED by the Maker-5 edge on every push: change the wiring on the",
           'Hardware canvas, not this file. A GPIO number is the one the code uses."""', ""]
    for b in pm["boards"]:
        out += ["", f"class {b['class'] or 'Board'}:", f'    """{b["name"]}{": " + ", ".join(b["modules"]) if b["modules"] else ""}."""']
        gp = [x for x in b["pins"] if x["gpio"] is not None]
        for x in gp:
            out.append(f"    {x['const']} = {x['gpio']}  # pin {x['n']} {x['name']} → {', '.join(x['to'])}{' (' + x['role'] + ')' if x['role'] else ''}")
        for x in [x for x in b["pins"] if x["gpio"] is None]:
            out.append(f"    # pin {x['n']} {x['name']} → {', '.join(x['to'])}{' (' + x['role'] + ')' if x['role'] else ''}")
        if not b["pins"]:
            out.append("    pass  # nothing wired yet")
    return "\n".join(out) + "\n"


# GPIO numbers as code writes them: Button(17), LED(pin=18), GPIO.setup(27, …), Pin(4)
USES = re.compile(r"\b(?:Button|LED|PWMLED|DigitalInputDevice|DigitalOutputDevice|OutputDevice|InputDevice|Buzzer|"
                  r"MotionSensor|Pin|setup|output|input|add_event_detect)\(\s*(?:pin\s*=\s*)?(\d{1,3})\b")


def pin_check(d: Path, pm: Dict[str, Any]) -> List[Dict[str, Any]]:
    """GPIO numbers the code uses that the wiring does not have: [{path, line, gpio}]."""
    known = {x["gpio"] for b in pm["boards"] for x in b["pins"] if x["gpio"] is not None}
    out = []
    for f in sorted((d / "software").rglob("*.py")):
        rel = f.relative_to(d).as_posix()
        if rel.startswith(GENERATED):
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in USES.finditer(line):
                if int(m.group(1)) not in known:
                    out.append({"path": rel, "line": i, "gpio": int(m.group(1))})
    return out[:50]


def block_image(products: Any, p: str, b: Dict[str, Any]) -> Optional[bytes]:
    """A block's picture as SVG bytes, whatever its source; None if it has none."""
    from . import drawing, wokwi
    from . import fritzing as fz
    kind = (b.get("image") or {}).get("kind", "none")
    try:
        if kind == "fritzing":
            return fz.image(b["image"]["ref"])
        if kind == "wokwi":
            return wokwi.image(b["image"]["ref"])
        if kind == "agent":
            return products.drawing(p, b["id"]).encode("utf-8")
        if kind == "drawn":
            return drawing.generated(b["name"], b["pins"]).encode("utf-8")
    except Exception:  # noqa: BLE001 - a library out of reach: the push goes on without the picture
        return None
    return None


def _images(products: Any, p: str, canvas: Dict[str, Any], folder: Path) -> None:
    """hardware/images/<block>.svg for each block with a picture (ADR-0021)."""
    if folder.exists():
        for f in folder.glob("*.svg"):
            f.unlink()
    for b in canvas["blocks"]:
        svg = block_image(products, p, b)
        if svg:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{b['id']}.svg").write_bytes(svg)


def prepare(products: Any, p: str) -> Dict[str, Any]:
    """Write hardware/ and NOTICE again from the model (they are the model's, not edited here)."""
    d = _linked(products, p)
    title = _title(products, p)
    g = products._exists(p)
    canvas = products.canvas(p)
    hw = d / "hardware"
    hw.mkdir(exist_ok=True)
    (hw / "model.ttl").write_text(public_model(g).serialize(format="turtle"), encoding="utf-8")
    (hw / "wiring.svg").write_text(wiring_svg(canvas, title), encoding="utf-8")
    (hw / "netlist.md").write_text(netlist_md(canvas, title), encoding="utf-8")
    (hw / "bom.md").write_text(bom_md(products.model(p), title), encoding="utf-8")
    (d / "NOTICE").write_text(notice(canvas), encoding="utf-8")
    _images(products, p, canvas, hw / "images")
    pm = pin_map(products, p)
    gen = d / GENERATED
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "pins.json").write_text(json.dumps(pm, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (gen / "pins.py").write_text(pins_py(pm, title), encoding="utf-8")
    (gen / "__init__.py").write_text("", encoding="utf-8")
    return status(products, p)


# ------------------------------------------------------------ the guard ----

SECRETS = (("an AWS access key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
           ("a GitHub token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
           ("an Anthropic or OpenAI key", re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{20,}\b")),
           ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
           ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
           ("a password or secret assignment", re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]")),
           ("a device token of the edge", re.compile(r"\bdt_[A-Za-z0-9_-]{20,}\b")))
FORBIDDEN = re.compile(r"(^|/)(cloud\.json|\.env|id_rsa[^/]*|[^/]*\.pem|[^/]*\.key)$|(^|/)inbox/")
ALLOWED_EMAIL = re.compile(r"@(example\.(org|com|net)|users\.noreply\.github\.com|noreply\.github\.com|anthropic\.com)$", re.I)


def guard(repo: Path) -> List[Dict[str, str]]:
    """What must not be published, in what is staged: [{path, what}]."""
    findings = []
    for path in [x for x in git(repo, "diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if x]:
        if FORBIDDEN.search(path):
            findings.append({"path": path, "what": "a file that is never published"})
            continue
        f = repo / path
        try:
            text = f.read_text(encoding="utf-8", errors="replace")[:2_000_000]
        except OSError:
            continue
        for what, rx in SECRETS:
            if rx.search(text):
                findings.append({"path": path, "what": what})
        mails = [m for m in EMAIL.findall(text) if not ALLOWED_EMAIL.search(m) and not path.startswith("LICENSE")]
        if mails:
            findings.append({"path": path, "what": f"an e-mail address ({len(mails)})"})
    return findings


# ------------------------------------------------------------ publish ----

def diff(products: Any, p: str) -> Dict[str, Any]:
    """Everything a push would publish, as a patch (staged, nothing committed)."""
    d = _linked(products, p)
    prepare(products, p)
    git(d, "add", "-A")
    patch = git(d, "diff", "--cached", "--stat") + "\n" + git(d, "diff", "--cached", "--no-color")
    return {"patch": patch[:MAX_DIFF], "cut": len(patch) > MAX_DIFF, "findings": guard(d),
            "pin_warnings": pin_check(d, pin_map(products, p)), **status(products, p)}


def push(products: Any, p: str, message: str, profile: Optional[str] = None) -> Dict[str, Any]:
    """Prepare, stage, check, commit and push; then tell the cloud where it is."""
    message = (message or "").strip()
    if not message:
        raise ValueError("a push needs a message: what changed, in a sentence")
    if len(message) > 2000:
        raise ValueError("that message is too long")
    d = _linked(products, p)
    if (d / ".git" / INCOMING).exists():
        raise RepoError("hardware/model.ttl was changed on GitHub: bring that into the model, or drop it, before you push")
    prepare(products, p)
    git(d, "add", "-A")
    found = guard(d)
    if found:
        git(d, "reset", "--quiet")
        raise RepoError("not pushed: " + "; ".join(f"{f['path']}: {f['what']}" for f in found[:5]))
    if git(d, "diff", "--cached", "--name-only").strip():
        git(d, "commit", "--quiet", "-m", message)
    try:
        git(d, "fetch", "--quiet", "origin", timeout=120)
        behind = int(git(d, "rev-list", "--count", "HEAD..@{upstream}").strip() or 0)
    except (RepoError, ValueError):
        behind = 0
    if behind:
        raise RepoError(f"GitHub has {behind} commit(s) this edge has not: Pull first, then push")
    git(d, "push", "--quiet", "origin", "HEAD", timeout=300)
    st = status(products, p)
    reported = _report(products, p, st, profile)
    return {**st, "reported": reported}


def _report(products: Any, p: str, st: Dict[str, Any], profile: Optional[str] = None) -> str:
    """The cloud keeps the link (edge/v1/repo); a push stands without it."""
    from . import materials
    if not st.get("linked") or not str(st.get("url", "")).startswith("https://github.com/"):
        return "not a GitHub repository"
    try:
        space = materials.product_space(products, p, profile)
        cloud.call("repo", {"name": space["id"], "url": st["url"], "branch": st["branch"],
                            "commit": (st.get("last") or {}).get("commit", "")}, profile)
        return "ok"
    except Exception as e:  # noqa: BLE001 - an offline cloud must not undo a push
        return str(e)[:200]


def pull(products: Any, p: str) -> Dict[str, Any]:
    """Take what others pushed (fast-forward only). If they changed
    hardware/model.ttl on GitHub, their change is kept aside as incoming:
    the model is not changed until the person brings it in, and no push
    goes out (it would overwrite theirs) until it is brought in or dropped."""
    d = _linked(products, p)
    old = git(d, "rev-parse", "HEAD").strip()
    git(d, "pull", "--quiet", "--ff-only", timeout=300)
    new = git(d, "rev-parse", "HEAD").strip()
    if old != new:
        _note_incoming(d, old, new)
    return status(products, p)


# ------------------------------------------------------------ changes made on GitHub ----

INCOMING = "maker5-incoming.json"            # inside .git/: never committed


def _model_at(d: Path, rev: str) -> Graph:
    g = Graph()
    try:
        g.parse(data=git(d, "show", f"{rev}:hardware/model.ttl"), format="turtle")
    except RepoError:
        pass                                  # not there in that commit
    except Exception as e:  # noqa: BLE001 - a broken file on GitHub is said, not thrown
        raise RepoError(f"hardware/model.ttl on GitHub is not readable Turtle: {e}") from e
    return g


def _nt(triples) -> str:
    g = Graph()
    for t in triples:
        g.add(t)
    return g.serialize(format="nt")


def _note_incoming(d: Path, old: str, new: str) -> None:
    if not git(d, "diff", "--name-only", old, new, "--", "hardware/model.ttl").strip():
        return
    before, after = _model_at(d, old), _model_at(d, new)
    added, removed = set(after) - set(before), set(before) - set(after)
    if not added and not removed:
        return
    f = d / ".git" / INCOMING
    have = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"added": "", "removed": "", "commits": []}
    commits = [dict(zip(("commit", "author", "subject"), line.split("\t", 2)))
               for line in git(d, "log", "--format=%H%x09%an%x09%s", f"{old}..{new}", "--", "hardware/model.ttl").splitlines() if line]
    prev_added, prev_removed = Graph(), Graph()
    if have["added"]:
        prev_added.parse(data=have["added"], format="nt")
    if have["removed"]:
        prev_removed.parse(data=have["removed"], format="nt")
    all_added = (set(prev_added) - removed) | added
    all_removed = (set(prev_removed) - added) | removed
    f.write_text(json.dumps({"added": _nt(all_added), "removed": _nt(all_removed),
                             "commits": have["commits"] + commits}), encoding="utf-8")


def _short(t) -> str:
    v = str(t)
    for base in ("https://maker-5.cloud/id/", M5, "https://schema.org/", "http://www.w3.org/1999/02/22-rdf-syntax-ns#"):
        if v.startswith(base):
            return v[len(base):]
    return v


def incoming(products: Any, p: str) -> Dict[str, Any]:
    """What others changed in hardware/model.ttl on GitHub, not yet in the model."""
    d = _linked(products, p)
    f = d / ".git" / INCOMING
    if not f.exists():
        return {"pending": False, "added": [], "removed": [], "commits": []}
    have = json.loads(f.read_text(encoding="utf-8"))
    show = lambda nt: sorted([_short(s), _short(pr), _short(o)] for s, pr, o in Graph().parse(data=nt, format="nt")) if nt else []  # noqa: E731
    return {"pending": True, "added": show(have["added"]), "removed": show(have["removed"]), "commits": have["commits"]}


def take_incoming(products: Any, p: str) -> Dict[str, Any]:
    """Bring the GitHub changes into the model, in one revision. Only the
    design is taken (things of the id space, no stock links or provenance);
    the model's shapes still decide, so a change they refuse is refused whole."""
    d = _linked(products, p)
    f = d / ".git" / INCOMING
    if not f.exists():
        raise RepoError("nothing came from GitHub to bring in")
    have = json.loads(f.read_text(encoding="utf-8"))
    ok = lambda t: str(t[0]).startswith("https://maker-5.cloud/id/") and str(t[1]) not in DROP and not str(t[1]).startswith(str(PROV))  # noqa: E731
    added = [t for t in Graph().parse(data=have["added"] or "", format="nt") if ok(t)]
    removed = [t for t in Graph().parse(data=have["removed"] or "", format="nt") if ok(t)]

    def apply(g: Graph) -> None:
        for t in removed:
            g.remove(t)
        for t in added:
            g.add(t)
    products._change(p, apply)
    f.unlink()
    prepare(products, p)
    return {"added": len(added), "removed": len(removed), **status(products, p)}


def drop_incoming(products: Any, p: str) -> Dict[str, Any]:
    """Keep the model as it is: the next push writes it over what came from GitHub."""
    d = _linked(products, p)
    (d / ".git" / INCOMING).unlink(missing_ok=True)
    return status(products, p)


# ------------------------------------------------------------ files ----

def _inside(d: Path, path: str) -> Path:
    path = (path or "").strip().lstrip("/")
    if not path or ".." in Path(path).parts or path.startswith(".git"):
        raise ValueError("a path inside the repository")
    f = (d / path).resolve()
    if d.resolve() not in f.parents:
        raise ValueError("a path inside the repository")
    return f


def files(products: Any, p: str) -> List[Dict[str, Any]]:
    d = _linked(products, p)
    tracked = set(git(d, "ls-files").splitlines())
    out = []
    for f in sorted(d.rglob("*")):
        rel = f.relative_to(d).as_posix()
        if f.is_file() and not rel.startswith(".git/"):
            out.append({"path": rel, "size": f.stat().st_size, "tracked": rel in tracked,
                        "writable": rel.startswith(WRITABLE) and not rel.startswith(GENERATED)})
    return out[:2000]


def read(products: Any, p: str, path: str) -> Dict[str, Any]:
    d = _linked(products, p)
    f = _inside(d, path)
    if not f.is_file():
        raise ValueError(f"no file {path}")
    if f.stat().st_size > MAX_FILE:
        raise ValueError(f"{path} is too large to show")
    return {"path": f.relative_to(d.resolve()).as_posix(), "text": f.read_text(encoding="utf-8", errors="replace")}


def write(products: Any, p: str, path: str, text: str) -> Dict[str, Any]:
    """A file under software/ (hardware/ is written from the model)."""
    d = _linked(products, p)
    f = _inside(d, path)
    rel = f.relative_to(d.resolve()).as_posix()
    if not rel.startswith(WRITABLE):
        raise ValueError(f"only files under {WRITABLE} are written here; hardware/ comes from the model")
    if rel.startswith(GENERATED):
        raise ValueError(f"{GENERATED} is written from the model on every push")
    if len((text or "").encode("utf-8")) > MAX_FILE:
        raise ValueError("that file is too large")
    if FORBIDDEN.search(rel):
        raise ValueError("that file is never published")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text or "", encoding="utf-8")
    return {"path": rel, "size": f.stat().st_size}
