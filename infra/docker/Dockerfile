# One image, three entrypoints. The bot, the API and the worker share every
# package they import, so building three separate images would triple the layer
# cache to hold the same dependency tree three times.
#
# DECISION: dependencies install from the lockfile *before* the source is copied.
# Editing a handler invalidates only the final `COPY`, so a code change rebuilds
# in seconds instead of resolving the tree again.
#
# DECISION: `uv sync --no-dev` — the runtime images have no pytest, no mypy and
# no testcontainers. That is a smaller attack surface, not only a smaller image.
FROM python:3.14-slim AS builder

# uv comes from its own image rather than pip, which keeps the resolver's
# version pinned by digest instead of by whatever pip finds today.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# The workspace members' manifests are all `uv sync` needs to resolve, so they
# are the only thing in this layer.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY apps/bot/pyproject.toml apps/bot/
COPY apps/worker/pyproject.toml apps/worker/
COPY packages/core/pyproject.toml packages/core/
COPY packages/db/pyproject.toml packages/db/
COPY packages/i18n/pyproject.toml packages/i18n/
COPY packages/shared/pyproject.toml packages/shared/

# `--no-install-workspace` resolves the third-party tree without needing our own
# source yet; the members install in the second pass below.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace

COPY alembic alembic
COPY alembic.ini ./
COPY apps/api apps/api
COPY apps/bot apps/bot
COPY apps/worker apps/worker
COPY packages packages

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev


FROM python:3.14-slim AS runtime

# Nothing in these services needs root, and a webhook handler that does is one
# container escape away from being a much worse day.
RUN useradd --create-home --uid 10001 app

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --from=builder --chown=app:app /app /app
USER app

# The venv is on PATH and the workspace packages are installed into it, so the
# entrypoints are plain console commands — no `uv run`, no PYTHONPATH.
FROM runtime AS api
EXPOSE 8000
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS bot
CMD ["python", "-m", "bot"]

FROM runtime AS worker
CMD ["arq", "worker.settings.WorkerSettings"]

# Runs the migrations and exits. Compose gates the three services on it, so the
# schema is never a race between three processes starting at once.
FROM runtime AS migrate
CMD ["alembic", "upgrade", "head"]


# Build the browser-only application separately from the Python workspace. It
# deliberately uses a same-origin API URL: Nginx below proxies `/api` to the API
# container, so neither a tunnel hostname nor a production domain is compiled
# into the JavaScript bundle.
FROM node:20-alpine AS miniapp-builder

ARG PNPM_VERSION=10.15.1
RUN corepack enable && corepack prepare "pnpm@${PNPM_VERSION}" --activate

WORKDIR /app/apps/miniapp
COPY apps/miniapp/package.json apps/miniapp/pnpm-lock.yaml apps/miniapp/pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

COPY apps/miniapp ./
COPY packages/i18n/locales /app/packages/i18n/locales
RUN pnpm run build


FROM node:20-alpine AS site-builder

ARG PNPM_VERSION=10.15.1
RUN corepack enable && corepack prepare "pnpm@${PNPM_VERSION}" --activate

WORKDIR /app/apps/site
COPY apps/site/package.json apps/site/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

COPY apps/site ./
RUN pnpm run build


# One public origin for both the Mini App and API. Cloudflare Tunnel (or a
# regular TLS reverse proxy in production) points here, never at Vite directly.
FROM nginx:1.27-alpine AS web

COPY infra/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=miniapp-builder /app/apps/miniapp/dist /usr/share/nginx/html
COPY --from=site-builder /app/apps/site/dist /usr/share/nginx/html/site

EXPOSE 80
