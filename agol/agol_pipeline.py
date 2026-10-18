"""
agol_pipeline.py
────────────────
Feeds the ArcGIS Online / Experience Builder version of the GACC Fire Weather
Intelligence Dashboard.

Experience Builder can't call the FEMS API itself, so this script does what
app.py + fems_fetcher.py do on the fly in Streamlit, then writes the results to
hosted layers that Experience Builder widgets read:

  1. Fetch D-30 … D+7 NFDR daily summaries for every key RAWS station
     (one FEMS request per station covers 30-day history AND 7-day forecast).
  2. Average stations to PSA level per day (same rules as fems_fetcher).
  3. Attach the 2005–2024 climo baseline + alert levels (same rules as app.py).
  4. Publish / update three AGOL items (created on first run, updated after):

     GACC Fire Wx – PSA Current   hosted polygon layer, 1 feature per PSA
                                  (NIFC PSA boundaries + today's values,
                                  climo thresholds, alerts, 7-day peaks)
     GACC Fire Wx – PSA Daily     hosted table, 1 row per PSA × date
                                  (D-30 … D+7, wide: every index + climo cols)
     GACC Fire Wx – Map           web map: PSA layer styled by alert for each
                                  primary index + the daily table

Run it:
  • In an ArcGIS Online Notebook (recommended — see GACC_AGOL_Pipeline.ipynb);
    GIS("home") signs in as the notebook owner, so SAML/eAuth orgs work.
  • Locally:  python agol/agol_pipeline.py --dry-run   (writes CSVs, no AGOL)
              python agol/agol_pipeline.py --profile nifc   (arcgis saved profile)

FEMS credentials come from env vars FEMS_API_KEY / FEMS_USERNAME, or a
KEY=VALUE file passed with --cred-file (in ArcGIS Notebooks keep it in
/arcgis/home, which only you can see).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger('agol_pipeline')

# ── Settings ──────────────────────────────────────────────────────────────────
REPO_DIR      = Path(__file__).resolve().parent.parent
HIST_DAYS     = 30          # observed history shown in Trend tab
FCST_DAYS     = 7           # NWS NFDR forecast days
LOCAL_TZ      = 'America/Los_Angeles'   # defines "today" for D-offsets
FOLDER        = 'GACC Fire Weather'
TAGS          = ['gacc-fire-wx', 'NFDRS', 'Predictive Services', 'FEMS']

TITLE_CURRENT = 'GACC Fire Wx – PSA Current'
TITLE_DAILY   = 'GACC Fire Wx – PSA Daily'
TITLE_MAP     = 'GACC Fire Wx – Map'

# Authoritative public PSA boundaries (NIFC / DMP)
PSA_BOUNDARY_URL = ('https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/'
                    'services/DMP_Predictive_Service_Area__PSA_Boundaries_Public/'
                    'FeatureServer/0')
PSA_CODE_FIELD   = 'PSANationalCode'
GEOM_SIMPLIFY_DEG = 0.002   # ~200 m — keeps the layer light; 0 = full detail

# Index keys (match fems_fetcher.FIELD_COLS and the baseline JSON)
ALL_FIELDS     = ['erc', 'ic', 'bi', 'sc', 'fm1', 'fm10', 'fm100', 'fm1000',
                  'kbdi', 'gsi', 'woody', 'herb']
CLIMO_FIELDS   = ['erc', 'ic', 'bi', 'sc', 'fm1', 'fm10', 'fm100', 'fm1000', 'kbdi']
CLIMO_STATS    = ['mean', 'p80', 'p90', 'p95', 'p97']
# Alerts only for "high = danger" indices. The baseline percentiles for fuel
# moisture are wet-side (p80…p97 of FM), so a ≥p97 test would flag WET days.
# FM alerts stay off until dry-side percentiles (p3/p5/p10/p20) are computed.
ALERT_FIELDS   = ['erc', 'ic', 'bi', 'sc', 'kbdi']
MOISTURE_FIELDS = {'fm1', 'fm10', 'fm100', 'fm1000', 'woody', 'herb'}

ALERT_RANK  = {'UNKNOWN': -1, 'NORMAL': 0, 'ELEVATED': 1, 'HIGH': 2, 'CRITICAL': 3}
ALERT_COLOR = {   # same palette as app.py
    'CRITICAL': '#ff2d55', 'HIGH': '#ff6b00', 'ELEVATED': '#ffcc00',
    'NORMAL': '#00c875', 'UNKNOWN': '#3a3f6b',
}
FIELD_LABEL = {
    'erc': 'ERC', 'ic': 'IC', 'bi': 'BI', 'sc': 'SC', 'fm1': 'FM-1',
    'fm10': 'FM-10', 'fm100': 'FM-100', 'fm1000': 'FM-1000', 'kbdi': 'KBDI',
    'gsi': 'GSI', 'woody': 'Woody FM', 'herb': 'Herb FM',
}


# ── Config / baseline loading ─────────────────────────────────────────────────
def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_inputs(repo_dir: Path = REPO_DIR):
    """Return (gacc_config, baseline_psa_dict, baseline_meta, fems_fetcher module)."""
    gacc_config = _load_module('gacc_config', repo_dir / 'gacc_config.py').GACC_CONFIG
    baseline = json.loads((repo_dir / 'gacc_climo_baseline.json').read_text(encoding='utf-8'))
    _patch_missing_psas(baseline, gacc_config)
    ff = _load_module('fems_fetcher', repo_dir / 'fems_fetcher.py')
    return gacc_config, baseline['psa'], baseline['meta'], ff


def _patch_missing_psas(baseline: dict, gacc_config: dict):
    """Same rule as app.py: a PSA missing from the baseline inherits thresholds
    from a PSA in the same GACC with an identical key-station set."""
    psa_data = baseline.setdefault('psa', {})
    for gname, ginfo in gacc_config.items():
        donors = {}
        for pid, info in ginfo['psas'].items():
            sids = frozenset(info.get('stations', []))
            if sids and f'{gname}|{pid}' in psa_data:
                donors[sids] = f'{gname}|{pid}'
        for pid, info in ginfo['psas'].items():
            key, sids = f'{gname}|{pid}', frozenset(info.get('stations', []))
            if key not in psa_data and sids and sids in donors:
                psa_data[key] = dict(psa_data[donors[sids]])
                log.info('Baseline: %s inherits %s', key, donors[sids])


def read_cred_file(path: str | None):
    if not path or not Path(path).exists():
        return
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ── Helpers ───────────────────────────────────────────────────────────────────
def local_today(tz: str = LOCAL_TZ) -> date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz)).date()
    except Exception:
        return date.today()


def alert_level(val, p90, p95, p97) -> str:
    """Identical thresholds to app.py alert_level()."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return 'UNKNOWN'
    if p97 is not None and val >= p97:
        return 'CRITICAL'
    if p95 is not None and val >= p95:
        return 'HIGH'
    if p90 is not None and val >= p90:
        return 'ELEVATED'
    return 'NORMAL'


def _noon_utc(d: date) -> pd.Timestamp:
    """Store calendar dates at 12:00 UTC so they render as the same day in
    every US time zone (AGOL date fields are UTC instants; midnight UTC shows
    as the previous evening in Pacific time)."""
    return pd.Timestamp(d) + pd.Timedelta(hours=12)


def _mean(vals):
    v = [x for x in vals if x is not None and not math.isnan(x) and x >= 0]
    return round(sum(v) / len(v), 1) if v else None


# ── 1. Fetch ──────────────────────────────────────────────────────────────────
def fetch_all_stations(ff, gacc_config: dict, today: date, workers: int = 16,
                       gacc_filter: list[str] | None = None) -> dict:
    """Returns {station_id: {date_str: entry}} for every key RAWS station."""
    station_fm = {}
    for ginfo in gacc_config.values():
        if gacc_filter and ginfo['abbrev'] not in gacc_filter:
            continue
        for info in ginfo['psas'].values():
            for s in info.get('stations', []):
                station_fm[s] = info.get('fuel_model', 'Y')

    start = str(today - timedelta(days=HIST_DAYS))
    end   = str(today + timedelta(days=FCST_DAYS))
    log.info('FEMS: %d stations, %s → %s', len(station_fm), start, end)

    out, done, t0 = {}, 0, time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(ff.fetch_station_data, sid, fm, start, end): sid
                for sid, fm in station_fm.items()}
        for fut in as_completed(futs):
            sid = futs[fut]
            try:
                data = fut.result()
            except Exception as e:      # never let one station kill the run
                log.warning('station %s: %s', sid, e)
                data = None
            if data:
                out[sid] = data
            done += 1
            if done % 100 == 0:
                log.info('  %d / %d stations (%.0fs)', done, len(station_fm), time.time() - t0)
    log.info('FEMS: data for %d / %d stations in %.0fs', len(out), len(station_fm), time.time() - t0)
    return out


# ── 2–3. Aggregate + attach climo/alerts ──────────────────────────────────────
def build_tables(gacc_config: dict, baseline_psa: dict, stations: dict,
                 today: date, run_utc: datetime,
                 gacc_filter: list[str] | None = None):
    """Return (current_df, daily_df) — plain pandas, no geometry yet."""
    dates = [today + timedelta(days=o) for o in range(-HIST_DAYS, FCST_DAYS + 1)]
    daily_rows, current_rows = [], []

    for gname, ginfo in gacc_config.items():
        abbrev = ginfo['abbrev']
        if gacc_filter and abbrev not in gacc_filter:
            continue
        for psa, info in ginfo['psas'].items():
            sids = info.get('stations', [])
            if not sids:                    # AICC etc. — no key stations configured
                continue
            b = baseline_psa.get(f'{gname}|{psa}', {})
            climo = {f'{fk}_{st}': (b.get(fk) or {}).get(st)
                     for fk in CLIMO_FIELDS for st in CLIMO_STATS}

            per_day = {}
            for d in dates:
                ds = str(d)
                entries = [stations[s][ds] for s in sids if s in stations and ds in stations[s]]
                types = {e.get('type') for e in entries}
                row = {
                    'gacc': abbrev, 'gacc_name': gname, 'psa': psa,
                    'fuel_model': info.get('fuel_model', ''),
                    'obs_date': _noon_utc(d),
                    'date_str': str(d),
                    'day_offset': (d - today).days,
                    'nfdr_type': 'O' if 'O' in types else ('F' if 'F' in types else None),
                    'n_stations': len(entries),
                }
                row['is_forecast'] = 1 if row['nfdr_type'] == 'F' else 0
                for fk in ALL_FIELDS:
                    row[fk] = _mean([e.get(fk) for e in entries])
                row.update(climo)
                for fk in ALERT_FIELDS:
                    lvl = alert_level(row[fk], climo[f'{fk}_p90'], climo[f'{fk}_p95'], climo[f'{fk}_p97'])
                    row[f'{fk}_alert'], row[f'{fk}_rank'] = lvl, ALERT_RANK[lvl]
                row['run_utc'] = run_utc
                per_day[row['day_offset']] = row
                daily_rows.append(row)

            # Current/summary feature for the map
            td = per_day[0]
            cur = {
                'gacc': abbrev, 'gacc_name': gname, 'psa': psa,
                'fuel_model': info.get('fuel_model', ''),
                'stations': ', '.join(str(s) for s in sids),
                'n_stations': len(sids),
                'n_with_data': sum(1 for s in sids if s in stations),
                'today_date': _noon_utc(today),
                'today_type': td['nfdr_type'],
                'run_utc': run_utc,
            }
            fc_days = [per_day[o] for o in range(1, FCST_DAYS + 1)]
            for fk in ALL_FIELDS:
                cur[f'{fk}_td'] = td[fk]
                cur[f'{fk}_yd'] = per_day[-1][fk]
                fvals = [r[fk] for r in fc_days if r[fk] is not None]
                # 7-day "worst" value: min for moisture, max for indices
                cur[f'{fk}_pk7'] = (min(fvals) if fk in MOISTURE_FIELDS else max(fvals)) if fvals else None
                cur[f'{fk}_d7'] = per_day[FCST_DAYS][fk]
            cur.update(climo)
            for fk in ALERT_FIELDS:
                p90, p95, p97 = climo[f'{fk}_p90'], climo[f'{fk}_p95'], climo[f'{fk}_p97']
                lvl = alert_level(cur[f'{fk}_td'], p90, p95, p97)
                pk  = alert_level(cur[f'{fk}_pk7'], p90, p95, p97)
                cur[f'{fk}_alert'], cur[f'{fk}_rank'] = lvl, ALERT_RANK[lvl]
                cur[f'{fk}_pk7_alert'], cur[f'{fk}_pk7_rank'] = pk, ALERT_RANK[pk]
            # ERC change today → D+7 (the old "ERC Trend" delta)
            cur['erc_chg7'] = (round(cur['erc_d7'] - cur['erc_td'], 1)
                               if cur['erc_d7'] is not None and cur['erc_td'] is not None else None)
            # Highest alert across indices today — handy for one-glance map
            ranks = [cur[f'{fk}_rank'] for fk in ALERT_FIELDS]
            top = max(ranks)
            cur['max_rank'] = top
            cur['max_alert'] = next(k for k, v in ALERT_RANK.items() if v == top)
            current_rows.append(cur)

    current = _coerce(pd.DataFrame(current_rows))
    daily = _coerce(pd.DataFrame(daily_rows))
    log.info('Built %d PSA features, %d daily rows', len(current), len(daily))
    return current, daily


TEXT_COLS = {'gacc', 'gacc_name', 'psa', 'psa_name', 'fuel_model', 'stations',
             'nfdr_type', 'today_type', 'date_str', 'max_alert'}
INT_COLS = {'day_offset', 'n_stations', 'n_with_data', 'is_forecast', 'max_rank'}


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    """Pin column dtypes so an all-null column (e.g. GSI on forecast days)
    never gets published as a text field."""
    for c in df.columns:
        if c in TEXT_COLS or c.endswith('_alert') or c in ('obs_date', 'today_date', 'run_utc'):
            continue
        if c in INT_COLS or c.endswith('_rank'):
            df[c] = pd.to_numeric(df[c], errors='coerce').astype('Int64')
        else:
            df[c] = pd.to_numeric(df[c], errors='coerce').astype('float64')
    return df


# ── 4. AGOL publish / update ──────────────────────────────────────────────────
def connect(profile: str | None = None):
    from arcgis.gis import GIS
    if profile:
        return GIS(profile=profile)
    try:
        return GIS('home')          # ArcGIS Notebook — signed in as owner
    except Exception:
        return GIS('pro')           # ArcGIS Pro active portal on Windows


def _find_item(gis, title: str, item_type: str):
    me = gis.users.me.username
    hits = gis.content.search(f'title:"{title}" AND owner:{me}', item_type=item_type, max_items=20)
    hits = [h for h in hits if h.title == title]
    return hits[0] if hits else None


def _ensure_folder(gis, name: str):
    try:
        gis.content.folders.create(name, exist_ok=True)      # arcgis >= 2.3
    except AttributeError:                                    # arcgis < 2.3
        if name not in [f['title'] for f in gis.users.me.folders]:
            gis.content.create_folder(name)


def _to_attrs(rec: dict) -> dict:
    out = {}
    for k, v in rec.items():
        if v is None or (not isinstance(v, (str, list, dict)) and pd.isna(v)):
            out[k] = None
        elif isinstance(v, (pd.Timestamp, datetime)):
            ts = pd.Timestamp(v)
            if ts.tzinfo is None:
                ts = ts.tz_localize('UTC')
            out[k] = int(ts.timestamp() * 1000)
        elif hasattr(v, 'item'):     # numpy scalar
            out[k] = v.item()
        else:
            out[k] = v
    return out


def _esri_field(name: str, series: pd.Series) -> dict:
    if pd.api.types.is_datetime64_any_dtype(series):
        t = 'esriFieldTypeDate'
    elif pd.api.types.is_integer_dtype(series):
        t = 'esriFieldTypeInteger'
    elif pd.api.types.is_float_dtype(series):
        t = 'esriFieldTypeDouble'
    else:
        t = 'esriFieldTypeString'
    f = {'name': name, 'type': t, 'alias': name, 'nullable': True, 'editable': True}
    if t == 'esriFieldTypeString':
        f['length'] = 512 if name == 'stations' else 128
    return f


def _sync_schema(layer, df: pd.DataFrame):
    """Add any new DataFrame columns to the hosted layer (schema evolves safely)."""
    have = {f['name'].lower() for f in layer.properties.fields}
    new = [_esri_field(c, df[c]) for c in df.columns if c.lower() not in have and c != 'SHAPE']
    if new:
        log.info('Adding fields to %s: %s', layer.properties.name, [f['name'] for f in new])
        layer.manager.add_to_definition({'fields': new})


def _apply(layer, adds=None, updates=None, batch=1000):
    for kind, feats in (('adds', adds or []), ('updates', updates or [])):
        for i in range(0, len(feats), batch):
            res = layer.edit_features(**{kind: feats[i:i + batch]})
            key = 'addResults' if kind == 'adds' else 'updateResults'
            bad = [r for r in res.get(key, []) if not r.get('success')]
            if bad:
                raise RuntimeError(f'{kind} failed on {len(bad)} records: {bad[:3]}')


def fetch_psa_boundaries(gis):
    from arcgis.features import FeatureLayer
    fl = FeatureLayer(PSA_BOUNDARY_URL, gis=gis)
    kw = dict(where='1=1', out_fields=f'{PSA_CODE_FIELD},PSANAME,GACCUnitID',
              out_sr=4326, return_geometry=True)
    if GEOM_SIMPLIFY_DEG:
        kw['max_allowable_offset'] = GEOM_SIMPLIFY_DEG
    fs = fl.query(**kw)
    geoms = {}
    for f in fs.features:
        code = (f.attributes.get(PSA_CODE_FIELD) or '').strip().upper()
        if code:
            geoms[code] = (f.geometry, f.attributes.get('PSANAME'))
    log.info('NIFC PSA boundaries: %d polygons', len(geoms))
    return geoms


def publish_current(gis, current: pd.DataFrame):
    """Create (first run) or attribute-update the PSA polygon layer."""
    item = _find_item(gis, TITLE_CURRENT, 'Feature Layer')
    if item is None:
        geoms = fetch_psa_boundaries(gis)
        df = current.copy()
        df['psa_name'] = [geoms.get(p.upper(), (None, None))[1] for p in df['psa']]
        missing = [p for p in df['psa'] if p.upper() not in geoms]
        if missing:
            log.warning('No NIFC boundary for %d PSAs — left off the map layer '
                        '(still in the Daily table): %s', len(missing), missing)
        df = df[[p.upper() in geoms for p in df['psa']]].reset_index(drop=True)

        layer_def = _layer_definition(TITLE_CURRENT, df, 'esriGeometryPolygon')
        item = _create_service(gis, TITLE_CURRENT, layer_def,
                               'Daily PSA fire-danger snapshot: NFDR indices vs 2005–2024 climo, '
                               'alert levels and 7-day forecast peaks. Updated by agol_pipeline.py.')
        layer = item.layers[0]
        feats = [{'attributes': _to_attrs(r), 'geometry': geoms[r['psa'].upper()][0]}
                 for r in df.to_dict('records')]
        _apply(layer, adds=feats, batch=200)
        log.info('Created %s (%s) with %d PSAs', TITLE_CURRENT, item.id, len(feats))
        return item

    layer = item.layers[0]
    _sync_schema(layer, current.assign(psa_name=''))
    existing = layer.query(where='1=1', out_fields='OBJECTID,psa', return_geometry=False)
    oid = {f.attributes['psa']: f.attributes['OBJECTID'] for f in existing.features}
    updates = []
    for r in current.to_dict('records'):
        if r['psa'] in oid:
            updates.append({'attributes': {**_to_attrs(r), 'OBJECTID': oid[r['psa']]}})
    new = sorted(set(current['psa']) - set(oid))
    if new:
        log.warning('PSAs not yet in the layer (add boundaries by deleting the item '
                    'and re-running, or append manually): %s', new)
    _apply(layer, updates=updates, batch=500)
    log.info('Updated %d PSA features in %s', len(updates), item.id)
    return item


def publish_daily(gis, daily: pd.DataFrame):
    """Create (first run) or truncate + reload the PSA × date table."""
    item = _find_item(gis, TITLE_DAILY, 'Feature Layer')
    if item is None:
        layer_def = _layer_definition(TITLE_DAILY, daily, None)
        item = _create_service(gis, TITLE_DAILY, layer_def,
                               'PSA × date NFDR values (30-day observed + 7-day forecast) with '
                               '2005–2024 climo thresholds. Updated by agol_pipeline.py.')
    table = item.tables[0]
    _sync_schema(table, daily)
    table.manager.truncate()
    _apply(table, adds=[{'attributes': _to_attrs(r)} for r in daily.to_dict('records')], batch=2000)
    log.info('Loaded %d rows into %s (%s)', len(daily), TITLE_DAILY, item.id)
    return item


def _layer_definition(name: str, df: pd.DataFrame, geom_type: str | None) -> dict:
    fields = [{'name': 'OBJECTID', 'type': 'esriFieldTypeOID', 'alias': 'OBJECTID',
               'nullable': False, 'editable': False}]
    fields += [_esri_field(c, df[c]) for c in df.columns]
    d = {
        'name': name.replace('–', '-'),
        'type': 'Feature Layer' if geom_type else 'Table',
        'objectIdField': 'OBJECTID',
        'fields': fields,
        'capabilities': 'Query,Create,Update,Delete,Editing',
        'hasAttachments': False,
        'indexes': [{'name': 'idx_psa', 'fields': 'psa', 'isAscending': True, 'isUnique': False},
                    {'name': 'idx_gacc', 'fields': 'gacc', 'isAscending': True, 'isUnique': False}],
    }
    if geom_type:
        d.update(geometryType=geom_type, extent={
            'xmin': -180, 'ymin': 15, 'xmax': -60, 'ymax': 72, 'spatialReference': {'wkid': 4326}})
    return d


def _create_service(gis, title: str, layer_def: dict, snippet: str):
    """Empty hosted feature service with one layer/table, in FOLDER."""
    _ensure_folder(gis, FOLDER)
    svc_name = title.replace('–', '').replace(' ', '_').replace('__', '_')
    svc_name = f'{svc_name}_{datetime.now(timezone.utc):%Y%m%d%H%M}'
    svc_item = gis.content.create_service(
        name=svc_name, service_type='featureService', wkid=4326, folder=FOLDER,
        max_record_count=2000, item_properties={'title': title, 'snippet': snippet},
        tags=TAGS, snippet=snippet)
    if svc_item.title != title:
        svc_item.update(item_properties={'title': title})
    from arcgis.features import FeatureLayerCollection
    flc = FeatureLayerCollection.fromitem(svc_item)
    key = 'layers' if layer_def['type'] == 'Feature Layer' else 'tables'
    flc.manager.add_to_definition({key: [layer_def]})
    return gis.content.get(svc_item.id)


def publish_map(gis, current_item, daily_item):
    """Create the web map once. Re-runs leave it alone (so your edits survive)."""
    item = _find_item(gis, TITLE_MAP, 'Web Map')
    if item is not None:
        return item
    url = current_item.layers[0].url
    op_layers = []
    views = [('max', 'Highest alert (any index) — today')] + \
            [(fk, f'{FIELD_LABEL[fk]} alert — today') for fk in ALERT_FIELDS] + \
            [('erc_pk7', 'ERC alert — 7-day forecast peak')]
    for i, (key, title) in enumerate(views):
        alert_field = 'max_alert' if key == 'max' else (
            'erc_pk7_alert' if key == 'erc_pk7' else f'{key}_alert')
        op_layers.append({
            'id': f'psa_{key}', 'title': title, 'url': url, 'itemId': current_item.id,
            'layerType': 'ArcGISFeatureLayer', 'visibility': i == 1,   # ERC on by default
            'opacity': 0.85,
            'layerDefinition': {'drawingInfo': {
                'renderer': _alert_renderer(alert_field),
                'labelingInfo': [_psa_label()]}},
            'showLabels': True,
            'popupInfo': _popup(),
        })
    wm = {
        'operationalLayers': op_layers,
        'tables': [{'id': 'psa_daily', 'title': 'PSA Daily (D-30 … D+7)',
                    'url': daily_item.tables[0].url, 'itemId': daily_item.id}],
        'baseMap': {'title': 'Dark Gray Canvas', 'baseMapLayers': [
            {'id': 'dg_base', 'title': 'World Dark Gray Base', 'layerType': 'ArcGISTiledMapServiceLayer',
             'url': 'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer',
             'visibility': True, 'opacity': 1},
            {'id': 'dg_ref', 'title': 'World Dark Gray Reference', 'layerType': 'ArcGISTiledMapServiceLayer',
             'url': 'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer',
             'visibility': True, 'opacity': 1, 'isReference': True}]},
        'spatialReference': {'wkid': 102100, 'latestWkid': 3857},
        'version': '2.31',
        'authoringApp': 'agol_pipeline.py', 'authoringAppVersion': '1.0',
    }
    props = {'type': 'Web Map', 'title': TITLE_MAP, 'tags': ','.join(TAGS),
             'snippet': 'PSA fire-danger alerts vs 2005–2024 climo for the GACC Fire Wx Experience.',
             'extent': '-125,24,-66,50', 'text': json.dumps(wm)}
    try:
        folder = gis.content.folders.get(FOLDER)
        item = folder.add(item_properties=props).result()
    except AttributeError:
        item = gis.content.add(item_properties=props, folder=FOLDER)
    log.info('Created web map %s', item.id)
    return item


def _alert_renderer(field: str) -> dict:
    def sym(color):
        h = color.lstrip('#')
        rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
        return {'type': 'esriSFS', 'style': 'esriSFSSolid', 'color': rgb + [190],
                'outline': {'type': 'esriSLS', 'style': 'esriSLSSolid',
                            'color': [13, 15, 26, 255], 'width': 0.6}}
    labels = {'CRITICAL': 'Critical (≥ 97th)', 'HIGH': 'High (≥ 95th)',
              'ELEVATED': 'Elevated (≥ 90th)', 'NORMAL': 'Normal (< 90th)', 'UNKNOWN': 'No data'}
    return {'type': 'uniqueValue', 'field1': field,
            'defaultSymbol': sym(ALERT_COLOR['UNKNOWN']), 'defaultLabel': 'No data',
            'uniqueValueInfos': [{'value': k, 'label': labels[k], 'symbol': sym(ALERT_COLOR[k])}
                                 for k in ['CRITICAL', 'HIGH', 'ELEVATED', 'NORMAL']]}


def _psa_label() -> dict:
    return {'labelExpressionInfo': {'expression': '$feature.psa'},
            'labelPlacement': 'esriServerPolygonPlacementAlwaysHorizontal',
            'minScale': 12000000, 'maxScale': 0,
            'symbol': {'type': 'esriTS', 'color': [232, 234, 246, 255],
                       'haloColor': [13, 15, 26, 255], 'haloSize': 1,
                       'font': {'family': 'Arial', 'size': 8, 'weight': 'bold'}}}


def _popup() -> dict:
    rows = ''.join(
        f'<tr><td>{FIELD_LABEL[fk]}</td><td><b>{{{fk}_td}}</b></td><td>{{{fk}_alert}}</td>'
        f'<td>{{{fk}_p90}} / {{{fk}_p95}} / {{{fk}_p97}}</td><td>{{{fk}_pk7}}</td></tr>'
        for fk in ALERT_FIELDS)
    html = ('<p><b>{gacc} · {psa}</b> {psa_name}<br>Fuel model {fuel_model} · '
            '{n_with_data}/{n_stations} key RAWS reporting · today = {today_type}</p>'
            '<table style="width:100%;font-size:12px"><tr><th>Index</th><th>Today</th>'
            '<th>Alert</th><th>P90/P95/P97</th><th>7-day peak</th></tr>' + rows +
            '</table><p style="font-size:11px">FM-100 today {fm100_td} (7-day min {fm100_pk7}) · '
            'ERC change to D+7: {erc_chg7}<br>Key RAWS: {stations}</p>')
    return {'title': '{psa} — {max_alert}', 'description': html, 'showAttachments': False}


# ── Entry point ───────────────────────────────────────────────────────────────
def run(dry_run: bool = False, profile: str | None = None, out_dir: Path | None = None,
        gaccs: list[str] | None = None, repo_dir: Path = REPO_DIR, workers: int = 16):
    gacc_config, baseline_psa, baseline_meta, ff = load_inputs(repo_dir)
    ff.FEMS_API_KEY = os.getenv('FEMS_API_KEY', '')
    ff.FEMS_USERNAME = os.getenv('FEMS_USERNAME', '')
    if not ff.FEMS_API_KEY:
        raise SystemExit('FEMS_API_KEY not set (env var or --cred-file).')

    today = local_today()
    run_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    stations = fetch_all_stations(ff, gacc_config, today, workers, gaccs)
    if not stations:
        raise SystemExit('FEMS returned no station data — leaving AGOL layers untouched.')
    current, daily = build_tables(gacc_config, baseline_psa, stations, today, run_utc, gaccs)

    if dry_run:
        out_dir = out_dir or Path('agol_out')
        out_dir.mkdir(parents=True, exist_ok=True)
        current.to_csv(out_dir / 'psa_current.csv', index=False)
        daily.to_csv(out_dir / 'psa_daily.csv', index=False)
        log.info('Dry run → %s', out_dir.resolve())
        return current, daily

    gis = connect(profile)
    log.info('Signed in to %s as %s', gis.properties.portalHostname, gis.users.me.username)
    cur_item = publish_current(gis, current)
    day_item = publish_daily(gis, daily)
    map_item = publish_map(gis, cur_item, day_item)
    log.info('Done. Current=%s Daily=%s Map=%s', cur_item.id, day_item.id, map_item.id)
    return cur_item, day_item, map_item


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--dry-run', action='store_true', help='write CSVs instead of publishing')
    p.add_argument('--out-dir', type=Path, default=Path('agol_out'))
    p.add_argument('--profile', help='arcgis saved profile name (local runs)')
    p.add_argument('--cred-file', help='KEY=VALUE file with FEMS_API_KEY / FEMS_USERNAME')
    p.add_argument('--gacc', nargs='*', help='limit to these GACC abbrevs (testing)')
    p.add_argument('--workers', type=int, default=16)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
    read_cred_file(a.cred_file or os.getenv('FEMS_CRED_FILE'))
    run(a.dry_run, a.profile, a.out_dir, a.gacc, workers=a.workers)


if __name__ == '__main__':
    main()
