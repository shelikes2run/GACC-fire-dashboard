"""
GACC Fire Weather Intelligence Dashboard
Sidebar: GACC → PSA → Primary Index
Tabs: 7-Day Forecast | GACC Overview | All Indices | ERC Trend | Heatmap | Context | Table
All 9 fields: ERC, IC, BI, SC, FM-1, FM-10, FM-100, FM-1000, KBDI
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json, os
from datetime import datetime, date
from pathlib import Path

st.set_page_config(
    page_title="GACC Fire Weather Intelligence",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS design system ─────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --bg:#0d0f1a;   --bg2:#12151f;  --surface:#1a1e2e; --surface2:#222740;
  --border:#2a3050; --fire:#ff4d00; --teal:#00d4b4;   --gold:#ffd700;
  --text:#e8eaf6;   --muted:#6b7299; --dim:#3a3f6b;
  --crit:#ff2d55;   --high:#ff6b00;  --elev:#ffcc00;  --norm:#00c875;
  --p80:#4dabf7;    --p90:#ffa94d;   --p95:#ff6b6b;   --p97:#cc5de8;
}

.stApp { background:var(--bg) !important; }
section[data-testid="stSidebar"] {
  background:var(--bg2) !important;
  border-right:1px solid var(--border) !important;
}
html,body,[class*="css"] { font-family:'Space Grotesk',sans-serif; color:var(--text); }

[data-testid="metric-container"] {
  background:var(--surface) !important;
  border:1px solid var(--border) !important;
  border-top:3px solid var(--fire) !important;
  border-radius:6px !important;
  padding:14px 18px !important;
}
[data-testid="metric-container"] label {
  color:var(--muted) !important; font-size:10px !important;
  text-transform:uppercase !important; letter-spacing:1.2px !important;
  font-family:'JetBrains Mono',monospace !important;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
  font-family:'Bebas Neue',sans-serif !important;
  font-size:36px !important; color:var(--text) !important; line-height:1.1 !important;
}

.stTabs [data-baseweb="tab-list"] {
  background:var(--surface) !important; border-radius:4px !important;
  padding:3px !important; border:1px solid var(--border) !important; gap:2px !important;
}
.stTabs [data-baseweb="tab"] {
  background:transparent !important; color:var(--muted) !important;
  border-radius:3px !important; font-family:'JetBrains Mono',monospace !important;
  font-size:10px !important; letter-spacing:1px !important;
  text-transform:uppercase !important; padding:7px 14px !important; border:none !important;
}
.stTabs [aria-selected="true"] { background:var(--fire) !important; color:white !important; }

.stSelectbox > div > div {
  background:var(--surface2) !important; border:1px solid var(--border) !important;
  color:var(--text) !important; border-radius:4px !important;
}
.stSelectbox label, .stRadio [data-testid="stWidgetLabel"] {
  color:var(--muted) !important; font-size:10px !important;
  text-transform:uppercase !important; letter-spacing:1px !important;
  font-family:'JetBrains Mono',monospace !important;
}
.stButton > button {
  background:var(--surface2) !important; border:1px solid var(--border) !important;
  color:var(--text) !important; border-radius:4px !important;
  font-family:'JetBrains Mono',monospace !important; font-size:11px !important;
}
.stButton > button:hover { border-color:var(--fire) !important; color:var(--fire) !important; }

#MainMenu, footer, header { visibility:hidden; }
hr { border-color:var(--border) !important; opacity:.4 !important; }

.badge-live   { background:rgba(0,200,117,.10); border:1px solid rgba(0,200,117,.35);
                color:#00c875; border-radius:4px; padding:8px 12px;
                font-family:'JetBrains Mono',monospace; font-size:10px; line-height:1.9; }
.badge-cached { background:rgba(255,214,0,.08); border:1px solid rgba(255,214,0,.30);
                color:#ffd700; border-radius:4px; padding:8px 12px;
                font-family:'JetBrains Mono',monospace; font-size:10px; line-height:1.9; }
.badge-err    { background:rgba(255,45,85,.10); border:1px solid rgba(255,45,85,.40);
                color:#ff2d55; border-radius:4px; padding:16px 20px;
                font-family:'Space Grotesk',sans-serif; font-size:13px; line-height:1.6; }

.alert-crit { background:#ff2d5522; border:1px solid #ff2d55; color:#ff2d55;
              border-radius:3px; padding:4px 12px; font-family:'JetBrains Mono',monospace;
              font-size:11px; font-weight:700; letter-spacing:1px; }
.alert-high { background:#ff6b0022; border:1px solid #ff6b00; color:#ff6b00;
              border-radius:3px; padding:4px 12px; font-family:'JetBrains Mono',monospace;
              font-size:11px; font-weight:700; letter-spacing:1px; }
.alert-elev { background:#ffcc0022; border:1px solid #ffcc00; color:#ffcc00;
              border-radius:3px; padding:4px 12px; font-family:'JetBrains Mono',monospace;
              font-size:11px; font-weight:700; letter-spacing:1px; }
.alert-norm { background:#00c87522; border:1px solid #00c875; color:#00c875;
              border-radius:3px; padding:4px 12px; font-family:'JetBrains Mono',monospace;
              font-size:11px; font-weight:700; letter-spacing:1px; }
</style>
""", unsafe_allow_html=True)

# ── Palette & Plotly base theme ───────────────────────────────────────────────
C = {
    'bg': '#0d0f1a',   'surface': '#1a1e2e',  'surface2': '#222740',
    'border': '#2a3050', 'fire': '#ff4d00',   'teal': '#00d4b4',
    'gold': '#ffd700',   'text': '#e8eaf6',   'muted': '#6b7299',
    'dim': '#3a3f6b',    'crit': '#ff2d55',   'high': '#ff6b00',
    'elev': '#ffcc00',   'norm': '#00c875',   'p80': '#4dabf7',
    'p90': '#ffa94d',    'p95': '#ff6b6b',    'p97': '#cc5de8',
}

PL = dict(
    paper_bgcolor=C['surface'],
    plot_bgcolor=C['surface'],
    font=dict(color=C['text'], family='Space Grotesk'),
    margin=dict(t=48, b=52, l=52, r=24),
    legend=dict(
        bgcolor=C['surface2'], bordercolor=C['border'], borderwidth=1,
        font=dict(size=10, color=C['muted']), orientation='h', y=-0.22, x=0,
    ),
    xaxis=dict(
        gridcolor=C['border'], linecolor=C['border'],
        tickfont=dict(color=C['muted'], size=10, family='JetBrains Mono'),
        title_font=dict(color=C['muted'], size=11),
    ),
    yaxis=dict(
        gridcolor=C['border'], linecolor=C['border'],
        tickfont=dict(color=C['muted'], size=10, family='JetBrains Mono'),
        title_font=dict(color=C['muted'], size=11),
    ),
)

# ── Field definitions  (9 fields from the NFDR daily summary endpoint) ────────
# pctile_flip=True: lower = worse (fuel moisture — critical when DRY)
FIELD_META = {
    'erc':    {'label': 'Energy Release Component', 'unit': 'ERC',     'color': '#ff4d00', 'pctile_flip': False},
    'ic':     {'label': 'Ignition Component',        'unit': 'IC',      'color': '#cc5de8', 'pctile_flip': False},
    'bi':     {'label': 'Burning Index',             'unit': 'BI',      'color': '#ffd700', 'pctile_flip': False},
    'sc':     {'label': 'Spread Component',          'unit': 'SC',      'color': '#ff6b6b', 'pctile_flip': False},
    'fm100':  {'label': '100-Hr Fuel Moisture',      'unit': 'FM-100',  'color': '#00d4b4', 'pctile_flip': True},
    'fm1':    {'label': '1-Hr Fuel Moisture',        'unit': 'FM-1',    'color': '#74c0fc', 'pctile_flip': True},
    'fm10':   {'label': '10-Hr Fuel Moisture',       'unit': 'FM-10',   'color': '#63e6be', 'pctile_flip': True},
    'fm1000': {'label': '1000-Hr Fuel Moisture',     'unit': 'FM-1000', 'color': '#a9e34b', 'pctile_flip': True},
    'kbdi':   {'label': 'Keetch-Byram Drought Index','unit': 'KBDI',    'color': '#f08c00', 'pctile_flip': False},
}

PRIMARY_FIELDS = ['erc', 'ic', 'bi', 'sc', 'fm100']
ALL_FIELDS     = list(FIELD_META.keys())
DAY_COLS       = ['yd', 'td', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']
DAY_LABELS     = ['Yesterday', 'Today', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']
CACHE_FILE     = Path('gacc_data.json')
CACHE_HOURS    = 6


# ── Helpers ───────────────────────────────────────────────────────────────────
def _creds():
    try:
        k = st.secrets['FEMS_API_KEY']
        u = st.secrets['FEMS_USERNAME']
        if k and u:
            return k, u
    except Exception:
        pass
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    return os.getenv('FEMS_API_KEY', ''), os.getenv('FEMS_USERNAME', '')


def _cache_fresh():
    if not CACHE_FILE.exists():
        return False
    age = (datetime.now() - datetime.fromtimestamp(
        CACHE_FILE.stat().st_mtime)).total_seconds()
    return age < CACHE_HOURS * 3600


@st.cache_resource
def load_gacc_config():
    import importlib.util
    p = Path('gacc_config.py')
    if not p.exists():
        return {}
    spec = importlib.util.spec_from_file_location('gacc_config', p)
    gc   = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gc)
    return gc.GACC_CONFIG


@st.cache_data(show_spinner=False)
def load_baseline():
    p = Path('gacc_climo_baseline.json')
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding='utf-8'))


@st.cache_data(ttl=CACHE_HOURS * 3600, show_spinner=False)
def load_live(api_key, username, gacc_name, psa_tuple):
    import fems_fetcher as ff
    ff.FEMS_API_KEY  = api_key
    ff.FEMS_USERNAME = username
    data = ff.fetch_psa_forecast(gacc_name, list(psa_tuple))
    return ff.json_to_dataframes(data), data['meta']


@st.cache_data(show_spinner=False)
def load_cached():
    import fems_fetcher as ff
    data = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    return ff.json_to_dataframes(data), data['meta']


def get_field_df(dfs, fk):
    return dfs.get(fk, pd.DataFrame())


def get_psa_bdata(gacc_name, psa_id, baseline, fk):
    """Return the baseline dict for one PSA + one field."""
    return (baseline.get('psa', {})
            .get(f'{gacc_name}|{psa_id}', {})
            .get(fk, {}))


def alert_level(val, p90, p95, p97):
    """Return (label, color, css_class) for a fire behaviour value."""
    if val is None:
        return 'UNKNOWN', C['dim'], 'alert-norm'
    if p97 is not None and val >= p97:
        return 'CRITICAL', C['crit'], 'alert-crit'
    if p95 is not None and val >= p95:
        return 'HIGH',     C['high'], 'alert-high'
    if p90 is not None and val >= p90:
        return 'ELEVATED', C['elev'], 'alert-elev'
    return 'NORMAL', C['norm'], 'alert-norm'


# ── Chart helpers ─────────────────────────────────────────────────────────────
def _title(text):
    return dict(
        text=(f'<span style="font-family:Bebas Neue;font-size:18px;'
              f'letter-spacing:2px">{text}</span>'),
        font=dict(color=C['text']), x=0, xanchor='left',
    )


def add_pctile_lines(fig, bdata):
    """Draw climo mean + P80/90/95/97 reference lines on the figure."""
    styles = [
        ('mean', C['teal'],  'dot',  1.5, 'Mean'),
        ('p80',  C['p80'],   'dot',  1.5, '80th'),
        ('p90',  C['p90'],   'dash', 1.8, '90th'),
        ('p95',  C['p95'],   'dash', 2.0, '95th'),
        ('p97',  C['p97'],   'dash', 2.2, '97th'),
    ]
    for key, color, dash, width, label in styles:
        val = bdata.get(key)
        if val is None:
            continue
        fig.add_hline(
            y=val, line_dash=dash, line_color=color,
            line_width=width, opacity=0.75,
            annotation_text=f'{label}: {val:.0f}',
            annotation_font_color=color, annotation_font_size=10,
            annotation_position='right',
        )


def chart_7day(row_dict, fk, fmeta, bdata, psa_id, height=360):
    vals  = [row_dict.get(d) for d in DAY_COLS]
    color = fmeta['color']
    fig   = go.Figure()

    # Shaded P90-P97 risk band
    p90 = bdata.get('p90')
    p97 = bdata.get('p97')
    if p90 is not None and p97 is not None:
        fig.add_trace(go.Scatter(
            x=DAY_LABELS + DAY_LABELS[::-1],
            y=[p97] * 8 + [p90] * 8,
            fill='toself', fillcolor='rgba(255,77,0,0.05)',
            line=dict(color='rgba(0,0,0,0)'),
            hoverinfo='skip', showlegend=False,
        ))

    fig.add_trace(go.Scatter(
        x=DAY_LABELS, y=vals, mode='lines+markers',
        name=fmeta['unit'],
        line=dict(color=color, width=3),
        marker=dict(size=9, color=color, line=dict(color=C['bg'], width=2)),
        hovertemplate=(f'<b>%{{x}}</b><br>'
                       f'{fmeta["unit"]} = <b>%{{y:.1f}}</b><extra></extra>'),
    ))

    add_pctile_lines(fig, bdata)

    fig.update_layout(**{
        **PL,
        'title':  _title(f'{psa_id} — 7-Day {fmeta["label"]}'),
        'height': height,
        'yaxis':  {**PL['yaxis'], 'title': fmeta['unit']},
    })
    return fig


def chart_bar_today(df, fk, fmeta, baseline, gacc_name):
    """Bar chart of today's value for all PSAs, colored by alert level."""
    psas, vals, colors = [], [], []
    for _, row in df.sort_values('PSA').iterrows():
        td = row.get('td')
        if td is None:
            continue
        bdata = get_psa_bdata(gacc_name, row['PSA'], baseline, fk)
        _, col, _ = alert_level(td, bdata.get('p90'), bdata.get('p95'), bdata.get('p97'))
        psas.append(row['PSA'])
        vals.append(td)
        colors.append(col)

    if not psas:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=psas, y=vals, marker_color=colors, marker_line_width=0,
        hovertemplate=(f'<b>%{{x}}</b><br>'
                       f'{fmeta["unit"]}: <b>%{{y:.1f}}</b><extra></extra>'),
    ))
    fig.update_layout(**{
        **PL,
        'title':  _title(f'{fmeta["label"]} Today — All PSAs'),
        'height': 340,
        'xaxis':  {**PL['xaxis'], 'tickangle': -45},
        'yaxis':  {**PL['yaxis'], 'title': fmeta['unit']},
    })
    return fig


def chart_pctile_grouped(df, fk, baseline, gacc_name):
    """Grouped bar: Today vs Climo Mean vs 90th vs 97th per PSA."""
    psas   = sorted(df['PSA'].tolist())
    today  = []
    means  = []
    p90s   = []
    p97s   = []

    for p in psas:
        rows  = df[df['PSA'] == p]
        bdata = get_psa_bdata(gacc_name, p, baseline, fk)
        today.append(rows.iloc[0].get('td') if not rows.empty else None)
        means.append(bdata.get('mean'))
        p90s.append(bdata.get('p90'))
        p97s.append(bdata.get('p97'))

    fig = go.Figure()
    for name, vals, color, opacity in [
        ('Today', today, C['fire'], 1.0),
        ('Mean',  means, C['teal'], 0.7),
        ('90th',  p90s,  C['p90'],  0.6),
        ('97th',  p97s,  C['p97'],  0.6),
    ]:
        fig.add_trace(go.Bar(
            x=psas, y=vals, name=name,
            marker_color=color, marker_line_width=0, opacity=opacity,
            hovertemplate=(f'<b>%{{x}}</b><br>'
                           f'{name}: <b>%{{y:.1f}}</b><extra></extra>'),
        ))
    fig.update_layout(**{
        **PL,
        'title':   _title('Percentile Context — All PSAs'),
        'barmode': 'group',
        'height':  360,
        'xaxis':   {**PL['xaxis'], 'tickangle': -45},
    })
    return fig


def chart_trend_heatmap(trend_df):
    t_days  = ['td', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']
    t_lbls  = ['Today', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']
    psas    = sorted(trend_df['PSA'].tolist())
    z       = [
        [trend_df[trend_df['PSA'] == p].iloc[0].get(d, 0) for d in t_days]
        for p in psas
    ]
    fig = go.Figure(go.Heatmap(
        z=z, x=t_lbls, y=psas,
        colorscale=[
            [0.00, '#00c875'],
            [0.40, '#1a1e2e'],
            [0.60, '#1a1e2e'],
            [0.82, '#ff6b00'],
            [1.00, '#ff2d55'],
        ],
        zmid=0,
        hovertemplate='<b>%{y}</b> · %{x}<br>Δ ERC: <b>%{z:+.1f}</b><extra></extra>',
        colorbar=dict(
            tickfont=dict(color=C['muted'], size=9, family='JetBrains Mono'),
            title=dict(text='Δ ERC', font=dict(color=C['muted'])),
            len=0.8,
        ),
    ))
    fig.update_layout(**{
        **PL,
        'title':  _title('ERC TREND HEATMAP — Δ vs Today'),
        'height': max(360, len(psas) * 20 + 100),
        'yaxis':  {**PL['yaxis'], 'autorange': 'reversed'},
    })
    return fig


# ── Sidebar ───────────────────────────────────────────────────────────────────
def build_sidebar(gacc_config, source, meta):
    with st.sidebar:
        st.markdown(f"""
        <div style="padding:24px 16px 8px;border-bottom:1px solid {C['border']};">
          <div style="font-family:'Bebas Neue',sans-serif;font-size:28px;
                      color:{C['fire']};letter-spacing:3px;line-height:1;">
            FIRE WEATHER
          </div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:9px;
                      color:{C['muted']};letter-spacing:2px;text-transform:uppercase;
                      margin-top:4px;">
            GACC Intelligence Dashboard
          </div>
        </div>""", unsafe_allow_html=True)

        st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)

        fetched = meta.get('fetched_at', '')[:16].replace('T', ' ')
        if source == 'live':
            st.markdown(
                f'<div class="badge-live">⬤ LIVE · FEMS API<br>'
                f'<span style="opacity:.6">{fetched} UTC</span></div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div class="badge-cached">◑ CACHED<br>'
                f'<span style="opacity:.6">{fetched} UTC</span></div>',
                unsafe_allow_html=True)

        st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)
        if st.button('↺  Refresh', use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown('<hr>', unsafe_allow_html=True)

        # GACC selector — only GACCs that have stations in the spreadsheet
        gacc_names = [
            n for n, d in gacc_config.items()
            if any(p['stations'] for p in d['psas'].values())
        ]
        selected_gacc = st.selectbox(
            'GACC',
            gacc_names,
            format_func=lambda n: (
                f"{gacc_config[n]['abbrev']} — "
                f"{' '.join(n.split()[:2])}"
            ),
        )

        # PSA selector — only PSAs belonging to the selected GACC
        psa_ids      = sorted(gacc_config[selected_gacc]['psas'].keys())
        selected_psa = st.selectbox('PSA', psa_ids)

        # Primary index radio
        st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
        selected_field = st.radio(
            'Primary Index',
            PRIMARY_FIELDS,
            format_func=lambda f: FIELD_META[f]['unit'],
            horizontal=True,
        )

        st.markdown('<hr>', unsafe_allow_html=True)

        # Alert legend
        st.markdown(
            f'<div style="font-family:JetBrains Mono,monospace;font-size:9px;'
            f'text-transform:uppercase;letter-spacing:1px;color:{C["dim"]};'
            f'margin-bottom:8px;">Alert Levels</div>',
            unsafe_allow_html=True)
        for lbl, col in [
            ('Critical  ≥ 97th', C['crit']),
            ('High      ≥ 95th', C['high']),
            ('Elevated  ≥ 90th', C['elev']),
            ('Normal    < 90th', C['norm']),
        ]:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:5px;">'
                f'<div style="width:10px;height:10px;border-radius:2px;'
                f'background:{col};flex-shrink:0"></div>'
                f'<span style="font-family:JetBrains Mono,monospace;font-size:10px;'
                f'color:{C["muted"]}">{lbl}</span></div>',
                unsafe_allow_html=True)

        st.markdown('<hr>', unsafe_allow_html=True)

        # Percentile line legend
        st.markdown(
            f'<div style="font-family:JetBrains Mono,monospace;font-size:9px;'
            f'text-transform:uppercase;letter-spacing:1px;color:{C["dim"]};'
            f'margin-bottom:8px;">Percentile Lines</div>',
            unsafe_allow_html=True)
        for lbl, col in [
            ('─── Climo Mean',   C['teal']),
            ('·· · 80th Pctile', C['p80']),
            ('- - - 90th Pctile',C['p90']),
            ('─ ─  95th Pctile', C['p95']),
            ('─ ─  97th Pctile', C['p97']),
        ]:
            st.markdown(
                f'<div style="font-family:JetBrains Mono,monospace;font-size:10px;'
                f'color:{col};margin-bottom:4px;">{lbl}</div>',
                unsafe_allow_html=True)

        st.markdown('<hr>', unsafe_allow_html=True)

        fm_label = (gacc_config[selected_gacc]['psas']
                    .get(selected_psa, {}).get('fuel_model', '?'))
        n_st = len(gacc_config[selected_gacc]['psas']
                   .get(selected_psa, {}).get('stations', []))
        pcts = meta.get('percentiles', [80, 90, 95, 97])

        st.markdown(f"""
        <div style='font-size:9px;color:{C["dim"]};font-family:JetBrains Mono,monospace;
                    line-height:2;text-transform:uppercase;letter-spacing:.8px;'>
          {gacc_config[selected_gacc]['abbrev']} · PSA {selected_psa}<br>
          Fuel Model: {fm_label} · Stations: {n_st}<br>
          Climo: {meta.get('climo_start',2005)}–{meta.get('climo_end',2020)}<br>
          Percentiles: {pcts}
        </div>""", unsafe_allow_html=True)

    return selected_gacc, selected_psa, selected_field


# ── KPI row ───────────────────────────────────────────────────────────────────
def build_kpis(dfs, fk, baseline, gacc_name):
    df    = get_field_df(dfs, fk)
    fmeta = FIELD_META[fk]
    if df.empty:
        return

    crits, highs, elevs, vals = 0, 0, 0, []
    for _, row in df.iterrows():
        td = row.get('td')
        if td is None:
            continue
        vals.append(td)
        bdata = get_psa_bdata(gacc_name, row['PSA'], baseline, fk)
        lvl, _, _ = alert_level(td, bdata.get('p90'), bdata.get('p95'), bdata.get('p97'))
        if lvl == 'CRITICAL':
            crits += 1
        elif lvl == 'HIGH':
            highs += 1
        elif lvl == 'ELEVATED':
            elevs += 1

    if not vals:
        return

    avg    = sum(vals) / len(vals)
    mx_row = df.loc[df['td'].idxmax()]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric('🔴 Critical PSAs',           crits,              delta='≥ 97th percentile')
    c2.metric('🟠 High PSAs',               highs,              delta='≥ 95th percentile')
    c3.metric('🟡 Elevated PSAs',           elevs,              delta='≥ 90th percentile')
    c4.metric(f'📊 Avg {fmeta["unit"]}',    f'{avg:.1f}')
    c5.metric(f'🔥 Max ({mx_row["PSA"]})',  f'{mx_row["td"]:.0f}')


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    gacc_config = load_gacc_config()
    if not gacc_config:
        st.error('gacc_config.py not found — place it alongside app.py')
        st.stop()

    baseline = load_baseline()
    api_key, username = _creds()

    if not api_key:
        st.markdown("""<div class="badge-err">
        <strong>🔑 FEMS credentials not configured</strong><br><br>
        <strong>Streamlit Cloud:</strong> App Settings → Secrets → add:<br>
        &nbsp;&nbsp;<code>FEMS_API_KEY = "your_key"</code><br>
        &nbsp;&nbsp;<code>FEMS_USERNAME = "your.email@usda.gov"</code><br><br>
        <strong>Local:</strong> create <code>.env</code> with those two lines.
        </div>""", unsafe_allow_html=True)
        st.stop()

    dummy_meta = {
        'fetched_at':  '',
        'fetch_date':  str(date.today()),
        'climo_start': baseline.get('meta', {}).get('climo_start', 2005),
        'climo_end':   baseline.get('meta', {}).get('climo_end',   2020),
        'percentiles': baseline.get('meta', {}).get('percentiles', [80, 90, 95, 97]),
    }

    # Sidebar renders first — needs gacc_config, uses dummy_meta for badge
    selected_gacc, selected_psa, selected_field = build_sidebar(
        gacc_config, 'cached', dummy_meta)

    psa_ids   = list(gacc_config[selected_gacc]['psas'].keys())
    dfs, meta = None, dummy_meta
    source    = 'cached'

    # Try live fetch if cache is stale
    if not _cache_fresh():
        try:
            with st.spinner(
                f'🔄 Fetching {gacc_config[selected_gacc]["abbrev"]} from FEMS...'
            ):
                dfs, meta = load_live(api_key, username,
                                       selected_gacc, tuple(psa_ids))
            source = 'live'
        except Exception as e:
            if _cache_fresh():
                st.warning(f'⚠️ Live fetch failed — using cache. ({e})')
            else:
                st.markdown(
                    f'<div class="badge-err">'
                    f'<strong>❌ FEMS error:</strong> {e}</div>',
                    unsafe_allow_html=True)
                st.stop()

    # Fall back to cache
    if dfs is None:
        try:
            dfs, meta = load_cached()
        except Exception:
            try:
                with st.spinner('Fetching from FEMS...'):
                    dfs, meta = load_live(api_key, username,
                                           selected_gacc, tuple(psa_ids))
                source = 'live'
            except Exception as e2:
                st.error(f'Data load failed: {e2}')
                st.stop()

    abbrev = gacc_config[selected_gacc]['abbrev']
    fmeta  = FIELD_META[selected_field]

    # ── Page header ───────────────────────────────────────────────────────────
    c_h, c_b = st.columns([4, 1])
    with c_h:
        st.markdown(f"""
        <div style="padding:4px 0 16px;">
          <div style="font-family:'Bebas Neue',sans-serif;font-size:36px;
                      color:{C['text']};letter-spacing:4px;line-height:1;">
            {abbrev}
            <span style="color:{C['fire']}">FIRE WEATHER</span>
            INTELLIGENCE
          </div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:10px;
                      color:{C['muted']};letter-spacing:2px;text-transform:uppercase;
                      margin-top:4px;">
            7-Day NFDR Forecast · ERC · IC · BI · SC · FM · KBDI ·
            Climo {meta.get('climo_start',2005)}–{meta.get('climo_end',2020)} Baseline
          </div>
        </div>""", unsafe_allow_html=True)
    with c_b:
        st.markdown(f"""
        <div style="text-align:right;padding-top:8px;">
          <div style="display:inline-block;background:{C['fire']};color:white;
                      padding:6px 18px;border-radius:3px;
                      font-family:'Bebas Neue',sans-serif;font-size:16px;
                      letter-spacing:2px;">{abbrev}</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:9px;
                      color:{C['muted']};margin-top:6px;letter-spacing:1px;
                      text-transform:uppercase;">
            {meta.get('fetch_date', str(date.today()))}
          </div>
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
    lvl, _, cls = alert_level(
        td_val, bdata.get('p90'), bdata.get('p95'), bdata.get('p97'))
    fm_label = (gacc_config[selected_gacc]['psas']
                .get(selected_psa, {}).get('fuel_model', '?'))
    pstr = '  ·  '.join(
        f"P{p}: {bdata.get(f'p{p}', '—')}"
        for p in [80, 90, 95, 97]
        if bdata.get(f'p{p}') is not None
    )

    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:16px;padding:12px 0 20px;flex-wrap:wrap;">
      <span style="font-family:'Bebas Neue',sans-serif;font-size:22px;
                   color:{C['muted']};letter-spacing:3px;">{selected_psa}</span>
      <div class="{cls}">{lvl}</div>
      <span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:{C['muted']};">
        Today: <strong style="color:{C['text']}">
          {f'{td_val:.1f}' if td_val is not None else '—'}
        </strong>
        &nbsp;·&nbsp; Fuel Model:
        <strong style="color:{C['text']}">{fm_label}</strong>
        &nbsp;·&nbsp; {pstr}
      </span>
    </div>""", unsafe_allow_html=True)

    # ── Tabs ──────────────────────────────────────────────────────────────────
    t1, t2, t3, t4, t5, t6, t7 = st.tabs([
        '📈  7-Day Forecast',
        '📊  GACC Overview',
        '🔥  All Indices',
        '📉  ERC Trend',
        '🗺️  Heatmap',
        '⚖️  Percentile Context',
        '🗒️  Data Table',
    ])

    # ── Tab 1: 7-Day for selected PSA + selected field ────────────────────────
    with t1:
        c_main, c_side = st.columns([3, 1])
        with c_main:
            st.plotly_chart(
                chart_7day(sel_dict, selected_field, fmeta, bdata, selected_psa),
                use_container_width=True)
        with c_side:
            st.markdown(f"""
            <div style="background:{C['surface2']};border:1px solid {C['border']};
                        border-radius:6px;padding:16px;margin-top:12px;">
              <div style="font-family:'JetBrains Mono',monospace;font-size:9px;
                          color:{C['muted']};text-transform:uppercase;letter-spacing:1px;
                          margin-bottom:12px;">
                Climo — {fmeta['unit']}
              </div>""", unsafe_allow_html=True)
            for key, lbl, col in [
                ('mean', 'Mean',  C['teal']),
                ('p80',  '80th',  C['p80']),
                ('p90',  '90th',  C['p90']),
                ('p95',  '95th',  C['p95']),
                ('p97',  '97th',  C['p97']),
            ]:
                v = bdata.get(key, '—')
                st.markdown(f"""
                <div style="display:flex;justify-content:space-between;
                            align-items:center;margin-bottom:8px;">
                  <span style="font-family:'JetBrains Mono',monospace;font-size:10px;
                               color:{C['muted']}">{lbl}</span>
                  <span style="font-family:'Bebas Neue',sans-serif;font-size:20px;
                               color:{col}">
                    {f'{v:.0f}' if isinstance(v, float) else v}
                  </span>
                </div>""", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

    # ── Tab 2: GACC-wide overview bar for each primary field ──────────────────
    with t2:
        main_df = get_field_df(dfs, selected_field)
        if not main_df.empty:
            st.plotly_chart(
                chart_bar_today(main_df, selected_field, fmeta, baseline, selected_gacc),
                use_container_width=True)
        others = [f for f in PRIMARY_FIELDS if f != selected_field]
        for i in range(0, len(others), 2):
            cols = st.columns(2)
            for col_w, fk in zip(cols, others[i:i+2]):
                df2 = get_field_df(dfs, fk)
                if not df2.empty:
                    with col_w:
                        st.plotly_chart(
                            chart_bar_today(df2, fk, FIELD_META[fk], baseline, selected_gacc),
                            use_container_width=True)

    # ── Tab 3: All 9 indices for selected PSA ─────────────────────────────────
    with t3:
        st.markdown(
            f'<div style="font-family:JetBrains Mono,monospace;font-size:10px;'
            f'color:{C["muted"]};text-transform:uppercase;letter-spacing:1.5px;'
            f'margin:8px 0 16px;">All Indices — {selected_psa}</div>',
            unsafe_allow_html=True)

        # Fire behaviour row
        fire_fks = ['erc', 'ic', 'bi', 'sc']
        fcols = st.columns(len(fire_fks))
        for col_w, fk in zip(fcols, fire_fks):
            df_f = get_field_df(dfs, fk)
            if df_f.empty:
                continue
            rows_f = df_f[df_f['PSA'] == selected_psa]
            if rows_f.empty:
                continue
            b2 = get_psa_bdata(selected_gacc, selected_psa, baseline, fk)
            with col_w:
                fig = chart_7day(rows_f.iloc[0].to_dict(), fk,
                                  FIELD_META[fk], b2, selected_psa, height=280)
                fig.update_layout(title=_title(FIELD_META[fk]['unit']))
                st.plotly_chart(fig, use_container_width=True)

        st.markdown('<hr>', unsafe_allow_html=True)

        # Fuel moisture row
        fm_fks = ['fm1', 'fm10', 'fm100', 'fm1000']
        fmcols = st.columns(len(fm_fks))
        for col_w, fk in zip(fmcols, fm_fks):
            df_f = get_field_df(dfs, fk)
            if df_f.empty:
                continue
            rows_f = df_f[df_f['PSA'] == selected_psa]
            if rows_f.empty:
                continue
            b2 = get_psa_bdata(selected_gacc, selected_psa, baseline, fk)
            with col_w:
                fig = chart_7day(rows_f.iloc[0].to_dict(), fk,
                                  FIELD_META[fk], b2, selected_psa, height=260)
                fig.update_layout(title=_title(FIELD_META[fk]['unit']))
                st.plotly_chart(fig, use_container_width=True)

        # KBDI full width
        kbdi_df = get_field_df(dfs, 'kbdi')
        if not kbdi_df.empty:
            kr = kbdi_df[kbdi_df['PSA'] == selected_psa]
            if not kr.empty:
                b2 = get_psa_bdata(selected_gacc, selected_psa, baseline, 'kbdi')
                st.plotly_chart(
                    chart_7day(kr.iloc[0].to_dict(), 'kbdi',
                               FIELD_META['kbdi'], b2, selected_psa),
                    use_container_width=True)

    # ── Tab 4: ERC trend ──────────────────────────────────────────────────────
    with t4:
        trend_df = get_field_df(dfs, 'trend')
        if not trend_df.empty:
            t_days = ['td', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']
            t_lbls = ['Today', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon']
            c4a, c4b = st.columns([2, 3])

            with c4a:
                tr = trend_df[trend_df['PSA'] == selected_psa]
                if not tr.empty:
                    trow  = tr.iloc[0]
                    vals  = [trow.get(d, 0) for d in t_days]
                    cbars = [
                        C['crit'] if v and v > 3 else
                        C['high'] if v and v > 0 else
                        C['norm']
                        for v in vals
                    ]
                    fig = go.Figure()
                    fig.add_hline(y=0, line_color=C['border'], line_width=1)
                    fig.add_trace(go.Bar(
                        x=t_lbls, y=vals, marker_color=cbars,
                        marker_line_width=0,
                        hovertemplate=(
                            '<b>%{x}</b>: Δ ERC = '
                            '<b>%{y:+.1f}</b><extra></extra>'),
                    ))
                    fig.update_layout(**{
                        **PL,
                        'title':  _title(f'{selected_psa} ERC TREND'),
                        'height': 300,
                        'yaxis':  {**PL['yaxis'], 'title': 'Δ ERC vs Today'},
                    })
                    st.plotly_chart(fig, use_container_width=True)

            with c4b:
                fig2 = go.Figure()
                palette = [
                    C['fire'], C['teal'], C['gold'], C['p80'],
                    C['p95'], C['p97'], C['p90'], '#74c0fc',
                ]
                for i, (_, row) in enumerate(
                        trend_df.sort_values('PSA').iterrows()):
                    psa = row['PSA']
                    lw  = 3   if psa == selected_psa else 1.2
                    op  = 1.0 if psa == selected_psa else 0.35
                    fig2.add_trace(go.Scatter(
                        x=t_lbls,
                        y=[row.get(d, 0) for d in t_days],
                        mode='lines', name=psa,
                        line=dict(color=palette[i % len(palette)], width=lw),
                        opacity=op,
                        hovertemplate=(
                            f'<b>{psa}</b> · %{{x}}: '
                            f'<b>%{{y:+.1f}}</b><extra></extra>'),
                    ))
                fig2.add_hline(y=0, line_color=C['border'], line_width=1)
                fig2.update_layout(**{
                    **PL,
                    'title':  _title('ERC TREND — All PSAs'),
                    'height': 300,
                    'yaxis':  {**PL['yaxis'], 'title': 'Δ ERC'},
                })
                st.plotly_chart(fig2, use_container_width=True)

    # ── Tab 5: Heatmap ────────────────────────────────────────────────────────
    with t5:
        trend_df = get_field_df(dfs, 'trend')
        if not trend_df.empty:
            st.plotly_chart(chart_trend_heatmap(trend_df), use_container_width=True)

    # ── Tab 6: Percentile context ─────────────────────────────────────────────
    with t6:
        main_df = get_field_df(dfs, selected_field)
        if not main_df.empty:
            st.plotly_chart(
                chart_pctile_grouped(main_df, selected_field, baseline, selected_gacc),
                use_container_width=True)

    # ── Tab 7: Data table ─────────────────────────────────────────────────────
    with t7:
        field_opts = {
            fk: f"{FIELD_META[fk]['unit']} — {FIELD_META[fk]['label']}"
            for fk in ALL_FIELDS
        }
        fc = st.selectbox(
            'Field', list(field_opts.keys()),
            format_func=lambda f: field_opts[f],
            key='tbl_field')
        tbl_df = get_field_df(dfs, fc).copy()
        if tbl_df.empty:
            st.info('No data for this field.')
            return
        search = st.text_input('🔍 Filter PSA', placeholder='e.g. GB21')
        if search:
            tbl_df = tbl_df[tbl_df['PSA'].str.contains(
                search.upper(), na=False)]
        num_cols = [c for c in
                    ['yd', 'td', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon',
                     'Climo_Mean', 'P80', 'P90', 'P95', 'P97']
                    if c in tbl_df.columns]

        display_df = tbl_df.sort_values('PSA')[['PSA'] + num_cols].copy()

        # Round numeric columns — avoids the .style.format() TypeError that
        # crashes when a column contains None/NaN (pandas bug on Python 3.13)
        for c in num_cols:
            display_df[c] = pd.to_numeric(display_df[c], errors='coerce').round(1)

        col_cfg = {
            c: st.column_config.NumberColumn(c, format='%.1f')
            for c in num_cols
        }

        st.dataframe(
            display_df,
            column_config=col_cfg,
            use_container_width=True,
            height=520,
        )
        st.download_button(
            f'⬇ Download {FIELD_META[fc]["unit"]} CSV',
            tbl_df.sort_values('PSA').to_csv(index=False),
            f'{abbrev}_{fc}_{date.today()}.csv',
            'text/csv',
        )


if __name__ == '__main__':
    main()
