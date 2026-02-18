"""
fems_fetcher.py
───────────────
Pulls ERC/F100 data directly from the FEMS GraphQL API and aggregates
it from RAWS station level to PSA level for the Great Basin GACC.

Credentials are injected by app.py from Streamlit secrets or .env.
Never hardcode credentials here.

Standalone usage (for testing):
    python fems_fetcher.py --check-auth
    python fems_fetcher.py
"""

import os, json, logging, argparse, time
from datetime import datetime, timedelta, date
from statistics import mean
from pathlib import Path

import requests

# ── Credentials (set by app.py before calling fetch_gacc_data) ──
FEMS_API_KEY  = os.getenv("FEMS_API_KEY", "")
FEMS_USERNAME = os.getenv("FEMS_USERNAME", "")
FEMS_API_URL  = "https://fems.fs2c.usda.gov/api/climatology/graphql"

# ── Climatology window matching Great Basin baseline ────────────
CLIMO_START_YEAR = "2005"
CLIMO_END_YEAR   = "2020"
FUEL_MODEL       = "Y"

# ── PSA → RAWS station mapping (WIMS IDs from Config sheet) ─────
PSA_STATIONS = {
    "GB01": [101044, 101108, 101109, 101220, 101223, 101402],
    "GB02": [101303, 101310, 101311, 101312, 101314, 101315, 101805],
    "GB03": [102709, 103207, 103208, 103210, 103211],
    "GB04": [101222, 101708, 102712],
    "GB05": [101809, 101812, 102802, 102903],
    "GB06": [102711, 102907, 103205, 103209, 103403, 104104],
    "GB07": [104004, 104103, 104105],
    "GB08": [103703, 103902, 103903, 104006, 104203],
    "GB09": [102004, 102301, 103904],
    "GB10": [480707, 480708, 480709, 481302, 481306, 481307],
    "GB11": [42802,  43702,  43707,  260117],
    "GB12": [40724,  41302,  260108, 260114, 261204],
    "GB13": [260504, 260701],
    "GB14": [260112, 260202, 260203, 260204, 260206, 260207, 260208],
    "GB15": [260501, 260503, 260601, 260603],
    "GB16": [260810, 261404],
    "GB17": [260310, 260505],
    "GB18": [260305, 260309, 260315],
    "GB19": [260306, 260308, 260314],
    "GB20": [260804, 260805, 260807, 261406],
    "GB21": [261603, 261604, 261608],
    "GB22": [261408],
    "GB23": [261702, 261708],
    "GB24": [261705],
    "GB25": [420403, 420901, 420908, 420911, 420914, 420915],
    "GB26": [420706, 420912, 421101, 421103],
    "GB27": [421501, 421502, 421806],
    "GB28": [421807, 421905, 422610, 422611],
    "GB29": [421301, 421304, 421305, 421406, 421407, 421415, 421416],
    "GB30": [421602],
    "GB31": [421405, 421702, 422002, 422102],
    "GB32": [422710, 422711, 422712],
    "GB33": [422203, 422502, 422803],
    "GB34": [422503, 422604, 422606, 422608, 422609, 422807],
    "GB35": [20107,  20108,  20109,  20114,  20224,  422805, 422806],
}

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("fems_fetcher")


# ── Auth header ──────────────────────────────────────────────────
def _headers():
    if not FEMS_API_KEY:
        raise EnvironmentError("FEMS_API_KEY not set — add it to Streamlit secrets or .env file")
    return {
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "x-api-key":    FEMS_API_KEY,
        "x-user-email": FEMS_USERNAME,
    }


# ── GraphQL runner with retry ────────────────────────────────────
def _query(gql: str, variables: dict = None, retries: int = 3) -> dict:
    payload = {"query": gql}
    if variables:
        payload["variables"] = variables

    for attempt in range(1, retries + 1):
        try:
            r = requests.post(FEMS_API_URL, headers=_headers(), json=payload, timeout=30)
            r.raise_for_status()
            body = r.json()
            if "errors" in body:
                raise ValueError(f"GraphQL errors: {body['errors']}")
            return body.get("data", {})
        except requests.exceptions.Timeout:
            log.warning(f"Timeout (attempt {attempt}/{retries})")
            if attempt < retries:
                time.sleep(2 ** attempt)
        except requests.exceptions.HTTPError as e:
            if r.status_code in (401, 403):
                raise PermissionError(f"Authentication failed ({r.status_code}) — check your FEMS_API_KEY") from e
            log.warning(f"HTTP {r.status_code} (attempt {attempt}/{retries})")
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                raise
        except Exception as e:
            log.warning(f"Error (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                raise

    raise RuntimeError(f"All {retries} attempts failed")


# ── Query 1: 90th/97th percentile thresholds ────────────────────
def fetch_percentile_thresholds(station_ids: list) -> dict:
    ids_str = ",".join(str(s) for s in station_ids)
    log.info(f"  Fetching percentile thresholds ({len(station_ids)} stations)...")
    gql = """
    query PercentileLevels($ids: String!) {
      percentileLevels(
        stationIds: $ids
        fuelModel: Y
        percentileLevels: "90,97"
        climatology: { startYear: "%s" endYear: "%s" startMonthDay: "01-01" endMonthDay: "12-31" startHour: "10" endHour: "20" }
        per_page: 2000
      ) {
        data {
          station_id
          energy_release_component
          hun_hr_tl_fuel_moisture
        }
      }
    }
    """ % (CLIMO_START_YEAR, CLIMO_END_YEAR)

    data = _query(gql, {"ids": ids_str})
    results = {}
    for rec in data.get("percentileLevels", {}).get("data", []):
        sid = rec["station_id"]
        erc = rec.get("energy_release_component", {})
        fm  = rec.get("hun_hr_tl_fuel_moisture", {})
        results[sid] = {
            "erc_p90": float(erc.get("90th") or 0),
            "erc_p97": float(erc.get("97th") or 0),
            "fm_p90":  float(fm.get("90th")  or 0),
            "fm_p97":  float(fm.get("97th")  or 0),
        }
    return results


# ── Query 2: Climatological mean ────────────────────────────────
def fetch_climo_mean(station_ids: list) -> dict:
    ids_str = ",".join(str(s) for s in station_ids)
    log.info(f"  Fetching climo means ({len(station_ids)} stations)...")
    gql = """
    query ClimoMean($ids: String!) {
      percentileAvgMinMax(
        stationIds: $ids
        fuelModel: Y
        climatology: { startYear: "%s" endYear: "%s" startMonthDay: "01-01" endMonthDay: "12-31" startHour: "10" endHour: "20" }
        per_page: 2000
      ) {
        data {
          station_id
          energy_release_component { avg }
          hun_hr_tl_fuel_moisture  { avg }
        }
      }
    }
    """ % (CLIMO_START_YEAR, CLIMO_END_YEAR)

    data = _query(gql, {"ids": ids_str})
    results = {}
    for rec in data.get("percentileAvgMinMax", {}).get("data", []):
        sid = rec["station_id"]
        results[sid] = {
            "erc_mean": float((rec.get("energy_release_component") or {}).get("avg") or 0),
            "fm_mean":  float((rec.get("hun_hr_tl_fuel_moisture")  or {}).get("avg") or 0),
        }
    return results


# ── Query 3: Observed + 7-day forecast ──────────────────────────
def fetch_forecast(station_ids: list) -> dict:
    today     = date.today()
    yesterday = today - timedelta(days=1)
    monday    = today + timedelta(days=(7 - today.weekday()) % 7 or 7)

    ids_str = ",".join(str(s) for s in station_ids)
    log.info(f"  Fetching {yesterday} → {monday} ({len(station_ids)} stations)...")
    gql = """
    query Forecast($ids: String!, $start: Date!, $end: Date!) {
      nfdrMinMax(
        stationIds: $ids
        fuelModels: "Y"
        nfdrType:   "Appended"
        startDate:  $start
        endDate:    $end
        sortBy:     summary_date
        sortOrder:  Asc
        per_page:   50000
      ) {
        data {
          station_id
          summary_date
          nfdr_type
          energy_release_component_max
          hun_hr_tl_fuel_moisture_min
        }
      }
    }
    """
    data = _query(gql, {"ids": ids_str, "start": str(yesterday), "end": str(monday)})
    results = {}
    for rec in data.get("nfdrMinMax", {}).get("data", []):
        sid = rec["station_id"]
        if sid not in results:
            results[sid] = []
        results[sid].append({
            "date": rec["summary_date"],
            "erc":  float(rec.get("energy_release_component_max") or 0),
            "fm":   float(rec.get("hun_hr_tl_fuel_moisture_min")  or 0),
            "type": rec.get("nfdr_type", "O"),
        })
    for sid in results:
        results[sid].sort(key=lambda x: x["date"])
    return results


# ── Batch helper ─────────────────────────────────────────────────
def _batched(lst, size=250):
    for i in range(0, len(lst), size):
        yield lst[i:i+size]


def _fetch_batched(all_ids, fetch_fn):
    merged = {}
    for chunk in _batched(all_ids):
        merged.update(fetch_fn(chunk))
        time.sleep(0.3)
    return merged


# ── PSA aggregator ───────────────────────────────────────────────
def _safe_mean(values):
    vals = [v for v in values if v and v > 0]
    return round(mean(vals), 1) if vals else 0.0


def aggregate_to_psa(psa_id, station_ids, percentiles, climo_means, forecasts):
    today     = date.today()
    yesterday = today - timedelta(days=1)

    def next_weekday(d, wd):
        days = (wd - d.weekday()) % 7 or 7
        return d + timedelta(days=days)

    day_map = {
        "yd":  str(yesterday),
        "td":  str(today),
        "Wed": str(next_weekday(today, 2)),
        "Thu": str(next_weekday(today, 3)),
        "Fri": str(next_weekday(today, 4)),
        "Sat": str(next_weekday(today, 5)),
        "Sun": str(next_weekday(today, 6)),
        "Mon": str(next_weekday(today, 0)),
    }

    # Percentile thresholds averaged across PSA stations
    p90_ercs   = [percentiles[s]["erc_p90"] for s in station_ids if s in percentiles]
    p97_ercs   = [percentiles[s]["erc_p97"] for s in station_ids if s in percentiles]
    p90_fms    = [percentiles[s]["fm_p90"]  for s in station_ids if s in percentiles]
    p97_fms    = [percentiles[s]["fm_p97"]  for s in station_ids if s in percentiles]
    climo_ercs = [climo_means[s]["erc_mean"] for s in station_ids if s in climo_means]
    climo_fms  = [climo_means[s]["fm_mean"]  for s in station_ids if s in climo_means]

    # ERC/FM per day, averaged across stations
    erc_by_day = {k: [] for k in day_map}
    fm_by_day  = {k: [] for k in day_map}
    for sid in station_ids:
        for obs in forecasts.get(sid, []):
            for label, target in day_map.items():
                if obs["date"] == target:
                    if obs["erc"] > 0: erc_by_day[label].append(obs["erc"])
                    if obs["fm"]  > 0: fm_by_day[label].append(obs["fm"])

    erc_row = {label: _safe_mean(vals) for label, vals in erc_by_day.items()}
    fm_row  = {label: _safe_mean(vals) for label, vals in fm_by_day.items()}

    # Trend = each forecast day minus today's observed
    today_erc = erc_row["td"]
    trend_row = {
        label: round(_safe_mean(vals) - today_erc, 1)
        for label, vals in erc_by_day.items()
        if label not in ("yd", "td")
    }
    trend_row["td"] = 0.0

    return {
        "PSA":        psa_id,
        "fuel_model": FUEL_MODEL,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "day_labels": day_map,
        "ERC": {**erc_row, "Climo_Mean": _safe_mean(climo_ercs), "Pctile_90": _safe_mean(p90_ercs), "Pctile_97": _safe_mean(p97_ercs)},
        "FM":  {**fm_row,  "Climo_Mean": _safe_mean(climo_fms),  "Pctile_90": _safe_mean(p90_fms),  "Pctile_97": _safe_mean(p97_fms)},
        "ERC_Trend": {"td":0.0, **{k:v for k,v in trend_row.items() if k!="td"}},
        "station_count": len(station_ids),
        "stations_with_data": len([s for s in station_ids if s in forecasts]),
    }


# ── Main fetch orchestrator ──────────────────────────────────────
def fetch_gacc_data(output_path: str = "gacc_data.json") -> dict:
    start = time.time()
    log.info("=" * 50)
    log.info("FEMS GACC Data Fetch — Great Basin")
    log.info(f"Endpoint : {FEMS_API_URL}")
    log.info(f"User     : {FEMS_USERNAME}")
    log.info(f"PSAs     : {len(PSA_STATIONS)}")
    log.info("=" * 50)

    all_ids = sorted(set(sid for info in PSA_STATIONS.values() for sid in info))
    log.info(f"Total unique RAWS stations: {len(all_ids)}")

    log.info("\n[1/3] Percentile thresholds...")
    percentiles = _fetch_batched(all_ids, fetch_percentile_thresholds)
    log.info(f"  ✓ {len(percentiles)} stations")

    log.info("\n[2/3] Climatological means...")
    climo_means = _fetch_batched(all_ids, fetch_climo_mean)
    log.info(f"  ✓ {len(climo_means)} stations")

    log.info("\n[3/3] Observed + forecast ERC/FM...")
    forecasts = _fetch_batched(all_ids, fetch_forecast)
    log.info(f"  ✓ {len(forecasts)} stations")

    log.info("\nAggregating to PSA level...")
    psa_data = {}
    for psa_id, station_ids in PSA_STATIONS.items():
        psa_data[psa_id] = aggregate_to_psa(psa_id, station_ids, percentiles, climo_means, forecasts)
        erc = psa_data[psa_id]["ERC"]
        log.info(f"  {psa_id}: ERC today={erc['td']:.1f}  90th={erc['Pctile_90']:.1f}  97th={erc['Pctile_97']:.1f}")

    output = {
        "meta": {
            "gacc":          "Great Basin",
            "fetched_at":    datetime.utcnow().isoformat() + "Z",
            "fetch_date":    str(date.today()),
            "climo_start":   CLIMO_START_YEAR,
            "climo_end":     CLIMO_END_YEAR,
            "fuel_model":    FUEL_MODEL,
            "psa_count":     len(psa_data),
            "station_count": len(all_ids),
        },
        "psa": psa_data,
    }

    Path(output_path).write_text(json.dumps(output, indent=2))
    log.info(f"\n✓ Saved → {output_path}  ({time.time()-start:.1f}s)")
    return output


# ── DataFrame converter (used by app.py) ────────────────────────
def json_to_dataframes(data: dict):
    import pandas as pd
    erc_rows, fm_rows, trend_rows = [], [], []

    for psa_id, psa in data["psa"].items():
        e = psa["ERC"]
        erc_rows.append({"PSA":psa_id,"Field":"ERC","yd":e.get("yd",0),"td":e.get("td",0),
            "Wed":e.get("Wed",0),"Thu":e.get("Thu",0),"Fri":e.get("Fri",0),
            "Sat":e.get("Sat",0),"Sun":e.get("Sun",0),"Mon":e.get("Mon",0),
            "Climo_Mean":e.get("Climo_Mean",0),"Pctile_90":e.get("Pctile_90",0),"Pctile_97":e.get("Pctile_97",0)})

        f = psa["FM"]
        fm_rows.append({"PSA":psa_id,"Field":"FM","yd":f.get("yd",0),"td":f.get("td",0),
            "Wed":f.get("Wed",0),"Thu":f.get("Thu",0),"Fri":f.get("Fri",0),
            "Sat":f.get("Sat",0),"Sun":f.get("Sun",0),"Mon":f.get("Mon",0),
            "Climo_Mean":f.get("Climo_Mean",0),"Pctile_90":f.get("Pctile_90",0),"Pctile_97":f.get("Pctile_97",0)})

        t = psa["ERC_Trend"]
        trend_rows.append({"PSA":psa_id,"Field":"ERC","td":t.get("td",0),
            "Wed":t.get("Wed",0),"Thu":t.get("Thu",0),"Fri":t.get("Fri",0),
            "Sat":t.get("Sat",0),"Sun":t.get("Sun",0),"Mon":t.get("Mon",0)})

    return pd.DataFrame(erc_rows), pd.DataFrame(fm_rows), pd.DataFrame(trend_rows)


# ── CLI ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch GACC data from FEMS API")
    parser.add_argument("--output", default="gacc_data.json")
    parser.add_argument("--check-auth", action="store_true", help="Test credentials only")
    args = parser.parse_args()

    # Load .env if running standalone
    try:
        from dotenv import load_dotenv
        load_dotenv()
        FEMS_API_KEY  = os.getenv("FEMS_API_KEY", "")
        FEMS_USERNAME = os.getenv("FEMS_USERNAME", "")
    except ImportError:
        pass

    if args.check_auth:
        log.info("Testing FEMS authentication...")
        try:
            result = _query('query { stationMetaData(stationIds: "101044") { data { station_name state } } }')
            log.info(f"✓ Auth OK — {result}")
        except Exception as e:
            log.error(f"✗ Auth failed: {e}")
        raise SystemExit(0)

    fetch_gacc_data(output_path=args.output)
