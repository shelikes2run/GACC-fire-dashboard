// GACC Fire Weather pages (successor of the Streamlit dashboard). Data: wx-data branch (site/build_wx.py).
const WX = (new URLSearchParams(location.search).get('wxdata')) || 'https://raw.githubusercontent.com/' + AREA.repo + '/wx-data/';
const Q = new URLSearchParams(location.search);
const EMBED = Q.get('embed') === '1';
const LVL = { 'Normal': '#2e7d32', 'Elevated': '#f9c80e', 'High': '#ff7a00', 'Critical': '#e0115f', 'No data': '#6b7280' };
const LVL_ORDER = ['Critical', 'High', 'Elevated', 'Normal', 'No data'];
const HI = [['p80', '80th', '#7fb3ff', 'dot'], ['p90', '90th', '#f9c80e', 'dash'], ['p95', '95th', '#ff7a00', 'dash'], ['p97', '97th', '#e0115f', 'dash']];
const LO = [['p20', '20th (dry)', '#7fb3ff', 'dot'], ['p10', '10th (very dry)', '#f9c80e', 'dash'], ['p5', '5th (critically dry)', '#ff7a00', 'dash'], ['p3', '3rd (extremely dry)', '#e0115f', 'dash']];
async function wxJSON(p) {
  const r = await fetch(WX + p + '?t=' + Math.floor(Date.now() / 300000), { cache: 'no-store' });
  if (!r.ok) throw new Error(p + ' → ' + r.status);
  return r.json();
}
const $ = id => document.getElementById(id);
const nf = (v, d) => v === null || v === undefined || isNaN(v) ? '–' : Number(v).toFixed(d !== undefined ? d : Math.abs(v) >= 100 ? 0 : 1);
function chip(l) { const c = LVL[l] || LVL['No data']; return `<span class="badge" style="background:${c};color:${l === 'Elevated' ? '#111' : '#fff'}">${esc(l || 'No data')}</span>`; }
function lines(b, moist) { return (moist ? LO : HI).filter(([k]) => b && b[k] !== undefined && b[k] !== null); }
function base(lay) {
  return { paper_bgcolor: '#2a2d31', plot_bgcolor: '#2a2d31', font: { color: '#e8eaed', size: 12 }, margin: { l: 50, r: 110, t: 40, b: 50 },
    xaxis: { gridcolor: '#3a3f45' }, yaxis: { gridcolor: '#3a3f45' }, legend: { orientation: 'h', y: -0.18 }, ...lay };
}
function hl(lay, b, moist) {   // climatology reference lines (mean + 80/90/95/97 or 20/10/5/3)
  lay.shapes = lay.shapes || []; lay.annotations = lay.annotations || [];
  const add = (y, txt, col, dash) => {
    lay.shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: y, y1: y, line: { color: col, width: 1.4, dash } });
    lay.annotations.push({ xref: 'paper', x: 1.01, xanchor: 'left', y, text: `${txt}: ${nf(y)}`, showarrow: false, font: { color: col, size: 10 } });
  };
  if (b && b.mean !== undefined) add(b.mean, 'Mean', '#00d4b4', 'dot');
  for (const [k, t, c, d] of lines(b, moist)) add(b[k], t, c, d);
  return lay;
}
function plot(id, tr, lay) { Plotly.newPlot(id, tr, base(lay), { responsive: true, displaylogo: false }); }
function dayLabel(d, today) {
  const t = new Date(today + 'T12:00'), x = new Date(d + 'T12:00'), k = Math.round((x - t) / 864e5);
  return k === 0 ? 'Today' : k === -1 ? 'Yesterday' : k === 1 ? 'Tomorrow' : (k < 0 ? `D${k}` : `D+${k}`) + ' ' + x.toLocaleDateString('en-US', { weekday: 'short', month: 'numeric', day: 'numeric' });
}
// series for one PSA and field: observed (solid) + forecast (dotted)
function seriesTraces(rec, k, name, color, from) {
  const s = rec.series; if (!s) return [];
  const xo = [], yo = [], xf = [], yf = [];
  s.dates.forEach((d, i) => { if (from && d < from) return; const v = s[k][i]; if (v === null) return;
    if (s.type[i] === 'O') { xo.push(d); yo.push(v); } else { xf.push(d); yf.push(v); } });
  if (xo.length && xf.length) { xf.unshift(xo[xo.length - 1]); yf.unshift(yo[yo.length - 1]); }
  return [{ x: xo, y: yo, name: name + ' observed', mode: 'lines+markers', line: { color, width: 2.2 }, marker: { size: 5 } },
          { x: xf, y: yf, name: name + ' forecast', mode: 'lines+markers', line: { color, width: 2, dash: 'dot' }, marker: { size: 5, symbol: 'circle-open' } }];
}
function shiftDays(iso, n) { const d = new Date(iso + 'T12:00'); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }
function fieldSelect(sel, fields, keys, cur) {
  sel.innerHTML = keys.map(k => `<option value="${k}"${k === cur ? ' selected' : ''}>${esc(fields[k].short)} — ${esc(fields[k].label)}</option>`).join('');
}
function linkQ(page, params) { const u = new URLSearchParams(params); if (EMBED) u.set('embed', '1'); return page + '?' + u.toString(); }
