# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""selection.py — what the page has open (a product, an item, a file given to the chat)."""

from __future__ import annotations

import threading
from typing import Dict

_lock = threading.Lock()
_current: Dict[str, str] = {}


def set(product: str = "", item: str = "", file: str = "") -> Dict[str, str]:  # noqa: A001 — module API
    with _lock:
        _current.clear()
        if product:
            _current["product"] = product
        if item:
            _current["item"] = item
        if file:
            _current["file"] = file
        return dict(_current)


def get() -> Dict[str, str]:
    with _lock:
        return dict(_current)


def key():
    got = get()
    return f"{got.get('product', '')}/{got.get('item', '')}/{got.get('file', '')}" if got else None
