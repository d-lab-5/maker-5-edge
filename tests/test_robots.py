# SPDX-License-Identifier: GPL-3.0-or-later
"""Robots are their own category, counted unit by unit (ADR-0019, amended)."""

from maker_5_edge import bom_import as bi


def test_a_robot_is_a_robot_not_a_controller():
    for name, cat in (("Thymio II", "robots/educational"), ("Anki Cozmo", "robots/educational"),
                      ("Four-wheel robot rover", "robots/mobile"), ("Small robot arm", "robots/arms")):
        assert bi._words(f" {name} ", bi.CATEGORY_WORDS) == cat, name
        assert cat in bi.SERIAL


def test_a_robot_in_an_order_is_a_device():
    from maker_5_edge import orders as od
    got = od._draft({"title": "Example Thymio II educational robot", "ordered": 1})
    assert got["what"] == "device" and got["article"]["category"] == "robots/educational"
