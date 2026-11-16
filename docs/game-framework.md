# Internal built-in game framework (experimental)

This is a **portable foundation**, not yet a linked firmware feature. Existing
Games (Sudoku, Vortex, Solitaire, Snake) remain unchanged. Pong and Blocks have
a separate portable rules module (`arcade_core.c`), not yet wired to this runner.

## Existing hardware integration

- `patch/navigation.c` intercepts buttons in `games_key` before stock.
- `patch/games.c` dispatches keys to each built-in game, and Vortex uses
  `wheel_raw` / `wheel_travel` (200 raw units per revolution).
- `games.c` uses the firmware `timer_add`, `games_paint`, `BLOB_IO`,
  `games_seal`, and built-in popups.
- Touch is not currently dispatched into built-in game logic by `games.c`.
  A touch adapter must be added carefully without stealing the Games chooser's
  touch events or stock system gestures.

## Reusable core

`patch/game_framework.h` declares a small callback interface:
`input`, `step`, `paint`, `reset`. `game_framework.c` provides runner
lifecycle (start, pause, resume, restart, game over), normalized wheel/key/touch
events and fixed-step accumulator with at most four ticks per host call.

The framework has **no dependencies on AWTK, POSIX APIs or allocations** and can
be used for a future browser/WebAssembly runner. A firmware adapter will map
Q2 hardware keycodes (Centre 218, Return 170, etc.) to `Q2GameAction`,
consume raw travel for analog games, and send touch coordinates in view space.

`Q2_GAME_PLAY` is reserved by the framework for pause/resume. Return and
game-over menu behavior remain the firmware UI's responsibility so it can
preserve the existing Return-hold/Home behavior.

## Host tests

```sh
sh test/game_framework.sh
sh test/arcade_core.sh
```

## Integration checklist

1. Attach the portable runner to Pong and Blocks using a small adapter.
2. Extend Games menu, paint dispatch and timer only after tests pass.
3. Leave legacy games untouched until compatibility is demonstrated.
4. Respect power-off/overlay pause behavior and raw-wheel cleanup on exit.
5. Only then test a full firmware build and real-hardware wheel/touch behavior.

Do not flash this branch expecting the new games to appear yet.
