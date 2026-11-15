"""hinge_lid L1, seeds 0..9: the original jams at the rear wall's outer top edge; the full-edge chamfer from the
scan passes S1 in 3D with real B-rep chamfers and is tight; under- and over-sized variants score as the
scenario says. Parts go through STEP like in real use. (Task 2b tests, moved to the 2c tooling: reward 0.6 and
S3 relative to V_ref, see docs/DECISIONS.md D9.)"""
import json

import pytest

from cadfix.core import kernel
from cadfix.core.reward import linear_score
from marks import SLOW, slow_except
from scenarios.hinge_lid import dev_sweep, devgrade, generator

SEEDS = slow_except(range(10), keep={0})
ALL_SEEDS = range(10)


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("hinge_lid")


@pytest.fixture(scope="module")
def rows(out_dir):
    cache = {}

    def get(seed):
        if seed not in cache:
            cache[seed] = dev_sweep.run_seed("L1", seed, out_dir, side_collisions=False,
                                             variants=("original", "full_edge", "side_0.7x", "symmetric"))
        return cache[seed]
    return get


def ratio(info, v):
    return v["changed_mm3"] / info["feasibility"]["V_ref_mm3"]


@pytest.mark.parametrize("seed", SEEDS)
def test_scan_deterministic_and_valid(seed):
    p1, f1, r1 = generator.resolve_seed(seed)
    p2, f2, r2 = generator.resolve_seed(seed)
    assert (p1, f1, r1) == (p2, f2, r2)
    assert f1["feasible"] and not f1["reasons"]
    assert p1.seed == seed + generator.REPLACE_STRIDE * len(r1)
    b = f1["scan"]["best"]
    assert b["seal_margin"] >= generator.SEAL_MARGIN_MIN - 1e-9
    assert b["min_wall"] >= generator.MIN_WALL
    assert b["clearance_2d"] >= generator.CLEARANCE
    assert b["volume_mm3"] == pytest.approx(0.5 * b["d_top"] * b["d_side"] * p1.L)
    # best = smallest volume among all valid chamfers
    vols = [0.5 * float(t) * s * p1.L for t, s in f1["scan"]["side_min_by_top"].items()]
    assert b["volume_mm3"] == pytest.approx(min(vols))


@pytest.mark.parametrize("seed", SEEDS)
def test_parts_valid_spec_written_lid_printable_top_down(seed, rows, out_dir):
    rows(seed)  # writes the STEP files
    d = generator.seed_dir(out_dir, "L1", seed)
    info = json.loads((d / "params.json").read_text())
    p, s3 = info["params"], info["spec"]["S3"]
    shapes = {n: kernel.import_step(d / f"{n}.step") for n in generator.PART_NAMES}
    assert all(s.isValid() for s in shapes.values())
    assert shapes["lid"].BoundingBox().zmax == pytest.approx(p["H"] + p["t_lid"], abs=1e-6)
    assert s3["V_ref_mm3"] == info["feasibility"]["V_ref_mm3"]
    assert (s3["full_factor"], s3["zero_factor"]) == (5.0, 10.0)
    assert s3["full_points_up_to_mm3"] == pytest.approx(5.0 * s3["V_ref_mm3"], abs=1e-3)
    assert info["spec"]["S1"]["clearance_from_deg"] == 10.0 and info["spec"]["S1"]["clearance_mm"] == 0.3


@pytest.mark.parametrize("seed", SEEDS)
def test_original_jams_at_rear_wall_edge(seed, rows):
    r = rows(seed)
    o = r["variants"]["original"]
    assert r["pin_x_enclosure"] == 0.0
    assert o["s1"]["first_overlap_deg"] != 0.0                 # closed position clean
    fc = r["first_contact"]
    assert 40 <= fc["angle"] <= 72
    assert abs(fc["angle"] - r["predicted_deg"]) <= 1.0
    assert r["first_pairs"] == [("lid", "enclosure")]           # never the module, never the pin
    assert r["first_in_zone"]                                   # at the edge, inside one lid segment per piece
    assert not o["s1"]["met"] and o["s1"]["ok_until"] < fc["angle"]
    assert o["reward"] == 0.0                                   # do nothing = 0


@pytest.mark.parametrize("seed", SEEDS)
def test_full_edge_chamfer_works_l1_scores_by_ratio(seed, rows):
    r = rows(seed)
    v = r["variants"]["full_edge"]
    assert v["error"] is None                                   # the real chamfer operation works
    assert v["s1"]["met"] and v["s1"]["min_clearance"] >= 0.3
    assert v["seal_margin"] >= 0.3 - 1e-3 and v["min_wall_ok"]
    assert all(v["gates"].values()) and v["printability"] == 1.0
    k = ratio(r["info"], v)                                     # 3.2-4.7 x V_ref on seeds 0-9
    assert k < 5.0 and v["s3"] == 1.0                           # L1 S3 5x / 10x (scenario.json 0.7, P2)
    assert v["reward"] == 1.0


@pytest.mark.parametrize("seed", SEEDS)
def test_best_chamfer_is_tight_in_3d(seed, rows, out_dir):
    """One grid step less side at the best top fails S1 in 3D too (2D and 3D agree at the boundary)."""
    info, shapes = devgrade.load("L1", seed, out_dir)
    b = info["feasibility"]["scan"]["best"]
    g = devgrade.Grader(info, shapes)
    v = g.grade([devgrade.chamfer_op(info, b["d_top"], round(b["d_side"] - generator.GRID_MM, 3))])
    assert not v["s1"]["met"]
    assert rows(seed)["variants"]["full_edge"]["s1"]["met"]


@pytest.mark.parametrize("seed", SEEDS)
def test_too_small_relief_partial_credit_only(seed, rows):
    v = rows(seed)["variants"]["side_0.7x"]
    assert not v["s1"]["met"]
    assert 0.0 <= v["reward"] < 0.25


@pytest.mark.parametrize("seed", SEEDS)
def test_double_side_over_cut_loses_minimal_change_points(seed, out_dir):
    info, shapes = devgrade.load("L1", seed, out_dir)
    b = info["feasibility"]["scan"]["best"]
    try:
        v = devgrade.Grader(info, shapes).grade([devgrade.chamfer_op(info, b["d_top"], 2 * b["d_side"])])
    except devgrade.OpError as e:      # seeds 0, 2: 2 x side >= the free band, the chamfer tool refuses
        assert "failed in the CAD kernel" in str(e) and 2 * b["d_side"] >= info["params"]["free_band"]
        return
    assert v["s1"]["met"] and v["gates"]["G3_keep_in"]
    k = ratio(info, v)                                          # 6.4-9.4 x V_ref
    assert v["s3"] == pytest.approx(linear_score(k, 5.0, 10.0), abs=1e-6) and v["s3"] < 1.0
    assert v["reward"] == pytest.approx(0.4 + 0.6 * v["s3"], abs=1e-6)


@pytest.mark.parametrize("seed", SEEDS)
def test_symmetric_chamfer_eats_the_seal(seed, rows):
    v = rows(seed)["variants"]["symmetric"]
    assert v["s1"]["met"]                                       # it is the smallest symmetric one passing S1
    assert v["seal_margin"] < generator.SEAL_MARGIN_MIN         # below the margin on every seed


@SLOW
def test_symmetric_chamfer_fails_seal_gate_on_nine_of_ten(rows):
    failed = [s for s in ALL_SEEDS if not rows(s)["variants"]["symmetric"]["gates"]["G5_seal"]]
    assert len(failed) == 9 and set(ALL_SEEDS) - set(failed) == {4}


@pytest.mark.parametrize("seed", SEEDS)
def test_sweeps_are_fast(seed, rows):
    r = rows(seed)
    assert r["first_contact_s"] < 5.0
    assert all(v["s1"]["seconds"] < 5.0 for v in r["variants"].values() if v)
