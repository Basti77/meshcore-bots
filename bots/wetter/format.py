"""Kompakte Wetter-Ticker-Formatierung für MeshCore (LoRa payload ~140 chars).

Output-Beispiel (3 Zeilen):
    ⛈ OWL Langenberg 14:00
    Jetzt: 12°C SW18 B35 km/h wolkig Regen 0.8mm
    +6h: 14°C S22 km/h klar
    +12h: 9°C W15 km/h bedeckt
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .windy import Hour


TZ_BERLIN = ZoneInfo("Europe/Berlin")

# WMO weather code → Emoji
# https://open-meteo.com/en/docs#weathervariables
_WMO_EMOJI = {
    0:  "☀️",          # klar
    1:  "🌤️",          # überwiegend klar
    2:  "⛅",          # wechselnd bewölkt
    3:  "☁️",          # bedeckt
    45: "🌫️",  48: "🌫️",                    # Nebel
    51: "🌦️",  53: "🌦️",  55: "🌧️",        # Nieselregen
    56: "🌧️",  57: "🌧️",                    # gefrierender Regen
    61: "🌦️",  63: "🌧️",  65: "🌧️",        # Regen
    66: "🌧️",  67: "🌧️",                    # gefrierender Regen
    71: "🌨️",  73: "🌨️",  75: "❄️",         # Schnee
    77: "🌨️",                               # Schneegriesel
    80: "🌦️",  81: "🌧️",  82: "🌧️",        # Schauer
    85: "🌨️",  86: "❄️",                    # Schneeschauer
    95: "⛈️",                               # Gewitter
    96: "⛈️",  99: "⛈️",                    # Gewitter mit Hagel
}


def _weather_emoji(h: Hour) -> str:
    # Sturm überschreibt alles (Böen >= 62 km/h = Bft 8)
    if h.gust_kmh >= 62:
        return "🌪️" if h.precip_mm < 0.2 else "⛈️"
    return _WMO_EMOJI.get(h.weather_code, "🌦️")


def _nearest(hours: list[Hour], target: datetime) -> Hour | None:
    if not hours:
        return None
    return min(hours, key=lambda h: abs((h.ts - target).total_seconds()))


def _line(label: str, h: Hour) -> str:
    gust = f" B{round(h.gust_kmh)}" if h.gust_kmh >= h.wind_kmh + 5 else ""
    rain = f" Regen {h.precip_mm:.1f}mm" if h.precip_mm >= 0.2 else ""
    wind = f"{h.dir_cardinal}{round(h.wind_kmh)}{gust} km/h"
    return f"{label}: {round(h.temp_c)}°C {wind} {h.cloud_desc}{rain}"


def format_ticker(location_name: str, hours: list[Hour], now: datetime | None = None) -> str:
    """Formatiert einen 3-Punkt-Forecast (jetzt / +6h / +12h) als knappe Message."""
    if now is None:
        now = datetime.now(tz=timezone.utc)
    h_now = _nearest(hours, now)
    h_6   = _nearest(hours, now + timedelta(hours=6))
    h_12  = _nearest(hours, now + timedelta(hours=12))

    emoji = _weather_emoji(h_now) if h_now else "🌦️"
    local_hm = now.astimezone(TZ_BERLIN).strftime("%H:%M")
    lines = [f"{emoji} OWL {location_name} {local_hm}"]
    if h_now:
        lines.append(_line("Jetzt", h_now))
    if h_6:
        lines.append(_line("+6h", h_6))
    if h_12:
        lines.append(_line("+12h", h_12))
    return "\n".join(lines)
