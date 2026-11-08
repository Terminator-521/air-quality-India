"""India National AQI (CPCB) from pollutant concentrations.

Units: PM2.5, PM10, NO2, SO2, O3 in ug/m3; CO in mg/m3.
Sub-index = piecewise-linear interpolation over the CPCB breakpoints; AQI = max sub-index,
reported only when at least one particulate (PM2.5 or PM10) is present, as CPCB requires.
"""
import numpy as np
import pandas as pd

IDX_KNOTS = [0, 50, 100, 200, 300, 400, 500]

# concentration knots matching IDX_KNOTS (upper end of "Severe" capped at a plausible maximum)
CONC_KNOTS = {
    "pm2_5": [0, 30, 60, 90, 120, 250, 380],
    "pm10": [0, 50, 100, 250, 350, 430, 550],
    "no2": [0, 40, 80, 180, 280, 400, 520],
    "o3": [0, 50, 100, 168, 208, 748, 1000],
    "co": [0, 1, 2, 10, 17, 34, 50],
    "so2": [0, 40, 80, 380, 800, 1600, 2000],
}

BANDS = [
    (50, "Good"),
    (100, "Satisfactory"),
    (200, "Moderate"),
    (300, "Poor"),
    (400, "Very Poor"),
    (500, "Severe"),
]


def band(aqi: float) -> str:
    if aqi is None or np.isnan(aqi):
        return "Unknown"
    for upper, name in BANDS:
        if aqi <= upper:
            return name
    return "Severe"


def band_index(aqi) -> np.ndarray:
    """0..5 band index, vectorised (used for category accuracy)."""
    a = np.asarray(aqi, dtype=float)
    return np.clip(np.searchsorted([50, 100, 200, 300, 400], a, side="left"), 0, 5)


def sub_indices(df: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for p, knots in CONC_KNOTS.items():
        if p in df.columns:
            x = df[p].to_numpy(dtype=float)
            y = np.interp(x, knots, IDX_KNOTS)  # clamps at both ends
            y[np.isnan(x)] = np.nan
            out[p] = y
    return pd.DataFrame(out, index=df.index)


def aqi_and_dominant(df: pd.DataFrame):
    """Return (aqi Series, dominant pollutant-key Series) for a frame of concentrations."""
    sub = sub_indices(df)
    if sub.empty:
        return pd.Series(np.nan, index=df.index), pd.Series(None, index=df.index, dtype=object)
    filled = sub.fillna(-1)
    dominant = filled.idxmax(axis=1).where(filled.max(axis=1) >= 0)
    aqi = sub.max(axis=1, skipna=True)
    has_pm = sub[[c for c in ("pm2_5", "pm10") if c in sub.columns]].notna().any(axis=1)
    aqi = aqi.where(has_pm).round()
    dominant = dominant.where(has_pm)
    return aqi, dominant
