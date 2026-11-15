"""hinge_lid generator: (level, seed) -> four parts (STEP) + params/feasibility JSON.

Local frame: x along the hinge, y from front (y=0) to rear (y=W), z up. Units mm, degrees. Everything is built
and all feasibility work runs in this frame. L1 and L2 place the assembly at the identity pose (world = local);
L3 places it with a seeded rigid pose (yaw about world z, tilt about a horizontal axis, offset), so the STEP
parts, axis, zones and print orientations written for L3 are in the rotated world frame.

Levels (docs/scenario.json `levels`)
- L1, L2: task 2b geometry, every lid rib identical (2 or 3 ribs: 5 or 7 knuckles). L2 differs from L1 only in
  the S3 factors.
- L3: always 3 ribs (7 knuckles), each rib's depth below the axis and front/rear extent drawn independently, so
  every rib needs its own relief; world pose.

Parts
- enclosure: open box, rear wall's outer top edge E = (y=W, z=H) is one straight edge along x.
  Enclosure knuckles (cylinder + upright + bridge + 45 deg gusset) hang off the rear wall's outer face
  BELOW a free band, so the free band under E stays clear.
- lid: plate on the wall tops (the whole wall top is the seal contact). In lid-knuckle segments it continues
  behind the wall: tail plate, knuckle cylinder and a rib (lug) hanging under the knuckle. Everything stays
  below the lid's top face (the lid prints top face down). Frame around lid_module on the underside.
- hinge_pin: fixed cylinder through all knuckles; knuckles have bores with a radial clearance.
- lid_module: board under the lid near its rear edge, inside the box when closed.

The defect: each rib reaches to radius R > |A - E| from the hinge axis A, so while opening it swings through
the wall's outer top edge E. Feasibility (exact 2D section model per rib) scans asymmetric triangular cuts
(top x side) of E meeting S1 (no overlap 0..110 deg, clearance >= 0.3 mm from 10 deg) with seal margin
>= 0.3 mm and wall >= 1.2 mm:
- per rib: the smallest relief over the rib's x-range extended by RELIEF_EXTENSION at both ends; V_ref = sum;
- full edge: the smallest chamfer along the whole edge that is valid for every rib (V_full_edge);
- identical: the same profile as that chamfer, but as one relief per rib (V_identical, the L3 trap).
A seed with an empty set for any rib is replaced by seed + 1000*k.

Run: python -m scenarios.hinge_lid.generator --level L1 --seeds 0-9 --out output/hinge_lid
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import cadquery as cq
import numpy as np
from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from cadfix.checks.sweep import opening_check
from cadfix.core import kernel
from cadfix.core.kernel import export_step
from cadfix.core.reward import RewardPolicy
from cadfix.ops.edit import apply_ops

OPEN_ANGLE_DEG = 110.0
STEP_DEG = 1.0
CLEARANCE = 0.3              # S1: min clearance lid(+module) vs enclosure while opening
CLEARANCE_FROM_DEG = 10.0    # S1: clearance required from this angle (at 0 deg the lid rests on the seal)
SEARCH_MM = 0.35             # clearance search radius (gaps beyond it are reported as SEARCH_MM)
SEAL_MIN_WIDTH = 1.5         # scenario.json protections.seal_band.min_contact_width_mm
SEAL_MARGIN_MIN = 0.3        # scenario.json protections.seal_band.min_margin_mm_base_level
MIN_WALL = 1.2               # scenario.json S2
GRID_MM = 0.05               # relief / chamfer scan step (top x side)
RELIEF_EXTENSION = 0.35      # relief length beyond each rib end along x: clearance 0.3 + one grid step
ANGLE_WINDOW = (40.0, 95.0)  # accepted predicted first-collision angle of the original (every rib)
# L3: the 2D scan asks for CLEARANCE + this. World coordinates (rotated pose) are snapped to SNAP_MM, so a relief
# that clears by < 1e-3 mm in the exact 2D model can read just below 0.3 in the world-frame grader (DECISIONS D10).
L3_SCAN_CLEARANCE_MARGIN = 0.002
L3_MIN_IDENTICAL_RATIO = 1.4  # L3: V_identical / V_ref (identical reliefs sized for the worst rib, the trap)
MAX_ATTEMPTS = 200
REPLACE_STRIDE = 1000        # empty set for a rib -> seed + REPLACE_STRIDE * k
# scenario.json spec.reward: S1 not met -> 0.25 * progress; met -> 0.3 + 0.1 * printability + 0.6 * minimal_change
REWARD_POLICY = RewardPolicy(progress_weight=0.25, met_base=0.3,
                             weights={"printability": 0.1, "minimal_change": 0.6})
# scenario.json levels.*.S3: (full points up to, zero at) x V_ref; tests/test_reward.py checks these against
# the text in docs/scenario.json
S3_FACTORS = {"L1": (5.0, 10.0), "L2": (1.15, 2.0), "L3": (1.15, 2.0)}
AXIS_DIRECTION = (-1.0, 0.0, 0.0)  # positive angle about this axis opens the lid (local frame)
PART_NAMES = ("enclosure", "lid", "hinge_pin", "lid_module")
LEVELS = ("L1", "L2", "L3")
# print orientation: build direction ("up" on the printer) in the local frame
PRINT_UP_LOCAL = {"enclosure": (0.0, 0.0, 1.0), "lid": (0.0, 0.0, -1.0)}
PRINT_RULE = {"enclosure": "on its floor", "lid": "top face down"}


@dataclass
class Pose:
    """Rigid placement local -> world: yaw about world z, then tilt about a horizontal axis, then offset."""
    yaw_deg: float
    tilt_deg: float
    tilt_axis_deg: float   # azimuth of the horizontal tilt axis in the world xy plane
    offset: tuple

    def matrix(self) -> np.ndarray:
        az = math.radians(self.tilt_axis_deg)
        yaw = kernel.rotation_matrix((0, 0, 0), (0, 0, 1), self.yaw_deg)
        tilt = kernel.rotation_matrix((0, 0, 0), (math.cos(az), math.sin(az), 0.0), self.tilt_deg)
        return kernel.compose(kernel.translation(self.offset), tilt, yaw)


@dataclass
class HingeLidParams:
    seed: int
    attempt: int
    # box
    L: float          # length along x
    W: float          # depth along y
    H: float          # height (wall top)
    t: float          # wall thickness
    floor: float
    t_lid: float
    # hinge
    a: float          # axis behind the rear wall's outer face (ya = W + a)
    b: float          # axis above the wall top (za = H + b)
    r_k: float        # knuckle outer radius
    r_pin: float
    r_bore: float
    axial_gap: float
    n_knuckles: int   # odd: enclosure knuckles at both ends
    hinge_span: float
    free_band: float  # height under the wall top kept free of enclosure-knuckle bridges
    bridge_h: float
    # rib (lug) under each lid knuckle, offsets from the axis (q: + rear / - front). L1/L2: every rib;
    # L3: rib 0 (see ribs)
    lug_q0: float     # front face
    lug_q1: float     # rear face
    lug_p: float      # bottom depth below the axis
    # module + frame
    module_x: float
    module_y: float
    module_z: float
    module_wall_gap: float
    frame_t: float
    frame_h: float
    frame_clear: float
    # level
    level: str = "L1"
    ribs: tuple | None = None   # L3: one (q0, q1, p) per lid segment
    pose: Pose | None = None    # L3: world placement

    # ---- derived
    @property
    def ya(self) -> float:
        return round(self.W + self.a, 3)

    @property
    def za(self) -> float:
        return round(self.H + self.b, 3)

    @property
    def axis_point(self) -> tuple[float, float, float]:
        return (0.0, self.ya, self.za)

    def segments(self) -> list[tuple[str, float, float]]:
        """Knuckle segments along x: (owner, x_start, x_end), alternating enclosure / lid."""
        n, g = self.n_knuckles, self.axial_gap
        seg = (self.hinge_span - (n - 1) * g) / n
        x0 = (self.L - self.hinge_span) / 2
        out = []
        for i in range(n):
            xs = x0 + i * (seg + g)
            out.append(("enclosure" if i % 2 == 0 else "lid", round(xs, 3), round(xs + seg, 3)))
        return out

    def lid_segments(self) -> list[tuple[float, float]]:
        return [(xs, xe) for o, xs, xe in self.segments() if o == "lid"]

    def rib_profiles(self) -> list[tuple[float, float, float]]:
        """(q0, q1, p) per lid segment."""
        if self.ribs is not None:
            return [tuple(r) for r in self.ribs]
        return [(self.lug_q0, self.lug_q1, self.lug_p)] * len(self.lid_segments())

    def pose_matrix(self) -> np.ndarray:
        return kernel.IDENTITY.copy() if self.pose is None else self.pose.matrix()

    def module_box(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        y1 = self.W - self.t - self.module_wall_gap - self.frame_t - self.frame_clear
        x0 = (self.L - self.module_x) / 2
        lo = (x0, y1 - self.module_y, self.H - self.module_z)
        hi = (x0 + self.module_x, y1, self.H)
        return tuple(round(v, 3) for v in lo), tuple(round(v, 3) for v in hi)


# ---------------------------------------------------------------- sampling
def _u(rng: np.random.Generator):
    return lambda lo, hi, nd=2: round(float(rng.uniform(lo, hi)), nd)


def _draw_rib(rng: np.random.Generator, a: float, b: float) -> tuple[float, float, float]:
    """Rib width, centre offset from the axis and how far its farthest corner reaches past |A-E|."""
    u = _u(rng)
    w = u(1.6, 2.0)
    s = u(-0.8, 0.6)
    pen = u(0.2, 0.45)
    q0, q1 = round(s - w / 2, 3), round(s + w / 2, 3)
    d_e = math.hypot(a, b)
    p = round(math.sqrt((d_e + pen) ** 2 - max(q0 * q0, q1 * q1)), 2)
    return q0, q1, p


def _draw(rng: np.random.Generator, seed: int, attempt: int) -> HingeLidParams:
    u = _u(rng)
    r_k, t_lid = 2.2, 3.0
    L = u(60, 100, 1)
    a = round(r_k + u(0.5, 1.0), 2)
    b = u(0.4, t_lid - r_k)
    q0, q1, p = _draw_rib(rng, a, b)
    return HingeLidParams(
        seed=seed, attempt=attempt,
        L=L, W=u(40, 70, 1), H=u(22, 35, 1), t=u(2.4, 3.0), floor=2.0, t_lid=t_lid,
        a=a, b=b, r_k=r_k, r_pin=0.875, r_bore=1.0, axial_gap=0.4,
        n_knuckles=int(rng.choice([5, 7])), hinge_span=round(L * u(0.5, 0.75), 1),
        free_band=4.0, bridge_h=2.5,
        lug_q0=q0, lug_q1=q1, lug_p=p,
        module_x=u(20, min(40, 0.45 * L), 1), module_y=u(10, 15, 1), module_z=u(4, 6, 1),
        module_wall_gap=1.0, frame_t=1.2, frame_h=3.0, frame_clear=0.2,
    )


def _draw_l3(rng: np.random.Generator, seed: int, attempt: int) -> HingeLidParams:
    """Task 2b draw with 7 knuckles (3 lid ribs), each rib drawn independently, plus a world pose."""
    base = _draw(rng, seed, attempt)
    ribs = (base.lug_q0, base.lug_q1, base.lug_p), _draw_rib(rng, base.a, base.b), _draw_rib(rng, base.a, base.b)
    u = _u(rng)
    sign = lambda: 1.0 if rng.random() < 0.5 else -1.0  # noqa: E731
    pose = Pose(yaw_deg=u(15, 40), tilt_deg=u(0, 8), tilt_axis_deg=u(0, 360),
                offset=(round(sign() * u(20, 200, 1), 1), round(sign() * u(20, 200, 1), 1), u(20, 200, 1)))
    return dataclasses.replace(base, n_knuckles=7, level="L3", ribs=tuple(ribs), pose=pose)


def _rng(seed: int, level: str) -> np.random.Generator:
    # L1 and L2 share the task 2b stream (same parts); L3 has its own
    return np.random.default_rng([seed, 3] if level == "L3" else seed)


def sample_params(seed: int, level: str = "L1") -> tuple[HingeLidParams, dict]:
    """Deterministic per (seed, level): draw until the cheap geometric checks accept (rejection sampling),
    then run the 2D scans on that draw. A rib with an empty set makes the draw infeasible (resolve_seed then
    replaces the seed). L3 also redraws until identical reliefs sized for the worst rib need
    >= L3_MIN_IDENTICAL_RATIO x V_ref and the lid plate outside the ribs clears the original wall."""
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}, expected one of {LEVELS}")
    rng = _rng(seed, level)
    reasons_seen = []
    for attempt in range(MAX_ATTEMPTS):
        p = _draw_l3(rng, seed, attempt) if level == "L3" else dataclasses.replace(_draw(rng, seed, attempt),
                                                                                     level=level)
        f = feasibility(p)
        if f["reasons"]:
            reasons_seen.append(f["reasons"])
            continue
        f.update(scan(p))
        f["feasible"] = f["scan"]["best"] is not None and all(r["best"] is not None for r in f["ribs"])
        if level == "L3" and f["feasible"]:
            late = []
            ident = f["V_identical_mm3"] / f["V_ref_mm3"]
            if ident < L3_MIN_IDENTICAL_RATIO:
                late.append(f"identical reliefs need {ident:.3f}x V_ref < {L3_MIN_IDENTICAL_RATIO}x")
            if not f["plate_clear"]:
                late.append("lid plate outside the ribs does not clear the original wall")
            if late:
                reasons_seen.append(late)
                continue
        return p, f
    raise RuntimeError(f"seed {seed} {level}: no feasible draw in {MAX_ATTEMPTS} attempts, e.g. {reasons_seen[:3]}")


def resolve_seed(seed: int, level: str = "L1", max_replacements: int = 20) -> tuple[HingeLidParams, dict, list[int]]:
    """Params for a task seed. If any rib has no valid relief, the seed is replaced by
    seed + REPLACE_STRIDE * k (k = 1, 2, ...). Returns (params, feasibility, rejected source seeds)."""
    rejected = []
    for k in range(max_replacements + 1):
        source = seed + REPLACE_STRIDE * k
        p, f = sample_params(source, level)
        if f["feasible"]:
            f["reference"] = verify_reference_3d(p, f)
            f["feasible"] = f["reference"]["met"]
            if not f["feasible"]:
                print(f"seed {seed} {level}: source seed {source}: per-rib reliefs fail S1 in 3D "
                      f"({f['reference']}), replacing")
        if f["feasible"]:
            if rejected:
                print(f"seed {seed} {level}: source seeds {rejected} have a rib without a valid relief, "
                      f"using source seed {source}")
            return p, f, rejected
        rejected.append(source)
    raise RuntimeError(f"seed {seed} {level}: no valid relief in source seeds {rejected}")


# ---------------------------------------------------------------- analytic feasibility
def _rotate_yz(pts: np.ndarray, theta_deg: np.ndarray) -> np.ndarray:
    """Rotate (dy, dz) offsets from the axis by the OPENING angle (about -x). pts (N,2), theta (M,) -> (M,N,2)."""
    th = np.radians(theta_deg)[:, None]
    c, s = np.cos(th), np.sin(th)
    y, z = pts[None, :, 0], pts[None, :, 1]
    return np.stack([y * c + z * s, -y * s + z * c], axis=-1)


def _rib(p: HingeLidParams, rib) -> tuple[float, float, float]:
    return (p.lug_q0, p.lug_q1, p.lug_p) if rib is None else tuple(rib)


def _lug_outline(p: HingeLidParams, rib=None, n: int = 60) -> np.ndarray:
    """Front, bottom and rear faces of the rib as (dy, dz) offsets from the axis."""
    q0, q1, d = _rib(p, rib)
    front = np.column_stack([np.full(n, q0), np.linspace(0, -d, n)])
    bottom = np.column_stack([np.linspace(q0, q1, n), np.full(n, -d)])
    rear = np.column_stack([np.full(n, q1), np.linspace(-d, 0, n)])
    return np.vstack([front, bottom, rear])


def predicted_first_collision(p: HingeLidParams, rib=None, step: float = 0.01) -> float | None:
    """Smallest opening angle at which the rib and the rear wall overlap (2D section, analytic geometry).

    Contact of two polygons starts either with a rib point entering the wall or with a wall corner
    entering the rib; both are tested on a fine angle grid.
    """
    q0, q1, d = _rib(p, rib)
    thetas = np.arange(0.0, 180.0 + step, step)
    # 1) rib outline points entering the wall rectangle y in [W-t, W], z in [0, H]
    pts = _rotate_yz(_lug_outline(p, rib), thetas)
    y, z = pts[..., 0] + p.ya, pts[..., 1] + p.za
    inside = (y < p.W - 1e-9) & (y > p.W - p.t) & (z < p.H - 1e-9) & (z > 0)
    hit1 = np.where(inside.any(axis=1))[0]
    # 2) wall corners (outer and inner top edge) entering the rib, seen in the lid's frame (inverse rotation)
    corners = np.array([[-p.a, -p.b], [-p.a - p.t, -p.b]])
    c = _rotate_yz(corners, -thetas)
    inside2 = ((c[..., 0] > q0) & (c[..., 0] < q1) & (c[..., 1] > -d) & (c[..., 1] < 0))
    hit2 = np.where(inside2.any(axis=1))[0]
    hits = [thetas[h[0]] for h in (hit1, hit2) if len(h)]
    return round(float(min(hits)), 2) if hits else None


def _rib_facts(p: HingeLidParams, rib) -> tuple[dict, list[str]]:
    a, b = p.a, p.b
    d_e = math.hypot(a, b)
    q0, q1, d = rib
    # lid material that can swing into the wall: the rib corners, the knuckle, the tail plate corners
    r_lug = max(math.hypot(q, -d) for q in (q0, q1))
    r_swept = max(r_lug, p.r_k, max(math.hypot(*q) for q in ((-a, -b), (p.r_k, -b))))
    theta = predicted_first_collision(p, rib)
    reasons = []
    if r_swept - d_e < 0.15:
        reasons.append("lid reaches less than 0.15 mm past the edge (collision too small)")
    if d < p.r_k + 0.3:
        reasons.append("lug does not hang below the knuckle")
    if theta is None or not (ANGLE_WINDOW[0] <= theta <= ANGLE_WINDOW[1]):
        reasons.append(f"predicted first collision {theta} outside {ANGLE_WINDOW}")
    zone = {"top_width": round(math.sqrt(max(r_swept ** 2 - b * b, 0)) - a, 4),
            "side_depth": round(math.sqrt(max(r_swept ** 2 - a * a, 0)) - b, 4)}
    return {"R_swept": round(r_swept, 4), "penetration": round(r_swept - d_e, 4), "collision_zone": zone,
            "predicted_first_collision_deg": theta}, reasons


def feasibility(p: HingeLidParams) -> dict:
    """Cheap analytic checks of a draw (the 2D scans run separately, see scan)."""
    d_e = math.hypot(p.a, p.b)
    reasons = []
    facts = []
    profiles = p.rib_profiles()
    for i, rib in enumerate(profiles):
        if i > 0 and rib == profiles[0] and facts:
            facts.append(facts[0])
            continue
        fa, rs = _rib_facts(p, rib)
        facts.append(fa)
        reasons += [(f"rib {i}: {r}" if p.ribs is not None else r) for r in rs]
    if p.r_k > d_e - 0.3:
        reasons.append("knuckle too close to the wall edge")
    if p.za + p.r_k > p.H + p.t_lid + 1e-9:
        reasons.append("lid knuckle sticks out above the lid top (lid prints top face down)")
    if any(xe - xs < 6.0 for _, xs, xe in p.segments()):
        reasons.append("knuckle segment shorter than 6 mm")
    (mx0, my0, mz0), _ = p.module_box()
    if my0 - p.frame_clear - p.frame_t < p.t + 5:
        reasons.append("module frame does not fit in the box depth")

    worst = max(facts, key=lambda fa: fa["R_swept"])
    thetas = [fa["predicted_first_collision_deg"] for fa in facts if fa["predicted_first_collision_deg"] is not None]
    return {
        "feasible": False,  # set by sample_params after the scans
        "reasons": reasons,
        "axis_to_edge": round(d_e, 4),
        "R_swept": worst["R_swept"],
        "penetration": worst["penetration"],
        "collision_zone": worst["collision_zone"],
        "predicted_first_collision_deg": min(thetas) if thetas else None,
        "rib_facts": facts,
    }


# ---------------------------------------------------------------- exact 2D scans
def _poly(pts) -> Polygon:
    return Polygon(pts)


def _rect(y0, y1, z0, z1) -> Polygon:
    return box(min(y0, y1), min(z0, z1), max(y0, y1), max(z0, z1))


def lid_section(p: HingeLidParams, rib=None, plate_only: bool = False) -> Polygon:
    """Section of the lid (+ module) through a lid knuckle segment, as (dy, dz) offsets from the hinge axis
    (dy + towards the rear). Plate (cut 8 mm in front of the wall, which only rises), tail plate, knuckle, rib,
    module frame bar and module. The bore is left out: it is far from the wall.
    plate_only: the section outside the lid segments (plate ends at the wall's outer face, no tail/knuckle/rib)."""
    a, b, t = p.a, p.b, p.t
    q0, q1, d = _rib(p, rib)
    (mx0, my0, mz0), (mx1, my1, mz1) = p.module_box()
    c, ft = p.frame_clear, p.frame_t
    parts = [
        _rect(my1 + c - p.ya, my1 + c + ft - p.ya, p.H - p.frame_h - p.za, -b),  # frame bar at the rear
        _rect(my0 - p.ya, my1 - p.ya, mz0 - p.za, mz1 - p.za),               # module
    ]
    if plate_only:
        parts.append(_rect(-(a + t + 8.0), -a, -b, p.t_lid - b))
    else:
        parts += [
            _rect(-(a + t + 8.0), p.r_k, -b, p.t_lid - b),                    # plate + tail plate
            Point(0, 0).buffer(p.r_k, quad_segs=64),                           # knuckle
            _rect(q0, q1, -d, 0.0),                                            # rib
        ]
    return unary_union(parts)


def wall_section(p: HingeLidParams, d_top: float, d_side: float, depth: float = 15.0) -> Polygon:
    """Rear wall section with an asymmetric triangular cut of E (d_top along the top, d_side down the outer
    face), as offsets from the hinge axis."""
    a, b, t = p.a, p.b, p.t
    pts = [(-a - t, -b), (-a - d_top, -b)]
    pts += [(-a, -b - d_side)] if d_top > 0 and d_side > 0 else [(-a, -b)]
    pts += [(-a, -b - depth), (-a - t, -b - depth)]
    return _poly(pts)


def _swept(sec: Polygon, angles) -> Polygon:
    """Union of the section rotated by each opening angle (same convention as _rotate_yz)."""
    out = []
    for th in angles:
        c, s = math.cos(math.radians(th)), math.sin(math.radians(th))
        out.append(affinity.affine_transform(sec, [c, s, -s, c, 0.0, 0.0]))
    return unary_union(out)


def s1_angles() -> tuple[list[float], list[float]]:
    """(all steps 0..110, steps where clearance is required 10..110)."""
    n = int(round(OPEN_ANGLE_DEG / STEP_DEG))
    steps = [round(i * STEP_DEG, 6) for i in range(n + 1)]
    return steps, [th for th in steps if th >= CLEARANCE_FROM_DEG - 1e-9]


class SectionModel:
    """S1 in the 2D section model: one lid section swept 0..110 deg against the rear wall with a triangular
    cut (top x side) of its outer top edge."""

    def __init__(self, p: HingeLidParams, sec: Polygon, seg_len: float):
        steps, clear_steps = s1_angles()
        self.p = p
        self.lift = _swept(sec, [th for th in steps if th < CLEARANCE_FROM_DEG - 1e-9])
        self.clear = _swept(sec, clear_steps)
        self.area_eps = 1e-3 / seg_len   # 1e-3 mm^3 overlap over the segment length
        self.clearance = CLEARANCE + (L3_SCAN_CLEARANCE_MARGIN if p.level == "L3" else 0.0)

    def check(self, d_top: float, d_side: float) -> tuple[bool, float]:
        w = wall_section(self.p, d_top, d_side)
        if self.lift.intersection(w).area > self.area_eps:
            return False, 0.0
        gap = self.clear.distance(w)
        return gap >= self.clearance - 1e-9, gap


def scan_grid(p: HingeLidParams) -> tuple[list[float], list[float]]:
    """tops <= t - 1.5 - 0.3 (seal margin >= 0.3 and wall >= 1.2), sides <= free_band - 0.5 (cut stays above the
    enclosure knuckle brackets)."""
    n_top = int(math.floor((p.t - SEAL_MIN_WIDTH - SEAL_MARGIN_MIN) / GRID_MM + 1e-9))
    n_side = int(math.floor((p.free_band - 0.5) / GRID_MM + 1e-9))
    return ([round(i * GRID_MM, 3) for i in range(1, n_top + 1)],
            [round(i * GRID_MM, 3) for i in range(1, n_side + 1)])


def side_min_by_top(model: SectionModel, tops, sides) -> dict:
    """Removing more material never reduces clearance, so for a fixed top the valid sides form one interval
    [side_min(top), side limit]: bisect for side_min."""
    out = {}
    for top in tops:
        if not model.check(top, sides[-1])[0]:
            continue
        lo, hi = -1, len(sides) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (lo, mid) if model.check(top, sides[mid])[0] else (mid, hi)
        out[top] = sides[hi]
    return out


def _profile_best(side_min: dict, models, p) -> dict | None:
    if not side_min:
        return None
    top = min(side_min, key=lambda tp: (tp * side_min[tp], tp))
    side = side_min[top]
    return {"d_top": top, "d_side": side, "area_mm2": round(0.5 * top * side, 6),
            "clearance_2d": round(min(m.check(top, side)[1] for m in models), 4),
            "seal_margin": round(p.t - top - SEAL_MIN_WIDTH, 4), "min_wall": round(p.t - top, 4)}


def scan(p: HingeLidParams) -> dict:
    """All 2D scans of a draw: per-rib reliefs (V_ref), the full-edge chamfer valid for every rib
    (V_full_edge, task 2b behaviour), identical reliefs with that profile (V_identical) and the smallest
    symmetric 45 deg full-edge chamfer passing S1."""
    tops, sides = scan_grid(p)
    lid_x = p.lid_segments()
    profiles = p.rib_profiles()
    seg_len = min(xe - xs for xs, xe in lid_x)
    models, side_mins = {}, {}
    for rib in profiles:
        if rib not in models:
            models[rib] = SectionModel(p, lid_section(p, rib), seg_len)
            side_mins[rib] = side_min_by_top(models[rib], tops, sides)

    ribs = []
    for i, ((xs, xe), rib) in enumerate(zip(lid_x, profiles)):
        best = _profile_best(side_mins[rib], [models[rib]], p)
        length = round(xe - xs + 2 * RELIEF_EXTENSION, 4)
        if best:
            best = best | {"x": [round(xs - RELIEF_EXTENSION, 4), round(xe + RELIEF_EXTENSION, 4)],
                           "length": length, "volume_mm3": round(best["area_mm2"] * length, 4)}
        ribs.append({"index": i, "x": [xs, xe], "profile": {"q0": rib[0], "q1": rib[1], "p": rib[2]},
                     "side_min_by_top": {f"{tp:.2f}": sd for tp, sd in sorted(side_mins[rib].items())},
                     "best": best})

    # full edge: valid for every rib at once
    all_models = list(models.values())
    common = set(tops)
    for sm in side_mins.values():
        common &= set(sm)
    side_min = {tp: max(sm[tp] for sm in side_mins.values()) for tp in sorted(common)}
    full = {"grid_mm": GRID_MM, "side_limit": sides[-1], "top_limit": tops[-1] if tops else None,
            "valid_tops": [], "side_min_by_top": {}, "best": None, "symmetric_45": None}
    if side_min:
        b = _profile_best(side_min, all_models, p)
        b["volume_mm3"] = round(0.5 * b["d_top"] * b["d_side"] * p.L, 4)
        valid_tops = sorted(side_min)
        mid_top = valid_tops[len(valid_tops) // 2]
        full.update({
            "valid_tops": valid_tops,
            "side_min_by_top": {f"{tp:.2f}": sd for tp, sd in side_min.items()},
            "n_valid": sum(len(sides) - sides.index(sd) for sd in side_min.values()),
            "best": b,
            "middle_top": mid_top,
            "side_interval_at_middle_top": [side_min[mid_top], sides[-1]],
        })
    for i in range(1, int(math.floor(p.t / GRID_MM)) + 1):
        d = round(i * GRID_MM, 3)
        if all(m.check(d, d)[0] for m in all_models):
            full["symmetric_45"] = {"d": d, "seal_width": round(p.t - d, 4),
                                    "seal_margin": round(p.t - d - SEAL_MIN_WIDTH, 4),
                                    "volume_mm3": round(0.5 * d * d * p.L, 3)}
            break

    out = {"scan": full, "ribs": ribs, "plate_clear": SectionModel(p, lid_section(p, plate_only=True), p.L)
           .check(0.0, 0.0)[0]}
    if full["best"] and all(r["best"] for r in ribs):
        vols = [r["best"]["volume_mm3"] for r in ribs]
        fb = full["best"]
        out.update({
            "V_ref_mm3": round(sum(vols), 4),
            "V_full_edge_mm3": fb["volume_mm3"],
            "identical_relief": {"d_top": fb["d_top"], "d_side": fb["d_side"]},
            "V_identical_mm3": round(sum(0.5 * fb["d_top"] * fb["d_side"] * r["best"]["length"] for r in ribs), 4),
            "relief_ratio": round(max(vols) / min(vols), 4),
        })
    return out


# ---------------------------------------------------------------- reliefs as operations
def relief_ops(p: HingeLidParams, sizes, extension: float = RELIEF_EXTENSION, world: bool = True) -> list[dict]:
    """One extrude_cut per lid segment removing the triangle (top along the wall top, side down the outer face)
    at the rear wall's outer top edge, over the segment's x-range extended by `extension` at both ends.
    sizes: one (top, side) per lid segment. world: coordinates placed with the level's pose (what an agent's
    tools would use), else the local frame."""
    m = p.pose_matrix() if world else kernel.IDENTITY
    normal = _unit(kernel.apply_dirs(m, (1.0, 0.0, 0.0))[0])
    x_dir = _unit(kernel.apply_dirs(m, (0.0, 1.0, 0.0))[0])
    ops = []
    for (xs, xe), (top, side) in zip(p.lid_segments(), sizes):
        x0 = xs - extension
        ops.append({"op": "extrude_cut", "part": "enclosure",
                    "origin": _snap(kernel.apply_points(m, (x0, p.W, p.H))[0]), "normal": normal, "x_dir": x_dir,
                    # triangle (-top, 0), (0, 0), (0, -side); the extra corners lie outside the wall and leave
                    # the top / outer face at right angles, so a 0.001 mm snap of a rotated origin leaves a
                    # sub-micron step, not a sliver with a downward face (DECISIONS D7)
                    "polygon_2d": [[-round(top, 3), 0.0], [-round(top, 3), 0.01], [0.01, 0.01],
                                   [0.01, -round(side, 3)], [0.0, -round(side, 3)]],
                    "depth_from": 0.0, "depth_to": round(xe - xs + 2 * extension, 3)})
    return ops


def reference_sizes(f: dict) -> list[tuple[float, float]]:
    return [(r["best"]["d_top"], r["best"]["d_side"]) for r in f["ribs"]]


def s1_spec() -> dict:
    return {"moving": ["lid", "lid_module"], "fixed": ["enclosure"], "range_deg": [0.0, OPEN_ANGLE_DEG],
            "step_deg": STEP_DEG, "overlap_eps_mm3": 1e-3, "clearance_mm": CLEARANCE,
            "clearance_from_deg": CLEARANCE_FROM_DEG, "search_mm": SEARCH_MM}


def verify_reference_3d(p: HingeLidParams, f: dict) -> dict:
    """The per-rib reliefs as real B-rep cuts on the local parts, S1 swept in 3D: this checks the end clearance
    along x that the 2D section model cannot see."""
    parts = build_parts_local(p)
    ops = relief_ops(p, reference_sizes(f), world=False)
    new, _ = apply_ops(parts, ops, ["enclosure"])
    meshes = {n: kernel.to_manifold(new[n]) for n in ("enclosure", "lid", "lid_module")}
    s = s1_spec()
    r = opening_check({n: meshes[n] for n in s["moving"]}, {"enclosure": meshes["enclosure"]}, p.axis_point,
                      AXIS_DIRECTION, s["range_deg"], s["step_deg"], s["overlap_eps_mm3"], s["clearance_mm"],
                      s["clearance_from_deg"], s["search_mm"])
    return {"met": r["met"], "ok_until": r["ok_until"], "min_clearance": round(r["min_clearance"], 4),
            "min_clearance_at": r["min_clearance_at"],
            "removed_mm3": round(parts["enclosure"].Volume() - new["enclosure"].Volume(), 4), "ops_local": ops}


# ---------------------------------------------------------------- B-rep construction
def _box(lo, hi) -> cq.Workplane:
    size = [h - l for l, h in zip(lo, hi)]
    return cq.Workplane("XY").box(*size, centered=False).translate(tuple(lo))


def _x_cyl(x0: float, x1: float, y: float, z: float, r: float) -> cq.Workplane:
    return cq.Workplane("YZ", origin=(x0, y, z)).circle(r).extrude(x1 - x0)


def _x_prism(x0: float, x1: float, pts_yz) -> cq.Workplane:
    """Polygon in the (y, z) plane extruded along +x from x0 to x1."""
    return cq.Workplane("YZ", origin=(x0, 0, 0)).polyline(pts_yz).close().extrude(x1 - x0)


def build_parts_local(p: HingeLidParams) -> dict[str, cq.Shape]:
    ya, za, rk = p.ya, p.za, p.r_k
    segs = p.segments()
    x0, x1 = segs[0][1], segs[-1][2]

    # enclosure: open box + knuckles hanging off the rear wall below the free band
    enc = _box((0, 0, 0), (p.L, p.W, p.H)).cut(_box((p.t, p.t, p.floor), (p.L - p.t, p.W - p.t, p.H + 1)))
    yw, yf, yr = p.W - 0.5, ya - rk, ya + rk          # yw: inside the wall so the union is solid
    z_t = p.H - p.free_band
    z_b = z_t - p.bridge_h
    z_g = z_b - (yr - yw)                              # 45 deg gusset under the bridge
    bracket = [(yw, z_t), (yf, z_t), (yf, za), (yr, za), (yr, z_b), (yw, z_g)]
    for owner, xs, xe in segs:
        if owner == "enclosure":
            enc = enc.union(_x_prism(xs, xe, bracket)).union(_x_cyl(xs, xe, ya, za, rk))
    enc = enc.cut(_x_cyl(x0 - 1, x1 + 1, ya, za, p.r_bore))

    # lid: plate + per lid segment tail, knuckle, rib; frame around the module
    lid = _box((0, 0, p.H), (p.L, p.W, p.H + p.t_lid))
    for (xs, xe), (q0, q1, d) in zip(p.lid_segments(), p.rib_profiles()):
        lid = (lid.union(_box((xs, p.W - 0.5, p.H), (xe, ya + rk, p.H + p.t_lid)))
               .union(_x_cyl(xs, xe, ya, za, rk))
               .union(_box((xs, ya + q0, za - d), (xe, ya + q1, za))))
    lid = lid.cut(_x_cyl(x0 - 1, x1 + 1, ya, za, p.r_bore))
    (mx0, my0, mz0), (mx1, my1, mz1) = p.module_box()
    c, ft = p.frame_clear, p.frame_t
    frame = (_box((mx0 - c - ft, my0 - c - ft, p.H - p.frame_h), (mx1 + c + ft, my1 + c + ft, p.H + 0.5))
             .cut(_box((mx0 - c, my0 - c, p.H - p.frame_h - 1), (mx1 + c, my1 + c, p.H + 0.01))))
    lid = lid.union(frame)

    pin = _x_cyl(x0, x1, ya, za, p.r_pin)
    module = _box((mx0, my0, mz0), (mx1, my1, mz1))
    return {name: wp.val() for name, wp in
            (("enclosure", enc), ("lid", lid), ("hinge_pin", pin), ("lid_module", module))}


def build_parts(p: HingeLidParams) -> dict[str, cq.Shape]:
    """Parts in the world frame (local parts placed with the level's pose)."""
    parts = build_parts_local(p)
    if p.pose is None:
        return parts
    m = p.pose_matrix()
    return {n: kernel.transform_shape(s, m) for n, s in parts.items()}


# ---------------------------------------------------------------- output
def _snap(v) -> list[float]:
    return [round(float(x), 3) + 0.0 for x in np.asarray(v, dtype=float).ravel()]


def _unit(v) -> list[float]:
    v = np.asarray(v, dtype=float).ravel()
    return [round(float(x), 6) + 0.0 for x in v / np.linalg.norm(v)]


def world_box(m, lo, hi) -> dict:
    """Local axis-aligned box [lo, hi] placed by pose m: corner origin + three edge vectors (world)."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    edges = kernel.apply_dirs(m, np.diag(hi - lo))
    return {"origin": _snap(kernel.apply_points(m, lo)[0]), "edges": [_snap(e) for e in edges]}


def bracket_zones(p: HingeLidParams) -> list[dict]:
    """Keep-in boxes of the enclosure knuckle brackets (one pair per enclosure segment): the bridge below the
    free band, including its root inside the wall, and the upright + knuckle behind the wall. Neither box
    touches the free band under the rear wall's outer top edge. `box` is in the local frame, `world` is the
    same box placed with the pose."""
    ya, za, rk = p.ya, p.za, p.r_k
    z_t = p.H - p.free_band
    z_g = round(z_t - p.bridge_h - ((ya + rk) - (p.W - 0.5)), 3)  # bottom of the 45 deg gusset
    m = p.pose_matrix()
    out = []
    for i, (owner, xs, xe) in enumerate(p.segments()):
        if owner != "enclosure":
            continue
        for name, lo, hi in ((f"bracket_{i}_bridge", [xs, round(p.W - 0.5, 3), z_g], [xe, round(ya + rk, 3), round(z_t, 3)]),
                             (f"bracket_{i}_knuckle", [xs, round(ya - rk, 3), round(z_t, 3)], [xe, round(ya + rk, 3), round(za + rk, 3)])):
            out.append({"name": name, "part": "enclosure", "box": [lo, hi], "world": world_box(m, lo, hi)})
    return out


SEAL_ZONE_DEPTH = 0.5      # seal band keep-in zones: this deep into the wall top / lid underside
BORE_ZONE_MARGIN = 0.6     # frozen hinge interface: material within r_bore + this around the axis


def _box_zone(m, name, kind, part, lo, hi, description, parts=None) -> dict:
    lo, hi = [round(float(v), 3) for v in lo], [round(float(v), 3) for v in hi]
    w = world_box(m, lo, hi)
    z = {"name": name, "kind": kind, "part": part, "box": [lo, hi], "description": description,
         "region": {"kind": "box", "origin": w["origin"], "edges": w["edges"]}}
    if parts:
        z["parts"] = parts
    return z


def _axis_cylinder(p: HingeLidParams, m, xs: float, xe: float, r: float) -> dict:
    a, b = kernel.apply_points(m, [[xs, p.ya, p.za], [xe, p.ya, p.za]])
    return {"kind": "cylinder", "p0": _snap(a), "p1": _snap(b), "radius": round(r, 3)}


def zones(p: HingeLidParams) -> list[dict]:
    """All keep-in zones (scenario.json protections.keep_in) and the keep-out zone, world regions at the closed
    pose. `box` (local) is kept for internal use (brief, tests)."""
    m = p.pose_matrix()
    L, W, H, t, d = p.L, p.W, p.H, p.t, SEAL_ZONE_DEPTH
    out = []
    for z in bracket_zones(p):
        out.append(_box_zone(m, z["name"], "keep_in", "enclosure", *z["box"], "enclosure knuckle bracket"))
    for i, ((xs, xe), (q0, q1, dep)) in enumerate(zip(p.lid_segments(), p.rib_profiles())):
        out.append({"name": f"lid_knuckle_{i}", "kind": "keep_in", "part": "lid", "description": "lid hinge knuckle",
                    "region": _axis_cylinder(p, m, xs, xe, p.r_k)})
        out.append(_box_zone(m, f"lid_rib_{i}", "keep_in", "lid", (xs, p.ya + q0, p.za - dep), (xe, p.ya + q1, p.za),
                             "lid knuckle rib (structural)"))
    (mx0, my0, mz0), (mx1, my1, mz1) = p.module_box()
    c, ft = p.frame_clear, p.frame_t
    out.append(_box_zone(m, "lid_module_frame", "keep_in", "lid", (mx0 - c - ft, my0 - c - ft, H - p.frame_h),
                         (mx1 + c + ft, my1 + c + ft, H), "lid module frame"))
    walls = {"front": ((0, 0), (L, t)), "rear": ((0, W - t), (L, W)), "left": ((0, 0), (t, W)), "right": ((L - t, 0), (L, W))}
    for name, ((x0, y0), (x1, y1)) in walls.items():
        out.append(_box_zone(m, f"seal_lid_{name}", "keep_in", "lid", (x0, y0, H), (x1, y1, H + d),
                             "seal band, lid underside over the wall tops"))
    s0, s1x, s1y = t - SEAL_MIN_WIDTH, L - t + SEAL_MIN_WIDTH, W - t + SEAL_MIN_WIDTH   # inner ring only
    inner = {"front": ((s0, s0), (s1x, t)), "rear": ((s0, W - t), (s1x, s1y)),
             "left": ((s0, s0), (t, s1y)), "right": ((L - t, s0), (s1x, s1y))}
    for name, ((x0, y0), (x1, y1)) in inner.items():
        out.append(_box_zone(m, f"seal_enclosure_{name}", "keep_in", "enclosure", (x0, y0, H - d), (x1, y1, H),
                             f"seal band, inner {SEAL_MIN_WIDTH} mm of the wall top"))
    out.append(_box_zone(m, "lid_module_volume", "keep_out", "lid_module", (mx0, my0, mz0), (mx1, my1, mz1),
                         "volume occupied by lid_module (moves with the lid)", parts=["lid", "enclosure"]))
    return out


def interface_regions(p: HingeLidParams) -> list[dict]:
    """Frozen hinge interface: the material around the pin axis (bore + wall, radius r_bore + BORE_ZONE_MARGIN)
    in every knuckle segment of both parts."""
    m = p.pose_matrix()
    return [{"name": f"bore_{o}_{i}", "part": o, "region": _axis_cylinder(p, m, xs, xe, p.r_bore + BORE_ZONE_MARGIN)}
            for i, (o, xs, xe) in enumerate(p.segments())]


def describe(p: HingeLidParams) -> dict:
    """Derived facts needed by tools/checks later: joint, segments, the edge in question, zones, print
    orientation. Joint, edge endpoints, zone `world` boxes and print directions are in the world frame;
    segments' x ranges and `box` / `module_box` are local (internal)."""
    m = p.pose_matrix()
    lo, hi = p.module_box()
    return {
        "joint": {"type": "revolute", "moving": ["lid", "lid_module"], "fixed": ["enclosure", "hinge_pin"],
                  "axis_point": _snap(kernel.apply_points(m, p.axis_point)[0]),
                  "axis_direction": _unit(kernel.apply_dirs(m, AXIS_DIRECTION)[0]),
                  "range_deg": [0.0, OPEN_ANGLE_DEG], "step_deg": STEP_DEG},
        "segments": [{"part": o, "x": [xs, xe]} for o, xs, xe in p.segments()],
        "rear_outer_top_edge": {"x": [0.0, p.L], "y": p.W, "z": p.H,
                                "world": [_snap(v) for v in kernel.apply_points(m, [[0.0, p.W, p.H], [p.L, p.W, p.H]])]},
        "module_box": [list(v) for v in (lo, hi)],
        "module_box_world": world_box(m, lo, hi),
        "keep_in": bracket_zones(p),
        "zones": zones(p),
        "interface_regions": interface_regions(p),
        "frame_axes": [_unit(kernel.apply_dirs(m, e)[0]) for e in np.eye(3)],
        "wall_top_plane": {"point": _snap(kernel.apply_points(m, (0.0, 0.0, p.H))[0]),
                           "normal": _unit(kernel.apply_dirs(m, (0.0, 0.0, 1.0))[0])},
        "print_orientation": {n: {"rule": PRINT_RULE[n], "build_up": _unit(kernel.apply_dirs(m, PRINT_UP_LOCAL[n])[0])}
                              for n in PRINT_RULE},
        "pose": None if p.pose is None else asdict(p.pose) | {"matrix": [_unit(r[:3]) + [round(r[3], 6)]
                                                                         for r in m]},
    }


def task_spec(f: dict, enclosure_volume: float, level: str) -> dict:
    """Grader parameters: S1, S3 (factors of the level x V_ref; the agent is told the factors only) and reward."""
    v_ref = f["V_ref_mm3"]
    full, zero = S3_FACTORS[level]
    pct = lambda v: round(100.0 * v / enclosure_volume, 4)  # noqa: E731
    return {
        "S1": s1_spec(),
        "S3": {"level": level, "enclosure_volume_mm3": round(enclosure_volume, 3), "V_ref_mm3": v_ref,
               "full_factor": full, "zero_factor": zero,
               "full_points_up_to_mm3": round(full * v_ref, 4), "zero_points_at_mm3": round(zero * v_ref, 4),
               "full_points_up_to_pct": pct(full * v_ref), "zero_points_at_pct": pct(zero * v_ref)},
        "reward": {"S1_not_met_progress_weight": REWARD_POLICY.progress_weight,
                   "S1_met_base": REWARD_POLICY.met_base, "S1_met_weights": REWARD_POLICY.weights},
    }


def params_from_info(info: dict) -> HingeLidParams:
    """HingeLidParams back from a params.json dict."""
    d = dict(info["params"])
    if d.get("ribs") is not None:
        d["ribs"] = tuple(tuple(r) for r in d["ribs"])
    if d.get("pose") is not None:
        d["pose"] = Pose(**{**d["pose"], "offset": tuple(d["pose"]["offset"])})
    return HingeLidParams(**d)


def generate(seed: int, level: str = "L1"):
    p, f, rejected = resolve_seed(seed, level)
    return p, f, rejected, build_parts(p)


def seed_dir(out_dir, level: str, seed: int) -> Path:
    return Path(out_dir) / level / f"seed_{seed:04d}"


def write(seed: int, out_dir, level: str = "L1") -> Path:
    p, f, rejected, parts = generate(seed, level)
    d = seed_dir(out_dir, level, seed)
    d.mkdir(parents=True, exist_ok=True)
    volumes = {}
    for name, shape in parts.items():
        if not shape.isValid():
            raise RuntimeError(f"seed {seed} {level}: {name} is not a valid solid")
        export_step(shape, d / f"{name}.step")
        volumes[name] = round(shape.Volume(), 3)
    info = {"scenario": "hinge_lid", "level": level, "seed": seed, "source_seed": p.seed,
            "rejected_source_seeds": rejected, "params": asdict(p), **describe(p), "volumes_mm3": volumes,
            # hidden (evaluation and tests only, never shown to agents): the reference fix in the world frame
            "reference_ops": relief_ops(p, reference_sizes(f)),
            "feasibility": copy.deepcopy(f), "spec": task_spec(f, volumes["enclosure"], level)}
    (d / "params.json").write_text(json.dumps(info, indent=2))
    return d


def parse_seeds(text: str) -> list[int]:
    out = []
    for part in text.split(","):
        lo, _, hi = part.partition("-")
        out.extend(range(int(lo), int(hi or lo) + 1))
    return out


def parse_levels(text: str) -> list[str]:
    out = [x.strip().upper() for x in text.split(",") if x.strip()]
    bad = [x for x in out if x not in LEVELS]
    if bad:
        raise SystemExit(f"unknown level(s) {bad}, expected {LEVELS}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--level", default="L1", help="L1, L2, L3 or a comma list")
    ap.add_argument("--seeds", default="0")
    ap.add_argument("--out", default="output/hinge_lid")
    args = ap.parse_args(argv)
    for level in parse_levels(args.level):
        for s in parse_seeds(args.seeds):
            d = write(s, args.out, level)
            info = json.loads((d / "params.json").read_text())
            f = info["feasibility"]
            ribs = "  ".join(f"{r['best']['d_top']}x{r['best']['d_side']}" for r in f["ribs"])
            pose = info["pose"]
            print(f"{level} seed {s} (source {info['source_seed']}): {d}  pred={f['predicted_first_collision_deg']} "
                  f"deg  ribs [{ribs}]  V_ref={f['V_ref_mm3']}  V_full_edge={f['V_full_edge_mm3']}  "
                  f"V_identical={f['V_identical_mm3']}  ratio={f['relief_ratio']}"
                  + (f"  pose yaw={pose['yaw_deg']} tilt={pose['tilt_deg']}@{pose['tilt_axis_deg']} "
                     f"offset={pose['offset']}" if pose else ""))


if __name__ == "__main__":
    main()
