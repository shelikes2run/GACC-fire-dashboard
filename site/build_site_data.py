"""
build_site_data.py — data for the FDRA season-tracking site (docs/).

Two jobs, both keyless (public FEMS climatology downloads, batches of 20 stations):

  python site/build_site_data.py normals OUT   # 2006-2025 climatology per FDRA (slow, run rarely)
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
sys.path.insert(0, str(ROOT / 'site'))
from area import AREA  # noqa: E402

log = logging.getLogger('site')
MEMBERSHIP = ROOT / 'site' / 'fdra_station_membership_2026.csv'
POLYGONS = ROOT / 'docs' / 'data' / 'fdras.geojson'
PAL_RAW = AREA['raw'] + 'pal-data/'
NORMAL_YEARS = (2006, 2025)
TZ = ZoneInfo(AREA['timezone'])
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
def load_weights() -> dict:
    """{unit: {stationId: weight}} from the membership file's optional weight column (FDOP SIG weights;
    blank = 1). Seasonal units use the same key as cn.load_fdra_membership ('ENF-335 (peak)')."""
    m = pd.read_csv(MEMBERSHIP, dtype=str).fillna('')
    if 'weight' not in m:
        return {}
    out = {}
    for _, r in m[m['weight'].str.strip() != ''].iterrows():
        unit = r['fdra_id'] + (f" ({r['season']})" if r['season'] else '')
        out.setdefault(unit, {})[int(r['stationId'])] = float(r['weight'])
    return out


def wmean(df: pd.DataFrame, by, cols, wts: dict | None):
    """Mean of cols per group; with station weights a weighted mean over the stations that reported
    (FireFamily Plus SIG behaviour: a missing station drops out and the rest are re-weighted)."""
    if not wts:
        return df.groupby(by)[cols].mean()
    w = df['stationId'].map(lambda x: wts.get(int(x), 1.0)).astype(float)
    X = df[cols].astype(float)
    num = X.mul(w, axis=0).groupby([df[b] for b in ([by] if isinstance(by, str) else by)]).sum(min_count=1)
    den = X.notna().mul(w, axis=0).groupby([df[b] for b in ([by] if isinstance(by, str) else by)]).sum()
    return num / den.where(den > 0)


def fast_unit_daily(hist: pd.DataFrame, named: dict, weights: dict | None = None) -> pd.DataFrame:
    """cn.unit_daily for ~1,000 units: split history by fuel model once (weighted SIGs supported)."""
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
        d = wmean(sub, 'date', cn.INDICES, (weights or {}).get(uid))
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
    wts = load_weights()
    daily = fast_unit_daily(hist, named, {fm_name(u, fm, own[u]): wts[u] for (u, fm) in allm if u in wts})
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


def _pick(df: pd.DataFrame, cols, wts: dict | None = None):
    """Per date: (weighted) mean of observed rows if any, else of forecast rows."""
    g = wmean(df, ['date', 'type'], cols, wts).reset_index()
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


SITE = AREA['site_url']
FDOP_START = ROOT / 'docs' / 'data' / 'fdop_start.json'
WEIGHTS = {}         # unit -> {stationId: SIG weight} (FDOP weighted SIGs)
LATEST = {}          # (unit, fuel model) -> latest observed / next forecast values, climatology quantiles
LVL_COL = ['#2e7d32', '#7cb342', '#fbc02d', '#fb8c00', '#e53935', '#8e24aa']


def _esc(t):
    return str(t).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _lvl(v, breaks):
    """Class index for value v: a breakpoint is the top of its class (v above it moves up)."""
    if v is None:
        return None
    c = 0
    for i, b in enumerate(breaks):
        if v > b:
            c = i + 1
    return c


def _chip(name, c, n):
    if c is None:
        return '<span style="color:#888">–</span>'
    k = min(len(LVL_COL) - 1, round(c * (len(LVL_COL) - 2) / max(1, n - 1)) + (1 if c == n - 1 and n >= 5 else 0))
    fg = '#111' if k in (1, 2) else '#fff'
    return f'<span style="padding:1px 6px;border-radius:3px;background:{LVL_COL[k]};color:{fg};white-space:nowrap">{_esc(name)}</span>'


def _q(qs, p):
    return None if not qs or len(qs) != 101 else qs[p]


def fdra_tools(fid: str, start: dict):
    s = next((v for k, v in start.items() if k.upper() == fid.upper()), None)
    if not s:
        return None, []
    tools = s.get('tools') or [{'label': f'FDOP {i.upper()}', 'idx': i, 'fm': s.get('fm', 'Y'), 'breaks': b,
                                'classes': s.get('classes') or [str(n + 1) for n in range(len(b) + 1)]}
                               for i, b in (s.get('breaks') or {}).items()]
    mt = s.get('matrix_tools') or []
    if mt:   # matrix tools sit among the plain tools by their workbook order
        tools = sorted(tools + mt, key=lambda t: (t.get('order', 999)))
    return s, tools


ADJ_NAMES = ['Low', 'Moderate', 'High', 'Very High', 'Extreme']
ADJ_COL = [('#2e7d32', '#fff'), ('#1565c0', '#fff'), ('#fdd835', '#111'), ('#fb8c00', '#111'), ('#c62828', '#fff')]
# NFDRS / WIMS adjective class from staffing level (rows, 1-5) and ignition component (columns: 0-20, 21-45, 46-65, 66-80, 81-100)
ADJ_MATRIX = [[0, 0, 0, 1, 1], [0, 1, 1, 1, 2], [1, 1, 2, 2, 3], [1, 2, 3, 3, 4], [2, 3, 3, 4, 4]]


def _adj_chip(a, label=None):
    if a is None:
        return '<span style="color:#888">–</span>'
    bg, fg = ADJ_COL[a]
    return f'<span style="padding:1px 6px;border-radius:3px;background:{bg};color:{fg};white-space:nowrap">{label or ADJ_NAMES[a]}</span>'


def _adj_from(sl5, ic):
    if sl5 is None or ic is None:
        return None
    col = 0 if ic <= 20 else 1 if ic <= 45 else 2 if ic <= 65 else 3 if ic <= 80 else 4
    return ADJ_MATRIX[sl5][col]


def _to5(c, n):
    return None if c is None else int(round(c * 4 / max(1, n - 1)))


def _tool_pick(tools, pat, avoid=None):
    import re as _re
    c = [t for t in tools if _re.search(pat, t['label'], _re.I) and not (avoid and _re.search(avoid, t['label'], _re.I))]
    return c[0] if c else None


# ── decision tool evaluation: plain breakpoints, BI × ERC style matrices, multi-day windows, adjustments ──
# days = [O1, F1, F2, ...] (latest observed day, then forecast days from today). Column 1 of the popup is the
# tool's window as of today, column 2 the same window one day later (no window: O1 and F1).
VAR = {'f100': 'fm100', 'f1000': 'fm1000'}


def _win(tool):
    w = (tool.get('window') or '').upper().replace(' ', '')
    if not w:
        return [0]
    pos = []
    for part in w.split('+'):
        m = re.fullmatch(r'([OF])(\d)', part)
        if m:
            pos.append(0 if m.group(1) == 'O' else int(m.group(2)))
    return pos or [0]


def _wval(days, var, pos, shift):
    var = VAR.get(var, var)
    vals = []
    for q in pos:
        i = q + shift
        if i >= len(days) or not days[i] or days[i].get(var) is None:
            return None
        vals.append(days[i][var])
    return sum(vals) / len(vals)


def _adjust(c, n, tool, days, shift):
    """Apply one-class adjustments, e.g. {'var': 'tmax', 'op': '<', 'value': 57, 'adjust': -1, 'window': 'F1'}."""
    notes = []
    for a in tool.get('adjust') or []:
        v = _wval(days, a['var'], _win(a) if a.get('window') else _win(tool), shift)
        if v is None:
            continue
        hit = {'<': v < a['value'], '<=': v <= a['value'], '>': v > a['value'], '>=': v >= a['value']}[a['op']]
        if hit:
            c += a['adjust']; notes.append(f"{VAR_NAME.get(a['var'], a['var'].upper())} {v:.4g} {a['op']} {a['value']:g}")
    return max(0, min(n - 1, c)), notes


VAR_NAME = {'erc': 'ERC', 'bi': 'BI', 'ic': 'IC', 'sc': 'SC', 'kbdi': 'KBDI', 'gsi': 'GSI', 'tmax': 'Tmax', 'rhmin': 'RH min',
            'f100': '100-hr', 'fm100': '100-hr', 'f1000': '1000-hr', 'fm1000': '1000-hr'}


def tool_eval(t, L):
    """-> n, class names, [(value text, class or None, notes) for today, tomorrow], description of what is used."""
    pos = _win(t)
    wtxt = '' if pos == [0] else (' · ' + ('avg ' if len(pos) > 1 else '') + '+'.join(('O1' if q == 0 else f'F{q}') for q in pos))
    adj = '; '.join(f"{VAR_NAME.get(a['var'], a['var'])} {a['op']} {a['value']:g} → {a['adjust']:+d}" for a in t.get('adjust') or [])
    adj = f' · adjust: {adj}' if adj else ''
    if t.get('type') == 'matrix':
        R, C = t['rows'], t['cols']
        n = len(t['classes'])
        out = []
        for sh in (0, 1):
            rv = _wval(L(R['fm']).get('days') or [], R['idx'], pos, sh)
            cv = _wval(L(C['fm']).get('days') or [], C['idx'], pos, sh)
            if rv is None or cv is None:
                out.append(('–', None, [])); continue
            c = t['matrix'][_lvl(rv, R['breaks'])][_lvl(cv, C['breaks'])] - 1
            c, notes = _adjust(c, n, t, L(R['fm']).get('days') or [], sh)
            out.append((f"{VAR_NAME.get(R['idx'], R['idx'])} {rv:.3g} · {VAR_NAME.get(C['idx'], C['idx'])} {cv:.3g}", c, notes))
        used = (f"{VAR_NAME.get(R['idx'], R['idx'])}-{R['fm']} {' / '.join(f'{b:g}' for b in R['breaks'])} × "
                f"{VAR_NAME.get(C['idx'], C['idx'])}-{C['fm']} {' / '.join(f'{b:g}' for b in C['breaks'])} matrix{wtxt}{adj}")
        return n, t['classes'], out, used
    n = len(t['breaks']) + 1
    names = t.get('classes') if t.get('classes') and len(t['classes']) == n else [str(i + 1) for i in range(n)]
    days = L(t['fm']).get('days') or []
    out = []
    for sh in (0, 1):
        v = _wval(days, t['idx'], pos, sh)
        if v is None:
            out.append(('–', None, [])); continue
        c, notes = _adjust(_lvl(v, t['breaks']), n, t, days, sh)
        out.append((f'{v:.0f}' if abs(v) >= 100 else f'{v:.1f}' if abs(v) >= 1 else f'{v:.2f}', c, notes))
    used = f"{VAR_NAME.get(t['idx'], t['idx'].upper())}-{t['fm']} {' / '.join(f'{b:g}' for b in t['breaks'])}{wtxt}{adj}"
    return n, names, out, used


def tool_cells(t, L, chip=None):
    n, names, out, used = tool_eval(t, L)
    cells = []
    for txt, c, notes in out:
        ch = chip(names[c] if c is not None else '', c, n) if chip else _chip(names[c] if c is not None else '', c, n)
        nt = f'<br><span style="color:#888;font-size:10px">↓ {_esc(", ".join(notes))}</span>' if notes else ''
        cells.append(f'<td style="text-align:center">{_esc(txt)}<br>{ch}{nt}</td>')
    return ''.join(cells), used, out, n, names


def headline_html(p, s, tools, L, own, base, fmt, sfchip, ob, fc):
    """Today at a glance: SFDI, staffing level, adjective (Smokey Bear sign) and dispatch — with what each is based on."""
    rows = []
    def cell(v, chip):
        return f'<td style="text-align:center">{fmt(v) if v is not None else ""}<br>{chip}</td>' if v is not None else f'<td style="text-align:center">{chip}</td>'
    rows.append(f'<tr><td><b>Fire danger (SFDI)</b><br><span style="color:#888">Severe Fire Danger Index, fuel model {own}</span></td>'
                f'<td style="text-align:center">{sfchip(ob)}</td><td style="text-align:center">{sfchip(fc)}</td></tr>')
    lo, hi = (80, 95) if '80th' in str(p.get('standard_90_97') or '') else (90, 97)
    st = (_tool_pick(tools, r'staffing', r'^2023 FDOP') or _tool_pick(tools, r'staffing')
          or _tool_pick(tools, r'preparedness', r'adjective'))
    sl = {}
    if st:
        cells, used, out, n, names = tool_cells(st, L)
        used = f'{_esc(used)} · {_esc(st["label"])}'
        sl = {'o': (None, out[0][1], n, names), 'f': (None, out[1][1], n, names)}
        rows.append(f'<tr><td><b>Staffing level</b><br><span style="color:#888">{used}</span></td>{cells}</tr>')
    else:
        sli = (p.get('sl_dl_index') or '').upper()
        k = 'bi' if ('BI' in sli and 'ERC' not in sli) else 'erc'
        qs = (base.get('q') or {}).get(k)
        br = [_q(qs, x) for x in (10, 20, lo, hi)]
        if all(b is not None for b in br):
            names = [f'SL {i + 1}' for i in range(5)]
            for key, dd in (('o', ob), ('f', fc)):
                v = dd.get(k); sl[key] = (v, _lvl(v, br), 5, names)
            used = (f'{k.upper()}-{own} climatology (no FDOP staffing tool): SL 4 above the {lo}th ({fmt(br[2])}), '
                    f'SL 5 above the {hi}th ({fmt(br[3])})')
            rows.append(f'<tr><td><b>Staffing level</b><br><span style="color:#888">{used}</span></td>' +
                        ''.join(cell(sl[key][0], _chip(sl[key][3][sl[key][1]] if sl[key][1] is not None else "", sl[key][1], sl[key][2])) for key in ('o', 'f')) + '</tr>')
    adj = _tool_pick(tools, r'adjective')
    if adj:
        n, names, out, used = tool_eval(adj, L)
        cs = []
        for txt, c, notes in out:
            nm = names[c] if c is not None else None
            a5 = None if c is None else (ADJ_NAMES.index(nm) if nm in ADJ_NAMES else (1 if nm and nm.lower().startswith('low-mod') else _to5(c, n)))
            nt = f'<br><span style="color:#888;font-size:10px">↓ {_esc(", ".join(notes))}</span>' if notes else ''
            cs.append(f'<td style="text-align:center">{_esc(txt)}<br>{_adj_chip(a5, "Low–Moderate" if nm and nm.lower().startswith("low-mod") else None)}{nt}</td>')
        used = f'{_esc(used)} · {_esc(adj["label"])}'
    elif sl:
        cs = []
        for key, dd in (('o', ob), ('f', fc)):
            v, c, n, _ = sl[key]
            cs.append(cell(dd.get('ic'), _adj_chip(_adj_from(_to5(c, n), dd.get('ic')))))
        used = f'NFDRS matrix: staffing level × IC-{own} (value shown is IC)'
    else:
        cs = None
    if cs:
        rows.append(f'<tr><td><b>Adjective rating</b> (Smokey Bear sign)<br><span style="color:#888">{used}</span></td>{"".join(cs)}</tr>')
    dp = _tool_pick(tools, r'dispatch|response', r'^2023 FDOP')
    if dp and dp is not st and dp is not adj:
        cells, used, *_ = tool_cells(dp, L)
        rows.append(f'<tr><td><b>Dispatch level</b><br><span style="color:#888">{_esc(used)} · {_esc(dp["label"])}</span></td>{cells}</tr>')
    return ('<table style="width:100%;font-size:12px;border-collapse:collapse;margin-bottom:8px">'
            f'<tr><th style="text-align:left">Today</th><th>Observed<br>{_esc(ob.get("date") or "")}</th><th>Forecast<br>{_esc(fc.get("date") or "")}</th></tr>'
            + ''.join(rows) + '</table>')


def popup_html(p: dict, r: dict, start: dict) -> str:
    """Popup for the main-map FDRA layer: latest values and each FDOP decision tool's level; FDRAs
    without FDOP breakpoints use climatological percentiles (WFS former USFWS / BLM units 80th/95th, USFS, CAL FIRE and other WFS units 90th/97th; set in the layer's standard_90_97 field)."""
    fid, unit = p['fdra_id'], r.get('active_unit')
    s, tools = fdra_tools(fid, start)
    own = (LATEST.get((unit, p.get('fuel_model'))) or {}).get('own') or p.get('fuel_model') or 'Y'
    L = lambda fm: LATEST.get((unit, fm)) or {}
    base = L(own)
    ob, fc = base.get('obs') or {}, base.get('fcst') or {}
    fmt = lambda v: '–' if v is None else (f'{v:.0f}' if abs(v) >= 100 else f'{v:.1f}')
    sf = lambda d: sfdi_class(d.get('sfdi'))
    SF_COL = {'Low': ('#2e7d32', '#fff'), 'Moderate': ('#c0ca33', '#111'), 'High': ('#f9a825', '#111'),
              'Very High': ('#ef6c00', '#fff'), 'Severe': ('#c62828', '#fff')}
    def sfchip(d):
        c = sf(d)
        if not c:
            return '<span style="color:#888">No data</span>'
        bg, fg = SF_COL[c]
        return f'<span style="padding:1px 6px;border-radius:3px;background:{bg};color:{fg};white-space:nowrap">{c} {fmt(d.get("sfdi"))}</span>'
    head = (f'<div style="font-size:12px;margin-bottom:6px">Fuel model {own} · ERC {fmt(ob.get("erc"))} → {fmt(fc.get("erc"))} · '
            f'BI {fmt(ob.get("bi"))} → {fmt(fc.get("bi"))} · IC {fmt(ob.get("ic"))} → {fmt(fc.get("ic"))} '
            f'<span style="color:#888">(observed → forecast)</span></div>')
    rows = []
    if tools:
        for t in tools:
            cells, used, *_ = tool_cells(t, L)
            rows.append(f'<tr><td>{_esc(t["label"])}<br><span style="color:#888">{_esc(used)}</span></td>{cells}</tr>')
        src = f'Breakpoints: {_esc(s.get("source", "current FDOP"))}.'
    else:
        lo, hi = (80, 95) if '80th' in str(p.get('standard_90_97') or '') else (90, 97)
        ag = p.get('agency') or ''
        who = 'WFS' if 'WFS' in ag and lo == 80 else ('USFS' if ag == 'USFS' else 'WFS' if 'WFS' in ag else 'CAL FIRE')
        for k in ('erc', 'bi'):
            qs = base.get('q', {}).get(k)
            a, b = _q(qs, lo), _q(qs, hi)
            if a is None:
                continue
            names = ['Normal', f'≥ {lo}th', f'≥ {hi}th']
            lv = lambda v: None if v is None else (2 if v >= b else 1 if v >= a else 0)
            o, f_ = ob.get(k), fc.get(k)
            rows.append(f'<tr><td>{k.upper()}-{own} vs {lo}th / {hi}th percentile<br><span style="color:#888">{fmt(a)} / {fmt(b)}</span></td>'
                        f'<td style="text-align:center">{fmt(o)}<br>{_chip(names[lv(o)] if lv(o) is not None else "", lv(o), 3)}</td>'
                        f'<td style="text-align:center">{fmt(f_)}<br>{_chip(names[lv(f_)] if lv(f_) is not None else "", lv(f_), 3)}</td></tr>')
        src = f'No FDOP breakpoints loaded — {who} standard {lo}th / {hi}th percentiles of all {base.get("years", [0])[0] if base.get("years") else ""}–{base.get("years", [0])[-1] if base.get("years") else ""} days.'
    q = base.get('q', {})
    clim = (f' 90th / 97th (FM {own}): ERC {fmt(_q(q.get("erc"), 90))} / {fmt(_q(q.get("erc"), 97))} · '
            f'BI {fmt(_q(q.get("bi"), 90))} / {fmt(_q(q.get("bi"), 97))}.') if tools and q.get('erc') else ''
    table = ('<table style="width:100%;font-size:12px;border-collapse:collapse"><tr><th style="text-align:left">Decision tool</th>'
             f'<th>Observed<br>{_esc(ob.get("date") or "")}</th><th>Forecast<br>{_esc(fc.get("date") or "")}</th></tr>' + ''.join(rows) + '</table>') if rows else \
        '<p style="font-size:12px">No current NFDRS data for this FDRA\'s stations.</p>'
    links = (f'<p style="font-size:12px;margin:6px 0 0"><a href="{SITE}fdra.html?id={requests.utils.quote(fid)}" target="_blank">Season tracking charts ▸</a> · '
             f'<a href="{SITE}fdop.html?id={requests.utils.quote(fid)}" target="_blank">FDOP Workbench ▸</a></p>')
    foot = (f'<p style="font-size:11px;color:#666;margin:6px 0 0">{src}{clim} FDRA value = mean of the FDOP stations '
            f'({base.get("n_st", "–")}) from FEMS daily summaries; levels: breakpoint = top of its class.</p>')
    top = headline_html(p, s, tools, L, own, base, fmt, sfchip, ob, fc)
    table = '<div style="font-size:12px;font-weight:600;margin:4px 0 2px">All decision tools</div>' + table if rows else table
    return top + head + table + links + foot


def write_sfdi_geojson(out: Path, polys: dict, rows: list, now):
    """fdras_sfdi.geojson: every FDRA polygon with today's forecast SFDI and class — the
    main-map layer in AGOL (GeoJSON layer read from the site-data branch, refreshed by the map)."""
    from shapely.geometry import mapping, shape
    by = {r['fdra_id']: r for r in rows}
    sp = out / 'fdop_start.json'   # built from site/thresholds/FDRA_thresholds.xlsx (thresholds_book.py) earlier in the run
    start = json.loads((sp if sp.exists() else FDOP_START).read_text()) if (sp.exists() or FDOP_START.exists()) else {}
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
            'popup_html': popup_html(p, r, start),
            'charts': SITE + 'fdra.html?id=' + requests.utils.quote(p['fdra_id']),
            'workbench': SITE + 'fdop.html?id=' + requests.utils.quote(p['fdra_id']),
            'generated': now.strftime('%Y-%m-%d %H:%M %Z')}})
    gj = {'type': 'FeatureCollection', 'features': feats}
    (out / 'fdras_sfdi.geojson').write_text(json.dumps(gj, separators=(',', ':'), allow_nan=False))
    # the same summary per FDRA for the season-tracking page (side panel of the app)
    (out / 'popups.json').write_text(json.dumps({'generated': now.strftime('%Y-%m-%d %H:%M %Z'),
                                                 'fdras': {f['properties']['fdra_id']: f['properties']['popup_html'] for f in feats}},
                                                separators=(',', ':')))
    log.info('fdras_sfdi.geojson: %d polygons', len(feats))


def build_current(out: Path):
    now = datetime.now(TZ)
    today = now.date()
    start, end = f'{today.year}-01-01', (today + timedelta(days=10)).isoformat()
    mem, pairs = cn.load_fdra_membership(MEMBERSHIP)
    allm, own = all_fm(mem)
    WEIGHTS.update(load_weights())
    sids = sorted(pairs['stationId'].astype(int).unique())
    pairs = pd.DataFrame([(s, fm) for s in sids for fm in FMS], columns=['stationId', 'FuelModel'])
    n, w = fetch_current(pairs, start, end)
    log.info('current: %d NFDR rows, %d wx rows, %s → %s', len(n), len(w), start, end)
    polys = json.loads(POLYGONS.read_text())
    pal = pal_by_polygon(polys) if (AREA.get('pal') or {}).get('enabled') else {}
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
        cols = ['erc', 'bi', 'ic', 'sc', 'herb', 'woody', 'fm1', 'fm10', 'fm100', 'fm1000', 'kbdi', 'gsi']
        d = _pick(sub, cols, WEIGHTS.get(uid))
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
                                                   for k in ['erc', 'bi', 'ic', 'erc_p', 'bi_p', 'sfdi', 'kbdi', 'gsi'] if k in r.index}
        o_row = d.loc[last_o] if last_o is not None else None
        f_row = fc.iloc[0] if len(fc) else None
        bid = base_id(uid)
        unit = {'unit_id': uid, 'fdra_id': bid, 'fm': fmk, 'fdop_fm': own[uid], 'season': uid[len(bid):].strip(' ()') or None,
                'stations': [{'stationId': s, 'name': names.get(s, ''), 'fm': f} for s, f in members],
                'has_normals': bool(climo), 'normal_years': climo.get('years', []),
                'latest_obs': {'date': last_o.strftime('%Y-%m-%d') if last_o is not None else None, **(snap(o_row) or {})},
                'next_fcst': {'date': fc.index[0].strftime('%Y-%m-%d') if len(fc) else None, **(snap(f_row) or {})}}
        dvars = [k for k in ('erc', 'bi', 'ic', 'sc', 'fm100', 'fm1000', 'kbdi', 'gsi', 'tmax', 'rhmin') if k in d.columns]
        drow = lambda r, dt: {'date': dt.strftime('%Y-%m-%d'), **{k: (None if pd.isna(r[k]) else round(float(r[k]), 2 if k == 'gsi' else 1)) for k in dvars}}
        days = ([drow(o_row, last_o)] if o_row is not None else [None]) + [drow(r_, dt) for dt, r_ in fc.head(8).iterrows()]
        LATEST[(uid, fmk)] = {'obs': unit['latest_obs'], 'fcst': unit['next_fcst'], 'own': own[uid], 'days': days,
                              'q': {k: climo.get(k + '_q') for k in ('erc', 'bi')}, 'years': climo.get('years', []),
                              'n_st': len(sids)}
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
