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
FROM python:3.12-slim AS builder

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
COPY apps apps
COPY packages packages

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

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
