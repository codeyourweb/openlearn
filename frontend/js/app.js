// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Application bootstrap: routes, chrome (nav/session box), language and theme. */

import { api, ensureCsrf } from "./api.js";
import { currentLanguage, LANGUAGES, onLanguageChange, setLanguage, t } from "./i18n.js";
import { navigate, register, render, setAfterRender, start } from "./router.js";
import { setUser, state } from "./store.js";
import { applyTheme, currentTheme, toggleTheme } from "./theme.js";
import { flagSvg } from "./flags.js";
import { escapeHtml, toast } from "./ui.js";

import { renderAccount } from "./pages/account.js";
import { renderAdmin } from "./pages/admin.js";
import { renderAdventureEditor } from "./pages/adventureEditor.js";
import { renderAdventurePlay } from "./pages/adventurePlay.js";
import { renderLogin, renderRegister } from "./pages/auth.js";
import { renderDashboard } from "./pages/dashboard.js";
import { renderEditor } from "./pages/editor.js";
import { renderEvalInvite } from "./pages/evalInvite.js";
import { renderHome } from "./pages/home.js";
import { renderHost } from "./pages/host.js";
import { renderJoin } from "./pages/join.js";
import { renderDocs } from "./pages/apiDocs.js";
import { renderMcpDocs } from "./pages/mcpDocs.js";
import { renderNewQuiz, renderNewQuizMethod } from "./pages/newQuiz.js";
import { renderPlay } from "./pages/play.js";
import { renderQuizDetail } from "./pages/quizDetail.js";
import { renderResults } from "./pages/results.js";
import { renderAbout } from "./pages/about.js";
import { renderAccessibility } from "./pages/accessibility.js";
import { renderLegal } from "./pages/legal.js";
import { renderWiki, renderWikiCreate, renderWikiHistory, renderWikiHome } from "./pages/wiki.js";
import { renderWikiChat } from "./pages/wikiChat.js";
import { renderWikiEditor } from "./pages/wikiEditor.js";
import { renderWikiGraph } from "./pages/wikiGraph.js";
import { renderWikiStructure } from "./pages/wikiStructure.js";
import { renderWikiReferences } from "./pages/wikiReferences.js";
import { renderWikiTemplates } from "./pages/wikiTemplates.js";
import { renderCards } from "./pages/cards.js";
import { renderResetPassword } from "./pages/passwordReset.js";
import { renderVerificationBanner, renderVerifyEmail } from "./pages/verifyEmail.js";
import { defaultRoute, instance, loadInstance } from "./instance.js";
import { renderDeck, renderDeckStudy } from "./pages/cardsDeck.js";

/* The entry page depends on the instance: a demo instance presents the project,
   a private one opens directly on the knowledge it hosts. */
register("/", () => (instance().demo_mode ? renderAbout() : renderWikiHome()));
register("/quizzes", renderHome);
register("/e/:token", renderEvalInvite);
register("/login", renderLogin);
register("/reset/:token", renderResetPassword);
register("/forgot", renderResetPassword);
register("/verify/:token", renderVerifyEmail);
register("/register", renderRegister);
register("/dashboard", renderDashboard);
register("/quizzes/new", renderNewQuiz);
register("/quizzes/new/:mode", renderNewQuizMethod);
register("/quizzes/new/:mode/:variant", renderEditor);
register("/quizzes/:id/edit", renderEditor);
register("/quizzes/:id", renderQuizDetail);
// Canonical, keyword-bearing form of the same page.
register("/quizzes/:id/:slug", renderQuizDetail);
register("/adventures/new", renderAdventureEditor);
register("/adventures/:id/edit", renderAdventureEditor);
register("/adventures/:id/play", renderAdventurePlay);
register("/play/:code", renderPlay);
register("/host/:code", renderHost);
register("/results/:code", renderResults);
register("/join/:token", renderJoin);
register("/account", renderAccount);
register("/admin", renderAdmin);
register("/docs", renderDocs);
register("/docs/mcp", renderMcpDocs);
register("/about", renderAbout);
register("/legal", renderLegal);
register("/accessibility", renderAccessibility);
/* Static wiki routes first: the router matches on segment count and order. */
register("/wiki", renderWikiHome);
register("/wiki/new", renderWikiCreate);
register("/wiki/chat", renderWikiChat);
register("/wiki/:id", renderWiki);
register("/wiki/:id/p/:slug", renderWiki);
register("/wiki/:id/edit", renderWikiEditor);
register("/wiki/:id/edit/:pageId", renderWikiEditor);
register("/wiki/:id/propose/:pageId", renderWikiEditor);
register("/wiki/:id/history/:pageId", renderWikiHistory);
register("/wiki/:id/graph", renderWikiGraph);
register("/wiki/:id/structure", renderWikiStructure);
register("/wiki/:id/references", renderWikiReferences);
register("/wiki/:id/templates", renderWikiTemplates);
// Canonical form with the wiki slug; registered after the fixed sub-pages so
// "/wiki/12/edit" keeps landing on the editor.
register("/wiki/:id/:slug", renderWiki);

register("/cards", renderCards);
register("/cards/:id/study", renderDeckStudy);
register("/cards/:id", renderDeck);

/** Fill every element carrying a data-i18n key with the current translation. */
function applyTranslations(scope = document) {
  scope.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  // Attributes carry translatable text too: a tooltip is as user-facing as a label.
  scope.querySelectorAll("[data-i18n-title]").forEach((node) => {
    node.title = t(node.dataset.i18nTitle);
  });
  scope.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  });
  const skip = document.getElementById("skip-link");
  if (skip) skip.textContent = t("a11y.skip");
  const footer = document.getElementById("footer-tagline");
  if (footer) footer.textContent = t("footer.tagline");
  document.title = t("app.name");
}

function buildLanguagePicker() {
  const picker = document.getElementById("language-picker");
  const button = document.getElementById("language-button");
  const menu = document.getElementById("language-menu");
  const flagSlot = document.getElementById("language-button-flag");
  const labelSlot = document.getElementById("language-button-label");
  if (!picker || !button || !menu) return;

  menu.innerHTML = LANGUAGES.map(
    (language) => `
      <li role="option" aria-selected="false">
        <button type="button" class="lang-option" data-language="${language.code}"
                role="option" aria-selected="false">
          ${flagSvg(language.code)}
          <span>${escapeHtml(language.label)}</span>
          <svg class="lang-check" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
            <path d="M2 6.4l2.6 2.6L10 3.4" fill="none" stroke="currentColor" stroke-width="1.8"
                  stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
      </li>`,
  ).join("");

  const paintCurrent = () => {
    const code = currentLanguage();
    const language = LANGUAGES.find((item) => item.code === code) || LANGUAGES[0];
    flagSlot.innerHTML = flagSvg(language.code);
    labelSlot.textContent = language.label;
    button.setAttribute("aria-label", `${t("common.language")}: ${language.label}`);
    menu.querySelectorAll("[data-language]").forEach((option) => {
      const selected = option.dataset.language === language.code;
      option.setAttribute("aria-selected", String(selected));
      option.closest("li").setAttribute("aria-selected", String(selected));
    });
  };

  const close = (focusButton = false) => {
    menu.hidden = true;
    button.setAttribute("aria-expanded", "false");
    picker.classList.remove("is-open");
    if (focusButton) button.focus();
  };
  const open = () => {
    menu.hidden = false;
    button.setAttribute("aria-expanded", "true");
    picker.classList.add("is-open");
    const current = menu.querySelector('[aria-selected="true"]');
    (current || menu.querySelector("[data-language]")).focus();
  };

  button.addEventListener("click", () => (menu.hidden ? open() : close()));
  menu.addEventListener("click", (event) => {
    const option = event.target.closest("[data-language]");
    if (!option) return;
    setLanguage(option.dataset.language);
    paintCurrent();
    close(true);
  });
  picker.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !menu.hidden) {
      event.preventDefault();
      close(true);
    }
  });
  document.addEventListener("click", (event) => {
    if (!menu.hidden && !picker.contains(event.target)) close();
  });

  paintCurrent();
  onLanguageChange(() => paintCurrent());
}

/** Two letters for the avatar: a face is quicker to find than a name. */
function _initials(name) {
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  const first = parts[0][0] || "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase();
}

/* One icon in the bar, one popover behind it: sign in, sign up, account,
   administration and sign out all live there instead of taking five links of
   horizontal room in the navigation. */
function renderChrome() {
  const box = document.getElementById("session-box");
  const nav = document.getElementById("nav");
  if (!box || !nav) return;

  nav.querySelectorAll("a").forEach((link) => {
    const path = link.getAttribute("href");
    link.classList.toggle("active", path === "/" ? location.pathname === "/" : location.pathname.startsWith(path));
  });

  const signedIn = Boolean(state.user);
  const label = signedIn ? state.user.display_name : t("nav.signin");
  box.innerHTML = `
    <div class="account-menu" id="account-menu">
      <button class="account-button" id="account-button" type="button"
              aria-haspopup="menu" aria-expanded="false" aria-controls="account-popover"
              title="${escapeHtml(signedIn ? state.user.email : t("nav.account"))}"
              aria-label="${escapeHtml(t("a11y.account_menu"))}">
        ${
          signedIn
            ? `<span class="account-avatar">${escapeHtml(_initials(state.user.display_name))}</span>`
            : `<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                 <circle cx="10" cy="6.4" r="3.4" fill="none" stroke="currentColor" stroke-width="1.7" />
                 <path d="M3.6 17c0-3.3 2.9-5.4 6.4-5.4s6.4 2.1 6.4 5.4" fill="none" stroke="currentColor"
                       stroke-width="1.7" stroke-linecap="round" />
               </svg>`
        }
      </button>
      <div class="account-popover" id="account-popover" role="menu" hidden>
        <p class="account-popover-head">${escapeHtml(label)}</p>
        ${
          signedIn
            ? `<a class="account-item" role="menuitem" href="/account" data-link>${t("nav.account")}</a>
               ${state.user.is_staff ? `<a class="account-item" role="menuitem" href="/admin" data-link>${t("nav.admin")}</a>` : ""}
               <button class="account-item account-signout" role="menuitem" type="button" id="logout-button">${t("nav.signout")}</button>`
            : `<a class="account-item" role="menuitem" href="/login" data-link>${t("nav.signin")}</a>
               <a class="account-item is-primary" role="menuitem" href="/register" data-link>${t("nav.signup")}</a>`
        }
      </div>
    </div>`;

  const menu = box.querySelector("#account-menu");
  const button = box.querySelector("#account-button");
  const popover = box.querySelector("#account-popover");
  const close = (focus = false) => {
    popover.hidden = true;
    button.setAttribute("aria-expanded", "false");
    menu.classList.remove("is-open");
    if (focus) button.focus();
  };
  const open = () => {
    popover.hidden = false;
    button.setAttribute("aria-expanded", "true");
    menu.classList.add("is-open");
    (popover.querySelector('[role="menuitem"]') || popover).focus?.();
  };
  button.addEventListener("click", () => (popover.hidden ? open() : close()));
  menu.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !popover.hidden) {
      event.preventDefault();
      close(true);
    }
  });
  document.addEventListener("click", (event) => {
    if (!popover.hidden && !menu.contains(event.target)) close();
  });
  // A navigation link inside the popover leaves the menu behind it otherwise.
  popover.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => close()));

  const logout = box.querySelector("#logout-button");
  if (logout) {
    logout.addEventListener("click", async () => {
      try {
        await api.post("/api/v1/auth/logout", undefined);
      } catch {
        /* the cookie is cleared client side anyway */
      }
      setUser(null);
      renderChrome();
      toast(t("auth.logged_out"));
      navigate("/");
    });
  }
}

setAfterRender(() => {
  applyTranslations();
  renderChrome();
  renderVerificationBanner(document.getElementById("app"));
  // Canvas pages and live sessions use the full width of a large screen.
  const container = document.querySelector("main");
  if (container) {
    const wide =
      location.pathname === "/" ||
      /^(\/adventures\/.+\/edit|\/quizzes\/[^/]+\/edit|\/quizzes\/new|\/host\/|\/play\/|\/wiki\/[^/]+\/(edit|propose|new|graph|structure|references|templates)|\/wiki\/chat|\/about)/.test(
        location.pathname,
      );
    container.classList.toggle("is-wide", wide);
  }
});
window.addEventListener("oq:auth-changed", renderChrome);

/* Sticky bars below the header need its real height: it wraps on narrow
   screens, so the value is measured instead of guessed. */
function measureTopbar() {
  const bar = document.querySelector(".topbar");
  if (!bar) return;
  document.documentElement.style.setProperty("--topbar-h", `${Math.round(bar.getBoundingClientRect().height)}px`);
}
setAfterRender(measureTopbar);
window.addEventListener("resize", measureTopbar);

onLanguageChange(() => {
  applyTranslations();
  renderChrome();
  syncChromeLabels();
  const select = document.getElementById("language-select");
  if (select) select.value = currentLanguage();
  // Re-render the current page so its strings follow the new language.
  render();
});

/* The glyph on the theme button says nothing to a screen reader, and "Switch
   between light and dark" does not say what a click will do next. */
function labelTheme() {
  const button = document.getElementById("theme-toggle");
  if (!button) return;
  const light = currentTheme() === "light";
  button.textContent = light ? "☀" : "◐";
  button.setAttribute("aria-label", t(light ? "a11y.theme_to_dark" : "a11y.theme_to_light"));
}

function syncChromeLabels() {
  const nav = document.getElementById("nav");
  if (nav) nav.setAttribute("aria-label", t("a11y.main_nav"));
  labelTheme();
}

async function boot() {
  applyTheme(currentTheme());
  await loadInstance();
  const aboutLink = document.querySelector('[data-nav="about"]');
  if (aboutLink) aboutLink.hidden = !instance().demo_mode;
  const nameSlot = document.querySelector("[data-instance-name]");
  if (nameSlot && instance().name && instance().name !== "OpenLearn") {
    nameSlot.textContent = instance().name;
  }
  buildLanguagePicker();
  applyTranslations();
  const themeButton = document.getElementById("theme-toggle");
  if (themeButton && !themeButton.dataset.wired) {
    themeButton.dataset.wired = "1";
    themeButton.addEventListener("click", () => {
      toggleTheme();
      labelTheme();
    });
  }
  syncChromeLabels();
  await ensureCsrf();
  try {
    setUser(await api.get("/api/v1/auth/me"));
  } catch {
    setUser(null);
  }
  renderChrome();
  start();
}

boot();
