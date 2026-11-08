// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* Wiki structure: the menu as a tree, reordered by drag and drop.

   One list, one save: every drop recomputes the whole order and posts it, so
   the server never has to guess what a partial move meant. Keyboard buttons do
   the same moves for people who do not use a mouse. */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { navigate } from "../router.js";
import { state } from "../store.js";
import { escapeHtml, toast } from "../ui.js";

export async function renderWikiStructure(params) {
  const root = document.createElement("section");
  await _structure(root, params);
  return root;
}

function flatten(pages) {
  const children = new Map();
  for (const page of pages) {
    const key = page.parent_id || 0;
    if (!children.has(key)) children.set(key, []);
    children.get(key).push(page);
  }
  for (const list of children.values()) {
    list.sort((a, b) => (a.position - b.position) || a.title.localeCompare(b.title));
  }
  const flat = [];
  const walk = (parentId, depth) => {
    for (const page of children.get(parentId) || []) {
      flat.push({ page, depth });
      walk(page.id, depth + 1);
    }
  };
  walk(0, 0);
  return flat;
}

function descendantsOf(pageId, items) {
  const found = new Set();
  let growing = true;
  while (growing) {
    growing = false;
    for (const item of items) {
      if (item.parent_id === pageId && !found.has(item.id)) {
        found.add(item.id);
        growing = true;
      }
    }
    for (const id of [...found]) {
      for (const item of items) {
        if (item.parent_id === id && !found.has(item.id)) {
          found.add(item.id);
          growing = true;
        }
      }
    }
  }
  return found;
}

async function _structure(root, params) {
  const wikiId = Number(params.id);
  if (!state.user) {
    navigate(`/login?next=${encodeURIComponent(location.pathname)}`, { replace: true });
    return;
  }

  let wiki = null;
  try {
    wiki = await api.get(`/api/v1/wiki/${wikiId}`);
  } catch (error) {
    root.innerHTML = `<div class="card empty">${escapeHtml(error.detail || t("wiki.not_found"))}</div>`;
    return;
  }
  if (!wiki.can_write) {
    root.innerHTML = `<div class="card empty">${escapeHtml(t("wiki.structure_readonly"))}</div>`;
    return;
  }

  let pages = wiki.pages.map((page) => ({
    id: page.id,
    title: page.title,
    slug: page.slug,
    parent_id: page.parent_id || null,
    position: page.position || 0,
  }));

  root.className = "wiki-structure-page";
  root.innerHTML = `
    <section class="page-head">
      <div>
        <h1>${escapeHtml(t("wiki.structure"))}</h1>
        <p class="muted">${escapeHtml(t("wiki.structure_help"))}</p>
      </div>
      <div class="row-wrap end">
        <a class="btn btn-ghost" data-link href="/wiki/${wikiId}">${escapeHtml(t("action.back"))}</a>
        <button class="btn btn-primary" id="tree-save" disabled>${escapeHtml(t("action.save"))}</button>
      </div>
    </section>
    <div class="tree-card card">
      <p class="muted small tree-tip">${escapeHtml(t("wiki.structure_tip"))}</p>
      <ul class="tree-list" id="tree-list" role="tree" aria-label="${escapeHtml(t("wiki.structure"))}"></ul>
    </div>
  `;

  const list = root.querySelector("#tree-list");
  const saveButton = root.querySelector("#tree-save");
  let dirty = false;
  let dragId = null;
  let dropHint = null;

  const markDirty = () => {
    dirty = true;
    saveButton.disabled = false;
  };

  const render = () => {
    const flat = flatten(pages);
    list.replaceChildren();
    for (const { page, depth } of flat) {
      const item = document.createElement("li");
      item.className = "tree-item";
      item.dataset.id = String(page.id);
      item.dataset.depth = String(depth);
      item.setAttribute("role", "treeitem");
      item.setAttribute("aria-level", String(depth + 1));
      item.draggable = true;
      item.style.setProperty("--depth", String(depth));
      if (dropHint && dropHint.id === page.id) item.classList.add(`is-drop-${dropHint.mode}`);

      const grip = document.createElement("span");
      grip.className = "tree-grip";
      grip.setAttribute("aria-hidden", "true");
      grip.textContent = "⠿";

      const title = document.createElement("a");
      title.className = "tree-title";
      title.href = `/wiki/${wikiId}/p/${encodeURIComponent(page.slug)}`;
      title.dataset.link = "";
      title.textContent = page.title;

      const depthBadge = document.createElement("span");
      depthBadge.className = "tree-depth";
      depthBadge.textContent = `n${depth + 1}`;
      if (!depth) depthBadge.hidden = true;

      const actions = document.createElement("span");
      actions.className = "tree-actions";
      const moves = [
        ["up", "↑", t("wiki.move_up")],
        ["down", "↓", t("wiki.move_down")],
        ["indent", "→", t("wiki.move_in")],
        ["outdent", "←", t("wiki.move_out")],
      ];
      for (const [action, glyph, label] of moves) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn-icon tree-move";
        button.dataset.move = action;
        button.dataset.id = String(page.id);
        button.title = label;
        button.setAttribute("aria-label", `${label} · ${page.title}`);
        button.textContent = glyph;
        actions.appendChild(button);
      }

      item.append(grip, title, depthBadge, actions);
      list.appendChild(item);
    }
  };

  /* -- the model moves -------------------------------------------------- */
  const order = () => flatten(pages).map(({ page }) => page.id);
  const byId = (id) => pages.find((page) => page.id === id);

  const renumber = (sequence, parents) => {
    const counts = new Map();
    const next = sequence.map((id, index) => {
      const parent = parents.get(id) || null;
      const key = parent || 0;
      const position = counts.get(key) || 0;
      counts.set(key, position + 1);
      return { ...byId(id), parent_id: parent, position, index };
    });
    pages = next;
  };

  // Where a page lands when it becomes the child of ``target``: after the
  // target's whole subtree, so it reads as the last child and not the first.
  const insertionInside = (sequence, targetId, parents) => {
    const shaped = pages.map((page) => ({ ...page, parent_id: parents.get(page.id) ?? page.parent_id }));
    const inside = descendantsOf(targetId, shaped);
    let cursor = sequence.indexOf(targetId) + 1;
    while (cursor < sequence.length && inside.has(sequence[cursor])) cursor += 1;
    return cursor;
  };

  const move = (id, action) => {
    const sequence = order();
    const parents = new Map(pages.map((page) => [page.id, page.parent_id || null]));
    const index = sequence.indexOf(id);
    if (index < 0) return;
    const target = sequence[index - 1];

    if (action === "up" || action === "down") {
      const siblings = sequence.filter((other) => (parents.get(other) || null) === (parents.get(id) || null));
      const at = siblings.indexOf(id);
      const swapWith = action === "up" ? siblings[at - 1] : siblings[at + 1];
      if (swapWith === undefined) return;
      const a = sequence.indexOf(id);
      const b = sequence.indexOf(swapWith);
      [sequence[a], sequence[b]] = [sequence[b], sequence[a]];
      renumber(sequence, parents);
    } else if (action === "indent") {
      if (target === undefined) return;
      parents.set(id, target);
      sequence.splice(index, 1);
      sequence.splice(insertionInside(sequence, target, parents), 0, id);
      renumber(sequence, parents);
    } else if (action === "outdent") {
      const parentId = parents.get(id);
      if (!parentId) return;
      parents.set(id, parents.get(parentId) || null);
      sequence.splice(index, 1);
      const shaped = pages.map((page) => ({ ...page, parent_id: parents.get(page.id) }));
      const inside = descendantsOf(parentId, shaped);
      const parentIndex = sequence.indexOf(parentId);
      let insertAt = parentIndex + 1;
      while (insertAt < sequence.length && inside.has(sequence[insertAt])) insertAt += 1;
      sequence.splice(insertAt, 0, id);
      renumber(sequence, parents);
    }
    markDirty();
    render();
  };

  list.addEventListener("click", (event) => {
    const button = event.target.closest("[data-move]");
    if (!button) return;
    event.preventDefault();
    move(Number(button.dataset.id), button.dataset.move);
  });

  /* -- drag and drop ---------------------------------------------------- */
  const dropModeFor = (row, clientY) => {
    const box = row.getBoundingClientRect();
    const ratio = (clientY - box.top) / box.height;
    if (ratio < 0.3) return "before";
    if (ratio > 0.7) return "after";
    return "into";
  };

  list.addEventListener("dragstart", (event) => {
    const row = event.target.closest(".tree-item");
    if (!row) return;
    dragId = Number(row.dataset.id);
    row.classList.add("is-dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", String(dragId));
  });

  list.addEventListener("dragend", () => {
    dragId = null;
    dropHint = null;
    render();
  });

  list.addEventListener("dragover", (event) => {
    if (dragId === null) return;
    const row = event.target.closest(".tree-item");
    if (!row) return;
    const targetId = Number(row.dataset.id);
    if (targetId === dragId) return;
    event.preventDefault();
    const mode = dropModeFor(row, event.clientY);
    dropHint = { id: targetId, mode };
    for (const item of list.children) {
      item.classList.remove("is-drop-before", "is-drop-after", "is-drop-into");
    }
    row.classList.add(`is-drop-${mode}`);
  });

  list.addEventListener("drop", (event) => {
    if (dragId === null) return;
    const row = event.target.closest(".tree-item");
    if (!row) return;
    event.preventDefault();
    const targetId = Number(row.dataset.id);
    const mode = dropModeFor(row, event.clientY);
    const sequence = order();
    const parents = new Map(pages.map((page) => [page.id, page.parent_id || null]));
    if (targetId === dragId || descendantsOf(dragId, pages).has(targetId)) {
      toast(t("wiki.structure_cycle"), "error");
      dragId = null;
      dropHint = null;
      render();
      return;
    }
    const from = sequence.indexOf(dragId);
    sequence.splice(from, 1);
    const at = sequence.indexOf(targetId);
    if (mode === "into") {
      parents.set(dragId, targetId);
      sequence.splice(insertionInside(sequence, targetId, parents), 0, dragId);
    } else {
      parents.set(dragId, parents.get(targetId) || null);
      sequence.splice(mode === "before" ? at : at + 1, 0, dragId);
    }
    renumber(sequence, parents);
    dragId = null;
    dropHint = null;
    markDirty();
    render();
  });

  saveButton.addEventListener("click", async () => {
    saveButton.disabled = true;
    try {
      const response = await api.put(`/api/v1/wiki/${wikiId}/tree`, {
        pages: flatten(pages).map(({ page }) => ({
          id: page.id,
          parent_id: page.parent_id || null,
          position: page.position,
        })),
      });
      pages = response.pages.map((page) => ({ ...page }));
      dirty = false;
      toast(t("wiki.structure_saved"), "success");
      render();
    } catch (error) {
      saveButton.disabled = false;
      toast(error.detail || t("error.generic"), "error");
    }
  });

  window.addEventListener("beforeunload", (event) => {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  render();
}
