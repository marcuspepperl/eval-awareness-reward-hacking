"""Convert judge outputs (or reference annotations) into label records for a label set.

    uv run python scripts/judge/export_judge_labels.py --set pilot10 --name judge-v6 \
        --judge logs/12-judge/pilot10/v6/logs:A,B1 logs/12-judge/pilot10/v7-b2/logs
    uv run python scripts/judge/export_judge_labels.py --set pilot10 --name subagents-v3 \
        --overlay logs/12-judge/pilot10/recall/review.json

Writes logs/12-judge/labels/<set>/<name>/*.json in the labelling UI's format (one record per
work item, per-attempt spans + B1), so earh.judge.agreement can compare any two sources.
Judge spans are merged across chunk boundaries and first-only labels keep the earliest.
`--overlay` takes {attempt_key: [{ids, label, note}]} (e.g. the recall reviewers' spans).
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from earh.judge.assemble import keep_first, load_judge_spans, merge_adjacent

SETS = Path("logs/12-judge/labelsets")
LABELS = Path("logs/12-judge/labels")
ATTRS = ("framing", "strength", "benchmark")


def _judge_spans(specs: list[str]) -> dict[str, dict]:
    """attempt_key -> {spans, summary} from judge log dirs (`dir` or `dir:A,B2`)."""
    merged: dict[str, dict] = defaultdict(lambda: {"spans": [], "summary": None})
    for spec in specs:
        d, _, ps = spec.partition(":")
        for k, v in load_judge_spans(d, set(ps.split(",")) if ps else None).items():
            merged[k]["spans"] += v["spans"]
            merged[k]["summary"] = merged[k]["summary"] or v["summary"]
    return merged


def main() -> None:
    """Build one label record per work item and write them under labels/<set>/<name>/."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--judge", nargs="*", default=[])
    ap.add_argument("--overlay", default=None)
    args = ap.parse_args()
    data = json.loads((SETS / args.set / "data.json").read_text())
    judged = _judge_spans(args.judge) if args.judge else {}
    overlay = json.loads(Path(args.overlay).read_text()) if args.overlay else {}
    out = LABELS / args.set / args.name
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for it in data["items"]:
        attempts = {}
        for att in it["attempts"]:
            order = {s["id"]: i for i, s in enumerate(att["reasoning"])}
            j = judged.get(att["key"], {"spans": [], "summary": None})
            raw = [s for s in j["spans"] if all(i in order for i in s["ids"])]
            spans = [
                {"label": s["label"], "start": s["ids"][0], "end": s["ids"][-1]}
                | {k: s[k] for k in ATTRS if k in s}
                for s in keep_first(merge_adjacent(raw, order), order)
            ]
            spans += [
                {
                    "label": o["label"],
                    "start": o["ids"][0],
                    "end": o["ids"][-1],
                    "note": o.get("note", ""),
                }
                for o in overlay.get(att["key"], [])
                if o["ids"][0] in order and o["ids"][-1] in order
            ]
            spans.sort(key=lambda s: order[s["start"]])
            b1 = j["summary"] or {}
            attempts[att["key"]] = {
                "spans": spans,
                "b1": {
                    "attempted": b1.get("attempted"),
                    "type": b1.get("type"),
                    "transparent": b1.get("transparent"),
                },
                "note": "",
            }
            n += len(spans)
        rec = {
            "rollout": it["rollout"],
            "set": args.set,
            "labeler": args.name,
            "status": "done",
            "attempts": attempts,
        }
        (out / (it["rollout"].replace(":", "__") + ".json")).write_text(
            json.dumps(rec, indent=1)
        )
    print(f"wrote {out}: {len(data['items'])} items, {n} spans")


if __name__ == "__main__":
    main()
