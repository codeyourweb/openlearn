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
import { confirmDialog, escapeHtml, toast } from "./ui.js";

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
 * Put the player between the illustration and the text it reads.
 *
 * A wiki page often opens on a picture, then explains it: a player above the
 * picture belongs to the header, not to the text. Move it under a leading image
 * (a bare <img>, or a paragraph holding nothing else), and leave it where it is
 * when the page starts with words.
 */
export function placePlayerUnderIllustration(host, content) {
  if (!host || !content) return;
  const first = content.firstElementChild;
  if (!first) return;
  const isImage = (element) => element && element.tagName === "IMG";
  const holder =
    isImage(first) || (first.children.length === 1 && isImage(first.firstElementChild)) ? first : null;
  if (holder) content.insertBefore(host, holder.nextElementSibling);
}

/**
 * The author's controls for one portion: a page or a scene.
 *
 * Three states, and no fourth: nothing yet (offer to make it), ready (offer to
 * listen, make it again, or drop it), and unavailable (the button is hidden).
 * "Make it again" replaces the previous rendition — the same voice and language
 * overwrite — so an author who dislikes a reading is never left with two.
 */
export async function mountAudioControls(container, { ownerType, ownerId, language, title = "", chars = 0, onReady }) {
  if (!container) return;
  container.innerHTML = "";
  container.hidden = true;
  if (!ownerId) return;
  const status = await audioStatus();
  if (!status.enabled) return;
  container.hidden = false;

  const supported = status.languages.includes(language);

  const paint = async () => {
    let renditions = [];
    try {
      const query = new URLSearchParams({ owner_type: ownerType, owner_id: String(ownerId) });
      const payload = await api.get(`/api/v1/audio/renditions?${query.toString()}`);
      renditions = payload.renditions || [];
    } catch {
      renditions = [];
    }
    container.innerHTML = "";
    const row = document.createElement("div");
    row.className = "audio-controls-row";

    const button = (label, className, action) => {
      const element = document.createElement("button");
      element.type = "button";
      element.className = className;
      element.textContent = label;
      element.addEventListener("click", action);
      return element;
    };

    if (!renditions.length) {
      if (!supported) {
        const note = document.createElement("p");
        note.className = "muted small";
        note.textContent = t("audio.unsupported");
        row.append(note);
        container.append(row);
        return;
      }
      row.append(
        button(t("audio.generate"), "btn btn-sm", () =>
          openGenerator({
            ownerType,
            ownerId,
            language,
            title,
            chars,
            onReady: () => {
              void paint();
              onReady?.();
            },
          }),
        ),
      );
      container.append(row);
      return;
    }

    const rendition = renditions[0];
    const state = document.createElement("span");
    state.className = "audio-controls-state";
    state.textContent = t("audio.ready_at", { duration: clock(totalOf(rendition)) });
    row.append(state);

    // Listening here beats reloading the page: the author is judging a voice.
    const host = document.createElement("div");
    host.className = "audio-host";
    row.append(
      button(t("audio.listen_now"), "btn btn-sm btn-ghost", () => {
        if (!host.childElementCount) {
          void mountPlayer(host, { ownerType, ownerId, language: rendition.language || language });
        }
        host.hidden = false;
      }),
      button(t("audio.redo"), "btn btn-sm btn-ghost", () =>
        openGenerator({
          ownerType,
          ownerId,
          language,
          title,
          chars,
          onReady: () => {
            void paint();
            onReady?.();
          },
        }),
      ),
      button(t("audio.remove"), "btn btn-sm btn-ghost btn-danger", async () => {
        const agreed = await confirmDialog(t("audio.remove"), t("audio.remove_confirm"), t("action.delete"));
        if (!agreed) return;
        try {
          await api.del(`/api/v1/audio/renditions/${rendition.id}`);
          toast(t("audio.removed"), "success");
          host.innerHTML = "";
          void paint();
          onReady?.();
        } catch (error) {
          toast(error?.detail || t("error.generic"), "error");
        }
      }),
    );
    container.append(row, host);
  };

  await paint();
}
