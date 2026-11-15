# Q2 Pod desktop simulator

Run a 375×320 interactive **Now Playing** preview on a computer. Open local MP3 and FLAC files
or use the built-in Vietnamese, Japanese and Spanish sample tags. The simulator renders the
embedded cover, scrolls long titles and shows which font the title uses.

## Windows

From PowerShell in the Q2 Pod checkout, using Python 3.12 with Tk support:

```powershell
py -3.12 -m pip install -r tools/requirements-simulator.txt
py -3.12 tools/simulator.py
```

On Linux or macOS, substitute `python3` for `py -3.12`. Some Linux distributions package Tk
separately as `python3-tk`.

- **Open tracks** loads one or more files. You can also pass paths on the command line.
- Arrow keys or the mouse wheel over the display switch tracks. Enter or Space toggles the
  simulated transport state. Click the display to return keyboard focus to it.
- Switch among Classic Light, Modern and Minimal using the dropdown.

## Test a font build

The simulator builds the branch's bundled fonts with Q2 Pod's existing font generator.
To compare with another build, extract that build's `bold.ttf`, `classic-light.ttf` and
`default.ttf` into a folder, then pass `--fonts-dir PATH`. You can supply just the extracted
stock font with `--stock-font PATH`. Without the stock font, the preview displays a desktop
substitute (the bundled bold face) wherever the device would use the stock face.

Save a screenshot without opening a window:

```powershell
py -3.12 tools/simulator.py "D:/Music/vietnamese-test.mp3" --snapshot now-playing.png
```

The desktop preview uses Mutagen for tags and Pillow for drawing. It uses Q2 Pod's theme
configuration, layout constants and bundled font generation. Firmware tag decoding, AWTK
rendering, audio playback and other Q2 screens are outside the scope of this first version.
The Play/Pause control changes the displayed state only. The original Shanling firmware is
unnecessary for running the preview.
