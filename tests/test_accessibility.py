# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Read paths: reachable by keyboard, understandable by a screen reader.

The scope agreed with the operator: everything that can be *read* targets
WCAG 2.2 AA; the rich editor and the adventure canvas are served by an
accessible markdown / list alternative and declared non-conforming in the
published statement. These checks therefore visit read paths only — pointing
axe at the rich editor would gate the build on a screen we deliberately do not
rewrite.

Needs the Playwright image (`open-quizz-tests:latest`), a reachable instance in
`OL_TEST_BASE_URL`, and `tools/axe/axe.min.js` (vendored, so runs never depend on
a CDN).
"""

import pathlib

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.test_frontend_e2e import BASE_URL, ConsoleRecorder

AXE = pathlib.Path(__file__).resolve().parents[1] / "tools" / "axe" / "axe.min.js"

# Paths anyone can open without an account. "/" is the presentation page on a
# demo instance and the wiki listing on a private one; both are read paths.
READ_PATHS = ["/", "/quizzes", "/wiki", "/about", "/legal", "/docs", "/docs/mcp", "/login", "/register", "/accessibility" ]

BLOCKING = {"serious", "critical"}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


def open_page(browser, viewport=(1280, 900), theme="dark"):
    """A context that lets us inject axe.

    Instances send `script-src 'self'`, which refuses an inline script — the
    protection is doing its job, so the measurement run opts out instead of the
    product being changed to allow it.
    """
    context = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]}, bypass_csp=True
    )
    context.add_init_script(
        "try { localStorage.setItem('ol_language', 'en'); localStorage.setItem('ol_theme', '%s'); }"
        " catch (e) {}" % theme
    )
    page = context.new_page()
    return context, page, ConsoleRecorder(page)


def settle(page):
    """Let the entrance animations finish before measuring.

    Sections arrive with `data-reveal` starting at opacity 0: axe run on that
    frame reads a half-transparent text colour over its own background and
    reports a contrast failure that no user ever sees. The measurement waits for
    the real state instead of the product being flattened to satisfy a probe.
    """
    try:
        page.wait_for_function(
            """() => [...document.querySelectorAll('[data-reveal]')]
                       .every((el) => getComputedStyle(el).opacity === '1')""",
            timeout=5000,
        )
    except Exception:  # an element that never reveals must not fail the audit
        pass
    page.wait_for_timeout(250)


def violations(page, tags=("wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa")):
    page.add_script_tag(path=str(AXE))
    return page.evaluate(
        """async (tags) => {
          const results = await axe.run(document, {
            runOnly: { type: 'tag', values: tags },
          });
          return results.violations.map((violation) => ({
            id: violation.id,
            impact: violation.impact,
            help: violation.help,
            nodes: violation.nodes.slice(0, 4).map((node) => node.target.join(' ')),
          }));
        }""",
        list(tags),
    )


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("path", READ_PATHS)
def test_no_serious_violation_on_a_read_path(browser, path, theme):
    context, page, recorder = open_page(browser, theme=theme)
    try:
        page.goto(f"{BASE_URL}{path}", wait_until="networkidle")
        settle(page)
        found = violations(page)
        blocking = [item for item in found if item["impact"] in BLOCKING]
        assert not blocking, f"{path} ({theme}): {blocking}"
        assert recorder.errors == [], f"{path}: {recorder.errors}"
    finally:
        context.close()


@pytest.mark.parametrize("path", READ_PATHS)
def test_one_heading_and_a_landmark_per_view(browser, path):
    context, page, _ = open_page(browser)
    try:
        page.goto(f"{BASE_URL}{path}", wait_until="networkidle")
        assert page.locator("h1").count() == 1, f"{path} has {page.locator('h1').count()} h1"
        expect(page.locator("main")).to_have_count(1)
        # A page may hold several navigation blocks (header, page list, pager);
        # what matters is that a screen reader can tell them apart.
        unnamed = page.evaluate(
            """() => [...document.querySelectorAll('nav')]
                 .filter((nav) => !(nav.getAttribute('aria-label')
                                 || nav.getAttribute('aria-labelledby')))
                 .map((nav) => nav.className || nav.id)"""
        )
        assert unnamed == [], f"{path} has unnamed nav: {unnamed}"
        # The first heading must be the h1, not an h2 announced before it.
        first_heading = page.evaluate("() => document.querySelector('h1,h2,h3,h4,h5,h6')?.tagName")
        assert first_heading == "H1", f"{path} starts on {first_heading}"
    finally:
        context.close()


def test_the_skip_link_is_the_first_thing_a_keyboard_finds(browser):
    context, page, _ = open_page(browser)
    try:
        page.goto(f"{BASE_URL}/quizzes", wait_until="networkidle")
        page.keyboard.press("Tab")
        focused = page.evaluate("() => document.activeElement?.getAttribute('href')")
        assert focused == "#app", f"first tab stop is {focused}"

        # Activating it moves the focus into the content, not merely the scroll.
        page.keyboard.press("Enter")
        page.wait_for_timeout(150)
        assert page.evaluate("() => document.activeElement?.id") == "app"
    finally:
        context.close()


def test_the_current_section_is_marked_for_a_screen_reader(browser):
    context, page, _ = open_page(browser)
    try:
        page.goto(f"{BASE_URL}/wiki", wait_until="networkidle")
        current = page.locator('#nav a[aria-current="page"]')
        expect(current).to_have_count(1)
        assert current.inner_text().strip().lower() in {"wiki", "wikis"}
        assert page.locator("#nav").get_attribute("aria-label")
    finally:
        context.close()


def test_a_new_page_is_announced_and_keeps_the_focus(browser):
    """Moving between views must not leave the focus on the old document."""
    context, page, _ = open_page(browser)
    try:
        page.goto(f"{BASE_URL}/wiki", wait_until="networkidle")
        page.locator('#nav a[href="/quizzes"]').click()
        page.wait_for_url("**/quizzes")
        page.wait_for_timeout(300)
        assert page.evaluate("() => document.activeElement?.id") == "app"
        # The announcement region carries the new page title, once.
        assert page.locator("#route-announcer").inner_text().strip() != ""
    finally:
        context.close()


def test_the_confirmation_dialog_can_be_used_without_a_mouse(browser):
    """A modal has to trap Tab, close on Escape and give the focus back."""
    context, page, _ = open_page(browser)
    try:
        page.goto(f"{BASE_URL}/quizzes", wait_until="networkidle")
        page.locator("#nav a[href=\"/quizzes\"]").focus()
        page.evaluate(
            """() => import('/js/ui.js').then((ui) => { window.__dlg = ui.confirmDialog('Delete', 'This cannot be undone.', 'Delete'); })"""
        )
        page.wait_for_selector(".modal[role=\"dialog\"]")
        modal = page.locator(".modal")
        assert modal.get_attribute("aria-modal") == "true"
        assert modal.get_attribute("aria-labelledby") == "modal-title"
        assert modal.get_attribute("aria-describedby") == "modal-desc"
        assert page.locator("#modal-desc").inner_text().strip() != ""

        # The safe answer, not the destructive one, takes the focus.
        assert page.evaluate("() => document.activeElement.dataset.action") == "cancel"

        # Tab cycles inside the dialog instead of escaping to the page.
        for _ in range(4):
            page.keyboard.press("Tab")
            inside = page.evaluate("() => Boolean(document.activeElement.closest('.modal'))")
            assert inside, "the focus left the dialog"

        page.keyboard.press("Escape")
        page.wait_for_timeout(100)
        assert page.locator(".modal").count() == 0
        # Once closed, the keyboard lands back where it was.
        assert page.evaluate("() => document.activeElement.getAttribute('href')") == "/quizzes"
    finally:
        context.close()


@pytest.mark.parametrize("path", READ_PATHS)
@pytest.mark.parametrize("width", [390, 320])
def test_a_read_path_never_scrolls_sideways_on_a_phone(browser, path, width):
    """WCAG 2.2 reflow (1.4.10): no horizontal scrolling at 320 px.

    Two regressions hid here. A documentation table whose parameter names set a
    min-content width wider than the screen, and a footer link row one item too
    long: both left the page 8 px wider than the viewport, so the reader could
    drag the whole document sideways to find the end of a sentence.
    """
    context, page, recorder = open_page(browser, viewport=(width, 800))
    try:
        page.goto(f"{BASE_URL}{path}", wait_until="networkidle")
        settle(page)
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        culprits = page.evaluate(
            """(limit) => [...document.querySelectorAll('body *')]
                 .filter((el) => Math.round(el.getBoundingClientRect().right) > limit + 1)
                 .slice(0, 5)
                 .map((el) => el.tagName.toLowerCase() + '.' + String(el.className || '').split(' ')[0])""",
            width,
        )
        assert overflow <= 1, f"{path} at {width}px is {overflow}px wider than its screen: {culprits}"
        assert recorder.errors == [], f"{path}: {recorder.errors}"
    finally:
        context.close()
