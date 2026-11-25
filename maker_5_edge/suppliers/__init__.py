# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
suppliers — a supplier's document into the stock (ADR-0024 in maker-5-shared,
after ADR-0023): an order confirmation, a shipping notice, an invoice or a
service report, as an e-mail (.eml), a PDF or pasted text.

    read(raw, name)          what the document is: the shop, its kind, number
                             and date, its lines, its attachments (name, type,
                             size, sha256); for a shop without a reader, its
                             text, for the agent to read
    preview(raw | file)      each line against the stock: the same article
                             (by the shop's number, the maker's part number or
                             the name), candidates that look alike, a line
                             expected already; and what to do with it:
                               expect  a new order line (ADR-0023)
                               link    the part is ours already: the shop's
                                       number and the documents go onto it
                               skip
                             writes nothing
    apply(preview)           does what the person kept: the expected lines,
                             the links, and every attachment uploaded once and
                             put onto the parts and lines it concerns

A reader per shop: Amazon (orders.parse, the HTML of its e-mails), ELV (the
table in the attached PDF). Any other shop: the agent reads the text and
fills the lines itself; that is how a new supplier works before it has a
reader.

What leaves this computer: the lines (title, the shop's number, quantity,
price), the document's number and date, and the attachments, which go to the
organisation's private storage in the cloud, onto the parts (the person chose
so: they carry the buyer's address and customer number, so they are never
published). The e-mail's own text is not kept anywhere.

The chat may PROPOSE apply (settings.CHAT_ALLOWED); the person's click runs it.
"""

from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import re
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import inbox as ib
from .. import materials, orders
from ..edge import cloud
from . import elv

MAX_BYTES = 25 * 1024 * 1024
MAX_LINES = 50
TEXT_LIMIT = 20000
DOC_KINDS = ("order", "shipment", "invoice", "service", "other")
ACTIONS = ("expect", "link", "skip")
# attachments worth keeping on a part; logos and inline pictures are not
KEEP_TYPES = ("application/pdf", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              "text/csv", "image/jpeg", "image/png")
MAX_ATTACHMENTS = 10
SIMILAR = 0.34                  # word overlap above which a name is a candidate
LIKELY = 0.6                    # ... and above which it is taken as the same part
_STOP = {"and", "und", "et", "the", "der", "die", "das", "de", "du", "la", "le", "les", "für", "fur", "for", "pour",
         "with", "mit", "avec", "of", "x", "pcs", "stück", "stk", "set", "pack", "ac", "dc", "von", "en", "à", "a"}


class SupplierError(ValueError):
    """The document can't be read or applied as asked: say why."""


# ---- reading -----------------------------------------------------------------

def _pdf_text(data: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix="m5-doc-") as d:
        p = Path(d) / "doc.pdf"
        p.write_bytes(data)
        try:
            return ib._pdf_text(p)
        except (ValueError, OSError):
            return ""


def _html_text(html: str) -> str:
    p = orders._Tokens()
    p.feed(html)
    p.close()
    return re.sub(r"[ \t]+", " ", "".join(t[1] for t in p.out if t[0] == "t"))


def _domain(sender: str) -> str:
    host = sender.rsplit("@", 1)[-1].lower().strip(">") if "@" in sender else ""
    parts = host.split(".")
    if len(parts) > 2 and parts[-2] in ("co", "com"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else ""


def _parts(raw: bytes, name: str) -> Dict[str, Any]:
    """{sender, subject, date, body, attachments: [{name, type, data}]} of an e-mail, a PDF or text."""
    if raw.startswith(b"%PDF"):
        return {"sender": "", "subject": name, "date": "", "body": "",
                "attachments": [{"name": Path(name or "document.pdf").name, "type": "application/pdf", "data": raw}]}
    head = raw[:4096].decode("utf-8", "replace")
    if not re.search(r"^(From|Subject|Date|Received|Return-Path|MIME-Version):", head, re.M | re.I):
        return {"sender": "", "subject": "", "date": "", "body": raw.decode("utf-8", "replace"), "attachments": []}
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    date = ""
    try:
        d = email.utils.parsedate_to_datetime(str(msg.get("Date") or ""))
        date = d.date().isoformat() if d else ""
    except (TypeError, ValueError):
        pass
    part = msg.get_body(preferencelist=("plain", "html"))
    html = msg.get_body(preferencelist=("html",))
    body = ""
    if part is not None:
        body = str(part.get_content())
        if part.get_content_type() == "text/html":
            body = _html_text(body)
    if html is not None and len(body.split()) < 20:          # a plain part that says nothing
        body = _html_text(str(html.get_content()))
    atts = []
    for p in msg.iter_attachments():
        fname = p.get_filename()
        ctype = p.get_content_type()
        data = p.get_payload(decode=True) or b""
        if not fname or not data or ctype not in KEEP_TYPES:
            continue
        if ctype.startswith("image/") and p.get("Content-ID"):  # a picture in the mail's text
            continue
        atts.append({"name": Path(fname).name[:160], "type": ctype, "data": data})
    return {"sender": email.utils.parseaddr(str(msg.get("From") or ""))[1], "subject": str(msg.get("Subject") or ""),
            "date": date, "body": body, "attachments": atts[:MAX_ATTACHMENTS]}


def _kind(subject: str, body: str) -> str:
    for text in (subject, body[:3000]):
        for k, rx in (("service", r"\bService\s*(Shipment|einsendung)|\bRMA\b|Reparatur|réparation|\brepair"),
                      ("invoice", r"\bRechnung\b|\bInvoice\b|\bFacture\b"),
                      ("shipment", r"versandt|verschickt|unterwegs|Expédié|expédié|\bshipped\b|dispatched|Lieferschein|delivery note|Versandbestätigung"),
                      ("order", r"Bestell|\bOrder\b|Commande|Auftragsbestätigung")):
            if re.search(rx, text, re.I):
                return k
    return "other"


def _read(raw: bytes, name: str = "") -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if not raw:
        raise SupplierError("the document is empty")
    if len(raw) > MAX_BYTES:
        raise SupplierError(f"documents up to {MAX_BYTES // (1024 * 1024)} MB")
    p = _parts(raw, name)
    blobs = p["attachments"]
    for a in blobs:
        a["sha256"] = hashlib.sha256(a["data"]).hexdigest()
        a["size"] = len(a["data"])
        a["text"] = _pdf_text(a["data"]) if a["type"] == "application/pdf" else ""
    texts = [a["text"] for a in blobs if a["text"]]
    everything = "\n".join([p["subject"], p["body"]] + texts)
    sender = _domain(p["sender"])
    amazon = orders.SHOP.search(sender) or (not sender and orders.SHOP.search(everything[:20000]))
    doc: Dict[str, Any] = {"supplier": None, "kind": _kind(p["subject"], everything), "ref": None,
                           "date": p["date"] or None, "subject": p["subject"][:200], "reader": "generic", "lines": []}
    if amazon:
        doc.update(supplier=amazon.group(1).lower(), reader="amazon")
        try:
            o = orders.parse(raw if p["sender"] else p["body"])
            doc.update(supplier=o["supplier"], ref=o["orderRef"], date=o["orderedAt"] or doc["date"], lines=o["lines"])
        except orders.OrderError:
            pass
    elif elv.mine(sender, everything):
        got = elv.read(texts + [p["body"]])
        doc.update(supplier=elv.SHOP, reader="elv", ref=got["ref"], date=got["date"] or doc["date"], lines=got["lines"],
                   kind=elv.kind(p["subject"], texts) or doc["kind"])
    else:
        doc["supplier"] = sender or None
    if not doc["lines"]:
        doc["text"] = everything[:TEXT_LIMIT]
        doc["note"] = ("no reader for this shop yet: read the text and give the lines yourself"
                       if doc["reader"] == "generic" else "the reader found no lines: read the text")
    doc["attachments"] = [{k: a[k] for k in ("name", "type", "size", "sha256")} for a in blobs]
    return doc, blobs


def read(raw: Any, name: str = "") -> Dict[str, Any]:
    """What a supplier's document is (see the module's doc); writes nothing."""
    return _read(raw.encode("utf-8") if isinstance(raw, str) else raw, name)[0]


# ---- matching ------------------------------------------------------------------

def _words(s: str) -> set:
    return {w for w in re.sub(r"[^\w]+", " ", (s or "").lower()).split() if len(w) > 1 and w not in _STOP}


def score(a: str, b: str) -> float:
    """How alike two names are: shared words over all words, the brand (first word) counting twice."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    first = lambda s: (re.sub(r"[^\w]+", " ", s.lower()).split() or [""])[0]
    bonus = 1 if first(a) and first(a) == first(b) else 0
    return round((len(wa & wb) + bonus) / (len(wa | wb) + bonus), 2)


def similar(line: Dict[str, Any], supplier: Optional[str], stock: List[Dict[str, Any]]) -> Tuple[Optional[Dict], List[Dict]]:
    """(the same article for sure, or None; up to three that look alike)."""
    sku = str(line.get("sku") or "").upper()
    if supplier and sku:
        ref = f"{supplier}:{sku}"
        for a in stock:
            if ref in (a.get("supplierRefs") or []):
                return {"id": a["id"], "name": a["name"], "by": "shop"}, []
    if sku and len(sku) >= 5:
        for a in stock:
            if str(a.get("mpn") or "").upper() == sku:
                return {"id": a["id"], "name": a["name"], "by": "mpn"}, []
    sure = orders._match({"sku": sku, "title": line.get("title", "")}, supplier or "", stock)
    if sure:
        return sure, []
    cands = sorted(({"id": a["id"], "name": a["name"], "score": score(line.get("title", ""), a.get("name", ""))}
                    for a in stock if a.get("name")), key=lambda c: -c["score"])
    return None, [c for c in cands if c["score"] >= SIMILAR][:3]


def _key(supplier: str, ref: str, line: Dict[str, Any]) -> str:
    title = " ".join(str(line.get("title") or "").split())[:200]
    sku = str(line.get("sku") or "").strip().upper()
    return f"{supplier}|{ref}|{sku or title.lower()}"


def _inbox_bytes(fid: str) -> Tuple[bytes, str]:
    m = ib.meta(fid)
    return (ib._dir(fid) / "file").read_bytes(), m.get("name", "")


def preview(raw: Any = None, name: str = "", file: str = "", profile: Optional[str] = None) -> Dict[str, Any]:
    """A document's lines against the stock and what is expected, each with a
    proposed action; writes nothing. From the inbox (file) or the bytes/text."""
    if file:
        raw, name = _inbox_bytes(file)
    if raw is None:
        raise SupplierError("give a file from the inbox, or the document itself")
    doc, _ = _read(raw.encode("utf-8") if isinstance(raw, str) else raw, name)
    try:
        stock = materials.stock("", "", profile)
    except cloud.CloudError:
        stock = []
    try:
        had = cloud.call("materials/orders/list", {"status": ""}, profile).get("lines", [])
    except cloud.CloudError:
        had = []
    by_key = {x.get("key"): x for x in had if x.get("key")}
    out = []
    for line in doc["lines"]:
        d = orders._draft(line)
        match, cands = similar(line, doc["supplier"], stock)
        k = _key(doc["supplier"] or "", doc["ref"] or "", line)
        was = by_key.get(k)
        known = {"id": was["id"], "status": was.get("status"), "articleId": was.get("articleId")} if was else None
        best = match or (cands[0] if cands and cands[0]["score"] >= LIKELY else None)
        if known:
            action = "link"
        elif doc["kind"] in ("service", "other") and best:
            action = "link"                     # it is ours already: a report about it, not a purchase
        else:
            action = "expect"
        target = (known or {}).get("articleId") or (best or {}).get("id")
        out.append({**line, **d, "match": match, "candidates": cands, "known": known, "action": action,
                    "articleId": target if action == "link" or match else None})
    return {**doc, "file": file or None, "lines": out, "dry_run": True}


# ---- applying ------------------------------------------------------------------

def _put(url: str, data: bytes, ctype: str) -> None:
    """The file to the cloud's signed link (S3), nothing else in the request."""
    req = urllib.request.Request(url, data=data, method="PUT",
                                 headers={"Content-Type": ctype, "Content-Length": str(len(data))})
    with urllib.request.urlopen(req, timeout=120) as r:      # noqa: S310 - an https link the cloud signed
        if r.status not in (200, 204):
            raise SupplierError(f"the cloud did not take the file ({r.status})")


def apply(pv: Dict[str, Any], profile: Optional[str] = None) -> Dict[str, Any]:
    """What the person kept of a preview: expected lines, links, and the
    documents onto the parts and lines they concern. Removes the e-mail from
    the inbox once done (forget: false keeps it)."""
    supplier = str(pv.get("supplier") or "").strip().lower()
    ref = str(pv.get("ref") or "").strip()
    lines = [x for x in (pv.get("lines") or []) if isinstance(x, dict)][:MAX_LINES]
    for x in lines:
        if x.get("action") not in ACTIONS:
            raise SupplierError(f"a line's action is one of {', '.join(ACTIONS)}")
        if x.get("action") == "link" and not (x.get("articleId") or x.get("known")):
            raise SupplierError(f"{x.get('title')}: linking needs the stock's article (articleId)")
    expect = [x for x in lines if x["action"] == "expect" and not x.get("known")]
    links = [x for x in lines if x["action"] == "link"]
    if not expect and not links:
        raise SupplierError("no line is to be expected or linked")
    article_ids: List[str] = []
    line_ids: List[str] = []
    added = skipped = 0
    if expect:
        if not supplier or not ref:
            raise SupplierError("expected lines need the shop (supplier, as example.org) and the document's number (ref)")
        got = orders.apply({"supplier": supplier, "orderRef": ref, "orderedAt": pv.get("date"),
                            "lines": [{**x, "include": True, "match": {"id": x["articleId"]} if x.get("articleId") else None}
                                      for x in expect]}, profile)
        added, skipped = got["added"], got["skipped"]
        now = {x.get("key"): x for x in cloud.call("materials/orders/list", {"status": ""}, profile).get("lines", [])}
        for x in expect:
            o = now.get(_key(supplier, ref, x))
            if o and o.get("status") == "open":
                line_ids.append(o["id"])
            elif o and o.get("articleId"):
                article_ids.append(o["articleId"])
    linked = []
    for x in links:
        k = x.get("known") or {}
        if k.get("status") == "open" and not x.get("articleId"):
            line_ids.append(k["id"])
            continue
        aid = x.get("articleId") or k.get("articleId")
        article_ids.append(aid)
        if supplier and x.get("sku"):
            try:
                cloud.call("materials/article/ref", {"articleId": aid, "ref": f"{supplier}:{str(x['sku']).upper()}"}, profile)
            except cloud.CloudError as e:                     # a number the cloud refuses: the link still counts
                linked.append({"articleId": aid, "note": str(e)})
                continue
        linked.append({"articleId": aid})
    documents = []
    file = str(pv.get("file") or "")
    if file and pv.get("documents", True) and (article_ids or line_ids):
        raw, name = _inbox_bytes(file)
        _, blobs = _read(raw, name)
        source = " ".join(x for x in (supplier, ref) if x)[:80]
        for a in blobs:
            meta = {"name": a["name"], "size": a["size"], "type": a["type"], "sha256": a["sha256"], "kind": "receipt", "source": source}
            up = cloud.call("materials/docs/upload", meta, profile)
            if not up.get("exists"):
                _put(up["url"], a["data"], a["type"])
            put = cloud.call("materials/docs/attach", {**meta, "fileId": up["fileId"],
                                                       "articleIds": sorted(set(article_ids)), "orderLineIds": sorted(set(line_ids))}, profile)
            documents.append({"name": a["name"], "kept": bool(up.get("exists")),
                              "articles": put.get("articles", []), "orderLines": put.get("orderLines", [])})
    if file and pv.get("forget", True):
        try:
            ib.remove(file)
        except (ib.NotFound, ValueError):
            pass
    return {"ref": ref or None, "added": added, "skipped": skipped, "linked": linked, "documents": documents}
