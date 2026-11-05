#!/usr/bin/env python3
"""用 Playwright 逐帧截取网页特效页，输出到 assets/web/<page>/f_%04d.jpg。

每个页面都实现了 window.__seek(t)：只要给同一个 t，画面就完全一致，
因此可以和音轨精确对帧，不需要录屏。
"""
import argparse
import glob
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES_DIR = os.path.join(ROOT, "pages")
OUT_DIR = os.path.join(ROOT, "assets", "web")
FPS = 24
QUALITY = 92

PAGES = [
    ("01_radar", 2.36),
    ("02_console", 3.22),
    ("03_poster", 2.50),
    ("04_manga", 2.84),
    ("05_glitch", 3.44),
    ("06_sms", 2.78),
    ("07_circuit", 2.05),
    ("08_profile", 1.22),
    ("09_stats", 1.72),
    ("10_cctv", 2.26),
]


def chromium_path():
    hits = sorted(glob.glob("/root/.cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
    return hits[-1] if hits else None


def capture(page_name, duration, browser):
    out = os.path.join(OUT_DIR, page_name)
    os.makedirs(out, exist_ok=True)
    n = int(round(duration * FPS))
    url = "file://" + os.path.join(PAGES_DIR, page_name + ".html")
    pg = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    pg.goto(url + "?t=0", wait_until="load")
    pg.wait_for_function("window.__ready === true", timeout=20000)
    for i in range(n):
        t = i / FPS
        pg.evaluate("t => window.__seek(t)", t)
        pg.wait_for_timeout(25)
        pg.screenshot(path=os.path.join(out, f"f_{i:04d}.jpg"),
                      type="jpeg", quality=QUALITY)
        if i % 60 == 0:
            print(f"  {page_name} {i}/{n}", flush=True)
    pg.close()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page", nargs="*", help="只截取指定页面")
    args = ap.parse_args()
    only = set(args.page)
    exe = chromium_path()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        total = 0
        for name, dur in PAGES:
            if only and name not in only:
                continue
            n = capture(name, dur, browser)
            total += n
            print(f"{name}: {n} frames", flush=True)
        browser.close()
    print(f"done, {total} frames -> {OUT_DIR}")


if __name__ == "__main__":
    main()
