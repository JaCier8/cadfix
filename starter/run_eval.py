"""Local evaluation without Harbor: agent x level x seeds -> table + CSV in results/.

For each case: the public task (output/tasks/<L>/seed_NNNN/task, built from the generator output if missing), a
fresh output dir, the agent plays through the same tools as over MCP (in-process Env, or --mcp for a real stdio
server), then the grader (cadfix.grade) scores the output dir against the pristine copy.

  python run_eval.py --agent reference,do_nothing,stop_early --level L1,L2,L3 --seeds 0-9 [--mcp]
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

from cadfix import grade, viz
from cadfix.agents import BASELINES
from cadfix.env.env import Env
from scenarios.hinge_lid import generator
from scenarios.hinge_lid import reference
from scenarios.hinge_lid import task as hl_task

AGENTS = {"reference": reference.solve, **BASELINES}
FIELDS = ["agent", "level", "seed", "reward", "s1_met", "gates_ok", "failed_gates", "volume_over_vref",
          "test_fit_calls", "tool_calls", "seconds"]


def run_case(agent: str, level: str, seed: int, results: Path, gen="output/hinge_lid", tasks="output/tasks",
             mcp: bool = False, with_viz: bool = True, with_playback: bool = True) -> dict:
    d = hl_task.ensure_task(level, seed, gen, tasks)
    out = results / agent / level / f"seed_{seed:04d}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    t0 = time.perf_counter()
    if mcp:
        import os
        client = reference.McpClient(env={**os.environ, "CADFIX_TASK_DIR": str(d / "task"), "CADFIX_OUT_DIR": str(out)})
    else:
        client = reference.InProcessClient(Env(d / "task", out))
    try:
        res = AGENTS[agent](client)
    finally:
        client.close()
    seconds = time.perf_counter() - t0
    rep = grade.grade(d / "task", d / "pristine", out)
    (out / "grade.json").write_text(json.dumps(rep, indent=2, default=str))
    if with_viz:
        try:
            viz.visualize(d / "task", d / "pristine", out, out / "viz", report=rep, playback=with_playback)
        except Exception as e:  # noqa: BLE001 - the 3D export must never break an eval
            print(f"warning: viz failed for {agent} {level} seed {seed}: {type(e).__name__}: {e}")
    if isinstance(res, dict) and res.get("log"):
        (out / "agent_log.txt").write_text("\n".join(res["log"]) + "\n")
    ep = json.loads((out / "episode.json").read_text()) if (out / "episode.json").exists() else {}
    s3 = rep["checks"]["S3_minimal_change"]["metrics"]
    return {"agent": agent, "level": level, "seed": seed, "reward": rep["reward"], "s1_met": rep["objective_met"],
            "gates_ok": rep["gates_ok"], "failed_gates": ",".join(rep["failed_gates"]),
            "volume_over_vref": round(s3.get("ratio_to_reference", 0.0), 3), "test_fit_calls": rep["test_fit_calls"],
            "tool_calls": ep.get("calls"), "seconds": round(seconds, 1)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--agent", default="reference,do_nothing,stop_early")
    ap.add_argument("--level", default="L1,L2,L3")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--results", default="results")
    ap.add_argument("--gen", default="output/hinge_lid")
    ap.add_argument("--tasks", default="output/tasks")
    ap.add_argument("--mcp", action="store_true", help="agents talk to a real MCP stdio server")
    ap.add_argument("--no-viz", action="store_true", help="skip the 3D model export (viz/ folder)")
    ap.add_argument("--no-playback", action="store_true", help="skip the step-by-step replay in viewer.html")
    a = ap.parse_args(argv)
    results = Path(a.results)
    rows = []
    print(f"{'agent':<11} {'lvl':<3} {'seed':>4} {'reward':>7} {'S1':<4} {'gates':<5} {'x_ref':>6} {'calls':>5} "
          f"{'tf':>3} {'s':>6}  failed")
    for agent in a.agent.split(","):
        for level in generator.parse_levels(a.level):
            for seed in generator.parse_seeds(a.seeds):
                r = run_case(agent, level, seed, results, a.gen, a.tasks, a.mcp, not a.no_viz, not a.no_playback)
                rows.append(r)
                print(f"{r['agent']:<11} {r['level']:<3} {r['seed']:>4} {r['reward']:>7.3f} "
                      f"{('ok' if r['s1_met'] else 'FAIL'):<4} {('ok' if r['gates_ok'] else 'FAIL'):<5} "
                      f"{r['volume_over_vref']:>6.2f} {r['tool_calls']:>5} {r['test_fit_calls']:>3} {r['seconds']:>6.1f}"
                      f"  {r['failed_gates']}", flush=True)
    print("\nsummary (reward min / mean / max):")
    for agent in a.agent.split(","):
        for level in generator.parse_levels(a.level):
            rw = [r["reward"] for r in rows if r["agent"] == agent and r["level"] == level]
            if rw:
                print(f"  {agent:<11} {level}: {min(rw):.3f} / {sum(rw) / len(rw):.3f} / {max(rw):.3f}  (n={len(rw)})")
    results.mkdir(exist_ok=True)
    name = results / f"run_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    for path in (name, results / "latest.csv"):
        with path.open("w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=FIELDS)
            wr.writeheader()
            wr.writerows(rows)
    print(f"\nwrote {name}")


if __name__ == "__main__":
    main()
