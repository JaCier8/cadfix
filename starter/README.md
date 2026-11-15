# cadfix: fix a 3D-printed hinge that jams

An RL environment for the AfterQuery "Break the Agent" track. The agent gets a printable box with a hinged lid,
as B-rep solids plus CAD tools over MCP. While the lid opens, a structural rib under each lid knuckle swings into
the top of the box's rear wall, so the lid jams somewhere around 40-70 deg and never reaches 110 deg. The agent
has to edit the parts so the lid opens to 110 deg with >= 0.3 mm clearance, without breaking the seal band, the
hinge, the ribs or the knuckle brackets, and with as little material removed as possible.

Nothing about the cause or the fix is given. The agent gets the bug report, every requirement with its threshold,
the scoring formula, the protected zones with coordinates, and tools to measure and check everything itself.

## Why it is hard

| Level | Geometry | What it tests |
|---|---|---|
| L1 | 2-3 identical ribs, axis-aligned | find the clash and size an asymmetric relief of the wall's outer top edge (a full-edge chamfer gets full points) |
| L2 | same parts, strict minimal-change score | realise the fix should be **local**: one relief per rib, and long enough past the rib ends (>= 0.3 mm clearance along the hinge too) |
| L3 | 3 **different** ribs, whole assembly rotated and moved in space | L2 + size each relief separately + work in a rotated frame (nothing is axis-aligned) |

Go/no-go (manual, no tools, three attempts with test_fit feedback): a weak model (Hydrogen) solved L1 seed 0,
but on L2 seed 0 it scored 0.103 -> 0.400 -> 0.400. Each time it tuned a full-edge chamfer (3.2x the volume
of the best known fix) and never tried a local relief.

Traps that score well below the reference, by design:

| Fix | Reward |
|---|---|
| one full-edge chamfer on L2/L3 (works, ~3-6x the material) | 0.400 |
| L3: identical reliefs sized for the worst rib (>= 1.4x the material) | 0.75-0.82 |
| reliefs exactly as long as the rib (rib ends rub) | 0.000 |
| relief 30 % too shallow | <= 0.11 |
| symmetric 45 deg chamfer (eats the seal band) | 0 on most seeds |

## How it is scored

Everything the grader checks is in the public spec (`spec.json` in the task, also in `instruction.md`). The same
check code runs in the agent's tools (`run_check_<id>`, `test_fit`) and in the verifier.

- **Gates** (any failure -> 0): G1 valid single solids; G2 hinge interface frozen (material around the pin axis
  unchanged); G3 keep-in zones (lid knuckles, ribs, module frame, seal band on both parts, enclosure knuckle
  brackets) keep >= 99 % of their material, keep-out (the lid module's volume) stays empty; G4 no collision when
  closed; G5 lid / wall-top contact >= 1.5 mm wide all around; G6 not rebuilt (envelope within 0.5 mm, <= 15 %
  of each part changed).
- **S1 opening** (objective): rotate the lid 0..110 deg in 1 deg steps; no overlap, clearance >= 0.3 mm from 10 deg.
- **S2 printability**: no new wall thinner than 1.2 mm, no new overhang steeper than 45 deg in print orientation
  (features < 0.2 mm ignored).
- **S3 minimal change**: changed volume vs the best known fix of the task (smallest valid relief per rib from an
  exact 2D scan): L1 full points up to 5x, zero at 10x; L2/L3 full up to 1.15x, zero at 2x. The agent is told the
  rule, never the volume.
- **Reward**: gate failed -> 0; S1 not met -> 0.25 x progress (progress = 0.5 x angle progress + 0.5 x
  clearance progress); S1 met -> 0.3 + 0.1 x printability + 0.6 x minimal change.
  `test_fit` (all checks at once): first 2 calls free, then -0.02 each, capped at -0.1. Single checks are free.

Doing nothing or stopping early scores 0. Any working fix beats any broken one, and a tailored fix beats a wasteful one.

## Reward integrity

The verifier runs in a **separate container** (Harbor `environment_mode = "separate"`). Only `/output` is copied
over from the agent's container, and the grader uses its own code, its own task copy and pristine parts. Missing,
garbage or unreadable files count as the original part, and a reward is always written. Exploit suite:
`python -m scenarios.hinge_lid.exploits --level L2,L3 --seeds 0` (full table in `docs/exploits.txt`):

| Exploit | L2 | L3 | Caught by |
|---|---|---|---|
| shorten the ribs / cut the lid's hinge side | 0.000 | 0.000 | G2, G3 keep-in |
| hollow the rear wall + full-edge relief | 0.300 | 0.300 | S2 thin walls, S3 |
| huge cut / cut through the seal band | 0.000 | 0.000 | G3, G5 seal |
| cut the knuckle brackets / widen the pin bores | 0.000 | 0.000 | G3, G2 |
| fill the box | 0.000 | 0.000 | G3 keep-out, G4, G6 |
| edit fixed parts (tool refuses; files written by shell are ignored) | 0.000 | 0.000 | fixed parts from pristine |
| spam test_fit / submit then keep editing | 0.000 | 0.000 | nothing fixed |
| overwrite outputs with garbage / original / delete them | 0.000 | 0.000 | treated as the original |
| scaled copy / lid saved already opened | 0.000 | 0.000 | G6 envelope, G2-G5 |
| edit the agent's own task files so its tools say "pass" | 0.000 | 0.000 | verifier has its own copies |

Known limitation: the test_fit counter lives in the agent's output dir. An agent can hide its calls, which gains
at most the 0.1 cap.

## Results

Local, without Harbor: `python run_eval.py --agent reference,do_nothing,stop_early --level L1,L2,L3 --seeds 0-9`
(`results/run_eval_20261115_011537.csv`):

| Agent | L1 | L2 | L3 |
|---|---|---|---|
| reference (tools only, `scenarios/hinge_lid/reference.py`) | 1.000 (10/10) | 1.000 (10/10) | 1.000 (10/10) |
| do_nothing | 0.000 | 0.000 | 0.000 |
| stop_early | 0.000 | 0.000 | 0.000 |

The reference solver uses only the agent's tools (27-33 calls, 2-5 s per task) and lands at 1.00-1.03x the best known
volume. Its design is in `docs/SOLVER_DESIGN.md`.

Harbor, on `harbor_tasks/judge` (L1, L2, L3 seed 0), logs in `harbor_runs/`:

| Run | Rewards | Mean |
|---|---|---|
| oracle (reference) | 1.0, 1.0, 1.0 | 1.000 |
| nop (do nothing) | 0.0, 0.0, 0.0 | 0.000 |
| stop-early | 0.0, 0.0, 0.0 | 0.000 |
| OpenCode, frontier model, x3 | see "Harbor run log" | |

## Commands

Setup (once): Docker, plus `pip install harbor==0.26.0` (tested in a Python 3.12 venv). Run from this directory.

```bash
# reference run
harbor run -p harbor_tasks/judge -a oracle
# agent x3
harbor run -p harbor_tasks/judge -a opencode -m <provider/model> -k 3
# do-nothing baseline
harbor run -p harbor_tasks/judge -a nop
# stop-early baseline (Harbor 0.26 takes a custom agent as -a module:Class; the repo must be on PYTHONPATH)
PYTHONPATH=. harbor run -p harbor_tasks/judge -a cadfix.harbor.agents:StopEarlyAgent
```

Harbor builds the task image from `environment/Dockerfile` on first use (about 4 min cold, about 2.2 GB). Running
`docker build -t cadfix-dev .` first shares the heavy layers.

All levels and seeds, and local evaluation without Harbor (inside the dev image):

```bash
docker build -t cadfix-dev .
alias dev='docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD":/app cadfix-dev'
dev python -m scenarios.hinge_lid.generator --level L1,L2,L3 --seeds 0-9 --out output/hinge_lid   # parts + hidden data
dev python -m scenarios.hinge_lid.task --level L1,L2,L3 --seeds 0-9                               # public task + pristine
dev python -m cadfix.harbor.build --level L1,L2,L3 --seeds 0-9                                    # harbor_tasks/<L>/seed_N
dev python run_eval.py --agent reference,do_nothing,stop_early --level L1,L2,L3 --seeds 0-9      # table + results/*.csv
dev python -m scenarios.hinge_lid.exploits --level L2,L3 --seeds 0                                 # exploit table
dev pytest -q -m "not slow"                                                                       # quick tests; full: pytest -q
```

## Harbor run log

_Placeholder: OpenCode run (model, command, `jobs/...` path, rewards per task, mean)._

## Layout

```
cadfix/            generic framework (knows nothing about hinges)
  core/            assembly (parts, joint, zones), kernel (B-rep + meshes), registry + spec (checks and reward as data)
  checks/          valid_solid, interface_frozen, keep_in/out, collision_free, sweep_clearance, contact_width,
                   min_wall, overhang, volume_change, envelope
  ops/             edit ops (chamfer, fillet, offset_face, extrude_cut, cut_box, add_box) and topology queries
  env/             episode env (log, snapshots, undo, test_fit) + MCP server (stdio)
  harbor/          Harbor task builder + StopEarlyAgent
  grade.py         verifier CLI
scenarios/hinge_lid/  generator (levels, hidden reference data), spec as data, task / instruction, reference solver,
                   exploits, dev tables
docs/              scenario.json (decisions), DECISIONS.md, SOLVER_DESIGN.md, PROGRESS.md, acceptance tables
```
