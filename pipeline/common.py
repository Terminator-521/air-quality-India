"""Shared paths and helpers. Every path can be redirected with AQ_ROOT for tests."""
import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("AQ_ROOT", Path(__file__).resolve().parent.parent))
RAW = ROOT / "data" / "raw"
LIVE = ROOT / "data" / "live"
PROCESSED = ROOT / "data" / "processed"
PUBLIC_DATA = ROOT / "public" / "data"

HOURLY_CSV = LIVE / "hourly.csv"          # rolling window of recent hourly readings
DAILY_CSV = LIVE / "daily.csv"            # permanent daily table built from Open-Meteo
DATASET_CSV = PROCESSED / "daily_all.csv.gz"

POLLUTANTS = ["pm2_5", "pm10", "no2", "so2", "co", "o3"]
POLLUTANT_LABELS = {"pm2_5": "PM2.5", "pm10": "PM10", "no2": "NO2", "so2": "SO2", "co": "CO", "o3": "O3"}
LABEL_TO_KEY = {v: k for k, v in POLLUTANT_LABELS.items()}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def ensure_dirs() -> None:
    for p in (LIVE, PROCESSED, PUBLIC_DATA, PUBLIC_DATA / "history"):
        p.mkdir(parents=True, exist_ok=True)
