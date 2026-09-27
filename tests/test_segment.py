"""Unit tests for earh.segment (sentence IDs for the judge)."""

from earh.segment import chunk, render, segment_answer, segment_reasoning


def _offsets_ok(text, segs):
    """Every segment's [start, end) slice reproduces its text exactly."""
    return all(text[s.start : s.end] == s.text for s in segs)


def test_sentences_split_on_punctuation_and_newlines():
    text = "We need implement. Need think.\nWait! Is this a test?"
    segs = segment_reasoning(text, 3)
    assert [s.text for s in segs] == [
        "We need implement.",
        "Need think.",
        "Wait!",
        "Is this a test?",
    ]
    assert [s.id for s in segs] == ["r3.0001", "r3.0002", "r3.0003", "r3.0004"]
    assert _offsets_ok(text, segs)


def test_no_split_on_decimals_method_calls_or_lowercase_continuation():
    text = "The value is 3.14 and x.append(y) works, e.g. the list."
    segs = segment_reasoning(text, 1)
    assert len(segs) == 1


def test_closing_quotes_and_brackets_stay_with_sentence():
    text = 'OK. "Quoted." (Aside.) Done!'
    segs = segment_reasoning(text, 1)
    assert [s.text for s in segs] == ["OK.", '"Quoted."', "(Aside.)", "Done!"]
    assert _offsets_ok(text, segs)


def test_code_block_in_reasoning_is_one_item():
    text = "Plan:\n```python\ndef f():\n    return 1\n```\nNext."
    segs = segment_reasoning(text, 2)
    kinds = [s.kind for s in segs]
    assert kinds == ["sentence", "code_block", "sentence"]
    assert segs[1].text.startswith("```python") and segs[1].text.endswith("```")
    assert _offsets_ok(text, segs)


def test_answer_code_lines_and_prose():
    text = "Here is the fix.\n```python\ndef f(x):\n\n    return 14\n```\nNote: the test looks wrong."
    segs = segment_answer(text, 3)
    assert [s.id for s in segs] == ["a3.S01", "a3.L01", "a3.L02", "a3.S02"]
    assert [s.kind for s in segs] == ["prose", "code_line", "code_line", "prose"]
    assert _offsets_ok(text, segs)


def test_render_and_chunk_keep_global_ids():
    text = "\n".join(f"Sentence number {i}." for i in range(1, 51))
    segs = segment_reasoning(text, 1)
    chunks = chunk(segs, max_tokens=50)
    assert len(chunks) > 1
    assert [s.id for c in chunks for s in c] == [s.id for s in segs]
    assert render(segs[:1]) == "[r1.0001] Sentence number 1."
