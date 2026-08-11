# Тексты, которые существуют только в панели (Mini App).
#
# Ключи, которые уже есть у бота — названия тарифов, заголовки и описания
# модулей, тексты ошибок, которые API возвращает по ключу, — лежат в main.ftl и
# переиспользуются оттуда. Здесь только то, чего больше нигде нет.

## Оболочка
panel-loading = Загрузка…
panel-retry = Повторить
panel-save = Сохранить
panel-saving = Сохраняем…
panel-cancel = Отмена
panel-delete = Удалить
panel-edit = Изменить
panel-confirm-delete = Удалить безвозвратно?
# Кнопки диалога о несохранённом: «Отмена» здесь не годится — непонятно, что
# именно отменяют, выход или сами правки.
panel-discard = Изменения не сохранены. Если выйти, они пропадут.
panel-discard-leave = Выйти
panel-discard-stay = Остаться
panel-language = Язык
# Названия языков остаются на своём языке — тот, кто ищет переключатель,
# высматривает «English», а не русское слово для него.
locale-ru = Русский
locale-en = English
panel-outside-telegram = Откройте панель из Telegram — ей нужны данные запуска, которые передаёт клиент.
panel-auth-failed = Не удалось войти. Закройте панель и откройте её заново из чата.

## Список чатов
chats-title = Ваши чаты
chats-empty = Чатов пока нет. Добавьте бота в группу, выдайте права администратора и откройте панель снова.
chats-role-owner = Владелец
chats-role-admin = Администратор
chats-members = {$count ->
        [one] {$count} участник
        [few] {$count} участника
       *[other] {$count} участников
    }
chats-inactive = Бот удалён

## Экран чата
chat-sections = Разделы
chat-tools = Инструменты
chat-language = Язык чата
chat-timezone = Часовой пояс
chat-timezone-hint = Используется для отложенных постов и ежедневных отчётов. Например: Europe/Moscow.
chat-sync-admins = Обновить список админов
chat-sync-admins-hint = Запустите после назначения нового администратора в Telegram.
chat-sync-done = Список администраторов обновлён
chat-general = Общие

## Модули
module-enabled = Включён
# Сам ключ `module-locked` лежит в main.ftl — бот говорит ту же фразу, когда
# команда закрыта тарифом, а два текста для одной ситуации со временем разойдутся.
module-locked-cta = Перейти на {$plan}
module-reset = Сбросить настройки
module-reset-confirm = Вернуть все настройки этого раздела к значениям по умолчанию?
section-billing = Тариф
section-platform = Платформа

## Настройки — общие подписи полей
field-unset = Не задано
field-item-placeholder = Новая запись
field-seconds = сек.
field-minutes = мин.
field-hours = ч.
field-days = дн.
field-characters = симв.
field-messages-count = {$count ->
        [one] {$count} сообщение
        [few] {$count} сообщения
       *[other] {$count} сообщений
    }
field-invalid-number = Введите число от {$min} до {$max}.

## Настройки — заголовки групп
#
# Форму каждого модуля панель строит из JSON Schema, которую отдаёт API, и
# группирует поля по префиксу имени. Здесь — заголовки этих групп.
settings-group-general = Общие
settings-group-warn = Предупреждения
settings-group-stop-word = Стоп-слова
settings-group-filter = Фильтры контента
settings-group-anti-flood = Антифлуд
settings-group-captcha = Капча
settings-group-greeting = Приветствие
settings-group-autoban = Новые аккаунты
settings-group-anti-raid = Антирейд
settings-group-forced-subscription = Обязательная подписка
settings-group-reputation = Репутация
settings-group-levels = Уровни
settings-group-track = Учёт
settings-group-report = Отчёты

## Настройки — варианты выбора
option-nothing = Ничего не делать
option-delete = Удалять
option-delete-warn = Удалять и предупреждать
option-delete-mute = Удалять и выдавать мут
option-alert-admins = Сообщать администраторам
option-mute = Мут
option-ban = Бан
option-kick = Исключение
option-button = Кнопка
option-emoji = Эмодзи
option-math = Пример
option-captcha = Отправлять на капчу

## Настройки — подписи полей, по одной на свойство схемы
setting-enabled = Включено
setting-timezone = Часовой пояс
setting-warn-limit = Предупреждений до наказания
setting-warn-punishment = Наказание при лимите
setting-warn-punishment-hours = Срок наказания
setting-warn-lifetime-days = Предупреждение сгорает через
setting-stop-words = Стоп-слова
setting-stop-word-presets = Готовые списки
setting-stop-word-action = При стоп-слове
setting-stop-word-mute-hours = Срок мута
setting-filters-links = Ссылки
setting-filters-mentions = Упоминания @
setting-filters-forwards = Пересылки
setting-filters-photos = Фото
setting-filters-videos = Видео
setting-filters-gifs = GIF
setting-filters-stickers = Стикеры
setting-filters-voices = Голосовые
setting-filters-video-notes = Видеосообщения
setting-filters-documents = Файлы
setting-filters-channel-senders = Сообщения от имени канала
setting-filter-action = При срабатывании фильтра
setting-anti-flood-enabled = Антифлуд включён
setting-anti-flood-messages = Сообщений можно
setting-anti-flood-seconds = …за
setting-anti-flood-mute-minutes = Срок мута
setting-anti-flood-media-messages = Медиа можно
setting-anti-flood-media-seconds = …за
setting-log-channel-id = ID канала для логов
setting-delete-service-messages = Удалять сообщения о входе и выходе
setting-exempt-admins = Не применять к администраторам
setting-captcha-enabled = Капча при входе
setting-captcha-kind = Тип капчи
setting-captcha-timeout-minutes = Время на ответ
setting-captcha-kick-on-timeout = Исключать, если не ответил
setting-greeting-enabled = Приветствовать новичков
setting-greeting-text = Текст приветствия
setting-greeting-media-file-id = file_id картинки
setting-greeting-delete-after-minutes = Удалять приветствие через
setting-rules-link = Ссылка на правила
setting-autoban-new-accounts = Проверять новые аккаунты
setting-autoban-require-username = Требовать @username
setting-autoban-require-photo = Требовать аватар
setting-autoban-min-account-age-days = Минимальный возраст аккаунта
setting-autoban-action = При подозрительном аккаунте
setting-anti-raid-enabled = Антирейд включён
setting-anti-raid-joins = Входов для срабатывания
setting-anti-raid-seconds = …за
setting-anti-raid-lockdown-minutes = Длительность блокировки
setting-forced-subscription-enabled = Требовать подписку на канал
setting-forced-subscription-channel-id = ID канала
setting-forced-subscription-channel-url = Ссылка на канал
setting-track-messages = Считать сообщения
setting-track-joins = Считать входы и выходы
setting-daily-report-enabled = Ежедневный отчёт
setting-weekly-report-enabled = Еженедельный отчёт
setting-report-hour-utc = Час отправки (UTC)
setting-reputation-enabled = Репутация включена
setting-reputation-keywords = Слова благодарности
setting-reputation-daily-limit = Сколько очков можно раздать за день
setting-reputation-cooldown-seconds = Пауза между очками
setting-levels-enabled = Уровни включены
setting-points-per-message = Очков за сообщение
setting-triggers-enabled = Триггеры включены
setting-sample-rate = Доля проверяемых сообщений
setting-min-text-length = Минимальная длина для проверки
setting-alert-chat-id = ID чата для оповещений
setting-autoban-on-join = Банить при входе
setting-alert-only = Только оповещать, не банить
setting-contribute-bans = Передавать баны в сеть

## Статистика
stats-screen-title = Статистика
stats-range = Период
stats-range-7 = 7 дней
stats-range-30 = 30 дней
stats-range-90 = 90 дней
stats-metric-messages = Сообщения
stats-metric-joins = Вступили
stats-metric-leaves = Вышли
stats-active-users = Активные участники
stats-top-users = Самые активные
stats-no-data = За этот период активности пока нет.
stats-retention-capped = Ваш тариф хранит {$days ->
        [one] {$days} день
        [few] {$days} дня
       *[other] {$days} дней
    } истории.

## Триггеры
triggers-title = Триггеры
triggers-add = Новый триггер
triggers-pattern = Ключевое слово или шаблон
triggers-match = Совпадение
triggers-response = Ответ
triggers-match-exact = Точное совпадение
triggers-match-contains = Содержит
triggers-match-regex = Регулярное выражение
triggers-case-sensitive = Учитывать регистр
triggers-delete-source = Удалять сообщение-триггер
triggers-empty = Триггеров пока нет. Добавьте первый, чтобы отвечать на ключевое слово автоматически.

## Отложенные посты
posts-title = Отложенные посты
posts-add = Новый пост
posts-name = Название
posts-text = Текст поста
posts-schedule = Расписание
posts-schedule-once = Один раз
posts-schedule-daily = Каждый день
posts-schedule-cron = Cron
posts-run-at = Отправить
posts-time = Время
posts-daily-hint = Каждый день, по часовому поясу чата.
posts-cron = Cron-выражение
posts-cron-hint = Минута час день месяц день недели — в часовом поясе чата.
posts-pin = Закреплять после отправки
posts-delete-previous = Удалять предыдущую копию
posts-enabled = Активен
posts-paused = Остановлен
posts-next-run = Следующий: {$when}
posts-empty = Отложенных постов пока нет.

## Репутация
reputation-title = Репутация
reputation-empty = Репутация пока не начислялась.
reputation-score = Очки
reputation-level = Уровень {$level}
reputation-adjust = Изменить
reputation-adjust-hint = Изменение в плюс или минус, а не новое значение.

## Тариф и оплата
billing-title = Тариф
billing-current = Текущий тариф
billing-expires = Продление {$date}
billing-expired = Истёк {$date}
billing-grace = Льготный период до {$date}
billing-lifetime = Без ограничения по сроку
billing-months = {$count ->
        [one] {$count} месяц
        [few] {$count} месяца
       *[other] {$count} месяцев
    }
billing-pay-stars = Оплатить {$amount} Stars
billing-pay-crypto = Оплатить {$amount} USD криптовалютой
billing-history = История платежей
billing-history-empty = Платежей пока не было.
billing-status-paid = Оплачен
billing-status-pending = Ожидает
billing-status-failed = Не прошёл
billing-status-refunded = Возвращён
billing-invoice-opening = Открываем счёт…
billing-invoice-paid = Платёж получен. Тариф активен.
billing-invoice-cancelled = Оплата отменена.
billing-invoice-failed = Не удалось открыть оплату. Деньги не списаны, попробуйте ещё раз.
billing-invoice-unsupported = Этот клиент не умеет открывать ссылки оплаты. Откройте чат в Telegram и попробуйте снова.
billing-choose-term = Срок
billing-features = Что входит

## Что входит в тариф — по ключу на каждый `Feature`
feature-moderation = Предупреждения, муты и баны
feature-captcha = Капча для новичков
feature-greeting = Приветствие
feature-stop-words = Списки стоп-слов
feature-anti-flood = Антифлуд
feature-log-channel = Канал логов модерации
feature-anti-raid = Антирейд
feature-stats = Статистика и отчёты
feature-triggers = Триггеры по ключевым словам
feature-autopost = Отложенные посты
feature-reputation = Репутация
feature-levels = Уровни и очки
feature-forced-subscription = Обязательная подписка на канал
feature-ai-moderation = ИИ-модерация
feature-crossban = Сеть кросс-банов
feature-chat-networks = Связанные сети чатов
feature-priority-support = Приоритетная поддержка
feature-white-label = White label

## Панель оператора платформы
platform-title = Платформа
platform-chats = Чаты
platform-active-chats = Активные
platform-revenue-stars = Stars за 30 дней
platform-revenue-usd = USD за 30 дней
platform-bans = Глобальные баны
platform-bans-title = Глобальный чёрный список
platform-bans-empty = Чёрный список пуст.
platform-ban-add = Добавить в чёрный список
platform-ban-user-id = Telegram ID пользователя
platform-ban-reason = Причина
platform-ban-revoke = Снять бан
platform-ban-chats = Пожаловались {$count ->
        [one] {$count} чат
        [few] {$count} чата
       *[other] {$count} чатов
    }
platform-broadcast-title = Рассылка
platform-broadcast-text = Сообщение
platform-broadcast-plans = Отправить тарифам
platform-broadcast-send = Поставить в очередь
platform-broadcast-queued = В очереди для {$count ->
        [one] {$count} чата
        [few] {$count} чатов
       *[other] {$count} чатов
    }
platform-broadcast-confirm = Отправить это во все чаты выбранных тарифов?
