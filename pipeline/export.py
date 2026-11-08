"""Write the static JSON the website reads (public/data/cities.json and public/data/history/<slug>.json).

    python -m pipeline.export

History per city is one compact daily AQI array from the first available date. Official history
(CPCB/Kaggle) is preferred; Open-Meteo-derived days fill in after it ends. `om_from` marks where that starts.
"""
import json

import pandas as pd

from . import common as C
from .cities import CITIES


def main() -> None:
    C.ensure_dirs()
    df = pd.read_csv(C.DATASET_CSV, parse_dates=["date"])
    info = []
    for c in CITIES:
        g = df[df["city"] == c.name]
        if g.empty:
            continue
        hist = g[g["src"] == "hist"].set_index("date")
        om = g[g["src"] == "om"].set_index("date")
        merged = hist[["aqi", "dominant"]].copy()
        om_from = None
        if len(om):
            extra = om.loc[~om.index.isin(merged.index), ["aqi", "dominant"]]
            if len(hist):
                extra = extra[extra.index > hist.index.max()]
            if len(extra):
                om_from = str(extra.index.min().date())
            merged = pd.concat([merged, extra]).sort_index()
        idx = pd.date_range(merged.index.min(), merged.index.max(), freq="D")
        merged = merged.reindex(idx)
        aqi = [None if pd.isna(v) else int(v) for v in merged["aqi"]]
        # dominant pollutant as a short code per day ("" when unknown) to keep the file small
        dom = ["" if not isinstance(v, str) else v for v in merged["dominant"]]
        payload = {"city": c.name, "start": str(idx[0].date()), "aqi": aqi, "dominant": dom, "om_from": om_from}
        (C.PUBLIC_DATA / "history" / f"{c.slug}.json").write_text(json.dumps(payload, separators=(",", ":")))
        info.append({"name": c.name, "slug": c.slug, "state": c.state, "lat": c.lat, "lon": c.lon,
                     "history_start": payload["start"], "history_end": str(idx[-1].date())})
    (C.PUBLIC_DATA / "cities.json").write_text(json.dumps(info, separators=(",", ":")))
    print(f"exported {len(info)} cities")


if __name__ == "__main__":
    main()
