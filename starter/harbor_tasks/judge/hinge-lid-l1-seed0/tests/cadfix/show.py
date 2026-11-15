"""Look at any run with one command: opens (building if needed) the 3D viewer of a run.

  python -m cadfix.show [PATH|latest] [--rebuild] [--no-build] [--no-open] [--print] [--task T]

PATH: a run_eval result dir (results/<agent>/<L>/seed_NNNN), a Harbor trial dir (jobs/<job>/<trial>, or its
verifier/), a dir of several runs (jobs/<job>, results/<agent>: an index.html is written and opened), a viz dir
or a viewer.html. No PATH = the most recently modified run under jobs/ and results/.
Progress goes to stderr; with --print stdout is just the path (relative to the repo root inside Docker).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import tempfile
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEARCH = ("jobs", "results")


class ShowError(Exception):
    pass


def _log(*a):
    print(*a, file=sys.stderr)


def _load(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- run discovery
def _is_trial(d: Path) -> bool:
    return (d / "verifier" / "grade.json").exists() or (d / "verifier" / "submitted").is_dir()


def _is_result(d: Path) -> bool:
    return (d / "grade.json").exists() and (d / "parts").is_dir()


def _run_kind(d: Path):
    if _is_trial(d):
        return "trial"
    if _is_result(d):
        return "result"
    if d.name == "verifier" and ((d / "grade.json").exists() or (d / "submitted").is_dir()):
        return "verifier"
    return None


def find_runs(base: Path) -> list[Path]:
    """Run dirs (trial or result) below base, sorted by path."""
    runs = []
    for g in sorted(base.rglob("grade.json")):
        d = g.parent
        if "viz" in d.parts[len(base.parts):] or "submitted" in d.parts[len(base.parts):]:
            continue
        if d.name == "verifier":
            d = d.parent
        if d not in runs and _run_kind(d):
            runs.append(d)
    return runs


def latest_run(root: Path | None = None) -> Path:
    root = root or ROOT
    cands = []
    for s in SEARCH:
        if (root / s).is_dir():
            cands += find_runs(root / s)
    if not cands:
        raise ShowError("no runs found under jobs/ or results/")
    return max(cands, key=lambda d: (d / "grade.json" if (d / "grade.json").exists() else d / "verifier" / "grade.json").stat().st_mtime)


def viz_dir_of(run: Path) -> Path:
    return (run / "verifier" if _is_trial(run) else run) / "viz"


def reward_of(run: Path):
    base = run / "verifier" if _is_trial(run) else run
    g = _load(base / "grade.json")
    if isinstance(g, dict) and g.get("reward") is not None:
        return g["reward"]
    try:
        return float((base / "reward.txt").read_text().strip())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- building
def _find_dir(rel: str) -> Path | None:
    p = Path(rel)
    for c in ([p] if p.is_absolute() else [Path.cwd() / p, ROOT / p]):
        if c.is_dir():
            return c
    return None


def _task_pristine(run: Path, task_override: str | None):
    """(task_dir, pristine_dir) for a run."""
    if task_override:
        t = Path(task_override)
        if (t / "task").is_dir():
            return t / "task", t / "pristine"
        raise ShowError(f"--task {t}: expected a dir with task/ and pristine/")
    if _is_trial(run):
        cfg = _load(run / "config.json") or {}
        tp = (cfg.get("task") or {}).get("path")
        if not tp:
            raise ShowError(f"{run}/config.json has no task.path; pass --task <dir with task/ and pristine/>")
        tdir = _find_dir(tp)
        if tdir is None or not (tdir / "tests" / "task").is_dir():
            raise ShowError(f"Harbor task {tp} (from {run}/config.json) not found or has no tests/task; "
                            "rebuild it with the cadfix.harbor.build command from CLAUDE.md")
        return tdir / "tests" / "task", tdir / "tests" / "pristine"
    m = re.fullmatch(r"seed_(\d+)", run.name)
    if not m or not re.fullmatch(r"L\d+", run.parent.name):
        raise ShowError(f"cannot infer level/seed from {run}; pass --task output/tasks/<L>/seed_NNNN")
    d = ROOT / "output" / "tasks" / run.parent.name / run.name
    if not (d / "task").is_dir():
        raise ShowError(f"task {d} missing; create it with: python -m scenarios.hinge_lid.task "
                        f"--level {run.parent.name} --seeds {int(m.group(1))}  (or pass --task)")
    return d / "task", d / "pristine"


def build(run: Path, task_override: str | None = None) -> Path:
    """Build <run>/viz (or <run>/verifier/viz) and return viewer.html."""
    from cadfix import grade, viz
    task, pristine = _task_pristine(run, task_override)
    out = viz_dir_of(run)
    base = run / "verifier" if _is_trial(run) else run
    report = _load(base / "grade.json")
    tmp = None
    try:
        if _is_trial(run):
            tmp = Path(tempfile.mkdtemp(prefix="cadfix_show_"))
            sub = tmp / "submitted"
            shutil.copytree(base / "submitted", sub)
            for f in ("actions.jsonl", "episode.json"):
                if (base / f).exists():
                    shutil.copy(base / f, sub / f)
        else:
            sub = run
        if report is None:
            _log("grading ...")
            report = grade.grade(task, pristine, sub)
            (base / "grade.json").write_text(json.dumps(report, indent=2, default=str))
        _log(f"building viewer for {run} ...")
        viz.visualize(task, pristine, sub, out, report=report)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    return out / "viewer.html"


def ensure_viewer(run: Path, rebuild=False, task_override=None) -> Path:
    v = viz_dir_of(run) / "viewer.html"
    if v.exists() and not rebuild:
        return v
    return build(run, task_override)


# ---------------------------------------------------------------- index
def _playback_status(info) -> str:
    if not isinstance(info, dict):
        return ""
    pb = info.get("playback")
    if pb is None:
        return ""
    if isinstance(pb, dict):
        for k in ("status", "state", "ok"):
            if k in pb:
                return str(pb[k])
        return f"{len(pb)} keys"
    return str(pb)


def _parse_ts(x):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except ValueError:
        return None


def _seconds(d):
    if not isinstance(d, dict):
        return None
    a, b = _parse_ts(d.get("started_at")), _parse_ts(d.get("finished_at"))
    return (b - a).total_seconds() if a and b else None


def _strip(pb: dict | None) -> tuple[str, int, int, int]:
    """(per-step codes e=edit ok, f=failed edit, c=check, o=other; steps; edits; failed edits) from playback.json."""
    steps = (pb or {}).get("steps")
    if not isinstance(steps, list):
        return "", 0, 0, 0
    codes = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        if s.get("is_edit"):
            codes.append("f" if s.get("edit_ok") is False else "e")
        else:
            codes.append("c" if s.get("tool") == "run_check" else "o")
    return "".join(codes), len(codes), codes.count("e") + codes.count("f"), codes.count("f")


def run_record(base: Path, r: Path, viewer: Path | None, err: str = "") -> dict:
    """One JSON-able record per run for the index page (every field degrades gracefully when data is missing)."""
    trial = _is_trial(r)
    rb = r / "verifier" if trial else r
    vdir = viz_dir_of(r)
    info = _load(vdir / "viz.json") or {}
    g = _load(rb / "grade.json") or {}
    cfg = (_load(r / "config.json") or {}) if trial else {}
    res = (_load(r / "result.json") or {}) if trial else {}
    rel = r.relative_to(base) if r != base else Path(r.name)
    group = ("/".join(rel.parts[:-1]) if trial else "/".join(rel.parts[:-2])) or base.name
    task = (cfg.get("task") or {}).get("path") or ""
    task = Path(task).name if task else ""
    ag = cfg.get("agent") or res.get("agent_info") or {}
    agent = ag.get("name") or ""
    if agent and ag.get("model_name"):
        agent += f" ({ag['model_name']})"
    if not agent and not trial:
        agent = group.split("/")[0]
    level = info.get("level") or g.get("level") or ""
    if not level:
        m = re.search(r"\bL(\d+)\b|-l(\d+)-", f"{task} {r}")
        level = f"L{m.group(1) or m.group(2)}" if m else ""
    seed = info.get("seed") if info.get("seed") is not None else g.get("seed", "")
    if seed in ("", None):
        m = re.search(r"seed_?(\d+)", f"{task} {r.name}")
        seed = int(m.group(1)) if m else ""
    pbi = info.get("playback")
    pbj = _load(vdir / "playback" / "playback.json") if isinstance(pbi, dict) else None
    strip, nsteps, nedits, nfail = _strip(pbj)
    if not nsteps and isinstance(pbi, dict) and isinstance(pbi.get("steps"), int):
        nsteps = pbi["steps"]
    s1 = (g.get("checks") or {}).get("S1_opening")
    s1 = s1 if isinstance(s1, dict) else None
    editable = [(n, p) for n, p in (info.get("parts") or {}).items() if isinstance(p, dict) and p.get("editable")]
    parts = [{"name": n, "removed": p.get("removed") or 0, "added": p.get("added") or 0}
             for n, p in editable if (p.get("removed") or p.get("added"))]
    gp = rb / "grade.json"
    rec = {
        "id": str(rel).replace(os.sep, "/"), "group": group,
        "name": f"{task or group}/{r.name}" if trial else f"{group}/{level}/{r.name}",
        "level": str(level), "seed": seed, "task": task, "agent": agent, "reward": reward_of(r),
        "gates_ok": g.get("gates_ok") if isinstance(g.get("gates_ok"), bool) else None,
        "failed_gates": g.get("failed_gates") or [],
        "s1": s1.get("passed") if s1 and isinstance(s1.get("passed"), bool) else None,
        "s1_deg": (s1.get("metrics") or {}).get("ok_until") if s1 else None,
        "playback": _playback_status(info), "steps": nsteps if (nsteps or pbi) else None,
        "edits": nedits, "edit_fail": nfail, "strip": strip, "parts": parts, "hasparts": bool(editable),
        "seconds": _seconds(res.get("agent_execution")) if trial else None,
        "href": os.path.relpath(viewer, base).replace(os.sep, "/") if viewer else None,
        "grade_href": os.path.relpath(gp, base).replace(os.sep, "/") if gp.exists() else None,
    }
    if err:
        rec["error"] = err.splitlines()[0][:200]
    elif viewer is None:
        rec["missing"] = f"viewer missing - run scripts/view.sh {os.path.relpath(r, ROOT) if r.is_relative_to(ROOT) else r}"
    return rec


def write_index(base: Path, runs: list[Path], rebuild=False, task_override=None, build_missing=True) -> Path:
    """Write base/index.html: a single-file dashboard of all runs (cards, grouped by job / agent)."""
    from datetime import datetime

    from cadfix import show_index
    recs = []
    for r in runs:
        err, viewer = "", None
        if build_missing or rebuild:
            try:
                viewer = ensure_viewer(r, rebuild, task_override)
            except Exception as e:  # noqa: BLE001 - one broken run must not hide the others
                err = f"{type(e).__name__}: {e}"
                _log(f"warning: {r}: {err}")
        elif (viz_dir_of(r) / "viewer.html").exists():
            viewer = viz_dir_of(r) / "viewer.html"
        recs.append(run_record(base, r, viewer, err))
    src = os.path.relpath(base, ROOT) if base.is_relative_to(ROOT) else str(base)
    doc = show_index.render(recs, src, datetime.now().strftime("%Y-%m-%d %H:%M"), f"cadfix runs - {base.name}")
    out = base / "index.html"
    out.write_text(doc)
    return out


# ---------------------------------------------------------------- resolve
def resolve(path: str | None, rebuild=False, task_override=None, build_missing=True) -> Path:
    """Return the html file to show (viewer.html or index.html), building when needed."""
    if path in (None, "", "latest"):
        p = latest_run()
        _log(f"latest run: {p}")
    else:
        p = Path(path)
        if not p.exists() and not p.is_absolute() and (ROOT / p).exists():
            p = ROOT / p
        if not p.exists():
            raise ShowError(f"{path}: no such file or directory")
    p = p.resolve()
    if p.is_file():
        if p.suffix == ".html":
            return p
        raise ShowError(f"{p}: not a directory or .html file")
    if (p / "viewer.html").exists() and not rebuild:
        return p / "viewer.html"
    if p.name == "viz" and (p / "viz.json").exists() and not rebuild:
        return p / "viewer.html"
    if p.name == "verifier" and _run_kind(p):
        p = p.parent
    if p.name == "viz" and rebuild:
        p = p.parent.parent if p.parent.name == "verifier" else p.parent
    if _run_kind(p):
        return ensure_viewer(p, rebuild, task_override)
    runs = find_runs(p)
    if not runs:
        raise ShowError(f"{p}: no runs found (expected grade.json next to parts/ or in verifier/)")
    if len(runs) == 1 and runs[0] != p:
        return ensure_viewer(runs[0], rebuild, task_override)
    return write_index(p, runs, rebuild, task_override, build_missing)


def in_docker() -> bool:
    return Path("/.dockerenv").exists()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", help="run dir, job dir, viz dir, viewer.html, or 'latest' (default)")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the viewer even if it exists")
    ap.add_argument("--no-open", action="store_true", help="do not launch a browser")
    ap.add_argument("--print", dest="print_", action="store_true", help="print the path of the html file (stdout)")
    ap.add_argument("--no-build", action="store_true", help="index only: do not build missing viewers (cards say so)")
    ap.add_argument("--task", help="dir with task/ and pristine/ (override automatic lookup)")
    a = ap.parse_args(argv)
    try:
        f = resolve(a.path, a.rebuild, a.task, not a.no_build)
    except ShowError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    docker = in_docker()
    shown = os.path.relpath(f, ROOT) if docker and f.is_relative_to(ROOT) else str(f)
    if a.print_ or a.no_open or docker:
        print(shown)
    if not (a.print_ or a.no_open or docker):
        webbrowser.open(f.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
