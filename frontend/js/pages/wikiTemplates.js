// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Wiki templates: markdown skeletons every contributor can start a page from. */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { markdownToHtml } from "../markdown.js";
import { navigate } from "../router.js";
import { confirmDialog, escapeHtml, renderError, setBusy, toast } from "../ui.js";

const BLANK = {
  name: "",
  description: "",
  keywords: [],
  content_md: "# Titre\n\n## Contexte\n\n## Points clés\n\n- \n\n## Références\n\n",
};

let editing = null;

function keywordList(raw) {
  return String(raw || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 8);
}

function templateCard(row, canWrite) {
  const keywords = (row.keywords || [])
    .map((word) => `<span class="pill small">${escapeHtml(word)}</span>`)
    .join(" ");
  return `
    <article class="card wiki-template" data-template="${row.id}">
      <header class="wiki-template-head">
        <div>
          <h2>${escapeHtml(row.name)}</h2>
          ${row.description ? `<p class="muted small">${escapeHtml(row.description)}</p>` : ""}
        </div>
        ${
          canWrite
            ? `<div class="row-wrap end">
                 <button class="btn btn-sm btn-ghost" data-edit="${row.id}">${escapeHtml(t("wiki.edit_template"))}</button>
                 <button class="btn btn-sm btn-ghost btn-danger" data-delete="${row.id}">${escapeHtml(t("action.delete"))}</button>
               </div>`
            : ""
        }
      </header>
      ${keywords ? `<p class="wiki-template-keywords">${keywords}</p>` : ""}
      <pre class="wiki-template-body">${escapeHtml((row.content_md || "").slice(0, 600))}</pre>
    </article>`;
}

export async function renderWikiTemplates(params) {
  const root = document.createElement("section");
  await _templates(root, params);
  return root;
}

async function _templates(root, params) {
  const wikiId = Number(params.id);
  let wiki;
  let rows = [];
  try {
    wiki = await api.get(`/api/v1/wiki/${wikiId}`);
    rows = await api.get(`/api/v1/wiki/${wikiId}/templates`);
  } catch (error) {
    renderError(root, error.detail || t("error.generic"));
    return;
  }

  const canWrite = Boolean(wiki.can_write);
  editing = null;

  root.innerHTML = `
    <section class="page-head">
      <div>
        <p class="muted small"><a data-link href="/wiki/${wiki.id}">${escapeHtml(wiki.title)}</a></p>
        <h1>${escapeHtml(t("wiki.templates_title"))}</h1>
        <p class="muted">${escapeHtml(t("wiki.templates_help"))}</p>
      </div>
      ${
        canWrite
          ? `<button class="btn btn-primary" id="template-new">${escapeHtml(t("wiki.new_template"))}</button>`
          : ""
      }
    </section>

    ${
      canWrite
        ? `<section class="card wiki-capsule">
             <div>
               <h2>${escapeHtml(t("wiki.capsule_title"))}</h2>
               <p class="muted">${escapeHtml(t("wiki.capsule_help"))}</p>
             </div>
             <button class="btn btn-primary" id="capsule-create">${escapeHtml(t("wiki.capsule_create"))}</button>
           </section>`
        : ""
    }

    <div id="template-list" class="wiki-template-list">${
      rows.length
        ? rows.map((row) => templateCard(row, canWrite)).join("")
        : `<p class="empty">${escapeHtml(t("wiki.template_empty"))}</p>`
    }</div>

    <section class="card wiki-template-editor" id="template-editor" hidden>
      <h2 id="template-editor-title">${escapeHtml(t("wiki.new_template"))}</h2>
      <label class="field">
        <span>${escapeHtml(t("wiki.template_name"))}</span>
        <input class="input" id="template-name" maxlength="120" />
      </label>
      <label class="field">
        <span>${escapeHtml(t("wiki.template_description"))}</span>
        <input class="input" id="template-description" maxlength="300" />
      </label>
      <label class="field">
        <span>${escapeHtml(t("wiki.template_keywords"))}</span>
        <input class="input" id="template-keywords" maxlength="200" />
      </label>
      <label class="field">
        <span>${escapeHtml(t("wiki.template_content"))}</span>
        <textarea class="input code" id="template-content" rows="14" spellcheck="false"></textarea>
      </label>
      <div class="row-wrap end">
        <button class="btn btn-ghost" id="template-cancel">${escapeHtml(t("action.cancel"))}</button>
        <button class="btn btn-primary" id="template-save">${escapeHtml(t("action.save"))}</button>
      </div>
    </section>
  `;

  const list = root.querySelector("#template-list");
  const editor = root.querySelector("#template-editor");
  const nameInput = root.querySelector("#template-name");
  const descInput = root.querySelector("#template-description");
  const keysInput = root.querySelector("#template-keywords");
  const bodyInput = root.querySelector("#template-content");
  const saveButton = root.querySelector("#template-save");
  const editorTitle = root.querySelector("#template-editor-title");

  const reload = () => navigate(`/wiki/${wiki.id}/templates`, { replace: true });

  const openEditor = (row) => {
    editing = row || null;
    editorTitle.textContent = row ? row.name : t("wiki.new_template");
    nameInput.value = row ? row.name : BLANK.name;
    descInput.value = row ? row.description || "" : "";
    keysInput.value = row ? (row.keywords || []).join(", ") : "";
    bodyInput.value = row ? row.content_md || "" : BLANK.content_md;
    editor.hidden = false;
    nameInput.focus();
  };

  const newButton = root.querySelector("#template-new");
  if (newButton) newButton.addEventListener("click", () => openEditor(null));

  const capsuleButton = root.querySelector("#capsule-create");
  if (capsuleButton) {
    capsuleButton.addEventListener("click", async () => {
      setBusy(capsuleButton, true);
      try {
        const lang = (document.documentElement.lang || "fr").slice(0, 2);
        const result = await api.post(`/api/v1/wiki/${wiki.id}/capsule?lang=${encodeURIComponent(lang)}`);
        toast(t("wiki.capsule_created"), "success");
        if (result.first_page_id) navigate(`/wiki/${wiki.id}/edit/${result.first_page_id}`);
        else navigate(`/wiki/${wiki.id}`);
      } catch (error) {
        toast(error.detail || t("common.error"), "error");
      } finally {
        setBusy(capsuleButton, false);
      }
    });
  }

  root.querySelector("#template-cancel").addEventListener("click", () => {
    editor.hidden = true;
    editing = null;
  });

  saveButton.addEventListener("click", async () => {
    const name = nameInput.value.trim();
    if (!name) {
      toast(t("wiki.template_no_name"), "error");
      nameInput.focus();
      return;
    }
    const payload = {
      name,
      description: descInput.value.trim(),
      keywords: keywordList(keysInput.value),
      content_md: bodyInput.value,
    };
    setBusy(saveButton, true);
    try {
      if (editing) await api.put(`/api/v1/wiki/${wiki.id}/templates/${editing.id}`, payload);
      else await api.post(`/api/v1/wiki/${wiki.id}/templates`, payload);
      toast(t("wiki.template_saved"), "success");
      reload();
    } catch (error) {
      toast(error.detail || t("error.generic"), "error");
      setBusy(saveButton, false);
    }
  });

  list.addEventListener("click", async (event) => {
    const editButton = event.target.closest("[data-edit]");
    if (editButton) {
      const row = rows.find((item) => String(item.id) === editButton.dataset.edit);
      if (row) openEditor(row);
      return;
    }
    const deleteButton = event.target.closest("[data-delete]");
    if (!deleteButton) return;
    const agreed = await confirmDialog(
      t("action.delete"),
      t("wiki.template_delete_warning"),
      t("action.delete"),
    );
    if (!agreed) return;
    setBusy(deleteButton, true);
    try {
      await api.del(`/api/v1/wiki/${wiki.id}/templates/${deleteButton.dataset.delete}`);
      toast(t("wiki.template_deleted"), "success");
      reload();
    } catch (error) {
      toast(error.detail || t("error.generic"), "error");
      setBusy(deleteButton, false);
    }
  });

  // A live preview costs nothing: the same renderer draws the reading view.
  const preview = document.createElement("div");
  preview.className = "wiki-template-preview";
  bodyInput.addEventListener("input", () => {
    preview.innerHTML = markdownToHtml(bodyInput.value, { pages: {} });
    bodyInput.after(preview);
  });
}
