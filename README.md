# Telegram Bot Manager

Мультитенантный SaaS-бот для управления Telegram-чатами: модерация, антиспам,
капча, статистика, репутация, автопостинг, ИИ-модерация и сеть кросс-банов —
всё настраивается из Telegram Mini App, помодульно и по тарифам.

Один бот обслуживает произвольное число чатов. У каждого чата свой тариф, свой
набор включённых модулей, своя конфигурация каждого модуля и свой язык.

## Возможности

| Модуль | Тариф | Что делает |
| --- | --- | --- |
| **moderation** | Free | `/ban`, `/mute`, `/warn`, `/kick` и ещё шесть команд; стоп-слова с обходом гомоглифов, фильтры контента, антифлуд со скользящим окном, лог-канал |
| **entry** | Free | Капча на входе, приветствие, антирейд, автобан новорегов |
| **stats** | Pro | Счётчики активности, ежедневная агрегация, ежедневные и недельные отчёты в часовом поясе чата |
| **engagement** | Pro | Триггеры, репутация (`+`/`-`), уровни |
| **autopost** | Pro | Отложенные и повторяющиеся посты, форс-подписка на канал |
| **ai_moderation** | Business | Бесплатный keyless LLM7 по умолчанию или любой OpenAI-совместимый endpoint, circuit breaker, дневной бюджет |
| **crossban** | Business | Общий чёрный список: три независимых чата, забанивших за скам, дают глобальный бан |

Тарифы: **Free**, **Pro** (299 ⭐ / $4.99), **Business** (999 ⭐ / $14.99),
**White Label** (4999 ⭐ / $79). Оплата — Telegram Stars или CryptoBot, с
напоминаниями об истечении и grace-периодом перед понижением.

Модуль объявляется один раз в `packages/core/src/core/registry.py` — оттуда
берутся и меню команд бота, и разделы панели, и матрица тарифов. Добавление
модуля не требует правок в TypeScript.

## Быстрый старт

```bash
cp .env.example .env      # заполните BOT_TOKEN
docker compose -f infra/docker/docker-compose.yml up -d --build
```

Готовая Mini App через Nginx поднимется на `localhost:8080`, API отдельно
останется доступен на `localhost:8000` (`/docs` — Swagger, `/api/health` —
проба), а бот начнёт long polling. Для Telegram можно поднять quick tunnel
внутри Compose:

```bash
docker compose -f infra/docker/docker-compose.yml --profile tunnel up -d
docker compose -f infra/docker/docker-compose.yml logs -f tunnel
```

Либо используйте установленный на хосте `cloudflared tunnel --url
http://127.0.0.1:8080`. Полученный HTTPS URL нужно одинаково указать в
`WEBAPP_URL`, `CORS_ORIGINS` и BotFather, затем перечитать `.env`, не перезапуская
quick tunnel:

```bash
docker compose -f infra/docker/docker-compose.yml up -d --no-deps --force-recreate api bot
```

Полная инструкция, включая webhook, Vercel и масштабирование, — в
[`docs/deploy.md`](docs/deploy.md).

## Разработка

Нужны [uv](https://docs.astral.sh/uv/), [Task](https://taskfile.dev) и pnpm.

```bash
uv sync
docker compose -f infra/docker/docker-compose.yml up -d postgres redis
task migrate

task api        # uvicorn с автоперезагрузкой
task bot        # long polling
task worker     # ARQ
task miniapp    # Vite dev-сервер
```

Postgres и Redis слушают **5433** и **6380**, а не стандартные порты — чтобы не
конфликтовать с уже установленными локально.

Гейты — те же, что в CI:

```bash
task lint       # ruff check + ruff format --check + mypy .
task test       # pytest
task check      # оба
task client     # перегенерировать TS-клиент из OpenAPI
```

`mypy .` проходит по всем 137 файлам, включая тесты; 322 теста зелёные.

## Структура

```
apps/
  bot/        aiogram 3: роутеры модулей, цепочка middleware, runner (polling/webhook)
  api/        FastAPI: initData → JWT, эндпоинты панели, вебхук CryptoBot
  worker/     ARQ: всё отложенное — размуты, посты, агрегация, напоминания
  miniapp/    React + TypeScript + Vite: панель управления
packages/
  core/       бизнес-логика: реестр модулей, тарифы, кэш, sender, сервисы
  db/         SQLAlchemy 2.0 async, репозитории, Unit of Work, Alembic
  shared/     настройки, enum'ы, Pydantic-схемы, логирование
  i18n/       Fluent-локали RU/EN — общие для бота и панели
```

Приложения импортируют общий код только из `packages/*`. Бот не импортирует API,
API не импортирует бота; всё, что нужно обоим, живёт в `core`.

## Ключевые решения

Стек в ТЗ был описан через TypeScript-аналоги; здесь всё, кроме панели, на
Python:

| Вместо | Используется | Почему |
| --- | --- | --- |
| grammY | **aiogram 3** | Роутеры, middleware, фильтры, FSM — нативный asyncio |
| NestJS | **FastAPI** | Pydantic v2 как единый слой валидации и OpenAPI |
| Prisma | **SQLAlchemy 2.0 + Alembic** | Типизированный async ORM и честные миграции |
| BullMQ | **ARQ** | Персистентные джобы на том же Redis |
| zod | **Pydantic v2** | Одна схема на валидацию, сериализацию и OpenAPI |
| pino | **structlog** | JSON-логи с контекстом |
| Turborepo | **uv workspace + Taskfile** | Один локфайл на весь монорепозиторий |

Решения, которые стоит знать, прежде чем менять код:

- **Ничего отложенного через `asyncio.sleep`.** Размуты, автоудаление и посты —
  джобы ARQ с явным `_job_id`: идемпотентны, отменяемы, переживают рестарт.
- **Весь исходящий трафик идёт через `core.sender`** с двумя токен-бакетами в
  Redis (30/сек глобально, 20/мин на чат) и классификацией ошибок Telegram.
- **`initData` проверяется на каждый вход в панель**, затем выдаётся JWT;
  права админа кэшируются на 5 минут, как требует ТЗ.
- **Все datetime — UTC-aware.** Наивных нет ни в моделях, ни в джобах.
- **Ни одной захардкоженной строки** в ответах бота и панели: всё через Fluent,
  один каталог на оба рантайма, парность ключей RU/EN проверяется тестом.
- **Прод падает на старте при небезопасной конфигурации** — плейсхолдер
  `JWT_SECRET`, `CORS_ORIGINS=*`, webhook без секрета.

Решения, принятые по ходу, помечены в коде комментариями `# DECISION:` — там,
где нужно объяснить не «что», а «почему именно так».

## Документация

- [`docs/deploy.md`](docs/deploy.md) — деплой, webhook, миграции, масштабирование
- [`.env.example`](.env.example) — все 23 переменные с комментариями
- `/docs` на запущенном API — Swagger по всем 38 операциям
