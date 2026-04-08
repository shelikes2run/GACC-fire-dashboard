"""
fems_fetcher.py
───────────────
Fetches NFDR data from FEMS using the confirmed REST endpoint:

  GET /api/ext-climatology/download-nfdr-daily-summary/
      ?dataset=all
      &startDate=YYYY-MM-DD   (5 days back)
      &endDate=YYYY-MM-DD     (7 days ahead)
      &dataFormat=csv
      &stationIds=XXXXX
      &fuelModels=Y

A single request per station returns 13 rows:
  - NFDRType=O  past 5 days + today  (observed daily values)
  - NFDRType=F  next 7 days          (NWS operational forecast)

All 12 NFDR fields confirmed from sample CSV:
  Fire behaviour (daily max):    ERC, IC, BI, SC
  Fuel moisture  (daily min):    1HrFM, 10HrFM, 100HrFM, 1000HrFM
  Drought/live fuel:             KBDI, GSI, WoodyFM, HerbFM
  QA:                            NFDRQAFlag

Climo baseline (2005–2024) loaded from gacc_climo_baseline.json — no API call.
"""

import os, json, logging, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, date
from pathlib import Path
from statistics import mean

import requests

FEMS_API_KEY  = os.getenv('FEMS_API_KEY',  '')
FEMS_USERNAME = os.getenv('FEMS_USERNAME', '')
FEMS_BASE     = ('https://fems.fs2c.usda.gov'
                 '/api/ext-climatology/download-nfdr-daily-summary/')

logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('fems_fetcher')

# ── Field definitions ─────────────────────────────────────────────────────────
# Internal key → exact CSV column name from the NFDR daily summary endpoint
# All confirmed from: nfdrsDailySummary2026-02-04_2026-02-25.csv

FIELD_COLS = {
    # Fire behaviour indices — daily MAX
    'erc':    'ERC',
    'ic':     'IC',
    'bi':     'BI',
    'sc':     'SC',
    # Fuel moisture — daily MIN (lower = drier = more dangerous)
    'fm1':    '1HrFM',
    'fm10':   '10HrFM',
    'fm100':  '100HrFM',
    'fm1000': '1000HrFM',
    # Drought & live fuel indices
    'kbdi':   'KBDI',
    'gsi':    'GSI',
    'woody':  'WoodyFM',
    'herb':   'HerbFM',
}

# QA flag — stored per day entry but not plotted as a field
QA_FLAG_COL = 'NFDRQAFlag'

# Note: KBDI, GSI, WoodyFM, HerbFM may be null/zero in forecast (F) rows
# depending on the NFDR model at each station — handled gracefully as None

# Day labels: 5 observed + today + 7 forecast = 13 total
DAY_LABELS = ['D-5','D-4','D-3','D-2','yd','td','D+1','D+2','D+3','D+4','D+5','D+6','D+7']

# Increment this when the cache JSON structure changes.
# app.py checks this on load — mismatch forces a fresh fetch.
CACHE_SCHEMA = 3   # v3: 13-day window (D-5…D+7) + day_types + QA flag


# ── Auth & config loaders ─────────────────────────────────────────────────────

def _headers():
    if not FEMS_API_KEY:
        raise EnvironmentError('FEMS_API_KEY not set')
    return {
        'x-api-key':    FEMS_API_KEY,
        'x-user-email': FEMS_USERNAME,
        'Accept':       'text/csv',
    }


def load_gacc_config():
    import importlib.util
    spec = importlib.util.spec_from_file_location('gacc_config', 'gacc_config.py')
    gc   = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gc)
    return gc.GACC_CONFIG


def load_baseline(path='gacc_climo_baseline.json'):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"'{path}' not found.\n"
            "Run GACC_Climo_Download.ipynb first to build the climo baseline."
        )
    data = json.loads(p.read_text(encoding='utf-8'))
    log.info('Baseline: %d PSAs  climo %d–%d',
             data['meta']['n_psa'],
             data['meta']['climo_start'],
             data['meta']['climo_end'])
    return data


# ── Day map & label helpers ───────────────────────────────────────────────────

def _build_day_map():
    """
    Returns {label: date_string} for all 13 display columns.

    5 observed days back  D-5 … yd   (NFDRType=O)
    Today                 td          (O if obs available, else F)
    7 forecast days ahead D+1 … D+7  (NFDRType=F)

    Uses rolling offsets — never weekday names — so labels are always
    correct regardless of what day the cache was written. app.py calls
    _day_label() at render time to convert to human-readable strings.
    """
    today = date.today()
    return {
        'D-5': str(today - timedelta(days=5)),
        'D-4': str(today - timedelta(days=4)),
        'D-3': str(today - timedelta(days=3)),
        'D-2': str(today - timedelta(days=2)),
        'yd':  str(today - timedelta(days=1)),
        'td':  str(today),
        'D+1': str(today + timedelta(days=1)),
        'D+2': str(today + timedelta(days=2)),
        'D+3': str(today + timedelta(days=3)),
        'D+4': str(today + timedelta(days=4)),
        'D+5': str(today + timedelta(days=5)),
        'D+6': str(today + timedelta(days=6)),
        'D+7': str(today + timedelta(days=7)),
    }


def _day_label(date_str: str) -> str:
    """
    Convert a YYYY-MM-DD string to a human-readable chart label.
    Called at render time — always reflects today's actual date.

    e.g. today = Wednesday Mar 25:
      D-5 (Mar 20) → 'Fri'
      D-2 (Mar 23) → 'Mon'
      yd  (Mar 24) → 'Yesterday'
      td  (Mar 25) → 'Today'
      D+1 (Mar 26) → 'Thu'
      D+7 (Apr 01) → 'Wed'
    """
    DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    try:
        from datetime import date as _date
        d     = _date.fromisoformat(date_str)
        today = _date.today()
        delta = (d - today).days
        if delta == -1: return 'Yesterday'
        if delta == 0:  return 'Today'
        return DAY_NAMES[d.weekday()]
    except Exception:
        return date_str


# ── Core station fetch ────────────────────────────────────────────────────────

def _safe_mean(vals):
    v = [x for x in vals if x is not None and x >= 0]
    return round(mean(v), 1) if v else None


def fetch_station_data(station_id, fuel_model, start_date, end_date, retries=3):
    """
    Fetch NFDR daily summary for one station over a date range.
    Returns {date_str: {'type': 'O'|'F', 'qa': int, fk: float, ...}}
    Returns None if station has no data.

    For each date, observed (O) beats forecast (F) when both exist.
    """
    url = (
        f'{FEMS_BASE}'
        f'?dataset=all'
        f'&startDate={start_date}'
        f'&endDate={end_date}'
        f'&dataFormat=csv'
        f'&stationIds={station_id}'
        f'&fuelModels={fuel_model}'
    )

    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=_headers(), timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            if not r.text.strip() or len(r.text) < 50:
                return None

            import pandas as pd
            from io import StringIO

            df = pd.read_csv(StringIO(r.text))
            df.columns = df.columns.str.strip()

            if 'ObservationTime' not in df.columns:
                return None

            # Build per-row entries keyed by (date, ntype)
            raw = {}
            for _, row in df.iterrows():
                try:
                    d     = str(pd.to_datetime(row['ObservationTime']).date())
                    ntype = str(row.get('NFDRType', 'O'))
                    entry = {'type': ntype}

                    for fk, col in FIELD_COLS.items():
                        if col in df.columns:
                            v = row[col]
                            entry[fk] = float(v) if pd.notna(v) else None
                        else:
                            entry[fk] = None

                    # Store QA flag (0 = good, non-zero = flagged)
                    if QA_FLAG_COL in df.columns:
                        qa = row[QA_FLAG_COL]
                        entry['qa'] = int(qa) if pd.notna(qa) else 0

                    raw[(d, ntype)] = entry
                except Exception:
                    continue

            # Merge: prefer O over F for same date
            result = {}
            for d in {d for d, _ in raw}:
                result[d] = raw.get((d, 'O')) or raw.get((d, 'F'))

            return result or None

        except Exception as e:
            if attempt < retries:
                time.sleep(2 * attempt)
            else:
                log.warning('station %s failed after %d tries: %s',
                            station_id, retries, e)
                return None


# ── PSA-level aggregation & cache ─────────────────────────────────────────────

def fetch_psa_forecast(gacc_name, psa_ids=None,
                       output_path='gacc_data.json',
                       baseline_path='gacc_climo_baseline.json'):
    """
    Full pipeline for one GACC:
      1. Load climo baseline (local — instant)
      2. Fetch 13-day window (D-5 → D+7) for every station in parallel
      3. Aggregate to PSA-level daily averages
      4. Attach climo thresholds from baseline
      5. Write per-GACC cache JSON and return dict

    Data window:
      D-5 … yd  → observed rows (NFDRType=O)
      td        → observed if available, otherwise forecast
      D+1 … D+7 → forecast rows (NFDRType=F)
    """
    t0          = time.time()
    gacc_config = load_gacc_config()
    baseline    = load_baseline(baseline_path)

    psas_cfg = gacc_config.get(gacc_name, {}).get('psas', {})
    if psa_ids:
        psas_cfg = {k: v for k, v in psas_cfg.items() if k in psa_ids}

    station_fuel_map = {}
    for info in psas_cfg.values():
        fm = info.get('fuel_model', 'Y')
        for s in info.get('stations', []):
            station_fuel_map[s] = fm

    all_sids  = sorted(station_fuel_map)
    day_map   = _build_day_map()
    start_str = day_map['D-5']
    end_str   = day_map['D+7']

    log.info('Fetching %s — %d stations  %s → %s',
             gacc_config[gacc_name]['abbrev'], len(all_sids), start_str, end_str)

    # Parallel fetch — 16 workers handles SACC (260 stations) in ~35s
    def _fetch_one(sid):
        return sid, fetch_station_data(
            sid, station_fuel_map[sid], start_str, end_str)

    forecasts = {}
    completed = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(_fetch_one, sid): sid for sid in all_sids}
        for fut in as_completed(futures):
            sid, data = fut.result()
            if data:
                forecasts[sid] = data
            completed += 1
            if completed % 25 == 0:
                log.info('  %d / %d stations', completed, len(all_sids))

    log.info('  Got data: %d / %d stations', len(forecasts), len(all_sids))

    # Aggregate to PSA level
    psa_out = {}
    for psa_id, info in psas_cfg.items():
        sids   = info.get('stations', [])
        bkey   = f'{gacc_name}|{psa_id}'
        bentry = baseline.get('psa', {}).get(bkey, {})

        def day_avgs(fk):
            """Average one field across stations for each day label."""
            out = {}
            for label, target in day_map.items():
                vals = []
                for sid in sids:
                    if sid in forecasts and target in forecasts[sid]:
                        v = forecasts[sid][target].get(fk)
                        if v is not None and v >= 0:
                            vals.append(v)
                out[label] = _safe_mean(vals)
            return out

        def attach_climo(day_dict, fk):
            b = bentry.get(fk, {})
            return {
                **day_dict,
                'Climo_Mean': b.get('mean'),
                'P80':  b.get('p80'),
                'P90':  b.get('p90'),
                'P95':  b.get('p95'),
                'P97':  b.get('p97'),
            }

        # Also store whether each day slot has observed vs forecast data
        def day_types():
            """Return {label: 'O'|'F'|None} for each day."""
            out = {}
            for label, target in day_map.items():
                types = []
                for sid in sids:
                    if sid in forecasts and target in forecasts[sid]:
                        types.append(forecasts[sid][target].get('type', 'O'))
                # If any station has O, call it observed
                if 'O' in types:
                    out[label] = 'O'
                elif 'F' in types:
                    out[label] = 'F'
                else:
                    out[label] = None
            return out

        field_data = {fk: attach_climo(day_avgs(fk), fk) for fk in FIELD_COLS}

        # ERC trend: delta vs today for forecast days
        today_erc = field_data['erc'].get('td') or 0
        erc_trend = {lbl: 0.0 if lbl == 'td' else
                     (round(field_data['erc'].get(lbl, 0) - today_erc, 1)
                      if field_data['erc'].get(lbl) is not None else None)
                     for lbl in DAY_LABELS}

        psa_out[psa_id] = {
            'psa':                psa_id,
            'fuel_model':         info.get('fuel_model', 'Y'),
            'day_map':            day_map,
            'day_types':          day_types(),   # O/F per day slot
            'stations_total':     len(sids),
            'stations_with_data': sum(1 for s in sids if s in forecasts),
            'ERC_trend':          erc_trend,
            **field_data,
        }

    output = {
        'meta': {
            'cache_schema': CACHE_SCHEMA,
            'gacc':        gacc_name,
            'abbrev':      gacc_config[gacc_name]['abbrev'],
            'fetched_at':  datetime.utcnow().isoformat() + 'Z',
            'fetch_date':  str(date.today()),
            'climo_start': baseline['meta']['climo_start'],
            'climo_end':   baseline['meta']['climo_end'],
            'percentiles': baseline['meta']['percentiles'],
            'fields':      list(FIELD_COLS.keys()),
            'day_labels':  DAY_LABELS,
            'psa_count':   len(psa_out),
        },
        'psa': psa_out,
    }

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(output, indent=2), encoding='utf-8')
    log.info('Done in %.1fs → %s', time.time() - t0, output_path)
    return output


def json_to_dataframes(data):
    """
    Convert gacc_data.json into per-field DataFrames.
    Returns {field_key: DataFrame, 'trend': DataFrame, 'types': DataFrame}

    Field DataFrames columns: PSA, D-5…D+7, Climo_Mean, P80, P90, P95, P97
    Trend DataFrame columns:  PSA, D-5…D+7  (ERC delta vs today)
    Types DataFrame columns:  PSA, D-5…D+7  ('O', 'F', or None)
    """
    import pandas as pd

    frames     = {fk: [] for fk in FIELD_COLS}
    trend_rows = []
    type_rows  = []

    for psa_id, psa in data['psa'].items():
        for fk in FIELD_COLS:
            fdata = psa.get(fk, {})
            row   = {'PSA': psa_id}
            for d in DAY_LABELS:
                row[d] = fdata.get(d)
            row['Climo_Mean'] = fdata.get('Climo_Mean')
            for p in [80, 90, 95, 97]:
                row[f'P{p}'] = fdata.get(f'P{p}')
            frames[fk].append(row)

        t = psa.get('ERC_trend', {})
        trend_rows.append({'PSA': psa_id, **{d: t.get(d) for d in DAY_LABELS}})

        dt = psa.get('day_types', {})
        type_rows.append({'PSA': psa_id, **{d: dt.get(d) for d in DAY_LABELS}})

    result = {fk: pd.DataFrame(rows) for fk, rows in frames.items()}
    result['trend'] = pd.DataFrame(trend_rows)
    result['types'] = pd.DataFrame(type_rows)   # O/F per day slot per PSA
    return result
