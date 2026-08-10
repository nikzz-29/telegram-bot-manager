"""ChatContext — the resolved tenant state for one update.

The ChatContext middleware builds this once per update and injects it into every
handler, so a handler answers "is this chat on Pro?", "is anti-flood on?" and
"what language do I reply in?" with no awaits and no extra queries.

DECISION: the context is a frozen snapshot. An update is processed against the
state that was true when it arrived; a settings change mid-update does not
half-apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

from core.configs import ModuleConfigService
from core.configs import module_configs as default_configs
from core.features import (
    FeatureService,
    effective_plan,
    in_grace_period,
)
from core.features import (
    features as default_features,
)
from core.registry import ModuleRegistry
from core.registry import registry as default_registry
from db.uow import UnitOfWork
from shared.enums import ModuleName, Plan, plan_rank
from shared.errors import FeatureLockedError
from shared.plans import Feature, PlanLimits, limits_for_plan, minimum_plan_for
from shared.schemas.module_configs import EntryConfig, ModerationConfig, ModuleConfig
from shared.time_utils import utc_now

ConfigT = TypeVar("ConfigT", bound=ModuleConfig)

DEFAULT_LANGUAGE = "ru"


@dataclass(frozen=True, slots=True)
class ChatContext:
    """Everything a handler needs to know about the chat it is serving."""

    chat_id: int
    tg_chat_id: int
    title: str
    plan: Plan
    features: frozenset[Feature]
    enabled_modules: frozenset[str]
    language: str = DEFAULT_LANGUAGE
    timezone: str = "UTC"
    is_active: bool = True
    lockdown_until: datetime | None = None
    in_grace: bool = False
    plan_expires_at: datetime | None = None
    moderation: ModerationConfig = field(default_factory=ModerationConfig)
    entry: EntryConfig = field(default_factory=EntryConfig)

    # --- synchronous gates ----------------------------------------------------
    def has(self, feature: Feature) -> bool:
        return feature in self.features

    def require(self, feature: Feature) -> None:
        if feature not in self.features:
            raise FeatureLockedError(
                f"Feature '{feature.value}' requires the {minimum_plan_for(feature).value} plan.",
                feature=feature.value,
                required_plan=minimum_plan_for(feature).value,
            )

    def module_enabled(self, module: str | ModuleName) -> bool:
        key = module.value if isinstance(module, ModuleName) else module
        return key in self.enabled_modules

    def at_least(self, plan: Plan) -> bool:
        return plan_rank(self.plan) >= plan_rank(plan)

    @property
    def is_paid(self) -> bool:
        return self.plan != Plan.FREE

    @property
    def limits(self) -> PlanLimits:
        return limits_for_plan(self.plan)

    def is_locked_down(self, *, now: datetime | None = None) -> bool:
        """Anti-raid lockdown: new members are rejected until this passes."""
        if self.lockdown_until is None:
            return False
        return self.lockdown_until > (now or utc_now())

    def log_fields(self) -> dict[str, Any]:
        """Structlog binding for this chat."""
        return {
            "chat_id": self.chat_id,
            "tg_chat_id": self.tg_chat_id,
            "plan": self.plan.value,
        }


class ChatContextResolver:
    """Builds `ChatContext` objects, reading through the cache where possible."""

    def __init__(
        self,
        *,
        uow_factory: type[UnitOfWork] | None = None,
        features: FeatureService | None = None,
        configs: ModuleConfigService | None = None,
        registry: ModuleRegistry | None = None,
    ) -> None:
        self._uow_factory = uow_factory or UnitOfWork
        self._features = features or default_features
        self._configs = configs or default_configs
        self._registry = registry or default_registry

    async def resolve(
        self,
        tg_chat_id: int,
        *,
        title: str = "",
        chat_type: str | None = None,
        owner_tg_id: int | None = None,
    ) -> ChatContext:
        """Resolve (and register on first sight) a chat by its Telegram id."""
        async with self._uow_factory() as uow:
            chat = await uow.chats.get_by_tg_id(tg_chat_id)
            created = chat is None
            if chat is None:
                chat = await uow.chats.get_or_create(
                    tg_chat_id, title=title, owner_tg_id=owner_tg_id
                )
            await uow.commit()
            chat_id = chat.id
            plan = effective_plan(chat)
            grace = in_grace_period(chat)
            language = chat.language or DEFAULT_LANGUAGE
            timezone = chat.timezone or "UTC"
            is_active = chat.is_active
            lockdown_until = chat.lockdown_until
            plan_expires_at = chat.plan_expires_at
            resolved_title = chat.title or title

        if created:
            await self._configs.ensure_defaults(chat_id)

        return await self.for_chat_id(
            chat_id,
            tg_chat_id=tg_chat_id,
            title=resolved_title,
            plan=plan,
            language=language,
            timezone=timezone,
            is_active=is_active,
            lockdown_until=lockdown_until,
            in_grace=grace,
            plan_expires_at=plan_expires_at,
        )

    async def for_chat_id(
        self,
        chat_id: int,
        *,
        tg_chat_id: int | None = None,
        title: str = "",
        plan: Plan | None = None,
        language: str | None = None,
        timezone: str | None = None,
        is_active: bool = True,
        lockdown_until: datetime | None = None,
        in_grace: bool = False,
        plan_expires_at: datetime | None = None,
    ) -> ChatContext:
        """Build a context for an already-known internal chat id.

        Used by the API (which authenticates against internal ids) and by worker
        jobs, which hold a chat id but no Telegram update.
        """
        if tg_chat_id is None or plan is None:
            async with self._uow_factory() as uow:
                chat = await uow.chats.get_by_id(chat_id)
                if chat is None:
                    raise ValueError(f"Unknown chat id {chat_id}")
                tg_chat_id = chat.tg_chat_id
                plan = effective_plan(chat)
                in_grace = in_grace_period(chat)
                title = chat.title or title
                language = language or chat.language
                timezone = timezone or chat.timezone
                is_active = chat.is_active
                lockdown_until = chat.lockdown_until
                plan_expires_at = chat.plan_expires_at

        resolved_features = await self._features.features(chat_id)
        enabled = await self._configs.enabled_modules(chat_id)
        moderation = await self._configs.get_as(chat_id, ModuleName.MODERATION, ModerationConfig)
        entry = await self._configs.get_as(chat_id, ModuleName.ENTRY, EntryConfig)

        return ChatContext(
            chat_id=chat_id,
            tg_chat_id=tg_chat_id,
            title=title,
            plan=plan,
            features=resolved_features,
            enabled_modules=enabled,
            language=language or DEFAULT_LANGUAGE,
            timezone=timezone or "UTC",
            is_active=is_active,
            lockdown_until=lockdown_until,
            in_grace=in_grace,
            plan_expires_at=plan_expires_at,
            moderation=moderation,
            entry=entry,
        )

    async def config(
        self, ctx: ChatContext, module: str | ModuleName, model: type[ConfigT]
    ) -> ConfigT:
        """Fetch a config the context does not carry eagerly (stats, autopost, AI)."""
        return await self._configs.get_as(ctx.chat_id, module, model)


chat_context = ChatContextResolver()

__all__ = [
    "DEFAULT_LANGUAGE",
    "ChatContext",
    "ChatContextResolver",
    "chat_context",
]
