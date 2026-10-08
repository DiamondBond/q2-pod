# Q2 Pod user guide

Controls, settings and media setup. For installation, see the [README](../README.md#install).

## Display settings

**System settings → Display**:

| Setting      | Options                                                         |
| ------------ | --------------------------------------------------------------- |
| **Accent**   | Graphite (default), Crimson (stock red), Tidal, Champagne       |
| **Home**     | Split (list beside the cover) or Full (list only)               |
| **Battery**  | Icon (default), Percent, Icon + Percent                         |
| **Shortcut** | Streaming (default) or Rockbox: what Home's Streaming row opens |
| **Wheel sensitivity** | 50–200% in 10% steps; default 100%, in both builds |

## Battery and library settings

| Where                                  | Setting          | What it does                                                                                                                            |
| -------------------------------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **System settings → Power management** | **Charge limit** | **80%** stops charging at 80% and starts again at 75%, so a Q2 left plugged in isn't held full. Off by default.                         |
| **System settings → Power management** | **Low power**    | Longer battery: the second CPU core sleeps while the screen is off, and the screen-on UI idles when you don't touch it. Off by default. |
| **Audio settings**                     | **Artists**      | **Artist** (default) or **Album Artist**: browse Artists by the Album Artist tag, so guest artists don't split albums.                  |

Charge limit applies while the Q2 is on; charging while it's powered off is stock's. Low power never touches the sound, EQ, brightness or radios. Audio settings also has stock's DAC **Filter**.

## iPod UI

- **Home:** a list (Now Playing, Library, Coverflow…) beside the playing track's cover, instead of the carousel.
- **Lists:** four rows per screen, full-width accent bar; **`>`** marks rows that open another list.
- **Status bar:** play state, EQ, time, Bluetooth, Wi-Fi, battery. The Bluetooth codec (AAC, LDAC…) shows briefly on connect.
- **Bluetooth quality:** LDAC HQ is 990 kbps (909 for 44.1 kHz music), LDAC Standard 660 (606), and LDAC Connection (auto) adapts the bit rate to the connection. Rockbox uses the last choice made here.
- **Now Playing:** "3 of 12", large rounded cover beside title, artist and album, and a slim accent progress capsule.
- **Visualizer:** swipe Now Playing to its fourth page: Spectrum, Oscilloscope, VU Meters or Halo. Tap to switch; your choice is kept. It follows what you hear, EQ included.
- **Quick settings:** pull down from the top edge.
- **Page slides:** in from the right, back out on Return.
- **Fast-scroll letter:** spinning a long list shows the letter it sorts under (C for The Cure).
- **Starts on Home.** **Memory playback → Location** restores your queue, paused; **Track** restarts the song. **In-Vehicle mode** starts playing.

## Controls

| Control                   | What it does                                                                                                                                                                                   |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Wheel**                 | One row per tick; spin to speed up. Outside menus it sets volume.                                                                                                                              |
| **Centre button**         | Opens the highlighted item. Double-press turns the screen off (single press on Now Playing).                                                                                                   |
| **Hold Play/Pause**       | Song or local Now Playing track: queue, favourite, playlist, go to album or artist. Album, artist, genre or folder: queue, shuffle, playlist; a Coverflow album: queue, shuffle, go to artist. |
| **Fast Coverflow turn**   | Album/Artist sorts jump one populated initial per tick; Sort and Refresh remain individual stops.                                                                                              |
| **Hold Return** (iPod)    | Opens Now Playing; the next Return goes back.                                                                                                                                                  |
| **Scrub** (iPod)          | On Now Playing, double-press centre, then turn: 5 s per tick. Double-press, Return, touch or wait 3 s to jump.                                                                                 |
| **Pull to search** (iPod) | At the top of Library (Local Songs), pull down until "Release to search" appears.                                                                                                              |

- **List ends:** lists stop at the end; pause, then turn again to wrap.
- **Position memory:** recent folders, albums, searches and menus reopen where you were, until power-off.
- **Artists:** open on Albums, with All Songs one tap away. Browse by the Album Artist tag with **Audio settings → Artists**.
- **Pop-ups** (iPod): the wheel moves between OK and Cancel.
- **Key Tone:** the speaker clicks only when nothing plays and no headphones (3.5/4.4 mm), Bluetooth or USB DAC are connected. iPod: once per row, not per tick.

### Shuffle, repeat and grouping

On **Now Playing**, hold **Play/Pause** for **Shuffle**, **Repeat** and **Group by: Album / Folder**, in both iPod and Stock builds. The wheel and touch select an option; the selected option has a check mark. Changes keep the playing track and its position.

| Shuffle | Traversal of the current queue |
| --- | --- |
| **Off** | Groups in their first appearance order, tracks in group order |
| **All** | Every queued song in random order |
| **Songs** | Groups in order, songs shuffled within each group |
| **Categories** | Groups shuffled, songs in group order |
| **Songs/Categories** | Groups and their songs shuffled |

**Play Single Song**, **Play Category** and **Play All Categories** stop after that song, group or queue. **Repeat Song**, **Repeat Category** and **Repeat All Categories** loop that scope, with a fresh shuffle cycle. Each shuffle cycle visits every eligible occurrence once, including duplicate entries. Manual Next bypasses single-song stop/repeat; category modes stay in the current category. Previous follows playback history (up to 4096 transitions).

Album groups use the album name, ignoring case; untagged songs use their parent folder. Albums play in disc, track, path and CUE-start order. Folder groups use the immediate parent directory and play in path and CUE-start order. **Library → Shuffle → Shuffle Albums / Shuffle Folders** loads all scanned songs and shuffles those groups, which can take a while on a large library. Existing collection Shuffle actions still shuffle all collected songs. **Next album / Previous album** in the hold menu skips the remaining group or returns to the start of the previously played group; folder grouping shows **Next folder / Previous folder**. Choosing a stock play mode clears the advanced options.

Advanced queues, options, traversal and history restore after reboot from `/mnt/data/ringnav-queue`; missing files are skipped. Restored queues keep their Library or Folder playback origin, so Folder Skip applies only to Folder playback; Coverflow albums, Most Played and Shuffle Songs are never folder plays. **Memory playback → Location** restores elapsed time, **Track** starts at the beginning, and **In-Vehicle mode** plays automatically. Invalid snapshots fall back to stock resume. Queues up to 16,384 occurrences can use advanced playback. Long Songs is deferred.

**Wheel sensitivity** changes scrolling and wheel volume, including screen-off volume and video controls. Drag its slider or press centre on its row, turn the wheel, then press centre or Return to finish. A higher percentage needs less wheel travel; volume still changes one step per event. The setting persists as `Q2POD/WHEELSENSITIVITY`.

### Photos, Books and Videos

| Screen    | Wheel                  | Centre                                | Other                                                       |
| --------- | ---------------------- | ------------------------------------- | ----------------------------------------------------------- |
| **Photo** | Previous or next photo | Shows or hides "3 of 40" and the name | **Return** goes back                                        |
| **Book**  | Turns the pages        | Shows or hides progress               | **Return** goes back; books reopen where you left off       |
| **Video** | Volume                 | Toggles seek: 10 s per tick           | **Play/Pause** pauses, previous/next skip, **Return** exits |

Video sound plays on the headphone jack, Bluetooth or a USB DAC. Music stops meanwhile. Decoding is software, so encodes near the screen's 375 × 320 play smoothest.

## Parametric EQ

**Audio settings → Equalizer**:

- **Curve:** the response is drawn above the list as you edit, with a ring on each band.
- **Bands:** Peaking, Low shelf or High shelf; frequency, gain, Q, on/off, channel (both, **L** or **R**).
- **Gain:** -24 to +24 dB on the wheel; picking one turns the band on, so the ten default bands (31 Hz to 16 kHz, Q 1.41) work as a graphic EQ.
- **Frequency and Q:** tap the value (or press centre) to type one, or step with **Raise** / **Lower**.
- **Balance:** L 12.0 dB to R 12.0 dB in 0.5 dB steps; **R 1.0 dB** plays the left 1 dB quieter.
- **Apply changes:** edits and presets take effect only when chosen.
- **PEQ: ON/OFF:** applies at once and persists; the status-bar **EQ** icon follows it.
- **Preamp:** **Auto** cuts just enough that boosts don't clip. Or pick +12 to -24 dB; above Auto, loud boosts can clip.

### Import a preset

1. Copy an AutoEQ / Equalizer APO `.txt` to `/EQ/` on the card. `Channel: L`, `R` and `all` sections work.
2. **Presets → Import from SD /EQ**, then pick the file.
3. Select the saved preset, then **Apply changes** (and **PEQ: ON**).

## microSD card

Media folders go at the card's root, any capitalisation; each adds its **Library** row when present. Caches are safe to delete and rebuild as needed (Coverflow and Photos need 16 MB free).

| Path                       | What it is                                                                    | Made by |
| -------------------------- | ----------------------------------------------------------------------------- | ------- |
| `Podcasts/`, `Audiobooks/` | One folder per show or book; always resume, never count as plays              | You     |
| `Photos/`                  | `.jpg`, `.jpeg`, `.png` (JPEG up to 6 MB, PNG 1 MB); subfolders are albums    | You     |
| `Books/`                   | `.txt`, `.epub` (no DRM); one level of subfolders                             | You     |
| `Videos/`                  | `.mp4`, `.m4v`, `.mkv`, `.avi`, `.mov`, `.mpg`; one level of subfolders       | You     |
| `EQ/`                      | AutoEQ / Equalizer APO presets to [import](#import-a-preset)                  | You     |
| `.scrobble.ini`            | Scrobble accounts (sample below); adds **Upload Scrobbles**                   | You     |
| `.scrobble.pem`            | CA bundle (e.g. [curl's](https://curl.se/ca/cacert.pem)) for verified uploads | You     |
| `.scrobbler.log`           | Every listen, Rockbox format; for Upload Scrobbles or any uploader            | Q2 Pod  |
| `.scrobbler.log.sent`      | Listens already uploaded                                                      | Q2 Pod  |
| `.coverflow/`              | Coverflow artwork cache                                                       | Q2 Pod  |
| `.photos/`                 | Photo thumbnails and screen-size copies                                       | Q2 Pod  |
| `.books/`                  | EPUBs converted to text                                                       | Q2 Pod  |
| `.sldp/`                   | Stock's own cover cache                                                       | Stock   |

### Set up scrobbling

Save a plain-text file named **`.scrobble.ini`** in the microSD card's root (next to `update.tar`, not inside a folder). Keep the leading dot and make sure your editor hasn't added `.txt`.

Copy the entire example for the service you use, including the section heading and field names. Replace only the values after `=` with your own details; do not add quotes. GitHub's purple/red syntax colours are just highlighting, not instructions to remove text.

**Last.fm only — completed example with made-up credentials:**

```ini
[LASTFM]
USER=q2listener
PASSWORD=ExamplePassword123
API_KEY=0123456789abcdef0123456789abcdef
API_SECRET=fedcba9876543210fedcba9876543210
```

Use your Last.fm username and password. Get your own API key and shared secret from [Create API account](https://www.last.fm/api/account/create) (any application name works). These example credentials won't authenticate.

**ListenBrainz only — completed example with a made-up token:**

```ini
[LISTENBRAINZ]
TOKEN=12345678-1234-1234-1234-123456789abc
```

Copy your user token from [ListenBrainz settings](https://listenbrainz.org/settings/). The example token won't authenticate.

To upload to both services, put both completed sections in the same file, separated by a blank line. Otherwise leave out the entire unused section: a placeholder token still counts as an account, and its failures stop every upload. The file contains plain-text credentials, so keep the card to yourself.

**Album artist instead of artist (optional):** if your Artist tags carry guests ("Artist feat. Guest") and you'd rather scrobble the album's artist, add this section. Songs without an Album Artist tag still scrobble their Artist. A compilation tagged "Various Artists" scrobbles as that, so leave this out if you have those.

```ini
[SCROBBLE]
ALBUM_ARTIST=1
```

It applies to songs you listen to from then on; listens already in `.scrobbler.log` keep their artist.

Safely eject the card, put it in the Q2 and reopen **Library**. **Upload Scrobbles** appears just above **Update Local Music** when a ListenBrainz token or all four Last.fm fields are present. Connect to Wi-Fi, then select **Upload Scrobbles**. If the row is missing, check the filename, section headings and required fields first.

V9.5 includes the certificates needed for verified TLS uploads; no `.scrobble.pem` file is needed on the card. A certificate or storage failure keeps pending listens. Uploads need listens in `.scrobbler.log`: play a tagged song for at least half its length or four minutes, whichever comes first. Set the Q2's date and time correctly before listening.

Settings, play counts, resume points and book pages live on the Q2 itself (`/mnt/data`), not the card.

## Coverflow

- Run **Update Local Music** first.
- **First open** prepares artwork once; **Cancel** keeps progress. Later opens add only new albums; **Refresh library**, the last card, rebuilds everything.
- **Sort**, the card before it: press to switch between **Album**, **Artist** (then year), **Recently Added** and **Most Played**. The choice is kept.
- **Artwork:** `cover.jpg`, `folder.jpg`, then embedded art; otherwise a placeholder.

