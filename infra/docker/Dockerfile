FROM python:3.12-slim AS base
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir uv && uv sync --frozen

FROM base AS api
ENV PYTHONPATH=/app/apps/api/src:/app/packages/shared/src:/app/packages/db/src
CMD ["uv", "run", "uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS bot
ENV PYTHONPATH=/app/apps/bot/src:/app/packages/core/src:/app/packages/shared/src:/app/packages/i18n/src
CMD ["uv", "run", "python", "-m", "bot"]

FROM base AS worker
ENV PYTHONPATH=/app/apps/worker/src:/app/packages/shared/src
CMD ["uv", "run", "arq", "worker.settings.WorkerSettings"]
