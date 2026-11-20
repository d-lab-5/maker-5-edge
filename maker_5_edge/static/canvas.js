/* SPDX-License-Identifier: GPL-3.0-or-later
 * The hardware canvas (ADR-0014 in maker-5-shared): the workspace's blocks as
 * parts with their pins, and the wires between pins. Everything drawn here is
 * in the model (products.py canvas/place/pins/wires), so it syncs with the
 * cloud and the chat reads it with canvas().
 *
 *   drag a part        moves it (saved when you let go: one revision)
 *   click a pin, then another     a wire, in the colour chosen above
 *   click a wire       its colour, or remove it
 *   drag the background, the wheel, − / +    pan and zoom
 */
(() => {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const esc = (s) => core.esc(String(s ?? ""));
  const t = (k, v) => window.i18n.t(k, v);
  const failed = (err) => (err && err.errors) ? err.errors.join("; ") : t("failed");
  const W = 190, HEAD = 28, ROW = 17, PAD = 8, GRID = 10;
  const COLORS = ["red", "black", "yellow", "white", "blue", "green", "orange", "purple"];
  const ROLE_COLOR = { power: "red", ground: "black", signal: "blue", audio: "purple", video: "orange", data: "green" };
  const C = { base: "", ws: "", data: null, key: "", view: { x: -40, y: -40, k: 1 }, from: null, color: "yellow", dragging: false };

  const el = (tag, attrs = {}, parent) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  };
  const snap = (v) => Math.round(v / GRID) * GRID;

  /** Which side and row a pin sits on: a long header odd left and even right,
   *  as it is on the board; a small part its first half left. */
  const IMG = 110;                                  // room for a block's picture
  const hasImage = (b) => !!b.fritzing || (b.image && b.image.kind !== "none");
  function layout(b) {
    const pins = b.pins;
    const w = hasImage(b) ? W + IMG : W;
    const header = pins.length >= 20;
    const left = [], right = [];
    pins.forEach((p, i) => ((header ? p.n % 2 === 1 : i < Math.ceil(pins.length / 2)) ? left : right).push(p));
    const rows = Math.max(left.length, right.length, 1);
    const at = {};
    left.forEach((p, i) => { at[p.id] = { x: 0, y: HEAD + PAD + i * ROW + ROW / 2, side: -1 }; });
    right.forEach((p, i) => { at[p.id] = { x: w, y: HEAD + PAD + i * ROW + ROW / 2, side: 1 }; });
    return { at, w, h: Math.max(HEAD + PAD * 2 + rows * ROW, hasImage(b) ? HEAD + IMG + PAD * 2 : 0) };
  }

  async function api(method, path, payload) {
    try { return await core.api(method, path, payload); } catch (err) { core.toast(failed(err), true); return null; }
  }

  async function reload() {
    C.key = "";
    await draw(C.base, C.ws);
  }

  async function draw(base, ws) {
    const box = document.getElementById("tab-canvas");
    if (!box) return;
    if (!ws) { box.innerHTML = `<p class="note">${esc(t("model.choose"))}</p>`; C.key = ""; return; }
    if (C.dragging || C.from) return;                              // never under the person's hand
    const data = await core.api("GET", `${base}/canvas`);
    const key = ws + JSON.stringify(data) + C.color;
    if (key === C.key && box.querySelector("svg")) return;
    if (C.ws !== ws) C.view = { x: -40, y: -40, k: 1 };
    Object.assign(C, { base, ws, data, key });
    const placed = data.blocks.filter((b) => b.x !== null);
    const loose = data.blocks.filter((b) => b.x === null);
    box.innerHTML = `
      <div class="hw-bar">
        <label>${esc(t("hw.color"))} <select class="hw-color" data-help="help.hw.color">${COLORS.map((c) =>
          `<option value="${c}" ${c === C.color ? "selected" : ""}>${esc(t(`hw.c.${c}`))}</option>`).join("")}</select></label>
        <button class="hw-zoom" data-z="-1" data-help="help.hw.zoom">−</button>
        <button class="hw-zoom" data-z="1" data-help="help.hw.zoom">+</button>
        <button class="hw-fit" data-help="help.hw.fit">${esc(t("hw.fit"))}</button>
        <button class="hw-full" data-help="help.hw.full">${esc(document.fullscreenElement ? t("hw.unfull") : t("hw.full"))}</button>
        <span class="hw-status note">${esc(t("hw.hint"))}</span>
      </div>
      <div class="hw">
        <aside class="hw-side">
          <h3>${esc(t("hw.loose"))}</h3>
          ${loose.length ? `<ul>${loose.map((b) => `<li><span>${esc(b.name)}</span>
            <button data-place="${esc(b.id)}" data-help="help.hw.place">${esc(t("hw.place"))}</button></li>`).join("")}</ul>`
            : `<p class="note">${esc(data.blocks.length ? t("hw.allPlaced") : t("hw.noBlocks"))}</p>`}
          ${placed.length ? `<h3>${esc(t("hw.placed"))}</h3><ul>${placed.map((b) => `<li><span>${esc(b.name)}</span>
            <span><button data-fz="${esc(b.id)}" data-help="help.hw.image">${esc(t("hw.image"))}</button>
            <button data-pins="${esc(b.id)}" data-help="help.hw.pins">${esc(t("hw.pins"))}</button></span></li>`).join("")}</ul>` : ""}
          <p class="note">${esc(t("hw.wires", { n: data.wires.length }))}</p>
          ${data.blocks.some((b) => b.fritzing) ? `<p class="note hw-credit">${esc(t("hw.fzCredit"))}
            <a href="https://github.com/fritzing/fritzing-parts" target="_blank" rel="noreferrer">fritzing-parts</a>, CC BY-SA 3.0</p>` : ""}
          ${data.blocks.some((b) => b.image && b.image.kind === "wokwi") ? `<p class="note hw-credit">${esc(t("hw.wkCredit"))}
            <a href="https://github.com/wokwi/wokwi-elements" target="_blank" rel="noreferrer">wokwi-elements</a>, MIT</p>` : ""}
        </aside>
        <div class="hw-stage"></div>
      </div>`;
    const svg = el("svg", { class: "hw-svg", role: "img", "aria-label": t("tab.canvas") }, box.querySelector(".hw-stage"));
    const defs = el("defs", {}, svg);
    const pat = el("pattern", { id: "hw-grid", width: GRID * 2, height: GRID * 2, patternUnits: "userSpaceOnUse" }, defs);
    el("circle", { cx: 1, cy: 1, r: 0.8, class: "hw-dot" }, pat);
    const world = el("g", { class: "hw-world" }, svg);
    el("rect", { x: -5000, y: -5000, width: 10000, height: 10000, fill: "url(#hw-grid)", class: "hw-bg" }, world);
    const wiresG = el("g", {}, world);
    const partsG = el("g", {}, world);

    const geo = {};
    for (const b of placed) geo[b.id] = { b, ...layout(b) };
    const pinPoint = (pinId, blockId) => {
      const g = geo[blockId];
      if (!g || !g.at[pinId]) return null;
      const a = g.at[pinId];
      return { x: g.b.x + a.x, y: g.b.y + a.y, side: a.side };
    };

    function drawWires() {
      wiresG.innerHTML = "";
      for (const w of data.wires) {
        const [a, b] = w.ends.map((e) => pinPoint(e.pin, e.block));
        if (!a || !b) continue;
        const ax = a.x + a.side * 18, bx = b.x + b.side * 18, mx = (ax + bx) / 2;
        const d = `M${a.x},${a.y} H${ax} H${mx} V${b.y} H${bx} H${b.x}`;
        const role = (geo[w.ends[0].block]?.b.pins.find((p) => p.id === w.ends[0].pin) || {}).role;
        const color = w.color || ROLE_COLOR[role] || "gray";
        el("path", { d, class: "hw-wire-hit", "data-wire": w.id }, wiresG);
        const path = el("path", { d, class: "hw-wire", stroke: color, "data-wire": w.id }, wiresG);
        const names = w.ends.map((e) => `${geo[e.block]?.b.name ?? e.block} · ${geo[e.block]?.b.pins.find((p) => p.id === e.pin)?.name ?? e.pin}`);
        el("title", {}, path).textContent = names.join(" → ");
      }
    }

    for (const g of Object.values(geo)) {
      const b = g.b;
      const part = el("g", { class: `hw-part${b.supply === "to-buy" ? " to-buy" : ""}`, transform: `translate(${b.x},${b.y})`, "data-block": b.id }, partsG);
      el("rect", { width: g.w, height: g.h, rx: 6, class: "hw-body" }, part);
      el("rect", { width: g.w, height: HEAD, rx: 6, class: "hw-head" }, part);
      const pic = picture(b);
      if (pic) {
        // the block's picture, between its pin columns; an <image> runs nothing
        const img = el("image", { x: (g.w - IMG) / 2, y: HEAD + PAD, width: IMG, height: g.h - HEAD - PAD * 2,
          href: pic.href, preserveAspectRatio: "xMidYMid meet", class: "hw-img" }, part);
        el("title", {}, img).textContent = pic.credit;
      }
      const title = el("text", { x: 10, y: 18, class: "hw-name" }, part);
      title.textContent = b.name.length > 26 ? b.name.slice(0, 25) + "…" : b.name;
      el("title", {}, title).textContent = b.name + (b.supply ? ` · ${t(`supply.${b.supply}`)}` : "");
      for (const p of b.pins) {
        const a = g.at[p.id];
        const pin = el("g", { class: `hw-pin role-${p.role || "none"}`, "data-pin": p.id, "data-block": b.id }, part);
        el("circle", { cx: a.x, cy: a.y, r: 5 }, pin);
        const label = el("text", { x: a.x - a.side * 9, y: a.y + 4, "text-anchor": a.side < 0 ? "start" : "end", class: "hw-pinname" }, pin);
        label.textContent = p.name.length > 12 ? p.name.slice(0, 11) + "…" : p.name;
        const reach = data.wires.filter((w) => w.ends.some((e) => e.pin === p.id))
          .map((w) => w.ends.find((e) => e.pin !== p.id)).map((e) => `${geo[e.block]?.b.name ?? e.block} ${geo[e.block]?.b.pins.find((x) => x.id === e.pin)?.name ?? ""}`);
        el("title", {}, pin).textContent = `${p.name} (${p.n})${p.role ? " · " + t(`role.${p.role}`) : ""}${reach.length ? " → " + reach.join(", ") : ""}`;
      }
    }
    drawWires();

    const apply = () => world.setAttribute("transform", `translate(${-C.view.x * C.view.k},${-C.view.y * C.view.k}) scale(${C.view.k})`);
    apply();
    const toWorld = (ev) => {
      const r = svg.getBoundingClientRect();
      return { x: (ev.clientX - r.left) / C.view.k + C.view.x, y: (ev.clientY - r.top) / C.view.k + C.view.y };
    };
    const status = (msg) => { const s = box.querySelector(".hw-status"); if (s) s.textContent = msg; };

    // drag a part, or the background to pan
    svg.addEventListener("pointerdown", (ev) => {
      if (ev.target.closest(".hw-pin") || ev.target.closest("[data-wire]")) return;
      const part = ev.target.closest(".hw-part");
      const start = toWorld(ev);
      const g = part ? geo[part.dataset.block] : null;
      const from = g ? { x: g.b.x, y: g.b.y } : { ...C.view };
      const sx = ev.clientX, sy = ev.clientY;
      C.dragging = true;
      svg.setPointerCapture(ev.pointerId);
      const move = (e) => {
        if (g) {
          const p = toWorld(e);
          g.b.x = snap(from.x + p.x - start.x); g.b.y = snap(from.y + p.y - start.y);
          part.setAttribute("transform", `translate(${g.b.x},${g.b.y})`);
          drawWires();
        } else {
          C.view.x = from.x - (e.clientX - sx) / C.view.k; C.view.y = from.y - (e.clientY - sy) / C.view.k;
          apply();
        }
      };
      const up = async () => {
        svg.removeEventListener("pointermove", move);
        svg.removeEventListener("pointerup", up);
        C.dragging = false;
        if (g && (g.b.x !== from.x || g.b.y !== from.y)) {
          if (await api("POST", `${C.base}/canvas/place`, { block: g.b.id, x: g.b.x, y: g.b.y })) C.key = "";
        }
      };
      svg.addEventListener("pointermove", move);
      svg.addEventListener("pointerup", up);
    });
    svg.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const p = toWorld(ev);
      const k = Math.min(3, Math.max(0.3, C.view.k * (ev.deltaY < 0 ? 1.1 : 1 / 1.1)));
      const r = svg.getBoundingClientRect();
      C.view = { k, x: p.x - (ev.clientX - r.left) / k, y: p.y - (ev.clientY - r.top) / k };
      apply();
    }, { passive: false });

    // a wire: one pin, then another
    svg.querySelectorAll(".hw-pin").forEach((pin) => pin.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const id = pin.dataset.pin;
      if (!C.from) {
        C.from = id;
        pin.classList.add("is-from");
        status(t("hw.pickSecond"));
        return;
      }
      const a = C.from;
      C.from = null;
      svg.querySelectorAll(".is-from").forEach((x) => x.classList.remove("is-from"));
      if (a === id) { status(t("hw.hint")); return; }
      if (await api("POST", `${C.base}/wires`, { from: a, to: id, color: C.color })) {
        core.toast(t("hw.wired"));
        await reload();
      } else status(t("hw.hint"));
    }));
    svg.querySelectorAll("path[data-wire]").forEach((p) => p.addEventListener("click", (ev) => {
      ev.stopPropagation();
      wireDialog(data.wires.find((w) => w.id === p.dataset.wire));
    }));
    const escape = (ev) => {
      if (ev.key !== "Escape" || !C.from) return;
      C.from = null;
      svg.querySelectorAll(".is-from").forEach((x) => x.classList.remove("is-from"));
      status(t("hw.hint"));
    };
    document.removeEventListener("keydown", C.escape || (() => {}));
    C.escape = escape;
    document.addEventListener("keydown", escape);

    box.querySelector(".hw-color").onchange = (e) => { C.color = e.target.value; };
    box.querySelectorAll(".hw-zoom").forEach((b) => b.onclick = () => {
      C.view.k = Math.min(3, Math.max(0.3, C.view.k * (b.dataset.z > 0 ? 1.2 : 1 / 1.2)));
      apply();
    });
    box.querySelector(".hw-fit").onclick = () => {
      if (!placed.length) return;
      const xs = placed.map((b) => b.x), ys = placed.map((b) => b.y);
      const r = svg.getBoundingClientRect();
      const w = Math.max(...placed.map((b) => b.x + geo[b.id].w)) - Math.min(...xs) + 80, h = Math.max(...placed.map((b) => b.y + geo[b.id].h)) - Math.min(...ys) + 80;
      const k = Math.min(3, Math.max(0.3, Math.min(r.width / w, r.height / h)));
      C.view = { k, x: Math.min(...xs) - 40, y: Math.min(...ys) - 40 };
      apply();
    };
    // full screen: the whole tab, so the bar and the side list come along
    box.querySelector(".hw-full").onclick = async () => {
      try {
        if (document.fullscreenElement) await document.exitFullscreen();
        else await box.requestFullscreen();
      } catch (err) { core.toast(String(err && err.message || err), true); }
    };
    box.querySelectorAll("[data-place]").forEach((b) => b.onclick = async () => {
      const n = placed.length;
      const x = snap(C.view.x + 60 + (n % 4) * (W + 80)), y = snap(C.view.y + 60 + Math.floor(n / 4) * 320);
      if (await api("POST", `${C.base}/canvas/place`, { block: b.dataset.place, x, y })) await reload();
    });
    box.querySelectorAll("[data-pins]").forEach((b) => b.onclick = () => pinsDialog(data.blocks.find((x) => x.id === b.dataset.pins)));
    box.querySelectorAll("[data-fz]").forEach((b) => b.onclick = () => imageDialog(data.blocks.find((x) => x.id === b.dataset.fz)));
  }

  function wireDialog(w) {
    if (!w) return;
    core.dialog(t("hw.wire"), `
      <label>${esc(t("hw.color"))} <select name="color">${COLORS.map((c) =>
        `<option value="${c}" ${c === w.color ? "selected" : ""}>${esc(t(`hw.c.${c}`))}</option>`).join("")}</select></label>
      <div class="actions"><button value="remove" class="danger" formnovalidate>${esc(t("hw.unwire"))}</button>
        <button value="cancel" formnovalidate>${esc(t("model.cancel"))}</button>
        <button value="ok" class="primary">${esc(t("model.save"))}</button></div>`, (form, dlg) => {
      form.onsubmit = async (ev) => {
        form.onsubmit = null;
        const v = ev.submitter && ev.submitter.value;
        if (v === "cancel") return;
        ev.preventDefault(); dlg.close();
        const ok = v === "remove"
          ? await api("DELETE", `${C.base}/items/${encodeURIComponent(w.id)}`)
          : await api("POST", `${C.base}/wires/${encodeURIComponent(w.id)}`, { color: form.querySelector('[name="color"]').value });
        if (ok) await reload();
      };
    });
  }

  /** A block's pins as lines: "11 GPIO17 signal". */
  function pinsDialog(b) {
    if (!b) return;
    const text = b.pins.map((p) => `${p.n} ${p.name}${p.role ? " " + p.role : ""}`).join("\n");
    core.dialog(t("hw.pinsOf", { name: b.name }), `
      <p class="note">${esc(t("hw.pinsHint"))}</p>
      <textarea name="pins" rows="14" spellcheck="false">${esc(text)}</textarea>
      <div class="actions"><button value="cancel" formnovalidate>${esc(t("model.cancel"))}</button>
        <button value="ok" class="primary">${esc(t("model.save"))}</button></div>`, (form, dlg) => {
      form.onsubmit = async (ev) => {
        form.onsubmit = null;
        if (ev.submitter && ev.submitter.value === "cancel") return;
        ev.preventDefault(); dlg.close();
        const roles = ["power", "ground", "signal", "audio", "video", "data"];
        const pins = form.querySelector('[name="pins"]').value.split("\n").map((l) => l.trim()).filter(Boolean).map((l, i) => {
          const parts = l.split(/\s+/);
          const n = /^\d+$/.test(parts[0]) ? Number(parts.shift()) : i + 1;
          const role = roles.includes((parts[parts.length - 1] || "").toLowerCase()) ? parts.pop().toLowerCase() : "";
          return { n, name: parts.join(" ") || String(n), role };
        });
        if (await api("POST", `${C.base}/canvas/pins`, { block: b.id, pins })) await reload();
      };
    });
  }

  /** Where a block's picture is served from, and its credit (ADR-0021). */
  function picture(b) {
    const kind = b.image ? b.image.kind : (b.fritzing ? "fritzing" : "none");
    const ref = b.image ? b.image.ref : b.fritzing;
    const own = `${C.base}/blocks/${encodeURIComponent(b.id)}/image.svg?v=${encodeURIComponent(kind === "drawn" ? b.pins.map((x) => x.n + x.name + x.role).join("|").length + "-" + b.pins.length : ref || "")}`;
    if (kind === "fritzing") return { href: `/api/fritzing/image?path=${encodeURIComponent(ref)}`, credit: `${t("hw.fzFrom")} ${ref} (CC BY-SA 3.0)` };
    if (kind === "wokwi") return { href: `/api/wokwi/image?name=${encodeURIComponent(ref)}`, credit: `${t("hw.wkFrom")} ${ref} (MIT)` };
    if (kind === "drawn") return { href: own, credit: t("hw.drawnFrom") };
    if (kind === "agent") return { href: own, credit: t("hw.agentFrom") };
    return null;
  }

  /** The libraries the Image window searches: the same view for each. */
  const LIBS = {
    fritzing: { search: (q, b) => `/api/fritzing/search?q=${encodeURIComponent(q)}&for=${encodeURIComponent(b.name)}`,
      part: (k) => `/api/fritzing/part?path=${encodeURIComponent(k)}`, image: (k) => `/api/fritzing/image?path=${encodeURIComponent(k)}`,
      key: (h) => h.path, label: (h) => h.name, sub: (h) => h.folder, hint: "hw.fzHint",
      about: (p) => `${esc(p.author)} · ${esc(p.license)} · <a href="${esc(p.source)}" target="_blank" rel="noreferrer">${esc(p.path)}</a>` },
    wokwi: { search: (q) => `/api/wokwi/search?q=${encodeURIComponent(q)}`,
      part: (k) => `/api/wokwi/part?name=${encodeURIComponent(k)}`, image: (k) => `/api/wokwi/image?name=${encodeURIComponent(k)}`,
      key: (h) => h.name, label: (h) => h.title, sub: (h) => t("hw.fzPins", { n: h.pins }), hint: "hw.wkHint",
      about: (p) => `Wokwi elements ${esc(p.version)} · ${esc(p.license)} · <a href="${esc(p.source)}" target="_blank" rel="noreferrer">${esc(p.name)}</a>` },
  };

  /** A block's picture: from Fritzing, from Wokwi, drawn from its pins, by
   *  the agent, or none. A library part brings its pins (and the board's ports). */
  function imageDialog(b, tab) {
    if (!b) return;
    const now = b.image ? b.image.kind : (b.fritzing ? "fritzing" : "none");
    tab = tab || (now === "none" ? "fritzing" : now);
    const tabs = ["fritzing", "wokwi", "drawn", "agent", "none"];
    const words = b.name.replace(/\(.*?\)/g, " ").replace(/[,;].*$/, "").split(/\s+/).filter(Boolean).slice(0, 6).join(" ");
    core.dialog(t("hw.imageFor", { name: b.name }), `
      <div class="img-tabs" role="tablist">${tabs.map((k) => `<button type="button" role="tab" data-tab="${k}" class="${k === tab ? "is-on" : ""}"
        aria-selected="${k === tab}">${esc(t(`hw.img.${k}`))}${k === now ? " ✓" : ""}</button>`).join("")}</div>
      <div class="img-body"></div>
      <div class="actions"><button value="cancel" formnovalidate>${esc(t("model.cancel"))}</button>
        <button value="search" class="img-find">${esc(t("hw.fzFind"))}</button>
        <button value="ok" class="primary" disabled>${esc(t("hw.fzUse"))}</button></div>`, (form, dlg) => {
      let chosen = null;
      const body = form.querySelector(".img-body"), useBtn = form.querySelector('button[value="ok"]'), findBtn = form.querySelector(".img-find");
      const library = (lib) => {
        const L = LIBS[lib];
        body.innerHTML = `<p class="note">${esc(t(L.hint))}</p>
          <label><input name="q" value="${esc(words)}" placeholder="${esc(t("hw.fzSearch"))}"></label>
          <div class="fz-results"><p class="note">…</p></div><div class="fz-pick"></div>`;
        const results = body.querySelector(".fz-results"), pick = body.querySelector(".fz-pick");
        const show = async (key) => {
          pick.innerHTML = `<p class="note">…</p>`;
          try {
            const p = await core.api("GET", L.part(key));
            chosen = { kind: lib, ref: key, title: p.title };
            useBtn.disabled = false;
            pick.innerHTML = `<div class="fz-part"><img src="${L.image(key)}" alt="">
              <div><strong>${esc(p.title)}</strong><br><small class="note">${L.about(p)}</small>
                <p class="note">${esc(t("hw.fzPins", { n: p.pins.length }))}: ${p.pins.map((x) => esc(x.name)).join(", ")}</p></div></div>`;
          } catch (err) { pick.innerHTML = `<p class="note warn">${esc(failed(err))}</p>`; }
        };
        const find = async () => {
          results.innerHTML = `<p class="note">…</p>`;
          try {
            const hits = await core.api("GET", L.search(body.querySelector('[name="q"]').value, b));
            results.innerHTML = hits.length ? `<ul>${hits.map((h) => `<li><button type="button" class="linkish" data-key="${esc(L.key(h))}">${esc(L.label(h))}</button>
              <small class="note">${esc(L.sub(h))}</small>${h.suggested ? ` <span class="pill">${esc(t("hw.fzSuggested"))}</span>` : ""}</li>`).join("")}</ul>`
              : `<p class="note">${esc(t("hw.fzNone"))}</p>`;
            results.querySelectorAll("[data-key]").forEach((x) => x.onclick = () => show(x.dataset.key));
          } catch (err) { results.innerHTML = `<p class="note warn">${esc(failed(err))}</p>`; }
        };
        body.find = find;
        find();
      };
      const open = (k) => {
        tab = k; chosen = null; useBtn.disabled = true; findBtn.hidden = !LIBS[k]; body.find = null;
        form.querySelectorAll("[data-tab]").forEach((x) => { x.classList.toggle("is-on", x.dataset.tab === k); x.setAttribute("aria-selected", x.dataset.tab === k); });
        useBtn.textContent = t(k === "agent" ? "hw.agentAsk" : k === "none" ? "hw.imgRemove" : "hw.fzUse");
        if (LIBS[k]) return library(k);
        if (k === "drawn") {
          body.innerHTML = `<p class="note">${esc(t("hw.drawnHint"))}</p>
            <div class="fz-part"><img class="img-preview" src="${C.base}/blocks/${encodeURIComponent(b.id)}/image.svg?drawn=1&v=${Date.now()}" alt=""></div>`;
          chosen = { kind: "drawn" }; useBtn.disabled = now === "drawn";
        } else if (k === "agent") {
          body.innerHTML = `<p class="note">${esc(t("hw.agentHint"))}</p>
            ${now === "agent" ? `<div class="fz-part"><img class="img-preview" src="${C.base}/blocks/${encodeURIComponent(b.id)}/image.svg?v=${Date.now()}" alt=""></div>` : ""}`;
          chosen = { kind: "agent" }; useBtn.disabled = false;
        } else {
          body.innerHTML = `<p class="note">${esc(t("hw.noneHint"))}</p>`;
          chosen = { kind: "none" }; useBtn.disabled = now === "none";
        }
      };
      form.querySelectorAll("[data-tab]").forEach((x) => x.onclick = () => open(x.dataset.tab));
      form.onsubmit = async (ev) => {
        const v = ev.submitter && ev.submitter.value;
        if (v === "cancel") { form.onsubmit = null; return; }
        ev.preventDefault();
        if (v === "search" || !chosen) { if (body.find) body.find(); return; }
        form.onsubmit = null;
        dlg.close();
        if (chosen.kind === "agent") return askAgent(b);
        if (await api("POST", `${C.base}/canvas/image`, { block: b.id, kind: chosen.kind, ref: chosen.ref || "" })) {
          core.toast(chosen.title ? t("hw.fzUsed", { title: chosen.title }) : t(`hw.imgSet.${chosen.kind}`));
          await reload();
        }
      };
      open(tab);
    });
  }

  /** The agent draws: its request is written into the chat box; the person adds to it and asks. */
  function askAgent(b) {
    const box = document.getElementById("edge-chat");
    const input = box && box.querySelector(".edge-chat__ask textarea");
    if (!input) { core.toast(t("hw.agentNoChat")); return; }
    input.value = t("hw.agentRequest", { name: b.name, n: b.pins.length });
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }

  // the label of the full-screen button follows the state (Esc leaves too)
  document.addEventListener("fullscreenchange", () => {
    const b = document.querySelector("#tab-canvas .hw-full");
    if (b) b.textContent = document.fullscreenElement ? t("hw.unfull") : t("hw.full");
  });

  window.canvasView = { draw };
})();
