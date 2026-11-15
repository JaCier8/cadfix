"""Edit ops on editable B-rep parts. Generic: no scenario names.

Every op takes a cadquery Shape and returns a NEW shape (the input is never modified). Inputs are validated and
every failure raises OpError with a message meant to be read by an agent. Lengths and points are snapped to
kernel.SNAP_MM (they cross a tool boundary); directions are normalised.

Ops as data (JSON-like dicts, see apply_op):
  {"op": "chamfer", "part": P, "edge_near": [x, y, z], "d1": a, "d2": b, "d1_face_normal": [nx, ny, nz]}
  {"op": "extrude_cut", "part": P, "origin": [x, y, z], "normal": [..], "x_dir": [..],
   "polygon_2d": [[u, v], ...], "depth_from": f, "depth_to": t}
"""
from __future__ import annotations

import math

import cadquery as cq
import numpy as np
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer
from shapely.geometry import Polygon

from cadfix.core.kernel import SNAP_MM

EDGE_SEARCH_MM = 1.0     # find_edge_near: the nearest edge must be this close to the point
EDGE_TIE_MM = 1e-3       # ... and closer than any other edge by this much
MIN_REMOVED_MM3 = 1e-6   # a cut that removes less than this did not touch the part


class OpError(ValueError):
    """An edit could not be applied; the message says why and what to change."""


# ---------------------------------------------------------------- input validation
def _snap(x: float) -> float:
    return round(round(x / SNAP_MM) * SNAP_MM, 6) + 0.0


def _number(name: str, v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise OpError(f"{name} must be a finite number, got {v!r}")
    return float(v)


def _length(name: str, v, positive: bool = True) -> float:
    x = _snap(_number(name, v))
    if positive and x <= 0:
        raise OpError(f"{name} must be > 0 mm (after snapping to {SNAP_MM} mm), got {v!r}")
    return x


def _point(name: str, v) -> np.ndarray:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise OpError(f"{name} must be a list of 3 numbers [x, y, z], got {v!r}")
    return np.array([_snap(_number(f"{name}[{i}]", c)) for i, c in enumerate(v)])


def _direction(name: str, v) -> np.ndarray:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise OpError(f"{name} must be a list of 3 numbers [x, y, z], got {v!r}")
    d = np.array([_number(f"{name}[{i}]", c) for i, c in enumerate(v)])
    n = np.linalg.norm(d)
    if n < 1e-9:
        raise OpError(f"{name} must not be the zero vector")
    return d / n


def _single_solid(shape: cq.Shape, what: str) -> cq.Shape:
    if isinstance(shape, cq.Compound):
        solids = shape.Solids()
        if len(solids) != 1:
            raise OpError(f"{what} would split the part into {len(solids)} separate solids; the part must stay "
                          f"one piece")
        shape = solids[0]
    if not shape.isValid():
        raise OpError(f"{what} produced an invalid solid (CAD kernel check failed)")
    return shape


def _fmt(v) -> str:
    return "[" + ", ".join(f"{x:.3f}" for x in v) + "]"


# ---------------------------------------------------------------- queries
def describe_edge(e: cq.Edge) -> str:
    a, b = e.startPoint().toTuple(), e.endPoint().toTuple()
    return f"{e.geomType().lower()} {_fmt(a)} -> {_fmt(b)}, length {e.Length():.3f}"


def find_edge_near(shape: cq.Shape, point, direction=None) -> cq.Edge:
    """The edge closest to `point` (within EDGE_SEARCH_MM). With `direction`, only straight edges parallel to
    it (within 1 deg) are considered. Ambiguous (two edges equally close) -> OpError."""
    p = _point("edge_near", point)
    d = None if direction is None else _direction("edge_direction", direction)
    v = cq.Vertex.makeVertex(*p.tolist())
    cands = []
    for e in shape.Edges():
        if d is not None:
            if e.geomType() != "LINE":
                continue
            t = np.array((e.endPoint() - e.startPoint()).toTuple())
            if abs(abs(t @ d) / np.linalg.norm(t) - 1.0) > 1.5e-4:
                continue
        cands.append((e.distance(v), e))
    cands.sort(key=lambda c: c[0])
    if not cands or cands[0][0] > EDGE_SEARCH_MM:
        near = f"; nearest edge is {cands[0][0]:.3f} mm away: {describe_edge(cands[0][1])}" if cands else ""
        raise OpError(f"no edge within {EDGE_SEARCH_MM} mm of {_fmt(p)}{near}")
    if len(cands) > 1 and cands[1][0] - cands[0][0] < EDGE_TIE_MM:
        raise OpError(f"edge_near {_fmt(p)} is ambiguous: {describe_edge(cands[0][1])} and "
                      f"{describe_edge(cands[1][1])} are both {cands[0][0]:.3f} mm away; move the point onto the "
                      f"edge you mean (e.g. its midpoint) or give edge_direction")
    return cands[0][1]


def adjacent_faces(shape: cq.Shape, edge: cq.Edge) -> list[cq.Face]:
    return [f for f in shape.Faces() if any(e.isSame(edge) for e in f.Edges())]


# ---------------------------------------------------------------- ops
def chamfer(shape: cq.Shape, edge_near, d1, d2=None, d1_face_normal=None, edge_direction=None) -> cq.Shape:
    """Chamfer one whole edge. d1 is measured on one adjacent face, d2 (default d1) on the other.

    The d1 face is the adjacent face whose outward normal is closest to d1_face_normal; without it, the adjacent
    face whose normal points most upwards (+z)."""
    d1 = _length("d1", d1)
    d2 = d1 if d2 is None else _length("d2", d2)
    edge = find_edge_near(shape, edge_near, edge_direction)
    faces = adjacent_faces(shape, edge)
    if len(faces) != 2:
        raise OpError(f"edge {describe_edge(edge)} has {len(faces)} adjacent faces, expected 2")
    mid = edge.positionAt(0.5)
    normals = [np.array(f.normalAt(mid).toTuple()) for f in faces]
    if d1_face_normal is None:
        k = int(np.argmax([n[2] for n in normals]))
    else:
        want = _direction("d1_face_normal", d1_face_normal)
        dots = [float(n @ want) for n in normals]
        k = int(np.argmax(dots))
        if dots[k] < 0.5:
            raise OpError(f"d1_face_normal {_fmt(want)} matches neither adjacent face of the edge; their outward "
                          f"normals are {_fmt(normals[0])} and {_fmt(normals[1])}")
    mk = BRepFilletAPI_MakeChamfer(shape.wrapped)
    mk.Add(d1, d2, edge.wrapped, faces[k].wrapped)
    try:
        mk.Build()
        ok = mk.IsDone()
    except Exception:  # noqa: BLE001 - OCC raises various StdFail_* types
        ok = False
    if not ok:
        raise OpError(f"chamfer d1={d1} d2={d2} on edge {describe_edge(edge)} failed in the CAD kernel; "
                      f"usually a distance is larger than the adjacent faces allow")
    return _single_solid(cq.Shape.cast(mk.Shape()), "chamfer")


def extrude_cut(shape: cq.Shape, origin, normal, x_dir, polygon_2d, depth_from, depth_to) -> cq.Shape:
    """Cut a prism out of the part: a polygon sketched on the plane through `origin` with normal `normal`
    (2D coordinates u along x_dir, v along y_dir = normal x x_dir) is swept along the normal from
    origin + depth_from * normal to origin + depth_to * normal, and that volume is removed."""
    o = _point("origin", origin)
    n = _direction("normal", normal)
    x = _direction("x_dir", x_dir)
    if abs(float(n @ x)) > 1e-3:
        raise OpError(f"x_dir {_fmt(x)} must be perpendicular to normal {_fmt(n)} (|cos| = {abs(float(n @ x)):.4f})")
    x = x - (n @ x) * n
    x /= np.linalg.norm(x)
    if not isinstance(polygon_2d, (list, tuple)) or len(polygon_2d) < 3:
        raise OpError("polygon_2d must be a list of at least 3 points [u, v]")
    pts = []
    for i, q in enumerate(polygon_2d):
        if not isinstance(q, (list, tuple)) or len(q) != 2:
            raise OpError(f"polygon_2d[{i}] must be [u, v], got {q!r}")
        pts.append((_snap(_number(f"polygon_2d[{i}][0]", q[0])), _snap(_number(f"polygon_2d[{i}][1]", q[1]))))
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    poly = Polygon(pts)
    if len(pts) < 3 or not poly.is_valid or poly.area < 1e-6:
        raise OpError("polygon_2d must be a simple (non self-intersecting) polygon with non-zero area")
    f = _length("depth_from", depth_from, positive=False)
    t = _length("depth_to", depth_to, positive=False)
    if t - f < SNAP_MM:
        raise OpError(f"depth_to ({t}) must be larger than depth_from ({f})")
    plane = cq.Plane(origin=tuple((o + f * n).tolist()), xDir=tuple(x.tolist()), normal=tuple(n.tolist()))
    tool = cq.Workplane(plane).polyline(pts).close().extrude(t - f).val()
    before = shape.Volume()
    out = _single_solid(cq.Workplane().add(shape).cut(tool).val(), "extrude_cut")
    if before - out.Volume() < MIN_REMOVED_MM3:
        raise OpError("extrude_cut removed no material: the prism does not intersect the part")
    return out


OPS = {
    "chamfer": (chamfer, {"edge_near", "d1"}, {"d2", "d1_face_normal", "edge_direction"}),
    "extrude_cut": (extrude_cut, {"origin", "normal", "x_dir", "polygon_2d", "depth_from", "depth_to"}, set()),
}


def apply_op(shapes: dict, op: dict, editable, default_part: str | None = None) -> tuple[str, cq.Shape]:
    """Apply one op dict to a copy of the named part. Returns (part name, new shape); `shapes` is unchanged."""
    if not isinstance(op, dict):
        raise OpError(f"each operation must be an object, got {op!r}")
    name = op.get("op")
    if name not in OPS:
        raise OpError(f"unknown op {name!r}; available: {sorted(OPS)}")
    fn, required, optional = OPS[name]
    keys = set(op) - {"op", "part"}
    missing, unknown = required - keys, keys - required - optional
    if missing or unknown:
        raise OpError(f"{name}: missing {sorted(missing)}, unknown {sorted(unknown)}; "
                      f"required {sorted(required)}, optional {sorted(optional) + ['part']}")
    part = op.get("part", default_part)
    if part not in shapes:
        raise OpError(f"{name}: unknown part {part!r}; parts: {sorted(shapes)}")
    if part not in editable:
        raise OpError(f"{name}: part {part!r} is not editable; editable parts: {sorted(editable)}")
    return part, fn(shapes[part], **{k: op[k] for k in keys})


def apply_ops(shapes: dict, ops, editable, default_part: str | None = None) -> tuple[dict, list[dict]]:
    """Apply a list of op dicts in order. Returns (new shapes dict, per-op log {index, op, part, removed_mm3}).
    The first failing op raises OpError prefixed with its index."""
    if not isinstance(ops, (list, tuple)):
        raise OpError("operations must be a JSON list")
    out, log = dict(shapes), []
    for i, op in enumerate(ops):
        try:
            part, new = apply_op(out, op, editable, default_part)
        except OpError as e:
            raise OpError(f"operation {i}: {e}") from None
        log.append({"index": i, "op": op["op"], "part": part,
                    "removed_mm3": round(out[part].Volume() - new.Volume(), 6)})
        out[part] = new
    return out, log
