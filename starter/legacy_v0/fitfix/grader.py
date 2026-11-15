"""Reward for a submitted enclosure. Runs OUTSIDE the agent container; reads hidden/.

R = gate * score
  gate  = 0 if the part is no longer a valid, functional enclosure (or it now collides with pcb/lid)
  score = 0.5 + 0.3*printability + 0.2*minimal_change      if the plug fits with clearance in band
        = 0.25 + 0.1*printability                            if the plug is free but the clearance is off-band
        = 0.2 * (fraction of the original plug collision removed)  otherwise
Doing nothing scores 0; only a real fix can reach the 0.5+ band.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import geom as g


def _ratio_filled(enc, region) -> float:
    v = float(region.volume())
    return float((enc ^ region).volume()) / v if v > 0 else 0.0


def check(enc, task_dir: Path, parts: dict | None = None, orig=None) -> dict:
    """Detailed checks shared by the grader and the agent's test_fit tool.

    Uses only check_spec.json (measurable facts). The minimal-change score needs hidden/ and is
    skipped when hidden/ is absent (inside the agent container).
    """
    task_dir = Path(task_dir)
    h = json.loads((task_dir / "check_spec.json").read_text())
    t = json.loads((task_dir / "task.json").read_text())
    c = t["constraints"]
    if parts is None:
        parts = {n: g.load_stl(task_dir / "parts" / f"{n}.stl") for n in ("pcb", "usb_plug", "lid")}
    if orig is None:
        orig = g.load_stl(task_dir / "parts" / "enclosure.stl")
    out: dict = {"gate": {}, "fit": {}, "print": {}, "change": {}}

    # ---------------------------------------------------------------- gate
    gate = out["gate"]
    vol, vol0 = float(enc.volume()), float(orig.volume())
    gate["volume_change_pct"] = round(100 * (vol - vol0) / vol0, 2)
    gate["volume_ok"] = abs(gate["volume_change_pct"]) <= c["volume_change_max_pct"]
    (lo, hi), (lo0, hi0) = g.bbox(enc), g.bbox(orig)
    dev = float(np.max(np.abs(np.r_[lo, hi] - np.r_[lo0, hi0])))
    gate["outer_bbox_deviation_mm"] = round(dev, 3)
    gate["outer_shape_ok"] = dev <= c["outer_bbox_tolerance_mm"]
    standoffs = []
    zb = h["pcb_bottom_z"]
    for (x, y) in h["holes_xy"]:
        ring = g.cylinder("z", (x, y), h["standoff_r"] - 0.1, h["floor"] + 0.3, zb - 0.05) - \
            g.cylinder("z", (x, y), h["pilot_r"] + 0.1, h["floor"], zb + 1)
        pilot = g.cylinder("z", (x, y), h["pilot_r"] - 0.15, h["floor"] + 0.5, zb - 0.05)
        top = g.cylinder("z", (x, y), h["standoff_r"] - 0.1, zb - 0.3, zb - 0.02) - \
            g.cylinder("z", (x, y), h["pilot_r"] + 0.1, zb - 1, zb + 1)
        ok = _ratio_filled(enc, ring) > 0.9 and _ratio_filled(enc, pilot) < 0.05 and _ratio_filled(enc, top) > 0.9
        standoffs.append(bool(ok))
    gate["standoffs_ok"] = standoffs
    for name in ("pcb", "lid"):
        v, _ = g.interference(enc, parts[name])
        gate[f"collision_{name}_mm3"] = round(v, 3)
    gate["passed"] = bool(gate["volume_ok"] and gate["outer_shape_ok"] and all(standoffs)
                          and gate["collision_pcb_mm3"] == 0 and gate["collision_lid_mm3"] == 0)

    # ---------------------------------------------------------------- fit (usb plug)
    fit = out["fit"]
    v_plug, bb = g.interference(enc, parts["usb_plug"])
    v_plug0, _ = g.interference(orig, parts["usb_plug"])
    fit["collision_usb_plug_mm3"] = round(v_plug, 3)
    fit["collision_usb_plug_region"] = bb
    band = c["clearance_mm"]
    # clearance on each side of the plug shell, measured in the wall section
    sy, sz = h["plug_shell_yz"]["y"], h["plug_shell_yz"]["z"]
    cy, cz = (sy[0] + sy[1]) / 2, (sz[0] + sz[1]) / 2
    sides = None
    for x_cut in (0.25 * h["wall"], 0.5 * h["wall"], 0.75 * h["wall"]):
        hole = None
        for l in g.section(enc, "x", x_cut):
            p = l["points"]
            if l["is_hole"] and p[:, 0].min() <= cy <= p[:, 0].max() and p[:, 1].min() <= cz <= p[:, 1].max():
                hole = l
        if hole is None:
            sides = None
            break
        p = hole["points"]
        s = {"-y": sy[0] - p[:, 0].min(), "+y": p[:, 0].max() - sy[1],
             "-z": sz[0] - p[:, 1].min(), "+z": p[:, 1].max() - sz[1]}
        sides = s if sides is None else {k: min(sides[k], s[k]) for k in s}
    fit["opening_clearance_mm"] = None if sides is None else {k: round(v, 3) for k, v in sides.items()}
    fit["clearance_in_band"] = bool(sides is not None and all(band[0] - 1e-3 <= v <= band[1] + 1e-3 for v in sides.values()))
    fit["plug_free"] = v_plug == 0
    fit["solved"] = bool(fit["plug_free"] and fit["clearance_in_band"])
    fit["progress"] = round(max(0.0, 1 - v_plug / v_plug0), 3) if v_plug0 > 0 else 1.0

    # ---------------------------------------------------------------- printability
    pr = out["print"]
    tmin, where, _ = g.wall_thickness(enc)
    pr["min_wall_mm"] = round(tmin, 3)
    pr["thinnest_at"] = where
    pr["score"] = round(float(np.clip(tmin / c["min_wall_mm"], 0, 1)) ** 2, 3)

    # ---------------------------------------------------------------- minimal change
    ch = out["change"]
    sd = g.sym_diff_volume(enc, orig)
    ch["changed_volume_mm3"] = round(sd, 2)
    hidden = task_dir / "hidden" / "params.json"
    if hidden.exists():
        ref = json.loads(hidden.read_text())["reference_change_mm3"]
        excess = max(0.0, sd - 1.5 * ref)
        ch["score"] = round(float(np.clip(1 - excess / (4 * ref), 0, 1)), 3)
    else:
        ch["score"] = None
    return out


def reward(report: dict) -> float:
    if not report["gate"]["passed"]:
        return 0.0
    f, p, ch = report["fit"], report["print"]["score"], report["change"]["score"]
    if f["solved"]:
        return round(0.5 + 0.3 * p + 0.2 * ch, 4)
    if f["plug_free"]:
        return round(0.25 + 0.1 * p, 4)
    return round(0.2 * f["progress"], 4)


def grade(enclosure_stl: Path, task_dir: Path) -> dict:
    try:
        enc = g.load_stl(enclosure_stl)
    except Exception as e:  # invalid / non-manifold / missing file
        return {"reward": 0.0, "error": f"invalid enclosure: {e}"}
    rep = check(enc, task_dir)
    return {"reward": reward(rep), "report": rep}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("task_dir")
    ap.add_argument("enclosure_stl")
    ap.add_argument("--out")
    a = ap.parse_args()
    res = grade(Path(a.enclosure_stl), Path(a.task_dir))
    s = json.dumps(res, indent=2)
    if a.out:
        Path(a.out).write_text(s)
    print(s)
