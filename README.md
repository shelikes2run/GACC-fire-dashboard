# GACC-fire-dashboard

Fire danger and fire weather products for Predictive Services, published with GitHub Pages
(https://shelikes2run.github.io/GACC-fire-dashboard/) and used in Experience Builder apps in the NIFC ArcGIS Online org.

## What is here

| Product | Pages | Data (built by GitHub Actions) |
|---|---|---|
| CA FDRA fire danger and FDOP | `docs/index.html`, `docs/fdra.html`, `docs/fdop.html` | `site/build_site_data.py` → `site-data` branch; `site/build_fdop_data.py` → `fdop-data` branch |
| GACC Fire Weather (national PSA fire danger vs 2005–2024 climatology) | `docs/wx/` | `site/build_wx.py` → `wx-data` branch, twice a day (`wx-data.yml`) |
| FDRA thresholds | `site/thresholds/FDRA_thresholds.xlsx` | checked on upload (`thresholds-check.yml`) |
| Template for another area (for example Colorado) | `setup/setup_area.ipynb` | see `setup/README.md` |

All data comes from public FEMS downloads; no API keys are stored in the repository.

The earlier Streamlit dashboard (`app.py`, `fems_fetcher.py` and its climatology files) was retired in October 2026;
its views live on in `docs/wx/`, and the files remain in the git history.
