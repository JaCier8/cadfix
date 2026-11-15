"""Generic checks (cadfix/checks) on small synthetic assemblies: each check passes on the original and fails on
the edit it is meant to catch."""
import cadquery as cq
import pytest

from cadfix.core import registry
from cadfix.core.assembly import Assembly, Joint, Part, Region, Zone
from cadfix.core.registry import CheckContext

FRAME = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def box(lo, hi):
    return cq.Workplane("XY").box(*[h - l for l, h in zip(lo, hi)], centered=False).translate(tuple(lo)).val()


def cut(shape, lo, hi):
    return shape.cut(box(lo, hi))


def make(parts: dict, zones=(), joint=None) -> Assembly:
    ps = {n: Part(n, s, editable=(n != "fixed"), build_up=(0, 0, 1)) for n, s in parts.items()}
    joint = joint or Joint("j", ("lid",) if "lid" in parts else (), ("fixed",) if "fixed" in parts else (),
                           (0, 0, 0), (1, 0, 0), (0, 90))
    return Assembly(ps, joint, list(zones))


def run(type_name, orig: Assembly, cur: Assembly, **params):
    return registry.get(type_name)(CheckContext(cur, orig), **params)


def zone_box(name, kind, part, lo, hi, parts=()):
    return Zone(name, kind, part, Region("box", origin=tuple(lo),
                                         edges=((hi[0] - lo[0], 0, 0), (0, hi[1] - lo[1], 0), (0, 0, hi[2] - lo[2]))), parts)


BLOCK = box((0, 0, 0), (20, 10, 10))


def test_valid_solid_rejects_two_pieces():
    a = make({"part": BLOCK})
    assert run("valid_solid", a, a, parts=["part"]).passed
    split = cut(BLOCK, (9, -1, -1), (11, 11, 11))
    res = run("valid_solid", a, a.with_shapes({"part": split}), parts=["part"])
    assert not res.passed and "2 solids" in res.metrics["part"]


def test_keep_in_and_keep_out():
    zones = [zone_box("keep", "keep_in", "part", (0, 0, 0), (5, 10, 10)),
             zone_box("out", "keep_out", "part", (30, 0, 0), (35, 10, 10), parts=("part",))]
    a = make({"part": BLOCK}, zones)
    assert run("keep_in", a, a).passed and run("keep_out", a, a).passed
    small = cut(BLOCK, (0, 0, 9.5), (5, 10, 10))                 # 5 % of the zone's material
    assert not run("keep_in", a, a.with_shapes({"part": small})).passed
    tiny = cut(BLOCK, (0, 0, 9.95), (5, 10, 10))                 # 0.5 %: still >= 99 %
    assert run("keep_in", a, a.with_shapes({"part": tiny})).passed
    grown = BLOCK.fuse(box((20, 0, 0), (31, 10, 10)))
    assert not run("keep_out", a, a.with_shapes({"part": grown})).passed


def test_interface_frozen_cylinder_region():
    bored = BLOCK.cut(cq.Workplane("YZ").circle(1.0).extrude(20).translate((0, 5, 5)).val())
    regions = [{"name": "bore", "part": "part",
                "region": {"kind": "cylinder", "p0": [0, 5, 5], "p1": [20, 5, 5], "radius": 1.6}}]
    a = make({"part": bored})
    assert run("interface_frozen", a, a, regions=regions).passed
    far = cut(bored, (0, 0, 9), (20, 10, 10))                    # outside the region
    assert run("interface_frozen", a, a.with_shapes({"part": far}), regions=regions).passed
    filled = bored.fuse(cq.Workplane("YZ").circle(1.0).extrude(5).translate((0, 5, 5)).val())
    assert not run("interface_frozen", a, a.with_shapes({"part": filled}), regions=regions).passed


def test_contact_width_ring():
    ring = box((0, 0, 0), (20, 20, 10)).cut(box((3, 3, 1), (17, 17, 11)))     # walls 3 mm
    plate = box((0, 0, 10), (20, 20, 12))
    a = make({"lower": ring, "upper": plate})
    kw = dict(lower="lower", upper="upper", plane_point=[0, 0, 10], plane_normal=[0, 0, 1], min_width_mm=1.5)
    res = run("contact_width", a, a, **kw)
    assert res.passed and res.metrics["width_mm"] == pytest.approx(3.0, abs=2e-3)
    edge = cut(ring, (5, 18.5, 9), (8, 21, 11))                  # outer 1.5 of a 3 mm wall top: 1.5 left
    assert run("contact_width", a, a.with_shapes({"lower": edge}), **kw).passed
    notched = cut(ring, (5, 18.0, 9), (8, 21, 11))               # 1.0 mm left
    res = run("contact_width", a, a.with_shapes({"lower": notched}), **kw)
    assert not res.passed and res.metrics["width_mm"] == pytest.approx(1.0, abs=2e-3)
    broken = cut(ring, (5, 16, 9), (8, 21, 11))                  # wall top cut through: no ring
    assert run("contact_width", a, a.with_shapes({"lower": broken}), **kw).metrics["width_mm"] == 0.0


def test_envelope_and_volume_limit():
    a = make({"part": BLOCK})
    kw = dict(parts=["part"], frame=FRAME, tol_mm=0.5, max_change_pct=15.0)
    assert run("envelope", a, a, **kw).passed
    moved = BLOCK.translate((1.0, 0, 0))
    assert not run("envelope", a, a.with_shapes({"part": moved}), **kw).passed
    gutted = cut(BLOCK, (1, 1, 1), (19, 9, 9.5))                 # same envelope, 69 % removed
    res = run("envelope", a, a.with_shapes({"part": gutted}), **kw)
    assert not res.passed and res.metrics["part"]["max_shift_mm"] == 0.0


def test_min_wall_new_thin_walls_only():
    shell = box((0, 0, 0), (20, 20, 10)).cut(box((3, 3, 1), (17, 17, 11)))
    a = make({"part": shell})
    kw = dict(parts=["part"], frame=FRAME, min_mm=1.2, feature_mm=0.2)
    assert run("min_wall", a, a, **kw).metrics["part"] == "unchanged"
    ok = cut(shell, (5, 17, 5), (10, 18.5, 11))                  # wall 3 -> 1.5 mm
    assert run("min_wall", a, a.with_shapes({"part": ok}), **kw).passed
    thin = cut(shell, (5, 17, 5), (10, 19.2, 11))                # wall 3 -> 0.8 mm
    res = run("min_wall", a, a.with_shapes({"part": thin}), **kw)
    assert not res.passed and res.metrics["thinnest_new_mm"] == pytest.approx(0.8, abs=0.05)
    sliver = cut(shell, (5, 17, 5), (10, 19.95, 11))             # 0.05 mm left: below the feature size
    assert run("min_wall", a, a.with_shapes({"part": sliver}), **kw).passed


def test_overhang_only_new_downward_faces_count():
    a = make({"part": BLOCK})
    kw = dict(parts=["part"], max_angle_deg=45.0, feature_mm=0.2, tol_mm2=0.01)
    top_notch = cut(BLOCK, (5, -1, 8), (10, 11, 11))             # open from above: no overhang
    assert run("overhang", a, a.with_shapes({"part": top_notch}), **kw).passed
    pocket = cut(BLOCK, (5, -1, 0), (10, 11, 4))                 # tunnel from below: 5 x 10 ceiling
    res = run("overhang", a, a.with_shapes({"part": pocket}), **kw)
    assert not res.passed and res.metrics["new_overhang_mm2"] == pytest.approx(50.0, abs=0.5)


def test_volume_change_score_needs_the_reference():
    a = make({"part": BLOCK})
    c = a.with_shapes({"part": cut(BLOCK, (0, 0, 9), (10, 10, 10))})    # 100 mm3
    kw = dict(parts=["part"], full_factor=1.15, zero_factor=2.0)
    res = run("volume_change", a, c, **kw)
    assert res.score is None and res.metrics["changed_mm3"] == pytest.approx(100.0, abs=0.01)
    assert run("volume_change", a, c, reference_mm3=100.0, **kw).score == 1.0
    assert run("volume_change", a, c, reference_mm3=50.0, **kw).score == 0.0
    assert run("volume_change", a, c, reference_mm3=100 / 1.575, **kw).score == pytest.approx(0.5, abs=1e-3)


def test_collision_free_and_sweep_progress():
    fixed = box((-5, -20, -10), (5, 20, -1))                     # block 1 mm below the axis (x through the origin)
    lid = box((-5, -0.25, 0), (5, 0.25, 8))                      # bar standing on the axis
    j = Joint("j", ("lid",), ("fixed",), (0, 0, 0), (1, 0, 0), (0, 120))
    a = make({"lid": lid, "fixed": fixed}, joint=j)
    kw = dict(clearance_mm=0.3, clearance_from_deg=10.0, step_deg=5.0)
    assert run("collision_free", a, a, angle_deg=0.0).passed
    assert not run("collision_free", a, a, angle_deg=120.0).passed
    res = run("sweep_clearance", a, a, **kw)
    assert not res.passed and 80 <= res.metrics["ok_until"] < 100 and res.score == 0.0   # progress vs itself
    stub = cut(lid, (-6, -1, 0.5), (6, 1, 9))                   # 0.5 mm stub: always >= 0.44 mm away
    res = run("sweep_clearance", a, a.with_shapes({"lid": stub}), **kw)
    assert res.passed and res.score == 1.0
    half = cut(lid, (-6, -1, 1.2), (6, 1, 9))                    # 1.2 mm: hits later, partial progress
    res = run("sweep_clearance", a, a.with_shapes({"lid": half}), **kw)
    assert not res.passed and 0.0 < res.score < 1.0
