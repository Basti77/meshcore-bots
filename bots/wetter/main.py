"""meshbot-wetter — posts a Windy-based 3-point forecast to a Matrix room every 6 hours.

The bridge (meshcore-matrix-bridge) picks up the message and forwards it onto
the mesh as the wetter channel.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from shared.matrix_sender import SimpleMatrixSender

from .windy import fetch_forecast
from .format import format_ticker


log = logging.getLogger("meshbot-wetter")

# Backoff between fetch attempts within one slot. A transient open-meteo 503
# at the full hour must not cost the whole 6h slot (happened 2026-07-04).
FETCH_BACKOFF_S = (30, 120, 300)
# One in-slot send retry, then the slot counts as failed.
SEND_RETRY_DELAY_S = 60
# After this many consecutive failed slots the bot alerts + exits non-zero,
# so the problem surfaces in systemd/journal instead of a silent zombie.
MAX_CONSECUTIVE_SEND_FAILURES = 2


def _env(key: str, default: str | None = None, required: bool = False) -> str:
    v = os.environ.get(key, default)
    if required and not v:
        raise SystemExit(f"env {key} required")
    return v  # type: ignore[return-value]


def _alert(msg: str) -> None:
    """Best-effort out-of-band alert via sysnotify (FHEM MatrixBot → Raum 'ich').

    Uses a different Matrix account/path than this bot, so it still works when
    this bot's token or room permissions are the problem."""
    try:
        subprocess.run(["/usr/local/bin/sysnotify", "ich", msg], timeout=20, check=False)
    except Exception:
        log.warning("sysnotify alert failed", exc_info=True)


async def _fetch_with_retry(cfg: dict) -> list:
    attempts = 1 + len(FETCH_BACKOFF_S)
    for i in range(attempts):
        if i:
            await asyncio.sleep(FETCH_BACKOFF_S[i - 1])
        try:
            hours = await asyncio.to_thread(
                fetch_forecast, cfg["lat"], cfg["lon"], cfg["model"]
            )
        except Exception as e:
            log.warning("open-meteo fetch failed (attempt %d/%d): %s", i + 1, attempts, e)
            continue
        if hours:
            return hours
        log.warning("open-meteo returned no hours (attempt %d/%d)", i + 1, attempts)
    log.error("open-meteo fetch gave up after %d attempts", attempts)
    return []


async def _post_forecast(
    sender: SimpleMatrixSender, room_id: str, cfg: dict, health: dict
) -> None:
    hours = await _fetch_with_retry(cfg)
    if not hours:
        # Upstream problem, not ours — the next slot retries with fresh data.
        return
    msg = format_ticker(cfg["location_name"], hours)
    log.info("posting forecast to %s:\n%s", room_id, msg)

    ok = False
    try:
        ok = await sender.send_text(room_id, msg)
        if not ok:
            await asyncio.sleep(SEND_RETRY_DELAY_S)
            ok = await sender.send_text(room_id, msg)
    except Exception:
        log.exception("matrix send raised")

    if not ok:
        health["send_failures"] += 1
        log.error("matrix send failed (%d consecutive slot(s))", health["send_failures"])
        if health["send_failures"] >= MAX_CONSECUTIVE_SEND_FAILURES:
            _alert(
                f"meshbot-wetter: {health['send_failures']} Wetter-Posts in Folge "
                f"fehlgeschlagen (Raum {room_id}) — Bot beendet sich für Neustart. "
                f"Token/Raum-Rechte prüfen: journalctl --user -u meshbot-wetter"
            )
            health["exit_code"] = 1
            health["stop"].set()
        return

    health["send_failures"] = 0
    # persist last *successful* post
    state_dir = Path(cfg["state_dir"])
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "last.json").write_text(json.dumps({
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "message": msg,
    }))


async def _async_main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )

    cfg = {
        "homeserver": _env("MATRIX_HOMESERVER", required=True),
        "user_id": _env("MATRIX_USER_ID", required=True),
        "access_token": _env("MATRIX_ACCESS_TOKEN", required=True),
        "device_id": _env("MATRIX_DEVICE_ID", "MESHBOT_WETTER"),
        "room": _env("WETTER_ROOM", required=True),  # alias or !id
        "model": _env("OPENMETEO_MODEL", "icon_eu"),
        "lat": float(_env("LOCATION_LAT", "51.7634")),
        "lon": float(_env("LOCATION_LON", "8.3213")),
        "location_name": _env("LOCATION_NAME", "Langenberg"),
        "schedule_hours": int(_env("SCHEDULE_HOURS", "6")),
        "post_on_startup": _env("POST_ON_STARTUP", "1") == "1",
        "state_dir": _env("STATE_DIR", str(Path.home() / ".local/state/meshbot-wetter")),
    }

    sender = SimpleMatrixSender(
        cfg["homeserver"], cfg["user_id"], cfg["access_token"], cfg["device_id"]
    )
    await sender.connect()

    # Resolve alias if needed; join if not already in room.
    room_id = cfg["room"]
    if room_id.startswith("#"):
        rid = await sender.resolve_alias(room_id)
        if not rid:
            # Never fall back to posting to the alias itself: Synapse rejects
            # sends to an alias path with 403 "not in room", which send_text
            # only logs as a warning -> the bot looks dead for days.
            raise SystemExit(f"could not resolve alias {room_id}; refusing to post to an alias")
        room_id = rid
    # Always attempt a join (idempotent if already member). Public rooms only.
    await sender.join(room_id)
    cfg["room_id"] = room_id
    log.info("wetter room id: %s", room_id)

    stop = asyncio.Event()
    health = {"send_failures": 0, "exit_code": 0, "stop": stop}

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _post_forecast,
        "cron",
        hour=f"*/{cfg['schedule_hours']}",
        minute=0,
        args=[sender, room_id, cfg, health],
        id="forecast",
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.start()

    if cfg["post_on_startup"]:
        await _post_forecast(sender, room_id, cfg, health)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    log.info("meshbot-wetter up, every %dh", cfg["schedule_hours"])
    await stop.wait()

    scheduler.shutdown(wait=False)
    await sender.close()
    if health["exit_code"]:
        raise SystemExit(health["exit_code"])


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
