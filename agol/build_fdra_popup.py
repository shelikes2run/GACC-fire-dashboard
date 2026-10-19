"""Build the Arcade popup for the web map's FDRA layer: FDOP breakpoints vs 90th / 97th.

  python agol/build_fdra_popup.py p9097.json > agol/fdra_popup.arcade

p9097.json: {'fm': {fdra_id: fuel model}, 'q': {fdra_id: {'erc': [p90, p97], 'bi': [p90, p97]}}}
(90th / 97th of 2016-2025 at the FDRA's FDOP stations, from the site-data normals).
Breakpoints come from docs/data/fdop_start.json (the current FDOPs) plus the few
2026-sheet values that are not in an FDOP file yet.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
start = json.loads((ROOT / 'docs' / 'data' / 'fdop_start.json').read_text())
p = json.loads(Path(sys.argv[1]).read_text())

SHEET = {   # 2026 Forest Thresholds sheet (no FDOP file loaded yet)
    'TNF-350': [['Custom (sheet; index assumed BI)', 'bi', 'Y', [22, 30], ['Normal', 'Elevated', 'Critical']]],
    'TNF-354': [['Custom (sheet; index assumed BI)', 'bi', 'Y', [22, 30], ['Normal', 'Elevated', 'Critical']]],
    'TNF-380': [['Custom (sheet; index assumed BI)', 'bi', 'Y', [22, 30], ['Normal', 'Elevated', 'Critical']]],
}

D = {}
for fid, fm in p['fm'].items():
    e = {'fm': fm, 'p': {k: [round(v[0], 1), round(v[1], 1)] for k, v in (p['q'].get(fid) or {}).items()}, 't': [], 'src': ''}
    s = next((v for k, v in start.items() if k.upper() == fid.upper()), None)
    if s:
        tools = s.get('tools') or [{'label': 'FDOP ' + i.upper(), 'idx': i, 'fm': s.get('fm', 'Y'), 'breaks': b,
                                    'classes': s.get('classes') or [str(n + 1) for n in range(len(b) + 1)]}
                                   for i, b in (s.get('breaks') or {}).items()]
        e['t'] = [[t['label'], t['idx'], t.get('fm', s.get('fm', 'Y')), t['breaks'],
                   (t.get('classes') or s.get('classes') or [str(n + 1) for n in range(len(t['breaks']) + 1)])] for t in tools]
        e['src'] = s.get('source', 'current FDOP')
    elif fid in SHEET:
        e['t'], e['src'] = SHEET[fid], '2026 Forest Thresholds sheet'
    D[fid] = e

print('// FDRA popup: FDOP breakpoints vs 90th / 97th (built by agol/build_fdra_popup.py — edit there, not here)')
print('var D = ' + json.dumps(D, ensure_ascii=False, separators=(',', ':')) + ';')
print(r'''
var id = $feature.fdra_id;
var E = {'fm': $feature.fuel_model, 'p': {}, 't': [], 'src': ''};
if (HasKey(D, id)) { E = D[id]; }
var flds = ['stationId','StationName','ERC','BI'];
var raws = FeatureSetByPortalItem(Portal('https://nifc.maps.arcgis.com'), '8c98d879e6c74d07ac6236c0bfa114a3', 0, flds, false);
var ids = Split(DefaultValue($feature.station_ids, ''), ';', -1, true);
var live = null; var n = 0; var how = 'FDOP stations';
if (Count(ids) > 0) { live = Filter(raws, 'stationId IN (' + Concatenate(ids, ',') + ')'); n = Count(live); }
if (n == 0) { live = Intersects(raws, $feature); n = Count(live); how = 'live RAWS inside the FDRA'; }
var NOW = {'erc': null, 'bi': null};
if (n > 0) { NOW = {'erc': Round(Average(live, 'ERC'), 1), 'bi': Round(Average(live, 'BI'), 1)}; }

function bclass(v, bps, labels) {
  if (IsEmpty(v)) { return '' }
  var c = labels[0];
  for (var i in bps) { if (v > bps[i] && i + 1 < Count(labels)) { c = labels[i + 1] } }   // breakpoint = top of its class
  return c;
}
function chip(c, rank, total) {
  if (c == '') { return '–' }
  var col = '#00a865';
  if (total > 1 && rank >= total - 1) { col = '#ff2d55' } else if (total > 1 && rank >= Floor(total / 2)) { col = '#ffcc00' }
  return '<span style="padding:1px 6px;border-radius:3px;background:' + col + ';color:#111">' + c + '</span>';
}
function pp(k, fm) {
  if (fm != E.fm || !HasKey(E.p, k)) { return '–' }
  return E.p[k][0] + ' / ' + E.p[k][1];
}
var rows = '';
var tools = E.t;
if (Count(tools) == 0) {
  tools = [['90th / 97th percentile (no FDOP breakpoints loaded)', 'erc', E.fm, [], []],
           ['90th / 97th percentile (no FDOP breakpoints loaded)', 'bi', E.fm, [], []]];
}
for (var i in tools) {
  var t = tools[i]; var k = t[1]; var fm = t[2]; var b = t[3]; var cls = t[4];
  var v = null; if (HasKey(NOW, k)) { v = NOW[k]; }
  var c = ''; var rank = 0; var total = Count(cls);
  if (fm == 'Y' && !IsEmpty(v)) {
    if (Count(b) > 0) {
      c = bclass(v, b, cls);
      rank = IndexOf(cls, c);
    } else if (HasKey(E.p, k) && E.fm == 'Y') {
      var q = E.p[k];
      c = When(v >= q[1], '≥ 97th', v >= q[0], '≥ 90th', 'below 90th');
      rank = When(v >= q[1], 2, v >= q[0], 1, 0); total = 3;
    }
  }
  var top = '';
  if (Count(b) > 0 && fm == E.fm && HasKey(E.p, k)) {
    var tb = b[Count(b) - 1];
    top = When(tb >= E.p[k][1], 'top break ≥ 97th', tb >= E.p[k][0], 'top break 90th–97th', 'top break < 90th');
  }
  rows += '<tr><td>' + t[0] + '</td><td>' + Upper(k) + '-' + fm + '</td><td><b>' + IIf(Count(b) > 0, Concatenate(b, ' / '), '–') + '</b></td>'
       + '<td>' + pp(k, fm) + '</td><td>' + IIf(fm == 'Y', DefaultValue(v, '–'), 'n/a') + '</td><td>' + chip(c, rank, total) + '</td></tr>'
       + IIf(top == '', '', '<tr><td colspan="6" style="font-size:10px;color:#666;padding-bottom:4px">' + top + '</td></tr>');
}
var names = [];
if (n > 0) { for (var s in live) { Push(names, s.StationName) } }
var notY = false;
for (var i in tools) { if (tools[i][2] != 'Y') { notY = true } }
return { type: 'text', text:
  '<table style="width:100%;font-size:12px;border-collapse:collapse"><tr><th align="left">Decision tool</th><th>Index</th><th>FDOP breakpoints</th><th>90th / 97th</th><th>Live</th><th>Level</th></tr>'
  + rows + '</table>'
  + '<p style="font-size:11px">' + IIf(E.src == '', 'No FDOP breakpoints loaded for this FDRA.', 'Breakpoints: ' + E.src + '.')
  + ' 90th / 97th: all 2016–2025 days at the FDRA\'s FDOP stations, fuel model ' + E.fm + '.'
  + IIf(notY, ' Live values are fuel model Y only (the live RAWS layer), so non-Y tools show breakpoints without a live level — the season-tracking charts track every fuel model.', '')
  + '<br>Live: ' + n + ' ' + how + IIf(n > 0, ': ' + Concatenate(names, ', '), '') + '</p>' };''')
