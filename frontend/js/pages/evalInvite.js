// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* The private evaluation link a candidate receives.
 *
 * The page is intentionally thin: it says what the questionnaire is, how many
 * runs are left, and starts a deferred session. Everything else — questions,
 * timing, scoring — stays in the usual play screen.
 */

import { api } from "../api.js";
import { t, tp } from "../i18n.js";
import { navigate } from "../router.js";
import { isLoggedIn } from "../store.js";
import { escapeHtml, toast } from "../ui.js";

export function renderEvalInvite({ token }) {
  const root = document.createElement("section");
  root.className = "card eval-invite";
  root.innerHTML = `<p class="muted">…</p>`;

  const start = async (button) => {
    button.disabled = true;
    try {
      const result = await api.post(`/api/v1/eval/${encodeURIComponent(token)}/sessions`, {
        mode: "solo",
      });
      const code = result.session.code;
      if (result.participant) {
        localStorage.setItem(`ol_pt_${code}`, result.participant.token);
        localStorage.setItem(`ol_pid_${code}`, String(result.participant.id));
        localStorage.setItem(`ol_nick_${code}`, result.participant.nickname);
      }
      toast(t("eval.started"), "success");
      navigate(`/play/${code}`);
    } catch (error) {
      button.disabled = false;
      toast(error.detail || error.message || t("common.error"), "error");
    }
  };

  api
    .get(`/api/v1/eval/${encodeURIComponent(token)}`)
    .then((quiz) => {
      const signedIn = isLoggedIn() && quiz.signed_in;
      const left = quiz.remaining_attempts;
      const exhausted = left !== null && left <= 0;
      const action = !signedIn
        ? `<a class="btn btn-primary btn-lg" data-link href="/login?next=${encodeURIComponent(`/e/${token}`)}">${escapeHtml(
            t("nav.signin"),
          )}</a>`
        : exhausted
          ? ""
          : `<button class="btn btn-primary btn-lg" id="eval-start">${escapeHtml(t("eval.start"))}</button>`;

      root.innerHTML = `
        <p class="ld-eyebrow">${escapeHtml(t("eval.title"))}</p>
        <h1>${escapeHtml(quiz.title)}</h1>
        ${quiz.description ? `<p class="lede">${escapeHtml(quiz.description)}</p>` : ""}
        <p class="muted">${escapeHtml(t("eval.lede"))}</p>
        <ul class="eval-facts">
          <li>${escapeHtml(tp("eval.question_one", "eval.questions", quiz.question_count))}</li>
          ${
            left === null
              ? `<li>${escapeHtml(t("quiz.attempts_unlimited"))}</li>`
              : `<li class="${exhausted ? "warn" : ""}">${escapeHtml(tp("eval.run_one", "eval.remaining", left))}</li>`
          }
        </ul>
        ${!signedIn ? `<p class="banner warn">${escapeHtml(t("eval.signin"))}</p>` : ""}
        ${exhausted ? `<p class="banner warn">${escapeHtml(t("eval.none_left"))}</p>` : ""}
        <div class="row-wrap mt-2">${action}</div>`;

      const button = root.querySelector("#eval-start");
      if (button) button.addEventListener("click", () => start(button));
    })
    .catch((error) => {
      root.innerHTML = `<h1>${escapeHtml(t("eval.invalid"))}</h1><p class="muted">${escapeHtml(
        error.detail || error.message || "",
      )}</p><a class="btn mt-2" data-link href="/quizzes">${escapeHtml(t("nav.questionnaires"))}</a>`;
    });

  return root;
}
