# Agent instructions

Project: does eval awareness (and its framing) change reward hacking? See `ARCH.md` for how the code fits together and `docs/` for design and plans.

## Environment
- Python via `uv`. Run everything with `uv run ...`. Add dependencies with `uv add <pkg>` (dev tools: `uv add --dev`).
- Secrets live in `.env` (gitignored). Never print, log, or commit the API key.
- Docker runtime is colima (`colima start` if `docker info` fails). ImpossibleBench runs model-written code, so never use `sandbox="local"`.

## Code style
- **After each batch of Python changes, run ruff** (it mirrors the editor's fix-all + format-on-save):
  ```
  uv run ruff check --fix . && uv run ruff format .
  ```
  Config is in `pyproject.toml` (`[tool.ruff]`). Fix remaining lint errors rather than silencing them, unless there's a clear reason (then say why in the config or a `# noqa` comment).
- **Docstrings** (every module, class and function outside `vendor/`):
  - **Internal or trivial** (private helpers, thin wrappers, obvious one-liners): a one-line docstring saying what it does, e.g. `"""Strip trailing spaces that make V4 close </think> early."""`.
  - **Public or non-trivial** (used across modules, meaningful branching/logic, or semantically important to the experiment): a short description, then one `@param name: ...` line per parameter and an `@returns: ...` line. Mention side effects (e.g. mutates `state.messages`) in the description.
  - Nested closures (Inspect `solve`/`score` inner functions) don't need their own docstring if the outer factory has one.
- `src/earh/vendor/` is vendored upstream code. Keep it byte-identical: no edits, no formatting (ruff excludes it).

## Logs and results
- Raw Inspect logs go in `logs/NN-phase/<model>/<run-id>/` (gitignored): `00-smoke`, `01-provider-check`, `02-parity`, `03-pilot`, then `10-observational`, `20-prefill`; throwaway runs go in `logs/scratch/`.
- **Use a new `<run-id>` folder per run** (default: timestamp). `eval_set` treats an existing folder as "resume" and skips finished samples.
- After every real (paid) run: save the summary under `results/` (same relative path, e.g. `summarize_pilot.py <log_dir> --write`) and add a row to `results/RUNS.md` (date, commit, run, model, samples, cost, log dir, takeaway). `results/` is committed.

## Git
- Commit at logical checkpoints with descriptive messages; pushing to `origin/main` is fine.
- Never commit `.env`, `logs/`, or `*.eval` files.
