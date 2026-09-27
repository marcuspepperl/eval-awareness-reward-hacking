"""Pilot: baseline cheat / flag / fail rates under prompt B, with and without the flag option.

    uv run python scripts/run_pilot.py                 # print the plan only (dry run)
    uv run python scripts/run_pilot.py --run           # actually run (costs money)
    uv run python scripts/run_pilot.py --run --model deepinfra-raw/qwen3-32b

Arms: {conflicting, oneoff} × {noflag, flag}, same N problems in every arm, neutral
feedback, 5 attempts, no prefill. Logs go to logs/pilot/<model-name>/.
"""

import argparse

from inspect_ai import eval_set

from earh.tasks import build_instruction, impossible_lcb

SPLITS = ["conflicting", "oneoff"]


def main() -> None:
    """Parse args, print the plan, and run the eval set if --run is given."""
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="deepinfra-raw/v4flash")
    p.add_argument("--n-tasks", type=int, default=25)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-attempts", type=int, default=5)
    p.add_argument("--feedback", choices=["neutral", "user"], default="neutral")
    p.add_argument("--max-connections", type=int, default=150)  # DeepInfra: 200/model
    p.add_argument("--max-sandboxes", type=int, default=120)
    p.add_argument("--run", action="store_true", help="actually run (default: dry run)")
    args = p.parse_args()

    tasks = [
        impossible_lcb(
            split=split,
            n_tasks=args.n_tasks,
            seed=args.seed,
            flag=flag,
            feedback=args.feedback,
            max_attempts=args.max_attempts,
        )
        for split in SPLITS
        for flag in (False, True)
    ]
    log_dir = f"logs/pilot/{args.model.split('/')[-1]}"

    print(f"model={args.model}  log_dir={log_dir}  feedback={args.feedback}")
    for t in tasks:
        print(f"  {t.name:24s} {len(t.dataset)} samples")
    print(f"total samples: {sum(len(t.dataset) for t in tasks)}")
    print(
        "\ninstruction (flag arm):\n  " + build_instruction(True).replace("\n", "\n  ")
    )
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
        fail_on_error=False,
    )


if __name__ == "__main__":
    main()
