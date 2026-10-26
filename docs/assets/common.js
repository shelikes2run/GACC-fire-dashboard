// Shared helpers for the FDRA season-tracking site. Area settings: assets/area.js (window.AREA).
const AREA = window.AREA || { repo: 'shelikes2run/GACC-fire-dashboard', pal: { enabled: true, matrix: 'R5' } };
// On GitHub Pages the address says where the repo lives (owner.github.io/repo/), so the data links follow a transfer.
if (/\.github\.io$/.test(location.hostname) && location.pathname.split('/')[1])
  AREA.repo = location.hostname.split('.')[0] + '/' + location.pathname.split('/')[1];
const PAL_ON = !!(AREA.pal && AREA.pal.enabled);
const DATA = (new URLSearchParams(location.search).get('data')) ||
  'https://raw.githubusercontent.com/' + AREA.repo + '/site-data/';
function palLink() { return PAL_ON && AREA.pal.url ? `PAL: <a href="${AREA.pal.url}" target="_blank">${AREA.pal.label || 'PAL report'}</a>.` : ''; }
const SFDI_CLASSES = [
  { max: 60, label: 'Low', color: '#2e7d32' },
  { max: 80, label: 'Moderate', color: '#c0ca33' },
  { max: 90, label: 'High', color: '#f9a825' },
  { max: 97, label: 'Very High', color: '#ef6c00' },
  { max: 101, label: 'Severe', color: '#c62828' },
];
function sfdiClass(v) {
  if (v === null || v === undefined || isNaN(v)) return null;
  return SFDI_CLASSES.find(c => v <= c.max) || SFDI_CLASSES[SFDI_CLASSES.length - 1];
}
async function getJSON(path) {
  const r = await fetch(DATA + path + '?t=' + Math.floor(Date.now() / 300000), { cache: 'no-store' });
  if (!r.ok) throw new Error(path + ' → ' + r.status);
  return r.json();
}
function fmt(v, d = 0) { return v === null || v === undefined || isNaN(v) ? '–' : Number(v).toFixed(d); }
function ord(v) {
  if (v === null || v === undefined || isNaN(v)) return '–';
  const n = Math.round(v), s = ['th', 'st', 'nd', 'rd'], m = n % 100;
  return n + (s[(m - 20) % 10] || s[m] || s[0]);
}
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
if (new URLSearchParams(location.search).get('embed') === '1') document.documentElement.classList.add('embed-root');
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.area-id').forEach(e => { e.textContent = AREA.id || e.textContent; });
  if (AREA.org) document.querySelectorAll('.area-org').forEach(e => { e.textContent = AREA.org; });
  if (document.documentElement.classList.contains('embed-root')) document.body.classList.add('embed');
});
