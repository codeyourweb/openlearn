// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Wiki chat: a RAG assistant grounded only in the wikis the reader may open. */

import { api } from "../api.js";
import { currentLanguage, t } from "../i18n.js";
import { escapeHtml, toast } from "../ui.js";

const SUGGESTIONS = ["wiki.chat_example_1", "wiki.chat_example_2", "wiki.chat_example_3"];

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
      <div class="gpt-suggestions">
        ${SUGGESTIONS.map(
          (key) =>
            `<button type="button" class="gpt-suggestion" data-suggest="${escapeHtml(t(key))}">
               ${escapeHtml(t(key))}</button>`,
        ).join("")}
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

  input.focus();
  return root;
}
