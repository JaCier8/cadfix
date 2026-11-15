# DECISIONS (task 2c)

Design questions the spec (docs/scenario.json 0.6-levels, docs/TASK_2c.md) does not answer. Format:
question / options / choice / why.

## D1. The folder was not a git repository
- Options: stop and ask; `git init` locally.
- Choice: `git init` + a baseline commit of the state before 2c (tests 109 green), then one commit per milestone.
- Why: TASK_2c asks for a commit per milestone; a local repo is reversible and pushes nothing.

## D2. "three identical ribs" for L1/L2 vs today's geometry
- Fact: the task 2b generator draws 5 or 7 knuckles, so L1 seeds have 2 or 3 lid ribs (seeds 0-9: only 0 and 5
  have 3).
- Options: (a) keep today's draws (2 or 3 ribs); (b) force 7 knuckles for L1/L2.
- Choice: (a) for L1/L2; L3 always uses 7 knuckles (3 ribs).
- Why: TASK_2c says "L1, L2: today's geometry" and "keep L1 working exactly as before"; (b) changes every L1 part.
  L3 explicitly asks for three different ribs. See spec change proposal P1.

## D3. L3 sampling
- L3 has its own random stream (`default_rng([seed, 3])`): the task 2b box/hinge draw, then n_knuckles = 7, rib 0
  = the 2b rib draw, ribs 1 and 2 drawn independently with the same ranges (width 1.6-2.0, centre offset -0.8..0.6,
  reach past the edge 0.2-0.45 mm), then the pose.
- Cheap per-rib checks (collision window 40-95 deg for EVERY rib, rib below the knuckle, reach >= 0.15) reject the
  draw (redraw within the seed). An empty relief set for any rib -> seed replaced by seed + 1000k (spec).
  Needed reliefs differing by < 1.5x, or a lid plate outside the ribs that would not clear the original wall
  -> redraw within the seed (these are draw constraints, not "rib not fixable").
  Since 0.7 (P3 applied, task 2d): the ratio rule is replaced by V_identical / V_ref >= 1.4
  (`L3_MIN_IDENTICAL_RATIO`); the plate rule stays.
- Why: same distributions as L1 per rib (no tuning towards a target), the spec's replacement rule kept as written.
- Observed: 6/10 L3 seeds need replacement (0, 2, 5 -> +1000; 6, 7 -> +2000), because with three independent ribs
  one of them is unfixable more often.

## D4. World pose (L3)
- R = R_tilt(horizontal axis at azimuth phi) * R_yaw(z); world = R * local + offset. yaw U(15, 40) deg (positive),
  tilt U(0, 8) deg, phi U(0, 360) deg; offset x, y = +-U(20, 200), z = U(20, 200) mm.
- Stored in params.json: `pose` {yaw_deg, tilt_deg, tilt_axis_deg, offset, matrix (3x4)}.
- Transformed: STEP parts, joint axis point/direction, rear outer top edge endpoints, keep-in zones and module box
  (as oriented boxes: corner `origin` + three `edges`, under `world`; the local `box` stays for internal use),
  print orientations (`build_up` vector: enclosure local +z, lid local -z = top face down).
- Why: "offset 20-200 mm" does not say per axis or length; per axis with random sign keeps coordinates large in
  every component (the "far coordinates" knob).

## D5. L3 "identical reliefs sized for the worst rib"
- Choice: the smallest single (top, side) profile valid for ALL ribs (intersection of the per-rib valid sets);
  this is the same profile as the best full-edge chamfer. V_identical = that profile x each rib's relief length.
- Why: a profile sized for the rib with the largest relief need not be valid for another rib with a different shape.

## D6. Tessellation weld grid 1e-6 mm instead of 0.001 mm
- Finding: in the L3 world frame, snapping mesh vertices to 0.001 mm pushes them up to ~0.0009 mm off their
  planes; the lid resting on the wall tops (coplanar contact, ~700 mm2) then shows 0.01-0.21 mm3 of "overlap" at
  0 deg on 10/10 L3 seeds (> the 1e-3 mm3 S1 limit), i.e. a false collision in the closed position.
- Options: overlap limit relative to contact area (spec change); measure in a hidden local frame (grader knows
  the pose, agent tools would not); weld finer.
- Choice: weld at 1e-6 mm (`kernel.WELD_MM`). All 80 parts of L1/L3 seeds 0-9 stay manifold, rest overlap 0.
  SNAP_MM = 0.001 stays for values that cross a file or tool boundary (CLAUDE.md rule), which is what it was for.
- L1 numbers: unchanged (L1 coordinates are on the 0.001 grid anyway).

## D7. Relief cutter shape (micro slivers in rotated frames)
- Finding: the reference relief as a triangle (-top, 0), (0.01, 0.01), (0, -side) left, on 7/10 L3 seeds, a
  sub-micron sliver of wall above the cutter where it meets the wall top (the world origin snapped to 0.001 mm
  puts the plane a few 1e-4 mm off); the sliver's underside counted as 0.21 mm2 of new overhang -> printability 0.
- Choice: pentagon (-top, 0), (-top, 0.01), (0.01, 0.01), (0.01, -side), (0, -side): it leaves the top and outer
  faces at right angles, so an offset leaves a step, not a sliver. Same removed volume when exact.
- Open (task 4): an agent typing world coordinates hits the same effect. The overhang / thin-feature checks
  should ignore features below a size threshold (e.g. 0.01 mm), or agents lose printability for sub-micron
  artefacts they cannot see.

## D8. Where the 3D end-clearance check runs
- Choice: inside `resolve_seed`: the per-rib reliefs are cut on the local B-rep parts and S1 is swept in 3D;
  failure rejects the source seed like an empty 2D set (logged). Result stored in `feasibility.reference`.
- Observed: never triggers on seeds 0-9 of any level (min 3D clearance = the 2D value, the x gap is 0.35).

## D9. Task 2b tests updated for reward 0.6 (tests/test_hinge_lid.py, tests/test_reward.py)
Spec 0.6 changes the reward (0.25 * progress; 0.3 + 0.1 * printability + 0.6 * minimal_change) and S3 (factors
x V_ref instead of 1.25 / 3 x V_best, per level). Same L1 parts, so the geometric assertions are unchanged; only
expectations that encode the old numbers changed:
- "best chamfer -> reward 1.0" -> "full-edge chamfer: S3 = linear(V / V_ref, 4, 8), reward = 0.4 + 0.6 * S3, >= 0.85"
  (L1 full-edge chamfers are 3.2-4.68 x V_ref, so 5/10 seeds lose a few S3 points; seed 6 gets 0.897).
- "0.7 x side: reward <= 0.3" -> "< 0.25" (new progress weight); the variant is now 0.7 x side on the reference
  reliefs (M6 variant 6), not on the full-edge chamfer.
- "2 x side: S3 = 1/1.75, reward 0.829" -> "S3 = linear(V / V_ref, 4, 8) < 0.5"; seeds 0 and 2: the chamfer op
  now returns its error (2 x side >= free band), the old table used a boolean fallback, which no tool offers.
- S3 thresholds in params.json: V_ref, factors and mm3/% thresholds instead of V_best and %.
- test_reward: old POLICY algebra replaced by the scenario policy, spec reference points, and a check that the
  policy and S3 factors equal the numbers in the docs/scenario.json text.
- Dev seal/wall/overhang are now measured on the geometry (devgrade), not from the chamfer size; on the 2b
  variants they give the same numbers (e.g. L1 seed 0 best: seal 1.830, wall 1.830, 0.2445 %).

## D10. L3 2D scan asks for clearance >= 0.3 + 0.002 mm (task 2d)
- Finding: with the 0.7 L3 draws, the reference fix failed S1 in the world-frame 3D sweep on seeds 0 and 1
  (rewards 0.221 / 0.149): the exact 2D model gave 0.3002 / 0.3001 mm, the local 3D check 0.3002 / 0.3001, the
  world-frame sweep (rotated pose, coordinates snapped to 0.001 mm) just below 0.3. Under 0.6 three L3
  references also sat at 0.300 and passed by luck. Seed 0's full-edge and identical variants failed the same way
  (they reuse the boundary profile of rib 0).
- Options: tolerance in the grader (changes the spec threshold); check the reference in the world frame inside
  resolve_seed (more replacements, generator depends on the world grader); margin in the L3 scan.
- Choice: `L3_SCAN_CLEARANCE_MARGIN = 0.002` (2 x the snap grid), L3 only. The grader threshold stays 0.3.
  L1/L2 sit at the identity pose on the 0.001 grid, so their parts and numbers stay as they were.

# Tasks 4-7 (docs/TASK_4-7.md, spec 0.7-levels-tuned)

## D11. Public task vs private grader data
- The agent's task dir holds task.json (parts, joint, zones, print directions; no generator parameters, no pose,
  no feasibility data), spec.json (every check with its thresholds, the reward formula, the S3 rule) and the
  STEP parts. V_ref is the only private number (scenario.json disclosure: "S3 RULE only"); it lives in
  pristine/grader.json and is merged into the S3 check's params by the grader. The agent's tools run the same
  S3 check without it: they report the changed volume and %, never a score.

## D12. Zones (G3)
- One gate per kind: G3_keep_in, G3_keep_out (spec G3 has both in one line; two ids make the agent's
  run_check output clearer). Keep-in fill = material inside the zone now / originally >= 99 %.
- Zones: enclosure knuckle brackets (as in 2c), lid knuckles (cylinder r_k about the axis per lid segment), lid
  ribs (box per rib), module frame (box around the frame below the plate), seal band on the lid (lowest 0.5 mm of
  the plate over each wall footprint) and on the enclosure (the INNER 1.5 mm ring of the wall tops, 0.5 mm deep:
  the minimal seal width the spec asks for, away from the outer edge where a fix cuts; first try covered the rear
  corners and failed every full-edge chamfer, fixed). Keep-out: the lid_module volume, no lid or enclosure
  material may enter it.

## D13. Frozen hinge interface (G2)
- interface_frozen: inside a cylinder of radius r_bore + 0.6 mm around the pin axis, per knuckle segment of both
  parts, the material is unchanged (symmetric difference <= 0.01 mm3). Covers diameter, position, axis and
  filling the bore. The pin is a fixed part, so "pin does not collide" follows.

## D14. Not rebuilt (G6)
- Extents along the three box axes may move by <= 0.5 mm; changed volume (removed + added, not the net change,
  so "gut and refill" is caught) <= 15 % per editable part. The box axes come from public data (hinge axis,
  rear-wall normal, up) and are written into spec.json.

## D15. Printability (S2): only NEW defects, 0.2 mm filter by thickness
- min_wall: sections every 0.2 mm along the three box axes through the changed region (+ 1.5 mm); material
  narrower than 1.2 mm (region minus its morphological opening) that the original section does not have counts.
  The original part is the accepted design: its 1.2 mm knuckle walls and cylinder-tangent sections never count.
- overhang: downward faces (> 45 deg from vertical in the part's print orientation) near the change that do not
  lie on a downward face of the original.
- Feature filter (spec 0.7 "features smaller than 0.2 mm are ignored"): a thin / overhanging patch counts if it
  is >= 0.2 mm THICK (largest inscribed circle). First version used the short side of the minimum rotated
  rectangle; bent rounding slivers on L3 (0.000-0.004 mm thick) passed it and failed printability. Known gap:
  a wall thinned below 0.2 mm is ignored too; such a cut never helps S1 more than removing the material and
  costs S3 (noted, exploit table).

## D16. S1 sweep in the box frame
- sweep_clearance takes an optional evaluation frame (the public box axes). Meshes and the axis are rotated
  into it before the sweep: distances and volumes are unchanged, manifold's distance queries on axis-aligned
  faces are ~10x faster (L3 sweep 1.6-2.7 s -> ~0.15 s).

## D17. Seal contact (G5) on rotated parts
- The wall-top plane point is on the 0.001 mm grid, so faces within 0.002 mm of the plane count. The contact
  region gets a 0.002 mm closing before the ring test: on L3 seed 4 a zero-width slit between tessellation
  triangles at a relief end "opened" the ring (width 0 instead of 2.09 mm).

## D18. Submission and test_fit cost in the grader
- Per editable part: a missing file -> its pristine original (did not edit it); an unreadable file -> pristine
  too (so garbage scores like doing nothing). Fixed parts always from the verifier's pristine copy.
- test_fit calls = max(episode.json counter, test_fit lines in actions.jsonl). Edited parts with no episode
  record at all pay the full cap (0.1). Both files live in the agent's output dir, so an agent with a shell can
  lower the count; the most it gains is the 0.1 cap (known limitation).

## D19. Old dev grader replaced
- devgrade.Grader now builds the in-memory Assembly + Spec and runs the generic checks (same code as the grader
  CLI and the tools). Removed: dev seal / wall sections, bracket fill, overhang area. Kept as dev-only extras:
  side_collisions over the sweep and the first-contact table in dev_sweep. Test changes: `min_wall` number ->
  `min_wall_ok` (the check reports new thin walls only), gate names valid/seal/brackets/closed -> spec ids.

## D20. Edit results and ids
- Every edit returns the edited part's full edge and face lists in a compact form (edge: id, type, end points,
  adjacent face ids, circle centre / radius; face: id, type, centre, area, normal / axis / radius): ~11 KB for the
  enclosure. `list_edges` / `list_faces` give the full descriptions (adjacent face normals, bboxes). Ids =
  positions in the current shape's lists.
- Edges and faces are selected by id or by a point (`edge_near` / `face_near` + optional direction / normal), so
  the 2c ops JSON (gonogo) still works.
- offset_face = push / pull of a PLANAR face (the prism swept by the face is added or cut); boxes are oriented
  (corner + three perpendicular edge vectors), needed on L3.

## D21. Episode details
- The server may be restarted mid-episode (harness reconnects): Env resumes from out_dir/parts and episode.json
  (counters kept, undo history lost, `resumed` counted).
- After `submit` every tool refuses (also queries): the episode is over.
- Tool-call cap 150 (scenario.json): after it only `submit` works.

## D22. Agents that write part files with their shell
- The agent's container has a shell and CadQuery. The grader grades whatever is in /output/parts/<editable>.step
  at the end, made by the tools or not: the checks use only the verifier's pristine data, so a hand-made STEP is
  judged by exactly the same rules (envelope, zones, interfaces, sweep, change). Fixed parts are never read from
  the output dir. Garbage or missing files count as the original part.

## D23. instruction.md content
- Rendered from task.json + spec.json only. It lists every check with its thresholds, the reward formula, the
  S3 rule, all zones with regions, the joint, print orientations, conventions and how the tools / episode work.
- It does not name the edit operations in prose (the agent sees them in the MCP tool list; the brief's leak test
  forbids fix words like "chamfer") and does not give the measured first-contact angle (scenario.json
  disclosure: the angle is measurable, not given).

## Spec change proposals
- P1. `levels.L1_easy.geometry` / `L2_medium.geometry` say "three identical ribs"; the task 2b geometry has 2 or 3
  (8/10 seeds: 2). Either reword to "two or three identical ribs" or force 7 knuckles (changes all L1 parts).
- P2 (APPLIED in 0.7, task 2d: 5x / 10x). L1 S3 "full points up to 4x (a full-edge chamfer gets full points)" holds on 5/10 seeds only: the full-edge
  chamfer is 3.20-4.68 x V_ref (L1 seeds with 2 ribs and short knuckles are above 4x). Rewards 0.897-1.0. If L1
  should give the full-edge chamfer exactly full points, use 5x / 10x (or define L1's reference as the full-edge
  chamfer, as in 2b).
- P3 (APPLIED in 0.7, task 2d: option (a)). L3 trap "identical reliefs sized for the largest rib: clearly < 0.9" does not follow from "reliefs differ
  by >= 1.5x". Measured (M6, seeds 0-9): identical / V_ref = 1.16-1.39, reward 0.829-0.993 (mean 0.903); only 4/10
  seeds are below 0.9 (1: 0.832, 2: 0.829, 5: 0.872, 7: 0.839), seed 0 gets 0.993 (two of three ribs are the big
  ones). With S3 1.15 / 2, identical reliefs land under 0.9 only if V_identical / V_ref > 1.28. Options:
  (a) constrain L3 draws by V_identical / V_ref >= 1.4 (reward <= 0.82) instead of max/min >= 1.5;
  (b) require the largest rib's relief >= 1.5x BOTH others (one big rib, two small ones);
  (c) tighten L3 S3 (e.g. full <= 1.05x). (a) states the property the trap needs directly. Not applied: the
  generator follows the current spec.
- P4. `expected_bad_fixes`: "reliefs exactly as long as the rib: rib ends rub (< 0.3 mm along x) -> S1 fails"
  holds (30/30), and they score 0.000 (not partial credit): the rib end touches the uncut wall at the original
  first-contact angle, so angle progress is 0 and the touch gives clearance progress 0. Fine as a trap; noting it
  because "broken, best case 0.25" never happens for near-misses of this kind.
