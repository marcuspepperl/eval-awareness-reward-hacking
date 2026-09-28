"""Extract per-attempt records from Track A Inspect logs.

A Track A sample's messages are: user (task), then for each attempt an assistant reply
(reasoning + answer), followed by a user feedback message if the attempt failed. The
solver's per-attempt records (pass / truncated / ...) live in sample.metadata["attempts"].
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from inspect_ai.log import list_eval_logs, read_eval_log
from inspect_ai.model import ChatMessage


@dataclass
class Attempt:
    """One attempt of one sample: everything the judge needs, plus identifiers."""

    key: str  # "<task>:<sample_id>:e<epoch>:a<attempt>"
    task: str
    sample_id: str
    epoch: int
    attempt: int
    split: str  # oneoff | conflicting | original
    task_prompt: str  # the first user message (spec + tests)
    # the feedback message shown before this attempt ("" for attempt 1)
    feedback_before: str
    reasoning: str
    answer: str
    passed: bool
    truncated: bool
    test_output: str  # tail of the test run output ("" if passed or flagged)

    def to_dict(self) -> dict:
        """Plain dict for JSONL."""
        return asdict(self)


def _resolve(sample, value: str) -> str:
    """Resolve Inspect's attachment:// references to stored text."""
    if value.startswith("attachment://"):
        return sample.attachments.get(value.split("//", 1)[1], value)
    return value


def _reasoning(sample, message: ChatMessage) -> str:
    """Concatenated reasoning blocks of an assistant message."""
    if isinstance(message.content, str):
        return ""
    return "\n".join(
        _resolve(sample, c.reasoning) for c in message.content if c.type == "reasoning"
    )


def extract_attempts(log_dir: str) -> list[Attempt]:
    """Read every Track A log under log_dir and return one Attempt per model attempt.

    @param log_dir: Directory of Inspect .eval logs (e.g. logs/03-pilot/v4flash/promptB-5att).
    @returns: Attempts in log order; samples whose messages don't line up with their
        attempt records are skipped with a warning.
    """
    out: list[Attempt] = []
    for info in list_eval_logs(log_dir):
        log = read_eval_log(info)
        for s in log.samples or []:
            records = s.metadata.get("attempts", [])
            msgs = s.messages
            task_prompt = _resolve(s, msgs[0].text) if msgs else ""
            # Walk messages: assistant replies are attempts; user messages after the first
            # are feedback shown before the next attempt.
            replies, feedback, pending = [], [], ""
            for m in msgs[1:]:
                if m.role == "assistant":
                    replies.append(m)
                    feedback.append(pending)
                    pending = ""
                elif m.role == "user":
                    pending = _resolve(s, m.text)
            if len(replies) != len(records):
                print(
                    f"warning: {log.eval.task} {s.id} e{s.epoch}: "
                    f"{len(replies)} replies vs {len(records)} attempt records; skipped"
                )
                continue
            for rec, msg, fb in zip(records, replies, feedback, strict=True):
                out.append(
                    Attempt(
                        key=f"{log.eval.task}:{s.id}:e{s.epoch}:a{rec['attempt']}",
                        task=log.eval.task,
                        sample_id=str(s.id),
                        epoch=s.epoch,
                        attempt=rec["attempt"],
                        split=s.metadata.get("impossible_type", ""),
                        task_prompt=task_prompt,
                        feedback_before=fb,
                        reasoning=_reasoning(s, msg),
                        answer=_resolve(s, msg.text),
                        passed=bool(rec["passed"]),
                        truncated=bool(rec["truncated"]),
                        test_output=rec.get("output", ""),
                    )
                )
    return out
