# Personal moderation statistics in the private chat (`core.dm_stats`).
#
# A catalogue of its own rather than part of `main.ftl`: that file holds the
# report the bot posts in a group for /stats, this one holds the digest an admin
# reads in their own DM across every chat they run. Keys are prefixed `report-`
# because `stats-` already belongs to the group report, and the bundle is flat —
# the same name in two catalogues silently ships one of the two wordings.
#
# Parse mode is HTML: the `<b>` tags here are deliberate, and any `<` or `>` in a
# substituted value is escaped by the caller.

## --- report windows ---
report-period-1d = Day
report-period-7d = Week
report-period-30d = Month
report-period-90d = Quarter

## --- one chat ---
report-chat-title = 📊 <b>{ $chat }</b> · { $period }
report-messages = 💬 Messages: <b>{ $count }</b>
report-active = 👥 Active members: <b>{ $count }</b>
report-flow = 📈 Joined: <b>{ $joins }</b> · left: <b>{ $leaves }</b> · net: <b>{ $growth }</b>
report-chart = 📉 Activity: { $chart }
# An ISO date: `08.11` and `11.08` are the same day to two different readers, and
# this line exists to be quoted back at people.
report-peak = 📅 Busiest day: <b>{ $date }</b> · { $count }
report-chart-moderation = 🛡 Moderation by day: { $chart }
report-empty = Nothing yet — numbers appear as soon as the chat comes to life.

## --- moderation ---
# No ├ or └ in the copy: the renderer draws them, because a counter that has no
# value yet drops out of the list and a branch baked into the string would dangle.
report-moderation-title = 🛡 <b>Moderation</b>
report-moderation-actions = Actions total: <b>{ $count }</b>
report-moderation-warns = Warnings issued: <b>{ $count }</b>
report-moderation-punishments = Mutes and bans: <b>{ $count }</b>
report-moderation-mine = Yours among them: <b>{ $count }</b>
report-moderation-automated = Handled by the bot: <b>{ $count }</b>
report-moderation-moderators = { $count ->
        [0] No human stepped in — the bot handled all of it
        [one] <b>{ $count }</b> moderator at work
       *[other] <b>{ $count }</b> moderators at work
    }
# `delta` arrives as text with its sign: as a number Fluent would group it for the
# locale and the leading `+` would be lost.
report-moderation-trend = 📐 Previous period: <b>{ $previous }</b> ({ $delta })

## --- what the actions were ---
# Plural nouns: these label numbers, they are not the event titles the log channel
# prints (those live in main.ftl under the `log-action-` prefix).
report-breakdown-title = 🧾 <b>What it was</b>
report-breakdown-row = • { $label } — <b>{ $count }</b>
report-action-warn = Warnings
report-action-unwarn = Warnings lifted
report-action-mute = Mutes
report-action-unmute = Mutes lifted
report-action-ban = Bans
report-action-unban = Bans lifted
report-action-kick = Kicks
report-action-delete = Messages deleted
report-action-alert = Alerts to admins
report-action-flagged = Logged without a penalty
report-action-auto-lift = Restrictions that ran out
report-action-other = Other

## --- top members ---
report-top-title = 🏆 <b>Most active</b>
report-top-row = { $place }. { $user } — { $messages }

## --- digest across every chat ---
report-overall-title = 📊 <b>Your digest</b> · { $period }
report-overall-chats = 🗂 Chats you run: <b>{ $count }</b>
report-overall-row = • { $chat } — 💬 { $messages } · 🛡 { $actions }
report-overall-none = You do not administer any chat with this bot yet.

## --- paid block ---
# Activity analytics is a Pro feature. Moderation counters stay visible on every
# plan: that is a log of the admin's own actions, not analytics.
report-locked-title = 🔒 <b>Activity analytics — Pro</b>
report-locked-hint = Charts, the top-members board and growth come with the Pro plan. The moderation counters below are always available.
