"""Generator output (output/hinge_lid/<L>/seed_NNNN, with hidden data) -> a task:

  <root>/<L>/seed_NNNN/task/       PUBLIC (goes into the agent's container): task.json, spec.json, parts/*.step
  <root>/<L>/seed_NNNN/pristine/   PRIVATE (verifier only): parts/*.step (copies), grader.json (V_ref)
  <root>/<L>/seed_NNNN/pristine/reference/parts/<editable>.step
                                   PRIVATE: editable parts with the hidden reference fix applied; only the 3D viewer
                                   (cadfix.viz, humans) reads it, the grader never does

task.json has no generator parameters, no pose, no feasibility data and no reference fix.

Run: python -m scenarios.hinge_lid.task --level L1,L2,L3 --seeds 0-9 [--gen output/hinge_lid] [--out output/tasks]
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from cadfix.core import kernel
from cadfix.ops.edit import apply_ops
from scenarios.hinge_lid import generator as gen
from scenarios.hinge_lid import spec as hl_spec

SCENARIO_JSON = Path(__file__).resolve().parents[2] / "docs" / "scenario.json"
BUG_REPORT = "The lid jams while opening and cannot reach 110 deg. The closed position is fine."


def task_dict(info: dict) -> dict:
    sc = json.loads(SCENARIO_JSON.read_text())
    parts = {}
    for n in gen.PART_NAMES:
        d = {"editable": sc["parts"][n]["editable"], "role": sc["parts"][n]["role"], "file": f"parts/{n}.step"}
        if n in info["print_orientation"]:
            d["print"] = info["print_orientation"][n]
        parts[n] = d
    j = info["joint"]
    joint = {"name": "hinge", "type": "revolute", "moving": j["moving"], "fixed": j["fixed"],
             "axis_point": j["axis_point"], "axis_direction": j["axis_direction"], "range_deg": j["range_deg"],
             "step_deg": j["step_deg"],
             "description": "the lid (with lid_module) rotates about the hinge pin axis; positive angles open it "
                            "(right-hand rule about axis_direction); 0 deg = closed"}
    zones = [{k: z[k] for k in ("name", "kind", "part", "region", "description", "parts") if k in z}
             for z in info["zones"]]
    return {"scenario": "hinge_lid", "level": info["level"], "seed": info["seed"], "units": "mm, degrees",
            "bug_report": BUG_REPORT, "parts": parts, "joint": joint, "zones": zones}


def task_dir(root, level: str, seed: int) -> Path:
    return Path(root) / level / f"seed_{seed:04d}"


def write_task(level: str, seed: int, gen_out="output/hinge_lid", root="output/tasks") -> Path:
    src = gen.seed_dir(gen_out, level, seed)
    if not (src / "params.json").exists():
        gen.write(seed, gen_out, level)
    info = json.loads((src / "params.json").read_text())
    if "zones" not in info:          # params.json from before task 4: regenerate the description only
        info |= gen.describe(gen.params_from_info(info))
        (src / "params.json").write_text(json.dumps(info, indent=2))
    out = task_dir(root, level, seed)
    if out.exists():
        shutil.rmtree(out)
    pub, pri = out / "task", out / "pristine"
    (pub / "parts").mkdir(parents=True)
    (pri / "parts").mkdir(parents=True)
    for n in gen.PART_NAMES:
        shutil.copy(src / f"{n}.step", pub / "parts" / f"{n}.step")
        shutil.copy(src / f"{n}.step", pri / "parts" / f"{n}.step")
    write_reference(info, src, pri)
    (pub / "task.json").write_text(json.dumps(task_dict(info), indent=2))
    (pub / "spec.json").write_text(json.dumps(hl_spec.public_spec(info), indent=2))
    (pri / "grader.json").write_text(json.dumps({"level": level, "seed": seed,
                                                 "private": hl_spec.private_values(info)}, indent=2))
    return out


def write_reference(info: dict, src: Path, pri: Path) -> None:
    """pristine/reference/parts/<editable>.step = original parts + the generator's hidden reference ops (viewer only)."""
    shapes = {n: kernel.import_step(src / f"{n}.step") for n in gen.PART_NAMES}
    editable = [n for n, d in task_dict(info)["parts"].items() if d["editable"]]
    new, _ = apply_ops(shapes, info["reference_ops"], editable, default_part="enclosure")
    (pri / "reference" / "parts").mkdir(parents=True, exist_ok=True)
    for n in editable:
        kernel.export_step(new[n], pri / "reference" / "parts" / f"{n}.step")


def ensure_task(level: str, seed: int, gen_out="output/hinge_lid", root="output/tasks") -> Path:
    out = task_dir(root, level, seed)
    if not (out / "pristine" / "grader.json").exists() or not (out / "pristine" / "reference" / "parts").exists():
        write_task(level, seed, gen_out, root)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--level", default="L1,L2,L3")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--gen", default="output/hinge_lid")
    ap.add_argument("--out", default="output/tasks")
    a = ap.parse_args(argv)
    for level in gen.parse_levels(a.level):
        for s in gen.parse_seeds(a.seeds):
            print(write_task(level, s, a.gen, a.out))


if __name__ == "__main__":
    main()
