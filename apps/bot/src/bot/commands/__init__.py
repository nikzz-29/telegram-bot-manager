"""Routers that are not modules.

A module router is gated by plan and by a per-chat `enabled` switch (see
`bot.modules`). The routers here answer *before* any of that applies: `/start` in
a DM belongs to no chat, so it has no plan to check and no switch to obey.
"""

from __future__ import annotations

__all__: list[str] = []
