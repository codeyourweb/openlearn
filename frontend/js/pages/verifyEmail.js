// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Address confirmation: the page a mailed link opens, and the reminder shown to
 * a signed-in visitor whose address is still a claim.
 *
 * Nothing is blocked while the address is unconfirmed — the account works — but
 * the interface says so until the link is opened, and offers to send it again.
 */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { state } from "../store.js";
import { escapeHtml, setBusy, toast } from "../ui.js";

const BANNER_ID = "verify-email-banner";

export async function renderVerifyEmail({ token: rawToken }) {
  /* Path parameters arrive at the top level (see `register` in router.js). A
     handler reading `{ params }` silently got an empty token and confirmed
     nothing, so every mailed confirmation opened as a bad link. */
  const token = rawToken ? String(rawToken) : "";
  const root = document.createElement("div");
  root.className = "auth-card card";
  root.innerHTML = `<div class="loading">${t("common.loading")}</div>`;

  try {
    await api.get(`/api/v1/auth/email/verify/${encodeURIComponent(token)}`);
    const user = await api.get("/api/v1/auth/me").catch(() => null);
    if (user) {
      const { setUser } = await import("../store.js");
      setUser(user);
      window.dispatchEvent(new CustomEvent("oq:auth-changed"));
    }
    root.innerHTML = `
      <h1>${t("verify.ok_title")}</h1>
      <p class="muted">${t("verify.ok_body")}</p>
      <p class="auth-switch"><a class="btn btn-primary" href="/dashboard" data-link>${t("verify.continue")}</a></p>`;
  } catch (error) {
    root.innerHTML = `
      <h1>${t("verify.bad_title")}</h1>
      <p class="muted">${escapeHtml(error.detail || t("verify.bad_body"))}</p>
      <p class="auth-switch"><a href="/login" data-link>${t("verify.back_to_login")}</a></p>`;
  }
  return root;
}

/** Send the link again, from the banner or the account page. */
export async function resendVerification(button) {
  if (button) setBusy(button, true);
  try {
    const result = await api.post("/api/v1/auth/email/resend", {});
    toast(result.sent ? t("verify.resent") : t("verify.throttled"), result.sent ? "success" : "info");
    return result;
  } catch (error) {
    toast(error.detail || t("error.generic"), "error");
    return null;
  } finally {
    if (button) setBusy(button, false);
  }
}

/** The reminder itself: one line, one button, no modal. */
export function renderVerificationBanner(container) {
  const existing = document.getElementById(BANNER_ID);
  const needed =
    Boolean(state.user) && state.user.email_verified === false && !location.pathname.startsWith("/verify/");
  if (!needed) {
    if (existing) existing.remove();
    return;
  }
  if (existing || !container) return;

  const banner = document.createElement("div");
  banner.id = BANNER_ID;
  banner.className = "banner warn";
  banner.setAttribute("role", "status");
  banner.innerHTML = `
    <strong>${t("verify.banner")}</strong>
    <span class="muted small">${t("verify.banner_lead")}</span>
    <button type="button" class="btn btn-small" id="verify-resend-inline">${t("verify.resend")}</button>`;
  container.prepend(banner);
  banner.querySelector("#verify-resend-inline").addEventListener("click", (event) => {
    resendVerification(event.currentTarget);
  });
}

export function verificationRow() {
  if (!state.user) return "";
  if (state.user.email_verified) {
    return `<div class="row-between"><span>${t("verify.status_label")}</span>
      <span class="badge ok">${t("verify.status_ok")}</span></div>`;
  }
  return `<div class="row-between"><span>${t("verify.status_label")}</span>
      <span class="badge warn">${t("verify.status_pending")}</span></div>
    <p class="muted small">${t("verify.banner_lead")}</p>
    <button type="button" class="btn btn-small" id="verify-resend-account">${t("verify.resend")}</button>`;
}

export function wireAccountResend(root) {
  const button = root.querySelector("#verify-resend-account");
  if (button) button.addEventListener("click", (event) => resendVerification(event.currentTarget));
}
