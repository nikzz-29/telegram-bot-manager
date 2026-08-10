"""Liveness, readiness and the platform catalog.

DECISION: `/meta` is derived from `core.registry` and `shared.plans` rather than
duplicated in the front-end. The Mini App renders its sections, icons, ordering
and paywall badges from this response, so adding a module or moving a feature
between plans is a Python-side change with no matching TypeScript edit.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from core import cache
from core.registry import registry
from i18n.runtime import SUPPORTED_LOCALES
from shared.config import get_settings
from shared.plans import PLAN_FEATURES, PLAN_LIMITS, PLAN_PRICES
from shared.schemas.api import CommandMeta, MetaResponse, ModuleMeta, PlanMeta

router = APIRouter(tags=["system"])


@router.get("/health", operation_id="health", summary="Liveness probe")
async def health() -> JSONResponse:
    """Always 200 while the process is up — no dependency is consulted.

    A liveness probe that fails when Redis is down would have the orchestrator
    restart a perfectly healthy API, which does not bring Redis back.
    """
    settings = get_settings()
    return JSONResponse(
        {"status": "ok", "service": "api", "environment": settings.app_env},
        status_code=status.HTTP_200_OK,
    )


@router.get("/ready", operation_id="ready", summary="Readiness probe")
async def ready() -> JSONResponse:
    """503 while a dependency the API cannot serve without is unreachable."""
    cache_ok = await cache.ping()
    payload = {"status": "ok" if cache_ok else "degraded", "cache": cache_ok}
    return JSONResponse(
        payload,
        status_code=status.HTTP_200_OK if cache_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@router.get(
    "/meta",
    response_model=MetaResponse,
    operation_id="getPlatformMeta",
    summary="Module catalog, plan matrix and shipped locales",
)
async def meta() -> MetaResponse:
    modules = [
        ModuleMeta(
            name=spec.name.value,
            title_key=spec.title_key,
            description_key=spec.description_key,
            required_plan=spec.required_plan,
            mandatory=spec.mandatory,
            enabled_by_default=spec.enabled_by_default,
            section_key=spec.miniapp_section.key if spec.miniapp_section else None,
            icon=spec.miniapp_section.icon if spec.miniapp_section else "settings",
            order=spec.miniapp_section.order if spec.miniapp_section else 100,
            commands=[
                CommandMeta(
                    name=command.name,
                    description_key=command.description_key,
                    admin_only=command.admin_only,
                )
                for command in spec.commands
            ],
            config_schema=spec.config_model.model_json_schema(),
        )
        for spec in registry
    ]
    plans = [
        PlanMeta(
            plan=plan,
            stars=PLAN_PRICES[plan].stars if plan in PLAN_PRICES else 0,
            usd=PLAN_PRICES[plan].usd if plan in PLAN_PRICES else "",
            features=sorted(feature.value for feature in features),
            limits={
                "triggers": PLAN_LIMITS[plan].triggers,
                "scheduled_posts": PLAN_LIMITS[plan].scheduled_posts,
                "stop_words": PLAN_LIMITS[plan].stop_words,
                "ai_checks_per_day": PLAN_LIMITS[plan].ai_checks_per_day,
                "stats_retention_days": PLAN_LIMITS[plan].stats_retention_days,
            },
        )
        for plan, features in PLAN_FEATURES.items()
    ]
    return MetaResponse(modules=modules, plans=plans, locales=list(SUPPORTED_LOCALES))


__all__ = ["router"]
