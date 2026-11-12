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
import { qrSharingEnabled, socialSharingEnabled } from "./instance.js";
import { qrSvg } from "./qr.js";
import { openQrOverlay } from "./qrOverlay.js";
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
  const withQr = qrSharingEnabled();
  const withNetworks = socialSharingEnabled();
  const links = withNetworks
    ? NETWORKS.map(
        (network) => `
      <a class="share-link" href="${escapeHtml(network.href(encodedUrl, encodedText))}"
         target="_blank" rel="noopener noreferrer nofollow"
         title="${escapeHtml(network.label)}">
        <span class="share-icon" aria-hidden="true">${escapeHtml(network.icon)}</span>
        <span class="share-label">${escapeHtml(network.label)}</span>
      </a>`,
      ).join("")
    : "";
  // An isolated network has no use for a code pointing at a closed host, nor for
  // links that cannot resolve: each switch drops its own block, and the card is
  // then just the address to copy into whatever the room already uses.
  const qrBlock = withQr
    ? `
      <button type="button" class="share-qr-open" data-share-qr="${escapeHtml(value)}"
              data-share-title="${escapeHtml(title)}"
              title="${escapeHtml(t("share.qr_open"))}" aria-label="${escapeHtml(t("share.qr_open"))}">
        <span class="share-qr">${qrSvg(value, { label: t("share.qr_label") })}</span>
      </button>
      <p class="muted small">${escapeHtml(hint || t("share.qr_hint"))}</p>`
    : `<p class="muted small">${escapeHtml(t("share.copy_hint"))}</p>`;
  return `
    <section class="card share-card" data-sharing="qr:${withQr ? "on" : "off"} social:${withNetworks ? "on" : "off"}">
      <h3>${escapeHtml(t("share.title"))}</h3>
      ${qrBlock}
      <button type="button" class="btn btn-sm btn-block" data-share-copy="${escapeHtml(value)}">
        ${escapeHtml(t("share.copy"))}
      </button>
      ${links ? `<div class="share-links">${links}</div>` : ""}
    </section>`;
}

/** Wire the copy button and the QR opener of every share card under `root`. */
export function wireShare(root) {
  if (!root) return;
  for (const button of root.querySelectorAll("[data-share-qr]")) {
    button.addEventListener("click", () => {
      const url = button.getAttribute("data-share-qr") || "";
      const title = button.getAttribute("data-share-title") || "";
      openQrOverlay(url, { title, hint: t("share.qr_project_hint") });
    });
  }
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

/**
 * Put the share card where it belongs on the screen the reader has.
 *
 * On a wide screen it sits in the aside, under the facts: you read the page, the
 * card is already there beside it. On a phone there is no "beside", and a card
 * that opens above the article pushes the very thing the reader came for below
 * the fold — a QR code before the first sentence. Under 860 px (the width at
 * which the aside stacks) the card moves to the end of the document instead,
 * where a reader who wants to share it has finished reading anyway.
 */
export function placeShare(root, slotSelector) {
  const card = root.querySelector(".share-card");
  const slot = root.querySelector(slotSelector);
  if (!card || !slot) return;
  const home = card.parentElement;
  const query = window.matchMedia("(max-width: 860px)");
  let watcher = null;

  const endWatch = () => {
    if (watcher) {
      watcher.disconnect();
      watcher = null;
    }
  };

  // A page may build its tree detached and attach it a moment later: an
  // unattached card is not a discarded one. Watch the insertion, then place it,
  // and give up after a few seconds if it never arrives — that is a page that
  // re-rendered, and holding a dead node forever would leak on every visit.
  const waitForAttachment = () => {
    if (watcher) return;
    watcher = new MutationObserver(() => {
      if (!card.isConnected) return;
      endWatch();
      place();
    });
    watcher.observe(document.body, { childList: true, subtree: true });
    // The listeners stay: a window that grows must still get its card back.
    window.setTimeout(endWatch, 5000);
  };

  const place = () => {
    if (!card.isConnected) {
      waitForAttachment();
      return;
    }
    if (query.matches) {
      if (card.parentElement !== slot) slot.appendChild(card);
    } else if (card.parentElement !== home) {
      home.appendChild(card);
    }
  };

  place();
  // An emulated phone can still report the desktop fallback width while the
  // page script runs, so `matchMedia` may answer false here and turn true once
  // the document is laid out. Re-place on the next frame, and on every change
  // of width afterwards.
  requestAnimationFrame(place);
  query.addEventListener("change", place);
  window.addEventListener("resize", place);
}
