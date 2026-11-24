# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
orders.py — an order-confirmation e-mail into expected parts (ADR-0023 in
maker-5-shared). Amazon's first: ordinary accounts have no order API, and
nobody signs in to a shop on the person's behalf.

    parse(raw)               the order in an e-mail (.eml bytes, or pasted text)
    preview(raw)             what an import would add, matched against the
                             stock; writes nothing
    apply(preview)           the lines the person kept, as expected in the cloud
    open_lines()             what is expected and has not arrived yet

What leaves the e-mail is only: the shop (from the sender's domain), the
order number and its date, and for each line its title, the shop's article
number (an ASIN), the quantity and the unit price. The address, the name,
the payment and everything else are read past and never kept; the e-mail
itself is not stored.

A line waits in the cloud until the parcel is scanned at the shelf and an
item is checked in against it (the intake, ADR-0022). Importing books no
stock: the check-in does, as always, by an admin.
"""

from __future__ import annotations

import email
import email.policy
import email.utils
import re
import urllib.parse
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

from . import bom_import, materials
from .edge import cloud

MAX_BYTES = 2 * 1024 * 1024
MAX_LINES = 50

ORDER_REF = re.compile(r"\b(\d{3}-\d{7}-\d{7})\b")
ASIN_IN_URL = re.compile(r"/(?:dp|gp/product|gp/aw/d|o/ASIN)/([A-Z0-9]{10})(?![A-Z0-9])")
SHOP = re.compile(r"\b(amazon\.(?:de|com|co\.uk|fr|it|es|nl|at|ch|se|pl|com\.be))\b", re.I)
QTY = re.compile(r"\b(?:Menge|Anzahl|Stückzahl|Quantity|Qty|Qté|Quantité)\s*:?\s*(\d{1,4})\b", re.I)
PRICE = re.compile(r"(?:(€|EUR|£|GBP|\$|USD|CHF)\s*(\d{1,6}(?:[.,]\d{3})*[.,]\d{2}))|(?:(\d{1,6}(?:[.,]\d{3})*[.,]\d{2})\s*(€|EUR|£|GBP|CHF))")
CURRENCY = {"€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP", "$": "USD", "USD": "USD", "CHF": "CHF"}
# a pack in the title: "100 Stück", "5 x", "20pcs"
PACK = re.compile(r"(?<![\d.,])(\d{1,4})\s*(?:Stück|Stk\.?|pcs|pieces|Teile|St\.|er[- ]Pack|-Pack|Pack|x\b)", re.I)
# where Amazon's own suggestions begin: nothing after this is the order
NOT_THE_ORDER = re.compile(r"(Kunden, die|Empfehlungen für Sie|Das könnte Ihnen|Customers who bought|Recommended for you|"
                           r"You might also like|Inspiré par|Les clients ayant)", re.I)
LINK_WORDS = {"ansehen", "anzeigen", "view", "details", "bestellung", "order", "produkt", "product", "voir", "hier"}
DEVICE_WORDS = (("device", ("raspberry pi 4", "raspberry pi 5", "raspberry pi zero", "router", "switch hub", "ip camera",
                            "webcam", "multimeter", "oscilloscope", "soldering station", "3d printer", "power bank",
                            "netzteil labor", "lab power supply")),)


class OrderError(ValueError):
    """The e-mail can't be read as an order: say why."""


# ---- reading the e-mail ------------------------------------------------------

class _Tokens(HTMLParser):
    """An HTML body as a stream: ("t", text) and ("a", href, anchor text)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: List[Tuple[str, ...]] = []
        self._skip = 0
        self._href: Optional[str] = None
        self._anchor: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head", "title"):
            self._skip += 1
        elif tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._anchor = []
        elif tag == "img" and self._href is not None:
            alt = dict(attrs).get("alt") or ""
            if alt:
                self._anchor.append(alt)
        elif tag in ("br", "p", "tr", "td", "div", "li"):
            self.out.append(("t", "\n"))

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head", "title"):
            self._skip = max(0, self._skip - 1)
        elif tag == "a" and self._href is not None:
            text = " ".join(" ".join(self._anchor).split())
            self.out.append(("a", self._href, text))
            self.out.append(("t", " " + text + " "))
            self._href = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._href is not None:
            self._anchor.append(data)
        else:
            self.out.append(("t", data))


def _plain_tokens(text: str) -> List[Tuple[str, ...]]:
    """Plain text as the same stream: a URL is a link whose anchor is the line before it."""
    out: List[Tuple[str, ...]] = []
    last = ""
    for line in text.splitlines():
        urls = re.findall(r"https?://\S+", line)
        rest = re.sub(r"<?https?://\S+>?", " ", line).strip()
        for u in urls:
            out.append(("a", u.strip("<>()"), rest or last))
        if rest:
            last = rest
        out.append(("t", line + "\n"))
    return out


def _asin(href: str) -> Optional[str]:
    """The ASIN a link points at, also through Amazon's redirects (?U=https%3A…%2Fdp%2FB0…)."""
    for _ in range(3):
        m = ASIN_IN_URL.search(href)
        if m:
            return m.group(1)
        nxt = urllib.parse.unquote(href)
        if nxt == href:
            return None
        href = nxt
    return None


def _message(raw: bytes) -> Tuple[str, str, Optional[str], str]:
    """(body, kind html|text, shop from the sender, date) of an e-mail, or the text itself."""
    head = raw[:4096].decode("utf-8", "replace")
    if not re.search(r"^(From|Subject|Date|Received|Return-Path|MIME-Version):", head, re.M | re.I):
        return raw.decode("utf-8", "replace"), "text", None, ""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    sender = email.utils.parseaddr(str(msg.get("From") or ""))[1]
    shop = SHOP.search(sender.split("@")[-1]) if "@" in sender else None
    date = ""
    try:
        d = email.utils.parsedate_to_datetime(str(msg.get("Date") or ""))
        date = d.date().isoformat() if d else ""
    except (TypeError, ValueError):
        pass
    part = msg.get_body(preferencelist=("html", "plain"))
    if part is None:
        raise OrderError("this e-mail has no text to read")
    kind = "html" if part.get_content_type() == "text/html" else "text"
    return str(part.get_content()), kind, shop.group(1).lower() if shop else None, date


def parse(raw: Any) -> Dict[str, Any]:
    """The order in an e-mail: {supplier, orderRef, orderedAt, lines: [{title, sku, ordered, unitPrice, currency}]}."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not raw or not raw.strip():
        raise OrderError("drop an order e-mail (.eml) or paste its text")
    if len(raw) > MAX_BYTES:
        raise OrderError("that e-mail is larger than 2 MB")
    body, kind, shop, date = _message(raw)
    if kind == "html":
        p = _Tokens()
        p.feed(body)
        p.close()
        tokens = p.out
    else:
        tokens = _plain_tokens(body)

    # the order's text, up to where the shop's suggestions begin
    text, cut = "", len(tokens)
    for i, tk in enumerate(tokens):
        if tk[0] == "t":
            if NOT_THE_ORDER.search(tk[1]):
                cut = i
                break
            text += tk[1]
    tokens = tokens[:cut]
    m = ORDER_REF.search(text)
    if not m:
        raise OrderError("no order number in this e-mail: is it an order confirmation?")
    if not shop:
        s = SHOP.search(text) or SHOP.search(" ".join(t[1] for t in tokens if t[0] == "a"))
        shop = s.group(1).lower() if s else "amazon.de"
    if not date:
        d = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b", text)
        date = f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}" if d else ""

    # each product: its ASIN, its longest anchor, and the text from it to the next product
    found: List[Dict[str, Any]] = []
    where: Dict[str, int] = {}
    for i, tk in enumerate(tokens):
        if tk[0] != "a":
            continue
        asin = _asin(tk[1])
        title = " ".join(str(tk[2]).split())
        if not asin:
            continue
        good = len(title) >= 6 and title.lower() not in LINK_WORDS and not re.match(r"^https?://", title)
        if asin in where:
            f = found[where[asin]]
            if good and len(title) > len(f["title"]):
                f["title"] = title
            continue
        where[asin] = len(found)
        found.append({"sku": asin, "title": title if good else "", "at": i})
    lines = []
    for n, f in enumerate(found):
        end = found[n + 1]["at"] if n + 1 < len(found) else len(tokens)
        seg = "".join(tk[1] if tk[0] == "t" else "" for tk in tokens[f["at"]:end])
        if not f["title"]:
            continue
        q = QTY.search(seg)
        pr = PRICE.search(seg)
        price, cur = None, None
        if pr:
            sym = pr.group(1) or pr.group(4)
            amount = pr.group(2) or pr.group(3)
            price = float(amount.replace(".", "").replace(",", ".")) if "," in amount[-3:] else float(amount.replace(",", ""))
            cur = CURRENCY.get(sym.upper() if sym.isalpha() else sym)
        lines.append({"title": f["title"][:200], "sku": f["sku"], "ordered": int(q.group(1)) if q else 1,
                      "unitPrice": price, "currency": cur})
    if not lines:
        raise OrderError("no articles found in this e-mail: it needs the links to the products")
    if len(lines) > MAX_LINES:
        raise OrderError(f"at most {MAX_LINES} lines in one order")
    return {"supplier": shop, "orderRef": m.group(1), "orderedAt": date or None, "lines": lines}


# ---- matching and drafting ---------------------------------------------------

def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", s.lower()).split())


def _match(line: Dict[str, Any], supplier: str, stock: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The stock's article for a line: by where it was bought, else by its name in the title."""
    ref = f"{supplier}:{line['sku']}"
    for a in stock:
        if ref in (a.get("supplierRefs") or []):
            return {"id": a["id"], "name": a["name"], "by": "shop"}
    t = _norm(line["title"])
    best = None
    for a in stock:
        n = _norm(a.get("name") or "")
        if len(n) >= 8 and (n == t or f" {n} " in f" {t} ") and (not best or len(n) > len(best["name"])):
            best = {"id": a["id"], "name": a["name"], "by": "name"}
    return best


def _maker(title: str) -> str:
    """The brand Amazon titles start with: "YIXISI 100 Stück …", "AZDelivery 5 x …"."""
    m = re.match(r"^([A-Za-z][A-Za-z0-9&-]{2,24})\b", title)
    if not m:
        return ""
    w = m.group(1)
    return w if (w.isupper() or re.search(r"[a-z][A-Z]", w)) else ""


def _draft(line: Dict[str, Any]) -> Dict[str, Any]:
    """A line as it would be expected: a device or parts, how many parts, and a new article."""
    title = line["title"]
    device = bool(bom_import._words(f" {title} ", DEVICE_WORDS))
    pack = PACK.search(title)
    each = int(pack.group(1)) if pack and not device else 1
    name = re.split(r"\s[,|–-]\s|, ", title)[0][:120] if len(title) > 120 else title
    article = {"name": name, "category": bom_import._words(f" {title} ", bom_import.CATEGORY_WORDS) or "other"}
    maker = _maker(title)
    if maker:
        article["manufacturer"] = maker
    return {"what": "device" if device else "bulk", "pack": each, "qty": line["ordered"] * each, "article": article}


def preview(raw: Any, profile: Optional[str] = None) -> Dict[str, Any]:
    """What importing this e-mail would add; writes nothing. Each line: matched to
    an article of the stock, or a new article drafted; a line already expected is
    not included again."""
    order = parse(raw)
    try:
        stock = materials.stock("", "", profile)
    except cloud.CloudError:
        stock = []
    try:
        had = cloud.call("materials/orders/list", {"status": ""}, profile).get("lines", [])
    except cloud.CloudError:
        had = []
    keys = {(x.get("supplier"), x.get("orderRef"), x.get("sku")) for x in had}
    out = []
    for line in order["lines"]:
        d = _draft(line)
        match = _match(line, order["supplier"], stock)
        known = (order["supplier"], order["orderRef"], line["sku"]) in keys
        out.append({**line, **d, "match": match, "known": known, "include": not known})
    return {**order, "lines": out, "dry_run": True}


def apply(pv: Dict[str, Any], profile: Optional[str] = None) -> Dict[str, Any]:
    """The lines the person kept, as expected in the cloud (a line imported before is skipped there)."""
    keep = [x for x in (pv.get("lines") or []) if x.get("include")]
    if not keep:
        raise OrderError("no line is ticked")
    lines = []
    for x in keep[:MAX_LINES]:
        line = {"title": x.get("title"), "sku": x.get("sku"), "qty": x.get("qty") or 1, "what": x.get("what") or "bulk",
                "unitPrice": x.get("unitPrice"), "currency": x.get("currency")}
        match = x.get("match") or {}
        if match.get("id"):
            line["articleId"] = match["id"]
        else:
            line["article"] = {k: v for k, v in (x.get("article") or {}).items()
                               if k in ("name", "category", "manufacturer", "mpn", "unit", "note") and v}
        lines.append({k: v for k, v in line.items() if v is not None})
    got = cloud.call("materials/orders/add", {"supplier": pv.get("supplier"), "orderRef": pv.get("orderRef"),
                                              "orderedAt": pv.get("orderedAt"), "lines": lines}, profile)
    return {"added": len(got.get("added") or []), "skipped": got.get("skipped", 0), "orderRef": pv.get("orderRef")}


def open_lines(profile: Optional[str] = None) -> List[Dict[str, Any]]:
    """What is expected and has not all arrived: title, quantity, arrived, the article (or a new one), when ordered."""
    return cloud.call("materials/orders/list", {"status": "open"}, profile).get("lines", [])
