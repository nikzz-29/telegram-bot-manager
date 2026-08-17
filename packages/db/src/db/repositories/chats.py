"""Chat and module-config repositories."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    AdminUser,
    AiCheckLog,
    CaptchaChallenge,
    Chat,
    ChatModuleConfig,
    GlobalBanReport,
    ModerationLog,
    Payment,
    Punishment,
    Reputation,
    ScheduledPost,
    StatDaily,
    StatEvent,
    StatUserDaily,
    TriggerRule,
    Warn,
)
from shared.enums import ChatType, Plan, plan_rank


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, chat_id: int) -> Chat | None:
        return await self._session.get(Chat, chat_id)

    async def get_by_tg_id(self, tg_chat_id: int) -> Chat | None:
        result = await self._session.execute(select(Chat).where(Chat.tg_chat_id == tg_chat_id))
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        tg_chat_id: int,
        *,
        title: str = "",
        chat_type: ChatType = ChatType.SUPERGROUP,
        owner_tg_id: int | None = None,
        username: str | None = None,
    ) -> Chat:
        """Upsert on tg_chat_id so concurrent updates cannot create duplicates."""
        stmt = (
            pg_insert(Chat)
            .values(
                tg_chat_id=tg_chat_id,
                title=title,
                type=chat_type,
                owner_tg_id=owner_tg_id,
                username=username,
                plan=Plan.FREE,
                settings={},
            )
            .on_conflict_do_update(
                index_elements=[Chat.tg_chat_id],
                set_={"title": title, "updated_at": func.now()},
            )
            .returning(Chat)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def migrate_tg_id(
        self,
        old_tg_chat_id: int,
        new_tg_chat_id: int,
        *,
        title: str = "",
        chat_type: ChatType = ChatType.SUPERGROUP,
        username: str | None = None,
    ) -> tuple[Chat | None, int | None]:
        """Move a Telegram chat to its post-migration id without duplicating it.

        Telegram sends ``migrate_to_chat_id`` when a basic group becomes a
        supergroup, followed by ``migrate_from_chat_id`` updates on the new
        chat.  Both updates can race with normal messages, so the two rows are
        locked in id order and all child records are moved in one transaction.
        The returned second value is the removed internal chat id, if a
        pre-existing duplicate had to be merged.
        """
        if old_tg_chat_id == new_tg_chat_id:
            return await self.get_by_tg_id(new_tg_chat_id), None

        rows = list(
            (
                await self._session.execute(
                    select(Chat)
                    .where(Chat.tg_chat_id.in_([old_tg_chat_id, new_tg_chat_id]))
                    .order_by(Chat.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        by_tg_id = {row.tg_chat_id: row for row in rows}
        old_chat = by_tg_id.get(old_tg_chat_id)
        new_chat = by_tg_id.get(new_tg_chat_id)

        if old_chat is None:
            # The new update may arrive first.  There is no safe row to merge;
            # the next update will still resolve the already-known new chat.
            return new_chat, None
        if new_chat is None:
            await self._session.execute(
                update(Chat)
                .where(Chat.id == old_chat.id)
                .values(
                    tg_chat_id=new_tg_chat_id,
                    title=title or old_chat.title,
                    username=username,
                    type=chat_type,
                    updated_at=func.now(),
                )
            )
            await self._session.flush()
            return old_chat, None

        # Keep the original internal id.  The second row is normally the one
        # created by a race before the migration service message was consumed.
        await self._merge_children(old_chat.id, new_chat.id)

        # Prefer the row with the richer subscription and preserve explicit
        # settings from the original row while accepting newer metadata.
        old_chat.plan = (
            old_chat.plan if plan_rank(old_chat.plan) >= plan_rank(new_chat.plan) else new_chat.plan
        )
        if old_chat.plan_expires_at is None or (
            new_chat.plan_expires_at is not None
            and new_chat.plan_expires_at > old_chat.plan_expires_at
        ):
            old_chat.plan_expires_at = new_chat.plan_expires_at
        if old_chat.grace_until is None or (
            new_chat.grace_until is not None and new_chat.grace_until > old_chat.grace_until
        ):
            old_chat.grace_until = new_chat.grace_until
        old_chat.settings = {**dict(new_chat.settings), **dict(old_chat.settings)}
        old_chat.title = title or new_chat.title or old_chat.title
        old_chat.username = username or new_chat.username
        old_chat.type = chat_type
        old_chat.is_active = old_chat.is_active or new_chat.is_active
        old_chat.owner_tg_id = old_chat.owner_tg_id or new_chat.owner_tg_id
        old_chat.members_count = old_chat.members_count or new_chat.members_count
        old_chat.joined_at = min(old_chat.joined_at, new_chat.joined_at)
        await self._session.execute(delete(Chat).where(Chat.id == new_chat.id))
        await self._session.flush()
        old_chat.tg_chat_id = new_tg_chat_id
        await self._session.flush()
        return old_chat, new_chat.id

    async def _merge_children(self, target_id: int, source_id: int) -> None:
        """Merge child rows, resolving each table's natural unique key."""
        # Additive rollups must be combined before conflicting source rows are
        # removed.  JSON metrics are intentionally shallow-merged; named source
        # keys are retained when the target has no value for them.
        await self._session.execute(
            text(
                """
                UPDATE stat_daily AS target
                SET messages = target.messages + source.messages,
                    active_users = target.active_users + source.active_users,
                    joins = target.joins + source.joins,
                    leaves = target.leaves + source.leaves,
                    moderation_actions = target.moderation_actions + source.moderation_actions,
                    metrics = source.metrics || target.metrics
                FROM stat_daily AS source
                WHERE target.chat_id = :target AND source.chat_id = :source
                  AND target.date = source.date
                """
            ),
            {"target": target_id, "source": source_id},
        )
        await self._session.execute(
            text(
                """
                UPDATE stat_user_daily AS target
                SET messages = target.messages + source.messages
                FROM stat_user_daily AS source
                WHERE target.chat_id = :target AND source.chat_id = :source
                  AND target.date = source.date AND target.tg_user_id = source.tg_user_id
                """
            ),
            {"target": target_id, "source": source_id},
        )
        await self._session.execute(
            text(
                """
                UPDATE reputations AS target
                SET points = target.points + source.points,
                    experience = target.experience + source.experience,
                    level = GREATEST(target.level, source.level),
                    weekly_points = target.weekly_points + source.weekly_points,
                    monthly_points = target.monthly_points + source.monthly_points
                FROM reputations AS source
                WHERE target.chat_id = :target AND source.chat_id = :source
                  AND target.tg_user_id = source.tg_user_id
                """
            ),
            {"target": target_id, "source": source_id},
        )

        # For configuration/state tables the original row wins.  Deleting only
        # conflicting source rows lets the remaining rows be moved with a
        # single UPDATE and keeps all foreign keys intact.
        unique_tables = (
            (AdminUser, "tg_user_id"),
            (ChatModuleConfig, "module"),
            (CaptchaChallenge, "tg_user_id"),
            (StatDaily, "date"),
            (StatUserDaily, "date, tg_user_id"),
            (Reputation, "tg_user_id"),
            (GlobalBanReport, "tg_user_id"),
        )
        for unique_model, key_columns in unique_tables:
            keys = [column.strip() for column in key_columns.split(",")]
            predicates = " AND ".join(f"target.{column} = source.{column}" for column in keys)
            await self._session.execute(
                text(
                    f"""
                    DELETE FROM {unique_model.__tablename__} AS source
                    USING {unique_model.__tablename__} AS target
                    WHERE source.chat_id = :source AND target.chat_id = :target
                      AND {predicates}
                    """
                ),
                {"target": target_id, "source": source_id},
            )

        for child_model in (
            AdminUser,
            ChatModuleConfig,
            Warn,
            Punishment,
            CaptchaChallenge,
            TriggerRule,
            ScheduledPost,
            StatEvent,
            StatDaily,
            StatUserDaily,
            Reputation,
            GlobalBanReport,
            Payment,
            AiCheckLog,
            ModerationLog,
        ):
            await self._session.execute(
                update(child_model)
                .where(child_model.chat_id == source_id)
                .values(chat_id=target_id)
            )

    async def list_for_admin(self, tg_user_id: int) -> list[Chat]:
        """Chats where the user is a recorded admin or the owner."""
        from db.models import AdminUser  # local import avoids a cycle at module load

        stmt: Select[tuple[Chat]] = (
            select(Chat)
            .outerjoin(AdminUser, AdminUser.chat_id == Chat.id)
            .where(
                Chat.is_active.is_(True),
                (AdminUser.tg_user_id == tg_user_id) | (Chat.owner_tg_id == tg_user_id),
            )
            .distinct()
            .order_by(Chat.title)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[Chat]:
        result = await self._session.execute(
            select(Chat).order_by(Chat.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_ids(self, chat_ids: list[int]) -> list[Chat]:
        """Batch fetch for cron fan-out — one query, not one per chat."""
        if not chat_ids:
            return []
        result = await self._session.execute(select(Chat).where(Chat.id.in_(chat_ids)))
        return list(result.scalars().all())

    async def list_by_plans(self, plans: list[Plan]) -> list[Chat]:
        result = await self._session.execute(
            select(Chat).where(Chat.plan.in_(plans), Chat.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def count_by_plan(self) -> dict[str, int]:
        result = await self._session.execute(select(Chat.plan, func.count()).group_by(Chat.plan))
        return {str(plan): count for plan, count in result.all()}

    async def count(self, *, active_only: bool = False) -> int:
        stmt = select(func.count()).select_from(Chat)
        if active_only:
            stmt = stmt.where(Chat.is_active.is_(True))
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def set_plan(
        self,
        chat_id: int,
        plan: Plan,
        *,
        expires_at: datetime | None,
        grace_until: datetime | None = None,
    ) -> None:
        await self._session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(plan=plan, plan_expires_at=expires_at, grace_until=grace_until)
        )

    async def set_active(self, chat_id: int, *, is_active: bool) -> None:
        await self._session.execute(
            update(Chat).where(Chat.id == chat_id).values(is_active=is_active)
        )

    async def update_fields(self, chat_id: int, **fields: Any) -> None:
        if not fields:
            return
        await self._session.execute(update(Chat).where(Chat.id == chat_id).values(**fields))

    async def set_lockdown(self, chat_id: int, until: datetime | None) -> None:
        await self._session.execute(
            update(Chat).where(Chat.id == chat_id).values(lockdown_until=until)
        )

    async def find_expiring(self, before: datetime) -> list[Chat]:
        """Paid chats whose subscription ends before `before` (reminder cron)."""
        result = await self._session.execute(
            select(Chat).where(
                Chat.plan != Plan.FREE,
                Chat.plan_expires_at.is_not(None),
                Chat.plan_expires_at <= before,
            )
        )
        return list(result.scalars().all())


class ModuleConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_chat(self, chat_id: int) -> list[ChatModuleConfig]:
        result = await self._session.execute(
            select(ChatModuleConfig).where(ChatModuleConfig.chat_id == chat_id)
        )
        return list(result.scalars().all())

    async def get(self, chat_id: int, module: str) -> ChatModuleConfig | None:
        result = await self._session.execute(
            select(ChatModuleConfig).where(
                ChatModuleConfig.chat_id == chat_id, ChatModuleConfig.module == module
            )
        )
        return result.scalar_one_or_none()

    async def get_many(self, chat_ids: list[int], module: str) -> dict[int, ChatModuleConfig]:
        """One module's rows for many chats, keyed by chat id (cron fan-out)."""
        if not chat_ids:
            return {}
        result = await self._session.execute(
            select(ChatModuleConfig).where(
                ChatModuleConfig.chat_id.in_(chat_ids), ChatModuleConfig.module == module
            )
        )
        return {row.chat_id: row for row in result.scalars().all()}

    async def upsert(
        self,
        chat_id: int,
        module: str,
        *,
        enabled: bool | None = None,
        config: dict[str, Any] | None = None,
    ) -> ChatModuleConfig:
        """Insert or patch a module config, touching only supplied fields."""
        values: dict[str, Any] = {
            "chat_id": chat_id,
            "module": module,
            "enabled": enabled if enabled is not None else False,
            "config": config if config is not None else {},
        }
        updates: dict[str, Any] = {"updated_at": func.now()}
        if enabled is not None:
            updates["enabled"] = enabled
        if config is not None:
            updates["config"] = config

        stmt = (
            pg_insert(ChatModuleConfig)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[ChatModuleConfig.chat_id, ChatModuleConfig.module],
                set_=updates,
            )
            .returning(ChatModuleConfig)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def set_enabled_bulk(self, chat_id: int, modules: list[str], *, enabled: bool) -> None:
        if not modules:
            return
        await self._session.execute(
            update(ChatModuleConfig)
            .where(ChatModuleConfig.chat_id == chat_id, ChatModuleConfig.module.in_(modules))
            .values(enabled=enabled)
        )

    async def list_enabled_chats(self, module: str) -> list[int]:
        """Chat ids with this module switched on (used by cron fan-out)."""
        result = await self._session.execute(
            select(ChatModuleConfig.chat_id).where(
                ChatModuleConfig.module == module, ChatModuleConfig.enabled.is_(True)
            )
        )
        return list(result.scalars().all())
