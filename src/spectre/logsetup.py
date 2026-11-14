"""Quiet the dependencies before anything else imports them.

twscrape installs its own loguru sink at import time (and removes every existing
one), so the level has to be set through its documented env var *before* the
import happens. Anything twscrape logs below ERROR — migrations, account pool
chatter, per-request INFO lines — is an implementation detail leaking into the
user's terminal, which is exactly what `spectre add` should never show.
"""

from __future__ import annotations

import os
import sys


def configure() -> None:
    level = os.environ.get("SPECTRE_LOG_LEVEL", "ERROR").upper()
    os.environ.setdefault("TWS_LOG_LEVEL", level)
    os.environ.setdefault("TWS_TELEMETRY", "0")

    # Import for the side effect of twscrape replacing the loguru sink, so our
    # sink below is the one that survives.
    try:
        import twscrape  # noqa: F401
    except Exception:  # noqa: BLE001 - never fail import over logging
        return

    from loguru import logger

    logger.remove()
    if level != "OFF":
        logger.add(
            sys.stderr,
            level=level,
            filter=lambda record: record["name"].startswith("spectre"),
            format="<level>{level: <7}</level> | {message}",
        )
