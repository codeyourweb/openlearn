// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Minimal history-API router (no dependency). */

const routes = [];
let afterRender = () => {};

export function setAfterRender(fn) {
  afterRender = typeof fn === "function" ? fn : () => {};
}

export function register(pattern, handler) {
  const segments = pattern.split("/").filter(Boolean);
  routes.push({ segments, handler, pattern });
}

export function currentPath() {
  return location.pathname + location.search;
}

function matchRoute(pathname) {
  const parts = pathname.split("/").filter(Boolean);
  for (const route of routes) {
    if (route.segments.length !== parts.length) continue;
    const params = {};
    let ok = true;
    for (let i = 0; i < route.segments.length; i += 1) {
      const segment = route.segments[i];
      if (segment.startsWith(":")) {
        params[segment.slice(1)] = decodeURIComponent(parts[i]);
      } else if (segment !== parts[i]) {
        ok = false;
        break;
      }
    }
    if (ok) return { route, params };
  }
  return null;
}

/* A view change has to be announced: a screen reader would otherwise stay in
   the previous document, and a keyboard user would keep the focus on a link that
   no longer exists on screen. The flag is set by user-driven navigations only, so
   the first paint does not steal the focus. */
let focusPending = false;

function sectionOf(pathname) {
  const link = [...document.querySelectorAll("#nav a[data-link]")].find((candidate) => {
    const href = candidate.getAttribute("href") || "";
    return pathname === href || pathname.startsWith(`${href}/`);
  });
  for (const candidate of document.querySelectorAll("#nav a[data-link]")) {
    if (candidate === link) candidate.setAttribute("aria-current", "page");
    else candidate.removeAttribute("aria-current");
  }
}

function announceRoute() {
  sectionOf(location.pathname);
  const app = document.getElementById("app");
  if (!app) return;
  app.focus({ preventScroll: true });
  const title = document.querySelector("#app h1")?.textContent?.trim() || document.title;
  const region = document.getElementById("route-announcer");
  if (region) region.textContent = title;
}

export function navigate(path, { replace = false } = {}) {
  if (replace) history.replaceState({}, "", path);
  else history.pushState({}, "", path);
  focusPending = true;
  render();
}

export async function render() {
  const app = document.getElementById("app");
  if (!app) return;
  const { pathname, search } = location;
  const found = matchRoute(pathname);
  const query = Object.fromEntries(new URLSearchParams(search));
  app.innerHTML = '<div class="loading">Loading…</div>';
  if (!found) {
    app.innerHTML = `
      <div class="empty">
        <h2>Page not found</h2>
        <p class="muted">The page you are looking for does not exist.</p>
        <a class="btn btn-primary mt-2" href="/" data-link>Back home</a>
      </div>`;
    afterRender();
    return;
  }
  try {
    const output = await found.route.handler({ ...found.params, query });
    app.innerHTML = "";
    if (output instanceof Node) app.appendChild(output);
    else if (typeof output === "string") app.innerHTML = output;
  } catch (error) {
    app.innerHTML = `
      <div class="empty">
        <h2>Something went wrong</h2>
        <p class="muted">${error && error.message ? String(error.message).replace(/[<>&]/g, "") : "Unexpected error"}</p>
        <a class="btn mt-2" href="/" data-link>Back home</a>
      </div>`;
  }
  window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
  afterRender();
  if (focusPending) {
    focusPending = false;
    announceRoute();
  } else {
    sectionOf(location.pathname);
  }
}

export function start() {
  window.addEventListener("popstate", () => {
    focusPending = true;
    render();
  });
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-link]");
    if (!link || link.target === "_blank" || event.metaKey || event.ctrlKey || event.shiftKey) return;
    const href = link.getAttribute("href");
    if (!href || href.startsWith("http") || href.startsWith("#")) return;
    event.preventDefault();
    navigate(href);
  });
  render();
}
