"""Who may open the control panel.

DECISION: one function, called from one place. The rule is currently "the
platform's superadmin list and nobody else", which is what `/admin` was asked to
enforce — but it is the kind of rule that changes as soon as a paying customer
who is not a platform operator wants their own panel. Keeping it here means
widening it to "operator, or admin of at least one connected chat" is an edit to
this file rather than a hunt through handlers.

DECISION: this is tidiness, not the security boundary. The API re-derives every
permission from the Mini App's signed `initData` on every request, so a user who
somehow obtains the URL still cannot read a chat they do not administer. What
this gate buys is that the panel is not advertised to people it is not for.
"""

from __future__ import annotations

from shared.config import get_settings


def may_open_panel(tg_user_id: int) -> bool:
    """Whether this account may be handed the Mini App."""
    return tg_user_id in get_settings().superadmin_id_list


__all__ = ["may_open_panel"]
