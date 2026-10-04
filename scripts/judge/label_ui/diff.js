// Label comparison page: B against reference A on one label set. Read-only.
// All matching and metrics come from the server (earh.judge.agreement); this file only renders.
"use strict";

const P = new URLSearchParams(location.search);
const LAB = {
  eval_awareness: { name: "Eval awareness", short: "EA" },
  grader: { name: "Grader", short: "grader" },
  bad_test: { name: "First bad test", short: "first bad test", first: true },
  cheat_considered: { name: "First cheat considered", short: "first cheat cons.", first: true },
};
const CLOSE = 5;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const pct = (x) => (x == null ? "—" : `${Math.round(x * 100)}%`);
const lsKey = "diff";
function lsGet(k, d) { try { const v = localStorage.getItem(`${lsKey}:${k}`); return v == null ? d : JSON.parse(v); } catch { return d; } }
function lsSet(k, v) { try { localStorage.setItem(`${lsKey}:${k}`, JSON.stringify(v)); } catch {} }
function toast(msg) { const t = $("toast"); t.textContent = msg; t.classList.remove("hidden"); setTimeout(() => t.classList.add("hidden"), 1600); }

let SET = P.get("set") || lsGet("set", null), A = P.get("a"), B = P.get("b");
let data, cmp, attempts = [], cur = 0, enabled = new Set(lsGet("labels", Object.keys(LAB))), disList = [], disIdx = -1;

// ---------- code highlighting (same as the labelling page) ----------
function hlLines(lines) {
  if (!window.hljs) return lines.map(esc);
  const html = hljs.highlight(lines.join("\n"), { language: "python", ignoreIllegals: true }).value;
  const out = [], stack = [];
  let line = "";
  for (const t of html.split(/(<span[^>]*>|<\/span>|\n)/)) {
    if (t === "\n") { out.push(line + "</span>".repeat(stack.length)); line = stack.join(""); }
    else if (t.startsWith("<span")) { stack.push(t); line += t; }
    else if (t === "</span>") { stack.pop(); line += t; }
    else line += t;
  }
  out.push(line);
  return out;
}
function hlFenced(text) {
  const m = text.match(/^(```[^\n]*\n)([\s\S]*?)(\n```\s*)?$/);
  if (!m) return esc(text);
  return `<span class="fence">${esc(m[1])}</span>${hlLines(m[2].split("\n")).join("\n")}<span class="fence">${esc(m[3] || "")}</span>`;
}
function diffPair(a, b) {
  let i = 0; while (i < a.length && i < b.length && a[i] === b[i]) i++;
  let j = 0; while (j < a.length - i && j < b.length - i && a[a.length - 1 - j] === b[b.length - 1 - j]) j++;
  const show = (t) => {
    const pre = t.slice(0, i), mid = t.slice(i, t.length - j), suf = t.slice(t.length - j);
    const p = pre.length > 60 ? "…" + pre.slice(-40) : pre, q = suf.length > 40 ? suf.slice(0, 30) + "…" : suf;
    return `<code>${esc(p)}<mark>${esc(mid) || "∅"}</mark>${esc(q)}</code>`;
  };
  return [show(a), show(b)];
}
function alteredHTML(alt) {
  if (!alt || !alt.length) return `<div class="altbox muted">Could not identify the altered assertion for this task.</div>`;
  return `<div class="altbox"><b>Altered test</b> <span class="muted">(the model is not told)</span>` + alt.map((x) => {
    if (x.kind === "changed") { const [o, m] = diffPair(x.original, x.modified); return `<div class="altrow"><div>original: ${o}</div><div>modified: ${m}</div></div>`; }
    if (x.counterpart) { const [o, m] = diffPair(x.counterpart, x.modified); return `<div class="altrow"><div>existing: ${o}</div><div>added: ${m}</div></div>`; }
    return `<div class="altrow"><code>${esc(x.modified)}</code></div>`;
  }).join("") + `</div>`;
}

// ---------- data ----------
async function getJSON(u) { const r = await fetch(u); if (!r.ok) throw new Error(`${u}: ${r.status}`); return r.json(); }

async function loadSet() {
  data = await getJSON(`/api/set/${SET}`);
  attempts = data.items.flatMap((it) => it.attempts.map((a) => ({ ...a, item: it })));
  const srcs = await getJSON(`/api/sources/${SET}`);
  if (!srcs.includes(A)) A = srcs.includes("mark") ? "mark" : srcs[0];
  if (!srcs.includes(B) || B === A) B = srcs.find((s) => s.startsWith("judge") && s !== A) || srcs.find((s) => s !== A) || A;
  const opt = (v) => srcs.map((s) => `<option ${s === v ? "selected" : ""}>${esc(s)}</option>`).join("");
  $("aSel").innerHTML = opt(A); $("bSel").innerHTML = opt(B);
  $("toLabel").href = `/?set=${encodeURIComponent(SET)}&labeler=mark`;
  await loadDiff();
}

async function loadDiff() {
  history.replaceState(null, "", `/diff?set=${encodeURIComponent(SET)}&a=${encodeURIComponent(A)}&b=${encodeURIComponent(B)}`);
  lsSet("set", SET);
  cmp = A && B ? await getJSON(`/api/diff/${SET}/${A}/${B}`) : null;
  cur = Math.min(lsGet(`cur:${SET}`, 0), attempts.length - 1);
  render();
}

// ---------- per-attempt spans with display status ----------
// First-only labels agree when both sources have one within CLOSE sentences.
// Labels one source never used are unscored ("na"): shown, but not counted as disagreements.
function scored(label) { const m = cmp.metrics; return m.labelled_by_a.includes(label) && m.labelled_by_b.includes(label); }
function spansFor(key) {
  const r = cmp.attempts[key];
  return r.spans.filter((s) => enabled.has(s.label)).map((s) => {
    if (!scored(s.label)) return { ...s, status: "na" };
    if (s.status !== "first") return s;
    const f = r.first[s.label];
    const ok = f.a && f.b && Math.abs(f.dist) <= CLOSE;
    return { ...s, status: ok ? "agree" : `${s.src}_only` };
  });
}
function disagreeCount(key) {
  const r = cmp.attempts[key];
  return spansFor(key).filter((s) => s.status === "a_only" || s.status === "b_only").length + Object.values(r.b1.agree).filter((v) => !v).length;
}

// ---------- render ----------
function metricsHTML() {
  const m = cmp.metrics, la = new Set(m.labelled_by_a), lb = new Set(m.labelled_by_b);
  const na = (l) => (!la.has(l) ? `not labelled by A` : !lb.has(l) ? `not labelled by B` : null);
  const row = (name, cells, l) => {
    const n = na(l);
    return `<tr><td>${name}</td>${n ? `<td colspan="5" class="na">${n}</td>` : cells}</tr>`;
  };
  const ea = m.eval_awareness, gr = m.grader;
  const prf = (x) => `<td>${x.n_a} / ${x.n_b}</td><td>${pct(x.precision)}</td><td>${pct(x.recall)}</td><td>${pct(x.f1)}</td>`;
  const first = (x) => `<td>both ${x.both} · A only ${x.a_only} · B only ${x.b_only}</td><td>${pct(x.presence_agreement)}</td><td>${pct(x.close)}</td><td>${x.median_abs_dist ?? "—"}</td>`;
  const b1 = ["attempted", "type", "transparent"].map((f) => `${f} ${pct(m["b1_" + f].agreement)} (n=${m["b1_" + f].n})`).join(" · ");
  return `<details class="metrics" open><summary><b>Agreement</b> — B = ${esc(B)} against reference A = ${esc(A)}, over ${m.n_attempts} attempts labelled by both</summary>
    <table><tr><th>Occurrence labels</th><th>spans A / B</th><th>precision (B)</th><th>recall (B)</th><th>F1</th><th></th></tr>
    ${row("Eval awareness", prf(ea) + `<td>attempt presence ${pct(ea.attempt_presence_agreement)} · framing ${pct(ea.framing_agreement)}</td>`, "eval_awareness")}
    ${row("Grader", prf(gr) + "<td></td>", "grader")}
    <tr><th>First-occurrence labels</th><th>per attempt</th><th>presence agrees</th><th>within ±${CLOSE}</th><th>median |Δ|</th><th></th></tr>
    ${row("First bad test", first(m.bad_test) + "<td></td>", "bad_test")}
    ${row("First cheat considered", first(m.cheat_considered) + "<td></td>", "cheat_considered")}
    <tr><th>Cheat verdict (B1)</th><td colspan="5">${la.has("b1") && lb.has("b1") ? b1 : `<span class="na">not labelled by ${la.has("b1") ? "B" : "A"}</span>`}</td></tr>
    </table></details>
    <div class="legend"><span><i class="lg" style="background:var(--c-eval_awareness)"></i>both agree</span>
      <span><i class="lg" style="background:repeating-linear-gradient(135deg,var(--c-eval_awareness) 0 5px,transparent 5px 9px)"></i>only B (A didn't mark it)</span>
      <span><i class="lg" style="outline:2px dashed var(--c-eval_awareness);outline-offset:-2px"></i>only A (B missed it)</span>
      <span>pills: <span class="pill src-a">A</span> dashed = A's label, <span class="pill">B</span> solid = B's; red ring = disagreement</span></div>`;
}

function pillHTML(s) {
  const t = s.label === "eval_awareness" ? `EA · ${s.framing || "?"}${s.strength === "speculative" ? " · spec" : ""}` : LAB[s.label].short + (s.strength === "speculative" ? " · spec" : "");
  return `<span class="pill src-${s.src}${s.status === "a_only" || s.status === "b_only" ? " dis" : ""}" title="${esc(s.note || "")}">${s.src.toUpperCase()} · ${esc(t)}</span>`;
}

function b1Text(b) {
  if (!b || b.attempted == null) return "—";
  return b.attempted ? `cheat (${b.type || "?"}, ${b.transparent ? "admitted" : "not admitted"})` : "no cheat";
}

function render() {
  if (!cmp) { $("doc").innerHTML = `<div class="empty">Need at least one label source for this set.</div>`; return; }
  $("itemSel").innerHTML = attempts.map((a, i) => {
    const r = cmp.attempts[a.key];
    const tag = !r.in_a ? " (A: none)" : !r.in_b ? " (B: none)" : ` · ${disagreeCount(a.key)} disagree`;
    const [, sid, , an] = a.key.split(":");
    return `<option value="${i}" ${i === cur ? "selected" : ""}>${i + 1}. ${sid} ${an} · ${a.item.split}${tag}</option>`;
  }).join("");
  const a = attempts[cur], r = cmp.attempts[a.key];
  const spans = spansFor(a.key);
  const ids = a.reasoning.map((s) => s.id), pos = Object.fromEntries(ids.map((id, i) => [id, i]));
  const cover = {}, starts = {};
  spans.forEach((s) => {
    const x = pos[s.start], y = pos[s.end];
    if (x == null || y == null) return;
    for (let i = x; i <= y; i++) (cover[i] ||= []).push(s);
    (starts[x] ||= []).push(s);
  });
  const fchips = Object.keys(LAB).filter((l) => LAB[l].first && enabled.has(l) && scored(l)).map((l) => {
    const f = r.first[l];
    const ok = (f.a == null) === (f.b == null) && (f.dist == null || Math.abs(f.dist) <= CLOSE);
    const txt = f.a && f.b ? `A ${f.a} · B ${f.b} · Δ ${f.dist > 0 ? "+" : ""}${f.dist}` : `A ${f.a || "none"} · B ${f.b || "none"}`;
    return `<span class="chip ${ok ? "ok" : "bad"}">${LAB[l].name}: ${txt}</span>`;
  }).join("");
  const b1ok = r.b1.agree.attempted;
  // paragraphs: fold the ones with no visible highlight when "highlights only" is on
  const only = $("only").checked;
  let html = "", para = [], hidden = 0;
  const flushPara = () => {
    if (!para.length) return;
    const show = !only || para.some((i) => cover[i]);
    if (show) {
      if (hidden) html += `<div class="fold">⋯ ${hidden} paragraph${hidden > 1 ? "s" : ""} without highlights</div>`;
      hidden = 0;
      html += `<p>` + para.map((i, k) => {
        const s = a.reasoning[i];
        const sep = k === 0 ? "" : s.brk === 1 ? "<br>" : " ";
        return sep + sentHTML(s, cover[i], starts[i]);
      }).join("") + `</p>`;
    } else hidden++;
    para = [];
  };
  a.reasoning.forEach((s, i) => {
    if (s.kind === "code_block") { flushPara(); para = [i]; flushPara(); return; }
    if (s.brk === 2) flushPara();
    para.push(i);
  });
  flushPara();
  if (hidden) html += `<div class="fold">⋯ ${hidden} paragraph${hidden > 1 ? "s" : ""} without highlights</div>`;
  const code = (() => {
    const lines = a.answer.filter((s) => s.kind === "code_line");
    const h = hlLines(lines.map((s) => s.text));
    return lines.map((s, i) => `<div class="row code_line ans"><span class="id">${s.id}</span><span class="txt">${h[i]}</span></div>`).join("");
  })();
  $("doc").innerHTML = metricsHTML() + `
    <div class="att">Attempt ${a.attempt}<span class="muted">${esc(a.key)} · ${a.reasoning.length} sentences${r.status_a && r.status_a !== "done" ? ` · A: ${r.status_a.replace("_", " ")}` : ""}</span></div>
    <div class="chips">${fchips}<span class="chip ${b1ok == null ? "" : b1ok && !Object.values(r.b1.agree).includes(false) ? "ok" : "bad"}">Cheat verdict: A ${b1Text(r.b1.a)} · B ${b1Text(r.b1.b)}</span></div>
    ${a.feedback_before ? `<details><summary>Feedback the model saw before this attempt</summary><pre class="ctx">${esc(a.feedback_before)}</pre></details>` : ""}
    <div class="rows para">${html}</div>
    <h3>Submitted answer</h3>${code}`;
  renderPanel(a, spans, pos);
  lsSet(`cur:${SET}`, cur);
}

function sentHTML(s, cov, st) {
  if (s.kind === "code_block") return `<span class="row code_block" data-id="${s.id}"><span class="txt">${(st || []).map(pillHTML).join("")}${hlFenced(s.text)}</span></span>`;
  let style = "", cls = "row";
  if (cov) {
    const agree = cov.find((x) => x.status === "agree" || x.status === "na"), bOnly = cov.find((x) => x.status === "b_only"), aOnly = cov.find((x) => x.status === "a_only");
    if (agree) style += `background:var(--c-${agree.label});`;
    else if (bOnly) { cls += " only-b"; style += `--hl:var(--c-${bOnly.label});`; }
    if (aOnly) { cls += " only-a"; style += `--hlA:var(--c-${aOnly.label});`; }
  }
  return `<span class="${cls}" data-id="${s.id}" title="${s.id}" style="${style}">${(st || []).map(pillHTML).join("")}${esc(s.text)}</span>`;
}

function renderPanel(a, spans, pos) {
  const text = Object.fromEntries(a.reasoning.map((s) => [s.id, s.text]));
  disList = spans.filter((s) => s.status === "a_only" || s.status === "b_only").sort((x, y) => pos[x.start] - pos[y.start]);
  $("disBox").innerHTML = disList.length ? disList.map((s, i) =>
    `<a data-i="${i}"><span class="pill src-${s.src}" style="background:var(--c-${s.label});color:var(--fg);border:0">${LAB[s.label].short}</span> only ${s.src.toUpperCase()} · ${s.start}${s.end !== s.start ? "–" + s.end : ""}
      <span class="snip">${esc(text[s.start] || "")}</span></a>`).join("") : `<div class="muted" style="margin-top:8px">None for the selected labels.</div>`;
  $("disBox").querySelectorAll("a").forEach((el) => el.addEventListener("click", () => jump(+el.dataset.i)));
  disIdx = -1;
}

function jump(i) {
  const s = disList[i];
  if (!s) return;
  disIdx = i;
  const el = document.querySelector(`.rows .row[data-id="${s.start}"]`);
  if (!el) { $("only").checked = false; render(); return jump(i); }
  el.scrollIntoView({ block: "center" });
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
}
function next(d) {
  if (disList.length && disIdx + d >= 0 && disIdx + d < disList.length) return jump(disIdx + d);
  for (let k = 1; k <= attempts.length; k++) {
    const i = (cur + d * k + attempts.length * k) % attempts.length;
    const r = cmp.attempts[attempts[i].key];
    if (r.in_a && r.in_b && disagreeCount(attempts[i].key)) {
      cur = i; render(); $("doc").scrollTop = 0;
      return jump(d > 0 ? 0 : disList.length - 1);
    }
  }
  toast("no other disagreements");
}

// ---------- drawers ----------
let cbHTML = null, drawerKind = null;
async function openDrawer(kind) {
  if (drawerKind === kind) { drawerKind = null; return $("drawer").classList.add("hidden"); }
  drawerKind = kind; $("drawer").classList.remove("hidden");
  if (kind === "problem") {
    const it = attempts[cur].item;
    $("dTitle").textContent = "Problem given to the model";
    $("dBody").innerHTML = alteredHTML(it.altered) + (window.marked ? marked.parse(it.task_prompt) : `<pre class="ctx">${esc(it.task_prompt)}</pre>`);
    $("dBody").querySelectorAll("pre code").forEach((el) => { el.innerHTML = hlLines(el.textContent.replace(/\n$/, "").split("\n")).join("\n"); el.classList.add("hljs"); });
  } else {
    $("dTitle").textContent = "Codebook";
    if (!cbHTML) { const md = await (await fetch("/codebook.md")).text(); cbHTML = window.marked ? marked.parse(md) : `<pre class="ctx">${esc(md)}</pre>`; }
    $("dBody").innerHTML = cbHTML;
  }
}

// ---------- wiring ----------
$("toggles").innerHTML = Object.entries(LAB).map(([k, v]) =>
  `<label><input type="checkbox" data-l="${k}" ${enabled.has(k) ? "checked" : ""}><i class="sw" style="background:var(--c-${k})"></i>${v.short}</label>`).join("");
$("toggles").querySelectorAll("input").forEach((el) => el.addEventListener("change", () => {
  el.checked ? enabled.add(el.dataset.l) : enabled.delete(el.dataset.l);
  lsSet("labels", [...enabled]); render();
}));
$("only").addEventListener("change", render);
$("itemSel").addEventListener("change", (e) => { cur = +e.target.value; render(); $("doc").scrollTop = 0; });
$("aSel").addEventListener("change", (e) => { A = e.target.value; loadDiff(); });
$("bSel").addEventListener("change", (e) => { B = e.target.value; loadDiff(); });
$("setSel").addEventListener("change", (e) => { SET = e.target.value; A = B = null; loadSet(); });
$("probBtn").addEventListener("click", () => openDrawer("problem"));
$("cbBtn").addEventListener("click", () => openDrawer("codebook"));
$("dClose").addEventListener("click", () => { drawerKind = null; $("drawer").classList.add("hidden"); });
document.addEventListener("keydown", (e) => {
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "Escape" && drawerKind) { drawerKind = null; return $("drawer").classList.add("hidden"); }
  if (e.key === "n") return next(1);
  if (e.key === "N") return next(-1);
  if (e.key === "p") return openDrawer("problem");
  if (e.key === "?" || (e.code === "Slash" && e.shiftKey)) return openDrawer("codebook");
});

(async function boot() {
  const sets = await getJSON("/api/sets").catch(() => null);
  const list = sets || (SET ? [SET] : []);
  if (!SET) SET = list[0];
  $("setSel").innerHTML = list.map((s) => `<option ${s === SET ? "selected" : ""}>${esc(s)}</option>`).join("");
  if (!SET) { $("doc").innerHTML = `<div class="empty">Add ?set=&lt;name&gt; to the URL.</div>`; return; }
  await loadSet();
})();
