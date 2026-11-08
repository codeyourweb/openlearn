# Administration

The administration area (`/admin`) mixes moderation and configuration. This page
covers the configuration tabs: **Settings**, **Single sign-on**, **AI error log**.

Only accounts with the administrator role see them. The first administrator is
created at boot from `OL_ADMIN_EMAIL` / `OL_ADMIN_PASSWORD`; afterwards another
administrator can promote an account from the **Users** tab.

## Roles

| Role | May | May not |
| --- | --- | --- |
| Member | Write wikis and quizzes, ask for publication | Publish without moderation |
| Trusted | Publish immediately, review others' content | Moderate accounts |
| Moderator | Everything a member may, plus: validate and reject wikis and quizzes, delete a quiz, read the security log and the AI reviews, grant or revoke *trusted* on a member | Reach **Settings**, **Single sign-on** or the **AI error log**; promote anyone to moderator or administrator; suspend or delete an account; touch another staff account |
| Administrator | Everything, including the instance configuration (AI, mail, SSO) and account deletion | — |

Moderation is `require_staff` on the server: an administrator or a moderator.
Configuration is `require_admin`: an administrator only. The interface hides the
configuration tabs from a moderator, but the API refuses them anyway, which is
the check that counts.

The three flags are independent columns on the user (`is_admin`,
`is_moderator`, `is_trusted`). Promoting to moderator does not grant
administrator rights, and demoting does not silently remove *trusted*.

## How settings are stored

Runtime settings live in the database (`app_settings`). The environment is the
bootstrap value: on the first start, `OL_*` variables seed the table; after
that, the panel has the last word. Precedence is therefore:

```
administration panel  >  environment variable  >  built-in default
```

A row marked *changed* was edited in the panel and no longer follows the
environment. Clearing the field restores the environment value.

Secrets — API key, SMTP password, OIDC client secret — are **write-only**: the
API tells the interface whether a value is stored, never what it is. Leaving the
field empty keeps the stored value; ticking *Remove the stored value* erases it.

## Settings

### Model provider

Anything that speaks the OpenAI chat-completions API: a local Ollama or vLLM, a
gateway (LiteLLM), OpenAI, Mistral, Groq…

| Setting | Meaning |
| --- | --- |
| Enable the AI features | Master switch. When off, every AI control disappears from the interface (`html[data-ai="off"]` hides them) and the API answers 503. |
| API base URL | Ends with `/v1`, e.g. `http://ollama:11434/v1`. |
| API key | Left empty for a local endpoint that does not check one. |
| Model | Used for quiz and adventure generation. |
| Model for the wiki | Style and grammar passes; may be smaller and cheaper. |
| Timeout | Per request. |
| Delay between two calls | Per user, in seconds. `0` disables the throttle. The default of 15 prevents an impatient click from spending a quota. |

**Test the connection** sends one short completion and reports the model name
and latency. Failures are written to the AI error log with the HTTP status and
the provider's message.

### E-mail

SMTP settings used for password resets and account notices.

- Port 587 + STARTTLS is the usual choice; port 465 uses implicit TLS (tick
  *Implicit TLS* and clear *STARTTLS*).
- With Gmail, an **application password** is required: the account password is
  refused for SMTP since 2022.
- **Send a test message** asks for an address and reports the SMTP error
  verbatim — that is where a wrong port or a blocked egress shows up.

When mail is not configured, the *Forgotten password?* link still exists but the
API answers 503 with a neutral message, and the interface says so. Accounts
created by an administrator then need a manual password change.

### Registration and security

| Setting | Meaning |
| --- | --- |
| Allow self-registration | Off closes `POST /api/v1/auth/register`; an administrator creates accounts. |
| Reset link lifetime | Minutes a reset token stays valid. Default 60. |

### Instance

The display name, used in the header, the browser title and the e-mail
signature.

## Single sign-on

Providers are declared in **Single sign-on**. A provider is a record, not a code
change: adding Okta on Tuesday does not require a redeploy.

| Field | OIDC | SAML 2.0 |
| --- | --- | --- |
| Identifier in the URL | yes — `/api/v1/auth/sso/<slug>/callback` | yes — `.../<slug>/acs` |
| Issuer URL | `https://login.microsoftonline.com/<tenant>/v2.0` | — |
| Client ID / secret | yes | — |
| SP entity ID | — | the audience you declare at the IdP |
| IdP sign-in URL | — | the SSO endpoint of the IdP |
| Signing certificate | — | the IdP X.500 certificate, PEM, without the header lines if your IdP shows it that way |
| Allowed domains | optional: only accept `@your-domain` addresses | same |

The callback URL to declare at the provider is displayed in the form, built from
`OL_PUBLIC_BASE_URL` (or from the request when it is empty).

**What SSO does and does not do.** The provider authenticates a person and hands
over an e-mail address; the local account, its display name and its roles stay
the property of the instance. An unknown address creates an account only when
*Create unknown accounts* is ticked; otherwise the sign-in is refused with a
clear message, and an administrator can create the account first.

**Test** fetches the OIDC discovery document, or verifies that the SAML fields
are complete, without going through a browser.

## AI error log

Every failed model call is recorded — throttled calls excluded — with its
timestamp, operation (`quiz`, `wiki-style`, `admin-test`…), model, HTTP status
and the provider's response. Users only ever see:

> The AI features are temporarily unavailable. Please try again later.

The log is capped by a periodic prune. **Clear the log** empties it; the tab
also shows the total, which is the number to watch when a quota runs out.

## Demo mode

A demo instance is the same code with `OL_DEMO_MODE=true`:

- the demo catalogue under `demo/content/*.json` is loaded once at boot (wikis,
  quizzes, revision decks, adventures, in several languages);
- the entry screen becomes the presentation page, and the *About* link appears
  in the header; on a private instance the entry screen is the wiki listing;
- the demo accounts share `OL_DEMO_PASSWORD`.

Content is data: a private instance never loads it, and updating a file bumps a
fingerprint stored in `app_settings`, so the new version is imported on the next
boot without a manual reset.

```bash
# inside the container, or on a bare-metal install
OL_DEMO_MODE=true python -m app.demo.seed
```

Removing demo content is a database restore or a fresh volume: the loader never
deletes what a real person wrote.
