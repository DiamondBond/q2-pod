#!/usr/bin/env python3
"""Build an iPod style overlay from the stock Q2 V1.32 UI assets.

MODE 'music_dark' (default): "an iPod in 2026", Apple Music dark mode driven by the wheel:
black, white and grey text, pink accent, a rounded pink selection pill (build with --row-inset 6).
MODE 'classic': the iPod 5G/nano 3G light look with glossy blue bars.

Usage: ipod_theme.py <stock raw assets dir> <overlay out dir>
The overlay mirrors rootfs paths and holds only files that differ from stock.
"""
import io, os, pathlib, re, sys
from PIL import Image
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import awtkstyle, awtkui

RAW = 'release/assets/default/raw'
MODE = 'music_dark'
DARK = MODE == 'music_dark'
# Apple Music dark palette
ACCENT = (0xfa, 0x2d, 0x48, 0xff)
TEXT2 = (0x8e, 0x8e, 0x93, 0xff)     # secondary text
SEP = (0x2c, 0x2c, 0x2e, 0xff)       # separators, pressed rows
ELEVATED = (0x1c, 0x1c, 0x1e, 0xff)  # dark greys that were cards/dialogs
CHEVRON = (0x63, 0x63, 0x66)
BLUE = (0x2f, 0x7f, 0xe0, 0xff)      # iPod 5G/7G selection blue
HEADER = (0xe4, 0xe6, 0xea, 0xff)    # light grey title bar
DIVIDER = (0xdc, 0xdc, 0xdc, 0xff)
INK = (0x1c, 0x1c, 0x1c)             # icon colour on white


def neutral(r, g, b):
    return max(r, g, b) - min(r, g, b) < 30


def remap(key, rgba):
    """Stock colour -> theme colour. Classic: greys invert, bright accents darken for white.
    Dark: stock is already dark; map it onto Apple's palette with pink as the one accent."""
    r, g, b, a = rgba
    if a == 0:
        return rgba
    if DARK:
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        if neutral(r, g, b):
            if lum < 12:
                return (0, 0, 0, a)
            if lum < 80:
                return ELEVATED[:3] + (a,)
            if lum < 210 and 'text' in key:
                return TEXT2[:3] + (a,)
            return (r, g, b, a) if lum < 210 else (255, 255, 255, a)
        return ACCENT[:3] + (a,) if 'text' in key or r > 200 and g < 80 else (r, g, b, a)
    if neutral(r, g, b):
        return (255 - r, 255 - g, 255 - b, a)
    if 'text' in key and (0.299 * r + 0.587 * g + 0.114 * b) > 150:
        return (r * 55 // 100, g * 55 // 100, b * 55 // 100, a)
    return rgba


def hexc(rgba):
    return '#%02x%02x%02x%02x' % rgba


def parse_hex(v):
    v = v.lstrip('#')
    if len(v) == 6:
        v += 'ff'
    return tuple(int(v[i:i + 2], 16) for i in range(0, 8, 2))


def u32(v):
    return v.to_bytes(4, 'little')


def theme_styles(data):
    t = awtkstyle.load(data)
    for e in t['entries']:
        if e['style'] == 'default':
            continue  # AWTK's own light fallbacks; the app styles what it shows.
        for p in e['props']:
            name, typ, raw = p
            if typ == 7 and 'color' in name and len(raw) == 4:
                p[2] = bytes(remap(name, tuple(raw)))
        if e['widget'] == 'list_item' and e['style'] == 's_listitem_style':
            flat = {'bg_color': (255, 255, 255, 255), 'border_color': DIVIDER,
                    'round_radius': 0, 'round_radius_top_left': 0,
                    'margin_left': 0, 'margin_right': 0, 'margin': 0, 'border_width': 1}
            if e['state'] == 'pressed':
                flat['bg_color'] = BLUE
            props = []
            for name, typ, raw in e['props']:
                if name in flat:
                    v = flat.pop(name)
                    raw = bytes(v) if isinstance(v, tuple) else u32(v)
                props.append([name, typ, raw])
            props.append(['border', 6, u32(8)])  # bottom divider only
            e['props'] = props
        if e['widget'] == 'button' and e['style'] == 's_btn_listitem':
            # Row cards become flat: no fill, no focus ring; highlighted while touched.
            fill = (SEP if DARK else BLUE) if e['state'] == 'pressed' else (0, 0, 0, 0)
            radius = 8 if DARK else 0
            props = [[n, ty, bytes(fill) if n == 'bg_color' else u32(radius) if n == 'round_radius' else raw]
                     for n, ty, raw in e['props'] if n != 'border_width']
            e['props'] = props
        if DARK and e['style'] == 's_scrlabel_white16l':
            for p in e['props']:  # second lines (artists) in secondary grey
                if p[0] == 'text_color':
                    p[2] = bytes(TEXT2)
        if e['widget'] == 'hscroll_label':
            for p in e['props']:
                if p[0] == 'font_size' and int.from_bytes(p[2], 'little') == 24:
                    p[2] = u32(20)
    add_selection_styles(t)
    return awtkstyle.dump(t)


def add_selection_styles(t):
    """'ipod_sel': the selected row's blue bar and its white title, switched in at runtime."""
    white = (255, 255, 255, 255)
    pill = [('bg_color', 7, bytes(ACCENT)), ('border_color', 7, bytes(4)),
            ('round_radius', 7, u32(8)), ('text_color', 7, bytes(white))]
    bar = [('bg_color', 7, bytes(BLUE)), ('border_color', 7, bytes(4)),
           ('round_radius', 7, u32(0)), ('text_color', 7, bytes(white)),
           ('bg_image', 14, SEL_IMAGE.encode() + b'\0')]
    new = {
        'button': pill if DARK else bar,
        'hscroll_label': [('text_color', 7, bytes(white)), ('font_size', 7, u32(20)),
                          ('text_align_h', 6, u32(2))],
        # label centres by default; the row title must stay put when the bar lands on it
        'label': [('text_color', 7, bytes(white)), ('font_size', 7, u32(20)), ('text_align_h', 6, u32(2))],
    }
    second = (255, 255, 255, 0xd0) if DARK else white
    grey_sel = [('text_color', 7, bytes(second)), ('font_size', 7, u32(16)), ('text_align_h', 6, u32(2))]
    blocks = [(w, 'ipod_sel', p) for w, p in new.items()] + \
        [(w, 'ipod_sel2', grey_sel) for w in ('hscroll_label', 'label')]  # selected second line
    if DARK:  # pop-up focus (wheel): the confirm pills with a white ring; retired Tidal image paths
        for style, img in (('ipod_okfocus', 'tidal_confirm_ok'), ('ipod_cancelfocus', 'tidal_confirm_cancel')):
            blocks.append(('image', style, [('bg_image', 14, img.encode() + b'\0')]))
        # Play All focused by the wheel: its icon white on the pink pill (the stock white glyph,
        # kept at a retired Tidal path; the bar's own icon is tinted pink).
        # Draw type 0 as in the stock s_img_allplay_navbar: unset, AWTK centres the glyph in the 100 px
        # box, which put it on the "Play All" text.
        blocks.append(('image', 'ipod_allplayfocus', [('bg_image_draw_type', 6, u32(0)),
                                                      ('bg_image', 14, ALLPLAY_WHITE.encode() + b'\0')]))
        # ...and the sort icon on the bar's right, which the pink would swallow
        blocks.append(('image', 'ipod_orderfocus', [('bg_image_draw_type', 6, u32(0)),
                                                    ('bg_image', 14, ORDER_WHITE.encode() + b'\0')]))
    ents = t['entries']
    for widget, style, props in blocks:
        group = [i for i, e in enumerate(ents) if e['widget'] == widget]
        if not group or any(e['style'] == style and e['widget'] == widget for e in ents):
            continue  # page sheets lack these groups; default.bin carries the shared styles
        last = group[-1]
        def state_props(state):
            out = [list(p) for p in props]
            if state == 'pressed':  # focus images darken while pressed, like the stock pills
                out = [[n, ty, raw.replace(b'\0', b'down\0') if n == 'bg_image' and raw.startswith(b'tidal_confirm') else raw]
                       for n, ty, raw in out]
            return out
        block = [dict(offset=0, state=state, style=style, widget=widget, props=state_props(state))
                 for state in ('normal', 'focused', 'pressed', 'over', 'disable')]
        ents[last + 1:last + 1] = block


HOME_TITLE = os.environ.get('IPOD_HOME_TITLE', 'iPod-Q\u00b2')  # the Home header (the stock font has U+00B2)
HOME_ORDER = ['localmusic', 'folder', 'stream', 'playset', 'sysset', 'playing']
HOME_W = 215 if MODE == 'music_dark' else 375  # dark: menu left, art pane right (split screen)


def node(typ, rect, props, children=()):
    return dict(type=typ, rect=list(rect), props=[list(p) for p in props], children=list(children))


def ipod_home(t):
    """Home carousel -> iPod main menu. The app finds img_<item> by name and hooks its click, and
    finds labels by name for their text; those widgets move into list rows. The slide_menu stays,
    hidden, with inert items: the app still calls slide_menu_* on it."""
    win = t
    sm = next(c for c in win['children'] if c['type'] == 'slide_menu')
    items = {dict(b['props'])['name'][4:]: b for b in sm['children']}
    rows = []
    for key in HOME_ORDER:
        old = items[key]
        img = next(c for c in old['children'] if c['type'] == 'image')
        lab = next(c for c in old['children'] if c['type'] == 'label')
        label = node('label', (12, 0, HOME_W - 48, 30),
                     [p for p in lab['props'] if p[0] in ('name', 'length', 'text')] +
                     [['style', 's_label_white20l']])
        arrow = node('image', (HOME_W - 30, 0, 24, 30), [['image', 'list_into'], ['draw_type', 'center']])
        # Last child, so it is on top for touch; no bg_image, so it draws nothing.
        hit = node('image', (0, 0, HOME_W, 30), [p for p in img['props'] if p[0] in ('name', 'clickable')])
        button = node('button', (0, 0, HOME_W, 30), [['name', 'btn_' + key], ['style', 's_btn_listitem']],
                      [label, arrow, hit])
        rows.append(node('list_item', (0, 0, HOME_W, 30), [['style', 's_listitem_black']], [button]))
    title = node('label', (0, 0, 375, 50), [['text', HOME_TITLE], ['style', 's_label_white20c']])
    if DARK:  # Apple large title: left-aligned and bigger
        title = node('label', (18, 0, 340, 50), [['text', HOME_TITLE], ['style', 's_label_white28c']])
        restyle_inline(title, text_align_h='left')
    header = node('view', (0, 0, 375, 50), [['name', 'view_navbar']], [title])
    scroll = node('scroll_view', (0, 0, HOME_W, 100), [['self_layout', 'default(x=0,y=0,w=%d,h=100%%)' % HOME_W],
                                                    ['name', 'scroll_view_home'],
                                                    # Stock pages enable this in code; a new list must ask.
                                                    ['yslidable', 'true']], rows)
    listv = node('list_view', (0, 50, HOME_W, 210), [['name', 'list_view_home'],
                                                  ['default_item_height', '30'], ['item_height', '30']],
                 [scroll])
    # Stock lists set their colours inline; without that AWTK's default list_view style paints a
    # light #f4f4f4 box with a border below the last row.
    restyle_inline(listv, bg_color='#00000000', border_color='#00000000')
    inert = [node('button', (0, 0, 0, 0), [['name', 'btn_inert%d' % i]],
                  [node('image', (0, 0, 0, 0), []), node('label', (0, 0, 0, 0), [])]) for i in range(6)]
    sm['children'] = inert
    sm['props'] = [p for p in sm['props'] if p[0] not in ('visible', 'enable', 'self_layout')] + \
        [['visible', 'false'], ['enable', 'false']]
    sm['rect'] = [0, 0, 375, 290]
    for c in win['children']:
        if c['type'] == 'image':  # carousel arrows: kept for their handlers, hidden
            c['props'] = [p for p in c['props'] if p[0] != 'visible'] + [['visible', 'false']]
    extra = []
    if HOME_W < 375:  # art pane: ringnav draws the panning cover / cover wall into it
        extra = [node('view', (HOME_W + 6, 56, 375 - HOME_W - 16, 196),
                      [['name', 'view_homeart'], ['sensitive', 'false']])]
    win['children'] = [header, listv] + extra + win['children']


STATES = ('normal', 'pressed', 'over', 'selected', 'disable', 'focused')


def restyle_inline(n, drop=(), **style):
    """Replace inline style keys (all states) on a layout node; drop= removes keys outright."""
    keys = set(style) | set(drop)
    n['props'] = [p for p in n['props']
                  if not (p[0].startswith('style:') and p[0].split(':', 2)[2] in keys)]
    for k, v in style.items():
        n['props'] += [['style:%s:%s' % (st, k), v] for st in STATES]


def find(n, name):
    if dict(n['props']).get('name') == name:
        return n
    for c in n['children']:
        f = find(c, name)
        if f:
            return f


def detach(root, target):
    for c in root['children']:
        if c is target:
            root['children'].remove(c)
            return True
        if detach(c, target):
            return True


def ipod_playing(t):
    """Now Playing -> iPod classic: art left, title/artist/album right, thin blue progress bar.
    Every widget the app drives keeps its name; only placement and inline styles change."""
    fill, track = ((hexc(ACCENT), '#48484aff') if DARK else (hexc(BLUE), '#d4d4d4ff'))
    bar = find(t, 'view_buttons')
    bar_h = NAV_H if DARK else 50
    bar['rect'] = [0, 0, 375, bar_h]
    if not DARK:
        bar['props'] += [['style:normal:bg_color', hexc(HEADER)], ['style:normal:bg_image', HEADER_IMAGE]]
    # ringnav writes "3 of 12" (the track's place in the queue) here, like the iPod classic.
    title = node('label', (70, 0, 150, bar_h), [['name', 'label_npcount'], ['text', 'Now Playing'],
                                                ['style', 's_label_white20c']])
    bar['children'].insert(0, title)
    for name, rect in [('img_return', (0, 0, 70, 50)), ('img_fav', (222, 0, 50, 50)),
                       ('img_playmode', (270, 0, 50, 50)), ('img_more', (318, 0, 55, 50))]:
        w = find(bar, name)
        w['rect'] = list(rect[:3]) + [bar_h]
        restyle_inline(w, drop=('x_offset', 'y_offset'))
        w['props'] = [p for p in w['props'] if p[0] != 'draw_type'] + [['draw_type', 'center']]
        if DARK:
            fit_icon(w)
    # Art left with a margin; everything clears the display's rounded corners.
    art = find(t, 'slide_view_view')
    art['rect'] = [16, 62, 140, 140]
    find(art, 'slide_view')['rect'] = [0, 0, 140, 140]
    find(art, 'img_cover')['rect'] = [0, 0, 140, 140]
    find(art, 'img_playstate')['rect'] = [10, 10, 120, 120]
    find(art, 'label_lyricmsg')['rect'] = [0, 56, 140, 28]
    lrc = find(art, 'view_lrc')
    lrc['props'] = [p for p in lrc['props'] if p[0] != 'self_layout'] + \
        [['self_layout', 'default(x=0,y=0,w=100%,h=140)']]
    ind = find(art, 'slide_indicator1')
    ind['props'] = [p for p in ind['props'] if p[0] not in ('self_layout', 'visible')] + [['visible', 'false']]
    album = find(art, 'label_album')
    detach(t, album)
    t['children'].append(album)
    if DARK:  # the app keeps writing "Album:<name>" here; ringnav mirrors it, prefix-free
        album['props'] = [p for p in album['props'] if p[0] != 'visible'] + [['visible', 'false']]
        # hscroll_label clips (and scrolls) long names; a plain label overflows, leaving stale text
        mirror = node('hscroll_label', (0, 0, 0, 0), [['name', 'label_album_ipod'], ['text', ''],
                                                     ['loop', 'true'], ['lull', '1500']])
        t['children'].append(mirror)
    # Track-info page: small left-aligned lines that fit the art square instead of spilling out.
    info = find(art, 'view_info')
    lines = info['children']
    for i, w in enumerate(lines):  # 8 x 15 px lines, then the file location in the last 20 px
        w['rect'] = [4, i * 15, 136, 15 if i < len(lines) - 1 else 20]
        restyle_inline(w, font_size='12', text_align_h='left')
    for name, rect, style in [('scrlabel_title', (170, 70, 180, 26), 's_scrlabel_white20l'),
                              ('scrlabel_artist', (170, 100, 180, 20), 's_scrlabel_white16l'),
                              ('label_album', (170, 124, 180, 20), 's_label_white16c'),
                              ('label_album_ipod', (170, 124, 180, 20), 's_scrlabel_white16l')][:4 if DARK else 3]:
        w = find(t, name)
        w['rect'] = list(rect)
        w['props'] = [p for p in w['props'] if p[0] != 'style'] + [['style', style]]
        restyle_inline(w, drop=('font_size',), text_align_h='left')
    # Flat iPod bar: exactly bar height so track and fill coincide; the theme knob is swapped
    # for a 1x1 transparent placeholder (menu_left is unused since Home became a list).
    slider = find(t, 'slider_play')
    slider['rect'] = [76, 232, 223, 8]
    restyle_inline(slider, drop=('bg_image', 'fg_image', 'y_offset'),
                   bg_color=track, fg_color=fill, round_radius='4', icon='menu_left')
    slider['props'] = [p for p in slider['props'] if p[0] not in ('bar_size', 'dragger_size')] + \
        [['bar_size', '8'], ['dragger_size', '0']]
    for name in ('img_repeata', 'img_repeatb'):
        find(t, name)['rect'][1] = 231
    find(t, 'label_playtime')['rect'] = [20, 226, 52, 20]
    playtime = find(t, 'label_playtime')
    restyle_inline(playtime, text_align_h='right')
    find(t, 'label_playlen')['rect'] = [303, 226, 52, 20]
    restyle_inline(find(t, 'label_playlen'), text_align_h='left')
    find(t, 'image_wait')['rect'] = [59, 105, 54, 54]
    if DARK:  # dimmed cover behind everything: Apple Music's tinted Now Playing (ringnav keeps it synced)
        # Full screen, so the wash also covers where the status bar was (it is a separate black window).
        t['props'] = [p for p in t['props'] if p[0] != 'fullscreen'] + [['fullscreen', 'true']]
        t['children'].insert(0, node('image', (0, -27, 375, 375),
                                     [['name', 'img_artbg'], ['image', ''], ['draw_type', 'scale_auto'],
                                      ['opacity', '56'], ['sensitive', 'false']]))
    if DARK:  # slimmer bar: everything below moves up; art corners rounded by a mask on top
        # Full screen gains the 30 px status bar: title bar 22 px down, clear of the display's
        # rounded top corners, and the content 32 px lower (there is room above the bottom corners).
        bar['rect'][1] = 22
        for c in t['children']:
            if c is not bar and dict(c['props']).get('name') != 'img_artbg':
                c['rect'][1] += 32 - (50 - bar_h)
        # Rounded art: ringnav draws the cover through a rounded path, so the stock square draw is
        # made invisible (opacity 0 keeps it tappable and app-driven). The pause badge moves above
        # the art page so it still draws on top.
        cover = find(art, 'img_cover')
        cover['props'] = [p for p in cover['props'] if p[0] != 'opacity'] + [['opacity', '0']]
        badge = find(art, 'img_playstate')
        detach(t, badge)
        t['children'].append(badge)
        swipe_pages(t, art, badge)  # Apple Music: pink artist, grey album and times
        restyle_inline(find(t, 'scrlabel_artist'), text_color=hexc(ACCENT))
        # Lyrics drag vertically: scroll_view_create leaves yslidable off, and stock never turned it
        # on (its lyrics only auto-scrolled).
        lrc = find(t, 'scroll_lrc')
        lrc['props'] = [p for p in lrc['props'] if p[0] != 'yslidable'] + [['yslidable', 'true']]
        for name in ('scrlabel_title', 'scrlabel_artist', 'label_album_ipod'):  # scroll there and back
            w = find(t, name)
            w['props'] = [p for p in w['props'] if p[0] != 'yoyo'] + [['yoyo', 'true']]
        # Time left instead of the length: the stock label stays (hidden, still app-updated) and
        # ringnav writes -m:ss into a mirror in its place.
        playlen = find(t, 'label_playlen')
        remain = node('label', playlen['rect'], [['name', 'label_remain_ipod'], ['text', '']] +
                      [p for p in playlen['props'] if p[0].startswith('style')])
        playlen['props'] = [p for p in playlen['props'] if p[0] != 'visible'] + [['visible', 'false']]
        t['children'].insert(t['children'].index(playlen) + 1, remain)
        for name in ('label_album', 'label_album_ipod', 'label_playtime', 'label_remain_ipod'):
            restyle_inline(find(t, name), text_color=hexc(TEXT2))


NAV_H, ALLPLAY_H = 42, 40  # slim title bar and "Play All" bar (stock: 50 and 50)
LAYOUT_RE = re.compile(r'default\(x=(-?\d+),y=(-?\d+),w=([^,]+),h=([^)]+)\)')


def move_node(n, dy, grow):
    """Shift a node up by dy; bottom-anchored nodes grow by dy so their bottom edge stays."""
    n['rect'][1] -= dy
    if grow:
        n['rect'][3] += dy
    for p in n['props']:
        m = p[0] == 'self_layout' and LAYOUT_RE.fullmatch(p[1])
        if m:
            x, y, w, h = m.groups()
            if h.isdigit() and grow:
                h = str(int(h) + dy)
            p[1] = 'default(x=%s,y=%d,w=%s,h=%s)' % (x, int(y) - dy, w, h)


def fit_icon(n):
    """Bar icons are 50 px images holding a 12-28 px glyph: draw them centred at native size.
    The stock default draw type pins them top-left (glyph off-centre); scaling makes thin lines
    jagged, since the toolkit scales nearest-neighbour."""
    if n['type'] in ('image', 'gif', 'button'):
        restyle_inline(n, bg_image_draw_type='center')
        if any(p[0] == 'image' for p in n['props']) or n['type'] != 'button':
            n['props'] = [p for p in n['props'] if p[0] != 'draw_type'] + [['draw_type', 'center']]


def slim_page(t):
    """50 px title bar -> 36, 50 px Play All bar -> 34; content below moves up to use the room."""
    kids = t['children']
    nav = next((c for c in kids if dict(c['props']).get('name') == 'view_navbar'
                and c['rect'] == [0, 0, 375, 50]), None)
    if not nav:
        return
    allplay = next((c for c in kids if dict(c['props']).get('name') == 'view_navbar_allplay'
                    and c['rect'][1] == 50 and c['rect'][3] == 50), None)
    for bar, h in ((nav, NAV_H), (allplay, ALLPLAY_H)):
        if bar:
            bar['rect'][3] = h
            for c in bar['children']:
                if c['rect'][3] == 50:
                    c['rect'][3] = h
                    fit_icon(c)
    if allplay:
        allplay['rect'][1] = NAV_H
        # The wheel's focus on Play All: a pink pill like a selected row, shown by ringnav. It sits
        # in the page just before the (transparent) bar, so it draws behind it: inside the bar it
        # would shift the bar's unnamed children, which the app finds by position.
        pill = node('view', (6, NAV_H + 1, 363, ALLPLAY_H - 2), [['name', 'ipod_allsel'], ['visible', 'false'],
                                                                 ['sensitive', 'false']])
        restyle_inline(pill, bg_color=hexc(ACCENT), border_color='#00000000', round_radius='8')
        kids.insert(kids.index(allplay), pill)
    for c in kids:
        if c is nav or c is allplay:
            continue
        y, h = c['rect'][1], c['rect'][3]
        dy = (50 - NAV_H if y >= 50 else 0) + (50 - ALLPLAY_H if allplay and y >= 100 else 0)
        if dy:
            move_node(c, dy, y + h >= 250)


def has_list(n):
    return n['type'] in ('list_view', 'table_view') or any(has_list(c) for c in n['children'])


def add_letter_overlay(t):
    """Hidden fast-scroll letter (ringnav shows it while the wheel jumps 8+ rows): a dark rounded
    square centred over the list, on top of everything, ignoring touches."""
    letter = node('label', (127, 100, 120, 90), [['name', 'ipod_letter'], ['text', ''],
                                                 ['visible', 'false'], ['sensitive', 'false']])
    restyle_inline(letter, bg_color='#1c1c1ee6', round_radius='18', font_size='56',
                   text_color='#ffffffff', text_align_h='center', text_align_v='middle')
    t['children'].append(letter)


def swipe_pages(t, art, badge):
    """Now Playing's swipeable pages span the whole content area: page 1 is big art with the
    title/artist/album beside it (those labels move into the album page; the app finds them by
    name), swiping shows full-width lyrics, then full-width track info. Page dots sit below."""
    top, h, size = 70, 172, 160
    art['rect'] = [0, top, 375, h]
    find(art, 'slide_view')['rect'] = [0, 0, 375, h - 8]
    album = find(art, 'view_album')
    find(album, 'img_cover')['rect'] = [16, 2, size, size]
    tx, tw = 16 + size + 14, 375 - (16 + size + 14) - 16
    for name, y, hh in (('scrlabel_title', 40, 26), ('scrlabel_artist', 70, 20),
                        ('label_album', 94, 20), ('label_album_ipod', 94, 20)):
        w = find(t, name)
        detach(t, w)
        w['rect'] = [tx, y, tw, hh]
        if name == 'label_album_ipod':  # an enabled hscroll_label would take the swipe
            w['props'] = [p for p in w['props'] if p[0] != 'enable'] + [['enable', 'false']]
        album['children'].append(w)
    badge['rect'] = [16 + 20, top + 2 + 20, 120, 120]  # over the art (paused state)
    find(t, 'image_wait')['rect'] = [16 + size // 2 - 27, top + 2 + size // 2 - 27, 54, 54]
    # Lyrics: full width.
    find(art, 'label_lyricmsg')['rect'] = [0, (h - 8) // 2 - 14, 375, 28]
    lrc = find(art, 'view_lrc')
    lrc['props'] = [p for p in lrc['props'] if p[0] != 'self_layout'] + \
        [['self_layout', 'default(x=0,y=0,w=100%,h=100%)']]
    # Track info: readable 14 px lines across the width; the file location wraps over two lines.
    lines = find(art, 'view_info')['children']
    for i, w in enumerate(lines):
        last = i == len(lines) - 1
        w['rect'] = [24, 4 + i * 18, 327, 36 if last else 18]
        restyle_inline(w, font_size='14', text_align_h='left')
    ind = find(art, 'slide_indicator1')
    ind['props'] = [p for p in ind['props'] if p[0] not in ('self_layout', 'visible')]
    ind['rect'] = [0, h - 7, 375, 6]
    # Timeline under the pages.
    find(t, 'slider_play')['rect'] = [76, top + h + 16, 223, 8]
    for name in ('img_repeata', 'img_repeatb'):
        find(t, name)['rect'][1] = top + h + 15
    find(t, 'label_playtime')['rect'] = [20, top + h + 10, 52, 20]
    find(t, 'label_playlen')['rect'] = [303, top + h + 10, 52, 20]


# Pages whose rows ringnav re-lays out (contexts.inc plus the iPod-only extras). Elsewhere a
# 30 px row height would squash stock 70 px cards, so those lists keep their height.
_CTX = pathlib.Path(__file__).parent / 'contexts.inc'  # next to this script, or the repo's patch/contexts.inc
if not _CTX.exists():
    _CTX = pathlib.Path(__file__).resolve().parents[2] / 'patch' / 'contexts.inc'
CONTEXTS = set(re.findall(r'"([^"]+)"', _CTX.read_text()))
CONTEXTS.add('updatemusic_page')


def theme_layout(data):
    t = awtkui.load(data)
    ipod_rows_page = dict(t['props']).get('name') in CONTEXTS
    if dict(t['props']).get('name') == 'home_page':
        ipod_home(t)

    def walk(n):
        for p in n['props']:
            if p[0].startswith('style:') and p[0].endswith('color') and p[1].startswith('#'):
                p[1] = hexc(remap(p[0], parse_hex(p[1])))
        if n['type'] in ('list_view', 'table_view') and n['rect'][1] + n['rect'][3] >= 280:
            n['rect'][3] -= 30  # clear the display's rounded bottom corners
        if n['type'] == 'list_view' and ipod_rows_page:
            props = dict(n['props'])
            if props.get('default_item_height') == '78':
                n['props'] = [[k, '30' if k == 'default_item_height' else v] for k, v in n['props']]
                n['props'].append(['item_height', '30'])
        if dict(n['props']).get('name') == 'view_right' and n['rect'][0] + n['rect'][2] == 375:
            n['rect'][0] -= 15  # battery clear of the display's rounded top-right corner
        if dict(n['props']).get('name') == 'view_navbar':
            if DARK:  # plain black bar with a hairline, like iOS
                n['props'] += [['style:normal:bg_color', '#000000ff'], ['style:normal:border_color', hexc(SEP)],
                               ['style:normal:border', 'bottom']]
            else:
                n['props'] += [['style:normal:bg_color', hexc(HEADER)],
                               ['style:normal:bg_image', HEADER_IMAGE]]
        for c in n['children']:
            walk(c)
    walk(t)
    if dict(t['props']).get('name') == 'playing_page':
        ipod_playing(t)  # after the recolour walk: its colours are already final
    if DARK:
        slim_page(t)
    if DARK and ipod_rows_page and has_list(t):
        add_letter_overlay(t)
    name = dict(t['props']).get('name')
    if DARK and t['type'] == 'window' and (ipod_rows_page or name == 'playing_page') and name != 'home_page':
        # iPod motion: pages slide in from the right. Opening only: a closing animation keeps the
        # window on top until its frames run, and the app pops pages in tight loops (pick a song in
        # Album info: navigator_back until playing_page), which then never ends and freezes the Q2.
        t['props'] = [p for p in t['props'] if not p[0].endswith('anim_hint')] + \
            [['open_anim_hint', 'htranslate(duration=200,easing=cubic_out)']]
    if DARK and t['type'] == 'system_bar':
        for n in ('img_vol', 'label_vol'):  # tidier status bar: no speaker icon or volume number
            w = find(t, n)
            w['rect'][2] = 0
            w['props'] = [p for p in w['props'] if p[0] != 'visible'] + [['visible', 'false']]
    if DARK and t['type'] == 'dialog':
        ipod_dialog(t)
    if dict(t['props']).get('name') == 'bigcover_page':
        # Full-screen art: a 375 px square box centred on the 375x320 screen, so square covers fill
        # the width and the window crops ~27 px top and bottom, instead of letterboxing at 320 px.
        cover = find(t, 'img_bigcover')
        cover['props'] = [p for p in cover['props'] if p[0] != 'self_layout'] + \
            [['self_layout', 'default(x=0,y=-27,w=375,h=375)']]
        restyle_inline(t, bg_color='#000000ff')  # photo page stays black behind non-square art
    return awtkui.dump(t)


CARD = (0x2c, 0x2c, 0x2e, 0xff)     # alert and HUD cards, over the dimmed page
FILL = (0x54, 0x54, 0x58, 0xff)     # unfilled track, secondary buttons
# Alert-style dialogs: (x, y, w, h) of the card behind the dialog's own widgets. msginfo builds its
# lines in code, at y 110-204 (hscroll_label_create in dialog_msginfo_dialog_init).
CARDS = {'confirminfo_dialog': (16, 58, 343, 180), 'checkfw_dialog': (16, 108, 343, 88),
         'msginfo_dialog': (16, 88, 343, 140), 'autoshutdown_dialog': (16, 86, 343, 214)}
PILL_W, PILL_H = 150, 46


def ipod_dialog(t):
    """Pop-ups become Apple alert cards over the dimmed page; volume becomes a slider HUD."""
    name = dict(t['props']).get('name')
    if name == 'volume_dialog':
        # The app moves label_vol onto the knob (dragger x+2, centred) and writes the number there:
        # dark text on the white knob. Card and speaker icons sit behind and beside the track.
        vol = find(t, 'label_vol')
        restyle_inline(vol, text_color='#1c1c1eff', font_size='15')
        card = node('view', (8, 121, 359, 64), [['name', 'view_volcard'], ['sensitive', 'false']])
        restyle_inline(card, bg_color=hexc(CARD), border_color='#00000000', round_radius='20')
        icons = [node('image', (x, 142, 26, 23), [['image', img], ['draw_type', 'center'], ['sensitive', 'false']])
                 for x, img in ((17, 'vol_left'), (332, 'vol_right'))]
        t['children'] = [card] + icons + t['children']
        dim(t, 110)
        return
    if name not in CARDS:
        return
    card = node('view', CARDS[name], [['name', 'view_alertcard'], ['sensitive', 'false']])
    restyle_inline(card, bg_color=hexc(CARD), border_color='#00000000', round_radius='18')
    t['children'].insert(0, card)
    restyle_inline(t, bg_color='#00000000', border_color='#00000000')
    dim(t, 120)
    x, y, w, h = CARDS[name]
    for key, left in (('img_cancel', True), ('img_enter', False)):
        b = find(t, key)
        if b:  # pill buttons side by side along the card's bottom edge
            gap = (w - 2 * PILL_W) // 3
            b['rect'] = [x + gap if left else x + w - gap - PILL_W, y + h - 20 - PILL_H, PILL_W, PILL_H]
    b = find(t, 'btn_cancel')
    if b:
        restyle_inline(b, bg_color=hexc(FILL), round_radius='20')


def dim(t, alpha):
    """How dark the page behind the dialog goes (AWTK dialog highlighter)."""
    t['props'] = [p for p in t['props'] if p[0] != 'highlight'] + [['highlight', 'default(alpha=%d)' % alpha]]


def png(im):
    buf = io.BytesIO()
    im.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def vol_track(filled):
    """Slider bar image (283x102, drawn clipped to the filled width): a 10 px rounded track."""
    from PIL import ImageDraw
    k, w, h, th = 4, 283, 102, 10
    im = Image.new('RGBA', (w * k, h * k), (0, 0, 0, 0))
    top = (h - th) // 2 * k
    ImageDraw.Draw(im).rounded_rectangle((2 * k, top, (w - 2) * k - 1, top + th * k - 1), radius=th * k // 2,
                                         fill=ACCENT if filled else FILL)
    return png(im.resize((w, h), Image.LANCZOS))


def vol_knob():
    """White 30 px knob with a soft edge, on the stock 36x36 dragger canvas."""
    from PIL import ImageDraw, ImageFilter
    k, s, r = 4, 36, 15
    im = Image.new('RGBA', (s * k, s * k), (0, 0, 0, 0))
    c = s * k // 2
    shadow = Image.new('RGBA', im.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((c - r * k - 2 * k, c - r * k - k, c + r * k + 2 * k, c + r * k + 3 * k),
                                   fill=(0, 0, 0, 110))
    im = Image.alpha_composite(im, shadow.filter(ImageFilter.GaussianBlur(2 * k)))
    ImageDraw.Draw(im).ellipse((c - r * k, c - r * k, c + r * k, c + r * k), fill=(255, 255, 255, 255))
    return png(im.resize((s, s), Image.LANCZOS))


def recolour_png(data, rgb):
    """Any glyph -> one colour, keeping its alpha (the stock speaker icons are red)."""
    im = Image.open(io.BytesIO(data)).convert('RGBA')
    im.putdata([(*rgb, a) for r, g, b, a in im.get_flattened_data()])
    return png(im)


def pill_png(ok, pressed, ring=False):
    """Alert button: pink pill with a tick, or a grey pill with a cross; darker while pressed.
    ring: the wheel's focus, a white ring just inside the edge."""
    from PIL import ImageDraw
    k, w, h = 4, PILL_W, PILL_H
    fill = ACCENT if ok else FILL
    if pressed:
        fill = tuple(v * 7 // 10 for v in fill[:3]) + (255,)
    im = Image.new('RGBA', (w * k, h * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=h * k // 2, fill=fill)
    if ring:
        d.rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=h * k // 2, outline=(255, 255, 255, 255),
                            width=round(2.5 * k))
    cx, cy, g, lw = w * k / 2, h * k / 2, 8 * k, round(2.6 * k)
    pts = [(cx - g, cy), (cx - g / 3, cy + g * 2 / 3), (cx + g, cy - g * 2 / 3)] if ok else None
    if ok:
        d.line(pts, fill=(255, 255, 255, 255), width=lw, joint='curve')
        for x, y in (pts[0], pts[-1]):
            d.ellipse((x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2), fill=(255, 255, 255, 255))
    else:
        g = 6.5 * k
        for a, b in (((cx - g, cy - g), (cx + g, cy + g)), ((cx - g, cy + g), (cx + g, cy - g))):
            d.line((a, b), fill=(255, 255, 255, 255), width=lw)
            for x, y in (a, b):
                d.ellipse((x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2), fill=(255, 255, 255, 255))
    return png(im.resize((w, h), Image.LANCZOS))


def radio_png(on):
    """26 px choice circle, iOS style: pink disc with a white tick, or an empty grey ring."""
    from PIL import ImageDraw
    k, s = 4, 26
    im = Image.new('RGBA', (s * k, s * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = 2 * k
    if on:
        d.ellipse((pad, pad, s * k - pad, s * k - pad), fill=ACCENT)
        c, g, lw = s * k / 2, 5 * k, round(2 * k)
        pts = [(c - g, c + k * 0.2), (c - g / 3, c + g * 0.66), (c + g, c - g * 0.6)]
        d.line(pts, fill=(255, 255, 255, 255), width=lw, joint='curve')
        for x, y in (pts[0], pts[-1]):
            d.ellipse((x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2), fill=(255, 255, 255, 255))
    else:
        d.ellipse((pad, pad, s * k - pad, s * k - pad), outline=CHEVRON + (255,), width=round(1.6 * k))
    return png(im.resize((s, s), Image.LANCZOS))


def usb_png(kind):
    """USB screen art (170x170): an app-icon tile with a white glyph instead of the glowing discs:
    an SD card (USB storage) or level bars (USB DAC)."""
    from PIL import ImageDraw
    k, s, tile = 4, 170, 116
    im = Image.new('RGBA', (s * k, s * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    o = (s - tile) // 2 * k
    top, bottom = ((0x3a, 0x3a, 0x3c), (0x1c, 0x1c, 0x1e))
    for y in range(tile * k):  # soft vertical gradient, rounded later by the mask
        f = y / (tile * k - 1)
        d.line((o, o + y, o + tile * k, o + y), fill=tuple(round(a + (b - a) * f) for a, b in zip(top, bottom)) + (255,))
    mask = Image.new('L', im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((o, o, o + tile * k - 1, o + tile * k - 1), radius=28 * k, fill=255)
    im.putalpha(mask)
    d = ImageDraw.Draw(im)
    c = s * k / 2
    white = (255, 255, 255, 255)
    if kind == 'storage':
        w, h, cut = 44 * k, 58 * k, 13 * k
        x0, y0 = c - w / 2, c - h / 2
        card = Image.new('L', im.size, 0)  # rounded card, clipped by the angled corner
        ImageDraw.Draw(card).rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=6 * k, fill=255)
        clip = Image.new('L', im.size, 0)
        ImageDraw.Draw(clip).polygon([(x0, y0), (x0 + w - cut, y0), (x0 + w, y0 + cut), (x0 + w, y0 + h), (x0, y0 + h)],
                                     fill=255)
        from PIL import ImageChops
        im.paste(white, (0, 0), ImageChops.darker(card, clip))
        d = ImageDraw.Draw(im)
        for i in range(4):  # contacts
            x = x0 + 8 * k + i * 7 * k
            d.rounded_rectangle((x, y0 + 7 * k, x + 4 * k, y0 + 19 * k), radius=1.5 * k, fill=(0x2c, 0x2c, 0x2e, 255))
    else:
        bars = (18, 34, 52, 40, 26, 46, 22)
        bw, gap = 6 * k, 5 * k
        x = c - (len(bars) * bw + (len(bars) - 1) * gap) / 2
        for hgt in bars:
            hh = hgt * k
            d.rounded_rectangle((x, c - hh / 2, x + bw, c + hh / 2), radius=bw / 2, fill=ACCENT if hgt == 52 else white)
            x += bw + gap
    return png(im.resize((s, s), Image.LANCZOS))


SPEEDS = {'1': '1\u00d7', '2': '1.25\u00d7', '3': '1.5\u00d7', '4': '2\u00d7'}


def speed_chip(n, on):
    """Playback speed option (42x24): the chosen speed a solid pink pill, the others outlined."""
    from PIL import ImageDraw, ImageFont
    k, w, h = 4, 42, 24
    im = Image.new('RGBA', (w * k, h * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    box = (k, 2 * k, w * k - k - 1, h * k - 2 * k - 1)
    if on:
        d.rounded_rectangle(box, radius=10 * k, fill=ACCENT)
    else:
        d.rounded_rectangle(box, radius=10 * k, outline=(0x63, 0x63, 0x66, 255), width=round(1.3 * k))
    text = SPEEDS[n]
    try:
        size = 13
        font = ImageFont.truetype(ui_font(), size * k)
        while d.textlength(text, font=font) > (w - 8) * k and size > 9:
            size -= 1
            font = ImageFont.truetype(ui_font(), size * k)
        d.text((w * k / 2, h * k / 2), text, font=font, anchor='mm',
               fill=(255, 255, 255, 255) if on else (0xae, 0xae, 0xb2, 255))
    except OSError:
        pass
    return png(im.resize((w, h), Image.LANCZOS))


# Bluetooth: the connect card's art (ringnav shows it when a headset connects; retired Tidal
# paths) and status-bar codec badges redrawn as one set of outlined text badges (stock mixed an
# 11 px AAC logo with plain text of varying sizes, all pushed right in a 42 px slot).
from PIL import ImageDraw, ImageFilter, ImageFont
def airpods_art(w=150,h=110,k=4):
    """Two AirPods Pro, white with soft grey shading, facing each other."""
    im=Image.new('RGBA',(w*k,h*k),(0,0,0,0))
    def bud(cx,flip):
        layer=Image.new('RGBA',im.size,(0,0,0,0)); d=ImageDraw.Draw(layer)
        s=-1 if flip else 1
        # head
        d.ellipse((cx-24*k,20*k,cx+24*k,64*k),fill=(245,245,247,255))
        # ear tip (grey silicone) toward the centre
        tx=cx+s*21*k; d.ellipse((tx-9*k,31*k,tx+9*k,49*k),fill=(200,200,205,255))
        # stem
        sx=cx-s*8*k; d.rounded_rectangle((sx-8*k,50*k,sx+8*k,100*k),radius=8*k,fill=(245,245,247,255))
        # stem sensor line and speaker mesh
        d.rounded_rectangle((sx-3*k,62*k,sx+3*k,80*k),radius=3*k,fill=(215,215,220,255))
        d.ellipse((cx-s*6*k-5*k,30*k,cx-s*6*k+5*k,40*k),fill=(60,60,64,255))
        return layer
    shadow=Image.new('RGBA',im.size,(0,0,0,0)); ImageDraw.Draw(shadow).ellipse((20*k,96*k,(w-20)*k,106*k),fill=(0,0,0,120))
    im=Image.alpha_composite(im,shadow.filter(ImageFilter.GaussianBlur(4*k)))
    im=Image.alpha_composite(im,bud(36*k,False)); im=Image.alpha_composite(im,bud((w-36)*k,True))
    return im.resize((w,h),Image.LANCZOS)
def headphones_art(w=150,h=110,k=4):
    im=Image.new('RGBA',(w*k,h*k),(0,0,0,0)); d=ImageDraw.Draw(im); c=w*k/2
    d.arc((c-46*k,8*k,c+46*k,100*k),start=180,end=360,fill=(245,245,247,255),width=9*k)
    for sx in (c-46*k,c+46*k):
        d.rounded_rectangle((sx-14*k,52*k,sx+14*k,100*k),radius=12*k,fill=(245,245,247,255))
    return im.resize((w,h),Image.LANCZOS)
def codec_badge(text,w=42,h=16,k=6):
    im=Image.new('RGBA',(w*k,h*k),(0,0,0,0)); d=ImageDraw.Draw(im)
    size=11
    font=ImageFont.truetype(ui_font(),size*k)
    while d.textlength(text,font=font)>(w-7)*k and size>7:
        size-=1; font=ImageFont.truetype(ui_font(),size*k)
    tw=d.textlength(text,font=font); pad=3*k
    x1=w*k-1; x0=x1-tw-2*pad
    d.rounded_rectangle((x0,1.5*k,x1,h*k-1.5*k),radius=3.5*k,outline=(255,255,255,235),width=int(1.2*k))
    d.text(((x0+x1)/2,h*k/2),text,font=font,anchor='mm',fill=(255,255,255,255))
    return im.resize((w,h),Image.LANCZOS)

ART = pathlib.Path(__file__).parent / 'art'
ALLPLAY_WHITE = 'tidal_top'  # the stock (white) Play All glyph, for the focused pill
ORDER_WHITE = 'tidal_track'  # the stock (white) sort glyph, likewise
ACCENT_SWATCH = 'tidal_album'  # System Setting > Theme Colour: a dot in the accent (ringnav recolours it)
SRC = None                   # the stock raw assets dir (set by main)


def accent_swatch():
    """50x28 row icon: an 18 px dot in the accent, at 4x then downsampled for smooth edges."""
    from PIL import ImageDraw
    k = 4
    im = Image.new('RGBA', (50 * k, 28 * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = 9 * k
    cx, cy = 34 * k, 14 * k  # right-aligned in the 50 px slot, like the toggles
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tuple(ACCENT[:3]) + (255,))
    return im.resize((50, 28), Image.LANCZOS)


def card_photo(name, box):
    """AirPods Pro 2 render (from LibrePods' res-apple, Apple's artwork: personal firmware only),
    trimmed and fitted into a box x box square for the connect card; None if the file is absent."""
    try:
        im = Image.open(ART / name).convert('RGBA')
    except OSError:
        return None
    im = im.crop(im.getbbox())
    im.thumbnail((box, box), Image.LANCZOS)
    out = Image.new('RGBA', (box, box), (0, 0, 0, 0))
    out.alpha_composite(im, ((box - im.width) // 2, (box - im.height) // 2))
    return out


CODECS = {'bar_aac': 'AAC', 'bar_sbc': 'SBC', 'bar_ldac': 'LDAC', 'bar_aptx': 'aptX', 'bar_aptxhd': 'aptX HD'}


DIALOG_IMAGES = {
    'vol_back': lambda d: vol_track(False), 'vol_plan': lambda d: vol_track(True),
    'vol_dot1': lambda d: vol_knob(),
    'vol_left': lambda d: recolour_png(d, TEXT2[:3]), 'vol_right': lambda d: recolour_png(d, TEXT2[:3]),
    'confirm_ok': lambda d: pill_png(True, False), 'confirm_okdown': lambda d: pill_png(True, True),
    'confirm_cancel': lambda d: pill_png(False, False), 'confirm_canceldown': lambda d: pill_png(False, True),
    'tidal_confirm_ok': lambda d: pill_png(True, False, True), 'tidal_confirm_okdown': lambda d: pill_png(True, True, True),
    'tidal_confirm_cancel': lambda d: pill_png(False, False, True),
    'tidal_confirm_canceldown': lambda d: pill_png(False, True, True),
    'select': lambda d: radio_png(True), 'unselect': lambda d: radio_png(False),
    'usb_storage': lambda d: usb_png('storage'), 'usb_dac': lambda d: usb_png('dac'),
    'play_fav': lambda d: recolour_png(d, ACCENT[:3]),  # the filled heart: stock red -> Apple pink
    'tidal_shangling_big': lambda d: png(card_photo('airpods_pro_2.png', 130) or airpods_art()),
    'tidal_shanling': lambda d: png(headphones_art()),
    ALLPLAY_WHITE: lambda d: (SRC / 'images' / 'xx' / 'navbar_playall.png').read_bytes(),
    ORDER_WHITE: lambda d: (SRC / 'images' / 'xx' / 'song_order.png').read_bytes(),
    ACCENT_SWATCH: lambda d: png(accent_swatch()),
    **{stem: (lambda d, t=t: png(codec_badge(t))) for stem, t in CODECS.items()},
    **{'forward_' + n: (lambda d, n=n: speed_chip(n, True)) for n in SPEEDS},
    **{'forward_un' + n: (lambda d, n=n: speed_chip(n, False)) for n in SPEEDS},
}


APPLE_FONT = '/System/Library/Fonts/SFNS.ttf'  # macOS system font; carries the Apple glyph U+F8FF


def ui_font():
    """Badge/chip text: the macOS system font if present, else the Q2's own font (any OS)."""
    return APPLE_FONT if os.path.exists(APPLE_FONT) else str(SRC / 'fonts' / 'default.ttf')


def boot_logo():
    """Boot splash (images/xx/logo.jpg, drawn by display_logo early in boot): a white Apple logo
    centred on black, like an iPod starting up. The panel scans portrait, so the stock file is the
    375x320 picture turned 90 degrees clockwise (320x375). Opt-in (IPOD_APPLE_LOGO=1: Apple's logo,
    from the macOS font); otherwise, or without the font, None: the stock logo is kept."""
    from PIL import ImageDraw, ImageFont
    if os.environ.get('IPOD_APPLE_LOGO') != '1':
        return None
    try:
        font = ImageFont.truetype(APPLE_FONT, 400)
    except OSError:
        return None
    k, w, h, size = 4, 375, 320, 104  # logo height in screen pixels
    glyph = Image.new('L', (600, 600), 0)
    ImageDraw.Draw(glyph).text((50, 0), '\uf8ff', font=font, fill=255)
    glyph = glyph.crop(glyph.getbbox())
    gw = round(glyph.width * size * k / glyph.height)
    glyph = glyph.resize((gw, size * k), Image.LANCZOS)
    im = Image.new('L', (w * k, h * k), 0)
    im.paste(255, ((w * k - gw) // 2, (h * k - size * k) // 2 - 6 * k), glyph)
    im = im.resize((w, h), Image.LANCZOS).convert('RGB').rotate(-90, expand=True)
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=92)  # baseline, like the stock file
    return buf.getvalue()


TINY_PNG = None


def tiny_png():
    """1x1 transparent placeholder: frees rootfs space for images of removed features (Tidal)."""
    global TINY_PNG
    if TINY_PNG is None:
        buf = io.BytesIO()
        Image.new('RGBA', (1, 1)).save(buf, 'PNG', optimize=True)
        TINY_PNG = buf.getvalue()
    return TINY_PNG


# Retired carousel artwork paths reused for theme images (the rootfs file list is fixed).
SEL_IMAGE, HEADER_IMAGE, MASK_IMAGE = 'menu_music', 'menu_playing', 'menu_stream'


def corner_mask(size=140, radius=12):
    """Black outside a rounded square, transparent inside (anti-aliased): rounds the art on black."""
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    for y in range(size):
        for x in range(size):
            cx = min(max(x + 0.5, radius), size - radius)
            cy = min(max(y + 0.5, radius), size - radius)
            d = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5 - radius
            a = max(0.0, min(1.0, d + 0.5))
            if a:
                im.putpixel((x, y), (0, 0, 0, round(a * 255)))
    buf = io.BytesIO()
    im.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def gradient_png(w, h, stops):
    """Vertical gradient through (position 0..1, rgb) stops, sized exactly to what it fills."""
    im = Image.new('RGBA', (w, h))
    for y in range(h):
        f = y / max(h - 1, 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= f <= p1:
                k = (f - p0) / max(p1 - p0, 1e-6)
                rgb = tuple(round(a + (b - a) * k) for a, b in zip(c0, c1))
                break
        for x in range(w):
            im.putpixel((x, y), (*rgb, 255))
    buf = io.BytesIO()
    im.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def gloss_bar():
    # iPod selection: glossy top half over a deeper blue base.
    return gradient_png(375, 30, [(0, (0x6d, 0xae, 0xf5)), (0.49, (0x3b, 0x8b, 0xea)),
                                  (0.5, (0x1f, 0x6f, 0xdc)), (1, (0x2a, 0x7f, 0xe6))])


def header_bar():
    # iPod title bar: light-to-mid grey, with a darker last line as its edge.
    return gradient_png(375, 50, [(0, (0xf7, 0xf7, 0xf8)), (0.5, (0xe3, 0xe5, 0xe8)),
                                  (0.97, (0xc9, 0xcc, 0xd1)), (1, (0x8e, 0x92, 0x98))])


def tint_png(data, rgb):
    """Recolour a light glyph, keeping its alpha."""
    rgba = Image.open(io.BytesIO(data)).convert('RGBA')
    rgba.putdata([(*rgb, a) if a and min(r, g, b) > 120 and neutral(r, g, b) else (r, g, b, a)
                  for r, g, b, a in rgba.get_flattened_data()])
    buf = io.BytesIO()
    rgba.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def toggle_png(on):
    """iOS-style switch (iOS proportions), 38x22 so it sits inside a 30 px row unscaled; drawn 4x and
    downsampled for smooth edges."""
    from PIL import ImageDraw
    k, w, h = 4, 38, 22
    im = Image.new('RGBA', (w * k, h * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=h * k // 2,
                        fill=ACCENT if on else (0x39, 0x39, 0x3d, 255))
    r, pad = (h * k) // 2 - 2 * k, 2 * k
    cx = w * k - pad - r if on else pad + r
    d.ellipse((cx - r, h * k // 2 - r, cx + r, h * k // 2 + r), fill=(255, 255, 255, 255))
    im = im.resize((w, h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def theme_image(data, stem=''):
    """Classic: white line icons -> dark ink. Dark: glyphs stay white, except grey chevrons and
    pink navigation-bar buttons. Icons with dark parts (white glyph on a dark disc) stay."""
    if DARK:
        if stem in ('list_into', 'list_intodown'):
            return tint_png(data, CHEVRON)
        if stem in NAV_IMAGES:
            return tint_png(data, ACCENT[:3])
        return None
    im = Image.open(io.BytesIO(data))
    rgba = im.convert('RGBA')
    px = list(rgba.get_flattened_data())
    visible = [p for p in px if p[3] > 20]
    if not visible or len(visible) > 0.97 * len(px):
        return None
    if any(p[3] > 100 and max(p[:3]) < 110 for p in visible):
        return None
    light = [p for p in visible if min(p[:3]) > 170 and neutral(*p[:3])]
    if len(light) < 0.6 * len(visible):
        return None
    out = [(*INK, a) if a and min(r, g, b) > 120 and neutral(r, g, b) else (r, g, b, a)
           for r, g, b, a in px]
    rgba.putdata(out)
    buf = io.BytesIO()
    rgba.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


NAV_STYLES = ('s_img_return', 'g_img_home', 's_img_search', 's_img_mulsel', 's_img_allplay_navbar',
              's_img_order_navbar')
NAV_IMAGES = set()


def main(src, dst):
    global SRC
    src, dst = pathlib.Path(src), pathlib.Path(dst)
    SRC = src
    theme = awtkstyle.load((src / 'styles' / 'default.bin').read_bytes())
    for e in theme['entries']:  # images drawn by the navigation-bar button styles
        if e['style'] in NAV_STYLES or 'navbar' in e['style']:
            NAV_IMAGES.update(raw.rstrip(b'\0').decode() for n, ty, raw in e['props'] if ty == 14 and 'image' in n)
    count = {}
    for f in sorted(src.rglob('*')):
        if not f.is_file():
            continue
        rel = f.relative_to(src)
        data = f.read_bytes()
        kind, new = None, None
        if rel.parts[0] == 'styles' and f.suffix == '.bin':
            kind, new = 'styles', theme_styles(data)
        elif rel.parts[0] == 'ui' and f.suffix == '.bin':
            kind, new = 'layouts', theme_layout(data)
        elif DARK and rel.parts[0] == 'images' and f.suffix == '.png' and f.stem in ('switch_on', 'switch_off'):
            kind, new = 'toggles', toggle_png(f.stem == 'switch_on')
        elif DARK and rel.parts[0] == 'images' and f.name == 'logo.jpg':
            kind, new = 'boot logo', boot_logo()
        elif DARK and rel.parts[0] == 'images' and f.suffix == '.png' and f.stem in DIALOG_IMAGES:
            kind, new = 'dialogs', DIALOG_IMAGES[f.stem](data)
        elif DARK and rel.parts[0] == 'images' and f.suffix == '.png' and f.stem == MASK_IMAGE:
            kind, new = 'art mask', corner_mask()
        elif not DARK and rel.parts[0] == 'images' and f.suffix == '.png' and f.stem == SEL_IMAGE:
            kind, new = 'gradients', gloss_bar()
        elif not DARK and rel.parts[0] == 'images' and f.suffix == '.png' and f.stem == HEADER_IMAGE:
            kind, new = 'gradients', header_bar()
        elif rel.parts[0] == 'images' and f.suffix == '.png' and f.stem.startswith(('tidal_', 'menu_')):
            kind, new = 'tidal placeholders', tiny_png()
        elif rel.parts[0] == 'images' and f.suffix == '.png':
            kind, new = 'icons', theme_image(data, f.stem)
        if new is not None and new != data:
            out = dst / RAW / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(new)
            count[kind] = count.get(kind, 0) + 1
    print('changed', count)


if __name__ == '__main__':
    main(*sys.argv[1:3])
