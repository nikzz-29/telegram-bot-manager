# Русская локаль. Ключи должны совпадать один-в-один с en/main.ftl.
#
# Соглашение: {$user} — уже готовая HTML-ссылка на участника (см. bot.facts.mention),
# поэтому её нельзя экранировать повторно. Остальные подстановки — простой текст.
#
# Здесь — то, что бот говорит в группах, плюс общие словари (тарифы, ошибки,
# названия модулей). Диалог в личке живёт в dm.ftl, справка — в guide.ftl,
# мини-апп — в panel.ftl. Один ключ не может быть определён в двух файлах:
# и бот, и панель сливают их в один бандл (см. tests/test_i18n.py).

## Предупреждения
warn-issued = ⚠️ {$user} получил предупреждение: {$count}/{$limit}.
warn-punishment-ban = 🚫 Лимит исчерпан — участник заблокирован.
warn-punishment-mute = 🔇 Лимит исчерпан — участник замьючен на {$duration}.
warn-punishment-mute-forever = 🔇 Лимит исчерпан — участник замьючен бессрочно.
unwarn-done = ✅ С {$user} снято предупреждение. Осталось: {$count}.
warns-own = Ваши предупреждения: {$count}/{$limit}.
warns-other = Предупреждения {$user}: {$count}/{$limit}.

## Модерация — ответы на команды
moderation-forbidden = ⛔ Эта команда доступна только администраторам чата.
moderation-reply-required = Ответьте этой командой на сообщение участника.
mute-success = 🔇 {$user} замьючен на {$duration}.
unmute-success = 🔊 С {$user} снято ограничение на отправку сообщений.
ban-success = 🚫 {$user} заблокирован на {$duration}.
ban-success-forever = 🚫 {$user} заблокирован бессрочно.
unban-success = ✅ {$user} разблокирован.
kick-success = 👋 {$user} исключён из чата.
read-only-on = 🔒 Чат переведён в режим «только чтение».
read-only-on-timed = 🔒 Чат переведён в режим «только чтение» на {$duration}.
read-only-off = 🔓 Режим «только чтение» выключен, можно писать.
read-only-usage = Использование: /ro on, /ro off или /ro 30m.

## Автоматические уведомления в чат
notice-filter = 🗑 Сообщение {$user} удалено: запрещённый контент ({$filter}).
notice-stop-word = 🗑 Сообщение {$user} удалено: стоп-слово.
notice-flood = 🌊 {$user}, слишком много сообщений подряд.
notice-warned = ⚠️ Предупреждение: {$count}/{$limit}.
notice-muted = 🔇 Ограничение на отправку сообщений: {$duration}.
notice-muted-forever = 🔇 Ограничение на отправку сообщений: бессрочно.
notice-banned = 🚫 Участник заблокирован.
notice-ai-toxic = 🤖 Сообщение {$user} удалено: оскорбления.
notice-ai-hidden-ad = 🤖 Сообщение {$user} удалено: скрытая реклама.
notice-ai-scam = 🤖 Сообщение {$user} удалено: похоже на мошенничество.

## Гейт модулей
module-locked = 🔒 Этот раздел доступен на тарифе {$plan}.
module-locked-command = 🔒 Команда недоступна: раздел «{$module}» требует тариф {$plan}.

## Лог-канал
log-action-warn = Предупреждение
log-action-unwarn = Снятие предупреждения
log-action-mute = Мут
log-action-unmute = Снятие мута
log-action-ban = Блокировка
log-action-unban = Разблокировка
log-action-kick = Исключение
log-action-delete = Удаление сообщения
log-action-auto-delete = Автоудаление
log-action-stop-word = Стоп-слово
log-action-content-filter = Контент-фильтр
log-action-anti-flood = Антифлуд
log-action-read-only = Режим «только чтение»
log-action-alert-admins = Оповещение администраторов
log-action-captcha-passed = Капча пройдена
log-action-captcha-failed = Капча не пройдена
log-action-captcha-timeout = Капча просрочена
log-action-autoban = Автобан на входе
log-action-raid = Рейд
log-action-lockdown = Чат закрыт для новых
log-action-lockdown-off = Чат открыт для новых
log-action-forced-subscription = Сообщение без подписки
log-action-trigger = Сработал триггер
log-action-autopost = Публикация по расписанию
log-action-ai-moderation = ИИ-модерация
log-action-ai-alert = ИИ: подозрительное сообщение
log-action-crossban = Сетевой бан
log-action-crossban-alert = Сеть: участник в чёрном списке
log-action-global-ban = Глобальная блокировка
log-action-global-unban = Глобальная разблокировка
log-field-target = Участник: {$value}
log-field-moderator = Модератор: {$value}
log-field-duration = Срок: {$value}
log-field-reason = Причина: {$value}
log-field-note = Детали: {$value}
log-field-when = Время: {$value}

## Вход в чат — капча
captcha-greeting = 👋 {$user}, добро пожаловать! Подтвердите, что вы не бот — у вас есть {$timeout}.
captcha-prompt-button = Нажмите кнопку ниже.
captcha-prompt-emoji = Нажмите на эмодзи: {$emoji}
captcha-prompt-math = Сколько будет {$left} + {$right}?
captcha-button-confirm = ✅ Я не бот
captcha-solved = ✅ Готово, добро пожаловать!
captcha-wrong = Неверно. Осталось попыток: {$remaining}.
captcha-failed = Попытки закончились.
captcha-failed-attempts = неверных ответов: {$attempts}
captcha-expired = Проверка уже завершена.
captcha-not-yours = Эта проверка не для вас.

## Вход в чат — автобан свежерегов
entry-autoban = 🛡 {$user} не прошёл проверку при входе: {$reason}.
entry-reason-no-username = нет username
entry-reason-no-photo = нет аватара
entry-reason-fresh-account = слишком новый аккаунт

## Вход в чат — анти-рейд
raid-detected = 🚨 Обнаружен рейд: {$joins} входов за {$seconds} с. Новые участники переведены в режим только чтения на {$duration}.
raid-log-note = входов: {$joins} за {$seconds} с
lockdown-on = 🔒 Чат закрыт для новых участников на {$duration}.
lockdown-off = 🔓 Чат снова открыт для новых участников.
lockdown-over = 🔓 Ограничение для новых участников снято.

## Вход в чат — обязательная подписка
forced-sub-required = 🔔 {$user}, чтобы писать в этом чате, подпишитесь на канал.
forced-sub-join-button = 🔔 Подписаться
forced-sub-check-button = ✅ Я подписался
forced-sub-open = Откройте это сообщение в чате.
forced-sub-still-missing = Подписка не найдена. Подпишитесь на канал и нажмите кнопку ещё раз.
forced-sub-thanks = ✅ Спасибо, можно писать!

## Статистика
stats-title = 📊 <b>{$chat}</b> — за {$days} дн.
stats-messages = Сообщений: {$count}
stats-active = Активных участников: {$count}
stats-joins = Пришли: {$count}
stats-leaves = Ушли: {$count}
stats-growth = Прирост: {$count}
stats-chart = Активность: {$chart}
stats-top-title = <b>Самые активные</b>
stats-top-row = {$place}. {$user} — {$messages}
stats-empty = Данных пока нет — статистика появится после первого часа работы модуля.

## Репутация и уровни
rep-granted = ✨ {$user}: +{$points} к репутации.
rep-standing = <b>{$user}</b> — репутация: {$points}
rep-level = Уровень: {$level}
rep-level-titled = Уровень: {$level} — {$title}
rep-progress = До следующего уровня: {$earned}/{$needed}
rep-rank = Место в топе: {$place}
rep-top-title = 🏆 <b>Топ по репутации</b>
rep-top-title-level = 🏆 <b>Топ по уровням</b>
rep-top-row = {$place}. {$user} — {$points}
rep-top-row-level = {$place}. {$user} — уровень {$level}, репутация {$points}
rep-top-empty = Репутацию пока никто не набрал.
level-up = 🎉 {$user} выходит на {$level} уровень!
level-up-titled = 🎉 {$user} выходит на {$level} уровень — {$title}!

## Триггеры
trigger-list-title = ⚡ <b>Триггеры</b> — {$count}/{$limit}
trigger-list-row = #{$id} · {$pattern} · {$match} · срабатываний: {$hits} · {$state}
trigger-list-more = …и ещё {$count}. Полный список — в панели управления.
trigger-list-empty = Триггеров пока нет.
trigger-usage = Использование: /addtrigger фраза {$separator} ответ. Префикс re: — регулярное выражение, префикс = — точное совпадение.
trigger-added = ✅ Триггер #{$id} добавлен: {$pattern}
trigger-deleted = 🗑 Триггер #{$id} удалён.
trigger-delete-usage = Использование: /deltrigger 12 — номер берётся из /triggers.
trigger-not-found = Триггер #{$id} не найден.

## Автопостинг
post-list-title = 🗓 <b>Публикации</b> — {$count}/{$limit}
post-list-row = #{$id} · {$title} · {$schedule} · {$next}
post-list-more = …и ещё {$count}. Полный список — в панели управления.
post-list-empty = Запланированных публикаций нет — создайте первую в панели управления.
post-module-paused = Модуль автопостинга выключен, публикации не отправляются.
post-paused = на паузе
post-expired = больше не повторится
post-not-found = Публикация #{$id} не найдена.
post-toggle-usage = Использование: /postpause 12 или /postresume 12 — номер берётся из /posts.
post-paused-ok = ⏸ Публикация #{$id} поставлена на паузу.
post-resumed = ▶️ Публикация #{$id} снова в расписании.

## Общее
state-on = вкл
state-off = выкл
limit-triggers = Достигнут лимит триггеров: {$limit}. Удалите ненужные или перейдите на более высокий тариф.

## Ошибки
error-generic = Не удалось выполнить действие. Попробуйте позже.
error-invalid-duration = Неверный срок. Используйте формат 30m, 2h, 7d или 1w.
error-invalid-config = Настройки не прошли проверку.
error-warn-not-found = У участника нет активных предупреждений.
error-chat-not-found = Чат не найден.
error-not-admin = Нужны права администратора чата.
error-feature-locked = Функция доступна на более высоком тарифе.
error-limit-exceeded = Достигнут лимит тарифа.
error-invalid-init-data = Не удалось подтвердить данные Telegram. Откройте панель заново.
error-invalid-session = Сессия истекла. Откройте панель заново.
error-invalid-timezone = Неизвестный часовой пояс. Пример: Europe/Moscow.
error-invalid-request = Запрос не прошёл проверку.
error-not-found = Не найдено.
error-server = Внутренняя ошибка сервера.
error-invalid-pattern = Неверное регулярное выражение.
error-invalid-schedule = Неверное расписание.
error-target-not-found = Не удалось определить участника. Ответьте на его сообщение или укажите @username — я знаю только тех, кто уже писал в чате.
error-self-action = Это действие нельзя применить к себе или к боту.
error-provider-unavailable = Платёжный провайдер недоступен. Попробуйте позже.
error-payment = Платёж не прошёл.

## Описания команд для меню Telegram
# Групповые команды берут ключ из core.registry; личные перечислены в
# bot.__main__.PRIVATE_COMMANDS — они не принадлежат ни одному модулю.
cmd-profile = ваш профиль
cmd-chats = ваши чаты и тарифы
cmd-plans = тарифы и оплата
cmd-help = что умеет бот
cmd-admin = панель управления (для операторов)
cmd-warn = выдать предупреждение
cmd-unwarn = снять предупреждение
cmd-warns = показать предупреждения
cmd-mute = ограничить отправку сообщений
cmd-unmute = снять ограничение
cmd-ban = заблокировать участника
cmd-unban = разблокировать участника
cmd-kick = исключить участника
cmd-del = удалить сообщение
cmd-ro = режим «только чтение»
cmd-lockdown = закрыть чат для новых участников
cmd-stats = статистика чата
cmd-addtrigger = добавить триггер
cmd-deltrigger = удалить триггер
cmd-triggers = список триггеров
cmd-rep = репутация участника
cmd-top = топ участников
cmd-posts = запланированные публикации
cmd-postpause = приостановить публикацию
cmd-postresume = вернуть публикацию в расписание
cmd-gban = глобальная блокировка

## Модули — заголовки и описания для Mini App
module-moderation-title = Модерация
module-moderation-description = Предупреждения, муты, баны, стоп-слова и антифлуд.
module-entry-title = Вход в чат
module-entry-description = Капча, приветствие и защита от рейдов.
module-stats-title = Статистика
module-stats-description = Активность чата, топ участников и ежедневные отчёты.
module-engagement-title = Вовлечение
module-engagement-description = Триггеры, репутация и уровни участников.
module-autopost-title = Автопостинг
module-autopost-description = Отложенные и регулярные публикации по расписанию.
module-ai-title = AI-модерация
module-ai-description = Распознавание спама и токсичности нейросетью.
module-crossban-title = Кросс-бан
module-crossban-description = Общий чёрный список нарушителей для всех ваших чатов.

## Разделы Mini App
section-moderation = Модерация
section-entry = Вход
section-stats = Статистика
section-engagement = Вовлечение
section-autopost = Автопостинг
section-ai = AI
section-crossban = Кросс-бан

api-status = API работает

## Тарифы и платежи
plan-free = Free
plan-pro = Pro
plan-business = Business
plan-white_label = White Label

billing-invoice-title = Подписка {$plan}
billing-invoice-description = Тариф {$plan} для этого чата на {$months ->
        [one] {$months} месяц
        [few] {$months} месяца
       *[other] {$months} месяцев
    }.
billing-payment-received = ✅ Платёж получен. Тариф {$plan} активен до {$until}.
billing-payment-replayed = Этот платёж уже был зачтён — подписка не изменилась.

billing-reminder-title = ⏳ Подписка скоро закончится
billing-reminder-body = Тариф {$plan} в чате «{$chat}» закончится {$until} — это через {$days ->
        [one] {$days} день
        [few] {$days} дня
       *[other] {$days} дней
    }. Продлите подписку, чтобы платные модули продолжили работать.
billing-reminder-button = 💳 Продлить подписку

billing-grace-title = ⚠️ Подписка закончилась
billing-grace-body = Тариф {$plan} в чате «{$chat}» закончился. Платные модули работают ещё {$days ->
        [one] {$days} день
        [few] {$days} дня
       *[other] {$days} дней
    } — до {$until}. После этого чат перейдёт на Free.
billing-downgraded-title = 📉 Чат переведён на Free
billing-downgraded-body = Подписка в чате «{$chat}» не была продлена, поэтому платные модули отключены. Настройки сохранены и вернутся сразу после оплаты.

## Кросс-бан — сетевой чёрный список
crossban-reason = чёрный список сети: {$chats ->
        [one] {$chats} чат
        [few] {$chats} чата
       *[other] {$chats} чатов
    }
crossban-banned = 🚫 {$user} заблокирован: участник в чёрном списке сети ({$chats ->
        [one] {$chats} чат
        [few] {$chats} чата
       *[other] {$chats} чатов
    }).
crossban-alert = ⚠️ Внимание: {$user} есть в чёрном списке сети ({$chats ->
        [one] {$chats} чат
        [few] {$chats} чата
       *[other] {$chats} чатов
    }). Решение за вами — включён режим оповещения.

## Кросс-бан — команды оператора
gban-forbidden = ⛔ Эта команда доступна только операторам платформы.
gban-usage = Использование: /gban <id или ответом на сообщение> причина
gban-reason-required = Укажите причину — она попадёт в сетевой чёрный список.
gban-done = ✅ {$user} добавлен в сетевой чёрный список. Причина: {$reason}
gban-already = {$user} уже в сетевом чёрном списке.
gban-ungban-usage = Использование: /ungban <id или ответом на сообщение>
gban-ungban-done = ✅ {$user} убран из сетевого чёрного списка.
gban-ungban-missing = Этого участника нет в сетевом чёрном списке.
gban-status-listed = {$user} в чёрном списке сети. Жалоб из чатов: {$chats}.
gban-status-clean = {$user} не в чёрном списке. Жалоб из чатов: {$chats}.
