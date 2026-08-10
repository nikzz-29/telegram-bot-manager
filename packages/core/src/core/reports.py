"""Rendering a statistics overview as chat-facing text.

Both `/stats` in the bot and the daily digest in the worker send the same
report, so the renderer lives here rather than in either process. The Mini App
gets the raw `StatsOverview` and draws a real chart from it.

DECISION: a text sparkline rather than a rendered PNG. It costs nothing to
produce, needs no image library in either runtime image, survives being
forwarded, and reads correctly on a phone in a group of a thousand people. The
Mini App is where a chart with axes belongs.
"""

from __future__ import annotations

from typing import Final

from i18n.runtime import Translator
from shared.schemas.api import StatsOverview

# Bars for the activity sparkline, lightest to heaviest.
BLOCKS: Final = "▁▂▃▄▅▆▇█"

# One column per day, and never so wide that a phone wraps the line.
MAX_COLUMNS: Final = 14

# How many names a top-list prints. Ten is what the spec asks for.
TOP_LIMIT: Final = 10


def sparkline(values: list[int]) -> str:
    """A one-line activity chart. Empty input renders as an empty string."""
    if not values:
        return ""
    trimmed = values[-MAX_COLUMNS:]
    peak = max(trimmed)
    if peak <= 0:
        return BLOCKS[0] * len(trimmed)
    span = len(BLOCKS) - 1
    return "".join(BLOCKS[round(value / peak * span)] for value in trimmed)


def _top_lines(overview: StatsOverview, t: Translator) -> list[str]:
    if not overview.top_users:
        return []
    lines = [t("stats-top-title")]
    for place, entry in enumerate(overview.top_users[:TOP_LIMIT], start=1):
        name = entry.display_name or (f"@{entry.username}" if entry.username else "")
        lines.append(
            t(
                "stats-top-row",
                place=place,
                user=name or str(entry.tg_user_id),
                messages=entry.messages,
            )
        )
    return lines


def format_overview(overview: StatsOverview, *, title: str, t: Translator) -> str:
    """Render an overview as the message the chat receives."""
    lines = [
        t("stats-title", chat=title, days=overview.period_days),
        t("stats-messages", count=overview.total_messages),
        t("stats-active", count=overview.total_active_users),
        t("stats-joins", count=overview.total_joins),
        t("stats-leaves", count=overview.total_leaves),
        t("stats-growth", count=overview.net_growth),
    ]
    chart = sparkline([point.messages for point in overview.series])
    if chart:
        lines.append(t("stats-chart", chart=chart))
    lines.extend(_top_lines(overview, t))
    if not overview.series:
        lines.append(t("stats-empty"))
    return "\n".join(lines)


__all__ = ["BLOCKS", "MAX_COLUMNS", "TOP_LIMIT", "format_overview", "sparkline"]
