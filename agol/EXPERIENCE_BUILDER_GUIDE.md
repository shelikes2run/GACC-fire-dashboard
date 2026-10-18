# GACC Fire Wx — Experience Builder build guide

How the Streamlit dashboard maps onto ArcGIS Online. The data side is automated by
`agol_pipeline.py` (run it from `GACC_AGOL_Pipeline.ipynb`); the app itself is assembled in
Experience Builder using the items that pipeline creates.

```
FEMS API ──► ArcGIS Notebook (scheduled 2×/day) ──► GACC Fire Wx – PSA Current  (polygons, 1/PSA)
             agol_pipeline.py                    ├► GACC Fire Wx – PSA Daily    (table, PSA × D-30…D+7)
             + gacc_config.py                    └► GACC Fire Wx – Map          (web map, alert styling)
             + gacc_climo_baseline.json                         │
                                                                ▼
                                                 Experience Builder app
```

## 0. Before you open Experience Builder

1. Run the notebook once by hand. Confirm the three items exist in the **GACC Fire Weather** folder.
2. Open **GACC Fire Wx – Map** in Map Viewer and check the PSA polygons line up and colour by alert.
   The layer list has one copy of the PSA layer per index (only *ERC alert — today* is on).
3. Note any PSAs the log listed as *no NIFC boundary* or *no climo* — they'll be missing from the map
   or grey (UNKNOWN) respectively.

## 1. Key fields

**PSA Current** (one polygon per PSA)

| Field pattern | Meaning |
|---|---|
| `gacc`, `gacc_name`, `psa`, `psa_name`, `fuel_model`, `stations`, `n_stations`, `n_with_data` | identity + key RAWS |
| `{idx}_td`, `{idx}_yd` | today / yesterday PSA average (idx = erc ic bi sc fm1 fm10 fm100 fm1000 kbdi gsi woody herb) |
| `{idx}_pk7` | 7-day forecast worst value (max for indices, **min** for fuel moistures) |
| `{idx}_d7` | value on D+7 |
| `{idx}_mean`, `{idx}_p80` … `{idx}_p97` | 2005–2024 climo (9 indices with baseline) |
| `{idx}_alert` / `{idx}_rank` | today's alert: CRITICAL ≥ p97 (3), HIGH ≥ p95 (2), ELEVATED ≥ p90 (1), NORMAL (0), UNKNOWN (-1) — for erc ic bi sc kbdi |
| `{idx}_pk7_alert` / `{idx}_pk7_rank` | same test applied to the 7-day peak |
| `max_alert` / `max_rank` | highest alert across the five indices today |
| `erc_chg7` | ERC change today → D+7 |
| `today_date`, `today_type` (O/F), `run_utc` | freshness |

**PSA Daily** (one row per PSA per day)

`gacc`, `psa`, `obs_date` (dates stored at 12:00 UTC so they show the right day everywhere in the US),
`date_str`, `day_offset` (-30 … +7, 0 = today), `nfdr_type` (O observed / F forecast), `is_forecast`,
every index value, the same climo columns, and `{idx}_alert` / `{idx}_rank`.

## 2. Data views to create (Data panel → each source → *Create view*)

| Source | View name | Filter |
|---|---|---|
| PSA Daily | **Forecast window** | `day_offset` ≥ -5 |
| PSA Daily | **Observed 30 days** | `day_offset` ≤ 0 |
| PSA Current | **ERC Critical** / **ERC High** / **ERC Elevated** | `erc_rank` = 3 / 2 / 1 |

Repeat the three alert views for IC, BI, SC, KBDI if you build KPI rows for every index (see §4).
Set **Auto refresh** on both data sources (Data panel → source → settings) to 30 min so an open app
picks up the 2×-daily updates.

## 3. Page layout

Template: **Blank fullscreen** (or *Foldable* for a collapsible side panel). Theme: **Dark**, then
customise: primary `#ff4d00`, background `#0d0f1a`, surface `#1a1e2e`, text `#e8eaf6`.

```
┌──────────────────────────── Header: title · "Updated {run_utc}" ───────────────────────────┐
├─ Side panel ───────┬──── KPI row (5 text widgets) ────────────────────────────────────────┤
│ Filter: GACC        │                                                                     │
│ Index views nav     │   Map (left 45%)          │  Section: ERC | IC | BI | SC | FM100 | KBDI │
│  (ERC IC BI SC …)   │   + Legend + Layer list    │   └ Views nav: Forecast · Overview · …      │
│ List: PSAs (sorted  │                           │                                             │
│  by alert)          │                           │                                             │
│ Legend text         │                                                                     │
└─────────────────────┴─────────────────────────────────────────────────────────────────────┘
```

## 4. Streamlit → Experience Builder, piece by piece

### Sidebar
| Streamlit | Experience Builder |
|---|---|
| GACC selectbox | **Filter** widget → *Add filter* → *Group* (or one clause per source with the same field) on **PSA Current** and **PSA Daily**, field `gacc`, operator *is*, *Ask for values*, *Unique (predefined)*, single select, default `OSCC`. Turn on *Apply automatically*. |
| PSA selectbox | **List** widget on PSA Current: card shows `psa`, `psa_name`, `{erc_td}` and a colored chip bound to `erc_alert` (Advanced → dynamic style by `erc_rank`). Sort `erc_rank` desc, then `psa`. Clicking a card = selecting the PSA. Map clicks select too (§5). |
| Primary Index radio | **Views navigation** bound to the **Section** that holds the charts — one view per index (ERC, IC, BI, SC, FM-100, KBDI). Build ERC fully, then *Duplicate view* and swap fields. |
| Alert/climo legend | **Text** widget (static) or the map **Legend** widget. |
| Live / cached badge + per-GACC chips | **Text** with dynamic content: *Statistics → Max of `run_utc`* on PSA Current. |
| Refresh All | Not needed — data source auto-refresh + schedule. |
| Password gate | Item sharing (group/org) replaces `check_password()`. |

### Header + KPI row
- Title text: "**{gacc}** FIRE WEATHER INTELLIGENCE" — dynamic `{gacc}` from PSA Current (first record of the filtered set) or static text.
- KPIs (Text widgets, dynamic *Statistics*):
  - Critical PSAs → *Count* on view **ERC Critical**
  - High PSAs → *Count* on **ERC High**
  - Elevated PSAs → *Count* on **ERC Elevated**
  - Avg ERC → *Average* of `erc_td` on PSA Current
  - Max ERC → *Max* of `erc_td` on PSA Current
  
  Filters on a source flow into its views, so the counts follow the GACC filter.
  If your Text widget offers **Arcade** dynamic content, `Count(Filter($dataSources[...].layer, "erc_rank = 3"))`
  avoids making a view per alert level.
- Alert strip for the selected PSA → **Text** connected to PSA Current, *Selected features* view:
  `{psa} · {erc_alert} · Today {erc_td} · Fuel model {fuel_model} · P80 {erc_p80} · P90 {erc_p90} · P95 {erc_p95} · P97 {erc_p97}`.

### Tab 1 — 7-Day Forecast
**Chart** → Line, source **PSA Daily › Forecast window**, *By field*:
category `obs_date` (bin by day), statistic *Average* of `erc`, `erc_mean`, `erc_p80`, `erc_p90`, `erc_p95`, `erc_p97`.
Series colors: erc `#ff4d00` (solid, markers), mean `#00d4b4` dotted, p80 `#4dabf7`, p90 `#ffa94d`, p95 `#ff6b6b`, p97 `#cc5de8` dashed.
The climo series draw as flat reference lines, so no axis guides are needed. To mark where
observations end and the NWS forecast starts, add a category-axis **guide** at today's date or a
footer note ("after today = forecast").

Climo side card → **Text** on PSA Current *Selected features*: Mean `{erc_mean}` · 80th `{erc_p80}` · 90th `{erc_p90}` · 95th `{erc_p95}` · 97th `{erc_p97}`.

> Until a PSA is selected the chart averages every PSA in the GACC. Label it "GACC average — pick a PSA" or
> set the chart's *No data* message and use the List's default selection of the top PSA.

### Tab 2 — GACC Overview
**Chart** → Column, source **PSA Current**, *By group*: category `psa`, statistic *No aggregation* (or *Sum*) on `erc_td`,
**Split by** `erc_alert`, stacked. Color the split series: CRITICAL `#ff2d55`, HIGH `#ff6b00`, ELEVATED `#ffcc00`, NORMAL `#00c875`.
Sort by value descending. Duplicate for IC, BI, SC, FM-100 (`fm100_td`, no split — no FM alerts), KBDI in a 2-column grid.

### Tab 3 — All Indices (selected PSA)
Grid of 9 small **Line** charts on **Forecast window**, each *By field* `{idx}` + `{idx}_p90` + `{idx}_p97`
(ERC, IC, BI, SC / FM-1, FM-10, FM-100, FM-1000 / KBDI). Build one, duplicate, swap fields.
For fuel moistures read the climo lines as *wet-side* percentiles (see Known gaps).

### Tab 4 — ERC Trend (30-day observed)
- Left: **Line** on **Observed 30 days**, *By field* `erc`, `erc_mean`, `erc_p90`, `erc_p95`, `erc_p97` (selected PSA).
- Right: **Line** on **Observed 30 days**, *By group*: category `obs_date`, *Average* `erc`, **Split by** `psa`
  (every PSA in the GACC). Note: split-by doesn't work on a source filtered by another widget's *selection*,
  so point this chart at the view directly and connect it only to the GACC filter, not to the PSA selection.

### Tab 5 — Heatmap (PSA × date)
Experience Builder's Chart widget has no heat chart. Options:
1. **Use the map instead** — the web map already colors PSAs by today's alert and by the 7-day peak,
   which answers "where and when" for most briefings without a grid.
2. **Embed widget** pointing at a small HTML page (GitHub Pages, like the RxFire evaluator) that queries
   PSA Daily and draws the heatmap, with the GACC passed in the URL. Requires the table to be shared
   to whoever views it.
3. **Table** widget on PSA Daily sorted by `psa`, `obs_date` with `erc_alert` shown — readable, not visual.

### Tab 6 — Percentile Context
**Chart** → Column, source **PSA Current**, *By field*: category `psa`, fields `erc_td`, `erc_p90`, `erc_p95`, `erc_p97`,
side-by-side. Colors: today `#ff4d00`, p90 `#ffa94d`, p95 `#ff6b6b`, p97 `#cc5de8`.

### Tab 7 — Data Table
**Table** widget with two sheets: PSA Current (show `psa`, `psa_name`, `{idx}_yd`, `{idx}_td`, `{idx}_pk7`, climo, alert)
and PSA Daily › Forecast window. Turn on *Search* (field `psa`), *Export to CSV*, and *Connect to selection*.

### Tab 8 — About & Data
Static **Text** with the methodology (2005–2024 observed NFDR, key RAWS only, percentiles 80/90/95/97,
fuel-moisture note) plus a dynamic line on PSA Current *Selected features*:
`{psa}: {n_stations} key RAWS ({n_with_data} reporting) — {stations} · Fuel model {fuel_model}`.

## 5. Interactions (Map widget → *Action* tab, List → *Action* tab)

| Trigger | Action | Target |
|---|---|---|
| Map: *Record selection changes* (PSA Current) | **Filter data records** | PSA Daily (+ its views) — relate `psa` ↔ `psa` |
| Map: *Record selection changes* | **Select data records** | List (keeps the side list in sync) |
| List: *Record selection changes* | **Filter data records** | PSA Daily — `psa` ↔ `psa` |
| List: *Record selection changes* | **Zoom to** / **Flash** | Map |
| Filter: *Data filtering changes* | **Zoom to** | Map (frames the selected GACC) |

Add **Legend** and **Layer list** inside the Map widget so users can switch between
*ERC alert — today*, *7-day peak*, *Highest alert (any index)* etc.

## 6. Known gaps / decisions

- **Fuel-moisture alerts are off.** The baseline's FM p80–p97 are wet-side percentiles; the Streamlit
  app compares FM-100 ≥ p97 and labels the line "3rd (Extreme Dry)", which flags wet days. Fix: recompute
  p3/p5/p10/p20 for fm1/fm10/fm100/fm1000 in `GACC_Climo_Download.ipynb`, add them to the baseline, and
  add dry-side alerts in `agol_pipeline.py` (`value ≤ p3` = critical, etc.).
- **SA03** has no climo entry in the baseline → UNKNOWN alerts.
- **SC12** (Lower Desert) inherits SC13's thresholds, same as the Streamlit app. If the NIFC layer has no
  `SC12` polygon it is left off the map (still in the Daily table and charts).
- `fems_fetcher.fetch_psa_history()` is called by `app.py` but isn't in the repo; the pipeline gets the
  30-day history from the same single FEMS request instead.
- AICC is skipped (no key stations configured), as in Streamlit.
