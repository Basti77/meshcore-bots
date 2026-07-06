"""Open-Meteo Point Forecast wrapper (kein API-Key nötig, ICON-EU direkt vom DWD).

Docs: https://open-meteo.com/en/docs
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass
class Hour:
    ts: datetime
    temp_c: float
    wind_kmh: float
    gust_kmh: float
    dir_deg: float
    precip_mm: float
    rh_pct: float
    pressure_hpa: float
    cloud_pct: float
    weather_code: int = 0

    @property
    def dir_cardinal(self) -> str:
        dirs = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]
        return dirs[int((self.dir_deg + 22.5) / 45) % 8]

    @property
    def cloud_desc(self) -> str:
        c = self.cloud_pct
        if c < 25:
            return "klar"
        if c < 60:
            return "wolkig"
        if c < 85:
            return "bewölkt"
        return "bedeckt"


def fetch_forecast(lat: float, lon: float, model: str = "icon_eu") -> list[Hour]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,precipitation,wind_speed_10m,wind_gusts_10m,wind_direction_10m,cloud_cover,weather_code",
        "models": model,
        "forecast_days": 3,
        "timezone": "UTC",
        "wind_speed_unit": "kmh",
    }
    r = requests.get(OPENMETEO_URL, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    log.debug("open-meteo model used: %s", data.get("model", model))

    hourly = data["hourly"]
    hours: list[Hour] = []
    for i, time_str in enumerate(hourly["time"]):
        try:
            dt = datetime.fromisoformat(time_str).replace(tzinfo=timezone.utc)
            hours.append(Hour(
                ts=dt,
                temp_c=hourly["temperature_2m"][i] or 0.0,
                wind_kmh=hourly["wind_speed_10m"][i] or 0.0,
                gust_kmh=hourly["wind_gusts_10m"][i] or 0.0,
                dir_deg=hourly["wind_direction_10m"][i] or 0.0,
                precip_mm=hourly["precipitation"][i] or 0.0,
                rh_pct=0.0,
                pressure_hpa=0.0,
                cloud_pct=hourly["cloud_cover"][i] or 0.0,
                weather_code=int(hourly["weather_code"][i] or 0),
            ))
        except (KeyError, IndexError, TypeError) as e:
            log.debug("skip idx %d: %s", i, e)
    return hours
