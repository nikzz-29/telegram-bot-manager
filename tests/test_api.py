"""Stage 3: initData verification, session tokens and the HTTP surface.

Three layers, deliberately kept apart:

* `core.webapp` — pure crypto and freshness rules, plus the replay guard against
  a fake Redis. The spec names `initData` validation as critical logic, so it is
  tested directly rather than only through an endpoint.
* `api.security` — the JWT round trip and everything that must *not* be trusted
  from a token.
* the routers — driven over real HTTP through `ASGITransport`, with the
  Telegram-facing and database-facing dependencies swapped for fakes. No
  Postgres, no Redis, no Bot API: those belong to the integration suite.

DECISION: the signature helper here re-derives the HMAC instead of importing
`core.webapp._digest`, and one test cross-checks our string against aiogram's
independent implementation. A test that calls the function under test to build
its own fixture proves only that the function is self-consistent.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import urlencode

from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
import httpx
import jwt
from pydantic import ValidationError
import pytest

from api.app import create_app
from api.deps import (
    get_admin_service,
    get_app_settings,
    get_features,
    get_module_configs,
    get_uow,
)
from api.routers import system as system_router
from api.security import AUDIENCE, ISSUER, Principal, decode_token, issue_token
from core import cache
from core.admins import BotPermissionSnapshot
from core.configs import InvalidModuleConfigError
from core.redis_client import set_redis
from core.registry import registry
from core.webapp import (
    CLOCK_SKEW,
    check_signature,
    parse_identity,
    verify_init_data,
)
from db.models import Chat, TgUser
from shared.config import PLACEHOLDER_JWT_SECRET, Settings, get_settings
from shared.enums import ChatType, Plan
from shared.errors import FeatureLockedError, InvalidInitDataError, InvalidSessionError
from shared.plans import PLAN_FEATURES, Feature, minimum_plan_for

# Structurally valid, never issued: `hmac` does not care and neither does BotFather.
FAKE_TOKEN = "123456:AAHfake-token-for-tests-only-not-a-real-secret"
NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
USER_ID = 7_654_321
CHAT_ID = 1
TG_CHAT_ID = -1001999888777

USER = {
    "id": USER_ID,
    "first_name": "Ada",
    "last_name": "Lovelace",
    "username": "ada",
    "language_code": "ru",
    "is_premium": True,
}


def sign(fields: dict[str, str], *, token: str = FAKE_TOKEN) -> str:
    """Build an `initData` string the way Telegram does."""
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    digest = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})


def init_data(
    *,
    auth_date: datetime = NOW,
    user: dict[str, Any] | None = None,
    token: str = FAKE_TOKEN,
    extra: dict[str, str] | None = None,
) -> str:
    fields = {
        "auth_date": str(int(auth_date.timestamp())),
        "query_id": "AAH0aXQAAAAAAPRpdCg8pXYb",
        "user": json.dumps(user if user is not None else USER, separators=(",", ":")),
    }
    fields.update(extra or {})
    return sign(fields, token=token)


# --- initData: signature --------------------------------------------------------
def test_valid_init_data_passes_signature_check() -> None:
    assert check_signature(init_data(), token=FAKE_TOKEN) is True


def test_signature_is_rejected_for_a_different_bot_token() -> None:
    """The whole trust model: only the bot that owns the token can mint initData."""
    assert check_signature(init_data(), token="999:another-bot-token") is False


def test_tampering_with_any_field_breaks_the_signature() -> None:
    raw = init_data()
    forged = raw.replace("Ada", "Eve")
    assert forged != raw
    assert check_signature(forged, token=FAKE_TOKEN) is False


def test_escalating_to_another_user_id_breaks_the_signature() -> None:
    honest = init_data()
    attacker = honest.replace(str(USER_ID), "1")
    assert check_signature(attacker, token=FAKE_TOKEN) is False


def test_init_data_without_a_hash_is_rejected() -> None:
    assert check_signature("auth_date=1&user=%7B%7D", token=FAKE_TOKEN) is False


def test_empty_init_data_is_rejected() -> None:
    assert check_signature("", token=FAKE_TOKEN) is False


def test_signature_survives_the_bot_api_80_signature_field() -> None:
    """Bot API 8.0 sends an extra Ed25519 `signature`; it must not break the HMAC.

    Telegram covers it in the token hash, so the primary candidate matches. The
    fallback that drops it exists for the day that stops being true.
    """
    raw = init_data(extra={"signature": "3E-hLdRLm5tZOZKF2gAqLm3iEdmr5PxSuA"})
    assert "signature=" in raw
    assert check_signature(raw, token=FAKE_TOKEN) is True


def test_a_forged_signature_field_cannot_launder_a_bad_hash() -> None:
    """The fallback path must not become a way to skip verification.

    An attacker who adds `signature` to an otherwise-unsigned payload gets both
    candidate digests computed over data they cannot sign.
    """
    fields = {
        "auth_date": str(int(NOW.timestamp())),
        "user": json.dumps(USER, separators=(",", ":")),
        "signature": "forged",
        "hash": "0" * 64,
    }
    assert check_signature(urlencode(fields), token=FAKE_TOKEN) is False


def test_our_data_check_string_matches_aiogram() -> None:
    """Cross-check against an independent implementation of the same rule."""
    from aiogram.utils.web_app import check_webapp_signature

    assert check_webapp_signature(FAKE_TOKEN, init_data()) is True


# --- initData: payload ----------------------------------------------------------
def test_identity_is_read_from_the_user_field() -> None:
    identity = parse_identity(init_data())
    assert identity.tg_user_id == USER_ID
    assert identity.username == "ada"
    assert identity.first_name == "Ada"
    assert identity.last_name == "Lovelace"
    assert identity.language_code == "ru"
    assert identity.is_premium is True
    assert identity.is_bot is False
    assert identity.auth_date == NOW
    # The hash doubles as the replay nonce, so it has to survive parsing.
    assert len(identity.fingerprint) == 64


def test_init_data_without_a_user_is_rejected() -> None:
    """A keyboard-button launch carries no user, so there is nobody to authorize."""
    fields = {"auth_date": str(int(NOW.timestamp())), "query_id": "AAH0"}
    with pytest.raises(InvalidInitDataError):
        parse_identity(sign(fields))


def test_malformed_user_json_is_rejected() -> None:
    with pytest.raises(InvalidInitDataError):
        parse_identity(sign({"auth_date": str(int(NOW.timestamp())), "user": "{not json"}))


def test_user_object_without_an_id_is_rejected() -> None:
    with pytest.raises(InvalidInitDataError):
        parse_identity(sign({"auth_date": str(int(NOW.timestamp())), "user": '{"first_name":"X"}'}))


def test_non_numeric_auth_date_is_rejected() -> None:
    with pytest.raises(InvalidInitDataError):
        parse_identity(sign({"auth_date": "yesterday", "user": json.dumps(USER)}))


# --- initData: freshness and replay ---------------------------------------------
@pytest.fixture
def fake_redis() -> Iterator[FakeRedis]:
    """Point the replay guard at an in-memory Redis for the duration of a test."""
    client = FakeRedis()
    set_redis(client)
    yield client
    set_redis(FakeRedis())


async def test_fresh_init_data_verifies(fake_redis: FakeRedis) -> None:
    identity = await verify_init_data(init_data(), token=FAKE_TOKEN, now=NOW)
    assert identity.tg_user_id == USER_ID


async def test_expired_init_data_is_rejected(fake_redis: FakeRedis) -> None:
    """Spec: `auth_date` TTL must be at most 24 h."""
    stale = NOW - timedelta(hours=25)
    with pytest.raises(InvalidInitDataError):
        await verify_init_data(
            init_data(auth_date=stale), token=FAKE_TOKEN, now=NOW, ttl=timedelta(hours=24)
        )


async def test_init_data_at_the_ttl_boundary_still_verifies(fake_redis: FakeRedis) -> None:
    edge = NOW - timedelta(hours=24)
    identity = await verify_init_data(
        init_data(auth_date=edge), token=FAKE_TOKEN, now=NOW, ttl=timedelta(hours=24)
    )
    assert identity.auth_date == edge


async def test_future_dated_init_data_is_rejected(fake_redis: FakeRedis) -> None:
    ahead = NOW + timedelta(minutes=10)
    with pytest.raises(InvalidInitDataError):
        await verify_init_data(init_data(auth_date=ahead), token=FAKE_TOKEN, now=NOW)


async def test_clock_skew_within_tolerance_is_accepted(fake_redis: FakeRedis) -> None:
    """Telegram's clock is not ours; a few seconds ahead is not an attack."""
    ahead = NOW + (CLOCK_SKEW / 2)
    identity = await verify_init_data(init_data(auth_date=ahead), token=FAKE_TOKEN, now=NOW)
    assert identity.tg_user_id == USER_ID


async def test_a_bot_cannot_open_the_panel(fake_redis: FakeRedis) -> None:
    with pytest.raises(InvalidInitDataError):
        await verify_init_data(init_data(user={**USER, "is_bot": True}), token=FAKE_TOKEN, now=NOW)


async def test_replaying_the_same_init_data_is_rejected(fake_redis: FakeRedis) -> None:
    """Second use of one string fails, which is what makes a leak short-lived."""
    raw = init_data()
    await verify_init_data(raw, token=FAKE_TOKEN, now=NOW)
    with pytest.raises(InvalidInitDataError):
        await verify_init_data(raw, token=FAKE_TOKEN, now=NOW)


async def test_two_distinct_sessions_do_not_collide(fake_redis: FakeRedis) -> None:
    first = init_data(extra={"query_id": "AAH-first"})
    second = init_data(extra={"query_id": "AAH-second"})
    assert await verify_init_data(first, token=FAKE_TOKEN, now=NOW)
    assert await verify_init_data(second, token=FAKE_TOKEN, now=NOW)


async def test_replay_check_can_be_waived_for_stateless_callers(fake_redis: FakeRedis) -> None:
    raw = init_data()
    await verify_init_data(raw, token=FAKE_TOKEN, now=NOW, single_use=False)
    await verify_init_data(raw, token=FAKE_TOKEN, now=NOW, single_use=False)


async def test_replay_guard_degrades_when_redis_is_down() -> None:
    """A cache outage must not lock every admin out of their own panel."""
    from redis.exceptions import ConnectionError as RedisConnectionError

    # A subclass rather than a stand-in: `set_redis` takes a `Redis`, and the
    # only call the replay guard makes is the one being broken here.
    class DeadRedis(FakeRedis):
        async def set(self, *args: Any, **kwargs: Any) -> bool:
            raise RedisConnectionError("connection refused")

    set_redis(DeadRedis())
    try:
        identity = await verify_init_data(init_data(), token=FAKE_TOKEN, now=NOW)
        assert identity.tg_user_id == USER_ID
    finally:
        set_redis(FakeRedis())


async def test_verification_without_a_bot_token_is_our_bug_not_a_login_failure(
    fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing deployment secret must not read as "wrong credentials"."""
    import core.webapp as webapp_module

    tokenless = get_settings().model_copy(update={"bot_token": ""})
    monkeypatch.setattr(webapp_module, "get_settings", lambda: tokenless)
    with pytest.raises(RuntimeError):
        await verify_init_data(init_data(), now=NOW)


# --- session tokens -------------------------------------------------------------
PRINCIPAL = Principal(
    tg_user_id=USER_ID,
    username="ada",
    first_name="Ada",
    last_name="Lovelace",
    language="ru",
)


def test_token_round_trip_preserves_identity() -> None:
    token, expires_in = issue_token(PRINCIPAL)
    assert expires_in > 0
    decoded = decode_token(token)
    assert decoded.tg_user_id == PRINCIPAL.tg_user_id
    assert decoded.username == PRINCIPAL.username
    assert decoded.first_name == PRINCIPAL.first_name
    assert decoded.last_name == PRINCIPAL.last_name
    assert decoded.language == PRINCIPAL.language


def test_expired_token_is_rejected() -> None:
    token, _ = issue_token(PRINCIPAL, now=NOW - timedelta(hours=2), ttl=timedelta(hours=1))
    with pytest.raises(InvalidSessionError):
        decode_token(token)


def test_tampered_token_is_rejected() -> None:
    token, _ = issue_token(PRINCIPAL)
    header, payload, signature = token.split(".")
    forged = f"{header}.{payload}.{signature[:-4]}AAAA"
    with pytest.raises(InvalidSessionError):
        decode_token(forged)


def test_token_signed_with_another_secret_is_rejected() -> None:
    """Anyone can craft a payload; only we can sign one."""
    forged = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": str(USER_ID),
            "iat": int(NOW.timestamp()),
            "exp": int((NOW + timedelta(hours=1)).timestamp()),
        },
        "not-our-secret-but-long-enough-to-be-plausible",
        algorithm="HS256",
    )
    with pytest.raises(InvalidSessionError):
        decode_token(forged)


def test_unsigned_token_is_rejected() -> None:
    """The `alg: none` classic — pyjwt must not be talked into accepting it."""
    forged = jwt.encode({"sub": str(USER_ID)}, key="", algorithm="none")
    with pytest.raises(InvalidSessionError):
        decode_token(forged)


@pytest.mark.parametrize(
    ("claim", "value"),
    [("aud", "someone-elses-app"), ("iss", "someone-elses-service")],
)
def test_token_issued_for_another_service_is_rejected(claim: str, value: str) -> None:
    settings = get_settings()
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(USER_ID),
        "iat": int(NOW.timestamp()),
        "exp": int((NOW + timedelta(hours=1)).timestamp()),
        claim: value,
    }
    forged = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(InvalidSessionError):
        decode_token(forged)


def test_token_without_an_expiry_is_rejected() -> None:
    """A token that never expires would outlive any revocation we can perform."""
    settings = get_settings()
    forged = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": str(USER_ID), "iat": int(NOW.timestamp())},
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(InvalidSessionError):
        decode_token(forged)


def test_superadmin_claim_in_the_token_is_not_trusted() -> None:
    """`sa` is re-derived from settings, so a self-signed elevation buys nothing.

    Only relevant if our secret leaks — but that is exactly when it matters.
    """
    settings = get_settings()
    forged = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": str(USER_ID),
            "iat": int(NOW.timestamp()),
            "exp": int((datetime.now(tz=UTC) + timedelta(hours=1)).timestamp()),
            "sa": True,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    assert USER_ID not in settings.superadmin_id_list
    assert decode_token(forged).is_superadmin is False


def test_principal_language_falls_back_to_a_supported_locale() -> None:
    token, _ = issue_token(Principal(tg_user_id=USER_ID, language="fr"))
    assert decode_token(token).language in {"ru", "en"}


# --- fakes for the HTTP layer ---------------------------------------------------
def make_chat(**overrides: Any) -> Chat:
    chat = Chat(
        id=CHAT_ID,
        tg_chat_id=TG_CHAT_ID,
        title="Test Chat",
        type=ChatType.SUPERGROUP,
        plan=Plan.FREE,
        plan_expires_at=None,
        grace_until=None,
        owner_tg_id=USER_ID,
        language="ru",
        timezone="UTC",
        members_count=1234,
        is_active=True,
        settings={},
    )
    for key, value in overrides.items():
        setattr(chat, key, value)
    return chat


class FakeChatRepo:
    def __init__(self, chats: dict[int, Chat]) -> None:
        self.chats = chats
        self.updates: list[tuple[int, dict[str, Any]]] = []

    async def get_by_id(self, chat_id: int) -> Chat | None:
        return self.chats.get(chat_id)

    async def list_for_admin(self, tg_user_id: int) -> list[Chat]:
        return list(self.chats.values())

    async def update_fields(self, chat_id: int, **fields: Any) -> None:
        self.updates.append((chat_id, fields))
        chat = self.chats[chat_id]
        for key, value in fields.items():
            setattr(chat, key, value)


class FakeUserRepo:
    def __init__(self) -> None:
        self.upserted: list[dict[str, Any]] = []

    async def upsert(self, **kwargs: Any) -> None:
        self.upserted.append(kwargs)

    async def get(self, tg_user_id: int) -> TgUser | None:
        if tg_user_id != USER_ID:
            return None
        return TgUser(
            tg_user_id=USER_ID,
            username="ada",
            first_name="Ada",
            last_name="Lovelace",
            language_code="ru",
        )


class FakeWebsiteTokenRepo:
    def __init__(self) -> None:
        self.valid_hash = hashlib.sha256(b"valid-website-token-with-enough-length").hexdigest()
        self.consumed = False

    async def consume(self, *, token_hash: str, scope: str, now: datetime) -> int | None:
        if scope != "website":
            return None
        if self.consumed or token_hash != self.valid_hash:
            return None
        self.consumed = True
        return USER_ID


class FakeUow:
    """Just the two repositories the Stage 3 routes reach for."""

    def __init__(self, chats: dict[int, Chat]) -> None:
        self.chats = FakeChatRepo(chats)
        self.users = FakeUserRepo()
        self.website_tokens = FakeWebsiteTokenRepo()
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeAdmins:
    """Stands in for `getChatMember`, which is the whole authorization decision."""

    def __init__(self, *, admin_of: set[int] | None = None) -> None:
        self.admin_of = {TG_CHAT_ID} if admin_of is None else admin_of
        self.synced: list[int] = []

    async def is_admin(self, tg_chat_id: int, tg_user_id: int) -> bool:
        return tg_chat_id in self.admin_of

    async def sync_to_db(self, chat_id: int, tg_chat_id: int) -> int:
        self.synced.append(chat_id)
        return 3

    async def bot_permissions(self, tg_chat_id: int) -> BotPermissionSnapshot:
        assert tg_chat_id == TG_CHAT_ID
        return BotPermissionSnapshot(
            status="administrator",
            is_admin=True,
            can_read_messages=True,
            can_send_messages=True,
            can_delete_messages=True,
            can_restrict_members=True,
            can_invite_users=True,
        )


class FakeFeatures:
    def __init__(self, plan: Plan = Plan.FREE) -> None:
        self.plan_value = plan

    async def features(self, chat_id: int) -> frozenset[Feature]:
        return PLAN_FEATURES[self.plan_value]

    async def has(self, chat_id: int, feature: Feature) -> bool:
        return feature in PLAN_FEATURES[self.plan_value]

    async def require(self, chat_id: int, feature: Feature) -> None:
        if not await self.has(chat_id, feature):
            raise FeatureLockedError(
                f"Feature '{feature.value}' is locked.",
                feature=feature.value,
                required_plan=minimum_plan_for(feature).value,
            )


class FakeConfigs:
    """In-memory module configs, validated through the real registry models."""

    def __init__(self, features: FakeFeatures) -> None:
        self.features = features
        self.stored: dict[str, dict[str, Any]] = {}
        self.enabled: dict[str, bool] = {}

    async def get(self, chat_id: int, module: str) -> Any:
        spec = registry.get(module)
        return spec.config_model.model_validate(self.stored.get(module, {}))

    async def is_enabled(self, chat_id: int, module: str) -> bool:
        spec = registry.get(module)
        if not await self.features.has(chat_id, spec.feature):
            return False
        if spec.mandatory:
            return True
        return self.enabled.get(module, spec.enabled_by_default)

    async def enabled_modules(self, chat_id: int) -> frozenset[str]:
        names = set()
        for spec in registry:
            if await self.is_enabled(chat_id, spec.name.value):
                names.add(spec.name.value)
        return frozenset(names)

    async def save(
        self,
        chat_id: int,
        module: str,
        *,
        config: dict[str, Any] | Any = None,
        enabled: bool | None = None,
    ) -> Any:
        spec = registry.get(module)
        if config is not None:
            # Strict, like the real service: an unknown or out-of-range key has to
            # surface as a domain error, not a 500.
            try:
                validated = spec.config_model.model_validate(config)
            except ValidationError as exc:
                raise InvalidModuleConfigError(
                    f"Invalid settings for '{module}'.",
                    module=module,
                    errors=exc.errors(include_url=False),
                ) from exc
            self.stored[module] = validated.model_dump(mode="json")
        if enabled is not None:
            self.enabled[module] = enabled
        return await self.get(chat_id, module)


# --- HTTP test bed --------------------------------------------------------------
class Bed:
    """The app plus handles on every fake it was wired with."""

    def __init__(self, app: FastAPI, client: httpx.AsyncClient) -> None:
        self.app = app
        self.client = client
        self.uow: FakeUow
        self.admins: FakeAdmins
        self.features: FakeFeatures
        self.configs: FakeConfigs

    def auth(self, principal: Principal = PRINCIPAL) -> dict[str, str]:
        token, _ = issue_token(principal)
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def bed(fake_redis: FakeRedis) -> AsyncIterator[Bed]:
    """`create_app()` with the outward-facing dependencies replaced.

    The lifespan is deliberately not run: it would open a real Bot session and a
    real Redis connection. Everything it wires is overridden here instead, and
    the cache goes to cashews' in-memory backend so invalidation is still real.
    """
    cache.cache.setup("mem://")
    chats = {CHAT_ID: make_chat()}
    uow = FakeUow(chats)
    admins = FakeAdmins()
    features = FakeFeatures()
    configs = FakeConfigs(features)

    app = create_app()
    app.dependency_overrides[get_uow] = lambda: uow
    app.dependency_overrides[get_admin_service] = lambda: admins
    app.dependency_overrides[get_features] = lambda: features
    app.dependency_overrides[get_module_configs] = lambda: configs
    app.dependency_overrides[get_app_settings] = get_settings

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        harness = Bed(app, client)
        harness.uow = uow
        harness.admins = admins
        harness.features = features
        harness.configs = configs
        yield harness


# --- system routes --------------------------------------------------------------
async def test_health_is_served_at_both_paths(bed: Bed) -> None:
    """The container probe calls `/health`; the panel calls `/api/health`."""
    for path in ("/health", "/api/health"):
        response = await bed.client.get(path)
        assert response.status_code == 200, path
        assert response.json()["status"] == "ok"


async def test_meta_describes_every_module_and_plan(
    bed: Bed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Mini App renders its sections from this, so it must be complete."""
    monkeypatch.setattr(
        system_router,
        "get_settings",
        lambda: Settings(ai_base_url="", ai_model="", _env_file=None),
    )
    response = await bed.client.get("/api/meta")
    assert response.status_code == 200
    body = response.json()

    names = {module["name"] for module in body["modules"]}
    assert names == {spec.name.value for spec in registry}
    assert {plan["plan"] for plan in body["plans"]} == {plan.value for plan in Plan}
    assert set(body["locales"]) == {"ru", "en"}
    assert body["capabilities"] == {
        "payment_providers": [],
        "ai_moderation_available": False,
    }

    moderation = next(m for m in body["modules"] if m["name"] == "moderation")
    assert moderation["required_plan"] == Plan.FREE.value
    assert moderation["mandatory"] is True
    # The panel builds its form controls from this schema.
    assert "warn_limit" in moderation["config_schema"]["properties"]


async def test_meta_reports_configured_integrations(
    bed: Bed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        system_router,
        "get_settings",
        lambda: Settings(
            bot_token="configured",
            cryptobot_token="configured",
            ai_enabled=True,
            ai_api_key="",
            ai_completion_path="",
            _env_file=None,
        ),
    )

    response = await bed.client.get("/api/meta")

    assert response.status_code == 200
    assert response.json()["capabilities"] == {
        "payment_providers": ["stars", "cryptobot"],
        "ai_moderation_available": True,
    }


async def test_openapi_gives_every_operation_a_stable_id(bed: Bed) -> None:
    """The generated TS client names its methods after these."""
    schema = bed.app.openapi()
    ids = [
        operation["operationId"] for path in schema["paths"].values() for operation in path.values()
    ]
    assert len(ids) == len(set(ids))
    assert "authenticateWithTelegram" in ids
    assert "patchModuleConfig" in ids
    # FastAPI's default ids carry the route function and method; ours are hand-set.
    assert not any(id_.endswith("_get") for id_ in ids)


# --- authentication over HTTP ---------------------------------------------------
async def test_a_missing_authorization_header_is_a_problem_body(bed: Bed) -> None:
    """Not FastAPI's `{"detail": "Not authenticated"}` — the panel branches on `code`."""
    response = await bed.client.get("/api/chats")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "invalid-session"
    assert body["status"] == 401
    assert body["title"]  # localized, safe to show
    assert body["instance"] == "/api/chats"


async def test_a_garbage_token_is_rejected(bed: Bed) -> None:
    response = await bed.client.get("/api/chats", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
    assert response.json()["code"] == "invalid-session"


async def test_the_wrong_authorization_scheme_is_rejected(bed: Bed) -> None:
    token, _ = issue_token(PRINCIPAL)
    response = await bed.client.get("/api/chats", headers={"Authorization": f"Basic {token}"})
    assert response.status_code == 401


async def test_a_valid_token_reaches_the_route(bed: Bed) -> None:
    response = await bed.client.get("/api/auth/me", headers=bed.auth())
    assert response.status_code == 200
    assert response.json()["tg_user_id"] == USER_ID


async def test_init_data_is_exchanged_for_a_token(bed: Bed) -> None:
    """The whole login: a signed string in, a usable session out."""
    settings = get_settings()
    response = await bed.client.post(
        "/api/auth/telegram",
        json={"init_data": init_data(auth_date=datetime.now(tz=UTC), token=settings.bot_token)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expires_in"] > 0
    assert body["user"]["tg_user_id"] == USER_ID
    # The admin's profile is cached so the panel and log channel can print a name.
    assert bed.uow.users.upserted[0]["tg_user_id"] == USER_ID
    assert bed.uow.commits == 1
    # And the issued token works on a protected route.
    follow_up = await bed.client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert follow_up.status_code == 200


async def test_website_key_is_exchanged_once_for_the_same_user(bed: Bed) -> None:
    payload = {"token": "valid-website-token-with-enough-length"}
    response = await bed.client.post("/api/auth/website", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["tg_user_id"] == USER_ID
    assert decode_token(body["access_token"]).tg_user_id == USER_ID

    replay = await bed.client.post("/api/auth/website", json=payload)
    assert replay.status_code == 401
    assert replay.json()["code"] == "invalid-session"


async def test_invalid_website_key_does_not_reveal_an_account(bed: Bed) -> None:
    response = await bed.client.post(
        "/api/auth/website", json={"token": "invalid-website-token-with-enough-length"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid-session"


async def test_bad_init_data_is_rejected_by_the_endpoint(bed: Bed) -> None:
    response = await bed.client.post(
        "/api/auth/telegram", json={"init_data": init_data(token="999:wrong-token")}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid-init-data"


async def test_replayed_init_data_is_rejected_by_the_endpoint(bed: Bed) -> None:
    settings = get_settings()
    raw = init_data(auth_date=datetime.now(tz=UTC), token=settings.bot_token)
    first = await bed.client.post("/api/auth/telegram", json={"init_data": raw})
    assert first.status_code == 200
    second = await bed.client.post("/api/auth/telegram", json={"init_data": raw})
    assert second.status_code == 401
    assert second.json()["code"] == "invalid-init-data"


async def test_refresh_renews_a_session_without_init_data(bed: Bed) -> None:
    """This is what makes single-use initData workable for a long panel session."""
    response = await bed.client.post("/api/auth/refresh", headers=bed.auth())
    assert response.status_code == 200
    assert decode_token(response.json()["access_token"]).tg_user_id == USER_ID


async def test_refresh_requires_a_live_token(bed: Bed) -> None:
    expired, _ = issue_token(PRINCIPAL, now=NOW - timedelta(days=2), ttl=timedelta(hours=1))
    response = await bed.client.post(
        "/api/auth/refresh", headers={"Authorization": f"Bearer {expired}"}
    )
    assert response.status_code == 401


async def test_an_empty_init_data_string_is_a_validation_error(bed: Bed) -> None:
    response = await bed.client.post("/api/auth/telegram", json={"init_data": ""})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid-request"
    # The panel highlights the offending field from this.
    assert body["context"]["errors"]


# --- chat authorization ---------------------------------------------------------
async def test_chat_list_shows_the_chats_the_caller_administers(bed: Bed) -> None:
    response = await bed.client.get("/api/chats", headers=bed.auth())
    assert response.status_code == 200
    [chat] = response.json()
    assert chat["id"] == CHAT_ID
    assert chat["title"] == "Test Chat"
    assert chat["role"] == "owner"  # owner_tg_id matches the caller
    assert chat["members_count"] == 1234


async def test_a_non_admin_gets_404_rather_than_403(bed: Bed) -> None:
    """404 for both cases, so a 403 cannot be used to enumerate chat ids."""
    bed.admins.admin_of = set()
    response = await bed.client.get(f"/api/chats/{CHAT_ID}", headers=bed.auth())
    assert response.status_code == 404
    assert response.json()["code"] == "chat-not-found"


async def test_an_unknown_chat_answers_exactly_like_a_forbidden_one(bed: Bed) -> None:
    """The two cases must be indistinguishable, or 404 is an existence oracle."""
    missing = await bed.client.get("/api/chats/424242", headers=bed.auth())
    bed.admins.admin_of = set()
    denied = await bed.client.get(f"/api/chats/{CHAT_ID}", headers=bed.auth())
    assert missing.status_code == denied.status_code == 404
    assert denied.json()["code"] == missing.json()["code"]
    assert denied.json()["title"] == missing.json()["title"]
    assert denied.json()["detail"] == missing.json()["detail"]


async def test_a_deactivated_chat_is_not_reachable(bed: Bed) -> None:
    """The bot was removed from the chat; its settings stop being addressable."""
    bed.uow.chats.chats[CHAT_ID].is_active = False
    response = await bed.client.get(f"/api/chats/{CHAT_ID}", headers=bed.auth())
    assert response.status_code == 404


async def test_reads_are_gated_too_not_only_writes(bed: Bed) -> None:
    """Stop-words and the log-channel id are moderation intelligence."""
    bed.admins.admin_of = set()
    for path in (
        f"/api/chats/{CHAT_ID}",
        f"/api/chats/{CHAT_ID}/modules",
        f"/api/chats/{CHAT_ID}/modules/moderation",
        f"/api/chats/{CHAT_ID}/plan",
    ):
        response = await bed.client.get(path, headers=bed.auth())
        assert response.status_code == 404, path


async def test_a_negative_chat_id_never_reaches_the_repository(bed: Bed) -> None:
    response = await bed.client.get("/api/chats/-1", headers=bed.auth())
    assert response.status_code == 422
    assert response.json()["code"] == "invalid-request"


# --- chat detail and settings ---------------------------------------------------
async def test_chat_detail_carries_module_state_and_unlocked_features(bed: Bed) -> None:
    response = await bed.client.get(f"/api/chats/{CHAT_ID}", headers=bed.auth())
    assert response.status_code == 200
    body = response.json()
    assert set(body["modules"]) == {spec.name.value for spec in registry}
    assert body["modules"]["moderation"] is True  # mandatory, always on
    assert body["modules"]["stats"] is False  # Pro, and this chat is Free
    assert set(body["features"]) == {f.value for f in PLAN_FEATURES[Plan.FREE]}
    assert body["language"] == "ru"
    assert body["timezone"] == "UTC"


async def test_updating_a_chat_persists_and_invalidates_the_cache(bed: Bed) -> None:
    """Spec §5.7: a saved setting applies without restarting the bot.

    The bot reads through the cache, so the write is only finished once the
    chat's cached entries are gone.
    """
    await cache.set_value(cache.plan_key(CHAT_ID), "free", ttl=600, tags=(cache.chat_tag(CHAT_ID),))
    response = await bed.client.patch(
        f"/api/chats/{CHAT_ID}", headers=bed.auth(), json={"language": "en"}
    )
    assert response.status_code == 200
    assert response.json()["language"] == "en"
    assert bed.uow.chats.updates == [(CHAT_ID, {"language": "en"})]
    assert bed.uow.commits == 1
    assert await cache.get_value(cache.plan_key(CHAT_ID)) is None


async def test_an_unknown_timezone_is_refused_before_it_reaches_a_cron_job(bed: Bed) -> None:
    response = await bed.client.patch(
        f"/api/chats/{CHAT_ID}", headers=bed.auth(), json={"timezone": "Mars/Olympus"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid-timezone"
    assert bed.uow.chats.updates == []


async def test_a_real_timezone_is_accepted(bed: Bed) -> None:
    response = await bed.client.patch(
        f"/api/chats/{CHAT_ID}", headers=bed.auth(), json={"timezone": "Europe/Moscow"}
    )
    assert response.status_code == 200
    assert response.json()["timezone"] == "Europe/Moscow"


async def test_an_unsupported_language_is_refused(bed: Bed) -> None:
    response = await bed.client.patch(
        f"/api/chats/{CHAT_ID}", headers=bed.auth(), json={"language": "fr"}
    )
    assert response.status_code == 422


async def test_an_empty_patch_changes_nothing(bed: Bed) -> None:
    response = await bed.client.patch(f"/api/chats/{CHAT_ID}", headers=bed.auth(), json={})
    assert response.status_code == 200
    assert bed.uow.chats.updates == []
    assert bed.uow.commits == 0


async def test_the_plan_route_reports_the_plan_actually_in_force(bed: Bed) -> None:
    """An expired subscription still runs on Pro until grace ends."""
    chat = bed.uow.chats.chats[CHAT_ID]
    chat.plan = Plan.PRO
    chat.plan_expires_at = datetime.now(tz=UTC) - timedelta(days=1)
    chat.grace_until = datetime.now(tz=UTC) + timedelta(days=2)
    response = await bed.client.get(f"/api/chats/{CHAT_ID}/plan", headers=bed.auth())
    assert response.status_code == 200
    assert response.json()["plan"] == Plan.PRO.value

    chat.grace_until = datetime.now(tz=UTC) - timedelta(hours=1)
    lapsed = await bed.client.get(f"/api/chats/{CHAT_ID}/plan", headers=bed.auth())
    assert lapsed.json()["plan"] == Plan.FREE.value


async def test_admin_sync_refreshes_the_mirror(bed: Bed) -> None:
    response = await bed.client.post(f"/api/chats/{CHAT_ID}/admins/sync", headers=bed.auth())
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert bed.admins.synced == [CHAT_ID]


async def test_bot_permissions_are_read_live_from_telegram(bed: Bed) -> None:
    response = await bed.client.get(f"/api/chats/{CHAT_ID}/bot-permissions", headers=bed.auth())

    assert response.status_code == 200
    assert response.json() == {
        "reachable": True,
        "status": "administrator",
        "is_admin": True,
        "privacy_mode_disabled": False,
        "can_read_messages": True,
        "can_send_messages": True,
        "can_delete_messages": True,
        "can_restrict_members": True,
        "can_invite_users": True,
        "can_manage_topics": False,
        "issues": [],
    }


# --- module settings ------------------------------------------------------------
async def test_module_list_includes_locked_modules(bed: Bed) -> None:
    """Locked modules are the paywall: rendered greyed out, not hidden."""
    response = await bed.client.get(f"/api/chats/{CHAT_ID}/modules", headers=bed.auth())
    assert response.status_code == 200
    by_name = {module["module"]: module for module in response.json()}
    assert by_name.keys() == {spec.name.value for spec in registry}

    assert by_name["moderation"]["available"] is True
    assert by_name["moderation"]["enabled"] is True
    stats = by_name["stats"]
    assert stats["available"] is False
    assert stats["enabled"] is False
    assert stats["required_plan"] == Plan.PRO.value
    # Defaults are filled in, so the panel never has to know what a missing key means.
    assert by_name["moderation"]["config"]["warn_limit"] == 3


async def test_a_free_module_saves_and_reads_back(bed: Bed) -> None:
    response = await bed.client.patch(
        f"/api/chats/{CHAT_ID}/modules/moderation",
        headers=bed.auth(),
        json={"config": {"warn_limit": 5, "stop_words": ["spam"]}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["warn_limit"] == 5
    assert body["config"]["stop_words"] == ["spam"]

    reread = await bed.client.get(f"/api/chats/{CHAT_ID}/modules/moderation", headers=bed.auth())
    assert reread.json()["config"]["warn_limit"] == 5


async def test_patch_merges_and_leaves_unrendered_keys_alone(bed: Bed) -> None:
    """A settings screen submits what it renders; a newer key must survive it."""
    await bed.client.patch(
        f"/api/chats/{CHAT_ID}/modules/moderation",
        headers=bed.auth(),
        json={"config": {"warn_limit": 7, "anti_flood_messages": 20}},
    )
    response = await bed.client.patch(
        f"/api/chats/{CHAT_ID}/modules/moderation",
        headers=bed.auth(),
        json={"config": {"warn_limit": 4}},
    )
    body = response.json()
    assert body["config"]["warn_limit"] == 4
    assert body["config"]["anti_flood_messages"] == 20  # not wiped by the merge


async def test_put_replaces_and_resets_omitted_keys_to_defaults(bed: Bed) -> None:
    """The counterpart to the merge — this is why the panel uses PATCH."""
    await bed.client.patch(
        f"/api/chats/{CHAT_ID}/modules/moderation",
        headers=bed.auth(),
        json={"config": {"anti_flood_messages": 20}},
    )
    response = await bed.client.put(
        f"/api/chats/{CHAT_ID}/modules/moderation",
        headers=bed.auth(),
        json={"config": {"warn_limit": 2}},
    )
    body = response.json()
    assert body["config"]["warn_limit"] == 2
    assert body["config"]["anti_flood_messages"] == 8  # back to the model default


async def test_reset_restores_defaults(bed: Bed) -> None:
    await bed.client.patch(
        f"/api/chats/{CHAT_ID}/modules/moderation",
        headers=bed.auth(),
        json={"config": {"warn_limit": 9}},
    )
    response = await bed.client.post(
        f"/api/chats/{CHAT_ID}/modules/moderation/reset", headers=bed.auth()
    )
    assert response.status_code == 200
    assert response.json()["config"]["warn_limit"] == 3


async def test_a_module_can_be_toggled_without_touching_its_config(bed: Bed) -> None:
    response = await bed.client.patch(
        f"/api/chats/{CHAT_ID}/modules/entry", headers=bed.auth(), json={"enabled": False}
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert "entry" not in bed.configs.stored


async def test_a_locked_module_answers_402_with_the_plan_that_unlocks_it(bed: Bed) -> None:
    """The panel turns this into an upgrade prompt rather than a silent no-op."""
    response = await bed.client.patch(
        f"/api/chats/{CHAT_ID}/modules/stats",
        headers=bed.auth(),
        json={"config": {"enabled_reports": []}},
    )
    assert response.status_code == 402
    body = response.json()
    assert body["code"] == "feature-locked"
    assert body["context"]["required_plan"] == Plan.PRO.value
    assert body["context"]["feature"] == Feature.STATS.value


async def test_upgrading_the_plan_unlocks_the_same_module(bed: Bed) -> None:
    bed.features.plan_value = Plan.PRO
    response = await bed.client.patch(
        f"/api/chats/{CHAT_ID}/modules/stats", headers=bed.auth(), json={"enabled": True}
    )
    assert response.status_code == 200
    assert response.json()["available"] is True
    assert response.json()["enabled"] is True


async def test_an_unknown_module_name_is_refused(bed: Bed) -> None:
    response = await bed.client.get(f"/api/chats/{CHAT_ID}/modules/telepathy", headers=bed.auth())
    assert response.status_code == 422
    assert response.json()["code"] == "invalid-module-config"


async def test_an_out_of_range_setting_is_refused_with_field_errors(bed: Bed) -> None:
    response = await bed.client.patch(
        f"/api/chats/{CHAT_ID}/modules/moderation",
        headers=bed.auth(),
        json={"config": {"warn_limit": 9_999}},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid-module-config"
    assert bed.configs.stored.get("moderation") is None


async def test_an_unknown_config_key_is_refused(bed: Bed) -> None:
    """Strict validation: a typo in a key must not be silently persisted."""
    response = await bed.client.patch(
        f"/api/chats/{CHAT_ID}/modules/moderation",
        headers=bed.auth(),
        json={"config": {"wran_limit": 5}},
    )
    assert response.status_code == 422


async def test_a_mandatory_module_cannot_be_disabled_through_the_api(bed: Bed) -> None:
    """`moderation` is the product; a chat with it off is a chat without the bot."""
    response = await bed.client.patch(
        f"/api/chats/{CHAT_ID}/modules/moderation", headers=bed.auth(), json={"enabled": False}
    )
    assert response.status_code == 200
    # The toggle is accepted and stored, but the gate still reports it as on.
    assert response.json()["enabled"] is True


# --- error shape ----------------------------------------------------------------
async def test_an_unknown_path_uses_the_same_problem_shape(bed: Bed) -> None:
    response = await bed.client.get("/api/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "http-404"


async def test_a_wrong_method_uses_the_same_problem_shape(bed: Bed) -> None:
    response = await bed.client.delete("/api/meta")
    assert response.status_code == 405
    assert response.json()["status"] == 405


async def test_error_titles_follow_the_caller_locale(bed: Bed) -> None:
    """The panel holder may not share the chat's language."""
    russian = await bed.client.get("/api/chats", headers={"Accept-Language": "ru"})
    english = await bed.client.get("/api/chats", headers={"Accept-Language": "en"})
    assert russian.status_code == english.status_code == 401
    assert russian.json()["title"] != english.json()["title"]
    assert russian.json()["code"] == english.json()["code"]


async def test_every_response_carries_a_request_id(bed: Bed) -> None:
    response = await bed.client.get("/api/meta")
    assert response.headers["x-request-id"]


async def test_an_inbound_request_id_is_reused(bed: Bed) -> None:
    """A caller-supplied id lets one trace span the panel and the API logs."""
    response = await bed.client.get("/api/meta", headers={"X-Request-ID": "trace-abc123"})
    assert response.headers["x-request-id"] == "trace-abc123"


# --------------------------------------------------------------------------- #
# Production configuration guard
# --------------------------------------------------------------------------- #
#
# The signing secret and the CORS list are the two settings whose defaults are
# convenient in development and dangerous in production. `Settings` refuses the
# dangerous combination rather than trusting a deploy checklist.


SAFE_PRODUCTION = {
    "app_env": "production",
    "jwt_secret": "x" * 43,
    "bot_token": FAKE_TOKEN,
    "cors_origins": "https://panel.example.com",
    "_env_file": None,
}


def production(**overrides: object) -> Settings:
    return Settings(**{**SAFE_PRODUCTION, **overrides})  # type: ignore[arg-type]


def test_a_correctly_configured_production_env_loads() -> None:
    settings = production()
    assert settings.is_production
    assert settings.cors_origin_list == ["https://panel.example.com"]


def test_the_placeholder_secret_cannot_reach_production() -> None:
    """It is printed in `config.py`, so anyone could mint session tokens."""
    with pytest.raises(ValidationError, match="placeholder"):
        production(jwt_secret=PLACEHOLDER_JWT_SECRET)


def test_a_short_secret_cannot_reach_production() -> None:
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        production(jwt_secret="short-but-not-the-placeholder")


def test_a_wildcard_cors_origin_cannot_reach_production() -> None:
    """`*` would let any page drive the API with a stolen token."""
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        production(cors_origins="*")


def test_a_webhook_without_a_secret_cannot_reach_production() -> None:
    """Without it, anyone who learns the URL can post fabricated updates."""
    with pytest.raises(ValidationError, match="WEBHOOK_SECRET"):
        production(use_webhook=True, webhook_secret="")


def test_development_keeps_the_convenient_defaults() -> None:
    """`task api` and `pytest` must work with no setup at all."""
    settings = Settings(app_env="development", _env_file=None)
    assert settings.jwt_secret == PLACEHOLDER_JWT_SECRET
    assert not settings.is_production
