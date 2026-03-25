"""
GACC Fire Weather Intelligence Dashboard
Sidebar: GACC → PSA → Primary Index
Tabs: 7-Day Forecast | GACC Overview | All Indices | ERC Trend | Heatmap | Context | Table
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json, os, threading
from contextlib import contextmanager
from datetime import datetime, date
from pathlib import Path

st.set_page_config(
    page_title="GACC Fire Weather Intelligence",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
:root {
  --bg:#0d0f1a; --bg2:#12151f; --surface:#1a1e2e; --surface2:#222740;
  --border:#2a3050; --fire:#ff4d00; --teal:#00d4b4; --gold:#ffd700;
  --text:#e8eaf6; --muted:#6b7299; --dim:#3a3f6b;
  --crit:#ff2d55; --high:#ff6b00; --elev:#ffcc00; --norm:#00c875;
  --p80:#4dabf7; --p90:#ffa94d; --p95:#ff6b6b; --p97:#cc5de8;
}
.stApp{background:var(--bg)!important;}
section[data-testid="stSidebar"]{background:var(--bg2)!important;border-right:1px solid var(--border)!important;}
html,body,[class*="css"]{font-family:'Space Grotesk',sans-serif;color:var(--text);}
[data-testid="metric-container"]{background:var(--surface)!important;border:1px solid var(--border)!important;border-top:3px solid var(--fire)!important;border-radius:6px!important;padding:14px 18px!important;}
[data-testid="metric-container"] label{color:var(--muted)!important;font-size:10px!important;text-transform:uppercase!important;letter-spacing:1.2px!important;font-family:'JetBrains Mono',monospace!important;}
[data-testid="metric-container"] [data-testid="stMetricValue"]{font-family:'Bebas Neue',sans-serif!important;font-size:36px!important;color:var(--text)!important;line-height:1.1!important;}
.stTabs [data-baseweb="tab-list"]{background:var(--surface)!important;border-radius:4px!important;padding:3px!important;border:1px solid var(--border)!important;gap:2px!important;}
.stTabs [data-baseweb="tab"]{background:transparent!important;color:var(--muted)!important;border-radius:3px!important;font-family:'JetBrains Mono',monospace!important;font-size:10px!important;letter-spacing:1px!important;text-transform:uppercase!important;padding:7px 14px!important;border:none!important;}
.stTabs [aria-selected="true"]{background:var(--fire)!important;color:white!important;}
.stSelectbox>div>div{background:var(--surface2)!important;border:1px solid var(--border)!important;color:var(--text)!important;border-radius:4px!important;}
.stSelectbox label,.stRadio [data-testid="stWidgetLabel"]{color:var(--muted)!important;font-size:10px!important;text-transform:uppercase!important;letter-spacing:1px!important;font-family:'JetBrains Mono',monospace!important;}
.stButton>button{background:var(--surface2)!important;border:1px solid var(--border)!important;color:var(--text)!important;border-radius:4px!important;font-family:'JetBrains Mono',monospace!important;font-size:11px!important;}
.stButton>button:hover{border-color:var(--fire)!important;color:var(--fire)!important;}
#MainMenu,footer,header{visibility:hidden;}
hr{border-color:var(--border)!important;opacity:.4!important;}
.badge-live{background:rgba(0,200,117,.10);border:1px solid rgba(0,200,117,.35);color:#00c875;border-radius:4px;padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:10px;line-height:1.9;}
.badge-cached{background:rgba(255,214,0,.08);border:1px solid rgba(255,214,0,.30);color:#ffd700;border-radius:4px;padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:10px;line-height:1.9;}
.badge-stale{background:rgba(255,45,85,.08);border:1px solid rgba(255,45,85,.35);color:#ff6b6b;border-radius:4px;padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:10px;line-height:1.9;}
.badge-err{background:rgba(255,45,85,.10);border:1px solid rgba(255,45,85,.40);color:#ff2d55;border-radius:4px;padding:16px 20px;font-family:'Space Grotesk',sans-serif;font-size:13px;line-height:1.6;}
.alert-crit{background:#ff2d5522;border:1px solid #ff2d55;color:#ff2d55;border-radius:3px;padding:4px 12px;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;letter-spacing:1px;}
.alert-high{background:#ff6b0022;border:1px solid #ff6b00;color:#ff6b00;border-radius:3px;padding:4px 12px;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;letter-spacing:1px;}
.alert-elev{background:#ffcc0022;border:1px solid #ffcc00;color:#ffcc00;border-radius:3px;padding:4px 12px;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;letter-spacing:1px;}
.alert-norm{background:#00c87522;border:1px solid #00c875;color:#00c875;border-radius:3px;padding:4px 12px;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;letter-spacing:1px;}
.fetch-row{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0;}
.fetch-chip{font-family:'JetBrains Mono',monospace;font-size:9px;padding:2px 7px;border-radius:3px;border:1px solid;}
.chip-fresh{background:rgba(0,200,117,.08);border-color:rgba(0,200,117,.35);color:#00c875;}
.chip-stale{background:rgba(255,45,85,.08);border-color:rgba(255,45,85,.35);color:#ff6b6b;}
</style>
""", unsafe_allow_html=True)

# ── Palette & Plotly base layout ──────────────────────────────────────────────
C = {
    'bg':'#0d0f1a','surface':'#1a1e2e','surface2':'#222740','border':'#2a3050',
    'fire':'#ff4d00','teal':'#00d4b4','gold':'#ffd700','text':'#e8eaf6',
    'muted':'#6b7299','dim':'#3a3f6b','crit':'#ff2d55','high':'#ff6b00',
    'elev':'#ffcc00','norm':'#00c875','p80':'#4dabf7','p90':'#ffa94d',
    'p95':'#ff6b6b','p97':'#cc5de8',
}
PL = dict(
    paper_bgcolor=C['surface'], plot_bgcolor=C['surface'],
    font=dict(color=C['text'], family='Space Grotesk'),
    margin=dict(t=48, b=52, l=52, r=24),
    legend=dict(bgcolor=C['surface2'], bordercolor=C['border'], borderwidth=1,
                font=dict(size=10, color=C['muted']), orientation='h', y=-0.22, x=0),
    xaxis=dict(gridcolor=C['border'], linecolor=C['border'],
               tickfont=dict(color=C['muted'], size=10, family='JetBrains Mono'),
               title_font=dict(color=C['muted'], size=11)),
    yaxis=dict(gridcolor=C['border'], linecolor=C['border'],
               tickfont=dict(color=C['muted'], size=10, family='JetBrains Mono'),
               title_font=dict(color=C['muted'], size=11)),
)

# ── Field definitions ─────────────────────────────────────────────────────────
FIELD_META = {
    'erc':    {'label':'Energy Release Component', 'unit':'ERC',     'color':'#ff4d00','pctile_flip':False},
    'ic':     {'label':'Ignition Component',       'unit':'IC',      'color':'#cc5de8','pctile_flip':False},
    'bi':     {'label':'Burning Index',            'unit':'BI',      'color':'#ffd700','pctile_flip':False},
    'sc':     {'label':'Spread Component',         'unit':'SC',      'color':'#ff6b6b','pctile_flip':False},
    'fm100':  {'label':'100-Hr Fuel Moisture',     'unit':'FM-100',  'color':'#00d4b4','pctile_flip':True},
    'fm1':    {'label':'1-Hr Fuel Moisture',       'unit':'FM-1',    'color':'#74c0fc','pctile_flip':True},
    'fm10':   {'label':'10-Hr Fuel Moisture',      'unit':'FM-10',   'color':'#63e6be','pctile_flip':True},
    'fm1000': {'label':'1000-Hr Fuel Moisture',    'unit':'FM-1000', 'color':'#a9e34b','pctile_flip':True},
    'kbdi':   {'label':'Keetch-Byram Drought Index','unit':'KBDI',   'color':'#f08c00','pctile_flip':False},
}
PRIMARY_FIELDS = ['erc','ic','bi','sc','fm100']
ALL_FIELDS     = list(FIELD_META.keys())
DAY_COLS       = ['yd','td','D+1','D+2','D+3','D+4','D+5','D+6']
# DAY_LABELS are now computed at render time via _day_labels_from_map()
# so they always reflect today's date regardless of cache age.
CACHE_HOURS    = 6
CACHE_DIR      = Path('gacc_cache')
CACHE_DIR.mkdir(exist_ok=True)   # ensure dir exists at import time

# ── Null context manager ──────────────────────────────────────────────────────
@contextmanager
def _nullctx():
    yield


def _day_labels_from_map(day_map: dict) -> list:
    """
    Convert the day_map {label: date_str} from the cache into human-readable
    axis labels computed from TODAY's actual date.

    Always called at render time — never stored in cache — so switching from
    a Tuesday cache to Wednesday render shows correct 'Today = Wed' labels.
    """
    import fems_fetcher as ff
    return [ff._day_label(day_map[k]) for k in ['yd','td','D+1','D+2','D+3','D+4','D+5','D+6']
            if k in day_map]


def _trend_day_labels(day_map: dict) -> tuple:
    """Return (keys, labels) for the 7 trend columns td … D+6."""
    import fems_fetcher as ff
    keys   = ['td','D+1','D+2','D+3','D+4','D+5','D+6']
    labels = [ff._day_label(day_map[k]) for k in keys if k in day_map]
    return keys, labels


# ── Credentials ───────────────────────────────────────────────────────────────
def _creds():
    try:
        k = st.secrets['FEMS_API_KEY']; u = st.secrets['FEMS_USERNAME']
        if k and u: return k, u
    except Exception: pass
    try:
        from dotenv import load_dotenv; load_dotenv()
    except ImportError: pass
    return os.getenv('FEMS_API_KEY',''), os.getenv('FEMS_USERNAME','')


# ── Per-GACC cache helpers ────────────────────────────────────────────────────
def _cache_path(abbrev):
    return CACHE_DIR / f'gacc_data_{abbrev}.json'


def _cache_fresh(abbrev):
    p = _cache_path(abbrev)
    if not p.exists(): return False
    age = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds()
    return age < CACHE_HOURS * 3600


def _cache_age_str(abbrev):
    p = _cache_path(abbrev)
    if not p.exists(): return 'no cache'
    age = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds()
    if age < 60:   return 'just now'
    if age < 3600: return f'{int(age//60)}m ago'
    return f'{age/3600:.1f}h ago'


# ── Static loaders ────────────────────────────────────────────────────────────
@st.cache_resource
def load_gacc_config():
    import importlib.util
    p = Path('gacc_config.py')
    if not p.exists(): return {}
    spec = importlib.util.spec_from_file_location('gacc_config', p)
    gc   = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gc)
    return gc.GACC_CONFIG


@st.cache_data(show_spinner=False)
def load_baseline():
    p = Path('gacc_climo_baseline.json')
    if not p.exists(): return {}
    return json.loads(p.read_text(encoding='utf-8'))


# ── Per-GACC fetch / load ─────────────────────────────────────────────────────
def _fetch_gacc_live(api_key, username, gacc_name, gacc_config):
    """Fetch one GACC from FEMS, write its per-GACC cache file, return (dfs, meta)."""
    import fems_fetcher as ff
    ff.FEMS_API_KEY  = api_key
    ff.FEMS_USERNAME = username
    abbrev   = gacc_config[gacc_name]['abbrev']
    psa_ids  = list(gacc_config[gacc_name]['psas'].keys())
    out_path = str(_cache_path(abbrev))
    data     = ff.fetch_psa_forecast(gacc_name, psa_ids, output_path=out_path)
    return ff.json_to_dataframes(data), data['meta']


def _load_gacc_cache(gacc_name, gacc_config):
    """Load a GACC from its on-disk cache file. Raises if file missing."""
    import fems_fetcher as ff
    abbrev = gacc_config[gacc_name]['abbrev']
    p      = _cache_path(abbrev)
    if not p.exists():
        raise FileNotFoundError(f'No cache for {abbrev}')
    data = json.loads(p.read_text(encoding='utf-8'))
    return ff.json_to_dataframes(data), data['meta']


def ensure_gacc_loaded(api_key, username, gacc_name, gacc_config, force=False):
    """
    Guarantee gacc_name's data is in st.session_state.
    Returns (dfs, meta, source_str).
    Priority:
      1. Already in session_state + cache still fresh → instant (no I/O)
      2. Cache file fresh on disk → read from disk (fast, no API)
      3. Stale / missing → fetch from FEMS (one-time per GACC per 6 h)
      4. FEMS fetch fails + stale cache exists → serve stale, warn user
    """
    dfs_key  = f'dfs_{gacc_name}'
    meta_key = f'meta_{gacc_name}'
    src_key  = f'source_{gacc_name}'
    abbrev   = gacc_config[gacc_name]['abbrev']

    # FIX 1: session_state check must also verify cache hasn't expired since load
    if not force and dfs_key in st.session_state and _cache_fresh(abbrev):
        return (st.session_state[dfs_key],
                st.session_state[meta_key],
                st.session_state[src_key])

    # Cache on disk is fresh — load without hitting API
    if not force and _cache_fresh(abbrev):
        try:
            dfs, meta = _load_gacc_cache(gacc_name, gacc_config)
            st.session_state[dfs_key]  = dfs
            st.session_state[meta_key] = meta
            st.session_state[src_key]  = 'cached'
            return dfs, meta, 'cached'
        except Exception:
            pass  # corrupt cache — fall through to live fetch

    # Need live fetch
    fetch_err = None
    try:
        dfs, meta = _fetch_gacc_live(api_key, username, gacc_name, gacc_config)
        st.session_state[dfs_key]  = dfs
        st.session_state[meta_key] = meta
        st.session_state[src_key]  = 'live'
        return dfs, meta, 'live'
    except Exception as e:
        fetch_err = e

    # Live fetch failed — try serving stale cache rather than crashing
    if _cache_path(abbrev).exists():
        try:
            dfs, meta = _load_gacc_cache(gacc_name, gacc_config)
            st.session_state[dfs_key]  = dfs
            st.session_state[meta_key] = meta
            st.session_state[src_key]  = 'cached (stale)'
            return dfs, meta, 'cached (stale)'
        except Exception:
            pass

    # Nothing worked
    raise fetch_err


# Module-level set tracks which GACCs are currently being background-fetched.
# Using a module-level object instead of st.session_state avoids thread-safety
# issues (Streamlit session_state is not safe to write from background threads).
_bg_fetching: set = set()
_bg_lock = threading.Lock()


def _prefetch_bg(api_key, username, active_gaccs, gacc_config, skip_gacc):
    """
    Background daemon thread: warm the cache for every GACC that isn't fresh.
    Runs after the primary GACC renders — never blocks the UI.
    Uses a module-level set (thread-safe via lock) instead of session_state.
    """
    def _worker():
        for gname in active_gaccs:
            if gname == skip_gacc:
                continue
            abbrev = gacc_config[gname]['abbrev']
            if _cache_fresh(abbrev):
                continue
            with _bg_lock:
                if gname in _bg_fetching:
                    continue          # already being fetched by another thread
                _bg_fetching.add(gname)
            try:
                import fems_fetcher as ff
                ff.FEMS_API_KEY  = api_key
                ff.FEMS_USERNAME = username
                psa_ids  = list(gacc_config[gname]['psas'].keys())
                out_path = str(_cache_path(abbrev))
                ff.fetch_psa_forecast(gname, psa_ids, output_path=out_path)
            except Exception:
                pass
            finally:
                with _bg_lock:
                    _bg_fetching.discard(gname)

    # Only start if there is actually stale work to do
    stale = [g for g in active_gaccs
             if g != skip_gacc and not _cache_fresh(gacc_config[g]['abbrev'])]
    if stale:
        threading.Thread(target=_worker, daemon=True).start()


# ── Data helpers ──────────────────────────────────────────────────────────────
def get_field_df(dfs, fk):
    return dfs.get(fk, pd.DataFrame())


def get_psa_bdata(gacc_name, psa_id, baseline, fk):
    return (baseline.get('psa', {})
            .get(f'{gacc_name}|{psa_id}', {})
            .get(fk, {}))


def alert_level(val, p90, p95, p97):
    # FIX 3: guard against NaN values reaching comparison operators
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return 'UNKNOWN', C['dim'], 'alert-norm'
        if p97 is not None and val >= p97: return 'CRITICAL', C['crit'], 'alert-crit'
        if p95 is not None and val >= p95: return 'HIGH',     C['high'], 'alert-high'
        if p90 is not None and val >= p90: return 'ELEVATED', C['elev'], 'alert-elev'
    except TypeError:
        pass
    return 'NORMAL', C['norm'], 'alert-norm'


# ── Chart helpers ─────────────────────────────────────────────────────────────
def _title(text):
    return dict(
        text=f'<span style="font-family:Bebas Neue;font-size:18px;letter-spacing:2px">{text}</span>',
        font=dict(color=C['text']), x=0, xanchor='left',
    )


def add_pctile_lines(fig, bdata):
    for key, color, dash, width, label in [
        ('mean', C['teal'], 'dot',  1.5, 'Mean'),
        ('p80',  C['p80'],  'dot',  1.5, '80th'),
        ('p90',  C['p90'],  'dash', 1.8, '90th'),
        ('p95',  C['p95'],  'dash', 2.0, '95th'),
        ('p97',  C['p97'],  'dash', 2.2, '97th'),
    ]:
        val = bdata.get(key)
        if val is None: continue
        fig.add_hline(y=val, line_dash=dash, line_color=color, line_width=width,
                      opacity=0.75, annotation_text=f'{label}: {val:.0f}',
                      annotation_font_color=color, annotation_font_size=10,
                      annotation_position='right')


def chart_7day(row_dict, fk, fmeta, bdata, psa_id, height=360, day_map=None):
    # Build axis labels fresh from today's date — never use cached weekday names
    if day_map:
        x_labels = _day_labels_from_map(day_map)
        day_keys = ['yd','td','D+1','D+2','D+3','D+4','D+5','D+6']
    else:
        x_labels = ['Yesterday','Today','D+1','D+2','D+3','D+4','D+5','D+6']
        day_keys = DAY_COLS
    vals  = [row_dict.get(d) for d in day_keys]
    color = fmeta['color']
    fig   = go.Figure()
    p90 = bdata.get('p90'); p97 = bdata.get('p97')
    if p90 is not None and p97 is not None:
        fig.add_trace(go.Scatter(
            x=x_labels + x_labels[::-1], y=[p97]*len(x_labels) + [p90]*len(x_labels),
            fill='toself', fillcolor='rgba(255,77,0,0.05)',
            line=dict(color='rgba(0,0,0,0)'), hoverinfo='skip', showlegend=False))
    fig.add_trace(go.Scatter(
        x=x_labels, y=vals, mode='lines+markers', name=fmeta['unit'],
        line=dict(color=color, width=3),
        marker=dict(size=9, color=color, line=dict(color=C['bg'], width=2)),
        hovertemplate=f'<b>%{{x}}</b><br>{fmeta["unit"]} = <b>%{{y:.1f}}</b><extra></extra>'))
    add_pctile_lines(fig, bdata)
    fig.update_layout(**{**PL,
        'title': _title(f'{psa_id} — 7-Day {fmeta["label"]}'),
        'height': height,
        'yaxis': {**PL['yaxis'], 'title': fmeta['unit']}})
    return fig


def chart_bar_today(df, fk, fmeta, baseline, gacc_name):
    psas, vals, colors = [], [], []
    for _, row in df.sort_values('PSA').iterrows():
        td = row.get('td')
        # FIX 4: skip NaN as well as None to prevent empty bars
        if td is None or (isinstance(td, float) and pd.isna(td)): continue
        bdata = get_psa_bdata(gacc_name, row['PSA'], baseline, fk)
        _, col, _ = alert_level(td, bdata.get('p90'), bdata.get('p95'), bdata.get('p97'))
        psas.append(row['PSA']); vals.append(td); colors.append(col)
    if not psas: return go.Figure()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=psas, y=vals, marker_color=colors, marker_line_width=0,
                         hovertemplate=f'<b>%{{x}}</b><br>{fmeta["unit"]}: <b>%{{y:.1f}}</b><extra></extra>'))
    fig.update_layout(**{**PL,
        'title': _title(f'{fmeta["label"]} Today — All PSAs'),
        'height': 340,
        'xaxis': {**PL['xaxis'], 'tickangle': -45},
        'yaxis': {**PL['yaxis'], 'title': fmeta['unit']}})
    return fig


def chart_pctile_grouped(df, fk, baseline, gacc_name):
    psas  = sorted(df['PSA'].tolist())
    today, means, p90s, p97s = [], [], [], []
    for p in psas:
        rows  = df[df['PSA'] == p]
        bdata = get_psa_bdata(gacc_name, p, baseline, fk)
        td = rows.iloc[0].get('td') if not rows.empty else None
        today.append(td if td is not None and not (isinstance(td, float) and pd.isna(td)) else None)
        means.append(bdata.get('mean'))
        p90s.append(bdata.get('p90'))
        p97s.append(bdata.get('p97'))
    fig = go.Figure()
    for name, vals, color, op in [
        ('Today', today, C['fire'], 1.0), ('Mean', means, C['teal'], 0.7),
        ('90th', p90s, C['p90'], 0.6),   ('97th', p97s, C['p97'], 0.6)]:
        fig.add_trace(go.Bar(x=psas, y=vals, name=name, marker_color=color,
                             marker_line_width=0, opacity=op,
                             hovertemplate=f'<b>%{{x}}</b><br>{name}: <b>%{{y:.1f}}</b><extra></extra>'))
    fig.update_layout(**{**PL,
        'title': _title('Percentile Context — All PSAs'),
        'barmode': 'group', 'height': 360,
        'xaxis': {**PL['xaxis'], 'tickangle': -45}})
    return fig


def chart_trend_heatmap(trend_df, day_map=None):
    import fems_fetcher as _ff
    _dm    = day_map or _ff._build_day_map()
    t_days, t_lbls = _trend_day_labels(_dm)
    psas   = sorted(trend_df['PSA'].tolist())
    # FIX 5: fill NaN trend values with 0 so heatmap renders without gaps
    z = [[float(trend_df[trend_df['PSA']==p].iloc[0].get(d) or 0)
          for d in t_days] for p in psas]
    fig = go.Figure(go.Heatmap(
        z=z, x=t_lbls, y=psas,
        colorscale=[[0,'#00c875'],[0.4,'#1a1e2e'],[0.6,'#1a1e2e'],[0.82,'#ff6b00'],[1,'#ff2d55']],
        zmid=0,
        hovertemplate='<b>%{y}</b> · %{x}<br>Δ ERC: <b>%{z:+.1f}</b><extra></extra>',
        colorbar=dict(tickfont=dict(color=C['muted'], size=9, family='JetBrains Mono'),
                      title=dict(text='Δ ERC', font=dict(color=C['muted'])), len=0.8)))
    fig.update_layout(**{**PL,
        'title': _title('ERC TREND HEATMAP — Δ vs Today'),
        'height': max(360, len(psas)*20 + 100),
        'yaxis': {**PL['yaxis'], 'autorange': 'reversed'}})
    return fig


# ── Sidebar ───────────────────────────────────────────────────────────────────
def build_sidebar(gacc_config, gacc_names, selected_gacc, source, meta):
    with st.sidebar:
        st.markdown(f"""
        <div style="padding:24px 16px 8px;border-bottom:1px solid {C['border']};">
          <div style="font-family:'Bebas Neue',sans-serif;font-size:28px;color:{C['fire']};letter-spacing:3px;line-height:1;">FIRE WEATHER</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:{C['muted']};letter-spacing:2px;text-transform:uppercase;margin-top:4px;">GACC Intelligence Dashboard</div>
        </div>""", unsafe_allow_html=True)

        st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)

        # Data status badge for the currently loaded GACC
        fetched = meta.get('fetched_at','')[:16].replace('T',' ')
        if source == 'live':
            badge_cls, icon = 'badge-live', '⬤ LIVE · FEMS API'
        elif 'stale' in source:
            badge_cls, icon = 'badge-stale', '⚠ STALE CACHE'
        else:
            badge_cls, icon = 'badge-cached', '◑ CACHED'
        st.markdown(f'<div class="{badge_cls}">{icon}<br>'
                    f'<span style="opacity:.6">{fetched} UTC</span></div>',
                    unsafe_allow_html=True)
        st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)

        # Per-GACC freshness chips
        chips = ''
        for gn in gacc_names:
            ab  = gacc_config[gn]['abbrev']
            age = _cache_age_str(ab)
            cls = 'chip-fresh' if _cache_fresh(ab) else 'chip-stale'
            chips += f'<span class="fetch-chip {cls}">{ab} {age}</span>'
        st.markdown(f'<div class="fetch-row">{chips}</div>', unsafe_allow_html=True)

        if st.button('↺  Refresh All', use_container_width=True):
            # Wipe all session data so everything re-fetches on next load
            for k in list(st.session_state.keys()):
                if k.startswith(('dfs_', 'meta_', 'source_', 'bg_')):
                    del st.session_state[k]
            st.rerun()

        st.markdown('<hr>', unsafe_allow_html=True)

        # FIX 6: GACC selectbox uses on_change callback to update session state
        # immediately — avoids the extra rerun cycle that caused lag
        def _gacc_changed():
            # Clear stale session data for the old GACC's PSA selection
            if 'selected_psa' in st.session_state:
                del st.session_state['selected_psa']

        selected_gacc_new = st.selectbox(
            'GACC', gacc_names,
            index=gacc_names.index(selected_gacc),
            format_func=lambda n: f"{gacc_config[n]['abbrev']} — {' '.join(n.split()[:2])}",
            key='gacc_selector',
            on_change=_gacc_changed,
        )

        # PSA list updates when GACC changes — preserve selection if same GACC
        psa_ids = sorted(gacc_config[selected_gacc_new]['psas'].keys())
        # FIX 7: reset PSA index to 0 when GACC changes so we don't get an
        # IndexError if the new GACC has fewer PSAs than the old one
        psa_default = 0
        if selected_gacc_new == selected_gacc and 'selected_psa' in st.session_state:
            prev = st.session_state['selected_psa']
            if prev in psa_ids:
                psa_default = psa_ids.index(prev)

        selected_psa = st.selectbox('PSA', psa_ids, index=psa_default, key='psa_selector')
        st.session_state['selected_psa'] = selected_psa

        selected_field = st.radio(
            'Primary Index', PRIMARY_FIELDS,
            format_func=lambda f: FIELD_META[f]['unit'],
            horizontal=True,
        )

        st.markdown('<hr>', unsafe_allow_html=True)
        for lbl, col in [('Critical  ≥ 97th', C['crit']), ('High      ≥ 95th', C['high']),
                          ('Elevated  ≥ 90th', C['elev']), ('Normal    < 90th', C['norm'])]:
            st.markdown(f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:5px;">'
                        f'<div style="width:10px;height:10px;border-radius:2px;background:{col};flex-shrink:0"></div>'
                        f'<span style="font-family:JetBrains Mono,monospace;font-size:10px;color:{C["muted"]}">{lbl}</span></div>',
                        unsafe_allow_html=True)
        st.markdown('<hr>', unsafe_allow_html=True)
        for lbl, col in [('─── Climo Mean', C['teal']), ('·· · 80th', C['p80']),
                          ('- - 90th', C['p90']), ('─ ─ 95th', C['p95']), ('─ ─ 97th', C['p97'])]:
            st.markdown(f'<div style="font-family:JetBrains Mono,monospace;font-size:10px;color:{col};margin-bottom:4px;">{lbl}</div>',
                        unsafe_allow_html=True)
        st.markdown('<hr>', unsafe_allow_html=True)
        fm_label = gacc_config[selected_gacc_new]['psas'].get(selected_psa, {}).get('fuel_model', '?')
        n_st     = len(gacc_config[selected_gacc_new]['psas'].get(selected_psa, {}).get('stations', []))
        pcts     = meta.get('percentiles', [80, 90, 95, 97])
        st.markdown(f"""<div style='font-size:9px;color:{C["dim"]};font-family:JetBrains Mono,monospace;
                    line-height:2;text-transform:uppercase;letter-spacing:.8px;'>
          {gacc_config[selected_gacc_new]['abbrev']} · PSA {selected_psa}<br>
          Fuel Model: {fm_label} · Stations: {n_st}<br>
          Climo: {meta.get('climo_start',2005)}–{meta.get('climo_end',2020)}<br>
          Percentiles: {pcts}</div>""", unsafe_allow_html=True)

    return selected_gacc_new, selected_psa, selected_field


# ── KPI row ───────────────────────────────────────────────────────────────────
def build_kpis(dfs, fk, baseline, gacc_name):
    df = get_field_df(dfs, fk)
    if df.empty: return
    fmeta = FIELD_META[fk]
    crits, highs, elevs, vals = 0, 0, 0, []
    for _, row in df.iterrows():
        td = row.get('td')
        if td is None or (isinstance(td, float) and pd.isna(td)): continue
        vals.append(float(td))
        bdata = get_psa_bdata(gacc_name, row['PSA'], baseline, fk)
        lvl, _, _ = alert_level(td, bdata.get('p90'), bdata.get('p95'), bdata.get('p97'))
        if lvl == 'CRITICAL':  crits += 1
        elif lvl == 'HIGH':    highs += 1
        elif lvl == 'ELEVATED':elevs += 1
    if not vals: return
    avg    = sum(vals) / len(vals)
    # FIX 8: dropna before idxmax to avoid ValueError when all td are NaN
    td_series = df['td'].dropna()
    if td_series.empty: return
    mx_row = df.loc[td_series.idxmax()]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric('🔴 Critical PSAs', crits, delta='≥ 97th percentile')
    c2.metric('🟠 High PSAs',     highs, delta='≥ 95th percentile')
    c3.metric('🟡 Elevated PSAs', elevs, delta='≥ 90th percentile')
    c4.metric(f'📊 Avg {fmeta["unit"]}', f'{avg:.1f}')
    c5.metric(f'🔥 Max ({mx_row["PSA"]})', f'{float(mx_row["td"]):.0f}')


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    gacc_config = load_gacc_config()
    if not gacc_config:
        st.error('gacc_config.py not found — place it alongside app.py'); st.stop()

    baseline = load_baseline()
    if not baseline:
        st.warning('gacc_climo_baseline.json not found — percentile lines will be absent.')

    api_key, username = _creds()
    if not api_key:
        st.markdown("""<div class="badge-err">
        <strong>🔑 FEMS credentials not configured</strong><br><br>
        Streamlit Cloud → App Settings → Secrets → add:<br>
        &nbsp;&nbsp;<code>FEMS_API_KEY = "your_key"</code><br>
        &nbsp;&nbsp;<code>FEMS_USERNAME = "your.email@usda.gov"</code><br><br>
        Local: create <code>.env</code> with those two lines.
        </div>""", unsafe_allow_html=True)
        st.stop()

    gacc_names = [n for n, d in gacc_config.items()
                  if any(p['stations'] for p in d['psas'].values())]

    # Persist GACC selection across reruns via session state
    if 'selected_gacc' not in st.session_state:
        st.session_state['selected_gacc'] = gacc_names[0]

    # If the sidebar GACC selectbox changed this run, pick it up
    selected_gacc = st.session_state.get('gacc_selector', st.session_state['selected_gacc'])
    st.session_state['selected_gacc'] = selected_gacc

    abbrev_sel = gacc_config[selected_gacc]['abbrev']
    needs_fetch = not _cache_fresh(abbrev_sel)

    try:
        ctx = st.spinner(f'Fetching {abbrev_sel} from FEMS...') if needs_fetch else _nullctx()
        with ctx:
            dfs, meta, source = ensure_gacc_loaded(api_key, username, selected_gacc, gacc_config)
    except Exception as e:
        st.error(f'Could not load {abbrev_sel}: {e}')
        st.info('Check FEMS credentials and network connectivity.')
        st.stop()

    if 'stale' in source:
        st.warning(f'⚠️ Using stale cache for {abbrev_sel} — FEMS fetch failed. Data may be outdated.')

    # Build sidebar — returns potentially new GACC if user switched
    new_gacc, selected_psa, selected_field = build_sidebar(
        gacc_config, gacc_names, selected_gacc, source, meta)

    # GACC changed — store new selection and rerun; new GACC loads from its own cache
    if new_gacc != selected_gacc:
        st.session_state['selected_gacc'] = new_gacc
        st.rerun()

    # Background: warm caches for all other GACCs without blocking the UI
    _prefetch_bg(api_key, username, gacc_names, gacc_config, selected_gacc)

    abbrev = gacc_config[selected_gacc]['abbrev']
    fmeta  = FIELD_META[selected_field]

    # ── Page header ───────────────────────────────────────────────────────────
    c_h, c_b = st.columns([4, 1])
    with c_h:
        st.markdown(f"""
        <div style="padding:4px 0 16px;">
          <div style="font-family:'Bebas Neue',sans-serif;font-size:36px;color:{C['text']};letter-spacing:4px;line-height:1;">
            {abbrev} <span style="color:{C['fire']}">FIRE WEATHER</span> INTELLIGENCE</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:{C['muted']};letter-spacing:2px;text-transform:uppercase;margin-top:4px;">
            7-Day NFDR Forecast · ERC · IC · BI · SC · FM · KBDI ·
            Climo {meta.get('climo_start',2005)}–{meta.get('climo_end',2020)} Baseline
          </div>
        </div>""", unsafe_allow_html=True)
    with c_b:
        st.markdown(f"""
        <div style="text-align:right;padding-top:8px;">
          <div style="display:inline-block;background:{C['fire']};color:white;padding:6px 18px;border-radius:3px;
                      font-family:'Bebas Neue',sans-serif;font-size:16px;letter-spacing:2px;">{abbrev}</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:{C['muted']};margin-top:6px;
                      letter-spacing:1px;text-transform:uppercase;">{meta.get('fetch_date',str(date.today()))}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown('<hr>', unsafe_allow_html=True)
    build_kpis(dfs, selected_field, baseline, selected_gacc)
    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ── PSA alert strip ───────────────────────────────────────────────────────
    sel_df   = get_field_df(dfs, selected_field)
    sel_rows = sel_df[sel_df['PSA'] == selected_psa]
    sel_dict = sel_rows.iloc[0].to_dict() if not sel_rows.empty else {}
    bdata    = get_psa_bdata(selected_gacc, selected_psa, baseline, selected_field)
    td_val   = sel_dict.get('td')
    if isinstance(td_val, float) and pd.isna(td_val):
        td_val = None
    lvl, _, cls = alert_level(td_val, bdata.get('p90'), bdata.get('p95'), bdata.get('p97'))
    fm_label = gacc_config[selected_gacc]['psas'].get(selected_psa, {}).get('fuel_model', '?')
    pstr = '  ·  '.join(
        f"P{p}: {bdata.get(f'p{p}','—')}" for p in [80, 90, 95, 97]
        if bdata.get(f'p{p}') is not None)

    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:16px;padding:12px 0 20px;flex-wrap:wrap;">
      <span style="font-family:'Bebas Neue',sans-serif;font-size:22px;color:{C['muted']};letter-spacing:3px;">{selected_psa}</span>
      <div class="{cls}">{lvl}</div>
      <span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:{C['muted']};">
        Today: <strong style="color:{C['text']}">{f'{td_val:.1f}' if td_val is not None else '—'}</strong>
        &nbsp;·&nbsp; Fuel Model: <strong style="color:{C['text']}">{fm_label}</strong>
        &nbsp;·&nbsp; {pstr}
      </span>
    </div>""", unsafe_allow_html=True)

    # ── Tabs ──────────────────────────────────────────────────────────────────
    t1, t2, t3, t4, t5, t6, t7 = st.tabs([
        '📈  7-Day Forecast', '📊  GACC Overview', '🔥  All Indices',
        '📉  ERC Trend', '🗺️  Heatmap', '⚖️  Percentile Context', '🗒️  Data Table'])

    # Tab 1 — 7-Day forecast for selected PSA
    # Build a fresh day_map for all chart rendering (always today's dates)
    import fems_fetcher as _ff
    _render_day_map = _ff._build_day_map()

    with t1:
        c_main, c_side = st.columns([3, 1])
        with c_main:
            st.plotly_chart(chart_7day(sel_dict, selected_field, fmeta, bdata,
                            selected_psa, day_map=_render_day_map),
                            use_container_width=True)
        with c_side:
            st.markdown(f"""<div style="background:{C['surface2']};border:1px solid {C['border']};
                        border-radius:6px;padding:16px;margin-top:12px;">
              <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:{C['muted']};
                          text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;">
                Climo — {fmeta['unit']}</div>""", unsafe_allow_html=True)
            for key, lbl, col in [('mean','Mean',C['teal']),('p80','80th',C['p80']),
                                   ('p90','90th',C['p90']),('p95','95th',C['p95']),('p97','97th',C['p97'])]:
                v = bdata.get(key, '—')
                st.markdown(f"""<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                  <span style="font-family:'JetBrains Mono',monospace;font-size:10px;color:{C['muted']}">{lbl}</span>
                  <span style="font-family:'Bebas Neue',sans-serif;font-size:20px;color:{col}">
                    {f'{v:.0f}' if isinstance(v, float) else v}</span></div>""", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

    # Tab 2 — GACC overview bars
    with t2:
        main_df = get_field_df(dfs, selected_field)
        if not main_df.empty:
            st.plotly_chart(chart_bar_today(main_df, selected_field, fmeta, baseline, selected_gacc),
                            use_container_width=True)
        others = [f for f in PRIMARY_FIELDS if f != selected_field]
        for i in range(0, len(others), 2):
            cols = st.columns(2)
            for cw, fk in zip(cols, others[i:i+2]):
                df2 = get_field_df(dfs, fk)
                if not df2.empty:
                    with cw:
                        st.plotly_chart(chart_bar_today(df2, fk, FIELD_META[fk], baseline, selected_gacc),
                                        use_container_width=True)

    # Tab 3 — All 9 indices for selected PSA
    with t3:
        st.markdown(f'<div style="font-family:JetBrains Mono,monospace;font-size:10px;color:{C["muted"]};'
                    f'text-transform:uppercase;letter-spacing:1.5px;margin:8px 0 16px;">All Indices — {selected_psa}</div>',
                    unsafe_allow_html=True)
        for fk_row, h in [(['erc','ic','bi','sc'], 280), (['fm1','fm10','fm100','fm1000'], 260)]:
            cols_r = st.columns(len(fk_row))
            for cw, fk in zip(cols_r, fk_row):
                df_f  = get_field_df(dfs, fk)
                rows_f = df_f[df_f['PSA'] == selected_psa] if not df_f.empty else pd.DataFrame()
                if rows_f.empty: continue
                b2 = get_psa_bdata(selected_gacc, selected_psa, baseline, fk)
                with cw:
                    fig = chart_7day(rows_f.iloc[0].to_dict(), fk, FIELD_META[fk], b2, selected_psa, height=h)
                    fig.update_layout(title=_title(FIELD_META[fk]['unit']))
                    st.plotly_chart(fig, use_container_width=True)
            if h == 280:
                st.markdown('<hr>', unsafe_allow_html=True)
        kbdi_df = get_field_df(dfs, 'kbdi')
        if not kbdi_df.empty:
            kr = kbdi_df[kbdi_df['PSA'] == selected_psa]
            if not kr.empty:
                b2 = get_psa_bdata(selected_gacc, selected_psa, baseline, 'kbdi')
                st.plotly_chart(chart_7day(kr.iloc[0].to_dict(), 'kbdi', FIELD_META['kbdi'], b2, selected_psa, day_map=_render_day_map),
                                use_container_width=True)

    # Tab 4 — ERC trend
    with t4:
        trend_df = get_field_df(dfs, 'trend')
        if not trend_df.empty:
            # Always build day_map from today's real date at render time
            # — never use the frozen day_map stored in the cache JSON
            import fems_fetcher as _ff
            _tdm   = _ff._build_day_map()
            t_days, t_lbls = _trend_day_labels(_tdm)
            c4a, c4b = st.columns([2, 3])
            with c4a:
                tr = trend_df[trend_df['PSA'] == selected_psa]
                if not tr.empty:
                    trow = tr.iloc[0]
                    vals = [float(trow.get(d) or 0) for d in t_days]
                    cbars = [C['crit'] if v > 3 else C['high'] if v > 0 else C['norm'] for v in vals]
                    fig = go.Figure()
                    fig.add_hline(y=0, line_color=C['border'], line_width=1)
                    fig.add_trace(go.Bar(x=t_lbls, y=vals, marker_color=cbars, marker_line_width=0,
                                         hovertemplate='<b>%{x}</b>: Δ ERC = <b>%{y:+.1f}</b><extra></extra>'))
                    fig.update_layout(**{**PL, 'title': _title(f'{selected_psa} ERC TREND'),
                                         'height': 300, 'yaxis': {**PL['yaxis'], 'title': 'Δ ERC vs Today'}})
                    st.plotly_chart(fig, use_container_width=True)
            with c4b:
                fig2 = go.Figure()
                palette = [C['fire'],C['teal'],C['gold'],C['p80'],C['p95'],C['p97'],C['p90'],'#74c0fc']
                for i, (_, row) in enumerate(trend_df.sort_values('PSA').iterrows()):
                    psa = row['PSA']
                    fig2.add_trace(go.Scatter(
                        x=t_lbls, y=[float(row.get(d) or 0) for d in t_days],
                        mode='lines', name=psa,
                        line=dict(color=palette[i % len(palette)],
                                  width=3 if psa == selected_psa else 1.2),
                        opacity=1.0 if psa == selected_psa else 0.35,
                        hovertemplate=f'<b>{psa}</b> · %{{x}}: <b>%{{y:+.1f}}</b><extra></extra>'))
                fig2.add_hline(y=0, line_color=C['border'], line_width=1)
                fig2.update_layout(**{**PL, 'title': _title('ERC TREND — All PSAs'),
                                      'height': 300, 'yaxis': {**PL['yaxis'], 'title': 'Δ ERC'}})
                st.plotly_chart(fig2, use_container_width=True)

    # Tab 5 — Heatmap
    with t5:
        trend_df = get_field_df(dfs, 'trend')
        if not trend_df.empty:
            st.plotly_chart(chart_trend_heatmap(trend_df), use_container_width=True)

    # Tab 6 — Percentile context
    with t6:
        main_df = get_field_df(dfs, selected_field)
        if not main_df.empty:
            st.plotly_chart(chart_pctile_grouped(main_df, selected_field, baseline, selected_gacc),
                            use_container_width=True)

    # Tab 7 — Data table
    with t7:
        field_opts = {fk: f"{FIELD_META[fk]['unit']} — {FIELD_META[fk]['label']}" for fk in ALL_FIELDS}
        fc = st.selectbox('Field', list(field_opts.keys()),
                          format_func=lambda f: field_opts[f], key='tbl_field')
        tbl_df = get_field_df(dfs, fc).copy()
        if tbl_df.empty:
            st.info('No data for this field.'); return
        search = st.text_input('🔍 Filter PSA', placeholder='e.g. GB21')
        if search:
            tbl_df = tbl_df[tbl_df['PSA'].str.contains(search.upper(), na=False)]
        num_cols = [c for c in ['yd','td','D+1','D+2','D+3','D+4','D+5','D+6',
                                 'Climo_Mean','P80','P90','P95','P97'] if c in tbl_df.columns]
        display_df = tbl_df.sort_values('PSA')[['PSA'] + num_cols].copy()
        for c in num_cols:
            display_df[c] = pd.to_numeric(display_df[c], errors='coerce').round(1)
        col_cfg = {c: st.column_config.NumberColumn(c, format='%.1f') for c in num_cols}
        st.dataframe(display_df, column_config=col_cfg, use_container_width=True, height=520)
        st.download_button(
            f'⬇ Download {FIELD_META[fc]["unit"]} CSV',
            tbl_df.sort_values('PSA').to_csv(index=False),
            f'{abbrev}_{fc}_{date.today()}.csv', 'text/csv')


if __name__ == '__main__':
    main()
