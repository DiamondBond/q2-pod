# 1.3.5 validation

Reviewed the final changes since `a4d0396`, including the playlist series `756f2ca`, `fb28866`, `01da4d1` and `ce7f2e8` together. Rockbox's return crash and Spotify channel balance remain deferred.

## Corrections

- Library Songs' native title sorter uses `toolsQueryDbTableAndSort`, bypassing the earlier music-only query hook. That helper now applies the same scoped policy. Folder loads and stored playlists retain their contents.
- Bluetooth absolute volume previously replaced unequal gains with `100,100`. Software gains now retain their ratio; reconnect and read-back reuse stock's volume calculation.
- Stock startup rejected synthetic wallpaper names before the picker could preserve them. Both wallpaper validation call sites now recognize valid built-ins. Missing images retain stock fallback, and the picker no longer makes repair writes.
- Add Songs search previously rebuilt its edit on text changes while the keyboard could own it. It now confirms the query and detaches the keyboard before rebuilding.
- Shared audio flags previously published their inode before mapping succeeded. A failed mapping could strand consumers on an obsolete inode. Mapping now precedes publication; failed publication releases the mapping.
- Delete's Minimal-theme bitmap was forced grey. Its active glyph keeps white, while the grey glyph retains its colour. Delete and Rename child labels follow the enabled state of their action's ancestors, including decorative disabled labels.

## Features and input

Swap L/R is saved as `Q2POD SWAPLR`, defaults Off, and follows Mono Audio. It runs after EQ/mono in hciplayer and after mono in q2video's common PCM writer. Spotify selects that helper on the headphone output with either setting enabled. DSD/DoP and AirPlay retain the existing exclusions; changing Spotify's headphone sink can require pause/play.

Advanced EQ orders Enabled, Balance, Preamp and Presets. The disconnected USB confirmation is handled before stock input routing in both editions. Fresh wheel releases during the Now Playing animation apply volume once without scheduling an overlay; normal input resumes after the animation. Quick-settings tap, hold, movement, release, cancellation and destruction retain their existing one-shot tests.

## Checks

Both release variants build as `V135I` and `V135S`. Independent repeat builds produce byte-identical `update.tar` files. Packaging checks validate identities, hashes, inode metadata, kernel preservation and audited UI changes. The archives contain `update.tar` and `manifest.json`; the accompanying PDF is rebuilt from the guide.

Regression coverage includes playlist ordering/removal, stale records and failed transactions, search/back and closure; music-only native title sorting; actual input routing and animation-time volume; asymmetric PCM swap and mono interaction; setting persistence and Spotify helper selection; Bluetooth gain/mute/failure/limits; and the real stock startup wallpaper validation/copy block on repeated boots.

Run logs accompany the local delivery. Suites: `patch.py` and `playback.py` for both builds; `peq.py`, `coverflow.py`, `chapters.py`, `build.py`, `mp3.py`, and `remote.py`; plus both variants of `m4b.py`, `id3.py`, `ldac.py`, `headset_io.py` and `bluealsa.py`. `graphify update .` refreshes the AST graph without API calls.

## Measured performance and limits

The playback regression reports cached successor lookup at **25 emulated instructions**, with traversal reads reduced to **0** from 7 or 127 for its 8- and 128-track fixtures. Elapsed checkpoints write **16 bytes**, compared with full snapshots of 296 or 3,922 bytes. These verify that existing caching and checkpoint behaviour survives this change; they are not measurements of a new speedup.

Toolkit services, headset I/O and audio devices are simulated. Hardware UI behaviour, reconnects with real headsets, device CPU/I/O and battery runtime remain unverified. No battery-runtime improvement is claimed. Stock export/import round trips and a firmware update on a physical Q2 remain device checks.
