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
log-action-lockdown-off = Chat reopened to new members
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
