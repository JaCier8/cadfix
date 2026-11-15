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


def _data(idx):
    """The JSON embedded in an index.html."""
    t = Path(idx).read_text()
    i = t.index('<script id="data" type="application/json">') + len('<script id="data" type="application/json">')
    return json.loads(t[i:t.index("</script>", i)])


def _index(root, rel, **kw):
    """Force the index even for a dir holding a single run."""
    base = root / rel
    return show.write_index(base, show.find_runs(base), **kw)


def test_job_dir_index(root):
    _trial(root, name="a", reward=1.0)
    _trial(root, name="b", reward=0.0, task=False)
    idx = show.resolve("jobs/job")
    assert idx == root / "jobs/job/index.html"
    runs = {r["id"]: r for r in _data(idx)["runs"]}
    assert runs["a"]["href"] == "a/verifier/viz/viewer.html" and runs["b"]["href"] == "b/verifier/viz/viewer.html"
    assert runs["a"]["reward"] == 1.0 and runs["b"]["reward"] == 0.0 and runs["a"]["level"] == "L1"
    assert runs["a"]["grade_href"] == "a/verifier/grade.json"
    assert runs["a"]["group"] == "job" and runs["a"]["task"] == "x"
    t = idx.read_text()
    assert 'href="a/verifier/viz/viewer.html"' in t  # noscript fallback
    assert "http://" not in t.split("<script id=")[0].replace("http://www.w3.org", "")  # self-contained, no CDN


def test_results_agent_index_with_playback(root):
    _result(root, seed=0)
    _result(root, seed=1, reward=0.2)
    d = _data(show.resolve("results/ref"))
    runs = {r["id"]: r for r in d["runs"]}
    assert runs["L1/seed_0001"]["href"] == "L1/seed_0001/viz/viewer.html" and runs["L1/seed_0001"]["reward"] == 0.2
    assert runs["L1/seed_0000"]["playback"] == "ok" and runs["L1/seed_0000"]["agent"] == "ref"
    assert {r["group"] for r in d["runs"]} == {"ref"}


def test_index_fields_from_viz_playback_grade(root):
    d = _result(root)
    g = json.loads((d / "grade.json").read_text())
    g.update(gates_ok=False, failed_gates=["G3_keep_in"], checks={"S1_opening": {"passed": False, "metrics": {"ok_until": 45.0}}})
    (d / "grade.json").write_text(json.dumps(g))
    _viz(d / "viz", level="L1", seed=0, playback={"status": "mismatch", "steps": 3, "dir": "playback"},
         parts={"lid": {"editable": True, "removed": 2.5, "added": 0.0}, "pin": {"editable": False, "removed": 9, "added": 9}})
    (d / "viz" / "playback").mkdir()
    steps = [{"tool": "get_task", "is_edit": False}, {"tool": "extrude_cut", "is_edit": True, "edit_ok": False},
             {"tool": "extrude_cut", "is_edit": True, "edit_ok": True}, {"tool": "run_check", "is_edit": False}]
    (d / "viz" / "playback" / "playback.json").write_text(json.dumps({"steps": steps}))
    r = _data(show.resolve("results/ref/L1/seed_0000/..").parent / "index.html")["runs"][0] if False else \
        _data(_index(root, "results/ref"))["runs"][0]
    assert (r["gates_ok"], r["failed_gates"], r["s1"], r["s1_deg"]) == (False, ["G3_keep_in"], False, 45.0)
    assert r["playback"] == "mismatch" and (r["steps"], r["edits"], r["edit_fail"]) == (4, 2, 1)
    assert r["strip"] == "ofec"
    assert r["parts"] == [{"name": "lid", "removed": 2.5, "added": 0.0}]


def test_multi_job_and_multi_agent_grouping(root):
    _trial(root, job="j1", name="a")
    _trial(root, job="j2", name="a", task=False)
    runs = _data(show.resolve("jobs"))["runs"]
    assert {r["group"] for r in runs} == {"j1", "j2"}
    assert {r["href"] for r in runs} == {"j1/a/verifier/viz/viewer.html", "j2/a/verifier/viz/viewer.html"}
    _result(root, agent="A", seed=0)
    _result(root, agent="B", L="L2", seed=1)
    runs = _data(show.resolve("results"))["runs"]
    assert {(r["group"], r["level"]) for r in runs} == {("A", "L1"), ("B", "L2")}
    assert {r["href"] for r in runs} == {"A/L1/seed_0000/viz/viewer.html", "B/L2/seed_0001/viz/viewer.html"}


def test_index_survives_broken_run(root):
    _trial(root, name="a")
    _trial(root, name="b", viz=False, task=False)
    runs = {r["id"]: r for r in _data(show.resolve("jobs/job"))["runs"]}
    assert runs["a"]["href"] and "error" not in runs["a"]
    assert runs["b"]["href"] is None and runs["b"]["error"]
    assert runs["b"]["reward"] == 0.5  # still a card with its grade


def test_index_no_build_marks_missing_viewer(root, fake_viz):
    _trial(root, name="a", viz=False)
    _trial(root, name="b", task=False)
    runs = {r["id"]: r for r in _data(show.resolve("jobs/job", build_missing=False))["runs"]}
    assert fake_viz == [] and runs["a"]["href"] is None and "scripts/view.sh" in runs["a"]["missing"]
    assert runs["b"]["href"] == "b/verifier/viz/viewer.html"
    assert show.main(["jobs/job", "--no-build", "--print"]) == 0 and fake_viz == []


def test_index_old_run_without_playback_or_config(root):
    d = _result(root, viz=False)
    _viz(d / "viz", level="L1", seed=0)  # old viz.json: no playback, no parts
    r = _data(_index(root, "results/ref"))["runs"][0]
    assert r["playback"] == "" and r["steps"] is None and r["strip"] == "" and r["parts"] == []


def test_index_json_is_script_safe(root):
    d = _result(root)
    (d / "grade.json").write_text(json.dumps({"reward": 1.0, "level": "</script><b>", "seed": 0}))
    (d / "viz" / "viz.json").write_text("{}")
    t = _index(root, "results/ref").read_text()
    assert t.count("</script>") == 2  # data + code, never closed early by run data
    assert _data(root / "results/ref/index.html")["runs"][0]["level"] == "</script><b>"


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
