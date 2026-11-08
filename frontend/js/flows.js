// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Shared user flows: start a solo session, host a live session. */

import { api } from "./api.js";
import { isLoggedIn, saveSessionCredentials, state } from "./store.js";
import { toast } from "./ui.js";

export async function startSolo(quizId, navigate, button) {
  if (button) button.disabled = true;
  try {
    const result = await api.post(`/api/v1/quizzes/${quizId}/sessions`, {
      mode: "solo",
      nickname: state.user ? state.user.display_name : undefined,
    });
    saveSessionCredentials(result.session.code, {
      participantToken: result.participant.token,
      hostToken: result.host_token,
      participantId: result.participant.id,
      nickname: result.participant.nickname,
    });
    navigate(`/play/${result.session.code}`);
  } catch (error) {
    toast(error.detail || "Could not start the quiz", "error");
  } finally {
    if (button) button.disabled = false;
  }
}

export async function hostLive(quizId, navigate, button) {
  if (!isLoggedIn()) {
    navigate(`/login?next=${encodeURIComponent(`/quizzes/${quizId}`)}`);
    return;
  }
  if (button) button.disabled = true;
  try {
    const result = await api.post(`/api/v1/quizzes/${quizId}/sessions`, { mode: "live" });
    saveSessionCredentials(result.session.code, { hostToken: result.host_token });
    navigate(`/host/${result.session.code}`);
  } catch (error) {
    toast(error.detail || "Could not open the lobby", "error");
  } finally {
    if (button) button.disabled = false;
  }
}

export async function duplicateQuiz(quizId, navigate, button) {
  if (button) button.disabled = true;
  try {
    const copy = await api.post(`/api/v1/quizzes/${quizId}/duplicate`, {});
    toast("Quiz duplicated", "success");
    navigate(`/quizzes/${copy.id}/edit`);
  } catch (error) {
    toast(error.detail || "Could not duplicate the quiz", "error");
  } finally {
    if (button) button.disabled = false;
  }
}
