"""FastAPI dependencies: request session, session token, chat authorization.

Everything a router needs to know about *who is calling* and *what they may
touch* is resolved here, so a handler body is only ever domain work.

DECISION: services are injected through dependencies (`get_admin_service`, …)
rather than imported into the routers. They are process-wide singletons in
production, but going through the dependency graph means a test can swap the
Telegram-facing ones for fakes without touching the module it is testing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from api.security import Principal, decode_token
from core.admins import AdminService
from core.admins import admins as admin_service
from core.configs import ModuleConfigService
from core.configs import module_configs as module_config_service
from core.features import FeatureService
from core.features import features as feature_service
from db.base import get_session_factory
from db.models import Chat
from db.uow import UnitOfWork
from i18n.runtime import Translator, normalize_locale, translator
from shared.config import Settings, get_settings
from shared.errors import ChatNotFoundError, InvalidSessionError, NotChatAdminError

# `auto_error=False`: a missing header must surface as our own `Problem` body,
# not as FastAPI's bare `{"detail": "Not authenticated"}`.
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="TelegramSession")


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """One session per request, committed on success and rolled back on error."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_uow(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UnitOfWork:
    """Repositories over the request session; the request owns the transaction."""
    return UnitOfWork.from_session(session)


def get_admin_service() -> AdminService:
    return admin_service


def get_module_configs() -> ModuleConfigService:
    return module_config_service


def get_features() -> FeatureService:
    return feature_service


def get_app_settings() -> Settings:
    return get_settings()


SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
UowDep = Annotated[UnitOfWork, Depends(get_uow)]
AdminsDep = Annotated[AdminService, Depends(get_admin_service)]
ConfigsDep = Annotated[ModuleConfigService, Depends(get_module_configs)]
FeaturesDep = Annotated[FeatureService, Depends(get_features)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    """The caller behind the `Authorization: Bearer <jwt>` header."""
    if credentials is None or not credentials.credentials:
        raise InvalidSessionError("Authorization header is missing.")
    return decode_token(credentials.credentials)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def get_translator(request: Request) -> Translator:
    """Locale for error copy: the caller's session language, then the header.

    Chat-scoped replies use the chat's own `language`; this is only for messages
    addressed to the person holding the panel, who may not share it.
    """
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        return translator(principal.language)
    header = request.headers.get("accept-language", "")
    return translator(normalize_locale(header.split(",")[0].strip() or None))


@dataclass(frozen=True, slots=True)
class ChatAccess:
    """A chat the caller has been proven to administer."""

    chat: Chat
    principal: Principal

    @property
    def chat_id(self) -> int:
        return self.chat.id

    @property
    def tg_chat_id(self) -> int:
        return self.chat.tg_chat_id


async def require_chat_access(
    request: Request,
    chat_id: Annotated[int, Path(ge=1)],
    principal: PrincipalDep,
    uow: UowDep,
    admins: AdminsDep,
) -> ChatAccess:
    """Load the chat and prove the caller administers it — reads included.

    DECISION: reads are gated too, not just writes. A chat's stop-word list and
    log-channel id are moderation intelligence; handing them to any authenticated
    Telegram user because the endpoint "only reads" would leak them platform-wide.

    DECISION: an unknown chat and a chat the caller cannot see both answer 404.
    A 403 here would confirm that a given `chat_id` exists on the platform, which
    is enumerable in a way 404 is not.
    """
    chat = await uow.chats.get_by_id(chat_id)
    if chat is None or not chat.is_active:
        raise ChatNotFoundError("Chat is not connected.", chat_id=chat_id)
    if not await admins.is_admin(chat.tg_chat_id, principal.tg_user_id):
        raise ChatNotFoundError("Chat is not connected.", chat_id=chat_id)
    request.state.principal = principal
    return ChatAccess(chat=chat, principal=principal)


ChatAccessDep = Annotated[ChatAccess, Depends(require_chat_access)]


async def require_superadmin(principal: PrincipalDep) -> Principal:
    """Platform-operator endpoints (Stage 6) hang off this."""
    if not principal.is_superadmin:
        raise NotChatAdminError("Platform operator rights are required.")
    return principal


SuperadminDep = Annotated[Principal, Depends(require_superadmin)]

__all__ = [
    "AdminsDep",
    "ChatAccess",
    "ChatAccessDep",
    "ConfigsDep",
    "FeaturesDep",
    "PrincipalDep",
    "SessionDep",
    "SettingsDep",
    "SuperadminDep",
    "UowDep",
    "bearer_scheme",
    "get_admin_service",
    "get_app_settings",
    "get_db_session",
    "get_features",
    "get_module_configs",
    "get_principal",
    "get_translator",
    "get_uow",
    "require_chat_access",
    "require_superadmin",
]
