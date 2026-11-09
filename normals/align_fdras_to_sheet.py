"""
align_fdras_to_sheet.py — make the FDRA polygons match the 2026 Forest Thresholds
sheet and attach each FDRA's FDOP stations, fuel model and thresholds.

Inputs
  clipped    R5_FDRAs_clipped.geojson     (build_r5_fdras.py)
  national   SRF_STF_TNF_LPF_FDRA.geojson (FDRA_Layers national: SRF-RWP FDOP, Sierra South
                                            348/370, Tahoe NF 350/354/380, Los Padres 512)
  forests    R5_forest_boundaries.geojson
  sheet      fdra_stations.csv            (parse_forest_thresholds.py)

Rules (2026 sheet is authoritative)
  SRF, STF, TNF   replace package polygons with the national layer (sheet numbering);
                  SRF 112 + 115 merged → '112-115'
  LPF             add 512 from the national layer
  LNF             sheet has one station set for the forest → whole forest = 'LNF-ALL'
  MDF             sheet has one FDRA (258) → whole forest = 'MDF-258'
  TMU             sheet: LTBMU rated on FDRA 335 stations → 'TMU-335'
  PNF             sheet West/Central/East; polygons 282/285/293 — matched by which polygon
                  holds the centroid of that FDRA's stations (flagged 'inferred')
  every polygon   clipped to its forest boundary

  FDRAs not in the sheet take the RAWS inside them, else the nearest RAWS (needs all_raws.csv:
  sid,name,lat,lon for every station)

Output: R5_FDRAs_2026.geojson + fdra_station_membership_2026.csv
"""
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPoint

warnings.filterwarnings('ignore')
FOREST = {'LNF': 'Lassen National Forest', 'MDF': 'Modoc National Forest', 'SRF': 'Six Rivers National Forest',
          'STF': 'Stanislaus National Forest', 'TNF': 'Tahoe National Forest', 'LPF': 'Los Padres National Forest',
          'TMU': 'Lake Tahoe Basin Management Unit', 'PNF': 'Plumas National Forest'}


def main(clipped, national, forests, sheet, stations_psv, out_dir, all_stations=None):
    f = gpd.read_file(clipped).to_crs(3310)
    nat = gpd.read_file(national).to_crs(3310)
    nf = gpd.read_file(forests).to_crs(3310)
    nf['geometry'] = nf.geometry.make_valid().buffer(0)
    sh = pd.read_csv(sheet, dtype={'station_ids': str}).fillna('')
    bnd = lambda code: nf.loc[nf.forestname == FOREST[code], 'geometry'].union_all()

    keep = f[~f.forest_code.isin(['SRF', 'STF', 'TNF', 'LNF', 'MDF', 'TMU'])].copy()
    keep['match'] = 'name'
    add = []
    # national replacements
    nat['geometry'] = nat.geometry.make_valid().buffer(0)
    nat.loc[(nat.forest_code == 'SRF') & nat.name.isin(['112', '115']), 'name'] = '112-115'
    nat = nat.dissolve(by=['forest_code', 'name'], as_index=False)
    for _, r in nat.iterrows():
        g = r.geometry.intersection(bnd(r.forest_code))
        if g.area > 1e5:
            add.append({'forest_code': r.forest_code, 'fdra_name': r['name'], 'geometry': g,
                        'source_layer': 'FDRA_Layers (national)', 'match': 'name'})
    # whole-forest FDRAs
    for code, name in (('LNF', 'ALL'), ('MDF', '258')):
        add.append({'forest_code': code, 'fdra_name': name, 'geometry': bnd(code),
                    'source_layer': 'forest boundary (single FDRA in sheet)', 'match': 'whole forest'})
    tmu = f[f.forest_code == 'TMU']
    add.append({'forest_code': 'TMU', 'fdra_name': '335', 'geometry': tmu.union_all(),
                'source_layer': 'FDRA_Layers (national) LTBMU', 'match': 'sheet: LTBMU rated on 335 stations'})
    allp = pd.concat([keep, gpd.GeoDataFrame(add, crs=3310)], ignore_index=True)
    allp['forest'] = allp.forest_code.map(lambda c: FOREST.get(c)) .fillna(allp['forest'])
    allp['fdra_id'] = allp.forest_code + '-' + allp.fdra_name.astype(str)

    # PNF: sheet West/Central/East → polygon holding the centroid of each set's stations
    st = pd.read_csv(stations_psv, sep='|', header=None, names=['sid', 'name', 'psa', 'unit', 'lat', 'lon'])
    stg = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.lon, st.lat), crs=4326).to_crs(3310).set_index('sid')
    pnf_rows = sh[sh.forest_code == 'PNF']
    for _, r in pnf_rows.iterrows():
        ids = [int(x) for x in r.station_ids.split(';') if x and int(x) in stg.index]
        if not ids:
            continue
        c = MultiPoint(list(stg.loc[ids].geometry)).centroid
        hit = allp[(allp.forest_code == 'PNF') & allp.contains(c)]
        if len(hit):
            i = hit.index[0]
            allp.loc[i, 'match'] = f"inferred: sheet '{r.fdra_sheet}' → polygon {allp.loc[i, 'fdra_name']}"
            allp.loc[i, 'fdra_name'] = r.fdra_sheet
            allp.loc[i, 'fdra_id'] = f'PNF-{r.fdra_sheet}'

    # any PNF sheet FDRA still unmatched takes the one remaining PNF polygon (e.g. West → 282:
    # its stations sit west of the forest boundary)
    left_sheet = [r.fdra_sheet for _, r in pnf_rows.iterrows() if f'PNF-{r.fdra_sheet}' not in set(allp.fdra_id)]
    left_poly = allp[(allp.forest_code == 'PNF') & ~allp.match.str.startswith('inferred')].index
    if len(left_sheet) == 1 and len(left_poly) == 1:
        i = left_poly[0]
        allp.loc[i, 'match'] = f"inferred (last remaining): sheet '{left_sheet[0]}' → polygon {allp.loc[i, 'fdra_name']}"
        allp.loc[i, 'fdra_name'] = left_sheet[0]
        allp.loc[i, 'fdra_id'] = f'PNF-{left_sheet[0]}'

    # attach sheet attributes
    sh['key_u'] = sh.fdra_key.str.upper()
    first = sh.drop_duplicates('key_u').set_index('key_u')
    allp['key_u'] = allp.fdra_id.str.upper()
    for col in ['station_ids', 'n_stations', 'fuel_model', 'sl_dl_index', 'standard_90_97', 'custom_thresholds', 'season']:
        allp[col] = allp.key_u.map(first[col]) if col in first else ''
    allp['in_sheet'] = allp.key_u.isin(first.index).astype(int)

    # FDRAs not in the sheet follow location: RAWS inside the polygon, else the nearest
    # RAWS (flagged). Fuel model = the forest's most common sheet fuel model.
    loc_rows = []
    if all_stations is not None:
        ast = pd.read_csv(all_stations)
        apts = gpd.GeoDataFrame(ast, geometry=gpd.points_from_xy(ast.lon, ast.lat), crs=4326).to_crs(3310)
        fm_by_forest = sh[sh.fuel_model != ''].groupby('forest_code').fuel_model.agg(lambda s: s.mode().iat[0])
        for i, r in allp[allp.in_sheet == 0].iterrows():
            inside = apts[apts.within(r.geometry)]
            if len(inside):
                sids, how = inside.sid.astype(int).tolist(), 'location: RAWS inside FDRA'
            else:
                d = apts.distance(r.geometry)
                sids, how = [int(apts.loc[d.idxmin(), 'sid'])], f'location: nearest RAWS ({d.min() / 1000:.0f} km)'
            fm = fm_by_forest.get(r.forest_code, 'Y')
            allp.loc[i, ['station_ids', 'n_stations', 'fuel_model']] = [';'.join(map(str, sids)), len(sids), fm]
            allp.loc[i, 'match'] = how
            loc_rows += [{'fdra_id': r.fdra_id, 'season': '', 'stationId': s, 'fuel_model': fm} for s in sids]
    allp['acres'] = (allp.geometry.area / 4046.856).round(0)
    cols = ['fdra_id', 'forest', 'forest_code', 'fdra_name', 'in_sheet', 'station_ids', 'n_stations', 'fuel_model',
            'sl_dl_index', 'standard_90_97', 'custom_thresholds', 'match', 'source_layer', 'acres', 'geometry']
    out = gpd.GeoDataFrame(allp[cols], crs=3310).to_crs(4326)
    out_dir.mkdir(parents=True, exist_ok=True)
    out.to_file(out_dir / 'R5_FDRAs_2026.geojson', driver='GeoJSON')

    # membership table for the normals notebook (one row per FDRA × station, incl. seasonal rows)
    mem = []
    for _, r in sh.iterrows():
        for x in str(r.station_ids).split(';'):
            if x:
                mem.append({'fdra_id': r.fdra_key, 'season': r.season, 'stationId': int(x), 'fuel_model': r.fuel_model})
    mem += loc_rows
    pd.DataFrame(mem).to_csv(out_dir / 'fdra_station_membership_2026.csv', index=False)

    no_poly = sorted(set(sh.key_u) - set(out.fdra_id.str.upper()))
    no_sheet = out.loc[out.in_sheet == 0, ['fdra_id', 'station_ids', 'match']]
    print(len(out), 'FDRA polygons;', int(out.in_sheet.sum()), 'have sheet stations')
    print('Sheet FDRAs without a polygon:', no_poly)
    print('Polygons not in sheet → stations by location:'); print(no_sheet.to_string(index=False))
    print(out.loc[out.match.str.startswith('inferred'), ['fdra_id', 'match']].to_string(index=False))
    return out


if __name__ == '__main__':
    a = [Path(x) for x in sys.argv[1:8]]
    main(*a)
