"""Playback data: the model after each step of an agent's episode. Generic. Humans only (never in the agent image).

  python -m cadfix.playback --task-dir T --pristine P --submitted S --out DIR [--time-budget 240]

S holds what the episode left behind (actions.jsonl, parts/, maybe snapshots/). Frames come from a REPLAY: every
edit call logged in actions.jsonl (EDIT_TOOLS, undo included) is re-applied by a fresh cadfix.env.Env to the
verifier's own pristine parts, so the agent cannot fake geometry through its files. Queries and checks are not
re-run; they are caption-only steps. The final replayed parts are compared with the graded submission
(grade.load_submission); status is "reproduced" | "mismatch" | "no_log" | "replay_error" | "truncated". When the
replay does not reproduce the submission, frames built from <S>/snapshots/NNN_<tool>/<part>.step are appended
(flagged "trusted": false, the agent could have written those files) and the graded state is the last frame.

Writes DIR/playback.json and DIR/frame_NNN.glb (closed pose, all parts, nodes `<part>`, plus for editable parts
`<part>__removed` / `<part>__added` cumulative vs the original and `<part>__step_removed` / `<part>__step_added`
for what changed since the previous frame). The agent log is agent-controlled: bad lines are skipped, every step is
guarded, and the number of steps, edit frames and seconds are capped. Never raises for bad input.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path

from cadfix.core import kernel
from cadfix.core.assembly import Assembly
from cadfix.env.env import EDIT_TOOLS, Env
from cadfix.grade import load_submission
from cadfix.viz import ADDED, REMOVED, _color, _trimesh, diff_meshes

MAX_STEPS = 300
MAX_EDIT_FRAMES = 80
STEP_REMOVED, STEP_ADDED = (1.0, 0.9, 0.1), (0.1, 0.9, 0.95)
SHORT = 160
SKIP_ERRORS = ("tool-call limit", "already submitted")     # calls the original env refused; a fresh env would not


# ---------------------------------------------------------------- captions
def _num(v) -> str:
    return f"{v:.4g}" if isinstance(v, float) else str(v)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def args_short(tool: str, args) -> str:
    if not isinstance(args, dict):
        return f"{tool} (bad args)"
    parts = [str(tool)]
    if isinstance(args.get("part"), str):
        parts.append(args["part"])
    for k, v in args.items():
        if k in ("part", "depth_from", "depth_to"):
            continue
        if _is_num(v):
            parts.append(f"{k}={_num(v)}")
        elif isinstance(v, str):
            parts.append(f"{k}={v[:30]}")
        elif isinstance(v, (list, tuple)) and v and all(_is_num(x) for x in v) and len(v) <= 3:
            parts.append(f"{k}=[{', '.join(_num(round(x, 2)) for x in v)}]")
        elif isinstance(v, (list, tuple)):
            parts.append(f"{k}[{len(v)}]")
    if _is_num(args.get("depth_from")) and _is_num(args.get("depth_to")):
        parts.append(f"depth {_num(args['depth_from'])}..{_num(args['depth_to'])}")
    return " ".join(parts)[:100]


def _scalars(d: dict, skip=(), n=4) -> str:
    out = []
    for k, v in d.items():
        if k in skip or len(out) >= n:
            continue
        if isinstance(v, bool) or _is_num(v) or v is None:
            out.append(f"{k}={_num(v)}")
        elif isinstance(v, str) and len(v) <= 24:
            out.append(f"{k}={v}")
        elif isinstance(v, list):
            out.append(f"{k}[{len(v)}]")
    return " ".join(out)


def result_short(tool: str, res) -> str:
    if not isinstance(res, dict):
        return str(res)[:SHORT]
    if res.get("error"):
        return ("error: " + str(res["error"]))[:SHORT]
    if tool == "measure":
        s = f"overlap {_num(res.get('overlap_mm3'))} mm3, min gap {_num(res.get('min_gap_mm'))} mm " \
            f"at {_num(res.get('joint_angle_deg'))} deg"
    elif tool == "run_check":
        m = res.get("metrics") if isinstance(res.get("metrics"), dict) else {}
        s = f"{res.get('id')} passed={res.get('passed')} score={_num(res.get('score'))} " + _scalars(m, n=3)
    elif tool == "test_fit":
        s = (f"gates_ok={res.get('gates_ok')} failed={res.get('failed_gates')} met={res.get('objective_met')} "
             f"progress={_num(res.get('objective_progress'))} printability={_num(res.get('printability'))}")
    elif tool in EDIT_TOOLS:
        s = "undone" if res.get("undone") else ""
        s = (s + f" removed {_num(res.get('removed_mm3'))} / added {_num(res.get('added_mm3'))} mm3 "
             f"(edit {res.get('edits_so_far')})").strip()
    elif tool == "submit":
        s = "submitted"
    else:
        s = _scalars(res, skip=("note",))
    return s.strip()[:SHORT]


# ---------------------------------------------------------------- geometry
def _tol(vol: float) -> float:
    return max(1e-3, 1e-6 * vol)


def _diff_vs(a: Assembly, b: Assembly) -> dict:
    """{editable part: [removed, added]} going from a to b, only the parts that differ beyond the tolerance."""
    out = {}
    for n in a.editable:
        r, d = kernel.changed_volume(a.parts[n].mesh, b.parts[n].mesh)
        if max(r, d) > _tol(float(a.parts[n].mesh.volume())):
            out[n] = [round(r, 4), round(d, 4)]
    return out


def _frame_glb(asm: Assembly, original: Assembly, prev: Assembly | None, path: Path) -> dict:
    """Write one closed-pose GLB; return {part: {removed, added, step_removed, step_added}} (mm3)."""
    import trimesh
    j = asm.joint
    angle = j.range_deg[0]
    pose = lambda n, m: kernel.rotate(m, j.axis_point, j.axis_direction, angle) if n in j.moving else m
    scene = trimesh.Scene()
    for n, p in asm.parts.items():
        scene.add_geometry(_trimesh(pose(n, p.mesh), _color(p, n in j.moving)), node_name=n, geom_name=n)
    stats = {}
    for n in asm.editable:
        cur = asm.parts[n]
        st = {}
        pairs = [("", original.parts[n], REMOVED, ADDED)]
        if prev is not None:
            pairs.append(("step_", prev.parts[n], STEP_REMOVED, STEP_ADDED))
        for pre, base, c_rem, c_add in pairs:
            rem_v, add_v = kernel.changed_volume(base.mesh, cur.mesh)
            st[pre + "removed"], st[pre + "added"] = round(rem_v, 4), round(add_v, 4)
            meshes = diff_meshes(base.shape, cur.shape) if max(rem_v, add_v) > kernel.VOL_EPS else (None, None)
            for suffix, m, rgb in (("removed", meshes[0], c_rem), ("added", meshes[1], c_add)):
                if m is not None:
                    node = f"{n}__{pre}{suffix}"
                    scene.add_geometry(_trimesh(pose(n, m), rgb), node_name=node, geom_name=node)
        stats[n] = st
    scene.export(str(path))
    return stats


class _Frames:
    def __init__(self, original: Assembly, out: Path):
        self.original, self.out, self.items = original, out, []
        self.prev: Assembly | None = None

    def add(self, asm: Assembly, after_step: int, label: str, trusted: bool = True, **extra) -> int:
        idx = len(self.items)
        name = f"frame_{idx:03d}.glb"
        parts = _frame_glb(asm, self.original, self.prev, self.out / name)
        self.items.append({"index": idx, "after_step": after_step, "label": label, "trusted": trusted,
                           "file": name, "parts": parts, **extra})
        self.prev = asm
        return idx


# ---------------------------------------------------------------- log
def _read_log(submitted: Path) -> list[dict]:
    f = submitted / "actions.jsonl"
    if not f.exists():
        return []
    rows = []
    try:
        lines = f.read_text(errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and isinstance(d.get("tool"), str):
            rows.append(d)
    return rows


def _snapshot_frames(submitted: Path, original: Assembly, log_steps: list[dict]) -> list[tuple]:
    """[(label, Assembly, step number)] from submitted/snapshots/NNN_<tool>/ (agent-written: untrusted)."""
    root = submitted / "snapshots"
    if not root.is_dir():
        return []
    edit_steps = [s["n"] for s in log_steps if s["is_edit"] and s["edit_ok"] is not False]
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir())[:MAX_EDIT_FRAMES + 1]:
        num, _, tool = d.name.partition("_")
        if not num.isdigit() or int(num) == 0:
            continue
        shapes = {}
        for n in original.editable:
            f = d / f"{n}.step"
            try:
                if f.exists():
                    shapes[n] = kernel.import_step(f)
            except Exception:  # noqa: BLE001 - agent-controlled file
                pass
        if shapes:
            k = int(num)
            out.append((f"snapshot {d.name} (unverified)", original.with_shapes(shapes),
                        edit_steps[k - 1] if 0 < k <= len(edit_steps) else (edit_steps[-1] if edit_steps else 0)))
    return out


# ---------------------------------------------------------------- main
def build_playback(task_dir, pristine_dir, submitted_dir, out_dir, time_budget_s: float = 240) -> dict:
    t0 = time.perf_counter()
    task_dir, pristine_dir, submitted_dir, out = Path(task_dir), Path(pristine_dir), Path(submitted_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    original = Assembly.load(task_dir, pristine_dir / "parts")
    graded, notes = load_submission(original, submitted_dir)
    rows = _read_log(submitted_dir)
    frames = _Frames(original, out)
    frames.add(original, 0, "start (original)")
    status, message, steps = "reproduced", None, []
    log_steps = []                                    # steps as built so far (also used for snapshot mapping)
    cur = original
    notes_list = []
    if len(rows) > MAX_STEPS:
        notes_list.append(f"log has {len(rows)} calls; only the first {MAX_STEPS} are shown")
        rows = rows[:MAX_STEPS]
    if not rows:
        status = "no_log"

    tmp = Path(tempfile.mkdtemp(prefix="cadfix_playback_"))
    env = None
    try:
        if rows:
            try:
                tdir = tmp / "task"
                tdir.mkdir()
                for f in ("task.json", "spec.json"):
                    shutil.copy(task_dir / f, tdir / f)
                shutil.copytree(pristine_dir / "parts", tdir / "parts")
                env = Env(tdir, tmp / "out", max_calls=10 ** 9, snapshots=False, resume=False)
                cur = env.current
            except Exception as e:  # noqa: BLE001
                status, message = "replay_error", f"cannot start the replay environment: {type(e).__name__}: {e}"[:300]
        last_check = None
        cur_frame, edit_frames, stopped = 0, 0, False
        for i, row in enumerate(rows):
            tool, args, res = row["tool"], row.get("args"), row.get("result")
            n = row["n"] if isinstance(row.get("n"), int) and not isinstance(row.get("n"), bool) else i + 1
            secs = row.get("seconds")
            is_edit = tool in EDIT_TOOLS
            step = {"n": n, "tool": tool[:60], "args_short": args_short(tool, args),
                    "result_short": result_short(tool, res), "seconds": secs if _is_num(secs) else None,
                    "frame": cur_frame, "is_edit": is_edit, "edit_ok": None}
            logged_err = res.get("error") if isinstance(res, dict) else None
            if tool in ("run_check", "test_fit") and isinstance(res, dict) and not logged_err:
                last_check = {"step": n, "tool": tool, "summary": step["result_short"]}
            if is_edit and env is not None and status in ("reproduced",) and not stopped \
                    and not (isinstance(logged_err, str) and any(s in logged_err for s in SKIP_ERRORS)):
                if time.perf_counter() - t0 > time_budget_s or edit_frames >= MAX_EDIT_FRAMES:
                    stopped = True
                    status = "truncated"
                    message = ("time budget exhausted" if edit_frames < MAX_EDIT_FRAMES
                               else f"more than {MAX_EDIT_FRAMES} edit frames")
                else:
                    try:
                        if not isinstance(args, dict) or not all(isinstance(k, str) for k in args):
                            raise ValueError("args is not an object")
                        r = env.call(tool, **args)
                        ok = isinstance(r, dict) and r.get("ok") is True
                        step["edit_ok"] = ok
                        if ok:
                            cur = env.current
                            edit_frames += 1
                            cur_frame = frames.add(cur, n, f"after {step['args_short']}")
                            step["frame"] = cur_frame
                        else:
                            step["replay_error"] = str((r or {}).get("error"))[:SHORT]
                    except Exception as e:  # noqa: BLE001 - agent-controlled call
                        step["edit_ok"] = False
                        step["replay_error"] = f"{type(e).__name__}: {e}"[:SHORT]
            elif is_edit:
                step["edit_ok"] = False if logged_err else None
            step["last_check"] = last_check
            steps.append(step)
            log_steps.append(step)

        # compare with what was graded
        mism = _diff_vs(cur, graded) if status in ("reproduced", "truncated") else {}
        if status == "reproduced" and mism:
            status = "mismatch"
            message = "replayed parts differ from the submission (removed/added mm3, replay -> graded): " + json.dumps(mism)
        if status in ("replay_error", "mismatch"):
            for label, asm, after in _snapshot_frames(submitted_dir, original, log_steps):
                frames.add(asm, after, label, trusted=False, fallback=True)
        graded_diff = _diff_vs(frames.prev, graded) if frames.prev is not None else {}
        if graded_diff:
            frames.add(graded, steps[-1]["n"] if steps else 0, "graded submission")
    except Exception as e:  # noqa: BLE001 - never raise for bad input
        status, message = "replay_error", f"{type(e).__name__}: {e}"[:300]
        try:
            if not frames.items or frames.items[-1]["label"] != "graded submission":
                frames.add(graded, steps[-1]["n"] if steps else 0, "graded submission")
        except Exception:  # noqa: BLE001
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    data = {"status": status, "message": message, "notes": notes_list, "submission": notes,
            "level": original.meta.get("level"), "seed": original.meta.get("seed"),
            "pose": {"joint_angle_deg": original.joint.range_deg[0], "name": "closed"},
            "editable": list(original.editable), "steps": steps, "frames": frames.items,
            "seconds": round(time.perf_counter() - t0, 2)}
    (out / "playback.json").write_text(json.dumps(data, indent=1, default=str))
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task-dir", required=True)
    ap.add_argument("--pristine", required=True)
    ap.add_argument("--submitted", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--time-budget", type=float, default=240)
    a = ap.parse_args(argv)
    d = build_playback(a.task_dir, a.pristine, a.submitted, a.out, a.time_budget)
    print(f"playback: status={d['status']} steps={len(d['steps'])} frames={len(d['frames'])} seconds={d['seconds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
