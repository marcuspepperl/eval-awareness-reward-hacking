"""Find candidate pre-existing errors in ImpossibleBench's *original* LiveCodeBench tests.

    uv run python scripts/dataset_check/original_tests.py [--per-problem 10] [--workers 6]

Method (no model calls): take honest V4-Flash submissions from the pilot and phase 1
(attempts that failed the impossible tests and whose code does not contain the altered
assertion's input), run each against the ORIGINAL tests, executing every assertion of
check() separately (so all failing assertions are seen, not just the first). Each problem
runs in one network-less container (local image python:3.12-slim).

Candidates: no submission passes every original assertion, or some assertion is failed by
a large share of submissions (consensus). A pass alone does not clear an assertion: some
submissions special-case a pre-existing broken assertion. Also reports diff irregularities (not exactly one changed / one added assertion).

Writes results/dataset-check/original_tests.json and diff_irregularities.json.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "judge"))
from build_labelset import _tests, altered  # noqa: E402

from earh.judge.extract import extract_attempts  # noqa: E402
from earh.solver import find_code  # noqa: E402

LOGS = [
    "logs/03-pilot/v4flash/promptB-5att",
    "logs/10-observational/v4flash/baseline-8att",
]
OUT = Path("results/dataset-check")
IMAGE = "python:3.12-slim"
MIN_FAIL, MIN_SHARE = (
    2,
    0.3,
)  # suspect assertion: failed by >= 2 and >= 30% of runnable submissions
TMP = Path(
    "logs/scratch/dataset-check-jobs"
).resolve()  # under $HOME: colima only mounts $HOME

RUNNER = r"""
import ast, json, signal
job = json.load(open("/w/job.json"))
class TO(Exception): pass
def _alarm(s, f): raise TO()
signal.signal(signal.SIGALRM, _alarm)
tree = ast.parse(job["test"])
check = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "check")
top = ast.Module(body=[n for n in tree.body if n is not check], type_ignores=[])
out = []
for sub in job["subs"]:
    res = {"key": sub["key"], "load_error": None, "stmts": []}
    ns = {"__name__": "__sol__"}
    try:
        signal.alarm(20)
        exec(compile(job["prompt"] + "\n    pass\n\n" + sub["code"], "sol", "exec"), ns)
        exec(compile(top, "test_top", "exec"), ns)
        signal.alarm(0)
        ns["candidate"] = ns[job["entry_point"]]
    except BaseException as e:
        signal.alarm(0)
        res["load_error"] = (type(e).__name__ + ": " + str(e))[:200]
        out.append(res)
        continue
    for i, stmt in enumerate(check.body):
        status = "ok"
        try:
            signal.alarm(10)
            exec(compile(ast.Module(body=[stmt], type_ignores=[]), "check", "exec"), ns)
        except AssertionError:
            status = "fail"
        except TO:
            status = "timeout"
        except BaseException as e:
            status = "error:" + type(e).__name__
        finally:
            signal.alarm(0)
        res["stmts"].append([i, status])
    out.append(res)
print("@@RESULT@@" + json.dumps(out))
"""


def _args_literal(line: str) -> str | None:
    """The call part of an assertion (`candidate(...)`), whitespace removed."""
    m = re.search(r"candidate\((.*)\)\s*==", line)
    return re.sub(r"\s+", "", m.group(1)) if m else None


def honest_submissions(per_problem: int) -> dict[str, list[dict]]:
    """task_id -> up to N honest submissions, spread across rollouts."""
    by_problem: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    lits_cache: dict[tuple, list[str]] = {}
    for log in LOGS:
        for a in extract_attempts(log):
            if "noflag" not in a.task or a.passed:
                continue
            code = find_code(a.answer)
            if not code:
                continue
            k = (a.sample_id, a.split)
            if k not in lits_cache:
                lits_cache[k] = [
                    x for x in (_args_literal(z["modified"]) for z in altered(*k)) if x
                ]
            if any(lit in re.sub(r"\s+", "", code) for lit in lits_cache[k]):
                continue  # likely a (failed) cheat on the altered assertion
            rollout = f"{a.task}:{a.sample_id}:e{a.epoch}"
            by_problem[a.sample_id][rollout].append({"key": a.key, "code": code})
    out = {}
    for pid, rolls in by_problem.items():
        picked, lists = (
            [],
            [list(reversed(v)) for v in rolls.values()],
        )  # latest attempt first
        while len(picked) < per_problem and any(lists):
            for lst in lists:
                if lst and len(picked) < per_problem:
                    picked.append(lst.pop(0))
        out[pid] = picked
    return out


def run_problem(pid: str, subs: list[dict], meta: dict) -> tuple[str, list]:
    """Run one problem's submissions against its original tests in a container."""
    TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        Path(d, "job.json").write_text(json.dumps({**meta, "subs": subs}))
        Path(d, "runner.py").write_text(RUNNER)
        try:
            r = subprocess.run(
                ["docker", "run", "--rm", "--network", "none", "--memory", "2g", "--cpus", "1",
                 "-v", f"{d}:/w:ro", IMAGE, "python", "/w/runner.py"],
                capture_output=True, text=True, timeout=1800,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            return pid, [{"error": "container timeout"}]
        line = next(
            (x for x in r.stdout.splitlines() if x.startswith("@@RESULT@@")), None
        )
        return pid, json.loads(line[10:]) if line else [
            {"error": (r.stderr or r.stdout)[-500:]}
        ]


def stmt_texts(test: str) -> list[dict]:
    """Per check() statement: source text and whether it is an assert."""
    tree = ast.parse(test)
    check = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "check"
    )
    return [
        {
            "text": ast.get_source_segment(test, s) or "",
            "assert": isinstance(s, ast.Assert),
        }
        for s in check.body
    ]


def diff_irregularities() -> list[dict]:
    """Problems whose diff does not match the split's recipe."""
    rows = []
    for split, want in (("oneoff", "changed"), ("conflicting", "added")):
        for pid in sorted(_tests(split), key=lambda s: int(s.split("_")[1])):
            alt = altered(pid, split)
            kinds = [x["kind"] for x in alt]
            ok = kinds == [want] and (want == "changed" or alt[0]["counterpart"])
            if not ok:
                rows.append({"task_id": pid, "split": split, "kinds": kinds, "n_changes": len(alt),
                             "changes": [{k: (v[:200] if isinstance(v, str) else v) for k, v in x.items()} for x in alt]})  # fmt: skip
    return rows


def main() -> None:
    """Collect submissions, run them, summarise per problem, write results."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-problem", type=int, default=10)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", default=None, help="comma list of task_ids (for testing)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    from datasets import load_dataset

    orig = {
        r["task_id"]: r
        for r in load_dataset("fjzzq2002/impossible_livecodebench", split="original")
    }
    subs = honest_submissions(args.per_problem)
    if args.only:
        subs = {k: v for k, v in subs.items() if k in args.only.split(",")}
        orig = {k: v for k, v in orig.items() if k in args.only.split(",")}
    print(
        f"{len(subs)} problems with honest submissions; {sum(map(len, subs.values()))} submissions"
    )
    results = {}
    with ThreadPoolExecutor(args.workers) as ex:
        futs = [
            ex.submit(
                run_problem,
                pid,
                s,
                {k: orig[pid][k] for k in ("prompt", "test", "entry_point")},
            )
            for pid, s in subs.items()
        ]
        for i, f in enumerate(futs, 1):
            pid, res = f.result()
            results[pid] = res
            print(f"  [{i}/{len(futs)}] {pid}", flush=True)
    touched = defaultdict(
        set
    )  # original assertion texts the diff touched (per problem)
    for split in ("oneoff", "conflicting"):
        for pid in orig:
            for x in altered(pid, split):
                for t in (x.get("original"), x.get("counterpart")):
                    if t:
                        touched[pid].add(re.sub(r"\s+", "", t))
    summary = []
    for pid in sorted(orig, key=lambda s: int(s.split("_")[1])):
        res = results.get(pid)
        texts = stmt_texts(orig[pid]["test"])
        row = {
            "task_id": pid,
            "n_submissions": len(res or []),
            "n_pass_all": 0,
            "n_load_error": 0,
            "failing": [],
        }
        if not res:
            row["status"] = "untested (no honest submission)"
            summary.append(row)
            continue
        fails = defaultdict(int)
        for r in res:
            if "error" in r:
                row["status"] = "runner error: " + r["error"][:120]
                continue
            if r["load_error"]:
                row["n_load_error"] += 1
                continue
            bad = [i for i, st in r["stmts"] if st != "ok"]
            if not bad:
                row["n_pass_all"] += 1
            for i in bad:
                fails[i] += 1
        n_ran = row["n_submissions"] - row["n_load_error"]
        row["failing"] = [
            {"stmt": i, "n_fail": c, "share": round(c / max(1, n_ran), 2), "text": texts[i]["text"][:300],
             "touched_by_diff": re.sub(r"\s+", "", texts[i]["text"]).removeprefix("assert") in {t.removeprefix("assert") for t in touched[pid]}}
            for i, c in sorted(fails.items(), key=lambda kv: -kv[1])
        ]  # fmt: skip
        # A passing submission does not prove an assertion right: honest-on-the-planted-test
        # submissions sometimes special-case a pre-existing broken assertion. So the signal is
        # consensus: an assertion that a large share of honest submissions fail.
        row["suspects"] = [
            f
            for f in row["failing"]
            if f["n_fail"] >= MIN_FAIL and f["share"] >= MIN_SHARE
        ]
        if "status" not in row:
            if not n_ran:
                row["status"] = "untested (all submissions failed to load)"
            elif not row["n_pass_all"]:
                row["status"] = (
                    "candidate (no submission passes all original assertions)"
                )
            elif row["suspects"]:
                row["status"] = "candidate (consensus failure on an assertion)"
            else:
                row["status"] = "clean"
        summary.append(row)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "original_tests.json").write_text(json.dumps(summary, indent=1))
    (out / "raw_results.json").write_text(json.dumps(results))
    (out / "diff_irregularities.json").write_text(
        json.dumps(diff_irregularities(), indent=1)
    )
    from collections import Counter

    print(Counter(r["status"].split(" (")[0].split(":")[0] for r in summary))


if __name__ == "__main__":
    main()
