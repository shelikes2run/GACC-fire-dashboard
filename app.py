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
    'erc':    {'label':'Energy Release Component',  'unit':'ERC',     'color':'#ff4d00','pctile_flip':False},
    'ic':     {'label':'Ignition Component',        'unit':'IC',      'color':'#cc5de8','pctile_flip':False},
    'bi':     {'label':'Burning Index',             'unit':'BI',      'color':'#ffd700','pctile_flip':False},
    'sc':     {'label':'Spread Component',          'unit':'SC',      'color':'#ff6b6b','pctile_flip':False},
    'fm100':  {'label':'100-Hr Fuel Moisture',      'unit':'FM-100',  'color':'#00d4b4','pctile_flip':True},
    'fm1':    {'label':'1-Hr Fuel Moisture',        'unit':'FM-1',    'color':'#74c0fc','pctile_flip':True},
    'fm10':   {'label':'10-Hr Fuel Moisture',       'unit':'FM-10',   'color':'#63e6be','pctile_flip':True},
    'fm1000': {'label':'1000-Hr Fuel Moisture',     'unit':'FM-1000', 'color':'#a9e34b','pctile_flip':True},
    'kbdi':   {'label':'Keetch-Byram Drought Index','unit':'KBDI',    'color':'#f08c00','pctile_flip':False},
    'gsi':    {'label':'Grassland Spread Index',    'unit':'GSI',     'color':'#e9ff70','pctile_flip':False},
    'woody':  {'label':'Woody Fuel Moisture',       'unit':'Woody FM','color':'#8ce99a','pctile_flip':True},
    'herb':   {'label':'Herbaceous Fuel Moisture',  'unit':'Herb FM', 'color':'#b2f2bb','pctile_flip':True},
}
PRIMARY_FIELDS = ['erc','ic','bi','sc','fm100','kbdi']
ALL_FIELDS     = list(FIELD_META.keys())
DAY_COLS       = ['D-5','D-4','D-3','D-2','yd','td','D+1','D+2','D+3','D+4','D+5','D+6','D+7']
# DAY_LABELS are now computed at render time via _day_labels_from_map()
# so they always reflect today's date regardless of cache age.
CACHE_HOURS    = 6
CACHE_DIR      = Path('gacc_cache')
CLIMO_START    = 2005
CLIMO_END      = 2024
CACHE_DIR.mkdir(exist_ok=True)   # ensure dir exists at import time
HIST_HOURS  = 12   # history re-fetched twice daily (data changes slowly)
HIST_DAYS   = 30   # how many days of observed history to pull

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
    return [ff._day_label(day_map[k]) for k in ['D-5','D-4','D-3','D-2','yd','td','D+1','D+2','D+3','D+4','D+5','D+6','D+7']
            if k in day_map]



def _psa_info_popover(gacc_name, psa_id, gacc_config, baseline, field_key):
    """
    Render an ℹ button that expands to show:
      - Station IDs tied to this PSA (WIMS IDs linking to FAMWEB)
      - What the selected index measures
      - How climo percentiles were computed
    """
    info = gacc_config.get(gacc_name, {}).get('psas', {}).get(psa_id, {})
    stations   = info.get('stations', [])
    fuel_model = info.get('fuel_model', 'Y')
    fmeta      = FIELD_META.get(field_key, {})

    INDEX_DESCRIPTIONS = {
        'erc': ('Energy Release Component',
                'A number related to the available energy (British Thermal Units) per unit area '                'within the flaming front at the head of a fire. ERC is a composite of live and '                'dead fuel moisture and is computed daily. Higher values indicate drier, more '                'energetic conditions.'),
        'bi':  ('Burning Index',
                'An estimate of the potential difficulty of fire containment as it relates to '                'flame length at the head of a fire. BI is a daily MAXIMUM value — computed at '                'the time of peak fire danger (typically early afternoon), not a single-time '                'observation like ERC. This means BI climo values are naturally higher relative '                'to a single observed reading.'),
        'ic':  ('Ignition Component',
                'The probability that a firebrand will cause a fire requiring suppression. '                'Ranges from 0–100. Values ≥ 50 indicate high ignition probability.'),
        'sc':  ('Spread Component',
                'The rate of spread of a fire at the head under current conditions. '                'Expressed in chains per hour.'),
        'fm100':('100-Hour Fuel Moisture',
                'The moisture content of dead woody fuels 1–3 inches in diameter. '                'Responds slowly to weather changes (3–4 day lag). '                'Lower values = drier fuels = higher fire danger.'),
        'fm1':  ('1-Hour Fuel Moisture',
                'Moisture content of fine dead fuels (grass, needle litter). '                'Responds to weather within hours. Critical for fire starts.'),
        'fm10': ('10-Hour Fuel Moisture',
                'Moisture of dead woody fuels 0.25–1 inch diameter. 1-day lag.'),
        'fm1000':('1000-Hour Fuel Moisture',
                'Moisture of large dead woody fuels 3–8 inches diameter. '                'Changes very slowly — tracks long-term drought.'),
        'kbdi': ('Keetch-Byram Drought Index',
                'A measure of soil and duff drought on a 0–800 scale. '                '0 = field capacity (saturated). 800 = maximum drought. '                'Values > 400 indicate elevated wildfire potential.'),
    }

    idx_name, idx_desc = INDEX_DESCRIPTIONS.get(field_key, (fmeta.get('label',''), ''))

    with st.expander(f"ℹ  {psa_id} · {fmeta.get('unit',field_key)} info", expanded=False):
        # ── Station list ──
        st.markdown(
            f'<div style="font-family:JetBrains Mono,monospace;font-size:9px;'            f'text-transform:uppercase;letter-spacing:1px;color:{C["muted"]};margin-bottom:6px;">'            f'RAWS Stations — PSA {psa_id} · Fuel Model {fuel_model}</div>',
            unsafe_allow_html=True)
        if stations:
            chips = ' '.join(
                f'<a href="https://famweb.nwcg.gov/SSOLogin/RawsWeatherInfo.cfm?'                f'siteId={sid}" target="_blank" '                f'style="font-family:JetBrains Mono,monospace;font-size:10px;'                f'background:{C["surface2"]};border:1px solid {C["border"]};'                f'color:{C["teal"]};border-radius:3px;padding:2px 8px;'                f'text-decoration:none;display:inline-block;margin:2px;">{sid}</a>'
                for sid in stations
            )
            st.markdown(f'<div style="line-height:2">{chips}</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div style="font-family:JetBrains Mono,monospace;font-size:9px;'                f'color:{C["dim"]};margin-top:4px;">'                f'Station IDs are WIMS IDs. Click to view station details in FAMWEB.</div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div style="font-family:JetBrains Mono,monospace;font-size:10px;'                f'color:{C["muted"]};">No stations mapped for this PSA.</div>',
                unsafe_allow_html=True)

        st.markdown('<hr style="margin:10px 0">', unsafe_allow_html=True)

        # ── Index description ──
        st.markdown(
            f'<div style="font-family:JetBrains Mono,monospace;font-size:9px;'            f'text-transform:uppercase;letter-spacing:1px;color:{C["muted"]};margin-bottom:6px;">'            f'About {idx_name}</div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-family:Space Grotesk,sans-serif;font-size:12px;'            f'color:{C["text"]};line-height:1.6;">{idx_desc}</div>',
            unsafe_allow_html=True)

        st.markdown('<hr style="margin:10px 0">', unsafe_allow_html=True)

        # ── Data source ──
        st.markdown(
            f'<div style="font-family:JetBrains Mono,monospace;font-size:9px;'            f'text-transform:uppercase;letter-spacing:1px;color:{C["muted"]};margin-bottom:6px;">'            f'Data Sources</div>',
            unsafe_allow_html=True)
        st.markdown(f"""
        <div style="font-family:Space Grotesk,sans-serif;font-size:11px;color:{C['muted']};line-height:1.8;">
          <b style="color:{C['text']}">7-Day Forecast</b> — FEMS GraphQL API
          (<code>nfdrMinMax</code>, <code>nfdrType=Appended</code>).
          Observed data stitched to NWS 7-day operational forecast.
          Refreshed every 6 hours.<br>
          <b style="color:{C['text']}">30-Day History</b> — FEMS REST API
          (<code>download-nfdr-daily-summary</code>).
          Observed records only (<code>NFDRType=O</code>). Refreshed every 12 hours.<br>
          <b style="color:{C['text']}">Percentile Thresholds</b> — Pre-computed 2005–2024
          climatology baseline from FEMS (<code>download-nfdr-daily-summary</code>).
          Percentiles calculated across all calendar days in the 16-year period.
          P80/P90/P95/P97 represent the 80th, 90th, 95th, and 97th percentile
          of daily values for each PSA across the full climo window.
        </div>
        """, unsafe_allow_html=True)

def _trend_day_labels(day_map: dict) -> tuple:
    """Return (keys, labels) for the 7 trend columns td … D+6."""
    import fems_fetcher as ff
    keys   = ['D-5','D-4','D-3','D-2','yd','td','D+1','D+2','D+3','D+4','D+5','D+6','D+7']
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


def _hist_cache_path(abbrev):
    return CACHE_DIR / f'gacc_hist_{abbrev}.json'


def _hist_cache_fresh(abbrev):
    p = _hist_cache_path(abbrev)
    if not p.exists(): return False
    age = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds()
    return age < HIST_HOURS * 3600


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


def ensure_history_loaded(api_key, username, gacc_name, gacc_config, force=False):
    """
    Load 30-day observed history for gacc_name.
    Same priority logic as ensure_gacc_loaded:
      1. session_state + fresh cache → instant
      2. fresh cache on disk → fast read
      3. stale/missing → fetch from FEMS (~10-20s, cached 12h)
    Returns (hist_data_dict, source_str)
    """
    hist_key = f'hist_{gacc_name}'
    abbrev   = gacc_config[gacc_name]['abbrev']

    if not force and hist_key in st.session_state and _hist_cache_fresh(abbrev):
        return st.session_state[hist_key], 'cached'

    if not force and _hist_cache_fresh(abbrev):
        try:
            p    = _hist_cache_path(abbrev)
            data = json.loads(p.read_text(encoding='utf-8'))
            st.session_state[hist_key] = data
            return data, 'cached'
        except Exception:
            pass

    try:
        import fems_fetcher as ff
        ff.FEMS_API_KEY  = api_key
        ff.FEMS_USERNAME = username
        out_path = str(_hist_cache_path(abbrev))
        data = ff.fetch_psa_history(gacc_name, days=HIST_DAYS,
                                    output_path=out_path)
        st.session_state[hist_key] = data
        return data, 'live'
    except Exception as e:
        # If live fails and stale cache exists, use it
        p = _hist_cache_path(abbrev)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                st.session_state[hist_key] = data
                return data, 'cached (stale)'
            except Exception:
                pass
        raise e


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


def add_pctile_lines(fig, bdata, flip=False):
    """
    Draw climo reference lines.
    flip=True for fuel moisture: danger is LOW (dry), so P20 is the low-moisture
    threshold and we label it accordingly. For fire indices, high=danger.
    """
    if flip:
        # FM: low values are dangerous — show low percentiles as warning thresholds
        # P80/P90/P95/P97 stored in baseline are HIGH moisture (normal/wet side)
        # We invert: show them but label as the dry-side equivalent
        lines = [
            ('mean', C['teal'], 'dot',  1.5, 'Mean'),
            ('p80',  C['p80'],  'dot',  1.5, '20th (Dry)'),   # low side
            ('p90',  C['p90'],  'dash', 1.8, '10th (Very Dry)'),
            ('p95',  C['p95'],  'dash', 2.0, '5th (Critically Dry)'),
            ('p97',  C['p97'],  'dash', 2.2, '3rd (Extreme Dry)'),
        ]
    else:
        lines = [
            ('mean', C['teal'], 'dot',  1.5, 'Mean'),
            ('p80',  C['p80'],  'dot',  1.5, '80th'),
            ('p90',  C['p90'],  'dash', 1.8, '90th'),
            ('p95',  C['p95'],  'dash', 2.0, '95th'),
            ('p97',  C['p97'],  'dash', 2.2, '97th'),
        ]
    for key, color, dash, width, label in lines:
        val = bdata.get(key)
        if val is None: continue
        fig.add_hline(y=val, line_dash=dash, line_color=color, line_width=width,
                      opacity=0.75, annotation_text=f'{label}: {val:.0f}',
                      annotation_font_color=color, annotation_font_size=10,
                      annotation_position='right')


def chart_7day(row_dict, fk, fmeta, bdata, psa_id, height=380, day_map=None, type_dict=None):
    """
    13-day chart: 5 observed days + today + 7 forecast days.
    Observed segment: solid line, filled markers.
    Forecast segment: dashed line, open markers, shaded background.
    Climo percentile bands overlaid as reference lines.
    """
    import fems_fetcher as _ff
    dm       = day_map or _ff._build_day_map()
    day_keys = DAY_COLS
    x_labels = [_ff._day_label(dm.get(k, k)) for k in day_keys]
    vals     = [row_dict.get(d) for d in day_keys]
    color    = fmeta['color']

    # Determine split point: where observed ends and forecast begins
    # Use type_dict if available, otherwise split at td/D+1 boundary
    obs_keys = ['D-5','D-4','D-3','D-2','yd','td']
    fct_keys = ['D+1','D+2','D+3','D+4','D+5','D+6','D+7']

    obs_idx = [i for i, k in enumerate(day_keys) if k in obs_keys]
    fct_idx = [i for i, k in enumerate(day_keys) if k in fct_keys]

    obs_x = [x_labels[i] for i in obs_idx]
    obs_y = [vals[i]     for i in obs_idx]
    fct_x = [x_labels[i] for i in fct_idx]
    fct_y = [vals[i]     for i in fct_idx]

    # Stitch at boundary (share the Today point so lines connect)
    td_i = day_keys.index('td') if 'td' in day_keys else None
    if td_i is not None and vals[td_i] is not None:
        fct_x = [x_labels[td_i]] + fct_x
        fct_y = [vals[td_i]]     + fct_y

    fig = go.Figure()

    # Forecast shaded background
    if fct_x:
        fig.add_vrect(
            x0=x_labels[td_i] if td_i is not None else fct_x[0],
            x1=fct_x[-1],
            fillcolor='rgba(255,77,0,0.04)',
            layer='below', line_width=0,
            annotation_text='FORECAST',
            annotation_position='top right',
            annotation_font_color=C['muted'],
            annotation_font_size=9,
        )

    # P90-P97 risk band
    p90 = bdata.get('p90'); p97 = bdata.get('p97')
    if p90 is not None and p97 is not None:
        fig.add_trace(go.Scatter(
            x=x_labels + x_labels[::-1],
            y=[p97]*len(x_labels) + [p90]*len(x_labels),
            fill='toself', fillcolor='rgba(204,93,232,0.04)',
            line=dict(color='rgba(0,0,0,0)'),
            hoverinfo='skip', showlegend=False))

    # Observed segment — solid line, filled markers
    if obs_x:
        fig.add_trace(go.Scatter(
            x=obs_x, y=obs_y, mode='lines+markers',
            name=f'{fmeta["unit"]} (Obs)',
            line=dict(color=color, width=3),
            marker=dict(size=8, color=color, line=dict(color=C['bg'], width=2)),
            hovertemplate='<b>%{x}</b> (Obs)<br>' + fmeta['unit'] + ' = <b>%{y:.1f}</b><extra></extra>'))

    # Forecast segment — dashed line, open markers
    if fct_x:
        fig.add_trace(go.Scatter(
            x=fct_x, y=fct_y, mode='lines+markers',
            name=f'{fmeta["unit"]} (Fcst)',
            line=dict(color=color, width=2.5, dash='dot'),
            marker=dict(size=7, color=C['bg'], line=dict(color=color, width=2)),
            hovertemplate='<b>%{x}</b> (Fcst)<br>' + fmeta['unit'] + ' = <b>%{y:.1f}</b><extra></extra>'))

    add_pctile_lines(fig, bdata, flip=fmeta.get('pctile_flip', False))

    fig.update_layout(**{**PL,
        'title': _title(f'{psa_id} — {fmeta["label"]} · Observed & Forecast'),
        'height': height,
        'xaxis': {**PL['xaxis']},
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


def chart_history_trend(hist_data, psa_id, fk, baseline, gacc_name, height=360):
    """
    Line chart of 30-day observed history for one PSA, one field.
    Shows climo mean, P80, P90, P95, P97 as reference lines.
    """
    psa = hist_data.get('psa', {}).get(psa_id, {})
    if not psa:
        return go.Figure()

    dates = psa.get('dates', [])
    vals  = psa.get(fk, [])
    fmeta = FIELD_META[fk]
    bdata = get_psa_bdata(gacc_name, psa_id, baseline, fk)
    color = fmeta['color']

    # X-axis: short date labels
    xlabels = [__import__('datetime').date.fromisoformat(d).strftime('%b %-d') for d in dates]

    fig = go.Figure()

    # P90-P97 shaded band
    p90 = bdata.get('p90'); p97 = bdata.get('p97')
    if p90 is not None and p97 is not None and xlabels:
        fig.add_trace(go.Scatter(
            x=xlabels + xlabels[::-1],
            y=[p97]*len(xlabels) + [p90]*len(xlabels),
            fill='toself', fillcolor='rgba(255,77,0,0.05)',
            line=dict(color='rgba(0,0,0,0)'),
            hoverinfo='skip', showlegend=False))

    fig.add_trace(go.Scatter(
        x=xlabels, y=vals, mode='lines+markers',
        name=fmeta['unit'],
        line=dict(color=color, width=2.5),
        marker=dict(size=5, color=color, line=dict(color=C['bg'], width=1)),
        hovertemplate='<b>%{x}</b><br>' + fmeta['unit'] + ' = <b>%{y:.1f}</b><extra></extra>'))

    add_pctile_lines(fig, bdata, flip=fmeta.get('pctile_flip', False))

    meta = hist_data.get('meta', {})
    def _fmt_d(s):
        try: return __import__('datetime').date.fromisoformat(s).strftime('%b %-d')
        except: return s[5:] if len(s) >= 7 else s
    date_range = f"{_fmt_d(meta.get('start_date',''))} → {_fmt_d(meta.get('end_date',''))}"
    fig.update_layout(**{**PL,
        'title': _title(f'{psa_id} — {fmeta["label"]} ({date_range})'),
        'height': height,
        'xaxis': {**PL['xaxis'], 'tickangle': -45},
        'yaxis': {**PL['yaxis'], 'title': fmeta['unit']}})
    return fig


def chart_history_all_psas(hist_data, fk, baseline, gacc_name, selected_psa, height=340):
    """
    Multi-line chart: 30-day ERC (or any field) for ALL PSAs.
    Selected PSA is highlighted; others are dimmed.
    """
    psa_dict = hist_data.get('psa', {})
    fmeta    = FIELD_META[fk]
    palette  = [C['fire'],C['teal'],C['gold'],C['p80'],C['p95'],C['p97'],C['p90'],'#74c0fc',
                '#a9e34b','#63e6be','#74c0fc','#e599f7']
    fig = go.Figure()
    for i, (psa_id, psa) in enumerate(sorted(psa_dict.items())):
        dates = psa.get('dates', [])
        vals  = psa.get(fk, [])
        if not dates: continue
        is_sel = psa_id == selected_psa
        fig.add_trace(go.Scatter(
            x=[__import__('datetime').date.fromisoformat(d).strftime('%b %-d') for d in dates], y=vals,
            mode='lines', name=psa_id,
            line=dict(color=palette[i % len(palette)], width=3 if is_sel else 1),
            opacity=1.0 if is_sel else 0.25,
            hovertemplate=f'<b>{psa_id}</b> · %{{x}}: <b>%{{y:.1f}}</b><extra></extra>'))

    meta = hist_data.get('meta', {})
    def _fmt_d(s):
        try: return __import__('datetime').date.fromisoformat(s).strftime('%b %-d')
        except: return s[5:] if len(s) >= 7 else s
    date_range = f"{_fmt_d(meta.get('start_date',''))} → {_fmt_d(meta.get('end_date',''))}"
    fig.update_layout(**{**PL,
        'title': _title(f'{fmeta["label"]} — All PSAs ({date_range})'),
        'height': height,
        'xaxis': {**PL['xaxis'], 'tickangle': -45},
        'yaxis': {**PL['yaxis'], 'title': fmeta['unit']}})
    return fig


def chart_history_heatmap(hist_data, fk, baseline, gacc_name):
    """
    Heatmap: PSA × date, colored by value relative to P90 threshold.
    Color scale: green (below P90) → dark (near P90) → orange/red (above P90/P97).
    """
    psa_dict = hist_data.get('psa', {})
    fmeta    = FIELD_META[fk]
    if not psa_dict:
        return go.Figure()

    psas      = sorted(psa_dict.keys())
    all_dates = sorted({d for psa in psa_dict.values() for d in psa.get('dates', [])})
    xlabels   = [__import__('datetime').date.fromisoformat(d).strftime('%b %-d') for d in all_dates]

    z         = []
    hover     = []
    for psa_id in psas:
        psa    = psa_dict.get(psa_id, {})
        dates  = psa.get('dates', [])
        vals   = psa.get(fk, [])
        bdata  = get_psa_bdata(gacc_name, psa_id, baseline, fk)
        p90    = bdata.get('p90')
        date_val = dict(zip(dates, vals))
        row    = []
        htxt   = []
        for d in all_dates:
            v = date_val.get(d)
            row.append(float(v) if v is not None else None)
            _dl = __import__('datetime').date.fromisoformat(d).strftime('%b %-d')
            if v is not None and p90:
                pct_str = f'{v/p90*100:.0f}% of P90'
                htxt.append(f'{psa_id}<br>{_dl}<br>{fmeta["unit"]}={v:.1f}<br>{pct_str}')
            else:
                htxt.append(f'{psa_id}<br>{_dl}<br>No data')
        z.append(row)
        hover.append(htxt)

    _fm_fields = {'fm1','fm10','fm100','fm1000'}
    _cs = (
        [[0.00,'#ff2d55'],[0.12,'#ff6b00'],[0.25,'#1a1e2e'],[0.45,'#1a1e2e'],[1.00,'#00c875']]
        if fk in _fm_fields else
        [[0.00,'#00c875'],[0.55,'#1a1e2e'],[0.75,'#1a1e2e'],[0.88,'#ff6b00'],[1.00,'#ff2d55']]
    )
    fig = go.Figure(go.Heatmap(
        z=z, x=xlabels, y=psas,
        customdata=hover,
        hovertemplate='%{customdata}<extra></extra>',
        colorscale=_cs,
        colorbar=dict(
            title=dict(text=fmeta['unit'], font=dict(color=C['muted'])),
            tickfont=dict(color=C['muted'], size=9, family='JetBrains Mono'),
            len=0.8),
    ))
    meta = hist_data.get('meta', {})
    def _fmt_d(s):
        try: return __import__('datetime').date.fromisoformat(s).strftime('%b %-d')
        except: return s[5:] if len(s) >= 7 else s
    date_range = f"{_fmt_d(meta.get('start_date',''))} → {_fmt_d(meta.get('end_date',''))}"
    fig.update_layout(**{**PL,
        'title': _title(f'{fmeta["label"]} HEATMAP — PSA × DATE ({date_range})'),
        'height': max(400, len(psas)*18 + 120),
        'xaxis': {**PL['xaxis'], 'tickangle': -45, 'nticks': 15},
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
          Climo: {meta.get('climo_start',2005)}–{meta.get('climo_end',2024)}<br>
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

    # Load 30-day history for Trend + Heatmap tabs (separate fetch, 12h cache)
    # Non-blocking: if history fetch fails, tabs show a friendly message
    hist_data   = None
    hist_source = 'none'
    hist_abbrev = gacc_config[selected_gacc]['abbrev']
    try:
        hist_spinner = (st.spinner(f'Loading {hist_abbrev} history...')
                        if not _hist_cache_fresh(hist_abbrev) else _nullctx())
        with hist_spinner:
            hist_data, hist_source = ensure_history_loaded(
                api_key, username, selected_gacc, gacc_config)
    except Exception as hist_err:
        # History is non-critical — dashboard still works without it
        hist_data = None

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
            5-Day Obs + 7-Day NFDR Forecast · ERC · IC · BI · SC · FM · KBDI · GSI ·
            Climo {meta.get('climo_start',2005)}–{meta.get('climo_end',2024)} Baseline
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
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs([
        '📈  7-Day Forecast', '📊  GACC Overview', '🔥  All Indices',
        '📉  ERC Trend', '🗺️  Heatmap', '⚖️  Percentile Context', '🗒️  Data Table',
        'ℹ️  About & Data'])

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

        # Info panel — stations + index description + data source
        _psa_info_popover(selected_gacc, selected_psa, gacc_config, baseline, selected_field)

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

    # Tab 4 — 30-Day ERC Trend (historical observed + climo bands)
    with t4:
        st.markdown(f'''<div style="background:{C['surface2']};border:1px solid {C['border']};
            border-left:3px solid {C['gold']};border-radius:4px;padding:8px 14px;margin-bottom:12px;
            font-family:JetBrains Mono,monospace;font-size:10px;color:{C['muted']};">
            📡 Based on key RAWS stations only — see About & Data tab for station list
            &nbsp;·&nbsp; Climo baseline: {baseline.get('meta',{}).get('climo_start',2005)}–{baseline.get('meta',{}).get('climo_end',2024)} observed data
        </div>''', unsafe_allow_html=True)
        if hist_data is None:
            st.info('Historical data unavailable — check FEMS connectivity.')
        else:
            # Field selector for trend tab
            trend_fk = st.radio('Index', PRIMARY_FIELDS,
                                 format_func=lambda f: FIELD_META[f]['unit'],
                                 horizontal=True, key='trend_field')
            c4a, c4b = st.columns([1, 2])
            with c4a:
                # Single PSA: 30-day line with climo bands
                st.plotly_chart(
                    chart_history_trend(hist_data, selected_psa, trend_fk, baseline, selected_gacc),
                    use_container_width=True)
            with c4b:
                # All PSAs overlay — selected PSA highlighted
                st.plotly_chart(
                    chart_history_all_psas(hist_data, trend_fk, baseline, selected_gacc, selected_psa),
                    use_container_width=True)

    # Tab 5 — 30-Day Heatmap (PSA × date, colored by value)
    with t5:
        st.markdown(f'''<div style="background:{C['surface2']};border:1px solid {C['border']};
            border-left:3px solid {C['gold']};border-radius:4px;padding:8px 14px;margin-bottom:12px;
            font-family:JetBrains Mono,monospace;font-size:10px;color:{C['muted']};">
            📡 Based on key RAWS stations only — see About & Data tab for station list
            &nbsp;·&nbsp; FM fields: red = dry (low moisture) = danger · Fire indices: red = high = danger
        </div>''', unsafe_allow_html=True)
        if hist_data is None:
            st.info('Historical data unavailable — check FEMS connectivity.')
        else:
            hm_fk = st.radio('Index', PRIMARY_FIELDS,
                              format_func=lambda f: FIELD_META[f]['unit'],
                              horizontal=True, key='heatmap_field')
            st.plotly_chart(
                chart_history_heatmap(hist_data, hm_fk, baseline, selected_gacc),
                use_container_width=True)

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
        num_cols = [c for c in ['D-5','D-4','D-3','D-2','yd','td','D+1','D+2','D+3','D+4','D+5','D+6','D+7',
                                 'Climo_Mean','P80','P90','P95','P97'] if c in tbl_df.columns]
        display_df = tbl_df.sort_values('PSA')[['PSA'] + num_cols].copy()
        for c in num_cols:
            display_df[c] = pd.to_numeric(display_df[c], errors='coerce').round(1)
        import fems_fetcher as _ff
        _dm_tbl = _ff._build_day_map()
        _inv    = {v: k for k, v in _dm_tbl.items()}  # date→label
        _label  = lambda c: (
            'Yesterday' if c == 'yd' else
            'Today'     if c == 'td' else
            _ff._day_label(_dm_tbl.get(c, c)) if c.startswith('D+') else c
        )
        col_cfg = {c: st.column_config.NumberColumn(_label(c), format='%.1f') for c in num_cols}
        st.dataframe(display_df, column_config=col_cfg, use_container_width=True, height=520)
        st.download_button(
            f'⬇ Download {FIELD_META[fc]["unit"]} CSV',
            tbl_df.sort_values('PSA').to_csv(index=False),
            f'{abbrev}_{fc}_{date.today()}.csv', 'text/csv')


def check_password():
    """
    Simple password gate — shown before any dashboard content.
    Password is set via Streamlit secrets (DASHBOARD_PASSWORD) or falls back
    to an environment variable. Remove the check_password() call from the
    bottom of this file once QC is complete.

    To set the password on Streamlit Cloud:
      App Settings → Secrets → add:
        DASHBOARD_PASSWORD = "your_password_here"

    To set locally, add to .env:
        DASHBOARD_PASSWORD=your_password_here
    """
    # Retrieve password from secrets or env
    try:
        correct_pw = st.secrets['DASHBOARD_PASSWORD']
    except Exception:
        correct_pw = os.getenv('DASHBOARD_PASSWORD', '')

    if not correct_pw:
        # No password configured — pass through silently
        return True

    # Already authenticated this session
    if st.session_state.get('_authenticated'):
        return True

    # ── Password screen ───────────────────────────────────────────────────────
    st.markdown("""
    <style>
    .pw-wrap {
        max-width: 420px;
        margin: 12vh auto 0;
        background: #1a1e2e;
        border: 1px solid #2a3050;
        border-top: 3px solid #ff4d00;
        border-radius: 8px;
        padding: 40px 36px 32px;
    }
    .pw-title {
        font-family: 'Bebas Neue', sans-serif;
        font-size: 32px;
        letter-spacing: 4px;
        color: #e8eaf6;
        line-height: 1;
        margin-bottom: 4px;
    }
    .pw-sub {
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        color: #6b7299;
        letter-spacing: 2px;
        text-transform: uppercase;
        margin-bottom: 28px;
    }
    .pw-note {
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        color: #3a3f6b;
        text-align: center;
        margin-top: 20px;
        letter-spacing: 1px;
    }
    </style>
    """, unsafe_allow_html=True)

    col = st.columns([1, 2, 1])[1]
    with col:
        st.markdown("""
        <div class="pw-wrap">
          <div class="pw-title">🔥 FIRE WEATHER</div>
          <div class="pw-sub">GACC Intelligence Dashboard — QC Preview</div>
        </div>
        """, unsafe_allow_html=True)

        pw_input = st.text_input(
            'Access password',
            type='password',
            placeholder='Enter password…',
            label_visibility='collapsed',
        )

        if st.button('Enter →', use_container_width=True, type='primary'):
            if pw_input == correct_pw:
                st.session_state['_authenticated'] = True
                st.rerun()
            else:
                st.error('Incorrect password — try again.')

        st.markdown(
            '<div class="pw-note">QC preview · contact dashboard admin for access</div>',
            unsafe_allow_html=True)

    return False


    # Tab 8 — About & Methodology
    with t8:
        _abbrev = gacc_config[selected_gacc]['abbrev']
        _n_psas = len(gacc_config[selected_gacc]['psas'])
        _n_stns = len(set(
            s for info in gacc_config[selected_gacc]['psas'].values()
            for s in info.get('stations', [])
        ))

        # Build station list for selected PSA
        _psa_stns = gacc_config[selected_gacc]['psas'].get(selected_psa, {}).get('stations', [])
        _fuel_mdl = gacc_config[selected_gacc]['psas'].get(selected_psa, {}).get('fuel_model', '?')

        climo_start = baseline.get('meta', {}).get('climo_start', 2005)
        climo_end   = baseline.get('meta', {}).get('climo_end',   2024)

        st.markdown(f"""
        <div style="max-width:860px;">

        <div style="font-family:'Bebas Neue',sans-serif;font-size:26px;color:{C['text']};
                    letter-spacing:3px;margin-bottom:4px;">About This Dashboard</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:{C['muted']};
                    letter-spacing:2px;text-transform:uppercase;margin-bottom:24px;">
            {_abbrev} Fire Weather Intelligence · Data Source & Methodology
        </div>

        <div style="background:{C['surface']};border:1px solid {C['border']};border-left:3px solid {C['fire']};
                    border-radius:6px;padding:20px 24px;margin-bottom:16px;">
          <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:{C['fire']};
                      text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;">
            📊 Data Source
          </div>
          <div style="font-family:'Space Grotesk',sans-serif;font-size:13px;color:{C['text']};line-height:1.8;">
            All fire weather indices (ERC, IC, BI, SC) and fuel moisture values are retrieved from the
            <strong>USDA Forest Service Fire & Environment Management System (FEMS)</strong>
            via the <code style="background:{C['surface2']};padding:1px 5px;border-radius:3px;font-size:11px;">
            download-nfdr-daily-summary</code> API endpoint.
            <br><br>
            Live 7-day forecasts are fetched every 6 hours. The 30-day historical trend uses
            observed rows only (<code style="background:{C['surface2']};padding:1px 5px;border-radius:3px;font-size:11px;">
            NFDRType = O</code>), refreshed every 12 hours.
          </div>
        </div>

        <div style="background:{C['surface']};border:1px solid {C['border']};border-left:3px solid {C['teal']};
                    border-radius:6px;padding:20px 24px;margin-bottom:16px;">
          <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:{C['teal']};
                      text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;">
            📐 Climatology Baseline ({climo_start}–{climo_end})
          </div>
          <div style="font-family:'Space Grotesk',sans-serif;font-size:13px;color:{C['text']};line-height:1.8;">
            Percentile thresholds are derived from <strong>{climo_start}–{climo_end} observed NFDR data</strong>
            downloaded from FEMS for every key RAWS station in each PSA.
            <br><br>
            <strong>Averaging method:</strong> For each PSA, daily values are averaged across all
            contributing stations to produce one daily PSA value. Percentiles are then computed
            across all daily values in the full {climo_end - climo_start + 1}-year period.
            <br><br>
            <strong>Percentile thresholds:</strong>
            <br>
          </div>
          <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:8px;">
            <div style="background:{C['surface2']};border:1px solid {C['border']};border-top:2px solid {C['p80']};
                        border-radius:4px;padding:10px;text-align:center;">
              <div style="font-family:'Bebas Neue',sans-serif;font-size:22px;color:{C['p80']};">80th</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:{C['muted']};text-transform:uppercase;">
                Above Average<br>Fire Weather</div>
            </div>
            <div style="background:{C['surface2']};border:1px solid {C['border']};border-top:2px solid {C['p90']};
                        border-radius:4px;padding:10px;text-align:center;">
              <div style="font-family:'Bebas Neue',sans-serif;font-size:22px;color:{C['p90']};">90th</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:{C['muted']};text-transform:uppercase;">
                Elevated<br>Fire Potential</div>
            </div>
            <div style="background:{C['surface2']};border:1px solid {C['border']};border-top:2px solid {C['p95']};
                        border-radius:4px;padding:10px;text-align:center;">
              <div style="font-family:'Bebas Neue',sans-serif;font-size:22px;color:{C['p95']};">95th</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:{C['muted']};text-transform:uppercase;">
                High<br>Fire Potential</div>
            </div>
            <div style="background:{C['surface2']};border:1px solid {C['border']};border-top:2px solid {C['p97']};
                        border-radius:4px;padding:10px;text-align:center;">
              <div style="font-family:'Bebas Neue',sans-serif;font-size:22px;color:{C['p97']};">97th</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:{C['muted']};text-transform:uppercase;">
                Critical<br>Fire Potential</div>
            </div>
          </div>
        </div>

        <div style="background:{C['surface']};border:1px solid {C['border']};border-left:3px solid {C['gold']};
                    border-radius:6px;padding:20px 24px;margin-bottom:16px;">
          <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:{C['gold']};
                      text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;">
            📡 Key RAWS Stations — {_abbrev} · PSA {selected_psa}
          </div>
          <div style="font-family:'Space Grotesk',sans-serif;font-size:13px;color:{C['text']};line-height:1.8;">
            <strong>Important:</strong> This dashboard uses a curated set of
            <strong>key RAWS stations</strong> for each PSA, as defined in the
            GACC fire weather program. Not all RAWS stations within each PSA boundary
            are included — only those designated as representative for climatological
            and fire weather decision support purposes.
            <br><br>
            PSA <strong>{selected_psa}</strong> uses <strong>{len(_psa_stns)} key station{'s' if len(_psa_stns) != 1 else ''}</strong>
            (Fuel Model <strong>{_fuel_mdl}</strong>):
          </div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:11px;color:{C['p80']};
                      margin-top:10px;word-break:break-all;">
            {', '.join(str(s) for s in _psa_stns) if _psa_stns else 'No stations configured'}
          </div>
          <div style="font-family:'Space Grotesk',sans-serif;font-size:12px;color:{C['muted']};margin-top:12px;">
            {_abbrev} total: {_n_psas} PSAs · {_n_stns} unique key RAWS stations
          </div>
        </div>

        <div style="background:{C['surface']};border:1px solid {C['border']};border-left:3px solid {C['muted']};
                    border-radius:6px;padding:20px 24px;margin-bottom:16px;">
          <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:{C['muted']};
                      text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;">
            ⚠️  Fuel Moisture Index Interpretation
          </div>
          <div style="font-family:'Space Grotesk',sans-serif;font-size:13px;color:{C['text']};line-height:1.8;">
            Fuel moisture indices (1-Hr, 10-Hr, 100-Hr, 1000-Hr FM) are interpreted
            <strong>inversely</strong> compared to fire behavior indices.
            <strong>Lower fuel moisture = drier fuels = greater fire danger.</strong>
            <br><br>
            On trend and heatmap charts, the colorscale for FM fields is reversed:
            red indicates critically low (dry) moisture, green indicates adequate moisture.
            Percentile reference lines are labeled to reflect the dry-side thresholds.
          </div>
        </div>

        <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:{C['dim']};margin-top:8px;line-height:2;">
          Dashboard built for internal GACC fire weather operations · Data: USDA FS FEMS ·
          Climo baseline: {climo_start}–{climo_end} · Refreshed 6h (forecast) / 12h (history)
        </div>

        </div>
        """, unsafe_allow_html=True)

        # Also add Key RAWS disclaimer to Trend and Heatmap tabs at top
        # (handled separately with a small banner in those tabs)


if __name__ == '__main__':
    if check_password():
        main()
