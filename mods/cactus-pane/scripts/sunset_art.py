# sunset_art.py
# One-off: render a braille sunset with a saguaro for the cactus-pane empty state.
# Responsibilities:
#   - compute a dot mask per layer (sky dither, sun disc, cactus, ground)
#   - fold dots into braille cells, one colour per cell by layer priority
#   - print an ANSI truecolor preview and the TS array of [text, colour] runs
import math
import sys

W, H = 36, 9          # cells; dots are 2x4 per cell
DW, DH = W * 2, H * 4
HORIZON = 28          # dot row where sky meets ground
SUN = (50, HORIZON, 10)
BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def noise(x, y):
    # Fixed hash in [0, 1): the same art every run, no grid.
    h = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (h ^ (h >> 16)) / 2 ** 32

SKY = ['#4b2a6b', '#6e2f6e', '#9a3468', '#c4405e', '#e05a4f', '#f07f45', '#f9a640']
SUN_C = '#ffd166'
CACTUS_C = '#3f9a5c'
CACTUS_SHADE = '#24603a'
GROUND_C = '#8a5a3c'


def cactus(x, y):
    trunk = 17 <= x <= 22 and 5 <= y
    cap = 18 <= x <= 21 and y == 4
    larm = 10 <= x <= 14 and 13 <= y <= 23
    lcap = 11 <= x <= 13 and y == 12
    lbar = 10 <= x <= 17 and 21 <= y <= 24
    rarm = 25 <= x <= 29 and 9 <= y <= 19
    rcap = 26 <= x <= 28 and y == 8
    rbar = 22 <= x <= 29 and 17 <= y <= 20
    return y < DH and (trunk or cap or larm or lcap or lbar or rarm or rcap or rbar)


# Light comes from the sun on the right: each part fades from lit (right edge)
# to shadow (left edge). Outline dots always draw so the silhouette holds.
PARTS = {
    'trunk': (17, 22, 0.25, 1.0),
    'larm': (10, 14, 0.15, 0.55),
    'lbar': (10, 17, 0.15, 0.55),
    'rarm': (25, 29, 0.5, 0.95),
    'rbar': (22, 29, 0.5, 0.95),
}


def part(x, y):
    if 17 <= x <= 22 and 5 <= y or 18 <= x <= 21 and y == 4:
        return 'trunk'
    if 10 <= x <= 14 and 13 <= y <= 23 or 11 <= x <= 13 and y == 12:
        return 'larm'
    if 10 <= x <= 17 and 21 <= y <= 24:
        return 'lbar'
    if 25 <= x <= 29 and 9 <= y <= 19 or 26 <= x <= 28 and y == 8:
        return 'rarm'
    if 22 <= x <= 29 and 17 <= y <= 20:
        return 'rbar'
    return None


# Interior columns, left (shadow) to right (lit): how many dots of every 4
# rows draw. Vertical stripes keep the shading clean at this size.
COLUMNS = {
    'trunk': {18: 1, 19: 4, 20: 2, 21: 4},
    'larm': {11: 1, 12: 2, 13: 1},
    'lbar': {11: 1, 12: 1, 13: 1, 14: 1, 15: 1, 16: 1},
    'rarm': {26: 2, 27: 4, 28: 3},
    'rbar': {23: 3, 24: 3, 25: 3, 26: 3, 27: 4, 28: 3},
}
STIPPLE = {1: (0,), 2: (0, 2), 3: (0, 1, 2), 4: (0, 1, 2, 3)}


def cactus_dot(x, y):
    """None outside the cactus, else whether this dot draws."""
    if y >= DH or not cactus(x, y):
        return None
    if any(not cactus(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
        return True
    n = COLUMNS[part(x, y)].get(x, 4)
    return (y + x) % 4 in STIPPLE[n]


def sun(x, y):
    cx, cy, r = SUN
    return y < HORIZON and (x - cx) ** 2 + ((y - cy) * 1.0) ** 2 <= r * r


def sky_on(x, y):
    t = y / HORIZON
    density = 0.02 + 0.6 * t ** 2.4
    glow = max(0.0, 1 - math.hypot(x - SUN[0], (y - SUN[1]) * 1.8) / 22)
    density = min(0.9, density + 0.35 * glow)
    return noise(x, y) < density


def ground_on(x, y):
    t = (y - HORIZON) / (DH - HORIZON)
    density = 0.18 - 0.12 * t
    reflect = abs(x - SUN[0]) < 8 - 2 * (y - HORIZON) and y % 2 == 0
    return reflect or y == HORIZON or noise(x + 91, y) < density


DOTS = [(0, 0, 0x01), (0, 1, 0x02), (0, 2, 0x04), (1, 0, 0x08),
        (1, 1, 0x10), (1, 2, 0x20), (0, 3, 0x40), (1, 3, 0x80)]


def cell(cx, cy):
    bits = {'cactus': 0, 'sun': 0, 'sky': 0, 'ground': 0}
    for dx, dy, bit in DOTS:
        x, y = cx * 2 + dx, cy * 4 + dy
        on = cactus_dot(x, y)
        if on is not None:
            if on:
                bits['cactus'] |= bit
            bits['shade'] = bits.get('shade', 0) + (0 if on else 1)
        elif sun(x, y):
            bits['sun'] |= bit
        elif y < HORIZON and sky_on(x, y):
            bits['sky'] |= bit
        elif y >= HORIZON and ground_on(x, y):
            bits['ground'] |= bit
    if bits['cactus'] or bits.get('shade'):
        lit = bin(bits['cactus']).count('1') >= 5
        return chr(0x2800 | bits['cactus']), CACTUS_C if lit else CACTUS_SHADE
    if bits['sun']:
        return chr(0x2800 | bits['sun']), SUN_C
    if bits['sky']:
        return chr(0x2800 | bits['sky']), SKY[min(len(SKY) - 1, cy * len(SKY) // (HORIZON // 4))]
    if bits['ground']:
        x0 = cx * 2
        return chr(0x2800 | bits['ground']), SUN_C if abs(x0 - SUN[0]) < 8 and cy * 4 >= HORIZON else GROUND_C
    return ' ', None


rows = [[cell(cx, cy) for cx in range(W)] for cy in range(H)]


def runs(row):
    out = []
    for ch, col in row:
        if out and out[-1][1] == col:
            out[-1][0] += ch
        else:
            out.append([ch, col])
    out[-1][0] = out[-1][0].rstrip() if out[-1][1] is None else out[-1][0]
    return [r for r in out if r[0]]


if '--ts' in sys.argv:
    print('const DESERT: [string, string | undefined][][] = [')
    for row in rows:
        parts = ', '.join(f"[{r[0]!r}, {('%r' % r[1]) if r[1] else 'undefined'}]" for r in runs(row))
        print(f'  [{parts}],'.replace("'", "'"))
    print(']')
else:
    for row in rows:
        line = ''
        for ch, col in row:
            if col:
                r, g, b = (int(col[i:i + 2], 16) for i in (1, 3, 5))
                line += f'\x1b[38;2;{r};{g};{b}m{ch}\x1b[0m'
            else:
                line += ch
        print(line)
