"""Grader CLI (cadfix.grade) on a real task (L2 seed 0): reward.txt is always written, empty / garbage / missing
submissions score like doing nothing, the reference fix scores 1.0, the test_fit cost is applied."""
import json

import pytest

from cadfix import grade
from cadfix.core import kernel
from cadfix.core.assembly import Assembly
from cadfix.ops.edit import apply_ops
from scenarios.hinge_lid import generator
from scenarios.hinge_lid import task as hl_task


@pytest.fixture(scope="module")
def task(tmp_path_factory):
    root = tmp_path_factory.mktemp("tasks")
    gen = tmp_path_factory.mktemp("gen")
    d = hl_task.write_task("L2", 0, gen_out=gen, root=root)
    info = json.loads((generator.seed_dir(gen, "L2", 0) / "params.json").read_text())
    asm = Assembly.load(d / "task")
    new, _ = apply_ops({n: p.shape for n, p in asm.parts.items()}, info["reference_ops"], ["enclosure", "lid"])
    return d, new


def submit(tmp_path, shapes: dict, test_fit_calls=None):
    (tmp_path / "parts").mkdir(parents=True, exist_ok=True)
    for n, s in shapes.items():
        kernel.export_step(s, tmp_path / "parts" / f"{n}.step")
    if test_fit_calls is not None:
        (tmp_path / "episode.json").write_text(json.dumps({"test_fit_calls": test_fit_calls}))
    return tmp_path


def cli(d, sub, tmp_path):
    rf = tmp_path / "logs" / "reward.txt"
    grade.main(["--task-dir", str(d / "task"), "--pristine", str(d / "pristine"), "--submitted", str(sub),
                "--level", "L2", "--out", str(tmp_path / "logs" / "report.json"), "--reward-file", str(rf)])
    return float(rf.read_text()), json.loads((tmp_path / "logs" / "report.json").read_text())


def test_empty_submission_scores_zero_and_writes_reward(task, tmp_path):
    d, _ = task
    (tmp_path / "out").mkdir()
    reward, rep = cli(d, tmp_path / "out", tmp_path)
    assert reward == 0.0 and rep["submission"] == {"enclosure": "missing -> original", "lid": "missing -> original"}
    assert not rep["objective_met"] and rep["test_fit_cost"] == 0.0


def test_missing_submitted_dir_scores_zero(task, tmp_path):
    d, _ = task
    reward, rep = cli(d, tmp_path / "does_not_exist", tmp_path)
    assert reward == 0.0


def test_garbage_file_scores_zero(task, tmp_path):
    d, _ = task
    (tmp_path / "out" / "parts").mkdir(parents=True)
    (tmp_path / "out" / "parts" / "enclosure.step").write_text("ISO-10303-21; garbage")
    reward, rep = cli(d, tmp_path / "out", tmp_path)
    assert reward == 0.0 and rep["submission"]["enclosure"].startswith("unreadable")


def test_reference_fix_scores_one_and_test_fit_cost(task, tmp_path):
    d, new = task
    sub = submit(tmp_path / "a", {"enclosure": new["enclosure"]}, test_fit_calls=2)
    reward, rep = cli(d, sub, tmp_path / "a")
    assert reward == 1.0 and rep["gates_ok"] and rep["objective_met"] and rep["test_fit_cost"] == 0.0
    sub = submit(tmp_path / "b", {"enclosure": new["enclosure"]}, test_fit_calls=5)
    assert cli(d, sub, tmp_path / "b")[0] == pytest.approx(0.94)              # 3 paid calls x 0.02
    sub = submit(tmp_path / "c", {"enclosure": new["enclosure"]}, test_fit_calls=40)
    assert cli(d, sub, tmp_path / "c")[0] == pytest.approx(0.9)               # capped at 0.1
    sub = submit(tmp_path / "d", {"enclosure": new["enclosure"]})             # no episode record
    reward, rep = cli(d, sub, tmp_path / "d")
    assert reward == pytest.approx(0.9) and rep["test_fit_calls"] is None
    # the log counts too: a lowered counter does not hide test_fit calls in actions.jsonl
    sub = submit(tmp_path / "e", {"enclosure": new["enclosure"]}, test_fit_calls=0)
    (sub / "actions.jsonl").write_text("\n".join(json.dumps({"tool": "test_fit"}) for _ in range(4)) + "\n")
    assert cli(d, sub, tmp_path / "e")[0] == pytest.approx(0.96)


def test_internal_error_still_writes_zero(task, tmp_path):
    (tmp_path / "out").mkdir()
    rf = tmp_path / "reward.txt"
    grade.main(["--task-dir", str(tmp_path / "nothing"), "--pristine", str(tmp_path / "nothing"),
                "--submitted", str(tmp_path / "out"), "--reward-file", str(rf), "--out", str(tmp_path / "r.json")])
    assert rf.read_text().strip() == "0.0" and "error" in json.loads((tmp_path / "r.json").read_text())
