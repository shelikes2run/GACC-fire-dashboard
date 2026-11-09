"""
build_r5_fdras.py — one statewide layer of national-forest FDRAs, each clipped
to its own forest's administrative boundary.

Inputs (not in the public repo — kept on your PC in normals/fdra/):
  FDRA_0930.ppkx          ArcGIS Pro project package of unit FDRA layers
  ENF_LTBMU_FDRA.geojson  Eldorado (330/335/340) + LTBMU from FDRA_Layers (national)
  MDF_PNF_FDRA.geojson    Modoc + Plumas FDRAs from FDRA_Layers (national)
  R5_forest_boundaries.geojson  USFS EDW Administrative Forest Boundaries, Region 5

Output: normals/fdra/R5_FDRAs_clipped.geojson  (WGS84) with fields
  fdra_id (e.g. 'SQF-440'), forest, forest_code, fdra_name, source_layer, acres

    python normals/build_r5_fdras.py <extracted ppkx commondata dir> <ENF geojson> <R5 boundaries geojson> <MDF/PNF geojson> [out]
"""
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd

warnings.filterwarnings('ignore')

FOREST = {  # code → EDW forestname
    'ANF': 'Angeles National Forest', 'CNF': 'Cleveland National Forest', 'ENF': 'Eldorado National Forest',
    'INF': 'Inyo National Forest', 'KNF': 'Klamath National Forest', 'LNF': 'Lassen National Forest',
    'LPF': 'Los Padres National Forest', 'MNF': 'Mendocino National Forest', 'MDF': 'Modoc National Forest',
    'SRF': 'Six Rivers National Forest', 'PNF': 'Plumas National Forest', 'BDF': 'San Bernardino National Forest',
    'SQF': 'Sequoia National Forest', 'SHF': 'Shasta-Trinity National Forest', 'SNF': 'Sierra National Forest',
    'STF': 'Stanislaus National Forest', 'TNF': 'Tahoe National Forest', 'TMU': 'Lake Tahoe Basin Management Unit',
}


def _s(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def sources(cd: Path, enf_geojson: Path, mdf_pnf_geojson: Path | None = None):
    """(forest code, GeoDataFrame, name function, label) for each forest's FDRA layer.

    Uses the newest layer per forest. Notes on the Pro package:
      - r05_shf.gdb/FDRA is labelled STF_FDRA_2025 in the project but is Shasta-Trinity.
      - 2022/STF2022FDRAs_all_Elev is Stanislaus (Sierra South FDOP covers STF too;
        the forest's own layer is used here).
      - INF FDRAs are three single-polygon shapefiles 443/460/461.
    """
    g5 = cd / 'fs_r5_fdras_2025.gdb'
    rd = lambda p, l=None: gpd.read_file(p, layer=l) if l else gpd.read_file(p)
    out = [
        ('ANF', rd(g5, 'ANF_FDRA_2025'), lambda r: r['Name'], 'ANF_FDRA_2025'),
        ('KNF', rd(g5, 'KNF_FDRA_2025'), lambda r: r['NAME'], 'KNF_FDRA_2025'),
        ('LNF', rd(g5, 'LNF_FDRA_2025'), lambda r: r['NAME'], 'LNF_FDRA_2025'),
        ('MNF', rd(g5, 'MNF_FDRA_2025'), lambda r: r['zone_'], 'MNF_FDRA_2025'),
        ('SQF', rd(g5, 'SQF_FDRA_2025'), lambda r: r['name'], 'SQF_FDRA_2025'),
        ('SRF', rd(g5, 'SRF_FDRA_2025'), lambda r: r['FDRA_Name'], 'SRF_FDRA_2025'),
        ('TNF', rd(g5, 'TNF_FDRA_2025'), lambda r: r['FDRA_Name'], 'TNF_FDRA_2025'),
        ('LPF', rd(cd / 'lpf_fdra_2025_gdb.gdb', 'LPF_FDRA'), lambda r: r['AreaNumber'], 'LPF_FDRA'),
        ('SHF', rd(cd / 'r05_shf.gdb', 'FDRA'), lambda r: r['fdra'], 'r05_shf FDRA'),
        ('SNF', rd(cd / 'fdra_gdb.gdb', 'FireDangerRateAreas'), lambda r: r['FDR_AREA'], 'SNF FireDangerRateAreas'),
        ('BDF', rd(cd / 'bdf_fdra_2021' / 'BDF_FDRA_2021.shp'), lambda r: r['NAME'], 'BDF_FDRA_2021'),
        ('CNF', rd(cd / 'cnf_fdra_2022' / 'CNF_FDRA_2022.shp'), lambda r: r['NAME'], 'CNF_FDRA_2022'),
        ('STF', rd(cd / '2022' / 'STF2022FDRAs_all_Elev.shp'), lambda r: r['NAME'], 'STF2022FDRAs_all_Elev'),
    ]
    inf = pd.concat([rd(cd / n / f'{n}.shp').to_crs(4326).assign(_n=n) for n in ('443', '460', '461')], ignore_index=True)
    out.append(('INF', gpd.GeoDataFrame(inf, crs=4326), lambda r: r['_n'], 'INF 443/460/461'))
    enf = rd(enf_geojson)
    out.append(('ENF', enf[enf['FDRA_Name'] != 'LTBMU'], lambda r: r['FDRA_Name'], 'FDRA_Layers (national)'))
    out.append(('TMU', enf[enf['FDRA_Name'] == 'LTBMU'], lambda r: 'LTBMU', 'FDRA_Layers (national)'))
    # Modoc: MDF_FDRA_2025 in the package is a DPA layer, not FDRAs. Plumas: only a
    # single 2018 polygon. Both come from FDRA_Layers (national) instead.
    if mdf_pnf_geojson:
        mp = rd(mdf_pnf_geojson)
        for code in ('MDF', 'PNF'):
            out.append((code, mp[mp['forest_code'] == code], lambda r: r['FDRA_Name'], 'FDRA_Layers (national)'))
    return out


def build(cd: Path, enf_geojson: Path, forests_geojson: Path, mdf_pnf_geojson: Path | None = None) -> gpd.GeoDataFrame:
    nf = gpd.read_file(forests_geojson).to_crs(3310)
    nf['geometry'] = nf.geometry.make_valid().buffer(0)
    parts = []
    for code, g, name_fn, label in sources(cd, enf_geojson, mdf_pnf_geojson):
        g = g.to_crs(3310)
        g['geometry'] = g.geometry.make_valid().buffer(0)
        names = [_s(name_fn(r)) or '?' for _, r in g.iterrows()]
        df = gpd.GeoDataFrame({'forest_code': code, 'fdra_name': names, 'source_layer': label},
                              geometry=g.geometry.values, crs=3310)
        df = df.dissolve(by=['forest_code', 'fdra_name', 'source_layer'], as_index=False)   # merge same-name pieces
        boundary = nf.loc[nf['forestname'] == FOREST[code], 'geometry'].union_all()
        df['geometry'] = df.geometry.intersection(boundary)
        df = df[~df.geometry.is_empty & (df.geometry.area > 1e5)]                          # drop slivers < 10 ha
        df['forest'] = FOREST[code]
        parts.append(df)
    out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=3310)
    out['fdra_id'] = out['forest_code'] + '-' + out['fdra_name']
    out['acres'] = (out.geometry.area / 4046.856).round(0)
    out = out[['fdra_id', 'forest', 'forest_code', 'fdra_name', 'source_layer', 'acres', 'geometry']]
    return out.to_crs(4326)


if __name__ == '__main__':
    cd, enf, nf, mp = map(Path, sys.argv[1:5])
    dest = Path(sys.argv[5]) if len(sys.argv) > 5 else Path(__file__).with_name('fdra') / 'R5_FDRAs_clipped.geojson'
    dest.parent.mkdir(parents=True, exist_ok=True)
    gdf = build(cd, enf, nf, mp)
    gdf.to_file(dest, driver='GeoJSON')
    print(dest, len(gdf), 'FDRAs')
    print(gdf.groupby('forest_code').size().to_dict())
