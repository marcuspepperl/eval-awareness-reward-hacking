"""Parity check: ImpossibleBench's own LiveCodeBench task, unchanged, through our provider.

    uv run inspect eval-set scripts/parity_check.py --model deepinfra-raw/v4flash --log-dir logs/02-parity/v4flash

Two tasks (2 samples each): `original` (possible tests, so passes are legitimate and
check the scorer) and `conflicting` (impossible tests, so any pass is a hack). Uses
ImpossibleBench's default instruction to reproduce their setup exactly.
"""

from impossiblebench import impossible_livecodebench
from inspect_ai import task

SETTINGS = dict(agent_type="minimal", max_attempts=5, allow_test_modifications=True)


@task
def parity_original():
    """Task: 2 original-split problems (tests are possible)."""
    return impossible_livecodebench(split="original", limit=2, **SETTINGS)


@task
def parity_conflicting():
    """Task: 2 conflicting-split problems (tests are impossible; pass = hack)."""
    return impossible_livecodebench(split="conflicting", limit=2, **SETTINGS)
