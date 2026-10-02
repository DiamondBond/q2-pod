<p align="center">
  <a href="https://youtu.be/C5x05EwsPGI" title="Watch the Q2 Pod video on YouTube">
    <img src="assets/banner.png" alt="Q2 Pod: the iPod firmware mod for the Shanling Q2" width="100%">
  </a>
</p>

<p align="center">
  An iPod classic style firmware mod for the Shanling Q2.<br>
  Wheel navigation, parametric EQ and Coverflow, built on the stock firmware.
</p>

<p align="center">
  <a href="https://github.com/DiamondBond/q2-ringnav/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/DiamondBond/q2-ringnav?style=flat-square&label=release&color=3D424B"></a>
  <a href="#features"><img alt="Device: Shanling Q2" src="https://img.shields.io/badge/device-Shanling%20Q2-B99AC8?style=flat-square"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-D77868?style=flat-square"></a>
  <a href="https://youtu.be/C5x05EwsPGI"><img alt="Watch on YouTube" src="https://img.shields.io/badge/YouTube-video-FF0000?style=flat-square&logo=youtube&logoColor=white"></a>
</p>

<p align="center">
  <b><a href="https://github.com/DiamondBond/q2-ringnav/releases/latest">Download</a></b> ·
  <b><a href="#install">Install</a></b> ·
  <b><a href="docs/changelog.md">Changelog</a></b> ·
  <b><a href="#documentation">Docs</a></b>
  <br>
  <a href="#display-settings">Display</a> |
  <a href="#ipod-ui">iPod UI</a> |
  <a href="#controls">Controls</a> |
  <a href="#parametric-eq">Parametric EQ</a> |
  <a href="#coverflow">Coverflow</a>
</p>

## Features

| For listening                                                 | Under the hood                                                                    |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Accent, Home layout and battery style options                 | Bluetooth AAC fix: no choppy audio when AirPods and similar headsets auto-connect |
| iPod classic style lists, Home and Now Playing                | Clock keeps the right time after power-off                                        |
| Wheel navigation with acceleration and position memory        | Less battery drain with the screen off                                            |
| Play next / Add to queue, Podcasts, Audiobooks, Photos, Books | Faster library browsing                                                           |
| Shuffle Songs, Most Played and scrobbling over Wi-Fi          | Long VBR MP3s start at once and seek accurately                                   |
| Parametric EQ: up to 30 bands, per channel, with balance      | Long tracks (mixes, audiobooks, podcasts) resume where you left them              |

### Podcasts and audiobooks

Put shows in a `Podcasts` folder and books in an `Audiobooks` folder at the root of the microSD card, one subfolder per show or book. **Local Music → Podcasts** and **Audiobooks** then appear at the end of the list and open those folders. An episode or chapter plays on through its folder in the order the folder lists them, always resumes where you left it, whatever its length, and never counts as a play or scrobble. Playback speed is stock's own, in Now Playing's menu.

### Photos

Put photos (`.jpg`, `.jpeg`, `.png`) in a `Photos` folder at the root of the microSD card; each subfolder is an album. **Local Music → Photos** lists **All Photos** and the albums, then shows a grid of thumbnails. **Centre** opens a photo full screen; the **wheel** moves to the previous or next one, **Centre** shows or hides "3 of 40" and the file name, and **Return** goes back. Photos are shown upright from their camera orientation, and music keeps playing.

Thumbnails and screen-size copies are made in the background the first time an album opens and cached in `.photos` on the card (16 MB free needed). A photo that won't open stays grey; JPEGs over 6 MB and PNGs over 1 MB are too big for the stock decoder. Up to 500 photos per album are shown.

### Books

Put ebooks (`.txt` and `.epub`) in a `Books` folder at the root of the microSD card, in subfolders if you like. **Local Music → Books** lists them by file name; **Centre** opens one. The **wheel** turns the pages, **Centre** shows or hides how far in you are, and **Return** goes back to the list. Each book reopens at the page you left. An EPUB is turned into text the first time it opens ("Preparing…") and kept in `.books` on the card; pictures are left out. Books with DRM can't be opened.

### Play counts and scrobbling

A song counts as played once you've heard half of it (or 4 minutes). **Local Music → Most Played** plays your 25 most played songs, most played first.

Each of those plays is also logged to `.scrobbler.log` at the root of the microSD card, in the same format Rockbox uses. Upload it to Last.fm or ListenBrainz with any `.scrobbler.log` uploader, such as [Open Scrobbler](https://openscrobbler.com/), [Universal Scrobbler](https://universalscrobbler.com/) or [rb-scrobbler](https://github.com/jeselnik/rb-scrobbler). Songs without an artist tag are skipped.

To upload from the Q2 itself, put a `.scrobble.ini` at the root of the card with a ListenBrainz token (from [your settings](https://listenbrainz.org/settings/)), a Last.fm account, or both:

```ini
[LISTENBRAINZ]
TOKEN=your-listenbrainz-user-token

[LASTFM]
USER=your-username
PASSWORD=your-password
API_KEY=your-api-key
API_SECRET=your-shared-secret
```

Last.fm needs your own API account ([create one](https://www.last.fm/api/account/create); any name works) for the key and secret. **Local Music → Upload Scrobbles** then appears under Most Played. On Wi-Fi it sends the log in the background, 50 plays at a time, and moves what was sent to `.scrobbler.log.sent`; plays that could not be sent stay in the log for next time. Last.fm ignores plays older than 14 days. There is no login screen on the device, as typing a password on the wheel's keyboard is slow; the file is plain text, so keep the card to yourself. The Q2 has no certificate store, so like Shanling's own Tidal and Baidu features the upload does not check the server's certificate, unless you add a PEM CA bundle as `.scrobble.pem` beside the file (for example [curl's](https://curl.se/ca/cacert.pem)).

## Install

> [!IMPORTANT]
> Charge the Q2 first, and leave the microSD card in until the update finishes.

1. [Download](https://github.com/DiamondBond/q2-ringnav/releases/latest) `Q2.Firmware.V*.zip`, unzip it and copy `update.tar` to the root of the microSD card.
2. On the Q2: **System settings → System Update → TF card update**.

**Prefer the stock look?** The Stock build, `Q2.Firmware.V*-stock.zip`, has everything except the [iPod UI](#ipod-ui).

### Restore stock

Flash the [official firmware](https://en.shanling.com/download/150) the same way. If the UI won't start, copy the `recovery-update` folder from [Shanling's recovery package](https://drive.google.com/file/d/1aINQfJu6n0JTQ4hOzzD1uSpSj3TS_NJj/view?usp=drive_link) to the card, then hold previous-song while powering on with the centre button.

## Display settings

**System settings → Display**:

| Setting     | Options                                                                            |
| ----------- | ---------------------------------------------------------------------------------- |
| **Accent**  | Graphite (default), Crimson (stock red), Tidal, Champagne, Custom (any hex colour) |
| **Home**    | Split (list beside the cover) or Full (list only)                                  |
| **Battery** | Icon (default), Percent, Icon + Percent                                            |

## iPod UI

- **Home:** a list beside the playing track's cover, instead of the carousel.
- **Lists:** flat, four rows per screen, full-width accent selection bar; **`>`** marks rows that open another list.
- **Status bar:** play state and EQ, the time, then Bluetooth, Wi-Fi and battery. The Bluetooth codec (AAC, LDAC…) shows briefly on connect.
- **Now Playing:** "3 of 12", large rounded cover art beside a bigger title over grey artist and album, and a slim accent capsule with elapsed and remaining time.
- **Quick settings:** pull down from the top edge.
- **Page slides:** pages slide in from the right and back out on Return.
- **Fast-scroll letter:** spinning through a long list shows the current title's first letter.
- **Starts on Home.** **Memory playback → Location** restores your queue paused where you left it; **Track** restarts the song. **In-Vehicle mode** starts playing.

## Controls

| Control                   | What it does                                                                                                                                     |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Wheel**                 | One row per tick; keep spinning to speed up. Outside menus it sets volume (iPod: in place of the progress bar on Now Playing, or a small panel). |
| **Centre button**         | Opens the highlighted item. Double-press turns the screen off (single press on Now Playing).                                                     |
| **Hold Play/Pause**       | On a song, album or folder: **Play next** / **Add to queue**.                                                                                    |
| **Hold Return** (iPod)    | Opens Now Playing; the next Return goes back.                                                                                                    |
| **Scrub** (iPod)          | On Now Playing, double-press centre, then turn 5 seconds per tick. Double-press again, press Return, touch, or wait 3 seconds to jump.           |
| **Pull to search** (iPod) | At the top of Local Songs, pull down until "Release to search" appears.                                                                          |

- **List ends:** local lists stop at the end; pause, then turn again to wrap.
- **Position memory:** returning to a recent folder, album, search or menu restores your place until power-off.
- **Artists:** open on Albums, with All Songs one tap away.
- **Pop-ups** (iPod): the wheel moves between OK and Cancel.
- **Key Tone** (iPod): clicks once per row, not per wheel tick.

## Parametric EQ

**Audio settings → Equalizer**:

- **Bands:** Peaking, Low shelf or High shelf; frequency, gain, Q, on/off, and channel (both, **L** or **R**). Gain is picked with the wheel, -24 to +24 dB, and picking one turns the band on, so the ten default bands (31 Hz to 16 kHz, Q 1.41, one octave wide) work as a 10-band graphic EQ. Frequency and Q open their own menu: tap the value (or press the centre button on it) to type one on the on-screen number keys, or step it with **Raise** / **Lower**.
- **Balance:** L 12.0 dB to R 12.0 dB in 0.5 dB steps; **R 1.0 dB** plays the left 1 dB quieter.
- **Apply changes:** edits and presets take effect only when chosen.
- **PEQ: ON/OFF:** applies at once and persists; the status-bar **EQ** icon follows it.
- **Preamp:** **Auto** sets just enough cut that boosts don't clip and follows band edits. Pick +12 to -24 dB instead to keep a level of your own; above Auto, loud boosts can clip.

### Import a preset

1. Copy an AutoEQ / Equalizer APO `.txt` to `/EQ/` on the microSD card. `Channel: L`, `R` and `all` sections are supported.
2. **Presets → Import from SD /EQ**, then pick the file.
3. Select the saved preset, then **Apply changes** (and **PEQ: ON**).

## Coverflow

- Run **Update Local Music** first.
- **First open** prepares artwork once; **Cancel** keeps progress for next time. Later opens add only new albums; **Refresh library**, the last card, rebuilds everything.
- **Browse** with the wheel.
- **Artwork:** `cover.jpg`, `folder.jpg`, then embedded art; otherwise a placeholder.

> [!NOTE]
> Artwork is cached in `.coverflow` on the microSD card, which needs 16 MB free.

## Documentation

| Document                       | Covers                                                |
| ------------------------------ | ----------------------------------------------------- |
| [Changelog](docs/changelog.md) | Every release                                         |
| [iPod UI](docs/ipod.md)        | Layout audit and iPod features                        |
| [Internals](docs/internals.md) | Hooks, selection, position memory, timing and drawing |
| [Building](docs/building.md)   | Building both variants and the MIPS test suite        |
| [Releasing](docs/releasing.md) | Packaging, verifying and publishing                   |
| [Boot logo](docs/boot-logo.md) | Replacing the power-on splash                         |

## Contributing

Found a bug? [Open an issue](https://github.com/DiamondBond/q2-ringnav/issues) with the screen and steps. To build it yourself, see [Building](docs/building.md).

## License

[MIT](LICENSE), covering this repository's code and docs. Shanling's Q2 firmware, from which the release images are built, remains Shanling's property. Not affiliated with Shanling.
