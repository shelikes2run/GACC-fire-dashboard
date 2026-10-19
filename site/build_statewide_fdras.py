"""
build_statewide_fdras.py — one statewide, non-overlapping FDRA layer.

  1. National-forest FDRAs from the 2026 Forest Thresholds sheet (docs/data/fdras.geojson as built
     by normals/align_fdras_to_sheet.py) go on top; where two forest FDRAs overlap, the smaller wins.
  2. CAL FIRE's statewide FDRA_MASTER_2 (FDRA_View layer 6, the layer the CA Prescribed Fire
     Planner uses) fills the rest of the state: pieces with the same unit + FDRA name are merged,
     named FDRAs win over catch-all polygons ("… UNIT", "LOCAL", blank), smaller beats larger, and
     everything is clipped around the forest FDRAs. Slivers under 1,000 acres are dropped.
  3. Stations: forest FDRAs keep the sheet's FDOP stations, fuel model and thresholds; the others get
     the RAWS inside them (nearest RAWS if none), fuel model Y — "follows where it is located".

    python site/build_statewide_fdras.py CALFIRE_MASTER.geojson
Writes docs/data/fdras.geojson (statewide) and site/fdra_station_membership_2026.csv (appends).
"""
import re
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd

warnings.filterwarnings('ignore')
ROOT = Path(__file__).resolve().parents[1]
FOREST = ROOT / 'docs' / 'data' / 'fdras_forest_2026.geojson'
OUT = ROOT / 'docs' / 'data' / 'fdras.geojson'
MEM = ROOT / 'site' / 'fdra_station_membership_2026.csv'
RAWS = ROOT / 'site' / 'ca_raws.csv'
FORESTS = ROOT / 'site' / 'R5_forest_boundaries.geojson'      # USFS EDW administrative forest boundaries, R5
GENERIC = re.compile(r'(^$|^\s*$|UNIT$|^LOCAL$|^FRA$|^LRA|^FED$|^NULL$|^NONE$)', re.I)
UNIT_NAMES = {'AEU': 'Amador-El Dorado', 'BDU': 'San Bernardino', 'BEU': 'San Benito-Monterey', 'BTU': 'Butte', 'CZU': 'San Mateo-Santa Cruz',
              'FKU': 'Fresno-Kings', 'HUU': 'Humboldt-Del Norte', 'KRN': 'Kern County', 'LAC': 'Los Angeles County', 'LMU': 'Lassen-Modoc',
              'LNU': 'Sonoma-Lake-Napa', 'MEU': 'Mendocino', 'MMU': 'Madera-Mariposa-Merced', 'MRN': 'Marin County', 'MVU': 'San Diego (MVU)',
              'NEU': 'Nevada-Yuba-Placer', 'ORC': 'Orange County', 'RRU': 'Riverside', 'SBC': 'Santa Barbara County', 'SCU': 'Santa Clara',
              'SDU': 'San Diego', 'SHU': 'Shasta-Trinity', 'SKU': 'Siskiyou', 'SLU': 'San Luis Obispo', 'TCU': 'Tuolumne-Calaveras',
              'TGU': 'Tehama-Glenn', 'TUU': 'Tulare', 'VNC': 'Ventura County', 'BLM': 'BLM', 'NPS': 'NPS', 'UFW': 'USFWS', 'USF': 'USFS',
              'LNF': 'Lassen NF', 'SQF': 'Sequoia NF', 'SRF': 'Six Rivers NF'}


def norm(s):
    s = re.sub(r'\s+', ' ', str(s or '').strip())
    return s.title() if s.isupper() or s.islower() else s


def main(master_path):
    if not FOREST.exists():                       # first run: keep the forest-only layer as the source
        FOREST.write_bytes(OUT.read_bytes())
    fo = gpd.read_file(FOREST).to_crs(3310)
    fo['geometry'] = fo.geometry.make_valid().buffer(0)
    nf = gpd.read_file(FORESTS).to_crs(3310)
    nf['geometry'] = nf.geometry.make_valid().buffer(0)
    nf_union = nf.union_all()
    fo['geometry'] = fo.geometry.intersection(nf_union)          # forest FDRAs stay inside forest boundaries
    fo = fo.sort_values('acres')                  # smaller forest FDRA wins an overlap
    taken, keep = None, []
    for _, r in fo.iterrows():
        g = r.geometry if taken is None else r.geometry.difference(taken)
        taken = r.geometry if taken is None else taken.union(r.geometry)
        if g.area > 4e6:
            keep.append({**r.drop('geometry').to_dict(), 'geometry': g, 'source': 'USFS 2026 Forest Thresholds FDRA'})
    keep = gpd.GeoDataFrame(keep, crs=3310)
    # every acre of every forest belongs to one of its FDRAs: gaps go to the forest FDRA sharing the
    # longest border with them (same forest first), else the nearest one
    # Sierra South FDOP: the Stanislaus high country above the 348/370 elevation bands is FDRA 533
    # (High Elevation, shared STF / YNP / SNF), so Stanislaus gaps go to 533
    GAP_TO = {'Stanislaus National Forest': 'SNF-533'}
    filled = 0
    for _, f in nf.iterrows():
        gap = f.geometry.difference(keep.union_all())
        parts = [p for p in getattr(gap, 'geoms', [gap]) if p.area > 1e4]
        same = keep[keep.forest == f.forestname]
        for p in parts:
            if f.forestname in GAP_TO and (keep.fdra_id == GAP_TO[f.forestname]).any():
                i = keep.index[keep.fdra_id == GAP_TO[f.forestname]][0]
                keep.at[i, 'geometry'] = keep.at[i, 'geometry'].union(p)
                filled += p.area
                continue
            pool = same if len(same) else keep
            shared = pool.geometry.apply(lambda g: g.buffer(30).intersection(p.boundary).length)
            i = shared.idxmax() if shared.max() > 0 else pool.distance(p).idxmin()
            if shared.max() == 0 and len(same):                    # not touching its own forest's FDRAs: try any
                sh2 = keep.geometry.apply(lambda g: g.buffer(30).intersection(p.boundary).length)
                if sh2.max() > 0:
                    i = sh2.idxmax()
            keep.at[i, 'geometry'] = keep.at[i, 'geometry'].union(p)
            filled += p.area
    keep['geometry'] = keep.geometry.buffer(0)
    print(f'forest gaps filled: {filled / 4046.86:,.0f} ac')
    forest_union = nf_union

    m = gpd.read_file(master_path)
    m = m[m.geometry.notna()].to_crs(3310)
    m['geometry'] = m.geometry.make_valid().buffer(0)
    m['unit'] = m['UNIT'].fillna('').astype(str).str.strip()
    m['name'] = m['FDRA'].fillna('').astype(str).str.strip()
    m.loc[m.unit == '', 'unit'] = 'LOCAL'
    m['key'] = m.unit.str.upper() + '|' + m.name.str.upper().str.replace(r'\s+', ' ', regex=True)
    m['generic'] = m.name.apply(lambda s: bool(GENERIC.search(s)))
    d = m.dissolve(by='key', aggfunc={'unit': 'first', 'name': 'first', 'generic': 'first', 'FDOP_Name': 'first',
                                      'Source': 'first', 'FDRA_Num': 'first'}).reset_index()
    d['area'] = d.geometry.area
    d = d.sort_values(['generic', 'area'])        # named before catch-all, then smaller first
    taken = forest_union
    cf = []
    for _, r in d.iterrows():
        g = r.geometry.difference(taken)
        taken = taken.union(r.geometry)
        if g.area < 4.05e6:                       # < 1,000 ac
            continue
        name = norm(r['name']) or 'Unit-wide'
        fid = f"{r.unit}-{name}"
        fdop = norm(r.FDOP_Name) if r.FDOP_Name and not str(r.FDOP_Name).startswith('NJC_') else 'Local'
        cf.append({'fdra_id': fid, 'forest': UNIT_NAMES.get(r.unit, fdop or r.unit), 'forest_code': r.unit, 'fdra_name': name,
                   'fuel_model': 'Y', 'sl_dl_index': '', 'standard_90_97': 'climatology 90th/97th', 'custom_thresholds': '',
                   'source': f"CAL FIRE FDRA_MASTER_2 ({str(r.Source or '').strip() or 'n/a'})", 'geometry': g})
    cf = gpd.GeoDataFrame(cf, crs=3310)
    # same id twice (e.g. generic pieces) → merge
    cf = cf.dissolve(by='fdra_id', aggfunc='first').reset_index()

    raws = pd.read_csv(RAWS)
    pts = gpd.GeoDataFrame(raws, geometry=gpd.points_from_xy(raws.lon, raws.lat), crs=4326).to_crs(3310)
    mem = pd.read_csv(MEM).fillna('')
    mem = mem[mem.fdra_id.isin(set(fo.fdra_id)) | mem.season.ne('')]     # drop rows from earlier statewide runs
    new_rows = []
    for i, r in cf.iterrows():
        inside = pts[pts.within(r.geometry)]
        if len(inside):
            sids, how = inside.sid.astype(int).tolist(), 'RAWS inside'
        else:
            dd = pts.distance(r.geometry)
            sids, how = [int(pts.loc[dd.idxmin(), 'sid'])], f'nearest RAWS ({dd.min() / 1000:.0f} km)'
        cf.loc[i, 'station_ids'] = ';'.join(map(str, sids))
        cf.loc[i, 'n_stations'] = len(sids)
        cf.loc[i, 'match'] = how
        new_rows += [{'fdra_id': r.fdra_id, 'season': '', 'stationId': s, 'fuel_model': 'Y'} for s in sids]
    fos = keep
    # CAL FIRE polygons that carry a forest FDRA's name but lie outside the forest (e.g. SQF 435-445 in
    # Sequoia-Kings Canyon NP) stay separate, labelled as outside the National Forest
    clash = cf.fdra_id.isin(set(fos.fdra_id))
    ren = {fid: fid + ' (outside NF)' for fid in cf.loc[clash, 'fdra_id']}
    cf['fdra_id'] = cf['fdra_id'].replace(ren)
    for x in new_rows:
        x['fdra_id'] = ren.get(x['fdra_id'], x['fdra_id'])
    allp = pd.concat([fos, cf], ignore_index=True)
    allp['acres'] = (allp.geometry.area / 4046.86).round(0)
    allp['agency'] = allp['source'].map(lambda s: 'USFS' if s.startswith('USFS') else 'CAL FIRE / interagency')
    cols = ['fdra_id', 'forest', 'forest_code', 'fdra_name', 'agency', 'station_ids', 'fuel_model', 'sl_dl_index', 'standard_90_97',
            'custom_thresholds', 'source', 'acres', 'geometry']
    out = gpd.GeoDataFrame(allp[cols], crs=3310)
    out['geometry'] = out.geometry.simplify(40, preserve_topology=True).make_valid().buffer(0)
    out = out.to_crs(4326)
    out.to_file(OUT, driver='GeoJSON', COORDINATE_PRECISION=5)
    pd.concat([mem, pd.DataFrame(new_rows)], ignore_index=True).to_csv(MEM, index=False)
    o3 = out.to_crs(3310)
    print(f'{len(out)} FDRAs ({len(fos)} forest + {len(cf)} CAL FIRE/interagency), {o3.area.sum() / 4046.86 / 1e6:.1f} M ac')
    for _, f in nf.iterrows():                    # coverage check per forest
        cov = o3[o3.agency == 'USFS'].intersection(f.geometry).area.sum() / f.geometry.area
        if cov < 0.995:
            print(f'  {f.forestname}: {100 * cov:.1f}% covered by forest FDRAs')
    return out


if __name__ == '__main__':
    main(sys.argv[1])
