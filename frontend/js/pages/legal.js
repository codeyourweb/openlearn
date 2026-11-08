// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Legal notice.
 *
 * Two layers on purpose:
 * - the project notice ships with the interface, so it follows the interface
 *   language and is rendered here from the dictionary;
 * - the instance notice is written by the administrator of *this* server, one
 *   document per language, and arrives from the API already rendered and
 *   sanitised (the wiki markdown allowlist ran server side).
 *
 * Nothing on this page comes from a query string, so there is no way to make
 * it echo anything back.
 */

import { api } from "../api.js";
import { currentLanguage, onLanguageChange, t } from "../i18n.js";
import { markdownToHtml } from "../markdown.js";
import { escapeHtml } from "../sanitize.js";
import { setPageSeo } from "../seo.js";

/* The project notice, in order. Each entry is a title key and a body key; the
   body is markdown so it can carry lists and links without a second format. */
const SECTIONS = ["publisher", "license", "contributions", "data"];

function _section(name) {
  const body = t(`legal.${name}_body`);
  // `markdownToHtml` escapes the text and only lets http(s), relative and
  // mailto links through. The question-text sanitiser drops every attribute, so
  // running the notice through it turned the contact link into plain words.
  const html = markdownToHtml(body);
  return `
    <section class="legal-section">
      <h2>${escapeHtml(t(`legal.${name}_title`))}</h2>
      <div class="legal-body">${html}</div>
    </section>`;
}

function _instance(notice) {
  if (notice && notice.html) {
    const stamp = notice.updated_at
      ? `<p class="legal-stamp">${escapeHtml(
          t("legal.updated", {
            date: new Date(notice.updated_at).toLocaleDateString(currentLanguage()),
          }),
        )}</p>`
      : "";
    return `
      <section class="legal-section legal-instance">
        <h2>${escapeHtml(t("legal.instance_title"))}</h2>
        <div class="legal-body">${notice.html}</div>
        ${stamp}
      </section>`;
  }
  return `
    <section class="legal-section legal-instance is-empty">
      <h2>${escapeHtml(t("legal.instance_title"))}</h2>
      <p class="muted">${escapeHtml(t("legal.instance_empty"))}</p>
    </section>`;
}

export async function renderLegal() {
  const root = document.createElement("section");
  root.className = "page-narrow legal";
  setPageSeo({
    title: t("legal.title"),
    description: t("legal.lead"),
    path: "/legal",
  });

  const paint = async () => {
    const language = currentLanguage();
    root.innerHTML = `
      <header class="legal-head">
        <h1>${escapeHtml(t("legal.title"))}</h1>
        <p class="muted">${escapeHtml(t("legal.lead"))}</p>
      </header>
      <div class="legal-doc">${SECTIONS.map(_section).join("")}<p class="legal-loading muted">…</p></div>`;

    let notice = null;
    try {
      notice = await api.get(`/api/v1/legal?lang=${encodeURIComponent(language)}`);
    } catch {
      // The project notice above already stands on its own: a missing addition
      // is not an error worth a banner.
      notice = null;
    }
    if (currentLanguage() !== language) return; // the reader switched meanwhile
    const doc = root.querySelector(".legal-doc");
    if (doc) {
      doc.innerHTML = `${
        SECTIONS.map(_section).join("") + _instance(notice)
      }<p class="legal-footnote muted">${escapeHtml(t("legal.footnote"))}</p>`;
    }
  };

  await paint();
  onLanguageChange(() => {
    paint();
  });
  return root;
}
