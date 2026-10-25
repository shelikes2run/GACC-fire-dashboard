"""Area settings (docs/assets/area.js) for the build scripts. One file drives the pages and the builds."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA_JS = ROOT / 'docs' / 'assets' / 'area.js'
DEFAULTS = {'id': 'CA', 'name': 'California', 'repo': 'shelikes2run/GACC-fire-dashboard', 'states': ['CA'],
            'bounds': [[32.4, -124.6], [42.1, -114.0]], 'timezone': 'America/Los_Angeles', 'crs': 3310,
            'stations_source': 'ca_nfdrs', 'perimeters': 'frap', 'pal': {'enabled': False},
            'raws_layer': 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/PublicView_RAWS/FeatureServer/1'}


def load(path: Path = AREA_JS) -> dict:
    txt = path.read_text() if path.exists() else ''
    m = re.search(r'\{.*\}', re.sub(r'^\s*//.*$', '', txt, flags=re.M), re.S)
    a = json.loads(m.group(0)) if m else {}
    out = {**DEFAULTS, **a}
    owner, name = out['repo'].split('/')
    out.setdefault('site_url', f'https://{owner.lower()}.github.io/{name}/')
    out['raw'] = f'https://raw.githubusercontent.com/{out["repo"]}/'
    return out


def write(area: dict, path: Path = AREA_JS):
    keep = {k: v for k, v in area.items() if k not in ('raw',)}
    path.write_text('// Area settings for this copy of the site. The setup notebook (setup_area.ipynb) writes this file;\n'
                    '// the pages and the build scripts (site/area.py) both read it. Keep it valid JSON inside the braces.\n'
                    'window.AREA = ' + json.dumps(keep, indent=2) + ';\n')


AREA = load()

if __name__ == '__main__':
    print(json.dumps(AREA, indent=1))
