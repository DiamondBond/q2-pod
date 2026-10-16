# Spotify (librespot)

Q2 Pod plays Spotify through a librespot port that runs from the microSD card. Spotify Premium is required. After a one-time Spotify Connect pairing from a phone, the Q2 browses and plays on its own over Wi-Fi; the phone can still pick the music over Spotify Connect. Either way the Q2 streams and decodes it itself.

## Port

The port lives in [DiamondBond/q2-librespot](https://github.com/DiamondBond/q2-librespot), a librespot fork. Its branch `shanlingq2` is v0.8.0 plus an IPv4 fallback for discovery, because the Q2's kernel has no IPv6. Its `contrib/shanlingq2/` holds the build, the card launcher and the README.

- **Release:** [q2-librespot's releases](https://github.com/DiamondBond/q2-librespot/releases/latest) ship the prebuilt card files as `q2-librespot-*.zip`, unzipped to the card's root.
- **On the card:** the binary, its launcher and its sink go in the card's `.spotify` folder, with the saved login in `.spotify/cache/`. Q2 Pod starts it; see the [user guide](https://github.com/DiamondBond/q2-pod/releases/latest/download/Q2-Pod-User-Guide.pdf) to install it.
- **Build:** librespot is built **static and soft-float (musl)**, so the firmware's `-mfp64`, NaN-2008 and glibc 2.28 don't matter. The kernel still requires the `nan2008` ELF flag, so the build sets it.
- **Audio:** goes through the stock `aplay` to `plughw:0,0`, the CS43131 headphone DAC, started only while librespot plays (its subprocess backend), so local music can open the DAC whenever Spotify is paused. With Bluetooth or a USB DAC as the output, Q2 Pod names the device and volume in `/tmp/q2-librespot.out` and `aplay.sh` runs Q2 Pod's `q2video -s` there instead, at hciplayer's soft volume ([internals](internals.md#spotify)).

**It plays.** On the device, librespot appears in Spotify Connect, the phone's session authenticates, and audio comes out of the headphones at 160 kbit/s. Soft-float decoding keeps up, with no stutter heard.

## Q2 Pod

**Streaming → Spotify** opens a browser in both builds: Now Playing (the cover, title, artist and album, a moving progress bar and the play state, in Now Playing's layout), Liked Songs, Playlists, Albums, Artists, Search, Queue, Playback Settings (shuffle, repeat), Account (sign out) and Downloaded Tracks. It needs q2-librespot v1.4 or later, Spotify Premium and Wi-Fi for new tracks. Downloaded Tracks replays previously played, completely cached tracks without Wi-Fi. Without a saved login it asks for a one-time pairing: pick Q2 in the Spotify app on a phone on the same Wi-Fi, and the page turns into the menu. With an older add-on, Now Playing still works from the phone and the page asks for the update. Q2 Pod treats librespot as a source of its own playback, as it treats Videos' q2video:

- **Start:** only from the row, once per boot; until then nothing Spotify runs or polls. Idle 30 s after playing with the browser shut, it stops; the row starts it again.
- **Power:** while it plays, standby, auto power-off and the DAC's power-off are held off; the screen still turns off.
- **DAC:** set up as stock's AirPlay receiver sets it (`config_outputchannel`, as a headset insert does, then PCM mode, unmuted and the Q2's volume).
- **Keys:** Play/Pause and the side buttons control Spotify while it was the last thing played; the wheel is the Q2's volume, which is Spotify's.
- **Hand-over:** casting stops local music; starting a local track pauses Spotify first.

The fork adds three options for this: `--status-file`, the player's state, track, position and cover for the page, `--control-socket`, the commands from the keys, and `--browse-socket`, the browser's requests (below). How they fit together is in [internals.md](internals.md#spotify).

## Browsing protocol (Q2SPOT/1)

The fork's `--browse-socket /tmp/q2-librespot.browse.sock` serves Q2 Pod's Spotify browser. Older backends lack it; Q2 Pod then keeps the Connect Now Playing page and asks for the add-on to be updated.

The browser integration uses q2-librespot `shanlingq2` (`q2-v1.4`, Q2SPOT/1). Card updates replace `.spotify/librespot`, `.spotify/run` and `.spotify/aplay.sh`; preserve `.spotify/cache` to keep the paired login and complete downloads. Signing out deletes that account's saved audio, keys and artwork.

**Transport.** A Unix stream socket. One request per connection: the client writes the request and shuts down its write side; the backend answers and closes. Requests are at most 8 KiB, responses at most 64 KiB. The client gives up after 15 s.

**Framing.** Text lines ending in `\n`, fields separated by tabs. The first line of a request and of a response is `Q2SPOT/1`. In every field, the bytes `%`, tab, LF and CR are written as `%25`, `%09`, `%0A` and `%0D`; any other byte, UTF-8 included, is literal. A `%` not followed by two hex digits is malformed. Fields are opaque: IDs, URIs and cursors are passed back exactly as received, never rebuilt from displayed text.

Request, after the version line, one line:

    <id>	<op>	<arg>…

`id` is the client's decimal request number, echoed back so a late reply can be dropped. Response, after the version line:

    <id>	<status>	<message>	<cursor>
    <kind>	<uri>	<title>	<subtitle>	<context>	<position>
    …

The header is followed by 0 to 50 rows. `message` is empty on `ok`, and otherwise one line of English for the screen (at most 120 bytes). `cursor`, when not empty, fetches the next page when passed as the op's last argument; it is at most 1 KiB. A page may hold fewer than 50 rows to stay within 64 KiB; its cursor then continues after the last row sent. `title` and `subtitle` are display text, at most 255 bytes each, cut on a character boundary; URIs and cursors are never cut.

Row fields:

- `kind`: `track`, `album`, `artist`, `playlist`, `account`, `setting` or `op`.
- `uri`: the item's Spotify URI (for `setting`, its name; for `op`, an op name).
- `title`, `subtitle`: what to show (a track's subtitle is its artists, an album's its artist, a playlist's its owner).
- `context`, `position`: for a playable track, `play <context> <position> <uri>` (the row's own URI last) starts it in its list, so the next track follows from Spotify's own context (even past the visible page) and a duplicated playlist entry starts at the copy chosen. An empty context means the track plays on its own: `play <uri>`.

Statuses: `ok`; `login` (no saved login: pair from the phone); `offline` (Spotify can't be reached); `premium` (the account isn't Premium); `refused` (Spotify refused the login, 401/403); `unavailable` (the item is gone or can't play here, a stale queue position included); `stale` (search's query hash changed, 412: the add-on needs updating); `throttled` (429: the message says when to retry; until then the backend answers `throttled` without asking Spotify); `unsupported` (unknown op); `bad` (malformed or oversized request); `error` (anything else). A temporary failure never removes the saved login.

Ops (`[cursor]` is optional):

| Op             | Arguments                  | Rows                                                                                  |
| -------------- | -------------------------- | ------------------------------------------------------------------------------------- |
| `caps`         |                            | `op` rows, one per supported op; `message` is the backend's version, e.g. `q2-v1.3`   |
| `account`      |                            | one `account` row: the user's URI, display name, `Premium`; or status `login`         |
| `playlists`    | `[cursor]`                 | the user's `playlist` rows                                                            |
| `playlist`     | `uri [cursor]`             | its `track` rows                                                                      |
| `liked`        | `[cursor]`                 | Liked Songs' `track` rows                                                             |
| `albums`       | `[cursor]`                 | saved `album` rows                                                                    |
| `artists`      | `[cursor]`                 | followed `artist` rows                                                                |
| `album`        | `uri [cursor]`             | its `track` rows                                                                      |
| `artist`       | `uri`                      | its top `track` rows, then its `album` rows                                           |
| `search`       | `category term [cursor]`   | `category` is `tracks`, `albums`, `artists` or `playlists`                            |
| `play`         | `context [position [uri]]` | none: Q2 becomes the active device and plays                                          |
| `queue`        |                            | the next `track` rows, `position` its index in this list                              |
| `skip`         | `position uri`             | none: plays that queue row; `unavailable` if the queue changed                        |
| `enqueue`      | `uri`                      | none: the track is added to the queue                                                 |
| `settings`     |                            | `setting` rows `shuffle` (`on`/`off`) and `repeat` (`off`/`context`/`track`) as title |
| `shuffle`      | `on\|off`                  | none                                                                                  |
| `repeat`       | `off\|context\|track`      | none                                                                                  |
| `signout`      |                            | none: playback stops, the saved login is removed, and the backend waits for pairing   |
| `downloaded`   | `[cursor]`                 | complete cached `track` rows, most recently played first; works without Wi-Fi         |
| `playdownload` | `uri`                      | none: starts that cached track without requesting its stream URL                      |

Example, Liked Songs' first page:

    Q2SPOT/1
    7	liked

    Q2SPOT/1
    7	ok		Cg4IARIK…
    track	spotify:track:4uLU6hMCjMI75M1A2tKUQC	Never Gonna Give You Up	Rick Astley	spotify:user:alice:collection	0
