"""Run the agentic harness (Track B) on Impossible-LiveCodeBench.

    uv run python scripts/run_agentic.py --phase 30-agentic-smoke --n-tasks 1          # dry run
    uv run python scripts/run_agentic.py --phase 30-agentic-smoke --n-tasks 1 --run    # costs money
    uv run python scripts/run_agentic.py --phase 31-agentic-pilot --n-tasks 25 --run
    uv run python scripts/run_agentic.py --phase 32-agentic-models \
        --models deepinfra-raw/v4flash deepinfra-raw/v41flash deepinfra-raw/glm53flash \
        --task-set task_sets/balanced10.txt --run

One task per split, same problems in each. Logs go to logs/<phase>/<model-or-"multi">/<run-id>/
(a new folder per run: eval_set treats an existing folder as "resume").
"""

import argparse
from datetime import datetime
from pathlib import Path

from inspect_ai import eval_set

from earh.agentic.prompt import BUDGET_SYSTEM, DEFAULT_PROMPT, PROMPTS, user_message
from earh.agentic.task import agentic_lcb


def main() -> None:
    """Parse args, print the plan, and run the eval set if --run is given."""
    p = argparse.ArgumentParser()
    p.add_argument("--phase", required=True, help="e.g. 30-agentic-smoke")
    p.add_argument("--models", nargs="+", default=["deepinfra-raw/v4flash"])
    p.add_argument(
        "--task-set", default=None, help="file of problem IDs (overrides --n-tasks)"
    )
    p.add_argument("--splits", nargs="+", default=["oneoff", "conflicting"])
    p.add_argument("--n-tasks", type=int, default=25)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-turns", type=int, default=60)
    p.add_argument("--time-limit", type=int, default=3600, help="seconds per sample")
    p.add_argument(
        "--pressures",
        nargs="+",
        default=["none"],
        choices=["none", "mild", "strong"],
        help="pressure variants (one task per variant per split)",
    )
    p.add_argument(
        "--exits",
        nargs="+",
        default=["none"],
        choices=["none", "end_task", "give_up"],
        help="exit-tool variants (one task per variant per split)",
    )
    p.add_argument(
        "--tool-budget",
        type=int,
        default=None,
        help="visible tool-call budget with countdown (default: none)",
    )
    p.add_argument("--prompt-version", choices=sorted(PROMPTS), default=DEFAULT_PROMPT)
    p.add_argument("--max-connections", type=int, default=100)  # Track A shares 200
    p.add_argument("--max-sandboxes", type=int, default=100)
    p.add_argument(
        "--max-subprocesses", type=int, default=64
    )  # docker exec per tool call
    p.add_argument("--tag", default=None, help="run id (default: timestamp)")
    p.add_argument("--run", action="store_true", help="actually run (default: dry run)")
    args = p.parse_args()

    task_ids = None
    if args.task_set:
        lines = Path(args.task_set).read_text().splitlines()
        task_ids = [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    tasks = [
        agentic_lcb(
            split=split,
            n_tasks=args.n_tasks,
            seed=args.seed,
            max_turns=args.max_turns,
            time_limit=args.time_limit,
            task_ids=task_ids,
            prompt_version=args.prompt_version,
            exit=None if exit == "none" else exit,
            pressure=pressure,
            tool_budget=args.tool_budget,
        )
        for split in args.splits
        for exit in args.exits
        for pressure in args.pressures
    ]
    run_id = args.tag or datetime.now().strftime("%Y%m%d-%H%M")
    model_dir = args.models[0].split("/")[-1] if len(args.models) == 1 else "multi"
    log_dir = f"logs/{args.phase}/{model_dir}/{run_id}"

    print(f"models={args.models}  log_dir={log_dir}")
    print(f"task set: {args.task_set or f'{args.n_tasks} seeded (seed {args.seed})'}")
    print(
        f"max_turns={args.max_turns}  time_limit={args.time_limit}s  "
        f"tool_budget={args.tool_budget}"
    )
    for t in tasks:
        print(f"  {t.name:22s} {len(t.dataset)} samples per model")
    print(f"total samples: {sum(len(t.dataset) for t in tasks) * len(args.models)}")
    system_prompt = PROMPTS[args.prompt_version][0]
    if args.tool_budget is not None:
        system_prompt += "\n\n" + BUDGET_SYSTEM.format(n=args.tool_budget)
    user_instruction = "\n  ".join(
        f"[{pr}] {user_message(args.prompt_version, pr)}" for pr in args.pressures
    )
    indent = "\n  "
    print(
        f"\nprompt {args.prompt_version}, system prompt:{indent}{system_prompt.replace(chr(10), indent)}"
    )
    print(f"user instruction:{indent}{user_instruction.replace(chr(10), indent)}")
    if not args.run:
        print("\n(dry run; pass --run to execute)")
        return

    eval_set(
        tasks,
        model=args.models,
        log_dir=log_dir,
        max_tasks=len(tasks) * len(args.models),
        max_samples=max(len(t.dataset) for t in tasks),
        max_connections=args.max_connections,
        max_sandboxes=args.max_sandboxes,
        max_subprocesses=args.max_subprocesses,
        fail_on_error=False,
    )


if __name__ == "__main__":
    main()
