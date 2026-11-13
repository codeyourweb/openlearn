// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Administration, grouped by what an operator is actually doing.
 *
 * Four rubrics, each with its own sub-tabs: **content** (accounts, quizzes,
 * wikis — look, edit, delete), **moderation** (what waits for a decision, shared
 * with moderators), **AI** (reviews, provider, error log) and **settings**
 * (instance, mail, sign-in, legal, audit trail, syslog, HTTP POST, environment).
 * The old flat tab names still resolve, so a bookmark keeps working.
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
import { aiLogView, environmentView, logTargetsView, settingsView, ssoView } from "./adminSettings.js";
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

/** One rubric: a heading, the shared filter, the rows and the pager. */
function rubric(panel, { id, term, placeholder, render }) {
  panel.innerHTML = `
    <div class="list-head">${filterBar(`${id}-filter`, term, placeholder)}</div>
    <div id="admin-rows" class="mt-2"><p class="muted">…</p></div>
    <div id="admin-pager" class="pager-slot"></div>`;
  return panel.querySelector("#admin-rows");
}

function paintPager(panel, page, total, again) {
  const pager = panel.querySelector("#admin-pager");
  if (!pager) return;
  pager.innerHTML = pagerHtml(page, total, PAGE_SIZE);
  bindPager(pager, (next) => again(next));
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

  /* ---------------------------------------------------------------- */
  /* Rubrics                                                          */
  /* ---------------------------------------------------------------- */
  const GROUPS = [
    {
      id: "content",
      label: "admin.group_content",
      tabs: [
        { id: "users", label: "admin.tab_users", view: usersView },
        { id: "quizzes", label: "admin.tab_quizzes", view: quizzesView },
        { id: "wikis", label: "admin.tab_wikis", view: wikisView },
      ],
    },
    {
      id: "moderation",
      label: "admin.group_moderation",
      tabs: [
        { id: "quizzes", label: "admin.tab_quiz_queue", view: queueView },
        { id: "wikis", label: "admin.tab_wiki_queue", view: wikiQueueView },
      ],
    },
    {
      id: "ai",
      label: "admin.group_ai",
      admin: true,
      tabs: [
        { id: "reviews", label: "admin.tab_reviews", view: reviewsView },
        { id: "provider", label: "admin.tab_ai_provider", view: sectionView("ai") },
        { id: "errors", label: "admin.tab_ai_log", view: aiLogView },
      ],
    },
    {
      id: "settings",
      label: "admin.group_settings",
      admin: true,
      tabs: [
        { id: "instance", label: "admin.tab_instance", view: sectionView("instance", "sharing") },
        { id: "mail", label: "admin.tab_mail", view: sectionView("mail") },
        { id: "security", label: "admin.tab_security", view: sectionView("security") },
        { id: "sso", label: "admin.tab_sso", view: ssoView },
        { id: "legal", label: "admin.tab_legal", view: legalEditorView },
        { id: "audit", label: "admin.tab_events", view: eventsView },
        { id: "syslog", label: "admin.tab_syslog", view: logTargetsView("syslog") },
        { id: "http", label: "admin.tab_http", view: logTargetsView("http") },
        { id: "environment", label: "admin.tab_environment", view: environmentView },
      ],
    },
  ];

  // A link written before the reorganisation names a rubric, not a pair: read it
  // as its natural home instead of dropping the person on the first tab.
  const LEGACY = {
    queue: "moderation.quizzes",
    quizzes: "content.quizzes",
    wikis: "moderation.wikis",
    wikis_all: "content.wikis",
    users: "content.users",
    reviews: "ai.reviews",
    settings: "settings.instance",
    sso: "settings.sso",
    ailog: "ai.errors",
    legal: "settings.legal",
    events: "settings.audit",
  };

  const visibleGroups = () => GROUPS.filter((group) => !group.admin || state.user.is_admin);

  const resolve = (wanted) => {
    const groups = visibleGroups();
    const name = LEGACY[wanted] || wanted || "moderation.quizzes";
    const [group, tab = ""] = String(name).split(".");
    const found = groups.find((row) => row.id === group) || groups[0];
    const chosen = found.tabs.find((row) => row.id === tab) || found.tabs[0];
    return { group: found, tab: chosen };
  };

  let current = resolve((query && query.tab) || "");

  const go = (group, tab) => {
    current = { group, tab };
    navigate(`/admin?tab=${group.id}.${tab.id}`, { replace: true });
    void render();
  };

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
    const pendingWikis = (stats.wikis || {}).pending || 0;

    const badge = (count) => (count ? `<span class="tab-count">${count}</span>` : "");

    root.innerHTML = `
      <div class="row between">
        <div>
          <h1>${t("admin.title")}</h1>
          <p class="muted">${t("admin.subtitle")}</p>
        </div>
      </div>
      <div class="grid grid-4 mt-2">
        <div class="card"><div class="muted small">${t("admin.stats_total")}</div><div class="pin-display sm">${stats.quizzes.total}</div></div>
        <div class="card"><div class="muted small">${t("admin.stats_pending")}</div><div class="pin-display sm">${pendingCount + pendingWikis}</div></div>
        <div class="card"><div class="muted small">${t("admin.stats_users")}</div><div class="pin-display sm">${stats.users.total}</div></div>
        <div class="card"><div class="muted small">${t("admin.stats_blocked")}</div><div class="pin-display sm">${stats.reviews.blocked}</div></div>
      </div>
      <div class="tabs tabs-groups mt-3" role="tablist">
        ${visibleGroups()
          .map(
            (group) => `
          <button class="tab tab-group ${group.id === current.group.id ? "is-active" : ""}"
                  role="tab" aria-selected="${group.id === current.group.id}"
                  data-group="${group.id}">${t(group.label)}</button>`,
          )
          .join("")}
      </div>
      <div class="tabs tabs-sub" role="tablist" data-group-tabs="${current.group.id}">
        ${current.group.tabs
          .map(
            (row) => `
          <button class="tab ${row.id === current.tab.id ? "is-active" : ""}" role="tab"
                  aria-selected="${row.id === current.tab.id}" data-tab="${row.id}">
            ${t(row.label)}${row.id === "quizzes" && current.group.id === "moderation" ? badge(pendingCount) : ""}${
              row.id === "wikis" && current.group.id === "moderation" ? badge(pendingWikis) : ""
            }
          </button>`,
          )
          .join("")}
      </div>
      <div id="tab-panel"></div>`;

    root.querySelectorAll("[data-group]").forEach((button) => {
      button.addEventListener("click", () => {
        const group = visibleGroups().find((row) => row.id === button.dataset.group);
        if (group) go(group, group.tabs[0]);
      });
    });
    root.querySelectorAll("[data-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        const tab = current.group.tabs.find((row) => row.id === button.dataset.tab);
        if (tab) go(current.group, tab);
      });
    });

    const panel = root.querySelector("#tab-panel");
    await current.tab.view(panel, "", 0);
  };

  /* ------------------------------------------------------------------ */
  /* Moderation: the questionnaire queue                                */
  /* ------------------------------------------------------------------ */
  async function queueView(panel, term, page) {
    const slot = rubric(panel, {
      id: "queue",
      term,
      placeholder: t("admin.filter_quizzes"),
    });
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

    paintPager(panel, page, data.total, (next) => queueView(panel, term, next));
    bindFilter(panel, "queue-filter", (value) => queueView(panel, value, 0));
  };

  /* ------------------------------------------------------------------ */
  /* Moderation: the wiki queue                                         */
  /* ------------------------------------------------------------------ */
  async function wikiQueueView(panel, term, page) {
    const slot = rubric(panel, { id: "wikiq", term, placeholder: t("admin.filter_wikis") });
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
                <td class="small-note">${escapeHtml((row.owner && row.owner.display_name) || "—")}<br />${escapeHtml((row.owner && row.owner.email) || "")}</td>
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

    paintPager(panel, page, data.total, (next) => wikiQueueView(panel, term, next));
    bindFilter(panel, "wikiq-filter", (value) => wikiQueueView(panel, value, 0));
  };

  /* ------------------------------------------------------------------ */
  /* Content: every questionnaire, with the three actions               */
  /* ------------------------------------------------------------------ */
  async function quizzesView(panel, term, page) {
    const slot = rubric(panel, { id: "quiz", term, placeholder: t("admin.filter_quizzes") });
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
              <tr data-row-quiz="${row.id}">
                <td><a href="/quizzes/${row.id}" data-link>${escapeHtml(row.title)}</a></td>
                <td>
                  <span class="pill ${escapeHtml(row.status)}">${t(`dash.status.${row.status}`)}</span>
                  ${row.pending_version ? `<span class="badge warn">v${row.pending_version}</span>` : ""}
                  ${row.published_version ? `<span class="badge">v${row.published_version}</span>` : ""}
                </td>
                <td class="small-note">${escapeHtml(row.owner_email)}</td>
                <td>${row.question_count}</td>
                <td class="right">
                  <div class="row-wrap end">
                    <a class="btn btn-sm btn-ghost" href="/quizzes/${row.id}" data-link>${t("action.view")}</a>
                    <a class="btn btn-sm" href="${row.mode === "adventure" ? `/adventures/${row.id}/edit` : `/quizzes/${row.id}/edit`}" data-link>${t("action.edit")}</a>
                    <button class="btn btn-sm btn-danger" data-act="delete-quiz">${t("action.delete")}</button>
                  </div>
                </td>
              </tr>`,
              )
              .join("")}
          </tbody></table></div>`
      : `<div class="empty"><p class="muted">${t("common.no_result")}</p></div>`;

    paintPager(panel, page, data.total, (next) => quizzesView(panel, term, next));
    bindFilter(panel, "quiz-filter", (value) => quizzesView(panel, value, 0));
  };

  /* ------------------------------------------------------------------ */
  /* Content: every wiki, with the three actions                        */
  /* ------------------------------------------------------------------ */
  async function wikisView(panel, term, page) {
    const slot = rubric(panel, { id: "wiki", term, placeholder: t("admin.filter_wikis") });
    let data;
    try {
      data = await page_("/api/v1/admin/wikis", term ? { q: term } : {}, page);
    } catch (error) {
      slot.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
      return;
    }
    slot.innerHTML = data.rows.length
      ? `<div class="table-wrap"><table class="table">
          <thead><tr>
            <th>${t("dash.col_title")}</th><th>${t("common.status")}</th><th>${t("common.owner")}</th>
            <th>${t("admin.wiki_pages_count")}</th><th class="right">${t("common.actions")}</th>
          </tr></thead>
          <tbody>
            ${data.rows
              .map(
                (row) => `
              <tr data-row-wiki="${row.id}">
                <td><a href="/wiki/${row.id}" data-link>${escapeHtml(row.title)}</a></td>
                <td>
                  <span class="pill ${escapeHtml(row.status)}">${t(`dash.status.${row.status}`) || escapeHtml(row.status)}</span>
                  ${row.is_public ? `<span class="pill public">${t("admin.public")}</span>` : ""}
                </td>
                <td class="small-note">${escapeHtml((row.owner && row.owner.email) || "—")}</td>
                <td>${row.page_count}</td>
                <td class="right">
                  <div class="row-wrap end">
                    <a class="btn btn-sm btn-ghost" href="/wiki/${row.id}" data-link>${t("action.view")}</a>
                    <a class="btn btn-sm" href="/wiki/${row.id}/edit" data-link>${t("action.edit")}</a>
                    <button class="btn btn-sm btn-danger" data-act="delete-wiki">${t("action.delete")}</button>
                  </div>
                </td>
              </tr>`,
              )
              .join("")}
          </tbody></table></div>`
      : `<div class="empty"><p class="muted">${t("common.no_result")}</p></div>`;

    paintPager(panel, page, data.total, (next) => wikisView(panel, term, next));
    bindFilter(panel, "wiki-filter", (value) => wikisView(panel, value, 0));
  };

  /* ------------------------------------------------------------------ */
  /* Content: accounts                                                  */
  /* ------------------------------------------------------------------ */
  async function usersView(panel, term, page) {
    const slot = rubric(panel, { id: "user", term, placeholder: t("admin.filter_users") });
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

    paintPager(panel, page, data.total, (next) => usersView(panel, term, next));
    bindFilter(panel, "user-filter", (value) => usersView(panel, value, 0));
  };

  /* ------------------------------------------------------------------ */
  /* AI: what the model said about published content                    */
  /* ------------------------------------------------------------------ */
  async function reviewsView(panel, term, page) {
    const slot = rubric(panel, { id: "review", term, placeholder: t("admin.filter_reviews") });
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

    paintPager(panel, page, data.total, (next) => reviewsView(panel, term, next));
    bindFilter(panel, "review-filter", (value) => reviewsView(panel, value, 0));
  };

  /* ------------------------------------------------------------------ */
  /* Settings: the local audit trail                                    */
  /* ------------------------------------------------------------------ */
  async function eventsView(panel, term, page) {
    const slot = rubric(panel, { id: "event", term, placeholder: t("admin.filter_events") });
    let data;
    try {
      data = await page_("/api/v1/admin/events", term ? { q: term } : {}, page);
    } catch (error) {
      slot.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
      return;
    }
    slot.innerHTML = data.rows.length
      ? `<div class="table-wrap"><table class="table">
          <thead><tr><th>${t("common.updated")}</th><th>${t("admin.event")}</th><th>${t("admin.ip")}</th><th>${t("admin.user")}</th><th>${t("admin.detail")}</th></tr></thead>
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

    paintPager(panel, page, data.total, (next) => eventsView(panel, term, next));
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
    const contentQuiz = button.closest("[data-row-quiz]");
    const contentWiki = button.closest("[data-row-wiki]");
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

    if (contentQuiz && action === "delete-quiz") {
      const agreed = await confirmDialog(
        t("action.delete"),
        t("admin.delete_quiz_confirm"),
        t("action.delete"),
      );
      if (!agreed) return;
      button.disabled = true;
      try {
        await api.del(`/api/v1/admin/quizzes/${contentQuiz.dataset.rowQuiz}`);
        toast(t("admin.deleted"), "success");
        await render();
      } catch (error) {
        button.disabled = false;
        toast(error.detail || t("common.error"), "error");
      }
      return;
    }

    if (contentWiki && action === "delete-wiki") {
      const agreed = await confirmDialog(
        t("action.delete"),
        t("admin.delete_wiki_confirm"),
        t("action.delete"),
      );
      if (!agreed) return;
      button.disabled = true;
      try {
        await api.del(`/api/v1/admin/wikis/${contentWiki.dataset.rowWiki}`);
        toast(t("admin.deleted"), "success");
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

/** Settings cards, addressed by their sections. */
function sectionView(...sections) {
  return (panel) => settingsView(panel, sections);
}
