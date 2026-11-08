// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* The legal notice an administrator adds to their own instance.
 *
 * One document per language, written either in a rich surface (what most
 * people expect from "WYSIWYG") or as markdown, and stored through the wiki
 * markdown pipeline server side. The formatting offered here is the same
 * subset the wiki allows: headings, emphasis, lists, quotes, links, code.
 * There is no way to insert raw HTML, an iframe or a script, because neither
 * the surface nor the allowlist knows how.
 */

import { api } from "../api.js";
import { LANGUAGES, t } from "../i18n.js";
import { flagSvg } from "../flags.js";
import { htmlToMarkdown, markdownToHtml } from "../markdown.js";
import { escapeHtml } from "../sanitize.js";
import { confirmDialog, setBusy, toast } from "../ui.js";

const TOOLBAR = [
  { cmd: "bold", key: "wiki.fmt_bold", label: "B" },
  { cmd: "italic", key: "wiki.fmt_italic", label: "I" },
  { cmd: "h2", key: "wiki.block_h2", label: "H2" },
  { cmd: "ul", key: "wiki.fmt_list", label: "•" },
  { cmd: "quote", key: "wiki.fmt_quote", label: "❝" },
  { cmd: "link", key: "wiki.insert_link", label: "↗" },
];

export async function legalEditorView(panel) {
  let data;
  try {
    data = await api.get("/api/v1/admin/legal");
  } catch (error) {
    panel.innerHTML = `<div class="card empty">${escapeHtml(error.detail || t("error.generic"))}</div>`;
    return;
  }

  const values = { ...(data.values || {}) };
  const stamps = { ...(data.updated_at || {}) };
  const maxLength = Number(data.max_length) || 24000;
  const draft = {};
  const dirty = new Set();
  let language = "fr";
  let mode = "rich";

  panel.innerHTML = `
    <div class="legal-admin">
      <div class="list-head">
        <div>
          <h2>${escapeHtml(t("legal.admin_title"))}</h2>
          <p class="muted small">${escapeHtml(t("legal.admin_lead"))}</p>
        </div>
        <a class="btn btn-sm" href="/legal" data-link>${escapeHtml(t("legal.admin_view"))}</a>
      </div>
      <div class="legal-langs" role="tablist" aria-label="${escapeHtml(t("legal.admin_language"))}"></div>
      <div class="legal-editor">
        <div class="legal-toolbar">
          ${TOOLBAR.map(
            (item) =>
              `<button type="button" class="legal-tool" data-cmd="${item.cmd}" title="${escapeHtml(
                t(item.key),
              )}" aria-label="${escapeHtml(t(item.key))}">${item.label}</button>`,
          ).join("")}
          <span class="legal-modes">
            <button type="button" class="legal-mode is-active" data-mode="rich">${escapeHtml(t("legal.admin_edit"))}</button>
            <button type="button" class="legal-mode" data-mode="source">${escapeHtml(t("legal.admin_source"))}</button>
          </span>
        </div>
        <div class="legal-surface" contenteditable="true" spellcheck="true"
             aria-label="${escapeHtml(t("legal.admin_title"))}"></div>
        <textarea class="legal-source" hidden spellcheck="false"
                  aria-label="${escapeHtml(t("legal.admin_source"))}"></textarea>
        <p class="legal-hint muted small">${escapeHtml(t("legal.admin_help"))}</p>
      </div>
      <div class="legal-bar">
        <span class="legal-count muted small"></span>
        <span class="legal-dirty chip chip-sm" hidden>${escapeHtml(t("legal.admin_unsaved"))}</span>
        <span class="legal-translate ai-only">
          <select class="input input-sm legal-from" aria-label="${escapeHtml(t("legal.admin_translate_source"))}"></select>
          <button type="button" class="btn btn-sm" data-act="translate">${escapeHtml(t("legal.admin_translate"))}</button>
        </span>
        <button type="button" class="btn btn-sm btn-ghost" data-act="clear">${escapeHtml(t("legal.admin_clear"))}</button>
        <button type="button" class="btn btn-sm btn-primary" data-act="save">${escapeHtml(t("legal.admin_save"))}</button>
      </div>
    </div>`;

  const langsBox = panel.querySelector(".legal-langs");
  const surface = panel.querySelector(".legal-surface");
  const source = panel.querySelector(".legal-source");
  const counter = panel.querySelector(".legal-count");
  const dirtyChip = panel.querySelector(".legal-dirty");
  const fromSelect = panel.querySelector(".legal-from");
  const saveButton = panel.querySelector('[data-act="save"]');
  const translateButton = panel.querySelector('[data-act="translate"]');

  const currentMarkdown = () =>
    mode === "rich" ? htmlToMarkdown(surface.innerHTML).trim() : source.value.trim();

  const remember = () => {
    draft[language] = currentMarkdown();
    dirty.add(language);
    paintStatus();
  };

  const paintStatus = () => {
    const text = draft[language] ?? values[language] ?? "";
    counter.textContent = t("legal.admin_characters", { n: text.length, max: maxLength });
    dirtyChip.hidden = !dirty.has(language);
    for (const button of langsBox.querySelectorAll("[data-lang]")) {
      const has = (draft[button.dataset.lang] ?? values[button.dataset.lang] ?? "").trim().length > 0;
      button.classList.toggle("is-filled", has);
      button.classList.toggle("is-active", button.dataset.lang === language);
      button.setAttribute("aria-selected", button.dataset.lang === language ? "true" : "false");
    }
  };

  const paintLanguage = () => {
    const text = draft[language] ?? values[language] ?? "";
    source.value = text;
    surface.innerHTML = markdownToHtml(text);
    paintStatus();
  };

  const paintLanguages = () => {
    langsBox.innerHTML = LANGUAGES.map(
      (item) => `
      <button type="button" class="legal-lang" data-lang="${item.code}" role="tab"
              title="${escapeHtml(item.label)}">
        ${flagSvg(item.code)}<span>${escapeHtml(item.code.toUpperCase())}</span>
      </button>`,
    ).join("");
    paintStatus();
  };

  const paintFrom = () => {
    const choices = LANGUAGES.filter((item) => (draft[item.code] ?? values[item.code] ?? "").trim());
    fromSelect.innerHTML = choices.length
      ? choices
          .map((item) => `<option value="${item.code}">${escapeHtml(item.label)}</option>`)
          .join("")
      : `<option value="">${escapeHtml(t("legal.admin_need_text"))}</option>`;
    if (choices.some((item) => item.code === language)) fromSelect.value = language;
    else if (choices.length) fromSelect.value = choices[0].code;
  };

  langsBox.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-lang]");
    if (!button || button.dataset.lang === language) return;
    if (dirty.has(language) && currentMarkdown() !== (values[language] || "")) {
      const leave = await confirmDialog(
        t("legal.admin_unsaved"),
        t("legal.admin_unsaved"),
        t("action.confirm"),
      );
      if (!leave) return;
    }
    remember();
    language = button.dataset.lang;
    paintLanguage();
    paintFrom();
  });

  panel.querySelectorAll(".legal-mode").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.mode === mode) return;
      if (button.dataset.mode === "source") {
        source.value = currentMarkdown();
      } else {
        surface.innerHTML = markdownToHtml(source.value);
      }
      mode = button.dataset.mode;
      surface.hidden = mode !== "rich";
      source.hidden = mode !== "source";
      panel.querySelectorAll(".legal-mode").forEach((other) => {
        other.classList.toggle("is-active", other.dataset.mode === mode);
      });
      paintStatus();
    });
  });

  panel.querySelectorAll("[data-cmd]").forEach((button) => {
    button.addEventListener("mousedown", (event) => event.preventDefault()); // keep the selection
    button.addEventListener("click", () => {
      if (mode !== "rich") return;
      const command = button.dataset.cmd;
      surface.focus();
      if (command === "h2") document.execCommand("formatBlock", false, "<h2>");
      else if (command === "ul") document.execCommand("insertUnorderedList");
      else if (command === "quote") document.execCommand("formatBlock", false, "<blockquote>");
      else if (command === "link") {
        const answer = window.prompt(t("wiki.insert_link"), "https://");
        if (!answer) return;
        // A bare host becomes https: only http(s) can ever reach the page,
        // because the server allowlist drops every other scheme.
        const url = /^https?:\/\//i.test(answer) ? answer : `https://${answer.replace(/^\/+/, "")}`;
        document.execCommand("createLink", false, url);
      } else document.execCommand(command);
      remember();
    });
  });

  surface.addEventListener("input", remember);
  source.addEventListener("input", remember);

  panel.querySelector('[data-act="clear"]').addEventListener("click", async () => {
    const sure = await confirmDialog(t("legal.admin_clear"), t("legal.admin_empty"), t("action.delete"));
    if (!sure) return;
    surface.innerHTML = "";
    source.value = "";
    draft[language] = "";
    dirty.add(language);
    paintStatus();
  });

  saveButton.addEventListener("click", async () => {
    remember();
    const payload = {};
    for (const code of dirty) payload[code] = (draft[code] ?? "").trim();
    if (!Object.keys(payload).length) return;
    setBusy(saveButton, true, t("legal.admin_save"));
    try {
      const saved = await api.put("/api/v1/admin/legal", { values: payload });
      Object.assign(values, saved.values || {});
      for (const code of Object.keys(payload)) {
        if (!(code in (saved.values || {}))) delete values[code];
      }
      dirty.clear();
      paintStatus();
      toast(t("legal.admin_saved"), "success");
    } catch (error) {
      toast(error.detail || t("error.generic"), "error");
    } finally {
      setBusy(saveButton, false);
    }
  });

  translateButton.addEventListener("click", async () => {
    const origin = fromSelect.value;
    const text = (draft[origin] ?? values[origin] ?? "").trim();
    if (!origin || !text) {
      toast(t("legal.admin_need_text"), "error");
      return;
    }
    setBusy(translateButton, true, t("legal.admin_translating"));
    try {
      const result = await api.post("/api/v1/admin/legal/translate", {
        target: language,
        source: origin,
        text,
      });
      const translated = String(result.markdown || "").trim();
      if (!translated) throw new Error("empty");
      surface.innerHTML = markdownToHtml(translated);
      source.value = translated;
      draft[language] = translated;
      dirty.add(language);
      paintStatus();
      toast(t("legal.admin_translate_done"), "info", 7000);
    } catch (error) {
      toast(error.detail || t("legal.admin_translate_failed"), "error", 6000);
    } finally {
      setBusy(translateButton, false);
    }
  });

  paintLanguages();
  paintFrom();
  paintLanguage();
  if (stamps[language]) {
    // Nothing to show yet, but the stamp is what tells an editor the text is
    // old; it lives in the counter line rather than in a second banner.
    counter.title = new Date(stamps[language]).toLocaleString();
  }
  fromSelect.addEventListener("focus", paintFrom);
}
