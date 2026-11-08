// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Host view: lobby (PIN + share link), live control, reveal and scoreboard.

   The host can take part in their own session: joining from the lobby stores a
   participant token, and the question screen then renders an answer panel. The
   countdown is driven by the server deadline (never by a local "remaining"
   value), so a repaint can never rewind it.
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
import { copyToClipboard, escapeHtml, shareLink, toast } from "../ui.js";

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
      if (label) label.textContent = `${Math.ceil(left / 1000)}s`;
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
        // Ask the server what happened: it reveals the expired question, which
        // is what turns "next" into an actual advance.
        refreshState();
      }
    }, 120);
  };

  const optionsBlock = (question, reveal) => {
    const counts = new Map((reveal ? reveal.options : []).map((option) => [option.id, option.count]));
    const correct = new Set(reveal ? reveal.correct_option_ids : []);
    return `
      <div class="options-grid">
        ${question.options
          .map((option, index) => {
            const isCorrect = correct.has(option.id);
            const cls = reveal ? (isCorrect ? "correct" : "wrong") : "";
            return `
              <div class="option-btn ${cls}" aria-disabled="true">
                <span class="letter">${String.fromCharCode(65 + index)}</span>
                <span>${escapeHtml(option.text)}</span>
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
    return `<section class="card host-play mt-2">
      <div class="card-head">
        <h3>${t("host.you_play")}</h3>
        <span class="badge muted">${question.multiple_answers ? t("play.multiple_hint") : t("play.single_hint")}</span>
      </div>
      <div class="answers-inline">
        ${question.options
          .map(
            (option, index) => `
          <button class="option-btn" data-pick="${option.id}" data-picked="0">
            <span class="letter">${String.fromCharCode(65 + index)}</span>
            <span>${escapeHtml(option.text)}</span>
          </button>`,
          )
          .join("")}
      </div>
      <div class="row end mt-2">
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
                 <div class="timer-row">
                   <span>${question.points} ${t("common.points")}</span>
                   ${
                     state.session && state.session.timer_mode === "global"
                       ? `<span class="timer-run">${t("play.whole_quiz")} <span data-run-clock></span></span>`
                       : ""
                   }
                   <span data-timer-label>${Math.ceil(remainingMs() / 1000)}s</span>
                 </div>
               </div>`
            : `<div class="timer timer-off">
                 <div class="timer-row">
                   <span>${question.points} ${t("common.points")}</span>
                   <span class="muted">${t("play.no_timer")}</span>
                 </div>
               </div>`
        }
        <div class="question-text">${question.text_html}</div>
        ${question.image_path ? `<img class="question-image" src="${escapeHtml(question.image_path)}" alt="" />` : ""}
        ${optionsBlock(question, null)}
        <div class="row end mt-3">
          <button class="btn" data-act="reveal" ${closed ? "" : "hidden"}>${t("host.reveal")}</button>
          <button class="btn btn-primary" data-act="next">${t("host.next")}</button>
        </div>
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
      </section>`;
    ensureTimer();
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
        <div class="question-text">${question.text_html}</div>
        ${question.image_path ? `<img class="question-image" src="${escapeHtml(question.image_path)}" alt="" />` : ""}
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
        <div class="row end mt-3">
          <button class="btn btn-primary" data-act="${
            question.position + 1 >= state.session.question_count ? "finish" : "next"
          }">
            ${question.position + 1 >= state.session.question_count ? t("host.finish") : t("host.next")}
          </button>
        </div>
      </div>
      <section class="card mt-2">
        <h3>${t("common.score")}</h3>
        ${scoreboardBlock()}
      </section>`;
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

  window.addEventListener("beforeunload", () => {
    connection.close();
    stopTimer();
  });

  paint();
  return root;
}
