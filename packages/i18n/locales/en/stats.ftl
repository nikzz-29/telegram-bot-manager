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
report-empty = Nothing yet — numbers appear as soon as the chat comes to life.

## --- moderation ---
# No ├ or └ in the copy: the renderer draws them, because a counter that has no
# value yet drops out of the list and a branch baked into the string would dangle.
report-moderation-title = 🛡 <b>Moderation</b>
report-moderation-actions = Actions total: <b>{ $count }</b>
report-moderation-warns = Warnings issued: <b>{ $count }</b>
report-moderation-punishments = Mutes and bans: <b>{ $count }</b>
report-moderation-mine = Yours among them: <b>{ $count }</b>

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
