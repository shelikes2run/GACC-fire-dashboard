// FDOP Workbench — build, display and validate an FDRA's fire danger indices, and check each
// year whether they still hold. Data: fdop-data branch (site/build_fdop_data.py).
const FDATA = (new URLSearchParams(location.search).get('fdata')) ||
  'https://raw.githubusercontent.com/' + ((window.AREA && window.AREA.repo) || 'shelikes2run/GACC-fire-dashboard') + '/fdop-data/';
const IDX_LABEL = { erc: 'ERC', bi: 'BI', ic: 'IC', sc: 'SC', f100: '100-hr FM', f1000: '1000-hr FM', kbdi: 'KBDI', gsi: 'GSI', gsic: 'GSI (lower = more cured)' };
// GSI as a breakpoint index: lower GSI = more cured = higher class. Internally the value is negated ('gsic' = −GSI) so every
// class / percentile / option routine keeps "higher = worse"; the helpers below show and read real GSI values.
const NEG = k => k === 'gsic';
const dv = (k, v) => (v === null || v === undefined || isNaN(v)) ? v : NEG(k) ? -v : v;
const fv = (k, v, d = 0) => { const x = dv(k, v); return x === null || x === undefined || isNaN(x) ? '–' : NEG(k) ? x.toFixed(2) : Number(x).toFixed(d); };
const fb = (k, arr) => arr.map(v => NEG(k) ? (-v).toFixed(2) : v).join(' / ');
const rng = (k, lo, hi) => `${fv(k, lo)}–${fv(k, hi)}`;
const MOIST = new Set(['f100', 'f1000', 'gsi']);    // lower = drier / less green: tested on the negative
const FM_FREE = new Set(['f100', 'f1000', 'kbdi', 'gsi']);   // same value for every fuel model
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const CLASS_NAMES = { 5: ['Low', 'Moderate', 'High', 'Very High', 'Extreme'], 4: ['Low', 'Moderate', 'High', 'Extreme'], 3: ['Low', 'Moderate', 'High'] };
// R5 Project Activity Level matrix (ERC-Y / IC-Y, updated 13 Apr 2023); the day's PAL is the lower of the two ratings
const PAL_LEVELS = ['A', 'B', 'C', 'D', 'Ev', 'E'];
// R5 PAL matrix, 2025 regional update for FEMS (as published in the ENF 2026 FDOP, Table 9) — upper bounds of A..Ev
const PAL_ERC = [32, 40, 43, 48, 51];
const PAL_IC = [17, 27, 36, 41, 49];
const palOf = (erc, ic) => {
  if (erc === null || ic === null) return null;
  const lv = (v, b) => { const i = b.findIndex(x => v <= x); return i < 0 ? b.length : i; };
  return Math.min(lv(Math.round(erc), PAL_ERC), lv(Math.round(ic), PAL_IC));
};
const inSeason = (md, s0, s1) => s0 <= s1 ? (md >= s0 && md <= s1) : (md >= s0 || md <= s1);
const seasonLabel = c => `${MONTHS[+c.season[0].slice(0, 2) - 1]} ${+c.season[0].slice(3)} – ${MONTHS[+c.season[1].slice(0, 2) - 1]} ${+c.season[1].slice(3)}`;
const FLAG = ['#2e7d32', '#f9a825', '#c62828'];
const FLAG_TXT = ['OK', 'Watch', 'Review'];

// ── fetch helpers ────────────────────────────────────────────────────────────
const _cache = new Map();
async function fjson(path, gz = false) {
  if (_cache.has(path)) return _cache.get(path);
  const p = (async () => {
    const r = await fetch(FDATA + path + '?t=' + Math.floor(Date.now() / 3600000));
    if (!r.ok) throw new Error(path + ' → ' + r.status);
    if (!gz) return r.json();
    const ds = r.body.pipeThrough(new DecompressionStream('gzip'));
    return JSON.parse(await new Response(ds).text());
  })();
  _cache.set(path, p);
  return p;
}
const stationFile = (sid, fm) => fjson(`stations/${sid}_${fm}.json.gz`, true).catch(() => null);

// ── statistics (mirrors site/build_fdop_data.py) ─────────────────────────────
function erfc(x) { // Abramowitz-Stegun 7.1.26
  const t = 1 / (1 + 0.5 * Math.abs(x));
  const y = t * Math.exp(-x * x - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 +
    t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
  return x >= 0 ? y : 2 - y;
}
function logistic(xs, ys) {
  const x = [], y = [];
  xs.forEach((v, i) => { if (v !== null && !isNaN(v)) { x.push(v); y.push(ys[i]); } });
  const n = x.length, ev = y.reduce((a, b) => a + b, 0);
  if (n < 30 || ev < 3 || ev === n) return null;
  const mu = x.reduce((a, b) => a + b, 0) / n;
  const sd = Math.sqrt(x.reduce((a, b) => a + (b - mu) ** 2, 0) / n) || 1;
  const z = x.map(v => (v - mu) / sd);
  let b0 = Math.log(ev / n / (1 - ev / n)), b1 = 0;
  for (let it = 0; it < 40; it++) {
    let g0 = 0, g1 = 0, h00 = 0, h01 = 0, h11 = 0;
    for (let i = 0; i < n; i++) {
      const p = 1 / (1 + Math.exp(-(b0 + b1 * z[i]))), w = p * (1 - p), r = y[i] - p;
      g0 += r; g1 += r * z[i]; h00 += w; h01 += w * z[i]; h11 += w * z[i] * z[i];
    }
    const det = h00 * h11 - h01 * h01; if (!det) return null;
    const d0 = (h11 * g0 - h01 * g1) / det, d1 = (h00 * g1 - h01 * g0) / det;
    b0 += d0; b1 += d1;
    if (Math.max(Math.abs(d0), Math.abs(d1)) < 1e-9) break;
  }
  let ll = 0, h00 = 0, h01 = 0, h11 = 0;
  for (let i = 0; i < n; i++) {
    const p = Math.min(1 - 1e-12, Math.max(1e-12, 1 / (1 + Math.exp(-(b0 + b1 * z[i])))));
    ll += y[i] * Math.log(p) + (1 - y[i]) * Math.log(1 - p);
    const w = p * (1 - p); h00 += w; h01 += w * z[i]; h11 += w * z[i] * z[i];
  }
  const p0 = ev / n, ll0 = ev * Math.log(p0) + (n - ev) * Math.log(1 - p0);
  const se = Math.sqrt(h00 / (h00 * h11 - h01 * h01));
  const pval = erfc(Math.abs(b1 / se) / Math.SQRT2);
  // AUC via ranks
  const ord = x.map((v, i) => [v, y[i]]).sort((a, b) => a[0] - b[0]);
  let rankSum = 0, i = 0;
  while (i < ord.length) { let j = i; while (j + 1 < ord.length && ord[j + 1][0] === ord[i][0]) j++; const r = (i + j + 2) / 2;
    for (let k = i; k <= j; k++) if (ord[k][1]) rankSum += r; i = j + 1; }
  const auc = (rankSum - ev * (ev + 1) / 2) / (ev * (n - ev));
  const B0 = b0 - b1 * mu / sd, B1 = b1 / sd;
  // binned (deciles) observed vs predicted — the Fire Family Plus style class check
  const bins = [], k = 10;
  for (let q = 0; q < k; q++) {
    const a = Math.floor(q * n / k), b = Math.floor((q + 1) * n / k); if (b <= a) continue;
    const seg = ord.slice(a, b), m = seg.reduce((s, v) => s + v[0], 0) / seg.length, o = seg.reduce((s, v) => s + v[1], 0) / seg.length;
    bins.push({ x: m, obs: o, pred: 1 / (1 + Math.exp(-(B0 + B1 * m))), n: seg.length });
  }
  const om = bins.reduce((s, v) => s + v.obs, 0) / bins.length;
  const ssr = bins.reduce((s, v) => s + (v.obs - v.pred) ** 2, 0), sst = bins.reduce((s, v) => s + (v.obs - om) ** 2, 0);
  return { b0: B0, b1: B1, p: pval, auc, r2: 1 - ll / ll0, r2bin: sst ? 1 - ssr / sst : null, n, events: ev, bins };
}
function pctile(sorted, p) {
  if (!sorted.length) return null;
  const i = (sorted.length - 1) * p / 100, lo = Math.floor(i), hi = Math.ceil(i);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
}
function rankPct(sorted, v) { let lo = 0, hi = sorted.length; while (lo < hi) { const m = (lo + hi) >> 1; if (sorted[m] <= v) lo = m + 1; else hi = m; } return 100 * lo / sorted.length; }
const mean = a => a.length ? a.reduce((s, v) => s + v, 0) / a.length : null;
const sdev = a => { if (a.length < 2) return null; const m = mean(a); return Math.sqrt(a.reduce((s, v) => s + (v - m) ** 2, 0) / (a.length - 1)); };
const median = a => { if (!a.length) return null; const s = a.slice().sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

// ── daily dataset: SIG mean of chosen stations + fire events ─────────────────
function buildDaily(stFiles, fires, cfg, scale, weights) {   // weights: {stationId: w} for an FDOP weighted SIG (missing = 1)
  const files = stFiles.filter(Boolean);
  if (!files.length) return [];
  const start = new Date(files[0].start + 'T00:00:00Z'), n = Math.max(...files.map(f => f.n));
  const fireBy = new Map();
  for (const [d, ac] of fires) {
    const r = fireBy.get(d) || { n: 0, large: 0 }; r.n++; if (ac >= cfg.large) r.large++; fireBy.set(d, r);
  }
  const rows = [];
  for (let i = 0; i < n; i++) {
    const dt = new Date(start.getTime() + i * 864e5), y = dt.getUTCFullYear();
    const ds = dt.toISOString().slice(0, 10);
    if (!inSeason(ds.slice(5), cfg.season[0], cfg.season[1]) || y < cfg.yearsFrom) continue;
    const row = { date: ds, year: y, doy: Math.floor((dt - Date.UTC(y, 0, 1)) / 864e5) + 1 };
    let nst = 0;
    for (const k of Object.keys(IDX_LABEL)) {
      if (k === 'gsic') continue;
      let s = 0, c = 0;
      let wsum = 0;
      for (const f of files) { const v = f[k] && f[k][i]; if (v !== null && v !== undefined) { const w = (weights && weights[f.sid]) || 1; s += w * v / (scale[k] || 1); wsum += w; c++; } }
      row[k] = c ? s / wsum : null; if (k === 'erc') nst = c;
    }
    row.gsic = row.gsi === null || row.gsi === undefined ? null : -row.gsi;
    row.nst = nst;
    const fr = fireBy.get(ds) || { n: 0, large: 0 };
    row.fires = fr.n; row.fd = fr.n > 0 ? 1 : 0; row.lfd = fr.large > 0 ? 1 : 0; row.mfd = fr.n >= cfg.mfd ? 1 : 0;
    rows.push(row);
  }
  return rows;
}
const sv = (rows, k) => rows.map(r => r[k] === null ? null : (MOIST.has(k) ? -r[k] : r[k]));   // signed for tests

// ── decision points ──────────────────────────────────────────────────────────
function parseBreaks(text, idxLabel) {
  // e.g. "Staffing level-ERC Value/Percentile 1-0-21/0-6% 2-22-39/7-32% 3-40-54/33-76% 4-55-61/77-96% 5→62/97%+"
  if (!text) return null;
  const segs = String(text).split('|');
  const seg = segs.find(s => new RegExp(idxLabel, 'i').test(s) && /level/i.test(s)) || segs.find(s => new RegExp(idxLabel, 'i').test(s));
  if (!seg) return null;
  const ups = [];
  for (const m of seg.matchAll(/(\d)\s*-\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)/g)) ups.push(Number(m[3]));
  return ups.length >= 2 ? ups : null;
}
function classTable(rows, k, breaks, sorted) {
  const cls = breaks.length + 1, out = Array.from({ length: cls }, (_, i) => ({ cls: i + 1, days: 0, fd: 0, fires: 0, lfd: 0, mfd: 0 }));
  for (const r of rows) {
    const v = r[k]; if (v === null) continue;
    let c = breaks.findIndex(b => v <= b); if (c < 0) c = breaks.length;
    const o = out[c]; o.days++; o.fd += r.fd; o.fires += r.fires; o.lfd += r.lfd; o.mfd += r.mfd;
  }
  const tot = out.reduce((s, o) => s + o.days, 0), totL = out.reduce((s, o) => s + o.lfd, 0);
  out.forEach((o, i) => {
    o.lo = i === 0 ? (sorted[0] ?? 0) : breaks[i - 1]; o.hi = i < breaks.length ? breaks[i] : (sorted[sorted.length - 1] ?? 0);
    o.pLo = i === 0 ? 0 : rankPct(sorted, breaks[i - 1]); o.pHi = i < breaks.length ? rankPct(sorted, breaks[i]) : 100;
    o.pct = tot ? o.days / tot : 0; o.pFD = o.days ? o.fd / o.days : null; o.pLFD = o.days ? o.lfd / o.days : null;
    o.pMFD = o.days ? o.mfd / o.days : null; o.fpd = o.days ? o.fires / o.days : null; o.shareL = totL ? o.lfd / totL : null;
  });
  const mono = key => out.every((o, i) => i === 0 || o[key] === null || out[i - 1][key] === null || o[key] >= out[i - 1][key] - 1e-9);
  return { classes: out, monoFD: mono('pFD'), monoLFD: mono('pLFD') };
}

// ── annual delta (mirrors scorecard() in build_fdop_data.py) ─────────────────
function annualDelta(rows, cfg, burned, k = 'erc') {
  const cal = rows.filter(r => r.year >= cfg.calibFrom && r.year <= cfg.calibTo);
  const e = cal.map(r => r[k]).filter(v => v !== null).sort((a, b) => a - b);
  if (e.length < 300) return null;
  const q90 = pctile(e, 90), q97 = pctile(e, 97);
  const byYear = y => rows.filter(r => r.year === y);
  const years = [...new Set(rows.map(r => r.year))].sort();
  const perCal = [...new Set(cal.map(r => r.year))].map(y => { const g = byYear(y); return { fires: g.reduce((s, r) => s + r.fires, 0), lfd: g.reduce((s, r) => s + r.lfd, 0) }; });
  const fm = mean(perCal.map(p => p.fires)), fs = sdev(perCal.map(p => p.fires)) || 1;
  const lm = mean(perCal.map(p => p.lfd)), ls = sdev(perCal.map(p => p.lfd)) || 1;
  const calLR = logistic(cal.map(r => r[k]), cal.map(r => r.fd));
  const calL = cal.filter(r => r.lfd && r[k] !== null);
  const topShare = calL.length ? calL.filter(r => r[k] >= q90).length / calL.length : null;
  const calDoy = median(cal.filter(r => r.fd).map(r => r.doy));
  const out = [];
  for (const y of years) {
    const g = byYear(y), ev = g.filter(r => r[k] !== null);
    if (ev.length < 30) continue;
    const r = { year: y, days: ev.length, complete: ev.length / g.length };
    r.ercPctl = mean(ev.map(x => rankPct(e, x[k])));
    r.ge90 = ev.filter(x => x[k] >= q90).length; r.ge97 = ev.filter(x => x[k] >= q97).length;
    r.exp90 = 0.10 * ev.length; r.exp97 = 0.03 * ev.length;
    r.fires = g.reduce((s, x) => s + x.fires, 0); r.lfd = g.reduce((s, x) => s + x.lfd, 0); r.fd = g.reduce((s, x) => s + x.fd, 0);
    r.firesZ = (r.fires - fm) / fs; r.lfdZ = (r.lfd - lm) / ls;
    const fdoy = median(g.filter(x => x.fd).map(x => x.doy));
    r.doyShift = fdoy !== null && calDoy !== null ? fdoy - calDoy : null;
    const ly = g.filter(x => x.lfd && x[k] !== null);
    r.lfdHit90 = ly.length ? ly.filter(x => x[k] >= q90).length / ly.length : null;
    const lr = logistic(g.map(x => x[k]), g.map(x => x.fd)); r.auc = lr ? lr.auc : null;
    const b = burned && burned.by_year ? burned.by_year[y] : null;
    r.burned = b ? b.pct : 0; r.burnedFires = b ? b.fires : [];
    r.burned5 = burned && burned.trailing5_pct ? (burned.trailing5_pct[y] || 0) : 0;
    const f = {};
    f.weather = r.ge97 > 3 * Math.max(r.exp97, 1) ? 2 : r.ge90 > 2 * Math.max(r.exp90, 1) ? 1 : 0;
    f.fire = Math.abs(r.firesZ) >= 2 || Math.abs(r.lfdZ) >= 2 ? 2 : Math.abs(r.firesZ) >= 1 || Math.abs(r.lfdZ) >= 1 ? 1 : 0;
    f.timing = r.doyShift === null ? 0 : Math.abs(r.doyShift) >= 30 ? 2 : Math.abs(r.doyShift) >= 15 ? 1 : 0;
    f.index = 0;
    if (r.auc !== null && calLR) { const drop = calLR.auc - r.auc; f.index = drop >= 0.10 ? 2 : drop >= 0.05 ? 1 : 0; }
    if (r.lfdHit90 !== null && topShare !== null && r.lfdHit90 < topShare - 0.25) f.index = Math.max(f.index, 1);
    f.veg = r.burned5 >= cfg.vegRed ? 2 : r.burned5 >= cfg.vegYellow ? 1 : 0;
    f.station = r.complete < 0.6 ? 2 : r.complete < cfg.completeMin ? 1 : 0;
    r.flags = f;
    const v = Object.values(f);
    r.verdict = (f.veg === 2 || v.filter(x => x === 2).length >= 2) ? 2 : (v.includes(2) || v.filter(x => x === 1).length >= 2) ? 1 : 0;
    out.push(r);
  }
  return { years: out, q90, q97, calAUC: calLR ? calLR.auc : null, topShare, fm, fs, lm, ls, calDoy };
}
