"""Shared geometry library: one implementation used by env tools, grader and solver.

Units: millimetres. Z up. All solids are manifold3d.Manifold objects.
"""
from __future__ import annotations

import numpy as np
import trimesh
import manifold3d as m3

VOL_EPS = 1e-3  # mm^3; overlaps below this count as touching, not colliding
SNAP = 3        # all coordinates are snapped to 0.001 mm, so a patch typed from a reported number
                # lands exactly on the existing face (STL float32 rounding would otherwise leave slivers)


def snap(v):
    return np.round(np.asarray(v, float), SNAP)

# Rotations that bring the given axis onto Z (proper rotations, det=+1).
# For a section along axis A we report 2D coords in this order:
_TO_Z = {
    "z": (np.eye(3), ("x", "y")),
    "x": (np.array([[0, 1, 0], [0, 0, 1], [1, 0, 0]], float), ("y", "z")),  # (x,y,z)->(y,z,x)
    "y": (np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], float), ("x", "z")),  # (x,y,z)->(z,x,y), reported as (x,z)
}
_AXIS_IDX = {"x": 0, "y": 1, "z": 2}


# ---------------------------------------------------------------- primitives
def box(lo, hi) -> m3.Manifold:
    lo = snap(lo)
    hi = snap(hi)
    if np.any(hi - lo <= 0):
        raise ValueError(f"box needs max > min on every axis, got min={lo.tolist()} max={hi.tolist()}")
    return m3.Manifold.cube((hi - lo).tolist()).translate(lo.tolist())


def cylinder(axis: str, center, radius: float, start: float, end: float, segments: int = 48) -> m3.Manifold:
    """Cylinder along `axis` from coordinate `start` to `end`.

    `center` is the 2D centre in the other two axes, in alphabetical order:
    axis x -> (y, z), axis y -> (x, z), axis z -> (x, y).
    """
    if axis not in _AXIS_IDX:
        raise ValueError("axis must be 'x', 'y' or 'z'")
    a0, a1 = sorted((float(snap(start)), float(snap(end))))
    radius = float(snap(radius))
    center = snap(center)
    if a1 - a0 <= 0 or radius <= 0:
        raise ValueError("cylinder needs positive length and radius")
    c = m3.Manifold.cylinder(a1 - a0, float(radius), float(radius), segments)  # along +z from 0
    u, v = float(center[0]), float(center[1])
    if axis == "z":
        return c.translate([u, v, a0])
    if axis == "x":
        # rotate about y by +90 deg: (x,y,z) -> (z, y, -x); circle ends up in the y/z plane
        return c.rotate([0, 90, 0]).translate([a0, u, v])
    # axis == "y": rotate about x by -90 deg: (x,y,z) -> (x, z, -y)
    return c.rotate([-90, 0, 0]).translate([u, a0, v])


# ---------------------------------------------------------------- io
def to_trimesh(m: m3.Manifold) -> trimesh.Trimesh:
    mesh = m.to_mesh64()
    v = np.asarray(mesh.vert_properties)[:, :3]
    f = np.asarray(mesh.tri_verts)
    return trimesh.Trimesh(v, f, process=False)


def from_trimesh(tm: trimesh.Trimesh) -> m3.Manifold:
    tm = tm.copy()
    tm.merge_vertices()
    mesh = m3.Mesh64(
        vert_properties=np.ascontiguousarray(snap(tm.vertices)),
        tri_verts=np.ascontiguousarray(tm.faces, dtype=np.uint64),
    )
    m = m3.Manifold(mesh)
    if m.status() != m3.Error.NoError:
        raise ValueError(f"mesh is not a valid closed manifold: {m.status()}")
    return m


def save_stl(m: m3.Manifold, path) -> None:
    to_trimesh(m).export(str(path))


def load_stl(path) -> m3.Manifold:
    tm = trimesh.load(str(path), force="mesh")
    return from_trimesh(tm)


# ---------------------------------------------------------------- queries
def bbox(m: m3.Manifold):
    b = m.bounding_box()
    return [float(x) for x in b[:3]], [float(x) for x in b[3:]]


def interference(a: m3.Manifold, b: m3.Manifold):
    """Volume of overlap and its bounding box (None if they only touch or are apart)."""
    i = a ^ b
    vol = float(i.volume())
    if vol <= VOL_EPS:
        return 0.0, None
    lo, hi = bbox(i)
    return vol, ([round(v, 3) for v in lo], [round(v, 3) for v in hi])


def min_gap(a: m3.Manifold, b: m3.Manifold, search: float = 10.0) -> float:
    """Smallest distance between surfaces, capped at `search`. 0 if touching or overlapping."""
    return float(a.min_gap(b, search))


def sym_diff_volume(a: m3.Manifold, b: m3.Manifold) -> float:
    return float((a - b).volume() + (b - a).volume())


def section(m: m3.Manifold, axis: str, value: float):
    """Cut with the plane axis=value. Returns loops with 2D coords, area and whether each is a hole."""
    rot, labels = _TO_Z[axis]
    mat = np.hstack([rot, np.zeros((3, 1))])
    cs = m.transform(mat).slice(float(value))
    loops = []
    for poly in cs.to_polygons():
        pts = np.asarray(poly, float)
        if len(pts) < 3:
            continue
        x, y = pts[:, 0], pts[:, 1]
        area = 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
        if axis == "y":
            pts = pts[:, ::-1].copy()  # (z, x) -> (x, z); hole flag already taken from the original winding
        loops.append({"coords": labels, "points": pts, "area": area, "is_hole": area < 0})
    return loops


def loop_summary(loop) -> dict:
    pts = loop["points"]
    a = abs(loop["area"])
    per = float(np.sum(np.linalg.norm(pts - np.roll(pts, -1, axis=0), axis=1)))
    circularity = 4 * np.pi * a / per**2 if per > 0 else 0.0
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    out = {
        "coords": list(loop["coords"]),
        "min": [round(float(v), 3) for v in lo],
        "max": [round(float(v), 3) for v in hi],
        "center": [round(float(v), 3) for v in (lo + hi) / 2],
        "area_mm2": round(a, 3),
        "shape": "circle" if circularity > 0.97 else ("rectangle" if abs(a - np.prod(hi - lo)) < 1e-3 * max(a, 1) else "other"),
    }
    if out["shape"] == "circle":
        out["diameter"] = round(float(np.mean(hi - lo)), 3)
    return out


def wall_thickness(m: m3.Manifold, samples_per_face: int = 2, seed: int = 0, region=None):
    """Local thickness by casting a ray inward from points on every triangle.

    Returns (min_thickness, location, all_thicknesses). `region` = (lo, hi) box to restrict samples.
    """
    tm = to_trimesh(m)
    rng = np.random.default_rng(seed)
    tris = tm.triangles
    normals = tm.face_normals
    pts = [tris.mean(axis=1)]
    nrm = [normals]
    for _ in range(samples_per_face):
        w = rng.uniform(0.15, 0.7, size=(len(tris), 3))
        w /= w.sum(axis=1, keepdims=True)
        pts.append(np.einsum("ij,ijk->ik", w, tris))
        nrm.append(normals)
    pts = np.vstack(pts)
    nrm = np.vstack(nrm)
    if region is not None:
        lo, hi = np.asarray(region[0]), np.asarray(region[1])
        keep = np.all((pts >= lo) & (pts <= hi), axis=1)
        pts, nrm = pts[keep], nrm[keep]
    off, reach = 1e-3, 60.0
    best, where, all_t = np.inf, None, []
    for p, n in zip(pts, nrm):
        o = p - n * off
        hits = m.ray_cast(o.tolist(), (o - n * reach).tolist())  # hit.distance is a fraction of the segment
        hits = [h for h in hits if h.distance * reach > 1e-6]
        if not hits:
            continue
        t = hits[0].distance * reach + off
        all_t.append(t)
        if t < best:
            best, where = t, p
    return float(best), (None if where is None else [round(float(v), 3) for v in where]), np.asarray(all_t)
