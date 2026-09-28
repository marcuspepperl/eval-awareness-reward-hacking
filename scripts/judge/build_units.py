"""Build judge units (prompts) from Track A logs. No API calls.

    uv run python scripts/judge/build_units.py logs/03-pilot/v4flash/promptB-5att \
        --passes A,B1,B2 --n-attempts 12 --seed 0 --out logs/12-judge/pilot-smoke

Writes <out>/judge_units.jsonl, <out>/attempts.jsonl (the source attempts), and
<out>/examples/*.md (a few rendered prompts, for reading).
"""

import argparse
import json
import random
from pathlib import Path

from earh.judge.extract import extract_attempts
from earh.judge.units import build_units


def main() -> None:
    """Parse args, extract attempts, build units, and write the outputs."""
    p = argparse.ArgumentParser()
    p.add_argument("log_dir")
    p.add_argument("--out", required=True)
    p.add_argument("--passes", default="A,B1,B2")
    p.add_argument(
        "--n-attempts", type=int, default=None, help="random subset of attempts"
    )
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--task-filter", default=None, help="substring of the task name, e.g. noflag"
    )
    p.add_argument(
        "--keys",
        default=None,
        help="file with one attempt key per line (overrides sampling)",
    )
    args = p.parse_args()

    attempts = extract_attempts(args.log_dir)
    if args.task_filter:
        attempts = [a for a in attempts if args.task_filter in a.task]
    if args.keys:
        wanted = [k.strip() for k in open(args.keys) if k.strip()]
        by_key = {a.key: a for a in attempts}
        attempts = [by_key[k] for k in wanted]
    elif args.n_attempts and args.n_attempts < len(attempts):
        attempts = random.Random(args.seed).sample(attempts, args.n_attempts)
    units = build_units(attempts, args.passes.split(","))

    out = Path(args.out)
    (out / "examples").mkdir(parents=True, exist_ok=True)
    with (out / "attempts.jsonl").open("w") as f:
        for a in attempts:
            f.write(json.dumps(a.to_dict()) + "\n")
    with (out / "judge_units.jsonl").open("w") as f:
        for u in units:
            f.write(json.dumps(u.to_dict()) + "\n")
    for pass_ in ("A", "B1", "B2"):
        ex = next(
            (u for u in units if u.pass_ == pass_ and u.n_chunks > 1 and u.chunk == 2),
            None,
        ) or next((u for u in units if u.pass_ == pass_), None)
        if ex:
            (out / "examples" / f"{pass_}.md").write_text(
                f"<!-- {ex.id} -->\n# SYSTEM\n{ex.system}\n\n# USER\n{ex.user}\n"
            )

    chars = sum(len(u.system) + len(u.user) for u in units)
    by_pass = {ps: sum(u.pass_ == ps for u in units) for ps in ("A", "B1", "B2")}
    print(
        f"{len(attempts)} attempts -> {len(units)} units {by_pass}; ~{chars / 4 / 1e6:.2f}M input tokens (chars/4)"
    )
    print(f"wrote {out}/judge_units.jsonl, attempts.jsonl, examples/")


if __name__ == "__main__":
    main()
