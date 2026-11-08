// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Inline SVG flags for the language picker.

   Emoji flags are not rendered on every platform (Windows shows "FR"), so the
   flags are drawn here: each one is a 24x16 viewBox, clipped by CSS.
*/

const FLAGS = {
  fr: `
    <rect width="8" height="16" fill="#0055a4"/>
    <rect x="8" width="8" height="16" fill="#ffffff"/>
    <rect x="16" width="8" height="16" fill="#ef4135"/>`,
  it: `
    <rect width="8" height="16" fill="#009246"/>
    <rect x="8" width="8" height="16" fill="#ffffff"/>
    <rect x="16" width="8" height="16" fill="#ce2b37"/>`,
  de: `
    <rect width="24" height="5.34" fill="#000000"/>
    <rect y="5.34" width="24" height="5.33" fill="#dd0000"/>
    <rect y="10.67" width="24" height="5.33" fill="#ffce00"/>`,
  es: `
    <rect width="24" height="16" fill="#aa151b"/>
    <rect y="4" width="24" height="8" fill="#f1bf00"/>`,
  en: `
    <rect width="24" height="16" fill="#012169"/>
    <path d="M0 0 L24 16 M24 0 L0 16" stroke="#ffffff" stroke-width="3.4"/>
    <path d="M0 0 L24 16 M24 0 L0 16" stroke="#c8102e" stroke-width="1.5"/>
    <path d="M12 0 V16 M0 8 H24" stroke="#ffffff" stroke-width="5.4"/>
    <path d="M12 0 V16 M0 8 H24" stroke="#c8102e" stroke-width="3"/>`,
  ru: `
    <rect width="24" height="5.34" fill="#ffffff"/>
    <rect y="5.34" width="24" height="5.33" fill="#0039a6"/>
    <rect y="10.67" width="24" height="5.33" fill="#d52b1e"/>`,
  ja: `
    <rect width="24" height="16" fill="#ffffff"/>
    <circle cx="12" cy="8" r="4.6" fill="#bc002d"/>`,
  zh: `
    <rect width="24" height="16" fill="#de2910"/>
    <polygon points="4.6,2.2 5.6,4.4 8,4.6 6.2,6.1 6.8,8.4 4.6,7.1 2.4,8.4 3,6.1 1.2,4.6 3.6,4.4"
             fill="#ffde00"/>`,
};

function escapeAttr(value) {
  return String(value).replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[ch]
  ));
}

/**
 * Small flag row for a quiz's language list.
 *
 * The default language is boxed, the rest are dimmed; past `max` the overflow is
 * summarised as "+n" so a card stays calm. Text codes stay in the tooltip for
 * screen readers and hover.
 */
export function flagStrip(languages, defaultLanguage = "fr", max = 4) {
  const list = (Array.isArray(languages) && languages.length ? languages : [defaultLanguage])
    .filter(Boolean)
    .map((code) => String(code).slice(0, 5));
  const shown = list.slice(0, max);
  const extra = list.length - shown.length;
  const chips = shown
    .map(
      (code) =>
        `<span class="flag-chip${code === defaultLanguage ? " is-default" : ""}" data-lang="${escapeAttr(code)}" title="${escapeAttr(code)}">${flagSvg(code)}</span>`,
    )
    .join("");
  return `<span class="flag-strip" title="${escapeAttr(list.join(", "))}">${chips}${
    extra > 0 ? `<span class="flag-more">+${extra}</span>` : ""
  }</span>`;
}

/* Nothing in the table: a blank chip, never somebody else's flag. */
const UNKNOWN = `
    <rect width="24" height="16" fill="currentColor" opacity="0.18"/>
    <rect x="0.6" y="0.6" width="22.8" height="14.8" rx="1.6" fill="none"
          stroke="currentColor" stroke-width="1.2" opacity="0.55"/>`;

/** Return the inline SVG markup for a language code. */
export function flagSvg(code) {
  const body = FLAGS[code] || UNKNOWN;
  return `<svg class="flag" viewBox="0 0 24 16" width="22" height="15" aria-hidden="true"
    focusable="false" preserveAspectRatio="none">${body}</svg>`;
}
