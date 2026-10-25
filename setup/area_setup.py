"""Helpers for setup_area.ipynb: turn this repository into the fire danger site for a new area.

Every step writes ordinary files in the repository, so a run can be repeated or fixed by hand:
  docs/assets/area.js                       area settings (name, states, map extent, time zone, ...)
  docs/data/fdras.geojson                   FDRA polygons
  site/fdra_station_membership_2026.csv     SIG stations and fuel model per FDRA
  site/thresholds/FDRA_thresholds.xlsx      FDOP thresholds workbook (edited in Excel afterwards)
"""
from __future__ import annotations

import io
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'site'))
import area as area_mod            # noqa: E402
import thresholds_book as tb       # noqa: E402

RAWS = 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/PublicView_RAWS/FeatureServer/1'
FEMS = 'https://fems.fs2c.usda.gov/api/ext-climatology/download-nfdr-daily-summary/'
FDRAS = ROOT / 'docs' / 'data' / 'fdras.geojson'
MEMBERSHIP = ROOT / 'site' / 'fdra_station_membership_2026.csv'
ALBERS = 5070   # CONUS Albers for areas and acres (Alaska / Hawaii: set the area's "crs")


# ── 1. area settings ──────────────────────────────────────────────────────────
def write_area(settings: dict) -> dict:
    """Write docs/assets/area.js. Required: id, name, repo, states, timezone. Bounds come from the FDRAs if omitted."""
    a = {'stations_source': 'raws_public', 'perimeters': 'nifc', 'pal': {'enabled': False}, 'crs': ALBERS,
         'raws_layer': RAWS, **settings}
    a.setdefault('title', f"{a['name']} Fire Danger Rating Areas")
    a.setdefault('short_title', f"{a['id']} FDRA Fire Danger")
    a.setdefault('subtitle', f"{a['name']} · FDRAs · NFDRS 2016 fuel models")
    a.setdefault('org', a['name'])
    owner, name = a['repo'].split('/')
    a['site_url'] = f'https://{owner.lower()}.github.io/{name}/'
    if 'bounds' not in a and FDRAS.exists():
        import geopandas as gpd
        x0, y0, x1, y1 = gpd.read_file(FDRAS).total_bounds
        a['bounds'] = [[round(y0 - 0.1, 2), round(x0 - 0.1, 2)], [round(y1 + 0.1, 2), round(x1 + 0.1, 2)]]
    area_mod.write(a)
    return area_mod.load()


# ── 2. FDRA boundaries ────────────────────────────────────────────────────────
def read_shapes(paths, workdir: Path | None = None):
    """Read shapefiles, zipped shapefiles, GeoJSON or file geodatabase layers into one GeoDataFrame (EPSG:4326)."""
    import geopandas as gpd
    workdir = Path(workdir or ROOT / 'setup' / 'inputs' / '_unzipped')
    frames = []
    for p in map(Path, paths):
        if p.suffix.lower() == '.zip':
            d = workdir / p.stem
            if d.exists():
                shutil.rmtree(d)
            zipfile.ZipFile(p).extractall(d)
            inner = [q for q in d.rglob('*') if q.suffix.lower() in ('.shp', '.geojson', '.json') or q.suffix.lower() == '.gdb']
            inner += [z for z in d.rglob('*.zip')]
            frames.append(read_shapes(inner, d / '_z'))
        elif p.is_dir() and p.suffix.lower() != '.gdb':
            frames.append(read_shapes([q for q in p.rglob('*') if q.suffix.lower() in ('.shp', '.geojson', '.zip')], workdir))
        else:
            g = gpd.read_file(p)
            g['_source'] = p.name
            frames.append(g.to_crs(4326) if g.crs else g.set_crs(4326))
    frames = [f for f in frames if f is not None and len(f)]
    return pd.concat(frames, ignore_index=True) if frames else None


def build_fdras(shapes, name_field: str, id_prefix: str, names: dict | None = None, forest: str = '', agency: str = 'Interagency',
                fuel_model: str = 'Y', crs: int = ALBERS, min_acres: float = 5):
    """Dissolve the shapes by name_field into one polygon per FDRA, fix geometry and set the layer's fields.
    names = {shape value: (short code, display name)}; otherwise codes come from the first letters of each word."""
    import geopandas as gpd
    from shapely import make_valid
    from shapely.geometry import MultiPolygon, Polygon
    g = shapes.copy()
    g[name_field] = g[name_field].astype(str).str.strip()
    g['geometry'] = g.geometry.apply(make_valid)
    d = g.dissolve(by=name_field).reset_index()

    def parts(x):
        out = []
        for y in getattr(x, 'geoms', [x]):
            if isinstance(y, Polygon) and not y.is_empty:
                out.append(y)
            elif hasattr(y, 'geoms'):
                out += parts(y)
        return out
    pa = d.to_crs(crs)
    rows = []
    for (_, r), geom_m in zip(d.iterrows(), pa.geometry):
        keep = [p for p, pm in zip(parts(r.geometry), parts(geom_m)) if pm.area > min_acres * 4046.86]
        geom = MultiPolygon(keep) if len(keep) > 1 else keep[0]
        val = r[name_field]
        code, disp = (names or {}).get(val, (''.join(w[0] for w in re.findall(r'[A-Za-z]+', val)).upper()[:3], val))
        rows.append({'fdra_id': f'{id_prefix}-{code}', 'forest': forest, 'forest_code': id_prefix, 'fdra_name': disp,
                     'agency': agency, 'station_ids': '', 'fuel_model': fuel_model, 'sl_dl_index': '',
                     'standard_90_97': 'climatology 90th/97th', 'custom_thresholds': '', 'source': '',
                     'acres': float(round(gpd.GeoSeries([geom], crs=4326).to_crs(crs).area.iloc[0] / 4046.86)), 'geometry': geom})
    out = gpd.GeoDataFrame(rows, crs=4326)
    dup = out.fdra_id[out.fdra_id.duplicated()].tolist()
    if dup:
        raise ValueError(f'two FDRAs got the same id {dup}: pass names={{...}} with unique codes')
    return out


def overlaps(fdras, crs: int = ALBERS, min_acres: float = 20):
    """Pairs of FDRAs that overlap by more than min_acres (FDRAs should not overlap)."""
    g = fdras.to_crs(crs)
    out = []
    for i in range(len(g)):
        for j in range(i + 1, len(g)):
            a = g.geometry.iloc[i].intersection(g.geometry.iloc[j]).area / 4046.86
            if a > min_acres:
                out.append((g.fdra_id.iloc[i], g.fdra_id.iloc[j], round(a)))
    return out


def write_fdras(fdras):
    from shapely.geometry import mapping
    from shapely import set_precision, make_valid
    feats = [{'type': 'Feature', 'properties': {k: v for k, v in r.items() if k != 'geometry'},
              'geometry': mapping(make_valid(set_precision(r['geometry'], 1e-5)))} for r in fdras.to_dict('records')]
    FDRAS.write_text(json.dumps({'type': 'FeatureCollection', 'features': feats}, separators=(',', ':')))
    return FDRAS


# ── 3. stations ───────────────────────────────────────────────────────────────
def raws_for_states(states) -> pd.DataFrame:
    """Every RAWS in the states (national public RAWS layer): WIMS id, name, location, active or not, last report."""
    where = 'State IN (' + ', '.join(f"'{s}'" for s in states) + ')'
    rows, start = [], 0
    while True:
        j = requests.get(RAWS + '/query', params={'where': where, 'outFields': 'NWSID,StationName,State,County,Agency,Unit,Status,'
                         'Latitude,Longitude,ObservedDate,MesoWestStationID', 'returnGeometry': 'false', 'f': 'json',
                         'resultOffset': start, 'resultRecordCount': 2000, 'orderByFields': 'OBJECTID'}, timeout=120).json()
        fs = j.get('features', [])
        rows += [f['attributes'] for f in fs]
        if len(fs) < 2000:
            break
        start += len(fs)
    df = pd.DataFrame(rows)
    df['wims'] = pd.to_numeric(df['NWSID'], errors='coerce').astype('Int64')
    df['last_report'] = pd.to_datetime(df['ObservedDate'], unit='ms', errors='coerce').dt.date
    return df


def stations_inside(fdras, raws: pd.DataFrame, buffer_km: float = 0, crs: int = ALBERS) -> pd.DataFrame:
    """RAWS inside (or within buffer_km of) each FDRA, as suggestions for SIGs."""
    import geopandas as gpd
    pts = gpd.GeoDataFrame(raws.dropna(subset=['wims']), geometry=gpd.points_from_xy(raws.dropna(subset=['wims']).Longitude,
                           raws.dropna(subset=['wims']).Latitude), crs=4326).to_crs(crs)
    g = fdras.to_crs(crs)
    rows = []
    for _, f in g.iterrows():
        d = pts.distance(f.geometry) / 1000
        for i in d[d <= buffer_km].index:
            r = pts.loc[i]
            rows.append({'fdra_id': f.fdra_id, 'stationId': int(r.wims), 'name': r.StationName, 'status': r.Status,
                         'km_outside': round(float(d[i]), 1), 'last_report': r.last_report})
    return pd.DataFrame(rows)


def fems_has_data(ids, fuel_model='Y', start='2025-07-01', end='2025-07-07') -> dict:
    """{stationId: rows returned} from FEMS for a week of daily summaries (0 = FEMS has nothing under that id)."""
    out = {int(i): 0 for i in ids}
    ids = sorted(out)
    for k in range(0, len(ids), 20):
        chunk = ids[k:k + 20]
        r = requests.get(FEMS, params={'dataset': 'observation', 'startDate': start, 'endDate': end, 'dataFormat': 'csv',
                                       'stationIds': ','.join(map(str, chunk)), 'fuelModels': fuel_model},
                         headers={'Accept': 'text/csv'}, timeout=300)
        if r.status_code == 404 or len(r.text) < 50:
            continue
        df = pd.read_csv(io.StringIO(r.text))
        for sid, n in df.groupby('StationId').size().items():
            out[int(sid)] = int(n)
    return out


def check_stations(members: pd.DataFrame, raws: pd.DataFrame, use_fems: bool = True) -> pd.DataFrame:
    """One row per SIG station: on the RAWS list? active? FEMS data? and a suggestion when the id looks wrong
    (same station name under another WIMS id)."""
    rl = raws.dropna(subset=['wims']).copy()
    by_id = rl.set_index('wims')
    fems = {}
    if use_fems:
        for fm, grp in members.groupby('fuel_model'):
            try:
                fems.update(fems_has_data(grp.stationId.unique(), fm))
            except Exception as e:      # FEMS unreachable from this computer: the RAWS check still runs
                print('FEMS check skipped:', e)
                fems = {}
                break
    out = []
    for _, m in members.iterrows():
        sid = int(m.stationId)
        r = by_id.loc[sid] if sid in by_id.index else None
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        note, sugg = [], ''
        if r is None:
            note.append('not on the RAWS list under this id')
        elif r.Status != 'A':
            note.append(f'RAWS status {r.Status} (not active)')
        if fems and fems.get(sid, 0) == 0:
            note.append('FEMS returns no data for this id')
        if (r is None or (fems and fems.get(sid, 0) == 0)) and m.get('name'):
            hit = rl[rl.StationName.str.upper().str.replace(r'[^A-Z]', '', regex=True) ==
                     re.sub(r'[^A-Z]', '', str(m['name']).upper())]
            if len(hit):
                sugg = ', '.join(f'{int(h.wims)} ({h.StationName}, {h.Status})' for h in hit.itertuples())
        out.append({'fdra_id': m.fdra_id, 'stationId': sid, 'name_given': m.get('name', ''),
                    'raws_name': None if r is None else r.StationName, 'status': None if r is None else r.Status,
                    'fems_rows': fems.get(sid) if fems else None, 'ok': not note, 'problem': '; '.join(note), 'suggested_id': sugg})
    return pd.DataFrame(out)


def write_membership(members: pd.DataFrame, fdras=None):
    """site/fdra_station_membership_2026.csv (fdra_id, season, stationId, fuel_model, weight) and the layer's station_ids."""
    m = members.copy()
    for c in ('season', 'weight'):
        if c not in m:
            m[c] = ''
    m = m[['fdra_id', 'season', 'stationId', 'fuel_model', 'weight']]
    MEMBERSHIP.write_text(m.to_csv(index=False, lineterminator='\r\n'))
    if fdras is not None:
        st = m.groupby('fdra_id').stationId.apply(lambda s: ';'.join(map(str, s)))
        fm = m.groupby('fdra_id').fuel_model.first()
        fdras['station_ids'] = fdras.fdra_id.map(st).fillna('')
        fdras['fuel_model'] = fdras.fdra_id.map(fm).fillna(fdras['fuel_model'])
    return MEMBERSHIP


# ── 4. thresholds workbook ────────────────────────────────────────────────────
def new_workbook(start: dict | None = None):
    """Write site/thresholds/FDRA_thresholds.xlsx: one FDOP info row per FDRA (blank, or filled from start)."""
    tb.export(start or {})
    d, probs, _ = tb.read()
    return tb.BOOK, probs


def check_workbook(path: Path | None = None):
    d, probs, bad = tb.read(path or tb.BOOK)
    print(tb.report(probs))
    return d, probs


# ── 5. clear California content that does not apply to the new area ──────────
def clear_template_content(area_name: str):
    (ROOT / 'docs' / 'data' / 'fdop_start.json').write_text(json.dumps({'_about': tb.ABOUT}, indent=1))
    (ROOT / 'docs' / 'data' / 'fdop_findings.md').write_text(
        f'# FDOP findings — {area_name}\n\nNotes on each FDRA\'s FDOP thresholds and data checks go here.\n')
    for p in (ROOT / 'agol').glob('*_edits'):
        shutil.rmtree(p, ignore_errors=True)


# ── 6. optional: AGOL layer + web map (ArcGIS API for Python, your own sign-in) ─
def agol_publish(gis, area: dict, title: str | None = None, folder: str | None = None, group: str | None = None):
    """Publish docs/data/fdras.geojson as a hosted feature layer and a web map whose FDRA popup shows today's levels
    from the site build. gis = arcgis.gis.GIS(org_url, username) (you are asked for your password)."""
    from arcgis.gis import ItemProperties  # noqa: F401  (imported to fail early if arcgis is missing)
    raw = f"https://raw.githubusercontent.com/{area['repo']}/site-data/"
    title = title or f"{area['name']} FDRAs"
    item = gis.content.add({'title': title, 'type': 'GeoJson', 'tags': 'FDRA,fire danger,NFDRS'}, data=str(FDRAS), folder=folder)
    lyr = item.publish()
    site = area['site_url']
    popup_levels = {'title': '{fdra_name} — {forest}', 'popupElements': [{'type': 'expression', 'expressionInfo': {
        'title': 'levels', 'returnType': 'dictionary', 'expression': "return { type: 'text', text: $feature.popup_html };"}}]}
    fdra_popup = {'title': '{fdra_name} — {forest}', 'popupElements': [
        {'type': 'expression', 'expressionInfo': {'title': 'levels', 'returnType': 'dictionary', 'expression':
            "var id = $feature.fdra_id;\nvar fs = FeatureSetByName($map, 'FDOP levels today (click an FDRA)', ['fdra_id', 'popup_html'], false);\n"
            "var f = First(Filter(fs, 'fdra_id = @id'));\nif (IsEmpty(f)) { return { type: 'text', text: '' }; }\n"
            "return { type: 'text', text: f.popup_html };"}},
        {'type': 'text', 'text': f"<p style='font-size:12px'><a href='{site}fdra.html?id={{fdra_id}}' target='_blank'>Season tracking ▸</a> · "
                                 f"<a href='{site}fdop.html?id={{fdra_id}}' target='_blank'>FDOP Workbench ▸</a></p>"}]}
    outline = {'renderer': {'type': 'simple', 'symbol': {'type': 'esriSFS', 'style': 'esriSFSNull', 'color': [0, 0, 0, 0],
               'outline': {'type': 'esriSLS', 'style': 'esriSLSSolid', 'color': [20, 20, 20, 255], 'width': 2}}}}
    x0, y0 = area['bounds'][0][1], area['bounds'][0][0]
    x1, y1 = area['bounds'][1][1], area['bounds'][1][0]
    wm = {'operationalLayers': [
        {'id': 'levels', 'title': 'FDOP levels today (click an FDRA)', 'layerType': 'GeoJSON', 'url': raw + 'fdras_sfdi.geojson',
         'visibility': True, 'opacity': 0, 'popupInfo': popup_levels},
        {'id': 'fdra', 'title': 'FDRAs — click for fire danger, FDOP levels and charts', 'layerType': 'ArcGISFeatureLayer',
         'url': lyr.layers[0].url, 'itemId': lyr.id, 'visibility': True, 'layerDefinition': {'drawingInfo': outline},
         'popupInfo': fdra_popup},
        {'id': 'raws', 'title': 'RAWS (latest hourly weather)', 'layerType': 'ArcGISFeatureLayer', 'url': area['raws_layer'],
         'visibility': False, 'layerDefinition': {'definitionExpression': 'State IN (' + ', '.join(f"'{s}'" for s in area['states']) + ')'}}],
        'baseMap': {'baseMapLayers': [{'id': 'topo', 'layerType': 'ArcGISTiledMapServiceLayer', 'visibility': True,
                    'url': 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer'}], 'title': 'Topographic'},
        'spatialReference': {'wkid': 102100}, 'version': '2.30', 'authoringApp': 'setup_area.ipynb'}
    m = gis.content.add({'title': f"{area['name']} FDOP Validation Map", 'type': 'Web Map', 'tags': 'FDRA,fire danger',
                         'extent': f'{x0},{y0},{x1},{y1}', 'text': json.dumps(wm)}, folder=folder)
    if group:
        for it in (lyr, m):
            it.sharing.groups.add(group) if hasattr(it, 'sharing') else it.share(groups=[group])
    return lyr, m
