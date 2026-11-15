# Task 9: pre-final fixes before the one Opus 5.5 run

Read CLAUDE.md, docs/scenario.json (0.8-pre-final-run, decision_log entries "0.8"), docs/RUN_ANALYSIS_sonnet55.md.
We have credits for exactly ONE final run (Opus 5.5, harbor_tasks/judge, -k 3). Everything below must be done and
verified before it. Work without waiting for approval; commit after each part; Polish note in docs/PROGRESS.md.
Never tune numbers to pass; report what really happens. Do not edit docs/scenario.json.

## A. Container audit (what can the agent read?)

The agent has a shell inside the task container, so everything copied into `environment/` is readable.
1. List exactly what the image contains (our code and data). Keep only what the MCP server needs at runtime
   (cadfix core/checks/ops/env, the hinge_lid spec data used by the checks) and the public task files.
   Remove from the image: reference solver, generator feasibility scan, exploits, tests, docs, examples, gonogo,
   legacy_v0, anything else not needed at runtime.
2. No file in the container may contain V_ref, reference ops, best relief sizes, V_full_edge, V_identical or S3
   thresholds as numbers.
3. S3 is computed only by the verifier (from tests/). Remove `run_check_S3...` from the agent's tools; `test_fit`
   reports every check except S3. Instead add a free tool `changed_volume`: removed + added material vs the
   original, per editable part, in mm3 and % of the part. It must not reveal V_ref.
4. The oracle works from `solution/` alone (Harbor uploads it only for oracle runs): put what the reference solver
   needs into solution/, not into the image.
5. Confirm in Harbor 0.26 when `tests/` reaches a container (after the agent ends / separate verifier container);
   document it in DECISIONS.md.
6. Add a test that builds one task per level and fails if any forbidden file or string (points 1-2) appears in
   `environment/`.
7. Report what was leaking before the fix, if anything, and what the agent in the Sonnet run could have seen.

## B. Remove the test_fit cost

The counter lives in the agent-writable output dir, so it cannot be enforced. test_fit is free, like run_check.
Update grader, reward, tests, instruction, README, DECISIONS.

## C. Graceful MCP shutdown (EPIPE)

Do the reproduction proposed in RUN_ANALYSIS_sonnet55.md. Make the server shut down cleanly (stdin close and
SIGTERM handled, BrokenPipe on the final write ignored, flush, exit 0). Keep it even if the crash turns out to be
OpenCode's alone, and then document that in the README run-log section.

## D. instruction.md: make the scoring impossible to miss (no fix hints)

Add a short section right after the bug report, before Parts, titled "How you are scored", in plain words:
- If any gate fails, the reward is 0.
- A fix that makes the lid open to 110 deg with the required clearance earns 0.3 + 0.1 for printability.
- The remaining 0.6 is for changing as little material as possible: full 0.6 if your changed volume (removed +
  added) is within 1.15x of the best known fix for this task, 0 at 2x or more, linear in between.
  (Use the level's factors: L1 5x / 10x.)
- Example: a fix that works but changes twice as much material as necessary scores 0.4.
- You can measure your own changed volume at any time with `changed_volume` (free). `test_fit` and every
  `run_check_<id>` are free and unlimited (up to the 150 tool-call cap).
Keep the full formula further down as now. Do NOT add anything about where or how to cut (no "local", "per rib",
"relief", "notch", "chamfer"); extend the forbidden-word test to this section.

## E. Evidence that the gap is a decision, not ignorance

Extend docs/RUN_ANALYSIS_sonnet55.md (no new runs, only the existing logs):
- For each trial: did the agent mention minimal change / material / volume / S3 in its visible messages?
  Quote it. Did it read the scoring section? Did it compare alternatives? Did it measure per-rib differences?
- What exactly test_fit returned to it about S3 in that run (the old build).
- One line per trial: "knew the rule: yes/no/unclear; tried to reduce: yes/no".

## F. Rebuild and verify (all must pass before the Opus run)

1. Rebuild all harbor_tasks; validate every task.toml with Harbor's TaskConfig.
2. Fast tests, then the full suite.
3. On harbor_tasks/judge: oracle (expect 1.0 on all three), nop (0), stop-early (0).
4. Print the final instruction.md for L3 seed 0 into docs/instruction_L3_seed0_final.md so the user can read it.
5. README: update scoring (no test_fit cost), add the Sonnet run as "preliminary run on the previous build" with its
   numbers, leave a placeholder for the Opus run.
6. Final Polish summary at the top of docs/PROGRESS.md: what changed, verification results, and the exact Opus
   command to run.
