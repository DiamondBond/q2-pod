#!/usr/bin/env python3
"""Host transport and pure q2remote protocol checks."""
import os
import contextlib
import io
import pathlib
import socket
import struct
import subprocess
import tempfile
import time
import zlib

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import q2remote as q

assert q.event(1, 30, 1) == struct.pack("<IIHHi", 0, 0, 1, 30, 1)
press, release = q.key_events(108)
assert q.decode_events(press)[0][2:] == (q.EV_KEY, 108, 1)
assert q.decode_events(release)[0][2:] == (q.EV_KEY, 108, 0)
assert q.decode_events(press)[-1][2:4] == (q.EV_SYN, 0) and q.decode_events(release)[-1][2:4] == (q.EV_SYN, 0)
assert q.touch_xy(0, 0) == (319, 0) and q.touch_xy(374, 319) == (0, 374)
# One tick is 28 units: overshoot half a tick, steps of at most 11, then the settle frames.
one = q.wheel_positions(1)
assert one[-1] == 58 and one[-1 - q.WHEEL_SETTLE:] == [58] * (q.WHEEL_SETTLE + 1)
assert all(0 < a - b <= q.WHEEL_STEP for a, b in zip([100] + one, one[:-q.WHEEL_SETTLE]))
assert q.wheel_positions(-1)[-1] == 142 and q.wheel_positions(1, start=5)[0] == 195  # x wraps 1-200
assert q.wheel_positions(-3, 7)[-1] == 100 + round(3.5 * 7)
assert [q.wheel_units(c) for c in ("WHEELSENSITIVITY=200\n", "x\nWHEELSENSITIVITY=100\n", "WHEELSENSITIVITY=55\n",
                                   "WHEELSENSITIVITY=050\n", "WHEELSENSITIVITY=210\n", "")] == [7, 14, 28, 28, 28, 28]
saved_host, saved_key = os.environ.pop("Q2_HOST", None), os.environ.pop("Q2_KEY", None)
try: q.shell("true")
except ValueError as e: assert "Q2_HOST and Q2_KEY" in str(e)
else: raise AssertionError("missing configuration accepted")
os.environ.update({k: v for k, v in (("Q2_HOST", saved_host), ("Q2_KEY", saved_key)) if v is not None})
gpio = q.parse_devices('''I: Bus=0019 Vendor=0001 Product=0001 Version=0100
N: Name="md-gpio-keys"
H: Handlers=kbd event1
B: EV=3
B: KEY=28 0 101080 0 0 0
''')[0]
assert gpio["event"] == 1 and q.bits(gpio["KEY"]) == {103, 108, 116, 163, 165}
assert q.bits(1 << 116) == {116}

# A padded framebuffer page with four distinct corners validates metadata, orientation and BGRA conversion.
w, h, stride = 320, 375, 320 * 4 + 8
page = bytearray(stride * h)
for x, y, bgra in ((0, 0, bytes((0, 0, 255, 255))), (319, 0, bytes((0, 255, 0, 255))),
                   (0, 374, bytes((255, 0, 0, 255))), (319, 374, bytes((255, 255, 255, 255)))):
    page[y * stride + x * 4:y * stride + x * 4 + 4] = bgra
frame = b"Q2FB\0" + struct.pack("<IIII", w, h, stride, len(page)) + page
png = q.framebuffer_png(frame)
assert png[:8] == b"\x89PNG\r\n\x1a\n"
assert struct.unpack_from(">II", png, 16) == (375, 320)
at, compressed = 8, bytearray()
while at < len(png):
    n = struct.unpack_from(">I", png, at)[0]; tag = png[at + 4:at + 8]; body = png[at + 8:at + 8 + n]
    if tag == b"IDAT": compressed.extend(body)
    at += n + 12
decoded = zlib.decompress(compressed)
def pixel(x, y): return decoded[y * (1 + 375 * 4) + 1 + x * 4:y * (1 + 375 * 4) + 1 + x * 4 + 4]
assert pixel(0, 0) == bytes((0, 255, 0, 255))
assert pixel(374, 0) == bytes((255, 255, 255, 255))
assert pixel(0, 319) == bytes((255, 0, 0, 255))
assert pixel(374, 319) == bytes((0, 0, 255, 255))
for bad in (frame[:20], frame[:-1], frame[:5] + struct.pack("<IIII", w + 1, h, stride, len(page)) + page):
    try: q.framebuffer_png(bad)
    except ValueError: pass
    else: raise AssertionError("bad framebuffer accepted")

with tempfile.TemporaryDirectory(prefix="q2-remote-") as td:
    root = pathlib.Path(td); keyfile = root / "key"; keyfile.write_text("0123456789abcdef\n")
    mounts, cache = root / "mounts", root / "cache"
    card = lambda on: mounts.write_text(f"/dev/mmcblk4p1 {root} vfat rw 0 0\n" if on else "")
    card(True)
    port = 32000 + os.getpid() % 20000
    q.PORT = port
    exe = root / "q2remote"
    subprocess.run(["cc", "-DREMOTE_HOST", f'-DKEY_FILE="{keyfile}"', f'-DCARD="{root}"', f'-DMOUNTS="{mounts}"',
                    f'-DCACHE_FILE="{cache}"', f"-DPORT={port}",
                    str(pathlib.Path(__file__).resolve().parents[1] / "patch/remote.c"), "-o", str(exe)], check=True)
    proc = subprocess.Popen([exe])
    try:
        time.sleep(.1)
        assert cache.read_text() == "0123456789abcdef\n"  # kept at start, before any client
        os.environ.update(Q2_HOST="127.0.0.1", Q2_KEY="0123456789abcdef")
        assert q.shell("cat", b"\x00binary\xff") == b"\x00binary\xff"
        for _ in range(3): assert q.shell("printf repeated") == b"repeated"
        # The CLI transports long/multiline scripts without sharing script text as command stdin.
        for command, expected in (("printf first; read x; printf done", b"firstdone"),
                                  ("read x\nprintf done", b"done"),
                                  ("#" + "x" * 5000 + "\nprintf long", b"long")):
            output = io.TextIOWrapper(io.BytesIO())
            with contextlib.redirect_stdout(output): assert q.main(["sh", command]) == 0
            assert output.buffer.getvalue() == expected

        os.environ["Q2_KEY"] = "ffffffffffffffff"
        try: q.shell("printf should-not-run")
        except PermissionError: pass
        else: raise AssertionError("wrong key accepted")
        os.environ["Q2_KEY"] = "0123456789abcdef"
        keyfile.write_text("fedcba9876543210\n")
        try: q.shell("printf stale")
        except PermissionError: pass
        else: raise AssertionError("rotated key accepted old key")
        os.environ["Q2_KEY"] = "fedcba9876543210"
        assert q.shell("printf rotated") == b"rotated"
        for invalid_key in ("short\n", "bad key with spaces\n", "x" * 128):
            keyfile.write_text(invalid_key)
            try: q.shell("printf invalid")
            except PermissionError: pass
            else: raise AssertionError("malformed card key accepted")
        keyfile.write_text("fedcba9876543210\n")
        keyfile.unlink()
        try: q.shell("printf removed")
        except PermissionError: pass
        else: raise AssertionError("missing key accepted")
        keyfile.write_text("fedcba9876543210\n")
        # Partial and malformed request lines are rejected without running the command; split reads still work.
        with socket.create_connection(("127.0.0.1", port), 2) as s:
            s.sendall(b"fedcba98")
        with socket.create_connection(("127.0.0.1", port), 2) as s:
            for part in (b"fedcba98", b"76543210\n", b"\n"):
                s.sendall(part); time.sleep(.01)
            assert s.recv(16) == b"ERR\n"
        with socket.create_connection(("127.0.0.1", port), 2) as s:
            for part in (b"fedcba98", b"76543210\n", b"true\n"):
                s.sendall(part); time.sleep(.01)
            assert s.recv(16).startswith(b"OK\n")
        # Shared over USB storage the card is unmounted: the last key read from it still works, until
        # the card is back without its key.
        assert q.shell("printf cached") == b"cached" and cache.read_text() == "fedcba9876543210\n"
        card(False); keyfile.unlink()
        assert q.shell("printf away") == b"away"
        card(True)
        try: q.shell("printf revoked")
        except PermissionError: pass
        else: raise AssertionError("key removed from the card still accepted")
        card(False)
        try: q.shell("printf revoked-away")
        except PermissionError: pass
        else: raise AssertionError("revoked cache accepted")
        assert not cache.exists()
        card(True); keyfile.write_text("fedcba9876543210\n")
        with socket.create_connection(("127.0.0.1", port), 2) as s:
            s.sendall(b"fedcba9876543210\n")
            s.settimeout(12)
            assert s.recv(16) == b""  # 10-second handshake timeout
    finally:
        proc.terminate(); proc.wait(timeout=2)
print("Remote auth, rotation/removal, USB-storage key cache, fragmented requests, binary stdin/output, timeout, devices and framebuffer checks passed.")
