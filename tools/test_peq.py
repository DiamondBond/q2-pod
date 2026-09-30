#!/usr/bin/env python3
"""Run the actual C parser/storage and PCM DSP checks."""
import cmath
import ctypes as C
import math
import pathlib
import subprocess
import tempfile
from build import FUNCTIONS
from peq import LIBC

PROTOTYPES = {**FUNCTIONS, **LIBC}  # the stock calls the host shims stand in for

ROOT = pathlib.Path(__file__).resolve().parents[1]

class Band(C.Structure):
    _fields_ = [('enabled', C.c_int), ('type', C.c_int), ('frequency', C.c_double),
                ('gain', C.c_double), ('q', C.c_double)]

class Preset(C.Structure):
    _fields_ = [('count', C.c_int), ('bypass', C.c_int), ('preamp', C.c_double), ('bands', Band * 10)]

class Error(C.Structure):
    _fields_ = [('line', C.c_uint), ('reason', C.c_char_p)]

class Coeff(C.Structure):
    _fields_ = [(k, C.c_double) for k in ('b0', 'b1', 'b2', 'a1', 'a2')]

class Engine(C.Structure):
    _fields_ = [('c', Coeff * 10), ('z', ((C.c_double * 2) * 10) * 8),
                ('gain', C.c_double), ('bypass', C.c_int)]

class DSP(C.Structure):
    _fields_ = [('current', Engine), ('next', Engine), ('pending', Engine),
                *[(k, C.c_int) for k in ('rate', 'channels', 'ramp', 'ramp_length', 'waiting')]]

def compile_host(tmp, name, *sources):
    path = tmp/name
    subprocess.run(['cc', '-DPEQ_HOST', f'-DPEQ_ROOT="{tmp}/root"', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', *map(str, sources), '-lm', '-o', str(path)], check=True)
    return C.CDLL(str(path))

def library(tmp):
    lib = compile_host(tmp, 'peq.so', ROOT/'patch/peq.c')
    signatures = {
        'peq_default': [C.POINTER(Preset)], 'peq_valid': [C.POINTER(Preset)],
        'peq_parse': [C.c_char_p, C.c_uint, C.POINTER(Preset), C.POINTER(Error)],
        'peq_import_file': [C.c_char_p, C.POINTER(Preset), C.POINTER(Error)],
        'peq_save': [C.c_char_p, C.POINTER(Preset), C.c_int],
        'peq_load': [C.c_char_p, C.POINTER(Preset)],
        'peq_compile': [C.POINTER(Preset), C.c_int, C.POINTER(Engine)],
        'peq_reset': [C.POINTER(DSP), C.c_int, C.c_int, C.POINTER(Preset)],
        'peq_update': [C.POINTER(DSP), C.POINTER(Preset)],
        'peq_process': [C.POINTER(DSP), C.POINTER(C.c_float), C.c_uint],
    }
    for name, args in signatures.items(): getattr(lib, name).argtypes = args
    return lib

def parse(lib, text):
    data = text.encode() if isinstance(text, str) else text
    p, error = Preset(), Error()
    assert lib.peq_parse(data, len(data), C.byref(p), C.byref(error)), (error.line, error.reason, data)
    return p

def parser_check(lib, tmp):
    source = '\ufeff # comment\r\nPreamp : -3 dB # inline\r\nPreamp:\t-2 dB\n'
    aliases = ['PK', 'PEQ', 'LS', 'LSC', 'HS', 'HSC']
    for i, alias in enumerate(aliases):
        source += f'Filter {99-i}: {"ON" if i%2 else "OFF"}\t{alias} Fc {100+i*100} Hz Gain -6 dB'
        source += ' Q 1.3\n' if i < 2 else '\n'
    p = parse(lib, source)
    assert p.count == 6 and p.preamp == -5 and p.bypass == 0
    assert [b.type for b in p.bands[:6]] == [0, 0, 1, 1, 2, 2]
    assert [b.enabled for b in p.bands[:6]] == [0, 1, 0, 1, 0, 1]
    assert [b.frequency for b in p.bands[:6]] == [100, 200, 300, 400, 500, 600]
    a = 10 ** (-6 / 40)  # APO: shelf without Q is slope 0.9 at Fc
    assert abs(p.bands[2].q - 1 / math.sqrt((a + 1/a) * (1/0.9 - 1) + 2)) < 1e-15
    # APO: LS/HS with Q give a corner frequency (S=1 at Q 0.7071 -> shift 10^(gain/80)); LSC/HSC the centre.
    shelves = parse(lib, 'Filter: ON LS Fc 100 Hz Gain 12 dB Q 0.7071067811865476\n'
                         'Filter: ON HS Fc 8000 Hz Gain -12 dB Q 0.7071067811865476\n'
                         'Filter: ON LSC Fc 100 Hz Gain 12 dB Q 0.7\n'
                         'Filter 11: OFF None\nFilter: ON PK Fc 1000,5 Hz Gain -3,5 dB Q 1,41\n')
    assert abs(shelves.bands[0].frequency - 100 * 10**(12/80)) < 1e-9
    assert abs(shelves.bands[1].frequency - 8000 / 10**(12/80)) < 1e-9
    assert shelves.bands[2].frequency == 100 and shelves.count == 4
    assert (shelves.bands[3].frequency, shelves.bands[3].gain, shelves.bands[3].q) == (1000.5, -3.5, 1.41)
    edges = parse(lib, 'Filter: ON LS Fc 19000 Hz Gain 12 dB Q 0.7\nFilter: ON HS Fc 21 Hz Gain -12 dB Q 0.7\n')
    assert (edges.bands[0].frequency, edges.bands[1].frequency) == (20000, 20)
    single = 'Filter: ON PK Fc 1e3 Hz Gain +6.0 dB Q .7\n'
    assert parse(lib, single).preamp == 0
    assert parse(lib, 'Preamp: 24 dB\nPreamp: 24 dB\nPreamp: -48 dB').preamp == 0
    assert parse(lib, single * 10).count == 10
    assert parse(lib, '').count == 0
    # Import is pure. Saving succeeds only after validation and explicit collision confirmation.
    active, saved = tmp/'active', tmp/'preset'
    for path in (active, saved): assert lib.peq_save(bytes(path), C.byref(p), 0) == 1
    baseline = bytes(p)
    failures = [
        (single * 10 + single.replace('ON', 'OFF'), 11, 'ten'),
        ('Preamp: 24 dB\nPreamp: 1 dB', 2, 'summed'),
        ('Preamp: -61 dB', 1, 'preamp'),
        ('Preamp: -3', 1, 'expected'),
        ('\nGraphicEQ: 20 0; 20000 0', 2, 'unsupported'),
        ('Include: other.txt', 1, 'unsupported'), ('Channel: L', 1, 'unsupported'),
        ('Eval: x=1', 1, 'unsupported'), ('garbage', 1, 'unsupported'),
        (single.replace(' Q .7', ''), 1, 'requires Q'),
        (single.replace('PK', 'HP'), 1, 'type'),
        (single.replace('PK', 'LS 6dB'), 1, 'form'),
        (single.replace('Q .7', 'BW Oct 1'), 1, 'form'),
        (single.replace('1e3', '`1000`'), 1, 'number'),
        (single.replace('Filter:', 'Filter x:'), 1, 'label'),
        (single + 'Filter: OFF PK Fc 19 Hz Gain 0 dB Q 1', 2, 'range'),
        (b'\0', 1, 'NUL'), (b'#' * 513, 1, 'line'), (b'#' * 16385, 1, 'file'),
    ]
    for old, values in [('1e3', ['nan', 'inf', '-inf', '1e999', '20junk', '0x100', '20001', '-20']),
                        ('+6.0', ['nan', '25', '-25']), ('.7', ['NaN', '0', '-1', '10.1'])]:
        failures += [(single.replace(old, value), 1, 'number' if value in ('nan', 'inf', '-inf', '1e999', '20junk', '0x100', 'NaN') else 'range') for value in values]
    for text, line, reason in failures:
        data = text.encode() if isinstance(text, str) else text
        error = Error()
        assert not lib.peq_parse(data, len(data), C.byref(p), C.byref(error)), data
        assert error.line == line and reason in error.reason.decode(), (data, error.line, error.reason)
        assert bytes(p) == baseline
        assert active.read_bytes() == saved.read_bytes()
    q = parse(lib, single)
    before = saved.read_bytes()
    assert lib.peq_save(bytes(saved), C.byref(q), 0) == 2
    assert saved.read_bytes() == before  # cancel
    assert lib.peq_save(bytes(saved), C.byref(q), 1) == 1  # confirm
    assert active.read_bytes() == before  # never auto-activate
    source_file = tmp/'input.txt'
    source_file.write_text(single)
    assert lib.peq_import_file(bytes(source_file), C.byref(p), C.byref(Error()))
    source_file.unlink()
    assert lib.peq_load(bytes(saved), C.byref(p)) and bytes(p) == bytes(q)
    unchanged = bytes(p)
    for path in (source_file, tmp):
        e = Error()
        assert not lib.peq_import_file(bytes(path), C.byref(p), C.byref(e))
        assert e.line and e.reason and bytes(p) == unchanged
    saved.write_bytes(saved.read_bytes()[:-1])
    assert not lib.peq_load(bytes(saved), C.byref(p)) and bytes(p) == unchanged
    assert not lib.peq_save(bytes(tmp/'missing'/'preset'), C.byref(q), 1)
    print('PEQ parser/storage: syntax, limits, transaction failures, confirmation and persistence passed.')

def response(engine, rate, frequency):
    if engine.bypass: return 1
    z = cmath.exp(-2j * math.pi * frequency / rate)
    result = complex(engine.gain)
    for c in engine.c: result *= (c.b0 + c.b1*z + c.b2*z*z)/(1 + c.a1*z + c.a2*z*z)
    return abs(result)

def process(lib, d, values, channels=1):
    audio = (C.c_float * len(values))(*values)
    lib.peq_process(C.byref(d), audio, len(values)//channels)
    return list(audio)

def dsp_check(lib):
    p = parse(lib, 'Preamp: -6 dB\nFilter: ON PK Fc 1000 Hz Gain 6 dB Q 1')
    # The manual and imported representation use exactly the same compiler.
    manual = Preset(); lib.peq_default(C.byref(manual))
    manual.count, manual.bypass, manual.preamp = 1, 0, -6
    manual.bands[0] = Band(1, 0, 1000, 6, 1)
    for rate in (8000, 11025, 16000, 22050, 32000, 44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000):
        a, b = Engine(), Engine()
        assert lib.peq_compile(C.byref(p), rate, C.byref(a))
        assert lib.peq_compile(C.byref(manual), rate, C.byref(b))
        assert bytes(a) == bytes(b)
        assert abs(20 * math.log10(response(a, rate, 1000))) < 1e-7
        d = DSP(); lib.peq_reset(C.byref(d), rate, 1, C.byref(p))
        samples = [0.05*math.sin(2*math.pi*1000*i/rate) for i in range(rate//5)]
        out = process(lib, d, samples)
        gain = math.sqrt(sum(x*x for x in out[rate//10:])/sum(x*x for x in samples[rate//10:]))
        assert abs(20*math.log10(gain)) < .01, (rate, gain)
    # Every band, both shelf endpoints, gain/Q limits and low-rate fallback.
    for index in range(10):
        p = Preset(); lib.peq_default(C.byref(p)); p.bypass = 0
        p.bands[index].enabled = 1; p.bands[index].gain = -6
        e = Engine(); assert lib.peq_compile(C.byref(p), 48000, C.byref(e))
        assert abs(20*math.log10(response(e, 48000, p.bands[index].frequency)) + 6) < 1e-7
    for kind in (1, 2):
        for q in (0.1, 1/math.sqrt(2), 10):
            for gain in (-24, 24):
                p.bands[9] = Band(1, kind, 1000, gain, q)
                e = Engine(); assert lib.peq_compile(C.byref(p), 48000, C.byref(e))
                assert abs(20*math.log10(response(e, 48000, 0 if kind == 1 else 24000))-gain) < 1e-7
                for c in e.c:
                    assert abs(c.a2) < 1 and 1+c.a1+c.a2 > 0 and 1-c.a1+c.a2 > 0
    p.bands[9] = Band(1, 0, 16000, 6, 1)
    e = Engine(); assert lib.peq_compile(C.byref(p), 8000, C.byref(e)) and not e.bypass
    assert (e.c[9].b0, e.c[9].a1) == (1, 0)  # only the unrepresentable band is skipped
    p = parse(lib, '\n'.join(f'Filter: ON PK Fc {100+i*1000} Hz Gain 6 dB Q 1' for i in range(10)))
    d = DSP(); lib.peq_reset(C.byref(d), 48000, 2, C.byref(p))
    clipped = process(lib, d, [1., -1.] * 20000, 2)
    assert all(math.isfinite(x) and -1 <= x <= 1 for x in clipped)
    # Block splitting and stereo independence; no file I/O or allocation in process.
    a, b = DSP(), DSP()
    for d in (a, b): lib.peq_reset(C.byref(d), 48000, 2, C.byref(p))
    signal = [x for i in range(10000) for x in (0.02*math.sin(i*.13), 0.)]
    entire = process(lib, a, signal, 2)
    split = process(lib, b, signal[:2346], 2) + process(lib, b, signal[2346:], 2)
    assert entire == split and all(x == 0 for x in entire[1::2])
    p.bypass = 1
    assert lib.peq_update(C.byref(a), C.byref(p))
    process(lib, a, [0., 0.] * 960, 2)
    assert process(lib, a, signal, 2) == list((C.c_float * len(signal))(*signal))
    # Rapid updates queue the latest target without restarting the current fade.
    p.bypass = 0
    assert lib.peq_update(C.byref(a), C.byref(p))
    process(lib, a, [0., 0.] * 100, 2)
    old_ramp = a.ramp
    p.preamp = -24
    assert lib.peq_update(C.byref(a), C.byref(p)) and a.ramp == old_ramp
    process(lib, a, [0., 0.] * 2000, 2)
    assert not a.ramp and not a.waiting and abs(a.current.gain-10**(-24/20)) < 1e-12
    lib.peq_reset(C.byref(a), 96000, 1, C.byref(p))
    assert process(lib, a, [0.] * 1000) == [0.] * 1000
    # Decaying tails settle at a ~-590 dB normal-float residue, never in the denormal range.
    tail = process(lib, a, [0.5] + [0.] * 96000)
    state = [abs(a.current.z[0][i][j]) for i in range(10) for j in range(2)]
    assert all(z < 1e-28 and (z == 0 or z > 1e-300) for z in state) and abs(tail[-1]) < 1e-28
    # A preamp-only change carries filter memory: the crossfade is a pure gain ramp.
    lib.peq_reset(C.byref(a), 48000, 1, C.byref(p))
    tone = [0.1*math.sin(2*math.pi*100*i/48000) for i in range(20000)]
    process(lib, a, tone[:10000])
    p.preamp = -30; assert lib.peq_update(C.byref(a), C.byref(p))
    after = process(lib, a, tone[10000:])
    b = DSP(); p.preamp = -24; lib.peq_reset(C.byref(b), 48000, 1, C.byref(p))
    reference = process(lib, b, tone)[10000:]
    fade = [1 - (1 - 10**(-6/20)) * min(i + 1, 960) / 960 for i in range(10000)]
    assert max(abs(x - r*f) for x, r, f in zip(after, reference, fade)) < 1e-6
    # A band switched off mid-play drains its carried memory before it is skipped, then passes x through.
    p = parse(lib, 'Filter: ON PK Fc 100 Hz Gain 6 dB Q 1')
    lib.peq_reset(C.byref(a), 48000, 1, C.byref(p))
    process(lib, a, tone[:10000])
    p.bands[0].gain = 0; assert lib.peq_update(C.byref(a), C.byref(p))
    process(lib, a, tone[:2000])
    assert all(a.current.z[0][i][j] == 0 for i in range(10) for j in range(2))
    assert process(lib, a, tone) == list((C.c_float * len(tone))(*tone))
    print('PEQ DSP: C PCM response, ten bands, shelves, rates, bypass, clipping, channels and updates passed.')

# Host stand-ins for the stock services peq_platform.h maps on the device.
SHIM_H = r"""
#include <dirent.h>
#include <sys/stat.h>
typedef int (*handler)(void *, void *);
extern volatile unsigned char g_equalizer_flag;
""" + ''.join(f'{r} {n}({a});\n' for n in """
list_item_create label_create list_view_create scroll_view_create widget_use_style
widget_set_text_utf8 widget_on widget_get_prop_int widget_set_prop_int widget_destroy_children
widget_resize scroll_view_set_offset widget_invalidate_force timer_add timer_remove
navigator_back write_int_config
""".split() for r, a in [PROTOTYPES[n]]) + r"""
"""
SHIM = r"""
static struct { int parent, h, bg; char text[160]; handler click, destroy, keyup; void *ctx; } w[4096];
static int count = 1, timers, removed, backs;
static int (*timer_fn)(const void *);
volatile unsigned char g_equalizer_flag;
int stock_eq_trampoline(int mode) { return mode; }
static void *make(void *parent, int h) {
    ++count; w[count].parent = (int)(long)parent; w[count].h = h;
    w[count].text[0] = 0; w[count].click = 0; w[count].bg = 0; return (void *)(long)count;
}
void *list_item_create(void *p, int x, int y, int ww, int h) { (void)x; (void)y; (void)ww; return make(p, h); }
void *label_create(void *p, int x, int y, int ww, int h) { (void)x; (void)y; (void)ww; return make(p, h); }
void *list_view_create(void *p, int x, int y, int ww, int h) { (void)x; (void)y; (void)ww; return make(p, h); }
void *scroll_view_create(void *p, int x, int y, int ww, int h) { (void)x; (void)y; (void)ww; return make(p, h); }
int widget_use_style(void *x, const char *s) { (void)x; (void)s; return 0; }
int widget_set_text_utf8(void *x, const char *s) { snprintf(w[(long)x].text, 160, "%s", s); return 0; }
unsigned widget_on(void *x, unsigned type, handler f, void *ctx) {
    long i = (long)x;
    if (type == 0x10c) { w[i].click = f; w[i].ctx = ctx; }
    else if (type == 0x0c) w[i].destroy = f;
    else w[i].keyup = f;
    return 1;
}
int widget_get_prop_int(void *x, const char *k, int d) { return (long)x == 1 && !strcmp(k, "h") ? 290 : d; }
int widget_set_prop_int(void *x, const char *k, int v) { if (!strcmp(k, "style:normal:bg_color")) w[(long)x].bg = v; return 0; }
int widget_destroy_children(void *x) { (void)x; count = 1; return 0; }
int widget_resize(void *x, int ww, int h) { (void)ww; w[(long)x].h = h; return 0; }
int scroll_view_set_offset(void *x, int a, int b) { (void)x; (void)a; (void)b; return 0; }
int widget_invalidate_force(void *x, void *y) { (void)x; (void)y; return 0; }
unsigned timer_add(int (*f)(const void *), void *ctx, unsigned ms) { (void)ctx; (void)ms; timer_fn = f; return ++timers; }
int timer_remove(unsigned id) { (void)id; timer_fn = 0; ++removed; return 0; }
int navigator_back(void) { return ++backs; }
static int eqflag = -1;
int write_int_config(int v, const char *s, const char *k) { if (!strcmp(s, "PLAYSET") && !strcmp(k, "EQFLAG")) eqflag = v; return 0; }
int shim_eqflag(void) { return eqflag; }

int peq_page_init(void *page, void *context);
int shim_open(void) { count = 1; w[1].destroy = w[1].keyup = 0; return peq_page_init((void *)1, 0); }
int shim_pending(void) { return timer_fn != 0; }
int shim_removed(void) { return removed; }
unsigned char shim_flag(void) { return g_equalizer_flag; }
void shim_run(void) { int (*f)(const void *) = timer_fn; timer_fn = 0; if (f) f(0); }
/* Click the row whose label starts with text; optionally let the deferred render run. */
int shim_click(const char *text, int run) {
    for (int i = 2; i <= count; ++i)
        if (!strncmp(w[i].text, text, strlen(text)) && w[w[i].parent].click) {
            int p = w[i].parent;
            w[p].click(w[p].ctx, 0);
            if (run) shim_run();
            return 1;
        }
    return 0;
}
void shim_return(void) { int event[8] = {0}; event[6] = 170; w[1].keyup(0, event); shim_run(); }
void shim_close(void) { w[1].destroy(0, 0); }
const char *shim_title(void) {
    for (int i = 2; i <= count; ++i) if (w[i].parent == 1 && w[i].h == 48) return w[i].text;
    return "";
}
int shim_list_height(void) { return w[2].h; } /* the list view is the page's first child */
unsigned shim_list_bg(void) { return (unsigned)w[2].bg; }
"""

def editor_check(lib, tmp):
    """The editor's promises, driven through its real click and render paths."""
    (tmp/'shim.h').write_text(SHIM_H)
    (tmp/'shim.c').write_text('#include "peq.h"\n' + SHIM)
    ui = compile_host(tmp, 'peq_ui.so', ROOT/'patch/peq_ui.c', ROOT/'patch/peq.c', tmp/'shim.c',
                      '-I', ROOT/'patch', '-include', tmp/'shim.h')
    ui.shim_title.restype = C.c_char_p
    data, saved = tmp/'root/mnt/data', tmp/'root/mnt/data/peq-presets'
    saved.mkdir(parents=True); (tmp/'root/mnt/mmc/EQ').mkdir(parents=True)
    active = data/'peq-active'
    def preset(**band):
        p = Preset(); lib.peq_default(C.byref(p)); p.bypass = 0
        for k, v in band.items(): setattr(p.bands[0], k, v)
        return p
    def read():
        p = Preset(); assert lib.peq_load(bytes(active), C.byref(p)); return p
    def click(text): assert ui.shim_click(text.encode(), 1), (text, ui.shim_title())
    title = lambda: ui.shim_title().decode()

    assert lib.peq_save(bytes(active), C.byref(preset(enabled=1)), 1) == 1
    # With the stock flag clear no filter runs, so the saved ON reads OFF.
    assert ui.shim_open() == 0 and title() == 'PEQ'
    # The switch writes the stock config key, so boot restores it; the flag follows the preset.
    click('PEQ: OFF'); assert ui.shim_eqflag() == 1 and ui.shim_flag() == 1
    click('PEQ: ON'); assert ui.shim_eqflag() == 0 and ui.shim_flag() == 0
    ui.shim_close(); assert ui.shim_open() == 0; click('PEQ: OFF')
    full = ui.shim_list_height()
    # iPod rows are transparent, so the list itself must paint black, not the theme's light card.
    ui.shim_list_bg.restype = C.c_uint; assert ui.shim_list_bg() == 0xff000000
    # Bypass switches at once but keeps unapplied band edits out of the active preset.
    click('1 ON'); click('Raise gain'); click('Raise gain'); ui.shim_return()
    click('PEQ: ON')
    assert read().bypass == 1 and read().bands[0].gain == 0 and ui.shim_flag() == 0
    click('Apply changes')
    assert read().bands[0].gain == 1 and read().bypass == 1 and title() == 'Applied'
    # A band edit sets the preamp to minus the combined response's peak: here the one +1 dB band.
    assert abs(read().preamp + 1) < 0.01, read().preamp
    # A message takes the title bar; the list keeps every row.
    assert ui.shim_list_height() == full == 240
    # Loading into the editor does not activate it.
    assert lib.peq_save(bytes(saved/'HD650.peq'), C.byref(preset(enabled=1, gain=-3.0)), 1) == 1
    before = active.read_bytes()
    click('Presets'); click('HD650.peq')
    assert active.read_bytes() == before and title() == 'Preset loaded; choose Apply to activate'
    click('PEQ: OFF'); click('PEQ: ON')  # any action clears the message
    assert title() == 'PEQ' and read().bands[0].gain == 1  # still the applied preset
    # A failed apply or switch leaves the active preset untouched.
    before = active.read_bytes()
    (data/'peq-active.tmp').mkdir()
    click('Apply changes')
    assert title() == 'Apply failed; active EQ unchanged' and active.read_bytes() == before
    click('PEQ: OFF')
    assert title() == 'Switch failed; PEQ unchanged' and active.read_bytes() == before
    (data/'peq-active.tmp').rmdir()
    click('Apply changes'); assert read().bands[0].gain == -3
    # Closing cancels the pending render.
    assert ui.shim_click(b'Presets', 0) and ui.shim_pending()
    removed = ui.shim_removed()
    ui.shim_close()
    assert not ui.shim_pending() and ui.shim_removed() == removed + 1
    ui.shim_open()
    assert title() == 'PEQ'
    # Deleting asks first, removes only the saved copy and leaves the active EQ alone.
    before = active.read_bytes()
    click('Presets'); click('Delete a preset'); click('HD650.peq'); click('Cancel')
    assert (saved/'HD650.peq').exists()
    click('HD650.peq'); click('Delete HD650.peq? Confirm')
    assert not (saved/'HD650.peq').exists() and active.read_bytes() == before
    assert title() == 'Deleted HD650.peq; active EQ unchanged' and not ui.shim_click(b'HD650.peq', 0)
    # Overlapping boosts add up (+6.5 and +6 dB at 1 kHz); cuts alone leave 0 dB.
    p = preset(enabled=1, gain=6.0); p.count = 2; p.bands[1] = p.bands[0]; p.preamp = -1
    assert lib.peq_save(bytes(active), C.byref(p), 1) == 1
    ui.shim_close(); ui.shim_open(); click('1 ON'); click('Raise gain'); ui.shim_return(); click('Apply changes')
    assert abs(read().preamp + 12.5) < 0.05, read().preamp
    click('1 ON'); click('Band: ON'); ui.shim_return(); click('2 ON'); click('Band: ON'); ui.shim_return(); click('Apply changes')
    assert math.copysign(1, read().preamp) == 1 and read().preamp == 0, read().preamp  # +0: shown as 0.0
    print('PEQ editor: bypass, apply, auto preamp, load, failed saves, delete and close passed.')

# Drives patch/peq_player.c the way hciplayer's af chain does. Built 32-bit like the device,
# so the file's ABI asserts hold; checked against the shared DSP driven directly.
PLAYER = r"""
#include <assert.h>
#include "peq.h"
typedef struct { void *audio; int len, rate, nch, format, bps; } af_data;
typedef struct af_instance {
    const void *info;
    int (*control)(struct af_instance *, int, void *);
    void (*uninit)(struct af_instance *);
    af_data *(*play)(struct af_instance *, af_data *);
    void *setup;
    af_data *data;
    struct af_instance *next, *prev;
    double delay, mul;
} af_instance;
typedef struct { peq_dsp dsp; peq_preset preset; } player_state;
int peq_open(af_instance *af);

static int left = -1; /* calloc calls before one fails; -1: never */
void *test_calloc(size_t n, size_t size) {
    if (!left--) return 0;
    void *p = malloc(n * size);
    return p ? memset(p, 0, n * size) : p;
}

static peq_preset active(double preamp, double gain) {
    peq_preset p;
    peq_default(&p);
    p.bypass = 0; p.preamp = preamp; p.count = 1;
    p.bands[0] = (peq_band){1, 0, 1000, gain, 1};
    assert(peq_save(PEQ_ACTIVE, &p, 1) == 1);
    return p;
}

static int negotiate(af_instance *af, af_data *in) { return af->control(af, 0x10000100, in); }

/* One block through the filter equals the same block through the reference DSP, and is filtered. */
static void same(af_instance *af, peq_dsp *ref, int rate, int nch) {
    float a[1024], b[1024], in[1024];
    unsigned frames = 1024 / nch;
    for (int i = 0; i < 1024; ++i) a[i] = b[i] = in[i] = 0.5f * sinf(i * 0.05f);
    af_data d = {a, (int)(frames * nch * 4), rate, nch, 0x1d, 4};
    assert(af->play(af, &d) == &d);
    peq_process(ref, b, frames);
    assert(!memcmp(a, b, sizeof(a)) && memcmp(a, in, sizeof(a)));
}

int main(void) {
    af_instance af;
    /* A failed open is cleaned up by af_create calling uninit on the partial state. */
    for (int n = 0; n < 2; ++n) {
        memset(&af, 0, sizeof(af));
        left = n;
        assert(peq_open(&af) == -2);
        af.uninit(&af);
        assert(!af.data && !af.setup);
    }
    left = -1;
    memset(&af, 0, sizeof(af));
    assert(peq_open(&af) == 1 && af.mul == 1 && !af.delay && af.data && af.setup);
    player_state *s = af.setup;

    /* Format negotiation: bad channel counts fail, unsupported rates and formats decline,
       other formats are asked to convert to float, and float is accepted. */
    af_data in = {0, 0, 48000, 0, 0x1d, 4};
    assert(negotiate(&af, 0) == -2);
    assert(negotiate(&af, &in) == -2);
    in.nch = PEQ_CHANNELS + 1; assert(negotiate(&af, &in) == -2);
    in.nch = 2; in.rate = 7999; assert(negotiate(&af, &in) == 2);
    in.rate = 384001; assert(negotiate(&af, &in) == 2);
    in.rate = 48000; in.format = 64; assert(negotiate(&af, &in) == 2);
    peq_preset first = active(-6, 6);
    in.format = 0x11; in.bps = 2;
    assert(negotiate(&af, &in) == 0 && in.format == 0x1d && in.bps == 4);
    assert(in.rate == 48000 && in.nch == 2);
    assert(negotiate(&af, &in) == 1);
    assert(af.data->format == 0x1d && af.data->bps == 4);
    assert(af.data->rate == 48000 && af.data->nch == 2);
    assert(s->dsp.rate == 48000 && s->dsp.channels == 2);
    assert(!memcmp(&s->preset, &first, sizeof(first)));
    peq_dsp ref;
    peq_reset(&ref, 48000, 2, &first);
    same(&af, &ref, 48000, 2);

    /* Buffers not in the negotiated format pass through untouched and leave the state alone. */
    float a[64] = {0.25f}, keep[64];
    memcpy(keep, a, sizeof(a));
    af_data bad[] = {
        {a, 256, 44100, 2, 0x1d, 4}, {a, 256, 48000, 1, 0x1d, 4}, {a, 256, 48000, 2, 0x11, 4},
        {a, 256, 48000, 2, 0x1d, 2}, {a, 252, 48000, 2, 0x1d, 4}, {a, 0, 48000, 2, 0x1d, 4},
    };
    for (unsigned i = 0; i < sizeof(bad) / sizeof(bad[0]); ++i)
        assert(af.play(&af, &bad[i]) == &bad[i] && !memcmp(a, keep, sizeof(a)));
    assert(af.play(&af, 0) == 0);
    same(&af, &ref, 48000, 2);

    /* Live updates arrive through the stock gain query on the playback loop, channel 0 only. */
    float gains[PEQ_BANDS];
    struct { float *gain; int channel; } ext = {gains, 1};
    peq_preset second = active(-3, -4);
    assert(af.control(&af, 0x40001d00, &ext) == 1 && !memcmp(&s->preset, &first, sizeof(first)));
    same(&af, &ref, 48000, 2);
    ext.channel = 0;
    assert(af.control(&af, 0x40001d00, &ext) == 1 && !memcmp(&s->preset, &second, sizeof(second)));
    assert(peq_update(&ref, &second));
    for (int i = 0; i < 4; ++i) same(&af, &ref, 48000, 2); /* through the crossfade */
    /* An unchanged or unreadable active file keeps the current filter. */
    assert(af.control(&af, 0x40001d00, &ext) == 1);
    FILE *f = fopen(PEQ_ACTIVE, "wb");
    assert(f && fputs("junk", f) >= 0 && !fclose(f));
    assert(af.control(&af, 0x40001d00, &ext) == 1 && !memcmp(&s->preset, &second, sizeof(second)));
    same(&af, &ref, 48000, 2);
    /* The stock graphic gains read back as flat; malformed queries fail. */
    for (int i = 0; i < PEQ_BANDS; ++i) gains[i] = 1;
    assert(af.control(&af, 0x40001d01, &ext) == 1);
    for (int i = 0; i < PEQ_BANDS; ++i) assert(gains[i] == 0);
    assert(af.control(&af, 0x40001d00, 0) == -2);
    ext.channel = PEQ_CHANNELS; assert(af.control(&af, 0x40001d00, &ext) == -2);
    ext.channel = -1; assert(af.control(&af, 0x40001d00, &ext) == -2);
    ext.channel = 0; ext.gain = 0; assert(af.control(&af, 0x40001d00, &ext) == -2);
    assert(af.control(&af, 0x20000300, 0) == 1 && af.control(&af, 0x12345, 0) == -1);

    /* A new track renegotiates: new rate and channels, the active preset reread, fresh state. */
    peq_preset third = active(0, 3);
    in = (af_data){0, 0, 96000, 1, 0x1d, 4};
    assert(negotiate(&af, &in) == 1 && s->dsp.rate == 96000 && s->dsp.channels == 1);
    assert(!memcmp(&s->preset, &third, sizeof(third)));
    peq_reset(&ref, 96000, 1, &third);
    same(&af, &ref, 96000, 1);
    memcpy(a, keep, sizeof(a));
    af_data old = {a, 256, 48000, 2, 0x1d, 4};
    assert(af.play(&af, &old) == &old && !memcmp(a, keep, sizeof(a)));
    /* Without an active file a track starts on the defaults. */
    assert(!unlink(PEQ_ACTIVE));
    in.rate = 44100;
    assert(negotiate(&af, &in) == 1);
    peq_preset defaults;
    peq_default(&defaults);
    assert(!memcmp(&s->preset, &defaults, sizeof(defaults)));

    af.uninit(&af);
    assert(!af.data && !af.setup);
    return 0;
}
"""

def player_check(tmp):
    """hciplayer's filter: negotiation, track changes, live updates and cleanup."""
    root = tmp/'player'
    (root/'mnt/data').mkdir(parents=True)
    (tmp/'player_test.c').write_text(PLAYER)
    binary = tmp/'player_test'
    sources = [ROOT/'patch/peq_player.c', ROOT/'patch/peq.c', tmp/'player_test.c']
    subprocess.run(['cc', '-m32', '-DPEQ_HOST', f'-DPEQ_ROOT="{root}"', '-Dcalloc=test_calloc',
                    '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT/'patch'),
                    *map(str, sources), '-lm', '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
    print('PEQ player: negotiation, pass-through, live updates, track changes and cleanup passed.')

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='q2-peq-check-') as directory:
        tmp = pathlib.Path(directory); lib = library(tmp)
        parser_check(lib, tmp)
        dsp_check(lib)
        editor_check(lib, tmp)
        player_check(tmp)
