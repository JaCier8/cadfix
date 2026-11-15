"""B-rep (CadQuery/OCP) and mesh (manifold3d) helpers. Generic: knows nothing about any scenario.

Units mm, degrees. B-rep shapes are cadquery.Shape (or Workplane); meshes are manifold3d.Manifold.
"""
from __future__ import annotations

from pathlib import Path

import cadquery as cq
import manifold3d
import numpy as np
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.gp import gp_Trsf
from shapely.geometry import Polygon
from shapely.ops import unary_union

SNAP_MM = 0.001   # grid for coordinates crossing a tool/file boundary (see CLAUDE.md)
# Tessellation weld grid. Not SNAP_MM: in a rotated frame, snapping mesh vertices to 0.001 mm moves them up to
# ~0.0009 mm off their planes, and two coplanar contact faces (lid on the wall tops) then "overlap" by
# 0.01-0.2 mm3 at rest. 1e-6 still welds OCC's per-face duplicate vertices (see docs/DECISIONS.md D6).
WELD_MM = 1e-6
VOL_EPS = 1e-3    # mm^3; overlaps below this count as touching, not colliding


# ---------------------------------------------------------------- B-rep io
def _as_shape(shape) -> cq.Shape:
    if isinstance(shape, cq.Workplane):
        return shape.val()
    return shape


def export_step(shape, path) -> None:
    cq.exporters.export(cq.Workplane().add(_as_shape(shape)), str(path), exportType="STEP")


def import_step(path) -> cq.Shape:
    """Load a STEP file holding one solid."""
    return cq.importers.importStep(str(path)).val()


# ---------------------------------------------------------------- B-rep -> mesh
def to_manifold(shape, tolerance: float = 0.01, angular_tolerance: float = 0.1) -> manifold3d.Manifold:
    """Tessellate a B-rep solid, weld shared vertices on a WELD_MM grid, build a Manifold."""
    verts, tris = _as_shape(shape).tessellate(tolerance, angular_tolerance)
    v = np.array([p.toTuple() for p in verts], dtype=np.float64)
    t = np.array(tris, dtype=np.int64).reshape(-1, 3)
    # OCC tessellates face by face, so edge vertices are duplicated; rounding + unique welds them.
    v = np.round(v / WELD_MM) * WELD_MM
    v, inverse = np.unique(v, axis=0, return_inverse=True)
    t = inverse.reshape(-1)[t]
    t = t[(t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])]  # drop collapsed tris
    mesh = manifold3d.Mesh64(vert_properties=np.ascontiguousarray(v),
                             tri_verts=np.ascontiguousarray(t, dtype=np.uint64))
    m = manifold3d.Manifold(mesh)
    if m.status() != manifold3d.Error.NoError:
        raise ValueError(f"tessellation is not a closed manifold: {m.status()}")
    return m


# ---------------------------------------------------------------- transforms
def rotation_matrix(point, direction, angle_deg: float) -> np.ndarray:
    """3x4 affine matrix: rotation by angle_deg about the axis through `point` along `direction`
    (right-hand rule)."""
    p = np.asarray(point, dtype=float)
    d = np.asarray(direction, dtype=float)
    d = d / np.linalg.norm(d)
    a = np.radians(angle_deg)
    k = np.array([[0, -d[2], d[1]], [d[2], 0, -d[0]], [-d[1], d[0], 0]])
    r = np.eye(3) + np.sin(a) * k + (1 - np.cos(a)) * (k @ k)  # Rodrigues
    return np.hstack([r, (p - r @ p).reshape(3, 1)])


def rotate(m: manifold3d.Manifold, point, direction, angle_deg: float) -> manifold3d.Manifold:
    if angle_deg == 0:
        return m
    return m.transform(rotation_matrix(point, direction, angle_deg))


def rotate_points(pts, point, direction, angle_deg: float) -> np.ndarray:
    mat = rotation_matrix(point, direction, angle_deg)
    pts = np.atleast_2d(np.asarray(pts, dtype=float))
    return pts @ mat[:, :3].T + mat[:, 3]


# ---------------------------------------------------------------- rigid poses (3x4 matrices [R | t])
IDENTITY = np.hstack([np.eye(3), np.zeros((3, 1))])


def compose(*mats) -> np.ndarray:
    """compose(A, B) applies B first, then A (like A @ B for 4x4 matrices)."""
    out = IDENTITY.copy()
    for m in mats:
        m = np.asarray(m, dtype=float)
        out = np.hstack([out[:, :3] @ m[:, :3], (out[:, :3] @ m[:, 3] + out[:, 3]).reshape(3, 1)])
    return out


def invert(m) -> np.ndarray:
    """Inverse of a rigid 3x4 matrix."""
    m = np.asarray(m, dtype=float)
    rt = m[:, :3].T
    return np.hstack([rt, (-rt @ m[:, 3]).reshape(3, 1)])


def translation(offset) -> np.ndarray:
    return np.hstack([np.eye(3), np.asarray(offset, dtype=float).reshape(3, 1)])


def apply_points(m, pts) -> np.ndarray:
    m = np.asarray(m, dtype=float)
    pts = np.atleast_2d(np.asarray(pts, dtype=float))
    return pts @ m[:, :3].T + m[:, 3]


def apply_dirs(m, dirs) -> np.ndarray:
    m = np.asarray(m, dtype=float)
    return np.atleast_2d(np.asarray(dirs, dtype=float)) @ m[:, :3].T


def transform_shape(shape, m) -> cq.Shape:
    """Rigid transform of a B-rep shape (geometry copied, so the result shares nothing with the input)."""
    t = gp_Trsf()
    t.SetValues(*np.asarray(m, dtype=float).ravel().tolist())
    return cq.Shape.cast(BRepBuilderAPI_Transform(_as_shape(shape).wrapped, t, True).Shape())


def transform_mesh(m: manifold3d.Manifold, mat) -> manifold3d.Manifold:
    return m.transform(np.asarray(mat, dtype=float).tolist())


def oriented_box(origin, edges) -> manifold3d.Manifold:
    """Parallelepiped with one corner at `origin` spanned by the three edge vectors (right-handed order)."""
    e = np.asarray(edges, dtype=float)
    mat = np.hstack([e.T, np.asarray(origin, dtype=float).reshape(3, 1)])
    return manifold3d.Manifold.cube([1.0, 1.0, 1.0]).transform(mat.tolist())


# ---------------------------------------------------------------- frames
def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float).ravel()
    return v / np.linalg.norm(v)


def frame_matrix(axes, origin=(0.0, 0.0, 0.0)) -> np.ndarray:
    """3x4 rigid matrix world -> frame coordinates for orthonormal `axes` (rows: the frame's x, y, z in world)
    with the frame origin at `origin` (world)."""
    r = np.asarray(axes, dtype=float).reshape(3, 3)
    return np.hstack([r, (-r @ np.asarray(origin, dtype=float)).reshape(3, 1)])


def orthonormal_axes(z_dir, x_hint=None) -> np.ndarray:
    """Rows (x, y, z) of a right-handed orthonormal frame with z along z_dir and x as close to x_hint as possible
    (default: the world axis least parallel to z). Deterministic."""
    z = unit(z_dir)
    if x_hint is None:
        x_hint = np.eye(3)[int(np.argmin(np.abs(z)))]
    x = np.asarray(x_hint, dtype=float) - (np.asarray(x_hint, dtype=float) @ z) * z
    if np.linalg.norm(x) < 1e-9:
        raise ValueError("x_hint is parallel to z_dir")
    x = x / np.linalg.norm(x)
    return np.vstack([x, np.cross(z, x), z])


def mesh_arrays(m: manifold3d.Manifold) -> tuple[np.ndarray, np.ndarray]:
    mesh = m.to_mesh()
    return np.asarray(mesh.vert_properties)[:, :3].astype(float), np.asarray(mesh.tri_verts, dtype=np.int64)


def centroid(m: manifold3d.Manifold) -> list[float] | None:
    """Volume centroid of a closed mesh (divergence theorem); None for an empty mesh."""
    v, t = mesh_arrays(m)
    if len(t) == 0:
        return None
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    vol = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
    total = vol.sum()
    if abs(total) < 1e-12:
        return [float(x) for x in v.mean(axis=0)]
    return [float(x) for x in ((a + b + c) / 4.0 * vol[:, None]).sum(axis=0) / total]


# ---------------------------------------------------------------- planar regions
def faces_region_at_z(m: manifold3d.Manifold, z: float, tol: float = 1e-4, facing: int = 1) -> Polygon:
    """Union (in x, y) of the mesh triangles lying in the plane z = const and facing +z (facing=1) or -z
    (facing=-1)."""
    v, t = mesh_arrays(m)
    n = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    on = (np.abs(v[t][:, :, 2] - z) < tol).all(axis=1) & (facing * n[:, 2] > 0)
    return unary_union([Polygon(v[tri][:, :2]) for tri in t[on]]).buffer(0)


def plane_faces_region(m: manifold3d.Manifold, point, normal, facing: int = 1, tol: float = 1e-4,
                       x_hint=None) -> tuple[Polygon, np.ndarray]:
    """Faces of m lying in the plane (point, normal) and facing along +normal (facing=1) or -normal, as a
    polygon in plane coordinates. Returns (region, world->plane 3x4 matrix)."""
    mat = frame_matrix(orthonormal_axes(normal, x_hint), point)
    return faces_region_at_z(transform_mesh(m, mat), 0.0, tol, facing), mat


def slice_region(m: manifold3d.Manifold, z: float):
    """Section of the mesh with the plane z = const as a shapely geometry (holes resolved by even-odd)."""
    region = Polygon()
    for loop in m.slice(z).to_polygons():
        loop = np.asarray(loop)
        if len(loop) >= 3:
            region = region.symmetric_difference(Polygon(loop))
    return region.buffer(0)


def _is_ring(g) -> bool:
    parts = getattr(g, "geoms", [g])
    return any(not p.is_empty and len(p.interiors) > 0 for p in parts)


def ring_width(region, upper: float, tol: float = 1e-3) -> float:
    """Smallest width of a closed ring in a planar region: twice the largest erosion that still leaves a
    closed ring (a polygon with a hole). 0 if the region is no ring; `upper` if the ring survives
    erosion by upper / 2."""
    if not _is_ring(region):
        return 0.0
    if _is_ring(region.buffer(-upper / 2)):
        return float(upper)
    lo, hi = 0.0, upper / 2
    while hi - lo > tol / 4:
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if _is_ring(region.buffer(-mid)) else (lo, mid)
    return round(2 * lo, 4)


# ---------------------------------------------------------------- queries
def bbox(m: manifold3d.Manifold) -> tuple[list[float], list[float]]:
    b = m.bounding_box()
    return [float(x) for x in b[:3]], [float(x) for x in b[3:]]


def intersection(a: manifold3d.Manifold, b: manifold3d.Manifold):
    """(volume, bbox) of the overlap of a and b; (0.0, None) if they only touch or are apart.

    bbox is ([xmin, ymin, zmin], [xmax, ymax, zmax]) rounded to SNAP_MM.
    """
    i = a ^ b
    vol = float(i.volume())
    if vol <= VOL_EPS:
        return 0.0, None
    lo, hi = bbox(i)
    return vol, ([round(v, 3) for v in lo], [round(v, 3) for v in hi])


def intersection_components(a: manifold3d.Manifold, b: manifold3d.Manifold, min_volume: float = VOL_EPS) -> list[dict]:
    """Disjoint pieces of the overlap of a and b, each with volume and bbox (pieces <= min_volume dropped)."""
    out = []
    for piece in (a ^ b).decompose():
        vol = float(piece.volume())
        if vol > min_volume:
            lo, hi = bbox(piece)
            out.append({"volume": vol, "bbox": ([round(v, 3) for v in lo], [round(v, 3) for v in hi])})
    return out


def changed_volume(a: manifold3d.Manifold, b: manifold3d.Manifold) -> tuple[float, float]:
    """(removed, added) volume going from a to b."""
    return float((a - b).volume()), float((b - a).volume())


def box_overlap_volume(m: manifold3d.Manifold, lo, hi) -> float:
    """Volume of m inside the axis-aligned box [lo, hi]."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    return float((m ^ manifold3d.Manifold.cube((hi - lo).tolist()).translate(lo.tolist())).volume())


def downward_area(m: manifold3d.Manifold, max_overhang_deg: float = 45.0, up=(0.0, 0.0, 1.0)) -> float:
    """Area of faces pointing down more steeply than max_overhang_deg from vertical walls,
    i.e. overhangs that need support when printed with `up` as the build direction."""
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3]
    t = np.asarray(mesh.tri_verts, dtype=np.int64)
    n = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    area2 = np.linalg.norm(n, axis=1)
    ok = area2 > 0
    u = np.asarray(up, dtype=float) / np.linalg.norm(up)
    nz = np.zeros(len(t))
    nz[ok] = (n[ok] @ u) / area2[ok]
    steep = nz < -np.cos(np.radians(90.0 - max_overhang_deg)) - 1e-9
    return float(0.5 * area2[steep].sum())


# ---------------------------------------------------------------- joint sweeps
def _angles(start: float, stop: float, step: float) -> list[float]:
    n = int(round((stop - start) / step))
    return [round(start + i * step, 6) for i in range(n + 1)]


def overlaps_at(moving: dict, fixed: dict, point, direction, angle_deg: float) -> list[dict]:
    """Every (moving, fixed) pair overlapping (> VOL_EPS) with the moving parts rotated by angle_deg."""
    out = []
    for mv, m in moving.items():
        r = rotate(m, point, direction, angle_deg)
        for fx, f in fixed.items():
            vol, bb = intersection(r, f)
            if vol > 0:
                out.append({"moving": mv, "fixed": fx, "volume": vol, "bbox": bb})
    return out


def _union_bbox(boxes):
    lo = np.min([b[0] for b in boxes], axis=0).round(3).tolist()
    hi = np.max([b[1] for b in boxes], axis=0).round(3).tolist()
    return lo, hi


def first_contact_sweep(moving: dict, fixed: dict, point, direction, start: float = 0.0, stop: float = 180.0,
                        step: float = 1.0, refine: float = 0.1) -> dict | None:
    """First angle of a revolute joint at which any moving part overlaps any fixed part.

    moving/fixed: {name: Manifold}. The moving parts rotate together about the axis (point, direction).
    Coarse steps of `step` from start to stop, then the last step before the hit is re-scanned in `refine`
    steps. Returns None if nothing overlaps up to `stop`, else {angle, coarse_angle, volume, bbox,
    contacts: [{moving, fixed, volume, bbox}]} at the first overlapping (refined) angle.
    """
    prev = None
    for ang in _angles(start, stop, step):
        hits = overlaps_at(moving, fixed, point, direction, ang)
        if hits:
            found = (ang, hits)
            if prev is not None:
                for fine in _angles(prev, ang, refine)[1:]:
                    h = overlaps_at(moving, fixed, point, direction, fine)
                    if h:
                        found = (fine, h)
                        break
            angle, contacts = found
            return {"angle": angle, "coarse_angle": ang, "contacts": contacts,
                    "volume": sum(c["volume"] for c in contacts),
                    "bbox": _union_bbox([c["bbox"] for c in contacts])}
        prev = ang
    return None


def clearance_sweep(moving: dict, fixed: dict, point, direction, angles, search: float) -> list[dict]:
    """Per joint angle: the smallest gap between any moving and any fixed part, capped at `search`
    (gaps >= search are reported as search), the closest pair and the overlap volume (0 = touching only).

    Returns [{angle, gap, pair, overlap}] in the order of `angles`.
    """
    out = []
    for ang in angles:
        best = (float(search), None, 0.0)
        for mv, m in moving.items():
            r = rotate(m, point, direction, ang)
            for fx, f in fixed.items():
                g = min(float(r.min_gap(f, search)), float(search))
                if g <= 0.0:
                    vol, _ = intersection(r, f)
                    if best[0] > 0.0 or vol > best[2]:
                        best = (0.0, (mv, fx), vol)
                elif g < best[0]:
                    best = (g, (mv, fx), best[2])
        out.append({"angle": ang, "gap": best[0], "pair": best[1], "overlap": best[2]})
    return out
