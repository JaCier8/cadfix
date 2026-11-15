"""MCP server (stdio, FastMCP) exposing the episode tools to an agent. Generic: tools come from the registries
(edit ops: cadfix.ops.edit.OP_SPECS; one run_check_<id> per check in the task's spec.json).

Env vars: CADFIX_TASK_DIR (public task dir, default /task), CADFIX_OUT_DIR (output dir, default /output).
Run: python -m cadfix.env.server

Shutdown is always quiet and exits 0: stdin closed (normal end), SIGTERM / SIGHUP (the client stopping us; a tool
call in progress finishes first) or a client that has gone away (BrokenPipe on the final write). Every tool call
already persists its result (log, episode.json, parts), so nothing is lost. Logging goes to stderr at WARNING only:
some clients (OpenCode) pipe stderr and never read it.
"""
from __future__ import annotations

import inspect
import os
import signal
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

from cadfix.core.spec import Spec
from cadfix.env.env import Env
from cadfix.ops.edit import OP_SPECS

CONVENTIONS = ("Units mm and degrees, world coordinates. Points are [x, y, z], directions [dx, dy, dz] (any length). "
               "Values are snapped to 0.001 mm.")
TYPES = {"number": float, "integer": int, "point": list[float], "vector": list[float],
         "polygon": list[list[float]], "box_edges": list[list[float]]}


# ------------------------------------------------------------ graceful shutdown
_STATE = {"busy": False, "stop": False}


def _exit_quietly(code: int = 0):
    """Flush what can be flushed, never raise on a closed pipe, exit with `code`."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    try:            # stdout may be a broken pipe: point it at /dev/null so no final flush can fail
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    except Exception:
        pass
    os._exit(code)


def _on_signal(signum, frame):
    if _STATE["busy"]:
        _STATE["stop"] = True       # let the running tool call finish (it persists its result), then exit
    else:
        _exit_quietly(0)


def _call(env_ref: dict, name: str, **kwargs) -> dict:
    _STATE["busy"] = True
    try:
        return env_ref["env"].call(name, **kwargs)
    finally:
        _STATE["busy"] = False
        if _STATE["stop"]:
            _exit_quietly(0)


def _client_gone(e: BaseException) -> bool:
    """True if `e` only says the client has gone (closed pipe, interrupt), also inside anyio exception groups."""
    if isinstance(e, BaseExceptionGroup):
        return all(_client_gone(x) for x in e.exceptions)
    return isinstance(e, (BrokenPipeError, ConnectionResetError, EOFError, KeyboardInterrupt))


def _tool(mcp: FastMCP, env_ref: dict, name: str, doc: str, params: list):
    """Register a tool `name` whose arguments are `params` [(name, type, required, doc)] and which calls
    env.call(name, **args)."""
    sig, ann = [], {}
    for pname, ptype, required, _ in params:
        t = TYPES.get(ptype, ptype)
        if required:
            sig.append(inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, annotation=t))
            ann[pname] = t
        else:
            sig.append(inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Optional[t]))
            ann[pname] = Optional[t]

    def fn(**kwargs) -> dict:
        return _call(env_ref, name, **{k: v for k, v in kwargs.items() if v is not None})
    fn.__name__ = name
    fn.__signature__ = inspect.Signature(sig, return_annotation=dict)
    fn.__annotations__ = {**ann, "return": dict}
    lines = [doc, ""] + [f"- {p}{'' if req else ' (optional)'}: {d}" for p, _, req, d in params]
    fn.__doc__ = "\n".join(lines)
    mcp.add_tool(fn, name=name, description=fn.__doc__)


QUERIES = [
    ("get_task", "The task: bug report, parts (editable or fixed, role, print orientation), the hinge joint, all keep-in "
                 "/ keep-out zones with their regions, every check with its thresholds, the reward formula and the "
                 "test_fit cost. " + CONVENTIONS, []),
    ("list_parts", "Parts with editable flag, role, volume, bounding box, print orientation; the joint.", []),
    ("part_info", "Volume, bounding box, number of edges / faces and validity of one part.",
     [("part", str, True, "part name")]),
    ("list_edges", "Edges of a part: id, type (line, circle, ...), end points, length, circle centre / radius, adjacent "
                   "faces with their outward normals at the edge midpoint. Ids change after every edit. " + CONVENTIONS,
     [("part", str, True, "part name"), ("near", "point", False, "only edges within `radius` of this point"),
      ("radius", "number", False, "search radius for `near` (mm, default 5)")]),
    ("list_faces", "Faces of a part: id, type (plane, cylinder, ...), centre, area, bbox, outward normal (planes), axis "
                   "and radius (cylinders). Ids change after every edit. " + CONVENTIONS,
     [("part", str, True, "part name"), ("near", "point", False, "only faces within `radius` of this point"),
      ("radius", "number", False, "search radius for `near` (mm, default 5)")]),
    ("find_edges_near", "Edges of a part closest to a point (up to 10, nearest first, with distance), optionally only "
                        "straight edges parallel to a direction. Does not depend on ids.",
     [("part", str, True, "part name"), ("point", "point", True, "query point"),
      ("direction", "vector", False, "only straight edges parallel to this (within 1 deg)"),
      ("radius", "number", False, "max distance (mm, default 1)")]),
    ("find_faces_near", "Faces of a part closest to a point (up to 10), optionally only planar faces with a given "
                        "outward normal.",
     [("part", str, True, "part name"), ("point", "point", True, "query point"),
      ("normal", "vector", False, "only planar faces with this outward normal (within 1 deg)"),
      ("radius", "number", False, "max distance (mm, default 1)")]),
    ("measure", "Interference and gap between two parts with the joint at an angle (moving parts rotated about the "
                "joint axis): min gap (capped at 5 mm), overlap volume, and the overlap as separate pieces (volume, "
                "bbox, centroid).",
     [("part_a", str, True, "first part"), ("part_b", str, True, "second part"),
      ("joint_angle_deg", "number", False, "joint angle in degrees (default 0 = closed)")]),
    ("section", "Cut a part with a plane and return its material regions in plane coordinates (u along x_dir projected "
                "into the plane, v = normal x u, origin at `point`): outer loops and holes as [[u, v], ...].",
     [("part", str, True, "part name"), ("point", "point", True, "point on the plane (2D origin)"),
      ("normal", "vector", True, "plane normal"), ("x_dir", "vector", False, "u direction (default: chosen for you)"),
      ("joint_angle_deg", "number", False, "joint angle for moving parts (default 0)"),
      ("window_mm", "number", False, "keep only |u|, |v| <= window_mm")]),
]


def _check_tool(env_ref: dict, check_id: str):
    def fn() -> dict:
        return _call(env_ref, "run_check", check_id=check_id)
    fn.__name__ = f"run_check_{check_id}"
    return fn


def build(env: Env | None = None, task_dir=None, out_dir=None) -> FastMCP:
    task_dir = task_dir or os.environ.get("CADFIX_TASK_DIR", "/task")
    out_dir = out_dir or os.environ.get("CADFIX_OUT_DIR", "/output")
    env_ref = {"env": env}
    spec = env.spec if env is not None else Spec.load(f"{task_dir}/spec.json")
    mcp = FastMCP("cadfix", log_level="WARNING", instructions=(
        "CAD tools for fixing an assembly. Start with get_task. Edits apply to editable parts only and are saved to "
        "the output dir after every edit; the parts as saved when the episode ends are graded. " + CONVENTIONS))
    if env is None:
        env_ref["env"] = Env(task_dir, out_dir)
    for name, doc, params in QUERIES:
        _tool(mcp, env_ref, name, doc, params)
    for name, (_, doc, params) in OP_SPECS.items():
        _tool(mcp, env_ref, name, doc + " Returns the part's new edge and face lists (ids change). " + CONVENTIONS,
              [("part", str, True, "editable part to change")] + list(params))
    _tool(mcp, env_ref, "undo", "Revert the last edit (any part).", [])
    for c in spec.checks:
        mcp.add_tool(_check_tool(env_ref, c.id), name=f"run_check_{c.id}",
                     description=f"Run check {c.id} ({c.role}) on the current parts: {c.description}. Free.")
    _tool(mcp, env_ref, "test_fit", "Run every check at once (gates, opening sweep, printability, change). The first "
                                    f"{spec.data.get('test_fit_cost', {}).get('free_calls', 0)} calls are free, then each "
                                    "costs reward (see get_task).", [])
    _tool(mcp, env_ref, "submit", "End the episode. The editable parts as saved now are graded; no further changes.", [])
    return mcp


def main():
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _on_signal)
    try:
        build().run()
    except BaseException as e:      # noqa: BLE001 - a real crash is re-raised below
        if not _client_gone(e):
            raise
    _exit_quietly(0)


if __name__ == "__main__":
    main()
