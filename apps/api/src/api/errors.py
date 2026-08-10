"""One place where an exception becomes a response body.

Spec §9: domain exceptions turn into an RFC7807-like JSON document. Routers
therefore raise `DomainError` subclasses and never build an error response
themselves.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from api.deps import get_translator
from shared.errors import DomainError
from shared.logging import get_logger
from shared.schemas.api import Problem

logger = get_logger(__name__)

PROBLEM_BASE = "https://tg-bot-manager.dev/problems"
PROBLEM_MEDIA_TYPE = "application/problem+json"

# Generic failures still need a localized title; these are their i18n keys.
_STATUS_KEYS: dict[int, str] = {
    status.HTTP_401_UNAUTHORIZED: "error-invalid-session",
    status.HTTP_403_FORBIDDEN: "error-not-admin",
    status.HTTP_404_NOT_FOUND: "error-not-found",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "error-invalid-request",
}

# Prose for the OpenAPI document, so the generated client documents its own
# failure modes; the human-facing text is the localized `title` instead.
_STATUS_DESCRIPTIONS: dict[int, str] = {
    status.HTTP_401_UNAUTHORIZED: "Session token missing, malformed or expired.",
    status.HTTP_402_PAYMENT_REQUIRED: "The chat's plan does not include this feature.",
    status.HTTP_404_NOT_FOUND: "No such chat, or the caller does not administer it.",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "Request failed validation.",
}


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Declare `Problem` as the error body for `statuses`, for OpenAPI.

    DECISION: routers list their failure statuses so the schema carries `Problem`.
    The generated TypeScript client then types the error branch instead of
    handing the panel an `unknown`, which is the whole point of generating it.
    """
    return {
        code: {
            "model": Problem,
            "description": _STATUS_DESCRIPTIONS.get(code, "Request failed."),
        }
        for code in statuses
    }


_OPERATIONS = frozenset({"get", "put", "post", "delete", "patch", "options", "head", "trace"})


def use_problem_media_type(app: FastAPI) -> None:
    """File the error bodies under the media type they are really sent with.

    DECISION: FastAPI records a `responses={..., "model": Problem}` entry under the
    route's *success* media type, so the document would promise `application/json`
    while `_problem_response` sends `application/problem+json`. Renaming the key
    after the fact keeps one accurate entry per status; declaring `content`
    ourselves alongside `model` would leave both, which is worse than either.
    """
    problem_ref = "#/components/schemas/Problem"

    def openapi() -> dict[str, Any]:
        schema = original()
        for path_item in schema.get("paths", {}).values():
            for method, operation in path_item.items():
                if method not in _OPERATIONS:
                    continue
                for response in operation.get("responses", {}).values():
                    content = response.get("content", {})
                    body = content.get("application/json")
                    if body and body.get("schema", {}).get("$ref") == problem_ref:
                        # Idempotent: the second call finds no `application/json`
                        # left to move, and FastAPI hands back its cached document.
                        content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")
        return schema

    original = app.openapi
    app.openapi = openapi  # type: ignore[method-assign]


def _problem_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    i18n_key: str,
    detail: str = "",
    context: dict[str, Any] | None = None,
) -> JSONResponse:
    problem = Problem(
        type=f"{PROBLEM_BASE}/{code}",
        # DECISION: `title` is localized and `detail` is not. The Mini App shows
        # the title to a human; the detail goes to logs and to a developer
        # console, where a translated string would only slow diagnosis down.
        title=get_translator(request)(i18n_key),
        status=status_code,
        detail=detail,
        instance=request.url.path,
        code=code,
        context=context or {},
    )
    return JSONResponse(
        problem.model_dump(mode="json"),
        status_code=status_code,
        media_type=PROBLEM_MEDIA_TYPE,
    )


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error = exc if isinstance(exc, DomainError) else DomainError(str(exc))
    logger.info(
        "api.domain_error",
        code=error.code,
        status=error.http_status,
        path=request.url.path,
        detail=error.message,
    )
    return _problem_response(
        request,
        status_code=error.http_status,
        code=error.code,
        i18n_key=error.i18n_key,
        detail=error.message,
        context=error.context,
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Pydantic rejected the request body or query.

    The per-field errors ride in `context.errors` so the Mini App can highlight
    the offending input instead of showing one opaque banner.
    """
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    return _problem_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="invalid-request",
        i18n_key="error-invalid-request",
        detail="Request validation failed.",
        context={"errors": [dict(item) for item in errors]},
    )


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Starlette's own 404s and 405s, rendered in the same shape as ours."""
    error = exc if isinstance(exc, HTTPException) else HTTPException(500, str(exc))
    key = _STATUS_KEYS.get(error.status_code, "error-generic")
    return _problem_response(
        request,
        status_code=error.status_code,
        code=f"http-{error.status_code}",
        i18n_key=key,
        detail=str(error.detail),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Anything we did not anticipate: log it fully, tell the caller nothing.

    A stack trace or a driver message in the response body is a gift to whoever
    is probing the API; the correlation is kept in the log instead.
    """
    logger.exception("api.unhandled_error", path=request.url.path, error=str(exc))
    return _problem_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal-error",
        i18n_key="error-server",
        detail="Internal server error.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)


__all__ = [
    "PROBLEM_BASE",
    "PROBLEM_MEDIA_TYPE",
    "domain_error_handler",
    "http_error_handler",
    "problem_responses",
    "register_exception_handlers",
    "unhandled_error_handler",
    "use_problem_media_type",
    "validation_error_handler",
]
