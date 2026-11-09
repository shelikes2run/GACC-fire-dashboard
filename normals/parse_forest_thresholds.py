"""
parse_forest_thresholds.py — turn 2026_Forest_Thresholds.xlsx (two side-by-side
forest tables) into one tidy table: one row per forest × FDRA.

Columns: forest_code, fdra_sheet (as written), fdra_key (normalised id used to
match the FDRA polygons), station_ids (6-digit FEMS ids, ';'-joined),
unresolved (names/ids that could not be turned into a station id),
fuel_model, sl_dl_index, standard_90_97, custom_thresholds, notes

    python normals/parse_forest_thresholds.py <xlsx> <out.csv> [stations.psv]
"""
import re
import sys

import openpyxl
import pandas as pd

FORESTS = {'ANF', 'BDF', 'CNF', 'ENF', 'INF', 'KNF', 'LNF', 'LPF', 'MDF', 'MNF', 'PNF',
           'SHF', 'SNF', 'SRF', 'STF', 'SQF', 'TNF', 'TMU'}

# Station names written without ids → FEMS station id (from the CA NFDRS 3.0 RAWS list)
NAME_IDS = {
    'jarbo gap': 41214, 'saddleback': 41304, 'pike county': 41701, 'quincy rd': 40910,
    'cashman': 40916, 'pierce': 40915, 'denten creek': 40921, 'laufman': 40709,
    'coyote': 40917,
}


def _ids(text: str):
    """Pull 5–6 digit station ids out of free text; map known names; return (ids, unresolved)."""
    if not text:
        return [], []
    t = str(text)
    ids, bad = [], []
    for tok in re.findall(r'\d{5,7}', t):
        n = int(tok)
        if n > 999999:            # e.g. '0411018' typo for 041018
            bad.append(tok)
            n = int(tok[:2] + tok[3:]) if len(tok) == 7 else n
        ids.append(n)
    if not ids:                   # names only (e.g. PNF)
        for part in re.split(r'[,/;]', t):
            k = part.strip().lower()
            if not k:
                continue
            if k in NAME_IDS:
                ids.append(NAME_IDS[k])
            else:
                bad.append(part.strip())
    return list(dict.fromkeys(ids)), bad


def _fm(cells):
    return ''.join(k for k, v in zip('VWXYZ', cells) if v not in (None, ''))


def _key(forest, name):
    s = str(name).strip()
    s = re.sub(r'^FDRA[\s\-]*', '', s, flags=re.I).strip()
    if s == '':
        return f'{forest}-ALL'                 # one station set for the whole forest (LNF)
    if s.lower().startswith('enf-pending'):
        return 'ENF-PENDING-HIGH-ELEV'
    m = re.match(r'(\d{3}(?:-\d{3}|IS)?)', s)   # 514IS, 112-115
    if m:
        return f'{forest}-{m.group(1)}'
    return f'{forest}-{s}'


def _season(name):
    s = str(name).lower()
    return 'peak' if '(peak)' in s else ('non-peak' if 'non-peak' in s else '')


def parse(xlsx):
    ws = openpyxl.load_workbook(xlsx, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(min_row=3, values_only=True))
    out = []
    for off in (0, 11):           # left table cols A–K, right table cols L–V
        forest = None
        for r in rows:
            c = list(r[off:off + 11]) + [None] * 11
            name = c[0]
            if name is None or str(name).strip() == '':
                if c[9] and out and out[-1]['forest_code'] == forest:   # trailing note
                    out[-1]['notes'] = (out[-1]['notes'] + ' ' + str(c[9])).strip()
                continue
            s = str(name).strip()
            if s.upper() in FORESTS:
                forest = s.upper()
                forest_fm = _fm(c[2:7])
                if c[1]:
                    forest_note = str(c[1])
                continue
            if s.upper() == 'FDRA' and not c[1]:
                continue
            ids, bad = _ids(c[1])
            out.append({
                'forest_code': forest, 'fdra_sheet': s, 'fdra_key': _key(forest, s), 'season': _season(s),
                'station_ids': ';'.join(str(i) for i in ids), 'n_stations': len(ids),
                'unresolved': '; '.join(bad), 'fuel_model': _fm(c[2:7]) or forest_fm,
                'sl_dl_index': (c[7] or ''), 'standard_90_97': (c[8] or ''),
                'custom_thresholds': ' | '.join(str(x) for x in (c[9], c[10]) if x), 'notes': '',
            })
    return pd.DataFrame(out)


if __name__ == '__main__':
    df = parse(sys.argv[1])
    df.to_csv(sys.argv[2], index=False)
    print(df[['forest_code', 'fdra_sheet', 'fdra_key', 'n_stations', 'fuel_model', 'unresolved']].to_string())
