"""hinge_lid spec as data: docs/scenario.json `spec` (G1-G6, S1-S3, reward) instantiated with generic checks for
one level/seed. public_spec() goes into the agent's task (spec.json); private_values() only to the grader."""
from __future__ import annotations

from scenarios.hinge_lid import generator as gen

EDITABLE = ["enclosure", "lid"]
MOVING = ["lid", "lid_module"]
TEST_FIT_COST = {"free_calls": 2, "per_call": 0.02, "cap": 0.1}


def s3_rule(level: str) -> str:
    full, zero = gen.S3_FACTORS[level]
    return (f"full points if the changed volume is within {full:g}x of the best known fix for this task, "
            f"zero at {zero:g}x (linear in between)")


def public_spec(info: dict) -> dict:
    level = info["level"]
    full, zero = gen.S3_FACTORS[level]
    frame = info["frame_axes"]
    plane = info["wall_top_plane"]
    s1 = gen.s1_spec()
    checks = [
        {"id": "G1_valid_solids", "type": "valid_solid", "role": "gate", "params": {"parts": EDITABLE},
         "description": "both editable parts are valid closed solids (OpenCascade check)"},
        {"id": "G2_hinge_interface", "type": "interface_frozen", "role": "gate",
         "params": {"regions": info["interface_regions"], "tol_mm3": 0.01},
         "description": "pin holes keep diameter, position and axis: the material within the given cylinders "
                        "around the pin axis is unchanged on both parts"},
        {"id": "G3_keep_in", "type": "keep_in", "role": "gate", "params": {"min_fill": 0.99},
         "description": "lid knuckles, knuckle ribs, enclosure knuckle brackets, module frame and seal band "
                        "(zones in task.json) keep >= 99 % of their original material"},
        {"id": "G3_keep_out", "type": "keep_out", "role": "gate", "params": {"tol_mm3": 1e-3},
         "description": "no new lid or enclosure material in the volume of lid_module (closed position)"},
        {"id": "G4_closed_position", "type": "collision_free", "role": "gate",
         "params": {"angle_deg": 0.0, "moving": MOVING, "fixed": ["enclosure", "hinge_pin"]},
         "description": "at 0 deg no collision between lid (with module) and enclosure or pin"},
        {"id": "G5_seal", "type": "contact_width", "role": "gate",
         "params": {"lower": "enclosure", "upper": "lid", "plane_point": plane["point"],
                    "plane_normal": plane["normal"], "min_width_mm": gen.SEAL_MIN_WIDTH},
         "description": f"at 0 deg the contact between lid and wall tops is >= {gen.SEAL_MIN_WIDTH} mm wide all "
                        f"around (eroded by {gen.SEAL_MIN_WIDTH / 2:g} mm it still forms a closed ring)"},
        {"id": "G6_not_rebuilt", "type": "envelope", "role": "gate",
         "params": {"parts": EDITABLE, "frame": frame, "tol_mm": 0.5, "max_change_pct": 15.0},
         "description": "outer envelope of each editable part moves by <= 0.5 mm along the box axes; changed "
                        "volume (removed + added) of each part <= 15 %"},
        {"id": "S1_opening", "type": "sweep_clearance", "role": "objective",
         "params": {"moving": s1["moving"], "fixed": s1["fixed"], "range_deg": s1["range_deg"],
                    "step_deg": s1["step_deg"], "overlap_eps_mm3": s1["overlap_eps_mm3"],
                    "clearance_mm": s1["clearance_mm"], "clearance_from_deg": s1["clearance_from_deg"],
                    "search_mm": s1["search_mm"], "frame": frame},
         "description": "rotate lid (with module) about the pin axis 0..110 deg in 1 deg steps: no overlap "
                        "(> 1e-3 mm3) at any step, touching allowed; clearance lid(+module) vs enclosure >= 0.3 mm "
                        "at every step from 10 deg (pin excluded). Score = progress: 0.5 * angle progress + 0.5 * "
                        "clearance progress (see the reward)"},
        {"id": "S2_min_wall", "type": "min_wall", "role": "score",
         "params": {"parts": EDITABLE, "frame": frame, "min_mm": gen.MIN_WALL, "feature_mm": 0.2},
         "description": "no new wall thinner than 1.2 mm (features smaller than 0.2 mm are ignored)"},
        {"id": "S2_overhang", "type": "overhang", "role": "score",
         "params": {"parts": EDITABLE, "max_angle_deg": 45.0, "feature_mm": 0.2, "tol_mm2": 0.01},
         "description": "no new overhang steeper than 45 deg in print orientation (enclosure on its floor, lid top "
                        "face down); features smaller than 0.2 mm are ignored"},
        {"id": "S3_minimal_change", "type": "volume_change", "role": "score",
         "params": {"parts": EDITABLE, "full_factor": full, "zero_factor": zero},
         "description": "changed volume (added + removed) vs the original parts; " + s3_rule(level)},
    ]
    r = gen.REWARD_POLICY
    return {
        "scenario": "hinge_lid", "level": level, "checks": checks,
        "reward": {"objective": "S1_opening", "progress_weight": r.progress_weight, "met_base": r.met_base,
                   "scores": {"printability": {"weight": r.weights["printability"],
                                               "checks": ["S2_min_wall", "S2_overhang"], "combine": "all_passed"},
                              "minimal_change": {"weight": r.weights["minimal_change"],
                                                 "checks": ["S3_minimal_change"], "combine": "score"}},
                   "formula": "any gate failed -> 0; S1 not met -> 0.25 * progress; S1 met -> 0.3 + 0.1 * "
                              "printability + 0.6 * minimal_change; minus the test_fit cost"},
        "test_fit_cost": TEST_FIT_COST,
        "rules": {"S3": s3_rule(level)},
    }


def private_values(info: dict) -> dict:
    """Grader-only parameters (merged into the check params by id)."""
    return {"S3_minimal_change": {"reference_mm3": info["feasibility"]["V_ref_mm3"]}}
