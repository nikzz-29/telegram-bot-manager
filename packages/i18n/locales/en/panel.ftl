# Panel-only copy for the Mini App.
#
# Keys the bot already owns — plan names, module titles and descriptions, error
# messages the API returns by key — live in main.ftl and are reused from there.
# This file holds only what exists on screen and nowhere else.

## Shell
panel-loading = Loading…
panel-retry = Try again
panel-save = Save
panel-saving = Saving…
panel-cancel = Cancel
panel-delete = Delete
panel-edit = Edit
panel-confirm-delete = Delete this permanently?
# Buttons for the unsaved-changes popup. Not "Cancel" — it is ambiguous about
# what is being cancelled, the leaving or the edits themselves.
panel-discard = Your changes are not saved. Leaving loses them.
panel-discard-leave = Leave
panel-discard-stay = Stay
panel-language = Language
# Language names stay in their own language — a Russian speaker looking for the
# switch scans for "Русский", not for the English word for it.
locale-ru = Русский
locale-en = English
panel-outside-telegram = Open this panel from Telegram — it needs the launch data your client provides.
panel-auth-failed = Could not sign you in. Close the panel and open it again from the chat.

## Chat list
chats-title = Your chats
chats-empty = No chats yet. Add the bot to a group and make it an administrator, then reopen this panel.
chats-role-owner = Owner
chats-role-admin = Admin
chats-members = {$count ->
        [one] {$count} member
       *[other] {$count} members
    }
chats-inactive = Bot removed

## Chat screen
chat-sections = Sections
chat-tools = Tools
chat-language = Chat language
chat-timezone = Timezone
chat-timezone-hint = Used for scheduled posts and daily reports. Example: Europe/Moscow.
chat-sync-admins = Refresh admin list
chat-sync-admins-hint = Run this after promoting someone in Telegram.
chat-sync-done = Admin list updated
chat-general = General

## Modules
module-enabled = Enabled
# `module-locked` itself lives in main.ftl — the bot says the same sentence when
# a command is gated, and two texts for one situation is how they drift.
module-locked-cta = Upgrade to {$plan}
module-integration-unavailable = AI moderation is temporarily unavailable because its provider is not configured.
module-reset = Reset to defaults
module-reset-confirm = Reset every setting in this section to its default?
section-billing = Plan
section-platform = Platform

## Settings — generic field labels
field-unset = Not set
field-item-placeholder = New entry
field-seconds = seconds
field-minutes = minutes
field-hours = hours
field-days = days
field-characters = characters
field-messages-count = {$count ->
        [one] {$count} message
       *[other] {$count} messages
    }
field-invalid-number = Enter a number between {$min} and {$max}.
# List fields: the greeting's buttons, the level titles.
field-add = Add
field-remove = Remove
field-list-empty = Nothing added yet.
field-list-incomplete = Fill in every field of each entry — it cannot be saved otherwise.

## Settings — group headings
#
# The panel generates each module's form from the JSON Schema the API ships, and
# groups the fields by name prefix. These are the headings those groups get.
settings-group-general = General
settings-group-warn = Warnings
settings-group-stop-word = Stop words
settings-group-filter = Content filters
settings-group-anti-flood = Anti-flood
settings-group-captcha = Captcha
settings-group-greeting = Greeting
settings-group-autoban = New accounts
settings-group-anti-raid = Anti-raid
settings-group-forced-subscription = Required subscription
settings-group-reputation = Reputation
settings-group-levels = Levels
settings-group-track = Tracking
settings-group-report = Reports
# The two AI moderation fields are maps keyed by the model's verdict, so the
# panel draws one row per verdict. Each map gets its own heading: the rows are
# named the same in both, and without a heading there is nothing to say which
# one is the confidence and which one is the response.
settings-group-thresholds = Confidence needed
settings-group-actions = What to do when it clears

## Settings — enum choices
option-nothing = Do nothing
option-delete = Delete
option-delete-warn = Delete and warn
option-delete-mute = Delete and mute
option-alert-admins = Alert admins
option-mute = Mute
option-ban = Ban
option-kick = Kick
option-button = Button
option-emoji = Emoji
option-math = Arithmetic
option-captcha = Send to captcha

## Settings — field labels, one per schema property
setting-enabled = Enabled
setting-timezone = Timezone
setting-warn-limit = Warnings before punishment
setting-warn-punishment = Punishment at the limit
setting-warn-punishment-hours = Punishment length
setting-warn-lifetime-days = A warning expires after
setting-stop-words = Stop words
setting-stop-word-presets = Ready-made lists
setting-stop-word-action = On a stop word
setting-stop-word-mute-hours = Mute length
setting-filters-links = Links
setting-filters-mentions = @mentions
setting-filters-forwards = Forwarded messages
setting-filters-photos = Photos
setting-filters-videos = Videos
setting-filters-gifs = GIFs
setting-filters-stickers = Stickers
setting-filters-voices = Voice messages
setting-filters-video-notes = Video messages
setting-filters-documents = Files
setting-filters-channel-senders = Posting as a channel
setting-filter-action = On filtered content
setting-anti-flood-enabled = Anti-flood enabled
setting-anti-flood-messages = Messages allowed
setting-anti-flood-seconds = …within
setting-anti-flood-mute-minutes = Mute length
setting-anti-flood-media-messages = Media allowed
setting-anti-flood-media-seconds = …within
setting-log-channel-id = Log channel ID
setting-delete-service-messages = Delete join and leave notices
setting-exempt-admins = Admins are exempt
setting-captcha-enabled = Captcha on join
setting-captcha-kind = Captcha type
setting-captcha-timeout-minutes = Time to solve
setting-captcha-kick-on-timeout = Remove on timeout
setting-greeting-enabled = Greet new members
setting-greeting-text = Greeting
setting-greeting-media-file-id = Image file_id
setting-greeting-buttons = Buttons under the greeting
setting-greeting-buttons-text = Label
setting-greeting-buttons-url = Link
setting-greeting-buttons-url-hint = Starts with https:// or tg://
setting-greeting-delete-after-minutes = Delete the greeting after
setting-rules-link = Rules link
setting-autoban-new-accounts = Screen new accounts
setting-autoban-require-username = Require a username
setting-autoban-require-photo = Require a profile photo
setting-autoban-min-account-age-days = Minimum account age
setting-autoban-action = On a suspicious account
setting-anti-raid-enabled = Anti-raid enabled
setting-anti-raid-joins = Joins that trigger lockdown
setting-anti-raid-seconds = …within
setting-anti-raid-lockdown-minutes = Lockdown length
setting-forced-subscription-enabled = Require a channel subscription
setting-forced-subscription-channel-id = Channel ID
setting-forced-subscription-channel-url = Channel link
setting-track-messages = Count messages
setting-track-joins = Count joins and leaves
setting-daily-report-enabled = Daily report
setting-weekly-report-enabled = Weekly report
setting-report-hour-utc = Hour to send (UTC)
setting-reputation-enabled = Reputation enabled
setting-reputation-keywords = Thank-you words
setting-reputation-daily-limit = Points one member can give per day
setting-reputation-cooldown-seconds = Pause between points
setting-levels-enabled = Levels enabled
setting-points-per-message = Points per message
# Level/title pairs. The admin invents the keys, so this field labels both halves
# of a row and says what a key may be.
setting-level-titles = Level names
setting-level-titles-key = Level
setting-level-titles-value = Name
setting-level-titles-key-hint = The key is a level number, from 1 up.
setting-triggers-enabled = Triggers enabled
setting-sample-rate = Share of messages checked
setting-min-text-length = Minimum length to check
setting-test-admin-messages = Test: check administrator messages
# One row per verdict the model can return. The labels are the verdicts
# themselves; which map they belong to is what the group heading above says.
setting-thresholds-toxic = Toxic
setting-thresholds-hidden-ad = Hidden advertising
setting-thresholds-scam = Scam
setting-actions-toxic = Toxic
setting-actions-hidden-ad = Hidden advertising
setting-actions-scam = Scam
setting-alert-chat-id = Alert chat ID
setting-autoban-on-join = Ban listed users on join
setting-alert-only = Alert instead of banning
setting-contribute-bans = Report bans to the network

## Statistics
stats-screen-title = Statistics
stats-range = Period
stats-range-1 = Today
stats-range-7 = 7 days
stats-range-30 = 30 days
stats-range-90 = 90 days
stats-metric-messages = Messages
stats-metric-joins = Joined
stats-metric-leaves = Left
stats-active-users = Active members
stats-top-users = Most active
stats-no-data = No activity recorded for this period yet.
stats-retention-capped = Your plan keeps {$days ->
        [one] {$days} day
       *[other] {$days} days
    } of history.

## Global user dashboard
nav-label = Navigation
nav-dashboard = Overview
nav-stats = Statistics
nav-chats = My chats
nav-plans = Plans
nav-profile = Profile
nav-platform = Operator
chat-untitled = Untitled
dashboard-title = Overview
dashboard-greeting = Welcome, {$name}
dashboard-week-activity = Messages this week
dashboard-analytics-on = Analytics active
dashboard-analytics-locked = Pro required
dashboard-metric-messages = Messages
dashboard-metric-active-users = Active members
dashboard-metric-joins = Joins
dashboard-metric-leaves = Leaves
dashboard-metric-moderation-actions = Moderation
dashboard-your-space = Your workspace
dashboard-chats = Chats: {$count}
dashboard-chat-roles = Owner: {$owned} · admin: {$admin}
dashboard-members = Members: {$count}
dashboard-paid-chats = Paid chats: {$count}
dashboard-plans-action = Manage plans
dashboard-plans-hint = Choose a chat and unlock the tools it needs.
dashboard-quick-actions = Quick actions
dashboard-open-stats = Open detailed statistics
user-stats-title = Overall statistics
user-stats-subtitle = Activity, growth and moderation across your chats.
stats-chat-filter = Chat
stats-all-chats = All chats
stats-period-summary = Last {$days} days
stats-growth-title = Audience growth
stats-growth-net = Net growth
stats-growth-flow = Joined: {$joins} · left: {$leaves}
stats-change-vs-previous = Compared with previous period
stats-change-new = New period
stats-moderation-title = Moderation
stats-moderation-total = Total actions
stats-moderation-mine = Done by you

## Plans
plans-title = Plans
plans-subtitle = Compare every platform capability in one place.
plans-chat-title = For which chat
plans-no-chats = Add the bot to a group and grant it administrator rights first.
plans-compare = Compare capabilities
plans-current = Current
plans-free-price = Free
plans-price = {$stars} Stars · ${$usd}/mo
plans-choose = Enable {$plan}
plan-description-free = Essential protection and automatic moderation.
plan-description-pro = Analytics, automation and advanced tools.
plan-description-business = AI moderation and team features.
plan-description-white_label = Full personalisation for your brand.

## Profile
profile-title = Profile
profile-subtitle = Your account and Mini App preferences.
profile-no-username = No username set
profile-operator = Platform operator
profile-account = Account
profile-telegram-id = Telegram ID
profile-language-code = Telegram language
profile-first-seen = First seen
profile-date-unknown = No data yet
profile-management = Chat management
profile-chats-total = Total chats
profile-chat-roles = Owner: {$owned} · admin: {$admin}
profile-members-total = Total members
profile-paid-chats = Chats on a paid plan
profile-preferences = Mini App preferences
profile-click-sound = Tap sounds
profile-click-sound-hint = A short click confirms an action.

## Triggers
triggers-title = Triggers
triggers-add = New trigger
triggers-pattern = Keyword or pattern
triggers-match = Matching
triggers-response = Reply
triggers-match-exact = Exact match
triggers-match-contains = Contains
triggers-match-regex = Regular expression
triggers-case-sensitive = Case-sensitive
triggers-delete-source = Delete the triggering message
triggers-empty = No triggers yet. Add one to reply automatically to a keyword.

## Scheduled posts
posts-title = Scheduled posts
posts-add = New post
posts-name = Name
posts-text = Post text
posts-schedule = Schedule
posts-schedule-once = Once
posts-schedule-daily = Daily
posts-schedule-cron = Cron
posts-run-at = Send at
posts-time = Time
posts-daily-hint = In the chat's timezone, every day.
posts-cron = Cron expression
posts-cron-hint = Minute hour day month weekday — in the chat's timezone.
posts-pin = Pin after sending
posts-delete-previous = Delete the previous copy
posts-enabled = Active
posts-paused = Paused
posts-next-run = Next: {$when}
posts-empty = No scheduled posts yet.

## Reputation
reputation-title = Reputation
reputation-empty = No reputation recorded yet.
reputation-score = Score
reputation-level = Level {$level}
reputation-adjust = Adjust
reputation-adjust-add = Add
reputation-adjust-remove = Take away
reputation-adjust-amount = How many points
reputation-adjust-result = Becomes {$total}
reputation-adjust-hint = Added to or taken off the current score, not a new total.

## Billing
billing-title = Plan
billing-current = Current plan
billing-expires = Active until {$date}
billing-expired = Expired {$date}
billing-grace = Grace period ends {$date}
billing-lifetime = No expiry
billing-months = {$count ->
        [one] {$count} month
       *[other] {$count} months
    }
billing-pay-stars = Pay {$amount} Stars
billing-pay-crypto = Pay {$amount} USD in crypto
billing-history = Payment history
billing-history-empty = No payments yet.
billing-status-paid = Paid
billing-status-pending = Pending
billing-status-failed = Failed
billing-status-refunded = Refunded
billing-invoice-opening = Opening the invoice…
billing-invoice-paid = Payment received. Your plan is active.
billing-invoice-cancelled = Payment cancelled.
billing-invoice-failed = Couldn't open the payment. Nothing was charged, please try again.
billing-invoice-unsupported = This client can't open payment links. Open the chat on Telegram and try again.
billing-provider-unavailable = Payments are temporarily unavailable because no provider is configured.
billing-choose-term = Term
billing-features = Included

## What each plan includes, one key per `Feature`
feature-moderation = Warnings, mutes and bans
feature-captcha = Captcha for new members
feature-greeting = Greeting message
feature-stop-words = Stop-word lists
feature-anti-flood = Anti-flood
feature-log-channel = Moderation log channel
feature-anti-raid = Anti-raid lockdown
feature-stats = Statistics and reports
feature-triggers = Keyword triggers
feature-autopost = Scheduled posts
feature-reputation = Reputation
feature-levels = Levels and points
feature-forced-subscription = Required channel subscription
feature-ai-moderation = AI moderation
feature-crossban = Cross-ban network
feature-chat-networks = Linked chat networks
feature-priority-support = Priority support
feature-white-label = White label

## Platform operator panel
platform-title = Platform
platform-chats = Chats
platform-active-chats = Active
platform-revenue-stars = Stars, 30 days
platform-revenue-usd = USD, 30 days
platform-bans = Global bans
platform-bans-title = Global blacklist
platform-bans-empty = The blacklist is empty.
platform-ban-add = Blacklist a user
platform-ban-user-id = Telegram user ID
platform-ban-reason = Reason
platform-ban-revoke = Lift ban
platform-ban-revoke-confirm = Lift the global ban on {$id}? They will be able to post in every chat again.
platform-ban-chats = Reported by {$count ->
        [one] {$count} chat
       *[other] {$count} chats
    }
platform-broadcast-title = Broadcast
platform-broadcast-text = Message
platform-broadcast-plans = Send to plans
platform-broadcast-send = Queue broadcast
platform-broadcast-queued = Queued for {$count ->
        [one] {$count} chat
       *[other] {$count} chats
    }
platform-broadcast-confirm = Send this to every chat on the selected plans?
chat-bot-permissions = Bot permissions
chat-bot-status = Moderation readiness
chat-privacy-disabled = Privacy Mode is disabled: ordinary messages are always available.
chat-privacy-enabled = Privacy Mode is enabled: reading works while the bot is an administrator.
chat-permission-read = Read ordinary messages
chat-permission-delete = Delete messages
chat-permission-restrict = Restrict and ban members
chat-permission-invite = Create invite links
state-ready = Ready
state-attention = Needs attention
