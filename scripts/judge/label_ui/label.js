// Gold labelling UI. Blind by construction: the label set contains no judge output.
// One work item = one rollout (all attempts). One label record per rollout, autosaved to the
// local server (label_server.py); spans and the B1 verdict are stored per attempt inside it.
"use strict";

const P = new URLSearchParams(location.search);
const SET = P.get("set");
const LABELER = P.get("labeler") || "mark";
const LS = `label2:${SET}:${LABELER}`;
const LAB = {
  eval_awareness: { name: "Eval awareness", short: "EA" },
  grader: { name: "Grader", short: "grader" },
  bad_test: { name: "First bad test", short: "first bad test", first: true },
  cheat_considered: { name: "First cheat considered", short: "first cheat considered", first: true },
};
const FRAMING = ["capability", "safety", "generic"];
const TYPES = ["special_case", "redefine_check", "stateful", "operator_overload", "other"];

let data, recs = {}, cur = 0, view = "label";
let rows = [], pos = {}, rowAtt = [], sel = null, dragging = false, moved = false, focus = [];
let undoStack = [], saveTimer = null, lastActive = Date.now(), toastTimer = null;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const item = () => data.items[cur];
const rec = () => recs[item().rollout];
const attRec = (key) => rec().attempts[key];

function lsGet(k, d) { try { const v = localStorage.getItem(`${LS}:${k}`); return v == null ? d : JSON.parse(v); } catch { return d; } }
function lsSet(k, v) { try { localStorage.setItem(`${LS}:${k}`, JSON.stringify(v)); } catch {} }
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add("hidden"), 1800);
}

function blank(it) {
  const attempts = {};
  it.attempts.forEach((a) => (attempts[a.key] = { spans: [], b1: { attempted: null, type: null, transparent: null }, note: "" }));
  return { rollout: it.rollout, set: SET, labeler: LABELER, status: "not_started", note: "", active_seconds: 0, read_marker: null, attempts };
}

// ---------- persistence ----------
function scheduleSave() { clearTimeout(saveTimer); $("saved").textContent = "saving…"; saveTimer = setTimeout(save, 400); }
async function save() {
  const r = rec();
  r.updated = new Date().toISOString();
  Object.values(r.attempts).forEach((ar) => ar.spans.forEach((s) => (s.ids = rows.slice(pos[s.start], pos[s.end] + 1))));
  lsSet(`backup:${r.rollout}`, r);
  try {
    const res = await fetch(`/api/labels/${SET}/${LABELER}/${cur}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(r) });
    if (!res.ok) throw new Error(res.status);
    $("saved").textContent = "saved"; $("saved").style.color = "";
  } catch {
    $("saved").textContent = "SAVE FAILED (kept in browser)"; $("saved").style.color = "#d33";
  }
}
function touch() { const r = rec(); if (r.status === "not_started") r.status = "in_progress"; }
function pushUndo() {
  undoStack.push({ rollout: rec().rollout, snap: JSON.stringify(rec().attempts) });
  if (undoStack.length > 200) undoStack.shift();
}
function undo() {
  const u = undoStack.pop();
  if (!u) return toast("nothing to undo");
  if (u.rollout !== rec().rollout) { undoStack.push(u); return toast("undo works within the current rollout"); }
  rec().attempts = JSON.parse(u.snap); focus = [];
  paint(); renderB1s(); scheduleSave();
}

// ---------- spans ----------
const range = (s) => [pos[s.start], pos[s.end]];
const selRange = () => (sel ? [Math.min(sel.a, sel.b), Math.max(sel.a, sel.b)] : null);
const hits = (s, a, b) => { const [x, y] = range(s); return x <= b && y >= a; };
const allSpans = () => Object.entries(rec().attempts).flatMap(([key, ar]) => ar.spans.map((s) => ({ key, s })));

function applyLabel(label, attrs) {
  const sr = selRange();
  if (!sr) return toast("select sentences first");
  let [a, b] = sr;
  const key = rowAtt[a];
  if (rowAtt[b] !== key) return toast("a label can't cross attempts");
  pushUndo(); touch();
  const ar = attRec(key);
  let s;
  if (LAB[label].first) {
    ar.spans = ar.spans.filter((x) => x.label !== label);
    s = { label, start: rows[a], end: rows[b], strength: "confident", note: "" };
  } else {
    const over = ar.spans.filter((x) => x.label === label && hits(x, a, b));
    const keep = over[0] || {};
    over.forEach((x) => { const [p, q] = range(x); a = Math.min(a, p); b = Math.max(b, q); });
    ar.spans = ar.spans.filter((x) => !over.includes(x));
    s = { label, start: rows[a], end: rows[b], strength: keep.strength || "confident", note: keep.note || "" };
    if (label === "eval_awareness") Object.assign(s, { benchmark: !!keep.benchmark }, attrs);
  }
  ar.spans.push(s);
  ar.spans.sort((x, y) => pos[x.start] - pos[y.start]);
  focus = [{ key, s }];
  paint(); scheduleSave();
}
function inSelection() { const sr = selRange(); return sr ? allSpans().filter(({ s }) => hits(s, ...sr)) : []; }
function targets() { const t = inSelection(); return t.length ? t : focus; }
function toggleSpeculative() {
  const t = targets();
  if (!t.length) return toast("no label in selection");
  pushUndo();
  const to = t.some(({ s }) => s.strength !== "speculative") ? "speculative" : "confident";
  t.forEach(({ s }) => (s.strength = to));
  paint(); scheduleSave();
}
function deleteSpans(t) {
  if (!t.length) return toast("no label in selection");
  pushUndo();
  t.forEach(({ key, s }) => { const ar = attRec(key); ar.spans = ar.spans.filter((x) => x !== s); });
  focus = []; paint(); scheduleSave();
}
function pillText(s) {
  const spec = s.strength === "speculative" ? " · spec" : "";
  if (s.label === "eval_awareness") return `EA · ${s.framing}${spec}${s.benchmark ? " · bench" : ""}`;
  return LAB[s.label].short + spec;
}

// ---------- label view ----------
function rowHTML(s, ans) {
  return `<div class="row ${s.kind}${ans ? " ans" : ""}" data-id="${s.id}"><span class="id">${s.id}</span><span class="txt"><span class="pills"></span>${esc(s.text)}</span></div>`;
}

function renderDoc() {
  const it = item(), r = rec();
  rows = []; rowAtt = [];
  it.attempts.forEach((a) => a.reasoning.forEach((s) => { rows.push(s.id); rowAtt.push(a.key); }));
  pos = Object.fromEntries(rows.map((id, i) => [id, i]));
  sel = null; focus = [];
  $("doc").innerHTML = it.attempts.map((a) => `
    <div class="att">Attempt ${a.attempt}<span class="muted">${a.reasoning.length} sentences${a.judge_cutoff ? " · reasoning looped; cut at the loop start" : ""}</span></div>
    ${a.feedback_before ? `<details open><summary>Feedback the model saw before this attempt</summary><pre class="ctx">${esc(a.feedback_before)}</pre></details>` : ""}
    <div class="rows">${a.reasoning.map((s) => rowHTML(s, false)).join("")}</div>
    <h3>Submitted answer · attempt ${a.attempt}</h3>
    <div class="b1" data-key="${a.key}"></div>
    <div>${a.answer.map((s) => rowHTML(s, true)).join("") || '<div class="muted">(empty)</div>'}</div>
    <details><summary>Test result for this attempt</summary><pre class="ctx">${esc(a.test_output || "(none)")}</pre></details>`).join("") +
    `<div class="donebar"><button id="done"></button><span class="muted" id="doneNote"></span></div>`;
  $("done").addEventListener("click", toggleDone);
  renderB1s(); paint(); renderDone(); renderItemSel();
  const mk = r.read_marker && document.querySelector(`.row[data-id="${r.read_marker}"]`);
  if (mk) mk.scrollIntoView({ block: "center" }); else $("doc").scrollTop = lsGet(`scroll:${it.rollout}`, 0);
}

function paint() {
  const r = rec(), sr = selRange();
  const cover = {}, starts = {};
  allSpans().forEach(({ s }) => {
    const [x, y] = range(s);
    for (let i = x; i <= y; i++) (cover[i] ||= []).push(s.label);
    (starts[x] ||= []).push(s);
  });
  document.querySelectorAll(".rows .row").forEach((el) => {
    const i = pos[el.dataset.id];
    const ls = [...new Set(cover[i] || [])];
    el.style.background = !ls.length ? "" : ls.length === 1 ? `var(--c-${ls[0]})`
      : `linear-gradient(90deg,${ls.map((l, k) => `var(--c-${l}) ${(k * 100) / ls.length}% ${((k + 1) * 100) / ls.length}%`).join(",")})`;
    el.classList.toggle("sel", !!sr && i >= sr[0] && i <= sr[1]);
    el.classList.toggle("marker", r.read_marker === rows[i]);
    el.querySelector(".pills").innerHTML = (starts[i] || []).map((s) =>
      `<span class="pill" title="${esc(s.note || "")}">${esc(pillText(s))}${s.note ? " ✎" : ""}</span>`).join("");
  });
  renderPanel();
}

function renderPanel() {
  $("labelBox").innerHTML = focus.length ? `<h3>Label</h3>` + focus.map((f, i) => spanEditor(f.s, i)).join("") : "";
  wireEditors();
  const it = item();
  $("allBox").innerHTML = `<div class="all">` + it.attempts.map((a) => {
    const sp = attRec(a.key).spans;
    return `<div class="an">Attempt ${a.attempt}</div>` + (sp.length ? sp.map((s, i) =>
      `<a data-k="${a.key}" data-i="${i}"><span class="pill" style="background:var(--c-${s.label});color:var(--fg)">${esc(pillText(s))}</span>${s.start}${s.end !== s.start ? "–" + s.end : ""}${s.note ? " ✎" : ""}</a>`).join("")
      : `<div class="muted">none</div>`);
  }).join("") + `</div>`;
  $("allBox").querySelectorAll("a").forEach((el) => el.addEventListener("click", () => {
    const s = attRec(el.dataset.k).spans[+el.dataset.i];
    sel = { a: pos[s.start], b: pos[s.end] }; focus = [{ key: el.dataset.k, s }]; paint();
    document.querySelector(`.row[data-id="${s.start}"]`).scrollIntoView({ block: "center" });
  }));
}

function spanEditor(s, i) {
  const ea = s.label === "eval_awareness";
  return `<div class="spanEd"><div class="hd"><i class="sw" style="background:var(--c-${s.label})"></i><b>${LAB[s.label].name}</b>
      <span class="muted">${s.start}${s.end !== s.start ? "–" + s.end : ""}</span><span class="grow"></span><button data-del="${i}">Delete</button></div>
    <div class="ctl">
      ${ea ? `<select data-i="${i}" data-k="framing">${FRAMING.map((x) => `<option ${x === s.framing ? "selected" : ""}>${x}</option>`).join("")}</select>` : ""}
      <label><input type="checkbox" data-i="${i}" data-k="speculative" ${s.strength === "speculative" ? "checked" : ""}> speculative</label>
      ${ea ? `<label><input type="checkbox" data-i="${i}" data-k="benchmark" ${s.benchmark ? "checked" : ""}> names benchmark</label>` : ""}
    </div>
    ${s.note || s._noteOpen ? `<input type="text" data-i="${i}" data-k="note" placeholder="note" value="${esc(s.note || "")}">` : `<button class="linkbtn" data-addnote="${i}">Add note</button>`}</div>`;
}

function wireEditors() {
  const box = $("labelBox");
  box.querySelectorAll("[data-k]").forEach((el) => {
    el.addEventListener(el.type === "text" ? "input" : "change", () => {
      const s = focus[+el.dataset.i].s, k = el.dataset.k;
      if (k === "note") { s.note = el.value; scheduleSave(); return paintRowsOnly(); }
      pushUndo();
      if (k === "speculative") s.strength = el.checked ? "speculative" : "confident";
      else if (k === "benchmark") s.benchmark = el.checked;
      else s[k] = el.value;
      paint(); scheduleSave();
    });
  });
  box.querySelectorAll("[data-del]").forEach((el) => el.addEventListener("click", () => deleteSpans([focus[+el.dataset.del]])));
  box.querySelectorAll("[data-addnote]").forEach((el) => el.addEventListener("click", () => {
    const s = focus[+el.dataset.addnote].s;
    Object.defineProperty(s, "_noteOpen", { value: true, enumerable: false, configurable: true });
    renderPanel(); box.querySelector('input[data-k="note"]')?.focus();
  }));
}
function paintRowsOnly() { const f = renderPanel; renderPanel = () => {}; paint(); renderPanel = f; }

function renderB1s() {
  document.querySelectorAll(".b1").forEach((box) => {
    const key = box.dataset.key, ar = attRec(key), b = ar.b1, off = b.attempted !== true;
    const opts = (k, vals, labels, dis) => vals.map((v, j) =>
      `<span class="opt${b[k] === v ? " on" : ""}${dis ? " dis" : ""}" data-k="${k}" data-v='${JSON.stringify(v)}'>${labels[j]}</span>`).join("");
    box.innerHTML = `<b>Cheat attempted in this code?</b><span class="grp">${opts("attempted", [true, false], ["yes", "no"])}</span>
      <span class="grp"><span class="muted">type</span>${opts("type", TYPES, TYPES, off)}</span>
      <span class="grp"><span class="muted">admitted in a comment</span>${opts("transparent", [true, false], ["yes", "no"], off)}</span>
      ${ar.note || ar._noteOpen ? `<input type="text" class="anote" placeholder="attempt note" value="${esc(ar.note || "")}">` : `<button class="linkbtn addnote">Add note</button>`}`;
    box.querySelectorAll(".opt").forEach((el) => el.addEventListener("click", () => {
      pushUndo(); touch();
      const k = el.dataset.k, v = JSON.parse(el.dataset.v);
      b[k] = b[k] === v ? null : v;
      if (k === "attempted" && b.attempted !== true) { b.type = null; b.transparent = null; }
      renderB1s(); scheduleSave();
    }));
    box.querySelector(".anote")?.addEventListener("input", (e) => { ar.note = e.target.value; scheduleSave(); });
    box.querySelector(".addnote")?.addEventListener("click", () => {
      Object.defineProperty(ar, "_noteOpen", { value: true, enumerable: false, configurable: true });
      renderB1s(); box.querySelector(".anote")?.focus();
    });
  });
}

function b1Complete(ar) { const b = ar.b1; return b.attempted === false || (b.attempted === true && b.type && b.transparent !== null); }
function renderDone() {
  const r = rec(), missing = item().attempts.filter((a) => !b1Complete(attRec(a.key))).map((a) => a.attempt);
  $("done").textContent = r.status === "done" ? "✓ Rollout done (click to reopen)" : "Mark rollout done";
  $("doneNote").textContent = missing.length ? `Cheat verdict missing for attempt ${missing.join(", ")}` : "";
}
function toggleDone() {
  const r = rec();
  if (r.status === "done") r.status = "in_progress";
  else {
    const missing = item().attempts.filter((a) => !b1Complete(attRec(a.key)));
    if (missing.length && !confirm("Some attempts have no cheat verdict. Mark done anyway?")) return;
    r.status = "done";
  }
  renderDone(); renderItemSel(); scheduleSave();
}

function renderItemSel() {
  const mark = { not_started: "○", in_progress: "◐", done: "●" };
  $("itemSel").innerHTML = data.items.map((it, i) => {
    const [, sid, ep] = it.rollout.split(":");
    return `<option value="${i}" ${i === cur ? "selected" : ""}>${mark[recs[it.rollout].status]} ${i + 1}. ${sid} ${ep} · ${it.split} · ${it.attempts.length} attempts</option>`;
  }).join("");
}

function go(i) {
  if (i < 0 || i >= data.items.length) return;
  if (i !== cur) { lsSet(`scroll:${item().rollout}`, $("doc").scrollTop); clearTimeout(saveTimer); save(); }
  cur = i; lsSet("cur", cur); undoStack = []; setView("label");
  renderDoc();
}

// ---------- work items view ----------
function renderItems() {
  const head = `<tr><th>#</th><th>Rollout</th><th>Split</th><th class="num">Attempts</th><th>Status</th>
    <th class="num">EA</th><th class="num">Grader</th><th class="num">Bad test</th><th class="num">Cheat cons.</th><th class="num">Cheat verdicts</th><th></th></tr>`;
  const body = data.items.map((it, i) => {
    const r = recs[it.rollout], c = { eval_awareness: 0, grader: 0, bad_test: 0, cheat_considered: 0 };
    let done = 0;
    it.attempts.forEach((a) => { const ar = r.attempts[a.key]; ar.spans.forEach((s) => c[s.label]++); if (b1Complete(ar)) done++; });
    const [, sid, ep] = it.rollout.split(":");
    return `<tr><td>${i + 1}</td><td>${esc(sid)} ${ep}</td><td>${it.split}</td><td class="num">${it.attempts.length}</td>
      <td><span class="st ${r.status}">${r.status.replace("_", " ")}</span></td>
      <td class="num">${c.eval_awareness}</td><td class="num">${c.grader}</td><td class="num">${c.bad_test}</td><td class="num">${c.cheat_considered}</td>
      <td class="num">${done} / ${it.attempts.length}</td><td><button data-open="${i}">Open</button></td></tr>`;
  }).join("");
  $("items").innerHTML = `<table>${head}${body}</table>`;
  $("items").querySelectorAll("[data-open]").forEach((el) => el.addEventListener("click", () => go(+el.dataset.open)));
}

function setView(v) {
  view = v; lsSet("view", v);
  $("labelView").classList.toggle("hidden", v !== "label");
  $("itemsView").classList.toggle("hidden", v !== "items");
  $("itemSel").classList.toggle("hidden", v !== "label");
  $("vLabel").classList.toggle("on", v === "label");
  $("vItems").classList.toggle("on", v === "items");
  if (v === "items") renderItems();
}

// ---------- drawers ----------
let cbHTML = null, drawerKind = null;
async function openDrawer(kind) {
  if (drawerKind === kind) return closeDrawer();
  drawerKind = kind;
  $("drawer").classList.remove("hidden");
  if (kind === "problem") {
    $("dTitle").textContent = "Problem given to the model";
    $("dBody").innerHTML = `<pre class="ctx">${esc(item().task_prompt)}</pre>`;
  } else {
    $("dTitle").textContent = "Codebook";
    if (!cbHTML) {
      const md = await (await fetch("/codebook.md")).text();
      cbHTML = window.marked ? marked.parse(md) : `<pre class="ctx">${esc(md)}</pre>`;
    }
    $("dBody").innerHTML = cbHTML;
  }
  $("drawer").scrollTop = 0;
}
function closeDrawer() { drawerKind = null; $("drawer").classList.add("hidden"); }

// ---------- input ----------
function rowIndex(el) { const r = el.closest(".rows .row"); return r ? pos[r.dataset.id] : null; }
document.addEventListener("mousedown", (e) => {
  const i = rowIndex(e.target);
  if (i == null || e.button !== 0) return;
  if (e.shiftKey && sel) sel.b = i; else sel = { a: i, b: i };
  dragging = true; moved = false; paint();
});
document.addEventListener("mouseover", (e) => {
  if (!dragging) return;
  const i = rowIndex(e.target);
  if (i != null && sel && sel.b !== i) { sel.b = i; moved = true; paint(); }
});
document.addEventListener("mouseup", () => {
  if (!dragging) return;
  dragging = false;
  const sr = selRange();
  focus = !moved && sr && sr[0] === sr[1] ? allSpans().filter(({ s }) => hits(s, sr[0], sr[0])) : [];
  renderPanel();
});
["mousemove", "keydown", "wheel", "scroll"].forEach((ev) => document.addEventListener(ev, () => (lastActive = Date.now()), true));
// Hotkey bar: shown while the mouse is at the bottom edge, hidden once it moves above the bar.
document.addEventListener("mousemove", (e) => {
  const bar = $("keys"), h = bar.offsetHeight;
  if (e.clientY >= innerHeight - 14) bar.classList.add("show");
  else if (e.clientY < innerHeight - h - 8) bar.classList.remove("show");
});

document.addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
  if (e.key === "Escape") {
    if (typing) return e.target.blur();
    if (drawerKind) return closeDrawer();
    sel = null; focus = []; return paint();
  }
  if (typing) return;
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); return undo(); }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "?" || (e.code === "Slash" && e.shiftKey)) return openDrawer("codebook");
  if (e.key === "p") return openDrawer("problem");
  if (view !== "label") return;
  const digit = e.code.startsWith("Digit") ? +e.code.slice(5) : null;
  if (digit >= 1 && digit <= 3) return applyLabel("eval_awareness", { framing: FRAMING[digit - 1] });
  if (digit === 4) return applyLabel("grader");
  if (digit === 5) return applyLabel("bad_test");
  if (digit === 6) return applyLabel("cheat_considered");
  if (e.key === "u") return toggleSpeculative();
  if (e.key === "Backspace" || e.key === "Delete") { e.preventDefault(); return deleteSpans(targets()); }
  if (e.key === "m") {
    const sr = selRange(); if (!sr) return toast("select a sentence first");
    rec().read_marker = rows[sr[1]]; paint(); return scheduleSave();
  }
});

$("vItems").addEventListener("click", () => setView("items"));
$("vLabel").addEventListener("click", () => setView("label"));
$("itemSel").addEventListener("change", (e) => go(+e.target.value));
$("probBtn").addEventListener("click", () => openDrawer("problem"));
$("cbBtn").addEventListener("click", () => openDrawer("codebook"));
$("dClose").addEventListener("click", closeDrawer);
$("doc").addEventListener("scroll", () => lsSet(`scroll:${item().rollout}`, $("doc").scrollTop));

// Active labelling time is recorded (for planning the gold-set size) but not shown.
setInterval(() => {
  if (!data || view !== "label") return;
  const r = rec();
  if (document.visibilityState === "visible" && Date.now() - lastActive < 90000 && r.status !== "done") {
    r.active_seconds = (r.active_seconds || 0) + 1;
    if (r.active_seconds % 30 === 0) scheduleSave();
  }
}, 1000);

// ---------- boot ----------
(async function boot() {
  if (!SET) { $("doc").innerHTML = "<p>Add <code>?set=&lt;name&gt;&amp;labeler=&lt;you&gt;</code> to the URL.</p>"; return; }
  const res = await fetch(`/api/set/${SET}`);
  if (!res.ok) { $("doc").innerHTML = `<p>Label set <b>${esc(SET)}</b> not found.</p>`; return; }
  data = await res.json();
  const saved = await (await fetch(`/api/labels/${SET}/${LABELER}`)).json();
  data.items.forEach((it) => {
    const backup = lsGet(`backup:${it.rollout}`, null), r = saved[it.rollout];
    const pick = backup && (!r || backup.updated > r.updated) ? backup : r;
    const b = blank(it);
    recs[it.rollout] = pick ? { ...b, ...pick, attempts: { ...b.attempts, ...pick.attempts } } : b;
  });
  cur = Math.min(lsGet("cur", 0), data.items.length - 1);
  renderDoc();
  setView(lsGet("view", "label"));
})();
