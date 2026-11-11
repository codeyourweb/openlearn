// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Share a page: a QR code for the room, and the networks people actually use.

   A QR code is the fastest way to move a questionnaire from a screen to a phone,
   and it needs no account on either side: a published questionnaire can be
   played by a visitor who never signed up. The encoder is vendored (see
   `vendor/README.md`) and the code is drawn as one SVG path, so nothing is
   fetched from a third party — the strict CSP stays as it is.

   Every network link is a plain anchor carrying the URL: no SDK, no tracking
   pixel, no script.
*/

import { t } from "./i18n.js";
import { qrSvg } from "./qr.js";
import { copyToClipboard, escapeHtml, toast } from "./ui.js";

const NETWORKS = [
  { label: "E-mail", icon: "✉", href: (url, text) => `mailto:?subject=${text}&body=${url}` },
  { label: "WhatsApp", icon: "💬", href: (url, text) => `https://wa.me/?text=${text}%20${url}` },
  { label: "LinkedIn", icon: "in", href: (url) => `https://www.linkedin.com/sharing/share-offsite/?url=${url}` },
  { label: "X", icon: "X", href: (url, text) => `https://x.com/intent/post?url=${url}&text=${text}` },
  { label: "Facebook", icon: "f", href: (url) => `https://www.facebook.com/sharer/sharer.php?u=${url}` },
];

/**
 * The share card, ready to drop into an aside.
 *
 * @param {string} url absolute URL of the page being shared
 * @param {{title?: string, hint?: string}} options page title (message body) and
 *   the line under the QR code — a questionnaire can say it needs no account,
 *   a wiki cannot
 */
export function shareCard(url, { title = "", hint = "" } = {}) {
  const value = String(url || "").trim();
  if (!value) return "";
  const encodedUrl = encodeURIComponent(value);
  const message = title ? `${title} — OpenLearn` : "OpenLearn";
  const encodedText = encodeURIComponent(message);
  const links = NETWORKS.map(
    (network) => `
      <a class="share-link" href="${escapeHtml(network.href(encodedUrl, encodedText))}"
         target="_blank" rel="noopener noreferrer nofollow"
         title="${escapeHtml(network.label)}">
        <span class="share-icon" aria-hidden="true">${escapeHtml(network.icon)}</span>
        <span class="share-label">${escapeHtml(network.label)}</span>
      </a>`,
  ).join("");
  return `
    <section class="card share-card">
      <h3>${escapeHtml(t("share.title"))}</h3>
      <div class="share-qr">${qrSvg(value, { label: t("share.qr_label") })}</div>
      <p class="muted small">${escapeHtml(hint || t("share.qr_hint"))}</p>
      <button type="button" class="btn btn-sm btn-block" data-share-copy="${escapeHtml(value)}">
        ${escapeHtml(t("share.copy"))}
      </button>
      <div class="share-links">${links}</div>
    </section>`;
}

/** Wire the copy button of every share card under `root`. */
export function wireShare(root) {
  if (!root) return;
  for (const button of root.querySelectorAll("[data-share-copy]")) {
    button.addEventListener("click", async () => {
      const url = button.getAttribute("data-share-copy") || "";
      const copied = await copyToClipboard(url);
      // copyToClipboard already toasts; this only covers the failure path, so
      // the button never looks dead.
      if (!copied) toast(t("share.copy_failed"), "error");
    });
  }
}
