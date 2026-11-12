// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* About: the platform explained as a scroll story.
 *
 * Every scene is a CSS mock rather than a screenshot, so the page stays sharp
 * at any size, weightless, and free of a stale picture of the UI. Elements
 * reveal as they enter the viewport; motion is disabled when the visitor asks
 * for reduced motion.
 */

import { LANGUAGES, t } from "../i18n.js";
import { escapeHtml, toast } from "../ui.js";
import { state } from "../store.js";
import { instance } from "../instance.js";

const SCENES = [
  { key: "quiz", side: "left", art: "quiz" },
  { key: "formats", side: "right", art: "formats" },
  { key: "wiki", side: "left", art: "wiki" },
  { key: "collab", side: "right", art: "collab" },
  { key: "ai", side: "left", art: "chat", highlight: true },
  { key: "host", side: "right", art: "host" },
  { key: "access", side: "left", art: "access" },
];

const STATS = [
  { value: LANGUAGES.length, suffix: "", key: "about.stat_languages", icon: "globe" },
  { value: 5, suffix: "", key: "about.stat_formats", icon: "layers" },
  { value: 100, suffix: "%", key: "about.stat_selfhosted", icon: "server" },
  { value: 0, suffix: "", key: "about.stat_tracking", icon: "shield" },
];

/* Small line icons, drawn inline: no sprite, no extra request, and they follow
   the text colour of whatever box they sit in. */
const ICONS = {
  alert:
    "M12 3.2 2.6 20h18.8L12 3.2Zm0 5.4v5.1m0 3.2v.1",
  bulb:
    "M9 18h6m-5 3h4M12 3a6 6 0 0 0-3.6 10.8c.5.4.8 1 .9 1.6l.1 1h5.2l.1-1c.1-.6.4-1.2.9-1.6A6 6 0 0 0 12 3Z",
  globe:
    "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 0c2.5 2.4 3.8 5.5 3.8 9s-1.3 6.6-3.8 9m0-18c-2.5 2.4-3.8 5.5-3.8 9s1.3 6.6 3.8 9M3.3 9h17.4M3.3 15h17.4",
  layers:
    "m12 3 8.5 4.5L12 12 3.5 7.5 12 3Zm8.5 9L12 16.5 3.5 12m17 4.5L12 21l-8.5-4.5",
  server:
    "M4 5h16v5H4V5Zm0 9h16v5H4v-5Zm3.5-6.5h.01M7.5 17.5h.01",
  shield:
    "M12 3 5 6v6c0 4.2 2.9 7.5 7 9 4.1-1.5 7-4.8 7-9V6l-7-3Zm-2.5 8.8 1.9 2 3.4-3.6",
};

function _icon(name, extra = "") {
  const path = ICONS[name];
  if (!path) return "";
  return `<svg class="ld-icon ${extra}" viewBox="0 0 24 24" width="18" height="18" fill="none"
      stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"
      aria-hidden="true"><path d="${path}" /></svg>`;
}

/* A block that can be linked to on its own.
 *
 * Someone who wants to send a colleague straight to "the database choice" sends
 * them the block, not the page: every section carries an id and a discreet
 * button that copies its address. The hash also opens the right view on load,
 * so the link works for someone who has never seen the page.
 */
function _anchor(id) {
  return `<a class="ld-anchor" href="#${id}" data-anchor="${id}"
      aria-label="${escapeHtml(t("about.anchor_copy"))}"
      title="${escapeHtml(t("about.anchor_copy"))}">#</a>`;
}

/* The quiz mock at the top of the page plays itself: three questions, each with
   its own tallies, so the hero shows what the product does instead of a still. */
const MOCK_SETS = [
  { key: "about.mock_q1", bars: [72, 18, 8, 2], players: 24 },
  { key: "about.mock_q2", bars: [11, 63, 21, 5], players: 31 },
  { key: "about.mock_q3", bars: [7, 19, 58, 16], players: 47 },
];

function _cta() {
  return state.user
    ? `<a class="btn btn-primary btn-lg" data-link href="/quizzes">${escapeHtml(t("about.cta_try"))}</a>
       <a class="btn btn-ghost btn-lg" data-link href="/dashboard">${escapeHtml(t("about.cta_dashboard"))}</a>`
    : `<a class="btn btn-primary btn-lg" data-link href="/register">${escapeHtml(t("about.cta_signup"))}</a>
       <a class="btn btn-ghost btn-lg" data-link href="/quizzes">${escapeHtml(t("about.cta_try"))}</a>`;
}

/** The repository, reachable from the first screen rather than after the tour. */
function _starCorner() {
  const repo = instance().github_url || "https://github.com/codeyourweb/openlearn";
  return `
    <a class="ld-star-corner" href="${escapeHtml(repo)}" target="_blank" rel="noopener noreferrer">
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="currentColor">
        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.4 7.4 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/>
      </svg>
      <span>${escapeHtml(t("about.github_star"))}</span>
    </a>`;
}

/** The two audiences, rendered after the message rather than above it. */
function _switchHtml() {
  return `
    <div class="ld-switch-wrap">
      <div class="ld-switch" role="tablist" aria-label="${escapeHtml(t("about.tabs_label"))}">
        <button class="ld-switch-btn is-active" type="button" role="tab" aria-selected="true" data-tab="discover">${escapeHtml(t("about.tab_discover"))}</button>
        <button class="ld-switch-btn" type="button" role="tab" aria-selected="false" data-tab="pro">${escapeHtml(t("about.tab_pro"))}</button>
        <button class="ld-switch-btn" type="button" role="tab" aria-selected="false" data-tab="security">${escapeHtml(t("about.tab_security"))}</button>
      </div>
    </div>`;
}

/** The closing call to action: three doors, plus a quiet GitHub invitation. */
function _finalCta() {
  const repo = instance().github_url || "https://github.com/codeyourweb/openlearn";
  return `
    ${_cta()}
    <a class="btn btn-ghost btn-lg" data-link href="/wiki">${escapeHtml(t("about.cta_wiki"))}</a>
    <a class="ld-github" href="${escapeHtml(repo)}" target="_blank" rel="noopener noreferrer">
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="currentColor">
        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.4 7.4 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/>
      </svg>
      <span>${escapeHtml(t("about.github_star"))}</span>
    </a>`;
}

/* -------------------------------------------------------------------------- */
/* Scene artwork: small app mocks, no images                                  */
/* -------------------------------------------------------------------------- */

/* The opening window used to be the quiz mock, and the same mock came back one
   screen later. This one window carries both stories instead: a wiki page being
   written by three people, then the questionnaire that page feeds. Tabs switch
   on click, and the window alternates on its own so the first screen shows both
   halves of the product without a scroll. */
function _artStudio() {
  // Two acts, one window: a wiki three people are writing, then the quiz it
  // produces. The AI review card sits beside the text, never on top of it.
  return `
    <div class="ld-window ld-studio" data-studio data-on="wiki">
      <div class="ld-window-bar"><span></span><span></span><span></span><em data-studio-title>${escapeHtml(t("about.mock_wiki"))}</em></div>
      <div class="ld-studio-tabs" role="tablist">
        <button class="ld-studio-tab is-active" type="button" role="tab" aria-selected="true"
                data-studio-tab="wiki">${escapeHtml(t("about.studio_tab_wiki"))}</button>
        <button class="ld-studio-tab" type="button" role="tab" aria-selected="false"
                data-studio-tab="quiz">${escapeHtml(t("about.studio_tab_quiz"))}</button>
        <span class="ld-studio-live"><i></i>${escapeHtml(t("about.mock_live"))}</span>
      </div>
      <div class="ld-studio-stage">
        <div class="ld-studio-panel is-on" data-studio-panel="wiki" role="tabpanel">
          <aside class="ld-studio-nav" aria-hidden="true">
            <span class="is-on"></span><span></span><span class="is-sub"></span><span></span><span></span>
          </aside>
          <div class="ld-studio-doc">
            <h4>${escapeHtml(t("about.studio_doc_title"))}</h4>
            <p>${escapeHtml(t("about.studio_doc_p1"))}<span class="ld-caret c-one"></span></p>
            <p>${escapeHtml(t("about.studio_doc_p2"))}<span class="ld-caret c-two"></span></p>
            <p class="ld-studio-typed">${escapeHtml(t("about.studio_doc_typed"))}<span class="ld-caret c-three"></span></p>
            <div class="ld-diff">
              <span class="add">${escapeHtml(t("about.studio_diff_add"))}</span>
              <span class="del">${escapeHtml(t("about.studio_diff_del"))}</span>
            </div>
            <div class="ld-avatars">
              <span class="a">AL</span><span class="b">MB</span><span class="c">JS</span>
            </div>
          </div>
          <aside class="ld-studio-ai">
            <p class="ld-studio-ai-badge">✨ ${escapeHtml(t("about.studio_ai_badge"))}</p>
            <p class="ld-studio-ai-text">${escapeHtml(t("about.studio_ai_text"))}</p>
            <div class="ld-studio-ai-actions">
              <button type="button" class="ld-studio-ai-yes">${escapeHtml(t("about.studio_ai_accept"))}</button>
              <button type="button" class="ld-studio-ai-no">${escapeHtml(t("about.studio_ai_dismiss"))}</button>
            </div>
          </aside>
        </div>
        <div class="ld-studio-panel" data-studio-panel="quiz" role="tabpanel">
          <p class="ld-mock-question">${escapeHtml(t("about.mock_q1"))}</p>
          <div class="ld-studio-options">
            ${["a", "b", "c", "d"]
              .map(
                (key, index) => `
              <span class="ld-studio-opt ${index === 0 ? "is-picked" : ""}">
                <b>${"ABCD"[index]}</b><span>${escapeHtml(t(`about.studio_opt_${key}`))}</span>
              </span>`,
              )
              .join("")}
          </div>
          <p class="ld-studio-from">✨ ${escapeHtml(t("about.studio_quiz_from"))}</p>
          <div class="ld-mock-foot"><span class="ld-dot"></span> <span>24</span> ${escapeHtml(t("about.mock_players"))}</div>
        </div>
      </div>
    </div>`;
}

/** Switch the two acts by hand, and let them alternate when motion is allowed. */
function _startStudio(root) {
  const studio = root.querySelector("[data-studio]");
  if (!studio) return;
  const panels = studio.querySelectorAll("[data-studio-panel]");
  const tabs = studio.querySelectorAll("[data-studio-tab]");
  const title = studio.querySelector("[data-studio-title]");

  const show = (act) => {
    studio.dataset.on = act;
    panels.forEach((panel) => panel.classList.toggle("is-on", panel.dataset.studioPanel === act));
    tabs.forEach((tab) => {
      const on = tab.dataset.studioTab === act;
      tab.classList.toggle("is-active", on);
      tab.setAttribute("aria-selected", String(on));
    });
    // The window keeps the wiki name in both acts: the quiz is drawn from it.
    if (title) title.textContent = t("about.mock_wiki");
  };

  let timer = null;
  const stop = () => {
    if (timer) clearInterval(timer);
    timer = null;
  };
  tabs.forEach((tab) =>
    tab.addEventListener("click", () => {
      stop();
      show(tab.dataset.studioTab);
    }),
  );

  show("wiki");
  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    timer = setInterval(() => show(studio.dataset.on === "wiki" ? "quiz" : "wiki"), 7000);
  }
}

function _artQuiz() {
  const set = MOCK_SETS[0];
  return `
    <div class="ld-window ld-mock-quiz" data-mock>
      <div class="ld-window-bar"><span></span><span></span><span></span><em>PIN 4KQ7RT</em></div>
      <div class="ld-window-body">
        <p class="ld-mock-question" data-mock-question>${escapeHtml(t(set.key))}</p>
        <div class="ld-bars">
          ${["A", "B", "C", "D"]
            .map(
              (letter, index) => `
          <div class="ld-bar"><span class="ld-bar-label">${letter}</span><i data-bar="${index}" data-h="${set.bars[index]}%"></i><b data-pct="${index}">${set.bars[index]}%</b></div>`,
            )
            .join("")}
        </div>
        <div class="ld-mock-foot"><span class="ld-dot"></span> <span data-mock-players>${set.players}</span> ${escapeHtml(t("about.mock_players"))}</div>
      </div>
    </div>`;
}

/** Cycle the hero mock: new question, new tallies, same window. */
function _startMockQuiz(root) {
  // Both views render their own mock; each one plays on its own.
  root.querySelectorAll("[data-mock]").forEach((mock) => _playMock(mock));
}

function _playMock(mock) {
  const question = mock.querySelector("[data-mock-question]");
  const players = mock.querySelector("[data-mock-players]");
  const bars = [...mock.querySelectorAll("[data-bar]")];
  const pcts = [...mock.querySelectorAll("[data-pct]")];
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // First frame: the bars are already at their value, the animation only runs
  // when the mock moves on to the next question.
  bars.forEach((bar) => {
    bar.style.width = bar.dataset.h || "0%";
  });
  let index = 0;
  const paint = (set) => {
    question.classList.add("is-swapping");
    bars.forEach((bar, i) => {
      bar.style.width = "0%";
    });
    window.setTimeout(() => {
      if (!document.body.contains(mock)) return;
      question.textContent = t(set.key);
      question.classList.remove("is-swapping");
      bars.forEach((bar, i) => {
        bar.dataset.h = `${set.bars[i]}%`;
        bar.style.width = `${set.bars[i]}%`;
        pcts[i].textContent = `${set.bars[i]}%`;
      });
      players.textContent = String(set.players);
    }, calm ? 0 : 420);
  };
  window.setInterval(() => {
    if (!document.body.contains(mock)) return;
    index = (index + 1) % MOCK_SETS.length;
    paint(MOCK_SETS[index]);
  }, 4200);
}

function _artFormats() {
  return `
    <div class="ld-formats">
      <article class="ld-format ld-format-swipe">
        <span class="ld-format-tag">${escapeHtml(t("editor.mode_swipe"))}</span>
        <div class="ld-swipe-card"><strong>${escapeHtml(t("about.mock_swipe"))}</strong>
          <div class="ld-swipe-actions"><span>✕</span><span>✓</span></div>
        </div>
      </article>
      <article class="ld-format ld-format-story">
        <span class="ld-format-tag">${escapeHtml(t("editor.mode_adventure"))}</span>
        <svg viewBox="0 0 180 120" class="ld-story" aria-hidden="true">
          <path d="M16 24h44v34h48V30h50" fill="none" stroke="currentColor" stroke-width="1.6" />
          <path d="M60 58v40h48" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="4 4" />
          <rect x="8" y="12" width="34" height="24" rx="6" />
          <rect x="52" y="46" width="34" height="24" rx="6" />
          <rect x="98" y="18" width="34" height="24" rx="6" />
          <rect x="112" y="86" width="34" height="24" rx="6" />
        </svg>
      </article>
      <article class="ld-format ld-format-poll">
        <span class="ld-format-tag">${escapeHtml(t("editor.mode_poll"))}</span>
        <div class="ld-poll">
          <div><i data-h="64%"></i><span>64%</span></div>
          <div><i data-h="36%"></i><span>36%</span></div>
        </div>
      </article>
    </div>`;
}

function _artWiki() {
  return `
    <div class="ld-window ld-window-wiki">
      <div class="ld-window-bar"><span></span><span></span><span></span><em>${escapeHtml(t("about.mock_wiki"))}</em></div>
      <div class="ld-window-body ld-wiki-body">
        <aside class="ld-wiki-nav">
          <span class="is-on"></span><span></span><span class="is-sub"></span><span></span><span class="is-sub"></span>
        </aside>
        <div class="ld-wiki-doc">
          <h4></h4>
          <p></p><p class="short"></p>
          <h5></h5>
          <p></p><p class="short"></p>
          <div class="ld-diff">
            <span class="add">+ ${escapeHtml(t("about.mock_added"))}</span>
            <span class="del">− ${escapeHtml(t("about.mock_removed"))}</span>
          </div>
        </div>
      </div>
    </div>`;
}

function _artCollab() {
  return `
    <div class="ld-window ld-window-collab">
      <div class="ld-window-bar"><span></span><span></span><span></span><em>${escapeHtml(t("about.mock_live"))}</em></div>
      <div class="ld-window-body ld-collab-body">
        <p></p><p><span class="ld-caret c-one"></span></p><p class="short"></p>
        <p><span class="ld-caret c-two"></span></p>
        <div class="ld-avatars">
          <span class="a">AL</span><span class="b">MB</span><span class="c">JS</span>
        </div>
      </div>
    </div>`;
}

function _artChat() {
  return `
    <div class="ld-chat">
      <div class="ld-chat-head"><span aria-hidden="true">✨</span> ${escapeHtml(t("wiki.ask"))}</div>
      <div class="ld-bubble me">${escapeHtml(t("about.mock_ask"))}</div>
      <div class="ld-bubble ai">
        ${escapeHtml(t("about.mock_answer"))}
        <span class="ld-source">1</span><span class="ld-source">2</span>
      </div>
      <div class="ld-bubble me short">${escapeHtml(t("about.mock_followup"))}</div>
      <div class="ld-typing"><span></span><span></span><span></span></div>
    </div>`;
}

function _artHost() {
  return `
    <div class="ld-window ld-window-host">
      <div class="ld-window-bar"><span></span><span></span><span></span><em>${escapeHtml(t("about.mock_deploy"))}</em></div>
      <div class="ld-window-body ld-host-body">
        <div class="ld-terminal">
          <p><b>$</b> docker compose up -d</p>
          <p class="ok">✓ openlearn</p>
          <p class="ok">✓ nginx · TLS</p>
          <p class="ok">✓ sqlite</p>
          <p class="cursor">_</p>
        </div>
        <div class="ld-shield"><span>🔒</span>${escapeHtml(t("about.mock_no_cloud"))}</div>
      </div>
    </div>`;
}

/* The seventh scene: a page read by something other than a pair of eyes.
   A focus ring on a link, the keys that got there, and the announcement a
   screen reader makes — the three things an accessibility statement promises. */
function _artAccess() {
  return `
    <div class="ld-window ld-window-a11y">
      <div class="ld-window-bar"><span></span><span></span><span></span><em>${escapeHtml(t("about.mock_a11y_bar"))}</em></div>
      <div class="ld-window-body ld-a11y-body">
        <div class="ld-a11y-doc">
          <p class="ld-a11y-line long"></p>
          <p class="ld-a11y-line"></p>
          <span class="ld-a11y-link">${escapeHtml(t("about.mock_a11y_link"))}</span>
          <p class="ld-a11y-line short"></p>
          <p class="ld-a11y-sr"><span aria-hidden="true">🔊</span> ${escapeHtml(t("about.mock_a11y_sr"))}</p>
        </div>
        <div class="ld-a11y-side">
          <span class="ld-a11y-key">Tab</span>
          <span class="ld-a11y-key">⏎</span>
          <span class="ld-a11y-pos is-ok">AA</span>
          <span class="ld-a11y-pos">4.9:1</span>
        </div>
      </div>
    </div>`;
}

function _art(kind) {
  if (kind === "quiz") return _artQuiz();
  if (kind === "formats") return _artFormats();
  if (kind === "wiki") return _artWiki();
  if (kind === "collab") return _artCollab();
  if (kind === "chat") return _artChat();
  if (kind === "access") return _artAccess();
  return _artHost();
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export function renderAbout() {
  const root = document.createElement("section");
  root.className = "landing";

  const scenes = SCENES.map(
    (scene, index) => `
    <section class="ld-scene ${scene.side === "right" ? "ld-scene-right" : ""} ${
      scene.highlight ? "ld-scene-ai" : ""
    }" data-scene="${scene.key}" id="decouvrir-${scene.key}">
      <div class="ld-scene-text">
        <p class="ld-step" data-reveal>${String(index + 1).padStart(2, "0")}</p>
        ${
          scene.highlight
            ? `<p class="ld-ai-badge" data-reveal><span aria-hidden="true">✨</span> ${escapeHtml(t("about.ai_badge"))}</p>`
            : ""
        }
        <h2 data-reveal>${escapeHtml(t(`about.ch_${scene.key}_title`))} ${_anchor(`decouvrir-${scene.key}`)}</h2>
        <p class="ld-lead" data-reveal>${escapeHtml(t(`about.ch_${scene.key}_lead`))}</p>
        <ul class="ld-points">
          ${["b1", "b2", "b3"]
            .map((bullet) => {
              const text = t(`about.ch_${scene.key}_${bullet}`);
              return text && !text.startsWith("about.")
                ? `<li data-reveal>${escapeHtml(text)}</li>`
                : "";
            })
            .join("")}
        </ul>
      </div>
      <div class="ld-scene-art" data-reveal data-parallax>${_art(scene.art)}</div>
    </section>`,
  ).join("");

  const discoverHtml = `
    <div class="ld-progress" aria-hidden="true"><span id="ld-bar"></span></div>

    <section class="ld-hero ld-hero-problem">
      <div class="ld-aurora" aria-hidden="true"><span></span><span></span><span></span></div>
      ${_starCorner()}
      <div class="ld-hero-text">
        <p class="ld-eyebrow" data-reveal>${escapeHtml(t("about.eyebrow_problem"))}</p>
        <h1 data-reveal>
          ${escapeHtml(t("about.hero_title_a"))}<br />
          <span class="ld-rotator" data-rotator>
            ${/* Every rotating word is laid out in the same grid cell, hidden: the
                 tallest one sets the height of the headline, so typing never
                 moves the boxes below. */""}
            ${[1, 2, 3, 4]
              .map(
                (index) =>
                  `<span class="ld-rot-sizer" aria-hidden="true">${escapeHtml(t(`about.rotate_${index}`))}</span>`,
              )
              .join("")}
            <span class="ld-rot-live"><span data-rot-word>${escapeHtml(t("about.rotate_1"))}</span><i class="ld-caret" aria-hidden="true"></i></span>
          </span>
        </h1>
        <div class="ld-problem" data-reveal>
          <span class="ld-box-icon" aria-hidden="true">${_icon("alert")}</span>
          <div>
            <p class="ld-problem-tag">${escapeHtml(t("about.problem_label"))}</p>
            <p>${escapeHtml(t("about.problem_text"))}</p>
          </div>
        </div>
        <div class="ld-solution" data-reveal>
          <span class="ld-box-icon" aria-hidden="true">${_icon("bulb")}</span>
          <div>
            <p class="ld-solution-tag">${escapeHtml(t("about.solution_label"))}</p>
            <p>${escapeHtml(t("about.solution_text"))}</p>
          </div>
        </div>
        <p class="hint" data-reveal>${escapeHtml(t("about.trust_line"))}</p>
        ${/* Only shown on a phone, where the page clearly continues below. */""}
        <a class="ld-scroll-cue" href="#ld-start" aria-hidden="true" tabindex="-1"><span></span></a>
      </div>
      <div class="ld-hero-art" data-reveal>${_artStudio()}</div>
    </section>

    ${_switchHtml()}

    <section class="ld-stats" id="ld-start">
      ${STATS.map(
        (stat) => `
        <div class="ld-stat" data-reveal>
          <span class="ld-stat-icon" aria-hidden="true">${_icon(stat.icon)}</span>
          <strong data-count="${stat.value}" data-suffix="${stat.suffix}">0${stat.suffix}</strong>
          <span>${escapeHtml(t(stat.key))}</span>
        </div>`,
      ).join("")}
    </section>

    <div class="ld-scenes">${scenes}</div>

    <section class="ld-steps" id="decouvrir-etapes">
      <h2 data-reveal>${escapeHtml(t("about.steps_title"))} ${_anchor("decouvrir-etapes")}</h2>
      <ol class="ld-step-list">
        ${[1, 2, 3]
          .map(
            (number) => `
          <li data-reveal>
            <span class="ld-step-num">${number}</span>
            <strong>${escapeHtml(t(`about.step${number}_title`))}</strong>
            <p>${escapeHtml(t(`about.step${number}_body`))}</p>
          </li>`,
          )
          .join("")}
      </ol>
    </section>

    <section class="ld-final" id="decouvrir-commencer">
      <div class="ld-final-inner" data-reveal>
        <h2>${escapeHtml(t("about.final_title"))}</h2>
        <p>${escapeHtml(t("about.final_body"))}</p>
        <div class="row-wrap ld-final-actions">${_finalCta()}</div>
      </div>
    </section>`;

  root.innerHTML = `
    <div data-view="discover">${discoverHtml}</div>
    <div data-view="pro" hidden>${_switchHtml()}${_proHtml()}</div>
    <div data-view="security" hidden>${_switchHtml()}${_secHtml()}</div>`;

  const select = _bindTabs(root);
  _bindAnchors(root, select);
  _animate(root);
  _startRotator(root);
  _startMockQuiz(root);
  _startStudio(root);
  return root;
}

/* -------------------------------------------------------------------------- */
/* "For professionals": the same platform, read as a training tool            */
/* -------------------------------------------------------------------------- */

const PRO_CARDS = [
  { key: "mooc", icon: "🎓" },
  { key: "wiki", icon: "📚" },
  { key: "learn", icon: "🧭" },
  { key: "eval", icon: "✅" },
];

function _proHtml() {
  return `
    <section class="ld-hero pro-hero">
      <div class="ld-aurora" aria-hidden="true"><span></span><span></span><span></span></div>
      <div class="ld-hero-text">
        <p class="ld-eyebrow" data-reveal>${escapeHtml(t("about.pro_eyebrow"))}</p>
        <h2 class="ld-hero-title" data-reveal>${escapeHtml(t("about.pro_title"))} ${_anchor("pro")}</h2>
        <p class="ld-lead" data-reveal>${escapeHtml(t("about.pro_lead"))}</p>
        <ul class="ld-hero-points" data-reveal>
          <li><span aria-hidden="true">✦</span> ${escapeHtml(t("about.pro_point_free"))}</li>
          <li><span aria-hidden="true">✦</span> ${escapeHtml(t("about.pro_point_tiers"))}</li>
          <li><span aria-hidden="true">✦</span> ${escapeHtml(t("about.pro_point_data"))}</li>
        </ul>
        <div class="row-wrap mt-2" data-reveal>${_cta()}</div>
      </div>
      <div class="ld-hero-art" data-reveal>${_artHost()}</div>
    </section>

    <section class="pro-cards" id="pro-cartes">
      ${PRO_CARDS.map(
        (card) => `
        <article class="pro-card" data-reveal id="pro-${card.key}">
          <span class="pro-icon" aria-hidden="true">${card.icon}</span>
          <h2>${escapeHtml(t(`about.pro_${card.key}_title`))} ${_anchor(`pro-${card.key}`)}</h2>
          <p>${escapeHtml(t(`about.pro_${card.key}_body`))}</p>
          <ul class="ld-points">
            ${["b1", "b2", "b3"]
              .map((bullet) => {
                const text = t(`about.pro_${card.key}_${bullet}`);
                return text && !text.startsWith("about.") ? `<li>${escapeHtml(text)}</li>` : "";
              })
              .join("")}
          </ul>
        </article>`,
      ).join("")}
    </section>

    <section class="pro-free" id="pro-gratuit">
      <div class="pro-free-inner" data-reveal>
        <p class="ld-ai-badge"><span aria-hidden="true">✨</span> ${escapeHtml(t("about.pro_free_badge"))}</p>
        <h2>${escapeHtml(t("about.pro_free_title"))}</h2>
        <p>${escapeHtml(t("about.pro_free_body"))}</p>
      </div>
    </section>`;
}

/* -------------------------------------------------------------------------- */
/* "Security — for IT and CISOs": the architecture choices, stated plainly     */
/* -------------------------------------------------------------------------- */

const SEC_CARDS = ["tests", "deploy", "database", "identity", "offline", "operations"];
const SEC_NOTES = ["roles", "audit", "backup", "licence", "a11y"];

function _secArt() {
  return `
    <div class="ld-window ld-window-sec">
      <div class="ld-window-bar"><span></span><span></span><span></span><em>${escapeHtml(t("about.sec_art_bar"))}</em></div>
      <div class="ld-window-body ld-sec-body">
        <div class="ld-terminal">
          <p><b>$</b> ${escapeHtml(t("about.sec_art_cmd"))}</p>
          <p class="ok">✓ ${escapeHtml(t("about.sec_art_db"))}</p>
          <p class="ok">✓ ${escapeHtml(t("about.sec_art_sso"))}</p>
          <p class="ok">✓ ${escapeHtml(t("about.sec_art_tests"))}</p>
          <p class="cursor">_</p>
        </div>
        <div class="ld-shield"><span aria-hidden="true">🔒</span>${escapeHtml(t("about.sec_art_offline"))}</div>
      </div>
    </div>`;
}

function _secHtml() {
  return `
    <section class="ld-hero sec-hero">
      <div class="ld-aurora" aria-hidden="true"><span></span><span></span><span></span></div>
      <div class="ld-hero-text">
        <p class="ld-eyebrow" data-reveal>${escapeHtml(t("about.sec_eyebrow"))}</p>
        <h2 class="ld-hero-title" data-reveal>${escapeHtml(t("about.sec_title"))} ${_anchor("securite")}</h2>
        <p class="ld-lead" data-reveal>${escapeHtml(t("about.sec_lead"))}</p>
        <ul class="ld-hero-points" data-reveal>
          ${SEC_HERO_POINTS.map(
            (point) => `<li><span aria-hidden="true">✦</span> ${escapeHtml(t(`about.sec_point_${point}`))}</li>`,
          ).join("")}
        </ul>
      </div>
      <div class="ld-hero-art" data-reveal>${_secArt()}</div>
    </section>

    <section class="sec-stack" id="securite-choix">
      ${SEC_CARDS.map(
        (card, index) => `
        <article class="sec-block" id="securite-${card}" data-reveal>
          <p class="sec-block-num" aria-hidden="true">${String(index + 1).padStart(2, "0")}</p>
          <div class="sec-block-text">
            <h2>
              <span class="sec-block-icon" aria-hidden="true">${SEC_ICONS[card]}</span>
              ${escapeHtml(t(`about.sec_${card}_title`))} ${_anchor(`securite-${card}`)}
            </h2>
            <p>${escapeHtml(t(`about.sec_${card}_body`))}</p>
          </div>
        </article>`,
      ).join("")}
    </section>

    <section class="pro-free" id="securite-controle">
      <div class="pro-free-inner sec-notes" data-reveal>
        <h2>${escapeHtml(t("about.sec_notes_title"))} ${_anchor("securite-controle")}</h2>
        <ul class="sec-notes-list">
          ${SEC_NOTES.map(
            (note) => `<li><strong>${escapeHtml(t(`about.sec_note_${note}_title`))}</strong> ${escapeHtml(t(`about.sec_note_${note}_body`))}</li>`,
          ).join("")}
        </ul>
        <p class="muted">${escapeHtml(t("about.sec_closing"))}</p>
      </div>
    </section>`;
}

const SEC_HERO_POINTS = ["code", "outbound", "data"];
const SEC_ICONS = {
  tests: "🧪",
  deploy: "📦",
  database: "🗄",
  identity: "🔑",
  offline: "🔌",
  operations: "🛠",
};

/** Three views, one page: the story, the training tool, the infrastructure. */
function _bindTabs(root) {
  const tabs = [...root.querySelectorAll(".ld-switch-btn")];
  const views = {
    discover: root.querySelector('[data-view="discover"]'),
    pro: root.querySelector('[data-view="pro"]'),
    security: root.querySelector('[data-view="security"]'),
  };
  const hashes = { pro: "#pro", security: "#securite" };
  const select = (name, { keepHash = false } = {}) => {
    tabs.forEach((tab) => {
      const active = tab.dataset.tab === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    Object.entries(views).forEach(([key, node]) => {
      if (node) node.hidden = key !== name;
    });
    if (!keepHash) window.history.replaceState({}, "", hashes[name] || location.pathname);
    if (name !== "discover") _animate(root);
  };
  tabs.forEach((tab) => tab.addEventListener("click", () => select(tab.dataset.tab)));
  if (location.hash === "#pro") select("pro");
  if (location.hash === "#securite") select("security");
  return select;
}

/* A block can be addressed and copied on its own.
 *
 * ``#securite-database`` opens the page on the database choice, in the right
 * view, scrolled there — so the link a reader sends means something to someone
 * who has never seen the page. The button copies that address.
 */
function _bindAnchors(root, select) {
  const open = (smooth) => {
    const id = decodeURIComponent(location.hash.replace(/^#/, ""));
    if (!id) return;
    const target = root.querySelector(`[id="${id}"]`);
    if (!target) return;
    const view = target.closest("[data-view]");
    if (view && view.hidden) select(view.dataset.view, { keepHash: true });
    target.scrollIntoView({
      block: "start",
      behavior: smooth && !window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "smooth"
        : "auto",
    });
  };

  root.querySelectorAll("[data-anchor]").forEach((link) => {
    link.addEventListener("click", async (event) => {
      event.preventDefault();
      const id = link.dataset.anchor;
      const url = `${location.origin}${location.pathname}#${id}`;
      window.history.replaceState({}, "", `#${id}`);
      try {
        await navigator.clipboard.writeText(url);
        toast(t("about.anchor_copied"), "success");
      } catch {
        // No clipboard (insecure context, refused permission): the address bar
        // already carries the address, which is what the reader wanted.
        toast(url, "info");
      }
    });
  });

  // The browser restores the scroll position after the view is shown: run once
  // after mount, then on every later change of address.
  window.requestAnimationFrame(() => open(false));
  window.addEventListener("hashchange", () => open(true));
}

/** Reveal on scroll, count the figures, drive the progress bar and parallax. */
function _animate(root) {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const revealables = [...root.querySelectorAll("[data-reveal]")];

  if (reduced || !("IntersectionObserver" in window)) {
    revealables.forEach((node) => node.classList.add("is-in"));
    root.querySelectorAll("[data-count]").forEach((node) => {
      node.textContent = `${node.dataset.count}${node.dataset.suffix || ""}`;
    });
    return;
  }

  // A scene reveals as a group: the text lines arrive one after the other.
  revealables.forEach((node) => {
    const siblings = [...(node.parentElement ? node.parentElement.children : [])].filter((child) =>
      child.hasAttribute("data-reveal"),
    );
    const order = Math.max(0, siblings.indexOf(node));
    node.style.setProperty("--d", `${Math.min(order * 90, 540)}ms`);
  });

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("is-in");
        const counter = entry.target.querySelector("[data-count]");
        if (counter) _count(counter);
        observer.unobserve(entry.target);
        // Bars and poll fills animate from zero once their card is on screen.
        entry.target.querySelectorAll("[data-h]").forEach((bar) => {
          bar.style.width = bar.dataset.h;
        });
      }
    },
    { rootMargin: "0px 0px -12% 0px", threshold: 0.18 },
  );
  revealables.forEach((node) => observer.observe(node));

  const bar = root.querySelector("#ld-bar");
  let ticking = false;
  const onScroll = () => {
    // The page is gone: stop listening rather than updating a detached node.
    if (!document.body.contains(root)) {
      window.removeEventListener("scroll", onScroll);
      return;
    }
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(() => {
      const scrollable = document.documentElement.scrollHeight - window.innerHeight;
      const ratio = scrollable > 0 ? Math.min(1, Math.max(0, window.scrollY / scrollable)) : 0;
      if (bar) bar.style.width = `${ratio * 100}%`;
      root.querySelectorAll("[data-parallax]").forEach((node) => {
        const box = node.getBoundingClientRect();
        // A gentle counter-motion: the mock drifts slower than the text.
        const offset = (box.top + box.height / 2 - window.innerHeight / 2) * -0.035;
        node.style.setProperty("--ldy", `${offset.toFixed(1)}px`);
      });
      ticking = false;
    });
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
}

function _count(node) {
  const target = Number(node.dataset.count) || 0;
  const suffix = node.dataset.suffix || "";
  if (!target) {
    node.textContent = `0${suffix}`;
    return;
  }
  const started = performance.now();
  const duration = 900;
  const tick = (now) => {
    const progress = Math.min(1, (now - started) / duration);
    const eased = 1 - (1 - progress) ** 3;
    node.textContent = `${Math.round(target * eased)}${suffix}`;
    if (progress < 1) window.requestAnimationFrame(tick);
  };
  window.requestAnimationFrame(tick);
}

/** The headline rotates through what knowledge does: shared, it grows. */
function _startRotator(root) {
  const host = root.querySelector("[data-rotator]");
  const word = root.querySelector("[data-rot-word]");
  if (!host || !word) return;
  const words = [1, 2, 3, 4].map((index) => t(`about.rotate_${index}`)).filter(Boolean);
  if (words.length < 2) return;

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    // No typing animation: the words still change, without motion.
    let index = 0;
    const still = setInterval(() => {
      if (!document.body.contains(host)) {
        clearInterval(still);
        return;
      }
      index = (index + 1) % words.length;
      word.textContent = words[index];
    }, 4200);
    return;
  }

  let index = 0;
  let position = words[0].length;
  let deleting = true;
  const step = () => {
    if (!document.body.contains(host)) return; // the page was left
    const target = words[index];
    if (deleting) {
      position -= 1;
      word.textContent = target.slice(0, Math.max(0, position));
      if (position <= 0) {
        deleting = false;
        index = (index + 1) % words.length;
        position = 0;
        setTimeout(step, 260);
        return;
      }
      setTimeout(step, 38);
    } else {
      const next = words[index];
      position += 1;
      word.textContent = next.slice(0, position);
      if (position >= next.length) {
        deleting = true;
        setTimeout(step, 2400);
        return;
      }
      setTimeout(step, 62);
    }
  };
  setTimeout(step, 2600);
}
