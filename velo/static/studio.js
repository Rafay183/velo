/* Velo Studio — drag & drop builder for Velo apps. Vanilla JS, no build step. */
(() => {
"use strict";
const CFG = window.STUDIO || {};
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clone = (o) => JSON.parse(JSON.stringify(o));
const isExpr = (v) => typeof v === "string" && v.startsWith("=") && v.length > 1;
const IDENT = /^[A-Za-z][A-Za-z0-9_]*$/;

let spec = null, CAT = null, TPLS = [], problems = [], file = "";
let selId = null, pageIdx = 0, view = "design", device = "desktop";
let undo = [], redo = [], typingSnap = null, lastField = null;
let saveT = null, codeT = null, saving = false, dirty = false;
const activeTab = new Map();
let drag = null;

/* =================================================================== spec helpers */
const page = () => spec.pages[Math.min(pageIdx, spec.pages.length - 1)];
const uid = () => "n" + Math.random().toString(36).slice(2, 10);
const meta = (t) => CAT.components[t] || { label: t, icon: "?", props: [] };

function slotCount(n) {
  const k = meta(n.type).slots, p = n.props || {};
  if (k === "columns") return Math.max(1, widths(p.widths).length);
  if (k === "tabs") return Math.max(1, asList(p.labels).length || 1);
  return k ? 1 : 0;
}
function widths(w) {
  if (typeof w === "number") return Array(Math.max(1, w)).fill(1);
  const out = String(w ?? "1,1").split(/[,;\s]+/).map(Number).filter((x) => x > 0);
  return out.length ? out : [1, 1];
}
const asList = (v) => Array.isArray(v) ? v.filter((x) => x !== "" && x != null) : String(v ?? "").split("\n").map((s) => s.trim()).filter(Boolean);
function syncSlots(n) {
  if (!meta(n.type).slots) return;
  const want = slotCount(n);
  n.slots = n.slots || [];
  while (n.slots.length < want) n.slots.push([]);
  if (n.slots.length > want) { const extra = n.slots.splice(want).flat(); n.slots[want - 1].push(...extra); }
}
function* walk(nodes) { for (const n of nodes || []) { yield n; for (const s of n.slots || []) yield* walk(s); } }
function* allNodes() { for (const p of spec.pages) { yield* walk(p.body); yield* walk(p.sidebar); } }
function find(id, pages = spec.pages) {
  for (let pi = 0; pi < pages.length; pi++) {
    for (const zone of ["body", "sidebar"]) {
      const r = findIn(pages[pi][zone], id, null);
      if (r) return Object.assign(r, { page: pi, zone });
    }
  }
  return null;
}
function findIn(arr, id, parent) {
  for (let i = 0; i < (arr || []).length; i++) {
    const n = arr[i];
    if (n.id === id) return { node: n, arr, index: i, parent };
    for (const s of n.slots || []) { const r = findIn(s, id, n); if (r) return r; }
  }
  return null;
}
function zoneArr(zid) {
  if (zid === "body") return page().body;
  if (zid === "side") return page().sidebar;
  const [id, i] = zid.split(":"); const f = find(id);
  return f && f.node.slots ? f.node.slots[+i] : null;
}
function vars() {
  const out = [];
  for (const k of Object.keys(spec.state || {})) out.push({ name: k, kind: "state", type: Array.isArray(spec.state[k]) ? "list" : typeof spec.state[k] });
  for (const p of spec.pages) for (const z of ["body", "sidebar"]) for (const n of walk(p[z]))
    if (meta(n.type).var && n.props && n.props.name) out.push({ name: n.props.name, kind: "widget", type: n.type, page: p.path, id: n.id });
  return out;
}
function uniqueVar(base, ignoreId) {
  const used = new Set(vars().filter((v) => v.id !== ignoreId).map((v) => v.name));
  for (const h of CAT.helpers) used.add(h);
  if (!used.has(base)) return base;
  let i = 2; while (used.has(base + i)) i++;
  return base + i;
}
function makeNode(type) {
  const m = meta(type), props = {};
  for (const d of m.props) props[d.name] = clone(d.default ?? null);
  const n = { id: uid(), type, props };
  if (m.var) props.name = uniqueVar(props.name || type);
  if (m.slots) { n.slots = []; syncSlots(n); }
  return n;
}
function cloneNode(n) {
  const c = clone(n);
  for (const x of walk([c])) { x.id = uid(); if (meta(x.type).var && x.props.name) x.props.name = uniqueVar(x.props.name.replace(/\d+$/, "") || x.type); }
  return c;
}

/* =================================================================== history + saving */
const snap = () => JSON.stringify(spec);
function commit() { undo.push(snap()); if (undo.length > 300) undo.shift(); redo = []; updUndo(); }
function updUndo() { $("#s-undo").disabled = !undo.length; $("#s-redo").disabled = !redo.length; }
function doUndo() { if (!undo.length) return; redo.push(snap()); spec = JSON.parse(undo.pop()); afterSwap(); }
function doRedo() { if (!redo.length) return; undo.push(snap()); spec = JSON.parse(redo.pop()); afterSwap(); }
function afterSwap() { if (pageIdx >= spec.pages.length) pageIdx = 0; if (selId && !find(selId)) selId = null; updUndo(); changed(true, true); }

function changed(inspector = true, panes = false) {
  renderCanvas();
  if (inspector) renderInspector();
  if (panes) { renderPages(); renderAppPane(); $("#s-app-title").value = spec.app.title; }
  dirty = true; setSave("dirty");
  clearTimeout(saveT); saveT = setTimeout(save, 450);
  if (view === "code") { clearTimeout(codeT); codeT = setTimeout(loadCode, 300); }
}
function setSave(s, msg) {
  const el = $("#s-save");
  el.className = "s-save " + (s === "dirty" ? "dirty" : s === "err" ? "err" : "");
  el.textContent = s === "dirty" ? "Unsaved…" : s === "saving" ? "Saving…" : s === "err" ? (msg || "Save failed") : "Saved ✓";
}
async function save() {
  if (saving) { clearTimeout(saveT); saveT = setTimeout(save, 300); return; }
  saving = true; setSave("saving");
  try {
    const body = JSON.stringify({ spec });
    const r = await fetch("/api/save", { method: "POST", headers: { "Content-Type": "application/json" }, body });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || r.status);
    dirty = false; problems = d.problems || []; setSave("ok"); renderProblems(); markProblems();
    if (selId) renderNodeProblems();
  } catch (e) { setSave("err", "Save failed"); toast("Could not save: " + e.message, "error"); }
  finally { saving = false; }
}
window.addEventListener("beforeunload", () => { if (dirty && navigator.sendBeacon) navigator.sendBeacon("/api/save", JSON.stringify({ spec })); });

/* =================================================================== palette */
function renderPalette(q = "") {
  q = q.trim().toLowerCase();
  const html = CAT.groups.map((g) => {
    const items = Object.entries(CAT.components).filter(([t, m]) => m.group === g &&
      (!q || (m.label + " " + t + " " + (m.desc || "")).toLowerCase().includes(q)));
    if (!items.length) return "";
    return `<div class="s-group"><div class="s-group-h">${esc(g)}</div><div class="s-grid">${items.map(([t, m]) =>
      `<button class="s-tile" draggable="true" data-new="${t}" title="${esc(m.desc || "")}"><span class="s-tile-ic">${esc(m.icon)}</span><span>${esc(m.label)}</span></button>`).join("")}</div></div>`;
  }).join("");
  $("#s-palette").innerHTML = html || `<p class="s-tip">No component matches “${esc(q)}”.</p>`;
}

/* =================================================================== canvas previews */
function tpl(v) {
  if (v == null || v === "") return "";
  if (isExpr(v)) return `<span class="s-fx">ƒ ${esc(v.slice(1))}</span>`;
  return esc(v).replace(/\{([^{}]+)\}/g, '<span class="s-var">{$1}</span>');
}
function mdLite(s) {
  if (isExpr(s)) return tpl(s);
  let h = tpl(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(])_([^_]+)_(?=[\s).,!?]|$)/g, "$1<i>$2</i>").replace(/\[([^\]]+)\]\(([^)]+)\)/g, "<a>$1</a>");
  return h.split(/\n{2,}/).map((b) => {
    const lines = b.split("\n");
    if (lines.every((l) => /^\s*[-*] /.test(l))) return "<ul>" + lines.map((l) => "<li>" + l.replace(/^\s*[-*] /, "") + "</li>").join("") + "</ul>";
    const m = b.match(/^(#{1,4}) (.*)/); if (m) return `<h${m[1].length + 1}>${m[2]}</h${m[1].length + 1}>`;
    return "<p>" + lines.join("<br>") + "</p>";
  }).join("");
}
const field = (n, label, ctrl, help) => `<div class="v-field"><span class="v-label-row" style="display:flex;justify-content:space-between;gap:8px">
  <span class="v-label">${tpl(label)}</span><span class="s-var" title="variable">${esc(n.props.name || "")}</span></span>${ctrl}${help ? `<span class="v-help">${tpl(help)}</span>` : ""}</div>`;
function csvRows(v) {
  if (typeof v !== "string" || isExpr(v) || !v.trim()) return null;
  const lines = v.trim().split("\n").filter((l) => l.trim());
  const cols = lines[0].split(",").map((s) => s.trim());
  return { cols, rows: lines.slice(1).map((l) => l.split(",").map((s) => s.trim())) };
}
function chartPv(p) {
  const d = csvRows(p.data);
  let vals = [40, 65, 52, 78, 70, 92];
  if (d && d.rows.length) {
    let yi = d.cols.indexOf(String(p.y || "").split(",")[0].trim());
    if (yi < 0) yi = d.cols.findIndex((c, i) => d.rows.every((r) => r[i] !== "" && !isNaN(+r[i])));
    if (yi >= 0) vals = d.rows.slice(0, 14).map((r) => +r[yi]);
  }
  const mx = Math.max(...vals, 1), mn = Math.min(0, ...vals);
  const head = `${p.title ? `<div class="v-label" style="margin-bottom:4px">${tpl(p.title)}</div>` : ""}${isExpr(p.data) ? `<span class="s-fx">ƒ ${esc(p.data.slice(1))}</span>` : ""}`;
  if (p.kind === "pie") return head + `<div class="s-pv-pie"></div>`;
  if (p.kind === "line" || p.kind === "area") {
    const pts = vals.map((v, i) => `${(i / Math.max(1, vals.length - 1)) * 300},${100 - ((v - mn) / (mx - mn || 1)) * 90}`).join(" ");
    return head + `<svg class="s-pv-line" viewBox="0 0 300 104" preserveAspectRatio="none">${p.kind === "area" ? `<polygon points="0,104 ${pts} 300,104" fill="var(--accent-soft)"/>` : ""}<polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="2.5" vector-effect="non-scaling-stroke"/></svg>`;
  }
  return head + `<div class="s-pv-chart">${vals.map((v) => `<i style="height:${Math.max(4, ((v - mn) / (mx - mn || 1)) * 100)}%"></i>`).join("")}</div>`;
}
function tablePv(p) {
  const d = csvRows(p.data);
  if (!d) return `<span class="s-fx">ƒ ${esc(String(p.data || "").slice(1)) || "no data"}</span>
    <table class="s-pv-table"><tr><th>column</th><th>column</th><th>column</th></tr>${"<tr><td>…</td><td>…</td><td>…</td></tr>".repeat(3)}</table>`;
  return `<table class="s-pv-table"><tr>${d.cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>${d.rows.slice(0, 5).map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</table>
    ${d.rows.length > 5 ? `<div class="v-help">+ ${d.rows.length - 5} more rows</div>` : ""}`;
}
const ICON = { info: "ℹ", success: "✓", warning: "!", error: "✕" };

function preview(n) {
  const p = n.props || {}, t = n.type;
  switch (t) {
    case "title": return `<div class="v-title"><h1>${tpl(p.text)}</h1>${p.subtitle ? `<p>${tpl(p.subtitle)}</p>` : ""}</div>`;
    case "header": return `<h2 class="v-h">${tpl(p.text)}</h2>`;
    case "subheader": return `<h3 class="v-h">${tpl(p.text)}</h3>`;
    case "text": return `<p class="v-text${p.muted ? " muted" : ""}">${tpl(p.text)}</p>`;
    case "markdown": return `<div class="v-md">${mdLite(p.text)}</div>`;
    case "caption": return `<p class="v-text muted small">${tpl(p.text)}</p>`;
    case "badge": return `<span class="v-badge ${esc(p.kind)}">${tpl(p.text)}</span>`;
    case "link": return `<a class="v-link">${tpl(p.text)} ↗</a>`;
    case "code": return `<div class="v-code"><div class="v-code-bar"><span>${esc(p.lang)}</span></div><pre><code>${esc(p.code)}</code></pre></div>`;
    case "image": return /^(https?:|data:|\/)/.test(p.src || "") ? `<figure class="v-img"><img src="${esc(p.src)}" alt="" style="${p.width ? `max-width:${+p.width}px` : ""}">${p.caption ? `<figcaption>${tpl(p.caption)}</figcaption>` : ""}</figure>`
      : `<div class="v-alert info"><span class="v-alert-ic">🖼</span><div class="v-alert-b">${tpl(p.src) || "Image — set a URL"}</div></div>`;
    case "divider": return `<hr class="v-hr">`;
    case "space": return `<div style="height:${+p.height || 24}px;border-radius:6px;background:repeating-linear-gradient(45deg,transparent 0 6px,var(--accent-soft) 6px 8px)"></div>`;
    case "alert": return `<div class="v-alert ${esc(p.kind)}"><span class="v-alert-ic">${ICON[p.kind] || "•"}</span><div class="v-alert-b">${p.title ? `<strong>${tpl(p.title)}</strong>` : ""}<div class="v-md">${mdLite(p.text)}</div></div></div>`;
    case "metric": {
      const d = String(p.delta ?? ""), up = !d.trim().startsWith("-"), good = up !== !!p.inverse;
      return `<div class="v-metric"><div class="v-metric-l">${tpl(p.label)}</div><div class="v-metric-v">${tpl(String(p.value ?? "")) || "—"}</div>${d ? `<div class="v-delta ${good ? "up" : "down"}">${up ? "▲" : "▼"} ${tpl(d.replace(/^[+-]/, ""))}</div>` : ""}</div>`;
    }
    case "progress": { const v = isExpr(String(p.value)) ? 60 : Math.max(0, Math.min(100, +p.value || 0));
      return `<div class="v-progress"><div class="v-progress-l"><span>${tpl(p.label)}</span><span>${isExpr(String(p.value)) ? tpl(String(p.value)) : v + "%"}</span></div><div class="v-bar"><div class="v-bar-fill" style="width:${v}%"></div></div></div>`; }
    case "input": return field(n, p.label, `<input class="v-in" placeholder="${esc(p.placeholder)}" value="${esc(p.value)}" type="${p.itype === "password" ? "password" : "text"}" tabindex="-1">`, p.help);
    case "textarea": return field(n, p.label, `<textarea class="v-in" rows="${Math.min(+p.rows || 4, 8)}" placeholder="${esc(p.placeholder)}" tabindex="-1">${esc(p.value)}</textarea>`, p.help);
    case "number": return field(n, p.label, `<input class="v-in" value="${esc(p.value)}" tabindex="-1">`, p.help);
    case "slider": { const mn = +p.min || 0, mx = +p.max || 100, v = isNaN(+p.value) ? mn : +p.value, pct = mx > mn ? ((v - mn) / (mx - mn)) * 100 : 0;
      return `<div class="v-field"><div class="v-label-row"><span class="v-label">${tpl(p.label)} <span class="s-var">${esc(p.name)}</span></span><span class="v-slider-v">${esc(v)}${esc(p.suffix || "")}</span></div>
        <input type="range" class="v-range" min="${mn}" max="${mx}" value="${v}" style="--pct:${pct}%" tabindex="-1"></div>`; }
    case "select": { const o = isExpr(p.options) ? [p.options] : asList(p.options);
      return field(n, p.label, `<div class="v-select"><select class="v-in" tabindex="-1"><option>${esc((p.value && o.includes(p.value)) ? p.value : (o[0] || "—"))}</option></select></div>`, p.help); }
    case "radio": { const o = isExpr(p.options) ? ["ƒ options"] : asList(p.options), sel = Math.max(0, o.indexOf(p.value));
      return field(n, p.label, `<div class="v-seg">${o.map((x, i) => `<button class="v-seg-b${i === sel ? " on" : ""}" tabindex="-1">${esc(x)}</button>`).join("")}</div>`); }
    case "multiselect": { const o = isExpr(p.options) ? ["ƒ options"] : asList(p.options), on = new Set(asList(p.value));
      return field(n, p.label, `<div class="v-chips">${o.map((x) => `<button class="v-chip${on.has(x) ? " on" : ""}" tabindex="-1">${esc(x)}</button>`).join("")}</div>`); }
    case "checkbox": case "toggle": return `<label class="${t === "toggle" ? "v-toggle" : "v-check"}"><input type="checkbox" ${p.value ? "checked" : ""} tabindex="-1"><span class="${t === "toggle" ? "v-switch" : "v-box"}"></span><span>${tpl(p.label)}</span> <span class="s-var">${esc(p.name)}</span></label>`;
    case "date": return field(n, p.label, `<input class="v-in" type="date" tabindex="-1">`);
    case "color": return field(n, p.label, `<input class="v-in" type="color" value="${esc(p.value || "#6366f1")}" tabindex="-1">`);
    case "upload": return field(n, "", `<div class="v-drop"><div class="v-drop-ic">⇪</div><div class="v-drop-t">${tpl(p.label)}</div><div class="v-drop-s">Drag & drop or click to browse${p.accept ? " · " + esc(p.accept) : ""}</div></div>`);
    case "button": return `<button class="v-btn ${esc(p.kind || "primary")}${p.full ? " full" : ""}" tabindex="-1">${p.icon ? `<span class="v-btn-ic">${esc(p.icon)}</span>` : ""}${tpl(p.label)}</button>`;
    case "download": return `<a class="v-btn secondary"><span class="v-btn-ic">⬇</span>${tpl(p.label)}</a>`;
    case "table": return tablePv(p);
    case "chart": return chartPv(p);
    case "chat": return `<div class="v-stack" style="gap:8px">${p.greeting ? `<div class="v-chat assistant"><div class="v-avatar">✨</div><div class="v-bubble v-md">${mdLite(p.greeting)}</div></div>` : ""}
      <div class="v-chat user"><div class="v-avatar">🧑</div><div class="v-bubble">Hello!</div></div>
      <div class="v-chat assistant"><div class="v-avatar">✨</div><div class="v-bubble v-md">${p.hook ? `<span class="s-fx">🐍 ${esc(p.hook)}(ctx, message)</span>` : mdLite(p.reply)}</div></div>
      <div class="v-chatin"><input class="v-in" placeholder="${esc(p.placeholder)}" tabindex="-1"><button class="v-btn primary" tabindex="-1">↑</button></div></div>`;
    case "columns": { const w = widths(p.widths);
      return `<div class="s-cols" style="grid-template-columns:${w.map((x) => `minmax(0,${x}fr)`).join(" ")}">${(n.slots || []).map((s, i) => zone(s, `${n.id}:${i}`)).join("")}</div>`; }
    case "card": return `<section class="v-card">${p.title || p.subtitle ? `<div class="v-card-h">${p.title ? `<h3>${tpl(p.title)}</h3>` : ""}${p.subtitle ? `<p>${tpl(p.subtitle)}</p>` : ""}</div>` : ""}${zone(n.slots[0], `${n.id}:0`)}</section>`;
    case "row": return `<div class="s-cont"><div class="s-cont-h">⋯ Row</div>${zone(n.slots[0], `${n.id}:0`, true)}</div>`;
    case "container": return `<div class="s-cont"><div class="s-cont-h">◫ Group${n.show_if ? ` · shown if <span class="s-fx">${esc(n.show_if)}</span>` : ""}</div>${zone(n.slots[0], `${n.id}:0`)}</div>`;
    case "expander": return `<div class="v-exp" style="padding:0"><div style="display:flex;justify-content:space-between;padding:12px 16px;font-weight:600"><span>${tpl(p.label)}</span><span>⌄</span></div><div style="padding:0 16px 14px">${zone(n.slots[0], `${n.id}:0`)}</div></div>`;
    case "tabs": { const labels = asList(p.labels), a = Math.min(activeTab.get(n.id) || 0, (n.slots || []).length - 1);
      return `<div class="s-tabs-pv"><div class="s-tabbar">${labels.map((l, i) => `<span class="${i === a ? "on" : ""}" data-tabpick="${n.id}" data-i="${i}">${tpl(l)}</span>`).join("")}</div>
        ${(n.slots || []).map((s, i) => `<div class="s-tabslot${i === a ? " on" : ""}" style="flex-direction:column">${zone(s, `${n.id}:${i}`)}</div>`).join("")}</div>`; }
  }
  return `<div class="v-text muted">Unknown component: ${esc(t)}</div>`;
}
function zone(nodes, zid, row = false) {
  const empty = !nodes || !nodes.length;
  const msg = zid === "body" ? `<div class="s-empty-ic">⤵</div><b>Drag components here</b><span>or click one on the left · or start from a ✨ template</span>`
    : zid === "side" ? "Drop for sidebar" : "Drop here";
  return `<div class="s-zone${empty ? " empty" : ""}${row ? " row" : ""}" data-zone="${zid}">${empty ? msg : nodes.map(nodeHtml).join("")}</div>`;
}
function nodeHtml(n) {
  const m = meta(n.type), acts = n.type === "button" ? (n.props.actions || []).length : 0;
  const pr = problems.filter((x) => x.id === n.id);
  const lvl = pr.some((x) => x.level === "error") ? "" : " warn";
  return `<div class="s-node${n.id === selId ? " sel" : ""}${n.show_if ? " hidden-if" : ""}" data-id="${n.id}" draggable="true">
    <div class="s-chip">${esc(m.label)}${acts ? ` · ⚡${acts}` : ""}<button data-act="up" title="Move up (Alt+↑)">↑</button><button data-act="down" title="Move down (Alt+↓)">↓</button><button data-act="dup" title="Duplicate (Ctrl+D)">⧉</button><button data-act="del" title="Delete (Del)">✕</button></div>
    ${pr.length ? `<span class="s-prob${lvl}" title="${esc(pr.map((x) => x.msg).join("\n"))}">!</span>` : ""}${preview(n)}</div>`;
}
function renderCanvas() {
  const c = $("#s-canvas"), pg = page();
  c.style.setProperty("--accent", spec.app.accent || "#6366f1");
  c.className = "s-canvas" + (device === "mobile" ? " mobile" : "") + (pg.sidebar.length ? "" : " no-side");
  const wrapScroll = $("#s-canvas-wrap").scrollTop;
  c.innerHTML = `<div class="s-side"><div class="s-side-h">☰ <span>Sidebar</span></div>${zone(pg.sidebar, "side")}</div><div class="s-body-area">${zone(pg.body, "body")}</div>`;
  $("#s-canvas-wrap").scrollTop = wrapScroll;
}
function markProblems() { renderCanvas(); }

/* =================================================================== inspector */
const fieldVal = (v) => v == null ? "" : String(v);
function propField(n, d) {
  const v = n.props[d.name], id = `f-${d.name}`;
  const lab = `<label for="${id}">${esc(d.label)}</label>`;
  const help = d.help ? `<span class="s-help">${esc(d.help)}</span>` : "";
  const common = `id="${id}" data-prop="${d.name}" data-kind="${d.kind}"`;
  switch (d.kind) {
    case "bool": return `<label class="s-sw"><input type="checkbox" ${common} ${v ? "checked" : ""}> ${esc(d.label)}</label>`;
    case "longtext": case "code": case "data":
      return `<div class="s-f">${lab}<textarea ${common} rows="${d.kind === "data" ? 6 : 3}" class="${d.kind !== "longtext" ? "mono" : ""}${isExpr(v) ? " fx" : ""}" spellcheck="false">${esc(fieldVal(v))}</textarea>${help}${d.kind === "data" ? dataHelp() : ""}</div>`;
    case "list": return `<div class="s-f">${lab}<textarea ${common} rows="3" class="${isExpr(v) ? "fx" : ""}" spellcheck="false">${esc(Array.isArray(v) ? v.join("\n") : fieldVal(v))}</textarea>${help}</div>`;
    case "choice": {
      if (isExpr(v)) return `<div class="s-f">${lab}<input type="text" ${common} class="fx" value="${esc(v)}" placeholder="=expression"></div>`;
      return `<div class="s-f">${lab}<select ${common}>${d.options.map((o) => `<option ${o === v ? "selected" : ""}>${esc(o)}</option>`).join("")}<option value="__fx">ƒ formula…</option></select></div>`;
    }
    case "color": return `<div class="s-f">${lab}<div class="s-color"><input type="color" data-prop="${d.name}" data-kind="color" value="${esc(v || "#6366f1")}"><input type="text" ${common} value="${esc(v)}"></div></div>`;
    case "var": return `<div class="s-f">${lab}<input type="text" ${common} class="mono" value="${esc(v)}" autocomplete="off" spellcheck="false"><span class="s-help">Use it as <code>{${esc(v)}}</code> in text or <code>=${esc(v)}</code> in formulas.</span></div>`;
    case "actions": return "";
    default: return `<div class="s-f">${lab}<input type="text" ${common} class="${isExpr(v) ? "fx" : ""}" value="${esc(fieldVal(v))}" spellcheck="false">${help}</div>`;
  }
}
function dataHelp() {
  const lists = vars().filter((v) => v.type === "list" || v.type === "upload");
  if (!lists.length) return `<span class="s-help">Paste CSV, or write <code>=my_list</code> / <code>=csv(file)</code>.</span>`;
  return `<span class="s-help">Paste CSV, or use: ${lists.map((v) => `<a href="#" data-setdata="${v.type === "upload" ? `=csv(${v.name})` : "=" + v.name}"><code>${v.type === "upload" ? `=csv(${esc(v.name)})` : "=" + esc(v.name)}</code></a>`).join(" ")}</span>`;
}
function varChips() {
  const vs = vars();
  if (!vs.length) return "";
  return `<div class="s-f-l" style="margin-bottom:6px">Insert a variable into the last field</div><div class="s-vars">${vs.map((v) =>
    `<button data-ins="${esc(v.name)}" title="${v.kind === "state" ? "state variable" : v.type + " on " + v.page}">${esc(v.name)}</button>`).join("")}</div>`;
}
function actionEditor(n) {
  const acts = n.props.actions || [], pages = spec.pages.map((p) => p.path), vs = vars();
  const varList = `<datalist id="s-varlist">${vs.map((v) => `<option value="${esc(v.name)}">`).join("")}</datalist>`;
  const f = (i, a, k) => {
    const val = a[k] ?? "";
    if (k === "var") return `<div class="s-f"><label>Variable</label><input type="text" list="s-varlist" data-ai="${i}" data-af="var" class="mono" value="${esc(val)}" placeholder="e.g. count (new names are created)"></div>`;
    if (k === "value") return `<div class="s-f"><label>Value</label><input type="text" data-ai="${i}" data-af="value" class="${isExpr(val) ? "fx" : ""}" value="${esc(val)}" placeholder="=count + 1   or   Hello {name}"></div>`;
    if (k === "text") return `<div class="s-f"><label>Message</label><input type="text" data-ai="${i}" data-af="text" value="${esc(val)}" placeholder="Saved, {name}!"></div>`;
    if (k === "kind") return `<div class="s-f"><label>Style</label><select data-ai="${i}" data-af="kind">${["info", "success", "warning", "error"].map((o) => `<option ${o === (val || "info") ? "selected" : ""}>${o}</option>`).join("")}</select></div>`;
    if (k === "to") return `<div class="s-f"><label>Page</label><select data-ai="${i}" data-af="to">${pages.map((o) => `<option ${o === val ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></div>`;
    if (k === "fn") return `<div class="s-f"><label>Function in ${esc(spec.hooks || "hooks.py")}</label><input type="text" data-ai="${i}" data-af="fn" class="mono" value="${esc(val)}" placeholder="send_email"><span class="s-help">def ${esc(val || "send_email")}(ctx): ...  — set the hooks file in App &amp; Data</span></div>`;
    if (k === "vars") return `<div class="s-f"><label>Inputs to reset</label><input type="text" data-ai="${i}" data-af="vars" class="mono" value="${esc(val)}" placeholder="blank = all inputs   or: name email"></div>`;
    return "";
  };
  return `<div class="s-sec"><div class="s-sec-h">⚡ When clicked <button class="s-btn sm" data-addact>+ Add action</button></div>${varList}
    ${acts.length ? "" : `<p class="s-help" style="margin:0 0 10px;font-size:12.5px;color:var(--muted)">No actions yet. Actions run top to bottom.</p>`}
    ${acts.map((a, i) => `<div class="s-act"><div class="s-act-h"><b style="font-size:12px;color:var(--muted)">${i + 1}</b>
      <select class="s-in" data-ai="${i}" data-af="do">${Object.entries(CAT.actions).map(([k, m]) => `<option value="${k}" ${k === a.do ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select>
      <button class="s-ib" data-actmv="${i}" data-d="-1" title="Up">↑</button><button class="s-ib" data-actmv="${i}" data-d="1" title="Down">↓</button><button class="s-ib" data-actdel="${i}" title="Remove">✕</button></div>
      ${(CAT.actions[a.do] || { fields: [] }).fields.map((k) => f(i, a, k)).join("")}
      <div class="s-f" style="margin:0"><label>Only if (optional)</label><input type="text" data-ai="${i}" data-af="if" class="mono" value="${esc(a.if || "")}" placeholder="e.g. agree and '@' in email"></div></div>`).join("")}</div>`;
}
function renderNodeProblems() {
  const box = $("#s-node-probs"); if (!box) return;
  const pr = problems.filter((x) => x.id === selId);
  box.innerHTML = pr.map((x) => `<li class="${x.level}">${x.level === "error" ? "⛔" : "⚠️"} ${esc(x.msg)}</li>`).join("");
}
function renderInspector() {
  const box = $("#s-inspector"), f = selId && find(selId);
  if (!f) { box.innerHTML = emptyInspector(); return; }
  if (f.page !== pageIdx) { pageIdx = f.page; renderPages(); }
  const n = f.node, m = meta(n.type);
  box.innerHTML = `<div class="s-insp">
    <div class="s-insp-h"><span class="s-tile-ic">${esc(m.icon)}</span><div><b>${esc(m.label)}</b><small>${esc(m.desc || "")}</small></div></div>
    <div class="s-insp-acts"><button class="s-btn sm" data-iact="dup">⧉ Duplicate</button><button class="s-btn sm" data-iact="up">↑</button><button class="s-btn sm" data-iact="down">↓</button>
      ${f.parent ? `<button class="s-btn sm" data-iact="parent">⤴ Parent</button>` : ""}<button class="s-btn sm danger" data-iact="del">🗑 Delete</button></div>
    <ul class="s-probs" id="s-node-probs"></ul>
    ${m.props.map((d) => propField(n, d)).join("")}
    ${m.props.some((d) => ["text", "longtext"].includes(d.kind)) ? varChips() : ""}
    ${n.type === "button" ? actionEditor(n) : ""}
    <div class="s-sec"><div class="s-sec-h">👁 Visibility</div>
      <div class="s-f"><label>Show only if</label><input type="text" data-showif class="mono${n.show_if ? " fx" : ""}" value="${esc(n.show_if || "")}" placeholder="e.g. agree   ·   len(entries) > 0   ·   plan == 'Pro'">
      <span class="s-help">Leave empty to always show. Any formula that is true/false.</span></div></div>
    <div class="s-help" style="margin-top:14px;font:11px var(--mono);color:var(--muted)">id: ${esc(n.id)}</div></div>`;
  renderNodeProblems();
}
function emptyInspector() {
  const vs = vars();
  return `<div class="s-empty-insp"><h3>Build visually ✨</h3>
    <ul><li><b>Drag</b> a component onto the canvas (or click it).</li><li><b>Click</b> anything to edit it here.</li>
    <li>Every input is a <b>variable</b>. Show it in text with <span class="s-var">{name}</span>.</li>
    <li>Start a value with <span class="s-fx">=</span> to compute it, like Excel: <span class="s-fx">=price * qty</span></li>
    <li><b>Buttons</b> run actions: set variables, add to lists, show messages, change pages.</li></ul>
    <p><span class="s-kbd">Del</span> delete · <span class="s-kbd">Ctrl D</span> duplicate · <span class="s-kbd">Ctrl Z</span> undo · <span class="s-kbd">Alt ↑↓</span> move · <span class="s-kbd">/</span> search</p>
    ${vs.length ? `<h3 style="margin-top:18px">Variables</h3><div class="s-vars">${vs.map((v) => `<button data-goto="${esc(v.id || "")}" title="${esc(v.kind)}">${esc(v.name)}</button>`).join("")}</div>` : ""}</div>`;
}
function readField(t) {
  const k = t.dataset.kind, v = t.value;
  if (k === "bool") return t.checked;
  if (k === "number") { const s = v.trim(); if (s === "") return null; return !isNaN(+s) ? +s : s; }
  if (k === "list") { const s = v.trim(); return s.startsWith("=") ? s : v.split("\n").map((x) => x.trim()).filter(Boolean); }
  if (k === "var") { let s = v.replace(/[^A-Za-z0-9_]/g, "_"); if (/^[^A-Za-z]/.test(s)) s = "v" + s; if (s !== v) t.value = s; return s; }
  return v;
}

/* ---- rename refactor: update {old} / =old references everywhere */
function renameRefs(oldN, newN) {
  if (!oldN || !newN || oldN === newN || !IDENT.test(newN)) return 0;
  const re = new RegExp(`(^|[^\\w.'"])${oldN}(?![\\w'"])`, "g");
  const inExpr = (s) => s.replace(re, `$1${newN}`);
  const fix = (s) => {
    if (typeof s !== "string") return s;
    if (isExpr(s)) return "=" + inExpr(s.slice(1));
    return s.replace(/\{([^{}]+)\}/g, (m, e) => "{" + inExpr(e) + "}");
  };
  let count = 0;
  for (const n of allNodes()) {
    for (const [k, v] of Object.entries(n.props || {})) {
      if (k === "name" || k === "code") continue;
      if (k === "actions") { for (const a of v || []) { for (const f of ["value", "text", "if", "to"]) { if (typeof a[f] !== "string") continue; const x = f === "if" && !a[f].startsWith("=") ? inExpr(a[f]) : fix(a[f]); if (x !== a[f]) { a[f] = x; count++; } }
        if (a.var === oldN) { a.var = newN; count++; } if (typeof a.vars === "string") a.vars = a.vars.split(/[\s,]+/).map((x) => x === oldN ? newN : x).join(" ").trim(); } continue; }
      const x = fix(v); if (x !== v) { n.props[k] = x; count++; }
    }
    if (n.show_if) { const x = n.show_if.startsWith("=") ? fix(n.show_if) : inExpr(n.show_if); if (x !== n.show_if) { n.show_if = x; count++; } }
  }
  return count;
}

/* =================================================================== pages + app panes */
function renderPages() {
  const pg = page();
  $("#s-pages").innerHTML = `${spec.pages.map((p, i) => `<div class="s-page${i === pageIdx ? " on" : ""}" data-page="${i}"><span>${esc(p.icon || "•")}</span><b>${esc(p.title)}</b><small>${esc(p.path)}</small></div>`).join("")}
    <button class="s-btn" data-addpage style="width:100%;justify-content:center;margin:4px 0 16px">+ Add page</button>
    <div class="s-sec-h">This page</div>
    <div class="s-f"><label>Title</label><input type="text" data-pg="title" value="${esc(pg.title)}"></div>
    <div class="s-f"><label>Path (URL)</label><input type="text" data-pg="path" class="mono" value="${esc(pg.path)}"></div>
    <div class="s-f"><label>Icon (emoji)</label><input type="text" data-pg="icon" value="${esc(pg.icon || "")}"></div>
    <div style="display:flex;gap:6px"><button class="s-btn sm" data-pgmv="-1">↑ Move up</button><button class="s-btn sm" data-pgmv="1">↓ Move down</button>
    <button class="s-btn sm" data-pgdup>⧉ Duplicate</button>${spec.pages.length > 1 ? `<button class="s-btn sm danger" data-pgdel>🗑 Delete</button>` : ""}</div>
    <p class="s-tip">Two or more pages get an automatic navigation menu. Buttons can jump between pages with “Go to page”.</p>`;
}
function renderAppPane() {
  const a = spec.app, st = spec.state || {};
  $("#s-appset").innerHTML = `<div class="s-sec-h">App</div>
    <div class="s-f"><label>Title</label><input type="text" data-app="title" value="${esc(a.title)}"></div>
    <div class="s-f"><label>Icon (emoji)</label><input type="text" data-app="icon" value="${esc(a.icon)}"></div>
    <div class="s-f"><label>Accent colour</label><div class="s-color"><input type="color" data-app="accent" value="${esc(a.accent)}"><input type="text" data-app="accent" class="mono" value="${esc(a.accent)}"></div></div>
    <div class="s-f"><label>Theme</label><select data-app="theme">${["auto", "light", "dark"].map((o) => `<option ${o === a.theme ? "selected" : ""}>${o}</option>`).join("")}</select></div>
    <label class="s-sw"><input type="checkbox" data-app="wide" ${a.wide ? "checked" : ""}> Wide layout</label>
    <div class="s-sec" style="margin-top:6px"><div class="s-sec-h">State variables <button class="s-btn sm" data-addstate>+ Add</button></div>
      <p class="s-tip" style="margin:-4px 0 10px">Values your app remembers per visitor: counters, lists of entries… Use <code>[]</code> for a list, <code>0</code> for a number.</p>
      ${Object.entries(st).map(([k, v]) => `<div class="s-statev"><input class="s-in mono" data-statek="${esc(k)}" value="${esc(k)}"><input class="s-in mono" data-statev="${esc(k)}" value="${esc(typeof v === "string" && v.length > 200 ? JSON.stringify(v.slice(0, 200) + "…") : JSON.stringify(v))}" ${typeof v === "string" && v.length > 200 ? "readonly title='long text — edit in the JSON file'" : ""}><button class="s-ib" data-statedel="${esc(k)}" title="Remove">✕</button></div>`).join("") || `<p class="s-tip" style="margin:0">None yet.</p>`}</div>
    <div class="s-sec"><div class="s-sec-h">Python hooks (optional)</div>
      <div class="s-f"><label>Hooks file</label><input type="text" data-app-hooks class="mono" value="${esc(spec.hooks || "")}" placeholder="hooks.py"><span class="s-help">Plain Python functions your buttons & chat can call: <code>def send_email(ctx): ...</code> Saved next to ${esc(file.split(/[\\/]/).pop())}.</span></div></div>
    <div class="s-sec"><div class="s-sec-h">Formula cheat sheet</div><dl class="s-cheat">
      <dt><code>Hello {name}</code></dt><dd>Show a variable inside text</dd>
      <dt><code>{price * qty:,.2f}</code></dt><dd>Compute + format (1,234.50)</dd>
      <dt><code>=count + 1</code></dt><dd>A whole value computed (starts with =)</dd>
      <dt><code>=csv(file)</code></dt><dd>Rows from an uploaded CSV</dd>
      <dt><code>=where(rows, 'city', city)</code></dt><dd>Filter rows by a column</dd>
      <dt><code>=group(rows, 'month', 'sales')</code></dt><dd>Group &amp; sum (agg='mean'|'count'…)</dd>
      <dt><code>=sum(col(rows, 'sales'))</code></dt><dd>Total of a column · also mean(), min(), max(), len()</dd>
      <dt><code>=columns(rows)</code></dt><dd>Column names (great for dropdown options)</dd>
      <dt><code>='Yes' if agree else 'No'</code></dt><dd>Conditions</dd>
      <dt><code>=[r for r in rows if r['score'] > 90]</code></dt><dd>Python list comprehensions work too</dd></dl></div>`;
}

/* =================================================================== mutations */
function insertNode(n, zid, index) {
  const arr = zoneArr(zid); if (!arr) return;
  commit();
  arr.splice(index == null ? arr.length : index, 0, n);
  selId = n.id; changed();
}
function addFromPalette(type) {
  const n = makeNode(type);
  const f = selId && find(selId);
  if (f && meta(f.node.type).slots) { const i = f.node.type === "tabs" ? Math.min(activeTab.get(f.node.id) || 0, f.node.slots.length - 1) : 0; return insertNode(n, `${f.node.id}:${i}`); }
  if (f && f.page === pageIdx) { commit(); f.arr.splice(f.index + 1, 0, n); selId = n.id; changed(); }
  else insertNode(n, "body");
  requestAnimationFrame(() => { const el = $(`.s-node[data-id="${n.id}"]`); el && el.scrollIntoView({ block: "nearest", behavior: "smooth" }); });
}
function nodeAct(act, id = selId) {
  const f = id && find(id); if (!f) return;
  if (act === "del") { commit(); f.arr.splice(f.index, 1); selId = f.arr[f.index] ? f.arr[f.index].id : f.arr[f.index - 1] ? f.arr[f.index - 1].id : f.parent ? f.parent.id : null; changed(); }
  else if (act === "dup") { commit(); const c = cloneNode(f.node); f.arr.splice(f.index + 1, 0, c); selId = c.id; changed(); }
  else if (act === "up" || act === "down") {
    const j = f.index + (act === "up" ? -1 : 1); if (j < 0 || j >= f.arr.length) return;
    commit(); [f.arr[f.index], f.arr[j]] = [f.arr[j], f.arr[f.index]]; selId = f.node.id; changed();
  } else if (act === "parent" && f.parent) { selId = f.parent.id; renderCanvas(); renderInspector(); }
}
function select(id, focus = false) {
  selId = id; $$(".s-node.sel").forEach((e) => e.classList.remove("sel"));
  if (id) { const el = $(`.s-node[data-id="${id}"]`); el && el.classList.add("sel"); }
  renderInspector();
  if (focus) { const i = $("#s-inspector [data-prop]"); i && i.focus(); }
}

/* =================================================================== drag & drop */
const line = document.createElement("div"); line.className = "s-drop-line"; line.hidden = true; document.body.append(line);
function dropTarget(e) {
  const z = e.target.closest && e.target.closest(".s-zone"); if (!z) return null;
  if (drag && drag.kind === "move") { const self = $(`.s-node[data-id="${drag.id}"]`); if (self && self.contains(z)) return null; }
  const row = z.classList.contains("row"), kids = [...z.children].filter((c) => c.classList.contains("s-node"));
  let index = kids.length;
  for (let i = 0; i < kids.length; i++) { const r = kids[i].getBoundingClientRect(); if (row ? e.clientX < r.left + r.width / 2 : e.clientY < r.top + r.height / 2) { index = i; break; } }
  return { z, zid: z.dataset.zone, index, kids, row };
}
function showLine(t) {
  $$(".s-zone.over").forEach((x) => x !== t.z && x.classList.remove("over")); t.z.classList.add("over");
  const zr = t.z.getBoundingClientRect(); line.hidden = false;
  if (!t.kids.length) { Object.assign(line.style, { left: zr.left + 8 + "px", top: zr.top + zr.height / 2 + "px", width: zr.width - 16 + "px", height: "3px" }); line.classList.remove("v"); return; }
  if (t.row) {
    const r = t.kids[Math.min(t.index, t.kids.length - 1)].getBoundingClientRect(), x = t.index >= t.kids.length ? r.right + 5 : r.left - 6;
    line.classList.add("v"); Object.assign(line.style, { left: x + "px", top: r.top + "px", height: r.height + "px", width: "3px" }); return;
  }
  line.classList.remove("v");
  const r = t.index >= t.kids.length ? t.kids[t.kids.length - 1].getBoundingClientRect() : t.kids[t.index].getBoundingClientRect();
  const y = t.index >= t.kids.length ? r.bottom + 5 : r.top - 6;
  Object.assign(line.style, { left: zr.left + "px", top: y + "px", width: zr.width + "px", height: "3px" });
}
function endDrag() { drag = null; line.hidden = true; document.body.classList.remove("s-dragging"); $$(".s-zone.over").forEach((x) => x.classList.remove("over")); $$(".s-node.dragging").forEach((x) => x.classList.remove("dragging")); }
document.addEventListener("dragstart", (e) => {
  const tile = e.target.closest && e.target.closest("[data-new]");
  const node = e.target.closest && e.target.closest(".s-node");
  if (tile) { drag = { kind: "new", type: tile.dataset.new }; e.dataTransfer.effectAllowed = "copy"; }
  else if (node) { drag = { kind: "move", id: node.dataset.id }; e.dataTransfer.effectAllowed = "move"; setTimeout(() => node.classList.add("dragging"), 0); }
  else return;
  e.dataTransfer.setData("text/plain", drag.type || drag.id);
  document.body.classList.add("s-dragging");
});
document.addEventListener("dragover", (e) => {
  if (!drag) return;
  const t = dropTarget(e);
  if (!t) { line.hidden = true; return; }
  e.preventDefault(); e.dataTransfer.dropEffect = drag.kind === "new" ? "copy" : "move"; showLine(t);
});
document.addEventListener("drop", (e) => {
  if (!drag) return;
  const t = dropTarget(e); const d = drag; endDrag();
  if (!t) return;
  e.preventDefault();
  if (d.kind === "new") return insertNode(makeNode(d.type), t.zid, t.index);
  const f = find(d.id), arr = zoneArr(t.zid); if (!f || !arr) return;
  let idx = t.index;
  if (f.arr === arr && f.index < idx) idx--;
  if (f.arr === arr && f.index === idx) return;
  commit(); f.arr.splice(f.index, 1); arr.splice(idx, 0, f.node); selId = f.node.id; changed();
});
document.addEventListener("dragend", endDrag);

/* =================================================================== views: preview + code */
function previewUrl() { return `${location.protocol}//${location.hostname}:${CFG.previewPort}${page().path}`; }
function syncPreview(force) {
  const fr = $("#s-preview"), url = previewUrl();
  $("#s-preview-url").textContent = url;
  $("#s-preview-wrap").classList.toggle("mobile", device === "mobile");
  if (view !== "preview" && view !== "split") return;
  if (force || fr.dataset.src !== url) { fr.dataset.src = url; fr.src = url; }
}
function setView(v) {
  view = v; $("#s-main").dataset.view = v;
  $$("#s-view button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  try { localStorage.setItem("velo-studio:view", v); } catch (e) {}
  if (v === "code") loadCode();
  syncPreview();
}
async function loadCode() {
  try {
    const r = await fetch("/api/code", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ spec }) });
    const d = await r.json(); $("#s-code").innerHTML = highlight(d.code || d.error || ""); $("#s-code").dataset.raw = d.code || "";
  } catch (e) { $("#s-code").textContent = "Could not generate code: " + e.message; }
}
function highlight(src) {
  const KW = /^(def|return|if|else|elif|for|in|not|and|or|with|import|from|as|True|False|None|lambda|is|pass|class|while|try|except)$/;
  const re = /(#[^\n]*)|("""[\s\S]*?"""|f?"(?:\\.|[^"\\\n])*"|f?'(?:\\.|[^'\\\n])*')|(@[\w.]+)|(\b\d[\d_.]*\b)|([A-Za-z_]\w*)|([\s\S])/g;
  let out = "", m;
  while ((m = re.exec(src))) {
    if (m[1]) out += `<span class="c">${esc(m[1])}</span>`;
    else if (m[2]) out += `<span class="s">${esc(m[2])}</span>`;
    else if (m[3]) out += `<span class="d">${esc(m[3])}</span>`;
    else if (m[4]) out += `<span class="n">${esc(m[4])}</span>`;
    else if (m[5]) out += KW.test(m[5]) ? `<span class="k">${m[5]}</span>` : m[5];
    else out += esc(m[6]);
  }
  return out;
}

/* =================================================================== problems + modal + toast */
function renderProblems() {
  const b = $("#s-problems"), errs = problems.filter((p) => p.level === "error").length, warns = problems.length - errs;
  b.hidden = !problems.length;
  b.className = "s-problems" + (errs ? "" : " warn");
  b.textContent = errs ? `⛔ ${errs} problem${errs > 1 ? "s" : ""}` : `⚠️ ${warns} warning${warns > 1 ? "s" : ""}`;
}
function modal(html) { $("#s-modal-box").innerHTML = html; $("#s-modal").hidden = false; }
function closeModal() { $("#s-modal").hidden = true; }
function showTemplates(first) {
  modal(`<h2>${first ? "Welcome to Velo Studio 👋" : "Start from a template"}</h2>
    <p>${first ? "Pick a starting point — everything stays editable. You can switch any time." : "This replaces the current app (you can undo)."}</p>
    <div class="s-tpls">${TPLS.map((t) => `<button class="s-tpl" data-tpl="${t.id}"><div>${t.icon}</div><b>${esc(t.title)}</b><small>${esc(t.desc)}</small></button>`).join("")}</div>
    <div class="s-modal-f"><button class="s-btn" data-close>${first ? "Start blank" : "Cancel"}</button></div>`);
}
function showProblems() {
  modal(`<h2>Problems</h2><p>Click one to jump to the component.</p><ul class="s-probs">${problems.map((p) =>
    `<li class="${p.level}" style="cursor:pointer" data-goto="${esc(p.id || "")}">${p.level === "error" ? "⛔" : "⚠️"} ${esc(p.msg)}</li>`).join("")}</ul>
    <div class="s-modal-f"><button class="s-btn" data-close>Close</button></div>`);
}
function toast(text, kind = "info") {
  const el = document.createElement("div"); el.className = "v-toast " + kind;
  el.innerHTML = `<span class="v-toast-ic">${ICON[kind] || "•"}</span><span>${esc(text)}</span>`;
  $("#v-toasts").append(el); requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("in")));
  setTimeout(() => { el.classList.remove("in"); setTimeout(() => el.remove(), 300); }, 3200);
}

/* =================================================================== events */
document.addEventListener("click", async (e) => {
  const t = e.target; let el;
  if ((el = t.closest("[data-close]")) || t.id === "s-modal") { closeModal(); return; }
  if ((el = t.closest("[data-tpl]"))) {
    const r = await fetch("/api/template?name=" + el.dataset.tpl); const d = await r.json();
    commit(); spec = d.spec; pageIdx = 0; selId = null; closeModal(); changed(true, true); syncPreview(true);
    toast("Template loaded — make it yours!", "success"); return;
  }
  if ((el = t.closest("[data-goto]"))) { const id = el.dataset.goto; closeModal(); if (id && find(id)) { selId = id; renderInspector(); renderCanvas(); const n = $(`.s-node[data-id="${id}"]`); n && n.scrollIntoView({ block: "center", behavior: "smooth" }); } return; }
  if ((el = t.closest("[data-new]"))) { addFromPalette(el.dataset.new); return; }
  if ((el = t.closest("[data-tabpick]"))) { activeTab.set(el.dataset.tabpick, +el.dataset.i); renderCanvas(); e.stopPropagation(); return; }
  if ((el = t.closest(".s-chip button"))) { const id = el.closest(".s-node").dataset.id; nodeAct(el.dataset.act, id); return; }
  if ((el = t.closest(".s-node"))) { if (el.dataset.id !== selId) select(el.dataset.id); return; }
  if (t.closest("#s-canvas-wrap")) { if (selId) select(null); return; }
  if ((el = t.closest("[data-iact]"))) { nodeAct(el.dataset.iact); return; }
  if ((el = t.closest("[data-ins]"))) {
    const v = el.dataset.ins, f = lastField && document.body.contains(lastField) ? lastField : $("#s-inspector [data-kind=text], #s-inspector [data-kind=longtext]");
    if (!f) return;
    const ins = f.value.startsWith("=") ? v : `{${v}}`, s = f.selectionStart ?? f.value.length, en = f.selectionEnd ?? s;
    typingSnap = typingSnap || snap(); f.value = f.value.slice(0, s) + ins + f.value.slice(en); f.focus(); f.selectionStart = f.selectionEnd = s + ins.length;
    f.dispatchEvent(new Event("input", { bubbles: true })); return;
  }
  if ((el = t.closest("[data-setdata]"))) { e.preventDefault(); const ta = $("#s-inspector [data-kind=data]"); if (ta) { typingSnap = snap(); ta.value = el.dataset.setdata; ta.dispatchEvent(new Event("input", { bubbles: true })); renderInspector(); } return; }
  // actions editor
  const nf = selId && find(selId);
  if (nf && (el = t.closest("[data-addact]"))) { commit(); (nf.node.props.actions = nf.node.props.actions || []).push({ do: "toast", text: "Done!", kind: "success" }); changed(); return; }
  if (nf && (el = t.closest("[data-actdel]"))) { commit(); nf.node.props.actions.splice(+el.dataset.actdel, 1); changed(); return; }
  if (nf && (el = t.closest("[data-actmv]"))) { const a = nf.node.props.actions, i = +el.dataset.actmv, j = i + +el.dataset.d; if (j < 0 || j >= a.length) return; commit(); [a[i], a[j]] = [a[j], a[i]]; changed(); return; }
  // pages
  if ((el = t.closest("[data-page]"))) { pageIdx = +el.dataset.page; selId = null; renderPages(); renderCanvas(); renderInspector(); syncPreview(); return; }
  if (t.closest("[data-addpage]")) {
    commit(); let i = spec.pages.length + 1; while (spec.pages.some((p) => p.path === "/page" + i)) i++;
    spec.pages.push({ id: "p" + Date.now(), path: "/page" + i, title: "Page " + i, icon: "📄", body: [makeNode("title")], sidebar: [] });
    spec.pages[spec.pages.length - 1].body[0].props.text = "Page " + i; spec.pages[spec.pages.length - 1].body[0].props.subtitle = "";
    pageIdx = spec.pages.length - 1; selId = null; changed(true, true); return;
  }
  if ((el = t.closest("[data-pgmv]"))) { const j = pageIdx + +el.dataset.pgmv; if (j < 0 || j >= spec.pages.length) return; commit(); [spec.pages[pageIdx], spec.pages[j]] = [spec.pages[j], spec.pages[pageIdx]]; pageIdx = j; changed(true, true); return; }
  if (t.closest("[data-pgdup]")) { commit(); const c = clone(page()); c.id = "p" + Date.now(); let i = 2; while (spec.pages.some((p) => p.path === `${page().path === "/" ? "/home" : page().path}-${i}`)) i++; c.path = `${page().path === "/" ? "/home" : page().path}-${i}`; c.title += " copy"; c.body = c.body.map(cloneNode); c.sidebar = c.sidebar.map(cloneNode); spec.pages.splice(pageIdx + 1, 0, c); pageIdx++; changed(true, true); return; }
  if (t.closest("[data-pgdel]")) { if (!confirm(`Delete page “${page().title}”?`)) return; commit(); spec.pages.splice(pageIdx, 1); pageIdx = Math.max(0, pageIdx - 1); selId = null; changed(true, true); return; }
  // state
  if (t.closest("[data-addstate]")) { commit(); let i = 1; while (("var" + i) in spec.state) i++; spec.state["var" + i] = 0; changed(false, true); return; }
  if ((el = t.closest("[data-statedel]"))) { commit(); delete spec.state[el.dataset.statedel]; changed(false, true); return; }
  // tabs, views, menus
  if ((el = t.closest("#s-left-tabs [data-tab]"))) { $$("#s-left-tabs button").forEach((b) => b.classList.toggle("on", b === el)); $$(".s-pane").forEach((p) => p.classList.toggle("on", p.dataset.pane === el.dataset.tab)); return; }
  if ((el = t.closest("#s-view [data-view]"))) { setView(el.dataset.view); return; }
  if ((el = t.closest("#s-device [data-dev]"))) { device = el.dataset.dev; $$("#s-device button").forEach((b) => b.classList.toggle("on", b === el)); renderCanvas(); syncPreview(); return; }
  if (t.closest("#s-undo")) return doUndo();
  if (t.closest("#s-redo")) return doRedo();
  if (t.closest("#s-templates")) return showTemplates(false);
  if (t.closest("#s-problems")) return showProblems();
  if (t.closest("#s-preview-reload")) return syncPreview(true);
  if (t.closest("#s-export")) { $("#s-export-menu").hidden = !$("#s-export-menu").hidden; return; }
  if (!t.closest(".s-menu")) $("#s-export-menu").hidden = true;
  if (t.closest("#s-import")) { $("#s-import-file").click(); return; }
  if (t.closest("#s-open-preview")) { window.open(previewUrl(), "_blank"); return; }
  if (t.closest("#s-code-copy")) { navigator.clipboard && navigator.clipboard.writeText($("#s-code").dataset.raw || "").then(() => toast("Code copied", "success")); return; }
  if (t.closest("#s-theme")) { const nt = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = nt; try { localStorage.setItem("velo-studio:theme", nt); } catch (x) {} }
});
document.addEventListener("dblclick", (e) => { const n = e.target.closest && e.target.closest(".s-node"); if (n) { e.stopPropagation(); select(n.dataset.id, true); } });

const insp = $("#s-inspector");
insp.addEventListener("focusin", (e) => {
  if (e.target.matches("input,textarea,select")) { typingSnap = snap(); if (e.target.dataset.kind === "var") e.target.dataset.old = e.target.value; }
  if (e.target.matches("input[type=text],textarea")) lastField = e.target;
});
document.addEventListener("focusout", () => { typingSnap = null; });
function takeSnap() { if (typingSnap) { undo.push(typingSnap); redo = []; typingSnap = null; updUndo(); } }
insp.addEventListener("input", (e) => {
  const t = e.target, f = selId && find(selId); if (!f) return;
  const n = f.node;
  if (t.dataset.prop) {
    if (t.tagName === "SELECT" && t.value === "__fx") return;
    takeSnap();
    n.props[t.dataset.prop] = readField(t);
    if (t.dataset.kind === "color") { $$(`[data-prop="${t.dataset.prop}"]`, insp).forEach((x) => { if (x !== t) x.value = t.value; }); }
    if (["text", "longtext", "list", "data"].includes(t.dataset.kind) || t.type === "text") t.classList.toggle("fx", isExpr(t.value.trim()));
    if (["widths", "labels"].includes(t.dataset.prop)) syncSlots(n);
  } else if (t.dataset.af) {
    takeSnap();
    const a = n.props.actions[+t.dataset.ai];
    a[t.dataset.af] = t.value;
    if (t.dataset.af === "do") { renderCanvas(); renderInspector(); changed(false); return; }
  } else if ("showif" in t.dataset) { takeSnap(); n.show_if = t.value.trim() || undefined; if (!n.show_if) delete n.show_if; }
  else return;
  changed(false);
});
insp.addEventListener("change", (e) => {
  const t = e.target, f = selId && find(selId); if (!f) return;
  if (t.tagName === "SELECT" && t.value === "__fx") { f.node.props[t.dataset.prop] = "=" + (meta(f.node.type).props.find((d) => d.name === t.dataset.prop) || {}).default; changed(); const x = $(`#s-inspector [data-prop="${t.dataset.prop}"]`); x && x.focus(); return; }
  if (t.dataset.kind === "var") {
    const old = t.dataset.old, nn = t.value;
    if (old && nn && old !== nn) {
      if (!IDENT.test(nn)) { toast("Variable names must start with a letter", "warning"); return; }
      const clash = vars().find((v) => v.name === nn && v.id !== f.node.id);
      if (clash) { toast(`“${nn}” is already used`, "warning"); }
      const c = renameRefs(old, nn); if (c) toast(`Renamed ${old} → ${nn} in ${c} place${c > 1 ? "s" : ""}`, "success");
      t.dataset.old = nn; changed();
    }
  }
  if (t.dataset.af === "var") {
    const v = t.value.trim(), a = f.node.props.actions[+t.dataset.ai];
    if (v && IDENT.test(v) && !vars().some((x) => x.name === v)) {
      spec.state[v] = a.do === "append" ? [] : a.do === "toggle" ? false : (a.do === "set" && !isNaN(+a.value) && String(a.value).trim() !== "") ? 0 : "";
      toast(`Created state variable “${v}”`, "success"); changed(false, true);
    }
  }
});
// pages + app panes
document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.dataset.pg) {
    takeSnap(); const pg = page();
    if (t.dataset.pg === "path") { let v = "/" + t.value.trim().replace(/^\/+/, "").replace(/[^\w\-/]/g, "-"); pg.path = v; }
    else pg[t.dataset.pg] = t.value;
    $$(`.s-page[data-page="${pageIdx}"]`).forEach((el) => { el.querySelector("b").textContent = pg.title; el.querySelector("small").textContent = pg.path; el.querySelector("span").textContent = pg.icon || "•"; });
    changed(false); syncPreview(); return;
  }
  if (t.dataset.app) {
    takeSnap(); const k = t.dataset.app;
    spec.app[k] = t.type === "checkbox" ? t.checked : t.value;
    if (k === "accent") $$(`[data-app="accent"]`).forEach((x) => { if (x !== t && /^#[0-9a-f]{6}$/i.test(t.value)) x.value = t.value; });
    if (k === "title") $("#s-app-title").value = t.value;
    changed(false); return;
  }
  if ("appHooks" in t.dataset) { takeSnap(); spec.hooks = t.value.trim() || undefined; if (!spec.hooks) delete spec.hooks; changed(false); return; }
  if (t.id === "s-app-title") { takeSnap(); spec.app.title = t.value; const x = $('[data-app="title"]'); x && (x.value = t.value); changed(false); return; }
  if (t.id === "s-search") renderPalette(t.value);
});
document.addEventListener("focusin", (e) => { if (e.target.matches("[data-pg],[data-app],[data-app-hooks],#s-app-title,[data-statek],[data-statev]")) typingSnap = snap(); });
document.addEventListener("change", (e) => {
  const t = e.target;
  if (t.dataset.statek !== undefined) {
    const old = t.dataset.statek, nn = t.value.trim();
    if (!IDENT.test(nn)) { toast("Names must start with a letter (letters, digits, _)", "warning"); t.value = old; return; }
    if (nn !== old) { takeSnap(); const entries = Object.entries(spec.state).map(([k, v]) => [k === old ? nn : k, v]); spec.state = Object.fromEntries(entries); renameRefs(old, nn); changed(true, true); }
    return;
  }
  if (t.dataset.statev !== undefined) {
    takeSnap(); let v; try { v = JSON.parse(t.value); } catch (x) { v = t.value; }
    spec.state[t.dataset.statev] = v; changed(false); return;
  }
  if (t.dataset.pg === "path") renderPages();
  if (t.id === "s-import-file" && t.files[0]) {
    const fr = new FileReader();
    fr.onload = () => { try { const d = JSON.parse(fr.result); if (!d.pages) throw new Error("not a Velo app spec"); commit(); spec = d; spec.state = spec.state || {}; pageIdx = 0; selId = null; changed(true, true); toast("Imported " + t.files[0].name, "success"); } catch (x) { toast("Import failed: " + x.message, "error"); } t.value = ""; };
    fr.readAsText(t.files[0]);
  }
});

document.addEventListener("keydown", (e) => {
  const inField = e.target.matches && e.target.matches("input,textarea,select,[contenteditable]");
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); clearTimeout(saveT); save(); return; }
  if (e.key === "Escape") { if (!$("#s-modal").hidden) closeModal(); else if (inField) e.target.blur(); else select(null); return; }
  if (inField) return;
  if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? doRedo() : doUndo(); return; }
  if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); doRedo(); return; }
  if (mod && e.key.toLowerCase() === "d") { e.preventDefault(); nodeAct("dup"); return; }
  if ((e.key === "Delete" || e.key === "Backspace") && selId) { e.preventDefault(); nodeAct("del"); return; }
  if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); nodeAct(e.key === "ArrowUp" ? "up" : "down"); return; }
  if (e.key === "/") { e.preventDefault(); $('[data-tab="components"]').click(); $("#s-search").focus(); return; }
  if (["1", "2", "3", "4"].includes(e.key) && !mod) setView(["design", "split", "preview", "code"][+e.key - 1]);
});

/* =================================================================== boot */
(async function boot() {
  const r = await fetch("/api/state"); const d = await r.json();
  spec = d.spec; CAT = d.catalog; TPLS = d.templates; problems = d.problems || []; file = d.file;
  spec.state = spec.state || {};
  $("#s-app-title").value = spec.app.title;
  $("#s-dl-json").setAttribute("download", file.split(/[\\/]/).pop());
  document.title = `${spec.app.title} · Velo Studio`;
  renderPalette(); renderPages(); renderAppPane(); renderCanvas(); renderInspector(); renderProblems(); updUndo(); setSave("ok");
  let v = "design"; try { v = localStorage.getItem("velo-studio:view") || "design"; } catch (e) {}
  setView(v);
  if (d.fresh) showTemplates(true);
})().catch((e) => { document.body.innerHTML = `<pre style="padding:24px">Velo Studio failed to start: ${esc(e.message)}</pre>`; });
})();
