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
  2. FDRA join ← point-in-polygon against an FDRA file you provide
                 (GeoJSON / shapefile / zipped shapefile; any CRS with a .prj)
  3. download  ← FEMS download-nfdr-daily-summary, one file per station-year,
                 cached so re-runs only fetch what's missing
  4. aggregate ← observed (NFDRType=O) daily values → PSA / FDRA daily means
                 (same rule as the dashboard: average reporting stations)
  5. normals   ← annual percentiles + day-of-year normals per unit & index
  6. outputs   ← CSVs ready to add to ArcGIS Online as hosted tables

Used by CA_Normals_2016_2025.ipynb — run the notebook, not this file.
"""

from __future__ import annotations

import io
import json
import logging
import math
import time
import zipfile
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


# ── 2. FDRA polygons + station join ───────────────────────────────────────────
def load_fdra_polygons(path: str | Path, name_fields: list[str]):
    """Return list of (fdra_id, attrs, shapely_geometry_in_wgs84).

    Accepts .geojson/.json (WGS84), .shp, or a .zip holding a shapefile.
    Shapefiles are reprojected to WGS84 from their .prj (e.g. CA Teale Albers).
    `name_fields` builds the FDRA id, e.g. ['UNIT', 'FDRA'] → 'BEU-2'.
    """
    from shapely.geometry import shape
    from shapely.ops import transform
    path = Path(path)
    recs = []
    if path.suffix.lower() in ('.geojson', '.json'):
        gj = json.loads(path.read_text(encoding='utf-8'))
        for f in gj['features']:
            recs.append((f['properties'], shape(f['geometry'])))
        to_wgs = None
    else:
        import shapefile  # pyshp
        if path.suffix.lower() == '.zip':
            z = zipfile.ZipFile(path)
            stem = next(n[:-4] for n in z.namelist() if n.lower().endswith('.shp'))
            rd = shapefile.Reader(shp=io.BytesIO(z.read(stem + '.shp')),
                                  shx=io.BytesIO(z.read(stem + '.shx')),
                                  dbf=io.BytesIO(z.read(stem + '.dbf')))
            prj = z.read(stem + '.prj').decode() if stem + '.prj' in z.namelist() else None
        else:
            rd = shapefile.Reader(str(path))
            p = path.with_suffix('.prj')
            prj = p.read_text() if p.exists() else None
        fields = [f[0] for f in rd.fields[1:]]
        for sr in rd.shapeRecords():
            recs.append((dict(zip(fields, sr.record)), shape(sr.shape.__geo_interface__)))
        to_wgs = None
        if prj:
            from pyproj import CRS, Transformer
            crs = CRS.from_wkt(prj)
            if crs.to_epsg() != 4326:
                tr = Transformer.from_crs(crs, 4326, always_xy=True)
                to_wgs = tr.transform
    out = []
    for attrs, geom in recs:
        if to_wgs:
            geom = transform(to_wgs, geom)
        fid = '-'.join(str(attrs.get(k, '')).strip() for k in name_fields)
        out.append((fid, attrs, geom.buffer(0) if not geom.is_valid else geom))
    log.info('FDRA polygons: %d from %s', len(out), path.name)
    return out


def load_fdra_from_agol(item_id: str, name_fields: list[str], gis=None):
    """Read FDRA polygons straight from an AGOL item (e.g. FDRA_CA) in WGS84.

    Signs in through ArcGIS Pro on this PC (GIS('pro')) unless a GIS is
    passed in, so secured services shared to your NIFC account work.
    """
    from arcgis.gis import GIS
    from shapely.geometry import Polygon, MultiPolygon
    gis = gis or GIS('pro')
    item = gis.content.get(item_id)
    lyr = item.layers[0]
    fs = lyr.query(where='1=1', out_fields='*', out_sr=4326, return_geometry=True)
    out = []
    for f in fs.features:
        rings = f.geometry.get('rings', [])
        polys = [Polygon(r) for r in rings if len(r) >= 4]
        geom = MultiPolygon(polys).buffer(0) if len(polys) > 1 else (polys[0].buffer(0) if polys else None)
        if geom is None:
            continue
        attrs = f.attributes
        fid = '-'.join(str(attrs.get(k, '')).strip() for k in name_fields)
        out.append((fid, attrs, geom))
    log.info('FDRA polygons: %d from AGOL item %s (%s)', len(out), item_id, item.title)
    return out


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


def assign_fdras(stations: pd.DataFrame, fdras) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Point-in-polygon. Returns (stations with 'FDRA' col, fdra table).

    FDRAs that contain no station get the nearest station (flagged
    nearest_only=1) so every FDRA still has normals.
    """
    from shapely.geometry import Point
    from shapely.strtree import STRtree
    geoms = [g for _, _, g in fdras]
    tree = STRtree(geoms)
    pts = [Point(lon, lat) for lon, lat in zip(stations['Longitude'], stations['Latitude'])]
    st_fdra = []
    for p in pts:
        hit = None
        for i in tree.query(p):
            if geoms[int(i)].contains(p):
                hit = fdras[int(i)][0]
                break
        st_fdra.append(hit)
    stations = stations.assign(FDRA=st_fdra)

    rows = []
    for fid, attrs, g in fdras:
        sids = stations.loc[stations['FDRA'] == fid, 'stationId'].tolist()
        nearest = 0
        if not sids:
            c = g.representative_point()
            d = [(c.distance(p), s) for p, s in zip(pts, stations['stationId'])]
            sids = [min(d)[1]]
            nearest = 1
        rows.append({'fdra_id': fid, 'stations': sids, 'n_stations': len(sids), 'nearest_only': nearest,
                     **{k: v for k, v in attrs.items() if isinstance(v, (str, int, float))}})
    fdra_tbl = pd.DataFrame(rows)
    log.info('FDRA join: %d stations inside an FDRA, %d FDRAs use nearest station',
             stations['FDRA'].notna().sum(), int(fdra_tbl['nearest_only'].sum()))
    return stations, fdra_tbl


# ── 3. FEMS download (cached) ─────────────────────────────────────────────────
def _fems_get(sid, fm, start, end, key, user, retries=4):
    params = dict(dataset='all', startDate=start, endDate=end, dataFormat='csv',
                  stationIds=sid, fuelModels=fm)
    headers = {'x-api-key': key, 'x-user-email': user, 'Accept': 'text/csv'}
    for a in range(1, retries + 1):
        try:
            r = requests.get(FEMS_URL, params=params, headers=headers, timeout=120)
            if r.status_code == 404:
                return ''
            r.raise_for_status()
            return r.text
        except Exception as e:
            if a == retries:
                raise
            time.sleep(3 * a)


def download_history(stations: pd.DataFrame, start_year: int, end_year: int, raw_dir: Path,
                     key: str, user: str, workers: int = 8):
    """One CSV per station × fuel model × year in raw_dir; existing files are skipped.

    `stations` needs columns stationId and FuelModel; the same station can appear
    with several fuel models (e.g. Y for its PSA, X for an FDRA).
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    pairs = stations[['stationId', 'FuelModel']].drop_duplicates()
    for sid, fm in zip(pairs['stationId'], pairs['FuelModel']):
        for y in range(start_year, end_year + 1):
            f = raw_dir / f'{sid}_{fm}_{y}.csv'
            if not f.exists():
                jobs.append((sid, fm, y, f))
    log.info('FEMS: %d station-years to download (%d cached)',
             len(jobs), len(pairs) * (end_year - start_year + 1) - len(jobs))
    failed = []

    def one(job):
        sid, fm, y, f = job
        txt = _fems_get(sid, fm, f'{y}-01-01', f'{y}-12-31', key, user)
        f.write_text(txt or '', encoding='utf-8')
        return job

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(one, j): j for j in jobs}
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception as e:
                failed.append((futs[fut][0], futs[fut][2], str(e)[:120]))
            done += 1
            if done % 100 == 0:
                log.info('  %d / %d', done, len(jobs))
    if failed:
        log.warning('%d station-years failed (re-run to retry): %s', len(failed), failed[:5])
    return failed


def load_history(stations: pd.DataFrame, start_year: int, end_year: int, raw_dir: Path) -> pd.DataFrame:
    """Observed daily values: columns stationId, fm, date, <indices>."""
    frames = []
    pairs = stations[['stationId', 'FuelModel']].drop_duplicates()
    for sid, fm in zip(pairs['stationId'], pairs['FuelModel']):
        for y in range(start_year, end_year + 1):
            f = raw_dir / f'{sid}_{fm}_{y}.csv'
            if not f.exists() or f.stat().st_size < 50:
                continue
            df = pd.read_csv(f)
            df.columns = df.columns.str.strip()
            if 'ObservationTime' not in df.columns:
                continue
            if 'NFDRType' in df.columns:
                df = df[df['NFDRType'].astype(str).str.upper() == 'O']
            out = pd.DataFrame({'stationId': sid, 'fm': fm,
                                'date': pd.to_datetime(df['ObservationTime'], errors='coerce').dt.normalize()})
            for k, col in FIELD_COLS.items():
                out[k] = pd.to_numeric(df[col], errors='coerce') if col in df.columns else np.nan
            frames.append(out.dropna(subset=['date']))
    hist = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=['stationId', 'fm', 'date', *INDICES])
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
