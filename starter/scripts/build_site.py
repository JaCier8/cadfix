"""Build the static demo site (GitHub Pages): an overview page + the run dashboards + every run's 3D viewer.

  python3 scripts/build_site.py [--out site] [--video demo/cadfix_demo.mp4]

Host Python, stdlib only (no Docker): it only copies viewers that already exist. Build them first with
`scripts/view.sh <dir>` (e.g. jobs/view_opus55, results/reference). Deploy: `scripts/deploy_site.sh`.

Layout of the output:
  index.html                         overview: results matrix (every trial chip opens its viewer), findings, repro
  <group>/index.html                 cadfix.show dashboard of that group
  <group>/<run>/.../viz/viewer.html  self-contained three.js viewer (GLBs embedded), with a back link added
  demo/cadfix_demo.mp4               the recorded demo, when present
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cadfix import show, show_index  # noqa: E402  (stdlib-only modules)

REPO = "https://github.com/JaCier8/cadfix"
TREE = REPO + "/tree/main/starter/"

# slug, title, kind, source, run selector, note, log (repo path of the archived Harbor job)
GROUPS = [
    dict(slug="reference", title="Reference solver", kind="ref", src="results/reference",
         runs=["L1/seed_0000", "L2/seed_0000", "L3/seed_0000"],
         note="The reference solver plays through the same MCP tools as the agent (local run_eval, seed 0). "
              "The Harbor oracle run scores the same 1.000 on all three levels.",
         log="harbor_runs/oracle_2026-11-15__07-37-23"),
    dict(slug="opus55", title="Claude Opus 5.5", kind="agent", src="jobs/view_opus55", runs="*",
         note="OpenCode 1.19.5, harbor_tasks/judge, -k 3.", log="harbor_runs/opus55_judge_k3_2026-11-15__07-55-50"),
    dict(slug="sonnet55", title="Claude Sonnet 5.5", kind="agent", src="jobs/view_sonnet55", runs="*",
         note="OpenCode 1.19.5, harbor_tasks/judge, -k 3.", log="harbor_runs/sonnet55_2026-11-15__06-48-21"),
    dict(slug="do_nothing", title="Do nothing", kind="base", src="results/do_nothing",
         runs=["L1/seed_0000", "L2/seed_0000", "L3/seed_0000"],
         note="Submits the untouched parts. Harbor nop run: 0.000 on all levels.",
         log="harbor_runs/nop_2026-11-15__07-38-15"),
    dict(slug="stop_early", title="Stop early", kind="base", src="results/stop_early",
         runs=["L1/seed_0000", "L2/seed_0000", "L3/seed_0000"],
         note="Inspects the task, then submits without a fix. Harbor stop-early run: 0.000 on all levels.",
         log="harbor_runs/stop_early_2026-11-15__02-22-43"),
]

# Trials worth opening first (ids are trial dir names); text grounded in README "Main finding".
FEATURED = [
    ("opus55", "hinge-lid-l3-seed0__UbNdaqs", "Opus sizes each rib separately",
     "Three different ribs, rotated frame. It measured each rib, cut one notch per rib, then undid and re-cut "
     "smaller after the first pass. Full points."),
    ("opus55", "hinge-lid-l3-seed0__uiW6Lhf", "Opus stops at the first pass",
     "One identical notch at all three ribs (1.55x the best known volume), submitted on its first passing fix: "
     "\"I didn't try to shrink the notches further because the clearance and seal margins are already small.\""),
    ("sonnet55", "hinge-lid-l3-seed0__yUegVYW", "Sonnet: one size for three ribs",
     "Every gate and the opening pass, but one relief size for three different ribs: 2.37x the best known "
     "volume, so minimal change scores 0."),
    ("reference", "L3/seed_0000", "Reference solver on L3",
     "The smallest valid relief per rib, sized from a 2D scan of the swept rib profile, cut through the same "
     "tools. 1.03x the best known volume."),
]

# Back links: inline in the viewer's top bar / above the dashboard's title (fixed positioning hid viewer controls).
BACK_VIEWER = ('<a href="../../../index.html" style="color:#00e5ff;text-decoration:none;font-weight:600;'
               'margin-right:10px">&larr; runs</a>')  # <run>/verifier/viz or <L>/seed/viz -> group index
BACK_INDEX = ('<a href="../index.html" style="display:inline-block;margin-bottom:12px;color:var(--cyan);'
              'text-decoration:none;font-weight:600">&larr; overview</a>')


def _load(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _copy(src: Path, dst: Path):
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def copy_run(src_run: Path, dst_run: Path) -> bool:
    """Copy only what the viewer and the dashboard read. Returns False if the run has no viewer."""
    trial = show._is_trial(src_run)
    sb, db = (src_run / "verifier", dst_run / "verifier") if trial else (src_run, dst_run)
    viewer = sb / "viz" / "viewer.html"
    if not viewer.exists():
        return False
    if trial:
        for f in ("config.json", "result.json"):
            _copy(src_run / f, dst_run / f)
    for f in ("grade.json", "reward.txt", "viz/viz.json", "viz/playback/playback.json"):
        _copy(sb / f, db / f)
    page = viewer.read_text()
    page = page.replace('<div id="bar">', '<div id="bar">' + BACK_VIEWER, 1)
    (db / "viz").mkdir(parents=True, exist_ok=True)
    (db / "viz" / "viewer.html").write_text(page)
    return True


def build_group(g: dict, out: Path) -> list[dict]:
    src = ROOT / g["src"]
    if not src.is_dir():
        print(f"warning: {g['src']} missing, skipping {g['slug']}", file=sys.stderr)
        return []
    runs = show.find_runs(src) if g["runs"] == "*" else [src / r for r in g["runs"]]
    base = out / g["slug"]
    copied = []
    for r in runs:
        rel = r.relative_to(src)
        if copy_run(r, base / rel):
            copied.append(base / rel)
        else:
            print(f"warning: {r} has no viewer (build it with scripts/view.sh {g['src']})", file=sys.stderr)
    recs = [show.run_record(base, r, show.viz_dir_of(r) / "viewer.html") for r in copied]
    for rec in recs:
        rec["group"] = g["title"]
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page = show_index.render(recs, g["log"], gen, f"cadfix runs - {g['title']}")
    page = page.replace("<h1>cadfix runs</h1>", f"<h1>{html.escape(g['title'])}</h1>", 1)
    page = page.replace("<header>", "<header>" + BACK_INDEX, 1)
    (base / "index.html").write_text(page)
    out_recs = []
    for r, rec in zip(copied, recs):
        gr = _load((r / "verifier" if show._is_trial(r) else r) / "grade.json") or {}
        s3 = ((gr.get("checks") or {}).get("S3_minimal_change") or {}).get("metrics") or {}
        out_recs.append(dict(group=g["slug"], id=rec["id"], level=rec["level"], reward=rec["reward"],
                             ratio=s3.get("ratio_to_reference"), changed=s3.get("changed_mm3"),
                             gates=rec["gates_ok"], s1=rec["s1"], steps=rec["steps"],
                             href=f"{g['slug']}/{rec['href']}"))
    return out_recs


# ---------------------------------------------------------------- overview page
def _cls(r):
    if r is None:
        return "na"
    return "ok" if r >= 0.995 else "mid" if r >= 0.75 else "low" if r > 0 else "zero"


def _fmt(x, d=3):
    return "–" if x is None else f"{x:.{d}f}"


def _chip_title(r) -> str:
    t = f"{r['id']}: reward {_fmt(r['reward'])}"
    if r["ratio"] is not None and r["changed"]:
        t += f", {r['ratio']:.2f}x the best known volume"
    return t


def overview(groups: list[dict], recs: list[dict], video: str | None) -> str:
    levels = ["L1", "L2", "L3"]
    by = {}
    for r in recs:
        by.setdefault(r["group"], {}).setdefault(r["level"], []).append(r)
    rows = []
    for g in groups:
        cells, means = [], []
        for L in levels:
            rs = sorted(by.get(g["slug"], {}).get(L, []), key=lambda r: -(r["reward"] or 0))
            if not rs:
                cells.append('<td class="lv"><span class="mute">not run</span></td>')
                continue
            m = sum(r["reward"] or 0 for r in rs) / len(rs)
            means.append(m)
            chips = "".join(
                f'<a class="chip {_cls(r["reward"])}" href="{html.escape(r["href"])}" '
                f'title="{html.escape(_chip_title(r))}">{_fmt(r["reward"], 2)}</a>' for r in rs)
            cells.append(f'<td class="lv"><div class="lm">{_fmt(m)}</div><div class="chips">{chips}</div></td>')
        mean = sum(means) / len(means) if means else None
        bar = f'<div class="bar"><i style="width:{(mean or 0) * 100:.1f}%"></i></div>'
        rows.append(f'<tr class="{g["kind"]}"><th scope="row"><a href="{g["slug"]}/index.html">{html.escape(g["title"])}</a>'
                    f'<div class="note">{html.escape(g["note"])}</div></th>{"".join(cells)}'
                    f'<td class="mean"><b>{_fmt(mean)}</b>{bar}</td></tr>')
    rows.insert(3, '<tr class="manual"><th scope="row">Hydrogen (weak model)<div class="note">Manual go/no-go: no tools, '
                   'ops as JSON, 3 attempts with test_fit feedback. No 3D replay.</div></th>'
                   '<td class="lv"><div class="lm">1.000</div></td><td class="lv"><div class="lm">0.400</div></td>'
                   '<td class="lv"><span class="mute">not run</span></td><td class="mean"><span class="mute">–</span></td></tr>')

    idx = {(r["group"], r["id"]): r for r in recs}
    feats = []
    for slug, rid, title, text in FEATURED:
        r = idx.get((slug, rid))
        if not r:
            continue
        who = next(g["title"] for g in groups if g["slug"] == slug)
        feats.append(f'<a class="feat" href="{html.escape(r["href"])}"><div class="fh"><span class="lvl">{r["level"]}</span>'
                     f'<span class="who">{html.escape(who)}</span><span class="rw {_cls(r["reward"])}">{_fmt(r["reward"])}</span></div>'
                     f'<h3>{html.escape(title)}</h3><p>{html.escape(text)}</p>'
                     f'<span class="open">Open 3D replay &rarr;</span></a>')

    vid = (f'<section id="video"><h2>Demo video</h2><video controls preload="metadata" playsinline poster="demo/poster.jpg" src="{video}"></video></section>'
           if video else "")
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return OVERVIEW.replace("__ROWS__", "\n".join(rows)).replace("__FEATS__", "\n".join(feats)) \
        .replace("__VIDEO__", vid).replace("__VIDEOBTN__", '<a class="btn" href="#video">Watch the demo</a>' if video else "") \
        .replace("__REPO__", REPO).replace("__TREE__", TREE).replace("__GEN__", gen)


OVERVIEW = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>cadfix: fix the hinge</title>
<meta name="description" content="An RL environment where an AI agent repairs a jammed 3D-printed hinge with CAD tools. Every run replayed in 3D.">
<style>
:root{--bg:#1e2024;--panel:#272a30;--panel2:#2e3239;--line:#3a3f48;--fg:#e8eaee;--mut:#9aa1ad;--mag:#ff2bd6;--cyan:#00e5ff;
--red:#ff5d5d;--grn:#3ddc84;--amb:#ffb74d;color-scheme:dark}
@media (prefers-color-scheme:light){:root{--bg:#f3f4f7;--panel:#fff;--panel2:#eef0f4;--line:#d6dae1;--fg:#1c1f24;--mut:#5b6472;
--mag:#c4009f;--cyan:#007c94;--red:#c62828;--grn:#1b8a46;--amb:#a35c00;color-scheme:light}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:inherit}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9em}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px 64px}
header{padding:48px 0 18px}
.tag{font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--mag)}
h1{font-size:clamp(30px,5vw,48px);line-height:1.08;letter-spacing:-.02em;margin:10px 0 14px}
h1 em{font-style:normal;color:var(--mag)}
.lead{font-size:18px;color:var(--mut);max-width:780px;margin:0}
.btns{display:flex;flex-wrap:wrap;gap:10px;margin-top:22px}
.btn{display:inline-block;padding:9px 16px;border-radius:999px;border:1px solid var(--line);background:var(--panel);text-decoration:none;font-weight:600}
.btn.pri{border-color:var(--mag);color:var(--mag)}
.btn:hover{border-color:var(--cyan)}
section{margin-top:44px}
h2{font-size:22px;letter-spacing:-.01em;margin:0 0 6px}
.sec-sub{color:var(--mut);margin:0 0 16px;max-width:820px}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:14px;background:var(--panel)}
table{border-collapse:collapse;width:100%;min-width:760px}
th,td{padding:12px 14px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}
thead th{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);font-weight:600}
tbody tr:last-child>*{border-bottom:0}
tbody th{width:28%;font-weight:700}
tbody th a{text-decoration:none;border-bottom:1px dashed var(--mut)}
tbody th a:hover{color:var(--cyan);border-color:var(--cyan)}
.note{font-weight:400;font-size:12.5px;color:var(--mut);margin-top:4px;line-height:1.4}
tr.ref th a{color:var(--cyan)}
tr.manual{opacity:.75}
.lm{font-weight:700;font-variant-numeric:tabular-nums;font-family:ui-monospace,Menlo,Consolas,monospace}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.chip{font:600 12px ui-monospace,Menlo,Consolas,monospace;padding:3px 8px;border-radius:7px;text-decoration:none;border:1px solid}
.chip:hover{transform:translateY(-1px);filter:brightness(1.15)}
.ok{color:var(--grn)} .mid{color:var(--amb)} .low{color:var(--red)} .zero{color:var(--mut)}
.chip.ok{background:color-mix(in srgb,var(--grn) 14%,transparent)} .chip.mid{background:color-mix(in srgb,var(--amb) 14%,transparent)}
.chip.low{background:color-mix(in srgb,var(--red) 14%,transparent)} .chip.zero{background:color-mix(in srgb,var(--mut) 12%,transparent)}
td.mean b{font:700 18px ui-monospace,Menlo,Consolas,monospace}
.bar{height:6px;border-radius:3px;background:var(--panel2);margin-top:8px;overflow:hidden;min-width:80px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--mag),var(--cyan))}
.mute{color:var(--mut)}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:var(--mut);margin-top:10px}
.feats{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}
.feat{display:flex;flex-direction:column;gap:6px;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;text-decoration:none;transition:border-color .12s,transform .12s}
.feat:hover{border-color:var(--mag);transform:translateY(-2px)}
.fh{display:flex;align-items:center;gap:8px;font-size:12.5px}
.lvl{font-weight:700;padding:1px 8px;border-radius:999px;border:1px solid var(--mag);color:var(--mag)}
.who{color:var(--mut)} .rw{margin-left:auto;font:700 14px ui-monospace,Menlo,Consolas,monospace}
.feat h3{margin:4px 0 0;font-size:16px}
.feat p{margin:0;color:var(--mut);font-size:13.5px;flex:1}
.open{font-weight:600;color:var(--cyan);font-size:13.5px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.card h3{margin:0 0 8px;font-size:15px}
.card p,.card li{color:var(--mut);font-size:14px;margin:0}
.card ul,.card ol{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:6px}
.card b{color:var(--fg)}
.formula{font:13px/1.6 ui-monospace,Menlo,Consolas,monospace;background:var(--panel2);border-radius:9px;padding:10px 12px;margin-top:10px;color:var(--fg)}
.ladder{counter-reset:s;display:flex;flex-direction:column;gap:12px}
.step{display:grid;grid-template-columns:44px 1fr;gap:14px;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.step::before{counter-increment:s;content:counter(s);display:grid;place-items:center;width:36px;height:36px;border-radius:10px;
background:linear-gradient(135deg,var(--mag),var(--cyan));color:#111;font-weight:800}
.step h3{margin:0 0 4px;font-size:15.5px}
.step p{margin:0;color:var(--mut);font-size:14px}
blockquote{margin:8px 0 0;padding:6px 12px;border-left:3px solid var(--mag);color:var(--fg);font-size:13.5px;background:var(--panel2);border-radius:0 8px 8px 0}
pre{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;overflow-x:auto;font-size:13px;line-height:1.6;margin:0}
pre .c{color:var(--mut)}
video{width:100%;border-radius:14px;border:1px solid var(--line);background:#000;display:block}
.ex td,.ex th{font-size:13.5px;padding:9px 14px}
.ex td.n{font-family:ui-monospace,Menlo,Consolas,monospace;white-space:nowrap}
footer{margin-top:56px;padding-top:18px;border-top:1px solid var(--line);color:var(--mut);font-size:13px;display:flex;flex-wrap:wrap;gap:8px 20px}
:focus-visible{outline:2px solid var(--cyan);outline-offset:2px}
</style></head><body><div class="wrap">

<header>
<div class="tag">AfterQuery · Break the Agent</div>
<h1>Can an AI agent fix a jammed <em>3D-printed hinge</em>?</h1>
<p class="lead">cadfix is an RL environment where an agent edits real B-rep CAD parts through MCP tools. The lid of a printed box
jams while opening; the agent has to make it open to 110&deg; while changing as little material as possible.
Every run below is replayed step by step in 3D, next to the reference fix.</p>
<div class="btns"><a class="btn pri" href="#results">See the runs</a>__VIDEOBTN__<a class="btn" href="__REPO__">Code &amp; one-command eval</a></div>
</header>

<section id="results">
<h2>Results on the judge set</h2>
<p class="sec-sub">Harbor, <code>harbor_tasks/judge</code> (L1, L2, L3 seed 0), OpenCode 1.19.5, three trials per level.
Each chip is one trial: click it to open the 3D replay of every tool call, the agent's fix next to the reference fix, and the grade.</p>
<div class="tw"><table>
<thead><tr><th>Agent</th><th>L1 · easy</th><th>L2 · strict minimal change</th><th>L3 · 3 different ribs, rotated</th><th>Mean</th></tr></thead>
<tbody>
__ROWS__
</tbody></table></div>
<div class="legend"><span><b class="ok">green</b> full points</span><span><b class="mid">amber</b> 0.75–0.99</span>
<span><b class="low">red</b> &lt; 0.75</span><span><b class="zero">grey</b> 0</span><span>Hover a chip for its volume vs the best known fix.</span></div>
</section>

<section>
<h2>Start here</h2>
<p class="sec-sub">Four replays that show where the gap comes from. In Playback, the magenta/cyan marks are this step's change; the left pane shows the reference fix.</p>
<div class="feats">__FEATS__</div>
</section>

__VIDEO__

<section>
<h2>The task</h2>
<div class="cols">
<div class="card"><h3>What the agent gets</h3><p>A printable box with a hinged lid as B-rep solids. While the lid opens, a rib under each lid
knuckle swings into the top of the rear wall: it jams around 40–70&deg;. The agent gets the bug report, every requirement with its
threshold, the scoring formula and the protected zones with coordinates. <b>Never the cause or the fix.</b></p></div>
<div class="card"><h3>Tools (MCP)</h3><ul>
<li><b>Inspect</b>: measure, section, edge/face queries</li>
<li><b>Edit</b>: chamfer, fillet, offset_face, extrude_cut, cut_box, add_box, undo</li>
<li><b>Check</b>: run_check_&lt;id&gt; (free), test_fit (2 free calls)</li>
<li><b>Budget</b>: 150 tool calls, 1 hour</li></ul></div>
<div class="card"><h3>How it is scored</h3><p>Any gate fails (broken solid, hinge or seal touched, protected zone cut, part rebuilt) &rarr; <b>0</b>.
Otherwise the opening sweep, printability and minimal change vs the best known fix (the agent is told the rule, never the volume).</p>
<div class="formula">S1 not met &rarr; 0.25 &times; progress<br>S1 met &rarr; 0.3 + 0.1&times;print + 0.6&times;minimal change</div></div>
</div>
</section>

<section>
<h2>What separates the models</h2>
<p class="sec-sub">All of them find the clash. The gap is whether they keep working once a fix passes. The information was there in
every run, so the remaining gap is a decision, not a missing fact.</p>
<div class="ladder">
<div class="step"><div><h3>Weaker models fall for the full-edge cut</h3><p>Hydrogen tuned one full-edge chamfer on every attempt:
3.2&times; the best known volume, 0.400 on L2. It never tried a local relief.</p></div></div>
<div class="step"><div><h3>Sonnet 5.5 stops at the first passing fix</h3><p>Every rib fixed locally, gates and opening 9/9, but each trial
called test_fit once and submitted the first fix that passed, with 120+ tool calls left. 0/9 tried to shrink a passing cut.
On L3 all three used one relief size for three different ribs.</p>
<blockquote>"I did not try to shrink the pockets further, so some of the minimal-change score may be left on the table."</blockquote></div></div>
<div class="step"><div><h3>Opus 5.5 is close, still below the reference on 3 of 9</h3><p>It optimised after its first passing fix in 4/9 trials
(undo, re-cut smaller, re-check). The L3 trial that sized each rib separately reached full points; it lost points where it skipped that step.</p>
<blockquote>"Total now ~14.8 mm³ (was 23.3). Running the free checks."</blockquote></div></div>
</div>
</section>

<section>
<h2>Reward integrity</h2>
<p class="sec-sub">The verifier runs in a separate container with its own grader code, task copy and pristine parts. Doing nothing or
stopping early scores 0; any working fix beats any broken one; a tailored fix beats a wasteful one. Exploit suite
(<code>python -m scenarios.hinge_lid.exploits --level L2,L3 --seeds 0</code>):</p>
<div class="tw"><table class="ex">
<thead><tr><th>Exploit</th><th>L2</th><th>L3</th><th>Caught by</th></tr></thead><tbody>
<tr><td>shorten the ribs / cut the lid's hinge side</td><td class="n">0.000</td><td class="n">0.000</td><td>G2, G3 keep-in</td></tr>
<tr><td>hollow the rear wall + full-edge relief</td><td class="n">0.300</td><td class="n">0.300</td><td>S2 thin walls, S3</td></tr>
<tr><td>huge cut / cut through the seal band</td><td class="n">0.000</td><td class="n">0.000</td><td>G3, G5 seal</td></tr>
<tr><td>fill the box / scaled copy / lid saved already opened</td><td class="n">0.000</td><td class="n">0.000</td><td>G3 keep-out, G4, G6</td></tr>
<tr><td>edit fixed parts or the agent's own task files</td><td class="n">0.000</td><td class="n">0.000</td><td>verifier uses its own copies</td></tr>
<tr><td>garbage / deleted outputs, spam test_fit, submit then keep editing</td><td class="n">0.000</td><td class="n">0.000</td><td>treated as the original</td></tr>
</tbody></table></div>
</section>

<section>
<h2>Reproduce</h2>
<p class="sec-sub">From <a href="__TREE__">the repo</a> (Docker + <code>pip install harbor==0.26.0</code>):</p>
<pre><span class="c"># reference run, agent x3, do-nothing, stop-early</span>
harbor run -p harbor_tasks/judge -a oracle
harbor run -p harbor_tasks/judge -a opencode -m &lt;provider/model&gt; -k 3
harbor run -p harbor_tasks/judge -a nop
PYTHONPATH=. harbor run -p harbor_tasks/judge -a cadfix.harbor.agents:StopEarlyAgent
<span class="c"># open the 3D viewer of any run</span>
scripts/view.sh jobs/&lt;job&gt;</pre>
</section>

<footer><span>cadfix · built __GEN__</span><a href="__REPO__">GitHub</a><a href="__TREE__docs/RUNS.md">All runs (docs/RUNS.md)</a>
<span>3D viewers load three.js from jsDelivr.</span></footer>
</div></body></html>
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="site")
    ap.add_argument("--video", default="demo/cadfix_demo.mp4", help="demo video to include ('' = none)")
    ap.add_argument("--poster-at", default="40", help="video poster frame time in seconds (needs ffmpeg)")
    a = ap.parse_args(argv)
    out = (ROOT / a.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    recs = []
    for g in GROUPS:
        recs += build_group(g, out)
    video = None
    if a.video and (ROOT / a.video).exists():
        (out / "demo").mkdir()
        shutil.copy2(ROOT / a.video, out / "demo" / Path(a.video).name)
        video = f"demo/{Path(a.video).name}"
        if shutil.which("ffmpeg"):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", a.poster_at, "-i", str(ROOT / a.video),
                            "-frames:v", "1", "-q:v", "4", str(out / "demo" / "poster.jpg")], check=False)
    (out / "index.html").write_text(overview(GROUPS, recs, video))
    (out / ".nojekyll").write_text("")
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"{out}: {len(recs)} runs, {size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
