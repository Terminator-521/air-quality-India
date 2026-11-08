# Hawa – India air quality: live data, 7-day forecast, website

Static website (HTML/CSS/JS, no build step) + a Python pipeline that collects live data, trains models and writes the JSON the site reads.

```
public/            the website (deploy this folder)      pipeline/   ingest · build_dataset · train · export
  data/*.json      forecasts, metrics, city history      data/raw/   CPCB csv (gz) + Kaggle 5-city csv
data/live/         hourly.csv + daily.csv (auto-stored)  .github/    scheduled jobs
```

## Data
| Source | Used for |
|---|---|
| CPCB daily AQI, 291 areas, Apr 2022 – Apr 2025 | training + history |
| Kaggle 5-city AQI, 2018–2024 | extends Delhi, Mumbai, Bengaluru, Hyderabad, Chennai back to 2018 (CPCB wins on overlap) |
| Open-Meteo Air Quality API (live, free, no key) | real pollutant concentrations; stored automatically; also queried from the browser for "live now" |

The Kaggle pollutant columns are ignored: every value is a fixed multiple of AQI (PM2.5 = 0.55×AQI on all rows).
AQI from Open-Meteo pollutants is computed with the CPCB NAQI breakpoints (`pipeline/naqi.py`, mirrored in `public/js/naqi.js`).

## Run locally
```bash
pip install -r requirements.txt
python -m pipeline.ingest backfill --start 2022-08-01   # once; needs internet access to open-meteo.com
python -m pipeline.ingest live                          # repeat any time
python -m pipeline.build_dataset && python -m pipeline.train && python -m pipeline.export
python -m http.server 3000 --directory public           # open http://localhost:3000
python -m pytest tests -q                               # RUN_E2E=1 adds the slow end-to-end test
```

## Deploy (Vercel) with automatic data storage
1. Push this folder to a GitHub repo.
2. vercel.com → Add New → Project → import the repo. Framework: Other. Output directory is read from `vercel.json` (`public`). No build command.
3. GitHub → Actions → **collect-live-data** → Run workflow with `backfill_from = 2022-08-01` (one time). Then run **retrain-and-publish** once.
4. From then on: readings are saved every 3 h to `data/live/` and models retrain nightly; each commit redeploys the site.
   If Vercel does not redeploy on bot commits, create a Deploy Hook in Vercel and save it as the repo secret `VERCEL_DEPLOY_HOOK`.

Netlify / Cloudflare Pages / GitHub Pages also work: publish the `public` folder.

## Model
Per-horizon (1–7 days) HistGradientBoosting models on lags, rolling means, season and a crop-burning flag (15 Oct–30 Nov); 10th/90th-percentile models give the likely range; a classifier predicts tomorrow's main pollutant; pollutant-concentration models train once enough Open-Meteo history is stored. Held-out last 90 days vs "same as today": see the site's Data and model section (`public/data/metrics.json`).
Ideas to improve: add weather forecasts (wind, boundary-layer height, rain) from Open-Meteo as features; fire counts for stubble burning.
