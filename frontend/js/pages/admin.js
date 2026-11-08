// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Administration: moderation queue, all quizzes, wikis, accounts, AI reviews, audit.
 *
 * Every rubric is a list that can outgrow one screen, so every rubric has a
 * filter field and a pager; both are served by the API (`q`, `limit`, `offset`,
 * `X-Total-Count`) rather than filtered in the browser.
 */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { navigate } from "../router.js";
import { state } from "../store.js";
import { bindPager, confirmDialog, escapeHtml, pagerHtml, toast } from "../ui.js";
import { aiLogView, settingsView, ssoView } from "./adminSettings.js";
import { legalEditorView } from "./legalEditor.js";

const PAGE_SIZE = 25;

/** The filter field every rubric shares. */
function filterBar(id, value, placeholder) {
  return `
    <form class="search-form" role="search" id="${id}-form">
      <input class="input" id="${id}" name="q" type="search" value="${escapeHtml(value)}"
             placeholder="${escapeHtml(placeholder)}" aria-label="${escapeHtml(placeholder)}" />
      <button class="btn" type="submit">${t("action.search")}</button>
    </form>`;
}

function bindFilter(panel, id, onSearch) {
  const input = panel.querySelector(`#${id}`);
  const form = panel.querySelector(`#${id}-form`);
  if (!input || !form) return;
  let timer = null;
  const fire = () => onSearch(input.value.trim());
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(fire, 250);
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    clearTimeout(timer);
    fire();
  });
}

/** Rows + total for one rubric; the caller renders them. */
async function page_(endpoint, params, page) {
  const search = new URLSearchParams(params);
  search.set("limit", String(PAGE_SIZE));
  search.set("offset", String(page * PAGE_SIZE));
  const meta = await api.getMeta(`${endpoint}?${search.toString()}`);
  return { rows: meta.data || [], total: Number(meta.headers.get("X-Total-Count") || (meta.data || []).length) };
}

export async function renderAdmin({ query }) {
  if (!state.user || !state.user.is_staff) {
    const root = document.createElement("div");
    root.innerHTML = `
      <div class="empty">
        <h2>${t("admin.not_authorized")}</h2>
        <a class="btn mt-2" href="/" data-link>${t("nav.home")}</a>
      </div>`;
    return root;
  }

  const root = document.createElement("div");
  const ADMIN_ONLY_TABS = ["settings", "sso", "ailog", "legal"];
  let tab = (query && query.tab) || "queue";
  if (!state.user.is_admin && ADMIN_ONLY_TABS.includes(tab)) tab = "queue";

  const render = async () => {
    root.innerHTML = `<div class="loading">${t("common.loading")}</div>`;
    let stats = null;
    try {
      stats = await api.get("/api/v1/admin/stats");
    } catch (error) {
      root.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
      return;
    }
    const pendingCount = (stats.quizzes.by_status || {}).pending || 0;

    root.innerHTML = `
      <div class="row between">
        <div>
          <h1>${t("admin.title")}</h1>
          <p class="muted">${t("admin.subtitle")}</p>
        </div>
      </div>
      <div class="grid grid-4 mt-2">
        <div class="card"><div class="muted small">${t("admin.stats_total")}</div><div class="pin-display sm">${stats.quizzes.total}</div></div>
        <div class="card"><div class="muted small">${t("admin.stats_pending")}</div><div class="pin-display sm">${pendingCount}</div></div>
        <div class="card"><div class="muted small">${t("admin.stats_users")}</div><div class="pin-display sm">${stats.users.total}</div></div>
        <div class="card"><div class="muted small">${t("admin.stats_blocked")}</div><div class="pin-display sm">${stats.reviews.blocked}</div></div>
      </div>
      <div class="tabs mt-3">
        <button class="tab ${tab === "queue" ? "is-active" : ""}" data-tab="queue">${t("admin.tab_queue")}<span class="tab-count">${pendingCount}</span></button>
        <button class="tab ${tab === "quizzes" ? "is-active" : ""}" data-tab="quizzes">${t("admin.tab_quizzes")}</button>
        <button class="tab ${tab === "wikis" ? "is-active" : ""}" data-tab="wikis">${t("admin.tab_wikis")}<span class="tab-count">${(stats.wikis || {}).pending || 0}</span></button>
        <button class="tab ${tab === "users" ? "is-active" : ""}" data-tab="users">${t("admin.tab_users")}</button>
        <button class="tab ${tab === "reviews" ? "is-active" : ""}" data-tab="reviews">${t("admin.tab_reviews")}</button>
        <button class="tab ${tab === "events" ? "is-active" : ""}" data-tab="events">${t("admin.tab_events")}</button>
        ${
          // AI, mail and SSO configuration stay with the administrator; a
          // moderator only validates content.
          state.user.is_admin
            ? `<button class="tab ${tab === "settings" ? "is-active" : ""}" data-tab="settings">${t("admin.tab_settings")}</button>
        <button class="tab ${tab === "sso" ? "is-active" : ""}" data-tab="sso">${t("admin.tab_sso")}</button>
        <button class="tab ${tab === "ailog" ? "is-active" : ""}" data-tab="ailog">${t("admin.tab_ai_log")}</button>
        <button class="tab ${tab === "legal" ? "is-active" : ""}" data-tab="legal">${t("admin.tab_legal")}</button>`
            : ""
        }
      </div>
      <div id="tab-panel"></div>`;

    root.querySelectorAll("[data-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        tab = button.dataset.tab;
        navigate(`/admin?tab=${tab}`, { replace: true });
        render();
      });
    });

    const panel = root.querySelector("#tab-panel");
    const views = {
      queue: queueView,
      quizzes: quizzesView,
      wikis: wikisView,
      users: usersView,
      reviews: reviewsView,
      events: eventsView,
      settings: settingsView,
      sso: ssoView,
      ailog: aiLogView,
      legal: legalEditorView,
    };
    await (views[tab] || queueView)(panel, "", 0);
  };

  /* ------------------------------------------------------------------ */
  /* Moderation queue                                                   */
  /* ------------------------------------------------------------------ */
  const queueView = async (panel, term, page) => {
    panel.innerHTML = `
      <div class="list-head">${filterBar("queue-filter", term, t("admin.filter_quizzes"))}</div>
      <div id="admin-rows" class="mt-2"><p class="muted">…</p></div>
      <div id="admin-pager" class="pager-slot"></div>`;

    const slot = panel.querySelector("#admin-rows");
    let data;
    try {
      data = await page_("/api/v1/admin/quizzes", { status: "pending", ...(term ? { q: term } : {}) }, page);
    } catch (error) {
      slot.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
      return;
    }
    slot.innerHTML = data.rows.length
      ? `<div class="table-wrap"><table class="table">
          <thead><tr>
            <th>${t("dash.col_title")}</th><th>${t("common.owner")}</th><th>${t("dash.col_questions")}</th>
            <th>${t("admin.note")}</th><th class="right">${t("common.actions")}</th>
          </tr></thead>
          <tbody>
            ${data.rows
              .map(
                (row) => `
              <tr data-quiz="${row.id}">
                <td>
                  <a href="/quizzes/${row.id}" data-link><strong>${escapeHtml(row.title)}</strong></a>
                  <div class="small-note">${escapeHtml((row.description || "").slice(0, 120))}</div>
                  ${row.legal_status ? `<span class="pill ${row.legal_status === "blocked" ? "rejected" : "public"}">${row.legal_status}</span>` : ""}
                </td>
                <td class="small-note">${escapeHtml(row.owner_name)}<br />${escapeHtml(row.owner_email)}</td>
                <td>${row.question_count}</td>
                <td><input class="input" data-note maxlength="300" placeholder="${t("admin.note")}" /></td>
                <td class="right">
                  <div class="row-wrap end">
                    <button class="btn btn-sm btn-primary" data-act="approve">${t("action.approve")}</button>
                    <button class="btn btn-sm btn-danger" data-act="reject">${t("action.reject")}</button>
                  </div>
                </td>
              </tr>`,
              )
              .join("")}
          </tbody></table></div>`
      : `<div class="empty"><p class="muted">${term ? t("common.no_result") : t("admin.queue_empty")}</p></div>`;

    const pager = panel.querySelector("#admin-pager");
    pager.innerHTML = pagerHtml(page, data.total, PAGE_SIZE);
    bindPager(pager, (next) => queueView(panel, term, next));
    bindFilter(panel, "queue-filter", (value) => queueView(panel, value, 0));
  };

  /* ------------------------------------------------------------------ */
  /* All questionnaires                                                 */
  /* ------------------------------------------------------------------ */
  const quizzesView = async (panel, term, page) => {
    panel.innerHTML = `
      <div class="list-head">${filterBar("quiz-filter", term, t("admin.filter_quizzes"))}</div>
      <div id="admin-rows" class="mt-2"><p class="muted">…</p></div>
      <div id="admin-pager" class="pager-slot"></div>`;

    const slot = panel.querySelector("#admin-rows");
    let data;
    try {
      data = await page_("/api/v1/admin/quizzes", term ? { q: term } : {}, page);
    } catch (error) {
      slot.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
      return;
    }
    slot.innerHTML = data.rows.length
      ? `<div class="table-wrap"><table class="table">
          <thead><tr>
            <th>${t("dash.col_title")}</th><th>${t("common.status")}</th><th>${t("common.owner")}</th>
            <th>${t("dash.col_questions")}</th><th class="right">${t("common.actions")}</th>
          </tr></thead>
          <tbody>
            ${data.rows
              .map(
                (row) => `
              <tr>
                <td><a href="/quizzes/${row.id}" data-link>${escapeHtml(row.title)}</a></td>
                <td>
                  <span class="pill ${escapeHtml(row.status)}">${t(`dash.status.${row.status}`)}</span>
                  ${row.pending_version ? `<span class="badge warn">v${row.pending_version}</span>` : ""}
                  ${row.published_version ? `<span class="badge">v${row.published_version}</span>` : ""}
                </td>
                <td class="small-note">${escapeHtml(row.owner_email)}</td>
                <td>${row.question_count}</td>
                <td class="right"><a class="btn btn-sm" href="${row.mode === "adventure" ? `/adventures/${row.id}/edit` : `/quizzes/${row.id}/edit`}" data-link>${t("action.edit")}</a></td>
              </tr>`,
              )
              .join("")}
          </tbody></table></div>`
      : `<div class="empty"><p class="muted">${t("common.no_result")}</p></div>`;

    const pager = panel.querySelector("#admin-pager");
    pager.innerHTML = pagerHtml(page, data.total, PAGE_SIZE);
    bindPager(pager, (next) => quizzesView(panel, term, next));
    bindFilter(panel, "quiz-filter", (value) => quizzesView(panel, value, 0));
  };

  /* ------------------------------------------------------------------ */
  /* Wiki moderation                                                    */
  /* ------------------------------------------------------------------ */
  const wikisView = async (panel, term, page) => {
    panel.innerHTML = `
      <div class="list-head">${filterBar("wiki-filter", term, t("admin.filter_wikis"))}</div>
      <div id="admin-rows" class="mt-2"><p class="muted">…</p></div>
      <div id="admin-pager" class="pager-slot"></div>`;

    const slot = panel.querySelector("#admin-rows");
    let data;
    try {
      data = await page_("/api/v1/admin/wikis", { status: "pending", ...(term ? { q: term } : {}) }, page);
    } catch (error) {
      slot.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
      return;
    }
    slot.innerHTML = data.rows.length
      ? `<div class="table-wrap"><table class="table">
          <thead><tr>
            <th>${t("dash.col_title")}</th><th>${t("common.owner")}</th><th>${t("admin.wiki_pages_count")}</th>
            <th>${t("admin.note")}</th><th class="right">${t("common.actions")}</th>
          </tr></thead>
          <tbody>
            ${data.rows
              .map(
                (row) => `
              <tr data-wiki="${row.id}">
                <td>
                  <a href="/wiki/${row.id}" data-link><strong>${escapeHtml(row.title)}</strong></a>
                  <div class="small-note">${escapeHtml((row.description || "").slice(0, 120))}</div>
                </td>
                <td class="small-note">${escapeHtml(row.owner_name || "—")}<br />${escapeHtml(row.owner_email || "")}</td>
                <td>${row.page_count}</td>
                <td><input class="input" data-note maxlength="300" placeholder="${t("admin.note")}" /></td>
                <td class="right">
                  <div class="row-wrap end">
                    <a class="btn btn-sm btn-ghost" href="/wiki/${row.id}" data-link>${t("action.view")}</a>
                    <button class="btn btn-sm btn-primary" data-act="wiki-approve">${t("action.approve")}</button>
                    <button class="btn btn-sm btn-danger" data-act="wiki-reject">${t("action.reject")}</button>
                  </div>
                </td>
              </tr>`,
              )
              .join("")}
          </tbody></table></div>`
      : `<div class="empty"><p class="muted">${term ? t("common.no_result") : t("admin.wikis_empty")}</p></div>`;

    const pager = panel.querySelector("#admin-pager");
    pager.innerHTML = pagerHtml(page, data.total, PAGE_SIZE);
    bindPager(pager, (next) => wikisView(panel, term, next));
    bindFilter(panel, "wiki-filter", (value) => wikisView(panel, value, 0));
  };

  /* ------------------------------------------------------------------ */
  /* Accounts                                                           */
  /* ------------------------------------------------------------------ */
  const usersView = async (panel, term, page) => {
    panel.innerHTML = `
      <div class="list-head">${filterBar("user-filter", term, t("admin.filter_users"))}</div>
      <div id="admin-rows" class="mt-2"><p class="muted">…</p></div>
      <div id="admin-pager" class="pager-slot"></div>`;

    const slot = panel.querySelector("#admin-rows");
    let data;
    try {
      data = await page_("/api/v1/admin/users", term ? { q: term } : {}, page);
    } catch (error) {
      slot.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
      return;
    }
    slot.innerHTML = data.rows.length
      ? `<div class="table-wrap"><table class="table">
          <thead><tr>
            <th>${t("admin.user")}</th><th>${t("admin.role")}</th><th>${t("admin.quizzes_count")}</th>
            <th>${t("admin.last_login")}</th><th class="right">${t("common.actions")}</th>
          </tr></thead>
          <tbody>
            ${data.rows
              .map(
                (row) => `
              <tr data-user="${row.id}" data-is-admin="${row.is_admin ? 1 : 0}"
                  data-is-moderator="${row.is_moderator ? 1 : 0}"
                  data-is-trusted="${row.is_trusted ? 1 : 0}" data-is-active="${row.is_active ? 1 : 0}">
                <td>
                  <strong>${escapeHtml(row.display_name)}</strong>
                  <div class="small-note">${escapeHtml(row.email)}</div>
                </td>
                <td>
                  ${row.is_admin ? `<span class="pill ai">${t("admin.admin")}</span>` : ""}
                  ${row.is_moderator ? `<span class="pill ai">${t("admin.moderator")}</span>` : ""}
                  ${row.is_trusted ? `<span class="pill public">${t("admin.trusted")}</span>` : ""}
                  ${row.is_active ? "" : `<span class="pill rejected">${t("admin.disable")}</span>`}
                  ${
                    // A blank role cell is ambiguous: say "member" rather than nothing.
                    row.is_admin || row.is_moderator || row.is_trusted || !row.is_active
                      ? ""
                      : `<span class="pill">${escapeHtml(t("admin.member"))}</span>`
                  }
                </td>
                <td>${row.quiz_count}</td>
                <td class="small-note">${row.last_login_at ? new Date(row.last_login_at).toLocaleString() : "—"}</td>
                <td class="right">
                  <div class="row-wrap end">
                    ${
                      // A moderator only vouches for members; roles, suspension
                      // and deletion belong to the administrator.
                      state.user.is_admin
                        ? `<button class="btn btn-sm" data-act="toggle-admin">${row.is_admin ? t("admin.revoke_admin") : t("admin.grant_admin")}</button>
                    <button class="btn btn-sm" data-act="toggle-moderator">${row.is_moderator ? t("admin.revoke_moderator") : t("admin.grant_moderator")}</button>
                    <button class="btn btn-sm" data-act="toggle-trusted">${row.is_trusted ? t("admin.revoke_trusted") : t("admin.grant_trusted")}</button>
                    <button class="btn btn-sm" data-act="toggle-active">${row.is_active ? t("admin.disable") : t("admin.enable")}</button>
                    <button class="btn btn-sm btn-danger" data-act="delete-user">${t("action.delete")}</button>`
                        : row.is_admin || row.is_moderator
                          ? `<span class="small-note">—</span>`
                          : `<button class="btn btn-sm" data-act="toggle-trusted">${row.is_trusted ? t("admin.revoke_trusted") : t("admin.grant_trusted")}</button>`
                    }
                  </div>
                </td>
              </tr>`,
              )
              .join("")}
          </tbody></table></div>`
      : `<div class="empty"><p class="muted">${t("common.no_result")}</p></div>`;

    const pager = panel.querySelector("#admin-pager");
    pager.innerHTML = pagerHtml(page, data.total, PAGE_SIZE);
    bindPager(pager, (next) => usersView(panel, term, next));
    bindFilter(panel, "user-filter", (value) => usersView(panel, value, 0));
  };

  /* ------------------------------------------------------------------ */
  /* AI reviews                                                         */
  /* ------------------------------------------------------------------ */
  const reviewsView = async (panel, term, page) => {
    panel.innerHTML = `
      <div class="list-head">${filterBar("review-filter", term, t("admin.filter_reviews"))}</div>
      <div id="admin-rows" class="mt-2"><p class="muted">…</p></div>
      <div id="admin-pager" class="pager-slot"></div>`;

    const slot = panel.querySelector("#admin-rows");
    let data;
    try {
      data = await page_("/api/v1/admin/reviews", term ? { q: term } : {}, page);
    } catch (error) {
      slot.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
      return;
    }
    slot.innerHTML = data.rows.length
      ? `<div class="table-wrap"><table class="table">
          <thead><tr>
            <th>${t("dash.col_title")}</th><th>${t("admin.kind")}</th><th>${t("common.status")}</th>
            <th>${t("admin.model")}</th><th>${t("common.updated")}</th>
          </tr></thead>
          <tbody>
            ${data.rows
              .map(
                (row) => `
              <tr>
                <td><a href="/quizzes/${row.quiz_id}" data-link>${escapeHtml(row.quiz_title)}</a>
                  <div class="finding">${escapeHtml(row.summary || "")}</div></td>
                <td>${escapeHtml(row.kind)}</td>
                <td><span class="pill ${row.status === "blocked" ? "rejected" : row.status === "corrected" ? "pending" : "public"}">${escapeHtml(row.status)}</span></td>
                <td class="small-note">${escapeHtml(row.model)}</td>
                <td class="small-note">${new Date(row.created_at).toLocaleString()}</td>
              </tr>`,
              )
              .join("")}
          </tbody></table></div>`
      : `<div class="empty"><p class="muted">${term ? t("common.no_result") : t("admin.no_reviews")}</p></div>`;

    const pager = panel.querySelector("#admin-pager");
    pager.innerHTML = pagerHtml(page, data.total, PAGE_SIZE);
    bindPager(pager, (next) => reviewsView(panel, term, next));
    bindFilter(panel, "review-filter", (value) => reviewsView(panel, value, 0));
  };

  /* ------------------------------------------------------------------ */
  /* Audit trail                                                        */
  /* ------------------------------------------------------------------ */
  const eventsView = async (panel, term, page) => {
    panel.innerHTML = `
      <div class="list-head">${filterBar("event-filter", term, t("admin.filter_events"))}</div>
      <div id="admin-rows" class="mt-2"><p class="muted">…</p></div>
      <div id="admin-pager" class="pager-slot"></div>`;

    const slot = panel.querySelector("#admin-rows");
    let data;
    try {
      data = await page_("/api/v1/admin/events", term ? { q: term } : {}, page);
    } catch (error) {
      slot.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
      return;
    }
    slot.innerHTML = data.rows.length
      ? `<div class="table-wrap"><table class="table">
          <thead><tr><th>${t("common.updated")}</th><th>Event</th><th>IP</th><th>${t("admin.user")}</th><th>Detail</th></tr></thead>
          <tbody>
            ${data.rows
              .map(
                (row) => `
              <tr>
                <td class="small-note">${new Date(row.created_at).toLocaleString()}</td>
                <td>${escapeHtml(row.event)}</td>
                <td class="small-note">${escapeHtml(row.ip || "—")}</td>
                <td>${row.user_id ?? "—"}</td>
                <td class="small-note">${escapeHtml(row.detail || "")}</td>
              </tr>`,
              )
              .join("")}
          </tbody></table></div>`
      : `<div class="empty"><p class="muted">${term ? t("common.no_result") : t("admin.no_events")}</p></div>`;

    const pager = panel.querySelector("#admin-pager");
    pager.innerHTML = pagerHtml(page, data.total, PAGE_SIZE);
    bindPager(pager, (next) => eventsView(panel, term, next));
    bindFilter(panel, "event-filter", (value) => eventsView(panel, value, 0));
  };

  /* ------------------------------------------------------------------ */
  /* Actions                                                            */
  /* ------------------------------------------------------------------ */
  root.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-act]");
    if (!button) return;
    const action = button.dataset.act;
    const quizRow = button.closest("[data-quiz]");
    const wikiRow = button.closest("[data-wiki]");
    const userRow = button.closest("[data-user]");

    if (quizRow) {
      const note = quizRow.querySelector("[data-note]")?.value || "";
      button.disabled = true;
      try {
        await api.post(`/api/v1/admin/quizzes/${quizRow.dataset.quiz}/${action}`, { note });
        toast(action === "approve" ? t("admin.approved") : t("admin.rejected"), "success");
        await render();
      } catch (error) {
        button.disabled = false;
        toast(error.detail || t("common.error"), "error");
      }
      return;
    }

    if (wikiRow) {
      const note = wikiRow.querySelector("[data-note]")?.value || "";
      button.disabled = true;
      try {
        const verb = action === "wiki-approve" ? "approve" : "reject";
        await api.post(`/api/v1/admin/wikis/${wikiRow.dataset.wiki}/${verb}`, { note });
        toast(action === "wiki-approve" ? t("admin.approved") : t("admin.rejected"), "success");
        await render();
      } catch (error) {
        button.disabled = false;
        toast(error.detail || t("common.error"), "error");
      }
      return;
    }

    if (userRow) {
      const userId = userRow.dataset.user;
      // The row carries its own flags: reloading a page of accounts to learn
      // what the row already says was a wasted round trip.
      const user = {
        is_admin: userRow.dataset.isAdmin === "1",
        is_moderator: userRow.dataset.isModerator === "1",
        is_trusted: userRow.dataset.isTrusted === "1",
        is_active: userRow.dataset.isActive === "1",
      };
      button.disabled = true;
      try {
        if (action === "toggle-admin") {
          await api.patch(`/api/v1/admin/users/${userId}`, { is_admin: !user.is_admin });
        } else if (action === "toggle-moderator") {
          await api.patch(`/api/v1/admin/users/${userId}`, { is_moderator: !user.is_moderator });
        } else if (action === "toggle-trusted") {
          await api.patch(`/api/v1/admin/users/${userId}`, { is_trusted: !user.is_trusted });
        } else if (action === "toggle-active") {
          await api.patch(`/api/v1/admin/users/${userId}`, { is_active: !user.is_active });
        } else if (action === "delete-user") {
          const confirmed = await confirmDialog(t("action.delete"), t("admin.delete_user_confirm"), t("action.delete"));
          if (!confirmed) {
            button.disabled = false;
            return;
          }
          await api.del(`/api/v1/admin/users/${userId}`);
        }
        toast(t("admin.updated"), "success");
        await render();
      } catch (error) {
        button.disabled = false;
        toast(error.detail || t("common.error"), "error");
      }
    }
  });

  await render();
  return root;
}
