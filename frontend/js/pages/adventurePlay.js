// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Adventure player: solo branching story with attribute tracking. */

import { api } from "../api.js";
import { currentLanguage, t } from "../i18n.js";
import { navigate } from "../router.js";
import { escapeHtml, toast } from "../ui.js";

const runKey = (quizId) => `ol_adventure_run_${quizId}`;

function readToken(quizId) {
  try {
    return localStorage.getItem(runKey(quizId)) || "";
  } catch {
    return "";
  }
}

function storeToken(quizId, token) {
  try {
    localStorage.setItem(runKey(quizId), token);
  } catch {
    /* private mode: the run still works, it just cannot be resumed */
  }
}

function clearToken(quizId) {
  try {
    localStorage.removeItem(runKey(quizId));
  } catch {
    /* ignore */
  }
}

function attributesBar(state, deltas = {}) {
  return `
    <ul class="adv-stats" role="list">
      ${state.attributes
        .map((attribute) => {
          const delta = deltas[attribute.key] || 0;
          const low = attribute.min;
          const high = attribute.max;
          let percent = 50;
          if (low !== null && high !== null && high > low) {
            percent = Math.max(0, Math.min(100, ((attribute.value - low) / (high - low)) * 100));
          } else if (attribute.value > 0) {
            percent = Math.min(100, attribute.value * 5);
          }
          const badge =
            delta === 0
              ? ""
              : `<span class="adv-delta ${delta > 0 ? "up" : "down"}">${delta > 0 ? "+" : ""}${delta}</span>`;
          return `
            <li class="adv-stat">
              <div class="adv-stat-head">
                <span class="adv-stat-label">${escapeHtml(attribute.label)}</span>
                <span class="adv-stat-value">${attribute.value}${
                  attribute.max !== null && attribute.max !== undefined
                    ? `<span class="muted small"> / ${attribute.max}</span>`
                    : ""
                }${badge}</span>
              </div>
              <div class="adv-stat-track"><span class="adv-stat-fill" data-fill="${Math.round(percent)}"></span></div>
            </li>`;
        })
        .join("")}
    </ul>`;
}

function nodeView(state) {
  const node = state.node;
  return `
    <section class="adv-scene">
      ${node.image_path ? `<img class="adv-image" src="${escapeHtml(node.image_path)}" alt="" loading="lazy" />` : ""}
      <div class="adv-body">
        <div class="adv-text">${/* already sanitised server-side */ node.text_html}</div>
        <div class="adv-choices" role="group" aria-label="${t("adventure.choices")}">
          ${node.choices
            .map(
              (choice) => `
            <button type="button" class="adv-choice" data-choice="${escapeHtml(choice.key)}">
              <span class="adv-choice-text">${escapeHtml(choice.text)}</span>
              <span class="adv-choice-arrow" aria-hidden="true">→</span>
            </button>`,
            )
            .join("")}
        </div>
      </div>
    </section>`;
}

function endingView(state, quizId) {
  const ending = state.ending || {};
  const kind = ending.kind || "exit";
  const scene = ending.scene_html || "";
  // A story may close on the scene's own words when no outcome matches: show
  // them once, not twice.
  const closing = ending.text_html && ending.text_html !== scene ? ending.text_html : "";
  const labels = {
    death: t("adventure.ending_death"),
    victory: t("adventure.ending_victory"),
    node: t("adventure.ending_story"),
    exit: t("adventure.ending_exit"),
  };
  return `
    <section class="adv-ending ${kind}${ending.background_path ? " has-bg" : ""}"${ending.background_path ? ` data-background="${escapeHtml(ending.background_path)}"` : ""}>
      ${
        ending.image_path
          ? `<img class="adv-image" src="${escapeHtml(ending.image_path)}" alt="" loading="eager" />`
          : ""
      }
      <div class="adv-ending-body">
        <span class="adv-ending-kind">${escapeHtml(labels[kind] || kind)}</span>
        <h1 class="adv-ending-title">${escapeHtml(t("adventure.the_end"))}</h1>
        ${
          ending.scene_html
            ? `<div class="adv-text adv-ending-scene">${ending.scene_html}</div>`
            : ""
        }
        ${
          closing
            ? `<div class="adv-text adv-ending-closing">${closing}</div>`
            : ending.scene_html
              ? ""
              : `<p class="adv-text muted">${t("adventure.ending_no_text")}</p>`
        }
        <h2 class="adv-ending-sub">${t("adventure.final_stats")}</h2>
        ${attributesBar(state)}
        <div class="row gap-2 mt-3">
          <button type="button" class="btn" data-act="replay">${t("adventure.play_again")}</button>
          <a class="btn btn-ghost" href="/quizzes/${quizId}" data-link>${t("action.back_to_quiz")}</a>
        </div>
      </div>
    </section>`;
}

export async function renderAdventurePlay({ id }) {
  const root = document.createElement("div");
  root.className = "adv-player";
  root.innerHTML = `<div class="loading">${t("common.loading")}</div>`;

  const quizId = Number(id);
  let quiz = null;
  try {
    quiz = await api.get(`/api/v1/quizzes/${quizId}`);
  } catch (error) {
    root.innerHTML = `<div class="empty"><h2>${t("error.not_found")}</h2>
      <p class="muted">${escapeHtml(error.detail || "")}</p>
      <a class="btn mt-2" href="/" data-link>${t("action.back")}</a></div>`;
    return root;
  }

  if (quiz.mode !== "adventure") {
    root.innerHTML = `<div class="empty"><h2>${t("adventure.not_a_story")}</h2>
      <a class="btn mt-2" href="/quizzes/${quizId}" data-link>${t("action.back_to_quiz")}</a></div>`;
    return root;
  }

  /* Inline `style` attributes are rejected by the application CSP, so dynamic
   * values are applied through the CSSOM after the markup is in the document. */
  const applyDynamicStyles = (host) => {
    host.querySelectorAll("[data-fill]").forEach((element) => {
      element.style.width = `${element.dataset.fill}%`;
    });
    const ending = host.querySelector(".adv-ending[data-background]");
    if (ending) {
      ending.style.backgroundImage = `linear-gradient(180deg, rgba(6,10,22,.72), rgba(6,10,22,.94)), url('${ending.dataset.background}')`;
    }
  };

  let previousValues = null;
  let lastScene = null;

  let clockHandle = 0;
  let expiring = false;

  /* Ask the server to apply the timeout. It decides: if its own deadline has
     not passed, nothing happens and the next tick retries. */
  const expire = async () => {
    if (expiring || !token) return;
    expiring = true;
    try {
      const next = await api.post(`/api/v1/adventure/runs/${encodeURIComponent(token)}/timeout`, {});
      paint(next);
    } catch {
      /* not yet, or no timer: the next render decides again */
    } finally {
      expiring = false;
    }
  };

  const paint = (state) => {
    const deltas = {};
    if (previousValues) {
      for (const attribute of state.attributes) {
        const before = previousValues[attribute.key];
        if (before !== undefined && before !== attribute.value) {
          deltas[attribute.key] = attribute.value - before;
        }
      }
    }
    previousValues = Object.fromEntries(state.attributes.map((a) => [a.key, a.value]));

    const finished = Boolean(state.finished);
    root.innerHTML = `
      <header class="adv-header">
        <a class="adv-brand" href="/quizzes/${quizId}" data-link>← ${escapeHtml(quiz.title)}</a>
        <span class="muted small">${escapeHtml(t("adventure.solo_only"))}</span>
        ${state.run && state.run.node_deadline ? `<span class="adv-clock" data-adv-clock></span>` : ""}
      </header>
      ${finished ? endingView(state, quizId) : nodeView(state)}
      ${finished ? "" : attributesBar(state, deltas)}
    `;
    applyDynamicStyles(root);

    // A new scene starts at the top of the page: the reader clicked at the
    // bottom of the previous one. The focus follows so that a screen reader
    // announces the scene it just moved to, and the choice list stays next in
    // the tab order.
    const sceneKey = finished ? "ending" : (state.node && state.node.key) || "";
    if (lastScene !== null && lastScene !== sceneKey) {
      window.scrollTo({ top: 0, left: 0, behavior: "auto" });
      const arrival = root.querySelector(finished ? ".adv-ending-title" : ".adv-text");
      if (arrival) {
        arrival.setAttribute("tabindex", "-1");
        arrival.focus({ preventScroll: true });
      }
    }
    lastScene = sceneKey;

    // Story clock: the server holds the deadline, the client only mirrors it
    // and asks for the penalty when it runs out.
    if (clockHandle) clearInterval(clockHandle);
    clockHandle = 0;
    const clock = root.querySelector("[data-adv-clock]");
    if (clock && state.run && state.run.node_deadline) {
      const deadline = new Date(state.run.node_deadline).getTime();
      const tick = () => {
        const left = Math.max(0, deadline - Date.now());
        const minutes = Math.floor(left / 60000);
        const seconds = Math.floor((left % 60000) / 1000);
        clock.textContent = `${minutes}:${String(seconds).padStart(2, "0")}`;
        clock.classList.toggle("low", left < 20000);
        if (left <= 0) {
          clearInterval(clockHandle);
          clockHandle = 0;
          expire();
        }
      };
      tick();
      clockHandle = setInterval(tick, 500);
    }

    root.querySelectorAll("[data-choice]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (button.disabled) return;
        root.querySelectorAll("[data-choice]").forEach((item) => {
          item.disabled = true;
        });
        button.classList.add("chosen");
        try {
          const next = await api.post(`/api/v1/adventure/runs/${encodeURIComponent(token)}/choose`, {
            choice: button.dataset.choice,
          });
          paint(next);
        } catch (error) {
          toast(error.detail || t("error.generic"), "error");
          root.querySelectorAll("[data-choice]").forEach((item) => {
            item.disabled = false;
          });
          button.classList.remove("chosen");
        }
      });
    });

    const replay = root.querySelector('[data-act="replay"]');
    if (replay) {
      replay.addEventListener("click", async () => {
        clearToken(quizId);
        await start();
      });
    }
  };

  let token = readToken(quizId);

  const start = async () => {
    root.innerHTML = `<div class="loading">${t("common.loading")}</div>`;
    try {
      const created = await api.post(`/api/v1/adventure/quizzes/${quizId}/runs`, {
        language: currentLanguage(),
      });
      token = created.run_token;
      storeToken(quizId, token);
      previousValues = null;
      paint(created.state);
    } catch (error) {
      root.innerHTML = `
        <div class="empty">
          <h2>${escapeHtml(error.detail || t("error.generic"))}</h2>
          <a class="btn mt-2" href="/quizzes/${quizId}" data-link>${t("action.back_to_quiz")}</a>
        </div>`;
    }
  };

  if (token) {
    try {
      const resumed = await api.get(`/api/v1/adventure/runs/${encodeURIComponent(token)}`);
      previousValues = null;
      paint(resumed);
      return root;
    } catch {
      clearToken(quizId);
      token = "";
    }
  }

  await start();
  return root;
}
