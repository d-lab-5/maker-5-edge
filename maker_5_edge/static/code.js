/* SPDX-License-Identifier: GPL-3.0-or-later
 * The Code tab (ADR-0017 in maker-5-shared): the workspace's repository on
 * GitHub. Link it, read its files, edit what is under software/, review what
 * a push publishes (hardware/ is written from the model first) and push it
 * with your own GitHub login. The cloud keeps only the link.
 */
(() => {
  "use strict";
  const esc = (s) => core.esc(String(s ?? ""));
  const t = (k, v) => window.i18n.t(k, v);
  const failed = (err) => (err && err.errors) ? err.errors.join("; ") : t("failed");
  const C = { base: "", ws: "", key: "", file: "", editing: false };

  async function api(method, path, payload) {
    try { return await core.api(method, path, payload); } catch (err) { core.toast(failed(err), true); return null; }
  }

  async function draw(base, ws, force) {
    const box = document.getElementById("tab-code");
    if (!box) return;
    if (!ws) { box.innerHTML = `<p class="note">${esc(t("model.choose"))}</p>`; C.key = ""; return; }
    if (C.editing && C.ws === ws && !force) return;                 // never under the person's hand
    const st = await core.api("GET", `${base}/repo`);
    const key = ws + JSON.stringify(st) + C.file;
    if (key === C.key && !force) return;
    if (C.ws !== ws) C.file = "";
    Object.assign(C, { base, ws, key });
    if (!st.linked) return drawUnlinked(box, st);
    const list = await core.api("GET", `${base}/repo/files`).catch(() => []);
    const changed = new Set(st.changes.map((c) => c.path));
    box.innerHTML = `
      <div class="code-bar">
        <span>GitHub: <a href="${esc(st.url)}" target="_blank" rel="noopener noreferrer"><strong>${esc(st.repo)}</strong></a>
          <span class="note">· ${esc(st.branch)}${st.last ? ` @ ${esc(st.last.commit.slice(0, 7))}` : ""}</span></span>
        <span class="note">${esc(t("code.changes", { n: st.changes.length }))}${st.ahead ? " · " + esc(t("code.ahead", { n: st.ahead })) : ""}${st.behind ? " · " + esc(t("code.behind", { n: st.behind })) : ""}</span>
        <button class="code-pull" data-help="help.code.pull">${esc(t("code.pull"))}</button>
        <button class="code-push primary" data-help="help.code.push">${esc(t("code.review"))}</button>
      </div>
      ${st.incoming ? `<div class="warn code-incoming"><strong>${esc(t("code.incoming"))}</strong>
        <button class="code-in-show" data-help="help.code.incoming">${esc(t("code.incomingShow"))}</button></div>` : ""}
      <div class="code">
        <aside class="code-files"><ul>${list.map((f) => `<li><button type="button" class="linkish${f.path === C.file ? " is-on" : ""}" data-file="${esc(f.path)}">
          ${esc(f.path)}</button>${changed.has(f.path) || [...changed].some((c) => c.endsWith("/") && f.path.startsWith(c)) ? ' <span class="pill">±</span>' : ""}</li>`).join("")}</ul>
          <button class="code-new" data-help="help.code.new">${esc(t("code.new"))}</button></aside>
        <div class="code-view"><p class="note">${esc(t("code.pick"))}</p></div>
      </div>
      <p class="note">${esc(t("code.public"))}</p>
      <section class="code-boards"></section>`;
    boards(box.querySelector(".code-boards"));
    box.querySelectorAll("[data-file]").forEach((b) => b.onclick = () => { C.file = b.dataset.file; show(box, list); });
    box.querySelector(".code-pull").onclick = async () => { if (await api("POST", `${base}/repo/pull`)) { core.toast(t("code.pulled")); draw(base, ws, true); } };
    box.querySelector(".code-push").onclick = () => review();
    const inc = box.querySelector(".code-in-show");
    if (inc) inc.onclick = () => incoming();
    box.querySelector(".code-new").onclick = () => edit({ path: "software/", text: "" }, true);
    if (C.file) show(box, list);
  }

  function drawUnlinked(box, st) {
    const gh = st.github || {};
    const ready = gh.installed && gh.login;
    box.innerHTML = `
      <div class="code-intro">
        <h3>${esc(t("code.notLinked"))}</h3>
        <p>${esc(t("code.what"))}</p>
        <p class="note">${esc(ready ? t("code.as", { login: gh.login }) : gh.installed ? t("code.signIn") : t("code.install"))}</p>
        <p><button class="primary code-link" ${ready ? "" : "disabled"} data-help="help.code.link">${esc(t("code.link"))}</button>
          <span class="note">${esc(t("code.willMake", { repo: st.suggested, visibility: st.visibility }))}</span></p>
        <p><button class="code-existing" ${ready ? "" : "disabled"} data-help="help.code.existing">${esc(t("code.existing"))}</button></p>
      </div>`;
    box.querySelector(".code-link").onclick = () => core.dialog(t("code.link"), `
      <p>${esc(t("code.confirm", { repo: st.suggested, visibility: st.visibility }))}</p>
      <div class="actions"><button value="cancel" formnovalidate>${esc(t("model.cancel"))}</button>
        <button value="ok" class="primary">${esc(t("code.link"))}</button></div>`, (form, dlg) => {
      form.onsubmit = async (ev) => {
        form.onsubmit = null;
        if (!ev.submitter || ev.submitter.value !== "ok") return;
        ev.preventDefault(); dlg.close();
        if (await api("POST", `${C.base}/repo/link`, {})) { core.toast(t("code.linked")); draw(C.base, C.ws, true); }
      };
    });
    box.querySelector(".code-existing").onclick = () => core.dialog(t("code.existing"), `
      <label>${esc(t("code.existingRepo"))} <input name="repo" required placeholder="owner/name"></label>
      <div class="actions"><button value="cancel" formnovalidate>${esc(t("model.cancel"))}</button>
        <button value="ok" class="primary">${esc(t("code.link"))}</button></div>`, (form, dlg) => {
      form.onsubmit = async (ev) => {
        form.onsubmit = null;
        if (!ev.submitter || ev.submitter.value !== "ok") return;
        ev.preventDefault(); dlg.close();
        if (await api("POST", `${C.base}/repo/link`, { existing: form.querySelector('[name="repo"]').value })) draw(C.base, C.ws, true);
      };
    });
  }

  async function show(box, list) {
    const view = box.querySelector(".code-view");
    box.querySelectorAll("[data-file]").forEach((b) => b.classList.toggle("is-on", b.dataset.file === C.file));
    const f = list.find((x) => x.path === C.file);
    if (!f) { view.innerHTML = ""; return; }
    view.innerHTML = `<p class="note">…</p>`;
    const got = await api("GET", `${C.base}/repo/file?path=${encodeURIComponent(C.file)}`);
    if (!got) { view.innerHTML = ""; return; }
    view.innerHTML = `<div class="code-head"><strong>${esc(got.path)}</strong>
        ${f.writable ? `<button class="code-edit" data-help="help.code.edit">${esc(t("code.edit"))}</button>`
          : `<span class="note">${esc(got.path.startsWith("hardware/") || got.path.startsWith("software/generated/") ? t("code.fromModel") : "")}</span>`}</div>
      <pre class="code-text">${esc(got.text)}</pre>`;
    const e = view.querySelector(".code-edit");
    if (e) e.onclick = () => edit(got, false);
  }

  function edit(file, isNew) {
    C.editing = true;
    core.dialog(isNew ? t("code.new") : file.path, `
      ${isNew ? `<label>${esc(t("code.path"))} <input name="path" required value="${esc(file.path)}"></label>` : ""}
      <textarea name="text" rows="22" spellcheck="false" class="code-area">${esc(file.text)}</textarea>
      <p class="note">${esc(t("code.public"))}</p>
      <div class="actions"><button value="cancel" formnovalidate>${esc(t("model.cancel"))}</button>
        <button value="ok" class="primary">${esc(t("model.save"))}</button></div>`, (form, dlg) => {
      dlg.addEventListener("close", () => { C.editing = false; }, { once: true });
      form.onsubmit = async (ev) => {
        form.onsubmit = null;
        if (!ev.submitter || ev.submitter.value !== "ok") return;
        ev.preventDefault();
        const path = isNew ? form.querySelector('[name="path"]').value : file.path;
        const ok = await api("POST", `${C.base}/repo/file`, { path, text: form.querySelector('[name="text"]').value });
        dlg.close();
        if (ok) { C.file = ok.path; core.toast(t("code.saved")); draw(C.base, C.ws, true); }
      };
    });
  }

  async function review() {
    const d = await api("GET", `${C.base}/repo/diff`);
    if (!d) return;
    const bad = d.findings.length > 0;
    core.dialog(t("code.review"), `
      ${bad ? `<div class="warn"><strong>${esc(t("code.found"))}</strong><ul>${d.findings.map((f) =>
        `<li>${esc(f.path)}: ${esc(f.what)}</li>`).join("")}</ul></div>` : ""}
      ${(d.pin_warnings || []).length ? `<div class="warn"><strong>${esc(t("code.pinWarn"))}</strong><ul>${d.pin_warnings.map((w) =>
        `<li>${esc(w.path)}:${w.line}: GPIO ${w.gpio}</li>`).join("")}</ul></div>` : ""}
      <pre class="code-text code-diff">${esc(d.patch || t("code.nothing"))}${d.cut ? "\n…" : ""}</pre>
      <label>${esc(t("code.message"))} <input name="message" required maxlength="2000" placeholder="${esc(t("code.messageHint"))}"></label>
      <p class="note">${esc(t("code.publicPush", { repo: d.repo }))}</p>
      <div class="actions"><button value="cancel" formnovalidate>${esc(t("model.cancel"))}</button>
        <button value="ok" class="primary" ${bad ? "disabled" : ""}>${esc(t("code.push"))}</button></div>`, (form, dlg) => {
      form.onsubmit = async (ev) => {
        form.onsubmit = null;
        if (!ev.submitter || ev.submitter.value !== "ok") return;
        ev.preventDefault(); dlg.close();
        const got = await api("POST", `${C.base}/repo/push`, { message: form.querySelector('[name="message"]').value });
        if (got) {
          core.toast(got.reported === "ok" ? t("code.pushed") : t("code.pushedNoCloud", { why: got.reported }), got.reported !== "ok");
          draw(C.base, C.ws, true);
        }
      };
    });
  }

  /** What others changed in hardware/model.ttl on GitHub: bring it in, or keep the model. */
  async function incoming() {
    const d = await api("GET", `${C.base}/repo/incoming`);
    if (!d) return;
    const rows = (list, sign) => list.map((x) => `<li><code>${sign} ${esc(x.join("  "))}</code></li>`).join("");
    core.dialog(t("code.incoming"), `
      <p class="note">${esc(t("code.incomingWhy"))}</p>
      <ul class="code-commits">${d.commits.map((c) => `<li>${esc(c.subject)} <span class="note">· ${esc(c.author)} · ${esc(c.commit.slice(0, 7))}</span></li>`).join("")}</ul>
      <ul class="code-triples">${rows(d.added, "+")}${rows(d.removed, "−")}</ul>
      <div class="actions"><button value="drop" class="danger" formnovalidate>${esc(t("code.incomingDrop"))}</button>
        <button value="cancel" formnovalidate>${esc(t("model.cancel"))}</button>
        <button value="ok" class="primary">${esc(t("code.incomingTake"))}</button></div>`, (form, dlg) => {
      form.onsubmit = async (ev) => {
        form.onsubmit = null;
        const v = ev.submitter && ev.submitter.value;
        if (v === "cancel") return;
        ev.preventDefault(); dlg.close();
        const got = await api("POST", `${C.base}/repo/incoming/${v === "ok" ? "take" : "drop"}`);
        if (got) { core.toast(v === "ok" ? t("code.incomingTaken", { added: got.added, removed: got.removed }) : t("code.incomingDropped")); draw(C.base, C.ws, true); }
      };
    });
  }

  /** The boards software/ is deployed to (deploy.py): set up here only, deployed from here or by the chat. */
  async function boards(sec) {
    const list = await core.api("GET", `${C.base}/deploy`).catch(() => []);
    const where = (x) => x.host ? `${x.user}@${x.host}${x.port !== 22 ? ":" + x.port : ""}:${x.path}` : `${t("dep.here")}: ${x.path}`;
    sec.innerHTML = `<h3>${esc(t("dep.title"))}</h3><p class="note">${esc(t("dep.hint"))}</p>
      ${list.length ? `<ul class="dep-list">${list.map((x) => `<li><strong>${esc(x.block_name)}</strong> <span class="note">${esc(where(x))}</span>
        ${x.last ? `<span class="pill${x.last.ok ? "" : " warn"}">${esc(x.last.ok ? t("dep.lastOk", { commit: x.last.commit.slice(0, 7), when: x.last.at.slice(0, 16).replace("T", " ") }) : t("dep.lastFailed"))}${x.last.dirty ? " · " + esc(t("dep.dirty")) : ""}</span>` : ""}
        <button class="primary" data-deploy="${esc(x.id)}" data-help="help.dep.run">${esc(t("dep.run"))}</button>
        <button data-dedit="${esc(x.id)}">${esc(t("code.edit"))}</button>
        <button class="danger" data-ddrop="${esc(x.id)}">${esc(t("dep.remove"))}</button></li>`).join("")}</ul>` : ""}
      <button class="dep-add" data-help="help.dep.add">${esc(t("dep.add"))}</button>`;
    sec.querySelector(".dep-add").onclick = () => target({});
    sec.querySelectorAll("[data-dedit]").forEach((b) => b.onclick = () => target(list.find((x) => x.id === b.dataset.dedit)));
    sec.querySelectorAll("[data-ddrop]").forEach((b) => b.onclick = async () => {
      if (await api("DELETE", `${C.base}/deploy/targets/${encodeURIComponent(b.dataset.ddrop)}`)) boards(sec);
    });
    sec.querySelectorAll("[data-deploy]").forEach((b) => b.onclick = async () => {
      b.disabled = true; b.textContent = "…";
      const got = await api("POST", `${C.base}/deploy/${encodeURIComponent(b.dataset.deploy)}`);
      boards(sec);
      if (!got) return;
      core.dialog(got.ok ? t("dep.done") : t("dep.failed"), `
        <p class="note">${esc(t("dep.commit", { commit: got.commit.slice(0, 7) }))}${got.dirty ? " · " + esc(t("dep.dirty")) : ""}</p>
        ${got.steps.map((st) => `<h4>${esc(t(`dep.step.${st.step}`))} ${st.ok ? "✓" : "✗"}</h4>${st.out ? `<pre class="code-text">${esc(st.out)}</pre>` : ""}`).join("")}
        <div class="actions"><button value="ok" class="primary">${esc(t("dep.close"))}</button></div>`);
    });
  }

  async function target(x) {
    const m = await core.api("GET", C.base);
    const sec = document.querySelector("#tab-code .code-boards");
    core.dialog(x.id ? t("dep.editTitle") : t("dep.add"), `
      <label>${esc(t("dep.board"))} <select name="block">${m.blocks.map((b) => `<option value="${esc(b.id)}" ${b.id === x.block ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select></label>
      <label>${esc(t("dep.host"))} <input name="host" value="${esc(x.host || "")}" placeholder="door-pi.local"></label>
      <label>${esc(t("dep.user"))} <input name="user" value="${esc(x.user || "")}" placeholder="pi"></label>
      <label>${esc(t("dep.port"))} <input name="port" type="number" min="1" max="65535" value="${esc(x.port || 22)}"></label>
      <label>${esc(t("dep.path"))} <input name="path" required value="${esc(x.path || "~/" + (m.product.title || "app").toLowerCase().replace(/[^a-z0-9]+/g, "-"))}"></label>
      <label>${esc(t("dep.restart"))} <input name="restart" value="${esc(x.restart || "")}" placeholder="systemctl --user restart door-bell"></label>
      <label>${esc(t("dep.log"))} <input name="log" value="${esc(x.log || "")}" placeholder="journalctl --user -u door-bell -n 40 --no-pager"></label>
      <p class="note">${esc(t("dep.keys"))}</p>
      <div class="actions"><button value="cancel" formnovalidate>${esc(t("model.cancel"))}</button>
        <button value="ok" class="primary">${esc(t("model.save"))}</button></div>`, (form, dlg) => {
      form.onsubmit = async (ev) => {
        form.onsubmit = null;
        if (!ev.submitter || ev.submitter.value !== "ok") return;
        ev.preventDefault();
        const v = (n) => form.querySelector(`[name="${n}"]`).value;
        const ok = await api("POST", `${C.base}/deploy/targets`, { id: x.id, block: v("block"), host: v("host"), user: v("user"),
          port: Number(v("port")) || 22, path: v("path"), restart: v("restart"), log: v("log") });
        dlg.close();
        if (ok && sec) boards(sec);
      };
    });
  }

  window.codeView = { draw };
})();
