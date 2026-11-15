"""Generic edit ops: chamfer (asymmetric, face choice) and extrude_cut (plane frame, depth range), validation."""
import math

import cadquery as cq
import numpy as np
import pytest

from cadfix.core import kernel
from cadfix.ops import edit
from cadfix.ops.edit import OpError

BOX = cq.Workplane().box(20, 10, 8, centered=False).val()      # x 0..20, y 0..10, z 0..8


def test_chamfer_asymmetric_default_d1_on_upper_face():
    out = edit.chamfer(BOX, edge_near=[10, 10, 8], d1=1.0, d2=3.0)        # top rear edge, d1 along the top face
    assert out.isValid()
    assert BOX.Volume() - out.Volume() == pytest.approx(0.5 * 1.0 * 3.0 * 20)
    top = [f for f in out.Faces() if f.normalAt().z > 0.99][0]
    assert top.BoundingBox().ymax == pytest.approx(9.0)          # top shortened by d1
    out2 = edit.chamfer(BOX, edge_near=[10, 10, 8], d1=1.0, d2=3.0, d1_face_normal=[0, 1, 0])
    top2 = [f for f in out2.Faces() if f.normalAt().z > 0.99][0]
    assert top2.BoundingBox().ymax == pytest.approx(7.0)         # d1 on the rear face, d2 = 3 on the top


def test_chamfer_errors_are_readable():
    with pytest.raises(OpError, match="no edge within"):
        edit.chamfer(BOX, edge_near=[10, 5, 4], d1=1)
    with pytest.raises(OpError, match="ambiguous"):
        edit.chamfer(BOX, edge_near=[0, 0, 0], d1=1)                       # a corner: three edges at distance 0
    with pytest.raises(OpError, match="failed in the CAD kernel"):
        edit.chamfer(BOX, edge_near=[10, 10, 8], d1=1, d2=20)
    with pytest.raises(OpError, match="matches neither"):
        edit.chamfer(BOX, edge_near=[10, 10, 8], d1=1, d2=2, d1_face_normal=[0, -1, 0])
    with pytest.raises(OpError, match="> 0"):
        edit.chamfer(BOX, edge_near=[10, 10, 8], d1=-1)


def test_edge_direction_resolves_a_corner():
    out = edit.chamfer(BOX, edge_near=[0, 0, 0], d1=1, edge_direction=[1, 0, 0])
    assert BOX.Volume() - out.Volume() == pytest.approx(0.5 * 20)


def test_extrude_cut_plane_frame_and_depths():
    # plane through the top rear edge at x=5, normal +x: u along +y, v along +z (= normal x x_dir)
    out = edit.extrude_cut(BOX, origin=[5, 10, 8], normal=[1, 0, 0], x_dir=[0, 1, 0],
                           polygon_2d=[[-1, 0], [0.01, 0.01], [0, -3]], depth_from=0, depth_to=4)
    assert BOX.Volume() - out.Volume() == pytest.approx(0.5 * 1 * 3 * 4, rel=1e-6)
    bb = kernel.bbox(kernel.to_manifold(BOX) - kernel.to_manifold(out))
    assert np.allclose(bb[0], [5, 9, 5], atol=1e-6) and np.allclose(bb[1], [9, 10, 8], atol=1e-6)
    # the same cut from the other side: normal -x, depth range 1..5 from x=10 -> x 5..9
    out2 = edit.extrude_cut(BOX, origin=[10, 10, 8], normal=[-1, 0, 0], x_dir=[0, 1, 0],
                            polygon_2d=[[-1, 0], [0.01, -0.01], [0, 3]], depth_from=1, depth_to=5)
    bb2 = kernel.bbox(kernel.to_manifold(BOX) - kernel.to_manifold(out2))
    assert np.allclose(bb2[0], bb[0], atol=1e-6) and np.allclose(bb2[1], bb[1], atol=1e-6)


def test_extrude_cut_validation():
    ok = dict(origin=[5, 10, 8], normal=[1, 0, 0], x_dir=[0, 1, 0], polygon_2d=[[-1, 0], [0, 0], [0, -1]],
              depth_from=0, depth_to=1)
    for bad, msg in ((dict(x_dir=[1, 1, 0]), "perpendicular"), (dict(normal=[0, 0, 0]), "zero vector"),
                     (dict(polygon_2d=[[0, 0], [1, 1]]), "at least 3"),
                     (dict(polygon_2d=[[0, 0], [1, 1], [1, 0], [0, 1]]), "simple"),
                     (dict(depth_to=0), "larger than"), (dict(origin=[50, 50, 50]), "removed no material"),
                     (dict(origin=[1, 2]), "3 numbers"), (dict(depth_to=float("nan")), "finite")):
        with pytest.raises(OpError, match=msg):
            edit.extrude_cut(BOX, **(ok | bad))
    # a slot through the whole part splits it (normal +y, x_dir +x -> v runs along -z)
    with pytest.raises(OpError, match="separate solids"):
        edit.extrude_cut(BOX, origin=[10, -1, 9], normal=[0, 1, 0], x_dir=[1, 0, 0],
                         polygon_2d=[[-0.5, 0], [0.5, 0], [0.5, 10], [-0.5, 10]], depth_from=0, depth_to=12)


def test_apply_ops_dispatch_and_errors():
    shapes = {"a": BOX, "b": BOX}
    new, log = edit.apply_ops(shapes, [{"op": "chamfer", "part": "a", "edge_near": [10, 10, 8], "d1": 1}], ["a"])
    assert new["b"] is BOX and new["a"] is not BOX and log[0]["removed_mm3"] == pytest.approx(10.0)
    assert shapes["a"] is BOX                                    # input untouched
    for ops, msg in (([{"op": "loft"}], "unknown op"), ([{"op": "chamfer", "edge_near": [0, 0, 0]}], "missing"),
                     ([{"op": "chamfer", "part": "b", "edge_near": [10, 10, 8], "d1": 1}], "not editable"),
                     ([{"op": "chamfer", "part": "a", "edge_near": [10, 10, 8], "d1": 1, "r": 2}], "unknown"),
                     ({"op": "chamfer"}, "JSON list")):
        with pytest.raises(OpError, match=msg):
            edit.apply_ops(shapes, ops, ["a"], default_part="a")


def test_fillet_offset_face_boxes_and_ids():
    out = edit.fillet(BOX, 1.0, edge_near=[10, 10, 8])
    assert BOX.Volume() - out.Volume() == pytest.approx((1 - math.pi / 4) * 20, rel=1e-3)
    top = edit.select_face(BOX, face_near=[10, 5, 8], face_normal=[0, 0, 1])
    assert edit.offset_face(BOX, -0.5, face_near=[10, 5, 8]).Volume() == pytest.approx(BOX.Volume() - 0.5 * 200)
    assert edit.offset_face(BOX, 1.0, face_near=[10, 5, 8]).Volume() == pytest.approx(BOX.Volume() + 200)
    fid = [i for i, f in enumerate(BOX.Faces()) if f.isSame(top)][0]
    assert edit.offset_face(BOX, -0.5, face=fid).Volume() == pytest.approx(BOX.Volume() - 100)
    eid = [i for i, e in enumerate(BOX.Edges()) if e.isSame(edit.find_edge_near(BOX, [10, 10, 8]))][0]
    assert edit.chamfer(BOX, 1.0, d2=3.0, edge=eid).Volume() == pytest.approx(BOX.Volume() - 30)
    with pytest.raises(OpError, match="does not exist"):
        edit.chamfer(BOX, 1.0, edge=999)
    with pytest.raises(OpError, match="planar faces only"):
        edit.offset_face(edit.fillet(BOX, 1.0, edge_near=[10, 10, 8]), 0.2, face_near=[10, 9.71, 7.71])
    # oriented boxes: rotated 45 deg about z, cut and add
    e = [[math.sqrt(0.5) * 2, math.sqrt(0.5) * 2, 0], [-math.sqrt(0.5), math.sqrt(0.5), 0], [0, 0, 1]]
    assert BOX.Volume() - edit.cut_box(BOX, [5, 5, 7.5], e).Volume() == pytest.approx(0.5 * 2.0, rel=1e-3)
    assert edit.add_box(BOX, [5, 5, 7.5], e).Volume() - BOX.Volume() == pytest.approx(0.5 * 2.0, rel=1e-3)
    with pytest.raises(OpError, match="perpendicular"):
        edit.cut_box(BOX, [5, 5, 7], [[1, 0, 0], [1, 1, 0], [0, 0, 1]])
    with pytest.raises(OpError, match="removed no material"):
        edit.cut_box(BOX, [50, 50, 50], [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
