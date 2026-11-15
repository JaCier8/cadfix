"""Test-speed marks. `pytest -q -m "not slow"` = quick run (< 1 min); `pytest -q` = full suite.

Multi-seed tests keep a few cases in the quick run and mark the rest `slow` (registered in pyproject.toml)."""
import pytest

SLOW = pytest.mark.slow


def slow_except(cases, keep):
    """Parametrize values: those in `keep` run in the quick run, the others are marked slow."""
    keep = set(keep)
    return [c if c in keep else pytest.param(*(c if isinstance(c, tuple) else (c,)), marks=SLOW) for c in cases]
