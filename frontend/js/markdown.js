// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Markdown <-> HTML for the wiki editor.
 *
 * The server owns the canonical rendering (`backend/app/wiki.py`): this module
 * only powers the live preview and the WYSIWYG round-trip. It is deliberately
 * small — no HTML passthrough, no plugin — so that what the author sees is a
 * faithful picture of what the reader will get, and never a richer one.
 */

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ESCAPES[char]);
}

const PALETTE = new Set(["red", "orange", "amber", "green", "teal", "blue", "violet", "pink", "muted"]);

/** Underline and text colour, the two decorations markdown does not have.
 *
 * The editor writes {u}…{/u} and {c:red}…{/c} so the source stays plain text and
 * the server can rebuild the same tags after its sanitiser.
 */
export function applyInlineStyles(html) {
  const underlined = String(html).replace(/\{u\}([\s\S]*?)\{\/u\}/g, "<u>$1</u>");
  const sized = underlined
    .replace(/\{s:(sm|lg|xl)\}([\s\S]*?)\{\/s\}/g, '<span class="sz-$1">$2</span>')
    .replace(/\{f:(serif|sans|mono|script)\}([\s\S]*?)\{\/f\}/g, '<span class="ff-$1">$2</span>');
  return sized.replace(/\{c:(#[0-9a-fA-F]{6}|[a-z]{3,10})\}([\s\S]*?)\{\/c\}/g, (match, value, inner) => {
    if (/<\/p>/.test(inner)) return match;
    if (value.startsWith("#")) return `<span class="c-hex" data-hex="${value.toLowerCase()}">${inner}</span>`;
    if (!PALETTE.has(value.toLowerCase())) return match;
    return `<span class="c-${value.toLowerCase()}">${inner}</span>`;
  });
}

/** Paint a custom colour: CSP forbids style attributes, the CSSOM does not. */
export function paintCustomColors(root) {
  root.querySelectorAll("[data-hex]").forEach((node) => {
    const value = node.getAttribute("data-hex") || "";
    if (/^#[0-9a-fA-F]{6}$/.test(value)) node.style.color = value;
  });
}

/** Inline markdown: code, emphasis, links, wikilinks, images, footnotes. */
export function inlineMarkdown(raw, { pages = {} } = {}) {
  let text = escapeHtml(raw);
  const codes = [];
  text = text.replace(/`([^`]+)`/g, (_, code) => {
    codes.push(`<code>${code}</code>`);
    return `\u0000${codes.length - 1}\u0000`;
  });

  // [[Target|Label]] — resolved against the wiki's page list.
  text = text.replace(/\[\[([^\]|]{1,180})(?:\|([^\]]{1,180}))?\]\]/g, (_, target, label) => {
    const name = (label || target).trim();
    const slug = pages[target.trim().toLowerCase()];
    // data-wikilink-target is what makes the WYSIWYG round-trip faithful: without
    // it, saving from the rich view would rewrite [[dns]] as a plain link to a
    // creation page, silently dropping every wikilink of the document.
    const written = escapeHtml(target.trim());
    if (slug) {
      return `<a class="wikilink" data-link data-wikilink-target="${written}" href="/wiki/p/${encodeURIComponent(slug)}">${name}</a>`;
    }
    return `<a class="wikilink is-missing" data-wikilink-target="${written}" href="/wiki/new?title=${encodeURIComponent(name)}">${name}</a>`;
  });

  text = text.replace(
    /!\[([^\]]*)\]\(([^)\s]+)\)(?:\{width=(\d{1,4})(%?)\})?/g,
    (_, alt, src, width, percent) => {
      const safe = /^(https?:\/\/|\/)/.test(src) ? src : "";
      if (!safe) return alt;
      const size = width ? ` width="${width}${percent || ""}"` : "";
      return `<img src="${safe}" alt="${alt}"${size} loading="lazy" />`;
    },
  );
  text = text.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) => {
    const external = /^https?:\/\//i.test(href);
    const safe = /^(https?:\/\/|\/|#|mailto:)/i.test(href) ? href : "";
    if (!safe) return label;
    return external
      ? `<a href="${safe}" target="_blank" rel="noopener noreferrer">${label}</a>`
      : `<a data-link href="${safe}">${label}</a>`;
  });

  text = text
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
    .replace(/~~([^~]+)~~/g, "<del>$1</del>")
    .replace(/\[\^(\d{1,3})\]/g, '<sup class="footnote-ref">[$1]</sup>');
  text = applyInlineStyles(text);
  text = text.replace(/\u0000(\d+)\u0000/g, (_, index) => codes[Number(index)] || "");
  return text;
}

function renderTable(lines) {
  const rows = lines.map((line) =>
    line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()),
  );
  const head = rows[0] || [];
  const body = rows.slice(2);
  const headHtml = head.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join("");
  const bodyHtml = body
    .map((cells) => `<tr>${cells.map((cell) => `<td>${inlineMarkdown(cell)}</td>`).join("")}</tr>`)
    .join("");
  return `<table><thead><tr>${headHtml}</tr></thead><tbody>${bodyHtml}</tbody></table>`;
}

/** Block level markdown to HTML. Footnote definitions collect at the end. */
export function markdownToHtml(markdown, options = {}) {
  const lines = String(markdown ?? "").replace(/\r\n?/g, "\n").split("\n");
  const html = [];
  const footnotes = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (/^```/.test(line.trim())) {
      const language = line.trim().slice(3).trim();
      const body = [];
      index += 1;
      while (index < lines.length && !/^```/.test(lines[index].trim())) {
        body.push(lines[index]);
        index += 1;
      }
      index += 1;
      html.push(
        `<pre><code${language ? ` class="language-${escapeHtml(language)}"` : ""}>${escapeHtml(
          body.join("\n"),
        )}</code></pre>`,
      );
      continue;
    }
    // An embedded questionnaire, adventure or deck is one block, not a line of
    // text: the editor renders it as the same box the insert menu creates, so
    // reopening a page shows what it holds instead of a raw marker.
    const embed = /^\{(quiz|adventure|deck):(\d{1,9})\}$/.exec(line.trim());
    if (embed) {
      const marker = `{${embed[1]}:${embed[2]}}`;
      html.push(
        `<div class="wiki-embed" data-embed="${embed[1]}" data-id="${embed[2]}" contenteditable="false">${marker}</div>`,
      );
      index += 1;
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const text = heading[2].trim();
      const anchor = text.toLowerCase().replace(/[^a-z0-9\u00c0-\u017f]+/g, "-").replace(/^-|-$/g, "");
      html.push(`<h${level} id="${anchor}">${inlineMarkdown(text, options)}</h${level}>`);
      index += 1;
      continue;
    }
    if (/^(---|\*\*\*|___)\s*$/.test(line)) {
      html.push("<hr />");
      index += 1;
      continue;
    }
    if (/^>\s?/.test(line)) {
      const body = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        body.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      html.push(`<blockquote>${markdownToHtml(body.join("\n"), options)}</blockquote>`);
      continue;
    }
    if (/^\|.*\|/.test(line) && /^\|[\s:|-]+\|?$/.test(lines[index + 1] || "")) {
      const block = [];
      while (index < lines.length && /^\|/.test(lines[index])) {
        block.push(lines[index]);
        index += 1;
      }
      html.push(renderTable(block));
      continue;
    }
    if (/^(\s*)([-*+]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (index < lines.length && /^(\s*)([-*+]|\d+\.)\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^(\s*)([-*+]|\d+\.)\s+/, ""));
        index += 1;
      }
      const tag = ordered ? "ol" : "ul";
      html.push(
        `<${tag}>${items.map((item) => `<li>${inlineMarkdown(item, options)}</li>`).join("")}</${tag}>`,
      );
      continue;
    }
    const footnote = /^\[\^(\d{1,3})\]:\s*(.*)$/.exec(line);
    if (footnote) {
      footnotes.push({ number: footnote[1], text: footnote[2] });
      index += 1;
      continue;
    }
    const paragraph = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^(#{1,6}\s|>|\||```|---|\*\*\*|(\s*)([-*+]|\d+\.)\s|\[\^\d+\]:)/.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    // A line can start like a block (a stray table separator, a "----" rule)
    // without being consumed by any branch above. Without this guard index
    // never moves and the renderer spins forever on that page.
    if (!paragraph.length) {
      paragraph.push(lines[index]);
      index += 1;
    }
    let joined = paragraph.join(" ").trim();
    const classes = [];
    // Block markers wrap the whole line, and they nest in any order: peel until
    // none is left, so `{a:center}{s:lg}…{/s}{/a}` keeps both.
    const blockMarkers = [
      [/^\{a:(left|center|right|justify)\}([\s\S]*?)\{\/a\}$/, "al"],
      [/^\{s:(sm|lg|xl)\}([\s\S]*?)\{\/s\}$/, "sz"],
      [/^\{f:(serif|sans|mono|script)\}([\s\S]*?)\{\/f\}$/, "ff"],
    ];
    for (let pass = 0; pass < 3; pass += 1) {
      let moved = false;
      for (const [pattern, prefix] of blockMarkers) {
        const found = pattern.exec(joined);
        if (found) {
          classes.push(`${prefix}-${found[1]}`);
          joined = found[2].trim();
          moved = true;
        }
      }
      if (!moved) break;
    }
    html.push(
      `<p${classes.length ? ` class="${classes.join(" ")}"` : ""}>${inlineMarkdown(joined, options)}</p>`,
    );
  }

  if (footnotes.length) {
    const items = footnotes
      .map(
        (note) =>
          `<li id="fn${note.number}">${inlineMarkdown(note.text, options)} <a href="#fnref${note.number}">↩︎</a></li>`,
      )
      .join("");
    html.push(`<section class="footnotes"><hr /><ol>${items}</ol></section>`);
  }
  return html.join("\n");
}

function childrenToMarkdown(node, depth = 0) {
  return Array.from(node.childNodes)
    .map((child) => nodeToMarkdown(child, depth))
    .join("");
}

function inlineChildren(node) {
  return Array.from(node.childNodes)
    .map((child) => inlineNode(child))
    .join("");
}

function inlineNode(node) {
  if (node.nodeType === Node.TEXT_NODE) return node.nodeValue.replace(/\s+/g, " ");
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  const tag = node.tagName.toLowerCase();
  switch (tag) {
    case "strong":
    case "b":
      return `**${inlineChildren(node)}**`;
    case "em":
    case "i":
      return `*${inlineChildren(node)}*`;
    case "del":
    case "s":
      return `~~${inlineChildren(node)}~~`;
    case "u":
      return `{u}${inlineChildren(node)}{/u}`;
    case "span": {
      if (node.classList.contains("c-hex")) {
        const hex = node.getAttribute("data-hex") || "";
        return /^#[0-9a-fA-F]{6}$/.test(hex) ? `{c:${hex}}${inlineChildren(node)}{/c}` : inlineChildren(node);
      }
      const classes = Array.from(node.classList);
      const size = classes.find((name) => /^sz-(sm|lg|xl)$/.test(name));
      if (size) return `{s:${size.slice(3)}}${inlineChildren(node)}{/s}`;
      const font = classes.find((name) => /^ff-(serif|sans|mono|script)$/.test(name));
      if (font) return `{f:${font.slice(3)}}${inlineChildren(node)}{/f}`;
      const colour = classes.find((name) => /^c-[a-z]+$/.test(name));
      return colour ? `{c:${colour.slice(2)}}${inlineChildren(node)}{/c}` : inlineChildren(node);
    }
    case "code":
      return `\`${node.textContent}\``;
    case "br":
      return "  \n";
    case "img": {
      const src = node.getAttribute("src") || "";
      const alt = node.getAttribute("alt") || "";
      const width = node.getAttribute("width");
      const size = width && /^\d{1,4}%?$/.test(width) ? `{width=${width}}` : "";
      return `![${alt}](${src})${size}`;
    }
    case "a": {
      const href = node.getAttribute("href") || "";
      if (node.dataset.wikilinkTarget) {
        const written = inlineChildren(node);
        const target = node.dataset.wikilinkTarget;
        return written && written !== target ? `[[${target}|${written}]]` : `[[${target}]]`;
      }
      const label = inlineChildren(node) || href;
      return href ? `[${label}](${href})` : label;
    }
    case "sup":
      if (/footnote-ref/.test(node.className)) return node.textContent.replace(/[[\]]/g, "");
      return `<sup>${inlineChildren(node)}</sup>`;
    default:
      return inlineChildren(node);
  }
}

function nodeToMarkdown(node, depth = 0) {
  if (node.nodeType === Node.TEXT_NODE) return node.nodeValue.replace(/\s+/g, " ");
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  const tag = node.tagName.toLowerCase();
  switch (tag) {
    case "h1":
    case "h2":
    case "h3":
    case "h4":
    case "h5":
    case "h6": {
      // A heading is one line: a line break typed inside it cannot be expressed,
      // and letting it through produced a bare newline the renderer dropped --
      // the text after the break disappeared from the saved page.
      const inner = inlineChildren(node)
        .replace(/[ \t]*\n[ \t]*/g, " ")
        .replace(/\s{2,}/g, " ")
        .trim();
      return `${"#".repeat(Number(tag[1]))} ${inner}\n\n`;
    }
    case "p": {
      // Alignment, size and typeface belong to the block: the markers wrap it.
      const names = Array.from(node.classList);
      const align = names.find((name) => /^al-(left|center|right|justify)$/.test(name));
      const size = names.find((name) => /^sz-(sm|lg|xl)$/.test(name));
      const font = names.find((name) => /^ff-(serif|sans|mono|script)$/.test(name));
      let inner = inlineChildren(node).trim();
      if (size) inner = `{s:${size.slice(3)}}${inner}{/s}`;
      if (font) inner = `{f:${font.slice(3)}}${inner}{/f}`;
      if (align) inner = `{a:${align.slice(3)}}${inner}{/a}`;
      return `${inner}\n\n`;
    }
    // An image the author inserted sits in a block of its own: keep it, and
    // keep the width marker the size handle writes.
    case "img": {
      const src = node.getAttribute("src") || "";
      if (!src) return "";
      const alt = node.getAttribute("alt") || "";
      const width = node.getAttribute("width");
      const size = width && /^\d{1,4}%?$/.test(width) ? `{width=${width}}` : "";
      return `![${alt}](${src})${size}\n\n`;
    }
    case "figure": {
      const image = node.querySelector("img");
      const caption = node.querySelector("figcaption");
      if (!image) return caption ? `${inlineChildren(caption).trim()}\n\n` : "";
      const markdown = nodeToMarkdown(image, depth);
      const legend = caption ? `*${inlineChildren(caption).trim()}*\n\n` : "";
      return `${markdown}${legend}`;
    }
    // Chromium wraps the line created by Enter in a <div> when the caret sits
    // in a heading, and a paste brings its own <div>s: they are paragraphs,
    // not inline runs glued to the next block.
    case "div":
      if (node.classList.contains("wiki-embed")) {
        // An embedded questionnaire is a marker, not content: keep it on its
        // own block so the server can rebuild the container. The kind travels
        // with the id — a deck of revision cards written back as `{quiz:12}`
        // would show a stranger's questionnaire under the author's hands.
        const KINDS = ["quiz", "adventure", "deck"];
        const kind = KINDS.includes(node.dataset.embed) ? node.dataset.embed : "quiz";
        const id = node.dataset.id || "";
        return /^\d{1,9}$/.test(id) ? `{${kind}:${id}}\n\n` : "";
      }
    // fall through
    case "section":
    case "article":
    case "header":
    case "footer":
    case "details":
    case "summary": {
      const names = Array.from(node.classList);
      const align = names.find((name) => /^al-(left|center|right|justify)$/.test(name));
      const size = names.find((name) => /^sz-(sm|lg|xl)$/.test(name));
      const font = names.find((name) => /^ff-(serif|sans|mono|script)$/.test(name));
      let inner = childrenToMarkdown(node, depth).trim();
      if (!inner) return "";
      if (size) inner = `{s:${size.slice(3)}}${inner}{/s}`;
      if (font) inner = `{f:${font.slice(3)}}${inner}{/f}`;
      if (align) inner = `{a:${align.slice(3)}}${inner}{/a}`;
      return `${inner}\n\n`;
    }
    case "br":
      return "  \n";
    case "hr":
      return "---\n\n";
    case "blockquote":
      return `${childrenToMarkdown(node, depth + 1)
        .trim()
        .split("\n")
        .map((line) => `> ${line}`)
        .join("\n")}\n\n`;
    case "ul":
    case "ol": {
      const ordered = tag === "ol";
      const items = Array.from(node.children).map((item, position) => {
        const marker = ordered ? `${position + 1}. ` : "- ";
        const body = childrenToMarkdown(item, depth + 1).trim().replace(/\n/g, "\n  ");
        return `${marker}${body}`;
      });
      return `${items.join("\n")}\n\n`;
    }
    case "pre": {
      const code = node.querySelector("code");
      const language = (code && (code.className.match(/language-([\w-]+)/) || [])[1]) || "";
      return `\`\`\`${language}\n${(code || node).textContent.replace(/\n$/, "")}\n\`\`\`\n\n`;
    }
    case "table": {
      const rows = Array.from(node.querySelectorAll("tr")).map((row) =>
        Array.from(row.children).map((cell) => inlineChildren(cell).trim()),
      );
      if (!rows.length) return "";
      const head = `| ${rows[0].join(" | ")} |`;
      const rule = `| ${rows[0].map(() => "---").join(" | ")} |`;
      const body = rows.slice(1).map((cells) => `| ${cells.join(" | ")} |`);
      return `${[head, rule, ...body].join("\n")}\n\n`;
    }
    case "section": {
      if (/footnotes/.test(node.className)) {
        return `${Array.from(node.querySelectorAll("li"))
          .map((item) => {
            const number = (item.id || "").replace(/[^0-9]/g, "");
            const text = item.innerHTML
              .replace(/<a[^>]*>↩︎<\/a>/g, "")
              .trim();
            return `[^${number}]: ${text}`;
          })
          .join("\n")}\n`;
      }
      return childrenToMarkdown(node, depth);
    }
    default: {
      if (INLINE_TAGS.has(tag)) return inlineNode(node);
      const inner = childrenToMarkdown(node, depth);
      return BLOCK_TAGS.has(tag) ? `${inner.trim()}\n\n` : inner;
    }
  }
}

/* Inline elements carry their markers (`**`, `[](...)`, `{c:red}`) in
   `inlineNode`. `nodeToMarkdown` used to send everything it did not recognise
   through `childrenToMarkdown`, which drops those markers: a link or a bold run
   inside a list item came back as plain text and the href was lost on save. */
const INLINE_TAGS = new Set([
  "a", "strong", "b", "em", "i", "u", "s", "del", "code", "sup", "sub", "mark", "kbd", "span", "br", "img",
]);

const BLOCK_TAGS = new Set([
  "div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li",
  "table", "thead", "tbody", "tr", "pre", "blockquote", "hr", "figure",
  "section", "article", "header", "footer", "details", "summary",
]);

/** Drop the whitespace the markup keeps between two blocks.
 *
 * `markdownToHtml` joins blocks with newlines, so re-parsing that HTML leaves a
 * text node made of layout whitespace between two elements. Serializing it adds
 * one leading space to every following line, which then defeats block detection
 * (a table header no longer starts with "|") and silently rewrites the page.
 * Spaces inside a paragraph are content and stay.
 */
function stripLayoutWhitespace(node) {
  const children = Array.from(node.childNodes);
  const hasBlock = children.some(
    (child) => child.nodeType === Node.ELEMENT_NODE && BLOCK_TAGS.has(child.tagName.toLowerCase()),
  );
  for (const child of children) {
    if (hasBlock && child.nodeType === Node.TEXT_NODE && !child.nodeValue.trim()) {
      child.remove();
    } else if (child.nodeType === Node.ELEMENT_NODE) {
      stripLayoutWhitespace(child);
    }
  }
}

/** WYSIWYG -> markdown. Inverse of `markdownToHtml`, for the save path. */
export function htmlToMarkdown(html) {
  // An inert document: it parses markup without running a script, fetching an
  // image or firing a handler, which a detached div does not promise.
  const container = new DOMParser().parseFromString(html || "", "text/html").body;
  if (!container) return "\n";
  stripLayoutWhitespace(container);
  return childrenToMarkdown(container)
    .replace(/\n{3,}/g, "\n\n")
    .trim()
    .concat("\n");
}
