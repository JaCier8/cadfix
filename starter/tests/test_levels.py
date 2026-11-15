"""Levels in the generator: L2 = L1 parts, L3 = three different ribs placed with a world pose.

The 3D facts are checked on the STEP parts as written (world frame), using the world axis from params.json."""
import json

import numpy as np
import pytest

from cadfix.core import kernel
from marks import slow_except
from scenarios.hinge_lid import generator

SEEDS = slow_except(range(10), keep={0})


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("levels")


@pytest.fixture(scope="module")
def written(out_dir):
    cache = {}

    def get(level, seed):
        if (level, seed) not in cache:
            d = generator.write(seed, out_dir, level)
            info = json.loads((d / "params.json").read_text())
            shapes = {n: kernel.import_step(d / f"{n}.step") for n in generator.PART_NAMES}
            cache[level, seed] = (d, info, shapes)
        return cache[level, seed]
    return get


@pytest.mark.parametrize("seed", SEEDS)
def test_l2_has_the_l1_geometry(seed):
    p1, f1, r1 = generator.resolve_seed(seed, "L1")
    p2, f2, r2 = generator.resolve_seed(seed, "L2")
    assert generator.dataclasses.replace(p2, level="L1") == p1 and r1 == r2
    assert f1["scan"] == f2["scan"] and f1["ribs"] == f2["ribs"]
    assert p1.pose is None and p1.ribs is None


@pytest.mark.parametrize("seed", SEEDS)
def test_l3_ribs_differ_collide_and_are_fixable(seed):
    p, f, rejected = generator.resolve_seed(seed, "L3")
    assert p.seed == seed + generator.REPLACE_STRIDE * len(rejected)
    assert p.n_knuckles == 7 and len(p.lid_segments()) == 3 and len(set(p.rib_profiles())) == 3
    assert not f["reasons"] and f["feasible"] and f["plate_clear"]
    for fa in f["rib_facts"]:   # every rib collides while opening, inside the accepted window
        assert generator.ANGLE_WINDOW[0] <= fa["predicted_first_collision_deg"] <= generator.ANGLE_WINDOW[1]
    # the trap: identical reliefs sized for the worst rib need >= 1.4 x V_ref (scenario.json 0.7)
    assert f["V_identical_mm3"] / f["V_ref_mm3"] >= generator.L3_MIN_IDENTICAL_RATIO == 1.4
    pose = p.pose
    assert 15 <= pose.yaw_deg <= 40 and 0 <= pose.tilt_deg <= 8
    assert all(20 <= abs(o) <= 200 for o in pose.offset)


@pytest.mark.parametrize("seed", SEEDS)
def test_l3_world_frame_is_consistent(seed, written):
    d, info, shapes = written("L3", seed)
    p = generator.HingeLidParams(**{k: v for k, v in info["params"].items() if k not in ("pose", "ribs")},
                                 ribs=tuple(tuple(r) for r in info["params"]["ribs"]),
                                 pose=generator.Pose(**{**info["params"]["pose"],
                                                        "offset": tuple(info["params"]["pose"]["offset"])}))
    m = p.pose_matrix()
    local = generator.build_parts_local(p)
    for n in generator.PART_NAMES:   # world part = local part placed by the pose (same volume, moved bbox)
        assert shapes[n].Volume() == pytest.approx(local[n].Volume(), rel=1e-6)
        back = kernel.transform_shape(shapes[n], kernel.invert(m)).BoundingBox()
        lb = local[n].BoundingBox()
        assert np.allclose([back.xmin, back.ymin, back.zmin, back.xmax, back.ymax, back.zmax],
                           [lb.xmin, lb.ymin, lb.zmin, lb.xmax, lb.ymax, lb.zmax], atol=1e-3)
    j = info["joint"]
    assert np.allclose(j["axis_point"], kernel.apply_points(m, p.axis_point)[0], atol=1e-3)
    assert np.allclose(j["axis_direction"], kernel.apply_dirs(m, generator.AXIS_DIRECTION)[0], atol=1e-6)
    assert abs(j["axis_direction"][2]) > 1e-3 or p.pose.tilt_deg < 0.1    # not axis-aligned
    po = info["print_orientation"]
    assert np.allclose(po["enclosure"]["build_up"], kernel.apply_dirs(m, (0, 0, 1))[0], atol=1e-6)
    assert np.allclose(po["lid"]["build_up"], kernel.apply_dirs(m, (0, 0, -1))[0], atol=1e-6)
    enc = kernel.to_manifold(shapes["enclosure"])
    for z in info["keep_in"]:        # world zone boxes hold the same material as the local boxes
        local_vol = kernel.box_overlap_volume(kernel.to_manifold(local["enclosure"]), *z["box"])
        world_vol = float((enc ^ kernel.oriented_box(z["world"]["origin"], z["world"]["edges"])).volume())
        assert world_vol == pytest.approx(local_vol, rel=1e-3)
    assert info["pose"]["yaw_deg"] == p.pose.yaw_deg


@pytest.mark.parametrize("seed", SEEDS)
def test_l3_original_jams_on_every_rib_and_nothing_else(seed, written):
    d, info, shapes = written("L3", seed)
    j = info["joint"]
    meshes = {n: kernel.to_manifold(s) for n, s in shapes.items()}
    moving = {n: meshes[n] for n in j["moving"]}
    assert kernel.intersection(meshes["hinge_pin"], meshes["enclosure"])[0] == 0.0
    assert not kernel.overlaps_at(moving, {n: meshes[n] for n in j["fixed"]}, j["axis_point"], j["axis_direction"], 0)
    # while opening every rib overlaps the rear wall, and every overlap piece lies within one lid segment
    m_inv = kernel.invert(np.array(info["pose"]["matrix"]))
    lid_x = [s["x"] for s in info["segments"] if s["part"] == "lid"]
    hit = set()
    enc_local = kernel.transform_mesh(meshes["enclosure"], m_inv)
    for ang in range(2, 111, 2):   # (0 deg = resting on the seal: touching, checked above)
        lid = kernel.rotate(meshes["lid"], j["axis_point"], j["axis_direction"], ang)
        for pc in kernel.intersection_components(kernel.transform_mesh(lid, m_inv), enc_local):
            lo, hi = pc["bbox"][0][0], pc["bbox"][1][0]
            seg = [i for i, (x0, x1) in enumerate(lid_x) if x0 - 0.02 <= lo and hi <= x1 + 0.02]
            assert len(seg) == 1, (ang, lo, hi)
            hit.add(seg[0])
    assert hit == {0, 1, 2}
    for n in ("hinge_pin",):
        for ang in (0, 30, 60, 90, 110):
            r = kernel.rotate(meshes["lid"], j["axis_point"], j["axis_direction"], ang)
            assert kernel.intersection(r, meshes[n])[0] == 0.0
            r = kernel.rotate(meshes["lid_module"], j["axis_point"], j["axis_direction"], ang)
            assert kernel.intersection(r, meshes["enclosure"])[0] == 0.0
