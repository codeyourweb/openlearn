// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/*
 * Creating a story, in two steps, like every other format.
 *
 * The first screen asks how the story is made: by hand on the canvas, or
 * written whole by the model and then edited. The second screen is the model's
 * brief. A generated story is saved as an ordinary draft quiz, so the editor is
 * the same one as for a hand-written story — nothing is locked behind the AI.
 */

import { api } from "../api.js";
import { LANGUAGES, currentLanguage, t } from "../i18n.js";
import { navigate } from "../router.js";
import { isLoggedIn } from "../store.js";
import { escapeHtml, toast } from "../ui.js";

function escapeAttr(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function card({ href, badge, icon, title, lead, cta }) {
  return `
    <a class="mode-card" href="${escapeAttr(href)}" data-link aria-label="${escapeAttr(title)}">
      <span class="mode-card-badge">${badge}</span>
      <span class="mode-card-icon">${icon}</span>
      <h2>${title}</h2>
      <p class="mode-card-lead">${lead}</p>
      <span class="mode-card-cta">${t(cta)}
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M5 12h13"></path><path d="M12.5 5.5L19 12l-6.5 6.5"></path>
        </svg>
      </span>
    </a>`;
}

/** Step 1: build the story by hand, or have it written? */
export async function renderAdventureMethod() {
  const root = document.createElement("div");
  if (!isLoggedIn()) {
    navigate(`/login?next=${encodeURIComponent("/adventures/new")}`, { replace: true });
    return root;
  }

  let aiAvailable = false;
  try {
    const status = await api.get("/api/v1/ai/status");
    aiAvailable = Boolean(status.available);
  } catch {
    /* AI is optional: the manual card stands alone rather than broken */
  }

  const aiCard = aiAvailable
    ? card({
        href: "/adventures/new/ai",
        badge: t("new_quiz.method_ai"),
        icon: `<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor"
                 stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                 <path d="M12 3l1.8 4.6L18.5 9l-4.7 1.4L12 15l-1.8-4.6L5.5 9l4.7-1.4z"></path>
                 <path d="M17.5 15.5l.9 2.3 2.3.9-2.3.9-.9 2.3-.9-2.3-2.3-.9 2.3-.9z"></path>
               </svg>`,
        title: t("new_quiz.method_ai"),
        lead: t("new_quiz.method_ai_desc"),
        cta: "new_quiz.start",
      })
    : "";

  root.innerHTML = `
    <section class="new-quiz">
      <header class="new-quiz-head">
        <a class="btn btn-quiet btn-sm" href="/quizzes/new" data-link>← ${t("new_quiz.back")}</a>
        <h1 class="mt-1">${t("new_quiz.method_title")}</h1>
        <p>${t("new_quiz.method_lede")}</p>
        <p class="badge">${t("new_quiz.story")}</p>
      </header>
      <div class="mode-grid mode-grid-two">
        ${card({
          href: "/adventures/new/manual",
          badge: t("new_quiz.method_manual"),
          icon: `<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor"
                   stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                   <path d="M4 20l4-1 9.5-9.5a2.1 2.1 0 0 0-3-3L5 16z"></path>
                   <path d="M13.5 5.5l3 3"></path>
                 </svg>`,
          title: t("new_quiz.method_manual"),
          lead: t("new_quiz.method_manual_desc"),
          cta: "new_quiz.start",
        })}
        ${aiCard}
      </div>
      ${aiAvailable ? "" : `<p class="new-quiz-foot muted small">${t("new_quiz.method_ai_unavailable")}</p>`}
    </section>`;

  return root;
}

/** Step 2: the brief given to the model. */
export async function renderAdventureAi() {
  const root = document.createElement("div");
  if (!isLoggedIn()) {
    navigate(`/login?next=${encodeURIComponent("/adventures/new/ai")}`, { replace: true });
    return root;
  }

  root.innerHTML = `
    <section class="new-quiz">
      <header class="new-quiz-head">
        <a class="btn btn-quiet btn-sm" href="/adventures/new" data-link>← ${t("new_quiz.back")}</a>
        <h1 class="mt-1">${t("new_quiz.method_ai")}</h1>
        <p>${t("new_quiz.method_ai_desc")}</p>
      </header>
      <form class="card adv-ai-form" novalidate>
        <div class="field">
          <label class="label" for="adv-topic">${t("adv_new.topic")}</label>
          <input class="input" id="adv-topic" name="topic" maxlength="300" required
                 placeholder="${escapeAttr(t("adv_new.topic_ph"))}" />
        </div>
        <div class="field">
          <label class="label" for="adv-brief">${t("adv_new.brief")}</label>
          <textarea class="textarea" id="adv-brief" name="brief" maxlength="1000" rows="3"
                    placeholder="${escapeAttr(t("adv_new.brief_ph"))}"></textarea>
        </div>
        <div class="row-wrap">
          <div class="field">
            <label class="label" for="adv-scenes">${t("adv_new.scenes")}</label>
            <select class="select" id="adv-scenes" name="scene_count">
              ${[4, 5, 6, 7, 8, 10, 12]
                .map((count) => `<option value="${count}"${count === 6 ? " selected" : ""}>${count}</option>`)
                .join("")}
            </select>
          </div>
          <div class="field">
            <label class="label" for="adv-language">${t("editor.language_label")}</label>
            <select class="select" id="adv-language" name="language">
              ${LANGUAGES.map((item) => {
                const selected = item.code === currentLanguage() ? " selected" : "";
                return `<option value="${item.code}"${selected}>${item.label}</option>`;
              }).join("")}
            </select>
          </div>
          <div class="field">
            <label class="label" for="adv-level">${t("editor.ai_level")}</label>
            <input class="input" id="adv-level" name="level" maxlength="60" />
          </div>
        </div>
        <div class="row-wrap mt-2">
          <button type="submit" class="btn btn-primary" data-act="generate">${t("adv_new.generate")}</button>
          <span class="muted small" data-status aria-live="polite"></span>
        </div>
      </form>
    </section>`;

  const form = root.querySelector("form");
  const button = root.querySelector('[data-act="generate"]');
  const status = root.querySelector("[data-status]");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const topic = form.topic.value.trim();
    if (topic.length < 3) {
      form.topic.focus();
      toast(t("adv_new.failed"), "error");
      return;
    }
    button.disabled = true;
    status.textContent = t("adv_new.generating");
    try {
      const result = await api.post("/api/v1/ai/adventures", {
        topic,
        brief: form.brief.value.trim(),
        scene_count: Number(form.scene_count.value) || 6,
        language: form.language.value,
        level: form.level.value.trim(),
        save: true,
      });
      const quiz = result && result.quiz;
      if (!quiz || !quiz.id) throw new Error("missing quiz");
      // The story is a normal draft from here on: the editor is the hand-written
      // one, and nothing about it is generated-only.
      navigate(`/adventures/${quiz.id}/edit`, { replace: true });
    } catch (error) {
      const detail = (error.payload && error.payload.detail) || error.detail || "";
      toast(detail || t("adv_new.failed"), "error");
      status.textContent = "";
      button.disabled = false;
    }
  });

  return root;
}