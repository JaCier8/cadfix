"""Reference solver for hinge_lid (docs/SOLVER_DESIGN.md). TOOLS ONLY: it calls the same tools an agent gets
(in-process through cadfix.env.Env, or over MCP stdio against `python -m cadfix.env.server`) and never reads task
files, generator parameters, feasibility data or reference ops. Deterministic.

Steps: get_task -> S1 check -> overlap pieces at 20..110 deg (measure) -> the edge E nearest to the clash
(find_edges_near, parallel to the hinge) and the frame (hinge axis, rear-wall outward normal, wall-top normal) ->
lid knuckle segments from the lid's planar end faces (list_faces) -> per segment: sections of lid, lid_module and
enclosure in the segment's mid plane, sweep in 2D, smallest triangular relief on a 0.05 mm grid -> extrude_cut per
segment (world coordinates) -> 3D S1 check; on failure grow side / end extension (3 rounds), then a full-edge
chamfer fallback -> test_fit -> submit.

Run: python -m scenarios.hinge_lid.reference --task-dir T --out-dir O [--mcp]
(also runs as a standalone file: python reference.py --mcp, for Harbor's solution/solve.sh)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import threading

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

GRID = 0.05            # relief size grid (mm)
CLEARANCE = 0.3        # S1 rule (also read from the spec when available)
MARGIN = 0.005         # extra 2D clearance: tool rounding (0.001 mm) + tessellation
SEAL_MIN, SEAL_MARGIN, WALL_MIN = 1.5, 0.3, 1.2
EXTENSION = 0.35       # relief beyond each rib end along the hinge: clearance 0.3 + one grid step
ROUNDS = 3
WINDOW = 9.0           # section window around the axis point (mm)


def unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------- tool clients
class InProcessClient:
    """Calls Env.call directly (run_eval, tests). Same tool implementations as the MCP server."""

    def __init__(self, env):
        self.env = env

    def __call__(self, tool, **args):
        return self.env.call(tool, **args)

    def check(self, check_id):
        return self.env.call("run_check", check_id=check_id)

    def close(self):
        pass


class McpClient:
    """Synchronous wrapper around an MCP stdio session (server started as a subprocess)."""

    def __init__(self, command=None, args=None, env=None):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        self._params = StdioServerParameters(command=command or sys.executable,
                                             args=args or ["-m", "cadfix.env.server"], env=env or dict(os.environ))
        self._loop = asyncio.new_event_loop()
        self._ready, self._stop = threading.Event(), None
        self._session, self._error = None, None
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

        async def main():
            self._stop = asyncio.Event()
            try:
                async with stdio_client(self._params) as (r, w):
                    async with ClientSession(r, w) as s:
                        await s.initialize()
                        self._session = s
                        self._ready.set()
                        await self._stop.wait()
            except Exception as e:  # noqa: BLE001
                self._error = e
                self._ready.set()
        self._main = asyncio.run_coroutine_threadsafe(main(), self._loop)
        self._ready.wait(120)
        if self._error or self._session is None:
            raise RuntimeError(f"MCP server did not start: {self._error}")

    def __call__(self, tool, **args):
        fut = asyncio.run_coroutine_threadsafe(self._session.call_tool(tool, args), self._loop)
        res = fut.result(600)
        text = res.content[0].text if res.content else "{}"
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"error": text}

    def check(self, check_id):
        return self(f"run_check_{check_id}")

    def close(self):
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
            try:
                self._main.result(30)
            except Exception:  # noqa: BLE001
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)


# ---------------------------------------------------------------- 2D model
def _polys(regions) -> Polygon:
    return unary_union([Polygon(r["outer"], r["holes"]).buffer(0) for r in regions]) if regions else Polygon()


class Section2D:
    """One lid segment in its mid plane: u = rear-wall outward normal, v = hinge x u, origin on the hinge axis."""

    def __init__(self, moving: Polygon, wall: Polygon, e2, up_sign: float, clearance: float, seg_len: float):
        self.e2, self.s = np.asarray(e2, float), up_sign
        self.need = clearance + MARGIN
        self.area_eps = 1e-3 / max(seg_len, 1.0)      # S1 overlap limit 1e-3 mm3 spread over the segment length
        rot = [affinity.rotate(moving, th, origin=(0, 0)) for th in range(0, 111)]   # +theta = CCW in (u, v)
        # 0 deg is the closed position: the lid rests on the wall top (seal); a cut can only reduce overlap there,
        # and the rounded section coordinates leave a 1e-4 mm2 sliver on rotated parts, so start at 1 deg
        self.lift, self.clear = unary_union(rot[1:10]), unary_union(rot[10:])
        ex, ey = self.e2
        self.wall = wall.intersection(box(ex - 6, ey - 8, ex + 1, ey + 8))

    def cutter(self, top: float, side: float) -> Polygon:
        ex, ey, s = *self.e2, self.s
        pts = [(-top, 0), (-top, 0.01), (0.01, 0.01), (0.01, -side), (0, -side)]   # (outward, up) from E
        return Polygon([(ex + du, ey + s * dv) for du, dv in pts])

    def ok(self, top: float, side: float) -> bool:
        w = self.wall if top <= 0 or side <= 0 else self.wall.difference(self.cutter(top, side))
        if self.lift.intersection(w).area > self.area_eps:
            return False
        return self.clear.distance(w) >= self.need - 1e-9

    def best(self, top_max: float, side_max: float):
        """Smallest-area (top, side) on the GRID meeting ok(); (0, 0) if the uncut wall already clears; None if no
        size works."""
        if self.ok(0.0, 0.0):
            return 0.0, 0.0
        tops = [round(i * GRID, 3) for i in range(1, int(top_max / GRID + 1e-9) + 1)]
        sides = [round(i * GRID, 3) for i in range(1, int(side_max / GRID + 1e-9) + 1)]
        best = None
        for top in tops:
            if not sides or not self.ok(top, sides[-1]):
                continue
            lo, hi = -1, len(sides) - 1
            while hi - lo > 1:
                mid = (lo + hi) // 2
                lo, hi = (lo, mid) if self.ok(top, sides[mid]) else (mid, hi)
            cand = (top * sides[hi], top, sides[hi])
            best = cand if best is None or cand < best else best
        return None if best is None else (best[1], best[2])


# ---------------------------------------------------------------- solver
class Solver:
    def __init__(self, client, log=None):
        self.c = client
        self.log_lines = []
        self._log = log

    def log(self, msg):
        self.log_lines.append(msg)
        if self._log:
            self._log(msg)

    def run(self) -> dict:
        try:
            return self._run()
        except Exception as e:  # noqa: BLE001 - the reference run must always end with submit
            self.log(f"solver error: {type(e).__name__}: {e}")
            self.c("submit")
            return {"ok": False, "error": str(e), "log": self.log_lines}

    def _run(self) -> dict:
        task = self.c("get_task")
        j = task["joint"]
        self.a0, self.a = np.asarray(j["axis_point"], float), unit(j["axis_direction"])
        up = unit(task["parts"]["enclosure"]["print"]["build_up"])
        s1spec = {c["id"]: c for c in task["checks"]}["S1_opening"]["params"]
        clearance = s1spec.get("clearance_mm", CLEARANCE)
        s1 = self.c.check("S1_opening")
        if s1["passed"]:
            self.log("S1 already met; nothing to fix")
            self.c("submit")
            return {"ok": True, "ops": [], "log": self.log_lines}
        ff = s1["metrics"]["first_fail"]
        self.log(f"original: S1 holds up to {s1['metrics']['ok_until']} deg, first failing step {ff}")

        # 1. colliding regions along the hinge
        angles = sorted({float(a) for a in range(20, 111, 10)} | ({float(ff["angle"])} if ff else set()))
        pieces = []
        for th in angles:
            m = self.c("measure", part_a="lid", part_b="enclosure", joint_angle_deg=th)
            pieces += [dict(pc, angle=th) for pc in m.get("pieces", [])]
        if not pieces:
            raise RuntimeError("no overlap between lid and enclosure at any sampled angle")
        regions = self._cluster(pieces)
        self.log(f"{len(regions)} colliding region(s) along the hinge at s = "
                 + ", ".join(f"{r['s']:.2f}" for r in regions))

        # 2. the edge E and the frame
        big = max(pieces, key=lambda p: p["volume_mm3"])
        hits = self.c("find_edges_near", part="enclosure", point=big["centroid"], direction=self.a.tolist(), radius=3.0)
        if not hits.get("edges"):
            raise RuntimeError("no straight edge parallel to the hinge near the clash")
        e = hits["edges"][0]
        normals = [unit(f["normal_at_mid"]) for f in e["faces"]]
        k = int(np.argmax([n @ up for n in normals]))
        self.n_top, self.n_out = normals[k], normals[1 - k]
        self.e0 = np.asarray(e["start"], float)
        self.edge = e
        self.log(f"edge E: {e['start']} -> {e['end']}, top normal {np.round(self.n_top, 4).tolist()}, "
                 f"outward normal {np.round(self.n_out, 4).tolist()}")

        # 3. lid knuckle segments from the lid's end faces
        segments = self._segments()
        self.log("lid segments (s along the hinge): " + ", ".join(f"[{a:.3f}, {b:.3f}]" for a, b in segments))
        plan = []
        for s0, s1_ in segments:
            hit = [r for r in regions if s0 - 0.5 <= r["s"] <= s1_ + 0.5]
            plan.append({"s0": s0, "s1": s1_, "regions": len(hit)})
        for r in regions:
            if not any(p["s0"] - 0.5 <= r["s"] <= p["s1"] + 0.5 for p in plan):
                self.log(f"region at s={r['s']:.2f} maps to no lid segment: relief over its extent")
                plan.append({"s0": r["lo"] - 0.5 + EXTENSION, "s1": r["hi"] + 0.5 - EXTENSION, "regions": 1,
                             "fallback": True})

        # 4. size each relief from sections
        for p in plan:
            p["size"] = self._size(p, clearance)
            self.log(f"segment [{p['s0']:.3f}, {p['s1']:.3f}]: relief top x side = {p['size']}")
        need = [p for p in plan if p["size"] and p["size"] != (0.0, 0.0)]
        if any(p["size"] is None for p in plan):
            self.log("a segment has no valid relief size in the 2D model")

        # 5. cut, verify in 3D, grow if needed
        grow_side, grow_ext = 0.0, 0.0
        for rnd in range(ROUNDS + 1):
            ops = [self._relief_op(p, grow_side, EXTENSION + grow_ext) for p in need if p["size"]]
            done = 0
            for op in ops:
                r = self.c("extrude_cut", **op)
                if r.get("error"):
                    self.log(f"extrude_cut failed: {r['error']}")
                    break
                done += 1
            s1 = self.c.check("S1_opening") if done == len(ops) else {"passed": False, "metrics": {}}
            if s1["passed"]:
                self.log(f"round {rnd}: S1 met (min clearance {s1['metrics'].get('min_clearance')} mm)")
                fit = self.c("test_fit")
                self.log(f"test_fit: gates_ok={fit.get('gates_ok')} failed={fit.get('failed_gates')} "
                         f"printability={fit.get('printability')}")
                self.c("submit")
                return {"ok": True, "ops": ops, "rounds": rnd, "log": self.log_lines}
            self.log(f"round {rnd}: S1 not met ({s1['metrics'].get('first_fail')}); growing the reliefs")
            for _ in range(done):
                self.c("undo")
            grow_side, grow_ext = grow_side + GRID, grow_ext + GRID

        # 6. fallback: one full-edge chamfer covering every segment's need
        tops = [p["size"][0] for p in need if p["size"]] or [0.5]
        sides = [p["size"][1] for p in need if p["size"]] or [1.5]
        mid = (np.asarray(self.edge["start"]) + np.asarray(self.edge["end"])) / 2
        op = {"part": "enclosure", "edge_near": mid.round(3).tolist(), "edge_direction": self.a.round(6).tolist(),
              "d1": max(tops), "d2": round(max(sides) + GRID, 3), "d1_face_normal": self.n_top.round(6).tolist()}
        r = self.c("chamfer", **op)
        self.log(f"fallback full-edge chamfer {op['d1']} x {op['d2']}: {r.get('error', 'ok')}")
        self.c("test_fit")
        self.c("submit")
        return {"ok": False, "ops": [op], "fallback": True, "log": self.log_lines}

    # ------------------------------------------------------------ helpers
    def s_of(self, p) -> float:
        return float((np.asarray(p, float) - self.a0) @ self.a)

    def _cluster(self, pieces) -> list[dict]:
        rows = []
        for pc in pieces:
            corners = np.array([[x, y, z] for x in (pc["bbox_min"][0], pc["bbox_max"][0])
                                for y in (pc["bbox_min"][1], pc["bbox_max"][1])
                                for z in (pc["bbox_min"][2], pc["bbox_max"][2])])
            ss = [self.s_of(c) for c in corners]
            rows.append((self.s_of(pc["centroid"]), min(ss), max(ss)))
        rows.sort()
        out = []
        for s, lo, hi in rows:
            if out and s - out[-1]["s_last"] <= 1.0:
                r = out[-1]
                r["n"] += 1
                r["s"] = r["s"] + (s - r["s"]) / r["n"]
                r["lo"], r["hi"], r["s_last"] = min(r["lo"], lo), max(r["hi"], hi), s
            else:
                out.append({"s": s, "lo": lo, "hi": hi, "n": 1, "s_last": s})
        return out

    def _segments(self) -> list[tuple[float, float]]:
        faces = self.c("list_faces", part="lid")["faces"]
        ends = []
        for f in faces:
            if f["type"] != "plane":
                continue
            n = unit(f["normal"])
            if abs(n @ self.a) < 0.999:
                continue
            rel = np.asarray(f["center"], float) - self.a0
            if np.linalg.norm(rel - (rel @ self.a) * self.a) > 5.0:
                continue
            ends.append((round(self.s_of(f["center"]), 3), 1 if n @ self.a > 0 else -1))
        ends = sorted(set(ends))
        segs, start = [], None
        for s, sign in ends:
            if sign < 0:
                start = s
            elif start is not None:
                segs.append((start, s))
                start = None
        return segs

    def _section(self, part, s) -> dict:
        p = self.a0 + s * self.a
        return self.c("section", part=part, point=p.round(4).tolist(), normal=self.a.tolist(),
                      x_dir=self.n_out.tolist(), window_mm=WINDOW)

    def _size(self, seg, clearance):
        s_mid = 0.5 * (seg["s0"] + seg["s1"])
        lid = self._section("lid", s_mid)
        mod = self._section("lid_module", s_mid)
        enc = self._section("enclosure", s_mid)
        u, v = np.asarray(lid["u_dir"]), np.asarray(lid["v_dir"])
        origin = np.asarray(lid["origin"])
        e2 = ((self.e0 - origin) @ u, (self.e0 - origin) @ v)
        sv = 1.0 if v @ self.n_top > 0 else -1.0
        moving = unary_union([_polys(lid["regions"]), _polys(mod["regions"])])
        wall = _polys(enc["regions"])
        t = self._wall_width(wall, e2, sv)
        side_max = self._side_limit(seg, e2, sv)
        model = Section2D(moving, wall, e2, sv, clearance, seg["s1"] - seg["s0"])
        top_max = round(t - SEAL_MIN - SEAL_MARGIN, 3)
        self.log(f"  wall top width {t:.3f}, top <= {top_max}, side <= {side_max}")
        return model.best(min(top_max, t - WALL_MIN), side_max)

    def _wall_width(self, wall, e2, sv) -> float:
        ex, ey = e2
        y = ey - 0.02 * sv
        line = LineString([(ex + 0.5, y), (ex - 10.0, y)])
        inter = line.intersection(wall)
        parts = [g for g in getattr(inter, "geoms", [inter]) if g.length > 0]
        near = [g for g in parts if g.distance(LineString([(ex, y), (ex - 0.05, y)])) < 0.05]
        return float(near[0].length) if near else 0.0

    def _side_limit(self, seg, e2, sv) -> float:
        """How deep a cut may go down the outer face: 0.5 mm above the enclosure knuckle bracket next to the
        segment (section just beyond the segment's end), at most 4 mm."""
        sec = self._section("enclosure", seg["s1"] + 1.0)
        mat = _polys(sec["regions"])
        ex, ey = e2
        strip = mat.intersection(box(ex + 0.02, ey - 8, ex + 0.4, ey + 8))
        if strip.is_empty:
            return 4.0
        vs = [c[1] for g in getattr(strip, "geoms", [strip]) for c in g.exterior.coords]
        below = [(ey - vv) * sv for vv in vs if (ey - vv) * sv > 0.05]
        if not below:
            return 4.0
        return round(math.floor((min(below) - 0.5) / GRID) * GRID, 3)

    def _relief_op(self, seg, grow_side, ext) -> dict:
        top, side = seg["size"]
        side = round(side + grow_side, 3)
        n_e = self.a if np.cross(self.a, self.n_out) @ self.n_top > 0 else -self.a
        s_start = seg["s0"] - ext if n_e @ self.a > 0 else seg["s1"] + ext
        origin = self.e0 + (s_start - self.s_of(self.e0)) * self.a
        return {"part": "enclosure", "origin": origin.round(4).tolist(), "normal": n_e.round(6).tolist(),
                "x_dir": self.n_out.round(6).tolist(),
                "polygon_2d": [[-top, 0.0], [-top, 0.01], [0.01, 0.01], [0.01, -side], [0.0, -side]],
                "depth_from": 0.0, "depth_to": round(seg["s1"] - seg["s0"] + 2 * ext, 4)}


def solve(client, log=None) -> dict:
    return Solver(client, log).run()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task-dir", default=os.environ.get("CADFIX_TASK_DIR", "/task"))
    ap.add_argument("--out-dir", default=os.environ.get("CADFIX_OUT_DIR", "/output"))
    ap.add_argument("--mcp", action="store_true", help="talk to `python -m cadfix.env.server` over stdio")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    log = None if a.quiet else (lambda m: print(m, flush=True))
    if a.mcp:
        env = {**os.environ, "CADFIX_TASK_DIR": a.task_dir, "CADFIX_OUT_DIR": a.out_dir}
        client = McpClient(env=env)
    else:
        from cadfix.env.env import Env
        client = InProcessClient(Env(a.task_dir, a.out_dir))
    try:
        res = solve(client, log)
    finally:
        client.close()
    print(json.dumps({k: v for k, v in res.items() if k != "log"}, default=str))


if __name__ == "__main__":
    main()
