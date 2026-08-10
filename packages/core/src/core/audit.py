"""Log channel — who did what to whom, why, and when.

Spec §5.1 requires every moderation action to be mirrored into a channel the
admins choose. This module builds that message and hands it to `MessageSender`.

DECISION: the entry is composed from one small Fluent key per line instead of a
single template with optional placeholders. Fluent has no "omit if empty", and a
log line reading "Причина: " with nothing after it is worse than no line at all.

DECISION: nothing here awaits delivery. A log channel the bot was kicked from
must never slow down or fail the moderation action that triggered the entry — the
sender retries, and gives up into the dead-letter list on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from aiogram.methods import SendMessage

from core.sender import SendPriority, sender
from i18n.runtime import Translator, translator
from shared.logging import get_logger
from shared.time_utils import utc_now

logger = get_logger(__name__)

# Prefixed to the action title so a channel of entries is scannable at a glance.
ACTION_ICONS: dict[str, str] = {
    "warn": "⚠️",
    "unwarn": "✅",
    "mute": "🔇",
    "unmute": "🔊",
    "ban": "⛔",
    "unban": "♻️",
    "kick": "👋",
    "delete": "🗑",
    "auto_delete": "🗑",
    "stop_word": "🚫",
    "content_filter": "🚫",
    "anti_flood": "🌊",
    "read_only": "🔒",
    "alert_admins": "📣",
    "captcha_passed": "🧩",
    "captcha_failed": "🧩",
    "captcha_timeout": "⏳",
    "autoban": "🛡",
    "raid": "🚨",
    "lockdown": "🔐",
    "lockdown_off": "🔓",
    "forced_subscription": "📢",
    "trigger": "💬",
    "autopost": "📨",
    "ai_moderation": "🤖",
    "ai_alert": "🤖",
    "crossban": "🌐",
    "crossban_alert": "🌐",
    "global_ban": "🌐",
    "global_unban": "♻️",
}
DEFAULT_ICON = "📝"


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One line item for the log channel."""

    action: str
    target: str = ""
    moderator: str = ""
    reason: str = ""
    duration: str = ""
    note: str = ""


def _who(name: str, tg_user_id: int | None) -> str:
    """`Имя (id)` — the id matters because display names are not unique."""
    label = escape(name.strip()) if name.strip() else ""
    if tg_user_id is None:
        return label
    return f"{label} (<code>{tg_user_id}</code>)" if label else f"<code>{tg_user_id}</code>"


def format_entry(entry: AuditEntry, *, t: Translator) -> str:
    """Render an entry as HTML, skipping every field that has no value."""
    action_key = f"log-action-{entry.action.replace('_', '-')}"
    title = t.get(action_key) if t.has(action_key) else entry.action
    icon = ACTION_ICONS.get(entry.action, DEFAULT_ICON)

    lines = [f"{icon} <b>{escape(title)}</b>"]
    if entry.target:
        lines.append(t("log-field-target", value=entry.target))
    if entry.moderator:
        lines.append(t("log-field-moderator", value=entry.moderator))
    if entry.duration:
        lines.append(t("log-field-duration", value=escape(entry.duration)))
    if entry.reason:
        lines.append(t("log-field-reason", value=escape(entry.reason)))
    if entry.note:
        lines.append(t("log-field-note", value=escape(entry.note)))
    lines.append(t("log-field-when", value=utc_now().strftime("%Y-%m-%d %H:%M UTC")))
    return "\n".join(lines)


class AuditService:
    """Mirrors moderation actions into a chat's configured log channel."""

    async def report(
        self,
        *,
        log_channel_id: int | None,
        locale: str,
        action: str,
        target_name: str = "",
        target_id: int | None = None,
        moderator_name: str = "",
        moderator_id: int | None = None,
        reason: str = "",
        duration: str = "",
        note: str = "",
    ) -> bool:
        """Queue one log entry. Returns False when the chat has no log channel."""
        if not log_channel_id:
            return False
        entry = AuditEntry(
            action=action,
            target=_who(target_name, target_id),
            moderator=_who(moderator_name, moderator_id),
            reason=reason,
            duration=duration,
            note=note,
        )
        text = format_entry(entry, t=translator(locale))
        sender.enqueue(
            SendMessage(chat_id=log_channel_id, text=text, disable_notification=True),
            chat_id=log_channel_id,
            priority=SendPriority.SYSTEM,
        )
        return True


audit = AuditService()

__all__ = [
    "ACTION_ICONS",
    "AuditEntry",
    "AuditService",
    "audit",
    "format_entry",
]
