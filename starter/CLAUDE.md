# CLAUDE.md

## What this project is

A reinforcement-learning environment for the AfterQuery "Break the Agent" hackathon track. An agent gets a
3D-printable assembly that does not work and must fix it with CAD operations. Judges score us on:
the gap between a frontier agent and our reference run (30), whether the agent's failures come from real
decisions with all needed information available (30), reward integrity against exploits (25), and craft:
one-command reproducible evaluation (15).

First scenario: **hinge_lid**. A box with a lid on a rear hinge. Closed, the lid fits; while opening, the lid
hits the top of the box's rear wall before 110 deg. The good fix is a chamfer/fillet on the outer top edge of the
rear wall, sized from the swept radius around the hinge axis, without destroying the seal band.

**Source of truth for all design decisions: @docs/scenario.json.** Do not change a decision recorded there
without asking the user first. If something is unclear or missing, ask instead of guessing.

## Required stack (from the organisers)

- Harbor task format: `instruction.md`, `task.toml`, `environment/Dockerfile`, `tests/`, `solution/`.
- Agent harness: OpenCode, e.g. `harbor run -p ./task -a opencode -m <provider/model>`.
- Verifier writes ONE score in [0, 1] to `/logs/verifier/reward.txt`.
- Submission needs at least one Harbor run log with its score and a short README.

## Architecture

```
cadfix/                      framework; knows NOTHING about hinges
  core/     assembly.py (Part, Joint, Zone, Assembly), kernel.py (B-rep + mesh helpers),
            spec.py (check specs from data), registry.py, reward.py (data-driven RewardPolicy)
  checks/   generic validations, one module per family, registered by type name
  ops/      edit.py (chamfer, fillet, offset_face, cut/add box, undo), topology.py (edge/face descriptions, queries)
  env/      env.py (episode state, JSONL log, snapshot after each edit), server.py (FastMCP, tools from registries)
  harbor/   build.py (any scenario -> Harbor task folders)
scenarios/
  hinge_lid/  generator.py, spec data, reference.py, bug_report.md
tests/        pytest: unit tests per check, exploit suites
docs/         scenario.json (decisions), TASKS.md (work plan), PROGRESS.md (log of finished tasks)
legacy_v0/    earlier mesh-only prototype; reuse its ideas/code where noted, do not import it from new code
```

Rules:
- A scenario is data + a generator + a reference solver. It composes generic checks with parameters.
- Every check in a scenario's spec is also exposed to the agent as a tool (`run_check(id)`), and `test_fit`
  runs them all. The grader and the agent's tools call the SAME check code.
- Grow the framework only by what the current scenario needs, but in generic form. No speculative features.

## Geometry rules

- Units mm, degrees. Z up.
- Edits happen on B-rep (OpenCascade through CadQuery). Parts are stored as STEP.
- Checks run on meshes (manifold3d / trimesh) tessellated from the B-rep after every edit, because sweeps need
  ~100 collision tests and must stay fast (a full sweep well under 5 s).
- Snap coordinates to 0.001 mm where values cross a file or tool boundary. Lesson from v0: float32 STL rounding
  left micron slivers that broke an otherwise exact patch.
- Edge/face ids change after every edit (topological naming). Every edit returns the fresh described list;
  geometric queries (`find_edges_near(point, direction)`) must not depend on ids.

## Reward and security rules

- Doing nothing and stopping early must score 0. Reward is measured against the initial state.
- Never reward similarity to a hidden "correct" model. Everything the grader checks is in the public spec.
- The agent container has a shell: it can read and modify any file there. The verifier in `tests/` must use
  its OWN copy of the grader code and pristine copies of all parts.
- Checks must be deterministic.

## How we work

- Work on exactly one task from `docs/TASKS.md` at a time. Do not start the next task unless asked.
- Start every task in plan mode and wait for the user to approve the plan.
- Every task ends with tests that pass (`pytest -q`) and its acceptance commands run, with real output.
- At the end of each task append a short entry to `docs/PROGRESS.md`: what was done, commands to run,
  results (numbers), open problems. Write that entry in Polish; code and comments in English.
- Keep code simple and readable; prefer a small working version over a clever one.

## Commands

(Fill in as they appear.)
- `docker build -t cadfix-dev .`: dev image (python:3.11-slim pinned by digest + requirements.lock). Cold build ~3.5 min, 2.2 GB.
- `docker run --rm cadfix-dev`: runs `pytest -q` (full suite, ~20 min: L3 generation is ~11 s per seed and each test module regenerates its seeds)
- `docker run --rm -v "$PWD":/app cadfix-dev pytest -q`: same with live code (package is installed editable)
- `docker run --rm -v "$PWD":/app cadfix-dev pytest -q -m "not slow"`: quick run, < 1 min (seed 0 of L1/L2, L3 seed 0 in test_levels only). `slow` = full 3D variant tables and multi-seed sweeps (marker in `pyproject.toml`, helpers in `tests/marks.py`); a task still ends with the full `pytest -q`
- `docker run --rm cadfix-dev python -m cadfix.smoke`: geometry stack check (CadQuery -> STEP -> manifold3d volumes)
- Live-code runs that write files: add `-u $(id -u):$(id -g) -e HOME=/tmp` so `output/` is not root-owned.
- Levels: L1 (easy, lenient S3), L2 (same parts, strict S3), L3 (3 different ribs, rotated world pose). Output: `output/hinge_lid/<L>/seed_NNNN/`.
- `... cadfix-dev python -m scenarios.hinge_lid.generator --level L1,L2,L3 --seeds 0-9 --out output/hinge_lid`: STEP parts + params.json per level/seed (per-rib scan, V_ref / V_full_edge / V_identical, hidden reference ops, pose for L3, seed replacement log)
- `... cadfix-dev python -m scenarios.hinge_lid.dev_sweep --level L1,L2,L3 --seeds 0-9 --out output/hinge_lid [--no-side] [-v] [--glb]`: acceptance tables (3D, real ops): original first contact + 7 enclosure variants (S1, gates, S3 vs V_ref, reward, pin/module/bracket collisions). L3 alone ~10 min (seed replacements). Full output: `docs/acceptance_2c.txt`.
- `... cadfix-dev python -m scenarios.hinge_lid.brief --level L --seed N`: what an agent would know (S3 as rule only; L3 in world coordinates only)
- `... cadfix-dev python -m scenarios.hinge_lid.evaluate --level L --seed N --ops ops.json [--hide-score]`: JSON list of ops (`chamfer`, `extrude_cut`, see the module docstring) -> test_fit-style report + reward; `--hide-score` = what we paste to models. Shortcut: `--top T --side S [--symmetric]` = one full-edge chamfer. Examples: `docs/examples/`.
- Go/no-go runs with a model: `scripts/brief.sh L S` (brief to paste), `scripts/try.sh L S ops.json` (stdout = `--hide-score` report to paste; appends reward, S1, volume/V_ref to `gonogo_log.csv`, private and gitignored). Ops format: `gonogo/README.md`.
- Tasks (task 4+): `... python -m scenarios.hinge_lid.task --level L --seeds N` -> `output/tasks/<L>/seed_NNNN/{task,pristine}` (public task: task.json, spec.json, parts; private: grader.json with V_ref). Rebuild after changing zones / spec.
- Grader: `... python -m cadfix.grade --task-dir T/task --pristine T/pristine --submitted OUT --level L --out report.json --reward-file reward.txt`
- MCP server: `CADFIX_TASK_DIR=T/task CADFIX_OUT_DIR=OUT python -m cadfix.env.server` (stdio); shell calls: `python -m cadfix.env.cli get_task submit`
- Local eval: `... python run_eval.py --agent reference,do_nothing,stop_early --level L1,L2,L3 --seeds 0-9 [--mcp]` -> table + `results/*.csv`
- Exploits: `... python -m scenarios.hinge_lid.exploits --level L2,L3 --seeds 0` (table in `docs/exploits.txt`); acceptance vs 2c: `... python -m scenarios.hinge_lid.acceptance`
- Harbor tasks: `... python -m cadfix.harbor.build --level L1,L2,L3 --seeds 0-9` / `--judge` (harbor_tasks/judge, committed); runs (host, harbor 0.26 in a venv): `harbor run -p harbor_tasks/judge -a oracle` / `-a nop` / `-a opencode -m <provider/model> -k 3`; stop-early: `PYTHONPATH=. harbor run -p harbor_tasks/judge -a cadfix.harbor.agents:StopEarlyAgent`
- EPIPE reproduction (OpenCode's MCP client stack on Bun, no model): `docker build -t cadfix-epipe scripts/epipe_repro && docker run --rm -v "$PWD":/app cadfix-epipe bash /app/scripts/epipe_repro/run.sh 20`; server exit codes: `... cadfix-dev python scripts/epipe_repro/server_exit.py`
- Delete `output/hinge_lid` after changing the generator: the scripts only generate missing level/seed folders.
- Design decisions not in scenario.json: `docs/DECISIONS.md`.
- Dependencies: change `pyproject.toml` ranges, then regenerate `requirements.lock` with `pip freeze` in python:3.11-slim.
