"""Render judged attempts as a self-contained HTML page with highlighted spans.

    uv run python scripts/judge/render_html.py \
        --attempts logs/12-judge/pilot10/v6/attempts.jsonl \
        --judge logs/12-judge/pilot10/v6/logs:A,B1 logs/12-judge/pilot10/v7-b2/logs \
        --out logs/12-judge/pilot10/review.html

Each sentence / code line is shown with its ID; spans are highlighted by label (hover for
attributes) and each label can be toggled, e.g. to check one label's precision at a time.
First-only labels (bad_test, cheat_considered) show the earliest occurrence per attempt.
--overlay adds reference annotations drawn as dashed outlines. "Highlights only" collapses
stretches with no visible highlight.
"""

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

from earh.judge.assemble import keep_first, load_judge_spans, merge_adjacent
from earh.judge.extract import Attempt
from earh.judge.units import reasoning_segments
from earh.segment import segment_answer

# label -> (legend text, light colour, dark colour). Order = legend / toggle order.
LABELS = {
    "eval_awareness": ("Eval awareness", "#f6c945", "#8a6d10"),
    "grader": ("Grader", "#8ec5ff", "#1f4f80"),
    "bad_test": ("First bad test", "#c7b3ff", "#5b45a8"),
    "cheat_considered": ("First cheat considered", "#ffb066", "#9a5410"),
    "cheat_impl": ("Cheat impl (code)", "#ff6b6b", "#b83232"),
}
POINT_LABELS = {"bad_test", "cheat_considered"}

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#6b6b70;--card:#fff;--line:#e6e3dc;--ref:#0a8f5b;__LIGHT__}
@media (prefers-color-scheme: dark){:root{--bg:#161618;--fg:#ececec;--muted:#9a9aa0;--card:#1f1f22;--line:#333;--ref:#3ddc97;__DARK__}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center}
h1{font-size:16px;margin:0 8px 0 0}
.tg{display:inline-flex;align-items:center;gap:5px;font-size:12px;cursor:pointer;user-select:none}
.sw{width:12px;height:12px;border-radius:3px;display:inline-block}
main{display:grid;grid-template-columns:270px 1fr}nav{position:sticky;top:52px;height:calc(100vh - 52px);overflow:auto;border-right:1px solid var(--line);padding:8px}
nav a{display:block;padding:6px 8px;border-radius:6px;color:inherit;text-decoration:none;font-size:12px}nav a:hover{background:var(--line)}
nav .meta{color:var(--muted)}section{padding:12px 20px 40px;max-width:1100px;min-width:0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:16px 0}
.card h2{font-size:14px;margin:0 0 6px;word-break:break-all}.stats{color:var(--muted);font-size:12px;margin-bottom:8px}
.stats b{color:var(--fg)}
h3{font-size:12px;color:var(--muted);margin:12px 0 4px;text-transform:uppercase;letter-spacing:.04em}
.item{display:flex;gap:8px;padding:1px 4px;border-radius:4px;white-space:pre-wrap;word-break:break-word}
.id{flex:0 0 72px;color:var(--muted);font:11px ui-monospace,monospace;padding-top:2px}.code .txt{font:12px ui-monospace,monospace}
.badge{font-size:11px;font-weight:600;padding:0 6px;border-radius:8px;margin-right:6px;background:var(--fg);color:var(--bg)}
.ref{outline:2px dashed var(--ref);outline-offset:-2px}
.fold{color:var(--muted);font-size:12px;padding:2px 80px}.hidden{display:none}
details{margin:6px 0}summary{cursor:pointer;color:var(--muted);font-size:12px}pre.fb{white-space:pre-wrap;font:12px ui-monospace,monospace;color:var(--muted)}
@media (max-width:760px){main{grid-template-columns:1fr}nav{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line)}.id{flex-basis:56px}.fold{padding-left:8px}}
"""

JS = """
const on=()=>new Set([...document.querySelectorAll('input[data-label]')].filter(i=>i.checked).map(i=>i.dataset.label));
function paint(){const en=on(),only=document.getElementById('only').checked;
 document.querySelectorAll('.item').forEach(it=>{const ls=(it.dataset.labs||'').split(' ').filter(l=>en.has(l));
  it.dataset.vis=ls.length?'1':'';
  it.style.background=ls.length===0?'':ls.length===1?`var(--c-${ls[0]})`:
   `linear-gradient(90deg,${ls.map((l,i)=>`var(--c-${l}) ${i*100/ls.length}% ${(i+1)*100/ls.length}%`).join(',')})`;
  it.querySelectorAll('.badge').forEach(b=>b.classList.toggle('hidden',!en.has(b.dataset.label)))});
 document.querySelectorAll('.card').forEach(c=>{c.querySelectorAll('.fold').forEach(f=>f.remove());
  const items=[...c.querySelectorAll('.item')];
  if(!only){items.forEach(i=>i.classList.remove('hidden'));return}
  const keep=new Set();items.forEach((it,i)=>{if(it.dataset.vis||it.classList.contains('ref')){for(let k=i-2;k<=i+2;k++)keep.add(k)}});
  let run=0;const fold=(n)=>{const f=document.createElement('div');f.className='fold';f.textContent='⋯ '+n+' not shown';return f};
  items.forEach((it,i)=>{const h=!keep.has(i);it.classList.toggle('hidden',h);
   if(h){run++}else if(run){it.before(fold(run));run=0}});
  if(run&&items.length)items[items.length-1].after(fold(run))});
 try{localStorage.setItem('judge-review',JSON.stringify({labels:[...en],only}))}catch(e){}}
try{const s=JSON.parse(localStorage.getItem('judge-review')||'null');if(s){
 document.querySelectorAll('input[data-label]').forEach(i=>i.checked=s.labels.includes(i.dataset.label));
 document.getElementById('only').checked=s.only}}catch(e){}
document.querySelectorAll('header input').forEach(i=>i.addEventListener('change',paint));paint();
"""


def _attrs(span: dict) -> str:
    """Compact attribute string for a span's tooltip."""
    keys = ("framing", "strength", "benchmark")
    return ", ".join(f"{k}={span[k]}" for k in keys if k in span)


def render(
    attempts: list[Attempt], spans_by_key: dict[str, dict], overlay: dict[str, list]
) -> str:
    """Build the HTML page: one card per attempt, highlights toggleable per label.

    @param attempts: Attempts to show, in order.
    @param spans_by_key: attempt_key -> {"spans": [...], "summary": ...} (from load_judge_spans).
    @param overlay: attempt_key -> reference spans ({ids, label, note}) drawn as dashed outlines.
    @returns: HTML document text.
    """
    nav, cards = [], []
    for n, a in enumerate(attempts):
        segs, info = reasoning_segments(a)
        answer = segment_answer(a.answer, a.attempt)
        order = {s.id: i for i, s in enumerate(segs + answer)}
        j = spans_by_key.get(a.key, {"spans": [], "summary": None})
        known = [s for s in j["spans"] if all(i in order for i in s["ids"])]
        spans = keep_first(merge_adjacent(known, order), order)
        lab = defaultdict(list)
        for s in spans:
            for i in s["ids"]:
                lab[i].append(s)
        ref = defaultdict(list)
        for r in overlay.get(a.key, []):
            for i in r["ids"]:
                ref[i].append(r)
        counts = defaultdict(int)
        first = {}
        for s in spans:
            counts[s["label"]] += 1
            if s["label"] in POINT_LABELS:
                first[s["label"]] = (
                    f"{s['start']} ({order[s['start']] / max(1, len(segs) - 1):.0%})"
                )
        summary = j.get("summary") or {}
        b1 = (
            f"attempted, {summary['type']}, {'disclosed' if summary['transparent'] else 'hidden'}"
            if summary.get("attempted")
            else ("not attempted" if summary else "—")
        )
        stat = (
            f"passed tests: <b>{a.passed}</b> · B1: <b>{b1}</b> · EA: <b>{counts['eval_awareness']}</b>"
            f" · grader: <b>{counts['grader']}</b> · first bad test: <b>{first.get('bad_test', 'none')}</b>"
            f" · first cheat considered: <b>{first.get('cheat_considered', 'none')}</b>"
            f" · {len(segs)} sentences"
        )
        if info.get("judge_cutoff"):
            stat += f" · loop cut at char {info['judge_cutoff']}"

        def row(s, code: bool, lab=lab, ref=ref) -> str:
            """One sentence / code line with its labels as data attributes."""
            ls = lab.get(s.id, [])
            rs = ref.get(s.id, [])
            cls = "item" + (" code" if code else "") + (" ref" if rs else "")
            tip = " | ".join(f"{LABELS[x['label']][0]} {_attrs(x)}".strip() for x in ls)
            tip += "".join(f" | REF {x['label']}: {x.get('note', '')}" for x in rs)
            badges = "".join(
                f'<span class="badge" data-label="{x["label"]}">{LABELS[x["label"]][0]}</span>'
                for x in ls
                if x["label"] in POINT_LABELS
            )
            labs = " ".join(dict.fromkeys(x["label"] for x in ls))
            return (
                f'<div class="{cls}" data-labs="{labs}" title="{html.escape(tip)}"><span class="id">{s.id}</span>'
                f'<span class="txt">{badges}{html.escape(s.text)}</span></div>'
            )

        rows = [row(s, False) for s in segs]
        code_rows = [row(s, s.kind == "code_line") for s in answer]
        anchor = f"a{n}"
        nav.append(
            f'<a href="#{anchor}">{html.escape(a.sample_id)} a{a.attempt} <span class="meta">{a.split}'
            f"{' · passed' if a.passed else ''} · EA {counts['eval_awareness']}"
            f"{' · cheat' if summary.get('attempted') else ''}</span></a>"
        )
        fb = (
            f"<details><summary>Feedback before this attempt</summary><pre class='fb'>{html.escape(a.feedback_before)}</pre></details>"
            if a.feedback_before
            else ""
        )
        cards.append(
            f'<div class="card" id="{anchor}"><h2>{html.escape(a.key)}</h2><div class="stats">{stat}</div>{fb}'
            f"<h3>Reasoning</h3>{''.join(rows)}<h3>Submitted answer</h3>{''.join(code_rows)}</div>"
        )
    toggles = "".join(
        f'<label class="tg"><input type="checkbox" data-label="{k}" checked>'
        f'<i class="sw" style="background:var(--c-{k})"></i>{t}</label>'
        for k, (t, _, _) in LABELS.items()
    )
    if overlay:
        toggles += '<span class="tg"><i class="sw" style="outline:2px dashed var(--ref)"></i>Reference</span>'
    css = CSS.replace(
        "__LIGHT__", ";".join(f"--c-{k}:{v[1]}" for k, v in LABELS.items())
    ).replace("__DARK__", ";".join(f"--c-{k}:{v[2]}" for k, v in LABELS.items()))
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Judge Review</title><style>{css}</style></head><body>"
        f"<header><h1>Judge review</h1>{toggles}"
        "<label class='tg'><input type='checkbox' id='only' checked> Highlights only (±2)</label></header>"
        f"<main><nav>{''.join(nav)}</nav><section>{''.join(cards)}</section></main><script>{JS}</script></body></html>"
    )


def main() -> None:
    """Parse args, load attempts / judge spans / overlay, and write the HTML file."""
    p = argparse.ArgumentParser()
    p.add_argument("--attempts", required=True)
    p.add_argument(
        "--judge",
        nargs="+",
        required=True,
        help="judge log dirs, optionally dir:A,B2 to keep only those passes",
    )
    p.add_argument(
        "--overlay", default=None, help="JSON {attempt_key: [{ids, label, note}]}"
    )
    p.add_argument("--out", required=True)
    args = p.parse_args()
    attempts = [Attempt(**json.loads(line)) for line in open(args.attempts)]
    merged: dict[str, dict] = defaultdict(lambda: {"spans": [], "summary": None})
    for spec in args.judge:
        d, _, ps = spec.partition(":")
        for k, v in load_judge_spans(d, set(ps.split(",")) if ps else None).items():
            merged[k]["spans"] += v["spans"]
            merged[k]["summary"] = merged[k]["summary"] or v["summary"]
    overlay = json.load(open(args.overlay)) if args.overlay else {}
    Path(args.out).write_text(render(attempts, merged, overlay))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
