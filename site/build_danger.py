"""California + Hawaii fire danger maps: station data for docs/wx/danger.html.

A statewide (ONCC + OSCC) and Hawaii version of the ONCC "PSA Fire Danger Maps", same method and classes:
  BI, ERC, IC, SC   percentile of the day's value within the station's own 2005-2024 record (all days of the year)
                    → classes 0-60 / 60-80 / 80-90 / 90-97 / 97+
  SFDI              Severe Fire Danger Index (Jolly et al. 2019): ERC percentile × BI percentile, ranked against the
                    station's own record of that product → Low / Moderate / High / Very High / Severe
  100-hr, 1000-hr   fuel moisture value (%), 2% classes;   KBDI   value, 100-point classes
Day 0 is the latest observed day (FEMS), days 1-7 the FEMS forecast. Fuel model Y, public FEMS downloads, no keys.
The page interpolates the station values into the map surface, so only station values are published here.

  python site/build_danger.py climo   OUT CACHE   per-station climatology (first run, or yearly) → CACHE/danger_climo.npz
  python site/build_danger.py current OUT CACHE   today's data → OUT/danger.json, OUT/danger_psa.geojson
"""
from __future__ import annotations

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'normals'))
import ca_normals as cn            # noqa: E402  (FEMS download helpers)

log = logging.getLogger('danger')
TZ = ZoneInfo('America/Los_Angeles')
CLIMO = (2005, 2024)
FM = 'Y'
RAWS = 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/PublicView_RAWS/FeatureServer/1/query'
PSA = f'{cn.CA_NFDRS_URL}/1/query'            # CA PSAs incl. Hawaii HI01-HI05 (the national PSA layer has no Hawaii PSAs)
CA_BOX = (-125.2, 32.0, -113.6, 42.6)          # California plus the stations just over the line (edges of the surface)
PCT = ['erc', 'bi', 'ic', 'sc']               # ranked against the station's record
RAW = ['fm100', 'fm1000', 'kbdi']              # mapped as values
QS = np.concatenate([np.arange(0, 95, 0.5), np.arange(95, 100.01, 0.1)])   # stored quantile levels (fine at the top)
DAYS = 8


def stations() -> pd.DataFrame:
    """Active RAWS in the California box (CA plus neighbours near the line) and Hawaii."""
    rows = []
    for where, box in (("Status='A'", CA_BOX), ("State='HI' AND Status='A'", None)):
        p = dict(where=where, outFields='NWSID,StationName,State,Latitude,Longitude', returnGeometry='false',
                 resultRecordCount=4000, f='json')
        if box:
            p.update(geometry=','.join(map(str, box)), geometryType='esriGeometryEnvelope', inSR=4326, spatialRel='esriSpatialRelIntersects')
        for f in requests.get(RAWS, params=p, timeout=90).json()['features']:
            a = f['attributes']
            try:
                rows.append({'stationId': int(str(a['NWSID']).strip()), 'name': str(a['StationName']).strip().title(),
                             'state': a['State'], 'lat': float(a['Latitude']), 'lon': float(a['Longitude'])})
            except (TypeError, ValueError):
                continue
    df = pd.DataFrame(rows).drop_duplicates('stationId')
    df['region'] = np.where(df['lat'] < 25, 'HI', 'CA')
    log.info('stations: %d (%s)', len(df), df.groupby('region').size().to_dict())
    return df.reset_index(drop=True)


def _read(txt: str, observed_only: bool) -> pd.DataFrame:
    if not txt or len(txt) < 50:
        return pd.DataFrame()
    import io
    d = pd.read_csv(io.StringIO(txt))
    d.columns = d.columns.str.strip()
    if 'ObservationTime' not in d.columns:
        return pd.DataFrame()
    typ = d['NFDRType'].astype(str).str.upper()
    d = d[(typ == 'O') if observed_only else typ.isin(['O', 'F'])]
    out = pd.DataFrame({'stationId': pd.to_numeric(d['StationId'], errors='coerce'),
                        'date': pd.to_datetime(d['ObservationTime'], errors='coerce').dt.normalize(),
                        'type': d['NFDRType'].astype(str).str.upper().values})
    for k in PCT + RAW:
        c = cn.FIELD_COLS[k]
        out[k] = pd.to_numeric(d[c], errors='coerce').values if c in d.columns else np.nan
    out = out.dropna(subset=['stationId', 'date'])
    out['stationId'] = out['stationId'].astype(int)
    for k in PCT + RAW:
        out.loc[out[k] < 0, k] = np.nan
    return out


def _pct(v, sorted_clim):
    """Percentile (0-100) of value(s) v in a sorted climatology (mid-rank for ties)."""
    if sorted_clim is None or len(sorted_clim) < 30:
        return np.full(np.shape(v), np.nan)
    v = np.asarray(v, dtype=float)
    lo = np.searchsorted(sorted_clim, v, 'left')
    hi = np.searchsorted(sorted_clim, v, 'right')
    p = 100.0 * (lo + hi) / 2 / len(sorted_clim)
    return np.where(np.isnan(v), np.nan, p)


def build_climo(out: Path, cache: Path):
    st = stations()
    raw = cache / 'danger_raw'
    cn._download(cn.FEMS_URL, 'nfdrY', st['stationId'].tolist(), [FM], CLIMO[0], CLIMO[1], raw, workers=6)
    frames = [_read(f.read_text(encoding='utf-8', errors='ignore'), True) for f in sorted(raw.glob('nfdrY_*.csv')) if f.stat().st_size >= 50]
    h = pd.concat([f for f in frames if len(f)], ignore_index=True)
    h = h[h['date'].dt.year.between(*CLIMO)].groupby(['stationId', 'date'], as_index=False)[PCT].mean()
    keep = {}
    for sid, g in h.groupby('stationId'):
        rec = {k: np.sort(g[k].dropna().to_numpy()) for k in PCT}
        if min(len(rec['erc']), len(rec['bi'])) < 365:          # at least a year of record
            continue
        e, b = _pct(g['erc'].to_numpy(), rec['erc']), _pct(g['bi'].to_numpy(), rec['bi'])
        prod = e * b
        rec['sfdi'] = np.sort(prod[~np.isnan(prod)])
        keep[sid] = rec
    # store compact quantiles, not every day
    arr = {f'{sid}_{k}': np.nanpercentile(v, QS).astype('float32') for sid, rec in keep.items() for k, v in rec.items() if len(v) >= 30}
    np.savez_compressed(cache / 'danger_climo.npz', **arr)
    (out / 'danger_climo.json').write_text(json.dumps({'years': CLIMO, 'fuel_model': FM, 'stations': len(keep),
                                                       'built': datetime.now(TZ).strftime('%Y-%m-%d %H:%M %Z')}))
    log.info('climatology: %d stations with a usable record', len(keep))


def _q_pct(v, q):
    """Percentile of v from stored quantiles q (levels QS)."""
    if q is None or np.isnan(v):
        return None
    return float(np.interp(v, q, QS, left=0.0, right=100.0)) if q[-1] > q[0] else 50.0


def psa_geojson(out: Path):
    p = dict(where='1=1', outFields='PSANationalCode,PSAName,GACCUnitID', outSR=4326, maxAllowableOffset=0.003, f='geojson')
    gj = requests.get(PSA, params=p, timeout=120).json()

    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 4), round(c[1], 4)]
    for f in gj['features']:
        f['geometry']['coordinates'] = rnd(f['geometry']['coordinates'])
        pr = f['properties']
        pr['PSANAME'] = pr.pop('PSAName', '')
        pr['region'] = 'HI' if str(pr.get('GACCUnitID')) == 'ONCC_HI' or str(pr.get('PSANationalCode') or '').startswith('HI') else 'CA'
    (out / 'danger_psa.geojson').write_text(json.dumps(gj, separators=(',', ':')))
    log.info('PSA polygons: %d', len(gj['features']))


def build_current(out: Path, cache: Path):
    st = stations()
    z = np.load(cache / 'danger_climo.npz')
    clim = {k: z[k] for k in z.files}
    today = datetime.now(TZ).date()
    start, end = (today - timedelta(days=4)).isoformat(), (today + timedelta(days=9)).isoformat()

    def one(chunk):
        return _read(cn._fems_get(cn.FEMS_URL, chunk, start, end, [FM], dataset='all'), False)
    with ThreadPoolExecutor(max_workers=6) as pool:
        frames = list(pool.map(one, cn._batches(st['stationId'], 20)))
    cur = pd.concat([f for f in frames if len(f)], ignore_index=True)
    cur['o'] = (cur['type'] == 'O').astype(int)          # an observation beats a forecast for the same day
    cur = cur.sort_values('o').groupby(['stationId', 'date'], as_index=False).last()
    obs = cur[cur['o'] == 1]
    day0 = obs['date'].value_counts().loc[lambda s: s >= 0.3 * s.max()].index.max()   # latest well-reported observed day
    dates = [day0 + pd.Timedelta(days=i) for i in range(DAYS)]
    st = st[st['stationId'].isin(cur['stationId'])].reset_index(drop=True)
    idx = {s: i for i, s in enumerate(st['stationId'])}
    data = []
    for i, d in enumerate(dates):
        day = cur[cur['date'] == d].set_index('stationId')
        vals = {k: [None] * len(st) for k in ['erc', 'bi', 'ic', 'sc', 'sfdi', 'erc_v', 'bi_v', 'ic_v', 'sc_v'] + RAW}
        for sid, r in day.iterrows():
            j = idx.get(sid)
            if j is None:
                continue
            for k in PCT:
                if not np.isnan(r[k]):
                    vals[k + '_v'][j] = round(float(r[k]), 1)
                    p = _q_pct(r[k], clim.get(f'{sid}_{k}'))
                    vals[k][j] = None if p is None else round(p, 1)
            if vals['erc'][j] is not None and vals['bi'][j] is not None:
                p = _q_pct(vals['erc'][j] * vals['bi'][j], clim.get(f'{sid}_sfdi'))
                vals['sfdi'][j] = None if p is None else round(p, 1)
            for k in RAW:
                if not np.isnan(r[k]):
                    vals[k][j] = round(float(r[k]), 1 if k != 'kbdi' else 0)
        data.append({'day': i, 'date': d.strftime('%Y-%m-%d'), 'observed': bool(i == 0), **vals})
    doc = {'generated': datetime.now(TZ).strftime('%Y-%m-%d %H:%M %Z'), 'issued': today.isoformat(), 'climo': CLIMO,
           'fuel_model': FM, 'stations': st[['stationId', 'name', 'lat', 'lon', 'region', 'state']].values.tolist(), 'days': data}
    (out / 'danger.json').write_text(json.dumps(doc, separators=(',', ':')))
    n0 = sum(v is not None for v in data[0]['bi'])
    log.info('danger.json: %d stations, day 0 %s (%d with BI percentile), to %s', len(st), dates[0].date(), n0, dates[-1].date())
    psa_geojson(out)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    mode, out, cache = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    (build_climo if mode == 'climo' else build_current)(out, cache)
