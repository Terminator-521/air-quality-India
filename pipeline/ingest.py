"""Collect live air-quality data from Open-Meteo and store it automatically.

    python -m pipeline.ingest live                 # last few days, run every few hours by GitHub Actions
    python -m pipeline.ingest backfill --start 2022-08-01   # one-off history fill

Storage (both plain CSV, committed back to the repo by the workflow):
  data/live/hourly.csv  rolling ~45 days of hourly readings
  data/live/daily.csv   permanent daily table (24h means; CO and O3 as daily max 8h mean)
                        with the India NAQI and dominant pollutant computed from them
"""
import argparse
import sys
import time
from typing import List

import numpy as np
import pandas as pd

from . import naqi
from .cities import CITIES
from .common import DAILY_CSV, HOURLY_CSV, POLLUTANTS, ensure_dirs
from .openmeteo import OpenMeteoError, fetch_hourly

MIN_HOURS_PER_DAY = 20
HOURLY_KEEP_DAYS = 45
GROUP_SIZE = 20


def now_ist() -> pd.Timestamp:
    return pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)


def aggregate_daily(hourly: pd.DataFrame, before: pd.Timestamp) -> pd.DataFrame:
    """Complete local days strictly before `before` -> daily pollutant table with NAQI."""
    out: List[pd.DataFrame] = []
    for city, g in hourly.groupby("city"):
        g = g.drop_duplicates("time", keep="last").set_index("time").sort_index()
        full = g.reindex(pd.date_range(g.index.min().floor("D"), g.index.max().ceil("h"), freq="h"))
        r8 = full[["co", "o3"]].rolling(8, min_periods=6).mean()
        d = pd.DataFrame({p: full[p].resample("D").mean() for p in ("pm2_5", "pm10", "no2", "so2")})
        d["co"] = r8["co"].resample("D").max()
        d["o3"] = r8["o3"].resample("D").max()
        d["n_hours"] = full["pm2_5"].resample("D").count()
        d = d[(d["n_hours"] >= MIN_HOURS_PER_DAY) & (d.index < before.normalize())]
        if d.empty:
            continue
        d.insert(0, "city", city)
        out.append(d.rename_axis("date").reset_index())
    if not out:
        return pd.DataFrame(columns=["city", "date", *POLLUTANTS, "n_hours", "aqi", "dominant"])
    daily = pd.concat(out, ignore_index=True)
    aqi, dom = naqi.aqi_and_dominant(daily)
    daily["aqi"], daily["dominant"] = aqi, dom
    return daily.dropna(subset=["aqi"])


def upsert(new: pd.DataFrame, path, keys) -> pd.DataFrame:
    if path.exists():
        old = pd.read_csv(path, parse_dates=[k for k in keys if k in ("date", "time")])
        new = pd.concat([old, new], ignore_index=True)
    new = new.drop_duplicates(keys, keep="last").sort_values(keys).reset_index(drop=True)
    new.to_csv(path, index=False, float_format="%.3f")
    return new


def groups(items, n):
    for i in range(0, len(items), n):
        yield items[i : i + n]


def run_live(past_days: int) -> None:
    ensure_dirs()
    now = now_ist()
    frames = [fetch_hourly(g, past_days=past_days, forecast_days=1) for g in groups(CITIES, GROUP_SIZE)]
    new = pd.concat(frames, ignore_index=True)
    new = new[new["time"] <= now]  # observed/analysed hours only, never the forecast tail
    hourly = upsert(new, HOURLY_CSV, ["city", "time"])
    hourly = hourly[hourly["time"] >= now - pd.Timedelta(days=HOURLY_KEEP_DAYS)]
    hourly.to_csv(HOURLY_CSV, index=False)
    daily = aggregate_daily(hourly, before=now)
    total = upsert(daily, DAILY_CSV, ["city", "date"])
    print(f"hourly rows kept: {len(hourly)}; daily rows total: {len(total)}; latest day: {total['date'].max().date()}")


def run_backfill(start: str, end: str, chunk_days: int, pause: float) -> None:
    ensure_dirs()
    now = now_ist()
    end_ts = min(pd.Timestamp(end), now.normalize() - pd.Timedelta(days=1))
    starts = pd.date_range(pd.Timestamp(start), end_ts, freq=f"{chunk_days}D")
    daily_parts, failures = [], 0
    for s in starts:
        e = min(s + pd.Timedelta(days=chunk_days - 1), end_ts)
        fetch_from = max(s - pd.Timedelta(days=1), pd.Timestamp(start))  # 1-day overlap for the 8h windows
        for g in groups(CITIES, GROUP_SIZE):
            try:
                h = fetch_hourly(g, start=fetch_from.strftime("%Y-%m-%d"), end=e.strftime("%Y-%m-%d"))
            except OpenMeteoError as err:
                failures += 1
                print(f"  chunk {s.date()}..{e.date()} ({g[0].name}+{len(g) - 1}) failed: {err}", file=sys.stderr)
                continue
            daily_parts.append(aggregate_daily(h, before=now))
            time.sleep(pause)
        print(f"fetched {s.date()}..{e.date()}")
    if daily_parts:
        total = upsert(pd.concat(daily_parts, ignore_index=True), DAILY_CSV, ["city", "date"])
        print(f"daily rows total: {len(total)} ({total['date'].min().date()} .. {total['date'].max().date()})")
    if failures:
        print(f"{failures} request(s) failed; re-run to retry (existing rows are kept)", file=sys.stderr)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    live = sub.add_parser("live")
    live.add_argument("--past-days", type=int, default=3)
    bf = sub.add_parser("backfill")
    bf.add_argument("--start", default="2022-08-01")
    bf.add_argument("--end", default=str(now_ist().date()))
    bf.add_argument("--chunk-days", type=int, default=60)
    bf.add_argument("--pause", type=float, default=1.0)
    a = ap.parse_args(argv)
    if a.mode == "live":
        run_live(a.past_days)
    else:
        run_backfill(a.start, a.end, a.chunk_days, a.pause)


if __name__ == "__main__":
    main()
