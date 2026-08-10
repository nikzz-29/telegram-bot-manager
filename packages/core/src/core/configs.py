"""Per-chat module configuration: read, validate, write, invalidate.

Configs are stored as JSONB and validated through the Pydantic models in
`shared.schemas.module_configs`, so a chat row with `{}` is always valid and new
options ship without a migration.

DECISION: a plan downgrade never deletes a config row. `is_enabled()` returns
False for a module the current plan does not cover, but the stored settings stay
untouched so re-subscribing restores the chat exactly as it was.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import ValidationError

from core import cache
from core.features import FeatureService
from core.features import features as default_features
from core.registry import ModuleRegistry, ModuleSpec
from core.registry import registry as default_registry
from db.uow import UnitOfWork
from shared.enums import ModuleName
from shared.errors import DomainError
from shared.plans import Feature
from shared.schemas.module_configs import ModuleConfig

ConfigT = TypeVar("ConfigT", bound=ModuleConfig)


class InvalidModuleConfigError(DomainError):
    """Submitted module settings failed validation."""

    code = "invalid-module-config"
    i18n_key = "error-invalid-config"
    http_status = 422


def _module_key(module: str | ModuleName) -> str:
    return module.value if isinstance(module, ModuleName) else module


class ModuleConfigService:
    """Cached accessor for `chat_module_configs` rows."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], UnitOfWork] | None = None,
        registry: ModuleRegistry | None = None,
        features: FeatureService | None = None,
    ) -> None:
        self._uow_factory = uow_factory or UnitOfWork
        self._registry = registry or default_registry
        self._features = features or default_features

    # --- reads ----------------------------------------------------------------
    async def _raw(self, chat_id: int, module: str) -> dict[str, Any]:
        """`{"enabled": bool, "config": dict}` for one module, cached."""
        key = cache.module_config_key(chat_id, module)
        cached = await cache.get_value(key)
        if isinstance(cached, dict):
            return cached

        spec = self._registry.specs.get(module)
        async with self._uow_factory() as uow:
            row = await uow.module_configs.get(chat_id, module)
        payload: dict[str, Any] = (
            {"enabled": row.enabled, "config": dict(row.config)}
            if row is not None
            else {
                "enabled": bool(spec.enabled_by_default) if spec else False,
                "config": {},
            }
        )
        await cache.set_value(
            key, payload, ttl=cache.TTL_MODULE_CONFIG, tags=(cache.chat_tag(chat_id),)
        )
        return payload

    async def get(self, chat_id: int, module: str | ModuleName) -> ModuleConfig:
        """Validated config for a module, with model defaults filled in."""
        name = _module_key(module)
        spec = self._registry.get(name)
        raw = await self._raw(chat_id, name)
        return self._validate(spec, raw["config"])

    async def get_as(self, chat_id: int, module: str | ModuleName, model: type[ConfigT]) -> ConfigT:
        """Same as `get`, typed to a concrete config model for call-site inference."""
        name = _module_key(module)
        raw = await self._raw(chat_id, name)
        try:
            return model.model_validate(raw["config"])
        except ValidationError:
            # DECISION: a config that no longer validates (option removed, value
            # out of a tightened range) must not take the module down — fall back
            # to defaults and let the admin re-save from the Mini App.
            return model()

    async def is_enabled(self, chat_id: int, module: str | ModuleName) -> bool:
        """Enabled in the DB *and* unlocked by the current plan."""
        name = _module_key(module)
        spec = self._registry.specs.get(name)
        if spec is None:
            return False
        if not await self._features.has(chat_id, spec.feature):
            return False
        if spec.mandatory:
            return True
        raw = await self._raw(chat_id, name)
        return bool(raw["enabled"])

    async def enabled_modules(self, chat_id: int) -> frozenset[str]:
        """All modules active for a chat right now — one cached set per chat."""
        key = cache.enabled_modules_key(chat_id)
        cached = await cache.get_value(key)
        if isinstance(cached, list):
            return frozenset(str(item) for item in cached)

        plan_features = await self._features.features(chat_id)
        async with self._uow_factory() as uow:
            rows = await uow.module_configs.list_for_chat(chat_id)
        stored = {row.module: row.enabled for row in rows}

        active = {
            spec.name.value
            for spec in self._registry
            if spec.feature in plan_features
            and (spec.mandatory or stored.get(spec.name.value, spec.enabled_by_default))
        }
        await cache.set_value(
            key,
            sorted(active),
            ttl=cache.TTL_MODULE_CONFIG,
            tags=(cache.chat_tag(chat_id),),
        )
        return frozenset(active)

    async def all_configs(self, chat_id: int) -> dict[str, ModuleConfig]:
        """Every module's validated config — the Mini App's settings payload."""
        async with self._uow_factory() as uow:
            rows = await uow.module_configs.list_for_chat(chat_id)
        stored = {row.module: dict(row.config) for row in rows}
        return {
            spec.name.value: self._validate(spec, stored.get(spec.name.value, {}))
            for spec in self._registry
        }

    # --- writes ---------------------------------------------------------------
    async def save(
        self,
        chat_id: int,
        module: str | ModuleName,
        *,
        config: dict[str, Any] | ModuleConfig | None = None,
        enabled: bool | None = None,
        require_feature: bool = True,
    ) -> ModuleConfig:
        """Validate and persist a module config, then invalidate its caches."""
        name = _module_key(module)
        spec = self._registry.get(name)
        if require_feature:
            await self._features.require(chat_id, spec.feature)
        if enabled is False and spec.mandatory:
            raise InvalidModuleConfigError(f"Module '{name}' cannot be disabled.", module=name)

        validated: ModuleConfig | None = None
        payload: dict[str, Any] | None = None
        if config is not None:
            validated = (
                config
                if isinstance(config, ModuleConfig)
                else self._validate(spec, config, strict=True)
            )
            payload = validated.model_dump(mode="json")

        async with self._uow_factory() as uow:
            await uow.module_configs.upsert(chat_id, name, enabled=enabled, config=payload)
            await uow.commit()

        await cache.invalidate_module_config(chat_id, name)
        return validated if validated is not None else await self.get(chat_id, name)

    async def patch(
        self, chat_id: int, module: str | ModuleName, changes: dict[str, Any]
    ) -> ModuleConfig:
        """Merge a partial update into the stored config (Mini App PATCH)."""
        name = _module_key(module)
        current = await self.get(chat_id, name)
        merged = {**current.model_dump(mode="json"), **changes}
        return await self.save(chat_id, name, config=merged)

    async def ensure_defaults(self, chat_id: int) -> None:
        """Create rows for default-on modules when a chat first connects."""
        async with self._uow_factory() as uow:
            existing = {row.module for row in await uow.module_configs.list_for_chat(chat_id)}
            for spec in self._registry.default_enabled():
                if spec.name.value not in existing:
                    await uow.module_configs.upsert(
                        chat_id,
                        spec.name.value,
                        enabled=True,
                        config=spec.default_config().model_dump(mode="json"),
                    )
            await uow.commit()
        await cache.invalidate_chat(chat_id)

    async def disable_locked_modules(self, chat_id: int) -> list[str]:
        """After a downgrade: switch off modules the new plan cannot run.

        Only the `enabled` flag moves; configs are preserved for re-subscription.
        """
        plan_features: frozenset[Feature] = await self._features.features(chat_id)
        locked = [spec.name.value for spec in self._registry if spec.feature not in plan_features]
        if locked:
            async with self._uow_factory() as uow:
                await uow.module_configs.set_enabled_bulk(chat_id, locked, enabled=False)
                await uow.commit()
        await cache.invalidate_chat(chat_id)
        return locked

    # --- helpers --------------------------------------------------------------
    @staticmethod
    def _validate(spec: ModuleSpec, raw: dict[str, Any], *, strict: bool = False) -> ModuleConfig:
        try:
            return spec.config_model.model_validate(raw)
        except ValidationError as exc:
            if strict:
                raise InvalidModuleConfigError(
                    f"Invalid settings for '{spec.name.value}'.",
                    module=spec.name.value,
                    errors=exc.errors(include_url=False),
                ) from exc
            return spec.config_model()


module_configs = ModuleConfigService()

__all__ = [
    "InvalidModuleConfigError",
    "ModuleConfigService",
    "module_configs",
]
