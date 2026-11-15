# Data format of a run

What one episode leaves behind, as the files exist in build `build-final` (and `build-sonnet-run`; the formats are
the same). Nothing here is new: the episode env (`cadfix/env/env.py`) writes the output dir, the verifier
(`tests/test.sh` -> `cadfix/grade.py`) writes the report, and Harbor writes everything around them.

The output dir has **the same format for every player**: an agent over MCP, the Harbor oracle (the reference solver
over MCP, `solution/solve.sh`), and the local scripted runs (`run_eval.py` -> `results/<agent>/<L>/seed_NNNN/`).
All of them call the same `Env.call(tool, **args)`. Checked on the Sonnet job, the oracle job `jobs/2026-11-15__07-37-23`
and `results/reference/L*/seed_0000`: the same file set, the same `episode.json` keys, the same `actions.jsonl` keys,
the same snapshot layout.

## Harbor trial directory

`harbor_runs/<run_id>/<task>__<id>/` (a byte-identical copy of `jobs/<job>/<task>__<id>/`, see `docs/RUNS.md`):

```
config.json, lock.json        Harbor's trial config; lock.json has the task digest (sha256 of the task dir)
result.json                   Harbor's result: verifier_result.rewards.reward, exception_info, agent_info
                              (name, version, model), agent_result (tokens, cost_usd), timings per phase
trial.log                     Harbor's log of the trial
exception.txt                 only if Harbor recorded an exception (e.g. OpenCode's EPIPE at exit)
agent/                        written by the agent harness
  trajectory.json             OpenCode: every step, tool call (MCP tools as cadfix_<tool>) and visible message
  opencode.txt                OpenCode's JSON event stream (stdout+stderr of `opencode run --format=json`)
  opencode/xdg-data/opencode/ OpenCode's own state: log/opencode.log, opencode.db, tool-output/
  setup/                      Harbor's agent install log
  oracle.txt                  oracle runs only: stdout of solution/solve.sh
artifacts/manifest.json       what Harbor copied out of the agent container
artifacts/output/             copy of the agent container's /output: the OUTPUT DIR below
artifacts/logs/artifacts/     empty
verifier/                     written by tests/test.sh in the separate verifier container
  reward.txt                  the one score in [0, 1]
  grade.json                  the full report (below)
  test-stdout.txt             "reward: <x>"
  grader_stderr.txt           the grader's stderr (usually empty or a shapely RuntimeWarning)
  actions.jsonl, episode.json copies of /output/actions.jsonl and /output/episode.json as the verifier received them
```

In git, `artifacts/output/` is excluded by the `output/` rule in `.gitignore`, so the STEP/GLB files exist only in
the local archive. `verifier/actions.jsonl` and `verifier/episode.json` are committed, and the RUN_ANALYSIS check
found them identical to the artifact copies in all 9 Sonnet trials.

## Output dir (`/output` in the container, `artifacts/output/` in the trial)

```
parts/<editable>.step         current state of every editable part (enclosure.step, lid.step); this is what is graded
episode.json                  counters and the submitted flag
actions.jsonl                 one JSON line per tool call
snapshots/NNN_<tool>/         the editable parts at the start and after every edit
```

`results/<agent>/<L>/seed_NNNN/` (local `run_eval.py`) has the same four entries plus `grade.json` (the same report
as `verifier/grade.json`) and `agent_log.txt` (the scripted agent's own notes, e.g. the reference solver's
measurements).

### `parts/<name>.step`

STEP AP214 of one B-rep solid, written by `kernel.export_step` after every edit to that part (and again by
`submit`, which only changes the STEP header timestamp). World coordinates of the task, mm. On L3 the whole assembly
is rotated and moved, so the parts are not axis-aligned. Fixed parts (`hinge_pin`, `lid_module`) are never written;
the grader takes them, and any editable part that is missing or unreadable, from its pristine copy.

### `episode.json`

```json
{"started": "2026-11-15T06:00:12+00:00", "calls": 15, "test_fit_calls": 1, "edits": 3, "submitted": true,
 "task": {"scenario": "hinge_lid", "level": "L2", "seed": 0}}
```

`calls` counts every tool call, including rejected ones; `edits` counts edit tools and `undo`. If the MCP server
restarts mid-episode it continues from this file and adds `"resumed": <n>` (no run so far has it). Rewritten after
every call.

### `actions.jsonl`

One line per call, appended after the call returns:

```json
{"n": 3, "time": "2026-11-15T06:00:18+00:00", "tool": "run_check", "args": {"check_id": "S1_opening"},
 "result": {"id": "S1_opening", "role": "objective", "passed": false, "score": 0.0, "metrics": {...}, "details": [...]},
 "seconds": 0.157}
```

- `n`: 1-based call number (= `episode.calls` at that call). `time`: UTC, seconds. `seconds`: tool run time.
- `tool`: the env's tool name. MCP `run_check_<id>` is logged as `run_check` with `args.check_id`; every other MCP
  tool keeps its name (`get_task`, `list_parts`, `part_info`, `list_edges`, `list_faces`, `find_edges_near`,
  `find_faces_near`, `measure`, `section`, `chamfer`, `fillet`, `offset_face`, `extrude_cut`, `cut_box`, `add_box`,
  `undo`, `test_fit`, `submit`).
- `args`: the arguments exactly as received.
- `result`: what the tool returned to the agent. A rejected call (bad argument, op failure, after `submit`, over the
  150-call cap) has `{"error": "<message>"}`. An edit returns `ok`, `part`, `removed_mm3`, `added_mm3` (vs the
  part before this edit), `volume_mm3`, `edits_so_far` and the part's new `edges` / `faces` lists.
  `test_fit` returns every check's result plus `test_fit_calls` and `test_fit_cost_so_far`.

### `snapshots/NNN_<tool>/`

`NNN` = `episode.edits` after the edit (`000_start` is written when the episode starts); `<tool>` = the edit tool
(`extrude_cut`, `cut_box`, `chamfer`, ..., or `undo`). Each holds every editable part, whether or not this edit
touched it:

- `<name>.step`: the B-rep, as in `parts/`.
- `<name>.glb`: the tessellated mesh the checks run on (`kernel.mesh_arrays`, exported with trimesh, no materials).
  Coordinates are the raw world coordinates in **mm, Z up**, not glTF's metres / Y up, so scale by 0.001 and rotate
  for a standard glTF viewer.

The last snapshot equals the graded `parts/` (symmetric-difference volume 0.00000 mm³ in all 9 Sonnet trials).

## `grade.json` (verifier report)

```
reward                        final reward (after the test_fit cost), = reward.txt
reward_before_test_fit_cost   reward from the checks alone
test_fit_calls, test_fit_cost max(episode.json counter, test_fit lines in actions.jsonl); cost from the spec
                              (first 2 free, then 0.02 each, at most 0.1). Edited parts with no episode record pay the cap
submission                    per editable part: "submitted" | "missing -> original" | "unreadable (...) -> original"
gates_ok, failed_gates        G1-G6
objective_met, progress       S1; progress = 0.5 x angle progress + 0.5 x clearance progress (used only if S1 not met)
scores                        {"printability": 0|1, "minimal_change": S3 score}
checks                        per check id (G1_valid_solids, G2_hinge_interface, G3_keep_in, G3_keep_out,
                              G4_closed_position, G5_seal, G6_not_rebuilt, S1_opening, S2_min_wall, S2_overhang,
                              S3_minimal_change): {passed, score, metrics, details}
level, seed, seconds
```

`checks.S3_minimal_change.metrics` has `removed_mm3`, `added_mm3`, `changed_mm3`, `changed_pct` and, in the verifier
only, `ratio_to_reference` (changed volume / V_ref) and `score`. `docs/RUNS.md` shows that ratio as "Vol / V_ref".
`checks.S1_opening.metrics` has `ok_until`, `original_ok_until`, `min_clearance`, `min_clearance_at`,
`first_overlap_deg`, `first_fail`.

## Run index (`runs/index.json`)

Written by `scripts/record_run.py`. One entry per run: `run_id`, `kind` (`harbor` | `manual` | `local`), `label`,
`notes`, `source` (job dir), `archive` (`harbor_runs/<run_id>`), `agent`, `agent_version`, `model`,
`harbor_version`, `n_attempts`, `started_at`, `finished_at`, `build` (`task_digests` from lock.json and
`matched_tags`: the git tags whose `harbor_tasks/judge` has exactly those digests), `summary` (mean, per-level
means and rewards, exceptions, cost) and `trials` (per trial: reward, exception, gates, S1, scores, changed volume
and ratio, MCP calls, edits, test_fit calls, cost). Non-Harbor entries carry their numbers in `tables`.
`docs/RUNS.md` is rendered from it.
