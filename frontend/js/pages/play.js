// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Player view: join, answer (QCM or swipe), live feedback, final score.

   The countdown is derived from the server deadline every tick, and selecting
   an answer only repaints the answer grid, so the timer never rewinds.
*/

import { api } from "../api.js";
import { t, tp } from "../i18n.js";
import { LiveConnection } from "../live.js";
import { navigate } from "../router.js";
import {
  hostToken,
  nickname as storedNickname,
  participantId,
  participantToken,
  saveSessionCredentials,
  state as appState,
} from "../store.js";
import { escapeHtml, toast } from "../ui.js";

export async function renderPlay({ code }) {
  const normalized = String(code).toUpperCase();
  const root = document.createElement("div");
  root.className = "play-shell";

  let overview = null;
  try {
    overview = await api.get(`/api/v1/sessions/${normalized}`);
  } catch {
    root.innerHTML = `
      <div class="empty">
        <h2>${t("play.invalid_code")}</h2>
        <p class="muted">${t("home.join_hint")}</p>
        <a class="btn mt-2" href="/" data-link>${t("nav.home")}</a>
      </div>`;
    return root;
  }

  const token = participantToken(normalized);
  if (!token) {
    if (overview.status !== "lobby") {
      root.innerHTML = `
        <div class="empty">
          <h2>${overview.status === "finished" ? t("play.finished") : t("play.already_started")}</h2>
          <p class="muted">${escapeHtml(overview.quiz_title)}</p>
          <a class="btn mt-2" href="/" data-link>${t("nav.home")}</a>
        </div>`;
      return root;
    }
    return renderJoinForm(root, normalized, overview);
  }
  return renderPlayer(root, normalized);
}

function renderJoinForm(root, code, overview) {
  const suggested = storedNickname(code) || (appState.user ? appState.user.display_name : "");
  root.innerHTML = `
    <div class="card play-join">
      <p class="muted small">${t("play.join_title")}</p>
      <h1>${escapeHtml(overview.quiz_title)}</h1>
      <p class="muted">${overview.question_count} ${t("common.questions")} · ${tp("host.player_one", "host.player_many", overview.participant_count)}</p>
      <form id="join-form" class="mt-2" novalidate>
        <div class="form-error" hidden></div>
        <div class="field">
          <label class="label" for="nickname">${t("play.nickname_label")}</label>
          <input class="input" id="nickname" name="nickname" maxlength="30" required
                 value="${escapeHtml(suggested)}" autocomplete="nickname" />
        </div>
        <button class="btn btn-primary btn-block" type="submit">${t("action.join")}</button>
      </form>
    </div>`;

  const form = root.querySelector("#join-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    const errorBox = form.querySelector(".form-error");
    errorBox.hidden = true;
    button.disabled = true;
    try {
      const result = await api.post(`/api/v1/sessions/${code}/join`, {
        nickname: form.querySelector("#nickname").value.trim(),
      });
      saveSessionCredentials(code, {
        participantToken: result.participant.token,
        participantId: result.participant.id,
        nickname: result.participant.nickname,
      });
      navigate(`/play/${code}`, { replace: true });
    } catch (error) {
      errorBox.textContent = error.detail || t("common.error");
      errorBox.hidden = false;
      button.disabled = false;
    }
  });
  return root;
}

async function renderPlayer(root, code) {
  const pt = participantToken(code);
  const pid = participantId(code);
  const isHostClient = Boolean(hostToken(code));
  const headers = { "X-Participant-Token": pt };

  let state;
  try {
    state = await api.get(`/api/v1/sessions/${code}/state`, { headers });
  } catch (error) {
    root.innerHTML = `
      <div class="empty">
        <h2>${t("error.forbidden")}</h2>
        <p class="muted">${escapeHtml(error.detail || "")}</p>
        <a class="btn mt-2" href="/play/${escapeHtml(code)}" data-link>${t("action.join")}</a>
      </div>`;
    return root;
  }

  let timerHandle = null;
  let lastAnnounced = null;

  const announceTimer = (message) => {
    const region = root.querySelector("#timer-announce");
    if (!region) return;
    region.textContent = "";
    window.setTimeout(() => {
      region.textContent = message;
    }, 40);
  };
  let currentDeadline = null;
  let clockOffset = 0;
  let timeUp = false;
  let selections = new Set();
  let currentQuestionId = null;
  let answeredLocally = false;
  let lastSwipe = null; // "yes" | "no", kept to label the "answer sent" panel

  const syncClock = () => {
    if (state.server_time) clockOffset = new Date(state.server_time).getTime() - Date.now();
  };

  const remainingMs = () => {
    if (!currentDeadline) return 0;
    return Math.max(0, new Date(currentDeadline).getTime() - (Date.now() + clockOffset));
  };

  const stopTimer = () => {
    if (timerHandle) clearInterval(timerHandle);
    timerHandle = null;
  };

  /* The countdown is only a local mirror of the server deadline. When it hits
     zero, ask the server for the authoritative state: it reveals an expired
     question, which is what unlocks the "next" button. Without this the player
     stayed on a closed question forever whenever the broadcast was missed
     (solo runs, dropped socket, restarted worker). */
  const refreshState = async () => {
    try {
      const next = await api.get(`/api/v1/sessions/${code}/state`, { headers });
      applyState(next);
    } catch {
      /* a stale screen is better than an empty one */
    }
  };

  const ensureTimer = () => {
    if (timerHandle || !currentDeadline) return;
    timerHandle = setInterval(() => {
      const fill = root.querySelector(".timer-fill");
      const label = root.querySelector("[data-timer-label]");
      const left = remainingMs();
      const total = Math.max(1, (state.question && state.question.time_limit_seconds) || 1) * 1000;
      if (fill) {
        fill.style.width = `${Math.min(100, (left / total) * 100)}%`;
        fill.classList.toggle("low", left < total * 0.3);
      }
      const secondsLeft = Math.ceil(left / 1000);
      if (label) label.textContent = `${secondsLeft}s`;
      // A counter read out ten times a second is noise. The thresholds that
      // matter are the last thirty seconds and the last ten.
      if ((secondsLeft === 30 || secondsLeft === 10) && secondsLeft !== lastAnnounced) {
        lastAnnounced = secondsLeft;
        announceTimer(t("play.time_left").replace("{seconds}", String(secondsLeft)));
      }
      const runClock = root.querySelector("[data-run-clock]");
      if (runClock) {
        const deadline = state.session && state.session.run_deadline;
        const runLeft = deadline
          ? Math.max(0, new Date(deadline).getTime() - (Date.now() + clockOffset))
          : 0;
        const minutes = Math.floor(runLeft / 60000);
        const seconds = Math.floor((runLeft % 60000) / 1000);
        runClock.textContent = `${minutes}:${String(seconds).padStart(2, "0")}`;
        runClock.classList.toggle("low", runLeft < 30000);
      }
      if (left <= 0 && !timeUp) {
        timeUp = true;
        root.classList.add("time-up");
        const submit = root.querySelector('[data-act="submit"]');
        if (submit) submit.disabled = true;
        const notice = root.querySelector("#time-notice");
        if (notice) notice.hidden = false;
        stopTimer();
        refreshState();
      }
    }, 120);
  };

  const myScore = () => {
    const row = (state.scoreboard || []).find((entry) => entry.id === pid);
    return row ? row.score : 0;
  };
  const myRank = () => {
    const index = (state.scoreboard || []).findIndex((entry) => entry.id === pid);
    return index >= 0 ? index + 1 : null;
  };
  const alreadyAnswered = () => {
    if (!state.question) return false;
    if (answeredLocally) return true;
    return (state.question.answered_ids || []).includes(pid);
  };

  const scoreboardHtml = () => `
    <div class="scoreboard">
      ${(state.scoreboard || [])
        .map(
          (row, index) => `
        <div class="score-row ${row.id === pid ? "me" : ""}">
          <span class="score-rank">${index + 1}</span>
          <span class="score-name">${escapeHtml(row.nickname)}</span>
          <span class="score-value">${row.score}</span>
        </div>`,
        )
        .join("")}
    </div>`;

  const paintLobby = () => {
    stopTimer();
    root.innerHTML = `
      <div class="card center">
        <p class="muted small">${t("play.waiting_host")}</p>
        <h1>${escapeHtml(state.session.quiz_title)}</h1>
        <p class="badge ok">${escapeHtml(storedNickname(code) || t("common.player"))}</p>
        <div class="participants mt-3">
          ${(state.participants || [])
            .map(
              (participant) => `
            <div class="participant-chip ${participant.id === pid ? "me" : ""}">
              <span class="dot"></span>
              <span>${escapeHtml(participant.nickname)}</span>
              ${participant.id === pid ? `<span class="badge muted">${t("play.you")}</span>` : ""}
            </div>`,
            )
            .join("")}
        </div>
      </div>`;
  };

  /** Answers grid only: repainting it must not touch the timer. */
  const optionsHtml = () => {
    const question = state.question;
    if (!question) return "";
    const reveal = state.reveal;
    const disabled = alreadyAnswered() || Boolean(reveal) || timeUp;
    const isSwipe = state.session.mode === "swipe";

    if (isSwipe) {
      // One statement, one card: the gesture itself is the answer.
      const yes = question.options[0];
      const no = question.options[1];
      if (alreadyAnswered() && !reveal) {
        const sent = lastSwipe === "yes" ? t("common.yes") : lastSwipe === "no" ? t("common.no") : t("play.submitted");
        return `
          <div class="swipe-sent">
            <span class="swipe-sent-badge">${escapeHtml(sent)}</span>
            <p class="muted small mt-2">${t("play.waiting_next")}</p>
          </div>`;
      }
      const correctId = reveal ? (reveal.correct_option_ids || [])[0] : null;
      const correctKind = correctId && yes && correctId === yes.id ? "yes" : "no";
      const yesCount = reveal ? ((reveal.options || []).find((entry) => entry.id === (yes || {}).id) || {}).count || 0 : 0;
      const noCount = reveal ? ((reveal.options || []).find((entry) => entry.id === (no || {}).id) || {}).count || 0 : 0;
      return `
        <div class="swipe-deck">
          <div class="swipe-card ${disabled ? "is-locked" : `is-inviting`} ${reveal ? `reveal-${correctKind}` : ""}"
               data-swipe-card data-yes="${yes ? yes.id : ""}" data-no="${no ? no.id : ""}"
               tabindex="${disabled ? "-1" : "0"}" aria-label="${escapeHtml(t("play.swipe_hint"))}">
            <span class="swipe-stamp no">← ${escapeHtml(t("common.no"))}</span>
            <span class="swipe-stamp yes">${escapeHtml(t("common.yes"))} →</span>
            <div class="swipe-card-body">
              ${question.image_path ? `<img class="swipe-card-image" src="${escapeHtml(question.image_path)}" alt="" draggable="false" />` : ""}
              <div class="swipe-card-text">${question.text_html}</div>
            </div>
          </div>
        </div>
        ${
          disabled
            ? ""
            : `<div class="swipe-actions">
                 <button class="btn" data-swipe-answer="no">← ${escapeHtml(t("common.no"))}</button>
                 <button class="btn btn-primary" data-swipe-answer="yes">${escapeHtml(t("common.yes"))} →</button>
               </div>
               <p class="swipe-hint">${t("play.swipe_hint")}</p>`
        }
        ${reveal ? `<p class="swipe-tally">← ${noCount} · ${yesCount} →</p>` : ""}`;
    }

    const multiple = question.multiple_answers;
    return `
      <div class="options-grid" role="group" aria-label="${escapeHtml(t("play.answer_choices"))}">
        ${question.options
          .map((option, index) => {
            const selected = selections.has(option.id);
            const isPoll = state.session.mode === "poll";
            const correct = reveal && !isPoll ? (reveal.correct_option_ids || []).includes(option.id) : false;
            // A poll never marks an answer right or wrong: only the tally matters.
            const cls = reveal && !isPoll
              ? correct
                ? "option-btn correct"
                : selected
                  ? "option-btn wrong"
                  : "option-btn"
              : selected
                ? "option-btn selected"
                : "option-btn";
            return `
              <button type="button" class="${cls}" data-option="${option.id}"
                      ${disabled ? "disabled" : ""} aria-pressed="${selected}">
                <span class="letter">${String.fromCharCode(65 + index)}</span>
                <span>${escapeHtml(option.text)}</span>
                ${reveal ? `<span class="option-count">${(reveal.options.find((entry) => entry.id === option.id) || {}).count || 0}</span>` : ""}
                ${reveal && !isPoll ? `<span class="visually-hidden">${correct ? t("play.correct") : selected ? t("play.incorrect") : ""}</span>` : ""}
              </button>`;
          })
          .join("")}
      </div>`;
  };

  const paintOptions = () => {
    const host = root.querySelector("#answers");
    if (host) host.innerHTML = optionsHtml();
    const submit = root.querySelector('[data-act="submit"]');
    if (submit) {
      // Nothing to send until the visitor actually picked an answer.
      submit.disabled = alreadyAnswered() || Boolean(state.reveal) || timeUp || selections.size === 0;
      submit.textContent = alreadyAnswered() ? t("play.submitted") : t("play.submit");
    }
  };

  const feedbackHtml = () => {
    const reveal = state.reveal;
    if (!reveal) return "";
    const mine = (reveal.results || []).find((entry) => entry.participant_id === pid);
    if (state.session.mode === "poll") {
      // Opinion, not a contest: thank the respondent instead of scoring them.
      return `<div class="feedback ok" role="status">${t(mine ? "play.poll_thanks" : "results.no_answer")}</div>`;
    }
    if (!mine) return `<div class="feedback wait" role="status">${t("results.no_answer")}</div>`;
    if (mine.is_correct) return `<div class="feedback ok" role="status">${t("play.correct")} +${mine.points_awarded} ${t("common.points")}</div>`;
    return `<div class="feedback ko" role="status">${t("play.incorrect")} — ${
      mine.points_awarded < 0 ? `${mine.points_awarded} ${t("common.points")}` : t("play.no_points")
    }</div>`;
  };

  const paintQuestion = () => {
    const question = state.question;
    if (!question) return;
    syncClock();
    currentDeadline = question.deadline || null;
    // No deadline means no clock: `remainingMs()` answers 0 for a quiz played
    // without a timer, and treating that as "expired" opened every question
    // already closed, with the time-up banner on screen.
    timeUp = Boolean(currentDeadline) && remainingMs() <= 0;
    answeredLocally = alreadyAnswered();
    if (currentQuestionId !== question.id) {
      currentQuestionId = question.id;
      selections = new Set();
      answeredLocally = false;
      lastSwipe = null;
      timeUp = Boolean(currentDeadline) && remainingMs() <= 0;
    }
    const swipe = state.session.mode === "swipe";
    const multiple = !swipe && question.multiple_answers;

    root.innerHTML = `
      <div class="play-head">
        <div class="row">
          <span class="badge">${t("play.question_of", { n: question.position + 1, total: state.session.question_count })}</span>
          <span class="badge ${multiple ? "warn" : "muted"}">${multiple ? t("play.multi_hint") : t("play.single_hint")}</span>
        </div>
        <span class="badge muted">${t("common.score")} ${myScore()}</span>
      </div>
      <div class="question-card">
        ${
          question.deadline
            ? `<div class="timer">
                 <div class="timer-bar"><div class="timer-fill"></div></div>
                 <span id="timer-announce" class="visually-hidden" role="status" aria-live="polite"></span>
                 <div class="timer-row">
                   <span>${question.points} ${t("common.points")}</span>
                   ${
                     state.session && state.session.timer_mode === "global"
                       ? `<span class="timer-run">${t("play.whole_quiz")} <span data-run-clock></span></span>`
                       : ""
                   }
                   <span data-timer-label aria-hidden="true">${Math.ceil(remainingMs() / 1000)}s</span>
                 </div>
               </div>`
            : `<div class="timer timer-off">
                 <div class="timer-row">
                   <span>${question.points} ${t("common.points")}</span>
                   <span class="muted">${t("play.no_timer")}</span>
                 </div>
               </div>`
        }
        ${swipe ? "" : `<div class="question-text">${question.text_html}</div>`}
        ${!swipe && question.image_path ? `<img class="question-image" src="${escapeHtml(question.image_path)}" alt="" />` : ""}
        <div id="answers">${optionsHtml()}</div>
        <p class="banner warn mt-2" id="time-notice" role="status" ${timeUp && !state.reveal ? "" : "hidden"}>${t("play.time_up")}</p>
        ${
          swipe
            ? ""
            : `<div class="row end mt-3">
                 <button class="btn btn-primary" data-act="submit" ${answeredLocally || state.reveal || timeUp ? "disabled" : ""}>
                   ${answeredLocally ? t("play.submitted") : t("play.submit")}
                 </button>
               </div>`
        }
        <div id="feedback">${feedbackHtml()}</div>
      </div>`;
    ensureTimer();
  };

  const paintReveal = () => {
    stopTimer();
    currentDeadline = null;
    const question = state.question;
    if (!question) return;
    root.innerHTML = `
      <div class="play-head">
        <span class="badge">${t("play.question_of", { n: question.position + 1, total: state.session.question_count })}</span>
        <span class="badge muted">${t("common.score")} ${myScore()}</span>
      </div>
      <div class="question-card">
        ${state.session.mode === "swipe" ? "" : `<div class="question-text">${question.text_html}</div>`}
        ${state.session.mode !== "swipe" && question.image_path ? `<img class="question-image" src="${escapeHtml(question.image_path)}" alt="" />` : ""}
        <div id="answers">${optionsHtml()}</div>
        <div id="feedback">${feedbackHtml()}</div>
        <p class="hint mt-2">${isHostClient ? "" : t("play.waiting_next")}</p>
      </div>
      ${
        isHostClient
          ? `<div class="row end mt-2">
               <button class="btn btn-primary" data-act="next">${
                 question.position + 1 >= state.session.question_count ? t("host.results") : t("host.next")
               }</button>
             </div>`
          : ""
      }
      <section class="card mt-2"><h3>${t("common.score")}</h3>${scoreboardHtml()}</section>`;
  };

  const paintFinished = () => {
    stopTimer();
    const score = myScore();
    const rank = myRank();
    const total = (state.scoreboard || []).length;
    const isPoll = state.session.mode === "poll";
    root.innerHTML = `
      <div class="card center">
        <p class="muted small">${t("play.finished")}</p>
        <h1>${escapeHtml(state.session.quiz_title)}</h1>
        ${
          isPoll
            ? `<p class="muted">${t("play.poll_thanks")}</p>`
            : `<div class="pin-display">${score}</div>`
        }
        <p class="muted">${isPoll ? "" : `${t("play.your_score")}${rank ? ` · ${t("play.rank")} ${rank}/${total}` : ""}`}</p>
        ${scoreboardHtml()}
        <div class="row row-center mt-3">
          <a class="btn btn-primary" href="/results/${escapeHtml(state.session.code)}" data-link>${t("play.see_results")}</a>
          <a class="btn" href="/" data-link>${t("nav.home")}</a>
        </div>
      </div>`;
  };

  const paint = () => {
    stopTimer();
    const session = state.session;
    if (session.status === "lobby") return paintLobby();
    if (session.status === "finished" || session.status === "cancelled") return paintFinished();
    if (session.phase === "reveal") return paintReveal();
    return paintQuestion();
  };

  const toggleSelection = (optionId) => {
    const question = state.question;
    if (!question || state.reveal || timeUp || alreadyAnswered()) return;
    const multiple = state.session.mode !== "swipe" && question.multiple_answers;
    if (multiple) {
      if (selections.has(optionId)) selections.delete(optionId);
      else selections.add(optionId);
    } else {
      selections = new Set([optionId]);
    }
    paintOptions();
  };

  /** POST the answer once: the button and the swipe gesture both land here. */
  const sendAnswer = async (optionIds) => {
    const question = state.question;
    if (!question) return false;
    try {
      await api.post(
        `/api/v1/sessions/${code}/answers`,
        { question_id: question.id, option_ids: optionIds },
        { headers },
      );
      answeredLocally = true;
      selections = new Set(optionIds);
      return true;
    } catch (error) {
      toast(error.detail || t("common.error"), "error");
      return false;
    }
  };

  root.addEventListener("click", async (event) => {
    const optionButton = event.target.closest("[data-option]");
    if (optionButton) {
      if (!optionButton.disabled) toggleSelection(Number(optionButton.dataset.option));
      return;
    }
    const swipeChoice = event.target.closest("[data-swipe-answer]");
    if (swipeChoice) {
      await commitSwipe(swipeChoice.dataset.swipeAnswer, root.querySelector("[data-swipe-card]"));
      return;
    }

    const button = event.target.closest("[data-act]");
    if (!button) return;
    const action = button.dataset.act;
    button.disabled = true;
    try {
      if (action === "submit") {
        if (!selections.size) {
          toast(t("editor.need_correct"), "error");
          button.disabled = false;
          return;
        }
        if (await sendAnswer(Array.from(selections))) paintOptions();
        else button.disabled = false;
      } else if (action === "next") {
        await api.post(`/api/v1/sessions/${code}/next`, undefined, {
          headers: { "X-Host-Token": hostToken(code) },
        });
      }
    } catch (error) {
      if (action === "submit") answeredLocally = false;
      toast(error.detail || t("common.error"), "error");
      button.disabled = false;
    }
  });

  /* ---------------------------------------------------------------------- */
  /* Swipe deck: one statement per card, dragged right (yes) or left (no).   */
  /* ---------------------------------------------------------------------- */

  const SWIPE_THRESHOLD = 120;
  let drag = null;

  const paintDrag = (card, dx, dy) => {
    const progress = Math.min(1, Math.abs(dx) / SWIPE_THRESHOLD);
    const rotation = Math.max(-14, Math.min(14, dx / 18));
    card.style.transform = `translate(${dx}px, ${Math.max(-26, Math.min(26, dy * 0.12))}px) rotate(${rotation}deg)`;
    card.style.setProperty("--swipe-progress", progress.toFixed(2));
    card.classList.toggle("lean-yes", dx > 4);
    card.classList.toggle("lean-no", dx < -4);
  };

  const releaseDrag = (card) => {
    card.style.transform = "";
    card.style.removeProperty("--swipe-progress");
    card.classList.remove("lean-yes", "lean-no", "is-dragging");
  };

  const canSwipe = () => Boolean(state.question) && !state.reveal && !timeUp && !alreadyAnswered();

  const commitSwipe = async (kind, card) => {
    if (!card || !canSwipe()) return;
    const optionId = Number(card.dataset[kind]);
    if (!optionId) return;
    const direction = kind === "yes" ? 1 : -1;
    card.classList.remove("is-inviting");
    card.style.setProperty("--swipe-progress", "1");
    card.classList.add("is-flying");
    card.style.transform = `translate(${direction * 130}%, -4%) rotate(${direction * 18}deg)`;
    lastSwipe = kind;
    if (await sendAnswer([optionId])) {
      paintOptions();
    } else {
      lastSwipe = null;
      card.classList.remove("is-flying");
      releaseDrag(card);
    }
  };

  root.addEventListener("pointerdown", (event) => {
    const card = event.target.closest("[data-swipe-card]");
    if (!card || !canSwipe()) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    drag = { startX: event.clientX, startY: event.clientY, dx: 0, dy: 0, pointerId: event.pointerId, card, axis: null };
    card.classList.remove("is-inviting");
    card.setPointerCapture?.(event.pointerId);
    card.classList.add("is-dragging");
  });

  root.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    // Decide once whether this gesture is a swipe or a page scroll.
    if (!drag.axis && (Math.abs(dx) > 8 || Math.abs(dy) > 8)) {
      drag.axis = Math.abs(dx) >= Math.abs(dy) ? "x" : "y";
    }
    if (drag.axis === "y") return;
    drag.dx = dx;
    drag.dy = dy;
    paintDrag(drag.card, dx, dy);
  });

  const endDrag = async (event, cancelled) => {
    if (!drag || (event.pointerId !== undefined && event.pointerId !== drag.pointerId)) return;
    const { card, dx } = drag;
    drag = null;
    card.classList.remove("is-dragging");
    if (cancelled || Math.abs(dx) < SWIPE_THRESHOLD) {
      releaseDrag(card);
      return;
    }
    await commitSwipe(dx > 0 ? "yes" : "no", card);
  };

  root.addEventListener("pointerup", (event) => { void endDrag(event, false); });
  root.addEventListener("pointercancel", (event) => { void endDrag(event, true); });

  // Keyboard equivalent: the arrows answer without a mouse.
  const onKeyDown = (event) => {
    if (!root.isConnected || !canSwipe()) return;
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const card = root.querySelector("[data-swipe-card]");
    if (!card) return;
    event.preventDefault();
    void commitSwipe(event.key === "ArrowRight" ? "yes" : "no", card);
  };
  document.addEventListener("keydown", onKeyDown);

  /* Single entry point for a new snapshot, whether it comes from the socket or
     from an explicit refresh. */
  const applyState = (next) => {
    state = next;
    if (state.question && state.question.id !== currentQuestionId) answeredLocally = false;
    paint();
  };

  const connection = new LiveConnection(code, pt, {
    onState: (next) => {
      applyState(next);
    },
    onStatus: (status) => {
      const banner = root.querySelector("#connection-banner");
      if (status !== "online" && !banner) {
        const node = document.createElement("div");
        node.id = "connection-banner";
        node.className = "banner warn";
        node.textContent = t("play.reconnect");
        root.prepend(node);
      }
      if (status === "online") root.querySelector("#connection-banner")?.remove();
    },
  });
  connection.connect();
  window.addEventListener("beforeunload", () => {
    connection.close();
    stopTimer();
    document.removeEventListener("keydown", onKeyDown);
  });

  paint();
  return root;
}
