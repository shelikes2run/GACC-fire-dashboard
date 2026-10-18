"""
ca_normals.py
─────────────
California NFDRS normals (default 2016–2025) by RAWS station, PSA and FDRA.

Station list comes from the live "CA NFDRS 3.0 (FEMS)" layer (California + Hawaii) that the
Experience Builder app displays (oncc_oscc_scripting, NIFC org), so the
normals line up 1:1 with the live values: same stations, same PSA
assignments, same fuel model (Y).

Pipeline
  1. stations  ← CA NFDRS 3.0 RAWS layer (public REST; CA + HI)
  2. FDRAs     ← FDOP stations + fuel model per FDRA (2026 Forest Thresholds sheet)
  3. download  ← FEMS download-nfdr-daily-summary (public, no key), batches of 20
                 stations per request per year, cached so re-runs only fetch what's missing
  4. aggregate ← observed (NFDRType=O) daily values → PSA / FDRA daily means
                 (same rule as the dashboard: average reporting stations)
  5. normals   ← annual percentiles + day-of-year normals per unit & index
  6. outputs   ← CSVs ready to add to ArcGIS Online as hosted tables

Used by CA_Normals_2016_2025.ipynb — run the notebook, not this file.
"""

from __future__ import annotations

import re
import json
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests

log = logging.getLogger('ca_normals')

CA_NFDRS_URL = ('https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/'
                'CA_NFDRS/FeatureServer')
FEMS_URL = 'https://fems.fs2c.usda.gov/api/ext-climatology/download-nfdr-daily-summary/'

# index key → FEMS CSV column
FIELD_COLS = {
    'erc': 'ERC', 'ic': 'IC', 'bi': 'BI', 'sc': 'SC',
    'fm1': '1HrFM', 'fm10': '10HrFM', 'fm100': '100HrFM', 'fm1000': '1000HrFM',
    'kbdi': 'KBDI', 'gsi': 'GSI', 'woody': 'WoodyFM', 'herb': 'HerbFM',
}
INDICES = list(FIELD_COLS)
MOISTURE = {'fm1', 'fm10', 'fm100', 'fm1000', 'woody', 'herb'}
# Annual percentiles: dry-side lows matter for fuel moisture, highs for indices.
ANNUAL_PCTS = [3, 5, 10, 20, 50, 80, 90, 95, 97]
DOY_STATS = ['mean', 'p10', 'p25', 'p50', 'p75', 'p90']
DOY_WINDOW = 7          # ± days pooled around each day-of-year (15-day window)


# ── 1. Stations ───────────────────────────────────────────────────────────────
def load_ca_stations(exclude_gaccs=()) -> pd.DataFrame:
    url = f'{CA_NFDRS_URL}/0/query'
    params = dict(where='1=1', outFields='stationId,StationName,GACC,PSA,FuelModel,Latitude,Longitude,Unit,Agency',
                  returnGeometry='false', f='json', resultRecordCount=2000)
    feats = requests.get(url, params=params, timeout=60).json()['features']
    df = pd.DataFrame([f['attributes'] for f in feats])
    df = df[~df['GACC'].isin(exclude_gaccs)].copy()
    df['stationId'] = df['stationId'].astype(int)
    df['FuelModel'] = df['FuelModel'].fillna('Y')
    log.info('CA stations: %d (%s)', len(df), df['GACC'].value_counts().to_dict())
    return df.reset_index(drop=True)


def load_ca_psas() -> pd.DataFrame:
    url = f'{CA_NFDRS_URL}/1/query'
    feats = requests.get(url, params=dict(where='1=1', outFields='PSANationalCode,PSAName,GACCUnitID',
                                          returnGeometry='false', f='json'), timeout=60).json()['features']
    return pd.DataFrame([f['attributes'] for f in feats])


# ── 2. FDRA station lists (2026 Forest Thresholds sheet) ──────────────────────
def load_fdra_membership(csv_path) -> tuple[dict, pd.DataFrame]:
    """FDOP station lists from the 2026 Forest Thresholds sheet
    (fdra_station_membership_2026.csv from align_fdras_to_sheet.py).

    Returns ({fdra_id: [(stationId, fuel_model), ...]}, pairs DataFrame with
    stationId / FuelModel for download). Seasonal FDRAs (e.g. ENF 335 peak /
    non-peak) become separate units: 'ENF-335 (peak)'.
    """
    m = pd.read_csv(csv_path).fillna('')
    m['unit'] = np.where(m['season'] != '', m['fdra_id'] + ' (' + m['season'] + ')', m['fdra_id'])
    mem = {u: list(zip(g['stationId'].astype(int), g['fuel_model'])) for u, g in m.groupby('unit')}
    pairs = m[['stationId', 'fuel_model']].rename(columns={'fuel_model': 'FuelModel'}).drop_duplicates()
    log.info('FDRA membership: %d FDRAs, %d station × fuel-model pairs', len(mem), len(pairs))
    return mem, pairs


# ── 3. FEMS download (public, batched, cached) ────────────────────────────────
# FEMS ext-climatology downloads are public (no API key). One request takes many
# stations and several fuel models: e.g. 20 stations × 3 fuel models × 1 year ≈ 3 s.
FEMS_WX_URL = 'https://fems.fs2c.usda.gov/api/ext-climatology/download-wx-daily-summary/'
BATCH = 20


def _fems_get(url, ids, start, end, fuel_models=None, dataset='observation', retries=4):
    params = dict(dataset=dataset, startDate=start, endDate=end, dataFormat='csv',
                  stationIds=','.join(map(str, ids)))
    if fuel_models:
        params['fuelModels'] = ','.join(fuel_models)
    for a in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, headers={'Accept': 'text/csv'}, timeout=300)
            if r.status_code == 404:
                return ''
            r.raise_for_status()
            return r.text
        except Exception:
            if a == retries:
                raise
            time.sleep(5 * a)


def _batches(ids, n=None):
    n = n or BATCH
    ids = sorted({int(i) for i in ids})
    return [ids[i:i + n] for i in range(0, len(ids), n)]


def _tag(ids):
    import hashlib
    return hashlib.md5(','.join(map(str, ids)).encode()).hexdigest()[:8]


def _download(url, prefix, ids, fuel_models, start_year, end_year, raw_dir, workers):
    raw_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for chunk in _batches(ids):
        for y in range(start_year, end_year + 1):
            f = raw_dir / f'{prefix}_{y}_{_tag(chunk)}.csv'
            if not f.exists():
                jobs.append((chunk, y, f))
    log.info('FEMS %s: %d batch-years to download', prefix, len(jobs))
    failed = []

    def one(job):
        chunk, y, f = job
        txt = _fems_get(url, chunk, f'{y}-01-01', f'{y}-12-31', fuel_models)
        f.write_text(txt or '', encoding='utf-8')

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(one, j): j for j in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                fut.result()
            except Exception as e:
                failed.append((futs[fut][1], str(e)[:120]))
            if i % 25 == 0:
                log.info('  %d / %d', i, len(jobs))
    if failed:
        log.warning('%d batch-years failed (re-run to retry): %s', len(failed), failed[:5])
    return failed


def download_history(stations: pd.DataFrame, start_year: int, end_year: int, raw_dir: Path,
                     workers: int = 4):
    """Batched, cached NFDR daily summaries (observed). `stations` needs stationId and
    FuelModel; all fuel models in use are requested for every station (one call per
    batch of 20 stations per year). Public FEMS endpoint — no login."""
    fms = sorted(stations['FuelModel'].dropna().astype(str).str.upper().unique())
    return _download(FEMS_URL, 'nfdr_' + ''.join(fms), stations['stationId'], fms,
                     start_year, end_year, raw_dir, workers)


def load_history(stations: pd.DataFrame, start_year: int, end_year: int, raw_dir: Path) -> pd.DataFrame:
    """Observed daily values: columns stationId, fm, date, <indices>."""
    want = set(zip(stations['stationId'].astype(int), stations['FuelModel'].astype(str).str.upper()))
    frames = []
    for f in sorted(raw_dir.glob('nfdr_*.csv')):
        if f.stat().st_size < 50:
            continue
        df = pd.read_csv(f)
        df.columns = df.columns.str.strip()
        if 'ObservationTime' not in df.columns:
            continue
        df = df[df['NFDRType'].astype(str).str.upper() == 'O']
        out = pd.DataFrame({'stationId': pd.to_numeric(df['StationId'], errors='coerce'),
                            'fm': df['FuelModel'].astype(str).str.upper(),
                            'date': pd.to_datetime(df['ObservationTime'], errors='coerce').dt.normalize()})
        for k, col in FIELD_COLS.items():
            out[k] = pd.to_numeric(df[col], errors='coerce') if col in df.columns else np.nan
        frames.append(out.dropna(subset=['date', 'stationId']))
    hist = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=['stationId', 'fm', 'date', *INDICES])
    hist['stationId'] = hist['stationId'].astype(int)
    hist = hist[[p in want for p in zip(hist['stationId'], hist['fm'])]]
    hist = hist[hist['date'].dt.year.between(start_year, end_year)]
    hist = hist.groupby(['stationId', 'fm', 'date'], as_index=False)[INDICES].mean()
    for k in INDICES:                       # FEMS uses negatives for missing
        hist.loc[hist[k] < 0, k] = np.nan
    log.info('History: %d station-days, %d stations, %s → %s', len(hist), hist['stationId'].nunique(),
             hist['date'].min(), hist['date'].max())
    return hist


# ── 4. Aggregate to PSA / FDRA ────────────────────────────────────────────────
def unit_daily(hist: pd.DataFrame, membership: dict, unit_type: str, fuel_model='Y') -> pd.DataFrame:
    """Daily mean of member stations for each unit (non-reporting stations ignored).

    membership: {unit_id: [stationId, ...]} using `fuel_model` for every unit, or
                {unit_id: [(stationId, fuel_model), ...]} for per-unit fuel models (FDRAs).
    """
    parts = []
    for uid, members in membership.items():
        pairs = [m if isinstance(m, tuple) else (m, fuel_model) for m in members]
        key = pd.MultiIndex.from_tuples(pairs, names=['stationId', 'fm'])
        sub = hist[pd.MultiIndex.from_frame(hist[['stationId', 'fm']]).isin(key)]
        if sub.empty:
            continue
        g = sub.groupby('date')[INDICES].mean()
        g['n_reporting'] = sub.groupby('date')['stationId'].nunique()
        g = g.reset_index()
        g.insert(0, 'unit_id', uid)
        g.insert(0, 'unit_type', unit_type)
        parts.append(g)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ── 5. Normals ────────────────────────────────────────────────────────────────
def annual_normals(daily: pd.DataFrame) -> pd.DataFrame:
    """One row per unit: n_days + mean and percentiles of every index (full year)."""
    rows = []
    for (ut, uid), g in daily.groupby(['unit_type', 'unit_id']):
        r = {'unit_type': ut, 'unit_id': uid, 'n_days': len(g),
             'first_date': g['date'].min().date().isoformat(), 'last_date': g['date'].max().date().isoformat()}
        for k in INDICES:
            v = g[k].dropna().to_numpy()
            r[f'{k}_n'] = len(v)
            r[f'{k}_mean'] = round(float(v.mean()), 2) if len(v) else None
            for p in ANNUAL_PCTS:
                r[f'{k}_p{p}'] = round(float(np.percentile(v, p)), 2) if len(v) else None
        rows.append(r)
    return pd.DataFrame(rows)


def doy_normals(daily: pd.DataFrame, plot_year: int) -> pd.DataFrame:
    """Day-of-year normals (± DOY_WINDOW days, all years pooled).

    One row per unit × day (1–365; Feb 29 folded into Feb 28). `plot_date`
    puts every row on the same calendar year so Experience Builder line charts
    can overlay normals on the current season.
    """
    import warnings
    d = daily.copy()
    doy = d['date'].dt.dayofyear
    leap = d['date'].dt.is_leap_year
    d['doy'] = np.where(leap & (doy > 59), doy - 1, doy)      # 1..365
    base = pd.Timestamp(f'{plot_year}-01-01')
    days = np.arange(1, 366)
    shifts = range(-DOY_WINDOW, DOY_WINDOW + 1)
    frames = []
    for (ut, uid), g in d.groupby(['unit_type', 'unit_id']):
        out = pd.DataFrame({'unit_type': ut, 'unit_id': uid, 'doy': days,
                            'plot_date': base + pd.to_timedelta(days - 1, unit='D') + pd.Timedelta(hours=12),
                            'month_day': (base + pd.to_timedelta(days - 1, unit='D')).strftime('%m-%d')})
        rank = g.groupby('doy').cumcount().to_numpy()          # nth value for that doy
        width = int(rank.max()) + 1 if len(rank) else 1
        for k in INDICES:
            M = np.full((365, width), np.nan)
            M[g['doy'].to_numpy() - 1, rank] = g[k].to_numpy()
            W = np.concatenate([np.roll(M, -o, axis=0) for o in shifts], axis=1)   # (365, 15*width)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', RuntimeWarning)  # all-NaN windows → NaN
                out[f'{k}_mean'] = np.round(np.nanmean(W, axis=1), 2)
                q = np.nanpercentile(W, [10, 25, 50, 75, 90], axis=1)
            for i, name in enumerate(['p10', 'p25', 'p50', 'p75', 'p90']):
                out[f'{k}_{name}'] = np.round(q[i], 2)
        frames.append(out)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ── 6. Write outputs ──────────────────────────────────────────────────────────
def write_outputs(out_dir: Path, start_year: int, end_year: int, stations, fdra_tbl,
                  annual: pd.DataFrame, doy: pd.DataFrame):
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f'{start_year}_{end_year}'
    files = {}
    meta = {'period': f'{start_year}-{end_year}', 'generated': date.today().isoformat(),
            'source': 'FEMS download-nfdr-daily-summary, observed (NFDRType=O) daily values',
            'stations_from': 'CA NFDRS 3.0 (FEMS) RAWS layer (California + Hawaii)',
            'fuel_model': sorted(stations['FuelModel'].unique().tolist()),
            'aggregation': 'unit daily value = mean of reporting member stations',
            'annual_percentiles': ANNUAL_PCTS, 'doy_window_days': 2 * DOY_WINDOW + 1}
    files['annual'] = out_dir / f'ca_normals_annual_{tag}.csv'
    annual.to_csv(files['annual'], index=False)
    files['doy'] = out_dir / f'ca_normals_doy_{tag}.csv'
    doy.to_csv(files['doy'], index=False)
    st = stations.copy()
    files['stations'] = out_dir / f'ca_normals_stations_{tag}.csv'
    st.to_csv(files['stations'], index=False)
    if fdra_tbl is not None:
        ft = fdra_tbl.copy()
        ft['stations'] = ft['stations'].apply(lambda s: ', '.join(map(str, s)))
        files['fdra'] = out_dir / f'ca_fdra_stations_{tag}.csv'
        ft.to_csv(files['fdra'], index=False)
    files['meta'] = out_dir / f'ca_normals_meta_{tag}.json'
    files['meta'].write_text(json.dumps(meta, indent=2))
    for k, f in files.items():
        log.info('wrote %-9s %s (%.1f MB)', k, f.name, f.stat().st_size / 1e6)
    return files


# ── 7. Site climatology (season-tracking charts, R6 style) ────────────────────
# Per FDRA, from the 2016–2025 daily FDRA values (FDOP stations, FDRA fuel model):
#   • ERC / BI / SFDI annual-percentile lookups (101 quantiles) — the GitHub site turns
#     live values into "annual percentile" with these
#   • per day-of-year max / avg of the annual percentiles (chart envelopes) and every
#     year's series (for analog years)
#   • live fuel moisture (herb, woody) avg / min by day of year
#   • temperature / RH by day of year when FEMS weather history is available
#   • fire-season end: first day after which ERC stays below the 70th percentile
#     (searched from July 1), its distribution across years → 25/50/75/90 % dates
# SFDI follows Jolly et al. 2019: p = ERC′ × BI′ (annual percentiles), SFDI = percentile
# of p in the same climatology; classes Low ≤60 < Moderate ≤80 < High ≤90 < Very High ≤97 < Severe.
SFDI_BREAKS = [60, 80, 90, 97]
SFDI_LABELS = ['Low', 'Moderate', 'High', 'Very High', 'Severe']
SEASON_END_PCT = 70
SEASON_SEARCH_FROM_DOY = 182   # July 1


def _pct_of(values: np.ndarray, sorted_clim: np.ndarray) -> np.ndarray:
    """Annual percentile (0–100) of each value within a sorted climatology."""
    v = np.asarray(values, dtype=float)
    out = np.full(v.shape, np.nan)
    ok = ~np.isnan(v)
    if len(sorted_clim):
        out[ok] = np.searchsorted(sorted_clim, v[ok], side='right') / len(sorted_clim) * 100
    return out


def _doy365(dates: pd.Series) -> np.ndarray:
    doy = dates.dt.dayofyear.to_numpy()
    leap = dates.dt.is_leap_year.to_numpy()
    return np.where(leap & (doy > 59), doy - 1, doy)


def season_end_doy(doy: np.ndarray, pct: np.ndarray, thresh=SEASON_END_PCT, start=SEASON_SEARCH_FROM_DOY):
    """First DOY ≥ start after which pct stays < thresh for the rest of the year (None if never)."""
    s = pd.Series(pct, index=doy).groupby(level=0).mean().reindex(range(1, 366))
    s = s.loc[start:]
    above = s[s >= thresh]
    if s.dropna().empty:
        return None
    if above.empty:
        return int(start)
    last = int(above.index.max())
    return last + 1 if last < 365 else None


def fdra_site_climo(daily_unit: pd.DataFrame, weather: pd.DataFrame | None = None) -> dict:
    """Climatology bundle for one FDRA (daily_unit: one unit's rows from unit_daily)."""
    d = daily_unit.sort_values('date').copy()
    d['doy'] = _doy365(d['date'])
    d['year'] = d['date'].dt.year
    q = np.linspace(0, 100, 101)
    out = {'years': sorted(d['year'].unique().tolist()), 'n_days': int(len(d))}
    clim = {}
    for k in ('erc', 'bi'):
        v = np.sort(d[k].dropna().to_numpy())
        clim[k] = v
        out[f'{k}_q'] = np.round(np.percentile(v, q), 2).tolist() if len(v) else []
        d[f'{k}_p'] = _pct_of(d[k], v)
    prod = d['erc_p'] * d['bi_p']
    clim['prod'] = np.sort(prod.dropna().to_numpy())
    out['sfdi_prod_q'] = np.round(np.percentile(clim['prod'], q), 1).tolist() if len(clim['prod']) else []
    d['sfdi'] = _pct_of(prod, clim['prod'])

    days = np.arange(1, 366)
    env = {}
    for k in ('erc_p', 'bi_p', 'sfdi'):
        g = d.groupby('doy')[k]
        env[k] = {'max': g.max().reindex(days).round(1).tolist(), 'avg': g.mean().reindex(days).round(1).tolist()}
    for k in ('erc', 'bi'):
        g = d.groupby('doy')[k]
        env[k] = {'max': g.max().reindex(days).round(1).tolist(), 'avg': g.mean().reindex(days).round(1).tolist()}
    for k in ('herb', 'woody', 'fm100', 'fm1000'):
        g = d.groupby('doy')[k]
        env[k] = {'min': g.min().reindex(days).round(1).tolist(), 'avg': g.mean().reindex(days).round(1).tolist()}
    out['envelope'] = env
    # every year's percentile series (analog years)
    out['years_series'] = {
        str(y): {k: g.groupby('doy')[k].mean().reindex(days).round(0).tolist()   # Feb 29 folded into Feb 28
                 for k in ('erc_p', 'bi_p', 'sfdi')}
        for y, g in d.groupby('year')}
    # season end
    ends = {str(y): season_end_doy(g['doy'].to_numpy(), g['erc_p'].to_numpy()) for y, g in d.groupby('year')}
    out['season_end_doy'] = ends
    ev = np.array([v for v in ends.values() if v is not None])
    out['season_end_quantiles'] = ({str(p): int(np.percentile(ev, p)) for p in (25, 50, 75, 90)} if len(ev) else {})
    # weather (optional)
    if weather is not None and len(weather):
        w = weather.copy()
        w['doy'] = _doy365(w['date'])
        for k in ('tmax', 'rhmin'):
            if k in w:
                g = w.groupby('doy')[k]
                env[k] = {'avg': g.mean().reindex(days).round(1).tolist(),
                          ('max' if k == 'tmax' else 'min'): (g.max() if k == 'tmax' else g.min()).reindex(days).round(1).tolist()}
    out['sfdi_breaks'] = SFDI_BREAKS
    out['sfdi_labels'] = SFDI_LABELS
    return out


def _clean(o):
    """NaN/inf → None, numpy scalars → Python, recursively (valid JSON for the site)."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    return o


def write_site_climo(daily: pd.DataFrame, fdra_attrs: pd.DataFrame, out_dir: Path,
                     weather_by_unit: dict | None = None) -> Path:
    """site_data/climo/<fdra_id>.json for every FDRA + site_data/fdras.json index."""
    cdir = out_dir / 'climo'
    cdir.mkdir(parents=True, exist_ok=True)
    idx = []
    f = daily[daily['unit_type'] == 'FDRA']
    for uid, g in f.groupby('unit_id'):
        w = (weather_by_unit or {}).get(uid)
        c = fdra_site_climo(g, w)
        safe = re.sub(r'[^A-Za-z0-9_-]+', '_', uid)
        (cdir / f'{safe}.json').write_text(json.dumps(_clean(c), separators=(',', ':'), allow_nan=False))
        row = {'fdra_id': uid, 'file': f'climo/{safe}.json', 'years': c['years'], 'n_days': c['n_days'],
               'season_end_quantiles': c['season_end_quantiles']}
        idx.append(row)
    (out_dir / 'fdras.json').write_text(json.dumps(idx, indent=1))
    log.info('site climatology: %d FDRAs → %s', len(idx), out_dir)
    return out_dir


# ── 8. FEMS weather history (daily Tmax / RHmin) — public, batched ──────────────
def download_weather(stations: pd.DataFrame, start_year: int, end_year: int, raw_dir: Path,
                     workers: int = 4):
    """Batched, cached FEMS wx daily summaries (TemperatureMax, RelativeHumidityMin)."""
    return _download(FEMS_WX_URL, 'wx', stations['stationId'], None, start_year, end_year, raw_dir, workers)


def load_weather_daily(stations: pd.DataFrame, start_year: int, end_year: int, raw_dir: Path) -> pd.DataFrame:
    """Daily max temperature and min RH per station (observed rows only)."""
    want = set(stations['stationId'].astype(int))
    frames = []
    for f in sorted(raw_dir.glob('wx_*.csv')):
        if f.stat().st_size < 50:
            continue
        df = pd.read_csv(f)
        df.columns = df.columns.str.strip()
        if 'TemperatureMax(F)' not in df.columns:
            continue
        df = df[df['ObservationType'].astype(str).str.upper() == 'O']
        frames.append(pd.DataFrame({
            'stationId': pd.to_numeric(df['StationId'], errors='coerce'),
            'date': pd.to_datetime(df['Date'], errors='coerce').dt.normalize(),
            'tmax': pd.to_numeric(df['TemperatureMax(F)'], errors='coerce'),
            'rhmin': pd.to_numeric(df['RelativeHumidityMin(%)'], errors='coerce')}))
    if not frames:
        return pd.DataFrame(columns=['stationId', 'date', 'tmax', 'rhmin'])
    w = pd.concat(frames, ignore_index=True).dropna(subset=['stationId', 'date'])
    w['stationId'] = w['stationId'].astype(int)
    w = w[w['stationId'].isin(want) & w['date'].dt.year.between(start_year, end_year)]
    return w.groupby(['stationId', 'date'], as_index=False)[['tmax', 'rhmin']].mean()


def unit_weather(wx: pd.DataFrame, membership: dict) -> dict:
    """{fdra_id: daily tmax/rhmin averaged over its stations}."""
    out = {}
    for uid, members in membership.items():
        sids = [m[0] if isinstance(m, tuple) else m for m in members]
        sub = wx[wx['stationId'].isin(sids)]
        if len(sub):
            out[uid] = sub.groupby('date')[['tmax', 'rhmin']].mean().reset_index()
    return out
