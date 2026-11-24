/* SPDX-License-Identifier: GPL-3.0-or-later
 * The intake (ADR-0022 in maker-5-shared): what was scanned at the shelf on
 * the phone, label after label into a shelf or box, with photos and notes.
 * The agent describes the items (intake skill); here the person looks at
 * each, changes what is wrong, and checks it in, or drops it. Checking in
 * and dropping are the person's: the agent has no tool for them, and the
 * edge refuses them from one. The cloud checks in only for an admin of the
 * organisation with two-step sign-in: the person who linked this edge.
 *
 * Orders (ADR-0023): an order e-mail dropped here (or its text pasted)
 * becomes expected lines in the cloud, after a preview the person ticks.
 * The e-mail is read here and not kept; only the order number, its date and
 * the lines leave. An item that arrived for a line names it (From order).
 *
 *   window.intakeView.draw()   the tab
 */
(() => {
  "use strict";
  const esc = (s) => core.esc(String(s ?? ""));
  const t = (k, v) => window.i18n.t(k, v);
  const failed = (err) => (err && err.errors) ? err.errors.join("; ") : t("failed");
  const V = { key: "", cats: null, site: null, lines: [] };
  /** The cloud's site, where Scan shows a QR for the phone. Only https. */
  async function site() {
    if (V.site === null) {
      try { const s = (await core.api("GET", "/api/cloud")).site || ""; V.site = /^https:\/\/[^/]+/.test(s) ? s.replace(/\/+$/, "") : ""; }
      catch { V.site = ""; }
    }
    return V.site;
  }
  const mark = (x) => (x.code.kind === "m5" ? `${x.family === "dhc" ? "DHC" : "M5"} ${x.code.value}` : x.code.value);
  const photoUrl = (x, p) => `/api/intake/${encodeURIComponent(x.id)}/photos/${encodeURIComponent(p.id)}.jpg`;
  const WHAT = ["device", "box", "bulk"];

  async function draw(force = false) {
    const box = document.getElementById("tab-intake");
    if (!box) return;
    if (document.querySelector("#core-dialog[open] .intake-form")) return;   // never under the person's hand
    let items;
    try { items = await core.api("GET", "/api/intake"); } catch (err) {
      box.innerHTML = `<p class="note">${esc(failed(err))}</p>`; V.key = ""; return;
    }
    try { V.lines = await core.api("GET", "/api/orders"); } catch { V.lines = []; }
    const key = JSON.stringify([items, V.lines]);
    if (!force && key === V.key && box.querySelector(".intake")) return;
    V.key = key;
    const described = items.filter((x) => x.status === "described").length;
    const scan = await site();
    box.innerHTML = `<div class="intake">
      <div class="intake__bar">
        <span>${esc(t("in.count", { n: items.length, d: described }))}</span>
        <button type="button" class="intake-ask" ${items.some((x) => x.status === "new" && !x.known) ? "" : "disabled"}
          data-help="help.in.ask">${esc(t("in.ask"))}</button>
        <button type="button" class="intake-reload">${esc(t("in.reload"))}</button>
        <button type="button" class="intake-order" data-help="help.or.mail">${esc(t("or.mail"))}</button>
        ${scan ? `<a class="button" href="${esc(scan)}/scan/?mode=intake" target="_blank" rel="noopener"
          data-help="help.in.phone">${esc(t("in.phone"))}</a>` : ""}
      </div>
      ${items.length ? `<ul class="intake__list">${items.map((x) => {
        const s = x.suggestion;
        const what = x.known ? t("in.known", { name: x.known.name || x.known.id })
          : s ? `${t(`in.what.${s.what}`)}: ${s.article?.name || s.articleId || ""}${s.qty ? ` × ${s.qty}` : ""}` : t("in.notYet");
        return `<li class="intake__item is-${esc(x.status)}" data-id="${esc(x.id)}">
          ${x.photos.length ? `<img src="${esc(photoUrl(x, x.photos[0]))}" alt="" loading="lazy" class="intake__thumb">`
            : `<span class="intake__thumb intake__thumb--none" aria-hidden="true">?</span>`}
          <span class="intake__text"><code>${esc(mark(x))}</code> <b>${esc(what)}</b>
            <small>${esc(x.placeName || "")}${x.note ? ` · ${esc(x.note)}` : ""}${x.qty ? ` · ${x.qty}` : ""}</small></span>
          <button type="button" class="intake-open">${esc(t("in.open"))}</button></li>`;
      }).join("")}</ul>` : `<p class="note">${esc(t("in.empty"))}</p>`}
      ${V.lines.length ? `<h3 class="intake__h">${esc(t("or.expected"))}</h3>
      <ul class="intake__list intake__expected">${V.lines.map((l) => `<li data-line="${esc(l.id)}">
        <span class="intake__text"><b>${esc(l.title)}</b>
          <small>${l.arrived ? `${l.arrived}/${l.qty}` : `× ${l.qty}`} · ${esc(l.orderedAt || "")} · ${esc(l.supplier)} · ${esc(l.articleName || t("or.new"))}</small></span>
      </li>`).join("")}</ul>` : ""}
    </div>`;
    box.querySelector(".intake-reload").onclick = () => draw(true);
    box.querySelector(".intake-ask").onclick = () => ask(t("in.request"));
    box.querySelector(".intake-order").onclick = orderDialog;
    box.querySelectorAll(".intake-open").forEach((b) => b.onclick = () => open(b.closest("[data-id]").dataset.id));
  }

  /** A request written into the chat box, for the person to finish and send. */
  function ask(text) {
    const input = document.querySelector("#edge-chat .edge-chat__ask textarea");
    if (!input) { core.toast(t("hw.agentNoChat")); return; }
    input.value = text;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.focus();
  }

  async function categories() {
    if (!V.cats) {
      try { V.cats = (await core.api("GET", "/api/catalogue")).map((c) => c.code || c.notation).filter(Boolean); } catch { V.cats = []; }
    }
    return V.cats;
  }

  /** One item: its photos, what it is (as suggested), and Check in or Drop. */
  async function open(id) {
    let got;
    try { got = await core.api("GET", `/api/intake/${encodeURIComponent(id)}`); } catch (err) { core.toast(failed(err), true); return; }
    const x = got.item, s = x.suggestion || {}, a = s.article || {};
    const cats = await categories();
    const known = x.known;
    const sure = (k) => (s.sure && s.sure[k] ? ` <small class="sure-${esc(s.sure[k])}">${esc(t(`in.sure.${s.sure[k]}`))}</small>` : "");
    const field = (name, label, value, attrs = "") => `<label>${esc(label)}${sure(name)}
      <input name="${name}" value="${esc(value ?? "")}" ${attrs}></label>`;
    core.dialog(`${mark(x)} · ${x.placeName || ""}`, `<div class="intake-form">
      <div class="intake-photos">${got.photos.length ? got.photos.map((p) =>
        `<a href="${esc(photoUrl(x, p))}" target="_blank" rel="noopener"><img src="${esc(photoUrl(x, p))}" alt="${esc(t("in.photo"))}"></a>`).join("")
        : `<p class="note">${esc(t("in.noPhoto"))}</p>`}</div>
      ${x.note || x.qty ? `<p class="note">${esc(t("in.taken"))}: ${esc(x.note || "")}${x.qty ? ` · ${x.qty}` : ""}</p>` : ""}
      ${known ? `<p>${esc(t("in.knownMove", { name: known.name || known.id, place: x.placeName || "" }))}</p>` : `
      ${V.lines.length ? `<label>${esc(t("or.from"))}<select name="orderLineId">
        <option value="">${esc(t("or.none"))}</option>
        ${V.lines.map((l) => `<option value="${esc(l.id)}" ${s.orderLineId === l.id ? "selected" : ""}>${esc(l.title.slice(0, 60))} × ${l.qty - l.arrived}</option>`).join("")}
      </select></label>` : ""}
      <fieldset class="intake-what">${WHAT.map((w) => `<label><input type="radio" name="what" value="${w}" ${(s.what || (x.family === "dhc" ? "device" : "")) === w ? "checked" : ""}>
        ${esc(t(`in.what.${w}`))}</label>`).join("")}</fieldset>
      <label>${esc(t("in.article"))}${sure("articleId")}
        <input name="find" placeholder="${esc(t("in.find"))}" value="${esc(got.article ? got.article.name : "")}" autocomplete="off">
        <input type="hidden" name="articleId" value="${esc(s.articleId || "")}"></label>
      <ul class="intake-found"></ul>
      <div class="intake-new" ${s.articleId ? "hidden" : ""}>
        ${field("name", t("in.name"), a.name, 'maxlength="120"')}
        <label>${esc(t("in.category"))}${sure("category")}<input name="category" list="intake-cats" value="${esc(a.category || "")}">
          <datalist id="intake-cats">${cats.map((c) => `<option value="${esc(c)}">`).join("")}</datalist></label>
        ${field("manufacturer", t("in.maker"), a.manufacturer, 'maxlength="80"')}
        ${field("mpn", t("in.mpn"), a.mpn, 'maxlength="80"')}
      </div>
      ${field("serial", t("in.serial"), s.serial, 'maxlength="80"')}
      ${field("qty", t("in.qty"), s.qty ?? x.qty ?? "", 'type="number" min="1"')}
      ${field("boxName", t("in.boxName"), s.boxName, 'maxlength="120"')}
      ${field("note", t("in.note"), s.note ?? a.note, 'maxlength="500"')}`}
      <div class="actions"><button value="drop" class="danger" formnovalidate>${esc(t("in.drop"))}</button>
        <button value="cancel" formnovalidate>${esc(t("model.cancel"))}</button>
        ${known ? "" : `<button value="save" formnovalidate>${esc(t("in.save"))}</button>`}
        <small class="intake-admin">${esc(t("in.adminonly"))}</small>
        <button value="in" class="primary">${esc(t("in.checkIn"))}</button></div></div>`, (form, dlg) => {
      const q = (n) => form.querySelector(`[name="${n}"]`);
      const shown = () => {
        if (known) return;
        const w = (form.querySelector('[name="what"]:checked') || {}).value;
        q("serial").closest("label").hidden = w !== "device";
        q("qty").closest("label").hidden = w === "device";
        q("boxName").closest("label").hidden = w !== "box";
      };
      if (!known && q("orderLineId")) {
        q("orderLineId").onchange = () => {
          const l = V.lines.find((x) => x.id === q("orderLineId").value);
          if (!l) return;
          const r = form.querySelector(`[name="what"][value="${l.what}"]`);
          if (r) r.checked = true;
          if (l.articleId) {
            q("articleId").value = l.articleId; q("find").value = l.articleName || l.title;
            form.querySelector(".intake-new").hidden = true;
          } else {
            const a = l.article || {};
            q("articleId").value = ""; q("find").value = "";
            form.querySelector(".intake-new").hidden = false;
            q("name").value = a.name || l.title; if (a.category) q("category").value = a.category;
            if (a.manufacturer) q("manufacturer").value = a.manufacturer; if (a.mpn) q("mpn").value = a.mpn;
          }
          q("qty").value = Math.max(1, l.qty - l.arrived);
          shown();
        };
      }
      if (!known) {
        form.querySelectorAll('[name="what"]').forEach((r) => r.onchange = shown);
        shown();
        let timer;
        q("find").oninput = () => {
          q("articleId").value = "";
          form.querySelector(".intake-new").hidden = false;
          clearTimeout(timer);
          timer = setTimeout(async () => {
            const words = q("find").value.trim();
            const list = form.querySelector(".intake-found");
            if (words.length < 2) { list.innerHTML = ""; return; }
            let found = [];
            try { found = await core.api("GET", `/api/stock?q=${encodeURIComponent(words)}`); } catch { /* offline: a new article */ }
            list.innerHTML = found.slice(0, 6).map((f) => `<li><button type="button" data-a="${esc(f.id)}">${esc(f.name)}
              <small>${esc(f.category)} · ${esc(f.tracking)}</small></button></li>`).join("");
            list.querySelectorAll("[data-a]").forEach((b) => b.onclick = () => {
              q("articleId").value = b.dataset.a; q("find").value = found.find((f) => f.id === b.dataset.a).name;
              list.innerHTML = ""; form.querySelector(".intake-new").hidden = true;
            });
          }, 250);
        };
      }
      const suggestion = () => {
        if (known) return null;
        const what = (form.querySelector('[name="what"]:checked') || {}).value;
        const out = { what, sure: s.sure };
        const v = (n) => q(n).value.trim();
        if (q("orderLineId") && v("orderLineId")) out.orderLineId = v("orderLineId");
        if (v("articleId")) out.articleId = v("articleId");
        else out.article = { name: v("name") || v("find"), category: v("category") || "other", manufacturer: v("manufacturer"), mpn: v("mpn") };
        if (what === "device" && v("serial")) out.serial = v("serial");
        if (what !== "device" && v("qty")) out.qty = Number(v("qty"));
        if (what === "box" && v("boxName")) out.boxName = v("boxName");
        if (v("note")) out.note = v("note");
        return out;
      };
      form.onsubmit = async (ev) => {
        const b = ev.submitter && ev.submitter.value;
        if (!b || b === "cancel") { form.onsubmit = null; return; }
        ev.preventDefault();
        const sg = suggestion();
        if (sg && b !== "drop" && !sg.what) { core.toast(t("in.sayWhat"), true); return; }
        try {
          if (b === "drop") await core.api("POST", `/api/intake/${encodeURIComponent(id)}/drop`, {});
          else if (b === "save") await core.api("POST", `/api/intake/${encodeURIComponent(id)}/describe`, { suggestion: sg });
          else {
            const r = await core.api("POST", `/api/intake/${encodeURIComponent(id)}/checkin`, sg ? { suggestion: sg } : {});
            core.toast(t(known ? "in.done.moved" : `in.done.${r.kind}`, { place: x.placeName || "" }));
          }
        } catch (err) { core.toast(failed(err), true); return; }
        form.onsubmit = null;
        dlg.close();
        await draw(true);
      };
    });
  }

  /** An order e-mail: drop or choose the .eml, or paste its text; a preview to tick; then expected. */
  function orderDialog() {
    let pv = null;
    core.dialog(t("or.mail"), `<div class="intake-form order-form">
      <p class="note">${esc(t("or.mailLead"))}</p>
      <label class="order-drop">${esc(t("or.file"))}<input type="file" name="file" accept=".eml,message/rfc822,.txt"></label>
      <label>${esc(t("or.paste"))}<textarea name="text" rows="5"></textarea></label>
      <div class="order-preview"></div>
      <div class="actions"><button value="cancel" formnovalidate>${esc(t("model.cancel"))}</button>
        <button value="read" formnovalidate>${esc(t("or.read"))}</button>
        <button value="apply" class="primary" disabled>${esc(t("or.apply"))}</button></div></div>`, (form, dlg) => {
      const zone = form.querySelector(".order-form");
      zone.ondragover = (e) => { e.preventDefault(); };
      zone.ondrop = (e) => {
        e.preventDefault();
        const f = e.dataTransfer && e.dataTransfer.files[0];
        if (f) { const dt = new DataTransfer(); dt.items.add(f); form.querySelector('[name="file"]').files = dt.files; read(); }
      };
      form.querySelector('[name="file"]').onchange = () => read();
      const show = () => {
        const box = form.querySelector(".order-preview");
        box.innerHTML = `<p><b>${esc(pv.supplier)} · ${esc(pv.orderRef)}</b> ${esc(pv.orderedAt || "")}</p>
          <table class="order-lines"><thead><tr><th></th><th>${esc(t("or.title"))}</th><th>${esc(t("in.qty"))}</th>
            <th>${esc(t("or.is"))}</th><th>${esc(t("in.category"))}</th></tr></thead><tbody>
          ${pv.lines.map((l, i) => `<tr class="${l.known ? "is-known" : ""}"><td><input type="checkbox" data-i="${i}" ${l.include ? "checked" : ""}></td>
            <td>${esc(l.title)}${l.unitPrice != null ? ` <small>${esc(l.unitPrice)} ${esc(l.currency || "")}</small>` : ""}</td>
            <td><input type="number" min="1" data-q="${i}" value="${l.qty}" class="order-qty">${l.pack > 1 ? ` <small>${esc(t("or.pack", { n: l.ordered, each: l.pack }))}</small>` : ""}</td>
            <td>${l.known ? esc(t("or.known")) : l.match ? `${esc(l.match.name)} <small>${esc(t(`or.by.${l.match.by}`))}</small>` : esc(t("or.new"))}</td>
            <td>${l.match ? "" : esc(l.article.category)}</td></tr>`).join("")}</tbody></table>`;
        box.querySelectorAll("[data-i]").forEach((c) => c.onchange = () => { pv.lines[+c.dataset.i].include = c.checked; });
        box.querySelectorAll("[data-q]").forEach((c) => c.onchange = () => { pv.lines[+c.dataset.q].qty = Math.max(1, +c.value || 1); });
        form.querySelector('[value="apply"]').disabled = false;
      };
      async function read() {
        const f = form.querySelector('[name="file"]').files[0];
        const text = form.querySelector('[name="text"]').value;
        let r;
        try {
          if (f) {
            const fd = new FormData(); fd.append("file", f);
            const res = await fetch("/api/orders/preview", { method: "POST", body: fd });
            r = await res.json().catch(() => ({}));
            if (!res.ok) throw r;
          } else r = await core.api("POST", "/api/orders/preview", { text });
        } catch (err) { core.toast(failed(err), true); return; }
        pv = r; show();
      }
      form.onsubmit = async (ev) => {
        const b = ev.submitter && ev.submitter.value;
        if (!b || b === "cancel") { form.onsubmit = null; return; }
        ev.preventDefault();
        if (b === "read") { await read(); return; }
        try {
          const r = await core.api("POST", "/api/orders/apply", { preview: pv });
          core.toast(t("or.added", { n: r.added, skipped: r.skipped }));
        } catch (err) { core.toast(failed(err), true); return; }
        form.onsubmit = null;
        dlg.close();
        await draw(true);
      };
    });
  }

  window.intakeView = { draw };
})();
