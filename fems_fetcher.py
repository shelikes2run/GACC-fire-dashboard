"""
fems_fetcher.py
───────────────
Fetches 7-day ERC / FM / BI / IC forecast from FEMS REST API.
Percentile thresholds come from gacc_climo_baseline.json (pre-built offline).
Only the live forecast query hits the network.
"""

import os, json, logging, time
from datetime import datetime, timedelta, date
from statistics import mean
from pathlib import Path
import requests

FEMS_API_KEY  = os.getenv('FEMS_API_KEY',  '')
FEMS_USERNAME = os.getenv('FEMS_USERNAME', '')
FEMS_BASE     = 'https://fems.fs2c.usda.gov/api/ext-climatology/download-weather'

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('fems_fetcher')


def _headers():
    if not FEMS_API_KEY:
        raise EnvironmentError('FEMS_API_KEY not set')
    return {'x-api-key': FEMS_API_KEY, 'x-user-email': FEMS_USERNAME, 'Accept': 'text/csv'}


def load_baseline(path='gacc_climo_baseline.json'):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"'{path}' not found. Run GACC_Climo_Download.ipynb first."
        )
    return json.loads(p.read_text())


def load_gacc_config():
    import importlib.util
    spec = importlib.util.spec_from_file_location('gacc_config', 'gacc_config.py')
    gc   = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gc)
    return gc.GACC_CONFIG


def _find_col(df, candidates):
    lmap = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in lmap: return lmap[c.lower()]
    for c in candidates:
        for col in df.columns:
            if c.lower() in col.lower(): return col
    return None


def fetch_station_forecast(station_id, start_date, end_date, retries=3):
    url = (f'{FEMS_BASE}?stationIds={station_id}'
           f'&startDate={start_date}T00:00:00Z&endDate={end_date}T23:59:59Z'
           f'&dataset=all&dataFormat=csv&dataIncrement=daily')
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=_headers(), timeout=25)
            if r.status_code == 404: return None
            r.raise_for_status()
            if not r.text.strip() or len(r.text) < 50: return None

            import pandas as pd
            from io import StringIO
            df = pd.read_csv(StringIO(r.text))
            df.columns = df.columns.str.strip().str.lower()

            date_col = _find_col(df, ['date','obs_date','summary_date'])
            erc_col  = _find_col(df, ['energy_release_component_max','erc_max','erc'])
            fm_col   = _find_col(df, ['hun_hr_tl_fuel_moisture_min','100hr_fm_min','fm100','f100'])
            bi_col   = _find_col(df, ['burning_index_max','bi_max','bi'])
            ic_col   = _find_col(df, ['ignition_component_max','ic_max','ic'])
            if date_col is None: return None

            result = {}
            for _, row in df.iterrows():
                try:
                    d = str(pd.to_datetime(row[date_col]).date())
                    result[d] = {
                        'erc': float(row[erc_col]) if erc_col and pd.notna(row[erc_col]) else None,
                        'fm':  float(row[fm_col])  if fm_col  and pd.notna(row[fm_col])  else None,
                        'bi':  float(row[bi_col])  if bi_col  and pd.notna(row[bi_col])  else None,
                        'ic':  float(row[ic_col])  if ic_col  and pd.notna(row[ic_col])  else None,
                    }
                except Exception:
                    continue
            return result
        except Exception as e:
            if attempt < retries: time.sleep(2 * attempt)
            else:
                log.warning(f'  station {station_id} failed: {e}')
                return None


def _safe_mean(vals):
    v = [x for x in vals if x is not None and x > 0]
    return round(mean(v), 1) if v else None


def _day_map():
    today     = date.today()
    yesterday = today - timedelta(days=1)
    def nwd(d, wd):
        days = (wd - d.weekday()) % 7 or 7
        return d + timedelta(days=days)
    return {
        'yd':  str(yesterday),
        'td':  str(today),
        'Wed': str(nwd(today, 2)),
        'Thu': str(nwd(today, 3)),
        'Fri': str(nwd(today, 4)),
        'Sat': str(nwd(today, 5)),
        'Sun': str(nwd(today, 6)),
        'Mon': str(nwd(today, 0)),
    }


def fetch_psa_forecast(gacc_name, psa_ids=None, output_path='gacc_data.json',
                       baseline_path='gacc_climo_baseline.json'):
    start = time.time()
    gacc_config = load_gacc_config()
    baseline    = load_baseline(baseline_path)

    psas_cfg = gacc_config.get(gacc_name, {}).get('psas', {})
    if psa_ids:
        psas_cfg = {k: v for k, v in psas_cfg.items() if k in psa_ids}

    all_sids = sorted(set(s for v in psas_cfg.values() for s in v.get('stations', [])))
    dm = _day_map()
    start_str = min(dm.values())
    end_str   = max(dm.values())

    log.info(f'Fetching {gacc_name} — {len(all_sids)} stations  {start_str}→{end_str}')
    forecasts = {}
    for i, sid in enumerate(all_sids, 1):
        data = fetch_station_forecast(sid, start_str, end_str)
        if data: forecasts[sid] = data
        if i % 25 == 0: log.info(f'  {i}/{len(all_sids)}')
        time.sleep(0.3)
    log.info(f'  ✓ data for {len(forecasts)}/{len(all_sids)} stations')

    psa_out = {}
    for psa_id, info in psas_cfg.items():
        sids = info.get('stations', [])
        bkey = f'{gacc_name}|{psa_id}'
        bentry = baseline.get('psa', {}).get(bkey, {})

        # Per-field day averages
        def day_avgs(field):
            out = {}
            for label, target in dm.items():
                vals = []
                for sid in sids:
                    if sid in forecasts and target in forecasts[sid]:
                        v = forecasts[sid][target].get(field)
                        if v is not None and v > 0: vals.append(v)
                out[label] = _safe_mean(vals)
            return out

        erc_d = day_avgs('erc')
        fm_d  = day_avgs('fm')
        bi_d  = day_avgs('bi')
        ic_d  = day_avgs('ic')

        today_erc = erc_d.get('td') or 0
        trend = {
            label: (round((v - today_erc), 1) if v is not None else None)
            for label, v in erc_d.items() if label != 'yd'
        }
        trend['td'] = 0.0

        def attach_baseline(day_dict, field_key):
            b = bentry.get(field_key, {})
            return {**day_dict,
                    'Climo_Mean': b.get('mean'),
                    'P80': b.get('p80'), 'P90': b.get('p90'),
                    'P95': b.get('p95'), 'P97': b.get('p97')}

        psa_out[psa_id] = {
            'psa': psa_id,
            'fuel_model': info.get('fuel_model', 'Y'),
            'day_map': dm,
            'ERC': attach_baseline(erc_d, 'erc'),
            'FM':  attach_baseline(fm_d,  'fm'),
            'BI':  attach_baseline(bi_d,  'bi'),
            'IC':  attach_baseline(ic_d,  'ic'),
            'ERC_trend': trend,
            'stations_total':     len(sids),
            'stations_with_data': sum(1 for s in sids if s in forecasts),
        }

    output = {
        'meta': {
            'gacc':            gacc_name,
            'fetched_at':      datetime.utcnow().isoformat() + 'Z',
            'fetch_date':      str(date.today()),
            'climo_start':     baseline.get('meta', {}).get('climo_start', 2005),
            'climo_end':       baseline.get('meta', {}).get('climo_end', 2020),
            'percentiles':     baseline.get('meta', {}).get('percentiles', [80,90,95,97]),
            'psa_count':       len(psa_out),
        },
        'psa': psa_out,
    }
    Path(output_path).write_text(json.dumps(output, indent=2))
    log.info(f'✓ Done {time.time()-start:.1f}s → {output_path}')
    return output


def json_to_dataframes(data):
    import pandas as pd
    erc_rows, fm_rows, bi_rows, ic_rows, trend_rows = [], [], [], [], []
    day_cols = ['yd','td','Wed','Thu','Fri','Sat','Sun','Mon']

    for psa_id, psa in data['psa'].items():
        def make_row(field_data, fname):
            row = {'PSA': psa_id, 'Field': fname}
            for d in day_cols: row[d] = field_data.get(d)
            row['Climo_Mean'] = field_data.get('Climo_Mean')
            for p in [80,90,95,97]: row[f'P{p}'] = field_data.get(f'P{p}')
            return row

        erc_rows.append(make_row(psa['ERC'], 'ERC'))
        fm_rows.append(make_row(psa['FM'],  'FM'))
        bi_rows.append(make_row(psa['BI'],  'BI'))
        ic_rows.append(make_row(psa['IC'],  'IC'))
        t = psa['ERC_trend']
        trend_rows.append({'PSA': psa_id, 'Field': 'ERC',
            'td': t.get('td',0), 'Wed':t.get('Wed'), 'Thu':t.get('Thu'),
            'Fri':t.get('Fri'), 'Sat':t.get('Sat'), 'Sun':t.get('Sun'), 'Mon':t.get('Mon')})

    return (pd.DataFrame(erc_rows), pd.DataFrame(fm_rows),
            pd.DataFrame(bi_rows),  pd.DataFrame(ic_rows),
            pd.DataFrame(trend_rows))
