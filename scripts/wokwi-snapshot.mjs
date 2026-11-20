// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 D-LAB-5
//
// The Wokwi elements (github.com/wokwi/wokwi-elements, MIT) as plain SVG
// pictures with their pins, for the edge's Image window (ADR-0021 in
// maker-5-shared). Run by a maintainer when Wokwi releases; the output is
// committed, so the edge fetches nothing and runs no third-party JavaScript.
//
//   mkdir /tmp/w && cd /tmp/w && npm i --ignore-scripts @wokwi/elements@1.9.2 jsdom@24.1.3
//   node --preserve-symlinks scripts/wokwi-snapshot.mjs /tmp/w maker_5_edge/parts/wokwi
//
// Writes <out>/<element>.svg and <out>/index.json:
//   {version, license, source, parts: [{name, title, width, height, pins: [{n, name, role, x, y}]}]}
//   width and height in CSS px; a pin's x and y as fractions of them (0 to 1).

import { createRequire } from "node:module";
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [modules, out] = process.argv.slice(2);
if (!modules || !out) {
  console.error("usage: wokwi-snapshot.mjs <folder with node_modules> <out>");
  process.exit(2);
}
const require = createRequire(join(modules, "package.json"));
const { JSDOM } = require("jsdom");
const dom = new JSDOM("<!doctype html><body></body>", { pretendToBeVisual: true });
for (const k of Object.getOwnPropertyNames(dom.window)) {
  if (k in globalThis) continue;
  try { globalThis[k] = dom.window[k]; } catch { /* a getter jsdom refuses */ }
}
for (const k of ["Event", "CustomEvent", "EventTarget"]) globalThis[k] = dom.window[k];   // jsdom's, not Node's
globalThis.window = dom.window;
globalThis.document = dom.window.document;

const pkgDir = join(modules, "node_modules", "@wokwi", "elements");
const pkg = JSON.parse(readFileSync(join(pkgDir, "package.json"), "utf8"));
require("@wokwi/elements");                 // the CommonJS build: the ESM one imports without extensions

const files = readdirSync(join(pkgDir, "dist", "esm")).filter((f) => /^[a-z0-9-]+-element\.js$/.test(f));
const title = (name) => name.split("-").map((w) => /^[a-z]*\d+[a-z]?$/.test(w) && /[a-z]/.test(w) && !/^v\d$/.test(w) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)).join(" ")
  .replace(/\bEsp32\b/, "ESP32").replace(/\bLed\b/g, "LED").replace(/\bLcd/g, "LCD").replace(/\bRgb\b/, "RGB")
  .replace(/\bHc Sr04\b/, "HC-SR04").replace(/\bIr\b/g, "IR").replace(/\bNtc\b/, "NTC").replace(/\bPir\b/, "PIR");

function role(pin) {
  const s = pin.signals || [];
  if (s.some((x) => x.type === "power" && /^(GND|VSS)$/i.test(x.signal || "")) || /^GND/i.test(pin.name)) return "ground";
  if (s.some((x) => x.type === "power") || /^(VCC|VDD|VIN|3V3|5V|3\.3V|V\+)/i.test(pin.name)) return "power";
  if (s.some((x) => ["i2c", "spi", "usart"].includes(x.type))) return "data";
  return "signal";
}

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
const parts = [];
for (const f of files.sort()) {
  const name = f.replace(/-element\.js$/, "");
  const el = document.createElement(`wokwi-${name}`);
  if (!el.shadowRoot && !el.updateComplete) continue;               // not one of its elements
  document.body.append(el);
  await el.updateComplete;
  // the element's picture: its top-level SVG that is shown (the buzzer also has a hidden note)
  const svg = el.shadowRoot && [...el.shadowRoot.querySelectorAll("svg")]
    .filter((x) => !x.parentElement?.closest?.("svg") && !/visibility:\s*hidden/.test(x.getAttribute("style") || ""))[0];
  if (!svg) { el.remove(); continue; }
  svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const css = (el.constructor.elementStyles || []).map((s) => s.cssText || "").join("\n").replace(/:host\b[^{]*\{[^}]*\}/g, "");
  if (css.trim()) {
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
    style.textContent = css;
    svg.insertBefore(style, svg.firstChild);
  }
  const vb = (svg.getAttribute("viewBox") || "").split(/[\s,]+/).map(Number);
  // pinInfo is in CSS pixels of the element as drawn; the picture says its size in mm or px
  const px = (v) => { const m = /^([\d.]+)\s*(mm|px)?$/.exec(v || ""); return m ? Number(m[1]) * (m[2] === "mm" ? 96 / 25.4 : 1) : null; };
  const w = px(svg.getAttribute("width")) || vb[2], h = px(svg.getAttribute("height")) || vb[3];
  const frac = (v, d) => (d ? Math.round((v / d) * 1000) / 1000 : null);
  const pins = (el.pinInfo || []).map((p, i) => ({ n: i + 1, name: String(p.name).slice(0, 40), role: role(p), x: frac(p.x, w), y: frac(p.y, h) }));
  // HTML entities are not XML ones: the picture is read as XML
  writeFileSync(join(out, `${name}.svg`), svg.outerHTML.replace(/&nbsp;/g, "&#160;") + "\n");
  parts.push({ name, title: title(name), width: w ? Math.round(w) : null, height: h ? Math.round(h) : null, pins });
  el.remove();
}
writeFileSync(join(out, "index.json"), JSON.stringify({
  version: pkg.version, license: pkg.license, source: "https://github.com/wokwi/wokwi-elements",
  copyright: "Copyright (c) 2020 Uri Shaked", parts,
}, null, 1) + "\n");
writeFileSync(join(out, "LICENSE"), readFileSync(join(pkgDir, "LICENSE"), "utf8"));
console.log(`${parts.length} elements, ${parts.reduce((n, p) => n + p.pins.length, 0)} pins → ${out}`);
