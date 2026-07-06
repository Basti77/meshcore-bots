"""meshbot-nina — NINA-Warnungen NRW → Matrix-Room → MeshCore #nrw.

Pollt warnung.bund.de alle 90 s für 53 NRW-Kreise/kreisfreie Städte,
filtert nach Severity, gruppiert pro Tick und schickt eine Matrix-Message
pro Gruppe in den Bridge-Room. Die meshcore-matrix-bridge zerlegt für LoRa.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

from shared.matrix_sender import SimpleMatrixSender

from . import poll as nina


log = logging.getLogger("meshbot-nina")


def _env(key: str, default: str | None = None, required: bool = False) -> str:
    v = os.environ.get(key, default)
    if required and not v:
        raise SystemExit(f"env {key} required")
    return v  # type: ignore[return-value]


async def _async_main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )

    # Provider-spezifische Schwellen: DWD-Wetter ab "Severe" (sonst Mesh-Flut bei
    # Sturmlage), alles andere (MOWAS/BIWAPP/KATWARN/police/lhp) ab "Minor".
    # MOWAS klassifiziert lokale Brände/Bombenfunde/Geruchslagen typisch als Minor.
    # NINA_SEVERITY_MIN setzt die Default-Schwelle für alle Provider ohne Override,
    # NINA_SEVERITY_MIN_DWD überschreibt nur den DWD-Provider.
    severity_min: dict[str, str] = {
        "_default": _env("NINA_SEVERITY_MIN", "Minor"),
        "DWD": _env("NINA_SEVERITY_MIN_DWD", "Severe"),
    }

    # Themen-Blacklist (Substring/regex, case-insensitive). Standard: nur „geruch"
    # (Geruchsbelästigungs-Meldungen sollen nicht übers Mesh raus). Override via env.
    exclude_spec = os.environ.get("NINA_EXCLUDE_PATTERNS")
    exclude_patterns = nina.compile_exclude_patterns(exclude_spec)

    cfg = {
        "homeserver": _env("MATRIX_HOMESERVER", required=True),
        "user_id": _env("MATRIX_USER_ID", required=True),
        "access_token": _env("MATRIX_ACCESS_TOKEN", required=True),
        "device_id": _env("MATRIX_DEVICE_ID", "MESHBOT_NINA"),
        "room": _env("NINA_ROOM", required=True),  # alias or !id
        "severity_min": severity_min,
        "forward_cancel": _env("NINA_FORWARD_CANCEL", "1") == "1",
        "forward_update": _env("NINA_FORWARD_UPDATE", "1") == "1",
        "poll_interval": int(_env("NINA_POLL_INTERVAL", "90")),
        "state_dir": _env("STATE_DIR", str(Path.home() / ".local/state/meshbot-nina")),
    }

    db_path = Path(cfg["state_dir"]) / "nina_seen.db"
    conn = nina.db_open(db_path)

    sender = SimpleMatrixSender(
        cfg["homeserver"], cfg["user_id"], cfg["access_token"], cfg["device_id"]
    )
    await sender.connect()

    room_id = cfg["room"]
    if room_id.startswith("#"):
        rid = await sender.resolve_alias(room_id)
        if not rid:
            # Never fall back to posting to the alias string: Synapse rejects
            # that with 403 "not in room" on every send and the bot looks
            # alive while nothing reaches the mesh (2026-05-22 incident).
            raise SystemExit(f"could not resolve alias {room_id}; refusing to post to an alias")
        room_id = rid
    await sender.join(room_id)
    log.info("nina room id: %s", room_id)

    async def send(text: str) -> None:
        await sender.send_text(room_id, text)

    sev_summary = ", ".join(f"{k}>={v}" for k, v in cfg["severity_min"].items())
    excl_summary = ", ".join(p.pattern for p in exclude_patterns) or "—"
    log.info(
        "meshbot-nina up — sev: %s, exclude: [%s], %d AGS, every %ds → %s",
        sev_summary, excl_summary, len(nina.AGS_LIST), cfg["poll_interval"], room_id,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    while not stop.is_set():
        try:
            await nina.run_tick(
                conn, send,
                cfg["severity_min"],
                cfg["forward_cancel"],
                cfg["forward_update"],
                exclude_patterns,
            )
        except Exception as e:
            log.exception("tick crash: %s", e)
        try:
            await asyncio.wait_for(stop.wait(), timeout=cfg["poll_interval"])
        except asyncio.TimeoutError:
            pass

    await sender.close()
    conn.close()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
