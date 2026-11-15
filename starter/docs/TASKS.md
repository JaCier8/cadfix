# TASKS

One task per Claude Code session (`/clear` between tasks). Paste the prompt block, review the plan, approve.
Each task must end green: tests pass, acceptance commands run, entry added to `docs/PROGRESS.md`.

---

## Task 1: repo skeleton + CadQuery in Docker

```
Read CLAUDE.md and docs/scenario.json. Task 1 from docs/TASKS.md.

Goal: a repo skeleton matching the architecture in CLAUDE.md, and proof that our geometry stack runs in Docker.

1. Create the package layout (cadfix/ with core, checks, ops, env, harbor; scenarios/hinge_lid; tests/)
   with empty modules and a pyproject or requirements file: cadquery, manifold3d, trimesh, numpy, scipy,
   shapely, "mcp<2", pytest.
2. Write a dev Dockerfile (python:3.11-slim) that installs these and our package. Find which system
   libraries cadquery/OCP needs on slim images and add them.
3. Smoke test inside the container: build a box with CadQuery, fillet one edge, export STEP, re-import it,
   tessellate it, load it into manifold3d, print volumes from both.
4. pytest with one test doing the same smoke check.

Acceptance (show real output):
- docker build succeeds; print the image size and build time
- docker run <image> pytest -q passes
- the two volumes printed by the smoke test agree within 0.1%
Plan first, wait for my approval.
```

---

## Task 2: hinge_lid geometry for one seed + "does it really collide?"

```
Read CLAUDE.md and docs/scenario.json. Task 2 from docs/TASKS.md.

Goal: scenarios/hinge_lid/generator.py builds the four parts for a seed with CadQuery, and we can SEE and
MEASURE that the lid hits the rear wall while opening.

Geometry (exact numbers are your choice, keep them plausible for FDM printing, units mm):
- Frame: x along the hinge, y from front (y=0) to rear, z up. Box open at the top, walls 2-3 mm, floor ~2 mm.
- Lid: plate on top of the walls. Closed, its underside rests on the wall tops (that contact is the seal band:
  >= 1.5 mm wide all around, on the INNER part of the wall top).
- Hinge at the rear: axis parallel to x, behind the rear wall's outer face and above the wall top, so lid
  material below the axis level swings forward and down while opening. Alternating knuckles (enclosure
  knuckles attached to the rear wall, lid knuckles attached to the lid), ~0.4 mm axial gaps, hinge_pin is a
  separate fixed cylinder through all knuckles with a small radial clearance. Notch the lid around the
  enclosure knuckles so knuckles never collide during rotation.
- lid_module: fixed box under the lid near its rear edge (a small board), inside the box when closed.
  The lid has a frame around it (keep-in zone).
- The defect: the outer top edge of the rear wall lies inside the circle swept by the lid's rear-bottom
  material around the hinge axis, so the lid collides somewhere between ~30 and ~100 deg.
- Randomise per seed: box size, wall thickness, hinge axis position. Expose a params dataclass.
- Feasibility: compute analytically the radius R swept by the lid near the wall, and check that removing the
  wall material within R + 0.3 mm of the axis is possible while keeping the seal band and a 1.2 mm wall.
  Return the required removal and the margin to the seal band. Reject seeds that are infeasible.
- Output per seed: STEP for enclosure, lid, hinge_pin, lid_module; a params/feasibility JSON.

Also write the minimal mesh helpers you need in cadfix/core/kernel.py (tessellate a CadQuery shape, rotate a
mesh about an axis, intersection volume with manifold3d) and a dev script that sweeps the lid (with module)
0..110 deg in 1 deg steps and prints the first colliding angle, the collision volume and its bbox.
Optionally show the parts in OCP CAD Viewer if ocp_vscode is available.

Acceptance (real output):
- at 0 deg: no collision between lid(+module) and enclosure; pin does not collide with knuckles
- during the sweep: first collision between 30 and 100 deg, and the collision bbox sits at the outer top
  edge of the rear wall (nowhere else, in particular not at the knuckles)
- a hand-made chamfer of the size returned by the feasibility check removes the collision over 0..110 deg
- these three facts hold for seeds 0..9 (print a table); pytest covers them
Plan first, wait for my approval.
```

---

## Task 3: go/no-go experiment (manual, no code)

Done by a person, not Claude Code. Give a frontier model (chat) the bug report, the full spec and the
measurements/STEP descriptions of seed 0, as if it had the tools. If it solves it at once, raise the
difficulty knobs (tight window, rotated assembly) before building further.

---

## Task 4: generic checks + reward for hinge_lid

```
Read CLAUDE.md and docs/scenario.json. Task 4 from docs/TASKS.md.

Goal: the spec section of docs/scenario.json (G1-G6, S1-S3, reward) implemented as GENERIC checks plus a
data-driven reward policy; the hinge_lid scenario declares them as data.

- cadfix/core: Part (name, B-rep, editable, print orientation), Joint (fixed / revolute with axis and range),
  Zone (keep-in / keep-out attached to a part), Assembly, a check registry, CheckResult(passed, score,
  metrics, details), RewardPolicy (gate ids, objective with progress, weighted score ids).
- cadfix/checks: valid_solid, interface_frozen, keep_in, keep_out, collision_free (at a joint pose),
  sweep_collision_free (joint range + step; returns max collision-free angle as progress metric),
  contact_width (erode contact region, must remain a closed ring), min_wall, overhang (print orientation,
  only NEW overhangs vs the original), volume_change, envelope.
- scenarios/hinge_lid: spec as data that instantiates these checks with parameters; reward exactly as in
  docs/scenario.json.
- cadfix/core/reward.py + a grader CLI: grade <task_dir> <submitted parts dir> -> JSON report + reward.txt.

Acceptance (real output, seeds 0..9):
- original parts: reward 0.0
- hand-made correct chamfer (from task 2 feasibility): reward >= 0.9
- chamfer 30% too small: 0 < reward < 0.5 (partial progress)
- chamfer that eats the seal band: 0.0
- cutting the lid's rear edge: 0.0 (keep-in)
- grading one submission takes < 10 s
Plan first, wait for my approval.
```

---

## Task 5: CAD operations + environment + MCP server

```
Read CLAUDE.md and docs/scenario.json. Task 5 from docs/TASKS.md.

Goal: the agent-facing side. Edit ops on B-rep, episode state, MCP server over stdio.

- cadfix/ops/topology.py: describe edges/faces of an editable part (id, type line/circle/..., endpoints or
  centre, length/area, adjacent face normals); find_edges_near(point, direction); find_faces_near(point).
- cadfix/ops/edit.py: chamfer(part, edge_id, d1, d2), fillet(part, edge_id, r), offset_face(part, face_id, d),
  cut_box, add_box, undo. Each edit returns the new described edge/face list (ids change after edits).
- cadfix/env/env.py: episode state, JSONL log of every call, snapshot STEP + mesh after each edit into the
  output dir, safety cap ~150 calls, test_fit runs all checks and costs a small reward penalty (record count).
- cadfix/env/server.py: FastMCP (mcp<2) stdio server; tools generated from the op registry, query tools and
  one run_check tool per check in the scenario spec. Clear docstrings: they are the agent's documentation.
- An MCP smoke test with a real stdio client (see legacy_v0 for a pattern).

Acceptance (real output):
- via the MCP client on seed 0: list edges, find the rear wall's outer top edge with find_edges_near, chamfer
  it with the feasibility size, run test_fit -> all checks pass; grader gives >= 0.9
- the JSONL log contains every call
Plan first, wait for my approval.
```

---

## Task 6: reference solver + exploit suite

```
Read CLAUDE.md and docs/scenario.json. Task 6 from docs/TASKS.md.

- scenarios/hinge_lid/reference.py: a solver that uses ONLY the env tools (never params/feasibility files):
  run the sweep check, read the collision region, compute the needed radius from the hinge axis, pick the
  edge with find_edges_near, choose an (asymmetric) chamfer that clears the radius + clearance and keeps the
  seal band, verify with checks, submit.
- Baseline agents: do_nothing, stop_early.
- A run_eval script: agent x seeds -> table of rewards and tool-call counts.
- tests/test_exploits.py: each exploit with expected max reward < 0.4, e.g. delete most of the rear wall,
  giant cut, cut the lid, overwrite output files with garbage or a scaled copy, edit fixed parts or the
  local copy of the grader (the verifier must not care), remove knuckles, fill the box.

Acceptance (real output, seeds 0..9): reference >= 0.9 on every seed, do_nothing = 0, stop_early = 0,
every exploit below its limit.
Plan first, wait for my approval.
```

---

## Task 7: Harbor packaging + first OpenCode run

```
Read CLAUDE.md and docs/scenario.json. Task 7 from docs/TASKS.md.

- cadfix/harbor/build.py: scenario + seed -> Harbor task folder: instruction.md (bug report + full spec,
  rendered from the scenario data; never mention the cause or the fix), task.toml with
  [[environment.mcp_servers]] (stdio), environment/Dockerfile (public files only), tests/test.sh (own grader
  copy + pristine parts -> /logs/verifier/reward.txt), solution/solve.sh (reference solver).
  legacy_v0/harbor/build_tasks.py shows a working version of this for the old prototype.
- Validate task.toml with Harbor's own TaskConfig model.
- Run: harbor run -p <task> -a oracle  (reference) and, after I confirm the model/credits,
  harbor run -p <task> -a opencode -m <provider/model>.

Acceptance: oracle run gives reward >= 0.9 in Harbor; one OpenCode run log with its score saved under runs/.
Plan first, wait for my approval.
```
