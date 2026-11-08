# Accessibility

OpenLearn targets **WCAG 2.2 level AA** on everything a reader can open, and
publishes what it does not cover rather than claiming everything. The public
statement is the page at `/accessibility`; this document is the contributor's
side of it.

## Scope, and what it leaves out

| Surface | Target | How it is served |
| --- | --- | --- |
| Read paths — home, catalogues, quiz and wiki pages, legal notice, API documentation | WCAG 2.2 AA | audited on every build |
| Editing a wiki page | AA, through the Markdown editor | the Markdown mode carries the same content and needs no pointer; the rich editor is a comfort, not a requirement |
| Adventure authoring (canvas) | declared non-conforming | the adventures it produces are played from the keyboard |
| Content written by authors (images, documents) | declared as the author's responsibility | a description is asked at upload, and an empty one means "decorative" |

The rule behind the table: **do not rewrite what already works to satisfy an
audit**. A `contenteditable` editor is not made conformant by patching it; a
Markdown path that writes the same page is conformant by construction, and it
stays useful to everyone else.

## The audit

`tests/test_accessibility.py` drives Chromium against a live instance and runs
axe-core 4.10.2 (vendored in `tools/axe`) with the WCAG 2.0, 2.1 and 2.2 tags.
Four checks per read path:

* no `serious` or `critical` violation, in both themes;
* exactly one `h1`, one `main`, and every `nav` named;
* no horizontal scrolling at 390 px and 320 px (WCAG 2.2 reflow, 1.4.10);
* no console error while the page settles.

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
docker compose run --rm tests pytest -q tests/test_accessibility.py
```

CI runs the same command in the end-to-end job, so a serious violation fails the
build. Two details make it honest rather than decorative:

- **Settle before measuring.** Sections arrive with `data-reveal` at opacity 0.
  axe run on that frame reads a half-transparent colour over its own background
  and reports a contrast failure no user ever sees. `settle()` waits for the real
  state instead of the product being flattened to satisfy a probe.
- **The audit context bypasses CSP.** Instances send `script-src 'self'`, which
  is correct; the throwaway browser context opts out so the test script can be
  injected. The product's policy is not loosened for a test.

## Contrast, measured not guessed

Colour fixes follow measurement. The method pills of the API page read 3.06:1
(`GET`) and 3.85:1 (`PATCH`) against their background; they now use a darker
tint per theme. A link inside a sentence measured 1.08:1 against its own
paragraph, so prose links are underlined — colour alone was never a signal. If
you touch a colour, run the suite; the failure names the element and the ratio.

## Adding to the statement

The page reads two lists from the dictionaries: `accessibility.verified_1..4`
(what is checked) and `accessibility.limit_1..4` (what is not). Both exist in all
twelve languages, so a new claim is a key in twelve files and no code. Keep the
claims short, factual, and in the same order as this document.

## When you cannot fix it

Say so on the page, in the limits list, and open an issue. A published limit is a
usable product; a silent one is a trap.
