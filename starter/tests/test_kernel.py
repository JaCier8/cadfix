import cadquery as cq
import manifold3d
import numpy as np
import pytest

from cadfix.core import kernel


def cube(lo, hi):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    return manifold3d.Manifold.cube((hi - lo).tolist()).translate(lo.tolist())


def test_rotate_box_about_offset_axis():
    m = cube((0, 0, 0), (2, 1, 1))
    # 90 deg about the z axis through (1, 0, 0): x-extent [0,2] becomes y-extent [-1, 1]
    r = kernel.rotate(m, (1, 0, 0), (0, 0, 1), 90)
    lo, hi = kernel.bbox(r)
    assert np.allclose(lo, (0, -1, 0), atol=1e-9) and np.allclose(hi, (1, 1, 1), atol=1e-9)
    assert r.volume() == pytest.approx(2.0)


def test_rotation_direction_follows_right_hand_rule():
    # +90 about -x (= opening direction in hinge_lid) takes +y to -z
    p = kernel.rotate_points([[0, 1, 0]], (0, 0, 0), (-1, 0, 0), 90)[0]
    assert np.allclose(p, (0, 0, -1), atol=1e-12)


def test_intersection_volume_and_bbox():
    vol, bb = kernel.intersection(cube((0, 0, 0), (2, 2, 2)), cube((1, 1, 1), (3, 3, 3)))
    assert vol == pytest.approx(1.0)
    assert bb == ([1, 1, 1], [2, 2, 2])


def test_touching_is_not_colliding():
    assert kernel.intersection(cube((0, 0, 0), (1, 1, 1)), cube((1, 0, 0), (2, 1, 1))) == (0.0, None)


def test_intersection_components():
    a = cube((0, 0, 0), (10, 1, 1))
    b = cube((1, 0, 0), (2, 1, 1)) + cube((5, 0, 0), (7, 1, 1))
    pieces = kernel.intersection_components(a, b)
    assert sorted(round(p["volume"], 6) for p in pieces) == [1.0, 2.0]


def test_tessellation_matches_brep(tmp_path):
    shape = cq.Workplane().box(20, 10, 8).faces(">Z").workplane().hole(4).val()
    kernel.export_step(shape, tmp_path / "s.step")
    back = kernel.import_step(tmp_path / "s.step")
    m = kernel.to_manifold(back)
    assert abs(m.volume() - back.Volume()) / back.Volume() < 1e-3


# ---------------------------------------------------------------- joint sweeps
BAR = cube((0, -0.5, 0), (10, 0.5, 10))     # rotates about +z through the origin (counter-clockwise)
Z = ((0, 0, 0), (0, 0, 1))


def test_first_contact_sweep_matches_analytic_angle():
    block = cube((5, 3, 0), (6, 4, 10))
    # the bar's leading face (y = +0.5) first reaches the block corner (6, 3):
    # theta = atan2(3, 6) - asin(0.5 / |(6, 3)|) = 22.30 deg; 1e-3 mm3 of overlap needs a little more
    fc = kernel.first_contact_sweep({"bar": BAR}, {"block": block}, *Z, 0, 180, 1.0, 0.1)
    assert fc["coarse_angle"] == 23.0
    assert 22.3 <= fc["angle"] <= 22.6
    assert [(c["moving"], c["fixed"]) for c in fc["contacts"]] == [("bar", "block")]
    assert fc["volume"] > kernel.VOL_EPS


def test_first_contact_sweep_none_and_pair_choice():
    far = cube((20, 3, 0), (21, 4, 10))
    assert kernel.first_contact_sweep({"bar": BAR}, {"far": far}, *Z, 0, 180) is None
    near, later = cube((5, 3, 0), (6, 4, 10)), cube((-4, 3, 0), (-3, 4, 10))   # later = at ~127 deg
    fc = kernel.first_contact_sweep({"bar": BAR}, {"later": later, "near": near}, *Z, 0, 180)
    assert [c["fixed"] for c in fc["contacts"]] == ["near"]


def test_first_contact_at_start_angle():
    fc = kernel.first_contact_sweep({"bar": BAR}, {"inside": cube((2, -1, 0), (3, 1, 1))}, *Z, 0, 10)
    assert fc["angle"] == 0.0 and fc["coarse_angle"] == 0.0


def test_clearance_sweep_gap_cap_touch_overlap():
    m = {"c": cube((0, 0, 0), (1, 1, 1))}
    res = kernel.clearance_sweep(m, {"f": cube((1.2, 0, 0), (2, 1, 1))}, *Z, [0.0], search=0.35)
    assert res[0]["gap"] == pytest.approx(0.2, abs=1e-9) and res[0]["pair"] == ("c", "f")
    res = kernel.clearance_sweep(m, {"f": cube((2, 0, 0), (3, 1, 1))}, *Z, [0.0], search=0.35)
    assert res[0]["gap"] == 0.35 and res[0]["pair"] is None        # beyond the search radius: capped
    res = kernel.clearance_sweep(m, {"f": cube((1, 0, 0), (2, 1, 1))}, *Z, [0.0], search=0.35)
    assert res[0]["gap"] == 0.0 and res[0]["overlap"] == 0.0        # touching only
    res = kernel.clearance_sweep(m, {"f": cube((0.5, 0, 0), (2, 1, 1))}, *Z, [0.0, 90.0], search=0.35)
    assert res[0]["overlap"] == pytest.approx(0.5)                 # overlapping
    assert res[1]["gap"] == 0.35                                   # rotated 90 deg away to x in [-1, 0]


def test_clearance_sweep_rotated_gap():
    # cube [0,1]^2 rotated 90 deg about z -> x in [-1, 0]; fixed block at x in [-1.3 - 1, -1.3]: gap 0.3
    res = kernel.clearance_sweep({"c": cube((0, 0, 0), (1, 1, 1))}, {"f": cube((-2.3, 0, 0), (-1.3, 1, 1))},
                                 *Z, [90.0], search=0.35)
    assert res[0]["gap"] == pytest.approx(0.3, abs=1e-6)


def test_changed_volume_and_downward_area():
    a, b = cube((0, 0, 0), (2, 1, 1)), cube((1, 0, 0), (3, 1, 1))
    assert kernel.changed_volume(a, b) == (pytest.approx(1.0), pytest.approx(1.0))
    assert kernel.downward_area(a) == pytest.approx(2.0)            # the bottom face
    assert kernel.box_overlap_volume(a, (0.5, 0, 0), (1.5, 1, 1)) == pytest.approx(1.0)
