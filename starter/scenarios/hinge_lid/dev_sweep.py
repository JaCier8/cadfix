"""Dev script: acceptance tables per level (3D, real B-rep operations).

For each level and seed: load the STEP parts (generated first if missing), then
- original: first contact while opening (kernel.first_contact_sweep, 0..180 deg, 1 deg + 0.1 refine), which
  pair touches and whether every overlap piece sits at the rear wall's outer top edge inside one lid segment;
- seven enclosure variants built as operation lists (cadfix.ops.edit) and graded by devgrade:
    original      no change
    reference     per-rib reliefs from the generator scan (V_ref)
    full_edge     best full-edge chamfer valid for every rib (task 2b behaviour)
    identical     one relief per rib, all sized for the worst rib (same profile as full_edge)
    exact_length  reference reliefs but exactly as long as each rib (no x extension)
    side_0.7x     reference reliefs with 0.7 x side
    symmetric     smallest symmetric 45 deg full-edge chamfer passing S1 in the 2D model
  columns: S1, angle up to which S1 holds, min clearance 10..110, seal margin, min wall, removed volume %,
  volume / V_ref, S3, reward; per variant also pin / module / bracket overlaps over the sweep (all must be 0).

Run: python -m scenarios.hinge_lid.dev_sweep --level L1,L2,L3 --seeds 0-9 --out output/hinge_lid [-v] [--glb]
"""
from __future__ import annotations

import argparse
import time

import numpy as np

from cadfix.core import kernel
from scenarios.hinge_lid import devgrade, generator

ZONE_TOL = 0.02          # mm, slack around the analytic collision zone
VARIANTS = ("original", "reference", "full_edge", "identical", "exact_length", "side_0.7x", "symmetric")


def load(seed: int, out_dir, level: str = "L1"):
    return devgrade.load(level, seed, out_dir)


def variant_ops(info: dict) -> dict:
    """Operation list per variant (None: the variant does not exist for this seed)."""
    p = generator.params_from_info(info)
    f = info["feasibility"]
    ref = generator.reference_sizes(f)
    full, sym = f["scan"]["best"], f["scan"]["symmetric_45"]
    ident = (f["identical_relief"]["d_top"], f["identical_relief"]["d_side"])
    return {
        "original": [],
        "reference": info["reference_ops"],
        "full_edge": [devgrade.chamfer_op(info, full["d_top"], full["d_side"])],
        "identical": generator.relief_ops(p, [ident] * len(ref)),
        "exact_length": generator.relief_ops(p, ref, extension=0.0),
        "side_0.7x": generator.relief_ops(p, [(t, round(0.7 * s, 2)) for t, s in ref]),
        "symmetric": [devgrade.chamfer_op(info, sym["d"], sym["d"])] if sym else None,
    }


# ---------------------------------------------------------------- original: first contact
def in_collision_zone(bb, info: dict) -> bool:
    """Is a contact bbox (local frame) inside the analytic zone at the rear wall's outer top edge, within one
    lid segment?"""
    p, f = info["params"], info["feasibility"]
    z = f["collision_zone"]
    (x0, y0, z0), (x1, y1, z1) = bb
    W, H = p["W"], p["H"]
    in_yz = (y0 >= W - z["top_width"] - ZONE_TOL and y1 <= W + ZONE_TOL
             and z0 >= H - z["side_depth"] - ZONE_TOL and z1 <= H + ZONE_TOL)
    lid_x = [s["x"] for s in info["segments"] if s["part"] == "lid"]
    return in_yz and any(x0 >= xs - ZONE_TOL and x1 <= xe + ZONE_TOL for xs, xe in lid_x)


def first_contact(g: devgrade.Grader) -> dict:
    joint, meshes = g.joint, g.meshes
    t0 = time.perf_counter()
    fc = kernel.first_contact_sweep({n: meshes[n] for n in joint["moving"]}, {n: meshes[n] for n in joint["fixed"]},
                                    joint["axis_point"], joint["axis_direction"], 0.0, 180.0, 1.0, 0.1)
    seconds = time.perf_counter() - t0
    pieces = []
    if fc:  # disjoint overlap pieces at the first contact angle, in the local frame
        for c in fc["contacts"]:
            m = kernel.rotate(meshes[c["moving"]], joint["axis_point"], joint["axis_direction"], fc["angle"])
            pieces += kernel.intersection_components(kernel.transform_mesh(m, g.to_local),
                                                     kernel.transform_mesh(meshes[c["fixed"]], g.to_local),
                                                     min_volume=1e-6)
    return {"first_contact": fc, "first_contact_s": seconds,
            "first_pairs": sorted({(c["moving"], c["fixed"]) for c in fc["contacts"]}) if fc else [],
            "first_pieces": pieces,
            "first_in_zone": bool(pieces) and all(in_collision_zone(pc["bbox"], g.info) for pc in pieces),
            "pin_x_enclosure": kernel.intersection(meshes["hinge_pin"], meshes["enclosure"])[0]}


# ---------------------------------------------------------------- per seed
def run_seed(level: str, seed: int, out_dir, side_collisions: bool = True, verbose: bool = False,
             glb: bool = False, variants=VARIANTS) -> dict:
    info, shapes = devgrade.load(level, seed, out_dir)
    g = devgrade.Grader(info, shapes)
    out = {"level": level, "seed": seed, "source_seed": info["source_seed"], "rejected": info["rejected_source_seeds"],
           "predicted_deg": info["feasibility"]["predicted_first_collision_deg"], "info": info,
           "orig_s1_until": g.orig_s1["ok_until"], **first_contact(g)}
    rows = {}
    for name, ops in variant_ops(info).items():
        if name not in variants:
            continue
        if ops is None:
            rows[name] = None
            continue
        try:
            rows[name] = g.grade(ops, side_collisions=side_collisions) | {"error": None}
        except devgrade.OpError as e:
            rows[name] = {"ops": ops, "error": str(e)}
    out["variants"] = rows
    if verbose:
        _print_detail(out)
    if glb:
        _export_glb(generator.seed_dir(out_dir, level, seed), g.meshes, g.joint,
                    out["first_contact"]["angle"] if out["first_contact"] else None)
    return out


def _print_detail(r: dict):
    fc = r["first_contact"]
    print(f"\n--- {r['level']} seed {r['seed']}  first contact {fc['angle'] if fc else None} deg")
    for pc in r["first_pieces"]:
        print(f"    piece vol={pc['volume']:.5f} mm3 local bbox={pc['bbox']}")
    for name, v in r["variants"].items():
        if v is None or v["error"]:
            print(f"  {name:<12} {v['error'] if v else 'n/a'}")
            continue
        ff = v["s1"]["first_fail"]
        print(f"  {name:<12} S1 until {v['s1']['ok_until']}  first fail "
              f"{(ff['angle'], round(ff['gap'], 4), round(ff['overlap'], 4), ff['pair']) if ff else None}  "
              f"bracket fill {v['bracket_fill']:.4f}  thin {v['thinnest_new_wall']}  new overhang {v['new_overhang_mm2']:.4f} mm2  "
              f"side collisions {v.get('side_collisions')}")


def _export_glb(d, meshes: dict, joint: dict, first_deg):
    import trimesh

    def tm(m, rgba):
        mesh = m.to_mesh()
        t = trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=False)
        t.visual.face_colors = rgba
        return t

    colors = {"enclosure": (180, 180, 190, 255), "lid": (90, 140, 220, 160),
              "hinge_pin": (60, 60, 60, 255), "lid_module": (60, 170, 90, 255)}
    for label, ang in (("closed", 0.0), ("first_hit", first_deg), ("open110", joint["range_deg"][1])):
        if ang is None:
            continue
        scene = trimesh.Scene()
        moved = {n: (kernel.rotate(m, joint["axis_point"], joint["axis_direction"], ang)
                     if n in joint["moving"] else m) for n, m in meshes.items()}
        for n, m in moved.items():
            scene.add_geometry(tm(m, colors[n]), node_name=n)
        for mv in joint["moving"]:
            col = moved[mv] ^ moved["enclosure"]
            if col.volume() > kernel.VOL_EPS:
                scene.add_geometry(tm(col, (230, 30, 30, 255)), node_name=f"collision_{mv}")
        path = d / f"view_{label}.glb"
        scene.export(str(path))
        print(f"  wrote {path}")


# ---------------------------------------------------------------- tables
def _sizes(ops) -> str:
    if not ops:
        return "-"
    if ops[0]["op"] == "chamfer":
        return f"{ops[0]['d1']:.2f}x{ops[0]['d2']:.2f} edge"
    tops = [(-o["polygon_2d"][0][0], -o["polygon_2d"][-1][1]) for o in ops]
    if len(set(tops)) == 1:
        return f"{tops[0][0]:.2f}x{tops[0][1]:.2f} x{len(tops)}"
    return " ".join(f"{t:.2f}x{s:.2f}" for t, s in tops)


def print_level(level: str, rows: list[dict]):
    full, zero = generator.S3_FACTORS[level]
    print(f"\n===== {level}: S3 full <= {full}x V_ref, zero at {zero}x =====")
    print("Per seed: original, reference volumes" + (", per-rib reliefs, world pose" if level == "L3" else ""))
    hdr = (f"{'seed':>4} {'src':>5} {'1st':>5} {'zone':>4} {'ribs':>4} {'V_ref':>7} {'V_full':>7} {'V_ident':>7} "
           f"{'full/ref':>8} {'id/ref':>6} {'sweep_s':>7}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        f = r["info"]["feasibility"]
        fc = r["first_contact"]
        sweep = r["variants"]["reference"]["s1"]["seconds"] if r["variants"].get("reference") else float("nan")
        print(f"{r['seed']:>4} {r['source_seed']:>5} {(fc['angle'] if fc else float('nan')):>5.1f} "
              f"{str(r['first_in_zone'])[0]:>4} {len(f['ribs']):>4} {f['V_ref_mm3']:>7.2f} {f['V_full_edge_mm3']:>7.2f} "
              f"{f['V_identical_mm3']:>7.2f} {f['V_full_edge_mm3'] / f['V_ref_mm3']:>8.2f} "
              f"{f['V_identical_mm3'] / f['V_ref_mm3']:>6.3f} {sweep:>7.2f}")
        if level == "L3":
            reliefs = "  ".join(f"rib{rb['index']} {rb['best']['d_top']:.2f}x{rb['best']['d_side']:.2f} "
                                f"({rb['best']['volume_mm3']:.2f} mm3)" for rb in f["ribs"])
            pose = r["info"]["pose"]
            print(f"     reliefs: {reliefs}  ratio {f['relief_ratio']:.2f}")
            print(f"     pose: yaw {pose['yaw_deg']} deg, tilt {pose['tilt_deg']} deg about azimuth "
                  f"{pose['tilt_axis_deg']} deg, offset {pose['offset']}")

    print(f"\nPer seed x variant ({level}, 3D, real B-rep operations)")
    hdr = (f"{'seed':>4} {'variant':<12} {'sizes':<26} {'S1':>4} {'until':>5} {'minclr':>6} {'seal':>6} "
           f"{'wall':>5} {'vol%':>6} {'x_ref':>6} {'S3':>5} {'gates':<12} {'side':>4} {'reward':>6}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        for name in VARIANTS:
            if name not in r["variants"]:
                continue
            v = r["variants"][name]
            if v is None:
                print(f"{r['seed']:>4} {name:<12} (no symmetric chamfer passes S1 within the wall)")
                continue
            if v["error"]:
                print(f"{r['seed']:>4} {name:<12} {_sizes(v['ops']):<26} OP ERROR: {v['error'][:80]}")
                continue
            failed = [k for k, ok in v["gates"].items() if not ok]
            sc = v.get("side_collisions")
            side = "-" if sc is None else ("0" if max(sc.values()) == 0 else "HIT")
            print(f"{r['seed']:>4} {name:<12} {_sizes(v['ops']):<26} {('ok' if v['s1']['met'] else 'FAIL'):>4} "
                  f"{str(v['s1']['ok_until']):>5} {v['s1']['min_clearance']:>6.3f} {v['seal_margin']:>6.2f} "
                  f"{('ok' if v['min_wall_ok'] else 'THIN'):>5} {v['changed_pct']:>6.3f} {v['ratio_to_ref']:>6.2f} {v['s3']:>5.3f} "
                  f"{('ok' if not failed else 'FAIL ' + ','.join(failed)):<12} {side:>4} {v['reward']:>6.3f}")
    print("\nS1 ok = no overlap 0..110 and clearance >= 0.3 mm from 10 deg; until = largest angle up to which S1 "
          "holds; minclr = min clearance 10..110 (capped at 0.35);\nseal = seal margin (ring width - 1.5); wall = "
          "no new wall < 1.2 mm; vol% = changed volume % of the enclosure; x_ref = changed volume / V_ref;\ngates: G1-G6 "
          "(cadfix/checks via scenarios/hinge_lid/spec.py); side = max overlap over 0..110 of pin x enclosure/lid, "
          "module x enclosure, lid x bracket material (0 = none).")


def summary(rows: list[dict]) -> dict:
    """Per level and variant: rewards over seeds, S1 pass count."""
    out = {}
    for r in rows:
        for name, v in r["variants"].items():
            if v is None or v.get("error"):
                continue
            d = out.setdefault((r["level"], name), {"rewards": [], "s1": 0, "n": 0, "side_hits": 0})
            d["rewards"].append(v["reward"])
            d["s1"] += int(v["s1"]["met"])
            d["n"] += 1
            sc = v.get("side_collisions")
            d["side_hits"] += int(bool(sc) and max(sc.values()) > 0)
    return out


def print_summary(rows: list[dict]):
    print("\n===== Summary: reward min / mean / max over seeds, S1 passes, side collisions =====")
    for (level, name), d in summary(rows).items():
        rw = d["rewards"]
        print(f"{level} {name:<12} {min(rw):.3f} / {np.mean(rw):.3f} / {max(rw):.3f}   S1 {d['s1']}/{d['n']}   "
              f"side hits {d['side_hits']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--level", default="L1,L2,L3")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--out", default="output/hinge_lid")
    ap.add_argument("--no-side", action="store_true", help="skip pin / module / bracket sweeps (faster)")
    ap.add_argument("-v", "--verbose", action="store_true", help="per seed: contacts and first S1 failure")
    ap.add_argument("--glb", action="store_true", help="export closed / first-hit / 110 deg scenes as .glb")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    all_rows = []
    for level in generator.parse_levels(args.level):
        rows = [run_seed(level, s, args.out, not args.no_side, args.verbose, args.glb)
                for s in generator.parse_seeds(args.seeds)]
        print_level(level, rows)
        all_rows += rows
    print_summary(all_rows)
    print(f"\ntotal {time.perf_counter() - t0:.1f} s")


if __name__ == "__main__":
    main()
