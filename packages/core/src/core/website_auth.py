"""Helpers for one-time credentials issued to the standalone website."""

from __future__ import annotations

from hashlib import sha256
import secrets
from urllib.parse import urlsplit, urlunsplit

WEBSITE_SCOPE = "website"


def generate_token() -> str:
    """Return an unguessable token suitable for a one-time login URL."""
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """Hash a token before it crosses the persistence boundary."""
    return sha256(token.encode("utf-8")).hexdigest()


def website_login_url(base_url: str, token: str) -> str | None:
    """Attach a login token to a configured website URL's fragment.

    A fragment is intentionally used because browsers do not send it to the
    server in the initial request, keeping the raw credential out of access logs.
    """
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, f"token={token}"))


__all__ = ["WEBSITE_SCOPE", "generate_token", "token_digest", "website_login_url"]
