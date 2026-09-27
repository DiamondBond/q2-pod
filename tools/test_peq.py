#!/usr/bin/env python3
"""Run the actual C parser/storage and PCM DSP checks."""
import cmath
import ctypes as C
import math
import pathlib
import subprocess
import tempfile

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

def library(tmp):
    path = tmp/'peq.so'
    subprocess.run(['cc', '-DPEQ_HOST', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    str(ROOT/'patch/peq.c'), '-lm', '-o', str(path)], check=True)
    lib = C.CDLL(str(path))
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
    assert abs(p.bands[2].q - 1 / math.sqrt(2)) < 1e-15
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
    e = Engine(); assert lib.peq_compile(C.byref(p), 8000, C.byref(e)) and e.bypass
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
    print('PEQ DSP: C PCM response, ten bands, shelves, rates, bypass, clipping, channels and updates passed.')

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='q2-peq-check-') as directory:
        tmp = pathlib.Path(directory); lib = library(tmp)
        parser_check(lib, tmp)
        dsp_check(lib)
