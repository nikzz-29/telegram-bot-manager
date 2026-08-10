# Deploying

Four processes, two datastores, and a static bundle. The bot talks to Telegram,
the API serves the Mini App, the worker runs everything time-shifted, and
`migrate` runs once before the other three start.

- [Prerequisites](#prerequisites)
- [First deploy](#first-deploy)
- [Configuration](#configuration)
- [Polling or webhook](#polling-or-webhook)
- [Migrations](#migrations)
- [The Mini App](#the-mini-app)
- [Payments](#payments)
- [Scaling](#scaling)
- [Operating](#operating)

## Prerequisites

- Docker with Compose v2 (`docker compose version` ≥ 2.20).
- A bot token from [@BotFather](https://t.me/BotFather).
- For webhook mode: a domain with a TLS certificate and a reverse proxy.
- For the panel: a [Vercel](https://vercel.com) project, or any static host.

Nothing else is installed on the host. Postgres and Redis come from the compose
file, and the three services share one image built from the repository root.

## First deploy

```bash
git clone <your-fork> && cd gateway
cp .env.example .env
$EDITOR .env                      # BOT_TOKEN, JWT_SECRET, CORS_ORIGINS, APP_ENV
docker compose -f infra/docker/docker-compose.yml up -d --build
```

Generate the JWT secret rather than inventing one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

With `APP_ENV=production` the process refuses to start on an unsafe
configuration instead of running with it — a placeholder `JWT_SECRET`, an empty
`BOT_TOKEN`, `CORS_ORIGINS=*`, or a webhook without a secret. The error names
every problem at once, so you fix them in one pass.

Check it came up:

```bash
docker compose -f infra/docker/docker-compose.yml ps
curl -fsS localhost:8000/api/health   # {"status":"ok",...}
curl -fsS localhost:8000/api/ready    # 503 while Redis is unreachable
docker compose -f infra/docker/docker-compose.yml logs -f bot
```

`/health` is the liveness probe and consults nothing: an API that fails it
because Redis is down would be restarted by the orchestrator, which does not
bring Redis back. `/ready` is the one that answers 503 when a dependency the API
cannot serve without is missing — point the load balancer at that one.

## Configuration

Every setting is an environment variable read once at startup by
`packages/shared/src/shared/config.py`; `.env.example` documents all 23 with the
defaults. The ones that matter in production:

| Variable | Why it matters |
| --- | --- |
| `APP_ENV` | `production` turns on the startup safety checks below. |
| `BOT_TOKEN` | From @BotFather. All four processes need it — the worker sends messages of its own. |
| `JWT_SECRET` | Signs panel sessions. ≥32 bytes, and never the shipped placeholder. |
| `CORS_ORIGINS` | The panel's exact origin. `*` is refused in production. |
| `WEBAPP_URL` | Where the Mini App is served. Must match what BotFather has, or `initData` verification fails. |
| `SUPERADMIN_IDS` | Comma-separated Telegram user ids that may open the platform console. Empty means nobody. |
| `AI_API_KEY` | Optional. Without it AI moderation degrades to disabled rather than failing messages. |
| `CRYPTOBOT_TOKEN` | Optional. Stars work without it; crypto payments do not. |

Compose passes `.env` to every service through `env_file` and then overrides
`DATABASE_URL` and `REDIS_URL` to the in-network names. The values in `.env`
stay pointed at `localhost:5433` / `localhost:6380` so `task api` keeps working
on the host — the same file serves both.

`.env` is in `.gitignore` and `.dockerignore`. It holds a live token, and a copy
baked into an image outlives any `docker rm`.

## Polling or webhook

Long polling is the default and needs no inbound connectivity at all. It is the
right choice until the bot is large enough that the extra round trip matters.

To switch:

```bash
USE_WEBHOOK=true
WEBHOOK_BASE_URL=https://bot.example.com   # https, and reachable from Telegram
WEBHOOK_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

The bot then serves its own endpoint on `WEBHOOK_PORT` (8081 by default), which
compose publishes to `127.0.0.1` only. Terminate TLS in front of it:

```nginx
location /telegram/webhook {
    proxy_pass http://127.0.0.1:8081;
    proxy_set_header X-Telegram-Bot-Api-Secret-Token $http_x_telegram_bot_api_secret_token;
}
```

Telegram sends `WEBHOOK_SECRET` back in that header and the bot compares it, so
the proxy has to forward it. Without the secret anyone who learns the URL can
post fabricated updates, which is why production refuses to start when
`USE_WEBHOOK` is on and it is unset.

Switching back to polling needs no cleanup: the bot deletes a leftover webhook
on startup, because `getUpdates` answers 409 while one is registered and the
process would otherwise start cleanly and receive nothing.

The webhook is deliberately *not* deleted on shutdown. Telegram queues updates
while an endpoint is unreachable and redelivers them, so a restart loses
nothing; deleting it would open a window on every deploy.

## Migrations

The `migrate` service runs `alembic upgrade head` and exits. The other three
wait on `service_completed_successfully`, so the schema is never a race between
three processes starting at once. Every `up` applies pending migrations before
anything serves traffic.

By hand:

```bash
docker compose -f infra/docker/docker-compose.yml run --rm migrate
task migrate                                              # on the host
task revision -- "add whatever"                           # autogenerate
```

Read generated migrations before committing them. Autogenerate detects added
tables and columns reliably; renames it sees as a drop plus an add, which on a
live table means silent data loss.

Back up before a deploy that migrates:

```bash
docker compose -f infra/docker/docker-compose.yml exec postgres \
    pg_dump -U postgres tg_manager | gzip > backup-$(date +%F).sql.gz
```

## The Mini App

The panel is a static bundle and does not belong in the Python images —
`.dockerignore` excludes it. Deploy it to Vercel:

| Setting | Value |
| --- | --- |
| Root directory | `apps/miniapp` |
| Install command | `pnpm install` |
| Build command | `pnpm run build` |
| Output directory | `dist` |
| `VITE_API_BASE_URL` | `https://api.example.com` |

Uncheck "Include source files outside of the Root Directory" only if you are
sure — the build imports `.ftl` files from `packages/i18n` through the
`@locales` alias so the panel and the bot read one set of locales. Vercel needs
the repository root available for that import to resolve.

Then three things have to agree, or `initData` verification fails with a 401
that looks like a bug:

1. `WEBAPP_URL` in `.env` — the origin the API checks against.
2. The Web App URL in BotFather (`/mybots` → Bot Settings → Menu Button).
3. Where Vercel actually serves it.

`CORS_ORIGINS` must also name that origin exactly. Production refuses `*`.

After changing an API schema, regenerate the typed client so the panel's types
match what the API returns:

```bash
task client       # exports openapi.json, then regenerates src/api/schema.ts
```

## Payments

**Telegram Stars** needs no configuration. Invoices are created by the bot and
settled by Telegram; the `pre_checkout_query` handler is already wired.

**CryptoBot** needs `CRYPTOBOT_TOKEN` from [@CryptoBot](https://t.me/CryptoBot)
and a webhook pointing at the API:

```
https://api.example.com/payments/cryptobot/webhook
```

That route is excluded from the OpenAPI schema on purpose — it is not part of
the panel's contract. It answers 200 for anything it has already handled or
cannot parse, because a non-2xx makes CryptoBot retry forever on a payload that
will never succeed.

## Scaling

**The worker scales horizontally.** It is where every deferred action runs, and
it is the first thing to add replicas of:

```bash
docker compose -f infra/docker/docker-compose.yml up -d --scale worker=3
```

Cron jobs stay correct across replicas: ARQ enqueues them with a deterministic
job id derived from the scheduled time (`unique=True`), so three workers racing
the same tick produce one job.

**The API scales horizontally** behind any load balancer. It holds no state
between requests; sessions are JWTs and everything cached lives in Redis.

**The bot does not scale by adding replicas while polling.** Two pollers on one
token both receive every update. Under a webhook it does scale — updates are
deduplicated through Redis, precisely because Telegram redelivers when a reply
is slow and a rolling deploy briefly runs two replicas.

Vertical knobs, all in `.env`:

| Variable | Default | What it controls |
| --- | --- | --- |
| `SENDER_WORKERS` | 4 | Concurrent outbound sends per process. |
| `GLOBAL_SEND_RATE` | 30 | Messages/second across all chats — Telegram's documented ceiling. |
| `GROUP_SEND_RATE_PER_MINUTE` | 20 | Per-group ceiling. Raising it invites 429s. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 10 / 20 | Connections per process. Multiply by replica count and compare against Postgres's `max_connections`. |

The send rates are Telegram's limits, not ours. Raising them does not send more
messages; it converts refusals into `retry_after` backoff.

## Operating

**Logs** are JSON on stdout (`LOG_JSON=true`), which is what a log shipper
wants. Set it false for human-readable local output.

```bash
docker compose -f infra/docker/docker-compose.yml logs -f bot worker
```

**Deploying a change:**

```bash
git pull
docker compose -f infra/docker/docker-compose.yml up -d --build
```

Compose stops the old containers with SIGTERM, which all three handle rather
than dying on. The bot returns from its runner and drains the outbound queue, so
a ban already decided still reaches Telegram. The worker cancels jobs still
running and re-queues them — ARQ retries on cancellation — then drains its own
sender in `on_shutdown`. Give them time to finish: `--timeout 30` if the default
10 seconds proves tight under load.

**Rolling back** is `git checkout <tag>` and the same command, with one caveat:
migrations do not roll back with the code. If the bad deploy migrated, either
`alembic downgrade -1` first (having read what it drops) or roll forward.

**A shell for one-off work:**

```bash
docker compose -f infra/docker/docker-compose.yml exec api python
docker compose -f infra/docker/docker-compose.yml exec postgres psql -U postgres tg_manager
```

**When something is wrong**, in the order that usually finds it:

| Symptom | Where to look |
| --- | --- |
| Bot silent, no errors | A webhook is registered while polling. `getWebhookInfo` against the API, or just restart — the bot clears it. |
| Panel shows 401 | `WEBAPP_URL`, BotFather's Web App URL and the deployed origin disagree. |
| Panel shows a CORS error | `CORS_ORIGINS` does not name the panel's exact origin. |
| API returns 503 on `/ready` | Redis is unreachable. `/health` stays 200 — that is intended. |
| Deferred actions never fire | The worker is down or its Redis is a different instance than the bot's. |
| Services restart in a loop | Usually the production config check. `logs migrate` and `logs api` name the exact problem. |

