"""
build_fdop_data.py — data for the FDOP Workbench (docs/fdop.html).

Everything public and keyless, so it runs unattended in GitHub Actions:

  stations   FEMS NFDR daily summaries (observed), fuel models V W X Y Z, 2006 → today,
             for every RAWS that could go in an FDRA's SIG (FDOP stations from the 2026
             sheet + CA NFDRS RAWS inside or within 25 km of the FDRA)
  fires      FPA FOD 7th edition (Short 2026, FPA_FOD_20260615, 1992-2024, all sizes) for 2006-2024 +
             WFIGS incident locations (wildfires) for 2025 → today, assigned to forest FDRAs
  burned     CAL FIRE FRAP fire perimeters (all agencies) + WFIGS year-to-date perimeters
             → burned acres and % of each FDRA by year (vegetation-change check)
  scorecard  the yearly "are the FDOP indices still good?" delta for every FDRA, using the
             2026 sheet SIG / fuel model and the same rules as the Workbench page

    python site/build_fdop_data.py OUT [CACHE]

OUT is a checkout of the `fdop-data` branch (force-pushed, one commit, so it never grows).
"""
from __future__ import annotations

import gzip
import io
import json
import logging
import math
import os
import re
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'normals'))
import ca_normals as cn  # noqa: E402

log = logging.getLogger('fdop')
TZ = ZoneInfo('America/Los_Angeles')
START_YEAR = 2006
FMS = ['V', 'W', 'X', 'Y', 'Z']
IDX = {'erc': 'ERC', 'bi': 'BI', 'ic': 'IC', 'sc': 'SC', 'f100': '100HrFM', 'f1000': '1000HrFM'}
SCALE = {'erc': 1, 'bi': 1, 'ic': 1, 'sc': 1, 'f100': 10, 'f1000': 10}   # stored as ints (fm ×10)
BUFFER_M = 25000
MEMBERSHIP = ROOT / 'site' / 'fdra_station_membership_2026.csv'
POLYGONS = ROOT / 'docs' / 'data' / 'fdras.geojson'
FOD_URL = 'https://www.fs.usda.gov/rds/archive/products/RDS-2013-0009.7/RDS-2013-0009.7_Data_Format2_GDB.zip'
WFIGS = 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Incident_Locations/FeatureServer/0'
FRAP = 'https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/California_Historic_Fire_Perimeters/FeatureServer/0'
WFIGS_YTD = 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_YearToDate/FeatureServer/0'

# defaults shared with the Workbench (docs/assets/fdop.js) — keep in step
# Season, large-fire size and multi-fire day follow the R5 FDOP examples (Sierra South, BDF); calibration is the
# FFP 10-year minimum (here 15 years, all fires: FPA FOD 7th ed. through 2024, WFIGS after). All are editable per FDRA in the Workbench.
DEFAULTS = {'season': ['05-01', '11-30'], 'large_fire_ac': 10, 'mfd_n': 2, 'calib': [2011, 2025],
            'veg_yellow_pct': 10, 'veg_red_pct': 20, 'complete_min': 0.8}


def safe(uid: str) -> str:
    return re.sub(r'[^A-Za-z0-9_-]+', '_', uid)


def base_id(uid: str) -> str:
    return re.sub(r'\s*\((?:peak|non-peak)\)$', '', uid)   # seasons only — '(outside NF)' is part of the id


def arcgis_query(url, where, fields='*', geometry=True, out_sr=4326, offset_m=None, page=1000, extra=None):
    """All features (GeoJSON-like dicts) from an ArcGIS FeatureServer layer, paged."""
    feats, start = [], 0
    while True:
        p = {'where': where, 'outFields': fields, 'returnGeometry': str(geometry).lower(), 'outSR': out_sr,
             'f': 'geojson', 'resultOffset': start, 'resultRecordCount': page, 'orderByFields': 'OBJECTID'}
        if offset_m:
            p['maxAllowableOffset'] = offset_m
        if extra:
            p.update(extra)
        for a in range(4):
            try:
                r = requests.get(url + '/query', params=p, timeout=180)
                j = r.json()
                break
            except Exception:
                if a == 3:
                    raise
        if 'error' in j:
            raise RuntimeError(f'{url}: {j["error"]}')
        fs = j.get('features', [])
        feats += fs
        if len(fs) < page and not j.get('properties', {}).get('exceededTransferLimit'):
            break
        start += len(fs)
        if not fs:
            break
    return feats


# ── FDRAs and candidate stations ─────────────────────────────────────────────
def load_fdras():
    import geopandas as gpd
    g = gpd.read_file(POLYGONS).to_crs(3310)
    g['geometry'] = g.geometry.make_valid().buffer(0)
    mem = pd.read_csv(MEMBERSHIP).fillna('')
    mem['unit'] = np.where(mem['season'] != '', mem['fdra_id'] + ' (' + mem['season'] + ')', mem['fdra_id'])
    return g, mem


def candidate_stations(g, mem):
    """{unit: [stationId,...]} candidates + station table (id, name, lat, lon)."""
    import geopandas as gpd
    st = cn.load_ca_stations()[['stationId', 'StationName', 'Latitude', 'Longitude']]
    st = st.rename(columns={'StationName': 'name', 'Latitude': 'lat', 'Longitude': 'lon'})
    pts = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.lon, st.lat), crs=4326).to_crs(3310)
    cand, info = {}, {}
    for unit, grp in mem.groupby('unit'):
        poly = g.loc[g.fdra_id.str.upper() == base_id(unit).upper(), 'geometry']
        sheet = [int(s) for s in grp.stationId]
        near = []
        if len(poly):
            p = poly.iloc[0]
            d = pts.distance(p)
            near = pts.loc[d <= BUFFER_M].assign(dist_km=(d[d <= BUFFER_M] / 1000).round(1))
            for _, r in near.iterrows():
                info.setdefault(unit, {})[int(r.stationId)] = {'inside': bool(r.dist_km == 0), 'dist_km': float(r.dist_km)}
            near = near.stationId.astype(int).tolist()
        cand[unit] = sorted(set(sheet) | set(near))
        for s in sheet:
            info.setdefault(unit, {}).setdefault(s, {'inside': None, 'dist_km': None})['sheet'] = True
    return cand, info, st


# ── station history (2006 → today, 5 fuel models) ────────────────────────────
def download_station_history(ids, cache: Path, workers=4):
    today = datetime.now(TZ).date()
    cache.mkdir(parents=True, exist_ok=True)
    jobs = []
    for chunk in cn._batches(ids, 20):
        for y in range(START_YEAR, today.year + 1):
            f = cache / f'fdop_{y}_{cn._tag(chunk)}.csv'
            if y == today.year or not f.exists():          # current year always refreshed
                jobs.append((chunk, y, f))
    log.info('FEMS station history: %d batch-years to fetch', len(jobs))

    def one(job):
        chunk, y, f = job
        end = min(date(y, 12, 31), today).isoformat()
        txt = cn._fems_get(cn.FEMS_URL, chunk, f'{y}-01-01', end, FMS, dataset='observation')
        f.write_text(txt or '', encoding='utf-8')

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))


STATION_NAMES: dict = {}


def load_station_history(cache: Path) -> pd.DataFrame:
    frames = []
    for f in sorted(cache.glob('fdop_*.csv')):
        if f.stat().st_size < 50:
            continue
        d = pd.read_csv(f)
        d.columns = d.columns.str.strip()
        d = d[d['NFDRType'].astype(str).str.upper() == 'O']
        STATION_NAMES.update(dict(zip(d['StationId'].astype(int), d['StationName'].astype(str))))
        o = pd.DataFrame({'sid': d['StationId'].astype(int), 'fm': d['FuelModel'].astype(str).str.upper(),
                          'date': pd.to_datetime(d['ObservationTime']).dt.normalize()})
        for k, c in IDX.items():
            v = pd.to_numeric(d[c], errors='coerce')
            o[k] = v.where(v >= 0)
        frames.append(o)
    h = pd.concat(frames, ignore_index=True)
    return h.groupby(['sid', 'fm', 'date'], as_index=False).mean()


def write_station_files(h: pd.DataFrame, out: Path, names: dict):
    """stations/<sid>_<fm>.json.gz: {sid, fm, name, start, erc:[], bi:[], ...} one value per day."""
    sdir = out / 'stations'
    sdir.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(f'{START_YEAR}-01-01')
    end = h['date'].max()
    days = pd.date_range(start, end)
    meta = {}
    for (sid, fm), g in h.groupby(['sid', 'fm']):
        g = g.set_index('date').reindex(days)
        doc = {'sid': int(sid), 'fm': fm, 'name': names.get(int(sid), ''), 'start': start.strftime('%Y-%m-%d'), 'n': len(days)}
        for k in IDX:
            v = g[k] * SCALE[k]
            doc[k] = [None if pd.isna(x) else int(round(x)) for x in v]
        (sdir / f'{sid}_{fm}.json.gz').write_bytes(gzip.compress(json.dumps(doc, separators=(',', ':')).encode()))
        ok = g['erc'].notna()
        meta.setdefault(int(sid), {})[fm] = {'first': ok.idxmax().strftime('%Y-%m-%d') if ok.any() else None,
                                             'complete': round(float(ok.mean()), 3)}
    return meta, days[-1].strftime('%Y-%m-%d')


# ── fires ─────────────────────────────────────────────────────────────────────
def fod_fires(cache: Path) -> pd.DataFrame:
    import pyogrio
    z = cache / 'fod7.zip'
    if not z.exists():
        log.info('downloading FPA FOD 7th edition (~160 MB)')
        with requests.get(FOD_URL, stream=True, timeout=900) as r:
            r.raise_for_status()
            with open(z, 'wb') as f:
                for ch in r.iter_content(1 << 20):
                    f.write(ch)
    d = cache / 'fod7'
    if not d.exists():
        zipfile.ZipFile(z).extractall(d)
    gdb = next(p for p in d.rglob('*.gdb') if p.is_dir())
    lyr = next(l[0] for l in pyogrio.list_layers(gdb) if l[0].lower() == 'fires')
    df = pyogrio.read_dataframe(gdb, layer=lyr, read_geometry=False,
                                columns=['FOD_ID', 'FIRE_YEAR', 'DISCOVERY_DATE', 'FIRE_SIZE', 'NWCG_CAUSE_CLASSIFICATION',
                                         'NWCG_GENERAL_CAUSE', 'LATITUDE', 'LONGITUDE', 'NWCG_REPORTING_AGENCY', 'FIRE_NAME', 'STATE'])
    log.info('FPA FOD read: %d fires nationally', len(df))
    df = df[(df['STATE'].astype(str).str.strip() == 'CA') & (pd.to_numeric(df['FIRE_YEAR']) >= START_YEAR)]
    dd = pd.to_datetime(df['DISCOVERY_DATE'])
    if dd.dt.tz is not None:              # 7th edition stores dates as UTC midnight; keep the calendar date
        dd = dd.dt.tz_localize(None)
    out = pd.DataFrame({'date': dd.dt.normalize(), 'acres': pd.to_numeric(df['FIRE_SIZE']),
                        'cause': df['NWCG_CAUSE_CLASSIFICATION'].map({'Human': 'H', 'Natural': 'N'}).fillna('U'),
                        'lat': df['LATITUDE'], 'lon': df['LONGITUDE'], 'agency': df['NWCG_REPORTING_AGENCY'],
                        'name': df['FIRE_NAME'].fillna(''), 'src': 'FOD'})
    log.info('FPA FOD CA fires %d-%d: %d', START_YEAR, int(df.FIRE_YEAR.max()), len(out))
    return out, int(df.FIRE_YEAR.max())


def wfigs_fires(first_year: int) -> pd.DataFrame:
    rows = []
    this = datetime.now(TZ).year
    for y in range(first_year, this + 1):
        feats = arcgis_query(WFIGS, f"POOState='US-CA' AND IncidentTypeCategory='WF' AND FireDiscoveryDateTime >= DATE '{y}-01-01' "
                                    f"AND FireDiscoveryDateTime < DATE '{y + 1}-01-01'",
                             fields='UniqueFireIdentifier,FireDiscoveryDateTime,IncidentSize,FinalAcres,DiscoveryAcres,FireCause,'
                                    'POOProtectingAgency,IncidentName,IsCpxChild,CpxID,IrwinID', page=2000)
        # every fire counts: keep complex members, drop only the complex "parent" record (it duplicates them)
        parents = {str(f['properties'].get('CpxID')).upper() for f in feats if f['properties'].get('CpxID')}
        for f in feats:
            p, gm = f['properties'], f.get('geometry')
            if not gm or (str(p.get('IrwinID')).upper() in parents and p.get('IsCpxChild') not in (1, '1', True)):
                continue
            ac = next((p[k] for k in ('FinalAcres', 'IncidentSize', 'DiscoveryAcres') if p.get(k) not in (None, '')), 0)
            rows.append({'uid': p.get('UniqueFireIdentifier'), 'date': pd.to_datetime(p['FireDiscoveryDateTime'], unit='ms', utc=True)
                         .tz_convert(TZ).tz_localize(None).normalize(), 'acres': float(ac or 0),
                         'cause': {'Human': 'H', 'Natural': 'N'}.get(p.get('FireCause'), 'U'),
                         'lon': gm['coordinates'][0], 'lat': gm['coordinates'][1], 'agency': p.get('POOProtectingAgency'),
                         'name': p.get('IncidentName') or '', 'src': 'WFIGS'})
        log.info('WFIGS %d: %d CA wildfires', y, len(feats))
    w = pd.DataFrame(rows)
    return w.drop_duplicates('uid').drop(columns='uid') if len(w) else w


def assign_fires(fires: pd.DataFrame, g) -> dict:
    import geopandas as gpd
    pts = gpd.GeoDataFrame(fires, geometry=gpd.points_from_xy(fires.lon, fires.lat), crs=4326).to_crs(3310)
    j = gpd.sjoin(pts, g[['fdra_id', 'geometry']], predicate='within', how='inner')
    out = {}
    for fid, grp in j.groupby('fdra_id'):
        grp = grp.sort_values('date')
        out[fid] = [[d.strftime('%Y-%m-%d'), round(float(a), 1), c, s, n[:40]] for d, a, c, s, n in
                    zip(grp['date'], grp['acres'], grp['cause'], grp['src'], grp['name'])]
    return out


# ── burned area (vegetation change) ──────────────────────────────────────────
def burned_by_year(g) -> tuple[dict, int]:
    import geopandas as gpd
    from shapely.geometry import shape
    this = datetime.now(TZ).year
    # f=geojson always returns WGS84, so simplify in degrees (~30 m) and project afterwards
    feats = arcgis_query(FRAP, f'YEAR_ >= {START_YEAR}', fields='YEAR_,FIRE_NAME,GIS_ACRES', out_sr=4326, offset_m=0.0003)
    rows = [{'year': int(f['properties']['YEAR_']), 'name': f['properties'].get('FIRE_NAME'), 'geometry': shape(f['geometry'])}
            for f in feats if f.get('geometry')]
    frap_max = max(r['year'] for r in rows)
    if frap_max < this:
        try:
            yt = arcgis_query(WFIGS_YTD, "attr_POOState='US-CA'", fields='poly_IncidentName,attr_FireDiscoveryDateTime',
                              out_sr=4326, offset_m=0.0003)
            rows += [{'year': this, 'name': f['properties'].get('poly_IncidentName'), 'geometry': shape(f['geometry'])}
                     for f in yt if f.get('geometry')]
        except Exception as e:
            log.warning('WFIGS YTD perimeters: %s', e)
    p = gpd.GeoDataFrame(rows, crs=4326)
    p = p[p.geom_type.isin(['Polygon', 'MultiPolygon'])].to_crs(3310)
    p['geometry'] = p.geometry.buffer(0)
    p = p[~p.geometry.is_empty]
    out = {}
    for _, r in g.iterrows():
        area = r.geometry.area
        sub = p[p.intersects(r.geometry)]
        yrs = {}
        for y, gy in sub.groupby('year'):
            a = gy.union_all().intersection(r.geometry).area
            if a > 0:
                yrs[int(y)] = {'acres': round(a / 4046.86), 'pct': round(100 * a / area, 2),
                               'fires': sorted({str(n) for n in gy['name'] if n})[:12]}
        # unique area burned in trailing windows (overlapping fires counted once)
        trail = {}
        for y in range(START_YEAR + 4, this + 1):
            w = sub[(sub.year > y - 5) & (sub.year <= y)]
            if len(w):
                trail[y] = round(100 * w.union_all().intersection(r.geometry).area / area, 2)
        out[r.fdra_id] = {'fdra_acres': round(area / 4046.86), 'by_year': yrs, 'trailing5_pct': trail}
    log.info('burned area: FRAP %d-%d (+WFIGS YTD %s)', START_YEAR, frap_max, this if frap_max < this else '—')
    return out, frap_max


# ── statistics (mirrors docs/assets/fdop.js) ─────────────────────────────────
def logistic(x: np.ndarray, y: np.ndarray):
    """One-variable logistic regression by IRLS → (b0, b1, se1, p1, auc, mcfadden_r2)."""
    ok = ~np.isnan(x)
    x, y = x[ok], y[ok]
    if len(x) < 30 or y.sum() < 3 or y.sum() == len(y):
        return None
    mu, sd = x.mean(), x.std() or 1
    z = (x - mu) / sd
    b = np.array([math.log(y.mean() / (1 - y.mean())), 0.0])
    X = np.column_stack([np.ones_like(z), z])
    for _ in range(30):
        p = 1 / (1 + np.exp(-(X @ b)))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None])
        try:
            step = np.linalg.solve(H, X.T @ (y - p))
        except np.linalg.LinAlgError:
            return None
        b += step
        if np.abs(step).max() < 1e-8:
            break
    p = np.clip(1 / (1 + np.exp(-(X @ b))), 1e-12, 1 - 1e-12)
    cov = np.linalg.inv(X.T @ (X * (p * (1 - p))[:, None]))
    se = math.sqrt(cov[1, 1])
    zstat = b[1] / se
    pval = math.erfc(abs(zstat) / math.sqrt(2))
    ll = np.sum(y * np.log(p) + (1 - y) * np.log(1 - p))
    p0 = y.mean()
    ll0 = np.sum(y * math.log(p0) + (1 - y) * math.log(1 - p0))
    # AUC (Mann-Whitney)
    r = pd.Series(x).rank().to_numpy()
    n1 = y.sum()
    n0 = len(y) - n1
    auc = (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
    return {'b0': b[0] - b[1] * mu / sd, 'b1': b[1] / sd, 'p': pval, 'auc': round(float(auc), 3),
            'r2': round(float(1 - ll / ll0), 3), 'n': int(len(y)), 'events': int(n1)}


def sig_daily(hist: pd.DataFrame, members, fm_default, weights: dict | None = None):
    """SIG daily mean; with FDOP station weights a weighted mean over the stations that reported."""
    pairs = {(int(s), (f or fm_default)) for s, f in members}
    sub = hist[[(s, f) in pairs for s, f in zip(hist['sid'], hist['fm'])]]
    if sub.empty:
        return pd.DataFrame()
    if weights:
        w = sub['sid'].map(lambda x: weights.get(int(x), 1.0)).astype(float)
        X = sub[list(IDX)].astype(float)
        d = X.mul(w, axis=0).groupby(sub['date']).sum(min_count=1) / X.notna().mul(w, axis=0).groupby(sub['date']).sum().replace(0, np.nan)
    else:
        d = sub.groupby('date')[list(IDX)].mean()
    d['n_st'] = sub.groupby('date')['sid'].nunique()
    return d


def event_table(days: pd.DatetimeIndex, fires, large_ac, mfd_n):
    f = pd.DataFrame(fires, columns=['date', 'acres', 'cause', 'src', 'name']) if fires else \
        pd.DataFrame(columns=['date', 'acres', 'cause', 'src', 'name'])
    f['date'] = pd.to_datetime(f['date'])
    c = f.groupby('date').size().reindex(days, fill_value=0)
    lg = f[f['acres'] >= large_ac].groupby('date').size().reindex(days, fill_value=0)
    return pd.DataFrame({'fires': c, 'fd': (c > 0).astype(int), 'lfd': (lg > 0).astype(int), 'mfd': (c >= mfd_n).astype(int)})


def scorecard(unit, members, fm, hist, fires, burned, cfg=DEFAULTS, weights=None):
    """Yearly delta for one FDRA unit: rows per year with metrics + flags vs the calibration window."""
    d = sig_daily(hist, members, fm, weights)
    if d.empty:
        return None
    md = d.index.strftime('%m-%d')
    s0, s1 = cfg['season']
    d = d[(md >= s0) & (md <= s1)] if s0 <= s1 else d[(md >= s0) | (md <= s1)]
    ev = event_table(d.index, fires, cfg['large_fire_ac'], cfg['mfd_n'])
    d = d.join(ev)
    d['year'] = d.index.year
    c0, c1 = cfg['calib']
    cal = d[(d.year >= c0) & (d.year <= c1)]
    if cal['erc'].notna().sum() < 300:
        return None
    q90, q97 = np.nanpercentile(cal['erc'], 90), np.nanpercentile(cal['erc'], 97)
    bq90, bq97 = np.nanpercentile(cal['bi'], 90), np.nanpercentile(cal['bi'], 97)
    stats = {k: logistic(cal[k].to_numpy(float), cal['fd'].to_numpy(float)) for k in ('erc', 'bi', 'ic', 'sc')}
    stats_l = {k: logistic(cal[k].to_numpy(float), cal['lfd'].to_numpy(float)) for k in ('erc', 'bi')}
    per = cal.groupby('year').agg(fires=('fires', 'sum'), fd=('fd', 'sum'), lfd=('lfd', 'sum'))
    base = {'fires_mean': per.fires.mean(), 'fires_sd': per.fires.std(ddof=1) or 1, 'lfd_mean': per.lfd.mean(),
            'lfd_sd': per.lfd.std(ddof=1) or 1, 'top_share': None}
    lf_days = cal[cal.lfd == 1]
    base['top_share'] = float((lf_days['erc'] >= q90).mean()) if len(lf_days) else None
    med_doy = cal[cal.fd == 1].index.dayofyear
    base['fire_doy_median'] = float(np.median(med_doy)) if len(med_doy) else None
    rows = []
    burned_u = burned.get(base_id(unit), {}) if burned else {}
    for y, gy in d.groupby('year'):
        if gy['erc'].notna().sum() < 30:
            continue
        e = gy['erc']
        r = {'year': int(y), 'days': int(e.notna().sum()), 'complete': round(float(e.notna().mean()), 2),
             'erc_mean_pctl': round(float((np.searchsorted(np.sort(cal['erc'].dropna()), e.dropna()) / cal['erc'].notna().sum()).mean() * 100), 1),
             'days_ge90': int((e >= q90).sum()), 'days_ge97': int((e >= q97).sum()),
             'exp_ge90': round(0.10 * e.notna().sum(), 1), 'exp_ge97': round(0.03 * e.notna().sum(), 1),
             'fires': int(gy.fires.sum()), 'fd': int(gy.fd.sum()), 'lfd': int(gy.lfd.sum()), 'mfd': int(gy.mfd.sum())}
        r['fires_z'] = round((r['fires'] - base['fires_mean']) / base['fires_sd'], 2)
        r['lfd_z'] = round((r['lfd'] - base['lfd_mean']) / base['lfd_sd'], 2)
        fdays = gy[gy.fd == 1].index.dayofyear
        r['fire_doy_shift'] = round(float(np.median(fdays)) - base['fire_doy_median'], 0) if len(fdays) and base['fire_doy_median'] else None
        lfy = gy[gy.lfd == 1]
        r['lfd_hit90'] = round(float((lfy['erc'] >= q90).mean()), 2) if len(lfy) else None
        lr = logistic(gy['erc'].to_numpy(float), gy['fd'].to_numpy(float))
        r['auc_fd_erc'] = lr['auc'] if lr else None
        by = burned_u.get('by_year', {}).get(str(y)) or burned_u.get('by_year', {}).get(int(y))
        r['burned_pct'] = by['pct'] if by else 0.0
        t5 = burned_u.get('trailing5_pct', {})
        r['burned5_pct'] = t5.get(str(y), t5.get(int(y), 0.0))
        # flags: 0 green, 1 yellow, 2 red
        f = {}
        f['weather'] = 2 if r['days_ge97'] > 3 * max(r['exp_ge97'], 1) else 1 if r['days_ge90'] > 2 * max(r['exp_ge90'], 1) else 0
        f['fire'] = 2 if abs(r['fires_z']) >= 2 or abs(r['lfd_z']) >= 2 else 1 if abs(r['fires_z']) >= 1 or abs(r['lfd_z']) >= 1 else 0
        f['timing'] = 0 if r['fire_doy_shift'] is None else 2 if abs(r['fire_doy_shift']) >= 30 else 1 if abs(r['fire_doy_shift']) >= 15 else 0
        f['index'] = 0
        if r['auc_fd_erc'] is not None and stats['erc']:
            drop = stats['erc']['auc'] - r['auc_fd_erc']
            f['index'] = 2 if drop >= 0.10 else 1 if drop >= 0.05 else 0
        if r['lfd_hit90'] is not None and base['top_share'] is not None and r['lfd_hit90'] < base['top_share'] - 0.25:
            f['index'] = max(f['index'], 1)
        f['veg'] = 2 if r['burned5_pct'] >= cfg['veg_red_pct'] else 1 if r['burned5_pct'] >= cfg['veg_yellow_pct'] else 0
        f['station'] = 2 if r['complete'] < 0.6 else 1 if r['complete'] < cfg['complete_min'] else 0
        r['flags'] = f
        v = list(f.values())
        # 2 recalibrate, 1 review breakpoints, 0 current (same rule as the Workbench)
        r['verdict'] = 2 if (f['veg'] == 2 or v.count(2) >= 2) else 1 if (2 in v or v.count(1) >= 2) else 0
        rows.append(r)
    return {'unit': unit, 'fm': fm, 'stations': [int(s) for s, _ in members], 'config': cfg,
            'calib': {'years': [c0, c1], 'erc_q90': round(q90, 1), 'erc_q97': round(q97, 1), 'bi_q90': round(bq90, 1),
                      'bi_q97': round(bq97, 1), 'fires_per_year': round(base['fires_mean'], 1),
                      'lfd_per_year': round(base['lfd_mean'], 1), 'lfd_share_ge_erc90': base['top_share'],
                      'fd_stats': stats, 'lfd_stats': stats_l},
            'years': rows}


def main(out: Path, cache: Path):
    import geopandas as gpd  # noqa: F401
    out.mkdir(parents=True, exist_ok=True)
    g, mem = load_fdras()
    cand, cinfo, st = candidate_stations(g, mem)
    names = dict(zip(st.stationId.astype(int), st.name))
    ids = sorted({s for v in cand.values() for s in v})
    download_station_history(ids, cache / 'fems')
    hist = load_station_history(cache / 'fems')
    for k, v in STATION_NAMES.items():
        names.setdefault(k, v)
    meta, last_day = write_station_files(hist, out, names)

    fod, fod_max = fod_fires(cache)
    wf = wfigs_fires(fod_max + 1)
    fires = pd.concat([fod, wf], ignore_index=True).dropna(subset=['lat', 'lon', 'date'])
    by_fdra = assign_fires(fires, g)
    fdir = out / 'fires'
    fdir.mkdir(exist_ok=True)
    for fid, rows in by_fdra.items():
        (fdir / f'{safe(fid)}.json').write_text(json.dumps(rows, separators=(',', ':')))

    burned, frap_max = burned_by_year(g)
    (out / 'burned.json').write_text(json.dumps(burned, separators=(',', ':')))

    # station latitude/longitude for the Workbench station picker
    stn = {int(r.stationId): {'name': r['name'], 'lat': r.lat, 'lon': r.lon} for _, r in st.iterrows()}
    units = []
    cards = []
    for unit, grp in mem.groupby('unit'):
        members = list(zip(grp.stationId.astype(int), grp.fuel_model))
        fm = (grp.fuel_model.mode().iat[0] or 'Y')
        poly = g.loc[g.fdra_id.str.upper() == base_id(unit).upper()]
        props = poly.iloc[0].drop('geometry').to_dict() if len(poly) else {}
        props = {k: ('' if v is None or (isinstance(v, float) and math.isnan(v)) else v) for k, v in props.items()}
        cands = []
        for s in cand.get(unit, []):
            ci = cinfo.get(unit, {}).get(s, {})
            cands.append({'sid': s, 'name': stn.get(s, {}).get('name') or names.get(s, ''), 'lat': stn.get(s, {}).get('lat'),
                          'lon': stn.get(s, {}).get('lon'), 'inside': ci.get('inside'), 'dist_km': ci.get('dist_km'),
                          'sheet': bool(ci.get('sheet')), 'fms': meta.get(s, {})})
        units.append({'unit': unit, 'fdra_id': props.get('fdra_id', base_id(unit)), 'forest': props.get('forest'),
                      'fuel_model': fm, 'sheet_stations': [int(s) for s in grp.stationId],
                      'sl_dl_index': props.get('sl_dl_index'), 'standard_90_97': props.get('standard_90_97'),
                      'custom_thresholds': props.get('custom_thresholds'), 'acres': props.get('acres'),
                      'fires_file': f'fires/{safe(props.get("fdra_id", base_id(unit)))}.json', 'candidates': cands})
        wts = ({int(a): float(b) for a, b in zip(grp.stationId, grp.weight) if str(b).strip() not in ('', 'nan')}
               if 'weight' in grp else {})
        sc = scorecard(unit, members, fm, hist, by_fdra.get(props.get('fdra_id', base_id(unit)), []), burned, weights=wts or None)
        if sc:
            (out / 'scorecards').mkdir(exist_ok=True)
            (out / 'scorecards' / f'{safe(unit)}.json').write_text(json.dumps(cn._clean(sc), separators=(',', ':'), default=float))
            last = sc['years'][-1] if sc['years'] else {}
            prev = next((r for r in reversed(sc['years']) if r['year'] < datetime.now(TZ).year), None)
            cards.append({'unit': unit, 'year': prev and prev['year'], 'verdict': prev and prev['verdict'],
                          'flags': prev and prev['flags'], 'current_year_flags': last.get('flags')})
    now = datetime.now(TZ)
    (out / 'index.json').write_text(json.dumps(cn._clean({
        'generated': now.strftime('%Y-%m-%d %H:%M %Z'), 'history_start': f'{START_YEAR}-01-01', 'history_end': last_day,
        'fuel_models': FMS, 'scale': SCALE, 'defaults': DEFAULTS,
        'sources': {'fires': f'FPA FOD 7th ed. (RDS-2013-0009.7) {START_YEAR}-{fod_max}; WFIGS incident locations {fod_max + 1}-{now.year}',
                    'fod_last_year': fod_max,
                    'perimeters': f'CAL FIRE FRAP {START_YEAR}-{frap_max}' + (f'; WFIGS YTD {now.year}' if frap_max < now.year else ''),
                    'nfdrs': 'FEMS daily summaries (observed), NFDRS 2016'},
        'units': units, 'scorecards': cards,
        # every RAWS with history, so a planner can add any station to an FDRA's SIG in the Workbench
        'stations': [{'sid': int(k), 'name': names.get(int(k), ''), 'lat': stn.get(int(k), {}).get('lat'),
                      'lon': stn.get(int(k), {}).get('lon'), 'fms': v} for k, v in sorted(meta.items())]}),
        separators=(',', ':'), default=float, allow_nan=False))
    log.info('FDOP data: %d units, %d stations × fuel models, %d FDRAs with fires', len(units),
             sum(len(v) for v in meta.values()), len(by_fdra))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
    main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'fdop_cache')
