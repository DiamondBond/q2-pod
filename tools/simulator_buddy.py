"""Run an installed Q2 card game against a small, isolated Linux device model."""
import io
import os
import struct
import time
from collections import deque
from pathlib import Path
from tempfile import NamedTemporaryFile

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile
from PIL import Image
from unicorn import Uc, UcError, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_INTR
from unicorn.mips_const import (
    UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3,
    UC_MIPS_REG_CP0_STATUS, UC_MIPS_REG_PC, UC_MIPS_REG_SP, UC_MIPS_REG_V0,
)

import build
from simulator_apps import card_path

INPUT = b"/tmp/q2-fidget.input.sock"
APP = b"/mnt/mmc/.fidget/"
FB, STACK = 0x20000000, 0x70000000
PANEL_W, PANEL_H = 320, 375
PAGE_BYTES = PANEL_W * PANEL_H * 4
SCREEN = (375, 320)
FILES = {"state": 2, "pet": 65536, "pet.new": 65536, "buddy.png": 3 << 20}


class Buddy:
    """The guest sees an emulated framebuffer, input queue and four card files."""

    def __init__(self, card, clock=time.monotonic, wall=time.time):
        self.card, self.clock, self.wall = card, clock, wall
        binary = card_path(card, ".fidget/q2-fidget")
        with binary.open("rb") as source:
            raw = source.read((2 << 20) + 1)
        self.uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        self.pc = self.load(raw)
        status = self.uc.reg_read(UC_MIPS_REG_CP0_STATUS)
        self.uc.reg_write(UC_MIPS_REG_CP0_STATUS, status | (1 << 29) | (1 << 26))
        self.uc.mem_map(FB, (2 * PAGE_BYTES + 4095) & ~4095)
        self.uc.mem_map(STACK, 0x100000)
        sp = STACK + 0xff000
        argv = APP + b"q2-fidget\0"
        self.uc.mem_write(sp, struct.pack("<4I", 1, sp + 16, 0, 0) + argv)
        self.uc.reg_write(UC_MIPS_REG_SP, sp)
        self.uc.hook_add(UC_HOOK_INTR, self.interrupt)
        self.messages: deque[bytes] = deque(maxlen=128)
        self.handles: dict[int, tuple[str, bool, io.BytesIO]] = {}
        self.fd = 5
        self.exit_code: int | None = None
        self.frames = self.front = 0
        self.watchdog = self.clock()
        self.stopped = False
        self.last_syscall = None
        self.image = Image.new("RGB", SCREEN)

    def load(self, raw):
        if len(raw) > 2 << 20:
            raise ValueError("Buddy executable is too large")
        try:
            elf = ELFFile(io.BytesIO(raw))
            if (elf.elfclass, elf.little_endian, elf["e_machine"], elf["e_type"]) != (32, True, "EM_MIPS", "ET_EXEC"):
                raise ValueError("Buddy needs a static little-endian MIPS32 executable")
            entry = int(elf["e_entry"])
            segments = list(elf.iter_segments())
            if any(seg["p_type"] in ("PT_INTERP", "PT_DYNAMIC") for seg in segments):
                raise ValueError("Buddy needs a static executable")
            loads = [seg for seg in segments if seg["p_type"] == "PT_LOAD"]
            if not loads or sum(seg["p_memsz"] for seg in loads) > 32 << 20:
                raise ValueError("Invalid Buddy executable segment sizes")
            if any(not (4096 <= seg["p_vaddr"] < seg["p_vaddr"] + seg["p_memsz"] <= FB)
                   or not (0 <= seg["p_filesz"] <= seg["p_memsz"])
                   or seg["p_offset"] + seg["p_filesz"] > len(raw) for seg in loads):
                raise ValueError("Invalid Buddy executable segment")
            if not any(seg["p_flags"] & 1 and seg["p_vaddr"] <= entry < seg["p_vaddr"] + seg["p_filesz"]
                       for seg in loads):
                raise ValueError("Invalid Buddy entry point")
            build.load_elf(self.uc, raw)
            return entry
        except (ELFError, struct.error, UcError) as exc:
            raise ValueError(f"Could not load Buddy executable: {exc}") from exc

    def send(self, message):
        self.messages.append(message.encode("ascii"))

    def close(self):
        self.stopped = True
        self.handles.clear()

    def frame(self):
        if self.stopped:
            return
        previous = self.frames
        try:
            self.uc.emu_start(self.pc, 0, timeout=100000, count=12_000_000)
        except UcError as exc:
            raise ValueError(f"Buddy guest CPU stopped at 0x{self.uc.reg_read(UC_MIPS_REG_PC):x}: {exc}") from exc
        self.pc = self.uc.reg_read(UC_MIPS_REG_PC)
        if self.frames != previous:
            raw = self.uc.mem_read(FB + self.front * PANEL_W * 4, PAGE_BYTES)
            portrait = Image.frombytes("RGB", (PANEL_W, PANEL_H), bytes(raw), "raw", "BGRX")
            self.image = portrait.transpose(Image.Transpose.ROTATE_90)
            self.watchdog = self.clock()
        if not self.stopped and self.clock() - self.watchdog > 6:
            raise ValueError(f"Buddy stopped presenting frames at 0x{self.pc:x} (last syscall {self.last_syscall})")

    def interrupt(self, uc, number, _data):
        if number != 17:
            raise ValueError(f"Unsupported Buddy guest interrupt {number}")
        call = uc.reg_read(UC_MIPS_REG_V0)
        self.last_syscall = call
        a, b, c = (uc.reg_read(reg) for reg in (UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2))
        result = self.syscall(call, a, b, c)
        uc.reg_write(UC_MIPS_REG_V0, abs(result))
        uc.reg_write(UC_MIPS_REG_A3, int(result < 0))

    def guest_string(self, address):
        value = bytearray()
        for i in range(200):
            byte = self.uc.mem_read(address + i, 1)[0]
            if byte == 0:
                return bytes(value)
            value.append(byte)
        raise ValueError("Buddy guest string is too long")

    def card_file(self, name):
        return card_path(self.card, ".fidget/" + name)

    def open_file(self, path, flags):
        if path == b"/dev/fb0":
            return 3
        if not path.startswith(APP):
            return -2
        name = path[len(APP):].decode("ascii", errors="replace")
        if name not in FILES:
            return -2
        writing = bool(flags & 1)
        if flags & 2 or writing and (name == "buddy.png" or flags & 0x300 != 0x300):
            return -13
        try:
            contents = io.BytesIO()
            if not writing:
                with self.card_file(name).open("rb") as source:
                    contents = io.BytesIO(source.read(FILES[name]))
            if len(self.handles) >= 16:
                return -24
            fd = self.fd
            self.fd += 1
            self.handles[fd] = name, writing, contents
            return fd
        except FileNotFoundError:
            return -2
        except (OSError, ValueError):
            return -13

    def close_file(self, fd):
        if fd in (3, 4):
            return 0
        if fd not in self.handles:
            return -9
        name, writing, contents = self.handles.pop(fd)
        if not writing:
            return 0
        temporary: Path | None = None
        try:
            target = self.card_file(name)
            with NamedTemporaryFile(dir=target.parent, prefix=".buddy-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(contents.getvalue())
            os.replace(temporary, self.card_file(name))
            return 0
        except (OSError, ValueError):
            return -13
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def framebuffer(self, request, address):
        if request == 0x4600:
            var = [0] * 40
            var[0], var[1], var[2], var[3] = PANEL_W, PANEL_H, PANEL_W, 2 * PANEL_H
            var[5], var[6], var[8] = self.front, 32, 16
            self.uc.mem_write(address, struct.pack("<40I", *var))
        elif request == 0x4602:
            fix = [0] * 17
            fix[5], fix[11] = 2 * PAGE_BYTES, PANEL_W * 4
            self.uc.mem_write(address, struct.pack("<17I", *fix))
        elif request == 0x4606:
            front = struct.unpack("<I", self.uc.mem_read(address + 20, 4))[0]
            if front not in (0, PANEL_H):
                return -22
            self.front = front
            self.frames += 1
            self.uc.emu_stop()
        else:
            return -22
        return 0

    def syscall(self, number, a, b, c):
        if number == 4005:
            return self.open_file(self.guest_string(a), b)
        if number == 4006:
            return self.close_file(a)
        if number in (4003, 4004):
            if a not in self.handles:
                return -9
            name, writing, stream = self.handles[a]
            if number == 4003 and not writing:
                data = stream.read(min(c, FILES[name]))
                if data:
                    self.uc.mem_write(b, data)
                return len(data)
            if number == 4004 and writing and c <= FILES[name] - stream.tell():
                return stream.write(bytes(self.uc.mem_read(b, c))) if c else 0
            return -13
        if number == 4054 and a == 3:
            return self.framebuffer(b, c)
        if number == 4090:  # Buddy's direct o32 mmap for two framebuffer pages
            return FB if a == 0 and b == 2 * PAGE_BYTES and c == 3 else -22
        if number == 4183:
            return 4 if (a, b, c) == (1, 1, 0) else -22
        if number == 4169:
            return 0 if a == 4 and self.guest_string(b + 2) == INPUT else -22
        if number == 4010:
            return 0 if self.guest_string(a) == INPUT else -13
        if number == 4175:
            if a != 4:
                return -9
            if not self.messages:
                return -11
            data = self.messages.popleft()[:c]
            self.uc.mem_write(b, data)
            return len(data)
        if number == 4188:
            if b == 1:
                self.uc.mem_write(a + 6, struct.pack("<H", bool(self.messages)))
            if c and not self.messages:
                self.uc.emu_stop()
            return int(b == 1 and bool(self.messages))
        if number == 4263:
            now = self.clock() if a == 1 else self.wall()
            seconds = int(now)
            self.uc.mem_write(b, struct.pack("<II", seconds & 0xffffffff, int((now - seconds) * 1e9)))
            return 0
        if number == 4038:
            if (self.guest_string(a), self.guest_string(b)) != (APP + b"pet.new", APP + b"pet"):
                return -13
            try:
                os.replace(self.card_file("pet.new"), self.card_file("pet"))
                return 0
            except (OSError, ValueError):
                return -13
        if number == 4218:  # Scratch-page reclamation is unnecessary in this device model.
            return 0
        if number == 4246 or number == 4001:
            self.stopped = True
            self.exit_code = a
            self.uc.emu_stop()
            return 0
        raise ValueError(f"Buddy uses an unsupported MIPS syscall ({number})")
