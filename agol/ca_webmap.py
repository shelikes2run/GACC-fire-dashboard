"""
ca_webmap.py — builds the operational layers for "CA Fire Weather Intelligence Map".

Writes agol/ca_webmap_layers.json: the operationalLayers array to paste into the
web map item's data (ArcGIS Online Assistant → View an Item's JSON → Data → edit),
keeping the item's existing baseMap / spatialReference.

Live data: CA NFDRS 3.0 (FEMS), owner oncc_oscc_scripting (refreshed daily).
FDRAs: Kristen's FDRA_View_KA (CAL FIRE FDRA_MASTER_2). FDRA values are rolled up
live in the popup from the RAWS inside each FDRA (Arcade FeatureSet).

    python agol/ca_webmap.py
"""
import json
from pathlib import Path

CA_SVC = 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/CA_NFDRS/FeatureServer'
CA_ITEM = '8c98d879e6c74d07ac6236c0bfa114a3'
FDRA_URL = 'https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/FDRA_View/FeatureServer/0'
FDRA_ITEM = 'd1f695757afe4fdab3e1442534a1125b'
PORTAL = 'https://nifc.maps.arcgis.com'

COLORS = {'Critical': '#ff2d55', 'High': '#ff6b00', 'Elevated': '#ffcc00',
          'Normal': '#00c875', 'No data': '#9aa0b4'}
# (field stem in PSA layer, field stem in RAWS layer, label, danger direction)
INDICES = [
    ('ERC', 'ERC', 'ERC', 'high'),
    ('BI', 'BI', 'BI', 'high'),
    ('FM100Hr', 'FM100Hr', '100-hr FM', 'low'),
    ('FM1000Hr', 'FM1000Hr', '1000-hr FM', 'low'),
    ('KBDI', 'KBDI', 'KBDI', 'high'),
]


def rgba(hex_, a=210):
    h = hex_.lstrip('#')
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [a]


def alert_expr(pct_field, direction):
    if direction == 'high':   # percentile of the index: high = dangerous
        return (f"var p = $feature.{pct_field}; When(IsEmpty(p), 'No data', p >= 97, 'Critical', "
                f"p >= 95, 'High', p >= 90, 'Elevated', 'Normal')")
    # fuel moisture percentile: low = dry = dangerous (mirror of 97/95/90)
    return (f"var p = $feature.{pct_field}; When(IsEmpty(p), 'No data', p <= 3, 'Critical', "
            f"p <= 5, 'High', p <= 10, 'Elevated', 'Normal')")


def legend_labels(direction):
    if direction == 'high':
        return {'Critical': 'Critical (≥ 97th pct)', 'High': 'High (≥ 95th)',
                'Elevated': 'Elevated (≥ 90th)', 'Normal': 'Normal (< 90th)', 'No data': 'No data'}
    return {'Critical': 'Critical (≤ 3rd pct, very dry)', 'High': 'High (≤ 5th)',
            'Elevated': 'Elevated (≤ 10th)', 'Normal': 'Normal (> 10th)', 'No data': 'No data'}


def renderer(expr, title, direction, geom='polygon'):
    def sym(c):
        if geom == 'point':
            return {'type': 'esriSMS', 'style': 'esriSMSCircle', 'color': rgba(c, 255), 'size': 7,
                    'outline': {'type': 'esriSLS', 'style': 'esriSLSSolid', 'color': [30, 30, 30, 255], 'width': 0.7}}
        return {'type': 'esriSFS', 'style': 'esriSFSSolid', 'color': rgba(c),
                'outline': {'type': 'esriSLS', 'style': 'esriSLSSolid', 'color': [40, 40, 40, 220], 'width': 0.8}}
    labels = legend_labels(direction)
    return {'type': 'uniqueValue', 'valueExpression': expr, 'valueExpressionTitle': title,
            'defaultSymbol': sym(COLORS['No data']), 'defaultLabel': 'No data',
            'uniqueValueInfos': [{'value': k, 'label': labels[k], 'symbol': sym(COLORS[k])}
                                 for k in ['Critical', 'High', 'Elevated', 'Normal']]}


def psa_popup():
    rows = ''.join(
        f'<tr><td>{lab}</td><td><b>{{Avg_{f}}}</b></td><td>{{Avg_{f}_Pct}}</td><td>{{Avg_{f}_Trend}}</td>'
        f'<td>{{Avg_{f}_Fcast}}</td><td>{{Avg_{f}_Fcast_Pct}}</td></tr>' for f, _, lab, _ in INDICES)
    html = ('<p><b>{PSANationalCode} — {PSAName}</b><br>{GACCName}</p>'
            '<table style="width:100%;font-size:12px;border-collapse:collapse">'
            '<tr><th align="left">Index</th><th>Today</th><th>Pct</th><th>Trend</th><th>Fcst</th><th>Fcst pct</th></tr>'
            + rows + '</table><p style="font-size:11px">Percentiles from the CA NFDRS 3.0 service (FEMS, fuel model Y). '
            'Fuel moisture: low percentile = drier than normal.</p>')
    return {'title': '{PSANationalCode} {PSAName}',
            'popupElements': [{'type': 'text', 'text': html}], 'showAttachments': False}


def raws_popup():
    rows = ''.join(
        f'<tr><td>{lab}</td><td><b>{{{f}}}</b></td><td>{{{f}_Pct}}</td><td>{{{f}_Trend}}</td>'
        f'<td>{{{f}_Fcast}}</td><td>{{{f}_DOY_Pct_Bin}}</td></tr>' for _, f, lab, _ in INDICES)
    html = ('<p><b>{StationName}</b> ({stationId}) · PSA {PSA} · {Unit}<br>Elev {Elevation} ft · '
            'fuel model {FuelModel} · last rain ≥0.10" {Precip010DaysSince} days ago</p>'
            '<table style="width:100%;font-size:12px"><tr><th align="left">Index</th><th>Today</th><th>Pct</th>'
            '<th>Trend</th><th>Fcst</th><th>For date</th></tr>' + rows + '</table>'
            '<p><a href="{ERC_Chart_URL}" target="_blank">ERC chart</a> · <a href="{BI_Chart_URL}" target="_blank">BI</a> · '
            '<a href="{FM100Hr_Chart_URL}" target="_blank">100-hr</a> · <a href="{FM1000Hr_Chart_URL}" target="_blank">1000-hr</a> · '
            '<a href="{KBDI_Chart_URL}" target="_blank">KBDI</a> · <a href="{MesoWest_URL}" target="_blank">MesoWest</a></p>')
    return {'title': '{StationName} ({stationId})', 'popupElements': [{'type': 'text', 'text': html}],
            'showAttachments': False}


FDRA_ARCADE = r"""
// Live FDRA roll-up: average of the CA NFDRS 3.0 RAWS inside this FDRA
var flds = ['stationId','StationName','ERC','ERC_Pct','BI','BI_Pct','FM100Hr','FM100Hr_Pct',
            'FM1000Hr','FM1000Hr_Pct','KBDI','KBDI_Pct'];
var raws = FeatureSetByPortalItem(Portal('""" + PORTAL + r"""'), '""" + CA_ITEM + r"""', 0, flds, false);
var inside = Intersects(raws, $feature);
var n = Count(inside);
if (n == 0) {
  return { type: 'text', text: '<p>No CA NFDRS 3.0 RAWS inside this FDRA. See the PSA or nearest station.</p>' };
}
function cls(p, dir) {
  if (IsEmpty(p)) { return 'No data' }
  if (dir == 'high') { return When(p >= 97, 'Critical', p >= 95, 'High', p >= 90, 'Elevated', 'Normal') }
  return When(p <= 3, 'Critical', p <= 5, 'High', p <= 10, 'Elevated', 'Normal');
}
var rows = '';
var idx = [['ERC','ERC','high'],['BI','BI','high'],['FM100Hr','100-hr FM','low'],['FM1000Hr','1000-hr FM','low'],['KBDI','KBDI','high']];
for (var i in idx) {
  var f = idx[i][0];
  var v = Round(Average(inside, f), 1);
  var p = Round(Average(inside, f + '_Pct'), 0);
  rows += '<tr><td>' + idx[i][1] + '</td><td><b>' + v + '</b></td><td>' + p + '</td><td>' + cls(p, idx[i][2]) + '</td></tr>';
}
var names = [];
for (var s in inside) { Push(names, s.StationName + ' (' + s.stationId + ')') }
return { type: 'text', text:
  '<table style="width:100%;font-size:12px"><tr><th align="left">Index</th><th>FDRA avg</th><th>Avg pct</th><th>Class</th></tr>'
  + rows + '</table><p style="font-size:11px">' + n + ' RAWS: ' + Concatenate(names, ', ') + '</p>' };
"""


def build():
    layers = []
    # PSA layers, one per index (today), plus ERC forecast; ERC today visible by default
    for i, (f, _, lab, d) in enumerate(INDICES):
        layers.append({
            'id': f'psa_{f.lower()}', 'title': f'PSA – {lab} percentile (today)',
            'url': f'{CA_SVC}/1', 'itemId': CA_ITEM, 'layerType': 'ArcGISFeatureLayer',
            'visibility': i == 0, 'opacity': 0.85,
            'layerDefinition': {'drawingInfo': {
                'renderer': renderer(alert_expr(f'Avg_{f}_Pct', d), f'{lab} alert', d),
                'labelingInfo': [{'labelExpressionInfo': {'expression': '$feature.PSANationalCode'},
                                  'labelPlacement': 'esriServerPolygonPlacementAlwaysHorizontal',
                                  'minScale': 0, 'maxScale': 0,
                                  'symbol': {'type': 'esriTS', 'color': [20, 20, 20, 255], 'haloColor': [255, 255, 255, 255],
                                             'haloSize': 1, 'font': {'family': 'Arial', 'size': 8, 'weight': 'bold'}}}]}},
            'showLabels': True, 'popupInfo': psa_popup()})
    layers.append({
        'id': 'psa_erc_fcast', 'title': 'PSA – ERC percentile (forecast)', 'url': f'{CA_SVC}/1', 'itemId': CA_ITEM,
        'layerType': 'ArcGISFeatureLayer', 'visibility': False, 'opacity': 0.85,
        'layerDefinition': {'drawingInfo': {'renderer': renderer(alert_expr('Avg_ERC_Fcast_Pct', 'high'), 'ERC forecast alert', 'high')}},
        'popupInfo': psa_popup()})
    layers.append({
        'id': 'fdra', 'title': 'FDRAs (CAL FIRE) – click for live roll-up', 'url': FDRA_URL, 'itemId': FDRA_ITEM,
        'layerType': 'ArcGISFeatureLayer', 'visibility': True, 'opacity': 1,
        'layerDefinition': {'drawingInfo': {'renderer': {'type': 'simple', 'symbol': {
            'type': 'esriSFS', 'style': 'esriSFSNull', 'color': [0, 0, 0, 0],
            'outline': {'type': 'esriSLS', 'style': 'esriSLSDash', 'color': [60, 60, 160, 255], 'width': 1.2}}}},
            'minScale': 4000000},
        'popupInfo': {'title': 'FDRA {UNIT}-{FDRA}', 'popupElements': [
            {'type': 'fields'},
            {'type': 'expression', 'expressionInfo': {'title': 'Live FDRA roll-up', 'expression': FDRA_ARCADE,
                                                      'returnType': 'dictionary'}}]}})
    layers.append({
        'id': 'raws', 'title': 'RAWS – ERC percentile (today)', 'url': f'{CA_SVC}/0', 'itemId': CA_ITEM,
        'layerType': 'ArcGISFeatureLayer', 'visibility': True, 'opacity': 1,
        'layerDefinition': {'drawingInfo': {
            'renderer': renderer(alert_expr('ERC_Pct', 'high'), 'Station ERC alert', 'high', geom='point'),
            'labelingInfo': [{'labelExpressionInfo': {'expression': '$feature.StationName'}, 'minScale': 1500000,
                              'symbol': {'type': 'esriTS', 'color': [20, 20, 20, 255], 'haloColor': [255, 255, 255, 255],
                                         'haloSize': 1, 'font': {'family': 'Arial', 'size': 8}}}]}},
        'showLabels': True, 'popupInfo': raws_popup()})
    layers.append({
        'id': 'gacc', 'title': 'CA GACCs', 'url': f'{CA_SVC}/2', 'itemId': CA_ITEM, 'layerType': 'ArcGISFeatureLayer',
        'visibility': True, 'layerDefinition': {
            'drawingInfo': {'renderer': {'type': 'simple', 'symbol': {
                'type': 'esriSFS', 'style': 'esriSFSNull', 'color': [0, 0, 0, 0],
                'outline': {'type': 'esriSLS', 'style': 'esriSLSSolid', 'color': [20, 20, 20, 255], 'width': 2}}}}},
        'popupInfo': None})
    return layers   # listed bottom → top (web map draws index 0 first)


if __name__ == '__main__':
    out = Path(__file__).with_name('ca_webmap_layers.json')
    out.write_text(json.dumps(build(), ensure_ascii=False))
    print(out, out.stat().st_size, 'bytes')
