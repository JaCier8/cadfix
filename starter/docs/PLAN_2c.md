# Plan: Task 2c (levels L1-L3)

Working mode: autonomous (docs/TASK_2c.md). Commit + Polish note in PROGRESS.md after each milestone.
Open design questions go to docs/DECISIONS.md.

## Starting state
- Folder was not a git repository: `git init` + baseline commit (109 tests green).
- L1 geometry = task 2b: 5 or 7 knuckles, so 2 or 3 lid ribs (8/10 seeds have 2). Kept as is for L1/L2
  ("today's geometry"); L3 forces 7 knuckles = 3 ribs (DECISIONS D2).

## Code layout
- `cadfix/core/kernel.py` (generic): rigid pose helpers (matrix <-> cq), `downward_area(up=...)`,
  oriented-box manifold, ring width of a planar region (erosion bisection), mesh slice -> shapely.
- `cadfix/checks/sweep.py` (generic): S1-style opening check over a revolute joint (overlap eps, clearance
  from angle, ok-until angle, min clearance), used by generator (3D verification), dev grading, brief.
- `cadfix/ops/edit.py` (generic): `OpError`, `find_edge_near`, `chamfer`, `extrude_cut`, `apply_ops`
  (JSON-like dicts, validated, clear errors).
- `cadfix/core/reward.py` (generic): `ratio_score`, `sweep_progress` (0.5 angle + 0.5 clearance).
- `scenarios/hinge_lid/generator.py`: `level`, per-rib profiles, L3 per-rib draws + world pose, per-rib
  relief scan, V_ref / V_full_edge / V_identical, reference ops (local + world), 3D check of the reference,
  output `output/hinge_lid/<L>/seed_NNNN/`.
- `scenarios/hinge_lid/devgrade.py` (new): load a level/seed, apply ops, dev gates measured on geometry
  (seal ring width, thinnest wall from sections, bracket keep-in as oriented boxes, closed position), S1,
  printability, S3 vs V_ref with level factors, reward 0.6. Shared by evaluate, dev_sweep, brief, tests.
- `scenarios/hinge_lid/evaluate.py`: `--ops` (JSON file or string), `--top/--side` shortcut, `--level`,
  `--hide-score`.
- `scenarios/hinge_lid/dev_sweep.py`: M6 acceptance tables (7 variants built as real ops) per level.
- `scenarios/hinge_lid/brief.py`: `--level`, S3 as rule only, L3 in world coordinates only.

## Milestones (each: pytest green, commit "2c Mx: ...", PROGRESS note)
- M1 levels in the generator (L1/L2 same parts, L3 per-rib + pose; zones/axis/print orientation in world).
- M2 generic extrude_cut + chamfer ops, evaluate with ops JSON.
- M3 per-rib 2D scan, V_ref, V_full_edge, V_identical, reference ops, 3D end-clearance verification.
- M4 reward 0.6 (levels' S3 factors, new weights, S1 progress), unit tests for reference points.
- M5 brief per level + leak test across levels.
- M6 acceptance tables L1/L2/L3 x seeds 0-9 (real numbers, not tuned).
- M7 CLAUDE.md commands, PROGRESS summary (Polish), docs/examples ops JSON for L2/L3 seed 0.

M1 and M3 touch the same generator code; M1 lands the geometry and pose, M3 the scans.
