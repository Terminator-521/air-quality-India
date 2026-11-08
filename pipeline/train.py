"""Train the forecasting models and write public/data/forecast.json + metrics.json.

    python -m pipeline.train

Models (scikit-learn HistGradientBoosting, one model per forecast horizon, "direct" multi-step):
  * AQI, 1..7 days ahead: mean + 10th/90th percentile models (the percentiles give the uncertainty band)
  * Dominant pollutant tomorrow: classifier
  * Pollutant concentrations, 1..7 days ahead: trained only when stored Open-Meteo history exists
All models predict the change from the 3-day mean, using lags, rolling statistics, season,
a crop-burning flag (15 Oct - 30 Nov) and a per-city level. Evaluation is a strict time split:
the last 90 days are held out and models are compared with persistence baselines.
"""
import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from . import common as C
from . import naqi
from .cities import CITIES

HORIZONS = list(range(1, 8))
LAGS = (0, 1, 2, 3, 4, 5, 6, 13, 20)
HOLDOUT_DAYS = 90
MODEL_VERSION = "hgb-direct-v1"
DOM_KEYS = ["pm2_5", "pm10", "o3", "co", "no2", "so2"]  # class order for the classifier
MIN_POLLUTANT_ROWS = 3000


# ---------------------------------------------------------------- features
def make_frame(df: pd.DataFrame, col: str, horizons, aux=()) -> pd.DataFrame:
    parts = []
    for (city, src), g in df.groupby(["city", "src"]):
        g = g.set_index("date").sort_index()
        idx = pd.date_range(g.index.min(), g.index.max(), freq="D")
        g = g.reindex(idx)
        s = g[col].astype(float)
        if s.notna().sum() < 40:
            continue
        f = pd.DataFrame(index=idx)
        for L in LAGS:
            f[f"lag{L}"] = s.shift(L)
        for w in (3, 7, 14, 30):
            f[f"m{w}"] = s.rolling(w, min_periods=max(2, w // 2)).mean()
        f["sd7"] = s.rolling(7, min_periods=4).std()
        f["d1"] = s - s.shift(1)
        for a in aux:
            for L in (0, 1, 2):
                f[f"{a}_lag{L}"] = g[a].astype(float).shift(L)
        doy = idx.dayofyear.values
        f["sin"] = np.sin(2 * np.pi * doy / 365.25)
        f["cos"] = np.cos(2 * np.pi * doy / 365.25)
        f["month"] = idx.month
        f["stubble"] = (((idx.month == 10) & (idx.day >= 15)) | (idx.month == 11)).astype(int)
        f["residue"] = idx.month.isin([4, 5]).astype(int)
        f["src_om"] = int(src == "om")
        f["base"] = f["m3"].fillna(f["lag0"])
        for h in horizons:
            f[f"y{h}"] = s.shift(-h)
        if "domcode" in g.columns:
            f["dom_y1"] = g["domcode"].astype(float).shift(-1)
        f["city"] = city
        f["src"] = src
        f["origin"] = idx
        f["last_obs"] = s.index[s.notna()].max()
        parts.append(f.reset_index(drop=True))
    return pd.concat(parts, ignore_index=True)


def add_city_level(F: pd.DataFrame, cutoff: pd.Timestamp) -> dict:
    train = F[F["origin"] < cutoff]
    means = train.groupby("city")["lag0"].mean()
    glob = float(train["lag0"].mean())
    F["cmean"] = F["city"].map(means).fillna(glob)
    return {"means": means.to_dict(), "global": glob}


def feature_cols(F: pd.DataFrame):
    return [c for c in F.columns if c not in ("city", "src", "origin", "last_obs", "dom_y1") and not c.startswith("y")]


# ---------------------------------------------------------------- models
def reg(loss="squared_error", q=None, iters=200):
    kw = dict(max_iter=iters, learning_rate=0.08, max_leaf_nodes=24, min_samples_leaf=60,
              l2_regularization=1.0, random_state=0)
    if loss == "quantile":
        return HistGradientBoostingRegressor(loss="quantile", quantile=q, **kw)
    return HistGradientBoostingRegressor(**kw)


def fit_horizons(F_train, feats, horizons, with_band):
    models = {}
    for h in horizons:
        d = F_train[F_train[f"y{h}"].notna() & F_train["base"].notna()]
        X, y = d[feats], d[f"y{h}"] - d["base"]
        m = {"mean": reg().fit(X, y)}
        if with_band:
            m["lo"] = reg("quantile", 0.1, 120).fit(X, y)
            m["hi"] = reg("quantile", 0.9, 120).fit(X, y)
        models[h] = m
    return models


def predict(models, h, X, base, lo_clip=0.0, hi_clip=500.0):
    m = models[h]
    mean = np.clip(base + m["mean"].predict(X), lo_clip, hi_clip)
    if "lo" in m:
        a, b = base + m["lo"].predict(X), base + m["hi"].predict(X)
        lo, hi = np.minimum.reduce([a, b, mean]), np.maximum.reduce([a, b, mean])
        return mean, np.clip(lo, lo_clip, hi_clip), np.clip(hi, lo_clip, hi_clip)
    return mean, None, None


def score(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    err = p - y
    ss_tot = np.sum((y - y.mean()) ** 2)
    return {
        "mae": round(float(np.abs(err).mean()), 2),
        "rmse": round(float(np.sqrt((err**2).mean())), 2),
        "r2": round(float(1 - np.sum(err**2) / ss_tot), 3) if ss_tot > 0 else None,
    }


def evaluate_aqi(F, feats, models, cutoff):
    test = F[F["origin"] >= cutoff]
    rows = []
    for h in HORIZONS:
        d = test[test[f"y{h}"].notna() & test["base"].notna()]
        if len(d) < 50:
            continue
        mean, lo, hi = predict(models, h, d[feats], d["base"].to_numpy())
        y = d[f"y{h}"].to_numpy()
        s = score(y, mean)
        s["horizon"] = h
        s["n"] = int(len(d))
        s["baseline_persistence_mae"] = score(y, d["lag0"].fillna(d["base"]))["mae"]
        s["baseline_mean7_mae"] = score(y, d["m7"].fillna(d["base"]))["mae"]
        s["skill_vs_persistence"] = round(1 - s["mae"] / s["baseline_persistence_mae"], 3)
        s["band_accuracy"] = round(float((naqi.band_index(mean) == naqi.band_index(y)).mean()), 3)
        s["interval_coverage_80"] = round(float(((y >= lo) & (y <= hi)).mean()), 3)
        rows.append(s)
    return rows


# ---------------------------------------------------------------- pipeline
def main() -> None:
    t0 = time.time()
    C.ensure_dirs()
    df = pd.read_csv(C.DATASET_CSV, parse_dates=["date"])
    df["domcode"] = df["dominant"].map({k: i for i, k in enumerate(DOM_KEYS)})
    today = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
    max_date = df["date"].max()
    cutoff = max_date - pd.Timedelta(days=HOLDOUT_DAYS)
    print(f"rows={len(df)} series={df.groupby(['city', 'src']).ngroups} data through {max_date.date()}; holdout from {cutoff.date()}")

    # ---- AQI
    F = make_frame(df, "aqi", HORIZONS, aux=("domcode",))
    level = add_city_level(F, cutoff)
    feats = feature_cols(F)
    train = F.copy()
    for h in HORIZONS:  # a training target must lie before the cutoff
        train.loc[train["origin"] + pd.Timedelta(days=h) >= cutoff, f"y{h}"] = np.nan
    train = train[train["origin"] < cutoff]
    print(f"AQI frame {F.shape}, evaluating...")
    eval_models = fit_horizons(train, feats, HORIZONS, with_band=True)
    aqi_metrics = evaluate_aqi(F, feats, eval_models, cutoff)
    for r in aqi_metrics:
        print(f"  h{r['horizon']}: MAE {r['mae']} vs persistence {r['baseline_persistence_mae']}  skill {r['skill_vs_persistence']}  cov80 {r['interval_coverage_80']}")

    # ---- dominant pollutant (tomorrow)
    dom_train = train[train["dom_y1"].notna()]
    dom_test = F[(F["origin"] >= cutoff) & F["dom_y1"].notna()]
    dom_metrics = None
    clf = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, max_leaf_nodes=24, min_samples_leaf=60, random_state=0)
    if len(dom_train) > 500:
        clf.fit(dom_train[feats], dom_train["dom_y1"].astype(int))
        if len(dom_test) > 50:
            pred = clf.predict(dom_test[feats])
            yt = dom_test["dom_y1"].astype(int).to_numpy()
            persist = dom_test["domcode_lag0"].fillna(-1).astype(int).to_numpy()
            dom_metrics = {"accuracy": round(float((pred == yt).mean()), 3),
                           "baseline_same_as_today": round(float((persist == yt).mean()), 3), "n": int(len(yt))}
            print("  dominant pollutant:", dom_metrics)

    # ---- pollutant concentrations (only from real Open-Meteo history)
    om = df[df["src"] == "om"]
    poll_metrics, poll_frames = {}, {}
    if len(om) and om["pm2_5"].notna().sum() >= MIN_POLLUTANT_ROWS:
        for p in C.POLLUTANTS:
            Fp = make_frame(om, p, HORIZONS, aux=("aqi",))
            add_city_level(Fp, cutoff)
            fp = feature_cols(Fp)
            tp = Fp.copy()
            for h in HORIZONS:
                tp.loc[tp["origin"] + pd.Timedelta(days=h) >= cutoff, f"y{h}"] = np.nan
            tp = tp[tp["origin"] < cutoff]
            if len(tp) < 1000:
                continue
            models = fit_horizons(tp, fp, [1, 3, 5, 7], with_band=False)
            test = Fp[Fp["origin"] >= cutoff]
            rows = []
            for h in (1, 3, 5, 7):
                d = test[test[f"y{h}"].notna() & test["base"].notna()]
                if len(d) < 50:
                    continue
                mean, _, _ = predict(models, h, d[fp], d["base"].to_numpy(), hi_clip=1e6)
                s = score(d[f"y{h}"], mean)
                s.update(horizon=h, n=int(len(d)), baseline_persistence_mae=score(d[f"y{h}"], d["lag0"].fillna(d["base"]))["mae"])
                rows.append(s)
            poll_metrics[p] = rows
            poll_frames[p] = (Fp, fp)
            print(f"  pollutant {p}: {rows[:1]}")
    else:
        print("  pollutant models skipped: not enough stored Open-Meteo history yet")

    # ---- final fit on everything we have, then forecast
    print("refitting on all data...")
    final = fit_horizons(F[F["base"].notna()], feats, HORIZONS, with_band=True)
    dom_all = F[F["dom_y1"].notna()]
    if len(dom_all) > 500:
        clf.fit(dom_all[feats], dom_all["dom_y1"].astype(int))
    poll_final = {}
    for p, (Fp, fp) in poll_frames.items():
        poll_final[p] = (fit_horizons(Fp[Fp["base"].notna()], fp, HORIZONS, with_band=False), Fp, fp)

    last = F.sort_values("origin").groupby(["city", "src"]).tail(1)
    forecast = {}
    for c in CITIES:
        cand = last[(last["city"] == c.name) & last["lag0"].notna()]
        if cand.empty:
            continue
        om_rows = cand[(cand["src"] == "om")]
        if len(om_rows) and df[(df["city"] == c.name) & (df["src"] == "om")].shape[0] >= 30:
            # prefer the live series whenever it is at least as fresh as the historical one
            pick = cand.sort_values(["origin", "src_om"], ascending=[False, False]).iloc[[0]]
        else:
            pick = cand[cand["src"] == "hist"].sort_values("origin", ascending=False).iloc[[0]] if (cand["src"] == "hist").any() else cand.iloc[[0]]
        as_of = pd.Timestamp(pick["origin"].iloc[0])
        X, base = pick[feats], pick["base"].to_numpy()
        days = []
        for h in HORIZONS:
            mean, lo, hi = predict(final, h, X, base)
            days.append({"date": str((as_of + pd.Timedelta(days=h)).date()), "h": h, "aqi": int(round(mean[0])),
                         "lo": int(round(lo[0])), "hi": int(round(hi[0])), "band": naqi.band(mean[0])})
        cur = df[(df["city"] == c.name) & (df["date"] == as_of) & (df["src"] == pick["src"].iloc[0])].iloc[0]
        entry = {
            "as_of": str(as_of.date()),
            "stale_days": int((today - as_of).days),
            "series": "open-meteo" if pick["src"].iloc[0] == "om" else "cpcb-history",
            "current": {"aqi": int(cur["aqi"]), "band": naqi.band(cur["aqi"]),
                        "dominant": cur["dominant"] if isinstance(cur["dominant"], str) else None},
            "forecast": days,
        }
        if len(dom_all) > 500:
            proba = clf.predict_proba(X)[0]
            entry["next_dominant"] = {DOM_KEYS[int(k)]: round(float(v), 3) for k, v in zip(clf.classes_, proba) if v >= 0.01}
        if pick["src"].iloc[0] == "om" and poll_final:
            pols = {}
            for p, (models, Fp, fp) in poll_final.items():
                row = Fp[(Fp["city"] == c.name) & (Fp["origin"] == as_of)]
                if row.empty or row["base"].isna().any():
                    continue
                vals = [predict(models, h, row[fp], row["base"].to_numpy(), hi_clip=1e6)[0][0] for h in HORIZONS]
                pols[p] = [round(float(v), 2) for v in vals]
                entry["current"][p] = round(float(cur[p]), 2) if pd.notna(cur[p]) else None
            if pols:
                entry["pollutants"] = pols
        forecast[c.name] = entry

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = {"generated_at": now, "model": MODEL_VERSION, "horizons": HORIZONS, "cities": forecast}
    (C.PUBLIC_DATA / "forecast.json").write_text(json.dumps(out, separators=(",", ":")))

    counts = df.groupby("src").agg(rows=("aqi", "size"), cities=("city", "nunique"),
                                   start=("date", "min"), end=("date", "max")).reset_index()
    metrics = {
        "generated_at": now,
        "model": MODEL_VERSION,
        "holdout": {"start": str(cutoff.date()), "end": str(max_date.date()), "days": HOLDOUT_DAYS},
        "aqi": aqi_metrics,
        "dominant_pollutant": dom_metrics,
        "pollutants": poll_metrics,
        "data": [{"src": r.src, "rows": int(r.rows), "cities": int(r.cities), "start": str(r.start.date()), "end": str(r.end.date())}
                 for r in counts.itertuples()],
        "training_rows_aqi": int(len(train)),
        "features": feats,
    }
    (C.PUBLIC_DATA / "metrics.json").write_text(json.dumps(metrics, indent=1))
    print(f"done in {time.time() - t0:.0f}s; {len(forecast)} city forecasts")


if __name__ == "__main__":
    main()
