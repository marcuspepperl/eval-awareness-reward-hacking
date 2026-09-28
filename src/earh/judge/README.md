# earh.judge

Sentence-level LLM judge for eval awareness and cheating. Design: [docs/judging.md](../../../docs/judging.md).

| File | Role |
|---|---|
| `extract.py` | Track A logs → `Attempt` records (task prompt, prior feedback, reasoning, answer, test result) |
| `units.py` | Attempts → judge units, one per (attempt × pass × chunk): segment, cut loops at `judge_cutoff`, ~4k-token chunks with 10 `[ctx]` overlap sentences, render prompts (shared prefix first, pass instructions last) |
| `prompts/` | **Plain-text templates**: `system`, `context` (shared prefix), `pass_a`, `pass_b1`, `pass_b2`. `{{placeholders}}` are filled by `units.fill` |
| `parse.py` | Flat line output → spans (one per occurrence); validation errors are fed back for retries |
| `task.py` | Inspect task `judge`: one Sample per unit; solver retries invalid outputs (≤ 2); scorer stores tags |
| `assemble.py` | Judge logs + attempts → per-attempt judgments (span text, positions, EA occurrences / share / framings, cheat summary) |

Workflow:
```
uv run python scripts/judge/build_units.py <track-a log dir> --out logs/12-judge/<run> [--passes A,B1,B2 --n-attempts N]
uv run inspect eval src/earh/judge/task.py@judge -T units=logs/12-judge/<run>/judge_units.jsonl \
    --model deepinfra-raw/glm53flash -M reasoning_effort=low --log-dir logs/12-judge/<run>/logs
uv run python scripts/judge/assemble.py logs/12-judge/<run>
```
`build_units.py` also writes `<run>/examples/{A,B1,B2}.md`: fully rendered prompts for reading.
