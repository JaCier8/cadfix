"""Dev script: what an agent would know about one hinge_lid level/seed after inspecting it with its tools.

Prints the bug report and the spec (from docs/scenario.json, agent-facing wording), the S3 rule of the level,
the geometry the tools would report (faces, edges, hinge axis, the lid section at each lid knuckle, zones) and
the original opening sweep, measured on the STEP parts. L1/L2 are axis-aligned and described in x/y/z terms;
L3 is described in world coordinates only (faces as point + normal, edges as endpoints, zones as oriented
boxes), as tools would report them: no pose, no hidden frame.

Deliberately NOT printed: anything from the feasibility scan (reference volumes, scanned sizes, valid ranges),
the analytic swept radius / collision zone, the S3 volumes, and scenario.json text that names the cause, the
fix or the traps.

Run: python -m scenarios.hinge_lid.brief --level L3 --seed 0 [--out output/hinge_lid]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


from cadfix.core import kernel
from scenarios.hinge_lid import devgrade, generator

SCENARIO_JSON = Path(__file__).resolve().parents[2] / "docs" / "scenario.json"


def _f(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _pt(*v) -> str:
    return "(" + ", ".join(_f(float(x)) for x in v) + ")"


def _dir(v) -> str:
    return "(" + ", ".join(f"{float(x):.4f}" for x in v) + ")"


def measure_original(g: devgrade.Grader) -> dict:
    joint, meshes = g.joint, g.meshes
    fc = kernel.first_contact_sweep({n: meshes[n] for n in joint["moving"]}, {n: meshes[n] for n in joint["fixed"]},
                                    joint["axis_point"], joint["axis_direction"], 0.0, 180.0, 1.0, 0.1)
    pieces = []
    if fc:
        for c in fc["contacts"]:
            m = kernel.rotate(meshes[c["moving"]], joint["axis_point"], joint["axis_direction"], fc["angle"])
            pieces += [dict(pc, pair=(c["moving"], c["fixed"]))
                       for pc in kernel.intersection_components(m, meshes[c["fixed"]], min_volume=1e-6)]
    return {"first_contact": fc, "pieces": pieces, "s1": g.orig_s1}


def s3_rule(level: str) -> str:
    full, zero = generator.S3_FACTORS[level]
    return (f"full points if the changed volume is within {_f(full)}x of the best known fix for this task, "
            f"zero at {_f(zero)}x (linear in between)")


def _spec_lines(sc: dict, level: str) -> list[str]:
    out = ["SPEC"]
    for k, v in sc["spec"]["gate"].items():
        out.append(f"  gate {k}: {v}")
    out.append(f"  S1_opening: {sc['spec']['score']['S1_opening']}")
    out.append(f"  S2_printability: {sc['spec']['score']['S2_printability']}")
    out.append("  S3_minimal_change: changed volume (added + removed) vs the original parts;")
    out.append(f"    {s3_rule(level)}")
    r = sc["spec"]["reward"]
    out.append(f"  reward: gate failed -> {r['gate_failed']}; S1 not met -> {r['S1_not_met']};")
    out.append(f"          S1 met -> {r['S1_met']}\n")
    return out


def _measured_lines(meas: dict) -> list[str]:
    out = ["ORIGINAL, MEASURED (opening sweep on the given parts)"]
    fc = meas["first_contact"]
    if fc is None:
        out.append("  no contact while opening 0..180 deg")
    else:
        out.append(f"  first contact at {fc['angle']} deg (1 deg steps, refined to 0.1 deg), total overlap "
                   f"{fc['volume']:.4f} mm3, pairs {sorted({(c['moving'], c['fixed']) for c in fc['contacts']})}")
        out.append(f"  overlap bbox {_pt(*fc['bbox'][0])} .. {_pt(*fc['bbox'][1])}, pieces:")
        for pc in meas["pieces"]:
            out.append(f"    {pc['pair'][0]} x {pc['pair'][1]}: {pc['volume']:.5f} mm3  "
                       f"{_pt(*pc['bbox'][0])} .. {_pt(*pc['bbox'][1])}")
    s1 = meas["s1"]
    ff = s1["first_fail"]
    out.append(f"  S1: {'met' if s1['met'] else 'NOT met'}; holds up to {s1['ok_until']} deg (the 'original angle' "
               f"in the reward); first failing step {ff['angle']} deg: clearance {ff['gap']:.3f} mm, overlap "
               f"{ff['overlap']:.4f} mm3" if ff else f"  S1: met, min clearance {s1['min_clearance']:.3f}")
    return out


def _header(sc: dict, level: str, seed: int, shapes: dict) -> list[str]:
    vol = {n: shapes[n].Volume() for n in shapes}
    out = [f"=== hinge_lid {level}, seed {seed}: what the agent knows after inspecting the task ===\n", "BUG REPORT",
           "  " + sc["spec"]["disclosure"]["agent_gets"][0].split(": ", 1)[1].capitalize() + ".",
           "  Fix it by editing the editable parts. The hinge interface is frozen.\n", "PARTS"]
    for n, d in sc["parts"].items():
        out.append(f"  {n:<11} {'editable' if d['editable'] else 'fixed   '}  volume {vol[n]:9.3f} mm3  {d['role']}")
    out.append("  Print orientation: enclosure on its floor; lid top face down.\n")
    return out


def brief_axis_aligned(info: dict, shapes: dict, sc: dict, level: str, seed: int, meas: dict) -> list[str]:
    p, joint = info["params"], info["joint"]
    L, W, H, t = p["L"], p["W"], p["H"], p["t"]
    ax, ay, az = joint["axis_point"]
    a, b = round(p["W"] + p["a"], 3) - W, round(p["H"] + p["b"], 3) - H
    out = _header(sc, level, seed, shapes)
    w = out.append
    w("COORDINATE FRAME (units mm, degrees)")
    w(f"  x along the hinge (0..{_f(L)}), y from the front wall (y=0) to the rear wall (y={_f(W)}), z up "
      f"(floor z=0, wall tops z={_f(H)}).")
    w(f"  Closed lid: plate z={_f(H)}..{_f(H + p['t_lid'])} over the whole box.\n")

    w("REAR WALL (section x = const)")
    w(f"  outer face y = {_f(W)}, inner face y = {_f(round(W - t, 3))}, thickness {_f(t)}; wall top z = {_f(H)}")
    w(f"  outer top edge: the straight edge along x at (y={_f(W)}, z={_f(H)}), x 0..{_f(L)}")
    w(f"  seal band: closed, the lid underside (z={_f(H)}) rests on the wall tops; on the rear wall the contact "
      f"is y {_f(round(W - t, 3))}..{_f(W)} (width {_f(t)});")
    w(f"  it must stay >= {sc['protections']['seal_band']['min_contact_width_mm']} mm wide all around.")
    enc_x = ", ".join(f"{s['x'][0]}..{s['x'][1]}" for s in info["segments"] if s["part"] == "enclosure")
    w(f"  enclosure knuckles: x {enc_x}, hung off the rear wall's outer face below "
      f"z = {_f(round(H - p['free_band'], 3))}\n")

    w("HINGE")
    w(f"  axis through {_pt(ax, ay, az)}, direction {_pt(*joint['axis_direction'])}; the lid opens by positive "
      f"rotation about it (right-hand rule), 0..{_f(joint['range_deg'][1])} deg")
    w(f"  axis vs the rear wall's outer top edge: {_f(a)} behind the outer face, {_f(b)} above the wall top, "
      f"distance {math.hypot(a, b):.3f}")
    w(f"  hinge_pin radius {_f(p['r_pin'])}, knuckle bores radius {_f(p['r_bore'])} (frozen), knuckle outer "
      f"radius {_f(p['r_k'])}, axial gaps {_f(p['axial_gap'])}\n")

    w("LID SECTION NEAR THE HINGE (in each lid knuckle segment)")
    lid_x = [s["x"] for s in info["segments"] if s["part"] == "lid"]
    w(f"  lid knuckle segments: x {', '.join(f'{xs}..{xe}' for xs, xe in lid_x)}")
    w(f"  knuckle: cylinder radius {_f(p['r_k'])} about the axis; plate continues behind the wall to "
      f"y = {_f(round(ay + p['r_k'], 3))} at z {_f(H)}..{_f(H + p['t_lid'])}")
    w("  rib under the knuckle (box over the whole segment length, the same in every segment), corners in the "
      "(y, z) section:")
    q0, q1, d = p["lug_q0"], p["lug_q1"], p["lug_p"]
    for label, (dy, dz) in (("top front", (q0, 0.0)), ("top rear", (q1, 0.0)),
                            ("bottom rear", (q1, -d)), ("bottom front", (q0, -d))):
        w(f"    {label:<12} y={ay + dy:8.3f} z={az + dz:8.3f}   rel. to axis dy={dy:+.3f} dz={dz:+.3f}   "
          f"distance {math.hypot(dy, dz):.3f}")
    w("")

    w("ZONES")
    w("  keep-in (filled >= 99 %): lid knuckles, knuckle ribs, lid module frame, seal band, enclosure knuckle brackets:")
    for z in info["keep_in"]:
        w(f"    {z['name']:<20} {z['part']}: {_pt(*z['box'][0])} .. {_pt(*z['box'][1])}")
    lo, hi = info["module_box"]
    w(f"  keep-out (must stay empty): lid_module volume {_pt(*lo)} .. {_pt(*hi)} (moves with the lid)\n")
    return out + _spec_lines(sc, level) + _measured_lines(meas)


def brief_world(info: dict, shapes: dict, sc: dict, level: str, seed: int, meas: dict) -> list[str]:
    """Everything as world points / unit vectors; the geometry is built in the hidden frame and placed here."""
    p = generator.params_from_info(info)
    m = p.pose_matrix()
    P = lambda *v: kernel.apply_points(m, v)[0]   # noqa: E731
    D = lambda *v: kernel.apply_dirs(m, v)[0]     # noqa: E731
    L, W, H, t = p.L, p.W, p.H, p.t
    joint = info["joint"]
    n_up, n_out, n_hinge = D(0, 0, 1), D(0, 1, 0), D(1, 0, 0)
    out = _header(sc, level, seed, shapes)
    w = out.append
    w("COORDINATES (units mm, degrees): world frame as reported by the tools. The assembly is not aligned with "
      "the world axes.")
    w(f"  box (outer): {_f(L)} along the hinge, {_f(W)} front to back, {_f(H)} floor to wall top; walls {_f(t)} "
      f"thick, floor {_f(p.floor)}.")
    w(f"  floor underside: plane through {_pt(*P(0, 0, 0))}, outward normal {_dir(-n_up)}")
    w(f"  wall tops: plane through {_pt(*P(0, 0, H))}, normal {_dir(n_up)}; closed, the lid plate "
      f"({_f(p.t_lid)} thick) lies on them.\n")

    w("REAR WALL")
    w(f"  outer face: plane through {_pt(*P(0, W, 0))}, outward normal {_dir(n_out)}")
    w(f"  inner face: plane through {_pt(*P(0, W - t, 0))}, normal {_dir(-n_out)} (into the box)")
    w(f"  outer top edge: straight edge {_pt(*P(0, W, H))} -> {_pt(*P(L, W, H))}, length {_f(L)}")
    w(f"  inner top edge: straight edge {_pt(*P(0, W - t, H))} -> {_pt(*P(L, W - t, H))}")
    w(f"  seal band: closed, the lid underside rests on the wall tops; on the rear wall the contact is the whole "
      f"wall top between these two edges (width {_f(t)});")
    w(f"  it must stay >= {sc['protections']['seal_band']['min_contact_width_mm']} mm wide all around.")
    w(f"  enclosure knuckles hang off the rear wall's outer face starting {_f(p.free_band)} below the wall top; "
      f"along the hinge they span:")
    for o, xs, xe in p.segments():
        if o == "enclosure":
            w(f"    {_pt(*P(xs, p.ya, p.za))} -> {_pt(*P(xe, p.ya, p.za))} (on the axis)")
    w("")

    w("HINGE")
    w(f"  axis through {_pt(*joint['axis_point'])}, direction {_dir(joint['axis_direction'])}; the lid opens by "
      f"positive rotation about it (right-hand rule), 0..{_f(joint['range_deg'][1])} deg")
    w(f"  axis vs the rear wall's outer top edge: {_f(p.a)} behind the outer face, {_f(p.b)} above the wall top "
      f"plane, distance {math.hypot(p.a, p.b):.3f}")
    w(f"  hinge_pin radius {_f(p.r_pin)}, knuckle bores radius {_f(p.r_bore)} (frozen), knuckle outer "
      f"radius {_f(p.r_k)}, axial gaps {_f(p.axial_gap)}\n")

    w("LID NEAR THE HINGE (each lid knuckle segment: knuckle cylinder, plate continued behind the wall, a rib "
      "(box) under the knuckle over the whole segment length)")
    for i, ((xs, xe), (q0, q1, d)) in enumerate(zip(p.lid_segments(), p.rib_profiles())):
        w(f"  segment {i}: on the axis {_pt(*P(xs, p.ya, p.za))} -> {_pt(*P(xe, p.ya, p.za))} "
          f"(length {_f(round(xe - xs, 3))})")
        w("    rib corners at the segment's first end (the same section at the other end, shifted along the "
          "axis):")
        for label, (dy, dz) in (("top front", (q0, 0.0)), ("top rear", (q1, 0.0)),
                                ("bottom rear", (q1, -d)), ("bottom front", (q0, -d))):
            w(f"      {label:<12} {_pt(*P(xs, p.ya + dy, p.za + dz))}   distance from the axis "
              f"{math.hypot(dy, dz):.3f}")
    w(f"  knuckle: cylinder radius {_f(p.r_k)} about the axis; plate continues behind the wall up to "
      f"{_f(p.a + p.r_k)} past the rear wall's outer face\n")

    w("ZONES (oriented boxes: corner + three edge vectors, world)")
    w("  keep-in (filled >= 99 %): lid knuckles, knuckle ribs, lid module frame, seal band, enclosure knuckle brackets:")
    for z in info["keep_in"]:
        e = z["world"]["edges"]
        w(f"    {z['name']:<20} {z['part']}: corner {_pt(*z['world']['origin'])}, edges {_pt(*e[0])} "
          f"{_pt(*e[1])} {_pt(*e[2])}")
    mb = info["module_box_world"]
    w(f"  keep-out (must stay empty): lid_module volume, corner {_pt(*mb['origin'])}, edges "
      + " ".join(_pt(*e) for e in mb["edges"]) + " (moves with the lid)\n")
    return out + _spec_lines(sc, level) + _measured_lines(meas)


def brief(seed: int, out_dir, level: str = "L1") -> str:
    sc = json.loads(SCENARIO_JSON.read_text())
    info, shapes = devgrade.load(level, seed, out_dir)
    meas = measure_original(devgrade.Grader(info, shapes))
    build = brief_world if info.get("pose") else brief_axis_aligned
    return "\n".join(build(info, shapes, sc, level, seed, meas))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--level", default="L1", choices=generator.LEVELS)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", default="output/hinge_lid")
    args = ap.parse_args(argv)
    print(brief(args.seed, args.out, args.level))


if __name__ == "__main__":
    main()
