/* SPDX-License-Identifier: GPL-3.0-or-later
 * The intake (ADR-0022 in maker-5-shared): what was scanned at the shelf on
 * the phone, label after label into a shelf or box, with photos and notes.
 * The agent describes the items (intake skill); here the person looks at
 * each, changes what is wrong, and checks it in, or drops it. Checking in
 * and dropping are the person's: the agent has no tool for them, and the
 * edge refuses them from one.
 *
 *   window.intakeView.draw()   the tab
 */
(() => {
  "use strict";
  const esc = (s) => core.esc(String(s ?? ""));
  const t = (k, v) => window.i18n.t(k, v);
  const failed = (err) => (err && err.errors) ? err.errors.join("; ") : t("failed");
  const V = { key: "", cats: null };
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
    const key = JSON.stringify(items);
    if (!force && key === V.key && box.querySelector(".intake")) return;
    V.key = key;
    const described = items.filter((x) => x.status === "described").length;
    box.innerHTML = `<div class="intake">
      <div class="intake__bar">
        <span>${esc(t("in.count", { n: items.length, d: described }))}</span>
        <button type="button" class="intake-ask" ${items.some((x) => x.status === "new" && !x.known) ? "" : "disabled"}
          data-help="help.in.ask">${esc(t("in.ask"))}</button>
        <button type="button" class="intake-reload">${esc(t("in.reload"))}</button>
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
    </div>`;
    box.querySelector(".intake-reload").onclick = () => draw(true);
    box.querySelector(".intake-ask").onclick = () => ask(t("in.request"));
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
        <button value="in" class="primary">${esc(t("in.checkIn"))}</button></div></div>`, (form, dlg) => {
      const q = (n) => form.querySelector(`[name="${n}"]`);
      const shown = () => {
        if (known) return;
        const w = (form.querySelector('[name="what"]:checked') || {}).value;
        q("serial").closest("label").hidden = w !== "device";
        q("qty").closest("label").hidden = w === "device";
        q("boxName").closest("label").hidden = w !== "box";
      };
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
            core.toast(t(`in.done.${r.kind}`, { place: x.placeName || "" }));
          }
        } catch (err) { core.toast(failed(err), true); return; }
        form.onsubmit = null;
        dlg.close();
        await draw(true);
      };
    });
  }

  window.intakeView = { draw };
})();
