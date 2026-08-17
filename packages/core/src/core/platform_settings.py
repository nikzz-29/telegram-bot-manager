"""Load persistent operator settings into the process configuration."""

from __future__ import annotations

from db.uow import UnitOfWork
from shared.config import get_settings
from shared.logging import get_logger

CRYPTOBOT_TESTNET_KEY = "cryptobot_testnet"

logger = get_logger(__name__)


async def load_platform_settings() -> None:
    settings = get_settings()
    async with UnitOfWork() as uow:
        row = await uow.platform_settings.get(CRYPTOBOT_TESTNET_KEY)

    if row is None:
        return
    enabled = row.value.get("enabled") is True
    if enabled and settings.is_production:
        logger.error("platform.testnet_override_refused_in_production")
        settings.cryptobot_testnet = False
        return
    settings.cryptobot_testnet = enabled
    logger.info("platform.settings_loaded", cryptobot_testnet=enabled)


__all__ = ["CRYPTOBOT_TESTNET_KEY", "load_platform_settings"]
