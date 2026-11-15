"""Edge and face descriptions in world coordinates, and geometric queries that do not depend on ids. Generic.

Ids are positions in the part's current edge / face list (shape.Edges() / shape.Faces() order). They change after
every edit; every edit returns the fresh lists. Coordinates are rounded to 0.001 mm, directions to 1e-4.
"""
from __future__ import annotations

import cadquery as cq
import numpy as np

ROUND = 3


def _p(v) -> list[float]:
    return [round(float(x), ROUND) + 0.0 for x in (v.toTuple() if hasattr(v, "toTuple") else v)]


def _d(v) -> list[float]:
    a = np.asarray(v.toTuple() if hasattr(v, "toTuple") else v, dtype=float)
    n = np.linalg.norm(a)
    return [round(float(x), 4) + 0.0 for x in (a / n if n > 0 else a)]


class Topology:
    """Edges, faces and the edge -> adjacent faces map of one shape (built once per shape version)."""

    def __init__(self, shape: cq.Shape):
        self.shape = shape
        self.edges = shape.Edges()
        self.faces = shape.Faces()
        self._edge_faces = None

    def edge_faces(self, i: int) -> list[int]:
        if self._edge_faces is None:
            m = {}
            for fi, f in enumerate(self.faces):
                for e in f.Edges():
                    m.setdefault(e.hashCode(), []).append((fi, e))
            self._edge_faces = []
            for e in self.edges:
                self._edge_faces.append(sorted({fi for fi, fe in m.get(e.hashCode(), []) if fe.isSame(e)}))
        return self._edge_faces[i]

    # ------------------------------------------------------------ descriptions
    def face_normal(self, fi: int, at=None) -> list[float]:
        f = self.faces[fi]
        return _d(f.normalAt(cq.Vector(*at)) if at is not None else f.normalAt())

    def describe_edge(self, i: int) -> dict:
        e = self.edges[i]
        kind = e.geomType().lower()
        d = {"id": i, "type": kind, "start": _p(e.startPoint()), "end": _p(e.endPoint()),
             "length": round(e.Length(), ROUND)}
        if kind == "circle":
            d["center"], d["radius"] = _p(e.Center()), round(e.radius(), ROUND)
        mid = e.positionAt(0.5)
        d["faces"] = [{"id": fi, "normal_at_mid": self.face_normal(fi, mid.toTuple())} for fi in self.edge_faces(i)]
        return d

    def describe_face(self, i: int) -> dict:
        f = self.faces[i]
        kind = f.geomType().lower()
        bb = f.BoundingBox()
        d = {"id": i, "type": kind, "center": _p(f.Center()), "area": round(f.Area(), ROUND),
             "bbox": [_p((bb.xmin, bb.ymin, bb.zmin)), _p((bb.xmax, bb.ymax, bb.zmax))]}
        if kind == "plane":
            d["normal"] = self.face_normal(i)
        elif kind == "cylinder":
            cyl = f._geomAdaptor().Cylinder()
            ax = cyl.Axis()
            d["axis_point"] = _p((ax.Location().X(), ax.Location().Y(), ax.Location().Z()))
            d["axis_direction"] = _d((ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()))
            d["radius"] = round(cyl.Radius(), ROUND)
        return d

    # ------------------------------------------------------------ queries
    def _edge_ok(self, e: cq.Edge, direction) -> bool:
        if direction is None:
            return True
        if e.geomType() != "LINE":
            return False
        t = np.array((e.endPoint() - e.startPoint()).toTuple())
        return abs(abs(t @ direction) / np.linalg.norm(t) - 1.0) <= 1.5e-4       # within ~1 deg

    def edges_near(self, point, direction=None, radius: float = 1.0) -> list[tuple[float, int]]:
        v = cq.Vertex.makeVertex(*[float(x) for x in point])
        d = None if direction is None else np.asarray(direction, float) / np.linalg.norm(direction)
        out = [(e.distance(v), i) for i, e in enumerate(self.edges) if self._edge_ok(e, d)]
        return sorted((dist, i) for dist, i in out if dist <= radius)

    def faces_near(self, point, normal=None, radius: float = 1.0, max_angle_deg: float = 1.0) -> list[tuple[float, int]]:
        v = cq.Vertex.makeVertex(*[float(x) for x in point])
        n = None if normal is None else np.asarray(normal, float) / np.linalg.norm(normal)
        out = []
        for i, f in enumerate(self.faces):
            dist = f.distance(v)
            if dist > radius:
                continue
            if n is not None:
                if f.geomType() != "PLANE" or float(np.dot(self.face_normal(i), n)) < np.cos(np.radians(max_angle_deg)):
                    continue
            out.append((dist, i))
        return sorted(out)

    def list_edges(self, near=None, radius=None) -> list[dict]:
        ids = range(len(self.edges)) if near is None else [i for _, i in self.edges_near(near, None, radius or 5.0)]
        return [self.describe_edge(i) for i in ids]

    def list_faces(self, near=None, radius=None) -> list[dict]:
        ids = range(len(self.faces)) if near is None else [i for _, i in self.faces_near(near, None, radius or 5.0)]
        return [self.describe_face(i) for i in ids]
