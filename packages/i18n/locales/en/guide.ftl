# English locale: the in-DM manual — how the bot is built, how the AI works, what
# each command does. Keys must match ru/guide.ftl exactly.
#
# Why a separate file: this is the longest and least frequently edited copy in the
# project. dm.ftl holds button labels and short answers that change alongside the
# handlers; this holds the text people read end to end.
#
# The constraint that is easy to forget: Telegram caps a message at 4096
# characters and nothing here checks it for us — the sender drops an over-long
# message silently. Hence pages rather than one wall of text.
#
# Key names come from `bot.guide.PAGES`: every slug needs exactly
# `guide-<slug>-title` and `guide-<slug>-body`. A page cannot be added by editing
# this file alone — the list lives in Python.
#
# Markup: parse mode is HTML everywhere, `guide.render` wraps the title in <b> and
# prints the body verbatim. Allowed: <b>, <i>, <code>, <pre>, <a href="">,
# <blockquote>. Any other angle bracket and Telegram rejects the whole message,
# while the sender swallows the rejection: the page simply never shows up. Write
# &lt; and &gt; when the character itself is meant.
#
# No curly brace reaches the output except a real placeholder: Fluent needs a
# special construct for a literal brace, and a test asserts none survives into the
# rendered page. Easier to write without braces.
#
# A paragraph break inside a value is a blank line followed by an indented line.
# An indented line may not start with a dot, an asterisk or a square bracket —
# Fluent reads those as the end of the value. Hence "•" for lists.
#
# Numbers and thresholds come from the code, not from memory: `shared.plans`
# (tiers, quotas, prices), `shared.schemas.module_configs` (defaults),
# `core.ai_provider` and `core.ai_moderation` (model, timeout, cache, breaker).
# When the code changes, so does the page.

## Navigation
guide-index-title = Manual
guide-index-hint = What the bot does and why it does it that way: where to start, how moderation and the AI work, what every command means. Pick a section — inside, the ‹ and › buttons page through.
guide-nav-prev = ‹ Back
guide-nav-next = Next ›
guide-footer = Page {$nth} of {$total}

## Pages
guide-overview-title = What this bot is
guide-overview-body = Not one bot but a platform of seven modules. You add it to a group as an administrator and the chat is protected immediately, on the free tier, with nothing configured.

    <b>The modules</b>
    🛡 Moderation — commands, attachment filters, stop words, anti-flood. Always on and cannot be switched off: everything else rests on it.
    🚪 Entry — captcha, greeting, new-account screening, anti-raid. On by default.
    📊 Statistics, 💬 Engagement (reputation, levels, triggers), 📅 Autoposting — the Pro tier.
    🤖 AI moderation and 🌐 the cross-ban network — the Business tier.

    <b>What happens to every message</b>
    It walks the same chain of checks, cheapest first: duplicate guard, hard rate ceiling, network blacklist, captcha, forced subscription, attachment filters, stop words and anti-flood, and only then the AI.

    The first check that fires deletes the message and the rest never run. That is why the AI is last: a message removed by a stop word never becomes a paid model call.

    <b>Worth knowing up front</b>
    • Chat administrators are exempt from every automatic rule by default.
    • Every action, manual and automatic, can be written to a separate log channel. Often that is the only trace left: a deleted message exists nowhere else.
    • Settings are per chat — language, timezone, limits, texts.
    • The bot never sends directly: everything goes through one rate-limited queue, otherwise Telegram starts refusing requests and it is not one command that goes quiet but the whole chat.

guide-setup-title = Setting the bot up
guide-setup-body = <b>1. Add the bot to the group and make it an administrator.</b>
    Without administrator rights it cannot even see who joined: Telegram only reports join events to admins.

    The rights it needs:
    • delete messages — without it no filter can act;
    • ban users — the same right covers muting and the captcha;
    • pin messages — only if you plan to autopost with a pin;
    • invite via link — if you want joins counted.

    <b>2. Configure nothing.</b>
    On the first event the chat registers itself with sensible values: moderation and entry on, warn limit 3, anti-flood 8 messages per 10 seconds, captcha and greeting off.

    <b>3. Check it.</b>
    Send /warns in the chat and the bot answers with your warning count. An answer means the rights are right.

    <b>4. Add a log channel.</b>
    Create a private channel, add the bot to it as an administrator and name the channel in the moderation settings. Every action lands there: who, whom, what for — and for deleted messages the first 200 characters of the text.

    <b>5. The fine settings.</b>
    Stop words, captcha style, greeting text, triggers, schedules and AI thresholds live in the control panel, a Telegram Mini App. Today only a platform operator opens it with /admin; a chat administrator has the in-chat commands plus /profile, /chats and /plans in DM.

guide-moderation-title = Moderation
guide-moderation-body = <b>How to point at a member</b>
    Every command works two ways: as a reply to the offending message, or with an @username or a numeric id as the first argument. Whatever follows is the reason and goes into the log. The bot deletes your command afterwards: its own report already says what happened, while the line above would only keep the offender's name in the history.

    <b>Warnings</b>
    /warn issues one. Three by default, and the third brings the punishment: a 12-hour mute (a ban or a kick instead, if you prefer). A warning lives 30 days and then stops counting on its own — otherwise one argument two years ago would leave someone permanently one step from a ban.
    /unwarn lifts the last one. /warns shows your own count to anyone, someone else's to admins only.

    <b>Restrictions</b>
    /mute 30m reason — no posting; with no duration it is one hour.
    /ban 7d reason — a ban; with no duration it is permanent.
    /kick — remove, they can come back.
    /unmute and /unban lift them.
    Durations are written 30m, 2h, 7d, 1w. Telegram treats anything under 30 seconds or over 366 days as forever, so such values are clamped to those bounds.

    <b>Messages and the whole chat</b>
    /del as a reply deletes a message. /ro on, /ro off, /ro 30m puts everyone in read-only mode.

    <b>The automatic rules</b>
    • Attachment filters: links, mentions, forwards, photos, video, GIFs, stickers, voice notes, video notes, documents, messages sent on behalf of a channel. Edited messages are checked too — pasting a link into text that is already sent is the oldest workaround there is.
    • Stop words: 100 of your own on Free, plus ready-made sets (profanity, crypto scam, casino). Text is normalised before matching: lookalike letters fold to Latin, invisible characters are stripped, separators inside a word are removed, repeats are collapsed. That is why both "c a s i n o" and a casino spelled with a Cyrillic с are found. An asterisk is a wildcard: casin* catches casino and casinos.
    • Anti-flood: 8 messages per 10 seconds, and separately 4 media per 15 seconds, punished with a 10-minute mute.
    Each rule picks its own action: delete, delete and warn, delete and mute, or only alert the admins.

guide-entry-title = Joining the chat
guide-entry-body = The order never changes: network blacklist, anti-raid, account screening, captcha, greeting. Each step can make the next one unnecessary.

    <b>Captcha</b>
    A newcomer loses the right to post first and sees the challenge second — otherwise they get their advert out in the gap. Three kinds: a single button, the right emoji out of five, and a small sum with four options. Five minutes and three attempts by default. Three wrong taps is an immediate kick regardless of the kick-on-timeout setting: that is an answer, not the absence of one. Nobody can press somebody else's button.

    <b>Greeting</b>
    Text with the member's name and the chat title filled in, optionally with an image and buttons. Sent after the captcha — there is no point greeting someone who never passed it. It can delete itself after a set time.

    <b>New-account screening</b>
    Three signals to choose from: no username, no avatar, account younger than N days. The age is an estimate: Telegram does not report a registration date, so it is interpolated from the numeric id and is accurate to weeks. That is exactly why a suspicious account gets a captcha by default rather than a ban.

    <b>Anti-raid</b>
    10 joins in 30 seconds closes the chat for 15 minutes: new members arrive without the right to post and a warning goes to the chat and the log. Manually it is /lockdown 30m and /lockdown off. Ending the window does not release those already held — each has their own expiry, and only /unmute lifts it early.

    <b>Forced subscription</b>
    A chat can require a channel subscription. The bot must be an administrator in that channel, otherwise membership cannot be checked — and then it lets everyone through rather than locking the whole chat out. The "I subscribed" button rechecks at once instead of waiting for the cache to expire.

guide-ai-title = How AI moderation works
guide-ai-body = This is not some intelligence built into Telegram. It is an ordinary request to an external model over an OpenAI-compatible protocol. The endpoint, the model and the key are platform settings, so your own self-hosted model works just as well. By default: an 8-second timeout, temperature 0, and at most 2000 characters of the message are sent.

    <b>What the model answers</b>
    One of four labels — ok, toxic (insults, harassment, threats), hidden_ad (covert advertising, referral links, "DM me"), scam (fraud, phishing, fake giveaways, impersonated support) — a confidence between 0 and 1, and a short reason. Only text is judged; photos and files are never sent anywhere.

    <b>What the bot does with it</b>
    Each label has its own confidence threshold and its own action. By default: toxic from 0.85 alerts the admins, hidden_ad from 0.80 deletes, scam from 0.75 deletes and warns. Below the threshold nothing happens. The alert-only mode exists so you can watch the model for a while without handing it the right to delete.

    <b>Three gates before a request</b>
    • Short text, under 12 characters, is not checked: there is nothing to judge in "ok".
    • Sampling. You can check only a share of messages, and that share is decided by a hash of the text rather than at random — resending the same text does not buy a fresh coin flip.
    • The verdict cache. An answer is kept for 24 hours under a hash of the text and is shared platform-wide: one scam template blasted into forty chats costs a single request, and a cached verdict spends no quota.
    Then the daily quota: 20 000 checks per chat per day on Business.

    <b>When the AI is unavailable</b>
    With no API key the module simply does not run: nothing is classified and nothing is blocked. On a timeout or a network error the message is allowed and the verdicts of the cheap rules still stand. After five consecutive failures a circuit breaker takes the model out of the path for a minute and no request is even attempted; one probe then decides whether it is back. An unreadable answer counts as ok. Losing messages to somebody else's outage costs more than missing one scam.

    <b>What is recorded</b>
    The check log keeps the label, the confidence, the action taken and a hash of the text. The text itself is not stored.

guide-engagement-title = Reputation, levels and triggers
guide-engagement-body = Three mechanics in one module, each switched on separately.

    <b>Reputation</b>
    A message that starts with a plus, "thanks" or "thank you" and replies to someone else gives that person one point. The word list is configurable. No points to yourself, to a bot, or to the same person twice within a minute — and in those cases the bot stays quiet: a chat where every plus draws a refusal is worse than a chat where a point silently did not land. One member can hand out at most 10 points a day.

    <b>Levels</b>
    Experience comes from messages, 1 each by default. The curve steepens: 100 experience for level two, 300 for three, 600 for four, up to a hundred. Reputation points do not feed levels — otherwise a level could be bought from friends without writing a word. Levels can be given names.
    /rep shows your card, or someone else's as a reply. /top ranks by points, /top level by levels.

    <b>Triggers</b>
    A phrase and its answer: /addtrigger hello | Hi there! Left of the vertical bar is what to look for, right of it what to answer.
    • a plain phrase matches as a substring but on word boundaries: "ok" will not fire inside "broken";
    • an equals sign in front means an exact match only;
    • re: in front means a regular expression.
    /triggers lists them with hit counts, /deltrigger and a number removes one. Regular expressions are screened for dangerous constructs when saved and are matched against the first thousand characters only: matching in Python has no timeout, and a single expression like <code>(a+)+</code> is enough to occupy the whole process.
    Limits: 50 triggers on Pro, 500 on Business.

guide-autopost-title = Autoposting
guide-autopost-body = A post is content plus a schedule. The content — text, image, buttons — is assembled in the panel: a post with media cannot be typed into a chat. What stays in the chat is the controls.

    <b>Schedules</b>
    • Once — an exact date and time.
    • Daily — a time such as 09:00.
    • Cron — five fields as in the system scheduler: minute, hour, day of month, month, day of week.
    Time is read in the chat's timezone, not in UTC. That matters exactly twice a year: "every day at nine" stays nine in the morning across a daylight-saving change instead of drifting by an hour.

    <b>Commands</b>
    /posts lists them: number, title, schedule and the next run. That run is recomputed from the schedule at the moment you ask rather than read from the database: if the timezone was changed or the worker was down, only the recomputed time describes what will actually happen.
    /postpause and a number takes a post off the schedule without deleting its text. /postresume and a number puts it back.

    <b>Also</b>
    A post can pin itself, and it can delete the previous copy before sending the new one — that way a daily announcement does not turn into thirty identical messages in the history.
    A one-off whose time has passed never runs again.
    Limits: 20 posts on Pro, 200 on Business.

guide-stats-title = Statistics
guide-stats-body = <b>What is counted</b>
    Messages, broken down by attachment type, joins and leaves, moderation actions, captchas passed and failed.

    <b>How it is built</b>
    An event is not written to the database on the spot: it goes into a buffer in Redis and a background process moves batches across. A buffer write costs microseconds and does not hold the message handler inside a transaction. Once an hour events are rolled up into one row per chat per day, and reports read only those rows — which is why /stats answers just as fast in a chat of a hundred as in a chat of a hundred thousand. The trade-off: today's numbers appear after the next hourly rollup.

    <b>The report</b>
    /stats covers a week, /stats 30 a month. The depth is capped by the tier: 90 days on Pro, 365 on Business. It shows messages, active members, joins and leaves, net growth, a per-day activity bar and the ten most active members. The answer deletes itself after five minutes so the chat does not fill up with stale reports.

    <b>The daily digest</b>
    An automatic digest can be sent at an hour you choose. It covers the day that has ended rather than the one in progress: a day still running has no complete figure in it. One digest per chat per day, and a repeated background run will not duplicate it.

guide-crossban-title = The cross-ban network
guide-crossban-body = A shared blacklist: a scammer thrown out of one chat is known to the others.

    <b>How someone gets listed</b>
    Two ways. First, three independent chats banned the same person for a reason that reads like fraud (scam, phish, fraud, and the Russian equivalents). Second, a platform operator does it by hand with /gban and a mandatory reason, which takes effect at once.

    <b>Why only those reasons</b>
    A ban for arguing is one moderator's local call, and turning it into a platform-wide ban is not defensible. So only bans with a fraud-shaped reason feed the network — and a chat may choose not to contribute its bans at all.

    <b>What happens in your chat</b>
    When a listed member joins there are two modes. Ban on sight, before the captcha and the greeting. Or alert only: a message goes to the log, or to the chat if there is no log, and the decision stays yours. The second mode exists because the list is filled by other people's chats, and not everyone wants to delegate their bans to them.

    <b>Getting off the list</b>
    Never happens on its own. Three independent chats agreeing is an argument; one chat changing its mind is not. Appeals go through the platform operators.

    Propagating a ban across the network runs in the background: a moderator's command should not wait while the bot visits every chat.

guide-plans-title = Tiers
guide-plans-body = A tier is bought for one chat, not for an account.

    <b>Free</b>
    Moderation and entry in full: every command, attachment filters, 100 stop words, anti-flood, a log channel, captcha, greeting, anti-raid. No expiry.

    <b>Pro — 299 Stars or 4.99 dollars a month</b>
    Adds statistics with 90 days of history, 50 triggers, 20 scheduled posts, reputation, levels, forced subscription, 1000 stop words.

    <b>Business — 999 Stars or 14.99 dollars</b>
    Adds AI moderation with a quota of 20 000 checks a day, the cross-ban network, chat networks, priority support, 500 triggers, 200 posts, 10 000 stop words, 365 days of history.

    <b>White Label — 4999 Stars or 79 dollars</b>
    Adds your own branding, 5000 triggers, 2000 posts, 200 000 AI checks, 730 days of history.

    <b>Paying</b>
    /plans in a private chat with the bot. Two rails: Telegram Stars and CryptoBot. Up to 12 months at once; a month counts as 30 days.
    Changing tier restarts the term rather than adding days to the old one: prorating the remainder would shortchange the buyer in one direction and the platform in the other.

    <b>When the term ends</b>
    Three days of grace with the tier intact, then the chat runs as Free. Nothing is deleted: the paid modules simply stop firing, and renewing brings everything back as it was.

guide-commands-title = Every command
guide-commands-body = <b>In a private chat with the bot</b>
    /profile — your profile
    /chats — your chats
    /plans — tiers and payment
    /help — help

    <b>In the chat: moderation</b>
    /warn — issue a warning
    /unwarn — lift a warning
    /warns — show warnings
    /mute — stop someone posting
    /unmute — let them post again
    /ban — ban a member
    /unban — unban a member
    /kick — remove a member
    /del — delete a message
    /ro — read-only mode

    <b>In the chat: entry</b>
    /lockdown — close the chat to newcomers

    <b>In the chat: statistics</b>
    /stats — chat statistics

    <b>In the chat: engagement</b>
    /addtrigger — add a trigger
    /deltrigger — remove a trigger
    /triggers — list triggers
    /rep — reputation
    /top — top members

    <b>In the chat: autoposting</b>
    /posts — scheduled posts
    /postpause — pause a post
    /postresume — put a post back on schedule

    <b>In the chat: network</b>
    /gban — global ban

    In-chat commands are for administrators. The exceptions: your own /warns, /rep and /top are open to everyone, and /gban is for platform operators only. Telegram's command menu shows the commands of whichever modules the chat's tier allows.

guide-faq-title = Common questions
guide-faq-body = <b>The bot does not react at all.</b>
    Almost always this is permissions. It has to be an administrator with the rights to delete messages and ban members. Without the second one, neither mutes nor the captcha work.

    <b>A command gives no answer.</b>
    The moderation commands are for chat administrators only. So is looking at another member's warnings.

    <b>My message vanished with no explanation.</b>
    An automatic rule fired. The note in the chat may have deleted itself, but the full reason is always in the log channel, if one is connected.

    <b>Why can't an administrator be muted?</b>
    Telegram does not allow restricting administrators — not by a bot, not by a person. Remove the rights first.

    <b>Who is the "system moderator" in the log?</b>
    That is how actions on behalf of an anonymous administrator are recorded: Telegram sends those messages with no author, so there is no particular person to name.

    <b>The AI let an obvious scam through.</b>
    There are five reasons: the author is an administrator, the text is shorter than 12 characters, the message was not in the sample, the daily quota is spent, or the model is unavailable. In the last case the message is passed on purpose: losing messages to someone else's outage costs more than letting one violation through.

    <b>Statistics are empty.</b>
    Statistics are a Pro feature, and events are rolled up once an hour. There is nothing to see right after connecting.

    <b>The bot deleted my command.</b>
    That is by design: its report already said what happened, and the command line would only keep the offender's name in the history.

    <b>Warnings reset by themselves.</b>
    Each one lives for 30 days (the value is configurable) and then stops counting.

    <b>How do I turn a module off?</b>
    In the control panel. Moderation cannot be turned off — everything else rests on it.
