"""Run: python -m pytest tests -q     (set RUN_E2E=1 to include the slow end-to-end run)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline import naqi  # noqa: E402
from pipeline.ingest import aggregate_daily  # noqa: E402


def test_naqi_breakpoints():
    df = pd.DataFrame({"pm2_5": [0, 30, 60, 90, 120, 250, 500], "pm10": np.nan})
    aqi, dom = naqi.aqi_and_dominant(df)
    assert aqi.tolist() == [0, 50, 100, 200, 300, 400, 500]
    assert set(dom) == {"pm2_5"}


def test_naqi_picks_worst_pollutant_and_needs_particulates():
    df = pd.DataFrame({"pm2_5": [20, np.nan], "pm10": [40, np.nan], "o3": [170, 300], "co": [0.5, 3.0]})
    aqi, dom = naqi.aqi_and_dominant(df)
    assert dom.iloc[0] == "o3" and 200 < aqi.iloc[0] < 300  # 170 ug/m3 O3 is just inside "Poor"
    assert np.isnan(aqi.iloc[1])  # no PM -> no AQI, as CPCB requires


def test_band_labels():
    assert [naqi.band(x) for x in (10, 75, 150, 250, 350, 450)] == ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]


def test_aggregate_daily_only_complete_past_days():
    t = pd.date_range("2026-01-01 00:00", "2026-01-03 11:00", freq="h")
    h = pd.DataFrame({"city": "X", "time": t, "pm2_5": 60.0, "pm10": 100.0, "no2": 10.0, "so2": 5.0, "co": 0.5, "o3": 20.0})
    d = aggregate_daily(h, before=pd.Timestamp("2026-01-03 12:00"))
    assert list(d["date"].dt.strftime("%Y-%m-%d")) == ["2026-01-01", "2026-01-02"]  # Jan 3 is incomplete
    assert (d["aqi"] == 100).all() and (d["dominant"] == "pm2_5").all()


@pytest.mark.skipif(not os.environ.get("RUN_E2E"), reason="slow; set RUN_E2E=1")
def test_end_to_end_with_mock_openmeteo():
    sys.path.insert(0, str(REPO / "tests"))
    from mock_openmeteo import serve

    srv = serve(0)
    port = srv.server_address[1]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copytree(REPO / "data" / "raw", root / "data" / "raw")
        env = {**os.environ, "AQ_ROOT": str(root), "OPENMETEO_AQ_URL": f"http://127.0.0.1:{port}/v1/air-quality", "PYTHONPATH": str(REPO)}
        run = lambda *a: subprocess.run([sys.executable, "-m", *a], env=env, cwd=REPO, check=True, capture_output=True, text=True)
        start = (pd.Timestamp.now() - pd.Timedelta(days=130)).strftime("%Y-%m-%d")
        run("pipeline.ingest", "backfill", "--start", start, "--pause", "0")
        run("pipeline.ingest", "live", "--past-days", "2")
        daily = pd.read_csv(root / "data" / "live" / "daily.csv", parse_dates=["date"])
        from pipeline.cities import CITIES
        assert daily["city"].nunique() == len(CITIES) and daily["aqi"].between(0, 500).all()
        assert not daily.duplicated(["city", "date"]).any()
        run("pipeline.build_dataset")
        run("pipeline.train")
        run("pipeline.export")
        fc = json.loads((root / "public" / "data" / "forecast.json").read_text())
        delhi = fc["cities"]["Delhi"]
        assert delhi["series"] == "open-meteo" and delhi["stale_days"] <= 1
        assert len(delhi["forecast"]) == 7 and all(d["lo"] <= d["aqi"] <= d["hi"] for d in delhi["forecast"])
        assert set(delhi["pollutants"]) == {"pm2_5", "pm10", "no2", "so2", "co", "o3"}
        assert json.loads((root / "public" / "data" / "metrics.json").read_text())["aqi"]
    srv.shutdown()
