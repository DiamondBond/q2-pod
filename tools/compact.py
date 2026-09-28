"""Build-time edits for the SHA-pinned UI assets (local browsing, settings, status bar) and native call sites.

No global widget hook: excluded pages stay byte-identical; iPod's list style edits are audited in place.
The audit records full original instructions and asset hashes, not search/replace patterns.
"""
import copy
import functools
import hashlib
import json
import pathlib
import re
import struct
from build import ROOT, check as require, fileoff

AUDIT = json.loads((pathlib.Path(__file__).resolve().parents[1]/'patch/compact.json').read_text())
UI_ASSETS = AUDIT['assets'] | AUDIT['navbar_only']
# The app window is the 375x320 screen minus the 30px status bar, so a 290px list holds four
# 72px rows. The stock 52px artwork is drawn 1:1 (no rescaling) with an 8px inset inside the
# 68px row body. Rows keep the row layout's eight-pixel left margin for the artwork.
BOTTOM = 290
PITCH = 72
BODY = PITCH - 4
ART = 52
ART_INSET = (BODY - ART) // 2
# iPod status bar (system_bar.bin, 375x30). Stock pads both icon groups 50px from the edges, but
# stock pages already put controls 3px from them (Now Playing's back arrow), so iPod uses the list
# rows' 8px. The title is centred on the screen: it spans between the right group's extent (EQ 20,
# BT/codec 43, Wi-Fi 16, battery 10, 5px apart: 112px) and the same distance from the left edge,
# 151px wide.
MARGIN = 8
TITLE_MIN = 150
# iPod Home: seven 41px rows fill the 290px client area; labels start at MARGIN and fit the longest
# English one ("Playback Setting", 149px at 20px). The art is a square on the right, centred.
INC = (ROOT/'patch/offsets.inc').read_text()
CHEVRON_W = int(re.search(r'#define CHEVRON_W (\d+)', INC)[1])
HOME_ROW = 41
HOME_LABEL_END = CHEVRON_W - 10  # label end to the row's right edge: 10px before the glyph (x 20 of 50)
HOME_LIST_W = MARGIN + 149 + HOME_LABEL_END
HOME_ART = 375 - HOME_LIST_W - 2 * MARGIN
HOME_ART_RECT = [HOME_LIST_W + MARGIN, (BOTTOM - HOME_ART) // 2, HOME_ART, HOME_ART]
# iPod Now Playing (Rockbox iVideo): a 40px top row, the art band below it, then the progress bar
# with the times under its ends. Stock draws the 3x10 A-B markers at y 250, so the 8px bar sits on
# 251; their x follows NP_BAR through the np_bar_* immediates in compact.json.
NP_TOP = 40
NP_ICON = 50                     # the stock 50px control icons, centred in the top row
NP_ART = 170
NP_SLIDE_H = 186                 # the swipeable art, lyrics and info pages; the dots sit below
NP_BAR = [MARGIN, 251, 375 - 2 * MARGIN, 8]
NP_TEXT_X = MARGIN + NP_ART + 12
NP_GREY = '#AAAAAA'              # stock secondary text (s_scrlabel_gray24l)
# The track is the status bar's bottom; the fill is Graphite's light tone until ringnav_playing sets the
# accent's (3.3:1 or more on the track for every preset).
NP_TRACK = '#' + re.search(r'#define BAR_BOTTOM 0x(\w+)', INC)[1]
NP_FILL = '#' + re.search(r'#define ACCENTS \{ 0x\w+, 0x\w+, 0x(\w+), 0x\w+ \}', INC)[1]


def decode(data):
    require(data[:4] == bytes.fromhex('12122211'), 'Unexpected AWTK UI magic')
    i = 4

    def string():
        nonlocal i
        end = data.index(0, i)
        value = data[i:end].decode('utf-8')
        i = end + 1
        return value

    def node():
        nonlocal i
        require(i + 48 <= len(data), 'Truncated UI widget')
        kind = data[i:i+32].split(b'\0')[0].decode('ascii')
        i += 32
        geometry = list(struct.unpack_from('<4i', data, i))
        i += 16
        props = {}
        while data[i]:
            key, value = string(), string()
            require(key not in props, 'Duplicate UI property')
            props[key] = value
        i += 1
        children = []
        while data[i]:
            children.append(node())
        i += 1
        return [kind, geometry, props, children]

    root = node()
    require(i == len(data), 'Trailing UI data')
    return root


def walk(n):
    yield n
    for child in n[3]:
        yield from walk(child)


def encode(root):
    def node(n):
        kind, geometry, props, children = n
        return (kind.encode().ljust(32, b'\0') + struct.pack('<4i', *geometry) +
                b''.join(k.encode()+b'\0'+v.encode()+b'\0' for k, v in props.items()) +
                b'\0' + b''.join(node(c) for c in children) + b'\0')
    return bytes.fromhex('12122211') + node(root)


# Both variants. Stock artist detail tabs carry literal Chinese `text` in every language; the
# stock string table already has these keys. The Albums tab and page start active (see ARTIST_ALBUMS).
ARTIST_PAGE = 'localmusic/artistinfo_page.bin'
ARTIST_TABS = {'btn_track': ('单曲', 'local_allsongs'), 'btn_album': ('专辑', 'album')}
# Stock init builds the Songs view (0x4adcbc); call the stock Albums tab click handler (0x4ac7ec)
# instead, which sets the tab state, queries the artist's albums and builds them. Songs stays a tap away.
ARTIST_ALBUMS = [(0x4aebd0, 0x2739dcbc, 0x2739c7ec), (0x4aebd4, 0x0411fc39, 0x0411f705)]


def artist_tabs(root):
    found = []
    for n in walk(root):
        name = n[2].get('name')
        if name in ARTIST_TABS:
            text, key = ARTIST_TABS[name]
            require(n[0] == 'tab_button' and n[2].get('text') == text, f'{name}: unexpected tab')
            n[2] = {('tr_text' if k == 'text' else k): (key if k == 'text' else v) for k, v in n[2].items()}
            if name == 'btn_album':
                n[2]['value'] = 'true'
            found.append(name)
        # tab_button loads before its pages sibling and can't sync it, so show the Albums view too.
        if n[0] == 'pages':
            require('value' not in n[2], 'Unexpected artist pages')
            n[2]['value'] = '1'
            found.append('pages')
    require(sorted(found) == sorted([*ARTIST_TABS, 'pages']), 'Unexpected artist tabs')


# Both variants. Coverflow's Home card: a clone of Local Music at index 2 with its own icon; its image
# (patch/coverflow.c binds it) is the click target. Stock translates label_* by name and ignores this one, so its text is literal.
HOME_PAGE = 'home_page.bin'


def home_card(root):
    menu = [n for n in root[3] if n[0] == 'slide_menu']
    require(len(menu) == 1, 'Unexpected home carousel')
    cards = [n[2].get('name') for n in menu[0][3]]
    require(cards[:2] == ['btn_playing', 'btn_localmusic'], 'Unexpected home cards')
    card = copy.deepcopy(menu[0][3][1])
    card[2]['name'] = 'btn_coverflow'
    image, label = card[3]
    require(image[2].get('name') == 'img_localmusic' and label[2].get('name') == 'label_localmusic',
            'Unexpected Local Music card')
    image[2]['name'] = 'img_coverflow'
    label[2]['name'] = 'label_coverflow'
    label[2]['text'] = 'Coverflow'
    for key, value in image[2].items():  # assets/menu_coverflow*.png, added to the rootfs by build.py
        if key.endswith(':bg_image'): image[2][key] = value.replace('menu_music', 'menu_coverflow')
    menu[0][3].insert(2, card)


# iPod only. Home becomes a list of the stock cards' names, in stock order with Coverflow third.
# home_page_init (0x523c84) looks up no widget: its widget_foreach visitor (0x5239b4) binds img_*
# clicks and translates label_* by name, and only img_left/img_right, gone here, reach the
# slide_menu. Each row's transparent image covers the row, on top of its label, so it takes the
# tap and is the row's click target for the wheel.
HOME_ROWS = ['playing', 'localmusic', 'coverflow', 'folder', 'stream', 'playset', 'sysset']


def ipod_home(root):
    require([n[0] for n in root[3]] == ['slide_menu', 'image', 'image'], 'Unexpected home carousel')
    require([n[2]['name'] for n in root[3][0][3]] == ['btn_' + r for r in HOME_ROWS if r != 'coverflow'],
            'Unexpected home cards')
    rows = []
    for i, name in enumerate(HOME_ROWS):
        # Translations longer than English's longest end in an ellipsis before the chevron.
        label = {'name': 'label_' + name, 'style': 's_scrlabel_white20l', 'only_focus': 'true', 'ellipses': 'true'}
        if name == 'coverflow':
            label['text'] = 'Coverflow'
        rows.append(['view', [0, i * HOME_ROW, HOME_LIST_W, HOME_ROW], {'name': 'btn_' + name}, [
            ['hscroll_label', [MARGIN, 0, HOME_LIST_W - MARGIN - HOME_LABEL_END, HOME_ROW], label, []],
            ['image', [0, 0, HOME_LIST_W, HOME_ROW], {'name': 'img_' + name, 'clickable': 'true'}, []]]])
    view = ['scroll_view', [0, 0, HOME_LIST_W, HOME_ROW * len(rows)],
            {'name': 'scroll_view_home', 'self_layout': 'default(x=0,y=0,w=100%,h=100%)'}, rows]
    root[3] = [
        ['list_view', [0, 0, HOME_LIST_W, HOME_ROW * len(rows)],
         {'name': 'list_view_home', 'item_height': str(HOME_ROW)}, [view]],
        ['image', HOME_ART_RECT, {'name': 'img_homeart', 'image': 'default_album_big', 'draw_type': 'scale_auto'}, []]]


def style_props(data):
    """Yield (widget, style, state, prop, value offset, value) for each property of an AWTK style file."""
    magic, _, count = struct.unpack_from('<3I', data)
    require(magic == 0xfafbfcfd, 'Unexpected AWTK style magic')
    for i in range(count):
        at, *names = struct.unpack_from('<I32s32s32s', data, 12 + 100*i)
        state, style, widget = (n.split(b'\0')[0].decode() for n in names)
        props, at = struct.unpack_from('<I', data, at)[0], at + 4
        for _ in range(props):
            _, key_len, size = struct.unpack_from('<BBH', data, at)
            prop, at = data[at+4:at+3+key_len].decode(), at + 4 + key_len
            yield widget, style, state, prop, at, data[at:at+size]
            at += size


def patch_style(data, audit):
    """Replace each edit's old value, same size, in the n states of widget/style that hold it."""
    require(hashlib.sha256(data).hexdigest() == audit['sha256'], 'Unaudited style file')
    out, props = bytearray(data), list(style_props(data))
    for widget, style, prop, old, new, n in audit['edits']:
        old, new = bytes.fromhex(old), bytes.fromhex(new)
        require(len(old) == len(new), f'{style}.{prop}: edit changes size')
        sites = [at for w, s, _, p, at, value in props if (w, s, p, value) == (widget, style, prop, old)]
        require(len(sites) == n, f'{style}.{prop}: expected {n} states with {old.hex()}, found {len(sites)}')
        for at in sites:
            out[at:at+len(new)] = new
    return bytes(out)


# iPod only. systembar_showface (0x52f610) finds every widget by name, recursively from the bar,
# and each second re-shows the volume, EQ, BT, synclink and Wi-Fi widgets and resets their text and
# images, but never their geometry. So widgets iPod hides move off-screen instead of going invisible.
# The volume number stays hidden: stock already opens dialog/volume_dialog on every wheel change.
STATUS_BAR = 'system_bar.bin'
STATUS_LEFT, STATUS_RIGHT = ['img_state'], ['label_eq', 'img_bt', 'img_wifi', 'img_battery']
STATUS_HIDDEN = ['img_vol', 'label_vol', 'img_synclink', 'label_battery']


def status_bar(root):
    left, right = root[3]
    require([left[2].get('name'), right[2].get('name')] == ['view_left', 'view_right'], 'Unexpected status bar')
    widgets = {n[2]['name']: n for n in left[3] + right[3]}
    require(sorted(widgets) == sorted(STATUS_LEFT + STATUS_RIGHT + STATUS_HIDDEN), 'Unexpected status bar widgets')
    left[3] = [widgets[n] for n in STATUS_LEFT]
    right[3] = [widgets[n] for n in STATUS_RIGHT]
    for view in (left, right):
        layout = view[2]['children_layout']
        require('xm=50,s=5)' in layout, 'Unexpected status bar layout')
        view[2]['children_layout'] = layout.replace('xm=50', f'xm={MARGIN}')
    extent = MARGIN + sum(n[1][2] for n in right[3]) + 5 * (len(right[3]) - 1)
    width = 375 - 2 * extent
    require(width >= TITLE_MIN and right[1][0] + right[1][2] == 375, 'Status bar title too narrow')
    for name in STATUS_HIDDEN:
        g = widgets[name][1]
        g[0], g[3] = -200, 30  # still updated by stock, drawn off-screen
        root[3].append(widgets[name])
    # The payload copies each page's title here (ringnav_paint_bg); a long one ends in an ellipsis.
    root[3].append(['hscroll_label', [extent, 0, width, 30], {
        'name': 'label_title', 'style': 's_scrlabel_white20c', 'only_focus': 'true', 'ellipses': 'true'}, []])


# iPod only. Stock finds every Now Playing widget by name, recursively, so they can move: title, artist
# and a new album label join the art on the slide_view's first page, so a swipe still swaps all of it for
# the lyrics or info page. Those keep their stock 225px column (stock creates 225px lyric lines),
# centred. The payload fills the label_ipod_* labels (ringnav_playing); label_playlen, the total, hides.
PLAYING_PAGE = 'playing_page.bin'


def playing_page(root):
    named = {n[2].get('name'): n for n in walk(root)}
    require([n[2].get('name') for n in root[3]] == [
        'view_buttons', 'scrlabel_title', 'scrlabel_artist', 'label_playtime', 'label_playlen',
        'slide_view_view', 'slider_play', 'img_repeata', 'img_repeatb', 'image_wait'], 'Unexpected Now Playing page')
    buttons, title, artist = root[3][:3]
    buttons[1] = [0, 0, 375, NP_TOP]
    named['img_return'][1][0] = -200  # the hardware Return, as on the pages whose navbars are hidden
    for i, name in enumerate(['img_fav', 'img_more', 'img_playmode']):
        n = named[name]
        n[1] = [375 - (3 - i) * NP_ICON, 0, NP_ICON, NP_TOP]
        n[2] = {k: v for k, v in n[2].items() if not k.endswith(('_offset', 'text_align_h'))}
        if 'image' in n[2]:
            n[2]['draw_type'] = 'center'
    buttons[3].append(['label', [MARGIN, 0, 375 - 3 * NP_ICON - MARGIN, NP_TOP], {
        'name': 'label_ipod_pos', 'style:normal:font_size': '16', 'style:normal:text_color': NP_GREY,
        'style:normal:text_align_h': 'left'}, []])

    art_y = (NP_SLIDE_H - NP_ART) // 2
    text_w = 375 - MARGIN - NP_TEXT_X
    top = art_y + NP_ART // 2 - (24 + 4 + 20 + 4 + 20) // 2  # the three lines centre on the art
    title[1] = [NP_TEXT_X, top, text_w, 24]
    title[2]['style'] = 's_scrlabel_white20l'
    artist[1] = [NP_TEXT_X, top + 28, text_w, 20]
    for key in artist[2]:
        if key.endswith(':text_color'): artist[2][key] = NP_GREY
        if key.endswith(':text_align_h'): artist[2][key] = 'left'
    album = copy.deepcopy(artist)
    album[1] = [NP_TEXT_X, top + 52, text_w, 20]
    album[2].update(name='label_ipod_album', text='')
    named['img_cover'][1] = [MARGIN, art_y, NP_ART, NP_ART]
    named['img_playstate'][1] = [MARGIN + (NP_ART - 120) // 2, art_y + (NP_ART - 120) // 2, 120, 120]
    named['view_album'][3] += [title, artist, album]
    column = (375 - 225) // 2
    named['label_lyricmsg'][1][0] += column
    named['view_lrc'][2]['self_layout'] = f'default(x={column},y=0,w=225,h=178)'
    for n in named['view_info'][3]:
        n[1][0] += column
    named['slide_view_view'][1] = [0, NP_TOP, 375, NP_SLIDE_H + 12]
    named['slide_view'][1] = [0, 0, 375, NP_SLIDE_H]
    dots = named['slide_indicator1']
    dots[1][1] = NP_SLIDE_H + 2
    dots[2]['self_layout'] = f'default(x=0,y={NP_SLIDE_H + 2},w=100%,h=10)'
    named['image_wait'][1] = [MARGIN + (NP_ART - 54) // 2, NP_TOP + art_y + (NP_ART - 54) // 2, 54, 54]

    # Colour fills (stock slider paint uses bg/fg_color when there is no image). The style has no
    # theme entry, so no thumb icon either: stock then fills exactly to the value, and slide_with_bar
    # keeps tap and drag seeking.
    slider = named['slider_play']
    x, y, w, h = NP_BAR
    slider[1] = [x, y - 11, w, h + 22]
    props = {k: v for k, v in slider[2].items() if not k.endswith((':bg_image', ':fg_image', ':icon', ':y_offset'))}
    for key in props:
        if key.endswith(':bg_color'): props[key] = NP_TRACK
        if key.endswith(':fg_color'): props[key] = NP_FILL
    props.update(style='s_ipod_progress', bar_size=str(h))
    slider[2] = props
    for name in ('img_repeata', 'img_repeatb'):
        named[name][1][0] = x
    times = y + h + 3
    total = named['label_playlen']
    remain = copy.deepcopy(total)
    remain[1] = [375 - MARGIN - 80, times, 80, 16]
    remain[2].update(name='label_ipod_remain', text='')
    total[2]['visible'] = 'false'
    named['label_playtime'][1] = [MARGIN, times, 80, 16]
    root[3][1:3] = []
    root[3].insert(3, remain)


# iPod only. Settings and Streaming keep the stock row height; only their navbar goes, as on the
# local pages. Tidal keeps its navbars: most hold a search button with no hardware equivalent.
NAVBAR_ONLY = AUDIT['navbar_only']


def patch_word(data, changes, address, old, new, purpose):
    off = fileoff(data, address)
    require(struct.unpack_from('<I', data, off)[0] == old, f'{address:#x}: unexpected instruction')
    struct.pack_into('<I', data, off, new)
    changes.append(dict(address=hex(address), original=hex(old), patched=hex(new), purpose=purpose))


def patch_asset(path, data, ipod):
    require(hashlib.sha256(data).hexdigest() == UI_ASSETS[path], f'{path}: unaudited UI asset')
    root = decode(data)
    require(encode(root) == data, f'{path}: UI round trip differs')
    if path == ARTIST_PAGE:
        artist_tabs(root)
    whole = {HOME_PAGE: ipod_home, STATUS_BAR: status_bar, PLAYING_PAGE: playing_page} if ipod else {HOME_PAGE: home_card}
    if path in whole:
        whole[path](root)
    if path in whole or not ipod:
        return encode(root)
    nav = [n for n in root[3] if n[2].get('name') == 'view_navbar']
    require(len(nav) == 1 and nav[0][1] in ([0, 0, 375, 50], [0, 0, 370, 50]), f'{path}: unexpected toolbar')  # 370: stream_page
    # Keep the widget (and callback lookups) alive. Children may be recreated by stock.
    nav[0][2]['visible'] = 'false'
    nav[0][2]['enable'] = 'false'
    for n in root[3]:
        if n is nav[0]:
            continue
        kind, g, props, _ = n
        if kind in ('list_view', 'table_view', 'tab_control'):
            require(g[1] in (50, 100), f'{path}: unexpected list position')
            g[1] -= 50
            g[3] = BOTTOM - g[1]
        elif props.get('name') == 'view_navbar_allplay':
            require(g == [0, 50, 375, 50], f'{path}: unexpected action bar')
            g[1] = 0
        elif kind == 'list_item':  # playlist editing actions
            g[1] = 10 + ((g[1] - 60) // 78) * PITCH
        elif props.get('name') == 'view':  # allmusic's stock empty-state panel
            g[1] -= 50
        elif path in NAVBAR_ONLY:  # settings panels and notes keep their size
            require(g[1] >= 50, f'{path}: unexpected content under the toolbar')
            g[1] -= 50
    if path in NAVBAR_ONLY:
        return encode(root)

    def rows(n, in_row=False):
        kind, g, props, children = n
        if path == 'localmusic/album_page.bin' and props.get('name') == 'button1':  # inline black grid buttons
            for key, value in props.items():
                if key.endswith(':bg_color') and value == '#000000':
                    props[key] = '#00000000'
        in_row = in_row or kind in ('list_item', 'table_row') and g[3] in (0, 78)
        for prop in ('row_height', 'default_item_height'):
            if props.get(prop) == '78':
                props[prop] = str(PITCH)
        if in_row:
            if kind in ('list_item', 'table_row') and g[3] == 78:
                g[3] = PITCH
            elif g[3] == 70:
                g[3] = BODY
            if g[1] in (11, 14, 21, 40, 41):
                # titles and metadata keep their stock centring: the body shrank by two pixels
                g[1] -= 1
            elif g[1] in (9, 10) and kind == 'image':
                g[1] = ART_INSET
        if path == ARTIST_PAGE:
            if kind == 'pages':
                require(props.get('self_layout') == 'default(x=0,y=40,w=100%,h=170)', 'Unexpected tabs layout')
                props['self_layout'] = f'default(x=0,y=40,w=100%,h={BOTTOM - 40})'
                g[3] = BOTTOM - 40
            if props.get('name') == 'list_view_album':
                g[3] = BOTTOM - 40
        for child in children:
            rows(child, in_row)
    rows(root)
    return encode(root)


def patch_code(data, symbols):
    changes = []
    word = functools.partial(patch_word, data, changes)

    for group in AUDIT['immediates']:
        value = {'pitch': PITCH, 'body': BODY, 'art': ART, 'art_inset': ART_INSET,
                 'scroll': BOTTOM - 50, 'np_bar_x': NP_BAR[0], 'np_bar_w': NP_BAR[2]}.get(group['value'], group['value'])
        for address, instruction in group['sites']:
            old = int(instruction, 16)
            word(int(address, 16), old, (old & 0xffff0000) | value, group['purpose'])
    group = AUDIT['row_layout_calls']
    for address, instruction in group['sites']:
        word(int(address, 16), int(instruction, 16),
             0x0c000000 | (symbols['compact_set_row_layout'] >> 2), group['purpose'])
    word(0x522410, 0x0320f809, 0, 'folder rebind retains the width owned by its row layouter')
    # Only the final long-Return call changes. All stock gates and its release guard precede it.
    word(0x4e8924, 0x04110fdf, 0x0c000000 | (symbols['compact_now_playing'] >> 2),
         'long Return destination after stock input gates')
    # home_page_init's memory-play resume opens Now Playing; outside car mode it runs the page's player_start alone.
    word(0x523de0, 0x0320f809, 0x0c000000 | (symbols['ringnav_boot'] >> 2),
         'boot resume restores the queue paused and stays on Home')
    return changes
