"""Merge CPCB, Kaggle and stored Open-Meteo data into one daily table.

    python -m pipeline.build_dataset

Rules
  * src="hist": official daily AQI. CPCB file wins over the Kaggle 5-city files on overlapping dates;
    Kaggle extends Delhi/Mumbai/Bengaluru/Hyderabad/Chennai back to 2018.
  * src="om": Open-Meteo daily table (real pollutant concentrations + NAQI computed from them).
  * The Kaggle pollutant columns are NOT used: they are fixed multiples of AQI (e.g. PM2.5 = 0.55 x AQI on
    every row), so they carry no independent information.
"""
import pandas as pd

from . import common as C
from .cities import CITIES

KAGGLE_TO_CITY = {c.kaggle: c.name for c in CITIES if c.kaggle}
CPCB_RENAME = {c.cpcb_area: c.name for c in CITIES if c.cpcb_area and c.cpcb_area != c.name}
COLUMNS = ["city", "date", "src", "aqi", "dominant", *C.POLLUTANTS]


def load_cpcb() -> pd.DataFrame:
    d = pd.read_csv(C.RAW / "cpcb_aqi.csv.gz", usecols=["date", "area", "aqi_value", "prominent_pollutants"])
    d["date"] = pd.to_datetime(d["date"], format="%d-%m-%Y")
    d["city"] = d["area"].replace(CPCB_RENAME)
    first = d["prominent_pollutants"].str.split(",").str[0].str.strip()
    d["dominant"] = first.map(C.LABEL_TO_KEY)
    d = d[d["aqi_value"].between(0, 500)]
    # the file has repeated (area, date) rows; average the AQI, keep the first dominant pollutant
    g = d.groupby(["city", "date"], as_index=False).agg(aqi=("aqi_value", "mean"), dominant=("dominant", "first"))
    g["aqi"] = g["aqi"].round()
    g["prio"] = 0
    return g


def load_kaggle() -> pd.DataFrame:
    parts = []
    for f in sorted((C.RAW / "kaggle").glob("*_AQI_Dataset.csv")):
        d = pd.read_csv(f, encoding="utf-8-sig").iloc[:, :9]
        name = KAGGLE_TO_CITY.get(d["City"].iloc[0], d["City"].iloc[0])
        parts.append(
            pd.DataFrame(
                {
                    "city": name,
                    "date": pd.to_datetime(d["Date"], format="%d/%m/%y"),
                    "aqi": pd.to_numeric(d["AQI"], errors="coerce"),
                    "dominant": None,
                    "prio": 1,
                }
            )
        )
    k = pd.concat(parts, ignore_index=True)
    return k[k["aqi"].between(0, 500)]


def build() -> pd.DataFrame:
    C.ensure_dirs()
    hist = pd.concat([load_cpcb(), load_kaggle()], ignore_index=True)
    hist = hist.sort_values(["city", "date", "prio"]).drop_duplicates(["city", "date"], keep="first")
    hist["src"] = "hist"
    parts = [hist.drop(columns="prio")]
    if C.DAILY_CSV.exists():
        om = pd.read_csv(C.DAILY_CSV, parse_dates=["date"])
        om["src"] = "om"
        parts.append(om)
    df = pd.concat(parts, ignore_index=True)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[COLUMNS].sort_values(["city", "src", "date"]).reset_index(drop=True)
    df.to_csv(C.DATASET_CSV, index=False, float_format="%.3f")
    return df


if __name__ == "__main__":
    out = build()
    print(out.groupby("src").agg(rows=("aqi", "size"), cities=("city", "nunique"), start=("date", "min"), end=("date", "max")))
