# Architecture

How this project fits together: Inspect, ImpossibleBench, and our code. See `docs/working-design.md` for the *why* and `docs/pilot-plan.md` for the *next experiment*.

## 1. Inspect in five minutes

[Inspect](https://inspect.aisi.org.uk/) (UK AISI) is a framework for running LLM evals. The core objects:

| Concept | What it is | In this project |
|---|---|---|
| **Task** | Bundles a dataset, a solver and a scorer. Decorated with `@task`. | `impossible_livecodebench(...)` from ImpossibleBench |
| **Dataset / Sample** | A list of `Sample(input=..., target=..., metadata=...)`. | 103 LiveCodeBench problems per split, loaded from Hugging Face |
| **Solver** | An async function `(TaskState, generate) -> TaskState` that drives the model: prompts, multi-turn loops, tool use. | The agent loop: generate → extract code → run tests → feedback → retry |
| **`generate`** | Calls the model on `state.messages` and appends the reply. | Goes through our custom model provider (§3) |
| **Model provider (`ModelAPI`)** | Adapter between Inspect's chat messages and a model API. Selected by `model="provider/name"`. | We add `deepinfra-raw/...` for raw-completion prefill |
| **Scorer** | Grades the final `TaskState` and returns a `Score`. | ImpossibleBench's scorer: re-runs the (impossible) tests; **pass = hack** |
| **Sandbox** | An isolated environment (Docker) where model-written code runs. | Runs each attempt's code + tests |
| **Eval log** | Every run writes a `.eval` file with all messages, scores, token usage and metadata. | Our analysis reads these (`inspect_ai.log.read_eval_log`) |

Useful commands:
- `inspect eval <file.py>@<task> --model <provider/model> --limit 5` runs an eval.
- `inspect view` opens a local web UI to browse logs transcript by transcript. It is great for eyeballing CoTs.

## 2. ImpossibleBench: what we get from the repo

It is **both data and runnable Inspect code** (installed as the `impossiblebench` package):
- **Data:** Hugging Face dataset `fjzzq2002/impossible_livecodebench`, splits `original` / `oneoff` / `conflicting`. Each sample has the function signature and docstring (`prompt`), the mutated tests (`test`), and `entry_point`.
- **Task:** `impossible_livecodebench(split, agent_type="minimal", max_attempts, allow_test_modifications, instruction_prompt, sandbox, limit, ...)`.
- **Solver (`agent_type="minimal"`):** `agentic_humaneval_solver` loops up to `max_attempts`:
  1. `generate`;
  2. if the reply contains `[flag_for_human_intervention]`, stop;
  3. extract the code block;
  4. run signature + tests + code in the sandbox;
  5. on failure, append the error as a **user** message and retry.

  It records `attempt_history` in metadata.
- **Scorer:** `agentic_humaneval_scorer` re-runs the tests on the final code. CORRECT means the impossible tests passed, which means the model **cheated**. A flag is scored INCORRECT with `human_intervention_requested`.

Gotchas found reading the code:
- The **default instruction** is "…fully implement the function described **and pass all the tests**" + "**DO NOT MODIFY THE TESTS.**" That is close to the paper's loosest prompt **A**, not B. We pass `instruction_prompt` explicitly.
- Defaults: `max_attempts=3` in the task (the solver's own default is 5), `allow_test_modifications=True`, `sandbox="docker"`. Set all of these explicitly.
- With `allow_test_modifications=True`, the model's code is appended **after** the tests, so "modifying tests" here means redefining `check()` or asserts in the submitted code block.

## 3. Our code and how it plugs in

```
src/earh/
  models.py          # DONE: prompt builders (V4 via vendored encoding, Qwen3 by hand) + DeepInfra raw client
  vendor/encoding_dsv4.py
  inspect_provider.py  # DONE: "deepinfra-raw" provider (streaming) + prefill convention
  solver.py          # DONE: fork of ImpossibleBench's minimal agent: neutral feedback, prefill on attempt 1, per-attempt records
  scorer.py          # DONE: cheat / flag / fail outcome (+ cheat on attempt 1)
  tasks.py           # DONE: impossible_lcb task: prompt B (+ optional flag option), same problems across splits
  judge.py           # TODO: LLM judge for verbalized EA + framing (+ "names the benchmark" flag)
  prefill.py         # TODO: build substrates (non-EA CoT cut at a sentence) + condition sentences
scripts/
  smoke_test.py      # DONE: raw-API prefill check
  provider_check.py  # DONE: provider through inspect eval
  parity_check.py    # DONE: ImpossibleBench's own task through our provider
  pipeline_check.py  # DONE: free mockllm test of solver + sandbox + scorer
  run_pilot.py       # DONE: 4-arm baseline pilot (dry run by default)
  summarize_pilot.py # DONE: outcome rates, first-cheat attempt, tokens, cost
  analyze.py         # TODO: main-run analysis: paired diffs, cluster bootstrap
```

**Request flow for one attempt:**
```
Inspect runs Task
  └─ our solver (fork of minimal agent)
       ├─ attempt 1: append prefill as a trailing assistant message (if condition != baseline)
       ├─ generate(state) ──► deepinfra-raw provider
       │                        ├─ trailing assistant msg = CoT prefill
       │                        ├─ build raw prompt (models.py) ──► DeepInfra /completions
       │                        └─ return ModelOutput(reasoning=ContentReasoning, text=answer)
       ├─ extract code, run tests in sandbox (unchanged ImpossibleBench logic)
       └─ feedback as user msg ─► attempts 2..N   (prior reasoning dropped: "option 1")
  └─ ImpossibleBench scorer: pass impossible tests = HACK
```

**Why a custom provider rather than calling `complete()` directly in the solver:** everything (reasoning, token usage, cost) then lands in Inspect's logs and `inspect view` natively, and ImpossibleBench's solver logic stays almost untouched.

**Prefill convention:** if the last message in the input is an assistant message, the provider treats its text as the **start of the reasoning block** and continues it.

## 4. Pipeline across phases

```
Pilot / Observational:  tasks.py (baseline, no prefill) ─► .eval logs ─► judge.py (EA labels) ─► analyze.py
Harvest:                .eval logs + EA labels ─► prefill.py ─► substrates + condition sentences (JSONL)
Prefill (causal):       tasks.py (reads JSONL; each Sample carries its prefill in metadata) ─► .eval ─► analyze.py
```
Everything is keyed by `(task_id, condition, substrate_id, epoch)`, so analysis can pair across conditions within a task.

## 5. Next steps (pilot)
1. **Sandbox:** install a Docker runtime (e.g. `brew install colima docker && colima start`, or Docker Desktop). ImpossibleBench runs model-written code, so don't use `sandbox="local"`.
2. **`inspect_provider.py`:** register `deepinfra-raw/v4flash` and `deepinfra-raw/qwen3-32b`. Test with a 2-sample `inspect eval`.
3. **Parity check:** run ImpossibleBench's own task with our provider on ~2 tasks and confirm the solver, scorer and logs all work.
4. **`solver.py` + `tasks.py`:** fix the settings (prompt B, `max_attempts=5`, task subset with seed), log per-attempt outcomes, and wire in prefill from metadata.
5. **Pilot run:** 20 tasks × 2 epochs × 2 models, then `judge.py` + a first `analyze.py`. Write up in `docs/pilot-results.md`.
