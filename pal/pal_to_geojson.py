"""
pal_to_geojson.py — CA PAL Combined Report → GeoJSON points for the AGOL web map.

Reads the public report (https://gacc.nifc.gov/oscc/predictive/weather/pal_combined_report.html
and its .js) and writes one point per RAWS with:
  name, forest, classification, elevation_ft, aspect_deg
  pal          today's PAL (override applied when one is active)
  pal_raw      PAL before any override;  pal_override, override_comment, override_until
  erc, ic      the 1400 observation the report used
  fc_dates     13 days, comma-separated (e.g. 2026-10-13,…)
  fc_pal       PAL per day (A,B,C,D,Ev,E or -)
  fc_type      O = observed, F = forecast, per day
  report_time  when the report was generated

Run by .github/workflows/pal-refresh.yml; output goes to the `pal-data` branch.
    python pal/pal_to_geojson.py out.geojson [--html file --js file]   (files = offline test)
"""
import argparse
import html as H
import json
import re
import sys
from pathlib import Path

BASE = 'https://gacc.nifc.gov/oscc/predictive/weather/'
PAL_ORDER = ['A', 'B', 'C', 'D', 'Ev', 'E']


def _get(url):
    import requests
    r = requests.get(url, timeout=60, headers={'User-Agent': 'CA-GACC-PAL-feed (GitHub Actions)'})
    r.raise_for_status()
    return r.text


def _cells(row):
    return re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)


def _text(c):
    return H.unescape(re.sub(r'<[^>]+>', '', c)).strip()


def _table_after(page, heading):
    i = page.find(heading)
    if i < 0:
        return None, []
    t = page[i:page.find('</table>', i)]
    head = [_text(x) for x in re.findall(r'<th[^>]*>(.*?)</th>', t, re.S)]
    body = t[t.find('<tbody>'):]
    return head, re.findall(r'<tr>(.*?)</tr>', body, re.S)


def parse(page, js):
    m = re.search(r'const STATION_DATA\s*=\s*(\[.*?\]);\s*\n', js, re.S)
    stations = json.loads(m.group(1))
    m = re.search(r'const OVERRIDES_DATA\s*=\s*(\{.*?\});\s*\n', js, re.S)
    overrides = json.loads(m.group(1)) if m else {}
    m = re.search(r'generated\s+([0-9-]+ [0-9:]+ ?\w*)', js)
    generated = m.group(1) if m else ''

    obs = {}
    _, rows = _table_after(page, 'Station Observations')
    for r in rows:
        c = [_text(x) for x in _cells(r)]
        if len(c) >= 6:
            num = lambda v: float(v) if re.fullmatch(r'-?\d+(\.\d+)?', v) else None
            obs[c[0].upper()] = {'erc': num(c[3]), 'ic': num(c[4]), 'pal_obs': c[5]}

    fc = {}
    head, rows = _table_after(page, 'Forecast (Daily Summary)')
    dates = [h for h in (head or []) if re.fullmatch(r'\d{4}-\d\d-\d\d', h)]
    for r in rows:
        cs = _cells(r)
        if len(cs) < 3:
            continue
        pals, types = [], []
        for c in cs[2:]:
            p, _, t = c.partition('<br>')
            p, t = _text(p), _text(t).upper()
            pals.append(p if p in PAL_ORDER else '-')
            types.append(t if t in ('O', 'F') else '-')
        fc[_text(cs[0]).upper()] = (pals, types)

    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()
    feats = []
    for s in stations:
        key = s['name'].upper()
        ov = overrides.get(s['name']) or overrides.get(key)
        if not (isinstance(ov, dict) and ov.get('pal') and str(ov.get('valid_until', '')) >= today):
            ov = None                                       # same rule as the report: active until valid_until
        o = obs.get(key, {})
        pals, types = fc.get(key, ([], []))
        props = {
            'name': s['name'], 'forest': s.get('forest') or '', 'classification': s.get('classification') or '',
            'elevation_ft': s.get('elevation_ft'), 'aspect_deg': s.get('aspect_deg'),
            'pal_raw': s.get('pal'), 'erc': o.get('erc'), 'ic': o.get('ic'),
            # '' rather than null so the fields always exist in the GeoJSON layer
            'pal_override': (ov or {}).get('pal') or '', 'override_comment': (ov or {}).get('comment') or '',
            'override_until': (ov or {}).get('valid_until') or '', 'override_by': (ov or {}).get('set_by') or '',
            'fc_dates': ','.join(dates) if pals else '', 'fc_pal': ','.join(pals), 'fc_type': ','.join(types),
            'forest_pal_station': 1 if key in fc else 0, 'report_time': generated,
        }
        props['pal'] = props['pal_override'] or props['pal_raw']
        props['pal_rank'] = PAL_ORDER.index(props['pal']) + 1 if props['pal'] in PAL_ORDER else None
        feats.append({'type': 'Feature', 'properties': props,
                      'geometry': {'type': 'Point', 'coordinates': [s['lon'], s['lat']]}})
    return {'type': 'FeatureCollection', 'name': 'CA_PAL_stations', 'report_time': generated, 'features': feats}


def append_history(gj, path: Path):
    """Keep every observed (O) day per forest PAL station: station,date,pal."""
    import csv
    rows = {}
    if path.exists():
        with path.open() as f:
            for r in csv.DictReader(f):
                rows[(r['station'], r['date'])] = r['pal']
    for ft in gj['features']:
        p = ft['properties']
        if not p['fc_dates']:
            continue
        for d, pal, t in zip(p['fc_dates'].split(','), p['fc_pal'].split(','), p['fc_type'].split(',')):
            if t == 'O' and pal in PAL_ORDER:
                rows[(p['name'], d)] = pal
    with path.open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['station', 'date', 'pal'])
        for (s, d), pal in sorted(rows.items()):
            w.writerow([s, d, pal])


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--html')
    ap.add_argument('--js')
    ap.add_argument('--history', help='CSV of daily observed PAL per station (appended, de-duplicated)')
    a = ap.parse_args()
    page = Path(a.html).read_text() if a.html else _get(BASE + 'pal_combined_report.html')
    js = Path(a.js).read_text() if a.js else _get(BASE + 'pal_combined_report.js')
    gj = parse(page, js)
    n = len(gj['features'])
    if n < 100:
        sys.exit(f'only {n} stations parsed — report format may have changed; not writing')
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(gj, separators=(',', ':')))
    if a.history:
        append_history(gj, Path(a.history))
    nf = sum(f['properties']['forest_pal_station'] for f in gj['features'])
    print(f"{n} stations ({nf} with 13-day PAL), report {gj['report_time']} → {a.out}")
