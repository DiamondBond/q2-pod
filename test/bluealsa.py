#!/usr/bin/env python3
"""Run the actual MIPS DROP paths with the encoder signal deliberately delayed.

Usage: python test/bluealsa.py BUILD_DIRECTORY (requires the existing Unicorn).
"""
import pathlib, struct, subprocess, sys
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import *
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
from build import BLUEALSA, BT_DROP, BT_DROP_HANDLER, BT_PCM_CALLERS, segments


def check_drop(raw, queued, caller=None):
    u = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
    for _, (kind, offset, address, _, size, memory, _, _) in segments(raw):
        if kind != 1:
            continue
        start = address & ~4095
        u.mem_map(start, ((address + memory + 4095) & ~4095) - start)
        u.mem_write(address, raw[offset:offset + size])
    u.mem_map(0x1000000, 0x10000)
    pcm, transport, state, stop = 0x1000000, 0x1000200, 0x1000400, 0x1000600
    def word(address, value): u.mem_write(address, struct.pack('<I', value))
    def read(address): return struct.unpack('<I', u.mem_read(address, 4))[0]
    word(pcm, transport)
    word(pcm + 4, transport + 0x50)
    word(state + 0x1c, 48000 * 300)  # the previous track's pacing clock
    word(state + 0x30, 100)
    fifo = [queued]
    locked = [False]
    signals, flushes = [], []
    def hook(u, address, size, _):
        if address == 0x414640:  # stock DROP repoll
            u.emu_stop()
            return
        if address == 0x4140b8:  # stock nonblocking io_pcm_flush
            assert u.reg_read(UC_MIPS_REG_A0) == pcm
            batch = min(fifo[0], 32768)
            fifo[0] -= batch
            flushes.append((batch, locked[0]))
            u.reg_write(UC_MIPS_REG_V0, batch // 2)
        elif address == 0x40b738:  # stock send_signal
            assert u.reg_read(UC_MIPS_REG_A0) == transport + 0x50
            assert not locked[0]
            signals.append(u.reg_read(UC_MIPS_REG_A1))
            u.reg_write(UC_MIPS_REG_V0, 0)
        elif address in (0x430690, 0x4303a0):  # PCM fd mutex
            assert u.reg_read(UC_MIPS_REG_A0) == pcm + 0xc
            assert locked[0] == (address == 0x4303a0)
            locked[0] = address == 0x430690
            u.reg_write(UC_MIPS_REG_V0, 0)
        else:
            return
        u.reg_write(UC_MIPS_REG_PC, u.reg_read(UC_MIPS_REG_RA))
    u.hook_add(UC_HOOK_CODE, hook)
    saved = (UC_MIPS_REG_S0, UC_MIPS_REG_S1, UC_MIPS_REG_S2, UC_MIPS_REG_S7)
    for i, register in enumerate(saved): u.reg_write(register, 0xabcd0000 + i)
    stack = 0x100ff00
    u.reg_write(UC_MIPS_REG_SP, stack)
    u.reg_write(UC_MIPS_REG_A0, pcm)
    u.reg_write(UC_MIPS_REG_RA, stop)
    u.emu_start(BT_DROP, stop, count=1000)
    assert u.reg_read(UC_MIPS_REG_PC) == stop
    assert u.reg_read(UC_MIPS_REG_V0) == 0 and u.reg_read(UC_MIPS_REG_SP) == stack
    assert [u.reg_read(r) for r in saved] == [0xabcd0000 + i for i in range(len(saved))]
    assert signals == [6]
    empty_at_ack = fifo[0] == 0 and all(held for _, held in flushes)
    # New track data is written after the acknowledged DROP, before the encoder
    # finally handles it. The stock handler wrongly discards these samples.
    fifo[0] = 4096
    flush_count = len(flushes)
    u.reg_write(UC_MIPS_REG_S1, pcm)
    u.reg_write(UC_MIPS_REG_S2, state)
    if caller:
        address, offset = caller
        word(stack + 0x54, address)
        buffer = 0x1001000
        if offset is not None:
            ffb = state + offset
            for off, value in ((0, buffer), (4, buffer+128), (8, 1024), (12, 2)):
                word(ffb+off, value)
            u.reg_write(UC_MIPS_REG_S6, buffer+128)
            u.reg_write(UC_MIPS_REG_S5, 960)
        else:
            word(stack+0x40, 0)  # caller's base offset, saved s4
            word(stack+0x4c, 128)  # caller's partial byte offset, saved s7
            word(stack+0x48, 224)  # caller's remaining samples, saved s6
            u.reg_write(UC_MIPS_REG_S6, buffer+128)
            u.reg_write(UC_MIPS_REG_S5, 224)
    u.emu_start(BT_DROP_HANDLER, 0x41463c, count=1000)
    rewound = True
    if caller:
        rewound = u.reg_read(UC_MIPS_REG_S6) == buffer
        if offset is not None:
            rewound &= read(ffb+4)==buffer and u.reg_read(UC_MIPS_REG_S5)==1024
            rewound &= read(ffb)==buffer and read(ffb+8)==1024 and read(ffb+12)==2
        else:
            rewound &= read(stack+0x4c)==0 and read(stack+0x48)==256 and u.reg_read(UC_MIPS_REG_S5)==256
    # Stock repolls at 0x414640; stop before the imported cancellation function.
    return empty_at_ack and fifo[0] == 4096 and len(flushes) == flush_count and read(state + 0x1c) == 0 and read(state + 0x30) == 0xffffffff and rewound


def check(directory):
    directory = pathlib.Path(directory)
    def extract(name):
        return subprocess.check_output(['unsquashfs', '-cat', str(directory / name), BLUEALSA])
    stock, patched = extract('stock.squashfs'), extract('rootfs.squashfs')
    # Execute stock argument construction independently of the reset patch's
    # metadata: it must identify the actual caller's PCM tail, not nearby memory.
    layouts = ((0x406474, 0x220, 0x294), (0x4150a8, 0x118, 0x14c),
               (0x417438, 0x280, 0x318), (0x4180e0, 0x220, 0x254),
               (0x418c50, 0x220, 0x280), (0x41a6d8, 0x2a0, None))
    for (caller, offset), (start, io, ffb) in zip(BT_PCM_CALLERS, layouts):
        u = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        u.mem_map(0x400000, 0x10000 * 6)
        for _, (kind, off, va, _, size, _, _, _) in segments(stock):
            if kind == 1: u.mem_write(va, stock[off:off+size])
        u.mem_map(0x1000000, 0x10000)
        stack, buffer = 0x1008000, 0x1001000
        u.reg_write(UC_MIPS_REG_SP, stack)
        if ffb is not None:
            assert ffb-io == offset
            u.mem_write(stack+ffb, struct.pack('<4I', buffer, buffer+128, 1024, 2))
            # The first caller caches data/tail/element-size before this block.
            for register, value in ((UC_MIPS_REG_FP,buffer), (UC_MIPS_REG_A2,buffer+128), (UC_MIPS_REG_T0,2)):
                u.reg_write(register,value)
            want = 960
        else:
            for register, value in ((UC_MIPS_REG_S1,buffer), (UC_MIPS_REG_S7,128), (UC_MIPS_REG_S6,224)):
                u.reg_write(register,value)
            want = 224
        u.emu_start(start, 0x4145d0, count=100)
        assert u.reg_read(UC_MIPS_REG_PC)==0x4145d0, hex(caller)
        assert u.reg_read(UC_MIPS_REG_A0)==stack+io and u.reg_read(UC_MIPS_REG_A2)==buffer+128
        assert u.reg_read(UC_MIPS_REG_A3)==want
    for queued in (0, 4096, 65536):
        assert not check_drop(stock, queued), 'Regression must reproduce against stock'
        assert check_drop(patched, queued), f'DROP lost new-track audio with {queued} old bytes'
    for caller in BT_PCM_CALLERS:
        assert not check_drop(stock, 4096, caller)
        assert check_drop(patched, 4096, caller), f'DROP retained partial PCM for {caller[0]:x}'
    print('Bluetooth DROP: delayed encoder signal preserves new PCM, flushes all old PCM and resets pacing; stock reproduces the fault.')


if __name__ == '__main__':
    check(sys.argv[1])
