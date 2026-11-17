// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 D-LAB-5
//
// app.js — Maker-5 Edge: the products on this edge and the model in each.
// core.js wires the header (window.core: api, esc, toast, dialog); edge.js
// the chat and the connections. A model is changed mostly through the chat's
// confirmed proposals, so the page re-reads it every few seconds and redraws
// only when it changed. The shell (rail, tabs, help, busy, files on the chat)
// is digitalhome-pro-edge's.

"use strict";

const $ = (sel) => document.querySelector(sel);
const esc = (s) => core.esc(String(s ?? ""));
const t = (key, vars) => window.i18n.t(key, vars);
const word = (prefix, v) => t(`${prefix}.${v}`) === `${prefix}.${v}` ? v : t(`${prefix}.${v}`);
const when = (iso) => { try { return iso ? new Date(iso).toLocaleString(window.i18n.lang) : ""; } catch (_) { return iso || ""; } };
const failed = (err) => (err && err.errors) ? err.errors.join("; ") : t("failed");
const P = () => `/api/products/${encodeURIComponent(S.ws)}`;

const S = { ws: null, item: null, tab: "model", seen: {} };

// A loading indicator in the middle of the screen, for what the person
// started (a tab, a product); never for the background poll. It shows only
// when the wait is long enough to notice.
let busyN = 0, busyT = null;
function busyOn() {
  if (busyN++ === 0) busyT = setTimeout(() => { $("#busy").hidden = false; }, 150);
}
function busyOff() {
  if (busyN > 0 && --busyN === 0) { clearTimeout(busyT); $("#busy").hidden = true; }
}
async function busy(work) {
  busyOn();
  try { return await (typeof work === "function" ? work() : work); } finally { busyOff(); }
}

function hashState() {
  const h = new URLSearchParams(location.hash.slice(1));
  return { ws: h.get("p"), item: h.get("i") };
}

async function select(ws, item) {
  if (ws !== S.ws) Object.assign(S, { cmp: null, cmpFrom: null, cmpTo: null, tagging: "", restoring: "", adding: "" });
  S.ws = ws; S.item = item || null;
  history.replaceState(null, "", ws ? `#p=${encodeURIComponent(ws)}${item ? `&i=${encodeURIComponent(item)}` : ""}` : "#");
  try { await core.api("POST", "/api/selection", { product: ws || "", item: item || "" }); } catch (_) { /* fine */ }
  S.seen = {};
  busy(refresh);
}

// Run a change from the page; on success redraw, on failure say why.
async function change(method, path, payload, done) {
  try {
    const r = await core.api(method, path, payload);
    if (done) core.toast(done);
    return r;
  } catch (err) { core.toast(failed(err), true); return null; }
  finally { S.seen = {}; refresh(); }
}

// ----------------------------------------------------------- the list ----

async function drawList() {
  const list = await core.api("GET", "/api/products");
  const open = list.find((p) => p.product === S.ws);
  S.wsTitle = open ? open.title : "";
  const key = JSON.stringify(list) + S.ws;
  if (S.seen.list === key) return;
  S.seen.list = key;
  const box = $("#ws-list");
  if (!list.length) {
    box.innerHTML = `<p class="note">${esc(t("list.none"))}</p>`;
    return;
  }
  box.innerHTML = list.map((p) =>
    `<button data-ws="${esc(p.product)}" class="${p.product === S.ws ? "is-on" : ""}">
       <span>${esc(p.title)}</span>
       <small>${esc(t("list.counts", { b: p.blocks, m: p.modules }))}${p.open_proposals ? ` · ${esc(t("list.open", { n: p.open_proposals }))}` : ""}</small>
     </button>`).join("");
  box.querySelectorAll("button[data-ws]").forEach((b) => b.onclick = () => select(b.dataset.ws));
}

// ---------------------------------------------------------- the model ----

// The product's display name. Only the title changes: the id, and with it
// the folder mydocs/<id>/, stay as they are (ADR-0003).
function renameForm(head, title) {
  const form = document.createElement("form");
  form.className = "ws-head ws-rename-form";
  form.innerHTML = `<input name="title" required maxlength="120" value="${esc(title)}">
    <button class="primary">${esc(t("model.save"))}</button>
    <button type="button" class="cancel">${esc(t("model.cancel"))}</button>`;
  const back = () => { S.seen.model = null; refresh(); };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const value = form.title.value.trim();
    if (!value || value === title) return back();
    await change("POST", P(), { title: value }, t("model.renamed"));
  };
  form.querySelector(".cancel").onclick = back;
  form.title.onkeydown = (e) => { if (e.key === "Escape") back(); };
  head.replaceWith(form);
  form.title.focus();
  form.title.select();
}

function itemRow(x, sub) {
  return `<li data-item="${esc(x.id)}" class="${x.id === S.item ? "is-on" : ""}">
    <span>${esc(x.name)} ${sub || ""}</span>
    <span class="acts"><button class="rn" data-help="help.rename">${esc(t("model.rename"))}</button>
      <button class="rm danger" data-help="help.remove">${esc(t("model.remove"))}</button></span></li>`;
}

async function drawModel() {
  const box = $("#tab-model");
  if (!S.ws) { box.innerHTML = `<p class="note">${esc(t("model.choose"))}</p>`; return; }
  const m = await core.api("GET", P());
  const key = JSON.stringify(m) + S.item + S.adding;
  if (S.seen.model === key) return;
  if (box.contains(document.activeElement) && document.activeElement.matches("input, select, textarea")) return;  // not while typing
  S.seen.model = key;
  const ends = [...m.blocks, ...m.modules];
  const addForm = (what) => S.adding !== what ? `<button class="add" data-add="${what}" data-help="help.add.${what}">+ ${esc(t(`model.add.${what}`))}</button>` :
    `<form class="add-form" data-form="${what}">
      <input type="text" name="name" required maxlength="120" placeholder="${esc(t(`model.ph.${what}`))}">
      ${what === "block" ? `<select name="kind"><option value="">${esc(t("model.kind.none"))}</option>
         <option value="electronic">${esc(t("kind.electronic"))}</option><option value="mechanical">${esc(t("kind.mechanical"))}</option></select>` : ""}
      ${what === "interface" ? `<select name="connects" multiple required>${ends.map((e) =>
         `<option value="${esc(e.id)}">${esc(e.name)}</option>`).join("")}</select><small class="note">${esc(t("model.connectsHint"))}</small>` : ""}
      <button class="primary">${esc(t("model.addIt"))}</button> <button type="button" class="cancel">${esc(t("model.cancel"))}</button></form>`;
  box.innerHTML = `
    <div class="ws-head"><h2>${esc(m.product.title)}</h2>
      <button class="ws-rename" data-help="help.renameProduct">${esc(t("model.renameProduct"))}</button>
      <a class="btn" download href="${P()}/export.ttl" data-help="help.export">${esc(t("model.export"))}</a></div>
    <p class="sub">${esc(t("model.sub", { n: m.triples }))}</p>
    <div class="cols">
      <section class="card"><header><h3>${esc(t("model.blocks"))}</h3><small>${m.blocks.length}</small></header>
        <ul class="items">${m.blocks.map((b) => itemRow(b, b.kind ? `<span class="pill ${esc(b.kind)}">${esc(word("kind", b.kind))}</span>` : "")).join("")}</ul>
        ${addForm("block")}</section>
      <section class="card"><header><h3>${esc(t("model.modules"))}</h3><small>${m.modules.length}</small></header>
        <ul class="items">${m.modules.map((x) => itemRow(x)).join("")}</ul>
        ${addForm("module")}</section>
      <section class="card"><header><h3>${esc(t("model.interfaces"))}</h3><small>${m.interfaces.length}</small></header>
        <ul class="items">${m.interfaces.map((i) => itemRow(i, `<br><small>${i.connects.map((c) => esc(c.name)).join(" ↔ ")}</small>`)).join("")}</ul>
        ${ends.length >= 2 ? addForm("interface") : `<p class="note">${esc(t("model.needTwo"))}</p>`}</section>
    </div>`;
  box.querySelector(".ws-rename").onclick = (e) => renameForm(e.target.closest(".ws-head"), m.product.title);
  box.querySelectorAll("button.add").forEach((b) => b.onclick = () => { S.adding = b.dataset.add; S.seen.model = null; drawModel(); });
  box.querySelectorAll("form.add-form").forEach((f) => {
    f.name.focus();
    f.querySelector(".cancel").onclick = () => { S.adding = ""; S.seen.model = null; drawModel(); };
    f.onsubmit = async (e) => {
      e.preventDefault();
      const what = f.dataset.form;
      const payload = { name: f.name.value };
      if (f.kind && f.kind.value) payload.kind = f.kind.value;
      if (f.connects) payload.connects = [...f.connects.selectedOptions].map((o) => o.value);
      S.adding = "";
      await change("POST", `${P()}/${what}s`, payload);
    };
  });
  box.querySelectorAll("li[data-item]").forEach((li) => {
    const id = li.dataset.item;
    li.onclick = (e) => { if (!e.target.closest("button")) select(S.ws, S.item === id ? null : id); };
    li.querySelector(".rn").onclick = async () => {
      const name = li.querySelector("span").textContent.trim();
      core.dialog(t("model.rename"), `<label><input name="name" required maxlength="120" value="${esc(name)}"></label>
        <div class="actions"><button value="cancel" formnovalidate>${esc(t("model.cancel"))}</button>
        <button value="ok" class="primary">${esc(t("model.save"))}</button></div>`, (form, dlg) => {
        // the dialog's form is reused by every dialog: set the handler, never add one
        form.onsubmit = (ev) => {
          form.onsubmit = null;
          if (ev.submitter && ev.submitter.value === "cancel") return;
          ev.preventDefault(); dlg.close();
          const name = form.querySelector('input[name="name"]').value;
          change("POST", `${P()}/items/${encodeURIComponent(id)}/rename`, { name });
        };
        form.querySelector('input[name="name"]').select();
      });
    };
    li.querySelector(".rm").onclick = () => change("DELETE", `${P()}/items/${encodeURIComponent(id)}`, null, t("model.removed"));
  });
}

// ---------------------------------------------------------- proposals ----
// An agent's proposal waits for a person (ADR-0006): only this page decides one.

async function drawProposals() {
  const box = $("#tab-proposals");
  if (!S.ws) { box.innerHTML = `<p class="note">${esc(t("model.choose"))}</p>`; return; }
  const m = await core.api("GET", P());
  const key = JSON.stringify(m.proposals);
  if (S.seen.proposals === key) return;
  if (box.contains(document.activeElement) && document.activeElement.matches("input")) return;
  S.seen.proposals = key;
  const open = m.proposals.filter((p) => p.state === "proposed");
  const done = m.proposals.filter((p) => p.state !== "proposed");
  const card = (p) => `<article class="proposal ${esc(p.state)}" data-p="${esc(p.id)}">
    <header><b>${esc(p.title)}</b><span class="pill">${esc(word("state", p.state))}</span></header>
    <p class="meta">${esc(t("p.by", { who: p.by || "?", when: when(p.at) }))}${p.concerns.length ? " · " + esc(t("p.concerns", { list: p.concerns.map((c) => c.name).join(", ") })) : ""}</p>
    ${p.decided ? `<p class="meta">${esc(t("p.decided", { who: p.decided.by, when: when(p.decided.at) }))}${p.decided.note ? ` — “${esc(p.decided.note)}”` : ""}</p>` :
      `<form class="decide"><input name="note" maxlength="300" placeholder="${esc(t("p.notePh"))}">
        <button class="primary" value="approved" data-help="help.approve">${esc(t("p.approve"))}</button>
        <button class="danger" value="rejected" data-help="help.reject">${esc(t("p.reject"))}</button></form>`}
  </article>`;
  box.innerHTML = `<p class="sub">${esc(t("p.intro"))}</p>
    ${open.length ? open.map(card).join("") : `<p class="note">${esc(t("p.none"))}</p>`}
    ${done.length ? `<h3 class="sub">${esc(t("p.decidedTitle"))}</h3>${done.map(card).join("")}` : ""}`;
  box.querySelectorAll("form.decide").forEach((f) => {
    const id = f.closest("[data-p]").dataset.p;
    f.onsubmit = (e) => {
      e.preventDefault();
      const decision = e.submitter ? e.submitter.value : "approved";
      change("POST", `${P()}/proposals/${encodeURIComponent(id)}/decide`, { decision, note: f.note.value },
             t(decision === "approved" ? "p.approved" : "p.rejected"));
    };
  });
}

// ----------------------------------------------------------- history ----
// Every saved state of the model (ADR-0004): compare two, name one, make a
// baseline (a frozen name: a prototype, a release), restore one as a new revision.

function drawDiff(d) {
  if (!d) return "";
  const vals = (v) => v.length ? v.map(esc).join(", ") : "—";
  const node = (x) => `${esc(word("type", x.type) || x.type)} <b>${esc(x.label || x.id)}</b>`;
  const none = !d.added.length && !d.removed.length && !d.changed.length;
  return `<div class="diff"><p class="sub">${esc(t("h.between", { a: d.from, b: d.to }))}</p>
    ${none ? `<p class="ok">${esc(t("h.same"))}</p>` : ""}
    ${d.added.map((x) => `<div class="add">+ ${node(x)}</div>`).join("")}
    ${d.removed.map((x) => `<div class="del">− ${node(x)}</div>`).join("")}
    ${d.changed.map((x) => `<div class="chg">~ ${node(x)}<ul>${x.changes.map((c) =>
      `<li><code>${esc(c.property)}</code> ${vals(c.before)} → ${vals(c.after)}</li>`).join("")}</ul></div>`).join("")}</div>`;
}

async function drawHistory() {
  const box = $("#tab-history");
  if (!S.ws) { box.innerHTML = `<p class="note">${esc(t("model.choose"))}</p>`; return; }
  const revs = await core.api("GET", `${P()}/revisions`);
  const key = JSON.stringify(revs) + JSON.stringify(S.cmp || null) + (S.tagging || "") + (S.restoring || "");
  if (S.seen.history === key) return;
  if (box.contains(document.activeElement) && document.activeElement.matches("input")) return;
  S.seen.history = key;
  const base = revs.flatMap((r) => r.tags.filter((g) => g.frozen).map((g) => g.name))[0];
  const opts = (sel) => revs.map((r) => {
    const name = r.tags.length ? ` · ${r.tags.map((g) => g.name).join(", ")}` : "";
    return `<option value="${r.n}" ${String(r.n) === String(sel) ? "selected" : ""}>r${r.n}${esc(name)}</option>`;
  }).join("");
  const from = S.cmpFrom || (base ? revs.find((r) => r.tags.some((g) => g.name === base)).n : (revs[1] || revs[0] || {}).n);
  const to = S.cmpTo || (revs[0] || {}).n;
  box.innerHTML = `
    <p class="sub">${esc(t("h.intro"))}</p>
    <form class="compare">${esc(t("h.compare"))} <select name="from">${opts(from)}</select> → <select name="to">${opts(to)}</select>
      <button type="submit">${esc(t("h.go"))}</button></form>
    ${drawDiff(S.cmp)}
    <table class="history"><thead><tr><th>#</th><th>${esc(t("h.when"))}</th><th>${esc(t("h.via"))}</th>
      <th>${esc(t("h.what"))}</th><th></th></tr></thead><tbody>
    ${revs.map((r, i) => `<tr data-n="${r.n}"><td>r${r.n}</td><td>${esc(when(r.at))}</td>
      <td>${esc(t(`h.via.${r.via}`))}<br><small>${esc(r.by)}</small></td>
      <td>${esc(r.summary)}${r.tags.map((g) => ` <span class="tag${g.frozen ? " frozen" : ""}" title="${esc(g.frozen ? t("h.frozen") : "")}">${g.frozen ? "🔒 " : ""}${esc(g.name)}</span>`).join("")}
        ${S.tagging === String(r.n) ? `<form class="tagging"><input name="name" maxlength="80" placeholder="${esc(t("h.tagPh"))}" required>
          <label><input type="checkbox" name="frozen"> ${esc(t("h.baseline"))}</label><button type="submit">${esc(t("h.save"))}</button></form>` : ""}</td>
      <td class="acts"><button class="tag-it">${esc(t("h.tag"))}</button>
        ${i > 0 ? `<button class="restore${S.restoring === String(r.n) ? " sure" : ""}">${esc(t(S.restoring === String(r.n) ? "h.sure" : "h.restore"))}</button>` : ""}</td></tr>`).join("")}
    </tbody></table>`;
  const again = () => { S.seen.history = null; drawHistory(); };
  box.querySelector("form.compare").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    S.cmpFrom = f.from.value; S.cmpTo = f.to.value;
    try { S.cmp = await core.api("GET", `${P()}/diff?from=${f.from.value}&to=${f.to.value}`); } catch (err) { core.toast(failed(err), true); }
    again();
  };
  box.querySelectorAll("tr[data-n]").forEach((tr) => {
    const n = tr.dataset.n;
    tr.querySelector(".tag-it").onclick = () => { S.tagging = S.tagging === n ? "" : n; S.restoring = ""; again(); };
    const form = tr.querySelector("form.tagging");
    if (form) {
      form.name.focus();
      form.onsubmit = async (e) => {
        e.preventDefault();
        try { await core.api("POST", `${P()}/revisions/${n}/tag`, { name: form.name.value, frozen: form.frozen.checked }); S.tagging = ""; }
        catch (err) { core.toast(failed(err), true); }
        again();
      };
    }
    const back = tr.querySelector(".restore");
    if (back) back.onclick = async () => {
      if (S.restoring !== n) { S.restoring = n; S.tagging = ""; return again(); }
      S.restoring = "";
      const r = await change("POST", `${P()}/revisions/${n}/restore`, {});
      if (r) core.toast(t("h.restored", { n, m: r.revision }));
    };
  });
}

// --------------------------------------------------------------- files ----
//
// Files given to the chat. Dropping one makes it the chat's selection; the
// chat reads it and proposes what to do with it (inbox.py).

// Into the inbox; the server makes it the chat's selection. Returns its meta, or null.
async function addFile(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/inbox", { method: "POST", body: fd }).catch(() => null);
  const r = res ? await res.json().catch(() => ({})) : {};
  S.seen.files = null;
  if (!res || !res.ok) { core.toast(`${file.name}: ${(r.errors || [t("f.notAdded")]).join("; ")}`, true); return null; }
  return r;
}

async function upload(file) {
  const r = await addFile(file);
  if (r) core.toast(t("f.added", { name: r.name, note: r.note }));
  refresh();
}

// The same, from the chat: 📎 beside Ask, or a file dropped on the chat. The
// message is started for the person ("I added …: "), who says what it is for.
// The chat panel belongs to the edge layer (edge.js) and is redrawn, so the
// button is put back whenever its form is new.
async function attachToChat(files) {
  const box = $("#edge-chat");
  const form = box && box.querySelector(".edge-chat__ask");
  const input = form && form.querySelector("textarea");
  const btn = form && form.querySelector(".chat-attach");
  if (!input || !files.length) return;
  if (btn) { btn.disabled = true; btn.textContent = "…"; }
  const added = [];
  for (const f of files) { const r = await addFile(f); if (r) added.push(r); }
  if (btn) { btn.disabled = false; btn.textContent = "📎"; }
  if (!added.length) return;
  const line = added.length === 1
    ? t("f.addedOne", { name: added[0].name, id: added[0].id, kind: added[0].kind })
    : t("f.addedMany", { list: added.map((r) => t("f.listItem", { name: r.name, id: r.id })).join(", ") });
  input.value = input.value.trim() ? `${input.value.trim()}\n${line}` : line;
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  if (S.tab === "files") refresh();
}

function wireChatAttach() {
  const box = $("#edge-chat");
  if (!box) return;
  const hook = () => {
    const form = box.querySelector(".edge-chat__ask");
    if (!form || form.querySelector(".chat-attach")) return;
    const pick = document.createElement("input");
    pick.type = "file"; pick.multiple = true; pick.hidden = true;
    pick.onchange = () => { attachToChat([...pick.files]); pick.value = ""; };
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "chat-attach"; btn.textContent = "📎";
    btn.setAttribute("aria-label", t("f.attachLabel"));
    btn.dataset.help = "help.attach";
    btn.onclick = () => pick.click();
    const ask = form.querySelector('button[type="submit"]');
    form.insertBefore(btn, ask || null);
    form.append(pick);
  };
  hook();
  new MutationObserver(hook).observe(box, { childList: true, subtree: true });
  let depth = 0;   // dragenter/leave fire for every child: count them
  const has = (e) => e.dataTransfer && [...(e.dataTransfer.types || [])].includes("Files");
  box.addEventListener("dragenter", (e) => { if (!has(e)) return; e.preventDefault(); depth++; box.classList.add("chat-drop"); });
  box.addEventListener("dragover", (e) => { if (has(e)) e.preventDefault(); });
  box.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; box.classList.remove("chat-drop"); } });
  box.addEventListener("drop", (e) => {
    if (!has(e)) return;
    e.preventDefault(); depth = 0; box.classList.remove("chat-drop");
    attachToChat([...e.dataTransfer.files]);
  });
}

async function drawFiles() {
  const got = await core.api("GET", "/api/inbox");
  const key = JSON.stringify(got) + S.wsTitle;
  if (S.seen.files === key) return;
  S.seen.files = key;
  const box = $("#tab-files");
  box.innerHTML = `
    <p class="sub">${esc(t("f.intro"))}${S.wsTitle ? " " + esc(t("f.inProduct", { name: S.wsTitle })) : ""}</p>
    <label class="dropzone"><input type="file" multiple hidden>
      <span>${esc(t("f.drop"))}</span></label>
    ${got.length ? `<table class="files"><thead><tr><th>${esc(t("f.file"))}</th><th>${esc(t("f.what"))}</th><th>${esc(t("f.where"))}</th><th class="num">${esc(t("f.size"))}</th><th></th></tr></thead><tbody>
      ${got.map((f) => `<tr data-f="${esc(f.id)}"><td>${esc(f.name)}</td><td><b>${esc(f.kind)}</b> · ${esc(f.note)}</td>
        <td>${f.product ? `<code>${esc(f.product)}/files</code>` : esc(t("f.shared"))}</td>
        <td class="num">${f.size < 1024 ? `${f.size} B` : `${new Intl.NumberFormat(window.i18n.lang).format(Math.round(f.size / 1024))} kB`}</td>
        <td><button class="ask" data-help="help.give">${esc(t("f.give"))}</button> <button class="drop">${esc(t("f.remove"))}</button></td></tr>`).join("")}
      </tbody></table>` : `<p class="note">${esc(t("f.none"))}</p>`}`;
  const zone = box.querySelector(".dropzone");
  const input = zone.querySelector("input");
  input.onchange = () => [...input.files].forEach(upload);
  zone.ondragover = (e) => { e.preventDefault(); zone.classList.add("over"); };
  zone.ondragleave = () => zone.classList.remove("over");
  zone.ondrop = (e) => { e.preventDefault(); zone.classList.remove("over"); [...e.dataTransfer.files].forEach(upload); };
  box.querySelectorAll("tr[data-f]").forEach((tr) => {
    const f = tr.dataset.f;
    tr.querySelector(".ask").onclick = async () => {
      await core.api("POST", "/api/selection", { product: S.ws || "", item: S.item || "", file: f });
      core.toast(t("f.inView"));
    };
    tr.querySelector(".drop").onclick = async () => {
      try { await core.api("DELETE", `/api/inbox/${encodeURIComponent(f)}`); } catch (err) { core.toast(failed(err), true); }
      S.seen.files = null; refresh();
    };
  });
}

// ------------------------------------------------------------- wiring ----

async function refresh() {
  try {
    await drawList();
    if (S.tab === "files") return drawFiles();
    if (S.tab === "model") await drawModel();
    if (S.tab === "proposals") await drawProposals();
    if (S.tab === "history") await drawHistory();
  } catch (err) {
    if (err && err.status === 404 && S.ws) select(null);
  }
}

function wire() {
  document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => {
    S.tab = b.dataset.tab;
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("is-on", x === b));
    document.querySelectorAll(".tab").forEach((x) => x.hidden = x.id !== `tab-${S.tab}`);
    S.seen = {};
    busy(refresh);
  });
  $("#np-make").onclick = async () => {
    try {
      const got = await core.api("POST", "/api/products", { title: $("#np-title").value });
      $("#np-title").value = "";
      $(".new-ws").open = false;
      select(got.product);
    } catch (err) { core.toast(failed(err), true); }
  };
  $("#np-title").onkeydown = (e) => { if (e.key === "Enter") $("#np-make").click(); };
  wireHelp();
  wireSide();
  wireChatAttach();
  // a language switch redraws what this page drew; i18n.js does the rest
  window.i18n.onChange(() => { S.seen = {}; refresh(); });
  const h = hashState();
  select(h.ws, h.item);
  setInterval(() => { if (!document.hidden) refresh(); }, 4000);
}

// ---------------------------------------------- help and the side rail ----

// A per-browser setting; private windows and blocked storage just forget it.
const pref = (k, v) => {
  try {
    if (v === undefined) return localStorage.getItem(k);
    localStorage.setItem(k, v);
  } catch (_) { /* not kept */ }
  return v === undefined ? null : v;
};

/** Hover help: [data-help] names a string; the switch in the header turns it on and off. */
function wireHelp() {
  const sw = $("#help-on");
  const tip = $("#help-tip");
  const theme = document.getElementById("core-theme");
  if (theme && theme.closest("label")) theme.closest("label").dataset.help = "help.theme";
  const chat = document.getElementById("edge-chat");
  if (chat) chat.dataset.help = "help.chat";
  const conn = document.getElementById("edge-connections");
  if (conn) conn.dataset.help = "help.connections";
  sw.checked = pref("maker5.help") !== "off";
  sw.onchange = () => { pref("maker5.help", sw.checked ? "on" : "off"); hide(); };
  let timer = null;
  let over = null;
  const hide = () => { clearTimeout(timer); timer = null; over = null; tip.hidden = true; };
  const show = (el) => {
    const text = t(el.dataset.help);
    if (!text || text === el.dataset.help) return;
    tip.textContent = text;
    tip.hidden = false;
    const r = el.getBoundingClientRect();
    const w = tip.offsetWidth;
    const h = tip.offsetHeight;
    const below = r.bottom + 8 + h < window.innerHeight;
    tip.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2))}px`;
    tip.style.top = `${below ? r.bottom + 8 : Math.max(8, r.top - h - 8)}px`;
  };
  const enter = (e) => {
    if (!sw.checked) return;
    // the innermost element with help wins; a panel's help shows only on its heading area
    const el = e.target.closest && e.target.closest("[data-help]");
    if (!el || el === over) return;
    hide();
    over = el;
    timer = setTimeout(() => show(el), 450);
  };
  document.addEventListener("mouseover", enter);
  document.addEventListener("focusin", enter);
  document.addEventListener("mouseout", (e) => { if (over && !over.contains(e.relatedTarget)) hide(); });
  document.addEventListener("focusout", hide);
  document.addEventListener("scroll", hide, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
}

/** The left rail (products) hides and comes back; the choice is kept. */
function wireSide() {
  const btn = $("#btn-side");
  const set = (shown) => {
    document.body.classList.toggle("side-hidden", !shown);
    btn.setAttribute("aria-pressed", String(shown));
    btn.title = t(shown ? "toolbar.sideHide" : "toolbar.sideShow");
    pref("maker5.side", shown ? "shown" : "hidden");
  };
  set(pref("maker5.side") !== "hidden");
  btn.onclick = () => set(document.body.classList.contains("side-hidden"));
  window.i18n.onChange(() => set(!document.body.classList.contains("side-hidden")));
}

// the strings first (i18n.json), then the page
const start = () => window.i18n.ready.then(wire);
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
else start();
