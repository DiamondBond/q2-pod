# q2-ringnav: Wheel Navigation, 10-Band PEQ & Coverflow

A firmware mod for the **Shanling Q2** that adds three everyday upgrades:

- **Wheel navigation:** scroll through menus and music, press the centre button to select, and move quickly through long lists with acceleration and position memory.
- **Ten-band parametric EQ:** tune your headphones with peaking and shelf filters, frequency, gain, Q and preamp, or import **AutoEQ / Equalizer APO** presets from your microSD card.
- **Coverflow:** flip through your albums by cover art from Home, then open an album to play or queue its tracks.

All three are included in the normal and iPod variants. Touch works as before, and outside supported menus the wheel still controls volume.

[**Download the latest release**](https://github.com/DiamondBond/q2-ringnav/releases/latest) · [Changelog](docs/changelog.md)

[Wheel controls](#controls) · [PEQ editor and preset import](#parametric-eq) · [Coverflow](#coverflow)

## Install

Charge the Q2 first, and leave the microSD card in until the update finishes.

1. Unzip the release ZIP and copy `update.tar` to the root of the microSD card.
2. On the Q2, open **System settings → System Update → TF card update** and confirm.
3. After the restart, **About** shows the version: ending in `R` for normal, `I` for iPod.

**Going back to stock:** flash the [official firmware](https://en.shanling.com/download/150) the same way. If the UI won't start, copy the `recovery-update` folder from [Shanling's recovery package](https://drive.google.com/file/d/1aINQfJu6n0JTQ4hOzzD1uSpSj3TS_NJj/view?usp=drive_link) to the card, then hold previous-song while powering on with the centre button.

## Parametric EQ

Open **Audio settings → Equalizer** for the ten-band PEQ editor. Select a band with the wheel and centre button or touch to change its type, frequency, gain and Q. **Return** steps back through the editor.

Editor overview after loading the example preset below (scroll for all ten bands):

```text
Apply changes
PEQ: OFF
Preamp -3.0 dB
Presets
1 ON PK 1000Hz -2.0dB Q1.00
… bands 2–10
```

Each band supports **Peaking**, **Low shelf** or **High shelf** filters and can be enabled separately. The preamp comes from the preset's `Preamp:` line and is shown read-only. Editing a band on the player resets it to just enough cut to keep the combined response at or below 0 dB, so boosts don't clip.

**PEQ: ON/OFF** switches it immediately, and the status-bar **EQ** icon follows it. It stays on or off across restarts; band edits and loaded presets take effect when you choose **Apply changes**.

### Import a preset

1. Put your AutoEQ / Equalizer APO `.txt` preset in an `EQ` folder at the root of the microSD card, for example `/EQ/My headphones.txt`.
2. Open **Audio settings → Equalizer → Presets → Import from SD /EQ** and select the file. This saves a copy on the player.
3. Press **Return** to go back to **Presets**, then select the saved preset to load it into the editor.
4. Choose **Apply changes**, then switch **PEQ: OFF** to **PEQ: ON** if needed.

For a simple import example, save this as `/EQ/Example.txt`:

```text
Preamp: -3.0 dB
Filter 1: ON PK Fc 1000 Hz Gain -2.0 dB Q 1.00
```

Save your edits with **Presets → Save editor preset**. Remove saved presets with **Presets → Delete a preset**, which asks for confirmation first.

## Coverflow

**Coverflow** sits after Local Music on Home (the third row in iPod) and flips through your library's albums by cover art. It reads the albums Local Music already knows, so run **Update Local Music** first; until then, and while an update is running, it says so.

- **First open:** it prepares artwork once, showing progress; **Cancel** or Return keeps what's done and finishes on the next open. It uses `cover.jpg`, then `folder.jpg` in the album's folder, then art embedded in the first track; albums without art show a placeholder.
- **Browsing:** turn the wheel or swipe to move between covers. Centre or tap opens the album's tracks; choose one to play the album from there. Return goes back to the covers, then Home. Coverflow remembers the last album and each album's highlighted track until power-off, and long names scroll.
- **New music:** after adding albums, the next open prepares only the new ones. **Refresh library**, the last card, rebuilds all artwork.

The artwork cache lives on the microSD card in `.coverflow` (one small JPEG per album; an empty file means the album has no art Coverflow can read), and it is skipped while less than 16 MB is free on the card. Holding Play/Pause on a track opens the same Play next / Add to queue menu as the Local Music lists.

## Variants

**Normal** (`Q2.Firmware.V*.zip`) keeps the stock layout and controls.

**iPod** (`Q2.Firmware.V*-ipod.zip`) makes browsing denser and cleaner:

- Home is an iPod-style menu instead of the carousel: Now Playing, Music, Coverflow, Folders, Streaming, Playback and Settings in one list, with the playing track's cover beside it.
- No primary toolbar, and 72-pixel rows that fit four full entries with stock fonts and artwork.
- Titles use the full row width, leaving room only for the artwork and controls that are showing.
- Flat list rows on every page, without the grey cards. The playing song keeps its icon but its title stays white.
- A full-width graphite selection bar replaces the outline.
- Spinning fast through a long list shows the selected title's first letter in large type over the list, as on an iPod.
- A `>` marks every row that opens another list: Home and playlists get one to match the rows that already show it (folders, Music categories, artists, genres and albums).
- A graphite status bar shows the play state, the page title in the middle, then the EQ, Bluetooth and Wi-Fi icons and the battery. Settings and Streaming drop their toolbar too, so each page shows its title once. Volume changes still show the stock volume pop-up.
- Hold Return to open **Now Playing** without interrupting playback; the next short Return goes back to where you were. Holding Return on Now Playing goes Home, as stock.
- Pull down at the top of Local Songs to search.

Other pages, Tidal and dialogs keep their stock layout, and your saved settings are unchanged.

Both variants fix choppy AAC audio when a headset such as AirPods connects to the Q2 by itself.

## Controls

- **Wheel:** moves one row or icon per tick. Keep spinning in long lists to speed up, to eight rows per tick.
- **List ends:** in the local folder and music lists, a turn past the end nudges the selection and the list stops there while you keep turning; pause briefly, then turn again to wrap around.
- **Centre button:** opens the highlighted item. Double-press to turn the screen off.
- **Hold Play/Pause:** on a highlighted song, album or folder in the local lists, opens **Play next** / **Add to queue**. It adds without interrupting what is playing; with shuffle on, Play next is still the next track. Return closes it.
- **Forcing it off:** if the player freezes or won't finish booting, hold the centre button until it switches off.
- **Touch:** works as normal and hides the outline until you use the wheel again. Turning the wheel mid-swipe stops the swipe.
- **Artists:** an artist opens on Albums, with All Songs one tap away. The tabs are translated instead of the stock Chinese labels.
- **Position memory:** going back to a folder, album, search or menu you visited recently restores your place, until power-off.
- **Pull to search (iPod):** at the top of Local Songs, pull down until "Release to search" appears, then let go. Move back up to cancel.

A short Play/Pause press and long-press power are unchanged. Timings and edge cases are in [docs/internals.md](docs/internals.md).

If a menu behaves strangely, please [open an issue](https://github.com/DiamondBond/q2-ringnav/issues) with the screen you were on and what you did.

## Documentation

- [Internals](docs/internals.md): hooks, selection, position memory, timing and drawing.
- [Building](docs/building.md): building both variants, the MIPS test suite and on-device checks.
- [Releasing](docs/releasing.md): packaging, verifying and publishing.
- [iPod variant](docs/ipod.md): layout audit and device checklist.
- [Boot logo](docs/boot-logo.md): replacing the power-on splash.

## License

The code and documentation in this repository are [MIT](LICENSE). The license does not cover Shanling's Q2 firmware: the release images are built from it and it remains Shanling's property. This project is not affiliated with Shanling.
