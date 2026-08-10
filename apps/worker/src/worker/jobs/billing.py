"""Subscription lifecycle: remind, lapse into grace, then downgrade.

Spec §5.8. Three sweeps, each of which re-reads the chat's own row rather than
trusting that the previous one ran. A worker that was down for a day comes back
and does the right thing for every chat in one pass, in the right order, because
each transition is expressed as a condition on state and not as a follow-on job.

DECISION: these are crons over `find_expiring`, not per-subscription jobs armed
at purchase time. A deferred job would have to be re-armed on every renewal,
cancelled on every downgrade, and would silently strand a chat if Redis lost it.
The query is one indexed scan of the paid chats and cannot drift from the rows.

DECISION: notices go to the owner's DM when the chat has an owner on file, and to
the chat itself otherwise. Billing is the owner's business rather than the whole
group's, but a chat with no known owner still has admins reading it, and a
downgrade nobody was told about is the worst outcome of the three.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final

from aiogram.methods import SendMessage

from core.billing import billing
from core.redis_client import get_redis
from core.sender import SendPriority, sender
from db.models import Chat
from db.uow import UnitOfWork
from i18n.runtime import translator
from shared.config import get_settings
from shared.logging import get_logger
from shared.plans import GRACE_PERIOD_DAYS
from shared.time_utils import utc_now
from worker.registry import scheduled

logger = get_logger(__name__)

WorkerContext = dict[Any, Any]

# One reminder per chat per subscription window. Keyed by the expiry the reminder
# was about, so a renewal — which moves the expiry — re-arms it for free.
REMINDER_MARKER: Final = "tgm:billing:reminded:{chat_id}:{expires}"
REMINDER_MARKER_TTL: Final = timedelta(days=GRACE_PERIOD_DAYS + 7)

DATE_FORMAT: Final = "%Y-%m-%d"


def _target(chat: Chat) -> tuple[int, bool]:
    """(chat id to send to, is a direct message)."""
    if chat.owner_tg_id:
        return chat.owner_tg_id, True
    return chat.tg_chat_id, False


def _notify(chat: Chat, text: str) -> None:
    """Queue one billing notice. Never silent — this one is worth a buzz."""
    target, _ = _target(chat)
    sender.enqueue(
        SendMessage(chat_id=target, text=text),
        chat_id=target,
        priority=SendPriority.SYSTEM,
    )


def _days_between(start: datetime, end: datetime) -> int:
    """Whole days remaining, rounded up: six hours left is still "1 day"."""
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return 0
    return int(-(-seconds // 86_400))


@scheduled(hour={9}, minute={17})
async def send_renewal_reminders(ctx: WorkerContext) -> int:
    """Warn owners whose subscription ends within `payment_reminder_days`.

    Once daily, not hourly: this is the one job here that talks to people who did
    nothing wrong, and a reminder that arrives twice reads as a dunning notice.
    """
    settings = get_settings()
    now = utc_now()
    horizon = now + timedelta(days=settings.payment_reminder_days)

    async with UnitOfWork() as uow:
        candidates = await uow.chats.find_expiring(horizon)

    client = get_redis()
    sent = 0
    for chat in candidates:
        expires = chat.plan_expires_at
        # `find_expiring` is inclusive of the past; those are the expiry sweep's
        # problem, not the reminder's.
        if expires is None or expires <= now or not chat.is_active:
            continue

        marker = REMINDER_MARKER.format(chat_id=chat.id, expires=expires.strftime(DATE_FORMAT))
        if not await client.set(marker, "1", ex=REMINDER_MARKER_TTL, nx=True):
            continue

        t = translator(chat.language)
        _notify(
            chat,
            "\n".join(
                (
                    t("billing-reminder-title"),
                    t(
                        "billing-reminder-body",
                        plan=chat.plan.value.upper(),
                        chat=chat.title or str(chat.tg_chat_id),
                        until=expires.strftime(DATE_FORMAT),
                        days=_days_between(now, expires),
                    ),
                )
            ),
        )
        sent += 1

    if sent:
        logger.info("job.send_renewal_reminders", reminded=sent, candidates=len(candidates))
    return sent


@scheduled(minute={7, 37})
async def expire_subscriptions(ctx: WorkerContext) -> int:
    """Open the grace window for chats whose paid term just ended.

    Half-hourly rather than daily: `effective_plan` already keeps a lapsed chat
    working through its grace window on its own, so this job is not what saves
    the chat — it is what tells the owner, and a "your subscription ended" notice
    twelve hours late is a notice nobody trusts.
    """
    now = utc_now()
    async with UnitOfWork() as uow:
        candidates = await uow.chats.find_expiring(now)

    lapsed = 0
    for chat in candidates:
        # Already in grace, or already handled by an earlier run of this sweep.
        if chat.grace_until is not None or chat.plan_expires_at is None:
            continue
        try:
            until = await billing.begin_grace(chat, now=now)
        except Exception:
            logger.exception("job.expire_subscriptions.failed", chat_id=chat.id)
            continue

        t = translator(chat.language)
        _notify(
            chat,
            "\n".join(
                (
                    t("billing-grace-title"),
                    t(
                        "billing-grace-body",
                        plan=chat.plan.value.upper(),
                        chat=chat.title or str(chat.tg_chat_id),
                        until=until.strftime(DATE_FORMAT),
                        days=_days_between(now, until),
                    ),
                )
            ),
        )
        lapsed += 1

    if lapsed:
        logger.info("job.expire_subscriptions", lapsed=lapsed)
    return lapsed


@scheduled(minute={22, 52})
async def apply_downgrade(ctx: WorkerContext) -> int:
    """Move chats whose grace window has closed onto Free.

    DECISION: the sweep re-checks `grace_until` against the clock instead of
    acting on whatever `expire_subscriptions` decided earlier. A chat that paid
    during its grace window has had `grace_until` cleared by `apply_payment`, and
    that single condition is what keeps a renewal from being undone by a downgrade
    that was already in flight.
    """
    now = utc_now()
    async with UnitOfWork() as uow:
        candidates = await uow.chats.find_expiring(now)

    downgraded = 0
    for chat in candidates:
        if chat.grace_until is None or chat.grace_until > now:
            continue
        try:
            await billing.downgrade(chat.id)
        except Exception:
            logger.exception("job.apply_downgrade.failed", chat_id=chat.id)
            continue

        t = translator(chat.language)
        _notify(
            chat,
            "\n".join(
                (
                    t("billing-downgraded-title"),
                    t(
                        "billing-downgraded-body",
                        chat=chat.title or str(chat.tg_chat_id),
                    ),
                )
            ),
        )
        downgraded += 1

    if downgraded:
        logger.info("job.apply_downgrade", downgraded=downgraded)
    return downgraded


__all__ = ["apply_downgrade", "expire_subscriptions", "send_renewal_reminders"]
