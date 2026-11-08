// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Wiki editor: markdown, preview or WYSIWYG over the same document, plus AI. */

import { api, uploadImage } from "../api.js";
import {
  offsetInEditable,
  offsetInTextarea,
  offsetOfSelection,
  pointInEditable,
  pointInTextarea,
  setSelectionOffset,
  shiftOffset,
} from "../caret.js";
import { t } from "../i18n.js";
import { htmlToMarkdown, markdownToHtml, paintCustomColors } from "../markdown.js";
import { navigate } from "../router.js";
import { state } from "../store.js";
import { confirmDialog, escapeHtml, setBusy, showUploadProgress, toast } from "../ui.js";
import { applySplice, connectLive, initials, otherEditors } from "../wikiLive.js";

const DRAFT_PREFIX = "ol_wiki_draft_";

const ICONS = {
  bold: "<b>B</b>",
  italic: "<i>I</i>",
  underline: "<u>U</u>",
  strike: "<s>S</s>",
  heading: "H",
  list: "≡",
  quote: "❝",
  code: "&lt;/&gt;",
  link: "🔗",
  wikilink: "[[ ]]",
  image: "🖼",
  embed: '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="3" width="12" height="10" rx="1.6"/><path d="M6.6 6.8 4.4 8l2.2 1.2M9.4 6.8 11.6 8l-2.2 1.2"/></svg>',
  table: '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="2" y="3" width="12" height="10" rx="1.4"/><path d="M2 6.6h12M2 9.6h12M6.4 3v10M10.4 3v10"/></svg>',
  color: "🎨",
};

// Alignment icons: four line patterns, drawn rather than typed so they render
// the same in every language.
const ALIGN_ICONS = {
  left: '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M2 3h12M2 6.5h8M2 10h12M2 13.5h8"/></svg>',
  center: '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M2 3h12M4 6.5h8M2 10h12M4 13.5h8"/></svg>',
  right: '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M2 3h12M6 6.5h8M2 10h12M6 13.5h8"/></svg>',
  justify: '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M2 3h12M2 5.5h12M2 8h12M2 10.5h12M2 13h12"/></svg>',
};

// The palette both the toolbar and the renderer agree on: a class per colour,
// so nothing inline ever reaches the page (the CSP forbids style attributes).
const COLORS = ["red", "orange", "amber", "green", "teal", "blue", "violet", "pink"];

function draftKey(wikiId, pageId) {
  return `${DRAFT_PREFIX}${wikiId}_${pageId || "new"}`;
}

function tool(key, command, title) {
  return `<button type="button" class="ed-tool" data-cmd="${command}" title="${escapeHtml(title)}"
    aria-label="${escapeHtml(title)}">${ICONS[key]}</button>`;
}

export async function renderWikiEditor(params) {
  const root = document.createElement("section");
  await _wikiEditor(root, params);
  return root;
}

async function _wikiEditor(root, params) {
  const wikiId = Number(params.id);
  const pageId = params.pageId ? Number(params.pageId) : null;
  const proposing = location.pathname.includes("/propose/");

  if (!state.user) {
    navigate(`/login?next=${encodeURIComponent(location.pathname)}`, { replace: true });
    return;
  }

  let wiki;
  let page = null;
  try {
    wiki = await api.get(`/api/v1/wiki/${wikiId}`);
    if (pageId) page = await api.get(`/api/v1/wiki/pages/${pageId}`);
  } catch (error) {
    root.innerHTML = `<div class="card empty">${escapeHtml(error.detail || t("wiki.not_found"))}</div>`;
    return;
  }

  const model = {
    title: page ? page.title : "",
    tags: page ? (page.tags || []).join(", ") : "",
    content: page ? page.content_md : `# ${t("wiki.untitled")}\n\n`,
    // Empty until switchMode() runs, otherwise the first call returns early and
    // all three panes stay visible, one of them empty.
    mode: "",
  };

  const pageSlugMap = () => {
    const map = {};
    for (const entry of wiki.pages || []) map[entry.title.toLowerCase()] = entry.slug;
    return map;
  };

  root.className = "ed-shell";
  root.innerHTML = `
    <header class="ed-bar">
      <a class="ed-back" data-link href="/wiki/${wikiId}" title="${escapeHtml(t("action.back"))}"
         aria-label="${escapeHtml(t("action.back"))}">←</a>
      <div class="ed-titles">
        <input class="input ed-title" id="wiki-page-title" value="${escapeHtml(model.title)}"
               placeholder="${escapeHtml(t("wiki.page_title"))}" maxlength="200"
               aria-label="${escapeHtml(t("wiki.page_title"))}" />
        <div class="ed-tags-row">
          <input class="input ed-tags" id="wiki-page-tags" value="${escapeHtml(model.tags)}"
                 placeholder="${escapeHtml(t("wiki.tags_placeholder"))}" maxlength="240"
                 aria-label="${escapeHtml(t("wiki.tags_placeholder"))}" />
          ${
            pageId
              ? `<button class="btn btn-sm btn-ai" id="wiki-tags-ai" title="${escapeHtml(t("wiki.tags_ai"))}">
                   <span aria-hidden="true">✨</span> ${escapeHtml(t("wiki.tags_ai"))}
                 </button>`
              : ""
          }
        </div>
      </div>
      <div class="ed-bar-actions">
        <div class="ed-live" id="wiki-live" title="${escapeHtml(t("wiki.live_help"))}">
          <span class="ed-live-status" id="wiki-live-status" aria-live="polite"></span>
          <div class="ed-live-people" id="wiki-live-people"></div>
        </div>
        <span class="muted small" id="wiki-save-state"></span>
        ${pageId ? `<a class="btn btn-sm btn-ghost" data-link href="/wiki/${wikiId}/structure">${escapeHtml(t("wiki.structure"))}</a>` : ""}
        ${pageId ? `<a class="btn btn-sm btn-ghost" data-link href="/wiki/${wikiId}/history/${pageId}">${escapeHtml(t("wiki.history"))}</a>` : ""}
        <a class="btn btn-sm btn-ghost" data-link href="/wiki/${wikiId}">${escapeHtml(t("action.cancel"))}</a>
        <button class="btn btn-sm btn-primary" id="wiki-save">${escapeHtml(proposing ? t("wiki.send_proposal") : t("action.save"))}</button>
        ${pageId ? `<button class="btn btn-sm btn-ghost btn-danger" id="wiki-delete">${escapeHtml(t("action.delete"))}</button>` : ""}
      </div>
    </header>

    <div class="ed-modebar">
      <div class="segmented" role="tablist" aria-label="${escapeHtml(t("wiki.editor_mode"))}">
        <button type="button" class="seg" data-mode="wysiwyg" role="tab" aria-selected="true">${escapeHtml(t("wiki.wysiwyg"))}</button>
        <button type="button" class="seg" data-mode="markdown" role="tab" aria-selected="false">Markdown</button>
        <button type="button" class="seg" data-mode="preview" role="tab" aria-selected="false">${escapeHtml(t("wiki.preview"))}</button>
      </div>
      <div class="ed-tools" role="toolbar" aria-label="${escapeHtml(t("wiki.tools"))}">
        <select class="ed-block" id="wiki-block" aria-label="${escapeHtml(t("wiki.block_style"))}" title="${escapeHtml(t("wiki.block_style"))}">
          <option value="p">${escapeHtml(t("wiki.block_paragraph"))}</option>
          <option value="h1">${escapeHtml(t("wiki.block_h1"))}</option>
          <option value="h2">${escapeHtml(t("wiki.block_h2"))}</option>
          <option value="h3">${escapeHtml(t("wiki.block_h3"))}</option>
          <option value="h4">${escapeHtml(t("wiki.block_h4"))}</option>
        </select>
        <span class="ed-sep" aria-hidden="true"></span>
        ${tool("bold", "bold", t("wiki.fmt_bold"))}
        ${tool("italic", "italic", t("wiki.fmt_italic"))}
        ${tool("underline", "underline", t("wiki.fmt_underline"))}
        ${tool("strike", "strike", t("wiki.fmt_strike"))}
        ${tool("code", "code", t("wiki.fmt_code"))}
        <span class="ed-sep" aria-hidden="true"></span>
        ${tool("list", "list", t("wiki.fmt_list"))}
        ${tool("quote", "quote", t("wiki.fmt_quote"))}
        <span class="ed-sep" aria-hidden="true"></span>
        ${tool("link", "link", t("wiki.insert_link"))}
        ${tool("wikilink", "wikilink", t("wiki.insert_wikilink"))}
        ${tool("table", "table", t("wiki.insert_table"))}
        ${tool("embed", "embed", t("wiki.insert_quiz"))}
        <span class="ed-sep" aria-hidden="true"></span>
        <span class="ed-align" role="group" aria-label="${escapeHtml(t("wiki.fmt_align"))}">
          ${["left", "center", "right", "justify"]
            .map(
              (direction) =>
                `<button type="button" class="ed-tool" data-align="${direction}" title="${escapeHtml(
                  t(`wiki.align_${direction}`),
                )}" aria-label="${escapeHtml(t(`wiki.align_${direction}`))}">${ALIGN_ICONS[direction]}</button>`,
            )
            .join("")}
        </span>
        <select class="ed-block" id="wiki-size" aria-label="${escapeHtml(t("wiki.fmt_size"))}" title="${escapeHtml(t("wiki.fmt_size"))}">
          <option value="md">${escapeHtml(t("wiki.size_md"))}</option>
          <option value="lg">${escapeHtml(t("wiki.size_lg"))}</option>
          <option value="xl">${escapeHtml(t("wiki.size_xl"))}</option>
          <option value="sm">${escapeHtml(t("wiki.size_sm"))}</option>
        </select>
        <select class="ed-block" id="wiki-font" aria-label="${escapeHtml(t("wiki.fmt_font"))}" title="${escapeHtml(t("wiki.fmt_font"))}">
          <option value="sans">${escapeHtml(t("wiki.font_sans"))}</option>
          <option value="serif">${escapeHtml(t("wiki.font_serif"))}</option>
          <option value="mono">${escapeHtml(t("wiki.font_mono"))}</option>
          <option value="script">${escapeHtml(t("wiki.font_script"))}</option>
        </select>
        <span class="ed-colors" role="group" aria-label="${escapeHtml(t("wiki.fmt_color"))}">
          <button type="button" class="ed-tool ed-color-toggle" data-color-menu aria-expanded="false"
                  title="${escapeHtml(t("wiki.fmt_color"))}" aria-label="${escapeHtml(t("wiki.fmt_color"))}">${ICONS.color}</button>
          <span class="ed-color-menu" id="wiki-color-menu" hidden>
            ${COLORS.map(
              (name) =>
                `<button type="button" class="ed-swatch c-${name}" data-color="${name}" title="${name}"
                         aria-label="${name}"><span aria-hidden="true">A</span></button>`,
            ).join("")}
            <label class="ed-swatch-picker" title="${escapeHtml(t("wiki.fmt_color_custom"))}">
              <span aria-hidden="true">+</span>
              <input type="color" id="wiki-color-custom" value="#e5484d"
                     aria-label="${escapeHtml(t("wiki.fmt_color_custom"))}" />
            </label>
            <button type="button" class="ed-swatch ed-swatch-reset" data-color="none" title="${escapeHtml(t("wiki.fmt_color_none"))}"
                    aria-label="${escapeHtml(t("wiki.fmt_color_none"))}">✕</button>
          </span>
        </span>
        <label class="ed-tool ed-upload" title="${escapeHtml(t("wiki.insert_image"))}">
          <span aria-hidden="true">${ICONS.image}</span>
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" id="wiki-image-input" hidden />
        </label>
      </div>
      <span class="spacer"></span>
      <div class="ed-reviews ai-only" role="group" aria-label="${escapeHtml(t("ai.reviews_help"))}">
        <span class="ed-reviews-label" title="${escapeHtml(t("ai.reviews_help"))}">
          <span aria-hidden="true">✨</span> ${escapeHtml(t("ai.group"))}
        </span>
        <button type="button" class="btn btn-sm btn-ghost" data-open-ai title="${escapeHtml(t("ai.fill_help"))}">
          <span aria-hidden="true">✨</span> ${escapeHtml(t("ai.draft_button"))}
        </button>
        <button type="button" class="btn btn-sm btn-ghost" data-review="grammar" ${pageId ? "" : "disabled"} title="${escapeHtml(t("ai.grammar_help"))}">
          <span aria-hidden="true">✨</span> ${escapeHtml(t("ai.grammar"))}
        </button>
        <button type="button" class="btn btn-sm btn-ghost" data-review="review" ${pageId ? "" : "disabled"} title="${escapeHtml(t("ai.review_help"))}">
          <span aria-hidden="true">✨</span> ${escapeHtml(t("ai.review"))}
        </button>
        <button type="button" class="btn btn-sm btn-ghost" data-review="compliance" ${pageId ? "" : "disabled"} title="${escapeHtml(t("ai.compliance_help"))}">
          <span aria-hidden="true">✨</span> ${escapeHtml(t("ai.compliance"))}
        </button>
      </div>
      <span class="muted small ed-count" id="wiki-word-count"></span>
    </div>

    <div class="ed-review-strip" id="wiki-review-strip" hidden></div>

    <div class="ed-template-bar" id="wiki-template-bar" hidden>
      <label class="field-inline">
        <span>${escapeHtml(t("wiki.template_apply"))}</span>
        <select class="input input-sm" id="wiki-template-select"></select>
      </label>
      <span class="muted small">${escapeHtml(t("wiki.template_apply_help"))}</span>
    </div>

    <div class="ed-surface">
      <div id="wiki-status" class="visually-hidden" role="status" aria-live="polite" aria-atomic="true"></div>
      <textarea id="wiki-md" class="ed-textarea" spellcheck="true" aria-label="Markdown"></textarea>
      <div class="ed-wysiwyg wiki-content" id="wiki-wysiwyg" contenteditable="true" spellcheck="true"
           aria-label="${escapeHtml(t("wiki.wysiwyg"))}"></div>
      <div class="ed-preview wiki-content" id="wiki-preview" aria-live="polite"></div>
      <div class="ed-carets" id="wiki-carets" aria-hidden="true"></div>
      <div class="ed-drop" id="wiki-drop" hidden>
        <span>${escapeHtml(t("wiki.drop_image"))}</span>
      </div>
      <div class="ed-img-tools" id="wiki-img-tools" hidden>
        <span class="muted small">${escapeHtml(t("wiki.image_width"))}</span>
        <button type="button" class="btn btn-sm btn-ghost" data-width="25%">25%</button>
        <button type="button" class="btn btn-sm btn-ghost" data-width="50%">50%</button>
        <button type="button" class="btn btn-sm btn-ghost" data-width="75%">75%</button>
        <button type="button" class="btn btn-sm btn-ghost" data-width="100%">100%</button>
        <button type="button" class="btn btn-sm btn-ghost" data-width="" title="${escapeHtml(t("wiki.image_reset"))}">↺</button>
        <span class="ed-img-grip" title="${escapeHtml(t("wiki.image_drag"))}" aria-hidden="true"></span>
      </div>
      <div class="ed-link-picker" id="wiki-link-picker" hidden>
        <div class="ed-link-search">
          <input class="input input-sm" id="wiki-link-query" type="search"
                 placeholder="${escapeHtml(t("wiki.link_search_placeholder"))}"
                 aria-label="${escapeHtml(t("wiki.link_search_placeholder"))}" />
          <label class="check">
            <input type="checkbox" id="wiki-link-global" />
            <span>${escapeHtml(t("wiki.link_search_global"))}</span>
          </label>
        </div>
        <ul class="ed-link-results" id="wiki-link-results" role="listbox"></ul>
      </div>
    </div>

    <details class="ed-ai card ai-only" id="wiki-ai-panel" ${pageId ? "" : "open"}>
      <summary>
        <span><span aria-hidden="true">✨</span> ${escapeHtml(t("ai.panel_title"))}</span>
        <span class="muted small">${escapeHtml(t("ai.panel_help"))}</span>
      </summary>
      <div class="ed-ai-body">
        <label class="field ed-ai-brief">
          <span>${escapeHtml(t("ai.brief"))}</span>
          <textarea class="input" id="ai-brief" rows="5" maxlength="4000"
            placeholder="${escapeHtml(t("ai.brief_placeholder"))}"></textarea>
          <span class="muted small" id="ai-brief-count">0 / 4000</span>
        </label>
        <div class="ed-ai-grid">
          <label class="field">
            <span>${escapeHtml(t("ai.topic"))}</span>
            <input class="input input-sm" id="ai-topic" value="${escapeHtml(wiki.title)}" maxlength="300" />
          </label>
          <label class="field">
            <span>${escapeHtml(t("ai.style"))}</span>
            <select class="input input-sm" id="ai-style">
              <option value="light">${escapeHtml(t("ai.style_light"))}</option>
              <option value="balanced" selected>${escapeHtml(t("ai.style_balanced"))}</option>
              <option value="formal">${escapeHtml(t("ai.style_formal"))}</option>
              <option value="detailed">${escapeHtml(t("ai.style_detailed"))}</option>
              <option value="academic">${escapeHtml(t("ai.style_academic"))}</option>
            </select>
          </label>
          <label class="field">
            <span>${escapeHtml(t("ai.audience"))}</span>
            <input class="input input-sm" id="ai-audience" placeholder="${escapeHtml(t("ai.audience_hint"))}" maxlength="160" />
          </label>
        </div>
        <div class="ed-ai-actions">
          <label class="check">
            <input type="checkbox" id="ai-research" checked />
            <span>${escapeHtml(t("ai.research"))}</span>
          </label>
          <span class="spacer"></span>
          <button class="btn btn-primary" id="ai-generate">${escapeHtml(t("ai.fill"))}</button>
        </div>
        <p class="muted small">${escapeHtml(t("ai.fill_help"))}</p>
        <div class="ai-jobs" id="ai-jobs"></div>
      </div>
    </details>
  `;

  const titleInput = root.querySelector("#wiki-page-title");
  const tagsInput = root.querySelector("#wiki-page-tags");
  /* Formatting a block changes the text silently: a sighted author sees the
     weight change, a screen reader hears nothing at all. One polite region
     carries the result of every command. */
  const status = root.querySelector("#wiki-status");
  const announce = (message) => {
    if (!status) return;
    status.textContent = "";
    window.setTimeout(() => {
      status.textContent = message;
    }, 40);
  };

  const textarea = root.querySelector("#wiki-md");
  const preview = root.querySelector("#wiki-preview");
  const wysiwyg = root.querySelector("#wiki-wysiwyg");
  const stateLabel = root.querySelector("#wiki-save-state");
  const counter = root.querySelector("#wiki-word-count");

  textarea.value = model.content;
  let renderedMarkdown = model.content;
  wysiwyg.innerHTML = markdownToHtml(model.content, { pages: pageSlugMap() });
  paintCustomColors(wysiwyg);

  wysiwyg.addEventListener("input", () => {
    renderedMarkdown = null;
  });

  const currentMarkdown = () =>
    model.mode === "wysiwyg" ? htmlToMarkdown(wysiwyg.innerHTML) : textarea.value;

  const paintPreview = () => {
    preview.innerHTML = markdownToHtml(currentMarkdown(), { pages: pageSlugMap() });
    paintCustomColors(preview);
  };

  const paintCounter = () => {
    const words = currentMarkdown().trim().split(/\s+/).filter(Boolean).length;
    counter.textContent = t("wiki.word_count", { n: words });
  };

  // A draft records *author work*, never the fact that the page was opened:
  // writing one on render made every visit offer to restore the text that was
  // already on screen.
  const markDirty = () => {
    stateLabel.textContent = t("wiki.draft_saved");
    try {
      localStorage.setItem(
        draftKey(wikiId, pageId),
        JSON.stringify({ title: titleInput.value, tags: tagsInput.value, content: currentMarkdown() }),
      );
    } catch {
      /* storage full or disabled: the draft is a convenience, not a guarantee */
    }
  };

  /** Offer the local draft in a banner: a modal here froze the whole tab. */
  const offerDraft = () => {
    let raw = null;
    try {
      raw = localStorage.getItem(draftKey(wikiId, pageId));
    } catch {
      return;
    }
    if (!raw) return;
    let draft = null;
    try {
      draft = JSON.parse(raw);
    } catch {
      return;
    }
    if (!draft || (!draft.title && !draft.content)) return;
    // A draft identical to what is on screen is not work worth restoring.
    if ((draft.content || "") === model.content && (draft.title || "") === model.title) {
      localStorage.removeItem(draftKey(wikiId, pageId));
      return;
    }

    const banner = document.createElement("div");
    banner.className = "ed-draft-offer";
    banner.innerHTML = `
      <span>${escapeHtml(t("wiki.draft_found"))}</span>
      <span class="spacer"></span>
      <button type="button" class="btn btn-sm" data-draft="restore">${escapeHtml(t("wiki.draft_restore"))}</button>
      <button type="button" class="btn btn-sm btn-ghost" data-draft="discard">${escapeHtml(t("wiki.draft_discard"))}</button>
    `;
    root.querySelector(".ed-surface").before(banner);

    banner.querySelector('[data-draft="restore"]').addEventListener("click", () => {
      titleInput.value = draft.title || titleInput.value;
      tagsInput.value = draft.tags || "";
      textarea.value = draft.content || textarea.value;
      model.content = textarea.value;
      renderRich(textarea.value);
      liveShadow = textarea.value;
      paintPreview();
      paintCounter();
      markDirty();
      banner.remove();
    });
    banner.querySelector('[data-draft="discard"]').addEventListener("click", () => {
      try {
        localStorage.removeItem(draftKey(wikiId, pageId));
      } catch {
        /* storage disabled: nothing to clean */
      }
      banner.remove();
    });
  };

  /** Paint the rich view: markdown in, coloured text out. */
  const renderRich = (markdown) => {
    // What the surface shows: comparing avoids repainting identical content,
    // which used to wipe the caret while the author was typing.
    const next = String(markdown ?? "");
    if (renderedMarkdown === next && wysiwyg.firstChild) return;
    renderedMarkdown = next;
    wysiwyg.innerHTML = markdownToHtml(next, { pages: pageSlugMap() });
    paintCustomColors(wysiwyg);
  };

  const switchMode = (mode) => {
    if (mode === model.mode) return;
    const markdown = currentMarkdown();
    if (mode === "markdown") textarea.value = markdown;
    if (mode === "wysiwyg") renderRich(markdown);
    model.mode = mode;
    textarea.hidden = mode !== "markdown";
    wysiwyg.hidden = mode !== "wysiwyg";
    preview.hidden = mode !== "preview";
    if (mode === "preview") paintPreview();
    root.querySelectorAll("[data-mode]").forEach((button) => {
      const active = button.dataset.mode === mode;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
    });
    root.querySelector(".ed-tools").hidden = mode === "preview";
    announce(
      `${t("wiki.editor_mode")}: ${root.querySelector(`[data-mode="${mode}"]`)?.textContent?.trim() || mode}`
    );
    paintCounter();
    renderCarets();
  };

  /* Selection and formatting -------------------------------------------- */

  // Clicking a toolbar button must not steal the selection from the editable:
  // without this the browser collapses it and the command has nothing to wrap.
  const toolsBar = root.querySelector(".ed-tools");
  toolsBar.addEventListener("mousedown", (event) => {
    if (event.target.closest("button")) event.preventDefault();
  });

  let savedRange = null;
  let mdRange = null;

  const saveRichSelection = () => {
    const selection = window.getSelection();
    if (selection && selection.rangeCount && wysiwyg.contains(selection.getRangeAt(0).commonAncestorContainer)) {
      savedRange = selection.getRangeAt(0).cloneRange();
    }
  };

  const saveMarkdownSelection = () => {
    mdRange = { start: textarea.selectionStart, end: textarea.selectionEnd };
  };

  const restoreRichSelection = () => {
    if (!savedRange) return false;
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(savedRange);
    return true;
  };

  const richWrap = (tagName, attrs = {}) => {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (!wysiwyg.contains(range.commonAncestorContainer)) return;

    // Clicking the same button again removes the decoration.
    const anchorNode = range.commonAncestorContainer;
    const startElement = anchorNode.nodeType === Node.ELEMENT_NODE ? anchorNode : anchorNode.parentElement;
    const existing = startElement ? startElement.closest(tagName) : null;
    const wanted = attrs.class ? attrs.class : null;
    if (
      existing &&
      !range.collapsed &&
      wysiwyg.contains(existing) &&
      existing.contains(range.startContainer) &&
      existing.contains(range.endContainer) &&
      (!wanted || existing.classList.contains(wanted))
    ) {
      const parent = existing.parentNode;
      while (existing.firstChild) parent.insertBefore(existing.firstChild, existing);
      parent.removeChild(existing);
      parent.normalize();
      wysiwyg.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }

    const element = document.createElement(tagName);
    Object.entries(attrs).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      element.setAttribute(key, value);
    });
    if (range.collapsed) {
      // A bare click: leave a caret inside the new decoration so typing lands in it.
      element.appendChild(document.createTextNode("\u200b"));
      range.insertNode(element);
      const caret = document.createRange();
      caret.setStart(element.firstChild, 1);
      caret.collapse(true);
      selection.removeAllRanges();
      selection.addRange(caret);
    } else {
      try {
        range.surroundContents(element);
      } catch {
        // A selection crossing element boundaries cannot be surrounded.
        element.appendChild(range.extractContents());
        range.insertNode(element);
      }
      const keep = document.createRange();
      keep.selectNodeContents(element);
      selection.removeAllRanges();
      selection.addRange(keep);
    }
    wysiwyg.focus();
    wysiwyg.dispatchEvent(new Event("input", { bubbles: true }));
  };

  const richBlock = (tag) => {
    // `formatBlock` acts on the live selection, so focus comes first and the
    // saved range is put back on top of it.
    wysiwyg.focus();
    restoreRichSelection();
    document.execCommand("formatBlock", false, `<${tag}>`);
    wysiwyg.dispatchEvent(new Event("input", { bubbles: true }));
  };

  // Alignment, size and typeface are properties of the block: the toolbar sets
  // a class, and htmlToMarkdown writes the matching {a:…}/{s:…}/{f:…} marker.
  /* Every block the selection touches, not only the one it starts in.
   *
   * Alignment, size and font are block properties, and a selection that spans
   * the whole page covers many blocks. Acting on `getRangeAt(0).startContainer`
   * alone justified the first paragraph and left the rest untouched, which reads
   * as a dead button when the selection is not where the author thinks it is. */
  const selectedBlocks = () => {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount) return [];
    const range = selection.getRangeAt(0);
    const selector = "p, h1, h2, h3, h4, h5, h6, li, blockquote";
    if (range.collapsed) {
      const anchor = range.startContainer;
      const element = anchor.nodeType === Node.ELEMENT_NODE ? anchor : anchor.parentElement;
      const block = element ? element.closest(`${selector}, div`) : null;
      return block && block !== wysiwyg && wysiwyg.contains(block) ? [block] : [];
    }
    return Array.from(wysiwyg.querySelectorAll(selector)).filter(
      (node) => node !== wysiwyg && wysiwyg.contains(node) && range.intersectsNode(node),
    );
  };

  const richBlockClass = (prefix, value, defaults) => {
    wysiwyg.focus();
    restoreRichSelection();
    const blocks = selectedBlocks();
    if (!blocks.length) return;
    for (const block of blocks) {
      Array.from(block.classList)
        .filter((name) => name.startsWith(`${prefix}-`))
        .forEach((name) => block.classList.remove(name));
      if (!defaults.includes(value)) block.classList.add(`${prefix}-${value}`);
    }
    wysiwyg.dispatchEvent(new Event("input", { bubbles: true }));
  };

  const mdSelectedLines = () => {
    const value = textarea.value;
    const start = value.lastIndexOf("\n", textarea.selectionStart - 1) + 1;
    let end = value.indexOf("\n", textarea.selectionEnd);
    if (end === -1) end = value.length;
    return { start, end, text: value.slice(start, end) };
  };

  const mdBlockClass = (prefix, value, defaults) => {
    const { start, end, text } = mdSelectedLines();
    let inner = text.trim();
    inner = inner
      .replace(new RegExp(`^\\{${prefix}:[a-z]+\\}`), "")
      .replace(new RegExp(`\\{\\/${prefix}\\}$`), "")
      .trim();
    if (inner && !defaults.includes(value)) inner = `{${prefix}:${value}}${inner}{/${prefix}}`;
    textarea.value = textarea.value.slice(0, start) + inner + textarea.value.slice(end);
    textarea.selectionStart = start;
    textarea.selectionEnd = start + inner.length;
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  };

  const insertTable = () => {
    const columns = 3;
    if (model.mode === "wysiwyg") {
      wysiwyg.focus();
      restoreRichSelection();
      const table = document.createElement("table");
      const head = document.createElement("thead");
      const headRow = document.createElement("tr");
      for (let index = 0; index < columns; index += 1) {
        const cell = document.createElement("th");
        cell.appendChild(document.createElement("br"));
        headRow.appendChild(cell);
      }
      head.appendChild(headRow);
      const body = document.createElement("tbody");
      const bodyRow = document.createElement("tr");
      for (let index = 0; index < columns; index += 1) {
        const cell = document.createElement("td");
        cell.appendChild(document.createElement("br"));
        bodyRow.appendChild(cell);
      }
      body.appendChild(bodyRow);
      table.append(head, body);
      const selection = window.getSelection();
      const range = selection && selection.rangeCount ? selection.getRangeAt(0) : null;
      if (range && wysiwyg.contains(range.commonAncestorContainer)) {
        range.deleteContents();
        range.insertNode(table);
      } else {
        wysiwyg.appendChild(table);
      }
      const paragraph = document.createElement("p");
      paragraph.appendChild(document.createElement("br"));
      table.after(paragraph);
      const caret = document.createRange();
      caret.setStart(headRow.firstChild.firstChild, 0);
      caret.collapse(true);
      selection.removeAllRanges();
      selection.addRange(caret);
      wysiwyg.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    const header = `| ${Array.from({ length: columns }, (_, index) => `${t("wiki.table_column")} ${index + 1}`).join(" | ")} |`;
    const rule = `| ${Array.from({ length: columns }, () => "---").join(" | ")} |`;
    const body = `| ${Array.from({ length: columns }, () => " ").join(" | ")} |`;
    const skeleton = `${header}\n${rule}\n${body}\n`;
    const value = textarea.value;
    const start = textarea.selectionStart;
    textarea.value = value.slice(0, start) + skeleton + value.slice(textarea.selectionEnd);
    textarea.selectionStart = start + skeleton.length;
    textarea.selectionEnd = textarea.selectionStart;
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  };

  // Attached questionnaires can be dropped anywhere in the page: the marker
  // becomes a live card in the reader, not a link leaving the article.
  const insertEmbed = (kind, id) => {
    const marker = `{${kind}:${id}}`;
    if (model.mode !== "wysiwyg") {
      const value = textarea.value;
      const start = textarea.selectionStart;
      const before = value.slice(0, start);
      const pad = before && !before.endsWith("\n\n") ? "\n\n" : "";
      const text = `${pad}${marker}\n\n`;
      textarea.value = before + text + value.slice(textarea.selectionEnd);
      textarea.selectionStart = textarea.selectionEnd = start + text.length;
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    wysiwyg.focus();
    restoreRichSelection();
    const block = document.createElement("div");
    block.className = "wiki-embed";
    block.dataset.embed = kind;
    block.dataset.id = String(id);
    block.contentEditable = "false";
    block.textContent = marker;
    const selection = window.getSelection();
    const range = selection && selection.rangeCount ? selection.getRangeAt(0) : null;
    const paragraph = document.createElement("p");
    paragraph.appendChild(document.createElement("br"));
    if (range && wysiwyg.contains(range.commonAncestorContainer)) {
      range.deleteContents();
      range.insertNode(block);
      block.after(paragraph);
    } else {
      wysiwyg.append(block, paragraph);
    }
    const caret = document.createRange();
    caret.setStart(paragraph, 0);
    caret.collapse(true);
    selection.removeAllRanges();
    selection.addRange(caret);
    wysiwyg.dispatchEvent(new Event("input", { bubbles: true }));
  };

  const openEmbedPicker = async () => {
    saveRichSelection();
    let items = [];
    try {
      const [result, decks] = await Promise.all([
        api.get(`/api/v1/wiki/${wikiId}/quizzes`),
        api.get(`/api/v1/decks?wiki_id=${wikiId}`).catch(() => ({ items: [] })),
      ]);
      items = (result.items || []).map((item) => ({
        kind: item.mode === "adventure" ? "adventure" : "quiz",
        id: item.id,
        title: item.title,
        label: item.mode === "adventure" ? t("wiki.embed_adventure") : item.mode === "swipe" ? t("wiki.embed_swipe") : t("wiki.embed_quiz"),
      }));
      // Decks made from this wiki's pages belong to the same article.
      (decks.items || []).forEach((deck) => {
        items.push({ kind: "deck", id: deck.id, title: deck.title, label: t("wiki.embed_deck") });
      });
    } catch (error) {
      toast(error.detail || t("common.error"), "error");
      return;
    }
    if (!items.length) {
      toast(t("wiki.embed_none"), "error");
      return;
    }
    const panel = document.createElement("div");
    panel.className = "ed-embed-menu";
    panel.innerHTML = `
      <p class="ed-embed-title">${escapeHtml(t("wiki.embed_choose"))}</p>
      ${items
        .map(
          (item) =>
            `<button type="button" class="ed-embed-item" data-kind="${item.kind}" data-id="${item.id}">
               <span>${escapeHtml(item.title || "")}</span>
               <span class="muted small">${escapeHtml(item.label)}</span>
             </button>`,
        )
        .join("")}`;
    root.querySelector(".ed-surface").appendChild(panel);
    const close = () => panel.remove();
    panel.addEventListener("click", (event) => {
      const button = event.target.closest("[data-id]");
      if (!button) return;
      insertEmbed(button.dataset.kind, Number(button.dataset.id));
      close();
    });
    document.addEventListener("mousedown", function outside(clickEvent) {
      if (!panel.contains(clickEvent.target)) {
        close();
        document.removeEventListener("mousedown", outside);
      }
    });
  };

  const richLink = (href, label, extra = {}) => {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (!wysiwyg.contains(range.commonAncestorContainer)) return;
    const anchor = document.createElement("a");
    anchor.setAttribute("href", href);
    Object.entries(extra).forEach(([key, value]) => anchor.setAttribute(key, value));
    if (range.collapsed) {
      anchor.textContent = label || href;
      range.insertNode(anchor);
      const caret = document.createRange();
      caret.setStartAfter(anchor);
      caret.collapse(true);
      selection.removeAllRanges();
      selection.addRange(caret);
    } else {
      try {
        range.surroundContents(anchor);
      } catch {
        anchor.appendChild(range.extractContents());
        range.insertNode(anchor);
      }
    }
    wysiwyg.focus();
    wysiwyg.dispatchEvent(new Event("input", { bubbles: true }));
  };

  /** Colour: a class for the palette, a validated hex for the picker. */
  const richColor = (value) => {
    if (!value || value === "none") {
      const selection = window.getSelection();
      if (!selection || !selection.rangeCount) return;
      const range = selection.getRangeAt(0);
      wysiwyg.querySelectorAll("span[class*='c-']").forEach((span) => {
        if (!selection.containsNode(span, true)) return;
        const parent = span.parentNode;
        while (span.firstChild) parent.insertBefore(span.firstChild, span);
        parent.removeChild(span);
      });
      wysiwyg.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    if (/^#[0-9a-fA-F]{6}$/.test(value)) {
      richWrap("span", { class: "c-hex", "data-hex": value.toLowerCase() });
      // Immediate feedback: CSP blocks style attributes, the CSSOM does not.
      wysiwyg.querySelectorAll("span.c-hex[data-hex]").forEach((span) => {
        span.style.color = span.getAttribute("data-hex");
      });
      return;
    }
    richWrap("span", { class: `c-${value}` });
  };

  const wrapSelection = (before, after = before) => {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selected = textarea.value.slice(start, end);
    textarea.value =
      textarea.value.slice(0, start) + before + selected + after + textarea.value.slice(end);
    textarea.selectionStart = start + before.length;
    textarea.selectionEnd = start + before.length + selected.length;
    textarea.focus();
    paintCounter();
    markDirty();
  };

  /** Insert a link to the chosen page: local wiki link, or a full URL. */
  const insertWikilink = (hit) => {
    const isLocal = hit.wiki_id === wikiId;
    const href = isLocal ? `/wiki/p/${hit.slug}` : `/wiki/${hit.wiki_id}/p/${hit.slug}`;
    if (model.mode === "wysiwyg") {
      restoreRichSelection();
      richLink(href, hit.title, {
        class: isLocal ? "wikilink" : "",
        "data-wikilink-target": isLocal ? hit.slug : "",
        "data-link": "",
      });
      return;
    }
    if (mdRange) textarea.setSelectionRange(mdRange.start, mdRange.end);
    const label = hit.title && hit.title !== hit.slug ? `|${hit.title}` : "";
    // A wikilink resolves inside its own wiki only, so a page hosted elsewhere
    // is inserted as a normal link that carries the wiki in its path.
    const snippet = isLocal
      ? `[[${hit.slug}${label}]]`
      : `[${hit.title}](/wiki/${hit.wiki_id}/p/${hit.slug})`;
    wrapSelection("", snippet);
  };

  const prefixLine = (prefix, block) => {
    const start = textarea.selectionStart;
    const lineStart = textarea.value.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
    textarea.value = textarea.value.slice(0, lineStart) + prefix + textarea.value.slice(lineStart);
    textarea.focus();
    paintCounter();
    markDirty();
  };

  /** Heading level in markdown mode: rewrite the marker of every selected line. */
  const setMarkdownBlock = (value) => {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const from = textarea.value.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
    let to = textarea.value.indexOf("\n", end);
    if (to === -1) to = textarea.value.length;
    const prefix = value === "p" ? "" : `${"#".repeat(Number(value[1]))} `;
    const block = textarea.value
      .slice(from, to)
      .split("\n")
      .map((line) => `${prefix}${line.replace(/^#{1,6}\s+/, "")}`)
      .join("\n");
    textarea.value = textarea.value.slice(0, from) + block + textarea.value.slice(to);
    textarea.focus();
    paintCounter();
    markDirty();
  };

  const blockSelect = root.querySelector("#wiki-block");
  blockSelect.addEventListener("mousedown", () => {
    if (model.mode === "wysiwyg") saveRichSelection();
    else saveMarkdownSelection();
  });
  blockSelect.addEventListener("change", () => {
    const value = blockSelect.value;
    if (model.mode === "wysiwyg") {
      richBlock(value);
    } else {
      textarea.focus();
      if (mdRange) textarea.setSelectionRange(mdRange.start, mdRange.end);
      setMarkdownBlock(value);
    }
  });

  const colorMenu = root.querySelector("#wiki-color-menu");
  const colorToggle = root.querySelector("[data-color-menu]");
  colorToggle.addEventListener("click", () => {
    const open = colorMenu.hidden;
    saveRichSelection();
    colorMenu.hidden = !open;
    colorToggle.setAttribute("aria-expanded", String(open));
  });
  colorMenu.addEventListener("click", (event) => {
    const swatch = event.target.closest("[data-color]");
    if (!swatch) return;
    richColor(swatch.dataset.color);
    colorMenu.hidden = true;
    colorToggle.setAttribute("aria-expanded", "false");
  });
  root.querySelector("#wiki-color-custom").addEventListener("input", (event) => {
    richColor(event.target.value);
  });

  root.querySelectorAll("[data-align]").forEach((button) => {
    button.addEventListener("click", () => {
      saveRichSelection();
      const direction = button.dataset.align;
      if (model.mode === "wysiwyg") richBlockClass("al", direction, ["left"]);
      else mdBlockClass("a", direction, ["left"]);
    });
  });
  root.querySelector("#wiki-size").addEventListener("change", (event) => {
    const value = event.target.value;
    if (model.mode === "wysiwyg") richBlockClass("sz", value, ["md"]);
    else mdBlockClass("s", value, ["md"]);
    event.target.value = "md";
  });
  root.querySelector("#wiki-font").addEventListener("change", (event) => {
    const value = event.target.value;
    if (model.mode === "wysiwyg") richBlockClass("ff", value, ["sans"]);
    else mdBlockClass("f", value, ["sans"]);
    event.target.value = "sans";
  });

  root.querySelectorAll("[data-cmd]").forEach((button) => {
    button.addEventListener("click", () => {
      const command = button.dataset.cmd;
      announce(`${button.getAttribute("aria-label") || command} — ${t("wiki.applied")}`);
      if (model.mode === "wysiwyg") {
        switch (command) {
          case "bold":
            richWrap("strong");
            break;
          case "italic":
            richWrap("em");
            break;
          case "underline":
            richWrap("u");
            break;
          case "strike":
            richWrap("s");
            break;
          case "code":
            richWrap("code");
            break;
          case "h2":
            richBlock("h2");
            break;
          case "quote":
            richBlock("blockquote");
            break;
          case "list":
            wysiwyg.focus();
            document.execCommand("insertUnorderedList");
            wysiwyg.dispatchEvent(new Event("input", { bubbles: true }));
            break;
          case "link": {
            const url = window.prompt(t("wiki.link_prompt"), "https://");
            if (url) richLink(url, url, /^https?:/i.test(url) ? {} : { "data-link": "" });
            break;
          }
          case "table":
            insertTable();
            break;
          case "embed":
            openEmbedPicker();
            break;
          case "wikilink":
            // The picker searches titles instead of asking for one from memory.
            saveRichSelection();
            openPicker();
            break;
          default:
            break;
        }
        return;
      }
      switch (command) {
        case "bold":
          wrapSelection("**");
          break;
        case "italic":
          wrapSelection("*");
          break;
        case "underline":
          wrapSelection("{u}", "{/u}");
          break;
        case "strike":
          wrapSelection("~~");
          break;
        case "code":
          wrapSelection("`");
          break;
        case "h2":
          prefixLine("## ");
          break;
        case "quote":
          prefixLine("> ");
          break;
        case "list":
          prefixLine("- ");
          break;
        case "table":
          insertTable();
          break;
        case "embed":
          openEmbedPicker();
          break;
        case "link": {
          const url = window.prompt(t("wiki.link_prompt"), "https://");
          if (url) wrapSelection("[", `](${url})`);
          break;
        }
        case "wikilink":
          saveMarkdownSelection();
          openPicker();
          break;
        default:
          break;
      }
    });
  });

  root.querySelectorAll("[data-mode]").forEach((button) => {
    button.addEventListener("click", () => switchMode(button.dataset.mode));
  });

  textarea.addEventListener("input", () => {
    touchedByAuthor = true;
    paintCounter();
    markDirty();
    notifyChange();
  });
  wysiwyg.addEventListener("input", () => {
    touchedByAuthor = true;
    paintCounter();
    markDirty();
    notifyChange();
  });
  titleInput.addEventListener("input", markDirty);
  tagsInput.addEventListener("input", markDirty);

  // The assistant proposes tags; the author decides which ones stay.
  const tagsButton = root.querySelector("#wiki-tags-ai");
  if (tagsButton) {
    tagsButton.addEventListener("click", async () => {
      setBusy(tagsButton, true);
      try {
        const result = await api.post(`/api/v1/wiki/pages/${pageId}/ai/tags`);
        const current = tagsInput.value
          .split(",")
          .map((tag) => tag.trim().toLowerCase())
          .filter(Boolean);
        for (const tag of result.tags || []) {
          if (!current.includes(tag.toLowerCase()) && current.length < 12) {
            current.push(tag);
          }
        }
        tagsInput.value = current.join(", ");
        markDirty();
        toast(t("wiki.tags_added"), "success");
      } catch (error) {
        toast(error.detail || t("common.error"), "error");
      } finally {
        setBusy(tagsButton, false);
      }
    });
  }

  const imageInput = root.querySelector("#wiki-image-input");
  imageInput.addEventListener("change", async () => {
    const file = imageInput.files && imageInput.files[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      toast(t("wiki.image_too_large", { mb: 10 }), "error");
      return;
    }
    const progress = showUploadProgress(t("wiki.uploading"), file.name);
    try {
      const uploaded = await uploadImage(
        file,
        (ratio) => progress.update(ratio),
        "/api/v1/uploads/image",
      );
      insertImageAt(null, uploaded.path, askImageAlt(file.name.replace(/\.[^.]+$/, "")));
    } catch (error) {
      toast(error.detail || t("error.generic"), "error");
    } finally {
      progress.done();
      imageInput.value = "";
    }
  });

  /* --------------------------------------------------------------------- */
  /* Images: picker, drag and drop, clipboard                              */
  /* --------------------------------------------------------------------- */
  const surface = root.querySelector(".ed-surface");
  const carets = root.querySelector("#wiki-carets");
  const dropZone = root.querySelector("#wiki-drop");

  let sendTimer = null;
  let lastSent = null;
  // Set on the first real edit: from then on the screen shows author work.
  let touchedByAuthor = false;
  let live = null;
  let liveShadow = model.content;
  const remoteCarets = new Map();

  const notifyChange = () => {
    if (!live) return;
    window.clearTimeout(sendTimer);
    sendTimer = window.setTimeout(() => {
      const text = currentMarkdown();
      if (text === lastSent) return;
      lastSent = text;
      live.sendText(text);
    }, 180);
  };

  /* An image dropped in with no description is a hole in the page for anyone
     using a screen reader. The author is asked once, at the moment they still
     know why the picture is there; an empty answer is a valid "decorative". */
  const askImageAlt = (suggested) => {
    const answer = window.prompt(t("wiki.image_alt_prompt"), suggested);
    if (answer === null) return suggested;
    return answer.trim();
  };

  const insertImageAt = (point, path, alt) => {
    if (model.mode === "markdown") {
      const offset = point
        ? offsetInTextarea(textarea, point.x, point.y)
        : textarea.selectionStart || textarea.value.length;
      const snippet = `\n\n![${alt}](${path})\n`;
      textarea.value = `${textarea.value.slice(0, offset)}${snippet}${textarea.value.slice(offset)}`;
      const caret = offset + snippet.length;
      textarea.focus();
      textarea.setSelectionRange(caret, caret);
    } else if (model.mode === "wysiwyg") {
      const offset = point ? offsetInEditable(wysiwyg, point.x, point.y) : offsetOfSelection(wysiwyg);
      wysiwyg.focus();
      setSelectionOffset(wysiwyg, offset);
      // Inside a paragraph that already carries text the image belongs in the
      // flow; on its own it becomes a block of its own.
      const caretBlock = window.getSelection()?.anchorNode
        ?.parentElement?.closest("p, li, blockquote")
        ?.textContent.trim();
      // The node is built and inserted by hand: `execCommand("insertHTML")`
      // lets the browser rewrite the fragment with inline styles, which the CSP
      // rightly refuses.
      const image = document.createElement("img");
      image.src = path;
      image.alt = alt;
      image.loading = "lazy";
      const selection = window.getSelection();
      if (!selection || !selection.rangeCount) return;
      const range = selection.getRangeAt(0);
      range.deleteContents();
      const fragment = document.createDocumentFragment();
      if (caretBlock) {
        // A space on each side keeps the image from being glued to the words
        // once the flow is written back to markdown.
        fragment.append(document.createTextNode(" "), image, document.createTextNode(" "));
      } else {
        const figure = document.createElement("figure");
        const paragraph = document.createElement("p");
        paragraph.appendChild(document.createElement("br"));
        figure.appendChild(image);
        fragment.append(figure, paragraph);
      }
      range.insertNode(fragment);
      const tail = image.closest("figure") ? image.closest("figure").nextSibling?.firstChild : image.nextSibling;
      if (tail) {
        const caretRange = document.createRange();
        caretRange.setStart(tail.nodeType === Node.TEXT_NODE ? tail : tail.parentNode, tail.nodeType === Node.TEXT_NODE ? tail.nodeValue.length : 0);
        caretRange.collapse(true);
        selection.removeAllRanges();
        selection.addRange(caretRange);
      }
    } else {
      textarea.value = `${textarea.value}\n\n![${alt}](${path})\n`;
      paintPreview();
    }
    paintCounter();
    markDirty();
    notifyChange();
  };

  const uploadAndInsert = async (file, point) => {
    if (!file || !file.type || !file.type.startsWith("image/")) return;
    if (file.size > 10 * 1024 * 1024) {
      toast(t("wiki.image_too_large", { mb: 10 }), "error");
      return;
    }
    const progress = showUploadProgress(t("wiki.uploading"), file.name);
    try {
      const uploaded = await uploadImage(
        file,
        (ratio) => progress.update(ratio),
        "/api/v1/uploads/image",
      );
      insertImageAt(point, uploaded.path, askImageAlt(file.name.replace(/\.[^.]+$/, "")));
    } catch (error) {
      toast(error.detail || t("error.generic"), "error");
    } finally {
      progress.done();
    }
  };

  const carriesFiles = (event) =>
    Boolean(event.dataTransfer) && Array.from(event.dataTransfer.types || []).includes("Files");

  let dragDepth = 0;
  surface.addEventListener("dragenter", (event) => {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    dragDepth += 1;
    dropZone.hidden = false;
  });
  surface.addEventListener("dragover", (event) => {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  surface.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) dropZone.hidden = true;
  });
  surface.addEventListener("drop", async (event) => {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    dragDepth = 0;
    dropZone.hidden = true;
    const point = { x: event.clientX, y: event.clientY };
    const files = Array.from(event.dataTransfer.files || []).filter((file) =>
      (file.type || "").startsWith("image/"),
    );
    for (const file of files) await uploadAndInsert(file, point);
  });
  surface.addEventListener("paste", async (event) => {
    const items = Array.from(event.clipboardData?.items || []);
    const images = items
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (!images.length) return;
    event.preventDefault();
    for (const file of images) await uploadAndInsert(file, null);
  });

  /* --------------------------------------------------------------------- */
  /* Real-time co-editing: presence, carets, live text                     */
  /* --------------------------------------------------------------------- */
  const liveStatus = root.querySelector("#wiki-live-status");
  const livePeople = root.querySelector("#wiki-live-people");

  const paintPeople = (users) => {
    const others = otherEditors(users, live ? live.me : null);
    livePeople.replaceChildren();
    for (const user of others) {
      const chip = document.createElement("span");
      chip.className = "ed-person";
      chip.style.background = user.color;
      chip.title = user.can_write ? user.name : `${user.name} · ${t("wiki.live_reader")}`;
      chip.textContent = initials(user.name);
      livePeople.appendChild(chip);
    }
    if (!live || !live.connected) {
      liveStatus.textContent = t("wiki.live_offline");
      liveStatus.classList.add("is-offline");
    } else {
      liveStatus.classList.remove("is-offline");
      liveStatus.textContent = others.length
        ? t("wiki.live_editing", { n: others.length })
        : t("wiki.live_alone");
    }
  };

  const adopt = (text, op) => {
    const focused = document.activeElement;
    let caret = null;
    if (model.mode === "markdown") caret = textarea.selectionStart;
    else if (focused === wysiwyg) caret = offsetOfSelection(wysiwyg);
    textarea.value = text;
    renderRich(text);
    if (model.mode === "preview") paintPreview();
    if (caret !== null) {
      const shifted =
        op === undefined
          ? Math.min(caret, text.length)
          : Math.min(shiftOffset(caret, op.pos, op.delete, op.insert), text.length);
      if (model.mode === "markdown") textarea.setSelectionRange(shifted, shifted);
      else setSelectionOffset(wysiwyg, shifted);
    }
    paintCounter();
  };

  const renderCarets = () => {
    carets.replaceChildren();
    const pane =
      model.mode === "markdown" ? textarea : model.mode === "wysiwyg" ? wysiwyg : null;
    if (!pane) return;
    const paneBox = pane.getBoundingClientRect();
    const surfaceBox = surface.getBoundingClientRect();
    for (const info of remoteCarets.values()) {
      const point =
        model.mode === "markdown"
          ? pointInTextarea(textarea, info.anchor)
          : pointInEditable(wysiwyg, info.anchor);
      const caretNode = document.createElement("div");
      caretNode.className = "ed-caret";
      caretNode.style.left = `${paneBox.left - surfaceBox.left + point.x}px`;
      caretNode.style.top = `${paneBox.top - surfaceBox.top + point.y}px`;
      caretNode.style.height = `${point.height}px`;
      caretNode.style.background = info.color;
      const label = document.createElement("span");
      label.className = "ed-caret-label";
      label.style.background = info.color;
      label.textContent = info.name;
      caretNode.appendChild(label);
      carets.appendChild(caretNode);
    }
  };

  const publishCursor = () => {
    if (!live || !live.connected) return;
    let offset = null;
    if (model.mode === "markdown") offset = textarea.selectionStart;
    else if (document.activeElement === wysiwyg) offset = offsetOfSelection(wysiwyg);
    if (offset === null) return;
    live.sendCursor(offset, offset);
  };
  let cursorTimer = null;
  const publishCursorSoon = () => {
    window.clearTimeout(cursorTimer);
    cursorTimer = window.setTimeout(publishCursor, 120);
  };

  if (pageId) {
    live = connectLive(pageId, {
      onHello: (hello) => {
        liveShadow = hello.content;
        // A socket that comes up late must not swallow keystrokes already on
        // screen: those are merged on the next send, not discarded.
        if (!touchedByAuthor && hello.content !== currentMarkdown()) adopt(hello.content);
        paintPeople(hello.users || []);
      },
      onPresence: (users) => paintPeople(users),
      onOp: (op) => {
        liveShadow = applySplice(liveShadow, op.pos, op.delete, op.insert);
        if (op.conflict) toast(t("wiki.live_conflict"), "error");
        // Our own edit is already on screen: re-rendering the surface from the
        // echo rebuilt the DOM under the author's caret and put it back at the
        // wrong place (the end of the heading, which is why typed text kept the
        // heading's colour). Only a conflict needs the server's version.
        if (op.isMine && !op.conflict) return;
        const local = currentMarkdown();
        if (liveShadow === local) return;
        // Local keystrokes not yet acknowledged are merged by the server on the
        // next send: never throw them away to show someone else's edit.
        const pending = lastSent !== null && local !== lastSent;
        if (!pending) adopt(liveShadow, op);
      },
      onReset: (message) => {
        liveShadow = message.content;
        lastSent = null;
        // Saving broadcasts the saved text to every editor of the page,
        // including the one that just saved: re-rendering the surface from a copy
        // identical to what is on screen rebuilt the DOM under the caret for
        // nothing, and the author went on typing in the wrong block.
        if (message.content !== currentMarkdown()) adopt(message.content);
        paintPeople(live.users || []);
      },
      onResync: (message) => {
        liveShadow = message.content;
        lastSent = null;
        // Adopting a copy identical to what is on screen rebuilds the surface and
        // moves the caret: skip it.
        if (message.content !== currentMarkdown()) adopt(message.content);
      },
      onCursor: (cursor) => {
        remoteCarets.set(cursor.client_id, cursor);
        renderCarets();
      },
      onDenied: () => toast(t("wiki.live_readonly"), "info"),
      onStatus: () => paintPeople(live ? live.users : []),
    });

    textarea.addEventListener("keyup", publishCursorSoon);
    textarea.addEventListener("click", publishCursorSoon);
    textarea.addEventListener("scroll", renderCarets);
    wysiwyg.addEventListener("keyup", publishCursorSoon);
    wysiwyg.addEventListener("click", publishCursorSoon);
    surface.addEventListener("scroll", renderCarets, true);
    window.addEventListener("resize", renderCarets);
    document.addEventListener("selectionchange", () => {
      if (document.activeElement === wysiwyg) publishCursorSoon();
    });
    window.addEventListener("beforeunload", () => live.close());
    // Leaving the editor removes the root: the socket must not linger.
    const watchdog = window.setInterval(() => {
      if (!document.body.contains(root)) {
        live.close();
        window.clearInterval(watchdog);
      }
    }, 2000);
    paintPeople([]);
  } else {
    root.querySelector("#wiki-live").hidden = true;
  }

  const save = async () => {
    const content = currentMarkdown();
    if (!content.trim()) {
      toast(t("wiki.need_content"), "error");
      return;
    }
    // A hint, not a refusal: the author may be pasting a document that carries
    // its own title, and losing their work over a heading level would be worse.
    const levelOne = content.split("\n").filter((line) => /^#\s+\S/.test(line)).length;
    if (levelOne > 1) toast(t("wiki.many_h1"), "info", 6000);
    const payload = {
      title: titleInput.value.trim() || t("wiki.untitled"),
      content_md: content,
      tags: tagsInput.value
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
      note: "",
    };
    const button = root.querySelector("#wiki-save");
    setBusy(button, true);
    try {
      if (pageId) {
        const result = await api.put(`/api/v1/wiki/pages/${pageId}`, payload);
        localStorage.removeItem(draftKey(wikiId, pageId));
        if (result.status === "proposal") {
          toast(t("wiki.proposal_sent"), "success");
          navigate(`/wiki/${wikiId}`);
          return;
        }
        toast(t("wiki.page_saved"), "success");
        navigate(`/wiki/${wikiId}/p/${encodeURIComponent(result.page.slug)}?updated=1`);
      } else {
        const created = await api.post(`/api/v1/wiki/${wikiId}/pages`, payload);
        localStorage.removeItem(draftKey(wikiId, null));
        toast(t("wiki.page_created"), "success");
        navigate(`/wiki/${wikiId}/p/${encodeURIComponent(created.slug)}?created=1`);
      }
    } catch (error) {
      toast(error.detail || t("error.generic"), "error");
    } finally {
      setBusy(button, false);
    }
  };

  root.querySelector("#wiki-save").addEventListener("click", save);
  /* Moving a block without a mouse: Alt+Arrow on the block under the caret.
     A drag is the only way otherwise, which leaves the whole page layout out of
     reach of a keyboard-only author. */
  const topBlockOf = (node) => {
    let current = node;
    while (current && current.parentElement !== wysiwyg) current = current.parentElement;
    return current && current.parentElement === wysiwyg ? current : null;
  };

  const moveBlock = (direction) => {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount) return false;
    const block = topBlockOf(selection.getRangeAt(0).startContainer);
    if (!block) return false;
    const sibling = direction < 0 ? block.previousElementSibling : block.nextElementSibling;
    if (!sibling) return false;
    if (direction < 0) wysiwyg.insertBefore(block, sibling);
    else wysiwyg.insertBefore(sibling, block);
    const range = document.createRange();
    range.selectNodeContents(block);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
    const blocks = Array.from(wysiwyg.children);
    announce(
      t("wiki.block_moved")
        .replace("{position}", String(blocks.indexOf(block) + 1))
        .replace("{total}", String(blocks.length))
    );
    markDirty();
    notifyChange();
    return true;
  };

  root.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      save();
      return;
    }
    if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown") && model.mode === "wysiwyg") {
      if (moveBlock(event.key === "ArrowUp" ? -1 : 1)) {
        event.preventDefault();
        event.stopPropagation();
      }
    }
  });

  /** Enter inside a styled block must open a plain paragraph.
   *
   * Chromium answers Enter in a heading with a <div> that inherits the heading's
   * colour, underline and bold: the author keeps writing in red without asking
   * for it. We place a clean paragraph ourselves instead.
   */
  /**
   * Press Enter under a heading and get a plain paragraph.
   *
   * Two traps here. Chromium restores its own pending selection once the key
   * event is over, so a caret set inside the handler snaps back into the
   * heading and the next letters keep the heading's colour; the placement is
   * therefore repeated on the next ticks. And `execCommand("insertParagraph")`
   * clones the heading's inline styles into a second block, which is where the
   * stray line breaks came from, so the paragraph is built by hand.
   */
  const placeCaretAtStart = (block) => {
    const put = () => {
      if (!block.isConnected) return;
      // The retries below exist for Chromium's own snap-back, but they land
      // *after* the first keystroke when the author writes fast: putting the
      // caret back at offset 0 then wrote the rest of the word before the first
      // letter ("remière ligne … P"). Once the paragraph holds a character, the
      // author owns the caret.
      if (block.textContent.length > 0) return;
      const range = document.createRange();
      range.setStart(block, 0);
      range.collapse(true);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    };
    put();
    setTimeout(put, 0);
    requestAnimationFrame(put);
  };

  const openParagraphBelow = (block) => {
    const paragraph = document.createElement("p");
    paragraph.appendChild(document.createElement("br"));
    block.after(paragraph);
    placeCaretAtStart(paragraph);
    return paragraph;
  };

  // Delegated on the editor root: a repaint can replace the surface node, and
  // a listener bound to the old one would silently stop working.
  const handleEnter = (event) => {
    const surface = event.target instanceof Node ? event.target.closest?.("#wiki-wysiwyg") : null;
    if (!surface || !root.contains(surface)) return;
    if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return;
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (!range.collapsed) return;
    let block = range.startContainer;
    while (block && block !== surface && block.nodeType !== Node.ELEMENT_NODE) {
      block = block.parentNode;
    }
    while (block && block !== surface && !/^(H1|H2|H3|H4|H5|H6)$/.test(block.tagName)) {
      block = block.parentNode;
    }
    // Only a heading misleads the browser; a paragraph splits natively.
    if (!block || block === surface) return;
    event.preventDefault();
    const paragraph = openParagraphBelow(block);
    touchedByAuthor = true;
    paintCounter();
    markDirty();
    notifyChange();
    requestAnimationFrame(() => paragraph.scrollIntoView({ block: "nearest" }));
  };
  root.addEventListener("keydown", handleEnter);

  /* --------------------------------------------------------------------- */
  /* AI: fill this page, and review it                                      */
  /* --------------------------------------------------------------------- */
  const jobsBox = root.querySelector("#ai-jobs");
  const reviewBox = root.querySelector("#wiki-review-strip");
  const brief = root.querySelector("#ai-brief");
  const briefCount = root.querySelector("#ai-brief-count");
  brief.addEventListener("input", () => {
    briefCount.textContent = `${brief.value.length} / 4000`;
  });

  /* One poller per job: the panel stays visible while the pages are written. */
  const pollJob = async (jobId) => {
    const node = document.createElement("div");
    node.className = "ai-job";
    node.innerHTML = `<div class="ai-job-bar"><span></span></div><p class="small"></p>`;
    jobsBox.prepend(node);
    const bar = node.querySelector(".ai-job-bar span");
    const label = node.querySelector("p");
    // A finished job stops being a progress panel. Without this the failed run
    // kept its bar at 3% for ever, which reads as "still working" long after
    // the server has answered, and there was no way to clear it.
    const settle = (failed) => {
      node.classList.add(failed ? "is-error" : "is-done");
      node.querySelector(".ai-job-bar").hidden = true;
      const close = document.createElement("button");
      close.type = "button";
      close.className = "ai-job-close";
      close.setAttribute("aria-label", t("action.close"));
      close.textContent = "×";
      close.addEventListener("click", () => node.remove());
      node.append(close);
      setTimeout(() => node.remove(), failed ? 15000 : 8000);
    };
    for (let attempt = 0; attempt < 400; attempt += 1) {
      let job = null;
      try {
        job = await api.get(`/api/v1/wiki/ai/jobs/${jobId}`);
      } catch {
        await new Promise((resolve) => setTimeout(resolve, 3000));
        continue;
      }
      bar.style.width = `${Math.max(3, job.progress)}%`;
      label.textContent = `${job.message} (${job.progress}%)`;
      if (job.status === "done" || job.status === "error") {
        if (job.status === "error") {
          label.textContent = job.error || t("ai.failed");
          bar.style.width = "100%";
          bar.classList.add("is-error");
          // The strip above the text announced "Running…" and stayed there.
          if (!["fill", "generate"].includes(job.kind)) {
            reviewBox.hidden = false;
            reviewBox.classList.add("is-error");
            reviewBox.textContent = job.error || t("ai.failed");
          }
          settle(true);
        } else if (job.kind === "fill") {
          const body = (job.result && job.result.content_md) || "";
          label.textContent = t("ai.filled", { n: body.split(/\s+/).filter(Boolean).length });
          if (body) insertGenerated(body, (job.result && job.result.title) || "");
        } else if (job.kind === "generate") {
          label.textContent = t("ai.generated_pages", { n: (job.result.pages || []).length });
          if (job.result.pages && job.result.pages[0]) {
            navigate(`/wiki/${wikiId}/p/${encodeURIComponent(job.result.pages[0].slug)}`);
            return;
          }
        } else if (job.kind === "grammar") {
          reviewBox.hidden = false;
          const outcome = job.result || {};
          reviewBox.textContent = outcome.summary || t("ai.grammar_applied");
          if (outcome.applied) {
            toast(t("ai.grammar_applied"), "success");
            // The server rewrote the page and froze a version: pull that text
            // into the editor. Left alone, the surface kept the old wording and
            // the next deliberate save silently undid the correction.
            try {
              const fresh = await api.get(`/api/v1/wiki/pages/${pageId}`);
              if (fresh && typeof fresh.content_md === "string") {
                textarea.value = fresh.content_md;
                renderedMarkdown = "";
                renderRich(fresh.content_md);
                model.content = fresh.content_md;
                paintCounter();
                try {
                  localStorage.removeItem(draftKey(wikiId, pageId));
                } catch {
                  /* the local draft is a convenience */
                }
                stateLabel.textContent = t("wiki.saved");
              }
            } catch {
              /* the correction is on the server either way */
            }
          }
        } else if (job.result.findings && job.result.findings.length) {
          reviewBox.hidden = false;
          reviewBox.innerHTML = job.result.findings
            .map(
              (finding) =>
                `<p class="ai-finding ${escapeHtml(finding.severity || "low")}">${escapeHtml(
                  finding.issue || finding.quote || "",
                )}</p>`,
            )
            .join("");
        } else {
          reviewBox.hidden = false;
          reviewBox.textContent = job.result.summary || t("ai.review_done");
        }
        settle(false);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  };

  root.querySelector("#ai-generate").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const text = brief.value.trim();
    if (text.length > 0 && text.length < 20) {
      toast(t("ai.brief_too_short"), "error");
      return;
    }
    setBusy(button, true);
    try {
      const job = await api.post("/api/v1/wiki/ai/jobs", {
        kind: "fill",
        wiki_id: wikiId,
        page_id: pageId || undefined,
        topic: root.querySelector("#ai-topic").value.trim() || titleInput.value.trim(),
        style: root.querySelector("#ai-style").value,
        audience: root.querySelector("#ai-audience").value.trim(),
        research: root.querySelector("#ai-research").checked,
        instructions: text,
        language: wiki.default_language || "fr",
      });
      toast(t("ai.started"), "success");
      pollJob(job.id);
    } catch (error) {
      if (error.status === 409) {
        const jobId = error.payload && error.payload.detail && error.payload.detail.job_id;
        toast(t("ai.already_running"), "info");
        if (jobId) pollJob(jobId);
      } else {
        toast(error.detail || t("error.generic"), "error");
      }
    } finally {
      setBusy(button, false);
    }
  });

  // One AI entry point next to the reviews: the brief panel opens, focused.
  const openAiButton = root.querySelector("[data-open-ai]");
  if (openAiButton) {
    openAiButton.addEventListener("click", () => {
      const panel = root.querySelector("#wiki-ai-panel");
      if (!panel) return;
      panel.open = true;
      panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
      const brief = root.querySelector("#ai-brief");
      if (brief) brief.focus();
    });
  }

  root.querySelectorAll("[data-review]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!pageId) return;
      setBusy(button, true);
      try {
        const job = await api.post("/api/v1/wiki/ai/jobs", {
          kind: button.dataset.review,
          wiki_id: wikiId,
          page_id: pageId,
          language: wiki.default_language || "fr",
        });
        reviewBox.hidden = false;
        reviewBox.textContent = t("ai.running");
        pollJob(job.id);
      } catch (error) {
        toast(error.detail || t("error.generic"), "error");
      } finally {
        setBusy(button, false);
      }
    });
  });

  /* --------------------------------------------------------------------- */
  /* Deleting the page being edited                                         */
  /* --------------------------------------------------------------------- */
  const deleteButton = root.querySelector("#wiki-delete");
  if (deleteButton) {
    deleteButton.addEventListener("click", async () => {
      const agreed = await confirmDialog(
        t("wiki.delete_page"),
        t("wiki.delete_page_warning"),
        t("action.delete"),
      );
      if (!agreed) return;
      setBusy(deleteButton, true);
      try {
        await api.del(`/api/v1/wiki/pages/${pageId}`);
        localStorage.removeItem(draftKey(wikiId, pageId));
        toast(t("wiki.page_deleted"), "success");
        navigate(`/wiki/${wikiId}`);
      } catch (error) {
        toast(error.detail || t("error.generic"), "error");
        setBusy(deleteButton, false);
      }
    });
  }

  /* --------------------------------------------------------------------- */
  /* Templates: a skeleton chosen when the page does not exist yet          */
  /* --------------------------------------------------------------------- */
  const templateBar = root.querySelector("#wiki-template-bar");
  const templateSelect = root.querySelector("#wiki-template-select");
  if (templateBar && templateSelect && !pageId) {
    api
      .get(`/api/v1/wiki/${wikiId}/templates`)
      .then(async (rows) => {
        if (!rows.length) return;
        templateBar.hidden = false;
        templateSelect.innerHTML =
          `<option value="">${escapeHtml(t("wiki.template_none"))}</option>` +
          rows
            .map((row) => `<option value="${row.id}">${escapeHtml(row.name)}</option>`)
            .join("");
        templateSelect.addEventListener("change", async () => {
          const row = rows.find((entry) => String(entry.id) === templateSelect.value);
          if (!row) return;
          if (currentMarkdown().trim() && currentMarkdown().trim() !== `# ${t("wiki.untitled")}`) {
            const replace = await confirmDialog(
              t("wiki.template_apply"),
              t("wiki.template_apply_warning"),
              t("wiki.template_replace"),
            );
            if (!replace) {
              templateSelect.value = "";
              return;
            }
          }
          textarea.value = row.content_md;
          renderRich(row.content_md);
          model.content = row.content_md;
          touchedByAuthor = true;
          paintCounter();
          markDirty();
          notifyChange();
          toast(t("wiki.template_applied", { name: row.name }), "success");
        });
      })
      .catch(() => {
        /* templates are a convenience: a failed listing stays silent */
      });
  }

  /* --------------------------------------------------------------------- */
  /* Images: pick one in the rich view to size it                           */
  /* --------------------------------------------------------------------- */
  const imgTools = root.querySelector("#wiki-img-tools");
  let selectedImage = null;

  const placeImageTools = () => {
    if (!selectedImage || imgTools.hidden) return;
    const box = selectedImage.getBoundingClientRect();
    const surfaceBox = surface.getBoundingClientRect();
    imgTools.style.top = `${box.bottom - surfaceBox.top + 6}px`;
    imgTools.style.left = `${Math.max(0, box.left - surfaceBox.left)}px`;
  };

  const clearImageTools = () => {
    selectedImage = null;
    imgTools.hidden = true;
    root.querySelectorAll("#wiki-wysiwyg img.is-selected").forEach((node) =>
      node.classList.remove("is-selected"),
    );
  };

  wysiwyg.addEventListener("click", (event) => {
    const image = event.target.closest ? event.target.closest("img") : null;
    if (!image || !wysiwyg.contains(image)) {
      clearImageTools();
      return;
    }
    clearImageTools();
    selectedImage = image;
    image.classList.add("is-selected");
    imgTools.hidden = false;
    placeImageTools();
  });

  imgTools.querySelectorAll("[data-width]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      if (!selectedImage) return;
      const value = button.dataset.width;
      if (value) selectedImage.setAttribute("width", value);
      else selectedImage.removeAttribute("width");
      touchedByAuthor = true;
      markDirty();
      notifyChange();
      placeImageTools();
    });
  });

  const grip = imgTools.querySelector(".ed-img-grip");
  if (grip) {
    grip.addEventListener("pointerdown", (event) => {
      if (!selectedImage) return;
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = selectedImage.getBoundingClientRect().width;
      const onMove = (moveEvent) => {
        const width = Math.max(80, Math.min(1600, Math.round(startWidth + (moveEvent.clientX - startX))));
        selectedImage.setAttribute("width", String(width));
        placeImageTools();
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        touchedByAuthor = true;
        markDirty();
        notifyChange();
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });
  }

  surface.addEventListener("scroll", () => {
    if (selectedImage) placeImageTools();
  }, true);
  window.addEventListener("resize", () => {
    if (selectedImage) placeImageTools();
  });

  /* --------------------------------------------------------------------- */
  /* Linking a page: search instead of typing a title from memory           */
  /* --------------------------------------------------------------------- */
  const picker = root.querySelector("#wiki-link-picker");
  const pickerQuery = root.querySelector("#wiki-link-query");
  const pickerResults = root.querySelector("#wiki-link-results");
  const pickerGlobal = root.querySelector("#wiki-link-global");
  let pickerTimer = null;
  let pickerHits = [];

  const closePicker = () => {
    picker.hidden = true;
  };

  const renderHits = (hits) => {
    pickerHits = hits;
    if (!hits.length) {
      pickerResults.innerHTML = `<li class="muted small ed-link-empty">${escapeHtml(
        t("wiki.link_search_empty"),
      )}</li>`;
      return;
    }
    pickerResults.innerHTML = hits
      .map(
        (hit, index) => `
        <li role="option" aria-selected="false">
          <button type="button" class="ed-link-hit" data-index="${index}">
            <span class="ed-link-title">${escapeHtml(hit.title)}</span>
            <span class="muted small">${escapeHtml(hit.wiki_title || "")}</span>
          </button>
        </li>`,
      )
      .join("");
  };

  // An empty query lists this wiki's own pages; typing switches to full text.
  const localPages = () =>
    (wiki.pages || []).map((page) => ({
      page_id: page.id,
      wiki_id: wiki.id,
      wiki_title: wiki.title,
      slug: page.slug,
      title: page.title,
    }));

  const searchLinks = async (query) => {
    if (!query) {
      renderHits(localPages().slice(0, 20));
      return;
    }
    const scope = pickerGlobal.checked ? "all" : "local";
    const params = new URLSearchParams({ q: query, scope, limit: "20" });
    params.set("wiki_id", String(wikiId));
    try {
      renderHits(await api.get(`/api/v1/wiki/search?${params.toString()}`));
    } catch {
      renderHits([]);
    }
  };

  const openPicker = () => {
    picker.hidden = false;
    pickerQuery.value = "";
    pickerResults.innerHTML = "";
    pickerQuery.focus();
    searchLinks("");
  };

  pickerQuery.addEventListener("input", () => {
    window.clearTimeout(pickerTimer);
    pickerTimer = window.setTimeout(() => searchLinks(pickerQuery.value.trim()), 220);
  });
  pickerGlobal.addEventListener("change", () => searchLinks(pickerQuery.value.trim()));
  pickerResults.addEventListener("click", (event) => {
    const button = event.target.closest("[data-index]");
    if (!button) return;
    const hit = pickerHits[Number(button.dataset.index)];
    if (!hit) return;
    insertWikilink(hit);
    closePicker();
  });
  picker.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      closePicker();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !picker.hidden) closePicker();
  });

  /* --------------------------------------------------------------------- */
  /* AI output lands in the surface, never in a new page                    */
  /* --------------------------------------------------------------------- */
  const insertGenerated = (body, title) => {
    const text = String(body || "").trim();
    if (!text) return;
    const current = currentMarkdown().trim();
    const placeholder = `# ${t("wiki.untitled")}`;
    const merged = current && current !== placeholder ? `${current}\n\n${text}\n` : `${text}\n`;
    textarea.value = merged;
    model.content = merged;
    renderRich(merged);
    if (title && !titleInput.value.trim()) titleInput.value = title;
    touchedByAuthor = true;
    paintPreview();
    paintCounter();
    markDirty();
    notifyChange();
    toast(t("ai.inserted"), "success");
  };

  switchMode("wysiwyg");
  offerDraft();
  paintCounter();
}
