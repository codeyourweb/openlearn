// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Assessment: one run per candidate, and the result book the author reads.
 *
 * The section only exists for the author of a multiple-choice, swipe or poll
 * questionnaire. It holds three things: the run ceiling, the private link the
 * candidates receive, and the table of every attempt with its detail.
 */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { escapeHtml, formatDate, toast } from "../ui.js";

const LIMITS = [0, 1, 2, 3, 5];

export function assessmentSection(quiz) {
  return `
    <section class="card assess mt-3" id="quiz-assess">
      <div class="assess-head">
        <div>
          <h2>${escapeHtml(t("results.evaluation"))}</h2>
          <p class="muted small">${escapeHtml(t("quiz.max_attempts_hint"))}</p>
        </div>
        <label class="inline-field">
          <span>${escapeHtml(t("quiz.max_attempts"))}</span>
          <select id="assess-limit">
            ${LIMITS.map(
              (value) =>
                `<option value="${value}" ${Number(quiz.max_attempts || 0) === value ? "selected" : ""}>${
                  value === 0 ? escapeHtml(t("quiz.attempts_unlimited")) : value
                }</option>`,
            ).join("")}
          </select>
        </label>
      </div>

      <div class="assess-share" id="assess-share"></div>
      <div class="assess-body" id="assess-body"><p class="muted small">…</p></div>
      <div class="assess-detail" id="assess-detail" hidden></div>
    </section>`;
}

export function bindAssessment(root, quiz) {
  const section = root.querySelector("#quiz-assess");
  if (!section) return;

  const share = section.querySelector("#assess-share");
  const body = section.querySelector("#assess-body");
  const detail = section.querySelector("#assess-detail");
  const limit = section.querySelector("#assess-limit");
  let state = { token: quiz.share_token || null };

  const paintShare = () => {
    if (state.token) {
      const url = `${location.origin}/e/${state.token}`;
      share.innerHTML = `
        <div class="assess-share-box">
          <div>
            <strong>${escapeHtml(t("results.share_title"))}</strong>
            <p class="muted small">${escapeHtml(t("results.share_help"))}</p>
            <input class="input" id="assess-url" readonly value="${escapeHtml(url)}" />
          </div>
          <div class="row-wrap">
            <button class="btn btn-sm" id="assess-copy">${escapeHtml(t("results.share_copy"))}</button>
            <button class="btn btn-sm btn-ghost btn-danger" id="assess-revoke">${escapeHtml(t("results.share_revoke"))}</button>
          </div>
        </div>`;
      share.querySelector("#assess-copy").addEventListener("click", async () => {
        const input = share.querySelector("#assess-url");
        input.select();
        try {
          await navigator.clipboard.writeText(input.value);
        } catch {
          document.execCommand("copy");
        }
        toast(t("results.share_copied"), "success");
      });
      share.querySelector("#assess-revoke").addEventListener("click", async (event) => {
        event.currentTarget.disabled = true;
        try {
          await api.del(`/api/v1/quizzes/${quiz.id}/share`);
          state.token = null;
          paintShare();
          toast(t("results.share_revoked"), "success");
        } catch (error) {
          toast(error.message || "Error", "error");
        }
      });
      return;
    }
    share.innerHTML = `
      <div class="assess-share-box">
        <div>
          <strong>${escapeHtml(t("results.share_title"))}</strong>
          <p class="muted small">${escapeHtml(t("results.share_help"))}</p>
        </div>
        <button class="btn btn-sm btn-primary" id="assess-create">${escapeHtml(t("results.share_create"))}</button>
      </div>`;
    share.querySelector("#assess-create").addEventListener("click", async (event) => {
      event.currentTarget.disabled = true;
      try {
        const payload = await api.post(`/api/v1/quizzes/${quiz.id}/share`, {});
        state.token = payload.token;
        paintShare();
      } catch (error) {
        toast(error.message || "Error", "error");
      }
    });
  };

  const paintDetail = async (participantId) => {
    detail.hidden = false;
    detail.innerHTML = `<p class="muted small">…</p>`;
    try {
      const payload = await api.get(`/api/v1/quizzes/${quiz.id}/attempts/${participantId}`);
      const rows = payload.items
        .map(
          (item) => `
          <li class="assess-answer ${item.is_correct === true ? "ok" : item.is_correct === false ? "ko" : ""}">
            <span class="assess-answer-num">${item.position}</span>
            <div>
              <p class="assess-answer-q">${item.question}</p>
              <p class="muted small">${escapeHtml(item.answer.join(", ") || "—")}</p>
            </div>
            <span class="assess-answer-score">${
              item.is_correct === null ? "—" : `${item.points}`
            }</span>
          </li>`,
        )
        .join("");
      detail.innerHTML = `
        <div class="assess-detail-head">
          <strong>${escapeHtml(payload.participant.candidate)}</strong>
          <span class="muted small">${payload.participant.score} / ${payload.participant.max_score} · ${escapeHtml(
            payload.participant.mode === "solo" ? t("results.solo") : t("results.live"),
          )}</span>
          <button class="btn btn-sm btn-ghost" id="assess-detail-close">×</button>
        </div>
        ${payload.reveal ? "" : `<p class="banner warn">${escapeHtml(t("results.reveal_later"))}</p>`}
        <ul class="assess-answers">${rows}</ul>`;
      detail.querySelector("#assess-detail-close").addEventListener("click", () => {
        detail.hidden = true;
      });
      detail.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
      detail.innerHTML = `<p class="banner warn">${escapeHtml(error.message || "Error")}</p>`;
    }
  };

  const paintBody = (payload) => {
    const candidates = payload.candidates || [];
    if (!candidates.length) {
      body.innerHTML = `<p class="muted small">${escapeHtml(t("results.empty"))}</p>`;
      return;
    }
    body.innerHTML = `
      <table class="assess-table">
        <thead>
          <tr>
            <th>${escapeHtml(t("results.candidate"))}</th>
            <th>${escapeHtml(t("results.runs"))}</th>
            <th>${escapeHtml(t("results.best"))}</th>
            <th>${escapeHtml(t("results.last"))}</th>
            <th>${escapeHtml(t("results.status"))}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${candidates
            .map(
              (candidate) => `
            <tr>
              <td>
                <strong>${escapeHtml(candidate.candidate)}</strong>
                ${candidate.email ? `<span class="muted small block">${escapeHtml(candidate.email)}</span>` : ""}
              </td>
              <td>${candidate.runs}</td>
              <td>${candidate.best_score} / ${candidate.max_score}</td>
              <td>${candidate.last_at ? escapeHtml(formatDate(candidate.last_at)) : "—"}</td>
              <td>${
                candidate.remaining_attempts === null
                  ? escapeHtml(t("results.unlimited"))
                  : candidate.remaining_attempts > 0
                    ? escapeHtml(t("results.remaining", { n: candidate.remaining_attempts }))
                    : `<span class="pill warn">${escapeHtml(t("results.none_left"))}</span>`
              }</td>
              <td class="assess-actions">
                <button class="btn btn-sm btn-ghost" data-detail="${candidate.user_id || ""}" data-participant="${
                  candidate.last_participant_id || ""
                }">${escapeHtml(t("results.detail"))}</button>
                ${
                  candidate.user_id && quiz.max_attempts
                    ? `<button class="btn btn-sm" data-grant="${candidate.user_id}">${escapeHtml(t("results.grant"))}</button>`
                    : ""
                }
              </td>
            </tr>`,
            )
            .join("")}
        </tbody>
      </table>`;

    body.querySelectorAll("[data-grant]").forEach((button) => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await api.post(`/api/v1/quizzes/${quiz.id}/attempts/${button.dataset.grant}/grant`, {});
          toast(t("results.granted"), "success");
          await refresh();
        } catch (error) {
          toast(error.message || "Error", "error");
          button.disabled = false;
        }
      });
    });
    body.querySelectorAll("[data-detail]").forEach((button) => {
      button.addEventListener("click", () => {
        const id = button.dataset.participant || payload.attempts.find((a) => String(a.user_id) === button.dataset.detail)?.participant_id;
        if (id) paintDetail(id);
      });
    });
  };

  const refresh = async () => {
    try {
      const payload = await api.get(`/api/v1/quizzes/${quiz.id}/attempts`);
      state.token = payload.quiz.share_token;
      paintShare();
      paintBody(payload);
    } catch (error) {
      section.hidden = true;
    }
  };

  limit.addEventListener("change", async () => {
    const value = Number(limit.value) || 0;
    try {
      await api.post(`/api/v1/quizzes/${quiz.id}/attempts-policy`, { max_attempts: value });
      quiz.max_attempts = value;
      toast(t("action.saved"), "success");
      await refresh();
    } catch (error) {
      toast(error.message || "Error", "error");
    }
  });

  refresh();
}
