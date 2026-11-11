// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Framing a picture inside the area that shows it.

   An illustration is rarely the shape of its frame: a 2:3 revision card, a wide
   scene banner, a square question slot. Instead of choosing once and for ever,
   the author picks a focus point and a zoom, and every surface applies them.

   `{}` — no framing — keeps the behaviour every existing picture had: shown
   whole, letterboxed inside a capped box. A framing switches the picture to
   `cover`: it fills the frame, and the author says which part stays visible.

   The values travel as a data attribute and land in CSS custom properties
   through the CSSOM: the CSP forbids inline `style` attributes.
*/

export const DEFAULT_FRAMING = { x: 50, y: 50, zoom: 1 };
export const MIN_ZOOM = 1;
export const MAX_ZOOM = 3;

/** Clamp a framing coming from a payload or from the editor. */
export function normalizeFraming(value) {
  if (!value || typeof value !== "object") return null;
  const x = Number(value.x);
  const y = Number(value.y);
  const zoom = Number(value.zoom);
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(zoom)) return null;
  const clean = {
    x: Math.min(100, Math.max(0, x)),
    y: Math.min(100, Math.max(0, y)),
    zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom)),
  };
  // Centred and unzoomed is the default: storing it would only add noise.
  if (Math.abs(clean.x - 50) < 0.05 && Math.abs(clean.y - 50) < 0.05 && clean.zoom < 1.005) {
    return null;
  }
  return {
    x: Math.round(clean.x * 10) / 10,
    y: Math.round(clean.y * 10) / 10,
    zoom: Math.round(clean.zoom * 100) / 100,
  };
}

function escapeAttr(value) {
  return String(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

/** `data-framing='{"x":…}'`, or "" when the picture is shown whole. */
export function framingAttr(framing) {
  const clean = normalizeFraming(framing);
  return clean ? ` data-framing="${escapeAttr(JSON.stringify(clean))}"` : "";
}

/** Apply every `[data-framing]` under `root`: values into CSS variables. */
export function paintFraming(root = document) {
  for (const element of root.querySelectorAll("[data-framing]")) {
    const framing = normalizeFraming(safeParse(element.getAttribute("data-framing")));
    if (!framing) continue;
    element.style.setProperty("--frame-x", `${framing.x}%`);
    element.style.setProperty("--frame-y", `${framing.y}%`);
    element.style.setProperty("--frame-zoom", String(framing.zoom));
    element.classList.add("is-framed");
    // A zoomed picture spills out of its box: the frame has to clip it.
    const frame = element.closest("[data-frame-clip], .revision-card-face, .adv-scene, .adv-ending, .question-card");
    if (frame) frame.classList.add("clip-frame");
  }
}

function safeParse(value) {
  try {
    return JSON.parse(value || "null");
  } catch {
    return null;
  }
}

/** CSS for the editor preview, mirroring what the page will show. */
export function framingStyle(framing) {
  const clean = normalizeFraming(framing) || DEFAULT_FRAMING;
  return {
    objectFit: clean.zoom > 1 || normalizeFraming(framing) ? "cover" : "contain",
    objectPosition: `${clean.x}% ${clean.y}%`,
    transform: `scale(${clean.zoom})`,
    transformOrigin: `${clean.x}% ${clean.y}%`,
  };
}
