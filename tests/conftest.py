"""Deterministic integration-test settings; never used by runtime services."""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "123456:AAAtest-token-for-ci-only")
