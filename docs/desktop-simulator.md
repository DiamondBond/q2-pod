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

## Test the Q2 Pod App Store

1. Use a Q2 Pod `update.tar` or start the launcher without a firmware package to use the checkout preview. The official Shanling firmware has no Q2 Pod App Store.
2. Create a temporary folder and choose **Mount SD folder**. The App Store writes real packages and install records to this folder.
3. On the virtual Q2, open **Settings → System → App Store**. Choose **Check for Updates** to refresh the catalog, or select an app to download and install its latest ZIP from GitHub. File Browser is a small package to try.
4. Press Centre again during the download to cancel. To remove an app, select its **Installed** row twice. A first Rockbox install also asks you to press twice, and Rockbox Themes appears with Rockbox installed.

The simulated Wi-Fi switch under **System → Wireless → Wi-Fi** controls whether the App Store can start online operations. Downloads use the computer's internet connection. Successfully installed packages leave Q2-compatible app folders and records in `.q2/apps`. The desktop simulator never launches the downloaded Q2 executables.

Settings shows the Q2 Pod System and Playback menus and their major subpages. Theme, brightness, wheel sensitivity, playback mode, the Folder Root choice, and Cover Flow's Album and Artist sorts affect the preview. Rows that require Q2 hardware or firmware services report that when selected. Firmware updating, radio pairing, and native app execution require the device.

## Browse the Library

Open **Library** from Home, then scroll to **Artists**, **Albums**, **Songs**, **Genres**, or the other Library categories. The lists use the tags of tracks on the mounted SD folder. **Update Library → Scan music now** picks up changes to that folder. **Playlists → Import** loads `.m3u` files from the folder's `_explaylist_data` directory for the current session.

In Q2 Pod, **Games** is near the bottom of the Library. It lists the four built-in games, then card apps whose `q2app` manifest says `game=1`. Install **Buddy** from the App Store to try this. The game entries are browsable, and running the games requires a Q2. With an official Shanling package loaded, **Local Music** uses the stock categories.
