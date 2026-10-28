// GACC Fire Weather pages (successor of the Streamlit dashboard). Data: wx-data branch (site/build_wx.py).
const WX = (new URLSearchParams(location.search).get('wxdata')) || 'https://raw.githubusercontent.com/' + AREA.repo + '/wx-data/';
const Q = new URLSearchParams(location.search);
const EMBED = Q.get('embed') === '1';
const LVL = { 'Dormant': '#8d6e63', 'Green-up': '#43a047', 'Normal': '#2e7d32', 'Elevated': '#f9c80e', 'High': '#ff7a00', 'Critical': '#e0115f', 'No data': '#6b7280' };
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
  const [lo, hi] = moist ? ['p3', 'p10'] : ['p90', 'p97'];   // shade the Elevated-to-Critical band, as the Streamlit trend did
  if (b && b[lo] != null && b[hi] != null) lay.shapes.push({ type: 'rect', xref: 'paper', x0: 0, x1: 1, y0: b[lo], y1: b[hi], fillcolor: 'rgba(255,90,40,0.10)', line: { width: 0 }, layer: 'below' });
  if (b && b.mean !== undefined) add(b.mean, 'Mean', '#00d4b4', 'dot');
  for (const [k, t, c, d] of lines(b, moist)) add(b[k], t, c, d);
  return lay;
}
// Approximate percentile of value v within the PSA's 2005–2024 climatology (interpolated between the stored points)
function pctRank(v, b) {
  if (v === null || v === undefined || !b) return null;
  const pts = [[3, b.p3], [5, b.p5], [10, b.p10], [20, b.p20], [80, b.p80], [90, b.p90], [95, b.p95], [97, b.p97]].filter(([, y]) => y !== null && y !== undefined);
  if (pts.length < 2) return null;
  if (v <= pts[0][1]) return pts[0][1] === pts[pts.length - 1][1] ? 50 : pts[0][0] * (v < pts[0][1] ? 0.5 : 1);
  if (v >= pts[pts.length - 1][1]) return v > pts[pts.length - 1][1] ? 99 : 97;
  for (let i = 1; i < pts.length; i++) { const [p0, y0] = pts[i - 1], [p1, y1] = pts[i];
    if (v <= y1) return y1 === y0 ? p1 : p0 + (p1 - p0) * (v - y0) / (y1 - y0); }
  return null;
}
const pctTxt = p => p === null ? '–' : p >= 99 ? '>97th' : p < 3 ? '<3rd' : `~${Math.round(p)}th`;
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
function fcstShade(lay, today) {   // shaded forecast region (right of today), as in the Streamlit 7-day chart
  lay.shapes = lay.shapes || [];
  lay.shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: today, x1: shiftDays(today, 8), y0: 0, y1: 1, fillcolor: 'rgba(255,122,51,0.06)', line: { width: 0 }, layer: 'below' });
  lay.annotations = (lay.annotations || []).concat([{ xref: 'x', yref: 'paper', x: today, xanchor: 'left', y: 1, yanchor: 'bottom', text: 'FORECAST ▸', showarrow: false, font: { size: 10, color: '#a5abb2' } }]);
  return lay;
}
function shiftDays(iso, n) { const d = new Date(iso + 'T12:00'); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }
function fieldSelect(sel, fields, keys, cur) {
  sel.innerHTML = keys.map(k => `<option value="${k}"${k === cur ? ' selected' : ''}>${esc(fields[k].short)} — ${esc(fields[k].label)}</option>`).join('');
}
function linkQ(page, params) { const u = new URLSearchParams(params); if (EMBED) u.set('embed', '1'); return page + '?' + u.toString(); }

// ── what each index is (shown under the charts for the index picked) ──
// ERC, BI, IC, SC, KBDI: NWCG PMS 437, "NFDRS System Inputs and Outputs"; fuel moistures and GSI: NFDRS 2016.
const NWCG_URL = 'https://www.nwcg.gov/publications/pms437/fire-danger/nfdrs-system-inputs-and-outputs';
const IDX_DEF = {
  erc: ['Energy Release Component (ERC)', 'The available energy (BTU per square foot) in the flaming front at the head of a fire. A cumulative, build-up index: the 1000-hour fuel moisture is a primary input and wind is not, so it changes slowly from day to day. Open-ended and relative (an ERC of 24 is twice the potential heat release of 12). Best NFDRS measure of seasonal drying and drought; used for planning 24–72 hours out and for preparedness and staffing.'],
  bi: ['Burning Index (BI)', 'How much fire behavior adds to the effort of containing a fire, built from the Spread Component and ERC. Roughly flame length in feet × 10, open-ended. Represents the near upper limit expected in the rating area (worst fuel, weather and topography); containment difficulty rises more than twice as fast as BI. Responds to wind, so it moves more day to day than ERC.'],
  ic: ['Ignition Component (IC)', 'The probability (0–100%) that a firebrand landing in receptive fuel starts a fire that needs suppression action. 100 means every firebrand would start an actionable fire; 0 means none would. Driven mostly by fine (1-hour) fuel moisture and temperature, plus spread potential.'],
  sc: ['Spread Component (SC)', 'The forward rate of spread of a head fire, numerically equal to the theoretical rate of spread in feet per minute. Open-ended and highly variable from day to day because it is driven by wind, slope and fine fuel moisture.'],
  fm1: ['1-hour dead fuel moisture', 'Moisture content (% of dry weight) of dead fuels under ¼ inch in diameter: grass, needles, small twigs and the surface litter. Responds within an hour or so to temperature, humidity and sun, so it swings through the day. Lower = easier ignition; the main driver of Ignition Component.'],
  fm10: ['10-hour dead fuel moisture', 'Moisture content of dead fuels ¼ to 1 inch in diameter. Responds over hours to about a day, tracking the day-to-day weather. A key input to fire spread; lower = more available fine fuel.'],
  fm100: ['100-hour dead fuel moisture', 'Moisture content of dead fuels 1 to 3 inches in diameter. Responds over several days, so it reflects the multi-day trend of temperature, humidity and precipitation rather than single-day swings. Lower values mean drying over the past week or so.'],
  fm1000: ['1000-hour dead fuel moisture', 'Moisture content of dead fuels 3 to 8 inches in diameter (large logs). Responds over weeks, so it reflects seasonal drying and drought; a primary input to ERC. Use as a stand-alone drought indicator only after checking local historical fire-weather data for critical levels.'],
  herb: ['Herbaceous live fuel moisture', 'Modeled moisture content of live grasses and forbs. In NFDRS 2016 it follows the Growing Season Index: it rises during green-up and falls to about 30% (fully cured) when plants are dormant. Cured herbaceous fuel behaves like dead fuel.'],
  woody: ['Woody live fuel moisture', 'Modeled moisture content of live shrub and tree foliage and small stems. In NFDRS 2016 it follows the Growing Season Index, ranging from about 60% (dormant) up to about 200% (full green-up). Lower values mean more of the live fuel can burn.'],
  kbdi: ['Keetch-Byram Drought Index (KBDI)', 'Not an NFDRS output itself, but often shown with it: a stand-alone index of seasonal drought. Estimates the rain, in hundredths of an inch, needed to bring the top 8 inches of soil back to saturation: 0 = saturated, 800 (8 inches) = maximum. Rising values mean more vegetation stress, live plants adding to the dead fuel load, and more duff and litter becoming available to burn.'],
  gsi: ['Growing Season Index (GSI)', 'A 0–1 index of how favorable conditions are for plant growth, from minimum temperature, vapor pressure deficit and day length, averaged over 21 days. In NFDRS 2016 it drives the herbaceous and woody live fuel moistures: green-up begins at 0.5 and live fuels are fully green at 1. It normally sits at or near 0 in fall and winter, especially in dry, offshore-wind periods, meaning live fuels are dormant or cured. Shown here as Dormant (below 0.5) or Green-up (0.5 and up).'],
};
function defBox(k) {
  const d = IDX_DEF[k]; if (!d) return '';
  return `<div style="margin-top:12px;padding:10px 12px;border-left:4px solid #7fb3ff;background:rgba(127,179,255,.08);border-radius:6px;font-size:13px;line-height:1.5">
    <b>${esc(d[0])}</b><br>${esc(d[1])}
    <div class="small muted" style="margin-top:4px">Source: <a href="${NWCG_URL}" target="_blank" rel="noopener">NWCG PMS 437, NFDRS System Inputs and Outputs</a>${['fm1', 'fm10', 'fm100', 'fm1000', 'herb', 'woody', 'gsi'].includes(k) ? ' and the NFDRS 2016 documentation' : ''}.</div></div>`;
}
