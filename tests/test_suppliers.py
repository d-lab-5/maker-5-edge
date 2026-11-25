# SPDX-License-Identifier: GPL-3.0-or-later
"""A supplier's document into the stock (suppliers/; ADR-0024 in
maker-5-shared): readers per shop, duplicates, expect or link, documents onto
the parts, and the chat only proposing it. The cloud is a fake; every name,
number and address is invented."""

from __future__ import annotations

import re
import shutil
from email.message import EmailMessage
from pathlib import Path

import pytest

from maker_5_edge import app as web
from maker_5_edge import inbox as ib
from maker_5_edge import suppliers as sp
from maker_5_edge.edge import cloud, settings
from maker_5_edge.suppliers import elv

FIX = Path(__file__).parent / "fixtures" / "orders"
ELV_TEXT = """   ELV Elektronik AG ° 00000 Example City                                         Page 1
   Example Org                                                     Service Shipment EX000001
   c/o Erika Example
   Example Street 1                                                Example City, 06.09.18
   0000 Example City                                               Customer:      00000000


  Service Shipment Item Line

  Item No.                          Description                                   Serial No.     Service Item No.
  118383                            EXAMPLE dLAN 1200+ WiFi ac Starter                           SART00000

                                    nur 1x Adapter.

  Service Shipment Line
  No.                               Description                                          Quantity   Measure
  SERVICE DE                        Servicemitarbeiter                                          1   STD
"""


def _pdf(text: str) -> bytes:
    """A one-page PDF of monospaced lines, so pdftotext -layout keeps the columns."""
    rows = text.splitlines()
    ops = ["BT /F1 7 Tf 8 TL 20 800 Td"]
    for r in rows:
        ops.append("(" + r.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1", "replace")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


def _elv_mail() -> bytes:
    m = EmailMessage()
    m["From"] = "Kundenservice <service@elv.de>"
    m["To"] = "someone@example.org"
    m["Subject"] = "ELV Elektronik AG - Service - Shipment EX000001"
    m["Date"] = "Thu, 06 Sep 2018 10:00:00 +0200"
    m.set_content("Sehr geehrte Damen und Herren,\n\nanliegend erhalten Sie Ihre Serviceeinsendung zurück.\n\nIhr ELV Team\n")
    m.add_attachment(_pdf(ELV_TEXT), maintype="application", subtype="pdf", filename="Service - Shipment EX000001.pdf")
    return bytes(m)


needs_pdftotext = pytest.mark.skipif(not shutil.which("pdftotext"), reason="reading a PDF needs pdftotext")


@pytest.fixture
def edge(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "SYNC_SCOPE", "shared")
    stock = [{"id": "a-2222222222", "name": "Example dLAN 1200+ WiFi Starter Kit", "supplierRefs": []},
             {"id": "a-3333333333", "name": "Raspberry Pi 5 Example Board", "supplierRefs": ["amazon.de:B0EXAMPLE2"]},
             {"id": "a-4444444444", "name": "Example tactile switch", "mpn": "EXSW-6X6", "supplierRefs": []}]
    lines = [{"id": "o-2222222222", "key": "amazon.de|000-0000000-0000001|B0EXAMPLE1", "status": "open"}]
    state = {"calls": [], "puts": [], "stock": stock, "lines": lines, "files": {}}

    def call(path, body=None, profile=None):
        state["calls"].append((path, body))
        if path == "materials/list":
            return {"articles": stock}
        if path == "materials/orders/list":
            return {"lines": lines}
        if path == "materials/orders/add":
            out = []
            for l in body["lines"]:
                key = f"{body['supplier']}|{body['orderRef']}|{l.get('sku') or l['title'].lower()}"
                if any(x["key"] == key for x in lines):
                    continue
                x = {"id": f"o-{len(lines) + 2:010d}", "key": key, "status": "open", "articleId": l.get("articleId")}
                lines.append(x)
                out.append(x)
            return {"added": out, "skipped": len(body["lines"]) - len(out)}
        if path == "materials/article/ref":
            return {"id": body["articleId"], "supplierRefs": [body["ref"]]}
        if path == "materials/docs/upload":
            if body["sha256"] in state["files"]:
                return {"exists": True, "fileId": state["files"][body["sha256"]]}
            fid = f"{len(state['files']) + 1:012x}"
            state["files"][body["sha256"]] = fid
            return {"exists": False, "fileId": fid, "url": f"https://bucket.example.org/{fid}"}
        if path == "materials/docs/attach":
            return {"articles": body["articleIds"], "orderLines": body["orderLineIds"]}
        raise AssertionError(path)
    monkeypatch.setattr(cloud, "call", call)
    monkeypatch.setattr(sp, "_put", lambda url, data, ctype: state["puts"].append((url, len(data), ctype)))
    return state


def test_elvs_table_gives_its_item_and_reads_past_the_address():
    got = elv.read([ELV_TEXT])
    assert got["ref"] == "EX000001" and got["date"] == "2018-09-06"
    assert [(l["sku"], l["title"], l["ordered"]) for l in got["lines"]] == [("118383", "EXAMPLE dLAN 1200+ WiFi ac Starter", 1)]
    out = repr(got)
    for word in ("Erika", "Example Street", "00000000", "SERVICE DE"):
        assert word not in out, word


@needs_pdftotext
def test_an_elv_mail_is_a_service_report_with_its_pdf():
    d = sp.read(_elv_mail())
    assert (d["supplier"], d["kind"], d["ref"], d["reader"]) == ("elv.de", "service", "EX000001", "elv")
    assert [l["sku"] for l in d["lines"]] == ["118383"]
    assert [(a["name"], a["type"]) for a in d["attachments"]] == [("Service - Shipment EX000001.pdf", "application/pdf")]
    assert re.fullmatch(r"[0-9a-f]{64}", d["attachments"][0]["sha256"])
    assert "text" not in d, "a shop with a reader gives lines, not its text"


def test_amazon_still_reads_through_the_same_door():
    d = sp.read((FIX / "amazon-de.eml").read_bytes())
    assert (d["supplier"], d["ref"], d["kind"], d["reader"]) == ("amazon.de", "000-0000000-0000001", "order", "amazon")
    assert sp.read((FIX / "amazon-fr-shipped.eml").read_bytes())["kind"] == "shipment"


def test_a_shop_without_a_reader_gives_its_text_for_the_agent():
    m = EmailMessage()
    m["From"] = "shop@parts.example.org"
    m["Subject"] = "Ihre Rechnung 4711"
    m["Date"] = "Mon, 23 Nov 2026 10:00:00 +0100"
    m.set_content("Rechnung 4711\n2 x Example relay module 5V  3,20 EUR\n")
    d = sp.read(bytes(m))
    assert d["reader"] == "generic" and d["supplier"] == "example.org" and d["kind"] == "invoice" and not d["lines"]
    assert "Example relay module" in d["text"] and "note" in d


def test_names_that_look_alike_are_candidates_never_merged_on_their_own():
    assert sp.score("DEVOLO dLAN 1200+ WiFi ac Starter", "devolo dLAN 1200+ WiFi Starter Kit") >= sp.LIKELY
    assert sp.score("Example relay module", "Raspberry Pi 5 Example Board") < sp.SIMILAR
    stock = [{"id": "a-2222222222", "name": "devolo dLAN 1200+ WiFi Starter Kit"},
             {"id": "a-4444444444", "name": "Example tactile switch", "mpn": "EXSW-6X6"}]
    match, cands = sp.similar({"title": "DEVOLO dLAN 1200+ WiFi ac Starter", "sku": "118383"}, "elv.de", stock)
    assert match is None and cands[0]["id"] == "a-2222222222"
    assert sp.similar({"title": "Taster", "sku": "exsw-6x6"}, "x.example.org", stock)[0]["by"] == "mpn"


@needs_pdftotext
def test_a_service_report_links_to_the_part_we_have_and_puts_its_pdf_on_it(edge):
    fid = ib.add("elv.eml", _elv_mail())["id"]
    assert ib.meta(fid)["kind"] == "email"
    pv = sp.preview(file=fid)
    [line] = pv["lines"]
    assert line["action"] == "link" and line["articleId"] == "a-2222222222", "a report about a part we have: no second article"
    got = sp.apply(pv)
    assert got["added"] == 0 and got["linked"] == [{"articleId": "a-2222222222"}]
    assert ("materials/article/ref", {"articleId": "a-2222222222", "ref": "elv.de:118383"}) in edge["calls"]
    assert len(edge["puts"]) == 1 and edge["puts"][0][2] == "application/pdf"
    assert got["documents"][0]["articles"] == ["a-2222222222"]
    assert not any(p == "materials/orders/add" for p, _ in edge["calls"])
    with pytest.raises(ib.NotFound):
        ib.meta(fid)                                        # the e-mail is not kept


@needs_pdftotext
def test_the_same_document_twice_is_uploaded_once(edge):
    for _ in range(2):
        pv = sp.preview(file=ib.add("elv.eml", _elv_mail())["id"])
        sp.apply(pv)
    assert len(edge["puts"]) == 1, "the cloud has its content already"


def test_an_order_is_expected_known_articles_by_their_id_and_a_line_read_before_not_twice(edge):
    pv = sp.preview(file=ib.add("amazon.eml", (FIX / "amazon-de.eml").read_bytes())["id"])
    by = {l["sku"]: l for l in pv["lines"]}
    assert by["B0EXAMPLE1"]["known"]["id"] == "o-2222222222" and by["B0EXAMPLE1"]["action"] == "link"
    assert by["B0EXAMPLE2"]["action"] == "expect" and by["B0EXAMPLE2"]["articleId"] == "a-3333333333"
    got = sp.apply(pv)
    add = next(b for p, b in edge["calls"] if p == "materials/orders/add")
    assert [l.get("articleId") for l in add["lines"]] == ["a-3333333333"]
    assert got["added"] == 1 and not edge["puts"], "no attachments, nothing uploaded"


def test_linking_needs_the_part_and_expecting_needs_the_number(edge):
    with pytest.raises(sp.SupplierError):
        sp.apply({"supplier": "example.org", "ref": "EX-1", "lines": [{"title": "x", "action": "link"}]})
    with pytest.raises(sp.SupplierError):
        sp.apply({"supplier": "example.org", "lines": [{"title": "Example relay", "action": "expect"}]})
    with pytest.raises(sp.SupplierError):
        sp.apply({"lines": [{"title": "x", "action": "merge"}]})


def test_the_page_reads_an_upload_and_the_chat_may_only_propose_apply(edge):
    c = web.app.test_client()
    r = c.post("/api/suppliers/preview", data={"file": ((FIX / "amazon-de.eml").open("rb"), "a.eml")},
               content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["file"].startswith("in-")
    assert c.post("/api/suppliers/apply", json={"preview": {"lines": []}}).status_code == 400
    allowed = lambda path: any(m == "POST" and re.fullmatch(rx, path) for m, rx in settings.CHAT_ALLOWED)
    assert allowed("/api/suppliers/apply") and not allowed("/api/suppliers/preview")
