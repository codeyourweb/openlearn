// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Author dashboard: every quiz with its publication status and actions. */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { navigate } from "../router.js";
import { isLoggedIn } from "../store.js";
import { confirmDialog, escapeHtml, toast } from "../ui.js";

export async function renderDashboard() {
  if (!isLoggedIn()) {
    navigate("/login?next=%2Fdashboard", { replace: true });
    return document.createElement("div");
  }
  const root = document.createElement("div");
  root.innerHTML = `<div class="loading">${t("common.loading")}</div>`;

  let quizzes;
  try {
    quizzes = await api.get("/api/v1/quizzes/mine");
  } catch (error) {
    root.innerHTML = `<div class="banner warn">${escapeHtml(error.detail || t("common.error"))}</div>`;
    return root;
  }

  const pending = quizzes.filter((quiz) => quiz.status === "pending").length;

  root.innerHTML = `
    <div class="row between">
      <div>
        <h1>${t("dash.title")}</h1>
        <p class="muted">${t("dash.subtitle")}</p>
      </div>
      <div class="row">
        <a class="btn btn-primary" href="/quizzes/new" data-link>${t("dash.new")}</a>
        <a class="btn" href="/adventures/new" data-link>${t("dash.new_story")}</a>
      </div>
    </div>
    ${pending ? `<div class="banner info mt-2">${pending} × ${t("dash.status.pending")}</div>` : ""}
    <div id="list" class="mt-3"></div>`;

  const list = root.querySelector("#list");
  if (!quizzes.length) {
    list.innerHTML = `
      <div class="empty">
        <h3>${t("dash.empty")}</h3>
        <p class="muted">${t("dash.empty_hint")}</p>
        <a class="btn btn-primary mt-2" href="/quizzes/new" data-link>${t("dash.new")}</a>
      </div>`;
    return root;
  }

  list.innerHTML = `
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>${t("dash.col_title")}</th>
            <th>${t("dash.col_status")}</th>
            <th>${t("dash.col_questions")}</th>
            <th>${t("dash.col_updated")}</th>
            <th class="right">${t("dash.col_actions")}</th>
          </tr>
        </thead>
        <tbody>
          ${quizzes
            .map(
              (quiz) => `
            <tr data-quiz="${quiz.id}">
              <td>
                <a href="/quizzes/${quiz.id}" data-link><strong>${escapeHtml(quiz.title)}</strong></a>
                ${quiz.ai_generated ? `<span class="pill ai">${t("quiz.ai_generated")}</span>` : ""}
                <div class="small-note">${escapeHtml((quiz.description || "").slice(0, 90))}</div>
              </td>
              <td><span class="pill ${escapeHtml(quiz.status)}">${t(`dash.status.${quiz.status}`)}</span></td>
              <td>${quiz.question_count}</td>
              <td class="small-note">${new Date(quiz.updated_at).toLocaleDateString()}</td>
              <td class="right">
                <div class="row-wrap end">
                  <a class="btn btn-sm btn-icon" href="/quizzes/${quiz.id}" data-link
                     title="${t("action.view")}" aria-label="${t("action.view")}"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg></a>
                  <button class="btn btn-sm btn-icon" data-act="edit"
                          title="${t("action.edit")}" aria-label="${t("action.edit")}"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg></button>
                  <button class="btn btn-sm btn-icon btn-primary" data-act="host" ${quiz.question_count ? "" : "disabled"}
                          title="${t("dash.host")}" aria-label="${t("dash.host")}"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 4l14 8-14 8z"/></svg></button>
                  <button class="btn btn-sm btn-icon btn-ghost" data-act="duplicate"
                          title="${t("action.duplicate")}" aria-label="${t("action.duplicate")}"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg></button>
                  <button class="btn btn-sm btn-icon btn-danger" data-act="delete"
                          title="${t("action.delete")}" aria-label="${t("action.delete")}"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/><path d="M10 11v5M14 11v5"/></svg></button>
                </div>
              </td>
            </tr>`,
            )
            .join("")}
        </tbody>
      </table>
    </div>`;

  list.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-act]");
    if (!button) return;
    const row = button.closest("[data-quiz]");
    const quizId = row.dataset.quiz;
    const quiz = quizzes.find((item) => String(item.id) === quizId);
    if (!quiz) return;

    if (button.dataset.act === "edit") {
      navigate(`/quizzes/${quizId}/edit`);
      return;
    }
    if (button.dataset.act === "host") {
      button.disabled = true;
      try {
        const result = await api.post(`/api/v1/quizzes/${quizId}/sessions`, {
          mode: "live",
          language: quiz.default_language,
        });
        const code = result.session.code;
        localStorage.setItem(`ol_ht_${code}`, result.host_token);
        navigate(`/host/${code}`);
      } catch (error) {
        button.disabled = false;
        toast(error.detail || t("common.error"), "error");
      }
      return;
    }
    if (button.dataset.act === "duplicate") {
      button.disabled = true;
      try {
        const copy = await api.post(`/api/v1/quizzes/${quizId}/duplicate`);
        toast(`${copy.title}`, "success");
        navigate(`/quizzes/${copy.id}/edit`);
      } catch (error) {
        button.disabled = false;
        toast(error.detail || t("common.error"), "error");
      }
      return;
    }
    if (button.dataset.act === "delete") {
      const confirmed = await confirmDialog(
        t("dash.delete_title"),
        t("dash.delete_body"),
        t("action.delete"),
      );
      if (!confirmed) return;
      try {
        await api.del(`/api/v1/quizzes/${quizId}`);
        toast(t("dash.deleted"), "success");
        navigate("/dashboard", { replace: true });
      } catch (error) {
        toast(error.detail || t("common.error"), "error");
      }
    }
  });

  return root;
}
