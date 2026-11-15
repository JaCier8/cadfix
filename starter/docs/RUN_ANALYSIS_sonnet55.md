# Run analysis: OpenCode + claude-sonnet-5-5 on harbor_tasks/judge

Job `jobs/2026-11-15__06-48-21` (Harbor 0.26, OpenCode 1.19.5, `-k 3`, 4 concurrent trials, 9 trials in total).
Harbor mean **0.840**, cost $4.23, 4 trials flagged `NonZeroAgentExitCodeError`.

| Level | Trials | Rewards | Mean | Reference (oracle) |
|---|---|---|---|---|
| L1 | 3 | 1.000, 1.000, 1.000 | 1.000 | 1.000 |
| L2 | 3 | 1.000, 0.884, 0.621 | 0.835 | 1.000 |
| L3 | 3 | 0.850, 0.804, 0.400 | 0.685 | 1.000 |

Sources read for every trial: `agent/trajectory.json`, `agent/opencode.txt`, `agent/opencode/xdg-data/opencode/log/opencode.log`,
`trial.log`, `result.json`, `exception.txt`, `verifier/{grade.json,reward.txt,grader_stderr.txt,episode.json,actions.jsonl}`
and `artifacts/output/{actions.jsonl,episode.json,parts,snapshots}`.

The model's thinking is **not readable**: OpenCode stored every `reasoning` part with an empty `text` and only an
encrypted Anthropic signature. The quotes below therefore come from the visible messages (short interim notes and
the final answer) and from the agents' own scripts and their outputs.

Best known volume V_ref (from `tests/pristine/grader.json`): L1 / L2 seed 0 25.83 mm³, L3 seed 0 15.91 mm³.

## 1. Per-trial table

MCP = calls to the `cadfix` server (identical in the trajectory, `episode.json` and `actions.jsonl` for every
trial). Shell = OpenCode `bash` tool calls. No other OpenCode tool (read, write, edit, glob, grep, webfetch) was used.

| Trial | Task | Reward | Exception | MCP calls by tool | Shell | test_fit | Final edits (all on `enclosure`; lid untouched) | Vol / V_ref | S1 |
|---|---|---|---|---|---|---|---|---|---|
| QjRN4co | L1 s0 | 1.000 | no | get_task 1, list_parts 1, run_check_S1 2, measure 5, section 2, cut_box 6, test_fit 1, submit 1 (19) | 0 | 1 | 3 rectangular notches 8.8×0.7×1.6, then deepened by 3 boxes 8.8×0.9×2.3 (y 57.35–58.25, z 29.3–31.6) | 49.37 mm³ = 1.91× | pass, min clr 0.300 |
| QofdJZK | L1 s0 | 1.000 | no | get_task 1, list_parts 1, run_check_S1 3, measure 6, section 2, cut_box 9, test_fit 1, submit 1 (24) | 0 | 1 | 3 rounds of 3 boxes: 8.6×0.7×2.5, widened to 9.0, deepened by 0.3 → notches 9.0 × 0.9 × 2.0 | 48.60 mm³ = 1.88× | pass, 0.35 |
| u2d86jU | L1 s0 | 1.000 | no | get_task 1, list_parts 1, run_check_S1 3, measure 6, section 5, cut_box 3, extrude_cut 3, test_fit 1, submit 1 (24) | 0 | 1 | 3 boxes 8.9×0.8×2.0 + 3 extrude_cuts of a 10-point swept-arc profile, 8.9 long | 54.00 mm³ = 2.09× | pass, 0.35 |
| AXwNsaV | L2 s0 | 1.000 | yes: EPIPE at OpenCode exit | get_task 1, list_parts 1, run_check_S1 2, measure 4, section 2, extrude_cut 3, test_fit 1, submit 1 (15) | 0 | 1 | 3 extrude_cuts of a 4-point profile (y 57.4–58.3, z 29.55–31.6), 8.9 long per rib | 27.67 mm³ = **1.07×** | pass, 0.321 |
| gJP7UPj | L2 s0 | 0.621 | no | get_task 1, list_parts 1, run_check_S1 2, measure 4, section 2, extrude_cut 3, test_fit 1, submit 1 (15) | 1 | 1 | 3 extrude_cuts of a 13-point arc profile, R = 3.95 mm about the hinge axis (y 57.08–59.5, z 29.13–33.0), 8.8 long | 43.56 mm³ = 1.69× | pass, 0.300 |
| znT7Qc9 | L2 s0 | 0.884 | yes: EPIPE at OpenCode exit | get_task 1, list_parts 1, run_check_S1 1, measure 4, section 2, extrude_cut 3, test_fit 1, submit 1 (14) | 0 | 1 | 3 extrude_cuts of a 7-point arc profile, R ≈ 3.8 mm (y 57.23–58.6, z 29.48–31.92), 9.0 long | 33.95 mm³ = 1.31× | pass, 0.35 |
| Vs6f6U7 | L3 s0 | 0.850 | yes: EPIPE at OpenCode exit | get_task 1, list_parts 1, run_check_S1 2, measure 6, section 2, extrude_cut 3, test_fit 1, submit 1 (17) | 3 | 1 | 3 **identical** 5-point profiles (2.39 × 1.49 in the rib section) in the rotated frame, 7.8–7.9 long | 21.68 mm³ = 1.36× | pass, 0.339 |
| vtetXAU | L3 s0 | 0.804 | no | get_task 1, list_parts 1, run_check_S1 2, measure 3, section 3, extrude_cut 3, run_check G2/G3/G5 1 each, test_fit 1, submit 1 (18) | 19 | 1 | 3 **identical** 7-point profiles (≈ 2.7 × 1.25, "45° chamfer"), 7.6 long | 22.72 mm³ = 1.43× | pass, 0.35 |
| yUegVYW | L3 s0 | 0.400 | yes: EPIPE at OpenCode exit | get_task 1, list_parts 1, run_check_S1 3, measure 8, section 3, list_faces 1, cut_box 6, undo 3, test_fit 1, submit 1 (28) | 5 | 1 | 3 identical boxes 7.4 × 2.6 × 0.74 (failed S1, undone 3×), then 3 **identical rectangular boxes** 7.54 (axis) × 3.0 × 0.99 | 37.64 mm³ = 2.37× | pass, 0.35 |

Every trial passed all gates and both printability checks. S3 scores: L1 1.0 ×3 (≤ 5× is full points), L2
1.0 / 0.807 / 0.369, L3 0.750 / 0.673 / 0.0. No test_fit cost anywhere: each agent called it exactly once.
Agent run time 74–686 s (limit 3600 s), at most 28 of 150 tool calls.

## 2. Integrity

**Verdict: all 9 trials legit.** Nothing suspicious and no exploit.

**What the agents read.** Every shell command is listed in the trajectories. Files outside `/tmp` that any agent
read or listed:

- `/task/parts/{lid,enclosure,lid_module}.step` and `/output/parts/*.step`, loaded with CadQuery. These are the
  public task files; the instruction says "The public task files (the same data the tools use) are in `/task`".
- `ls /task /output /output/parts ...; ls /app` (Vs6f6U7). Its output showed only `requirements.lock` in `/app`.
- `ls /task /task/* /output/parts` (yUegVYW), `ls /task /output/parts` (vtetXAU).
- Library probes such as `python3 -c "import OCP"`, `import cadquery`, `import trimesh`, `import shapely; print(shapely.__version__)`.

No command touched `/opt/cadfix` (our code), `/solution`, `/tests`, `params.json`, the generator, the reference
solver, `docs/examples` or `grader.json`. None of those except `/opt/cadfix` (generic code, no scenario data) is
in the agent image anyway. The verifier's data sits in a separate container.

**Writes.** Shell writes went only to the agents' scratch scripts: `/tmp/opencode/{a,b,sw,sw2,sw3,prof,run1..run5}.py`
and `/tmp/d.py`. There was one in-place edit, of the agent's own script: `sed -i ... run5.py`. Nothing was written to
`/output` by shell.

To confirm, I compared each graded `parts/*.step` with the last snapshot written by the env after the agent's last
edit tool call. The symmetric-difference volume was 0.00000 mm³ for both parts in all 9 trials. The files differ
byte-wise only because `submit` re-exports them with a new STEP header timestamp.

**test_fit counter / action log.** `episode.json` says `test_fit_calls: 1` in all trials. That matches the single
`cadfix_test_fit` call in each trajectory. The number of `actions.jsonl` lines equals the number of MCP calls in the
trajectory, and the verifier's copy is identical to the artifact copy. No shell command mentioned `episode.json` or
`actions.jsonl`.

**Network.** OpenCode's log shows only the model API: provider `anthropic`, `claude-sonnet-5-5` for the agent and
`claude-haiku-5-5` for OpenCode's session title, 9 calls. No shell command used `curl`, `wget`, `pip` or any URL.
Harbor's agent setup downloads nvm/node/OpenCode via `curl` before the agent starts; that is harness setup, not
the agent.

**Most "creative" behaviour, still legit.** Three L3 agents rebuilt our analysis themselves with CadQuery and
OCP on the public STEP files: the rotated sweep, intersections, and 2D sections along the hinge axis. Examples:

```
vtetXAU: lid.rotate(pt,pt+ax,a); c=r.intersect(enc)  ...  for a in range(30,111,2): ... u.fuse(c)
vtetXAU: sc=BRepAlgoAPI_Section(shape.wrapped, gp_Pln(gp_Pnt(*p),gp_Dir(*A)))  # own swept-profile scan, 26 s
yUegVYW: d=BRepExtrema_DistShapeShape(l,enc); d.Perform()   # own clearance check at 46/70/101/110 deg
```

This is real engineering with public data, the same information the MCP tools give. Writing an editable part
directly with CadQuery would also have been graded the normal way; no agent did it.

## 3. The 4 exceptions

| Trial | Reward | Reward valid? |
|---|---|---|
| AXwNsaV (L2) | 1.000 | yes |
| znT7Qc9 (L2) | 0.884 | yes |
| Vs6f6U7 (L3) | 0.850 | yes |
| yUegVYW (L3) | 0.400 | yes |

**Exact cause.** `opencode run` exited with code 1 after an unhandled stream error in its Bun/Node runtime:

```
error: EPIPE: broken pipe, write
      at emitError (node:events:50:13)
      at emitErrorNT (internal:streams/destroy:88:12)
      at emitErrorCloseNT (internal:streams/destroy:69:14)
```

Harbor turns exit code 1 into `NonZeroAgentExitCodeError` (`exception.txt`: "Command failed (exit 1): ... opencode
... run --format=json ...").

**When it happens: at OpenCode's shutdown, after the work was finished.** In all 4 trials:

- the agent had already called `submit` successfully;
- the last JSON event is the final answer with `"reason":"stop"`.

In 3 of the 4 OpenCode logs the last entries are `exiting loop` and then `disposing instance`. The 4th log
(AXwNsaV) is cut off after the last step. The same cut-off also happens in two trials that exited cleanly
(QofdJZK, u2d86jU), so it says nothing on its own. The error text appears at the top of `opencode.txt` only
because stderr is unbuffered and stdout is not.

**What it is not:**
- a timeout: agent run 74–209 s against 3600 s;
- the tool-call cap: at most 28 of 150;
- an MCP tool error: every cadfix call returned normally;
- our grader: the verifier ran normally, reward was written, and `grader_stderr.txt` holds only a shapely
  RuntimeWarning, which also appears in clean trials.

**Whose bug.** OpenCode's. It writes to a pipe whose reader has already gone and doesn't handle the `error`
event. The only pipe-connected child alive at that point in every trial is our MCP server (`python3 -m
cadfix.env.server` over stdio; 2 of the 4 failing trials used no shell at all). So the most likely trigger is
OpenCode closing the local MCP server: it stops the child, then flushes a write to its stdin. It hit 4 of 9 runs
at random; it doesn't correlate with level, shell use or run length. Our server does not exit on `submit`; it only
stops when its stdin closes or it is killed.

**Impact.** None on the score: rewards were recorded and Harbor's mean (0.840) includes all 9 trials. It only
makes the job summary say "4 errors". Retries are off for this exception type, so nothing was re-run.

**Proposed fix (ours to try, not applied):**
1. **Reproduce without a model, for free.** Write a tiny Node script with `@modelcontextprotocol/sdk`'s
   `StdioClientTransport`: start `python3 -m cadfix.env.server`, call `get_task` and `submit`, then `close()`.
   Run it 20× in the task image and see whether EPIPE shows up. That tells us whether our server's exit timing
   matters.
2. **If it does,** make the server shut down gracefully on SIGTERM: keep reading stdin until EOF instead of
   dying at once. Or wrap the command in `task.toml` so stdin stays open until the client closes it. Then
   re-check with the script from step 1.
3. **If it doesn't** (pure OpenCode bug), say so in the README's Harbor run log: "4/9 trials end with OpenCode
   EPIPE at shutdown after submit; rewards unaffected". Optionally pin or bump the OpenCode version.

## 4. Failure modes per level (for the demo)

The weak-model trap from the go/no-go ("one full-edge chamfer, 3–6× the material") **did not catch
Sonnet 5.5**. All 9 agents found the right cause:

- ribs under the lid knuckles hit the top of the rear wall;
- hence one local relief per rib, on the enclosure only, with the lid untouched.

Each agent's process was nearly identical:

1. Run `get_task`, then `run_check_S1`, which shows the jam at ~45–46° on L1/L2 and ~37° on L3.
2. Use `measure` at 60/90/110° to get the overlap pieces per rib, then `section`.
3. Make 3 cuts.
4. Run `test_fit` once and `submit` right away.

The gap to the reference comes from **one decision: stopping at the first fix that passes**.

- Every agent called `test_fit` once and submitted on the first all-pass, with one free `test_fit` and 120+ tool
  calls left.
- Every agent knew the S3 rule from the instruction (L2/L3: full points only up to 1.15× the best known fix).
  In its final answer each one said it could not see the reference, e.g. "I can't see the grader's best-known
  fix, so I don't know how the S3 minimal-change score compares to it" (AXwNsaV).
- None tried to shrink a passing cut.

So the information was there and the failure is a real decision, not a missing fact.

**L1 (lenient S3): all 1.000.**
- All three agents used rectangular notches (`cut_box`) per rib, sized by trial and error against `run_check_S1`.
  One agent added swept-arc profiles on top.
- They landed at 1.88–2.09× V_ref, well inside L1's 5× full-points rule, so L1 does not separate the reference
  from the agent. That is intended: L1 is the "can you find the clash" level.
- Typical iteration (QjRN4co): "my first cuts were too shallow. The lid reached 65° with only 0.16 mm of
  clearance, so I lowered the notch floor and extended the cuts back to y = 57.35."

**L2 (strict S3): 1.000 / 0.884 / 0.621.**
- AXwNsaV hit the per-rib fix almost exactly (1.07×): a 4-point profile following the rib-corner sweep, 0.9 mm
  into the wall and 2.05 mm down, 8.9 mm long per rib. The reference is 0.9 × 2.15 × 8.9.
- The other two cut a **circular arc around the hinge axis**, which also removes wall material the rib never
  sweeps through. That is the common mistake on L2.
  - gJP7UPj: "Each notch follows an arc 3.95 mm from the hinge axis, which is the rib's swept radius plus the
    0.3 mm clearance margin." Its profile also runs above the wall top and past the outer face (y up to 59.5,
    z to 33.0). Result 1.69×, S3 0.37.
  - znT7Qc9: arc R ≈ 3.8 mm, 1.31×, S3 0.81.
- Lengths were right in all three (rib + ~0.3 mm each side), so the "rib ends rub" trap did not trigger.

**L3 (3 different ribs, rotated pose): 0.850 / 0.804 / 0.400.** The intended L3 trap worked in **3/3** trials.
- All agents handled the rotated frame correctly: cuts placed along the world hinge axis, profiles in the
  rib's own (u, v) section.
- But all three used **identical reliefs for three different ribs**. The reference reliefs per rib are
  0.75 × 2.75, 0.65 × 1.50 and 0.70 × 1.70 mm (7.53 mm long). One profile sized for the worst rib costs
  1.36–1.43× V_ref, so S3 drops to 0.67–0.75.

| Trial | Reliefs | Vol / V_ref | S3 | Reward |
|---|---|---|---|---|
| Vs6f6U7 | one 5-point profile, copied 3 times: "It sits at the three lug positions along the hinge axis and clears the lug sweep by about 0.34 mm." | 1.36× | 0.75 | 0.850 |
| vtetXAU | one "45° chamfer" profile, copied 3 times (details below) | 1.43× | 0.67 | 0.804 |
| yUegVYW | identical rectangular boxes 3.0 deep × 0.99 into the wall | 2.37× | 0 | 0.400 |

- **vtetXAU** is the best demo moment. It wrote its own per-rib sweep scan (19 shell calls, ~10 min). The scan
  **measured that the ribs differ**, with swept-overlap areas of 0.948 / 0.585 / 0.700 mm². That ranks them like
  the reference (rib 0 worst, rib 1 smallest). Then it cut the same worst-case profile at all three: "I cut a
  small 45° chamfer into the top edge of the rear wall, on the hinge-facing side, at each of the three lid
  knuckles."
- **yUegVYW**: a rectangle removes about twice the triangular relief the sweep needs, so it ended past the 2× zero
  line. It knew it was leaving points: "I did not try to shrink the pockets further, so some of the minimal-change
  score may be left on the table."
  - Its first attempt (2.6 × 0.74 boxes) still failed S1 at 101° (0.19 mm, from its own `BRepExtrema` check).
  - It undid them and enlarged all three uniformly with an extra margin (`m=0.36`) rather than only the rib that
    failed.

**Typical mistakes, in order of cost:**
1. Stopping at the first passing fix, never trading volume against the S3 rule (all 9 trials).
2. L3: one relief size for all ribs although the ribs differ, and in vtetXAU's case although the agent had
   measured the difference (3/3).
3. Over-cutting shape: a full arc or disk around the axis (L2), or a rectangular pocket instead of a relief
   that follows the sweep (L3 yUegVYW).

**One-line demo summary:** Sonnet 5.5 diagnoses the jam and fixes it locally every time (S1 9/9, gates 9/9).
It loses points only on minimal change, by settling on the first passing cut and by not sizing the three L3
reliefs separately. L1 1.00, L2 0.84, L3 0.68 against the reference's 1.00 on all levels.

## Update (2026-11-15): reproduction done

`scripts/epipe_repro/` ran OpenCode's MCP client stack (MCP SDK 1.29.0 on Bun 1.4.4, no model) against our server:
0 EPIPE in 60 runs (normal shutdown, SIGTERM during a write, SIGKILL then a write), with the old and the new server.
The crash is OpenCode's alone. The server now shuts down gracefully anyway (exit 0 on stdin close, SIGTERM and
broken pipe; WARNING-level logging). The README run-log section notes it. Details: `scripts/epipe_repro/README.md`.

## 5. Evidence that the gap is a decision, not ignorance

No new runs. Sources: the archived job `harbor_runs/sonnet55_2026-11-15__06-48-21` (identical copy of
`jobs/2026-11-15__06-48-21`): every `text` part in `agent/opencode.txt`, the tool calls and outputs in
`agent/trajectory.json`, and `verifier/actions.jsonl`. The reasoning parts are encrypted (see the top), so
"mentioned" below means **in a visible message**. The build is `build-sonnet-run` (c2b3560).

### What the agent was told about S3 before it acted

Every trial got the same three statements, in the prompt and again in `get_task`:

- the S3 description in the spec list: "changed volume (added + removed) vs the original parts; full points if the
  changed volume is within 1.15x of the best known fix for this task, zero at 2x (linear in between)" (L1: 5x / 10x);
- `get_task.rules.S3`: the same rule;
- the reward formula: "S1 met -> 0.3 + 0.1 * printability + 0.6 * minimal_change; minus the test_fit cost", followed
  by the test_fit cost line ("the first 2 calls are free, then each call costs 0.02 ...").

All 9 trials called `get_task` first. 8 of 9 final answers or interim notes refer to the test_fit cost line, which
comes right after the reward formula. That is direct evidence they read the scoring paragraph: "Now the other checks
(test_fit first 2 calls are free)" (u2d86jU), "Run the full check (free first call)" (AXwNsaV), "I used one `test_fit`
call, within the two free ones, so there was no cost" (Vs6f6U7). Only yUegVYW does not mention it.

### What test_fit returned about S3 (old build)

`test_fit` compacts each check to `passed` + `details`. For S3 that was, verbatim (AXwNsaV):

```json
"S3_minimal_change": {"passed": true, "details": [
  "changed volume 27.672 mm3 (removed 27.672, added 0.000) = 0.0559 % of enclosure, lid",
  "scored by the rule: full points within 1.15x of the best known fix for this task, zero at 2x"]}
```

The result also carried `"note": "minimal change is scored by the grader with the rule in spec.json (best known fix
not shown)"`. So the agent saw its own changed volume and the rule, never V_ref or a score. `"passed": true` is what
the agent-side S3 check always returns, because without V_ref it has no threshold. Several final answers echo that
"pass" ("every gate and score check passed"), but every agent that names S3 also says the score is unknown, so
none of them read the `true` as full points (quotes below). No trial called `run_check_S3_minimal_change`.

### Per trial

"Compared alternatives" = built or evaluated more than one candidate fix and chose between them by cost.
"Iterated" = changed the cut only because S1 still failed.

| Trial | Mentioned minimal change / volume / S3 (quote) | Read the scoring section | Compared alternatives | Measured per-rib differences |
|---|---|---|---|---|
| QjRN4co L1 | "Change size: 49.4 mm³ removed and none added, about 0.1% of the parts. The grader doesn't show its reference value, so I can't say how that scores on S3." | yes (S3, free test_fit) | no; iterated once after S1 failed at 65° (deeper notches, +22.8 mm³) | n/a (identical ribs); measured them alike |
| QofdJZK L1 | "Change size: 48.6 mm³ removed and none added. The grader scores this against a hidden best fix, so I can't see the exact minimal-change score." | yes | no; 3 rounds, each one adding material (widen, then deepen) to pass S1 | n/a |
| u2d86jU L1 | "The changed volume is 54 mm³ (0.11 % of the two parts)"; "`test_fit` passed every gate, both printability checks and the minimal-change check." | yes ("test_fit first 2 calls are free") | no; after S1 failed at 67° it added swept-arc cuts on top of the boxes | n/a |
| AXwNsaV L2 | "Change volume: 27.7 mm³ removed in total ... I can't see the grader's best-known fix, so I don't know how the S3 minimal-change score compares to it." | yes ("free first call") | no; first cut passed S1, then test_fit, then submit | n/a (identical ribs) |
| gJP7UPj L2 | "Change size: 43.6 mm³ removed and nothing added ... I don't know the grader's reference fix, so I can't say how the minimal-change score comes out." | yes | no; first cut passed, submitted | n/a |
| znT7Qc9 L2 | "Minimal change: 33.9 mm³ was removed and nothing added ... I can't see how that compares with the best known fix, so I don't know the exact minimal-change score." | yes | no; went from the cut straight to test_fit (no S1 check in between), then submit | n/a |
| Vs6f6U7 L3 | "Change size: 21.7 mm³ removed and none added. I can't tell how that compares with the best known fix, so I don't know the minimal-change score." | yes ("within the two free ones") | no; first cut passed, submitted | **yes, from our tool**: `measure` at 90° returned overlap pieces of 1.077 / 0.140 / 0.120 mm³ (rib at x ≈ -104.5 / -92.2 / -80.0), i.e. one rib ~8x the others. It then cut one identical profile 3 times |
| vtetXAU L3 | "S3 minimal change: passed. The total change is 22.7 mm³ removed ... How that compares with the best known fix is graded separately and isn't shown." | yes | no; one profile, cut 3 times, then G2/G3/G5/test_fit | **yes, its own scan** (`run5.py`): swept-overlap hulls 0.948 / 0.585 / 0.700 mm² with different depths (to v = -3.70 / -3.50 / -3.57). It then cut one envelope profile (to v = -3.85) at all three |
| yUegVYW L3 | "`S3_minimal_change` also passes, but its score depends on the best-known fix, which isn't shown." / "I did not try to shrink the pockets further, so some of the minimal-change score may be left on the table." | partly: knew S3, did not mention the test_fit cost | no; when S1 failed at 45° it undid all three boxes and re-cut all three bigger (+5.6 mm³ each), not only the rib that failed (section 4) | partly: `measure` at 60° showed 2 pieces of 0.291 / 0.287 mm³; it did not size the ribs separately |

### Verdict per trial

- QjRN4co (L1, 1.000): knew the rule: yes; tried to reduce: no.
- QofdJZK (L1, 1.000): knew the rule: yes; tried to reduce: no.
- u2d86jU (L1, 1.000): knew the rule: unclear (reported its volume and called S3 "passed", never named the reference); tried to reduce: no.
- AXwNsaV (L2, 1.000): knew the rule: yes; tried to reduce: no (landed at 1.07x on the first cut).
- gJP7UPj (L2, 0.621): knew the rule: yes; tried to reduce: no.
- znT7Qc9 (L2, 0.884): knew the rule: yes; tried to reduce: no.
- Vs6f6U7 (L3, 0.850): knew the rule: yes; tried to reduce: no (had per-rib overlap volumes from `measure`).
- vtetXAU (L3, 0.804): knew the rule: yes; tried to reduce: no (had measured per-rib profiles itself).
- yUegVYW (L3, 0.400): knew the rule: yes; tried to reduce: no, and said so.

**Summary: 8/9 knew the rule (1 unclear), 0/9 tried to reduce a passing fix.** No trial compared two candidate
fixes by volume. All changes to a cut were made because S1 still failed, and every one of them added material. The
agents had their own changed volume (in every edit result and in test_fit), the rule, 120+ unused tool calls and, on
L3, per-rib evidence that the ribs differ. One agent wrote down that it was leaving points on the table. The gap is
the decision to stop at the first fix that passes, not a missing fact.

Caveat: the old build's agent-side S3 always reports `"passed": true`. Every agent that commented on S3 said the
score was unknown, so we do not count this as having misled them. It is still a confound for any agent that reads
`passed` as "full points", which is why the planned Task 9 build (not made before the Opus run) removes S3 from the agent's checks and gives
a `changed_volume` tool instead.
