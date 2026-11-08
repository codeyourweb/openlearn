// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Detailed post-game view: who answered what, question by question. */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { hostToken, participantToken } from "../store.js";
import { escapeHtml, formatDate, formatDuration } from "../ui.js";

export async function renderResults({ code }) {
  const normalized = String(code).toUpperCase();
  const root = document.createElement("div");
  const headers = {};
  if (participantToken(normalized)) headers["X-Participant-Token"] = participantToken(normalized);
  if (hostToken(normalized)) headers["X-Host-Token"] = hostToken(normalized);

  let data;
  try {
    data = await api.get(`/api/v1/sessions/${normalized}/results`, { headers });
  } catch (error) {
    root.innerHTML = `
      <div class="empty">
        <h2>${t("error.forbidden")}</h2>
        <p class="muted">${escapeHtml(error.detail || "")}</p>
        <a class="btn mt-2" href="/" data-link>${t("nav.home")}</a>
      </div>`;
    return root;
  }

  const isHost = data.viewer && data.viewer.role === "host";
  const myPid = data.viewer && data.viewer.participant_id;
  const totalSeconds = data.questions.reduce((sum, question) => sum + question.time_limit_seconds, 0);

  const scoreboard = data.scoreboard
    .map(
      (row, index) => `
      <div class="score-row ${row.id === myPid ? "me" : ""}">
        <span class="score-rank">${index + 1}</span>
        <span class="score-name">${escapeHtml(row.nickname)}</span>
        <span class="score-value">${row.score}</span>
      </div>`,
    )
    .join("");

  const questionsHtml = data.questions
    .map((question) => {
      const correctTexts = question.options
        .filter((option) => option.is_correct)
        .map((option) => escapeHtml(option.text))
        .join(" · ");
      const multiple = question.options.filter((option) => option.is_correct).length > 1;
      return `
      <section class="card mt-2">
        <div class="card-head">
          <div class="row">
            <span class="q-index">${question.position + 1}</span>
            <div>
              <div class="question-text">${question.text_html}</div>
              <div class="quiz-meta">
                <span>${question.time_limit_seconds}s</span>
                <span>·</span>
                <span>${question.points} ${t("common.points")}</span>
                <span>·</span>
                <span>${multiple ? t("play.multi_hint") : t("play.single_hint")}</span>
              </div>
            </div>
          </div>
        </div>
        ${question.image_path ? `<img class="question-image" src="${escapeHtml(question.image_path)}" alt="" />` : ""}
        <p class="small"><strong>${t("results.correct_answer")}:</strong> ${correctTexts}</p>
        <div class="table-wrap mt-1">
          <table class="table">
            <thead>
              <tr><th>${t("results.player")}</th><th>${t("results.given")}</th><th>${t("common.status")}</th><th>${t("common.points")}</th><th>${t("common.seconds")}</th></tr>
            </thead>
            <tbody>
              ${
                question.answers.length
                  ? question.answers
                      .map(
                        (row) => `
                <tr>
                  <td>${escapeHtml(row.nickname)}</td>
                  <td class="${row.answered ? "" : "muted"}">${
                    row.answered
                      ? row.selected_options.map((text) => escapeHtml(text)).join(" · ") || `<em>${t("common.none")}</em>`
                      : "—"
                  }</td>
                  <td class="${row.is_correct ? "correct" : "wrong"}">${
                    row.answered ? (row.is_correct ? t("results.correct") : t("play.incorrect")) : t("results.no_answer")
                  }</td>
                  <td>${row.points_awarded}</td>
                  <td class="muted">${row.response_ms === null ? "—" : formatDuration(row.response_ms / 1000)}</td>
                </tr>`,
                      )
                      .join("")
                  : `<tr><td colspan="5" class="muted">${t("host.no_players")}</td></tr>`
              }
            </tbody>
          </table>
        </div>
      </section>`;
    })
    .join("");

  root.innerHTML = `
    <div class="row between">
      <div>
        <a class="muted small" href="/" data-link>← ${t("nav.home")}</a>
        <h1 class="mt-1">${escapeHtml(data.session.quiz_title)}</h1>
        <p class="muted">
          ${t("host.pin")} ${escapeHtml(data.session.code)} ·
          ${data.session.started_at ? formatDate(data.session.started_at) : t("host.lobby")} ·
          ${data.questions.length} ${t("common.questions")} ·
          ${Math.round(totalSeconds / 60)} min
        </p>
      </div>
      <div class="row">
        <span class="badge ${data.session.status === "finished" ? "ok" : "muted"}">${escapeHtml(data.session.status)}</span>
        <span class="badge ${isHost ? "" : "muted"}">${isHost ? t("host.results") : t("play.your_score")}</span>
      </div>
    </div>

    <section class="card mt-2">
      <h2>${t("common.score")}</h2>
      ${scoreboard || `<p class="muted">${t("host.no_players")}</p>`}
    </section>

    <section class="mt-3">
      <h2>${t("results.detail")}</h2>
      ${questionsHtml}
    </section>`;

  return root;
}
