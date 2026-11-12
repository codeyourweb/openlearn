---
title: Self-hosting OpenLearn — Docker, backup, restore, upgrades
description: >-
  Install OpenLearn on your own server: Docker image, SQLite, environment variables, consistent
  backup, tested restore, and upgrading without losing data.
permalink: /self-hosting/
---

# Self-hosting OpenLearn

<p class="muted small">Target: a Linux server, Docker, fifteen minutes.</p>

## What you need

- A Linux server (amd64 or arm64), 1 GB of RAM, 2 GB of disk.
- Docker and the `docker compose` plugin.
- A domain name if the instance is to be public (optional on a local network).
- An SMTP server if you want verification and reset emails.

## Getting started

```bash
git clone https://github.com/codeyourweb/openlearn.git
cd openlearn
cp .env.example .env      # read it: secret, SMTP, domain
docker compose up -d --build
```

The instance listens on the port set by `OL_PORT` (8000 by default). The SQLite database and the
media files are written to the `openlearn-data` volume; that is the only state to back up.

### Important variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `OL_ENVIRONMENT` | `production` enables secure cookies and disables debug pages | `development` |
| `OL_SECRET_KEY` | Session signing | generated on first start |
| `OL_DEMO_MODE` | Loads the demonstration catalogue | `false` |
| `OL_AUTH_RATE_LIMIT` | Sign-in attempts allowed per window | `10` |
| `OL_MAIL_HOST`, `OL_MAIL_PORT`, `OL_MAIL_FROM` | Outgoing mail | empty |
| `OL_AI_BASE_URL`, `OL_AI_MODEL` | OpenAI-compatible provider for the assistant | empty |
| `OL_LOG_ENABLED`, `OL_LOG_SYSLOG_HOST`, `OL_LOG_HTTP_URL` | Audit forwarding to a SIEM ([details](/audit-logging/)) | off, empty, empty |

A variable that is not declared in `docker-compose.yml` never reaches the container: if a setting
seems to have no effect, check first that it is passed through.

## Backup

The SQLite database is written continuously; copying it with `cp` can produce an inconsistent
file. The repository ships a script that uses SQLite's `.backup` command, archives the media, and
encrypts the whole thing if asked:

```bash
OL_BACKUP_DIR=/var/backups/openlearn ./tools/backup.sh
```

A daily backup is enough for most uses; keep several, on a medium separate from the machine.

## Restore

```bash
docker compose stop app
./tools/restore.sh /var/backups/openlearn/openlearn-2026-11-08.tar.gz
docker compose start app
```

Restore replaces the volume: it is destructive by construction. Test it at least once on a
disposable instance before you need it. A backup that was never restored is not a backup, it is
an intention.

## Upgrading

```bash
git pull
docker compose up -d --build
```

Migrations are **additive**: they add columns and tables, they do not drop them. A deployment can
therefore be undone by starting the previous image again.

The `tools/deploy.sh` script goes further, for an instance that matters:

1. it takes a snapshot of the database and media before touching the service;
2. it builds the new image while the old one is still answering;
3. it switches over, measures the downtime, and checks health;
4. it compares content counters before and after, and fails if one went down;
5. it keeps the previous image for an immediate `--rollback`.

## Behind a proxy

Put OpenLearn behind nginx, Caddy or Traefik and pass `X-Forwarded-For`: rate limiting and
anti-spam bans rely on the real address, not the proxy's. If the proxy runs on the same host, add
its network to the exemption list, otherwise every visitor will share the same address.

## Email

Without SMTP configured, the instance works: address verification is simply unavailable, and the
interface says so. For a public instance, configure SPF, DKIM and DMARC on the sending domain —
otherwise your confirmation messages will land in spam, and your users will conclude that
sign-up is broken.

## What we do not provide

No "all-in-one" image with a reverse proxy, an external database and monitoring: too many
divergent choices for a single Compose file. The documentation describes the building blocks;
assembling them is your call, and that is precisely the point of self-hosting.
