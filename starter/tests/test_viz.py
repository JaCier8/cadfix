"""3D diff viewer (cadfix.viz) on a real L1 seed 0 task: GLB nodes, red/green diff nodes, reference variant,
self-contained side-by-side viewer.html."""
import json
import re
import shutil

import pytest
import trimesh

from cadfix import viz
from cadfix.core.assembly import Assembly
from scenarios.hinge_lid import task as hl_task


@pytest.fixture(scope="module")
def task(tmp_path_factory):
    return hl_task.write_task("L1", 0, gen_out=tmp_path_factory.mktemp("gen"), root=tmp_path_factory.mktemp("tasks"))


def node_names(glb):
    return set(trimesh.load(glb).geometry.keys())


def is_diff(n):
    return n.endswith("__removed") or n.endswith("__added")


def test_do_nothing(task, tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    out = tmp_path / "viz"
    info = viz.visualize(task / "task", task / "pristine", sub, out)
    asm = Assembly.load(task / "task")
    for v in ("agent", "reference", "original"):
        for q in ("closed", "open"):
            assert (out / f"{v}_{q}.glb").exists()
            names = node_names(out / f"{v}_{q}.glb")
            if v == "reference":
                assert set(asm.parts) < names and any(n.endswith("__removed") for n in names)
            else:
                assert names == set(asm.parts)       # do nothing: no diff nodes; original never has any
    assert (out / "viewer.html").exists() and (out / "viz.json").exists()
    assert all(v.startswith("missing") for v in info["submission"].values())
    assert json.loads((out / "viz.json").read_text())["parts"].keys() == asm.parts.keys()
    assert info["variants"].keys() == {"agent", "reference", "original"}
    assert info["variants"]["agent"]["diff_bbox"] is None and info["variants"]["reference"]["diff_bbox"] is not None


def test_submission_equals_reference(task, tmp_path):
    asm = Assembly.load(task / "task")
    sub = tmp_path / "sub"
    (sub / "parts").mkdir(parents=True)
    ref = task / "pristine" / "reference" / "parts"
    changed = [f.stem for f in ref.glob("*.step")]
    assert changed and set(changed) <= set(asm.editable)
    for n in changed:
        shutil.copy(ref / f"{n}.step", sub / "parts" / f"{n}.step")
    out = tmp_path / "viz"
    info = viz.visualize(task / "task", task / "pristine", sub, out, report={"reward": 0.5, "level": "L1", "seed": 0})
    assert info["reward"] == 0.5
    rem = {n: info["variants"]["reference"]["parts"][n]["removed"] for n in changed}
    assert max(rem.values()) > 0
    for n in changed:
        assert info["submission"][n] == "submitted"
        assert (f"{n}__removed" in node_names(out / "agent_open.glb")) == (rem[n] > 0)
        assert info["variants"]["agent"]["parts"][n]["removed"] == pytest.approx(rem[n], rel=1e-3)
        assert info["variants"]["agent"]["parts"][n]["added"] == pytest.approx(
            info["variants"]["reference"]["parts"][n]["added"], abs=1e-3)
    assert not any(is_diff(n) for n in node_names(out / "original_closed.glb"))
    html = (out / "viewer.html").read_text()
    assert all(re.search(rf'"{v}": \{{"closed": "[A-Za-z0-9+/=]{{1000,}}"', html) for v in ("agent", "reference", "original"))
    urls = set(re.findall(r"https?://[^\s\"')]+", html))
    assert urls and all(u.startswith("https://cdn.jsdelivr.net/npm/three@0.160.0") for u in urls)


def test_no_reference(task, tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    pri = tmp_path / "pri"
    shutil.copytree(task / "pristine", pri)
    shutil.rmtree(pri / "reference")
    info = viz.visualize(task / "task", pri, sub, tmp_path / "viz")
    assert info["variants"].keys() == {"agent", "original"}


def test_diff_meshes_no_slivers(task):
    from cadfix.core import kernel
    asm = Assembly.load(task / "task")
    ref = viz._reference_assembly(asm, task / "pristine" / "reference")
    n = next(n for n in asm.editable if kernel.changed_volume(asm.parts[n].mesh, ref.parts[n].mesh)[0] > 1)
    removed, added = viz.diff_meshes(asm.parts[n].shape, ref.parts[n].shape)
    assert added is None
    comps = removed.decompose()
    assert comps and all(c.volume() >= viz.MIN_DIFF_MM3 for c in comps)
    assert removed.volume() == pytest.approx(kernel.changed_volume(asm.parts[n].mesh, ref.parts[n].mesh)[0], rel=0.01)
    assert viz.diff_meshes(asm.parts[n].shape, asm.parts[n].shape) == (None, None)
