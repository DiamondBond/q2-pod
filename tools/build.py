#!/usr/bin/env python3
"""Reproducibly patch only the audited Q2 V1.32 ZIP. Requires LLVM and squashfs-tools."""
import argparse, hashlib, io, json, pathlib, re, struct, subprocess, tarfile, zipfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
ZIP_SHA = '154c17822d09be001be35c03d2d3488424dee195221790bd70864480d55b0f00'
DEMO_SHA = '2c5f06142850b4fc168f82b44a81550cce0a5b4b9fe1c179dced4a08a3049138'
BASE = 0xb00000
SCRATCH = 0xb0f000
SCRATCH_IPOD = 0xb14000
HOOK = 0x4e85c8
HOOKS = {
    'on_wm_keyup_before_fun': (HOOK, 'ringnav'),
    'on_wm_tsdown_before_fun': (0x4e8bd0, 'ringnav_touch'),
    'widget_on_paint_border': (0x6596a0, 'ringnav_paint'),
    'widget_dispatch': (0x65e0ec, 'ringnav_dispatch'),
}

def run(*args):
    return subprocess.check_output([str(a) for a in args], text=True)
def sha(b): return hashlib.sha256(b).hexdigest()
def check(condition, message):
    if not condition: raise ValueError(message)
def symbols(p):
    out = {}
    for line in run('readelf', '-Ws', p).splitlines():
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
 'window_manager': ('void *', 'void'),
 'window_manager_get_top_window': ('void *', 'void *'),
 'window_manager_is_animating': ('int', 'void *'),
 'window_manager_get_pointer_pressed': ('int', 'void *'),
 'widget_get_visible': ('int', 'void *'),
 'widget_get_prop_bool': ('int', 'void *, const char *, int'),
 'widget_get_prop_int': ('int', 'void *, const char *, int'),
 'widget_get_prop_str': ('const char *', 'void *, const char *, const char *'),
 'widget_get_type': ('const char *', 'void *'),
 'widget_count_children': ('unsigned', 'void *'),
 'widget_get_child': ('void *', 'void *, unsigned'),
 'widget_set_prop_int': ('int', 'void *, const char *, int'),
 'widget_invalidate_force': ('int', 'void *, void *'),
 'widget_animator_pause': ('int', 'void *'),
 'widget_animator_destroy': ('int', 'void *'),
 'canvas_get_clip_rect': ('int', 'void *, void *'),
 'canvas_set_clip_rect': ('int', 'void *, const void *'),
 'canvas_set_stroke_color': ('int', 'void *, unsigned'),
 'canvas_stroke_rect': ('int', 'void *, int, int, int, int'),
 'pointer_event_init': ('void *', 'void *, int, void *, int, int'),
 'time_now_ms': ('unsigned', 'void'),
 'timer_add': ('unsigned', 'int (*)(const void *), void *, unsigned'),
 'timer_remove': ('int', 'unsigned'),
 'tk_snprintf': ('int', 'char *, unsigned, const char *, ...'),
 'file_write': ('int', 'const char *, const void *, unsigned'),
 'widget_move_resize': ('int', 'void *, int, int, int, int'),
 'widget_layout': ('int', 'void *'),
 'idle_add': ('unsigned', 'int (*)(const void *), void *'),
 'widget_get_text': ('const int *', 'void *'),
 'widget_set_text': ('int', 'void *, const int *'),
 'widget_lookup': ('void *', 'void *, const char *, int'),
 'widget_load_image': ('int', 'void *, const char *, void *'),
 'widget_unload_image': ('int', 'void *, void *'),
 'image_manager': ('void *', 'void'),
 'image_manager_unload_bitmap_by_name': ('int', 'void *, const char *'),
 'canvas_get_vgcanvas': ('void *', 'void *'),
 'vgcanvas_save': ('int', 'void *'),
 'vgcanvas_restore': ('int', 'void *'),
 'vgcanvas_begin_path': ('int', 'void *'),
 'vgcanvas_translate': ('int', 'void *, float, float'),
 'vgcanvas_scale': ('int', 'void *, float, float'),
 'vgcanvas_rounded_rect': ('int', 'void *, float, float, float, float, float'),
 'vgcanvas_paint': ('int', 'void *, int, void *'),
 'vgcanvas_set_global_alpha': ('int', 'void *, float'),
 'vgcanvas_set_line_width': ('int', 'void *, float'),
 'vgcanvas_set_stroke_color': ('int', 'void *, unsigned'),
 'vgcanvas_stroke': ('int', 'void *'),
 'canvas_set_fill_color': ('int', 'void *, unsigned'),
 'canvas_fill_rect': ('int', 'void *, int, int, int, int'),
 'os_fs': ('void *', 'void'),
 'fs_open_dir': ('void *', 'void *, const char *'),
 'fs_dir_read': ('int', 'void *, void *'),
 'fs_dir_close': ('int', 'void *'),
 'widget_use_style': ('int', 'void *, const char *'),
 'widget_set_prop_str': ('int', 'void *, const char *, const char *'),
 'slide_menu_scroll_to_next': ('int', 'void *'),
 'slide_menu_scroll_to_prev': ('int', 'void *'),
 'table_client_stop_animator_scroll': ('int', 'void *'),
 'table_client_set_yoffset': ('int', 'void *, int'),
 'scroll_view_scroll_delta_to': ('int', 'void *, int, int, int'),
 'mclGetPlayPos': ('int', 'void'),
 'mclGetPlayStatus': ('int', 'void'),
 'player_play_pause': ('int', 'void'),
 'player_next_music': ('int', 'void'),
 'player_prev_music': ('int', 'void'),
 'player_start': ('int', 'void *, int, int, int'),
 'device_set_volume': ('int', 'int, int'),
 'navigator_to': ('int', 'const char *'),
 'list_item_create': ('void *', 'void *, int, int, int, int'),
 'list_view_create': ('void *', 'void *, int, int, int, int'),
 'scroll_view_create': ('void *', 'void *, int, int, int, int'),
 'window_create': ('void *', 'void *, int, int, int, int'),
 'vgcanvas_set_fill_color': ('int', 'void *, unsigned'),
 'vgcanvas_fill': ('int', 'void *'),
 'button_create': ('void *', 'void *, int, int, int, int'),
 'hscroll_label_create': ('void *', 'void *, int, int, int, int'),
 'widget_on': ('unsigned', 'void *, int, int (*)(void *, void *), void *'),
 'image_manager_unload_all': ('int', 'void *'),
 'bitmap_lock_buffer_for_write': ('unsigned char *', 'void *'),
 'bitmap_unlock_buffer': ('int', 'void *'),
 'file_read': ('void *', 'const char *, unsigned *'),
 'tk_free': ('void', 'void *'),
 'idle_queue': ('int', 'int (*)(const void *), void *'),
 'player_playtime': ('int', 'void'),
 'btctl_transport_get_volume': ('int', 'void'),
 'btctl_transport_set_volume': ('int', 'int'),
 'popup_create': ('void *', 'void *, int, int, int, int'),
 'image_create': ('void *', 'void *, int, int, int, int'),
 'label_create': ('void *', 'void *, int, int, int, int'),
 'image_base_set_image': ('int', 'void *, const char *'),
 'widget_set_text_utf8': ('int', 'void *, const char *'),
 'window_close': ('int', 'void *'),
 'deque_at': ('void *', 'void *, int'),
 'getBtLinkSize': ('int', 'void'),
 'getBtLinkItem': ('int', 'int, int *, char *'),
 'deque_size': ('int', 'void *'),
 'check_albumcover_flag': ('int', 'int, int'),
 'local_albumsmallcover_task': ('int', 'int, int'),
 'local_albumcover_task': ('int', 'int, int'),
}
POINTERS = ['mcl_pdeqplaylist', 'pdeq_btpairlist']
LIBC = {  # libc imports (PLT stubs; they need the demo's $gp)
    'socket': ('int', 'int, int, int'), 'connect': ('int', 'int, const void *, unsigned'),
    'send': ('int', 'int, const void *, unsigned, int'), 'recv': ('int', 'int, void *, unsigned, int'),
    'select': ('int', 'int, void *, void *, void *, void *'), 'close': ('int', 'int'),
    'usleep': ('int', 'unsigned'), '__errno_location': ('int *', 'void'),
    'pthread_create': ('int', 'unsigned long *, const void *, void *(*)(void *), void *'),
    'pthread_detach': ('int', 'unsigned long'),
    'ioctl': ('int', 'int, unsigned long, void *'),
    'open': ('int', 'const char *, int'), 'read': ('int', 'int, void *, unsigned'),
}
INTS = ['bt_showcoding', 'bt_connectstatus']  # > 0 while a Bluetooth codec is streaming  # the play queue (a deque); its size is the "of N" in "3 of 12"
GLOBALS = ['g_backlight_status', 'g_lockscreen_pageflag', 'g_testmode_flag',
           'g_guideflag', 'g_poweroff_state', 'g_usblink_status', 'bt__recv_pageflag',
           'g_power_longkey', 'g_ingore_bootkey_flag', 'g_bluetoothflag', 'bt_linkstatus']

# Stock bug fix (--aac48): when a headset itself sets up the A2DP stream (AirPods taken out of the case
# connect to the Q2), it picks AAC at 44.1 kHz, and Shanling's bluealsa is then fed 48 kHz audio: it
# encodes 44.1 kHz frames and drops ~8% of them (an HCI trace showed skipped RTP sequence numbers
# 4 times a second, timestamps 8% fast): choppy audio. Links the Q2 sets up pick 48 kHz and are
# clean. The A2DP AAC source capability (a2dp_aac_t in .data) offers 44.1 kHz + 48 kHz; clearing the
# 44.1 kHz bit leaves 48 kHz, which every AAC sink must support.
BLUEALSA = 'usr/bin/bluealsa'
BLUEALSA_SHA = '0a4ffb7cc8207a46a3568440c5f31022b7125befd164e2f1af52537340a9892a'
AAC_CAPS_OFF = 0x317b7  # object type MPEG-2/4 AAC LC, 44.1 kHz, 48 kHz + stereo, VBR 320000 (bitrate set at run time)
AAC_CAPS = bytes([0xc0, 0x01, 0x84, 0x84, 0xe2, 0x00])

def build(zip_path, out, step, color=0xffffffff, overlay=None, version='V2.1R', dump=False, ipod=False, inset=0, accel=False, aac48=False):
    hooks_used = dict(HOOKS, **({'table_client_set_row_height': (0x5c9de0, 'ringnav_rowh'),
                                 'table_client_set_on_load_data': (0x5ca984, 'ringnav_set_load'),
                                 'window_animator_prepare': (0x682ee8, 'ringnav_prepare'),
                                 'scroll_view_scroll_to': (0x5f0178, 'ringnav_scrollto'),
                                 'widget_layout_children': (0x6461b0, 'ringnav_layout'),
                                 'mclSetBtVol': (0x5accec, 'ringnav_btvol'),
                                 'style_get_color': (0x649f6c, 'ringnav_style_color'),
                                 'image_manager_add': (0x6445d4, 'ringnav_image_add')} if ipod else {}))
    out.mkdir(parents=True, exist_ok=True)
    check(not (out/'update.tar').exists(), 'Output already exists; use a fresh --out directory')
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
    demo = out/'stock-demo'; demo.write_bytes(raw_demo)
    syms = symbols(demo)
    check(syms['on_wm_keyup_before_fun'] == HOOK, 'Callback address mismatch')
    header = ['#define RING_STEP '+str(step), '#define RING_COLOR 0x%08xu' % color]+(['#define RINGNAV_DUMP 1'] if dump else [])+(['#define RINGNAV_IPOD 1'] if ipod else [])+(['#define ROW_INSET %d' % inset] if inset else [])+(['#define RINGNAV_ACCEL 1'] if accel else [])+[
              'extern int stock_keyup_trampoline(void *, void *);',
              '#define stock_keyup stock_keyup_trampoline']
    for name in ('touch', 'paint', 'dispatch') + (('rowh', 'loaddata', 'prepare', 'scrollto', 'layout', 'btvol', 'stylecolor', 'imgadd') if ipod else ()):
        args = {'loaddata': 'void *, void *, void *', 'prepare': 'void *, void *, void *, void *',
                'scrollto': 'void *, int, int, int', 'layout': 'void *', 'btvol': 'int, int', 'stylecolor': 'unsigned *, void *, const char *, unsigned',
                'imgadd': 'void *, const char *, void *'}.get(name, 'void *, void *')
        header += [f'extern int stock_{name}_trampoline({args});',
                   f'#define stock_{name} stock_{name}_trampoline']
    for name,(ret,args) in FUNCTIONS.items():
        header.append(f'#define {name} (({ret} (*)({args}))0x{syms[name]:x}u)')
    for name in GLOBALS:
        header.append(f'#define {name} (*(volatile unsigned char *)0x{syms[name]:x}u)')
    for name in POINTERS:
        header.append(f'#define {name} (*(void *volatile *)0x{syms[name]:x}u)')
    for name,(ret,args) in LIBC.items():
        sym = next(k for k in syms if k.split('@')[0] == name and '@' in k)
        header.append(f'#define {name} (({ret} (*)({args}))0x{syms[sym]:x}u)')
    for name in INTS:
        header.append(f'#define {name} (*(volatile int *)0x{syms[name]:x}u)')
    (out/'stock.h').write_text('\n'.join(header)+'\n')
    flags = ['--target=mipsel-linux-gnu','-march=mips32r2','-mabi=32','-mfp64',
             '-mno-abicalls','-fno-pic','-G0','-ffreestanding','-fno-builtin',
             '-fno-stack-protector','-fno-unwind-tables','-fno-asynchronous-unwind-tables',
             '-Oz' if ipod else '-Os','-Wall','-Wextra','-Werror']  # iPod builds: -Oz, ~15% smaller (V2.6d)
    run('clang',*flags,'-I',out,'-c',ROOT/'patch/ringnav.c','-o',out/'ringnav.o')
    run('clang',*flags,*(['-DRINGNAV_IPOD'] if ipod else []),*(['-DRINGNAV_DUMP'] if dump else []),'-c',ROOT/'patch/trampoline.S','-o',out/'trampoline.o')
    # iPod builds outgrew the 60K below the stock scratch page (V2.2d, theme colours): their scratch
    # moves up; other builds keep 0xb0f000 (the plain build stays byte-identical).
    scratch = SCRATCH_IPOD if ipod else SCRATCH
    ld = (ROOT/'patch/link.ld').read_text()
    check(ld.count('0xb0f000') == 1, 'link.ld: scratch address')
    (out/'link.ld').write_text(ld.replace('0xb0f000', hex(scratch)))
    run('ld.lld','-m','elf32ltsmip','-T',out/'link.ld','-e','ringnav',
        out/'ringnav.o',out/'trampoline.o','-o',out/'patch.elf')
    run('llvm-objcopy','-O','binary',out/'patch.elf',out/'patch.bin')
    payload = (out/'patch.bin').read_bytes()
    ps = symbols(out/'patch.elf')
    check(len(payload) < scratch-BASE, 'Payload overlaps its scratch page')
    check(ps['center'] == scratch or dump or ipod or accel, 'Scratch cell moved')
    scratch_len = 0x2000 if dump else 0x800 if ipod or accel else 8
    sizes = {s[7]: int(s[2], 0) for s in (l.split() for l in run('readelf', '-Ws', out/'patch.elf').splitlines())
             if len(s) >= 8 and s[0].endswith(':') and s[3] == 'OBJECT'}
    state = {n: v for n, v in ps.items() if scratch <= v < scratch + 0x4000 and n in sizes}
    check(state and all(v + sizes[n] <= scratch + scratch_len for n, v in state.items()),
          'Scratch state outside its mapped cells')
    patched = bytearray(raw_demo)
    hookoff = fileoff(patched, HOOK)
    hooks = {}
    for name, (address, replacement) in hooks_used.items():
        check(syms[name] == address, f'{name}: callback address mismatch')
        off = fileoff(patched, address)
        prolog = struct.unpack_from('<III', patched, off)
        check(prolog[0] >> 16 == 0x3c1c and prolog[1] >> 16 == 0x279c and
              prolog[2] == 0x0399e021, f'{name}: unexpected PIC prologue')
        low = prolog[1] & 65535
        gp = ((prolog[0] & 65535) << 16) + (low if low < 32768 else low - 65536) + address
        check(gp == 0xa26cc0, f'{name}: unexpected GOT base')
        patched[off:off+8] = struct.pack('<II', 0x08000000 | (ps[replacement] >> 2), 0)
        hooks[name] = dict(address=hex(address), replacement=replacement, original=raw_demo[off:off+12].hex())
    # Single shared version literal: About display and updater equality check.
    check(patched.count(b'V1.32\0') == 1, 'Version literal is not unique')
    if accel:
        # get_direction is a leaf without a PIC prologue: verify its first two instructions
        # (subu a0,a0,a1; addiu a1,a0,200) and jump to ringnav_direction, which returns to the caller.
        gd = syms['get_direction']; off = fileoff(patched, gd)
        check(struct.unpack_from('<II', patched, off) == (0x00852023, 0x248500c8), 'get_direction: unexpected code')
        patched[off:off+8] = struct.pack('<II', 0x08000000 | ((ps['ringnav_direction'] >> 2) & 0x3ffffff), 0)
        hooks['get_direction'] = dict(address=hex(gd), replacement='ringnav_direction', original=raw_demo[off:off+8].hex())
    if ipod:
        # Boot to Home: home_page_init resumes the last queue by opening Now Playing with it,
        # navigator_to_with_context("playing_page", {queue, pos, source, mode}), whose init calls
        # player_start with it. That call (jalr t9, after lw t9 <- navigator_to_with_context and
        # a0 = "playing_page") becomes jal ringnav_boot_play, which starts the queue without the page.
        check(syms['home_page_init'] == 0x523c84 and syms['playing_page_init'] == 0x52ca88, 'boot resume: moved')
        site = 0x523de0; off = fileoff(patched, site)
        check(struct.unpack_from('<I', patched, fileoff(patched, 0x523db8))[0] == 0x8f99a864 and
              struct.unpack_from('<I', patched, fileoff(patched, 0x523dc4))[0] == 0x24846790 and
              struct.unpack_from('<II', patched, off) == (0x0320f809, 0xafa20024), 'boot resume: unexpected code')
        # the two globals playing_page_init sets before player_start (ringnav_boot_play sets them too)
        check(struct.unpack_from('<5I', patched, fileoff(patched, 0x52cbe4)) ==
              (0x8f8280bc, 0x24030028, 0x8e260008, 0xa040a6c1, 0x8f82a940) and
              struct.unpack_from('<I', patched, fileoff(patched, 0x52cbf8))[0] == 0xa043f660, 'playing_page_init: unexpected code')
        struct.pack_into('<I', patched, off, 0x0c000000 | ((ps['ringnav_boot_play'] >> 2) & 0x3ffffff))
        # The app's volume level (0-100, a static byte): responseSetVolume (remote volume) stores it
        # through GOT[gp-0x5244] and calls device_set_volume with it; ringnav_hsvol does the same.
        check(struct.unpack_from('<II', raw_demo, fileoff(raw_demo, 0x519fdc)) == (0x8f91adbc, 0xa2230000) and
              struct.unpack_from('<I', raw_demo, fileoff(raw_demo, 0xa26cc0 - 0x5244))[0] == 0xa38c41, 'volume level: unexpected code')
        hooks['boot_resume'] = dict(address=hex(site), replacement='ringnav_boot_play', original=raw_demo[off:off+4].hex())
        # Background fills (widget_fill_rect) take their colours from style_get_gradient, a leaf
        # (beqz a0; nop; lw v0,0(a0)...) calling the style's get_gradient: jump to ringnav_style_gradient,
        # which does the same and maps the stops' colours (theme colours).
        sg = syms['style_get_gradient']; off = fileoff(patched, sg)
        check(sg == 0x649f3c and struct.unpack_from('<III', patched, off) == (0x10800009, 0, 0x8c820000), 'style_get_gradient: unexpected code')
        patched[off:off+8] = struct.pack('<II', 0x08000000 | ((ps['ringnav_style_gradient'] >> 2) & 0x3ffffff), 0)
        hooks['style_get_gradient'] = dict(address=hex(sg), replacement='ringnav_style_gradient', original=raw_demo[off:off+8].hex())
    check(len(version) == 5, 'Version literal must stay 5 characters')
    # update_firmware (0x4f8150) rejects an update.tar whose firmware_v20.info version has no 'V'.
    check('V' in version, "The updater rejects versions without a 'V'")
    patched = patched.replace(b'V1.32\0', version.encode()+b'\0')
    nulls = [(o,p) for o,p in segments(patched) if p[0] == 0]
    check(len(nulls) == 1 and nulls[0][0] == segments(patched)[-1][0], 'No final PT_NULL slot')
    check(all(p[2]+p[5] < BASE for _,p in segments(patched) if p[0] == 1), 'Patch mapping overlaps')
    appendoff = (len(patched)+65535)&~65535
    patched.extend(bytes(appendoff-len(patched)))
    patched.extend(payload)
    struct.pack_into('<8I',patched,nulls[0][0],1,appendoff,BASE,BASE,len(payload),scratch-BASE+scratch_len,7,65536)
    (out/'demo').write_bytes(patched)
    (out/'patch.dis').write_text(run('llvm-objdump','-d',out/'patch.elf'))
    # Pseudo-file round trip preserves every original inode's metadata and hardlinks.
    pseudo = out/'root.pseudo'
    run('unsquashfs','-pf',pseudo,sq)
    p = pseudo.read_bytes()
    old = re.search(rb'^release/bin/demo R (\d+) (\d+) (\d+) (\d+) .+$',p,re.M)
    check(old is not None, 'Missing demo pseudo inode')
    # mksquashfs takes "/" from the source dir, not the pseudo file; carry stock values over.
    root = re.search(rb'^/ D (\d+) (\d+) (\d+) (\d+)$',p,re.M)
    check(root is not None, 'Missing root pseudo inode')
    t,mode,uid,gid = (x.decode() for x in root.groups())
    rootargs = ['-root-time',t,'-root-mode',mode,'-root-uid',uid,'-root-gid',gid]
    # Paths are passed through a shell by mksquashfs F entries; quote them explicitly.
    import shlex
    replacement = b'release/bin/demo F '+b' '.join(old.groups())+b' cat '+shlex.quote(str(out/'demo')).encode()
    p = p[:old.start()]+replacement+p[old.end():]
    # Optional asset overlay: each file replaces the stock file at the same path, keeping its metadata.
    replaced = []
    for f in sorted(overlay.rglob('*') if overlay else []):
        if not f.is_file(): continue
        rel = f.relative_to(overlay).as_posix().encode()
        m = re.search(rb'^'+re.escape(rel)+rb' R (\d+) (\d+) (\d+) (\d+) .+$',p,re.M)
        check(m is not None, 'Overlay path is not a stock regular file: '+rel.decode())
        p = p[:m.start()]+rel+b' F '+b' '.join(m.groups())+b' cat '+shlex.quote(str(f.resolve())).encode()+p[m.end():]
        replaced.append(rel.decode())
    if aac48:
        stock_ba = subprocess.check_output(['unsquashfs','-cat',str(sq),BLUEALSA])
        check(sha(stock_ba) == BLUEALSA_SHA, 'Unexpected stock bluealsa')
        check(stock_ba[AAC_CAPS_OFF:AAC_CAPS_OFF+6] == AAC_CAPS and stock_ba.count(AAC_CAPS) == 1, 'bluealsa: unexpected AAC capabilities')
        ba = bytearray(stock_ba); ba[AAC_CAPS_OFF+1] = 0x00  # 44.1 kHz off
        (out/'bluealsa').write_bytes(ba)
        rel = BLUEALSA.encode()
        m = re.search(rb'^'+re.escape(rel)+rb' R (\d+) (\d+) (\d+) (\d+) .+$',p,re.M)
        check(m is not None, 'Missing bluealsa pseudo inode')
        p = p[:m.start()]+rel+b' F '+b' '.join(m.groups())+b' cat '+shlex.quote(str(out/'bluealsa')).encode()+p[m.end():]
        replaced.append(BLUEALSA)
    pseudo.write_bytes(p)
    (out/'empty').mkdir()
    newsq = out/'rootfs.squashfs'
    epoch = struct.unpack_from('<I',sq.read_bytes(),8)[0]
    run('mksquashfs',out/'empty',newsq,'-pf',pseudo,'-noappend','-comp','lzo',
        '-b','131072','-Xcompression-level','9','-mkfs-time',epoch,*rootargs,'-processors','1','-no-progress')
    # Every inode except demo must keep stock name/type/mtime/mode/uid/gid (size/offset fields shift).
    def inodes(image):
        text = subprocess.check_output(['unsquashfs','-pf','-',str(image)]).split(b'\n# START OF DATA')[0]
        return sorted(l.split()[:6] for l in text.splitlines() if l and not l.startswith((b'#',b'release/bin/demo ')))
    check(inodes(newsq) == inodes(sq), 'Repacked rootfs metadata differs from stock')
    blobs['recovery-update/rootfs.squashfs'] = newsq.read_bytes()
    # Stock image proves this size fits; do not enlarge beyond its padded size.
    check(len(blobs['recovery-update/rootfs.squashfs']) <= sq.stat().st_size, 'Repacked rootfs exceeds stock size')
    blobs['firmware_v20.info'] = ('Shanling Q2\n'+version+'\n'+''.join(
        hashlib.md5(blobs[n]).hexdigest()+'  '+n+'\n' for n in [
            'recovery-update/xImage','recovery-update/rootfs.squashfs'])).encode()
    with tarfile.open(out/'update.tar','w',format=tarfile.GNU_FORMAT) as t:
        for m in meta:
            data = blobs.get(m.name)
            if data is not None: m.size=len(data)
            t.addfile(m,io.BytesIO(data) if data is not None else None)
    manifest = dict(input_zip_sha256=ZIP_SHA, stock_demo_sha256=DEMO_SHA,
        demo_sha256=sha(patched), patch_sha256=sha(payload), update_sha256=sha((out/'update.tar').read_bytes()),
        rootfs_sha256=sha(newsq.read_bytes()), kernel_sha256=sha(blobs['recovery-update/xImage']),
        hook_address=hex(HOOK), hook_file_offset=hex(hookoff), patch_address=hex(BASE),
        patch_file_offset=hex(appendoff), patch_bytes=len(payload), ring_step_pixels=step,
        version=version, hooks=hooks, ring_color=hex(color), overlay_files=len(replaced), ipod=ipod, row_inset=inset, accel=accel, aac48=aac48, dump=dump,
        patch_symbols={n:hex(v) for n,v in ps.items() if n.startswith('stock_') or n in ('ringnav_aap_thread','aap','ringnav_avrcp_thread','avrcp','ringnav_boot_play','avrcp_idle','accent')},
        tools={t:run(t,'--version').splitlines()[0] for t in ['clang','ld.lld','llvm-objcopy']})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:manifest[k] for k in ['update_sha256','patch_bytes','version']},indent=2))

if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('zip',type=pathlib.Path)
    ap.add_argument('--out',type=pathlib.Path,default=ROOT/'build')
    ap.add_argument('--step',type=int,default=48,choices=range(8,129),metavar='8..128')
    ap.add_argument('--ring-color',type=lambda v:int(v,16),default=0xffffffff,help='outline colour as AABBGGRR hex')
    ap.add_argument('--overlay',type=pathlib.Path,help='directory of rootfs files to replace')
    ap.add_argument('--version',default='V2.1R')
    ap.add_argument('--dump',action='store_true',help='debug: write widget trees to the SD card')
    ap.add_argument('--ipod',action='store_true',help='iPod classic list rows (needs the iPod theme overlay)')
    ap.add_argument('--accel',action='store_true',help='wheel acceleration on fast spins')
    ap.add_argument('--aac48',action='store_true',help='stock fix: bluealsa offers AAC at 48 kHz only (44.1 kHz links stutter)')
    ap.add_argument('--row-inset',type=int,default=0,choices=range(0,21),metavar='0..20',help='iPod rows: inset selection pill')
    a=ap.parse_args()
    build(a.zip,a.out.resolve(),a.step,a.ring_color,a.overlay and a.overlay.resolve(),a.version,a.dump,a.ipod,a.row_inset,a.accel,a.aac48)
