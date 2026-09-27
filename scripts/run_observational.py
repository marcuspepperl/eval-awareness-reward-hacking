"""Phase 1 (Track A): observational baseline, no prefill, all problems × both splits × repeats.

    uv run python scripts/run_observational.py                 # dry run: prints the plan
    uv run python scripts/run_observational.py --run           # run (~$5-7)

Per task (problem × split) this yields a cheat tendency, the per-attempt cheat curve,
and CoTs for the eval-awareness judge. Logs: logs/10-observational/<model>/<run-id>/.
"""

import argparse
from datetime import datetime

from inspect_ai import eval_set

from earh.tasks import build_instruction, impossible_lcb

SPLITS = ["oneoff", "conflicting"]


def main() -> None:
    """Parse args, print the plan, and run the eval set if --run is given."""
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="deepinfra-raw/v4flash")
    p.add_argument(
        "--n-tasks", type=int, default=None, help="problems (default: all 103)"
    )
    p.add_argument("--epochs", type=int, default=2, help="repeats per task")
    p.add_argument("--max-attempts", type=int, default=8)
    p.add_argument("--max-connections", type=int, default=120)  # DeepInfra: 200/model
    p.add_argument("--max-sandboxes", type=int, default=150)
    p.add_argument("--max-subprocesses", type=int, default=64)
    p.add_argument("--tag", default=None, help="run id (default: timestamp)")
    p.add_argument("--run", action="store_true", help="actually run (default: dry run)")
    args = p.parse_args()

    tasks = [
        impossible_lcb(
            split=split,
            n_tasks=args.n_tasks,
            flag=False,
            feedback="neutral",
            max_attempts=args.max_attempts,
        )
        for split in SPLITS
    ]
    run_id = args.tag or datetime.now().strftime("%Y%m%d-%H%M")
    log_dir = f"logs/10-observational/{args.model.split('/')[-1]}/{run_id}"
    per_task = args.max_connections // len(tasks)

    print(f"model={args.model}  log_dir={log_dir}")
    print(
        f"epochs={args.epochs}  max_attempts={args.max_attempts}  concurrency≈{per_task * len(tasks)}"
    )
    for t in tasks:
        print(
            f"  {t.name:24s} {len(t.dataset)} problems × {args.epochs} = {len(t.dataset) * args.epochs} samples"
        )
    print(f"total samples: {sum(len(t.dataset) for t in tasks) * args.epochs}")
    print("\ninstruction:\n  " + build_instruction(False).replace("\n", "\n  "))
    if not args.run:
        print("\n(dry run; pass --run to execute)")
        return

    eval_set(
        tasks,
        model=args.model,
        log_dir=log_dir,
        epochs=args.epochs,
        max_tasks=len(tasks),
        max_samples=per_task,
        max_connections=args.max_connections,
        max_sandboxes=args.max_sandboxes,
        max_subprocesses=args.max_subprocesses,
        fail_on_error=False,
    )


if __name__ == "__main__":
    main()
