"""Grader CLI. Generic: everything comes from the task's data.

  python -m cadfix.grade --task-dir T --pristine P --submitted S [--level L] [--out report.json]
                         [--reward-file reward.txt]

T: the verifier's own copy of the public task (task.json, spec.json).
P: the verifier's pristine copy: parts/<name>.step for every part, grader.json (private reference values).
S: what the episode left behind: parts/<editable>.step, episode.json, actions.jsonl.

Fixed parts always come from P. An editable part missing from S, or one that cannot be read, is graded as its
pristine original (so an empty S scores like doing nothing). The test_fit cost uses the larger of the counter in
episode.json and the number of test_fit calls in actions.jsonl; edited parts without any episode record pay the
full cap. Any internal error -> reward 0 with the error in the report. reward.txt is always written.
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path

from cadfix.core import kernel
from cadfix.core.assembly import Assembly
from cadfix.core.registry import CheckContext
from cadfix.core.spec import Spec


def _test_fit_calls(submitted: Path) -> int | None:
    counts = []
    ep = submitted / "episode.json"
    if ep.exists():
        try:
            counts.append(int(json.loads(ep.read_text()).get("test_fit_calls", 0)))
        except (ValueError, TypeError, AttributeError):
            pass
    log = submitted / "actions.jsonl"
    if log.exists():
        n = 0
        for line in log.read_text(errors="replace").splitlines():
            try:
                n += json.loads(line).get("tool") == "test_fit"
            except (ValueError, AttributeError):
                continue
        counts.append(n)
    return max(counts) if counts else None


def load_submission(original: Assembly, submitted: Path) -> tuple[Assembly, dict]:
    shapes, notes = {}, {}
    for n in original.editable:
        f = submitted / "parts" / f"{n}.step"
        if not f.exists():
            notes[n] = "missing -> original"
            continue
        try:
            s = kernel.import_step(f)
            if s is None:
                raise ValueError("no shape in file")
            shapes[n] = s
            notes[n] = "submitted"
        except Exception as e:  # noqa: BLE001 - unreadable file of any kind
            notes[n] = f"unreadable ({str(e)[:80]}) -> original"
    return original.with_shapes(shapes), notes


def grade(task_dir, pristine_dir, submitted_dir, level: str | None = None) -> dict:
    t0 = time.perf_counter()
    task_dir, pristine_dir, submitted_dir = Path(task_dir), Path(pristine_dir), Path(submitted_dir)
    grader = json.loads((pristine_dir / "grader.json").read_text())
    if level and grader.get("level") and level != grader["level"]:
        raise ValueError(f"--level {level} does not match the pristine data ({grader['level']})")
    spec = Spec.load(task_dir / "spec.json", grader.get("private"))
    original = Assembly.load(task_dir, pristine_dir / "parts")
    current, notes = load_submission(original, submitted_dir)
    ctx = CheckContext(current, original)
    ev = spec.evaluate(ctx)
    edited = [n for n, v in notes.items() if v == "submitted"]
    calls = _test_fit_calls(submitted_dir)
    if calls is None:
        cost = spec.test_fit_cost(10 ** 6) if edited else 0.0
    else:
        cost = spec.test_fit_cost(calls)
    base = ev["reward"] if ev["reward"] is not None else 0.0
    return {"reward": round(max(0.0, base - cost), 6), "reward_before_test_fit_cost": base,
            "test_fit_calls": calls, "test_fit_cost": cost, "submission": notes,
            "gates_ok": ev["gates_ok"], "failed_gates": ev["failed_gates"], "objective_met": ev["objective_met"],
            "progress": ev["progress"], "scores": ev["scores"],
            "checks": {k: r.to_dict() for k, r in ev["results"].items()},
            "level": grader.get("level"), "seed": grader.get("seed"), "seconds": round(time.perf_counter() - t0, 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task-dir", required=True)
    ap.add_argument("--pristine", required=True)
    ap.add_argument("--submitted", required=True)
    ap.add_argument("--level")
    ap.add_argument("--out", help="JSON report path (default: stdout)")
    ap.add_argument("--reward-file", help="write the reward alone to this file")
    a = ap.parse_args(argv)
    try:
        rep = grade(a.task_dir, a.pristine, a.submitted, a.level)
    except Exception as e:  # noqa: BLE001 - the verifier must always produce a reward
        rep = {"reward": 0.0, "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}
    text = json.dumps(rep, indent=2, default=str)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text)
    else:
        print(text)
    if a.reward_file:
        Path(a.reward_file).parent.mkdir(parents=True, exist_ok=True)
        Path(a.reward_file).write_text(f"{rep['reward']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
