// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* One deck: its cards, the editor, and the study mode.
 *
 * Study mode deliberately looks like the swipe mode of the questionnaires: one
 * card at a time, a click or a keypress flips it, two buttons say what the
 * learner thought of it. No score, no timer — a revision card asks "did you
 * know", not "how fast".
 */

import { api, uploadImage } from "../api.js";
import { t } from "../i18n.js";
import { markdownToHtml } from "../markdown.js";
import { navigate } from "../router.js";
import { confirmDialog, escapeHtml, toast } from "../ui.js";

let rootEl = null;
let deck = null;
let study = null;
let deckId = null;
let record = [];

function canEdit() {
  return Boolean(deck && deck.can_edit);
}

function renderMarkdown(text) {
  return markdownToHtml(text || "", { pages: {} });
}

//: The shapes a deck can take. Portrait first: it is what a character card is.
const SHAPES = [
  ["2:3", "cards.aspect_2_3"],
  ["3:4", "cards.aspect_3_4"],
  ["1:1", "cards.aspect_1_1"],
  ["3:2", "cards.aspect_3_2"],
  ["16:9", "cards.aspect_16_9"],
];

export function aspectOptions(current = "2:3") {
  return SHAPES.map(
    ([value, key]) =>
      `<option value="${value}"${value === current ? " selected" : ""}>${escapeHtml(t(key))}</option>`,
  ).join("");
}

export function cardFace(card, side) {
  const content = (side === "front" ? card.front_md : card.back_md) || "";
  const text = content.trim();
  const source = side === "front" ? card.image_path : card.back_image_path;
  const picture = source
    ? `<img class="revision-card-image" src="${escapeHtml(source)}" alt="" loading="lazy">`
    : "";
  // Text is optional: a character card is often a picture and nothing else.
  const body = text ? `<div class="revision-card-text">${renderMarkdown(text)}</div>` : "";
  const shape = picture && !text ? " image-only" : "";
  return `<div class="revision-card-body${picture ? " has-image" : ""}${shape}">${picture}${body}</div>`;
}

function cardTile(card, index) {
  return `
    <article class="revision-card" data-card="${card.id}" data-aspect="${escapeHtml(deck.aspect || "2:3")}" tabindex="0">
      <div class="revision-card-inner">
        <div class="revision-card-face revision-card-front">
          <span class="revision-card-index">${index + 1}</span>
          ${cardFace(card, "front")}
        </div>
        <div class="revision-card-face revision-card-back">
          <span class="revision-card-index">${index + 1}</span>
          ${cardFace(card, "back")}
        </div>
      </div>
      ${
        canEdit()
          ? `<div class="revision-card-tools">
               <button class="btn btn-sm btn-ghost" data-edit="${card.id}">${escapeHtml(t("action.edit"))}</button>
               <button class="btn btn-sm btn-ghost btn-danger" data-delete="${card.id}">${escapeHtml(t("action.delete"))}</button>
             </div>`
          : ""
      }
    </article>`;
}

function paintDeck() {
  if (!rootEl || !deck) return;
  const cards = deck.cards || [];
  rootEl.innerHTML = `
    <section class="page deck-page">
      <header class="page-head">
        <div>
          ${
            deck.wiki_id
              ? `<a class="muted small" href="/wiki/${deck.wiki_id}" data-link>← ${escapeHtml(t("cards.back_to_wiki"))}</a>`
              : ""
          }
          <h1>${escapeHtml(deck.title)}</h1>
          <p class="muted">
            ${escapeHtml(`${cards.length} ${cards.length === 1 ? t("cards.card_one") : t("cards.card_many")}`)}
            ${deck.is_public ? `· <span class="pill small ok">${escapeHtml(t("cards.published"))}</span>` : ""}
          </p>
          ${deck.description ? `<p class="muted small">${escapeHtml(deck.description)}</p>` : ""}
        </div>
        <div class="row-wrap end">
          ${cards.length ? `<button class="btn btn-primary" id="deck-study">${escapeHtml(t("cards.study"))}</button>` : ""}
          ${cards.length ? `<a class="btn btn-ghost" href="/api/v1/decks/${deck.id}/sheet.pdf" target="_blank" rel="noopener">${escapeHtml(t("cards.print"))}</a>` : ""}
          ${
            canEdit()
              ? `<label class="field inline shape-picker">
                   <span>${escapeHtml(t("cards.shape"))}</span>
                   <select id="deck-aspect">${aspectOptions(deck.aspect || "2:3")}</select>
                 </label>
                 <button class="btn btn-ghost" id="deck-publish">${escapeHtml(deck.is_public ? t("cards.unpublish") : t("cards.publish"))}</button>
                 <button class="btn btn-ghost btn-danger" id="deck-delete">${escapeHtml(t("action.delete"))}</button>`
              : ""
          }
        </div>
      </header>

      ${
        cards.length
          ? `<div class="revision-grid">${cards.map(cardTile).join("")}</div>`
          : `<div class="empty">
               <h2>${escapeHtml(t("cards.no_cards"))}</h2>
               <p class="muted">${escapeHtml(t("cards.generate_hint"))}</p>
             </div>`
      }

      ${
        canEdit()
          ? `<section class="card deck-editor" id="deck-editor">
               <h2>${escapeHtml(t("cards.add_title"))}</h2>
               <form id="deck-card-form">
                 <input type="hidden" id="deck-card-id" value="">
                 <div class="grid-2">
                   <label class="field">
                     <span>${escapeHtml(t("cards.front"))}</span>
                     <textarea id="deck-front" rows="3" maxlength="4000" placeholder="${escapeHtml(t("cards.front_placeholder"))}"></textarea>
                   </label>
                   <label class="field">
                     <span>${escapeHtml(t("cards.back"))}</span>
                     <textarea id="deck-back" rows="3" maxlength="4000" placeholder="${escapeHtml(t("cards.back_placeholder"))}"></textarea>
                   </label>
                 </div>
                 <div class="row-wrap">
                   <label class="btn btn-sm btn-ghost file-button">
                     ${escapeHtml(t("cards.image"))}
                     <input type="file" id="deck-image" accept="image/png,image/jpeg,image/webp,image/gif" hidden>
                   </label>
                   <span class="muted small" id="deck-image-name"></span>
                   <button type="button" class="btn btn-sm btn-ghost" id="deck-image-clear" hidden>${escapeHtml(t("cards.remove_image"))}</button>
                 </div>
                 <div class="row-wrap">
                   <label class="btn btn-sm btn-ghost file-button">
                     ${escapeHtml(t("cards.back_image"))}
                     <input type="file" id="deck-back-image" accept="image/png,image/jpeg,image/webp,image/gif" hidden>
                   </label>
                   <span class="muted small" id="deck-back-image-name"></span>
                   <button type="button" class="btn btn-sm btn-ghost" id="deck-back-image-clear" hidden>${escapeHtml(t("cards.remove_back_image"))}</button>
                 </div>
                 <div class="row-wrap end mt-2">
                   <button type="button" class="btn btn-ghost" id="deck-card-reset">${escapeHtml(t("action.cancel"))}</button>
                   <button type="submit" class="btn btn-primary">${escapeHtml(t("cards.add"))}</button>
                 </div>
               </form>
               <hr class="sep">
               <div class="row-wrap">
                 <label class="field grow">
                   <span>${escapeHtml(t("cards.append_wiki"))}</span>
                   <select id="deck-append-page"><option value="">…</option></select>
                 </label>
                 <button class="btn btn-ghost" id="deck-append-wiki-go">${escapeHtml(t("cards.generate"))}</button>
               </div>
               <div class="row-wrap">
                 <label class="field grow">
                   <span>${escapeHtml(t("cards.append_quiz"))}</span>
                   <select id="deck-append-quiz"><option value="">…</option></select>
                 </label>
                 <button class="btn btn-ghost" id="deck-append-quiz-go">${escapeHtml(t("cards.generate"))}</button>
               </div>
             </section>`
          : ""
      }
    </section>`;

  rootEl.querySelectorAll(".revision-card").forEach((tile) => {
    const flip = (event) => {
      if (event.target.closest("button")) return;
      tile.classList.toggle("flipped");
    };
    tile.addEventListener("click", flip);
    tile.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        flip(event);
      }
    });
  });

  rootEl.querySelector("#deck-study")?.addEventListener("click", () => navigate(`/cards/${deck.id}/study`));
  rootEl.querySelector("#deck-aspect")?.addEventListener("change", async (event) => {
    try {
      deck = await api.put(`/api/v1/decks/${deck.id}`, { aspect: event.target.value });
      deck.can_edit = true;
      paintDeck();
    } catch (error) {
      toast(error.detail || error.message || t("common.error"), "error");
    }
  });
  rootEl.querySelector("#deck-publish")?.addEventListener("click", async () => {
    try {
      deck = await api.put(`/api/v1/decks/${deck.id}`, { is_public: !deck.is_public });
      deck.can_edit = true;
      paintDeck();
    } catch (error) {
      toast(error.detail || error.message || t("common.error"), "error");
    }
  });
  rootEl.querySelector("#deck-delete")?.addEventListener("click", async () => {
    if (!(await confirmDialog(t("cards.delete_confirm")))) return;
    try {
      await api.delete(`/api/v1/decks/${deck.id}`);
      toast(t("cards.deleted"), "success");
      navigate("/cards");
    } catch (error) {
      toast(error.detail || error.message || t("common.error"), "error");
    }
  });

  bindEditor();
}

function bindEditor() {
  if (!canEdit()) return;
  const form = rootEl.querySelector("#deck-card-form");
  const front = rootEl.querySelector("#deck-front");
  const back = rootEl.querySelector("#deck-back");
  const hiddenId = rootEl.querySelector("#deck-card-id");
  const imageInput = rootEl.querySelector("#deck-image");
  const imageName = rootEl.querySelector("#deck-image-name");
  const imageClear = rootEl.querySelector("#deck-image-clear");
  const backImageInput = rootEl.querySelector("#deck-back-image");
  const backImageName = rootEl.querySelector("#deck-back-image-name");
  const backImageClear = rootEl.querySelector("#deck-back-image-clear");
  let imagePath = null;
  let backImagePath = null;

  const reset = () => {
    form.reset();
    hiddenId.value = "";
    imagePath = null;
    backImagePath = null;
    imageName.textContent = "";
    backImageName.textContent = "";
    imageClear.hidden = true;
    backImageClear.hidden = true;
    front.focus();
  };
  rootEl.querySelector("#deck-card-reset")?.addEventListener("click", reset);

  imageInput?.addEventListener("change", async () => {
    const file = imageInput.files?.[0];
    if (!file) return;
    try {
      const stored = await uploadImage(file, null, "/api/v1/uploads/image");
      imagePath = stored.path;
      imageName.textContent = stored.path.split("/").pop();
      imageClear.hidden = false;
    } catch (error) {
      toast(error.detail || error.message || t("common.error"), "error");
    }
  });
  imageClear?.addEventListener("click", () => {
    imagePath = null;
    imageName.textContent = "";
    imageClear.hidden = true;
    if (imageInput) imageInput.value = "";
  });

  backImageInput?.addEventListener("change", async () => {
    const file = backImageInput.files?.[0];
    if (!file) return;
    try {
      const stored = await uploadImage(file, null, "/api/v1/uploads/image");
      backImagePath = stored.path;
      backImageName.textContent = stored.path.split("/").pop();
      backImageClear.hidden = false;
    } catch (error) {
      toast(error.detail || error.message || t("common.error"), "error");
    }
  });
  backImageClear?.addEventListener("click", () => {
    backImagePath = null;
    backImageName.textContent = "";
    backImageClear.hidden = true;
    if (backImageInput) backImageInput.value = "";
  });

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      front_md: front.value.trim(),
      back_md: back.value.trim(),
      image_path: imagePath,
      back_image_path: backImagePath,
    };
    if (!payload.front_md && !payload.image_path) {
      toast(t("cards.need_face"), "error");
      return;
    }
    try {
      if (hiddenId.value) {
        await api.put(`/api/v1/decks/${deck.id}/cards/${hiddenId.value}`, payload);
      } else {
        await api.post(`/api/v1/decks/${deck.id}/cards`, payload);
      }
      toast(t("cards.saved"), "success");
      await loadDeck();
    } catch (error) {
      toast(error.detail || error.message || t("common.error"), "error");
    }
  });

  rootEl.querySelectorAll("[data-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      const card = (deck.cards || []).find((row) => String(row.id) === button.dataset.edit);
      if (!card) return;
      hiddenId.value = String(card.id);
      front.value = card.front_md || "";
      back.value = card.back_md || "";
      imagePath = card.image_path || null;
      imageName.textContent = imagePath ? imagePath.split("/").pop() : "";
      imageClear.hidden = !imagePath;
      backImagePath = card.back_image_path || null;
      backImageName.textContent = backImagePath ? backImagePath.split("/").pop() : "";
      backImageClear.hidden = !backImagePath;
      rootEl.querySelector("#deck-editor")?.scrollIntoView({ behavior: "smooth", block: "center" });
      front.focus();
    });
  });

  rootEl.querySelectorAll("[data-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!(await confirmDialog(t("cards.delete_card_confirm")))) return;
      try {
        await api.delete(`/api/v1/decks/${deck.id}/cards/${button.dataset.delete}`);
        await loadDeck();
      } catch (error) {
        toast(error.detail || error.message || t("common.error"), "error");
      }
    });
  });

  fillAppendSources();

  rootEl.querySelector("#deck-append-wiki-go")?.addEventListener("click", async () => {
    const pageId = rootEl.querySelector("#deck-append-page")?.value;
    if (!pageId) return;
    try {
      const payload = await api.post(`/api/v1/decks/${deck.id}/add-from-wiki`, {
        page_id: Number(pageId),
      });
      toast(`${payload.added} ${t("cards.added_count")}`, "success");
      await loadDeck();
    } catch (error) {
      toast(error.detail || error.message || t("common.error"), "error");
    }
  });
  rootEl.querySelector("#deck-append-quiz-go")?.addEventListener("click", async () => {
    const quizId = rootEl.querySelector("#deck-append-quiz")?.value;
    if (!quizId) return;
    try {
      const payload = await api.post(`/api/v1/decks/${deck.id}/add-from-quiz`, {
        quiz_id: Number(quizId),
      });
      toast(`${payload.added} ${t("cards.added_count")}`, "success");
      await loadDeck();
    } catch (error) {
      toast(error.detail || error.message || t("common.error"), "error");
    }
  });
}

async function fillAppendSources() {
  const pageSelect = rootEl.querySelector("#deck-append-page");
  const quizSelect = rootEl.querySelector("#deck-append-quiz");
  if (!pageSelect || !quizSelect) return;
  try {
    const list = await api.get("/api/v1/wiki?limit=100&mine=true");
    const options = [];
    for (const wiki of Array.isArray(list) ? list : []) {
      // The catalogue carries counts, not pages: ask for the menu of each wiki.
      const detail = await api.get(`/api/v1/wiki/${wiki.id}`);
      for (const page of detail.pages || []) {
        options.push(
          `<option value="${page.id}">${escapeHtml(`${wiki.title} — ${page.title}`)}</option>`,
        );
      }
    }
    pageSelect.innerHTML = options.join("");
    if (!pageSelect.innerHTML.trim()) {
      pageSelect.innerHTML = `<option value="">${escapeHtml(t("cards.no_pages"))}</option>`;
    }
  } catch {
    pageSelect.innerHTML = `<option value="">${escapeHtml(t("cards.no_pages"))}</option>`;
  }
  try {
    const quizzes = await api.get("/api/v1/quizzes/mine");
    const list = quizzes.items || quizzes || [];
    quizSelect.innerHTML = list.length
      ? list.map((quiz) => `<option value="${quiz.id}">${escapeHtml(quiz.title)}</option>`).join("")
      : `<option value="">${escapeHtml(t("cards.no_quizzes"))}</option>`;
  } catch {
    quizSelect.innerHTML = `<option value="">${escapeHtml(t("cards.no_quizzes"))}</option>`;
  }
}

async function loadDeck() {
  deck = await api.get(`/api/v1/decks/${deckId}`);
  paintDeck();
}

export async function renderDeck({ id }) {
  deckId = Number(id);
  const root = document.createElement("section");
  root.className = "page";
  root.innerHTML = `<p class="muted">…</p>`;
  rootEl = root;
  try {
    deck = await api.get(`/api/v1/decks/${deckId}`);
    paintDeck();
  } catch (error) {
    root.innerHTML = `<div class="empty"><h2>${escapeHtml(t("cards.missing"))}</h2>
      <p class="muted">${escapeHtml(error.detail || error.message || "")}</p>
      <a class="btn mt-2" data-link href="/cards">${escapeHtml(t("cards.title"))}</a></div>`;
  }
  return root;
}

/* ------------------------------------------------------------------------- */
/* Study mode                                                                 */
/* ------------------------------------------------------------------------- */
function paintStudy(summary = null) {
  if (!rootEl) return;
  const cards = (study && study.cards) || [];
  if (summary) {
    const known = summary.filter((row) => row.known).length;
    rootEl.innerHTML = `
      <section class="page deck-study-page">
        <header class="page-head"><h1>${escapeHtml(study.title)}</h1></header>
        <div class="card study-summary">
          <p class="study-score">${known} / ${summary.length}</p>
          <p class="muted">${escapeHtml(t("cards.done_hint"))}</p>
          <div class="row-wrap end">
            <a class="btn btn-ghost" data-link href="/cards/${study.id}">${escapeHtml(t("cards.back_to_deck"))}</a>
            <button class="btn btn-primary" id="study-again">${escapeHtml(t("cards.restart"))}</button>
          </div>
        </div>
      </section>`;
    rootEl.querySelector("#study-again")?.addEventListener("click", () => startStudy());
    return;
  }
  if (!cards.length) {
    rootEl.innerHTML = `<div class="empty"><h2>${escapeHtml(t("cards.no_cards"))}</h2></div>`;
    return;
  }
  const card = cards[0];
  rootEl.innerHTML = `
    <section class="page deck-study-page">
      <header class="study-head">
        <span class="muted">${escapeHtml(
          `${t("cards.progress")} ${study.total - cards.length + 1} / ${study.total}`,
        )}</span>
        <a class="btn btn-sm btn-ghost" data-link href="/cards/${study.id}">${escapeHtml(t("action.close"))}</a>
      </header>
      <article class="study-card" id="study-card" data-aspect="${escapeHtml(study.aspect || "2:3")}" tabindex="0">
        <div class="revision-card-face revision-card-front">
          ${cardFace(card, "front")}
        </div>
        <div class="revision-card-face revision-card-back" hidden>
          ${cardFace(card, "back")}
        </div>
      </article>
      <p class="muted small center">${escapeHtml(t("cards.flip_hint"))}</p>
      <div class="study-actions" hidden id="study-actions">
        <button class="btn btn-lg btn-ghost" id="study-again">${escapeHtml(t("cards.again"))}</button>
        <button class="btn btn-lg btn-primary" id="study-known">${escapeHtml(t("cards.known"))}</button>
      </div>
    </section>`;

  const surface = rootEl.querySelector("#study-card");
  const backFace = surface.querySelector(".revision-card-back");
  const actions = rootEl.querySelector("#study-actions");
  let flipped = false;

  const flip = () => {
    if (flipped) return;
    flipped = true;
    backFace.hidden = false;
    surface.classList.add("flipped");
    actions.hidden = false;
  };
  surface.addEventListener("click", flip);
  surface.addEventListener("keydown", (event) => {
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      flip();
    }
  });
  surface.focus();

  const answer = async (known) => {
    record.push({ card_id: card.id, known });
    study.cards.shift();
    try {
      await api.post(`/api/v1/decks/${study.id}/review`, { card_id: card.id, known });
    } catch {
      /* A lost box update must not stop the revision session. */
    }
    if (!study.cards.length) paintStudy(record);
    else paintStudy();
  };
  rootEl.querySelector("#study-known")?.addEventListener("click", () => answer(true));
  rootEl.querySelector("#study-again")?.addEventListener("click", () => answer(false));

  const keyHandler = (event) => {
    if (event.target.closest("input, textarea")) return;
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      flip();
      return;
    }
    if (!flipped) return;
    if (event.key === "ArrowRight") answer(true);
    if (event.key === "ArrowLeft") answer(false);
  };
  document.addEventListener("keydown", keyHandler);
  // One handler at a time: re-painting the page must not stack them up.
  rootEl._studyCleanup = () => document.removeEventListener("keydown", keyHandler);
}

async function startStudy() {
  record = [];
  const payload = await api.get(`/api/v1/decks/${deckId}/study`);
  study = { ...payload, cards: payload.cards.slice(), total: payload.cards.length };
  paintStudy();
}

export async function renderDeckStudy({ id }) {
  deckId = Number(id);
  const root = document.createElement("section");
  root.className = "page";
  root.innerHTML = `<p class="muted">…</p>`;
  rootEl = root;
  try {
    await startStudy();
  } catch (error) {
    root.innerHTML = `<div class="empty"><h2>${escapeHtml(t("cards.missing"))}</h2>
      <p class="muted">${escapeHtml(error.detail || error.message || "")}</p></div>`;
  }
  return root;
}
