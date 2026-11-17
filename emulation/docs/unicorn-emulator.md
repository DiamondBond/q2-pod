# Q2 Pod Unicorn/MIPS game emulator (experimental)

Branch: `unicorn-mips-emulator`, based on `desktop-simulator`.

## What is real

- **Actual little-endian MIPS32r2 game instructions**, compiled from
  `patch/arcade_core.c` using the Q2 firmware's target architecture and
  executed in Unicorn. The host does not reimplement the Pong or Blocks rules.
- The existing desktop simulator's **Q2 chassis graphic and click-wheel
  geometry** (`emulation/simulator_device.py`).
- MIPS test from `emulation/arcade_mips.py`, usable without stock firmware.

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
`ld.lld`, and the Python `pyelftools` package. The launcher installs Pillow,
Unicorn, Mutagen and fontTools into its isolated Python environment.

Linux / WSL:
```sh
sudo apt install clang lld binutils python3-venv python3-tk
bash emulation/run-emulator.sh
bash emulation/run-emulator.sh --game pong
bash emulation/run-emulator.sh --game blocks
bash emulation/run-emulator.sh --self-test
```

Windows 11: install Python with Tcl/Tk and Ubuntu WSL with `clang` and
`ld.lld` (`wsl --exec clang --version` and `wsl --exec ld.lld --version`
from PowerShell). The Windows simulator automatically compiles MIPS in WSL,
then runs Unicorn and Tkinter natively in Windows. No Windows LLVM installation,
MIPS cross compiler on Windows, or `llvm-readelf.exe` is required.
Python `pyelftools` is installed by the launcher.
Run `emulation\run-simulator.bat` or `emulation\run-emulator.bat --game pong`.

For a custom Windows LLVM toolchain that genuinely supports MIPS, set
`Q2_MIPS_COMPILER=windows` to disable the WSL compiler route.

macOS: install the Homebrew LLVM toolchain (`brew install llvm`), ensure
`clang`, `ld.lld` are on PATH, and use Python with Tkinter.
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

Use `python3 emulation/arcade_emulator.py --snapshot out.png --game blocks`
for a headless device screenshot.

## Launch from existing desktop simulator

Open **Library → Games** to play **Pong**, **Blocks**, **Snake**, **Vortex**, **Sudoku**, or **Solitaire**
inside the desktop simulator window. All six run their C rules under Unicorn.
Snake and Vortex use the rules in `patch/games.c`, keep host music playing,
and track best scores for the current session. Pong and Blocks pause host
music on entry. The simulator compiles the MIPS rules when opening a game.

In Sudoku and Solitaire, use the wheel or arrows to move and Enter to select.
Use Space for a new puzzle or deal. Esc cancels a selection or returns to Games.
The desktop starts a fresh puzzle or deal each time you open either game.

The standalone `emulation/run-emulator.sh` / `emulation\run-emulator.bat` game window is also
available for focused game debugging without the music UI. Pass `--game snake`
or `--game vortex` to open either directly.

## Music playback and UI

`bash emulation/run-simulator.sh --sd-card /path/to/Music` now uses host `ffplay` from
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


## Running Buddy from a mounted SD folder

Mount the SD folder containing `.fidget/q2app` and `.fidget/q2-fidget`.
The simulator App Store can install Buddy to that folder. Open **Library → Games → Buddy**.
Click, hold, or drag the ghost, scroll or drag the wheel, press Enter for Centre,
and use Esc for Buddy's menu. Choose **Quit** there to save and return to Games.

The runner executes Buddy's installed static MIPS32 executable in Unicorn. It
models the rotated double-buffered framebuffer, the Q2 input datagrams, the
clock, and Buddy's own card files. State and pet saves go to the mounted
`.fidget` directory, and the optional `buddy.png` is read from there. Guest
syscalls use only these emulated devices and explicitly allowed card paths.
The guest uses Buddy's default popup style. Other card apps, the Q2 Linux
kernel, and device drivers remain outside this runtime.
