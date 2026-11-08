# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Import a wiki from an archive, or a page from a markdown file.

Two entry points, one parser:

* ``POST /wiki/import`` takes a ``.zip`` exported from Obsidian, Joplin or any
  folder of markdown files, and creates a whole wiki.
* ``POST /wiki/{id}/pages/import`` takes a single ``.md`` file and adds it as a
  page.

Archives are untrusted input: the size and the number of entries are capped, the
total inflated size is capped while extracting (a zip bomb is a stream of zeros
that never fills the disk at once), paths are normalised against traversal, and
everything that is not markdown or an allowlisted image is ignored.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass, field

from fastapi import HTTPException

from .media import MAX_WIKI_DIMENSION, store_image

MAX_ARCHIVE_BYTES = 40 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 120 * 1024 * 1024
MAX_ENTRIES = 600
MAX_PAGES = 200
MAX_PAGE_BYTES = 1024 * 1024
MAX_FILE_BYTES = 5 * 1024 * 1024

MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".txt"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
# Folders nobody wants imported: editor state, caches, version control, trash.
SKIP_DIRS = {
    ".obsidian",
    ".trash",
    ".git",
    ".github",
    "__macosx",
    ".joplin",
    ".stfolder",
    "node_modules",
    "_resources",
    ".smart-env",
}

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_YAML_LINE = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$")
_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_OBSIDIAN_EMBED = re.compile(r"!\[\[([^\]\|]+?)(?:\|[^\]]*)?\]\]")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}[-_ ]+")


@dataclass
class ImportedPage:
    title: str
    content_md: str
    tags: list[str] = field(default_factory=list)
    source: str = ""


@dataclass
class ImportedWiki:
    title: str
    pages: list[ImportedPage]
    source: str
    images: int = 0
    skipped: int = 0


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return YAML front matter as a flat dict, and the body.

    Only the handful of keys these tools actually write are read: a full YAML
    parser would be another dependency and another attack surface for metadata we
    simply display.
    """
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        found = _YAML_LINE.match(line.strip())
        if found:
            meta[found.group(1).lower()] = found.group(2).strip().strip("\"'")
    return meta, text[match.end():]


def _title_of(meta: dict[str, str], body: str, filename: str) -> str:
    if meta.get("title"):
        return meta["title"][:200]
    heading = _H1.search(body)
    if heading:
        return heading.group(1).strip()[:200]
    stem = posixpath.splitext(posixpath.basename(filename))[0]
    stem = _DATE_PREFIX.sub("", stem).replace("_", " ").replace("-", " ").strip()
    return (stem or "Untitled")[:200]


def _tags_of(meta: dict[str, str]) -> list[str]:
    raw = meta.get("tags") or meta.get("tag") or ""
    raw = raw.strip("[]")
    items = [item.strip().strip("\"'") for item in re.split(r"[,\s]+", raw) if item.strip()]
    return [item for item in items if len(item) <= 40][:12]


def parse_markdown_file(raw: bytes, filename: str) -> ImportedPage:
    """One ``.md`` file to a page. Front matter is dropped, the title is inferred."""
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="This markdown file is larger than 5 MB.")
    text = _decode(raw).replace("\r\n", "\n").replace("\r", "\n")
    meta, body = _split_frontmatter(text)
    body = body.lstrip("\n")
    title = _title_of(meta, body, filename)
    # The page title is displayed above the article: a leading h1 saying the same
    # thing would be printed twice.
    body = re.sub(r"\A#\s+" + re.escape(title) + r"\s*\n+", "", body, count=1)
    return ImportedPage(title=title, content_md=body.strip() + "\n", tags=_tags_of(meta), source=filename)


def _safe_name(name: str) -> str | None:
    """Normalise an archive member name, rejecting anything that escapes the root."""
    name = name.replace("\\", "/").lstrip("/")
    normalised = posixpath.normpath(name)
    if normalised.startswith("..") or "/../" in normalised:
        return None
    return normalised


def _is_skipped(path: str) -> bool:
    parts = [part.lower() for part in path.split("/")]
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return True
    base = parts[-1]
    return base.startswith(".") or base.endswith(".tmp")


def _detect_source(names: list[str], bodies: list[str]) -> str:
    if any("/.obsidian/" in f"/{name.lower()}/" or name.lower().startswith(".obsidian/") for name in names):
        return "obsidian"
    if any("parent_id:" in body for body in bodies) or any("joplin" in name.lower() for name in names):
        return "joplin"
    if any("[[" in body for body in bodies):
        return "obsidian"
    return "markdown"


def read_archive(raw: bytes, *, archive_name: str = "") -> ImportedWiki:
    """Parse a zip of markdown files into a wiki, images rewritten to ``/media``."""
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="This archive is larger than 40 MB.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=415, detail="This file is not a valid zip archive.") from exc

    members = [info for info in archive.infolist() if not info.is_dir()]
    if not members:
        raise HTTPException(status_code=422, detail="This archive is empty.")
    if len(members) > MAX_ENTRIES:
        raise HTTPException(
            status_code=422, detail=f"This archive holds more than {MAX_ENTRIES} files."
        )

    total = 0
    documents: list[tuple[str, bytes]] = []
    pictures: dict[str, bytes] = {}
    skipped = 0
    for info in members:
        path = _safe_name(info.filename)
        if path is None or _is_skipped(path):
            skipped += 1
            continue
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise HTTPException(
                status_code=413, detail="This archive is too large once decompressed."
            )
        suffix = posixpath.splitext(path)[1].lower()
        if suffix in MARKDOWN_SUFFIXES:
            if info.file_size > MAX_PAGE_BYTES:
                skipped += 1
                continue
            documents.append((path, archive.read(info)))
        elif suffix in IMAGE_SUFFIXES:
            if info.file_size > MAX_FILE_BYTES:
                skipped += 1
                continue
            pictures[path] = archive.read(info)
        else:
            skipped += 1

    if not documents:
        raise HTTPException(
            status_code=422, detail="No markdown file found: is this really a wiki export?"
        )
    if len(documents) > MAX_PAGES:
        skipped += len(documents) - MAX_PAGES
        documents = documents[:MAX_PAGES]

    bodies = [_decode(data) for _, data in documents]
    source = _detect_source([path for path, _ in documents], bodies)

    # Store the images once, keep a lookup by full path and by bare file name:
    # Obsidian writes `![[image.png]]` (bare name) while Joplin writes
    # `![](:/4f2c…jpg)` or `resources/4f2c….jpg` (a path).
    stored: dict[str, str] = {}
    by_basename: dict[str, str] = {}
    for path, data in pictures.items():
        try:
            result = store_image(data, max_dimension=MAX_WIKI_DIMENSION)
        except HTTPException:
            skipped += 1
            continue
        stored[path.lower()] = str(result["path"])
        by_basename.setdefault(posixpath.basename(path).lower(), str(result["path"]))
        by_basename.setdefault(posixpath.splitext(posixpath.basename(path))[0].lower(), str(result["path"]))

    def resolve_image(reference: str) -> str | None:
        cleaned = reference.strip().strip("<>").split("|")[0].strip()
        cleaned = cleaned.lstrip("./").replace("\\", "/")
        if cleaned.startswith(":/"):
            cleaned = cleaned[2:]
        candidates = [
            cleaned.lower(),
            posixpath.basename(cleaned).lower(),
            posixpath.splitext(posixpath.basename(cleaned))[0].lower(),
        ]
        for candidate in candidates:
            if candidate in stored:
                return stored[candidate]
            if candidate in by_basename:
                return by_basename[candidate]
        return None

    # The root folder is usually the container itself ("vault", "export"): it is
    # not information, unlike a Joplin notebook ("Sécurité"). Drop it only when it
    # matches the archive name.
    folders = [posixpath.dirname(path) for path, _ in documents if posixpath.dirname(path)]
    root = posixpath.commonpath(folders) if len(folders) > 1 else ""
    if root in {".", "/"}:
        root = ""
    stem = posixpath.splitext(posixpath.basename(archive_name))[0].strip().lower()
    container = root if root and stem and posixpath.basename(root).lower() == stem else ""

    pages: list[ImportedPage] = []
    for (path, _), body in zip(documents, bodies, strict=True):
        meta, text = _split_frontmatter(body.replace("\r\n", "\n"))
        text = text.lstrip("\n")
        title = _title_of(meta, text, path)
        text = re.sub(r"\A#\s+" + re.escape(title) + r"\s*\n+", "", text, count=1)

        if source == "obsidian":
            # Attachments are not inside the vault folder but next to it.
            folder = posixpath.dirname(path)
            tags = _tags_of(meta)
            for match in _OBSIDIAN_EMBED.finditer(text):
                target = resolve_image(match.group(1))
                if target:
                    text = text.replace(match.group(0), f"![]({target})")
        else:
            tags = _tags_of(meta)
            folder = posixpath.dirname(path)

        def replace_image(match: re.Match[str]) -> str:
            alt, reference = match.group(1), match.group(2)
            if reference.startswith("http://") or reference.startswith("https://"):
                return match.group(0)
            target = resolve_image(reference)
            return f"![{alt}]({target})" if target else match.group(0)

        text = _MD_IMAGE.sub(replace_image, text)

        # The deepest folder of an export is its notebook or folder name: keep it
        # as a tag so the imported wiki still shows how it was organised.
        if folder and folder != container:
            leaf = posixpath.basename(folder)
            if leaf and leaf.lower() not in {"resources", "attachments", "assets", "files", "images"}:
                tags.append(leaf[:40])

        pages.append(
            ImportedPage(
                title=title,
                content_md=text.strip() + "\n",
                tags=sorted({tag for tag in tags if tag})[:12],
                source=path,
            )
        )

    archive_title = _archive_title(documents)
    return ImportedWiki(
        title=archive_title,
        pages=pages,
        source=source,
        images=len(stored),
        skipped=skipped,
    )


def _archive_title(documents: list[tuple[str, bytes]]) -> str:
    """Name the wiki after the archive's folder, or the first page."""
    folders = [posixpath.dirname(path) for path, _ in documents if posixpath.dirname(path)]
    if folders:
        common = posixpath.commonpath(folders) if len(folders) > 1 else folders[0]
        leaf = posixpath.basename(common)
        if leaf:
            return leaf.replace("_", " ").replace("-", " ").strip()[:200]
    first = _decode(documents[0][1])
    meta, body = _split_frontmatter(first)
    return _title_of(meta, body, documents[0][0])[:200]
