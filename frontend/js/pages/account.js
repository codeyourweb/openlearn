// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Account: five sections of its own — profile, my wikis, my questionnaires,
 * my game history and API keys.
 *
 * Every section that can grow holds a list, and every list is searched and
 * paginated server side: an author with two hundred decks of cards should not
 * have to scroll through all of them to find one.
 */

import { api } from "../api.js";
import { flagSvg } from "../flags.js";
import { currentLanguage, LANGUAGES, setLanguage, t, tp } from "../i18n.js";
import { navigate } from "../router.js";
import { isLoggedIn, state } from "../store.js";
import { applyTheme, currentTheme } from "../theme.js";
import { bindPager, confirmDialog, escapeHtml, formatDate, pagerHtml, toast } from "../ui.js";

const MODE_KEY = {
  qcm: "editor.mode_qcm",
  swipe: "editor.mode_swipe",
  adventure: "editor.mode_adventure",
  poll: "editor.mode_poll",
};

const TABS = ["profile", "wikis", "quizzes", "history", "keys"];
const PAGE_SIZE = 10;

function keyRow(key) {
  return `
    <tr>
      <td>${escapeHtml(key.name)}</td>
      <td><code>${escapeHtml(key.prefix)}…</code></td>
      <td class="muted">${formatDate(key.created_at)}</td>
      <td class="muted">${key.last_used_at ? formatDate(key.last_used_at) : t("common.none")}</td>
      <td>${
        key.revoked_at
          ? `<span class="badge danger">${t("account.api_revoke")}</span>`
          : `<button class="btn btn-sm btn-danger" data-revoke="${key.id}">${t("account.api_revoke")}</button>`
      }</td>
    </tr>`;
}

/** A search field shared by every list: one keystroke per 250 ms, then reload. */
function searchBar(id, value, placeholder) {
  return `
    <form class="search-form" role="search" id="${id}-form">
      <input class="input" id="${id}" name="q" type="search" value="${escapeHtml(value)}"
             placeholder="${escapeHtml(placeholder)}" aria-label="${escapeHtml(placeholder)}" />
      <button class="btn" type="submit">${t("action.search")}</button>
    </form>`;
}

function bindSearch(root, id, onSearch) {
  const input = root.querySelector(`#${id}`);
  const form = root.querySelector(`#${id}-form`);
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

export async function renderAccount({ query } = {}) {
  if (!isLoggedIn()) {
    navigate("/login?next=%2Faccount", { replace: true });
    return document.createElement("div");
  }
  const requested = (query && query.tab) || "profile";
  const tab = TABS.includes(requested) ? requested : "profile";

  const root = document.createElement("div");
  root.innerHTML = `
    <h1>${t("account.title")}</h1>
    <p class="muted">${escapeHtml(state.user.email)}</p>
    <nav class="tabs mt-2" role="tablist" aria-label="${escapeHtml(t("account.title"))}">
      ${TABS.map(
        (name) => `<button class="tab ${name === tab ? "is-active" : ""}" role="tab"
                    aria-selected="${name === tab}" data-section="${name}">${t(`account.tab_${name}`)}</button>`,
      ).join("")}
    </nav>
    <div id="account-panel"></div>`;

  root.querySelectorAll("[data-section]").forEach((button) => {
    button.addEventListener("click", () => {
      navigate(`/account?tab=${button.dataset.section}`, { replace: false });
    });
  });

  const panel = root.querySelector("#account-panel");
  if (tab === "profile") panel.innerHTML = _profileHtml();
  else if (tab === "keys") await _paintKeys(panel);
  else if (tab === "wikis") await _paintWikis(panel);
  else if (tab === "quizzes") await _paintQuizzes(panel);
  else await _paintHistory(panel);

  if (tab === "profile") _bindProfile(root);
  return root;
}

/* -------------------------------------------------------------------------- */
/* Profile                                                                    */
/* -------------------------------------------------------------------------- */

function _profileHtml() {
  return `
    <div class="grid mt-2">
      <section class="card">
        <h2>${t("account.profile")}</h2>
        <p class="muted small">${t("common.email")}</p>
        <p>${escapeHtml(state.user.email)}</p>
        <p class="muted small">${t("common.display_name")}</p>
        <p>${escapeHtml(state.user.display_name)}</p>
        <p class="muted small">${t("common.created")}</p>
        <p>${formatDate(state.user.created_at)}</p>
        ${state.user.is_admin ? `<p><span class="pill ai">${t("admin.admin")}</span></p>` : ""}
        <div class="row-wrap mt-2">
          <a class="btn btn-sm" href="/quizzes?tab=mine" data-link>${t("nav.dashboard")}</a>
          ${state.user.is_admin ? `<a class="btn btn-sm" href="/admin" data-link>${t("nav.admin")}</a>` : ""}
        </div>
      </section>

      <section class="card">
        <h2>${t("account.password_title")}</h2>
        <form id="password-form" novalidate>
          <div class="form-error" hidden></div>
          <div class="field">
            <label class="label" for="current">${t("account.current_password")}</label>
            <input class="input" type="password" id="current" name="current" autocomplete="current-password" required />
          </div>
          <div class="field">
            <label class="label" for="next">${t("account.new_password")}</label>
            <input class="input" type="password" id="next" name="next" autocomplete="new-password" required minlength="8" />
            <span class="hint">${t("auth.password_hint")}</span>
          </div>
          <button class="btn" type="submit">${t("account.change_password")}</button>
        </form>
      </section>

      <section class="card">
        <h2>${t("common.language")} & ${t("common.theme")}</h2>
        <div class="field">
          <span class="label">${t("common.language")}</span>
          <div class="flag-grid" id="account-language" role="group" aria-label="${t("common.language")}">
            ${LANGUAGES.map(
              (language) => `
              <button type="button" class="flag-choice" data-language="${language.code}"
                      aria-pressed="${language.code === currentLanguage()}">
                ${flagSvg(language.code)}<span>${escapeHtml(language.label)}</span>
              </button>`,
            ).join("")}
          </div>
        </div>
        <div class="field">
          <label class="label" for="account-theme">${t("common.theme")}</label>
          <select class="input" id="account-theme">
            <option value="dark" ${currentTheme() === "dark" ? "selected" : ""}>${t("common.theme_dark")}</option>
            <option value="light" ${currentTheme() === "light" ? "selected" : ""}>${t("common.theme_light")}</option>
          </select>
        </div>
      </section>
    </div>`;
}

function _bindProfile(root) {
  root.querySelector("#account-language").addEventListener("click", (event) => {
    const choice = event.target.closest("[data-language]");
    if (!choice) return;
    setLanguage(choice.dataset.language);
    root.querySelectorAll("#account-language [data-language]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button === choice));
    });
  });
  root.querySelector("#account-theme").addEventListener("change", (event) => {
    applyTheme(event.target.value);
  });

  root.querySelector("#password-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const errorBox = form.querySelector(".form-error");
    errorBox.hidden = true;
    try {
      await api.post("/api/v1/me/password", {
        current_password: form.querySelector("#current").value,
        new_password: form.querySelector("#next").value,
      });
      form.reset();
      toast(t("account.password_changed"), "success");
    } catch (error) {
      errorBox.textContent = error.detail || t("error.generic");
      errorBox.hidden = false;
    }
  });
}

/* -------------------------------------------------------------------------- */
/* My wikis                                                                   */
/* -------------------------------------------------------------------------- */

async function _paintWikis(panel, term = "", page = 0) {
  panel.innerHTML = `
    <div class="list-head">
      ${searchBar("wiki-search", term, t("account.search_wikis"))}
      <a class="btn btn-primary" href="/wiki/new" data-link>${t("wiki.new")}</a>
    </div>
    <div id="wiki-rows" class="wiki-grid mt-2"><p class="muted">…</p></div>
    <div id="wiki-pager" class="pager-slot"></div>`;

  const rows = panel.querySelector("#wiki-rows");
  const params = new URLSearchParams({ mine: "true", limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE) });
  if (term) params.set("q", term);

  let wikis = [];
  let total = 0;
  try {
    const meta = await api.getMeta(`/api/v1/wiki?${params.toString()}`);
    wikis = meta.data || [];
    total = Number(meta.headers.get("X-Total-Count") || wikis.length);
  } catch (error) {
    rows.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
    return;
  }

  rows.innerHTML = wikis.length
    ? wikis
        .map(
          (wiki) => `
        <a class="wiki-card card" data-link href="/wiki/${wiki.id}">
          <div class="row between">
            <strong>${escapeHtml(wiki.title)}</strong>
            <span class="pill ${escapeHtml(wiki.status)}">${t(`wiki.status.${wiki.status}`)}</span>
          </div>
          <p class="muted small">${escapeHtml(wiki.description || t("wiki.no_description"))}</p>
          <p class="small-note">${tp("wiki.page_one", "wiki.page_many", wiki.page_count)} · ${escapeHtml(
            formatDate(wiki.updated_at),
          )}${wiki.role && wiki.role !== "owner" ? ` · ${escapeHtml(t(`wiki.role.${wiki.role}`))}` : ""}</p>
        </a>`,
        )
        .join("")
    : `<div class="empty"><p class="muted">${term ? t("common.no_result") : t("account.wikis_empty")}</p></div>`;

  const pager = panel.querySelector("#wiki-pager");
  pager.innerHTML = pagerHtml(page, total, PAGE_SIZE);
  bindPager(pager, (next) => _paintWikis(panel, term, next));
  bindSearch(panel, "wiki-search", (value) => _paintWikis(panel, value, 0));
}

/* -------------------------------------------------------------------------- */
/* My questionnaires                                                          */
/* -------------------------------------------------------------------------- */

async function _paintQuizzes(panel, term = "", page = 0) {
  panel.innerHTML = `
    <div class="list-head">
      ${searchBar("quiz-search", term, t("account.search_quizzes"))}
      <a class="btn btn-primary" href="/quizzes/new" data-link>${t("home.create")}</a>
    </div>
    <div id="quiz-rows" class="wiki-grid mt-2"><p class="muted">…</p></div>
    <div id="quiz-pager" class="pager-slot"></div>`;

  const rows = panel.querySelector("#quiz-rows");
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE) });
  if (term) params.set("q", term);

  let quizzes = [];
  let total = 0;
  try {
    const meta = await api.getMeta(`/api/v1/quizzes/mine?${params.toString()}`);
    quizzes = meta.data || [];
    total = Number(meta.headers.get("X-Total-Count") || quizzes.length);
  } catch (error) {
    rows.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
    return;
  }

  rows.innerHTML = quizzes.length
    ? quizzes
        .map(
          (quiz) => `
        <a class="wiki-card card" data-link href="/quizzes/${quiz.id}">
          <div class="row between">
            <strong>${escapeHtml(quiz.title)}</strong>
            <span class="pill ${escapeHtml(quiz.status)}">${t(`dash.status.${quiz.status}`)}</span>
          </div>
          <p class="muted small">${escapeHtml((quiz.description || "").slice(0, 140))}</p>
          <p class="small-note">${t(MODE_KEY[quiz.mode] || MODE_KEY.qcm)} · ${quiz.question_count} ${t(
            "common.questions",
          )} · ${escapeHtml(formatDate(quiz.updated_at))}</p>
        </a>`,
        )
        .join("")
    : `<div class="empty"><p class="muted">${term ? t("common.no_result") : t("home.mine_empty")}</p></div>`;

  const pager = panel.querySelector("#quiz-pager");
  pager.innerHTML = pagerHtml(page, total, PAGE_SIZE);
  bindPager(pager, (next) => _paintQuizzes(panel, term, next));
  bindSearch(panel, "quiz-search", (value) => _paintQuizzes(panel, value, 0));
}

/* -------------------------------------------------------------------------- */
/* Game history                                                               */
/* -------------------------------------------------------------------------- */

async function _paintHistory(panel, term = "", page = 0) {
  panel.innerHTML = `
    <div class="list-head">
      ${searchBar("history-search", term, t("account.search_history"))}
    </div>
    <div id="history-rows" class="mt-2"><p class="muted">…</p></div>
    <div id="history-pager" class="pager-slot"></div>`;

  const slot = panel.querySelector("#history-rows");
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE) });
  if (term) params.set("q", term);

  let rows = [];
  let total = 0;
  try {
    const meta = await api.getMeta(`/api/v1/me/history?${params.toString()}`);
    rows = meta.data || [];
    total = Number(meta.headers.get("X-Total-Count") || rows.length);
  } catch (error) {
    slot.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
    return;
  }

  const rowHtml = (row) => `
    <a class="history-row" href="/results/${escapeHtml(row.code)}" data-link>
      <span class="history-mode badge ${row.quiz_mode === "adventure" ? "ai" : "muted"}">${t(
        MODE_KEY[row.quiz_mode] || MODE_KEY.qcm,
      )}</span>
      <span class="history-title">
        <strong>${escapeHtml(row.quiz_title)}</strong>
        <span class="small-note">${formatDate(row.finished_at || row.created_at)} · ${
          row.is_solo ? t("account.solo") : t("account.live")
        } · ${tp("account.player_one", "account.player_many", row.participant_count)}</span>
      </span>
      <span class="history-score">
        ${
          row.best_score === null || row.best_score === undefined
            ? `<span class="muted small">—</span>`
            : `<strong>${row.best_score}</strong> ${t("common.points")}`
        }
        ${row.rank ? `<span class="badge muted">#${row.rank}</span>` : ""}
      </span>
      <span class="pill ${escapeHtml(row.status)}">${t(`session.status.${row.status}`)}</span>
    </a>`;

  slot.innerHTML = rows.length
    ? `<div class="history-list">${rows.map(rowHtml).join("")}</div>`
    : `<div class="empty"><p class="muted">${term ? t("common.no_result") : t("account.history_empty")}</p></div>`;

  const pager = panel.querySelector("#history-pager");
  pager.innerHTML = pagerHtml(page, total, PAGE_SIZE);
  bindPager(pager, (next) => _paintHistory(panel, term, next));
  bindSearch(panel, "history-search", (value) => _paintHistory(panel, value, 0));
}

/* -------------------------------------------------------------------------- */
/* API keys                                                                   */
/* -------------------------------------------------------------------------- */

async function _paintKeys(panel) {
  let keys = [];
  try {
    keys = await api.get("/api/v1/me/api-keys");
  } catch (error) {
    panel.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
    return;
  }

  panel.innerHTML = `
    <section class="card mt-2">
      <div class="card-head">
        <div>
          <h2>${t("account.api_title")}</h2>
          <p class="muted small">${t("account.api_hint")}</p>
        </div>
      </div>
      <form id="key-form" class="row">
        <input class="input" id="key-name" maxlength="60" placeholder="${t("account.api_name")}" />
        <button class="btn btn-primary" type="submit">${t("account.api_create")}</button>
      </form>
      <div id="new-key"></div>
      <div class="table-wrap mt-2">
        <table class="table">
          <thead><tr><th>${t("account.api_name")}</th><th>Prefix</th><th>${t("common.created")}</th><th>${t(
            "common.updated",
          )}</th><th></th></tr></thead>
          <tbody>
            ${keys.length ? keys.map(keyRow).join("") : `<tr><td colspan="5" class="muted">${t("account.api_none")}</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>`;

  panel.querySelector("#key-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = panel.querySelector("#key-name");
    const name = input.value.trim();
    if (name.length < 2) {
      toast(t("account.api_name"), "error");
      return;
    }
    try {
      const created = await api.post("/api/v1/me/api-keys", { name });
      input.value = "";
      const box = panel.querySelector("#new-key");
      box.innerHTML = `
        <div class="banner ok mt-2">
          <strong>${t("account.api_created")}</strong>
          <div class="join-url mt-1">
            <input class="input" id="fresh-key" readonly value="${escapeHtml(created.key)}" />
            <button class="btn btn-sm" id="copy-key" type="button">${t("action.copy")}</button>
          </div>
        </div>`;
      box.querySelector("#copy-key").addEventListener("click", async () => {
        const field = box.querySelector("#fresh-key");
        try {
          await navigator.clipboard.writeText(field.value);
          toast(t("common.copied"), "success");
        } catch {
          field.select();
        }
      });
      const refreshed = await api.get("/api/v1/me/api-keys");
      panel.querySelector("tbody").innerHTML = refreshed.map(keyRow).join("");
    } catch (error) {
      toast(error.detail || t("error.generic"), "error");
    }
  });

  panel.querySelector("tbody").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-revoke]");
    if (!button) return;
    const ok = await confirmDialog(t("account.api_revoke"), t("account.api_hint"), t("account.api_revoke"));
    if (!ok) return;
    try {
      await api.del(`/api/v1/me/api-keys/${button.dataset.revoke}`);
      toast(t("account.api_revoked"), "success");
      await _paintKeys(panel);
    } catch (error) {
      toast(error.detail || t("error.generic"), "error");
    }
  });
}
