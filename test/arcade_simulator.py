#!/usr/bin/env python3
"""Check Unicorn games inside the desktop simulator model (headless, no Tk)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from simulator import Simulator
from simulator_library import LibraryRow

for game in ("Pong", "Blocks"):
    ui = Simulator("modern", [])
    ui.select_library(LibraryRow(game, "device"))
    assert ui.page == "arcade", ui.hint
    assert ui.arcade is not None
    assert ui.arcade.game == game.lower()
    assert ui.paused  # music should pause when entering a game
    image, hits = ui.frame(None)
    assert image.size == (375, 320) and not hits
    ui.advance(0.05)
    ui.move(1)
    ui.arcade.on_wheel(0.8)  # real pointer drag path, not only discrete menu movement
    ui.arcade.on_wheel(-0.6)
    ui.toggle()
    assert ui.arcade.paused
    ui.toggle()
    assert not ui.arcade.paused
    ui.back()
    assert ui.arcade.menu
    ui.move(1)
    ui.enter()
    assert ui.arcade.scene == "games"
    ui.back()
    assert ui.page == "home" and ui.arcade is None
print("Desktop simulator inline MIPS game tests passed")
