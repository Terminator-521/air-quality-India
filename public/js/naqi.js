// India National AQI (CPCB). Mirrors pipeline/naqi.py so live browser values and stored values agree.
// Units: PM2.5, PM10, NO2, SO2, O3 in µg/m³; CO in mg/m³.

export const BANDS = [
  { max: 50, name: 'Good', cls: 'b-good', advice: 'The air is clean. A good day to be outside.' },
  { max: 100, name: 'Satisfactory', cls: 'b-sat', advice: 'Fine for most people. Unusually sensitive people may notice mild discomfort.' },
  { max: 200, name: 'Moderate', cls: 'b-mod', advice: 'Children, older adults and people with lung or heart conditions should cut back on long outdoor exertion.' },
  { max: 300, name: 'Poor', cls: 'b-poor', advice: 'Many people will feel discomfort with longer exposure. Keep outdoor exercise short; sensitive groups should stay in.' },
  { max: 400, name: 'Very Poor', cls: 'b-vpoor', advice: 'Breathing problems are likely with longer exposure. Skip outdoor exercise and wear an N95 mask outside.' },
  { max: 500, name: 'Severe', cls: 'b-severe', advice: 'This affects everyone and can seriously harm people with existing conditions. Stay indoors with windows closed.' },
];

export const band = (aqi) => BANDS[bandIndex(aqi)];
export function bandIndex(aqi) {
  for (let i = 0; i < BANDS.length; i++) if (aqi <= BANDS[i].max) return i;
  return BANDS.length - 1;
}

const IDX = [0, 50, 100, 200, 300, 400, 500];
const KNOTS = {
  pm2_5: [0, 30, 60, 90, 120, 250, 380],
  pm10: [0, 50, 100, 250, 350, 430, 550],
  no2: [0, 40, 80, 180, 280, 400, 520],
  o3: [0, 50, 100, 168, 208, 748, 1000],
  co: [0, 1, 2, 10, 17, 34, 50],
  so2: [0, 40, 80, 380, 800, 1600, 2000],
};

export const POLLUTANTS = [
  { key: 'pm2_5', label: 'PM2.5', om: 'pm2_5', unit: 'µg/m³', hint: 'Fine particles from traffic, burning and industry' },
  { key: 'pm10', label: 'PM10', om: 'pm10', unit: 'µg/m³', hint: 'Dust and coarse particles' },
  { key: 'no2', label: 'NO₂', om: 'nitrogen_dioxide', unit: 'µg/m³', hint: 'Mostly from vehicles and power plants' },
  { key: 'so2', label: 'SO₂', om: 'sulphur_dioxide', unit: 'µg/m³', hint: 'Coal burning and industry' },
  { key: 'co', label: 'CO', om: 'carbon_monoxide', unit: 'mg/m³', hint: 'Incomplete burning, mainly vehicles' },
  { key: 'o3', label: 'O₃', om: 'ozone', unit: 'µg/m³', hint: 'Forms from sunlight reacting with other pollutants' },
];
export const LABEL = Object.fromEntries(POLLUTANTS.map((p) => [p.key, p.label]));

function interp(x, xs, ys) {
  if (x == null || Number.isNaN(x)) return NaN;
  if (x <= xs[0]) return ys[0];
  for (let i = 1; i < xs.length; i++) {
    if (x <= xs[i]) return ys[i - 1] + ((ys[i] - ys[i - 1]) * (x - xs[i - 1])) / (xs[i] - xs[i - 1]);
  }
  return ys[ys.length - 1];
}

export const subIndex = (key, conc) => interp(conc, KNOTS[key], IDX);

/** conc: {pm2_5, pm10, no2, so2, co, o3} -> {aqi, dominant} (AQI needs a particulate reading) */
export function aqiFromConc(conc) {
  let best = -1, dom = null;
  for (const p of POLLUTANTS) {
    const s = subIndex(p.key, conc[p.key]);
    if (!Number.isNaN(s) && s > best) { best = s; dom = p.key; }
  }
  const hasPM = !Number.isNaN(subIndex('pm2_5', conc.pm2_5)) || !Number.isNaN(subIndex('pm10', conc.pm10));
  return hasPM && best >= 0 ? { aqi: Math.round(best), dominant: dom } : { aqi: NaN, dominant: null };
}

/** Open-Meteo hourly block -> one record per local day, aggregated as the pipeline does:
 *  24h mean for PM2.5/PM10/NO2/SO2, daily max of the 8-hour rolling mean for CO and O3. */
export function dailyFromHourly(h) {
  const n = h.time.length;
  const val = (key, i) => {
    const v = h[POLLUTANTS.find((p) => p.key === key).om][i];
    return v == null ? NaN : key === 'co' ? v / 1000 : v;
  };
  const roll8 = (key) => {
    const out = new Array(n).fill(NaN);
    for (let i = 0; i < n; i++) {
      let s = 0, c = 0;
      for (let k = Math.max(0, i - 7); k <= i; k++) { const v = val(key, k); if (!Number.isNaN(v)) { s += v; c++; } }
      if (c >= 6) out[i] = s / c;
    }
    return out;
  };
  const r8 = { co: roll8('co'), o3: roll8('o3') };
  const days = new Map();
  for (let i = 0; i < n; i++) {
    const d = h.time[i].slice(0, 10);
    if (!days.has(d)) days.set(d, { date: d, hours: 0, sums: {}, counts: {}, max: {} });
    const r = days.get(d);
    r.hours++;
    for (const p of POLLUTANTS) {
      if (p.key === 'co' || p.key === 'o3') {
        const v = r8[p.key][i];
        if (!Number.isNaN(v)) r.max[p.key] = Math.max(r.max[p.key] ?? -Infinity, v);
      } else {
        const v = val(p.key, i);
        if (!Number.isNaN(v)) { r.sums[p.key] = (r.sums[p.key] || 0) + v; r.counts[p.key] = (r.counts[p.key] || 0) + 1; }
      }
    }
  }
  return [...days.values()].filter((r) => r.hours >= 20).map((r) => {
    const conc = {};
    for (const p of POLLUTANTS) {
      conc[p.key] = p.key === 'co' || p.key === 'o3' ? r.max[p.key] : r.counts[p.key] ? r.sums[p.key] / r.counts[p.key] : undefined;
    }
    return { date: r.date, ...conc, ...aqiFromConc(conc) };
  });
}
