"""Kompakte Wetter-Ticker-Formatierung für MeshCore (LoRa payload ~140 chars).

Output-Beispiel (3 Zeilen):
    🌦 OWL Langenberg 14:00
    Jetzt: 12°C SW18 (B35) wolkig
    +6h: 14°C S22 (B38) Regen 0.8mm
    +12h: 9°C W15 bedeckt
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .windy import Hour


TZ_BERLIN = ZoneInfo("Europe/Berlin")


def _nearest(hours: list[Hour], target: datetime) -> Hour | None:
    if not hours:
        return None
    return min(hours, key=lambda h: abs((h.ts - target).total_seconds()))


def _line(label: str, h: Hour) -> str:
    gust = f" (B{round(h.gust_kmh)})" if h.gust_kmh >= h.wind_kmh + 5 else ""
    rain = f" Regen {h.precip_mm:.1f}mm" if h.precip_mm >= 0.2 else ""
    return f"{label}: {round(h.temp_c)}°C {h.dir_cardinal}{round(h.wind_kmh)}{gust} {h.cloud_desc}{rain}"


def format_ticker(location_name: str, hours: list[Hour], now: datetime | None = None) -> str:
    """Formatiert einen 3-Punkt-Forecast (jetzt / +6h / +12h) als knappe Message."""
    if now is None:
        now = datetime.now(tz=timezone.utc)
    h_now = _nearest(hours, now)
    h_6 = _nearest(hours, now + timedelta(hours=6))
    h_12 = _nearest(hours, now + timedelta(hours=12))

    local_hm = now.astimezone(TZ_BERLIN).strftime("%H:%M")
    lines = [f"🌦 OWL {location_name} {local_hm}"]
    if h_now:
        lines.append(_line("Jetzt", h_now))
    if h_6:
        lines.append(_line("+6h", h_6))
    if h_12:
        lines.append(_line("+12h", h_12))
    return "\n".join(lines)
