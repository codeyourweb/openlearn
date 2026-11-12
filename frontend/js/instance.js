// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* What this instance is: demo or private, AI on or off, which providers.
 *
 * Loaded once before the first render. The `<html>` element carries the flags
 * as data attributes so CSS can hide an AI entry point without every page
 * remembering to ask.
 */

import { api } from "./api.js";

const FALLBACK = {
  name: "OpenLearn",
  version: "",
  demo_mode: false,
  github_url: "https://github.com/codeyourweb/openlearn",
  registration_open: true,
  languages: ["en", "fr", "it", "es", "de", "ru", "zh", "ja"],
  ai: { enabled: false, available: false, model: "", min_interval_seconds: 15 },
  mail: { configured: false },
  sharing: { qr: true, social: true },
  sso: [],
  mcp: { enabled: false, endpoint: "/mcp", requires_auth: true },
};

let meta = null;

export async function loadInstance() {
  try {
    meta = await api.get("/api/v1/meta");
  } catch {
    // An unreachable meta endpoint must not blank the whole application: fall
    // back to the most conservative reading (private instance, no AI).
    meta = { ...FALLBACK };
  }
  const root = document.documentElement;
  root.dataset.ai = aiEnabled() ? "on" : "off";
  root.dataset.demo = instance().demo_mode ? "on" : "off";
  root.dataset.sso = instance().sso && instance().sso.length ? "on" : "off";
  return meta;
}

export function instance() {
  return meta || FALLBACK;
}

/** AI is offered to users only when the provider is switched on *and* usable. */
export function aiEnabled() {
  const ai = instance().ai || {};
  return Boolean(ai.enabled && ai.available);
}

/** Both switches are independent: the room may want the code and no networks. */
export function qrSharingEnabled() {
  const sharing = instance().sharing || {};
  return sharing.qr !== false;
}

export function socialSharingEnabled() {
  const sharing = instance().sharing || {};
  return sharing.social !== false;
}

/** The entry page: the presentation on a demo instance, the wiki elsewhere. */
export function defaultRoute() {
  return instance().demo_mode ? "/about" : "/wiki";
}
