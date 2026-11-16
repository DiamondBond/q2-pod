# Built-in arcade games: development branch

Pong and a lightweight falling-block game are being developed as **built-in**
Q2 Pod games, with original game code and no downloaded proprietary assets.

## Current status

Portable game-rule layer only. This branch does **not yet** add Pong or the
falling-block game to Library > Games, nor modify the firmware payload, nor
provide a flashable update. The next stage must connect this module to
`patch/games.c` using Q2 Pod's existing drawing, timer, key, and save APIs.
Check Q2 Pod build inclusion before linking an additional compilation unit.

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
```

## Planned Q2 hardware mapping

| Control | Pong | Blocks |
| --- | --- | --- |
| Wheel | Player paddle up/down | Move piece left/right |
| Centre | Serve / restart | Rotate clockwise |
| Play/Pause | Pause | Pause |
| Prev / Next | - | Soft / hard drop |
| Return | Game menu | Game menu |

Pong coordinates use an internal 320x240 arena; the renderer will scale this
to the Games page drawing rect. Game ticks should be driven from the existing
firmware timer, not direct hardware polling.

## Future click-wheel game preservation work

Reference: https://github.com/Olsro/ipodclickwheelgamespreservationproject

That project preserves original iPod game binaries and an offline distribution
workflow, not reusable Q2 game source code. Direct binaries are not
Q2-compatible and may have licensing/DRM constraints. Evaluate each potential
port individually; prefer licensed open-source game logic and original assets.
No proprietary iPod game code or artwork is included here.
