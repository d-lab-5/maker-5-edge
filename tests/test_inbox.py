# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""The inbox: files given to the chat, kinds detected from their content."""

import io
import zipfile

import pytest

from maker_5_edge import inbox as ib


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "data"))
    yield


def _xlsx(rows):
    buf = io.BytesIO()
    strings = sorted({c for r in rows for c in r})
    idx = {s: i for i, s in enumerate(strings)}
    sheet = "".join("<row>" + "".join(f'<c r="{chr(65 + j)}{i + 1}" t="s"><v>{idx[c]}</v></c>' for j, c in enumerate(r))
                    + "</row>" for i, r in enumerate(rows))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{sheet}</sheetData></worksheet>")
    return buf.getvalue()


SCH = b'(kicad_sch (version 20231120)\n  (symbol (lib_id "Device:R") (at 10 10 0))\n  (symbol (lib_id "Device:C") (at 20 10 0)))\n'
STEP = b"ISO-10303-21;\nHEADER;\nFILE_NAME('enclosure.step','2026-01-01',(''),(''),'','','');\nENDSEC;\n"


def test_kinds_come_from_content_not_the_name():
    assert ib.detect("x.txt", SCH)["kind"] == "kicad"
    assert "2 symbols" in ib.detect("x.txt", SCH)["note"]
    assert ib.detect("model.bin", STEP) == {"kind": "step", "note": "a STEP model (CAD), enclosure.step"}
    assert ib.detect("bom.dat", b"ref;value;qty\nR1;10k;1\nC1;100n;2\n")["kind"] == "csv"
    assert ib.detect("bom", _xlsx([["ref", "qty"], ["R1", "1"]]))["kind"] == "xlsx"
    assert ib.detect("m", b"@prefix m5: <https://maker-5.cloud/ontology#> .")["kind"] == "turtle"
    assert ib.detect("j", b'{"a": 1}')["kind"] == "json"
    assert ib.detect("b", b"\x00\x01\x02")["kind"] == "unknown"


def test_files_are_private_and_read_in_slices():
    m = ib.add("schematic.kicad_sch", SCH)
    d = ib._dir(m["id"])
    assert d.stat().st_mode & 0o777 == 0o700 and (d / "file").stat().st_mode & 0o777 == 0o600
    got = ib.read(m["id"], offset=0, limit=20)
    assert got["text"] == SCH.decode()[:20] and got["more"]
    assert ib.read(m["id"], offset=20)["more"] is False


def test_bad_ids_never_reach_the_disk():
    for bad in ("../x", "in-zz", "", "in-0123456789/.."):
        with pytest.raises(ValueError):
            ib.meta(bad)
    with pytest.raises(ib.NotFound):
        ib.meta("in-0123456789")
    with pytest.raises(ValueError):
        ib.add("empty", b"")
