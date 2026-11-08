---
title: Accessibility — WCAG 2.2 AA, commitment and method
description: >-
  How OpenLearn meets WCAG 2.2 AA: keyboard navigation, contrast, live announcements, reduced
  motion, and automated checks in continuous integration.
permalink: /accessibility/
---

# Accessibility

<p class="muted small">Target met: WCAG 2.2 level AA on the main journeys.</p>

## Why it is a floor, not an argument

A learning platform is by definition aimed at people who are learning — a significant share of
whom face difficulties with reading, vision, attention or motor control. Shipping an interface
that excludes part of them is not only a legal defect: it is a pedagogical contradiction.

Accessibility was therefore treated as a design constraint, from the first line of interface, and
not as a catch-up campaign.

## What is actually in place

- **Semantic structure**: one `h1` per screen, a continuous heading hierarchy, `header`/`main`/
  `nav`/`footer` regions, lists for lists.
- **Keyboard**: every journey can be completed without a mouse (sign-in, quiz creation, live
  game, page editing, revision). Natural tab order, no keyboard trap.
- **Visible focus**: a 3 px focus ring, never removed, with sufficient contrast in both themes.
- **Contrast**: the palette aims at AAA for body text and at least 3:1 on components; the
  automated check fails below AA.
- **Forms**: every field has an associated `label`, errors are tied to the field with
  `aria-describedby`, and the error message is announced.
- **Dynamic states**: score changes, confirmations and errors go through `role="status"` or
  `aria-live` regions, never through a colour change alone.
- **Motion**: `prefers-reduced-motion` removes transitions and game animations.
- **Language**: correct `lang` per screen, including the `dir="rtl"` switch for Arabic.
- **Zoom and reflow**: usable at 200 % without losing content or needing horizontal scrolling.
- **Touch targets**: at least 24 × 24 px everywhere (criterion 2.5.8), more on primary actions.

## How it is checked

Three levels, all run on every pull request:

1. **Static checks** in the test suite: presence of labels, text alternatives, skip links, no
   inline `onclick` attributes, a single `h1`.
2. **Automated axe-core audit** in a browser on the main screens (landing page, sign-in,
   dashboard, wiki, quiz, administration), failing the build on serious violations.
3. **Manual review** before each release: full keyboard journey, screen reader (NVDA and
   VoiceOver), 200 % zoom, dark theme.

An automated audit does not replace a human test: it catches mechanical omissions, not
ambiguities. Both are needed.

## Reporting an accessibility problem

Open an issue labelled `accessibility`, stating: the screen concerned, the browser, the assistive
technology you use, and what you expected. An accessibility regression is treated as a blocking
defect, not as an enhancement.

If you cannot go through GitHub, write to `developper@openlearnproject.org`: the message will be
copied into the public tracker unless you ask otherwise.
