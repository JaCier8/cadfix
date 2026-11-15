"""Acceptance properties of the 2c variant table (M6) on a few seeds per level, 3D with real B-rep operations.
The full table (seeds 0-9, all variants, side collisions) is `python -m scenarios.hinge_lid.dev_sweep`; its
numbers are in docs/PROGRESS.md."""
import pytest

from cadfix.core.reward import linear_score
from marks import SLOW
from scenarios.hinge_lid import dev_sweep, generator

pytestmark = SLOW   # full 3D variant table, all levels

CASES = [(lv, s) for lv in generator.LEVELS for s in (0, 1)]


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("acceptance")


@pytest.fixture(scope="module")
def rows(out_dir):
    cache = {}

    def get(level, seed):
        if (level, seed) not in cache:
            cache[level, seed] = dev_sweep.run_seed(level, seed, out_dir, side_collisions=(seed == 0))
        return cache[level, seed]
    return get


@pytest.mark.parametrize("level,seed", CASES)
def test_variant_rewards(level, seed, rows):
    v = rows(level, seed)["variants"]
    full, zero = generator.S3_FACTORS[level]
    assert v["original"]["reward"] == 0.0
    assert v["reference"]["reward"] == 1.0
    assert v["side_0.7x"]["reward"] < 0.25 and not v["side_0.7x"]["s1"]["met"]
    fe = v["full_edge"]
    assert fe["s1"]["met"] and all(fe["gates"].values())
    assert fe["s3"] == pytest.approx(linear_score(fe["ratio_to_ref"], full, zero), abs=1e-6)
    if level == "L1":
        assert fe["reward"] == 1.0                                # 3.2-4.7 x V_ref < 5x: full points (P2)
    else:
        assert fe["reward"] == pytest.approx(0.4)                 # ~3-5 x V_ref: S3 = 0
    ident = v["identical"]
    assert ident["s1"]["met"] and all(ident["gates"].values())
    if level == "L3":                                             # draw needs >= 1.4 x V_ref (P3)
        assert ident["ratio_to_ref"] >= generator.L3_MIN_IDENTICAL_RATIO - 0.01 and ident["reward"] <= 0.83
    else:
        assert ident["reward"] == 1.0                             # identical ribs: same as the reference


@pytest.mark.parametrize("level,seed", CASES)
def test_reliefs_exactly_as_long_as_the_rib_fail_s1(level, seed, rows):
    v = rows(level, seed)["variants"]["exact_length"]
    assert not v["s1"]["met"] and v["s1"]["min_clearance"] < 0.3   # rib ends rub along x
    assert v["reward"] < 0.25


@pytest.mark.parametrize("level", generator.LEVELS)
def test_pin_module_brackets_never_collide(level, rows):
    for name, v in rows(level, 0)["variants"].items():
        if v and not v.get("error"):
            assert max(v["side_collisions"].values()) == 0.0, (name, v["side_collisions"])
