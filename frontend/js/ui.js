// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Small DOM/UI helpers shared by every page. */

import { t } from "./i18n.js";
import { escapeHtml } from "./sanitize.js";

export { escapeHtml };

export function qs(selector, root = document) {
  return root.querySelector(selector);
}

export function qsa(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

export function toast(message, type = "info", timeout = 4200) {
  const region = document.getElementById("toast-region");
  if (!region) return;
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.textContent = message;
  region.appendChild(node);
  setTimeout(() => {
    node.style.opacity = "0";
    node.style.transition = "opacity .2s";
    setTimeout(() => node.remove(), 220);
  }, timeout);
}

export function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}m ${rest}s`;
}

export function setBusy(button, busy, label = "Working…") {
  if (!button) return;
  if (busy) {
    button.dataset.originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = label;
  } else {
    button.disabled = false;
    if (button.dataset.originalLabel) button.textContent = button.dataset.originalLabel;
  }
}

/**
 * Determinate progress overlay for an upload.
 *
 * The editors call ``update(ratio)`` from the XHR progress event and ``done()``
 * once the request settles. A photo taken on a phone can take seconds to leave
 * the device: without this the UI simply froze.
 */
export function showUploadProgress(label, fileName = "") {
  const node = document.createElement("div");
  node.className = "upload-progress";
  node.setAttribute("role", "status");
  node.setAttribute("aria-live", "polite");
  node.innerHTML = `
    <span class="upload-label"></span>
    <div class="upload-track"><div class="upload-fill"></div></div>
    <span class="upload-percent">0%</span>`;
  node.querySelector(".upload-label").textContent = fileName ? `${label} · ${fileName}` : label;
  document.body.appendChild(node);
  const fill = node.querySelector(".upload-fill");
  const percent = node.querySelector(".upload-percent");
  return {
    update(ratio) {
      const value = Math.max(0, Math.min(1, Number(ratio) || 0));
      fill.style.width = `${Math.round(value * 100)}%`;
      percent.textContent = `${Math.round(value * 100)}%`;
    },
    /* Bytes are on the server: the server still has to decode the image. */
    finishing() {
      node.classList.add("is-finishing");
      node.querySelector(".upload-label").textContent = `${label}…`;
      fill.style.width = "100%";
      percent.textContent = "100%";
    },
    done() {
      node.remove();
    },
  };
}

/**
 * Full-screen busy overlay for a slow server-side job (AI translation, review,
 * generation). The request can take tens of seconds: without it the page looks
 * frozen and people click again.
 */
export function showBusyOverlay(label) {
  const node = document.createElement("div");
  node.className = "busy-overlay";
  node.setAttribute("role", "status");
  node.setAttribute("aria-live", "assertive");
  node.innerHTML = `
    <div class="busy-card">
      <span class="busy-spinner" aria-hidden="true"></span>
      <p class="busy-label"></p>
    </div>`;
  node.querySelector(".busy-label").textContent = label;
  document.body.appendChild(node);
  return {
    label(text) {
      node.querySelector(".busy-label").textContent = text;
    },
    done() {
      node.remove();
    },
  };
}

export function confirmDialog(title, message, confirmLabel = "Confirm") {
  return new Promise((resolve) => {
    const root = document.getElementById("modal-root");
    // A dialog that swallows Tab, forgets where the focus came from and offers
    // no way out by keyboard is a trap for anyone not using a mouse.
    const previous = document.activeElement;
    root.innerHTML = `
      <div class="modal-backdrop" role="presentation">
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"
             aria-describedby="modal-desc" tabindex="-1">
          <h3 id="modal-title">${escapeHtml(title)}</h3>
          <p class="muted" id="modal-desc">${escapeHtml(message)}</p>
          <div class="modal-actions">
            <button class="btn btn-ghost" data-action="cancel">${escapeHtml(t("action.cancel"))}</button>
            <button class="btn btn-danger" data-action="confirm">${escapeHtml(confirmLabel)}</button>
          </div>
        </div>
      </div>`;
    const modal = root.querySelector(".modal");
    const close = (value) => {
      root.innerHTML = "";
      document.removeEventListener("keydown", onKey, true);
      if (previous && typeof previous.focus === "function" && document.contains(previous)) {
        previous.focus();
      }
      resolve(value);
    };
    const focusables = () => Array.from(modal.querySelectorAll("button, [href], input, select, textarea"));
    const onKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close(false);
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables();
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
    };
    document.addEventListener("keydown", onKey, true);
    root.querySelector('[data-action="cancel"]').addEventListener("click", () => close(false));
    root.querySelector('[data-action="confirm"]').addEventListener("click", () => close(true));
    root.querySelector(".modal-backdrop").addEventListener("click", (event) => {
      if (event.target.classList.contains("modal-backdrop")) close(false);
    });
    // The safe answer takes the focus: a destructive action should not be one
    // stray Enter away.
    root.querySelector('[data-action="cancel"]').focus();
  });
}

/**
 * Copy text, with a fallback for insecure origins.
 *
 * `navigator.clipboard` only exists in a secure context, so a plain-HTTP
 * deployment (a LAN address or a bare port) silently lost the share link. The
 * textarea + execCommand path covers those origins.
 */
export async function copyToClipboard(text) {
  const value = String(text ?? "");
  if (!value) return false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      toast(t("common.copied"), "success");
      return true;
    }
  } catch {
    /* fall through to the legacy path */
  }
  try {
    const field = document.createElement("textarea");
    field.value = value;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.top = "-1000px";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    field.setSelectionRange(0, value.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(field);
    toast(ok ? t("common.copied") : t("common.copy_failed"), ok ? "success" : "error");
    return ok;
  } catch {
    toast(t("common.copy_failed"), "error");
    return false;
  }
}

/** Native share sheet when available; returns false so callers can fall back. */
export async function shareLink({ title, text, url }) {
  if (!navigator.share) return false;
  try {
    await navigator.share({ title, text, url });
    return true;
  } catch (error) {
    return error && error.name === "AbortError";
  }
}

export function renderError(container, message) {
  container.innerHTML = `<div class="banner warn">${escapeHtml(message)}</div>`;
}

export function statusBadge(status) {
  const map = {
    lobby: ["muted", "Lobby"],
    active: ["ok", "Live"],
    finished: ["", "Finished"],
    cancelled: ["danger", "Cancelled"],
  };
  const [variant, label] = map[status] || ["muted", status];
  return `<span class="badge ${variant}">${escapeHtml(label)}</span>`;
}

/**
 * Pager markup for a long list.
 *
 * A list of a thousand items must not be one endless scroll: the caller asks
 * the API for one window and renders this under it. ``page`` is 0-based.
 */
export function pagerHtml(page, total, pageSize) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  // A filtered list that returns nothing, or everything, still has to say how
  // many rows it holds — otherwise the reader cannot tell a filter from a bug.
  const count =
    total > 0
      ? `<p class="muted small list-count">${escapeHtml(
          t(total === 1 ? "common.results_one" : "common.results_many", { n: total }),
        )}</p>`
      : "";
  if (pages <= 1) return count;
  const first = Math.max(0, Math.min(page - 2, pages - 5));
  const numbers = [];
  for (let index = first; index < Math.min(pages, first + 5); index += 1) {
    numbers.push(
      `<button class="pager-num ${index === page ? "is-active" : ""}" data-page="${index}"
               aria-current="${index === page ? "page" : "false"}">${index + 1}</button>`,
    );
  }
  return `
    ${count}
    <nav class="pager" aria-label="${escapeHtml(t("common.pagination"))}">
      <button class="btn btn-sm btn-ghost" data-page="${page - 1}" ${page === 0 ? "disabled" : ""}>
        ${escapeHtml(t("common.prev"))}
      </button>
      ${numbers.join("")}
      <button class="btn btn-sm btn-ghost" data-page="${page + 1}" ${page >= pages - 1 ? "disabled" : ""}>
        ${escapeHtml(t("common.next"))}
      </button>
      <span class="muted small">${pages} ${escapeHtml(t("common.pages"))}</span>
    </nav>`;
}

/** Wire the buttons produced by ``pagerHtml``. */
export function bindPager(container, onGo) {
  container.querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => {
      const page = Number(button.dataset.page);
      if (Number.isFinite(page) && page >= 0) onGo(page);
    });
  });
}
