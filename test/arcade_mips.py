#!/usr/bin/env python3
"""Run the actual Q2-targeted MIPS arcade rules in Unicorn (no Q2, no stock ZIP).

Only the game rules are emulated. The device's Linux, AWTK and peripherals
are NOT emulated. The graphical frontend uses this same backend.
"""
from __future__ import annotations
import argparse
import os
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

def tool_executable(name: str) -> str:
    """Find an LLVM tool on PATH or in a standard Windows installation."""
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "win32":
        roots = [
            pathlib.Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "LLVM" / "bin",
            pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "LLVM" / "bin",
        ]
        for root in roots:
            candidate = root / (name + ".exe")
            if candidate.is_file():
                return str(candidate)
    if sys.platform == "win32":
        raise RuntimeError("Missing LLVM tool " + name + ". Install LLVM with winget install LLVM.LLVM, then restart the simulator.")
    raise RuntimeError("Missing LLVM tool " + name + ". Install clang and lld using your package manager.")


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


def compile_mips(directory: pathlib.Path) -> pathlib.Path:
    obj = directory / "arcade.o"
    elf = directory / "arcade.elf"
    flags = ["--target=mipsel-linux-gnu", "-march=mips32r2", "-mabi=32",
             "-mfp64", "-mnan=2008", "-mabs=2008", "-mno-abicalls",
             "-fno-pic", "-G0", "-ffreestanding", "-fno-builtin",
             "-fno-stack-protector", "-fno-unwind-tables",
             "-fno-asynchronous-unwind-tables", "-Oz", "-Wall", "-Wextra", "-Werror"]
    subprocess.run([tool_executable("clang"), *flags, "-c", str(ROOT / "patch/arcade_core.c"),
                    "-o", str(obj)], check=True)
    subprocess.run([tool_executable("ld.lld"), "-m", "elf32ltsmip", "-static",
                    "-Ttext=0x100000", "-e", "q2_pong_init",
                    str(obj), "-o", str(elf)], check=True)
    return elf


def symbols(elf: pathlib.Path) -> dict[str, int]:
    reader = shutil.which("readelf") or shutil.which("llvm-readelf")
    if reader is None:
        reader = tool_executable("llvm-readelf")
    output = subprocess.check_output([reader, "-Ws", str(elf)], text=True)
    found = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 8 and parts[0].endswith(":") and parts[3] == "FUNC":
            found[parts[7]] = int(parts[1], 16)
    needed = ["q2_pong_init", "q2_pong_move", "q2_pong_tick",
              "q2_blocks_init", "q2_blocks_move", "q2_blocks_rotate",
              "q2_blocks_tick", "q2_blocks_drop", "q2_blocks_cell",
              "q2_blocks_next_cell"]
    for name in needed:
        if name not in found:
            raise RuntimeError(f"MIPS ELF lacks {name}")
    return found


def load_elf(uc: Uc, elf: pathlib.Path) -> None:
    # Reuse Q2 Pod's audited ELF LOAD mapping helper, not a homegrown decoder.
    sys.path.insert(0, str(ROOT / "tools"))
    from build import load_elf as load_segments
    load_segments(uc, elf.read_bytes())


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
        print("MIPS Unicorn arcade: Pong + Blocks smoke tests passed")
    finally:
        a.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run MIPS smoke tests")
    args = parser.parse_args()
    self_test()
