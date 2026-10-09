# Internet Radio under Streaming, version 9.9 → 1.0

## Context
Streaming currently has only Spotify. The user wants a full Internet Radio, and FM if possible.
**FM isn't possible:** the Q2 has no tuner. The DT only has the axp2101 on i2c; the modules are the DAC, fuel gauge, touch, rtl8733bs and SoC drivers; and stock hciplayer was built with `--disable-radio`. So there is no FM row; the changelog and guide say why.
Versioning resets to **1.0**, and later releases are 1.0.1, 1.0.2 and so on.

Stations come from favourites on the card plus the radio-browser.info directory (the user's choice).

## Design (reuse first)

### Audio: extend q2video, no new binary
`patch/video.c` already runs stock `/usr/bin/ffmpeg` → a pipe → ALSA, and it already handles the DAC ioctls, Bluetooth, USB and soft volume, plus the datagram socket. Add an audio-only mode:
- **Mode:** `q2video -r DEVICE URL [VOLUME]` skips the frame pipe and the fb0 drawing.
- **ffmpeg args:** `-icy 1 -reconnect 1 -reconnect_streamed 1 -i URL -vn` → s16le at 48k.
- **Metadata:** ffmpeg's stderr goes to a pipe. Stock libavformat 4.2 prints `Metadata update for StreamTitle: …` (verified in the rootfs strings), plus `icy-name` and `icy-br` in the input dump. The helper writes `state/title/station/bitrate/at` lines to `/tmp/q2radio.state`, in the same `key=value` format `spot_read`/`field` parse.
- **Retry:** when ffmpeg dies (the network drops), back off and restart up to N times, then `state=error`.
- **HTTPS:** ffmpeg defaults to `tls_verify=0`, so the empty `/etc/ssl/certs` doesn't matter.

### Payload: new `patch/radio.c`, modelled on `patch/spotify.c`
- **Row:** `library_into(view, "stream_radio", radio_open, 0, "Internet Radio")` in `ringnav_stream` (navigation.c:3389). Icon `assets/icons/stream_radio.png`, added in build.py:788 like `stream_spotify.png`.
- **Radio menu:** a `page_list`/`page_row_detail` page (coverflow.c), with a `contexts.inc` entry and a `PAYLOAD_WINDOWS` entry for the wheel. Rows:
  - **Favourites:** `/mnt/mmc/Radio/*.m3u` / `*.pls`. On first open, `favourites.m3u` is seeded with ~6 starter stations.
  - **Top Stations:** `GET https://de1.api.radio-browser.info/m3u/stations/topvote/100?hidebroken=true`. The m3u format means one parser serves both the card files and the directory.
  - **By Country:** `/csv/countries?order=stationcount&reverse=true&limit=60` → `/m3u/stations/bycountrycodeexact/XX?order=votes&reverse=true&limit=100`.
  - **By Genre:** `/csv/tags?order=stationcount&reverse=true&limit=60` → `/m3u/stations/bytagexact/TAG?…`.
  - Fetches run on a pthread with demo's libcurl, as `scrobble.c` does. A "Loading…" caption is shown meanwhile, and "No Wi-Fi" is shown on failure.
- **Station list:** a scrolling list. Centre plays the station. **Hold Centre** appends it to `favourites.m3u`, or removes it when it's already in Favourites, with a `toast()`.
- **Now Playing page:** reuses Spotify's layout helpers (`label`, `spot_paint`'s bar/glyph style, `spot_art`). It shows the station name, the StreamTitle split into artist and title on `" - "`, the codec/bitrate and the elapsed time. The art is the station logo when the fetch succeeds (the `favicon` from the directory, through `thumb()`), otherwise a radio glyph.
- **Keys:** Play/Pause stops or restarts the stream (live, so there is no pause buffer). The side buttons go to the previous/next station in the current list, from any page while radio is active, as `spot_media` does. The wheel is volume, sent as the existing `v` datagram for Bluetooth/USB soft volume. Return goes back.
- **Process and power:** fork/exec plus a `waitpid` poll, as `play_video`/`video_poll` do (books.c:722-767). While playing, use `reset_poweroptions_timer(1,1,0)`, so the screen may turn off, and zero `g_dacoff_time`.
- **Hand-over:** the `mclStartPlayer` hook (navigation.c:3398) quits radio before local music starts. Radio start calls `player_stop()` and pauses Spotify (`spot_send("s")`). Spotify starting kills radio. The Rockbox teardown (navigation.c:4043) kills it too.
- **Resume:** the last station is remembered in `/mnt/mmc/Radio/.last` so the Now Playing row can reopen it. Auto-play at boot is skipped.

### Version 1.0
- **build.py:10:** `VERSION = '1.0'`.
- **Updater tag:** it must stay 5 chars (build.py:740 replaces `V1.32\0` in place). Derive it as `'V' + (VERSION if len==3 else VERSION.replace('.',''))` + `I`/`S`, which gives `V1.0I` now and `V101I` for 1.0.1. Assert 5 chars.
- **Callers that assume `VERSIONS[v] == f'V{VERSION}…'`:** `tools/release.py:44,53`, `test/patch.py:19-20`, `test/build.py:101` and `docs/building.md:37-39`. Point them at `VERSIONS`.
- **Unchanged:** About still shows the full `V1.0.1 iPod`.
- **Changelog:** a new top entry `- **V1.0**:` (versions restart; Internet Radio; no FM, because there's no tuner).

### Docs and tests
- **Docs:** `docs/guide.md` gets `### Internet Radio` (controls table, adding stations, Favourites file format) and a microSD table row. `docs/internals.md` gets `## Internet Radio` (the contract, as with Spotify's).
- **`test/patch.py`:** `stream_page()` now expects 3 rows. Add a `RadioMachine`, copying the `SpotMachine` pattern: state-file parse, keys, hand-over.
- **Host checks:** m3u/pls/csv parser asserts in the `test/peq.py` host build (PEQ_HOST), plus the q2video ffmpeg-stderr metadata parser.

## Execution
1. **Sub-agent A (implementation, worktree):** radio.c, the q2video `-r` mode, build wiring, icon, row, tests, docs.
2. **In parallel, sub-agent B (worktree):** the version change across build/release/tests/docs, plus the changelog. Another session may be editing q2-pod, so check `git status` first and coordinate.
3. Merge, then run `/ponytail:ponytail-review` on the diff. Fix the findings, and a correctness pass too.
4. Leave the result uncommitted for the user to review, unless they ask for a commit.

## Verification
- `python3 tools/build.py 'Q2 Firmware V1.32.zip' --ipod --dev --out $CLAUDE_JOB_DIR/tmp/b-ipod`, and the stock variant too.
- `~/.cache/q2/venv/bin/python test/patch.py <build>`, `test/build.py <build>`, `test/peq.py`, `test/coverflow.py`, `test/release.py`.
- On the host, run the stock ffmpeg flow with a desktop ffmpeg against a real station: `ffmpeg -icy 1 -i URL -f s16le - 2>&1 >/dev/null | grep 'Metadata update'` confirms the parser's input format. `curl` the three radio-browser endpoints to confirm the m3u/csv shapes.
- On the device (user): Wi-Fi on, Streaming → Internet Radio → Top Stations → play, metadata updates, side buttons change station, a local track takes over, Bluetooth output.
