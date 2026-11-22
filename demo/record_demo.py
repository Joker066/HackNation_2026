"""Record the Tap & Check highlight video from the live site (desktop web UI).

Usage (from demo/, with ./start.sh running):
  python make_screens.py screens                      # once: screenshots for the "Dla każdego" train
  python make_tab_screens.py tabs                     # once: tab pages for the "Więcej informacji" scene
  python record_demo.py stage.html icon.jpg screens tapcheck_demo.mp4 [site_url]

The site runs for real (real questions, real answers). Only the waiting time is shown
faster (×6), and the video says so on screen while it happens. If a verdict is not the
expected one, the script stops instead of making a misleading video.

Inside the stage's iframe the browser blocks the site's localStorage, so the demo checks
are saved without a session id; they hold no personal data and expire after 30 days.
"""

import base64
import json
import pathlib
import subprocess
import sys
import time

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

STAGE, ICON, SCREENS, OUT = (pathlib.Path(a) for a in sys.argv[1:5])
SITE = sys.argv[5] if len(sys.argv) > 5 else "http://localhost:8000/"
SPEED = 6
TYPE_MS = 55
Q1 = ("Czy szczepionki przeciw COVID-19 zawierają mikroczipy?", "Fałsz")
Q2 = ("Od jutra w Rzeszowie obowiązuje godzina policyjna?", "Brak wystarczających dowodów")
PHONES = {"02", "04", "06", "08", "10", "12"}

WORK = OUT.parent / "raw"
WORK.mkdir(parents=True, exist_ok=True)


def data_uri(path, mime):
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


train = "".join(
    f'<img class="{"phone" if p.stem in PHONES else "desk"}" src="{data_uri(p, "image/jpeg")}" alt="">'
    for p in sorted(SCREENS.glob("*.jpg"))
)
tab_imgs = "".join(f'<img src="{data_uri(p, "image/jpeg")}" alt="">' for p in sorted((SCREENS.parent / "tabs").glob("*.jpg")))
html = (STAGE.read_text(encoding="utf-8")
        .replace("TAB_IMAGES", tab_imgs)
        .replace("ICON_DATA_URI", data_uri(ICON, "image/jpeg"))
        .replace("TRAIN_IMAGES", train))

marks = []

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, color_scheme="light",
                              record_video_dir=str(WORK), record_video_size={"width": 1920, "height": 1080})
    page = ctx.new_page()
    t0 = time.monotonic()
    mark = lambda name: marks.append((name, round(time.monotonic() - t0, 3)))
    js, pause = page.evaluate, page.wait_for_timeout

    page.set_content(html, wait_until="networkidle")
    js(f"document.getElementById('app').src = {json.dumps(SITE)}")
    app = page.frame_locator("#app")
    app.locator("#verifyInput").wait_for()
    frame = page.frame(name="app")
    frame.wait_for_load_state("networkidle")
    pause(600)

    def ask(question, expected, nth):
        js(f"typeInto({json.dumps(question)}, {TYPE_MS})")
        app.locator("#verifyInput").press_sequentially(question, delay=TYPE_MS)
        pause(350)
        app.locator("#checkBtn").click()
        js("speed(true)"); mark(f"wait{nth}_start")
        result = app.locator("text=Wynik sprawdzenia").nth(nth - 1)
        result.wait_for(timeout=90000)
        mark(f"wait{nth}_end"); js("speed(false)")
        verdict = frame.evaluate("[...document.querySelectorAll('#chatLog article')].pop().querySelector('span span').textContent")
        if verdict.strip() != expected:
            sys.exit(f"Unexpected verdict for {question!r}: {verdict!r} (expected {expected!r}). Run again.")

    # --- intro
    mark("start")
    js("scene('intro')"); pause(2800)

    # --- 1. paste anything → real check
    js("scene('main')")
    js("caption(1, 'Wklej <em>cokolwiek</em>', 'Pytanie, SMS, link albo zrzut ekranu.', 'Wpisujesz')"); pause(1500)
    ask(*Q1, nth=1)

    # --- 2. verdict with evidence
    js("caption(2, 'Werdykt <em>z dowodem</em>', 'Dosłowne cytaty i linki do źródeł.')"); pause(2400)
    frame.evaluate("window.scrollBy({top: 430, behavior: 'smooth'})"); pause(2800)

    # --- 3. honest "we don't know"
    js("caption(3, 'Nie wiemy? <em>Mówimy to.</em>', 'Bez dowodów nie ma werdyktu.', 'Wpisujesz')"); pause(1100)
    ask(*Q2, nth=2)
    pause(3200)

    # --- 4. more information: the pointer hovers each tab, its page appears
    js("scene('tabs')"); pause(1100)
    for i in range(4):
        js(f"hoverTab({i})"); pause(2600 if i == 2 else 2000)   # a little longer on Discord

    # --- 5. the train: many screens, accelerating to the left
    js("scene('train')"); pause(900)
    js("runTrain(5200)"); pause(5300)

    # --- outro: the title leaves, a short calm pause on the empty background, then fade in + float up
    js("scene(null)"); pause(1300)
    js("outro()"); pause(3800)
    mark("end")

    video_path = page.video.path()
    ctx.close(); browser.close()

m = dict(marks)
print("marks:", m)
cuts = [("n", m["start"], m["wait1_start"]), ("f", m["wait1_start"], m["wait1_end"]),
        ("n", m["wait1_end"], m["wait2_start"]), ("f", m["wait2_start"], m["wait2_end"]),
        ("n", m["wait2_end"], m["end"])]
parts, labels = [], []
for i, (kind, a, b) in enumerate(cuts):
    pts = f"(PTS-STARTPTS)/{SPEED}" if kind == "f" else "PTS-STARTPTS"
    parts.append(f"[0:v]trim=start={a}:end={b},setpts={pts}[v{i}]")
    labels.append(f"[v{i}]")
graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(cuts)}:v=1:a=0,fps=30,format=yuv420p[out]"
subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", video_path,
                "-filter_complex", graph, "-map", "[out]", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                "-movflags", "+faststart", str(OUT)], check=True)
total = sum((b - a) / (SPEED if k == "f" else 1) for k, a, b in cuts)
print(f"video: {OUT}  (~{total:.1f} s)")
