"""Build judge units for Track B (agentic) episodes.

    uv run python scripts/judge/build_units_agentic.py <track-b .eval file or dir> \
        --ids lcbhard_58,lcbhard_44 --passes A,B1,B2 --out logs/12-judge/trackb-smoke/v1

Writes <out>/judge_units.jsonl (for `inspect eval src/earh/judge/task.py@judge -T units=...`),
<out>/episodes.jsonl, and <out>/examples/{A,B1A,B2}.md (one fully rendered prompt per pass).
"""

import argparse
import json
from pathlib import Path

from earh.judge.extract_agentic import extract_episodes
from earh.judge.units_agentic import build_units_agentic


def main() -> None:
    """Extract episodes, build units, write files."""
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument(
        "--ids", default=None, help="comma list of sample ids (default: all)"
    )
    ap.add_argument("--passes", default="A,B1,B2")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    eps = extract_episodes(args.log)
    if args.ids:
        want = args.ids.split(",")
        eps = sorted(
            (e for e in eps if e.sample_id in want),
            key=lambda e: want.index(e.sample_id),
        )
    units = build_units_agentic(eps, args.passes.split(","))
    out = Path(args.out)
    (out / "examples").mkdir(parents=True, exist_ok=True)
    with open(out / "judge_units.jsonl", "w") as f:
        for u in units:
            f.write(json.dumps(u.to_dict()) + "\n")
    with open(out / "episodes.jsonl", "w") as f:
        for e in eps:
            f.write(json.dumps(e.to_dict()) + "\n")
    for ps in ("A", "B1A", "B2"):
        u = next((u for u in units if u.pass_ == ps), None)
        if u:
            (out / "examples" / f"{ps}.md").write_text(
                f"# system\n{u.system}\n\n# user\n{u.user}\n"
            )
    chars = sum(len(u.user) for u in units)
    by = {ps: sum(u.pass_ == ps for u in units) for ps in ("A", "B1A", "B2")}
    print(
        f"{len(eps)} episodes -> {len(units)} units {by}; ~{chars / 4 / 1e6:.2f}M input tokens (chars/4)"
    )


if __name__ == "__main__":
    main()
