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
    _fields_ = [('count', C.c_int), ('bypass', C.c_int), ('preamp', C.c_double), ('bands', Band * 30),
                ('balance', C.c_double)]

class Error(C.Structure):
    _fields_ = [('line', C.c_uint), ('reason', C.c_char_p)]

class Coeff(C.Structure):
    _fields_ = [(k, C.c_double) for k in ('b0', 'b1', 'b2', 'a1', 'a2')]

class Engine(C.Structure):
    _fields_ = [('c', Coeff * 30), ('z', ((C.c_double * 2) * 30) * 8),
                ('gain', C.c_double * 8), ('bypass', C.c_int), ('used', C.c_int), ('only', C.c_int * 30)]

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
    assert parse(lib, single * 30).count == 30
    assert parse(lib, single + 'Filter 2: OFF PK Fc 0 Hz Gain 0.0 dB Q 0.000').count == 1  # blank slot
    assert parse(lib, '').count == 0
    # Import is pure. Saving succeeds only after validation and explicit collision confirmation.
    active, saved = tmp/'active', tmp/'preset'
    for path in (active, saved): assert lib.peq_save(bytes(path), C.byref(p), 0) == 1
    baseline = bytes(p)
    failures = [
        (single * 30 + single.replace('ON', 'OFF'), 31, '30 bands'),
        ('Preamp: 24 dB\nPreamp: 1 dB', 2, 'summed'),
        ('Preamp: -61 dB', 1, 'preamp'),
        ('Preamp: -3', 1, 'expected'),
        ('\nGraphicEQ: 20 0; 20000 0', 2, 'unsupported'),
        ('Include: other.txt', 1, 'unsupported'), ('Channel: C', 1, 'only channels'), ('Channel:', 1, 'expected Channel'),
        ('Channel: L\nPreamp: -13 dB', 2, 'differ'),
        ('Eval: x=1', 1, 'unsupported'), ('garbage', 1, 'unsupported'),
        (single.replace(' Q .7', ''), 1, 'requires Q'),
        (single.replace('PK', 'HP'), 1, 'type'),
        (single.replace('PK', 'LS 6dB'), 1, 'form'),
        (single.replace('Q .7', 'BW Oct 1'), 1, 'form'),
        (single.replace('1e3', '`1000`'), 1, 'number'),
        (single.replace('Filter:', 'Filter x:'), 1, 'label'),
        (single + 'Filter: ON PK Fc 19 Hz Gain 0 dB Q 1', 2, 'range'),
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
    # APO Channel scopes: bands follow it, per-channel preamps become preamp + balance.
    scoped = parse(lib, 'Preamp: -3 dB\nChannel: L\nPreamp: -1.5 dB\n' + single + 'Channel: R\nPreamp: -0.5 dB\n'
                        + single + 'Channel: L R\n' + single + 'Channel: all\n' + single.replace('ON', 'OFF'))
    assert [b.enabled for b in scoped.bands[:4]] == [2, 3, 1, 0]
    assert parse(lib, single * 30 + 'Filter: OFF PK Fc 0 Hz Gain 0 dB Q 0').count == 30  # blank slots do not count
    assert scoped.preamp == -3.5 and scoped.balance == 1  # left 1 dB below right
    # v1 files (no balance) still load, with the balance centred.
    v1 = tmp/'v1'
    v1.write_bytes(b'Q2PEQ01\0' + bytes(q)[:16 + 10*32])
    assert lib.peq_load(bytes(v1), C.byref(p)) and bytes(p) == bytes(q)  # q's bands 11-30 are the defaults
    v1.write_bytes(b'Q2PEQ02\0' + bytes(q)[:-8])
    assert not lib.peq_load(bytes(v1), C.byref(p))
    v1.write_bytes(b'')
    assert not lib.peq_load(bytes(v1), C.byref(p))
    assert not lib.peq_save(bytes(tmp/'missing'/'preset'), C.byref(q), 1)
    print('PEQ parser/storage: syntax, limits, transaction failures, confirmation and persistence passed.')

def response(engine, rate, frequency, ch=0):
    if engine.bypass: return 1
    z = cmath.exp(-2j * math.pi * frequency / rate)
    result = complex(engine.gain[ch])
    for c, only in zip(engine.c, engine.only):
        if not only or only == ch + 1: result *= (c.b0 + c.b1*z + c.b2*z*z)/(1 + c.a1*z + c.a2*z*z)
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
    assert not a.ramp and not a.waiting and abs(a.current.gain[0]-10**(-24/20)) < 1e-12
    lib.peq_reset(C.byref(a), 96000, 1, C.byref(p))
    assert process(lib, a, [0.] * 1000) == [0.] * 1000
    # Decaying tails settle at a ~-590 dB normal-float residue, never in the denormal range.
    tail = process(lib, a, [0.5] + [0.] * 96000)
    state = [abs(a.current.z[0][i][j]) for i in range(30) for j in range(2)]
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
    assert all(a.current.z[0][i][j] == 0 for i in range(30) for j in range(2)) and a.current.used == 1
    assert process(lib, a, tone) == list((C.c_float * len(tone))(*tone))
    # One-channel bands and balance: left gets the band and 2 dB less, right neither.
    p = parse(lib, 'Channel: L\nFilter: ON PK Fc 1000 Hz Gain 6 dB Q 1'); p.balance = 2
    e = Engine(); assert lib.peq_compile(C.byref(p), 48000, C.byref(e))
    assert abs(20*math.log10(response(e, 48000, 1000, 0)) - 4) < 1e-7
    assert abs(20*math.log10(response(e, 48000, 1000, 1))) < 1e-12
    lib.peq_reset(C.byref(a), 48000, 2, C.byref(p))
    out = process(lib, a, [x for v in tone for x in (v, v)], 2)
    assert out[1::2] == list((C.c_float * len(tone))(*tone))
    gain = math.sqrt(sum(x*x for x in out[10000::2])/sum(x*x for x in tone[5000:]))
    assert abs(20*math.log10(gain) + 2) < .1, gain  # 100 Hz: the band barely reaches it
    # A both-channel band narrowed to the left drops the right's carried memory.
    p.bands[0].enabled = 1; lib.peq_reset(C.byref(a), 48000, 2, C.byref(p)); process(lib, a, [.5, .5] * 100, 2)
    p.bands[0].enabled = 2; assert lib.peq_update(C.byref(a), C.byref(p)); process(lib, a, [0., 0.] * 2000, 2)
    assert a.current.z[1][0][0] == a.current.z[1][0][1] == 0 and a.current.z[0][0][0]
    print('PEQ DSP: C PCM response, 30 bands, shelves, rates, bypass, clipping, channels, balance and updates passed.')

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
navigator_back write_int_config widget_factory widget_factory_create_widget widget_set_prop_str
widget_get_text widget_set_focused widget_lookup window_manager pages_set_active_by_name
""".split() for r, a in [PROTOTYPES[n]]) + r"""
"""
SHIM = r"""
static struct { int parent, h, bg; char text[160]; handler click, destroy, keyup, change, focus; void *ctx; } w[4096];
static int count = 1, timers, removed, backs;
static int (*timer_fn)(const void *);
volatile unsigned char g_equalizer_flag;
int stock_eq_trampoline(int mode) { return mode; }
static void *make(void *parent, int h) {
    ++count; w[count].parent = (int)(long)parent; w[count].h = h;
    w[count].text[0] = 0; w[count].click = w[count].change = w[count].focus = 0; w[count].bg = 0; return (void *)(long)count;
}
/* The value menu's edit: its text, the keyboard it asks for, whether it took focus. */
static int edit_widget, focused;
static char keyboard[32];
void *widget_factory(void) { return 0; }
void *widget_factory_create_widget(void *f, const char *type, void *p, int x, int y, int ww, int h) {
    (void)f; (void)x; (void)y; (void)ww; void *e = make(p, h);
    if (!strcmp(type, "edit")) { edit_widget = (int)(long)e; keyboard[0] = 0; focused = 0; }
    return e;
}
int widget_set_prop_str(void *x, const char *k, const char *v) {
    if ((long)x == edit_widget && !strcmp(k, "keyboard")) snprintf(keyboard, sizeof(keyboard), "%s", v);
    return 0;
}
const unsigned *widget_get_text(void *x) {
    static unsigned wide[160];
    unsigned i = 0;
    for (; w[(long)x].text[i]; ++i) wide[i] = (unsigned char)w[(long)x].text[i];
    wide[i] = 0; return wide;
}
int widget_set_focused(void *x, int v) {
    if ((long)x == edit_widget && (focused = v) && w[edit_widget].focus) w[edit_widget].focus(0, 0);
    return 0;
}
/* The stock keyboard window (4000) and its page panel (4001); the page it was switched to. */
static char page[16];
void *window_manager(void) { return (void *)3999L; }
void *widget_lookup(void *x, const char *name, int recursive) {
    (void)recursive;
    if ((long)x == 3999 && !strcmp(name, "kb_default_t9")) return (void *)4000L;
    return (long)x == 4000 && !strcmp(name, "panel") ? (void *)4001L : 0;
}
int pages_set_active_by_name(void *x, const char *name) { if ((long)x == 4001) snprintf(page, sizeof(page), "%s", name); return 0; }
const char *shim_page(void) { return page; }
const char *shim_edit(void) { return edit_widget ? w[edit_widget].text : ""; }
const char *shim_keyboard(void) { return keyboard; }
int shim_focused(void) { return focused; }
/* Typing a value and closing the keyboard: the edit reports EVT_VALUE_CHANGED. */
void shim_run(void);
void shim_type(const char *text) {
    snprintf(w[edit_widget].text, 160, "%s", text);
    w[edit_widget].change(0, 0); shim_run();
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
    else if (type == 0x0e) w[i].change = f;
    else if (type == 0x10e) w[i].focus = f;
    else w[i].keyup = f;
    return 1;
}
int widget_get_prop_int(void *x, const char *k, int d) { return (long)x == 1 && !strcmp(k, "h") ? 290 : d; }
static int selection, offset;
int widget_set_prop_int(void *x, const char *k, int v) {
    if (!strcmp(k, "style:normal:bg_color")) w[(long)x].bg = v;
    if (!strcmp(k, "_ringnav_index")) selection = v;
    return 0;
}
int widget_destroy_children(void *x) { (void)x; count = 1; return 0; }
int widget_resize(void *x, int ww, int h) { (void)ww; w[(long)x].h = h; return 0; }
int scroll_view_set_offset(void *x, int a, int b) { (void)x; (void)a; offset = b; return 0; }
int shim_selection(void) { return selection; }
int shim_offset(void) { return offset; }
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
    click('1 ON'); click('Gain +0.0 dB'); assert title() == 'PEQ Band 1 Gain'; click('+1.0 dB'); ui.shim_return()
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
    ui.shim_close(); ui.shim_open(); click('1 ON'); click('Gain +6.0 dB'); click('+6.5 dB'); ui.shim_return(); click('Apply changes')
    assert read().preamp == -1, read().preamp  # a preamp off Auto (here the preset's) sticks through band edits
    click('Preamp -1.0 dB'); assert title() == 'PEQ Preamp' and ui.shim_selection() == 27  # opens on -1.0
    click('Auto (-12.5 dB)'); click('Apply changes')
    assert abs(read().preamp + 12.5) < 0.05, read().preamp
    click('1 ON'); click('Band: ON'); ui.shim_return(); click('2 ON'); click('Band: ON'); ui.shim_return(); click('Apply changes')
    assert math.copysign(1, read().preamp) == 1 and read().preamp == 0, read().preamp  # +0: shown as 0.0
    # Channels cycle on enabled bands; headroom takes the louder side, balance only turns one down.
    click('1 OFF'); click('Gain +6.5 dB'); click('+7.5 dB'); click('Channels: Both')  # picking a gain turns the band on
    assert title() == 'PEQ Band 1'
    click('Channels: Left'); ui.shim_return()
    # Balance: one row opens a picker, L 12 to R 12 dB in 0.5 dB steps, on the current value.
    click('Balance: Centre'); assert title() == 'PEQ Balance'
    assert (ui.shim_selection(), ui.shim_offset()) == (24, 24 * 48 - 96)  # 5 rows of 48 shown
    click('R 12.0 dB'); assert title() == 'PEQ'; click('Balance: R 12.0 dB')
    assert (ui.shim_selection(), ui.shim_offset()) == (48, 49 * 48 - 240)  # clamped to the end
    ui.shim_return(); assert title() == 'PEQ'; click('Balance: R 12.0 dB'); click('L 0.5 dB'); click('Apply changes')
    r = read(); assert (r.bands[0].enabled, r.balance) == (3, -0.5) and abs(r.preamp + 7.5) < 0.05, (r.bands[0].enabled, r.balance)
    assert ui.shim_click(b'1 ON R', 0) and ui.shim_click(b'Balance: L 0.5 dB', 0)
    # Frequency and Q open a value menu: an edit with the value (keyboard on tap or centre), then Raise/Lower.
    ui.shim_edit.restype = ui.shim_keyboard.restype = C.c_char_p
    edit = lambda: ui.shim_edit().decode()
    ui.shim_close(); ui.shim_open(); click('1 ON R'); click('Frequency 31 Hz')
    assert title() == 'PEQ Band 1 Frequency (Hz)' and edit() == '31' and ui.shim_keyboard() == b'kb_default_t9'
    click('Lower 1 Hz'); click('Lower 1 Hz'); assert edit() == '29'
    click('Step: 1 Hz'); click('Lower 10 Hz'); assert edit() == '20'  # clamped at 20 Hz
    click('Step: 10 Hz'); click('Raise 100 Hz'); assert edit() == '120'
    ui.shim_page.restype = C.c_char_p
    assert not ui.shim_focused(); click('120'); assert ui.shim_focused()  # the centre button opens the keyboard
    assert ui.shim_page() == b'symnum'  # on its number keys
    ui.shim_type(b'2500'); assert edit() == '2500'
    ui.shim_type(b'abc'); assert edit() == '2500'      # not a number: unchanged
    ui.shim_type(b'99999'); assert edit() == '20000'   # clamped like Raise
    ui.shim_type(b'1000.5'); assert edit() == '1000'   # kept exactly, shown whole
    ui.shim_return(); assert title() == 'PEQ Band 1'
    click('Q 1.41'); assert title() == 'PEQ Band 1 Q' and edit() == '1.41'
    click('Raise 0.05'); assert edit() == '1.46'
    ui.shim_type(b'0.7'); assert edit() == '0.70'
    ui.shim_return(); ui.shim_return(); click('Apply changes')
    r = read(); assert (r.bands[0].frequency, round(r.bands[0].q, 9)) == (1000.5, 0.7), (r.bands[0].frequency, r.bands[0].q)
    print('PEQ editor: bypass, apply, auto preamp, channels, balance, frequency and Q, load, failed saves, delete and close passed.')

# Drives patch/peq_player.c the way hciplayer's af chain does. Built 32-bit like the device,
# so the file's ABI asserts hold; checked against the shared DSP driven directly.
PLAYER = r"""
#include <assert.h>
#include "peq.h"
int mp3_toc(const unsigned char *h, unsigned n, double t, double *frac, double *length);
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

char *peq_mpctx; /* the player's MPContext pointer; null: no codec to check */
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
    /* DSD detaches, by the vendor's dsdiff driver or an FFmpeg ffdsd codec; other codecs negotiate. */
    static char *mp[12], *sh[2], *codec[0x3e4 / 4];
    peq_mpctx = (char *)mp; mp[0x2c / 4] = (char *)sh; sh[1] = (char *)codec;
    in.format = 0x1d;
    codec[0x3e0 / 4] = "dsdiff"; assert(negotiate(&af, &in) == 2);
    codec[0x3e0 / 4] = "ffmpeg"; codec[0x3d0 / 4] = "ffdsdmsbf"; assert(negotiate(&af, &in) == 2);
    codec[0x3d0 / 4] = "ffflac"; assert(negotiate(&af, &in) == 1);
    peq_mpctx = 0;
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
    float gains[10]; /* stock's graphic EQ array */
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
    for (int i = 0; i < 10; ++i) gains[i] = 1;
    assert(af.control(&af, 0x40001d01, &ext) == 1);
    for (int i = 0; i < 10; ++i) assert(gains[i] == 0);
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

    /* Exact VBR seeking: a 44.1 kHz stereo MPEG-1 Layer III Xing frame, 3600 s long, whose table
     * puts the first half of the time in the first quarter of the bytes. */
    unsigned char h[192] = {0xff, 0xfb, 0x90, 0x00};
    unsigned frames = 3600 * 44100 / 1152; /* 137812 frames, 3599.98 s */
    memcpy(h + 36, "Xing\0\0\0\x07", 8);
    h[44] = frames >> 24; h[45] = frames >> 16; h[46] = frames >> 8; h[47] = frames;
    for (int i = 0; i < 100; i++) h[52 + i] = i < 50 ? i * 64 / 50 : 64 + (i - 50) * 192 / 50;
    double frac, length;
    assert(mp3_toc(h, sizeof h, 0, &frac, &length) && frac == 0 && fabs(length - frames * 1152.0 / 44100) < 1e-9);
    assert(mp3_toc(h, sizeof h, length / 2, &frac, &length) && fabs(frac - 0.25) < 1e-9);
    assert(mp3_toc(h, sizeof h, length / 4, &frac, &length) && fabs(frac - 0.125) < 1e-9);
    assert(mp3_toc(h, sizeof h, length * 0.995, &frac, &length) && frac > 0.98 && frac < 1);
    assert(mp3_toc(h, sizeof h, length, &frac, &length) && frac == 1);
    assert(!mp3_toc(h, 100, 10, &frac, &length));        /* cut short */
    h[43] = 3;                                            /* no table */
    assert(!mp3_toc(h, sizeof h, 10, &frac, &length));
    h[43] = 7; memcpy(h + 36, "Info", 4);                 /* CBR: stock is already exact */
    assert(!mp3_toc(h, sizeof h, 10, &frac, &length));
    memcpy(h + 36, "Xing", 4); h[1] = 0xfd;               /* Layer III only */
    assert(!mp3_toc(h, sizeof h, 10, &frac, &length));
    h[1] = 0xf3; h[2] = 0x90;                             /* MPEG-2, 22.05 kHz: side info 17, 576 a frame */
    memmove(h + 21, h + 36, 120);
    assert(mp3_toc(h, sizeof h, 0, &frac, &length) && fabs(length - frames * 576.0 / 22050) < 1e-9);
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
    print('PEQ player: negotiation, pass-through, live updates, track changes, cleanup and the Xing seek table passed.')

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='q2-peq-check-') as directory:
        tmp = pathlib.Path(directory); lib = library(tmp)
        parser_check(lib, tmp)
        dsp_check(lib)
        editor_check(lib, tmp)
        player_check(tmp)
