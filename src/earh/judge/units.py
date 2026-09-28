"""Turn attempts into judge units: one prompt per (attempt × pass × chunk).

Passes (see docs/judging.md):
  A   eval awareness      reasoning chunks (+ [ctx] overlap)      one span per occurrence
  B1  code summary        numbered answer code + tests + result   one unit per attempt
  B2  reasoning behavior  the same reasoning chunks as A          answer code as context

Prompt order is shared prefix first (system + setup + task + feedback + reasoning chunk),
pass-specific instructions last, so A and B2 units for the same chunk share a prefix.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from earh.degenerate import diagnose
from earh.judge.extract import Attempt
from earh.segment import Segment, chunk, render, segment_answer, segment_reasoning

Pass = Literal["A", "B1", "B2"]
PROMPTS = Path(__file__).parent / "prompts"
CHUNK_TOKENS = 4_000
OVERLAP_SENTENCES = 10
MAX_TEST_OUTPUT_CHARS = 1_500


@dataclass
class Unit:
    """One judge call: prompt messages, the IDs it may label, and identifiers."""

    id: str  # "<attempt key>:<pass>:c<chunk>"
    attempt_key: str
    pass_: Pass
    chunk: int
    n_chunks: int
    system: str
    user: str
    taggable_ids: list[str]
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Plain dict for JSONL (pass_ serialised as 'pass')."""
        d = asdict(self)
        d["pass"] = d.pop("pass_")
        return d


def template(name: str) -> str:
    """Load a prompt template from prompts/<name>.md."""
    return (PROMPTS / f"{name}.md").read_text()


def fill(text: str, **values: str) -> str:
    """Replace {{key}} placeholders (plain replace, so braces in code are safe)."""
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def reasoning_segments(a: Attempt) -> tuple[list[Segment], dict]:
    """Segment an attempt's reasoning, cut at the loop start for degenerate attempts."""
    text, info = a.reasoning, {"judge_cutoff": None}
    if a.truncated:
        d = diagnose(text)
        if d.judge_cutoff is not None:
            text = text[: d.judge_cutoff]
            info = {"judge_cutoff": d.judge_cutoff, "loop_kind": d.kind}
    return segment_reasoning(text, a.attempt), info


def _context_block(
    a: Attempt, part: int, n_parts: int, ctx: list[Segment], body: list[Segment]
) -> str:
    """Render the shared prefix: setup, task, prior feedback, and one reasoning chunk."""
    feedback = (
        "\n## Feedback the model saw before this attempt (context only)\n"
        f"<feedback>\n{a.feedback_before}\n</feedback>\n"
        if a.feedback_before
        else ""
    )
    return fill(
        template("context"),
        task_prompt=a.task_prompt,
        feedback_section=feedback,
        attempt=a.attempt,
        part=part,
        n_parts=n_parts,
        context_lines="".join(f"[ctx] {s.text}\n" for s in ctx),
        reasoning_lines=render(body),
    )


def reasoning_units(a: Attempt, passes: list[Pass]) -> list[Unit]:
    """Pass A and/or B2 units for one attempt, one per reasoning chunk.

    @param a: The attempt.
    @param passes: Subset of ["A", "B2"] to build.
    @returns: Units in chunk order; empty if the attempt has no reasoning.
    """
    segs, info = reasoning_segments(a)
    if not segs:
        return []
    chunks = chunk(segs, max_tokens=CHUNK_TOKENS)
    answer_code = "\n".join(
        s.text for s in segment_answer(a.answer, a.attempt) if s.kind == "code_line"
    )
    system = template("system").strip()
    suffixes = {
        "A": template("pass_a"),
        "B2": fill(template("pass_b2"), answer_code=answer_code),
    }
    units = []
    for i, body in enumerate(chunks, start=1):
        ctx = chunks[i - 2][-OVERLAP_SENTENCES:] if i > 1 else []
        prefix = _context_block(a, i, len(chunks), ctx, body)
        for pass_ in ("A", "B2"):
            if pass_ in passes:
                units.append(
                    Unit(
                        id=f"{a.key}:{pass_}:c{i}",
                        attempt_key=a.key,
                        pass_=pass_,
                        chunk=i,
                        n_chunks=len(chunks),
                        system=system,
                        user=prefix + "\n" + suffixes[pass_],
                        taggable_ids=[s.id for s in body],
                        meta={"n_sentences": len(segs), **info},
                    )
                )
    return units


def summary_unit(a: Attempt) -> Unit:
    """The pass B1 unit for one attempt: numbered answer code, tests, and test result."""
    code = [s for s in segment_answer(a.answer, a.attempt) if s.kind == "code_line"]
    result = (
        "PASSED" if a.passed else "FAILED\n" + a.test_output[-MAX_TEST_OUTPUT_CHARS:]
    )
    user = fill(
        template("pass_b1"),
        task_prompt=a.task_prompt,
        attempt=a.attempt,
        answer_lines=render(code) if code else "(no code block)",
        test_result=result,
    )
    return Unit(
        id=f"{a.key}:B1:c1",
        attempt_key=a.key,
        pass_="B1",
        chunk=1,
        n_chunks=1,
        system=template("system").strip(),
        user=user,
        taggable_ids=[s.id for s in code],
    )


def build_units(attempts: list[Attempt], passes: list[Pass]) -> list[Unit]:
    """All units for the given attempts and passes.

    @param attempts: Attempts from earh.judge.extract.
    @param passes: Any of "A", "B1", "B2".
    @returns: Units ordered by attempt, then pass, then chunk.
    """
    units: list[Unit] = []
    for a in attempts:
        rp = [p for p in passes if p in ("A", "B2")]
        if rp:
            units += reasoning_units(a, rp)
        if "B1" in passes:
            units.append(summary_unit(a))
    return units
