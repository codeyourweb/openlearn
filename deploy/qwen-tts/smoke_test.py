# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Smoke test of speech, in a real browser, against a running instance.

Generates a transcript from the wiki editor with the actual engine, then plays
it on the page and asserts the audio really advances. Run it with the same
Playwright image the end-to-end suite uses:

    docker run --rm --network <instance network> -v "$PWD":/work -w /work \
      -e OL_TEST_BASE_URL=http://openlearn:8000 --entrypoint python ol-pw \
      smoke_test.py
"""

from __future__ import annotations

import os
import sys
import time
import uuid

from playwright.sync_api import sync_playwright

BASE = os.environ.get("OL_TEST_BASE_URL", "http://ol-test:8000")
SHOTS = os.environ.get("OL_SHOTS", "/work/shots")


def main() -> int:
    email = f"audio-{uuid.uuid4().hex[:10]}@example.org"
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        page.on("console", lambda message: errors.append(f"console: {message.text}") if message.type == "error" else None)

        page.goto(f"{BASE}/register", wait_until="networkidle")
        page.fill("#display_name", "Audio Author")
        page.fill("#email", email)
        page.fill("#password", "TestingPassw0rd!")
        page.click("#register-form button[type=submit]")
        page.wait_for_url("**/dashboard", timeout=20000)

        csrf = next((c["value"] for c in context.cookies() if c["name"] == "ol_csrf"), "")
        headers = {"X-CSRF-Token": csrf}
        wiki = context.request.post(
            f"{BASE}/api/v1/wiki",
            headers=headers,
            data={"title": "Manuel réseau", "description": "", "default_language": "fr"},
        ).json()
        page_created = context.request.post(
            f"{BASE}/api/v1/wiki/{wiki['id']}/pages",
            headers=headers,
            data={
                "title": "Bases du DNS",
                "content_md": "# Bases du DNS\n\nUn résolveur cache les réponses pendant un moment. "
                "Il les garde jusqu'à expiration du TTL.",
            },
        ).json()
        print("page:", page_created["id"], page_created["slug"])

        page.goto(f"{BASE}/wiki/{wiki['id']}/edit/{page_created['id']}", wait_until="networkidle")
        button = page.locator("[data-audio-open]")
        button.wait_for(state="visible", timeout=15000)
        print("bouton transcription visible")
        page.screenshot(path=f"{SHOTS}/audio-editor-button.png")

        button.click()
        page.wait_for_selector("#audio-gen[open]", timeout=10000)
        estimate = page.locator("[data-audio-estimate]").inner_text()
        print("estimation:", estimate)
        page.screenshot(path=f"{SHOTS}/audio-dialog.png")
        page.click("[data-audio-start]")

        started = time.time()
        # Success closes the dialog; a failure leaves it open with a reason. The
        # interface language is the reader's, so the text itself is not asserted.
        while time.time() - started < 420:
            if page.locator("#audio-gen").count() == 0:
                break
            page.wait_for_timeout(2000)
        elapsed = int(time.time() - started)
        still_open = page.locator("#audio-gen").count() > 0
        print(f"job terminé en {elapsed} s, boîte encore ouverte: {still_open}")
        if still_open:
            print("statut:", page.locator("[data-audio-status]").inner_text())
            page.screenshot(path=f"{SHOTS}/audio-error.png")
            print("échec:", errors[:5])
            return 1

        page.goto(f"{BASE}/wiki/{wiki['id']}/p/{page_created['slug']}", wait_until="networkidle")
        card = page.locator(".audio-card")
        card.wait_for(state="visible", timeout=20000)
        title = page.locator(".audio-title").inner_text()
        print("lecteur:", title)
        page.screenshot(path=f"{SHOTS}/audio-player.png")

        page.click("[data-audio-toggle]")
        page.wait_for_timeout(4000)
        position = page.evaluate("() => document.querySelector('[data-audio-pos]').textContent")
        paused = page.evaluate("() => document.querySelector('[data-audio-toggle]').getAttribute('aria-pressed')")
        print("position après 4 s:", position, "aria-pressed:", paused)
        page.screenshot(path=f"{SHOTS}/audio-playing.png")

        if position in ("0:00", "", None):
            print("l'audio n'avance pas")
            return 1

        page.click("[data-audio-toggle]")
        page.wait_for_timeout(600)
        print("erreurs:", errors[:5])
        context.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
