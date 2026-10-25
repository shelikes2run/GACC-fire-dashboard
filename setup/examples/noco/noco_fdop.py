"""Northern Colorado (NoCo) 2026 FDOP (v1.2, 2026-06-06) as setup inputs: area settings, FDRA names, SIG stations and
thresholds. Read by setup_area.ipynb when EXAMPLE = 'noco'. Breakpoints are the top of each class (FDOP lower limits - 0.1)."""
AREA = {'id': 'NOCO', 'name': 'Northern Colorado', 'repo': 'shelikes2run/NOCO-fire-danger', 'states': ['CO', 'WY', 'NE'],
        'timezone': 'America/Denver', 'title': 'Northern Colorado Fire Danger Rating Areas', 'short_title': 'NoCo FDRA Fire Danger',
        'subtitle': 'Northern Colorado (NoCo) · 2026 FDOP · NFDRS 2016 fuel models', 'org': 'Northern Colorado Fire Danger',
        'crs': 5070}
SHAPES = 'NOCO_FDRAs.zip'
NAME_FIELD = 'FDRA'
NAMES = {'Juniper': ('JU', 'Juniper (JU)'), 'Brush': ('BR', 'Brush (BR)'), 'Divide': ('DD', 'Divide (DD)'),
         'Front Range': ('FR', 'Front Range (FR)'), 'Plains': ('PN', 'Plains (PN)')}
FOREST = 'Northern Colorado (NoCo)'
PREFIX = 'NOCO'

# SIG stations (FDOP Fire Danger Decision Matrix). The notebook checks each id against the RAWS list and FEMS.
STATIONS = [
    ('NOCO-JU', 50104, 'Lodore', 'X'), ('NOCO-JU', 50108, 'Calico', 'X'), ('NOCO-JU', 51402, 'Pinto', 'X'), ('NOCO-JU', 51407, 'Dragon Road', 'X'),
    ('NOCO-BR', 50106, 'Great Divide', 'Z'), ('NOCO-BR', 482011, 'Cow Creek', 'Z'), ('NOCO-BR', 51608, 'Hangman', 'Z'),
    ('NOCO-DD', 50207, 'Dry Lake', 'Z'), ('NOCO-DD', 50304, 'Willow Creek', 'Z'), ('NOCO-DD', 50305, 'Independence Mountain', 'Z'),
    ('NOCO-DD', 50408, 'Keyser Ridge', 'Z'),
    ('NOCO-FR', 50508, 'Redstone', 'Z'), ('NOCO-FR', 53105, 'Carpenter Peak', 'Z'), ('NOCO-FR', 50604, 'Sugarloaf', 'Z'),
    ('NOCO-PN', 50510, 'Buckeye', 'Z'), ('NOCO-PN', 50901, 'North Sterling', 'Z'), ('NOCO-PN', 52301, 'Arsenal', 'Z'),
]

ADJ = ['Low', 'Moderate', 'High', 'Very High', 'Extreme']
LV = ['1', '2', '3', '4', '5']
MATRIX = [[1, 1, 1, 2, 3], [1, 2, 2, 3, 3], [1, 2, 3, 3, 4], [2, 3, 3, 4, 4], [3, 3, 4, 4, 5]]   # rows ERC class, columns BI class
SRC = 'Northern Colorado 2026 FDOP workbook v1.2 (2026-06-06), Fire Danger Decision Matrix and FDRA analysis tabs'
TMAX = {'var': 'tmax', 'op': '<', 'value': 57, 'adjust': -1, 'window': 'F1'}
F100 = {'var': 'f100', 'op': '>', 'value': 14, 'adjust': -1, 'window': 'F1'}
GSI = {'var': 'gsi', 'op': '>', 'value': 0.3, 'adjust': -1}


def mx(label, fm, erc, bi, classes, window, adjust=None, order=0):
    t = {'type': 'matrix', 'label': label, 'rows': {'idx': 'erc', 'fm': fm, 'breaks': erc}, 'cols': {'idx': 'bi', 'fm': fm, 'breaks': bi},
         'matrix': MATRIX, 'classes': classes, 'window': window, 'order': order}
    if adjust:
        t['adjust'] = adjust
    return t


def one(label, idx, fm, breaks, classes, window='', adjust=None, order=0):
    t = {'label': label, 'idx': idx, 'fm': fm, 'breaks': breaks, 'classes': classes, 'order': order}
    if window:
        t['window'] = window
    if adjust:
        t['adjust'] = adjust
    return t


def entry(fid, fm, st, calib, large, mfd, tools, matrices, notes):
    return {'source': SRC, 'stations': st, 'fm': fm, 'idx': tools[0]['idx'] if tools else 'erc', 'season': ['01-01', '12-31'],
            'calib': calib, 'large': large, 'mfd': mfd, 'tools': tools, 'matrix_tools': matrices, 'notes': notes,
            'breaks': {t['idx']: t['breaks'] for t in reversed(tools)}, 'classes': tools[0]['classes'] if tools else LV}


def start():
    S = {s[0]: [] for s in STATIONS}
    for fid, sid, _, _ in STATIONS:
        S[fid].append(sid)
    d = {}
    # Juniper: BI-X + ERC-X matrix, Tmax < 57 drops one level
    erc, bi = [39.9, 69.9, 83.9, 95.9], [99.9, 174.9, 219.9, 267.9]
    d['NOCO-JU'] = entry('NOCO-JU', 'X', S['NOCO-JU'], [2012, 2022], 20, 8,
        [one('ERC-X class (matrix rows)', 'erc', 'X', erc, LV, order=4), one('BI-X class (matrix columns)', 'bi', 'X', bi, LV, order=5)],
        [mx('Adjective rating & preparedness (ERC-X × BI-X matrix)', 'X', erc, bi, ADJ, 'O1+F1+F2+F3', [TMAX], 1),
         mx('Staffing level (ERC-X × BI-X matrix)', 'X', erc, bi, LV, 'F1', [TMAX], 2),
         mx('Response level (ERC-X × BI-X matrix)', 'X', erc, bi, LV, 'F1', [TMAX], 3)],
        'NoCo 2026 FDOP: SIG Lodore, Calico, Pinto, Dragon Road (fuel model X), 2012-2022; large fire 20 ac, multi-fire day 8+. '
        'Adjective / preparedness: 4-day average O1+F1+F2+F3; staffing and response: F1. ERC-X rows x BI-X columns 5x5 matrix; '
        'one level lower when Tmax (F1) < 57 F. ERC-X classes 0-39.9 / 40-69.9 / 70-83.9 / 84-95.9 / 96+ (the Decision Matrix tab '
        'lists High as 70-84.9, overlapping Very High 84-95.9; the analysis tab 70.0-83.9 is used). Climatology 90th/97th: BI-X 258/297, ERC-X 94/100.')
    # Brush: BI-Z + ERC-Z matrix, Tmax
    erc, bi = [24.9, 71.9, 94.9, 107.9], [49.9, 89.9, 111.9, 139.9]
    d['NOCO-BR'] = entry('NOCO-BR', 'Z', S['NOCO-BR'], [2012, 2022], 50, 2,
        [one('ERC-Z class (matrix rows)', 'erc', 'Z', erc, LV, order=4), one('BI-Z class (matrix columns)', 'bi', 'Z', bi, LV, order=5)],
        [mx('Adjective rating & preparedness (ERC-Z × BI-Z matrix)', 'Z', erc, bi, ADJ, 'O1+F1+F2+F3', [TMAX], 1),
         mx('Staffing level (ERC-Z × BI-Z matrix)', 'Z', erc, bi, LV, 'F1', [TMAX], 2),
         mx('Response level (ERC-Z × BI-Z matrix)', 'Z', erc, bi, LV, 'F1', [TMAX], 3)],
        'NoCo 2026 FDOP: SIG Great Divide, Cow Creek (WY), Hangman (fuel model Z), 2012-2022; large fire 50 ac, multi-fire day 2+. '
        'Adjective / preparedness O1+F1+F2+F3; staffing and response F1; ERC-Z x BI-Z matrix; one level lower when Tmax (F1) < 57 F. '
        'ERC-Z classes from the Decision Matrix tab 0-24.9 / 25-71.9 / 72-94.9 / 95-107.9 / 108+ (the BR analysis tab uses 25.0-74.9 / 75.0-94.9). '
        'Climatology 90th/97th: BI-Z 132/155, ERC-Z 102/114.')
    # Divide: adjective & preparedness on ERC-Z alone; staffing & response on the matrix
    erc, bi = [34.9, 74.9, 90.9, 101.9], [34.9, 68.9, 84.9, 98.9]
    d['NOCO-DD'] = entry('NOCO-DD', 'Z', S['NOCO-DD'], [2012, 2022], 5, 3,
        [one('Adjective rating & preparedness (ERC-Z)', 'erc', 'Z', erc, ADJ, 'O1+F1+F2+F3', order=1),
         one('ERC-Z class (matrix rows)', 'erc', 'Z', erc, LV, order=4), one('BI-Z class (matrix columns)', 'bi', 'Z', bi, LV, order=5)],
        [mx('Staffing level (ERC-Z × BI-Z matrix)', 'Z', erc, bi, LV, 'F1', None, 2),
         mx('Response level (ERC-Z × BI-Z matrix)', 'Z', erc, bi, LV, 'F1', None, 3)],
        'NoCo 2026 FDOP: SIG Dry Lake, Willow Creek, Independence Mountain, Keyser Ridge (fuel model Z), 2012-2022; large fire 5 ac, '
        'multi-fire day 3+. Adjective and preparedness on ERC-Z alone (4-day average O1+F1+F2+F3); staffing and response on the ERC-Z x BI-Z '
        'matrix (F1). No additional criteria. Climatology 90th/97th: BI-Z 85/99, ERC-Z 91/102.')
    # Front Range: matrix, 100-hr FM > 14 drops one level
    erc, bi = [49.9, 73.9, 88.9, 99.9], [37.9, 64.9, 80.9, 94.9]
    d['NOCO-FR'] = entry('NOCO-FR', 'Z', S['NOCO-FR'], [2012, 2022], 5, 3,
        [one('ERC-Z class (matrix rows)', 'erc', 'Z', erc, LV, order=4), one('BI-Z class (matrix columns)', 'bi', 'Z', bi, LV, order=5)],
        [mx('Adjective rating & preparedness (ERC-Z × BI-Z matrix)', 'Z', erc, bi, ADJ, 'O1+F1+F2+F3', [F100], 1),
         mx('Staffing level (ERC-Z × BI-Z matrix)', 'Z', erc, bi, LV, 'F1', [F100], 2),
         mx('Response level (ERC-Z × BI-Z matrix)', 'Z', erc, bi, LV, 'F1', [F100], 3)],
        'NoCo 2026 FDOP: SIG Redstone, Carpenter Peak, Sugarloaf (fuel model Z), 2012-2022; large fire 5 ac, multi-fire day 3+. '
        'Adjective / preparedness O1+F1+F2+F3; staffing and response F1 (no more than 3 days of forecast); ERC-Z x BI-Z matrix; '
        'one level lower when the 100-hr fuel moisture (F1) > 14%. Climatology 90th/97th: BI-Z 86/95, ERC-Z 97/107.')
    # Plains: BI-Z alone (1 x 5), GSI > 0.3 drops one level, all on the 4-day average
    bi = [64.9, 86.9, 107.9, 137.9]
    d['NOCO-PN'] = entry('NOCO-PN', 'Z', S['NOCO-PN'], [2017, 2025], 300, 10,
        [one('Adjective rating & preparedness (BI-Z)', 'bi', 'Z', bi, ADJ, 'O1+F1+F2+F3', [GSI], 1),
         one('Staffing level (BI-Z)', 'bi', 'Z', bi, LV, 'F1', [GSI], 2),
         one('Response level (BI-Z)', 'bi', 'Z', bi, LV, 'F1', [GSI], 3)],
        [],
        'NoCo 2026 FDOP: SIG Buckeye, North Sterling, Arsenal (fuel model Z), 2017-2025; large fire 300 ac, multi-fire day 10+. '
        'BI-Z alone (1 x 5) for adjective, preparedness, staffing and response; one level lower when GSI > 0.3 (green-up). '
        'Adjective / preparedness on the 4-day average O1+F1+F2+F3; staffing and response on the single forecast day (F1), as the '
        'workbook calculates them (PN analysis tab, "1-day only"); the Decision Matrix tab lists O1+F3 for Plains staffing. '
        'Climatology 90th/97th: BI-Z 120/140.')
    return d
