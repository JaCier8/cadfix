"""Solid validity and frozen interfaces. Generic."""
from __future__ import annotations

from cadfix.core.assembly import Region
from cadfix.core.registry import CheckContext, CheckResult, register


@register("valid_solid")
def valid_solid(ctx: CheckContext, parts) -> CheckResult:
    """Each listed part is one valid closed solid (OpenCascade check + a closed manifold tessellation)."""
    ok, metrics, details = True, {}, []
    for n in parts:
        shape = ctx.current.parts[n].shape
        problems = []
        try:
            solids = shape.Solids()
            if len(solids) != 1:
                problems.append(f"{len(solids)} solids, expected 1")
            if not shape.isValid():
                problems.append("OpenCascade validity check failed")
            ctx.current.parts[n].mesh  # noqa: B018  (tessellation must be a closed manifold)
        except Exception as e:  # noqa: BLE001 - any failure here means "not a valid solid"
            problems.append(f"cannot tessellate: {str(e)[:120]}")
        metrics[n] = "ok" if not problems else "; ".join(problems)
        if problems:
            ok = False
            details.append(f"{n}: {'; '.join(problems)}")
    if ok:
        details.append(f"valid single solids: {', '.join(parts)}")
    return CheckResult(ok, None, metrics, details)


@register("interface_frozen")
def interface_frozen(ctx: CheckContext, regions, tol_mm3: float = 0.01) -> CheckResult:
    """Inside each region the part's material is exactly the original's (nothing removed, nothing added):
    symmetric difference volume <= tol_mm3. regions: [{"name", "part", "region"}]."""
    ok, metrics, details = True, {}, []
    for r in regions:
        n = r["part"]
        if ctx.current.parts[n].shape is ctx.original.parts[n].shape:
            metrics[r["name"]] = 0.0
            continue
        zone = Region.from_dict(r["region"]).to_manifold()
        a = ctx.original.parts[n].mesh ^ zone
        b = ctx.current.parts[n].mesh ^ zone
        diff = float((a - b).volume()) + float((b - a).volume())
        metrics[r["name"]] = round(diff, 5)
        if diff > tol_mm3:
            ok = False
            details.append(f"{r['name']} ({n}): material changed by {diff:.4f} mm3 (limit {tol_mm3})")
    if ok:
        details.append(f"all {len(regions)} interface regions unchanged")
    return CheckResult(ok, None, metrics, details)
