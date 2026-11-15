"""Sweep checks over a revolute joint. Generic: the scenario supplies parts, axis and thresholds."""
from __future__ import annotations

import time

from cadfix.core import kernel


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
