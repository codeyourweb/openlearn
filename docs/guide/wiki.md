---
layout: doc
title: The wiki — write, version, cross-link, publish
description: >-
  Create a wiki space in OpenLearn, write pages in Markdown, follow the history, restore a
  version, cross-link pages, suggest an edit, and request publication.
permalink: /guide/wiki/
---

<p class="doc-eyebrow">Guide · Write, version, publish</p>

# The wiki

A wiki is a space of pages linked to one another, with a history. It is where knowledge gets
written down: a fact sheet, a procedure, a course, a manual.

## Creating a space

1. **New wiki** (`/wiki/new`).
2. Enter the **title**, a short **description** and the **language** of the space.
3. Submit: the space is created with a first home page.

You are the **owner** of the space. You can then invite **contributors** (they write) or
**administrators** (they manage the space and its members).

## Writing a page

**New page** opens the editor (`/wiki/<id>/edit`). The title serves as the address: "Volcanoes"
becomes `/wiki/<id>/p/volcanoes`.

The editor is **Markdown**, with a preview. A few basics:

| To get | Write |
| --- | --- |
| A section heading | `## Heading` |
| A list | `- item` |
| An internal link | `[Volcanoes](volcanoes)` |
| An external link | `[USGS](https://www.usgs.gov)` |
| A quotation | `> text` |
| Code | `` `code` `` or three backticks |
| A table | `| a | b |` then `| --- | --- |` |

Section headings feed the **On this page** table of contents automatically, on the right.

<div class="note">
<p><strong>Simultaneous writing.</strong> If two people open the same page, changes synchronise
live, with each person's caret. There is no "edit lock": the last keystroke wins, and the history
keeps a record of every version.</p>
</div>

## Versions and restore

Every save creates a **version**. **History** (`/wiki/<id>/history/<pageId>`) lists versions with
their author, date and diff against the previous one. An earlier version can be **restored**: it
becomes the current version without erasing the versions that follow it — history is never
rewritten.

## Linking pages

- `[A title](a-title)` creates an internal link; if the page does not exist, the link is shown as
  **broken** and the tool offers to create it.
- **Backlinks**: on every page, the list of pages pointing to it.
- **Link graph** (`/wiki/<id>/graph`): an overview of pages and their links, to spot islands and
  dead ends.
- **Structure** (`/wiki/<id>/structure`): the page tree, to reorganise without breaking addresses.
- **References** (`/wiki/<id>/references`): pages, cited sources, linked pages, broken links,
  orphan pages — the health of the mesh.

## Page templates

**Templates** (`/wiki/<id>/templates`) offers ready-made structures to fill in: fact sheet,
procedure, manual. A template is only a starting point; once the page exists, it lives its own
life.

## Suggesting an edit

On a page you cannot edit directly, **Suggest an edit** opens the same editor
(`/wiki/<id>/propose/<pageId>`). Your proposal is stored as an update to review: space managers
see the number of pending proposals and can accept or refuse them, with a note.

## Asking the wiki

If the instance has a model provider, **Ask the wiki** (`/wiki/chat`) answers a question using
the pages of the space, and cites the pages it used. Without a configured provider, the button
does not appear.

## Publishing

A space starts as a **draft** or **private**. To make it readable by everyone:

1. open the space settings and request **publication**;
2. the space moves to **pending review** — a moderator reads it;
3. once approved it becomes **public** and you receive an email, with the moderator's note where
   there is one — until then, the space is already readable by whoever has its link: publication
   only decides whether it appears in the catalogue and the search;
4. if it is refused, the space stays private and the reason is shown to the managers.

| Status | Who sees it |
| --- | --- |
| Draft | You and the members of the space |
| Private | **Anyone holding the address of the space** — it is not listed and not searchable, but a link opens it for a visitor without an account |
| Pending review | You, and the moderators reading it; the link already works |
| Public | Everyone: listed in `/wiki`, in the search results, indexed for search engines |
| Pending review | Members, and moderators |
| Public | Everyone, including signed-out visitors |
| Refused | Members; publication can be requested again after fixes |

## Exporting

From a space: **Export (.md)** for a single page, **Export (.zip)** for all sources, **Export the
wiki as PDF** for a printable version. The Markdown export is deliberately raw: it must stay
readable in a text editor and importable elsewhere.

## Searching

Search (`/wiki`) covers titles and bodies, with an **All wikis** / **My wikis** filter. In the
editor, <kbd>Ctrl</kbd> + <kbd>F</kbd> searches the current page.
