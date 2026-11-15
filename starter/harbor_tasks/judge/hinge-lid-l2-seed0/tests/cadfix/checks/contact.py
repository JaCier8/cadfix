"""Contact band between two parts at the closed pose. Generic."""
from __future__ import annotations

from cadfix.core import kernel
from cadfix.core.registry import CheckContext, CheckResult, register


@register("contact_width")
def contact_width(ctx: CheckContext, lower: str, upper: str, plane_point, plane_normal, min_width_mm: float,
                  tol_mm: float = 2e-3) -> CheckResult:
    """Contact region in the plane (point, normal) between `lower` (faces facing +normal) and `upper` (faces
    facing -normal): its narrowest width must be >= min_width_mm, i.e. eroded by min_width_mm / 2 it still forms
    a closed ring. Width measured as twice the largest erosion that keeps a closed ring (0.001 mm). Faces within
    tol_mm of the plane count as in it (the plane point is given on the 0.001 mm grid)."""
    lo, _ = kernel.plane_faces_region(ctx.current.parts[lower].mesh, plane_point, plane_normal, 1, tol_mm)
    up, _ = kernel.plane_faces_region(ctx.current.parts[upper].mesh, plane_point, plane_normal, -1, tol_mm)
    # closing by tol: seals zero-width slits between tessellation triangles (rotated frames), which would
    # otherwise open the ring; straight boundaries do not move
    contact = lo.intersection(up).buffer(tol_mm, join_style="mitre").buffer(-tol_mm, join_style="mitre")
    width = kernel.ring_width(contact, upper=4 * min_width_mm)
    ok = width >= min_width_mm - 1e-3
    details = [f"{'PASS' if ok else 'FAIL'}: narrowest contact {width:.3f} mm "
               f"({'>=' if ok else '<'} {min_width_mm} mm), contact area {contact.area:.2f} mm2"
               + ("" if width > 0 else "; the contact is not a closed ring")]
    return CheckResult(ok, None, {"width_mm": round(width, 4), "margin_mm": round(width - min_width_mm, 4),
                                  "area_mm2": round(contact.area, 3)}, details)
