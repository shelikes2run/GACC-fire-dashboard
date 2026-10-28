"""
build_wx.py — national GACC fire weather data for the GACC Fire Weather app (docs/wx/), the successor of the Streamlit
dashboard. Same PSA / key-RAWS lists (gacc_config.py) and the same 2005–2024 climatology method; no keys (public FEMS
climatology downloads).

  python site/build_wx.py baseline OUT CACHE   # 2005-2024 PSA percentiles incl. dry-side fuel moisture (slow, run rarely)
  python site/build_wx.py current  OUT         # last 30 days observed + 7-day forecast per PSA (twice a day)

OUT is a checkout of the `wx-data` branch:
  baseline.json            {meta, psa: {"<ABBREV>|<PSA>": {fuel_model, n_days, <field>: {mean, p3,p5,p10,p20, p80,p90,p95,p97}}}}
  index.json               generated time, GACC list with PSAs, day labels, field metadata
  gacc/<ABBREV>.json       per PSA: series (dates, O/F type, every field), today / next-day values, alert levels, stations
  psas.geojson             PSA polygons with today's value and alert level per field + popup_html (AGOL map layer)
"""
from __future__ import annotations

import io
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
sys.path[:0] = [str(ROOT), str(ROOT / 'normals'), str(ROOT / 'site')]
import ca_normals as cn            # noqa: E402  (FEMS download helpers)
from gacc_config import GACC_CONFIG  # noqa: E402

log = logging.getLogger('wx')
TZ = ZoneInfo('America/Denver')
CLIMO = (2005, 2024)
FIELDS = ['erc', 'ic', 'bi', 'sc', 'fm1', 'fm10', 'fm100', 'fm1000', 'kbdi', 'gsi', 'herb', 'woody']
MOIST = {'fm1', 'fm10', 'fm100', 'fm1000', 'herb', 'woody'}            # low = dry = danger
PRIMARY = ['erc', 'bi', 'ic', 'sc', 'fm100', 'kbdi']
META = {'erc': ('ERC', 'Energy Release Component'), 'ic': ('IC', 'Ignition Component'), 'bi': ('BI', 'Burning Index'),
        'sc': ('SC', 'Spread Component'), 'fm1': ('1-hr FM', '1-hour fuel moisture (%)'), 'fm10': ('10-hr FM', '10-hour fuel moisture (%)'),
        'fm100': ('100-hr FM', '100-hour fuel moisture (%)'), 'fm1000': ('1000-hr FM', '1000-hour fuel moisture (%)'),
        'kbdi': ('KBDI', 'Keetch-Byram Drought Index'), 'gsi': ('GSI', 'Growing Season Index'),
        'herb': ('Herb FM', 'Herbaceous fuel moisture (%)'), 'woody': ('Woody FM', 'Woody fuel moisture (%)')}
HI_P, LO_P = [80, 90, 95, 97], [20, 10, 5, 3]
PSA_LAYER = ('https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/'
             'DMP_Predictive_Service_Area__PSA_Boundaries_Public/FeatureServer/0')
LEVELS = ['Normal', 'Elevated', 'High', 'Critical']          # ≥90th / ≥95th / ≥97th (fuel moisture: ≤10th / ≤5th / ≤3rd)
LVL_COL = {'Normal': '#2e7d32', 'Elevated': '#f9c80e', 'High': '#ff7a00', 'Critical': '#e0115f', 'No data': '#9aa0a6'}
SITE = 'https://shelikes2run.github.io/GACC-fire-dashboard/'


def gaccs():
    """[(abbrev, name, {psa: {fuel_model, stations}})] for GACCs with key stations (AICC has none)."""
    out = []
    for name, g in GACC_CONFIG.items():
        psas = {p: v for p, v in g['psas'].items() if v.get('stations')}
        if psas:
            out.append((g['abbrev'], name, psas))
    return out


def pairs():
    """Station × fuel model pairs needed (a station can serve PSAs with different fuel models)."""
    s = {(int(sid), v['fuel_model'].upper()) for _, _, psas in gaccs() for v in psas.values() for sid in v['stations']}
    return pd.DataFrame(sorted(s), columns=['stationId', 'FuelModel'])


# ── FEMS reads ────────────────────────────────────────────────────────────────
def _read(txt: str, want: set, observed_only: bool) -> pd.DataFrame:
    if not txt or len(txt) < 50:
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(txt))
    df.columns = df.columns.str.strip()
    if 'ObservationTime' not in df.columns:
        return pd.DataFrame()
    typ = df['NFDRType'].astype(str).str.upper()
    keep = typ == 'O' if observed_only else typ.isin(['O', 'F'])
    df = df[keep]
    out = pd.DataFrame({'stationId': pd.to_numeric(df['StationId'], errors='coerce'),
                        'fm': df['FuelModel'].astype(str).str.upper(),
                        'date': pd.to_datetime(df['ObservationTime'], errors='coerce').dt.normalize(),
                        'type': typ[keep].values})
    for k in FIELDS:
        c = cn.FIELD_COLS.get(k)
        out[k] = pd.to_numeric(df[c], errors='coerce').astype('float32') if c in df.columns else np.float32(np.nan)
    out = out.dropna(subset=['stationId', 'date'])
    out['stationId'] = out['stationId'].astype(int)
    out = out.loc[np.array([p in want for p in zip(out['stationId'], out['fm'])], dtype=bool)]
    for k in FIELDS:
        out.loc[out[k] < 0, k] = np.nan
    return out


def psa_daily(st: pd.DataFrame, prefer_obs: bool = True) -> dict:
    """{(abbrev, psa): DataFrame indexed by date with FIELDS (+ type)}: mean of the PSA's key stations each day,
    observed rows preferred over forecast rows for the same day (as the Streamlit app did)."""
    out = {}
    for ab, _, psas in gaccs():
        for psa, v in psas.items():
            fm = v['fuel_model'].upper()
            sub = st[st['stationId'].isin(v['stations']) & (st['fm'] == fm)]
            if sub.empty:
                continue
            if 'type' in sub and prefer_obs:
                g = sub.groupby(['date', 'type'])[FIELDS].mean().reset_index()
                g['r'] = (g['type'] == 'F').astype(int)
                g = g.sort_values(['date', 'r']).drop_duplicates('date').drop(columns='r').set_index('date')
                g['n'] = sub.groupby('date')['stationId'].nunique()
            else:
                g = sub.groupby('date')[FIELDS].mean()
            out[(ab, psa)] = g.sort_index()
    return out


# ── baseline (2005-2024, observed) ────────────────────────────────────────────
def build_baseline(out: Path, cache: Path):
    pr = pairs()
    raw = cache / 'wx_raw'
    for fm, grp in pr.groupby('FuelModel'):            # one fuel model per request keeps the downloads small
        cn._download(cn.FEMS_URL, f'nfdr{fm}', grp['stationId'].tolist(), [fm], CLIMO[0], CLIMO[1], raw, workers=6)
    want = set(zip(pr['stationId'], pr['FuelModel']))
    frames = []
    for f in sorted(raw.glob('nfdr*.csv')):
        d = _read(f.read_text(encoding='utf-8', errors='ignore') if f.stat().st_size >= 50 else '', want, True)
        if len(d):
            frames.append(d.drop(columns='type'))
    st = pd.concat(frames, ignore_index=True)
    st = st[st['date'].dt.year.between(*CLIMO)]
    st = st.groupby(['stationId', 'fm', 'date'], as_index=False)[FIELDS].mean()
    log.info('baseline: %d station-days, %d stations', len(st), st['stationId'].nunique())
    daily = psa_daily(st, prefer_obs=False)
    psa = {}
    for (ab, p), d in daily.items():
        fm = next(v['fuel_model'] for a, _, ps in gaccs() if a == ab for q, v in ps.items() if q == p)
        e = {'fuel_model': fm, 'n_days': int(d['erc'].notna().sum()), 'stations': next(v['stations'] for a, _, ps in gaccs()
                                                                                         if a == ab for q, v in ps.items() if q == p)}
        for k in FIELDS:
            x = d[k].dropna().to_numpy(float)
            if len(x) < 365:
                continue
            e[k] = {'mean': round(float(x.mean()), 1), **{f'p{q}': round(float(np.percentile(x, q)), 1) for q in LO_P + HI_P}}
        psa[f'{ab}|{p}'] = e
    doc = {'meta': {'climo_start': CLIMO[0], 'climo_end': CLIMO[1], 'percentiles_high': HI_P, 'percentiles_low': LO_P,
                    'method': 'daily mean of the PSA key RAWS (observed, FEMS daily summary), all days of the year',
                    'generated': datetime.now(TZ).strftime('%Y-%m-%d'), 'n_psa': len(psa)}, 'psa': psa}
    (out / 'baseline.json').write_text(json.dumps(doc, separators=(',', ':')))
    log.info('baseline: %d PSAs → %s', len(psa), out / 'baseline.json')


def load_baseline(out: Path) -> dict:
    """wx-data baseline.json (built above) if present, else the Streamlit app's gacc_climo_baseline.json (high side only)."""
    p = out / 'baseline.json'
    if p.exists():
        return json.loads(p.read_text())['psa']
    old = json.loads((ROOT / 'gacc_climo_baseline.json').read_text())['psa']
    ab = {name: g['abbrev'] for name, g in GACC_CONFIG.items()}
    return {f"{ab.get(k.split('|')[0], k.split('|')[0])}|{k.split('|')[1]}": v for k, v in old.items()}


def level(k, v, b):
    """Alert level of value v for field k against its PSA baseline entry b."""
    if v is None or b is None or (isinstance(v, float) and np.isnan(v)):
        return 'No data'
    if k in MOIST:
        if b.get('p3') is None:
            return 'No data'
        return 'Critical' if v <= b['p3'] else 'High' if v <= b['p5'] else 'Elevated' if v <= b['p10'] else 'Normal'
    return 'Critical' if v >= b['p97'] else 'High' if v >= b['p95'] else 'Elevated' if v >= b['p90'] else 'Normal'


# ── current (twice a day) ─────────────────────────────────────────────────────
def fetch_current(pr: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    want = set(zip(pr['stationId'], pr['FuelModel']))
    jobs = [(chunk, [fm]) for fm, grp in pr.groupby('FuelModel') for chunk in cn._batches(grp['stationId'], 20)]

    def one(job):
        chunk, fms = job
        return _read(cn._fems_get(cn.FEMS_URL, chunk, start, end, fms, dataset='all'), want, False)
    with ThreadPoolExecutor(max_workers=6) as pool:
        frames = list(pool.map(one, jobs))
    st = pd.concat([f for f in frames if len(f)], ignore_index=True)
    log.info('current: %d station-days (%d stations), %s → %s', len(st), st['stationId'].nunique(), start, end)
    return st


def psa_polygons() -> dict:
    feats, off = [], 0
    while True:
        r = requests.get(PSA_LAYER + '/query', params={'where': '1=1', 'outFields': 'PSANationalCode,PSANAME,GACCName,GACCUnitID',
                         'outSR': 4326, 'f': 'geojson', 'maxAllowableOffset': 0.005, 'geometryPrecision': 4,
                         'resultOffset': off, 'resultRecordCount': 200}, timeout=180).json()
        fs = r.get('features', [])
        feats += fs
        if len(fs) < 200:
            break
        off += len(fs)
    return {f['properties']['PSANationalCode']: f for f in feats}


def _r(x, k=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 2 if k == 2 else 1)


def popup(ab, gname, psa, pname, rec):
    td, nx = rec['today'], rec['next']
    rows = []
    for k in ['erc', 'bi', 'ic', 'sc', 'fm1', 'fm10', 'fm100', 'fm1000', 'kbdi']:
        b = rec['baseline'].get(k) or {}
        def cell(v, lv):
            bg = LVL_COL.get(lv, '#9aa0a6'); fg = '#111' if lv in ('Elevated',) else '#fff'
            return (f'<td style="text-align:center">{"–" if v is None else (f"{v:.0f}" if abs(v) >= 100 else f"{v:.1f}")}<br>'
                    f'<span style="padding:0 5px;border-radius:3px;background:{bg};color:{fg};font-size:10px">{lv}</span></td>')
        thr = (f'{b.get("p10", "–")} / {b.get("p5", "–")} / {b.get("p3", "–")} (≤10th/5th/3rd)' if k in MOIST
               else f'{b.get("p90", "–")} / {b.get("p95", "–")} / {b.get("p97", "–")} (≥90th/95th/97th)') if b else 'no baseline'
        rows.append(f'<tr><td><b>{META[k][0]}</b><br><span style="color:#888;font-size:10px">{thr}</span></td>'
                    f'{cell(td["v"].get(k), td["lvl"].get(k))}{cell(nx["v"].get(k), nx["lvl"].get(k))}</tr>')
    link = f'{SITE}wx/psa.html?psa={psa}'
    return (f'<div style="font-size:12px;margin-bottom:4px"><b>{psa} {pname}</b> · {gname} ({ab}) · fuel model {rec["fuel_model"]} · '
            f'{len(rec["stations"])} key RAWS</div>'
            f'<table style="width:100%;font-size:12px;border-collapse:collapse"><tr><th style="text-align:left">Index</th>'
            f'<th>{td["label"]}<br>{td["date"] or ""}</th><th>{nx["label"]}<br>{nx["date"] or ""}</th></tr>{"".join(rows)}</table>'
            f'<p style="font-size:12px;margin:6px 0 0"><a href="{link}" target="_blank">PSA charts ▸</a> · '
            f'<a href="{SITE}wx/gacc.html?gacc={ab}" target="_blank">{ab} overview ▸</a></p>'
            f'<p style="font-size:11px;color:#666;margin:4px 0 0">Mean of the PSA key RAWS (FEMS daily summaries). Levels vs the PSA\'s '
            f'2005–2024 climatology: fire indices ≥90th Elevated, ≥95th High, ≥97th Critical; fuel moisture ≤10th / ≤5th / ≤3rd.</p>')


def build_current(out: Path):
    now = datetime.now(TZ)
    today = pd.Timestamp(now.date())
    start, end = (today - pd.Timedelta(days=30)).strftime('%Y-%m-%d'), (today + pd.Timedelta(days=8)).strftime('%Y-%m-%d')
    base = load_baseline(out)
    st = fetch_current(pairs(), start, end)
    daily = psa_daily(st)
    names = {}
    try:
        polys = psa_polygons()
        names = {k: f['properties'] for k, f in polys.items()}
    except Exception as e:
        log.warning('PSA polygons unavailable: %s', e)
        polys = {}
    (out / 'gacc').mkdir(parents=True, exist_ok=True)
    idx, feats = [], []
    for ab, gname, psas in gaccs():
        doc = {'abbrev': ab, 'name': gname, 'generated': now.strftime('%Y-%m-%d %H:%M %Z'), 'psas': {}}
        for psa, v in psas.items():
            b = base.get(f'{ab}|{psa}', {})
            d = daily.get((ab, psa))
            rec = {'psa': psa, 'name': (names.get(psa) or {}).get('PSANAME', ''), 'fuel_model': v['fuel_model'],
                   'stations': v['stations'], 'baseline': {k: b.get(k) for k in FIELDS if b.get(k)}, 'n_days_climo': b.get('n_days')}
            if d is not None and len(d):
                obs = d[(d['type'] == 'O') & (d.index <= today)]
                fc = d[(d['type'] == 'F') & (d.index >= today)]
                o_row = obs.iloc[-1] if len(obs) else None
                f_rows = [fc.iloc[i] for i in range(min(2, len(fc)))]
                # "today" = today's forecast (else latest observed), "next" = tomorrow's forecast — as the Streamlit cards
                t_row = d.loc[today] if today in d.index else o_row
                n_row = d.loc[today + pd.Timedelta(days=1)] if (today + pd.Timedelta(days=1)) in d.index else None
                def snap(r, label, date):
                    vals = {k: (None if r is None else _r(r[k], 2 if k == 'gsi' else 1)) for k in FIELDS}
                    return {'label': label, 'date': date, 'v': vals, 'lvl': {k: level(k, vals[k], b.get(k)) for k in FIELDS}}
                rec['today'] = snap(t_row, 'Today', today.strftime('%Y-%m-%d') if t_row is not None else None)
                rec['next'] = snap(n_row, 'Tomorrow', (today + pd.Timedelta(days=1)).strftime('%Y-%m-%d') if n_row is not None else None)
                rec['latest_obs'] = None if o_row is None else obs.index[-1].strftime('%Y-%m-%d')
                rec['series'] = {'dates': [x.strftime('%Y-%m-%d') for x in d.index], 'type': d['type'].tolist(),
                                 'n': [None if pd.isna(x) else int(x) for x in d['n']],
                                 **{k: [_r(x, 2 if k == 'gsi' else 1) for x in d[k]] for k in FIELDS}}
                # station table: latest observed and next forecast per key station
                rows = []
                for sid in v['stations']:
                    s = st[(st['stationId'] == sid) & (st['fm'] == v['fuel_model'].upper())].sort_values('date')
                    so, sf = s[(s['type'] == 'O') & (s['date'] <= today)].tail(1), s[(s['type'] == 'F') & (s['date'] >= today)].head(1)
                    rows.append({'stationId': sid, **{f'{t}_{k}': (None if r.empty else _r(r.iloc[0][k], 2 if k == 'gsi' else 1))
                                                       for t, r in (('o', so), ('f', sf)) for k in ('erc', 'bi', 'ic', 'fm100', 'kbdi')},
                                 'o_date': None if so.empty else so.iloc[0]['date'].strftime('%Y-%m-%d')})
                rec['station_table'] = rows
            else:
                empty = {'label': 'Today', 'date': None, 'v': {k: None for k in FIELDS}, 'lvl': {k: 'No data' for k in FIELDS}}
                rec['today'], rec['next'] = empty, {**empty, 'label': 'Tomorrow'}
            doc['psas'][psa] = rec
            p = polys.get(psa)
            if p:
                props = {'psa': psa, 'name': rec['name'], 'gacc': ab, 'gacc_name': gname, 'fuel_model': v['fuel_model'],
                         'n_stations': len(v['stations']), 'date': rec['today']['date']}
                for k in FIELDS:
                    props[f'{k}_td'] = rec['today']['v'].get(k)
                    props[f'{k}_lvl'] = rec['today']['lvl'].get(k)
                    props[f'{k}_nx_lvl'] = rec['next']['lvl'].get(k)
                props['popup_html'] = popup(ab, gname, psa, rec['name'], rec)
                feats.append({'type': 'Feature', 'properties': props, 'geometry': p['geometry']})
        (out / 'gacc' / f'{ab}.json').write_text(json.dumps(doc, separators=(',', ':'), allow_nan=False))
        lv = {k: {L: sum(1 for r in doc['psas'].values() if r['today']['lvl'].get(k) == L) for L in LEVELS + ['No data']} for k in PRIMARY}
        idx.append({'abbrev': ab, 'name': gname, 'psas': sorted(psas), 'levels_today': lv})
    (out / 'psas.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': feats}, separators=(',', ':'), allow_nan=False))
    (out / 'index.json').write_text(json.dumps({
        'generated': now.strftime('%Y-%m-%d %H:%M %Z'), 'today': today.strftime('%Y-%m-%d'), 'window': [start, end],
        'climo': CLIMO, 'baseline_source': 'wx-data baseline.json' if (out / 'baseline.json').exists() else 'gacc_climo_baseline.json (Streamlit)',
        'fields': {k: {'short': META[k][0], 'label': META[k][1], 'moisture': k in MOIST} for k in FIELDS}, 'primary': PRIMARY,
        'gaccs': idx}, separators=(',', ':')))
    log.info('current: %d GACCs, %d PSA polygons → %s', len(idx), len(feats), out)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
    mode, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    if mode == 'baseline':
        build_baseline(out, Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / 'wx_cache')
    else:
        build_current(out)
