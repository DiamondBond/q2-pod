# Q2 Pod desktop simulator

Run a 375×320 interactive Q2 UI simulator on a computer. Open Shanling's official Q2
firmware ZIP, the stock `update.tar` inside it, or a Q2 Pod `update.tar` from `tools/build.py`.
Use **Open firmware** to switch packages while keeping the same tracks. Use **Mount SD folder**
to browse a local music directory and populate the Library with its MP3 and FLAC files.

## Windows

From PowerShell in the Q2 Pod checkout, using Python 3.12 with Tk support:

```powershell
py -3.12 -m pip install -r tools/requirements-simulator.txt
py -3.12 tools/simulator.py
```

On Linux or macOS, substitute `python3` for `py -3.12`. Some Linux distributions package Tk
separately as `python3-tk`. Opening a firmware package requires an `unsquashfs` executable
with LZO support (`squashfs-tools` on Ubuntu, `squashfs` in Homebrew). On Windows, run the
simulator from Ubuntu/WSL with WSLg for the desktop window, or pass the path to a native
`unsquashfs.exe` with `--unsquashfs`.

## Compare the official and generated firmware

```sh
python3 tools/simulator.py --firmware 'Q2 Firmware V1.36.zip'
python3 tools/simulator.py --firmware /tmp/q2-build/update.tar
python3 tools/simulator.py --firmware /tmp/q2-build/update.tar --sd-card sim-sd
```

The loaded package supplies the compiled AWTK screen layouts, default styles, artwork and
fonts. Home uses Shanling's carousel or Q2 Pod's list. It opens Now Playing, Folders, the
Library song list, Cover Flow (Album Wall on stock firmware), and Settings.

- Drag clockwise or counterclockwise anywhere on the wheel ring to move in either direction.
  Click its top for Back, bottom for Play/Pause, sides for Previous/Next, and center to select.
- The mouse wheel and arrow keys move selection. Enter selects, and Esc or Backspace goes back.
  In Now Playing, click the display or press **L** to switch to lyrics and back. Timed lyrics
  come from a UTF-8 or UTF-16 `.lrc` file with the same basename as the track.
- The SD folder is scanned recursively. Folders shows the directory structure containing the
  loaded tracks. Cover Flow groups tracks by album and album artist and opens each album's
  track list. Artwork comes from the tags, a neighboring `cover.jpg`, `folder.jpg` or
  `cover.png`, or the package's placeholder.
- Settings changes the preview's brightness, album sorting, shuffle and repeat. Classic Light,
  Modern and Minimal are available in Display settings with Q2 Pod or in checkout mode.
- Click **Shell color** alongside **Open firmware** and **Mount SD folder** to cycle through Silver, Black, Orange,
  and Champagne Gold. The button shows the current finish. Orange is the default.
  For screenshots, use `--with-device --shell "Champagne Gold"` to choose a finish.
- A build with `folder-regular.ttf` can use it for Vietnamese file names and the artist line.

## Test a font build

Without `--firmware`, the checkout preview builds the branch's fonts with Q2 Pod's existing font generator.
To compare with another build, extract that build's `bold.ttf`, `classic-light.ttf` and
`default.ttf` into a folder, then pass `--fonts-dir PATH`. You can supply just the extracted
stock font with `--stock-font PATH`. Without the stock font, the preview displays a desktop
substitute (the bundled bold face) wherever the device would use the stock face.

Save a screenshot without opening a window:

```powershell
py -3.12 tools/simulator.py "D:/Music/vietnamese-test.mp3" --snapshot now-playing.png
```

Add `--firmware PATH` to capture a package in a headless run. Use `--screen` to choose the
screen and `--with-device` to include the enclosure and wheel. The desktop reads tags with
Mutagen and draws the packaged assets with Pillow. The status bar shows local time and the
preview's playback state, with simulated Wi-Fi and battery indicators. Enter a value from 0 to 100
in **Battery %** and use **Charging** to preview the charging state. Shanling stock uses its
packaged charging icon. Q2 Pod Classic Light uses a bolt inside the battery, while Modern and
Minimal use the firmware's green battery fill. The preview uses the Icon + Percent battery layout.
Playback advances a simulated clock.
Audio output, hardware services and the firmware's AWTK event loop require a separate backend.
