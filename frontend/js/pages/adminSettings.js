// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Administration of the instance: AI provider, mail, sign-in, audit log.
 *
 * Each rubric is one form served by `/api/v1/admin/...`. Secrets are never
 * echoed back: a password field left empty keeps the stored value, and the
 * "clear" box removes it.
 */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { escapeHtml, setBusy, toast } from "../ui.js";

const SECTION_TITLE = {
  ai: "admin.set_ai_title",
  mail: "admin.set_mail_title",
  security: "admin.set_security_title",
  instance: "admin.set_instance_title",
};

const SECTION_LEAD = {
  ai: "admin.set_ai_lead",
  mail: "admin.set_mail_lead",
  security: "admin.set_security_lead",
  instance: "admin.set_instance_lead",
};

function fieldLabel(key) {
  return t(`setting.${key}`);
}

function renderField(row) {
  const label = escapeHtml(fieldLabel(row.key));
  const id = `set-${row.key.replace(/\./g, "-")}`;
  const overridden = row.overridden ? `<span class="chip chip-sm">${escapeHtml(t("admin.set_overridden"))}</span>` : "";
  if (row.type === "bool") {
    return `
      <label class="switch-row" for="${id}">
        <input type="checkbox" id="${id}" data-key="${row.key}" data-type="bool" ${row.value ? "checked" : ""} />
        <span>${label}</span>${overridden}
      </label>`;
  }
  if (row.secret) {
    return `
      <div class="field">
        <label class="label" for="${id}">${label} ${overridden}</label>
        <input class="input" type="password" id="${id}" data-key="${row.key}" data-type="secret"
               autocomplete="new-password" placeholder="${row.is_set ? escapeHtml(t("admin.set_secret_kept")) : ""}" />
        ${row.is_set ? `<label class="checkline"><input type="checkbox" data-clear="${row.key}" /> ${escapeHtml(t("admin.set_secret_clear"))}</label>` : ""}
      </div>`;
  }
  if (row.type === "int") {
    return `
      <div class="field">
        <label class="label" for="${id}">${label} ${overridden}</label>
        <input class="input" type="number" id="${id}" data-key="${row.key}" data-type="int" value="${escapeHtml(String(row.value ?? 0))}" />
      </div>`;
  }
  return `
    <div class="field">
      <label class="label" for="${id}">${label} ${overridden}</label>
      <input class="input" type="text" id="${id}" data-key="${row.key}" data-type="str" value="${escapeHtml(String(row.value ?? ""))}" />
    </div>`;
}

function collect(panel) {
  const values = {};
  panel.querySelectorAll("[data-key]").forEach((input) => {
    const key = input.dataset.key;
    const type = input.dataset.type;
    if (type === "bool") values[key] = input.checked;
    else if (type === "int") values[key] = Number(input.value || 0);
    else values[key] = String(input.value || "").trim();
    // Empty secret fields mean "unchanged", not "erase".
    if (type === "secret" && !values[key]) delete values[key];
  });
  panel.querySelectorAll("[data-clear]").forEach((box) => {
    if (box.checked) values[box.dataset.clear] = null;
  });
  return values;
}

export async function settingsView(panel) {
  panel.innerHTML = `<div class="loading">${t("common.loading")}</div>`;
  let data;
  try {
    data = await api.get("/api/v1/admin/settings");
  } catch (error) {
    panel.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("error.generic"))}</div>`;
    return;
  }
  const env = data.environment || {};
  panel.innerHTML = `
    <div class="settings-grid">
      ${Object.entries(data.sections)
        .map(
          ([section, rows]) => `
        <section class="card settings-card" data-section="${section}">
          <header class="settings-head">
            <h2>${escapeHtml(t(SECTION_TITLE[section] || section))}</h2>
            <p class="muted small">${escapeHtml(t(SECTION_LEAD[section] || ""))}</p>
          </header>
          <div class="settings-body">
            ${rows.map(renderField).join("")}
          </div>
          <footer class="settings-foot">
            <button class="btn btn-primary" type="button" data-save="${section}">${t("action.save")}</button>
            ${section === "ai" ? `<button class="btn" type="button" data-test="ai">${t("admin.set_test_ai")}</button>` : ""}
            ${section === "mail" ? `<button class="btn" type="button" data-test="mail">${t("admin.set_test_mail")}</button>` : ""}
          </footer>
        </section>`,
        )
        .join("")}
    </div>
    <section class="card settings-card mt-3">
      <header class="settings-head">
        <h2>${t("admin.set_env_title")}</h2>
        <p class="muted small">${t("admin.set_env_lead")}</p>
      </header>
      <div class="settings-body env-facts">
        <span>${t("admin.set_env_demo")}: <strong>${env.demo_mode ? t("common.yes") : t("common.no")}</strong></span>
        <span>${t("admin.set_env_database")}: <strong>${escapeHtml(env.database || "")}</strong></span>
        <span>${t("admin.set_env_tls")}: <strong>${env.tls_enabled ? t("common.yes") : t("common.no")}</strong></span>
        <span>${t("admin.set_env_mcp")}: <strong>${env.mcp_enabled ? t("common.yes") : t("common.no")}</strong></span>
      </div>
    </section>
    <div id="settings-output" class="mt-2"></div>`;

  const output = panel.querySelector("#settings-output");

  panel.querySelectorAll("[data-save]").forEach((button) => {
    button.addEventListener("click", async () => {
      const section = button.dataset.save;
      const card = panel.querySelector(`[data-section="${section}"]`);
      setBusy(button, true);
      try {
        await api.put("/api/v1/admin/settings", { values: collect(card) });
        toast(t("admin.set_saved"), "success");
        await settingsView(panel);
      } catch (error) {
        output.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("error.generic"))}</div>`;
        setBusy(button, false);
      }
    });
  });

  const testAi = panel.querySelector('[data-test="ai"]');
  if (testAi) {
    testAi.addEventListener("click", async () => {
      setBusy(testAi, true);
      output.innerHTML = `<p class="muted">${t("admin.set_testing")}</p>`;
      try {
        const result = await api.post("/api/v1/admin/settings/ai/test", {});
        output.innerHTML = result.ok
          ? `<div class="banner ok">${escapeHtml(t("admin.set_ai_ok", { model: result.model || "", ms: String(result.latency_ms || 0) }))}</div>`
          : `<div class="banner warn">${escapeHtml(result.detail || t("admin.set_ai_failed"))}</div>`;
      } catch (error) {
        output.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("error.generic"))}</div>`;
      } finally {
        setBusy(testAi, false);
      }
    });
  }

  const testMail = panel.querySelector('[data-test="mail"]');
  if (testMail) {
    testMail.addEventListener("click", async () => {
      const to = window.prompt(t("admin.set_mail_to"), "");
      if (!to) return;
      setBusy(testMail, true);
      output.innerHTML = `<p class="muted">${t("admin.set_testing")}</p>`;
      try {
        const result = await api.post("/api/v1/admin/settings/mail/test", { to });
        output.innerHTML = result.ok
          ? `<div class="banner ok">${escapeHtml(result.detail || "")}</div>`
          : `<div class="banner warn">${escapeHtml(result.detail || t("error.generic"))}</div>`;
      } catch (error) {
        output.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("error.generic"))}</div>`;
      } finally {
        setBusy(testMail, false);
      }
    });
  }
}

/* ------------------------------------------------------------------ */
/* Identity providers                                                  */
/* ------------------------------------------------------------------ */

function providerForm(provider = {}) {
  const isSaml = provider.kind === "saml";
  return `
    <form class="settings-card card" id="provider-form" data-id="${provider.id || ""}">
      <header class="settings-head">
        <h2>${provider.id ? t("admin.sso_edit") : t("admin.sso_add")}</h2>
      </header>
      <div class="settings-body">
        <div class="grid grid-2">
          <div class="field">
            <label class="label" for="sso-label">${t("admin.sso_label")}</label>
            <input class="input" id="sso-label" name="label" required maxlength="80" value="${escapeHtml(provider.label || "")}" />
          </div>
          <div class="field">
            <label class="label" for="sso-slug">${t("admin.sso_slug")}</label>
            <input class="input" id="sso-slug" name="slug" ${provider.id ? "readonly" : "required"} maxlength="40" value="${escapeHtml(provider.slug || "")}" placeholder="okta" />
          </div>
          <div class="field">
            <label class="label" for="sso-kind">${t("admin.sso_kind")}</label>
            <select class="input" id="sso-kind" name="kind">
              <option value="oidc" ${!isSaml ? "selected" : ""}>OpenID Connect (Entra ID, Okta, Keycloak…)</option>
              <option value="saml" ${isSaml ? "selected" : ""}>SAML 2.0</option>
            </select>
          </div>
          <div class="field checkline">
            <label><input type="checkbox" name="enabled" ${provider.enabled === false ? "" : "checked"} /> ${t("admin.sso_enabled")}</label>
            <label><input type="checkbox" name="auto_create_users" ${provider.auto_create_users === false ? "" : "checked"} /> ${t("admin.sso_auto_create")}</label>
          </div>
        </div>
        <div data-kind="oidc" ${isSaml ? "hidden" : ""}>
          <div class="field">
            <label class="label" for="sso-issuer">${t("admin.sso_issuer")}</label>
            <input class="input" id="sso-issuer" name="issuer" value="${escapeHtml(provider.issuer || "")}" placeholder="https://login.microsoftonline.com/<tenant>/v2.0" />
          </div>
          <div class="grid grid-2">
            <div class="field">
              <label class="label" for="sso-client">${t("admin.sso_client_id")}</label>
              <input class="input" id="sso-client" name="client_id" value="${escapeHtml(provider.client_id || "")}" />
            </div>
            <div class="field">
              <label class="label" for="sso-secret">${t("admin.sso_client_secret")}</label>
              <input class="input" type="password" id="sso-secret" name="client_secret" autocomplete="new-password"
                     placeholder="${provider.has_secret ? escapeHtml(t("admin.set_secret_kept")) : ""}" />
            </div>
          </div>
        </div>
        <div data-kind="saml" ${isSaml ? "" : "hidden"}>
          <div class="grid grid-2">
            <div class="field">
              <label class="label" for="sso-entity">${t("admin.sso_entity_id")}</label>
              <input class="input" id="sso-entity" name="entity_id" value="${escapeHtml(provider.entity_id || "")}" />
            </div>
            <div class="field">
              <label class="label" for="sso-url">${t("admin.sso_sso_url")}</label>
              <input class="input" id="sso-url" name="sso_url" value="${escapeHtml(provider.sso_url || "")}" />
            </div>
          </div>
          <div class="field">
            <label class="label" for="sso-cert">${t("admin.sso_cert")}</label>
            <textarea class="input" id="sso-cert" name="x509_cert" rows="4" placeholder="-----BEGIN CERTIFICATE-----">${provider.x509_cert || ""}</textarea>
          </div>
        </div>
        <div class="field">
          <label class="label" for="sso-domains">${t("admin.sso_domains")}</label>
          <input class="input" id="sso-domains" name="allowed_domains" value="${escapeHtml(provider.allowed_domains || "")}" placeholder="example.com, example.org" />
        </div>
        ${provider.callback_url ? `<p class="hint">${t("admin.sso_callback")} <code>${escapeHtml(provider.callback_url)}</code></p>` : ""}
      </div>
      <footer class="settings-foot">
        <button class="btn btn-primary" type="submit">${t("action.save")}</button>
        <button class="btn" type="button" data-cancel>${t("action.cancel")}</button>
      </footer>
    </form>`;
}

export async function ssoView(panel) {
  panel.innerHTML = `<div class="loading">${t("common.loading")}</div>`;
  let providers;
  try {
    providers = await api.get("/api/v1/admin/sso/providers");
  } catch (error) {
    panel.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("error.generic"))}</div>`;
    return;
  }

  panel.innerHTML = `
    <div class="row between">
      <p class="muted small">${t("admin.sso_lead")}</p>
      <button class="btn btn-primary" type="button" data-new>${t("admin.sso_add")}</button>
    </div>
    <div class="table-wrap mt-2">
      <table class="table">
        <thead>
          <tr><th>${t("admin.sso_label")}</th><th>${t("admin.sso_kind")}</th><th>${t("admin.sso_status")}</th>
          <th>${t("admin.sso_domains")}</th><th class="right">${t("common.actions")}</th></tr>
        </thead>
        <tbody>
          ${
            providers.length
              ? providers
                  .map(
                    (provider) => `
              <tr>
                <td><strong>${escapeHtml(provider.label)}</strong><div class="small-note">/${escapeHtml(provider.slug)}</div></td>
                <td>${provider.kind === "saml" ? "SAML 2.0" : "OIDC"}</td>
                <td>${
                  provider.enabled
                    ? provider.ready
                      ? `<span class="chip chip-ok">${t("admin.sso_ready")}</span>`
                      : `<span class="chip chip-warn">${t("admin.sso_incomplete")}</span>`
                    : `<span class="chip">${t("admin.sso_disabled")}</span>`
                }</td>
                <td>${escapeHtml(provider.allowed_domains || "—")}</td>
                <td class="right">
                  <button class="icon-btn" type="button" data-edit="${provider.id}" title="${t("action.edit")}">✎</button>
                  <button class="icon-btn" type="button" data-test="${provider.id}" title="${t("admin.set_test")}">⚡</button>
                  <button class="icon-btn danger" type="button" data-delete="${provider.id}" title="${t("action.delete")}">🗑</button>
                </td>
              </tr>`,
                  )
                  .join("")
              : `<tr><td colspan="5" class="muted">${t("admin.sso_empty")}</td></tr>`
          }
        </tbody>
      </table>
    </div>
    <div id="provider-editor" class="mt-3"></div>
    <div id="sso-output" class="mt-2"></div>`;

  const editor = panel.querySelector("#provider-editor");
  const output = panel.querySelector("#sso-output");

  const openForm = (provider) => {
    editor.innerHTML = providerForm(provider || {});
    const form = editor.querySelector("#provider-form");
    const kind = form.querySelector("#sso-kind");
    kind.addEventListener("change", () => {
      form.querySelector('[data-kind="oidc"]').hidden = kind.value !== "oidc";
      form.querySelector('[data-kind="saml"]').hidden = kind.value !== "saml";
    });
    form.querySelector("[data-cancel]").addEventListener("click", () => {
      editor.innerHTML = "";
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const payload = {
        label: String(data.get("label") || "").trim(),
        kind: String(data.get("kind") || "oidc"),
        enabled: data.get("enabled") === "on",
        auto_create_users: data.get("auto_create_users") === "on",
        issuer: String(data.get("issuer") || "").trim(),
        client_id: String(data.get("client_id") || "").trim(),
        client_secret: String(data.get("client_secret") || ""),
        entity_id: String(data.get("entity_id") || "").trim(),
        sso_url: String(data.get("sso_url") || "").trim(),
        x509_cert: String(data.get("x509_cert") || "").trim(),
        allowed_domains: String(data.get("allowed_domains") || "").trim(),
      };
      if (!payload.client_secret) delete payload.client_secret;
      const id = form.dataset.id;
      const button = form.querySelector('button[type="submit"]');
      setBusy(button, true);
      try {
        if (id) await api.patch(`/api/v1/admin/sso/providers/${id}`, payload);
        else await api.post("/api/v1/admin/sso/providers", { ...payload, slug: String(data.get("slug") || "").trim() });
        toast(t("admin.sso_saved"), "success");
        await ssoView(panel);
      } catch (error) {
        output.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("error.generic"))}</div>`;
        setBusy(button, false);
      }
    });
  };

  panel.querySelector("[data-new]").addEventListener("click", () => openForm(null));
  panel.querySelectorAll("[data-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      const provider = providers.find((row) => String(row.id) === button.dataset.edit);
      if (provider) {
        openForm(provider);
        editor.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });
  });
  panel.querySelectorAll("[data-test]").forEach((button) => {
    button.addEventListener("click", async () => {
      setBusy(button, true);
      try {
        const result = await api.post(`/api/v1/admin/sso/providers/${button.dataset.test}/test`, {});
        output.innerHTML = result.ok
          ? `<div class="banner ok">${escapeHtml(t("admin.sso_test_ok", { issuer: result.issuer || "" }))}</div>`
          : `<div class="banner warn">${escapeHtml(result.detail || t("admin.sso_test_failed"))}</div>`;
      } catch (error) {
        output.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("error.generic"))}</div>`;
      } finally {
        setBusy(button, false);
      }
    });
  });
  panel.querySelectorAll("[data-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!window.confirm(t("admin.sso_delete_confirm"))) return;
      try {
        await api.del(`/api/v1/admin/sso/providers/${button.dataset.delete}`);
        toast(t("admin.sso_deleted"), "success");
        await ssoView(panel);
      } catch (error) {
        output.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("error.generic"))}</div>`;
      }
    });
  });
}

/* ------------------------------------------------------------------ */
/* AI error log                                                        */
/* ------------------------------------------------------------------ */

export async function aiLogView(panel) {
  panel.innerHTML = `<div class="loading">${t("common.loading")}</div>`;
  let data;
  try {
    data = await api.get("/api/v1/admin/ai/errors?limit=100");
  } catch (error) {
    panel.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("error.generic"))}</div>`;
    return;
  }
  panel.innerHTML = `
    <div class="row between">
      <p class="muted small">${t("admin.ai_log_lead", { total: String(data.total || 0) })}</p>
      ${data.total ? `<button class="btn" type="button" data-clear>${t("admin.ai_log_clear")}</button>` : ""}
    </div>
    ${
      data.items.length
        ? `<div class="table-wrap mt-2"><table class="table">
        <thead><tr><th>${t("admin.ai_log_when")}</th><th>${t("admin.ai_log_operation")}</th>
        <th>${t("admin.ai_log_model")}</th><th>${t("admin.ai_log_status")}</th><th>${t("admin.ai_log_detail")}</th></tr></thead>
        <tbody>
          ${data.items
            .map(
              (row) => `<tr>
              <td class="small-note">${escapeHtml(String(row.created_at || "").replace("T", " ").slice(0, 19))}</td>
              <td>${escapeHtml(row.operation || "")}</td>
              <td class="small-note">${escapeHtml(row.model || "")}</td>
              <td>${row.status_code ? escapeHtml(String(row.status_code)) : "—"}</td>
              <td class="small-note mono wrap-anywhere">${escapeHtml((row.detail || "").slice(0, 300))}</td>
            </tr>`,
            )
            .join("")}
        </tbody></table></div>`
        : `<div class="empty mt-2">${t("admin.ai_log_empty")}</div>`
    }`;

  const clear = panel.querySelector("[data-clear]");
  if (clear) {
    clear.addEventListener("click", async () => {
      if (!window.confirm(t("admin.ai_log_clear_confirm"))) return;
      await api.del("/api/v1/admin/ai/errors");
      toast(t("admin.ai_log_cleared"), "success");
      await aiLogView(panel);
    });
  }
}
