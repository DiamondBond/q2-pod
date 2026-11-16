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

for name in ("Vortex", "Snake"):
    ui = Simulator("classic-light", [])
    ui.open_library()
    ui.select_library(LibraryRow("Games", "games"))
    ui.paused = False
    ui.select_library(next(row for row in ui.library_rows if row.name == name))
    assert ui.page == "arcade", ui.hint
    assert ui.arcade is not None and not ui.paused
    image, hits = ui.frame(None)
    assert image.size == (375, 320) and not hits
    machine = ui.arcade.machine
    if name == "Vortex":
        assert machine.vortex().state == 0
        ui.arcade.on_wheel(0.5)
        ui.advance(0.02)
        moved = machine.vortex()
        assert moved.pa != 768
        ui.button("center")
        assert machine.vortex().state == 1
        for _ in range(25):
            ui.advance(0.02)
        assert machine.vortex().score > 0
    else:
        before = machine.snake()
        ui.arcade.on_wheel(0.8)
        assert machine.snake().dir == before.dir
        ui.button("left")
        for _ in range(8):
            ui.advance(0.02)
        after = machine.snake()
        assert after.dir == 0 and after.body[3] == before.body[2] - 20

    ui.toggle()
    assert ui.arcade.paused
    stopped = bytes(ui.arcade.firmware_state())
    ui.advance(0.1)
    assert bytes(ui.arcade.firmware_state()) == stopped
    ui.toggle()
    assert not ui.arcade.paused
    ui.back()
    assert ui.arcade.menu
    ui.move(1)
    ui.button("center")
    assert ui.page == "library" and ui.library_title == "Games" and ui.arcade is None

print("Snake and Vortex launch, MIPS rules, steering, pause and quit passed")


for name in ("Sudoku", "Solitaire"):
    ui = Simulator("classic-light", [])
    ui.open_library()
    ui.select_library(LibraryRow("Games", "games"))
    ui.select_library(next(row for row in ui.library_rows if row.name == name))
    assert ui.page == "arcade", ui.hint
    assert ui.arcade is not None and ui.arcade.game == name.lower()
    machine, puzzle = ui.arcade.machine, ui.arcade.puzzle
    assert ui.frame(None)[0].size == (375, 320)
    if name == "Sudoku":
        initial = bytes(machine.sudoku().cell)
        assert any(initial) and 0 in initial
        ui.move(initial.index(0))
        ui.enter()
        assert puzzle.pick == 0
        ui.move(4)
        ui.enter()
        assert machine.sudoku().cell[puzzle.cursor] == 4
        ui.toggle()
        assert puzzle.confirm
        ui.back()
        assert machine.sudoku().cell[puzzle.cursor] == 4
    else:
        assert tuple(machine.solitaire().len) == (24, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7)
        ui.enter()
        assert tuple(machine.solitaire().len[:2]) == (23, 1)
        ui.move(1)
        ui.enter()
        assert puzzle.pick == 1
        ui.back()
        assert puzzle.pick is None
        ui.toggle()
        assert puzzle.confirm
        ui.enter()
        assert tuple(machine.solitaire().len[:2]) == (24, 0)
    ui.back()
    assert ui.page == "library" and ui.library_title == "Games" and ui.arcade is None

print("Sudoku and Solitaire launch, MIPS moves, new game and return routing passed")
