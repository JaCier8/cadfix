# Go/no-go runs

1. `scripts/brief.sh LEVEL SEED`: the brief to paste to the model (bug report, spec, S3 as a rule, geometry).
2. The model answers with an ops file (format below). Save it, e.g. `gonogo/L2_s0_try1.json`.
3. `scripts/try.sh LEVEL SEED gonogo/L2_s0_try1.json`: stdout is the `--hide-score` report to paste back
   (no reward). The script also appends a line to `gonogo_log.csv` in the repo root (timestamp, level,
   seed, ops file, reward, S1 pass, volume / V_ref). That log is a private record: do not show it to the model.

## Ops JSON format

A JSON list of operations, applied in order to a fresh copy of the original parts (each run starts from
the original). Units are mm. Coordinates are in the frame the brief uses (world frame for L3). All values
below are placeholders.

```json
[
  {
    "op": "chamfer",
    "part": "enclosure",
    "edge_near": [X, Y, Z],
    "d1": D1,
    "d2": D2,
    "d1_face_normal": [NX, NY, NZ],
    "edge_direction": [DX, DY, DZ]
  },
  {
    "op": "extrude_cut",
    "part": "enclosure",
    "origin": [X, Y, Z],
    "normal": [NX, NY, NZ],
    "x_dir": [UX, UY, UZ],
    "polygon_2d": [[U1, V1], [U2, V2], [U3, V3]],
    "depth_from": F,
    "depth_to": T
  }
]
```

`chamfer` cuts the whole edge nearest to `edge_near`:
- `edge_near`: a point on or near the edge. The nearest edge must be within 1 mm and clearly closer than any
  other edge.
- `d1`: chamfer leg (> 0) on the face selected by `d1_face_normal`.
- `d2`: leg on the other face. Optional, defaults to `d1`.
- `d1_face_normal`: optional. Picks the adjacent face whose outward normal is closest to this direction. If
  you leave it out, `d1` goes on the face that points most upwards.
- `edge_direction`: optional. Only edges parallel to it (within 1 deg) are candidates, which helps at
  corners.

`extrude_cut` sketches a polygon on a plane and removes the prism swept along the plane normal:
- `origin`: the point where the sketch plane's (u, v) = (0, 0).
- `normal`: the plane normal, which is also the extrusion direction.
- `x_dir`: the sketch u axis, perpendicular to `normal`. The v axis is `normal` x `x_dir`.
- `polygon_2d`: at least 3 [u, v] points of a simple polygon.
- `depth_from`, `depth_to`: the prism runs from `depth_from` to `depth_to` along `normal`, measured from
  `origin`.

For both ops, `part` is optional and defaults to `"enclosure"`.
Directions don't need to be unit vectors. Points and lengths are snapped to 0.001 mm.
An operation that fails prints `ERROR ...` with the reason. Nothing is changed and no reward is logged
(the log line gets `ERROR`).
