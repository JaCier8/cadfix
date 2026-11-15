"""3D diff viewer. Generic: everything comes from the Assembly / Joint data.

  python -m cadfix.viz --task-dir T --pristine P --submitted S --out DIR [--report grade.json] [--reference DIR]

Writes into DIR: `<variant>_<pose>.glb` for variant in agent / reference / original and pose in closed / open
(one node per part named `<part>`; for every editable part of the agent and reference variants two more nodes:
`<part>__removed` = original - variant in red and `<part>__added` = variant - original in green), viewer.html
(self-contained, GLBs embedded as base64, three.js from a pinned CDN; reference and agent side by side) and viz.json.
Shows exactly what was graded (loads the submission with grade.load_submission). The reference (the known-good fix,
`<pristine>/reference/parts/<editable>.step` by default) is optional. Never raises for missing submission parts.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import numpy as np

from cadfix.core import kernel
from cadfix.core.assembly import Assembly
from cadfix.grade import load_submission

THREE = "https://cdn.jsdelivr.net/npm/three@0.160.0"
# base colours (RGB 0-1)
FIXED, MOVING, EDIT_FIXED, EDIT_MOVING = (0.55, 0.55, 0.58), (0.85, 0.55, 0.20), (0.62, 0.70, 0.80), (0.18, 0.45, 0.85)
NON_EDITABLE = (0.25, 0.25, 0.27)
REMOVED, ADDED = (0.9, 0.15, 0.15), (0.15, 0.75, 0.2)
POSES = ("closed", "open")
MIN_DIFF_MM3 = 1e-3     # diff components below this are tessellation slivers, not geometry


def _color(part, moving: bool) -> tuple:
    if part.editable:
        return EDIT_MOVING if moving else EDIT_FIXED
    return NON_EDITABLE if not moving else MOVING


def _to_gltf(p) -> list:
    """Z-up model point -> glTF Y-up point (-90 deg about X)."""
    return [float(p[0]), float(p[2]), -float(p[1])]


def _trimesh(m, rgb, alpha=1.0):
    import trimesh
    from trimesh.visual.material import PBRMaterial
    v, t = kernel.mesh_arrays(m)
    v = np.column_stack([v[:, 0], v[:, 2], -v[:, 1]])      # Z-up -> glTF Y-up (-90 deg about X)
    mat = PBRMaterial(baseColorFactor=[*rgb, alpha], metallicFactor=0.0, roughnessFactor=0.7,
                      alphaMode="BLEND" if alpha < 1 else "OPAQUE", doubleSided=alpha < 1)
    mesh = trimesh.Trimesh(v, t, process=False)
    mesh.visual = trimesh.visual.TextureVisuals(material=mat)
    return mesh



def _components(m):
    """Components of a manifold with volume >= MIN_DIFF_MM3, merged into one manifold (None if nothing remains)."""
    import manifold3d
    parts = [c for c in m.decompose() if c.volume() >= MIN_DIFF_MM3] if m.volume() > 0 else []
    return manifold3d.Manifold.batch_boolean(parts, manifold3d.OpType.Add) if parts else None


def diff_meshes(original_shape, new_shape):
    """(removed, added) meshes (Manifold or None): original - new and new - original. Computed on the B-rep, so unchanged
    faces cancel exactly (meshes tessellated separately leave zero-thickness slivers); components smaller than
    MIN_DIFF_MM3 are dropped. Falls back to the mesh difference if the B-rep boolean fails."""
    try:
        a, b = original_shape.cut(new_shape), new_shape.cut(original_shape)
        out = [_components(kernel.to_manifold(x)) if x.Volume() > MIN_DIFF_MM3 else None for x in (a, b)]
    except Exception:  # noqa: BLE001 - OCC boolean or tessellation failure
        ma, mb = kernel.to_manifold(original_shape), kernel.to_manifold(new_shape)
        out = [_components(ma - mb), _components(mb - ma)]
    return tuple(out)


def _scene(asm: Assembly, original: Assembly, angle: float, diff: bool):
    """(trimesh scene, bbox of all diff meshes in glTF Y-up coords or None, {part: [removed, added]} volumes)."""
    import trimesh
    j = asm.joint
    pose = lambda n, m: kernel.rotate(m, j.axis_point, j.axis_direction, angle) if n in j.moving else m
    scene = trimesh.Scene()
    for n, p in asm.parts.items():
        scene.add_geometry(_trimesh(pose(n, p.mesh), _color(p, n in j.moving)), node_name=n, geom_name=n)
    pts, vols = [], {}
    for n in asm.editable if diff else []:
        removed, added = diff_meshes(original.parts[n].shape, asm.parts[n].shape)
        vols[n] = list(kernel.changed_volume(original.parts[n].mesh, asm.parts[n].mesh))
        for suffix, m, rgb in (("removed", removed, REMOVED), ("added", added, ADDED)):
            if m is not None:
                m = pose(n, m)
                g = f"{n}__{suffix}"
                scene.add_geometry(_trimesh(m, rgb), node_name=g, geom_name=g)
                lo, hi = kernel.bbox(m)
                pts += [_to_gltf(lo), _to_gltf(hi)]
    box = [np.min(pts, axis=0).round(3).tolist(), np.max(pts, axis=0).round(3).tolist()] if pts else None
    return scene, box, vols


VIEWER = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>cadfix diff viewer</title>
<style>
html,body{height:100%}
body{margin:0;font:13px sans-serif;background:#1e2024;color:#ddd;display:flex;flex-direction:column;overflow:hidden}
#bar{padding:6px 10px;background:#15171a;display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center}
#bar b{font-size:14px} #bar label{display:inline-block;margin:0} #notes{font-size:11px;opacity:.7}
#stage{position:relative;flex:1;min-height:0}
#stage canvas{position:absolute;left:0;top:0}
#labels{position:absolute;inset:0;display:flex;flex-direction:row;pointer-events:none}
.pane{flex:1;position:relative;border-right:1px solid #555;box-sizing:border-box}
.pane:last-child{border:0}
.lab{position:absolute;top:6px;left:8px;background:#000a;padding:6px 8px;border-radius:4px;max-width:92%}
.lab h3{margin:0 0 3px;font-size:14px} .lab pre{margin:3px 0 0;font-size:11px;white-space:pre-wrap}
.lab select{pointer-events:auto;font-size:13px}
.r{color:#ff6b6b} .g{color:#5fdc78}
@media (max-width:700px){#labels{flex-direction:column}.pane{border-right:0;border-bottom:1px solid #555}}
button{cursor:pointer}
</style></head><body>
<div id="bar"><b id="head"></b>
<span><button id="bc">Closed</button> <button id="bo">Open</button></span>
<span><button id="bf">Focus changes</button> <button id="bw">Whole model</button></span>
<label><input type="checkbox" id="xray"> x-ray</label>
<label><input type="checkbox" id="diff" checked> show <span class="r">removed</span>/<span class="g">added</span></label>
<span id="parts"></span><span id="notes"></span></div>
<div id="stage"><div id="labels"><div class="pane" id="p0"></div><div class="pane" id="p1"></div></div></div>
<script type="importmap">{"imports":{"three":"@@THREE@@/build/three.module.js","three/addons/":"@@THREE@@/examples/jsm/"}}</script>
<script type="module">
import * as THREE from "three";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";
import {GLTFLoader} from "three/addons/loaders/GLTFLoader.js";
const DATA = @@DATA@@;
const GLB = @@GLB@@;
const V = DATA.variants, TITLE = {agent: "Agent's result", reference: "Reference fix", original: "Original (broken)"};
document.getElementById("head").textContent = `level ${DATA.level} seed ${DATA.seed} reward ${DATA.reward ?? "n/a"}`;
document.getElementById("notes").textContent = Object.entries(DATA.submission || {}).map(([k, v]) => `${k}: ${v}`).join("; ");
const stage = document.getElementById("stage");
const renderer = new THREE.WebGLRenderer({antialias: true, preserveDrawingBuffer: true});
stage.prepend(renderer.domElement);
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
const controls = new OrbitControls(camera, renderer.domElement);
const hidden = new Set(); let pose = "closed", showDiff = true, xray = false;
function mkScene(bg) {
  const s = new THREE.Scene(); s.background = new THREE.Color(bg);
  s.add(new THREE.AmbientLight(0xffffff, 0.8));
  const sun = new THREE.DirectionalLight(0xffffff, 2.0); sun.position.set(1, 2, 1.5); s.add(sun);
  return s;
}
const panes = [{el: document.getElementById("p0"), scene: mkScene(0x1e2024), v: V.reference ? "reference" : "original"},
               {el: document.getElementById("p1"), scene: mkScene(0x24272d), v: "agent"}];
const models = {}; const loader = new GLTFLoader();
const parse = b64 => new Promise(res => loader.parse(Uint8Array.from(atob(b64), c => c.charCodeAt(0)).buffer, "", g => res(g.scene)));
for (const v of Object.keys(GLB)) { models[v] = {}; for (const p of Object.keys(GLB[v])) models[v][p] = await parse(GLB[v][p]); }
const isDiff = n => n.endsWith("__removed") || n.endsWith("__added");
function applyVis(root) {
  root.traverse(o => {
    if (!o.isMesh) return;
    const d = isDiff(o.name), base = d ? o.name.replace(/__(removed|added)$/, "") : o.name;
    o.visible = !hidden.has(base) && (!d || showDiff);
    if (!d) for (const m of [].concat(o.material)) { m.transparent = xray; m.opacity = xray ? 0.35 : 1; m.depthWrite = !xray; }
  });
}
const fmt = x => x.toFixed(1);
function label(p) {
  const v = p.v, info = V[v], el = p.el; el.innerHTML = "";
  const box = document.createElement("div"); box.className = "lab";
  const h = document.createElement("h3");
  if (p === panes[0]) {
    const sel = document.createElement("select");
    for (const k of ["reference", "original"]) if (V[k]) { const o = new Option(TITLE[k], k); o.selected = k === v; sel.add(o); }
    sel.onchange = () => { p.v = sel.value; setModel(p); label(p); };
    h.append(sel);
  } else h.textContent = TITLE[v] + (DATA.reward != null ? `  (reward ${DATA.reward})` : "");
  box.append(h);
  const pre = document.createElement("pre");
  const lines = Object.entries(info.parts).filter(([n, x]) => x.removed + x.added > 0.0005).map(([n, x]) => `${n}: <span class="r">-${fmt(x.removed)}</span> / <span class="g">+${fmt(x.added)}</span> mm3`);
  pre.innerHTML = v === "original" ? "unmodified model" : lines.join("\n") || "no changes";
  box.append(pre); el.append(box);
}
function setModel(p) {
  if (p.root) p.scene.remove(p.root);
  p.root = models[p.v][pose].clone(); p.scene.add(p.root); applyVis(p.root);
}
function allBox(pred) {
  const box = new THREE.Box3(); box.makeEmpty();
  for (const p of panes) { p.root.updateMatrixWorld(true); p.root.traverse(o => { if (o.isMesh && pred(o.name)) box.expandByObject(o); }); }
  return box;
}
function dirNow() { const d = camera.position.clone().sub(controls.target); return d.lengthSq() > 1e-9 ? d.normalize() : new THREE.Vector3(0.5, 0.6, 1).normalize(); }
function fit(box, dist, dir) {
  const c = box.getCenter(new THREE.Vector3());
  camera.position.copy(c).add(dir.clone().multiplyScalar(dist)); controls.target.copy(c); controls.update();
}
function initialDir(box) {
  const c = box.getCenter(new THREE.Vector3()), d = new THREE.Vector3(0.8, 0.6, 1);
  if (DATA.view_toward) {  // look at the joint axis side from the opposite side, from above (the open lid stands behind it)
    d.copy(new THREE.Vector3(...DATA.view_toward)).sub(c).negate(); d.y = 0;
    if (d.lengthSq() > 1e-9) { d.normalize(); d.add(new THREE.Vector3(-d.z, 0, d.x).multiplyScalar(0.4)); d.y = 1.1; }
    else d.set(0.8, 0.6, 1);
  }
  return d.normalize();
}
function whole(dir) { const b = allBox(n => !isDiff(n)); fit(b, b.getSize(new THREE.Vector3()).length() * 1.2, dir || dirNow()); }
function focus(dir) {
  const b = allBox(isDiff);
  if (b.isEmpty()) return whole(dir);
  fit(b, Math.max(b.getSize(new THREE.Vector3()).length() * 2.0, 150), dir || dirNow());   // margin: keep wall edge / hinge in view
}
function setPose(q) { pose = q; for (const p of panes) setModel(p); }
function layout() {
  const W = stage.clientWidth, H = stage.clientHeight; renderer.setSize(W, H); const stacked = W < 700;
  panes.forEach((p, i) => { p.rect = stacked ? [0, i === 0 ? H / 2 : 0, W, H / 2] : [i * W / 2, 0, W / 2, H]; });
}
function render() {
  renderer.setScissorTest(true);
  for (const p of panes) {
    const [x, y, w, h] = p.rect; renderer.setViewport(x, y, w, h); renderer.setScissor(x, y, w, h);
    camera.aspect = w / h; camera.updateProjectionMatrix(); renderer.render(p.scene, camera);
  }
}
for (const n of Object.keys(DATA.parts)) {
  const l = document.createElement("label"), cb = document.createElement("input");
  cb.type = "checkbox"; cb.checked = true;
  cb.onchange = () => { cb.checked ? hidden.delete(n) : hidden.add(n); for (const p of panes) applyVis(p.root); };
  l.append(cb, " " + n); document.getElementById("parts").append(l, " ");
}
document.getElementById("bc").onclick = () => setPose("closed");
document.getElementById("bo").onclick = () => setPose("open");
document.getElementById("bf").onclick = () => focus();
document.getElementById("bw").onclick = () => whole();
document.getElementById("xray").onchange = e => { xray = e.target.checked; for (const p of panes) applyVis(p.root); };
document.getElementById("diff").onchange = e => { showDiff = e.target.checked; for (const p of panes) applyVis(p.root); };
for (const p of panes) { setModel(p); label(p); }
layout();
camera.position.set(0, 0, 100); controls.target.set(0, 0, 0);
const hasDiff = Object.values(V).some(x => x.diff_bbox);
if (hasDiff) setPose("open");   // the closed lid hides the edited wall edge; use the Closed button for the closed pose
focus(initialDir(allBox(n => !isDiff(n))));
addEventListener("resize", layout);
renderer.setAnimationLoop(() => { controls.update(); render(); });
</script></body></html>
"""


def _write_viewer(out: Path, data: dict, glbs: dict) -> Path:
    b64 = {v: {q: base64.b64encode((out / f).read_bytes()).decode() for q, f in d.items()} for v, d in glbs.items()}
    html = (VIEWER.replace("@@THREE@@", THREE).replace("@@DATA@@", json.dumps(data).replace("</", "<\\/"))
            .replace("@@GLB@@", json.dumps(b64)))
    p = out / "viewer.html"
    p.write_text(html)
    return p


def _reference_assembly(original: Assembly, ref_dir: Path) -> Assembly | None:
    shapes = {}
    for n in original.editable:
        f = ref_dir / "parts" / f"{n}.step"
        if f.exists():
            shapes[n] = kernel.import_step(f)
    return original.with_shapes(shapes) if shapes else None


def visualize(task_dir, pristine_dir, submitted_dir, out_dir, report: dict | None = None, reference_dir=None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    original = Assembly.load(Path(task_dir), Path(pristine_dir) / "parts")
    current, notes = load_submission(original, Path(submitted_dir))
    grader = {}
    gj = Path(pristine_dir) / "grader.json"
    if gj.exists():
        grader = json.loads(gj.read_text())
    ref_dir = Path(reference_dir) if reference_dir else Path(pristine_dir) / "reference"
    reference = _reference_assembly(original, ref_dir) if ref_dir.exists() else None
    assemblies = {"agent": current, "original": original}
    if reference is not None:
        assemblies = {"agent": current, "reference": reference, "original": original}
    lo, hi = current.joint.range_deg
    files, glbs, variants = [], {}, {}
    for v, asm in assemblies.items():
        glbs[v], vparts, bbox = {}, {}, None
        for q, angle in zip(POSES, (lo, hi)):
            scene, box, vols = _scene(asm, original, angle, diff=v != "original")
            f = f"{v}_{q}.glb"
            scene.export(str(out / f))
            glbs[v][q] = f
            files.append(f)
            if q == "closed":
                bbox = box
                vparts = {n: {"removed": round(r, 3), "added": round(a, 3)} for n, (r, a) in vols.items()}
        variants[v] = {"parts": vparts, "diff_bbox": bbox}
    parts = {}
    for n, p in current.parts.items():
        d = {"editable": p.editable, "moving": n in current.joint.moving,
             "volume_original": round(float(original.parts[n].mesh.volume()), 3),
             "volume_current": round(float(p.mesh.volume()), 3), "removed": 0.0, "added": 0.0}
        if p.editable:
            rem, add = kernel.changed_volume(original.parts[n].mesh, p.mesh)
            d["removed"], d["added"] = round(rem, 3), round(add, 3)
        parts[n] = d
    rep = report or {}
    info = {"level": rep.get("level", grader.get("level")), "seed": rep.get("seed", grader.get("seed")),
            "reward": rep.get("reward"), "submission": notes, "parts": parts, "variants": variants,
            "view_toward": _to_gltf(current.joint.axis_point), "files": files + ["viewer.html", "viz.json"]}
    _write_viewer(out, info, glbs)
    (out / "viz.json").write_text(json.dumps(info, indent=2))
    return info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task-dir", required=True)
    ap.add_argument("--pristine", required=True)
    ap.add_argument("--submitted", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", help="grade.json written by cadfix.grade")
    ap.add_argument("--reference", help="dir with parts/<editable>.step of the known-good fix (default <pristine>/reference)")
    a = ap.parse_args(argv)
    rep = json.loads(Path(a.report).read_text()) if a.report and Path(a.report).exists() else None
    info = visualize(a.task_dir, a.pristine, a.submitted, a.out, rep, a.reference)
    print(f"wrote {len(info['files'])} files to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
