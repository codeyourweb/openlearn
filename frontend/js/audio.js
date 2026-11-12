// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/**
 * Speech transcripts: the player a reader sees, and the dialog an author uses.
 *
 * Audio is made when the author asks, never when a reader waits. The player is
 * a queue over one <audio> element: segments arrive as separate files, so the
 * first one starts immediately and the position survives a pause — no audio
 * editor, no ffmpeg, and a retry only costs the segment that failed.
 */

import { api } from "./api.js";
import { t } from "./i18n.js";
import { escapeHtml, toast } from "./ui.js";

const SPEEDS = [0.8, 1, 1.25, 1.5];

function clock(seconds) {
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function totalOf(rendition) {
  return rendition.seconds || rendition.segments.reduce((sum, segment) => sum + (segment.seconds || 0), 0);
}

/** Is speech available here, and in which languages. */
export async function audioStatus() {
  try {
    return await api.get("/api/v1/audio/status");
  } catch {
    return { enabled: false, languages: [], voices: [] };
  }
}

/**
 * Build the player for one document, if it has a transcript.
 *
 * The container stays empty when there is nothing to play: an empty player is
 * worse than no player, and a document edited since its transcript was made
 * falls into that case on purpose.
 */
export async function mountPlayer(host, { ownerType, ownerId, language = null } = {}) {
  if (!host) return;
  const params = new URLSearchParams({ owner_type: ownerType, owner_id: String(ownerId) });
  if (language) params.set("language", language);
  let payload;
  try {
    payload = await api.get(`/api/v1/audio/renditions?${params.toString()}`);
  } catch {
    return;
  }
  if (!payload?.enabled || !payload.renditions?.length) {
    host.innerHTML = "";
    return;
  }

  let current = payload.renditions.find((row) => row.language === language) || payload.renditions[0];
  host.innerHTML = "";
  const card = document.createElement("div");
  card.className = "audio-card";
  host.append(card);

  let audio = null;
  let segmentIndex = 0;
  let playing = false;

  const offsets = (rendition) => {
    const starts = [];
    let running = 0;
    for (const segment of rendition.segments) {
      starts.push(running);
      running += segment.seconds || 0;
    }
    return starts;
  };

  const render = () => {
    const total = totalOf(current);
    const starts = offsets(current);
    card.innerHTML = `
      <button type="button" class="audio-btn" data-audio-toggle
              aria-label="${escapeHtml(t("audio.play"))}" aria-pressed="false">▶</button>
      <div class="audio-main">
        <span class="audio-title">${escapeHtml(t("audio.listen"))} · ${clock(total)}</span>
        <input type="range" class="audio-range" data-audio-range min="0" max="${Math.max(1, Math.round(total))}"
               step="1" value="0" aria-label="${escapeHtml(t("audio.position"))}" />
        <span class="audio-meta"><span data-audio-pos>0:00</span> / ${clock(total)}</span>
      </div>
      <label class="audio-speed">
        <span class="visually-hidden">${escapeHtml(t("audio.speed"))}</span>
        <select data-audio-speed>
          ${SPEEDS.map(
            (speed) => `<option value="${speed}"${speed === 1 ? " selected" : ""}>${speed}×</option>`,
          ).join("")}
        </select>
      </label>
      ${
        payload.renditions.length > 1
          ? `<label class="audio-voice">
               <span class="visually-hidden">${escapeHtml(t("audio.voice"))}</span>
               <select data-audio-voice>
                 ${payload.renditions
                   .map(
                     (row, index) =>
                       `<option value="${index}"${row.id === current.id ? " selected" : ""}>${escapeHtml(
                         t(`audio.voice_${row.voice}`),
                       )}</option>`,
                   )
                   .join("")}
               </select>
             </label>`
          : ""
      }`;

    const button = card.querySelector("[data-audio-toggle]");
    const range = card.querySelector("[data-audio-range]");
    const position = card.querySelector("[data-audio-pos]");

    const stop = () => {
      playing = false;
      button.textContent = "▶";
      button.setAttribute("aria-pressed", "false");
      button.setAttribute("aria-label", t("audio.play"));
    };
    const start = () => {
      playing = true;
      button.textContent = "❚❚";
      button.setAttribute("aria-pressed", "true");
      button.setAttribute("aria-label", t("audio.pause"));
    };

    const load = (index, autoplay = false) => {
      segmentIndex = Math.max(0, Math.min(index, current.segments.length - 1));
      if (!audio) {
        audio = new Audio();
        audio.preload = "metadata";
        audio.addEventListener("ended", () => {
          if (segmentIndex + 1 < current.segments.length) {
            load(segmentIndex + 1, true);
          } else {
            stop();
            range.value = "0";
            position.textContent = "0:00";
          }
        });
        audio.addEventListener("timeupdate", () => {
          const elapsed = starts[segmentIndex] + (audio.currentTime || 0);
          range.value = String(Math.round(elapsed));
          position.textContent = clock(elapsed);
        });
      }
      audio.src = current.segments[segmentIndex].path;
      audio.playbackRate = Number(card.querySelector("[data-audio-speed]")?.value || 1);
      if (autoplay) void audio.play().catch(() => stop());
    };

    button.addEventListener("click", () => {
      if (playing) {
        audio?.pause();
        stop();
        return;
      }
      if (!audio || !audio.src) load(0, true);
      else void audio.play().catch(() => stop());
      start();
    });

    range.addEventListener("input", () => {
      const target = Number(range.value);
      let index = starts.length - 1;
      for (let i = 0; i < starts.length; i += 1) {
        if (target < starts[i] + (current.segments[i].seconds || 0)) {
          index = i;
          break;
        }
      }
      load(index);
      if (audio) {
        audio.currentTime = Math.max(0, target - starts[index]);
        if (playing) void audio.play().catch(() => stop());
      }
      position.textContent = clock(target);
    });

    card.querySelector("[data-audio-speed]")?.addEventListener("change", (event) => {
      if (audio) audio.playbackRate = Number(event.target.value);
    });

    card.querySelector("[data-audio-voice]")?.addEventListener("change", (event) => {
      const previous = audio?.currentTime || 0;
      audio?.pause();
      stop();
      current = payload.renditions[Number(event.target.value)];
      render();
      if (previous) card.querySelector("[data-audio-toggle]")?.focus();
    });
  };

  render();
}

/**
 * The dialog that asks for a transcript, then watches the job.
 *
 * Everything expensive happens in a background job on the server; this only
 * shows how far along it is, and never blocks the editor.
 */
export function openGenerator({ ownerType, ownerId, language, chars = 0, title = "", onReady }) {
  const existing = document.querySelector("#audio-gen");
  existing?.remove();

  const audioSeconds = Math.round(chars / 15.4);
  const cpuMinutes = Math.max(1, Math.round((audioSeconds * 3.7) / 60));
  const dialog = document.createElement("dialog");
  dialog.className = "modal audio-gen";
  dialog.id = "audio-gen";
  dialog.innerHTML = `
    <form method="dialog" class="modal-body">
      <h2>${escapeHtml(t("audio.dialog_title"))}</h2>
      <p class="muted small">${escapeHtml(title)}</p>
      <p class="muted small">${escapeHtml(t("audio.dialog_help"))}</p>
      <fieldset class="field">
        <legend>${escapeHtml(t("audio.voice"))}</legend>
        <label class="check">
          <input type="radio" name="audio-voice" value="female" checked />
          <span>${escapeHtml(t("audio.voice_female"))}</span>
        </label>
        <label class="check">
          <input type="radio" name="audio-voice" value="male" />
          <span>${escapeHtml(t("audio.voice_male"))}</span>
        </label>
      </fieldset>
      <p class="muted small" data-audio-estimate>
        ${escapeHtml(t("audio.estimate", { minutes: cpuMinutes, audio: clock(audioSeconds) }))}
      </p>
      <p class="audio-gen-status" data-audio-status role="status" aria-live="polite"></p>
      <div class="row-wrap end">
        <button class="btn btn-ghost" value="cancel" formnovalidate>${escapeHtml(t("action.cancel"))}</button>
        <button class="btn btn-primary" data-audio-start value="default">${escapeHtml(t("audio.start"))}</button>
      </div>
    </form>`;
  document.body.append(dialog);

  const status = dialog.querySelector("[data-audio-status]");
  const startButton = dialog.querySelector("[data-audio-start]");
  let timer = null;

  const close = () => {
    if (timer) clearInterval(timer);
    dialog.close();
    dialog.remove();
  };

  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close();
  });

  startButton.addEventListener("click", async (event) => {
    event.preventDefault();
    const voice = dialog.querySelector('[name="audio-voice"]:checked')?.value || "female";
    startButton.disabled = true;
    status.textContent = t("audio.queued");
    let job;
    try {
      job = await api.post("/api/v1/audio/render", {
        owner_type: ownerType,
        owner_id: ownerId,
        voice,
        language: language || null,
      });
    } catch (error) {
      startButton.disabled = false;
      status.textContent =
        error?.status === 422 && error?.payload?.detail?.message
          ? error.payload.detail.message
          : t("audio.failed");
      return;
    }

    timer = setInterval(async () => {
      try {
        const state = await api.get(`/api/v1/audio/jobs/${job.job_id}`);
        if (state.status === "running" || state.status === "queued") {
          status.textContent = t("audio.progress", { message: state.message || "…", percent: state.progress });
          return;
        }
        clearInterval(timer);
        timer = null;
        if (state.status === "done") {
          status.textContent = t("audio.ready");
          toast(t("audio.ready"), "success");
          onReady?.(state.result);
          setTimeout(close, 900);
          return;
        }
        status.textContent = state.error || t("audio.failed");
        startButton.disabled = false;
      } catch {
        clearInterval(timer);
        timer = null;
        status.textContent = t("audio.failed");
        startButton.disabled = false;
      }
    }, 2500);
  });

  dialog.showModal();
}

/**
 * Generate the transcripts of every scene of an adventure, one after the other.
 *
 * An adventure is a graph, not a text: there is no single audio track to make,
 * so each scene gets its own. Enqueuing them one at a time keeps the progress
 * honest ("3 of 13") and stops a half-written draft from queueing twelve jobs
 * that will all fail on the same mistake.
 */
export function openBatchGenerator({ items, language, title, onReady }) {
  const existing = document.querySelector("#audio-gen");
  existing?.remove();
  if (!items.length) return;

  const totalChars = items.reduce((sum, item) => sum + (item.chars || 0), 0);
  const audioSeconds = Math.round(totalChars / 15.4);
  const cpuMinutes = Math.max(1, Math.round((audioSeconds * 3.7) / 60));

  const dialog = document.createElement("dialog");
  dialog.className = "modal audio-gen";
  dialog.id = "audio-gen";
  dialog.innerHTML = `
    <form method="dialog" class="modal-body">
      <h2>${escapeHtml(t("audio.dialog_title"))}</h2>
      <p class="muted small">${escapeHtml(title)}</p>
      <p class="muted small">${escapeHtml(t("audio.batch_help", { count: items.length }))}</p>
      <fieldset class="field">
        <legend>${escapeHtml(t("audio.voice"))}</legend>
        <label class="check">
          <input type="radio" name="audio-voice" value="female" checked />
          <span>${escapeHtml(t("audio.voice_female"))}</span>
        </label>
        <label class="check">
          <input type="radio" name="audio-voice" value="male" />
          <span>${escapeHtml(t("audio.voice_male"))}</span>
        </label>
      </fieldset>
      <p class="muted small" data-audio-estimate>
        ${escapeHtml(t("audio.estimate", { minutes: cpuMinutes, audio: clock(audioSeconds) }))}
      </p>
      <p class="audio-gen-status" data-audio-status role="status" aria-live="polite"></p>
      <div class="row-wrap end">
        <button class="btn btn-ghost" value="cancel" formnovalidate>${escapeHtml(t("action.cancel"))}</button>
        <button class="btn btn-primary" data-audio-start value="default">${escapeHtml(t("audio.start"))}</button>
      </div>
    </form>`;
  document.body.append(dialog);

  const status = dialog.querySelector("[data-audio-status]");
  const startButton = dialog.querySelector("[data-audio-start]");
  let stopped = false;

  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      stopped = true;
      dialog.close();
      dialog.remove();
    }
  });
  dialog.addEventListener("close", () => {
    stopped = true;
  });

  const waitFor = async (jobId) => {
    for (;;) {
      if (stopped) return { status: "abandoned" };
      const state = await api.get(`/api/v1/audio/jobs/${jobId}`);
      if (state.status !== "done") {
        status.textContent = t("audio.progress", {
          message: state.message || "…",
          percent: state.progress || 0,
        });
      }
      if (state.status === "done") return state;
      if (state.status !== "running" && state.status !== "queued") return state;
      await new Promise((resolve) => setTimeout(resolve, 2500));
    }
  };

  startButton.addEventListener("click", async (event) => {
    event.preventDefault();
    const voice = dialog.querySelector('[name="audio-voice"]:checked')?.value || "female";
    startButton.disabled = true;
    let done = 0;
    for (const item of items) {
      if (stopped) return;
      status.textContent = t("audio.batch_scene", { index: done + 1, total: items.length });
      let job;
      try {
        job = await api.post("/api/v1/audio/render", {
          owner_type: item.ownerType,
          owner_id: item.ownerId,
          voice,
          language: language || null,
        });
      } catch (error) {
        status.textContent = `${item.label || done + 1} — ${
          error?.payload?.detail?.message || t("audio.failed")
        }`;
        startButton.disabled = false;
        return;
      }
      const state = await waitFor(job.job_id);
      if (state.status !== "done") {
        if (state.status === "abandoned") return;
        status.textContent = `${item.label || done + 1} — ${state.error || t("audio.failed")}`;
        startButton.disabled = false;
        return;
      }
      done += 1;
      status.textContent = t("audio.batch_done", { done, total: items.length });
    }
    onReady?.();
    toast(t("audio.ready"), "success");
    setTimeout(() => {
      dialog.close();
      dialog.remove();
    }, 900);
  });

  dialog.showModal();
}
