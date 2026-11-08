import { BANDS, band, bandIndex, POLLUTANTS, LABEL, subIndex, dailyFromHourly } from './naqi.js';

/* ───────── helpers ───────── */
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtDay = new Intl.DateTimeFormat('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
const fmtLong = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'long', year: 'numeric' });
const fmtShort = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short' });
const day = (s) => new Date(s + 'T00:00:00');
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const daysBetween = (a, b) => Math.round((b - a) / 864e5);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const getJSON = async (u) => { const r = await fetch(u, { cache: 'no-cache' }); if (!r.ok) throw new Error(`${u}: ${r.status}`); return r.json(); };
const bandVar = ['--good', '--sat', '--mod', '--poor', '--vpoor', '--severe'];
const bandColor = (aqi) => css(bandVar[bandIndex(aqi)]);

const S = { cities: [], forecast: null, metrics: null, city: null, entry: null, hist: null, live: null, liveErr: null, token: 0, sort: 'worst', year: null };
const charts = {};

/* ───────── theme ───────── */
function initTheme() {
  try { const t = localStorage.getItem('hawa-theme'); if (t) document.documentElement.dataset.theme = t; } catch {}
  $('#theme').addEventListener('click', () => {
    const dark = css('color-scheme') === 'dark';
    const next = dark ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('hawa-theme', next); } catch {}
    restyleAll();
  });
}
function restyleAll() {
  Chart.defaults.color = css('--muted');
  Chart.defaults.borderColor = css('--line');
  if (S.city) { renderOutlook(); renderForecastChart(); }
  if (map) setTiles();
  markers.forEach((m, name) => m.setIcon(pinIcon(name)));
}

/* ───────── live data from Open-Meteo (browser → API, CORS enabled) ───────── */
const istHourKey = () => new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Kolkata' }).slice(0, 13).replace(' ', 'T') + ':00';

async function fetchLive(c) {
  const p = new URLSearchParams({
    latitude: c.lat.toFixed(4), longitude: c.lon.toFixed(4), hourly: POLLUTANTS.map((x) => x.om).join(','),
    timezone: 'Asia/Kolkata', past_days: '3', forecast_days: '5',
  });
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 10000);
  try {
    const r = await fetch(`https://air-quality-api.open-meteo.com/v1/air-quality?${p}`, { signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const h = (await r.json()).hourly;
    const key = istHourKey();
    let i = h.time.indexOf(key);
    if (i < 0) i = Math.max(0, h.time.findIndex((t) => t > key) - 1);
    const now = {};
    for (const x of POLLUTANTS) { const v = h[x.om][i]; now[x.key] = v == null ? null : x.key === 'co' ? v / 1000 : v; }
    return { time: h.time[i], now, daily: dailyFromHourly(h), today: key.slice(0, 10) };
  } finally { clearTimeout(timer); }
}

/* ───────── hero (the skyline) ───────── */
const freshEntry = () => S.entry && S.entry.stale_days <= 3;

function heroItems() {
  const e = S.entry, lv = S.live;
  const useStored = e && (freshEntry() || !lv);
  if (useStored) {
    return {
      kind: 'stored',
      items: [{ label: fmtDay.format(day(e.as_of)), aqi: e.current.aqi, kind: 'latest' },
        ...e.forecast.map((f) => ({ label: fmtDay.format(day(f.date)), aqi: f.aqi, lo: f.lo, hi: f.hi, kind: 'fc' }))],
    };
  }
  if (lv) {
    const upcoming = lv.daily.filter((d) => d.date >= lv.today && !Number.isNaN(d.aqi)).slice(0, 6);
    if (upcoming.length) {
      return { kind: 'live', items: upcoming.map((d, i) => ({ label: fmtDay.format(day(d.date)), aqi: d.aqi, kind: i === 0 ? 'latest' : 'fc', dom: d.dominant })) };
    }
  }
  return { kind: 'none', items: [] };
}

function renderHero() {
  const c = S.city, e = S.entry;
  $('#city-name').textContent = c.name;
  $('#state').textContent = c.state || '';
  const { kind, items } = heroItems();
  const hero = $('#hero');
  const notice = $('#notice');
  notice.hidden = true;

  if (!items.length) {
    hero.className = 'hero b-none';
    $('#sky').innerHTML = $('#sky-head').innerHTML = $('#sky-days').innerHTML = '';
    $('#status').textContent = S.liveErr ? 'The live data service did not respond, so there is nothing to show for this place yet.' : 'Loading…';
    $('#advice').textContent = '';
    $('#dominant').textContent = '';
    if (S.liveErr) { notice.hidden = false; notice.innerHTML = 'Check your connection and <a href="" id="retry">try again</a>.'; $('#retry').onclick = (ev) => { ev.preventDefault(); selectCity(c); }; }
    return;
  }

  const first = items[0];
  const b = band(first.aqi);
  hero.className = `hero ${b.cls}`;
  const when = kind === 'live' ? 'Today (model estimate)' : `Latest reading, ${fmtLong.format(day(e.as_of))}`;
  $('#status').innerHTML = `${esc(when)}: <strong class="${b.cls}">AQI ${first.aqi} · ${b.name}</strong>`;
  $('#advice').textContent = b.advice;

  // skyline
  const n = items.length;
  const top = Math.max(150, ...items.map((i) => (i.hi ?? i.aqi))) * 1.22;
  $('.sky-wrap').style.setProperty('--n', n);
  $('#sky-head').innerHTML = `<span>${kind === 'live' ? 'Today' : 'Latest'}</span><span style="grid-column: 2 / -1">${kind === 'live' ? 'Open-Meteo model forecast' : 'Forecast, with likely range'}</span>`;
  $('#sky').innerHTML = items.map((it, i) => {
    const bb = band(it.aqi);
    const pct = (v) => `${(v / top) * 100}%`;
    const range = it.lo != null ? `, likely ${it.lo} to ${it.hi}` : '';
    return `<li class="${bb.cls}" style="--h:${pct(it.aqi)};--i:${i};${it.lo != null ? `--lo:${pct(it.lo)};--hi:${pct(it.hi)}` : ''}" aria-label="${esc(it.label)}: AQI ${it.aqi}, ${bb.name}${range}">
      <span class="val">${it.aqi}</span><span class="bar"></span>${it.lo != null ? '<span class="whisker"></span>' : ''}</li>`;
  }).join('');
  $('#sky-days').innerHTML = items.map((it) => `<li>${esc(it.label)}</li>`).join('');

  // pollutant line
  const dom = $('#dominant');
  if (kind === 'stored' && e.next_dominant) {
    const parts = Object.entries(e.next_dominant).sort((a, b) => b[1] - a[1]).slice(0, 2);
    dom.innerHTML = `Likely main pollutant next day: <b>${LABEL[parts[0][0]]}</b> (${Math.round(parts[0][1] * 100)}%)${parts[1] ? `, then ${LABEL[parts[1][0]]} (${Math.round(parts[1][1] * 100)}%)` : ''}.`;
  } else if (kind === 'live' && first.dom) {
    dom.innerHTML = `Main pollutant today: <b>${LABEL[first.dom]}</b>.`;
  } else dom.textContent = '';

  // notices
  const msgs = [];
  if (kind === 'live' && e && e.stale_days > 3) msgs.push(`Hawa's stored forecast for ${esc(c.name)} ends at ${fmtLong.format(day(e.as_of))}, so this view uses the Open-Meteo model until the data pipeline runs again.`);
  if (kind === 'live' && !e) msgs.push(`Hawa's trained forecast covers ${S.cities.length} tracked cities. This place shows the Open-Meteo model forecast instead.${nearestHint(c)}`);
  if (kind === 'stored' && e.stale_days > 3) msgs.push(`These are the latest stored readings (${e.stale_days} days old). New data arrives when the collection job runs.`);
  if (msgs.length) { notice.hidden = false; notice.innerHTML = msgs.join(' '); wireNearest(); }
}

function nearest(c) {
  let best = null;
  for (const t of S.cities) { const d = Math.hypot((t.lat - c.lat) * 111, (t.lon - c.lon) * 111 * Math.cos((c.lat * Math.PI) / 180)); if (!best || d < best.d) best = { t, d }; }
  return best;
}
function nearestHint(c) {
  const n = nearest(c);
  return n ? ` Nearest tracked city: <a href="" data-pick="${esc(n.t.slug)}">${esc(n.t.name)}</a> (${Math.round(n.d)} km).` : '';
}
function wireNearest() {
  document.querySelectorAll('[data-pick]').forEach((a) => a.addEventListener('click', (ev) => { ev.preventDefault(); const t = S.cities.find((x) => x.slug === a.dataset.pick); if (t) selectCity({ ...t, tracked: true }); }));
}

/* ───────── live tiles ───────── */
function renderLive() {
  const tiles = $('#tiles');
  const lv = S.live;
  if (!lv) {
    tiles.innerHTML = `<p class="meta">${S.liveErr ? 'Live readings are not available right now.' : ''}</p>`;
    $('#live-meta').innerHTML = S.liveErr ? '<a href="" id="retry2">Try again</a>' : '';
    const r = $('#retry2'); if (r) r.onclick = (ev) => { ev.preventDefault(); selectCity(S.city); };
    return;
  }
  const subs = POLLUTANTS.map((p) => subIndex(p.key, lv.now[p.key]));
  const maxI = subs.reduce((m, v, i) => (!Number.isNaN(v) && v > (subs[m] ?? -1) ? i : m), 0);
  tiles.innerHTML = POLLUTANTS.map((p, i) => {
    const v = lv.now[p.key], s = subs[i];
    const b = Number.isNaN(s) ? null : band(s);
    const txt = v == null ? '–' : p.key === 'co' ? v.toFixed(2) : v < 10 ? v.toFixed(1) : Math.round(v);
    return `<div class="tile ${i === maxI && b ? 'is-dom' : ''} ${b ? b.cls : 'b-none'}">
      <div class="nm">${p.label}<small>${i === maxI && b ? 'Highest now' : ''}</small></div>
      <div class="num">${txt}<small>${p.unit}</small></div>
      <div class="meter" aria-hidden="true"><i style="--w:${Math.max(3, (s / 500) * 100 || 0)}%"></i></div>
      <div class="cat">${b ? b.name : 'No reading'}</div>
      <div class="hint">${p.hint}</div></div>`;
  }).join('');
  $('#live-meta').textContent = `${S.city.name} · hour starting ${lv.time.slice(11)} IST · Open-Meteo (CAMS model)`;
}

/* ───────── charts ───────── */
const bandZones = {
  id: 'bandZones',
  beforeDatasetsDraw(chart) {
    const { ctx, chartArea: a, scales: { y } } = chart;
    if (!a) return;
    ctx.save();
    ctx.globalAlpha = 0.11;
    let lo = 0;
    BANDS.forEach((b, i) => {
      const y1 = y.getPixelForValue(Math.min(b.max, y.max)), y0 = y.getPixelForValue(lo);
      if (lo < y.max) { ctx.fillStyle = css(bandVar[i]); ctx.fillRect(a.left, y1, a.right - a.left, y0 - y1); }
      lo = b.max;
    });
    ctx.restore();
  },
};
function baseChart(canvas, labels, datasets, extra = {}) {
  charts[canvas]?.destroy();
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = css('--muted');
  Chart.defaults.borderColor = css('--line');
  charts[canvas] = new Chart($('#' + canvas), {
    type: 'line', plugins: [bandZones],
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      scales: { y: { beginAtZero: true, grid: { display: false }, title: { display: true, text: 'AQI' } }, x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 9 } } },
      plugins: { legend: { labels: { usePointStyle: true, boxWidth: 8, filter: (i) => !i.text.startsWith('_') } }, tooltip: { filter: (i) => !i.dataset.label.startsWith('_') } },
      ...extra,
    },
  });
}

function renderOutlook() {
  const note = $('#outlook-note'), card = $('#outlook').closest('.chart-card');
  const lv = S.live;
  if (!lv) { card.hidden = true; return; }
  card.hidden = false;
  const daily = lv.daily.filter((d) => !Number.isNaN(d.aqi));
  const labels = daily.map((d) => d.date);
  const ink = css('--ink'), accent = css('--accent');
  const sets = [{ label: 'Open-Meteo model (CAMS)', data: daily.map((d) => d.aqi), borderColor: css('--muted'), borderDash: [6, 4], pointRadius: 3, tension: 0.25 }];
  if (freshEntry()) {
    const m = new Map(S.entry.forecast.map((f) => [f.date, f]));
    sets.push({ label: '_lo', data: labels.map((l) => m.get(l)?.lo ?? null), borderWidth: 0, pointRadius: 0, fill: false });
    sets.push({ label: 'Likely range', data: labels.map((l) => m.get(l)?.hi ?? null), borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: accent + '33' });
    sets.push({ label: 'Hawa forecast', data: labels.map((l) => m.get(l)?.aqi ?? null), borderColor: ink, backgroundColor: ink, pointRadius: 4, tension: 0.25 });
    note.textContent = 'Both lines are daily AQI on the India scale. Where they disagree, the likely range shows how unsure Hawa is.';
  } else {
    note.textContent = S.entry ? 'Hawa\'s own forecast for this city will appear here once fresh data has been collected.' : 'Hawa\'s own forecast covers tracked cities only.';
  }
  baseChart('outlook', labels.map((d) => fmtShort.format(day(d))), sets);
}

function renderForecast() {
  const e = S.entry;
  const secs = ['#fctable', '#fcchart'].map((s) => $(s).closest('.table-wrap, .chart-card'));
  if (!e) {
    secs.forEach((x) => (x.hidden = true));
    $('#dom-card').hidden = true;
    $('#fc-meta').innerHTML = `No trained forecast for ${esc(S.city.name)}.${nearestHint(S.city)}`;
    wireNearest();
    return;
  }
  secs.forEach((x) => (x.hidden = false));
  $('#fc-meta').textContent = `Issued from data through ${fmtLong.format(day(e.as_of))}${e.series === 'open-meteo' ? ' (Open-Meteo)' : ' (CPCB records)'}. The range covers about 80% of past outcomes.`;
  const pol = e.pollutants;
  const head = `<thead><tr><th>Day</th><th>AQI</th><th>Likely range</th><th>Category</th>${pol ? POLLUTANTS.map((p) => `<th>${p.label} <small>${p.unit}</small></th>`).join('') : ''}</tr></thead>`;
  const rows = e.forecast.map((f, i) => {
    const b = band(f.aqi);
    return `<tr><td>${fmtDay.format(day(f.date))}</td><td><b>${f.aqi}</b></td><td>${f.lo}–${f.hi}</td><td><span class="chip ${b.cls}">${b.name}</span></td>${pol ? POLLUTANTS.map((p) => `<td>${pol[p.key] ? pol[p.key][i] : '–'}</td>`).join('') : ''}</tr>`;
  }).join('');
  $('#fctable').innerHTML = `${head}<tbody>${rows}</tbody>`;

  const dc = $('#dom-card');
  if (e.next_dominant) {
    dc.hidden = false;
    dc.innerHTML = `<h3>Likely main pollutant the next day</h3>` + Object.entries(e.next_dominant).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<div class="dom-row"><span>${LABEL[k]}</span><span class="track"><i style="--w:${v * 100}%"></i></span><span>${Math.round(v * 100)}%</span></div>`).join('');
  } else dc.hidden = true;
  renderForecastChart();
}

function renderForecastChart() {
  const e = S.entry;
  if (!e) return;
  const asOf = day(e.as_of);
  const N = 45;
  const dates = Array.from({ length: N + 7 }, (_, i) => addDays(asOf, i - N + 1));
  const actual = dates.map((d) => {
    if (!S.hist) return d.getTime() === asOf.getTime() ? e.current.aqi : null;
    const i = daysBetween(day(S.hist.start), d);
    return d <= asOf && i >= 0 ? S.hist.aqi[i] ?? null : null;
  });
  const fc = new Map(e.forecast.map((f) => [f.date, f]));
  const pick = (k) => dates.map((d) => { const f = fc.get(isoDay(d)); return f ? f[k] : d.getTime() === asOf.getTime() ? e.current.aqi : null; });
  const ink = css('--ink'), accent = css('--accent');
  baseChart('fcchart', dates.map((d) => fmtShort.format(d)), [
    { label: 'Recorded AQI', data: actual, borderColor: ink, backgroundColor: ink, pointRadius: 0, borderWidth: 2, tension: 0.2, spanGaps: false },
    { label: '_lo', data: pick('lo'), borderWidth: 0, pointRadius: 0, fill: false },
    { label: 'Likely range', data: pick('hi'), borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: accent + '40' },
    { label: 'Forecast', data: pick('aqi'), borderColor: accent, backgroundColor: accent, borderDash: [5, 4], borderWidth: 2.5, pointRadius: 3, tension: 0.2 },
  ]);
}

/* ───────── map + ranking ───────── */
let map = null, tileLayer = null;
const markers = new Map();
const entryOf = (name) => S.forecast?.cities?.[name];
function pinIcon(name) {
  const e = entryOf(name);
  const v = e ? e.current.aqi : null;
  const sel = S.city && S.city.name === name;
  const size = sel ? 34 : 26;
  const b = v == null ? { cls: 'b-none' } : band(v);
  return L.divIcon({ className: '', iconSize: [size, size], html: `<div class="pin ${b.cls}" style="width:${size}px;height:${size}px;${sel ? 'border-color:var(--ink);border-width:3px' : ''}">${v ?? ''}</div>` });
}
function setTiles() {
  const dark = css('color-scheme') === 'dark';
  tileLayer?.remove();
  tileLayer = L.tileLayer(`https://{s}.basemaps.cartocdn.com/${dark ? 'dark_all' : 'light_all'}/{z}/{x}/{y}{r}.png`, { maxZoom: 10, subdomains: 'abcd', attribution: '© OpenStreetMap © CARTO' }).addTo(map);
}
function drawMap() {
  if (!S.forecast) { $('#mapbox').innerHTML = '<p class="meta" style="padding:1rem">Forecast data is not available.</p>'; return; }
  map = L.map('mapbox', { zoomControl: true, scrollWheelZoom: false, attributionControl: false }).fitBounds([[7.5, 69], [34, 90]]);
  setTiles();
  for (const c of S.cities) {
    if (!entryOf(c.name)) continue;
    const m = L.marker([c.lat, c.lon], { icon: pinIcon(c.name), keyboard: true, title: `${c.name}: AQI ${entryOf(c.name).current.aqi}` }).addTo(map);
    m.on('click', () => selectCity({ ...c, tracked: true }));
    markers.set(c.name, m);
  }
}
function refreshMapSelection() { markers.forEach((m, name) => m.setIcon(pinIcon(name))); }

function renderRanking() {
  const list = S.cities.filter((c) => entryOf(c.name)).map((c) => ({ c, e: entryOf(c.name) }));
  list.sort((a, b) => (S.sort === 'worst' ? b.e.current.aqi - a.e.current.aqi : a.e.current.aqi - b.e.current.aqi));
  const newest = list.reduce((m, x) => (x.e.as_of > m ? x.e.as_of : m), '');
  $('#map-meta').textContent = list.length ? `Latest stored reading per city; newest is ${fmtLong.format(day(newest))}.` : '';
  $('#rank').innerHTML = list.map(({ c, e }, i) => {
    const b = band(e.current.aqi);
    return `<li class="${S.city && S.city.name === c.name ? 'is-current' : ''}"><button type="button" data-slug="${c.slug}"><span class="pos">${i + 1}</span><span class="nm ${b.cls}">${esc(c.name)}<small>${esc(c.state)}</small><span class="bar" style="--w:${(e.current.aqi / 500) * 100}%"></span></span><span class="v">${e.current.aqi}</span></button></li>`;
  }).join('');
  document.querySelectorAll('#rank button').forEach((btn) => btn.addEventListener('click', () => { const c = S.cities.find((x) => x.slug === btn.dataset.slug); selectCity({ ...c, tracked: true }); window.scrollTo({ top: 0, behavior: 'smooth' }); }));
}

/* ───────── a year of air ───────── */
function renderYears() {
  const box = $('#years'), cal = $('#cal'), sum = $('#year-summary');
  if (!S.hist) { box.innerHTML = ''; cal.innerHTML = ''; sum.innerHTML = `<p class="meta">${S.city.tracked ? 'History is loading or not available.' : 'Yearly history is available for tracked cities.'}</p>`; $('#cal-wrap').hidden = true; return; }
  $('#cal-wrap').hidden = false;
  const start = day(S.hist.start), end = addDays(start, S.hist.aqi.length - 1);
  const years = []; for (let y = start.getFullYear(); y <= end.getFullYear(); y++) years.push(y);
  if (!years.includes(S.year)) S.year = years[years.length - 1];
  box.innerHTML = years.map((y) => `<button type="button" aria-pressed="${y === S.year}" data-y="${y}">${y}</button>`).join('');
  box.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => { S.year = +b.dataset.y; renderYears(); }));
  drawCalendar(S.year, start);
}
function drawCalendar(year, histStart) {
  const cal = $('#cal');
  const jan1 = new Date(year, 0, 1), dec31 = new Date(year, 11, 31);
  const off = (jan1.getDay() + 6) % 7;
  const colOf = (d) => Math.floor((off + daysBetween(jan1, d)) / 7) + 1;
  let html = '';
  const counts = new Array(6).fill(0), monthSum = Array.from({ length: 12 }, () => [0, 0]);
  for (let d = new Date(jan1); d <= dec31; d = addDays(d, 1)) {
    const k = daysBetween(histStart, d);
    const v = k >= 0 ? S.hist.aqi[k] : null;
    const col = colOf(d), row = ((off + daysBetween(jan1, d)) % 7) + 2;
    if (v == null) html += `<i class="d none" style="grid-column:${col};grid-row:${row}" title="${fmtLong.format(d)}: no data"></i>`;
    else {
      const b = band(v); counts[bandIndex(v)]++; monthSum[d.getMonth()][0] += v; monthSum[d.getMonth()][1]++;
      html += `<i class="d ${b.cls}" style="grid-column:${col};grid-row:${row}" title="${fmtLong.format(d)}: AQI ${v}, ${b.name}"></i>`;
    }
  }
  for (let m = 0; m < 12; m++) html += `<span class="m" style="grid-column:${colOf(new Date(year, m, 1))} / span 3">${fmtShort.format(new Date(year, m, 1)).split(' ')[1]}</span>`;
  html += `<span class="burn" style="grid-column:${colOf(new Date(year, 9, 15))} / ${colOf(new Date(year, 10, 30)) + 1}">Crop-burning season</span>`;
  cal.innerHTML = html;

  const total = counts.reduce((a, b) => a + b, 0);
  const sum = $('#year-summary');
  if (!total) { sum.innerHTML = `<p class="meta">No data for ${year}.</p>`; return; }
  const poorPlus = counts.slice(3).reduce((a, b) => a + b, 0);
  const avgs = monthSum.map(([s, n], i) => (n >= 10 ? { i, v: s / n } : null)).filter(Boolean);
  const worst = avgs.sort((a, b) => b.v - a.v)[0];
  const mon = (i) => new Date(year, i, 1).toLocaleString('en-IN', { month: 'long' });
  sum.innerHTML = `<p><b>${poorPlus}</b> of ${total} days in ${year} were Poor or worse${worst ? `. The worst month was ${mon(worst.i)}, averaging AQI ${Math.round(worst.v)}` : ''}.${S.hist.om_from && day(S.hist.om_from).getFullYear() <= year ? ` From ${fmtLong.format(day(S.hist.om_from))} the days come from Open-Meteo model data rather than CPCB records.` : ''}</p>
    <div class="stack" role="img" aria-label="Share of days by category">${counts.map((c, i) => `<i class="${BANDS[i].cls}" style="--w:${(c / total) * 100}%"></i>`).join('')}</div>
    <div class="stack-legend">${BANDS.map((b, i) => `<span class="${b.cls}">${b.name} ${counts[i]}</span>`).join('')}</div>`;
}

/* ───────── data & model section ───────── */
function renderModel() {
  const m = S.metrics;
  if (!m) { $('#acc-intro').textContent = 'Accuracy figures are not available yet.'; return; }
  $('#md-meta').textContent = `Models retrained ${fmtLong.format(new Date(m.generated_at))} · ${m.model}`;
  $('#acc-intro').textContent = `Scored on the last ${m.holdout.days} days of data (${fmtShort.format(day(m.holdout.start))} to ${fmtLong.format(day(m.holdout.end))}), which the model never saw while learning. "Same as today" is the simple guess that tomorrow will look like today.`;
  $('#acc').innerHTML = `<thead><tr><th>Days ahead</th><th>Typical error (AQI)</th><th>"Same as today" error</th><th>Right category</th><th>Range hit rate</th></tr></thead><tbody>` +
    m.aqi.map((r) => `<tr><td>${r.horizon}</td><td><b>${r.mae}</b></td><td>${r.baseline_persistence_mae}</td><td>${Math.round(r.band_accuracy * 100)}%</td><td>${Math.round(r.interval_coverage_80 * 100)}%</td></tr>`).join('') + '</tbody>';
  const names = { hist: 'CPCB and Kaggle daily AQI', om: 'Open-Meteo stored readings' };
  const parts = m.data.map((d) => `${names[d.src] || d.src}: ${d.rows.toLocaleString('en-IN')} city-days across ${d.cities} places, ${fmtShort.format(day(d.start))} ${day(d.start).getFullYear()} to ${fmtShort.format(day(d.end))} ${day(d.end).getFullYear()}`);
  const hasOm = m.data.some((d) => d.src === 'om');
  let extra = '';
  if (m.dominant_pollutant) extra += ` The next-day main pollutant is right ${Math.round(m.dominant_pollutant.accuracy * 100)}% of the time, against ${Math.round(m.dominant_pollutant.baseline_same_as_today * 100)}% for "same as today".`;
  $('#acc-intro').textContent += extra;
  $('#sources-note').innerHTML = `<b>Data in this build.</b> ${parts.join('. ')}.${hasOm ? '' : ' Live collection has not stored any readings in this build yet; pollutant-level forecasts appear once it has.'} Pollutant columns in the Kaggle files were left out because every value is a fixed multiple of that day's AQI.`;
}

/* ───────── search ───────── */
function setupSearch() {
  const q = $('#q'), list = $('#results');
  let items = [], active = -1, timer = 0, seq = 0;
  const close = () => { list.hidden = true; q.setAttribute('aria-expanded', 'false'); active = -1; };
  const render = () => {
    list.innerHTML = items.map((it, i) => it.group ? `<li class="grp" role="presentation">${esc(it.group)}</li>` : `<li role="option" id="opt${i}" data-i="${i}" aria-selected="${i === active}">${esc(it.c.name)}<small>${esc(it.c.state || '')}</small></li>`).join('');
    list.hidden = !items.length; q.setAttribute('aria-expanded', String(!!items.length));
  };
  const pick = (it) => { close(); q.value = ''; selectCity(it.c); q.blur(); };
  const tracked = (term) => S.cities.filter((c) => c.name.toLowerCase().includes(term) || c.state.toLowerCase().includes(term)).slice(0, 8).map((c) => ({ c: { ...c, tracked: true } }));
  q.addEventListener('input', () => {
    const term = q.value.trim().toLowerCase();
    clearTimeout(timer);
    if (!term) return close();
    const t = tracked(term);
    items = t.length ? [{ group: 'Tracked cities (forecast + live)' }, ...t] : [];
    active = items.findIndex((i) => !i.group);
    render();
    if (term.length < 3) return;
    timer = setTimeout(async () => {
      const mine = ++seq;
      try {
        const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(term)}&count=8&language=en&format=json&countryCode=IN`);
        const j = await r.json();
        if (mine !== seq) return;
        const known = new Set(t.map((x) => x.c.name.toLowerCase()));
        const more = (j.results || []).filter((p) => !known.has(p.name.toLowerCase())).slice(0, 5)
          .map((p) => ({ c: { name: p.name, state: [p.admin2, p.admin1].filter(Boolean).join(', '), lat: p.latitude, lon: p.longitude, tracked: false } }));
        if (!more.length) return;
        items = [...(t.length ? [{ group: 'Tracked cities (forecast + live)' }, ...t] : []), { group: 'Other places (live data only)' }, ...more];
        active = items.findIndex((i) => !i.group);
        render();
      } catch { /* geocoding is optional */ }
    }, 280);
  });
  q.addEventListener('keydown', (ev) => {
    const opts = items.map((it, i) => (it.group ? -1 : i)).filter((i) => i >= 0);
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      if (!opts.length) return; ev.preventDefault();
      const p = opts.indexOf(active); active = opts[(p + (ev.key === 'ArrowDown' ? 1 : opts.length - 1)) % opts.length]; render();
      q.setAttribute('aria-activedescendant', `opt${active}`);
    } else if (ev.key === 'Enter') { if (items[active] && !items[active].group) { ev.preventDefault(); pick(items[active]); } }
    else if (ev.key === 'Escape') close();
  });
  list.addEventListener('mousedown', (ev) => { const li = ev.target.closest('li[data-i]'); if (li) { ev.preventDefault(); pick(items[+li.dataset.i]); } });
  document.addEventListener('click', (ev) => { if (!ev.target.closest('.finder')) close(); });
}

/* ───────── selecting a place ───────── */
async function selectCity(c) {
  const token = ++S.token;
  S.city = c; S.entry = c.tracked ? entryOf(c.name) || null : null;
  S.hist = null; S.live = null; S.liveErr = null;
  const u = new URL(location.href); u.search = '';
  if (c.tracked) u.searchParams.set('city', c.slug); else { u.searchParams.set('place', c.name); u.searchParams.set('lat', c.lat.toFixed(3)); u.searchParams.set('lon', c.lon.toFixed(3)); }
  history.replaceState(null, '', u);
  document.title = `${c.name} air quality – Hawa`;

  $('#tiles').innerHTML = '<div class="tile skel"></div>'.repeat(6);
  $('#live-meta').textContent = 'Fetching live readings…';
  const needsLive = !S.entry || !freshEntry();
  if (!needsLive) renderHero(); else { $('#city-name').textContent = c.name; $('#state').textContent = c.state || ''; $('#status').textContent = 'Loading…'; }
  renderForecast(); renderYears(); renderRanking(); refreshMapSelection();

  const histP = c.tracked ? getJSON(`data/history/${c.slug}.json`).catch(() => null) : Promise.resolve(null);
  const liveP = fetchLive(c).then((v) => { S.live = v; }, (e) => { S.liveErr = e; });
  histP.then((h) => { if (token !== S.token) return; S.hist = h; renderYears(); renderForecastChart(); });
  await liveP;
  if (token !== S.token) return;
  renderHero(); renderLive(); renderOutlook(); renderForecast();
}

/* ───────── boot ───────── */
async function boot() {
  initTheme();
  $('#legend').innerHTML = BANDS.map((b, i) => `<li class="${b.cls}"><i></i>${b.name} <span class="small">${i ? BANDS[i - 1].max + 1 : 0}–${b.max}</span></li>`).join('');
  const [cities, forecast, metrics] = await Promise.all([getJSON('data/cities.json').catch(() => []), getJSON('data/forecast.json').catch(() => null), getJSON('data/metrics.json').catch(() => null)]);
  S.cities = cities; S.forecast = forecast; S.metrics = metrics;
  Chart.defaults.color = css('--muted');
  setupSearch(); drawMap(); renderModel();
  document.querySelectorAll('[data-sort]').forEach((b) => b.addEventListener('click', () => {
    S.sort = b.dataset.sort;
    document.querySelectorAll('[data-sort]').forEach((x) => x.setAttribute('aria-selected', String(x === b)));
    renderRanking();
  }));
  const p = new URL(location.href).searchParams;
  let start = S.cities.find((c) => c.slug === p.get('city')) || S.cities.find((c) => c.name === 'Delhi') || S.cities[0];
  if (start) start = { ...start, tracked: true };
  if (p.get('place') && p.get('lat')) start = { name: p.get('place'), state: '', lat: +p.get('lat'), lon: +p.get('lon'), tracked: false };
  if (!start) { $('#city-name').textContent = 'No data yet'; $('#status').textContent = 'Run the data pipeline to create public/data files (see README).'; return; }
  await selectCity(start);
}
boot();
