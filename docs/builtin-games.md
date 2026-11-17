# Built-in games and reusable game framework

This guide is the single overview of the **eight built-in games** on the
`new-builtin-games` development branch, their controls, implementation, and
testing. All eight are registered under **Library → Games** in
`patch/games.c`. They are part of the firmware; separate app downloads are
not needed. Downloadable card apps (such as Buddy and Groovebox) are a
different feature and are not counted as built-in games.

> **Development status:** Source integration does not mean the firmware
> package has been successfully installed or validated on a physical Q2.
> Build from this branch, confirm the eight menu entries, and validate on
> hardware before treating this work as release-ready.

## Complete built-in game list

| Menu order | Game | Status in this branch | Description and saved data |
| --- | --- | --- | --- |
| 1 | **Sudoku** | Existing | Number-placement puzzle; saved puzzle progress |
| 2 | **Vortex** | Existing | Circular arcade action; persistent best score |
| 3 | **Solitaire** | Existing | Card game; saved game state |
| 4 | **Snake** | Existing | Grow the snake while avoiding collisions; persistent best score |
| 5 | **Pong** | New | Player paddle versus CPU; ball bounce, serves and scoring |
| 6 | **Blocks** (Tetris-style) | New | 10×20 field, seven tetrominoes, 7-bag selection, line clearing, levels and persistent best score |
| 7 | **Breakout** | New | 8×5 brick grid, paddle and ball, three lives, level progression and persistent best score |
| 8 | **2048** | New | 4×4 sliding puzzle with a saved board and best score |

The existing four games remain in the Games menu with their established
controls. New games extend the menu rather than replacing the older games.

### New game behavior

- **Pong:** wheel-controlled paddle, CPU paddle, wall/paddle collisions,
  scoring, and new serves. It uses an internal 320×240 arena scaled to the
  Games drawing area.
- **Blocks:** seven shapes, a deterministic 7-bag, clockwise rotation with
  simple horizontal kicks, gravity, soft/hard drop, line completion and
  increasing speed as levels advance.
- **Breakout:** five rows of eight bricks, click-wheel paddle, center-button
  ball launch, row-dependent points, three lives, successive levels and
  saved best score.

## Q2 controls for the new games

| Input | Pong | Blocks | Breakout |
| --- | --- | --- | --- |
| Click wheel | Move paddle up/down | Rotate piece counterclockwise / clockwise | Move paddle left/right |
| Centre | No game-specific action | Hard drop; restart after game over | Launch docked ball; restart after game over |
| Previous / Next wheel ticks | Nudge paddle | Wheel rotation is handled through raw travel | Nudge paddle |
| Side Previous / Next (Left / Right) | Nudge paddle | Move piece left / right | Nudge paddle |
| Down (physical Play/Pause) | Pause/resume | Soft drop faster (up to three rows per press) | Pause/resume |
| Return / Back | Game menu | Pause and open Continue/Quit menu | Game menu |

**2048:** Turn the wheel to select a direction and press Centre to slide.
The side Previous and Next buttons slide left and right directly.
Play/Pause pauses or resumes. Return opens the pause menu, where **Game options**
offers New game and Quit. Reach 2048 and press Centre to keep playing. A full
board with no available merge ends the round.

The rules are based on [Gabriele Cirulli’s 2048](https://github.com/gabrielecirulli/2048)
and the [Q2 card port](https://github.com/lampsonlnguyen/q2-2048), with the
compact exponent representation used by [Maurits van der Schee’s 2048.c](https://github.com/mevdschee/2048.c).

Legacy games keep their existing controls. On-device control responsiveness,
screen rendering, and pause/exit interaction still need hardware verification.

## Why the code is split into reusable modules

Previously, `patch/games.c` handled many concerns together: Games menu
navigation, individual games' logic, hardware input, painting, timers and save
data. Adding each new game directly to that file would make it increasingly
large, tightly coupled and difficult to test.

This branch separates **portable game rules** from **firmware adapters** and
provides a small **shared framework**. The intent is to let a contributor
implement a new game's state and rules without rewriting common lifecycle,
input, timing or menu behavior.

| File | Responsibility |
| --- | --- |
| `patch/game_framework.h` / `.c` | Reusable portable runner: normalized input events, game lifecycle, fixed-step timing and callbacks |
| `patch/arcade_core.h` / `.c` | Portable Pong and Blocks rules |
| `patch/breakout_core.h` / `.c` | Portable Breakout rules |
| `patch/tile2048.h` / `.c` | Portable 2048 rules |
| `patch/arcade_gameplay.inc` | Firmware-specific wheel/button input and game timing |
| `patch/arcade_draw.inc` | Rendering through the existing AWTK canvas |
| `patch/games.c` | Game selection, existing games, dispatch, UI interactions and persistence |
| `patch/peq.h` | `GAMES_BUILTIN` count (8) |
| `tools/peq.py` | Registers sources for the firmware MIPS payload |

### Framework interface

`Q2GameHooks` defines four callbacks:

| Hook | Purpose |
| --- | --- |
| `input(context, event)` | Respond to normalized wheel/button/touch events |
| `step(context, step_ms)` | Advance simulation at a fixed time step |
| `paint(context, canvas)` | Render the current state |
| `reset(context)` | Initialize or restart the game |

`Q2GameRunner` retains a per-game context, running/paused/game-over status,
fixed-step timing accumulator and touch-active state. The core runner bounds
catch-up work to four steps per call. It does not depend on AWTK, OS APIs,
heap allocation or floating-point operations.

This makes rules easier to test independently of the Q2 hardware without
duplicating game rules. Desktop emulation tooling is maintained separately on
the `desktop-simulator` branch.

**Current integration boundary:** The framework is an implemented and
independently tested **foundation**, not yet a runner adopted by every game.
2048 uses the runner for input, lifecycle and drawing, with updates driven by button events.
Pong, Blocks and Breakout currently use portable rules with adapters calling
the firmware's existing timers, drawing, wheel input, pause/return and save
services. Sudoku, Vortex, Solitaire and Snake remain on their existing
implementations. A future change can gradually move games onto the framework
callbacks after demonstrating compatibility.

### Adding a game in the future

1. Define the game's state and rules in a small portable C module.
2. Prefer common input and lifecycle conventions from `game_framework.h`;
   use the callback runner when the firmware adapter supports it.
3. Implement the AWTK drawing and Q2 input/timer adapter.
4. Register the game in `patch/games.c`, update `GAMES_BUILTIN` and
   firmware source registration as necessary.
5. Add native tests, firmware cross-compilation checks and integration tests
   before testing on hardware.

The design favors compact, integer-based rules, static state and bounded
per-frame work because the Q2 has limited hardware resources. No proprietary
iPod games or artwork are included.

## Persistence

The existing integrity-checked firmware blob mechanism is reused rather than
introducing a new storage format:

- Sudoku: puzzle progress
- Solitaire: game state
- Vortex and Snake: best scores
- Blocks and Breakout: best scores
- 2048: board, score, best score and keep-playing state

Pong does not currently have a persistent high-score entry.

## Testing

From the repository root:

```sh
sh test/arcade_core.sh
sh test/breakout_core.sh
sh test/tile2048.sh
sh test/game_framework.sh
```

Automated coverage includes native C rules, the framework's lifecycle,
undefined-behavior sanitizer checks and mocked firmware integration tests.
The arcade GitHub Actions workflow also cross-compiles the Games code for MIPS.
Emulation-specific tests are maintained on the `desktop-simulator` branch.

**Before release or flashing:** validate a complete firmware package built
from the intended branch and the stock firmware archive; then exercise all
eight games on a real Q2, including navigation, controls, rendering,
pause/resume, restart, persistence and performance. Passing host tests alone does not establish hardware compatibility.

## Future work

- Gradually migrate legacy games and newer adapters to the common callback
  runner while preserving behavior and saved data.
- Simplify `patch/games.c` by moving more game-specific code into modules.
- Keep desktop emulator development and tests on the `desktop-simulator` branch.
- Add game templates, further titles and hardware regression coverage.

## Related material

- [Game framework implementation notes](game-framework.md)
- [Building firmware](building.md)
- [Main README](../README.md)
- [Click-wheel game preservation reference](https://github.com/Olsro/ipodclickwheelgamespreservationproject)
  (reference only; its original binaries are not directly compatible with Q2,
  and licensing/DRM must be evaluated for any individual port).
