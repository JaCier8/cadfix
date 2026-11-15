"""Keep-in / keep-out zones. Generic: zones come from the assembly (task.json)."""
from __future__ import annotations

from cadfix.core.registry import CheckContext, CheckResult, register


def _zone_mesh(ctx: CheckContext, zone):
    key = ("zone_mesh", zone.name)
    if key not in ctx.original_cache:
        ctx.original_cache[key] = zone.region.to_manifold()
    return ctx.original_cache[key]


@register("keep_in")
def keep_in(ctx: CheckContext, min_fill: float = 0.99, zones=None) -> CheckResult:
    """Every keep-in zone keeps >= min_fill of the original material of its part inside the zone."""
    ok, metrics, details = True, {}, []
    for z in ctx.current.zones:
        if z.kind != "keep_in" or (zones and z.name not in zones):
            continue
        zm = _zone_mesh(ctx, z)
        key = ("keep_in_orig", z.name)
        if key not in ctx.original_cache:
            ctx.original_cache[key] = float((ctx.original.parts[z.part].mesh ^ zm).volume())
        orig = ctx.original_cache[key]
        if ctx.current.parts[z.part].shape is ctx.original.parts[z.part].shape or orig <= 0:
            fill = 1.0
        else:
            fill = float((ctx.current.parts[z.part].mesh ^ zm).volume()) / orig
        metrics[z.name] = round(fill, 5)
        if fill < min_fill:
            ok = False
            details.append(f"{z.name} ({z.part}): {100 * fill:.2f} % of its material left (need >= {100 * min_fill:g} %)")
    if ok:
        details.append(f"all {len(metrics)} keep-in zones filled >= {100 * min_fill:g} %")
    return CheckResult(ok, None, metrics, details)


@register("keep_out")
def keep_out(ctx: CheckContext, tol_mm3: float = 1e-3, zones=None) -> CheckResult:
    """No new material of the listed parts (default: all editable parts) inside any keep-out zone, at the
    closed pose."""
    ok, metrics, details = True, {}, []
    for z in ctx.current.zones:
        if z.kind != "keep_out" or (zones and z.name not in zones):
            continue
        zm = _zone_mesh(ctx, z)
        for n in z.parts or ctx.current.editable:
            key = ("keep_out_orig", z.name, n)
            if key not in ctx.original_cache:
                ctx.original_cache[key] = float((ctx.original.parts[n].mesh ^ zm).volume())
            new = (ctx.original_cache[key] if ctx.current.parts[n].shape is ctx.original.parts[n].shape
                   else float((ctx.current.parts[n].mesh ^ zm).volume()))
            extra = new - ctx.original_cache[key]
            metrics[f"{z.name}/{n}"] = round(extra, 5)
            if extra > tol_mm3:
                ok = False
                details.append(f"{z.name}: {extra:.4f} mm3 of {n} inside (limit {tol_mm3})")
    if ok:
        details.append(f"keep-out zones empty ({', '.join(sorted({k.split('/')[0] for k in metrics}))})")
    return CheckResult(ok, None, metrics, details)
