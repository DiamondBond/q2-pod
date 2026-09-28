"""Build-time edits for the SHA-pinned local browsing assets and native call sites.

No global widget hook: excluded pages and shared UI styles stay byte-identical.
The audit records full original instructions and asset hashes, not search/replace patterns.
"""
import copy
import functools
import hashlib
import json
import pathlib
import struct
from build import check as require, fileoff

AUDIT = json.loads((pathlib.Path(__file__).resolve().parents[1]/'patch/compact.json').read_text())
# The app window is the 375x320 screen minus the 30px status bar, so a 290px list holds four
# 72px rows. The stock 52px artwork is drawn 1:1 (no rescaling) with an 8px inset inside the
# 68px row body. Rows keep the row layout's eight-pixel left margin for the artwork.
BOTTOM = 290
PITCH = 72
BODY = PITCH - 4
ART = 52
ART_INSET = (BODY - ART) // 2


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

    def walk(n):
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
        for child in n[3]:
            walk(child)
    walk(root)
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


def patch_word(data, changes, address, old, new, purpose):
    off = fileoff(data, address)
    require(struct.unpack_from('<I', data, off)[0] == old, f'{address:#x}: unexpected instruction')
    struct.pack_into('<I', data, off, new)
    changes.append(dict(address=hex(address), original=hex(old), patched=hex(new), purpose=purpose))


def patch_asset(path, data, ipod):
    require(hashlib.sha256(data).hexdigest() == AUDIT['assets'][path], f'{path}: unaudited UI asset')
    root = decode(data)
    require(encode(root) == data, f'{path}: UI round trip differs')
    if path == ARTIST_PAGE:
        artist_tabs(root)
    if path == HOME_PAGE:
        home_card(root)
        return encode(root)
    if not ipod:
        return encode(root)
    nav = [n for n in root[3] if n[2].get('name') == 'view_navbar']
    require(len(nav) == 1 and nav[0][1] == [0, 0, 375, 50], f'{path}: unexpected toolbar')
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

    def rows(n, in_row=False):
        kind, g, props, children = n
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
                 'scroll': BOTTOM - 50}.get(group['value'], group['value'])
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
    return changes
