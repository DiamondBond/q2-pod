# Built-in arcade games: development branch

Pong and a lightweight falling-block game are being developed as **built-in**
Q2 Pod games, with original game code and no downloaded proprietary assets.

## Current status

Pong and Blocks now appear in `Library → Games` in this branch's
`patch/games.c`. Their actual rules live in `patch/arcade_core.c`, compiled
into the MIPS firmware payload through `tools/peq.py`'s `UI_SOURCES`.
They share the existing Q2 timer, drawing, wheel sampling, pause/menu and
save APIs. The framework module remains an independent portable foundation
pending fuller migration of the legacy games.

**Validation:** Native C and actual MIPS32r2 Unicorn game tests pass in
GitHub Actions. Full firmware packaging (requiring stock V1.36 ZIP), the
existing mocked-firmware regression suite, and physical Q2 input/rendering
tests must also pass before flashing or releasing this branch.

- `patch/arcade_core.h` / `.c`: no dynamic allocation, OS APIs, floating
  point, or third-party dependencies; deterministic integer game state.
- Pong: paddle movement, CPU paddle, wall/paddle bounce, scoring and serve.
- Blocks: 10x20 field, seven shapes, deterministic 7-bag, rotation with
  simple horizontal kicks, gravity, hard drop, line clearing and scoring.
- `test/arcade_core_test.c`: host test of rules and termination.
- `test/arcade_core.sh`: compile and execute tests with a host C compiler.

## Test

```sh
sh test/arcade_core.sh
sh test/game_framework.sh
python3 test/arcade_mips.py --self-test
```

## Q2 hardware mapping

| Control | Pong | Blocks |
| --- | --- | --- |
| Wheel | Player paddle up/down | Move piece left/right |
| Centre | Restart after game over | Rotate clockwise |
| Play/Pause | Pause | Pause |
| Side Prev / Next | Paddle nudge | Soft / hard drop |
| Return | Game menu | Game menu |

Pong coordinates use an internal 320x240 arena; the renderer will scale this
to the Games page drawing rect. Game ticks use the existing firmware timer, not direct hardware polling.
Blocks saves its best score via the firmware's existing integrity-checked blob store.

## Future click-wheel game preservation work

Reference: https://github.com/Olsro/ipodclickwheelgamespreservationproject

That project preserves original iPod game binaries and an offline distribution
workflow, not reusable Q2 game source code. Direct binaries are not
Q2-compatible and may have licensing/DRM constraints. Evaluate each potential
port individually; prefer licensed open-source game logic and original assets.
No proprietary iPod game code or artwork is included here.
