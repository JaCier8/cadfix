"""Procedural electronics-enclosure assembly with an injected defect.

Parts (all STL, mm):
  enclosure  - EDITABLE. Open-top box with 4 screw standoffs and a USB-C opening in the front wall (x=0).
  pcb        - fixed. Board with 4 mounting holes and a USB-C receptacle at its front edge.
  usb_plug   - fixed. USB-C cable plug in its fully inserted position (shell + overmold outside the box).
  lid        - fixed. Top plate with a lip that drops into the enclosure opening.

Defect D1: the USB opening in the front wall is shifted, so the plug hits the wall.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from . import geom as g

# Real-world-ish dimensions (mm)
WALL = 2.0
FLOOR = 2.0
MARGIN = 1.0          # gap between PCB edge and inner wall
PCB_T = 1.6
HOLE_INSET = 3.5
PCB_HOLE_D = 2.7      # M2.5 clearance
STANDOFF_R = 2.5
PILOT_R = 1.1         # self-tapping pilot hole
RECEPT = (7.35, 8.94, 3.26)   # USB-C receptacle depth(x), width(y), height(z)
RECEPT_OVERHANG = 0.6
PLUG_SHELL = (8.25, 2.4)      # width(y), height(z)
OVERMOLD = (12.0, 6.5)        # width(y), height(z)
OPENING_CLEARANCE = 0.3       # designed gap around the plug shell
COMPONENT_HEADROOM = 12.0
LID_T = 2.0
LID_LIP_DEPTH = 3.0
LID_LIP_T = 1.5
LID_CLEARANCE = 0.25

CONSTRAINTS = {
    "clearance_mm": [0.15, 0.5],
    "min_wall_mm": 1.2,
    "volume_change_max_pct": 15,
    "outer_bbox_tolerance_mm": 1.0,
    "lid_insert_axis": [0, 0, -1],
    "plug_insert_axis": [1, 0, 0],
}


@dataclass
class Params:
    seed: int
    pcb_len: float      # along x
    pcb_wid: float      # along y
    standoff_h: float
    usb_y: float        # receptacle centre, y
    defect: str
    shift_y: float
    shift_z: float

    # derived geometry --------------------------------------------------
    @property
    def outer(self):
        x = self.pcb_len + 2 * (WALL + MARGIN)
        y = self.pcb_wid + 2 * (WALL + MARGIN)
        z = FLOOR + self.standoff_h + PCB_T + COMPONENT_HEADROOM
        return x, y, z

    @property
    def pcb_lo(self):
        return WALL + MARGIN, WALL + MARGIN, FLOOR + self.standoff_h

    @property
    def holes_xy(self):
        x0, y0, _ = self.pcb_lo
        xs = (x0 + HOLE_INSET, x0 + self.pcb_len - HOLE_INSET)
        ys = (y0 + HOLE_INSET, y0 + self.pcb_wid - HOLE_INSET)
        return [(x, y) for x in xs for y in ys]

    @property
    def usb_center_z(self):
        return self.pcb_lo[2] + PCB_T + RECEPT[2] / 2

    def opening(self, dy=0.0, dz=0.0):
        """Opening box through the front wall, centred on the plug shell (+ optional shift)."""
        hw = PLUG_SHELL[0] / 2 + OPENING_CLEARANCE
        hh = PLUG_SHELL[1] / 2 + OPENING_CLEARANCE
        cy, cz = self.usb_y + dy, self.usb_center_z + dz
        return [-0.5, cy - hw, cz - hh], [WALL + 0.5, cy + hw, cz + hh]


def sample_params(seed: int) -> Params:
    rng = np.random.default_rng(seed)
    pcb_len = round(float(rng.uniform(50, 70)) * 2) / 2
    pcb_wid = round(float(rng.uniform(32, 45)) * 2) / 2
    standoff_h = round(float(rng.uniform(3, 6)) * 2) / 2
    y0 = WALL + MARGIN
    usb_y = round(float(rng.uniform(y0 + 9, y0 + pcb_wid - 9)), 2)
    # D1: shift the opening by 1.0-2.5 mm in y and/or 0.8-1.5 mm in z
    mode = rng.choice(["y", "z", "yz"])
    sy = float(rng.uniform(1.0, 2.5)) * rng.choice([-1, 1]) if "y" in mode else 0.0
    sz = float(rng.uniform(0.8, 1.5)) * rng.choice([-1, 1]) if "z" in mode else 0.0
    return Params(seed, pcb_len, pcb_wid, standoff_h, usb_y, "D1_opening_shift", round(sy, 2), round(sz, 2))


# ---------------------------------------------------------------- parts
def build_enclosure(p: Params, opening_shift=(0.0, 0.0)):
    X, Y, Z = p.outer
    body = g.box([0, 0, 0], [X, Y, Z]) - g.box([WALL, WALL, FLOOR], [X - WALL, Y - WALL, Z + 1])
    for (hx, hy) in p.holes_xy:
        body = body + g.cylinder("z", (hx, hy), STANDOFF_R, FLOOR - 0.01, p.pcb_lo[2])
    for (hx, hy) in p.holes_xy:
        body = body - g.cylinder("z", (hx, hy), PILOT_R, FLOOR + 0.2, p.pcb_lo[2] + 1)
    lo, hi = p.opening(*opening_shift)
    return body - g.box(lo, hi)


def build_pcb(p: Params):
    x0, y0, z0 = p.pcb_lo
    board = g.box([x0, y0, z0], [x0 + p.pcb_len, y0 + p.pcb_wid, z0 + PCB_T])
    for (hx, hy) in p.holes_xy:
        board = board - g.cylinder("z", (hx, hy), PCB_HOLE_D / 2, z0 - 1, z0 + PCB_T + 1)
    rx0 = x0 - RECEPT_OVERHANG
    recept = g.box([rx0, p.usb_y - RECEPT[1] / 2, z0 + PCB_T],
                   [rx0 + RECEPT[0], p.usb_y + RECEPT[1] / 2, z0 + PCB_T + RECEPT[2]])
    return board + recept


def build_plug(p: Params):
    x_face = p.pcb_lo[0] - RECEPT_OVERHANG          # receptacle front face
    cz = p.usb_center_z
    shell = g.box([-9.0, p.usb_y - PLUG_SHELL[0] / 2, cz - PLUG_SHELL[1] / 2],
                  [x_face, p.usb_y + PLUG_SHELL[0] / 2, cz + PLUG_SHELL[1] / 2])
    mold = g.box([-24.0, p.usb_y - OVERMOLD[0] / 2, cz - OVERMOLD[1] / 2],
                 [-1.0, p.usb_y + OVERMOLD[0] / 2, cz + OVERMOLD[1] / 2])
    return shell + mold


def build_lid(p: Params):
    X, Y, Z = p.outer
    plate = g.box([0, 0, Z], [X, Y, Z + LID_T])
    o = WALL + LID_CLEARANCE
    outer = g.box([o, o, Z - LID_LIP_DEPTH], [X - o, Y - o, Z + 0.01])
    i = o + LID_LIP_T
    inner = g.box([i, i, Z - LID_LIP_DEPTH - 1], [X - i, Y - i, Z + 1])
    return plate + (outer - inner)


# ---------------------------------------------------------------- task export
def task_description(p: Params) -> dict:
    return {
        "task_id": f"enc-{p.seed:04d}",
        "units": "mm",
        "frame": "x points out of the front wall inward (front wall at x=0..2), y along the front wall, z up; floor at z=0",
        "editable_part": "enclosure",
        "fixed_parts": ["pcb", "usb_plug", "lid"],
        "parts": {
            "enclosure": "3D-printed open-top case with 4 screw standoffs and a USB-C opening in the front wall",
            "pcb": "circuit board resting on the standoffs, with a USB-C receptacle at its front edge",
            "usb_plug": "USB-C cable plug shown fully inserted into the receptacle (it passes through the front wall)",
            "lid": "top cover; its lip drops into the enclosure from above",
        },
        "goal": "Modify the enclosure so the assembly fits: the USB plug must pass through the front wall with the required clearance, "
                "and nothing else may collide. Keep the change minimal and the part printable.",
        "constraints": CONSTRAINTS,
        "functional_features": ["4 standoffs supporting the pcb, each with a pilot hole for a screw", "opening for the usb plug", "outer shape unchanged"],
        "test_fit_budget": 3,
    }


def make_task(seed: int, out_root: Path) -> Path:
    p = sample_params(seed)
    tdir = out_root / f"enc-{seed:04d}"
    (tdir / "parts").mkdir(parents=True, exist_ok=True)
    (tdir / "hidden").mkdir(parents=True, exist_ok=True)

    broken = build_enclosure(p, (p.shift_y, p.shift_z))
    correct = build_enclosure(p)
    g.save_stl(broken, tdir / "parts" / "enclosure.stl")
    g.save_stl(build_pcb(p), tdir / "parts" / "pcb.stl")
    g.save_stl(build_plug(p), tdir / "parts" / "usb_plug.stl")
    g.save_stl(build_lid(p), tdir / "parts" / "lid.stl")
    g.save_stl(correct, tdir / "hidden" / "enclosure_reference.stl")

    (tdir / "task.json").write_text(json.dumps(task_description(p), indent=2))
    # Facts the checks need. All are measurable from the public parts, so they may live next to them.
    spec = {
        "holes_xy": p.holes_xy,
        "pcb_bottom_z": p.pcb_lo[2],
        "standoff_r": STANDOFF_R,
        "pilot_r": PILOT_R,
        "floor": FLOOR,
        "wall": WALL,
        "plug_shell_yz": {"y": [p.usb_y - PLUG_SHELL[0] / 2, p.usb_y + PLUG_SHELL[0] / 2],
                          "z": [p.usb_center_z - PLUG_SHELL[1] / 2, p.usb_center_z + PLUG_SHELL[1] / 2]},
    }
    (tdir / "check_spec.json").write_text(json.dumps(spec, indent=2))
    # Secrets: copied into the container only at grading time.
    hidden = asdict(p) | spec | {
        "opening_correct": p.opening(),
        "opening_broken": p.opening(p.shift_y, p.shift_z),
        "reference_change_mm3": g.sym_diff_volume(broken, correct),
    }
    (tdir / "hidden" / "params.json").write_text(json.dumps(hidden, indent=2))
    return tdir


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--out", default="tasks")
    a = ap.parse_args()
    lo, hi = (int(v) for v in a.seeds.split("-"))
    for s in range(lo, hi + 1):
        print(make_task(s, Path(a.out)))
