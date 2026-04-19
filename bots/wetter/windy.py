"""Windy Point Forecast API wrapper — minimal.

Docs: https://api.windy.com/point-forecast/docs
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests


log = logging.getLogger(__name__)

WINDY_URL = "https://api.windy.com/api/point-forecast/v2"


@dataclass
class Hour:
    ts: datetime          # UTC
    temp_c: float
    wind_kmh: float
    gust_kmh: float
    dir_deg: float
    precip_mm: float
    rh_pct: float
    pressure_hpa: float
    lclouds_pct: float
    mclouds_pct: float
    hclouds_pct: float

    @property
    def dir_cardinal(self) -> str:
        dirs = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]
        return dirs[int((self.dir_deg + 22.5) / 45) % 8]

    @property
    def cloud_desc(self) -> str:
        total = max(self.lclouds_pct, self.mclouds_pct, self.hclouds_pct)
        if total < 25:
            return "klar"
        if total < 60:
            return "wolkig"
        if total < 85:
            return "bewölkt"
        return "bedeckt"


def fetch_forecast(api_key: str, lat: float, lon: float, model: str = "iconEu") -> list[Hour]:
    body = {
        "lat": lat,
        "lon": lon,
        "model": model,
        "parameters": ["temp", "wind", "windGust", "dewpoint", "rh", "pressure", "lclouds", "mclouds", "hclouds", "precip"],
        "levels": ["surface"],
        "key": api_key,
    }
    r = requests.post(WINDY_URL, json=body, timeout=20)
    r.raise_for_status()
    data = r.json()
    ts_ms = data["ts"]
    hours: list[Hour] = []
    for i, t in enumerate(ts_ms):
        dt = datetime.fromtimestamp(t / 1000, tz=timezone.utc)
        try:
            # Windy wind components: wind_u-surface, wind_v-surface (m/s)
            u = data["wind_u-surface"][i]
            v = data["wind_v-surface"][i]
            import math
            ws_ms = math.sqrt(u * u + v * v)
            wind_kmh = ws_ms * 3.6
            # direction FROM which wind blows; Windy u/v are "towards", convert
            dir_to = (math.degrees(math.atan2(-u, -v)) + 360) % 360
            gust_ms = data.get("gust-surface", [ws_ms] * len(ts_ms))[i]
            gust_kmh = gust_ms * 3.6
            temp_k = data["temp-surface"][i]
            temp_c = temp_k - 273.15
            precip = data.get("past3hprecip-surface", [0.0] * len(ts_ms))[i]
            rh = data.get("rh-surface", [0.0] * len(ts_ms))[i]
            p = data.get("pressure-surface", [0.0] * len(ts_ms))[i]
            lc = data.get("lclouds-surface", [0.0] * len(ts_ms))[i]
            mc = data.get("mclouds-surface", [0.0] * len(ts_ms))[i]
            hc = data.get("hclouds-surface", [0.0] * len(ts_ms))[i]
            hours.append(Hour(
                ts=dt, temp_c=temp_c, wind_kmh=wind_kmh, gust_kmh=gust_kmh,
                dir_deg=dir_to, precip_mm=precip, rh_pct=rh,
                pressure_hpa=p / 100.0 if p > 10000 else p,
                lclouds_pct=lc, mclouds_pct=mc, hclouds_pct=hc,
            ))
        except (KeyError, IndexError, TypeError) as e:
            log.debug("skip idx %d: %s", i, e)
            continue
    return hours
