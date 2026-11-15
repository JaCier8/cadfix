"""3D diff viewer. Generic: everything comes from the Assembly / Joint data.

  python -m cadfix.viz --task-dir T --pristine P --submitted S --out DIR [--report grade.json] [--reference DIR]

Writes into DIR: `<variant>_<pose>.glb` for variant in agent / reference / original and pose in closed / open
(one node per part named `<part>`; for every editable part of the agent and reference variants two more nodes:
`<part>__removed` = original - variant in red and `<part>__added` = variant - original in green), viewer.html
(self-contained, GLBs embedded as base64, three.js from a pinned CDN; reference and agent side by side) and viz.json.
Shows exactly what was graded (loads the submission with grade.load_submission). The reference (the known-good fix,
`<pristine>/reference/parts/<editable>.step` by default) is optional. Never raises for missing submission parts.
Unless --no-playback, also runs cadfix.playback into DIR/playback/ and embeds its frames as a Playback mode of viewer.html
(player over the logged steps, current-step change in magenta/cyan); #step=N in the URL jumps to step N, #mode=compare.
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
<html><head><meta charset="utf-8"><title>cadfix viewer</title>
<style>
html,body{height:100%}
body{margin:0;font:13px sans-serif;background:#1e2024;color:#ddd;display:flex;flex-direction:column;overflow:hidden}
#bar{padding:6px 10px;background:#15171a;display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center}
#bar b{font-size:14px} #bar label{display:inline-block;margin:0} #notes{font-size:11px;opacity:.7}
#modes button{padding:4px 12px;font-size:13px;border:1px solid #666;background:#2a2d33;color:#ddd}
#modes button.on{background:#ff2bd6;color:#000;border-color:#ff2bd6;font-weight:600}
#modes button:disabled{opacity:.4;cursor:default}
#pbnote{color:#ffb86b;font-size:12px}
#stage{position:relative;flex:1;min-height:0}
#stage canvas{position:absolute;left:0;top:0}
#labels{position:absolute;inset:0;display:flex;flex-direction:row;pointer-events:none}
.pane{flex:1;position:relative;border-right:1px solid #555;box-sizing:border-box}
.pane:last-child{border:0}
.lab{position:absolute;top:6px;left:8px;background:#000a;padding:6px 8px;border-radius:4px;max-width:92%}
.lab h3{margin:0 0 3px;font-size:14px} .lab pre{margin:3px 0 0;font-size:11px;white-space:pre-wrap}
.lab select{pointer-events:auto;font-size:13px}
.r{color:#ff6b6b} .g{color:#5fdc78} .m{color:#ff2bd6} .c{color:#00e5ff}
#legend{position:absolute;right:8px;top:6px;background:#000b;padding:6px 10px;border-radius:4px;font-size:12px;line-height:1.55;pointer-events:none;z-index:3}
#legend i{display:inline-block;width:12px;height:12px;margin-right:6px;vertical-align:-1px;border-radius:2px}
#pb{background:#15171a;border-top:1px solid #444;padding:8px 12px}
#banner{background:#5a1d1d;color:#ffd0d0;padding:5px 8px;border-radius:4px;margin-bottom:6px;font-size:13px}
#cap{border-left:6px solid #666;padding:4px 12px;margin-bottom:8px;background:#1e2024;min-height:84px}
#cap.edit{border-color:#ff2bd6;background:#2a1a28} #cap.fail{border-color:#ff4040;background:#2a1a1a}
#c1{font-size:20px;font-weight:600;overflow-wrap:anywhere} #c2{font-size:15px;margin-top:2px;overflow-wrap:anywhere}
#c3,#c4{font-size:13px;opacity:.9;margin-top:2px}
.chip{display:inline-block;font-size:12px;font-weight:700;padding:1px 7px;border-radius:3px;margin-left:8px;vertical-align:2px;color:#000}
.chip.edit{background:#ff2bd6} .chip.fail{background:#ff4040} .chip.warn{background:#ffb86b}
#ctl{display:flex;gap:8px;align-items:center}
#ctl button{font-size:15px;min-width:36px;padding:4px 8px}
#strip{flex:1;display:flex;align-items:flex-end;height:38px;cursor:pointer;touch-action:none;user-select:none;min-width:80px}
.tick{flex:1;position:relative;height:100%}
.tick::after{content:"";position:absolute;left:12%;right:12%;bottom:0;height:10px;background:#5b6270}
.tick.chk::after{height:16px;background:#4a90d9}
.tick.edit::after{height:32px;background:#ff2bd6}
.tick.fail::after{height:32px;background:#ff4040}
.tick.cur{background:#ffffff30;box-shadow:inset 0 0 0 1px #fff}
#cnt{min-width:64px;text-align:right;font-variant-numeric:tabular-nums}
@media (max-width:700px){#labels{flex-direction:column}.pane{border-right:0;border-bottom:1px solid #555}}
button{cursor:pointer}
</style></head><body>
<div id="bar"><b id="head"></b>
<span id="modes"><button id="mc">Compare</button> <button id="mp">Playback</button></span>
<span id="cmpctl"><button id="bc">Closed</button> <button id="bo">Open</button></span>
<span><button id="bf">Focus changes</button> <button id="bw">Whole model</button></span>
<label><input type="checkbox" id="xray"> x-ray</label>
<label><input type="checkbox" id="diff" checked> show <span class="r">removed</span>/<span class="g">added</span></label>
<label id="afl"><input type="checkbox" id="autofocus" checked> auto-focus</label>
<span id="parts"></span><span id="pbnote"></span><span id="notes"></span></div>
<div id="stage"><div id="labels"><div class="pane" id="p0"></div><div class="pane" id="p1"></div></div>
<div id="legend"><div><i style="background:#ff2bd6"></i>removed this step</div><div><i style="background:#00e5ff"></i>added this step</div>
<div><i style="background:#d62a2a"></i>removed earlier (left pane: reference fix)</div><div><i style="background:#27c23a"></i>added earlier (left pane: reference fix)</div></div></div>
<div id="pb"><div id="banner" hidden></div>
<div id="cap"><div id="c1"></div><div id="c2"></div><div id="c3"></div><div id="c4"></div></div>
<div id="ctl"><button id="bfirst" title="first (Home)">|&#9664;</button><button id="bprev" title="previous (Left)">&#9664;</button>
<button id="bplay" title="play / pause (Space)">&#9654;</button><button id="bnext" title="next (Right)">&#9654;&#9654;</button><button id="blast" title="last (End)">&#9654;|</button>
<div id="strip" title="click or drag to scrub"></div><span id="cnt"></span>
<select id="speed"><option value="0.5">0.5x</option><option value="1" selected>1x</option><option value="2">2x</option><option value="4">4x</option></select></div></div>
<script type="importmap">{"imports":{"three":"@@THREE@@/build/three.module.js","three/addons/":"@@THREE@@/examples/jsm/"}}</script>
<script type="module">
import * as THREE from "three";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";
import {GLTFLoader} from "three/addons/loaders/GLTFLoader.js";
const DATA = @@DATA@@;
const GLB = @@GLB@@;
const PB = @@PB@@;
const PBGLB = @@PBGLB@@;
const V = DATA.variants, TITLE = {agent: "Agent's result", reference: "Reference fix", original: "Original (broken)"};
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;"}[c]));
$("head").textContent = `level ${DATA.level} seed ${DATA.seed} reward ${DATA.reward ?? "n/a"}`;
$("notes").textContent = Object.entries(DATA.submission || {}).map(([k, v]) => `${k}: ${v}`).join("; ");
const stage = $("stage");
const renderer = new THREE.WebGLRenderer({antialias: true, preserveDrawingBuffer: true});
stage.prepend(renderer.domElement);
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
const controls = new OrbitControls(camera, renderer.domElement);
const hidden = new Set(); let pose = "closed", showDiff = true, xrayUser = null, mode = "compare";
let stepHighlight = false;
function mkScene(bg) {
  const s = new THREE.Scene(); s.background = new THREE.Color(bg);
  s.add(new THREE.AmbientLight(0xffffff, 0.8));
  const sun = new THREE.DirectionalLight(0xffffff, 2.0); sun.position.set(1, 2, 1.5); s.add(sun);
  return s;
}
const panes = [{el: $("p0"), scene: mkScene(0x1e2024), v: V.reference ? "reference" : "original"},
               {el: $("p1"), scene: mkScene(0x24272d), v: "agent"}];
const models = {}; const loader = new GLTFLoader();
const parse = b64 => new Promise(res => loader.parse(Uint8Array.from(atob(b64), c => c.charCodeAt(0)).buffer, "", g => res(g.scene)));
for (const v of Object.keys(GLB)) { models[v] = {}; for (const p of Object.keys(GLB[v])) models[v][p] = await parse(GLB[v][p]); }

// ---- node classes: <part>, <part>__removed/__added (cumulative), <part>__step_removed/__step_added (this step)
const NODE = /^(.*?)__(step_)?(removed|added)$/;
const cls = n => { const m = NODE.exec(n); return m ? {base: m[1], step: !!m[2], kind: m[3]} : {base: n, step: false, kind: null}; };
const isDiff = n => NODE.test(n);
const mkMat = (color, emissive, ei) => new THREE.MeshStandardMaterial({color, emissive, emissiveIntensity: ei, roughness: 0.6, metalness: 0, side: THREE.DoubleSide});
const M = {rem: mkMat(0xd62a2a, 0x300000, 0.5), add: mkMat(0x27c23a, 0x002a06, 0.5),
           srem: mkMat(0xff2bd6, 0xff2bd6, 1), sadd: mkMat(0x00e5ff, 0x00e5ff, 1)};
for (const m of [M.srem, M.sadd]) { m.polygonOffset = true; m.polygonOffsetFactor = -2; m.polygonOffsetUnits = -2; }
function prepare(root) {   // consistent colours for the agent frames (override whatever the GLB carries)
  root.traverse(o => { if (!o.isMesh) return; const c = cls(o.name);
    if (c.kind) o.material = c.step ? (c.kind === "removed" ? M.srem : M.sadd) : (c.kind === "removed" ? M.rem : M.add); });
  return root;
}
const frameCache = new Map();
const frameRoot = k => { if (!frameCache.has(k)) frameCache.set(k, parse(PBGLB[k]).then(prepare)); return frameCache.get(k); };

// ---- timeline
const steps = [];
const pbOk = !!(PB && PB.frames && PB.frames.length > 1 && PBGLB.length === PB.frames.length);
if (pbOk) {
  for (const s of PB.steps) steps.push(s);
  const maxF = Math.max(0, ...PB.steps.map(s => s.frame));
  const lc = () => steps.length ? steps[steps.length - 1].last_check : null;
  for (let f = maxF + 1; f < PB.frames.length; f++)
    steps.push({synthetic: true, tool: "(end)", args_short: PB.frames[f].label, result_short: "", frame: f, is_edit: false, edit_ok: null, last_check: lc()});
}
const N = steps.length;
const prevFrame = i => i > 0 ? steps[i - 1].frame : 0;
const highlightOf = i => pbOk && steps[i].frame === prevFrame(i) + 1;
const xrayNow = () => xrayUser ?? (mode === "playback" && (stepHighlight || curFrame > 0));   // auto: see through the closed lid once something changed
function applyVis(root) {
  const xr = xrayNow();
  root.traverse(o => {
    if (!o.isMesh) return;
    const c = cls(o.name);
    if (!c.kind) {
      o.visible = !hidden.has(c.base);
      for (const m of [].concat(o.material)) { m.transparent = xr; m.opacity = xr ? (mode === "playback" ? 0.3 : 0.35) : 1; m.depthWrite = !xr; }
    } else o.visible = !hidden.has(c.base) && (c.step ? stepHighlight : showDiff);
  });
}
const applyAll = () => { for (const p of panes) if (p.root) applyVis(p.root); };
const fmt = x => x.toFixed(1);
function pbLines() {
  const f = PB.frames[curFrame].parts || {}, out = [];
  for (const [n, x] of Object.entries(f)) {
    if (x.removed + x.added > 0.0005) out.push(`${n}: <span class="r">-${fmt(x.removed)}</span> / <span class="g">+${fmt(x.added)}</span> mm3 vs original`);
    if (stepHighlight && x.step_removed + x.step_added > 0.0005) out.push(`this step: <span class="m">-${fmt(x.step_removed)}</span> / <span class="c">+${fmt(x.step_added)}</span> mm3`);
  }
  return out.join("\n") || "no changes yet";
}
function label(p) {
  const v = p.v, info = V[v], el = p.el; el.innerHTML = "";
  const box = document.createElement("div"); box.className = "lab";
  const h = document.createElement("h3");
  if (p === panes[0]) {
    const sel = document.createElement("select");
    for (const k of ["reference", "original"]) if (V[k]) { const o = new Option(TITLE[k] + (mode === "playback" ? " (target)" : ""), k); o.selected = k === v; sel.add(o); }
    sel.onchange = () => { p.v = sel.value; setModel(p); label(p); sel.blur(); };
    h.append(sel);
  } else h.textContent = mode === "playback" ? `Agent's replay: frame ${curFrame} of ${PB.frames.length - 1}` : TITLE[v] + (DATA.reward != null ? `  (reward ${DATA.reward})` : "");
  box.append(h);
  const pre = document.createElement("pre");
  const lines = Object.entries(info.parts).filter(([n, x]) => x.removed + x.added > 0.0005).map(([n, x]) => `${n}: <span class="r">-${fmt(x.removed)}</span> / <span class="g">+${fmt(x.added)}</span> mm3`);
  pre.innerHTML = (p === panes[1] && mode === "playback") ? pbLines() : (v === "original" ? "unmodified model" : lines.join("\n") || "no changes");
  box.append(pre); el.append(box);
}
function setModel(p) {
  if (p.root) p.scene.remove(p.root);
  p.root = models[p.v][mode === "playback" ? "closed" : pose].clone(); p.scene.add(p.root); applyVis(p.root);
}
function allBox(pred) {
  const box = new THREE.Box3(); box.makeEmpty();
  for (const p of panes) { p.root.updateMatrixWorld(true); p.root.traverse(o => { if (o.isMesh && pred(o)) box.expandByObject(o); }); }
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
const baseBox = () => allBox(o => !isDiff(o.name));
function whole(dir) { const b = baseBox(); fit(b, b.getSize(new THREE.Vector3()).length() * 1.2, dir || dirNow()); }
function focus(dir) {
  const b = allBox(o => isDiff(o.name) && o.visible);
  if (b.isEmpty()) return whole(dir);
  fit(b, Math.max(b.getSize(new THREE.Vector3()).length() * 2.0, 150), dir || dirNow());   // margin: keep wall edge / hinge in view
}
let anim = null;
function flyTo(box, instant) {   // move the camera target to the change, keep the viewing direction, stay >= 150 mm away
  const c = box.getCenter(new THREE.Vector3()), dist = Math.max(box.getSize(new THREE.Vector3()).length() * 2.5, 150);
  const to = c.clone().add(dirNow().multiplyScalar(dist));
  if (instant) { camera.position.copy(to); controls.target.copy(c); controls.update(); anim = null; return; }
  anim = {t0: performance.now(), p0: camera.position.clone(), c0: controls.target.clone(), p1: to, c1: c};
}
let boxes = [], rings = [];
function ringTex(css) {   // screen-space target ring that marks where the current step changed something
  const c = document.createElement("canvas"); c.width = c.height = 128; const g = c.getContext("2d");
  g.lineWidth = 9; g.strokeStyle = css; g.shadowColor = css; g.shadowBlur = 10; g.beginPath(); g.arc(64, 64, 50, 0, 7); g.stroke();
  return new THREE.CanvasTexture(c);
}
const RING = {m: ringTex("#ff2bd6"), c: ringTex("#00e5ff")};
function setBoxes(box, removed) {
  for (const b of boxes) { b.parent && b.parent.remove(b); b.dispose(); }
  for (const r of rings) { r.parent && r.parent.remove(r); r.material.dispose(); }
  boxes = []; rings = [];
  if (!box) return;
  for (const p of panes) {
    const h = new THREE.Box3Helper(box.clone().expandByScalar(1.5), removed ? 0xff2bd6 : 0x00e5ff);
    h.material.depthTest = false; h.renderOrder = 10; p.scene.add(h); boxes.push(h);
    const s = new THREE.Sprite(new THREE.SpriteMaterial({map: removed ? RING.m : RING.c, depthTest: false, transparent: true, sizeAttenuation: false}));
    s.position.copy(box.getCenter(new THREE.Vector3())); s.renderOrder = 11; p.scene.add(s); rings.push(s);
  }
}
function setPose(q) { pose = q; for (const p of panes) setModel(p); }
function layout() {
  const W = stage.clientWidth, H = stage.clientHeight; renderer.setSize(W, H); const stacked = W < 700;
  panes.forEach((p, i) => { p.rect = stacked ? [0, i === 0 ? H / 2 : 0, W, H / 2] : [i * W / 2, 0, W / 2, H]; });
}
function render() {
  if (anim) {
    const k = Math.min(1, (performance.now() - anim.t0) / 600), e = k * k * (3 - 2 * k);
    controls.target.lerpVectors(anim.c0, anim.c1, e); camera.position.lerpVectors(anim.p0, anim.p1, e);
    if (k >= 1) anim = null;
  }
  const pulse = 0.5 + 0.5 * Math.sin(performance.now() / 1000 * 6);      // ~1 Hz
  M.srem.emissiveIntensity = M.sadd.emissiveIntensity = 0.35 + 1.65 * pulse;
  for (const r of rings) { r.scale.setScalar(0.15 + 0.06 * pulse); r.material.opacity = 0.55 + 0.45 * pulse; }
  renderer.setScissorTest(true);
  for (const p of panes) {
    const [x, y, w, h] = p.rect; renderer.setViewport(x, y, w, h); renderer.setScissor(x, y, w, h);
    camera.aspect = w / h; camera.updateProjectionMatrix(); renderer.render(p.scene, camera);
  }
}
for (const n of Object.keys(DATA.parts)) {
  const l = document.createElement("label"), cb = document.createElement("input");
  cb.type = "checkbox"; cb.checked = true;
  cb.onchange = () => { cb.checked ? hidden.delete(n) : hidden.add(n); applyAll(); };
  l.append(cb, " " + n); $("parts").append(l, " ");
}
$("bc").onclick = () => setPose("closed");
$("bo").onclick = () => setPose("open");
$("bf").onclick = () => focus();
$("bw").onclick = () => whole();
$("xray").onchange = e => { xrayUser = e.target.checked; applyAll(); };
$("diff").onchange = e => { showDiff = e.target.checked; applyAll(); };

// ---- playback
let cmpInit = false, cur = 0, curFrame = 0, token = 0, playing = false, timer = null, speed = 1, firstPb = true;
const strip = $("strip");
steps.forEach((s, i) => {
  const t = document.createElement("div"); t.className = "tick" + (s.is_edit ? (s.edit_ok === false ? " fail" : " edit") : (s.tool === "run_check" || s.tool === "test_fit" ? " chk" : ""));
  t.title = `${i + 1}: ${s.args_short || s.tool}`; strip.append(t);
});
const ticks = [...strip.children];
function caption(i) {
  const s = steps[i], f = PB.frames[s.frame], hl = stepHighlight, failed = s.is_edit && s.edit_ok === false;
  const cap = $("cap"); cap.className = hl ? "edit" : failed ? "fail" : "";
  const chip = hl ? '<span class="chip edit">EDIT</span>' : failed ? '<span class="chip fail">EDIT FAILED</span>' : "";
  $("c1").innerHTML = `step ${i + 1} / ${N} &middot; ${esc(s.args_short || s.tool)}${chip}`;
  const bad = failed || /^error/.test(s.result_short || "");
  $("c2").innerHTML = (bad ? `<span class="r">${esc(s.result_short)}</span>` : esc(s.result_short)) + (s.replay_error ? ` <span class="r">(replay: ${esc(s.replay_error)})</span>` : "");
  const lc = s.last_check;
  $("c3").textContent = lc ? `agent last saw (step ${lc.step}): ${lc.summary}` : "agent has not run a check yet";
  $("c4").innerHTML = `frame ${s.frame}/${PB.frames.length - 1}: ${esc(f.label)}` +
    (f.trusted === false ? ' <span class="chip warn">&#9888; frame from agent-written snapshot (untrusted)</span>' : "");
  $("cnt").textContent = `${i + 1} / ${N}`;
  ticks.forEach((t, k) => t.classList.toggle("cur", k === i));
}
async function showStep(i, instant, fitAll) {
  i = Math.max(0, Math.min(N - 1, i)); const my = ++token, s = steps[i];
  const root = await frameRoot(s.frame); if (my !== token) return;
  cur = i; curFrame = s.frame; stepHighlight = highlightOf(i);
  const p = panes[1];
  if (p.root !== root) { if (p.root) p.scene.remove(p.root); p.root = root; p.scene.add(root); }
  applyVis(panes[0].root); applyVis(root);
  if (fitAll) whole(initialDir(baseBox()));
  if (xrayUser === null) $("xray").checked = xrayNow();
  root.updateMatrixWorld(true);
  const b1 = new THREE.Box3(); b1.makeEmpty(); root.traverse(o => { if (o.isMesh && o.visible && /__step_(removed|added)$/.test(o.name)) b1.expandByObject(o); });
  let anyRem = false; root.traverse(o => { if (o.isMesh && o.visible && /__step_removed$/.test(o.name)) anyRem = true; });
  setBoxes(b1.isEmpty() ? null : b1, anyRem);
  if (!b1.isEmpty() && $("autofocus").checked) flyTo(b1, instant || !!fitAll);
  label(panes[1]); caption(i);
  for (const k of [i + 1, i + 2, i + 3]) if (k < N) frameRoot(steps[k].frame);
}
const stepMs = () => (stepHighlight ? 2500 : 1000) / speed;
function schedule() {
  clearTimeout(timer); if (!playing) return;
  timer = setTimeout(async () => { if (cur >= N - 1) return setPlaying(false); await showStep(cur + 1); schedule(); }, stepMs());
}
function setPlaying(v) { playing = v; $("bplay").innerHTML = v ? "&#10074;&#10074;" : "&#9654;"; if (!v) clearTimeout(timer); else schedule(); }
async function go(i, instant) { await showStep(i, instant); if (playing) schedule(); }
$("bfirst").onclick = e => { e.target.blur(); go(0); };
$("blast").onclick = e => { e.target.blur(); go(N - 1); };
$("bprev").onclick = e => { e.target.blur(); go(cur - 1); };
$("bnext").onclick = e => { e.target.blur(); go(cur + 1); };
$("bplay").onclick = async e => { e.target.blur(); togglePlay(); };
async function togglePlay() { if (!playing && cur >= N - 1) await showStep(0); setPlaying(!playing); }
$("speed").onchange = e => { speed = +e.target.value; e.target.blur(); schedule(); };
const idxAt = e => { const r = strip.getBoundingClientRect(); return Math.max(0, Math.min(N - 1, Math.floor((e.clientX - r.left) / r.width * N))); };
let drag = false;
strip.onpointerdown = e => { drag = true; strip.setPointerCapture(e.pointerId); go(idxAt(e), true); };
strip.onpointermove = e => { if (drag) { const i = idxAt(e); if (i !== cur) go(i, true); } };
strip.onpointerup = () => { drag = false; };
addEventListener("keydown", e => {
  if (mode !== "playback" || e.target.tagName === "SELECT") return;
  const k = e.key; let used = true;
  if (k === " ") togglePlay(); else if (k === "ArrowRight") go(cur + 1); else if (k === "ArrowLeft") go(cur - 1);
  else if (k === "Home") go(0); else if (k === "End") go(N - 1); else used = false;
  if (used) e.preventDefault();
});
addEventListener("keyup", e => { if (mode === "playback" && e.key === " ") e.preventDefault(); });

// ---- modes
function banner() {
  const b = $("banner"), st = PB && PB.status, msg = PB && PB.message ? `: ${PB.message}` : "";
  let t = "";
  if (!PB) t = "";
  else if (st === "mismatch" || st === "replay_error") t = `⚠ replay does not reproduce the graded submission${msg}`;
  else if (st === "truncated") t = `⚠ replay truncated${msg}`;
  else if (st === "no_log") t = "no action log: showing final state only";
  else if (st === "error") t = `⚠ playback failed${msg}`;
  b.hidden = !t; b.textContent = t; return t;
}
async function setMode(m, first) {
  mode = m; stepHighlight = false; setBoxes(null); anim = null;
  $("pb").style.display = m === "playback" ? "" : "none";
  $("legend").style.display = m === "playback" ? "" : "none";
  $("cmpctl").style.display = m === "playback" ? "none" : "";
  $("afl").style.display = m === "playback" ? "" : "none";
  $("mc").classList.toggle("on", m === "compare"); $("mp").classList.toggle("on", m === "playback");
  layout();
  if (m === "compare") {
    setPlaying(false); token++;
    const fresh = !cmpInit; cmpInit = true;
    if (fresh) pose = Object.values(V).some(x => x.diff_bbox) ? "open" : "closed";   // the closed lid hides the edited wall edge
    for (const p of panes) { setModel(p); label(p); }
    $("xray").checked = xrayNow();
    focus(fresh ? initialDir(baseBox()) : undefined);
  } else {
    setModel(panes[0]); label(panes[0]);
    await showStep(cur, !!firstPb, firstPb); firstPb = false;
  }
}
$("mc").onclick = () => setMode("compare");
$("mp").onclick = () => setMode("playback");
const note = banner();
$("pbnote").textContent = pbOk ? "" : (PB && PB.status === "no_log" ? "playback: no action log (final state only)"
  : PB && PB.status === "reproduced" ? "playback: no edits in the action log"
  : PB && PB.status === "disabled" ? "" : PB ? `playback unavailable: ${PB.message || PB.status}` : "");
if (pbOk) $("banner").hidden = !note || (PB.status === "no_log");
$("mp").disabled = !pbOk; if (!pbOk) $("mp").title = "no playback frames";
addEventListener("resize", layout);
new ResizeObserver(layout).observe(stage);
layout();
camera.position.set(0, 0, 100); controls.target.set(0, 0, 0);
const hs = Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
let startMode = pbOk ? "playback" : "compare";
if (hs.mode === "compare" || hs.mode === "playback") startMode = hs.mode === "playback" && !pbOk ? "compare" : hs.mode;
if (hs.step && pbOk) cur = Math.max(0, Math.min(N - 1, (parseInt(hs.step) || 1) - 1));
await setMode(startMode, true);
renderer.setAnimationLoop(() => { controls.update(); render(); });
</script></body></html>
"""


def _js(x) -> str:
    return json.dumps(x).replace("</", "<\\/")


def _write_viewer(out: Path, data: dict, glbs: dict, pb: dict | None = None, pb_glbs: list | None = None) -> Path:
    """pb = playback.json content (or {"status": ..., "message": ...} when there is none), pb_glbs = frame files."""
    b64 = {v: {q: base64.b64encode((out / f).read_bytes()).decode() for q, f in d.items()} for v, d in glbs.items()}
    frames = [base64.b64encode((out / "playback" / f).read_bytes()).decode() for f in (pb_glbs or [])]
    html = (VIEWER.replace("@@THREE@@", THREE).replace("@@DATA@@", _js(data)).replace("@@GLB@@", json.dumps(b64))
            .replace("@@PBGLB@@", json.dumps(frames)).replace("@@PB@@", _js(pb)))
    p = out / "viewer.html"
    p.write_text(html, encoding="utf-8")
    return p


def _playback(task_dir, pristine_dir, submitted_dir, out: Path, time_budget_s: float):
    """(playback dict for the viewer, frame file names to embed, summary for viz.json). Never raises."""
    from cadfix import playback as pbm
    try:
        pb = pbm.build_playback(task_dir, pristine_dir, submitted_dir, out / "playback", time_budget_s)
        frames = [f["file"] for f in pb["frames"]] if len(pb["frames"]) > 1 else []
        summary = {"status": pb["status"], "message": pb["message"], "steps": len(pb["steps"]),
                   "frames": len(pb["frames"]), "seconds": pb["seconds"], "dir": "playback"}
        return pb, frames, summary
    except Exception as e:  # noqa: BLE001 - playback must never break the viewer
        msg = f"{type(e).__name__}: {e}"[:300]
        return {"status": "error", "message": msg}, [], {"status": "error", "message": msg}


def _reference_assembly(original: Assembly, ref_dir: Path) -> Assembly | None:
    shapes = {}
    for n in original.editable:
        f = ref_dir / "parts" / f"{n}.step"
        if f.exists():
            shapes[n] = kernel.import_step(f)
    return original.with_shapes(shapes) if shapes else None


def visualize(task_dir, pristine_dir, submitted_dir, out_dir, report: dict | None = None, reference_dir=None,
              playback: bool = True, time_budget_s: float = 240) -> dict:
    """Write the viewer. playback=True also replays the agent's logged edits into out/playback/ (see cadfix.playback)
    and embeds the frames in viewer.html as a Playback mode; time_budget_s limits that replay."""
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
    pb, pb_frames, summary = ({"status": "disabled"}, [], {"status": "disabled"})
    if playback:
        pb, pb_frames, summary = _playback(task_dir, pristine_dir, submitted_dir, out, time_budget_s)
        info["files"] += ["playback/playback.json"] + [f"playback/{f}" for f in pb_frames]
    info["playback"] = summary
    _write_viewer(out, info, glbs, pb, pb_frames)
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
    ap.add_argument("--no-playback", action="store_true", help="skip the step-by-step replay of the agent's edits")
    ap.add_argument("--playback-budget", type=float, default=240, help="seconds the replay may take")
    a = ap.parse_args(argv)
    rep = json.loads(Path(a.report).read_text()) if a.report and Path(a.report).exists() else None
    info = visualize(a.task_dir, a.pristine, a.submitted, a.out, rep, a.reference,
                     playback=not a.no_playback, time_budget_s=a.playback_budget)
    print(f"wrote {len(info['files'])} files to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
