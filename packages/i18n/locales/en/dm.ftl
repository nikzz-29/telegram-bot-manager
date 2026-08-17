# English locale: the bot's private chat. Keys must match ru/dm.ftl exactly.
#
# Why a separate file: `main.ftl` is what the bot says in groups, and it is edited
# alongside the modules. The DM conversation is its own surface with its own pace
# of change, and keeping it here is cheaper than hunting for the right section
# among three hundred keys.
#
# Same convention as main.ftl: {$user} is an already-built HTML mention and must
# not be escaped again; every other placeholder is plain text.

## Private chat
start-welcome = 👋 <b>Welcome!</b>

    🛡️ I help run Telegram chats: moderation, onboarding, statistics and scheduled posts.
    🚀 Add me to a group as an administrator — the chat connects automatically on the Free plan.
    📱 Open the Mini App with the button beside the message field for statistics, chats, plans, profile and settings.
    🌐 Use /website to receive a one-time link to your personal statistics dashboard.
    📋 The pinned button below keeps the full command list one tap away.
help-text = 📋 <b>Bot commands</b>

    🛡️ Group moderation commands are for administrators; public commands are marked separately.
    👤 In the DM you can open your profile, chats, statistics and plans.
    📱 Fine settings live in the Mini App — open it with the button beside the message field.
open-miniapp = 📱 Open Mini App
menu-button = 📱 Mini App

## Private chat — control panel
admin-welcome = 🛠️ The operator console is ready to open.
admin-forbidden = 🔒 This operator command is unavailable. Open the user Mini App with the button beside the message field.

## Private chat — profile and chats
dm-profile-header = 👤 <b>{$name}</b>
dm-profile-username = 🔗 Username: {$username}
dm-profile-id = 🆔 Telegram ID: <code>{$id}</code>
dm-profile-language = 🌐 Telegram language: {$language}
dm-profile-anonymous = id{$id}
dm-value-not-set = not set
dm-value-unknown = unknown
dm-profile-chats = {$count ->
        [0] 🗂️ No connected chats yet.
        [one] 🗂️ Under your management: <b>{$count} chat</b>
       *[other] 🗂️ Under your management: <b>{$count} chats</b>
    }
dm-profile-roles = 👑 Owner: <b>{$owners}</b> · 🛡️ Administrator: <b>{$admins}</b>
dm-profile-subscriptions = 🆓 Free: <b>{$free}</b> · 💎 Paid: <b>{$paid}</b>
dm-profile-plan-count = {$plan}: {$count}
dm-profile-plans = 💳 Plans: {$plans}
dm-profile-members = 👥 Members in known chats: <b>{$count}</b>
dm-profile-members-unknown = 👥 Member counts will appear after chat synchronization.
dm-profile-next-expiry = 📅 Nearest plan expiry: <b>{$until}</b>
dm-profile-no-expiry = ♾️ No active plan has an expiry date.
dm-profile-preview-title = 📌 <b>Quick overview</b>
dm-profile-chat-preview = ▫️ {$chat} · {$plan}
dm-profile-more = ➕ {$count ->
        [one] {$count} more chat
       *[other] {$count} more chats
    }. The full list is /chats
dm-chat-untitled = Untitled
dm-chats-header = {$count ->
        [one] 💬 <b>My chat</b>
       *[other] 💬 <b>My chats · {$count}</b>
    }
dm-chats-page = 📄 Page <b>{$page}</b> of <b>{$pages}</b>
dm-chats-row = {$status} <b>{$chat}</b> · {$role}
dm-chats-row-meta = 💎 {$plan} · {$members} · 🔗 {$username}
dm-chats-row-free = ♾️ Free plan with no expiry
dm-chats-row-open-ended = ♾️ Plan active with no recorded expiry
dm-chats-row-until = 📅 Active until <b>{$until}</b>
dm-chats-empty = 🚀 No chats yet. Add the bot to a group, grant administrator rights and send the first message — the chat will then appear here.
dm-chat-role-owner = 👑 owner
dm-chat-role-admin = 🛡️ administrator
dm-chat-private = private chat
dm-chat-members = 👥 {$count}
dm-chat-members-unknown = 👥 no data
dm-chats-button = 💬 My chats
dm-profile-button = 👤 Profile
dm-page-prev-button = ⬅️ Back
dm-page-next-button = ➡️ Next

## Private chat — plans and payment
dm-plans-header = 💎 <b>Plans</b>
dm-plans-intro = 🧭 Each plan belongs to one chat. Higher tiers include the capabilities of the tiers below.
dm-plans-row-free = {$icon} <b>{$plan}</b> · free forever
dm-plans-row = {$icon} <b>{$plan}</b> · {$stars} Stars or ${$usd} per month
dm-plans-features = 🧩 Capabilities: {$features}
dm-plans-limits = 📏 Limits: {$limits}
dm-feature-moderation = warnings, mutes and bans
dm-feature-captcha = newcomer captcha
dm-feature-greeting = greeting
dm-feature-stop-words = stop words
dm-feature-anti-flood = anti-flood
dm-feature-log-channel = moderation log
dm-feature-anti-raid = anti-raid
dm-feature-stats = statistics and reports
dm-feature-triggers = triggers
dm-feature-autopost = scheduled posts
dm-feature-reputation = reputation
dm-feature-levels = levels
dm-feature-forced-subscription = required subscription
dm-feature-ai-moderation = AI moderation
dm-feature-crossban = cross-ban network
dm-feature-chat-networks = chat networks
dm-feature-priority-support = priority support
dm-feature-white-label = custom branding
dm-limit-stop-words = stop words {$count}
dm-limit-triggers = triggers {$count}
dm-limit-posts = posts {$count}
dm-limit-ai = AI checks/day {$count}
dm-limit-stats = statistics history {$count} days
dm-plans-hint = 💳 Buy a paid plan for a selected chat for 1 to {$months} months. Payment is in Telegram Stars.
dm-plans-button = 💳 {$plan} · {$stars} Stars/mo
dm-plans-button-short = 💎 Plans
dm-buy-choose-chat = 💬 Which chat should get {$plan}?
dm-buy-choose-term = 📅 <b>{$chat}</b> → {$plan}. Choose the subscription term.
dm-buy-no-chats = 🚀 A plan belongs to a chat, and you have none yet. Add the bot to a group as an administrator and come back.
dm-buy-unknown-chat = ⚠️ That chat is no longer available. Open /chats and start again.
dm-buy-invoice = 🧾 <b>{$chat}</b> → {$plan}, {$months ->
        [one] {$months} month
       *[other] {$months} months
    }. The invoice is ready — pay it with the button below.
dm-buy-pay = ⭐ Pay {$stars} Stars
dm-term-button = 📅 {$months ->
        [one] {$months} month
       *[other] {$months} months
    } — {$stars} Stars

## Private chat — navigation and sections
# Button labels are plain text, not HTML: Telegram renders them verbatim, so
# {$chat} and {$period} here are neither escaped nor marked up.
dm-menu = 🏠 <b>Main menu</b>

    👤 Profile and account overview.
    💬 Connected chats and per-chat reports.
    📊 Statistics for a day, week, month or quarter.
    💎 Plans, capabilities and payment.
    📖 A detailed guide to every feature.
dm-home-button = 🏠 Menu
dm-back-button = ↩️ Back
dm-stats-button = 📊 Statistics
dm-guide-button = 📖 Guide
dm-guide-contents-button = 📖 Contents
dm-chat-report-button = 📊 {$chat}
dm-chats-setup-button = 🚀 How to connect a chat
dm-chat-unavailable = ⚠️ That chat is no longer available. Open the chat list and start again.
dm-stats-period-current = ✅ {$period}

## Private chat — persistent command button
dm-commands-reply-button = 📋 Commands
dm-commands-placeholder = Message or command
dm-commands-keyboard-ready = 📌 The “📋 Commands” button is pinned below the message field.

    💡 Tap it any time to open the bot's current command list.
dm-commands-header = 📋 <b>Bot commands</b>
dm-commands-intro = 💡 Use commands in the DM or in a group. The detailed guide explains their arguments.
dm-commands-dm-title = 👤 <b>In the DM</b>
dm-command-row-private = 👤 <code>{$command}</code> — {$description}
dm-command-row-public = 🌍 <code>{$command}</code> — {$description}
dm-command-row-admin = 🔐 <code>{$command}</code> — {$description}
dm-commands-note = 🧭 Legend: 🔐 administrators · 🌍 every member · 👤 private messages.

## Personal website dashboard
dm-website-issued = 🌐 <b>Your personal dashboard is ready</b>

    🔐 This single-use link expires in {$minutes} minutes.
    📊 The site contains your overview, activity, chats, plans and profile.
    🛡️ After sign-in the key disappears from the address bar and cannot be reused.
dm-website-open-button = 🌐 Open dashboard
dm-website-unavailable = ⚠️ The website is not configured yet. An administrator must set WEBSITE_URL.
