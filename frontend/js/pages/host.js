// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Host view: lobby (PIN + share link), live control, reveal and scoreboard.

   The host can take part in their own session: joining from the lobby stores a
   participant token, and the question screen then renders an answer panel. The
   countdown is driven by the server deadline (never by a local "remaining"
   value), so a repaint can never rewind it.
*/

import { api } from "../api.js";
import { framingAttr, paintFraming } from "../imageFrame.js";
import { localized, t, tp } from "../i18n.js";
import { LiveConnection } from "../live.js";
import { qrSvg } from "../qr.js";
import { navigate } from "../router.js";
import {
  hostToken,
  nickname as storedNickname,
  participantId,
  participantToken,
  saveSessionCredentials,
  state as appState,
} from "../store.js";
import { confirmDialog, copyToClipboard, escapeHtml, shareLink, toast } from "../ui.js";

export async function renderHost({ code }) {
  const normalized = String(code).toUpperCase();
  const root = document.createElement("div");
  root.className = "play-shell";

  const headers = () => {
    const token = hostToken(normalized);
    return token ? { "X-Host-Token": token } : {};
  };
  const participantHeaders = () => ({ "X-Participant-Token": participantToken(normalized) });

  let state;
  let joinUrl = "";
  try {
    state = await api.get(`/api/v1/sessions/${normalized}/state`, { headers: headers() });
    const link = await api.get(`/api/v1/sessions/${normalized}/join-link`, { headers: headers() });
    joinUrl = link.join_url;
  } catch (error) {
    root.innerHTML = `
      <div class="empty">
        <h2>${t("error.forbidden")}</h2>
        <p class="muted">${escapeHtml(error.detail || "")}</p>
        <a class="btn mt-2" href="/dashboard" data-link>${t("nav.dashboard")}</a>
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
  let closed = false;
  let selection = new Set();
  let submitting = false;

  const myPid = () => participantId(normalized);
  const iAmPlaying = () => Boolean(participantToken(normalized));

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
      }
      if (left <= 0 && !closed) {
        closed = true;
        root.classList.add("time-up");
        const submit = root.querySelector('[data-act="submit"]');
        if (submit) submit.disabled = true;
        const answerButton = root.querySelector('[data-act="send-answer"]');
        if (answerButton) answerButton.disabled = true;
        const revealButton = root.querySelector('[data-act="reveal"]');
        if (revealButton) revealButton.hidden = false;
        const advance = root.querySelector("[data-advance]");
        if (advance) {
          advance.classList.add("is-ready");
          const hint = advance.querySelector("[data-advance-hint]");
          if (hint) hint.textContent = t("host.time_up_ready");
          const nextButton = advance.querySelector('[data-act="next"]');
          if (nextButton) nextButton.dataset.gated = "0";
        }
        // Ask the server what happened: it reveals the expired question, which
        // is what turns "next" into an actual advance.
        refreshState();
      }
    }, 120);
  };

  /** Players who have not answered the question on screen. */
  const pendingPlayers = (question) => {
    const answeredIds = new Set(question.answered_ids || []);
    return (state.participants || []).filter((participant) => !answeredIds.has(participant.id));
  };

  /** The advance controls, at the bottom of the page and away from "submit".
   *
   * A hosting player used to have "next question" right under the answer grid,
   * where a thumb looks for the submit button. It now sits below the player
   * list, says why it is armed, and only fires without a question when everyone
   * has answered or the countdown is over.
   */
  const advanceBar = (question) => {
    const pending = pendingPlayers(question);
    // An untimed question has no deadline: `remainingMs()` answers 0 and the
    // bar would announce a countdown that never started.
    const timeUp = Boolean(currentDeadline) && (closed || remainingMs() <= 0);
    const ready = timeUp || pending.length === 0;
    const hint = timeUp
      ? t("host.time_up_ready")
      : pending.length === 0
        ? t("host.all_answered")
        : tp("host.pending_one", "host.pending_many", pending.length);
    return `
      <section class="host-advance${ready ? " is-ready" : ""}" data-advance>
        <p class="host-advance-hint" data-advance-hint>${escapeHtml(hint)}</p>
        <div class="row end">
          <button class="btn" data-act="reveal" ${closed ? "" : "hidden"}>${t("host.reveal")}</button>
          <button class="btn btn-primary" data-act="next" data-gated="${ready ? "0" : "1"}">${t("host.next")}</button>
        </div>
      </section>`;
  };

  /** The answer grid, shared by the host view and the host-as-player view.
   *
   * A host who joined their own session used to see the question listed twice:
   * once as the static grid above, once as buttons in a separate card. The grid
   * itself becomes the answer surface in that case, so the question and its
   * options appear exactly once — same as for any other player.
   */
  const optionsBlock = (question, reveal) => {
    const counts = new Map((reveal ? reveal.options : []).map((option) => [option.id, option.count]));
    const correct = new Set(reveal ? reveal.correct_option_ids : []);
    const playing =
      !reveal && iAmPlaying() && !closed && !(question.answered_ids || []).includes(myPid());
    return `
      <div class="options-grid">
        ${question.options
          .map((option, index) => {
            const isCorrect = correct.has(option.id);
            const cls = reveal ? (isCorrect ? "correct" : "wrong") : "";
            const letter = String.fromCharCode(65 + index);
            if (playing) {
              return `
              <button class="option-btn ${selection.has(option.id) ? "is-picked" : ""}"
                      type="button" data-pick="${option.id}" data-picked="0" aria-pressed="${selection.has(option.id)}">
                <span class="letter">${letter}</span>
                <span>${escapeHtml(localized(option.text, option.translations))}</span>
              </button>`;
            }
            return `
              <div class="option-btn ${cls}" aria-disabled="true">
                <span class="letter">${letter}</span>
                <span>${escapeHtml(localized(option.text, option.translations))}</span>
                ${reveal ? `<span class="option-count">${counts.get(option.id) || 0}</span>` : ""}
              </div>`;
          })
          .join("")}
      </div>`;
  };

  /** Answer panel shown to a host who joined their own session. */
  const hostPlayBlock = (question) => {
    if (!iAmPlaying()) return "";
    const already = (question.answered_ids || []).includes(myPid());
    if (already) {
      return `<section class="card host-play mt-2">
        <div class="card-head"><h3>${t("host.you_play")}</h3></div>
        <p class="feedback ok">${t("play.submitted")}</p>
      </section>`;
    }
    if (state.session.mode === "swipe") {
      return `<section class="card host-play mt-2">
        <div class="card-head"><h3>${t("host.you_play")}</h3><span class="badge muted">${t("editor.mode_swipe")}</span></div>
        <p class="hint">${t("play.swipe_hint")}</p>
        <div class="row row-center mt-2">
          <button class="btn" data-act="send-answer" data-answer="1">← ${t("common.no")}</button>
          <button class="btn btn-primary" data-act="send-answer" data-answer="0">${t("common.yes")} →</button>
        </div>
      </section>`;
    }
    // Answer control only: the question and its options are already on screen,
    // as interactive buttons, a few lines above. Repeating them here is what
    // made a hosting player read every question twice.
    return `<section class="card host-play mt-2">
      <div class="row between row-wrap">
        <span class="hint">${question.multiple_answers ? t("play.multiple_hint") : t("play.single_hint")}</span>
        <button class="btn btn-primary" data-act="send-answer" disabled>${t("play.submit")}</button>
      </div>
    </section>`;
  };

  const myResult = () => {
    const reveal = state.reveal;
    if (!reveal || !iAmPlaying()) return null;
    const pid = myPid();
    return (reveal.results || []).find((row) => row.participant_id === pid) || null;
  };

  const scoreboardBlock = (limit = 10) => {
    const rows = (state.scoreboard || []).slice(0, limit);
    if (!rows.length) return `<p class="muted">${t("host.no_players")}</p>`;
    const pid = myPid();
    return `
      <div class="scoreboard">
        ${rows
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
  };

  // A room joins by scanning: the PIN stays, because a code is still the
  // fastest thing to say out loud when a phone is flat.
  const qrBlock = () => `
    <div class="lobby-qr-block">
      <div class="lobby-qr" data-qr="${escapeHtml(joinUrl)}" role="img"
           aria-label="${escapeHtml(t("host.qr_label"))}"></div>
      <p class="muted small">${escapeHtml(t("host.qr_hint"))}</p>
      <button class="btn btn-sm btn-ghost" data-act="qr-big">${t("host.qr_full")}</button>
    </div>`;

  const shareBlock = () => `
    <div class="share-box">
      <p class="muted small">${t("host.join_link")}</p>
      <div class="join-url">
        <input class="input" id="join-url" readonly value="${escapeHtml(joinUrl)}" aria-label="${t("host.join_link")}" />
        <button class="btn btn-sm" data-act="copy">${t("action.copy_link")}</button>
      </div>
      <div class="row-wrap mt-2">
        <button class="btn btn-sm btn-ghost" data-act="share">${t("action.share")}</button>
        <button class="btn btn-sm btn-ghost" data-act="copy-code">${t("host.copy_code")}</button>
      </div>
    </div>`;

  // The matrix is computed in the page, not fetched: the lobby must draw its
  // code even on a conference network that drops image requests.
  const paintQr = () => {
    root.querySelectorAll("[data-qr]").forEach((slot) => {
      const value = slot.getAttribute("data-qr");
      if (!value || slot.dataset.qrDrawn === value) return;
      slot.innerHTML = qrSvg(value);
      slot.dataset.qrDrawn = value;
    });
  };

  let overlay = null;
  const closeQrOverlay = () => {
    if (!overlay) return;
    overlay.remove();
    overlay = null;
    const opener = root.querySelector('[data-act="qr-big"]');
    if (opener) opener.focus();
  };

  const openQrOverlay = () => {
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.className = "qr-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", t("host.qr_label"));
    overlay.innerHTML = `
      <div class="qr-overlay-card">
        <p class="muted small">${escapeHtml(state.session.quiz_title)}</p>
        <div class="qr-overlay-code">${escapeHtml(state.session.code)}</div>
        <div class="qr-overlay-qr">${qrSvg(joinUrl)}</div>
        <p class="hint">${escapeHtml(t("host.qr_hint"))}</p>
        <button class="btn" type="button" data-act="qr-close">${t("host.qr_close")}</button>
      </div>`;
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay || event.target.closest('[data-act="qr-close"]')) closeQrOverlay();
    });
    document.body.appendChild(overlay);
    overlay.querySelector('[data-act="qr-close"]').focus();
  };

  const paintLobby = () => {
    stopTimer();
    const participants = state.participants || [];
    const playing = iAmPlaying();
    root.innerHTML = `
      <div class="row between">
        <div>
          <p class="muted small">${t("nav.dashboard")}</p>
          <h1>${escapeHtml(state.session.quiz_title)}</h1>
        </div>
        <button class="btn btn-danger btn-sm" data-act="cancel">${t("host.cancel")}</button>
      </div>

      <div class="lobby mt-2">
        <div class="card center">
          <p class="muted">${t("host.pin")}</p>
          <div class="pin-display" aria-label="${t("host.pin")}">${escapeHtml(state.session.code)}</div>
          ${qrBlock()}
          ${shareBlock()}
          <p class="hint mt-2">${t("host.waiting")}</p>
          <button class="btn btn-primary btn-block mt-2" data-act="start">${t("host.start")}</button>
        </div>

        <div class="stack">
          <div class="card">
            <div class="card-head">
              <h3>${tp("host.player_one", "host.player_many", participants.length)}</h3>
              <span class="badge ${participants.length ? "ok" : "muted"}">${participants.length ? "✓" : "…"}</span>
            </div>
            <div class="participants">
              ${
                participants.length
                  ? participants
                      .map(
                        (participant) => `
                  <div class="participant-chip ${participant.id === myPid() ? "me" : ""}">
                    <span class="dot"></span>
                    <span>${escapeHtml(participant.nickname)}</span>
                    ${participant.id === myPid() ? `<span class="badge muted">${t("play.you")}</span>` : ""}
                  </div>`,
                      )
                      .join("")
                  : `<p class="muted small">${t("host.no_players")}</p>`
              }
            </div>
          </div>

          <div class="card">
            <div class="card-head"><h3>${t("host.you_play")}</h3></div>
            ${
              playing
                ? `<p class="feedback ok">${t("host.playing_as", { name: escapeHtml(storedNickname(normalized) || "—") })}</p>
                   <p class="hint">${t("host.playing_hint")}</p>`
                : `<p class="hint">${t("host.you_play_hint")}</p>
                   <form class="row mt-2" data-form="join-self">
                     <input class="input" id="host-nickname" maxlength="30" required
                            value="${escapeHtml((appState.user && appState.user.display_name) || "")}"
                            placeholder="${t("play.nickname_label")}" aria-label="${t("play.nickname_label")}" />
                     <button class="btn btn-primary" type="submit">${t("host.join_and_play")}</button>
                   </form>`
            }
          </div>
        </div>
      </div>`;
    paintQr();
  };

  const paintQuestion = () => {
    const question = state.question;
    if (!question) return;
    syncClock();
    currentDeadline = question.deadline || null;
    // An untimed question has no deadline; `remainingMs()` then answers 0 and
    // the host screen used to treat it as already expired.
    closed = Boolean(currentDeadline) && remainingMs() <= 0;
    const answered = (question.answered_ids || []).includes(myPid());

    root.innerHTML = `
      <div class="play-head">
        <div class="row">
          <span class="badge">${t("host.question_of", { n: question.position + 1, total: state.session.question_count })}</span>
          <span class="badge muted">${state.session.mode === "swipe" ? t("editor.mode_swipe") : t("editor.mode_qcm")}</span>
        </div>
        <span class="badge ${state.participants.length ? "ok" : "muted"}">${tp("host.player_one", "host.player_many", state.participants.length)}</span>
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
        <div class="question-text">${localized(question.text_html, question.translations)}</div>
        ${question.image_path ? `<img class="question-image" src="${escapeHtml(question.image_path)}" alt=""${framingAttr(question.image_framing)} />` : ""}
        ${optionsBlock(question, null)}
      </div>
      ${answered ? "" : hostPlayBlock(question)}
      <section class="card mt-2">
        <div class="card-head"><h3>${tp("host.player_one", "host.player_many", state.participants.length)}</h3></div>
        <div class="participants">
          ${(state.participants || [])
            .map(
              (participant) => `
            <div class="participant-chip ${answered || (question.answered_ids || []).includes(participant.id) ? "answered" : ""}">
              <span class="dot"></span>
              <span>${escapeHtml(participant.nickname)}</span>
            </div>`,
            )
            .join("")}
        </div>
      </section>
      ${advanceBar(question)}`;
    ensureTimer();
    paintFraming(root);
  };

  const paintReveal = () => {
    stopTimer();
    currentDeadline = null;
    const question = state.question;
    if (!question) return;
    const reveal = state.reveal || { options: [], correct_option_ids: [], answered_count: 0, results: [] };
    const mine = myResult();
    root.innerHTML = `
      <div class="play-head">
        <span class="badge">${t("host.question_of", { n: question.position + 1, total: state.session.question_count })}</span>
        <span class="badge ok">${reveal.answered_count}/${state.participants.length}</span>
      </div>
      <div class="question-card">
        <div class="question-text">${localized(question.text_html, question.translations)}</div>
        ${question.image_path ? `<img class="question-image" src="${escapeHtml(question.image_path)}" alt=""${framingAttr(question.image_framing)} />` : ""}
        ${optionsBlock(question, reveal)}
        ${
          iAmPlaying()
            ? mine
              ? `<div class="feedback ${mine.is_correct ? "ok" : "wait"}">
                   ${mine.is_correct ? t("play.correct") : t("play.incorrect")}
                   ${mine.points_awarded ? `<strong>+${mine.points_awarded}</strong>` : ""}
                 </div>`
              : `<div class="feedback wait">${t("results.no_answer")}</div>`
            : ""
        }
      </div>
      <section class="card mt-2">
        <h3>${t("common.score")}</h3>
        ${scoreboardBlock()}
      </section>
      <section class="host-advance is-ready">
        <div class="row end">
          <button class="btn btn-primary" data-act="${
            question.position + 1 >= state.session.question_count ? "finish" : "next"
          }">
            ${question.position + 1 >= state.session.question_count ? t("host.finish") : t("host.next")}
          </button>
        </div>
      </section>`;
    paintFraming(root);
  };

  const paintFinished = () => {
    stopTimer();
    root.innerHTML = `
      <div class="card center">
        <p class="muted small">${t("play.finished")}</p>
        <h1>${escapeHtml(state.session.quiz_title)}</h1>
        ${scoreboardBlock(50)}
        <div class="row row-center mt-3">
          <a class="btn btn-primary" href="/results/${escapeHtml(state.session.code)}" data-link>${t("host.results")}</a>
          <a class="btn" href="/dashboard" data-link>${t("nav.dashboard")}</a>
        </div>
      </div>`;
  };

  const paint = () => {
    stopTimer();
    const session = state.session;
    // A code left on screen over the first question would hide it from the room.
    if (session.status !== "lobby" && overlay) closeQrOverlay();
    if (session.status === "lobby") return paintLobby();
    if (session.status === "finished" || session.status === "cancelled") return paintFinished();
    if (session.phase === "reveal") return paintReveal();
    return paintQuestion();
  };

  const applyState = (next) => {
    // A new question clears the local selection; the same question keeps it.
    if (!state.question || !next.question || state.question.id !== next.question.id) selection = new Set();
    state = next;
    paint();
  };

  const refreshState = async () => {
    try {
      applyState(await api.get(`/api/v1/sessions/${normalized}/state`, { headers: headers() }));
    } catch {
      /* keep the current screen */
    }
  };

  const connection = new LiveConnection(normalized, hostToken(normalized), {
    onState: (next) => {
      applyState(next);
    },
  });
  connection.connect();

  const sendAnswer = async (optionIds) => {
    const question = state.question;
    if (!question || submitting) return;
    submitting = true;
    try {
      await api.post(
        `/api/v1/sessions/${normalized}/answers`,
        { question_id: question.id, option_ids: optionIds },
        { headers: participantHeaders() },
      );
      toast(t("play.submitted"), "success");
      const next = await api.get(`/api/v1/sessions/${normalized}/state`, { headers: headers() });
      state = next;
      paint();
    } catch (error) {
      toast(error.detail || t("common.error"), "error");
    } finally {
      submitting = false;
    }
  };

  root.addEventListener("submit", async (event) => {
    const form = event.target.closest('[data-form="join-self"]');
    if (!form) return;
    event.preventDefault();
    const button = form.querySelector("button[type=submit]");
    const value = (form.querySelector("#host-nickname").value || "").trim();
    if (!value) {
      toast(t("play.nickname_label"), "error");
      return;
    }
    button.disabled = true;
    try {
      const result = await api.post(`/api/v1/sessions/${normalized}/join`, { nickname: value });
      saveSessionCredentials(normalized, {
        participantToken: result.participant.token,
        participantId: result.participant.id,
        nickname: result.participant.nickname,
      });
      toast(t("host.joined_as_player", { name: result.participant.nickname }), "success");
      // The page is rebuilt as a playing host: drop the old socket first.
      connection.close();
      stopTimer();
      navigate(`/host/${normalized}`, { replace: true });
    } catch (error) {
      button.disabled = false;
      toast(error.detail || t("common.error"), "error");
    }
  });

  root.addEventListener("click", async (event) => {
    const pick = event.target.closest("[data-pick]");
    if (pick) {
      const optionId = Number(pick.dataset.pick);
      const multiple = Boolean(state.question && state.question.multiple_answers);
      if (multiple) {
        if (selection.has(optionId)) selection.delete(optionId);
        else selection.add(optionId);
      } else {
        selection = new Set([optionId]);
      }
      root.querySelectorAll("[data-pick]").forEach((button) => {
        const on = selection.has(Number(button.dataset.pick));
        button.classList.toggle("selected", on);
        button.dataset.picked = on ? "1" : "0";
        button.setAttribute("aria-pressed", String(on));
      });
      const submit = root.querySelector('[data-act="send-answer"]');
      if (submit) submit.disabled = selection.size === 0;
      return;
    }

    const button = event.target.closest("[data-act]");
    if (!button) return;
    const action = button.dataset.act;
    if (action === "copy") {
      await copyToClipboard(root.querySelector("#join-url")?.value || joinUrl);
      return;
    }
    if (action === "copy-code") {
      await copyToClipboard(state.session.code);
      return;
    }
    if (action === "qr-big") {
      openQrOverlay();
      return;
    }
    if (action === "share") {
      const ok = await shareLink({
        title: state.session.quiz_title,
        text: `${t("host.join_link")} — ${state.session.code}`,
        url: joinUrl,
      });
      if (!ok) await copyToClipboard(joinUrl);
      return;
    }
    if (action === "send-answer") {
      if (button.dataset.answer !== undefined) {
        // Swipe: the button order maps to the position of the option.
        const index = Number(button.dataset.answer);
        const option = (state.question.options || [])[index];
        if (option) await sendAnswer([option.id]);
        return;
      }
      if (!selection.size) return;
      await sendAnswer([...selection]);
      return;
    }

    if (action === "next" && button.dataset.gated === "1") {
      const goOn = await confirmDialog(t("host.skip_title"), t("host.skip_body"), t("host.skip_confirm"));
      if (!goOn) return;
    }

    button.disabled = true;
    try {
      if (action === "start") {
        await api.post(`/api/v1/sessions/${normalized}/start`, undefined, { headers: headers() });
      } else if (action === "next") {
        await api.post(`/api/v1/sessions/${normalized}/next`, undefined, { headers: headers() });
      } else if (action === "reveal") {
        await api.post(`/api/v1/sessions/${normalized}/reveal`, undefined, { headers: headers() });
      } else if (action === "finish") {
        await api.post(`/api/v1/sessions/${normalized}/finish`, undefined, { headers: headers() });
        navigate(`/results/${normalized}`);
      } else if (action === "cancel") {
        await api.post(`/api/v1/sessions/${normalized}/cancel`, undefined, { headers: headers() });
        navigate("/dashboard");
      }
    } catch (error) {
      button.disabled = false;
      toast(error.detail || t("common.error"), "error");
    }
  });

  // The overlay sits above a screen that keeps repainting itself, so it is
  // removed whenever the lobby is left, and Escape always closes it.
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && overlay) {
      event.preventDefault();
      closeQrOverlay();
    }
  });

  window.addEventListener("beforeunload", () => {
    connection.close();
    stopTimer();
  });

  paint();
  return root;
}
