// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Password reset: ask for a link, then choose a new password.
 *
 * The same page serves both steps because they share a card and a layout: with
 * a token in the URL it is the second step, without one it is the request form.
 */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { navigate } from "../router.js";
import { escapeHtml, setBusy, toast } from "../ui.js";

function card() {
  const root = document.createElement("div");
  root.className = "auth-card card";
  return root;
}

export async function renderResetPassword({ params, path }) {
  const root = card();
  const token = params && params.token ? String(params.token) : "";

  if (!token) {
    root.innerHTML = `
      <h1>${t("reset.title_request")}</h1>
      <p class="muted small">${t("reset.lead_request")}</p>
      <form id="forgot-form" novalidate>
        <div class="form-error" hidden></div>
        <div class="field">
          <label class="label" for="email">${t("common.email")}</label>
          <input class="input" type="email" id="email" name="email" required autocomplete="email" />
        </div>
        <button class="btn btn-primary btn-block" type="submit">${t("reset.submit_request")}</button>
      </form>
      <p class="auth-switch"><a href="/login" data-link>${t("reset.back_to_login")}</a></p>`;

    const form = root.querySelector("#forgot-form");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector('button[type="submit"]');
      const errorBox = form.querySelector(".form-error");
      errorBox.hidden = true;
      setBusy(button, true);
      try {
        await api.post("/api/v1/auth/password/forgot", {
          email: String(new FormData(form).get("email") || "").trim(),
        });
        root.querySelector("#forgot-form").outerHTML = `<div class="banner ok">${escapeHtml(t("reset.sent"))}</div>`;
      } catch (error) {
        errorBox.textContent = error.detail || t("error.generic");
        errorBox.hidden = false;
      } finally {
        setBusy(button, false);
      }
    });
    return root;
  }

  // Second step: the token decides whether a form is worth showing at all.
  root.innerHTML = `<div class="loading">${t("common.loading")}</div>`;
  try {
    await api.get(`/api/v1/auth/password/reset/${encodeURIComponent(token)}`);
  } catch (error) {
    root.innerHTML = `
      <h1>${t("reset.title_expired")}</h1>
      <p class="muted">${escapeHtml(error.detail || t("reset.expired_body"))}</p>
      <p class="auth-switch"><a href="/forgot" data-link>${t("reset.request_again")}</a></p>`;
    return root;
  }

  root.innerHTML = `
    <h1>${t("reset.title_choose")}</h1>
    <p class="muted small">${t("reset.lead_choose")}</p>
    <form id="reset-form" novalidate>
      <div class="form-error" hidden></div>
      <div class="field">
        <label class="label" for="password">${t("common.new_password")}</label>
        <input class="input" type="password" id="password" name="password" required minlength="8"
               autocomplete="new-password" />
        <span class="hint">${t("auth.password_hint")}</span>
      </div>
      <div class="field">
        <label class="label" for="confirm">${t("common.confirm_password")}</label>
        <input class="input" type="password" id="confirm" name="confirm" required minlength="8"
               autocomplete="new-password" />
      </div>
      <button class="btn btn-primary btn-block" type="submit">${t("reset.submit_choose")}</button>
    </form>`;

  const form = root.querySelector("#reset-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const password = String(data.get("password") || "");
    const errorBox = form.querySelector(".form-error");
    errorBox.hidden = true;
    if (password !== String(data.get("confirm") || "")) {
      errorBox.textContent = t("reset.mismatch");
      errorBox.hidden = false;
      return;
    }
    const button = form.querySelector('button[type="submit"]');
    setBusy(button, true);
    try {
      await api.post("/api/v1/auth/password/reset", { token, password });
      toast(t("reset.done"), "success");
      navigate("/login");
    } catch (error) {
      errorBox.textContent = error.detail || t("error.generic");
      errorBox.hidden = false;
    } finally {
      setBusy(button, false);
    }
  });
  return root;
}
