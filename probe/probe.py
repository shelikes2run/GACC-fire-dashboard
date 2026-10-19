import requests, json
out = {}
def q(name, url, params):
    try:
        r = requests.get(url, params=params, timeout=90)
        out[name] = r.text[:3000]
    except Exception as e:
        out[name] = 'ERR ' + str(e)
FOD = 'https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_FireOccurrence6thEdition_01/MapServer'
q('fod_svc', FOD, {'f': 'json'})
q('fod_l0', FOD + '/0', {'f': 'json'})
q('fod_l0_q', FOD + '/0/query', {'where': "STATE='CA'", 'returnCountOnly': 'true', 'f': 'json'})
q('fod_l0_sample', FOD + '/0/query', {'where': "STATE='CA'", 'outFields': '*', 'resultRecordCount': 2, 'returnGeometry': 'true', 'outSR': 4326, 'f': 'json'})
W = 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Incident_Locations/FeatureServer/0'
q('wfigs', W, {'f': 'json'})
q('wfigs_cnt', W + '/query', {'where': "POOState='US-CA' AND FireDiscoveryDateTime >= DATE '2023-01-01' AND FireDiscoveryDateTime < DATE '2024-01-01'", 'returnCountOnly': 'true', 'f': 'json'})
q('wfigs_s', W + '/query', {'where': "POOState='US-CA'", 'outFields': 'IncidentName,FireDiscoveryDateTime,IncidentSize,FireCause,IncidentTypeCategory,POOProtectingAgency,FinalAcres,DiscoveryAcres', 'resultRecordCount': 2, 'f': 'json'})
P = 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/InterAgencyFirePerimeterHistory_All_Years_View/FeatureServer/0'
q('perim', P, {'f': 'json'})
q('perim_cnt', P + '/query', {'where': "FIRE_YEAR_INT=2020", 'geometry': '-124.5,32.5,-114,42', 'geometryType': 'esriGeometryEnvelope', 'inSR': 4326, 'returnCountOnly': 'true', 'f': 'json'})
F = 'https://fems.fs2c.usda.gov/api/ext-climatology/download-nfdr-daily-summary/'
r = requests.get(F, params=dict(dataset='observation', startDate='2006-01-01', endDate='2006-12-31', dataFormat='csv', stationIds='40910,40916,45438', fuelModels='Y'), timeout=120)
out['fems2006'] = f'{r.status_code} lines={len(r.text.splitlines())} {r.text[:300]}'
r = requests.get(F, params=dict(dataset='observation', startDate='2000-01-01', endDate='2000-12-31', dataFormat='csv', stationIds='40910', fuelModels='Y'), timeout=120)
out['fems2000'] = f'{r.status_code} lines={len(r.text.splitlines())}'
json.dump(out, open('probe_out.json', 'w'), indent=1)
