// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Application state and per-session credentials (localStorage). */

export const state = {
  user: null,
  ready: false,
};

const PREFIX = "ol";

export function isLoggedIn() {
  return Boolean(state.user);
}

export function setUser(user) {
  state.user = user || null;
  state.ready = true;
}

export function credentialKey(kind, code) {
  return `${PREFIX}_${kind}_${String(code).toUpperCase()}`;
}

export function saveSessionCredentials(code, { participantToken, hostToken, participantId, nickname } = {}) {
  if (participantToken) localStorage.setItem(credentialKey("pt", code), participantToken);
  if (hostToken) localStorage.setItem(credentialKey("ht", code), hostToken);
  if (participantId) localStorage.setItem(credentialKey("pid", code), String(participantId));
  if (nickname) localStorage.setItem(credentialKey("nick", code), nickname);
}

export function participantToken(code) {
  return localStorage.getItem(credentialKey("pt", code)) || "";
}

export function hostToken(code) {
  return localStorage.getItem(credentialKey("ht", code)) || "";
}

export function participantId(code) {
  const value = localStorage.getItem(credentialKey("pid", code));
  return value ? Number(value) : null;
}

export function nickname(code) {
  return localStorage.getItem(credentialKey("nick", code)) || "";
}

export function clearSessionCredentials(code) {
  ["pt", "ht", "pid", "nick"].forEach((kind) => localStorage.removeItem(credentialKey(kind, code)));
}
