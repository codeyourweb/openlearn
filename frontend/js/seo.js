// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Per-page metadata, from the client.
 *
 * The server already fills the shell for the first request (see backend
 * `seo.py`); this keeps the tab, the canonical URL and the social preview
 * correct when the reader moves around without reloading.
 */

import { t } from "./i18n.js";

const SITE = "OpenLearn";

/** A readable slug for a title, the same shape the backend produces. */
export function titleSlug(title, fallback = "item") {
  const slug = String(title || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 70);
  return slug || fallback;
}

/** Canonical path for a document: id first, slug as a readable suffix. */
export function documentPath(kind, id, title, extra = "") {
  const slug = titleSlug(title, kind);
  return `/${kind}/${id}/${slug}${extra}`;
}

function _upsert(selector, create) {
  let node = document.head.querySelector(selector);
  if (!node) {
    node = create();
    document.head.appendChild(node);
  }
  return node;
}

function _meta(property, content, attr = "property") {
  if (!content) return;
  const node = _upsert(`meta[${attr}="${property}"]`, () => {
    const element = document.createElement("meta");
    element.setAttribute(attr, property);
    return element;
  });
  node.setAttribute("content", content);
}

/**
 * Describe the page currently on screen.
 *
 * @param {object} options
 * @param {string} options.title      page title, without the site name
 * @param {string} [options.description]
 * @param {string} [options.path]     canonical path (defaults to the location)
 * @param {string} [options.type]     Open Graph type
 * @param {string} [options.image]    absolute or site-relative image URL
 * @param {object} [options.jsonLd]   structured data for this page
 */
export function setPageSeo({ title, description, path, type = "website", image, jsonLd } = {}) {
  const fullTitle = title ? `${title} — ${SITE}` : `${SITE} — ${t("about.tagline")}`;
  document.title = fullTitle;
  const canonical = `${location.origin}${path || location.pathname}`;

  _meta("description", description || "", "name");
  _meta("og:title", fullTitle);
  _meta("og:description", description || "");
  _meta("og:type", type);
  _meta("og:url", canonical);
  _meta("twitter:card", "summary_large_image");
  _meta("twitter:title", fullTitle);
  _meta("twitter:description", description || "");
  if (image) {
    const absolute = image.startsWith("http") ? image : `${location.origin}${image}`;
    _meta("og:image", absolute);
    _meta("twitter:image", absolute);
  }

  const link = _upsert('link[rel="canonical"]', () => {
    const element = document.createElement("link");
    element.setAttribute("rel", "canonical");
    return element;
  });
  link.setAttribute("href", canonical);

  const existing = document.head.querySelector('script[data-page-jsonld]');
  if (existing) existing.remove();
  if (jsonLd) {
    const script = document.createElement("script");
    script.type = "application/ld+json";
    script.dataset.pageJsonld = "1";
    script.textContent = JSON.stringify(jsonLd);
    document.head.appendChild(script);
  }
}
