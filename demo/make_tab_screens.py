"""Screenshots of the information tabs, for the "Więcej informacji" scene of the demo video.

Usage: python make_tab_screens.py <out_dir> [site_url]

Desktop, light mode; the site's own header is cut off (the video draws its own tab bar).
"""

import pathlib
import sys

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
SITE = (sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000").rstrip("/")
TABS = [("1", "ostrzezenia", "#warningsGrid article"), ("2", "jak-to-dziala", ".flip-card"),
        ("3", "discord", "#discordAction"), ("4", "o-projekcie", "#corpusBadge")]
CLIP = {"x": 0, "y": 150, "width": 1280, "height": 650}   # below the site's own top bar and tabs

with sync_playwright() as p:
    browser = p.chromium.launch()
    for name, tab, ready in TABS:
        page = browser.new_page(viewport={"width": 1280, "height": 800}, color_scheme="light")
        page.goto(f"{SITE}/#{tab}", wait_until="networkidle")
        page.wait_for_selector(ready, timeout=15000)
        if tab == "jak-to-dziala":   # show one card turned over, as a visitor would see on hover
            page.evaluate("document.querySelectorAll('.flip-card')[1].classList.add('flipped')")
        page.wait_for_timeout(1400)
        page.screenshot(path=str(OUT / f"{name}.jpg"), type="jpeg", quality=85, clip=CLIP)
        page.close()
        print("tab", name, tab)
    browser.close()
