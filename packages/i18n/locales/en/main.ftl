# English locale — the fallback chain's last stop, so it must stay complete.
# Keys must match ru/main.ftl exactly.
#
# Convention: {$user} is an already-built HTML mention (see bot.facts.mention) and
# must not be escaped again. Every other placeholder is plain text.

## Private chat
start-welcome = Hi! I help run Telegram chats: moderation, captcha, statistics and autoposting. Add me to a chat as an administrator, then open the control panel.
help-text = Add me to your chat and grant administrator rights, then open the control panel — every setting lives there. In the chat you can use the moderation commands: /warn, /mute, /ban, /kick, /del, /ro.
open-miniapp = Open control panel
menu-button = Panel

## Warnings
warn-issued = {$user} received a warning: {$count}/{$limit}.
warn-punishment-ban = Warn limit reached — the member has been banned.
warn-punishment-mute = Warn limit reached — the member has been muted for {$duration}.
warn-punishment-mute-forever = Warn limit reached — the member has been muted indefinitely.
unwarn-done = A warning was removed from {$user}. Remaining: {$count}.
warns-own = Your warnings: {$count}/{$limit}.
warns-other = Warnings for {$user}: {$count}/{$limit}.

## Moderation — command replies
moderation-forbidden = This command is available to chat administrators only.
moderation-reply-required = Reply to a member's message with this command.
mute-success = {$user} has been muted for {$duration}.
unmute-success = {$user} can post again.
ban-success = {$user} has been banned for {$duration}.
ban-success-forever = {$user} has been banned indefinitely.
unban-success = {$user} has been unbanned.
kick-success = {$user} has been removed from the chat.
read-only-on = The chat is now read-only.
read-only-on-timed = The chat is now read-only for {$duration}.
read-only-off = Read-only mode is off, posting is open again.
read-only-usage = Usage: /ro on, /ro off or /ro 30m.

## Automatic notices
notice-filter = A message from {$user} was removed: disallowed content ({$filter}).
notice-stop-word = A message from {$user} was removed: stop-word.
notice-flood = {$user}, that is too many messages in a row.
notice-warned = Warning: {$count}/{$limit}.
notice-muted = Posting restricted for {$duration}.
notice-muted-forever = Posting restricted indefinitely.
notice-banned = The member has been banned.

## Module gate
module-locked = This section is available on the {$plan} plan.
module-locked-command = Command unavailable: the "{$module}" section requires the {$plan} plan.

## Log channel
log-action-warn = Warning
log-action-unwarn = Warning removed
log-action-mute = Mute
log-action-unmute = Unmute
log-action-ban = Ban
log-action-unban = Unban
log-action-kick = Kick
log-action-delete = Message deleted
log-action-auto-delete = Auto-delete
log-action-stop-word = Stop-word
log-action-content-filter = Content filter
log-action-anti-flood = Anti-flood
log-action-read-only = Read-only mode
log-action-alert-admins = Admins alerted
log-action-captcha-passed = Captcha solved
log-action-captcha-failed = Captcha failed
log-action-captcha-timeout = Captcha timed out
log-action-autoban = Auto-ban on entry
log-action-raid = Raid
log-action-lockdown = Chat closed to new members
log-action-lockdown-off = Chat reopened
log-action-forced-subscription = Message without subscription
log-action-trigger = Trigger fired
log-action-autopost = Scheduled post to new members
log-field-target = Member: {$value}
log-field-moderator = Moderator: {$value}
log-field-duration = Duration: {$value}
log-field-reason = Reason: {$value}
log-field-note = Details: {$value}
log-field-when = Time: {$value}

## Chat entry — captcha
captcha-greeting = {$user}, welcome! Please confirm you are not a bot — you have {$timeout}.
captcha-prompt-button = Tap the button below.
captcha-prompt-emoji = Tap this emoji: {$emoji}
captcha-prompt-math = What is {$left} + {$right}?
captcha-button-confirm = I am not a bot
captcha-solved = Done, welcome aboard!
captcha-wrong = Wrong. Attempts left: {$remaining}.
captcha-failed = No attempts left.
captcha-failed-attempts = wrong answers: {$attempts}
captcha-expired = This check is already over.
captcha-not-yours = This check is not for you.

## Chat entry — new-account auto-ban
entry-autoban = {$user} did not pass the entry check: {$reason}.
entry-reason-no-username = no username
entry-reason-no-photo = no profile photo
entry-reason-fresh-account = account is too new

## Chat entry — anti-raid
raid-detected = Raid detected: {$joins} joins in {$seconds}s. New members are read-only for {$duration}.
raid-log-note = joins: {$joins} in {$seconds}s
lockdown-on = The chat is closed to new members for {$duration}.
lockdown-off = The chat is open to new members again.
lockdown-over = The restriction on new members has been lifted.

## Chat entry — forced subscription
forced-sub-required = {$user}, please subscribe to the channel before posting here.
forced-sub-join-button = Subscribe
forced-sub-check-button = I subscribed
forced-sub-open = Open this message in the chat.
forced-sub-still-missing = No subscription found. Join the channel, then tap the button again.
forced-sub-thanks = Thanks, you can post now!

## Statistics
stats-title = 📊 <b>{$chat}</b> — last {$days} days
stats-messages = Messages: {$count}
stats-active = Active members: {$count}
stats-joins = Joined: {$count}
stats-leaves = Left: {$count}
stats-growth = Net growth: {$count}
stats-chart = Activity: {$chart}
stats-top-title = <b>Most active</b>
stats-top-row = {$place}. {$user} — {$messages}
stats-empty = No data yet — statistics appear after the module's first hour.

## Reputation and levels
rep-granted = {$user}: +{$points} reputation.
rep-standing = <b>{$user}</b> — reputation: {$points}
rep-level = Level: {$level}
rep-level-titled = Level: {$level} — {$title}
rep-progress = To the next level: {$earned}/{$needed}
rep-rank = Rank: {$place}
rep-top-title = <b>Top by reputation</b>
rep-top-title-level = <b>Top by level</b>
rep-top-row = {$place}. {$user} — {$points}
rep-top-row-level = {$place}. {$user} — level {$level}, reputation {$points}
rep-top-empty = Nobody has earned reputation yet.
level-up = 🎉 {$user} reached level {$level}!
level-up-titled = 🎉 {$user} reached level {$level} — {$title}!

## Triggers
trigger-list-title = <b>Triggers</b> — {$count}/{$limit}
trigger-list-row = #{$id} · {$pattern} · {$match} · hits: {$hits} · {$state}
trigger-list-more = …and {$count} more. The full list is in the control panel.
trigger-list-empty = No triggers yet.
trigger-usage = Usage: /addtrigger phrase {$separator} reply. Prefix re: for a regular expression, prefix = for an exact match.
trigger-added = Trigger #{$id} added: {$pattern}
trigger-deleted = Trigger #{$id} deleted.
trigger-delete-usage = Usage: /deltrigger 12 — the number comes from /triggers.
trigger-not-found = Trigger #{$id} not found.

## Autoposting
post-list-title = <b>Scheduled posts</b> — {$count}/{$limit}
post-list-row = #{$id} · {$title} · {$schedule} · {$next}
post-list-more = …and {$count} more. The full list is in the control panel.
post-list-empty = No scheduled posts — create the first one in the control panel.
post-module-paused = The autoposting module is off; nothing is being sent.
post-paused = paused
post-expired = will not repeat
post-not-found = Post #{$id} not found.
post-toggle-usage = Usage: /postpause 12 or /postresume 12 — the number comes from /posts.
post-paused-ok = Post #{$id} is paused.
post-resumed = Post #{$id} is back on schedule.

## Shared
state-on = on
state-off = off
limit-triggers = Trigger limit reached: {$limit}. Delete some or move to a higher plan.

## Errors
error-generic = The action could not be completed. Please try again later.
error-invalid-duration = Invalid duration. Use the format 30m, 2h, 7d or 1w.
error-invalid-config = These settings failed validation.
error-warn-not-found = The member has no active warnings.
error-chat-not-found = Chat not found.
error-not-admin = Chat administrator rights are required.
error-feature-locked = This feature requires a higher plan.
error-limit-exceeded = You have reached your plan's limit.
error-invalid-init-data = Telegram data could not be verified. Please reopen the panel.
error-invalid-session = Your session has expired. Please reopen the panel.
error-invalid-timezone = Unknown timezone. Example: Europe/Moscow.
error-invalid-request = The request failed validation.
error-not-found = Not found.
error-server = Internal server error.
error-invalid-pattern = Invalid regular expression.
error-invalid-schedule = Invalid schedule.
error-target-not-found = I could not identify that member. Reply to their message or use @username — I only know people who have posted in this chat.
error-self-action = This action cannot be applied to yourself or to the bot.
error-provider-unavailable = The payment provider is unavailable. Please try again later.
error-payment = The payment did not go through.

## Command descriptions for the Telegram menu (keys come from core.registry)
cmd-warn = issue a warning
cmd-unwarn = remove a warning
cmd-warns = show warnings
cmd-mute = restrict a member from posting
cmd-unmute = lift a restriction
cmd-ban = ban a member
cmd-unban = unban a member
cmd-kick = remove a member
cmd-del = delete a message
cmd-ro = read-only mode
cmd-lockdown = close the chat to new members
cmd-stats = chat statistics
cmd-addtrigger = add a trigger
cmd-deltrigger = delete a trigger
cmd-triggers = list triggers
cmd-rep = member reputation
cmd-top = top members
cmd-posts = scheduled posts
cmd-postpause = pause a scheduled post
cmd-postresume = put a post back on schedule
cmd-gban = global ban

## Modules — titles and descriptions for the Mini App
module-moderation-title = Moderation
module-moderation-description = Warnings, mutes, bans, stop-words and anti-flood.
module-entry-title = Chat entry
module-entry-description = Captcha, greeting and raid protection.
module-stats-title = Statistics
module-stats-description = Chat activity, top members and daily reports.
module-engagement-title = Engagement
module-engagement-description = Triggers, reputation and member levels.
module-autopost-title = Autoposting
module-autopost-description = Scheduled and recurring posts.
module-ai-title = AI moderation
module-ai-description = Spam and toxicity detection powered by an AI model.
module-crossban-title = Cross-ban
module-crossban-description = A shared blocklist of offenders across all your chats.

## Mini App sections
section-moderation = Moderation
section-entry = Entry
section-stats = Statistics
section-engagement = Engagement
section-autopost = Autoposting
section-ai = AI
section-crossban = Cross-ban

api-status = API is healthy

## Plans and payments
plan-free = Free
plan-pro = Pro
plan-business = Business
plan-white_label = White Label

billing-invoice-title = {$plan} subscription
billing-invoice-description = {$plan} plan for this chat, {$months ->
        [one] {$months} month
       *[other] {$months} months
    }.
billing-payment-received = Payment received. {$plan} is active until {$until}.
billing-payment-replayed = This payment was already credited — nothing changed.

billing-reminder-title = Your subscription ends soon
billing-reminder-body = The {$plan} plan for "{$chat}" ends on {$until}, in {$days ->
        [one] {$days} day
       *[other] {$days} days
    }. Renew it to keep the paid modules running.
billing-reminder-button = Renew subscription

billing-grace-title = Subscription ended
billing-grace-body = The {$plan} plan for "{$chat}" has ended. Paid modules keep working for {$days ->
        [one] {$days} more day
       *[other] {$days} more days
    }, until {$until}. After that the chat moves to Free.
billing-downgraded-title = Chat moved to Free
billing-downgraded-body = The subscription for "{$chat}" was not renewed, so the paid modules are off. Your settings are kept and come back the moment you pay.
