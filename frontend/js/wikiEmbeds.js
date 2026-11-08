// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Questionnaire, adventure and deck embeds inside a wiki page.

   A page carries a bare marker, `{quiz:12}`, `{adventure:12}` or `{deck:12}`,
   on its own line. The server turns it into an empty container; this module
   fills it with the real widget, already open: the reader meets the content,
   not a button promising it. The only escape hatch is a discreet link to the
   full page, in the top-right corner of the module.

   Mounting is deferred until the module comes into view, so a long article
   with three embeds does not open three runs nobody asked for.
*/

import { api } from "./api.js";
import { t, tp } from "./i18n.js";
import { escapeHtml, toast } from "./ui.js";
import { navigate } from "./router.js";
import { currentLanguage } from "./i18n.js";
import { renderPlay } from "./pages/play.js";
import { renderAdventurePlay } from "./pages/adventurePlay.js";
import { cardFace } from "./pages/cardsDeck.js";

function summary(quiz) {
  const count = (quiz.questions || []).length;
  const mode = quiz.mode === "adventure" ? t("wiki.embed_adventure") : quiz.mode === "swipe" ? t("wiki.embed_swipe") : t("wiki.embed_quiz");
  return `<span class="badge">${escapeHtml(mode)}</span>
    <span class="muted small">${escapeHtml(tp("wiki.embed_questions_one", "wiki.embed_questions", count))}</span>`;
}

/** Start a solo run and mount the player inside `host`. */
async function playInline(kind, quizId, host) {
  host.innerHTML = `<div class="loading">${escapeHtml(t("common.loading"))}</div>`;
  try {
    if (kind === "adventure") {
      host.replaceChildren(await renderAdventurePlay({ id: quizId }));
      return;
    }
    const result = await api.post(`/api/v1/quizzes/${quizId}/sessions`, { mode: "solo", language: currentLanguage() });
    const code = result.session.code;
    if (result.participant) {
      localStorage.setItem(`ol_pt_${code}`, result.participant.token);
      localStorage.setItem(`ol_pid_${code}`, String(result.participant.id));
    }
    host.replaceChildren(await renderPlay({ code }));
  } catch (error) {
    host.innerHTML = `<p class="banner error">${escapeHtml(error.detail || t("common.error"))}</p>`;
  }
}

/** The deck reader mounted in the article: one card, both faces, arrows. */
function deckReader(deck) {
  const cards = deck.cards || [];
  let index = 0;
  let flipped = false;

  const stage = document.createElement("div");
  stage.className = "embed-deck";
  stage.innerHTML = `
    <div class="embed-deck-bar">
      <button type="button" class="btn btn-sm btn-ghost" data-deck-prev aria-label="${escapeHtml(t("cards.previous"))}">←</button>
      <span class="muted small" data-deck-count></span>
      <button type="button" class="btn btn-sm btn-ghost" data-deck-next aria-label="${escapeHtml(t("cards.next"))}">→</button>
    </div>
    <article class="revision-card" data-aspect="${escapeHtml(deck.aspect || "2:3")}" tabindex="0">
      <div class="revision-card-inner"></div>
    </article>
    <p class="muted small center" data-deck-hint>${escapeHtml(t("cards.flip_hint"))}</p>`;

  const inner = stage.querySelector(".revision-card-inner");
  const counter = stage.querySelector("[data-deck-count]");

  const paint = () => {
    const card = cards[index];
    inner.innerHTML = `
      <div class="revision-card-face revision-card-front">${cardFace(card, "front")}</div>
      <div class="revision-card-face revision-card-back">${cardFace(card, "back")}</div>`;
    stage.querySelector(".revision-card").classList.toggle("flipped", flipped);
    counter.textContent = `${index + 1} / ${cards.length}`;
  };

  stage.querySelector(".revision-card").addEventListener("click", () => {
    flipped = !flipped;
    stage.querySelector(".revision-card").classList.toggle("flipped", flipped);
  });
  stage.querySelector(".revision-card").addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      stage.querySelector(".revision-card").click();
    }
  });
  const move = (step) => {
    index = (index + step + cards.length) % cards.length;
    flipped = false;
    paint();
  };
  stage.querySelector("[data-deck-prev]").addEventListener("click", () => move(-1));
  stage.querySelector("[data-deck-next]").addEventListener("click", () => move(1));
  paint();
  return stage;
}

/** The module frame: title and summary on the left, one discreet link on the right. */
function shell({ title, meta, href, label }) {
  return `
    <div class="wiki-embed-card">
      <div class="wiki-embed-head">
        <div class="wiki-embed-ident">
          <p class="wiki-embed-title">${escapeHtml(title || "")}</p>
          <p class="wiki-embed-meta">${meta}</p>
        </div>
        <a class="wiki-embed-open" href="${escapeHtml(href)}" data-embed-open title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}">
          <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M14 4h6v6M20 4l-8 8M9 5H5a1 1 0 0 0-1 1v13a1 1 0 0 0 1 1h13a1 1 0 0 0 1-1v-4"/></svg>
        </a>
      </div>
      <div class="wiki-embed-body"></div>
    </div>`;
}

/** Run `mount` once the element is on screen (or right away, without support). */
function whenVisible(element, mount) {
  if (typeof IntersectionObserver !== "function") {
    mount();
    return;
  }
  const observer = new IntersectionObserver(
    (entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      mount();
    },
    { rootMargin: "200px 0px" },
  );
  observer.observe(element);
  // A module already on screen at load time may never fire an entry.
  window.setTimeout(() => {
    if (!element.isConnected) observer.disconnect();
  }, 30000);
}

async function fillDeck(container, id) {
  let deck = null;
  try {
    deck = await api.get(`/api/v1/decks/${id}`);
  } catch {
    container.innerHTML = `<p class="muted small">${escapeHtml(t("wiki.embed_failed"))}</p>`;
    return;
  }
  const cards = deck.cards || [];
  const count = tp("cards.card_one", "cards.card_many", cards.length);
  container.innerHTML = shell({
    title: deck.title,
    meta: `<span class="badge">${escapeHtml(t("wiki.embed_deck"))}</span>
      <span class="muted small">${escapeHtml(`${cards.length} ${count}`)}</span>`,
    href: `/cards/${id}`,
    label: t("wiki.embed_full_page"),
  });
  const body = container.querySelector(".wiki-embed-body");
  whenVisible(container, () => body.replaceChildren(deckReader(deck)));
}

async function fill(container) {
  const kind = container.dataset.embed; // "quiz", "adventure" or "deck"
  const id = Number(container.dataset.id);
  if (!id) return;
  if (kind === "deck") {
    await fillDeck(container, id);
    return;
  }
  let quiz = null;
  try {
    quiz = await api.get(`/api/v1/quizzes/${id}`);
  } catch {
    container.innerHTML = `<p class="muted small">${escapeHtml(t("wiki.embed_failed"))}</p>`;
    return;
  }
  container.innerHTML = shell({
    title: quiz.title,
    meta: summary(quiz),
    href: kind === "adventure" ? `/adventures/${id}/play` : `/quizzes/${id}`,
    label: t("wiki.embed_full_page"),
  });
  const body = container.querySelector(".wiki-embed-body");
  whenVisible(container, () => playInline(kind, id, body));
  container.querySelector("[data-embed-open]").addEventListener("click", (event) => {
    event.preventDefault();
    navigate(kind === "adventure" ? `/adventures/${id}/play` : `/quizzes/${id}`);
  });
}

/** Fill every embed placeholder found under `root`. */
export function hydrateEmbeds(root) {
  if (!root) return;
  root.querySelectorAll(".wiki-embed[data-embed]").forEach((container) => {
    if (container.dataset.hydrated === "1") return;
    container.dataset.hydrated = "1";
    fill(container);
  });
}
