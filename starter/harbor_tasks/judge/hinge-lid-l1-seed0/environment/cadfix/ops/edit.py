"""Edit ops on editable B-rep parts. Generic: no scenario names.

Every op takes a cadquery Shape and returns a NEW shape (the input is never modified). Inputs are validated and
every failure raises OpError with a message meant to be read by an agent. Lengths and points are snapped to
kernel.SNAP_MM (they cross a tool boundary); directions are normalised.

Ops as data (JSON-like dicts, see apply_op; OP_SPECS documents every parameter):
  {"op": "chamfer", "part": P, "edge_near": [x, y, z], "d1": a, "d2": b, "d1_face_normal": [nx, ny, nz]}
  {"op": "chamfer", "part": P, "edge": 12, "d1": a}                       (edge id from list_edges)
  {"op": "fillet", "part": P, "edge_near": [x, y, z], "r": r}
  {"op": "offset_face", "part": P, "face_near": [x, y, z], "d": d}        (planar faces; d > 0 adds material)
  {"op": "extrude_cut", "part": P, "origin": [x, y, z], "normal": [..], "x_dir": [..],
   "polygon_2d": [[u, v], ...], "depth_from": f, "depth_to": t}
  {"op": "cut_box" | "add_box", "part": P, "origin": [x, y, z], "edges": [[..], [..], [..]]}
"""
from __future__ import annotations

import math

import cadquery as cq
import numpy as np
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
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


def _index(name: str, v, n: int, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v:
        raise OpError(f"{name} must be an integer id, got {v!r}")
    if not 0 <= int(v) < n:
        raise OpError(f"{name} {int(v)} does not exist: the part has {n} {what} (ids 0..{n - 1}); ids change after "
                      f"every edit, use the list returned by the last edit or call list_{what}")
    return int(v)


def select_edge(shape: cq.Shape, edge=None, edge_near=None, edge_direction=None) -> cq.Edge:
    if edge is not None:
        edges = shape.Edges()
        return edges[_index("edge", edge, len(edges), "edges")]
    if edge_near is None:
        raise OpError("give the edge id (`edge`, from list_edges) or a point on it (`edge_near`)")
    return find_edge_near(shape, edge_near, edge_direction)


def find_face_near(shape: cq.Shape, point, normal=None) -> cq.Face:
    """The face closest to `point` (within EDGE_SEARCH_MM); with `normal`, only planar faces whose outward normal
    is within 1 deg of it."""
    p = _point("face_near", point)
    nrm = None if normal is None else _direction("face_normal", normal)
    v = cq.Vertex.makeVertex(*p.tolist())
    cands = []
    for f in shape.Faces():
        if nrm is not None and (f.geomType() != "PLANE" or float(np.array(f.normalAt().toTuple()) @ nrm) < 0.99985):
            continue
        cands.append((f.distance(v), f))
    cands.sort(key=lambda c: c[0])
    if not cands or cands[0][0] > EDGE_SEARCH_MM:
        raise OpError(f"no face within {EDGE_SEARCH_MM} mm of {_fmt(p)}" + ("" if nrm is None else f" with normal {_fmt(nrm)}"))
    if len(cands) > 1 and cands[1][0] - cands[0][0] < EDGE_TIE_MM:
        raise OpError(f"face_near {_fmt(p)} is ambiguous (two faces equally close); move the point onto the face "
                      f"you mean or give face_normal")
    return cands[0][1]


def select_face(shape: cq.Shape, face=None, face_near=None, face_normal=None) -> cq.Face:
    if face is not None:
        faces = shape.Faces()
        return faces[_index("face", face, len(faces), "faces")]
    if face_near is None:
        raise OpError("give the face id (`face`, from list_faces) or a point on it (`face_near`)")
    return find_face_near(shape, face_near, face_normal)


# ---------------------------------------------------------------- ops
def chamfer(shape: cq.Shape, d1, d2=None, edge=None, edge_near=None, edge_direction=None,
            d1_face_normal=None) -> cq.Shape:
    """Chamfer one whole edge. d1 is measured on one adjacent face, d2 (default d1) on the other.

    The d1 face is the adjacent face whose outward normal is closest to d1_face_normal; without it, the adjacent
    face whose normal points most upwards (+z)."""
    d1 = _length("d1", d1)
    d2 = d1 if d2 is None else _length("d2", d2)
    e = select_edge(shape, edge, edge_near, edge_direction)
    faces = adjacent_faces(shape, e)
    if len(faces) != 2:
        raise OpError(f"edge {describe_edge(e)} has {len(faces)} adjacent faces, expected 2")
    mid = e.positionAt(0.5)
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
    mk.Add(d1, d2, e.wrapped, faces[k].wrapped)
    try:
        mk.Build()
        ok = mk.IsDone()
    except Exception:  # noqa: BLE001 - OCC raises various StdFail_* types
        ok = False
    if not ok:
        raise OpError(f"chamfer d1={d1} d2={d2} on edge {describe_edge(e)} failed in the CAD kernel; "
                      f"usually a distance is larger than the adjacent faces allow")
    return _single_solid(cq.Shape.cast(mk.Shape()), "chamfer")


def fillet(shape: cq.Shape, r, edge=None, edge_near=None, edge_direction=None) -> cq.Shape:
    """Round one whole edge with radius r."""
    r = _length("r", r)
    e = select_edge(shape, edge, edge_near, edge_direction)
    mk = BRepFilletAPI_MakeFillet(shape.wrapped)
    mk.Add(r, e.wrapped)
    try:
        mk.Build()
        ok = mk.IsDone()
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        raise OpError(f"fillet r={r} on edge {describe_edge(e)} failed in the CAD kernel; usually the radius is larger "
                      f"than the adjacent faces allow")
    return _single_solid(cq.Shape.cast(mk.Shape()), "fillet")


def offset_face(shape: cq.Shape, d, face=None, face_near=None, face_normal=None) -> cq.Shape:
    """Move one planar face along its outward normal by d (d > 0 adds material, d < 0 removes it): the prism swept
    by the face is added or cut."""
    d = _length("d", d, positive=False)
    if d == 0:
        raise OpError("d must not be 0")
    f = select_face(shape, face, face_near, face_normal)
    if f.geomType() != "PLANE":
        raise OpError(f"offset_face works on planar faces only; this face is a {f.geomType().lower()}")
    n = np.array(f.normalAt().toTuple())
    prism = cq.Solid.extrudeLinear(f, cq.Vector(*(n * d).tolist()))
    before = shape.Volume()
    out = shape.fuse(prism) if d > 0 else shape.cut(prism)
    out = _single_solid(out.clean() if hasattr(out, "clean") else out, "offset_face")
    if abs(out.Volume() - before) < MIN_REMOVED_MM3:
        raise OpError("offset_face changed nothing")
    return out


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


def _box_solid(origin, edges) -> cq.Shape:
    o = _point("origin", origin)
    if not isinstance(edges, (list, tuple)) or len(edges) != 3:
        raise OpError("edges must be three vectors [[ax, ay, az], [bx, by, bz], [cx, cy, cz]] (box edges from origin)")
    e = [np.array([_snap(_number(f"edges[{i}][{k}]", c)) for k, c in enumerate(_vec3(f"edges[{i}]", v))])
         for i, v in enumerate(edges)]
    lens = [float(np.linalg.norm(v)) for v in e]
    if min(lens) < SNAP_MM:
        raise OpError("every box edge must be longer than 0.001 mm")
    u = [v / ln for v, ln in zip(e, lens)]
    for i, j in ((0, 1), (0, 2), (1, 2)):
        if abs(float(u[i] @ u[j])) > 1e-3:
            raise OpError(f"box edges {i} and {j} must be perpendicular (|cos| = {abs(float(u[i] @ u[j])):.4f})")
    sign = 1.0 if float(np.cross(u[2], u[0]) @ u[1]) > 0 else -1.0     # plane y = normal x x_dir
    plane = cq.Plane(origin=tuple(o.tolist()), xDir=tuple(u[0].tolist()), normal=tuple(u[2].tolist()))
    pts = [(0.0, 0.0), (lens[0], 0.0), (lens[0], sign * lens[1]), (0.0, sign * lens[1])]
    return cq.Workplane(plane).polyline(pts).close().extrude(lens[2]).val()


def _vec3(name, v):
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise OpError(f"{name} must be a list of 3 numbers, got {v!r}")
    return v


def cut_box(shape: cq.Shape, origin, edges) -> cq.Shape:
    """Remove a box (corner `origin` + three perpendicular edge vectors) from the part."""
    before = shape.Volume()
    out = _single_solid(cq.Workplane().add(shape).cut(_box_solid(origin, edges)).val(), "cut_box")
    if before - out.Volume() < MIN_REMOVED_MM3:
        raise OpError("cut_box removed no material: the box does not intersect the part")
    return out


def add_box(shape: cq.Shape, origin, edges) -> cq.Shape:
    """Add a box (corner `origin` + three perpendicular edge vectors) to the part; it must touch or overlap it."""
    before = shape.Volume()
    out = _single_solid(cq.Workplane().add(shape).union(_box_solid(origin, edges)).val(), "add_box")
    if out.Volume() - before < MIN_REMOVED_MM3:
        raise OpError("add_box added no material (the box lies inside the part)")
    return out


# ---------------------------------------------------------------- registry
P, V, N, I, POLY, EDGES = "point", "vector", "number", "integer", "polygon", "box_edges"
EDGE_SEL = [("edge", I, False, "edge id from list_edges / the last edit's result (ids change after every edit)"),
            ("edge_near", P, False, "a point on or near the edge [x, y, z] (mm, world); used if `edge` is not given; "
                                    "the nearest edge within 1 mm is taken"),
            ("edge_direction", V, False, "with edge_near: only straight edges parallel to this direction (within 1 deg)")]
FACE_SEL = [("face", I, False, "face id from list_faces / the last edit's result (ids change after every edit)"),
            ("face_near", P, False, "a point on or near the face [x, y, z]; used if `face` is not given"),
            ("face_normal", V, False, "with face_near: only planar faces with this outward normal (within 1 deg)")]
OP_SPECS = {
    "chamfer": (chamfer, "Chamfer one whole edge of an editable part (asymmetric allowed).", [
        ("d1", N, True, "chamfer distance (mm) on the d1 face"),
        ("d2", N, False, "chamfer distance (mm) on the other adjacent face (default d1)"),
        *EDGE_SEL,
        ("d1_face_normal", V, False, "picks the d1 face: the adjacent face whose outward normal is closest to this "
                                     "direction (default: the adjacent face pointing most towards +z)")]),
    "fillet": (fillet, "Round one whole edge of an editable part.", [
        ("r", N, True, "radius (mm)"), *EDGE_SEL]),
    "offset_face": (offset_face, "Move one planar face along its outward normal (push / pull).", [
        ("d", N, True, "distance (mm): > 0 adds material outwards, < 0 removes material"), *FACE_SEL]),
    "extrude_cut": (extrude_cut, "Sketch a polygon on a plane and cut the prism it sweeps along the plane normal.", [
        ("origin", P, True, "point on the sketch plane = (u, v) origin [x, y, z]"),
        ("normal", V, True, "sketch plane normal = extrusion direction"),
        ("x_dir", V, True, "direction of the sketch u axis, perpendicular to normal; v axis = normal x x_dir"),
        ("polygon_2d", POLY, True, "simple polygon [[u, v], ...] in the sketch plane (mm, >= 3 points)"),
        ("depth_from", N, True, "start of the prism along the normal, measured from origin (mm, may be negative)"),
        ("depth_to", N, True, "end of the prism along the normal (mm, > depth_from)")]),
    "cut_box": (cut_box, "Remove a box from an editable part.", [
        ("origin", P, True, "one corner of the box [x, y, z]"),
        ("edges", EDGES, True, "three perpendicular edge vectors from that corner [[..], [..], [..]] (mm)")]),
    "add_box": (add_box, "Add a box of material to an editable part (must touch or overlap it).", [
        ("origin", P, True, "one corner of the box [x, y, z]"),
        ("edges", EDGES, True, "three perpendicular edge vectors from that corner [[..], [..], [..]] (mm)")]),
}
OPS = {name: (fn, {p[0] for p in params if p[2]}, {p[0] for p in params if not p[2]})
       for name, (fn, _, params) in OP_SPECS.items()}


def apply_op(shapes: dict, op: dict, editable, default_part: str | None = None) -> tuple[str, cq.Shape]:
    """Apply one op dict to a copy of the named part. Returns (part name, new shape); `shapes` is unchanged."""
    if not isinstance(op, dict):
        raise OpError(f"each operation must be an object, got {op!r}")
    name = op.get("op")
    if name not in OPS:
        raise OpError(f"unknown op {name!r}; available: {sorted(OPS)}")
    fn, required, optional = OPS[name]
    keys = {k for k, v in op.items() if v is not None} - {"op", "part"}
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
