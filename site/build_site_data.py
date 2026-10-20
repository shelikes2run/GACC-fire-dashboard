"""
build_site_data.py — data for the FDRA season-tracking site (docs/).

Two jobs, both keyless (public FEMS climatology downloads, batches of 20 stations):

  python site/build_site_data.py normals OUT   # 2016-2025 climatology per FDRA (slow, run rarely)
  python site/build_site_data.py current OUT   # this year's observed + forecast, PAL, index (daily)

OUT is a checkout of the `site-data` branch. The site reads it from
https://raw.githubusercontent.com/<repo>/site-data/...

  OUT/normals/climo/<unit>.json   ERC/BI/SFDI lookups, max/avg envelopes, every year's series,
                                  season-end dates, LFM / 100-hr / 1000-hr / Tmax / RHmin envelopes
  OUT/current/<unit>.json         this year by day: ERC, BI, ERC %, BI %, SFDI, herb, woody,
                                  100-hr, 1000-hr, Tmax, RHmin, O/F; station table; PAL lines
  OUT/fdras.json                  index for the map: one row per FDRA polygon with today's values
"""
from __future__ import annotations

import io
import json
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'normals'))
import ca_normals as cn  # noqa: E402

log = logging.getLogger('site')
MEMBERSHIP = ROOT / 'site' / 'fdra_station_membership_2026.csv'
POLYGONS = ROOT / 'docs' / 'data' / 'fdras.geojson'
PAL_RAW = 'https://raw.githubusercontent.com/shelikes2run/GACC-fire-dashboard/pal-data/'
NORMAL_YEARS = (2016, 2025)
TZ = ZoneInfo('America/Los_Angeles')
SEASONS = {'peak': ((5, 1), (11, 15))}            # ENF-335 peak season May 1 – Nov 15
FMS = ['V', 'W', 'X', 'Y', 'Z']                   # NFDRS 2016 fuel models offered on the charts


def all_fm(mem: dict):
    """Membership with every fuel model: {(unit, fm): [(stationId, fm), ...]} and the
    unit's own (FDOP) fuel model. Same stations, each fuel model averaged on its own."""
    out, own = {}, {}
    for uid, members in mem.items():
        own[uid] = members[0][1] if members else 'Y'
        sids = sorted({s for s, _ in members})
        for fm in FMS:
            out[(uid, fm)] = members if fm == own[uid] else [(s, fm) for s in sids]
    return out, own


def fm_name(uid: str, fm: str, own: str) -> str:
    """File stem: the FDOP fuel model keeps the plain unit name; others get _<FM>."""
    return safe(uid) if fm == own else f'{safe(uid)}__{fm}'


def safe(uid: str) -> str:
    return re.sub(r'[^A-Za-z0-9_-]+', '_', uid)


def base_id(uid: str) -> str:
    return re.sub(r'\s*\((?:peak|non-peak)\)$', '', uid)   # seasons only — '(outside NF)' is part of the id


# ── normals ───────────────────────────────────────────────────────────────────
def fast_unit_daily(hist: pd.DataFrame, named: dict) -> pd.DataFrame:
    """cn.unit_daily for ~1,000 units: split history by fuel model once."""
    by_fm = {fm: g for fm, g in hist.groupby('fm')}
    parts = []
    for uid, members in named.items():
        pieces = []
        for fm in {f for _, f in members}:
            g = by_fm.get(fm)
            if g is not None:
                pieces.append(g[g['stationId'].isin({sid for sid, f in members if f == fm})])
        sub = pd.concat(pieces) if pieces else pd.DataFrame()
        if sub.empty:
            continue
        d = sub.groupby('date')[cn.INDICES].mean()
        d['n_reporting'] = sub.groupby('date')['stationId'].nunique()
        d = d.reset_index()
        d.insert(0, 'unit_id', uid)
        d.insert(0, 'unit_type', 'FDRA')
        parts.append(d)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def build_normals(out: Path, cache: Path):
    mem, pairs = cn.load_fdra_membership(MEMBERSHIP)
    allm, own = all_fm(mem)
    y0, y1 = NORMAL_YEARS
    sids = sorted(pairs['stationId'].astype(int).unique())
    pairs = pd.DataFrame([(s, fm) for s in sids for fm in FMS], columns=['stationId', 'FuelModel'])
    cn.download_history(pairs, y0, y1, cache)
    hist = cn.load_history(pairs, y0, y1, cache)
    named = {fm_name(u, fm, own[u]): m for (u, fm), m in allm.items()}
    daily = fast_unit_daily(hist, named)
    wx_st = pairs[['stationId']].drop_duplicates()
    cn.download_weather(wx_st, y0, y1, cache)
    wx = cn.load_weather_daily(wx_st, y0, y1, cache)
    wx_by_unit = cn.unit_weather(wx, named) if len(wx) else None
    cn.write_site_climo(daily, None, out / 'normals', wx_by_unit)
    # extra envelopes the site charts use (100-hr / 1000-hr already in envelope)
    log.info('normals written for %d units', daily['unit_id'].nunique())


# ── current year ──────────────────────────────────────────────────────────────
def _csv(url, ids, start, end, fms=None):
    txt = cn._fems_get(url, ids, start, end, fms, dataset='all')
    if not txt or len(txt) < 50:
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(txt))
    df.columns = df.columns.str.strip()
    return df


def fetch_current(pairs: pd.DataFrame, start: str, end: str):
    fms = sorted(pairs['FuelModel'].unique())
    nf, wx = [], []
    for chunk in cn._batches(pairs['stationId'], 20):
        nf.append(_csv(cn.FEMS_URL, chunk, start, end, fms))
        wx.append(_csv(cn.FEMS_WX_URL, chunk, start, end))
    nf = pd.concat([d for d in nf if len(d)], ignore_index=True)
    wx = pd.concat([d for d in wx if len(d)], ignore_index=True)

    n = pd.DataFrame({'stationId': nf['StationId'].astype(int), 'name': nf['StationName'],
                      'fm': nf['FuelModel'].astype(str).str.upper(),
                      'date': pd.to_datetime(nf['ObservationTime']).dt.normalize(),
                      'type': nf['NFDRType'].fillna('').astype(str).str.upper()})
    for k, c in cn.FIELD_COLS.items():
        n[k] = pd.to_numeric(nf[c], errors='coerce')
        n.loc[n[k] < 0, k] = np.nan
    n = n[n['type'].isin(['O', 'F'])]
    w = pd.DataFrame({'stationId': wx['StationId'].astype(int),
                      'date': pd.to_datetime(wx['Date']).dt.normalize(),
                      'type': wx['ObservationType'].fillna('').astype(str).str.upper(),
                      'tmax': pd.to_numeric(wx['TemperatureMax(F)'], errors='coerce'),
                      'rhmin': pd.to_numeric(wx['RelativeHumidityMin(%)'], errors='coerce')})
    w = w[w['type'].isin(['O', 'F'])]
    return n, w


def _pick(df: pd.DataFrame, cols):
    """Per date: mean of observed rows if any, else mean of forecast rows."""
    g = df.groupby(['date', 'type'])[cols].mean().reset_index()
    g['rank'] = (g['type'] == 'F').astype(int)
    g = g.sort_values(['date', 'rank']).drop_duplicates('date').drop(columns='rank')
    return g.set_index('date')


def _pct(v, qs):
    if not qs:
        return np.full(len(v), np.nan)
    q = np.asarray(qs, float)
    v = np.asarray(v, float)
    out = np.interp(v, q, np.linspace(0, 100, len(q)))
    out[np.isnan(v)] = np.nan
    return out


def sfdi_class(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    for b, lab in zip(cn.SFDI_BREAKS, cn.SFDI_LABELS):
        if v <= b:
            return lab
    return cn.SFDI_LABELS[-1]


def pal_by_polygon(polys):
    """{fdra_id: [{name, dates, pal, type}]} from the PAL feed (pal-data branch)."""
    from shapely.geometry import Point, shape
    try:
        gj = requests.get(PAL_RAW + 'pal_stations.geojson', timeout=60).json()
        hist = pd.read_csv(io.StringIO(requests.get(PAL_RAW + 'pal_history.csv', timeout=60).text))
    except Exception as e:
        log.warning('PAL feed unavailable: %s', e)
        return {}
    shapes = [(f['properties']['fdra_id'], shape(f['geometry'])) for f in polys['features']]
    out = {}
    for f in gj['features']:
        p = f['properties']
        pt = Point(*f['geometry']['coordinates'])
        hit = next((fid for fid, s in shapes if s.contains(pt)), None)
        if not hit:
            continue
        h = hist[hist['station'] == p['name']].sort_values('date')
        series = dict(zip(h['date'], zip(h['pal'], ['O'] * len(h))))
        if p.get('fc_dates'):
            for d, v, t in zip(p['fc_dates'].split(','), p['fc_pal'].split(','), p['fc_type'].split(',')):
                if v in cn_pal_order and (d not in series or t == 'O'):
                    series[d] = (v, t)
        ds = sorted(series)
        out.setdefault(hit, []).append({'name': p['name'], 'forest_pal_station': p.get('forest_pal_station', 0),
                                        'today_1400': p.get('pal'), 'dates': ds,
                                        'pal': [series[d][0] for d in ds], 'type': [series[d][1] for d in ds]})
    for v in out.values():
        v.sort(key=lambda s: (-s['forest_pal_station'], s['name']))
    return out


cn_pal_order = ['A', 'B', 'C', 'D', 'Ev', 'E']


SITE = 'https://shelikes2run.github.io/GACC-fire-dashboard/'


def write_sfdi_geojson(out: Path, polys: dict, rows: list, now):
    """fdras_sfdi.geojson: every FDRA polygon with today's forecast SFDI and class — the
    main-map layer in AGOL (GeoJSON layer read from the site-data branch, refreshed by the map)."""
    from shapely.geometry import mapping, shape
    by = {r['fdra_id']: r for r in rows}
    feats = []
    for f in polys['features']:
        p = f['properties']
        r = by.get(p['fdra_id'], {})
        fc, ob = r.get('next_fcst') or {}, r.get('latest_obs') or {}
        g = shape(f['geometry']).simplify(0.001, preserve_topology=True)
        val = lambda d, k: (None if d.get(k) is None else round(float(d[k]), 1))
        feats.append({'type': 'Feature', 'geometry': mapping(g), 'properties': {
            'fdra_id': p['fdra_id'], 'forest': p.get('forest') or '', 'fdra_name': p.get('fdra_name') or '',
            'fuel_model': p.get('fuel_model') or '',
            'sfdi': val(fc, 'sfdi'), 'sfdi_class': sfdi_class(fc.get('sfdi')) or 'No data', 'fcst_date': fc.get('date') or '',
            'sfdi_obs': val(ob, 'sfdi'), 'sfdi_class_obs': sfdi_class(ob.get('sfdi')) or 'No data', 'obs_date': ob.get('date') or '',
            'erc': val(ob, 'erc'), 'erc_p': val(ob, 'erc_p'), 'bi': val(ob, 'bi'), 'bi_p': val(ob, 'bi_p'),
            'erc_f': val(fc, 'erc'), 'bi_f': val(fc, 'bi'),
            'charts': SITE + 'fdra.html?id=' + requests.utils.quote(p['fdra_id']),
            'workbench': SITE + 'fdop.html?id=' + requests.utils.quote(p['fdra_id']),
            'generated': now.strftime('%Y-%m-%d %H:%M %Z')}})
    gj = {'type': 'FeatureCollection', 'features': feats}
    (out / 'fdras_sfdi.geojson').write_text(json.dumps(gj, separators=(',', ':'), allow_nan=False))
    log.info('fdras_sfdi.geojson: %d polygons', len(feats))


def build_current(out: Path):
    now = datetime.now(TZ)
    today = now.date()
    start, end = f'{today.year}-01-01', (today + timedelta(days=10)).isoformat()
    mem, pairs = cn.load_fdra_membership(MEMBERSHIP)
    allm, own = all_fm(mem)
    sids = sorted(pairs['stationId'].astype(int).unique())
    pairs = pd.DataFrame([(s, fm) for s in sids for fm in FMS], columns=['stationId', 'FuelModel'])
    n, w = fetch_current(pairs, start, end)
    log.info('current: %d NFDR rows, %d wx rows, %s → %s', len(n), len(w), start, end)
    polys = json.loads(POLYGONS.read_text())
    pal = pal_by_polygon(polys)
    cdir = out / 'current'
    cdir.mkdir(parents=True, exist_ok=True)
    idx_units = {}
    names = n.drop_duplicates('stationId').set_index('stationId')['name'].to_dict()
    fm_files = {}
    for (uid, fmk), members in allm.items():
        stem = fm_name(uid, fmk, own[uid])
        mset = set(members)
        sub = n[[(s, f) in mset for s, f in zip(n['stationId'], n['fm'])]]
        if sub.empty:
            continue
        cols = ['erc', 'bi', 'ic', 'sc', 'herb', 'woody', 'fm1', 'fm10', 'fm100', 'fm1000', 'kbdi']
        d = _pick(sub, cols)
        d = d[~d.index.duplicated()]
        sids = sorted({s for s, _ in members})
        ww = w[w['stationId'].isin(sids)]
        if len(ww):
            d = d.join(_pick(ww, ['tmax', 'rhmin'])[['tmax', 'rhmin']], how='left')
        else:
            d['tmax'] = d['rhmin'] = np.nan
        cpath = out / 'normals' / 'climo' / f'{stem}.json'
        climo = json.loads(cpath.read_text()) if cpath.exists() else {}
        d['erc_p'] = _pct(d['erc'], climo.get('erc_q'))
        d['bi_p'] = _pct(d['bi'], climo.get('bi_q'))
        d['sfdi'] = _pct(d['erc_p'] * d['bi_p'], climo.get('sfdi_prod_q'))
        d['n'] = sub.groupby('date')['stationId'].nunique()
        d = d.sort_index()
        rnd = lambda s, k=1: [None if pd.isna(x) else round(float(x), k) for x in s]
        series = {'dates': [x.strftime('%Y-%m-%d') for x in d.index], 'type': d['type'].tolist(),
                  **{k: rnd(d[k]) for k in cols + ['tmax', 'rhmin', 'erc_p', 'bi_p', 'sfdi']},
                  'n': [int(x) if pd.notna(x) else None for x in d['n']]}
        # station table: latest observed day and next forecast day per station
        st_rows = []
        for (sid, fm), g in sub.groupby(['stationId', 'fm']):
            for t in ('O', 'F'):
                gg = g[g['type'] == t]
                if t == 'O':
                    gg = gg[gg['date'] <= pd.Timestamp(today)]
                    r = gg.sort_values('date').tail(1)
                else:
                    r = gg[gg['date'] >= pd.Timestamp(today)].sort_values('date').head(1)
                if len(r):
                    r = r.iloc[0]
                    st_rows.append({'stationId': int(sid), 'name': names.get(sid, ''), 'fm': fm, 'type': t,
                                    'date': r['date'].strftime('%Y-%m-%d'),
                                    **{k: (None if pd.isna(r[k]) else round(float(r[k]), 1)) for k in
                                       ['fm1', 'fm10', 'fm100', 'fm1000', 'herb', 'woody', 'kbdi', 'ic', 'erc', 'sc', 'bi']}})
        obs = d[(d['type'] == 'O')]
        last_o = obs.index.max() if len(obs) else None
        fc = d[(d['type'] == 'F') & (d.index >= pd.Timestamp(today))]
        snap = lambda r: None if r is None else {k: (None if pd.isna(r[k]) else round(float(r[k]), 1))
                                                   for k in ['erc', 'bi', 'erc_p', 'bi_p', 'sfdi']}
        o_row = d.loc[last_o] if last_o is not None else None
        f_row = fc.iloc[0] if len(fc) else None
        bid = base_id(uid)
        unit = {'unit_id': uid, 'fdra_id': bid, 'fm': fmk, 'fdop_fm': own[uid], 'season': uid[len(bid):].strip(' ()') or None,
                'stations': [{'stationId': s, 'name': names.get(s, ''), 'fm': f} for s, f in members],
                'has_normals': bool(climo), 'normal_years': climo.get('years', []),
                'latest_obs': {'date': last_o.strftime('%Y-%m-%d') if last_o is not None else None, **(snap(o_row) or {})},
                'next_fcst': {'date': fc.index[0].strftime('%Y-%m-%d') if len(fc) else None, **(snap(f_row) or {})}}
        unit['sfdi_class_fcst'] = sfdi_class(unit['next_fcst'].get('sfdi'))
        unit['sfdi_class_obs'] = sfdi_class(unit['latest_obs'].get('sfdi'))
        doc = {**unit, 'generated': now.strftime('%Y-%m-%d %H:%M %Z'), 'series': series, 'station_table': st_rows,
               'pal': pal.get(next((p['properties']['fdra_id'] for p in polys['features']
                                    if p['properties']['fdra_id'].upper() == bid.upper()), bid), [])}
        (cdir / f'{stem}.json').write_text(json.dumps(doc, separators=(',', ':'), allow_nan=False))
        fm_files.setdefault(uid, {})[fmk] = {'cur': f'current/{stem}.json',
                                             **({'norm': f'normals/climo/{stem}.json'} if climo else {})}
        if fmk == own[uid]:
            idx_units.setdefault(bid.upper(), []).append(unit)

    # index: one row per polygon; seasonal FDRAs pick the unit for today's season
    md = (today.month, today.day)
    rows = []
    for f in polys['features']:
        p = f['properties']
        units = idx_units.get(p['fdra_id'].upper(), [])
        active = None
        for u in units:
            if u['season'] in SEASONS:
                a, b = SEASONS[u['season']]
                if a <= md <= b:
                    active = u
        if active is None and units:
            active = next((u for u in units if u['season'] not in SEASONS), units[0])
        rows.append({'fdra_id': p['fdra_id'], 'forest': p['forest'], 'fdra_name': p['fdra_name'],
                     'fuel_model': p['fuel_model'], 'units': [u['unit_id'] for u in units],
                     'files': {u['unit_id']: f"current/{safe(u['unit_id'])}.json" for u in units},
                     'normals': {u['unit_id']: f"normals/climo/{safe(u['unit_id'])}.json" for u in units if u['has_normals']},
                     'fm_files': {u['unit_id']: fm_files.get(u['unit_id'], {}) for u in units},
                     'active_unit': active and active['unit_id'],
                     'latest_obs': active and active['latest_obs'], 'next_fcst': active and active['next_fcst'],
                     'sfdi_class_fcst': active and active['sfdi_class_fcst'],
                     'pal': [{'name': s['name'], 'today_1400': s['today_1400']} for s in pal.get(p['fdra_id'], [])]})
    write_sfdi_geojson(out, polys, rows, now)
    (out / 'fdras.json').write_text(json.dumps({'generated': now.strftime('%Y-%m-%d %H:%M %Z'), 'fdras': rows},
                                               separators=(',', ':'), allow_nan=False))
    log.info('current: %d units, %d polygons → %s', sum(len(v) for v in idx_units.values()), len(rows), out)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
    mode, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    if mode == 'normals':
        build_normals(out, Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / 'fems_raw')
    else:
        build_current(out)
