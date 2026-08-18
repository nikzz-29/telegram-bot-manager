# Русская локаль: личные сообщения с ботом. Ключи должны совпадать
# один-в-один с en/dm.ftl.
#
# Почему отдельный файл: `main.ftl` — это то, что бот говорит в группах, и
# редактируется он вместе с модулями. Диалог в личке — отдельная поверхность со
# своим темпом изменений, и держать её здесь дешевле, чем каждый раз искать
# нужную секцию среди трёхсот ключей.
#
# Соглашение то же, что в main.ftl: {$user} — уже готовая HTML-ссылка на
# участника, экранировать повторно нельзя; остальные подстановки — простой текст.

## Личные сообщения
start-welcome = 👋 <b>Добро пожаловать!</b>

    🛡️ Я помогаю управлять Telegram-чатами: модерирую, встречаю новичков, считаю статистику и публикую посты.
    🚀 Добавьте меня в группу администратором — чат подключится автоматически и сразу получит тариф Free.
    📱 Mini App открывается кнопкой слева от поля ввода: там собраны статистика, чаты, тарифы, профиль и настройки.
    🌐 Команда /website выдаёт одноразовую ссылку на личный веб-кабинет со статистикой и активностью.
    📋 Список команд всегда доступен по закреплённой кнопке внизу.
help-text = 📋 <b>Команды бота</b>

    🛡️ В группах команды модерации доступны администраторам, а публичные команды отмечены отдельно.
    👤 В личных сообщениях можно открыть профиль, чаты, статистику и тарифы.
    📱 Тонкие настройки находятся в Mini App — откройте его кнопкой слева от поля ввода.
open-miniapp = 📱 Открыть Mini App
menu-button = 📱 Mini App

## Личные сообщения — панель управления
admin-welcome = 🛠️ Операторская панель готова к открытию.
admin-forbidden = 🔒 Операторская команда недоступна. Пользовательский Mini App открывается кнопкой слева от поля ввода.

## Личные сообщения — профиль и чаты
dm-profile-header = 👤 <b>{$name}</b>
dm-profile-username = 🔗 Username: {$username}
dm-profile-id = 🆔 Telegram ID: <code>{$id}</code>
dm-profile-language = 🌐 Язык Telegram: {$language}
dm-profile-anonymous = id{$id}
dm-value-not-set = не указан
dm-value-unknown = неизвестно
dm-profile-chats = {$count ->
        [0] 🗂️ Подключённых чатов пока нет.
        [one] 🗂️ Под вашим управлением: <b>{$count} чат</b>
        [few] 🗂️ Под вашим управлением: <b>{$count} чата</b>
       *[other] 🗂️ Под вашим управлением: <b>{$count} чатов</b>
    }
dm-profile-roles = 👑 Владелец: <b>{$owners}</b> · 🛡️ Администратор: <b>{$admins}</b>
dm-profile-subscriptions = 🆓 Free: <b>{$free}</b> · 💎 Платные: <b>{$paid}</b>
dm-profile-plan-count = {$plan}: {$count}
dm-profile-plans = 💳 Тарифы: {$plans}
dm-profile-members = 👥 Участников в известных чатах: <b>{$count}</b>
dm-profile-members-unknown = 👥 Число участников обновится после синхронизации чатов.
dm-profile-next-expiry = 📅 Ближайшее окончание тарифа: <b>{$until}</b>
dm-profile-no-expiry = ♾️ Активных тарифов с датой окончания нет.
dm-profile-preview-title = 📌 <b>Быстрый обзор</b>
dm-profile-chat-preview = ▫️ {$chat} · {$plan}
dm-profile-more = ➕ Ещё {$count ->
        [one] {$count} чат
        [few] {$count} чата
       *[other] {$count} чатов
    }. Полный список — /chats
dm-chat-untitled = Без названия
dm-chats-header = {$count ->
        [one] 💬 <b>Мой чат</b>
       *[other] 💬 <b>Мои чаты · {$count}</b>
    }
dm-chats-page = 📄 Страница <b>{$page}</b> из <b>{$pages}</b>
dm-chats-row = {$status} <b>{$chat}</b> · {$role}
dm-chats-row-meta = 💎 {$plan} · {$members} · 🔗 {$username}
dm-chats-row-free = ♾️ Бесплатный тариф без срока действия
dm-chats-row-open-ended = ♾️ Тариф активен без указанной даты окончания
dm-chats-row-until = 📅 Активен до <b>{$until}</b>
dm-chats-empty = 🚀 Чатов пока нет. Добавьте бота в группу, выдайте права администратора и отправьте первое сообщение — после этого чат появится здесь.
dm-chat-role-owner = 👑 владелец
dm-chat-role-admin = 🛡️ администратор
dm-chat-private = приватный чат
dm-chat-members = 👥 {$count}
dm-chat-members-unknown = 👥 нет данных
dm-chats-button = 💬 Мои чаты
dm-profile-button = 👤 Профиль
dm-page-prev-button = ⬅️ Назад
dm-page-next-button = ➡️ Дальше

## Личные сообщения — тарифы и оплата
dm-plans-header = 💎 <b>Тарифы</b>
dm-plans-intro = 🧭 Каждый тариф подключается к отдельному чату. Более высокий уровень включает возможности предыдущих.
dm-plans-row-free = {$icon} <b>{$plan}</b> · бесплатно навсегда
dm-plans-row = {$icon} <b>{$plan}</b> · {$stars} Stars или ${$usd} в месяц
dm-plans-features = 🧩 Возможности: {$features}
dm-plans-limits = 📏 Лимиты: {$limits}
dm-feature-moderation = предупреждения, муты и баны
dm-feature-captcha = капча для новичков
dm-feature-greeting = приветствие
dm-feature-stop-words = стоп-слова
dm-feature-anti-flood = антифлуд
dm-feature-log-channel = журнал модерации
dm-feature-anti-raid = антирейд
dm-feature-stats = статистика и отчёты
dm-feature-triggers = триггеры
dm-feature-autopost = автопостинг
dm-feature-reputation = репутация
dm-feature-levels = уровни
dm-feature-forced-subscription = обязательная подписка
dm-feature-ai-moderation = AI-модерация
dm-feature-crossban = сеть кросс-банов
dm-feature-chat-networks = сети чатов
dm-feature-priority-support = приоритетная поддержка
dm-feature-white-label = собственный бренд
dm-limit-stop-words = стоп-слова {$count}
dm-limit-triggers = триггеры {$count}
dm-limit-posts = посты {$count}
dm-limit-ai = AI-проверки/день {$count}
dm-limit-stats = история статистики {$count} дн.
dm-plans-hint = 💳 Платный тариф покупается для выбранного чата на срок от 1 до {$months} месяцев. Оплата — Telegram Stars.
dm-plans-button = 💳 {$plan} · {$stars} Stars/мес
dm-plans-button-short = 💎 Тарифы
dm-buy-choose-chat = 💬 Для какого чата подключаем {$plan}?
dm-buy-choose-term = 📅 <b>{$chat}</b> → {$plan}. Выберите срок подписки.
dm-buy-no-chats = 🚀 Тариф подключается к чату, а у вас их пока нет. Добавьте бота в группу администратором и возвращайтесь.
dm-buy-unknown-chat = ⚠️ Этот чат больше недоступен. Откройте /chats и начните заново.
dm-buy-invoice = 🧾 <b>{$chat}</b> → {$plan}, {$months ->
        [one] {$months} месяц
        [few] {$months} месяца
       *[other] {$months} месяцев
    }. Счёт готов — оплатите его кнопкой ниже.
dm-buy-pay = ⭐ Оплатить {$stars} Stars
dm-term-button = 📅 {$months ->
        [one] {$months} месяц
        [few] {$months} месяца
       *[other] {$months} месяцев
    } — {$stars} Stars

## Личные сообщения — навигация и разделы
# Подписи кнопок — обычный текст, не HTML: Telegram рисует их как есть, поэтому
# {$chat} и {$period} здесь не экранируются и не размечаются.
dm-menu = 🏠 <b>Главное меню</b>

    👤 Профиль и сводная информация об аккаунте.
    💬 Подключённые чаты и отчёты по каждому.
    📊 Статистика за сутки, неделю, месяц или квартал.
    💎 Тарифы, возможности и оплата.
    📖 Подробный справочник по всем функциям.
dm-home-button = 🏠 В меню
dm-back-button = ↩️ Назад
dm-stats-button = 📊 Статистика
dm-guide-button = 📖 Справочник
dm-guide-contents-button = 📖 К оглавлению
dm-chat-report-button = 📊 {$chat}
dm-chats-setup-button = 🚀 Как подключить чат
dm-chat-unavailable = ⚠️ Этот чат больше недоступен. Откройте список чатов и начните заново.
dm-stats-period-current = ✅ {$period}

## Личные сообщения — постоянная кнопка команд
dm-commands-reply-button = 📋 Команды
dm-commands-placeholder = Сообщение или команда
dm-commands-keyboard-ready = 📌 Кнопка «📋 Команды» закреплена под полем ввода.

    💡 Она в любой момент откроет актуальный список команд бота.
dm-commands-header = 📋 <b>Команды бота</b>
dm-commands-intro = 💡 Используйте команды в личке или в группе. Параметры после команды можно посмотреть в подробном справочнике.
dm-commands-dm-title = 👤 <b>В личных сообщениях</b>
dm-command-row-private = 👤 <code>{$command}</code> — {$description}
dm-command-row-public = 🌍 <code>{$command}</code> — {$description}
dm-command-row-admin = 🔐 <code>{$command}</code> — {$description}
dm-commands-note = 🧭 Обозначения: 🔐 администраторы · 🌍 все участники · 👤 личные сообщения.

## Личный веб-кабинет
dm-website-issued = 🌐 <b>Личный веб-кабинет готов</b>

    🔐 Ссылка одноразовая и действует {$minutes} мин.
    📊 В кабинете доступны общая статистика, динамика, чаты, тарифы и профиль.
    🔑 Ключ для ручного входа: {$token}
    🛡️ После входа ключ исчезнет из адресной строки и не сможет быть использован повторно.
dm-website-open-button = 🌐 Открыть веб-кабинет
dm-website-copy-button = 📋 Скопировать ключ
dm-website-unavailable = ⚠️ Веб-кабинет пока не настроен. Администратору нужно указать WEBSITE_URL.
