"""Job registry — where deferred work announces itself.

DECISION: jobs register into these lists through a decorator instead of being
listed in `WorkerSettings`. A job then lives in exactly one place (its own
module, next to its `@job`), and `worker.settings` never has to import the job
modules it configures — which is what would make the import graph circular.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from arq import cron

FUNCTIONS: list[Any] = []
CRON_JOBS: list[Any] = []


def job[JobFunc: Callable[..., Any]](func: JobFunc) -> JobFunc:
    """Register an ARQ task. Its `__name__` must match a `JobName` value."""
    FUNCTIONS.append(func)
    return func


def scheduled[JobFunc: Callable[..., Any]](
    **cron_kwargs: Any,
) -> Callable[[JobFunc], JobFunc]:
    """Register a cron job: `@scheduled(minute={0, 30})`.

    A cron job is *not* also queued by name; if something needs both, register it
    with `@job` as well.
    """

    def decorator(func: JobFunc) -> JobFunc:
        CRON_JOBS.append(cron(func, **cron_kwargs))
        return func

    return decorator


__all__ = ["CRON_JOBS", "FUNCTIONS", "job", "scheduled"]
