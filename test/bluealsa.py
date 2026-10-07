#!/usr/bin/env python3
"""Run the actual MIPS DROP paths with the encoder signal deliberately delayed.

Usage: python test/bluealsa.py BUILD_DIRECTORY (requires the existing Unicorn).
"""
import pathlib, struct, subprocess, sys
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import *
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
from build import BLUEALSA, BT_DROP, BT_DROP_HANDLER, segments


def check_drop(raw, queued):
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
    u.emu_start(BT_DROP_HANDLER, 0x41463c, count=1000)
    # Stock repolls at 0x414640; stop before the imported cancellation function.
    return empty_at_ack and fifo[0] == 4096 and len(flushes) == flush_count and read(state + 0x1c) == 0 and read(state + 0x30) == 0xffffffff


def check(directory):
    directory = pathlib.Path(directory)
    def extract(name):
        return subprocess.check_output(['unsquashfs', '-cat', str(directory / name), BLUEALSA])
    stock, patched = extract('stock.squashfs'), extract('rootfs.squashfs')
    for queued in (0, 4096, 65536):
        assert not check_drop(stock, queued), 'Regression must reproduce against stock'
        assert check_drop(patched, queued), f'DROP lost new-track audio with {queued} old bytes'
    print('Bluetooth DROP: delayed encoder signal preserves new PCM, flushes all old PCM and resets pacing; stock reproduces the fault.')


if __name__ == '__main__':
    check(sys.argv[1])
