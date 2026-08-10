"""Module registry — the plugin seam for every bot feature.

A module is metadata (`ModuleSpec`) plus, at runtime, an aiogram router. The
metadata is what the API serves to the Mini App to draw its sections and paywall
badges; the router is attached by the bot process only.

DECISION: `Router` is imported under TYPE_CHECKING and attached through
`attach_router()` rather than being a field on `ModuleSpec`. That keeps the
registry importable by the API and worker without pulling aiogram's dispatcher
machinery into a process that never dispatches an update.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from shared.enums import ModuleName, Plan, plan_rank
from shared.plans import Feature, minimum_plan_for
from shared.schemas.module_configs import CONFIG_MODELS, ModuleConfig

if TYPE_CHECKING:  # pragma: no cover
    from aiogram import Router


@dataclass(frozen=True, slots=True)
class BotCommandSpec:
    """One chat command, surfaced in Telegram's command menu and in /help."""

    name: str
    description_key: str
    admin_only: bool = True


@dataclass(frozen=True, slots=True)
class MiniAppSection:
    """A settings page in the Mini App."""

    key: str
    title_key: str
    icon: str = "settings"
    order: int = 100


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """Everything the platform needs to know about a module without loading it."""

    name: ModuleName
    feature: Feature
    config_model: type[ModuleConfig]
    title_key: str
    description_key: str
    commands: tuple[BotCommandSpec, ...] = ()
    miniapp_section: MiniAppSection | None = None
    enabled_by_default: bool = False
    # Modules the user cannot switch off (moderation is the product's floor).
    mandatory: bool = False

    @property
    def required_plan(self) -> Plan:
        """Derived from the feature matrix so a plan change never needs two edits."""
        return minimum_plan_for(self.feature)

    def default_config(self) -> ModuleConfig:
        return self.config_model()


class BotModule(Protocol):
    """Runtime shape of a module living in the bot process."""

    spec: ModuleSpec

    def build_router(self) -> Router: ...


MODULE_SPECS: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        name=ModuleName.MODERATION,
        feature=Feature.MODERATION,
        config_model=CONFIG_MODELS["moderation"],
        title_key="module-moderation-title",
        description_key="module-moderation-description",
        commands=(
            BotCommandSpec("warn", "cmd-warn"),
            BotCommandSpec("unwarn", "cmd-unwarn"),
            BotCommandSpec("warns", "cmd-warns", admin_only=False),
            BotCommandSpec("mute", "cmd-mute"),
            BotCommandSpec("unmute", "cmd-unmute"),
            BotCommandSpec("ban", "cmd-ban"),
            BotCommandSpec("unban", "cmd-unban"),
            BotCommandSpec("kick", "cmd-kick"),
            BotCommandSpec("del", "cmd-del"),
            BotCommandSpec("ro", "cmd-ro"),
        ),
        miniapp_section=MiniAppSection("moderation", "section-moderation", "shield", 10),
        enabled_by_default=True,
        mandatory=True,
    ),
    ModuleSpec(
        name=ModuleName.ENTRY,
        feature=Feature.CAPTCHA,
        config_model=CONFIG_MODELS["entry"],
        title_key="module-entry-title",
        description_key="module-entry-description",
        commands=(BotCommandSpec("lockdown", "cmd-lockdown"),),
        miniapp_section=MiniAppSection("entry", "section-entry", "door", 20),
        enabled_by_default=True,
    ),
    ModuleSpec(
        name=ModuleName.STATS,
        feature=Feature.STATS,
        config_model=CONFIG_MODELS["stats"],
        title_key="module-stats-title",
        description_key="module-stats-description",
        commands=(BotCommandSpec("stats", "cmd-stats"),),
        miniapp_section=MiniAppSection("stats", "section-stats", "chart", 30),
    ),
    ModuleSpec(
        name=ModuleName.ENGAGEMENT,
        feature=Feature.TRIGGERS,
        config_model=CONFIG_MODELS["engagement"],
        title_key="module-engagement-title",
        description_key="module-engagement-description",
        commands=(
            BotCommandSpec("addtrigger", "cmd-addtrigger"),
            BotCommandSpec("deltrigger", "cmd-deltrigger"),
            BotCommandSpec("triggers", "cmd-triggers"),
            BotCommandSpec("rep", "cmd-rep", admin_only=False),
            BotCommandSpec("top", "cmd-top", admin_only=False),
        ),
        miniapp_section=MiniAppSection("engagement", "section-engagement", "spark", 40),
    ),
    ModuleSpec(
        name=ModuleName.AUTOPOST,
        feature=Feature.AUTOPOST,
        config_model=CONFIG_MODELS["autopost"],
        title_key="module-autopost-title",
        description_key="module-autopost-description",
        commands=(
            BotCommandSpec("posts", "cmd-posts"),
            BotCommandSpec("postpause", "cmd-postpause"),
            BotCommandSpec("postresume", "cmd-postresume"),
        ),
        miniapp_section=MiniAppSection("autopost", "section-autopost", "clock", 50),
    ),
    ModuleSpec(
        name=ModuleName.AI_MODERATION,
        feature=Feature.AI_MODERATION,
        config_model=CONFIG_MODELS["ai_moderation"],
        title_key="module-ai-title",
        description_key="module-ai-description",
        miniapp_section=MiniAppSection("ai_moderation", "section-ai", "sparkles", 60),
    ),
    ModuleSpec(
        name=ModuleName.CROSSBAN,
        feature=Feature.CROSSBAN,
        config_model=CONFIG_MODELS["crossban"],
        title_key="module-crossban-title",
        description_key="module-crossban-description",
        commands=(BotCommandSpec("gban", "cmd-gban"),),
        miniapp_section=MiniAppSection("crossban", "section-crossban", "globe", 70),
    ),
)

SPEC_BY_NAME: dict[str, ModuleSpec] = {spec.name.value: spec for spec in MODULE_SPECS}


@dataclass(slots=True)
class ModuleRegistry:
    """Holds module metadata and, in the bot process, their routers."""

    specs: dict[str, ModuleSpec] = field(default_factory=lambda: dict(SPEC_BY_NAME))
    _routers: dict[str, Router] = field(default_factory=dict, repr=False)

    def register(self, spec: ModuleSpec) -> None:
        if spec.name.value in self.specs:
            raise ValueError(f"Module '{spec.name.value}' is already registered.")
        self.specs[spec.name.value] = spec

    def attach_router(self, name: str | ModuleName, router: Router) -> None:
        key = name.value if isinstance(name, ModuleName) else name
        if key not in self.specs:
            raise KeyError(f"Unknown module '{key}'.")
        self._routers[key] = router

    def router_for(self, name: str | ModuleName) -> Router | None:
        key = name.value if isinstance(name, ModuleName) else name
        return self._routers.get(key)

    def routers(self) -> tuple[Router, ...]:
        """Routers in module declaration order, so dispatch order is deterministic."""
        return tuple(self._routers[name] for name in self.specs if name in self._routers)

    def get(self, name: str | ModuleName) -> ModuleSpec:
        key = name.value if isinstance(name, ModuleName) else name
        return self.specs[key]

    def all(self) -> tuple[ModuleSpec, ...]:
        return tuple(self.specs.values())

    def available_for_plan(self, plan: Plan) -> tuple[ModuleSpec, ...]:
        rank = plan_rank(plan)
        return tuple(spec for spec in self.specs.values() if plan_rank(spec.required_plan) <= rank)

    def locked_for_plan(self, plan: Plan) -> tuple[ModuleSpec, ...]:
        rank = plan_rank(plan)
        return tuple(spec for spec in self.specs.values() if plan_rank(spec.required_plan) > rank)

    def default_enabled(self) -> tuple[ModuleSpec, ...]:
        return tuple(spec for spec in self.specs.values() if spec.enabled_by_default)

    def commands_for_plan(self, plan: Plan) -> tuple[BotCommandSpec, ...]:
        return tuple(command for spec in self.available_for_plan(plan) for command in spec.commands)

    def __iter__(self) -> Iterator[ModuleSpec]:
        return iter(self.specs.values())

    def __len__(self) -> int:
        return len(self.specs)


registry = ModuleRegistry()

__all__ = [
    "MODULE_SPECS",
    "SPEC_BY_NAME",
    "BotCommandSpec",
    "BotModule",
    "MiniAppSection",
    "ModuleRegistry",
    "ModuleSpec",
    "registry",
]
