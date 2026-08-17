"""Scheduling rules for daily and weekly statistics reports."""

from __future__ import annotations

from datetime import UTC, date, datetime

from shared.schemas.module_configs import StatsConfig
from worker.jobs.stats import _report_windows


def test_reports_use_the_chat_timezone() -> None:
    config = StatsConfig(
        daily_report_enabled=True,
        report_hour_utc=9,
        timezone="Europe/Moscow",
    )

    due = _report_windows(config, now=datetime(2026, 8, 17, 6, 12, tzinfo=UTC))

    assert due == (("daily", 1, date(2026, 8, 16)),)


def test_weekly_report_is_due_on_local_monday_for_previous_week() -> None:
    config = StatsConfig(
        weekly_report_enabled=True,
        report_hour_utc=9,
        timezone="Europe/Moscow",
    )

    due = _report_windows(config, now=datetime(2026, 8, 17, 6, 42, tzinfo=UTC))

    assert due == (("weekly", 7, date(2026, 8, 16)),)


def test_weekly_report_is_not_sent_on_other_days() -> None:
    config = StatsConfig(
        weekly_report_enabled=True,
        report_hour_utc=9,
        timezone="Europe/Moscow",
    )

    due = _report_windows(config, now=datetime(2026, 8, 18, 6, 12, tzinfo=UTC))

    assert due == ()
