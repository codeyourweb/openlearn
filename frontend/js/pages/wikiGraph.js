// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Wiki map: an animated force graph, and an Obsidian-style canvas.
 *
 * Graph — nodes are laid out by a small force simulation drawn on a 2D canvas:
 * links pull, nodes push each other apart, and the scene keeps a slow breathing
 * motion instead of freezing. Wheel zooms around the pointer, dragging empty
 * space pans, dragging a node moves it. A click opens the page beside the map,
 * so the graph and the text are read together.
 *
 * Canvas — a free board: cards are pages, dragged anywhere, joined by edges and
 * saved as JSON. Nothing is implied by the position; it is a thinking surface.
 */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { navigate } from "../router.js";
import { escapeHtml, setBusy, toast } from "../ui.js";
import { paintCustomColors } from "../markdown.js";

const CARD_W = 210;
const CARD_H = 92;

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

async function _wikiGraph(root, params) {
  const wikiId = Number(params.id);
  let wiki;
  let graph;
  try {
    wiki = await api.get(`/api/v1/wiki/${wikiId}`);
    graph = await api.get(`/api/v1/wiki/${wikiId}/graph`);
  } catch (error) {
    root.innerHTML = `<div class="card empty">${escapeHtml(error.detail || t("wiki.not_found"))}</div>`;
    return;
  }

  root.innerHTML = `
    <section class="page-head">
      <div>
        <h1>${escapeHtml(t("wiki.map"))}</h1>
        <p class="muted">${escapeHtml(wiki.title)} · ${escapeHtml(t("wiki.map_help"))}</p>
      </div>
      <div class="row-wrap end">
        <div class="segmented" role="tablist">
          <button class="seg is-active" data-tab="graph" role="tab" aria-selected="true">${escapeHtml(t("wiki.graph"))}</button>
          <button class="seg" data-tab="canvas" role="tab" aria-selected="false">${escapeHtml(t("wiki.canvas"))}</button>
        </div>
        <a class="btn btn-ghost" data-link href="/wiki/${wikiId}">${escapeHtml(t("action.back"))}</a>
      </div>
    </section>

    <section class="card wiki-graph-panel" id="panel-graph">
      <div class="graph-toolbar">
        <span class="muted small">${escapeHtml(t("wiki.graph_legend", { n: graph.edges.length }))}</span>
        <div class="row-wrap">
          <button class="btn btn-sm btn-ghost" id="graph-zoom-in" title="${escapeHtml(t("wiki.zoom_in"))}">+</button>
          <button class="btn btn-sm btn-ghost" id="graph-zoom-out" title="${escapeHtml(t("wiki.zoom_out"))}">−</button>
          <button class="btn btn-sm btn-ghost" id="graph-fit">${escapeHtml(t("wiki.fit"))}</button>
        </div>
      </div>
      <div class="graph-split" id="graph-split">
        <div class="graph-stage" id="graph-stage">
          <canvas id="wiki-graph" aria-label="${escapeHtml(t("wiki.graph"))}" role="img"></canvas>
          <p class="graph-hint small muted">${escapeHtml(t("wiki.graph_hint"))}</p>
        </div>
        <aside class="graph-pane" id="graph-pane" hidden>
          <div class="graph-pane-head">
            <strong id="graph-pane-title"></strong>
            <button class="btn btn-sm btn-ghost" id="graph-pane-close" aria-label="${escapeHtml(t("action.close"))}">×</button>
          </div>
          <div class="graph-pane-body" id="graph-pane-body"></div>
        </aside>
      </div>
    </section>

    <section class="card wiki-canvas-panel" id="panel-canvas" hidden>
      <div class="row-wrap canvas-toolbar">
        <select class="input input-sm" id="canvas-page" aria-label="${escapeHtml(t("wiki.canvas_pick"))}">
          ${(wiki.pages || [])
            .map((page) => `<option value="${page.id}">${escapeHtml(page.title)}</option>`)
            .join("")}
        </select>
        <button class="btn btn-sm" id="canvas-add">${escapeHtml(t("wiki.canvas_add"))}</button>
        <button class="btn btn-sm" id="canvas-link">${escapeHtml(t("wiki.canvas_link"))}</button>
        <button class="btn btn-sm btn-ghost" data-czoom="in">+</button>
        <button class="btn btn-sm btn-ghost" data-czoom="out">−</button>
        <button class="btn btn-sm btn-ghost" data-czoom="fit">${escapeHtml(t("wiki.fit"))}</button>
        <button class="btn btn-sm btn-primary" id="canvas-save">${escapeHtml(t("action.save"))}</button>
      </div>
      <p class="muted small">${escapeHtml(t("wiki.canvas_help"))}</p>
      <div class="wcanvas-viewport" id="wcanvas">
        <div class="wcanvas-board" id="wcanvas-board">
          <svg class="wcanvas-edges" id="wcanvas-edges"><g></g></svg>
          <div class="wcanvas-cards" id="wcanvas-cards"></div>
        </div>
      </div>
    </section>
  `;

  root.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.tab;
      root.querySelectorAll("[data-tab]").forEach((other) => {
        other.classList.toggle("is-active", other === button);
        other.setAttribute("aria-selected", String(other === button));
      });
      root.querySelector("#panel-graph").hidden = tab !== "graph";
      root.querySelector("#panel-canvas").hidden = tab !== "canvas";
      if (tab === "canvas") _fitCanvas();
    });
  });

  /* ------------------------------------------------------------------ */
  /* Graph                                                              */
  /* ------------------------------------------------------------------ */

  const stage = root.querySelector("#graph-stage");
  const canvas = root.querySelector("#wiki-graph");
  const ctx = canvas.getContext("2d");
  const pane = root.querySelector("#graph-pane");
  const view = { x: 0, y: 0, k: 1 };
  const selected = { id: null };

  const nodes = graph.nodes.map((node, index) => {
    const angle = (2 * Math.PI * index) / Math.max(1, graph.nodes.length);
    return {
      ...node,
      x: Math.cos(angle) * (120 + graph.nodes.length * 6),
      y: Math.sin(angle) * (120 + graph.nodes.length * 6),
      vx: 0,
      vy: 0,
      radius: 7 + Math.min(9, (node.tags || []).length * 2 + Math.min(6, node.links)),
    };
  });
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const links = graph.edges
    .map((edge) => ({ ...edge, from: byId.get(edge.source), to: byId.get(edge.target) }))
    .filter((edge) => edge.from && edge.to);

  let width = 0;
  let height = 0;
  let dpr = window.devicePixelRatio || 1;

  const resize = () => {
    // The canvas fills its stage through CSS; only the backing store is sized
    // here. Reading the box before layout would freeze it at 320 px.
    const box = stage.getBoundingClientRect();
    width = Math.max(320, Math.round(box.width));
    height = Math.max(320, Math.round(box.height));
    dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
  };

  const fit = () => {
    if (!nodes.length) return;
    const xs = nodes.map((node) => node.x);
    const ys = nodes.map((node) => node.y);
    const minX = Math.min(...xs) - 90;
    const maxX = Math.max(...xs) + 90;
    const minY = Math.min(...ys) - 70;
    const maxY = Math.max(...ys) + 70;
    const scale = clamp(Math.min(width / (maxX - minX), height / (maxY - minY)), 0.25, 2.2);
    view.k = scale;
    view.x = width / 2 - ((minX + maxX) / 2) * scale;
    view.y = height / 2 - ((minY + maxY) / 2) * scale;
  };

  const world = (clientX, clientY) => {
    const box = canvas.getBoundingClientRect();
    return { x: (clientX - box.left - view.x) / view.k, y: (clientY - box.top - view.y) / view.k };
  };

  let alpha = 1;
  const step = () => {
    // Repulsion between every pair, then springs along the edges.
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let distance = Math.hypot(dx, dy) || 0.01;
        const force = (2600 * alpha) / (distance * distance);
        dx /= distance;
        dy /= distance;
        a.vx -= dx * force;
        a.vy -= dy * force;
        b.vx += dx * force;
        b.vy += dy * force;
      }
    }
    for (const link of links) {
      const dx = link.to.x - link.from.x;
      const dy = link.to.y - link.from.y;
      const distance = Math.hypot(dx, dy) || 0.01;
      const target = link.kind === "tag" ? 150 : 110;
      const pull = ((distance - target) / distance) * 0.012 * alpha * (link.kind === "tag" ? 0.6 : 1);
      link.from.vx += dx * pull;
      link.from.vy += dy * pull;
      link.to.vx -= dx * pull;
      link.to.vy -= dy * pull;
    }
    for (const node of nodes) {
      if (node.fixed) continue;
      node.vx *= 0.86;
      node.vy *= 0.86;
      node.x += node.vx;
      node.y += node.vy;
    }
    alpha = Math.max(0.02, alpha * 0.995);
  };

  const draw = () => {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(dpr * view.k, 0, 0, dpr * view.k, dpr * view.x, dpr * view.y);

    for (const link of links) {
      ctx.beginPath();
      ctx.strokeStyle = link.kind === "tag" ? "rgba(139, 92, 246, 0.45)" : "rgba(148, 163, 184, 0.55)";
      ctx.lineWidth = (link.kind === "tag" ? 1 : 1.4) / view.k;
      if (link.kind === "tag") ctx.setLineDash([4 / view.k, 4 / view.k]);
      else ctx.setLineDash([]);
      ctx.moveTo(link.from.x, link.from.y);
      // A slight curve reads better than a straight web.
      const mx = (link.from.x + link.to.x) / 2;
      const my = (link.from.y + link.to.y) / 2 - 18;
      ctx.quadraticCurveTo(mx, my, link.to.x, link.to.y);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    for (const node of nodes) {
      const active = selected.id === node.id;
      const glow = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, node.radius * 3.4);
      glow.addColorStop(0, active ? "rgba(139, 92, 246, 0.55)" : "rgba(34, 211, 238, 0.28)");
      glow.addColorStop(1, "rgba(34, 211, 238, 0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.radius * 3.4, 0, Math.PI * 2);
      ctx.fill();

      ctx.beginPath();
      ctx.fillStyle = active ? "#8b5cf6" : (node.tags || []).length ? "#22d3ee" : "#94a3b8";
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      ctx.fill();

      if (node.radius > 11) {
        ctx.beginPath();
        ctx.strokeStyle = "rgba(255,255,255,0.55)";
        ctx.lineWidth = 1.2 / view.k;
        ctx.arc(node.x, node.y, node.radius - 3, 0, Math.PI * 2);
        ctx.stroke();
      }

      // Labels are drawn in screen pixels and scaled back by the view, so they
      // stay readable at any zoom level.
      ctx.font = `${12 / view.k}px ui-sans-serif, system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.lineWidth = 3 / view.k;
      ctx.strokeStyle = "rgba(7, 11, 22, 0.75)";
      const label = node.title.length > 26 ? `${node.title.slice(0, 25)}…` : node.title;
      const labelY = node.y + node.radius + 15 / view.k;
      ctx.strokeText(label, node.x, labelY);
      ctx.fillStyle = "rgba(232, 237, 249, 0.95)";
      ctx.fillText(label, node.x, labelY);
    }
  };

  let running = true;
  const loop = () => {
    if (!running) return;
    if (!root.isConnected) {
      running = false;
      return;
    }
    step();
    draw();
    window.requestAnimationFrame(loop);
  };

  const openNode = async (node) => {
    selected.id = node.id;
    pane.hidden = false;
    canvas.style.cursor = "pointer";
    root.querySelector("#graph-pane-title").textContent = node.title;
    const body = root.querySelector("#graph-pane-body");
    body.innerHTML = `<p class="muted small">${escapeHtml(t("common.loading"))}</p>`;
    try {
      const page = await api.get(`/api/v1/wiki/pages/${node.id}`);
      body.innerHTML = `
        <div class="graph-pane-meta">
          ${(page.tags || [])
            .map((tag) => `<span class="tag-chip">${escapeHtml(tag)}</span>`)
            .join("")}
        </div>
        <article class="wiki-content markdown-body">${page.html || ""}</article>
        <a class="btn btn-sm btn-primary" data-link href="/wiki/${wikiId}/p/${encodeURIComponent(node.slug)}">
          ${escapeHtml(t("wiki.open_page"))}
        </a>`;
      paintCustomColors(body);
    } catch (error) {
      body.innerHTML = `<p class="muted small">${escapeHtml(error.detail || t("error.generic"))}</p>`;
    }
  };

  root.querySelector("#graph-pane-close").addEventListener("click", () => {
    pane.hidden = true;
    selected.id = null;
  });

  /* Pointer: pan, drag a node, or click to open. */
  let drag = null;
  canvas.addEventListener("pointerdown", (event) => {
    const point = world(event.clientX, event.clientY);
    const hit = nodes
      .slice()
      .reverse()
      .find((node) => Math.hypot(node.x - point.x, node.y - point.y) <= node.radius + 8);
    drag = hit
      ? { mode: "node", node: hit, startX: point.x, startY: point.y, moved: false }
      : { mode: "pan", startX: event.clientX, startY: event.clientY, originX: view.x, originY: view.y, moved: false };
    if (hit) {
      hit.fixed = true;
      alpha = Math.max(alpha, 0.4);
    }
    canvas.setPointerCapture?.(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!drag) {
      const point = world(event.clientX, event.clientY);
      const over = nodes.some((node) => Math.hypot(node.x - point.x, node.y - point.y) <= node.radius + 8);
      canvas.style.cursor = over ? "pointer" : "grab";
      return;
    }
    if (drag.mode === "pan") {
      view.x = drag.originX + (event.clientX - drag.startX);
      view.y = drag.originY + (event.clientY - drag.startY);
      drag.moved = Math.abs(event.clientX - drag.startX) + Math.abs(event.clientY - drag.startY) > 3;
    } else if (drag.node) {
      const point = world(event.clientX, event.clientY);
      drag.node.x = point.x;
      drag.node.y = point.y;
      drag.node.vx = 0;
      drag.node.vy = 0;
      drag.moved = true;
    }
  });
  const release = (event) => {
    if (!drag) return;
    if (drag.mode === "node" && drag.node) {
      drag.node.fixed = false;
      if (!drag.moved) openNode(drag.node);
    }
    canvas.releasePointerCapture?.(event.pointerId);
    drag = null;
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);

  canvas.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const box = canvas.getBoundingClientRect();
      const px = event.clientX - box.left;
      const py = event.clientY - box.top;
      const factor = Math.exp(-event.deltaY * 0.0016);
      const next = clamp(view.k * factor, 0.2, 5);
      view.x = px - ((px - view.x) * next) / view.k;
      view.y = py - ((py - view.y) * next) / view.k;
      view.k = next;
    },
    { passive: false },
  );

  root.querySelector("#graph-zoom-in").addEventListener("click", () => {
    view.k = clamp(view.k * 1.25, 0.2, 5);
  });
  root.querySelector("#graph-zoom-out").addEventListener("click", () => {
    view.k = clamp(view.k / 1.25, 0.2, 5);
  });
  root.querySelector("#graph-fit").addEventListener("click", fit);
  window.addEventListener("resize", () => {
    if (!root.isConnected) return;
    resize();
  });

  for (let index = 0; index < 90; index += 1) step();
  // Layout is not final on the first frame, so the size and the fit are taken
  // once the browser has placed the panel.
  window.requestAnimationFrame(() => {
    resize();
    fit();
    window.requestAnimationFrame(loop);
  });
  if (typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(() => {
      if (!root.isConnected) {
        observer.disconnect();
        return;
      }
      resize();
      draw();
    });
    observer.observe(stage);
  }

  /* ------------------------------------------------------------------ */
  /* Canvas                                                             */
  /* ------------------------------------------------------------------ */

  const viewport = root.querySelector("#wcanvas");
  const board = root.querySelector("#wcanvas-board");
  const cards = root.querySelector("#wcanvas-cards");
  const edgeLayer = root.querySelector("#wcanvas-edges");
  const cv = { x: 60, y: 40, k: 1 };
  const state = {
    nodes: (wiki.canvas && Array.isArray(wiki.canvas.nodes) ? wiki.canvas.nodes : []).map((node) => ({
      ...node,
      w: node.w || CARD_W,
      h: node.h || CARD_H,
    })),
    edges: (wiki.canvas && Array.isArray(wiki.canvas.edges) ? wiki.canvas.edges : []).map((edge) => ({ ...edge })),
  };
  const pagesById = new Map((wiki.pages || []).map((page) => [page.id, page]));
  let sequence = state.nodes.length;
  let linkFrom = null;

  const applyView = () => {
    board.style.transform = `translate(${cv.x}px, ${cv.y}px) scale(${cv.k})`;
  };

  const _fitCanvas = () => {
    if (!state.nodes.length) {
      cv.x = 40;
      cv.y = 30;
      cv.k = 1;
      applyView();
      return;
    }
    const maxX = Math.max(...state.nodes.map((node) => node.x + (node.w || CARD_W)));
    const maxY = Math.max(...state.nodes.map((node) => node.y + (node.h || CARD_H)));
    const box = viewport.getBoundingClientRect();
    cv.k = clamp(Math.min((box.width - 80) / Math.max(400, maxX), (box.height - 80) / Math.max(280, maxY)), 0.3, 1.4);
    cv.x = 40;
    cv.y = 30;
    applyView();
  };

  const drawCanvasEdges = () => {
    const group = edgeLayer.querySelector("g");
    if (!group) return;
    const byNode = new Map(state.nodes.map((node) => [node.id, node]));
    group.innerHTML = state.edges
      .map((edge) => {
        const from = byNode.get(edge.from);
        const to = byNode.get(edge.to);
        if (!from || !to) return "";
        const x1 = from.x + (from.w || CARD_W) / 2;
        const y1 = from.y + (from.h || CARD_H) / 2;
        const x2 = to.x + (to.w || CARD_W) / 2;
        const y2 = to.y + (to.h || CARD_H) / 2;
        return `<path d="M ${x1} ${y1} C ${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}"
                      data-edge="${escapeHtml(edge.from)}|${escapeHtml(edge.to)}" />`;
      })
      .join("");
  };

  const paintCards = () => {
    cards.innerHTML = state.nodes
      .map((node) => {
        const page = node.page_id ? pagesById.get(node.page_id) : null;
        return `
        <article class="wcanvas-card ${linkFrom === node.id ? "is-linking" : ""}" data-card="${escapeHtml(node.id)}">
          <header>
            <strong>${escapeHtml(node.title || (page ? page.title : t("wiki.untitled")))}</strong>
            <button class="wcanvas-remove" data-remove="${escapeHtml(node.id)}" aria-label="${escapeHtml(t("action.delete"))}">×</button>
          </header>
          <p>${escapeHtml(node.text || (page ? page.excerpt || "" : ""))}</p>
          <footer>
            ${
              node.slug
                ? `<a class="small" data-link href="/wiki/${wikiId}/p/${encodeURIComponent(node.slug)}">${escapeHtml(t("wiki.open"))}</a>`
                : ""
            }
            <span class="small muted">${escapeHtml(t("wiki.canvas_connect"))}</span>
          </footer>
        </article>`;
      })
      .join("");
    for (const node of state.nodes) {
      const element = cards.querySelector(`[data-card="${node.id}"]`);
      if (!element) continue;
      element.style.left = `${node.x}px`;
      element.style.top = `${node.y}px`;
      element.style.width = `${node.w || CARD_W}px`;
    }
    drawCanvasEdges();
    bindCardEvents();
  };

  const bindCardEvents = () => {
    cards.querySelectorAll("[data-remove]").forEach((button) => {
      button.addEventListener("pointerdown", (event) => event.stopPropagation());
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const id = button.dataset.remove;
        state.nodes = state.nodes.filter((node) => node.id !== id);
        state.edges = state.edges.filter((edge) => edge.from !== id && edge.to !== id);
        paintCards();
      });
    });

    cards.querySelectorAll(".wcanvas-card").forEach((element) => {
      const node = state.nodes.find((item) => item.id === element.dataset.card);
      if (!node) return;
      element.addEventListener("pointerdown", (event) => {
        if (event.target.closest("a,button")) return;
        if (linkFrom) {
          // Second click of a connection: join the two cards.
          if (linkFrom !== node.id && !state.edges.some((edge) => edge.from === linkFrom && edge.to === node.id)) {
            state.edges.push({ from: linkFrom, to: node.id });
          }
          linkFrom = null;
          paintCards();
          return;
        }
        const startX = event.clientX;
        const startY = event.clientY;
        const originX = node.x;
        const originY = node.y;
        const onMove = (moveEvent) => {
          node.x = Math.max(0, originX + (moveEvent.clientX - startX) / cv.k);
          node.y = Math.max(0, originY + (moveEvent.clientY - startY) / cv.k);
          element.style.left = `${node.x}px`;
          element.style.top = `${node.y}px`;
          drawCanvasEdges();
        };
        const onUp = () => {
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
        };
        element.setPointerCapture?.(event.pointerId);
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
      });
    });
  };

  // Panning the board: empty space only, so dragging a card never moves the view.
  viewport.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".wcanvas-card, .wcanvas-remove, a, button")) return;
    const startX = event.clientX;
    const startY = event.clientY;
    const originX = cv.x;
    const originY = cv.y;
    if (linkFrom) {
      linkFrom = null;
      paintCards();
    }
    const onMove = (moveEvent) => {
      cv.x = originX + (moveEvent.clientX - startX);
      cv.y = originY + (moveEvent.clientY - startY);
      applyView();
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });

  viewport.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const box = viewport.getBoundingClientRect();
      const px = event.clientX - box.left;
      const py = event.clientY - box.top;
      const factor = Math.exp(-event.deltaY * 0.0014);
      const next = clamp(cv.k * factor, 0.25, 2.5);
      cv.x = px - ((px - cv.x) * next) / cv.k;
      cv.y = py - ((py - cv.y) * next) / cv.k;
      cv.k = next;
      applyView();
    },
    { passive: false },
  );

  root.querySelectorAll("[data-czoom]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.czoom === "fit") {
        _fitCanvas();
        return;
      }
      cv.k = clamp(button.dataset.czoom === "in" ? cv.k * 1.2 : cv.k / 1.2, 0.25, 2.5);
      applyView();
    });
  });

  root.querySelector("#canvas-add").addEventListener("click", () => {
    if (!wiki.can_write) {
      toast(t("wiki.read_only"), "error");
      return;
    }
    const select = root.querySelector("#canvas-page");
    const pageId = Number(select.value);
    const page = pagesById.get(pageId);
    if (!page) return;
    if (state.nodes.some((node) => node.page_id === page.id)) {
      toast(t("wiki.canvas_already"), "info");
      return;
    }
    sequence += 1;
    // Lay the cards on a loose grid so two of them never land on top of the
    // previous one; the author moves them from there.
    const slot = state.nodes.length;
    state.nodes.push({
      id: `n${Date.now()}-${sequence}`,
      page_id: page.id,
      slug: page.slug,
      title: page.title,
      text: (page.excerpt || "").slice(0, 160),
      x: 60 + (slot % 3) * (CARD_W + 40),
      y: 50 + Math.floor(slot / 3) * (CARD_H + 50),
    });
    paintCards();
  });

  root.querySelector("#canvas-link").addEventListener("click", () => {
    // "Link" arms the board: the next card clicked becomes the source, the one
    // after it the target, which is the two-step gesture Obsidian uses too.
    if (!wiki.can_write) {
      toast(t("wiki.read_only"), "error");
      return;
    }
    if (!state.nodes.length) return;
    linkFrom = state.nodes[0].id;
    paintCards();
    toast(t("wiki.canvas_link_hint"), "info");
  });

  root.querySelector("#canvas-save").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (!wiki.can_write) {
      toast(t("wiki.read_only"), "error");
      return;
    }
    setBusy(button, true);
    try {
      await api.put(`/api/v1/wiki/${wikiId}/canvas`, { canvas: state });
      toast(t("wiki.canvas_saved"), "success");
    } catch (error) {
      toast(error.detail || t("error.generic"), "error");
    } finally {
      setBusy(button, false);
    }
  });

  paintCards();
  _fitCanvas();
  if (!wiki.can_write) {
    root.querySelector("#canvas-add").hidden = true;
    root.querySelector("#canvas-link").hidden = true;
    root.querySelector("#canvas-save").hidden = true;
  }
  if (!wiki.pages || !wiki.pages.length) navigate(`/wiki/${wikiId}`, { replace: true });
}

export async function renderWikiGraph(params) {
  const root = document.createElement("section");
  await _wikiGraph(root, params);
  return root;
}
