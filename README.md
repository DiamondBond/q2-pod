# Shanling Q2 Scroll Wheel Navigation

A firmware mod that lets the Shanling Q2's scroll wheel move through menus and the centre button select. Touch works as before, and outside supported menus the wheel still controls volume.

[**Download the latest release**](https://github.com/DiamondBond/q2-ringnav/releases/latest) · [Changelog](docs/changelog.md)

## Install

Charge the Q2 first, and leave the microSD card in until the update finishes.

1. Unzip the release ZIP and copy `update.tar` to the root of the microSD card.
2. On the Q2, open **System settings → System Update → TF card update** and confirm.
3. After the restart, **About** shows the version: ending in `R` for normal, `C` for compact.

**Going back to stock:** flash the [official firmware](https://en.shanling.com/download/150) the same way. If the UI won't start, copy the `recovery-update` folder from [Shanling's recovery package](https://drive.google.com/file/d/1aINQfJu6n0JTQ4hOzzD1uSpSj3TS_NJj/view?usp=drive_link) to the card, then hold previous-song while powering on with the centre button.

## Variants

**Normal** (`Q2.Firmware.V*.zip`) keeps the stock layout and controls.

**Compact** (`Q2.Firmware.V*-compact.zip`) makes Folder and Local Songs browsing denser:

- No primary toolbar, and 72-pixel rows that fit four full entries with stock fonts and artwork.
- Titles use the full row width, leaving room only for the artwork and controls that are showing.
- Hold Return to open **Now Playing** without interrupting playback; the next short Return goes back to where you were. Holding Return on Now Playing goes Home, as stock.
- Pull down at the top of Local Songs to search.

Other pages, dialogs and your saved settings are unchanged.

## Controls

- **Wheel:** moves one row or icon per tick. Keep spinning in long lists to speed up, to eight rows per tick.
- **List ends:** in the local folder and music lists, one turn past the end nudges the outline and the next one wraps around.
- **Centre button:** opens the highlighted item. Double-press to turn the screen off.
- **Touch:** works as normal and hides the outline until you use the wheel again. Turning the wheel mid-swipe stops the swipe.
- **Position memory:** going back to a folder, album, search or menu you visited recently restores your place, until power-off.
- **Pull to search (compact):** at the top of Local Songs, pull down until "Release to search" appears, then let go. Move back up to cancel.

Play/Pause and long-press power are unchanged. Timings and edge cases are in [docs/internals.md](docs/internals.md).

If a menu behaves strangely, please [open an issue](https://github.com/DiamondBond/q2-ringnav/issues) with the screen you were on and what you did.

## Documentation

- [Internals](docs/internals.md): hooks, selection, position memory, timing and drawing.
- [Building](docs/building.md): building both variants, the MIPS test suite and on-device checks.
- [Releasing](docs/releasing.md): packaging, verifying and publishing.
- [Compact mode](docs/compact.md): layout audit and device checklist.
- [Boot logo](docs/boot-logo.md): replacing the power-on splash.
