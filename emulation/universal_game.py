#!/usr/bin/env python3
"""Generic MIPS game runner for the experimental Q2G ABI v1.

Run ABI-compliant MIPS ELF games, not arbitrary Q2 firmware or stock executables.
The host has no game-name-specific structures, callbacks or rendering code.
"""
from __future__ import annotations
import argparse
import pathlib
import struct
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN
from unicorn.mips_const import (UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_RA,
                                UC_MIPS_REG_SP, UC_MIPS_REG_V0)
from mips_elf import load_elf

STACK = 0x500000
RETURN = 0x600000
MAX_COMMANDS = 128
DRAW_SIZE = 88
SCREEN_SIZE = (375, 320)
EXPORTS = ("q2g_version", "q2g_name", "q2g_init", "q2g_input", "q2g_step", "q2g_render")


def exports_from_elf(path):
    from elftools.elf.elffile import ELFFile
    from elftools.elf.sections import SymbolTableSection
    with pathlib.Path(path).open("rb") as stream:
        elf = ELFFile(stream)
        if elf["e_machine"] != "EM_MIPS" or not elf.little_endian or elf.elfclass != 32:
            raise ValueError("Game must be a 32-bit little-endian MIPS ELF")
        names = {}
        for section in elf.iter_sections():
            if isinstance(section, SymbolTableSection):
                for symbol in section.iter_symbols():
                    if symbol.name in EXPORTS and symbol["st_info"]["type"] == "STT_FUNC":
                        names[symbol.name] = symbol["st_value"]
        missing = set(EXPORTS) - names.keys()
        if missing:
            raise ValueError("Game ABI exports missing: " + ", ".join(sorted(missing)))
        return names


class UniversalGame:
    """Execute a guest ABI with no Python game-specific code."""
    def __init__(self, path):
        self.symbols = exports_from_elf(path)
        self.uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        load_elf(self.uc, pathlib.Path(path).read_bytes())
        self.uc.mem_map(STACK, 0x10000)
        self.uc.reg_write(UC_MIPS_REG_SP, STACK + 0xffe0)
        if self.call("q2g_version") != 1:
            raise ValueError("Unsupported Q2G game ABI version")
        name_ptr = self.call("q2g_name")
        name_data = bytes(self.uc.mem_read(name_ptr, 128)).split(b"\0", 1)[0]
        self.name = name_data.decode("utf-8", errors="replace") or "Unnamed game"
        self.call("q2g_init", 42)

    def call(self, export, *args):
        self.uc.reg_write(UC_MIPS_REG_SP, STACK + 0xffe0)
        self.uc.reg_write(UC_MIPS_REG_RA, RETURN)
        for register, value in zip((UC_MIPS_REG_A0, UC_MIPS_REG_A1), args):
            self.uc.reg_write(register, int(value) & 0xffffffff)
        self.uc.emu_start(self.symbols[export], RETURN, count=500000)
        return int(self.uc.reg_read(UC_MIPS_REG_V0))

    def input(self, action, value=0):
        self.call("q2g_input", action, value)

    def advance(self, ms=16):
        self.call("q2g_step", min(100, max(0, int(ms))))

    def commands(self):
        base = self.call("q2g_render")
        count = struct.unpack("<I", self.uc.mem_read(base, 4))[0]
        if count > MAX_COMMANDS:
            raise ValueError("Guest draw command count exceeds ABI limit")
        data = bytes(self.uc.mem_read(base + 4, count * DRAW_SIZE))
        result = []
        for item in struct.iter_unpack("<IiiiiI64s", data):
            kind, x, y, w, h, rgb, raw_text = item
            if kind not in (1, 2, 3, 4):
                raise ValueError("Unknown guest draw command")
            result.append((kind, x, y, w, h, rgb, raw_text.split(b"\0", 1)[0].decode("utf-8", "replace")))
        return result

    def image(self):
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new("RGB", SCREEN_SIZE, "#10141c")
        draw = ImageDraw.Draw(image)
        for kind, x, y, w, h, rgb, text in self.commands():
            color = f"#{rgb & 0xffffff:06x}"
            if kind == 1:
                draw.rectangle((0, 0, SCREEN_SIZE[0], SCREEN_SIZE[1]), fill=color)
            elif kind == 2 and w > 0 and h > 0:
                draw.rectangle((x, y, x + w - 1, y + h - 1), fill=color)
            elif kind == 3:
                draw.text((x, y), text, fill=color)
            elif kind == 4 and w > 0:
                draw.ellipse((x-w, y-w, x+w, y+w), fill=color)
        return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", required=True, type=pathlib.Path, help="ABI-compliant game MIPS ELF")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--snapshot", type=pathlib.Path)
    args = parser.parse_args()
    game = UniversalGame(args.elf)
    original = game.commands()
    assert original and original[0][0] == 1
    game.input(1, 12)
    game.advance()
    assert game.commands()
    if args.self_test:
        print(f"Universal Q2 game ABI v1 passed: {game.name}")
        return
    if args.snapshot:
        game.image().save(args.snapshot)
        print(args.snapshot)
        return
    import tkinter as tk
    from PIL import ImageTk
    root = tk.Tk()
    root.title("Q2 universal game guest — " + game.name)
    root.resizable(False, False)
    screen = tk.Label(root)
    screen.pack()
    holder = [None]
    def send(event):
        key = event.keysym
        action = {"Return": 2, "space": 5, "Escape": 6,
                  "Left": 3, "Right": 4}.get(key)
        if action is not None:
            game.input(action)
    def wheel(event):
        game.input(1, -12 if event.delta > 0 else 12)
    root.bind("<Key>", send)
    root.bind("<MouseWheel>", wheel)
    root.bind("<Button-4>", lambda _: game.input(1, -12))
    root.bind("<Button-5>", lambda _: game.input(1, 12))
    def refresh():
        game.advance(16)
        holder[0] = ImageTk.PhotoImage(game.image())
        screen.configure(image=holder[0])
        root.after(16, refresh)
    refresh()
    root.mainloop()


if __name__ == "__main__":
    main()
