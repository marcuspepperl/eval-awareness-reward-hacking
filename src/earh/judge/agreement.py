"""Agreement between two label sources (human, reviewer agent, or judge) on one label set.

Every source is stored in the labelling format: logs/12-judge/labels/<set>/<source>/*.json,
one record per work item with per-attempt `spans` and `b1`. Judge runs are converted into
that format by scripts/judge/export_judge_labels.py, so all comparisons are like for like.

Matching rules (the same numbers feed the review page and the report):
- Occurrence labels (`eval_awareness`, `grader`): a span **agrees** if it overlaps any span
  of the same label in the other source (by at least one sentence). Precision of B against
  reference A = agreeing B spans / B spans; recall = agreeing A spans / A spans.
- First-occurrence labels (`bad_test`, `cheat_considered`): per attempt, presence (both /
  A only / B only / neither) and the signed distance in sentences between the two starts.
  "Close" means both present and |distance| <= CLOSE.
- B1: agreement on `attempted`, and on `type` / `transparent` where both say attempted.
- `interesting` is a personal bookmark and is never compared.
"""

from __future__ import annotations

import json
from pathlib import Path

SPAN_LABELS = ("eval_awareness", "grader")
FIRST_LABELS = ("bad_test", "cheat_considered")
CLOSE = 5


def load_source(labels_dir: Path) -> dict[str, dict]:
    """Per-attempt labels from one source: attempt_key -> {spans, b1, status}."""
    out: dict[str, dict] = {}
    for f in sorted(labels_dir.glob("*.json")):
        rec = json.loads(f.read_text())
        for key, ar in rec.get("attempts", {}).items():
            out[key] = {
                "spans": [
                    s for s in ar.get("spans", []) if s["label"] != "interesting"
                ],
                "b1": ar.get("b1") or {},
                "status": rec.get("status", "done"),
            }
    return out


def _covers(spans: list[dict], order: dict[str, int]) -> list[tuple[int, int, dict]]:
    """(first index, last index, span) for spans whose endpoints are known sentence IDs."""
    return [
        (order[s["start"]], order[s["end"]], s)
        for s in spans
        if s["start"] in order and s["end"] in order
    ]


def _overlaps(x: tuple[int, int, dict], ys: list[tuple[int, int, dict]]) -> list:
    """Spans in ys that share at least one sentence with x."""
    return [y for y in ys if y[0] <= x[1] and y[1] >= x[0]]


def compare_attempt(order: dict[str, int], a: dict | None, b: dict | None) -> dict:
    """Compare two sources on one attempt.

    @param order: sentence ID -> position in the attempt's reasoning.
    @param a: reference source's {spans, b1} for this attempt (None if it has no record).
    @param b: candidate source's {spans, b1} (None if absent).
    @returns: {spans: [span + src + status], first: {label: {a, b, dist}}, b1: {a, b, agree},
        n_disagree}. Status is "agree", "a_only", or "b_only".
    """
    a = a or {"spans": [], "b1": {}}
    b = b or {"spans": [], "b1": {}}
    spans, n_dis = [], 0
    for label in SPAN_LABELS:
        sa = _covers([s for s in a["spans"] if s["label"] == label], order)
        sb = _covers([s for s in b["spans"] if s["label"] == label], order)
        for src, mine, other in (("a", sa, sb), ("b", sb, sa)):
            for x in mine:
                hit = _overlaps(x, other)
                status = "agree" if hit else f"{src}_only"
                n_dis += status != "agree"
                rec = {**x[2], "src": src, "status": status}
                if label == "eval_awareness" and hit:
                    best = max(hit, key=lambda y: min(x[1], y[1]) - max(x[0], y[0]))
                    rec["framing_match"] = best[2].get("framing") == x[2].get("framing")
                spans.append(rec)
    first = {}
    for label in FIRST_LABELS:
        fa = min(
            _covers([s for s in a["spans"] if s["label"] == label], order),
            default=None,
            key=lambda t: t[0],
        )
        fb = min(
            _covers([s for s in b["spans"] if s["label"] == label], order),
            default=None,
            key=lambda t: t[0],
        )
        dist = fb[0] - fa[0] if fa and fb else None
        first[label] = {
            "a": fa[2]["start"] if fa else None,
            "b": fb[2]["start"] if fb else None,
            "dist": dist,
        }
        n_dis += (fa is None) != (fb is None) or (
            dist is not None and abs(dist) > CLOSE
        )
        for t, src in ((fa, "a"), (fb, "b")):
            if t:
                spans.append({**t[2], "src": src, "status": "first"})
    ba, bb = a["b1"], b["b1"]
    agree = {}
    if ba.get("attempted") is not None and bb.get("attempted") is not None:
        agree["attempted"] = ba["attempted"] == bb["attempted"]
        if ba["attempted"] and bb["attempted"]:
            agree["type"] = ba.get("type") == bb.get("type")
            agree["transparent"] = ba.get("transparent") == bb.get("transparent")
    n_dis += sum(not v for v in agree.values())
    return {
        "spans": spans,
        "first": first,
        "b1": {"a": ba, "b": bb, "agree": agree},
        "n_disagree": n_dis,
    }


def _prf(n_a: int, n_b: int, agree_a: int, agree_b: int) -> dict:
    """Precision / recall / F1 of B against reference A from agreement counts."""
    p = agree_b / n_b if n_b else None
    r = agree_a / n_a if n_a else None
    f = 2 * p * r / (p + r) if p and r else None
    return {"n_a": n_a, "n_b": n_b, "precision": p, "recall": r, "f1": f}


def compare_sources(set_data: dict, a: dict[str, dict], b: dict[str, dict]) -> dict:
    """Compare two sources over every attempt that both have labelled.

    @param set_data: The label set (data.json): items with attempts and numbered reasoning.
    @param a: Reference source (load_source output).
    @param b: Candidate source.
    @returns: {attempts: {key: compare_attempt(...) + in_a/in_b/status}, metrics: {...}}.
    """
    attempts, metrics = {}, {}
    both = []
    for it in set_data["items"]:
        for att in it["attempts"]:
            key = att["key"]
            order = {s["id"]: i for i, s in enumerate(att["reasoning"])}
            res = compare_attempt(order, a.get(key), b.get(key))
            res.update(
                in_a=key in a, in_b=key in b, status_a=a.get(key, {}).get("status")
            )
            attempts[key] = res
            if key in a and key in b:
                both.append(res)
    for label in SPAN_LABELS:
        sp = [s for r in both for s in r["spans"] if s["label"] == label]
        na = sum(s["src"] == "a" for s in sp)
        nb = sum(s["src"] == "b" for s in sp)
        aa = sum(s["src"] == "a" and s["status"] == "agree" for s in sp)
        ab = sum(s["src"] == "b" and s["status"] == "agree" for s in sp)
        metrics[label] = _prf(na, nb, aa, ab)
    ea_a = [
        any(s["label"] == "eval_awareness" and s["src"] == "a" for s in r["spans"])
        for r in both
    ]
    ea_b = [
        any(s["label"] == "eval_awareness" and s["src"] == "b" for s in r["spans"])
        for r in both
    ]
    metrics["eval_awareness"]["attempt_presence_agreement"] = (
        sum(x == y for x, y in zip(ea_a, ea_b, strict=True)) / len(both)
        if both
        else None
    )
    fm = [
        s["framing_match"]
        for r in both
        for s in r["spans"]
        if s.get("framing_match") is not None and s["src"] == "a"
    ]
    metrics["eval_awareness"]["framing_agreement"] = sum(fm) / len(fm) if fm else None
    for label in FIRST_LABELS:
        fs = [r["first"][label] for r in both]
        pres = sum((f["a"] is None) == (f["b"] is None) for f in fs)
        d = [abs(f["dist"]) for f in fs if f["dist"] is not None]
        metrics[label] = {
            "presence_agreement": pres / len(fs) if fs else None,
            "both": len(d),
            "a_only": sum(f["a"] is not None and f["b"] is None for f in fs),
            "b_only": sum(f["a"] is None and f["b"] is not None for f in fs),
            "close": sum(x <= CLOSE for x in d) / len(d) if d else None,
            "median_abs_dist": sorted(d)[len(d) // 2] if d else None,
        }
    for field in ("attempted", "type", "transparent"):
        v = [r["b1"]["agree"][field] for r in both if field in r["b1"]["agree"]]
        metrics[f"b1_{field}"] = {
            "n": len(v),
            "agreement": sum(v) / len(v) if v else None,
        }
    # Which categories each source labelled at all (a source that never used a label, e.g.
    # reviewers asked only for EA / grader, should read "not labelled", not 0% agreement).
    for src, d in (("a", a), ("b", b)):
        used = {s["label"] for v in d.values() for s in v["spans"]}
        if any(v["b1"].get("attempted") is not None for v in d.values()):
            used.add("b1")
        metrics[f"labelled_by_{src}"] = sorted(used)
    metrics["n_attempts"] = len(both)
    return {"attempts": attempts, "metrics": metrics}
