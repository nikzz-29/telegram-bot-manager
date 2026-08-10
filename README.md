# Telegram Bot Manager

Мультитенантный SaaS-бот для управления Telegram-чатами. Сейчас реализован **Этап 0 — скелет**: `uv`-workspace, FastAPI, aiogram, ARQ worker, SQLAlchemy/Alembic, Redis/PostgreSQL, Mini App-заглушка и общий i18n.

## Быстрый запуск

1. Скопируйте `.env.example` в `.env` и укажите `BOT_TOKEN`.
2. Запустите `docker compose -f infra/docker/docker-compose.yml up --build`.
3. API будет доступен на `http://localhost:8000/docs`, health-check — `http://localhost:8000/health`.

Локальные команды:

```bash
uv sync
task api
task bot
task worker
task lint
task test
```

Команда `task bot` запускает polling с корректным `PYTHONPATH` для `apps/bot` и общих пакетов.

При запуске приложений из macOS используйте `localhost` для PostgreSQL и Redis. Имена `postgres` и `redis` работают только внутри Docker-сети; команды `task api` и `task worker` уже подставляют локальные адреса автоматически.

## Архитектурные решения

- `aiogram 3` используется вместо grammY.
- `FastAPI` используется вместо NestJS.
- `SQLAlchemy 2.0 + Alembic` используется вместо Prisma.
- `ARQ` используется вместо BullMQ.
- `Pydantic v2` используется вместо zod.
- `structlog` используется вместо pino.
- `uv workspace + Taskfile` используется вместо Turborepo.

Приложения импортируют общий код только из `packages/*`; это сохраняет границы между bot, API и worker.

## Сервисы

- `apps/api` — REST API и OpenAPI для Mini App.
- `apps/bot` — Telegram long polling в dev-режиме.
- `apps/worker` — заготовка ARQ worker.
- `apps/miniapp` — React + TypeScript + Vite заглушка.
- `packages/db` — SQLAlchemy-модели и Alembic.
- `packages/shared` — настройки и общие enum/схемы.
- `packages/i18n` — Fluent-локали.

## ENV

См. `.env.example`. `BOT_TOKEN` обязателен только для запуска бота; API и миграции могут запускаться без него.
