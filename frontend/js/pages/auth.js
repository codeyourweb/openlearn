// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Login and registration. */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { navigate } from "../router.js";
import { setUser } from "../store.js";
import { escapeHtml, setBusy, toast } from "../ui.js";
import { instance } from "../instance.js";

/** "Continue with <provider>" buttons, one per identity provider. */
function ssoBlock() {
  const providers = instance().sso || [];
  if (!providers.length) return "";
  return `
    <div class="sso-block">
      <p class="sso-separator"><span>${t("auth.or")}</span></p>
      ${providers
        .map(
          (provider) => `
        <a class="btn btn-ghost btn-block sso-button" href="/api/v1/auth/sso/${encodeURIComponent(provider.slug)}/start?next=${encodeURIComponent(
          location.pathname === "/login" ? "/dashboard" : location.pathname,
        )}">
          <span aria-hidden="true">🔑</span> ${escapeHtml(t("auth.sso_with", { provider: provider.label }))}
        </a>`,
        )
        .join("")}
    </div>`;
}

function safeNext(query) {
  const next = query && query.next ? String(query.next) : "/dashboard";
  return next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
}

function bindForm(root, form, submit) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    const errorBox = form.querySelector(".form-error");
    errorBox.hidden = true;
    setBusy(button, true);
    try {
      await submit(new FormData(form));
      // The login payload only carries the token: read the profile back, both to
      // fill the header and to name the session in the welcome toast (it used to
      // read "Signed in as ." because the name was never there).
      const me = await api.get("/api/v1/auth/me");
      setUser(me);
      window.dispatchEvent(new CustomEvent("oq:auth-changed"));
      toast(t("auth.welcome", { name: (me && (me.display_name || me.email)) || "" }), "success");
      navigate(safeNext(root.dataset.next));
    } catch (error) {
      errorBox.textContent = error.detail || t("error.generic");
      errorBox.hidden = false;
    } finally {
      setBusy(button, false);
    }
  });
}

export async function renderLogin({ query }) {
  const root = document.createElement("div");
  root.className = "auth-card card";
  root.dataset.next = safeNext(query);
  root.innerHTML = `
    <h1>${t("auth.login_title")}</h1>
    <p class="muted small">${t("auth.login_subtitle")}</p>
    <form id="login-form" novalidate>
      <div class="form-error" hidden></div>
      <div class="field">
        <label class="label" for="email">${t("common.email")}</label>
        <input class="input" type="email" id="email" name="email" required autocomplete="email" />
      </div>
      <div class="field">
        <label class="label" for="password">${t("common.password")}</label>
        <input class="input" type="password" id="password" name="password" required autocomplete="current-password" />
      </div>
      <button class="btn btn-primary btn-block" type="submit">${t("auth.submit_login")}</button>
      <p class="auth-forgot"><a href="/forgot" data-link>${t("auth.forgot_link")}</a></p>
    </form>
    ${ssoBlock()}
    <p class="auth-switch">${t("auth.no_account")} <a href="/register" data-link>${t("nav.signup")}</a></p>`;

  bindForm(root, root.querySelector("#login-form"), async (data) => {
    await api.post("/api/v1/auth/login", {
      email: String(data.get("email") || "").trim(),
      password: String(data.get("password") || ""),
    });
  });
  return root;
}

export async function renderRegister({ query }) {
  const root = document.createElement("div");
  root.className = "auth-card card";
  root.dataset.next = safeNext(query);
  root.innerHTML = `
    <h1>${t("auth.register_title")}</h1>
    <p class="muted small">${t("auth.register_subtitle")}</p>
    <form id="register-form" novalidate>
      <div class="form-error" hidden></div>
      <div class="field">
        <label class="label" for="display_name">${t("common.display_name")}</label>
        <input class="input" id="display_name" name="display_name" required minlength="2" maxlength="60" autocomplete="nickname" />
      </div>
      <div class="field">
        <label class="label" for="email">${t("common.email")}</label>
        <input class="input" type="email" id="email" name="email" required autocomplete="email" />
      </div>
      <div class="field">
        <label class="label" for="password">${t("common.password")}</label>
        <input class="input" type="password" id="password" name="password" required minlength="8" autocomplete="new-password" />
        <span class="hint">${t("auth.password_hint")}</span>
      </div>
      <button class="btn btn-primary btn-block" type="submit">${t("auth.submit_register")}</button>
    </form>
    <p class="auth-switch">${t("auth.have_account")} <a href="${escapeHtml(
      `/login?next=${encodeURIComponent(safeNext(query))}`,
    )}" data-link>${t("nav.signin")}</a></p>`;

  bindForm(root, root.querySelector("#register-form"), async (data) => {
    await api.post("/api/v1/auth/register", {
      display_name: String(data.get("display_name") || "").trim(),
      email: String(data.get("email") || "").trim(),
      password: String(data.get("password") || ""),
    });
  });
  return root;
}
