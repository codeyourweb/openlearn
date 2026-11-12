// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Quiz editor: metadata, mode, WYSIWYG questions, translations, publication and AI. */

import { api, keepaliveRequest, uploadImage } from "../api.js";
import { openFramingEditor } from "../framingEditor.js";
import { framingAttr, paintFraming } from "../imageFrame.js";
import { LANGUAGES, currentLanguage, languageLabel, t } from "../i18n.js";
import { navigate } from "../router.js";
import { isLoggedIn } from "../store.js";
import { escapeHtml, showBusyOverlay, showUploadProgress, toast } from "../ui.js";
import { htmlToText, sanitizeHtml } from "../sanitize.js";

const MAX_OPTIONS = 8;
const MIN_OPTIONS = 2;
const MAX_UPLOAD = 2 * 1024 * 1024;

function blankOption(isCorrect = false) {
  return { text: "", is_correct: isCorrect, translations: {} };
}

function blankQuestion(mode = "qcm") {
  const isPoll = mode === "poll";
  return {
    text_html: "",
    translations: {},
    image_path: null,
    time_limit_seconds: 30,
    points: isPoll ? 0 : 100,
    multiple: false,
    // A poll has no answer key: no option starts out marked correct.
    options: isPoll ? [blankOption(false), blankOption(false)] : [blankOption(true), blankOption(false)],
  };
}

function blankModel(mode = "qcm") {
  const format = ["swipe", "poll"].includes(mode) ? mode : "qcm";
  return {
    id: null,
    title: "",
    description: "",
    wrong_answer_policy: "zero",
    timer_mode: "per_question",
    global_time_limit_seconds: 0,
    results_visibility: "respondents",
    mode: format,
    default_language: currentLanguage() === "en" ? "en" : currentLanguage(),
    languages: [],
    title_translations: {},
    description_translations: {},
    questions: [blankQuestion(format)],
  };
}

function toModel(quiz) {
  const target = (quiz.languages || []).filter((code) => code !== quiz.default_language);
  return {
    id: quiz.id,
    title: quiz.title,
    description: quiz.description || "",
    wrong_answer_policy: quiz.wrong_answer_policy || "zero",
    timer_mode: quiz.timer_mode || "per_question",
    global_time_limit_seconds: quiz.global_time_limit_seconds || 0,
    results_visibility: quiz.results_visibility || "respondents",
    mode: quiz.mode || "qcm",
    default_language: quiz.default_language || "en",
    languages: target,
    title_translations: quiz.title_translations || {},
    description_translations: quiz.description_translations || {},
    questions: quiz.questions.map((question) => ({
      text_html: question.text_html,
      translations: question.translations || {},
      image_path: question.image_path,
      image_framing: question.image_framing || null,
      time_limit_seconds: question.time_limit_seconds,
      points: question.points || 100,
      multiple: Boolean(question.allow_multiple ?? question.multiple_answers),
      options: question.options.map((option) => ({
        text: option.text,
        is_correct: Boolean(option.is_correct),
        translations: option.translations || {},
      })),
    })),
  };
}

function toolbar() {
  const buttons = [
    ["bold", "<b>B</b>"],
    ["italic", "<i>I</i>"],
    ["underline", "<u>U</u>"],
    ["insertUnorderedList", "•"],
    ["insertOrderedList", "1."],
    ["formatBlock:h3", "H"],
    ["removeFormat", "✕"],
  ];
  return `<div class="rte-toolbar" role="toolbar">
    ${buttons.map(([cmd, label]) => `<button type="button" class="rte-btn" data-cmd="${cmd}">${label}</button>`).join("")}
  </div>`;
}

function translationBlock(question, index, languages) {
  if (!languages.length) return "";
  return `
    <details class="translation-panel" open>
      <summary>
        <span>${t("editor.translations_inline")} · ${languages.map(languageLabel).join(", ")}</span>
        <button type="button" class="btn btn-sm" data-act="translate-question" data-q="${index}"
                title="${t("editor.ai_translate_question_hint")}"><span aria-hidden="true">✨</span> ${t("editor.ai_translate_question")}</button>
      </summary>
      ${languages
        .map(
          (code) => `
        <div class="translation-row">
          <span class="lang-tag">${escapeHtml(code)}</span>
          <textarea class="textarea" rows="2" data-tr="question" data-lang="${code}" data-q="${index}"
                    placeholder="${languageLabel(code)}">${escapeHtml(htmlToText(question.translations[code] || ""))}</textarea>
        </div>
        ${question.options
          .map(
            (option, optionIndex) => `
          <div class="translation-row">
            <span class="lang-tag">${escapeHtml(code)} · ${optionIndex + 1}</span>
            <input class="input" data-tr="option" data-lang="${code}" data-q="${index}" data-o="${optionIndex}"
                   maxlength="500" value="${escapeHtml(option.translations[code] || "")}"
                   placeholder="${t("editor.answer_n", { n: optionIndex + 1 })}" />
          </div>`,
          )
          .join("")}`,
        )
        .join("")}
    </details>`;
}

function optionRow(question, qIndex, optionIndex, mode) {
  const option = question.options[optionIndex];
  if (mode === "swipe") {
    return `
      <div class="option-row ${option.is_correct ? "correct" : ""}" data-o="${optionIndex}">
        <button type="button" class="opt-marker radio" data-act="toggle-correct" data-o="${optionIndex}"
                aria-pressed="${option.is_correct}"></button>
        <strong>${optionIndex === 0 ? t("editor.swipe_yes") : t("editor.swipe_no")}</strong>
      </div>`;
  }
  if (mode === "poll") {
    // Nothing to mark: only the label matters.
    return `
      <div class="option-row" data-o="${optionIndex}">
        <span class="opt-marker poll" aria-hidden="true">${optionIndex + 1}</span>
        <input class="input" data-field="option-text" data-o="${optionIndex}" maxlength="500"
               value="${escapeHtml(option.text)}" placeholder="${t("editor.answer_n", { n: optionIndex + 1 })}" />
        <button type="button" class="btn btn-sm btn-ghost opt-remove" data-act="remove-option" data-o="${optionIndex}"
                title="${t("action.remove")}" ${question.options.length <= MIN_OPTIONS ? "disabled" : ""}>✕</button>
      </div>`;
  }
  return `
    <div class="option-row ${option.is_correct ? "correct" : ""}" data-o="${optionIndex}">
      <button type="button" class="opt-marker ${question.multiple ? "checkbox" : "radio"}"
              data-act="toggle-correct" data-o="${optionIndex}" aria-pressed="${option.is_correct}"
              aria-label="${t("editor.correct")}"></button>
      <input class="input" data-field="option-text" data-o="${optionIndex}" maxlength="500"
             value="${escapeHtml(option.text)}" placeholder="${t("editor.answer_n", { n: optionIndex + 1 })}" />
      <button type="button" class="btn btn-sm btn-ghost" data-act="remove-option" data-o="${optionIndex}"
              title="${t("action.remove")}" ${question.options.length <= MIN_OPTIONS ? "disabled" : ""}>✕</button>
    </div>`;
}

function questionCard(question, index, model) {
  const isSwipe = model.mode === "swipe";
  return `
    <article class="question-editor" data-q="${index}">
      <div class="question-editor-head">
        <span class="q-index">${index + 1}</span>
        <strong>${t("editor.question_n", { n: index + 1 })}</strong>
        <div class="spacer"></div>
        <button type="button" class="btn btn-sm btn-ghost" data-act="move-up" title="${t("editor.move_up")}" ${index === 0 ? "disabled" : ""}>↑</button>
        <button type="button" class="btn btn-sm btn-ghost" data-act="move-down" title="${t("editor.move_down")}" ${index === model.questions.length - 1 ? "disabled" : ""}>↓</button>
        <button type="button" class="btn btn-sm btn-danger" data-act="remove-question" title="${t("editor.delete_question")}">✕</button>
      </div>

      <div class="rte-wrap">
        ${toolbar()}
        <div class="rte" contenteditable="true" role="textbox" aria-multiline="true"
             data-field="text_html" data-placeholder="${t("editor.question_text")}">${sanitizeHtml(question.text_html)}</div>
      </div>

      <div class="q-settings">
        <div class="field" data-timer-field ${model.timer_mode === "per_question" ? "" : "hidden"}>
          <label class="label">${t("editor.time_limit")}</label>
          <input class="input" type="number" min="5" max="300" step="5" data-field="time_limit_seconds" value="${question.time_limit_seconds}" />
        </div>
        <div class="field">
          <label class="label">${t("editor.points")}</label>
          <input class="input" type="number" min="10" max="1000" step="10" data-field="points" value="${question.points}" />
        </div>
        ${
          isSwipe
            ? ""
            : model.mode === "poll"
              ? `<label class="checkbox">
                   <input type="checkbox" data-field="multiple" ${question.multiple ? "checked" : ""} />
                   ${t("editor.poll_multiple")}
                 </label>`
              : `<label class="checkbox">
                   <input type="checkbox" data-field="multiple" ${question.multiple ? "checked" : ""} />
                   ${t("play.multi_hint")}
                 </label>`
        }
        <div class="spacer"></div>
        <div class="field">
          <label class="label">${t("editor.image")} (${t("common.optional")})</label>
          <div class="row">
            <button type="button" class="btn btn-sm" data-act="upload-image">${question.image_path ? t("action.remove") : t("action.upload")}</button>
            ${
              question.image_path
                ? `<button type="button" class="btn btn-sm btn-ghost" data-act="frame-image">${escapeHtml(
                    t("framing.edit"),
                  )}</button>`
                : ""
            }
            ${question.image_path ? `<button type="button" class="btn btn-sm btn-ghost" data-act="remove-image">${t("editor.remove_image")}</button>` : ""}
          </div>
        </div>
      </div>

      ${
        question.image_path
          ? `<div class="image-preview clip-frame"><img src="${escapeHtml(question.image_path)}" alt=""${framingAttr(
              question.image_framing,
            )} /></div>`
          : ""
      }

      <div class="options-editor">
        ${question.options.map((_, optionIndex) => optionRow(question, index, optionIndex, model.mode)).join("")}
      </div>
      <div class="editor-footer">
        ${
          isSwipe
            ? `<span class="hint">${t("editor.mode_swipe_hint")}</span>`
            : `<button type="button" class="btn btn-sm" data-act="add-option" ${question.options.length >= MAX_OPTIONS ? "disabled" : ""}>+ ${t("editor.add_answer")}</button>
               <span class="hint">${model.mode === "poll" ? t("editor.poll_answer_hint") : question.multiple ? t("play.multi_hint") : t("play.single_hint")}</span>`
        }
      </div>
      ${translationBlock(question, index, model.languages)}
    </article>`;
}

/** Client-side validation mirroring the server rules. */
function validate(model) {
  if (model.title.trim().length < 3) return `${t("editor.title_label")}: 3+`;
  if (!model.questions.length) return t("editor.need_question");
  for (const [index, question] of model.questions.entries()) {
    if (!htmlToText(question.text_html).trim()) return `${t("editor.question_n", { n: index + 1 })}: ${t("editor.question_text")}`;
    if (model.mode === "swipe") {
      if (question.options.length !== 2) return t("editor.need_options");
      if (question.options.filter((option) => option.is_correct).length !== 1) return t("editor.need_correct");
      continue;
    }
    if (model.mode === "poll") {
      // No answer key to check: only the labels have to be there, and unique.
      if (question.options.length < MIN_OPTIONS) return t("editor.need_options");
      const labels = question.options.map((option) => option.text.trim().toLowerCase());
      if (labels.some((text) => !text)) return t("editor.need_options");
      if (new Set(labels).size !== labels.length) return t("editor.need_unique");
      continue;
    }
    if (question.options.length < MIN_OPTIONS) return t("editor.need_options");
    if (!question.options.some((option) => option.is_correct)) return t("editor.need_correct");
    if (question.options.every((option) => option.is_correct)) return t("editor.need_wrong");
    const texts = question.options.map((option) => option.text.trim().toLowerCase());
    if (new Set(texts).size !== texts.length) return t("editor.need_unique");
    if (texts.some((text) => !text)) return t("editor.need_options");
  }
  return "";
}

function payloadFrom(model) {
  const clean = (map) => {
    const output = {};
    for (const code of model.languages) {
      const value = (map || {})[code];
      if (typeof value === "string" && value.trim()) output[code] = value;
    }
    return output;
  };
  return {
    title: model.title.trim(),
    description: model.description.trim(),
    wrong_answer_policy: model.wrong_answer_policy,
    timer_mode: model.timer_mode,
    global_time_limit_seconds: model.timer_mode === "global" ? Number(model.global_time_limit_seconds) || 0 : 0,
    results_visibility: model.results_visibility || "respondents",
    mode: model.mode,
    default_language: model.default_language,
    title_translations: clean(model.title_translations),
    description_translations: clean(model.description_translations),
    questions: model.questions.map((question) => ({
      text_html: question.text_html,
      translations: clean(question.translations),
      image_path: question.image_path,
      time_limit_seconds: question.time_limit_seconds,
      points: model.mode === "poll" ? 0 : question.points,
      allow_multiple: model.mode === "poll" ? Boolean(question.multiple) : false,
      options: question.options.map((option, optionIndex) => ({
        // Swipe cards are positional: option 0 is "yes" (swipe right), option 1
        // is "no", so the player maps a gesture to a fixed answer.
        text: model.mode === "swipe" ? (optionIndex === 0 ? "Yes" : "No") : option.text.trim(),
        is_correct: model.mode === "poll" ? false : option.is_correct,
        translations: model.mode === "swipe" ? {} : clean(option.translations),
      })),
    })),
  };
}

export async function renderEditor({ id, mode, variant }) {
  const isNew = !id || id === "new";
  const variantName = variant === "ai" ? "ai" : "manual";
  if (!isLoggedIn()) {
    const next = isNew ? "/quizzes/new" : `/quizzes/${id}/edit`;
    navigate(`/login?next=${encodeURIComponent(next)}`, { replace: true });
    return document.createElement("div");
  }

  const root = document.createElement("div");
  root.innerHTML = `<div class="loading">${t("common.loading")}</div>`;

  let model;
  let quiz = null;
  try {
    if (isNew) {
      model = blankModel(mode);
    } else {
      quiz = await api.get(`/api/v1/quizzes/${id}`);
      model = toModel(quiz);
    }
  } catch (error) {
    root.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("error.not_found"))}</div>`;
    return root;
  }

  let aiStatus = { available: false, model: "" };
  try {
    aiStatus = await api.get("/api/v1/ai/status");
  } catch {
    /* AI is optional */
  }

  let tab = "content";
  let dirty = false;

  // Autosave: the working copy is written to the server while the author types,
  // so a closed tab or a back navigation never loses the draft.
  const AUTOSAVE_DELAY = 1200;
  let autosaveTimer = 0;
  let autosaveInFlight = false;
  let autosaveQueued = false;
  let autosavedAt = null;
  let autosaveError = "";

  const targetLanguages = () => model.languages;
  const otherLanguages = () => LANGUAGES.filter((item) => item.code !== model.default_language);

  const shell = () => {
    // Anything the author typed lives in the DOM until it is read back: without
    // this, changing the timer, the format or the language repainted the form
    // and silently threw the question being written away.
    if (questionsHost) syncFromDom();
    root.innerHTML = `
      <div class="editor-head">
        <div>
          <a class="muted small" href="/dashboard" data-link>← ${t("nav.dashboard")}</a>
          <h1 class="mt-1">${isNew && !model.id ? t("editor.new_title") : t("editor.edit_title")}</h1>
          ${quiz ? `<span class="pill ${escapeHtml(quiz.status)}">${t(`dash.status.${quiz.status}`)}</span>` : ""}
        </div>
        <div class="row">
          <span class="small-note autosave-state" id="save-flag" data-state="idle">${t("editor.autosave_idle")}</span>
          <button class="btn btn-sm" id="save-quiz">${t("editor.save")}</button>
        </div>
      </div>

      <div class="tabs mt-2">
        <button class="tab ${tab === "content" ? "active" : ""}" data-tab="content">${t("editor.tab_content")}</button>
        <button class="tab ${tab === "preview" ? "active" : ""}" data-tab="preview">${t("editor.tab_preview")}</button>
        <button class="tab ${tab === "publish" ? "active" : ""}" data-tab="publish">${t("editor.tab_publish")}</button>
      </div>

      <div id="tab-body"></div>`;

    const body = root.querySelector("#tab-body");
    if (tab === "content") body.appendChild(contentTab());
    else if (tab === "preview") body.appendChild(previewTab());
    else body.appendChild(publishTab());
    paintFraming(root);
    root.querySelector("#save-quiz").addEventListener("click", save);
    paintSaveState(dirty ? "pending" : autosavedAt ? "saved" : "idle");
    root.querySelectorAll("[data-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        syncFromDom();
        tab = button.dataset.tab;
        shell();
      });
    });

  };

  const paintSaveState = (state, detail = "") => {
    const flag = root.querySelector("#save-flag");
    if (!flag) return;
    flag.dataset.state = state;
    if (state === "saving") flag.textContent = t("editor.autosave_saving");
    else if (state === "saved") {
      const time = autosavedAt ? autosavedAt.toLocaleTimeString(currentLanguage(), { hour: "2-digit", minute: "2-digit" }) : "";
      flag.textContent = t("editor.autosave_saved", { time });
    } else if (state === "error") flag.textContent = detail || t("editor.autosave_error");
    else if (state === "pending") flag.textContent = t("editor.unsaved");
    else flag.textContent = t("editor.autosave_idle");
  };

  const draftPayload = () => ({
    ...payloadFrom(model),
    // A draft may be nameless and unfinished; the server accepts it as-is.
    title: model.title.trim(),
  });

  const flushDraft = async () => {
    if (autosaveInFlight) {
      autosaveQueued = true;
      return;
    }
    autosaveInFlight = true;
    paintSaveState("saving");
    try {
      // Read the live DOM first: the author types faster than the debounce.
      if (questionsHost) syncFromDom();
      const payload = draftPayload();
      const saved = model.id
        ? await api.put(`/api/v1/quizzes/${model.id}/draft`, payload)
        : await api.post("/api/v1/quizzes/draft", payload);
      model.id = saved.id;
      quiz = { ...(quiz || {}), ...saved };
      autosavedAt = new Date();
      autosaveError = "";
      paintSaveState("saved");
      if (/^\/quizzes\/new(\/|$)/.test(location.pathname)) {
        // Give the draft a real address so a reload comes back to it instead of
        // creating a second draft from the chooser entry point.
        history.replaceState({}, "", `/quizzes/${saved.id}/edit`);
      }
    } catch (error) {
      autosaveError = error.detail || t("common.error");
      paintSaveState("error", autosaveError);
    } finally {
      autosaveInFlight = false;
      if (autosaveQueued) {
        autosaveQueued = false;
        scheduleAutosave(0);
      }
    }
  };

  const scheduleAutosave = (delay = AUTOSAVE_DELAY) => {
    window.clearTimeout(autosaveTimer);
    autosaveTimer = window.setTimeout(() => {
      if (!dirty) return;
      dirty = false;
      void flushDraft();
    }, delay);
  };

  const markDirty = () => {
    dirty = true;
    paintSaveState("pending");
    scheduleAutosave();
  };

  const contentTab = () => {
    const section = document.createElement("section");
    section.innerHTML = `
      ${
        aiStatus.available
          ? `<details class="card ai-draft-card" ${variant === "ai" ? "open" : ""}>
               <summary><strong><span aria-hidden="true">✨</span> ${t("editor.ai_generate")}</strong></summary>
               <p class="hint">${t("new_quiz.method_ai_desc")}</p>
               <div class="row-wrap mt-2">
                 <input class="input" id="ai-topic" maxlength="300" placeholder="${t("editor.ai_topic_placeholder")}" />
                 <input class="input" id="ai-count" type="number" min="1" max="50" value="10" data-size="narrow" />
                 <input class="input" id="ai-level" maxlength="60" placeholder="${t("editor.ai_level")}" data-size="medium" />
                 <button class="btn btn-primary" data-act="ai-generate">${t("editor.ai_generate_run")}</button>
               </div>
               <div id="ai-output" class="mt-2"></div>
             </details>`
          : ""
      }
      <section class="card">
        <div class="field">
          <label class="label" for="quiz-title">${t("editor.title_label")}</label>
          <input class="input" id="quiz-title" maxlength="120" value="${escapeHtml(model.title)}"
                 placeholder="${t("editor.title_placeholder")}" />
        </div>
        <div class="field">
          <label class="label" for="quiz-description">${t("editor.description_label")}</label>
          <textarea class="textarea" id="quiz-description" maxlength="2000"
                    placeholder="${t("editor.description_placeholder")}">${escapeHtml(model.description)}</textarea>
        </div>
        <div class="row-wrap">
          <div class="field">
            <label class="label" for="quiz-mode">${t("editor.mode_label")}</label>
            <select class="select" id="quiz-mode">
              <option value="qcm">${t("editor.mode_qcm")}</option>
              <option value="swipe">${t("editor.mode_swipe")}</option>
              <option value="poll">${t("new_quiz.poll")}</option>
            </select>
            <p class="hint" id="mode-hint"></p>
          </div>
          <div class="field">
            <label class="label" for="quiz-policy">${t("editor.policy_label")}</label>
            <select class="select" id="quiz-policy">
              <option value="zero">${t("editor.policy_zero")}</option>
              <option value="penalty">${t("editor.policy_penalty")}</option>
            </select>
            <p class="hint">${t("editor.policy_hint")}</p>
          </div>
          <div class="field">
            <label class="label" for="quiz-timer">${t("editor.timer_label")}</label>
            <select class="select" id="quiz-timer">
              <option value="per_question">${t("editor.timer_per_question")}</option>
              <option value="global">${t("editor.timer_global")}</option>
              <option value="none">${t("editor.timer_none")}</option>
            </select>
            <p class="hint" id="timer-hint"></p>
          </div>
          <div class="field" id="global-timer-field">
            <label class="label" for="quiz-global-timer">${t("editor.global_timer_label")}</label>
            <input class="input" type="number" id="quiz-global-timer" min="30" max="7200" step="30"
                   value="${Number(model.global_time_limit_seconds) || 300}" />
            <p class="hint">${t("editor.global_timer_hint")}</p>
          </div>
          <div class="field" id="results-visibility-field" ${model.mode === "poll" ? "" : "hidden"}>
            <label class="label" for="quiz-results">${t("editor.results_visibility")}</label>
            <select class="select" id="quiz-results">
              <option value="private">${t("editor.results_private")}</option>
              <option value="respondents">${t("editor.results_respondents")}</option>
              <option value="public">${t("editor.results_public")}</option>
            </select>
            <p class="hint">${t("editor.results_hint")}</p>
          </div>
          <div class="field">
            <label class="label" for="quiz-language">${t("editor.language_label")}</label>
            <select class="select" id="quiz-language">
              ${LANGUAGES.map((item) => `<option value="${item.code}">${item.label}</option>`).join("")}
            </select>
          </div>
        </div>
        <div class="field">
          <label class="label">${t("editor.languages_label")}</label>
          <div class="lang-checkboxes" id="lang-checks">
            ${otherLanguages()
              .map(
                (item) => `<label><input type="checkbox" value="${item.code}" ${
                  model.languages.includes(item.code) ? "checked" : ""
                } /> ${item.label}</label>`,
              )
              .join("")}
          </div>
          <p class="hint">${t("editor.languages_hint")}</p>
        </div>
        ${
          model.languages.length
            ? `<details class="translation-panel">
                 <summary>${t("editor.translations_for", { language: model.languages.map(languageLabel).join(", ") })}</summary>
                 ${model.languages
                   .map(
                     (code) => `
                   <div class="translation-row">
                     <span class="lang-tag">${escapeHtml(code)} · ${t("editor.title_label")}</span>
                     <input class="input" data-tr-meta="title" data-lang="${code}" maxlength="120"
                            value="${escapeHtml(model.title_translations[code] || "")}" />
                   </div>
                   <div class="translation-row">
                     <span class="lang-tag">${escapeHtml(code)} · ${t("editor.description_label")}</span>
                     <textarea class="textarea" rows="2" data-tr-meta="description" data-lang="${code}">${escapeHtml(model.description_translations[code] || "")}</textarea>
                   </div>`,
                   )
                   .join("")}
               </details>`
            : ""
        }
      </section>

      <section class="mt-3">
        <div class="row between">
          <h2>${t("editor.questions_section")}</h2>
          <button class="btn btn-sm" id="add-question">+ ${t("editor.add_question")}</button>
        </div>
        <div class="stack mt-2" id="questions"></div>
      </section>`;

    section.querySelector("#quiz-mode").value = model.mode;
    section.querySelector("#quiz-policy").value = model.wrong_answer_policy;
    section.querySelector("#quiz-results").value = model.results_visibility || "respondents";
    // A poll has no scoring at all: the policy select only confuses.
    const policyField = section.querySelector("#quiz-policy").closest(".field");
    if (policyField) policyField.hidden = model.mode === "poll";
    section.querySelector("#quiz-timer").value = model.timer_mode;
    const applyTimerUi = () => {
      const field = section.querySelector("#global-timer-field");
      field.hidden = model.timer_mode !== "global";
      section.querySelector("#timer-hint").textContent =
        model.timer_mode === "global"
          ? t("editor.timer_global_hint")
          : model.timer_mode === "none"
            ? t("editor.timer_none_hint")
            : t("editor.timer_per_question_hint");
      // A per-question limit is meaningless outside the per-question mode: the
      // control disappears instead of sitting there greyed out, which read as
      // "the timer is still on" in a quiz that has none.
      section.querySelectorAll("[data-timer-field]").forEach((field) => {
        field.hidden = model.timer_mode !== "per_question";
      });
      section.querySelectorAll('[data-field="time_limit_seconds"]').forEach((input) => {
        input.disabled = model.timer_mode !== "per_question";
      });
    };
    applyTimerUi();
    section.querySelector("#quiz-language").value = model.default_language;
    section.querySelector("#mode-hint").textContent =
      model.mode === "swipe"
        ? t("editor.mode_swipe_hint")
        : model.mode === "poll"
          ? t("editor.mode_poll_hint")
          : t("editor.mode_qcm_hint");

    section.querySelector("#quiz-title").addEventListener("input", (event) => {
      model.title = event.target.value;
      markDirty();
    });
    section.querySelector("#quiz-description").addEventListener("input", (event) => {
      model.description = event.target.value;
      markDirty();
    });
    section.querySelector("#quiz-mode").addEventListener("change", (event) => {
      syncFromDom();
      model.mode = event.target.value;
      if (model.mode === "poll") {
        // Leaving a scored format for a poll: the keys and the points go away,
        // otherwise the server would store a lie nobody can undo in the UI.
        model.questions.forEach((question) => {
          question.options.forEach((option) => {
            option.is_correct = false;
          });
          question.points = 0;
        });
        model.wrong_answer_policy = "zero";
      }
      if (model.mode === "swipe") {
        model.questions.forEach((question) => {
          const keep = question.options.findIndex((option) => option.is_correct);
          question.options = [question.options[keep === -1 ? 0 : keep] || blankOption(true), blankOption(false)];
          question.options[0].is_correct = true;
          question.options[1].is_correct = false;
          question.options.forEach((option, position) => {
            option.text = position === 0 ? "Yes" : "No";
          });
          question.multiple = false;
        });
      }
      markDirty();
      shell();
    });
    section.querySelector("#quiz-policy").addEventListener("change", (event) => {
      model.wrong_answer_policy = event.target.value;
      markDirty();
    });
    section.querySelector("#quiz-results").addEventListener("change", (event) => {
      model.results_visibility = event.target.value;
      markDirty();
    });
    section.querySelector("#quiz-timer").addEventListener("change", (event) => {
      model.timer_mode = event.target.value;
      markDirty();
      shell();
    });
    section.querySelector("#quiz-global-timer").addEventListener("input", (event) => {
      model.global_time_limit_seconds = Number(event.target.value) || 0;
      markDirty();
    });
    section.querySelector("#quiz-language").addEventListener("change", (event) => {
      model.default_language = event.target.value;
      if (model.languages.includes(model.default_language)) {
        model.languages = model.languages.filter((code) => code !== model.default_language);
        delete model.title_translations[model.default_language];
      }
      markDirty();
      shell();
    });
    section.querySelector("#lang-checks").addEventListener("change", (event) => {
      const code = event.target.value;
      if (event.target.checked) {
        if (!model.languages.includes(code)) model.languages.push(code);
      } else {
        model.languages = model.languages.filter((item) => item !== code);
      }
      markDirty();
      drawQuestions(section);
    });
    section.querySelector("#add-question").addEventListener("click", () => {
      syncFromDom();
      model.questions.push(blankQuestion(model.mode));
      markDirty();
      drawQuestions(section);
    });

    drawQuestions(section);
    return section;
  };

  let questionsHost = null;
  const drawQuestions = (section) => {
    questionsHost = section.querySelector("#questions");
    questionsHost.innerHTML = model.questions.map((question, index) => questionCard(question, index, model)).join("");
  };


  /* A draft is only worth writing if you can see it: this tab plays the
     questionnaire with what is on screen right now, without saving anything and
     without going back to the list to start a test run. */
  const previewTab = () => {
    syncFromDom();
    const section = document.createElement("section");
    const questions = model.questions.filter(
      (question) =>
        htmlToText(question.text_html || "").trim() || question.image_path || question.options.length,
    );
    let index = 0;
    let picked = [];
    let revealed = false;

    const optionLabel = (question, position) => {
      if (model.mode === "swipe") return t(position === 0 ? "editor.swipe_yes" : "editor.swipe_no");
      return question.options[position].text || t("editor.answer_n", { n: position + 1 });
    };

    const draw = () => {
      if (!questions.length) {
        section.innerHTML = `
          <div class="empty">
            <h2>${escapeHtml(t("editor.preview_empty"))}</h2>
            <p class="muted">${escapeHtml(t("editor.preview_empty_hint"))}</p>
          </div>`;
        return;
      }
      index = Math.min(Math.max(0, index), questions.length - 1);
      const question = questions[index];
      const multiple = Boolean(question.multiple) && model.mode === "qcm";
      const isPoll = model.mode === "poll";
      const options = question.options
        .map((option, position) => {
          const selected = picked.includes(position);
          const state = revealed ? (option.is_correct ? " correct" : " wrong") : "";
          return `
            <button type="button" class="preview-option${selected ? " chosen" : ""}${isPoll ? "" : state}"
                    data-option="${position}" aria-pressed="${selected}">
              <span class="opt-marker ${multiple ? "checkbox" : "radio"}" aria-hidden="true"></span>
              <span>${escapeHtml(optionLabel(question, position))}</span>
            </button>`;
        })
        .join("");

      section.innerHTML = `
        <div class="card preview-card">
          <div class="card-head">
            <h2>${escapeHtml(t("editor.preview_title"))}</h2>
            <span class="badge muted">${escapeHtml(t("editor.preview_draft_badge"))}</span>
          </div>
          <p class="hint">${escapeHtml(t("editor.preview_lead"))}</p>

          <div class="question-card preview-question">
            <div class="row between">
              <span class="badge">${escapeHtml(
                t("play.question_of", { n: index + 1, total: questions.length }),
              )}</span>
              ${isPoll ? `<span class="badge muted">${escapeHtml(t("editor.preview_poll"))}</span>` : ""}
            </div>
            ${
              htmlToText(question.text_html || "").trim()
                ? `<div class="question-text">${sanitizeHtml(question.text_html)}</div>`
                : ""
            }
            ${
              question.image_path
                ? `<img class="question-image" src="${escapeHtml(question.image_path)}" alt=""${framingAttr(
                    question.image_framing,
                  )} />`
                : ""
            }
            <div class="preview-options" role="group">${options}</div>
          </div>

          <div class="row between mt-2">
            <button type="button" class="btn btn-sm" data-act="preview-prev" ${index === 0 ? "disabled" : ""}>
              ← ${escapeHtml(t("action.previous"))}
            </button>
            <div class="row">
              ${
                isPoll
                  ? ""
                  : `<button type="button" class="btn btn-sm btn-ghost" data-act="preview-reveal">
                       ${escapeHtml(revealed ? t("editor.preview_hide") : t("editor.preview_reveal"))}
                     </button>`
              }
              <button type="button" class="btn btn-sm btn-primary" data-act="preview-next"
                      ${index >= questions.length - 1 ? "disabled" : ""}>
                ${escapeHtml(t("action.next"))} →
              </button>
            </div>
          </div>
          ${revealed && !isPoll ? `<p class="hint">${escapeHtml(t("editor.preview_revealed"))}</p>` : ""}
        </div>`;

      section.querySelectorAll("[data-option]").forEach((button) => {
        button.addEventListener("click", () => {
          if (revealed) return;
          const position = Number(button.dataset.option);
          if (multiple) {
            picked = picked.includes(position)
              ? picked.filter((value) => value !== position)
              : [...picked, position];
          } else {
            picked = [position];
          }
          draw();
        });
      });
      section.querySelector('[data-act="preview-prev"]')?.addEventListener("click", () => {
        index -= 1;
        picked = [];
        revealed = false;
        draw();
      });
      section.querySelector('[data-act="preview-next"]')?.addEventListener("click", () => {
        index += 1;
        picked = [];
        revealed = false;
        draw();
      });
      section.querySelector('[data-act="preview-reveal"]')?.addEventListener("click", () => {
        revealed = !revealed;
        draw();
      });
      paintFraming(section);
    };

    draw();
    return section;
  };

  const publishTab = () => {
    const section = document.createElement("section");
    const status = quiz ? t(`dash.status.${quiz.status}`) : t(`dash.status.draft`);
    const live = Number((quiz && quiz.published_version) || 0);
    const canPublishPublicly = Boolean(quiz && quiz.can_publish_publicly);
    section.innerHTML = `
      <section class="card">
        <h2>${t("editor.publish_title")}</h2>
        <p class="hint">${t("editor.publish_hint")}</p>
        <div class="row-wrap mt-2">
          <span class="pill ${escapeHtml(quiz ? quiz.status : "draft")}">${status}</span>
          ${
            live
              ? `<span class="badge">${t("editor.live_version", { n: live })}</span>`
              : `<span class="badge muted">${t("editor.no_live_version")}</span>`
          }
          ${quiz ? `<span class="badge muted">${(quiz.languages || []).map(languageLabel).join(", ")}</span>` : ""}
        </div>

        <div class="publish-choices mt-3">
          ${
            aiStatus.available
              ? `<div class="publish-check">
                   <h3><span aria-hidden="true">✨</span> ${t("editor.ai_title")}</h3>
                   <div class="row-wrap ai-zone">
                     <button class="btn" data-act="ai-legal"><span aria-hidden="true">✨</span> ${t("editor.ai_legal")}</button>
                     <button class="btn" data-act="ai-answers"><span aria-hidden="true">✨</span> ${t("editor.ai_answers")}</button>
                     <button class="btn" data-act="ai-apply" hidden>${t("editor.ai_apply")}</button>
                   </div>
                   <div id="ai-output" class="mt-2"></div>
                 </div>`
              : `<p class="muted">${t("editor.ai_unavailable")}</p>`
          }
        </div>


        <div class="publish-actions mt-3">
          <div class="publish-action">
            <button class="btn btn-lg" data-act="publish-private">${t("editor.publish_private")}</button>
            <p class="hint">${t("editor.publish_private_hint")}</p>
          </div>
          <div class="publish-action">
            ${
              canPublishPublicly
                ? `<button class="btn btn-primary btn-lg" data-act="publish-public">${t("editor.publish_public")}</button>`
                : `<button class="btn btn-primary btn-lg" data-act="publish-public" disabled aria-describedby="public-forbidden">${t("editor.publish_public")}</button>`
            }
            <p class="hint">${t("editor.publish_public_hint")}</p>
            ${
              canPublishPublicly
                ? ""
                : `<p class="hint small-note" id="public-forbidden">${t("editor.publish_public_forbidden")}</p>`
            }
          </div>
        </div>
        <p class="hint mt-2">${t("editor.publish_version_hint")}</p>
        ${quiz && quiz.moderation_note ? `<p class="banner warn mt-2">${escapeHtml(quiz.moderation_note)}</p>` : ""}
        ${
          quiz && quiz.status === "public"
            ? `<div class="row mt-2"><button class="btn btn-ghost" data-act="retire">${t("quiz.retire")}</button></div>`
            : ""
        }
      </section>

      <details class="card mt-3" ${live ? "" : "open"}>
        <summary><strong>${t("editor.keep_versions")}</strong></summary>
        <p class="hint">${t("editor.versions_hint")}</p>
        <div id="versions-body" class="mt-2"><p class="muted">${t("common.loading")}</p></div>
      </details>`;
    void drawVersions(section);
    return section;
  };

  const drawVersions = async (section) => {
    const host = section.querySelector("#versions-body");
    if (!host) return;
    if (!model.id) {
      host.innerHTML = `<p class="muted">${t("editor.versions_empty")}</p>`;
      return;
    }
    try {
      const rows = await api.get(`/api/v1/quizzes/${model.id}/versions`);
      if (!rows.length) {
        host.innerHTML = `<p class="muted">${t("editor.versions_empty")}</p>`;
        return;
      }
      host.innerHTML = `
        <table class="table versions-table">
          <thead>
            <tr>
              <th>${t("editor.version")}</th>
              <th>${t("editor.version_title")}</th>
              <th>${t("editor.version_items")}</th>
              <th>${t("editor.version_state")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${rows
              .map(
                (row) => `
              <tr data-version="${row.number}">
                <td><strong>v${row.number}</strong></td>
                <td>${escapeHtml(row.title || "—")}</td>
                <td>${row.node_count ? t("editor.version_nodes", { n: row.node_count }) : t("editor.version_questions", { n: row.question_count })}</td>
                <td>
                  <span class="pill ${escapeHtml(row.status)}">${t(`editor.version_status.${row.status}`)}</span>
                  <div class="small-note">${row.published_at ? escapeHtml(new Date(row.published_at).toLocaleDateString(currentLanguage())) : ""}</div>
                </td>
                <td class="row">
                  <button class="btn btn-sm btn-ghost" data-act="restore-version" data-n="${row.number}">${t("editor.restore")}</button>
                  <button class="btn btn-sm" data-act="restore-publish" data-n="${row.number}">${t("editor.restore_publish")}</button>
                </td>
              </tr>`,
              )
              .join("")}
          </tbody>
        </table>`;
    } catch (error) {
      host.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
    }
  };

  const syncFromDom = () => {
    const title = root.querySelector("#quiz-title");
    if (title) model.title = title.value;
    const description = root.querySelector("#quiz-description");
    if (description) model.description = description.value;
    const policy = root.querySelector("#quiz-policy");
    if (policy) model.wrong_answer_policy = policy.value;
    const results = root.querySelector("#quiz-results");
    if (results) model.results_visibility = results.value;
    const timer = root.querySelector("#quiz-timer");
    if (timer) model.timer_mode = timer.value;
    const globalTimer = root.querySelector("#quiz-global-timer");
    if (globalTimer) model.global_time_limit_seconds = Number(globalTimer.value) || 0;
    const mode = root.querySelector("#quiz-mode");
    if (mode) model.mode = mode.value;
    const language = root.querySelector("#quiz-language");
    if (language) model.default_language = language.value;

    root.querySelectorAll(".question-editor").forEach((card) => {
      const index = Number(card.dataset.q);
      const question = model.questions[index];
      if (!question) return;
      const rte = card.querySelector(".rte");
      if (rte) question.text_html = rte.innerHTML;
      const time = card.querySelector('[data-field="time_limit_seconds"]');
      if (time) question.time_limit_seconds = Number(time.value) || 30;
      const points = card.querySelector('[data-field="points"]');
      if (points) question.points = Number(points.value) || 100;
      const multiple = card.querySelector('[data-field="multiple"]');
      if (multiple) {
        question.multiple = multiple.checked;
        if (!question.multiple) {
          const firstCorrect = question.options.findIndex((option) => option.is_correct);
          question.options.forEach((option, position) => {
            option.is_correct = position === (firstCorrect === -1 ? 0 : firstCorrect);
          });
        }
      }
      card.querySelectorAll('[data-field="option-text"]').forEach((input) => {
        const optionIndex = Number(input.dataset.o);
        if (question.options[optionIndex]) question.options[optionIndex].text = input.value;
      });
      card.querySelectorAll("[data-tr]").forEach((input) => {
        const code = input.dataset.lang;
        if (!code) return;
        const value = input.value.trim();
        if (input.dataset.tr === "question") {
          if (value) question.translations[code] = `<p>${escapeHtml(value)}</p>`;
          else delete question.translations[code];
        } else {
          const optionIndex = Number(input.dataset.o);
          const option = question.options[optionIndex];
          if (!option) return;
          if (value) option.translations[code] = value;
          else delete option.translations[code];
        }
      });
    });
    const titleTranslationInputs = root.querySelectorAll("[data-tr-meta]");
    titleTranslationInputs.forEach((input) => {
      const code = input.dataset.lang;
      const value = input.value.trim();
      const key = input.dataset.trMeta;
      const map = key === "title" ? model.title_translations : model.description_translations;
      if (value) map[code] = value;
      else delete map[code];
    });
  };

  const save = async () => {
    syncFromDom();
    const problem = validate(model);
    if (problem) {
      toast(problem, "error");
      return;
    }
    const button = root.querySelector("#save-quiz");
    button.disabled = true;
    try {
      const payload = payloadFrom(model);
      const saved = model.id
        ? await api.put(`/api/v1/quizzes/${model.id}`, payload)
        : await api.post("/api/v1/quizzes", payload);
      const isFirstSave = !model.id;
      model.id = saved.id;
      quiz = saved;
      dirty = false;
      autosavedAt = new Date();
      toast(t("editor.saved"), "success");
      if (isFirstSave) {
        // A brand-new quiz gets its own address; the page is rebuilt from it.
        navigate(`/quizzes/${saved.id}/edit`, { replace: true });
        return;
      }
      paintSaveState("saved");
      shell();
    } catch (error) {
      button.disabled = false;
      toast(error.detail || t("common.error"), "error");
    }
  };

  // Rough size of what would be read: the title, the description, the questions
  // and their options. Good enough for an estimate, and no request needed.
  const runAi = async (action, button) => {
    if (!model.id) {
      toast(t("editor.save"), "error");
      return;
    }
    button.disabled = true;
    const output = root.querySelector("#ai-output");
    // Every AI call is slow by nature: say so while the model works.
    const busy =
      action === "ai-translate"
        ? showBusyOverlay(t("editor.ai_translating"))
        : action === "ai-legal"
          ? showBusyOverlay(t("editor.ai_reviewing_legal"))
          : action === "ai-answers"
            ? showBusyOverlay(t("editor.ai_reviewing_answers"))
            : action === "ai-generate"
              ? showBusyOverlay(t("editor.ai_generating"))
              : null;
    try {
      if (action === "ai-translate") {
        const languages = model.languages.length ? model.languages : otherLanguages().map((item) => item.code);
        const overwrite = Boolean(root.querySelector("#ai-overwrite")?.checked);
        const updated = await api.post(`/api/v1/quizzes/${model.id}/ai/translate`, { languages, overwrite });
        quiz = updated;
        model = toModel(updated);
        toast(t("editor.saved"), "success");
        shell();
        return;
      }
      if (action === "translate-question") {
        const questionIndex = Number(button.dataset.q || 0);
        const languages = model.languages.length ? model.languages : otherLanguages().map((item) => item.code);
        if (!languages.length) {
          toast(t("editor.translations_hint"), "error");
          return;
        }
        if (questionsHost) syncFromDom();
        await flushDraft();
        const updated = await api.post(`/api/v1/quizzes/${model.id}/ai/translate`, {
          languages,
          // Only this question and its answers: a whole-document call for one
          // card would spend the budget of fifteen seconds on nothing.
          question_index: questionIndex,
          overwrite: true,
        });
        quiz = updated;
        model = toModel(updated);
        toast(t("editor.saved"), "success");
        shell();
        return;
      }
      if (action === "ai-legal" || action === "ai-answers") {
        const path = action === "ai-legal" ? "review-legal" : "review-answers";
        const review = await api.post(`/api/v1/quizzes/${model.id}/ai/${path}`);
        if (output) {
          output.innerHTML = `
            <div class="review-item ${escapeHtml(review.status)}">
              <strong>${escapeHtml(review.status)}</strong>
              <div class="finding">${escapeHtml(review.summary || "")}</div>
              ${(review.findings || [])
                .map((finding) => `<div class="finding">• Q${Number(finding.question_index) + 1}: ${escapeHtml(finding.issue)}</div>`)
                .join("")}
            </div>`;
        }
        const applyButton = root.querySelector('[data-act="ai-apply"]');
        if (applyButton && (review.corrections || []).length) applyButton.hidden = false;
        return;
      }
      if (action === "ai-apply") {
        const result = await api.post(`/api/v1/quizzes/${model.id}/ai/apply-answers`);
        quiz = result.quiz;
        model = toModel(result.quiz);
        toast(t("editor.ai_applied", { n: result.applied }), "success");
        shell();
        return;
      }
      if (action === "ai-generate") {
        const topic = root.querySelector("#ai-topic").value.trim();
        const count = Number(root.querySelector("#ai-count").value) || 10;
        const level = root.querySelector("#ai-level").value.trim();
        if (topic.length < 3) {
          toast(t("editor.ai_topic"), "error");
          return;
        }
        if (output) output.innerHTML = `<p class="muted">${t("editor.ai_generating")}</p>`;
        const result = await api.post("/api/v1/ai/quizzes", {
          topic,
          question_count: count,
          mode: model.mode,
          language: model.default_language,
          level,
          save: false,
        });
        const draft = result.draft;
        model.title = draft.title;
        model.description = draft.description || "";
        model.questions = draft.questions.map((question) => ({
          text_html: question.text_html,
          translations: {},
          image_path: null,
          time_limit_seconds: question.time_limit_seconds,
          points: question.points,
          options: question.options.map((option) => ({
            text: option.text,
            is_correct: option.is_correct,
            translations: {},
          })),
        }));
        tab = "content";
        markDirty();
        shell();
        toast(t("editor.saved"), "success");
      }
    } catch (error) {
      toast(error.detail || t("common.error"), "error");
    } finally {
      busy?.done();
      button.disabled = false;
    }
  };

  root.addEventListener("click", async (event) => {
    const rteButton = event.target.closest(".rte-btn");
    if (rteButton) {
      event.preventDefault();
      const cmd = rteButton.dataset.cmd;
      const card = rteButton.closest(".question-editor");
      card?.querySelector(".rte")?.focus();
      if (cmd.startsWith("formatBlock:")) document.execCommand("formatBlock", false, cmd.split(":")[1]);
      else document.execCommand(cmd, false, null);
      return;
    }

    const button = event.target.closest("[data-act]");
    if (!button) return;
    const action = button.dataset.act;
    const card = button.closest(".question-editor");
    const index = card ? Number(card.dataset.q) : null;

    if (action === "toggle-correct") {
      const optionIndex = Number(button.dataset.o);
      const question = model.questions[index];
      if (!question) return;
      if (model.mode === "swipe" || !question.multiple) {
        // Radio behaviour: exactly one correct answer.
        question.options.forEach((option, position) => {
          option.is_correct = position === optionIndex;
        });
      } else {
        // Checkbox behaviour: toggle, but keep at least one correct answer.
        const nextValue = !question.options[optionIndex].is_correct;
        if (!nextValue && question.options.filter((option) => option.is_correct).length === 1) {
          toast(t("editor.need_correct"), "error");
          return;
        }
        question.options[optionIndex].is_correct = nextValue;
      }
      markDirty();
      syncFromDom();
      card.outerHTML = questionCard(question, index, model);
      return;
    }
    if (action === "add-option") {
      syncFromDom();
      const question = model.questions[index];
      if (question && question.options.length < MAX_OPTIONS) {
        question.options.push(blankOption(false));
        markDirty();
        card.outerHTML = questionCard(question, index, model);
      }
      return;
    }
    if (action === "remove-option") {
      syncFromDom();
      const question = model.questions[index];
      const optionIndex = Number(button.dataset.o);
      if (question && question.options.length > MIN_OPTIONS) {
        question.options.splice(optionIndex, 1);
        markDirty();
        card.outerHTML = questionCard(question, index, model);
      }
      return;
    }
    if (action === "remove-question") {
      syncFromDom();
      if (model.questions.length > 1) {
        model.questions.splice(index, 1);
        markDirty();
        shell();
      }
      return;
    }
    if (action === "move-up" || action === "move-down") {
      syncFromDom();
      const target = action === "move-up" ? index - 1 : index + 1;
      if (target >= 0 && target < model.questions.length) {
        const [moved] = model.questions.splice(index, 1);
        model.questions.splice(target, 0, moved);
        markDirty();
        shell();
      }
      return;
    }
    if (action === "upload-image") {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = "image/png,image/jpeg,image/webp,image/gif";
      input.addEventListener("change", async () => {
        const file = input.files && input.files[0];
        if (!file) return;
        if (file.size > MAX_UPLOAD) {
          toast(t("editor.too_large"), "error");
          return;
        }
        const progress = showUploadProgress(t("editor.uploading"), file.name);
        try {
          syncFromDom();
          const uploaded = await uploadImage(file, (ratio) => progress.update(ratio));
          progress.finishing();
          model.questions[index].image_path = uploaded.path;
          markDirty();
          toast(t("editor.image_uploaded"), "success");
          shell();
        } catch (error) {
          toast(error.detail || t("editor.image_failed"), "error");
        } finally {
          progress.done();
        }
      });
      input.click();
      return;
    }
    if (action === "frame-image") {
      syncFromDom();
      const question = model.questions[index];
      if (!question || !question.image_path) return;
      const chosen = await openFramingEditor({
        src: question.image_path,
        aspect: 4 / 3,
        framing: question.image_framing || null,
        label: t("editor.image"),
      });
      if (chosen === undefined) return;
      question.image_framing = chosen;
      markDirty();
      shell();
      return;
    }
    if (action === "remove-image") {
      syncFromDom();
      model.questions[index].image_path = null;
      model.questions[index].image_framing = null;
      markDirty();
      shell();
      return;
    }
    if (action === "publish-private" || action === "publish-public") {
      button.disabled = true;
      const wantsPublic = action === "publish-public";
      try {
        // Freeze exactly what is on screen: flush the working copy first.
        if (questionsHost) syncFromDom();
        await flushDraft();
        const result = await api.post(`/api/v1/quizzes/${model.id}/publish`, {
          note: "",
          visibility: wantsPublic ? "public" : "private",
        });
        if (!wantsPublic) {
          toast(t("editor.publish_private_done"), "success");
        } else if (result.requires_moderation) {
          toast(t("editor.publish_public_queued"), "success");
        } else {
          toast(t("editor.publish_public_done"), "success");
        }
        quiz = { ...(quiz || {}), ...result };
        dirty = false;
        shell();
      } catch (error) {
        toast(error.detail || t("common.error"), "error");
      } finally {
        button.disabled = false;
      }
      return;
    }
    if (action === "retire") {
      button.disabled = true;
      try {
        const result = await api.post(`/api/v1/quizzes/${model.id}/visibility`, { visibility: "private" });
        toast(t("quiz.retired"), "success");
        quiz = { ...(quiz || {}), ...result };
        shell();
      } catch (error) {
        toast(error.detail || t("common.error"), "error");
      } finally {
        button.disabled = false;
      }
      return;
    }
    if (action === "reload-versions") {
      const section = button.closest("section");
      const body = section && section.parentElement;
      if (body) void drawVersions(body);
      return;
    }
    if (action === "restore-version" || action === "restore-publish") {
      button.disabled = true;
      try {
        const publish = action === "restore-publish";
        const result = await api.post(`/api/v1/quizzes/${model.id}/versions/${button.dataset.n}/restore`, {
          publish,
        });
        model = toModel(result.quiz);
        quiz = result.quiz;
        dirty = false;
        autosavedAt = new Date();
        toast(
          publish
            ? result.status === "public"
              ? t("editor.restored_published", { n: result.published_version })
              : t("editor.publish_pending")
            : t("editor.restored", { n: Number(button.dataset.n) }),
          "success",
        );
        shell();
      } catch (error) {
        button.disabled = false;
        toast(error.detail || t("common.error"), "error");
      }
      return;
    }
    if (action.startsWith("ai-")) {
      await runAi(action, button);
    }
  });

  root.addEventListener("input", (event) => {
    if (event.target.closest(".question-editor") || event.target.closest(".card")) markDirty();
  });

  // Last chance to keep the work: flush the working copy when the tab goes away.
  const flushOnExit = () => {
    if (!dirty) return;
    window.clearTimeout(autosaveTimer);
    if (questionsHost) syncFromDom();
    const path = model.id ? `/api/v1/quizzes/${model.id}/draft` : "/api/v1/quizzes/draft";
    keepaliveRequest(model.id ? "PUT" : "POST", path, draftPayload());
    dirty = false;
  };
  window.addEventListener("pagehide", flushOnExit);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushOnExit();
  });

  shell();
  window.onbeforeunload = (event) => {
    if (!dirty) return undefined;
    flushOnExit();
    // Browsers ignore custom text but still show their own confirmation.
    event.preventDefault();
    event.returnValue = "";
    return "";
  };
  return root;
}
