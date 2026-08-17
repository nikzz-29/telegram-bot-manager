"""Install persisted plan overrides into the process-wide effective catalogue."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from db.uow import UnitOfWork
from shared.enums import Plan
from shared.logging import get_logger
from shared.plans import (
    DEFAULT_PLAN_FEATURES,
    DEFAULT_PLAN_PRICES,
    Feature,
    PlanPrice,
    install_plan_overrides,
)

logger = get_logger(__name__)


class PlanOverrideRow(Protocol):
    plan: Plan
    features: list[str] | None
    stars: int | None
    usd: str | None


def install_plan_override_rows(rows: Sequence[PlanOverrideRow]) -> None:
    """Resolve sparse rows over shipped defaults and install the result."""
    features = dict(DEFAULT_PLAN_FEATURES)
    prices = dict(DEFAULT_PLAN_PRICES)

    for row in rows:
        plan = Plan(row.plan)
        if row.features is not None:
            try:
                features[plan] = frozenset(Feature(value) for value in row.features)
            except ValueError as error:
                logger.error(
                    "plans.invalid_feature_override",
                    plan=plan.value,
                    error=str(error),
                )

        if row.stars is not None or row.usd is not None:
            default = DEFAULT_PLAN_PRICES.get(plan, PlanPrice(stars=0, usd=""))
            prices[plan] = PlanPrice(
                stars=row.stars if row.stars is not None else default.stars,
                usd=row.usd if row.usd is not None else default.usd,
            )

    install_plan_overrides(features=features, prices=prices)
    logger.info("plans.overrides_loaded", count=len(rows))


async def load_plan_overrides() -> None:
    """Load persisted overrides into the process-wide effective catalogue."""
    async with UnitOfWork() as uow:
        rows = await uow.plan_overrides.list_all()
    install_plan_override_rows(rows)


__all__ = ["install_plan_override_rows", "load_plan_overrides"]
