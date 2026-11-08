"""Thin client for the Open-Meteo Air Quality API (free, no key).

Docs: https://open-meteo.com/en/docs/air-quality-api
Set OPENMETEO_AQ_URL to point at a mock server in tests.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable, Optional

import pandas as pd

BASE_URL = os.environ.get("OPENMETEO_AQ_URL", "https://air-quality-api.open-meteo.com/v1/air-quality")

# our key -> Open-Meteo variable name
VARIABLES = {
    "pm2_5": "pm2_5",
    "pm10": "pm10",
    "no2": "nitrogen_dioxide",
    "so2": "sulphur_dioxide",
    "co": "carbon_monoxide",
    "o3": "ozone",
}


class OpenMeteoError(RuntimeError):
    pass


def _get_json(url: str, retries: int = 4) -> object:
    delay = 2.0
    last: Optional[Exception] = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "india-aqi-forecast/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503, 504):
                last = OpenMeteoError(f"HTTP {e.code}: {body}")
                time.sleep(delay)
                delay *= 2
                continue
            raise OpenMeteoError(f"HTTP {e.code}: {body}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            time.sleep(delay)
            delay *= 2
    raise OpenMeteoError(f"request failed after {retries} attempts: {last}")


def fetch_hourly(
    cities: Iterable,
    *,
    past_days: Optional[int] = None,
    forecast_days: int = 1,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """Hourly pollutant concentrations (local India time) for several cities in one request.

    Returns columns: city, time, pm2_5, pm10, no2, so2, co (mg/m3), o3.
    """
    cities = list(cities)
    params = {
        "latitude": ",".join(f"{c.lat:.4f}" for c in cities),
        "longitude": ",".join(f"{c.lon:.4f}" for c in cities),
        "hourly": ",".join(VARIABLES.values()),
        "timezone": "Asia/Kolkata",
    }
    if start and end:
        params["start_date"], params["end_date"] = start, end
    else:
        params["past_days"] = past_days if past_days is not None else 3
        params["forecast_days"] = forecast_days
    payload = _get_json(f"{BASE_URL}?{urllib.parse.urlencode(params)}")
    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(cities):
        raise OpenMeteoError(f"expected {len(cities)} locations, got {len(items)}")

    frames = []
    for city, item in zip(cities, items):
        h = item.get("hourly")
        if not h or "time" not in h:
            raise OpenMeteoError(f"no hourly block for {city.name}: {str(item)[:200]}")
        df = pd.DataFrame({"time": pd.to_datetime(h["time"])})
        for key, om in VARIABLES.items():
            df[key] = pd.to_numeric(pd.Series(h.get(om), dtype="float64"), errors="coerce")
        df["co"] = df["co"] / 1000.0  # ug/m3 -> mg/m3 (CPCB unit)
        df.insert(0, "city", city.name)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)
