# Q2 Pod: Wheel Navigation, Parametric EQ & Coverflow

<p align="center">
  <a href="https://youtu.be/C5x05EwsPGI" title="Watch the Q2 Pod demo on YouTube">
    <img src="assets/banner.png" alt="Q2 Pod: the iPod firmware mod for the Shanling Q2" width="100%">
  </a>
</p>

A firmware mod that restyles the **Shanling Q2** after an iPod classic. It includes:

- **Wheel navigation:** scroll through menus and music, press the centre button to select, and move quickly through long lists with acceleration and position memory.
- **Parametric EQ:** up to 30 peaking and shelf bands, per channel if needed, or import **AutoEQ / Equalizer APO** presets from the microSD card.
- **Coverflow:** flip through your albums by cover art from Home, then open an album to play or queue its tracks.
- **Bluetooth AAC fix:** no more choppy AAC audio when a headset such as AirPods connects to the Q2 by itself.
- **Clock fix:** the time stays right after a power-off instead of jumping by your time zone.
- **Battery and speed:** less drain with the screen off, a quicker library and long VBR MP3s that start at once and seek exactly.

Touch works as before, and outside supported menus the wheel still controls volume.

[**Download the latest release**](https://github.com/DiamondBond/q2-ringnav/releases/latest) · [Changelog](docs/changelog.md) · [Demo video](https://youtu.be/C5x05EwsPGI)

[Install](#install) · [iPod UI](#ipod-ui) · [Controls](#controls) · [Parametric EQ](#parametric-eq) · [Coverflow](#coverflow)

## Install

Charge the Q2 first, and leave the microSD card in until the update finishes.

1. Download `Q2.Firmware.V*-ipod.zip`. Unzip it and copy `update.tar` to the root of the microSD card.
2. On the Q2, open **System settings → System Update → TF card update** and confirm.
3. After the restart, **About** shows the version, ending in `I`.

**Prefer the stock look?** The Normal build, `Q2.Firmware.V*.zip`, has every feature except the [iPod UI](#ipod-ui); its version ends in `R`.

**Going back to stock:** flash the [official firmware](https://en.shanling.com/download/150) the same way. If the UI won't start, copy the `recovery-update` folder from [Shanling's recovery package](https://drive.google.com/file/d/1aINQfJu6n0JTQ4hOzzD1uSpSj3TS_NJj/view?usp=drive_link) to the card, then hold previous-song while powering on with the centre button.

## iPod UI

- **Home** is a list instead of the carousel, beside the playing track's cover.
- **Lists** are flat, four rows per screen, with a full-width selection bar in the accent colour. **`>`** marks every row that opens another list.
- **Status bar:** play state and EQ on the left, the time in the middle, then Bluetooth, Wi-Fi and the battery. A new Bluetooth codec badge (AAC, LDAC…) shows for a second, then fades into the Bluetooth icon.
- **Now Playing:** "3 of 12" at the top, the cover with the title, artist and album beside it, and a slim progress bar with the time played and the time left. Swipe the cover for lyrics and track info, as before.
- **Quick settings:** pull down from the top edge. Brightness is a slim bar you can tap or drag.
- **Page slides:** lists and settings slide in from the right when opened and back out on Return.
- **Fast-scroll letter:** spinning quickly through a long list shows the selected title's first letter in large type.
- **Starts on Home.** **Memory playback → Location** restores your last queue and song, paused where you left it; **Track** restores the song from its beginning. **In-Vehicle mode** starts playing on Now Playing.

Tidal pages keep their stock layout, and your saved settings are unchanged.

### iPod controls

- **Hold Return:** opens Now Playing without interrupting playback; the next short Return goes back to where you were.
- **Volume:** turning the wheel shows the volume as a white bar, in place of the progress bar on Now Playing and in a small panel elsewhere, without dimming the screen.
- **Scrub:** on Now Playing, press the centre button and turn the wheel to move 5 seconds per tick, more while spinning. Press centre or Return, touch the screen, or wait 3 seconds to jump there.
- **Pull to search:** at the top of Local Songs, pull down until "Release to search" appears, then let go.
- **Pop-ups:** in OK/Cancel prompts, turn the wheel to move between the buttons and press the centre button to pick one.
- **Key Tone:** with Key Tone on, lists click once for each row change instead of on every wheel tick.

### Display settings

**System settings → Display** gains three rows. Centre or tap cycles each, and the choice is kept across restarts:

- **Accent:** Graphite (default), Crimson (the stock red), Tidal or Champagne.
- **Home:** Split (the list beside the playing track's cover) or Full (the list across the screen, no cover).
- **Battery:** Icon (default), Percent, or Icon + Percent (the level inside a horizontal battery).

## Controls

| Control                | What it does                                                                                                                                         |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Wheel**              | Moves one row or icon per tick; keep spinning in long lists to speed up. iPod lists ignore a stray second tick, so a one-row turn doesn't overshoot. |
| **Centre button**      | Opens the highlighted item. Double-press to turn the screen off.                                                                                     |
| **Hold Play/Pause**    | On a song, album or folder in the local lists, opens **Play next** / **Add to queue** without interrupting playback. Return closes it.               |
| **Touch**              | Works as normal, and hides the selection until you use the wheel or buttons again.                                                                   |
| **Hold centre button** | Forces the player off if it freezes or won't finish booting.                                                                                         |

- **List ends:** in the local folder and music lists, the list stops at the end while you keep turning. Pause briefly, then turn again to wrap around.
- **Position memory:** going back to a folder, album, search or menu you visited recently restores your place, until power-off.
- **Artists:** an artist opens on Albums, with All Songs one tap away.

A short Play/Pause press and long-press power are unchanged. More in [iPod controls](#ipod-controls).

## Parametric EQ

**Audio settings → Equalizer** opens the editor:

```text
Apply changes
PEQ: OFF
Preamp -3.0 dB
Balance: Centre
Presets
1 ON PK 1000Hz -2.0dB Q1.00
… a row per band, plus a spare to add the next (up to 30)
```

- **Bands:** type (**Peaking**, **Low shelf**, **High shelf**), frequency, gain, Q, on/off, and **Channels**: both, left or right (**ON L** / **ON R** in the list). **Return** steps back.
- **Balance:** fixes a left/right level mismatch by turning one side down: **R 1.0 dB** plays the left 1 dB quieter. The row opens a list from **L 12.0 dB** through **Centre** to **R 12.0 dB** in 0.5 dB steps, starting on the current value; pick one.
- **Apply changes:** edits and loaded presets take effect only when you choose it.
- **PEQ: ON/OFF:** switches at once and is kept across restarts; the status-bar **EQ** icon follows it.
- **Preamp:** read-only; editing a band resets it to just enough cut that boosts don't clip.

### Import a preset

1. Copy an AutoEQ / Equalizer APO `.txt` preset to an `EQ` folder on the microSD card, e.g. `/EQ/My headphones.txt`. `Channel: L`, `R` and `all` sections apply their filters and preamp to that side.
2. **Presets → Import from SD /EQ**, then pick the file. The player saves a copy.
3. Return to **Presets**, select the saved preset, then **Apply changes** (and **PEQ: ON** if it's off).

## Shuffle Songs

**Shuffle Songs**, the first row of Local Music, plays your whole library in shuffle from a random song and sets the play mode to Shuffle.

## Coverflow

**Coverflow** sits after Local Music on Home and flips through your albums by cover art. Run **Update Local Music** first: it shows the albums Local Music already knows.

- **First open:** it prepares artwork once, showing progress. **Cancel** or Return keeps what's done and finishes next time.
- **Browsing:** turn the wheel or swipe between covers; tap a side cover to centre it. Centre or a tap on the middle cover opens the tracks, and picking one plays the album from there. Return goes back to the covers, then Home.
- **Queueing:** hold Play/Pause on a track for **Play next** / **Add to queue**.
- **New music:** the next open prepares only the new albums. **Refresh library**, the last card, rebuilds all artwork.
- **Artwork:** `cover.jpg`, then `folder.jpg` in the album's folder, then art embedded in the first track. Albums without art show a placeholder.

Artwork is cached on the microSD card in `.coverflow`, and needs at least 16 MB free.

## Help and documentation

If a menu behaves strangely, please [open an issue](https://github.com/DiamondBond/q2-ringnav/issues) with the screen you were on and what you did.

- [Internals](docs/internals.md): hooks, selection, position memory, timing and drawing.
- [Building](docs/building.md): building both variants and the MIPS test suite.
- [Releasing](docs/releasing.md): packaging, verifying and publishing.
- [iPod UI](docs/ipod.md): layout audit and each iPod feature.
- [Boot logo](docs/boot-logo.md): replacing the power-on splash.

## License

The code and documentation in this repository are [MIT](LICENSE). The license does not cover Shanling's Q2 firmware: the release images are built from it and it remains Shanling's property. This project is not affiliated with Shanling.
