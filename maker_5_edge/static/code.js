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
      <div class="code">
        <aside class="code-files"><ul>${list.map((f) => `<li><button type="button" class="linkish${f.path === C.file ? " is-on" : ""}" data-file="${esc(f.path)}">
          ${esc(f.path)}</button>${changed.has(f.path) || [...changed].some((c) => c.endsWith("/") && f.path.startsWith(c)) ? ' <span class="pill">±</span>' : ""}</li>`).join("")}</ul>
          <button class="code-new" data-help="help.code.new">${esc(t("code.new"))}</button></aside>
        <div class="code-view"><p class="note">${esc(t("code.pick"))}</p></div>
      </div>
      <p class="note">${esc(t("code.public"))}</p>`;
    box.querySelectorAll("[data-file]").forEach((b) => b.onclick = () => { C.file = b.dataset.file; show(box, list); });
    box.querySelector(".code-pull").onclick = async () => { if (await api("POST", `${base}/repo/pull`)) { core.toast(t("code.pulled")); draw(base, ws, true); } };
    box.querySelector(".code-push").onclick = () => review();
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
          : `<span class="note">${esc(got.path.startsWith("hardware/") ? t("code.fromModel") : "")}</span>`}</div>
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

  window.codeView = { draw };
})();
