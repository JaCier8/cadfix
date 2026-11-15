"""Public task dir (what goes into the agent's container) vs private grader data."""
import json

import pytest

from marks import SLOW
from scenarios.hinge_lid import generator
from scenarios.hinge_lid import task as hl_task

LEAK_KEYS = ("feasibility", "reference_ops", "pose", "V_ref", "source_seed", "rejected", "lug_q0", "lug_p", "free_band",
             "attempt", "relief", "identical")


def _check(level, seed, tmp_path_factory):
    gen = tmp_path_factory.mktemp("gen")
    d = hl_task.write_task(level, seed, gen_out=gen, root=tmp_path_factory.mktemp("tasks"))
    info = json.loads((generator.seed_dir(gen, level, seed) / "params.json").read_text())
    pub = {f.name: f.read_text() for f in (d / "task").iterdir() if f.is_file()}
    assert set(pub) == {"task.json", "spec.json"}
    assert sorted(p.name for p in (d / "task" / "parts").iterdir()) == sorted(f"{n}.step" for n in generator.PART_NAMES)
    v_ref = info["feasibility"]["V_ref_mm3"]
    for name, text in pub.items():
        for k in LEAK_KEYS:
            assert f'"{k}' not in text, (name, k)
        for v in {f"{v_ref}", f"{v_ref:.2f}", f"{v_ref:.3f}"}:
            assert v not in text, (name, v)
        for r in info["feasibility"]["ribs"]:
            assert f"{r['best']['volume_mm3']}" not in text
    grader = json.loads((d / "pristine" / "grader.json").read_text())
    assert grader["private"]["S3_minimal_change"]["reference_mm3"] == v_ref
    task = json.loads(pub["task.json"])
    assert {z["kind"] for z in task["zones"]} == {"keep_in", "keep_out"}
    assert {z["name"].split("_")[0] for z in task["zones"]} >= {"bracket", "lid", "seal"}
    return task, json.loads(pub["spec.json"])


def test_l2_task_is_public_only(tmp_path_factory):
    task, spec = _check("L2", 0, tmp_path_factory)
    assert [c["id"] for c in spec["checks"] if c["role"] == "gate"] == [
        "G1_valid_solids", "G2_hinge_interface", "G3_keep_in", "G3_keep_out", "G4_closed_position", "G5_seal",
        "G6_not_rebuilt"]
    assert spec["rules"]["S3"].startswith("full points if the changed volume is within 1.15x")
    assert "reference_mm3" not in json.dumps(spec)


@SLOW
def test_l3_task_is_public_only(tmp_path_factory):
    task, spec = _check("L3", 0, tmp_path_factory)
    assert max(abs(c) for c in task["joint"]["axis_direction"]) < 0.999      # world frame: not axis-aligned
