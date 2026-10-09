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
  <a href="https://github.com/DiamondBond/q2-pod/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/DiamondBond/q2-pod?style=flat-square&label=release&color=3D424B"></a>
  <a href="#features"><img alt="Device: Shanling Q2" src="https://img.shields.io/badge/device-Shanling%20Q2-B99AC8?style=flat-square"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-D77868?style=flat-square"></a>
  <a href="https://youtu.be/C5x05EwsPGI"><img alt="Watch on YouTube" src="https://img.shields.io/badge/YouTube-video-FF0000?style=flat-square&logo=youtube&logoColor=white"></a>
  <a href="https://discord.gg/pgsQpXhSQ"><img alt="Join the Discord" src="https://img.shields.io/badge/Discord-join-5865F2?style=flat-square&logo=discord&logoColor=white"></a>
</p>

<p align="center">
  <b><a href="https://github.com/DiamondBond/q2-pod/releases/latest">Download</a></b> ·
  <b><a href="#install">Install</a></b> ·
  <b><a href="docs/guide.md">User guide</a></b> ·
  <b><a href="docs/changelog.md">Changelog</a></b>
</p>

## Features

Made for the **Shanling Q2**, with an iPod classic feel and a few extras:

- **iPod UI:** Home, lists, Now Playing, Coverflow and four visualizers. Choose your accent, Home layout and battery display.
- **Wheel navigation:** faster scrolling, adjustable sensitivity and menus that remember your place.
- **More ways to listen:** favourites, playlists, Most Played, and shuffle by song, album or folder. Hold Play/Pause for track and playback options.
- **Parametric EQ:** up to 30 bands, per-channel adjustments, balance, a live curve and AutoEQ / Equalizer APO preset imports.
- **Beyond music:** videos, photos, books, podcasts and audiobooks. Podcasts, audiobooks and long mixes resume where you left off.
- **Scrobbling:** log listens and upload to Last.fm or ListenBrainz over Wi-Fi.
- **Battery options:** an optional 80% charge limit and Low power mode.

Also fixes choppy AirPods AAC audio, the clock resetting after power-off, screen-off battery drain, slow library browsing, and startup/seeking on long VBR MP3s.

**Prefer the stock look?** Download `Q2.Firmware.V*-stock.zip`: all the same features and fixes, except the iPod UI.

## Install

> [!IMPORTANT]
> Charge the Q2 first, and leave the microSD card in until the update finishes.

1. [Download the latest release](https://github.com/DiamondBond/q2-pod/releases/latest), unzip `Q2.Firmware.V*.zip` and copy `update.tar` to the microSD card's root.
2. On the Q2, open **System settings → System Update → TF card update**.
3. After the restart, **System settings → About** shows FW V1.32 and your **CFW. Version**.

### Restore stock

Flash the [official Shanling firmware](https://en.shanling.com/download/150) the same way. If the UI won't start, copy the `recovery-update` folder from [Shanling's recovery package](https://drive.google.com/file/d/1aINQfJu6n0JTQ4hOzzD1uSpSj3TS_NJj/view?usp=drive_link) to the card, then hold previous-song and power on with the centre button.

### Rockbox alongside Q2 Pod

Unzip [Rockbox's `rockbox.zip`](https://github.com/DiamondBond/q2-rockbox/releases) to the card's root. Rockbox then starts at power-on. **Hold Play/Pause while powering on**, or choose Rockbox's **Boot stock OS**, to use Q2 Pod for that session.

For Bluetooth, connect your headphones in Q2 Pod first, set **System settings → Display → Shortcut** to **Rockbox**, then select Home's Streaming row to launch it.

See the [setup guide](docs/setup.md) for the full walkthrough and [ported themes](https://github.com/DiamondBond/q2-rockbox-themes/releases).

## Everyday use

| Control                                      | Action                                                                                    |
| -------------------------------------------- | ----------------------------------------------------------------------------------------- |
| **Wheel**                                    | Scroll; spin faster to speed up. Outside menus, adjust volume.                            |
| **Centre**                                   | Open the selected item. Double-press to turn the screen off; single press on Now Playing. |
| **Hold Play/Pause**                          | Open track, queue, playlist and shuffle/repeat options.                                   |
| **Hold Return** (iPod UI)                    | Jump to Now Playing; Return takes you back.                                               |
| **Double-press centre, then turn** (iPod UI) | Scrub on Now Playing, 5 seconds per tick.                                                 |
| **Pull down from the top edge** (iPod UI)    | Open quick settings.                                                                      |

Run **Library → Update Local Music** after adding music; it adds up to 65,000 songs. Coverflow prepares artwork on its first open; cancelling keeps its progress.

- **Personalise:** **System settings → Display** for accent, Home layout, battery display, shortcut and wheel sensitivity.
- **Save battery:** **System settings → Power management** for Charge limit and Low power. Both are off by default; charge limit applies while the Q2 is on.
- **Browse by Album Artist:** **Audio settings → Artists** keeps guest artists from splitting albums.
- **Use EQ:** **Audio settings → Equalizer**. Select **Apply changes** after editing or choosing a preset, and turn **PEQ: ON**. Import preset `.txt` files from the card's `EQ/` folder.

The [user guide](docs/guide.md) covers [all controls](docs/guide.md#controls), [shuffle and repeat](docs/guide.md#shuffle-repeat-and-grouping), [resume behaviour](docs/guide.md#ipod-ui), [EQ](docs/guide.md#parametric-eq) and [Coverflow](docs/guide.md#coverflow).

## Set up your card

Put these folders at the microSD card's root; each adds a Library entry when present:

| Folder                     | Contents                                                             |
| -------------------------- | -------------------------------------------------------------------- |
| `Podcasts/`, `Audiobooks/` | One folder per show or book; always resume and don't count as plays. |
| `Photos/`                  | JPG or PNG; subfolders become albums.                                |
| `Books/`                   | TXT or EPUB without DRM.                                             |
| `Videos/`                  | MP4, M4V, MKV, AVI, MOV or MPG.                                      |
| `EQ/`                      | AutoEQ / Equalizer APO `.txt` presets.                               |

For format limits and cache details, see [microSD card](docs/guide.md#microsd-card). Settings, play counts and resume points live on the Q2, so they stay with the device.

**Want scrobbling?** Add your account details to `.scrobble.ini` at the card's root, then connect to Wi-Fi and choose **Library → Upload Scrobbles**. Follow the [scrobbling setup](docs/guide.md#set-up-scrobbling) for the exact file format and credentials. Set the Q2's date and time before listening; listens are saved in `.scrobbler.log`.

## Documentation

- [User guide](docs/guide.md) — settings, controls, playback, media and scrobbling
- [Setup](docs/setup.md) — Q2 Pod, Rockbox and themes on a fresh Q2
- [Changelog](docs/changelog.md) — what's changed in each release
- [Building](docs/building.md) — both firmware variants and the MIPS test suite
- [iPod UI](docs/ipod.md) · [Internals](docs/internals.md) · [Boot](docs/boot.md) · [Releasing](docs/releasing.md)

## Contributing

Found a bug? [Open an issue](https://github.com/DiamondBond/q2-pod/issues) with the screen and steps to reproduce it. To build it yourself, see [Building](docs/building.md).

## License

[MIT](LICENSE) for this repository's code and docs. The Shanling firmware used in release images remains Shanling's. Not affiliated with Shanling.
