"""Per-rib feasibility and reference volumes (M3), all levels, seeds 0..9.

The 2D scan gives each rib's smallest valid relief; V_ref is their sum. The reference fix is stored as ops in the
evaluate JSON format (world frame) and, applied as real B-rep cuts to the STEP parts, passes S1 in 3D."""
import pytest

from marks import slow_except
from scenarios.hinge_lid import devgrade, generator

CASES = slow_except([(lv, s) for lv in generator.LEVELS for s in range(10)],
                    keep={("L1", 0), ("L2", 0)})   # L3 seed 0: quick run covers it in test_levels


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("reference")


@pytest.mark.parametrize("level,seed", CASES)
def test_reference_volumes(level, seed):
    p, f, rejected = generator.resolve_seed(seed, level)
    ribs = f["ribs"]
    assert len(ribs) == len(p.lid_segments())
    for r, (xs, xe) in zip(ribs, p.lid_segments()):
        b = r["best"]
        assert b["seal_margin"] >= generator.SEAL_MARGIN_MIN - 1e-9 and b["min_wall"] >= generator.MIN_WALL
        assert b["clearance_2d"] >= generator.CLEARANCE
        assert b["x"] == [pytest.approx(xs - 0.35), pytest.approx(xe + 0.35)]
        assert b["volume_mm3"] == pytest.approx(0.5 * b["d_top"] * b["d_side"] * (xe - xs + 0.7), abs=1e-3)
        smallest = min(float(t) * sd for t, sd in r["side_min_by_top"].items())   # smallest valid per rib
        assert b["d_top"] * b["d_side"] == pytest.approx(smallest)
    assert f["V_ref_mm3"] == pytest.approx(sum(r["best"]["volume_mm3"] for r in ribs), abs=1e-3)
    assert f["V_ref_mm3"] <= f["V_identical_mm3"] + 1e-3 < f["V_full_edge_mm3"]
    if level != "L3":
        assert f["V_identical_mm3"] == pytest.approx(f["V_ref_mm3"], abs=1e-3)
    else:
        assert f["V_identical_mm3"] > f["V_ref_mm3"]
    ref = f["reference"]                             # 3D check of the local reliefs (end clearance along x)
    assert ref["met"] and ref["min_clearance"] >= generator.CLEARANCE
    assert ref["removed_mm3"] == pytest.approx(f["V_ref_mm3"], abs=2e-3)


@pytest.mark.parametrize("level,seed", CASES)
def test_world_reference_ops_pass_s1_in_3d(level, seed, out_dir):
    info, shapes = devgrade.load(level, seed, out_dir)
    ops = info["reference_ops"]
    assert [o["op"] for o in ops] == ["extrude_cut"] * len(info["feasibility"]["ribs"])
    v = devgrade.Grader(info, shapes).grade(ops)
    assert v["s1"]["met"] and v["s1"]["min_clearance"] >= 0.3
    assert all(v["gates"].values()) and v["printability"] == 1.0
    assert v["seal_margin"] >= 0.3 - 1e-3 and v["min_wall"] >= 1.2
    assert v["changed_mm3"] == pytest.approx(info["feasibility"]["V_ref_mm3"], rel=2e-3)
