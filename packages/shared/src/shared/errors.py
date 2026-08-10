"""Domain error hierarchy.

Bot handlers translate these into localized chat replies; the API exception
handler turns them into RFC7807-like JSON. Every error carries a stable
``code`` (used as the RFC7807 ``type`` suffix) and an ``i18n_key`` so the bot
can render the message in the chat language.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base error for expected domain failures."""

    code = "domain-error"
    i18n_key = "error-generic"
    http_status = 400

    def __init__(self, message: str = "", **context: Any) -> None:
        super().__init__(message or self.__class__.__doc__ or self.code)
        self.context: dict[str, Any] = context

    @property
    def message(self) -> str:
        return str(self)


class InvalidDurationError(DomainError):
    """Duration must use the format 30m, 2h, 7d or 1w."""

    code = "invalid-duration"
    i18n_key = "error-invalid-duration"
    http_status = 422


class WarnNotFoundError(DomainError):
    """No active warn to remove."""

    code = "warn-not-found"
    i18n_key = "error-warn-not-found"
    http_status = 404


class ChatNotFoundError(DomainError):
    """Chat is not connected to the bot."""

    code = "chat-not-found"
    i18n_key = "error-chat-not-found"
    http_status = 404


class ResourceNotFoundError(DomainError):
    """A chat-scoped row (trigger, post, …) does not exist under this chat.

    Deliberately the same answer as "exists, but belongs to another chat": the
    repositories filter by `chat_id`, so an id from a neighbouring chat is
    indistinguishable from one that was never created.
    """

    code = "not-found"
    i18n_key = "error-not-found"
    http_status = 404


class NotChatAdminError(DomainError):
    """User is not an administrator of this chat."""

    code = "not-chat-admin"
    i18n_key = "error-not-admin"
    http_status = 403


class FeatureLockedError(DomainError):
    """Feature requires a higher plan."""

    code = "feature-locked"
    i18n_key = "error-feature-locked"
    http_status = 402


class LimitExceededError(DomainError):
    """Plan limit for this resource is exhausted."""

    code = "limit-exceeded"
    i18n_key = "error-limit-exceeded"
    http_status = 409


class InvalidInitDataError(DomainError):
    """Telegram initData signature is missing, malformed or expired."""

    code = "invalid-init-data"
    i18n_key = "error-invalid-init-data"
    http_status = 401


class InvalidSessionError(DomainError):
    """API session token is missing, malformed or expired."""

    code = "invalid-session"
    i18n_key = "error-invalid-session"
    http_status = 401


class InvalidTimezoneError(DomainError):
    """Timezone must be a valid IANA name such as Europe/Moscow."""

    code = "invalid-timezone"
    i18n_key = "error-invalid-timezone"
    http_status = 422


class InvalidPatternError(DomainError):
    """Trigger pattern is not a usable regular expression."""

    code = "invalid-pattern"
    i18n_key = "error-invalid-pattern"
    http_status = 422


class InvalidScheduleError(DomainError):
    """Post schedule is not valid."""

    code = "invalid-schedule"
    i18n_key = "error-invalid-schedule"
    http_status = 422


class TargetNotFoundError(DomainError):
    """Moderation target could not be resolved from the message."""

    code = "target-not-found"
    i18n_key = "error-target-not-found"
    http_status = 404


class SelfActionError(DomainError):
    """Moderators cannot apply this action to themselves or to the bot."""

    code = "self-action"
    i18n_key = "error-self-action"
    http_status = 409


class ProviderUnavailableError(DomainError):
    """External provider is unavailable; the caller should degrade gracefully."""

    code = "provider-unavailable"
    i18n_key = "error-provider-unavailable"
    http_status = 503


class PaymentError(DomainError):
    """Payment could not be processed."""

    code = "payment-error"
    i18n_key = "error-payment"
    http_status = 402
