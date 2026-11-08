// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Light / dark theme, persisted in localStorage. */

const KEY = "ol_theme";
export const THEMES = ["dark", "light"];

export function currentTheme() {
  try {
    const stored = localStorage.getItem(KEY);
    if (THEMES.includes(stored)) return stored;
  } catch {
    /* storage disabled */
  }
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function applyTheme(theme) {
  const value = THEMES.includes(theme) ? theme : "dark";
  document.documentElement.dataset.theme = value;
  const meta = document.querySelector('meta[name="color-scheme"]');
  if (meta) meta.setAttribute("content", value === "light" ? "light" : "dark");
  try {
    localStorage.setItem(KEY, value);
  } catch {
    /* ignore */
  }
  return value;
}

export function toggleTheme() {
  return applyTheme(currentTheme() === "dark" ? "light" : "dark");
}
