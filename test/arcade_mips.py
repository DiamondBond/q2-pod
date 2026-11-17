#!/usr/bin/env python3
"""Run the actual Q2-targeted MIPS arcade rules in Unicorn (no Q2, no stock ZIP).

Only the game rules are emulated. The device's Linux, AWTK and peripherals
are NOT emulated. The graphical frontend uses this same backend.
"""
from __future__ import annotations
import argparse
import ctypes as C
import pathlib
import shutil
import subprocess
import sys
import tempfile
from unicorn.mips_const import (
    UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3,
    UC_MIPS_REG_RA, UC_MIPS_REG_SP, UC_MIPS_REG_V0,
)
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN

ROOT = pathlib.Path(__file__).resolve().parents[1]
STACK = 0x200000
STATE = 0x300000
RETURN = 0x400000
PONG_SIZE = 36


class Pong(C.LittleEndianStructure):
    _fields_ = [(k, C.c_int32) for k in
                "ball_x ball_y vel_x vel_y player_y cpu_y player_score cpu_score rallies".split()]


class Blocks(C.LittleEndianStructure):
    _fields_ = [
        ("board", (C.c_uint8 * 10) * 20),
        ("piece", C.c_uint8), ("next", C.c_uint8), ("rotation", C.c_uint8),
        ("bag", C.c_uint8 * 7), ("bag_pos", C.c_uint8),
        ("x", C.c_int32), ("y", C.c_int32), ("rng", C.c_uint32),
        ("score", C.c_uint32), ("lines", C.c_uint32),
        ("level", C.c_uint32), ("game_over", C.c_int32),
    ]


class Breakout(C.LittleEndianStructure):
    _fields_ = [
        ("bricks", (C.c_uint8 * 8) * 5),
        ("ball_x", C.c_int32), ("ball_y", C.c_int32),
        ("dx", C.c_int32), ("dy", C.c_int32), ("paddle_x", C.c_int32),
        ("score", C.c_uint32), ("level", C.c_uint32),
        ("lives", C.c_uint32), ("remaining", C.c_uint32),
        ("waiting", C.c_int32), ("game_over", C.c_int32),
    ]


def compile_mips(directory: pathlib.Path) -> pathlib.Path:
    obj = directory / "arcade.o"
    breakout_obj = directory / "breakout.o"
    elf = directory / "arcade.elf"
    flags = ["--target=mipsel-linux-gnu", "-march=mips32r2", "-mabi=32",
             "-mfp64", "-mnan=2008", "-mabs=2008", "-mno-abicalls",
             "-fno-pic", "-G0", "-ffreestanding", "-fno-builtin",
             "-fno-stack-protector", "-fno-unwind-tables",
             "-fno-asynchronous-unwind-tables", "-Oz", "-Wall", "-Wextra", "-Werror"]
    subprocess.run(["clang", *flags, "-c", str(ROOT / "patch/arcade_core.c"),
                    "-o", str(obj)], check=True)
    subprocess.run(["clang", *flags, "-c", str(ROOT / "patch/breakout_core.c"),
                    "-o", str(breakout_obj)], check=True)
    subprocess.run(["ld.lld", "-m", "elf32ltsmip", "-static",
                    "-Ttext=0x100000", "-e", "q2_pong_init",
                    str(obj), str(breakout_obj), "-o", str(elf)], check=True)
    return elf


def symbols(elf: pathlib.Path) -> dict[str, int]:
    reader = shutil.which("readelf") or shutil.which("llvm-readelf")
    if reader is None:
        raise RuntimeError("Install binutils readelf or LLVM llvm-readelf")
    output = subprocess.check_output([reader, "-Ws", str(elf)], text=True)
    found = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 8 and parts[0].endswith(":") and parts[3] == "FUNC":
            found[parts[7]] = int(parts[1], 16)
    needed = ["q2_pong_init", "q2_pong_move", "q2_pong_tick",
              "q2_blocks_init", "q2_blocks_move", "q2_blocks_rotate",
              "q2_blocks_tick", "q2_blocks_drop", "q2_blocks_cell",
              "q2_blocks_next_cell", "q2_breakout_init",
              "q2_breakout_move", "q2_breakout_launch", "q2_breakout_tick"]
    for name in needed:
        if name not in found:
            raise RuntimeError(f"MIPS ELF lacks {name}")
    return found


def load_elf(uc: Uc, elf: pathlib.Path) -> None:
    # Reuse the firmware tool's checked ELF segment parsing on newer q2-pod.
    sys.path.insert(0, str(ROOT / "tools"))
    from build import segments
    data = elf.read_bytes()
    loads = [(offset, vaddr, size, memory)
             for _, (kind, offset, vaddr, _, size, memory, _, _) in segments(data)
             if kind == 1 and memory]
    if not loads:
        raise RuntimeError("Compiled MIPS ELF has no loadable segments")
    start = min(vaddr for _, vaddr, _, _ in loads) & ~0xfff
    end = (max(vaddr + memory for _, vaddr, _, memory in loads) + 0xfff) & ~0xfff
    if end <= start or end - start > 16 * 1024 * 1024:
        raise RuntimeError("Unexpected MIPS ELF memory footprint")
    uc.mem_map(start, end - start)
    for offset, vaddr, size, _ in loads:
        uc.mem_write(vaddr, data[offset:offset + size])


class MipsArcade:
    """A real MIPS little-endian instruction runner, with host-side game state."""
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="q2-arcade-mips-")
        elf = compile_mips(pathlib.Path(self.tmp.name))
        self.address = symbols(elf)
        self.uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        load_elf(self.uc, elf)
        self.uc.mem_map(STACK, 0x10000)
        self.uc.mem_map(STATE, 0x10000)
        self.uc.mem_write(STATE, bytes(0x10000))
        self.uc.reg_write(UC_MIPS_REG_SP, STACK + 0xfff0)
        self.pong_init()
        self.blocks_init(42)
        self.breakout_init()

    def call(self, name: str, *args: int) -> int:
        self.uc.reg_write(UC_MIPS_REG_SP, STACK + 0xfff0)
        self.uc.reg_write(UC_MIPS_REG_RA, RETURN)
        for reg, value in zip((UC_MIPS_REG_A0, UC_MIPS_REG_A1,
                               UC_MIPS_REG_A2, UC_MIPS_REG_A3), args):
            self.uc.reg_write(reg, value & 0xffffffff)
        self.uc.emu_start(self.address[name], RETURN, count=500000)
        value = self.uc.reg_read(UC_MIPS_REG_V0)
        return value - 0x100000000 if value & 0x80000000 else value

    def pong_init(self) -> None:
        self.call("q2_pong_init", STATE)

    def pong_move(self, steps: int) -> None:
        self.call("q2_pong_move", STATE, steps)

    def pong_tick(self) -> None:
        self.call("q2_pong_tick", STATE)

    def pong(self) -> Pong:
        return Pong.from_buffer_copy(bytes(self.uc.mem_read(STATE, C.sizeof(Pong))))

    def blocks_init(self, seed: int = 42) -> None:
        self.call("q2_blocks_init", STATE + 0x1000, seed)

    def blocks_move(self, delta: int) -> int:
        return self.call("q2_blocks_move", STATE + 0x1000, delta)

    def blocks_rotate(self) -> int:
        return self.call("q2_blocks_rotate", STATE + 0x1000)

    def blocks_tick(self) -> int:
        return self.call("q2_blocks_tick", STATE + 0x1000)

    def blocks_drop(self) -> int:
        return self.call("q2_blocks_drop", STATE + 0x1000)

    def blocks(self) -> Blocks:
        return Blocks.from_buffer_copy(bytes(self.uc.mem_read(STATE + 0x1000, C.sizeof(Blocks))))

    def blocks_cell(self, x: int, y: int) -> int:
        return self.call("q2_blocks_cell", STATE + 0x1000, x, y)

    def blocks_preview_cell(self, x: int, y: int) -> int:
        return self.call("q2_blocks_next_cell", STATE + 0x1000, x, y)

    def breakout_init(self) -> None:
        self.call("q2_breakout_init", STATE + 0x2000)

    def breakout_move(self, distance: int) -> None:
        self.call("q2_breakout_move", STATE + 0x2000, distance)

    def breakout_launch(self) -> None:
        self.call("q2_breakout_launch", STATE + 0x2000)

    def breakout_tick(self) -> None:
        self.call("q2_breakout_tick", STATE + 0x2000)

    def breakout(self) -> Breakout:
        return Breakout.from_buffer_copy(
            bytes(self.uc.mem_read(STATE + 0x2000, C.sizeof(Breakout))))

    def close(self) -> None:
        self.tmp.cleanup()


def self_test() -> None:
    a = MipsArcade()
    try:
        p = a.pong()
        assert (p.ball_x, p.ball_y, p.player_y) == (160, 120, 96)
        a.pong_move(-1000)
        assert a.pong().player_y == 0
        for _ in range(50):
            a.pong_tick()
        assert 0 <= a.pong().ball_y <= 239
        g = a.blocks()
        assert g.level == 1 and g.piece < 7 and not g.game_over
        assert sum(a.blocks_cell(x, y) != 0 for y in range(20) for x in range(10)) == 4
        assert sum(a.blocks_preview_cell(x, y) != 0 for y in range(4) for x in range(4)) == 4
        assert a.blocks_rotate() in (0, 1)
        assert a.blocks_drop() >= 0
        assert a.blocks().score < 1000
        b = a.breakout()
        assert b.remaining == 40 and b.lives == 3 and b.waiting
        a.breakout_move(-1000)
        assert a.breakout().paddle_x == 0
        a.breakout_launch()
        assert not a.breakout().waiting
        for _ in range(100):
            a.breakout_tick()
        assert a.breakout().score >= 0
        print("MIPS Unicorn arcade: Pong + Blocks + Breakout smoke tests passed")
    finally:
        a.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run MIPS smoke tests")
    args = parser.parse_args()
    self_test()
