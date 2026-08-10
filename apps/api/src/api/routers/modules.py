"""Per-chat module settings — the Mini App's settings screens.

Every section of the panel (Moderation, Entry, Filters, …) is one module here.
Reads return the module's validated config with defaults filled in, so the panel
never has to know what a missing field means; writes go through
`ModuleConfigService`, which validates strictly, persists and invalidates.

DECISION: `PATCH` merges and `PUT` replaces, and the panel uses `PATCH`. A
settings screen submits the fields it renders; if that were a replace, a config
key added by a newer bot version — one the installed panel does not render yet —
would be silently wiped by the next save.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from api.deps import ChatAccessDep, ConfigsDep, FeaturesDep
from api.errors import problem_responses
from core.configs import InvalidModuleConfigError
from core.registry import registry
from shared.logging import get_logger
from shared.schemas.api import ModuleConfigResponse, ModuleConfigUpdate

logger = get_logger(__name__)

router = APIRouter(
    prefix="/chats/{chat_id}/modules",
    tags=["modules"],
    responses=problem_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_402_PAYMENT_REQUIRED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)


def _known_module(module: str) -> str:
    """Reject an unknown module name before it reaches the service layer."""
    if module not in registry.specs:
        raise InvalidModuleConfigError(f"Unknown module '{module}'.", module=module)
    return module


async def _render(
    *, chat_id: int, module: str, configs: ConfigsDep, features: FeaturesDep
) -> ModuleConfigResponse:
    spec = registry.get(module)
    unlocked = await features.features(chat_id)
    available = spec.feature in unlocked
    config = await configs.get(chat_id, module)
    return ModuleConfigResponse(
        module=module,
        # `is_enabled` folds in the plan gate; a Pro module on a downgraded chat
        # reads as off here while its stored settings stay untouched below.
        enabled=await configs.is_enabled(chat_id, module),
        required_plan=spec.required_plan,
        available=available,
        config=config.model_dump(mode="json"),
    )


@router.get(
    "",
    response_model=list[ModuleConfigResponse],
    operation_id="listModuleConfigs",
    summary="Every module's settings for one chat",
)
async def list_configs(
    access: ChatAccessDep, configs: ConfigsDep, features: FeaturesDep
) -> list[ModuleConfigResponse]:
    """One payload for the whole settings screen — locked modules included.

    Locked modules are returned rather than hidden: the panel renders them
    greyed out with the plan that unlocks them, which is the paywall.
    """
    return [
        await _render(
            chat_id=access.chat_id, module=spec.name.value, configs=configs, features=features
        )
        for spec in registry
    ]


@router.get(
    "/{module}",
    response_model=ModuleConfigResponse,
    operation_id="getModuleConfig",
    summary="One module's settings",
)
async def get_config(
    module: str, access: ChatAccessDep, configs: ConfigsDep, features: FeaturesDep
) -> ModuleConfigResponse:
    return await _render(
        chat_id=access.chat_id, module=_known_module(module), configs=configs, features=features
    )


@router.patch(
    "/{module}",
    response_model=ModuleConfigResponse,
    operation_id="patchModuleConfig",
    summary="Merge a partial settings update into a module",
)
async def patch_config(
    module: str,
    payload: ModuleConfigUpdate,
    access: ChatAccessDep,
    configs: ConfigsDep,
    features: FeaturesDep,
) -> ModuleConfigResponse:
    name = _known_module(module)
    spec = registry.get(name)
    # 402 rather than a silent no-op: the panel turns this into an upgrade prompt.
    await features.require(access.chat_id, spec.feature)

    if payload.config is not None:
        current = await configs.get(access.chat_id, name)
        merged = {**current.model_dump(mode="json"), **payload.config}
        await configs.save(access.chat_id, name, config=merged, enabled=payload.enabled)
    elif payload.enabled is not None:
        await configs.save(access.chat_id, name, enabled=payload.enabled)

    logger.info(
        "api.module_config_saved",
        chat_id=access.chat_id,
        module=name,
        enabled=payload.enabled,
        keys=sorted(payload.config or {}),
    )
    return await _render(chat_id=access.chat_id, module=name, configs=configs, features=features)


@router.put(
    "/{module}",
    response_model=ModuleConfigResponse,
    operation_id="replaceModuleConfig",
    summary="Replace a module's settings wholesale",
)
async def replace_config(
    module: str,
    payload: ModuleConfigUpdate,
    access: ChatAccessDep,
    configs: ConfigsDep,
    features: FeaturesDep,
) -> ModuleConfigResponse:
    name = _known_module(module)
    spec = registry.get(name)
    await features.require(access.chat_id, spec.feature)
    await configs.save(access.chat_id, name, config=payload.config or {}, enabled=payload.enabled)
    logger.info("api.module_config_replaced", chat_id=access.chat_id, module=name)
    return await _render(chat_id=access.chat_id, module=name, configs=configs, features=features)


@router.post(
    "/{module}/reset",
    response_model=ModuleConfigResponse,
    operation_id="resetModuleConfig",
    summary="Restore a module's default settings",
)
async def reset_config(
    module: str, access: ChatAccessDep, configs: ConfigsDep, features: FeaturesDep
) -> ModuleConfigResponse:
    name = _known_module(module)
    spec = registry.get(name)
    await features.require(access.chat_id, spec.feature)
    await configs.save(access.chat_id, name, config=spec.default_config())
    logger.info("api.module_config_reset", chat_id=access.chat_id, module=name)
    return await _render(chat_id=access.chat_id, module=name, configs=configs, features=features)


__all__ = ["router"]
