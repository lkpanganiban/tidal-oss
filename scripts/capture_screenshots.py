#!/usr/bin/env python3
"""Capture the Tidal MSP web app (TELEMAC-2D refinement outputs) as screenshots.

Drives the MapLibre GL JS frontend served by src/web/app.py and saves PNGs for
each key interaction state.  Run it against a server pointed at a TELEMAC
refinement output directory:

    GEOTIFF_PATH=output/telemac/region-001/tidal_power_density.tif \
        python -m src.web.app --host 127.0.0.1 --port 5055 &

    .venv/bin/python scripts/capture_screenshots.py --base http://127.0.0.1:5055 --out screenshots

Note: on macOS port 5000 is owned by ControlCenter (AirPlay) and returns
HTTP 403, so use a different port and pass it with --base.  --base overrides
the server URL for both the page navigation and the JSON API fetches.

Requires Playwright + Chromium (pip install playwright && playwright install chromium).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request

from playwright.async_api import async_playwright

VIEWPORT = {"width": 1440, "height": 900}
BASE = "http://127.0.0.1:5000"
API = BASE + "/api"


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def wait_for(fn, timeout=30.0, interval=0.4):
    async def _wait(page):
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await fn(page):
                return True
            await page.wait_for_timeout(interval * 1000)
        return False

    return _wait


async def goto_and_settle(page):
    await page.goto(BASE, wait_until="networkidle", timeout=60000)
    # Wait for the map to load and the layer manager to populate.
    ok = await wait_for(
        lambda p: p.evaluate(
            "() => !!(window.__map && window.__map.isStyleLoaded() && document.querySelectorAll('#layer-list .layer-row').length)"
        ),
        timeout=60.0,
    )(page)
    if not ok:
        print("!! map/layers did not settle", file=sys.stderr)
    await page.wait_for_timeout(1500)


async def screenshot(page, name: str, out_dir: str):
    await page.wait_for_timeout(400)
    path = f"{out_dir}/{name}"
    await page.screenshot(path=path)
    print(f"  saved {path}")


async def fly_to_region(page):
    """Center the map on the power layer's bounds (the refinement region)."""
    meta = fetch_json(API + "/layers")["layers"]["power"]
    if not meta.get("available"):
        return
    b = meta["bounds"]
    lon = (b["west"] + b["east"]) / 2.0
    lat = (b["south"] + b["north"]) / 2.0
    await page.evaluate(
        f"""() => {{
            const m = window.__map;
            m.jumpTo({{ center: [{lon}, {lat}], zoom: 8.5 }});
        }}"""
    )
    await page.wait_for_timeout(2500)


async def main():
    global BASE, API
    parser = argparse.ArgumentParser(description="Capture Tidal MSP screenshots")
    parser.add_argument("--out", default="screenshots", help="output directory")
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    import os

    BASE = args.base
    API = BASE + "/api"

    os.makedirs(args.out, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport=VIEWPORT, device_scale_factor=1)

        print("== 01 overview (power layer) ==")
        await goto_and_settle(page)
        await fly_to_region(page)
        await screenshot(page, "01-map-power-overview.png", args.out)

        print("== 02 all data layers on ==")
        for name in ["speed", "depth", "distance"]:
            await page.evaluate(
                f"""() => {{
                    const row = document.querySelector('#layer-list .layer-row[data-layer="{name}"]');
                    if (row) {{ const cb = row.querySelector('input[type=checkbox]'); if (cb && !cb.checked) cb.click(); }}
                }}"""
            )
        await page.wait_for_timeout(2500)
        await screenshot(page, "02-map-all-layers.png", args.out)

        print("== 03 satellite basemap ==")
        await page.click('#basemap-pills button[data-base="satellite"]')
        await page.wait_for_timeout(3000)
        await screenshot(page, "03-map-satellite.png", args.out)

        print("== 04 dark basemap ==")
        await page.click('#basemap-pills button[data-base="dark"]')
        await page.wait_for_timeout(3000)
        await screenshot(page, "04-map-dark.png", args.out)

        print("== 05 hotspot inspector (site + tidal + turbine charts) ==")
        await page.click('#basemap-pills button[data-base="osm"]')
        # Use the first hotspot from the API so the site has model data.
        hots = fetch_json(API + "/hotspots?limit=5").get("features", [])
        if hots:
            c = hots[0]["geometry"]["coordinates"]
            await page.evaluate(
                f"""() => {{
                    const m = window.__map;
                    m.flyTo({{ center: [{c[0]}, {c[1]}], zoom: 9 }});
                }}"""
            )
            await page.wait_for_timeout(1500)
            await page.evaluate(
                f"""() => {{ inspectPoint({{ lng: {c[0]}, lat: {c[1]} }}); }}"""
            )
            ok = await wait_for(
                lambda p: p.evaluate(
                    "() => document.querySelectorAll('#card-query .stat').length >= 4"
                ),
                timeout=30.0,
            )(page)
            if not ok:
                print("!! inspector stats did not appear", file=sys.stderr)
            # Wait for the tidal curve + turbine output charts to render.
            await page.wait_for_timeout(3500)
        await screenshot(page, "05-site-inspector.png", args.out)

        print("== 06 hotspots list ==")
        # Close the inspector card so this shot shows the hotspot ranking.
        await page.evaluate("() => hideCard('card-query')")
        await page.wait_for_timeout(500)
        await screenshot(page, "06-hotspots-list.png", args.out)

        print("== 07 export menu ==")
        await page.click("#btn-export")
        await page.wait_for_timeout(600)
        await screenshot(page, "07-export-menu.png", args.out)
        await page.keyboard.press("Escape")
        await page.click("body", position={"x": 700, "y": 300})

        print("== 08 polygon site assessment ==")
        await page.click("#btn-draw")
        await page.wait_for_timeout(500)
        if hots:
            c = hots[0]["geometry"]["coordinates"]
            # Draw via the map's public API instead of raw pixels.
            await page.evaluate(
                f"""() => {{
                    const c = {[c[0], c[1]]};
                    const pts = [
                        [c[0] - 0.2, c[1] - 0.2],
                        [c[0] + 0.2, c[1] - 0.2],
                        [c[0] + 0.2, c[1] + 0.2],
                        [c[0] - 0.2, c[1] + 0.2],
                    ];
                    pts.forEach(p => addDrawPoint({{ lng: p[0], lat: p[1] }}));
                    finishAreaDraw();
                }}"""
            )
        ok = await wait_for(
            lambda p: p.evaluate(
                "() => !!document.querySelector('#area-results .stat')"
            ),
            timeout=30.0,
        )(page)
        if not ok:
            print("!! area assessment did not complete", file=sys.stderr)
        await page.wait_for_timeout(1200)
        await screenshot(page, "08-polygon-assessment.png", args.out)
        await page.click("#area-cancel")
        await page.wait_for_timeout(400)

        print("== 09 resource screening totals ==")
        ok = await wait_for(
            lambda p: p.evaluate(
                "() => document.getElementById('rt-area').textContent.trim() !== '—'"
            ),
            timeout=30.0,
        )(page)
        if not ok:
            print("!! resource totals did not load", file=sys.stderr)
        await screenshot(page, "09-resource-screening.png", args.out)

        print("== 10 measure tool ==")
        await page.click("#btn-measure")
        await page.wait_for_timeout(300)
        await screenshot(page, "10-measure-tool.png", args.out)

        await browser.close()
    print("Done. Screenshots written to", args.out)


if __name__ == "__main__":
    asyncio.run(main())
