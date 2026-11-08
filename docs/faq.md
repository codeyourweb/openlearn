---
title: OpenLearn frequently asked questions
description: >-
  Licence, hosting, cost, email, personal data, accessibility, differences with Moodle or Kahoot,
  translation, and how the project is governed.
permalink: /faq/
---

# Frequently asked questions

<h2>Is it really free?</h2>
<p>Yes, with no hidden trade-off: the software is under AGPL-3.0-only, there is no "pro" edition,
no account limit, no reserved feature. Hosting costs what a server costs — a few euros a month for
a small instance.</p>

<h2>How is it different from Moodle?</h2>
<p>Moodle is a full learning platform: courses, assignments, grades, enrolment, calendar.
OpenLearn does not do that. It does three things: write a wiki, have quizzes recite, and schedule
revision. If you are looking for a full LMS, this is the wrong tool; if you are looking for "a
wiki and quizzes that work, that I can host myself", it is one.</p>

<h2>And compared with Kahoot or Quizlet?</h2>
<p>The live mode resembles Kahoot, and the cards resemble Quizlet. The difference comes down to
three points: your content stays with you, there is no advertising tracker, and the software is
modifiable. The trade-off: no library of millions of community quizzes.</p>

<h2>Do I need a powerful server?</h2>
<p>No. A 1 GB server is enough for about a hundred occasional users; SQLite carries the load.
Beyond that, PostgreSQL is supported. The installation guide details the variables and the
backup.</p>

<h2>Is my data being exploited?</h2>
<p>There is no advertising network, no third-party analytics script, no sale of data. The software
writes access logs to diagnose a failure and block a spammer, not to build a profile. On your own
instance you are in sole control of the data; on the public demo, do not put anything confidential
there.</p>

<h2>Why does the email address have to be confirmed?</h2>
<p>So that publication notices actually reach you. Confirmation is not blocking: you can work
without it, a banner simply reminds you. It also prevents a mistyped address from being used to
create accounts in bulk.</p>

<h2>I am not receiving any email</h2>
<p>Three ordinary causes: the message is in spam (SPF/DKIM/DMARC missing on the sending domain),
the instance has no SMTP configured, or the request was made twice within five minutes and
therefore produced a single message. See the
<a href="{{ '/guide/troubleshooting/' | relative_url }}">Troubleshooting</a> page.</p>

<h2>How many languages are available?</h2>
<p>Twelve: French, English, German, Spanish, Italian, Russian, Chinese, Japanese, Portuguese,
Hindi, Bengali and Arabic. The whole interface is translated, not only the landing page, and
Arabic switches to right-to-left writing.</p>

<h2>May I use the name "OpenLearn" for my instance?</h2>
<p>For a private instance, yes. For a public one, present it as "an OpenLearn instance" rather
than as the official instance: the name and the demo are not granted by the licence. See
<a href="{{ '/contributing/' | relative_url }}">Contributing</a>.</p>

<h2>How is the project funded?</h2>
<p>It is not. Development is carried by its author; there is no foundation, no investor, no
roadmap conditioned by a client. That is an accepted fragility, and one more reason for the code
to stay readable and takeable over by others.</p>

<h2>What happens if the project stops?</h2>
<p>The sources remain available, the database is a single SQLite file, and content exports to
Markdown and JSON. An instance keeps running without updates. That is exactly why AGPL and
self-hosting were chosen: the disappearance of a maintainer must not mean the disappearance of
the data.</p>
