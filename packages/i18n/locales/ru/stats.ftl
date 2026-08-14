# Личная статистика в личных сообщениях (`core.dm_stats`).
#
# Отдельный каталог, а не часть `main.ftl`: там живут отчёты, которые бот
# отправляет в группу командой /stats, здесь — сводка, которую администратор
# читает у себя в личке про все свои чаты сразу. Ключи с префиксом `report-`,
# потому что `stats-` уже занят групповым отчётом, а плоский бандл не различает
# файлы — одинаковое имя в двух каталогах молча оставит одну из двух формулировок.
#
# Парс-мод HTML: `<b>` здесь намеренны, а любые `<` и `>` в подставляемых
# значениях экранирует вызывающая сторона.

## --- окна отчёта ---
report-period-1d = 🕐 Сутки
report-period-7d = 📅 Неделя
report-period-30d = 📆 Месяц
report-period-90d = 🗓 Квартал

## --- отчёт по одному чату ---
report-chat-title = 📊 <b>{ $chat }</b> · { $period }
report-messages = 💬 Сообщений: <b>{ $count }</b>
report-active = 👥 Активных участников: <b>{ $count }</b>
report-flow = 📈 Пришло: <b>{ $joins }</b> · ушло: <b>{ $leaves }</b> · итог: <b>{ $growth }</b>
report-chart = 📉 Активность: { $chart }
# Дата в ISO: `08.11` и `11.08` — один и тот же день для разных читателей, а эту
# строку цитируют в переписке.
report-peak = 📅 Пик активности: <b>{ $date }</b> · { $count }
report-chart-moderation = 🛡 Модерация по дням: { $chart }
report-empty = 🌱 Пока пусто — данные появятся, как только в чате начнётся жизнь.

## --- модерация ---
# Без ├ и └ в тексте: рисует их рендерер, потому что счётчик, который ещё не
# посчитан, из списка выпадает — а зашитая в строку ветка осталась бы висеть.
report-moderation-title = 🛡 <b>Модерация</b>
report-moderation-actions = 📋 Всего действий: <b>{ $count }</b>
report-moderation-warns = ⚠️ Предупреждений выдано: <b>{ $count }</b>
report-moderation-punishments = 🔨 Мутов и банов: <b>{ $count }</b>
report-moderation-mine = 👤 Из них ваших: <b>{ $count }</b>
report-moderation-automated = 🤖 Автоматически ботом: <b>{ $count }</b>
report-moderation-moderators = { $count ->
        [0] 👥 Люди не вмешивались — всё сделал бот
        [one] 👥 Работал <b>{ $count }</b> модератор
        [few] 👥 Работали <b>{ $count }</b> модератора
       *[other] 👥 Работали <b>{ $count }</b> модераторов
    }
# `delta` приходит строкой со знаком: число Fluent отформатировал бы по локали и
# «+» из него пропал бы.
report-moderation-trend = 📐 Прошлый период: <b>{ $previous }</b> ({ $delta })

## --- из чего сложились действия ---
# Названия действий во множественном числе: это подписи к числам, а не заголовки
# событий в журнале (те живут в main.ftl под префиксом `log-action-`).
report-breakdown-title = 🧾 <b>Из чего сложилось</b>
report-breakdown-row = ▫️ { $label } — <b>{ $count }</b>
report-action-warn = Предупреждения
report-action-unwarn = Снятые предупреждения
report-action-mute = Муты
report-action-unmute = Снятые муты
report-action-ban = Баны
report-action-unban = Разбаны
report-action-kick = Исключения
report-action-delete = Удалённые сообщения
report-action-alert = Сигналы администраторам
report-action-flagged = Зафиксировано без наказания
report-action-auto-lift = Ограничения, снятые по сроку
report-action-other = Прочее

## --- топ участников ---
report-top-title = 🏆 <b>Самые активные</b>
report-top-row = 🏅 { $place }. { $user } — { $messages }

## --- сводка по всем чатам ---
report-overall-title = 📊 <b>Ваша сводка</b> · { $period }
report-overall-chats = 🗂 Чатов под управлением: <b>{ $count }</b>
report-overall-row = • { $chat } — 💬 { $messages } · 🛡 { $actions }
report-overall-none = 🗂 Вы пока не администрируете ни одного чата с этим ботом.

## --- платный блок ---
# Аналитика активности — функция тарифа Pro. Счётчики модерации показываем всем:
# это журнал собственных действий администратора, а не аналитика.
report-locked-title = 🔒 <b>Аналитика активности — Pro</b>
report-locked-hint = 💡 Графики, топ участников и динамика приходят вместе с тарифом Pro. Счётчики модерации ниже доступны всегда.
