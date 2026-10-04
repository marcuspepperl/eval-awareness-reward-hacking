"""Track B (agentic harness) logs → `Episode` records for the judge.

One episode = one Inspect sample: system → user → alternating assistant turns (reasoning +
optional text + tool calls) and tool results; the episode ends with an assistant message
without tool calls (the report to the user). Reasoning is kept in context across turns,
so the episode is judged as one stream. See docs/judge-track-b-adaptation.md.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from inspect_ai.log import list_eval_logs, read_eval_log
from inspect_ai.model import ContentReasoning, ContentText

THINK_TAGS = re.compile(r"</?think>")


@dataclass
class Turn:
    """One assistant turn: its reasoning, visible text, tool calls, and their results."""

    turn: int
    reasoning: str
    text: str
    calls: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


@dataclass
class Episode:
    """One agentic episode, with what the judge needs and the scorer's outcome."""

    key: str  # "<task>:<sample_id>:e<epoch>"
    task: str
    sample_id: str
    epoch: int
    split: str
    task_prompt: str
    turns: list[Turn]
    final_message: str
    final_code: str
    test_diff: str
    passed: bool
    test_modified: bool
    stop_reason: str

    def to_dict(self) -> dict:
        """Plain dict for JSONL."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Episode:
        """Inverse of to_dict."""
        return cls(**{**d, "turns": [Turn(**t) for t in d["turns"]]})


def _call_text(tc) -> str:
    """A tool call as one readable string: `bash: python test.py`, `text_editor: create func.py …`."""
    args = tc.arguments or {}
    if tc.function == "bash" and "command" in args:
        return f"bash: {args['command']}"
    if tc.function == "python" and "code" in args:
        return f"python: {args['code']}"
    if tc.function == "text_editor":
        cmd, path = args.get("command", ""), args.get("path", "")
        body = args.get("file_text") or args.get("new_str") or ""
        old = args.get("old_str")
        return f"text_editor {cmd} {path}" + (
            f"\nreplace: {old}\nwith: {body}" if old else f"\n{body}" if body else ""
        )
    return f"{tc.function}: {args}"


def _task_prompt(sample) -> str:
    """What the model was asked, plus the two files it found in the sandbox."""
    md = sample.metadata
    user = next(m.text for m in sample.messages if m.role == "user")
    return f"{user}\n\nfunc.py:\n```python\n{md['prompt']}\n```\n\ntest.py:\n```python\n{md['test']}\n```"


def episode_from_sample(task: str, sample) -> Episode:
    """Build an Episode from one Track B sample."""
    turns: list[Turn] = []
    final = ""
    for m in sample.messages:
        if m.role == "assistant":
            parts = (
                m.content
                if isinstance(m.content, list)
                else [ContentText(text=m.content or "")]
            )
            reasoning = "\n".join(
                THINK_TAGS.sub("", p.reasoning or "")
                for p in parts
                if isinstance(p, ContentReasoning)
            ).strip()
            text = "\n".join(
                p.text or "" for p in parts if isinstance(p, ContentText)
            ).strip()
            turns.append(
                Turn(
                    len(turns) + 1,
                    reasoning,
                    text,
                    [_call_text(tc) for tc in m.tool_calls or []],
                )
            )
            if not m.tool_calls:
                final = text
        elif m.role == "tool" and turns:
            turns[-1].outputs.append(m.text or "")
    md = next(iter(sample.scores.values())).metadata or {}
    return Episode(
        key=f"{task}:{sample.id}:e{sample.epoch}",
        task=task,
        sample_id=str(sample.id),
        epoch=sample.epoch,
        split=md.get("split") or sample.metadata.get("impossible_type", ""),
        task_prompt=_task_prompt(sample),
        turns=turns,
        final_message=final,
        final_code=md.get("func_py") or "",
        test_diff=md.get("test_diff") or "",
        passed=bool(md.get("passed")),
        test_modified=bool(md.get("test_modified")),
        stop_reason=str(md.get("stop_reason") or ""),
    )


def extract_episodes(log_path: str) -> list[Episode]:
    """All episodes from a Track B .eval file or a directory of them.

    @param log_path: A .eval file or a log directory.
    @returns: Episodes in log order.
    """
    files = (
        [log_path]
        if log_path.endswith(".eval")
        else [i.name for i in list_eval_logs(log_path)]
    )
    out = []
    for f in files:
        log = read_eval_log(f)
        out += [episode_from_sample(log.eval.task, s) for s in log.samples or []]
    return out
