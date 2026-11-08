/* Velo client — renders the component tree and morphs the DOM in place. */
(() => {
"use strict";
const CFG = window.VELO || {};
const NS = "http://www.w3.org/2000/svg";
const SVG = new Set(["svg","g","path","rect","line","circle","text","polyline","title"]);
const $ = (s, el = document) => el.querySelector(s);
const ICON = { info: "ℹ", success: "✓", warning: "!", error: "✕" };
const PAL = ["var(--accent)","#10b981","#f59e0b","#ef4444","#06b6d4","#a855f7","#ec4899","#84cc16"];

let sid = null;
try { sid = localStorage.getItem("velo:sid"); } catch (e) {}
if (!sid) {
  sid = (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36));
  try { localStorage.setItem("velo:sid", sid); } catch (e) {}
}

/* ------------------------------------------------------------------ DOM helpers */
function h(tag, attrs, ...kids) {
  const el = SVG.has(tag) ? document.createElementNS(NS, tag) : document.createElement(tag);
  if (attrs) for (const k in attrs) {
    const v = attrs[k];
    if (v === null || v === undefined || v === false) continue;
    if (k === "text") el.textContent = v;
    else if (k === "html") el.innerHTML = v;
    else if (k === "value") { el.value = v; if (tag === "input") el.setAttribute("value", v); }
    else if (k === "checked") el.checked = true;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

/* Morph `a` (live) into `b` (fresh). Keeps focus, caret, scroll and element identity. */
function morph(a, b) {
  if (a.nodeType !== b.nodeType || a.nodeName !== b.nodeName ||
      (a.nodeType === 1 && a.getAttribute("data-k") !== b.getAttribute("data-k"))) {
    a.replaceWith(b); return;
  }
  if (a.nodeType === 3 || a.nodeType === 8) { if (a.nodeValue !== b.nodeValue) a.nodeValue = b.nodeValue; return; }
  if (a.nodeType !== 1) return;
  for (const at of [...a.attributes]) if (!b.hasAttribute(at.name)) a.removeAttribute(at.name);
  for (const at of [...b.attributes]) if (a.getAttribute(at.name) !== at.value) a.setAttribute(at.name, at.value);
  if (a.tagName === "TEXTAREA") { if (document.activeElement !== a && a.value !== b.value) a.value = b.value; return; }
  morphKids(a, [...b.childNodes]);
  if (a.tagName === "INPUT") {
    if (a.type === "checkbox") a.checked = b.checked;
    else if (a.type !== "file" && document.activeElement !== a && a.value !== b.value) a.value = b.value;
  } else if (a.tagName === "SELECT" && document.activeElement !== a) a.value = b.value;
}
function morphKids(a, bk) {
  const ak = [...a.childNodes];
  for (let i = 0; i < bk.length; i++) i < ak.length ? morph(ak[i], bk[i]) : a.appendChild(bk[i]);
  for (let i = bk.length; i < ak.length; i++) ak[i].remove();
}

/* ------------------------------------------------------------------ formatting */
const fmt = (v) => {
  if (typeof v !== "number") return v == null ? "" : String(v);
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
  if (a >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (a >= 1e4) return (v / 1e3).toFixed(1).replace(/\.0$/, "") + "k";
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
};
const cell = (v) => typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 4 })
  : v === null || v === undefined ? "—" : typeof v === "boolean" ? (v ? "✓" : "✗") : String(v);
const cmp = (a, b) => (a == null) - (b == null) || (typeof a === "number" && typeof b === "number" ? a - b
  : String(a ?? "").localeCompare(String(b ?? ""), undefined, { numeric: true }));

/* ------------------------------------------------------------------ components */
const R = {};
function render(n) {
  const f = R[n.t] || R._unknown;
  const el = f(n.p || {}, n, n.k);
  if (n.k && el.setAttribute) el.setAttribute("data-k", n.k);
  return el;
}
const kids = (n) => (n.c || []).map(render);
const field = (p, ctrl, tag = "label") => h(tag, { class: "v-field" },
  p.label != null && p.label !== "" && h("span", { class: "v-label", text: p.label }), ctrl,
  p.help && h("span", { class: "v-help", text: p.help }));

R.title = (p) => h("div", { class: "v-title" }, h("h1", { text: p.text }), p.sub && h("p", { text: p.sub }));
R.heading = (p) => h("h" + p.level, { class: "v-h", text: p.text });
R.text = (p) => h("p", { class: "v-text" + (p.muted ? " muted" : "") + (p.small ? " small" : ""), text: p.text });
R.md = (p) => h("div", { class: "v-md", html: p.html });
R.html = (p) => h("div", { class: "v-html", html: p.html });
R.divider = () => h("hr", { class: "v-hr" });
R.space = (p) => h("div", { style: `height:${p.h}px` });
R.link = (p) => h("a", { class: "v-link", href: p.url, target: "_blank", rel: "noopener", text: p.text + " ↗" });
R.badge = (p) => h("span", { class: "v-badge " + p.kind, text: p.text });
R.code = (p) => h("div", { class: "v-code" },
  h("div", { class: "v-code-bar" }, h("span", { text: p.lang || "" }), h("button", { class: "v-copy", "data-copy": "", type: "button", text: "Copy" })),
  h("pre", {}, h("code", { text: p.code })));
R.alert = (p) => h("div", { class: "v-alert " + p.kind, role: "status" },
  h("span", { class: "v-alert-ic", text: ICON[p.kind] || "•" }),
  h("div", { class: "v-alert-b" }, p.title && h("strong", { text: p.title }), h("div", { class: "v-md", html: p.html })));
R.metric = (p) => h("div", { class: "v-metric" },
  h("div", { class: "v-metric-l", text: p.label }), h("div", { class: "v-metric-v", text: p.value }),
  p.delta != null && h("div", { class: "v-delta " + (p.good ? "up" : "down") }, (p.up ? "▲ " : "▼ ") + String(p.delta).replace(/^[+-]/, "")),
  p.help && h("div", { class: "v-metric-h", text: p.help }));
R.progress = (p) => h("div", { class: "v-progress" },
  h("div", { class: "v-progress-l" }, h("span", { text: p.label || "" }), h("span", { text: Math.round(p.value * 100) + "%" })),
  h("div", { class: "v-bar" }, h("div", { class: "v-bar-fill", style: `width:${(p.value * 100).toFixed(2)}%` })));
R.image = (p) => h("figure", { class: "v-img" },
  h("img", { src: p.src, alt: p.caption || "", loading: "lazy", style: p.width ? `max-width:${p.width}px` : null }),
  p.caption && h("figcaption", { text: p.caption }));
R.button = (p, n, k) => h("button", { class: `v-btn ${p.kind}${p.full ? " full" : ""}`, type: "button", "data-click": k, disabled: p.disabled },
  p.icon && h("span", { class: "v-btn-ic", text: p.icon }), p.label);
R.download = (p) => h("a", { class: "v-btn secondary", href: p.href, download: p.filename }, h("span", { class: "v-btn-ic", text: "⬇" }), p.label);
R.input = (p, n, k) => field(p, h("input", {
  class: "v-in", type: p.itype || "text", value: p.value ?? "", placeholder: p.ph, disabled: p.disabled,
  "data-bind": k, "data-kind": p.itype === "date" || p.itype === "color" ? "change" : "text", autocomplete: "off" }));
R.textarea = (p, n, k) => field(p, h("textarea", { class: "v-in", rows: p.rows, placeholder: p.ph, value: p.value ?? "", "data-bind": k, "data-kind": "text" }));
R.number = (p, n, k) => field(p, h("input", { class: "v-in", type: "number", value: p.value, min: p.min, max: p.max, step: p.step, "data-bind": k, "data-kind": "number" }));
R.slider = (p, n, k) => {
  const pct = p.max > p.min ? ((p.value - p.min) / (p.max - p.min)) * 100 : 0;
  return h("div", { class: "v-field" },
    h("div", { class: "v-label-row" }, h("span", { class: "v-label", text: p.label }), h("span", { class: "v-slider-v", text: fmt(p.value) + (p.suffix || "") })),
    h("input", { type: "range", class: "v-range", min: p.min, max: p.max, step: p.step, value: p.value, style: `--pct:${pct}%`,
      "data-bind": k, "data-kind": "range", "data-suffix": p.suffix || "" }),
    p.help && h("span", { class: "v-help", text: p.help }));
};
R.select = (p, n, k) => field(p, h("div", { class: "v-select" },
  h("select", { class: "v-in", "data-bind": k, "data-kind": "index" }, p.options.map((o, i) => h("option", { value: i, selected: i === p.index }, o)))));
R.radio = (p, n, k) => field(p, h("div", { class: "v-seg", role: "radiogroup" },
  p.options.map((o, i) => h("button", { class: "v-seg-b" + (i === p.index ? " on" : ""), type: "button", "data-set": k, "data-v": i }, o))), "div");
R.multiselect = (p, n, k) => {
  const sel = new Set(p.selected);
  return field(p, h("div", { class: "v-chips" },
    p.options.map((o, i) => h("button", { class: "v-chip" + (sel.has(i) ? " on" : ""), type: "button", "data-multi": k, "data-v": i }, o))), "div");
};
R.checkbox = (p, n, k) => h("label", { class: p.toggle ? "v-toggle" : "v-check" },
  h("input", { type: "checkbox", checked: p.value, "data-bind": k, "data-kind": "bool" }),
  h("span", { class: p.toggle ? "v-switch" : "v-box" }), h("span", { text: p.label }));
R.upload = (p, n, k) => field({ label: p.label && p.files && p.files.length ? p.label : null },
  h("label", { class: "v-drop" + (p.files && p.files.length ? " has" : "") },
    h("input", { type: "file", accept: p.accept, multiple: p.multiple, "data-bind": k, "data-kind": "file" }),
    h("div", { class: "v-drop-ic", text: p.files && p.files.length ? "✓" : "⇪" }),
    h("div", { class: "v-drop-t", text: p.files && p.files.length ? p.files.join(", ") : p.label }),
    h("div", { class: "v-drop-s", text: p.files && p.files.length ? "Click or drop to replace" : "Drag & drop or click to browse" + (p.accept ? ` · ${p.accept}` : "") })), "div");
R.chat = (p) => h("div", { class: "v-chat " + p.role }, h("div", { class: "v-avatar", text: p.avatar }), h("div", { class: "v-bubble v-md", html: p.html }));
R.chat_input = (p, n, k) => h("form", { class: "v-chatin", "data-submit": k },
  h("input", { class: "v-in", placeholder: p.ph, name: "q", autocomplete: "off" }),
  h("button", { class: "v-btn primary", type: "submit", "aria-label": "Send", text: "↑" }));
R.columns = (p, n) => h("div", { class: "v-cols gap-" + p.gap, style: `grid-template-columns:${(n.c || []).map((c) => `minmax(0,${c.p.w}fr)`).join(" ")}` }, kids(n));
R.col = (p, n) => h("div", { class: "v-stack" }, kids(n));
R.card = (p, n) => h("section", { class: "v-card" },
  (p.title || p.sub) && h("div", { class: "v-card-h" }, p.title && h("h3", { text: p.title }), p.sub && h("p", { text: p.sub })),
  h("div", { class: "v-stack" }, kids(n)));
R.row = (p, n) => h("div", { class: "v-row" }, kids(n));
R.container = (p, n) => h("div", { class: "v-stack" }, kids(n));
R.tabs = (p, n, k) => h("div", { class: "v-tabs" },
  h("div", { class: "v-tablist", role: "tablist" }, p.labels.map((l, i) => h("button", { class: "v-tab" + (i === p.index ? " on" : ""), type: "button", role: "tab", "data-tab": k, "data-v": i }, l))),
  (n.c || []).map((c, i) => h("div", { class: "v-panel v-stack" + (i === p.index ? " on" : ""), role: "tabpanel" }, kids(c))));
R.expander = (p, n, k) => h("details", { class: "v-exp", open: p.open, "data-exp": k, "data-open": p.open ? "1" : "0" },
  h("summary", {}, h("span", { text: p.label }), h("span", { class: "v-exp-ic", text: "⌄" })), h("div", { class: "v-stack v-exp-b" }, kids(n)));
R.error = (p) => h("div", { class: "v-error" }, h("strong", { text: "⚠ " + p.text }), p.tb && h("pre", { text: p.tb }));
R.notfound = (p) => h("div", { class: "v-empty-page" }, h("div", { class: "v-big", text: "404" }), h("p", { text: `No page at ${p.path}` }), h("a", { href: "/", "data-nav": "", class: "v-btn secondary", text: "Go home" }));
R._unknown = (p, n) => h("div", { class: "v-text muted", text: `Unknown component: ${n.t}` });

/* ---- tables (client-side search / sort / paging; state survives re-renders) */
const TS = {}, TP = {};
R.table = (p, n, k) => { TP[k] = p; TS[k] = TS[k] || { q: "", col: -1, dir: 1, page: 0 }; return table(p, k, TS[k]); };
function table(p, k, st) {
  let rows = p.rows;
  if (st.q) { const q = st.q.toLowerCase(); rows = rows.filter((r) => r.some((c) => c != null && String(c).toLowerCase().includes(q))); }
  if (st.col >= 0) { const c = st.col; rows = [...rows].sort((a, b) => cmp(a[c], b[c]) * st.dir); }
  const ps = p.page, pages = Math.max(1, Math.ceil(rows.length / ps));
  st.page = Math.min(st.page, pages - 1);
  const view = rows.slice(st.page * ps, (st.page + 1) * ps);
  const num = p.cols.map((_, ci) => p.rows.length > 0 && p.rows.every((r) => r[ci] == null || typeof r[ci] === "number"));
  return h("div", { class: "v-table", "data-table": k, "data-k": k },
    h("div", { class: "v-table-top" },
      p.search && h("input", { class: "v-in v-table-q", placeholder: "Search…", value: st.q, "data-tq": k }),
      h("span", { class: "v-table-n", text: `${rows.length.toLocaleString()} row${rows.length === 1 ? "" : "s"}` })),
    h("div", { class: "v-table-scroll", style: p.height ? `max-height:${p.height}px` : null },
      h("table", {},
        h("thead", {}, h("tr", {}, p.cols.map((c, ci) => h("th", { class: num[ci] ? "num" : null, "data-ts": k, "data-c": ci, title: "Sort" },
          c, h("span", { class: "v-sort", text: st.col === ci ? (st.dir > 0 ? "↑" : "↓") : "↕" }))))),
        h("tbody", {}, view.length ? view.map((r) => h("tr", {}, r.map((c, ci) => h("td", { class: num[ci] ? "num" : null, text: cell(c) }))))
          : h("tr", {}, h("td", { colspan: p.cols.length || 1, class: "v-empty", text: "No matching rows" }))))),
    pages > 1 && h("div", { class: "v-table-foot" },
      h("span", { text: `${(st.page * ps + 1).toLocaleString()}–${Math.min((st.page + 1) * ps, rows.length).toLocaleString()} of ${rows.length.toLocaleString()}` }),
      h("div", { class: "v-row" },
        h("button", { class: "v-btn ghost sm", type: "button", "data-tp": k, "data-d": -1, disabled: st.page === 0, text: "‹ Prev" }),
        h("span", { class: "v-pg", text: `${st.page + 1} / ${pages}` }),
        h("button", { class: "v-btn ghost sm", type: "button", "data-tp": k, "data-d": 1, disabled: st.page >= pages - 1, text: "Next ›" }))));
}
const retable = (k) => { const el = document.querySelector(`[data-table="${CSS.escape(k)}"]`); if (el) morph(el, table(TP[k], k, TS[k])); };

/* ---- charts (pure SVG, hover tooltips, light/dark aware) */
const CL = {}, CW = {};
function ticks(lo, hi, n = 5) {
  if (!(hi > lo)) hi = lo + 1;
  const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw)), f = raw / mag;
  const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag;
  const out = [];
  for (let v = Math.floor(lo / step) * step; v <= Math.ceil(hi / step) * step + step / 2; v += step) out.push(+v.toFixed(10));
  return out;
}
R.chart = (p, n, k) => {
  const W = CW[k] || 760, H = p.height || 300, S = p.series || [], N = (p.x || []).length;
  const wrap = h("div", { class: "v-chart", "data-chart": k, "data-k": k }, p.title && h("div", { class: "v-chart-t", text: p.title }));
  if (!N || !S.length) { wrap.append(h("div", { class: "v-empty", text: "No data" })); return wrap; }
  if (p.kind === "pie") return pie(p, wrap, H);
  const bar = p.kind === "bar", stack = bar && p.stacked;
  let vals = [];
  if (stack) for (let i = 0; i < N; i++) { let pos = 0, neg = 0; S.forEach((s) => { const v = s.data[i] || 0; v >= 0 ? (pos += v) : (neg += v); }); vals.push(pos, neg); }
  else S.forEach((s) => s.data.forEach((v) => v != null && vals.push(v)));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (bar || p.kind === "area") lo = Math.min(0, lo), hi = Math.max(0, hi);
  else { const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad; }
  const T = ticks(lo, hi); lo = T[0]; hi = T[T.length - 1];
  const m = { l: 54, r: 18, t: 12, b: 30 }, iw = W - m.l - m.r, ih = H - m.t - m.b, band = iw / N;
  const Y = (v) => m.t + ih - ((v - lo) / (hi - lo)) * ih;
  const X = (i) => bar ? m.l + band * (i + 0.5) : m.l + (N <= 1 ? iw / 2 : (i * iw) / (N - 1));
  const svg = h("svg", { viewBox: `0 0 ${W} ${H}`, class: "v-svg", role: "img" });
  T.forEach((t) => svg.append(h("line", { class: "v-grid" + (t === 0 ? " zero" : ""), x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t) }),
    h("text", { class: "v-axis", x: m.l - 10, y: Y(t) + 4, "text-anchor": "end", text: fmt(t) })));
  const every = Math.ceil(N / Math.max(2, Math.floor(iw / 90)));
  for (let i = 0; i < N; i += every) svg.append(h("text", { class: "v-axis", x: X(i), y: H - 8, "text-anchor": "middle", text: String(p.x[i]).slice(0, 14) }));
  if (bar) {
    const gw = band * 0.72, bw = stack ? gw : gw / S.length, base = [], baseN = [];
    S.forEach((s, si) => s.data.forEach((v, i) => {
      if (v == null) return;
      let y0 = 0;
      if (stack) { if (v >= 0) { y0 = base[i] || 0; base[i] = y0 + v; } else { y0 = baseN[i] || 0; baseN[i] = y0 + v; } }
      const x = m.l + band * i + (band - gw) / 2 + (stack ? 0 : si * bw);
      const y1 = Y(y0 + v), y2 = Y(y0);
      svg.append(h("rect", { class: "v-barr", x: x + 1, width: Math.max(1, bw - 2), y: Math.min(y1, y2), height: Math.max(1, Math.abs(y2 - y1)), rx: 4, style: `fill:${PAL[si % PAL.length]}` }));
    }));
    svg.append(h("rect", { class: "v-band", x: 0, y: m.t, width: band, height: ih }));
  } else {
    S.forEach((s, si) => {
      let d = "", pen = false, area = "", first = null, last = null;
      s.data.forEach((v, i) => {
        if (v == null) { pen = false; return; }
        d += (pen ? "L" : "M") + X(i).toFixed(1) + "," + Y(v).toFixed(1); pen = true;
        if (first === null) first = i; last = i;
      });
      if (p.kind === "area" && first !== null) {
        area = d + `L${X(last).toFixed(1)},${Y(Math.max(lo, 0))}L${X(first).toFixed(1)},${Y(Math.max(lo, 0))}Z`;
        svg.append(h("path", { d: area, class: "v-area", style: `fill:${PAL[si % PAL.length]}` }));
      }
      svg.append(h("path", { d, class: "v-line", style: `stroke:${PAL[si % PAL.length]}` }));
      if (N <= 40) s.data.forEach((v, i) => v != null && svg.append(h("circle", { cx: X(i), cy: Y(v), r: 3, class: "v-pt", style: `stroke:${PAL[si % PAL.length]}` })));
    });
    svg.append(h("line", { class: "v-guide", x1: 0, x2: 0, y1: m.t, y2: m.t + ih }));
    S.forEach((s, si) => svg.append(h("circle", { class: "v-dot", "data-s": si, r: 5, cx: -10, cy: -10, style: `fill:${PAL[si % PAL.length]}` })));
  }
  svg.append(h("rect", { class: "v-hit", x: m.l, y: m.t, width: iw, height: ih }));
  CL[k] = { p, W, m, iw, band, N, bar, X, Y };
  wrap.append(svg, h("div", { class: "v-tip" }));
  if (S.length > 1) wrap.append(legend(S.map((s) => s.name)));
  return wrap;
};
const legend = (names, extra) => h("div", { class: "v-legend" }, names.map((nm, i) => h("span", {}, h("i", { style: `background:${PAL[i % PAL.length]}` }), nm, extra ? h("b", { text: extra[i] }) : null)));
function pie(p, wrap, H) {
  const vals = p.series[0].data.map((v) => Math.max(0, v || 0)), tot = vals.reduce((a, b) => a + b, 0) || 1;
  const size = Math.min(H, 260), r = size / 2 - 6, ir = r * 0.62, c = size / 2;
  const svg = h("svg", { viewBox: `0 0 ${size} ${size}`, class: "v-svg v-pie", style: `max-width:${size}px` });
  let a0 = -Math.PI / 2;
  vals.forEach((v, i) => {
    const a1 = a0 + (v / tot) * Math.PI * 2 - 1e-6, big = a1 - a0 > Math.PI ? 1 : 0;
    const P = (a, rr) => `${(c + rr * Math.cos(a)).toFixed(2)},${(c + rr * Math.sin(a)).toFixed(2)}`;
    svg.append(h("path", { class: "v-slice", style: `fill:${PAL[i % PAL.length]}`,
      d: `M${P(a0, r)}A${r},${r} 0 ${big} 1 ${P(a1, r)}L${P(a1, ir)}A${ir},${ir} 0 ${big} 0 ${P(a0, ir)}Z` },
      h("title", { text: `${p.x[i]}: ${cell(v)} (${((v / tot) * 100).toFixed(1)}%)` })));
    a0 = a1 + 1e-6;
  });
  svg.append(h("text", { x: c, y: c - 2, "text-anchor": "middle", class: "v-pie-v", text: fmt(tot) }),
    h("text", { x: c, y: c + 16, "text-anchor": "middle", class: "v-axis", text: p.series[0].name }));
  wrap.append(h("div", { class: "v-pie-wrap" }, svg, legend(p.x.map(String), vals.map((v) => ((v / tot) * 100).toFixed(1) + "%"))));
  return wrap;
}
function fitCharts() {
  document.querySelectorAll(".v-chart[data-chart]").forEach((el) => {
    const k = el.dataset.chart, L = CL[k]; if (!L) return;
    const w = Math.round(el.clientWidth - 28);
    if (w > 120 && Math.abs(w - L.W) > 6) { CW[k] = w; morph(el, R.chart(L.p, null, k)); }
  });
}
let rzT; window.addEventListener("resize", () => { clearTimeout(rzT); rzT = setTimeout(fitCharts, 120); });
function hover(hit, e) {
  const wrap = hit.closest(".v-chart"), L = CL[wrap.dataset.chart]; if (!L) return;
  const svg = hit.ownerSVGElement, rc = svg.getBoundingClientRect(), sc = rc.width / L.W;
  const x = (e.clientX - rc.left) / sc;
  let i = L.bar ? Math.floor((x - L.m.l) / L.band) : Math.round(((x - L.m.l) / L.iw) * (L.N - 1));
  i = Math.max(0, Math.min(L.N - 1, i));
  const S = L.p.series;
  if (L.bar) { const b = $(".v-band", svg); b.setAttribute("x", L.m.l + L.band * i); b.classList.add("on"); }
  else {
    const g = $(".v-guide", svg); g.setAttribute("x1", L.X(i)); g.setAttribute("x2", L.X(i)); g.classList.add("on");
    svg.querySelectorAll(".v-dot").forEach((d) => { const v = S[+d.dataset.s].data[i]; if (v == null) return d.classList.remove("on");
      d.setAttribute("cx", L.X(i)); d.setAttribute("cy", L.Y(v)); d.classList.add("on"); });
  }
  const tip = $(".v-tip", wrap);
  morphKids(tip, [h("div", { class: "v-tip-x", text: String(L.p.x[i]) }),
    ...S.map((s, si) => h("div", { class: "v-tip-r" }, h("i", { style: `background:${PAL[si % PAL.length]}` }), h("span", { text: s.name }), h("b", { text: cell(s.data[i]) })))]);
  const wr = wrap.getBoundingClientRect(), px = rc.left - wr.left + L.X(i) * sc;
  tip.classList.add("on");
  const tw = tip.offsetWidth;
  tip.style.left = Math.max(4, Math.min(wr.width - tw - 4, px + (px + tw + 24 > wr.width ? -tw - 14 : 14))) + "px";
  tip.style.top = (rc.top - wr.top + 10) + "px";
}
function unhover(hit) {
  const wrap = hit.closest(".v-chart");
  wrap.querySelectorAll(".on").forEach((el) => el.classList.remove("on"));
}

/* ------------------------------------------------------------------ network */
let chain = Promise.resolve(), inflight = 0, loadT = null, refreshT = null, boot = null, lastNav = null;
const loading = (on) => {
  clearTimeout(loadT);
  if (on) loadT = setTimeout(() => $("#v-load").classList.add("on"), 140);
  else $("#v-load").classList.remove("on");
};
const setConn = (ok) => { const c = $("#v-conn"); c.className = ok ? "ok" : "bad"; c.title = ok ? "Connected" : "Reconnecting…"; };
function send(ev) { chain = chain.then(() => post(ev)); return chain; }
async function post(ev) {
  inflight++; loading(true);
  try {
    for (let tries = 0; ; tries++) {
      try {
        const r = await fetch("/api/render", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sid, path: location.pathname, event: ev || null }) });
        if (!r.ok) throw new Error("HTTP " + r.status);
        apply(await r.json()); setConn(true); return;
      } catch (e) {
        setConn(false);
        if (tries >= 3) { toast("Can't reach the server", "error"); console.error(e); return; }
        await new Promise((res) => setTimeout(res, 400 * (tries + 1)));
      }
    }
  } finally { inflight--; if (!inflight) loading(false); }
}
const timers = new Map();
function debounce(k, mk, ms) { clearTimeout(timers.get(k)?.id); timers.set(k, { id: setTimeout(() => { timers.delete(k); send(mk()); }, ms), mk }); }
function throttle(k, mk, ms) { const t = timers.get(k); if (t) { t.mk = mk; return; } const o = { mk }; o.id = setTimeout(() => { timers.delete(k); send(o.mk()); }, ms); timers.set(k, o); }
function flushKey(k) { const t = timers.get(k); if (t) { clearTimeout(t.id); timers.delete(k); send(t.mk()); } }
const flushAll = () => [...timers.keys()].forEach(flushKey);

function apply(d) {
  document.title = d.page ? `${d.page} · ${d.app.title}` : d.app.title;
  $("#v-brand-t").textContent = d.app.title;
  $("#v-top-t").textContent = d.page || d.app.title;
  morphKids($("#v-nav"), d.nav.map((it) => h("a", { href: it.path, "data-nav": "", class: "v-nav-i" + (it.path === location.pathname ? " on" : "") },
    h("span", { class: "v-nav-ic", text: it.icon }), h("span", { text: it.title }))));
  morphKids($("#v-side-content"), d.side.map(render));
  document.body.classList.toggle("no-side", !d.nav.length && !d.side.length);
  morphKids($("#v-root"), d.tree.map(render));
  requestAnimationFrame(fitCharts);
  $("#v-overlay").hidden = true;
  (d.toasts || []).forEach((t) => toast(t.text, t.kind));
  clearTimeout(refreshT);
  if (d.refresh) refreshT = setTimeout(() => { if (!document.hidden) send({ type: "tick" }); else refreshT = setTimeout(() => send({ type: "tick" }), 1000); }, d.refresh * 1000);
  if (d.navigate && d.navigate !== location.pathname) go(d.navigate);
}
function go(path) {
  if (path !== location.pathname) history.pushState({}, "", path);
  window.scrollTo({ top: 0 });
  send({ type: "nav" });
}
window.addEventListener("popstate", () => send({ type: "nav" }));

function toast(text, kind = "info") {
  const el = h("div", { class: "v-toast " + kind }, h("span", { class: "v-toast-ic", text: ICON[kind] || "•" }), h("span", { text }));
  $("#v-toasts").append(el);
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("in")));
  setTimeout(() => { el.classList.remove("in"); setTimeout(() => el.remove(), 300); }, 3600);
}

function stream() {
  if (!window.EventSource) return;
  const es = new EventSource("/api/stream?sid=" + encodeURIComponent(sid));
  es.addEventListener("hello", (e) => { const x = JSON.parse(e.data); if (boot && boot !== x.boot) send({ type: "tick" }); boot = x.boot; setConn(true); });
  es.addEventListener("reload", () => send({ type: "tick" }));
  es.addEventListener("rerun", () => send({ type: "tick" }));
  es.addEventListener("deverror", (e) => { $("#v-ov-pre").textContent = JSON.parse(e.data); $("#v-overlay").hidden = false; });
  es.onerror = () => setConn(false);
}

/* ------------------------------------------------------------------ events (delegated) */
const val = (t) => {
  const kind = t.dataset.kind;
  if (kind === "bool") return t.checked;
  if (kind === "number") { const n = parseFloat(t.value); return isNaN(n) ? null : n; }
  if (kind === "range" || kind === "index") return +t.value;
  return t.value;
};
const readFiles = (files) => Promise.all([...files].map((f) => new Promise((res, rej) => {
  const r = new FileReader();
  r.onload = () => res({ name: f.name, type: f.type, size: f.size, data: String(r.result).split(",")[1] || "" });
  r.onerror = rej; r.readAsDataURL(f);
})));

document.addEventListener("click", (e) => {
  const t = e.target; let el;
  if ((el = t.closest("[data-copy]"))) {
    const code = el.closest(".v-code").querySelector("code").textContent;
    (navigator.clipboard ? navigator.clipboard.writeText(code) : Promise.reject()).catch(() => {});
    el.textContent = "Copied ✓"; setTimeout(() => (el.textContent = "Copy"), 1200); return;
  }
  if ((el = t.closest("[data-nav]"))) { e.preventDefault(); document.body.classList.remove("side-open"); go(el.getAttribute("href")); return; }
  if ((el = t.closest("[data-click]"))) { flushAll(); send({ type: "click", k: el.dataset.click }); return; }
  if ((el = t.closest("[data-set]"))) {
    el.parentNode.querySelectorAll(".v-seg-b").forEach((b) => b.classList.toggle("on", b === el));
    send({ type: "set", k: el.dataset.set, v: +el.dataset.v }); return;
  }
  if ((el = t.closest("[data-multi]"))) {
    el.classList.toggle("on");
    send({ type: "set", k: el.dataset.multi, v: [...el.parentNode.querySelectorAll(".v-chip.on")].map((b) => +b.dataset.v) }); return;
  }
  if ((el = t.closest("[data-tab]"))) {
    const box = el.closest(".v-tabs"), i = +el.dataset.v;
    box.querySelectorAll(":scope>.v-tablist>.v-tab").forEach((b, j) => b.classList.toggle("on", j === i));
    box.querySelectorAll(":scope>.v-panel").forEach((p, j) => p.classList.toggle("on", j === i));
    requestAnimationFrame(fitCharts); send({ type: "set", k: el.dataset.tab, v: i }); return;
  }
  if ((el = t.closest("[data-ts]"))) {
    const k = el.dataset.ts, c = +el.dataset.c, st = TS[k];
    if (st.col === c) st.dir === 1 ? (st.dir = -1) : (st.col = -1, st.dir = 1); else { st.col = c; st.dir = 1; }
    retable(k); return;
  }
  if ((el = t.closest("[data-tp]"))) { TS[el.dataset.tp].page += +el.dataset.d; retable(el.dataset.tp); return; }
  if (t.closest("#v-theme")) {
    const nt = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = nt; try { localStorage.setItem("velo:theme", nt); } catch (x) {} return;
  }
  if (t.closest("#v-burger")) { document.body.classList.toggle("side-open"); return; }
  if (t.id === "v-scrim") document.body.classList.remove("side-open");
});
document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.dataset.tq) { const st = TS[t.dataset.tq]; st.q = t.value; st.page = 0; retable(t.dataset.tq); return; }
  const k = t.dataset.bind; if (!k) return;
  const kind = t.dataset.kind;
  if (kind === "range") {
    const mn = +t.min, mx = +t.max;
    t.style.setProperty("--pct", ((t.value - mn) / (mx - mn || 1)) * 100 + "%");
    const lab = t.parentNode.querySelector(".v-slider-v"); if (lab) lab.textContent = fmt(+t.value) + (t.dataset.suffix || "");
    throttle(k, () => ({ type: "set", k, v: val(t) }), 70);
  } else if (kind === "text" || kind === "number") debounce(k, () => ({ type: "set", k, v: val(t) }), 280);
  else if (kind === "change") debounce(k, () => ({ type: "set", k, v: val(t) }), 150);
});
document.addEventListener("change", (e) => {
  const t = e.target, k = t.dataset.bind; if (!k) return;
  const kind = t.dataset.kind;
  if (kind === "file") { readFiles(t.files).then((v) => send({ type: "set", k, v })); return; }
  if (kind === "text" || kind === "number" || kind === "range" || kind === "change") { timers.has(k) ? flushKey(k) : send({ type: "set", k, v: val(t) }); return; }
  send({ type: "set", k, v: val(t) });
});
document.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.dataset && e.target.dataset.bind && e.target.tagName === "INPUT") flushKey(e.target.dataset.bind); });
document.addEventListener("submit", (e) => {
  const f = e.target.closest("[data-submit]"); if (!f) return;
  e.preventDefault();
  const inp = f.querySelector("input"), v = inp.value.trim(); if (!v) return;
  inp.value = ""; flushAll(); send({ type: "submit", k: f.dataset.submit, v });
});
document.addEventListener("toggle", (e) => {
  const d = e.target; if (!d.dataset || !d.dataset.exp) return;
  if ((d.dataset.open === "1") === d.open) return;
  d.dataset.open = d.open ? "1" : "0"; send({ type: "set", k: d.dataset.exp, v: d.open });
}, true);
document.addEventListener("mousemove", (e) => { const hit = e.target.closest && e.target.closest(".v-hit"); if (hit) hover(hit, e); });
document.addEventListener("mouseout", (e) => { const hit = e.target.closest && e.target.closest(".v-hit"); if (hit && !(e.relatedTarget && hit.contains(e.relatedTarget))) unhover(hit); });
["dragover", "dragleave", "drop"].forEach((ev) => document.addEventListener(ev, (e) => {
  const d = e.target.closest && e.target.closest(".v-drop"); if (!d) return;
  e.preventDefault();
  d.classList.toggle("over", ev === "dragover");
  if (ev === "drop" && e.dataTransfer.files.length) {
    const inp = d.querySelector("input"); inp.files = e.dataTransfer.files; inp.dispatchEvent(new Event("change", { bubbles: true }));
  }
}));

window.velo = { send, toast, sid };
send({ type: "nav" });
stream();
})();
