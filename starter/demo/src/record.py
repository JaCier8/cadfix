"""Record the demo scenes with Playwright. Each scene -> its own webm + a log of (t_ready, t_end, cues)."""
import asyncio, json, sys, time, re
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
ONLY = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
H = "http://127.0.0.1:8765/jobs/"
VIEW = H + "{}/verifier/viz/viewer.html"
ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
W, Hh = 1600, 900


class Scene:
    def __init__(self, pg):
        self.pg, self.cues, self.t_ready = pg, [], None
    def ready(self):
        self.t_ready = time.monotonic()
    def cue(self, text):
        self.cues.append([round(time.monotonic() - self.t_ready, 2), text])
    async def wait(self, s):
        await self.pg.wait_for_timeout(int(s * 1000))


async def hide_parts(pg, names):
    await pg.evaluate("""(names) => { for (const l of document.querySelectorAll('#parts label')) {
        const n = l.textContent.trim(); const cb = l.querySelector('input');
        if (names.includes(n) && cb.checked) cb.click(); } }""", names)


async def orbit(pg, dx, dy, secs, x=400, y=450):
    n = max(1, int(secs / 0.04))
    await pg.mouse.move(x, y); await pg.mouse.down()
    for i in range(1, n + 1):
        await pg.mouse.move(x + dx * i / n, y + dy * i / n); await pg.wait_for_timeout(40)
    await pg.mouse.up()


async def zoom(pg, ticks, secs=1.0, x=400, y=450):
    await pg.mouse.move(x, y)
    for _ in range(ticks):
        await pg.mouse.wheel(0, -250 if ticks > 0 else 250); await pg.wait_for_timeout(int(secs * 1000 / abs(ticks)))


async def compare_rear(sc, run, intro, cues, hold=11):
    """Compare mode, closed, lid hidden, seen from behind/above the rear wall."""
    pg = sc.pg
    await pg.goto(VIEW.format(run) + "#mode=compare"); await pg.wait_for_timeout(5500)
    await pg.click("#bc"); await hide_parts(pg, ["lid", "lid_module", "hinge_pin"])
    await pg.click("#bf"); await pg.wait_for_timeout(1500)
    sc.ready(); sc.cue(intro)
    await orbit(pg, -430, 60, 2.2)
    await zoom(pg, 6, 1.4)
    await sc.wait(1.0)
    per = (hold - 4.6) / max(1, len(cues))
    for c in cues:
        sc.cue(c); await sc.wait(per)


# ---------------------------------------------------------------- scenes
async def s_card(sc, name, secs):
    await sc.pg.goto(H + f"demo/cards.html?card={name}"); await sc.pg.wait_for_timeout(1200)
    sc.ready(); await sc.wait(secs)


async def s_problem(sc):
    pg = sc.pg
    await pg.goto(VIEW.format("view_opus55/hinge-lid-l3-seed0__UbNdaqs") + "#mode=compare"); await pg.wait_for_timeout(5500)
    await pg.select_option("#p0 select", "original")
    await pg.click("#bw"); await pg.click("#bo"); await pg.wait_for_timeout(1500)
    sc.ready()
    sc.cue("A printed box with a hinged lid. Left: the original part. Right: what an agent made of it.")
    await orbit(pg, 260, 0, 4.0)
    sc.cue("Opening it, a rib under each hinge knuckle swings into the rear wall: the lid jams around 40°, never reaching 110°.")
    await pg.click("#bf"); await sc.wait(1.0); await zoom(pg, 3, 1.0); await sc.wait(3.0)
    sc.cue("The agent gets CAD tools over MCP, every requirement with its threshold, and the scoring rule. Never the fix.")
    await orbit(pg, -200, 40, 3.0); await sc.wait(2.5)


async def s_dashboard(sc):
    pg = sc.pg
    await pg.goto(H + "view_opus55/index.html"); await pg.wait_for_timeout(2000)
    sc.ready()
    sc.cue("Opus 5.5 on the judge set: 9 trials, mean 0.963. All gates passed, and every replay reproduces the graded parts.")
    await sc.wait(4.5)
    for _ in range(12):
        await pg.mouse.wheel(0, 60); await pg.wait_for_timeout(80)
    sc.cue("Three trials stayed below the reference, all because of minimal change. Let's open the interesting ones.")
    await sc.wait(4.5)


async def s_playback(sc):
    pg = sc.pg
    await pg.goto(VIEW.format("view_opus55/hinge-lid-l3-seed0__UbNdaqs") + "#mode=playback&step=1"); await pg.wait_for_timeout(5500)
    sc.ready()
    sc.cue("Opus 5.5 on L3: three different ribs, the whole assembly rotated in space. This is the replay of every tool call.")
    await sc.wait(3.5)
    total = int((await pg.inner_text("#cnt")).split("/")[1])
    seen = set()
    while True:
        cur = int((await pg.inner_text("#cnt")).split("/")[0])
        title = (await pg.inner_text("#c1")).strip()
        tool = title.split("·", 1)[-1].strip().split(" ")[0].removesuffix("EDIT")
        hold = 0.45
        if tool in ("measure", "section") and "measure" not in seen:
            sc.cue("It measures the interference at several angles and cuts sections through the ribs."); hold = 1.6
        elif tool in ("extrude_cut",) and "undo" in seen and "recut" not in seen:
            seen.add("recut")
            sc.cue("...and re-cuts each rib to its own swept radius: 3.70, 3.50 and 3.57 mm."); hold = 2.0
        elif tool in ("extrude_cut", "cut_box") and "cut" not in seen:
            sc.cue("Then one notch per rib, cut along the path the rib sweeps."); hold = 1.6
        elif tool in ("extrude_cut", "cut_box"):
            hold = 0.9
        elif tool == "test_fit" and "test_fit" not in seen:
            sc.cue("The first fix passes every check: 23.3 mm³ removed. This is where Sonnet submitted, every time."); hold = 4.5
        elif tool == "undo" and "undo" not in seen:
            sc.cue("Opus instead undoes all three cuts..."); hold = 1.6
        elif tool == "submit":
            sc.cue("Submitted at 14.8 mm³, 0.93× the best known fix. Reward 1.0."); hold = 4.0
        elif tool == "run_check" and "undo" in seen and "checks" not in seen:
            seen.add("checks"); sc.cue("Then it re-checks every requirement one by one before submitting."); hold = 0.8
        seen.add({"extrude_cut": "cut", "cut_box": "cut", "section": "measure"}.get(tool, tool))
        await sc.wait(hold)
        if cur >= total:
            break
        await pg.keyboard.press("ArrowRight"); await pg.wait_for_timeout(150)


async def s_best(sc):
    await compare_rear(sc, "view_opus55/hinge-lid-l3-seed0__UbNdaqs",
        "Same trial, from behind the wall. Red = material removed. Left: the reference fix. Right: Opus.",
        ["Both size each notch to its own rib: the reference volume is 15.9 mm³, Opus removed 14.8 mm³ (0.93×)."], hold=11)


async def s_opus_bad(sc):
    await compare_rear(sc, "view_opus55/hinge-lid-l3-seed0__uiW6Lhf",
        "Another Opus attempt at the same task. The reference cuts differ per rib; Opus copied one notch three times.",
        ["24.7 mm³ = 1.55× the best known fix, submitted after its first passing check. Reward 0.714.",
         "Its explanation: “I didn't try to shrink the notches further because the clearance and seal margins are already small.”"],
        hold=15)


async def s_sonnet_bad(sc):
    await compare_rear(sc, "view_sonnet55/hinge-lid-l3-seed0__yUegVYW",
        "Sonnet 5.5 on the same task: identical rectangular pockets instead of a relief that follows the rib's sweep.",
        ["37.6 mm³ = 2.37× the necessary material, past the zero line for minimal change. Reward 0.400.",
         "And it knew: “I did not try to shrink the pockets further, so some of the minimal-change score may be left on the table.”"],
        hold=15)


SCENES = [
    ("01_title", lambda sc: s_card(sc, "title", 7)),
    ("02_problem", s_problem),
    ("03_score", lambda sc: s_card(sc, "score", 10)),
    ("04_results", lambda sc: s_card(sc, "results", 10)),
    ("05_dashboard", s_dashboard),
    ("06_playback", s_playback),
    ("07_best", s_best),
    ("08_opus_bad", s_opus_bad),
    ("09_sonnet_bad", s_sonnet_bad),
    ("10_finding", lambda sc: s_card(sc, "finding", 12)),
    ("11_end", lambda sc: s_card(sc, "end", 7)),
]


async def main():
    log = json.loads((OUT / "log.json").read_text()) if (OUT / "log.json").exists() else {}
    async with async_playwright() as p:
        b = await p.chromium.launch(args=ARGS)
        for name, fn in SCENES:
            if ONLY and name not in ONLY:
                continue
            ctx = await b.new_context(viewport={"width": W, "height": Hh}, record_video_dir=str(OUT / "raw"),
                                      record_video_size={"width": W, "height": Hh})
            t0 = time.monotonic()
            pg = await ctx.new_page()
            pg.on("pageerror", lambda e: print("pageerror:", e))
            sc = Scene(pg)
            await fn(sc)
            t_end = time.monotonic()
            vpath = await pg.video.path()
            await ctx.close()
            dst = OUT / f"{name}.webm"
            Path(vpath).replace(dst)
            log[name] = {"start": round(sc.t_ready - t0, 2), "dur": round(t_end - sc.t_ready, 2), "cues": sc.cues}
            print(name, log[name]["start"], log[name]["dur"], len(sc.cues), "cues", flush=True)
            (OUT / "log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False))
        await b.close()

asyncio.run(main())
