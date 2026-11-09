// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)

/* Where a reader lands after signing in.
 *
 * Signing in from an article used to drop the reader on the account page, so
 * the thing they wanted to do was two navigations away. The last page they
 * looked at is remembered for the session, and an explicit `?next=` still wins
 * over it: a link that says where to go must not be overruled by history.
 */
const KEY = "ol.returnTo";
// Pages that are part of signing in, not a destination of their own.
const AUTH_PAGES = /^\/(login|register|verify|reset|forgot|logout)(\/|$)/;

function safePath(value) {
  const path = value ? String(value) : "";
  return path.startsWith("/") && !path.startsWith("//") ? path : "";
}

export function rememberReturnTarget() {
  if (AUTH_PAGES.test(location.pathname)) return;
  try {
    sessionStorage.setItem(KEY, `${location.pathname}${location.search}`);
  } catch {
    /* storage can be unavailable; the fallback is the dashboard */
  }
}

export function returnTarget(query = {}) {
  const asked = safePath(query && query.next);
  if (asked) return asked;
  let stored = "";
  try {
    stored = safePath(sessionStorage.getItem(KEY));
  } catch {
    /* private mode */
  }
  return stored || "/dashboard";
}

export function forgetReturnTarget() {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* private mode */
  }
}
