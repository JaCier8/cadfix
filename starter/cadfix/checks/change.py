"""Changes vs the original: changed volume (minimal change) and the outer envelope. Generic."""
from __future__ import annotations

import numpy as np

from cadfix.core import kernel
from cadfix.core.registry import CheckContext, CheckResult, register
from cadfix.core.reward import ratio_score


def changed(ctx: CheckContext, n: str) -> tuple[float, float]:
    """(removed, added) mm3 of part n vs the original, cached per grading."""
    key = ("changed", n)
    if key not in ctx.cache:
        if ctx.current.parts[n].shape is ctx.original.parts[n].shape:
            ctx.cache[key] = (0.0, 0.0)
        else:
            ctx.cache[key] = kernel.changed_volume(ctx.original.parts[n].mesh, ctx.current.parts[n].mesh)
    return ctx.cache[key]


@register("volume_change")
def volume_change(ctx: CheckContext, parts, full_factor: float, zero_factor: float,
                  reference_mm3: float | None = None) -> CheckResult:
    """Changed volume (removed + added, all listed parts) compared with the best known fix of the task
    (reference_mm3): full points up to full_factor x, zero at zero_factor x, linear in between. Without the
    reference (the agent's own tools) the score is not computed; the volume is reported."""
    removed = added = orig_vol = 0.0
    for n in parts:
        r, a = changed(ctx, n)
        removed, added = removed + r, added + a
        orig_vol += float(ctx.original.parts[n].mesh.volume())
    total = removed + added
    metrics = {"removed_mm3": round(removed, 4), "added_mm3": round(added, 4), "changed_mm3": round(total, 4),
               "changed_pct": round(100.0 * total / orig_vol, 5)}
    line = (f"changed volume {total:.3f} mm3 (removed {removed:.3f}, added {added:.3f}) = "
            f"{metrics['changed_pct']:.4f} % of {', '.join(parts)}")
    if reference_mm3 is None:
        return CheckResult(True, None, metrics, [line, f"scored by the rule: full points within {full_factor:g}x of "
                                                       f"the best known fix for this task, zero at {zero_factor:g}x"])
    score = ratio_score(total, reference_mm3, full_factor, zero_factor)
    metrics |= {"ratio_to_reference": round(total / reference_mm3, 5), "score": round(score, 6)}
    return CheckResult(True, round(score, 6), metrics, [line + f" -> score {score:.3f}"])


def _extents(m, frame) -> np.ndarray:
    v, _ = kernel.mesh_arrays(m)
    p = v @ np.asarray(frame, dtype=float).T
    return np.vstack([p.min(axis=0), p.max(axis=0)])


@register("envelope")
def envelope(ctx: CheckContext, parts, frame, tol_mm: float = 0.5, max_change_pct: float = 15.0) -> CheckResult:
    """Not rebuilt: along each frame axis the part's extent (min and max) moves by <= tol_mm, and its changed
    volume (removed + added) is <= max_change_pct of the original volume."""
    ok, metrics, details = True, {}, []
    for n in parts:
        if ctx.current.parts[n].shape is ctx.original.parts[n].shape:
            metrics[n] = {"max_shift_mm": 0.0, "changed_pct": 0.0}
            continue
        e0, e1 = _extents(ctx.original.parts[n].mesh, frame), _extents(ctx.current.parts[n].mesh, frame)
        shift = float(np.abs(e1 - e0).max())
        r, a = changed(ctx, n)
        pct = 100.0 * (r + a) / float(ctx.original.parts[n].mesh.volume())
        metrics[n] = {"max_shift_mm": round(shift, 4), "changed_pct": round(pct, 4)}
        if shift > tol_mm:
            ok = False
            details.append(f"{n}: outer envelope moved by {shift:.3f} mm (limit {tol_mm})")
        if pct > max_change_pct:
            ok = False
            details.append(f"{n}: {pct:.2f} % of its volume changed (limit {max_change_pct:g} %)")
    if ok:
        details.append(f"envelopes within {tol_mm} mm, volume changes <= {max_change_pct:g} %")
    return CheckResult(ok, None, metrics, details)
