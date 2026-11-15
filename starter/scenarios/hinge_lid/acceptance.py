"""Task 4 acceptance: the 2c/2d variant table (dev_sweep variants, real B-rep ops) graded by the NEW generic
checks, compared with the rewards in docs/acceptance_2c.txt (graded by the 2c dev approximations).

Run: python -m scenarios.hinge_lid.acceptance --level L1,L2,L3 --seeds 0-9 [--out docs/acceptance_4.txt]
"""
from __future__ import annotations

import argparse
import re
import time
import warnings
from pathlib import Path

from scenarios.hinge_lid import dev_sweep, generator

OLD = Path(__file__).resolve().parents[2] / "docs" / "acceptance_2c.txt"
ROW = re.compile(r"^\s+(\d+) (original|reference|full_edge|identical|exact_length|side_0\.7x|symmetric)\s+(.*)$")


def old_rewards(path=OLD) -> dict:
    """{(level, seed, variant): reward} from the 2c table ('OP ERROR' rows -> 'error')."""
    out, level = {}, None
    for line in Path(path).read_text().splitlines():
        m = re.match(r"^===== (L\d):", line)
        if m:
            level = m.group(1)
            continue
        m = ROW.match(line)
        if m and level:
            rest = m.group(3)
            out[level, int(m.group(1)), m.group(2)] = "error" if "OP ERROR" in rest else float(rest.split()[-1])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--level", default="L1,L2,L3")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--gen", default="output/hinge_lid")
    ap.add_argument("--out", default="docs/acceptance_4.txt")
    a = ap.parse_args(argv)
    warnings.filterwarnings("ignore")
    old = old_rewards()
    t0 = time.perf_counter()
    lines = ["# Task 4 acceptance: 2c/2d variants graded by the generic checks (cadfix/checks via",
             "# scenarios/hinge_lid/spec.py) vs the 2c dev grader (docs/acceptance_2c.txt).",
             "# new = reward now, old = reward in acceptance_2c.txt, failed = failed gates / S2 now.", ""]
    diffs, rows = [], []
    for level in generator.parse_levels(a.level):
        lines.append(f"===== {level} =====")
        lines.append(f"{'seed':>4} {'variant':<12} {'new':>6} {'old':>6} {'diff':>7}  {'S1':<4} {'x_ref':>6} failed")
        for seed in generator.parse_seeds(a.seeds):
            r = dev_sweep.run_seed(level, seed, a.gen, side_collisions=False)
            for name, v in r["variants"].items():
                o = old.get((level, seed, name))
                if v is None:
                    lines.append(f"{seed:>4} {name:<12} {'n/a':>6} {str(o):>6}")
                    continue
                if v.get("error"):
                    lines.append(f"{seed:>4} {name:<12} {'error':>6} {str(o):>6}          {v['error'][:60]}")
                    continue
                failed = [k for k, ok in v["gates"].items() if not ok]
                failed += [k for k in ("S2_min_wall", "S2_overhang") if not v["checks"][k]["passed"]]
                d = None if not isinstance(o, float) else round(v["reward"] - o, 3)
                rows.append((level, seed, name, v["reward"], o))
                if d is None or abs(d) > 0.0015:
                    diffs.append((level, seed, name, v["reward"], o, failed))
                lines.append(f"{seed:>4} {name:<12} {v['reward']:>6.3f} {str(o):>6} "
                             f"{('' if d is None else f'{d:+.3f}'):>7}  {('ok' if v['s1']['met'] else 'FAIL'):<4} "
                             f"{v['ratio_to_ref']:>6.2f} {','.join(failed)}")
        lines.append("")
    lines.append("===== Summary per level x variant: new reward min / mean / max =====")
    for level in generator.parse_levels(a.level):
        for name in dev_sweep.VARIANTS:
            rw = [r[3] for r in rows if r[0] == level and r[2] == name]
            if rw:
                lines.append(f"{level} {name:<12} {min(rw):.3f} / {sum(rw) / len(rw):.3f} / {max(rw):.3f}  (n={len(rw)})")
    lines.append("")
    lines.append(f"===== Differences > 0.0015 vs acceptance_2c.txt: {len(diffs)} =====")
    for level, seed, name, new, o, failed in diffs:
        lines.append(f"{level} seed {seed} {name:<12} new {new:.3f} old {o}  failed: {','.join(failed) or '-'}")
    lines.append(f"\ntotal {time.perf_counter() - t0:.1f} s")
    text = "\n".join(lines) + "\n"
    Path(a.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
