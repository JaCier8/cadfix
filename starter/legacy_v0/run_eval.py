"""Run scripted agents on tasks and grade them, mimicking the container split.

For each task: copy it WITHOUT hidden/ into a sandbox, let the agent work there through FitFixEnv,
then grade the saved part against the full task folder (with hidden/).

  python run_eval.py --agent solver --seeds 0-9
  python run_eval.py --agent all --seeds 0-9
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import tempfile
import time
from pathlib import Path

from fitfix.agents import AGENTS, load_hidden
from fitfix.env import FitFixEnv
from fitfix.grader import grade


def run_one(agent: str, task_dir: Path, results: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp) / "task"
        shutil.copytree(task_dir, sandbox, ignore=shutil.ignore_patterns("hidden"))
        out = results / agent / task_dir.name
        if out.exists():
            shutil.rmtree(out)
        env = FitFixEnv(sandbox, out)
        t0 = time.time()
        AGENTS[agent](env, load_hidden(task_dir) if agent == "oracle" else None)
        res = grade(out / "enclosure.stl", task_dir)
        res["agent"], res["task"], res["seconds"], res["tool_calls"] = agent, task_dir.name, round(time.time() - t0, 2), env.calls
        (out / "grade.json").write_text(json.dumps(res, indent=2))
        return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="all")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--tasks", default="tasks")
    ap.add_argument("--results", default="results")
    a = ap.parse_args()
    lo, hi = (int(v) for v in a.seeds.split("-"))
    agents = list(AGENTS) if a.agent == "all" else [a.agent]
    summary = {}
    for ag in agents:
        rs = [run_one(ag, Path(a.tasks) / f"enc-{s:04d}", Path(a.results)) for s in range(lo, hi + 1)]
        scores = [r["reward"] for r in rs]
        summary[ag] = {"mean": round(statistics.mean(scores), 3), "min": min(scores), "max": max(scores),
                       "per_task": scores}
        print(f"{ag:>11}: mean {summary[ag]['mean']:.3f}  per task {scores}")
    Path(a.results).mkdir(exist_ok=True)
    (Path(a.results) / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
