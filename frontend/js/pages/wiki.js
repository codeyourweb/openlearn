// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Wiki: catalogue, reader and creation flow. */

import { api, uploadImage } from "../api.js";
import { currentLanguage, t, tp } from "../i18n.js";
import { markdownToHtml, inlineMarkdown, paintCustomColors } from "../markdown.js";
import { hydrateEmbeds } from "../wikiEmbeds.js";
import { flagStrip } from "../flags.js";
import { setPageSeo, titleSlug } from "../seo.js";
import { navigate } from "../router.js";
import { state } from "../store.js";
import {
  bindPager,
  confirmDialog,
  escapeHtml,
  formatDate,
  pagerHtml,
  renderError,
  setBusy,
  showUploadProgress,
  statusBadge,
  toast,
} from "../ui.js";

const STATUS_ORDER = ["public", "private", "pending", "draft", "rejected"];

function statusPill(status) {
  const label = t(`wiki.status.${status}`);
  return `<span class="pill ${status}">${escapeHtml(label === `wiki.status.${status}` ? status : label)}</span>`;
}

/** Canonical wiki path: the id, then the wiki's own slug — the form the server
 *  indexes and the sitemap lists. A slug built from the title does not match
 *  any page, which used to open the wiki on an empty reader. */
function wikiPath(wiki) {
  return `/wiki/${wiki.id}/${encodeURIComponent(wiki.slug || titleSlug(wiki.title, "wiki"))}`;
}

/* ------------------------------------------------------------------------- */
/* Catalogue                                                                 */
/* ------------------------------------------------------------------------- */
async function _wikiHome(root) {
  root.innerHTML = `
    <section class="page-head">
      <div>
        <h1>${escapeHtml(t("wiki.title"))}</h1>
        <p class="muted">${escapeHtml(t("wiki.subtitle"))}</p>
      </div>
      <div class="row-wrap end">
        <a class="btn btn-ghost btn-ai ai-only" data-link href="/wiki/chat"><span aria-hidden="true">✨</span> ${escapeHtml(t("wiki.ask"))}</a>
        ${
          state.user
            ? `<a class="btn btn-primary" data-link href="/wiki/new">${escapeHtml(t("wiki.new"))}</a>
               <label class="btn btn-ghost btn-import" title="${escapeHtml(t("wiki.import_zip_help"))}">
                 ${escapeHtml(t("wiki.import_zip"))}
                 <input type="file" id="wiki-import-zip" accept=".zip,application/zip" hidden />
               </label>`
            : `<a class="btn btn-primary" data-link href="/login?next=/wiki/new">${escapeHtml(t("wiki.sign_in_to_write"))}</a>`
        }
      </div>
      ${
        state.user
          ? `<p class="muted small wiki-import-hint">${escapeHtml(t("wiki.import_zip_help"))}</p>`
          : ""
      }
    </section>

    <div class="wiki-toolbar card">
      <input id="wiki-q" class="input" type="search" placeholder="${escapeHtml(t("wiki.search_placeholder"))}" />
      <div class="segmented" role="tablist">
        <button class="seg is-active" data-scope="all" role="tab" aria-selected="true">${escapeHtml(t("wiki.scope_all"))}</button>
        <button class="seg" data-scope="mine" role="tab" aria-selected="false">${escapeHtml(t("wiki.scope_mine"))}</button>
      </div>
    </div>

    <div id="wiki-results" class="wiki-grid"></div>
    <p id="wiki-empty" class="empty" hidden>${escapeHtml(t("wiki.empty"))}</p>
    <div id="wiki-pager" class="pager-slot"></div>
  `;

  const results = root.querySelector("#wiki-results");
  const empty = root.querySelector("#wiki-empty");
  const pagerSlot = root.querySelector("#wiki-pager");
  const search = root.querySelector("#wiki-q");
  const PAGE_SIZE = 12;
  let scope = "all";
  let pageIndex = 0;

  const zipInput = root.querySelector("#wiki-import-zip");
  if (zipInput) {
    zipInput.addEventListener("change", async () => {
      const file = zipInput.files && zipInput.files[0];
      if (!file) return;
      const progress = showUploadProgress(t("wiki.import_zip"), file.name);
      try {
        const result = await uploadImage(
          file,
          (ratio) => progress.update(ratio),
          "/api/v1/wiki/import",
        );
        toast(
          t("wiki.import_done", {
            pages: result.pages,
            images: result.images,
            source: result.source,
          }),
          "success",
        );
        navigate(`/wiki/${result.wiki.id}`);
      } catch (error) {
        toast(error.detail || t("error.generic"), "error");
      } finally {
        progress.done();
        zipInput.value = "";
      }
    });
  }

  const paint = async () => {
    const query = search.value.trim();
    results.innerHTML = `<div class="skeleton card"></div>`;
    try {
      if (query) {
        pagerSlot.innerHTML = "";
        const hits = await api.get(`/api/v1/wiki/search?q=${encodeURIComponent(query)}`);
        empty.hidden = hits.length > 0;
        results.innerHTML = hits
          .map(
            (hit) => `
            <a class="card quiz-card wiki-card wiki-result" data-link href="/wiki/${hit.wiki_id}/p/${encodeURIComponent(hit.slug)}">
              <div class="row between">
                <span class="badge muted">${escapeHtml(hit.wiki_title)}</span>
              </div>
              <h3 class="mt-2">${escapeHtml(hit.title)}</h3>
              <p class="muted small">${escapeHtml(hit.excerpt)}</p>
            </a>`,
          )
          .join("");
        return;
      }
      const meta = await api.getMeta(
        `/api/v1/wiki?mine=${scope === "mine"}&limit=${PAGE_SIZE}&offset=${pageIndex * PAGE_SIZE}`,
      );
      const wikis = meta.data;
      const total = Number(meta.headers.get("X-Total-Count") || wikis.length);
      if (pageIndex > 0 && !wikis.length && total > 0) {
        pageIndex = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);
        await paint();
        return;
      }
      pagerSlot.innerHTML = pagerHtml(pageIndex, total, PAGE_SIZE);
      bindPager(pagerSlot, (next) => {
        pageIndex = next;
        paint();
        root.querySelector("#wiki-q").scrollIntoView({ block: "start", behavior: "smooth" });
      });
      empty.hidden = wikis.length > 0;
      results.innerHTML = wikis
        .map((wiki) => {
          const canOpen = wiki.is_public || wiki.role;
          // Same card as a questionnaire: status and kind on top, then the
          // title, then the flags and the numbers the reader compares.
          const cover = wiki.cover_image
            ? `<a class="wiki-card-cover" data-link href="/wiki/${wiki.id}"><img src="${escapeHtml(wiki.cover_image)}" alt="" loading="lazy" /></a>`
            : "";
          return `
          <article class="card quiz-card wiki-card">
            ${cover}
            <div class="row between">
              <span class="pill ${escapeHtml(wiki.status)}">${t(`wiki.status.${wiki.status}`)}</span>
              <span class="badge muted">${tp("wiki.page_one", "wiki.page_many", wiki.page_count)}</span>
            </div>
            <h3 class="mt-2">
              ${canOpen ? `<a data-link href="${wikiPath(wiki)}">${escapeHtml(wiki.title)}</a>` : escapeHtml(wiki.title)}
            </h3>
            <p class="muted small">${escapeHtml((wiki.description || t("wiki.no_description")).slice(0, 140))}</p>
            <div class="row between mt-2 quiz-card-foot">
              <span class="row quiz-card-langs">
                ${flagStrip([], wiki.default_language)}
                <span class="small-note">${escapeHtml(wiki.owner ? wiki.owner.display_name : "")}${
                  wiki.updated_at ? ` · ${escapeHtml(formatDate(wiki.updated_at))}` : ""
                }</span>
              </span>
              <div class="row quiz-card-actions">
                ${
                  wiki.role && wiki.role !== "owner"
                    ? `<span class="pill">${escapeHtml(t(`wiki.role.${wiki.role}`))}</span>`
                    : ""
                }
                ${canOpen ? `<a class="btn btn-sm btn-primary" data-link href="${wikiPath(wiki)}">${t("action.open")}</a>` : ""}
                ${wiki.can_write ? `<a class="btn btn-sm" data-link href="/wiki/${wiki.id}/p/accueil">${t("action.edit")}</a>` : ""}
              </div>
            </div>
          </article>`;
        })
        .join("");
    } catch (error) {
      renderError(results, error.detail || t("error.generic"));
    }
  };

  let timer = null;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    pageIndex = 0;
    timer = setTimeout(paint, 220);
  });
  root.querySelectorAll("[data-scope]").forEach((button) => {
    button.addEventListener("click", () => {
      scope = button.dataset.scope;
      pageIndex = 0;
      root.querySelectorAll("[data-scope]").forEach((other) => {
        other.classList.toggle("is-active", other === button);
        other.setAttribute("aria-selected", String(other === button));
      });
      paint();
    });
  });
  await paint();
}

/* ------------------------------------------------------------------------- */
/* Creation                                                                  */
/* ------------------------------------------------------------------------- */
async function _wikiCreate(root) {
  if (!state.user) {
    navigate("/login?next=/wiki/new", { replace: true });
    return;
  }
  root.innerHTML = `
    <section class="page-head"><div>
      <h1>${escapeHtml(t("wiki.new"))}</h1>
      <p class="muted">${escapeHtml(t("wiki.new_help"))}</p>
    </div></section>
    <form id="wiki-create" class="card form">
      <label class="field">
        <span>${escapeHtml(t("wiki.field_title"))}</span>
        <input class="input" name="title" required minlength="3" maxlength="160"
               placeholder="${escapeHtml(t("wiki.title_placeholder"))}" />
      </label>
      <label class="field">
        <span>${escapeHtml(t("wiki.field_description"))}</span>
        <textarea class="input" name="description" rows="3" maxlength="2000"></textarea>
      </label>
      <label class="field">
        <span>${escapeHtml(t("wiki.field_language"))}</span>
        <select class="input" name="default_language">
          <option value="fr">Français</option>
          <option value="en">English</option>
        </select>
      </label>
      <p class="form-error" hidden></p>
      <div class="row-wrap end">
        <a class="btn btn-ghost" data-link href="/wiki">${escapeHtml(t("action.cancel"))}</a>
        <button class="btn btn-primary" type="submit">${escapeHtml(t("wiki.create"))}</button>
      </div>
    </form>
  `;

  const form = root.querySelector("#wiki-create");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    const error = form.querySelector(".form-error");
    error.hidden = true;
    setBusy(button, true);
    try {
      const data = Object.fromEntries(new FormData(form));
      const wiki = await api.post("/api/v1/wiki", data);
      toast(t("wiki.created"), "success");
      // The new wiki is born with a home page: write that one, do not add a
      // second page on top of it.
      let home = null;
      try {
        const detail = await api.get(`/api/v1/wiki/${wiki.id}`);
        home = (detail.pages || [])[0] || null;
      } catch (error) {
        home = null;
      }
      navigate(home ? `/wiki/${wiki.id}/edit/${home.id}` : `/wiki/${wiki.id}/edit`);
    } catch (failure) {
      error.textContent = failure.detail || t("error.generic");
      error.hidden = false;
    } finally {
      setBusy(button, false);
    }
  });
}

/* ------------------------------------------------------------------------- */
/* Reader                                                                    */
/* ------------------------------------------------------------------------- */
function navTree(wiki, current) {
  // The menu is a tree, so the reader has to see it as one: depth shows where
  // a page sits, and the trail down to the current page stays lit.
  const children = new Map();
  for (const page of wiki.pages) {
    const key = page.parent_id || 0;
    if (!children.has(key)) children.set(key, []);
    children.get(key).push(page);
  }
  for (const list of children.values()) {
    list.sort((a, b) => (a.position - b.position) || a.title.localeCompare(b.title));
  }

  const trail = new Set();
  let cursor = current ? current.parent_id || null : null;
  while (cursor) {
    trail.add(cursor);
    const parent = wiki.pages.find((page) => page.id === cursor);
    cursor = parent ? parent.parent_id || null : null;
  }

  const rows = [];
  const walk = (parentId, depth) => {
    for (const page of children.get(parentId) || []) {
      const active = current && current.id === page.id;
      const classes = [
        "wiki-nav-item",
        `depth-${Math.min(depth, 5)}`,
        depth ? "is-child" : "is-root",
        active ? "is-active" : "",
        trail.has(page.id) ? "is-ancestor" : "",
      ]
        .filter(Boolean)
        .join(" ");
      rows.push(`<li class="${classes}" data-id="${page.id}" data-parent="${page.parent_id || 0}">
    <a class="wiki-nav-link${active ? " is-active" : ""}" data-link
       href="/wiki/${wiki.id}/p/${encodeURIComponent(page.slug)}"
       ${active ? 'aria-current="page"' : ""}>
      <span class="wiki-nav-title">${escapeHtml(page.title)}</span>
      <span class="wiki-nav-version muted small">v${page.version}</span>
    </a>
  </li>`);
      walk(page.id, depth + 1);
    }
  };
  walk(0, 0);
  // ``<li>`` needs its list parent to stay valid HTML.
  return `<ul class="wiki-nav-list">${rows.join("")}</ul>`;
}

function breadcrumbHtml(wiki, page) {
  const trail = page.breadcrumb || [];
  if (trail.length < 2) return "";
  return `<nav class="wiki-breadcrumb" aria-label="${escapeHtml(t("wiki.breadcrumb"))}">
    ${trail
      .slice(0, -1)
      .map(
        (item) =>
          `<a data-link href="/wiki/${wiki.id}/p/${encodeURIComponent(item.slug)}">${escapeHtml(item.title)}</a><span class="wiki-crumb-sep" aria-hidden="true">/</span>`,
      )
      .join("")}
    <span class="wiki-crumb-current">${escapeHtml(trail[trail.length - 1].title)}</span>
  </nav>`;
}

function sourcesHtml(wiki, page) {
  const stored = (page.references && page.references.external) || [];
  const detected = page.external_links || [];
  const merged = [];
  const seen = new Map();
  for (const item of detected) {
    seen.set(item.url, { url: item.url, label: item.label || item.url, stored: false });
    merged.push(seen.get(item.url));
  }
  for (const item of stored) {
    if (seen.has(item.url)) seen.get(item.url).stored = true;
    else merged.push({ url: item.url, label: item.label || item.url, stored: true, note: item.note });
  }
  const addForm = wiki.can_write
    ? `<form class="wiki-source-form" id="wiki-source-form" hidden>
        <input class="input input-sm" name="url" type="url" required
               placeholder="https://…" aria-label="${escapeHtml(t("wiki.ref_url"))}" />
        <input class="input input-sm" name="label" maxlength="200"
               placeholder="${escapeHtml(t("wiki.ref_label"))}" aria-label="${escapeHtml(t("wiki.ref_label"))}" />
        <button class="btn btn-sm btn-primary" type="submit">${escapeHtml(t("wiki.ref_add"))}</button>
      </form>
      <button class="btn btn-sm btn-ghost wiki-source-add" type="button" data-add-source>
        ${escapeHtml(t("wiki.ref_add"))}
      </button>`
    : "";
  if (!merged.length) {
    return `<h2 class="wiki-toc-title wiki-sources-title">${escapeHtml(t("wiki.sources"))}</h2>
      <p class="muted small">${escapeHtml(t("wiki.ref_none"))}</p>
      ${addForm}`;
  }
  return `<h2 class="wiki-toc-title wiki-sources-title">${escapeHtml(t("wiki.sources"))}</h2>
    <ol class="wiki-sources">
      ${merged
        .map(
          (source) => `<li>
        <a href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(source.label)}</a>
        ${source.stored ? `<span class="pill ok small">${escapeHtml(t("wiki.ref_declared"))}</span>` : ""}
      </li>`,
        )
        .join("")}
    </ol>
    <a class="wiki-sources-all" data-link href="/wiki/${wiki.id}/references">${escapeHtml(t("wiki.ref_all"))}</a>
    ${addForm}`;
}

function missingLinksHtml(wiki, page) {
  const missing = page.missing_links || [];
  if (!missing.length) return "";
  return `<section class="wiki-missing" aria-label="${escapeHtml(t("wiki.ref_unresolved_title"))}">
    <h2>${escapeHtml(t("wiki.ref_unresolved_title"))}</h2>
    <p class="muted small">${escapeHtml(t("wiki.ref_unresolved_help"))}</p>
    <ul>
      ${missing
        .map(
          (item) => `<li data-missing="${escapeHtml(item.slug)}">
        <span class="wiki-missing-name">[[${escapeHtml(item.slug)}]]</span>
        ${wiki.can_write ? `<button class="btn btn-sm" data-create="${escapeHtml(item.title)}">${escapeHtml(t("wiki.ref_create_page"))}</button>` : ""}
      </li>`,
        )
        .join("")}
    </ul>
  </section>`;
}

/**
 * Poll an AI job until it settles and mirror its progress into ``box``.
 *
 * The jobs run server side; the page only needs "running", then the result.
 */
async function watchJob(job, box, onDone) {
  const node = document.createElement("div");
  node.className = "ai-job";
  const label = document.createElement("span");
  label.className = "ai-job-label";
  label.textContent = t("ai.running");
  node.appendChild(label);
  box.appendChild(node);

  let current = job;
  for (let tick = 0; tick < 240; tick += 1) {
    if (current.status === "done" || current.status === "error") {
      node.classList.add(current.status === "done" ? "is-done" : "is-error");
      label.textContent =
        current.status === "error" ? current.error || t("ai.failed") : t("ai.review_done");
      if (current.status === "done" && onDone) onDone(current);
      return current;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1500));
    try {
      current = await api.get(`/api/v1/wiki/ai/jobs/${current.id}`);
    } catch {
      return current;
    }
  }
  return current;
}

async function _wikiPage(root, params) {
  const query = params.query || {};
  const wikiId = Number(params.id);
  let wiki;
  let page = null;
  try {
    wiki = await api.get(`/api/v1/wiki/${wikiId}`);
    const slug = params.slug;
    // `/wiki/:id/:slug` is the canonical form and carries the *wiki* slug, so a
    // slug that names no page still means "this wiki": open its first page.
    // A genuine page link (`/wiki/:id/p/:slug`) keeps its own miss handling.
    const isPageLink = location.pathname.includes("/p/");
    const target =
      (slug ? wiki.pages.find((item) => item.slug === slug) : null) ||
      (isPageLink ? null : wiki.pages[0]);
    if (target) page = await api.get(`/api/v1/wiki/pages/${target.id}`);
  } catch (error) {
    root.innerHTML = `<div class="card empty">${escapeHtml(error.detail || t("wiki.not_found"))}</div>`;
    return;
  }

  // The page, not the wiki, is the document a search engine should index.
  setPageSeo({
    title: page ? `${page.title} — ${wiki.title}` : wiki.title,
    description: (page ? page.content_md : wiki.description || "").replace(/[#*_>`]/g, "").slice(0, 200),
    path: page
      ? `/wiki/${wiki.id}/p/${encodeURIComponent(page.slug)}`
      : wikiPath(wiki),
    type: "article",
    image: wiki.cover_image || undefined,
    jsonLd: {
      "@context": "https://schema.org",
      "@type": page ? "Article" : "CollectionPage",
      headline: page ? page.title : wiki.title,
      name: page ? page.title : wiki.title,
      isPartOf: { "@type": "CreativeWork", name: wiki.title },
      inLanguage: wiki.default_language || "en",
      isAccessibleForFree: true,
    },
  });

  const canWrite = Boolean(wiki.can_write);
  const role = wiki.role;
  const pagesHtml = navTree(wiki, page);

  root.innerHTML = `
    <div class="wiki-shell">
      <aside class="wiki-side card">
        <div class="wiki-side-head">
          <a class="wiki-side-title" data-link href="${wikiPath(wiki)}">${escapeHtml(wiki.title)}</a>
          ${statusPill(wiki.status)}
          <button type="button" class="btn btn-sm btn-ghost wiki-side-toggle" id="wiki-side-toggle"
                  aria-expanded="true" aria-controls="wiki-nav">
            <span aria-hidden="true">☰</span> ${escapeHtml(t("wiki.side_toggle"))}
          </button>
        </div>
        <input id="wiki-page-filter" class="input input-sm" type="search"
               placeholder="${escapeHtml(t("wiki.filter_pages"))}" />
        <nav class="wiki-nav" id="wiki-nav" aria-label="${escapeHtml(t("wiki.page_list"))}">${pagesHtml}</nav>
        <div class="wiki-side-actions">
          ${canWrite ? `<a class="btn btn-sm btn-primary" data-link href="/wiki/${wiki.id}/edit">${escapeHtml(t("wiki.new_page"))}</a>` : ""}
          ${
            canWrite
              ? `<label class="btn btn-sm btn-ghost btn-import" title="${escapeHtml(t("wiki.import_page_help"))}">
                   ${escapeHtml(t("wiki.import_page"))}
                   <input type="file" id="wiki-import-md" accept=".md,.markdown,.txt,text/markdown" hidden />
                 </label>`
              : ""
          }
          ${canWrite ? `<a class="btn btn-sm btn-ghost" data-link href="/wiki/${wiki.id}/structure">${escapeHtml(t("wiki.structure"))}</a>` : ""}
          ${canWrite ? `<a class="btn btn-sm btn-ghost" data-link href="/wiki/${wiki.id}/templates">${escapeHtml(t("wiki.templates"))}</a>` : ""}
          <a class="btn btn-sm btn-ghost" data-link href="/cards?wiki=${wiki.id}">${escapeHtml(t("wiki.cards"))}</a>
          <a class="btn btn-sm btn-ghost" data-link href="/wiki/${wiki.id}/references">${escapeHtml(t("wiki.references_title"))}</a>
          <a class="btn btn-sm btn-ghost" data-link href="/wiki/${wiki.id}/graph">${escapeHtml(t("wiki.graph"))}</a>
          <a class="btn btn-sm btn-ai ai-only" data-link href="/wiki/chat?wiki=${wiki.id}"><span aria-hidden="true">✨</span> ${escapeHtml(t("wiki.ask"))}</a>
          <a class="btn btn-sm btn-ghost" href="/api/v1/wiki/${wiki.id}/export.zip">${escapeHtml(t("wiki.export_zip"))}</a>
          <a class="btn btn-sm btn-ghost" href="/api/v1/wiki/${wiki.id}/export.pdf?lang=${encodeURIComponent(currentLanguage())}" title="${escapeHtml(t("wiki.export_pdf_hint"))}">${escapeHtml(t("wiki.export_wiki_pdf"))}</a>
        </div>
        ${wiki.pending_proposals ? `<p class="pill warn">${escapeHtml(t("wiki.pending_proposals", { n: wiki.pending_proposals }))}</p>` : ""}
        ${
          canWrite || wiki.can_delete
            ? `<div class="wiki-side-foot">
                 ${
                   canWrite
                     ? `<button class="btn btn-sm btn-ai ai-only" id="wiki-ai-open" aria-expanded="false">
                          <span aria-hidden="true">✨</span> ${escapeHtml(t("ai.generate_pages"))}
                        </button>`
                     : ""
                 }
                 ${
                   wiki.can_delete
                     ? `<button class="btn btn-sm btn-ghost btn-danger" id="wiki-delete">${escapeHtml(t("wiki.delete_wiki"))}</button>`
                     : ""
                 }
               </div>`
            : ""
        }
      </aside>

      <main class="wiki-main">
        ${
          canWrite
            ? `<section class="card wiki-ai-panel ai-only" id="wiki-ai-panel" hidden>
                 <h2>${escapeHtml(t("ai.generate_pages"))}</h2>
                 <p class="muted small">${escapeHtml(t("ai.generate_pages_help"))}</p>
                 <label class="field">
                   <span>${escapeHtml(t("ai.brief"))}</span>
                   <textarea class="input" id="wiki-ai-brief" rows="4" maxlength="4000"
                             placeholder="${escapeHtml(t("ai.brief_placeholder"))}"></textarea>
                 </label>
                 <div class="wiki-ai-grid">
                   <label class="field">
                     <span>${escapeHtml(t("ai.style"))}</span>
                     <select class="input" id="wiki-ai-style">
                       <option value="light">${escapeHtml(t("ai.style_light"))}</option>
                       <option value="balanced" selected>${escapeHtml(t("ai.style_balanced"))}</option>
                       <option value="formal">${escapeHtml(t("ai.style_formal"))}</option>
                       <option value="detailed">${escapeHtml(t("ai.style_detailed"))}</option>
                       <option value="academic">${escapeHtml(t("ai.style_academic"))}</option>
                     </select>
                   </label>
                   <label class="field">
                     <span>${escapeHtml(t("ai.audience"))}</span>
                     <input class="input" id="wiki-ai-audience" maxlength="120"
                            placeholder="${escapeHtml(t("ai.audience_hint"))}" />
                   </label>
                   <label class="field">
                     <span>${escapeHtml(t("ai.pages"))}</span>
                     <input class="input" id="wiki-ai-pages" type="number" min="0" max="12" value="0"
                            placeholder="${escapeHtml(t("ai.pages_auto"))}" />
                   </label>
                 </div>
                 <label class="check">
                   <input type="checkbox" id="wiki-ai-research" checked />
                   <span>${escapeHtml(t("ai.research"))}</span>
                 </label>
                 <div class="row-wrap end">
                   <button class="btn btn-primary" id="wiki-ai-run">${escapeHtml(t("ai.generate"))}</button>
                 </div>
                 <div class="ai-jobs" id="wiki-ai-jobs"></div>
               </section>`
            : ""
        }
        ${
          page
            ? `
          <article class="card wiki-article">
            <header class="wiki-article-head">
              <div>
                ${breadcrumbHtml(wiki, page)}
                <h1>${escapeHtml(page.title)}</h1>
                <p class="muted small">
                  ${escapeHtml(t("wiki.version", { n: page.version }))} ·
                  ${escapeHtml(formatDate(page.updated_at))}
                  ${(page.tags || []).map((tag) => `<span class="pill">${escapeHtml(tag)}</span>`).join(" ")}
                </p>
              </div>
              <div class="row-wrap end">
                ${canWrite
                  ? `<a class="btn btn-sm btn-primary" data-link href="/wiki/${wiki.id}/edit/${page.id}">${escapeHtml(t("action.edit"))}</a>
                     <a class="btn btn-sm btn-ghost" data-link href="/wiki/${wiki.id}/history/${page.id}">${escapeHtml(t("wiki.history"))}</a>`
                  : `<a class="btn btn-sm" data-link href="/wiki/${wiki.id}/propose/${page.id}">${escapeHtml(t("wiki.propose"))}</a>`}
                ${canWrite || page.can_delete
                  ? `<button class="btn btn-sm btn-ghost btn-danger" id="wiki-delete-page">${escapeHtml(t("wiki.delete_page"))}</button>`
                  : ""}
                <a class="btn btn-sm btn-ghost" href="/api/v1/wiki/pages/${page.id}/export.md">${escapeHtml(t("wiki.export_md"))}</a>
                <a class="btn btn-sm btn-ghost" href="/api/v1/wiki/pages/${page.id}/export.pdf" title="${escapeHtml(t("wiki.export_pdf_hint"))}">${escapeHtml(t("wiki.export_pdf"))}</a>
              </div>
            </header>
            <div class="wiki-content" id="wiki-content">${page.html}</div>
            ${missingLinksHtml(wiki, page)}
            ${
              (page.backlinks || []).length
                ? `<footer class="wiki-backlinks">
                     <h2>${escapeHtml(t("wiki.backlinks"))}</h2>
                     <ul>${page.backlinks
                       .map(
                         (link) =>
                           `<li><a data-link href="/wiki/${wiki.id}/p/${encodeURIComponent(link.slug)}">${escapeHtml(link.title)}</a></li>`,
                       )
                       .join("")}</ul>
                   </footer>`
                : ""
            }
          </article>
          <aside class="wiki-toc card">
            <h2 class="wiki-toc-title">${escapeHtml(t("wiki.on_this_page"))}</h2>
            <ol>
              ${(page.outline || [])
                .filter((item) => item.depth <= 3)
                .map(
                  (item) =>
                    `<li class="toc-depth-${item.depth}"><a href="#${escapeHtml(item.anchor)}">${escapeHtml(item.text)}</a></li>`,
                )
                .join("") || `<li class="muted">${escapeHtml(t("wiki.no_outline"))}</li>`}
            </ol>
            ${sourcesHtml(wiki, page)}
          </aside>`
            : `<div class="card empty">${escapeHtml(t("wiki.no_pages"))}</div>`
        }
        <section class="card wiki-quizzes" id="wiki-quizzes">
          <h2><span aria-hidden="true">✨</span> ${escapeHtml(t("wiki.quizzes_title"))}</h2>
          <p class="muted small">${escapeHtml(t("wiki.quizzes_help"))}</p>
          <div class="wiki-quiz-list" id="wiki-quiz-list"></div>
          ${
            canWrite
              ? `<div class="row-wrap mt-2">
                   <select class="input" id="wiki-quiz-pick" aria-label="${escapeHtml(t("wiki.quizzes_attach"))}"></select>
                   <button class="btn btn-sm" id="wiki-quiz-attach">${escapeHtml(t("wiki.quizzes_attach"))}</button>
                   <button class="btn btn-sm btn-ai ai-only" id="wiki-quiz-generate"><span aria-hidden="true">✨</span> ${escapeHtml(t("wiki.quiz_generate"))}</button>
                 </div>
                 <div class="card ai-zone mt-2" id="wiki-quiz-form" hidden>
                   <p class="small">${escapeHtml(t("wiki.quiz_generate_help"))}</p>
                   <div class="wiki-ai-grid">
                     <label class="field">
                       <span>${escapeHtml(t("wiki.quiz_mode"))}</span>
                       <select class="input" id="wiki-quiz-mode">
                         <option value="qcm">${escapeHtml(t("editor.mode_qcm"))}</option>
                         <option value="swipe">${escapeHtml(t("editor.mode_swipe"))}</option>
                       </select>
                     </label>
                     <label class="field">
                       <span>${escapeHtml(t("wiki.quiz_count"))}</span>
                       <input class="input" id="wiki-quiz-count" type="number" min="3" max="20" value="8" />
                     </label>
                     <label class="field grow">
                       <span>${escapeHtml(t("wiki.quiz_brief"))}</span>
                       <input class="input" id="wiki-quiz-brief" maxlength="600" />
                     </label>
                   </div>
                   <div class="row-wrap end">
                     <button class="btn btn-primary" id="wiki-quiz-run">${escapeHtml(t("wiki.quiz_generate"))}</button>
                   </div>
                 </div>`
              : ""
          }
        </section>
      </main>
    </div>
  `;

  const aiPanel = root.querySelector("#wiki-ai-panel");
  if (aiPanel) {
    const openButton = root.querySelector("#wiki-ai-open");
    // Generating pages is not an edit of the page on screen: while the panel is
    // open the article steps aside, otherwise the brief looks like it fills it.
    const mainColumn = root.querySelector(".wiki-main");
    const toggleGenerating = (active) => {
      if (mainColumn) mainColumn.classList.toggle("is-generating", active);
      openButton.setAttribute("aria-expanded", String(active));
    };
    openButton.addEventListener("click", () => {
      aiPanel.hidden = !aiPanel.hidden;
      toggleGenerating(!aiPanel.hidden);
      if (!aiPanel.hidden) root.querySelector("#wiki-ai-brief").focus();
    });

    const runButton = root.querySelector("#wiki-ai-run");
    const jobsBox = root.querySelector("#wiki-ai-jobs");
    runButton.addEventListener("click", async () => {
      const brief = root.querySelector("#wiki-ai-brief").value.trim();
      if (brief.length < 12) {
        toast(t("ai.brief_too_short"), "error");
        return;
      }
      setBusy(runButton, true);
      try {
        const job = await api.post("/api/v1/wiki/ai/jobs", {
          kind: "generate",
          wiki_id: wiki.id,
          topic: wiki.title,
          style: root.querySelector("#wiki-ai-style").value,
          page_count: Number(root.querySelector("#wiki-ai-pages").value) || 0,
          audience: root.querySelector("#wiki-ai-audience").value.trim(),
          research: root.querySelector("#wiki-ai-research").checked,
          instructions: brief,
          language: wiki.default_language || "fr",
        });
        toast(t("ai.started"), "success");
        await watchJob(job, jobsBox, (done) => {
          const count = (done.result && done.result.pages ? done.result.pages.length : 0);
          toast(t("ai.generated_pages", { n: count }), "success");
          window.setTimeout(() => navigate(`/wiki/${wiki.id}`), 900);
        });
      } catch (error) {
        toast(error.detail || t("error.generic"), "error");
      } finally {
        setBusy(runButton, false);
      }
    });
  }

  const deletePageButton = root.querySelector("#wiki-delete-page");
  if (deletePageButton && page) {
    deletePageButton.addEventListener("click", async () => {
      const agreed = await confirmDialog(
        t("wiki.delete_page"),
        t("wiki.delete_page_warning"),
        t("action.delete"),
      );
      if (!agreed) return;
      setBusy(deletePageButton, true);
      try {
        await api.del(`/api/v1/wiki/pages/${page.id}`);
        toast(t("wiki.page_deleted"), "success");
        navigate(`/wiki/${wiki.id}`);
      } catch (error) {
        toast(error.detail || t("error.generic"), "error");
        setBusy(deletePageButton, false);
      }
    });
  }

  const deleteWikiButton = root.querySelector("#wiki-delete");
  if (deleteWikiButton) {
    deleteWikiButton.addEventListener("click", async () => {
      const agreed = await confirmDialog(
        t("wiki.delete_wiki"),
        t("wiki.delete_wiki_warning"),
        t("action.delete"),
      );
      if (!agreed) return;
      setBusy(deleteWikiButton, true);
      try {
        await api.del(`/api/v1/wiki/${wiki.id}`);
        toast(t("wiki.wiki_deleted"), "success");
        navigate("/wiki");
      } catch (error) {
        toast(error.detail || t("error.generic"), "error");
        setBusy(deleteWikiButton, false);
      }
    });
  }

  // On a phone the page list would push the article below three screens of
  // menu and stay stuck there while scrolling: it collapses to one bar.
  const side = root.querySelector(".wiki-side");
  const sideToggle = root.querySelector("#wiki-side-toggle");
  if (side && sideToggle) {
    const collapsedByDefault = window.matchMedia("(max-width: 900px)").matches;
    side.classList.toggle("is-collapsed", collapsedByDefault);
    sideToggle.setAttribute("aria-expanded", String(!collapsedByDefault));
    sideToggle.addEventListener("click", () => {
      const collapsed = side.classList.toggle("is-collapsed");
      sideToggle.setAttribute("aria-expanded", String(!collapsed));
    });
  }

  const filter = root.querySelector("#wiki-page-filter");
  if (filter) {
    filter.addEventListener("input", () => {
      const needle = filter.value.trim().toLowerCase();
      const items = [...root.querySelectorAll(".wiki-nav-item")];
      const byId = new Map(items.map((item) => [item.dataset.id, item]));
      const keep = new Set();
      if (needle) {
        for (const item of items) {
          const link = item.querySelector(".wiki-nav-link");
          if (!link || !link.textContent.toLowerCase().includes(needle)) continue;
          keep.add(item.dataset.id);
          // A match deep in the tree is useless if its parents are hidden.
          let parent = item.dataset.parent;
          let guard = 0;
          while (parent && parent !== "0" && guard < 12) {
            keep.add(parent);
            const node = byId.get(parent);
            parent = node ? node.dataset.parent : "0";
            guard += 1;
          }
        }
      }
      for (const item of items) item.hidden = Boolean(needle) && !keep.has(item.dataset.id);
    });
  }

  const sourceButton = root.querySelector("[data-add-source]");
  if (sourceButton) {
    const form = root.querySelector("#wiki-source-form");
    sourceButton.addEventListener("click", () => {
      form.hidden = !form.hidden;
      if (!form.hidden) form.querySelector('input[name="url"]').focus();
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const url = String(data.get("url") || "").trim();
      if (!url) return;
      try {
        const reference = await api.post(`/api/v1/wiki/pages/${page.id}/references`, {
          kind: "external",
          url,
          label: String(data.get("label") || "").trim(),
        });
        const list = root.querySelector(".wiki-sources");
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.href = reference.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = reference.label || reference.url;
        const badge = document.createElement("span");
        badge.className = "pill ok small";
        badge.textContent = t("wiki.ref_declared");
        item.append(link, badge);
        list.appendChild(item);
        form.reset();
        form.hidden = true;
        toast(t("wiki.ref_added"), "success");
      } catch (error) {
        toast(error.detail || t("error.generic"), "error");
      }
    });
  }

  root.querySelectorAll("[data-create]").forEach((button) => {
    button.addEventListener("click", async () => {
      const title = button.dataset.create;
      button.disabled = true;
      try {
        const created = await api.post(`/api/v1/wiki/${wiki.id}/pages`, {
          title,
          content_md: `# ${title}\n\n`,
        });
        toast(t("wiki.page_created"), "success");
        navigate(`/wiki/${wiki.id}/edit/${created.id}`);
      } catch (error) {
        toast(error.detail || t("error.generic"), "error");
        button.disabled = false;
      }
    });
  });

    const pageInput = root.querySelector("#wiki-import-md");
    if (pageInput) {
      pageInput.addEventListener("change", async () => {
        const file = pageInput.files && pageInput.files[0];
        if (!file) return;
        const progress = showUploadProgress(t("wiki.import_page"), file.name);
        try {
          const result = await uploadImage(
            file,
            (ratio) => progress.update(ratio),
            `/api/v1/wiki/${wiki.id}/pages/import`,
          );
          toast(t("wiki.import_page_done", { title: result.page.title }), "success");
          navigate(`/wiki/${wiki.id}/p/${encodeURIComponent(result.page.slug)}`);
        } catch (error) {
          toast(error.detail || t("error.generic"), "error");
        } finally {
          progress.done();
          pageInput.value = "";
        }
      });
    }

  // An edit button on a wiki the visitor only reads is a dead end: they get the
  // proposal flow instead, which is the same editor with a different target.
  if (query && query.created && page) {
    toast(t("wiki.page_created"), "success");
  }
  if (query && query.updated && page) {
    toast(t("wiki.page_saved"), "success");
  }

  /* Questionnaires attached to this wiki ---------------------------------- */
  const quizList = root.querySelector("#wiki-quiz-list");
  if (quizList) {
    const quizModeLabel = (mode) =>
      mode === "swipe"
        ? t("editor.mode_swipe")
        : mode === "adventure"
          ? t("editor.mode_adventure")
          : mode === "poll"
            ? t("editor.mode_poll")
            : t("editor.mode_qcm");

    const drawQuizzes = (items, canManage) => {
      if (!items.length) {
        quizList.innerHTML = `<p class="muted small">${escapeHtml(t("wiki.quizzes_empty"))}</p>`;
        return;
      }
      quizList.innerHTML = items
        .map(
          (quiz) => `
          <div class="wiki-quiz-row">
            <div>
              <strong>${quiz.ai_generated ? '<span aria-hidden="true">✨</span> ' : ""}${escapeHtml(quiz.title)}</strong>
              <p class="muted small">${quiz.question_count} ${escapeHtml(t("common.questions"))} · ${escapeHtml(quizModeLabel(quiz.mode))}</p>
            </div>
            <div class="wiki-quiz-actions">
              <a class="btn btn-sm" data-link href="/quizzes/${quiz.id}">${escapeHtml(t("wiki.open"))}</a>
              ${
                canManage
                  ? `<button class="btn btn-sm btn-ghost btn-danger" data-detach="${quiz.id}">${escapeHtml(t("wiki.quizzes_detach"))}</button>`
                  : ""
              }
            </div>
          </div>`,
        )
        .join("");
      quizList.querySelectorAll("[data-detach]").forEach((button) => {
        button.addEventListener("click", async () => {
          try {
            await api.del(`/api/v1/wiki/${wiki.id}/quizzes/${button.dataset.detach}`);
            await loadQuizzes();
          } catch (error) {
            toast(error.detail || t("common.error"), "error");
          }
        });
      });
    };

    const loadQuizzes = async () => {
      try {
        const data = await api.get(`/api/v1/wiki/${wiki.id}/quizzes`);
        drawQuizzes(data.items || [], Boolean(data.can_manage));
      } catch {
        quizList.innerHTML = "";
      }
    };

    await loadQuizzes();

    const pick = root.querySelector("#wiki-quiz-pick");
    if (pick) {
      const fillPick = async () => {
        const linked = new Set(
          [...quizList.querySelectorAll("[data-detach]")].map((node) => Number(node.dataset.detach)),
        );
        try {
          const mine = await api.get("/api/v1/quizzes/mine");
          const available = mine.filter((quiz) => !linked.has(quiz.id) && quiz.mode !== "adventure");
          pick.innerHTML = available.length
            ? available.map((quiz) => `<option value="${quiz.id}">${escapeHtml(quiz.title)}</option>`).join("")
            : `<option value="">${escapeHtml(t("wiki.quizzes_none_to_attach"))}</option>`;
          pick.disabled = !available.length;
          const attachButton = root.querySelector("#wiki-quiz-attach");
          if (attachButton) attachButton.disabled = !available.length;
        } catch {
          pick.innerHTML = "";
        }
      };
      await fillPick();
      root.querySelector("#wiki-quiz-attach").addEventListener("click", async (event) => {
        const button = event.currentTarget;
        if (!pick.value) return;
        setBusy(button, true);
        try {
          await api.post(`/api/v1/wiki/${wiki.id}/quizzes`, { quiz_id: Number(pick.value) });
          await loadQuizzes();
          await fillPick();
        } catch (error) {
          toast(error.detail || t("common.error"), "error");
        } finally {
          setBusy(button, false);
        }
      });
    }

    const form = root.querySelector("#wiki-quiz-form");
    const generateButton = root.querySelector("#wiki-quiz-generate");
    if (generateButton && form) {
      generateButton.addEventListener("click", () => {
        form.hidden = !form.hidden;
        if (!form.hidden) root.querySelector("#wiki-quiz-brief").focus();
      });
      root.querySelector("#wiki-quiz-run").addEventListener("click", async (event) => {
        const button = event.currentTarget;
        setBusy(button, true);
        toast(t("wiki.quiz_generating"), "info");
        try {
          const result = await api.post(`/api/v1/wiki/${wiki.id}/ai/quiz`, {
            mode: root.querySelector("#wiki-quiz-mode").value,
            count: Number(root.querySelector("#wiki-quiz-count").value) || 8,
            language: currentLanguage(),
            brief: root.querySelector("#wiki-quiz-brief").value.trim(),
          });
          toast(t("wiki.quiz_created", { n: result.question_count }), "success");
          navigate(`/quizzes/${result.quiz_id}/edit`);
        } catch (error) {
          toast(error.detail || t("common.error"), "error");
        } finally {
          setBusy(button, false);
        }
      });
    }
  }

  // Custom text colours travel as data-hex: the CSP blocks style attributes,
  // so they are painted through the CSSOM once the article is in the document.
  paintCustomColors(root);
  // Embedded questionnaires become live cards in place: no navigation.
  hydrateEmbeds(root);
}

/* ------------------------------------------------------------------------- */
/* --------------------------------------------------------------------------
   Side-by-side diff
   -------------------------------------------------------------------------- */

function diffCell(side, tone) {
  if (!side || (!side.text && !(side.segments || []).length)) {
    return `<td class="diff-cell diff-blank ${tone}"></td>`;
  }
  const sign =
    tone === "is-add" ? "+" : tone === "is-del" ? "−" : "";
  const body =
    side.segments && side.segments.length
      ? side.segments
          .map((segment) => `<span class="diff-seg diff-seg-${segment.kind}">${escapeHtml(segment.text)}</span>`)
          .join("")
      : escapeHtml(side.text);
  return `<td class="diff-cell ${tone}"><span class="diff-no">${side.no ?? ""}</span><span class="diff-sign" aria-hidden="true">${sign}</span><span class="diff-text">${body || "&nbsp;"}</span></td>`;
}

function sideBySideHtml(diff) {
  const labels = diff.labels || {};
  const rows = (diff.side || [])
    .map((row) => {
      if (row.kind === "hunk") {
        return `<tr class="diff-hunk"><td colspan="2">${escapeHtml(row.text || "")}</td></tr>`;
      }
      const leftTone =
        row.kind === "add" ? "is-blank" : row.kind === "equal" ? "is-same" : "is-del";
      const rightTone =
        row.kind === "del" ? "is-blank" : row.kind === "equal" ? "is-same" : "is-add";
      return `<tr class="diff-line diff-${row.kind}">${diffCell(row.left, leftTone)}${diffCell(row.right, rightTone)}</tr>`;
    })
    .join("");
  return `
    <div class="diff-panes">
      <table class="diff-table">
        <thead>
          <tr>
            <th scope="col">
              <span class="diff-ver">${escapeHtml(labels.from || "")}</span>
              <span class="diff-vtitle">${escapeHtml(labels.page || "")}</span>
            </th>
            <th scope="col">
              <span class="diff-ver">${escapeHtml(labels.to || "")}</span>
              <span class="diff-vtitle">${escapeHtml(labels.page || "")}</span>
            </th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

/* History (versions + diff)                                                 */
/* ------------------------------------------------------------------------- */
async function _wikiHistory(root, params) {
  const pageId = Number(params.pageId);
  const wikiId = Number(params.id);
  try {
    const [wiki, versions] = await Promise.all([
      api.get(`/api/v1/wiki/${wikiId}`),
      api.get(`/api/v1/wiki/pages/${pageId}/versions`),
    ]);
    root.innerHTML = `
      <section class="page-head"><div>
        <h1>${escapeHtml(t("wiki.history"))}</h1>
        <p class="muted">${escapeHtml(wiki.title)} · ${escapeHtml(t("wiki.version_count", { n: versions.length }))}</p>
      </div>
      <a class="btn btn-ghost" data-link href="/wiki/${wikiId}">${escapeHtml(t("action.back"))}</a></section>
      <div class="wiki-history card">
        <ol class="version-list">
          ${versions
            .map(
              (version, index) => `
            <li class="version-item" data-version="${version.number}">
              <div>
                <strong>v${version.number}</strong>
                <span class="muted">${escapeHtml(version.author || t("wiki.unknown_author"))}</span>
                <span class="muted small">${escapeHtml(formatDate(version.created_at))}</span>
                ${version.note ? `<p class="small">${escapeHtml(version.note)}</p>` : ""}
              </div>
              <div class="row-wrap end">
                ${index < versions.length - 1
                  ? `<button class="btn btn-sm btn-ghost" data-diff="${version.number}" data-against="${versions[index + 1].number}">
                       ${escapeHtml(t("wiki.compare_previous"))}
                     </button>`
                  : `<span class="muted small">${escapeHtml(t("wiki.first_version"))}</span>`}
                <button class="btn btn-sm" data-show="${version.number}">${escapeHtml(t("wiki.view_version"))}</button>
              </div>
            </li>`,
            )
            .join("")}
        </ol>
      </div>
      <div id="wiki-diff" class="card" hidden></div>
      <div id="wiki-version-view" class="card wiki-article" hidden></div>
    `;

    const diffBox = root.querySelector("#wiki-diff");
    root.querySelectorAll("[data-diff]").forEach((button) => {
      button.addEventListener("click", async () => {
        const from = button.dataset.against;
        const to = button.dataset.diff;
        const diff = await api.get(`/api/v1/wiki/pages/${pageId}/diff?from=${from}&to=${to}`);
        diffBox.hidden = false;
        diffBox.innerHTML = `
          <header class="diff-head">
            <h2>${escapeHtml(t("wiki.diff_title", { from, to }))}</h2>
            <p class="muted small">
              <span class="diff-tally diff-tally-add">+${diff.stats.added}</span>
              <span class="diff-tally diff-tally-del">−${diff.stats.removed}</span>
              <span class="diff-legend">
                <span class="is-del">${escapeHtml(t("wiki.diff_removed"))}</span>
                <span class="is-add">${escapeHtml(t("wiki.diff_added"))}</span>
              </span>
            </p>
          </header>
          ${sideBySideHtml(diff)}
        `;
        diffBox.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    const viewer = root.querySelector("#wiki-version-view");
    root.querySelectorAll("[data-show]").forEach((button) => {
      button.addEventListener("click", async () => {
        const version = await api.get(`/api/v1/wiki/pages/${pageId}/versions/${button.dataset.show}`);
        viewer.hidden = false;
        viewer.innerHTML = `
          <header class="row-wrap">
            <h2>${escapeHtml(version.title)} · v${version.number}</h2>
            <button class="btn btn-sm" id="wiki-restore">${escapeHtml(t("wiki.restore"))}</button>
          </header>
          <div class="wiki-content">${version.html}</div>`;
        const restore = viewer.querySelector("#wiki-restore");
        if (!wiki.can_write) restore.remove();
        else
          restore.addEventListener("click", async () => {
            const ok = await confirmDialog(t("wiki.restore"), t("wiki.restore_confirm", { n: version.number }), t("wiki.restore"));
            if (!ok) return;
            await api.post(`/api/v1/wiki/pages/${pageId}/restore/${version.number}`, {});
            toast(t("wiki.restored"), "success");
            navigate(`/wiki/${wikiId}`);
          });
      });
    });
  } catch (error) {
    renderError(root, error.detail || t("error.generic"));
  }
}

export { statusPill, STATUS_ORDER };

/* The router hands one params object and expects a node back. */
export async function renderWikiHome() {
  const root = document.createElement("section");
  await _wikiHome(root);
  return root;
}

export async function renderWikiCreate() {
  const root = document.createElement("section");
  await _wikiCreate(root);
  return root;
}

export async function renderWiki(params) {
  const root = document.createElement("section");
  await _wikiPage(root, params);
  return root;
}

export async function renderWikiHistory(params) {
  const root = document.createElement("section");
  await _wikiHistory(root, params);
  return root;
}
