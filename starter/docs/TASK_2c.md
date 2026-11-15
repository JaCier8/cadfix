# Task 2c: difficulty levels L1-L3 (long autonomous run)

Read CLAUDE.md and docs/scenario.json (version 0.6-levels) first: `levels`, `spec.score`, `spec.reward`,
`spec.disclosure`, `agent_interface.edit_operations`, `randomisation`, `expected_good_fix`, `expected_bad_fixes`.

## Why

A weak model solved L1 seed 0 in two attempts with one full-edge chamfer: two numbers plus precise test_fit
feedback is a guided search, not reasoning. The better engineering fix is LOCAL: relieve the rear wall only where
each rib passes. L2 and L3 make that, and per-rib sizing in a rotated frame, the decisions that matter.

## Working mode for this task (overrides "wait for approval" in CLAUDE.md)

The user is away for several hours.
- Write your plan to `docs/PLAN_2c.md`, then start without waiting.
- Work through the milestones below in order. After each one: `pytest -q` green, then
  `git add -A && git commit -m "2c Mx: <what>"`, and append a short Polish note to `docs/PROGRESS.md`.
- Design questions that the spec does not answer: choose the option most consistent with docs/scenario.json, write it
  to `docs/DECISIONS.md` (question, options, choice, why), and continue.
- STOP and write a clear report at the top of `docs/PROGRESS.md` only if something makes the spec impossible or
  meaningless (like the earlier stop-window finding). Do not tune numbers to make an acceptance line pass: report
  what really happens.
- Never edit docs/scenario.json. Put proposed spec changes into `docs/DECISIONS.md` under "Spec change proposals".
- Keep L1 working exactly as before (all existing tests must still pass or be updated with a reason in DECISIONS).

## Milestones

### M1: levels in the generator
- `level` in params (`L1`, `L2`, `L3`); output folders per level and seed, e.g. `output/hinge_lid/L2/seed_0000/`.
- L1, L2: today's geometry (three identical ribs, axis-aligned). L2 differs from L1 only in S3 thresholds.
- L3: per-rib geometry drawn independently (depth below the axis, front/rear extent), constrained so that every
  rib collides while opening, every rib is fixable, and the needed relief volumes of the largest and the smallest
  rib differ by >= 1.5x. The enclosure knuckles, pin and brackets must still never collide.
- L3 world pose: build everything in the local frame, then place the whole assembly with a seeded rigid transform
  (yaw 15-40 deg about world z, tilt 0-8 deg about a horizontal axis, offset 20-200 mm). Transform consistently:
  parts, axis, zones, print orientations (print orientation stays relative to the part: enclosure on its floor,
  lid top face down). Store the pose in params.json. Feasibility runs in the local frame.

### M2: generic extrude_cut + ops in evaluate
- Generic op (no hinge names) in the ops layer: `extrude_cut(part, origin, normal, x_dir, polygon_2d, depth_from,
  depth_to)`: a sketch polygon on the plane (origin, normal, x_dir; y_dir = normal x x_dir) cut through the part
  between the two depths along the normal. Validate inputs, return clear errors (agents will read them).
- `evaluate.py` takes a JSON list of operations instead of only --top/--side, e.g.
  `[{"op":"chamfer","edge_near":[x,y,z],"d1":0.9,"d2":2.1}, {"op":"extrude_cut", ...}]`, applies them to a copy of
  the parts and prints the test_fit-style report. Keep --top/--side as a shortcut for a full-edge chamfer.
  Add `--level` and `--hide-score` (no REWARD line, S3 shows only the removed volume and %; this is what we paste
  to models).

### M3: per-rib feasibility and reference volumes
- Per rib, exact 2D scan of an asymmetric triangular relief (top x side, 0.05 mm steps) at the rear wall outer top
  edge, over that rib's x-range extended by 0.3 + 0.05 mm at both ends, meeting S1 for that rib (no overlap 0-110,
  clearance >= 0.3 from 10 deg), seal margin >= 0.3, wall >= 1.2. The end clearance along x must be checked in 3D.
- V_ref = sum of the smallest valid relief per rib. Also store: V_full_edge (best full-edge chamfer, as in 2b) and
  V_identical (all three reliefs sized for the worst rib). Empty set for any rib -> replace the seed with
  seed+1000*k, logged.
- Store the reference fix as a list of operations in the evaluate JSON format (the reference solver in Task 6 must
  later find it through tools; this list is for evaluation and tests only, never shown to agents).

### M4: reward 0.6
- In cadfix/core/reward.py: S3 thresholds per level from docs/scenario.json `levels` (L1: full <= 4x V_ref, zero at
  8x; L2/L3: full <= 1.15x, zero at 2x). Reward: gate fail 0; S1 not met 0.25 * progress; S1 met
  0.3 + 0.1 * printability + 0.6 * minimal_change.
- S1 progress = 0.5 * angle progress + 0.5 * clearance progress, as in spec.score.S1_opening.
- Unit tests for the reference points in spec.reward.

### M5: brief.py per level
- `brief.py --seed N --level L`: what an agent knows after inspecting with tools, neutral wording, no fix words
  ("chamfer", "relief", "notch", "V_ref", "local", "per rib") and no numbers from the feasibility scan.
- S3 shown as the RULE only: "full points if the changed volume is within <factor>x of the best known fix for this
  task, zero at <factor>x" with the level's factors. No volumes or percentages of the reference.
- L3: all coordinates in the world frame (rotated), as tools would report them. Do not print the pose or the
  local frame; the agent can work it out from the hinge axis and faces.
- Keep the test that fails if fix words or reference numbers appear in the brief; extend it to all levels.

### M6: acceptance tables (3D, real B-rep)
For each level L1, L2, L3 and seeds 0-9, variants built as real operations:
1. original
2. reference fix (per-rib reliefs from M3)
3. best full-edge chamfer
4. identical reliefs sized for the worst rib
5. reference reliefs but exactly as long as each rib (no x extension)
6. reference reliefs 0.7x side
7. symmetric 45 deg full-edge chamfer
Columns: S1 pass, angle up to which S1 holds, min clearance 10-110, seal margin, min wall, removed volume %,
volume / V_ref, S3, reward. Also print per seed the rib relief sizes (L3) and the world pose (L3).

Expected (report the real numbers; do not tune to match):
- all levels: original 0; reference 1.0; variant 6 < 0.25
- L1: full-edge chamfer ~1.0
- L2, L3: full-edge chamfer ~0.4
- L3: identical reliefs clearly below 0.9
- variant 5: S1 fails (rib ends rub) on every seed
Also: L3 sweep time per seed, and confirm the pin, module and brackets never collide in any variant.

### M7: wrap-up
- Update CLAUDE.md commands (generator per level, brief, evaluate with ops JSON, tables).
- `docs/PROGRESS.md`: a Polish summary at the top: what works, the three tables (compact), open problems,
  decisions taken (link DECISIONS.md), spec change proposals.
- Example ops JSON files for the reference fix of L2 seed 0 and L3 seed 0 in `docs/examples/`.
