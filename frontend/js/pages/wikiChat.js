// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Wiki chat: a RAG assistant grounded only in the wikis the reader may open. */

import { api } from "../api.js";
import { currentLanguage, t } from "../i18n.js";
import { escapeHtml, toast } from "../ui.js";

const GENERIC_SUGGESTIONS = [
  "wiki.chat_example_1",
  "wiki.chat_example_2",
  "wiki.chat_example_3",
  "wiki.chat_example_4",
  "wiki.chat_example_5",
  "wiki.chat_example_6",
];

/** Three questions out of six: the same three every visit read like a fixture. */
function pickGenericSuggestions(count = 3) {
  const pool = [...GENERIC_SUGGESTIONS];
  for (let index = pool.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(Math.random() * (index + 1));
    [pool[index], pool[swap]] = [pool[swap], pool[index]];
  }
  return pool.slice(0, count).map((key) => t(key));
}

function suggestionButtons(questions) {
  return questions
    .map(
      (question) =>
        `<button type="button" class="gpt-suggestion" data-suggest="${escapeHtml(question)}">${escapeHtml(question)}</button>`,
    )
    .join("");
}

function paragraph(text) {
  return escapeHtml(text)
    .split(/\n{2,}/)
    .map((block) => `<p>${block.replace(/\n/g, "<br />")}</p>`)
    .join("");
}

function messageMarkup(message) {
  if (message.role === "user") {
    return `<div class="gpt-turn is-user"><div class="gpt-body"><div class="gpt-bubble">${paragraph(message.content)}</div></div></div>`;
  }
  const sources = message.sources || [];
  return `
    <div class="gpt-turn is-assistant">
      <div class="gpt-avatar" aria-hidden="true">◆</div>
      <div class="gpt-body">
        ${paragraph(message.content)}
        ${
          sources.length
            ? `<div class="gpt-sources">
                 <span class="gpt-sources-label">${escapeHtml(t("wiki.chat_sources"))}</span>
                 ${sources
                   .map(
                     (source, index) =>
                       `<a class="gpt-source" data-link href="/wiki/${source.wiki_id}/p/${encodeURIComponent(source.slug)}"
                           title="${escapeHtml(source.wiki_title)}${source.heading ? ` · ${escapeHtml(source.heading)}` : ""}">
                          <span class="gpt-source-num">${index + 1}</span>${escapeHtml(source.title)}${
                            source.heading ? `<span class="gpt-source-head">${escapeHtml(source.heading)}</span>` : ""
                          }
                        </a>`,
                   )
                   .join("")}
               </div>`
            : ""
        }
      </div>
    </div>`;
}

export async function renderWikiChat({ query }) {
  const root = document.createElement("section");
  root.className = "gpt-shell";

  const empty = `
    <div class="gpt-empty">
      <h1><span aria-hidden="true">✨</span> ${escapeHtml(t("wiki.chat_title"))}</h1>
      <p class="muted">${escapeHtml(t("wiki.chat_subtitle"))}</p>
      <div class="gpt-suggestions" id="gpt-suggestions">
        ${suggestionButtons(pickGenericSuggestions())}
      </div>
      <p class="muted small">${escapeHtml(t("wiki.chat_scope"))}</p>
    </div>`;

  root.innerHTML = `
    <div class="gpt-log" id="gpt-log" aria-live="polite">${empty}</div>
    <form class="gpt-composer" id="gpt-form">
      <textarea id="gpt-input" rows="1" maxlength="2000"
        placeholder="${escapeHtml(t("wiki.chat_placeholder"))}"
        aria-label="${escapeHtml(t("wiki.chat_placeholder"))}"></textarea>
      <button class="gpt-send" type="submit" aria-label="${escapeHtml(t("wiki.chat_send"))}"
              title="${escapeHtml(t("wiki.chat_send"))}">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 19V5" /><path d="M5 12l7-7 7 7" />
        </svg>
      </button>
      <p class="gpt-hint muted small">${escapeHtml(t("wiki.chat_hint"))}</p>
    </form>
  `;

  const log = root.querySelector("#gpt-log");
  const form = root.querySelector("#gpt-form");
  const input = root.querySelector("#gpt-input");
  const send = root.querySelector(".gpt-send");
  const chat = { id: null, wikiIds: query && query.wiki ? [Number(query.wiki)] : [], started: false };

  const autoGrow = () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(200, input.scrollHeight)}px`;
  };

  const scrollDown = () => {
    log.scrollTop = log.scrollHeight;
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  };

  const append = (markup) => {
    if (!chat.started) {
      log.innerHTML = "";
      chat.started = true;
    }
    const holder = document.createElement("div");
    holder.innerHTML = markup;
    while (holder.firstElementChild) log.append(holder.firstElementChild);
    scrollDown();
  };

  const ask = async (question) => {
    if (question.length < 2) return;
    append(messageMarkup({ role: "user", content: question }));
    input.value = "";
    autoGrow();
    send.disabled = true;

    const waiting = document.createElement("div");
    waiting.className = "gpt-turn is-assistant is-thinking";
    waiting.innerHTML = `
      <div class="gpt-avatar" aria-hidden="true">◆</div>
      <div class="gpt-body"><span class="gpt-dots" aria-label="${escapeHtml(t("wiki.chat_thinking"))}">
        <i></i><i></i><i></i></span></div>`;
    log.append(waiting);
    scrollDown();

    try {
      const answer = await api.post("/api/v1/wiki/ai/chat", {
        question,
        chat_id: chat.id,
        wiki_ids: chat.wikiIds,
        language: currentLanguage(),
      });
      chat.id = answer.chat_id;
      waiting.remove();
      append(messageMarkup({ role: "assistant", content: answer.answer, sources: answer.sources }));
    } catch (error) {
      waiting.remove();
      toast(error.detail || t("error.generic"), "error");
    } finally {
      send.disabled = false;
      input.focus();
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    ask(input.value.trim());
  });

  const syncSend = () => {
    send.disabled = input.value.trim().length < 2;
  };
  input.addEventListener("input", () => {
    autoGrow();
    syncSend();
  });
  syncSend();
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      ask(input.value.trim());
    }
  });

  root.addEventListener("click", (event) => {
    const suggestion = event.target.closest("[data-suggest]");
    if (suggestion) ask(suggestion.dataset.suggest);
  });

  // Scoped to a single wiki: ask that wiki what it talks about. The server reads
  // the headings of its published pages, so the three buttons name real sections
  // instead of questions that could belong to any other wiki.
  const scopedWiki = chat.wikiIds[0];
  if (scopedWiki) {
    api
      .get(
        `/api/v1/wiki/ai/suggestions?wiki_id=${scopedWiki}&language=${encodeURIComponent(currentLanguage())}`,
      )
      .then((data) => {
        const questions = (data.suggestions || []).slice(0, 4);
        const holder = root.querySelector("#gpt-suggestions");
        if (holder && questions.length && !chat.started) holder.innerHTML = suggestionButtons(questions);
      })
      .catch(() => {
        /* the generic questions stay */
      });
  }

  input.focus();
  return root;
}
