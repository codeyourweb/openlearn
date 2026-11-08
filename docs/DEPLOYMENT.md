# Deployment

OpenLearn runs as one container, or one process, against a database you choose.
Nothing else is required: no queue, no cache, no object store.

## Choose a shape

| Shape | When | How |
| --- | --- | --- |
| Single container, SQLite | A class, a workshop, a demo. Up to a few hundred accounts. | `docker compose up -d` |
| Container + PostgreSQL | A school, an institution, real concurrency. | `docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d` |
| Container + MariaDB | Your infrastructure already runs MySQL. | `docker compose -f docker-compose.yml -f docker-compose.mysql.yml up -d` |
| Container + external database | Managed database, backups handled elsewhere. | Set `OL_DATABASE_URL`, keep only the app service |
| Bare metal | No Docker allowed, or a single small VM. | `./run.sh` (or `./serve.sh` with a prepared venv) |

## Quick start with Docker

```bash
git clone https://github.com/codeyourweb/openlearn.git
cd openlearn
cp .env.example .env      # set OL_ADMIN_EMAIL / OL_ADMIN_PASSWORD at least
docker compose up -d
```

The interface answers on `http://localhost:8000` (set `PORT=` to change it).
`docker compose logs -f app` shows the boot log, including the URL of the
administration account created on first start.

## Environment

Every variable is optional; the defaults target a local, private instance.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PORT` | `8000` | Published host port. |
| `APP_PORT` | `8000` | Listening port inside the container (`8443` with the TLS overlay). |
| `OL_DATABASE_URL` | `sqlite:////app/data/openlearn.db` | SQLAlchemy URL: `sqlite`, `postgresql+psycopg`, `mysql+pymysql`. |
| `OL_MEDIA_DIR` | `/app/data/media` | Uploaded images. Must be writable and persistent. |
| `OL_SECRET_KEY` | generated | Signs session tokens and SSO state. Generated once into the data volume when empty — **set it explicitly if you run more than one replica**. |
| `OL_PUBLIC_BASE_URL` | derived | Absolute URLs in e-mails and share links. Set it behind a proxy: `https://learn.example.org`. |
| `OL_COOKIE_SECURE` | `false` | Force the `Secure` cookie flag. Detected automatically over HTTPS, forced here for exotic proxies. |
| `OL_INSTANCE_NAME` | `OpenLearn` | Header and e-mail signature. |
| `OL_ENVIRONMENT` | `production` | `development` relaxes a few checks. |
| `OL_DEMO_MODE` | `false` | Load the demo catalogue and show the presentation page as the entry screen. |
| `OL_DEMO_CONTENT_DIR` | `demo` | Where the catalogue JSON files live. |
| `OL_ADMIN_EMAIL` / `OL_ADMIN_PASSWORD` | — | Account created, or promoted to administrator, at boot. |
| `OL_AI_ENABLED` | `false` | Bootstrap value; the administration panel overrides it afterwards. |
| `OL_MAIL_*` | — | SMTP bootstrap (`HOST`, `PORT`, `USERNAME`, `PASSWORD`, `FROM_ADDRESS`, `FROM_NAME`). |
| `OL_SSO_ENABLED` | `true` | Allow providers configured in the administration panel. |
| `OL_MCP_ENABLED` / `OL_MCP_REQUIRE_AUTH` | `true` / `true` | Agent endpoint, see [MCP.md](MCP.md). |
| `OL_TLS_CERT_FILE` / `OL_TLS_KEY_FILE` | — | Serve HTTPS directly (bare metal or TLS overlay). |

The full list lives in `backend/app/config.py`; every `OL_*` name is the
upper-case form of the setting.


### Installing the demo catalogue

The catalogue under `demo/content/` is installed automatically when
`OL_DEMO_MODE=true`. To (re)install it into an instance that is already running,
including one where demo mode is off:

```sh
./tools/demo-seed.sh            # container "openlearn"
./tools/demo-seed.sh ol-demo    # any other container name
```

The script validates every file first, then forces the install, so editing a
JSON file and re-running is enough. The full catalogue is 30 wikis, 100
questionnaires, 17 revision decks and 4 story adventures, mostly in English with
French, German and Spanish entries.

## TLS

### With a reverse proxy (recommended)

Terminate TLS at nginx, Caddy or Traefik, and proxy to the container port:

```nginx
server {
    listen 443 ssl http2;
    server_name learn.example.org;

    ssl_certificate     /etc/letsencrypt/live/learn.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/learn.example.org/privkey.pem;

    client_max_body_size 12m;          # question images

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        "upgrade";   # live sessions use WebSocket
    }
}
```

`X-Forwarded-Proto` is what tells the application to flag cookies `Secure` and
to build `https://` share links.

### Without a reverse proxy

The application can hold the certificate itself:

```bash
mkdir -p certs
# Let's Encrypt writes privkey.pem as 0600 root, while the image runs as an
# unprivileged user: the key has to be readable, or serve.sh stops with
# "cannot read". `install -m` copies and fixes the mode in one step.
install -m 644 /etc/letsencrypt/live/learn.example.org/fullchain.pem certs/
install -m 644 /etc/letsencrypt/live/learn.example.org/privkey.pem certs/
# in .env: PORT=8443, APP_PORT=8443
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d
```

On bare metal, the same thing without Docker:

```bash
OL_TLS_CERT_FILE=/etc/ssl/learn/fullchain.pem \
OL_TLS_KEY_FILE=/etc/ssl/learn/privkey.pem \
OL_TLS_PORT=8443 ./serve.sh
```

Renewing a certificate is a copy followed by a restart
(`docker compose ... restart app`): the key is read once at boot.

## Backups

Two things hold state: the database and the media directory.

SQLite:

```bash
docker compose exec app python - <<'PY'
import sqlite3
src = sqlite3.connect("/app/data/openlearn.db")
dst = sqlite3.connect("/app/data/backup.db")
src.backup(dst)
PY
docker compose cp app:/app/data/backup.db ./openlearn-$(date +%F).db
```

PostgreSQL / MariaDB: use `pg_dump` / `mariadb-dump` against the `db` service.

Media: `docker run --rm -v openlearn_openlearn-data:/data -v "$PWD":/out alpine tar czf /out/media.tgz -C /data media`.

Restore is the reverse operation, with the container stopped.

## Upgrades

```bash
git pull
docker compose build app
docker compose up -d app
```

Migrations run at boot, in a single transaction, before the first request is
served. A failed migration leaves the previous schema in place and the
container exits non-zero: check `docker compose logs app` before retrying.

## Health and observability

- `GET /api/v1/health` — liveness, no authentication, no database access.
- `GET /api/v1/meta` — instance name, version, enabled features; this is what
  the interface reads at boot.
- The container healthcheck calls the same endpoint, over HTTP or HTTPS
  depending on how the server was started.

Logs go to stdout as structured lines. `OL_LOG_LEVEL=DEBUG` adds SQL and
request traces.

## Scaling

The application is stateless apart from the database and the media directory,
so several replicas can sit behind a load balancer — provided that:

1. `OL_SECRET_KEY` is the same on every replica (otherwise sessions and SSO
   state break between them);
2. the database is PostgreSQL or MariaDB (SQLite does not tolerate two writers
   across containers);
3. `OL_MEDIA_DIR` is a shared volume.

Background AI jobs run inside the web process; with several replicas, each job
is claimed by whichever worker polls it first, which is safe because the claim
is a conditional `UPDATE`.
