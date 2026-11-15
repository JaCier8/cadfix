"""instruction.md for one hinge_lid task, rendered from the PUBLIC task files only (task.json + spec.json): bug
report, parts, coordinate conventions, the hinge, zones, every requirement with its threshold, the scoring rules
and how the tools / episode work. Neutral wording: no cause, no fix, no reference numbers (tests/test_instruction.py).

Run: python -m scenarios.hinge_lid.instruction --task-dir output/tasks/L2/seed_0000/task
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _v(v, nd=3) -> str:
    return "(" + ", ".join(f"{float(x):.{nd}f}".rstrip("0").rstrip(".") if nd == 3 else f"{float(x):.{nd}f}"
                           for x in v) + ")"


def _region(r: dict) -> str:
    if r["kind"] == "box":
        e = r["edges"]
        return f"box, corner {_v(r['origin'])}, edges {_v(e[0])} {_v(e[1])} {_v(e[2])}"
    return f"cylinder, axis {_v(r['p0'])} -> {_v(r['p1'])}, radius {r['radius']:g}"


def render(task: dict, spec: dict, task_path: str = "/task", out_path: str = "/output") -> str:
    j = task["joint"]
    aligned = all(max(abs(c) for c in d) > 0.9999 for d in [j["axis_direction"]] +
                  [p["print"]["build_up"] for p in task["parts"].values() if "print" in p])
    cost = spec.get("test_fit_cost", {})
    L = []
    w = L.append
    w("# Fix the hinged lid\n")
    w(f"**Bug report:** {task['bug_report']}\n")
    w("You get a 3D-printable assembly as B-rep solids and CAD tools. Change the editable parts so that the "
      "assembly meets every requirement below. The result is scored automatically when the episode ends.\n")
    w("## Parts\n")
    for n, p in task["parts"].items():
        pr = p.get("print")
        w(f"- `{n}` ({'editable' if p['editable'] else 'fixed'}): {p['role']}"
          + (f". Printed {pr['rule']} (build direction {_v(pr['build_up'], 4)})." if pr else "."))
    w("")
    w("## Coordinates and the hinge\n")
    w(f"Units: {task.get('units', 'mm, degrees')}. All coordinates are world coordinates"
      + ("." if aligned else "; the assembly is NOT aligned with the world axes, so work with the directions the "
                             "tools report (face normals, edge directions, the joint axis)."))
    w(f"The `{j['name']}` joint is {j['type']}: {', '.join(j['moving'])} rotate together about the axis through "
      f"{_v(j['axis_point'])} with direction {_v(j['axis_direction'], 4)}; positive angles open the lid "
      f"(right-hand rule), 0 deg = closed, range {j['range_deg'][0]:g}..{j['range_deg'][1]:g} deg. "
      f"Fixed: {', '.join(j['fixed'])}.\n")
    w("## Protected zones\n")
    w("Keep-in zones (each must keep >= 99 % of its original material):")
    for z in task["zones"]:
        if z["kind"] == "keep_in":
            w(f"- `{z['name']}` ({z['part']}; {z.get('description', '')}): {_region(z['region'])}")
    w("\nKeep-out zones (no new material may enter):")
    for z in task["zones"]:
        if z["kind"] == "keep_out":
            w(f"- `{z['name']}` ({z.get('description', '')}; parts {', '.join(z.get('parts', []))}): {_region(z['region'])}")
    w("")
    w("## Requirements and scoring\n")
    w("Gates: if any gate fails, the reward is 0.")
    for c in spec["checks"]:
        if c["role"] == "gate":
            w(f"- `{c['id']}`: {c['description']}")
    w("\nObjective:")
    for c in spec["checks"]:
        if c["role"] == "objective":
            w(f"- `{c['id']}`: {c['description']}")
    w("\nScores:")
    for c in spec["checks"]:
        if c["role"] == "score":
            w(f"- `{c['id']}`: {c['description']}")
    r = spec["reward"]
    w(f"\nReward: {r['formula']}. Printability = 1 if both S2 checks pass, else 0. Minimal change = the S3 score. "
      f"Objective progress = 0.5 * angle progress + 0.5 * clearance progress, where angle progress = (largest angle up "
      f"to which the S1 rules hold - the original's) / (110 - the original's) and clearance progress = min clearance "
      f"from 10 deg / 0.3 (0 if anything overlaps).")
    w(f"test_fit: the first {cost.get('free_calls', 0)} calls are free, then each call costs {cost.get('per_call', 0):g} "
      f"reward, at most {cost.get('cap', 0):g} in total. Single checks (run_check_<id>) are free.\n")
    w("## Tools and the episode\n")
    w("All tools are on the `cadfix` MCP server. Start with `get_task`: it returns the same information as data "
      "(parts, joint, zones with regions, every check with its parameters).")
    w("- Inspect: `list_parts`, `part_info`, `list_edges`, `list_faces`, `find_edges_near`, `find_faces_near`, "
      "`measure` (gap and interference between two parts at any joint angle), `section` (a part cut by any plane).")
    w("- Edit: the edit operations in the server's tool list work on the editable parts. Every edit returns the "
      "part's new edge and face lists; edge and face ids change after every edit. `undo` reverts the last edit.")
    w("- Check: one `run_check_<id>` per requirement (free), `test_fit` = all of them.")
    w("- `submit` ends the episode. Tool calls are capped at 150.")
    w(f"\nThe editable parts are saved to `{out_path}/parts/` after every edit and are graded as saved when the episode "
      f"ends. The public task files (the same data the tools use) are in `{task_path}`.")
    return "\n".join(L) + "\n"


def render_dir(task_dir, task_path: str = "/task", out_path: str = "/output") -> str:
    d = Path(task_dir)
    return render(json.loads((d / "task.json").read_text()), json.loads((d / "spec.json").read_text()),
                  task_path, out_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task-dir", required=True)
    a = ap.parse_args(argv)
    print(render_dir(a.task_dir), end="")


if __name__ == "__main__":
    main()
