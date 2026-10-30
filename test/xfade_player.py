#!/usr/bin/env python3
"""Crossfade in the built player (patch/peq_player.c crossfade) under Unicorn: the MIPS build of
the filter, as test/peq.py's crossfade_check drives the host build.

A track's last seconds are held back (half of each block put out once the hold window opens) and
mixed, equal power, under the next instance's first frames, at that track's rate; no fade asked
plays every block whole.
Usage: test/xfade_player.py BUILD_DIR"""
import math, pathlib, re, struct, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
from build import fileoff, load_elf, symbols
from peq import EQ_OPEN_SLOT
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import *

out = pathlib.Path(sys.argv[1])/'peq'
raw = (out/'hciplayer').read_bytes()
ps = symbols(out/'peq.elf')
assert struct.unpack_from('<I', raw, fileoff(raw, EQ_OPEN_SLOT))[0] == ps['peq_open']
DONE, STUBS, HEAP, STACK = 0x2000000, 0x2800000, 0x3000000, 0x40f0000
WRITTEN_PTS, LENGTH, MPCTX = 0x44641c, 0xb10e84, 0xaf9e30  # peq_player.c decoded(), LENGTH, MPCTX

u = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
u.ctl_set_cpu_model(UC_CPU_MIPS32_24KF)
load_elf(u, raw)
for base, size in ((DONE, 0x10000), (STUBS, 0x1000), (HEAP, 0x1000000), (STACK - 0xf0000, 0x100000)):
    u.mem_map(base, size)
u.reg_write(UC_MIPS_REG_CP0_STATUS, u.reg_read(UC_MIPS_REG_CP0_STATUS) | 1 << 29 | 1 << 26)  # CU1, FR
imports = {}  # each peq_lib_* stub's GOT word (peq_imports.S) points at a stub of our own
for name, hi, lo in re.findall(r'peq_lib_(\w+):\nlui \$gp.*\nori \$gp.*\nlui \$t8, (\d+)\nori \$t8, \$t8, (\d+)', (out/'peq_imports.S').read_text()):
    imports[STUBS + 4*len(imports)] = name
    u.mem_write(int(hi) << 16 | int(lo), struct.pack('<I', STUBS + 4*(len(imports)-1)))
heap, clock, pts = [HEAP], [10**9], [-1.0]

def w(p, *v): u.mem_write(p, struct.pack('<' + 'I'*len(v), *v))
def r(p): return struct.unpack('<I', u.mem_read(p, 4))[0]
def a(n): return u.reg_read((UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3)[n])
def f12(): return struct.unpack('<d', struct.pack('<Q', u.reg_read(UC_MIPS_REG_F12)))[0]
def f12s(): return struct.unpack('<f', struct.pack('<I', u.reg_read(UC_MIPS_REG_F12) & 0xffffffff))[0]
def ret_d(x): u.reg_write(UC_MIPS_REG_F0, struct.unpack('<Q', struct.pack('<d', x))[0])
def ret_f(x): u.reg_write(UC_MIPS_REG_F0, struct.unpack('<I', struct.pack('<f', x))[0])
def alloc(n, align=16):
    p = (heap[0] + align - 1) & ~(align - 1)
    heap[0] = p + n
    u.mem_write(p, bytes(n))
    return p
def cstr(p): return bytes(u.mem_read(p, 256)).split(b'\0')[0]
flag = alloc(4)  # /tmp/q2xfade, demo's int
w(LENGTH, 10)
sh = alloc(16)  # sh_audio with no codec: not DSD
mp = alloc(64)
w(mp + 0x2c, sh), w(mp + 0x34, sh)
w(MPCTX, mp)

def libc(u, address, size, _):
    """What the filter calls: allocation, strings, libm, the clock and demo's shared ints."""
    n, result = imports[address], 0
    if n in ('malloc', 'calloc'): result = alloc(a(0) * (a(1) if n == 'calloc' else 1))
    elif n == 'free': pass
    elif n in ('memcpy', 'memmove'): u.mem_write(a(0), bytes(u.mem_read(a(1), a(2)))); result = a(0)
    elif n == 'memset': u.mem_write(a(0), bytes([a(1) & 255]) * a(2)); result = a(0)
    elif n == 'memcmp':
        x, y = bytes(u.mem_read(a(0), a(2))), bytes(u.mem_read(a(1), a(2)))
        result = (x > y) - (x < y)
    elif n == 'strcmp': x, y = cstr(a(0)), cstr(a(1)); result = (x > y) - (x < y)
    elif n == 'strlen': result = len(cstr(a(0)))
    elif n == 'clock_gettime': w(a(1), clock[0] // 10**9, clock[0] % 10**9)
    elif n == 'fopen': result = 0  # no saved EQ: the defaults, bypass
    elif n == 'open': result = 5 if cstr(a(0)) == b'/tmp/q2xfade' else -1
    elif n == 'mmap64': result = flag
    elif n == 'close': pass
    elif n in ('sinf', 'cosf'): ret_f(getattr(math, n[:3])(f12s()))
    elif n in ('sin', 'cos', 'exp', 'log', 'sqrt'): ret_d(getattr(math, n)(f12()))
    elif n == 'pow': ret_d(f12() ** struct.unpack('<d', struct.pack('<Q', u.reg_read(UC_MIPS_REG_F14)))[0])
    else: raise AssertionError(n)
    u.reg_write(UC_MIPS_REG_V0, result & 0xffffffff)
    u.reg_write(UC_MIPS_REG_PC, u.reg_read(UC_MIPS_REG_RA))
u.hook_add(UC_HOOK_CODE, libc, begin=STUBS, end=STUBS + 0xfff)
def written_pts(u, address, size, _):
    ret_d(pts[0])
    u.reg_write(UC_MIPS_REG_PC, u.reg_read(UC_MIPS_REG_RA))
u.hook_add(UC_HOOK_CODE, written_pts, begin=WRITTEN_PTS, end=WRITTEN_PTS)

def call(fn, *args):
    for i, value in enumerate(args): u.reg_write((UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3)[i], value)
    u.reg_write(UC_MIPS_REG_SP, STACK), u.reg_write(UC_MIPS_REG_RA, DONE)
    u.emu_start(fn, DONE, count=100_000_000)
    return u.reg_read(UC_MIPS_REG_V0)

def track(rate):
    """A filter instance negotiated for float stereo at rate, as the player adds one per file."""
    af, data = alloc(48), alloc(24)
    assert call(ps['peq_open'], af) == 1
    w(data, 0, 0, rate, 2, 0x1d, 4)
    assert call(r(af + 4), af, 0x10000100, data) == 1
    return af

BUF, DATA, MAX = alloc(8 * 4096), alloc(24), 4096
def block(af, frames, n, level, rate):
    """One stereo block: channel 0 a ramp from n (the track's frame count), channel 1 level. Returns
    the frames put out and them as (ch0, ch1) pairs."""
    pcm = []
    for i in range(frames): pcm += [float(n + i), level]
    u.mem_write(BUF, struct.pack(f'<{2 * frames}f', *pcm))
    pts[0] = (n + frames) / rate
    w(DATA, BUF, frames * 8, rate, 2, 0x1d, 4)
    assert call(r(af + 12), af, DATA) == DATA and r(DATA) == BUF and r(DATA + 4) % 8 == 0
    k = r(DATA + 4) // 8
    got = struct.unpack(f'<{2 * k}f', u.mem_read(BUF, 8 * k))
    return k, list(zip(got[::2], got[1::2]))
def uninit(af): call(r(af + 8), af)

def hold(rate, length, fade_ms, start, block_frames=1024):
    """The outgoing track from start seconds to its end: frames put out, in order, and the held count."""
    w(flag, fade_ms), w(LENGTH, length)
    af = track(rate)
    n = out = start * rate
    window = length - 2.0 * fade_ms / 1000 - 2.0
    while n < length * rate:
        k, got = block(af, block_frames, n, 1.0, rate)
        if (n + block_frames) / rate <= window: assert k == block_frames, (n, k)
        for c0, c1 in got: assert c0 == float(out) and c1 == 1.0, (out, c0, c1); out += 1
        n += block_frames
    uninit(af)
    return out, n - out

def mix(rate, held, out, seconds=2, block_frames=1024, step=1.0):
    """The next track's first seconds: the tail (step held frames a frame) under it, equal power, then
    alone, every frame out."""
    af = track(rate)
    w(flag, 0)  # the next fade switched off must still finish this one
    m = mixed = 0
    while m < seconds * rate:
        k, got = block(af, block_frames, m, 0.0, rate)
        assert k == block_frames, (m, k)
        for i, (c0, c1) in enumerate(got):
            if mixed < held:
                p = (mixed + 0.5) / held * 1.5707963
                assert abs(c1 - math.cos(p)) < 1e-4, (mixed, c1, math.cos(p))
                # the ramp at c1's own gain (the rotated gains drift 1e-5 over a long fade), float32
                assert abs(c0 - ((m + i) * math.sqrt(1 - c1 * c1) + (out + mixed * step) * c1)) < 1 + abs(c0) * 1e-6, (mixed, c0)
            else:
                assert c0 == float(m + i) and c1 == 0.0, (m + i, c0, c1)
            mixed += 1
        m += block_frames
    uninit(af)
    assert mixed >= held

# A 1 s fade at the end of a 10 s track: the hold opens 4 s before the end and keeps one second;
# the next track mixes it under its start, from the ring the instances share.
out, held = hold(48000, 10, 1000, 0)
assert held == 48000, held
mix(48000, held, out)
# A real song: 5 s at 44.1 kHz, the hold starting 12 s before the end of 4 minutes.
out, held = hold(44100, 240, 5000, 225)
assert held == 5 * 44100, held
mix(44100, held, out, seconds=6)
# Odd block sizes at the longest fade, 15 s at 48 kHz: the hold wraps the ring.
out, held = hold(48000, 60, 15000, 20, block_frames=1000)
assert held == 15 * 48000, held
mix(48000, held, out, seconds=16, block_frames=333)
# The next track at another rate: the 48 kHz tail plays over 44100 frames at 44.1 kHz, interpolated.
out, held = hold(48000, 10, 1000, 0)
mix(44100, 44100, out, step=48000 / 44100)
# No fade asked: every block whole.
w(flag, 0), w(LENGTH, 10)
af = track(48000)
for n in range(0, 10 * 48000, 1024):
    k, got = block(af, 1024, n, 1.0, 48000)
    assert k == 1024 and got[0] == (float(n), 1.0)
uninit(af)
print('Player crossfade (MIPS build): the hold window, half-rate emission in order, the equal-power '
      'mix and whole blocks with no fade passed.')
