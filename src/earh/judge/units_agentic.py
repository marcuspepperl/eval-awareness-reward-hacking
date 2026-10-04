"""Track B episodes → judge units (one prompt per episode × pass × chunk).

Same passes and rubric as Track A (earh.judge.units); what changes:
- the unit is the whole episode: reasoning of every turn (`r<turn>.<nnnn>`) and visible
  turn text (`a<turn>.S<nn>`, incl. the final message) in one stream, chunked across turns;
- tool calls and results are interleaved as compressed context lines (never labelable);
- B1 (`B1A`) reads the final func.py, the test.py diff, the final test result, and the final
  message, and adds `disclosed` / `flagged_test`.
"""

from __future__ import annotations

from earh.judge.extract_agentic import Episode
from earh.judge.units import CHUNK_TOKENS, OVERLAP_SENTENCES, Pass, Unit, fill, template
from earh.segment import Segment, chunk, render, segment_answer, segment_reasoning

MAX_CALL_CHARS = 800
MAX_OUTPUT_CHARS = 1_500


def _clip(text: str, n: int) -> str:
    """Keep head and tail of long text."""
    text = text.strip()
    if len(text) <= n:
        return text
    h = n * 2 // 3
    return f"{text[:h]} … [{len(text) - n} chars cut] … {text[-(n - h) :]}"


def episode_segments(e: Episode) -> list[Segment]:
    """The episode as one stream: reasoning + visible text (labelable) and tool lines (context).

    Tool lines and turn dividers have kind "tool" / "turn" and IDs that are never taggable.
    """
    out: list[Segment] = []
    for t in e.turns:
        out.append(Segment(f"turn{t.turn}", "turn", f"── turn {t.turn} ──", 0, 0))
        out += segment_reasoning(t.reasoning, t.turn)
        if t.text:
            out += [s for s in segment_answer(t.text, t.turn) if s.kind != "code_line"]
        for k, call in enumerate(t.calls):
            res = t.outputs[k] if k < len(t.outputs) else ""
            line = f"{_clip(call, MAX_CALL_CHARS)}\n→ {_clip(res, MAX_OUTPUT_CHARS) or '(no output)'}"
            out.append(Segment(f"tool{t.turn}.{k + 1}", "tool", line, 0, 0))
    return out


def _labelable(s: Segment) -> bool:
    """Reasoning sentences and visible text are labelable; tool lines and dividers are not."""
    return s.kind not in ("tool", "turn")


def _render(segs: list[Segment]) -> str:
    """Labelable segments as '[id] text'; tool lines as '[tool] …'; dividers as-is."""
    lines = []
    for s in segs:
        if s.kind == "turn":
            lines.append(s.text)
        elif s.kind == "tool":
            lines.append("[tool] " + s.text.replace("\n", "\n       "))
        else:
            lines.append(render([s]))
    return "\n".join(lines)


def reasoning_units_agentic(e: Episode, passes: list[Pass]) -> list[Unit]:
    """Pass A and/or B2 units for one episode, chunked across turns.

    @param e: The episode.
    @param passes: Subset of ["A", "B2"].
    @returns: Units in chunk order.
    """
    segs = episode_segments(e)
    if not any(_labelable(s) for s in segs):
        return []
    chunks = chunk(segs, max_tokens=CHUNK_TOKENS)
    system = template("system").strip()
    suffixes = {
        "A": template("pass_a"),
        "B2": fill(template("pass_b2"), answer_code=e.final_code),
    }
    n_lab = sum(_labelable(s) for s in segs)
    units = []
    for i, body in enumerate(chunks, start=1):
        prev = [s for c in chunks[: i - 1] for s in c if _labelable(s)]
        ctx = prev[-OVERLAP_SENTENCES:]
        prefix = fill(
            template("context_agentic"),
            task_prompt=e.task_prompt,
            part=i,
            n_parts=len(chunks),
            context_lines="".join(f"[ctx] {s.text}\n" for s in ctx),
            reasoning_lines=_render(body),
        )
        for pass_ in ("A", "B2"):
            if pass_ in passes:
                units.append(
                    Unit(
                        id=f"{e.key}:{pass_}:c{i}",
                        attempt_key=e.key,
                        pass_=pass_,
                        chunk=i,
                        n_chunks=len(chunks),
                        system=system,
                        user=prefix + "\n" + suffixes[pass_],
                        taggable_ids=[s.id for s in body if _labelable(s)],
                        meta={"n_sentences": n_lab, "harness": "agentic"},
                    )
                )
    return units


def summary_unit_agentic(e: Episode) -> Unit:
    """The B1A unit: numbered final func.py, test.py diff, final result, final message."""
    code = [
        s
        for s in segment_answer(f"```python\n{e.final_code}\n```", 0)
        if s.kind == "code_line"
    ]
    user = fill(
        template("pass_b1_agentic"),
        task_prompt=e.task_prompt,
        answer_lines=render(code) if code else "(empty func.py)",
        test_diff=e.test_diff.strip() or "(test.py unchanged)",
        test_result="PASSED" if e.passed else "FAILED",
        final_message=e.final_message or "(no final message)",
    )
    return Unit(
        id=f"{e.key}:B1A:c1",
        attempt_key=e.key,
        pass_="B1A",
        chunk=1,
        n_chunks=1,
        system=template("system").strip(),
        user=user,
        taggable_ids=[s.id for s in code],
        meta={"harness": "agentic"},
    )


def build_units_agentic(episodes: list[Episode], passes: list[str]) -> list[Unit]:
    """All units for the given episodes; passes are any of "A", "B1", "B2" (B1 → B1A)."""
    units: list[Unit] = []
    for e in episodes:
        rp = [p for p in passes if p in ("A", "B2")]
        if rp:
            units += reasoning_units_agentic(e, rp)
        if "B1" in passes:
            units.append(summary_unit_agentic(e))
    return units
