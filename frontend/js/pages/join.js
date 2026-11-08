// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Join by shared link (/join/<token>): resolve, then hand over to the player view. */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { renderPlay } from "./play.js";

export async function renderJoin({ token }) {
  const root = document.createElement("div");
  let session;
  try {
    session = await api.get(`/api/v1/join/${encodeURIComponent(token)}`);
  } catch {
    root.innerHTML = `
      <div class="empty">
        <h2>${t("join.invalid")}</h2>
        <p class="muted">${t("join.invalid_hint")}</p>
        <a class="btn mt-2" href="/" data-link>${t("action.back")}</a>
      </div>`;
    return root;
  }

  // A live link stops working the moment the host starts: say why instead of
  // letting the join fail with a generic error.
  if (session.join_state === "started" || session.join_state === "finished") {
    root.innerHTML = `
      <div class="empty">
        <h2>${t("join.already_started")}</h2>
        <p class="muted">${t("join.already_started_hint", { title: session.quiz_title })}</p>
        <a class="btn mt-2" href="/" data-link>${t("action.back")}</a>
      </div>`;
    return root;
  }
  if (session.join_state === "full") {
    root.innerHTML = `
      <div class="empty">
        <h2>${t("join.full")}</h2>
        <p class="muted">${t("join.full_hint")}</p>
        <a class="btn mt-2" href="/" data-link>${t("action.back")}</a>
      </div>`;
    return root;
  }
  // Keep the browser URL in sync with the canonical player route.
  history.replaceState({}, "", `/play/${session.code}`);
  return renderPlay({ code: session.code });
}
