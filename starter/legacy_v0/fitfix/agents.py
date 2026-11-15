"""Scripted agents. All act only through env.call(...), i.e. the same tools the LLM gets over MCP.

  do_nothing  - submits immediately (judging baseline)
  stop_early  - looks around once, then submits (judging baseline)
  oracle      - reads hidden/ and applies the exact inverse of the injected defect (upper bound / grader test)
  solver      - heuristic reference: diagnoses with tools only, never reads hidden/
"""
from __future__ import annotations

import json
from pathlib import Path


def do_nothing(env, hidden=None):
    env.call("submit")


def stop_early(env, hidden=None):
    env.call("get_task")
    env.call("check_interference", part_a="enclosure", part_b="usb_plug")
    env.call("submit")


def oracle(env, hidden: dict):
    lo, hi = hidden["opening_broken"]
    w = hidden["wall"]
    env.call("add_box", min=[0.0, lo[1], lo[2]], max=[w, hi[1], hi[2]])
    lo, hi = hidden["opening_correct"]
    env.call("subtract_box", min=lo, max=hi)
    env.call("submit")


def solver(env, hidden=None, clearance=0.3):
    """Reference strategy an engineer would follow, using only tools."""
    task = env.call("get_task")
    band = task["constraints"]["clearance_mm"]
    clearance = min(max(clearance, band[0] + 0.05), band[1] - 0.05)

    hit = env.call("check_interference", part_a="enclosure", part_b="usb_plug")
    if not hit["colliding"]:
        env.call("submit")
        return
    # 1. Where is the wall the plug passes through? The overlap bbox spans the wall along x.
    x0, x1 = hit["overlap_bbox_min"][0], hit["overlap_bbox_max"][0]
    xm = (x0 + x1) / 2
    # 2. Plug shell profile in that wall plane.
    shell = [l for l in env.call("section", part="usb_plug", axis="x", value=xm)["loops"] if not l["is_hole"]]
    s = shell[0]
    (sy0, sz0), (sy1, sz1) = s["min"], s["max"]
    # 3. Existing (wrong) opening near the plug.
    holes = env.call("find_holes", part="enclosure", axis="x", value=xm)["loops"]
    cy, cz = (sy0 + sy1) / 2, (sz0 + sz1) / 2
    holes.sort(key=lambda h: (h["center"][0] - cy) ** 2 + (h["center"][1] - cz) ** 2)
    old = holes[0]
    # 4. Fill the old opening through the wall thickness, then cut the right one.
    env.call("add_box", min=[x0, old["min"][0], old["min"][1]], max=[x1, old["max"][0], old["max"][1]])
    env.call("subtract_box", min=[x0 - 0.5, sy0 - clearance, sz0 - clearance],
             max=[x1 + 0.5, sy1 + clearance, sz1 + clearance])
    # 5. Verify cheaply, then once with the expensive check.
    for other in ("usb_plug", "pcb", "lid"):
        r = env.call("check_interference", part_a="enclosure", part_b=other)
        if r["colliding"]:
            env.call("undo"), env.call("undo")
            break
    env.call("check_printability")
    env.call("test_fit")
    env.call("submit")


AGENTS = {"do_nothing": do_nothing, "stop_early": stop_early, "oracle": oracle, "solver": solver}


def load_hidden(task_dir: Path):
    p = Path(task_dir) / "hidden" / "params.json"
    return json.loads(p.read_text()) if p.exists() else None
