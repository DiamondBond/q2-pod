#!/usr/bin/env python3
"""Drive a --dev Q2 over Wi-Fi (Q2_HOST and Q2_KEY required; see docs/remote.md).

usage: q2remote.py {sh COMMAND|shot OUT.png|devices|key NAME [MS]|wheel N|tap X Y|events EVENT [S]|reboot}"""
import os
import re
import shlex
import socket
import struct
import sys
import zlib

PORT = 2302
W, H = 320, 375
# md-gpio-keys codes; Centre is KEY_POWER (hold 5 s for the shutdown prompt), Return is KEY_UP.
KEYS = {"centre": 116, "center": 116, "return": 103, "play": 108, "next": 163, "prev": 165}
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
BTN_TOUCH, ABS_X, ABS_Y, ABS_PRESSURE = 0x14a, 0, 1, 0x18
WHEEL_UNITS, WHEEL_STEP, WHEEL_SETTLE, SAMPLE_US = 28, 11, 4, 20000
TIMEOUT = 30


def event(kind, code, value):
    return struct.pack("<IIHHi", 0, 0, kind, code, value)


def shell(cmd, data=b"", timeout=TIMEOUT):
    host, key = os.environ.get("Q2_HOST"), os.environ.get("Q2_KEY")
    if not host or not key:
        raise ValueError("set Q2_HOST and Q2_KEY")
    try:
        with socket.create_connection((host, PORT), timeout) as s:
            s.sendall(key.encode() + b"\n" + cmd.encode() + b"\n" + data)
            s.shutdown(socket.SHUT_WR)
            out = bytearray()
            while part := s.recv(65536):
                out.extend(part)
    except socket.timeout as e:
        raise TimeoutError("network timeout talking to Q2") from e
    except OSError as e:
        raise ConnectionError(f"cannot reach Q2 at {host}:{PORT}: {e}") from e
    # The helper answers ERR and closes, or OK and then the output.
    if not out.startswith(b"OK\n"):
        raise PermissionError("authentication rejected (check Q2_KEY and /mnt/mmc/q2remote.key)")
    return bytes(out[3:])


def parse_devices(text):
    """Parse /proc/bus/input/devices; each result includes name, handlers, and capability bitsets."""
    result = []
    for block in re.split(r"\n\s*\n", text.strip()):
        name = re.search(r'^N: Name="(.*)"$', block, re.M)
        handlers = re.search(r"^H: Handlers=(.*)$", block, re.M)
        if not name or not handlers:
            continue
        caps = {}
        for kind in ("KEY", "ABS"):
            m = re.search(rf"^B: {kind}=(.*)$", block, re.M)
            # Kernel prints unpadded words, most significant first; the Q2 kernel's long is 32-bit.
            caps[kind] = sum(int(w, 16) << 32 * i for i, w in enumerate(reversed(m.group(1).split()))) if m else 0
        events = re.findall(r"event(\d+)", handlers.group(1))
        if events:
            result.append({"name": name.group(1), "event": int(events[0]), "handlers": handlers.group(1), **caps})
    return result


def bits(bitmap):
    return {n for n in range(bitmap.bit_length()) if bitmap >> n & 1}


def decode_events(data):
    if len(data) % 16:
        raise ValueError("truncated input-event stream")
    return list(struct.iter_unpack("<IIHHi", data))


def key_events(code):
    return [event(EV_KEY, code, 1) + event(EV_SYN, 0, 0),
            event(EV_KEY, code, 0) + event(EV_SYN, 0, 0)]


def touch_xy(x, y):
    return W - 1 - y, x


def wheel_positions(ticks, units=WHEEL_UNITS, start=100):
    """x samples (1-200 a turn) for `ticks` firmware ticks; positive falls, which is next/down.

    Travel overshoots by half a tick so rounding never loses one, and the final x repeats
    WHEEL_SETTLE times: tslib's dejitter averages small moves, so a gesture that lifts straight
    after its last step lands short."""
    travel = round((abs(ticks) + .5) * units)
    n = -(-travel // WHEEL_STEP)
    sign = -1 if ticks > 0 else 1
    points = [(start + sign * (travel * i // n) - 1) % 200 + 1 for i in range(1, n + 1)]
    return points + points[-1:] * WHEEL_SETTLE


def wheel_units(config):
    """Travel per tick from config.ini's Q2POD WHEELSENSITIVITY, as playback.c reads it."""
    m = re.search(r"^WHEELSENSITIVITY=(\d+)\s*$", config, re.M)
    pct = int(m.group(1)) if m and m.group(1) == str(int(m.group(1))) else 50
    return WHEEL_UNITS * 50 / (pct if 50 <= pct <= 200 and pct % 10 == 0 else 50)


def event_writer(path, batches, delay_us=SAMPLE_US):
    commands = []
    for i, batch in enumerate(batches):
        if i:
            commands.append(f"usleep {delay_us}")
        octets = "".join(f"\\{byte:03o}" for byte in batch)
        commands.append(f"printf '%b' {shlex.quote(octets)} > {shlex.quote(path)}")
    return "; ".join(commands)


def devices():
    return parse_devices(shell("cat /proc/bus/input/devices").decode("utf-8", "replace"))


def framebuffer_png(data):
    # helper emits Q2FB\0, little-endian width/height/stride/size, then the displayed page.
    if len(data) < 21 or data[:5] != b"Q2FB\0":
        raise ValueError("invalid framebuffer response")
    w, h, stride, size = struct.unpack_from("<IIII", data, 5)
    pixels = data[21:]
    if (w, h) != (W, H) or stride < w * 4 or size != stride * h or len(pixels) != size:
        raise ValueError("invalid or truncated framebuffer data")
    rows = [pixels[y * stride:y * stride + w * 4] for y in range(h)]
    # FB pixels are BGRA; rotate portrait framebuffer counterclockwise to upright 375x320.
    raw = b"".join(bytes((p[2], p[1], p[0], p[3])) for y in range(w) for x in range(h)
                    for p in (rows[x][(w - 1 - y) * 4:(w - y) * 4],))
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    def chunk(tag, body):
        payload = tag + body
        png.extend(struct.pack(">I", len(body)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xffffffff))
    chunk(b"IHDR", struct.pack(">2I5B", H, W, 8, 6, 0, 0, 0))
    chunk(b"IDAT", zlib.compress(b"".join(b"\0" + raw[y * H * 4:(y + 1) * H * 4] for y in range(W))))
    chunk(b"IEND", b"")
    return bytes(png)


def screenshot(out):
    png = framebuffer_png(shell("/usr/bin/q2remote --shot"))  # no empty file left on an error
    with open(out, "wb") as f:
        f.write(png)


def input_action(kind, args):
    devs = {d["name"]: f"/dev/input/event{d['event']}" for d in devices()}
    need = {"key": "md-gpio-keys", "tap": "hyn_ts", "wheel": "hyn_sliderbar"}[kind]
    if need not in devs: raise ValueError(f"no {need} input device; inspect `devices`")
    path = devs[need]
    if kind == "key":
        code = KEYS.get(args[0].lower())
        if code is None: raise ValueError(f"key must be one of {', '.join(KEYS)}")
        try: ms = int(args[1]) if len(args) > 1 else 80
        except ValueError: raise ValueError("key duration must be an integer number of milliseconds")
        if not 1 <= ms <= 60000: raise ValueError("key duration must be 1..60000 ms")
        shell("sh", event_writer(path, key_events(code), ms * 1000).encode())
    elif kind == "tap":
        try: x, y = map(int, args)
        except ValueError: raise ValueError("tap coordinates must be integers")
        if not 0 <= x < H or not 0 <= y < W: raise ValueError(f"coordinates must be x=0..{H-1}, y=0..{W-1}")
        # The touchscreen axes follow the 320x375 portrait panel, while CLI coordinates are upright.
        px, py = touch_xy(x, y)
        batches = [event(EV_ABS, ABS_X, px) + event(EV_ABS, ABS_Y, py) + event(EV_ABS, ABS_PRESSURE, 1) + event(EV_KEY, BTN_TOUCH, 1) + event(EV_SYN, 0, 0),
                   event(EV_ABS, ABS_PRESSURE, 0) + event(EV_KEY, BTN_TOUCH, 0) + event(EV_SYN, 0, 0)]
        shell("sh", event_writer(path, batches).encode())
    elif kind == "wheel":
        try: ticks = int(args[0])
        except ValueError: raise ValueError("wheel travel must be an integer")
        if not -1000 <= ticks <= 1000: raise ValueError("wheel travel must be -1000..1000 ticks")
        if ticks == 0: return
        units = wheel_units(shell("cat /mnt/data/config.ini 2>/dev/null").decode("utf-8", "replace"))
        # Settle frames alternate y so the input core does not drop them as unchanged.
        batches = [event(EV_ABS, ABS_X, 100) + event(EV_ABS, ABS_Y, 100) +
                   event(EV_ABS, ABS_PRESSURE, 1) + event(EV_KEY, BTN_TOUCH, 1) + event(EV_SYN, 0, 0)]
        batches.extend(event(EV_ABS, ABS_X, x) + event(EV_ABS, ABS_Y, 100 + i % 2) + event(EV_SYN, 0, 0)
                       for i, x in enumerate(wheel_positions(ticks, units)))
        batches.append(event(EV_ABS, ABS_PRESSURE, 0) + event(EV_KEY, BTN_TOUCH, 0) + event(EV_SYN, 0, 0))
        shell("sh", event_writer(path, batches).encode())  # stdin: a long turn outgrows the 4 KB command line


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, a = argv[0], argv[1:]
    if cmd == "sh" and len(a) == 1:
        if not a[0]: raise ValueError("sh requires a non-empty command")
        sys.stdout.buffer.write(shell(a[0])); return 0
    if cmd == "shot" and len(a) == 1:
        screenshot(a[0]); return 0
    if cmd == "devices" and not a:
        for d in devices():
            print(f"event{d['event']} {d['name']} handlers={d['handlers']} keys={sorted(bits(d['KEY']))} abs={sorted(bits(d['ABS']))}")
        return 0
    if cmd in ("key", "tap", "wheel"):
        if len(a) not in {"key": (1, 2), "wheel": (1,), "tap": (2,)}[cmd]: raise ValueError(f"invalid arguments for {cmd}")
        input_action(cmd, a); return 0
    if cmd == "reboot" and not a:
        # Detached so the reply arrives before the network drops; the PMIC's 10-15 s Centre reset can't be injected.
        shell("(sleep 1; sync; reboot) </dev/null >/dev/null 2>&1 &"); return 0
    if cmd == "events" and 1 <= len(a) <= 2:
        try: n = int(a[0]); seconds = float(a[1]) if len(a) > 1 else 5
        except ValueError: raise ValueError("events requires an integer event number and seconds")
        if n < 0 or seconds <= 0 or seconds > 3600: raise ValueError("events requires EVENT>=0 and 0<S<=3600")
        # Device busybox has no timeout(1); the stream may be silent for the whole window.
        out = shell(f"cat /dev/input/event{n} 2>/dev/null & p=$!; sleep {seconds:g}; kill $p", timeout=TIMEOUT + seconds)
        for sec, usec, typ, code, value in decode_events(out):
            print(f"{sec}.{usec:06d} type={typ} code={code} value={value}")
        return 0
    raise ValueError(__doc__.splitlines()[-1])


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (ValueError, OSError) as e:
        print(f"q2remote: {e}", file=sys.stderr)
        sys.exit(2)
