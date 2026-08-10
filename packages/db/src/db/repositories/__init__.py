"""Repository layer: all SQLAlchemy access lives here.

Services depend on repositories, never on the session directly, so domain logic
stays testable without a database.
"""

from db.repositories.admins import AdminRepository
from db.repositories.ai import AiCheckLogRepository
from db.repositories.captcha import CaptchaRepository
from db.repositories.chats import ChatRepository, ModuleConfigRepository
from db.repositories.global_bans import GlobalBanRepository
from db.repositories.moderation import ModerationLogRepository, PunishmentRepository, WarnRepository
from db.repositories.payments import PaymentRepository
from db.repositories.posts import ScheduledPostRepository
from db.repositories.reputation import ReputationRepository
from db.repositories.stats import StatsRepository
from db.repositories.triggers import TriggerRepository
from db.repositories.users import TgUserRepository

__all__ = [
    "AdminRepository",
    "AiCheckLogRepository",
    "CaptchaRepository",
    "ChatRepository",
    "GlobalBanRepository",
    "ModerationLogRepository",
    "ModuleConfigRepository",
    "PaymentRepository",
    "PunishmentRepository",
    "ReputationRepository",
    "ScheduledPostRepository",
    "StatsRepository",
    "TgUserRepository",
    "TriggerRepository",
    "WarnRepository",
]
