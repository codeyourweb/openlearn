// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/*
 * Creation chooser, in two steps.
 *
 * Step 1 picks the format (multiple choice, swipe cards, poll, story); step 2
 * picks how to fill it (a model draft to edit, or a blank form). The second
 * step lives on `/quizzes/new/:mode` so a reload or a shared link lands on the
 * same place; the editor itself is only reached from there.
 */

import { t } from "../i18n.js";
import { api } from "../api.js";
import { navigate } from "../router.js";
import { isLoggedIn } from "../store.js";

const ICONS = {
  qcm: `<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.7"
        stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <rect x="3" y="4" width="18" height="16" rx="3"></rect>
    <path d="M7.5 10.5l1.6 1.6 3-3.2"></path>
    <path d="M7.5 16h9"></path>
  </svg>`,
  swipe: `<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.7"
        stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <rect x="7" y="3" width="10" height="18" rx="3"></rect>
    <path d="M4 9l-1.5 3L4 15"></path>
    <path d="M20 9l1.5 3L20 15"></path>
  </svg>`,
  poll: `<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.7"
        stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M4 20h16"></path>
    <rect x="6" y="11" width="3.4" height="6" rx="1"></rect>
    <rect x="11.3" y="7" width="3.4" height="10" rx="1"></rect>
    <rect x="16.6" y="13" width="3.4" height="4" rx="1"></rect>
  </svg>`,
  story: `<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.7"
        stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <circle cx="5.5" cy="6" r="2.2"></circle>
    <circle cx="5.5" cy="18" r="2.2"></circle>
    <circle cx="18.5" cy="12" r="2.2"></circle>
    <path d="M7.7 6.6c5 .6 5.6 4 8.6 4.9"></path>
    <path d="M7.7 17.4c5-.6 5.6-4 8.6-4.9"></path>
  </svg>`,
};

const CARDS = [
  {
    key: "qcm",
    badge: "new_quiz.badge_classic",
    icon: ICONS.qcm,
    points: ["new_quiz.qcm_p1", "new_quiz.qcm_p2", "new_quiz.qcm_p3"],
  },
  {
    key: "swipe",
    badge: "new_quiz.badge_fast",
    icon: ICONS.swipe,
    points: ["new_quiz.swipe_p1", "new_quiz.swipe_p2", "new_quiz.swipe_p3"],
  },
  {
    key: "poll",
    badge: "new_quiz.badge_survey",
    icon: ICONS.poll,
    points: ["new_quiz.poll_p1", "new_quiz.poll_p2", "new_quiz.poll_p3"],
  },
  {
    key: "story",
    badge: "new_quiz.badge_visual",
    icon: ICONS.story,
    points: ["new_quiz.story_p1", "new_quiz.story_p2", "new_quiz.story_p3"],
  },
];

/** Escape a value used inside an attribute. */
function escapeAttr(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function card({ href, badge, icon, title, lead, points, cta }) {
  return `
    <a class="mode-card" href="${escapeAttr(href)}" data-link aria-label="${escapeAttr(title)}">
      <span class="mode-card-badge">${t(badge)}</span>
      <span class="mode-card-icon">${icon}</span>
      <h2>${title}</h2>
      <p class="mode-card-lead">${lead}</p>
      <ul class="mode-card-points">
        ${points.map((point) => `<li>${t(point)}</li>`).join("")}
      </ul>
      <span class="mode-card-cta">${t(cta)}
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M5 12h13"></path><path d="M12.5 5.5L19 12l-6.5 6.5"></path>
        </svg>
      </span>
    </a>`;
}

/** Step 1: which questionnaire? */
export async function renderNewQuiz() {
  const root = document.createElement("div");
  if (!isLoggedIn()) {
    navigate(`/login?next=${encodeURIComponent("/quizzes/new")}`, { replace: true });
    return root;
  }

  root.innerHTML = `
    <section class="new-quiz">
      <header class="new-quiz-head">
        <h1>${t("new_quiz.title")}</h1>
        <p>${t("new_quiz.lede")}</p>
      </header>
      <div class="mode-grid">
        ${CARDS.map((entry) =>
          card({
            // A story has its own canvas, everything else goes through the method step.
            href: entry.key === "story" ? "/adventures/new" : `/quizzes/new/${entry.key}`,
            badge: entry.badge,
            icon: entry.icon,
            title: t(`new_quiz.${entry.key}`),
            lead: t(`new_quiz.${entry.key}_desc`),
            points: entry.points,
            cta: "new_quiz.start",
          }),
        ).join("")}
      </div>
      <p class="new-quiz-foot muted small">${t("new_quiz.footnote")}</p>
    </section>`;

  return root;
}

/** Step 2: how to fill it — a model draft to edit, or a blank form. */
export async function renderNewQuizMethod({ mode }) {
  const root = document.createElement("div");
  const normalized = ["qcm", "swipe", "poll"].includes(mode) ? mode : "qcm";
  if (!isLoggedIn()) {
    navigate(`/login?next=${encodeURIComponent(`/quizzes/new/${normalized}`)}`, { replace: true });
    return root;
  }

  let aiAvailable = false;
  try {
    const status = await api.get("/api/v1/ai/status");
    aiAvailable = Boolean(status.available);
  } catch {
    /* AI is optional: the manual card stays alone rather than broken */
  }

  const aiCard = aiAvailable
    ? card({
        href: `/quizzes/new/${normalized}/ai`,
        badge: "new_quiz.method_ai",
        icon: `<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor"
                 stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                 <path d="M12 3l1.8 4.6L18.5 9l-4.7 1.4L12 15l-1.8-4.6L5.5 9l4.7-1.4z"></path>
                 <path d="M17.5 15.5l.9 2.3 2.3.9-2.3.9-.9 2.3-.9-2.3-2.3-.9 2.3-.9z"></path>
               </svg>`,
        title: t("new_quiz.method_ai"),
        lead: t("new_quiz.method_ai_desc"),
        points: [],
        cta: "new_quiz.start",
      })
    : "";

  root.innerHTML = `
    <section class="new-quiz">
      <header class="new-quiz-head">
        <a class="btn btn-quiet btn-sm" href="/quizzes/new" data-link>← ${t("new_quiz.back")}</a>
        <h1 class="mt-1">${t("new_quiz.method_title")}</h1>
        <p>${t("new_quiz.method_lede")}</p>
        <p class="badge">${t(`new_quiz.${normalized}`)}</p>
      </header>
      <div class="mode-grid mode-grid-two">
        ${card({
          href: `/quizzes/new/${normalized}/manual`,
          badge: "new_quiz.method_manual",
          icon: `<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor"
                   stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                   <path d="M4 20l4-1 9.5-9.5a2.1 2.1 0 0 0-3-3L5 16z"></path>
                   <path d="M13.5 5.5l3 3"></path>
                 </svg>`,
          title: t("new_quiz.method_manual"),
          lead: t("new_quiz.method_manual_desc"),
          points: [],
          cta: "new_quiz.start",
        })}
        ${aiCard}
      </div>
      ${aiAvailable ? "" : `<p class="new-quiz-foot muted small">${t("new_quiz.method_ai_unavailable")}</p>`}
    </section>`;

  return root;
}
