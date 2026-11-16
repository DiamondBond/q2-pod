# Q2 Pod desktop simulator

Run a 375×320 interactive Q2 UI simulator on a computer. Open Shanling's official Q2
firmware ZIP, the stock `update.tar` inside it, or a Q2 Pod `update.tar` from `tools/build.py`.
Use **Open firmware** to switch packages while keeping the same tracks, or use **Open tracks**
to replace the built-in Vietnamese, Japanese and Spanish sample tags with local MP3 and FLAC files.

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
```

The loaded package supplies the compiled AWTK screen layouts, default styles, artwork and
fonts. The simulator starts at Home, using Shanling's carousel or Q2 Pod's list. From there
open Now Playing, Folders or the Library song list. The status line shows the package version
and, in Now Playing, the selected title and artist faces. A build with `folder-regular.ttf`
can use it for Vietnamese file names and the artist line. The theme selector applies the
checkout's title font preferences and preview colors over the packaged Q2 Pod layout.

- **Open tracks** loads one or more files. You can also pass paths on the command line.
- Arrow keys or the mouse wheel move selection. Click a row or press Enter or Space to open
  it. Esc or Backspace goes back.
- In Now Playing, arrows or the wheel step through tracks, and Enter or Space toggles the
  simulated transport state.
- Switch among Classic Light, Modern and Minimal for Q2 Pod packages or the checkout preview.

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

Add `--firmware PATH` to capture a package in a headless run. Use `--screen home`,
`--screen folder` or `--screen localmusic` to capture another screen. The desktop reads tags with
Mutagen and draws the packaged assets with Pillow. Library and Folders both use the tracks loaded
in the simulator. Hardware audio and the firmware's AWTK event loop require a separate backend.
