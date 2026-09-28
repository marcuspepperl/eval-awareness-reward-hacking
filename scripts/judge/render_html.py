"""Render judged attempts as a self-contained HTML page with highlighted spans.

    uv run python scripts/judge/render_html.py \
        --attempts logs/12-judge/pilot10/v3-high/attempts.jsonl \
        --judge logs/12-judge/pilot10/v3-high/logs logs/12-judge/pilot10/v3-high-b2/logs \
        --overlay logs/12-judge/pilot10/recall/review.json \
        --out logs/12-judge/pilot10/review.html

Each sentence / code line is shown with its ID; spans are highlighted by label (hover for
attributes). --overlay adds reference annotations (e.g. recall reviewers) drawn as outlines,
so judge misses are visible. "Highlights only" collapses unlabelled stretches.
"""

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

from earh.judge.assemble import load_judge_spans, merge_adjacent
from earh.judge.extract import Attempt
from earh.judge.units import reasoning_segments
from earh.segment import segment_answer

LABELS = {
    "eval_awareness": "Eval awareness",
    "grader": "Grader reasoning",
    "contradiction": "Recognizes bad test",
    "cheat": "Cheat (considered / decided)",
    "cheat_code": "Cheat code",
}

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#6b6b70;--card:#fff;--line:#e6e3dc;
--ea:#f6c945;--grader:#8ec5ff;--contradiction:#c7b3ff;--cheat:#ff9f9f;--cheat-d:#ff5c5c;--code:#ffb3b3;--ref:#0a8f5b}
@media (prefers-color-scheme: dark){:root{--bg:#161618;--fg:#ececec;--muted:#9a9aa0;--card:#1f1f22;--line:#333;
--ea:#8a6d10;--grader:#1f4f80;--contradiction:#4b3a8a;--cheat:#7a2e2e;--cheat-d:#b83232;--code:#7a2e2e;--ref:#3ddc97}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
h1{font-size:16px;margin:0 12px 0 0}.legend span{display:inline-flex;align-items:center;gap:4px;margin-right:10px;font-size:12px}
.sw{width:12px;height:12px;border-radius:3px;display:inline-block}
main{display:grid;grid-template-columns:260px 1fr;gap:0}nav{position:sticky;top:52px;height:calc(100vh - 52px);overflow:auto;border-right:1px solid var(--line);padding:8px}
nav a{display:block;padding:6px 8px;border-radius:6px;color:inherit;text-decoration:none;font-size:12px}nav a:hover{background:var(--line)}
nav .meta{color:var(--muted)}section{padding:12px 20px 40px;max-width:1100px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:16px 0}
.card h2{font-size:14px;margin:0 0 6px}.stats{color:var(--muted);font-size:12px;margin-bottom:8px}
.item{display:flex;gap:8px;padding:1px 4px;border-radius:4px;border-left:4px solid transparent;white-space:pre-wrap;word-break:break-word}
.id{flex:0 0 72px;color:var(--muted);font:11px ui-monospace,monospace;padding-top:2px}.code .txt{font:12px ui-monospace,monospace}
.l-eval_awareness{background:var(--ea)}.l-grader{background:var(--grader)}.l-contradiction{background:var(--contradiction)}
.l-cheat{background:var(--cheat)}.l-cheat.decided{background:var(--cheat-d)}.l-cheat_code{background:var(--code)}
.multi{background-image:repeating-linear-gradient(135deg,transparent 0 6px,rgba(0,0,0,.08) 6px 12px)}
.ref{outline:2px dashed var(--ref);outline-offset:-2px}.refonly{border-left-color:var(--ref)}
.fold{color:var(--muted);font-size:12px;padding:2px 80px;cursor:pointer}.hidden{display:none}
details{margin:6px 0}summary{cursor:pointer;color:var(--muted);font-size:12px}pre.fb{white-space:pre-wrap;font:12px ui-monospace,monospace;color:var(--muted)}
label.tg{font-size:12px;color:var(--muted)}
@media (max-width:760px){main{grid-template-columns:1fr}nav{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line)}.id{flex-basis:56px}}
"""

JS = """
function setOnly(on){document.querySelectorAll('.card').forEach(c=>{
 const items=[...c.querySelectorAll('.item')];c.querySelectorAll('.fold').forEach(f=>f.remove());
 if(!on){items.forEach(i=>i.classList.remove('hidden'));return}
 const keep=new Set();items.forEach((it,i)=>{if(it.dataset.lab||it.classList.contains('ref')){for(let k=i-2;k<=i+2;k++)keep.add(k)}});
 let run=0;items.forEach((it,i)=>{const h=!keep.has(i);it.classList.toggle('hidden',h);
  if(h){run++}else if(run){const f=document.createElement('div');f.className='fold';f.textContent='⋯ '+run+' unlabelled';it.before(f);run=0}});
 if(run){const f=document.createElement('div');f.className='fold';f.textContent='⋯ '+run+' unlabelled';items[items.length-1].after(f)}})}
document.getElementById('only').addEventListener('change',e=>setOnly(e.target.checked));setOnly(true);
"""


def _attrs(span: dict) -> str:
    """Compact attribute string for a span's tooltip."""
    keys = ("framing", "strength", "names_benchmark", "status")
    return ", ".join(f"{k}={span[k]}" for k in keys if k in span)


def render(
    attempts: list[Attempt], spans_by_key: dict[str, dict], overlay: dict[str, list]
) -> str:
    """Build the HTML page.

    @param attempts: Attempts to show, in order.
    @param spans_by_key: attempt_key -> {"spans": [...], "summary": ...} (from load_judge_spans, merged).
    @param overlay: attempt_key -> reference spans ({ids, label, note}) drawn as outlines.
    @returns: HTML document text.
    """
    nav, cards = [], []
    for n, a in enumerate(attempts):
        segs, info = reasoning_segments(a)
        answer = segment_answer(a.answer, a.attempt)
        items = segs + answer
        order = {s.id: i for i, s in enumerate(items)}
        j = spans_by_key.get(a.key, {"spans": [], "summary": None})
        spans = merge_adjacent(
            [s for s in j["spans"] if all(i in order for i in s["ids"])], order
        )
        lab = defaultdict(list)
        for s in spans:
            for i in s["ids"]:
                lab[i].append(s)
        ref = defaultdict(list)
        for r in overlay.get(a.key, []):
            for i in r["ids"]:
                ref[i].append(r)
        counts = defaultdict(int)
        for s in spans:
            counts[s["label"] + ("/" + s["status"] if "status" in s else "")] += 1
        summary = j.get("summary")
        stat = (
            f"passed tests: <b>{a.passed}</b> · B1: {html.escape(json.dumps(summary)) if summary else '—'} · "
            + " · ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
        )
        if info.get("judge_cutoff"):
            stat += f" · loop cut at char {info['judge_cutoff']}"
        rows = []
        for s in items:
            ls = lab.get(s.id, [])
            rs = ref.get(s.id, [])
            cls = ["item"] + (["code"] if s.kind == "code_line" else [])
            if ls:
                cls.append(f"l-{ls[0]['label']}")
                if ls[0].get("status") == "decided":
                    cls.append("decided")
                if len({x["label"] for x in ls}) > 1:
                    cls.append("multi")
            if rs:
                cls.append("ref" if ls else "ref refonly")
            tip = " | ".join(
                f"{LABELS.get(x['label'], x['label'])} {_attrs(x)}" for x in ls
            )
            tip += "".join(f" | REF {x['label']}: {x.get('note', '')}" for x in rs)
            data = f' data-lab="{html.escape(ls[0]["label"])}"' if ls else ""
            rows.append(
                f'<div class="{" ".join(cls)}"{data} title="{html.escape(tip)}"><span class="id">{s.id}</span>'
                f'<span class="txt">{html.escape(s.text)}</span></div>'
            )
        anchor = f"a{n}"
        nav.append(
            f'<a href="#{anchor}">{html.escape(a.sample_id)} a{a.attempt} <span class="meta">{a.split}'
            f"{' ✔cheat' if a.passed else ''} · EA {counts.get('eval_awareness', 0)}</span></a>"
        )
        fb = (
            f"<details><summary>Feedback before this attempt</summary><pre class='fb'>{html.escape(a.feedback_before)}</pre></details>"
            if a.feedback_before
            else ""
        )
        cards.append(
            f'<div class="card" id="{anchor}"><h2>{html.escape(a.key)}</h2><div class="stats">{stat}</div>{fb}{"".join(rows)}</div>'
        )
    legend = (
        "".join(
            f'<span><i class="sw" style="background:var(--{v})"></i>{t}</span>'
            for v, t in [
                ("ea", "Eval awareness"),
                ("grader", "Grader"),
                ("contradiction", "Bad test"),
                ("cheat", "Cheat considered"),
                ("cheat-d", "Cheat decided"),
                ("code", "Cheat code"),
            ]
        )
        + '<span><i class="sw" style="outline:2px dashed var(--ref)"></i>Reference (recall)</span>'
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Judge Review</title><style>{CSS}</style></head><body>"
        f"<header><h1>Judge review</h1><div class='legend'>{legend}</div>"
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
