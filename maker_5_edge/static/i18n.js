// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 D-LAB-5
//
// i18n.js — Maker-5 Edge in English (the default), German and French.
//
// The strings live in i18n.json: {en, de, fr} by key for what this tool
// draws, and edge.{de, fr} by exact English text for the panels the edge
// layer draws (edge.js). The header (core/_base.html) and the edge panels
// belong to the templates and are not edited: their labels are translated
// here, by element id and by text, after they are drawn. A text with no
// translation stays English.
//
// window.i18n: t(key, vars), lang, setLang(code), apply(root), onChange(fn)

"use strict";

(function () {
  const LANGS = ["en", "de", "fr"];
  const KEY = "maker5.lang";
  let lang = "en";
  try { const v = localStorage.getItem(KEY); if (LANGS.includes(v)) lang = v; } catch (_) { /* private mode */ }
  document.documentElement.lang = lang;          // edge.js sends the chat this language

  let table = { en: {}, de: {}, fr: {}, edge: { de: {}, fr: {} } };
  const listeners = [];
  const fill = (s, vars) => String(s).replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? vars[k] : m));

  function t(key, vars) {
    const s = (table[lang] && table[lang][key]) ?? table.en[key] ?? key;
    return fill(s, vars);
  }

  // [data-i18n] text, [data-i18n-title], [data-i18n-placeholder]
  function apply(root) {
    (root || document).querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    (root || document).querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
    (root || document).querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  }

  // ---- the header (core/_base.html), by id
  function header() {
    const set = (sel, key, titleKey) => {
      const el = document.querySelector(sel);
      if (!el) return;
      // a button may hold more than its label (the agent dot): change the first text only
      const txt = [...el.childNodes].find((n) => n.nodeType === 3 && n.textContent.trim());
      if (txt) txt.textContent = t(key);
      if (titleKey) el.title = t(titleKey);
    };
    set("#core-about", "core.about", "core.aboutTitle");
    set("#core-connect", "core.agent", "core.agentTitle");
    set("#core-restart", "core.restart", "core.restartTitle");
    set("#core-stop", "core.stop", "core.stopTitle");
    const theme = document.getElementById("core-theme");
    if (theme) {
      const label = theme.closest("label");
      const txt = label && [...label.childNodes].find((n) => n.nodeType === 3 && n.textContent.trim());
      if (txt) txt.textContent = t("core.theme") + " ";
      if (label) label.title = t("core.themeTitle");
      [...theme.options].forEach((o) => { o.textContent = t(`core.${o.value}`); });
    }
  }

  // ---- the edge panels (edge.js), by exact English text; originals are kept
  // so a switch back to English (or to the other language) works.
  const orig = new WeakMap();      // text node / element -> {text, ph, help, title}
  function edgeText(en) {
    if (lang === "en") return en;
    const m = table.edge[lang] || {};
    if (en in m) return m[en];
    const k = en.trim();
    return k in m ? en.replace(k, m[k]) : en;
  }
  function edgePanel(box) {
    if (!box) return;
    const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const p = n.parentElement;
      // only the panel's own labels, never what was said in the chat
      if (!p || p.closest(".edge-chat__log, .edge-chat__me, .edge-chat__them, textarea")) continue;
      if (!orig.has(n)) orig.set(n, n.textContent);
      const want = edgeText(orig.get(n));
      if (n.textContent !== want) n.textContent = want;
    }
    box.querySelectorAll("[placeholder], [data-help], [title]").forEach((el) => {
      if (!orig.has(el)) orig.set(el, { ph: el.getAttribute("placeholder"), help: el.getAttribute("data-help"), title: el.getAttribute("title") });
      const o = orig.get(el);
      for (const [attr, v] of [["placeholder", o.ph], ["data-help", o.help], ["title", o.title]]) {
        if (v == null) continue;
        const want = edgeText(v);
        if (el.getAttribute(attr) !== want) el.setAttribute(attr, want);
      }
    });
  }
  function watchEdge() {
    ["edge-chat", "edge-connections"].forEach((id) => {
      const box = document.getElementById(id);
      if (!box) return;
      edgePanel(box);
      new MutationObserver(() => edgePanel(box)).observe(box, { childList: true, subtree: true, characterData: true });
    });
  }

  function setLang(code) {
    if (!LANGS.includes(code) || code === lang) return;
    lang = code;
    try { localStorage.setItem(KEY, code); } catch (_) { /* fine */ }
    document.documentElement.lang = code;
    apply(); header();
    ["edge-chat", "edge-connections"].forEach((id) => edgePanel(document.getElementById(id)));
    listeners.forEach((fn) => fn(code));
  }

  const ready = fetch(document.currentScript.src.replace(/i18n\.js(\?.*)?$/, "i18n.json"))
    .then((r) => r.json()).then((j) => { table = j; })
    .catch(() => { /* English keys stay as they are */ })
    .then(() => {
      apply(); header(); watchEdge();
      const pick = document.getElementById("lang-pick");
      if (pick) { pick.value = lang; pick.onchange = () => setLang(pick.value); }
    });

  window.i18n = {
    t, apply, setLang, ready,
    get lang() { return lang; },
    onChange: (fn) => listeners.push(fn),
  };
})();
