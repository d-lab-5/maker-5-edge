# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
inbox.py — files given to the chat (ADR-0005 in maker-5-shared).

A person drops a file on the page or on the chat: a datasheet as PDF, a
KiCad schematic or board, a STEP export, a BOM as CSV or a workbook, a Turtle
model. The chat reads it and decides what it is for, then proposes the
blocks, modules and interfaces it finds tool by tool like anything else. A
file is one more input to the model; it never changes the model by itself.

Each file is kept privately (0700, files 0600): with a product open, in that
product's folder, <data>/<product>/files/<id>/ (ADR-0003); with none open, in
<data>/inbox/<id>/. Each has meta.json: name, size, the kind detected from
its content (not its name alone), and a short note of what was found. Text
is extracted on demand:

  csv, txt, json, xml, ttl, kicad, step   as text
  pdf                                     pdftotext (poppler), when installed
  xlsx                                    read with the standard library (zip + XML)

Nothing here sends a file anywhere. The pattern is digitalhome-pro-edge's.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from . import selection as sel
from .edge import knowledge as kn

MAX_BYTES = 64 * 1024 * 1024
TEXT_LIMIT = 20000               # characters returned per read
KINDS = ("kicad", "step", "csv", "xlsx", "turtle", "json", "pdf", "text", "unknown")
_ID = re.compile(r"^in-[0-9a-f]{10}$")


class NotFound(LookupError):
    pass


def _root() -> Path:
    d = kn.data_dir() / "inbox"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def _open_product() -> str:
    """The product the page has open, when it has a folder here."""
    from .products import MODEL, RESERVED
    p = sel.get().get("product", "")
    if p and p not in RESERVED and "/" not in p and not p.startswith(".") \
            and (kn.data_dir() / p / MODEL).is_file():
        return p
    return ""


def _product_root(product: str) -> Path:
    d = kn.data_dir() / product / "files"
    d.mkdir(exist_ok=True, mode=0o700)
    return d


def _roots() -> List[Path]:
    """Where files are looked for: the shared inbox, then every product's files."""
    return [_root()] + sorted(kn.data_dir().glob("*/files"))


def _dir(fid: str) -> Path:
    if not _ID.match(fid or ""):
        raise ValueError(f"not a file id: {fid}")
    for root in _roots():
        if (root / fid).is_dir():
            return root / fid
    raise NotFound(f"no file {fid} in the inbox")


def _write(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


# ------------------------------------------------------------- reading ----

def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _pdf_text(path: Path) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise ValueError("reading a PDF needs pdftotext (poppler-utils) on this computer")
    got = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(path), "-"],
                         capture_output=True, timeout=60, check=False)
    if got.returncode != 0:
        raise ValueError("pdftotext could not read this PDF")
    return got.stdout.decode("utf-8", "replace")


def _col(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + ord(ch.upper()) - 64
    return n - 1


def xlsx_rows(data: bytes, limit: int = 100000) -> List[List[str]]:
    """The first sheet of a workbook, as rows of strings."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        shared: List[str] = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        sheets = sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        if not sheets:
            return []
        rows = []
        for r in ET.fromstring(z.read(sheets[0])).iter(f"{{{ns['m']}}}row"):
            row: List[str] = []
            for c in r.findall("m:c", ns):
                v = c.find("m:v", ns)
                if c.get("t") == "inlineStr":
                    text = "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
                elif v is None:
                    text = ""
                elif c.get("t") == "s":
                    text = shared[int(v.text)]
                else:
                    text = v.text or ""
                i = _col(c.get("r", ""))
                if i >= 0:
                    row.extend([""] * (i - len(row)))
                row.append(text)
            rows.append(row)
            if len(rows) >= limit:
                break
        return rows


def _xlsx_csv(data: bytes) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    for row in xlsx_rows(data):
        w.writerow(row)
    return out.getvalue().encode()


def extract(path: Path, kind: str) -> str:
    data = path.read_bytes()
    if kind == "pdf":
        return _pdf_text(path)
    if kind == "xlsx":
        return _xlsx_csv(data).decode()
    return _decode(data)


# ----------------------------------------------------------- detecting ----

def _n(k: int, one: str, many: str) -> str:
    return f"{k} {one if k == 1 else many}"


_KICAD = re.compile(r"^\((kicad_sch|kicad_pcb|kicad_symbol_lib|footprint|module)\b")
_KICAD_WHAT = {"kicad_sch": "a KiCad schematic", "kicad_pcb": "a KiCad board",
               "kicad_symbol_lib": "a KiCad symbol library", "footprint": "a KiCad footprint",
               "module": "a KiCad footprint"}


def detect(name: str, data: bytes, path: Optional[Path] = None) -> Dict:
    """What a file is, from its content: {kind, note}."""
    head = data[:4096]
    low = name.lower()
    if head.startswith(b"%PDF"):
        try:
            text = _pdf_text(path) if path else ""
        except (ValueError, subprocess.TimeoutExpired):
            return {"kind": "pdf", "note": "a PDF; its text could not be read here"}
        return {"kind": "pdf", "note": f"a PDF, {len(text.split())} words of text"}
    if head.startswith(b"PK") and (low.endswith(".xlsx") or b"xl/" in data[:2000]):
        try:
            rows = xlsx_rows(data, limit=2000)
        except (zipfile.BadZipFile, ET.ParseError, KeyError):
            return {"kind": "unknown", "note": "a zip archive, not a readable workbook"}
        return {"kind": "xlsx", "note": f"a workbook, {_n(len(rows), 'row', 'rows')}"}
    text = _decode(head)
    stripped = text.lstrip()
    m = _KICAD.match(stripped)
    if m:
        whole = _decode(data)
        symbols = len(re.findall(r"\(symbol\s+\(lib_id\b", whole))
        footprints = len(re.findall(r"\(footprint\s+\"", whole))
        found = ", ".join(x for x in (
            _n(symbols, "symbol", "symbols") if symbols else "",
            _n(footprints, "footprint", "footprints") if footprints else "") if x)
        return {"kind": "kicad", "note": _KICAD_WHAT[m.group(1)] + (f", {found}" if found else "")}
    if stripped.startswith("ISO-10303-21"):
        product = re.search(r"FILE_NAME\s*\(\s*'([^']*)'", _decode(data[:20000]))
        return {"kind": "step", "note": "a STEP model (CAD)" + (f", {product.group(1)}" if product and product.group(1) else "")}
    if low.endswith((".ttl", ".turtle")) or re.match(r"(@prefix|PREFIX)\s", stripped):
        return {"kind": "turtle", "note": "Turtle: a model graph"}
    if stripped[:1] in "{[":
        try:
            json.loads(_decode(data))
            return {"kind": "json", "note": "JSON"}
        except ValueError:
            pass
    if b"\x00" in head:
        return {"kind": "unknown", "note": "a binary file this edge cannot read"}
    if low.endswith((".csv", ".tsv")) or (re.search(r"[;,\t]", stripped.split("\n", 1)[0] or "")
                                          and stripped.count("\n") >= 1 and not stripped.startswith("<")):
        rows = [r for r in _decode(data).splitlines() if r.strip()]
        return {"kind": "csv", "note": f"a table, {_n(len(rows), 'row', 'rows')}"}
    if stripped.startswith("<"):
        return {"kind": "text", "note": "XML"}
    return {"kind": "text", "note": f"text, {len(text.split())} words at the start"}


# ------------------------------------------------------------- the box ----

def add(name: str, data: bytes) -> Dict:
    if not data:
        raise ValueError("the file is empty")
    if len(data) > MAX_BYTES:
        raise ValueError(f"files up to {MAX_BYTES // (1024 * 1024)} MB")
    name = Path(name or "file").name[:200] or "file"
    fid = "in-" + secrets.token_hex(5)
    product = _open_product()
    d = (_product_root(product) if product else _root()) / fid
    d.mkdir(mode=0o700)
    raw = d / "file"
    _write(raw, data)
    found = detect(name, data, raw)
    meta = {"id": fid, "name": name, "size": len(data), "added": int(time.time()),
            "product": product, **found}
    _write(d / "meta.json", json.dumps(meta, ensure_ascii=False).encode())
    return meta


def files() -> List[Dict]:
    """The open product's files and the shared inbox's."""
    product = _open_product()
    roots = [_root()] + ([kn.data_dir() / product / "files"] if product else [])
    out = []
    for root in roots:
        for d in root.iterdir() if root.is_dir() else []:
            m = d / "meta.json"
            if _ID.match(d.name) and m.exists():
                out.append({"product": "", **json.loads(m.read_text())})
    return sorted(out, key=lambda m: -m["added"])


def meta(fid: str) -> Dict:
    return json.loads((_dir(fid) / "meta.json").read_text())


def read(fid: str, offset: int = 0, limit: int = TEXT_LIMIT) -> Dict:
    """A slice of the file's text, so a long file is read in parts."""
    m = meta(fid)
    if m["kind"] == "unknown":
        raise ValueError(f"{m['name']}: {m['note']}")
    text = extract(_dir(fid) / "file", m["kind"])
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), TEXT_LIMIT))
    return {**m, "offset": offset, "length": len(text), "text": text[offset:offset + limit],
            "more": offset + limit < len(text)}


def remove(fid: str) -> Dict:
    shutil.rmtree(_dir(fid))
    return {"removed": fid}
