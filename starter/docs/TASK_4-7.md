# Tasks 4-7: the full agent-facing environment (long autonomous run, overnight)

Read CLAUDE.md and docs/scenario.json (0.7-levels-tuned) first, then docs/DECISIONS.md and the top of
docs/PROGRESS.md. Goal by the morning: a frontier agent can play L1/L2/L3 through Harbor + OpenCode over MCP,
our reference solver plays the same tasks through the same tools, and the judges' five run types each work with
ONE command.

## Organiser requirements (must, these decide the score)

- Harbor task format: `instruction.md`, `task.toml`, `environment/Dockerfile`, `tests/`, `solution/`.
- Agents play with the OpenCode harness: `harbor run -p <task or dataset dir> -a opencode -m <provider/model>`.
- The verifier writes ONE score in [0, 1] to `/logs/verifier/reward.txt` (partial credit welcome).
- Judges rerun with the standard harness: our reference run, three agent runs, a do-nothing baseline and a
  stop-early baseline, then spend 15 minutes looking for reward exploits. They must reproduce our numbers from
  the README with one command per run type.
- Submission: at least one Harbor run log with its score (the user will produce the OpenCode one in the morning)
  and a short README: what the agent has to do, why it is hard, how it is scored.

Harbor facts (checked in Harbor's source):
- built-in agent `oracle` runs `solution/solve.sh` -> our reference run;
- built-in agent `nop` does nothing -> do-nothing baseline. The MCP server is never started, so the output dir
  is EMPTY: the verifier must then grade the original parts (reward 0) and must never crash or skip writing
  reward.txt;
- `-p` takes a single task dir or a dataset dir (one task per subdirectory); `-k N` = attempts per task
  (three agent runs = `-k 3`); `--agent-import-path module:Class` runs a custom agent (use it for stop-early).

## Working mode (overrides "wait for approval" in CLAUDE.md)

The user is asleep.
- Write the plan to `docs/PLAN_4-7.md`, then start without waiting.
- Milestones in order. After each: fast tests green (`pytest -q -m "not slow"`), commit
  `git add -A && git commit -m "4-7 Mx: <what>"`, short Polish note in `docs/PROGRESS.md`.
  Run the full suite only at the end of M3 and M5.
- Open design questions: choose what fits docs/scenario.json best, record it in `docs/DECISIONS.md`, continue.
- STOP with a clear report at the top of `docs/PROGRESS.md` only if something makes the spec impossible.
  Never tune numbers to pass an acceptance line; report what really happens.
- Do not edit docs/scenario.json; put spec change proposals into DECISIONS.md.
- If something outside your control blocks a milestone (no Docker daemon, Harbor install fails), record it, do
  what you can without it, and move on.

## M0: think the reference solver through BEFORE writing code

Write `docs/SOLVER_DESIGN.md` (in English, ~1-2 pages) and only then continue. The reference run is worth 30
rubric points (the gap) and must be: tools-only (the same MCP tools the agent gets; never params, feasibility
output, stored reference ops or hidden files), deterministic, reproducible, robust on L1/L2/L3 seeds 0-9, and
finish well inside the agent timeout.
Cover at least:
- How it builds its own understanding from tool outputs only: hinge axis and the joint, rear wall faces and the
  outer top edge, the colliding regions, which rib each region belongs to (group along the hinge axis), where
  each rib starts and ends along the axis.
- L3: deriving a local frame (hinge axis direction, rear wall outer face normal, up) from tool outputs and
  expressing every cut in world coordinates through that frame.
- Sizing each relief: compare at least (a) analytic sizing from measured geometry, (b) bisection on trial cuts
  with run_check + undo, (c) a hybrid (analytic first guess, then verify/tighten). Choose one and justify:
  number of tool calls, robustness to rounding, closeness to V_ref (S3 needs <= 1.15x on L2/L3).
- End extension along the axis (>= 0.3 mm + margin) and how it verifies the rib ends do not rub.
- Failure handling: what it does if a cut fails, if a check never passes, if a region does not map to a rib.
- What a typical LLM agent does differently (from the go/no-go: a weak model optimised a full-edge chamfer to
  3.2x V_ref and never tried local reliefs) and which tool outputs would let a smart agent find the local fix,
  so the difficulty stays fair.
Then implement exactly that design in M3; if the implementation forces a change, update the design file.

## M1 (Task 4): generic checks + reward from scenario data

- `cadfix/core`: Part, Joint (revolute: axis point, direction, range), Zone (keep-in / keep-out, attached to a
  part, moves with it), Assembly, check registry, CheckResult(passed, score, metrics, details), RewardPolicy
  read from scenario data (gate ids, objective with progress, weights, level S3 factors).
- `cadfix/checks` (generic, registered by type name, no hinge names): valid_solid, interface_frozen, keep_in,
  keep_out, collision_free (at a joint pose), sweep_clearance (joint range, step, overlap rule from the start
  angle, clearance rule from a later angle, progress metric as in spec.score.S1_opening), contact_width (erosion
  ring test for the seal), min_wall and overhang in print orientation with the 0.2 mm feature filter,
  volume_change vs V_ref with level factors, envelope.
- Keep-in boxes for ALL zones (lid knuckles, ribs, module frame, seal band, brackets), stored in params.
- `scenarios/hinge_lid/spec.py` (or a data file): the spec as data that instantiates these checks per level.
- Grader CLI: `grade --task-dir <public task dir> --pristine <pristine parts dir> --submitted <dir> --level L`
  -> JSON report + `reward.txt`. It never reads files the agent could have changed. Missing or unreadable
  submission -> grade the pristine originals (reward 0), still write reward.txt.
- Replace the rough dev versions of seal / bracket / overhang checks with these.
- Acceptance: the 2c/2d acceptance variants through the NEW grader for L1/L2/L3 seeds 0-9 match
  docs/acceptance_2c.txt within rounding (reference 1.0, original 0, full-edge 0.4 on L2/L3, identical reliefs
  <= ~0.82 on L3, exact-length reliefs 0). Explain any difference.

## M2 (Task 5): CAD operations, environment, MCP server

- `cadfix/ops/topology.py`: describe edges and faces of an editable part in WORLD coordinates (id, type,
  endpoints / centre, length / area, adjacent face normals), `find_edges_near(point, direction=None)`,
  `find_faces_near(point, normal=None)`. Coordinates rounded to 0.001 mm.
- `cadfix/ops/edit.py`: chamfer(edge, d1, d2), fillet(edge, r), offset_face(face, d), extrude_cut (as in 2c),
  cut_box, add_box, undo. Every edit returns the fresh described edge/face list of the edited part (ids change
  after edits). Errors are short and actionable (agents read them).
- `cadfix/env/env.py`: episode state, JSONL log of every call (args, result, duration), snapshot of the parts
  at start AND after each edit (STEP for the grader, GLB for the later viewer), safety cap 150 calls,
  `test_fit` = all checks of the level's spec. test_fit cost: first 2 calls free, then -0.02 reward each,
  capped at -0.1 (count stored in the output dir; the grader applies it). `run_check(id)` per check is free.
  `submit` ends the episode.
- `cadfix/env/server.py`: FastMCP (mcp<2), stdio. Tools generated from the op registry, query tools (list_parts,
  part_info, list_edges, list_faces, find_edges_near, find_faces_near, measure, section), one `run_check_<id>`
  per check in the level's spec, test_fit, submit. Docstrings are the agent's documentation: precise, with
  units and coordinate conventions, no hints about the fix.
- `instruction.md` renderer: bug report + full spec for the level, neutral wording, S3 as the rule only, no fix
  words (reuse the brief test's forbidden-word list). Tell the agent the tools are on the `cadfix` MCP server and
  that the parts are graded as saved when the episode ends.
- MCP smoke test with a real stdio client (pattern in legacy_v0): on L2 seed 0 apply the reference ops through
  the MCP tools, test_fit passes, the grader gives 1.0.
- The agent container has a shell and CadQuery. If an agent writes part files directly, the grader grades what
  is in the output dir at the end; record that decision.

## M3 (Task 6): reference solver, baselines, exploits

- Implement `scenarios/hinge_lid/reference.py` as designed in M0 (tools only).
- Baselines as code: do_nothing (submit at once), stop_early (one inspection call, then submit).
- `run_eval` script (local, without Harbor): agent x level x seeds -> table (reward, S1, volume/V_ref, tool
  calls, time) + CSV in `results/`.
- `tests/test_exploits.py` (slow marker where needed), each with an expected max reward < 0.4:
  cut the lid / ribs; gut the rear wall; one huge cut; cut through the seal band; cut the brackets; fill the box;
  overwrite output files with garbage, with a scaled copy, with the original; delete the output files; edit
  fixed parts; edit the grader copy inside the container (the verifier must not care); spam test_fit; call
  submit early then keep editing.
- Acceptance: reference >= 0.95 on every level/seed 0-9; do_nothing and stop_early = 0; every exploit below its
  limit. Full suite at the end of this milestone.

## M4 (Task 7): Harbor packaging

- `cadfix/harbor/build.py`: level + seed -> `harbor_tasks/<level>/seed_<n>/`:
  instruction.md, task.toml (`[[environment.mcp_servers]]`, stdio, `python3 -m cadfix.env.server`, sensible
  agent and verifier timeouts), environment/Dockerfile (python 3.11 + deps + package + PUBLIC task files only;
  keep every layer identical across tasks except the final COPY of task files, so Docker caches the heavy
  layers), tests/test.sh (own copy of grader code + pristine parts -> /logs/verifier/reward.txt, test_fit cost
  applied, empty output -> 0), solution/solve.sh (reference solver).
  legacy_v0/harbor/build_tasks.py is a working pattern.
- Also build a small judging dataset `harbor_tasks/judge/` (L1 seed 0, L2 seed 0, L3 seed 0 as subfolders),
  so every judge run is one command on three tasks and stays cheap.
- `cadfix/harbor/agents.py`: a custom Harbor agent `StopEarlyAgent` (for `--agent-import-path`) that makes one
  inspection call inside the container and submits.
- Validate every task.toml with Harbor's own TaskConfig model (`pip install harbor` in a venv if needed).
- If a Docker daemon is available, run on `harbor_tasks/judge/`: `-a oracle`, `-a nop`, and the stop-early agent;
  record rewards and log paths in `docs/PROGRESS.md`. Do NOT run opencode or any paid model.

## M5: README and wrap-up

- `README.md` for judges (human tone, short): what the agent has to do, why it is hard (the three levels and what
  each tests; the go/no-go finding), how it is scored (gate, S1-S3, reward formula, test_fit cost), exploit
  table, results table from run_eval and from the Harbor runs, and the five commands, exactly:
  - reference: `harbor run -p harbor_tasks/judge -a oracle`
  - agent x3: `harbor run -p harbor_tasks/judge -a opencode -m <provider/model> -k 3`
  - do-nothing: `harbor run -p harbor_tasks/judge -a nop`
  - stop-early: `harbor run -p harbor_tasks/judge --agent-import-path cadfix.harbor.agents:StopEarlyAgent`
  - plus how to build all levels/seeds and run local run_eval without Harbor.
  Check every command really works (except opencode) and fix the README if a flag differs.
- A placeholder section "Harbor run log" where the user will add the OpenCode log and score.
- CLAUDE.md commands updated.
- Polish summary at the top of docs/PROGRESS.md: what works, numbers, what the user must do in the morning
  (the exact opencode command with a model placeholder), open problems, decisions.
