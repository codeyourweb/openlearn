// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Public accessibility statement.

   It says what the audit covers and — just as important — what it does not:
   a statement that promises everything is a statement nobody believes.
*/

import { t } from "../i18n.js";
import { escapeHtml } from "../sanitize.js";

const VERIFIED = ["verified_1", "verified_2", "verified_3", "verified_4"];
const LIMITS = ["limit_1", "limit_2", "limit_3", "limit_4"];

const list = (keys) =>
  `<ul class="a11y-list">${keys
    .map((key) => `<li>${escapeHtml(t(`accessibility.${key}`))}</li>`)
    .join("")}</ul>`;

export async function renderAccessibility() {
  const root = document.createElement("section");
  root.className = "page-narrow legal-page";
  const reviewed = new Date().toLocaleDateString(undefined, {
    year: "numeric", month: "long", day: "numeric",
  });
  root.innerHTML = `
    <header class="legal-head">
      <h1>${escapeHtml(t("accessibility.title"))}</h1>
      <p class="muted">${escapeHtml(t("accessibility.lead"))}</p>
    </header>

    <article class="legal-doc">
      <h2>${escapeHtml(t("accessibility.standard_title"))}</h2>
      <p>${escapeHtml(t("accessibility.standard_body"))}</p>

      <h2>${escapeHtml(t("accessibility.verified_title"))}</h2>
      ${list(VERIFIED)}

      <h2>${escapeHtml(t("accessibility.limits_title"))}</h2>
      ${list(LIMITS)}

      <h2>${escapeHtml(t("accessibility.report_title"))}</h2>
      <p>${escapeHtml(t("accessibility.report_body"))}
        <a href="mailto:developper@openlearnproject.org">developper@openlearnproject.org</a></p>
      <p class="muted small">${escapeHtml(
        t("accessibility.reviewed").replace("{date}", reviewed)
      )}</p>
    </article>`;
  return root;
}
