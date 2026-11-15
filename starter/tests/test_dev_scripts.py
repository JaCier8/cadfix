"""brief.py tells the agent-visible facts only; evaluate.py reproduces the dev_sweep numbers."""
import json
import re

import pytest

from marks import SLOW, slow_except
from scenarios.hinge_lid import brief, dev_sweep, devgrade, evaluate


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("hinge_lid")


FIX_WORDS = ("chamfer", "relief", "notch", "v_ref", "local", "per rib", "fillet", "feasib", "over-cut",
             "smallest valid", "pose", "yaw", "tilt")


def _scan_numbers(info: dict) -> set[str]:
    """Numbers only the feasibility scan knows. Single relief legs are left out: they coincide with public
    geometry by chance (e.g. a 2.2 mm side = the knuckle radius)."""
    f, s3 = info["feasibility"], info["spec"]["S3"]
    out = {f"{f['scan']['best']['volume_mm3']}"}
    for r in f["ribs"]:
        b = r["best"]
        out |= {f"{b['volume_mm3']}", f"{b['volume_mm3']:.2f}", f"{b['d_top']}x{b['d_side']}",
                f"{b['d_top']} x {b['d_side']}"}
    for k in ("V_ref_mm3", "V_full_edge_mm3", "V_identical_mm3"):
        out |= {f"{f[k]}", f"{f[k]:.2f}", f"{f[k]:.3f}"}
    for k in ("full_points_up_to_mm3", "zero_points_at_mm3", "full_points_up_to_pct", "zero_points_at_pct"):
        out.add(f"{s3[k]}")
    # a scan number that equals a public dimension is a coincidence, not a leak (L1 seed 2: 5 x V_ref = 70.5 mm3 and
    # the box is 70.5 mm long)
    p = info["params"]
    public = {f"{p[k]}" for k in ("L", "W", "H", "t", "floor", "t_lid")}
    return out - public


@pytest.mark.parametrize("level,seed", slow_except([(lv, s) for lv in ("L1", "L2", "L3") for s in (0, 1, 2)],
                                                   keep={("L1", 0), ("L2", 0)}))
def test_brief_does_not_leak_the_fix(level, seed, out_dir):
    text = brief.brief(seed, out_dir, level)
    info, _ = devgrade.load(level, seed, out_dir)
    low = text.lower()
    for word in FIX_WORDS:
        assert word not in low, word
    for n in _scan_numbers(info):
        assert not re.search(r"(?<![\d.])" + re.escape(n) + r"(?![\d])", text), n
    if level == "L1" and seed == 0:   # task 2b check, kept
        assert f"{info['feasibility']['scan']['best']['d_side']}" not in text
    full, zero = devgrade.generator.S3_FACTORS[level]
    assert (f"full points if the changed volume is within {full:g}x of the best known fix for this task, "
            f"zero at {zero:g}x") in text
    assert "first contact at" in text and "S1: NOT met" in text and " %" not in text.split("S3_minimal")[1].split("reward")[0]


@SLOW   # L3 generation ~11 s per seed
def test_l3_brief_is_in_world_coordinates(out_dir):
    text = brief.brief(0, out_dir, "L3")
    info, _ = devgrade.load("L3", 0, out_dir)
    assert "x along the hinge" not in text and "rel. to axis" not in text
    ax = info["joint"]["axis_point"]
    assert f"axis through ({ax[0]:g}, {ax[1]:g}, {ax[2]:g})" in text
    assert f"{info['params']['pose']['yaw_deg']}" not in text


def test_evaluate_best_chamfer_scores_one(out_dir):
    info, _ = dev_sweep.load(0, out_dir)
    b = info["feasibility"]["scan"]["best"]
    text = evaluate.report("L1", 0, [devgrade.chamfer_op(info, b["d_top"], b["d_side"])], out_dir)
    assert "S1 opening        PASS" in text and "REWARD            1.000" in text


def test_evaluate_ops_json_cli_and_hide_score(out_dir, capsys):
    info, _ = dev_sweep.load(0, out_dir)
    b = info["feasibility"]["scan"]["best"]
    op = json.dumps([devgrade.chamfer_op(info, b["d_top"], b["d_side"])])
    evaluate.main(["--level", "L1", "--seed", "0", "--ops", op, "--out", str(out_dir)])
    via_ops = capsys.readouterr().out
    evaluate.main(["--level", "L1", "--seed", "0", "--top", str(b["d_top"]), "--side", str(b["d_side"]),
                   "--out", str(out_dir)])
    assert capsys.readouterr().out == via_ops                       # the shortcut is the same chamfer op
    evaluate.main(["--level", "L1", "--seed", "0", "--ops", op, "--out", str(out_dir), "--hide-score"])
    hidden = capsys.readouterr().out
    assert "REWARD" not in hidden and "S1 opening        PASS" in hidden
    s3 = [ln for ln in hidden.splitlines() if ln.startswith("S3")][0]
    assert "->" not in s3 and "full" not in s3 and "% of the enclosure" in s3


def test_evaluate_reports_op_errors(out_dir):
    text = evaluate.report("L1", 0, [{"op": "chamfer", "edge_near": [0, 0, 999], "d1": 1}], out_dir)
    assert "ERROR" in text and "no edge within" in text and "REWARD" not in text
