"""Episode state + tool implementations. The MCP server and all scripted agents call these same methods."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import geom as g
from .grader import check

MAX_CALLS = 80
EDIT_TOOLS = {"add_box", "subtract_box", "add_cylinder", "subtract_cylinder", "undo"}


def _r(v, n=3):
    return round(float(v), n)


class FitFixEnv:
    def __init__(self, task_dir, out_dir):
        self.task_dir = Path(task_dir)
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.task = json.loads((self.task_dir / "task.json").read_text())
        self.editable = self.task["editable_part"]
        self.parts = {n: g.load_stl(self.task_dir / "parts" / f"{n}.stl")
                      for n in [self.editable, *self.task["fixed_parts"]]}
        self.original = self.parts[self.editable]
        self.history: list = []
        self.test_fit_left = int(self.task["test_fit_budget"])
        self.calls = 0
        self.submitted = False
        self.log_path = self.out_dir / "actions.jsonl"
        self.log_path.write_text("")
        self._save()

    # ------------------------------------------------------------ plumbing
    def call(self, tool: str, **kwargs) -> dict:
        """Run a tool by name, log it, and turn errors into a message instead of a crash."""
        t0 = time.time()
        self.calls += 1
        try:
            if self.submitted:
                res = {"error": "episode already submitted"}
            elif self.calls > MAX_CALLS and tool != "submit":
                res = {"error": f"tool-call limit of {MAX_CALLS} reached; call submit"}
            else:
                res = getattr(self, "t_" + tool)(**kwargs)
        except (ValueError, KeyError, TypeError) as e:
            res = {"error": str(e)}
        with self.log_path.open("a") as f:
            f.write(json.dumps({"t": round(time.time() - t0, 3), "n": self.calls, "tool": tool,
                                "args": kwargs, "result": res}, default=str) + "\n")
        return res

    def _part(self, name):
        if name not in self.parts:
            raise KeyError(f"unknown part '{name}', choose from {list(self.parts)}")
        return self.parts[name]

    def _save(self):
        g.save_stl(self.parts[self.editable], self.out_dir / f"{self.editable}.stl")

    def _edit(self, new):
        if new.is_empty() or new.volume() <= 0:
            raise ValueError("edit would delete the whole part; rejected")
        self.history.append(self.parts[self.editable])
        self.parts[self.editable] = new
        self._save()
        lo, hi = g.bbox(new)
        return {"ok": True, "volume_mm3": _r(new.volume(), 2), "bbox_min": [_r(v) for v in lo],
                "bbox_max": [_r(v) for v in hi], "edits_so_far": len(self.history)}

    # ------------------------------------------------------------ info tools
    def t_get_task(self):
        return self.task

    def t_list_parts(self):
        return {n: {"editable": n == self.editable, "description": self.task["parts"].get(n, "")} for n in self.parts}

    def t_part_info(self, part: str):
        m = self._part(part)
        lo, hi = g.bbox(m)
        return {"part": part, "editable": part == self.editable, "bbox_min": [_r(v) for v in lo],
                "bbox_max": [_r(v) for v in hi], "volume_mm3": _r(m.volume(), 2), "triangles": m.num_tri()}

    def t_check_interference(self, part_a: str, part_b: str):
        v, bb = g.interference(self._part(part_a), self._part(part_b))
        out = {"overlap_volume_mm3": _r(v), "colliding": v > 0}
        if bb:
            out["overlap_bbox_min"] = [_r(x) for x in bb[0]]
            out["overlap_bbox_max"] = [_r(x) for x in bb[1]]
        return out

    def t_min_clearance(self, part_a: str, part_b: str):
        d = g.min_gap(self._part(part_a), self._part(part_b), 10.0)
        return {"min_gap_mm": _r(d), "note": "0 means touching or overlapping; 10 means 10 mm or more"}

    def t_section(self, part: str, axis: str, value: float):
        loops = g.section(self._part(part), axis, float(value))
        out = []
        for l in loops:
            s = g.loop_summary(l)
            s["is_hole"] = bool(l["is_hole"])
            if len(l["points"]) <= 16:
                s["points"] = [[_r(a), _r(b)] for a, b in l["points"]]
            out.append(s)
        return {"part": part, "plane": f"{axis}={value}", "coords": out[0]["coords"] if out else None,
                "loops": out, "note": "is_hole=true loops are openings inside material"}

    def t_find_holes(self, part: str, axis: str, value: float):
        res = self.t_section(part, axis, value)
        res["loops"] = [l for l in res["loops"] if l["is_hole"]]
        return res

    def t_check_printability(self):
        m = self.parts[self.editable]
        tmin, where, _ = g.wall_thickness(m)
        need = self.task["constraints"]["min_wall_mm"]
        return {"min_wall_mm": _r(tmin), "thinnest_at": where, "required_min_wall_mm": need, "ok": tmin >= need}

    # ------------------------------------------------------------ edit tools (editable part only)
    def t_add_box(self, min: list, max: list):
        return self._edit(self.parts[self.editable] + g.box(min, max))

    def t_subtract_box(self, min: list, max: list):
        return self._edit(self.parts[self.editable] - g.box(min, max))

    def t_add_cylinder(self, axis: str, center: list, radius: float, start: float, end: float):
        return self._edit(self.parts[self.editable] + g.cylinder(axis, center, radius, start, end))

    def t_subtract_cylinder(self, axis: str, center: list, radius: float, start: float, end: float):
        return self._edit(self.parts[self.editable] - g.cylinder(axis, center, radius, start, end))

    def t_undo(self):
        if not self.history:
            return {"error": "nothing to undo"}
        self.parts[self.editable] = self.history.pop()
        self._save()
        return {"ok": True, "edits_so_far": len(self.history)}

    # ------------------------------------------------------------ expensive / final
    def t_test_fit(self):
        if self.test_fit_left <= 0:
            return {"error": "test_fit budget used up"}
        self.test_fit_left -= 1
        rep = check(self.parts[self.editable], self.task_dir,
                    parts={n: m for n, m in self.parts.items() if n != self.editable}, orig=self.original)
        rep["change"].pop("score", None)
        return {"report": rep, "test_fit_left": self.test_fit_left}

    def t_submit(self):
        self.submitted = True
        self._save()
        return {"ok": True, "message": "submitted; the grader will evaluate parts/enclosure as saved"}
