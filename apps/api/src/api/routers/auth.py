"""Session endpoints: trade `initData` for a JWT, then renew the JWT.

DECISION: `initData` is exchanged once per panel session and renewal goes through
`/auth/refresh`. Telegram's string is single-use (see `core.webapp`), so a client
that re-posted it on every token expiry would lock itself out — the refresh route
is what makes single use practical rather than hostile.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, status

from api.deps import PrincipalDep, SettingsDep, UowDep
from api.errors import problem_responses
from api.security import Principal, issue_token
from core.webapp import verify_init_data
from core.website_auth import WEBSITE_SCOPE, token_digest
from shared.errors import InvalidSessionError
from shared.logging import get_logger
from shared.schemas.api import AuthRequest, AuthResponse, AuthUser, WebsiteLoginRequest

logger = get_logger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    responses=problem_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)


@router.post(
    "/telegram",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    operation_id="authenticateWithTelegram",
    summary="Exchange Telegram initData for an API session token",
)
async def authenticate(payload: AuthRequest, settings: SettingsDep, uow: UowDep) -> AuthResponse:
    identity = await verify_init_data(payload.init_data, token=settings.bot_token)
    principal = Principal.from_identity(identity)

    # The profile cache is what lets the Mini App and the log channel print a
    # name instead of a numeric id; the panel is the one place we reliably see
    # a fresh one for the *admin* rather than for a chat member.
    await uow.users.upsert(
        tg_user_id=identity.tg_user_id,
        username=identity.username,
        first_name=identity.first_name,
        last_name=identity.last_name,
        language_code=identity.language_code or None,
        has_photo=bool(identity.photo_url),
    )
    await uow.commit()

    token, expires_in = issue_token(principal)
    logger.info("api.auth_ok", user_id=principal.tg_user_id, superadmin=principal.is_superadmin)
    return AuthResponse(access_token=token, expires_in=expires_in, user=principal.to_schema())


@router.post(
    "/website",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    operation_id="authenticateWithWebsiteToken",
    summary="Exchange a single-use bot-issued website token for a session",
)
async def authenticate_website(
    payload: WebsiteLoginRequest, settings: SettingsDep, uow: UowDep
) -> AuthResponse:
    digest = token_digest(payload.token)
    user_id = await uow.website_tokens.consume(
        token_hash=digest, scope=WEBSITE_SCOPE, now=datetime.now(UTC)
    )
    if user_id is None:
        raise InvalidSessionError("Website login key is invalid or expired.")
    profile = await uow.users.get(user_id)
    if profile is None:
        raise InvalidSessionError("Telegram profile is no longer available.")
    principal = Principal(
        tg_user_id=profile.tg_user_id,
        username=profile.username,
        first_name=profile.first_name,
        last_name=profile.last_name,
        language=profile.language_code or "en",
        is_superadmin=profile.tg_user_id in settings.superadmin_id_list,
    )
    token, expires_in = issue_token(principal)
    return AuthResponse(access_token=token, expires_in=expires_in, user=principal.to_schema())


@router.post(
    "/refresh",
    response_model=AuthResponse,
    operation_id="refreshSession",
    summary="Renew a session token that has not expired yet",
)
async def refresh(principal: PrincipalDep) -> AuthResponse:
    token, expires_in = issue_token(principal)
    return AuthResponse(access_token=token, expires_in=expires_in, user=principal.to_schema())


@router.get(
    "/me",
    response_model=AuthUser,
    operation_id="getCurrentUser",
    summary="The caller behind the current session token",
)
async def me(principal: PrincipalDep) -> AuthUser:
    return principal.to_schema()


__all__ = ["router"]
