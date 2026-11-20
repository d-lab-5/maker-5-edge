/* SPDX-License-Identifier: GPL-3.0-or-later
 * Wire routing for the hardware canvas (ADR-0014 in maker-5-shared), mirrored
 * by git_repo.py for hardware/wiring.svg, so the two pictures agree.
 *
 * Each wire leaves its pin straight out for a stub, then finds its way on a
 * 10-unit grid with A*: never through a part, few bends, and away from the
 * wires routed before it (running along one costs more than crossing it).
 * Short wires go first, so they stay straight. Where a horizontal stretch
 * still crosses a vertical one, it hops over it in a half circle.
 *
 *   window.wireRoute.route(ends, rects) → [[{x, y}, …] per wire]
 *   window.wireRoute.path(points, others) → an SVG path with the hops
 */
(() => {
  "use strict";
  // in front of a part's pins the stubs need the room: nothing runs there but them
  const G = 10, STUB = 30, CLEAR = 8, SIDE = STUB - 8, MARGIN = 200, HOP = 5;
  const BEND = 4, ALONG = 25, ACROSS = 2, MAX_EXPAND = 250000;
  const DX = [1, 0, -1, 0], DY = [0, 1, 0, -1];          // right, down, left, up

  /** Point a pin's stub reaches: straight out of the part, on the grid. */
  const stub = (p) => ({ x: Math.round((p.x + p.side * STUB) / G) * G, y: Math.round(p.y / G) * G });

  /** A small binary heap of [priority, value]. */
  function Heap() { this.a = []; }
  Heap.prototype.push = function (k, v) {
    const a = this.a; a.push([k, v]);
    for (let i = a.length - 1; i > 0;) { const j = (i - 1) >> 1; if (a[j][0] <= a[i][0]) break; [a[i], a[j]] = [a[j], a[i]]; i = j; }
  };
  Heap.prototype.pop = function () {
    const a = this.a, top = a[0], last = a.pop();
    if (a.length) {
      a[0] = last;
      for (let i = 0; ;) {
        const l = 2 * i + 1, r = l + 1; let m = i;
        if (l < a.length && a[l][0] < a[m][0]) m = l;
        if (r < a.length && a[r][0] < a[m][0]) m = r;
        if (m === i) break; [a[i], a[m]] = [a[m], a[i]]; i = m;
      }
    }
    return top;
  };

  /** The simple way, when there is no grid route: out, across, in. */
  function simple(a, b) {
    const sa = { x: a.x + a.side * STUB, y: a.y }, sb = { x: b.x + b.side * STUB, y: b.y }, mx = (sa.x + sb.x) / 2;
    return [{ x: a.x, y: a.y }, sa, { x: mx, y: sa.y }, { x: mx, y: sb.y }, sb, { x: b.x, y: b.y }];
  }

  /** Corners only: drop the points in the middle of a straight run. */
  function corners(pts) {
    const out = [];
    for (const p of pts) {
      const n = out.length;
      if (n && out[n - 1].x === p.x && out[n - 1].y === p.y) continue;
      if (n >= 2) {
        const q = out[n - 1], r = out[n - 2];
        if ((r.x === q.x && q.x === p.x) || (r.y === q.y && q.y === p.y)) { out[n - 1] = p; continue; }
      }
      out.push({ ...p });
    }
    return out;
  }

  /** ends: [[pinA, pinB]] with {x, y, side}; rects: the parts [{x, y, w, h}]. */
  function route(ends, rects) {
    if (!ends.length) return [];
    const xs = [], ys = [];
    for (const r of rects) { xs.push(r.x, r.x + r.w); ys.push(r.y, r.y + r.h); }
    for (const [a, b] of ends) { xs.push(a.x, b.x); ys.push(a.y, b.y); }
    const x0 = Math.floor((Math.min(...xs) - MARGIN) / G) * G, y0 = Math.floor((Math.min(...ys) - MARGIN) / G) * G;
    const cols = Math.ceil((Math.max(...xs) + MARGIN - x0) / G) + 1, rows = Math.ceil((Math.max(...ys) + MARGIN - y0) / G) + 1;
    if (cols * rows > 400000) return ends.map(([a, b]) => simple(a, b));   // too far apart for the grid
    const blocked = new Uint8Array(cols * rows);
    for (const r of rects) {
      const i0 = Math.ceil((r.x - SIDE - x0) / G), i1 = Math.floor((r.x + r.w + SIDE - x0) / G);
      const j0 = Math.ceil((r.y - CLEAR - y0) / G), j1 = Math.floor((r.y + r.h + CLEAR - y0) / G);
      for (let j = Math.max(0, j0); j <= Math.min(rows - 1, j1); j++)
        for (let i = Math.max(0, i0); i <= Math.min(cols - 1, i1); i++) blocked[j * cols + i] = 1;
    }
    const usedH = new Uint8Array(cols * rows), usedV = new Uint8Array(cols * rows);
    const order = ends.map((e, k) => k).sort((p, q) => {
      const len = (k) => Math.abs(ends[k][0].x - ends[k][1].x) + Math.abs(ends[k][0].y - ends[k][1].y);
      return len(p) - len(q) || p - q;
    });
    const out = new Array(ends.length);
    for (const k of order) {
      const [a, b] = ends[k];
      const sa = stub(a), sb = stub(b);
      const si = (sa.x - x0) / G, sj = (sa.y - y0) / G, gi = (sb.x - x0) / G, gj = (sb.y - y0) / G;
      const start = sj * cols + si, goal = gj * cols + gi;
      const found = astar(start, goal, a.side > 0 ? 0 : 2, cols, rows, blocked, usedH, usedV);
      if (!found) { out[k] = simple(a, b); continue; }
      for (let n = 1; n < found.length; n++) {
        const p = found[n - 1], q = found[n];
        (Math.abs(p - q) === 1 ? usedH : usedV)[p] = 1;
        (Math.abs(p - q) === 1 ? usedH : usedV)[q] = 1;
      }
      const pts = found.map((c) => ({ x: x0 + (c % cols) * G, y: y0 + Math.floor(c / cols) * G }));
      out[k] = fit(corners([{ x: a.x, y: sa.y }, ...pts, { x: b.x, y: sb.y }]), a, b);
    }
    return out;
  }

  /** The grid route, lined up on the pins themselves: a pin is rarely on the
   *  grid, so the first and last horizontal runs move to the pin's height. */
  function fit(pts, a, b) {
    if (pts.length === 2) {                                         // one straight run: a jog halfway if the pins differ
      const mx = Math.round((a.x + b.x) / 2 / G) * G;
      return corners(a.y === b.y ? [{ x: a.x, y: a.y }, { x: b.x, y: b.y }]
        : [{ x: a.x, y: a.y }, { x: mx, y: a.y }, { x: mx, y: b.y }, { x: b.x, y: b.y }]);
    }
    const n = pts.length - 1;
    pts[0].y = a.y;
    if (pts[1].x !== pts[0].x) pts[1].y = a.y;                    // the first run is horizontal: at the pin's height
    pts[n].y = b.y;
    if (pts[n - 1].x !== pts[n].x) pts[n - 1].y = b.y;
    return corners(pts);
  }

  function astar(start, goal, dir0, cols, rows, blocked, usedH, usedV) {
    const N = cols * rows;
    const cost = new Float64Array(N * 4).fill(Infinity), from = new Int32Array(N * 4).fill(-1);
    const gi = goal % cols, gj = Math.floor(goal / cols);
    const h = (c) => Math.abs((c % cols) - gi) + Math.abs(Math.floor(c / cols) - gj);
    const heap = new Heap();
    cost[start * 4 + dir0] = 0;
    heap.push(h(start), start * 4 + dir0);
    let expanded = 0;
    while (heap.a.length) {
      const [, s] = heap.pop();
      const c = s >> 2, d = s & 3;
      if (c === goal) {
        const path = [];
        for (let x = s; x !== -1; x = from[x]) path.push(x >> 2);
        return path.reverse();
      }
      if (++expanded > MAX_EXPAND) return null;
      const ci = c % cols, cj = Math.floor(c / cols);
      for (let nd = 0; nd < 4; nd++) {
        if (nd === ((d + 2) & 3)) continue;                         // no turning back
        const ni = ci + DX[nd], nj = cj + DY[nd];
        if (ni < 0 || nj < 0 || ni >= cols || nj >= rows) continue;
        const n = nj * cols + ni;
        if (blocked[n] && n !== goal) continue;
        const horizontal = nd === 0 || nd === 2;
        const step = 1 + (nd !== d ? BEND : 0) + ((horizontal ? usedH : usedV)[n] ? ALONG : 0) + ((horizontal ? usedV : usedH)[n] ? ACROSS : 0);
        const ns = n * 4 + nd, nc = cost[s] + step;
        if (nc < cost[ns]) { cost[ns] = nc; from[ns] = s; heap.push(nc + h(n), ns); }
      }
    }
    return null;
  }

  /** The straight stretches of a route. */
  function segments(pts) {
    const out = [];
    for (let i = 1; i < pts.length; i++) out.push({ a: pts[i - 1], b: pts[i], h: pts[i - 1].y === pts[i].y });
    return out;
  }

  /** An SVG path along the points, hopping over the vertical stretches of
   *  `others` (the other wires' points) where a horizontal one crosses them. */
  function path(pts, others) {
    const vertical = [];
    for (const o of others) for (const s of segments(o)) if (!s.h && s.a.x === s.b.x) vertical.push(s);
    let d = `M${pts[0].x},${pts[0].y}`;
    for (const s of segments(pts)) {
      if (!s.h) { d += ` L${s.b.x},${s.b.y}`; continue; }
      const dir = Math.sign(s.b.x - s.a.x) || 1, y = s.a.y;
      const lo = Math.min(s.a.x, s.b.x) + HOP + 2, hi = Math.max(s.a.x, s.b.x) - HOP - 2;
      const xs = [...new Set(vertical.filter((v) => v.a.x > lo && v.a.x < hi
        && y > Math.min(v.a.y, v.b.y) + HOP && y < Math.max(v.a.y, v.b.y) - HOP).map((v) => v.a.x))]
        .sort((p, q) => dir * (p - q));
      let last = s.a.x - dir * HOP * 3;
      for (const x of xs) {
        if (dir * (x - last) < HOP * 2.5) continue;                 // two crossings too close: one hop
        d += ` L${x - dir * HOP},${y} A${HOP},${HOP} 0 0 ${dir > 0 ? 1 : 0} ${x + dir * HOP},${y}`;
        last = x;
      }
      d += ` L${s.b.x},${s.b.y}`;
    }
    return d;
  }

  window.wireRoute = { route, path, simple, stub, G, STUB };
})();
