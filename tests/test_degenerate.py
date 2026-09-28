"""Unit tests for earh.degenerate (repetition-loop detection)."""

import random

from earh.degenerate import diagnose


def _prose(n_words: int, seed: int = 0) -> str:
    """Pseudo-random, non-repetitive text."""
    rng = random.Random(seed)
    vocab = [f"w{rng.randrange(10**6)}" for _ in range(5000)]
    return " ".join(rng.choice(vocab) for _ in range(n_words))


def test_normal_text_is_not_degenerate():
    d = diagnose(_prose(20_000))
    assert d.kind == "none" and d.loop_start is None and d.judge_cutoff is None


def test_exact_loop_detected_with_start_near_true_start():
    head = _prose(5_000)
    text = head + " " + "1601 = " * 20_000
    d = diagnose(text)
    assert d.kind == "exact_loop"
    assert abs(d.loop_start - len(head)) <= 4_000  # within one 4k window
    assert d.judge_cutoff >= len(head)  # never cuts pre-loop reasoning


def test_character_loop_without_spaces_detected():
    d = diagnose(_prose(3_000) + " " + "W" * 100_000)
    assert d.kind == "exact_loop"
