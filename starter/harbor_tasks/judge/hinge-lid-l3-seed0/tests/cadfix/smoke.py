"""Smoke check of the geometry stack: CadQuery B-rep -> STEP -> re-import -> mesh -> manifold3d.

Run: python -m cadfix.smoke
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import cadquery as cq

from cadfix.core.kernel import to_manifold


@dataclass
class SmokeResult:
    box_volume: float       # plain box, analytic
    brep_volume: float      # filleted box after STEP round trip, from OpenCascade
    mesh_volume: float      # same solid tessellated and loaded into manifold3d
    brep_valid: bool
    manifold_status: str
    n_triangles: int

    @property
    def rel_diff(self) -> float:
        return abs(self.mesh_volume - self.brep_volume) / self.brep_volume


def run(size=(40.0, 30.0, 20.0), fillet_r: float = 3.0) -> SmokeResult:
    box = cq.Workplane("XY").box(*size)
    filleted = box.edges("|Z and >X and >Y").fillet(fillet_r)  # exactly one vertical edge

    with tempfile.TemporaryDirectory() as d:
        step = Path(d) / "part.step"
        cq.exporters.export(filleted, str(step))
        solid = cq.importers.importStep(str(step)).val()

    m = to_manifold(solid)
    return SmokeResult(
        box_volume=size[0] * size[1] * size[2],
        brep_volume=solid.Volume(),
        mesh_volume=m.volume(),
        brep_valid=solid.isValid(),
        manifold_status=str(m.status()),
        n_triangles=m.num_tri(),
    )


if __name__ == "__main__":
    r = run()
    print(f"cadquery {cq.__version__}, manifold3d {version('manifold3d')}")
    print(f"plain box volume      : {r.box_volume:.4f} mm^3")
    print(f"B-rep volume (OCC)    : {r.brep_volume:.4f} mm^3  valid={r.brep_valid}")
    print(f"mesh volume (manifold): {r.mesh_volume:.4f} mm^3  status={r.manifold_status} tris={r.n_triangles}")
    print(f"relative difference   : {r.rel_diff * 100:.4f} %")
