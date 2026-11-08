// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Browser-side HTML sanitiser: mirrors the server allowlist.

   The server is authoritative; this only keeps the editor and the renderer
   consistent and never lets unsanitised markup reach the DOM. */

const ALLOWED = new Set([
  "p", "br", "strong", "b", "em", "i", "u", "s",
  "ul", "ol", "li", "h1", "h2", "h3", "h4",
  "blockquote", "code", "pre", "sub", "sup", "span",
]);

function cleanChildren(node) {
  const fragment = document.createDocumentFragment();
  for (const child of Array.from(node.childNodes)) {
    if (child.nodeType === Node.TEXT_NODE) {
      fragment.appendChild(document.createTextNode(child.nodeValue));
    } else if (child.nodeType === Node.ELEMENT_NODE) {
      const tag = child.tagName.toLowerCase();
      if (ALLOWED.has(tag)) {
        const element = document.createElement(tag); // no attributes copied
        element.appendChild(cleanChildren(child));
        fragment.appendChild(element);
      } else {
        fragment.appendChild(cleanChildren(child)); // keep text, drop the tag
      }
    }
  }
  return fragment;
}

export function sanitizeHtml(html) {
  if (!html) return "";
  const template = document.createElement("template");
  template.innerHTML = String(html);
  const container = document.createElement("div");
  container.appendChild(cleanChildren(template.content));
  return container.innerHTML;
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function htmlToText(html) {
  const container = document.createElement("div");
  container.innerHTML = sanitizeHtml(html);
  return (container.textContent || "").replace(/\s+/g, " ").trim();
}
