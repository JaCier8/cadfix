---
name: cadfix-viz
description: Conventions for visualizing cadfix agent runs in 3D (GLB scenes, the standalone three.js viewer.html, pass/fail colouring, joint animation). Use when writing or changing cadfix/viz.py, the viewer, or the viz hook in cadfix/harbor/build.py / run_eval.py.
---

# cadfix visualization

Goal levels: (1) after every run there is a model of what the agent made, openable in a viewer;
(2) the model shows what went right/wrong (colours); (3) live view of the mechanism moving.

## Hard rules
- **Humans only.** The agent under test must never see the viewer or its code: `cadfix/harbor/build.py`
  excludes `viz.py` from `environment/cadfix` (agent image) and ships it only in `tests/` (verifier,
  separate container). Output goes only to `/logs/verifier/`. Keep it that way for every new viz file
  (add it to `IGNORE_AGENT`; `tests/test_harbor_build.py` asserts it).
- **Never affect the reward.** Viz runs AFTER `reward.txt` is written, as a separate process,
  `timeout ... || true`. It parses agent-controlled STEP files, so it never goes inside `grade()`.
- **Show what was graded.** Load the submission with `cadfix.grade.load_submission` (missing or
  unreadable parts fall back to the original; record those notes so an untouched original is not
  mistaken for agent work).
- **Generic.** `cadfix/viz.py` must not name hinge parts. Drive everything from `Assembly`
  (editable/fixed), `Joint` (moving, axis, range_deg) and the grade report (`checks`, `failed_gates`).
- **Output location.** Harbor: `/logs/verifier/viz/` (the only path proven to reach the host; the
  `artifacts/output` download is unreliable). Local: `results/<agent>/<L>/seed_NNNN/viz/`.
- After changing anything under `cadfix/`, regenerate the committed judge dataset
  (`python -m cadfix.harbor.build --judge`); it ships its own copy of `cadfix/`.

## Geometry / glTF pitfalls
- Parts are Z-up mm; glTF is Y-up. Rotate -90 deg about X (root transform or per mesh).
- Translucency: use a trimesh `PBRMaterial(alphaMode="BLEND", baseColorFactor=[r,g,b,a])`.
  Vertex/face colour alpha is ignored by many viewers.
- One node per part named exactly `<part>`; diff nodes of an editable part = `<part>__removed` (red, original minus variant) / `<part>__added` (green); variants agent / reference / original; reference fix lives in `pristine/reference/parts` (verifier-only).
  Later levels recolour/rotate nodes by these names, so keep them stable.
- In the closed pose the moving part can hide the edited region: always also provide the open pose
  (joint at `range_deg[1]`), or make the moving part translucent.
- Meshes come from `kernel.mesh_arrays(part.mesh)`; poses from `Joint.matrix(angle)` /
  `kernel.rotate`. Do not re-tessellate with different tolerances (results must match the checks).

## viewer.html
- Single file, works from `file://`: GLBs embedded as base64; three.js via importmap from
  `cdn.jsdelivr.net/npm/three@0.160.0` (exact pinned version, incl. `three/addons/`).
- OrbitControls, auto-fit camera, per-node visibility toggles, header with level/seed/reward/notes.
- Keep it plain; no build step, no npm, no server.

## Level 2 ideas (colouring) — data already available
- `grade.json` `checks.<id>.passed/metrics/details`, `failed_gates`, `scores`.
- Removed/added material: `kernel.changed_volume` / boolean difference original vs current
  (manifold3d) -> separate nodes coloured e.g. red (removed) / green (added).
- Collisions: `kernel.overlaps_at` / `intersection_components` at the first failing sweep angle ->
  red node `collision_<part>@<deg>`.
- Zones: `Zone`/`Region.to_manifold()` from the spec -> translucent keep-in (green) / keep-out (red)
  boxes, coloured by the G3 metrics.

## Level 3 ideas (live)
- Precompute the joint transform per angle in Python (or pass axis point/direction + range to JS and
  rotate the moving nodes about the axis in three.js; remember the Z-up -> Y-up swap of the axis).
- Slider over `range_deg` with `step_deg`; overlay per-angle sweep results (clearance, collisions)
  from the S1 check so the frame where it jams turns red.

## Verify
- `pytest -q tests/test_viz.py` and the quick suite in Docker (see CLAUDE.md commands).
- Open `viewer.html` in a real browser: model upright, edited region visible, ghosts translucent.
- Harbor oracle/nop runs: rewards unchanged, `viz/` present in the host trial `verifier/` folder.

## Playback mode (viewer.html)
`viz.visualize(..., playback=True)` runs `cadfix/playback.py` (replay of the logged edits) and embeds `playback.json` +
frame GLBs; viewer.html opens in Playback when there is more than one frame (Compare otherwise). Current-step change =
`__step_removed` magenta / `__step_added` cyan (pulsing, ring + box marker), earlier = red/green. URL hash for
screenshots: `#step=N` (1-based, no autoplay), `#mode=compare`. `--no-playback` / `playback=False` turns it off.
