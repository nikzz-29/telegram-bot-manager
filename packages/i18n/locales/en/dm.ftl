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
start-welcome = Hi! I help run Telegram chats: moderation, captcha, statistics and autoposting. Add me to a chat as an administrator and I start working right away, on the Free plan.

    <b>What is here:</b>
    /profile — your profile
    /chats — your chats and their plans
    /plans — plans and payment
    /help — what the bot can do
help-text = <b>In a chat</b> — the moderation commands: /warn, /mute, /ban, /kick, /del, /ro. They are for administrators, and the bot answers them in the chat itself.

    <b>Here, in the DM</b>:
    /profile — who you are to the bot and which chats you run
    /chats — your chats with their plan and renewal date
    /plans — what the plans cost and how to pay

    The fine settings — stop words, captcha, triggers, autoposting — live in the control panel, which a platform operator opens with /admin.
open-miniapp = Open control panel
menu-button = Panel

## Private chat — control panel
admin-welcome = The control panel is open. Every chat setting lives there.
admin-forbidden = The control panel is for platform operators only. Whoever connected the bot configures your chat; /profile, /chats and /plans are yours.

## Private chat — profile and chats
dm-profile-header = <b>{$name}</b>
dm-profile-id = ID: <code>{$id}</code>
dm-profile-anonymous = id{$id}
dm-profile-chats = {$count ->
        [0] You do not administer any chat with this bot yet.
        [one] You administer {$count} chat:
       *[other] You administer {$count} chats:
    }
dm-profile-more = …and {$count ->
        [one] {$count} more chat
       *[other] {$count} more chats
    }. The full list is /chats
dm-chat-untitled = Untitled
dm-chats-header = {$count ->
        [one] <b>Your chat</b>
       *[other] <b>Your chats</b>
    }
dm-chats-row = • <b>{$chat}</b> — {$plan}, until {$until}
dm-chats-row-free = • <b>{$chat}</b> — {$plan}
dm-chats-empty = No chats yet. Add the bot to a group and grant it administrator rights — the chat appears here as soon as the first message arrives.
dm-chats-button = My chats
dm-profile-button = Profile

## Private chat — plans and payment
dm-plans-header = <b>Plans</b>
dm-plans-row = <b>{$plan}</b> — {$stars} Stars or ${$usd} per month
dm-plans-hint = A plan is bought for one chat, for a term of 1 to {$months} months. Payment is in Telegram Stars.
dm-plans-button = {$plan} — {$stars} Stars/mo
dm-plans-button-short = Plans
dm-buy-choose-chat = Which chat is {$plan} for?
dm-buy-choose-term = <b>{$chat}</b> → {$plan}. For how long?
dm-buy-no-chats = A plan is bought for a chat, and you have none yet. Add the bot to a group as an administrator and come back.
dm-buy-unknown-chat = That chat is no longer available. Open /chats and start again.
dm-buy-invoice = <b>{$chat}</b> → {$plan}, {$months ->
        [one] {$months} month
       *[other] {$months} months
    }. The invoice is ready — pay it with the button below.
dm-buy-pay = Pay {$stars} Stars
dm-term-button = {$months ->
        [one] {$months} month
       *[other] {$months} months
    } — {$stars} Stars

## Private chat — navigation and sections
# Button labels are plain text, not HTML: Telegram renders them verbatim, so
# {$chat} and {$period} here are neither escaped nor marked up.
dm-menu = <b>Main menu</b>

    Profile, your chats, statistics, plans and the guide — all below.
dm-home-button = 🏠 Menu
dm-back-button = ‹ Back
dm-stats-button = 📊 Statistics
dm-guide-button = 📖 Guide
dm-guide-contents-button = 📖 Contents
dm-chat-report-button = 📊 {$chat}
dm-chats-setup-button = 🚀 How to connect a chat
dm-chat-unavailable = That chat is no longer available. Open the chat list and start again.
dm-stats-period-current = • {$period} •
