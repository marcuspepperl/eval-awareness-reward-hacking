"""Run the agentic harness (Track B) on Impossible-LiveCodeBench.

    uv run python scripts/run_agentic.py --phase 30-agentic-smoke --n-tasks 1          # dry run
    uv run python scripts/run_agentic.py --phase 30-agentic-smoke --n-tasks 1 --run    # costs money
    uv run python scripts/run_agentic.py --phase 31-agentic-pilot --n-tasks 25 --run

One task per split, same N problems in each. Logs go to logs/<phase>/<model>/<run-id>/
(a new folder per run: eval_set treats an existing folder as "resume").
"""

import argparse
from datetime import datetime

from inspect_ai import eval_set

from earh.agentic.prompt import SYSTEM_PROMPT, USER_INSTRUCTION
from earh.agentic.task import agentic_lcb


def main() -> None:
    """Parse args, print the plan, and run the eval set if --run is given."""
    p = argparse.ArgumentParser()
    p.add_argument("--phase", required=True, help="e.g. 30-agentic-smoke")
    p.add_argument("--model", default="deepinfra-raw/v4flash")
    p.add_argument("--splits", nargs="+", default=["oneoff", "conflicting"])
    p.add_argument("--n-tasks", type=int, default=25)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-turns", type=int, default=30)
    p.add_argument("--time-limit", type=int, default=1800, help="seconds per sample")
    p.add_argument("--max-connections", type=int, default=100)  # Track A shares 200
    p.add_argument("--max-sandboxes", type=int, default=100)
    p.add_argument(
        "--max-subprocesses", type=int, default=64
    )  # docker exec per tool call
    p.add_argument("--tag", default=None, help="run id (default: timestamp)")
    p.add_argument("--run", action="store_true", help="actually run (default: dry run)")
    args = p.parse_args()

    tasks = [
        agentic_lcb(
            split=split,
            n_tasks=args.n_tasks,
            seed=args.seed,
            max_turns=args.max_turns,
            time_limit=args.time_limit,
        )
        for split in args.splits
    ]
    run_id = args.tag or datetime.now().strftime("%Y%m%d-%H%M")
    log_dir = f"logs/{args.phase}/{args.model.split('/')[-1]}/{run_id}"

    print(f"model={args.model}  log_dir={log_dir}")
    print(f"max_turns={args.max_turns}  time_limit={args.time_limit}s")
    for t in tasks:
        print(f"  {t.name:22s} {len(t.dataset)} samples")
    print(f"\nsystem prompt:\n  {SYSTEM_PROMPT.replace(chr(10), chr(10) + '  ')}")
    print(f"\nuser instruction:\n  {USER_INSTRUCTION.replace(chr(10), chr(10) + '  ')}")
    if not args.run:
        print("\n(dry run; pass --run to execute)")
        return

    eval_set(
        tasks,
        model=args.model,
        log_dir=log_dir,
        max_tasks=len(tasks),
        max_samples=args.n_tasks,
        max_connections=args.max_connections,
        max_sandboxes=args.max_sandboxes,
        max_subprocesses=args.max_subprocesses,
        fail_on_error=False,
    )


if __name__ == "__main__":
    main()
