"""cadfix.show: path resolution, index, --print (no geometry; viz/grade mocked)."""
import json
import os
from pathlib import Path

import pytest

from cadfix import show


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(show, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _viz(out, **kw):
    out.mkdir(parents=True, exist_ok=True)
    (out / "viewer.html").write_text("<html>")
    (out / "viz.json").write_text(json.dumps(kw))


def _result(root, agent="ref", L="L1", seed=0, viz=True, reward=1.0):
    d = root / "results" / agent / L / f"seed_{seed:04d}"
    (d / "parts").mkdir(parents=True)
    (d / "grade.json").write_text(json.dumps({"reward": reward, "level": L, "seed": seed}))
    if viz:
        _viz(d / "viz", level=L, seed=seed, playback={"status": "ok"})
    return d


def _trial(root, job="job", name="t1", viz=True, reward=0.5, task=True):
    d = root / "jobs" / job / name
    v = d / "verifier"
    (v / "submitted" / "parts").mkdir(parents=True)
    (v / "grade.json").write_text(json.dumps({"reward": reward}))
    (v / "actions.jsonl").write_text("{}\n")
    (d / "config.json").write_text(json.dumps({"task": {"path": "harbor_tasks/judge/x"}}))
    if task:
        (root / "harbor_tasks/judge/x/tests/task").mkdir(parents=True)
        (root / "harbor_tasks/judge/x/tests/pristine").mkdir(parents=True)
    if viz:
        _viz(v / "viz", level="L1", seed=0)
    return d


@pytest.fixture
def fake_viz(monkeypatch):
    calls = []

    def fake(task, pristine, sub, out, report=None, reference_dir=None):
        calls.append({"task": Path(task), "pristine": Path(pristine), "files": sorted(p.name for p in Path(sub).iterdir()),
                      "report": report})
        _viz(Path(out), level="L1", seed=0)
        return {}
    from cadfix import viz
    monkeypatch.setattr(viz, "visualize", fake)
    return calls


def test_result_dir_existing_viewer(root):
    d = _result(root)
    assert show.resolve(str(d)) == d / "viz" / "viewer.html"


def test_trial_and_verifier_subdir(root):
    d = _trial(root)
    assert show.resolve(str(d)) == d / "verifier" / "viz" / "viewer.html"
    assert show.resolve(str(d / "verifier")) == d / "verifier" / "viz" / "viewer.html"


def test_viz_dir_and_html_direct(root):
    d = _result(root)
    assert show.resolve(str(d / "viz")) == d / "viz" / "viewer.html"
    assert show.resolve(str(d / "viz" / "viewer.html")) == d / "viz" / "viewer.html"


def test_trial_rebuild_when_missing(root, fake_viz):
    d = _trial(root, viz=False)
    assert show.resolve(str(d)) == d / "verifier" / "viz" / "viewer.html"
    c = fake_viz[0]
    assert c["task"] == root / "harbor_tasks/judge/x/tests/task"
    assert c["pristine"] == root / "harbor_tasks/judge/x/tests/pristine"
    assert {"parts", "actions.jsonl"} <= set(c["files"])
    assert c["report"] == {"reward": 0.5}


def test_rebuild_flag(root, fake_viz):
    d = _trial(root)
    show.resolve(str(d), rebuild=True)
    assert len(fake_viz) == 1


def test_result_rebuild_uses_output_tasks(root, fake_viz):
    d = _result(root, L="L2", seed=3, viz=False)
    with pytest.raises(show.ShowError, match="scenarios.hinge_lid.task --level L2 --seeds 3"):
        show.resolve(str(d))
    (root / "output/tasks/L2/seed_0003/task").mkdir(parents=True)
    show.resolve(str(d))
    assert fake_viz[0]["task"] == root / "output/tasks/L2/seed_0003/task"
    assert fake_viz[0]["files"] == ["grade.json", "parts"]


def test_job_dir_index(root):
    _trial(root, name="a", reward=1.0)
    _trial(root, name="b", reward=0.0, task=False)
    idx = show.resolve("jobs/job")
    assert idx == root / "jobs/job/index.html"
    t = idx.read_text()
    assert 'href="a/verifier/viz/viewer.html"' in t and 'href="b/verifier/viz/viewer.html"' in t
    assert "1.000" in t and "0.000" in t and "L1" in t


def test_results_agent_index_with_playback(root):
    _result(root, seed=0)
    _result(root, seed=1, reward=0.2)
    t = show.resolve("results/ref").read_text()
    assert "L1/seed_0000/viz/viewer.html" in t and "ok" in t and "0.200" in t


def test_index_survives_broken_run(root):
    _trial(root, name="a")
    _trial(root, name="b", viz=False, task=False)
    t = show.resolve("jobs/job").read_text()
    assert "class=err" in t and 'href="a/' in t


def test_latest(root):
    a = _result(root, seed=0)
    b = _trial(root)
    os.utime(a / "grade.json", (1, 1))
    assert show.resolve(None) == b / "verifier" / "viz" / "viewer.html"
    os.utime(b / "verifier" / "grade.json", (0, 0))
    assert show.resolve("latest") == a / "viz" / "viewer.html"


def test_errors(root):
    with pytest.raises(show.ShowError):
        show.resolve("nope")
    with pytest.raises(show.ShowError, match="no runs"):
        show.resolve(str(root))
    assert show.main(["nope"]) == 2


def test_print_and_no_open(root, capsys, monkeypatch):
    d = _result(root)
    opened = []
    monkeypatch.setattr(show.webbrowser, "open", opened.append)
    monkeypatch.setattr(show, "in_docker", lambda: False)
    assert show.main([str(d), "--print"]) == 0
    assert capsys.readouterr().out.strip() == str(d / "viz" / "viewer.html")
    assert show.main([str(d)]) == 0
    assert opened == [(d / "viz" / "viewer.html").as_uri()]
    monkeypatch.setattr(show, "in_docker", lambda: True)
    show.main([str(d)])
    assert capsys.readouterr().out.strip() == "results/ref/L1/seed_0000/viz/viewer.html"
    assert len(opened) == 1
