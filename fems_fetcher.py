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
DAY_LABELS = ['yd', 'td', 'D+1', 'D+2', 'D+3', 'D+4', 'D+5', 'D+6']


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

            # Store rows keyed by (date, ntype) then prefer 'O' over 'F'
            # when both exist for the same date (e.g. today has both observed
            # and a model forecast — we always want the observed value)
            raw = {}   # (date_str, ntype) → entry
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
                    raw[(d, ntype)] = entry
                except Exception:
                    continue

            # Merge: for each date prefer 'O'; fall back to 'F' if no observed row
            result = {}
            all_dates = {d for d, _ in raw}
            for d in all_dates:
                if (d, 'O') in raw:
                    result[d] = raw[(d, 'O')]
                elif (d, 'F') in raw:
                    result[d] = raw[(d, 'F')]

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
    Returns {label: date_string} for the 8 display columns using rolling
    day offsets (+0 … +6) rather than weekday-name lookups.

    Fixes two bugs with the old weekday-name approach:
      1. Stale cache: frozen day_map showed "Today=Tuesday" on Wednesday
      2. Same-day gap: next_weekday(Wed, Wed) jumped +7, leaving a blank
         between Today and the first forecast slot.

    Labels are yd / td / D+1 … D+6.  app.py converts D+N to readable names
    at render time using _day_label(), so axis labels are always correct
    regardless of when the cache was written.
    """
    today = date.today()
    return {
        'yd':  str(today - timedelta(days=1)),
        'td':  str(today),
        'D+1': str(today + timedelta(days=1)),
        'D+2': str(today + timedelta(days=2)),
        'D+3': str(today + timedelta(days=3)),
        'D+4': str(today + timedelta(days=4)),
        'D+5': str(today + timedelta(days=5)),
        'D+6': str(today + timedelta(days=6)),
    }


def _day_label(date_str: str) -> str:
    """
    Convert a YYYY-MM-DD string to a human-readable chart label.
    Called by app.py at render time — always reflects today's actual date.

    e.g. if today is Wednesday:
      yesterday  → 'Yesterday'
      today      → 'Today'
      D+1        → 'Thu'
      D+6        → 'Tue'
    """
    from datetime import date as _date
    DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    try:
        d     = _date.fromisoformat(date_str)
        today = _date.today()
        delta = (d - today).days
        if delta == -1: return 'Yesterday'
        if delta == 0:  return 'Today'
        return DAY_NAMES[d.weekday()]
    except Exception:
        return date_str


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

    # Parallel fetch — 8 workers keeps us well within FEMS rate limits while
    # cutting SACC (260 stations) from ~130s serial → ~20s parallel
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch_one(sid):
        result = fetch_station_forecast(
            sid, station_fuel_map[sid], start_str, end_str)
        return sid, result

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
                log.info('  %d / %d stations fetched', completed, len(all_sids))

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
        for lbl in ['D+1', 'D+2', 'D+3', 'D+4', 'D+5', 'D+6']:
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

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(output, indent=2), encoding='utf-8')
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
            **{d: t.get(d) for d in ['td', 'D+1', 'D+2', 'D+3', 'D+4', 'D+5', 'D+6']}
        })

    result = {fk: pd.DataFrame(rows) for fk, rows in frames.items()}
    result['trend'] = pd.DataFrame(trend_rows)
    return result


# ── Historical observed data (for Trend + Heatmap tabs) ───────────────────────

def fetch_psa_history(gacc_name, days: int = 30,
                      output_path: str = None,
                      baseline_path: str = 'gacc_climo_baseline.json'):
    """
    Fetch the last `days` days of OBSERVED (NFDRType=O) NFDR data for every
    PSA in the GACC.  Used by the Trend and Heatmap tabs.

    Separate from fetch_psa_forecast() — this window is purely historical
    (yesterday-N → yesterday) so it never contains forecast rows.

    Returns a dict:
      {
        'meta': { gacc, abbrev, start_date, end_date, days, fetched_at, ... },
        'psa':  {
          psa_id: {
            'dates':  ['2026-02-23', '2026-02-24', ...],   # ascending
            'erc':    [29.1, 30.4, ...],                    # NaN → None
            'ic':     [...],
            'bi':     [...],
            'sc':     [...],
            'fm100':  [...],
            'p90_erc':  44.7,   # climo threshold for this PSA
            'p97_erc':  50.5,
            'mean_erc': 21.0,
          }
        }
      }
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    t0          = time.time()
    gacc_config = load_gacc_config()
    baseline    = load_baseline(baseline_path)

    psas_cfg = gacc_config.get(gacc_name, {}).get('psas', {})

    station_fuel_map = {}
    for info in psas_cfg.values():
        fm = info.get('fuel_model', 'Y')
        for s in info.get('stations', []):
            station_fuel_map[s] = fm

    all_sids  = sorted(station_fuel_map)
    yesterday = date.today() - timedelta(days=1)
    start_dt  = yesterday - timedelta(days=days - 1)
    start_str = str(start_dt)
    end_str   = str(yesterday)

    abbrev = gacc_config[gacc_name]['abbrev']
    log.info('History %s — %d stations  %s → %s',
             abbrev, len(all_sids), start_str, end_str)

    # Fetch all stations in parallel (observed-only window)
    def _fetch_one(sid):
        return sid, fetch_station_forecast(
            sid, station_fuel_map[sid], start_str, end_str)

    forecasts = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        for sid, data_s in pool.map(lambda s: _fetch_one(s), all_sids):
            if data_s:
                # Keep only observed rows
                forecasts[sid] = {
                    d: e for d, e in data_s.items()
                    if e.get('type', 'O') == 'O'
                }

    log.info('  History: %d/%d stations returned data', len(forecasts), len(all_sids))

    # Build date range spine (all days in window)
    date_spine = [
        str(start_dt + timedelta(days=i))
        for i in range(days)
    ]

    # Aggregate to PSA level
    psa_out = {}
    for psa_id, info in psas_cfg.items():
        sids   = info.get('stations', [])
        bkey   = f'{gacc_name}|{psa_id}'
        bentry = baseline.get('psa', {}).get(bkey, {})

        psa_dates  = []
        field_vals = {fk: [] for fk in FIELD_COLS}

        for d in date_spine:
            day_field = {fk: [] for fk in FIELD_COLS}
            for sid in sids:
                if sid not in forecasts or d not in forecasts[sid]:
                    continue
                entry = forecasts[sid][d]
                for fk in FIELD_COLS:
                    v = entry.get(fk)
                    if v is not None and v >= 0:
                        day_field[fk].append(v)

            # Only include dates where at least one station has ERC data
            if day_field['erc']:
                psa_dates.append(d)
                for fk in FIELD_COLS:
                    vs = day_field[fk]
                    field_vals[fk].append(round(mean(vs), 1) if vs else None)

        if not psa_dates:
            continue

        entry_out = {
            'dates': psa_dates,
            **{fk: field_vals[fk] for fk in FIELD_COLS},
        }
        # Attach climo thresholds for quick lookup
        for fk in ('erc', 'ic', 'bi', 'sc', 'fm100'):
            b = bentry.get(fk, {})
            for pct in ('mean', 'p80', 'p90', 'p95', 'p97'):
                v = b.get(pct)
                if v is not None:
                    entry_out[f'{pct}_{fk}'] = v

        psa_out[psa_id] = entry_out

    output = {
        'meta': {
            'gacc':       gacc_name,
            'abbrev':     abbrev,
            'start_date': start_str,
            'end_date':   end_str,
            'days':       days,
            'fetched_at': datetime.utcnow().isoformat() + 'Z',
            'psa_count':  len(psa_out),
        },
        'psa': psa_out,
    }

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(output, indent=2), encoding='utf-8')
        log.info('History done in %.1fs → %s', time.time() - t0, output_path)

    return output
