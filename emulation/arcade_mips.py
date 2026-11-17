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

EMULATION = pathlib.Path(__file__).resolve().parent
STACK = 0x200000
STATE = 0x300000
BREAKOUT_STATE = STATE + 0x6000
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


class Breakout(C.LittleEndianStructure):
    _fields_ = [
        ("bricks", (C.c_uint8 * 8) * 5),
        ("ball_x", C.c_int32), ("ball_y", C.c_int32),
        ("dx", C.c_int32), ("dy", C.c_int32), ("paddle_x", C.c_int32),
        ("score", C.c_uint32), ("level", C.c_uint32),
        ("lives", C.c_uint32), ("remaining", C.c_uint32),
        ("waiting", C.c_int32), ("game_over", C.c_int32),
    ]


class Snake(C.LittleEndianStructure):
    _fields_ = [
        ("body", C.c_uint16 * 400), ("tail", C.c_uint16), ("len", C.c_uint16),
        ("food", C.c_uint16), ("dir", C.c_uint8), ("turned", C.c_uint8),
        ("state", C.c_uint8), ("next", C.c_int8), ("score", C.c_int32),
    ]


class Vortex(C.LittleEndianStructure):
    _fields_ = [(name, C.c_int32) for name in "state lives level score pa x y vx vy".split()] + [
        ("brick", C.c_uint16 * 3), ("pad", C.c_uint16),
    ]


class Sudoku(C.LittleEndianStructure):
    _fields_ = [("magic", C.c_uint32), ("cell", C.c_uint8 * 81),
                ("cur", C.c_uint8), ("pad", C.c_uint8 * 2), ("sum", C.c_uint32)]


class Solitaire(C.LittleEndianStructure):
    _fields_ = [("magic", C.c_uint32), ("card", (C.c_uint8 * 24) * 13),
                ("len", C.c_uint8 * 13), ("cur", C.c_uint8),
                ("pad", C.c_uint8 * 2), ("sum", C.c_uint32)]


def use_wsl_compiler() -> bool:
    """Windows LLVM distributions often lack the MIPS backend."""
    return sys.platform == "win32" and os.environ.get("Q2_MIPS_COMPILER", "wsl").lower() != "windows"


def wsl_path(path: pathlib.Path) -> str:
    """Convert a Windows path to a mounted Linux path without shell interpolation."""
    try:
        return subprocess.check_output(
            ["wsl.exe", "--exec", "wslpath", "-a", str(path.resolve())],
            text=True, stderr=subprocess.PIPE).strip()
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "Windows MIPS compilation requires Ubuntu WSL with clang/lld. "
            "Check: wsl --exec clang --version; wsl --exec ld.lld --version"
        ) from exc


def compiler_commands(obj: pathlib.Path, elf: pathlib.Path, flags: list[str]) -> tuple[list[str], list[str]]:
    """Use native Linux clang, or the installed WSL clang from Windows."""
    source = EMULATION / "arcade_payload.c"
    if use_wsl_compiler():
        source_arg, obj_arg, elf_arg = (wsl_path(p) for p in (source, obj, elf))
        compile_command = ["wsl.exe", "--exec", "clang", *flags, "-c",
                           source_arg, "-o", obj_arg]
        link_command = ["wsl.exe", "--exec", "ld.lld", "-m", "elf32ltsmip",
                        "-static", "-Ttext=0x100000", "-e", "q2_pong_init",
                        obj_arg, "-o", elf_arg]
    else:
        compile_command = [tool_executable("clang"), *flags, "-c", str(source), "-o", str(obj)]
        link_command = [tool_executable("ld.lld"), "-m", "elf32ltsmip",
                        "-static", "-Ttext=0x100000", "-e", "q2_pong_init",
                        str(obj), "-o", str(elf)]
    return compile_command, link_command

def compile_mips(directory: pathlib.Path) -> pathlib.Path:
    obj = directory / "arcade.o"
    elf = directory / "arcade.elf"
    flags = ["--target=mipsel-linux-gnu", "-march=mips32r2", "-mabi=32",
             "-mfp64", "-mnan=2008", "-mabs=2008", "-mno-abicalls",
             "-fno-pic", "-G0", "-ffreestanding", "-fno-builtin",
             "-fno-stack-protector", "-fno-unwind-tables",
             "-fno-asynchronous-unwind-tables", "-Oz", "-Wall", "-Wextra", "-Werror"]
    compile_command, link_command = compiler_commands(obj, elf, flags)
    try:
        subprocess.run(compile_command, check=True)
        subprocess.run(link_command, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        if use_wsl_compiler():
            raise RuntimeError(
                "MIPS compilation in WSL failed. Install clang and lld in Ubuntu: "
                "sudo apt install clang lld. Then run "
                "'wsl --exec clang --version' in Windows PowerShell."
            ) from exc
        raise RuntimeError(
            "Local LLVM could not compile MIPS32r2. On Windows, remove "
            "Q2_MIPS_COMPILER=windows to use the Ubuntu WSL toolchain."
        ) from exc
    return elf


def symbols(elf: pathlib.Path) -> dict[str, int]:
    """Read actual MIPS ELF symbol table on Windows, Linux or macOS."""
    from elftools.elf.elffile import ELFFile
    from elftools.elf.sections import SymbolTableSection

    found = {}
    with elf.open("rb") as stream:
        binary = ELFFile(stream)
        if binary["e_machine"] != "EM_MIPS":
            raise RuntimeError("Arcade build did not produce a MIPS ELF")
        for section in binary.iter_sections():
            if not isinstance(section, SymbolTableSection):
                continue
            for symbol in section.iter_symbols():
                if symbol["st_info"]["type"] == "STT_FUNC":
                    found[symbol.name] = symbol["st_value"]
    needed = ["q2_pong_init", "q2_pong_move", "q2_pong_tick",
              "q2_blocks_init", "q2_blocks_move", "q2_blocks_rotate",
              "q2_blocks_tick", "q2_blocks_drop", "q2_blocks_cell",
              "q2_blocks_next_cell", "q2_breakout_init", "q2_breakout_move",
              "q2_breakout_launch", "q2_breakout_tick", "q2_snake_seed", "snake_new", "snake_turn",
              "snake_ms", "snake_step", "vortex_new", "vortex_launch", "vortex_step",
              "sud_new", "sud_set", "sud_conflict", "sud_done", "sol_new", "sol_draw",
              "sol_home", "sol_move", "sol_finish", "sol_won"]
    for name in needed:
        if name not in found:
            raise RuntimeError(f"MIPS ELF lacks {name}")
    return found


def load_elf(uc: Uc, elf: pathlib.Path) -> None:
    # Reuse Q2 Pod's audited ELF LOAD mapping helper, not a homegrown decoder.
    from mips_elf import load_elf as load_segments
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

    def breakout_init(self) -> None:
        self.call("q2_breakout_init", BREAKOUT_STATE)

    def breakout_move(self, distance: int) -> None:
        self.call("q2_breakout_move", BREAKOUT_STATE, distance)

    def breakout_launch(self) -> None:
        self.call("q2_breakout_launch", BREAKOUT_STATE)

    def breakout_tick(self) -> None:
        self.call("q2_breakout_tick", BREAKOUT_STATE)

    def breakout(self) -> Breakout:
        return Breakout.from_buffer_copy(
            bytes(self.uc.mem_read(BREAKOUT_STATE, C.sizeof(Breakout))))

    def snake_init(self, seed: int) -> None:
        self.call("q2_snake_seed", seed)
        self.call("snake_new", STATE + 0x2000)

    def snake(self) -> Snake:
        return Snake.from_buffer_copy(bytes(self.uc.mem_read(STATE + 0x2000, C.sizeof(Snake))))

    def snake_turn(self, direction: int) -> None:
        self.call("snake_turn", STATE + 0x2000, direction)

    def snake_ms(self) -> int:
        return self.call("snake_ms", STATE + 0x2000)

    def snake_tick(self) -> None:
        self.call("snake_step", STATE + 0x2000)

    def vortex_init(self) -> None:
        self.call("vortex_new", STATE + 0x3000)

    def vortex(self) -> Vortex:
        return Vortex.from_buffer_copy(bytes(self.uc.mem_read(STATE + 0x3000, C.sizeof(Vortex))))

    def vortex_launch(self) -> None:
        self.call("vortex_launch", STATE + 0x3000)

    def vortex_tick(self, turn: int = 0) -> None:
        self.call("vortex_step", STATE + 0x3000, turn)

    def puzzle_init(self, game: str, seed: int) -> None:
        self.call("q2_snake_seed", seed)
        if game == "sudoku":
            self.call("sud_new", STATE + 0x4000)
        else:
            self.call("sol_new", STATE + 0x5000)

    def sudoku(self) -> Sudoku:
        return Sudoku.from_buffer_copy(bytes(self.uc.mem_read(STATE + 0x4000, C.sizeof(Sudoku))))

    def solitaire(self) -> Solitaire:
        return Solitaire.from_buffer_copy(bytes(self.uc.mem_read(STATE + 0x5000, C.sizeof(Solitaire))))

    def sudoku_action(self, name: str, *args: int) -> int:
        return self.call(name, STATE + 0x4000, *args)

    def solitaire_action(self, name: str, *args: int) -> int:
        return self.call(name, STATE + 0x5000, *args)

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
