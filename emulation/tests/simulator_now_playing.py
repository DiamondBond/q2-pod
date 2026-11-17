#!/usr/bin/env python3
"""Check which packaged Now Playing geometry the desktop simulator renders."""

from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import simulator
import simulator_firmware as sf


def playing(cover_box):
    return ("window", (0, 0, 375, 290), {"name": "playing_page"}, [
        ("image", cover_box, {"name": "img_cover"}, []),
        ("label", (200, 70, 110, 20), {"name": "scrlabel_title"}, []),
        ("label", (200, 90, 110, 20), {"name": "scrlabel_artist"}, []),
        ("label", (200, 110, 110, 20), {"name": "label_ipod_album"}, []),
        ("slider", (60, 252, 255, 6), {"name": "slider_play"}, []),
    ])


assets = {
    "fonts/default.ttf": b"font",
    "ui/playing_page.bin": b"base",
    "ui/classic-light_playing_page.bin": b"classic",
    "ui/home_page.bin": b"home",
    "ui/folder_page.bin": b"folder",
}
decoded = {
    b"base": playing((20, 50, 120, 120)),
    b"classic": playing((40, 40, 100, 120)),
    b"folder": ("window", (0, 0, 375, 290), {"name": "folder_page"}, []),
}


def read_asset(command, **_kwargs):
    if command[1] == "-ls":
        listing = "\n".join("squashfs-root/" + sf.RAW + name for name in assets)
        return SimpleNamespace(stdout=listing.encode())
    return SimpleNamespace(stdout=assets[command[-1].removeprefix(sf.RAW)])


with (patch.object(sf, "read_rootfs", return_value="test"),
      patch.object(sf.subprocess, "run", side_effect=read_asset),
      patch.object(sf.ipod, "decode", side_effect=decoded.__getitem__),
      patch.object(sf, "home_entries", return_value=())):
    firmware = sf.load_firmware(Path("update.tar"))

assert firmware.now_playing("classic-light")["img_cover"].box == (40, 40, 100, 120)
assert firmware.now_playing("ipod") is firmware.page

fonts = SimpleNamespace(face=lambda face, title, size: (face, size),
                        artist=lambda value: (value, "default"))
track = simulator.Track("Track", "Artist", "Album", art=b"cover", duration=180)
with (patch.object(simulator, "label"), patch.object(simulator, "status_bar"),
      patch.object(simulator, "cover", side_effect=lambda _, size, __:
                   (Image.new("RGB", (size, size), "red"), None))):
    classic, _ = simulator.render(track, fonts, "classic-light", firmware=firmware)
    modern, _ = simulator.render(track, fonts, "modern", firmware=firmware)
assert classic.getpixel((40, 26 + 40)) == (255, 0, 0)
assert classic.getpixel((40, 26 + 40 + 100)) != (255, 0, 0)
assert modern.getpixel((20, 30 + 50)) == (255, 0, 0)
assert modern.getpixel((40, 26 + 40)) != (255, 0, 0)
print("Now Playing selects the packaged theme geometry and aligns the cover and status bar")
