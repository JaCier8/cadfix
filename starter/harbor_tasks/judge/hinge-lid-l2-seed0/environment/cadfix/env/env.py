"""Episode environment: state, tools, log, snapshots. Generic: everything comes from the task dir.

The MCP server (cadfix/env/server.py), the scripted agents and the reference solver all call Env.call(tool, **args),
so they use exactly the same tool implementations.

out_dir layout:
  parts/<editable>.step     current state of every editable part (what the grader grades)
  episode.json              counters (calls, test_fit_calls, edits), submitted flag
  actions.jsonl             one line per call: n, time, tool, args, result, seconds
  snapshots/NNN_<tool>/     STEP + GLB of the editable parts at the start (000_start) and after every edit
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from cadfix.core import kernel
from cadfix.core.assembly import Assembly
from cadfix.core.registry import CheckContext
from cadfix.core.spec import Spec
from cadfix.ops import edit
from cadfix.ops.edit import OP_SPECS, OpError
from cadfix.ops.topology import Topology

MAX_CALLS = 150
GAP_CAP_MM = 5.0
EDIT_TOOLS = set(OP_SPECS) | {"undo"}


class ToolError(ValueError):
    """A tool call that cannot be served; the message goes back to the agent."""


def _r(v, n=3):
    return round(float(v), n) + 0.0


def _compact_edge(t: Topology, i: int) -> dict:
    e = t.edges[i]
    d = {"id": i, "type": e.geomType().lower(), "start": [_r(x) for x in e.startPoint().toTuple()],
         "end": [_r(x) for x in e.endPoint().toTuple()], "faces": t.edge_faces(i)}
    if d["type"] == "circle":
        d["center"], d["radius"] = [_r(x) for x in e.Center().toTuple()], _r(e.radius())
    return d


def _compact_face(t: Topology, i: int) -> dict:
    d = t.describe_face(i)
    d.pop("bbox", None)
    return d


class Env:
    def __init__(self, task_dir, out_dir, max_calls: int = MAX_CALLS, snapshots: bool = True, resume: bool = True):
        self.task_dir, self.out_dir = Path(task_dir), Path(out_dir)
        self.task = json.loads((self.task_dir / "task.json").read_text())
        self.spec = Spec.load(self.task_dir / "spec.json")
        self.original = Assembly.load(self.task_dir)
        self.max_calls, self.snapshots = max_calls, snapshots
        self.ocache: dict = {}
        self._topo: dict = {}
        self.history: list = []
        (self.out_dir / "parts").mkdir(parents=True, exist_ok=True)
        self.episode_path, self.log_path = self.out_dir / "episode.json", self.out_dir / "actions.jsonl"
        ep = json.loads(self.episode_path.read_text()) if resume and self.episode_path.exists() else None
        self.current = self.original
        if ep is not None:     # the server restarted mid-episode: continue from the saved parts
            shapes = {}
            for n in self.original.editable:
                f = self.out_dir / "parts" / f"{n}.step"
                if f.exists():
                    shapes[n] = kernel.import_step(f)
            self.current = self.original.with_shapes(shapes)
            self.episode = ep | {"resumed": ep.get("resumed", 0) + 1}
        else:
            self.episode = {"started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "calls": 0,
                            "test_fit_calls": 0, "edits": 0, "submitted": False,
                            "task": {k: self.task.get(k) for k in ("scenario", "level", "seed")}}
            self.log_path.write_text("")
            self._save_parts(self.original.editable)
            self._snapshot("start")
        self._write_episode()

    # ------------------------------------------------------------ plumbing
    def tools(self) -> list[str]:
        return sorted(n[2:] for n in dir(self) if n.startswith("t_")) + sorted(OP_SPECS)

    def call(self, tool: str, **kwargs) -> dict:
        """Run a tool by name, log it, turn errors into {"error": ...} (never raises for agent mistakes)."""
        t0 = time.perf_counter()
        self.episode["calls"] += 1
        try:
            if self.episode["submitted"]:
                raise ToolError("the episode is already submitted; nothing can be changed or checked any more")
            if self.episode["calls"] > self.max_calls and tool != "submit":
                raise ToolError(f"tool-call limit of {self.max_calls} reached; call submit")
            if tool in OP_SPECS:
                res = self._edit(tool, kwargs)
            elif hasattr(self, "t_" + tool):
                res = getattr(self, "t_" + tool)(**kwargs)
            else:
                raise ToolError(f"unknown tool {tool!r}")
        except (ToolError, OpError, KeyError, TypeError, ValueError) as e:
            res = {"error": str(e).strip("'\"")}
        dt = time.perf_counter() - t0
        with self.log_path.open("a") as f:
            f.write(json.dumps({"n": self.episode["calls"], "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "tool": tool, "args": kwargs, "result": res, "seconds": round(dt, 3)}, default=str) + "\n")
        self._write_episode()
        return res

    def _write_episode(self):
        self.episode_path.write_text(json.dumps(self.episode, indent=2))

    def _save_parts(self, names):
        for n in names:
            kernel.export_step(self.current.parts[n].shape, self.out_dir / "parts" / f"{n}.step")

    def _snapshot(self, label: str):
        if not self.snapshots:
            return
        d = self.out_dir / "snapshots" / f"{self.episode['edits']:03d}_{label}"
        d.mkdir(parents=True, exist_ok=True)
        import trimesh
        for n in self.original.editable:
            p = self.current.parts[n]
            kernel.export_step(p.shape, d / f"{n}.step")
            v, t = kernel.mesh_arrays(p.mesh)
            trimesh.Trimesh(v, t, process=False).export(str(d / f"{n}.glb"))

    def _part(self, name: str, editable: bool = False):
        if name not in self.current.parts:
            raise ToolError(f"unknown part {name!r}; parts: {sorted(self.current.parts)}")
        if editable and not self.current.parts[name].editable:
            raise ToolError(f"part {name!r} is fixed; editable parts: {self.current.editable}")
        return self.current.parts[name]

    def topology(self, name: str) -> Topology:
        shape = self.current.parts[name].shape
        t = self._topo.get(name)
        if t is None or t.shape is not shape:
            t = self._topo[name] = Topology(shape)
        return t

    def _ctx(self) -> CheckContext:
        return CheckContext(self.current, self.original, self.ocache)

    def _posed_mesh(self, name: str, angle: float):
        m = self.current.parts[name].mesh
        j = self.current.joint
        return kernel.rotate(m, j.axis_point, j.axis_direction, angle) if name in j.moving and angle else m

    # ------------------------------------------------------------ edits
    def _edit(self, tool: str, args: dict) -> dict:
        part = args.get("part")
        if part is None:
            raise ToolError(f"{tool}: give `part` (editable parts: {self.current.editable})")
        self._part(part, editable=True)
        op = {"op": tool, **args}
        new_shapes, _ = edit.apply_ops({n: p.shape for n, p in self.current.parts.items()}, [op],
                                       self.current.editable)
        before = self.current.parts[part]
        self.history.append(self.current)
        self.current = self.current.with_shapes({part: new_shapes[part]})
        removed, added = kernel.changed_volume(before.mesh, self.current.parts[part].mesh)
        self.episode["edits"] += 1
        self._save_parts([part])
        self._snapshot(tool)
        return self._edit_result(part, {"removed_mm3": _r(removed, 4), "added_mm3": _r(added, 4)})

    def _edit_result(self, part: str, extra: dict) -> dict:
        t = self.topology(part)
        return {"ok": True, "part": part, **extra, "volume_mm3": _r(self.current.parts[part].shape.Volume(), 3),
                "edits_so_far": self.episode["edits"],
                "note": "edge and face ids of this part changed; the lists below are current",
                "edges": [_compact_edge(t, i) for i in range(len(t.edges))],
                "faces": [_compact_face(t, i) for i in range(len(t.faces))]}

    def t_undo(self) -> dict:
        """Revert the last edit."""
        if not self.history:
            raise ToolError("nothing to undo")
        prev = self.history.pop()
        changed = [n for n in self.current.editable if prev.parts[n].shape is not self.current.parts[n].shape]
        self.current = prev
        self.episode["edits"] += 1
        self._save_parts(changed or self.current.editable)
        self._snapshot("undo")
        part = changed[0] if changed else self.current.editable[0]
        return self._edit_result(part, {"undone": True})

    # ------------------------------------------------------------ queries
    def t_get_task(self) -> dict:
        """Bug report, parts, joint, zones, every check with its thresholds, the reward formula."""
        s = self.spec.data
        return {"bug_report": self.task.get("bug_report"), "units": self.task.get("units"),
                "parts": self.task["parts"], "joint": self.task["joint"], "zones": self.task["zones"],
                "checks": [{"id": c["id"], "role": c["role"], "description": c.get("description", ""),
                            "params": c.get("params", {})} for c in s["checks"]],
                "reward": s["reward"], "rules": s.get("rules", {}), "test_fit_cost": s.get("test_fit_cost"),
                "max_tool_calls": self.max_calls}

    def t_list_parts(self) -> dict:
        out = {}
        for n, p in self.current.parts.items():
            lo, hi = kernel.bbox(p.mesh)
            out[n] = {"editable": p.editable, "role": p.role, "volume_mm3": _r(p.shape.Volume()),
                      "bbox_min": [_r(v) for v in lo], "bbox_max": [_r(v) for v in hi]}
            if p.build_up is not None:
                out[n]["print"] = {"rule": p.print_rule, "build_up": list(p.build_up)}
        return {"parts": out, "joint": self.task["joint"]}

    def t_part_info(self, part: str) -> dict:
        p = self._part(part)
        t = self.topology(part)
        lo, hi = kernel.bbox(p.mesh)
        return {"part": part, "editable": p.editable, "role": p.role, "volume_mm3": _r(p.shape.Volume()),
                "bbox_min": [_r(v) for v in lo], "bbox_max": [_r(v) for v in hi], "edges": len(t.edges),
                "faces": len(t.faces), "valid_solid": bool(p.shape.isValid())}

    def t_list_edges(self, part: str, near=None, radius: float = 5.0) -> dict:
        self._part(part)
        return {"part": part, "edges": self.topology(part).list_edges(near, radius)}

    def t_list_faces(self, part: str, near=None, radius: float = 5.0) -> dict:
        self._part(part)
        return {"part": part, "faces": self.topology(part).list_faces(near, radius)}

    def t_find_edges_near(self, part: str, point, direction=None, radius: float = 1.0) -> dict:
        self._part(part)
        t = self.topology(part)
        return {"part": part, "edges": [t.describe_edge(i) | {"distance": _r(d, 4)}
                                        for d, i in t.edges_near(point, direction, radius)[:10]]}

    def t_find_faces_near(self, part: str, point, normal=None, radius: float = 1.0) -> dict:
        self._part(part)
        t = self.topology(part)
        return {"part": part, "faces": [t.describe_face(i) | {"distance": _r(d, 4)}
                                        for d, i in t.faces_near(point, normal, radius)[:10]]}

    def t_measure(self, part_a: str, part_b: str, joint_angle_deg: float = 0.0) -> dict:
        self._part(part_a), self._part(part_b)
        a, b = self._posed_mesh(part_a, joint_angle_deg), self._posed_mesh(part_b, joint_angle_deg)
        gap = min(float(a.min_gap(b, GAP_CAP_MM)), GAP_CAP_MM)
        inter = a ^ b
        pieces = []
        for pc in inter.decompose():
            vol = float(pc.volume())
            if vol > 1e-6:
                lo, hi = kernel.bbox(pc)
                pieces.append({"volume_mm3": _r(vol, 6), "bbox_min": [_r(v) for v in lo], "bbox_max": [_r(v) for v in hi],
                               "centroid": [_r(v) for v in kernel.centroid(pc)]})
        pieces.sort(key=lambda p: -p["volume_mm3"])
        return {"part_a": part_a, "part_b": part_b, "joint_angle_deg": joint_angle_deg,
                "min_gap_mm": _r(gap, 4), "overlap_mm3": _r(float(inter.volume()), 6), "pieces": pieces[:20],
                "note": f"moving parts {list(self.current.joint.moving)} rotated about the joint; gaps >= "
                        f"{GAP_CAP_MM} reported as {GAP_CAP_MM}; 0 = touching or overlapping"}

    def t_section(self, part: str, point, normal, x_dir=None, joint_angle_deg: float = 0.0, window_mm=None) -> dict:
        self._part(part)
        n = np.asarray(normal, dtype=float)
        if n.shape != (3,) or np.linalg.norm(n) < 1e-9:
            raise ToolError("normal must be a non-zero vector [x, y, z]")
        if x_dir is not None and np.linalg.norm(np.cross(np.asarray(x_dir, float), n)) < 1e-6:
            raise ToolError("x_dir must not be parallel to normal")
        loops, axes = kernel.section_loops(self._posed_mesh(part, joint_angle_deg), point, n, x_dir, window_mm)
        return {"part": part, "joint_angle_deg": joint_angle_deg, "origin": [_r(v) for v in point],
                "u_dir": [_r(v, 6) for v in axes[0]], "v_dir": [_r(v, 6) for v in axes[1]],
                "normal": [_r(v, 6) for v in axes[2]], "regions": loops,
                "note": "2D points [u, v] (mm) relative to origin; world = origin + u * u_dir + v * v_dir"}

    # ------------------------------------------------------------ checks
    def t_run_check(self, check_id: str) -> dict:
        if check_id not in self.spec.by_id:
            raise ToolError(f"unknown check {check_id!r}; checks: {[c.id for c in self.spec.checks]}")
        c = self.spec.by_id[check_id]
        return {"id": check_id, "role": c.role, **self.spec.run_check(self._ctx(), check_id).to_dict()}

    def t_test_fit(self) -> dict:
        self.episode["test_fit_calls"] += 1
        ev = self.spec.evaluate(self._ctx())
        n = self.episode["test_fit_calls"]
        return {"gates_ok": ev["gates_ok"], "failed_gates": ev["failed_gates"], "objective_met": ev["objective_met"],
                "objective_progress": ev["progress"],
                "printability": ev["scores"].get("printability"),
                "checks": {k: {"passed": r.passed, "details": r.details} for k, r in ev["results"].items()},
                "test_fit_calls": n, "test_fit_cost_so_far": self.spec.test_fit_cost(n),
                "note": "minimal change is scored by the grader with the rule in spec.json (best known fix not shown)"}

    def t_submit(self) -> dict:
        self._save_parts(self.current.editable)
        self.episode["submitted"] = True
        return {"ok": True, "message": "submitted; the editable parts as saved in the output dir are graded"}
