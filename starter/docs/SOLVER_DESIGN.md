# Reference solver design (hinge_lid, all levels)

The reference run is our "frontier" upper bound. It must play by the agent's rules: it only calls the MCP tools
an agent gets (in-process for run_eval, over stdio in Harbor), never reads params.json, feasibility output,
stored reference ops, V_ref or any file. It is deterministic: fixed sampling, no randomness, no timing-based
decisions. Target: >= 0.95 on L1/L2/L3 seeds 0-9 in under ~60 tool calls and well under a minute of tool time.

## Tools it relies on (all generic, all available to agents)
- `list_parts`: parts, editable flags, print build-up directions, the revolute joint (axis point, direction,
  range, moving / fixed parts).
- `run_check_S1_opening`: the S1 sweep as graded (ok_until, first failing step, min clearance).
- `measure(part_a, part_b, joint_angle_deg)`: overlap volume, overlap pieces (volume, bbox, centroid) and
  min gap with the moving parts rotated about the joint.
- `find_edges_near(part, point, direction, radius)`, `list_faces(part)`: edge / face descriptions in world
  coordinates (adjacent face normals, planar face normals and centres).
- `section(part, point, normal, x_dir, joint_angle_deg, window_mm)`: section polygons in plane coordinates
  (u along x_dir, v = normal x u), the plane point is the 2D origin.
- `extrude_cut`, `undo`, `test_fit`, `submit`.

## 1. Understanding the assembly from tool outputs
1. `list_parts` -> axis point a0, unit axis direction a, moving {lid, lid_module}, fixed {enclosure, hinge_pin},
   editable {enclosure, lid}; enclosure build-up direction `up`.
2. `run_check_S1_opening` on the original -> original ok_until and the first failing step (angle, pair).
3. Colliding regions: `measure(lid, enclosure, th)` for th = 20, 30, ..., 110 deg and the first failing angle.
   Every overlap piece gives a centroid c; its axial coordinate s = (c - a0) . a. Pieces within 1 mm in s are one
   region (one region per colliding rib).
4. The edge: `find_edges_near(enclosure, c, direction=a, radius=3)` at a region centroid returns the straight edge
   parallel to the hinge nearest to the clash: the rear wall's outer top edge E (point e0 on it). Its two adjacent
   face normals are the wall top normal n_top (the one closest to `up`) and the rear wall's outward normal n_out.
5. Ribs along the axis: `list_faces(lid)` -> planar faces whose normal is parallel to a (|n . a| > 0.999) and
   whose centre lies within 5 mm of the axis: the end faces of the lid knuckle segments (knuckle + rib + tail).
   Their axial positions s_j, sorted, give the segments [s_lo, s_hi] (consecutive pairs with lid material
   between them, checked with one `section` at the midpoint). Each region from step 3 maps to the segment
   containing its s. A region that maps to no segment is handled by the fallback (section 5).

## 2. Local frame (needed for L3, used on every level)
u = n_out (outward from the rear wall), w = n_top (up), a = hinge axis. All 2D work happens in section planes
with normal a and x_dir = n_out, so v = a x n_out; if v . n_top < 0 the up direction is -v (the solver keeps the
sign and converts). Positive joint rotation about a is counter-clockwise in (u, v). Every cut is written back to
world coordinates through this frame: origin = E projected to the relief's start plane, extrude normal = +-a
chosen so that the tool's v axis (normal x x_dir) points up, x_dir = n_out. Nothing assumes axis-aligned
coordinates, so L1/L2 run the same code as L3.

## 3. Sizing each relief: options and choice
- (a) Analytic from measured geometry: per segment, take `section` of lid + lid_module (moving) and enclosure
  (fixed) in the segment's mid plane, sweep the moving section about the axis in 1 deg steps (as S1 does), and
  find the smallest triangle relief (top along the wall top, side down the outer face) on a 0.05 mm grid with:
  no overlap below 10 deg, clearance >= 0.3 + m from 10 deg (m = 0.01 mm for tessellation and 0.001 mm rounding),
  seal width t - top >= 1.5 + 0.3 (spec's base margin), side below the bracket top - 0.5 (measured in a section
  through the neighbouring enclosure knuckle). For a fixed top the valid sides are one interval, so each top
  needs a bisection (~8 polygon checks). Tool calls: 3-4 sections per segment. Same model as the generator's
  V_ref scan, so it lands at ~1.0 x V_ref. Weakness: it trusts the section (tessellated circles, rounding) and
  cannot see the rib ends.
- (b) Bisection with trial cuts: cut, `run_check_S1_opening`, undo, per parameter and rib. 2 parameters x 3
  ribs x ~7 steps x 3 calls ~ 130 calls, close to the 150 cap, slow on L3 (each sweep ~1-2 s), and S1 is global
  (a failing step does not say which rib), so ribs interact. Robust to rounding, but expensive and fragile.
- (c) Hybrid: (a) for the first guess, then the real 3D S1 check as the judge; on failure grow every relief by
  one grid step (side + 0.05) and the end extension by 0.05 mm, at most 3 rounds.
- **Choice: (c).** ~35-45 tool calls, deterministic, the 3D check covers what the 2D model cannot see (rib ends,
  rounding), and the volume stays within a few % of V_ref (S3 needs <= 1.15 x on L2/L3). No tightening pass:
  the grid minimum is already the best the 2D model allows.

## 4. End extension along the axis
Each relief runs from s_lo - e to s_hi + e with e = 0.35 mm (clearance 0.3 + one grid step), the same rule as
the spec's expected good fix. The 3D S1 sweep checks the rib ends (the 2D model cannot); if it fails, e grows by
0.05 per round together with the side (3 rounds max). Axial gaps between knuckles are 0.4 mm, so e <= 0.4 keeps
the relief off the enclosure brackets; the keep-in check (G3) confirms it.

## 5. Failure handling
- A cut op returns an error: record it, undo nothing (nothing changed), shrink the cut length to the segment +
  0.3 mm and retry once; if it fails again, skip to the fallback.
- S1 never passes after 3 rounds: undo all reliefs and apply the fallback: one full-edge chamfer of E
  (`chamfer` with d1 on the top face) sized as the envelope (max top, max side) of the per-segment reliefs + one
  grid step. That is the L1 fix, worth 0.4 on L2/L3 if it works.
- A region that maps to no lid segment (unexpected geometry): relief over the region's axial extent (overlap
  piece bbox corners projected on a) + 0.5 mm, sized from a section through the region centre.
- A gate fails after the fix (`test_fit`): report it in the log and keep the state with the best S1 progress;
  the solver never "fixes" by cutting the lid (keep-in).
- The solver always ends with `submit`; tool errors never crash it.

## 6. What a typical LLM agent does differently, and fairness
The go/no-go run: Hydrogen on L2 seed 0 sized a full-edge chamfer three times (0.103 -> 0.400 -> 0.400, 3.2 x
V_ref) and never tried a local relief. What the tools give a careful agent that the solver also uses:
- `measure` at any opening angle returns the overlap as SEPARATE pieces, each only as long as one rib segment
  along the hinge: the clash is local, not along the whole edge.
- `section` through a rib and between ribs shows the rib only in the knuckle segments.
- The S3 rule ("full points within 1.15x of the best known fix, zero at 2x") says that a much smaller fix exists
  on L2/L3, and the reward formula is public.
- On L3 the ribs differ: per-segment sections show different rib depths, so identical reliefs over-cut
  (>= 1.4 x V_ref by construction, reward <= ~0.82).
- On L3 nothing is axis-aligned: an agent has to build the frame from face normals and the axis, as above.
Nothing the solver uses is hidden from the agent; it needs no secret numbers and no hints. The difficulty is
reasoning (local fix, end clearance, per-rib sizing, rotated frame), not missing information.
