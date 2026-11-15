"""Check specs and the reward policy as data (spec.json). Generic.

spec.json:
  {"checks": [{"id", "type", "role": "gate" | "objective" | "score", "params": {...}, "description"}],
   "reward": {"objective": id, "progress_weight": w, "met_base": b,
              "scores": {name: {"weight": w, "checks": [ids], "combine": "all_passed" | "score"}}},
   "test_fit_cost": {"free_calls": n, "per_call": c, "cap": m}, ...}

Private reference values (e.g. the volume of the best known fix) are not in spec.json; the grader merges them
in from its own data as extra params per check id (`private`).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from cadfix.core import registry
from cadfix.core.registry import CheckContext, CheckResult
from cadfix.core.reward import RewardPolicy


@dataclass(frozen=True)
class CheckSpec:
    id: str
    type: str
    role: str
    params: dict
    description: str = ""


class Spec:
    def __init__(self, data: dict, private: dict | None = None):
        self.data = data
        private = private or {}
        self.checks = [CheckSpec(c["id"], c["type"], c["role"], {**c.get("params", {}), **private.get(c["id"], {})},
                                 c.get("description", "")) for c in data["checks"]]
        self.by_id = {c.id: c for c in self.checks}
        r = data["reward"]
        self.policy = RewardPolicy(progress_weight=r["progress_weight"], met_base=r["met_base"],
                                   weights={k: v["weight"] for k, v in r["scores"].items()})
        self.objective = r["objective"]
        self.score_groups = r["scores"]
        self.gates = [c.id for c in self.checks if c.role == "gate"]

    @staticmethod
    def load(path, private: dict | None = None) -> "Spec":
        return Spec(json.loads(Path(path).read_text()), private)

    def run_check(self, ctx: CheckContext, check_id: str) -> CheckResult:
        c = self.by_id[check_id]
        t0 = time.perf_counter()
        res = registry.get(c.type)(ctx, **c.params)
        res.metrics.setdefault("seconds", round(time.perf_counter() - t0, 3))
        return res

    def evaluate(self, ctx: CheckContext) -> dict:
        """Run every check and combine them into the reward. reward is None when a score cannot be computed
        (a private reference value is missing, as in the agent's own tools)."""
        results = {c.id: self.run_check(ctx, c.id) for c in self.checks}
        gates_ok = all(results[g].passed for g in self.gates)
        obj = results[self.objective]
        scores = {}
        for name, grp in self.score_groups.items():
            rs = [results[i] for i in grp["checks"]]
            if grp["combine"] == "all_passed":
                scores[name] = 1.0 if all(r.passed for r in rs) else 0.0
            else:
                vals = [r.score for r in rs]
                scores[name] = None if any(v is None for v in vals) else min(vals)
        progress = obj.score if obj.score is not None else (1.0 if obj.passed else 0.0)
        if obj.passed and gates_ok and any(v is None for v in scores.values()):
            reward = None
        else:
            reward = self.policy.reward(gates_ok, obj.passed, progress,
                                        {k: (v if v is not None else 0.0) for k, v in scores.items()})
        return {"results": results, "gates_ok": gates_ok, "objective_met": obj.passed, "progress": progress,
                "scores": scores, "reward": reward,
                "failed_gates": [g for g in self.gates if not results[g].passed]}

    def test_fit_cost(self, test_fit_calls: int) -> float:
        c = self.data.get("test_fit_cost") or {}
        extra = max(0, int(test_fit_calls) - int(c.get("free_calls", 0)))
        return round(min(float(c.get("cap", 0.0)), extra * float(c.get("per_call", 0.0))), 6)
