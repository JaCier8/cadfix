"""Episode environment (in-process, the same Env the MCP server wraps): edits, undo, errors, cap, resume, queries."""
import json

import pytest

from cadfix import grade
from cadfix.env.env import Env
from scenarios.hinge_lid import generator
from scenarios.hinge_lid import task as hl_task


@pytest.fixture(scope="module")
def task(tmp_path_factory):
    gen = tmp_path_factory.mktemp("gen")
    d = hl_task.write_task("L2", 0, gen_out=gen, root=tmp_path_factory.mktemp("tasks"))
    info = json.loads((generator.seed_dir(gen, "L2", 0) / "params.json").read_text())
    return d, info


def test_edit_undo_errors_and_log(task, tmp_path):
    d, info = task
    env = Env(d / "task", tmp_path / "out")
    a, b = info["rear_outer_top_edge"]["world"]
    mid = [(x + y) / 2 for x, y in zip(a, b)]
    r = env.call("chamfer", part="enclosure", edge_near=mid, d1=0.9, d2=2.15)
    assert r["ok"] and r["removed_mm3"] > 50 and len(r["edges"]) > 100 and r["faces"]
    assert "error" in env.call("chamfer", part="hinge_pin", edge_near=mid, d1=1)       # fixed part
    assert "error" in env.call("chamfer", part="enclosure", edge_near=[0, 0, 999], d1=1)
    assert "error" in env.call("chamfer", part="enclosure", edge=10 ** 6, d1=1)
    assert "error" in env.call("no_such_tool")
    s1 = env.call("run_check", check_id="S1_opening")
    assert s1["passed"] and s1["score"] == 1.0
    s3 = env.call("run_check", check_id="S3_minimal_change")
    assert s3["score"] is None and s3["metrics"]["changed_mm3"] > 50                  # no V_ref in the tools
    u = env.call("undo")
    assert u["ok"] and "error" in env.call("undo")
    assert not env.call("run_check", check_id="S1_opening")["passed"]
    log = [json.loads(x) for x in (tmp_path / "out" / "actions.jsonl").read_text().splitlines()]
    assert [e["tool"] for e in log] == ["chamfer", "chamfer", "chamfer", "chamfer", "no_such_tool", "run_check",
                                        "run_check", "undo", "undo", "run_check"]
    assert grade.grade(d / "task", d / "pristine", tmp_path / "out")["reward"] == 0.0  # undone: original again


def test_call_cap_and_submit(task, tmp_path):
    d, _ = task
    env = Env(d / "task", tmp_path / "out", max_calls=3, snapshots=False)
    for _ in range(3):
        assert "error" not in env.call("list_parts")
    assert "limit" in env.call("list_parts")["error"]
    assert env.call("submit")["ok"]
    assert "submitted" in env.call("list_parts")["error"]


def test_resume_after_server_restart(task, tmp_path):
    d, info = task
    env = Env(d / "task", tmp_path / "out", snapshots=False)
    for op in info["reference_ops"]:
        assert env.call(**{"tool": op["op"]}, **{k: v for k, v in op.items() if k != "op"})["ok"]
    env.call("test_fit")
    env2 = Env(d / "task", tmp_path / "out", snapshots=False)                       # new process, same output dir
    assert env2.episode["test_fit_calls"] == 1 and env2.episode["resumed"] == 1
    assert env2.call("run_check", check_id="S1_opening")["passed"]


def test_measure_and_section(task, tmp_path):
    d, info = task
    env = Env(d / "task", tmp_path / "out", snapshots=False)
    m = env.call("measure", part_a="lid", part_b="enclosure", joint_angle_deg=70)
    lid_x = [s["x"] for s in info["segments"] if s["part"] == "lid"]
    assert m["overlap_mm3"] > 0 and len(m["pieces"]) == len(lid_x)                   # one piece per rib
    for pc in m["pieces"]:
        assert any(x0 - 0.01 <= pc["bbox_min"][0] and pc["bbox_max"][0] <= x1 + 0.01 for x0, x1 in lid_x)
    assert env.call("measure", part_a="lid", part_b="enclosure")["overlap_mm3"] == 0.0
    j = info["joint"]
    s = env.call("section", part="lid", point=[sum(lid_x[0]) / 2, *j["axis_point"][1:]], normal=[1, 0, 0],
                 x_dir=[0, 1, 0], window_mm=6)
    assert s["u_dir"] == [0.0, 1.0, 0.0] and s["v_dir"] == [0.0, 0.0, 1.0] and s["regions"]
    vs = [v for reg in s["regions"] for _, v in reg["outer"]]
    assert min(vs) == pytest.approx(-info["params"]["lug_p"], abs=1e-3)              # rib bottom below the axis
