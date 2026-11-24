# SPDX-License-Identifier: GPL-3.0-or-later
"""Deploying software/ onto a board (ADR-0020 in maker-5-shared): a local
target really runs; a remote one records the ssh and rsync it would run."""

from __future__ import annotations

import pytest

from maker_5_edge import deploy as dp
from maker_5_edge import git_repo as gr
from tests.test_git_repo import ws  # noqa: F401 - the same workspace and fake GitHub


def board(ws):  # noqa: F811
    return next(b["id"] for b in ws["P"].model(ws["p"])["blocks"] if b["name"] == "Example board")


def test_a_local_target_is_copied_restarted_and_recorded(ws, tmp_path):  # noqa: F811
    gr.link(ws["P"], ws["p"])
    gr.write(ws["P"], ws["p"], "software/main.py", "print('ding')\n")
    gr.push(ws["P"], ws["p"], "Firmware")
    dest = tmp_path / "board" / "door-bell"
    t = dp.save_target(ws["P"], ws["p"], {"block": board(ws), "path": str(dest),
                                          "restart": f"echo restarted > {dest}/restarted.txt", "log": f"cat {dest}/restarted.txt"})
    got = dp.deploy(ws["P"], ws["p"], t["id"])
    assert got["ok"] and not got["dirty"], got
    assert (dest / "main.py").read_text() == "print('ding')\n" and (dest / "generated" / "pins.py").exists()
    assert got["steps"][-1] == {"step": "log", "ok": True, "out": "restarted\n"}
    ttl = ws["P"].export(ws["p"])
    assert "deployedCommit" in ttl and got["commit"] in ttl
    assert dp.targets(ws["P"], ws["p"])[0]["last"]["ok"] is True
    (dest / "old.py").write_text("x")                              # a file the next deployment removes
    dp.deploy(ws["P"], ws["p"], t["id"])
    assert not (dest / "old.py").exists() and (dest / dp.MARKER).exists()


def test_a_folder_that_is_not_ours_is_never_written(ws, tmp_path):  # noqa: F811
    gr.link(ws["P"], ws["p"])
    home = tmp_path / "someones-home"
    home.mkdir()
    (home / "thesis.txt").write_text("precious")
    t = dp.save_target(ws["P"], ws["p"], {"block": board(ws), "path": str(home)})
    got = dp.deploy(ws["P"], ws["p"], t["id"])
    assert not got["ok"] and "no deployment put there" in got["steps"][-1]["out"]
    assert (home / "thesis.txt").read_text() == "precious"
    assert "deployedCommit" not in ws["P"].export(ws["p"])


def test_targets_are_checked(ws):  # noqa: F811
    b = board(ws)
    for bad in ({"block": "b-nothing00", "path": "~/x"}, {"block": b, "path": "~"}, {"block": b, "path": "/"},
                {"block": b, "path": "~/a b"}, {"block": b, "path": "~/../etc"}, {"block": b, "host": "pi;rm", "user": "pi", "path": "~/x"},
                {"block": b, "host": "door-pi.local", "user": "Root Me", "path": "~/x"}, {"block": b, "path": "~/x", "restart": "a\nb"}):
        with pytest.raises(ValueError):
            dp.save_target(ws["P"], ws["p"], bad)


def test_a_remote_target_goes_over_ssh_with_the_persons_key(ws, monkeypatch):  # noqa: F811
    gr.link(ws["P"], ws["p"])
    calls = []
    monkeypatch.setattr(dp, "run", lambda args, timeout=0: calls.append(args) or ("OK\n" if "mkdir" in args[-1] else "active\n"))
    t = dp.save_target(ws["P"], ws["p"], {"block": board(ws), "host": "door-pi.local", "user": "pi", "path": "~/door-bell",
                                          "restart": "systemctl --user restart door-bell", "log": "journalctl --user -u door-bell -n 20"})
    got = dp.deploy(ws["P"], ws["p"], t["id"])
    assert got["ok"]
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-p", "22", "pi@door-pi.local"]
    assert calls[0][:8] == ssh and '"$HOME"/' in calls[0][8]
    assert calls[1][0] == "rsync" and calls[1][-1] == "pi@door-pi.local:door-bell/" and "BatchMode=yes" in calls[1][calls[1].index("-e") + 1]
    assert calls[2] == ssh + ["systemctl --user restart door-bell"] and calls[3] == ssh + ["journalctl --user -u door-bell -n 20"]


def test_the_chat_may_deploy_but_never_set_a_target():
    import re
    from maker_5_edge.edge import settings
    allowed = lambda m, path: any(mm == m and re.fullmatch(rx, path) for mm, rx in settings.CHAT_ALLOWED)  # noqa: E731
    assert allowed("POST", "/api/products/p-abc/deploy/t-0123abcd")
    assert not allowed("POST", "/api/products/p-abc/deploy/targets")
