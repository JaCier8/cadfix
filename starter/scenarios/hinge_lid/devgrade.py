"""Dev grader for hinge_lid: apply ops (cadfix.ops.edit) to a copy of the parts and grade them with the REAL
spec (scenarios/hinge_lid/spec.py -> generic checks in cadfix/checks, the same code as cadfix.grade and the agent's
tools), in memory. Shared by evaluate.py, dev_sweep.py, brief.py, acceptance.py and the tests.

Output keys kept from task 2c (dev tables): s1 (met, ok_until, first_fail, min_clearance, ...), gates (one bool per
gate id), seal_width / seal_margin (G5), min_wall_ok / thinnest_new_wall (S2), new_overhang_mm2, printability,
removed / added / changed volume, changed_pct (of the enclosure), ratio_to_ref, s3, progress, reward.
side_collisions (pin / module / bracket material over the sweep) is a dev-only extra.
"""
from __future__ import annotations

import json
import time

import numpy as np

from cadfix.core import kernel
from cadfix.core.assembly import Assembly, Joint, Part, Zone
from cadfix.core.registry import CheckContext
from cadfix.core.spec import Spec
from cadfix.ops.edit import OpError, apply_ops  # noqa: F401  (OpError re-exported for callers)
from scenarios.hinge_lid import generator
from scenarios.hinge_lid import spec as hl_spec
from scenarios.hinge_lid import task as hl_task

EDITABLE = ("enclosure", "lid")


def load(level: str, seed: int, out_dir) -> tuple[dict, dict]:
    """params.json + STEP parts of a level/seed (generated first if missing; description refreshed if it predates
    task 4)."""
    d = generator.seed_dir(out_dir, level, seed)
    if not (d / "params.json").exists():
        generator.write(seed, out_dir, level)
    info = json.loads((d / "params.json").read_text())
    if "zones" not in info:
        info |= generator.describe(generator.params_from_info(info))
        (d / "params.json").write_text(json.dumps(info, indent=2))
    return info, {n: kernel.import_step(d / f"{n}.step") for n in generator.PART_NAMES}


def chamfer_op(info: dict, d_top: float, d_side: float) -> dict:
    """Full-edge chamfer of the rear wall's outer top edge (the evaluate --top/--side shortcut)."""
    a, b = np.array(info["rear_outer_top_edge"]["world"])
    return {"op": "chamfer", "part": "enclosure", "edge_near": [round(float(v), 3) for v in 0.5 * (a + b)],
            "d1": d_top, "d2": d_side}


def assembly(info: dict, shapes: dict) -> Assembly:
    t = hl_task.task_dict(info)
    parts = {n: Part(n, shapes[n], d["editable"], d["role"],
                     tuple(d["print"]["build_up"]) if "print" in d else None, d.get("print", {}).get("rule", ""))
             for n, d in t["parts"].items()}
    return Assembly(parts, Joint.from_dict(t["joint"]), [Zone.from_dict(z) for z in t["zones"]],
                    {k: v for k, v in t.items() if k not in ("parts", "joint", "zones")})


def _s1_row(res) -> dict:
    m = res.metrics
    return {"met": res.passed, "ok_until": m["ok_until"], "first_fail": m["first_fail"],
            "min_clearance": m["min_clearance"], "min_clearance_at": m["min_clearance_at"],
            "first_overlap_deg": m["first_overlap_deg"], "any_overlap": m["any_overlap"],
            "seconds": m["sweep_seconds"]}


class Grader:
    def __init__(self, info: dict, shapes: dict):
        self.info, self.shapes = info, shapes
        self.p = info["params"]
        self.joint = info["joint"]
        # dev tables only (first-contact pieces in the local frame); grading never uses the pose
        self.to_local = kernel.invert(np.array(info["pose"]["matrix"])) if info.get("pose") else kernel.IDENTITY
        self.original = assembly(info, shapes)
        self.spec = Spec(hl_spec.public_spec(info), hl_spec.private_values(info))
        self.cache = {}
        self.meshes = self.original.meshes()
        orig = self.spec.run_check(CheckContext(self.original, self.original, self.cache), "S1_opening")
        self.orig_s1 = _s1_row(orig)

    def apply(self, ops) -> tuple[dict, list[dict]]:
        return apply_ops(self.shapes, ops, EDITABLE, default_part="enclosure")

    def grade(self, ops, side_collisions: bool = False) -> dict:
        """Apply ops (list of dicts) and grade. OpError propagates (the agent's tool would return it)."""
        t0 = time.perf_counter()
        new_shapes, log = self.apply(ops)
        edited = sorted({e["part"] for e in log})
        cur = self.original.with_shapes({n: new_shapes[n] for n in edited})
        ev = self.spec.evaluate(CheckContext(cur, self.original, self.cache))
        r = ev["results"]
        s3m = r["S3_minimal_change"].metrics
        seal = r["G5_seal"].metrics["width_mm"]
        enc_vol = self.info["spec"]["S3"]["enclosure_volume_mm3"]
        out = {"ops": list(ops), "log": log, "edited": edited, "s1": _s1_row(r["S1_opening"]),
               "orig_s1_until": self.orig_s1["ok_until"],
               "gates": {g: r[g].passed for g in self.spec.gates},
               "bracket_fill": min(v for k, v in r["G3_keep_in"].metrics.items() if k.startswith("bracket")
                                   and isinstance(v, float)),
               "seal_width": seal, "seal_margin": round(seal - generator.SEAL_MIN_WIDTH, 4),
               "min_wall_ok": r["S2_min_wall"].passed, "thinnest_new_wall": r["S2_min_wall"].metrics["thinnest_new_mm"],
               "new_overhang_mm2": r["S2_overhang"].metrics["new_overhang_mm2"],
               "printability": ev["scores"]["printability"],
               "removed_mm3": s3m["removed_mm3"], "added_mm3": s3m["added_mm3"], "changed_mm3": s3m["changed_mm3"],
               "changed_pct": 100.0 * s3m["changed_mm3"] / enc_vol, "ratio_to_ref": s3m["ratio_to_reference"],
               "s3": ev["scores"]["minimal_change"], "progress": ev["progress"], "reward": ev["reward"],
               "checks": {k: v.to_dict() for k, v in r.items()}}
        if side_collisions:
            out["side_collisions"] = self.side_collisions(cur)
        out["seconds"] = time.perf_counter() - t0
        return out

    def side_collisions(self, cur: Assembly) -> dict:
        """Dev extra: max overlap (mm3) over 0..110 of pin vs enclosure / lid, module vs enclosure, lid vs bracket
        keep-in material. All 0 in every variant."""
        j = cur.joint
        enc, lid, pin, mod = (cur.parts[n].mesh for n in ("enclosure", "lid", "hinge_pin", "lid_module"))
        brackets = None
        for z in cur.zones:
            if z.name.startswith("bracket"):
                piece = enc ^ z.region.to_manifold()
                brackets = piece if brackets is None else brackets + piece
        out = {"pin_x_enclosure": kernel.intersection(pin, enc)[0], "pin_x_lid": 0.0, "module_x_enclosure": 0.0,
               "lid_x_brackets": 0.0}
        for ang in range(0, int(j.range_deg[1]) + 1):
            lr = kernel.rotate(lid, j.axis_point, j.axis_direction, ang)
            mr = kernel.rotate(mod, j.axis_point, j.axis_direction, ang)
            out["pin_x_lid"] = max(out["pin_x_lid"], kernel.intersection(lr, pin)[0])
            out["module_x_enclosure"] = max(out["module_x_enclosure"], kernel.intersection(mr, enc)[0])
            out["lid_x_brackets"] = max(out["lid_x_brackets"], kernel.intersection(lr, brackets)[0])
        return out
