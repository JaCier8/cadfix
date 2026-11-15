"""Harbor task folders (cadfix/harbor/build.py): layout, public / private split, verifier and solution scripts."""
import json
import tomllib

from cadfix.harbor import build
from scenarios.hinge_lid import task as hl_task


def test_build_layout_and_split(tmp_path):
    root = hl_task.write_task("L2", 0, gen_out=tmp_path / "gen", root=tmp_path / "tasks")
    out = build.build_task(root, tmp_path / "harbor" / "t")
    cfg = tomllib.loads((out / "task.toml").read_text())
    assert cfg["verifier"]["environment_mode"] == "separate" and cfg["artifacts"] == ["/output"]
    mcp = cfg["environment"]["mcp_servers"][0]
    assert mcp["name"] == "cadfix" and mcp["transport"] == "stdio" and mcp["args"] == ["-m", "cadfix.env.server"]
    env = out / "environment"
    assert (env / "Dockerfile").read_text().rstrip().endswith("COPY task /task")      # task files in the last layer
    public = {p.relative_to(env / "task").as_posix() for p in (env / "task").rglob("*") if p.is_file()}
    assert public == {"task.json", "spec.json", "parts/enclosure.step", "parts/lid.step", "parts/hinge_pin.step",
                      "parts/lid_module.step"}
    assert not list(env.rglob("grader.json")) and not (env / "scenarios").exists()     # no private data, no generator
    assert not [p for p in env.rglob("*") if "reference" in p.name.lower() and p.name != "reference.py"]   # no reference fix
    assert (out / "tests" / "pristine" / "reference" / "parts" / "enclosure.step").exists()
    assert "reference_mm3" not in (env / "task" / "spec.json").read_text()
    pri = json.loads((out / "tests" / "pristine" / "grader.json").read_text())
    assert pri["private"]["S3_minimal_change"]["reference_mm3"] > 0
    assert (out / "tests" / "cadfix" / "grade.py").exists() and (out / "tests" / "task" / "spec.json").exists()
    t = (out / "tests" / "test.sh").read_text()
    assert "PYTHONPATH=/tests" in t and "--pristine /tests/pristine" in t and "reward.txt" in t
    assert not (env / "cadfix" / "viz.py").exists() and (out / "tests" / "cadfix" / "viz.py").exists()  # viewer: humans only
    assert not (env / "cadfix" / "show.py").exists()                                   # viewer launcher: humans only
    assert not (env / "cadfix" / "playback.py").exists() and (out / "tests" / "cadfix" / "playback.py").exists()
    assert t.index("reward.txt") < t.index("cadfix.viz") and "cadfix.viz" in t and t.rstrip().endswith("exit 0")
    assert "--mcp" in (out / "solution" / "solve.sh").read_text() and (out / "solution" / "reference.py").exists()
    assert "`cadfix` MCP server" in (out / "instruction.md").read_text()
