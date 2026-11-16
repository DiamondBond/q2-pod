# Desktop simulator — quick start

The desktop simulator previews the Q2/Q2 Pod UI on a computer. **This is a Python UI simulator, not a MIPS emulator and not the actual firmware running on a PC.** Some device-only features and settings are not implemented.

## Run in one command (Linux / macOS)

From the repository root:

```sh
bash run-simulator.sh
```

The launcher is invoked through Bash, so no executable permission change is required.

The first launch creates `.venv-simulator/` and installs only its Python dependencies. Later launches reuse them. Python 3.10+ and Tkinter are required; a graphical desktop/display is required to open the window. On Ubuntu/Debian, install missing system packages using:

```sh
sudo apt install python3 python3-venv python3-tk
```

On macOS, use a Python distribution with Tkinter included. If the launcher cannot find that Python, set `PYTHON=/path/to/python3`.

## Windows 11 (double-click or Command Prompt)

Install Python 3.10+ from [python.org](https://www.python.org/downloads/) with **Tcl/Tk** enabled. Double-click `run-simulator.bat` in the repository folder. It creates its own virtual environment, installs dependencies, and opens the simulator. Alternatively, in Command Prompt or PowerShell opened at the repository root:

```cmd
.\run-simulator.bat
```

You can pass CLI options as arguments, for example `run-simulator.bat --sd-card "C:\\Music"`. If Windows opens the Microsoft Store instead of Python, install Python from python.org and ensure the Python launcher or Python executable is available on PATH.

For WSL, use the Linux launcher and make sure GUI applications are supported (for example WSLg).

## Try it with real content

No firmware or audio files are needed for the default demo: `bash run-simulator.sh` opens a checkout preview with sample tracks.

- **Mount music as an SD card:** `bash run-simulator.sh --sd-card "/path/to/music"` or choose **Mount SD folder** in the window. The simulator currently scans MP3 and FLAC files.
- **Preview a firmware package:** `bash run-simulator.sh --firmware "/path/to/update.tar"` or `bash run-simulator.sh --firmware "/path/to/stock-firmware.zip"`. You can also click **Open firmware**.
- **Both together:** `bash run-simulator.sh --firmware "/path/to/update.tar" --sd-card "/path/to/music"`.
- **Save a screenshot without a GUI:** `bash run-simulator.sh --snapshot /tmp/q2.png --screen home --with-device`.
- **All options:** `bash run-simulator.sh --help`.

To load a firmware package, install **squashfs-tools** so `unsquashfs` is on PATH (Ubuntu/Debian: `sudo apt install squashfs-tools`; macOS: `brew install squashfs`). A package must contain the expected Q2 update files. The checkout preview does not require `unsquashfs`.

## Controls

Use the simulated wheel with the mouse, scroll using the mouse wheel or arrow keys, press Enter to select, Escape/Backspace to return, and Space to select or toggle playback. The GUI has controls to change shell color, battery percentage and charging state. Clicking the display on Now Playing switches to lyrics.

## Limitations

This is a visual/interaction model driven by repository code and firmware assets; it does not execute the MIPS firmware. Playback timing, filesystem browsing, many menus and device behavior are approximations or partial implementations. The charging checkbox supplies a simulated battery state; it does not read actual hardware. The simulator does not need the full firmware-build requirements or a physical Q2.

The venv is local to the checkout. Delete `.venv-simulator/` to reset dependencies.
