"""Telegram Mini App `initData`: signature, freshness and replay.

The Mini App hands the API the raw `initData` query string it was launched with.
Everything the API believes about the caller comes from that one string, so it is
verified here and nowhere else.

DECISION: the HMAC is computed here rather than delegated to
`aiogram.utils.web_app.check_webapp_signature`. Bot API 8.0 added a `signature`
field (Ed25519, for third-party validation) whose participation in the
bot-token hash the docs do not spell out. We accept a hash over every field
except `hash`, and — only if that fails — over every field except `hash` and
`signature`. Forging `signature` alone buys an attacker nothing: we never read
it, and every field we do read stays covered by the HMAC either way.

DECISION: `initData` is single-use. The string is constant for the lifetime of a
Mini App session, so a leaked one would otherwise mint API sessions for the full
24 h Telegram allows. Legitimate clients never need it twice — they renew
through `POST /auth/refresh` with the JWT they already hold — and a client that
does lose its token reopens the panel, which is what `error-invalid-init-data`
already tells the user to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from typing import Any, Final
from urllib.parse import parse_qsl

from redis.exceptions import RedisError

from core.redis_client import get_redis
from shared.config import get_settings
from shared.errors import InvalidInitDataError
from shared.logging import get_logger
from shared.time_utils import utc, utc_now

logger = get_logger(__name__)

# Telegram's fixed HMAC salt for WebApp payloads.
WEBAPP_SALT: Final = b"WebAppData"
NONCE_PREFIX: Final = "tgm:initdata"
# `auth_date` comes from Telegram's clock, not ours; a minute of skew is normal.
CLOCK_SKEW: Final = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class WebAppIdentity:
    """The verified caller behind an `initData` string."""

    tg_user_id: int
    username: str | None
    first_name: str
    last_name: str | None
    language_code: str
    is_premium: bool
    is_bot: bool
    auth_date: datetime
    # The `hash` field itself — unique per Mini App session, so it doubles as the
    # replay nonce without us having to invent one.
    fingerprint: str


def _secret_key(token: str) -> bytes:
    return hmac.new(WEBAPP_SALT, token.encode(), hashlib.sha256).digest()


def _data_check_string(fields: dict[str, str], *, drop: frozenset[str]) -> str:
    return "\n".join(f"{key}={value}" for key, value in sorted(fields.items()) if key not in drop)


def _digest(fields: dict[str, str], *, token: str, drop: frozenset[str]) -> str:
    return hmac.new(
        _secret_key(token),
        _data_check_string(fields, drop=drop).encode(),
        hashlib.sha256,
    ).hexdigest()


def _fields(init_data: str) -> dict[str, str]:
    try:
        pairs = parse_qsl(init_data, strict_parsing=True, keep_blank_values=True)
    except ValueError as exc:
        raise InvalidInitDataError("initData is not a valid query string.") from exc
    return dict(pairs)


def check_signature(init_data: str, *, token: str) -> bool:
    """True when `init_data` carries a valid bot-token HMAC. Pure, no I/O."""
    fields = _fields(init_data)
    supplied = fields.get("hash")
    if not supplied:
        return False
    for drop in (frozenset({"hash"}), frozenset({"hash", "signature"})):
        if hmac.compare_digest(_digest(fields, token=token, drop=drop), supplied):
            return True
    return False


def parse_identity(init_data: str) -> WebAppIdentity:
    """Read the caller out of `init_data`. Does **not** verify anything."""
    fields = _fields(init_data)
    raw_user = fields.get("user")
    if not raw_user:
        # Launched from a keyboard button rather than a chat: no user, no session.
        raise InvalidInitDataError("initData carries no user.")
    try:
        user: Any = json.loads(raw_user)
        auth_date = datetime.fromtimestamp(int(fields["auth_date"]), tz=UTC)
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidInitDataError("initData is malformed.") from exc
    if not isinstance(user, dict) or "id" not in user:
        raise InvalidInitDataError("initData user object is malformed.")

    return WebAppIdentity(
        tg_user_id=int(user["id"]),
        username=user.get("username"),
        first_name=str(user.get("first_name", "")),
        last_name=user.get("last_name"),
        language_code=str(user.get("language_code") or ""),
        is_premium=bool(user.get("is_premium", False)),
        is_bot=bool(user.get("is_bot", False)),
        auth_date=auth_date,
        fingerprint=fields.get("hash", ""),
    )


async def _claim_nonce(fingerprint: str, *, expires_in: int) -> bool:
    """Reserve an `initData` fingerprint. False means it was already used.

    DECISION: a Redis outage degrades to signature+freshness rather than locking
    every admin out of their own panel. That is the guarantee Telegram itself
    documents as sufficient, and the cache being down already means the API is
    running on one engine.
    """
    try:
        claimed = await get_redis().set(
            f"{NONCE_PREFIX}:{fingerprint}", b"1", nx=True, ex=max(expires_in, 1)
        )
    except RedisError as exc:
        logger.warning("webapp.replay_guard_unavailable", error=str(exc))
        return True
    return bool(claimed)


async def verify_init_data(
    init_data: str,
    *,
    token: str | None = None,
    now: datetime | None = None,
    ttl: timedelta | None = None,
    single_use: bool = True,
) -> WebAppIdentity:
    """Verify signature, freshness and single use, then return the caller.

    Raises:
        InvalidInitDataError: signature mismatch, expired `auth_date`, a replayed
            string, or a payload we cannot read.
    """
    settings = get_settings()
    secret = token or settings.bot_token
    if not secret:
        # A deployment without a token cannot verify anything; that is ours to
        # fix, not the caller's, so it must not read as a failed login.
        raise RuntimeError("BOT_TOKEN is required to verify Mini App initData.")

    if not check_signature(init_data, token=secret):
        raise InvalidInitDataError("initData signature does not match.")

    identity = parse_identity(init_data)
    if identity.is_bot:
        raise InvalidInitDataError("Bots cannot open the admin panel.")

    lifetime = ttl or timedelta(seconds=settings.init_data_ttl_seconds)
    moment = now or utc_now()
    age = moment - utc(identity.auth_date)
    if age > lifetime:
        raise InvalidInitDataError(
            "initData has expired.", auth_date=identity.auth_date.isoformat()
        )
    if age < -CLOCK_SKEW:
        raise InvalidInitDataError(
            "initData is dated in the future.", auth_date=identity.auth_date.isoformat()
        )

    if single_use and not await _claim_nonce(
        identity.fingerprint, expires_in=int((lifetime - age).total_seconds())
    ):
        raise InvalidInitDataError("initData has already been used.")
    return identity


__all__ = [
    "CLOCK_SKEW",
    "WEBAPP_SALT",
    "WebAppIdentity",
    "check_signature",
    "parse_identity",
    "verify_init_data",
]
