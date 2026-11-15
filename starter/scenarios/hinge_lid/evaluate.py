"""Dev script: apply a list of edit operations (real B-rep) and print what test_fit would show.

Operations are a JSON list (a file path or the JSON text itself), applied in order to a copy of the parts:
  [{"op": "chamfer", "edge_near": [x, y, z], "d1": 0.9, "d2": 2.1},
   {"op": "extrude_cut", "origin": [x, y, z], "normal": [1, 0, 0], "x_dir": [0, 1, 0],
    "polygon_2d": [[-0.9, 0], [0.01, 0.01], [0, -2.1]], "depth_from": 0, "depth_to": 9.0}]
"part" defaults to "enclosure". chamfer: d1 is measured on the adjacent face whose outward normal is closest to
"d1_face_normal" (default: the face pointing most upwards), d2 (default d1) on the other one. extrude_cut: the
polygon is sketched on the plane through origin with that normal (u along x_dir, v along normal x x_dir) and
the prism between depth_from and depth_to along the normal is removed.

--top/--side is a shortcut for one full-edge chamfer of the rear wall's outer top edge (d1 = top on the wall top).
--hide-score prints what we paste to models: no reward line, minimal change only as removed volume and %.
Checks are the real spec (devgrade.py -> cadfix/checks), the same code as the grader and the agent's tools.

Run: python -m scenarios.hinge_lid.evaluate --level L2 --seed 0 --ops docs/examples/L2_seed0_reference.json
     python -m scenarios.hinge_lid.evaluate --level L1 --seed 0 --top 0.9 --side 2.15 [--hide-score]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scenarios.hinge_lid import devgrade, generator


def _f3(v) -> str:
    return "[" + ", ".join(f"{x:.3f}" for x in v) + "]"


def describe_op(op) -> str:
    try:
        part = op.get("part", "enclosure")
        if op.get("op") == "chamfer":
            d2 = op.get("d2", op.get("d1"))
            return f"chamfer {part}: edge near {_f3(op['edge_near'])}, d1 {op['d1']}, d2 {d2}"
        if op.get("op") == "extrude_cut":
            return (f"extrude_cut {part}: origin {_f3(op['origin'])}, normal {_f3(op['normal'])}, x_dir "
                    f"{_f3(op['x_dir'])}, {len(op['polygon_2d'])}-gon, depth {op['depth_from']}..{op['depth_to']}")
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    return json.dumps(op)


def report(level: str, seed: int, ops, out_dir, hide_score: bool = False) -> str:
    info, shapes = devgrade.load(level, seed, out_dir)
    g = devgrade.Grader(info, shapes)
    out = [f"=== test_fit, {level} seed {seed}: {len(ops)} operation(s) ==="]
    w = out.append
    for i, op in enumerate(ops):
        w(f"  [{i}] {describe_op(op)}")
    try:
        v = g.grade(ops)
    except devgrade.OpError as e:
        w(f"ERROR             {e}")
        w("                  nothing was changed")
        return "\n".join(out)
    s1, spec = v["s1"], info["spec"]
    for e in v["log"]:
        w(f"  [{e['index']}] {e['op']} on {e['part']}: removed {e['removed_mm3']:.3f} mm3")
    ff = s1["first_fail"]
    w(f"S1 opening        {'PASS' if s1['met'] else 'FAIL'}  holds up to {s1['ok_until']} deg "
      f"(original: {v['orig_s1_until']} deg)")
    if ff:
        w(f"                  first failing step {ff['angle']} deg: clearance {ff['gap']:.3f} mm "
          f"(need >= {spec['S1']['clearance_mm']} from {spec['S1']['clearance_from_deg']} deg), "
          f"overlap {ff['overlap']:.4f} mm3, pair {ff['pair']}")
    w(f"                  min clearance 10..110 deg: {s1['min_clearance']:.3f} mm at {s1['min_clearance_at']} deg"
      f"{'  (capped at the search radius)' if s1['min_clearance'] >= spec['S1']['search_mm'] else ''}")
    w(f"seal              width {v['seal_width']:.3f} mm, margin {v['seal_margin']:+.3f} mm over "
      f"{generator.SEAL_MIN_WIDTH} -> gate {'ok' if v['gates']['G5_seal'] else 'FAIL'}")
    w(f"S2 printability   {v['checks']['S2_min_wall']['details'][0]}; {v['checks']['S2_overhang']['details'][0]} "
      f"-> {v['printability']:.0f}")
    vol = info["spec"]["S3"]["enclosure_volume_mm3"]
    s3_line = (f"S3 minimal change removed {v['removed_mm3']:.3f} mm3, added {v['added_mm3']:.3f} mm3 = "
               f"{v['changed_pct']:.4f} % of the enclosure ({vol:.3f} mm3)")
    w(s3_line if hide_score else s3_line + f" -> {v['s3']:.3f}")
    w("gates             " + ", ".join(f"{k} {'ok' if ok else 'FAIL'}" for k, ok in v["gates"].items()))
    for k, ok in v["gates"].items():
        if not ok:
            for line in v["checks"][k]["details"][:3]:
                w(f"                  {k}: {line}")
    if not hide_score:
        pw = generator.REWARD_POLICY.progress_weight
        w(f"REWARD            {v['reward']:.3f}"
          + ("" if s1["met"] or not all(v["gates"].values()) else f"  (S1 not met: {pw} x progress {v['progress']:.3f})"))
    return "\n".join(out)


def load_ops(text: str) -> list:
    path = Path(text)
    raw = path.read_text() if not text.lstrip().startswith("[") and path.exists() else text
    try:
        ops = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"--ops is neither a JSON list nor a readable JSON file: {e}") from None
    if not isinstance(ops, list):
        raise SystemExit("--ops must be a JSON list of operations")
    return ops


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--level", default="L1", choices=generator.LEVELS)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--ops", help="JSON list of operations, or a path to a JSON file")
    ap.add_argument("--top", type=float, help="shortcut: full-edge chamfer, leg along the wall top (mm)")
    ap.add_argument("--side", type=float, help="shortcut: leg down the outer face (mm)")
    ap.add_argument("--symmetric", action="store_true", help="shortcut: 45 deg chamfer, side = top")
    ap.add_argument("--hide-score", action="store_true", help="no reward line; S3 as removed volume and %% only")
    ap.add_argument("--out", default="output/hinge_lid")
    args = ap.parse_args(argv)
    if (args.ops is None) == (args.top is None):
        ap.error("give either --ops or --top (with --side or --symmetric)")
    if args.ops is not None:
        ops = load_ops(args.ops)
    else:
        side = args.top if args.symmetric else args.side
        if side is None:
            ap.error("--side is required unless --symmetric")
        info, _ = devgrade.load(args.level, args.seed, args.out)
        ops = [devgrade.chamfer_op(info, args.top, side)]
    print(report(args.level, args.seed, ops, args.out, args.hide_score))


if __name__ == "__main__":
    main()
