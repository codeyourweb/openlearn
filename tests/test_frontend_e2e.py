# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Frontend end-to-end tests (Playwright, real Chromium).

Run against a live instance:

    OL_TEST_BASE_URL=http://localhost:8080 pytest -m e2e

They are skipped automatically when no instance URL is provided.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

pytestmark = pytest.mark.e2e

BASE_URL = os.environ.get("OL_TEST_BASE_URL", "").rstrip("/")

PASSWORD = "E2eTestingPassw0rd!"


@pytest.fixture(scope="session", autouse=True)
def _require_instance():
    if not BASE_URL:
        pytest.skip("OL_TEST_BASE_URL is not set: end-to-end tests need a running instance.")


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


class ConsoleRecorder:
    """Collect console errors and uncaught exceptions raised by the page."""

    def __init__(self, page):
        self.errors: list[str] = []
        page.on("console", self._on_console)
        page.on("pageerror", lambda exc: self.errors.append(f"pageerror: {exc}"))

    # Chromium noise that is not a frontend defect: missing favicon, the
    # anonymous /auth/me probe answering 401, and the COOP warning it emits on
    # plain-http origins (the suite runs against the container, not behind TLS).
    IGNORED = (
        "favicon",
        "Failed to load resource",
        "Cross-Origin-Opener-Policy header has been ignored",
    )

    def _on_console(self, message):
        if message.type == "error":
            text = message.text
            if any(token in text for token in self.IGNORED):
                return
            self.errors.append(f"console: {text}")


def new_page(browser, viewport=(1280, 900), force_language: bool = True):
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]})
    if force_language:
        # The interface defaults to French; the assertions below are written in
        # English, so pin the language before any page script runs. The script
        # runs on every navigation, so it must stay off during language tests.
        context.add_init_script("try { localStorage.setItem('ol_language', 'en'); } catch (e) {}")
    page = context.new_page()
    recorder = ConsoleRecorder(page)
    return context, page, recorder


def register_through_ui(page, email: str, name: str = "E2E User") -> None:
    page.goto(f"{BASE_URL}/register", wait_until="networkidle")
    page.fill("#display_name", name)
    page.fill("#email", email)
    page.fill("#password", PASSWORD)
    # A whole run creates an account per scenario, and a hardened instance
    # answers the sixteenth one with 429. Left alone, that surfaces as "the page
    # did not reach /dashboard", which sends the reader hunting a frontend bug.
    refused = []
    page.on(
        "response",
        lambda response: refused.append(response)
        if response.url.endswith("/api/v1/auth/register") and response.status == 429
        else None,
    )
    page.click("#register-form button[type=submit]")
    try:
        expect(page).to_have_url(re.compile(r".*/dashboard$"), timeout=15000)
    except AssertionError:
        if refused:
            pytest.fail(
                "The instance refused this registration with 429: the run creates "
                "one account per scenario and the auth rate limit counts them. "
                "Raise the limit on the instance under test, or run fewer "
                "scenarios at once."
            )
        raise


def create_quiz_through_editor(page, title: str) -> int:
    # /quizzes/new picks the format, /quizzes/new/qcm the method, then the editor.
    page.goto(f"{BASE_URL}/quizzes/new/qcm/manual", wait_until="networkidle")
    page.fill("#quiz-title", title)
    page.fill("#quiz-description", "Created by the end-to-end test suite.")

    # First question
    first_rte = page.locator(".rte").first
    first_rte.click()
    page.keyboard.type("What is the capital of France?")
    option_inputs = page.locator('input[data-field="option-text"]')
    option_inputs.nth(0).fill("Paris")
    option_inputs.nth(1).fill("Lyon")
    # A live session test spends time asserting the host screen; with the
    # default 30 s the question can close under the guest's fingers. Five
    # minutes keeps the countdown out of the assertions' way.
    page.locator("article.question-editor").nth(0).locator(
        'input[data-field="time_limit_seconds"]'
    ).fill("300")

    # Second question: multiple correct answers
    page.click("#add-question")
    second_card = page.locator(".question-editor").nth(1)
    second_card.locator(".rte").click()
    page.keyboard.type("Which of these are French cities?")
    second_card.locator('input[data-field="option-text"]').nth(0).fill("Marseille")
    second_card.locator('input[data-field="option-text"]').nth(1).fill("Nice")
    second_card.locator('[data-act="add-option"]').click()
    second_card.locator('input[data-field="option-text"]').nth(2).fill("Turin")
    second_card.locator('input[data-field="multiple"]').check()
    # In multiple mode the first answer stays correct; mark the second one too.
    second_card.locator('[data-act="toggle-correct"][data-o="1"]').click()
    page.locator("article.question-editor").nth(1).locator(
        'input[data-field="time_limit_seconds"]'
    ).fill("300")

    page.click("#save-quiz")
    expect(page.locator(".toast.success").first).to_be_visible(timeout=15000)
    expect(page).to_have_url(re.compile(r".*/quizzes/\d+/edit$"), timeout=15000)
    return int(re.search(r"/quizzes/(\d+)/edit$", page.url).group(1))




def _one_pixel_png() -> bytes:
    """A real PNG: Pillow refuses anything whose checksums do not add up."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (32, 96, 208)).save(buffer, format="PNG")
    return buffer.getvalue()


def _picture_png(width: int, height: int) -> bytes:
    """A plain PNG of the requested size, for interactions on an <img>."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (32, 96, 208)).save(buffer, format="PNG")
    return buffer.getvalue()


def current_question(page) -> str:
    """Text of the question on screen, lowercased."""
    return page.locator(".question-text").first.inner_text().lower()


def click_options(page, labels) -> None:
    """Tick answer buttons by label, surviving the list being repainted.

    A state broadcast replaces the whole answer list, which detaches the button
    that was just found: the locator is re-resolved on every attempt, and a click
    that lands on a stale node is retried. The selection is then *confirmed*
    before anything else clicks again — clicking twice on a checkbox deselects
    it, which used to turn a right answer into a wrong one.
    """
    for label in labels:
        for attempt in range(5):
            option = page.locator("[data-option]").filter(has_text=label).first
            try:
                expect(option).to_be_visible(timeout=15000)
                expect(option).to_be_enabled(timeout=5000)
                option.click(timeout=5000)
            except Exception:
                if attempt == 4:
                    raise
                page.wait_for_timeout(250)
                continue
            if wait_selected(option):
                break
            if attempt == 4:
                raise AssertionError(f"option {label!r} never looked selected")


def wait_selected(option, timeout_ms: int = 4000) -> bool:
    """Poll the button state without clicking it again."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            if option.get_attribute("aria-pressed") == "true":
                return True
            if "selected" in (option.get_attribute("class") or ""):
                return True
        except Exception:  # noqa: BLE001 - the node was repainted under us
            pass
        time.sleep(0.1)
    return False


def answer_current_question(page, correct: bool = True) -> None:
    """Answer whatever question is on screen, by text rather than by position.

    Session questions and answers are shuffled per session, so a fixed index is
    not a stable way to say "this one is correct". The card also re-renders
    between questions, so the labels are read and the choice is made from the
    same snapshot: never from a previous poll.
    """
    for _ in range(25):
        # Option buttons read "A\nParis": keep the label, drop the key.
        labels = page.eval_on_selector_all(
            "[data-option]",
            "(nodes) => nodes.map((node) => ((node.innerText || '').split('\\n').pop() || '').trim())",
        )
        capital = "Paris" in labels and "Lyon" in labels
        cities = "Marseille" in labels and "Nice" in labels and "Turin" in labels
        if capital:
            wanted = ["Paris"] if correct else ["Lyon"]
        elif cities:
            wanted = ["Marseille", "Nice"] if correct else ["Turin"]
        else:
            wanted = []
        if wanted and all(label in labels for label in wanted):
            click_options(page, wanted)
            page.locator('[data-act="submit"]').click()
            return
        page.wait_for_timeout(400)
    raise AssertionError(f"Question card never showed the expected answers (last labels: {labels})")


def read_pin(page) -> str:
    pin = page.locator(".pin-display").first.inner_text()
    return pin.strip().upper()


def test_signing_in_from_a_page_comes_back_to_that_page(browser):
    """Signing in used to land on the account page, whatever you were reading.

    The reader had to walk back to the article they wanted to edit. The page
    they left is remembered for the session, and this test proves the browser
    really returns there — the API cannot show it.
    """
    context, page, recorder = new_page(browser)
    try:
        email = f"e2e-return-{uuid.uuid4().hex[:10]}@example.com"
        register_through_ui(page, email, "Retour")

        page.click("#account-button")
        page.click("#logout-button")
        expect(page).to_have_url(re.compile(r".*/$"), timeout=15000)

        # A public page nobody would call a destination of the sign-in flow.
        page.goto(f"{BASE_URL}/about", wait_until="networkidle")
        page.click("#account-button")
        page.click("#account-popover a[href='/login']")
        expect(page).to_have_url(re.compile(r".*/login$"))

        page.fill("#email", email)
        page.fill("#password", PASSWORD)
        page.click("#login-form button[type=submit]")

        expect(page).to_have_url(re.compile(r".*/about$"), timeout=15000)
        assert not page.url.endswith("/account"), "the reader was sent to the account page"
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_register_create_and_play_solo(browser):
    context, page, recorder = new_page(browser)
    try:
        email = f"solo-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Solo Tester")
        quiz_id = create_quiz_through_editor(page, "Capital cities quiz")

        page.goto(f"{BASE_URL}/quizzes/{quiz_id}", wait_until="networkidle")
        page.locator('button[data-act="solo"]').first.click()
        expect(page).to_have_url(re.compile(r".*/play/[A-Z0-9]+$"), timeout=15000)
        expect(page.locator(".question-card")).to_be_visible(timeout=15000)
        expect(page.locator(".options-grid")).to_be_visible()

        # Questions are shuffled: answer by text, never by position.
        answer_current_question(page)
        expect(page.locator(".feedback.ok")).to_be_visible(timeout=15000)

        # Go to the second question and answer it as well.
        page.locator('[data-act="next"]').click()
        expect(page.locator(".question-text")).not_to_have_text("", timeout=15000)
        answer_current_question(page)
        expect(page.locator(".feedback.ok")).to_be_visible(timeout=15000)

        page.locator('[data-act="next"]').click()
        expect(page.locator(".card.center")).to_contain_text("Game over", timeout=15000)
        expect(page.locator(".pin-display")).to_contain_text("200")

        page.locator('a[href^="/results/"]').first.click()
        expect(page).to_have_url(re.compile(r".*/results/[A-Z0-9]+$"), timeout=15000)
        expect(page.locator("table").first).to_be_visible()
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_live_session_with_guest_and_join_lock(browser):
    host_context, host_page, host_errors = new_page(browser)
    guest_context, guest_page, guest_errors = new_page(browser, (900, 800))
    late_context, late_page, _ = new_page(browser, (900, 800))
    try:
        host_email = f"host-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(host_page, host_email, "Host Tester")
        create_quiz_through_editor(host_page, "Live quiz")

        host_page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
        host_page.locator('button[data-act="host"]').first.click()
        expect(host_page).to_have_url(re.compile(r".*/host/[A-Z0-9]+$"), timeout=15000)
        expect(host_page.locator(".pin-display")).to_be_visible(timeout=15000)
        pin = read_pin(host_page)

        # Guest joins with the PIN.
        guest_page.goto(f"{BASE_URL}/play/{pin}", wait_until="networkidle")
        guest_page.fill("#nickname", "Guest Tester")
        guest_page.click("#join-form button[type=submit]")
        expect(guest_page.locator(".participant-chip")).to_be_visible(timeout=15000)
        expect(host_page.locator(".participant-chip")).to_contain_text("Guest Tester", timeout=15000)

        # The host starts: no late join afterwards.
        host_page.locator('[data-act="start"]').click()
        expect(host_page.locator(".question-card")).to_be_visible(timeout=15000)
        expect(guest_page.locator(".question-card")).to_be_visible(timeout=15000)

        late_page.goto(f"{BASE_URL}/play/{pin}", wait_until="networkidle")
        expect(late_page.locator("#app")).to_contain_text(
            "already started", timeout=15000, ignore_case=True
        )

        # Guest answers correctly. With every player having answered, the server
        # reveals the question on its own: the host does not need to press.
        answer_current_question(guest_page)
        expect(host_page.locator(".option-btn.correct").first).to_be_visible(timeout=15000)
        expect(guest_page.locator(".feedback.ok")).to_be_visible(timeout=15000)

        # The host moves to the next question; the guest answers it wrong.
        host_page.locator('[data-act="next"]').click()
        expect(guest_page.locator(".question-card")).to_be_visible(timeout=15000)
        answer_current_question(guest_page, correct=False)

        # Last question: the automatic reveal turns the control into "finish".
        expect(guest_page.locator(".feedback.ko")).to_be_visible(timeout=15000)
        expect(host_page.locator(".option-btn.correct").first).to_be_visible(timeout=15000)
        host_page.locator('[data-act="finish"]').click()
        expect(guest_page.locator(".card.center")).to_contain_text("Game over", timeout=15000)

        # Pressing finish sends the host straight to the detailed results.
        expect(host_page).to_have_url(re.compile(r".*/results/[A-Z0-9]+$"), timeout=15000)
        expect(host_page.locator(".table-wrap").first).to_be_visible()
        body = host_page.locator("#app").inner_text()
        assert "Guest Tester" in body
        assert "Correct answer" in body
        assert host_errors.errors == [], f"host errors: {host_errors.errors}"
        assert guest_errors.errors == [], f"guest errors: {guest_errors.errors}"
    finally:
        host_context.close()
        guest_context.close()
        late_context.close()


def test_a_private_instance_opens_on_the_wiki_listing(browser):
    """Demo mode owns the tour: a private instance starts on its content."""
    context, page, recorder = new_page(browser)
    try:
        meta = page.request.get(f"{BASE_URL}/api/v1/meta").json()
        if meta.get("demo_mode"):
            pytest.skip("a demo instance opens on its presentation page")
        page.goto(f"{BASE_URL}/", wait_until="networkidle")
        # The suite runs a private instance: no demo seed, no presentation page.
        # Its catalogue may be empty, and an empty grid stays hidden, so the
        # page itself is what proves the wiki listing is the entry point.
        expect(page.locator(".page-head h1")).to_be_visible()
        expect(page.locator("#wiki-q")).to_be_visible()
        expect(page.locator(".ld-hero")).to_have_count(0)
        expect(page.locator('#nav a[data-nav="about"]')).to_be_hidden()
        # It still answers when asked for by URL (the pro view is hidden, so both
        # heroes are in the DOM and only the first one is on screen).
        page.goto(f"{BASE_URL}/about", wait_until="networkidle")
        expect(page.locator(".ld-hero").first).to_be_visible()
    finally:
        context.close()


def test_security_headers_and_no_csp_violation(browser):
    context, page, recorder = new_page(browser)
    try:
        # The tour lives on /about: on a private instance the home page is the
        # wiki listing, the presentation page belongs to demo instances.
        response = page.goto(f"{BASE_URL}/about", wait_until="networkidle")
        headers = response.headers
        assert headers["x-frame-options"] == "DENY"
        assert headers["x-content-type-options"] == "nosniff"
        assert "default-src 'self'" in headers["content-security-policy"]
        # The default page is the tour; the catalogue lives on /quizzes.
        # Both tabs live in the DOM: scope the hero to the visible one.
        expect(page.locator('[data-view="discover"] .ld-hero')).to_be_visible()
        assert not any("Content Security Policy" in error for error in recorder.errors), recorder.errors
    finally:
        context.close()


def test_language_switch_and_theme_toggle(browser):
    context, page, recorder = new_page(browser, force_language=False)
    try:
        page.goto(f"{BASE_URL}/quizzes", wait_until="networkidle")
        hero = page.locator(".hero").first
        english = hero.inner_text()

        # The picker is a flag menu, not a plain-text select.
        button = page.locator("#language-button")
        assert page.locator("#language-select").count() == 0
        assert button.locator("svg.flag").count() == 1

        button.click()
        menu = page.locator("#language-menu")
        expect(menu).to_be_visible()
        options = page.locator("#language-menu .lang-option")
        # The count comes from the instance, so adding a language does not need
        # a test edit and a half-translated menu is what fails instead.
        meta = page.request.get(f"{BASE_URL}/api/v1/meta").json()
        expected = len(meta["languages"])
        assert options.count() == expected
        assert any("Русский" in (option.inner_text() or "") for option in options.all())
        assert any("العربية" in (option.inner_text() or "") for option in options.all())
        assert page.locator("#language-menu .lang-option svg.flag").count() == expected

        # Every option carries its own flag, so the language is recognisable
        # before the label is read.
        assert options.nth(0).locator("svg.flag").count() == 1

        page.click('#language-menu .lang-option[data-language="fr"]')
        expect(page.locator(".hero").first).not_to_have_text(english, timeout=10000)
        expect(page).to_have_url(re.compile(r".*/quizzes$"))
        expect(menu).to_be_hidden()

        # The choice survives a reload, and the button shows the French flag.
        page.reload(wait_until="networkidle")
        french = page.locator(".hero").first.inner_text()
        assert french != english
        assert page.evaluate("() => localStorage.getItem('ol_language')") == "fr"
        expect(page.locator("#language-button-label")).to_have_text("Français")

        # Theme toggle flips the document attribute and persists.
        page.click("#theme-toggle")
        theme = page.evaluate("() => document.documentElement.dataset.theme")
        assert theme in ("light", "dark"), theme
        page.reload(wait_until="networkidle")
        assert page.evaluate("() => document.documentElement.dataset.theme") == theme

        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()

def test_swipe_deck_answers_with_a_drag(browser):
    """Swipe mode is a single card per statement: the gesture is the answer."""
    context, page, recorder = new_page(browser)
    try:
        email = f"swipe-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Swipe Tester")

        # Enter through the swipe route the format chooser links to.
        page.goto(f"{BASE_URL}/quizzes/new/swipe/manual", wait_until="networkidle")
        page.fill("#quiz-title", "Swipe deck test")
        page.fill("#quiz-description", "One statement per card.")
        page.locator(".rte").first.click()
        page.keyboard.type("The card is dragged to answer.")
        page.click("#save-quiz")
        expect(page.locator(".toast.success").first).to_be_visible(timeout=15000)
        expect(page).to_have_url(re.compile(r".*/quizzes/\d+/edit$"), timeout=15000)
        quiz_url = re.sub(r"/edit$", "", page.url)

        page.goto(quiz_url, wait_until="networkidle")
        page.click('button[data-act="solo"]')
        page.wait_for_selector("[data-swipe-card]", timeout=15000)

        # A single card carrying the statement, not a yes/no grid of two cards.
        assert page.locator("[data-swipe-card]").count() == 1
        assert page.locator(".swipe-card-text").inner_text().strip()
        assert page.locator('button[data-swipe-answer="yes"]').count() == 1
        assert page.locator(".options-grid").count() == 0

        card = page.locator("[data-swipe-card]")
        box = card.bounding_box()
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        for step in range(1, 10):
            page.mouse.move(start_x + step * 18, start_y - step * 2)
            page.wait_for_timeout(15)
        # Mid-drag the "yes" stamp is readable and the card is tilted.
        stamp_opacity = page.eval_on_selector(".swipe-stamp.yes", "el => getComputedStyle(el).opacity")
        assert float(stamp_opacity) > 0.3, f"stamp stayed hidden while dragging ({stamp_opacity})"
        assert "rotate" in page.eval_on_selector("[data-swipe-card]", "el => el.style.transform")
        page.mouse.move(start_x + 260, start_y - 12)
        page.mouse.up()

        # Releasing past the threshold answers without any extra click.
        expect(page.locator("#feedback")).to_contain_text(re.compile(r"correct", re.I), timeout=15000)
        expect(page.locator(".swipe-card.reveal-yes")).to_have_count(1, timeout=5000)
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()



def test_editor_autosaves_the_draft_across_a_reload(browser):
    """Closing the tab must not lose an unpublished working copy."""
    context, page, recorder = new_page(browser)
    try:
        email = f"autosave-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Autosave Tester")

        page.goto(f"{BASE_URL}/quizzes/new/qcm/manual", wait_until="networkidle")
        page.fill("#quiz-title", "Draft never lost")
        page.locator(".rte").first.click()
        page.keyboard.type("A question typed before the save button is pressed.")

        # The draft is written while typing, without pressing anything.
        expect(page).to_have_url(re.compile(r".*/quizzes/\d+/edit$"), timeout=15000)
        expect(page.locator("#save-flag")).to_have_attribute("data-state", "saved", timeout=15000)

        page.reload(wait_until="networkidle")
        assert page.input_value("#quiz-title") == "Draft never lost"
        assert "typed before the save button" in page.locator(".rte").first.inner_text()

        # The dashboard lists the draft instead of an empty account.
        page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
        expect(page.locator("#app")).to_contain_text("Draft never lost", timeout=15000)
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_story_editor_links_and_deletes_nodes_with_the_mouse(browser):
    context, page, recorder = new_page(browser)
    try:
        email = f"story-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Story Tester")

        page.goto(f"{BASE_URL}/adventures/new/manual", wait_until="networkidle")
        page.fill(".adv-title", "Story editor gestures")
        # Autosave gives the story a real address before anything is valid.
        expect(page).to_have_url(re.compile(r".*/adventures/\d+/edit$"), timeout=15000)

        initial_nodes = page.locator(".adv-node").count()
        page.click('[data-act="add-question"]')
        page.click('[data-act="add-question"]')
        expect(page.locator(".adv-node")).to_have_count(initial_nodes + 2, timeout=10000)

        # Each answer is a row with its own numbered port, like a switch block.
        first_node = page.locator(".adv-node").nth(0)
        answer_rows = first_node.locator(".adv-row").count()
        assert answer_rows >= 2
        assert first_node.locator(".adv-port").count() == answer_rows
        first_row = first_node.locator(".adv-row").first
        first_row_box = first_row.bounding_box()
        first_port_box = first_node.locator(".adv-port").first.bounding_box()
        # The port sits on the row it belongs to, within a couple of pixels.
        assert abs(
            (first_port_box["y"] + first_port_box["height"] / 2)
            - (first_row_box["y"] + first_row_box["height"] / 2)
        ) < 6

        # Drag a free output port onto another node: that creates the link.
        initial_edges = page.locator("path.adv-edge").count()
        port = page.locator(".adv-node").nth(0).locator(".adv-port").nth(1)
        target = page.locator(".adv-node").last
        port_box = port.bounding_box()
        target_box = target.bounding_box()
        page.mouse.move(port_box["x"] + port_box["width"] / 2, port_box["y"] + port_box["height"] / 2)
        page.mouse.down()
        page.mouse.move(target_box["x"] + target_box["width"] / 2, target_box["y"] + target_box["height"] / 2, steps=12)
        page.mouse.up()
        expect(page.locator("path.adv-edge")).to_have_count(initial_edges + 1, timeout=10000)

        # Right click gives a contextual menu; deleting removes the node.
        page.locator(".adv-node").nth(2).click(button="right")
        expect(page.locator(".adv-node-menu")).to_be_visible(timeout=5000)
        page.locator('.adv-node-menu [data-menu="delete"]').click()
        page.locator('#modal-root [data-action="confirm"]').click()
        expect(page.locator(".adv-node")).to_have_count(initial_nodes + 1, timeout=10000)
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_catalogue_pagination_shows_ten_rows_then_a_second_page(browser):
    """The home page never lists more than ten quizzes at once."""
    admin_email = os.environ.get("OL_TEST_ADMIN_EMAIL", "")
    admin_password = os.environ.get("OL_TEST_ADMIN_PASSWORD", "")
    if not (admin_email and admin_password):
        pytest.skip("OL_TEST_ADMIN_EMAIL / OL_TEST_ADMIN_PASSWORD are not set.")

    context, page, recorder = new_page(browser)
    created: list[int] = []
    try:
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.fill("#email", admin_email)
        page.fill("#password", admin_password)
        page.click("#login-form button[type=submit]")
        expect(page).to_have_url(re.compile(r".*/(dashboard)?$"), timeout=15000)

        csrf = next(cookie["value"] for cookie in context.cookies() if cookie["name"] == "ol_csrf")
        headers = {"X-CSRF-Token": csrf}
        payload = {
            "title": "",
            "description": "Pagination probe.",
            "mode": "qcm",
            "questions": [
                {
                    "text_html": "<p>Probe question?</p>",
                    "options": [
                        {"text": "Yes", "is_correct": True},
                        {"text": "No", "is_correct": False},
                    ],
                }
            ],
        }
        for index in range(11):
            payload["title"] = f"Pagination probe {index:02d}"
            response = context.request.post(f"{BASE_URL}/api/v1/quizzes", data=payload, headers=headers)
            assert response.ok, response.text()
            quiz_id = response.json()["id"]
            created.append(quiz_id)
            published = context.request.post(
                f"{BASE_URL}/api/v1/quizzes/{quiz_id}/publish", data={"note": ""}, headers=headers
            )
            assert published.ok, published.text()

        page.goto(f"{BASE_URL}/quizzes", wait_until="networkidle")
        expect(page.locator(".quiz-card")).to_have_count(10, timeout=15000)
        expect(page.locator("#catalog-pager")).to_be_visible()
        first_page_titles = page.locator(".quiz-card h3").all_inner_texts()

        page.locator("#catalog-pager a", has_text="2").first.click()
        expect(page).to_have_url(re.compile(r".*\?page=2$"), timeout=15000)
        expect(page.locator(".quiz-card").first).to_be_visible(timeout=15000)
        second_page_titles = page.locator(".quiz-card h3").all_inner_texts()
        # The second page is a different slice of the catalogue, capped at ten.
        assert second_page_titles and len(second_page_titles) <= 10
        assert second_page_titles[0] not in first_page_titles
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        for quiz_id in created:
            try:
                # DELETE needs the CSRF header, like every state-changing call.
                context.request.delete(f"{BASE_URL}/api/v1/quizzes/{quiz_id}", headers=headers)
            except Exception:  # noqa: BLE001 - best effort cleanup
                pass
        context.close()

def test_format_chooser_offers_four_cards_and_a_method_step_before_the_editor(browser):
    context, page, recorder = new_page(browser)
    try:
        email = f"chooser-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Chooser Tester")

        page.goto(f"{BASE_URL}/quizzes/new", wait_until="networkidle")
        cards = page.locator(".mode-card")
        expect(cards).to_have_count(4)
        expect(cards.nth(0)).to_contain_text("Multiple choice")
        expect(cards.nth(1)).to_contain_text("Swipe cards")
        expect(cards.nth(2)).to_contain_text("Poll")
        expect(cards.nth(3)).to_contain_text("Adventure")

        # The format is a separate decision from how to fill it: the second step
        # asks for a model draft or a blank form, and only then opens the editor.
        cards.nth(1).click()
        expect(page).to_have_url(re.compile(r".*/quizzes/new/swipe$"), timeout=15000)
        methods = page.locator(".mode-card")
        # Manual, plus an AI draft when the instance offers a provider: without
        # one the second card is not rendered at all, which is the whole point
        # of the ai-only rule.
        offered = 2 if page.locator('html[data-ai="on"]').count() else 1
        expect(methods).to_have_count(offered)
        expect(methods.nth(0)).to_contain_text("Manual")
        methods.nth(0).click()
        expect(page).to_have_url(re.compile(r".*/quizzes/new/swipe/manual$"), timeout=15000)
        expect(page.locator("#quiz-mode")).to_have_value("swipe")
        expect(page.locator(".question-editor .option-row")).to_have_count(2)
        expect(page.locator('.question-editor input[data-field="option-text"]')).to_have_count(0)

        # Saving swaps the chooser URL for the real draft address, so a reload
        # never forks a second draft, and the positional Yes/No answers pass the
        # server's swipe validation.
        page.fill("#quiz-title", "Chooser swipe probe")
        page.locator(".question-editor .rte").first.click()
        page.keyboard.type("The SOC is quiet at 3am.")
        page.click("#save-quiz")
        expect(page.locator(".toast.success").first).to_be_visible(timeout=15000)
        expect(page).to_have_url(re.compile(r".*/quizzes/\d+/edit$"), timeout=15000)
        swipe_id = int(re.search(r"/quizzes/(\d+)/edit$", page.url).group(1))

        # The created quiz really is a swipe deck.
        page.goto(f"{BASE_URL}/quizzes/{swipe_id}", wait_until="networkidle")
        page.locator('button[data-act="solo"]').first.click()
        expect(page.locator("[data-swipe-card]")).to_be_visible(timeout=15000)

        # Adventure hands over to the story editor.
        page.goto(f"{BASE_URL}/quizzes/new", wait_until="networkidle")
        page.locator(".mode-card").nth(3).click()
        expect(page).to_have_url(re.compile(r".*/adventures/new$"), timeout=15000)
        # A story is built by hand or drafted by the model, in that order: the
        # chooser has to offer both before the canvas opens.
        expect(page.locator('.mode-card[href="/adventures/new/manual"]')).to_be_visible(timeout=15000)
        page.locator('.mode-card[href="/adventures/new/manual"]').click()
        expect(page.locator(".adv-canvas, .adv-node").first).to_be_visible(timeout=15000)
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_host_plays_and_the_run_shows_in_history_and_stats(browser):
    """The host can answer their own live run, then find it in their history."""
    context, page, recorder = new_page(browser)
    try:
        email = f"playhost-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Host Player")
        quiz_id = create_quiz_through_editor(page, "Host plays too")

        # Hosting from the quiz page, enrolling as a player from the lobby.
        page.goto(f"{BASE_URL}/quizzes/{quiz_id}", wait_until="networkidle")
        page.locator('[data-act="live"]').click()
        expect(page).to_have_url(re.compile(r".*/host/[A-Z0-9]+$"), timeout=20000)

        join_form = page.locator("form[data-form='join-self']")
        expect(join_form).to_be_visible(timeout=15000)
        page.fill("#host-nickname", "Host Player")
        join_form.locator("button[type=submit]").click()

        # The lobby now lists the host as a participant of their own session.
        expect(page.locator(".participant-chip").first).to_contain_text("Host Player", timeout=15000)
        expect(page.locator(".feedback.ok").first).to_be_visible(timeout=15000)

        page.locator('[data-act="start"]').click()
        expect(page.locator(".question-card")).to_be_visible(timeout=15000)

        def answer_as_host():
            # The grid is the answer surface when the host plays: the panel below
            # only carries the submit button, so the question is not shown twice.
            picks = page.locator(".options-grid [data-pick]")
            expect(picks.first).to_be_visible(timeout=20000)
            picks.first.click()
            submit = page.locator('[data-act="send-answer"]')
            expect(submit).to_be_enabled(timeout=10000)
            submit.click()
            expect(page.locator(".toast.success").first).to_be_visible(timeout=15000)

        answer_as_host()

        # The single player in the room has answered: the server reveals.
        expect(page.locator(".option-btn.correct").first).to_be_visible(timeout=20000)
        page.locator('[data-act="next"]').click()
        expect(page.locator(".question-card")).to_be_visible(timeout=15000)
        answer_as_host()
        expect(page.locator(".option-btn.correct").first).to_be_visible(timeout=20000)

        page.locator('[data-act="finish"]').click()
        expect(page).to_have_url(re.compile(r".*/results/[A-Z0-9]+$"), timeout=20000)

        # The participation is recorded on the profile, with a rank. The account
        # page opens on the profile section since lot 13: history is a tab.
        page.goto(f"{BASE_URL}/account", wait_until="networkidle")
        page.click('[data-section="history"]')
        row = page.locator(".history-row").first
        expect(row).to_be_visible(timeout=15000)
        expect(row).to_contain_text("Host plays too")
        expect(row.locator(".pill").first).to_be_visible()
        assert re.search(r"#\d", row.inner_text()), row.inner_text()

        # "Host and play" enrols the host straight away: no second form.
        page.goto(f"{BASE_URL}/quizzes/{quiz_id}", wait_until="networkidle")
        page.locator('[data-act="live-play"]').click()
        expect(page).to_have_url(re.compile(r".*/host/[A-Z0-9]+$"), timeout=20000)
        expect(page.locator(".feedback.ok").first).to_be_visible(timeout=20000)
        assert page.locator("form[data-form='join-self']").count() == 0
        page.locator('[data-act="cancel"]').click()
        page.wait_for_timeout(600)

        # And the creator statistics aggregate the run per question.
        page.goto(f"{BASE_URL}/quizzes/{quiz_id}", wait_until="networkidle")
        page.locator('[data-tab="stats"]').click()
        expect(page.locator(".stat-card").first).to_be_visible(timeout=15000)
        assert page.locator(".bar-row").count() >= 2
        stats_text = page.locator(".tab-panel").last.inner_text()
        assert "%" in stats_text

        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_catalogue_card_hosts_a_game_directly(browser):
    """A quiz card in the catalogue starts a live session without opening the quiz."""
    context, page, recorder = new_page(browser)
    try:
        register_through_ui(page, f"tile-{uuid.uuid4().hex[:8]}@example.com", "Tile Host")
        page.goto(f"{BASE_URL}/quizzes", wait_until="networkidle")

        host_buttons = page.locator(".quiz-card-actions [data-host]")
        if host_buttons.count() == 0:
            page.goto(f"{BASE_URL}/quizzes?page=2", wait_until="networkidle")
        host_buttons = page.locator(".quiz-card-actions [data-host]")
        assert host_buttons.count() >= 1, "no catalogue card exposes a host button"

        host_buttons.first.click()
        expect(page).to_have_url(re.compile(r".*/host/[A-Z0-9]+$"), timeout=20000)
        expect(page.locator(".pin-display")).to_be_visible(timeout=15000)

        # Leave no live session behind for the next run.
        page.locator('[data-act="cancel"]').click()
        page.wait_for_timeout(800)
    finally:
        context.close()


def test_api_reference_page_lists_every_operation(browser):
    context, page, recorder = new_page(browser)
    try:
        # Swagger cannot run under our CSP, so /docs renders the spec itself.
        page.goto(f"{BASE_URL}/docs", wait_until="networkidle")
        operations = page.locator(".docs-op")
        expect(operations.first).to_be_visible(timeout=15000)
        assert operations.count() > 20
        assert page.locator(".docs-group").count() > 3
        assert page.locator(".docs-method").count() == operations.count()

        # The filter narrows the list instead of reloading the page.
        page.fill("#docs-filter", "adventure")
        page.wait_for_timeout(300)
        visible = page.locator(".docs-op:visible")
        assert 0 < visible.count() < operations.count()
        assert all("adventure" in text for text in page.locator(".docs-op:visible .docs-path").all_inner_texts())

        # The old URL still lands on the reference.
        page.goto(f"{BASE_URL}/api/docs", wait_until="networkidle")
        expect(page).to_have_url(re.compile(r".*/docs$"))
        expect(page.locator(".docs-op").first).to_be_visible(timeout=15000)
        assert not recorder.errors
    finally:
        context.close()


def test_quiz_detail_keeps_management_and_play_actions_apart(browser):
    context, page, recorder = new_page(browser)
    try:
        email = f"detail-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Detail Tester")
        quiz_id = create_quiz_through_editor(page, "Detail layout")

        page.goto(f"{BASE_URL}/quizzes/{quiz_id}", wait_until="networkidle")
        aside = page.locator(".detail-aside")
        expect(aside).to_be_visible()

        # Editing belongs to the owner card, not to the row of play buttons.
        owner_card = aside.locator(".card").last
        edit_link = owner_card.locator('a[href$="/edit"]')
        assert edit_link.count() == 1
        play_card = page.locator("[data-act='live']").first
        assert page.locator("[data-act='live'] a[href$='/edit']").count() == 0
        assert play_card.count() == 1

        # "Modifier" and the button below it ("Dépublier") must not touch.
        edit_box = edit_link.bounding_box()
        below = owner_card.locator(".stack-sm .btn").first.bounding_box()
        assert below["y"] - (edit_box["y"] + edit_box["height"]) >= 4
        assert not recorder.errors
    finally:
        context.close()


def test_a_poll_is_published_privately_and_answered_without_any_score(browser):
    """A poll has no answer key: publication, play and feedback all stay scoreless."""
    context, page, recorder = new_page(browser)
    try:
        email = f"poll-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Poll Tester")

        page.goto(f"{BASE_URL}/quizzes/new", wait_until="networkidle")
        page.locator(".mode-card").nth(2).click()
        expect(page).to_have_url(re.compile(r".*/quizzes/new/poll$"), timeout=15000)
        page.locator(".mode-card").nth(0).click()
        expect(page).to_have_url(re.compile(r".*/quizzes/new/poll/manual$"), timeout=15000)
        expect(page.locator("#quiz-mode")).to_have_value("poll")

        # The author picks who may read the answers, and no row is marked correct.
        expect(page.locator("#results-visibility-field")).to_be_visible()
        page.select_option("#quiz-results", "public")
        expect(page.locator(".question-editor .option-row.correct")).to_have_count(0)
        assert page.locator(".question-editor .rte").count() > 0

        page.fill("#quiz-title", "Which channel do you prefer?")
        page.fill("#quiz-description", "One question, no wrong answer.")
        page.locator(".question-editor .rte").first.click()
        page.keyboard.type("Which channel do you use most?")
        options = page.locator('.question-editor input[data-field="option-text"]')
        options.nth(0).fill("Team chat")
        options.nth(1).fill("Email")
        page.click("#save-quiz")
        expect(page.locator(".toast.success").first).to_be_visible(timeout=15000)
        expect(page).to_have_url(re.compile(r".*/quizzes/\d+/edit$"), timeout=15000)
        quiz_id = int(re.search(r"/quizzes/(\d+)/edit$", page.url).group(1))

        # Publication: the second tab offers a private and a public button.
        page.click('[data-tab="publish"]')
        private_button = page.locator('[data-act="publish-private"]')
        expect(private_button).to_be_visible(timeout=10000)
        private_button.click()
        expect(page.locator(".toast.success").first).to_be_visible(timeout=15000)

        # Private means out of the catalogue but playable by link.
        listing = page.request.get(f"{BASE_URL}/api/v1/quizzes?scope=public")
        titles = [item["title"] for item in listing.json()]
        assert "Which channel do you prefer?" not in titles

        page.goto(f"{BASE_URL}/quizzes/{quiz_id}", wait_until="networkidle")
        page.locator('button[data-act="solo"]').first.click()
        page.wait_for_url(re.compile(r".*/play/.*"), timeout=20000)
        page.locator(".option-btn").first.click()
        page.locator('[data-act="submit"]').click()
        expect(page.locator(".feedback.ok")).to_be_visible(timeout=15000)
        # Nothing tells the respondent whether they were right: there is no right.
        expect(page.locator(".option.correct, .option.incorrect")).to_have_count(0)
        assert not recorder.errors, recorder.errors
    finally:
        context.close()


def test_an_untimed_quiz_never_opens_as_expired(browser):
    """A quiz with no clock must not look like it ran out of time on load.

    `remainingMs()` answers 0 when there is no deadline, and the play screen used
    to read that as "expired": the time-up banner was up and the submit button
    disabled on the very first question.
    """
    context, page, recorder = new_page(browser)
    try:
        email = f"untimed-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Untimed Tester")

        page.goto(f"{BASE_URL}/quizzes/new/qcm/manual", wait_until="networkidle")
        page.fill("#quiz-title", "No clock at all")
        page.fill("#quiz-description", "Played without any timer.")
        page.locator(".rte").first.click()
        page.keyboard.type("Which answer needs no clock?")
        options = page.locator('input[data-field="option-text"]')
        options.nth(0).fill("This one")
        options.nth(1).fill("Neither")
        page.locator("#quiz-timer").select_option("none")

        # The per-question clock disappears from the question cards: leaving it
        # visible in a quiz without a timer read as "the timer is still on".
        expect(page.locator("[data-timer-field]").first).to_be_hidden(timeout=5000)

        page.click("#save-quiz")
        expect(page.locator(".toast.success").first).to_be_visible(timeout=15000)
        expect(page).to_have_url(re.compile(r".*/quizzes/\d+/edit$"), timeout=15000)
        quiz_id = int(re.search(r"/quizzes/(\d+)/edit$", page.url).group(1))

        page.goto(f"{BASE_URL}/quizzes/{quiz_id}", wait_until="networkidle")
        page.locator('[data-act="solo"], [data-act="play-solo"], a[href$="/play"]').first.click()
        page.wait_for_timeout(2200)
        expect(page.locator(".timer-off")).to_be_visible(timeout=15000)
        expect(page.locator("#time-notice")).to_be_hidden(timeout=5000)
        expect(page.locator('[data-act="submit"]')).to_be_enabled(timeout=5000)
        # And the answer actually goes through: the server used to reject it with
        # "Time is up for this question." because it read the missing deadline as
        # an expired one.
        page.locator(".option-btn").first.click()
        page.locator('[data-act="submit"]').click()
        expect(page.locator(".feedback")).to_be_visible(timeout=15000)
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_the_story_canvas_pans_with_the_mouse(browser):
    """Grabbing empty space moves the graph; the cursor promised it already.

    The listener sat on the canvas element, whose painted box is smaller than the
    viewport once scaled, so a drag started in the margin hit nothing.
    """
    context, page, recorder = new_page(browser)
    try:
        email = f"pan-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Pan Tester")
        page.goto(f"{BASE_URL}/adventures/new/manual", wait_until="networkidle")
        page.fill(".adv-title", "Panning story")
        expect(page).to_have_url(re.compile(r".*/adventures/\d+/edit$"), timeout=15000)
        for _ in range(3):
            page.click('[data-act="add-question"]')
        page.wait_for_timeout(900)

        canvas = page.locator("[data-canvas]").first
        before = canvas.evaluate("(el) => el.style.transform")
        view = page.locator(".adv-canvas-scroll").first.bounding_box()
        start_x, start_y = view["x"] + view["width"] - 40, view["y"] + view["height"] - 40
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(start_x - 120, start_y - 60, steps=12)
        page.mouse.up()
        page.wait_for_timeout(400)
        after = canvas.evaluate("(el) => el.style.transform")
        assert after != before, f"the canvas did not pan (transform stayed {before})"
        assert "translate" in after
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_a_success_toast_stays_readable_in_both_themes(browser):
    """Toast colours must not collapse into each other once the theme flips."""
    context, page, recorder = new_page(browser)
    try:
        email = f"toast-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Toast Tester")

        for theme in ("dark", "light"):
            page.evaluate("(value) => document.documentElement.setAttribute('data-theme', value)", theme)
            page.evaluate(
                "() => { const region = document.getElementById('toast-region');"
                " const node = document.createElement('div'); node.className = 'toast success';"
                " node.id = 'contrast-probe'; node.textContent = 'Quiz saved and published';"
                " region.appendChild(node); }"
            )
            ratio = page.evaluate(
                "() => { const parse = (value) => value.match(/[\\d.]+/g).slice(0, 3).map(Number);"
                " const luminance = (rgb) => { const [r, g, b] = rgb.map((channel) => {"
                "   const v = channel / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });"
                "   return 0.2126 * r + 0.7152 * g + 0.0722 * b; };"
                " const node = document.getElementById('contrast-probe');"
                " const style = getComputedStyle(node);"
                " const fg = luminance(parse(style.color));"
                " const bg = luminance(parse(style.backgroundColor));"
                " return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05); }"
            )
            assert ratio >= 4.5, f"{theme} theme: toast contrast is only {ratio:.2f}:1"
            page.evaluate("() => document.getElementById('contrast-probe').remove()")
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_the_dashboard_row_offers_a_view_button_and_icon_actions(browser):
    """The row links to the quiz from its title *and* from an explicit button.

    Clicking a title was not obvious enough, so the actions cell gained a "view"
    button; every action is an icon with an accessible name instead of a word.
    """
    context, page, recorder = new_page(browser)
    try:
        email = f"dash-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Dashboard Tester")
        quiz_id = create_quiz_through_editor(page, "Dashboard actions")

        page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
        row = page.locator(f'tr[data-quiz="{quiz_id}"]')
        expect(row).to_be_visible(timeout=15000)

        view = row.locator(f'a[href="/quizzes/{quiz_id}"].btn-icon')
        expect(view).to_be_visible()
        expect(view).to_have_attribute("aria-label", re.compile("View|Voir"))

        # Every action in the cell is an icon button: no visible text, real label.
        actions = row.locator("td .row-wrap > *")
        assert actions.count() == 5
        for index in range(actions.count()):
            item = actions.nth(index)
            assert item.locator("svg").count() == 1, item.inner_html()
            assert (item.inner_text() or "").strip() == ""
            assert (item.get_attribute("aria-label") or ""), "icon buttons need a label"
            assert (item.get_attribute("title") or "")

        view.click()
        expect(page).to_have_url(re.compile(rf".*/quizzes/{quiz_id}$"), timeout=15000)
        expect(page.locator("h1")).to_contain_text("Dashboard actions", timeout=15000)
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_the_wiki_diff_is_side_by_side_and_a_markdown_file_imports(browser):
    """Two panes, green additions, red removals — and a .md file becomes a page."""
    context, page, recorder = new_page(browser, viewport=(1440, 980))
    try:
        email = f"wiki-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Wiki Tester")

        # --- create a wiki through its form -------------------------------
        page.goto(f"{BASE_URL}/wiki/new", wait_until="networkidle")
        page.fill('#wiki-create input[name="title"]', "Manuel de test")
        page.fill('#wiki-create textarea[name="description"]', "Wiki cree par le test de bout en bout.")
        page.click("#wiki-create button[type=submit]")
        # A new wiki opens on the editor of the home page it was born with.
        expect(page).to_have_url(re.compile(r".*/wiki/\d+/edit/\d+$"), timeout=15000)

        # --- first version ------------------------------------------------
        # The editor opens in WYSIWYG; markdown is one click away and is what a
        # person pasting a document actually wants.
        page.click('[data-mode="markdown"]')
        page.fill("#wiki-page-title", "Ports")
        page.locator("#wiki-md").fill(
            "# Ports\n\nLe resolver ecoute sur le port 53.\nLa zone est signee.\n"
        )
        page.click("#wiki-save")
        expect(page).to_have_url(re.compile(r".*/wiki/\d+/p/ports(\?.*)?$"), timeout=15000)

        # --- second version, through the editor ---------------------------
        # The article's own "Edit" link, not the sidebar's "New page" button.
        page.locator('a[href*="/edit/"]').first.click()
        expect(page).to_have_url(re.compile(r".*/wiki/\d+/edit/\d+$"), timeout=15000)
        page.click('[data-mode="markdown"]')
        page.locator("#wiki-md").fill(
            "# Ports\n\nLe resolver ecoute sur le port 5353.\nLa zone est signee.\n"
            "Une ligne ajoutee.\n"
        )
        page.click("#wiki-save")
        expect(page).to_have_url(re.compile(r".*/wiki/\d+/p/ports(\?.*)?$"), timeout=15000)

        # --- compare v1 and v2 -------------------------------------------
        page.get_by_role("link", name=re.compile("History")).first.click()
        expect(page.locator("[data-diff]").first).to_be_visible(timeout=15000)
        page.locator("[data-diff]").first.click()
        panes = page.locator(".diff-panes")
        expect(panes).to_be_visible(timeout=15000)

        assert page.locator(".diff-table thead th").count() == 2, "two columns expected"
        assert page.locator(".diff-cell.is-add").count() >= 1, "the added line must be green"
        assert page.locator(".diff-cell.is-del").count() >= 1, "the removed line must be red"
        # The changed pair faces its replacement, with the changed words marked.
        change_rows = page.locator("tr.diff-change")
        assert change_rows.count() >= 1
        assert page.locator(".diff-cell.is-del .diff-seg-chg").count() >= 1
        assert page.locator(".diff-cell.is-add .diff-seg-chg").count() >= 1

        # --- import a markdown page --------------------------------------
        page.goto(page.url.split("/history")[0], wait_until="networkidle")
        page.set_input_files(
            "#wiki-import-md",
            {
                "name": "journal.md",
                "mimeType": "text/markdown",
                "buffer": (
                    b"---\ntitle: Journal de bord\ntags: [incident]\n---\n\n"
                    b"# Journal de bord\n\nLa zone a cesse de repondre a 9 h.\n"
                ),
            },
        )
        expect(page).to_have_url(re.compile(r".*/wiki/\d+/p/journal-de-bord(\?.*)?$"), timeout=20000)
        expect(page.locator("article h1, .wiki-article h1")).to_contain_text("Journal de bord")

        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_two_windows_edit_the_same_page_and_the_menu_is_a_tree(browser):
    """Presence, remote carets, live text, then the menu tree and references."""
    context, page, recorder = new_page(browser, viewport=(1440, 980))
    second_context = None
    try:
        email = f"wiki-live-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Alice Martin")

        # --- a wiki with one page holding a link and a source -------------
        page.goto(f"{BASE_URL}/wiki/new", wait_until="networkidle")
        page.fill('#wiki-create input[name="title"]', "Wiki collaboratif")
        page.fill('#wiki-create textarea[name="description"]', "Co-edition de bout en bout.")
        page.click("#wiki-create button[type=submit]")
        expect(page).to_have_url(re.compile(r".*/wiki/\d+/edit/\d+$"), timeout=15000)
        wiki_id = int(re.search(r"/wiki/(\d+)/edit", page.url).group(1))

        page.click('[data-mode="markdown"]')
        page.fill("#wiki-page-title", "Accueil")
        page.locator("#wiki-md").fill(
            "# Accueil\n\nLe resolver ecoute sur le port 53.\n\n"
            "Voir [[dns]] et https://www.rfc-editor.org/rfc/rfc1035\n"
        )
        assert "[[dns]]" in page.locator("#wiki-md").input_value(), "the textarea keeps the wikilink"
        page.click("#wiki-save")
        expect(page).to_have_url(re.compile(r".*/p/accueil(\?.*)?$"), timeout=15000)
        stored = page.request.get(f"{BASE_URL}/api/v1/wiki/{wiki_id}").json()
        home_page = [item for item in stored["pages"] if item["slug"] == "accueil"][0]
        detail = page.request.get(
            f"{BASE_URL}/api/v1/wiki/pages/{home_page['id']}"
        ).json()
        assert "[[dns]]" in detail["content_md"], detail["content_md"]

        # --- a second window, same account, on the same page --------------
        second_context, second, second_recorder = new_page(browser, viewport=(1280, 900))
        second.goto(f"{BASE_URL}/login", wait_until="networkidle")
        second.fill("#email", email)
        second.fill("#password", PASSWORD)
        second.click("#login-form button[type=submit]")
        expect(second).to_have_url(re.compile(r".*/dashboard$"), timeout=15000)

        page.locator('a[href*="/edit/"]').first.click()
        expect(page).to_have_url(re.compile(r".*/wiki/\d+/edit/\d+$"), timeout=15000)
        editor_url = page.url
        page.click('[data-mode="markdown"]')

        second.goto(editor_url, wait_until="networkidle")
        second.click('[data-mode="markdown"]')

        # Each window sees the other one in the presence bar.
        expect(page.locator(".ed-person").first).to_be_visible(timeout=20000)
        expect(second.locator(".ed-person").first).to_be_visible(timeout=20000)

        # Typing in the second window reaches the first one, without saving.
        second.locator("#wiki-md").click()
        second.keyboard.press("Control+End")
        second.keyboard.type(" Ligne partagee en direct.")
        expect(page.locator("#wiki-md")).to_have_value(
            re.compile("Ligne partagee en direct"), timeout=20000
        )
        # ... and the other window's caret is drawn on the page.
        expect(page.locator(".ed-caret").first).to_be_visible(timeout=20000)
        second_context.close()
        second_context = None

        # --- images: the drop zone opens, the picker inserts at the caret --
        page.evaluate(
            """() => {
              const box = document.querySelector('.ed-surface');
              const transfer = new DataTransfer();
              transfer.items.add(new File([new Uint8Array([137, 80, 78, 71])], 'plan.png',
                                          { type: 'image/png' }));
              box.dispatchEvent(new DragEvent('dragenter', { bubbles: true, dataTransfer: transfer }));
            }"""
        )
        expect(page.locator("#wiki-drop")).to_be_visible(timeout=5000)

        page.set_input_files(
            "#wiki-image-input",
            {"name": "plan.png", "mimeType": "image/png", "buffer": _one_pixel_png()},
        )
        expect(page.locator("#wiki-md")).to_have_value(re.compile(r"!\[plan\]\(/media/"), timeout=20000)

        # --- the menu becomes a tree ---------------------------------------
        page.goto(f"{BASE_URL}/wiki/{wiki_id}/edit", wait_until="networkidle")
        page.click('[data-mode="markdown"]')
        page.fill("#wiki-page-title", "DNS")
        page.locator("#wiki-md").fill("# DNS\n\nLe protocole de resolution de noms.\n")
        page.click("#wiki-save")
        expect(page).to_have_url(re.compile(r".*/p/dns(\?.*)?$"), timeout=15000)

        page.goto(f"{BASE_URL}/wiki/{wiki_id}/structure", wait_until="networkidle")
        rows = page.locator(".tree-item")
        expect(rows.first).to_be_visible(timeout=15000)
        assert rows.count() >= 2, "the wiki has two pages"
        dns_row = page.locator('.tree-item:has-text("DNS")').first
        dns_row.locator('[data-move="indent"]').click()
        page.click("#tree-save")
        expect(page.locator(".toast.success").first).to_be_visible(timeout=15000)

        # The reader shows the hierarchy, and the page it displays stands out.
        page.goto(f"{BASE_URL}/wiki/{wiki_id}", wait_until="networkidle")
        nav = page.locator("#wiki-nav")
        expect(nav.locator(".wiki-nav-item.is-child")).to_have_count(1, timeout=15000)
        active = nav.locator(".wiki-nav-item.is-active")
        expect(active).to_have_count(1)
        assert active.locator("a").get_attribute("aria-current") == "page"

        # --- references: sources, internal links, broken links -------------
        index = page.request.get(f"{BASE_URL}/api/v1/wiki/{wiki_id}/references")
        assert index.ok, index.text()
        payload = index.json()
        assert [item["title"] for item in payload["internal"]] == ["DNS"], payload
        assert payload["stats"]["sources"] >= 1, payload

        page.goto(f"{BASE_URL}/wiki/{wiki_id}/references", wait_until="networkidle")
        expect(page.locator(".ref-host-name").first).to_contain_text("rfc-editor.org")
        expect(page.locator(".ref-internal")).to_contain_text("DNS")
        assert page.locator(".ref-stats .pill").count() >= 4

        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
        assert second_recorder.errors == [], f"second window errors: {second_recorder.errors}"
    finally:
        if second_context is not None:
            second_context.close()
        context.close()


def test_the_editor_offers_templates_reviews_a_link_picker_and_deletion(browser):
    """Lot 6: templates, visible AI reviews, search-based linking, deletion."""
    context, page, recorder = new_page(browser, viewport=(1440, 980))
    try:
        email = f"wiki-lot6-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Camille Durand")

        # --- a wiki with a first page ------------------------------------
        page.goto(f"{BASE_URL}/wiki/new", wait_until="networkidle")
        page.fill('#wiki-create input[name="title"]', "Wiki des procedures")
        page.fill('#wiki-create textarea[name="description"]', "Lot 6, bout en bout.")
        page.click("#wiki-create button[type=submit]")
        expect(page).to_have_url(re.compile(r".*/wiki/\d+/edit/\d+$"), timeout=15000)
        wiki_id = int(re.search(r"/wiki/(\d+)/edit", page.url).group(1))

        page.click('[data-mode="markdown"]')
        page.fill("#wiki-page-title", "Accueil")
        page.locator("#wiki-md").fill("# Accueil\n\nLe resolveur ecoute sur le port 53.\n")
        page.click("#wiki-save")
        expect(page).to_have_url(re.compile(r".*/p/accueil(\?.*)?$"), timeout=15000)

        # --- the reader can delete the page it is showing ----------------
        delete_page = page.locator("#wiki-delete-page")
        expect(delete_page).to_be_visible()

        # --- templates are written in their own screen -------------------
        page.goto(f"{BASE_URL}/wiki/{wiki_id}/templates", wait_until="networkidle")
        expect(page.locator("h1")).to_contain_text("Page templates")
        page.click("#template-new")
        page.fill("#template-name", "Fiche de procedure")
        page.fill("#template-description", "Squelette pour une procedure interne")
        page.fill("#template-keywords", "procedure, interne")
        page.locator("#template-content").fill(
            "# Titre\n\n## Contexte\n\n## Etapes\n\n1. Premiere etape\n"
        )
        page.click("#template-save")
        expect(page.locator(".wiki-template h2").first).to_contain_text("Fiche de procedure")

        # --- a new page starts from that template ------------------------
        page.goto(f"{BASE_URL}/wiki/{wiki_id}/edit", wait_until="networkidle")
        expect(page.locator("#wiki-template-bar")).to_be_visible()
        page.select_option("#wiki-template-select", label="Fiche de procedure")
        assert "## Etapes" in page.locator("#wiki-md").input_value()

        # --- AI reviews sit at the top of the editing area ---------------
        # They only exist on an instance that offers an AI provider: a public
        # continuous-integration run has no key, so the buttons are rendered
        # disabled and the scenario says so instead of reporting a frontend bug.
        reviews = page.locator(".ed-reviews button[data-review]")
        assert reviews.count() == 3
        if page.locator('html[data-ai="off"]').count():
            pytest.skip("The instance under test declares AI off: no review to click.")
        for index in range(3):
            expect(reviews.nth(index)).to_be_visible()

        # --- linking a page searches instead of asking for a title -------
        page.click('[data-mode="markdown"]')
        page.locator("#wiki-md").click()
        page.click('.ed-tools [data-cmd="wikilink"]')
        expect(page.locator("#wiki-link-picker")).to_be_visible()
        page.fill("#wiki-link-query", "Accueil")
        hit = page.locator(".ed-link-hit").first
        expect(hit).to_be_visible(timeout=10000)
        expect(hit).to_contain_text("Accueil")
        hit.click()
        expect(page.locator("#wiki-link-picker")).to_be_hidden()
        assert "[[accueil" in page.locator("#wiki-md").input_value()

        # --- an image can be sized from the rich view --------------------
        # A 2x2 pixel target is too small for a real click: use a picture
        # large enough that the click lands on the image itself.
        page.set_input_files(
            "#wiki-image-input",
            {"name": "schema.png", "mimeType": "image/png", "buffer": _picture_png(160, 100)},
        )
        expect(page.locator("#wiki-md")).to_have_value(
            re.compile(r"!\[schema\]\(/media/"), timeout=20000
        )
        page.click('[data-mode="wysiwyg"]')
        page.locator("#wiki-wysiwyg img").first.click()
        expect(page.locator("#wiki-img-tools")).to_be_visible()
        page.click('#wiki-img-tools [data-width="50%"]')
        page.click('[data-mode="markdown"]')
        assert "{width=50%}" in page.locator("#wiki-md").input_value()

        # --- and the page can be deleted from the reader -----------------
        page.goto(f"{BASE_URL}/wiki/{wiki_id}/p/accueil", wait_until="networkidle")
        page.click("#wiki-delete-page")
        page.locator('#modal-root [data-action="confirm"]').click()
        expect(page).to_have_url(re.compile(r".*/wiki/\d+(\?.*)?$"), timeout=15000)
        remaining = page.request.get(f"{BASE_URL}/api/v1/wiki/{wiki_id}").json()
        assert "accueil" not in [item["slug"] for item in remaining["pages"]]

        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_rich_formatting_keeps_the_selected_text_and_the_landing_is_home(browser):
    """Lot 7: the default page is the tour, and the rich toolbar keeps its text."""
    context, page, recorder = new_page(browser, viewport=(1440, 980))
    try:
        # --- the tour keeps its scenes, and the wiki comes first in a header
        # that hides the presentation page on a private instance --
        page.goto(f"{BASE_URL}/about", wait_until="networkidle")
        expect(page.locator('[data-view="discover"] .ld-hero h1')).to_be_visible()
        # Seven chapters: the accessibility one joined the six product scenes.
        expect(page.locator(".landing .ld-scene")).to_have_count(7)
        expect(page.locator(".ld-scene-ai .ld-ai-badge")).to_be_visible()
        first_nav = page.locator("#nav a:visible").first
        meta = page.request.get(f"{BASE_URL}/api/v1/meta").json()
        # A demo instance keeps its presentation page in the header; a private
        # one starts on the wiki listing, which is then the first link.
        expect(first_nav).to_have_attribute("href", "/about" if meta.get("demo_mode") else "/wiki")

        # --- the catalogue has a public tab and, once signed in, a mine tab -
        page.goto(f"{BASE_URL}/quizzes", wait_until="networkidle")
        expect(page.locator(".tabs a.tab")).to_have_count(1)

        email = f"wiki-lot7-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Nadia Roux")
        page.goto(f"{BASE_URL}/quizzes", wait_until="networkidle")
        expect(page.locator(".tabs a.tab")).to_have_count(2)
        page.locator('.tabs a.tab[href*="tab=mine"]').click()
        expect(page.locator(".tabs a.tab.is-active")).to_contain_text("My questionnaires")

        # --- a wiki to format -----------------------------------------------
        page.goto(f"{BASE_URL}/wiki/new", wait_until="networkidle")
        page.fill('#wiki-create input[name="title"]', "Wiki du formatage")
        page.fill('#wiki-create textarea[name="description"]', "Lot 7.")
        page.click("#wiki-create button[type=submit]")
        expect(page).to_have_url(re.compile(r".*/wiki/\d+/edit/\d+$"), timeout=15000)
        wiki_id = int(re.search(r"/wiki/(\d+)/edit", page.url).group(1))

        page.click('[data-mode="markdown"]')
        page.fill("#wiki-page-title", "Accueil")
        page.locator("#wiki-md").fill("# Accueil\n\nLe resolveur ecoute sur le port 53.\n")
        page.click("#wiki-save")
        expect(page).to_have_url(re.compile(r".*/p/accueil(\?.*)?$"), timeout=15000)

        pages = page.request.get(f"{BASE_URL}/api/v1/wiki/{wiki_id}").json()["pages"]
        page_id = next(item["id"] for item in pages if item["slug"] == "accueil")
        page.goto(f"{BASE_URL}/wiki/{wiki_id}/edit/{page_id}", wait_until="networkidle")
        expect(page.locator("#wiki-wysiwyg")).to_be_visible()

        # --- bold keeps the words it decorates ------------------------------
        def select_paragraph():
            page.evaluate(
                """() => {
                    const box = document.querySelector('#wiki-wysiwyg');
                    box.focus();
                    const paragraph = [...box.querySelectorAll('p')].find((node) =>
                        node.textContent.includes('resolveur'));
                    const range = document.createRange();
                    range.selectNodeContents(paragraph);
                    const selection = window.getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                }"""
            )

        select_paragraph()
        page.click('.ed-tools [data-cmd="bold"]')
        assert page.locator("#wiki-wysiwyg").inner_text().strip() != ""
        expect(page.locator("#wiki-wysiwyg strong").first).to_contain_text("resolveur")
        page.click('[data-mode="markdown"]')
        assert "**Le resolveur ecoute sur le port 53.**" in page.locator("#wiki-md").input_value()

        # --- underline, heading level and colour ----------------------------
        page.click('[data-mode="wysiwyg"]')
        select_paragraph()
        page.click('.ed-tools [data-cmd="underline"]')
        expect(page.locator("#wiki-wysiwyg u").first).to_contain_text("resolveur")

        select_paragraph()
        page.select_option("#wiki-block", "h2")
        expect(page.locator("#wiki-wysiwyg h2").first).to_contain_text("resolveur")

        page.evaluate(
            """() => {
                const box = document.querySelector('#wiki-wysiwyg');
                const heading = box.querySelector('h2');
                const range = document.createRange();
                range.selectNodeContents(heading);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            }"""
        )
        page.click("[data-color-menu]")
        expect(page.locator("#wiki-color-menu")).to_be_visible()
        page.click('#wiki-color-menu [data-color="red"]')
        expect(page.locator("#wiki-wysiwyg span.c-red").first).to_contain_text("resolveur")

        page.click('[data-mode="markdown"]')
        md = page.locator("#wiki-md").input_value()
        assert "## " in md and "{u}" in md and "{c:red}" in md, md
        page.click("#wiki-save")
        expect(page).to_have_url(re.compile(r".*/p/accueil(\?.*)?$"), timeout=15000)
        expect(page.locator(".wiki-content u").first).to_contain_text("resolveur")
        expect(page.locator(".wiki-content span.c-red").first).to_contain_text("resolveur")

        # --- the wiki sidebar separates generating from deleting ------------
        page.goto(f"{BASE_URL}/wiki/{wiki_id}/p/accueil", wait_until="networkidle")
        if page.locator('html[data-ai="on"]').count():
            expect(page.locator(".wiki-side-foot #wiki-ai-open")).to_be_visible()
            page.click("#wiki-ai-open")
            expect(page.locator("#wiki-ai-panel")).to_be_visible()
            expect(page.locator(".wiki-content")).to_be_hidden()
        else:
            # No provider: the button is rendered but the ai-only rule hides it,
            # and the reading area stays visible.
            expect(page.locator("#wiki-ai-open")).to_be_hidden()
            expect(page.locator(".wiki-content")).to_be_visible()

        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_pro_tab_pdf_export_and_the_assessment_card(browser):
    """Lot 9: a professional tab, a PDF export, and the assessment card."""
    context, page, recorder = new_page(browser, viewport=(1440, 980))
    try:
        page.goto(f"{BASE_URL}/about", wait_until="networkidle")
        # Each view carries its own switch (the pro view is hidden, not removed).
        expect(page.locator(".ld-switch-btn:visible")).to_have_count(2)
        page.locator('.ld-switch-btn[data-tab="pro"]:visible').click()
        expect(page.locator(".pro-card")).to_have_count(4)
        expect(page.locator(".pro-free h2")).to_be_visible()
        expect(page.locator(".pro-free")).to_contain_text("Free for everyone")

        email = f"lot9-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Yann Pro")
        csrf = next(cookie["value"] for cookie in context.cookies() if cookie["name"] == "ol_csrf")

        # A questionnaire with a single run: the assessment card appears.
        quiz = page.request.post(
            f"{BASE_URL}/api/v1/quizzes",
            data=json.dumps(
                {
                    "title": "Certification — réseau",
                    "description": "Évaluation des candidats.",
                    "mode": "qcm",
                    "max_attempts": 1,
                    "questions": [
                        {
                            "text_html": "<p>Quel port pour le DNS ?</p>",
                            "time_limit_seconds": 30,
                            "points": 100,
                            "options": [
                                {"text": "53", "is_correct": True},
                                {"text": "80", "is_correct": False},
                            ],
                        }
                    ],
                }
            ),
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        ).json()
        page.goto(f"{BASE_URL}/quizzes/{quiz['id']}", wait_until="networkidle")
        expect(page.locator("#quiz-assess")).to_be_visible()
        expect(page.locator("#assess-limit")).to_be_visible()
        expect(page.locator("#assess-limit")).to_have_value("1")

        # A wiki page offers both markdown and PDF exports.
        wiki = page.request.post(
            f"{BASE_URL}/api/v1/wiki",
            data=json.dumps({"title": "Wiki du lot 9", "description": "Export PDF."}),
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        ).json()
        detail = page.request.get(f"{BASE_URL}/api/v1/wiki/{wiki['id']}").json()
        slug = detail["pages"][0]["slug"]
        page.goto(f"{BASE_URL}/wiki/{wiki['id']}/p/{slug}", wait_until="networkidle")
        expect(page.locator(f'a[href^="/api/v1/wiki/{wiki["id"]}/export.pdf"]')).to_be_visible()
        expect(page.locator('a[href^="/api/v1/wiki/pages/"][href$="/export.pdf"]')).to_be_visible()

        pdf = page.request.get(f"{BASE_URL}/api/v1/wiki/{wiki['id']}/export.pdf?lang=fr")
        assert pdf.status == 200
        assert pdf.body()[:4] == b"%PDF"
    finally:
        context.close()
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"


def test_enter_after_a_heading_and_images_beside_text_survive_save(browser):
    """Field report: stray line breaks, and images vanishing on save."""
    context, page, recorder = new_page(browser, viewport=(1440, 980))
    try:
        page.goto(f"{BASE_URL}/", wait_until="networkidle")
        email = f"typing-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Plume Test")
        csrf = next(cookie["value"] for cookie in context.cookies() if cookie["name"] == "ol_csrf")

        wiki = page.request.post(
            f"{BASE_URL}/api/v1/wiki",
            data=json.dumps({"title": "Atelier d'écriture", "description": "Frappe"}),
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        ).json()
        detail = page.request.get(f"{BASE_URL}/api/v1/wiki/{wiki['id']}").json()
        page_id = detail["pages"][0]["id"]
        page.request.put(
            f"{BASE_URL}/api/v1/wiki/pages/{page_id}",
            data=json.dumps(
                {"title": "Séance", "content_md": "# {c:red}Titre coloré{/c}\n\nUn paragraphe existant.\n"}
            ),
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        )

        page.goto(f"{BASE_URL}/wiki/{wiki['id']}/edit/{page_id}", wait_until="networkidle")
        page.click('[data-mode="wysiwyg"]')
        page.wait_for_timeout(400)

        # Enter at the end of the coloured heading: the new line must be a plain
        # paragraph, not a copy of the heading's colour.
        page.evaluate(
            """() => {
              const heading = document.querySelector("#wiki-wysiwyg h1");
              const range = document.createRange();
              range.selectNodeContents(heading);
              range.collapse(false);
              const selection = window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              document.querySelector("#wiki-wysiwyg").focus();
            }"""
        )
        page.keyboard.press("Enter")
        page.keyboard.type("Première ligne écrite par l'auteure.", delay=12)
        page.wait_for_timeout(200)
        html = page.evaluate("() => document.querySelector('#wiki-wysiwyg').innerHTML")
        assert "<p>Première ligne écrite par l'auteure.</p>" in html, html[:400]

        # An image dropped inside a paragraph that already has text.
        image_path = "/tmp/e2e-wiki.png"
        with open(image_path, "wb") as handle:
            handle.write(_picture_png(160, 100))
        page.keyboard.type(" ", delay=10)
        page.set_input_files("#wiki-image-input", image_path)
        page.wait_for_timeout(2200)
        page.keyboard.type("Et la suite après l'image.", delay=10)
        page.wait_for_timeout(300)

        page.click("#wiki-save")
        page.wait_for_timeout(2000)
        saved = page.request.get(f"{BASE_URL}/api/v1/wiki/pages/{page_id}").json()["content_md"]
        assert "Première ligne écrite par l'auteure." in saved
        assert "Et la suite après l'image." in saved
        assert "![" in saved, saved
        assert "\n\nPremière ligne" in saved, repr(saved)

        slug = page.request.get(f"{BASE_URL}/api/v1/wiki/pages/{page_id}").json()["slug"]
        page.goto(f"{BASE_URL}/wiki/{wiki['id']}/p/{slug}", wait_until="networkidle")
        expect(page.locator(".wiki-article img")).to_have_count(1)
    finally:
        context.close()
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"


def test_the_account_menu_stays_on_screen_on_a_phone(browser):
    """The account popover has to open inwards, not off the edge of the screen.

    It is anchored on the right edge of its button, and a 13rem panel does not
    fit beside a control placed in the middle of the bar: on a 390px screen the
    menu started 31px outside the viewport. Keeping the account last, after the
    theme switch, is what makes the geometry work — so the test checks both the
    order of the controls and where the panel lands.
    """
    for width in (320, 360, 390):
        context, page, recorder = new_page(browser, viewport=(width, 780))
        try:
            page.goto(f"{BASE_URL}/", wait_until="networkidle")
            page.click("#account-button")
            page.wait_for_selector("#account-popover:not([hidden])")
            phone = page.evaluate(
                """() => {
                  const rect = (selector) => {
                    const el = document.querySelector(selector);
                    return el ? el.getBoundingClientRect() : null;
                  };
                  const pop = rect('#account-popover');
                  return {
                    left: Math.round(pop.left), right: Math.round(pop.right),
                    bottom: Math.round(pop.bottom),
                    vw: window.innerWidth, vh: window.innerHeight,
                    account: Math.round(rect('#account-button').right),
                    theme: Math.round(rect('#theme-toggle').right),
                    language: Math.round(rect('#language-button').right),
                  };
                }"""
            )
            assert phone["left"] >= 0, (width, phone)
            assert phone["right"] <= phone["vw"], (width, phone)
            assert phone["bottom"] <= phone["vh"], (width, phone)
            assert phone["account"] > phone["theme"] > phone["language"], (width, phone)
            assert recorder.errors == [], recorder.errors
        finally:
            context.close()


def test_a_wiki_card_opens_on_a_page_that_exists(browser):
    """The catalogue link must carry the wiki slug, not one built from the title.

    Regression: a demo wiki titled "Climate and resources" has the slug
    "environment". The card pointed at /wiki/34/climate-and-resources, no page
    matched that slug, and the reader announced an empty wiki holding four
    pages. The link, the reader fallback and the server canonical must agree.
    """
    context, page, recorder = new_page(browser, viewport=(1440, 980))
    try:
        email = f"wiki-links-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Link Tester")

        page.goto(f"{BASE_URL}/wiki", wait_until="networkidle")
        cards = page.locator(".wiki-card a[data-link]")
        expect(cards.first).to_be_visible(timeout=15000)
        href = cards.first.get_attribute("href")
        assert re.fullmatch(r"/wiki/\d+/[a-z0-9-]+", href or ""), href

        # The catalogue's own link, opened as a visitor would open it.
        page.goto(f"{BASE_URL}{href}", wait_until="networkidle")
        heading = page.locator(".wiki-article-head h1")
        expect(heading).to_be_visible(timeout=15000)
        assert heading.inner_text().strip(), "the reader showed no article"

        body = page.locator("#wiki-content")
        expect(body).to_be_visible(timeout=15000)
        assert body.inner_text().strip(), "the article rendered empty"

        # And the empty state must not be what the visitor reads.
        assert "no page yet" not in page.locator(".wiki-main").inner_text().lower()

        # The sidebar title link, the other way back into the same wiki.
        sidebar = page.locator(".wiki-side-title").first
        expect(sidebar).to_have_attribute("href", re.compile(r"/wiki/\d+/[a-z0-9-]+$"))
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_the_about_headline_does_not_move_the_boxes_below_it(browser):
    """Typing the rotating sentence used to resize the headline by one line.

    The h1 measured 184px with a short word and 233px with a long one, so the
    problem and answer boxes jumped 25px up and down for ever. Every rotating
    word now shares one grid cell, and the tallest one fixes the line height.
    """
    context, page, recorder = new_page(browser, viewport=(1440, 900))
    try:
        page.goto(f"{BASE_URL}/about", wait_until="networkidle")
        page.wait_for_selector(".ld-problem", timeout=20000)
        page.wait_for_timeout(2500)  # the reveal animation moves the block once

        heights, tops = [], []
        for _ in range(12):
            page.wait_for_timeout(250)
            heights.append(
                round(page.evaluate("document.querySelector('.ld-hero h1').getBoundingClientRect().height"))
            )
            tops.append(
                round(page.evaluate("document.querySelector('.ld-problem').getBoundingClientRect().top"))
            )
        assert len(set(heights)) == 1, f"the headline changes height while typing: {heights}"
        assert max(tops) - min(tops) <= 1, f"the boxes move while typing: {tops}"
        assert recorder.errors == [], recorder.errors
    finally:
        context.close()


def test_a_phone_shows_the_problem_before_it_asks_for_a_scroll(browser):
    """A phone used to open on the mock, then a headline, and nothing else.

    The visitor had to guess that the page continued. The text comes first now,
    the problem box is on the first screen, and a sticky arrow says so.
    """
    for width, height in ((390, 844), (360, 640), (320, 568)):
        context, page, recorder = new_page(browser, viewport=(width, height))
        try:
            page.goto(f"{BASE_URL}/about", wait_until="networkidle")
            page.wait_for_selector(".ld-problem", timeout=20000)
            page.wait_for_timeout(2400)
            metrics = page.evaluate(
                """() => {
                  const box = (s) => document.querySelector(s).getBoundingClientRect();
                  return {
                    vh: window.innerHeight,
                    problemTop: box('.ld-problem').top,
                    problemBottom: box('.ld-problem').bottom,
                    cueDisplay: getComputedStyle(document.querySelector('.ld-scroll-cue')).display,
                    cueTop: box('.ld-scroll-cue').top,
                  };
                }"""
            )
            assert metrics["problemTop"] < metrics["vh"], (width, metrics)
            assert metrics["problemBottom"] > 0, (width, metrics)
            # Three quarters of the box at least: a sliver is not an invitation.
            visible = min(metrics["problemBottom"], metrics["vh"]) - max(metrics["problemTop"], 0)
            assert visible > 0.75 * (metrics["problemBottom"] - metrics["problemTop"]), (width, metrics)
            assert metrics["cueDisplay"] != "none", (width, metrics)
            assert metrics["cueTop"] < metrics["vh"], (width, metrics)
            assert recorder.errors == [], recorder.errors
        finally:
            context.close()


def test_the_first_visual_shows_both_a_wiki_and_a_quiz(browser):
    """One picture for the whole product: a shared document, then a live quiz.

    The hero used to repeat the quiz mock that already sits in the first scene
    below it. It is now a two-act window: a wiki being written by three people,
    and a quiz being answered. The tabs must switch by hand and the panel must
    follow.
    """
    context, page, recorder = new_page(browser, viewport=(1440, 900))
    try:
        page.goto(f"{BASE_URL}/about", wait_until="networkidle")
        page.wait_for_selector("[data-studio]", timeout=20000)
        page.wait_for_timeout(1200)

        assert page.locator("[data-studio-panel]").count() == 2
        on = page.evaluate(
            "[...document.querySelectorAll('[data-studio-panel]')].filter(p => p.classList.contains('is-on')).map(p => p.dataset.studioPanel)"
        )
        assert len(on) == 1, f"exactly one act is visible, got {on}"

        page.evaluate("document.querySelector('[data-studio-tab=\"quiz\"]').click()")
        page.wait_for_timeout(400)
        assert page.evaluate("document.querySelector('[data-studio]').dataset.on") == "quiz"
        assert page.evaluate("[...document.querySelectorAll('[data-studio-panel]')].filter(p => p.classList.contains('is-on')).length") == 1
        assert recorder.errors == [], recorder.errors
    finally:
        context.close()


def test_the_footer_offers_a_way_to_write_to_the_project(browser):
    """A visitor who wants to help or ask something finds a mail address."""
    context, page, recorder = new_page(browser, viewport=(1440, 900))
    try:
        page.goto(f"{BASE_URL}/", wait_until="networkidle")
        page.wait_for_selector("footer", timeout=20000)
        hrefs = page.evaluate("[...document.querySelectorAll('footer a')].map(a => a.getAttribute('href') || '')")
        assert any(href.startswith("mailto:developper@openlearnproject.org") for href in hrefs), hrefs
        assert recorder.errors == [], recorder.errors
    finally:
        context.close()


def test_the_advance_button_sits_under_the_room_and_asks_before_skipping(browser):
    """A host cannot skip a question by accident, and the control is out of reach.

    The button used to sit right under the answer grid, where a hosting player
    looks for "submit". It now lives below the player list and only fires
    without a question once everyone has answered or the countdown is over.
    """
    host_context, host_page, host_errors = new_page(browser)
    guest_context, guest_page, guest_errors = new_page(browser, (900, 800))
    try:
        host_email = f"advance-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(host_page, host_email, "Advance Host")
        create_quiz_through_editor(host_page, "Advance button quiz")

        host_page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
        host_page.locator('button[data-act="host"]').first.click()
        expect(host_page).to_have_url(re.compile(r".*/host/[A-Z0-9]+$"), timeout=15000)
        pin = read_pin(host_page)

        guest_page.goto(f"{BASE_URL}/play/{pin}", wait_until="networkidle")
        guest_page.fill("#nickname", "Slow Guest")
        guest_page.click("#join-form button[type=submit]")
        expect(host_page.locator(".participant-chip")).to_contain_text("Slow Guest", timeout=15000)

        host_page.locator('[data-act="start"]').click()
        expect(host_page.locator(".question-card")).to_be_visible(timeout=15000)

        next_button = host_page.locator('[data-act="next"]')
        expect(next_button).to_be_visible(timeout=15000)
        # Armed only in the sense that it asks first.
        assert next_button.get_attribute("data-gated") == "1"
        expect(host_page.locator("[data-advance-hint]")).to_contain_text(
            "1 player has not answered yet", timeout=15000
        )

        # Below the room: the player list ends above the control's box.
        room = host_page.locator("section.card").last
        assert next_button.bounding_box()["y"] > room.bounding_box()["y"] + room.bounding_box()["height"] - 8

        next_button.click()
        modal = host_page.locator("#modal-root .modal")
        expect(modal).to_be_visible(timeout=5000)
        assert "Move to the next question?" in modal.inner_text()

        # Backing out leaves the question where it was.
        modal.locator('[data-action="cancel"]').click()
        expect(modal).to_be_hidden(timeout=5000)
        expect(host_page.locator(".question-card")).to_be_visible(timeout=5000)
        assert "Question 1" in host_page.locator(".badge").first.inner_text()

        # Everyone answers: the server reveals, and the control stops asking.
        answer_current_question(guest_page)
        expect(host_page.locator(".option-btn.correct").first).to_be_visible(timeout=15000)
        finish = host_page.locator('[data-act="next"], [data-act="finish"]').last
        expect(finish).to_be_visible(timeout=15000)
        assert finish.get_attribute("data-gated") in (None, "0")

        assert host_errors.errors == [], f"host errors: {host_errors.errors}"
        assert guest_errors.errors == [], f"guest errors: {guest_errors.errors}"
    finally:
        host_context.close()
        guest_context.close()


def test_the_account_menu_lists_only_the_account_and_the_way_out(browser):
    """Questionnaires have their own section in the account page.

    The popover kept a "My questionnaires" entry after the account page grew a
    dedicated section, so the same link appeared twice in two different shapes.
    """
    context, page, recorder = new_page(browser, viewport=(1280, 900))
    try:
        register_through_ui(page, f"menu-{uuid.uuid4().hex[:8]}@example.com", "Menu Tester")
        page.click("#account-button")
        expect(page.locator("#account-popover")).to_be_visible(timeout=5000)
        items = page.locator("#account-popover .account-item")
        labels = [item.inner_text().strip() for item in items.all()]
        assert len(labels) == 2, labels
        assert labels[0] == "Account", labels
        assert labels[1] == "Sign out", labels
        assert recorder.errors == [], recorder.errors
    finally:
        context.close()


def test_the_legal_notice_ships_with_the_interface(browser):
    """The project notice is written once, in every language, and linked."""
    context, page, recorder = new_page(browser)
    try:
        page.goto(f"{BASE_URL}/legal", wait_until="networkidle")
        expect(page.locator(".legal-head h1")).to_be_visible()
        expect(page.locator(".footer a[href=\"/legal\"]")).to_be_visible()

        doc = page.locator(".legal-doc")
        # Four project sections plus the instance block, always present.
        expect(page.locator(".legal-section")).to_have_count(5)
        expect(page.locator(".legal-instance")).to_be_visible()
        text = doc.inner_text()
        assert "AGPL-3.0-only" in text
        assert "Contributions" in text

        # Markdown was rendered, not printed: the notice carries real headings,
        # emphasis and a clickable mail link, and no leftover asterisks.
        assert page.locator(".legal-doc h2").count() >= 5
        assert page.locator(".legal-body strong").count() >= 3
        assert page.locator('.legal-body a[href^="mailto:"]').count() >= 1
        assert "**" not in text

        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_arabic_flips_the_document_and_every_language_reaches_the_page(browser):
    context, page, recorder = new_page(browser, force_language=False)
    try:
        page.goto(f"{BASE_URL}/legal", wait_until="networkidle")
        page.evaluate("() => localStorage.setItem('ol_language', 'ar')")
        page.reload(wait_until="networkidle")

        assert page.evaluate("() => document.documentElement.dir") == "rtl"
        # A parking spot written with a physical side (`left: -999px`) used to
        # widen the document by a thousand pixels in a right-to-left page.
        width = page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        assert width[0] == width[1], f"the page scrolls sideways in Arabic: {width}"
        assert page.evaluate("() => document.documentElement.lang") == "ar"
        arabic = page.locator(".legal-doc").inner_text()
        # A key that was never translated would be printed verbatim.
        assert "legal." not in arabic
        assert "العربية" in page.locator("#language-button").inner_text() or "ar" in page.evaluate(
            "() => document.documentElement.lang"
        )

        # Hindi keeps the document left to right, and is translated too.
        page.evaluate("() => localStorage.setItem('ol_language', 'hi')")
        page.reload(wait_until="networkidle")
        assert page.evaluate("() => document.documentElement.dir") == "ltr"
        hindi = page.locator(".legal-doc").inner_text()
        assert "legal." not in hindi
        assert any("\u0900" <= char <= "\u097f" for char in hindi), hindi[:120]

        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_a_link_inside_a_list_survives_the_rich_editor(browser):
    """The rich surface serialises back to markdown; a bullet keeps its marks."""
    context, page, recorder = new_page(browser)
    try:
        email = f"inline-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Inline Tester")

        page.goto(f"{BASE_URL}/wiki/new", wait_until="networkidle")
        page.fill('#wiki-create input[name="title"]', "Liens en liste")
        page.fill('#wiki-create textarea[name="description"]', "Regression: marques en ligne dans une puce.")
        page.click("#wiki-create button[type=submit]")
        expect(page).to_have_url(re.compile(r".*/wiki/\d+/edit/\d+$"), timeout=15000)
        wiki_url = re.sub(r"/edit/.*$", "", page.url)

        page.click('[data-mode="markdown"]')
        page.fill("#wiki-page-title", "Contact")
        page.locator("#wiki-md").fill(
            "- **Gras** puis [courriel](mailto:contact@example.org)\n- Un point sans marque\n"
        )
        # Through the rich surface and back: this is the serialiser a save uses.
        page.click('[data-mode="wysiwyg"]')
        expect(page.locator("#wiki-wysiwyg li strong")).to_have_count(1)
        expect(page.locator('#wiki-wysiwyg li a[href="mailto:contact@example.org"]')).to_have_count(1)
        page.click('[data-mode="markdown"]')
        serialised = page.input_value("#wiki-md")
        assert "**Gras**" in serialised, serialised
        assert "](mailto:contact@example.org)" in serialised, serialised

        page.click("#wiki-save")
        page.goto(wiki_url, wait_until="networkidle")
        expect(page.locator('.wiki-main li a[href="mailto:contact@example.org"]')).to_have_count(1)
        expect(page.locator(".wiki-main li strong")).to_have_count(1)
        assert recorder.errors == [], f"frontend errors: {recorder.errors}"
    finally:
        context.close()


def test_a_page_emptied_to_its_title_still_takes_a_line_break(browser):
    """A new page opens on "# Untitled". Clearing it left the heading behind, so
    everything typed next went *into a title*: Shift+Enter wrote a <br> inside an
    h1, the author saw three lines in one block, and the page was saved as a
    heading made of prose. An emptied heading is not a title."""
    context, page, recorder = new_page(browser, viewport=(1440, 900))
    try:
        email = f"wiki-empty-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Camille Vide")

        page.goto(f"{BASE_URL}/wiki/new", wait_until="networkidle")
        page.fill('#wiki-create input[name="title"]', "Page vide")
        page.click("#wiki-create button[type=submit]")
        expect(page).to_have_url(re.compile(r".*/wiki/\d+/edit/\d+$"), timeout=15000)

        surface = page.locator("#wiki-wysiwyg")
        expect(surface).to_be_visible(timeout=15000)
        surface.click()
        page.keyboard.press("Control+a")
        page.keyboard.press("Delete")
        # The cleared page is a paragraph again, not a heading waiting for text.
        expect(surface.locator("h1")).to_have_count(0)

        page.keyboard.type("premiere ligne")
        page.keyboard.press("Shift+Enter")
        page.keyboard.type("deuxieme ligne")
        markup = page.evaluate("document.querySelector('#wiki-wysiwyg').innerHTML")
        assert "<h1" not in markup, markup
        assert "premiere ligne<br>deuxieme ligne" in markup, markup

        page.click("#wiki-save")
        expect(page).to_have_url(re.compile(r".*/p/.+$"), timeout=15000)
        text = page.locator("#wiki-content").inner_text()
        assert "premiere ligne" in text and "deuxieme ligne" in text, text
        assert text.count("\n") >= 1, text
        assert recorder.errors == [], recorder.errors
    finally:
        context.close()


def test_a_table_column_is_added_and_removed_where_the_caret_stands(browser):
    """A table could only be inserted whole: adding or dropping a column meant
    rewriting the markdown by hand. The menu acts on the cell holding the caret,
    on every row at once, and refuses to empty the table of its last column."""
    context, page, recorder = new_page(browser, viewport=(1440, 900))
    try:
        email = f"wiki-table-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Yann Tableau")

        page.goto(f"{BASE_URL}/wiki/new", wait_until="networkidle")
        page.fill('#wiki-create input[name="title"]', "Tableau")
        page.click("#wiki-create button[type=submit]")
        expect(page).to_have_url(re.compile(r".*/wiki/\d+/edit/\d+$"), timeout=15000)
        wiki_id = int(re.search(r"/wiki/(\d+)/edit", page.url).group(1))

        surface = page.locator("#wiki-wysiwyg")
        expect(surface).to_be_visible(timeout=15000)
        surface.click()
        page.click('[data-cmd="table"]')
        widths = lambda: page.evaluate(  # noqa: E731 - a one-line reader
            "() => Array.from(document.querySelectorAll('#wiki-wysiwyg table tr')).map((r) => r.children.length)"
        )
        first = widths()
        assert first and len(set(first)) == 1, first
        columns = first[0]

        def column_action(action: str) -> None:
            page.click("[data-table-menu]")
            expect(page.locator("#wiki-table-menu")).to_be_visible(timeout=5000)
            page.click(f'[data-table-act="{action}"]')

        # A body cell, because that is where an author writes.
        page.click("#wiki-wysiwyg tbody tr:nth-child(1) td:nth-child(1)")
        column_action("column-after")
        grown = widths()
        assert set(grown) == {columns + 1}, grown

        # The caret now stands in the inserted cell: remove that same column.
        column_action("column-delete")
        assert set(widths()) == {columns}, widths()

        # And the last column cannot be removed: the table would stop being one.
        while widths()[0] > 1:
            page.click("#wiki-wysiwyg tbody tr:nth-child(1) td:nth-child(1)")
            column_action("column-delete")
        assert set(widths()) == {1}, widths()
        page.click("#wiki-wysiwyg tbody tr:nth-child(1) td:nth-child(1)")
        column_action("column-delete")
        assert set(widths()) == {1}, widths()

        page.click("#wiki-save")
        expect(page).to_have_url(re.compile(r".*/p/.+$"), timeout=15000)
        detail = page.request.get(f"{BASE_URL}/api/v1/wiki/{wiki_id}").json()
        markdown = detail["pages"][0]["content_md"]
        table_lines = [line for line in markdown.splitlines() if line.strip().startswith("|")]
        assert table_lines, markdown
        assert len({line.count("|") for line in table_lines}) == 1, markdown
        assert recorder.errors == [], recorder.errors
    finally:
        context.close()


def test_a_revision_deck_is_not_rewritten_into_a_stranger_s_quiz(browser):
    """A deck embedded in a page came back as `{quiz:<same id>}`.

    The editor kept two of the three kinds of embed, so a page holding `{deck:19}`
    was saved as `{quiz:19}` — another author's questionnaire, in another
    language, in place of the author's own revision cards.
    """
    context, page, recorder = new_page(browser, viewport=(1440, 900))
    try:
        email = f"wiki-deck-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Nadia Fiches")
        csrf = next(cookie["value"] for cookie in context.cookies() if cookie["name"] == "ol_csrf")
        headers = {"X-CSRF-Token": csrf, "Content-Type": "application/json"}

        wiki = page.request.post(
            f"{BASE_URL}/api/v1/wiki",
            headers=headers,
            data=json.dumps({"title": "Wiki des fiches", "description": ""}),
        ).json()
        detail = page.request.get(f"{BASE_URL}/api/v1/wiki/{wiki['id']}").json()
        page_id = detail["pages"][0]["id"]
        deck = page.request.post(
            f"{BASE_URL}/api/v1/decks",
            headers=headers,
            data=json.dumps({"title": "Fiches du wiki", "wiki_id": wiki["id"]}),
        ).json()
        page.request.put(
            f"{BASE_URL}/api/v1/wiki/pages/{page_id}",
            headers=headers,
            data=json.dumps({"title": "Le cheval", "content_md": f"# Le cheval\n\n{{deck:{deck['id']}}}\n"}),
        )

        page.goto(f"{BASE_URL}/wiki/{wiki['id']}/edit/{page_id}", wait_until="networkidle")
        surface = page.locator("#wiki-wysiwyg")
        expect(surface).to_be_visible(timeout=15000)
        expect(surface.locator('.wiki-embed[data-embed="deck"]')).to_have_count(1)

        # Touching the page is enough: saving rewrites every embed it holds.
        surface.click()
        page.keyboard.press("End")
        page.keyboard.type(" ")
        page.click("#wiki-save")
        expect(page).to_have_url(re.compile(r".*/p/.+$"), timeout=15000)

        saved = page.request.get(f"{BASE_URL}/api/v1/wiki/{wiki['id']}").json()
        markdown = next(item for item in saved["pages"] if item["id"] == page_id)["content_md"]
        assert f"{{deck:{deck['id']}}}" in markdown, markdown
        assert f"{{quiz:{deck['id']}}}" not in markdown, markdown

        # The caret cannot enter an opaque block, so the block carries the way
        # out: a page written before the fix holds a marker its author must be
        # able to delete without switching to markdown by hand.
        page.goto(f"{BASE_URL}/wiki/{wiki['id']}/edit/{page_id}", wait_until="networkidle")
        surface = page.locator("#wiki-wysiwyg")
        expect(surface.locator(".wiki-embed")).to_have_count(1, timeout=15000)
        surface.locator("[data-embed-remove]").click()
        expect(surface.locator(".wiki-embed")).to_have_count(0)
        page.click("#wiki-save")
        expect(page).to_have_url(re.compile(r".*/p/.+$"), timeout=15000)
        cleared = page.request.get(f"{BASE_URL}/api/v1/wiki/{wiki['id']}").json()
        text = next(item for item in cleared["pages"] if item["id"] == page_id)["content_md"]
        assert f"{{deck:{deck['id']}}}" not in text and f"{{quiz:{deck['id']}}}" not in text, text
        assert recorder.errors == [], recorder.errors
    finally:
        context.close()


def test_the_lobby_shows_a_code_a_phone_can_scan(browser):
    """A host projecting the lobby needs more than a PIN read aloud: a student
    points a camera at the screen. The code carries the join link itself, so a
    scan lands on the same page the URL opens, and it can be shown large."""
    context, page, recorder = new_page(browser, viewport=(1440, 900))
    try:
        email = f"qr-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Hôte Projection")
        quiz_id = create_quiz_through_editor(page, "Partie projetée")

        page.goto(f"{BASE_URL}/quizzes/{quiz_id}", wait_until="networkidle")
        page.locator('[data-act="live"]').click()
        expect(page).to_have_url(re.compile(r".*/host/[A-Z0-9]+$"), timeout=20000)

        code = page.url.rsplit("/", 1)[-1]
        join_url = page.locator("#join-url").input_value()
        # The code carries the invitation link, not the four-letter PIN: a scan
        # must land on the page that asks for a nickname, without typing.
        assert join_url.startswith("http") and "/join/" in join_url, join_url

        qr = page.locator(".lobby-qr svg")
        expect(qr).to_be_visible(timeout=15000)
        viewbox = qr.get_attribute("viewBox").split()
        assert viewbox[0] == "0" and viewbox[1] == "0" and viewbox[2] == viewbox[3]
        # Quiet zone of four modules on each side around a real QR matrix.
        modules = int(viewbox[2]) - 8
        assert modules >= 21 and (modules - 21) % 4 == 0, viewbox
        # A scanner needs contrast: the code draws its own white field.
        assert qr.locator("rect[fill='#ffffff']").count() == 1

        page.click('[data-act="qr-big"]')
        overlay = page.locator(".qr-overlay")
        expect(overlay).to_be_visible(timeout=10000)
        expect(overlay.locator(".qr-overlay-code")).to_have_text(code)
        expect(overlay.locator("svg")).to_be_visible()

        page.keyboard.press("Escape")
        expect(page.locator(".qr-overlay")).to_have_count(0)
        expect(page.locator(".lobby-qr svg")).to_be_visible()
        assert recorder.errors == [], recorder.errors
    finally:
        context.close()


def test_a_step_keeps_the_caret_and_a_trash_asks_before_it_deletes(browser):
    """Clicking a step's text put the caret in the toolbar, not in the text.

    The rich text area sat inside a `<label>`, so the browser forwarded every
    click to the first control the label owns — the bold button. Typing then
    toggled bold and the caret vanished. The delete buttons had the mirror
    problem: one refused silently (a step keeps two answers), the other threw an
    effect away on a single click.
    """
    context, page, recorder = new_page(browser, viewport=(1440, 1000))
    try:
        email = f"adv-caret-{uuid.uuid4().hex[:8]}@example.com"
        register_through_ui(page, email, "Sacha Aventure")
        csrf = next(cookie["value"] for cookie in context.cookies() if cookie["name"] == "ol_csrf")
        headers = {"X-CSRF-Token": csrf, "Content-Type": "application/json"}
        draft = page.request.post(
            f"{BASE_URL}/api/v1/quizzes/draft",
            headers=headers,
            data=json.dumps(
                {
                    "title": "Le curseur",
                    "mode": "adventure",
                    "default_language": "en",
                    "adventure": {
                        "start": "debut",
                        "attributes": [
                            {"key": "courage", "label": "Courage", "initial_value": 1, "min_value": 0, "max_value": 5}
                        ],
                        "nodes": [
                            {
                                "key": "debut",
                                "kind": "question",
                                "text_html": "<p>Bonjour</p>",
                                "choices": [
                                    {"key": "debut-a", "text": "Go", "target": "fin", "effects": []},
                                    {"key": "debut-b", "text": "Stay", "target": "fin", "effects": []},
                                ],
                            },
                            {
                                "key": "fin",
                                "kind": "ending",
                                "text_html": "<p>The end.</p>",
                                "outcomes": [
                                    {"kind": "highest", "attribute": "courage", "text_html": "<p>Well done.</p>"}
                                ],
                            },
                        ],
                    },
                }
            ),
        ).json()

        page.goto(f"{BASE_URL}/adventures/{draft['id']}/edit", wait_until="networkidle")
        surface = page.locator('[data-node-field="text_html"]').first
        expect(surface).to_be_visible(timeout=15000)
        surface.click()
        assert page.evaluate(
            "() => document.activeElement && document.activeElement.classList.contains('rte')"
        ), page.evaluate("() => document.activeElement && document.activeElement.className")

        page.keyboard.type(" encore")
        expect(surface).to_contain_text("Bonjour encore")
        assert page.locator(".rte-toolbar [data-cmd='bold'][aria-pressed='true']").count() == 0

        # A delete click asks first, and cancelling leaves the row in place.
        page.locator('[data-act="add-effect"]').first.click()
        rows = page.locator(".adv-effect-row")
        expect(rows).to_have_count(1)
        page.locator('[data-act="remove-effect"]').first.click()
        dialog = page.locator('[role="dialog"]')
        expect(dialog).to_be_visible(timeout=5000)
        dialog.get_by_role("button", name=re.compile("cancel", re.I)).click()
        expect(rows).to_have_count(1)
        page.locator('[data-act="remove-effect"]').first.click()
        page.locator('[role="dialog"]').get_by_role("button", name=re.compile("remove", re.I)).click()
        expect(rows).to_have_count(0)

        # A refused removal says why instead of doing nothing at all.
        page.locator('[data-act="remove-choice"]').first.click()
        expect(page.locator(".adv-choice-card")).to_have_count(2)
        expect(page.get_by_text(re.compile("at least two answers", re.I))).to_be_visible(timeout=5000)
        assert recorder.errors == [], recorder.errors
    finally:
        context.close()


def test_a_mailed_reset_link_opens_the_form_that_chooses_a_password(browser):
    """`/reset/<token>` used to paint the *request* form again.

    The router calls a handler with the path parameters spread at the top level
    (`{ token, query }`); the page destructured `{ params }`, so the token was
    always empty and every mailed link sent the reader back to "enter your
    address" — the one thing they had just done.
    """
    context, page, recorder = new_page(browser)
    try:
        asked: list[str] = []
        page.on(
            "request",
            lambda request: "password/reset" in request.url and asked.append(request.url),
        )
        page.goto(f"{BASE_URL}/reset/known-token-123", wait_until="networkidle")
        page.wait_for_timeout(1500)

        assert any(url.endswith("/password/reset/known-token-123") for url in asked), (
            f"the page never asked the server about its token: {asked}"
        )
        assert page.locator("#forgot-form").count() == 0, "the request form came back"
        assert recorder.errors == [], recorder.errors
    finally:
        context.close()


def test_a_mailed_confirmation_link_carries_its_token_to_the_server(browser):
    """Same defect on the other mailed link: `/verify/<token>` lost the token."""
    context, page, recorder = new_page(browser)
    try:
        asked: list[str] = []
        page.on(
            "request",
            lambda request: "email/verify" in request.url and asked.append(request.url),
        )
        page.goto(f"{BASE_URL}/verify/known-token-123", wait_until="networkidle")
        page.wait_for_timeout(1500)

        assert any(url.endswith("/email/verify/known-token-123") for url in asked), (
            f"the confirmation page never sent its token: {asked}"
        )
        assert recorder.errors == [], recorder.errors
    finally:
        context.close()
