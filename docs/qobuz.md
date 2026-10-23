# Qobuz (q2-qobuz)

Spec. Q2 Pod plays Qobuz through `q2-qobuz`, a daemon that runs from the microSD card as librespot does ([librespot.md](librespot.md)). A paid Qobuz streaming plan is required. The Q2 browses, downloads and plays on its own over Wi-Fi, in hi-res up to 24-bit 192 kHz. Every track is downloaded whole to the card while it plays, and a cached track plays again without Wi-Fi.

Q2 Pod's side reuses Spotify's: the same browser (Q2SPOT/1), the same status file, control socket and sink. The parts that are new are the daemon, the sink's hi-res formats and a second source in `patch/spotify.c`.

## Daemon

The daemon lives in its own repository, `DiamondBond/q2-qobuz`. It is written in Rust (`rustls` with the webpki roots, `serde_json`), built **static and soft-float (musl)** with librespot's toolchain and the `nan2008` ELF flag.

- **Release:** `q2-qobuz-*.zip`, unzipped to the card's root.
- **On the card:** `.qobuz/` holds `q2-qobuz`, its launcher `run`, the app credentials `app`, the saved login `token`, the cache size `.cache-size` and the audio `cache/`.
- **Launcher:** `run` works like Spotify's. It runs a restart loop (5 s, doubling to a minute) and leaves the loop's pid in `/tmp/q2-qobuz`, so a second `run` exits. It passes `--cache-size-limit` from `.cache-size` (`2048M`, or `2G` when the file is missing or malformed). It also passes `--status-file /tmp/q2-qobuz.state`, `--control-socket /tmp/q2-qobuz.sock`, `--browse-socket /tmp/q2-qobuz.browse.sock` and `--out-file /tmp/q2-qobuz.out`.
- **Decoding:** stock `/usr/bin/ffmpeg` (4.2) decodes FLAC. The daemon decodes nothing itself.

## Qobuz API

Qobuz has no public API. q2-qobuz uses the web player's, as other third-party players do. Requests go to `https://www.qobuz.com/api.json/0.2/` with `X-App-Id`, and once logged in, `X-User-Auth-Token`.

**App credentials.** On the first start, and again whenever Qobuz answers an invalid app id, the daemon fetches `play.qobuz.com/login`. From the page's bundle it takes the `app_id` and the candidate secrets, which are the seeds joined with their timezone's info and extras, base64-decoded. It keeps the first secret that signs a `track/getFileUrl` request Qobuz accepts. The id and secret are written to `.qobuz/app`, one per line (a `.tmp`, renamed). An `app` file the user writes by hand is used as it is.

**Login.** The user puts `.qobuz/login` on the card from a computer: the email on the first line, the password on the second. The daemon calls `user/login` (`email`, `password` as its MD5 in hex) and saves `user_auth_token` and the user id to `.qobuz/token` (a `.tmp`, renamed). It then **deletes `login`**, so the password does not stay on the card. A 401 later removes `token`, and the browser asks for `login` again. Network errors, 5xx responses and 429s never remove it.

**Subscription.** An account whose `getFileUrl` answers only 30-second samples (`sample: true`) is `premium`: "Qobuz streaming needs a paid plan".

**Calls.**

| Use               | Endpoint                                                           |
| ----------------- | ------------------------------------------------------------------ |
| Account           | `user/get`                                                         |
| Favourite tracks  | `favorite/getUserFavorites?type=tracks`                            |
| Favourite albums  | `favorite/getUserFavorites?type=albums`                            |
| Favourite artists | `favorite/getUserFavorites?type=artists`                           |
| Playlists         | `playlist/getUserPlaylists`                                        |
| A playlist        | `playlist/get?extra=tracks`                                        |
| An album          | `album/get`                                                        |
| An artist         | `artist/get?extra=albums`                                          |
| Search            | `track/search`, `album/search`, `artist/search`, `playlist/search` |
| Stream URL        | `track/getFileUrl`                                                 |

**Stream URL.** `track/getFileUrl` takes `track_id`, `format_id`, `intent=stream`, `request_ts` (Unix seconds) and `request_sig`, which is the MD5 of `trackgetFileUrlformat_id<f>intentstreamtrack_id<id><ts><secret>`. The format ids are 6 (FLAC 16-bit 44.1 kHz), 7 (FLAC 24-bit up to 96 kHz) and 27 (FLAC 24-bit up to 192 kHz). The answer gives `url`, `format_id`, `bit_depth` and `sampling_rate`. These can be lower than asked for when an album has no hi-res master, and the cache and status file name what was given. The URL expires, so it is fetched again for each download or resume and never stored.

## Quality

The **Quality** setting is `cd` (6), `hires96` (7) or `hires192` (27), and `hires192` is the default. It is saved in `.qobuz/quality`. A track already cached in any format plays from the card. A new download asks for the setting's format.

## Cache

Downloading is how every track plays, so hi-res survives the Q2's Wi-Fi.

- **Names:** `.qobuz/cache/<id>-<format_id> <artist> - <title>.flac`, labelled as Tidal's cache is (`tidal_name`'s rules: FAT's reserved characters become `_`, and a long label is cut at a whole UTF-8 character). A track is found by its `<id>-` prefix, and the highest format present wins.
- **Download:** one at a time, with a single HTTP GET written to `<name>.tmp`. A dropped connection resumes with `Range` after a fresh `getFileUrl`, up to 5 tries. A finished file is flushed, synced and renamed. Once the current track is complete, the next one in the queue downloads. Leftover `.tmp` files are removed at start. No download starts with less than 16 MB free on the card.
- **Eviction:** after each download, the oldest files by mtime are removed until the cache fits its cap. The track playing and the one downloading are never removed. Playing a cached track touches its mtime.
- **Size:** at 24-bit 192 kHz a track is about 100-300 MB, so the 2 GB default holds about ten. Streaming → Configuration's **Qobuz Cache** row sets 512 MB to 8 GB, as Tidal's and Spotify's rows do.

## Playback

**Decode.** For each track the daemon runs ffmpeg with `-loglevel error`, `-ss POSITION` when resuming or seeking, then `-i INPUT -vn -ac 2 -f FMT -ar RATE pipe:1`:

- `INPUT` is the cached file's path once it is complete. While it is still downloading, it is `pipe:0`, and the daemon follows the `.tmp` file into ffmpeg's stdin: it waits at the end of the file until the download grows it, and ends at the download's end. Playback starts once 5 s of audio, by the stream's bitrate, has been written, or the whole file.
- On the headphone DAC and USB DACs, `FMT` and `RATE` are the track's own: `s16le` for 16-bit, `s32le` for 24-bit (left-justified), at its sampling rate. On Bluetooth (`plug:bluealsa`), the output is `s16le` at 44100 for the 44.1 kHz family and 48000 otherwise.

**Sink.** ffmpeg's output goes to `/usr/bin/q2video -s DEVICE VOLUME RATE BITS` (below). The device and volume come from `/tmp/q2-qobuz.out`, which Q2 Pod writes as it writes `SPOT_OUT`. Without the file, the device is the headphone DAC, `plughw:0,0`, and the volume is `h`. One sink stays open across tracks with the same rate and bits, so those tracks play gaplessly. A change of format closes it and opens a new one. As with librespot, the sink is killed on pause and stop, so local music can take the PCM.

**Pause and seek.** Pause remembers the position, then kills ffmpeg and the sink. Play and seek start ffmpeg again at the position (`-ss`). A seek past the downloaded part waits for the download to reach it.

**Queue.** The daemon owns the queue. `play <context> <position> <uri>` loads the context's tracks (an album, a playlist, the favourite tracks or an artist's top tracks, at most 2000) and starts at the position. `shuffle` and `repeat` work on that list, and `enqueue` inserts after the current track. At the end, playback stops unless `repeat` is `context`.

## Interfaces

All three follow librespot's contract ([internals](internals.md#spotify)), with the paths above.

- **Status file** `/tmp/q2-qobuz.state`, rewritten whole: `state=` (`none` only when there is no `token`), `track=` (the Qobuz track id), `title=`, `artist=`, `album=`, `duration=`, `position=`, `at=` and `cover=1` once `/tmp/q2-qobuz.state.jpg` holds the album's `image.small` (230 px). There is one more line, `quality=`, as display text: `24-bit 96 kHz`, `16-bit 44.1 kHz`.
- **Control socket** `/tmp/q2-qobuz.sock`: `p`, `P`, `s`, `n`, `b`, and `S` with a position in ms, as Spotify's.
- **Browse socket** `/tmp/q2-qobuz.browse.sock`: Q2SPOT/1 unchanged, with the same version line, framing, limits and statuses, so the browser's client code is shared. The differences are below.

### Q2SPOT/1 on Qobuz

URIs are `qobuz:track:<id>`, `qobuz:album:<id>`, `qobuz:artist:<id>`, `qobuz:playlist:<id>` and `qobuz:favorites:tracks`. `caps`' message is the daemon's version, e.g. `q2q-v1.0`. Cursors are the API's `offset`, as text.

| Op                                                   | On Qobuz                                                                                                                |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `account`                                            | the user's display name and plan; `login` without `token` (message: "Put your Qobuz login in .qobuz/login on the card") |
| `liked`                                              | favourite tracks, context `qobuz:favorites:tracks`                                                                      |
| `albums`                                             | favourite albums                                                                                                        |
| `artists`                                            | favourite artists                                                                                                       |
| `playlists`, `playlist`, `album`, `artist`, `search` | as Spotify's                                                                                                            |
| `play`, `queue`, `skip`, `enqueue`                   | as Spotify's, on the daemon's queue                                                                                     |
| `settings`                                           | `shuffle`, `repeat` and `quality` (`cd`/`hires96`/`hires192`) as title                                                  |
| `shuffle`, `repeat`                                  | as Spotify's                                                                                                            |
| `quality`                                            | `cd\|hires96\|hires192`: none; applies to the next download                                                             |
| `signout`                                            | playback stops; `token` and the whole `cache/` are removed                                                              |
| `downloaded`                                         | complete cached tracks, most recently played first; works without Wi-Fi                                                 |
| `playdownload`                                       | plays a cached track without asking Qobuz                                                                               |

A track row's subtitle ends in ` · Hi-Res` when its `maximum_bit_depth` is 24.

## Q2 Pod

**Source.** `patch/spotify.c`'s source becomes a table of two, Spotify and Qobuz, each with a title, an icon, the launcher, the pid file, the four paths above and its own state (`sp` per source). `spot_poll`, `spot_take`, `spot_yield`, `spot_media`, `spot_output`, `spot_stop`, the idle stop and the power holds run per source. Only one source is active at a time: one source's `spot_take` first yields the other, and radio, through `spot_yield`/`radio_stop`. `media_owner` and the keys follow the active source.

**Row.** Streaming gets a **Qobuz** row after Spotify, `assets/icons/stream_qobuz.png` (52 px palette PNG with `list_tidal`'s inode metadata, resized on iPod as the other Streaming icons). It opens the shared browser with Qobuz's source. Without `.qobuz/q2-qobuz` on the card, the page says so and nothing starts.

**Browser.** `spotbrowse_page` takes the source and shows its title. Its menu gains Quality under Playback Settings when `caps` lists `quality`. The Now Playing page shows `quality=` in a fourth line under the album (16 px `#AAAAAA`), and the line is left out when empty, so Spotify's page doesn't change.

**Sink.** `q2video -s DEVICE VOLUME [RATE BITS]`. Without the last two, it is 44100 and 16 as before, so librespot's `aplay.sh` doesn't change. `sound_open` takes the format: `SND_PCM_FORMAT_S16_LE` (2) or `SND_PCM_FORMAT_S32_LE` (10). The writer applies `au.gain` to 32-bit samples in 64-bit arithmetic. At 65536 (the headphone DAC, `h`), the writer leaves the samples alone, so the DAC gets them bit-perfect at the hardware volume.

**Configuration.** Streaming → Configuration gets **Qobuz Cache** (`.qobuz/.cache-size`, the same five sizes, read with `state_read`, written with `blob_io`). **Stop Streaming Services** also stops Qobuz (`SPOT_KILL` with Qobuz's pid file and `killall -9 q2-qobuz ffmpeg q2video`). Home's Rockbox row kills it as it kills librespot.

**Checks.** `test/peq.py` (host build): the sink's 32-bit gain and bit-perfect pass-through. `test/patch.py`: the Qobuz row and its icon, the page without the daemon, the source table's hand-over both ways (Spotify ↔ Qobuz, radio → Qobuz), the out file per source, the fourth line present and absent, Qobuz Cache, and Stop Streaming Services stopping it. The daemon's repository has its own tests: the request signature, the bundle's secret extraction against a saved bundle, the cache names, eviction, the follow read, and the Q2SPOT/1 replies.

## Saved collection downloads

Follow the [shared download UX/protocol contract](downloads.md), including its Qobuz mapping, capability negotiation, ordered manifests, protected storage and conformance scenarios. This extends the existing integration; it does not claim q2-qobuz already implements these collection controls.
