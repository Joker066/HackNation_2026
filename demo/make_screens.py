"""Screenshots of the site in many variants, for the "Dla każdego" train in the demo video.

Usage: python make_screens.py <out_dir> [site_url] [result_id_false] [result_id_insufficient]

Uses saved results (/r/<id>), so no new checks are run.
"""

import pathlib
import sys

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
SITE = (sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000").rstrip("/")
R_FALSE = sys.argv[3] if len(sys.argv) > 3 else "ad653e57345c"
R_NONE = sys.argv[4] if len(sys.argv) > 4 else "7d8f2fc2d2c3"

DESKTOP = {"viewport": {"width": 1280, "height": 800}}
PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True}

# name, device, theme, font size, path, scroll (px)
SHOTS = [
    ("01", DESKTOP, "light", "normal", f"/r/{R_FALSE}", 0),
    ("02", PHONE, "light", "normal", f"/r/{R_FALSE}", 0),
    ("03", DESKTOP, "dark", "normal", f"/r/{R_NONE}", 0),
    ("04", PHONE, "dark", "normal", f"/r/{R_FALSE}", 260),
    ("05", DESKTOP, "light", "xlarge", f"/r/{R_FALSE}", 0),
    ("06", PHONE, "light", "xlarge", f"/r/{R_NONE}", 0),
    ("07", DESKTOP, "dark", "normal", "/#jak-to-dziala", 0),
    ("08", PHONE, "dark", "large", "/", 0),
    ("09", DESKTOP, "light", "normal", "/#discord", 0),
    ("10", PHONE, "light", "normal", "/#ostrzezenia", 0),
    ("11", DESKTOP, "dark", "xlarge", f"/r/{R_FALSE}", 420),
    ("12", PHONE, "dark", "normal", f"/r/{R_NONE}", 0),
]

with sync_playwright() as p:
    browser = p.chromium.launch()
    for name, device, theme, size, path, scroll in SHOTS:
        ctx = browser.new_context(color_scheme=theme, **device)
        page = ctx.new_page()
        page.goto(SITE + path, wait_until="networkidle")
        page.wait_for_timeout(700)
        if size != "normal":
            page.evaluate(f"setFontSize('{size}')")
            page.evaluate("document.getElementById('toastNotification')?.classList.add('hidden')")
        if path.startswith("/r/"):
            page.wait_for_selector("text=Wynik sprawdzenia", timeout=15000)
        page.wait_for_timeout(500)
        page.evaluate(f"window.scrollTo(0, {scroll})")
        page.wait_for_timeout(1200)  # page transitions, fonts, toast gone
        page.evaluate("document.getElementById('toastNotification')?.classList.add('hidden')")
        page.screenshot(path=str(OUT / f"{name}.jpg"), type="jpeg", quality=82)
        ctx.close()
        print("shot", name, theme, size, path)
    browser.close()
