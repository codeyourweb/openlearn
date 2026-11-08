---
layout: doc
title: Getting started — create an account, sign in, find your way
description: >-
  Create an OpenLearn account, confirm your address, sign in, find your content on the dashboard,
  change language and theme.
permalink: /guide/getting-started/
---

<p class="doc-eyebrow">Guide · Account, sign-in, navigation</p>

# Getting started

## Creating an account

1. Open `/register` (the **Create an account** button at the top of the page).
2. Enter a display name, an email address and a password.
3. Submit: your account exists immediately, you are signed in, and a confirmation email is sent
   to the address you gave.

The display name appears next to your contributions. The address is never published: it is used
for signing in and for notifications.

<div class="note">
<p><strong>Password requirements.</strong> Twelve characters at minimum, and the interface
rejects the most common passwords. A password manager does the job perfectly well; nothing
obliges you to invent one you can memorise.</p>
</div>

## Confirming your address

The email you receive contains a link to `/verify/<token>`. Open it: the page confirms the address
and takes you back to your dashboard.

If the link has expired, or the email never arrived:

- a banner at the top of every page reminds you the address is not confirmed, with a
  **Resend the link** button;
- the same action exists in **Account** → *Email address*;
- a new send is only possible after a delay (five minutes by default). The button then answers
  that a link was sent recently: that is deliberate, so that a public form cannot be used to
  flood someone's inbox.

Nothing is blocked while the address is unconfirmed: you can write, create quizzes and revise.
Only email notifications depend on that confirmation.

## Signing in, signing out

- `/login` for the classic sign-in.
- If the instance offers single sign-on, one button per provider appears under the form (for
  example "Sign in with Keycloak").
- **Forgotten password**: `/forgot`. Enter your address; if an account exists, a link arrives.
  The message shown is deliberately identical in both cases, so as not to reveal which addresses
  are registered.
- Signing out: account menu, top right.

Repeated wrong passwords lock the account temporarily. The lock message only appears after a
correct password: that is a protection against account enumeration, not a reprimand.

## Finding your way

| Page | Path | What it is for |
| --- | --- | --- |
| Dashboard | `/dashboard` | Your content, drafts, cards, and the creation actions |
| Wikis | `/wiki` | Public spaces, and yours |
| Quizzes | `/quizzes` | The catalogue of public quizzes |
| Cards | `/cards` | Your revision decks |
| Account | `/account` | Profile, password, address, API keys |
| Administration | `/admin` | Reserved for administrators and moderators |

## Language, theme, accessibility

- The language selector in the footer offers twelve languages. The choice is remembered by the
  browser; Arabic switches the whole interface to right-to-left writing.
- The theme follows the system setting by default (light or dark) and can be forced.
- The whole interface can be driven from the keyboard. <kbd>Tab</kbd> moves forward,
  <kbd>Shift</kbd> + <kbd>Tab</kbd> moves back, <kbd>Enter</kbd> activates, and the first
  <kbd>Tab</kbd> offers "Skip to content" to jump past the navigation.

## What a signed-out visitor sees

Public wikis and quizzes can be read without an account, including published wiki pages. A visitor
cannot write, cannot play a quiz reserved for signed-in users, and cannot see a draft.
