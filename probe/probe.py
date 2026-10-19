import requests, json, io, zipfile
out = {}
def q(name, url, params, n=2500):
    try:
        r = requests.get(url, params=params, timeout=120); out[name] = r.text[:n]
    except Exception as e:
        out[name] = 'ERR ' + str(e)
C = 'https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/California_Historic_Fire_Perimeters/FeatureServer'
q('cal_svc', C, {'f': 'json'}, 1500)
q('cal_l0_fields', C + '/0', {'f': 'json'}, 6000)
q('cal_cnt2020', C + '/0/query', {'where': 'YEAR_=2020', 'returnCountOnly': 'true', 'f': 'json'})
P = 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/InterAgencyFirePerimeterHistory_All_Years_View/FeatureServer/0'
r = requests.get(P, params={'f': 'json'}, timeout=60).json()
out['perim_fields'] = ','.join(f['name'] for f in r.get('fields', []))
W = 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Incident_Locations/FeatureServer/0'
r = requests.get(W, params={'f': 'json'}, timeout=60).json()
out['wfigs_fields'] = ','.join(f['name'] for f in r.get('fields', []))
q('wfigs_minyear', W + '/query', {'where': "POOState='US-CA' AND IncidentTypeCategory='WF'", 'outStatistics': json.dumps([{'statisticType': 'min', 'onStatisticField': 'FireDiscoveryDateTime', 'outStatisticFieldName': 'mn'}, {'statisticType': 'count', 'onStatisticField': 'OBJECTID', 'outStatisticFieldName': 'n'}]), 'f': 'json'})
for y in (2016, 2019, 2021, 2024):
    q(f'wfigs_wf_{y}', W + '/query', {'where': f"POOState='US-CA' AND IncidentTypeCategory='WF' AND FireDiscoveryDateTime >= DATE '{y}-01-01' AND FireDiscoveryDateTime < DATE '{y+1}-01-01'", 'returnCountOnly': 'true', 'f': 'json'})
# FPA FOD 6th edition (RDS-2013-0009.6)
for u in ['https://www.fs.usda.gov/rds/archive/products/RDS-2013-0009.6/RDS-2013-0009.6_Data_Format2_GDB.zip',
          'https://www.fs.usda.gov/rds/archive/products/RDS-2013-0009.6/RDS-2013-0009.6_Data_Format1_SQLITE.zip',
          'https://www.fs.usda.gov/rds/archive/products/RDS-2013-0009.6/RDS-2013-0009.6_Data_Format3_CSV.zip',
          'https://www.fs.usda.gov/rds/archive/catalog/RDS-2013-0009.6']:
    try:
        h = requests.head(u, timeout=60, allow_redirects=True)
        out['fod ' + u.rsplit('/', 1)[-1]] = f"{h.status_code} {h.headers.get('content-length')} {h.headers.get('content-type')}"
    except Exception as e:
        out['fod ' + u] = 'ERR ' + str(e)
json.dump(out, open('probe_out.json', 'w'), indent=1)
