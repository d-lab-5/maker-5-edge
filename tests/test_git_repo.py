# SPDX-License-Identifier: GPL-3.0-or-later
"""A workspace's repository (ADR-0017 in maker-5-shared), against a local bare
repository; gh is faked, nothing reaches GitHub."""

from __future__ import annotations

import subprocess

import pytest

from maker_5_edge import app as web
from maker_5_edge import git_repo as gr
from maker_5_edge import materials as mt
from maker_5_edge import products as pr


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKER5_EDGE_EDGE_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    for k, v in (("GIT_AUTHOR_NAME", "Example Maker"), ("GIT_AUTHOR_EMAIL", "maker@example.org"),
                 ("GIT_COMMITTER_NAME", "Example Maker"), ("GIT_COMMITTER_EMAIL", "maker@example.org")):
        monkeypatch.setenv(k, v)
    remote = tmp_path / "remote.git"
    calls = []

    def gh(*args, timeout=0):
        calls.append(args)
        if args[:2] == ("repo", "view"):
            if remote.exists():
                return '{"name":"x"}'
            raise gr.RepoError("Could not resolve to a Repository")
        if args[:2] == ("repo", "create"):
            sh("git", "init", "--quiet", "--bare", "-b", "main", str(remote))
            seed = tmp_path / "seed"
            sh("git", "clone", "--quiet", str(remote), str(seed))
            (seed / "LICENSE").write_text("GNU GENERAL PUBLIC LICENSE\nVersion 3\n")
            sh("git", "add", "-A", cwd=seed)
            sh("git", "commit", "--quiet", "-m", "Initial commit", cwd=seed)
            sh("git", "push", "--quiet", "origin", "main", cwd=seed)
            return ""
        if args[:2] == ("api", "user"):
            return "example-user\n"
        raise AssertionError(args)
    monkeypatch.setattr(gr, "gh", gh)
    # the remote is a GitHub address, which git reads from the local bare repository
    (tmp_path / ".gitconfig").write_text(f'[url "{remote}/"]\n\tinsteadOf = https://github.com/maker-5-platform/door-bell.git/\n'
                                         f'[url "{remote}"]\n\tinsteadOf = https://github.com/maker-5-platform/door-bell.git\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / ".gitconfig"))
    monkeypatch.setattr(gr.shutil, "which", lambda name: None if name == "gh" else "/usr/bin/" + name)
    reported = []
    monkeypatch.setattr(mt, "product_space", lambda products, p, profile=None: {"id": "s-aaaaaaaaaa"})
    monkeypatch.setattr(gr.cloud, "call", lambda path, body, profile=None: reported.append((path, body)) or {"status": "ok"})

    P = pr.Products()
    p = P.new_product("Door bell")["product"]
    a = P.add_block(p, "Example board")["id"]
    b = P.add_block(p, "Example opto")["id"]
    P.link_article(p, a, "a-2222222222", 2)
    P.place(p, a, 0, 0, [{"n": 1, "name": "GPIO17", "role": "signal"}, {"n": 2, "name": "GND", "role": "ground"}])
    P.place(p, b, 300, 0, [{"n": 1, "name": "Out", "role": "signal"}, {"n": 2, "name": "GND", "role": "ground"}])
    c = P.canvas(p)
    pins = {x["name"] + "@" + blk["id"]: x["id"] for blk in c["blocks"] for x in blk["pins"]}
    P.add_wire(p, pins[f"GPIO17@{a}"], pins[f"Out@{b}"], "yellow")
    return {"P": P, "p": p, "remote": remote, "calls": calls, "reported": reported, "tmp": tmp_path}


def test_not_linked_says_where_it_would_go(ws):
    st = gr.status(ws["P"], ws["p"])
    assert not st["linked"] and st["suggested"] == "maker-5-platform/door-bell"
    assert st["github"] == {"installed": True, "login": "example-user"}


def test_link_makes_the_repository_and_its_layout_but_pushes_nothing(ws):
    st = gr.link(ws["P"], ws["p"])
    assert ("repo", "create", "maker-5-platform/door-bell", "--public", "--license", "gpl-3.0") == ws["calls"][1][:6]
    d = gr.repo_dir(ws["P"], ws["p"])
    for f in ("README.md", "LICENSE", "LICENSE-hardware", ".gitignore", "NOTICE", "software/README.md",
              "hardware/model.ttl", "hardware/wiring.svg", "hardware/netlist.md", "hardware/bom.md"):
        assert (d / f).exists(), f
    assert st["linked"] and st["branch"] == "main" and st["changes"], "scaffolded, not committed"
    assert st["repo"] == "maker-5-platform/door-bell" and st["url"] == "https://github.com/maker-5-platform/door-bell"
    assert sh("git", "--git-dir", str(ws["remote"]), "rev-list", "--count", "main").strip() == "1"
    with pytest.raises(gr.RepoError, match="linked already"):
        gr.link(ws["P"], ws["p"])


def test_the_public_model_keeps_no_stock_and_the_netlist_has_the_wire(ws):
    gr.link(ws["P"], ws["p"])
    d = gr.repo_dir(ws["P"], ws["p"])
    ttl = (d / "hardware/model.ttl").read_text()
    assert "Example board" in ttl and "GPIO17" in ttl
    assert "usesArticle" not in ttl and "a-2222222222" not in ttl and "quantity" not in ttl
    assert "Example board · GPIO17 (1)" in (d / "hardware/netlist.md").read_text()
    assert (d / "hardware/wiring.svg").read_text().startswith("<svg") and "yellow" in (d / "hardware/wiring.svg").read_text()


def test_push_commits_pushes_and_tells_the_cloud(ws):
    gr.link(ws["P"], ws["p"])
    with pytest.raises(ValueError):
        gr.push(ws["P"], ws["p"], "  ")
    got = gr.push(ws["P"], ws["p"], "First design")
    assert got["changes"] == [] and got["ahead"] == 0 and got["reported"] == "ok"
    assert sh("git", "--git-dir", str(ws["remote"]), "log", "-1", "--format=%s", "main").strip() == "First design"
    path, body = ws["reported"][-1]
    assert path == "repo" and body["name"] == "s-aaaaaaaaaa" and len(body["commit"]) == 40


def test_the_guard_stops_secrets_and_addresses(ws):
    gr.link(ws["P"], ws["p"])
    gr.write(ws["P"], ws["p"], "software/config.py", 'TOKEN = "ghp_' + "a" * 36 + '"\n')
    with pytest.raises(gr.RepoError, match="GitHub token"):
        gr.push(ws["P"], ws["p"], "With a token")
    assert sh("git", "--git-dir", str(ws["remote"]), "rev-list", "--count", "main").strip() == "1", "nothing sent"
    gr.write(ws["P"], ws["p"], "software/config.py", "# ask a.person@private.example.net\n")
    with pytest.raises(gr.RepoError, match="e-mail"):
        gr.push(ws["P"], ws["p"], "With an address")
    gr.write(ws["P"], ws["p"], "software/config.py", "# maker@example.org is fine\n")
    assert gr.push(ws["P"], ws["p"], "Clean")["reported"] == "ok"


def test_only_software_is_written_and_only_inside(ws):
    gr.link(ws["P"], ws["p"])
    for bad in ("hardware/model.ttl", "README.md", "../x", "software/../../x", ".git/config", "software/cloud.json"):
        with pytest.raises(ValueError):
            gr.write(ws["P"], ws["p"], bad, "x")
    gr.write(ws["P"], ws["p"], "software/door/main.py", "print('ding')\n")
    assert gr.read(ws["P"], ws["p"], "software/door/main.py")["text"] == "print('ding')\n"
    assert any(f["path"] == "software/door/main.py" and f["writable"] for f in gr.files(ws["P"], ws["p"]))


def test_a_push_behind_github_asks_for_a_pull(ws):
    gr.link(ws["P"], ws["p"])
    gr.push(ws["P"], ws["p"], "First design")
    other = ws["tmp"] / "other"
    sh("git", "clone", "--quiet", str(ws["remote"]), str(other))
    (other / "software" / "notes.md").write_text("from elsewhere\n")
    sh("git", "add", "-A", cwd=other)
    sh("git", "commit", "--quiet", "-m", "Elsewhere", cwd=other)
    sh("git", "push", "--quiet", "origin", "main", cwd=other)
    gr.write(ws["P"], ws["p"], "software/a.py", "x = 1\n")
    with pytest.raises(gr.RepoError, match="Pull first"):
        gr.push(ws["P"], ws["p"], "Mine")
    sh("git", "-C", str(gr.repo_dir(ws["P"], ws["p"])), "reset", "--quiet", "--soft", "HEAD~1")
    sh("git", "-C", str(gr.repo_dir(ws["P"], ws["p"])), "stash", "--quiet", "-u")
    assert gr.pull(ws["P"], ws["p"])["behind"] == 0
    assert (gr.repo_dir(ws["P"], ws["p"]) / "software" / "notes.md").exists()


def test_the_routes(ws):
    web._products = ws["P"]
    try:
        c = web.app.test_client()
        assert c.get(f"/api/products/{ws['p']}/repo").get_json()["linked"] is False
        assert c.post(f"/api/products/{ws['p']}/repo/push", json={"message": "x"}).status_code == 409
        assert c.post(f"/api/products/{ws['p']}/repo/link", json={}).get_json()["linked"] is True
        d = c.get(f"/api/products/{ws['p']}/repo/diff").get_json()
        assert "hardware/model.ttl" in d["patch"] and d["findings"] == []
        assert c.post(f"/api/products/{ws['p']}/repo/file", json={"path": "hardware/x", "text": "x"}).status_code == 400
    finally:
        web._products = None


def test_the_model_had_the_stock_link_the_public_one_drops(ws):
    assert "a-2222222222" in ws["P"].export(ws["p"]), "the private model keeps it"


def test_a_remote_that_is_not_github_is_shown_as_it_is(ws, monkeypatch):
    monkeypatch.setattr(gr, "clone_url", lambda full: str(ws["remote"]))
    st = gr.link(ws["P"], ws["p"])
    assert st["repo"] == str(ws["remote"]) and st["url"] == str(ws["remote"])
    assert gr._report(ws["P"], ws["p"], st) == "not a GitHub repository"


def test_a_model_change_on_github_waits_to_be_brought_in(ws):
    gr.link(ws["P"], ws["p"])
    gr.push(ws["P"], ws["p"], "First design")
    other = ws["tmp"] / "other"
    sh("git", "clone", "--quiet", "https://github.com/maker-5-platform/door-bell.git", str(other))
    f = other / "hardware" / "model.ttl"
    f.write_text(f.read_text().replace('"Example opto"', '"Example optocoupler"'))
    sh("git", "add", "-A", cwd=other)
    sh("git", "commit", "--quiet", "-m", "Rename the opto", cwd=other)
    sh("git", "push", "--quiet", "origin", "main", cwd=other)
    st = gr.pull(ws["P"], ws["p"])
    assert st["incoming"] is True
    inc = gr.incoming(ws["P"], ws["p"])
    assert inc["commits"][0]["subject"] == "Rename the opto"
    assert any(x[2] == "Example optocoupler" for x in inc["added"]) and any(x[2] == "Example opto" for x in inc["removed"])
    with pytest.raises(gr.RepoError, match="changed on GitHub"):
        gr.push(ws["P"], ws["p"], "Would overwrite")
    got = gr.take_incoming(ws["P"], ws["p"])
    assert got["incoming"] is False and (got["added"], got["removed"]) == (1, 1)
    assert "Example optocoupler" in [b["name"] for b in ws["P"].model(ws["p"])["blocks"]]
    assert gr.push(ws["P"], ws["p"], "Took the rename")["reported"] == "ok"


def test_dropping_github_changes_keeps_the_model(ws):
    gr.link(ws["P"], ws["p"])
    gr.push(ws["P"], ws["p"], "First design")
    other = ws["tmp"] / "other"
    sh("git", "clone", "--quiet", "https://github.com/maker-5-platform/door-bell.git", str(other))
    f = other / "hardware" / "model.ttl"
    f.write_text(f.read_text().replace('"Example opto"', '"Something else"'))
    sh("git", "commit", "--quiet", "-am", "Rename", cwd=other)
    sh("git", "push", "--quiet", "origin", "main", cwd=other)
    gr.pull(ws["P"], ws["p"])
    gr.drop_incoming(ws["P"], ws["p"])
    gr.push(ws["P"], ws["p"], "Keep ours")
    assert '"Example opto"' in (gr.repo_dir(ws["P"], ws["p"]) / "hardware" / "model.ttl").read_text()


def test_the_pin_map_follows_the_wiring_and_the_code_is_checked(ws):
    gr.link(ws["P"], ws["p"])
    d = gr.repo_dir(ws["P"], ws["p"])
    pm = gr.pin_map(ws["P"], ws["p"])
    board = next(b for b in pm["boards"] if b["name"] == "Example board")
    assert board["pins"][0]["gpio"] == 17 and board["pins"][0]["const"] == "EXAMPLE_OPTO_OUT"
    py = (d / "software/generated/pins.py").read_text()
    assert "class ExampleBoard:" in py and "EXAMPLE_OPTO_OUT = 17" in py
    ns: dict = {}
    exec(compile(py, "pins.py", "exec"), ns)                 # it is valid Python
    assert ns["ExampleBoard"].EXAMPLE_OPTO_OUT == 17
    with pytest.raises(ValueError, match="generated"):
        gr.write(ws["P"], ws["p"], "software/generated/pins.py", "x")
    gr.write(ws["P"], ws["p"], "software/main.py", "from gpiozero import Button\nb = Button(17)\nled = LED(pin=22)\n")
    assert gr.diff(ws["P"], ws["p"])["pin_warnings"] == [{"path": "software/main.py", "line": 3, "gpio": 22}]


def test_gpio_numbers_from_pin_names():
    assert [gr._gpio(n) for n in ("GPIO17", "GPIO 17", "GPIO 14/TXD", "IO5", "D4", "GND")] == [17, 17, 14, 5, None, None]


def test_pictures_go_to_hardware_images_and_are_credited(ws):
    P, p = ws["P"], ws["p"]
    blocks = {b["name"]: b["id"] for b in P.model(p)["blocks"]}
    opto = blocks["Example opto"]
    P.use_image(p, opto, "drawn")
    gr.link(P, p)
    d = gr.repo_dir(P, p)
    assert (d / "hardware" / "images" / f"{opto}.svg").read_bytes().startswith(b"<svg")
    assert "drawn for this design" in (d / "NOTICE").read_text() and "Example opto" in (d / "NOTICE").read_text()
    led = P.add_block(p, "Spare LED")["id"]
    P.use_image(p, led, "wokwi", "led", [{"n": 1, "name": "A", "role": "signal"}, {"n": 2, "name": "C", "role": "signal"}])
    gr.prepare(P, p)
    notice = (d / "NOTICE").read_text()
    assert "Wokwi elements" in notice and "LED (led)" in notice and "MIT" in notice
    assert (d / "hardware" / "images" / f"{led}.svg").exists()


def test_linking_an_existing_repository_brings_its_design_into_an_empty_workspace(ws):
    gr.link(ws["P"], ws["p"])
    gr.push(ws["P"], ws["p"], "First design")
    fresh = ws["P"].new_product("Door bell again")["product"]
    st = gr.link(ws["P"], fresh, "maker-5-platform/door-bell")
    assert st["imported"]["brings"]["blocks"] == 2 and st["imported"]["brings"]["wires"] == 1
    model = ws["P"].model(fresh)
    assert sorted(b["name"] for b in model["blocks"]) == ["Example board", "Example opto"]
    assert not any(b["article"] for b in model["blocks"]), "stock links never travel"
    published = (gr.repo_dir(ws["P"], fresh) / "hardware" / "model.ttl").read_text()
    assert "Example opto" in published, "the repository's design is not written over with an empty model"


def test_a_readme_names_the_site_at_its_address(ws):
    gr.link(ws["P"], ws["p"])
    readme = (gr.repo_dir(ws["P"], ws["p"]) / "README.md").read_text()
    assert "https://maker5.cloud" in readme and "maker-5.cloud" not in readme
