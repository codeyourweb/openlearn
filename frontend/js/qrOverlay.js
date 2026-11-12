// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* A QR code, full screen, for the room.

   A trainer projects the page from a video projector; the 148px code in the
   aside is meant for a phone held near the screen, not for the last row. One
   click opens the same code at the size of the window, on white, with the
   address printed under it for whoever cannot scan.

   Drawn locally like every other code here (no image request, no third party),
   and the dialog closes on Escape, on the backdrop and on its own button, then
   gives the focus back to whatever opened it.
*/

import { t } from "./i18n.js";
import { qrSvg } from "./qr.js";
import { escapeHtml } from "./ui.js";

let opened = null;

/**
 * @param {string} url the address the code carries
 * @param {{title?: string, hint?: string, label?: string}} options
 */
export function openQrOverlay(url, { title = "", hint = "", label = "" } = {}) {
  const value = String(url || "").trim();
  if (!value || opened) return;

  const previous = document.activeElement;
  const overlay = document.createElement("div");
  overlay.className = "qr-overlay";
  overlay.dataset.qrOverlay = "1";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", label || t("share.qr_label"));
  overlay.innerHTML = `
    <div class="qr-overlay-card">
      ${title ? `<p class="qr-overlay-title">${escapeHtml(title)}</p>` : ""}
      <div class="qr-overlay-qr">${qrSvg(value)}</div>
      <p class="qr-overlay-url">${escapeHtml(value)}</p>
      ${hint ? `<p class="qr-overlay-hint">${escapeHtml(hint)}</p>` : ""}
      <button class="btn" type="button" data-qr-close>${escapeHtml(t("action.close"))}</button>
    </div>`;

  const close = () => {
    if (opened !== overlay) return;
    overlay.remove();
    document.body.classList.remove("qr-open");
    document.removeEventListener("keydown", onKey, true);
    opened = null;
    if (previous && typeof previous.focus === "function" && document.contains(previous)) {
      previous.focus();
    }
  };

  function onKey(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    // One control, so the trap is trivial — but it must not walk into the page
    // behind the dialog.
    const items = Array.from(overlay.querySelectorAll("button, a[href], input"));
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  overlay.addEventListener("click", (event) => {
    const target = /** @type {HTMLElement} */ (event.target);
    if (target === overlay || target.closest("[data-qr-close]")) close();
  });

  document.body.appendChild(overlay);
  document.body.classList.add("qr-open");
  document.addEventListener("keydown", onKey, true);
  opened = overlay;
  overlay.querySelector("[data-qr-close]")?.focus();
}
