"""
GACC Fire Weather Intelligence Dashboard
─────────────────────────────────────────
Sidebar: pick GACC → pick PSA
Loads climo baselines from gacc_climo_baseline.json (pre-built offline)
Fetches live 7-day ERC/F100/BI/IC forecast from FEMS REST API
Shows percentile reference lines + trend charts matching the HTML dashboard aesthetic
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json, os
from datetime import datetime, date
from pathlib import Path

st.set_page_config(
    page_title="GACC Fire Weather Intelligence",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Design system — matches the HTML dashboard exactly ───────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --bg:       #0d0f1a;
  --bg2:      #12151f;
  --surface:  #1a1e2e;
  --surface2: #222740;
  --border:   #2a3050;
  --fire:     #ff4d00;
  --fire2:    #ff6b35;
  --gold:     #ffd700;
  --teal:     #00d4b4;
  --text:     #e8eaf6;
  --muted:    #6b7299;
  --dim:      #3a3f6b;
  --crit:     #ff2d55;
  --high:     #ff6b00;
  --elev:     #ffcc00;
  --norm:     #00c875;
  --p80:      #4dabf7;
  --p90:      #ffa94d;
  --p95:      #ff6b6b;
  --p97:      #cc5de8;
}

.stApp { background: var(--bg) !important; }

section[data-testid="stSidebar"] {
  background: var(--bg2) !important;
  border-right: 1px solid var(--border) !important;
}
section[data-testid="stSidebar"] > div { padding-top: 0 !important; }

html, body, [class*="css"] {
  font-family: 'Space Grotesk', sans-serif;
  color: var(--text);
}

/* Metric cards */
[data-testid="metric-container"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-top: 3px solid var(--fire) !important;
  border-radius: 6px !important;
  padding: 14px 18px !important;
}
[data-testid="metric-container"] label {
  color: var(--muted) !important;
  font-size: 10px !important;
  text-transform: uppercase !important;
  letter-spacing: 1.2px !important;
  font-family: 'JetBrains Mono', monospace !important;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
  font-family: 'Bebas Neue', sans-serif !important;
  font-size: 36px !important;
  color: var(--text) !important;
  line-height: 1.1 !important;
}
[data-testid="metric-container"] [data-testid="stMetricDelta"] {
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 10px !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
  background: var(--surface) !important;
  border-radius: 4px !important;
  padding: 3px !important;
  border: 1px solid var(--border) !important;
  gap: 2px !important;
}
.stTabs [data-baseweb="tab"] {
  background: transparent !important;
  color: var(--muted) !important;
  border-radius: 3px !important;
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 10px !important;
  letter-spacing: 1px !important;
  text-transform: uppercase !important;
  padding: 7px 16px !important;
  border: none !important;
}
.stTabs [aria-selected="true"] {
  background: var(--fire) !important;
  color: white !important;
}

/* Selectbox */
.stSelectbox > div > div {
  background: var(--surface2) !important;
  border: 1px solid var(--border) !important;
  color: var(--text) !important;
  border-radius: 4px !important;
  font-family: 'Space Grotesk', sans-serif !important;
}
.stSelectbox label {
  color: var(--muted) !important;
  font-size: 10px !important;
  text-transform: uppercase !important;
  letter-spacing: 1px !important;
  font-family: 'JetBrains Mono', monospace !important;
}

/* Buttons */
.stButton > button {
  background: var(--surface2) !important;
  border: 1px solid var(--border) !important;
  color: var(--text) !important;
  border-radius: 4px !important;
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 11px !important;
  letter-spacing: 0.5px !important;
  transition: all 0.15s !important;
}
.stButton > button:hover {
  border-color: var(--fire) !important;
  color: var(--fire) !important;
}

/* Radio */
.stRadio [data-testid="stWidgetLabel"] {
  color: var(--muted) !important;
  font-size: 10px !important;
  text-transform: uppercase !important;
  letter-spacing: 1px !important;
  font-family: 'JetBrains Mono', monospace !important;
}

#MainMenu, footer, header { visibility: hidden; }
hr { border-color: var(--border) !important; opacity: 0.4 !important; }

/* Status badges */
.badge-live {
  background: rgba(0,200,117,0.1);
  border: 1px solid rgba(0,200,117,0.35);
  color: #00c875;
  border-radius: 4px;
  padding: 8px 12px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  line-height: 1.9;
}
.badge-cached {
  background: rgba(255,214,0,0.08);
  border: 1px solid rgba(255,214,0,0.3);
  color: #ffd700;
  border-radius: 4px;
  padding: 8px 12px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  line-height: 1.9;
}
.badge-err {
  background: rgba(255,45,85,0.1);
  border: 1px solid rgba(255,45,85,0.4);
  color: #ff2d55;
  border-radius: 4px;
  padding: 16px 20px;
  font-family: 'Space Grotesk', sans-serif;
  font-size: 13px;
  line-height: 1.6;
}

/* PSA selection pill bar */
.psa-label {
  display: inline-block;
  background: var(--surface2);
  border: 1px solid var(--dim);
  color: var(--muted);
  border-radius: 3px;
  padding: 4px 10px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  margin: 2px;
}

/* Alert level badge */
.alert-crit { background:#ff2d5522; border:1px solid #ff2d55; color:#ff2d55; border-radius:3px; padding:4px 12px; font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; letter-spacing:1px; }
.alert-high { background:#ff6b0022; border:1px solid #ff6b00; color:#ff6b00; border-radius:3px; padding:4px 12px; font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; letter-spacing:1px; }
.alert-elev { background:#ffcc0022; border:1px solid #ffcc00; color:#ffcc00; border-radius:3px; padding:4px 12px; font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; letter-spacing:1px; }
.alert-norm { background:#00c87522; border:1px solid #00c875; color:#00c875; border-radius:3px; padding:4px 12px; font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; letter-spacing:1px; }
</style>
""", unsafe_allow_html=True)

# ── Palette & plotly base ─────────────────────────────────────────────────────
C = dict(
    bg='#0d0f1a', surface='#1a1e2e', surface2='#222740', border='#2a3050',
    fire='#ff4d00', fire2='#ff6b35', gold='#ffd700', teal='#00d4b4',
    text='#e8eaf6', muted='#6b7299', dim='#3a3f6b',
    crit='#ff2d55', high='#ff6b00', elev='#ffcc00', norm='#00c875',
    p80='#4dabf7', p90='#ffa94d', p95='#ff6b6b', p97='#cc5de8',
)

PL = dict(
    paper_bgcolor=C['surface'], plot_bgcolor=C['surface'],
    font=dict(color=C['text'], family='Space Grotesk, sans-serif'),
    margin=dict(t=48, b=48, l=52, r=24),
    legend=dict(bgcolor=C['surface2'], bordercolor=C['border'], borderwidth=1,
                font=dict(size=10, color=C['muted']), orientation='h',
                y=-0.18, x=0),
    xaxis=dict(gridcolor=C['border'], linecolor=C['border'],
               tickfont=dict(color=C['muted'], size=10, family='JetBrains Mono'),
               title_font=dict(color=C['muted'], size=11)),
    yaxis=dict(gridcolor=C['border'], linecolor=C['border'],
               tickfont=dict(color=C['muted'], size=10, family='JetBrains Mono'),
               title_font=dict(color=C['muted'], size=11)),
)

DAY_COLS   = ['yd', 'td', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']
DAY_LABELS = ['Yesterday', 'Today', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']
CACHE_FILE = Path('gacc_data.json')
CACHE_HOURS = 6

FIELD_META = {
    'ERC':  dict(label='Energy Release Component', unit='ERC', color=C['fire'],  pctile_flip=False),
    'FM':   dict(label='100-hr Fuel Moisture',      unit='%',   color=C['teal'],  pctile_flip=True),   # lower=worse
    'BI':   dict(label='Burning Index',             unit='BI',  color=C['gold'],  pctile_flip=False),
    'IC':   dict(label='Ignition Component',        unit='IC',  color=C['p95'],   pctile_flip=False),
}

PCTILE_COLORS = {'P80': C['p80'], 'P90': C['p90'], 'P95': C['p95'], 'P97': C['p97']}


# ── Credential loader ─────────────────────────────────────────────────────────
def _creds():
    try:
        k = st.secrets['FEMS_API_KEY']; u = st.secrets['FEMS_USERNAME']
        if k and u: return k, u
    except Exception:
        pass
    try:
        from dotenv import load_dotenv; load_dotenv()
    except ImportError:
        pass
    return os.getenv('FEMS_API_KEY', ''), os.getenv('FEMS_USERNAME', '')


def _cache_fresh():
    if not CACHE_FILE.exists(): return False
    age = (datetime.now() - datetime.fromtimestamp(CACHE_FILE.stat().st_mtime)).total_seconds()
    return age < CACHE_HOURS * 3600


# ── Load GACC config ──────────────────────────────────────────────────────────
@st.cache_resource
def load_gacc_config():
    import importlib.util, sys
    cfg_path = Path('gacc_config.py')
    if not cfg_path.exists():
        return {}
    spec = importlib.util.spec_from_file_location('gacc_config', cfg_path)
    gc   = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gc)
    return gc.GACC_CONFIG


# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=CACHE_HOURS * 3600, show_spinner=False)
def load_live(api_key, username, gacc_name, psa_ids):
    import fems_fetcher as ff
    ff.FEMS_API_KEY = api_key
    ff.FEMS_USERNAME = username
    data = ff.fetch_psa_forecast(gacc_name, psa_ids, output_path=str(CACHE_FILE))
    return ff.json_to_dataframes(data), data['meta']


@st.cache_data(show_spinner=False)
def load_cached():
    import fems_fetcher as ff
    data = json.loads(CACHE_FILE.read_text())
    return ff.json_to_dataframes(data), data['meta']


@st.cache_data(show_spinner=False)
def load_baseline():
    p = Path('gacc_climo_baseline.json')
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def get_psa_baseline(gacc_name, psa_id, baseline):
    key = f'{gacc_name}|{psa_id}'
    return baseline.get('psa', {}).get(key, {})


# ── Alert level ───────────────────────────────────────────────────────────────
def alert_level(val, p90, p95, p97):
    if val is None: return 'UNKNOWN', C['dim'], 'alert-norm'
    if p97 and val >= p97: return 'CRITICAL', C['crit'], 'alert-crit'
    if p95 and val >= p95: return 'HIGH',     C['high'], 'alert-high'
    if p90 and val >= p90: return 'ELEVATED', C['elev'], 'alert-elev'
    return 'NORMAL', C['norm'], 'alert-norm'


# ── Plotly helpers ────────────────────────────────────────────────────────────
def _pctile_lines(fig, baseline_entry, field_key):
    """Add mean + percentile horizontal reference lines to fig."""
    fdata = baseline_entry.get(field_key.lower(), {})
    styles = [
        ('mean',  C['teal'],  'dot',  1.5, 'Mean'),
        ('p80',   C['p80'],   'dot',  1.5, '80th'),
        ('p90',   C['p90'],   'dash', 1.8, '90th'),
        ('p95',   C['p95'],   'dash', 2.0, '95th'),
        ('p97',   C['p97'],   'dash', 2.2, '97th'),
    ]
    for key, color, dash, width, label in styles:
        val = fdata.get(key)
        if val is None: continue
        fig.add_hline(
            y=val, line_dash=dash, line_color=color, line_width=width, opacity=0.75,
            annotation_text=f"{label}: {val:.0f}",
            annotation_font_color=color, annotation_font_size=10,
            annotation_position='right',
        )


def chart_7day(psa_data, field_key, field_meta, baseline_entry, psa_id):
    """7-day forecast line chart with percentile reference lines."""
    vals   = [psa_data.get(d) for d in DAY_COLS]
    color  = field_meta['color']

    fig = go.Figure()

    # Shaded risk band p90→p97
    fdata = baseline_entry.get(field_key.lower(), {})
    p90 = fdata.get('p90'); p97 = fdata.get('p97')
    if p90 and p97:
        fig.add_trace(go.Scatter(
            x=DAY_LABELS + DAY_LABELS[::-1],
            y=[p97]*8 + [p90]*8,
            fill='toself', fillcolor='rgba(255,77,0,0.06)',
            line=dict(color='rgba(0,0,0,0)'), hoverinfo='skip', showlegend=False,
        ))

    fig.add_trace(go.Scatter(
        x=DAY_LABELS, y=vals, mode='lines+markers',
        name=field_meta['unit'],
        line=dict(color=color, width=3),
        marker=dict(size=9, color=color, line=dict(color=C['bg'], width=2)),
        hovertemplate=f'<b>%{{x}}</b><br>{field_meta["unit"]} = <b>%{{y:.1f}}</b><extra></extra>',
    ))

    _pctile_lines(fig, baseline_entry, field_key)

    layout = {**PL}
    layout['title']  = dict(
        text=f'<span style="font-family:Bebas Neue;font-size:18px;letter-spacing:2px">'
             f'{psa_id} — 7-Day {field_meta["label"]}</span>',
        font=dict(color=C['text']), x=0, xanchor='left'
    )
    layout['height'] = 360
    layout['xaxis']  = {**layout['xaxis'], 'title': ''}
    layout['yaxis']  = {**layout['yaxis'], 'title': field_meta['unit']}
    fig.update_layout(**layout)
    return fig


def chart_all_psa_bar(all_psa_data, field_key, field_meta, baseline, gacc_name):
    """Bar chart showing today's value for all PSAs in a GACC."""
    psas, vals, colors = [], [], []
    for psa_id, pdata in sorted(all_psa_data.items()):
        td = pdata.get('td')
        if td is None: continue
        bentry = get_psa_baseline(gacc_name, psa_id, baseline)
        fdata  = bentry.get(field_key.lower(), {})
        _, col, _ = alert_level(td, fdata.get('p90'), fdata.get('p95'), fdata.get('p97'))
        psas.append(psa_id); vals.append(td); colors.append(col)

    if not psas:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=psas, y=vals, marker_color=colors, marker_line_width=0,
        name=f'{field_meta["unit"]} Today',
        hovertemplate='<b>%{x}</b><br>' + field_meta['unit'] + ': <b>%{y:.1f}</b><extra></extra>',
    ))

    layout = {**PL}
    layout['title']  = dict(
        text=f'<span style="font-family:Bebas Neue;font-size:18px;letter-spacing:2px">'
             f'{field_meta["label"]} Today — All PSAs</span>',
        font=dict(color=C['text']), x=0, xanchor='left',
    )
    layout['height'] = 340
    layout['xaxis']  = {**layout['xaxis'], 'tickangle': -45}
    layout['yaxis']  = {**layout['yaxis'], 'title': field_meta['unit']}
    fig.update_layout(**layout)
    return fig


def chart_pctile_comparison(all_psa_data, field_key, baseline, gacc_name):
    """Grouped bar: today vs mean vs 90th vs 97th for all PSAs."""
    psas = sorted(all_psa_data.keys())
    vals_today, vals_mean, vals_p90, vals_p97 = [], [], [], []
    for psa_id in psas:
        td    = all_psa_data[psa_id].get('td')
        bdata = get_psa_baseline(gacc_name, psa_id, baseline).get(field_key.lower(), {})
        vals_today.append(td)
        vals_mean.append(bdata.get('mean'))
        vals_p90.append(bdata.get('p90'))
        vals_p97.append(bdata.get('p97'))

    fig = go.Figure()
    for name, vals, color, opacity in [
        ('Today',    vals_today, C['fire'],  1.0),
        ('Mean',     vals_mean,  C['teal'],  0.7),
        ('90th',     vals_p90,   C['p90'],   0.6),
        ('97th',     vals_p97,   C['p97'],   0.6),
    ]:
        fig.add_trace(go.Bar(
            x=psas, y=vals, name=name, marker_color=color,
            marker_line_width=0, opacity=opacity,
            hovertemplate=f'<b>%{{x}}</b><br>{name}: <b>%{{y:.1f}}</b><extra></extra>',
        ))

    layout = {**PL}
    layout['title']  = dict(
        text=f'<span style="font-family:Bebas Neue;font-size:18px;letter-spacing:2px">'
             f'Percentile Context — All PSAs</span>',
        font=dict(color=C['text']), x=0, xanchor='left',
    )
    layout['barmode'] = 'group'
    layout['height']  = 360
    layout['xaxis']   = {**layout['xaxis'], 'tickangle': -45}
    fig.update_layout(**layout)
    return fig


def chart_trend_heatmap(trend_data):
    """Heatmap of ERC trend Δ vs today for all PSAs × forecast days."""
    t_days   = ['td', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']
    t_labels = ['Today', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']
    psas = sorted(trend_data.keys())
    z    = [[trend_data[p].get(d, 0) for d in t_days] for p in psas]

    fig = go.Figure(go.Heatmap(
        z=z, x=t_labels, y=psas,
        colorscale=[
            [0.0, '#00c875'], [0.35, '#1a1e2e'],
            [0.65, '#1a1e2e'], [0.82, '#ff6b00'], [1.0, '#ff2d55']
        ],
        zmid=0,
        hovertemplate='<b>%{y}</b> · %{x}<br>Δ ERC: <b>%{z:+.1f}</b><extra></extra>',
        colorbar=dict(
            tickfont=dict(color=C['muted'], size=9, family='JetBrains Mono'),
            title=dict(text='Δ ERC', font=dict(color=C['muted'], size=11)),
            len=0.8,
        ),
    ))
    layout = {**PL}
    layout['title']  = dict(
        text='<span style="font-family:Bebas Neue;font-size:18px;letter-spacing:2px">'
             'ERC TREND HEATMAP — Δ vs Today</span>',
        font=dict(color=C['text']), x=0, xanchor='left',
    )
    layout['height'] = max(380, len(psas) * 20 + 100)
    layout['yaxis']  = {**layout['yaxis'], 'autorange': 'reversed', 'tickangle': 0}
    layout['xaxis']  = {**layout['xaxis'], 'tickangle': 0}
    fig.update_layout(**layout)
    return fig


def chart_trend_diverging(trend_data, selected_psa):
    """Diverging bar for one PSA's ERC trend across the 7-day window."""
    t_days   = ['td', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']
    t_labels = ['Today', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']
    pdata = trend_data.get(selected_psa, {})
    vals  = [pdata.get(d, 0) for d in t_days]
    colors = [C['crit'] if v > 3 else C['high'] if v > 0 else C['norm'] for v in vals]

    fig = go.Figure()
    fig.add_hline(y=0, line_color=C['border'], line_width=1)
    fig.add_trace(go.Bar(
        x=t_labels, y=vals, marker_color=colors, marker_line_width=0,
        hovertemplate='<b>%{x}</b>: Δ ERC = <b>%{y:+.1f}</b><extra></extra>',
    ))
    layout = {**PL}
    layout['title'] = dict(
        text=f'<span style="font-family:Bebas Neue;font-size:18px;letter-spacing:2px">'
             f'{selected_psa} — ERC TREND</span>',
        font=dict(color=C['text']), x=0, xanchor='left',
    )
    layout['height'] = 280
    layout['yaxis']  = {**layout['yaxis'], 'title': 'Δ ERC vs Today'}
    fig.update_layout(**layout)
    return fig


# ── Sidebar ───────────────────────────────────────────────────────────────────
def build_sidebar(gacc_config, source, meta):
    with st.sidebar:
        # ── Logo / header
        st.markdown("""
        <div style="padding: 24px 16px 8px; border-bottom: 1px solid #2a3050;">
          <div style="font-family:'Bebas Neue',sans-serif; font-size:28px; color:#ff4d00;
                      letter-spacing:3px; line-height:1;">FIRE WEATHER</div>
          <div style="font-family:'JetBrains Mono',monospace; font-size:9px;
                      color:#6b7299; letter-spacing:2px; text-transform:uppercase;
                      margin-top:4px;">GACC Intelligence Dashboard</div>
        </div>
        """, unsafe_allow_html=True)

        # ── Data source status
        st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
        fetched = meta.get('fetched_at', '')[:16].replace('T', ' ')
        if source == 'live':
            st.markdown(f'<div class="badge-live">⬤ LIVE · FEMS API<br>'
                        f'<span style="opacity:.6">{fetched} UTC</span></div>',
                        unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="badge-cached">◑ CACHED · {fetched} UTC<br>'
                        f'<span style="opacity:.6">Refresh to force update</span></div>',
                        unsafe_allow_html=True)
        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        if st.button('↺  Refresh Data', use_container_width=True):
            st.cache_data.clear(); st.rerun()

        st.markdown('<hr>', unsafe_allow_html=True)

        # ── GACC selector
        gacc_names = [n for n, d in gacc_config.items()
                      if any(p['stations'] for p in d['psas'].values())]
        gacc_display = {n: f"{gacc_config[n]['abbrev']} — {n.split()[0]} {n.split()[1] if len(n.split())>1 else ''}"
                        for n in gacc_names}
        selected_gacc = st.selectbox(
            'GACC',
            gacc_names,
            format_func=lambda n: gacc_display[n],
            key='gacc_sel',
        )

        # ── PSA selector (filtered to selected GACC)
        psa_ids = sorted(gacc_config[selected_gacc]['psas'].keys())
        selected_psa = st.selectbox('PSA', psa_ids, key='psa_sel')

        # ── Field selector
        st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
        selected_field = st.radio(
            'Index',
            list(FIELD_META.keys()),
            format_func=lambda f: FIELD_META[f]['unit'],
            horizontal=True,
            key='field_sel',
        )

        st.markdown('<hr>', unsafe_allow_html=True)

        # ── Legend
        st.markdown("""
        <div style="font-family:'JetBrains Mono',monospace; font-size:9px;
                    text-transform:uppercase; letter-spacing:1px; color:#3a3f6b;
                    margin-bottom:8px;">Alert Levels</div>
        """, unsafe_allow_html=True)
        for label, color in [
            ('Critical  ≥ 97th', C['crit']),
            ('High      ≥ 95th', C['high']),
            ('Elevated  ≥ 90th', C['elev']),
            ('Normal    < 90th', C['norm']),
        ]:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:5px;">'
                f'<div style="width:10px;height:10px;border-radius:2px;background:{color};'
                f'flex-shrink:0"></div>'
                f'<span style="font-family:JetBrains Mono,monospace;font-size:10px;'
                f'color:#6b7299">{label}</span></div>',
                unsafe_allow_html=True,
            )

        st.markdown('<hr>', unsafe_allow_html=True)

        # ── Percentile legend
        st.markdown("""
        <div style="font-family:'JetBrains Mono',monospace; font-size:9px;
                    text-transform:uppercase; letter-spacing:1px; color:#3a3f6b;
                    margin-bottom:8px;">Percentile Lines</div>
        """, unsafe_allow_html=True)
        for label, color in [
            ('─── Climo Mean',  C['teal']),
            ('·· · 80th Pctile', C['p80']),
            ('- - - 90th Pctile', C['p90']),
            ('─ ─ 95th Pctile',  C['p95']),
            ('─ ─ 97th Pctile',  C['p97']),
        ]:
            st.markdown(
                f'<div style="font-family:JetBrains Mono,monospace;font-size:10px;'
                f'color:{color};margin-bottom:4px;">{label}</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<hr>', unsafe_allow_html=True)
        fm   = gacc_config[selected_gacc]['psas'].get(selected_psa, {}).get('fuel_model', '?')
        n_st = len(gacc_config[selected_gacc]['psas'].get(selected_psa, {}).get('stations', []))
        st.markdown(f"""
        <div style='font-size:9px;color:#3a3f6b;font-family:JetBrains Mono,monospace;
                    line-height:2;text-transform:uppercase;letter-spacing:0.8px;'>
          GACC: {gacc_config[selected_gacc]['abbrev']}<br>
          PSA: {selected_psa} · Fuel Model: {fm}<br>
          RAWS Stations: {n_st}<br>
          Date: {meta.get('fetch_date', str(date.today()))}
        </div>""", unsafe_allow_html=True)

    return selected_gacc, selected_psa, selected_field


# ── KPI row ───────────────────────────────────────────────────────────────────
def build_kpis(all_psa_data, field_key, baseline, gacc_name):
    vals, crits, highs, elevs = [], 0, 0, 0
    for psa_id, pdata in all_psa_data.items():
        td = pdata.get('td')
        if td is None: continue
        vals.append(td)
        bdata = get_psa_baseline(gacc_name, psa_id, baseline).get(field_key.lower(), {})
        lvl, _, _ = alert_level(td, bdata.get('p90'), bdata.get('p95'), bdata.get('p97'))
        if lvl == 'CRITICAL': crits += 1
        elif lvl == 'HIGH':    highs += 1
        elif lvl == 'ELEVATED': elevs += 1

    if not vals: return
    avg  = sum(vals) / len(vals)
    mx   = max(vals)
    mx_psa = max(all_psa_data, key=lambda p: all_psa_data[p].get('td') or 0)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric('🔴 Critical PSAs',   crits,       delta='≥ 97th percentile' if crits else '─')
    c2.metric('🟠 High PSAs',       highs,       delta='≥ 95th percentile')
    c3.metric('🟡 Elevated PSAs',   elevs,       delta='≥ 90th percentile')
    c4.metric(f'📊 GACC Avg {FIELD_META[field_key]["unit"]}', f'{avg:.1f}')
    c5.metric(f'🔥 Max ({mx_psa})',  f'{mx:.0f}')


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    gacc_config = load_gacc_config()
    if not gacc_config:
        st.error('gacc_config.py not found — add it to the same folder as app.py')
        st.stop()

    baseline = load_baseline()
    api_key, username = _creds()

    # ── Determine what data to load
    if not api_key:
        st.markdown("""<div class="badge-err">
        <strong>🔑 FEMS credentials not configured</strong><br><br>
        <strong>Streamlit Cloud:</strong> App Settings → Secrets → add:<br>
        &nbsp;&nbsp;<code>FEMS_API_KEY = "your_key"</code><br>
        &nbsp;&nbsp;<code>FEMS_USERNAME = "your.email@usda.gov"</code><br><br>
        <strong>Local:</strong> create a <code>.env</code> file with the same two lines.
        </div>""", unsafe_allow_html=True)
        st.stop()

    # For sidebar we need at least dummy meta before first load
    dummy_meta = {'fetched_at': '', 'fetch_date': str(date.today()),
                  'climo_start': baseline.get('meta', {}).get('climo_start', 2005),
                  'climo_end':   baseline.get('meta', {}).get('climo_end', 2020)}

    # Sidebar (needs gacc_config, meta is approximate here — updated after data load)
    selected_gacc, selected_psa, selected_field = build_sidebar(gacc_config, 'cached', dummy_meta)

    # Now load data for the selected GACC
    psa_ids = list(gacc_config[selected_gacc]['psas'].keys())
    source = 'cached'

    if not _cache_fresh():
        try:
            with st.spinner(f'🔄 Fetching {gacc_config[selected_gacc]["abbrev"]} forecast from FEMS...'):
                (erc, fm, bi, ic, trend), meta = load_live(api_key, username, selected_gacc, psa_ids)
            source = 'live'
        except Exception as e:
            if _cache_fresh():
                st.warning(f'⚠️ Live fetch failed — using cache. ({e})')
                try:
                    (erc, fm, bi, ic, trend), meta = load_cached()
                except Exception as e2:
                    st.error(f'Cache also failed: {e2}'); st.stop()
            else:
                st.markdown(f'<div class="badge-err"><strong>❌ FEMS API error:</strong> {e}</div>',
                            unsafe_allow_html=True)
                st.stop()
    else:
        try:
            (erc, fm, bi, ic, trend), meta = load_cached()
        except Exception as e:
            try:
                with st.spinner('Fetching from FEMS...'):
                    (erc, fm, bi, ic, trend), meta = load_live(api_key, username, selected_gacc, psa_ids)
                source = 'live'
            except Exception as e2:
                st.error(f'Data load failed: {e2}'); st.stop()

    # Build all_psa_data for selected field from DataFrames
    field_dfs = {'ERC': erc, 'FM': fm, 'BI': bi, 'IC': ic}
    selected_df = field_dfs[selected_field]

    def df_to_psa_dict(df):
        """Convert field DataFrame to {psa_id: {day_col: val}} dict."""
        out = {}
        for _, row in df.iterrows():
            psa = row['PSA']
            out[psa] = {d: row.get(d) for d in DAY_COLS}
            out[psa]['Climo_Mean'] = row.get('Climo_Mean')
            for p in [80, 90, 95, 97]:
                out[psa][f'P{p}'] = row.get(f'P{p}')
        return out

    all_psa_data = df_to_psa_dict(selected_df)
    erc_all      = df_to_psa_dict(erc)
    trend_dict   = {}
    for _, row in trend.iterrows():
        trend_dict[row['PSA']] = {d: row.get(d) for d in ['td','Wed','Thu','Fri','Sat','Sun','Mon']}

    # Rebuild sidebar with real meta
    # (Streamlit doesn't re-render sidebar on data load — values already set, just update badge)

    # ── Page header ──────────────────────────────────────────────────────────
    abbrev = gacc_config[selected_gacc]['abbrev']
    pcts   = baseline.get('meta', {}).get('percentiles', [80, 90, 95, 97])
    col_h, col_b = st.columns([4, 1])
    with col_h:
        st.markdown(f"""
        <div style="padding: 4px 0 16px;">
          <div style="font-family:'Bebas Neue',sans-serif; font-size:36px;
                      color:{C['text']}; letter-spacing:4px; line-height:1;">
            {abbrev} <span style="color:{C['fire']}">FIRE WEATHER</span> INTELLIGENCE
          </div>
          <div style="font-family:'JetBrains Mono',monospace; font-size:10px;
                      color:{C['muted']}; letter-spacing:2px; text-transform:uppercase;
                      margin-top:4px;">
            7-Day Forecast · Climo {meta.get('climo_start',2005)}–{meta.get('climo_end',2020)} Baseline
            · Percentiles {pcts}
          </div>
        </div>
        """, unsafe_allow_html=True)
    with col_b:
        st.markdown(f"""
        <div style="text-align:right; padding-top:8px;">
          <div style="display:inline-block; background:{C['fire']}; color:white;
                      padding:6px 18px; border-radius:3px; font-family:'Bebas Neue',sans-serif;
                      font-size:16px; letter-spacing:2px;">{abbrev}</div>
          <div style="font-family:'JetBrains Mono',monospace; font-size:9px;
                      color:{C['muted']}; margin-top:6px; letter-spacing:1px;
                      text-transform:uppercase;">{meta.get('fetch_date', str(date.today()))}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<hr>', unsafe_allow_html=True)

    # ── KPI row
    build_kpis(all_psa_data, selected_field, baseline, selected_gacc)

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ── Alert level for selected PSA ─────────────────────────────────────────
    sel_psa_data   = all_psa_data.get(selected_psa, {})
    sel_baseline   = get_psa_baseline(selected_gacc, selected_psa, baseline)
    sel_fdata      = sel_baseline.get(selected_field.lower(), {})
    td_val         = sel_psa_data.get('td')
    lvl, _, cls    = alert_level(td_val, sel_fdata.get('p90'), sel_fdata.get('p95'), sel_fdata.get('p97'))
    fm_label       = gacc_config[selected_gacc]['psas'].get(selected_psa, {}).get('fuel_model', '?')
    pstr = '  ·  '.join([f"P{p}: {sel_fdata.get(f'p{p}','—')}"
                         for p in [80, 90, 95, 97] if sel_fdata.get(f'p{p}')])

    st.markdown(f"""
    <div style="display:flex; align-items:center; gap:16px; padding: 12px 0 20px; flex-wrap:wrap;">
      <span style="font-family:'Bebas Neue',sans-serif; font-size:22px;
                   color:{C['muted']}; letter-spacing:3px;">{selected_psa}</span>
      <div class="{cls}">{lvl}</div>
      <span style="font-family:'JetBrains Mono',monospace; font-size:11px; color:{C['muted']};">
        Today: <strong style="color:{C['text']}">{td_val if td_val else '—'}</strong>
        &nbsp;·&nbsp; Fuel Model: <strong style="color:{C['text']}">{fm_label}</strong>
        &nbsp;·&nbsp; {pstr}
      </span>
    </div>
    """, unsafe_allow_html=True)

    # ── Tabs ─────────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        '📈  7-Day Forecast',
        '📊  GACC Overview',
        '📉  ERC Trend',
        '🗺️  Trend Heatmap',
        '⚖️  Percentile Context',
        '🗒️  Data Table',
    ])

    # ── Tab 1: 7-Day forecast for selected PSA, all fields ───────────────────
    with tab1:
        fmeta = FIELD_META[selected_field]
        psa_forecast_data = {**sel_psa_data}

        col_main, col_side = st.columns([3, 1])
        with col_main:
            st.plotly_chart(
                chart_7day(psa_forecast_data, selected_field, fmeta, sel_baseline, selected_psa),
                use_container_width=True,
            )
        with col_side:
            # Mini stats card
            st.markdown(f"""
            <div style="background:{C['surface2']}; border:1px solid {C['border']};
                        border-radius:6px; padding:16px; margin-top:12px;">
              <div style="font-family:'JetBrains Mono',monospace; font-size:9px;
                          color:{C['muted']}; text-transform:uppercase; letter-spacing:1px;
                          margin-bottom:12px;">Climo Thresholds</div>
            """, unsafe_allow_html=True)
            for key, label, color in [
                ('mean', 'Mean',  C['teal']),
                ('p80',  '80th',  C['p80']),
                ('p90',  '90th',  C['p90']),
                ('p95',  '95th',  C['p95']),
                ('p97',  '97th',  C['p97']),
            ]:
                val = sel_fdata.get(key, '—')
                st.markdown(f"""
                <div style="display:flex; justify-content:space-between; align-items:center;
                            margin-bottom:8px;">
                  <span style="font-family:'JetBrains Mono',monospace; font-size:10px;
                               color:{C['muted']}">{label}</span>
                  <span style="font-family:'Bebas Neue',sans-serif; font-size:20px;
                               color:{color}">{f'{val:.0f}' if isinstance(val, float) else val}</span>
                </div>""", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # All fields in a row below
        st.markdown(f"""
        <div style="font-family:'JetBrains Mono',monospace; font-size:10px;
                    color:{C['muted']}; text-transform:uppercase; letter-spacing:1.5px;
                    margin: 16px 0 12px;">Other Indices — {selected_psa}</div>
        """, unsafe_allow_html=True)
        other_fields = [f for f in FIELD_META if f != selected_field]
        cols = st.columns(len(other_fields))
        other_dfs = {'ERC': erc, 'FM': fm, 'BI': bi, 'IC': ic}
        for col, fk in zip(cols, other_fields):
            with col:
                df_row = other_dfs[fk][other_dfs[fk]['PSA'] == selected_psa]
                if df_row.empty: continue
                row    = df_row.iloc[0]
                fmeta2 = FIELD_META[fk]
                b2     = sel_baseline.get(fk.lower(), {})
                fig2   = chart_7day(
                    {d: row.get(d) for d in DAY_COLS},
                    fk, fmeta2, sel_baseline, selected_psa,
                )
                fig2.update_layout(height=280, title=dict(
                    text=f'<span style="font-family:Bebas Neue;font-size:14px;letter-spacing:2px">'
                         f'{fmeta2["unit"]}</span>'))
                st.plotly_chart(fig2, use_container_width=True)

    # ── Tab 2: GACC overview bar charts ──────────────────────────────────────
    with tab2:
        st.plotly_chart(chart_all_psa_bar(all_psa_data, selected_field, FIELD_META[selected_field], baseline, selected_gacc), use_container_width=True)
        c2a, c2b = st.columns(2)
        other2 = [f for f in FIELD_META if f != selected_field]
        for col, fk in zip([c2a, c2b], other2[:2]):
            with col:
                fd2 = df_to_psa_dict(other_dfs[fk])
                st.plotly_chart(chart_all_psa_bar(fd2, fk, FIELD_META[fk], baseline, selected_gacc), use_container_width=True)
        if len(other2) > 2:
            fd3 = df_to_psa_dict(other_dfs[other2[2]])
            st.plotly_chart(chart_all_psa_bar(fd3, other2[2], FIELD_META[other2[2]], baseline, selected_gacc), use_container_width=True)

    # ── Tab 3: ERC trend for selected PSA ────────────────────────────────────
    with tab3:
        c3a, c3b = st.columns([2, 3])
        with c3a:
            st.plotly_chart(chart_trend_diverging(trend_dict, selected_psa), use_container_width=True)
        with c3b:
            # Multi-PSA ERC trend lines
            fig_mt = go.Figure()
            t_days   = ['td','Wed','Thu','Fri','Sat','Sun','Mon']
            t_labels = ['Today','Wed','Thu','Fri','Sat','Sun','Mon']
            palette  = [C['fire'], C['teal'], C['gold'], C['p80'], C['p95'], C['p97'], C['p90']]
            for i, (psa, tdata) in enumerate(sorted(trend_dict.items())):
                color = palette[i % len(palette)]
                lw = 3 if psa == selected_psa else 1.2
                op = 1.0 if psa == selected_psa else 0.4
                fig_mt.add_trace(go.Scatter(
                    x=t_labels, y=[tdata.get(d, 0) for d in t_days],
                    mode='lines', name=psa,
                    line=dict(color=color, width=lw), opacity=op,
                    hovertemplate=f'<b>{psa}</b> · %{{x}}: <b>%{{y:+.1f}}</b><extra></extra>',
                ))
            fig_mt.add_hline(y=0, line_color=C['border'], line_width=1)
            lmt = {**PL}
            lmt['title']  = dict(
                text='<span style="font-family:Bebas Neue;font-size:18px;letter-spacing:2px">'
                     'ERC TREND — All PSAs</span>',
                font=dict(color=C['text']), x=0, xanchor='left',
            )
            lmt['height'] = 300
            lmt['yaxis']  = {**lmt['yaxis'], 'title': 'Δ ERC vs Today'}
            fig_mt.update_layout(**lmt)
            st.plotly_chart(fig_mt, use_container_width=True)

    # ── Tab 4: Trend heatmap ──────────────────────────────────────────────────
    with tab4:
        st.plotly_chart(chart_trend_heatmap(trend_dict), use_container_width=True)
        st.markdown(f"""
        <div style="font-family:'JetBrains Mono',monospace; font-size:10px; color:{C['muted']};
                    line-height:1.8; padding:8px 0;">
          <span style="color:{C['norm']}">■</span> Green = ERC decreasing (improving)
          &nbsp;&nbsp;
          <span style="color:{C['crit']}">■</span> Red = ERC increasing (worsening)
          &nbsp;&nbsp;
          Dark = stable
        </div>""", unsafe_allow_html=True)

    # ── Tab 5: Percentile context grouped bar ────────────────────────────────
    with tab5:
        st.plotly_chart(chart_pctile_comparison(all_psa_data, selected_field, baseline, selected_gacc), use_container_width=True)

    # ── Tab 6: Data table ─────────────────────────────────────────────────────
    with tab6:
        field_choice = st.selectbox('Field', list(FIELD_META.keys()),
                                    format_func=lambda f: f'{FIELD_META[f]["unit"]} — {FIELD_META[f]["label"]}',
                                    key='tbl_field')
        tbl_df = field_dfs[field_choice].copy()
        num_cols = [c for c in ['yd','td','Wed','Thu','Fri','Sat','Sun','Mon',
                                'Climo_Mean','P80','P90','P95','P97'] if c in tbl_df.columns]
        search = st.text_input('🔍 Filter PSA', placeholder='e.g. GB21')
        if search:
            tbl_df = tbl_df[tbl_df['PSA'].str.contains(search.upper(), na=False)]
        tbl_df = tbl_df.sort_values('PSA')
        tbl_show = tbl_df[['PSA'] + num_cols]
        st.dataframe(
            tbl_show.style.format({c: '{:.1f}' for c in num_cols}),
            use_container_width=True, height=520,
        )
        st.download_button(
            f'⬇ Download {field_choice} CSV',
            tbl_show.to_csv(index=False),
            f'{abbrev}_{field_choice}_{date.today()}.csv',
            'text/csv',
        )


if __name__ == '__main__':
    main()
