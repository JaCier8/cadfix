#!/usr/bin/env python3
"""Archive a Harbor job and record it in the run index.

  python scripts/record_run.py <job_dir> --label LABEL [--notes TEXT] [--run-id ID] [--replace]
  python scripts/record_run.py --entry entry.json [--replace]      # a non-Harbor run (manual, local run_eval)
  python scripts/record_run.py --render                            # only re-render docs/RUNS.md

For a Harbor job (e.g. jobs/2026-11-15__06-48-21):
  1. COPIES the job dir to harbor_runs/<run_id>/ (default run_id = <label>_<job name>). The job dir is never moved
     or changed. If harbor_runs/<run_id>/ already holds this job (same job_name in config.json) the copy is skipped.
  2. Reads config.json, lock.json, result.json and every trial's result.json + verifier/{grade.json,episode.json}
     and appends one entry to runs/index.json.
  3. Re-renders docs/RUNS.md from runs/index.json (the index is the source; RUNS.md is generated, in index order).

The build is identified from the task digests in lock.json (Harbor's content hash of each task dir). If Harbor is
importable (run with the Harbor venv's python), they are compared with harbor_tasks/judge at every git tag, so
the entry names the tag whose tasks are byte-identical to what the run used.

Run from the repo's starter/ directory. Standard library only (Harbor optional, for the digest match).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "runs" / "index.json"
RUNS_MD = ROOT / "docs" / "RUNS.md"
ARCHIVE = ROOT / "harbor_runs"
JUDGE = "harbor_tasks/judge"


def _load(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


# ---------------------------------------------------------------- build identification (task digests vs git tags)

def _tag_digests() -> dict[str, dict[str, str]]:
    """{tag: {task name: sha256 hex}} for harbor_tasks/judge at every git tag. Empty if Harbor is not importable."""
    try:
        from harbor.publisher.packager import Packager
    except ImportError:
        return {}
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    prefix, top = git("rev-parse", "--show-prefix"), git("rev-parse", "--show-toplevel")
    tags = subprocess.run(["git", "tag"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    out = {}
    for tag in tags:
        with tempfile.TemporaryDirectory() as tmp:
            arch = subprocess.run(["git", "archive", tag, prefix + JUDGE], cwd=top, capture_output=True)
            if arch.returncode != 0:
                continue
            subprocess.run(["tar", "-x", "-C", tmp], input=arch.stdout, check=True)
            base = Path(tmp) / prefix / JUDGE
            out[tag] = {d.name: Packager.compute_content_hash(d)[0] for d in sorted(base.iterdir()) if d.is_dir()}
    return out


def _build(lock: dict) -> dict:
    digests = {}
    for t in lock.get("trials", []):
        task = t.get("task") or {}
        digests[task.get("name")] = (task.get("digest") or "").removeprefix("sha256:")
    tags = _tag_digests()
    matched = [tag for tag, d in tags.items() if all(d.get(n) == h for n, h in digests.items())]
    return {"task_digests": {n: h[:12] for n, h in sorted(digests.items())},
            "matched_tags": matched if tags else None,
            "match_method": "Harbor Packager.compute_content_hash of harbor_tasks/judge at each git tag"
            if tags else "not checked (Harbor not importable)"}


# ---------------------------------------------------------------- Harbor job -> entry

def _level(task_name: str) -> str | None:
    for part in task_name.split("-"):
        if len(part) == 2 and part[0] == "l" and part[1].isdigit():
            return part.upper()
    return None


def _trial(tdir: Path) -> dict:
    r = _load(tdir / "result.json") or {}
    g = _load(tdir / "verifier" / "grade.json") or {}
    ep = _load(tdir / "verifier" / "episode.json") or _load(tdir / "artifacts" / "output" / "episode.json") or {}
    exc = r.get("exception_info") or None
    s3 = (g.get("checks") or {}).get("S3_minimal_change", {}).get("metrics", {})
    ar = r.get("agent_result") or {}
    return {
        "trial": tdir.name, "task": r.get("task_name"), "level": _level(r.get("task_name") or tdir.name),
        "reward": ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward"),
        "exception": exc.get("exception_type") if exc else None,
        "gates_ok": g.get("gates_ok"), "failed_gates": g.get("failed_gates"), "s1_met": g.get("objective_met"),
        "scores": g.get("scores"), "changed_mm3": s3.get("changed_mm3"), "ratio_to_ref": s3.get("ratio_to_reference"),
        "test_fit_calls": g.get("test_fit_calls"), "test_fit_cost": g.get("test_fit_cost"),
        "mcp_calls": ep.get("calls"), "edits": ep.get("edits"), "submitted": ep.get("submitted"),
        "cost_usd": ar.get("cost_usd"), "started_at": r.get("started_at"), "finished_at": r.get("finished_at"),
    }


def _summary(trials: list[dict]) -> dict:
    by = defaultdict(list)
    for t in trials:
        if t["reward"] is not None:
            by[t["level"]].append(t["reward"])
    allr = [x for v in by.values() for x in v]
    cost = [t["cost_usd"] for t in trials if t["cost_usd"] is not None]
    return {"n_trials": len(trials), "n_rewarded": len(allr),
            "n_exceptions": sum(1 for t in trials if t["exception"]),
            "mean": round(sum(allr) / len(allr), 4) if allr else None,
            "per_level": {k: {"n": len(v), "mean": round(sum(v) / len(v), 4), "rewards": [round(x, 3) for x in v]}
                          for k, v in sorted(by.items())},
            "cost_usd": round(sum(cost), 4) if cost else None}


def harbor_entry(job: Path, label: str, notes: str, run_id: str, archive: Path) -> dict:
    cfg, lock, res = _load(job / "config.json") or {}, _load(job / "lock.json") or {}, _load(job / "result.json") or {}
    agents = cfg.get("agents") or [cfg.get("agent") or {}]
    a = agents[0]
    datasets = [d.get("path") for d in cfg.get("datasets", [])] or [t.get("path") for t in cfg.get("tasks", [])]
    trials = [_trial(d) for d in sorted(job.iterdir()) if d.is_dir() and (d / "result.json").exists()]
    first = next((t for t in trials if t.get("started_at")), {})
    info = (_load(job / trials[0]["trial"] / "result.json") or {}).get("agent_info") if trials else None
    return {
        "run_id": run_id, "kind": "harbor", "label": label, "notes": notes,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "job_name": cfg.get("job_name", job.name), "source": _rel(job), "archive": _rel(archive),
        "harbor_version": (lock.get("harbor") or {}).get("version"),
        "agent": a.get("name") or a.get("import_path"), "agent_version": (info or {}).get("version"),
        "model": a.get("model_name"), "dataset": datasets, "n_attempts": cfg.get("n_attempts"),
        "started_at": res.get("started_at") or first.get("started_at"), "finished_at": res.get("finished_at"),
        "build": _build(lock), "summary": _summary(trials), "trials": trials,
    }


# ---------------------------------------------------------------- index + RUNS.md

def load_index() -> dict:
    return _load(INDEX) or {"schema": 1, "description": "Every evaluation run of cadfix/hinge_lid. Written by "
                                                         "scripts/record_run.py; docs/RUNS.md is rendered from it.",
                            "runs": []}


def add(entry: dict, replace: bool) -> None:
    idx = load_index()
    ids = [r["run_id"] for r in idx["runs"]]
    if entry["run_id"] in ids:
        if not replace:
            sys.exit(f"run_id {entry['run_id']!r} is already in {_rel(INDEX)} (use --replace)")
        idx["runs"][ids.index(entry["run_id"])] = entry
    else:
        idx["runs"].append(entry)
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(idx, indent=2, ensure_ascii=False) + "\n")


def _f(x, nd=3):
    return "–" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def render() -> str:
    idx = load_index()
    out = ["# Runs", "",
           "Every evaluation run so far. Generated by `scripts/record_run.py` from `runs/index.json` (do not edit by "
           "hand; re-render with `python scripts/record_run.py --render`). Harbor jobs are copied unchanged into "
           "`harbor_runs/<run_id>/`; the per-trial files are described in `docs/DATA_FORMAT.md`. Harbor times are local "
           "(+01:00, as Harbor writes them); manual and local runs are UTC (Z). Build = the git tag whose "
           "harbor_tasks/judge has exactly the task digests Harbor recorded in the job's lock.json.", "",
           "| Run | Kind | Agent / model | Tasks | Build | Mean | L1 | L2 | L3 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in idx["runs"]:
        s = r.get("summary") or {}
        pl = s.get("per_level") or {}
        build = r.get("build") or {}
        tag = ", ".join(build.get("matched_tags") or []) or build.get("commit") or "–"
        who = " / ".join(x for x in (r.get("agent"), r.get("model")) if x)
        out.append(f"| [{r['run_id']}](#{r['run_id'].lower().replace('_', '-').replace('.', '')}) | {r['kind']} | "
                   f"{who} | {r.get('tasks_text') or ', '.join(r.get('dataset') or [])} | {tag} | {_f(s.get('mean'))} | "
                   + " | ".join(_f((pl.get(L) or {}).get("mean")) for L in ("L1", "L2", "L3")) + " |")
    for r in idx["runs"]:
        out += ["", f"## {r['run_id']}", ""]
        meta = [("kind", r["kind"]), ("label", r.get("label")), ("agent", r.get("agent")),
                ("agent version", r.get("agent_version")), ("model", r.get("model")),
                ("harbor", r.get("harbor_version")), ("attempts per task (-k)", r.get("n_attempts")),
                ("started", r.get("started_at")), ("finished", r.get("finished_at")),
                ("source", r.get("source") and f"`{r['source']}`"), ("archive", r.get("archive") and f"`{r['archive']}`")]
        b = r.get("build") or {}
        if b.get("task_digests"):
            meta.append(("task digests", ", ".join(f"{k[-8:]} {v}" for k, v in b["task_digests"].items())))
        if "matched_tags" in b:
            meta.append(("build", (", ".join(f"`{t}`" for t in b["matched_tags"]) or "no tag matches")
                         if b["matched_tags"] is not None else b.get("match_method")))
        elif b.get("commit"):
            meta.append(("build", b["commit"]))
        s = r.get("summary") or {}
        if s.get("cost_usd") is not None:
            meta.append(("cost", f"${s['cost_usd']:.2f}"))
        if s.get("n_trials"):
            meta.append(("trials", f"{s['n_trials']} ({s.get('n_exceptions', 0)} with a Harbor exception)"))
        out += [f"- {k}: {v}" for k, v in meta if v not in (None, "")]
        if r.get("notes"):
            out += ["", r["notes"]]
        if r.get("trials"):
            out += ["", "| Trial | Level | Reward | Exception | Gates | S1 | Vol / V_ref | MCP calls | test_fit | Cost $ |",
                    "|---|---|---|---|---|---|---|---|---|---|"]
            for t in r["trials"]:
                out.append(f"| {t['trial']} | {t['level']} | {_f(t['reward'])} | {t['exception'] or '–'} | "
                           f"{'ok' if t['gates_ok'] else ('–' if t['gates_ok'] is None else 'FAIL')} | "
                           f"{'met' if t['s1_met'] else ('–' if t['s1_met'] is None else 'not met')} | "
                           f"{_f(t['ratio_to_ref'], 2)} | {_f(t['mcp_calls'])} | {_f(t['test_fit_calls'])} | "
                           f"{_f(t['cost_usd'], 2)} |")
        for tbl in r.get("tables") or []:
            out += ["", f"**{tbl['title']}**" if tbl.get("title") else "", "",
                    "| " + " | ".join(tbl["columns"]) + " |", "|" + "---|" * len(tbl["columns"])]
            out += ["| " + " | ".join(str(c) for c in row) + " |" for row in tbl["rows"]]
    return "\n".join(out) + "\n"


def write_md() -> None:
    RUNS_MD.write_text(render())


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("job_dir", nargs="?", help="Harbor job dir, e.g. jobs/2026-11-15__06-48-21")
    ap.add_argument("--label", help="short label, e.g. sonnet55, opus55, oracle")
    ap.add_argument("--notes", default="", help="free text shown under the run in docs/RUNS.md")
    ap.add_argument("--run-id", help="default <label>_<job name>")
    ap.add_argument("--entry", help="JSON file with a ready entry (non-Harbor runs)")
    ap.add_argument("--replace", action="store_true", help="replace an entry with the same run_id")
    ap.add_argument("--render", action="store_true", help="only re-render docs/RUNS.md")
    a = ap.parse_args(argv)

    if a.render:
        write_md()
        print(f"rendered {_rel(RUNS_MD)}")
        return 0
    if a.entry:
        entry = json.loads(Path(a.entry).read_text())
        for k in ("run_id", "kind"):
            if k not in entry:
                sys.exit(f"--entry needs {k!r}")
        add(entry, a.replace)
        write_md()
        print(f"added {entry['run_id']} -> {_rel(INDEX)}, {_rel(RUNS_MD)}")
        return 0
    if not a.job_dir or not a.label:
        ap.error("give <job_dir> --label (or --entry / --render)")

    job = Path(a.job_dir).resolve()
    cfg = _load(job / "config.json")
    if cfg is None:
        sys.exit(f"{job} has no readable config.json: not a Harbor job dir")
    run_id = a.run_id or f"{a.label}_{cfg.get('job_name', job.name)}"
    dest = ARCHIVE / run_id
    if not a.replace and run_id in [r["run_id"] for r in load_index()["runs"]]:
        sys.exit(f"run_id {run_id!r} is already in {_rel(INDEX)} (use --replace)")
    if dest.exists():
        if (_load(dest / "config.json") or {}).get("job_name") != cfg.get("job_name"):
            sys.exit(f"{_rel(dest)} exists and holds a different job; choose another --run-id")
        print(f"{_rel(dest)} already holds this job: copy skipped")
    else:
        shutil.copytree(job, dest, symlinks=True)       # copy, never move: the job dir stays as Harbor left it
        print(f"copied {_rel(job)} -> {_rel(dest)}")
    entry = harbor_entry(dest, a.label, a.notes, run_id, dest) | {"source": _rel(job)}
    add(entry, a.replace)
    write_md()
    s = entry["summary"]
    print(f"recorded {run_id}: {s['n_trials']} trials, mean {_f(s['mean'])}, "
          + ", ".join(f"{k} {v['mean']:.3f}" for k, v in s["per_level"].items())
          + f"; build {entry['build']['matched_tags']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
