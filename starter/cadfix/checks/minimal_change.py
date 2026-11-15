"""Minimal-change score (volume_change): changed volume compared with the best known fix of the task. Generic.

VERIFIER ONLY: the score needs a private reference value (reference_mm3) and the level's factors, so this module
is not copied into the agent's container (cadfix/harbor/build.py). The agent measures its own changed volume
with the env tool `changed_volume` (same helper, cadfix.checks.change.changed)."""
from __future__ import annotations

from cadfix.checks.change import changed
from cadfix.core.registry import CheckContext, CheckResult, register
from cadfix.core.reward import ratio_score


@register("volume_change")
def volume_change(ctx: CheckContext, parts, full_factor: float, zero_factor: float,
                  reference_mm3: float | None = None) -> CheckResult:
    """Changed volume (removed + added, all listed parts) compared with the best known fix of the task
    (reference_mm3): full points up to full_factor x, zero at zero_factor x, linear in between. Without the
    reference the score is not computed; the volume is reported."""
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
