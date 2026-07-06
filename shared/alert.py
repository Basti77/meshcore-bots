"""Best-effort out-of-band alerting for bots.

Goes through sysnotify (FHEM MatrixBot → Raum "ich"), i.e. a different
Matrix account and code path than the bot itself — so it still works when
the bot's own token or room permissions are exactly what broke.
"""
from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

SYSNOTIFY = "/usr/local/bin/sysnotify"


def alert(msg: str) -> None:
    try:
        subprocess.run([SYSNOTIFY, "ich", msg], timeout=20, check=False)
    except Exception:
        log.warning("sysnotify alert failed", exc_info=True)
