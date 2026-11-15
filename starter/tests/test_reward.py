"""Reward 0.6 (scenario.json spec.reward, levels): generic helpers, the hinge_lid policy and its reference points,
and the scenario's numbers checked against the text in docs/scenario.json."""
import json
import re
from pathlib import Path

import pytest

from cadfix.core.reward import RewardPolicy, linear_score, progress, ratio_score, sweep_progress
from scenarios.hinge_lid import generator

POLICY = generator.REWARD_POLICY
SCENARIO = json.loads((Path(__file__).resolve().parents[1] / "docs" / "scenario.json").read_text())


def test_linear_score():
    assert linear_score(1.0, 1.25, 3.0) == 1.0
    assert linear_score(1.25, 1.25, 3.0) == 1.0
    assert linear_score(2.0, 1.25, 3.0) == pytest.approx(1 / 1.75)
    assert linear_score(3.0, 1.25, 3.0) == 0.0
    assert linear_score(9.0, 1.25, 3.0) == 0.0


def test_progress_clipped():
    assert progress(45, 45, 110) == 0.0
    assert progress(20, 45, 110) == 0.0
    assert progress(77.5, 45, 110) == pytest.approx(0.5)
    assert progress(200, 45, 110) == 1.0


def test_ratio_score_per_level():
    for level, (full, zero) in generator.S3_FACTORS.items():
        assert ratio_score(full * 10.0, 10.0, full, zero) == 1.0
        assert ratio_score(zero * 10.0, 10.0, full, zero) == 0.0
        assert ratio_score(0.5 * (full + zero) * 10.0, 10.0, full, zero) == pytest.approx(0.5)
    assert ratio_score(3.2, 1.0, 1.15, 2.0) == 0.0             # L2/L3: full-edge chamfer ~3.2-5 x V_ref
    assert ratio_score(4.68, 1.0, *generator.S3_FACTORS["L1"]) == 1.0   # L1: same chamfer (<= 4.68x), full points


def test_sweep_progress():
    # 0.5 * angle progress + 0.5 * clearance progress; clearance progress 0 if anything overlaps
    assert sweep_progress(45, 45, 110, 0.0, 0.3, True) == 0.0                    # do nothing
    assert sweep_progress(77.5, 45, 110, 0.15, 0.3, False) == pytest.approx(0.5)
    assert sweep_progress(77.5, 45, 110, 0.15, 0.3, True) == pytest.approx(0.25)
    assert sweep_progress(45, 45, 110, 0.6, 0.3, False) == pytest.approx(0.5)    # clipped at 1
    assert sweep_progress(None, 45, 110, 0.2, 0.3, True) == 0.0                  # fails at the first step
    assert sweep_progress(109, 0, 110, 0.299, 0.3, False) < 1.0


def test_reference_points_from_scenario():
    pts = SCENARIO["spec"]["reward"]["reference_points"]
    full = {"printability": 1.0, "minimal_change": 1.0}
    assert POLICY.reward(True, True, 1.0, full) == pts["reference fix"] == 1.0
    assert POLICY.reward(True, True, 1.0, {"printability": 1.0, "minimal_change": 0.0}) == \
        pts["working but wasteful (S3 = 0)"] == 0.4
    best_broken = POLICY.reward(True, False, sweep_progress(109, 45, 110, 0.299, 0.3, False), full)
    assert best_broken < pts["broken, best case"] == 0.25 == POLICY.reward(True, False, 1.0, full)
    assert POLICY.reward(True, False, sweep_progress(45, 45, 110, 0.0, 0.3, True), full) == pts["do-nothing"] == 0.0
    assert POLICY.reward(False, True, 1.0, full) == SCENARIO["spec"]["reward"]["gate_failed"] == 0.0
    # ordering: broken < working-but-wasteful < working-and-tailored
    assert POLICY.reward(True, False, 1.0, full) < POLICY.reward(True, True, 1.0, {"printability": 0.0,
                                                                                   "minimal_change": 0.0})


def test_policy_matches_scenario_text():
    r = SCENARIO["spec"]["reward"]
    assert re.fullmatch(r"([\d.]+) \* progress.*", r["S1_not_met"]).group(1) == str(POLICY.progress_weight)
    m = re.fullmatch(r"([\d.]+) \+ ([\d.]+) \* printability \+ ([\d.]+) \* minimal_change", r["S1_met"])
    assert tuple(float(x) for x in m.groups()) == (POLICY.met_base, POLICY.weights["printability"],
                                                   POLICY.weights["minimal_change"])
    assert RewardPolicy(0.25, 0.3, {"printability": 0.1, "minimal_change": 0.6}) == POLICY


def test_s3_factors_match_scenario_levels():
    lv = SCENARIO["levels"]

    def factors(text):
        return tuple(float(x) for x in re.findall(r"([\d.]+)x", text))
    assert factors(lv["L1_easy"]["S3"]) == generator.S3_FACTORS["L1"] == (5.0, 10.0)
    assert factors(lv["L2_medium"]["S3"]) == generator.S3_FACTORS["L2"] == (1.15, 2.0)
    assert lv["L3_hard"]["S3"].startswith("strict, as L2") and generator.S3_FACTORS["L3"] == generator.S3_FACTORS["L2"]
