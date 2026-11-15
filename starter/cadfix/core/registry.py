"""Check registry. Generic: checks are registered by type name and instantiated from data (spec.json).

A check is a function `fn(ctx: CheckContext, **params) -> CheckResult`. The same function runs in the agent's
tools (run_check_<id>, test_fit) and in the grader.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from cadfix.core.assembly import Assembly

CHECKS: dict = {}


@dataclass
class CheckResult:
    passed: bool
    score: float | None = None     # in [0, 1] where the check scores (objective progress, S3); else None
    metrics: dict = field(default_factory=dict)
    details: list = field(default_factory=list)   # short human-readable lines for the agent

    def to_dict(self) -> dict:
        return {"passed": self.passed, "score": self.score, "metrics": self.metrics, "details": self.details}


@dataclass
class CheckContext:
    """What a check sees: the current assembly, the original one, and caches.

    original_cache survives across gradings of the same original (an environment keeps it for the whole
    episode); cache is per grading."""
    current: Assembly
    original: Assembly
    original_cache: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)

    def changed_parts(self, names=None) -> list[str]:
        """Parts whose shape object differs from the original (cheap identity test)."""
        names = names or list(self.current.parts)
        return [n for n in names if self.current.parts[n].shape is not self.original.parts[n].shape]


def register(type_name: str):
    def deco(fn):
        if type_name in CHECKS:
            raise ValueError(f"check type {type_name!r} registered twice")
        CHECKS[type_name] = fn
        return fn
    return deco


def get(type_name: str):
    import cadfix.checks  # noqa: F401  (registers the built-in checks)
    if type_name not in CHECKS:
        raise KeyError(f"unknown check type {type_name!r}; known: {sorted(CHECKS)}")
    return CHECKS[type_name]
