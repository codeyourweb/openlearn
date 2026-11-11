// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* The framing editor: drag to place, slide to zoom, inside the real frame.

   The box shows the exact shape the picture will have where it lives (a 2:3
   card, a 16:9 scene, a square question slot), with a dashed border standing for
   the edges. What the author sees here is what the reader will see: the preview
   uses the same CSS as the page.

   Resolves to the framing, to `null` for "show the whole picture again", or to
   `undefined` when the author cancels.
*/

import { t } from "./i18n.js";
import { DEFAULT_FRAMING, MAX_ZOOM, MIN_ZOOM, normalizeFraming } from "./imageFrame.js";
import { escapeHtml } from "./ui.js";

/**
 * @param {{src: string, aspect: number, framing: object|null, label?: string}} options
 * @returns {Promise<{x:number,y:number,zoom:number}|null|undefined>}
 */
export function openFramingEditor({ src, aspect = 16 / 9, framing = null, label = "" }) {
  return new Promise((resolve) => {
    const root = document.getElementById("modal-root");
    const previous = document.activeElement;
    let current = normalizeFraming(framing) || { ...DEFAULT_FRAMING };
    let zoomed = Boolean(normalizeFraming(framing));

    root.innerHTML = `
      <div class="modal-backdrop" role="presentation">
        <div class="modal framing-modal" role="dialog" aria-modal="true"
             aria-labelledby="framing-title" aria-describedby="framing-help" tabindex="-1">
          <h3 id="framing-title">${escapeHtml(t("framing.title"))}</h3>
          <p class="muted small" id="framing-help">${escapeHtml(t("framing.help"))}</p>
          <div class="framing-stage" data-stage tabindex="0" role="application"
               aria-label="${escapeHtml(t("framing.stage"))}">
            <div class="framing-box" data-box>
              <img data-picture src="${escapeHtml(src)}" alt="${escapeHtml(label)}" />
            </div>
            <span class="framing-guide" aria-hidden="true"></span>
          </div>
          <label class="field framing-zoom">
            <span class="label">${escapeHtml(t("framing.zoom"))}</span>
            <input type="range" data-zoom min="${MIN_ZOOM}" max="${MAX_ZOOM}" step="0.05"
                   value="${current.zoom}" aria-label="${escapeHtml(t("framing.zoom"))}" />
          </label>
          <p class="muted small framing-readout" data-readout aria-live="polite"></p>
          <div class="modal-actions">
            <button type="button" class="btn btn-ghost" data-action="whole">${escapeHtml(t("framing.whole"))}</button>
            <button type="button" class="btn btn-ghost" data-action="cancel">${escapeHtml(t("action.cancel"))}</button>
            <button type="button" class="btn btn-primary" data-action="save">${escapeHtml(t("framing.save"))}</button>
          </div>
        </div>
      </div>`;

    const modal = root.querySelector(".modal");
    const box = root.querySelector("[data-box]");
    const picture = root.querySelector("[data-picture]");
    const zoomInput = root.querySelector("[data-zoom]");
    const readout = root.querySelector("[data-readout]");

    const paint = () => {
      box.style.aspectRatio = String(aspect);
      if (zoomed) {
        picture.style.objectFit = "cover";
        picture.style.objectPosition = `${current.x}% ${current.y}%`;
        picture.style.transform = `scale(${current.zoom})`;
        picture.style.transformOrigin = `${current.x}% ${current.y}%`;
      } else {
        picture.style.objectFit = "contain";
        picture.style.objectPosition = "50% 50%";
        picture.style.transform = "none";
        picture.style.transformOrigin = "50% 50%";
      }
      readout.textContent = zoomed
        ? t("framing.readout", { x: Math.round(current.x), y: Math.round(current.y), zoom: current.zoom.toFixed(2) })
        : t("framing.whole_hint");
      zoomInput.value = String(current.zoom);
    };

    // Dragging moves the picture under a fixed window: the focus point travels
    // the other way, and the further we zoom, the less a pixel is worth.
    let dragging = null;
    const onPointerDown = (event) => {
      if (event.button !== undefined && event.button !== 0) return;
      dragging = { x: event.clientX, y: event.clientY };
      box.setPointerCapture?.(event.pointerId);
      event.preventDefault();
    };
    const onPointerMove = (event) => {
      if (!dragging) return;
      const rect = box.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const dx = ((event.clientX - dragging.x) / rect.width) * 100;
      const dy = ((event.clientY - dragging.y) / rect.height) * 100;
      dragging = { x: event.clientX, y: event.clientY };
      zoomed = true;
      current = {
        x: Math.min(100, Math.max(0, current.x - (dx * 100) / (100 * current.zoom))),
        y: Math.min(100, Math.max(0, current.y - (dy * 100) / (100 * current.zoom))),
        zoom: current.zoom,
      };
      paint();
    };
    const onPointerUp = () => {
      dragging = null;
    };
    const onWheel = (event) => {
      if (!event.deltaY) return;
      event.preventDefault();
      zoomed = true;
      current = {
        ...current,
        zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current.zoom - event.deltaY / 500)),
      };
      paint();
    };
    const onKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close(undefined);
        return;
      }
      if (event.key !== "Tab") return;
      const items = Array.from(modal.querySelectorAll("button, input"));
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    const close = (value) => {
      root.innerHTML = "";
      document.removeEventListener("keydown", onKey, true);
      if (previous && typeof previous.focus === "function" && document.contains(previous)) {
        previous.focus();
      }
      resolve(value);
    };

    box.addEventListener("pointerdown", onPointerDown);
    box.addEventListener("pointermove", onPointerMove);
    box.addEventListener("pointerup", onPointerUp);
    box.addEventListener("pointercancel", onPointerUp);
    box.addEventListener("wheel", onWheel, { passive: false });
    zoomInput.addEventListener("input", () => {
      zoomed = true;
      current = { ...current, zoom: Number(zoomInput.value) };
      paint();
    });
    document.addEventListener("keydown", onKey, true);
    root.querySelector('[data-action="cancel"]').addEventListener("click", () => close(undefined));
    root.querySelector('[data-action="whole"]').addEventListener("click", () => {
      zoomed = false;
      current = { ...DEFAULT_FRAMING };
      paint();
      close(null);
    });
    root.querySelector('[data-action="save"]').addEventListener("click", () => {
      close(zoomed ? normalizeFraming(current) : null);
    });
    root.querySelector(".modal-backdrop").addEventListener("click", (event) => {
      if (event.target.classList.contains("modal-backdrop")) close(undefined);
    });

    paint();
    box.focus();
  });
}
