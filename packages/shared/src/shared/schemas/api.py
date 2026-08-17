"""Request/response DTOs for the Mini App REST API.

These drive the generated TypeScript client, so every field the front-end
needs must be represented here rather than assembled ad hoc in a router.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.enums import (
    AdminRole,
    ChatType,
    PaymentProvider,
    PaymentStatus,
    Plan,
    PunishmentType,
    ScheduleKind,
    TriggerMatch,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
class AuthRequest(BaseModel):
    """Raw `initData` string handed over by the Telegram WebApp SDK."""

    init_data: str = Field(min_length=1, max_length=8_192)


class WebsiteLoginRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class AuthUser(ApiModel):
    tg_user_id: int
    username: str | None = None
    first_name: str = ""
    last_name: str | None = None
    language_code: str = "en"
    is_superadmin: bool = False
    is_premium: bool = False
    has_photo: bool = False
    photo_url: str | None = None


class AuthResponse(ApiModel):
    access_token: str
    expires_in: int
    user: AuthUser


class UserProfile(ApiModel):
    """The user-facing profile shown outside a chat editor."""

    user: AuthUser
    display_name: str
    first_seen_at: datetime | None = None
    chats_total: int = 0
    chats_owned: int = 0
    chats_admin: int = 0
    paid_chats: int = 0
    total_members: int = 0


# --------------------------------------------------------------------------
# chats
# --------------------------------------------------------------------------
class ChatSummary(ApiModel):
    id: int
    tg_chat_id: int
    title: str
    type: ChatType
    plan: Plan
    plan_expires_at: datetime | None = None
    is_active: bool = True
    role: AdminRole = AdminRole.ADMIN
    members_count: int | None = None


class ChatDetail(ChatSummary):
    owner_tg_id: int | None = None
    language: str = "ru"
    timezone: str = "UTC"
    modules: dict[str, bool] = Field(default_factory=dict)
    features: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class ChatUpdate(BaseModel):
    language: str | None = Field(default=None, pattern="^(ru|en)$")
    timezone: str | None = None


class ChatBotPermissions(ApiModel):
    reachable: bool = True
    status: str = "unknown"
    is_admin: bool = False
    privacy_mode_disabled: bool = False
    can_read_messages: bool = False
    can_send_messages: bool = False
    can_delete_messages: bool = False
    can_restrict_members: bool = False
    can_invite_users: bool = False
    can_manage_topics: bool = False
    issues: list[str] = Field(default_factory=list)


class ModuleConfigResponse(ApiModel):
    module: str
    enabled: bool
    required_plan: Plan
    available: bool
    config: dict[str, Any]


class ModuleConfigUpdate(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None


# --------------------------------------------------------------------------
# platform metadata (drives the Mini App's sections and paywall)
# --------------------------------------------------------------------------
class CommandMeta(ApiModel):
    name: str
    description_key: str
    admin_only: bool = True


class ModuleMeta(ApiModel):
    """One module as the Mini App needs to draw it, before any chat is chosen."""

    name: str
    title_key: str
    description_key: str
    required_plan: Plan
    mandatory: bool = False
    enabled_by_default: bool = False
    section_key: str | None = None
    icon: str = "settings"
    order: int = 100
    commands: list[CommandMeta] = Field(default_factory=list)
    # JSON Schema of the module's config model — the settings form is generated
    # from this, so a new option ships without a front-end change.
    config_schema: dict[str, Any] = Field(default_factory=dict)


class PlanMeta(ApiModel):
    plan: Plan
    stars: int = 0
    usd: str = ""
    features: list[str] = Field(default_factory=list)
    limits: dict[str, int] = Field(default_factory=dict)


class PlatformCapabilities(ApiModel):
    """Optional integrations that are actually usable on this deployment.

    Keeping these server-derived prevents the Mini App from sending a customer
    into a checkout or an AI setting which the deployment cannot fulfil.
    """

    payment_providers: list[PaymentProvider] = Field(default_factory=list)
    ai_moderation_available: bool = False


class MetaResponse(ApiModel):
    modules: list[ModuleMeta] = Field(default_factory=list)
    plans: list[PlanMeta] = Field(default_factory=list)
    locales: list[str] = Field(default_factory=list)
    capabilities: PlatformCapabilities


# --------------------------------------------------------------------------
# moderation data
# --------------------------------------------------------------------------
class WarnEntry(ApiModel):
    id: int
    tg_user_id: int
    moderator_tg_id: int
    reason: str
    created_at: datetime
    expires_at: datetime | None = None


class PunishmentEntry(ApiModel):
    id: int
    tg_user_id: int
    moderator_tg_id: int
    type: PunishmentType
    reason: str
    expires_at: datetime | None = None
    active: bool
    created_at: datetime


# --------------------------------------------------------------------------
# triggers
# --------------------------------------------------------------------------
class TriggerButton(BaseModel):
    text: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=1, max_length=2_048)


class TriggerCreate(BaseModel):
    pattern: str = Field(min_length=1, max_length=256)
    match: TriggerMatch = TriggerMatch.CONTAINS
    response: str = Field(min_length=1, max_length=4_000)
    media_file_id: str | None = None
    buttons: list[TriggerButton] = Field(default_factory=list, max_length=8)
    case_sensitive: bool = False
    delete_trigger: bool = False
    enabled: bool = True


class TriggerUpdate(BaseModel):
    pattern: str | None = Field(default=None, min_length=1, max_length=256)
    match: TriggerMatch | None = None
    response: str | None = Field(default=None, min_length=1, max_length=4_000)
    media_file_id: str | None = None
    buttons: list[TriggerButton] | None = None
    case_sensitive: bool | None = None
    delete_trigger: bool | None = None
    enabled: bool | None = None


class TriggerEntry(ApiModel):
    id: int
    pattern: str
    match: TriggerMatch
    response: str
    media_file_id: str | None = None
    buttons: list[TriggerButton] = Field(default_factory=list)
    case_sensitive: bool = False
    delete_trigger: bool = False
    enabled: bool = True
    hits: int = 0


# --------------------------------------------------------------------------
# scheduled posts
# --------------------------------------------------------------------------
class PostCreate(BaseModel):
    title: str = Field(default="", max_length=128)
    content: str = Field(min_length=1, max_length=4_000)
    media_file_id: str | None = None
    buttons: list[TriggerButton] = Field(default_factory=list, max_length=8)
    schedule_kind: ScheduleKind = ScheduleKind.DAILY
    schedule_value: str = Field(min_length=1, max_length=64)
    target_chat_id: int | None = None
    pin: bool = False
    delete_previous: bool = False
    enabled: bool = True


class PostUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=128)
    content: str | None = Field(default=None, min_length=1, max_length=4_000)
    media_file_id: str | None = None
    buttons: list[TriggerButton] | None = None
    schedule_kind: ScheduleKind | None = None
    schedule_value: str | None = Field(default=None, min_length=1, max_length=64)
    target_chat_id: int | None = None
    pin: bool | None = None
    delete_previous: bool | None = None
    enabled: bool | None = None


class PostEntry(ApiModel):
    id: int
    title: str
    content: str
    media_file_id: str | None = None
    buttons: list[TriggerButton] = Field(default_factory=list)
    schedule_kind: ScheduleKind
    schedule_value: str
    target_chat_id: int | None = None
    next_run_at: datetime | None = None
    pin: bool = False
    delete_previous: bool = False
    enabled: bool = True


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------
class StatPoint(ApiModel):
    date: date
    messages: int = 0
    active_users: int = 0
    joins: int = 0
    leaves: int = 0
    moderation_actions: int = 0


class TopUser(ApiModel):
    tg_user_id: int
    messages: int
    username: str | None = None
    display_name: str | None = None


class StatsOverview(ApiModel):
    period_days: int
    total_messages: int
    total_active_users: int
    total_joins: int
    total_leaves: int
    net_growth: int
    series: list[StatPoint] = Field(default_factory=list)
    top_users: list[TopUser] = Field(default_factory=list)


class DashboardTotals(ApiModel):
    """Totals for one dashboard window, across one or more chats."""

    messages: int = 0
    active_users: int = 0
    joins: int = 0
    leaves: int = 0
    net_growth: int = 0
    moderation_actions: int = 0


class ModerationBreakdownEntry(ApiModel):
    action: str
    count: int


class DashboardModeration(ApiModel):
    total: int = 0
    warns: int = 0
    restrictions: int = 0
    mine: int = 0
    automated: int = 0
    moderators: int = 0
    breakdown: list[ModerationBreakdownEntry] = Field(default_factory=list)


class UserDashboard(ApiModel):
    """Aggregated user dashboard for the global Mini App shell."""

    period_days: int
    selected_chat_id: int | None = None
    analytics_available: bool = False
    totals: DashboardTotals = Field(default_factory=DashboardTotals)
    previous: DashboardTotals = Field(default_factory=DashboardTotals)
    # Percentage change for the same metric in `totals` vs `previous`.
    # `None` means there is no meaningful denominator (a new metric).
    deltas_percent: dict[str, float | None] = Field(default_factory=dict)
    series: list[StatPoint] = Field(default_factory=list)
    moderation: DashboardModeration = Field(default_factory=DashboardModeration)
    top_users: list[TopUser] = Field(default_factory=list)
    chats: list[ChatSummary] = Field(default_factory=list)


# --------------------------------------------------------------------------
# reputation
# --------------------------------------------------------------------------
class ReputationEntry(ApiModel):
    tg_user_id: int
    points: int
    level: int
    username: str | None = None
    display_name: str | None = None


class ReputationAdjust(ApiModel):
    """A manual correction, expressed as a delta so concurrent edits compose."""

    delta: int = Field(ge=-100_000, le=100_000)


# --------------------------------------------------------------------------
# payments / plans
# --------------------------------------------------------------------------
class PlanOption(ApiModel):
    plan: Plan
    stars: int
    usd: str
    features: list[str]


class PlanCatalog(ApiModel):
    current_plan: Plan
    expires_at: datetime | None = None
    # Set only while the paid term has lapsed and grace has not. `current_plan`
    # already folds grace in, so without this the panel cannot tell a chat still
    # running on Pro from one that has dropped to Free — both arrive as a plan
    # plus a past `expires_at`, and it would report the paid plan as expired.
    grace_until: datetime | None = None
    options: list[PlanOption]


class InvoiceRequest(BaseModel):
    plan: Plan
    provider: PaymentProvider = PaymentProvider.STARS
    months: int = Field(default=1, ge=1, le=12)


class InvoiceResponse(ApiModel):
    provider: PaymentProvider
    invoice_url: str | None = None
    invoice_payload: str
    amount: str
    currency: str


class PaymentEntry(ApiModel):
    id: int
    provider: PaymentProvider
    amount: Decimal
    currency: str
    status: PaymentStatus
    plan: Plan
    months: int
    created_at: datetime


# --------------------------------------------------------------------------
# platform superadmin
# --------------------------------------------------------------------------
class PlatformStats(ApiModel):
    total_chats: int
    active_chats: int
    chats_by_plan: dict[str, int]
    revenue_stars: int
    revenue_usd: Decimal
    global_bans: int


class PlatformSeriesPoint(ApiModel):
    day: date
    chats: int = 0
    new_chats: int = 0
    active_chats: int = 0
    messages: int = 0
    moderation_actions: int = 0
    joins: int = 0
    leaves: int = 0
    subscriptions: int = 0
    revenue_stars: int = 0
    revenue_usd: Decimal = Decimal(0)
    refunds: int = 0
    churned_chats: int = 0


class PlatformTotals(ApiModel):
    chats: int = 0
    active_chats: int = 0
    paying_chats: int = 0
    new_chats: int = 0
    known_users: int = 0
    messages: int = 0
    active_chats_in_window: int = 0
    moderation_actions: int = 0
    subscriptions: int = 0
    refunds: int = 0
    revenue_stars: int = 0
    revenue_usd: Decimal = Decimal(0)
    refunded_stars: int = 0
    refunded_usd: Decimal = Decimal(0)


class PlatformPlanRow(ApiModel):
    plan: Plan
    chats: int = 0
    active_chats: int = 0
    subscriptions: int = 0
    revenue_stars: int = 0
    revenue_usd: Decimal = Decimal(0)


class PlatformDashboard(ApiModel):
    days: int
    start: date
    end: date
    totals: PlatformTotals
    series: list[PlatformSeriesPoint] = Field(default_factory=list)
    plan_mix: list[PlatformPlanRow] = Field(default_factory=list)
    cryptobot_configured: bool = False
    cryptobot_testnet: bool = False
    ai_moderation_available: bool = False


class PlatformUser(ApiModel):
    tg_user_id: int
    username: str | None = None
    first_name: str = ""
    last_name: str | None = None
    is_bot: bool = False
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    admin_chats: int = 0
    owned_chats: int = 0
    is_globally_banned: bool = False
    ban_reports: int = 0
    payments: int = 0
    spent_stars: int = 0
    spent_usd: Decimal = Decimal(0)
    last_payment_at: datetime | None = None


class PlatformUserPage(ApiModel):
    items: list[PlatformUser] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class PlatformUserChat(ApiModel):
    id: int
    tg_chat_id: int
    title: str
    plan: Plan
    plan_expires_at: datetime | None = None
    is_active: bool = True
    owner_tg_id: int | None = None
    members_count: int | None = None


class PlatformUserDetail(ApiModel):
    user: PlatformUser
    chats: list[PlatformUserChat] = Field(default_factory=list)


class PlatformSubscriptionGrant(BaseModel):
    chat_id: int = Field(ge=1)
    plan: Plan
    months: int = Field(default=1, ge=1, le=120)


class PlatformPlanOverride(BaseModel):
    stars: int | None = Field(default=None, ge=0, le=10_000_000)
    usd: str | None = Field(default=None, max_length=16)
    features: list[str] | None = None
    note: str = Field(default="", max_length=2_000)


class PlatformPlanOverrideResponse(ApiModel):
    plan: Plan
    stars: int | None = None
    usd: str | None = None
    features: list[str] | None = None
    note: str = ""
    updated_by: int | None = None
    updated_at: datetime | None = None
    effective_stars: int = 0
    effective_usd: str = ""
    effective_features: list[str] = Field(default_factory=list)


class PlatformCryptoBotSettings(ApiModel):
    configured: bool = False
    testnet: bool = False
    network: str


class PlatformCryptoBotUpdate(BaseModel):
    testnet: bool


class PlatformSettings(ApiModel):
    environment: str
    cryptobot: PlatformCryptoBotSettings
    ai_moderation_available: bool = False
    payment_providers: list[PaymentProvider] = Field(default_factory=list)
    global_ban_chat_threshold: int = 3


class PlatformPayment(ApiModel):
    id: int
    chat_id: int
    tg_chat_id: int
    chat_title: str
    provider: PaymentProvider
    provider_payment_id: str
    amount: Decimal
    currency: str
    status: PaymentStatus
    plan: Plan
    months: int
    payer_tg_id: int | None = None
    created_at: datetime
    period_start: datetime | None = None
    period_end: datetime | None = None
    refunded_at: datetime | None = None
    refund_reason: str = ""


class PlatformPaymentPage(ApiModel):
    items: list[PlatformPayment] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class GlobalBanEntry(ApiModel):
    id: int
    tg_user_id: int
    reason: str
    chat_count: int
    is_active: bool
    created_at: datetime


class GlobalBanCreate(BaseModel):
    tg_user_id: int
    reason: str = Field(default="", max_length=512)


class BroadcastRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)
    plans: list[Plan] = Field(default_factory=list)


class OperationResult(ApiModel):
    ok: bool = True
    detail: str = ""


class Problem(BaseModel):
    """RFC7807-like error body returned by the API exception handler.

    `title` is localized for the caller and safe to show; `detail` is the
    developer-facing message. `code` is the stable machine-readable discriminator
    the Mini App branches on, and `context` carries whatever the error knew (the
    required plan for a paywall, the offending field for a validation failure).
    """

    type: str = "about:blank"
    title: str
    status: int
    detail: str = ""
    instance: str | None = None
    code: str = "domain-error"
    context: dict[str, Any] = Field(default_factory=dict)
