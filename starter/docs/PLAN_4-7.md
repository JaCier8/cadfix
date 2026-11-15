# Plan: tasks 4-7 (autonomous overnight run, docs/TASK_4-7.md)

Spec: docs/scenario.json 0.7-levels-tuned. Decisions go to docs/DECISIONS.md (D11+), notes to docs/PROGRESS.md.
After each milestone: `pytest -q -m "not slow"` green, commit `4-7 Mx: ...`, Polish note. Full suite at the end
of M3 and M5.

## Architecture in one picture

```
generator (dev, hidden data)          build (dev)                         agent container            verifier container
params.json + STEP  ──────────────►  public task dir  ───────────────►  /task  (public)            /tests/task (own copy)
  V_ref, reference ops, pose           task.json  (parts, joint,          MCP server cadfix         /tests/pristine (STEP + grader.json: V_ref)
                                       zones, print dirs, frame)          (cadfix.env.server)       /tests/cadfix (own grader code)
                                       spec.json  (checks as data,        writes /output:           /output  (artifact copied from the agent
                                       no V_ref)                           parts/*.step, actions.jsonl, container by Harbor, separate mode)
                                       parts/*.step                        episode.json, snapshots/   -> /logs/verifier/reward.txt
                                     private: pristine/grader.json (V_ref)
```

- Everything the grader checks is in the public spec (spec.json) except V_ref, which the agent only gets as the
  S3 rule (scenario.json disclosure). The grader takes V_ref from its own pristine/grader.json.
- The same check code runs in the agent's tools (run_check_<id>, test_fit) and in the grader. Without V_ref the
  tools report S3 as volume and % only.
- Harbor verifier in `environment_mode = "separate"` (Harbor 0.26): a fresh container from the same image, only
  `/output` is copied over as an artifact. The agent can therefore not tamper with the libraries or files the
  verifier uses (checked in Harbor's source: trial.py `_run_separate_verifier`, artifact_handler.upload_artifacts).

## M0: docs/SOLVER_DESIGN.md (before any code)

## M1 (task 4): generic checks + reward from data + grader CLI
1. `cadfix/core/assembly.py`: Part, Joint (revolute), Region (oriented box | cylinder), Zone (keep_in/keep_out,
   part, region, attached), Assembly (load from task dir: task.json + STEP).
2. `cadfix/core/registry.py`: check registry; `CheckResult(passed, score, metrics, details)`.
   `cadfix/core/spec.py`: CheckSpec list from spec.json; `RewardPolicy.from_spec` (gates, objective, score
   weights, S3 factors).
3. `cadfix/checks/*`: valid_solid, interface_frozen, keep_in, keep_out, collision_free, sweep_clearance (with an
   optional evaluation frame: L3 sweeps ~10x faster in the joint-aligned frame), contact_width, min_wall and
   overhang (NEW thin walls / overhangs vs the original, 0.2 mm feature filter), volume_change, envelope.
4. Generator: all keep-in zones (lid knuckles, ribs, module frame, seal band on both parts, brackets) as world
   regions in params.json; `scenarios/hinge_lid/spec.py` = the spec as data per level.
5. `cadfix/grade.py` CLI: `--task-dir --pristine --submitted --level [--out] [--reward-file]`; missing /
   unreadable submission -> pristine parts (reward 0), reward.txt always written; test_fit cost applied from
   episode data.
6. `scenarios/hinge_lid/task.py`: generator output -> public task dir + private pristine dir.
7. Acceptance: M6 variants (L1/L2/L3 seeds 0-9) through the new grader vs docs/acceptance_2c.txt
   (`scenarios/hinge_lid/acceptance.py`, output `docs/acceptance_4.txt`); differences explained.
   devgrade/evaluate switch to the new grader (old dev checks removed).

## M2 (task 5): ops, env, MCP server
1. `cadfix/ops/topology.py`: describe edges/faces (world, 0.001 mm), find_edges_near, find_faces_near.
2. `cadfix/ops/edit.py`: + fillet, offset_face (planar push/pull), cut_box, add_box (oriented boxes); edges
   and faces by id or by point; registry with parameter docs.
3. `cadfix/env/env.py`: Env(task_dir, out_dir): state, undo stack, JSONL log, snapshots (STEP + GLB) at start
   and after each edit, cap 150, run_check, test_fit (count in episode.json; cost in the grader), submit.
4. `cadfix/env/server.py`: FastMCP stdio, tools generated from the registries + query tools + run_check_<id>.
5. `scenarios/hinge_lid/instruction.py`: instruction.md from public data, leak test (brief's word list).
6. MCP smoke test with a real stdio client on L2 seed 0: reference ops via tools, test_fit passes, grader 1.0.

## M3 (task 6): reference solver, baselines, exploits, run_eval
1. `scenarios/hinge_lid/reference.py` exactly as SOLVER_DESIGN.md; tool client interface (in-process or MCP).
2. `cadfix/agents.py`: do_nothing, stop_early.
3. `run_eval.py`: agent x level x seeds -> table + CSV in results/.
4. `tests/test_exploits.py` (list from TASK_4-7), each < 0.4.
5. Acceptance: reference >= 0.95 on L1/L2/L3 seeds 0-9, baselines 0, exploits below limit. Full suite.

## M4 (task 7): Harbor
1. `cadfix/harbor/build.py`: level+seed -> harbor_tasks/<L>/seed_<n>/ (instruction.md, task.toml, environment/
   with identical heavy layers + final COPY of the public task, tests/ with own grader + pristine, solution/).
   `harbor_tasks/judge/` with L1/L2/L3 seed 0.
2. `cadfix/harbor/agents.py`: StopEarlyAgent.
3. Validate task.toml with harbor's TaskConfig; run oracle / nop / stop-early on judge if Docker works.

## M5: README, CLAUDE.md, PROGRESS summary, full suite.

## Risks
- L3 generation is slow (~11 s/seed, more with replacements); generated data is cached in output/.
- Harbor separate-verifier mode is new; if it fails locally, fall back to shared mode and record it (the
  verifier then runs Python in isolated mode from /tests, but site-packages tampering stays an open problem).
