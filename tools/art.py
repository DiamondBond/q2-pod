"""Original raster art the theme files state in numbers, drawn at build time: small vector shapes, antialiased
over sub-rows, written as 8-bit RGBA PNGs. No Apple assets or reference pixels; every shape is drawn here."""
import functools
import math
import operator
import re
import struct
import zlib
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from build import ROOT, need
from ipod import CLASSIC_LIGHT_FONT_SRC, STATE_W, inc

SUB = 8  # sub-rows per pixel; columns are exact within a sub-row


def _arc(p0, rx, ry, phi, large, sweep, p1, steps=48):
    """SVG's endpoint arc as points after p0."""
    c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = c * dx + s * dy, -s * dx + c * dy
    k = x1**2 / rx**2 + y1**2 / ry**2
    if k > 1:
        rx, ry = rx * math.sqrt(k), ry * math.sqrt(k)
    num = max(0, rx**2 * ry**2 - rx**2 * y1**2 - ry**2 * x1**2)
    f = math.sqrt(num / (rx**2 * y1**2 + ry**2 * x1**2)) * (1 if large != sweep else -1)
    cx1, cy1 = f * rx * y1 / ry, -f * ry * x1 / rx
    cx, cy = c * cx1 - s * cy1 + (p0[0] + p1[0]) / 2, s * cx1 + c * cy1 + (p0[1] + p1[1]) / 2
    a0 = math.atan2((y1 - cy1) / ry, (x1 - cx1) / rx)
    a1 = math.atan2((-y1 - cy1) / ry, (-x1 - cx1) / rx)
    d = a1 - a0
    if sweep and d < 0:
        d += 2 * math.pi
    elif not sweep and d > 0:
        d -= 2 * math.pi
    out = []
    for i in range(1, steps + 1):
        a = a0 + d * i / steps
        x, y = rx * math.cos(a), ry * math.sin(a)
        out.append((c * x - s * y + cx, s * x + c * y + cy))
    return out


def path(d):
    """An SVG path's d (M L H V C Q A Z, absolute or relative, an M's further pairs lines) as closed polylines."""
    tokens = re.findall(r'[MLHVCQAZmlhvcqaz]|-?[0-9]*\.?[0-9]+', d)
    polys, pts, i, cmd = [], [], 0, None
    cur = (0.0, 0.0)

    def num():
        nonlocal i
        i += 1
        return float(tokens[i - 1])

    def at(rel):  # the next pair, from the current point in a lower-case command
        x, y = num(), num()
        return (cur[0] + x, cur[1] + y) if rel else (x, y)
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
        cmd = need(cmd, 'SVG path data before its first command')
        rel, op = cmd.islower(), cmd.upper()
        if op == 'Z':
            polys.append(pts)
            cur, pts = pts[0], []
            continue
        if op == 'M':
            cur = at(rel)
            pts = [cur]
            cmd = 'l' if rel else 'L'
        elif op == 'L':
            cur = at(rel)
            pts.append(cur)
        elif op == 'H':
            cur = (num() + (cur[0] if rel else 0), cur[1])
            pts.append(cur)
        elif op == 'V':
            cur = (cur[0], num() + (cur[1] if rel else 0))
            pts.append(cur)
        elif op in 'CQ':
            ctrl = [cur, *(at(rel) for _ in range(3 if op == 'C' else 2))]
            n = len(ctrl) - 1
            for k in range(1, 25):
                t = k / 24
                weights = [math.comb(n, m) * (1 - t)**(n - m) * t**m for m in range(n + 1)]
                pts.append(tuple(sum(w * p[a] for w, p in zip(weights, ctrl)) for a in (0, 1)))
            cur = pts[-1]
        elif op == 'A':
            rx, ry, phi, large, sweep = num(), num(), num(), num(), num()
            end = at(rel)
            pts += _arc(cur, rx, ry, phi, large, sweep, end)
            cur = pts[-1]
    return polys + ([pts] if pts else [])


def stroke(polys, width, closed=True):
    """Polylines' stroke, round joined and capped, as polygons a union fills."""
    r, out = width / 2, []
    circle = lambda x, y: [(x + r * math.cos(a * math.pi / 8), y + r * math.sin(a * math.pi / 8)) for a in range(16)]
    for poly in polys:
        if not closed:
            out.append(circle(*poly[0]))
        for (x0, y0), (x1, y1) in zip(poly, poly[1:] + (poly[:1] if closed else [])):
            n = math.hypot(x1 - x0, y1 - y0)
            if n:
                nx, ny = (y1 - y0) / n * r, (x0 - x1) / n * r
                out.append([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)])
            out.append(circle(x1, y1))
    return out


def coverage(polys, box):
    """Each pixel's covered fraction of box (x, y, w, h), the polygons' union, each polygon even-odd."""
    x0, y0, w, h = box
    cov = [0.0] * (w * h)
    # each polygon's rows and edges, once: a sub-row reads only the polygons it crosses (a stroke is hundreds of small ones)
    edged = [(min(y for _, y in poly), max(y for _, y in poly), list(zip(poly, poly[1:] + poly[:1]))) for poly in polys]
    for sub in range(h * SUB):
        y = y0 + (sub + 0.5) / SUB
        spans = []
        for top, foot, edges in edged:
            if top <= y < foot:
                xs = sorted(ax + (y - ay) * (bx - ax) / (by - ay) for (ax, ay), (bx, by) in edges if (ay <= y) != (by <= y))
                spans += zip(xs[::2], xs[1::2])
        spans.sort()
        row, end = sub // SUB * w, None
        for a, b in spans:
            if end is not None and a < end:
                a = end
            if end is None or b > end:
                end = b
            a, b = max(a - x0, 0), min(b - x0, w)
            if a >= b:  # inside the union so far
                continue
            first, last = int(a), math.ceil(b) - 1  # the span's end pixels, in part; each pixel between takes 1 / SUB
            cov[row + first] += (min(b, first + 1) - a) / SUB
            if last > first:
                cov[row + last] += (b - last) / SUB
                cov[row + first + 1:row + last] = [c + 1 / SUB for c in cov[row + first + 1:row + last]]
    return cov


def gradient(stops, y0, y1):
    """A y -> 0xRRGGBB function: stops (pos %, 0xRRGGBB) from y0 to y1, as an SVG linearGradient's."""
    def at(y):
        p = max(stops[0][0], min(100, (y - y0) * 100 / (y1 - y0)))  # before the first stop, its colour
        for (pa, ca), (pb, cb) in zip(stops, stops[1:]):
            if p <= pb:
                t = (p - pa) / (pb - pa)
                return sum(round((ca >> s & 255) + ((cb >> s & 255) - (ca >> s & 255)) * t) << s for s in (16, 8, 0))
        return stops[-1][1]
    return at


def laid(w, h, layers):
    """RGBA bytes: layers (coverage per pixel, paint(x, y) -> (0xRRGGBB, alpha 0 to 1)) source-over, straight alpha."""
    px = [(0.0, 0.0, 0.0, 0.0)] * (w * h)
    for cov, paint in layers:
        for i, c in enumerate(cov):
            if c:
                rgb, a = paint(i % w + 0.5, i // w + 0.5)
                a *= min(c, 1)
                if not a:
                    continue
                r, g, b, d = px[i]
                out = a + d * (1 - a)
                if not out:  # a soft layer's clear pixel, on nothing
                    continue
                px[i] = (*((v * d * (1 - a) + (rgb >> s & 255) * a) / out for v, s in ((r, 16), (g, 8), (b, 0))), out)
    return b''.join(bytes((round(r), round(g), round(b), round(a * 255))) for r, g, b, a in px)


def compose(box, layers):
    """box's RGBA bytes: layers (polygons, paint(x, y) -> (0xRRGGBB, alpha 0 to 1)[, clip polygons]) source-over,
    straight alpha."""
    x0, y0, w, h = box
    def layer(polys, paint, *clip):
        cov = coverage(polys, box)
        if clip:
            cov = [a * b for a, b in zip(cov, coverage(clip[0], box))]
        return cov, lambda x, y: paint(x0 + x, y0 + y)
    return laid(w, h, [layer(*l) for l in layers])


def png(w, h, rgba):
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data))
    rows = b''.join(b'\0' + rgba[y * 4 * w:(y + 1) * 4 * w] for y in range(h))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b'')


# Screen coordinates, the bar's rows and columns; each image's box is where the payload draws it.
BOLT = 'M301.67 6 298.56 11.24 300.85 11.24 300.2 15.16 303.64 9.76 301.35 9.76 302.49 6Z'
PLUG = 'M295.45 8.78h2.78v1.23H295.45ZM295.45 10.99h2.78v1.23H295.45ZM298.07 7.47h3.52a3.03 3.03 0 0 1 0 6.05h-3.52ZM303.64 9.93h4.09v1.23h-4.09Z'
BOLT_BOX = (290, 5, 24, 11)  # the battery's inside, the set's batt_w - 2 x batt_h - 2, in a frame of its own: classic_light_battery draws it at the inside's top-left
def note(svg, rgb):
    """The note's RGBA bytes: its drawing's shape (note.svg), flat in rgb."""
    shape = path(need(re.search(r'id="shape" d="([^"]*)"', svg), 'Missing shape')[1])
    return compose(NOTE_BOX, [(shape, lambda x, y: (rgb, 1))])


SORT = 'M0 0H16V2H0ZM0 5H11V7H0ZM0 10H6V12H0Z'
SORT_BOX = (0, 0, 16, 12)  # Songs' Sort, white as stock's glyphs: Light Mode flips it to the ink
# Home's pane (coverflow.c): original drawings in the note's coordinates. Each but the note is fitted into a 92 px box
# centred on PANE_CENTRE, the note's own place standing for its size; all share one fill and stroke (icon).
# The volume bar's two ends (volume.c vol_paint), where an iPod classic's are: a speaker, and one with its
# waves, the iPod bar's height; white as SORT, Light Mode flips them to the ink. The waves end within the cone's
# height, so the box's rows hold them.
SPEAKER = 'M0 4.3H3L7.5 0.9V12.1L3 8.7H0Z'
SPEAKER_BOX, WAVES_BOX = (0, 0, 8, 13), (0, 0, 18, 13)


def wave(r, cx=7, cy=6.5, half=5.6):  # pragma: no mutate block
    """An arc of radius r about the cone's tip, 96 degrees, or as much of it as keeps within half above and below."""
    dy = min(r * math.sin(math.radians(48)), half)
    dx = math.sqrt(r * r - dy * dy)
    return f'M{cx + dx:.2f} {cy - dy:.2f}A{r} {r} 0 0 1 {cx + dx:.2f} {cy + dy:.2f}'


WAVES = [wave(r) for r in (3.2, 6.6, 10)]
PANE_ICONS = {
    'note': 'M254 82.5 317 71.5V156A16 12.5 -12 1 1 308.5 145.5V101L262 109.5V165A17 12.5 -12 1 1 254 153.5Z',
    'folder': 'M230 92q0-6 6-6h24l8 9h43q6 0 6 6v60q0 6-6 6h-75q-6 0-6-6Z',
    'stack': 'M246 94h60v60h-60ZM228 104l14-4v48l-14-4ZM324 104l-14-4v48l14-4Z',
    'game': 'M251 96h44c16 0 25 15 27 35 2 17-3 28-11 28-7 0-11-6-16-13-3-4-6-6-11-6h-22c-5 0-8 2-11 6-5 7-9 13-16 13-8 0-13-11-11-28 2-20 11-35 27-35Z'
            'M243 109v9h-9v8h9v9h8v-9h9v-8h-9v-9ZM296 108a6 6 0 1 0 .01 0ZM284 120a6 6 0 1 0 .01 0Z',
    'wave': 'M273 113a11 11 0 1 0 .01 0ZM293.1 105.9A27 27 0 0 1 293.1 142.1L287.9 137.4A20 20 0 0 0 287.9 110.6Z'
            'M304.2 95.9A42 42 0 0 1 304.2 152.1L299.0 147.4A35 35 0 0 0 299.0 100.6ZM252.9 142.1A27 27 0 0 1 252.9 105.9L258.1 110.6A20 20 0 0 0 258.1 137.4Z'
            'M241.8 152.1A42 42 0 0 1 241.8 95.9L247.0 100.6A35 35 0 0 0 247.0 147.4Z',
    'gear': 'M313.7 140.8L309.6 148.4L296.3 147.3L291.3 151.4L289.8 164.7L281.6 167.2L273.0 157.0L266.6 156.4L256.2 164.7L248.6 160.6L249.7 147.3'
            'L245.6 142.3L232.3 140.8L229.8 132.6L240.0 124.0L240.6 117.6L232.3 107.2L236.4 99.6L249.7 100.7L254.7 96.6L256.2 83.3L264.4 80.8L273.0 91.0'
            'L279.4 91.6L289.8 83.3L297.4 87.4L296.3 100.7L300.4 105.7L313.7 107.2L316.2 115.4L306.0 124.0L305.4 130.4ZM273 108a16 16 0 1 0 .01 0Z'}
PANE_CENTRE, PANE_FIT = (278, 124), 92
ICON_BOX = (230, 76, 96, 96)  # the icons' image in the drawing's coordinates: home.pane.icon_x, icon_y place it
PANE_INK = {'': 0xffffff, '_l': 0x1c1c1e}  # the pane's marks: white on the dark half's pane, the flat pages' ink on the light one's
CHEVRON = 'M2.9 3 8.4 8.5 2.9 14'
CHEVRON_STROKE = 3.2
CHEVRON_BOX = (0, 0, 12, 16)  # the row's chevron (navigation.c paint_chevrons, paint_into)
def icon(d, fit, rgb):
    """A pane icon's RGBA bytes: its subpaths even-odd, flat in rgb."""
    polys = path(d)
    xs, ys = [p[0] for poly in polys for p in poly], [p[1] for poly in polys for p in poly]
    k = min(PANE_FIT / (max(xs) - min(xs)), PANE_FIT / (max(ys) - min(ys))) if fit else 1
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    place = (lambda p: (PANE_CENTRE[0] + k * (p[0] - cx), PANE_CENTRE[1] + k * (p[1] - cy))) if fit else (lambda p: p)
    placed = [[place(p) for p in poly] for poly in polys]
    # one even-odd polygon: each subpath joined from the first's start and back, those seams crossed twice
    whole = [q for poly in placed for q in (*poly, poly[0], placed[0][0])]
    return compose(ICON_BOX if fit else NOTE_BOX, [([whole], lambda x, y: (rgb, 1))])


NOTE_BOX = (222, 66, 100, 115)  # the drawing's viewBox
# Internet Radio's cover under Classic (playing.station, #204's generic cover's family), an original drawing on a 320 px
# square, drawn at the size it fills: its rows' gradient, a light band across its top, and a mast over its soft shadow.
# The mast's gradient and the shadow are stated at 160 px.
STATION_BAND = 'M0 0H320V64L240 80 0 120Z'
STATION_MAST = ('M96 86a90 90 0 0 0 0 110l18-14a66 66 0 0 1 0-82ZM224 86a90 90 0 0 1 0 110l-18-14a66 66 0 0 0 0-82Z'
                'M126 108a50 50 0 0 0 0 66l16-13a28 28 0 0 1 0-40ZM194 108a50 50 0 0 1 0 66l-16-13a28 28 0 0 0 0-40Z'
                'M160 118a23 23 0 1 1-.1 0ZM150 170h20l28 100h-76Z')
STATION_MAST_Y = (19, 134)  # the mast's gradient's ends, in the image's rows
STATION_SHADOW = (1.5, 2.5)  # the shadow: rows down, and its blur's standard deviation in px
@functools.cache
def station(stops, mast_stops, band_a, shadow_a, size):
    """The station cover's RGBA bytes, size px square."""
    scale = size / 160
    placed = lambda d: [[(x * scale / 2, y * scale / 2) for x, y in poly] for poly in path(d)]
    box = (0, 0, size, size)
    mast, down, sd, reach = placed(STATION_MAST), STATION_SHADOW[0] * scale, STATION_SHADOW[1] * scale, round(8 * scale)
    held = coverage([[(x, y + down) for x, y in poly] for poly in mast], box)
    kernel = [math.exp(-(k * k) / (2 * sd * sd)) for k in range(-reach, reach + 1)]
    total = sum(kernel)
    at = lambda v, x, y: v[max(0, min(size - 1, y)) * size + max(0, min(size - 1, x))]
    across = [sum(w * at(held, x + k - reach, y) for k, w in enumerate(kernel)) / total for y in range(size) for x in range(size)]
    shadow = [sum(w * at(across, x, y + k - reach) for k, w in enumerate(kernel)) / total for y in range(size) for x in range(size)]
    whole = [[(0, 0), (size, 0), (size, size), (0, size)]]
    fill, ink = gradient(stops, 0, size), gradient(mast_stops, *(y * scale for y in STATION_MAST_Y))
    return compose(box, [(whole, lambda x, y: (fill(y), 1)),
                         (placed(STATION_BAND), lambda x, y: (0xffffff, band_a / 255)),
                         (whole, lambda x, y: (0, shadow[int(y) * size + int(x)] * shadow_a / 255)),
                         (mast, lambda x, y: (ink(y), 1))])
STATE = {'play': 'M270.5 4.5 282.5 11.5 270.5 18.5Z', 'pause': 'M270.5 4.5H275V18.5H270.5ZM278 4.5H282.5V18.5H278Z'}
STATE_BOX = (266, 0, STATE_W, 22)  # the frame the state art is drawn in, on the bar's rows; the art itself is position-free
STATE_Y = (4, 19)  # the fill's and edge's first and last rows


# The volume's and the slider pages' speakers, their boxes the image; drawn on the bar and page in these colours.
SPEAKER = 'M0 4.5h3.5L9 .5v13L3.5 9.5H0Z'
SPEAKER_ARCS = ('M12 4.5a3.5 3.5 0 0 1 0 5', 'M14.5 2.5a7 7 0 0 1 0 9', 'M17 .8a10 10 0 0 1 0 12.4')
SPEAKER_INKS = {'l': 0x393c39, 'd': 0xc6c3c6, 'w': 0xffffff}
def speaker(loud, rgb):
    """The speaker, with its three arcs when loud."""
    w = 22 if loud else 12
    arcs = [q for d in SPEAKER_ARCS for q in stroke(path(d), 1.5, closed=False)] if loud else []
    return png(w, 14, compose((0, 0, w, 14), [(path(SPEAKER) + arcs, lambda x, y: (rgb, 1))]))


# The soft shadow of the rating panel's box, as CSS's box-shadow draws it: name, the box's w, h and corner radius, the
# shadow's blur, its drop and alpha. The image reaches blur + 2 past the shadow's box on every side and is clear under
# the box itself.
SHADOWS = {'rate_shadow': (304, 110, 12, 6, 2, 0x33)}
BLACK = 0
@functools.cache
def classic_light_font():
    """The theme face's source, opened once a build."""
    return TTFont(CLASSIC_LIGHT_FONT_SRC, lazy=True)
# Classic's glyphs, one family: solid shapes and lines with round ends, each thing drawn once. Quick Settings' page
# (quick_settings.c quick_page) paints each 54 px round button, and its glyph over it in the button's ink: QS_INK, white,
# or _l, dark, off in the light half and on a bright accent (Graphite's silver). Own drawings; stock's image names (the
# demo's own strings) decide which button, and QS_LIT (stock.h, qs_lit) which are on.
def circle(cx, cy, r):
    return f'M{cx - r} {cy}A{r} {r} 0 1 1 {cx + r} {cy}A{r} {r} 0 1 1 {cx - r} {cy}Z'
def rounded_path(x, y, w, h, r):
    return (f'M{x + r} {y}H{x + w - r}A{r} {r} 0 0 1 {x + w} {y + r}V{y + h - r}A{r} {r} 0 0 1 {x + w - r} {y + h}'
            f'H{x + r}A{r} {r} 0 0 1 {x} {y + h - r}V{y + r}A{r} {r} 0 0 1 {x + r} {y}Z')
def rounded(w, h, x, y, bw, bh, r):
    """A rounded box's coverage of a w x h image, 0 to 1 per pixel."""
    return [min(c, 1) for c in coverage(path(rounded_path(x, y, bw, bh, r)), (0, 0, w, h))]
def pane_glyph(name, size):
    """One of Home's pane icons, the same drawing, its larger side size px, about 0, 0."""
    polys = path(PANE_ICONS[name])
    xs, ys = [x for poly in polys for x, _ in poly], [y for poly in polys for _, y in poly]
    cx, cy, k = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, size / max(max(xs) - min(xs), max(ys) - min(ys))
    return ''.join('M' + 'L'.join(f'{(x - cx) * k:.2f} {(y - cy) * k:.2f}' for x, y in poly) + 'Z' for poly in polys)
# A glyph about 0, 0: fill, shapes, a shape's later subpaths its holes; line, open paths stroked w wide (QS_WEIGHT
# without one) with round ends; dots, filled discs (x, y, r); faint, lines at QS_FAINT of the ink.
QS_WEIGHT, QS_FAINT, QS_DIM, QS_BOX = 2.6, .3, .45, 54
BARS = ('M-7.5 9V4', 'M0 9V-2.5', 'M7.5 9V-9')
# Now Playing's play modes: two arrows to the right; a loop of two, turning
NP_HEADS = ('M8.5 -10.2 13.5 -6 8.5 -1.8Z', 'M8.5 1.8 13.5 6 8.5 10.2Z')
NP_LOOP = ('M-11 -1V-2.5A3.5 3.5 0 0 1 -7.5 -6H9', 'M11 1V2.5A3.5 3.5 0 0 1 7.5 6H-9')
NP_TURNS = ('M8.5 -10.2 13.5 -6 8.5 -1.8Z', 'M-8.5 1.8 -13.5 6 -8.5 10.2Z')
QS_GLYPHS: dict[str, dict] = {
    'wifi': dict(line=('M-11.6 -4.3a18 18 0 0 1 23.2 0', 'M-6.4 1.4a10 10 0 0 1 12.8 0'), dots=((0, 8.4, 2.5),), w=2.9),
    'bt': dict(line=('M-5.6 -5.8 5.6 5.8 0 11.4V-11.4L5.6 -5.8-5.6 5.8',), w=2.3),
    'lock': dict(fill=(rounded_path(-8.5, -1.5, 17, 13, 3.4),), line=('M-5 -2v-4.2a5 5 0 0 1 10 0v4.2',)),
    # stock's three USB modes, each its own: storage a stick, DAC a USB-C port, audio the trident
    'stick': dict(fill=(rounded_path(-6.5, -4.5, 13, 16.5, 3.2), rounded_path(-4, -12, 8, 6, 1.4))),
    'usbc': dict(fill=(rounded_path(-12, -5.5, 24, 11, 5.5) + rounded_path(-6.5, -1.4, 13, 2.8, 1.4),)),
    'usb': dict(fill=('M0 -13.6 -3.9 -7.6H3.9Z', rounded_path(4.3, -10.4, 4.6, 4.6, .8)),
                line=('M0 10V-8.4', 'M0 6 -6.6 1.2V-3.2', 'M0 2.4 6.6 -2.4V-6'), dots=((-6.6, -4.4, 2.5), (0, 10.4, 3)), w=2.3),
    'sl': dict(line=('M-8 -11V11', 'M0 -11V11', 'M8 -11V11'), dots=((-8, 4, 3.5), (0, -4.5, 3.5), (8, 5.5, 3.5)), w=2.3),
    'gear': dict(fill=(pane_glyph('gear', 27),)),  # Home's Settings gear
    # gain, three bars: all of them high, the first alone low; the output, headphones, its label saying which
    'gain': dict(line=BARS, w=3.6), 'gain_low': dict(line=BARS[:1], faint=BARS[1:], w=3.6),
    'phones': dict(fill=(rounded_path(-11.2, 1.5, 5.4, 9.5, 2.2), rounded_path(5.8, 1.5, 5.4, 9.5, 2.2)), line=('M-9 3.5v-3a9 9 0 0 1 18 0v3',), w=2.4),
    'sun': dict(dots=((0, 0, 4.2),), w=2,
                line=tuple(f'M{7.2 * math.cos(a * math.pi / 4):.2f} {7.2 * math.sin(a * math.pi / 4):.2f}L{10 * math.cos(a * math.pi / 4):.2f} {10 * math.sin(a * math.pi / 4):.2f}' for a in range(8))),
    'note': dict(fill=(pane_glyph('note', 28),)),  # Home's note
    # Now Playing's marks (navigation.c np_marks): More, and the play modes: in order, shuffled, repeating, repeating one
    'more': dict(dots=((-9, 0, 2.6), (0, 0, 2.6), (9, 0, 2.6))),
    'order': dict(line=('M-12 -6H9', 'M-12 6H9'), fill=NP_HEADS, w=2.3),
    'shuffle': dict(line=('M-12 -6H-7L5 6H9', 'M-12 6H-7L5 -6H9'), fill=NP_HEADS, w=2.3),
    'repeat': dict(line=NP_LOOP, fill=NP_TURNS, w=2.3),
    'repeat1': dict(line=NP_LOOP, fill=(*NP_TURNS, 'M-0.3 -3.4H1.5V3.4H-0.5V-1.3L-2 -0.7V-2.4Z'), w=2.3),
}
QS_INK = {'': 0xffffff, '_l': 0x1c1c1e}
# Stock's name: glyph, on, the glyph's opacity (disabled: dimmed).
QS_BUTTONS = {
    'wifi': ('wifi', 0, 1), 'wifiopen': ('wifi', 1, 1), 'bt': ('bt', 0, 1), 'btopen': ('bt', 1, 1),
    'keylock': ('lock', 0, 1), 'keylockopen': ('lock', 1, 1),
    'lowgain': ('gain_low', 0, 1), 'lowgaindisable': ('gain_low', 0, QS_DIM),
    'highgain': ('gain', 1, 1), 'highgaindisable': ('gain', 0, QS_DIM),
    'lo': ('phones', 1, 1), 'po': ('phones', 0, 1), 'sa': ('phones', 0, 1),
    'usbstorage': ('stick', 0, 1), 'usbaudio': ('usb', 1, 1), 'usbdac': ('usbc', 1, 1),
    'playset': ('sl', 0, 1), 'sysset': ('gear', 0, 1),
}
# The brightness bar's suns (quick_scrub): the small one on the fill and the large one past it, name: px, scale; the
# large one's quiet inks, on the bar's rest in the light and dark half.
QS_SUNS = {'dim': (24, .62), 'bright': (30, .95)}
QS_QUIET = {'_ql': 0x6e6e73, '_qd': 0x98989d}
# The message screens' mark (classic_pages.c msg_paint): a glyph at MSG_SCALE on a MSG_BOX px square, in the half's ink.
MSG_BOX, MSG_SCALE = 84, 2.8
MSG_INK = {'l': 0x1c1c1e, 'd': 0xffffff}
# Now Playing's marks: a glyph on an NP_BOX px square in the half's ink; More, pressed, in its quiet grey.
NP_BOX, NP_MARKS = 32, ('more', 'order', 'shuffle', 'repeat', 'repeat1')
NP_QUIET = {'l': 0x6e6e73, 'd': 0x98989d}
# Set Time's face (clock.c time_paint): a flat disc in the half's resting grey, its numerals quiet. The hands are the payload's.
CLOCK_PX = 110
CLOCK_FACE = {'l': (0xe9e9ec, 0x6e6e73), 'd': (0x2c2c2e, 0x98989d)}
def blurred(cov, w, h, sigma):
    """cov under a Gaussian of sigma, its edge values carried on past the image."""
    r = math.ceil(3 * sigma)
    k = [math.exp(-i * i / (2 * sigma * sigma)) for i in range(-r, r + 1)]
    k = [v / sum(k) for v in k]
    def line(px):  # a row or a column, its end values carried on r past it: no tap's index is clamped
        px = [px[0]] * r + px + [px[-1]] * r
        return [sum(map(operator.mul, k, px[i:i + len(k)])) for i in range(len(px) - 2 * r)]
    across = [v for y in range(h) for v in line(cov[y * w:(y + 1) * w])]
    down = [line(across[x::w]) for x in range(w)]
    return [down[x][y] for y in range(h) for x in range(w)]
def inked(w, h, layers):
    """RGBA bytes of layers (coverage, alpha 0 to 255, grey), the first on top."""
    out = bytearray()
    for i in range(w * h):
        a = g = 0.0
        for cov, alpha, grey in layers:
            x = cov[i] * alpha / 255 * (1 - a)
            g, a = g + grey * x, a + x
        v = round(a * 255) and round(g / a)
        out += bytes((v, v, v, round(a * 255)))
    return bytes(out)
def outside(cov, box):
    return [c * (1 - b) for c, b in zip(cov, box)]
@functools.lru_cache(maxsize=None)
def shadow(bw, bh, r, blur, drop, alpha):
    """box-shadow: 0 drop blur black at alpha; the image's first row is the shadow's less blur + 2."""
    pad = blur + 2
    w, h = bw + 2 * pad, bh + 2 * pad
    box = rounded(w, h, pad, pad - drop, bw, bh, r)
    soft = blurred(rounded(w, h, pad, pad, bw, bh, r), w, h, blur / 2)
    return png(w, h, inked(w, h, [(outside(soft, box), alpha, BLACK)]))
def holed(d):
    """d's subpaths as one even-odd polygon: each joined from the first's start and back, those seams crossed twice."""
    subs = path(d)
    return [q for poly in subs for q in (*poly, poly[0], subs[0][0])]
def qs_glyph(glyph, ink, size=QS_BOX, k=1):
    """A glyph's layers for compose on a size px square, its 0, 0 the centre, k times its drawing, in ink."""
    g = QS_GLYPHS[glyph]
    at = lambda poly: [(size / 2 + x * k, size / 2 + y * k) for x, y in poly]
    lines = lambda ds: stroke([at(poly) for d in ds for poly in path(d)], g.get('w', QS_WEIGHT) * k, closed=False)
    polys = [at(holed(d)) for d in g.get('fill', ())] + lines(g.get('line', ()))
    polys += [at(poly) for x, y, r in g.get('dots', ()) for poly in path(circle(x, y, r))]
    return [(polys, lambda x, y: (ink, 1)), (lines(g.get('faint', ())), lambda x, y: (ink, QS_FAINT))]
@functools.lru_cache(maxsize=None)
def qs_mark(glyph, opacity, ink, size=QS_BOX, k=1):
    """One glyph, a PNG on clear, at opacity."""
    mark = bytearray(compose((0, 0, size, size), qs_glyph(glyph, ink, size, k)))
    mark[3::4] = bytes(round(a * opacity) for a in mark[3::4])
    return png(size, size, bytes(mark))
def qs_lit():
    """QS_LIT: the names whose button is on, NUL-separated, for navigation.c."""
    return ''.join(f'drop_{n}\\0' for n, (_, lit, _) in QS_BUTTONS.items() if lit)
# The lock screen's hint: the soft shadow (0 1px 2px #00000080) of stock's three marks, drawn at 21 x 7, HINT_PAD past them all round.
HINT_MARK = 'M1.5 1.5L8.2 8L1.5 14.5'
HINT_MARKS, HINT_PAD, HINT_DROP, HINT_SIGMA, HINT_A = (0, 10.5, 21), 4, 1, 1, 0x80
def hint_shadow():
    w, h = 21 + 2 * HINT_PAD, 7 + 2 * HINT_PAD
    marks = [[((x + at) * 0.7 + HINT_PAD, y * 7 / 16 + HINT_PAD + HINT_DROP) for x, y in poly] for at in HINT_MARKS for poly in stroke(path(HINT_MARK), 2.6, closed=False)]
    return png(w, h, inked(w, h, [(blurred([min(v, 1) for v in coverage(marks, (0, 0, w, h))], w, h, HINT_SIGMA), HINT_A, 0)]))


# The info screen's dark face, on a -50..50 box at CLOCK_DARK_PX: its numerals in the theme's own outlines. The hands are the payload's (clock.c paint_clock).
CLOCK_DARK_PX = 96
def outlines(text, size, cx, baseline):
    """text's glyphs centred on cx, in the theme's face at size, as one even-odd polygon per glyph."""
    from fontTools.pens.basePen import BasePen
    font = classic_light_font()
    glyphs, cmap, k = font.getGlyphSet(), font.getBestCmap(), size / font['head'].unitsPerEm
    names = [cmap[ord(c)] for c in text]
    x = cx - sum(glyphs[n].width for n in names) * k / 2

    class Flat(BasePen):
        def __init__(self):
            super().__init__(glyphs)
            self.parts = []

        def _moveTo(self, p):
            self.parts.append([p])

        def _lineTo(self, p):
            self.parts[-1].append(p)

        def _curveToOne(self, a, b, c):
            p0 = self.parts[-1][-1]
            for i in range(1, 9):
                t = i / 8
                self.parts[-1].append(tuple((1 - t)**3 * p0[j] + 3 * (1 - t)**2 * t * a[j] + 3 * (1 - t) * t**2 * b[j] + t**3 * c[j] for j in (0, 1)))
    out = []
    for name in names:
        pen = Flat()
        glyphs[name].draw(pen)
        placed = [[(x + px * k, baseline - py * k) for px, py in part] for part in pen.parts]
        if placed:
            out.append([q for part in placed for q in (*part, part[0], placed[0][0])])
        x += glyphs[name].width * k
    return out


def clock_dark():
    """The dark face's RGBA bytes: disc r 49, its stroke, numerals 1..12 at r 38."""
    size = CLOCK_DARK_PX
    k = size / 100
    place = lambda polys: [[((x + 50) * k, (y + 50) * k) for x, y in poly] for poly in polys]
    circle = [(49 * math.cos(a * math.pi / 60), 49 * math.sin(a * math.pi / 60)) for a in range(120)]
    numerals = []
    for i in range(1, 13):
        a = i * math.pi / 6
        numerals += outlines(str(i), 11, 38 * math.sin(a), 4 - 38 * math.cos(a))
    return compose((0, 0, size, size), [(place([circle]), lambda x, y: (0x0c0f15, 1)),
                                        (stroke(place([circle]), .8 * k), lambda x, y: (0xffffff, 0x66 / 255)),
                                        (place(numerals), lambda x, y: (0xffffff, 1))])


# The T9 keyboard's glyphs and the search field, each in its own box.
KB_GLYPHS = {'kb_del': ((22, 18), (('M8 1h15v16H8L1 9Z', None, 0xffffff), ('M12 6 18 12', 2, 0x5b6472), ('M18 6 12 12', 2, 0x5b6472))),
             'kb_shift': ((22, 18), (('M9 1 17 10h-4v7H5v-7H1Z', None, 0xffffff),)),
             'kb_back': ((13, 24), (('M12 2 2 12l10 10', 2.6, 0xffffff),)),
             'field_glass': ((16, 16), (('M11 6.5A4.5 4.5 0 1 1 2 6.5 4.5 4.5 0 1 1 11 6.5Z', 2, 0x8a8f96), ('M10 10l4.5 4.5', 2.4, 0x8a8f96)))}
KB_VIEW = {'kb_del': (24, 18), 'kb_shift': (18, 18), 'kb_back': (14, 24), 'field_glass': (16, 16)}
def kb_glyph(name):
    """A glyph's PNG: its viewBox fitted and centred in its box, each part filled, or stroked open at its width."""
    (w, h), parts = KB_GLYPHS[name]
    vw, vh = KB_VIEW[name]
    k = min(w / vw, h / vh)
    dx, dy = (w - vw * k) / 2, (h - vh * k) / 2
    place = lambda polys: [[(x * k + dx, y * k + dy) for x, y in poly] for poly in polys]
    layers = [((place(path(d)) if width is None else place(stroke(path(d), width, closed=d.endswith('Z')))), lambda x, y, c=rgb: (c, 1)) for d, width, rgb in parts]
    return png(w, h, compose((0, 0, w, h), layers))


FIELD_W, FIELD_H = 32, 31  # the field's image: 15 px caps round a column the payload stretches, the row below it in the image
def field():
    """The search field's RGBA bytes: R 15 white, its ring inside, its top inset soft (0, 2, blur 2), the row below it."""
    w, h, box = FIELD_W, FIELD_H, (0, 0, FIELD_W, FIELD_H)
    body = path(rounded_path(0, 0, 32, 30, 15))[0]
    inner = path(rounded_path(1, 1, 30, 28, 14))[0]
    ring = [*body, body[0], inner[0], *inner[::-1], inner[0], body[0]]
    held = coverage([[(x, y + 2) for x, y in body]], box)  # the inset's hole, 2 rows down
    kernel = [math.exp(-k * k / 2) for k in range(-3, 4)]
    at = lambda v, x, y: v[max(0, min(h - 1, y)) * w + max(0, min(w - 1, x))]
    across = [sum(a * at(held, x + i - 3, y) for i, a in enumerate(kernel)) / sum(kernel) for y in range(h) for x in range(w)]
    soft = [sum(a * at(across, x, y + i - 3) for i, a in enumerate(kernel)) / sum(kernel) for y in range(h) for x in range(w)]
    return compose(box, [([[(x, y + 1) for x, y in body]], lambda x, y: (0xffffff, 0x59 / 255)), ([body], lambda x, y: (0xffffff, 1)),
                         ([body], lambda x, y: (0, (1 - soft[int(y) * w + int(x)]) * 0x4d / 255)), ([ring], lambda x, y: (0, 0x2e / 255))])

# A coverage table per radius of the round boxes the painter draws a row at a time (navigation.c paint_round_rows): their
# corners' pixels take the row's colour at this alpha, so they stay the scheme's.
CORNERS = (2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 18, 26, 27)
def corner_cover(r):
    """A radius r corner's coverage out of 255, r rows of r pixels, the outermost first."""
    n = 16
    inside = lambda x, y: sum(math.hypot(r - x - (i + .5) / n, r - y - (j + .5) / n) <= r for i in range(n) for j in range(n))
    return bytes(round(inside(x, y) * 255 / n ** 2) for y in range(r) for x in range(r))
def corner_table():
    """The tables as a C initialiser, by radius."""
    rows = (f'[{r}] = (const unsigned char[]){{ {",".join(map(str, corner_cover(r)))} }}' for r in CORNERS)
    return '{ ' + ', '.join(rows) + ' }'


# The rating panel's hearts: filled, or the outline alone, in the panel's ink; 32 x 30.
RATE_HEART = 'M16 28C6 20 2 15 2 9.6 2 2 12 0 16 7.2 20 0 30 2 30 9.6 30 15 26 20 16 28Z'
RATE_HEART_INKS = {'l': 0x000000, 'd': 0xffffff}
def rate_heart(on, rgb):
    shape = path(RATE_HEART)
    return png(32, 30, compose((0, 0, 32, 30), [((shape if on else []) + stroke(shape, 2.4), lambda x, y: (rgb, 1))]))
def ink(rgb, alpha):
    return lambda x, y: (rgb, alpha / 255)
def numeral(text, size, cx, cy):
    """text's outlines in the theme's font as one even-odd polygon each glyph, centred on cx, its baseline 3.3 / 9.5 of size under cy."""
    font = classic_light_font()
    glyphs, cmap, s = font.getGlyphSet(), font.getBestCmap(), size / font['head'].unitsPerEm
    x = cx - sum(glyphs[cmap[ord(c)]].width for c in text) * s / 2
    out = []
    for c in text:
        glyph = glyphs[cmap[ord(c)]]
        pen = SVGPathPen(glyphs, ntos=lambda v: f'{v:.3f}')
        glyph.draw(TransformPen(pen, (s, 0, 0, -s, x, cy + size * 3.3 / 9.5)))
        contours = path(pen.getCommands())
        out.append([q for one in contours for q in (*one, one[0], contours[0][0])])  # the bridges cancel: counters stay open
        x += glyph.width * s
    return out
def clock_face(half):
    """Set Time's face without its hands, drawn on a -50..50 box: the disc, and 1 to 12 at r 39."""
    k = CLOCK_PX / 100
    fit = lambda polys: [[(CLOCK_PX / 2 + x * k, CLOCK_PX / 2 + y * k) for x, y in poly] for poly in polys]
    a = [i * math.pi / 6 for i in range(1, 13)]
    numerals = [q for i in range(12) for q in numeral(str(i + 1), 10, 39 * math.sin(a[i]), -39 * math.cos(a[i]))]
    rest, quiet = CLOCK_FACE[half]
    return png(CLOCK_PX, CLOCK_PX, compose((0, 0, CLOCK_PX, CLOCK_PX), [
        (fit(path('M-49.5 0A49.5 49.5 0 1 1 49.5 0A49.5 49.5 0 1 1 -49.5 0Z')), ink(rest, 255)),
        (fit(numerals), ink(quiet, 255))]))



def images(t):
    """Theme t's generated images, {name: PNG bytes}; those its values state."""
    out, prefix = {}, t['id'].replace('-', '_')
    if t['chevron_x']:  # white on the band in both halves, its point on the middle row
        out[f'{prefix}_sort_bars'] = png(*SORT_BOX[2:], compose(SORT_BOX, [(path(SORT), lambda x, y: (0xffffff, 1))]))
        out[f'{prefix}_chevron'] = png(*CHEVRON_BOX[2:], compose(CHEVRON_BOX, [
            (stroke(path(CHEVRON), CHEVRON_STROKE, closed=False), lambda x, y: (0xffffff, 1))]))
    if t['bolt']:
        shape = path(BOLT)
        out[f'{prefix}_bolt'] = png(*BOLT_BOX[2:], compose(BOLT_BOX, [(stroke(shape, 1.6), lambda x, y: (0xffffff, t['bolt_halo_a'] / 255)),
                                                                       (shape, lambda x, y: (t['bolt'], 1))]))
        out[f'{prefix}_plug'] = png(*BOLT_BOX[2:], compose(BOLT_BOX, [(path(PLUG), lambda x, y: (t['bolt'], 1))]))
    if t['np_track'] or t['light'].get('np_track'):  # the iPod's bar on Now Playing: its volume's ends
        white = lambda x, y: (0xffffff, 1)
        waves = stroke([p for d in WAVES for p in path(d)], 1.5, closed=False)
        out[f'{prefix}_vol_lo'] = png(*SPEAKER_BOX[2:], compose(SPEAKER_BOX, [(path(SPEAKER), white)]))
        out[f'{prefix}_vol_hi'] = png(*WAVES_BOX[2:], compose(WAVES_BOX, [(path(SPEAKER), white), (waves, white)]))
    if t['state_stops']:
        fill, edge = gradient(t['state_stops'], *STATE_Y), gradient(t['state_edge'], *STATE_Y)
        for name, d in STATE.items():
            shape = path(d)
            for half, halo in (('l', t['state_halo_light']), ('d', t['state_halo_dark'])):
                out[f'{prefix}_{name}_{half}'] = png(*STATE_BOX[2:], compose(STATE_BOX, [
                    *[(stroke(shape, 2.6), lambda x, y, a=halo / 255: (0xffffff, a))][:halo > 0],  # none at alpha 0
                    (shape, lambda x, y: (fill(y), 1)),
                    (stroke(shape, 1), lambda x, y: (edge(y), 1))]))
    drawing = ROOT/f'assets/themes/{t["id"]}/note.svg'
    if drawing.exists():
        out |= {f'{prefix}_note{k}': png(*NOTE_BOX[2:], note(drawing.read_text(), rgb)) for k, rgb in PANE_INK.items()}
    if t['pane_icon_x']:
        for name, d in PANE_ICONS.items():
            fit = name != 'note'
            out |= {f'{prefix}_icon_{name}{k}': png(*(ICON_BOX if fit else NOTE_BOX)[2:], icon(d, fit, rgb)) for k, rgb in PANE_INK.items()}
    if t['painter[PAINT_VOLUME]']:
        for half, rgb in SPEAKER_INKS.items():
            out |= {f'{prefix}_spk_quiet_{half}': speaker(False, rgb), f'{prefix}_spk_loud_{half}': speaker(True, rgb)}
    if t['painter[PAINT_PAGES]']:
        out |= {f'{prefix}_msg_{name}_{half}': qs_mark(name, 1, rgb, MSG_BOX, MSG_SCALE) for name in ('usb', 'note') for half, rgb in MSG_INK.items()}
        out |= {f'{prefix}_{name}': shadow(*a) for name, a in SHADOWS.items()}
        out |= {f'{prefix}_np_{name}_{half}': qs_mark(name, 1, rgb, NP_BOX) for name in NP_MARKS for half, rgb in MSG_INK.items()}
        out |= {f'{prefix}_np_more_q_{half}': qs_mark('more', 1, rgb, NP_BOX) for half, rgb in NP_QUIET.items()}
        for name, (glyph, lit, opacity) in QS_BUTTONS.items():
            out |= {f'{prefix}_drop_{name}{k}': qs_mark(glyph, opacity, rgb) for k, rgb in QS_INK.items()}
        for name, (px, k) in QS_SUNS.items():
            out |= {f'{prefix}_drop_{name}{ink}': qs_mark('sun', 1, rgb, px, k) for ink, rgb in (QS_INK if name == 'dim' else QS_INK | QS_QUIET).items()}
        out[f'{prefix}_clock_dark'] = png(CLOCK_DARK_PX, CLOCK_DARK_PX, clock_dark())
        out |= {f'{prefix}_{name}': kb_glyph(name) for name in KB_GLYPHS}
        out[f'{prefix}_field'] = png(FIELD_W, FIELD_H, field())
        for half, rgb in RATE_HEART_INKS.items():
            out |= {f'{prefix}_heart_on_{half}': rate_heart(True, rgb), f'{prefix}_heart_off_{half}': rate_heart(False, rgb)}
        out |= {f'{prefix}_clock_face_{half}': clock_face(half) for half in CLOCK_FACE}
        out[f'{prefix}_hint_shadow'] = hint_shadow()
    if t['station_stops']:  # Internet Radio's Now Playing art, as large as the slanted art (navigation.c stream_ipod)
        px = inc('NP_IPOD_ART')
        out[f'{prefix}_station'] = png(px, px, station(t['station_stops'], t['station_mast'], t['station_band_a'], t['station_shadow_a'], px))
    return out
