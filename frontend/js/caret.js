// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Caret geometry shared by the editor, the live carets and drag-and-drop.

   A character offset means the same thing in markdown and in the WYSIWYG view:
   the position in the document's text. This module converts between that offset
   and pixels, in both directions, for a textarea (through a mirror element) and
   for a contenteditable (through a Range). */

const MIRROR_PROPS = [
  "boxSizing",
  "width",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "borderTopWidth",
  "borderRightWidth",
  "borderBottomWidth",
  "borderLeftWidth",
  "fontFamily",
  "fontSize",
  "fontWeight",
  "fontStyle",
  "letterSpacing",
  "lineHeight",
  "textTransform",
  "wordSpacing",
  "tabSize",
  "whiteSpace",
  "wordBreak",
  "overflowWrap",
];

function mirrorFor(textarea) {
  let mirror = document.getElementById("ol-caret-mirror");
  if (!mirror) {
    mirror = document.createElement("div");
    mirror.id = "ol-caret-mirror";
    mirror.setAttribute("aria-hidden", "true");
    document.body.appendChild(mirror);
  }
  const computed = window.getComputedStyle(textarea);
  for (const prop of MIRROR_PROPS) mirror.style[prop] = computed[prop];
  mirror.style.position = "absolute";
  mirror.style.visibility = "hidden";
  mirror.style.left = "-9999px";
  mirror.style.top = "0";
  mirror.style.whiteSpace = "pre-wrap";
  mirror.style.overflowWrap = "break-word";
  return mirror;
}

/** Pixel position of a character offset inside a textarea, relative to it. */
export function pointInTextarea(textarea, offset) {
  const mirror = mirrorFor(textarea);
  const text = textarea.value.slice(0, Math.max(0, Math.min(offset, textarea.value.length)));
  mirror.textContent = text;
  const marker = document.createElement("span");
  marker.textContent = "\u200b";
  mirror.appendChild(marker);
  const rect = textarea.getBoundingClientRect();
  const left = marker.offsetLeft - textarea.scrollLeft + (rect.width - textarea.clientWidth) / 2;
  const top = marker.offsetTop - textarea.scrollTop;
  return { x: left, y: top, height: parseFloat(window.getComputedStyle(textarea).lineHeight) || 20 };
}

/** Character offset under a point, for dropping text where the mouse is. */
export function offsetInTextarea(textarea, clientX, clientY) {
  const mirror = mirrorFor(textarea);
  const value = textarea.value;
  const rect = textarea.getBoundingClientRect();
  const x = clientX - rect.left + textarea.scrollLeft;
  const y = clientY - rect.top + textarea.scrollTop;
  mirror.textContent = "";
  let best = 0;
  let bestDistance = Infinity;
  // Binary search would need measured prefixes; a coarse scan is fast enough
  // for a few thousand characters and never wrong by more than one line.
  const step = Math.max(1, Math.floor(value.length / 400));
  for (let offset = 0; offset <= value.length; offset += step) {
    mirror.textContent = value.slice(0, offset);
    const marker = document.createElement("span");
    marker.textContent = "\u200b";
    mirror.appendChild(marker);
    const dy = marker.offsetTop - y;
    const dx = marker.offsetLeft - x;
    const distance = Math.abs(dy) * 1000 + Math.abs(dx);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = offset;
    }
  }
  return best;
}

/* -- contenteditable ------------------------------------------------------ */
function textNodes(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
  const nodes = [];
  let node = walker.nextNode();
  while (node) {
    nodes.push(node);
    node = walker.nextNode();
  }
  return nodes;
}

/** Character offset of the caret inside a contenteditable. */
export function offsetOfSelection(root) {
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount) return 0;
  const range = selection.getRangeAt(0).cloneRange();
  const before = range.cloneRange();
  before.selectNodeContents(root);
  before.setEnd(range.startContainer, range.startOffset);
  return before.toString().length;
}

/** Put the caret back at a character offset inside a contenteditable. */
export function setSelectionOffset(root, offset) {
  const target = Math.max(0, offset);
  let remaining = target;
  const nodes = textNodes(root);
  const range = document.createRange();
  for (const node of nodes) {
    const length = node.textContent.length;
    if (remaining <= length) {
      range.setStart(node, remaining);
      range.collapse(true);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      return true;
    }
    remaining -= length;
  }
  if (nodes.length) {
    const last = nodes[nodes.length - 1];
    range.setStart(last, last.textContent.length);
    range.collapse(true);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  } else {
    range.selectNodeContents(root);
    range.collapse(false);
  }
  return false;
}

/** Pixel position of a character offset inside a contenteditable, relative to it. */
export function pointInEditable(root, offset) {
  const nodes = textNodes(root);
  let remaining = Math.max(0, offset);
  const rootRect = root.getBoundingClientRect();
  for (const node of nodes) {
    const length = node.textContent.length;
    if (remaining <= length) {
      const range = document.createRange();
      range.setStart(node, Math.min(remaining, length));
      range.collapse(true);
      const rect = range.getBoundingClientRect();
      return {
        x: rect.left - rootRect.left + root.scrollLeft,
        y: rect.top - rootRect.top + root.scrollTop,
        height: rect.height || parseFloat(window.getComputedStyle(root).lineHeight) || 20,
      };
    }
    remaining -= length;
  }
  return { x: 0, y: root.scrollHeight, height: 20 };
}

/** Character offset nearest a point inside a contenteditable. */
export function offsetInEditable(root, clientX, clientY) {
  const selection = window.getSelection();
  const range =
    typeof document.caretRangeFromPoint === "function"
      ? document.caretRangeFromPoint(clientX, clientY)
      : null;
  if (!range) {
    // No hit: append at the end rather than losing the drop.
    return root.textContent.length;
  }
  if (!root.contains(range.startContainer)) return root.textContent.length;
  const before = range.cloneRange();
  before.selectNodeContents(root);
  try {
    before.setEnd(range.startContainer, range.startOffset);
  } catch {
    return root.textContent.length;
  }
  const offset = before.toString().length;
  if (selection) selection.removeAllRanges();
  return offset;
}

/** Move a caret offset when a splice is applied before it. */
export function shiftOffset(offset, pos, remove, insert) {
  if (offset <= pos) return offset;
  if (offset >= pos + remove) return offset - remove + insert.length;
  // Inside the replaced region: land at the end of the replacement.
  return pos + insert.length;
}
