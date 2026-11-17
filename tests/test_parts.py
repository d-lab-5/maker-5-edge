# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""Parts from the organisation's stock (ADR-0010 in maker-5-shared): a block
names its article, the parts list counts what the model needs against what
the product took, and taking parts goes to the cloud for the product's
space. The cloud is a fake here; every name is invented."""

from __future__ import annotations

import re

import pytest

from maker_5_edge import materials as mt
from maker_5_edge import products as pr
from maker_5_edge.edge import cloud, knowledge as kn, settings

PI = "a-abcdefghjk"
SD = "a-bcdefghjkm"


@pytest.fixture
def P(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "mydocs"))
    return pr.Products()


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def call(path, body, profile=None):
        calls.append((path, body))
        if path == "materials/list":
            return {"articles": [{"id": PI, "name": "Raspberry Pi 1 B", "tracking": "serial", "unit": "pcs", "free": 2},
                                 {"id": SD, "name": "microSD 16 GB", "tracking": "bulk", "unit": "pcs", "free": 10}]}
        if path == "materials/product":
            return {"lines": [{"articleId": SD, "reserved": 1, "consumed": 0, "units": []}]}
        if path.startswith("materials/"):
            return {"done": path.split("/")[1], "qty": body.get("qty", 1)}
        raise AssertionError(path)
    monkeypatch.setattr(cloud, "call", call)
    monkeypatch.setattr(cloud, "space_by_slug", lambda slug, profile=None:
                        {"id": "s-aaaaaaaaaa", "name": "Weather box"} if slug == "weather-box" else None)
    return calls


def test_a_block_names_its_article_and_the_shapes_check_it(P):
    p = P.new_product("Weather box")["product"]
    b = P.add_block(p, "Controller")["id"]
    P.link_article(p, b, PI)
    s = P.add_block(p, "Boot card")["id"]
    P.link_article(p, s, SD, 2)
    got = {x["name"]: (x["article"], x["quantity"]) for x in P.model(p)["blocks"]}
    assert got == {"Controller": (PI, 1), "Boot card": (SD, 2)}
    with pytest.raises(ValueError):
        P.link_article(p, b, "not-an-article")
    with pytest.raises(ValueError):
        P.link_article(p, b, PI, 0)
    P.link_article(p, b, "")
    assert P.model(p)["blocks"][1]["article"] == ""


def test_the_parts_list_counts_need_against_what_was_taken(P, fake):
    p = P.new_product("Weather box")["product"]
    for name, art, q in (("Controller", PI, 1), ("Boot card", SD, 2), ("Spare card", SD, 1)):
        P.link_article(p, P.add_block(p, name)["id"], art, q)
    got = mt.bom(P, p)
    lines = {l["article"]: l for l in got["lines"]}
    assert got["space"]["id"] == "s-aaaaaaaaaa"
    assert lines[SD]["need"] == 3 and lines[SD]["reserved"] == 1 and lines[SD]["missing"] == 2 and lines[SD]["free"] == 10
    assert lines[PI]["missing"] == 1 and lines[PI]["name"] == "Raspberry Pi 1 B"


def test_taking_parts_goes_to_the_products_space(P, fake):
    p = P.new_product("Weather box")["product"]
    mt.take(P, p, "reserve", SD, qty=2)
    mt.take(P, p, "return", PI, unit_id="u-abcdefghjk")
    assert fake[-2] == ("materials/reserve", {"spaceId": "s-aaaaaaaaaa", "articleId": SD, "note": "", "qty": 2})
    assert fake[-1][1]["unitId"] == "u-abcdefghjk" and "qty" not in fake[-1][1]
    with pytest.raises(ValueError):
        mt.take(P, p, "consume", SD, qty=1)          # using up is the person's, on the site
    q = P.new_product("Nameless here")["product"]
    with pytest.raises(mt.NoSpace):
        mt.take(P, q, "reserve", SD, qty=1)


def test_the_chat_may_propose_parts_but_not_more():
    p = "p-abcdefgh"
    ok = [("POST", f"/api/products/{p}/items/b-abcdefgh/article"), ("POST", f"/api/products/{p}/parts/reserve"),
          ("POST", f"/api/products/{p}/parts/return")]
    for method, path in ok:
        assert any(m == method and re.fullmatch(rx, path) for m, rx in settings.CHAT_ALLOWED), path
    for path in (f"/api/products/{p}/parts/consume", f"/api/products/{p}/items/i-abcdefgh/article"):
        assert not any(re.fullmatch(rx, path) for _, rx in settings.CHAT_ALLOWED), path
