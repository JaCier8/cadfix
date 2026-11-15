# cadfix: fix a 3D-printed hinge that jams

An RL environment for the AfterQuery "Break the Agent" track.

## What the agent has to do

The agent gets a printable box with a hinged lid, as B-rep solids, plus CAD tools over MCP. While the lid opens, a
structural rib under each lid knuckle swings into the top of the box's rear wall. The lid jams somewhere around
40-70 deg and never reaches 110 deg. The agent has to edit the parts so that the lid opens to 110 deg with >= 0.3 mm
clearance. It must not break the seal band, the hinge, the ribs or the knuckle brackets, and it should change as
little material as possible.

Nothing about the cause or the fix is given. The agent gets the bug report, every requirement with its threshold,
the scoring formula, the protected zones with coordinates, and tools to measure and check everything itself:
inspect (`measure`, `section`, edge/face queries), edit (`chamfer`, `fillet`, `offset_face`, `extrude_cut`,
`cut_box`, `add_box`, `undo`), check (`run_check_<id>`, `test_fit`), `submit`. 150 tool calls, 1 hour.

## Why it is hard

| Level | Geometry | What it tests |
|---|---|---|
| L1 | 2-3 identical ribs, axis-aligned | find the clash and size a relief of the wall's outer top edge (a full-edge chamfer still gets full points) |
| L2 | same parts, strict minimal-change score | realise the fix should be **local**: one relief per rib, long enough past the rib ends (>= 0.3 mm clearance along the hinge too) |
| L3 | 3 **different** ribs, whole assembly rotated and moved in space | L2 + size each relief separately + work in a rotated frame (nothing is axis-aligned) |

Go/no-go (manual, no tools, three attempts with test_fit feedback): a weak model (Hydrogen) solved L1 seed 0. On
L2 seed 0 it scored 0.103 -> 0.400 -> 0.400: each time it tuned a full-edge chamfer (3.2x the volume of the best
known fix) and never tried a local relief.

Traps that score well below the reference, by design:

| Fix | Reward |
|---|---|
| one full-edge chamfer on L2/L3 (works, ~3-6x the material) | 0.400 |
| L3: identical reliefs sized for the worst rib (>= 1.4x the material) | 0.75-0.82 |
| reliefs exactly as long as the rib (rib ends rub) | 0.000 |
| relief 30 % too shallow | <= 0.11 |
| symmetric 45 deg chamfer (eats the seal band) | 0 on most seeds |

## How it is scored

Everything the grader checks is in the public spec (`spec.json` in the task, also in `instruction.md`). The agent's
tools (`run_check_<id>`, `test_fit`) and the verifier run the same check code.

- **Gates** (any failure -> 0): G1 valid single solids; G2 hinge interface frozen (material around the pin axis
  unchanged); G3 keep-in zones (lid knuckles, ribs, module frame, seal band on both parts, enclosure knuckle
  brackets) keep >= 99 % of their material, and the keep-out zone (the lid module's volume) stays empty; G4 no
  collision when closed; G5 lid / wall-top contact >= 1.5 mm wide all around; G6 not rebuilt (envelope within
  0.5 mm, <= 15 % of each part changed).
- **S1 opening** (objective): rotate the lid 0..110 deg in 1 deg steps; no overlap, clearance >= 0.3 mm from 10 deg.
- **S2 printability**: no new wall thinner than 1.2 mm, no new overhang steeper than 45 deg in print orientation
  (features < 0.2 mm ignored).
- **S3 minimal change**: changed volume (removed + added) vs the best known fix of the task, which is the smallest
  valid relief per rib from an exact 2D scan. L1: full points up to 5x, zero at 10x. L2/L3: full points up to
  1.15x, zero at 2x. The agent is told the rule, never the volume.
- **Reward**: gate failed -> 0; S1 not met -> 0.25 x progress (progress = 0.5 x angle progress + 0.5 x
  clearance progress); S1 met -> 0.3 + 0.1 x printability + 0.6 x minimal change.
  `test_fit` (all checks at once): first 2 calls free, then -0.02 each, capped at -0.1. Single checks are free.

Doing nothing or stopping early scores 0. Any working fix beats any broken one, and a tailored fix beats a
wasteful one.

## Commands (the five run types)

Setup (once): Docker, plus `pip install harbor==0.26.0` (tested in a Python 3.12 venv). Run from this directory.

```bash
# 1. reference run (the reference solver plays through the same MCP tools)
harbor run -p harbor_tasks/judge -a oracle
# 2. agent x3 (OpenCode)
harbor run -p harbor_tasks/judge -a opencode -m <provider/model> -k 3
# 3. do-nothing baseline
harbor run -p harbor_tasks/judge -a nop
# 4. stop-early baseline (Harbor 0.26 takes a custom agent as -a module:Class; the repo must be on PYTHONPATH)
PYTHONPATH=. harbor run -p harbor_tasks/judge -a cadfix.harbor.agents:StopEarlyAgent
# 5. all levels and seeds without Harbor: reference / do-nothing / stop-early, L1-L3 x seeds 0-9 (dev image below)
dev python run_eval.py --agent reference,do_nothing,stop_early --level L1,L2,L3 --seeds 0-9
```

`harbor_tasks/judge` holds L1, L2 and L3 seed 0. Harbor builds the task image from `environment/Dockerfile` on
first use (about 4 min cold, about 2.2 GB). Running `docker build -t cadfix-dev .` first shares the heavy layers.
To archive a finished job and add it to `runs/index.json` + `docs/RUNS.md`:
`python scripts/record_run.py jobs/<job> --label <name> --notes "..."`.

Dev image, generation and the other local tools:

```bash
docker build -t cadfix-dev .
alias dev='docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD":/app cadfix-dev'
dev python -m scenarios.hinge_lid.generator --level L1,L2,L3 --seeds 0-9 --out output/hinge_lid   # parts + hidden data
dev python -m scenarios.hinge_lid.task --level L1,L2,L3 --seeds 0-9                               # public task + pristine
dev python -m cadfix.harbor.build --level L1,L2,L3 --seeds 0-9                                    # harbor_tasks/<L>/seed_N
dev python -m scenarios.hinge_lid.exploits --level L2,L3 --seeds 0                                 # exploit table
dev pytest -q -m "not slow"                                                                       # quick tests; full: pytest -q
```

## Results

Harbor, `harbor_tasks/judge` (L1, L2, L3 seed 0), OpenCode 1.19.5, `-k 3`. All runs are listed in
[`docs/RUNS.md`](docs/RUNS.md), with logs in `harbor_runs/<run_id>/`. The file format is in
[`docs/DATA_FORMAT.md`](docs/DATA_FORMAT.md).

| Agent | Build | L1 | L2 | L3 | Mean | Log |
|---|---|---|---|---|---|---|
| reference (oracle) | build-final | 1.000 | 1.000 | 1.000 | **1.000** | `harbor_runs/oracle_2026-11-15__07-37-23` |
| Claude Opus 5.5, x3 | build-final | _pending_ | _pending_ | _pending_ | _pending_ | `jobs/2026-11-15__07-55-50` (running) |
| Claude Sonnet 5.5, x3 | build-sonnet-run | 1.000, 1.000, 1.000 | 1.000, 0.884, 0.621 | 0.850, 0.804, 0.400 | **0.840** | `harbor_runs/sonnet55_2026-11-15__06-48-21` |
| do nothing (nop) | build-final | 0.000 | 0.000 | 0.000 | 0.000 | `harbor_runs/nop_2026-11-15__07-38-15` |
| stop early | build-sonnet-run | 0.000 | 0.000 | 0.000 | 0.000 | `harbor_runs/stop_early_2026-11-15__02-22-43` |

`build-final` and `build-sonnet-run` are git tags. Each run's tasks are byte-identical to `harbor_tasks/judge` at its tag
(Harbor's task digests in the job's `lock.json`). The two builds differ only in the MCP server's shutdown code
(`cadfix/env/server.py`). The instruction, spec, tools and grader are the same, so the Sonnet and Opus numbers are
directly comparable.

Locally, without Harbor (`results/run_eval_20261115_011537.csv`): the reference solver scores 1.000 on 30/30
(L1-L3 x seeds 0-9) at 1.00-1.03x the best known volume, with 27-33 tool calls. do-nothing and stop-early score 0 on
30/30. The reference solver's design is in `docs/SOLVER_DESIGN.md`.

## Main finding: agents stop at the first passing fix

Sonnet 5.5 diagnoses the jam and fixes it locally every time. S1 and all gates pass in 9/9 trials, and no agent
fell for the full-edge chamfer that caught the weak model. It loses points only on minimal change:

- **Every agent called `test_fit` once and submitted the first fix that passed**, with a free `test_fit` and 120+
  tool calls left. None of the 9 tried to shrink a passing cut, and none compared two candidate fixes by volume.
  Every later change to a cut added material, because S1 still failed.
- **They knew the rule.** 8/9 final answers discuss S3 or the changed volume and say the score is unknown, e.g.
  "I can't see the grader's best-known fix, so I don't know how the S3 minimal-change score compares to it". One
  wrote "I did not try to shrink the pockets further, so some of the minimal-change score may be left on the table."
- **L3: one relief size for three different ribs (3/3).** Two agents had the per-rib difference in front of them,
  one from its own section scan (0.948 / 0.585 / 0.700 mm²) and one from our `measure` tool (overlap pieces of
  1.077 / 0.140 / 0.120 mm³). Both still cut the worst-case profile at all three ribs.

The information was there, so the failure is a decision, not a missing fact. Per-trial evidence:
[`docs/RUN_ANALYSIS_sonnet55.md`](docs/RUN_ANALYSIS_sonnet55.md) sections 4-5.

## Reward integrity

The verifier runs in a **separate container** (Harbor `environment_mode = "separate"`). Only `/output` is copied
over from the agent's container. The grader uses its own code, its own task copy and pristine parts. Missing,
garbage or unreadable files count as the original part, and a reward is always written. In the Sonnet run all 9
trials were checked by hand: no exploit, no reads outside the public task, graded parts identical to the env's last
snapshot. Exploit suite: `python -m scenarios.hinge_lid.exploits --level L2,L3 --seeds 0` (full table in
`docs/exploits.txt`):

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

## Known limitations

- **S3 is checkable by the agent in this build.** `run_check_S3_minimal_change` and `test_fit` report the agent's
  changed volume and the S3 rule. They never report V_ref or a score, and they always say `"passed": true`, because
  without V_ref the agent-side check has no threshold. The agents in the Sonnet run all said the score was
  unknown, so they did not read the `true` as full points. Still, a cleaner build would compute S3 in the verifier
  only and give the agent a plain `changed_volume` tool.
- **The test_fit counter lives in the agent-writable output dir** (`/output/episode.json`, `actions.jsonl`). The
  verifier takes the larger of the two counts, but an agent with a shell could edit both and hide extra test_fit
  calls. The most this can gain is the 0.1 cost cap. No agent touched these files (Sonnet: 1 test_fit call in
  every trial, counters match the trajectories).
- **OpenCode's own EPIPE crash at shutdown.** Some OpenCode 1.19.5 trials end with `NonZeroAgentExitCodeError`
  (`EPIPE: broken pipe, write` in OpenCode's Bun runtime), always after `submit` and the final answer. Rewards are
  unaffected: the verifier runs normally and Harbor's mean includes these trials (Sonnet: 4/9). It is not our MCP
  server: 0 EPIPE in 60 runs of OpenCode's MCP client stack against it (`scripts/epipe_repro`), and the server now
  exits 0 on stdin close, SIGTERM and broken pipe.

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
harbor_tasks/judge/   the judge set (L1-L3 seed 0), committed
harbor_runs/       archived Harbor jobs; runs/index.json + docs/RUNS.md list every run (scripts/record_run.py)
docs/              scenario.json (decisions), DECISIONS.md, SOLVER_DESIGN.md, RUN_ANALYSIS_sonnet55.md, DATA_FORMAT.md,
                   PROGRESS.md, acceptance tables
```
