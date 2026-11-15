"""Dev grader for hinge_lid: apply ops (cadfix.ops.edit) to a copy of the parts and measure what test_fit would
report: S1 (generic sweep check), dev versions of the gates an edit can break, printability, minimal change (S3)
and the reward. Shared by evaluate.py, dev_sweep.py, brief.py and the tests.

Dev approximations until task 4 (generic checks):
- seal: smallest width of the ring of upward-facing enclosure faces at the wall-top plane (closed: the lid's flat
  underside covers the whole wall top, so this ring is the contact); gate: >= 1.5 mm (G5: eroded by 0.75 mm it
  must stay a closed ring).
- thinnest wall: smallest ring width of horizontal enclosure sections (wall top band at 0.1 mm steps, then
  1 mm steps down to the floor).
- brackets: enclosure knuckle bracket keep-in boxes (oriented, world frame) filled >= 99 %.
- closed: no overlap at 0 deg; valid: every edited part is one valid solid.
- printability: thinnest wall >= 1.2 and no new downward-facing area (> 45 deg) in each edited part's print
  orientation.
- S3: changed volume (removed + added) / V_ref scored with the level's factors; S1 progress = 0.5 * angle
  progress + 0.5 * clearance progress (scenario.json spec.score.S1_opening).
Wall-top plane and section heights are taken in the scenario's local frame (the grader knows the pose).
Lid keep-in zones (knuckles, ribs, frame) are not defined yet; lid edits are applied but not gated.
"""
from __future__ import annotations

import json
import time

import numpy as np

from cadfix.checks.sweep import opening_check
from cadfix.core import kernel
from cadfix.core.reward import ratio_score, sweep_progress
from cadfix.ops.edit import OpError, apply_ops  # noqa: F401  (OpError re-exported for callers)
from scenarios.hinge_lid import generator

KEEP_IN_FILL = 0.99      # scenario.json G3
OVERHANG_TOL_MM2 = 0.01  # new downward-facing area below this counts as none
EDITABLE = ("enclosure", "lid")


def load(level: str, seed: int, out_dir) -> tuple[dict, dict]:
    """params.json + STEP parts of a level/seed (generated first if missing)."""
    d = generator.seed_dir(out_dir, level, seed)
    if not (d / "params.json").exists():
        generator.write(seed, out_dir, level)
    info = json.loads((d / "params.json").read_text())
    return info, {n: kernel.import_step(d / f"{n}.step") for n in generator.PART_NAMES}


def chamfer_op(info: dict, d_top: float, d_side: float) -> dict:
    """Full-edge chamfer of the rear wall's outer top edge (the evaluate --top/--side shortcut)."""
    a, b = np.array(info["rear_outer_top_edge"]["world"])
    return {"op": "chamfer", "part": "enclosure", "edge_near": [round(float(v), 3) for v in 0.5 * (a + b)],
            "d1": d_top, "d2": d_side}


class Grader:
    def __init__(self, info: dict, shapes: dict):
        self.info, self.shapes = info, shapes
        self.p = info["params"]
        self.spec = info["spec"]
        self.joint = info["joint"]
        m = np.array(info["pose"]["matrix"]) if info.get("pose") else kernel.IDENTITY
        self.to_local = kernel.invert(m)
        self.meshes = {n: kernel.to_manifold(s) for n, s in shapes.items()}
        self.orig_s1 = self.s1(self.meshes)
        self.orig_down = {n: kernel.downward_area(self.meshes[n], up=info["print_orientation"][n]["build_up"])
                          for n in EDITABLE}
        self.zones = [(z["name"], kernel.oriented_box(z["world"]["origin"], z["world"]["edges"]))
                      for z in info["keep_in"]]
        self.zone_orig = {nm: float((self.meshes["enclosure"] ^ zb).volume()) for nm, zb in self.zones}

    # ------------------------------------------------------------ measurements
    def s1(self, meshes: dict) -> dict:
        s = self.spec["S1"]
        return opening_check({n: meshes[n] for n in s["moving"]}, {n: meshes[n] for n in s["fixed"]},
                             self.joint["axis_point"], self.joint["axis_direction"], s["range_deg"], s["step_deg"],
                             s["overlap_eps_mm3"], s["clearance_mm"], s["clearance_from_deg"], s["search_mm"])

    def walls(self, enc_mesh) -> tuple[float, float]:
        """(seal width, thinnest wall) of the enclosure, measured in the local frame."""
        local = kernel.transform_mesh(enc_mesh, self.to_local)
        H, t, fb = self.p["H"], self.p["t"], self.p["free_band"]
        seal = kernel.ring_width(kernel.faces_region_at_z(local, H), upper=2 * t)
        wall = seal
        levels = [H - 0.001 - 0.1 * k for k in range(int((fb + 1.0) / 0.1) + 1)]
        levels += list(np.arange(H - fb - 2.0, self.p["floor"] + 0.4, -1.0))
        for z in levels:
            region = kernel.slice_region(local, float(z))
            if wall > 0 and kernel._is_ring(region.buffer(-(wall / 2 - 1e-4))):
                continue                    # this section cannot be thinner than the current minimum
            wall = min(wall, kernel.ring_width(region, upper=2 * t))
        return seal, wall

    def side_collisions(self, meshes: dict, enc_mesh) -> dict:
        """Max overlap (mm3) over 0..110 of: pin vs enclosure / lid, module vs enclosure, lid vs bracket keep-in
        material. All should be 0 in every variant."""
        s = self.spec["S1"]
        steps = [round(i * s["step_deg"], 6) for i in range(int(round(s["range_deg"][1] / s["step_deg"])) + 1)]
        brackets = None
        for _, zb in self.zones:
            piece = enc_mesh ^ zb
            brackets = piece if brackets is None else brackets + piece
        out = {"pin_x_enclosure": kernel.intersection(meshes["hinge_pin"], enc_mesh)[0],
               "pin_x_lid": 0.0, "module_x_enclosure": 0.0, "lid_x_brackets": 0.0}
        for ang in steps:
            lid = kernel.rotate(meshes["lid"], self.joint["axis_point"], self.joint["axis_direction"], ang)
            mod = kernel.rotate(meshes["lid_module"], self.joint["axis_point"], self.joint["axis_direction"], ang)
            out["pin_x_lid"] = max(out["pin_x_lid"], kernel.intersection(lid, meshes["hinge_pin"])[0])
            out["module_x_enclosure"] = max(out["module_x_enclosure"], kernel.intersection(mod, enc_mesh)[0])
            out["lid_x_brackets"] = max(out["lid_x_brackets"], kernel.intersection(lid, brackets)[0])
        return out

    # ------------------------------------------------------------ grading
    def apply(self, ops) -> tuple[dict, list[dict]]:
        return apply_ops(self.shapes, ops, EDITABLE, default_part="enclosure")

    def grade(self, ops, side_collisions: bool = False) -> dict:
        """Apply ops (list of dicts) and grade. OpError propagates (the agent's tool would return it)."""
        t0 = time.perf_counter()
        new_shapes, log = self.apply(ops)
        edited = sorted({e["part"] for e in log})
        meshes = dict(self.meshes)
        for n in edited:
            meshes[n] = kernel.to_manifold(new_shapes[n])
        enc = meshes["enclosure"]
        s1 = self.s1(meshes)
        seal, wall = self.walls(enc)
        fills = {nm: (float((enc ^ zb).volume()) / self.zone_orig[nm] if self.zone_orig[nm] > 0 else 1.0)
                 for nm, zb in self.zones}
        removed = added = 0.0
        for n in edited:
            r, a = kernel.changed_volume(self.meshes[n], meshes[n])
            removed, added = removed + r, added + a
        new_down = max([kernel.downward_area(meshes[n], up=self.info["print_orientation"][n]["build_up"])
                        - self.orig_down[n] for n in edited] or [0.0])
        gates = {"valid": all(new_shapes[n].isValid() for n in edited),
                 "seal": seal >= generator.SEAL_MIN_WIDTH - 1e-3,
                 "brackets": min(fills.values()) >= KEEP_IN_FILL,
                 "closed": s1["first_overlap_deg"] != 0.0}
        printability = 1.0 if (wall >= generator.MIN_WALL - 1e-3 and new_down <= OVERHANG_TOL_MM2) else 0.0
        s3spec = self.spec["S3"]
        changed = removed + added
        changed_pct = 100.0 * changed / s3spec["enclosure_volume_mm3"]
        ratio = changed / s3spec["V_ref_mm3"]
        s3 = ratio_score(changed, s3spec["V_ref_mm3"], s3spec["full_factor"], s3spec["zero_factor"])
        prog = sweep_progress(s1["ok_until"], self.orig_s1["ok_until"], self.spec["S1"]["range_deg"][1],
                              s1["min_clearance"], self.spec["S1"]["clearance_mm"], s1["any_overlap"])
        reward = generator.REWARD_POLICY.reward(all(gates.values()), s1["met"], prog,
                                                {"printability": printability, "minimal_change": s3})
        out = {"ops": list(ops), "log": log, "edited": edited, "s1": s1, "orig_s1_until": self.orig_s1["ok_until"],
               "gates": gates, "bracket_fill": min(fills.values()), "seal_width": seal,
               "seal_margin": seal - generator.SEAL_MIN_WIDTH, "min_wall": wall, "new_overhang_mm2": new_down,
               "printability": printability, "removed_mm3": removed, "added_mm3": added, "changed_mm3": changed,
               "changed_pct": changed_pct, "ratio_to_ref": ratio, "s3": s3, "progress": prog, "reward": reward}
        if side_collisions:
            out["side_collisions"] = self.side_collisions(meshes, enc)
        out["seconds"] = time.perf_counter() - t0
        return out
