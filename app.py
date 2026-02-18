"""
GACC Fire Weather Intelligence Dashboard
Pulls live data from FEMS API only — no Excel dependency.
Data is cached in memory for 6 hours, then re-fetched automatically.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json, os
from datetime import datetime, date
from pathlib import Path

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="GACC Fire Weather Dashboard",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap');
  .stApp { background: #1a1d2e; }
  section[data-testid="stSidebar"] { background: #141824 !important; border-right: 1px solid #2d3748; }
  html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; color: #e8eaf6; }
  [data-testid="metric-container"] { background: #242740; border: 1px solid #3a3f6b; border-radius: 8px; padding: 16px !important; border-top: 3px solid #e85d04; }
  [data-testid="metric-container"] label { color: #8b92c4 !important; font-size: 11px !important; text-transform: uppercase; letter-spacing: 0.7px; font-family: 'DM Mono', monospace !important; }
  [data-testid="metric-container"] [data-testid="stMetricValue"] { font-family: 'Syne', sans-serif !important; font-size: 32px !important; font-weight: 800 !important; color: #e8eaf6 !important; }
  .stTabs [data-baseweb="tab-list"] { background: #242740; border-radius: 6px; padding: 4px; gap: 2px; border: 1px solid #3a3f6b; }
  .stTabs [data-baseweb="tab"] { background: transparent; color: #8b92c4; border-radius: 4px; font-family: 'DM Mono', monospace; font-size: 11px; letter-spacing: 0.5px; text-transform: uppercase; padding: 8px 20px; border: none; }
  .stTabs [aria-selected="true"] { background: #e85d04 !important; color: white !important; }
  .stSelectbox label, .stMultiSelect label { color: #8b92c4 !important; font-size: 11px !important; text-transform: uppercase; letter-spacing: 0.7px; font-family: 'DM Mono', monospace !important; }
  .stSelectbox > div > div, .stMultiSelect > div > div { background: #2e3150 !important; border: 1px solid #3a3f6b !important; color: #e8eaf6 !important; border-radius: 4px !important; }
  h1 { font-family: 'Syne', sans-serif !important; font-weight: 800 !important; color: #e8eaf6 !important; }
  h2, h3 { font-family: 'Syne', sans-serif !important; font-weight: 700 !important; color: #e8eaf6 !important; }
  #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
  .status-live   { background: rgba(63,185,80,0.1);  border: 1px solid rgba(63,185,80,0.3);  border-radius: 6px; padding: 10px 14px; font-family: 'DM Mono',monospace; font-size: 11px; color: #3fb950; line-height:1.8; }
  .status-cached { background: rgba(227,179,65,0.1); border: 1px solid rgba(227,179,65,0.3); border-radius: 6px; padding: 10px 14px; font-family: 'DM Mono',monospace; font-size: 11px; color: #e3b341; line-height:1.8; }
  .err-box { background: rgba(192,57,43,0.1); border: 1px solid rgba(192,57,43,0.4); border-radius: 8px; padding: 20px 24px; font-family: 'DM Sans', sans-serif; }
  .err-box h3 { color: #e74c3c !important; margin-bottom: 10px; }
  .err-box code { background: #2e3150; padding: 2px 6px; border-radius: 3px; font-family: 'DM Mono',monospace; font-size: 12px; }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────
COLORS = {
    "bg":"#1a1d2e","surface":"#242740","surface2":"#2e3150","border":"#3a3f6b",
    "fire":"#e85d04","teal":"#4ecdc4","gold":"#ffe66d","text":"#e8eaf6","muted":"#8b92c4",
    "critical":"#c0392b","high":"#e67e22","elevated":"#f1c40f","normal":"#27ae60",
}
PL = dict(
    paper_bgcolor=COLORS["surface"], plot_bgcolor=COLORS["surface"],
    font=dict(color=COLORS["text"], family="DM Sans"),
    margin=dict(t=40, b=40, l=40, r=40),
    legend=dict(bgcolor=COLORS["surface2"], bordercolor=COLORS["border"], borderwidth=1, font=dict(size=11, color=COLORS["muted"])),
    xaxis=dict(gridcolor=COLORS["border"], linecolor=COLORS["border"], tickfont=dict(color=COLORS["muted"], size=10), title_font=dict(color=COLORS["muted"], size=11)),
    yaxis=dict(gridcolor=COLORS["border"], linecolor=COLORS["border"], tickfont=dict(color=COLORS["muted"], size=10), title_font=dict(color=COLORS["muted"], size=11)),
)
DAY_COLS   = ["yd", "td", "Wed", "Thu", "Fri", "Sat", "Sun", "Mon"]
DAY_LABELS = ["Yesterday", "Today", "Wed", "Thu", "Fri", "Sat", "Sun", "Mon"]
CACHE_FILE = Path("gacc_data.json")
CACHE_MAX_AGE_HOURS = 6


# ── Credential loader ─────────────────────────────────────────
def _load_credentials():
    """Load from Streamlit secrets (cloud) or environment/.env (local)."""
    try:
        k = st.secrets["FEMS_API_KEY"]
        u = st.secrets["FEMS_USERNAME"]
        if k and u:
            return k, u
    except Exception:
        pass
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    return os.getenv("FEMS_API_KEY", ""), os.getenv("FEMS_USERNAME", "")


# ── Cache freshness check ─────────────────────────────────────
def _cache_is_fresh():
    if not CACHE_FILE.exists():
        return False
    age = (datetime.now() - datetime.fromtimestamp(CACHE_FILE.stat().st_mtime)).total_seconds()
    return age < CACHE_MAX_AGE_HOURS * 3600


# ── Data loader — FEMS only, two-tier: live → cache ──────────
@st.cache_data(ttl=CACHE_MAX_AGE_HOURS * 3600, show_spinner=False)
def load_from_api(api_key: str, username: str):
    """Fetch fresh data from FEMS, write cache, return DataFrames."""
    import fems_fetcher as ff
    ff.FEMS_API_KEY  = api_key
    ff.FEMS_USERNAME = username
    data = ff.fetch_gacc_data(output_path=str(CACHE_FILE))
    erc, fm, trend = ff.json_to_dataframes(data)
    return erc, fm, trend, data["meta"]


@st.cache_data(show_spinner=False)
def load_from_cache():
    """Load the most recent gacc_data.json from disk."""
    import fems_fetcher as ff
    data = json.loads(CACHE_FILE.read_text())
    erc, fm, trend = ff.json_to_dataframes(data)
    return erc, fm, trend, data["meta"]


def load_data():
    """
    Two-tier loader:
      1. Live FEMS API  — when cache is stale (> 6 hrs) and credentials exist
      2. gacc_data.json — when cache is still fresh
    Shows a clear error if neither works.
    """
    api_key, username = _load_credentials()

    # No credentials at all — show setup instructions
    if not api_key:
        st.markdown("""
        <div class="err-box">
          <h3>🔑 FEMS credentials not configured</h3>
          <p>This dashboard pulls live data from the FEMS API. Add your credentials to continue:</p>
          <p><strong>On Streamlit Cloud:</strong><br>
          App Settings → Secrets → paste these two lines:<br>
          <code>FEMS_API_KEY = "your_key_here"</code><br>
          <code>FEMS_USERNAME = "your.email@usda.gov"</code></p>
          <p><strong>Running locally:</strong><br>
          Create a <code>.env</code> file in the same folder as app.py with those same two lines.</p>
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    # Try live API if cache is stale
    if not _cache_is_fresh():
        try:
            with st.spinner("🔄 Fetching live data from FEMS..."):
                erc, fm, trend, meta = load_from_api(api_key, username)
            return erc, fm, trend, meta, "live"
        except Exception as e:
            # API failed — fall through to cache if available
            if _cache_is_fresh():
                st.warning(f"⚠️ Live fetch failed ({e}) — showing cached data.")
            else:
                st.markdown(f"""
                <div class="err-box">
                  <h3>❌ FEMS API connection failed</h3>
                  <p><strong>Error:</strong> {e}</p>
                  <p>Check that your API key is correct and that fems.fs2c.usda.gov is reachable.
                  Hit <strong>🔄 Refresh</strong> in the sidebar to try again.</p>
                </div>
                """, unsafe_allow_html=True)
                st.stop()

    # Serve from cache
    try:
        erc, fm, trend, meta = load_from_cache()
        return erc, fm, trend, meta, "cached"
    except Exception as e:
        st.error(f"❌ Cache read failed: {e}")
        st.stop()


# ── Alert helpers ─────────────────────────────────────────────
def get_alert_level(erc_val, p90, p97):
    if erc_val >= p97:      return "CRITICAL", COLORS["critical"]
    if erc_val >= p90:      return "HIGH",     COLORS["high"]
    if erc_val >= p90*0.7:  return "ELEVATED", COLORS["elevated"]
    return "NORMAL", COLORS["normal"]


def make_erc_with_alerts(erc):
    levels, colors = [], []
    for _, row in erc.iterrows():
        lvl, col = get_alert_level(row["td"], row["Pctile_90"], row["Pctile_97"])
        levels.append(lvl); colors.append(col)
    erc = erc.copy()
    erc["Alert"]      = levels
    erc["AlertColor"] = colors
    return erc


# ── Charts ────────────────────────────────────────────────────
def chart_overview_bar(erc):
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=erc["PSA"], y=erc["td"],
        marker_color=erc["AlertColor"], marker_line_width=0,
        name="ERC Today",
        hovertemplate="<b>%{x}</b><br>ERC Today: <b>%{y}</b><extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=erc["PSA"], y=erc["Climo_Mean"], mode="lines+markers",
        name="Climo Mean", line=dict(color=COLORS["teal"], width=2, dash="dot"),
        marker=dict(size=4),
    ))
    fig.add_trace(go.Scatter(
        x=erc["PSA"], y=erc["Pctile_90"], mode="lines",
        name="90th Pctile", line=dict(color=COLORS["gold"], width=1.5, dash="dash"), opacity=0.7,
    ))
    layout = {**PL}
    layout["title"]  = dict(text="ERC Today — All PSAs", font=dict(size=14, color=COLORS["text"]))
    layout["xaxis"]  = {**layout["xaxis"], "title": "PSA", "tickangle": -45}
    layout["yaxis"]  = {**layout["yaxis"], "title": "ERC Value"}
    layout["height"] = 380
    fig.update_layout(**layout)
    return fig


def chart_7day_line(erc_row, fm_row=None):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    vals = [erc_row[d] for d in DAY_COLS]

    # Shaded risk band
    fig.add_trace(go.Scatter(
        x=DAY_LABELS + DAY_LABELS[::-1],
        y=[erc_row["Pctile_97"]]*8 + [erc_row["Pctile_90"]]*8,
        fill="toself", fillcolor="rgba(231,76,60,0.08)",
        line=dict(color="rgba(0,0,0,0)"), name="90th–97th Band", hoverinfo="skip",
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=DAY_LABELS, y=vals, mode="lines+markers", name="ERC Forecast",
        line=dict(color=COLORS["fire"], width=3),
        marker=dict(size=8, color=COLORS["fire"], line=dict(color="white", width=1.5)),
        hovertemplate="<b>%{x}</b>: ERC = <b>%{y}</b><extra></extra>",
    ), secondary_y=False)

    fig.add_hline(y=erc_row["Pctile_90"], line_dash="dash", line_color=COLORS["gold"],   opacity=0.7, annotation_text=f"90th: {erc_row['Pctile_90']:.0f}", annotation_font_color=COLORS["gold"],     annotation_font_size=10)
    fig.add_hline(y=erc_row["Pctile_97"], line_dash="dash", line_color=COLORS["critical"],opacity=0.7, annotation_text=f"97th: {erc_row['Pctile_97']:.0f}", annotation_font_color=COLORS["critical"],  annotation_font_size=10)
    fig.add_hline(y=erc_row["Climo_Mean"],line_dash="dot",  line_color=COLORS["teal"],   opacity=0.6, annotation_text=f"Climo: {erc_row['Climo_Mean']:.0f}",annotation_font_color=COLORS["teal"],     annotation_font_size=10)

    if fm_row is not None:
        fig.add_trace(go.Scatter(
            x=DAY_LABELS, y=[fm_row[d] for d in DAY_COLS],
            mode="lines+markers", name="F100",
            line=dict(color=COLORS["teal"], width=2, dash="dot"),
            marker=dict(size=6, color=COLORS["teal"]),
            hovertemplate="<b>%{x}</b>: F100 = <b>%{y}</b><extra></extra>",
        ), secondary_y=True)

    layout = {**PL}
    layout["title"]  = dict(text=f"{erc_row['PSA']} — 7-Day ERC Forecast", font=dict(size=14, color=COLORS["text"]))
    layout["height"] = 380
    layout["xaxis"]["title"] = "Forecast Day"
    layout["yaxis"]["title"] = "ERC"
    fig.update_layout(**layout)
    fig.update_yaxes(title_text="F100", secondary_y=True, tickfont=dict(color=COLORS["teal"], size=10), title_font=dict(color=COLORS["teal"]))
    return fig


def chart_fm_bar(fm):
    colors = [COLORS["critical"] if v<=10 else COLORS["high"] if v<=14 else COLORS["elevated"] if v<=18 else COLORS["normal"] for v in fm["td"]]
    fig = go.Figure(go.Bar(x=fm["PSA"], y=fm["td"], marker_color=colors, marker_line_width=0, hovertemplate="<b>%{x}</b><br>F100: <b>%{y}</b><extra></extra>"))
    layout = {**PL}
    layout["title"]  = dict(text="F100 Today — All PSAs", font=dict(size=14, color=COLORS["text"]))
    layout["xaxis"]  = {**layout["xaxis"], "tickangle": -45}
    layout["yaxis"]  = {**layout["yaxis"], "range": [0, 26]}
    layout["height"] = 320
    fig.update_layout(**layout)
    return fig


def chart_trend_diverging(trend):
    mon_vals = trend["Mon"].fillna(0)
    colors   = [COLORS["critical"] if v > 2 else COLORS["normal"] for v in mon_vals]
    fig = go.Figure(go.Bar(x=trend["PSA"], y=mon_vals, marker_color=colors, marker_line_width=0, hovertemplate="<b>%{x}</b><br>Mon Δ: <b>%{y:+.1f}</b><extra></extra>"))
    fig.add_hline(y=0, line_color=COLORS["border"], line_width=1)
    layout = {**PL}
    layout["title"]  = dict(text="Net ERC Change by Monday (vs Today)", font=dict(size=14, color=COLORS["text"]))
    layout["xaxis"]  = {**layout["xaxis"], "title": "PSA", "tickangle": -45}
    layout["yaxis"]  = {**layout["yaxis"], "title": "ERC Change"}
    layout["height"] = 320
    fig.update_layout(**layout)
    return fig


def chart_trend_line_psa(trend_row):
    t_days   = ["td","Wed","Thu","Fri","Sat","Sun","Mon"]
    t_labels = ["Today","Wed","Thu","Fri","Sat","Sun","Mon"]
    vals     = [trend_row[d] for d in t_days]
    marker_colors = [COLORS["critical"] if v > 0 else COLORS["normal"] for v in vals]
    fig = go.Figure()
    fig.add_hline(y=0, line_color=COLORS["border"], line_width=1, opacity=0.7)
    fig.add_trace(go.Scatter(
        x=t_labels, y=vals, mode="lines+markers",
        line=dict(color=COLORS["fire"], width=2.5),
        marker=dict(size=8, color=marker_colors, line=dict(color="white", width=1.5)),
        name=trend_row["PSA"],
        hovertemplate="<b>%{x}</b>: Δ ERC = <b>%{y:+.1f}</b><extra></extra>",
    ))
    layout = {**PL}
    layout["title"]  = dict(text=f"{trend_row['PSA']} — ERC Change vs Observed", font=dict(size=14, color=COLORS["text"]))
    layout["yaxis"]["title"] = "Δ ERC"
    layout["height"] = 300
    fig.update_layout(**layout)
    return fig


def chart_heatmap_trend(trend):
    t_days   = ["td","Wed","Thu","Fri","Sat","Sun","Mon"]
    t_labels = ["Today","Wed","Thu","Fri","Sat","Sun","Mon"]
    fig = go.Figure(go.Heatmap(
        z=trend[t_days].values, x=t_labels, y=trend["PSA"],
        colorscale=[[0,"#27ae60"],[0.45,"#2e3150"],[0.55,"#2e3150"],[0.75,"#e67e22"],[1,"#c0392b"]],
        zmid=0,
        hovertemplate="PSA: <b>%{y}</b><br>Day: <b>%{x}</b><br>Δ ERC: <b>%{z:+.1f}</b><extra></extra>",
        colorbar=dict(tickfont=dict(color=COLORS["muted"], size=10), title=dict(text="Δ ERC", font=dict(color=COLORS["muted"], size=11))),
    ))
    layout = {**PL}
    layout["title"]  = dict(text="ERC Trend Heatmap — All PSAs × All Days", font=dict(size=14, color=COLORS["text"]))
    layout["height"] = 700
    layout["yaxis"]["autorange"] = "reversed"
    fig.update_layout(**layout)
    return fig


# ── Sidebar ───────────────────────────────────────────────────
def build_sidebar(erc, meta, source):
    with st.sidebar:
        st.markdown("""
        <div style='padding:20px 0 8px;'>
          <div style='font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#e8eaf6;'>
            🔥 <span style='color:#e85d04'>GACC</span> Fire
          </div>
          <div style='font-family:DM Mono,monospace;font-size:10px;color:#8b92c4;letter-spacing:1px;text-transform:uppercase;margin-top:4px;'>
            Weather Intelligence
          </div>
        </div>
        <hr style='border-color:#2d3748;margin:12px 0 16px;'/>
        """, unsafe_allow_html=True)

        # Data source status
        fetched = meta.get("fetched_at", "")[:16].replace("T", " ")
        if source == "live":
            st.markdown(f'<div class="status-live">⬤ LIVE — FEMS API<br><span style="font-size:9px;opacity:0.7">{fetched} UTC · refreshes every 6h</span></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="status-cached">◑ CACHED — {fetched} UTC<br><span style="font-size:9px;opacity:0.7">Auto-refresh in &lt;6h · hit Refresh to force</span></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown("<hr style='border-color:#2d3748;margin:16px 0;'/>", unsafe_allow_html=True)

        psa_options  = sorted(erc["PSA"].unique().tolist())
        selected_psa = st.selectbox("📍 Selected PSA", psa_options,
                                    index=psa_options.index("GB21") if "GB21" in psa_options else 0)

        st.markdown("<hr style='border-color:#2d3748;margin:16px 0;'/>", unsafe_allow_html=True)

        alert_filter = st.multiselect(
            "🚨 Alert Level Filter",
            ["CRITICAL","HIGH","ELEVATED","NORMAL"],
            default=["CRITICAL","HIGH","ELEVATED","NORMAL"],
        )

        st.markdown("<hr style='border-color:#2d3748;margin:16px 0;'/>", unsafe_allow_html=True)
        for label, color in [
            ("CRITICAL  ≥ 97th", COLORS["critical"]),
            ("HIGH      ≥ 90th", COLORS["high"]),
            ("ELEVATED  ≥ 70th", COLORS["elevated"]),
            ("NORMAL    < 70th", COLORS["normal"]),
        ]:
            st.markdown(f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;"><div style="width:12px;height:12px;border-radius:3px;background:{color};flex-shrink:0"></div><span style="font-family:DM Mono,monospace;font-size:11px;color:#8b92c4">{label}</span></div>', unsafe_allow_html=True)

        st.markdown("<hr style='border-color:#2d3748;margin:16px 0;'/>", unsafe_allow_html=True)
        st.markdown(f"""<div style='font-size:10px;color:#4a5270;font-family:DM Mono,monospace;line-height:1.8;'>
          Source: FEMS GraphQL API<br>
          Climo baseline: 2005–2020<br>
          Fuel model: Y<br>
          GACC: Great Basin<br>
          Date: {meta.get("fetch_date","—")}
        </div>""", unsafe_allow_html=True)

    return selected_psa, alert_filter


# ── KPI row ───────────────────────────────────────────────────
def build_kpis(erc):
    critical   = (erc["Alert"] == "CRITICAL").sum()
    high       = (erc["Alert"] == "HIGH").sum()
    above_mean = (erc["td"] > erc["Climo_Mean"]).sum()
    avg_erc    = erc["td"].mean()
    max_psa    = erc.loc[erc["td"].idxmax(), "PSA"]
    max_erc    = erc["td"].max()
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("🔴 Critical PSAs",    critical,       delta="≥ 97th pctile" if critical > 0 else "All clear")
    c2.metric("🟠 High PSAs",        high,           delta="≥ 90th pctile")
    c3.metric("📊 Above Climo Mean", above_mean,     delta=f"of {len(erc)} PSAs")
    c4.metric("📈 Avg ERC Today",    f"{avg_erc:.1f}", delta=f"Climo avg: {erc['Climo_Mean'].mean():.1f}")
    c5.metric(f"🔥 Highest ({max_psa})", f"{max_erc:.0f}")


# ── Main ──────────────────────────────────────────────────────
def main():
    # Load — stops app with instructions if credentials missing
    erc, fm, trend, meta, source = load_data()
    erc = make_erc_with_alerts(erc)

    selected_psa, alert_filter = build_sidebar(erc, meta, source)
    erc_filtered = erc[erc["Alert"].isin(alert_filter)] if alert_filter else erc

    # Header
    col_title, col_badge = st.columns([3, 1])
    with col_title:
        st.markdown('<h1 style="margin-bottom:4px">GACC Fire Weather Intelligence</h1><p style="color:#8b92c4;font-size:14px;margin:0;font-family:DM Mono,monospace;">7-Day ERC & F100 Percentile Dashboard · Great Basin Coordination Center</p>', unsafe_allow_html=True)
    with col_badge:
        fetch_date = meta.get("fetch_date", str(date.today()))
        st.markdown(f'<div style="text-align:right;padding-top:8px"><div style="background:#e85d04;color:white;padding:6px 16px;border-radius:20px;font-size:11px;font-weight:700;display:inline-block;font-family:DM Mono,monospace;letter-spacing:1px">GREAT BASIN GACC</div><div style="color:#8b92c4;font-size:10px;margin-top:6px;font-family:DM Mono,monospace">{fetch_date} · Climo 2005–2020</div></div>', unsafe_allow_html=True)

    st.markdown("<hr style='border-color:#3a3f6b;margin:16px 0 20px;'/>", unsafe_allow_html=True)
    build_kpis(erc_filtered)
    st.markdown("<br/>", unsafe_allow_html=True)

    tab1,tab2,tab3,tab4,tab5 = st.tabs([
        "📊  Overview",
        "📈  7-Day Forecast",
        "📉  ERC Trend",
        "🎯  Data Table",
        "🗺️  Heatmap",
    ])

    # ── Tab 1: Overview ──────────────────────────────────────
    with tab1:
        st.plotly_chart(chart_overview_bar(erc_filtered), use_container_width=True)
        col_a, col_b = st.columns(2)
        with col_a:
            erc_sel = erc[erc["PSA"] == selected_psa].iloc[0]
            fm_sel  = fm[fm["PSA"] == selected_psa]
            st.plotly_chart(chart_7day_line(erc_sel, fm_sel.iloc[0] if not fm_sel.empty else None), use_container_width=True)
        with col_b:
            st.plotly_chart(chart_fm_bar(fm), use_container_width=True)

    # ── Tab 2: 7-Day Forecast ────────────────────────────────
    with tab2:
        psa_options = sorted(erc["PSA"].unique().tolist())
        col_sel, col_info = st.columns([1, 3])
        with col_sel:
            psa_choice = st.selectbox("Select PSA", psa_options,
                                      index=psa_options.index(selected_psa), key="forecast_psa")
        with col_info:
            row = erc[erc["PSA"] == psa_choice].iloc[0]
            lvl, col = get_alert_level(row["td"], row["Pctile_90"], row["Pctile_97"])
            st.markdown(f'<div style="display:flex;gap:24px;align-items:center;padding-top:28px"><div style="background:{col};padding:6px 18px;border-radius:4px;font-family:DM Mono,monospace;font-size:12px;font-weight:700;color:white;letter-spacing:1px">{lvl}</div><span style="color:#8b92c4;font-size:13px">90th: <strong style="color:#e8eaf6">{row["Pctile_90"]:.0f}</strong> &nbsp;|&nbsp; 97th: <strong style="color:#e8eaf6">{row["Pctile_97"]:.0f}</strong> &nbsp;|&nbsp; Climo: <strong style="color:#e8eaf6">{row["Climo_Mean"]:.0f}</strong></span></div>', unsafe_allow_html=True)

        fm_row2 = fm[fm["PSA"] == psa_choice]
        st.plotly_chart(chart_7day_line(row, fm_row2.iloc[0] if not fm_row2.empty else None), use_container_width=True)

        st.markdown("#### Compare Multiple PSAs")
        psa_multi = st.multiselect("Select PSAs", psa_options, default=psa_options[:6], key="multi_psa")
        if psa_multi:
            fig_c = go.Figure()
            for psa in psa_multi:
                r = erc[erc["PSA"] == psa].iloc[0]
                fig_c.add_trace(go.Scatter(x=DAY_LABELS, y=[r[d] for d in DAY_COLS], mode="lines+markers", name=psa, line=dict(width=2), marker=dict(size=5)))
            layout_c = {**PL}
            layout_c["title"]  = dict(text="Multi-PSA ERC Comparison", font=dict(size=14, color=COLORS["text"]))
            layout_c["height"] = 360
            fig_c.update_layout(**layout_c)
            st.plotly_chart(fig_c, use_container_width=True)

    # ── Tab 3: ERC Trend ─────────────────────────────────────
    with tab3:
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.plotly_chart(chart_trend_diverging(trend), use_container_width=True)
        with col_t2:
            psa_t = st.selectbox("PSA", sorted(trend["PSA"].tolist()), key="trend_psa")
            t_row = trend[trend["PSA"] == psa_t].iloc[0]
            st.plotly_chart(chart_trend_line_psa(t_row), use_container_width=True)

        st.markdown("#### 7-Day ERC Trend — All PSAs")
        t_display = trend.copy().drop(columns=["Field"]).rename(columns={
            "td":"Today Δ","Wed":"Wed Δ","Thu":"Thu Δ","Fri":"Fri Δ","Sat":"Sat Δ","Sun":"Sun Δ","Mon":"Mon Δ"
        })
        st.dataframe(
            t_display.style
                .background_gradient(subset=["Today Δ","Wed Δ","Thu Δ","Fri Δ","Sat Δ","Sun Δ","Mon Δ"], cmap="RdYlGn_r", vmin=-15, vmax=10)
                .format({c:"{:+.1f}" for c in ["Today Δ","Wed Δ","Thu Δ","Fri Δ","Sat Δ","Sun Δ","Mon Δ"]}),
            use_container_width=True, height=460,
        )

    # ── Tab 4: Data Table ────────────────────────────────────
    with tab4:
        st.markdown("#### ERC Percentile Data — All PSAs")
        col_s1, col_s2 = st.columns([1, 3])
        with col_s1:
            search = st.text_input("🔍 Search PSA", placeholder="e.g. GB21")
        with col_s2:
            sort_col = st.selectbox("Sort by", ["PSA","td","Climo_Mean","Pctile_90","Pctile_97"],
                format_func=lambda x: {"td":"Today","Climo_Mean":"Climo Mean","Pctile_90":"90th Pctile","Pctile_97":"97th Pctile"}.get(x,x))

        display = erc.copy()
        if search:
            display = display[display["PSA"].str.contains(search.upper(), na=False)]
        display = display.sort_values(sort_col, ascending=(sort_col=="PSA"))
        display = display[["PSA","Alert","yd","td","Wed","Thu","Fri","Sat","Sun","Mon","Climo_Mean","Pctile_90","Pctile_97"]]

        st.dataframe(
            display.style.format({c:"{:.0f}" for c in ["yd","td","Wed","Thu","Fri","Sat","Sun","Mon","Climo_Mean","Pctile_90","Pctile_97"]}),
            use_container_width=True, height=560,
        )
        st.download_button("⬇️ Download CSV", display.to_csv(index=False), "gacc_erc_data.csv", "text/csv")

    # ── Tab 5: Heatmap ───────────────────────────────────────
    with tab5:
        st.plotly_chart(chart_heatmap_trend(trend), use_container_width=True)
        st.markdown('<div style="font-size:12px;color:#8b92c4;line-height:1.8;padding:12px 0;"><strong style="color:#e8eaf6">Reading this chart:</strong> Green = ERC decreasing (improving conditions) &nbsp;|&nbsp; Red = ERC increasing (worsening conditions) &nbsp;|&nbsp; Dark = stable</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
