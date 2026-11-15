"""Printability: thin walls and overhangs that are NEW compared with the original part. Generic.

Both checks look only where a part changed (the bounding box of the symmetric difference with the original, plus
a margin): the original is the accepted design, so its own features (e.g. 1.2 mm knuckle walls, curved
undersides) never count. Features smaller than `feature_mm` are ignored (rounding slivers, spec S2): a thin or
overhanging patch counts only if it is at least feature_mm thick (diameter of its largest inscribed circle), so a
0.004 mm sliver along a cut edge never counts, however long or bent it is.
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import polylabel, unary_union

from cadfix.core import kernel
from cadfix.core.registry import CheckContext, CheckResult, register

SLICE_OFFSET = 0.0137   # keeps slice planes off round coordinates (faces lying exactly in a slice plane)


def _parts(g):
    return [x for x in getattr(g, "geoms", [g]) if not x.is_empty]


def _size(poly) -> float:
    """Thickness of a planar patch: diameter of its largest inscribed circle (0.001 mm)."""
    if poly.geom_type != "Polygon" or poly.area < 1e-9:
        return 0.0
    return 2.0 * float(poly.exterior.distance(polylabel(poly, 1e-3)))


def _thin(region, w: float):
    """Parts of a planar region narrower than w (region minus its morphological opening by w / 2)."""
    if region.is_empty:
        return region
    with np.errstate(all="ignore"):
        opened = region.buffer(-w / 2, join_style="mitre").buffer(w / 2, join_style="mitre")
    return region.difference(opened)


def _diff_mesh(ctx: CheckContext, n: str):
    key = ("diff_mesh", n)
    if key not in ctx.cache:
        o, c = ctx.original.parts[n].mesh, ctx.current.parts[n].mesh
        d = (o - c) + (c - o)
        ctx.cache[key] = d if d.volume() > 1e-6 else None
    return ctx.cache[key]


@register("min_wall")
def min_wall(ctx: CheckContext, parts, frame, min_mm: float = 1.2, feature_mm: float = 0.2,
             margin_mm: float = 1.5) -> CheckResult:
    """No new wall thinner than min_mm. Sections every feature_mm along each frame axis through the changed
    region (+ margin_mm); in each section, material narrower than min_mm (region minus its opening) that the
    original section does not have counts, if it is at least feature_mm wide."""
    frame = np.asarray(frame, dtype=float)
    found, metrics, n_slices = [], {}, 0
    for n in parts:
        d = _diff_mesh(ctx, n) if ctx.current.parts[n].shape is not ctx.original.parts[n].shape else None
        if d is None:
            metrics[n] = "unchanged"
            continue
        for k in range(3):
            axes = np.vstack([frame[(k + 1) % 3], frame[(k + 2) % 3], frame[k]])
            m = kernel.frame_matrix(axes)
            o = kernel.transform_mesh(ctx.original.parts[n].mesh, m)
            c = kernel.transform_mesh(ctx.current.parts[n].mesh, m)
            lo, hi = kernel.bbox(kernel.transform_mesh(d, m))
            z = lo[2] - margin_mm + SLICE_OFFSET
            while z <= hi[2] + margin_mm:
                n_slices += 1
                ro, rc = kernel.slice_region(o, z), kernel.slice_region(c, z)
                if ro.symmetric_difference(rc).area > 1e-7:
                    new_thin = _thin(rc, min_mm).difference(_thin(ro, min_mm).buffer(0.02, join_style="mitre"))
                    for comp in _parts(new_thin):
                        thick = _size(comp)
                        if thick < feature_mm:
                            continue
                        pt = polylabel(comp, 1e-3)
                        world = kernel.apply_points(kernel.invert(m), [pt.x, pt.y, z])[0]
                        found.append({"part": n, "thickness_mm": round(thick, 3),
                                      "at": [round(float(v), 3) for v in world], "area_in_section_mm2": round(comp.area, 4)})
                z += feature_mm
    found.sort(key=lambda f: f["thickness_mm"])
    ok = not found
    metrics |= {"new_thin_walls": len(found), "thinnest_new_mm": found[0]["thickness_mm"] if found else None,
                "sections": n_slices}
    details = ([f"no new wall thinner than {min_mm} mm (features < {feature_mm} mm ignored)"] if ok else
               [f"new thin wall in {f['part']}: ~{f['thickness_mm']} mm near {f['at']}" for f in found[:5]])
    return CheckResult(ok, None, metrics, details)


def _down_tris(mesh, up, max_angle_deg):
    v, t = kernel.mesh_arrays(mesh)
    n = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    a2 = np.linalg.norm(n, axis=1)
    ok = a2 > 1e-12
    u = kernel.unit(up)
    nz = np.zeros(len(t))
    nz[ok] = (n[ok] @ u) / a2[ok]
    steep = ok & (nz < -np.cos(np.radians(90.0 - max_angle_deg)) - 1e-9)
    return v, t[steep], n[steep] / a2[steep][:, None], 0.5 * a2[steep]


def _on_triangles(points, v, tris, normals, tol=1e-4):
    """For each point: does it lie on one of the triangles (within tol of its plane, inside it)?"""
    if len(tris) == 0 or len(points) == 0:
        return np.zeros(len(points), dtype=bool)
    a, b, c = v[tris[:, 0]], v[tris[:, 1]], v[tris[:, 2]]
    out = np.zeros(len(points), dtype=bool)
    for i, p in enumerate(points):
        dist = np.einsum("ij,ij->i", p - a, normals)
        cand = np.abs(dist) < tol
        if not cand.any():
            continue
        q = p - dist[cand][:, None] * normals[cand]
        v0, v1, v2 = c[cand] - a[cand], b[cand] - a[cand], q - a[cand]
        d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
        d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
        den = d00 * d11 - d01 * d01
        good = np.abs(den) > 1e-18
        uu = np.where(good, (d11 * d20 - d01 * d21) / np.where(good, den, 1), -1)
        vv = np.where(good, (d00 * d21 - d01 * d20) / np.where(good, den, 1), -1)
        out[i] = bool(((uu >= -1e-6) & (vv >= -1e-6) & (uu + vv <= 1 + 1e-6)).any())
    return out


def _components(tris) -> list[np.ndarray]:
    """Groups of triangles connected through shared vertices (union-find)."""
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for t in tris:
        r0 = find(int(t[0]))
        for x in t[1:]:
            r = find(int(x))
            if r != r0:
                parent[r] = r0
    groups = {}
    for i, t in enumerate(tris):
        groups.setdefault(find(int(t[0])), []).append(i)
    return [np.array(g) for g in groups.values()]


@register("overhang")
def overhang(ctx: CheckContext, parts, max_angle_deg: float = 45.0, feature_mm: float = 0.2, tol_mm2: float = 0.01,
             margin_mm: float = 0.5) -> CheckResult:
    """No new downward-facing surface steeper than max_angle_deg from vertical in each part's print orientation
    (build-up direction from the assembly). A patch is new if it does not lie on a downward face of the original;
    patches thinner than feature_mm (projected) are ignored; the rest must total <= tol_mm2."""
    patches, metrics = [], {}
    for n in parts:
        p = ctx.current.parts[n]
        d = _diff_mesh(ctx, n) if p.shape is not ctx.original.parts[n].shape else None
        if d is None or p.build_up is None:
            metrics[n] = "unchanged" if d is None else "no print orientation"
            continue
        lo, hi = (np.asarray(x) for x in kernel.bbox(d))
        lo, hi = lo - margin_mm, hi + margin_mm
        v, t, nrm, area = _down_tris(p.mesh, p.build_up, max_angle_deg)
        cen = v[t].mean(axis=1)
        near = ((cen >= lo) & (cen <= hi)).all(axis=1)
        vo, to, no, _ = _down_tris(ctx.original.parts[n].mesh, p.build_up, max_angle_deg)
        co = vo[to].mean(axis=1) if len(to) else np.zeros((0, 3))
        keep = ((co >= lo - 2.0) & (co <= hi + 2.0)).all(axis=1) if len(to) else np.zeros(0, dtype=bool)
        old = _on_triangles(cen[near], vo, to[keep], no[keep])
        idx = np.where(near)[0][~old]
        if len(idx) == 0:
            continue
        axes = kernel.orthonormal_axes(p.build_up)
        for comp in _components(t[idx]):
            tri_ids = idx[comp]
            poly = unary_union([Polygon((v[t[i]] @ axes[:2].T)) for i in tri_ids]).buffer(0)
            if poly.is_empty:
                continue
            big = [g for g in _parts(poly) if _size(g) >= feature_mm]
            if not big:
                continue
            c = cen[tri_ids].mean(axis=0)
            patches.append({"part": n, "area_mm2": round(float(area[tri_ids].sum()), 4),
                            "at": [round(float(x), 3) for x in c]})
    total = sum(pa["area_mm2"] for pa in patches)
    ok = total <= tol_mm2
    metrics |= {"new_overhang_mm2": round(total, 4), "patches": len(patches)}
    details = ([f"no new overhang steeper than {max_angle_deg:g} deg (features < {feature_mm} mm ignored)"] if ok else
               [f"new overhang in {pa['part']}: {pa['area_mm2']} mm2 near {pa['at']}" for pa in patches[:5]])
    return CheckResult(ok, None, metrics, details)
