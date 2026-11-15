"""Sweep checks over a revolute joint. Generic: the scenario supplies parts, axis and thresholds."""
from __future__ import annotations

import time

from cadfix.core import kernel
from cadfix.core.registry import CheckContext, CheckResult, register
from cadfix.core.reward import sweep_progress


def joint_steps(start: float, stop: float, step: float) -> list[float]:
    n = int(round((stop - start) / step))
    return [round(start + i * step, 6) for i in range(n + 1)]


def opening_check(moving: dict, fixed: dict, axis_point, axis_direction, range_deg, step_deg: float,
                  overlap_eps_mm3: float, clearance_mm: float, clearance_from_deg: float, search_mm: float) -> dict:
    """Rotate `moving` about the axis over range_deg in step_deg steps.

    Rules: overlap <= overlap_eps_mm3 at every step (touching allowed); gap >= clearance_mm at every step from
    clearance_from_deg. Returns met, ok_until (largest angle up to which both rules hold, None if the first step
    fails), first_fail, min_clearance / min_clearance_at over the clearance steps (gaps capped at search_mm),
    first_overlap_deg, any_overlap, steps (per-step rows) and seconds.
    """
    steps = joint_steps(range_deg[0], range_deg[1], step_deg)
    t0 = time.perf_counter()
    res = kernel.clearance_sweep(moving, fixed, axis_point, axis_direction, steps, search_mm)
    seconds = time.perf_counter() - t0
    ok_until, first_fail = None, None
    for r in res:
        ok = r["overlap"] <= overlap_eps_mm3 and (
            r["angle"] < clearance_from_deg - 1e-9 or r["gap"] >= clearance_mm - 1e-9)
        if not ok:
            first_fail = r
            break
        ok_until = r["angle"]
    clear = [r for r in res if r["angle"] >= clearance_from_deg - 1e-9]
    worst = min(clear, key=lambda r: (r["gap"], -r["overlap"]))
    overl = [r["angle"] for r in res if r["overlap"] > overlap_eps_mm3]
    return {"met": first_fail is None, "ok_until": ok_until, "first_fail": first_fail,
            "min_clearance": worst["gap"], "min_clearance_at": worst["angle"],
            "first_overlap_deg": overl[0] if overl else None, "any_overlap": bool(overl),
            "steps": res, "seconds": seconds}


def in_frame(meshes: dict, axis_point, axis_direction, frame):
    """Rotate meshes and the axis into an evaluation frame (rows = frame axes in world). Distances and volumes
    do not change; manifold's distance queries are much faster when flat faces are axis-aligned."""
    if frame is None:
        return meshes, axis_point, axis_direction
    m = kernel.frame_matrix(frame)
    return ({n: kernel.transform_mesh(x, m) for n, x in meshes.items()},
            kernel.apply_points(m, axis_point)[0].tolist(), kernel.apply_dirs(m, axis_direction)[0].tolist())


def _sweep(asm, moving, fixed, rng, step, eps, clearance, clear_from, search, frame) -> dict:
    j = asm.joint
    meshes, pt, d = in_frame(asm.meshes(list(moving) + list(fixed)), j.axis_point, j.axis_direction, frame)
    return opening_check({n: meshes[n] for n in moving}, {n: meshes[n] for n in fixed}, pt, d, rng, step, eps,
                         clearance, clear_from, search)


@register("sweep_clearance")
def sweep_clearance(ctx: CheckContext, clearance_mm: float, clearance_from_deg: float, overlap_eps_mm3: float = 1e-3,
                    search_mm: float = 0.35, moving=None, fixed=None, range_deg=None, step_deg=None, frame=None,
                    angle_weight: float = 0.5) -> CheckResult:
    """Rotate the joint's moving parts over its range: no overlap above overlap_eps_mm3 at any step, clearance
    >= clearance_mm at every step from clearance_from_deg. Score = progress vs the original:
    angle_weight * angle progress + (1 - angle_weight) * clearance progress (1 when met)."""
    j = ctx.current.joint
    moving = tuple(moving or j.moving)
    fixed = tuple(fixed or j.fixed)
    rng = tuple(range_deg or j.range_deg)
    step = float(step_deg or j.step_deg)
    args = (moving, fixed, rng, step, overlap_eps_mm3, clearance_mm, clearance_from_deg, search_mm,
            None if frame is None else tuple(map(tuple, frame)))
    key = ("sweep_clearance", args)
    if key not in ctx.original_cache:
        ctx.original_cache[key] = _sweep(ctx.original, *args)
    orig = ctx.original_cache[key]
    cur = orig if not ctx.changed_parts(list(moving) + list(fixed)) else _sweep(ctx.current, *args)
    prog = 1.0 if cur["met"] else sweep_progress(cur["ok_until"], orig["ok_until"], rng[1], cur["min_clearance"],
                                                 clearance_mm, cur["any_overlap"], angle_weight)
    ff = cur["first_fail"]
    details = [f"{'PASS' if cur['met'] else 'FAIL'}: rules hold up to {cur['ok_until']} deg "
               f"(original: {orig['ok_until']} deg), min clearance {cur['min_clearance']:.3f} mm at "
               f"{cur['min_clearance_at']} deg (from {clearance_from_deg} deg; gaps >= {search_mm} reported as {search_mm})"]
    if ff:
        details.append(f"first failing step {ff['angle']} deg: clearance {ff['gap']:.3f} mm (need >= {clearance_mm} "
                       f"from {clearance_from_deg} deg), overlap {ff['overlap']:.4f} mm3 (limit {overlap_eps_mm3}), "
                       f"pair {list(ff['pair']) if ff['pair'] else None}")
    return CheckResult(cur["met"], round(float(prog), 6), {
        "ok_until": cur["ok_until"], "original_ok_until": orig["ok_until"], "min_clearance": round(cur["min_clearance"], 4),
        "min_clearance_at": cur["min_clearance_at"], "first_overlap_deg": cur["first_overlap_deg"],
        "any_overlap": cur["any_overlap"],
        "first_fail": None if ff is None else {"angle": ff["angle"], "gap": round(ff["gap"], 4),
                                               "overlap": round(ff["overlap"], 6),
                                               "pair": list(ff["pair"]) if ff["pair"] else None},
        "sweep_seconds": round(cur["seconds"], 3)}, details)
