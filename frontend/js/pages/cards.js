// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Revision decks — the catalogue, always anchored to a wiki.
 *
 * A deck of revision cards is born from written material, so creating one
 * always names the wiki it belongs to: the cards feed that wiki's pages and the
 * wiki is where a reader finds them. Opened from a wiki (`/cards?wiki=ID`) the
 * page shows that wiki's decks only and keeps the parent wiki in the title;
 * opened on its own it asks which wiki the new deck belongs to.
 */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { navigate } from "../router.js";
import { isLoggedIn } from "../store.js";
import { aspectOptions } from "./cardsDeck.js";
import { escapeHtml, pagerHtml, bindPager, setBusy, toast } from "../ui.js";

const PAGE_SIZE = 12;

const state = {
  scope: "public",
  decks: [],
  loading: true,
  error: "",
  wikiId: null,
  wikiTitle: "",
  wikis: [],
  page: 0,
  total: 0,
};
// The section the router puts on screen; paint() fills it in place so that a
// reload never fights the router's own `app.innerHTML = ""`.
let rootEl = null;

function sourceBadge(deck) {
  if (deck.wiki_id) return t("cards.source_wiki");
  if (deck.quiz_id) return t("cards.source_quiz");
  return t("cards.source_manual");
}

function deckCard(deck) {
  const count = deck.card_count || 0;
  return `
    <a class="card deck-card" data-link href="/cards/${deck.id}">
      <div class="deck-card-head">
        <h2>${escapeHtml(deck.title)}</h2>
        <span class="pill small">${escapeHtml(sourceBadge(deck))}</span>
      </div>
      ${deck.description ? `<p class="muted small">${escapeHtml(deck.description)}</p>` : ""}
      <p class="deck-card-meta">
        <span>${escapeHtml(`${count} ${count === 1 ? t("cards.card_one") : t("cards.card_many")}`)}</span>
        ${deck.is_public ? `<span class="pill small ok">${escapeHtml(t("cards.published"))}</span>` : ""}
      </p>
    </a>`;
}

async function load(scope, page = 0) {
  state.scope = scope;
  state.page = page;
  state.loading = true;
  paint();
  try {
    const params = new URLSearchParams();
    if (state.wikiId) params.set("wiki_id", String(state.wikiId));
    else if (scope === "mine") params.set("mine", "true");
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(page * PAGE_SIZE));
    const meta = await api.getMeta(`/api/v1/decks?${params.toString()}`);
    state.decks = meta.data.items || meta.data || [];
    state.total = Number(meta.headers.get("X-Total-Count") || state.decks.length);
    state.error = "";
  } catch (error) {
    state.error = error.detail || error.message || t("common.error");
  } finally {
    state.loading = false;
    paint();
  }
}

async function loadWikis() {
  if (!isLoggedIn()) return;
  try {
    const list = await api.get("/api/v1/wiki?limit=100&mine=true");
    state.wikis = Array.isArray(list) ? list : [];
  } catch {
    state.wikis = [];
  }
}

async function createDeck(title, aspect, wikiId) {
  const deck = await api.post("/api/v1/decks", {
    title: title.trim(),
    aspect: aspect || "2:3",
    wiki_id: wikiId,
  });
  toast(t("cards.created"), "success");
  navigate(`/cards/${deck.id}`);
}

async function generateFrom(source, id) {
  const body = source === "wiki" ? { page_id: Number(id) } : { quiz_id: Number(id) };
  const deck = await api.post("/api/v1/decks/from-source", body);
  toast(`${deck.added} ${deck.added === 1 ? t("cards.card_one") : t("cards.card_many")}`, "success");
  navigate(`/cards/${deck.id}`);
}

function generatorPanel() {
  return `
    <dialog class="modal" id="deck-source">
      <form method="dialog" class="modal-body">
        <h2>${escapeHtml(t("cards.from_source_title"))}</h2>
        <fieldset class="field">
          <legend>${escapeHtml(t("cards.source_kind"))}</legend>
          <label class="check">
            <input type="radio" name="deck-source-kind" value="wiki" checked>
            <span>${escapeHtml(t("cards.from_wiki"))}</span>
          </label>
          <label class="check">
            <input type="radio" name="deck-source-kind" value="quiz">
            <span>${escapeHtml(t("cards.from_quiz"))}</span>
          </label>
        </fieldset>
        <label class="field" data-source-panel="wiki">
          <span>${escapeHtml(t("cards.source_page"))}</span>
          <select id="deck-source-wiki"><option value="">${escapeHtml(t("cards.choose_source"))}</option></select>
        </label>
        <label class="field" data-source-panel="quiz" hidden>
          <span>${escapeHtml(t("cards.source_quiz"))}</span>
          <select id="deck-source-quiz"><option value="">${escapeHtml(t("cards.choose_source"))}</option></select>
        </label>
        <p class="muted small">${escapeHtml(t("cards.from_source_hint"))}</p>
        <div class="row-wrap end">
          <button class="btn btn-ghost" value="cancel" formnovalidate>${escapeHtml(t("action.cancel"))}</button>
          <button class="btn btn-primary" id="deck-source-go" value="ok" disabled>${escapeHtml(t("cards.generate"))}</button>
        </div>
      </form>
    </dialog>`;
}

/** The two sources are exclusive, and nothing is pre-selected.
 *
 * Both lists used to arrive pre-filled, and the generator took whichever value
 * came first: choosing a wiki page and pressing Generate could quietly build the
 * deck from an unrelated quiz. A source is now picked explicitly, the matching
 * list starts empty, and Generate stays disabled until something is chosen.
 */
function wireSourceKind(app) {
  const kinds = app.querySelectorAll('[name="deck-source-kind"]');
  const selects = {
    wiki: app.querySelector("#deck-source-wiki"),
    quiz: app.querySelector("#deck-source-quiz"),
  };
  const go = app.querySelector("#deck-source-go");
  const selectedKind = () =>
    [...kinds].find((input) => input.checked)?.value || "wiki";
  const refresh = () => {
    const kind = selectedKind();
    app.querySelectorAll("[data-source-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.sourcePanel !== kind;
    });
    if (go) go.disabled = !selects[kind]?.value;
  };
  kinds.forEach((input) => input.addEventListener("change", refresh));
  Object.values(selects).forEach((select) => select?.addEventListener("change", refresh));
  refresh();
  return { selectedKind, selects, refresh };
}

async function fillSources() {
  const wikiSelect = document.getElementById("deck-source-wiki");
  const quizSelect = document.getElementById("deck-source-quiz");
  if (!wikiSelect || !quizSelect) return;
  try {
    const list = await api.get("/api/v1/wiki?limit=100&mine=true");
    const options = [];
    for (const wiki of Array.isArray(list) ? list : []) {
      const detail = await api.get(`/api/v1/wiki/${wiki.id}`);
      for (const page of detail.pages || []) {
        options.push(`<option value="${page.id}">${escapeHtml(`${wiki.title} — ${page.title}`)}</option>`);
      }
    }
    wikiSelect.innerHTML = `<option value="">${escapeHtml(t("cards.choose_source"))}</option>${options.join("")}`;
    if (!options.length) {
      wikiSelect.innerHTML = `<option value="">${escapeHtml(t("cards.no_pages"))}</option>`;
    }
  } catch {
    wikiSelect.innerHTML = `<option value="">${escapeHtml(t("cards.no_pages"))}</option>`;
  }
  try {
    const quizzes = await api.get("/api/v1/quizzes/mine?limit=100");
    const list = quizzes.items || quizzes || [];
    quizSelect.innerHTML = `<option value="">${escapeHtml(t("cards.choose_source"))}</option>${
      list.length
        ? list.map((quiz) => `<option value="${quiz.id}">${escapeHtml(quiz.title)}</option>`).join("")
        : ""
    }`;
    if (!list.length) {
      quizSelect.innerHTML = `<option value="">${escapeHtml(t("cards.no_quizzes"))}</option>`;
    }
  } catch {
    quizSelect.innerHTML = `<option value="">${escapeHtml(t("cards.no_quizzes"))}</option>`;
  }
}

function wikiPicker() {
  if (state.wikiId) {
    return `
      <label class="field">
        <span>${escapeHtml(t("cards.belongs_to"))}</span>
        <input class="input" type="text" value="${escapeHtml(state.wikiTitle)}" readonly />
      </label>`;
  }
  const options = state.wikis
    .map((wiki) => `<option value="${wiki.id}">${escapeHtml(wiki.title)}</option>`)
    .join("");
  return `
    <label class="field">
      <span>${escapeHtml(t("cards.belongs_to"))}</span>
      <select id="deck-new-wiki" required>
        <option value="">${escapeHtml(t("cards.choose_wiki"))}</option>
        ${options}
      </select>
    </label>`;
}

function paint() {
  const app = rootEl;
  if (!app) return;
  const signedIn = isLoggedIn();
  const body = state.loading
    ? `<p class="muted">…</p>`
    : state.error
      ? `<div class="banner warn">${escapeHtml(state.error)}</div>`
      : state.decks.length
        ? `<div class="deck-grid">${state.decks.map(deckCard).join("")}</div>`
        : `<div class="empty">
             <h2>${escapeHtml(t("cards.empty"))}</h2>
             <p class="muted">${escapeHtml(t("cards.empty_hint"))}</p>
           </div>`;

  const title = state.wikiId ? state.wikiTitle || t("cards.title") : t("cards.title");
  const subtitle = state.wikiId ? t("cards.wiki_subtitle") : t("cards.subtitle");

  app.innerHTML = `
    <section class="page cards-page">
      <header class="page-head">
        <div>
          ${
            state.wikiId
              ? `<a class="muted small" href="/wiki/${state.wikiId}" data-link>← ${escapeHtml(t("cards.back_to_wiki"))}</a>`
              : ""
          }
          <h1>${escapeHtml(title)}</h1>
          <p class="muted">${escapeHtml(subtitle)}</p>
        </div>
        ${
          signedIn
            ? `<div class="row-wrap end">
                 <button class="btn btn-ghost" id="deck-from-source">${escapeHtml(t("cards.from_source"))}</button>
                 <button class="btn btn-primary" id="deck-new">${escapeHtml(t("cards.new"))}</button>
               </div>`
            : ""
        }
      </header>
      ${
        signedIn
          ? `<form class="card deck-new-form" id="deck-new-form" hidden>
               <div class="grid-2">
                 <label class="field">
                   <span>${escapeHtml(t("cards.deck_title"))}</span>
                   <input type="text" id="deck-new-title" maxlength="160" placeholder="${escapeHtml(t("cards.deck_placeholder"))}" required>
                 </label>
                 ${wikiPicker()}
                 <label class="field">
                   <span>${escapeHtml(t("cards.shape"))}</span>
                   <select id="deck-new-aspect">${aspectOptions()}</select>
                 </label>
               </div>
               <div class="row-wrap end">
                 <button type="button" class="btn btn-ghost" id="deck-new-cancel">${escapeHtml(t("action.cancel"))}</button>
                 <button type="submit" class="btn btn-primary">${escapeHtml(t("action.create"))}</button>
               </div>
             </form>`
          : ""
      }
      ${
        signedIn && !state.wikiId
          ? `<div class="tabs" role="tablist">
               <button class="tab" data-scope="public" role="tab">${escapeHtml(t("cards.public"))}</button>
               <button class="tab" data-scope="mine" role="tab">${escapeHtml(t("cards.mine"))}</button>
             </div>`
          : ""
      }
      ${body}
      <div id="deck-pager" class="pager-slot"></div>
      ${signedIn ? generatorPanel() : ""}
    </section>`;

  app.querySelectorAll("[data-scope]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.scope === state.scope);
    button.setAttribute("aria-selected", String(button.dataset.scope === state.scope));
    button.addEventListener("click", () => load(button.dataset.scope, 0));
  });

  const pager = app.querySelector("#deck-pager");
  if (pager) {
    pager.innerHTML = pagerHtml(state.page, state.total, PAGE_SIZE);
    bindPager(pager, (next) => load(state.scope, next));
  }

  const newButton = app.querySelector("#deck-new");
  if (newButton) {
    newButton.addEventListener("click", async () => {
      const form = app.querySelector("#deck-new-form");
      form.hidden = !form.hidden;
      if (!form.hidden) {
        if (!state.wikiId) await loadWikis();
        // The picker was painted before the wikis were known: refill it.
        if (!state.wikiId) {
          const select = app.querySelector("#deck-new-wiki");
          if (select && select.options.length <= 1) {
            select.innerHTML = `<option value="">${escapeHtml(t("cards.choose_wiki"))}</option>${state.wikis
              .map((wiki) => `<option value="${wiki.id}">${escapeHtml(wiki.title)}</option>`)
              .join("")}`;
          }
        }
        form.querySelector("input").focus();
      }
    });
  }
  app.querySelector("#deck-new-cancel")?.addEventListener("click", () => {
    app.querySelector("#deck-new-form").hidden = true;
  });
  app.querySelector("#deck-new-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = app.querySelector("#deck-new-title");
    if (!input.value.trim()) return;
    const picked = state.wikiId ? String(state.wikiId) : app.querySelector("#deck-new-wiki")?.value;
    if (!picked) {
      toast(t("cards.choose_wiki"), "error");
      return;
    }
    const button = event.submitter;
    setBusy(button, true);
    try {
      await createDeck(input.value, app.querySelector("#deck-new-aspect")?.value, Number(picked));
    } catch (error) {
      setBusy(button, false);
      toast(error.detail || error.message || t("common.error"), "error");
    }
  });

  const sourceButton = app.querySelector("#deck-from-source");
  if (sourceButton) {
    sourceButton.addEventListener("click", async () => {
      const dialog = app.querySelector("#deck-source");
      dialog.showModal();
      await fillSources();
    });
  }
  const dialog = app.querySelector("#deck-source");
  if (dialog) {
    const sourceWiring = wireSourceKind(app);
    dialog.addEventListener("close", async () => {
      if (dialog.returnValue !== "ok") return;
      const kind = sourceWiring.selectedKind();
      // Only the list of the chosen source is read: the other one is not a
      // fallback, it is a different intent.
      const value = sourceWiring.selects[kind]?.value;
      if (!value) {
        toast(t("cards.choose_source"), "info");
        return;
      }
      try {
        await generateFrom(kind, value);
      } catch (error) {
        toast(error.detail || error.message || t("common.error"), "error");
      }
    });
  }
}

export async function renderCards({ query } = {}) {
  const root = document.createElement("section");
  root.className = "page";
  rootEl = root;
  root.innerHTML = `<p class="muted">…</p>`;
  state.wikiId = query && query.wiki ? Number(query.wiki) || null : null;
  state.page = 0;
  state.decks = [];
  if (state.wikiId) {
    // The parent wiki gives the deck its home: show where we are.
    try {
      const wiki = await api.get(`/api/v1/wiki/${state.wikiId}`);
      state.wikiTitle = wiki.title || "";
    } catch {
      state.wikiTitle = "";
    }
  }
  // The page paints itself: load() calls paint() once the decks are in.
  load(state.scope, 0);
  return root;
}
