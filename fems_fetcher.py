"""
fems_fetcher.py
───────────────
Fetches the live 7-day NFDR forecast using the confirmed endpoint:

  GET /api/ext-climatology/download-nfdr-daily-summary/
      ?dataset=all
      &startDate=YYYY-MM-DD
      &endDate=YYYY-MM-DD
      &dataFormat=csv
      &stationIds=XXXXX
      &fuelModels=Y

CSV columns returned (confirmed from nfdrsDailySummary sample file):
  StationName, ObservationTime, NFDRType (O=observed / F=forecast),
  FuelModel, 1HrFM, Min1HrFMTime, 10HrFM, Min10HrFMTime,
  100HrFM, Min100HrFMTime, 1000HrFM, Min1000HrFMTime,
  KBDI, GSI, WoodyFM, HerbFM, IC, MaxICTime, ERC, MaxERCTime,
  SC, MaxSCTime, BI, MaxBITime, NFDRQAFlag

Only the live 7-day window hits the network.
Percentile thresholds load from gacc_climo_baseline.json (offline file — instant).
"""

import os, json, logging, time
from datetime import datetime, timedelta, date
from pathlib import Path
from statistics import mean

import requests

FEMS_API_KEY  = os.getenv('FEMS_API_KEY',  '')
FEMS_USERNAME = os.getenv('FEMS_USERNAME', '')

# Confirmed working endpoint
FEMS_BASE = ('https://fems.fs2c.usda.gov'
             '/api/ext-climatology/download-nfdr-daily-summary/')

logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('fems_fetcher')

# Internal key  →  exact CSV column name from the API
FIELD_COLS = {
    'erc':    'ERC',
    'ic':     'IC',
    'bi':     'BI',
    'sc':     'SC',
    'fm1':    '1HrFM',
    'fm10':   '10HrFM',
    'fm100':  '100HrFM',
    'fm1000': '1000HrFM',
    'kbdi':   'KBDI',
}

# Day-label ordering used throughout the app
DAY_LABELS = ['yd', 'td', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']


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


def fetch_station_forecast(station_id, fuel_model, start_date, end_date, retries=3):
    """
    Fetch NFDR daily summary for one station over the given date range.

    Parameters
    ----------
    station_id  : int or str
    fuel_model  : str  e.g. 'Y', 'Z', 'X'
    start_date  : str  'YYYY-MM-DD'
    end_date    : str  'YYYY-MM-DD'

    Returns
    -------
    dict  {date_str: {'type': 'O'|'F', 'erc': float, 'ic': float, ...}}
    None  if station returns no data
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
            r = requests.get(url, headers=_headers(), timeout=25)
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

            result = {}
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
                    result[d] = entry
                except Exception:
                    continue

            return result or None

        except Exception as e:
            if attempt < retries:
                time.sleep(2 * attempt)
            else:
                log.warning('station %s failed after %d tries: %s',
                            station_id, retries, e)
                return None


def _safe_mean(vals):
    v = [x for x in vals if x is not None and x >= 0]
    return round(mean(v), 1) if v else None


def _build_day_map():
    """
    Returns {label: date_string} for yd / td / Wed … Mon.
    'yd' = yesterday (for observed), 'td' = today, rest = forecast days.
    """
    today     = date.today()
    yesterday = today - timedelta(days=1)

    def next_weekday(d, wd):   # wd: 0=Mon … 6=Sun
        days = (wd - d.weekday()) % 7 or 7
        return d + timedelta(days=days)

    return {
        'yd':  str(yesterday),
        'td':  str(today),
        'Wed': str(next_weekday(today, 2)),
        'Thu': str(next_weekday(today, 3)),
        'Fri': str(next_weekday(today, 4)),
        'Sat': str(next_weekday(today, 5)),
        'Sun': str(next_weekday(today, 6)),
        'Mon': str(next_weekday(today, 0)),
    }


def fetch_psa_forecast(gacc_name, psa_ids=None,
                       output_path='gacc_data.json',
                       baseline_path='gacc_climo_baseline.json'):
    """
    Full pipeline:
      1. Load pre-computed climo baseline (local JSON — no network call)
      2. Fetch live 7-day NFDR forecast for every station in the GACC
      3. Aggregate station readings to PSA-level day averages
      4. Attach climo thresholds (mean / P80 / P90 / P95 / P97) from baseline
      5. Write gacc_data.json cache and return the dict

    Parameters
    ----------
    gacc_name    : str  e.g. 'Great Basin Coordination Center'
    psa_ids      : list or None  — subset of PSAs; None = all PSAs in GACC
    output_path  : str  where to write the cache JSON
    baseline_path: str  path to gacc_climo_baseline.json
    """
    t0          = time.time()
    gacc_config = load_gacc_config()
    baseline    = load_baseline(baseline_path)

    psas_cfg = gacc_config.get(gacc_name, {}).get('psas', {})
    if psa_ids:
        psas_cfg = {k: v for k, v in psas_cfg.items() if k in psa_ids}

    # Build station → fuel model map for this GACC
    station_fuel_map = {}
    for info in psas_cfg.values():
        fm = info.get('fuel_model', 'Y')
        for s in info.get('stations', []):
            station_fuel_map[s] = fm

    all_sids  = sorted(station_fuel_map)
    day_map   = _build_day_map()
    start_str = min(day_map.values())
    end_str   = max(day_map.values())

    log.info('Fetching %s — %d stations  %s → %s',
             gacc_config[gacc_name]['abbrev'],
             len(all_sids), start_str, end_str)

    # Fetch all stations (observed + forecast rows come back in one request)
    forecasts = {}
    for i, sid in enumerate(all_sids, 1):
        data = fetch_station_forecast(
            sid, station_fuel_map[sid], start_str, end_str)
        if data:
            forecasts[sid] = data
        if i % 25 == 0:
            log.info('  %d / %d stations fetched', i, len(all_sids))
        time.sleep(0.3)

    log.info('  Got data for %d / %d stations',
             len(forecasts), len(all_sids))

    # Aggregate to PSA level
    psa_out = {}
    for psa_id, info in psas_cfg.items():
        sids   = info.get('stations', [])
        bkey   = f'{gacc_name}|{psa_id}'
        bentry = baseline.get('psa', {}).get(bkey, {})

        def day_avgs(fk):
            """Average one field across all stations for each day label."""
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

        # Build all field day-averages with climo thresholds attached
        field_data = {fk: attach_climo(day_avgs(fk), fk) for fk in FIELD_COLS}

        # ERC trend: delta vs today for each forecast day
        today_erc = field_data['erc'].get('td') or 0
        erc_trend = {'td': 0.0}
        for lbl in ['Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']:
            v = field_data['erc'].get(lbl)
            erc_trend[lbl] = round(v - today_erc, 1) if v is not None else None

        psa_out[psa_id] = {
            'psa':                psa_id,
            'fuel_model':         info.get('fuel_model', 'Y'),
            'day_map':            day_map,
            'stations_total':     len(sids),
            'stations_with_data': sum(1 for s in sids if s in forecasts),
            'ERC_trend':          erc_trend,
            **field_data,
        }

    output = {
        'meta': {
            'gacc':        gacc_name,
            'abbrev':      gacc_config[gacc_name]['abbrev'],
            'fetched_at':  datetime.utcnow().isoformat() + 'Z',
            'fetch_date':  str(date.today()),
            'climo_start': baseline['meta']['climo_start'],
            'climo_end':   baseline['meta']['climo_end'],
            'percentiles': baseline['meta']['percentiles'],
            'fields':      list(FIELD_COLS.keys()),
            'psa_count':   len(psa_out),
        },
        'psa': psa_out,
    }

    Path(output_path).write_text(
        json.dumps(output, indent=2), encoding='utf-8')
    log.info('Done in %.1f s → %s', time.time() - t0, output_path)
    return output


def json_to_dataframes(data):
    """
    Convert gacc_data.json into a dict of DataFrames, one per field key,
    plus a 'trend' DataFrame for ERC delta values.

    Each field DataFrame has columns:
      PSA, yd, td, Wed, Thu, Fri, Sat, Sun, Mon,
      Climo_Mean, P80, P90, P95, P97
    """
    import pandas as pd

    frames     = {fk: [] for fk in FIELD_COLS}
    trend_rows = []

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
        trend_rows.append({
            'PSA': psa_id,
            **{d: t.get(d) for d in ['td', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']}
        })

    result = {fk: pd.DataFrame(rows) for fk, rows in frames.items()}
    result['trend'] = pd.DataFrame(trend_rows)
    return result
