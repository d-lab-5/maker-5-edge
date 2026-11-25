# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
elv.py — ELV Elektronik's documents (elv.de): orders, invoices, delivery
notes and service shipments. The e-mail itself says little; the attached
PDF has the table, read as text (pdftotext -layout):

    Item No.    Description                          Serial No.   ...
    118383      EXAMPLE dLAN 1200+ WiFi ac Starter                SART00000

German documents say "Artikel-Nr." / "Art.-Nr." and "Bezeichnung". Only the
article number, its description and a quantity (when the line has one) are
kept; the address block, the clerk and the bank lines are read past.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

SHOP = "elv.de"
# a table's head, and where its lines end
_HEAD = re.compile(r"^\s*(Item No\.|Artikel-?Nr\.?|Art\.-Nr\.?)\s{2,}(Description|Bezeichnung)", re.I | re.M)
_END = re.compile(r"^\s*(Service Shipment Line|Executive:|Vorstand|Gesamtbetrag|Total|Summe|Zwischensumme|Page \d|Seite \d)", re.I)
_LINE = re.compile(r"^\s{0,6}(\d{5,8}|[A-Z]{1,3}-?\d{4,8})\s{2,}(\S.*?)(?:\s{2,}(.*))?$")
_QTY = re.compile(r"(?:^|\s)(\d{1,4})\s+(?:St\.?|Stk\.?|pcs|PCS|STK|Stück)(?:\s|$)")
_PRICE = re.compile(r"(\d{1,6},\d{2})\s*(?:€|EUR)?")
_REF = re.compile(r"\b(?:Service Shipment|Rechnung|Invoice|Lieferschein|Auftrag|Order|Bestellung)\s*(?:Nr\.?|No\.?)?\s*:?\s*([A-Z]{0,8}\d{5,12})\b", re.I)
_DATE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{2}|\d{4})\b")


def mine(sender: str, text: str) -> bool:
    return sender.endswith("elv.de") or "ELV Elektronik AG" in text


def read(texts: List[str]) -> Dict[str, Any]:
    """The lines of every ELV table in the PDFs' texts, with the document's number and date."""
    lines: List[Dict[str, Any]] = []
    ref, date = None, None
    for text in texts:
        r = _REF.search(text)
        if r and not ref:
            ref = r.group(1).upper()
        d = _DATE.search(text)
        if d and not date:
            y = d.group(3)
            date = f"{'20' + y if len(y) == 2 else y}-{d.group(2)}-{d.group(1)}"
        for m in _HEAD.finditer(text):
            for raw in text[m.end():].splitlines()[1:]:
                if _END.match(raw):
                    break
                x = _LINE.match(raw)
                if not x:
                    continue
                title = re.split(r"\s{2,}", x.group(2).strip())[0]
                rest = " ".join(filter(None, [x.group(2), x.group(3)]))
                q = _QTY.search(rest)
                p = _PRICE.search(x.group(3) or "")
                if any(l["sku"] == x.group(1) for l in lines):
                    continue
                lines.append({"title": title[:200], "sku": x.group(1).upper(), "ordered": int(q.group(1)) if q else 1,
                              "unitPrice": float(p.group(1).replace(",", ".")) if p else None,
                              "currency": "EUR" if p else None})
    return {"ref": ref, "date": date, "lines": lines}


def kind(subject: str, texts: List[str]) -> Optional[str]:
    s = " ".join([subject] + texts[:1])
    if re.search(r"Service\s*(Shipment|einsendung)|Reparatur|RMA", s, re.I):
        return "service"
    return None
