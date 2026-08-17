# Деплой

Пять процессов, два хранилища и статическая сборка. Бот общается с Telegram,
API обслуживает Mini App, воркер выполняет всё отложенное, Nginx отдаёт панель
и проксирует единый origin, а `migrate` отрабатывает один раз перед стартом
Python-сервисов.

- [Требования](#требования)
- [Первый деплой](#первый-деплой)
- [Production](#production)
- [Конфигурация](#конфигурация)
- [Polling или webhook](#polling-или-webhook)
- [Миграции](#миграции)
- [Mini App](#mini-app)
- [Платежи](#платежи)
- [Масштабирование](#масштабирование)
- [Эксплуатация](#эксплуатация)

## Требования

- Docker с Compose v2 (`docker compose version` ≥ 2.20; для production overlay
  с `!reset` нужен Compose ≥ 2.24.4).
- Токен бота от [@BotFather](https://t.me/BotFather).
- Для webhook: публичный HTTPS URL — собственный домен или Cloudflare Tunnel.
- Для внешнего хостинга панели вместо встроенного Nginx: проект на
  [Vercel](https://vercel.com) или любой статический хостинг.

Больше на хост ничего не ставится. Postgres и Redis поднимаются из compose-файла,
а три сервиса используют один образ, собранный из корня репозитория.

## Первый деплой

```bash
git clone <ваш-форк> && cd tg-bot-manager
cp .env.example .env
$EDITOR .env                      # BOT_TOKEN, JWT_SECRET, CORS_ORIGINS, APP_ENV
docker compose -f infra/docker/docker-compose.yml up -d --build
```

JWT-секрет нужно сгенерировать, а не придумать:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

При `APP_ENV=production` процесс откажется стартовать на небезопасной
конфигурации вместо того, чтобы работать с ней: плейсхолдер `JWT_SECRET`, пустой
`BOT_TOKEN`, `CORS_ORIGINS=*` или webhook без секрета. Ошибка перечисляет все
проблемы разом, так что чинятся они за один проход.

Проверить, что поднялось:

```bash
docker compose -f infra/docker/docker-compose.yml ps
curl -fsS localhost:8080 >/dev/null       # Mini App через Nginx
curl -fsS localhost:8080/api/health       # API через тот же origin
curl -fsS localhost:8000/api/health   # {"status":"ok",...}
curl -fsS localhost:8000/api/ready    # 503, пока Redis недоступен
docker compose -f infra/docker/docker-compose.yml logs -f bot
```

## Production

Для боевого запуска используйте отдельный файл секретов и overlay. Он не
публикует Postgres, Redis и API наружу, включает пароль Redis, обязательные
проверки `APP_ENV=production`, healthcheck бота/воркера, лимиты памяти/CPU,
ротацию Docker-логов и ежедневный PostgreSQL backup в volume
`postgres_backups`:

```bash
cp .env.production.example .env.production
$EDITOR .env.production
docker compose --env-file .env.production \
  -f infra/docker/docker-compose.yml \
  -f infra/docker/docker-compose.production.yml \
  --profile production up -d --build
```

`POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `JWT_SECRET`, `BOT_TOKEN`,
`WEBHOOK_SECRET` и `CLOUDFLARE_TUNNEL_TOKEN` должны быть сгенерированы
случайно и не храниться в git. Пароли в URL должны быть URL-safe; для генерации
подходит `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

Named Tunnel должен иметь один hostname, например `panel.example.com`, с
маршрутизацией на `http://web:80`. Этот же HTTPS origin укажите в
`WEBAPP_URL`, `CORS_ORIGINS`, `WEBHOOK_BASE_URL` и в BotFather → Bot Settings →
Menu Button. В Cloudflare Zero Trust создайте tunnel, скопируйте его token в
`CLOUDFLARE_TUNNEL_TOKEN`, а затем проверьте:

```bash
docker compose --env-file .env.production \
  -f infra/docker/docker-compose.yml \
  -f infra/docker/docker-compose.production.yml ps
curl -fsS https://panel.example.com/api/health
curl -fsS https://panel.example.com/api/ready
```

Ежедневный backup создаётся автоматически. Перед миграцией и не реже раза в
неделю проверяйте настоящее восстановление. Сначала скопируйте последний файл
из volume в текущий каталог, затем восстановите его в одноразовый PostgreSQL:

```bash
backup_container=$(docker compose --env-file .env.production \
  -f infra/docker/docker-compose.yml \
  -f infra/docker/docker-compose.production.yml ps -q backup)
latest=$(docker exec "$backup_container" sh -c 'ls -1t /backups/*.dump.gz | head -n1')
docker cp "$backup_container:$latest" ./latest.dump.gz
bash scripts/verify_backup.sh ./latest.dump.gz
```

Скрипт проверки намеренно принимает только явно указанный файл и удаляет
временный контейнер после результата. Эту команду удобно запускать еженедельно
из cron/CI и поднимать alert, если exit code ненулевой.

Для локального открытия панели внутри Telegram проще всего запустить
`cloudflared` в том же Compose. Он обращается к `web:80` по внутренней сети и
поэтому не зависит от того, слушает ли хостовый Vite IPv4 или IPv6:

```bash
docker compose -f infra/docker/docker-compose.yml --profile tunnel up -d
docker compose -f infra/docker/docker-compose.yml logs -f tunnel
```

В логах появится `https://...trycloudflare.com`. Если `cloudflared` уже
установлен на хосте, эквивалентная команда — `cloudflared tunnel --url
http://127.0.0.1:8080`.

Каждый новый quick tunnel получает новый адрес. Его нужно одновременно записать
в `WEBAPP_URL`, `CORS_ORIGINS` и Web App URL в BotFather, после чего пересоздать
`api` и `bot` следующей командой:

```bash
docker compose -f infra/docker/docker-compose.yml up -d --no-deps --force-recreate api bot
```

Не пересоздавайте при этом сервис `tunnel`: новый контейнер получит новый URL,
и настройку придётся повторить. Пока используется Docker-сервис `web`, отдельно
запускать `task miniapp` не нужно.

`/health` — это liveness-проба, и она не опрашивает ничего: API, падающий по ней
из-за недоступного Redis, был бы перезапущен оркестратором, а Redis это не
вернёт. `/ready` — та, что отвечает 503, когда недоступна зависимость, без
которой API не может обслуживать запросы. Балансировщик направляйте именно на неё.

## Конфигурация

Каждая настройка — переменная окружения, читаемая один раз при старте в
`packages/shared/src/shared/config.py`; в `.env.example` описаны все 23 с
дефолтами. Те, что важны в проде:

| Переменная | Почему важна |
| --- | --- |
| `APP_ENV` | `production` включает проверки безопасности при старте. |
| `BOT_TOKEN` | От @BotFather. Нужен боту, API и воркеру — последние два тоже обращаются к Bot API. |
| `JWT_SECRET` | Подписывает сессии панели. ≥32 байт и никогда не поставляемый плейсхолдер. |
| `CORS_ORIGINS` | Точный origin панели. `*` в проде отклоняется. |
| `WEBAPP_URL` | HTTPS-адрес Mini App, который бот помещает в кнопку операторской панели. |
| `SUPERADMIN_IDS` | Telegram-id через запятую, кому доступна платформенная консоль. Пусто — никому. |
| `AI_BASE_URL`, `AI_MODEL` | По умолчанию используется бесплатный keyless LLM7 (`DeepSeek-V4-Flash-0731`). Текст проверяемых сообщений передаётся выбранному внешнему провайдеру. |
| `AI_API_KEY` | Необязателен для LLM7 и локальных моделей; указывается только для провайдера, который требует авторизацию. |
| `AI_COMPLETION_PATH` | Путь OpenAI-compatible chat completions, по умолчанию `/chat/completions`. |
| `CRYPTOBOT_TOKEN` | Необязателен. Stars работают без него, криптоплатежи — нет. |

Compose передаёт `.env` каждому сервису через `env_file`, а затем перекрывает
`DATABASE_URL` и `REDIS_URL` на внутрисетевые имена. Значения в самом `.env`
остаются указывать на `localhost:5433` / `localhost:6380`, чтобы `task api`
продолжал работать на хосте — один файл обслуживает оба случая.

Шаблон задаёт `WEBAPP_URL=http://localhost:8080`, потому что полный Compose
отдаёт панель через Nginx. Для отдельного dev-сервера `task miniapp` замените
его на `http://localhost:5173`; для Telegram в обоих случаях нужен публичный
HTTPS origin туннеля или домена.

`.env` перечислен в `.gitignore` и `.dockerignore`. В нём живой токен, а копия,
запечённая в образ, переживает любой `docker rm`.

## Polling или webhook

Long polling — режим по умолчанию, ему вообще не нужна входящая связность. Это
правильный выбор до тех пор, пока бот не вырастет настолько, что лишний
round-trip начнёт что-то значить.

Переключение:

```bash
USE_WEBHOOK=true
WEBHOOK_BASE_URL=https://bot.example.com   # https и доступен со стороны Telegram
WEBHOOK_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

Бот поднимет собственный эндпоинт на `WEBHOOK_PORT` (по умолчанию 8081).
Встроенный сервис `web` уже проксирует стандартный путь
`/telegram/webhook` на `bot:8081`, поэтому для полного Compose и Cloudflare
Tunnel дополнительный Nginx не нужен. Оставьте `WEBHOOK_PATH` и `WEBHOOK_PORT`
стандартными, укажите URL туннеля в `WEBHOOK_BASE_URL` и пересоздайте только бот:

```bash
docker compose -f infra/docker/docker-compose.yml up -d --no-deps --force-recreate bot
```

Если TLS завершает отдельный Nginx на хосте, Compose публикует порт бота только
на `127.0.0.1`, и внешний прокси настраивается так:

```nginx
location /telegram/webhook {
    proxy_pass http://127.0.0.1:8081;
    proxy_set_header X-Telegram-Bot-Api-Secret-Token $http_x_telegram_bot_api_secret_token;
}
```

Telegram возвращает `WEBHOOK_SECRET` в этом заголовке, а бот его сверяет — значит,
прокси обязан заголовок пробрасывать. Без секрета любой, кто узнает URL, сможет
слать поддельные апдейты; поэтому прод отказывается стартовать, когда
`USE_WEBHOOK` включён, а секрет не задан.

Возврат на polling не требует уборки: бот удаляет оставшийся webhook при старте,
потому что `getUpdates` отвечает 409, пока webhook зарегистрирован, — иначе
процесс поднялся бы чисто и не получал ничего.

Webhook намеренно **не** удаляется при остановке. Telegram копит апдейты, пока
эндпоинт недоступен, и доставляет их повторно, так что рестарт ничего не теряет;
удаление же открывало бы окно на каждом деплое.

## Миграции

Сервис `migrate` выполняет `alembic upgrade head` и завершается. Остальные три
ждут `service_completed_successfully`, поэтому схема никогда не становится
гонкой трёх процессов, стартующих одновременно. Каждый `up` применяет
незакрытые миграции до того, как что-либо начнёт обслуживать трафик.

Вручную:

```bash
docker compose -f infra/docker/docker-compose.yml run --rm migrate
task migrate                                              # на хосте
task revision -- "add whatever"                           # автогенерация
```

Читайте сгенерированные миграции перед коммитом. Автогенерация надёжно ловит
добавленные таблицы и колонки; переименование она видит как удаление плюс
добавление, а на живой таблице это тихая потеря данных.

Бэкап перед деплоем с миграцией:

```bash
docker compose -f infra/docker/docker-compose.yml exec postgres \
    pg_dump -U postgres tg_manager | gzip > backup-$(date +%F).sql.gz
```

## Mini App

В полном Compose панель собирается отдельной Node-стадией и попадает в небольшой
Nginx-образ `web`; Node и исходники в финальном образе не остаются. Nginx отдаёт
SPA и проксирует `/api`, поэтому клиент использует относительный same-origin URL
и `VITE_API_BASE_URL` задавать не нужно.

Vercel остаётся альтернативой встроенному Nginx:

| Настройка | Значение |
| --- | --- |
| Root directory | `apps/miniapp` |
| Install command | `pnpm install` |
| Build command | `pnpm run build` |
| Output directory | `dist` |
| `VITE_API_BASE_URL` | `https://api.example.com` — только если API на другом origin |

Снимайте галку «Include source files outside of the Root Directory» только если
уверены: сборка импортирует `.ftl` из `packages/i18n` через алиас `@locales` —
так панель и бот читают один набор локалей. Чтобы этот импорт разрешился,
Vercel нужен корень репозитория.

Дальше адрес панели должен быть согласован в трёх местах, иначе бот откроет
старый origin или браузер заблокирует запросы к отдельному API:

1. `WEBAPP_URL` в `.env` — адрес, который бот помещает в Web App кнопку.
2. Web App URL в BotFather (`/mybots` → Bot Settings → Menu Button).
3. Адрес, по которому панель реально отдаётся через Nginx, tunnel или Vercel.

`CORS_ORIGINS` должен называть тот же origin в точности. Прод не принимает `*`.

После изменения схемы API перегенерируйте типизированный клиент, чтобы типы
панели соответствовали тому, что API отдаёт:

```bash
task client       # экспортирует openapi.json, затем пересобирает src/api/schema.ts
```

## Платежи

**Telegram Stars** не требуют настройки. Инвойсы создаёт бот, расчёт проводит
Telegram; обработчик `pre_checkout_query` уже подключён.

**CryptoBot** требует `CRYPTOBOT_TOKEN` от [@CryptoBot](https://t.me/CryptoBot)
и вебхука, указывающего на API:

```
https://api.example.com/payments/cryptobot/webhook
```

Встроенный Nginx проксирует именно этот стандартный путь. Если переопределить
`CRYPTOBOT_WEBHOOK_PATH`, тот же маршрут нужно изменить в
`infra/nginx/default.conf`.

Этот маршрут намеренно исключён из OpenAPI-схемы — он не часть контракта
панели. Он отвечает 200 на всё, что уже обработано или не разбирается, потому
что не-2xx заставит CryptoBot вечно повторять запрос с payload, который никогда
не пройдёт.

### Тестовая сеть CryptoBot

Чтобы прогнать покупку подписки, не платя настоящими деньгами, есть
`CRYPTOBOT_TESTNET`:

```env
CRYPTOBOT_TOKEN=<токен от @CryptoTestnetBot>
CRYPTOBOT_TESTNET=true
```

Меняются токен и сеть вместе: токен выдаётся под одну сеть, и боевой на тестовом
хосте (`https://testnet-pay.crypt.bot`) отвечает ошибкой авторизации, как и
наоборот. Поэтому флаг один, а не второй токен рядом с первым — иначе легко
получить пару, где ни один счёт не открывается, а причина не видна.

Тестовые счета оплачиваются игровым балансом [@CryptoTestnetBot](https://t.me/CryptoTestnetBot),
но подписка продлевается по-настоящему: вебхук и `core.billing` не отличают сеть.
Поэтому при `APP_ENV=production` вместе с `CRYPTOBOT_TESTNET=true` процесс
откажется стартовать — иначе платные тарифы раздавались бы бесплатно.

В логах открытие клиента видно как `cryptobot.client_opened` с полями `testnet` и
`network`; это самый быстрый способ убедиться, куда реально уходят счета.

## Масштабирование

**Воркер масштабируется горизонтально.** В нём выполняется каждое отложенное
действие, и реплики стоит добавлять в первую очередь именно ему:

```bash
docker compose -f infra/docker/docker-compose.yml up -d --scale worker=3
```

Cron-джобы остаются корректными на нескольких репликах: ARQ ставит их в очередь
с детерминированным job id, выведенным из времени запуска (`unique=True`), — три
воркера, столкнувшись на одном тике, породят одну джобу.

**API масштабируется горизонтально** за любым балансировщиком. Между запросами
он не хранит состояния: сессии — это JWT, а всё кэшируемое лежит в Redis.

**Бот не масштабируется репликами, пока работает на polling.** Два поллера с
одним токеном получают каждый апдейт оба. На webhook — масштабируется: апдейты
дедуплицируются через Redis ровно потому, что Telegram доставляет повторно при
медленном ответе, а rolling-деплой на короткое время держит две реплики.

Вертикальные ручки, все в `.env`:

| Переменная | Дефолт | Что задаёт |
| --- | --- | --- |
| `SENDER_WORKERS` | 4 | Параллельных исходящих отправок на процесс. |
| `GLOBAL_SEND_RATE` | 30 | Сообщений в секунду по всем чатам — задокументированный потолок Telegram. |
| `GROUP_SEND_RATE_PER_MINUTE` | 20 | Потолок на группу. Поднимете — получите 429. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 10 / 20 | Соединений на процесс. Умножьте на число реплик и сравните с `max_connections` у Postgres. |

Лимиты отправки — это лимиты Telegram, а не наши. Их повышение не отправляет
больше сообщений; оно превращает отказы в ожидание по `retry_after`.

## Эксплуатация

**Логи** — JSON в stdout (`LOG_JSON=true`), как и нужно сборщику логов. Для
человекочитаемого вывода локально поставьте false.

```bash
docker compose -f infra/docker/docker-compose.yml logs -f bot worker
```

**Выкатка изменений:**

```bash
git pull
docker compose -f infra/docker/docker-compose.yml up -d --build
```

Compose останавливает старые контейнеры через SIGTERM, и все три его
обрабатывают, а не умирают на нём. Бот выходит из своего раннера и дренирует
очередь отправки — уже принятый бан всё равно дойдёт до Telegram. Воркер
отменяет выполняющиеся джобы и возвращает их в очередь (ARQ повторяет при
отмене), после чего дренирует собственный sender в `on_shutdown`. Дайте им
время закончить: `--timeout 30`, если дефолтных 10 секунд под нагрузкой мало.

**Откат** — это `git checkout <tag>` и та же команда, с одной оговоркой:
миграции вместе с кодом не откатываются. Если неудачный деплой мигрировал схему,
либо сначала `alembic downgrade -1` (прочитав, что именно он удаляет), либо
катитесь вперёд.

**Шелл для разовых задач:**

```bash
docker compose -f infra/docker/docker-compose.yml exec api python
docker compose -f infra/docker/docker-compose.yml exec postgres psql -U postgres tg_manager
```

**Когда что-то не так** — в том порядке, в котором обычно и находится:

| Симптом | Куда смотреть |
| --- | --- |
| Бот молчит, ошибок нет | При polling зарегистрирован webhook. `getWebhookInfo` через API — или просто перезапустите, бот его снимет. |
| Панель отдаёт 401 | Проверьте свежесть Telegram `initData`, `BOT_TOKEN` API и время на хосте; URL панели сам по себе подпись не формирует. |
| Панель показывает ошибку CORS | `CORS_ORIGINS` не называет точный origin панели. |
| API отвечает 503 на `/ready` | Недоступен Redis. `/health` остаётся 200 — так и задумано. |
| Отложенные действия не срабатывают | Воркер не поднят либо смотрит в другой Redis, не в тот, что бот. |
| Сервисы перезапускаются по кругу | Обычно это проверка прод-конфигурации. `logs migrate` и `logs api` называют конкретную проблему. |
