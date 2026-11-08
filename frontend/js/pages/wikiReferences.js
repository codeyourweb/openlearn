// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* The wiki's bibliography: where every source is cited, what links where, and
   which links point at a page that does not exist yet. */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { navigate } from "../router.js";
import { escapeHtml, setBusy, toast } from "../ui.js";

export async function renderWikiReferences(params) {
  const root = document.createElement("section");
  await _references(root, params);
  return root;
}

/** "{n} pages" reads wrong at one: pick the singular key when it applies. */
function count(key, n) {
  return t(n === 1 ? `${key}_one` : key, { n });
}

async function _references(root, params) {
  const wikiId = Number(params.id);
  let index = null;
  let wiki = null;
  try {
    [index, wiki] = await Promise.all([
      api.get(`/api/v1/wiki/${wikiId}/references`),
      api.get(`/api/v1/wiki/${wikiId}`),
    ]);
  } catch (error) {
    root.innerHTML = `<div class="card empty">${escapeHtml(error.detail || t("wiki.not_found"))}</div>`;
    return;
  }

  const canWrite = Boolean(wiki.can_write);
  const external = index.external || [];
  const internal = index.internal || [];
  const unresolved = index.unresolved || [];
  const orphans = index.orphans || [];

  const hostGroups = new Map();
  for (const source of external) {
    const key = source.host || "—";
    if (!hostGroups.has(key)) hostGroups.set(key, []);
    hostGroups.get(key).push(source);
  }

  root.innerHTML = `
    <section class="page-head">
      <div>
        <h1>${escapeHtml(t("wiki.references_title"))}</h1>
        <p class="muted">${escapeHtml(t("wiki.references_help"))}</p>
      </div>
      <a class="btn btn-ghost" data-link href="/wiki/${wikiId}">${escapeHtml(t("action.back"))}</a>
    </section>

    <div class="ref-stats">
      <span class="pill">${escapeHtml(count("wiki.ref_pages", index.stats.pages))}</span>
      <span class="pill">${escapeHtml(count("wiki.ref_sources", index.stats.sources))}</span>
      <span class="pill">${escapeHtml(count("wiki.ref_internal", index.stats.internal))}</span>
      <span class="pill ${unresolved.length ? "warn" : ""}">${escapeHtml(count("wiki.ref_unresolved", unresolved.length))}</span>
      <span class="pill ${orphans.length ? "warn" : ""}">${escapeHtml(count("wiki.ref_orphans", orphans.length))}</span>
    </div>

    <section class="card ref-block">
      <h2>${escapeHtml(t("wiki.ref_sources_title"))}</h2>
      ${
        external.length
          ? `<ul class="ref-sources">${[...hostGroups.entries()]
              .map(
                ([host, sources]) => `
                <li class="ref-host">
                  <span class="ref-host-name">${escapeHtml(host)}</span>
                  <span class="muted small">${escapeHtml(t("wiki.ref_cited", { n: sources.length }))}</span>
                  <ul>${sources
                    .map(
                      (source) => `
                      <li>
                        <a href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(
                          source.label || source.url,
                        )}</a>
                        ${source.stored ? `<span class="pill ok">${escapeHtml(t("wiki.ref_declared"))}</span>` : ""}
                        <span class="muted small">${source.pages
                          .map(
                            (page) =>
                              `<a data-link href="/wiki/${wikiId}/p/${encodeURIComponent(page.slug)}">${escapeHtml(page.title)}</a>`,
                          )
                          .join(" · ")}</span>
                      </li>`,
                    )
                    .join("")}</ul>
                </li>`,
              )
              .join("")}</ul>`
          : `<p class="muted">${escapeHtml(t("wiki.ref_none"))}</p>`
      }
    </section>

    <section class="card ref-block">
      <h2>${escapeHtml(t("wiki.ref_internal_title"))}</h2>
      ${
        internal.length
          ? `<ul class="ref-internal">${internal
              .map(
                (target) => `
              <li>
                <a data-link href="/wiki/${wikiId}/p/${encodeURIComponent(target.slug)}">${escapeHtml(target.title)}</a>
                <span class="muted small">← ${target.sources
                  .map((source) => escapeHtml(source.title))
                  .join(", ")}</span>
              </li>`,
              )
              .join("")}</ul>`
          : `<p class="muted">${escapeHtml(t("wiki.ref_none"))}</p>`
      }
    </section>

    <section class="card ref-block">
      <h2>${escapeHtml(t("wiki.ref_unresolved_title"))}</h2>
      ${
        unresolved.length
          ? `<ul class="ref-missing">${unresolved
              .map(
                (item) => `
              <li data-missing="${escapeHtml(item.slug)}">
                <span class="ref-missing-name">[[${escapeHtml(item.slug)}]]</span>
                <span class="muted small">${item.sources
                  .map((source) => escapeHtml(source.title))
                  .join(", ")}</span>
                ${canWrite ? `<button class="btn btn-sm" data-create="${escapeHtml(item.title)}">${escapeHtml(t("wiki.ref_create_page"))}</button>` : ""}
              </li>`,
              )
              .join("")}</ul>`
          : `<p class="muted">${escapeHtml(t("wiki.ref_clean"))}</p>`
      }
    </section>

    <section class="card ref-block">
      <h2>${escapeHtml(t("wiki.ref_orphans_title"))}</h2>
      <p class="muted small">${escapeHtml(t("wiki.ref_orphans_help"))}</p>
      ${
        orphans.length
          ? `<ul class="ref-orphans">${orphans
              .map(
                (page) =>
                  `<li><a data-link href="/wiki/${wikiId}/p/${encodeURIComponent(page.slug)}">${escapeHtml(page.title)}</a></li>`,
              )
              .join("")}</ul>`
          : `<p class="muted">${escapeHtml(t("wiki.ref_none"))}</p>`
      }
    </section>
  `;

  root.querySelectorAll("[data-create]").forEach((button) => {
    button.addEventListener("click", async () => {
      const title = button.dataset.create;
      setBusy(button, true);
      try {
        const page = await api.post(`/api/v1/wiki/${wikiId}/pages`, {
          title,
          content_md: `# ${title}\n\n`,
        });
        toast(t("wiki.page_created"), "success");
        navigate(`/wiki/${wikiId}/edit/${page.id}`);
      } catch (error) {
        toast(error.detail || t("error.generic"), "error");
        setBusy(button, false);
      }
    });
  });
}
