#!/usr/bin/env python3
"""Reproducibly patch only the audited Q2 V1.32 ZIP. Requires LLVM and squashfs-tools, and ImageMagick for --ipod.

--logo swaps the boot splash JPEG (320x375); it defaults to assets/logo.jpg.
"""
import argparse, hashlib, io, json, pathlib, re, shlex, struct, subprocess, tarfile, zipfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
ZIP_SHA = '154c17822d09be001be35c03d2d3488424dee195221790bd70864480d55b0f00'
DEMO_SHA = '2c5f06142850b4fc168f82b44a81550cce0a5b4b9fe1c179dced4a08a3049138'
VERSION = '5.8'  # the only place a release bumps the version
VERSIONS = {'normal': f'V{VERSION}R', 'ipod': f'V{VERSION}I'}
# --dev: lowercase tag, never equal to a release, so the updater accepts either over the other
DEV_VERSIONS = {'normal': f'V{VERSION}r', 'ipod': f'V{VERSION}i'}
BASE = 0xb00000
SCRATCH = 0xb20000
RING_STEP = 48
HOOKS = {
    'on_wm_keyup_before_fun': (0x4e85c8, 'ringnav'),
    'on_wm_tsdown_before_fun': (0x4e8bd0, 'ringnav_touch'),
    'widget_on_paint_border': (0x6596a0, 'ringnav_paint'),
    'widget_dispatch': (0x65e0ec, 'ringnav_dispatch'),
    'on_wm_keylong_fun': (0x4e873c, 'ringnav_keylong'),
    'playset_equalizer_page_init': (0x4b642c, 'peq_page_init'),
    'set_equalizer_value': (0x4f9230, 'peq_stock_eq'),
    'home_page_init': (0x523c84, 'coverflow_home'),
}
# Hooked in iPod builds only, so normal keeps these entry points stock.
IPOD_HOOKS = {'widget_on_paint_background': (0x65c77c, 'ringnav_paint_bg'),
              'playing_page_init': (0x52ca88, 'ringnav_playing'),
              'systemset_display_page_init': (0x4c1d04, 'ringnav_display'),
              'style_get_color': (0x649f6c, 'ringnav_style_color'),
              'image_manager_add': (0x6445d4, 'ringnav_image_add')}
# iPod: style_get_gradient has no PIC prologue. It is a leaf that null-checks the style and its
# vtable, then tail-calls get_gradient (+0x18); its first two words (beqz a0; nop) become the jump
# and the payload does the whole of it. The third word is pinned too, so the layout is the audited one.
IPOD_LEAF = ('style_get_gradient', 0x649f3c, 'ringnav_style_gradient', (0x10800009, 0, 0x8c820000))
# The byte in bluealsa's AAC capability holding the 44.1 kHz bit; see docs/internals.md.
BLUEALSA = 'usr/bin/bluealsa'
BLUEALSA_SHA = '0a4ffb7cc8207a46a3568440c5f31022b7125befd164e2f1af52537340a9892a'
AAC_44K1 = 0x317b8
# mclNextSong's shuffle pick; the payload calls the stock pick, then applies a pending Play next.
SHUFFLE_CALL = (0x5addf0, 0x0411e8cb)  # bal mcl_shuffle_pick; its delay slot (a0=1) stays

def run(*args):
    return subprocess.check_output([str(a) for a in args], text=True)
def sha(b): return hashlib.sha256(b).hexdigest()

def source_sha256():
    """Hash every build input, so a test run cannot silently use a stale output directory."""
    h = hashlib.sha256()
    tools = [ROOT/'tools'/f for f in ('build.py', 'compact.py', 'peq.py', 'release.py')]
    for path in sorted([*ROOT.glob('assets/*'), *ROOT.glob('patch/*'), *tools]):
        h.update(str(path.relative_to(ROOT)).encode() + b'\0')
        h.update(path.read_bytes())
    return h.hexdigest()

def check(condition, message):
    if not condition: raise ValueError(message)
def jpeg_size(b):
    """Validate the splash's supported JPEG frame header and return its dimensions."""
    check(b[:2] == b'\xff\xd8', 'Logo must be a JPEG')
    i = 2
    while i < len(b):
        check(b[i] == 0xFF, 'Malformed JPEG')
        while i < len(b) and b[i] == 0xFF: i += 1
        check(i < len(b), 'Truncated JPEG marker')
        marker = b[i]
        i += 1
        if marker in (0xD9, 0xDA): break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7: continue
        check(marker not in (0, 0xD8), 'Malformed JPEG marker')
        check(i + 2 <= len(b), 'Truncated JPEG segment')
        size = struct.unpack_from('>H', b, i)[0]
        check(size >= 2 and i + size <= len(b), 'Invalid JPEG segment length')
        if marker in (0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF):
            check(size >= 8 and size == 8 + 3 * b[i+7], 'Invalid JPEG frame length')
            # Stock display_logo indexes decoded pixels as RGB triples (0x400ec0 onward),
            # but leaves libjpeg's output color space unchanged. Grayscale/CMYK are unsafe.
            check(marker == 0xC0 and b[i+2] == 8 and b[i+7] == 3,
                  'Logo must be an 8-bit, three-component baseline JPEG (not grayscale/CMYK)')
            h, w = struct.unpack_from('>HH', b, i+3)
            check(w > 0 and h > 0, 'Invalid JPEG dimensions')
            return w, h
        i += size
    raise ValueError('No JPEG size marker')
def symbols(p, table=None):
    out = {}
    for line in (table or run('readelf', '-Ws', p)).splitlines():
        s = line.split()
        if len(s) >= 8 and s[0].endswith(':'):
            try: out[s[7]] = int(s[1], 16)
            except ValueError: pass
    return out

def segments(b):
    phoff = struct.unpack_from('<I', b, 28)[0]
    size, num = struct.unpack_from('<HH', b, 42)
    check(size == 32, 'Unexpected ELF program header size')
    return [(phoff+i*size, struct.unpack_from('<8I', b, phoff+i*size)) for i in range(num)]
def fileoff(b, a):
    for _, (t, o, v, _, f, _, _, _) in segments(b):
        if t == 1 and v <= a < v+f: return o+a-v
    raise ValueError(f'Unmapped address {a:x}')

FUNCTIONS = {
 'widget_on': ('unsigned', 'void *, unsigned, int (*)(void *, void *), void *'),
 'widget_set_visible': ('int', 'void *, int, int'),
 'widget_set_enable': ('int', 'void *, int'),
 'widget_set_text_utf8': ('int', 'void *, const char *'),
 'widget_use_style': ('int', 'void *, const char *'),
 'widget_set_name': ('int', 'void *, const char *'),
 'widget_set_sensitive': ('int', 'void *, int'),
 'widget_to_local': ('int', 'void *, void *'),
 'widget_dispatch_event_to_target_recursive': ('int', 'void *, void *'),
 'label_create': ('void *', 'void *, int, int, int, int'),
 'stock_search': ('int', 'void *, void *'),
 'widget_set_children_layout': ('int', 'void *, const char *'),
 'widget_resize': ('int', 'void *, int, int'),
 'widget_lookup': ('void *', 'void *, const char *, int'),
 'scroll_bar_scroll_to': ('int', 'void *, int, unsigned'),
 'navigator_back_to_home': ('int', 'void'),
 'navigator_switch_to_with_context': ('int', 'const char *, const void *, int'),
 'window_manager': ('void *', 'void'),
 'window_manager_get_top_window': ('void *', 'void *'),
 'window_manager_is_animating': ('int', 'void *'),
 'window_manager_get_pointer_pressed': ('int', 'void *'),
 'widget_get_visible': ('int', 'void *'),
 'widget_get_prop_bool': ('int', 'void *, const char *, int'),
 'widget_get_prop_int': ('int', 'void *, const char *, int'),
 'widget_get_prop_str': ('const char *', 'void *, const char *, const char *'),
 'widget_get_text': ('const unsigned *', 'void *'),
 'widget_set_text': ('int', 'void *, const unsigned *'),
 'widget_set_tr_text': ('int', 'void *, const char *'),
 'widget_get_type': ('const char *', 'void *'),
 'widget_count_children': ('unsigned', 'void *'),
 'widget_get_child': ('void *', 'void *, unsigned'),
 'widget_set_prop_int': ('int', 'void *, const char *, int'),
 'widget_invalidate_force': ('int', 'void *, void *'),
 'widget_animator_start': ('int', 'void *'),
 'widget_animator_scroll_set_params': ('int', 'void *, int, int, int, int'),
 'slide_menu_set_value': ('int', 'void *, int'),
 'slide_menu_item_width': ('int', 'void *'),
 'slide_menu_on_scroll_done': ('int', 'void *, void *'),
 'slide_menu_scroll_to': ('int', 'void *, int'),
 'widget_animator_scroll_create': ('void *', 'void *, unsigned, unsigned, int'),
 'widget_animator_on': ('unsigned', 'void *, unsigned, int (*)(void *, void *), void *'),
 'widget_set_focused': ('int', 'void *, int'),
 'widget_animator_pause': ('int', 'void *'),
 'widget_animator_destroy': ('int', 'void *'),
 'widget_ungrab': ('int', 'void *, void *'),
 'canvas_get_clip_rect': ('int', 'void *, void *'),
 'canvas_set_clip_rect': ('int', 'void *, const void *'),
 'canvas_set_fill_color': ('int', 'void *, unsigned'),
 'canvas_set_stroke_color': ('int', 'void *, unsigned'),
 'canvas_stroke_rect': ('int', 'void *, int, int, int, int'),
 'canvas_fill_rect': ('int', 'void *, int, int, int, int'),
 'canvas_draw_icon': ('int', 'void *, void *, int, int'),
 'canvas_set_font': ('int', 'void *, const char *, unsigned'),
 'canvas_set_text_color': ('int', 'void *, unsigned'),
 'canvas_draw_text_in_rect': ('int', 'void *, const unsigned *, unsigned, const void *'),
 'canvas_fill_rounded_rect': ('int', 'void *, const void *, const void *, const void *, unsigned'),
 'canvas_stroke_rounded_rect': ('int', 'void *, const void *, const void *, const void *, unsigned, unsigned'),
 'pointer_event_init': ('void *', 'void *, int, void *, int, int'),
 'time_now_ms': ('unsigned', 'void'),
 'timer_add': ('unsigned', 'int (*)(const void *), void *, unsigned'),
 'timer_remove': ('int', 'unsigned'),
 'tk_strcmp': ('int', 'const char *, const char *'),
 'slide_menu_scroll_to_next': ('int', 'void *'),
 'slide_menu_scroll_to_prev': ('int', 'void *'),
 'table_client_stop_animator_scroll': ('int', 'void *'),
 'table_client_set_yoffset': ('int', 'void *, int'),
 'scroll_view_set_offset': ('int', 'void *, int, int'),
 'table_client_scroll_to': ('int', 'void *, int'),
 'scroll_view_scroll_delta_to': ('int', 'void *, int, int, int'),
 'widget_destroy_children': ('int', 'void *'),
 'list_item_create': ('void *', 'void *, int, int, int, int'),
 'hscroll_label_create': ('void *', 'void *, int, int, int, int'),
 'set_hscroll_label_attribute': ('void', 'void *'),
 'widget_off_by_func': ('int', 'void *, unsigned, void *, void *'),
 'window_close': ('int', 'void *'),
 'navigator_to': ('int', 'const char *'),
 'navigator_to_with_context': ('int', 'const char *, const void *'),
 'window_manager_get_input_device_status': ('char *', 'void *'),
 'airplayGetFlag': ('int', 'void'),
 'tk_snprintf': ('int', 'char *, unsigned, const char *, ...'),
 'toolsTimeItoa': ('int', 'char *, int'),
 'getMusicByAlbum': ('int', 'const char *'),
 'getMusicByAlbumAndSonger': ('int', 'const char *, const char *, int'),
 'getMusicByAlbumAndAlbumSonger': ('int', 'const char *, const char *, int'),
 'toolsLoadDirectory': ('int', 'const char *'),
 'mclLoadPlayList': ('int', 'void *, int, int'),
 'mcl_shuffle_pick': ('int', 'int'),
 'getAllAlbum': ('int', 'void'),
 'toolsThumbSpecCover': ('int', 'const char *, const char *, int, int'),
 'toolsGetAlbumCover': ('int', 'const char *, const char *, int, int'),
 'window_create': ('void *', 'void *, int, int, int, int'),
 'widget_factory': ('void *', 'void'),
 'widget_factory_create_widget': ('void *', 'void *, const char *, void *, int, int, int, int'),
 'image_create': ('void *', 'void *, int, int, int, int'),
 'image_set_draw_type': ('int', 'void *, int'),
 'image_base_set_image': ('int', 'void *, const char *'),
 'widget_load_image': ('int', 'void *, const char *, void *'),
 'widget_unload_image': ('int', 'void *, void *'),
 'list_view_create': ('void *', 'void *, int, int, int, int'),
 'scroll_view_create': ('void *', 'void *, int, int, int, int'),
 'navigator_back': ('int', 'void'),
 'write_int_config': ('int', 'int, const char *, const char *'),
 'toolsReadConfig': ('int', 'const char *, const char *, const char *, char *, const char *'),
 'button_create': ('void *', 'void *, int, int, int, int'),
 'widget_move_resize': ('int', 'void *, int, int, int, int'),
 'tk_str_end_with': ('int', 'const char *, const char *'),
 'image_manager': ('void *', 'void'),
 'image_manager_unload_all': ('int', 'void *'),
 'bitmap_get_line_length': ('unsigned', 'void *'),
 'bitmap_lock_buffer_for_write': ('unsigned char *', 'void *'),
 'bitmap_unlock_buffer': ('int', 'void *'),
 # Coverflow depth (coverflow.c): its frame bitmap, reading decoded covers, and the slide_menu stride
 'bitmap_create_ex': ('void *', 'unsigned, unsigned, unsigned, unsigned'),
 'bitmap_destroy': ('int', 'void *'),
 'bitmap_lock_buffer_for_read': ('const unsigned char *', 'void *'),
 'canvas_draw_image': ('int', 'void *, void *, const void *, const void *'),
 'slide_menu_set_spacer': ('int', 'void *, int'),
 'playing_timer_start': ('int', 'void *'),
 'playing_timer_clear': ('int', 'void *'),
 'player_seek_time': ('int', 'int'),
 'player_start': ('int', 'void *, int, int, int'),
}
# Local stock routines in the SHA-256-pinned V1.32 executable.
PRIVATE_FUNCTIONS = {
    "stock_search": 0x5241c4,
    "slide_menu_item_width": 0x5f3040,
    "slide_menu_on_scroll_done": 0x5f3654,
    "slide_menu_scroll_to": 0x5f3400,
    "mcl_shuffle_pick": 0x5a8120,
}
GLOBALS = ['g_backlight_status', 'g_lockscreen_pageflag', 'g_testmode_flag',
           'g_guideflag', 'g_poweroff_state', 'g_usblink_status', 'bt__recv_pageflag',
           'g_power_longkey', 'g_ingore_bootkey_flag', 'g_equalizer_flag', 'g_navbar_status', 'g_playcover_type']
# Audited stock browsing state, deque pointers, art locks, the status bar widget
# (system_bar_init stores it) and the playing cover's track path; sizes are checked against the ELF.
CONTEXT_DATA = {'g_folder_path': 1024, 'g_class_type': 4,
                'g_local_classinfo_save': 912, 'g_artist_type': 4, 'album_modetype': 4,
                'p_deque_showlist': 4, 'tools_pdeq_directory': 4, 'mcl_pdeqplaylist': 4,
                'parse_cover_mutex': 24, 'g_playcover_mutex': 24, 'system_bar': 4, 'g_lastcover_url': 1024}
# Windows the payload creates at runtime (window_create), so no rootfs asset names them.
PAYLOAD_WINDOWS = {'coverflow_page'}
ICONS = ['menu_coverflow.png', 'menu_coverflowdown.png']
# The stock EQ preset page and the images only it and the stock equalizer page show: the PEQ
# editor clears that page's widgets on init and never binds the preset button, so none can load.
STOCK_EQ = ['release/assets/default/raw/ui/playset/preseteq_page.bin'] + [
    f'release/assets/default/raw/images/xx/{n}.png' for n in
    ['eq_bg', 'eq_off', 'eq_sidebg', 'eqbox'] + [f'eq_{p}{s}' for p in
    ('blues', 'classical', 'custon', 'dance', 'jazz', 'metal', 'pop', 'rock', 'scene') for s in ('', '_select')]]
# iPod: the Home carousel's card and arrow images; only the stock home_page.bin names them.
CAROUSEL = [f'release/assets/default/raw/images/xx/menu_{n}.png' for n in
    [*(c + s for c in ('playing', 'music', 'folder', 'stream', 'playset', 'sysset') for s in ('', 'down')), 'left', 'right']]

FLAGS = ['--target=mipsel-linux-gnu','-march=mips32r2','-mabi=32','-mfp64',
         '-mno-abicalls','-fno-pic','-G0','-ffreestanding','-fno-builtin',
         '-fno-stack-protector','-fno-unwind-tables','-fno-asynchronous-unwind-tables',
         '-Oz','-Wall','-Wextra','-Werror']

def hooks(ipod): return HOOKS | IPOD_HOOKS if ipod else HOOKS

def compile_payload(out, ipod=False):
    """Compile and link the payload."""
    from peq import compile_common
    extra = compile_common(out, out/'stock-demo', ipod=ipod)  # also writes the libc/libcstl imports ringnav.c uses
    run('clang',*FLAGS,f'-DIPOD={int(ipod)}','-I',out,'-c',ROOT/'patch/ringnav.c','-o',out/'ringnav.o')
    run('clang',*FLAGS,'-c',ROOT/'patch/trampoline.S','-o',out/'trampoline.o')
    run('ld.lld','-m','elf32ltsmip','--gc-sections','-T',ROOT/'patch/link.ld','-e','ringnav',
        *[f'--undefined={name}' for _, name in hooks(ipod).values()], *[f'--undefined={IPOD_LEAF[2]}'] * ipod,
        out/'ringnav.o',out/'trampoline.o',*extra,'-o',out/'patch.elf')
    run('llvm-objcopy','-O','binary',out/'patch.elf',out/'patch.bin')
    return symbols(out/'patch.elf')

def append_payload(image, payload, base, memsz, flags, label):
    """Map payload at base through the image's final PT_NULL header."""
    nulls = [(o,p) for o,p in segments(image) if p[0] == 0]
    check(len(nulls) == 1 and nulls[0][0] == segments(image)[-1][0], f'{label}: no final PT_NULL slot')
    check(all(p[2]+p[5] < base for _,p in segments(image) if p[0] == 1), f'{label}: payload mapping overlaps')
    off = (len(image)+65535)&~65535
    image.extend(bytes(off-len(image)))
    image.extend(payload)
    struct.pack_into('<8I',image,nulls[0][0],1,off,base,base,len(payload),memsz,flags,65536)

def patch_bluealsa(raw):
    """Offer AAC at 48 kHz only. A headset that opens the stream itself (AirPods out of the case)
    picks 44.1 kHz, and bluealsa, still fed 48 kHz, drops about 8% of the AAC frames."""
    check(sha(raw) == BLUEALSA_SHA, 'Unsupported bluealsa binary')
    return raw[:AAC_44K1] + b'\0' + raw[AAC_44K1+1:]

def build(zip_path, out, logo, ipod=False, dev=False):
    variant = 'ipod' if ipod else 'normal'
    version = (DEV_VERSIONS if dev else VERSIONS)[variant]
    out.mkdir(parents=True, exist_ok=True)
    check(not (out/'update.tar').exists(), 'Output already exists; use a fresh --out directory')
    source = source_sha256()
    raw = zip_path.read_bytes()
    check(sha(raw) == ZIP_SHA, 'Unsupported ZIP: SHA-256 differs from audited original')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        tarbytes = z.read('Q2 Firmware V1.32/update.tar')
    with tarfile.open(fileobj=io.BytesIO(tarbytes)) as t:
        meta = t.getmembers()
        check([m.name for m in meta] == ['firmware_v20.info','recovery-update',
              'recovery-update/xImage','recovery-update/rootfs.squashfs'], 'Unexpected package members')
        blobs = {m.name:t.extractfile(m).read() for m in meta if m.isfile()}
    info = blobs['firmware_v20.info'].decode().splitlines()
    check(info[:2] == ['Shanling Q2','V1.32'], 'Wrong model/version')
    for line in info[2:]:
        digest, name = line.split()
        check(hashlib.md5(blobs[name]).hexdigest() == digest, 'Stock MD5 mismatch')
    sq = out/'stock.squashfs'; sq.write_bytes(blobs['recovery-update/rootfs.squashfs'])
    raw_demo = subprocess.check_output(['unsquashfs','-cat',str(sq),'release/bin/demo'])
    check(sha(raw_demo) == DEMO_SHA, 'Unsupported demo binary')
    # Every allowlisted context must be a window name. The runtime name is the root "name"
    # property of the UI asset, not the asset path, so check the stock rootfs assets directly:
    # a prefix-trimmed typo cannot silently disable a screen this way.
    from compact import (AUDIT, ARTIST_ALBUMS, ARTIST_PAGE, HOME_PAGE, INC, SETTINGS_ICONS, UI_ASSETS, patch_asset,
                         imagemagick, patch_code, patch_style, patch_word, settings_icon)
    contexts = re.findall(r'"([^"]+)"', (ROOT/'patch/contexts.inc').read_text())
    check(contexts, 'No navigation contexts audited')
    windows = set()
    for line in run('unsquashfs', '-l', sq).splitlines():
        found = re.search(r'/raw/ui/(.+)\.bin$', line)
        if not found: continue
        rel = found.group(1)
        data = subprocess.check_output(['unsquashfs', '-cat', str(sq),
                                        'release/assets/default/raw/ui/'+rel+'.bin'])
        i = data.find(b'name\x00')
        name = data[i+5:data.find(b'\x00', i+5)].decode('utf-8', 'replace') if i >= 0 else ''
        windows.add(name or rel.split('/')[-1])
        # iPod pre-sizes the settings icons, so no UI asset may name one (only native settings code does).
        for icon in SETTINGS_ICONS:
            check(icon.removesuffix('.png').encode() + b'\0' not in data, f'{rel}: names settings icon {icon}')
    check(windows, 'No UI assets in the stock rootfs')
    for name in contexts:
        check(name in windows | PAYLOAD_WINDOWS, f'Context {name} is not a window name in the stock rootfs')
    demo = out/'stock-demo'; demo.write_bytes(raw_demo)
    symbol_table = run('readelf', '-Ws', demo)
    syms = symbols(demo, symbol_table)
    syms.update(PRIVATE_FUNCTIONS)
    header = [f'#define RING_STEP {RING_STEP}']
    for name in GLOBALS:
        check(re.search(rf'\b1\s+OBJECT\s+GLOBAL\s+DEFAULT\s+\d+\s+{name}$',
                        symbol_table, re.M), f'{name}: byte global size mismatch')
    for name, size in CONTEXT_DATA.items():
        check(re.search(rf'\b{size}\s+OBJECT\s+GLOBAL\s+DEFAULT\s+\d+\s+{name}$',
                        symbol_table, re.M), f'{name}: context data size mismatch')
        header.append(f'#define {name} ((const unsigned char *)0x{syms[name]:x}u)')
    # iPod's image hook leaves the settings icons' category colours alone (ringnav.c settings_icon).
    names = ''.join(n.removesuffix('.png') + '\\0' for n in AUDIT['settings_icons'])
    header.append(f'#define SETTINGS_ICON_NAMES "{names}"')
    (out/'stock.h').write_text('\n'.join(header)+'\n')
    ps = compile_payload(out, ipod)
    payload = (out/'patch.bin').read_bytes()
    check(len(payload) < SCRATCH-BASE, 'Payload overlaps its scratch page')
    check(ps['__scratch_start'] == SCRATCH, 'Scratch state moved')
    check(ps['__scratch_end'] <= SCRATCH + 0x10000, 'Scratch state exceeds its page')
    patched = bytearray(raw_demo)
    def jump(off, name): patched[off:off+8] = struct.pack('<II', 0x08000000 | (ps[name] >> 2), 0)
    for name, (address, replacement) in hooks(ipod).items():
        check(syms[name] == address, f'{name}: callback address mismatch')
        off = fileoff(patched, address)
        prolog = struct.unpack_from('<III', patched, off)
        check(prolog[0] >> 16 == 0x3c1c and prolog[1] >> 16 == 0x279c and
              prolog[2] == 0x0399e021, f'{name}: unexpected PIC prologue')
        low = prolog[1] & 65535
        gp = ((prolog[0] & 65535) << 16) + (low if low < 32768 else low - 65536) + address
        check(gp == 0xa26cc0, f'{name}: unexpected GOT base')
        jump(off, replacement)
    if ipod:
        name, address, replacement, words = IPOD_LEAF
        off = fileoff(patched, address)
        check(syms[name] == address and struct.unpack_from('<III', patched, off) == words, f'{name}: unexpected code')
        # style_get_color's own bal style_get_gradient, returning to STYLE_COLOR_GRADIENT_RET, stays unmapped.
        ret = int(re.search(r'#define STYLE_COLOR_GRADIENT_RET (0x\w+)', INC)[1], 16)
        check(struct.unpack_from('<I', patched, fileoff(patched, ret - 8))[0] == 0x04110000 | (address - ret + 4) >> 2 & 0xffff,
              'style_get_color: unexpected gradient call')
        jump(off, replacement)
    from peq import patch_player
    raw_player = subprocess.check_output(['unsquashfs', '-cat', str(sq), 'usr/bin/hciplayer'])
    audio = patch_player(raw_player, out/'peq')
    bluealsa = patch_bluealsa(subprocess.check_output(['unsquashfs', '-cat', str(sq), BLUEALSA]))
    (out/'bluealsa').write_bytes(bluealsa)
    for address, old, new in ARTIST_ALBUMS:
        patch_word(patched, [], address, old, new, 'artist detail opens on Albums')
    patch_word(patched, [], *SHUFFLE_CALL, 0x0c000000 | (ps['ringnav_shuffle'] >> 2),
               'shuffle honours Play next')
    # Pin added private entry points as well as every replaced instruction, and the stock bitmap,
    # canvas and slide_menu entries Coverflow's depth renderer calls (docs/internals.md#coverflow-depth).
    for name, original in (AUDIT['private_prologues'] | AUDIT['coverflow_prologues']).items():
        off = fileoff(raw_demo, syms[name])
        check(raw_demo[off:off+12].hex() == original, f'{name}: unexpected stock entry')
    for address, original in AUDIT['event_abi_words'].items():
        off = fileoff(raw_demo, int(address, 16))
        check(raw_demo[off:off+4].hex() == original, f'{address}: unexpected event ABI instruction')
    code_changes = []
    if ipod:
        code_changes = patch_code(patched, ps)
    # Single shared version literal: About display and updater equality check.
    check(patched.count(b'V1.32\0') == 1, 'Version literal is not unique')
    check(len(version) + 1 == len(b'V1.32\0'),
          'VERSION must stay 5 characters; a longer literal shifts every later file offset')
    patched = patched.replace(b'V1.32\0', version.encode()+b'\0')
    append_payload(patched, payload, BASE, ps['__scratch_end']-BASE, 7, 'demo')
    (out/'demo').write_bytes(patched)
    # Pseudo-file round trip preserves every original inode's metadata and hardlinks.
    pseudo = out/'root.pseudo'
    run('unsquashfs','-pf',pseudo,sq)
    p = pseudo.read_bytes()
    # mksquashfs takes "/" from the source dir, not the pseudo file; carry stock values over.
    root = re.search(rb'^/ D (\d+) (\d+) (\d+) (\d+)$',p,re.M)
    check(root is not None, 'Missing root pseudo inode')
    t,mode,uid,gid = (x.decode() for x in root.groups())
    rootargs = ['-root-time',t,'-root-mode',mode,'-root-uid',uid,'-root-gid',gid]
    # Paths are passed through a shell by mksquashfs F entries; quote them explicitly.
    def swap_inode(p, path, src):
        line = re.search(rb'^'+re.escape(path)+rb' R (\d+) (\d+) (\d+) (\d+) .+$',p,re.M)
        check(line is not None, f'Missing {path.decode()} pseudo inode')
        return p[:line.start()]+path+b' F '+b' '.join(line.groups())+b' cat '+shlex.quote(str(src)).encode()+p[line.end():]
    p = swap_inode(p, b'release/bin/demo', out/'demo')
    p = swap_inode(p, b'usr/bin/hciplayer', out/'peq/hciplayer')
    p = swap_inode(p, BLUEALSA.encode(), out/'bluealsa')
    logo_data = logo.read_bytes()
    check(jpeg_size(logo_data) == (320, 375), 'Logo must be 320x375 like the stock splash')
    # Package exactly the validated bytes, even if the input is edited during compression.
    logo = out/'logo.jpg'
    logo.write_bytes(logo_data)
    p = swap_inode(p, b'release/assets/default/raw/images/xx/logo.jpg', logo)
    # Normal's Coverflow card icons are the only new inodes; they copy menu_music's metadata.
    added = []
    for name in [] if ipod else ICONS:
        stock = re.search(rb'^release/assets/default/raw/images/xx/'+name.replace('coverflow','music').encode()+rb' R (\d+) (\d+) (\d+) (\d+) .+$',p,re.M)
        check(stock is not None, f'Missing stock icon for {name}')
        path = b'release/assets/default/raw/images/xx/'+name.encode()
        (out/name).write_bytes((ROOT/'assets'/name).read_bytes())  # package the hashed bytes, as the logo
        entry = path+b' F '+b' '.join(stock.groups())+b' cat '+shlex.quote(str(out/name)).encode()+b'\n'
        at = p.index(b'# START OF DATA')  # definitions precede the embedded data
        p = p[:at]+entry+p[at:]
        added.append([path, b'R', *stock.groups()])
    removed = []
    for path in STOCK_EQ + (CAROUSEL if ipod else []):
        line = re.search(rb'^'+re.escape(path.encode())+rb' R .+\n', p, re.M)
        check(line is not None, f'Missing stock inode {path}')
        removed.append(line.group().split()[:6])
        p = p[:line.start()]+p[line.end():]
    changed_assets = {}
    assets = ['ui/'+rel for rel in (UI_ASSETS if ipod else [ARTIST_PAGE, HOME_PAGE])]
    if ipod:
        assets += ['styles/'+rel for rel in AUDIT['styles']]
    for rel in assets:
        path = 'release/assets/default/raw/' + rel
        original = subprocess.check_output(['unsquashfs', '-cat', str(sq), path])
        kind, name = rel.split('/', 1)
        data = patch_style(original, AUDIT['styles'][name]) if kind == 'styles' else patch_asset(name, original, ipod)
        target = out/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        p = swap_inode(p, path.encode(), target)
        changed_assets[path] = dict(original_sha256=sha(original), sha256=sha(data))
    # iPod: settings icons pre-sized to the rows' SET_ICON, in place, so each keeps its inode metadata.
    for name in SETTINGS_ICONS if ipod else []:
        path = 'release/assets/default/raw/images/xx/' + name
        original = subprocess.check_output(['unsquashfs', '-cat', str(sq), path])
        data = settings_icon(name, original)
        target = out/'images'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        p = swap_inode(p, path.encode(), target)
        changed_assets[path] = dict(original_sha256=sha(original), sha256=sha(data))
    pseudo.write_bytes(p)
    (out/'empty').mkdir()
    newsq = out/'rootfs.squashfs'
    epoch = struct.unpack_from('<I',sq.read_bytes(),8)[0]
    run('mksquashfs',out/'empty',newsq,'-pf',pseudo,'-noappend','-comp','lzo',
        '-b','131072','-Xcompression-level','9','-mkfs-time',epoch,*rootargs,'-processors','1','-no-progress')
    # All inodes, including demo and the logo, keep name/type/mtime/mode/uid/gid (sizes/offsets shift).
    def inodes(image):
        text = subprocess.check_output(['unsquashfs','-pf','-',str(image)]).split(b'\n# START OF DATA')[0]
        return sorted(l.split()[:6] for l in text.splitlines() if l and not l.startswith(b'#'))
    check(inodes(newsq) == sorted([i for i in inodes(sq) if i not in removed]+added),
          'Repacked rootfs metadata differs from stock')
    blobs['recovery-update/rootfs.squashfs'] = newsq.read_bytes()
    # Stock image proves this size fits; do not enlarge beyond its padded size.
    check(len(blobs['recovery-update/rootfs.squashfs']) <= sq.stat().st_size, 'Repacked rootfs exceeds stock size')
    blobs['firmware_v20.info'] = (f'Shanling Q2\n{version}\n'+''.join(
        hashlib.md5(blobs[n]).hexdigest()+'  '+n+'\n' for n in [
            'recovery-update/xImage','recovery-update/rootfs.squashfs'])).encode()
    with tarfile.open(out/'update.tar','w',format=tarfile.GNU_FORMAT) as t:
        for m in meta:
            data = blobs.get(m.name)
            if data is not None: m.size=len(data)
            t.addfile(m,io.BytesIO(data) if data is not None else None)
    manifest = dict(input_zip_sha256=ZIP_SHA, stock_demo_sha256=DEMO_SHA, source_sha256=source,
        demo_sha256=sha(patched), patch_sha256=sha(payload), update_sha256=sha((out/'update.tar').read_bytes()),
        rootfs_sha256=sha(newsq.read_bytes()), kernel_sha256=sha(blobs['recovery-update/xImage']),
        patch_bytes=len(payload), ring_step_pixels=RING_STEP,
        version=version, variant=variant, dev=dev, peq=audio, bluealsa_sha256=sha(bluealsa), compact_code=code_changes, changed_assets=changed_assets, logo_sha256=sha(logo_data),
        patch_symbols={n:hex(v) for n,v in ps.items() if n.startswith('stock_')},
        tools={t:run(t,'--version').splitlines()[0] for t in ['clang','ld.lld','llvm-objcopy']} |
              ({'imagemagick': imagemagick('-version', data=b'').decode().splitlines()[0]} if ipod else {}))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:manifest[k] for k in ['update_sha256','patch_bytes','version']},indent=2))

if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('zip',type=pathlib.Path)
    ap.add_argument('--out',type=pathlib.Path,default=ROOT/'build')
    ap.add_argument('--logo',type=pathlib.Path,default=ROOT/'assets/logo.jpg',
                    help='320x375 JPEG boot splash (default: assets/logo.jpg)')
    ap.add_argument('--ipod', action='store_true', help='iPod UI: compact local browsing and long Return to Now Playing')
    ap.add_argument('--dev', action='store_true',
                    help=f'development build: lowercase version tag (V{VERSION}r/i); never a release input')
    a=ap.parse_args()
    try:
        build(a.zip,a.out.resolve(),a.logo,a.ipod,a.dev)
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        ap.error(str(exc))
