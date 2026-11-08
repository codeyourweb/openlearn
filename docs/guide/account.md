---
layout: doc
title: Your account — profile, password, address, API keys
description: >-
  Managing your OpenLearn account: display name, avatar, password, email address and
  verification, API keys, invitations, deleting the account.
permalink: /guide/account/
---

<p class="doc-eyebrow">Guide · Profile, password, API keys</p>

# Your account

Everything happens on `/account`, in tabs.

## Profile

- **Display name**: what other people see, next to your contributions.
- **Avatar**: a square image, resized automatically. An explicit avatar is not required; initials
  serve as the fallback.
- **Language** and **theme**: remembered on your account, they follow you from one device to
  another.

## Email address and verification

The address is used for signing in and for notifications. It is **never** shown publicly.

The **Email address** block states whether it is **confirmed**, with a **Resend the link** button
when it is not. After an address change, confirmation is required again: an unverified address
does not receive publication notices.

A new send is limited to one every five minutes, and the button says so plainly.

## Password

**Change password** asks for the old one, then the new one twice. Other open sessions stay valid;
to cut them all off, use **Sign out other sessions** where it is offered, or change the password
from a trusted device.

If you forget it, `/forgot` sends a link. Only one email goes out every five minutes per address:
if you click ten times, one link arrives, and that is the one that works.

## API keys

An API key lets a script or an agent work with **your** rights.

1. **Create a key**: give it a name ("card import", "watch agent").
2. The value is shown **once** — copy it immediately.
3. **Revoke** a key to disable it without deleting what it created.

A key behaves like your account: do not put it in a public repository, and prefer one key per use
so you can revoke just one.

## Invitations and sharing

- **Shared assessment**: from a quiz, a link `/e/<token>` opens the assessment attempt directly,
  without going through the catalogue. Useful for a remote exam.
- **Wiki invitation**: the owner of a space invites by email, with a role — *contributor* (they
  propose changes) or *administrator* (they write directly and manage members). The link
  `/join/<token>` joins the space.

## Deleting your account

**Delete account** erases the profile and personal data. Published content (wikis, quizzes) stays
in place, attributed to an anonymised account: deleting it would break other contributors' work.
The action is permanent and asks for your password.
