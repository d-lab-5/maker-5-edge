# SPDX-License-Identifier: GPL-3.0-or-later
"""An order e-mail into expected parts (orders.py; ADR-0023 in maker-5-shared).
The cloud is a fake; every name, number and address is invented."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from maker_5_edge import app as web
from maker_5_edge import orders as od
from maker_5_edge.edge import cloud, settings

FIX = Path(__file__).parent / "fixtures" / "orders"


@pytest.fixture
def fake_cloud(monkeypatch):
    calls = []
    stock = [{"id": "a-2222222222", "name": "Raspberry Pi 5 Example Board", "supplierRefs": []},
             {"id": "a-3333333333", "name": "Something else", "supplierRefs": ["amazon.com:B0EXAMPLE3"]}]

    def call(path, body=None, profile=None):
        calls.append((path, body))
        if path == "materials/list":
            return {"articles": stock}
        if path == "materials/orders/list":
            return {"lines": [{"supplier": "amazon.de", "orderRef": "000-0000000-0000009", "sku": "B0EXAMPLE1", "status": "open"}]}
        if path == "materials/orders/add":
            return {"added": [{"id": "o-2222222222"}] * len(body["lines"]), "skipped": 0}
        raise AssertionError(path)
    monkeypatch.setattr(cloud, "call", call)
    return calls


def test_a_german_html_mail_gives_its_order_and_lines():
    o = od.parse((FIX / "amazon-de.eml").read_bytes())
    assert o["supplier"] == "amazon.de" and o["orderRef"] == "000-0000000-0000001" and o["orderedAt"] == "2026-11-20"
    assert [(x["sku"], x["ordered"], x["unitPrice"], x["currency"]) for x in o["lines"]] == [
        ("B0EXAMPLE1", 2, 9.99, "EUR"), ("B0EXAMPLE2", 1, 89.9, "EUR")]
    assert o["lines"][0]["title"].startswith("EXAMPLEBRAND 100 Stück")


def test_the_shops_suggestions_are_not_the_order():
    o = od.parse((FIX / "amazon-de.eml").read_bytes())
    assert "B0EXAMPLE9" not in [x["sku"] for x in o["lines"]]
    t = od.parse((FIX / "amazon-com.txt").read_text())
    assert [x["sku"] for x in t["lines"]] == ["B0EXAMPLE3"]


def test_pasted_english_text_works_too():
    o = od.parse((FIX / "amazon-com.txt").read_text())
    assert o["supplier"] == "amazon.com" and o["orderRef"] == "000-0000000-0000002" and o["orderedAt"] == "2026-11-21"
    x = o["lines"][0]
    assert (x["title"], x["ordered"], x["unitPrice"], x["currency"]) == ("ExampleCo 20pcs LM386 audio amplifier module", 3, 12.49, "USD")


def test_nothing_personal_leaves_the_mail():
    for f in ("amazon-de.eml", "amazon-com.txt"):
        out = json.dumps(od.parse((FIX / f).read_bytes()), ensure_ascii=False)
        for word in ("Erika", "Beispielweg", "12345", "Visa", "0000\"", "Example Person", "Example Street", "someone@"):
            assert word not in out, (f, word)


def test_not_an_order_says_so():
    with pytest.raises(od.OrderError):
        od.parse("Hello, this is no order.")
    with pytest.raises(od.OrderError):
        od.parse("")


def test_a_preview_matches_by_shop_then_by_name_and_drafts_the_rest(fake_cloud):
    de = od.preview((FIX / "amazon-de.eml").read_bytes())
    switch, pi = de["lines"]
    assert switch["match"] is None and switch["what"] == "bulk" and switch["pack"] == 100 and switch["qty"] == 200
    assert switch["article"]["manufacturer"] == "EXAMPLEBRAND"
    assert pi["match"] == {"id": "a-2222222222", "name": "Raspberry Pi 5 Example Board", "by": "name"}
    assert pi["what"] == "device" and pi["qty"] == 1
    com = od.preview((FIX / "amazon-com.txt").read_text())
    assert com["lines"][0]["match"]["by"] == "shop" and com["lines"][0]["article"]["category"] == "media/audio"
    assert all(p != "materials/orders/add" for p, _ in fake_cloud), "a preview writes nothing"


def test_apply_sends_only_the_ticked_lines(fake_cloud):
    pv = od.preview((FIX / "amazon-de.eml").read_bytes())
    pv["lines"][1]["include"] = False
    got = od.apply(pv)
    assert got["added"] == 1
    sent = [b for p, b in fake_cloud if p == "materials/orders/add"][0]
    assert sent["orderRef"] == "000-0000000-0000001" and len(sent["lines"]) == 1
    line = sent["lines"][0]
    assert line["qty"] == 200 and "articleId" not in line and line["article"]["name"].startswith("EXAMPLEBRAND")
    with pytest.raises(od.OrderError):
        od.apply({**pv, "lines": [{**x, "include": False} for x in pv["lines"]]})


def test_the_page_takes_a_file_or_text(fake_cloud):
    c = web.app.test_client()
    r = c.post("/api/orders/preview", data={"file": ((FIX / "amazon-de.eml").open("rb"), "order.eml")},
               content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["dry_run"] and len(r.get_json()["lines"]) == 2
    r = c.post("/api/orders/preview", json={"text": "no order here"})
    assert r.status_code == 400
    r = c.post("/api/orders/apply", json={"preview": r.get_json()})
    assert r.status_code == 400


def test_the_chat_cannot_import_an_order():
    for path in ("/api/orders/preview", "/api/orders/apply"):
        assert not any(m == "POST" and re.fullmatch(rx, path) for m, rx in settings.CHAT_ALLOWED)
