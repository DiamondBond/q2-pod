# Built-in game framework: developer notes

For the **complete built-in game list**, gameplay details, controls and testing,
see [Built-in games and reusable game framework](builtin-games.md).

## Purpose

The portable framework separates reusable game lifecycle and input handling
from Q2-specific firmware hooks. It provides a small foundation for adding
games without duplicating pause/resume, update scheduling and normalized
input handling across implementations.

The seven menu entries on `new-builtin-games` are Sudoku, Vortex, Solitaire,
Snake, Pong, Blocks and Breakout. The first four preserve their existing
implementations; Pong, Blocks and Breakout are integrated through portable
game cores and firmware-specific adapters.

**Current status:** `patch/game_framework.c` is implemented and tested, but
the built-in games are **not yet migrated to its `Q2GameRunner` callback
runner**. The existing firmware timer and control path currently drives the
games. Do not describe the runner as already responsible for all seven games.

## Reusable interface

`patch/game_framework.h` defines:

- `Q2GameInput`: normalized wheel, center, return, play/pause,
  previous/next and touch events, including signed wheel travel and
  view-relative touch coordinates.
- `Q2GameHooks`: `input`, `step`, `paint`, `reset` callbacks with
  a game-owned context.
- `Q2GameRunner`: status (`RUNNING`, `PAUSED`, `OVER`), configurable
  fixed step, remainder accumulator and touch-active state.
- `q2_game_init`, `q2_game_input`, `q2_game_advance`,
  `q2_game_paint`, `q2_game_pause`, `q2_game_resume`,
  `q2_game_over`, `q2_game_restart`.

`q2_game_advance` caps catch-up at four fixed steps per call. Paused and
game-over states do not advance simulation. `Q2_GAME_PLAY` is handled by
the framework as pause/resume; Return and game-over menu presentation remain
the firmware UI's responsibility.

The framework is written in portable C without AWTK, POSIX APIs or heap
allocation. Hardware and UI services are supplied by adapters.

## Current firmware path

- `patch/navigation.c`: routes Games input before stock handling.
- `patch/games.c`: menu selection, existing game code and dispatch.
- `patch/arcade_core.c`: Pong and Blocks gameplay rules.
- `patch/breakout_core.c`: Breakout gameplay rules.
- `patch/arcade_gameplay.inc`: wheel sampling, hardware keys and timer ticks.
- `patch/arcade_draw.inc`: AWTK canvas painting.
- Existing `timer_add`, `BLOB_IO`, integrity checks, and UI popups are
  reused in the firmware layer.

Raw wheel travel is used for analog-style paddle movement, while discrete
previous/next keys support Blocks movement. The framework's touch actions
are prepared for a future adapter, but touch is not presently dispatched
into the built-in game logic; it must not interfere with the chooser or
stock touch gestures.

## Tests

```sh
sh test/game_framework.sh
sh test/arcade_core.sh
sh test/breakout_core.sh
```

See [the canonical built-in games guide](builtin-games.md#testing) for
firmware integration and physical-hardware validation requirements.
Emulation tooling and emulator-specific tests belong to `desktop-simulator`.

## Remaining migration work

1. Add a firmware adapter for the `Q2GameRunner` callbacks.
2. Migrate the new games incrementally without changing control semantics.
3. Preserve pause, Return-hold/Home and power-management behavior.
4. Keep older game save formats and controls intact during migration.
5. Validate MIPS packaging, input, rendering and persistence on actual Q2
   hardware before migrating more games.
