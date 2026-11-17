#!/usr/bin/env python3
"""Boot an actual Buddy MIPS executable and drive it through the simulator."""
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simulator import Simulator


with TemporaryDirectory() as directory:
    card = Path(directory)
    shutil.copytree(Path(sys.argv[1]), card / ".fidget")
    ui = Simulator("classic-light", [], sd_card=card)
    ui.open_library()
    ui.cursor = next(i for i, row in enumerate(ui.library_rows) if row.name == "Games")
    ui.enter()
    ui.cursor = next(i for i, row in enumerate(ui.library_rows) if row.name == "Buddy")
    ui.enter()
    assert ui.page == "buddy", ui.hint
    guest = ui.buddy
    assert guest is not None
    now = [100.0]
    guest.clock = lambda: now[0]
    guest.watchdog = now[0]
    guest.wall = lambda: 1_750_000_000

    def until(condition):
        for _ in range(480):
            now[0] += 1 / 60
            ui.advance(1 / 60)
            if condition():
                return
            assert ui.page == "buddy", ui.hint
        raise AssertionError(f"Buddy did not reach expected state after {guest.frames} frames: {ui.hint}")

    until(lambda: guest.frames >= 2)
    frame, _ = ui.frame(None)
    assert frame.size == (375, 320) and frame.getbbox() is not None
    ui.back()
    menu_frame = guest.frames + 3
    until(lambda: guest.frames >= menu_frame)
    guest.send("t d 187 179")
    guest.send("t u 187 179")
    until(lambda: (card / ".fidget" / "state").is_file())
    assert (card / ".fidget" / "state").read_bytes()[1:] == b"1"
    guest.send("t d 187 216")
    guest.send("t u 187 216")
    until(lambda: ui.page == "library")
    assert guest.exit_code == 0 and ui.buddy is None

print("Buddy MIPS executable rendered frames, handled touch and saved Tamagotchi state")
