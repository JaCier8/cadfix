"""Collision at a fixed joint pose. Generic."""
from __future__ import annotations

from cadfix.core import kernel
from cadfix.core.registry import CheckContext, CheckResult, register


@register("collision_free")
def collision_free(ctx: CheckContext, angle_deg: float = 0.0, moving=None, fixed=None,
                   overlap_eps_mm3: float = kernel.VOL_EPS) -> CheckResult:
    """With the joint at angle_deg, no moving part overlaps a fixed part by more than overlap_eps_mm3
    (touching is allowed)."""
    j = ctx.current.joint
    moving, fixed = list(moving or j.moving), list(fixed or j.fixed)
    hits = []
    for mv in moving:
        m = kernel.rotate(ctx.current.parts[mv].mesh, j.axis_point, j.axis_direction, angle_deg)
        for fx in fixed:
            vol, bb = kernel.intersection(m, ctx.current.parts[fx].mesh)
            if vol > overlap_eps_mm3:
                hits.append({"moving": mv, "fixed": fx, "volume": round(vol, 6), "bbox": bb})
    details = ([f"{h['moving']} x {h['fixed']}: overlap {h['volume']:.4f} mm3, bbox {h['bbox'][0]} .. {h['bbox'][1]}"
                for h in hits] or [f"no collision at {angle_deg:g} deg"])
    return CheckResult(not hits, None, {"angle_deg": angle_deg, "collisions": hits}, details)
