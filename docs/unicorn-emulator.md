# Q2 Pod Unicorn/MIPS game emulator (experimental)

Branch: `unicorn-mips-emulator`, based on `desktop-simulator`.

## What is real

- **Actual little-endian MIPS32r2 game instructions**, compiled from
  `patch/arcade_core.c` using the Q2 firmware's target architecture and
  executed in Unicorn. The host does not reimplement the Pong or Blocks rules.
- The existing desktop simulator's **Q2 chassis graphic and click-wheel
  geometry** (`tools/simulator_device.py`).
- MIPS test from `test/arcade_mips.py`, usable without stock firmware.

## What's simulated

- Display pixels are drawn using Pillow on the host. This is **not** AWTK's
  production renderer and cannot certify font/lyrics/theme pixel accuracy.
- Mouse, scroll wheel and keyboard are translated to game actions by the host.
  The real Q2 device driver is not running.
- The physical X2000 processor peripherals, LCD/ALSA drivers, battery, kernel
  and hardware timings are **not** emulated.
- The desktop simulator still models the Q2's navigation, fonts and lyric
  display (which may differ from stock firmware).

## Quick start

Requirements: Python 3.10+, Tkinter, LLVM `clang` with MIPS target support,
`ld.lld`, and `readelf` or `llvm-readelf`. The launcher installs Pillow,
Unicorn, Mutagen and fontTools into its isolated Python environment.

Linux / WSL:
```sh
sudo apt install clang lld binutils python3-venv python3-tk
bash run-emulator.sh
bash run-emulator.sh --game pong
bash run-emulator.sh --game blocks
bash run-emulator.sh --self-test
```

Windows 11: install Python with Tcl/Tk and **LLVM for Windows** (clang/ld.lld
on PATH). Use the included `run-emulator.bat` after installing LLVM
`llvm-readelf` or GNU binutils. WSL with WSLg is an alternative.

macOS: install the Homebrew LLVM toolchain (`brew install llvm`), ensure
`clang`, `ld.lld`, `llvm-readelf` are on PATH, and use Python with Tkinter.
Apple's system clang may not contain the MIPS backend.

## Controls

| Action | Keyboard | Click wheel |
|---|---|---|
| Choose game | Up/Down, Enter | Wheel, Centre |
| Pong paddle | Left/Right or A/D | Wheel rotation |
| Blocks move | Left/Right or A/D | Wheel rotation |
| Blocks rotate | Enter | Centre |
| Blocks soft drop | S or Down | Previous side button |
| Blocks hard drop | Shift | Next side button |
| Pause/resume | Space/P | Play/Pause |
| Return/menu | Escape/Backspace | Return |

Use `python3 tools/arcade_emulator.py --snapshot out.png --game blocks`
for a headless device screenshot.

## Launch from existing desktop simulator

On this branch, **Library → Games → Pong / Blocks** launches the Unicorn game
window as a separate child process. The built-in legacy games still require
the device. MIPS compilation happens when a game window starts. A source edit
and relaunch rebuilds the actual game instructions automatically.

## Music playback and UI

`bash run-simulator.sh --sd-card /path/to/Music` now uses host `ffplay` from
FFmpeg to play local MP3/FLAC tracks while the existing simulator keeps its
Now Playing and lyrics UI clock. Install FFmpeg including `ffplay`. Disable
host playback with `--no-audio`, or pass `--ffplay /path/to/ffplay`.
This is **not MIPS audio decoding**. Lyrics, album art, themes, animation and
font behavior are desktop approximations informed by Q2 resources, not a
pixel-exact execution of the firmware's AWTK UI.

## Separate firmware work

The `builtin-pong-tetris` branch contains the actual firmware Games menu,
frame timer, input routing and drawing adapters. It must be built against a
Q2 V1.36 stock ZIP and verified on physical Q2 before distribution.
The emulator branch intentionally avoids mixing its large Python UI changes
into that firmware PR.
