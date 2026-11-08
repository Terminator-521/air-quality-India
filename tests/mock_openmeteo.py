"""Local stand-in for the Open-Meteo Air Quality API (same request/response shape).

Used only by tests: the real API is not reachable from the build sandbox. Values are synthetic
(seasonal + weekly + noise) and exist purely to exercise ingest -> dataset -> train -> export.
"""
import json
import math
import random
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

VARS = ["pm2_5", "pm10", "nitrogen_dioxide", "sulphur_dioxide", "carbon_monoxide", "ozone"]
SCALE = {"pm2_5": 1.0, "pm10": 1.9, "nitrogen_dioxide": 0.45, "sulphur_dioxide": 0.15, "carbon_monoxide": 9.0, "ozone": 0.9}


def hourly_series(lat, lon, t):
    doy = t.timetuple().tm_yday
    season = 1.0 + 0.8 * math.cos(2 * math.pi * (doy - 340) / 365)  # winter peak
    rng = random.Random(f"{lat:.2f}{lon:.2f}{t.date()}")
    day_level = 45 * season * (0.7 + 0.6 * rng.random()) * (1 + (lat - 20) / 40)
    diurnal = 1 + 0.25 * math.cos(2 * math.pi * (t.hour - 8) / 24)
    return day_level * diurnal


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        lats = [float(x) for x in q["latitude"][0].split(",")]
        lons = [float(x) for x in q["longitude"][0].split(",")]
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        if "start_date" in q:
            start = datetime.fromisoformat(q["start_date"][0])
            end = datetime.fromisoformat(q["end_date"][0]) + timedelta(hours=23)
        else:
            start = (now - timedelta(days=int(q.get("past_days", ["0"])[0]))).replace(hour=0)
            end = now.replace(hour=0) + timedelta(days=int(q.get("forecast_days", ["1"])[0])) - timedelta(hours=1)
        times = []
        t = start
        while t <= end:
            times.append(t)
            t += timedelta(hours=1)
        out = []
        for lat, lon in zip(lats, lons):
            h = {"time": [x.strftime("%Y-%m-%dT%H:%M") for x in times]}
            for v in VARS:
                h[v] = [round(hourly_series(lat, lon, x) * SCALE[v], 1) for x in times]
            out.append({"latitude": lat, "longitude": lon, "hourly": h})
        body = json.dumps(out if len(out) > 1 else out[0]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def serve(port=0):
    srv = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    s = serve(8765)
    print("mock Open-Meteo on http://127.0.0.1:8765/v1/air-quality")
    threading.Event().wait()
