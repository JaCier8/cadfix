"""Assembly data model. Generic: parts, one revolute joint, zones as regions; no scenario names.

Everything is in the world frame (units mm, degrees). A task directory holds task.json (this model as data) and
parts/<name>.step. Meshes are tessellated lazily from the B-rep and cached per part.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import cadquery as cq
import manifold3d
import numpy as np

from cadfix.core import kernel

CYLINDER_SEGMENTS = 128


@dataclass(frozen=True)
class Region:
    """A solid region in world coordinates.

    box:      corner `origin` + three edge vectors `edges` (a parallelepiped, right-handed order)
    cylinder: axis from `p0` to `p1`, `radius`
    """
    kind: str
    origin: tuple = ()
    edges: tuple = ()
    p0: tuple = ()
    p1: tuple = ()
    radius: float = 0.0

    @staticmethod
    def from_dict(d: dict) -> "Region":
        if d["kind"] == "box":
            return Region("box", origin=tuple(d["origin"]), edges=tuple(tuple(e) for e in d["edges"]))
        if d["kind"] == "cylinder":
            return Region("cylinder", p0=tuple(d["p0"]), p1=tuple(d["p1"]), radius=float(d["radius"]))
        raise ValueError(f"unknown region kind {d['kind']!r}")

    def to_dict(self) -> dict:
        if self.kind == "box":
            return {"kind": "box", "origin": list(self.origin), "edges": [list(e) for e in self.edges]}
        return {"kind": "cylinder", "p0": list(self.p0), "p1": list(self.p1), "radius": self.radius}

    def to_manifold(self) -> manifold3d.Manifold:
        if self.kind == "box":
            return kernel.oriented_box(self.origin, self.edges)
        p0, p1 = np.asarray(self.p0, float), np.asarray(self.p1, float)
        h = float(np.linalg.norm(p1 - p0))
        axes = kernel.orthonormal_axes(p1 - p0)        # rows x, y, z(axis) in world
        mat = np.hstack([axes.T, p0.reshape(3, 1)])    # frame -> world
        return manifold3d.Manifold.cylinder(h, self.radius, self.radius, CYLINDER_SEGMENTS).transform(mat.tolist())


@dataclass(frozen=True)
class Zone:
    """Named keep-in (material must stay) or keep-out (no material may enter) region of a part, given at the
    joint's closed pose (zones of moving parts move with them)."""
    name: str
    kind: str          # "keep_in" | "keep_out"
    part: str          # part the zone belongs to / moves with
    region: Region
    parts: tuple = ()  # keep_out: parts whose material must stay out (default: all editable parts)
    description: str = ""

    @staticmethod
    def from_dict(d: dict) -> "Zone":
        return Zone(d["name"], d["kind"], d["part"], Region.from_dict(d["region"]), tuple(d.get("parts", ())),
                    d.get("description", ""))

    def to_dict(self) -> dict:
        out = {"name": self.name, "kind": self.kind, "part": self.part, "region": self.region.to_dict()}
        if self.parts:
            out["parts"] = list(self.parts)
        if self.description:
            out["description"] = self.description
        return out


@dataclass(frozen=True)
class Joint:
    """Revolute joint: `moving` parts rotate together about the axis (point, direction), positive angles by the
    right-hand rule, over range_deg."""
    name: str
    moving: tuple
    fixed: tuple
    axis_point: tuple
    axis_direction: tuple
    range_deg: tuple
    step_deg: float = 1.0
    type: str = "revolute"

    @staticmethod
    def from_dict(d: dict) -> "Joint":
        return Joint(d.get("name", "joint"), tuple(d["moving"]), tuple(d["fixed"]), tuple(d["axis_point"]),
                     tuple(d["axis_direction"]), tuple(d["range_deg"]), float(d.get("step_deg", 1.0)),
                     d.get("type", "revolute"))

    def to_dict(self) -> dict:
        return {"name": self.name, "type": self.type, "moving": list(self.moving), "fixed": list(self.fixed),
                "axis_point": list(self.axis_point), "axis_direction": list(self.axis_direction),
                "range_deg": list(self.range_deg), "step_deg": self.step_deg}

    def matrix(self, angle_deg: float) -> np.ndarray:
        return kernel.rotation_matrix(self.axis_point, self.axis_direction, angle_deg)


@dataclass
class Part:
    name: str
    shape: cq.Shape
    editable: bool
    role: str = ""
    build_up: tuple | None = None   # print orientation: build direction ("up" on the printer), world
    print_rule: str = ""
    _mesh: manifold3d.Manifold | None = field(default=None, repr=False)

    @property
    def mesh(self) -> manifold3d.Manifold:
        if self._mesh is None:
            self._mesh = kernel.to_manifold(self.shape)
        return self._mesh

    def with_shape(self, shape: cq.Shape) -> "Part":
        return replace(self, shape=shape, _mesh=None)


@dataclass
class Assembly:
    parts: dict
    joint: Joint
    zones: list
    meta: dict = field(default_factory=dict)

    @property
    def editable(self) -> list[str]:
        return [n for n, p in self.parts.items() if p.editable]

    def meshes(self, names=None) -> dict:
        return {n: self.parts[n].mesh for n in (names or self.parts)}

    def with_shapes(self, shapes: dict) -> "Assembly":
        """Copy with some parts' shapes replaced (unchanged parts keep their cached meshes)."""
        parts = dict(self.parts)
        for n, s in shapes.items():
            parts[n] = parts[n].with_shape(s)
        return Assembly(parts, self.joint, self.zones, self.meta)

    # ------------------------------------------------------------ io
    @staticmethod
    def load(task_dir, parts_dir=None) -> "Assembly":
        """task.json from task_dir; STEP parts from parts_dir (default task_dir/parts)."""
        task_dir = Path(task_dir)
        task = json.loads((task_dir / "task.json").read_text())
        parts_dir = Path(parts_dir) if parts_dir is not None else task_dir / "parts"
        parts = {}
        for name, d in task["parts"].items():
            shape = kernel.import_step(parts_dir / f"{name}.step")
            pr = d.get("print") or {}
            parts[name] = Part(name, shape, bool(d["editable"]), d.get("role", ""),
                               tuple(pr["build_up"]) if pr.get("build_up") else None, pr.get("rule", ""))
        return Assembly(parts, Joint.from_dict(task["joint"]), [Zone.from_dict(z) for z in task["zones"]],
                        {k: v for k, v in task.items() if k not in ("parts", "joint", "zones")})

    def task_dict(self) -> dict:
        parts = {}
        for n, p in self.parts.items():
            d = {"editable": p.editable, "role": p.role, "file": f"parts/{n}.step"}
            if p.build_up is not None:
                d["print"] = {"rule": p.print_rule, "build_up": list(p.build_up)}
            parts[n] = d
        return {**self.meta, "parts": parts, "joint": self.joint.to_dict(), "zones": [z.to_dict() for z in self.zones]}
