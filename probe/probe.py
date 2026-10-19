import requests, json, io, zipfile, os, subprocess
out = {}
u = 'https://www.fs.usda.gov/rds/archive/products/RDS-2013-0009.6/RDS-2013-0009.6_Data_Format2_GDB.zip'
with requests.get(u, stream=True, timeout=600) as r:
    with open('fod.zip', 'wb') as f:
        for ch in r.iter_content(1 << 20): f.write(ch)
z = zipfile.ZipFile('fod.zip'); out['zip'] = z.namelist()[:20]; z.extractall('fod')
import pyogrio
gdb = [os.path.join(dp, d) for dp, dn, fn in os.walk('fod') for d in dn if d.endswith('.gdb')][0]
out['layers'] = str(pyogrio.list_layers(gdb))
lyr = [l[0] for l in pyogrio.list_layers(gdb) if 'ire' in l[0]][0]
info = pyogrio.read_info(gdb, layer=lyr); out['fields'] = list(info['fields']); out['n'] = info['features']
df = pyogrio.read_dataframe(gdb, layer=lyr, where="STATE='CA' AND FIRE_YEAR>=2006", read_geometry=False)
out['ca_rows'] = len(df); out['sample'] = df.head(3).astype(str).to_dict('records')
out['by_year'] = df.groupby('FIRE_YEAR').size().to_dict()
C = 'https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/California_Historic_Fire_Perimeters/FeatureServer/0'
r = requests.get(C, params={'f': 'json'}, timeout=60).json()
out['frap_fields'] = [f['name'] for f in r['fields']]; out['frap_max'] = r.get('maxRecordCount')
out['frap_years'] = requests.get(C + '/query', params={'where': 'YEAR_>=2020', 'outStatistics': json.dumps([{'statisticType': 'count', 'onStatisticField': 'OBJECTID', 'outStatisticFieldName': 'n'}]), 'groupByFieldsForStatistics': 'YEAR_', 'f': 'json'}, timeout=60).text[:800]
Y = 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_YearToDate/FeatureServer/0'
r = requests.get(Y, params={'f': 'json'}, timeout=60).json()
out['ytd_fields'] = [f['name'] for f in r.get('fields', [])][:60]; out['ytd_err'] = r.get('error')
F = 'https://fems.fs2c.usda.gov/api/ext-climatology/download-nfdr-daily-summary/'
t = requests.get(F, params=dict(dataset='observation', startDate='2010-07-01', endDate='2010-07-02', dataFormat='csv', stationIds='40910', fuelModels='V,W,X,Y,Z'), timeout=120).text
out['fms'] = sorted(set(l.split(',')[3] for l in t.splitlines()[1:]))
json.dump(out, open('probe_out.json', 'w'), indent=1, default=str)
