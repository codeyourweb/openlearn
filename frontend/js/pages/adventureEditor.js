// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Adventure editor: a node canvas plus a contextual inspector.
 *
 * Editing model: the whole story is one document. The canvas is a plain DOM +
 * SVG surface (no build step, no third-party library) where nodes can be
 * dragged; every change is applied to `model` and the affected view is painted
 * again. Saving sends the complete graph to PUT /api/v1/quizzes/{id}.
 */

import { api, keepaliveRequest, uploadImage } from "../api.js";
import { currentLanguage, t } from "../i18n.js";
import { navigate } from "../router.js";
import { confirmDialog, escapeHtml, showUploadProgress, toast } from "../ui.js";

const NODE_W = 340;
const NODE_HEAD_H = 40;
const NODE_TEXT_H = 54;
const NODE_ROW_H = 44;
const NODE_PAD_BOTTOM = 12;
const GRID = 40;

const uid = (prefix) => `${prefix}_${Math.random().toString(36).slice(2, 8)}`;

/** Same rule as the server (`_slug_key`): a label becomes an identifier.
 *
 * Folded accents, spaces and punctuation turned into hyphens, lower case. The
 * two implementations must agree, otherwise a key the editor shows is not the
 * key the server stores.
 */
const slugifyKey = (value) =>
  String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase()
    .slice(0, 40) || "item";

/* Validation messages arrive from the API in the language of the schema, which
 * is English. A French author reading "String should have at least 3
 * characters" has no way to know which field is meant, and no way to fix it. */
const PROBLEM_PATTERNS = [
  [/^String should have at least (\d+) characters?$/i, (m) => t("error.min_chars", { n: m[1] })],
  [/^String should have at most (\d+) characters?$/i, (m) => t("error.max_chars", { n: m[1] })],
  [/^Field required$/i, () => t("error.required")],
  [/^Input should be a valid integer/i, () => t("error.integer")],
  [/^Input should be a valid number/i, () => t("error.number")],
  [/^String should match pattern/i, () => t("error.format")],
  [/^Attribute label cannot be empty\.?$/i, () => t("error.attr_label")],
  [/^Node text cannot be empty\.?$/i, () => t("error.node_text")],
];

const humanizeProblem = (message) => {
  const text = String(message || "").trim();
  for (const [pattern, render] of PROBLEM_PATTERNS) {
    const match = text.match(pattern);
    if (match) return render(match);
  }
  return text || t("error.generic");
};

/** Rename a key everywhere it is used.
 *
 * Choices, outcomes and the timeout penalty all point at an attribute by key. A
 * key that changes on its own — which is what happens when it is derived from a
 * label the author just retyped — would leave those references dangling, and the
 * save would fail with "affects unknown attribute".
 */
const renameKeyEverywhere = (model, previous, next) => {
  if (!previous || previous === next) return;
  for (const node of model.adventure.nodes || []) {
    for (const choice of node.choices || []) {
      for (const effect of choice.effects || []) {
        if (effect.attribute === previous) effect.attribute = next;
      }
    }
    for (const outcome of node.outcomes || []) {
      if (outcome.attribute === previous) outcome.attribute = next;
    }
  }
  if (model.adventure.timeout_penalty_attribute === previous) {
    model.adventure.timeout_penalty_attribute = next;
  }
};

/** Two attributes cannot share a key: the second would overwrite the first. */
const uniqueAttributeKey = (base, index, attributes) => {
  const taken = new Set(
    (attributes || [])
      .filter((_, other) => other !== index)
      .map((attribute) => attribute.key),
  );
  if (!taken.has(base)) return base;
  let suffix = 2;
  while (taken.has(`${base}-${suffix}`)) suffix += 1;
  return `${base}-${suffix}`;
};

const clone = (value) => JSON.parse(JSON.stringify(value));

const snap = (value) => Math.round(value / GRID) * GRID;

function emptyModel() {
  return {
    id: null,
    title: "",
    description: "",
    status: "draft",
    is_public: false,
    default_language: currentLanguage(),
    adventure: {
      start: "start",
      timer_mode: "none",
      time_limit_seconds: 0,
      timeout_effect: "penalty",
      timeout_penalty: 1,
      timeout_penalty_attribute: "",
      death_text_html: "<p></p>",
      death_translations: {},
      death_background_path: null,
      victory_text_html: "<p></p>",
      victory_translations: {},
      victory_background_path: null,
      attributes: [
        {
          key: "energy",
          label: t("adventure.default_attribute"),
          translations: {},
          initial_value: 5,
          min_value: 0,
          max_value: 20,
          death_at_or_below: null,
          victory_at_or_above: null,
        },
      ],
      nodes: [
        {
          key: "start",
          kind: "question",
          text_html: `<p>${t("adventure.default_scene")}</p>`,
          translations: {},
          image_path: null,
          background_path: null,
          pos_x: 40,
          pos_y: 60,
          choices: [
            {
              key: uid("c"),
              text: t("adventure.default_choice_a"),
              translations: {},
              target: "ending",
              effects: [
                { attribute: "energy", delta: 1 },
              ],
            },
            {
              key: uid("c"),
              text: t("adventure.default_choice_b"),
              translations: {},
              target: "",
              effects: [],
            },
          ],
          outcomes: [],
        },
        {
          key: "ending",
          kind: "ending",
          text_html: `<p>${t("adv_editor.default_ending")}</p>`,
          translations: {},
          image_path: null,
          background_path: null,
          pos_x: 320,
          pos_y: 230,
          choices: [],
          outcomes: [
            {
              kind: "highest",
              attribute: "energy",
              range_min: null,
              range_max: null,
              text_html: `<p>${t("adv_editor.default_outcome")}</p>`,
              translations: {},
              priority: 0,
            },
          ],
        },
      ],
    },
  };
}

function normalizePositions(model) {
  // Keep the graph anchored to the top-left corner of the canvas whatever the
  // coordinates the author left behind, so nothing opens off-screen.
  const nodes = model.adventure.nodes;
  if (!nodes.length) return;
  const minX = Math.min(...nodes.map((node) => node.pos_x));
  const minY = Math.min(...nodes.map((node) => node.pos_y));
  const shiftX = minX - 40;
  const shiftY = minY - 60;
  if (shiftX === 0 && shiftY === 0) return;
  nodes.forEach((node) => {
    node.pos_x = Math.max(0, node.pos_x - shiftX);
    node.pos_y = Math.max(0, node.pos_y - shiftY);
  });
}

function fromQuiz(quiz) {
  const adventure = clone(quiz.adventure || emptyModel().adventure);
  adventure.nodes = adventure.nodes.map((node) => ({
    ...node,
    choices: (node.choices || []).map((choice) => ({
      ...choice,
      target: choice.target || "",
      effects: choice.effects || [],
    })),
    outcomes: node.outcomes || [],
  }));
  return {
    id: quiz.id,
    title: quiz.title,
    description: quiz.description,
    status: quiz.status,
    is_public: quiz.is_public,
    default_language: quiz.default_language || "en",
    adventure,
  };
}

function nodeByKey(model, key) {
  return model.adventure.nodes.find((node) => node.key === key);
}

function attributeLabel(model, key) {
  const attribute = model.adventure.attributes.find((item) => item.key === key);
  return attribute ? attribute.label : key;
}

/* ------------------------------------------------------------------------- */
/* Canvas                                                                     */
/* ------------------------------------------------------------------------- */

/**
 * A block is as tall as its answers: one row per answer, like the numbered
 * rules of a switch block. Every row owns the port on the right edge, so a link
 * always starts from the answer that produces it.
 */
function blockRows(node) {
  return node.kind === "ending" ? node.outcomes.length : node.choices.length;
}

function blockHeight(node) {
  return NODE_HEAD_H + NODE_TEXT_H + Math.max(1, blockRows(node)) * NODE_ROW_H + NODE_PAD_BOTTOM;
}

function rowCenter(index) {
  return NODE_HEAD_H + NODE_TEXT_H + index * NODE_ROW_H + NODE_ROW_H / 2;
}

function outPort(node, index) {
  return { x: node.pos_x + NODE_W, y: node.pos_y + rowCenter(index) };
}

function inPort(node) {
  return { x: node.pos_x, y: node.pos_y + blockHeight(node) / 2 };
}

/**
 * Orthogonal stub out of the answer, then a flat curve into the next block.
 *
 * A forward link is a plain S-curve. A link that points backwards (or straight
 * down) cannot use the same shape: the control points would sit behind the
 * target and the curve would loop on itself. Those links leave to the right,
 * run down a vertical lane and come back to the target's input port, which is
 * exactly what a workflow editor draws when a branch returns upstream.
 */
function edgePath(from, to, index) {
  const start = outPort(from, index);
  const end = inPort(to);
  const stub = 22;
  const ahead = end.x - start.x;
  if (ahead >= 90) {
    const bend = Math.min(190, ahead / 2);
    return `M ${start.x} ${start.y} L ${start.x + stub} ${start.y} C ${start.x + stub + bend} ${
      start.y
    }, ${end.x - bend} ${end.y}, ${end.x} ${end.y}`;
  }
  const lane = Math.max(start.x, end.x) + 54;
  return `M ${start.x} ${start.y} L ${start.x + stub} ${start.y} C ${lane} ${start.y}, ${lane} ${
    end.y
  }, ${end.x} ${end.y}`;
}

/** True when two blocks sit on top of each other. */
function blocksOverlap(model) {
  const nodes = model.adventure.nodes;
  for (let a = 0; a < nodes.length; a += 1) {
    for (let b = a + 1; b < nodes.length; b += 1) {
      const first = nodes[a];
      const second = nodes[b];
      const overlapX = Math.abs(first.pos_x - second.pos_x) < NODE_W - 24;
      const overlapY = Math.abs(first.pos_y - second.pos_y) < Math.min(blockHeight(first), blockHeight(second)) - 24;
      if (overlapX && overlapY) return true;
    }
  }
  return false;
}

/**
 * Lay the story out in columns: one column per graph depth, blocks stacked in
 * reading order. Without it a hand-placed graph drifts into a pile.
 */
function autoLayout(model, options = {}) {
  const nodes = model.adventure.nodes;
  const byKey = Object.fromEntries(nodes.map((node) => [node.key, node]));
  const depth = new Map();
  if (byKey[model.adventure.start]) depth.set(model.adventure.start, 0);
  const queue = [...depth.keys()];
  let guard = nodes.length * 4;
  while (queue.length && guard-- > 0) {
    const key = queue.shift();
    const node = byKey[key];
    const next = (depth.get(key) || 0) + 1;
    for (const choice of node.choices || []) {
      const target = byKey[choice.target];
      if (!target || target.key === key) continue;
      if (!depth.has(target.key) || depth.get(target.key) < next) {
        depth.set(target.key, next);
        queue.push(target.key);
      }
    }
  }
  // Unreachable blocks still deserve a column of their own.
  let extra = Math.max(0, ...depth.values()) + 1;
  nodes.forEach((node) => {
    if (!depth.has(node.key)) {
      depth.set(node.key, extra);
      extra += 1;
    }
  });

  const columns = new Map();
  nodes.forEach((node) => {
    const column = depth.get(node.key) || 0;
    if (!columns.has(column)) columns.set(column, []);
    columns.get(column).push(node);
  });

  const pad = 60;
  const gapX = 90;
  const gapY = 48;
  if (options.narrow) {
    // Phone: one column. A two-column story would need a 0.4 zoom to fit 390 px,
    // which is unreadable; stacked blocks scroll vertically instead.
    [...columns.keys()]
      .sort((a, b) => a - b)
      .flatMap((column) => columns.get(column))
      .reduce((y, node) => {
        node.pos_x = pad;
        node.pos_y = y;
        return y + blockHeight(node) + gapY;
      }, pad);
    return;
  }
  [...columns.keys()]
    .sort((a, b) => a - b)
    .forEach((column) => {
      let y = pad;
      columns.get(column).forEach((node) => {
        node.pos_x = pad + column * (NODE_W + gapX);
        node.pos_y = y;
        y += blockHeight(node) + gapY;
      });
    });
}

function nodeLabel(node) {
  const text = (node.text_html || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
  return text || t("adv_editor.empty_node");
}

function paintCanvas(host, model, selectedKey, zoom) {
  const nodes = model.adventure.nodes;
  const byKey = Object.fromEntries(nodes.map((node) => [node.key, node]));

  const edges = [];
  for (const node of nodes) {
    node.choices.forEach((choice, index) => {
      const target = byKey[choice.target];
      if (target) {
        edges.push(
          `<path class="adv-edge" data-from="${escapeHtml(node.key)}" data-edge="${escapeHtml(
            node.key,
          )}:${index}" marker-end="url(#adv-arrow)" d="${edgePath(node, target, index)}"></path>`,
        );
      }
    });
  }

  const width = Math.max(1200, ...nodes.map((node) => node.pos_x + NODE_W + 320));
  const height = Math.max(760, ...nodes.map((node) => node.pos_y + blockHeight(node) + 220));

  host.innerHTML = `
    <svg class="adv-edges" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true">
      <defs>
        <marker id="adv-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"></path>
        </marker>
      </defs>
      ${edges.join("")}
    </svg>
    ${nodes
      .map((node) => {
        const isStart = model.adventure.start === node.key;
        const ending = node.kind === "ending";
        const rows = ending
          ? node.outcomes.map((outcome, index) => ({
              index,
              label:
                outcome.kind === "default"
                  ? t("adv_editor.default_outcome_kind")
                  : `${attributeLabel(model, outcome.attribute) || outcome.kind}`,
              hint: [outcome.range_min, outcome.range_max].every((value) => value === null || value === undefined)
                ? ""
                : `${outcome.range_min ?? "−∞"} – ${outcome.range_max ?? "+∞"}`,
              linked: true,
            }))
          : node.choices.map((choice, index) => {
              const target = byKey[choice.target];
              return {
                index,
                // No hard cut: the row clamps to two lines and the rest is a tooltip.
              label: (choice.text || "").trim() || t("adv_editor.empty_choice"),
                hint: target ? `→ ${nodeLabel(target)}` : t("adv_editor.not_linked"),
                linked: Boolean(target),
              };
            });

        return `
        <article class="adv-node ${ending ? "is-ending" : ""} ${node.key === selectedKey ? "is-selected" : ""} ${
          isStart ? "is-start" : ""
        }" data-node="${escapeHtml(node.key)}" data-x="${node.pos_x}" data-y="${node.pos_y}">
          ${ending ? "" : `<span class="adv-node-in" aria-hidden="true"></span>`}
          <header class="adv-node-head">
            <span class="adv-node-kind">${ending ? t("adv_editor.ending") : t("adv_editor.question")}</span>
            ${isStart ? `<span class="adv-node-start">${t("adv_editor.start")}</span>` : ""}
            <span class="spacer"></span>
            ${
              ending
                ? ""
                : `<button type="button" class="adv-node-action" data-act="add-child" data-node="${escapeHtml(
                    node.key,
                  )}" title="${t("adv_editor.add_child")}" aria-label="${t("adv_editor.add_child")}">＋</button>`
            }
            <button type="button" class="adv-node-action is-danger" data-act="delete-node" data-node="${escapeHtml(
              node.key,
            )}" title="${t("adv_editor.delete_node")}" aria-label="${t("adv_editor.delete_node")}">✕</button>
          </header>
          <p class="adv-node-text" title="${escapeHtml(nodeLabel(node))}">${escapeHtml(nodeLabel(node))}</p>
          <ul class="adv-node-rows">
            ${rows
              .map(
                (row) => `
              <li class="adv-row ${row.linked ? "is-linked" : "is-open"}" data-row="${row.index}"
                  data-edge="${escapeHtml(node.key)}:${row.index}" data-node="${escapeHtml(node.key)}">
                <span class="adv-row-index">${row.index + 1}</span>
                <span class="adv-row-label" title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</span>
                <span class="adv-row-hint">${escapeHtml(row.hint)}</span>
              </li>`,
              )
              .join("")}
          </ul>
          ${
            ending
              ? ""
              : `<div class="adv-ports">${node.choices
                  .map(
                    (choice, index) =>
                      `<button type="button" class="adv-port ${choice.target ? "is-linked" : "is-open"}"
                               data-port="${index}" data-node="${escapeHtml(node.key)}"
                               title="${t("adv_editor.drag_to_link", { n: index + 1 })}"
                               aria-label="${t("adv_editor.drag_to_link", { n: index + 1 })}"></button>`,
                  )
                  .join("")}</div>`
          }
        </article>`;
      })
      .join("")}
  `;
  // Inline style attributes are rejected by the CSP: positions are applied via
  // the CSSOM once the nodes are in the document.
  host.querySelectorAll("article.adv-node").forEach((element) => {
    element.style.left = `${element.dataset.x}px`;
    element.style.top = `${element.dataset.y}px`;
    element.style.width = `${NODE_W}px`;
  });
  // One port per answer, aligned with its row: the link always leaves from the
  // answer that produces it, exactly like a switch block in n8n.
  host.querySelectorAll(".adv-ports").forEach((ports) => {
    ports.querySelectorAll(".adv-port").forEach((port, index) => {
      port.style.top = `${rowCenter(index) - 6}px`;
    });
  });

  // The view transform (pan + zoom) is applied by the render function, which
  // owns both values; paintCanvas only places blocks.
}

/* ------------------------------------------------------------------------- */
/* Inspector                                                                  */
/* ------------------------------------------------------------------------- */

function effectsEditor(model, choice, choiceIndex) {
  const attributes = model.adventure.attributes;
  return `
    <div class="adv-effects">
      ${choice.effects
        .map(
          (effect, index) => `
        <div class="adv-effect-row">
          <select class="input input-sm" data-effect="attribute" data-choice="${choiceIndex}" data-effect-index="${index}">
            ${attributes
              .map(
                (attribute) =>
                  `<option value="${escapeHtml(attribute.key)}" ${
                    attribute.key === effect.attribute ? "selected" : ""
                  }>${escapeHtml(attribute.label)}</option>`,
              )
              .join("")}
          </select>
          <input class="input input-sm adv-effect-value" type="number" step="1" data-effect="delta"
                 data-choice="${choiceIndex}" data-effect-index="${index}" value="${effect.delta}" />
          <button type="button" class="btn btn-xs btn-ghost" data-act="remove-effect"
                  data-choice="${choiceIndex}" data-effect-index="${index}">✕</button>
        </div>`,
        )
        .join("")}
      <button type="button" class="btn btn-xs btn-ghost" data-act="add-effect" data-choice="${choiceIndex}">
        + ${t("adv_editor.add_effect")}
      </button>
    </div>`;
}

function choicesEditor(model, node) {
  const targets = model.adventure.nodes;
  return `
    <div class="adv-choice-list">
      ${node.choices
        .map(
          (choice, index) => `
        <div class="adv-choice-card" data-choice-index="${index}">
          <div class="row gap-2">
            <span class="adv-choice-index">${index + 1}</span>
            <input class="input" data-choice-field="text" data-choice="${index}" maxlength="500"
                   value="${escapeHtml(choice.text)}" placeholder="${t("adv_editor.choice_text")}" />
            <button type="button" class="btn btn-xs btn-ghost" data-act="remove-choice" data-choice="${index}">✕</button>
          </div>
          <div class="adv-choice-meta">
            <label class="field">
              <span class="label">${t("adv_editor.goes_to")}</span>
              <select class="input input-sm" data-choice-field="target" data-choice="${index}">
                <option value="">${t("adv_editor.end_here")}</option>
                ${targets
                  .map(
                    (target) =>
                      `<option value="${escapeHtml(target.key)}" ${
                        target.key === choice.target ? "selected" : ""
                      }>${escapeHtml(
                        (target.text_html || "").replace(/<[^>]*>/g, " ").trim().slice(0, 30) ||
                          target.key,
                      )}${target.kind === "ending" ? " · " + t("adv_editor.ending") : ""}</option>`,
                  )
                  .join("")}
              </select>
            </label>
          </div>
          <div class="adv-choice-effects">
            <span class="label">${t("adv_editor.effects")}</span>
            ${effectsEditor(model, choice, index)}
          </div>
        </div>`,
        )
        .join("")}
      <button type="button" class="btn btn-sm" data-act="add-choice" ${node.choices.length >= 8 ? "disabled" : ""}>
        + ${t("adv_editor.add_choice")}
      </button>
    </div>`;
}

function outcomesEditor(model, node) {
  const attributes = model.adventure.attributes;
  return `
    <div class="adv-outcome-list">
      ${node.outcomes
        .map(
          (outcome, index) => `
        <div class="adv-outcome-card" data-outcome-index="${index}">
          <div class="row gap-2">
            <select class="input input-sm" data-outcome-field="kind" data-outcome="${index}">
              <option value="highest" ${outcome.kind === "highest" ? "selected" : ""}>${t("adv_editor.highest")}</option>
              <option value="lowest" ${outcome.kind === "lowest" ? "selected" : ""}>${t("adv_editor.lowest")}</option>
              <option value="range" ${outcome.kind === "range" ? "selected" : ""}>${t("adv_editor.range")}</option>
              <option value="default" ${outcome.kind === "default" ? "selected" : ""}>${t("adv_editor.fallback")}</option>
            </select>
            ${
              outcome.kind === "default"
                ? ""
                : `<select class="input input-sm" data-outcome-field="attribute" data-outcome="${index}">
                    ${attributes
                      .map(
                        (attribute) =>
                          `<option value="${escapeHtml(attribute.key)}" ${
                            attribute.key === outcome.attribute ? "selected" : ""
                          }>${escapeHtml(attribute.label)}</option>`,
                      )
                      .join("")}
                  </select>`
            }
            ${
              outcome.kind === "range"
                ? `<input class="input input-sm adv-range" type="number" data-outcome-field="range_min" data-outcome="${index}" value="${
                    outcome.range_min ?? 0
                  }" />
                   <span class="muted">→</span>
                   <input class="input input-sm adv-range" type="number" data-outcome-field="range_max" data-outcome="${index}" value="${
                     outcome.range_max ?? 0
                   }" />`
                : ""
            }
            <input class="input input-sm adv-priority" type="number" min="0" max="999" data-outcome-field="priority"
                   data-outcome="${index}" value="${outcome.priority}" title="${t("adv_editor.priority")}" />
            <button type="button" class="btn btn-xs btn-ghost" data-act="remove-outcome" data-outcome="${index}">✕</button>
          </div>
          <div class="rte-wrap">
            <div class="rte-toolbar" role="toolbar">
              ${[
                ["bold", "<b>B</b>"],
                ["italic", "<i>I</i>"],
                ["underline", "<u>U</u>"],
                ["insertUnorderedList", "•"],
                ["removeFormat", "✕"],
              ]
                .map(
                  ([cmd, label]) => `<button type="button" class="rte-btn" data-cmd="${cmd}">${label}</button>`,
                )
                .join("")}
            </div>
            <div class="rte" contenteditable="true" role="textbox" aria-multiline="true"
                 data-outcome-field="text_html" data-outcome="${index}">${outcome.text_html || ""}</div>
          </div>
        </div>`,
        )
        .join("")}
      <button type="button" class="btn btn-sm" data-act="add-outcome">+ ${t("adv_editor.add_outcome")}</button>
    </div>`;
}

function inspectorNode(model, node) {
  return `
    <div class="adv-inspector-section">
      <div class="row between">
        <h3>${node.kind === "ending" ? t("adv_editor.ending") : t("adv_editor.question")}</h3>
        <div class="row gap-2">
          ${
            model.adventure.start === node.key
              ? `<span class="pill">${t("adv_editor.start")}</span>`
              : `<button type="button" class="btn btn-xs btn-ghost" data-act="set-start">${t("adv_editor.make_start")}</button>`
          }
          <button type="button" class="btn btn-xs btn-ghost" data-act="toggle-kind">
            ${node.kind === "ending" ? t("adv_editor.make_question") : t("adv_editor.make_ending")}
          </button>
        </div>
      </div>

      <label class="field">
        <span class="label">${t("adv_editor.node_text")}</span>
        <div class="rte-wrap">
          <div class="rte-toolbar" role="toolbar">
            ${[
              ["bold", "<b>B</b>"],
              ["italic", "<i>I</i>"],
              ["underline", "<u>U</u>"],
              ["insertUnorderedList", "•"],
              ["insertOrderedList", "1."],
              ["formatBlock:h3", "H"],
              ["removeFormat", "✕"],
            ]
              .map(([cmd, label]) => `<button type="button" class="rte-btn" data-cmd="${cmd}">${label}</button>`)
              .join("")}
          </div>
          <div class="rte" contenteditable="true" role="textbox" aria-multiline="true"
               data-node-field="text_html">${node.text_html || ""}</div>
        </div>
      </label>

      <div class="row gap-2 adv-media-row">
        <label class="field grow">
          <span class="label">${t("adv_editor.image")}</span>
          <input class="input" data-node-field="image_path" value="${escapeHtml(node.image_path || "")}"
                 placeholder="/media/…" />
        </label>
        <label class="btn btn-sm btn-ghost adv-upload">
          ${t("adv_editor.upload")}
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden data-upload="image_path" />
        </label>
        ${node.image_path ? `<button type="button" class="btn btn-sm btn-ghost" data-act="clear-image">✕</button>` : ""}
      </div>
      ${
        node.image_path
          ? `<figure class="adv-preview">
               <img src="${escapeHtml(node.image_path)}" alt="" loading="lazy" />
             </figure>`
          : ""
      }

      ${
        node.kind === "ending"
          ? `
        <label class="field">
          <span class="label">${t("adv_editor.background")}</span>
          <div class="row gap-2">
            <input class="input grow" data-node-field="background_path" value="${escapeHtml(
              node.background_path || "",
            )}" placeholder="/media/…" />
            <label class="btn btn-sm btn-ghost adv-upload">
              ${t("adv_editor.upload")}
              <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden data-upload="background_path" />
            </label>
          </div>
          ${
            node.background_path
              ? `<figure class="adv-preview adv-preview-wide">
                   <img src="${escapeHtml(node.background_path)}" alt="" loading="lazy" />
                 </figure>`
              : ""
          }
        </label>
        <h4 class="mt-3">${t("adv_editor.outcomes")}</h4>
        <p class="muted small">${t("adv_editor.outcomes_help")}</p>
        ${outcomesEditor(model, node)}`
          : `
        <h4 class="mt-3">${t("adv_editor.choices")}</h4>
        <p class="muted small">${t("adv_editor.choices_help")}</p>
        ${choicesEditor(model, node)}`
      }
    </div>`;
}

function inspectorAttributes(model) {
  return `
    <div class="adv-inspector-section">
      <h3>${t("adv_editor.attributes")}</h3>
      <p class="muted small">${t("adv_editor.attributes_help")}</p>
      ${model.adventure.attributes
        .map(
          (attribute, index) => `
        <div class="adv-attribute-card">
          <div class="row gap-2">
            <input class="input" data-attribute-field="label" data-attribute="${index}" maxlength="80"
                   value="${escapeHtml(attribute.label)}" placeholder="${t("adv_editor.attribute_label")}" />
            <input class="input adv-key" data-attribute-field="key" data-attribute="${index}" maxlength="40"
                   value="${escapeHtml(attribute.key)}" title="${t("adv_editor.attribute_key")}"
                   aria-label="${t("adv_editor.attribute_key")}" readonly />
            <button type="button" class="btn btn-xs btn-ghost" data-act="remove-attribute"
                    data-attribute="${index}" ${
                      model.adventure.attributes.length <= 1 ? "disabled" : ""
                    }>✕</button>
          </div>
          <div class="adv-attribute-grid">
            <label class="field"><span class="label">${t("adv_editor.initial")}</span>
              <input class="input input-sm" type="number" data-attribute-field="initial_value"
                     data-attribute="${index}" value="${attribute.initial_value}" /></label>
            <label class="field"><span class="label">${t("adv_editor.min")}</span>
              <input class="input input-sm" type="number" data-attribute-field="min_value"
                     data-attribute="${index}" value="${attribute.min_value ?? ""}" placeholder="—" /></label>
            <label class="field"><span class="label">${t("adv_editor.max")}</span>
              <input class="input input-sm" type="number" data-attribute-field="max_value"
                     data-attribute="${index}" value="${attribute.max_value ?? ""}" placeholder="—" /></label>
            <label class="field"><span class="label">${t("adv_editor.death_at")}</span>
              <input class="input input-sm" type="number" data-attribute-field="death_at_or_below"
                     data-attribute="${index}" value="${attribute.death_at_or_below ?? ""}" placeholder="—" /></label>
            <label class="field"><span class="label">${t("adv_editor.victory_at")}</span>
              <input class="input input-sm" type="number" data-attribute-field="victory_at_or_above"
                     data-attribute="${index}" value="${attribute.victory_at_or_above ?? ""}" placeholder="—" /></label>
          </div>
        </div>`,
        )
        .join("")}
      <button type="button" class="btn btn-sm" data-act="add-attribute"
              ${model.adventure.attributes.length >= 12 ? "disabled" : ""}>+ ${t("adv_editor.add_attribute")}</button>
    </div>`;
}

function inspectorStory(model) {
  const nodes = model.adventure.nodes;
  return `
    <div class="adv-inspector-section">
      <h3>${t("adv_editor.story_settings")}</h3>
      <label class="field">
        <span class="label">${t("editor.description_label")}</span>
        <textarea class="input" rows="3" maxlength="2000" data-field="description"
                  placeholder="${t("editor.description_placeholder")}">${escapeHtml(model.description || "")}</textarea>
      </label>
      <label class="field">
        <span class="label">${t("adv_editor.start_node")}</span>
        <select class="input" data-story-field="start">
          ${nodes
            .filter((node) => node.kind === "question")
            .map(
              (node) =>
                `<option value="${escapeHtml(node.key)}" ${
                  node.key === model.adventure.start ? "selected" : ""
                }>${escapeHtml(
                  (node.text_html || "").replace(/<[^>]*>/g, " ").trim().slice(0, 40) || node.key,
                )}</option>`,
            )
            .join("")}
        </select>
      </label>

      <h4 class="mt-3">${t("adv_editor.story_timer")}</h4>
      <div class="row-wrap">
        <label class="field">
          <span class="label">${t("adv_editor.timer_mode")}</span>
          <select class="input" data-story-field="timer_mode">
            <option value="none" ${(model.adventure.timer_mode || "none") === "none" ? "selected" : ""}>${t("adv_editor.timer_none")}</option>
            <option value="global" ${model.adventure.timer_mode === "global" ? "selected" : ""}>${t("adv_editor.timer_global")}</option>
            <option value="per_node" ${model.adventure.timer_mode === "per_node" ? "selected" : ""}>${t("adv_editor.timer_per_node")}</option>
          </select>
        </label>
        <label class="field">
          <span class="label">${t("adv_editor.timer_seconds")}</span>
          <input class="input" type="number" min="10" max="7200" step="10"
                 data-story-field="time_limit_seconds" value="${Number(model.adventure.time_limit_seconds) || 120}" />
        </label>
      </div>
      <div class="row-wrap">
        <label class="field">
          <span class="label">${t("adv_editor.timeout_effect")}</span>
          <select class="input" data-story-field="timeout_effect">
            <option value="penalty" ${(model.adventure.timeout_effect || "penalty") === "penalty" ? "selected" : ""}>${t("adv_editor.timeout_penalty_effect")}</option>
            <option value="death" ${model.adventure.timeout_effect === "death" ? "selected" : ""}>${t("adv_editor.timeout_death_effect")}</option>
          </select>
        </label>
        <label class="field">
          <span class="label">${t("adv_editor.timeout_penalty")}</span>
          <input class="input" type="number" min="0" max="10" step="1"
                 data-story-field="timeout_penalty" value="${Number(model.adventure.timeout_penalty ?? 1)}" />
        </label>
        <label class="field">
          <span class="label">${t("adv_editor.timeout_attribute")}</span>
          <select class="input" data-story-field="timeout_penalty_attribute">
            <option value="">${t("adv_editor.timeout_attribute_auto")}</option>
            ${(model.adventure.attributes || [])
              .map(
                (attribute) =>
                  `<option value="${escapeHtml(attribute.key)}" ${
                    attribute.key === model.adventure.timeout_penalty_attribute ? "selected" : ""
                  }>${escapeHtml(attribute.label || attribute.key)}</option>`,
              )
              .join("")}
          </select>
        </label>
      </div>
      <p class="hint">${t("adv_editor.timer_hint")}</p>

      <h4 class="mt-3">${t("adv_editor.death_ending")}</h4>
      <div class="rte-wrap">
        <div class="rte-toolbar" role="toolbar">
          ${[
            ["bold", "<b>B</b>"],
            ["italic", "<i>I</i>"],
            ["removeFormat", "✕"],
          ]
            .map(([cmd, label]) => `<button type="button" class="rte-btn" data-cmd="${cmd}">${label}</button>`)
            .join("")}
        </div>
        <div class="rte" contenteditable="true" role="textbox" aria-multiline="true"
             data-story-field="death_text_html">${model.adventure.death_text_html || ""}</div>
      </div>
      <label class="field mt-2">
        <span class="label">${t("adv_editor.background")}</span>
        <div class="row gap-2">
          <input class="input grow" data-story-field="death_background_path"
                 value="${escapeHtml(model.adventure.death_background_path || "")}" placeholder="/media/…" />
          <label class="btn btn-sm btn-ghost adv-upload">${t("adv_editor.upload")}
            <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden data-upload="story:death_background_path" />
          </label>
        </div>
      </label>

      <h4 class="mt-3">${t("adv_editor.victory_ending")}</h4>
      <div class="rte-wrap">
        <div class="rte-toolbar" role="toolbar">
          ${[
            ["bold", "<b>B</b>"],
            ["italic", "<i>I</i>"],
            ["removeFormat", "✕"],
          ]
            .map(([cmd, label]) => `<button type="button" class="rte-btn" data-cmd="${cmd}">${label}</button>`)
            .join("")}
        </div>
        <div class="rte" contenteditable="true" role="textbox" aria-multiline="true"
             data-story-field="victory_text_html">${model.adventure.victory_text_html || ""}</div>
      </div>
      <label class="field mt-2">
        <span class="label">${t("adv_editor.background")}</span>
        <div class="row gap-2">
          <input class="input grow" data-story-field="victory_background_path"
                 value="${escapeHtml(model.adventure.victory_background_path || "")}" placeholder="/media/…" />
          <label class="btn btn-sm btn-ghost adv-upload">${t("adv_editor.upload")}
            <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden data-upload="story:victory_background_path" />
          </label>
        </div>
      </label>
    </div>`;
}

/* ------------------------------------------------------------------------- */
/* Page                                                                      */
/* ------------------------------------------------------------------------- */

export async function renderAdventureEditor({ id }) {
  const isNew = !id || id === "new";
  const root = document.createElement("div");
  root.className = "adv-editor";

  let model = emptyModel();
  if (!isNew) {
    try {
      const quiz = await api.get(`/api/v1/quizzes/${id}`);
      if (quiz.mode !== "adventure") {
        root.innerHTML = `<div class="empty"><h2>${t("adventure.not_a_story")}</h2>
          <a class="btn mt-2" href="/quizzes/${id}" data-link>${t("action.back_to_quiz")}</a></div>`;
        return root;
      }
      model = fromQuiz(quiz);
      normalizePositions(model);
    } catch (error) {
      root.innerHTML = `<div class="empty"><h2>${t("error.not_found")}</h2>
        <p class="muted">${escapeHtml(error.detail || "")}</p>
        <a class="btn mt-2" href="/dashboard" data-link>${t("nav.dashboard")}</a></div>`;
      return root;
    }
  }

  let selectedKey = model.adventure.start;
  let zoom = 1;
  // Viewport offset in screen pixels. Panning is a translate on the canvas, not
  // a scroll: the canvas is scaled, so a scroll container cannot describe what
  // the eye sees, and an emptied-of-range container simply refused to move.
  let panX = 0;
  let panY = 0;
  let tab = "node";
  let dirty = false;

  root.innerHTML = `
    <header class="adv-editor-bar">
      <a class="btn btn-ghost btn-sm" href="${isNew ? "/dashboard" : `/quizzes/${id}`}" data-link>←</a>
      <input class="input adv-title" data-field="title" maxlength="120"
             placeholder="${t("adv_editor.title_placeholder")}" value="${escapeHtml(model.title)}" />
      <span class="muted small adv-status"></span>
      <div class="spacer"></div>
      ${
        isNew
          ? ""
          : `<a class="btn btn-sm btn-ghost" href="/adventures/${id}/play" target="_blank" rel="noopener">${t(
              "adv_editor.preview",
            )}</a>`
      }
      <button type="button" class="btn btn-sm" data-act="save">${t("action.save")}</button>
    </header>

    <div class="adv-editor-body">
      <div class="adv-canvas-wrap">
        <div class="adv-canvas-toolbar" role="toolbar" aria-label="${t("adv_editor.toolbar")}">
          <button type="button" class="adv-tool" data-act="add-question" title="${t("adv_editor.add_question")}" aria-label="${t("adv_editor.add_question")}">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
          </button>
          <button type="button" class="adv-tool" data-act="add-ending" title="${t("adv_editor.add_ending")}" aria-label="${t("adv_editor.add_ending")}">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 21V4"/><path d="M5 5h11l-1.6 3L16 11H5z"/></svg>
          </button>
          <span class="adv-tool-sep" aria-hidden="true"></span>
          <button type="button" class="adv-tool" data-act="duplicate-node" title="${t("adv_editor.duplicate_node")}" aria-label="${t("adv_editor.duplicate_node")}">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M15 5.5A2.5 2.5 0 0 0 12.5 3H6a2.5 2.5 0 0 0-2.5 2.5V13"/></svg>
          </button>
          <button type="button" class="adv-tool is-danger" data-act="delete-selected" title="${t("adv_editor.delete_node")}" aria-label="${t("adv_editor.delete_node")}">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16"/><path d="M9 7V4.8A1.8 1.8 0 0 1 10.8 3h2.4A1.8 1.8 0 0 1 15 4.8V7"/><path d="M6 7l1 12.2A1.8 1.8 0 0 0 8.8 21h6.4a1.8 1.8 0 0 0 1.8-1.8L18 7"/></svg>
          </button>
          <span class="adv-tool-sep" aria-hidden="true"></span>
          <button type="button" class="adv-tool" data-act="relayout" title="${t("adv_editor.relayout_help")}" aria-label="${t("adv_editor.relayout")}">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="7" height="6" rx="1.6"/><rect x="14" y="4" width="7" height="6" rx="1.6"/><rect x="8.5" y="14" width="7" height="6" rx="1.6"/><path d="M6.5 10v2h11v-2"/><path d="M12 12v2"/></svg>
          </button>
          <button type="button" class="adv-tool" data-act="fit" title="${t("adv_editor.fit")}" aria-label="${t("adv_editor.fit")}">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9V5.8A1.8 1.8 0 0 1 5.8 4H9"/><path d="M15 4h3.2A1.8 1.8 0 0 1 20 5.8V9"/><path d="M20 15v3.2a1.8 1.8 0 0 1-1.8 1.8H15"/><path d="M9 20H5.8A1.8 1.8 0 0 1 4 18.2V15"/></svg>
          </button>
          <button type="button" class="adv-tool" data-act="zoom-in" title="${t("adv_editor.zoom_in")}" aria-label="${t("adv_editor.zoom_in")}">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.4 15.4L21 21"/><path d="M10.5 7.8v5.4M7.8 10.5h5.4"/></svg>
          </button>
          <button type="button" class="adv-tool" data-act="zoom-out" title="${t("adv_editor.zoom_out")}" aria-label="${t("adv_editor.zoom_out")}">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.4 15.4L21 21"/><path d="M7.8 10.5h5.4"/></svg>
          </button>
          <span class="adv-zoom-level" data-zoom-level aria-live="polite">100%</span>
        </div>
        <div class="adv-canvas-scroll">
          <div class="adv-canvas" data-canvas></div>
        </div>
        <ul class="adv-problems" data-problems role="alert" tabindex="-1" hidden></ul>
      </div>

      <aside class="adv-inspector">
        <div class="adv-tabs" role="tablist">
          <button type="button" class="adv-tab" data-tab="node" role="tab">${t("adv_editor.tab_node")}</button>
          <button type="button" class="adv-tab" data-tab="attributes" role="tab">${t("adv_editor.tab_attributes")}</button>
          <button type="button" class="adv-tab" data-tab="story" role="tab">${t("adv_editor.tab_story")}</button>
        </div>
        <div class="adv-inspector-body" data-inspector></div>
      </aside>
    </div>
  `;

  const canvas = root.querySelector("[data-canvas]");
  // The scrolling viewport around the canvas. Panning has to listen here, not
  // on the canvas: the canvas is scaled with `zoom`, so its painted box is
  // smaller than the viewport and a drag started in the margin never reached a
  // listener bound to the canvas itself.
  const scroll = canvas.closest(".adv-canvas-scroll");
  const inspector = root.querySelector("[data-inspector]");
  const statusEl = root.querySelector(".adv-status");

  // Title and description live in the top bar: wire them once, the bar is never
  // repainted by the inspector or the canvas.
  root.querySelector('[data-field="title"]')?.addEventListener("input", (event) => {
    model.title = event.target.value;
    markDirty();
  });
  const current = () => nodeByKey(model, selectedKey);

  const refreshStatus = () => {
    if (dirty) {
      statusEl.textContent = t("adv_editor.unsaved");
    } else if (autosavedAt) {
      statusEl.textContent = t("editor.autosave_saved", {
        time: autosavedAt.toLocaleTimeString(currentLanguage(), { hour: "2-digit", minute: "2-digit" }),
      });
    } else {
      statusEl.textContent = `${t("adv_editor.saved")} · ${t(`dash.status.${model.status}`)}`;
    }
    statusEl.classList.toggle("is-dirty", dirty);
  };

  /**
   * Zoom so the whole graph fits the visible canvas: a 2K screen should show
   * the story, not a postage stamp in the corner.
   */
  const fitToContent = () => {
    const nodes = model.adventure.nodes;
    if (!scroll || !nodes.length) return;
    const minX = Math.min(...nodes.map((node) => node.pos_x));
    const minY = Math.min(...nodes.map((node) => node.pos_y));
    const maxX = Math.max(...nodes.map((node) => node.pos_x + NODE_W));
    const maxY = Math.max(...nodes.map((node) => node.pos_y + blockHeight(node)));
    const pad = scroll.clientWidth < 760 ? 18 : 56;
    const availW = Math.max(240, scroll.clientWidth - pad * 2);
    const availH = Math.max(200, scroll.clientHeight - pad * 2);
    const scale = Math.min(1, availW / Math.max(1, maxX - minX), availH / Math.max(1, maxY - minY));
    // Never shrink below a readable scale: scrolling beats a postage stamp. A
    // phone needs a lower floor, otherwise the second column of the graph stays
    // off-screen on a 390 px viewport.
    const floor = scroll.clientWidth < 760 ? 0.4 : 0.75;
    zoom = Math.max(floor, Math.min(1, Math.floor(scale * 20) / 20));
    paintCanvas(canvas, model, selectedKey, zoom);
    panX = pad - minX * zoom;
    panY = pad - minY * zoom;
    applyView();
  };

  const paintTabs = () => {
    root.querySelectorAll(".adv-tab").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.tab === tab);
      button.setAttribute("aria-selected", String(button.dataset.tab === tab));
    });
  };

  /* Clamp the offset so the graph never drifts off the viewport and no empty
     gap opens beyond its bottom-right corner; content smaller than the viewport
     is centred rather than pinned to a corner. */
  const applyView = () => {
    const nodes = model.adventure.nodes;
    if (!nodes.length) {
      canvas.style.transform = `translate(0px, 0px) scale(${zoom})`;
      return;
    }
    const width = Math.max(...nodes.map((node) => node.pos_x + NODE_W)) * zoom;
    const height = Math.max(...nodes.map((node) => node.pos_y + blockHeight(node))) * zoom;
    const viewW = scroll.clientWidth;
    const viewH = scroll.clientHeight;
    const axis = (value, view, content) =>
      content <= view
        ? Math.round((view - content) / 2)
        : Math.min(0, Math.max(view - content, value));
    panX = axis(panX, viewW, width);
    panY = axis(panY, viewH, height);
    canvas.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
    // The label lives in the toolbar and every path that changes the scale goes
    // through here, so it can never drift out of sync with the drawing.
    const label = root.querySelector("[data-zoom-level]");
    if (label) label.textContent = `${Math.round(zoom * 100)}%`;
  };

  const paintAll = () => {
    paintCanvas(canvas, model, selectedKey, zoom);
    applyView();
    paintInspector();
    paintTabs();
    refreshStatus();
  };

  const paintInspector = () => {
    const node = current();
    if (tab === "attributes") inspector.innerHTML = inspectorAttributes(model);
    else if (tab === "story") inspector.innerHTML = inspectorStory(model);
    else if (node) inspector.innerHTML = inspectorNode(model, node);
    else
      inspector.innerHTML = `<div class="adv-inspector-section"><p class="muted">${t(
        "adv_editor.select_node",
      )}</p></div>`;
    wireInspector();
  };

  /* --- field plumbing --------------------------------------------------- */

  // Autosave: a story draft is written to the server while it is edited, so a
  // closed tab never loses a scene graph.
  let autosaveTimer = 0;
  let autosaveInFlight = false;
  let autosaveQueued = false;
  let autosavedAt = null;

  const flushDraft = async () => {
    if (autosaveInFlight) {
      autosaveQueued = true;
      return;
    }
    autosaveInFlight = true;
    try {
      const payload = storyPayload();
      const saved = model.id
        ? await api.put(`/api/v1/quizzes/${model.id}/draft`, payload)
        : await api.post("/api/v1/quizzes/draft", payload);
      model.id = saved.id;
      autosavedAt = new Date();
      if (id === "new" || !id) history.replaceState({}, "", `/adventures/${saved.id}/edit`);
      refreshStatus();
    } catch {
      statusEl.textContent = t("editor.autosave_error");
      statusEl.classList.add("is-dirty");
    } finally {
      autosaveInFlight = false;
      if (autosaveQueued) {
        autosaveQueued = false;
        scheduleAutosave(0);
      }
    }
  };

  const scheduleAutosave = (delay = 1500) => {
    window.clearTimeout(autosaveTimer);
    autosaveTimer = window.setTimeout(() => {
      if (!dirty) return;
      dirty = false;
      refreshStatus();
      void flushDraft();
    }, delay);
  };

  const markDirty = () => {
    dirty = true;
    refreshStatus();
    scheduleAutosave();
  };

  const wireInspector = () => {
    const node = current();

    inspector.querySelectorAll("[data-cmd]").forEach((button) => {
      button.addEventListener("click", () => {
        const cmd = button.dataset.cmd;
        if (cmd.startsWith("formatBlock:")) {
          document.execCommand("formatBlock", false, cmd.split(":")[1]);
        } else {
          document.execCommand(cmd, false, null);
        }
      });
    });

    if (node) {
      const text = inspector.querySelector('[data-node-field="text_html"]');
      text?.addEventListener("input", () => {
        node.text_html = text.innerHTML;
        markDirty();
      });
      text?.addEventListener("blur", () => {
        paintCanvas(canvas, model, selectedKey, zoom);
        applyView();
      });

      inspector.querySelectorAll('[data-node-field="image_path"], [data-node-field="background_path"]').forEach(
        (input) => {
          input.addEventListener("input", () => {
            node[input.dataset.nodeField] = input.value || null;
            markDirty();
          });
        },
      );

      for (const [index, choice] of node.choices.entries()) {
        inspector
          .querySelectorAll(`[data-choice-field="text"][data-choice="${index}"]`)
          .forEach((input) =>
            input.addEventListener("input", () => {
              choice.text = input.value;
              markDirty();
            }),
          );
        inspector
          .querySelectorAll(`[data-choice-field="target"][data-choice="${index}"]`)
          .forEach((select) =>
            select.addEventListener("change", () => {
              choice.target = select.value;
              markDirty();
              paintAll();
            }),
          );
      }

      node.choices.forEach((choice, choiceIndex) => {
        choice.effects.forEach((effect, effectIndex) => {
          const keySelect = inspector.querySelector(
            `[data-effect="attribute"][data-choice="${choiceIndex}"][data-effect-index="${effectIndex}"]`,
          );
          keySelect?.addEventListener("change", () => {
            effect.attribute = keySelect.value;
            markDirty();
          });
          const deltaInput = inspector.querySelector(
            `[data-effect="delta"][data-choice="${choiceIndex}"][data-effect-index="${effectIndex}"]`,
          );
          deltaInput?.addEventListener("input", () => {
            effect.delta = Number(deltaInput.value) || 0;
            markDirty();
          });
        });
      });

      node.outcomes.forEach((outcome, index) => {
        inspector.querySelectorAll(`[data-outcome-field][data-outcome="${index}"]`).forEach((field) => {
          const name = field.dataset.outcomeField;
          const apply = () => {
            if (name === "text_html") outcome.text_html = field.innerHTML;
            else if (["priority", "range_min", "range_max"].includes(name))
              outcome[name] = field.value === "" ? null : Number(field.value);
            else outcome[name] = field.value;
            markDirty();
          };
          field.addEventListener("input", apply);
          field.addEventListener("change", () => {
            apply();
            paintInspector();
          });
        });
      });
    }

    if (tab === "attributes") {
      model.adventure.attributes.forEach((attribute, index) => {
        inspector.querySelectorAll(`[data-attribute-field][data-attribute="${index}"]`).forEach((field) => {
          field.addEventListener("input", () => {
            const name = field.dataset.attributeField;
            if (["initial_value", "min_value", "max_value", "death_at_or_below", "victory_at_or_above"].includes(name))
              attribute[name] = field.value === "" ? null : Number(field.value);
            else attribute[name] = field.value;
            // The key is an internal identifier. Asking an author to type one is
            // asking them to guess a rule; it follows the label instead.
            if (name === "label") {
              const keyField = inspector.querySelector(
                `[data-attribute-field="key"][data-attribute="${index}"]`,
              );
              const previous = attribute.key;
              attribute.key = uniqueAttributeKey(slugifyKey(field.value), index, model.adventure.attributes);
              renameKeyEverywhere(model, previous, attribute.key);
              if (keyField) keyField.value = attribute.key;
            }
            markDirty();
          });
          field.addEventListener("change", () => {
            paintCanvas(canvas, model, selectedKey, zoom);
            applyView();
          });
        });
      });
    }

    if (tab === "story") {
      inspector.querySelector('[data-field="description"]')?.addEventListener("input", (event) => {
        model.description = event.target.value;
        markDirty();
      });
      inspector
        .querySelectorAll(
          '[data-story-field="timer_mode"], [data-story-field="time_limit_seconds"], [data-story-field="timeout_effect"], [data-story-field="timeout_penalty"], [data-story-field="timeout_penalty_attribute"]',
        )
        .forEach((field) => {
          field.addEventListener("change", () => {
            const key = field.dataset.storyField;
            if (key === "time_limit_seconds" || key === "timeout_penalty") {
              model.adventure[key] = Number(field.value) || 0;
            } else {
              model.adventure[key] = field.value;
            }
            markDirty();
          });
        });

      inspector.querySelector('[data-story-field="start"]')?.addEventListener("change", (event) => {
        model.adventure.start = event.target.value;
        markDirty();
        paintAll();
      });
      inspector.querySelectorAll('[data-story-field="death_text_html"], [data-story-field="victory_text_html"]').forEach(
        (block) =>
          block.addEventListener("input", () => {
            model.adventure[block.dataset.storyField] = block.innerHTML;
            markDirty();
          }),
      );
      inspector
        .querySelectorAll('[data-story-field="death_background_path"], [data-story-field="victory_background_path"]')
        .forEach((input) =>
          input.addEventListener("input", () => {
            model.adventure[input.dataset.storyField] = input.value || null;
            markDirty();
          }),
        );
    }

    inspector.querySelectorAll("[data-upload]").forEach((input) => {
      input.addEventListener("change", async () => {
        const file = input.files && input.files[0];
        if (!file) return;
        const target = input.dataset.upload;
        const progress = showUploadProgress(t("editor.uploading"), file.name);
        try {
          const uploaded = await uploadImage(file, (ratio) => progress.update(ratio));
          progress.finishing();
          const path = uploaded.path || uploaded.url || "";
          if (target.startsWith("story:")) {
            model.adventure[target.split(":")[1]] = path;
          } else if (node) {
            node[target] = path;
          }
          markDirty();
          paintAll();
          toast(t("adv_editor.upload_done"), "success");
        } catch (error) {
          toast(error.detail || t("error.generic"), "error");
        } finally {
          progress.done();
        }
      });
    });
  };

  /* --- canvas interactions ---------------------------------------------- */

  const addNode = (kind) => {
    const nodes = model.adventure.nodes;
    const key = uid(kind === "ending" ? "end" : "q");
    const anchor = current() || nodes[0];
    const node = {
      key,
      kind,
      text_html: kind === "ending" ? `<p>${t("adv_editor.default_ending")}</p>` : `<p>${t("adv_editor.default_scene")}</p>`,
      translations: {},
      image_path: null,
      background_path: null,
      pos_x: (anchor ? anchor.pos_x : 80) + NODE_W + 120,
      pos_y: (anchor ? anchor.pos_y : 120) + nodes.length * 30,
      choices:
        kind === "ending"
          ? []
          : [
              { key: uid("c"), text: t("adv_editor.default_choice_a"), translations: {}, target: "", effects: [] },
              { key: uid("c"), text: t("adv_editor.default_choice_b"), translations: {}, target: "", effects: [] },
            ],
      outcomes:
        kind === "ending"
          ? [
              {
                kind: "default",
                attribute: null,
                range_min: null,
                range_max: null,
                text_html: `<p>${t("adv_editor.default_outcome")}</p>`,
                translations: {},
                priority: 0,
              },
            ]
          : [],
    };
    nodes.push(node);
    selectedKey = key;
    tab = "node";
    markDirty();
    paintAll();
  };

  const deleteNode = async (key) => {
    if (model.adventure.nodes.length <= 1) {
      toast(t("adv_editor.delete_blocked"), "error");
      return;
    }
    const node = nodeByKey(model, key);
    if (!node) return;
    const referring = model.adventure.nodes.filter(
      (candidate) => candidate.key !== key && candidate.choices.some((choice) => choice.target === key),
    );
    const confirmed = await confirmDialog(
      t("adv_editor.delete_node"),
      referring.length
        ? t("adv_editor.delete_confirm_linked", { n: referring.length })
        : t("adv_editor.delete_confirm"),
      t("action.delete"),
    );
    if (!confirmed) return;
    model.adventure.nodes = model.adventure.nodes.filter((candidate) => candidate.key !== key);
    for (const candidate of model.adventure.nodes) {
      for (const choice of candidate.choices) {
        if (choice.target === key) choice.target = "";
      }
    }
    if (model.adventure.start === key) {
      model.adventure.start = model.adventure.nodes[0].key;
    }
    selectedKey = model.adventure.nodes[0].key;
    markDirty();
    paintAll();
    toast(t("adv_editor.node_deleted"), "success");
  };

  const closeNodeMenu = () => {
    root.querySelector(".adv-node-menu")?.remove();
  };

  const openNodeMenu = (key, clientX, clientY) => {
    closeNodeMenu();
    const node = nodeByKey(model, key);
    if (!node) return;
    const menu = document.createElement("div");
    menu.className = "adv-node-menu";
    menu.setAttribute("role", "menu");
    menu.innerHTML = `
      <button type="button" class="adv-menu-item" data-menu="start">${t("adv_editor.set_start")}</button>
      ${
        node.kind === "ending"
          ? ""
          : `<button type="button" class="adv-menu-item" data-menu="child">${t("adv_editor.add_child")}</button>`
      }
      <button type="button" class="adv-menu-item is-danger" data-menu="delete">${t("adv_editor.delete_node")}</button>
      <hr class="adv-menu-sep" />
      <button type="button" class="adv-menu-item" data-menu="close">${t("action.close")}</button>`;
    root.appendChild(menu);
    menu.style.left = `${Math.min(clientX, window.innerWidth - 220)}px`;
    menu.style.top = `${Math.min(clientY, window.innerHeight - 180)}px`;
    menu.addEventListener("click", (event) => {
      const item = event.target.closest("[data-menu]");
      if (!item) return;
      const action = item.dataset.menu;
      closeNodeMenu();
      if (action === "start") {
        model.adventure.start = key;
        markDirty();
        paintAll();
      } else if (action === "child") {
        addChild(key);
      } else if (action === "delete") {
        void deleteNode(key);
      }
    });
    // A click anywhere else dismisses the menu.
    window.setTimeout(() => {
      const dismiss = (event) => {
        if (event.target.closest(".adv-node-menu")) return;
        closeNodeMenu();
        document.removeEventListener("pointerdown", dismiss, true);
      };
      document.addEventListener("pointerdown", dismiss, true);
    }, 0);
  };

  canvas.addEventListener("contextmenu", (event) => {
    const element = event.target.closest(".adv-node");
    if (!element) return;
    event.preventDefault();
    selectedKey = element.dataset.node;
    paintAll();
    openNodeMenu(selectedKey, event.clientX, event.clientY);
  });

  const addChild = (fromKey) => {
    const parent = nodeByKey(model, fromKey);
    const node = {
      key: uid("q"),
      kind: "question",
      text_html: `<p>${t("adv_editor.default_scene")}</p>`,
      translations: {},
      image_path: null,
      background_path: null,
      pos_x: (parent ? parent.pos_x : 0) + NODE_W + 140,
      pos_y: (parent ? parent.pos_y : 0) + 40,
      choices: [
        { key: uid("c"), text: t("adv_editor.default_choice_a"), translations: {}, target: "", effects: [] },
        { key: uid("c"), text: t("adv_editor.default_choice_b"), translations: {}, target: "", effects: [] },
      ],
      outcomes: [],
    };
    model.adventure.nodes.push(node);
    // Link the first free choice of the parent to the new node.
    const free = (parent?.choices || []).find((choice) => !choice.target);
    if (free) free.target = node.key;
    selectedKey = node.key;
    markDirty();
    paintAll();
  };

  let drag = null;
  // Panning: grabbing empty space moves the viewport, like a workflow canvas.
  let pan = null;

  /* --- linking a choice to a node with the mouse ------------------------- */

  let linking = null;

  const canvasPoint = (event) => {
    const rect = canvas.getBoundingClientRect();
    return { x: (event.clientX - rect.left) / zoom, y: (event.clientY - rect.top) / zoom };
  };

  const paintGhostLink = (fromKey, choiceIndex, point) => {
    const svg = canvas.querySelector("svg.adv-edges");
    const node = nodeByKey(model, fromKey);
    if (!svg || !node) return;
    let ghost = svg.querySelector("#adv-link-ghost");
    if (!ghost) {
      ghost = document.createElementNS("http://www.w3.org/2000/svg", "path");
      ghost.setAttribute("id", "adv-link-ghost");
      ghost.setAttribute("class", "adv-edge is-ghost");
      // The ghost must never swallow the pointer: dropping relies on
      // elementFromPoint finding the node underneath.
      ghost.setAttribute("pointer-events", "none");
      svg.appendChild(ghost);
    }
    const from = outPort(node, choiceIndex);
    const bend = Math.max(60, Math.abs(point.x - from.x) / 2);
    ghost.setAttribute(
      "d",
      `M ${from.x} ${from.y} L ${from.x + 18} ${from.y} C ${from.x + 18 + bend} ${from.y}, ${
        point.x - bend
      } ${point.y}, ${point.x} ${point.y}`,
    );
  };

  const clearGhostLink = () => {
    canvas.querySelector("#adv-link-ghost")?.remove();
    canvas.classList.remove("is-linking");
    root.classList.remove("is-linking");
  };

  const finishLink = (event) => {
    const link = linking;
    linking = null;
    clearGhostLink();
    if (!link) return;
    const dropped = document.elementFromPoint(event.clientX, event.clientY)?.closest(".adv-node");
    const targetKey = dropped?.dataset.node;
    const node = nodeByKey(model, link.fromKey);
    const choice = node?.choices[link.choiceIndex];
    if (!choice) return;
    if (!targetKey) {
      toast(t("adv_editor.link_cancelled"), "info");
      return;
    }
    if (targetKey === link.fromKey) {
      toast(t("adv_editor.link_self"), "error");
      return;
    }
    choice.target = targetKey;
    markDirty();
    paintAll();
    toast(t("adv_editor.link_created"), "success");
  };

  // Hovering an answer highlights its own link, so crossing curves stay
  // unambiguous without moving the blocks around.
  const highlightEdge = (edgeId) => {
    canvas.classList.toggle("has-hot", Boolean(edgeId));
    canvas.querySelectorAll("path.adv-edge").forEach((path) => {
      path.classList.toggle("is-hot", Boolean(edgeId) && path.dataset.edge === edgeId);
    });
    canvas.querySelectorAll(".adv-row").forEach((row) => {
      row.classList.toggle("is-hot", Boolean(edgeId) && row.dataset.edge === edgeId);
    });
  };
  canvas.addEventListener("pointerover", (event) => {
    const row = event.target.closest(".adv-row");
    if (row) highlightEdge(row.dataset.edge);
  });
  canvas.addEventListener("pointerout", (event) => {
    const row = event.target.closest(".adv-row");
    if (row) highlightEdge(null);
  });
  canvas.addEventListener("pointerleave", () => highlightEdge(null));

  scroll.addEventListener("pointerdown", (event) => {
    // A link can start from the numbered port or from the answer row itself:
    // grabbing an answer and dropping it on the next block is the whole gesture.
    const port = event.target.closest(".adv-port") || event.target.closest(".adv-row");
    if (port) {
      event.preventDefault();
      linking = {
        fromKey: port.dataset.node,
        choiceIndex: Number(port.dataset.port ?? port.dataset.row ?? 0),
      };
      selectedKey = port.dataset.node;
      canvas.classList.add("is-linking");
      root.classList.add("is-linking");
      paintGhostLink(linking.fromKey, linking.choiceIndex, canvasPoint(event));
      return;
    }
    const handle = event.target.closest(".adv-node");
    if (!handle) {
      // Empty space: pan the canvas instead of doing nothing.
      if (event.button !== 0) return;
      pan = {
        startX: event.clientX,
        startY: event.clientY,
        left: panX,
        top: panY,
        pointerId: event.pointerId,
      };
      canvas.classList.add("is-panning");
      root.classList.add("is-panning");
      // Keep receiving the gesture when the pointer leaves the viewport.
      try {
        scroll.setPointerCapture(event.pointerId);
      } catch {
        /* capture is best effort */
      }
      event.preventDefault();
      return;
    }
    const key = handle.dataset.node;
    if (event.target.closest("button")) return;
    const node = nodeByKey(model, key);
    selectedKey = key;
    drag = {
      key,
      startX: event.clientX,
      startY: event.clientY,
      originX: node.pos_x,
      originY: node.pos_y,
      moved: false,
    };
    handle.setPointerCapture(event.pointerId);
    handle.classList.add("is-dragging");
    // Selecting a block always shows its form: leaving the previous node's
    // fields on screen made the canvas feel disconnected from the inspector.
    if (tab !== "node") {
      tab = "node";
      paintTabs();
    }
    paintInspector();
    canvas.querySelectorAll(".adv-node").forEach((item) => {
      item.classList.toggle("is-selected", item.dataset.node === key);
    });
  });

  scroll.addEventListener("pointermove", (event) => {
    if (pan) {
      // 1:1 with the pointer: the translate runs outside the scale, so a mouse
      // pixel is a graph pixel whatever the zoom.
      panX = pan.left + (event.clientX - pan.startX);
      panY = pan.top + (event.clientY - pan.startY);
      applyView();
      return;
    }
    if (linking) {
      paintGhostLink(linking.fromKey, linking.choiceIndex, canvasPoint(event));
      return;
    }
    if (!drag) return;
    const node = nodeByKey(model, drag.key);
    const dx = (event.clientX - drag.startX) / zoom;
    const dy = (event.clientY - drag.startY) / zoom;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.moved = true;
    node.pos_x = Math.max(0, snap(drag.originX + dx));
    node.pos_y = Math.max(0, snap(drag.originY + dy));
    const element = canvas.querySelector(`[data-node="${drag.key}"]`);
    if (element) {
      element.style.left = `${node.pos_x}px`;
      element.style.top = `${node.pos_y}px`;
    }
    paintEdgesOnly();
  });

  const endPan = () => {
    if (!pan) return;
    if (pan.pointerId !== undefined && scroll.hasPointerCapture?.(pan.pointerId)) {
      scroll.releasePointerCapture(pan.pointerId);
    }
    pan = null;
    canvas.classList.remove("is-panning");
    root.classList.remove("is-panning");
  };

  const endDrag = () => {
    if (!drag) return;
    canvas.querySelector(`[data-node="${drag.key}"]`)?.classList.remove("is-dragging");
    if (drag.moved) {
      markDirty();
      paintAll();
    }
    drag = null;
  };

  scroll.addEventListener("pointerup", (event) => {
    endPan();
    if (linking) {
      finishLink(event);
      return;
    }
    endDrag();
  });
  window.addEventListener("pointerup", endPan);
  scroll.addEventListener("pointercancel", () => {
    linking = null;
    clearGhostLink();
    endPan();
    endDrag();
  });

  const paintEdgesOnly = () => {
    const svg = canvas.querySelector("svg.adv-edges");
    if (!svg) return;
    const byKey = Object.fromEntries(model.adventure.nodes.map((node) => [node.key, node]));
    const paths = [];
    for (const node of model.adventure.nodes) {
      node.choices.forEach((choice, index) => {
        const target = byKey[choice.target];
        if (target) {
          paths.push(
            `<path class="adv-edge" data-from="${escapeHtml(node.key)}" data-edge="${escapeHtml(
              node.key,
            )}:${index}" marker-end="url(#adv-arrow)" d="${edgePath(node, target, index)}"></path>`,
          );
        }
      });
    }
    const defs = svg.querySelector("defs");
    svg.innerHTML = "";
    if (defs) svg.appendChild(defs);
    svg.insertAdjacentHTML("beforeend", paths.join(""));
  };

  /* --- toolbar actions -------------------------------------------------- */

  const showZoom = () => applyView();
  /* Zooming around the middle of the viewport keeps the block the author was
     looking at under their eyes instead of throwing the graph off-screen. */
  const zoomAroundCenter = (next) => {
    const cx = scroll.clientWidth / 2;
    const cy = scroll.clientHeight / 2;
    const ratio = next / zoom;
    panX = cx - (cx - panX) * ratio;
    panY = cy - (cy - panY) * ratio;
    zoom = next;
    paintCanvas(canvas, model, selectedKey, zoom);
    applyView();
    showZoom();
  };

  root.querySelector('[data-act="zoom-in"]').addEventListener("click", () => {
    zoomAroundCenter(Math.min(1.6, Math.round((zoom + 0.1) * 100) / 100));
  });
  root.querySelector('[data-act="zoom-out"]').addEventListener("click", () => {
    zoomAroundCenter(Math.max(0.4, Math.round((zoom - 0.1) * 100) / 100));
  });
  showZoom();
  root.querySelector('[data-act="fit"]').addEventListener("click", () => {
    fitToContent();
  });

  root.querySelector('[data-act="add-question"]').addEventListener("click", () => addNode("question"));
  root.querySelector('[data-act="add-ending"]').addEventListener("click", () => addNode("ending"));

  /** Copy the selected block beside itself: n8n's duplicate, minus the links. */
  const duplicateNode = () => {
    const source = current();
    if (!source) return;
    const copy = structuredClone(source);
    copy.key = uid(source.kind === "ending" ? "end" : "q");
    copy.pos_x = source.pos_x + NODE_W + 80;
    copy.pos_y = source.pos_y + 40;
    copy.choices = copy.choices.map((choice) => ({ ...choice, key: uid("c"), target: "" }));
    model.adventure.nodes.push(copy);
    selectedKey = copy.key;
    markDirty();
    paintAll();
    toast(t("adv_editor.duplicated"), "success");
  };
  root.querySelector('[data-act="duplicate-node"]')?.addEventListener("click", duplicateNode);
  root.querySelector('[data-act="delete-selected"]')?.addEventListener("click", () => {
    if (!selectedKey) {
      toast(t("adv_editor.select_first"), "error");
      return;
    }
    if (selectedKey === model.adventure.start) {
      toast(t("adv_editor.delete_start_blocked"), "error");
      return;
    }
    void deleteNode(selectedKey);
  });

  root.querySelector('.adv-title').addEventListener("input", (event) => {
    model.title = event.target.value;
    markDirty();
  });

  root.querySelectorAll(".adv-tab").forEach((button) => {
    button.addEventListener("click", () => {
      tab = button.dataset.tab;
      paintAll();
      if (tab !== "node" && canvas.querySelector(".adv-node.is-selected")) {
        canvas.querySelectorAll(".adv-node").forEach((item) => item.classList.remove("is-selected"));
      }
    });
  });

  root.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-act]");
    if (!button) return;
    const node = current();

    switch (button.dataset.act) {
      case "add-child":
        addChild(button.dataset.node);
        break;
      case "delete-node":
        void deleteNode(button.dataset.node);
        break;
      case "set-start":
        model.adventure.start = node.key;
        markDirty();
        paintAll();
        break;
      case "toggle-kind": {
        if (node.kind === "question") {
          node.kind = "ending";
          node.choices = [];
          if (!node.outcomes.length) {
            node.outcomes.push({
              kind: "default",
              attribute: null,
              range_min: null,
              range_max: null,
              text_html: `<p>${t("adv_editor.default_outcome")}</p>`,
              translations: {},
              priority: 0,
            });
          }
          // Never leave dangling links pointing at a node that lost its choices.
          model.adventure.nodes.forEach((item) => {
            item.choices.forEach((choice) => {
              if (choice.target === node.key) choice.target = "";
            });
          });
        } else {
          node.kind = "question";
          node.outcomes = [];
          node.choices = [
            { key: uid("c"), text: t("adv_editor.default_choice_a"), translations: {}, target: "", effects: [] },
            { key: uid("c"), text: t("adv_editor.default_choice_b"), translations: {}, target: "", effects: [] },
          ];
        }
        markDirty();
        paintAll();
        break;
      }
      case "clear-image":
        node.image_path = null;
        markDirty();
        paintAll();
        break;
      case "add-choice":
        if (node.choices.length < 8) {
          node.choices.push({
            key: uid("c"),
            text: "",
            translations: {},
            target: "",
            effects: [],
          });
          markDirty();
          paintInspector();
        }
        break;
      case "remove-choice":
        if (node.choices.length > 2) {
          node.choices.splice(Number(button.dataset.choice), 1);
          markDirty();
          paintAll();
        }
        break;
      case "add-effect":
        node.choices[Number(button.dataset.choice)].effects.push({
          attribute: model.adventure.attributes[0].key,
          delta: 1,
        });
        markDirty();
        paintInspector();
        break;
      case "remove-effect":
        node.choices[Number(button.dataset.choice)].effects.splice(Number(button.dataset.effectIndex), 1);
        markDirty();
        paintInspector();
        break;
      case "add-outcome":
        node.outcomes.push({
          kind: "highest",
          attribute: model.adventure.attributes[0].key,
          range_min: null,
          range_max: null,
          text_html: "<p></p>",
          translations: {},
          priority: node.outcomes.length,
        });
        markDirty();
        paintInspector();
        break;
      case "remove-outcome":
        if (node.outcomes.length > 1) {
          node.outcomes.splice(Number(button.dataset.outcome), 1);
          markDirty();
          paintInspector();
        }
        break;
      case "add-attribute":
        if (model.adventure.attributes.length < 12) {
          model.adventure.attributes.push({
            key: `attribute_${model.adventure.attributes.length + 1}`,
            label: `${t("adv_editor.attribute")} ${model.adventure.attributes.length + 1}`,
            translations: {},
            initial_value: 0,
            min_value: null,
            max_value: null,
            death_at_or_below: null,
            victory_at_or_above: null,
          });
          markDirty();
          paintInspector();
        }
        break;
      case "remove-attribute": {
        const index = Number(button.dataset.attribute);
        const removed = model.adventure.attributes[index];
        const approved = await confirmDialog(
          t("adv_editor.remove_attribute"),
          t("adv_editor.confirm_remove_attribute"),
          t("action.remove"),
        );
        if (approved) {
          model.adventure.attributes.splice(index, 1);
          const keys = new Set(model.adventure.attributes.map((attribute) => attribute.key));
          model.adventure.nodes.forEach((item) => {
            item.choices.forEach((choice) => {
              choice.effects = choice.effects.filter((effect) => keys.has(effect.attribute));
            });
            item.outcomes = item.outcomes.filter(
              (outcome) => !outcome.attribute || keys.has(outcome.attribute),
            );
          });
          void removed;
          markDirty();
          paintAll();
        }
        break;
      }
      case "relayout":
        autoLayout(model, { narrow: narrowCanvas() });
        markDirty();
        paintAll();
        requestAnimationFrame(() => fitToContent());
        toast(t("adv_editor.relayout_done"), "info");
        break;
      case "save":
        await save();
        break;
      default:
        break;
    }
  });

  /* --- save -------------------------------------------------------------- */

  const storyPayload = () => ({
      title: model.title.trim(),
      description: model.description || "",
      mode: "adventure",
      default_language: model.default_language || currentLanguage(),
      is_public: model.is_public,
      adventure: {
        ...model.adventure,
        nodes: model.adventure.nodes.map((node) => ({
          ...node,
          choices: node.choices.map((choice) => ({
            ...choice,
            target: choice.target || null,
            effects: choice.effects.filter((effect) => Number(effect.delta) !== 0),
          })),
          outcomes: node.outcomes,
        })),
      },
    });

  const save = async () => {
    const button = root.querySelector('[data-act="save"]');
    const problems = root.querySelector("[data-problems]");
    button.disabled = true;
    button.textContent = t("common.saving");

    const payload = storyPayload();
    try {
      const saved = model.id
        ? await api.put(`/api/v1/quizzes/${model.id}`, payload)
        : await api.post("/api/v1/quizzes", payload);
      model = fromQuiz(saved);
      dirty = false;
      problems.hidden = true;
      if (!id || id === "new") {
        navigate(`/adventures/${saved.id}/edit`, { replace: true });
        return;
      }
      toast(t("adv_editor.saved_toast"), "success");
      paintAll();
    } catch (error) {
      const detail = error.payload && error.payload.detail;
      let entries;
      if (Array.isArray(detail)) {
        entries = detail.map((item) => ({
          where: Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(" · ") : "",
          message: humanizeProblem((item.msg || "").replace(/^Value error, /, "")),
        }));
      } else if (typeof detail === "string") {
        entries = [{ where: "", message: humanizeProblem(detail) }];
      } else {
        entries = [{ where: "", message: error.detail || t("error.generic") }];
      }
      problems.innerHTML = entries
        .map((entry) => `<li>${entry.where ? `<strong>${escapeHtml(entry.where)}</strong> — ` : ""}${escapeHtml(entry.message)}</li>`)
        .join("");
      problems.hidden = false;
      // The block sits under the canvas: without this it opened behind the
      // sticky action bar and the author only saw the first line of it.
      problems.scrollIntoView({ block: "center", behavior: "smooth" });
      problems.focus({ preventScroll: true });
      toast(t("adv_editor.fix_problems"), "error");
    } finally {
      button.disabled = false;
      button.textContent = t("action.save");
    }
  };

  const flushOnExit = () => {
    if (!dirty) return;
    window.clearTimeout(autosaveTimer);
    const path = model.id ? `/api/v1/quizzes/${model.id}/draft` : "/api/v1/quizzes/draft";
    keepaliveRequest(model.id ? "PUT" : "POST", path, storyPayload());
    dirty = false;
  };
  window.addEventListener("pagehide", flushOnExit);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushOnExit();
  });
  window.onbeforeunload = (event) => {
    if (!dirty) return undefined;
    flushOnExit();
    event.preventDefault();
    event.returnValue = "";
    return "";
  };

  paintAll();
  // A hand-placed graph drifts into a pile: untangle it once on open, then let
  // the author own the layout.
  const narrowCanvas = () =>
    Boolean(scroll && scroll.clientWidth > 0 && scroll.clientWidth < 760);
  requestAnimationFrame(() => {
    if (blocksOverlap(model) || narrowCanvas()) {
      autoLayout(model, { narrow: narrowCanvas() });
      paintAll();
    }
    fitToContent();
  });
  return root;
}
