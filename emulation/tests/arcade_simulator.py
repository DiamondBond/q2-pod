#!/usr/bin/env python3
"""Check Unicorn games inside the desktop simulator model (headless, no Tk)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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


def check_mounted_apps():
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as folder:
        root = Path(folder)
        app = root / ".fidget"
        app.mkdir()
        (app / "q2app").write_text("name=Buddy\ngame=1\n", encoding="utf-8")
        (app / "q2-fidget").touch()
        app = root / ".filebrowser"
        app.mkdir()
        (app / "q2app").write_text("name=File Browser\n", encoding="utf-8")
        (app / "q2-filebrowser").touch()
        rockbox = root / ".rockbox" / "rockbox"
        rockbox.parent.mkdir()

        ui = Simulator("modern", [])
        ui.open_library()
        ui.select_library(LibraryRow("Games", "games"))
        assert all(row.name != "Buddy" for row in ui.library_rows)
        ui.mount_card([], root)
        assert ui.library_title == "Games"
        assert LibraryRow("Buddy", "card-game:fidget") in ui.library_rows
        assert all(row.name != "File Browser" for row in ui.library_rows)
        ui.back()
        ui.back()

        assert ("rockbox", "Rockbox") not in ui.home_items()
        ui.cursor = ui.home_items().index(("settings", "Settings"))
        ui.enter()
        rockbox.touch()
        ui.store.events.put(("done", "Rockbox installed"))
        ui.advance(0)
        ui.back()
        assert ui.home_items()[ui.cursor] == ("settings", "Settings")
        assert ("rockbox", "Rockbox") in ui.home_items()
        assert ui.store.has_rockbox(root)
        ui.cursor = ui.home_items().index(("rockbox", "Rockbox"))
        ui.enter()
        assert "Start it on the Q2" in ui.hint

        ui.cursor = ui.home_items().index(("stream", "Streaming"))
        ui.enter()
        assert ui.library_title == "Streaming"
        assert ui.library_rows == [LibraryRow("File Browser", "card-app")]

        # Starting the simulator with the same card needs no App Store record.
        restarted = Simulator("modern", [], sd_card=root)
        assert ("rockbox", "Rockbox") in restarted.home_items()
        assert LibraryRow("Buddy", "card-game:fidget") in restarted.game_rows()

        rockbox.unlink()
        restarted.store.events.put(("done", "Rockbox removed"))
        restarted.advance(0)
        assert ("rockbox", "Rockbox") not in restarted.home_items()


check_mounted_apps()
print("Mounted Buddy, streaming apps and the Rockbox Home shortcut verified")


def check_breakout():
    from types import SimpleNamespace
    from simulator_firmware import BUILTIN_GAMES

    firmware = SimpleNamespace(custom=True, builtin_games=(*BUILTIN_GAMES, "Breakout"))
    ui = Simulator("modern", [], firmware)
    ui.show_library("Games", ui.game_rows())
    ui.cursor = next(i for i, row in enumerate(ui.library_rows) if row.name == "Breakout")
    try:
        ui.enter()
        assert ui.page == "arcade", ui.hint
        game = ui.arcade
        initial = game.machine.breakout()
        assert initial.remaining == 40 and initial.lives == 3 and initial.waiting
        ui.move(1)
        assert game.machine.breakout().paddle_x == initial.paddle_x + 14
        ui.enter()
        assert not game.machine.breakout().waiting
        ui.advance(.05)
        assert game.machine.breakout().ball_y < initial.ball_y
        assert game.render_screen().size == (375, 320)
        ui.toggle()
        assert game.paused
        ui.toggle()
        ui.back()
        assert game.menu
        ui.move(1)
        ui.enter()
        assert ui.page == "library" and ui.arcade is None
    finally:
        ui.close_arcade()


check_breakout()
print("Breakout launches from Games and runs MIPS paddle, serve, frame, pause and exit")
