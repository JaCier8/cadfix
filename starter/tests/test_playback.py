"""cadfix.playback on a real L2 seed 0 episode produced by the reference solver."""
import json
import shutil

import pytest

from cadfix import grade, playback
from cadfix.core import kernel
from cadfix.core.assembly import Assembly
from cadfix.env.env import EDIT_TOOLS, Env
from scenarios.hinge_lid import reference
from scenarios.hinge_lid import task as hl_task


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    d = hl_task.write_task("L2", 0, gen_out=tmp_path_factory.mktemp("gen"), root=tmp_path_factory.mktemp("tasks"))
    out = tmp_path_factory.mktemp("episode")
    client = reference.InProcessClient(Env(d / "task", out))
    reference.solve(client)
    client.close()
    return d, out


def run(case, sub, tmp_path):
    d, _ = case
    return playback.build_playback(d / "task", d / "pristine", sub, tmp_path / "pb")


def ok_edits(out):
    n = 0
    for line in (out / "actions.jsonl").read_text().splitlines():
        r = json.loads(line)
        n += r["tool"] in EDIT_TOOLS and r["result"].get("ok") is True
    return n


def test_reproduced(case, tmp_path):
    d, out = case
    pb = run(case, out, tmp_path)
    assert pb["status"] == "reproduced", pb["message"]
    assert len(pb["frames"]) == 1 + ok_edits(out)
    assert all(0 <= s["frame"] < len(pb["frames"]) for s in pb["steps"])
    assert len(pb["steps"]) == len((out / "actions.jsonl").read_text().splitlines())
    assert all((tmp_path / "pb" / f["file"]).exists() for f in pb["frames"])
    original = Assembly.load(d / "task", d / "pristine" / "parts")
    graded, _ = grade.load_submission(original, out)
    last = pb["frames"][-1]["parts"]
    for n in original.editable:
        rem, add = kernel.changed_volume(original.parts[n].mesh, graded.parts[n].mesh)
        assert last[n]["removed"] == pytest.approx(rem, abs=1e-2)
        assert last[n]["added"] == pytest.approx(add, abs=1e-2)
    assert any(s["last_check"] for s in pb["steps"])


def test_tamper_drops_edit(case, tmp_path):
    d, out = case
    sub = tmp_path / "sub"
    shutil.copytree(out, sub, ignore=shutil.ignore_patterns("snapshots"))
    lines = (out / "actions.jsonl").read_text().splitlines()
    i = next(i for i, l in enumerate(lines) if json.loads(l)["tool"] in EDIT_TOOLS)
    (sub / "actions.jsonl").write_text("\n".join(lines[:i] + lines[i + 1:]) + "\n")
    pb = run(case, sub, tmp_path)
    assert pb["status"] == "mismatch"
    assert pb["frames"][-1]["label"] == "graded submission"


def test_garbage_lines(case, tmp_path):
    d, out = case
    sub = tmp_path / "sub"
    shutil.copytree(out, sub, ignore=shutil.ignore_patterns("snapshots"))
    with (sub / "actions.jsonl").open("a") as f:
        f.write("{not json\n" + json.dumps({"tool": "rm_rf", "args": {"x": 1}, "result": None}) + "\n"
                + json.dumps({"tool": "chamfer", "args": [1, 2], "result": {"error": 5}}) + "\n"
                + json.dumps({"tool": "chamfer", "args": {"tool": 1}, "result": {}}) + "\n" + "[1]\n")
    pb = run(case, sub, tmp_path)
    assert pb["status"] == "reproduced"
    assert pb["steps"][-1]["edit_ok"] is False


def test_no_log(case, tmp_path):
    sub = tmp_path / "empty"
    sub.mkdir()
    pb = run(case, sub, tmp_path)
    assert pb["status"] == "no_log" and len(pb["frames"]) == 1 and pb["steps"] == []
