// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Questionnaires: public catalogue and the signed-in author's own list, in two tabs. */

import { api } from "../api.js";
import { flagStrip } from "../flags.js";
import { t, currentLanguage } from "../i18n.js";
import { navigate } from "../router.js";
import { isLoggedIn } from "../store.js";
import { titleSlug } from "../seo.js";
import { escapeHtml, toast } from "../ui.js";

const PAGE_SIZE = 10;

/** One card, shared by both tabs: the owner sees edit actions, visitors see play. */
function _card(quiz, { owned }) {
  const modeLabel =
    quiz.mode === "swipe"
      ? t("editor.mode_swipe")
      : quiz.mode === "adventure"
        ? t("editor.mode_adventure")
        : quiz.mode === "poll"
          ? t("editor.mode_poll")
          : t("editor.mode_qcm");
  return `
      <article class="card quiz-card">
        <div class="row between">
          <span class="pill ${escapeHtml(quiz.status)}">${t(`dash.status.${quiz.status}`)}</span>
          <span class="badge muted">${modeLabel}</span>
        </div>
        <h3 class="mt-2"><a href="/quizzes/${quiz.id}/${titleSlug(quiz.title, "quiz")}" data-link>${escapeHtml(quiz.title)}</a></h3>
        <p class="muted small">${escapeHtml((quiz.description || "").slice(0, 140))}</p>
        <div class="row between mt-2 quiz-card-foot">
          <span class="row quiz-card-langs">${flagStrip(quiz.languages || [], quiz.default_language)}<span class="small-note">${quiz.question_count} ${t("common.questions")}${
            owned ? "" : ` · ${t("home.by")} ${escapeHtml(quiz.owner_name || "—")}`
          }</span></span>
          <div class="row quiz-card-actions">
            ${
              owned
                ? `<a class="btn btn-sm" href="/quizzes/${quiz.id}/edit" data-link>${t("action.edit")}</a>
                   <a class="btn btn-sm btn-primary" href="/quizzes/${quiz.id}/${titleSlug(quiz.title, "quiz")}" data-link>${t("dash.manage")}</a>`
                : `${
                    quiz.mode === "adventure"
                      ? ""
                      : `<button class="btn btn-sm" data-host="${quiz.id}">${t("home.host_live")}</button>`
                  }
                   <button class="btn btn-sm btn-primary" data-play="${quiz.id}" ${
                     quiz.mode === "adventure" ? 'data-story="1"' : ""
                   }>${quiz.mode === "adventure" ? t("home.play_story") : t("home.play_solo")}</button>`
            }
          </div>
        </div>
      </article>`;
}

function _bindPlayActions(container) {
  container.addEventListener("click", (event) => {
    const hostButton = event.target.closest("[data-host]");
    if (hostButton) {
      event.preventDefault();
      const id = hostButton.dataset.host;
      hostButton.disabled = true;
      api
        .post(`/api/v1/quizzes/${id}/sessions`, { mode: "live", language: currentLanguage() })
        .then((result) => {
          const code = result.session.code;
          localStorage.setItem(`ol_ht_${code}`, result.host_token);
          localStorage.setItem(`ol_join_url_${code}`, result.join_url || "");
          navigate(`/host/${code}`);
        })
        .catch((error) => {
          hostButton.disabled = false;
          toast(error.detail || t("common.error"), "error");
        });
      return;
    }
    const button = event.target.closest("[data-play]");
    if (!button) return;
    event.preventDefault();
    const id = button.dataset.play;
    button.disabled = true;
    if (button.dataset.story === "1") {
      navigate(`/adventures/${id}/play`);
      return;
    }
    api
      .post(`/api/v1/quizzes/${id}/sessions`, { mode: "solo", language: currentLanguage() })
      .then((result) => {
        const code = result.session.code;
        localStorage.setItem(`ol_ht_${code}`, result.host_token);
        if (result.participant) {
          localStorage.setItem(`ol_pt_${code}`, result.participant.token);
          localStorage.setItem(`ol_pid_${code}`, String(result.participant.id));
        }
        navigate(`/play/${code}`);
      })
      .catch((error) => {
        button.disabled = false;
        toast(error.detail || t("common.error"), "error");
      });
  });
}

export async function renderHome({ query }) {
  const root = document.createElement("div");
  const search = (query && query.q) || "";
  const tab = query && query.tab === "mine" && isLoggedIn() ? "mine" : "public";
  const requestedPage = Math.max(1, Number((query && query.page) || 1) || 1);
  let page = requestedPage;
  let quizzes = [];
  let total = 0;
  let failed = false;

  const load = async (target) => {
    if (tab === "mine") {
      // The owner's list is small and unpaginated: search is filtered here.
      quizzes = await api.get("/api/v1/quizzes/mine");
      total = quizzes.length;
      return;
    }
    const params = new URLSearchParams();
    if (search) params.set("q", search);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String((target - 1) * PAGE_SIZE));
    const result = await api.getMeta(`/api/v1/quizzes?${params.toString()}`);
    quizzes = result.data || [];
    const headerTotal = Number(result.headers.get("X-Total-Count"));
    // A search that shrinks while the user pages back must not show an empty page.
    if (Number.isFinite(headerTotal)) total = headerTotal;
    else total = quizzes.length;
  };

  try {
    await load(page);
  } catch {
    failed = true;
  }
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (tab === "public" && !failed && page > pageCount) {
    page = pageCount;
    await load(page).catch(() => {
      failed = true;
    });
  }

  const tabHref = (value, extra = "") =>
    value === "public" ? `/quizzes${extra}` : `/quizzes?tab=mine${extra ? `&${extra}` : ""}`;

  root.innerHTML = `
    <section class="hero">
      <div>
        <h1>${t("home.title")}</h1>
        <p class="muted">${t("home.subtitle")}</p>
        <div class="row-wrap mt-2">
          ${isLoggedIn() ? `<a class="btn btn-primary" href="/quizzes/new" data-link>${t("home.create")}</a>` : ""}
          ${
            isLoggedIn()
              ? `<a class="btn" href="/quizzes?tab=mine" data-link>${t("nav.dashboard")}</a>`
              : `<a class="btn btn-primary" href="/register" data-link>${t("nav.signup")}</a>`
          }
        </div>
        <p class="hint mt-2">${t("home.create_hint")}</p>
      </div>
      <div class="card join-box">
        <h2>${t("home.join_title")}</h2>
        <p class="hint">${t("home.join_hint")}</p>
        <form id="pin-form" class="mt-2" novalidate>
          <div class="field">
            <label class="label" for="pin">${t("common.pin")}</label>
            <input class="input pin-input" id="pin" name="pin" maxlength="8" autocomplete="off"
                   placeholder="ABC123" required />
          </div>
          <button class="btn btn-primary btn-block" type="submit">${t("home.join_button")}</button>
        </form>
      </div>
    </section>

    <section class="mt-4">
      <nav class="tabs" role="tablist" aria-label="${t("home.tabs_label")}">
        <a class="tab ${tab === "public" ? "is-active" : ""}" role="tab" aria-selected="${tab === "public"}"
           href="${tabHref("public", search ? `q=${encodeURIComponent(search)}` : "")}" data-link>
          ${t("home.tab_public")}
        </a>
        ${
          isLoggedIn()
            ? `<a class="tab ${tab === "mine" ? "is-active" : ""}" role="tab" aria-selected="${tab === "mine"}"
                 href="${tabHref("mine")}" data-link>${t("home.tab_mine")}
                 <span class="tab-count" id="mine-count"></span></a>`
            : ""
        }
      </nav>

      <div class="row between mt-2">
        <h2>${tab === "mine" ? t("home.my_catalog") : t("home.catalog")}</h2>
        ${
          tab === "mine"
            ? `<div class="search-form" role="search">
                 <input class="input" id="search" name="q" value="${escapeHtml(search)}"
                        placeholder="${t("common.search_placeholder")}" aria-label="${t("home.search_label")}" />
               </div>`
            : `<form id="search-form" class="search-form" role="search">
                 <input class="input" id="search" name="q" value="${escapeHtml(search)}"
                        placeholder="${t("common.search_placeholder")}" aria-label="${t("home.search_label")}" />
                 <button class="btn" type="submit">${t("action.search")}</button>
               </form>`
        }
      </div>
      <div id="catalog" class="grid mt-2"></div>
      <nav id="catalog-pager" class="pager" aria-label="${t("home.pagination_label")}"></nav>
    </section>`;

  const pinForm = root.querySelector("#pin-form");
  pinForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const code = pinForm.querySelector("#pin").value.trim().toUpperCase();
    if (!code) {
      toast(t("play.invalid_code"), "error");
      return;
    }
    navigate(`/play/${encodeURIComponent(code)}`);
  });

  const searchForm = root.querySelector("#search-form");
  if (searchForm) {
    searchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = searchForm.querySelector("#search").value.trim();
      navigate(value ? `/quizzes?q=${encodeURIComponent(value)}` : "/quizzes");
    });
  }

  const catalog = root.querySelector("#catalog");
  const mineCount = root.querySelector("#mine-count");
  if (mineCount && tab === "mine") {
    const mineAll = Number.isFinite(total) ? total : 0;
    mineCount.textContent = mineAll ? String(mineAll) : "";
  }

  const draw = (rows) => {
    if (!rows.length) {
      catalog.innerHTML = `
        <div class="empty">
          <h3>${tab === "mine" ? t("home.mine_empty") : t("home.empty")}</h3>
          <p class="muted">${tab === "mine" ? t("home.mine_empty_hint") : t("home.empty_hint")}</p>
          ${
            tab === "mine"
              ? `<a class="btn btn-primary mt-2" href="/quizzes/new" data-link>${t("home.create")}</a>`
              : ""
          }
        </div>`;
      return;
    }
    catalog.innerHTML = rows.map((quiz) => _card(quiz, { owned: tab === "mine" })).join("");
  };

  const pager = root.querySelector("#catalog-pager");
  const renderPager = () => {
    if (!pager) return;
    if (tab === "mine") {
      pager.innerHTML = total ? `<span class="small-note">${t("home.catalog_count", { n: total })}</span>` : "";
      return;
    }
    if (total <= PAGE_SIZE) {
      pager.innerHTML = total ? `<span class="small-note">${t("home.catalog_count", { n: total })}</span>` : "";
      return;
    }
    const target = (value) => {
      const params = new URLSearchParams();
      if (search) params.set("q", search);
      if (value > 1) params.set("page", String(value));
      const suffix = params.toString();
      return suffix ? `/quizzes?${suffix}` : "/quizzes";
    };
    const numbers = [];
    const first = Math.max(1, Math.min(page - 2, pageCount - 4));
    const last = Math.min(pageCount, first + 4);
    for (let index = first; index <= last; index += 1) numbers.push(index);
    pager.innerHTML = `
      <a class="btn btn-sm btn-ghost ${page === 1 ? "is-disabled" : ""}" ${page === 1 ? 'aria-disabled="true"' : `href="${target(page - 1)}"`} data-link>‹ ${t("home.prev_page")}</a>
      ${numbers
        .map(
          (index) =>
            `<a class="btn btn-sm ${index === page ? "btn-primary" : "btn-ghost"}" href="${target(index)}" data-link${
              index === page ? ' aria-current="page"' : ""
            }>${index}</a>`,
        )
        .join("")}
      <a class="btn btn-sm btn-ghost ${page === pageCount ? "is-disabled" : ""}" ${page === pageCount ? 'aria-disabled="true"' : `href="${target(page + 1)}"`} data-link>${t("home.next_page")} ›</a>
      <span class="small-note">${t("home.catalog_count", { n: total })}</span>`;
  };

  if (failed) {
    catalog.innerHTML = `<div class="banner warn">${t("common.error")}</div>`;
    return root;
  }

  if (tab === "mine") {
    // Local filter on the owner's list, no round trip per keystroke.
    const input = root.querySelector("#search");
    const apply = () => {
      const needle = input.value.trim().toLowerCase();
      const rows = needle
        ? quizzes.filter(
            (quiz) =>
              quiz.title.toLowerCase().includes(needle) ||
              (quiz.description || "").toLowerCase().includes(needle),
          )
        : quizzes;
      draw(rows);
    };
    input.addEventListener("input", apply);
    renderPager();
    draw(quizzes);
    _bindPlayActions(catalog);
    return root;
  }

  renderPager();
  draw(quizzes);
  _bindPlayActions(catalog);
  return root;
}
