"""Look at any run with one command: opens (building if needed) the 3D viewer of a run.

  python -m cadfix.show [PATH|latest] [--rebuild] [--no-open] [--print] [--task T]

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


def write_index(base: Path, runs: list[Path], rebuild=False, task_override=None) -> Path:
    rows = []
    for r in runs:
        err = ""
        try:
            viewer = ensure_viewer(r, rebuild, task_override)
        except Exception as e:  # noqa: BLE001 - one broken run must not hide the others
            viewer, err = None, f"{type(e).__name__}: {e}"
            _log(f"warning: {r}: {err}")
        info = _load(viz_dir_of(r) / "viz.json") or {}
        g = _load((r / "verifier" if _is_trial(r) else r) / "grade.json") or {}
        level = info.get("level") or g.get("level") or ""
        seed = info.get("seed") if info.get("seed") is not None else g.get("seed", "")
        rw = reward_of(r)
        link = (f'<a href="{html.escape(os.path.relpath(viewer, base).replace(os.sep, "/"))}">open</a>'
                if viewer else f"<span class=err>{html.escape(err or 'no viewer')}</span>")
        rows.append(f"<tr><td>{html.escape(str(r.relative_to(base)))}</td><td>{html.escape(str(level))}</td>"
                    f"<td>{html.escape(str(seed))}</td><td class=num>{'' if rw is None else f'{rw:.3f}'}</td>"
                    f"<td>{html.escape(_playback_status(info))}</td><td>{link}</td></tr>")
    doc = ("<!doctype html><meta charset=utf-8><title>cadfix runs</title>"
           "<style>body{font:14px system-ui;margin:2em}table{border-collapse:collapse}"
           "td,th{border:1px solid #8884;padding:4px 10px;text-align:left}.num{text-align:right}.err{color:#c33}"
           "</style>"
           f"<h1>{html.escape(base.name)}</h1><table><tr><th>run</th><th>level</th><th>seed</th><th>reward</th>"
           "<th>playback</th><th>viewer</th></tr>" + "".join(rows) + "</table>")
    out = base / "index.html"
    out.write_text(doc)
    return out


# ---------------------------------------------------------------- resolve
def resolve(path: str | None, rebuild=False, task_override=None) -> Path:
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
    return write_index(p, runs, rebuild, task_override)


def in_docker() -> bool:
    return Path("/.dockerenv").exists()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", help="run dir, job dir, viz dir, viewer.html, or 'latest' (default)")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the viewer even if it exists")
    ap.add_argument("--no-open", action="store_true", help="do not launch a browser")
    ap.add_argument("--print", dest="print_", action="store_true", help="print the path of the html file (stdout)")
    ap.add_argument("--task", help="dir with task/ and pristine/ (override automatic lookup)")
    a = ap.parse_args(argv)
    try:
        f = resolve(a.path, a.rebuild, a.task)
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
