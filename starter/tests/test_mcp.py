"""MCP smoke test with a real stdio client: the server starts as `python -m cadfix.env.server`, the reference fix of
L2 seed 0 is applied through the tools, test_fit passes, the grader gives 1.0, the log has every call."""
import asyncio
import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from cadfix import grade
from marks import SLOW
from scenarios.hinge_lid import generator
from scenarios.hinge_lid import task as hl_task


@pytest.fixture(scope="module")
def task(tmp_path_factory):
    gen = tmp_path_factory.mktemp("gen")
    d = hl_task.write_task("L2", 0, gen_out=gen, root=tmp_path_factory.mktemp("tasks"))
    info = json.loads((generator.seed_dir(gen, "L2", 0) / "params.json").read_text())
    return d, info


async def _episode(task_dir, out_dir, ops):
    params = StdioServerParameters(command=sys.executable, args=["-m", "cadfix.env.server"],
                                   env={**os.environ, "CADFIX_TASK_DIR": str(task_dir), "CADFIX_OUT_DIR": str(out_dir)})
    calls = []
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name: t for t in (await s.list_tools()).tools}

            async def call(name, **args):
                res = await s.call_tool(name, args)
                calls.append(name)
                return json.loads(res.content[0].text)
            task = await call("get_task")
            edge_hits = await call("find_edges_near", part="enclosure",
                                   point=ops[0]["origin"], direction=ops[0]["normal"], radius=0.5)
            s1 = await call("run_check_S1_opening")
            results = [await call("extrude_cut", **{k: v for k, v in op.items() if k != "op"}) for op in ops]
            fit = await call("test_fit")
            sub = await call("submit")
            after = await call("extrude_cut", **{k: v for k, v in ops[0].items() if k != "op"})
    return tools, task, edge_hits, s1, results, fit, sub, after, calls


def test_reference_fix_through_mcp(task, tmp_path):
    d, info = task
    out = tmp_path / "out"
    tools, task_info, edges, s1, results, fit, sub, after, calls = asyncio.run(
        _episode(d / "task", out, info["reference_ops"]))
    assert {"get_task", "list_edges", "list_faces", "find_edges_near", "find_faces_near", "measure", "section",
            "chamfer", "fillet", "offset_face", "extrude_cut", "cut_box", "add_box", "undo", "test_fit", "submit",
            "run_check_S1_opening", "run_check_G5_seal", "run_check_S3_minimal_change"} <= set(tools)
    assert "d1" in tools["chamfer"].inputSchema["properties"] and "part" in tools["chamfer"].inputSchema["required"]
    assert [c["id"] for c in task_info["checks"]][0] == "G1_valid_solids"
    assert edges["edges"] and edges["edges"][0]["type"] == "line"              # the rear wall's outer top edge
    assert not s1["passed"] and s1["metrics"]["ok_until"] == 45.0
    assert all(r.get("ok") and r["removed_mm3"] > 0 and r["edges"] for r in results)
    assert fit["gates_ok"] and fit["objective_met"] and fit["printability"] == 1.0
    assert sub["ok"] and "error" in after                                      # no edits after submit
    log = [json.loads(line) for line in (out / "actions.jsonl").read_text().splitlines()]
    assert [e["tool"] for e in log] == ["get_task", "find_edges_near", "run_check", "extrude_cut", "extrude_cut",
                                        "extrude_cut", "test_fit", "submit", "extrude_cut"]
    ep = json.loads((out / "episode.json").read_text())
    assert ep["test_fit_calls"] == 1 and ep["edits"] == 3 and ep["submitted"]
    assert sorted(p.name for p in (out / "snapshots").iterdir()) == ["000_start", "001_extrude_cut",
                                                                     "002_extrude_cut", "003_extrude_cut"]
    rep = grade.grade(d / "task", d / "pristine", out)
    assert rep["reward"] == 1.0 and rep["test_fit_cost"] == 0.0


def _server_exit_script():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "scripts" / "epipe_repro" / "server_exit.py"
    spec = importlib.util.spec_from_file_location("server_exit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@SLOW      # starts the server 3x (~5 s each); the quick run keeps test_signal_during_call_waits_for_the_call
@pytest.mark.parametrize("mode", ["stdin-eof", "sigterm", "stdout-closed"])
def test_server_shuts_down_quietly(task, mode, monkeypatch):
    """stdin closed, SIGTERM, or a client that has gone (BrokenPipe on the final write): exit 0, no traceback."""
    mod = _server_exit_script()
    monkeypatch.setattr(mod, "TASK", str(task[0] / "task"))
    assert mod.run(mode) == 0


def test_signal_during_call_waits_for_the_call(monkeypatch):
    """A SIGTERM while a tool call runs only marks the stop; the server exits right after the call returns."""
    from cadfix.env import server
    exits = []
    monkeypatch.setattr(server, "_exit_quietly", lambda code=0: exits.append(code))
    monkeypatch.setattr(server, "_STATE", {"busy": False, "stop": False})

    class FakeEnv:
        def call(self, name, **kw):
            server._on_signal(15, None)              # signal arrives mid-call
            assert exits == []                       # ... and does not exit yet
            return {"ok": name}
    assert server._call({"env": FakeEnv()}, "list_parts") == {"ok": "list_parts"}
    assert exits == [0]
    server._STATE.update(busy=False, stop=False)
    server._on_signal(15, None)                      # idle: exit at once
    assert exits == [0, 0]
