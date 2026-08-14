"""API session tokens.

The Mini App trades a verified `initData` string for a short-lived JWT once, then
carries that token on every later request. Telegram's own credential is therefore
touched exactly once per panel session — see `core.webapp` for why that matters.

DECISION: HS256 with the shared `JWT_SECRET`. The only issuer and the only
verifier are this service, so an asymmetric key would add key distribution
without adding a party that needs it.

DECISION: no server-side session store. The token is short-lived (default 1 h)
and carries nothing but identity — every authorization decision is re-made per
request against `getChatMember`, so a revoked admin loses access within the
5-minute admin cache regardless of how long their token lives.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final
import uuid

import jwt

from core.webapp import WebAppIdentity
from i18n.runtime import normalize_locale
from shared.config import get_settings
from shared.errors import InvalidSessionError
from shared.schemas.api import AuthUser
from shared.time_utils import utc_now

ALGORITHM: Final = "HS256"
ISSUER: Final = "tg-bot-manager"
AUDIENCE: Final = "tg-bot-manager-miniapp"


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller, rebuilt from a token on every request."""

    tg_user_id: int
    username: str | None = None
    first_name: str = ""
    last_name: str | None = None
    language: str = "en"
    is_superadmin: bool = False
    is_premium: bool = False
    photo_url: str | None = None

    @classmethod
    def from_identity(cls, identity: WebAppIdentity) -> Principal:
        settings = get_settings()
        return cls(
            tg_user_id=identity.tg_user_id,
            username=identity.username,
            first_name=identity.first_name,
            last_name=identity.last_name,
            language=normalize_locale(identity.language_code),
            is_superadmin=identity.tg_user_id in settings.superadmin_id_list,
            is_premium=identity.is_premium,
            photo_url=identity.photo_url,
        )

    def to_schema(self) -> AuthUser:
        return AuthUser(
            tg_user_id=self.tg_user_id,
            username=self.username,
            first_name=self.first_name,
            last_name=self.last_name,
            language_code=self.language,
            is_superadmin=self.is_superadmin,
            is_premium=self.is_premium,
            has_photo=bool(self.photo_url),
            photo_url=self.photo_url,
        )


def issue_token(
    principal: Principal, *, now: datetime | None = None, ttl: timedelta | None = None
) -> tuple[str, int]:
    """Sign a session token. Returns `(token, expires_in_seconds)`."""
    settings = get_settings()
    lifetime = ttl or timedelta(seconds=settings.jwt_ttl_seconds)
    issued_at = now or utc_now()
    expires_at = issued_at + lifetime
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(principal.tg_user_id),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
        "username": principal.username,
        "first_name": principal.first_name,
        "last_name": principal.last_name,
        "lang": principal.language,
        "sa": principal.is_superadmin,
        "premium": principal.is_premium,
        "photo": principal.photo_url,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
    return token, int(lifetime.total_seconds())


def decode_token(token: str) -> Principal:
    """Verify a session token and rebuild its principal.

    Raises:
        InvalidSessionError: the token is expired, tampered with, or was issued
            for a different service.
    """
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidSessionError("Session token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise InvalidSessionError("Session token is not valid.") from exc

    try:
        tg_user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidSessionError("Session token has no usable subject.") from exc

    # DECISION: `is_superadmin` is re-derived from settings rather than trusted
    # from the token. Removing an id from `SUPERADMIN_IDS` has to take effect on
    # the next request, not whenever the last issued token happens to expire.
    return Principal(
        tg_user_id=tg_user_id,
        username=payload.get("username"),
        first_name=str(payload.get("first_name") or ""),
        last_name=payload.get("last_name"),
        language=normalize_locale(payload.get("lang")),
        is_superadmin=tg_user_id in settings.superadmin_id_list,
        is_premium=bool(payload.get("premium", False)),
        photo_url=payload.get("photo"),
    )


__all__ = [
    "ALGORITHM",
    "AUDIENCE",
    "ISSUER",
    "Principal",
    "decode_token",
    "issue_token",
]
