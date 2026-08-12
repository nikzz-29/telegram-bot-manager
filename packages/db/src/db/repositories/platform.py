"""Platform-wide reporting for the creator-only console.

Every other repository is `chat_id`-scoped, which is the right default: a query
that forgets its tenant filter is a data leak. Nothing here takes a chat id, so
the file exists partly to make that obvious — if a method belongs in this file it
is only ever reachable behind `SuperadminDep`.

DECISION: the daily series is assembled from four grouped queries plus one
baseline count, then zip-filled in Python over the requested days. The
alternative — a `generate_series` CTE joined five ways — is one round trip
instead of five, but it hides which numbers come from which table, and the window
is capped at a year so the Python side is at most 365 rows.

DECISION: revenue counts payments whose status is still `paid`. A refund
therefore removes the money from every window it appeared in, including past
ones, rather than showing as an offsetting entry in the month it was issued. For
an operator asking "what did this platform earn", the refunded month never
earned it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import ColumnElement, Select, and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    AdminUser,
    Chat,
    GlobalBan,
    GlobalBanReport,
    Payment,
    PlanOverride,
    StatDaily,
    TgUser,
)
from shared.enums import PaymentStatus, Plan

# Stars are quoted in XTR and everything else is fiat; the console shows the two
# columns separately because they cannot be added up.
STARS_CURRENCY: Final = "XTR"

MAX_PAGE_SIZE: Final = 200


def _int(value: object) -> int:
    """SQL aggregates arrive as `Any`; a NULL sum is zero here, not None."""
    if value is None:
        return 0
    return int(Decimal(str(value)))


def _money(value: object) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def _as_date(value: object) -> date:
    """`func.date()` gives a `date` on asyncpg and a string on some drivers."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


@dataclass(frozen=True, slots=True)
class PlatformDay:
    """One point on the operator dashboard's charts."""

    day: date
    chats: int
    new_chats: int
    active_chats: int
    messages: int
    moderation_actions: int
    joins: int
    leaves: int
    subscriptions: int
    revenue_stars: int
    revenue_usd: Decimal
    refunds: int
    churned_chats: int


@dataclass(frozen=True, slots=True)
class PlatformTotals:
    """Point-in-time counts plus whole-window sums."""

    chats: int
    active_chats: int
    paying_chats: int
    new_chats: int
    known_users: int
    messages: int
    active_chats_in_window: int
    moderation_actions: int
    subscriptions: int
    refunds: int
    revenue_stars: int
    revenue_usd: Decimal
    refunded_stars: int
    refunded_usd: Decimal


@dataclass(frozen=True, slots=True)
class PlatformPlanRow:
    plan: Plan
    chats: int
    active_chats: int
    subscriptions: int
    revenue_stars: int
    revenue_usd: Decimal


@dataclass(frozen=True, slots=True)
class PlatformUserRow:
    """A known Telegram user as the console's user table needs to draw them."""

    tg_user_id: int
    username: str | None
    first_name: str
    last_name: str | None
    is_bot: bool
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    admin_chats: int
    owned_chats: int
    is_globally_banned: bool
    ban_reports: int
    payments: int
    spent_stars: int
    spent_usd: Decimal
    last_payment_at: datetime | None


@dataclass(frozen=True, slots=True)
class PlatformPaymentRow:
    """A payment plus the chat it was for, which is what the console lists by."""

    payment: Payment
    chat_title: str
    tg_chat_id: int


class PlatformRepository:
    """Cross-tenant aggregates. Only ever called behind `SuperadminDep`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- dashboard ------------------------------------------------------------
    async def totals(self, *, start: date, end: date) -> PlatformTotals:
        chats = await self._scalar(select(func.count()).select_from(Chat))
        active = await self._scalar(
            select(func.count()).select_from(Chat).where(Chat.is_active.is_(True))
        )
        # "Paying" is the stored plan, not the effective one: a chat inside its
        # grace window has stopped paying, and counting it here would make churn
        # invisible for three days.
        paying = await self._scalar(
            select(func.count()).select_from(Chat).where(Chat.plan != Plan.FREE)
        )
        known_users = await self._scalar(select(func.count()).select_from(TgUser))
        new_chats = await self._scalar(
            select(func.count())
            .select_from(Chat)
            .where(func.date(Chat.created_at) >= start, func.date(Chat.created_at) <= end)
        )

        activity = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(StatDaily.messages), 0),
                    func.coalesce(func.sum(StatDaily.moderation_actions), 0),
                    func.count(func.distinct(case((StatDaily.messages > 0, StatDaily.chat_id)))),
                ).where(StatDaily.date >= start, StatDaily.date <= end)
            )
        ).one()

        money = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(self._count_if(self._paid())), 0),
                    func.coalesce(func.sum(self._amount_if(self._paid(), stars=True)), 0),
                    func.coalesce(func.sum(self._amount_if(self._paid(), stars=False)), 0),
                    func.coalesce(func.sum(self._count_if(self._refunded())), 0),
                    func.coalesce(func.sum(self._amount_if(self._refunded(), stars=True)), 0),
                    func.coalesce(func.sum(self._amount_if(self._refunded(), stars=False)), 0),
                ).where(
                    func.date(Payment.created_at) >= start, func.date(Payment.created_at) <= end
                )
            )
        ).one()

        return PlatformTotals(
            chats=chats,
            active_chats=active,
            paying_chats=paying,
            new_chats=new_chats,
            known_users=known_users,
            messages=_int(activity[0]),
            moderation_actions=_int(activity[1]),
            active_chats_in_window=_int(activity[2]),
            subscriptions=_int(money[0]),
            revenue_stars=_int(money[1]),
            revenue_usd=_money(money[2]),
            refunds=_int(money[3]),
            refunded_stars=_int(money[4]),
            refunded_usd=_money(money[5]),
        )

    async def daily_series(self, *, start: date, end: date) -> list[PlatformDay]:
        activity = await self._activity_by_day(start=start, end=end)
        signups = await self._signups_by_day(start=start, end=end)
        money = await self._money_by_day(start=start, end=end)
        refunds = await self._refunds_by_day(start=start, end=end)
        churn = await self._churn_by_day(start=start, end=end)
        # Chats are a running total, so the series needs to know how many existed
        # before the window opened; without it every chart would start at zero.
        running = await self._scalar(
            select(func.count()).select_from(Chat).where(func.date(Chat.created_at) < start)
        )

        series: list[PlatformDay] = []
        day = start
        while day <= end:
            new_chats = signups.get(day, 0)
            running += new_chats
            messages, moderation, joins, leaves, active = activity.get(day, (0, 0, 0, 0, 0))
            subscriptions, stars, usd = money.get(day, (0, 0, Decimal(0)))
            series.append(
                PlatformDay(
                    day=day,
                    chats=running,
                    new_chats=new_chats,
                    active_chats=active,
                    messages=messages,
                    moderation_actions=moderation,
                    joins=joins,
                    leaves=leaves,
                    subscriptions=subscriptions,
                    revenue_stars=stars,
                    revenue_usd=usd,
                    refunds=refunds.get(day, 0),
                    churned_chats=churn.get(day, 0),
                )
            )
            day = date.fromordinal(day.toordinal() + 1)
        return series

    async def plan_mix(self, *, start: date, end: date) -> list[PlatformPlanRow]:
        """Chats and revenue per plan, one row per plan even at zero.

        The console draws a bar per plan, so a plan nobody is on has to arrive as
        a zero rather than as a gap the front-end has to reconstruct.
        """
        chats = {
            str(plan): (_int(total), _int(active))
            for plan, total, active in (
                await self._session.execute(
                    select(
                        Chat.plan,
                        func.count(),
                        func.count(func.distinct(case((Chat.is_active.is_(True), Chat.id)))),
                    ).group_by(Chat.plan)
                )
            ).all()
        }
        money = {
            str(plan): (_int(count), _int(stars), _money(usd))
            for plan, count, stars, usd in (
                await self._session.execute(
                    select(
                        Payment.plan,
                        func.count(),
                        func.coalesce(func.sum(self._amount_if(self._paid(), stars=True)), 0),
                        func.coalesce(func.sum(self._amount_if(self._paid(), stars=False)), 0),
                    )
                    .where(
                        self._paid(),
                        func.date(Payment.created_at) >= start,
                        func.date(Payment.created_at) <= end,
                    )
                    .group_by(Payment.plan)
                )
            ).all()
        }

        rows: list[PlatformPlanRow] = []
        for plan in Plan:
            total, active = chats.get(plan.value, (0, 0))
            count, stars, usd = money.get(plan.value, (0, 0, Decimal(0)))
            rows.append(
                PlatformPlanRow(
                    plan=plan,
                    chats=total,
                    active_chats=active,
                    subscriptions=count,
                    revenue_stars=stars,
                    revenue_usd=usd,
                )
            )
        return rows

    # --- users ----------------------------------------------------------------
    async def user_page(
        self,
        *,
        search: str = "",
        banned_only: bool = False,
        admins_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PlatformUserRow], int]:
        """One page of known users, with everything the console shows per row.

        The per-row counts are correlated scalar subqueries rather than joins: a
        user administering three chats and holding two payments would otherwise
        arrive six times and every count would be multiplied by the other side.
        A page is at most `MAX_PAGE_SIZE` rows, so the subqueries run that many
        times and no more.
        """
        conditions = self._user_conditions(
            search=search, banned_only=banned_only, admins_only=admins_only
        )
        total = await self._scalar(select(func.count()).select_from(TgUser).where(*conditions))

        admin_chats = (
            select(func.count(func.distinct(AdminUser.chat_id)))
            .where(AdminUser.tg_user_id == TgUser.tg_user_id)
            .correlate(TgUser)
            .scalar_subquery()
        )
        owned_chats = (
            select(func.count())
            .select_from(Chat)
            .where(Chat.owner_tg_id == TgUser.tg_user_id)
            .correlate(TgUser)
            .scalar_subquery()
        )
        ban_reports = (
            select(func.count(func.distinct(GlobalBanReport.chat_id)))
            .where(GlobalBanReport.tg_user_id == TgUser.tg_user_id)
            .correlate(TgUser)
            .scalar_subquery()
        )
        payer = and_(Payment.payer_tg_id == TgUser.tg_user_id, self._paid())
        payments = (
            select(func.count())
            .select_from(Payment)
            .where(payer)
            .correlate(TgUser)
            .scalar_subquery()
        )
        spent_stars = (
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(payer, Payment.currency == STARS_CURRENCY)
            .correlate(TgUser)
            .scalar_subquery()
        )
        spent_usd = (
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(payer, Payment.currency != STARS_CURRENCY)
            .correlate(TgUser)
            .scalar_subquery()
        )
        last_payment = (
            select(func.max(Payment.created_at)).where(payer).correlate(TgUser).scalar_subquery()
        )

        stmt: Select[Any] = (
            select(
                TgUser,
                admin_chats,
                owned_chats,
                self._is_banned(),
                ban_reports,
                payments,
                spent_stars,
                spent_usd,
                last_payment,
            )
            .where(*conditions)
            # Most recently seen first: the profile cache is refreshed whenever the
            # user is observed, which makes this "who is around now" without a
            # second table to consult.
            .order_by(TgUser.updated_at.desc(), TgUser.tg_user_id.desc())
            .limit(min(limit, MAX_PAGE_SIZE))
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            PlatformUserRow(
                tg_user_id=user.tg_user_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                is_bot=user.is_bot,
                first_seen_at=user.created_at,
                last_seen_at=user.updated_at,
                admin_chats=_int(admins),
                owned_chats=_int(owned),
                is_globally_banned=bool(banned),
                ban_reports=_int(reports),
                payments=_int(payment_count),
                spent_stars=_int(stars),
                spent_usd=_money(usd),
                last_payment_at=paid_at,
            )
            for (
                user,
                admins,
                owned,
                banned,
                reports,
                payment_count,
                stars,
                usd,
                paid_at,
            ) in rows
        ], total

    async def user_chats(self, tg_user_id: int, *, limit: int = 50) -> list[Chat]:
        """Chats this user administers or owns — the console's user drawer."""
        stmt = (
            select(Chat)
            .outerjoin(AdminUser, AdminUser.chat_id == Chat.id)
            .where(
                or_(AdminUser.tg_user_id == tg_user_id, Chat.owner_tg_id == tg_user_id),
            )
            .distinct()
            .order_by(Chat.title)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # --- payments -------------------------------------------------------------
    async def payment_page(
        self,
        *,
        status: PaymentStatus | None = None,
        chat_id: int | None = None,
        tg_user_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PlatformPaymentRow], int]:
        """Newest payments first, joined to the chat they bought a plan for."""
        conditions: list[ColumnElement[bool]] = []
        if status is not None:
            conditions.append(Payment.status == status)
        if chat_id is not None:
            conditions.append(Payment.chat_id == chat_id)
        if tg_user_id is not None:
            conditions.append(Payment.payer_tg_id == tg_user_id)

        total = await self._scalar(select(func.count()).select_from(Payment).where(*conditions))
        stmt: Select[Any] = (
            select(Payment, Chat.title, Chat.tg_chat_id)
            .join(Chat, Chat.id == Payment.chat_id)
            .where(*conditions)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(min(limit, MAX_PAGE_SIZE))
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            PlatformPaymentRow(payment=payment, chat_title=title, tg_chat_id=int(tg_chat_id))
            for payment, title, tg_chat_id in rows
        ], total

    # --- helpers --------------------------------------------------------------
    async def _scalar(self, stmt: Select[tuple[int]]) -> int:
        return int((await self._session.execute(stmt)).scalar_one())

    @staticmethod
    def _paid() -> ColumnElement[bool]:
        return Payment.status == PaymentStatus.PAID

    @staticmethod
    def _refunded() -> ColumnElement[bool]:
        return Payment.status == PaymentStatus.REFUNDED

    @staticmethod
    def _count_if(condition: ColumnElement[bool]) -> ColumnElement[int]:
        return case((condition, 1), else_=0)

    @staticmethod
    def _amount_if(condition: ColumnElement[bool], *, stars: bool) -> ColumnElement[Decimal]:
        currency = (
            Payment.currency == STARS_CURRENCY if stars else Payment.currency != STARS_CURRENCY
        )
        return case((and_(condition, currency), Payment.amount), else_=0)

    @staticmethod
    def _is_banned() -> ColumnElement[bool]:
        return (
            exists()
            .where(
                and_(GlobalBan.tg_user_id == TgUser.tg_user_id, GlobalBan.is_active.is_(True)),
            )
            .correlate(TgUser)
        )

    @staticmethod
    def _user_conditions(
        *, search: str, banned_only: bool, admins_only: bool
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        term = search.strip().lstrip("@")
        if term:
            like = f"%{term.lower()}%"
            # Widened past the `.like()` seed elements so the numeric id branch
            # below can append its `==` comparison, which is a plain
            # `ColumnElement[bool]` rather than a `BinaryExpression`.
            matches: list[ColumnElement[bool]] = [
                func.lower(TgUser.username).like(like),
                func.lower(TgUser.first_name).like(like),
                func.lower(func.coalesce(TgUser.last_name, "")).like(like),
            ]
            # A numeric search is an id lookup as well as a name search: the
            # console's one search box is where an operator pastes a user id from
            # a support ticket.
            if term.lstrip("-").isdigit():
                matches.append(TgUser.tg_user_id == int(term))
            conditions.append(or_(*matches))
        if banned_only:
            conditions.append(PlatformRepository._is_banned())
        if admins_only:
            conditions.append(
                or_(
                    exists().where(AdminUser.tg_user_id == TgUser.tg_user_id).correlate(TgUser),
                    exists().where(Chat.owner_tg_id == TgUser.tg_user_id).correlate(TgUser),
                )
            )
        return conditions

    async def _activity_by_day(
        self, *, start: date, end: date
    ) -> dict[date, tuple[int, int, int, int, int]]:
        rows = (
            await self._session.execute(
                select(
                    StatDaily.date,
                    func.coalesce(func.sum(StatDaily.messages), 0),
                    func.coalesce(func.sum(StatDaily.moderation_actions), 0),
                    func.coalesce(func.sum(StatDaily.joins), 0),
                    func.coalesce(func.sum(StatDaily.leaves), 0),
                    func.count(func.distinct(case((StatDaily.messages > 0, StatDaily.chat_id)))),
                )
                .where(StatDaily.date >= start, StatDaily.date <= end)
                .group_by(StatDaily.date)
            )
        ).all()
        return {
            _as_date(day): (
                _int(messages),
                _int(moderation),
                _int(joins),
                _int(leaves),
                _int(active),
            )
            for day, messages, moderation, joins, leaves, active in rows
        }

    async def _signups_by_day(self, *, start: date, end: date) -> dict[date, int]:
        day = func.date(Chat.created_at)
        rows = (
            await self._session.execute(
                select(day, func.count()).where(day >= start, day <= end).group_by(day)
            )
        ).all()
        return {_as_date(created): _int(count) for created, count in rows}

    async def _money_by_day(
        self, *, start: date, end: date
    ) -> dict[date, tuple[int, int, Decimal]]:
        day = func.date(Payment.created_at)
        rows = (
            await self._session.execute(
                select(
                    day,
                    func.count(),
                    func.coalesce(func.sum(self._amount_if(self._paid(), stars=True)), 0),
                    func.coalesce(func.sum(self._amount_if(self._paid(), stars=False)), 0),
                )
                .where(self._paid(), day >= start, day <= end)
                .group_by(day)
            )
        ).all()
        return {
            _as_date(created): (_int(count), _int(stars), _money(usd))
            for created, count, stars, usd in rows
        }

    async def _refunds_by_day(self, *, start: date, end: date) -> dict[date, int]:
        """Counted on `refunded_at`: a June payment refunded in August is August's."""
        day = func.date(Payment.refunded_at)
        rows = (
            await self._session.execute(
                select(day, func.count())
                .where(Payment.refunded_at.is_not(None), day >= start, day <= end)
                .group_by(day)
            )
        ).all()
        return {_as_date(refunded): _int(count) for refunded, count in rows}

    async def _churn_by_day(self, *, start: date, end: date) -> dict[date, int]:
        """Chats whose *last* paid term ended on that day.

        A renewal moves `max(period_end)` forward, so a chat that kept paying can
        never appear: only the final term any chat bought is counted, and only if
        it ended inside the window. That makes today's number provisional — a chat
        that renews this afternoon leaves the count — which is the honest shape
        for churn and cheaper than maintaining a subscription-state table.
        """
        last_term = (
            select(Payment.chat_id, func.max(Payment.period_end).label("ends"))
            .where(self._paid(), Payment.period_end.is_not(None))
            .group_by(Payment.chat_id)
            .subquery()
        )
        day = func.date(last_term.c.ends)
        rows = (
            await self._session.execute(
                select(day, func.count()).where(day >= start, day <= end).group_by(day)
            )
        ).all()
        return {_as_date(ended): _int(count) for ended, count in rows}


class PlanOverrideRepository:
    """The operator's edits to plan prices and plan feature sets.

    Sparse by design: a NULL column means "whatever shipped", so an override of
    the price alone keeps tracking feature changes that arrive in a release.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[PlanOverride]:
        result = await self._session.execute(select(PlanOverride).order_by(PlanOverride.plan))
        return list(result.scalars().all())

    async def get(self, plan: Plan) -> PlanOverride | None:
        result = await self._session.execute(select(PlanOverride).where(PlanOverride.plan == plan))
        return result.scalar_one_or_none()

    async def save(
        self,
        plan: Plan,
        *,
        stars: int | None,
        usd: str | None,
        features: list[str] | None,
        updated_by: int | None,
        note: str = "",
    ) -> PlanOverride:
        """Replace the row for one plan, whole.

        DECISION: a full replace rather than a patch. The console always sends the
        complete picture it is showing, and a partial write would make "clear the
        price but keep the features" impossible to express — the two are told apart
        by NULL, which a patch cannot distinguish from "not mentioned".
        """
        row = await self.get(plan)
        if row is None:
            row = PlanOverride(plan=plan)
            self._session.add(row)
        row.stars = stars
        row.usd = usd
        row.features = features
        row.updated_by = updated_by
        row.note = note
        await self._session.flush()
        return row

    async def delete(self, plan: Plan) -> bool:
        row = await self.get(plan)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True


__all__ = [
    "MAX_PAGE_SIZE",
    "STARS_CURRENCY",
    "PlanOverrideRepository",
    "PlatformDay",
    "PlatformPaymentRow",
    "PlatformPlanRow",
    "PlatformRepository",
    "PlatformTotals",
    "PlatformUserRow",
]
