# iPod audit and device checks

Normal and iPod share one navigation payload. `--ipod` enables the compact layout
payload helpers and build-time edits in `tools/compact.py`; normal receives no
compact executable sites or UI assets. `patch/compact.json` records the original
asset hashes and full MIPS instructions. The builder also pins the complete stock
ZIP and executable, rejects mismatches, and records every changed asset/site.

AWTK binary UI files contain a four-byte magic, recursive widgets with a 32-byte
type and four signed geometry fields, NUL-separated properties and child/end
markers. Decode/encode must round-trip exactly before editing. Only the assets
pinned in `compact.json` are accepted: nine local browsing pages, the settings
and streaming pages, Home, the status bar and Now Playing. The primary `view_navbar` stays allocated but invisible
and disabled, including dynamically recreated children. Separate action bars are
moved into its space.

`PITCH = 72` is shared by all build-time row geometry edits, native row-height
resets and artwork offset divisors. Four rows fit the 290-pixel client area below
the status bar, so `BOTTOM = 290` replaces the stock lists' 260-pixel content
bottom. Row bodies are `PITCH - 4` pixels, and the stock 52-pixel artwork is
drawn at natural size (`ART = 52`) with `ART_INSET = 8` on all four sides: the
artwork never rescales, so glyphs and covers stay as sharp as stock, and the row
layout's eight-pixel left margin seats the artwork exactly. ART_INSET also
positions the playing overlay. Font definitions are untouched. Full-height
text/icon containers are shortened with their button. Titles and metadata keep
their stock centring, one pixel higher for the two-pixel-shorter body.

Theme edits change values in place in the shared `styles/default.bin`, so they
reach every page using these styles. The file holds a magic `0xFAFBFCFD`, a
100-byte index entry (data offset, state, style, widget type) per style state,
and typed properties. `compact.json` pins its hash and lists each edit with its
old value and the number of states holding it; a count mismatch fails the build.
List buttons (`s_btn_listitem`) lose their grey fill and 14-pixel corners, keeping
the pressed colour for touch feedback. Black list items, table rows and the black
album grid buttons (`s_btn_listblack`, used only by the album and all-music grids)
become transparent. The red playing-title styles (`s_scrlabel_red16l/20l/24l`) turn white,
leaving the stock playing glyph to mark the current song; only list rows use them.
The album page's inline black grid buttons become transparent as well.

## Home

`home_page_init` (`0x523c84`) looks up no widget and reads no `slide_menu` state. After the
guide and memory-play checks it runs `widget_foreach(win, 0x5239b4, win)`, whose visitor
matches each widget's name (`+0x10`): `img_playing`, `img_localmusic`, `img_folder`,
`img_stream`, `img_playset`, `img_sysset`, `img_left` and `img_right` get their stock click
handlers, and `label_*` gets `widget_set_tr_text` with its `small_*` key. Missing names are
skipped. Only the `img_left`/`img_right` handlers (`0x52391c`, `0x523968`) look up
`slide_menu`, and nothing else in the executable names it or any card. `application_init`
opens `home_page` once and it is never recreated, so the list keeps its own selection
(`CTX_DYNAMIC` is enough) and needs no hidden `slide_menu` or arrow stubs.

iPod's `home_page.bin` is a `list_view` (41-pixel `item_height`) holding a `scroll_view` of
seven 41-pixel rows (`btn_*` views), in stock order with Coverflow third: Now Playing, Local
Songs, Coverflow, Folder, Streaming, Playback Setting, System Setting. Each row holds a
white 20-pixel `label_*` (an ellipsis when too long) inset 8 pixels,
under a full-row transparent `img_*` that takes the tap and is the wheel's click target, so
the stock visitor binds and translates the rows as it did the cards. Coverflow's label is
literal. The wheel moves through the rows with hard ends, and the selection bar spans the
list. The 14 `menu_*` images are named only by the stock `home_page.bin` (every UI asset and
the executable were checked; the inputs are SHA-pinned), so iPod removes them.

The list is 205 pixels wide. Labels start 8 pixels in and end 10 pixels before the chevron's
glyph, 149 pixels wide, so the longest English label ("Playback Setting") fits. `img_homeart`, a
154-pixel square on the right, sits 8 pixels from the edge and centred in the 290-pixel client
area. Sizes are `HOME_*`
constants in `tools/compact.py`.

The Home setting (see [Display settings](#display-settings)) picks the layout. Split is the asset
as built. Full resizes `list_view_home` and, below it, every widget but the labels (the scroll
view, the rows and their tap images) to 375 pixels with `widget_move_resize` (`0x65ea44`, which
also marks the children for relayout), and hides the art, so the chevrons sit at the screen edge
and the whole row takes a tap. Split puts back the list's asset width, recorded at init. Home is
opened once and never recreated, so the layout is applied at init and again when the setting
changes. The art is not loaded while it is hidden.

The art follows the player. `player_get_id3info` hands the playing record's path
(`REC_PATH`) to `player_set_coverinfo`, and `player_parsecover_thd` (`0x512ca4`) then
writes that track's cover, sets `g_playcover_type` (`0xa3a332`) and copies the path to
`g_lastcover_url` (`0xa39c30`). Types: 1 embedded (`/tmp/coverpic.jpg`, 320x320), 2
folder image and 4 downloaded (`/tmp/externpic.jpg`), 3 none, 0 while it parses and
after `player_stop`. Tidal (5, `/tmp/album_tidal.jpg`) is keyed by its online URL and
left out. Now Playing reads the same files by type and clears `g_playcover_finishflag`,
so Home leaves the flag alone. Home uses the player's file only while
`g_lastcover_url` is the path of the queue's current track (`*mcl_pdeqplaylist` at
`MCL_POS`), so a track change never shows the previous cover; otherwise it shows that
track's Coverflow thumbnail, then `default_album_big`. Each load uses Coverflow's
sequence (`widget_load_image`, `image_base_set_image`, `widget_unload_image`), so the
same file name decodes again after a track change. The check runs when Home or the
status bar paints (the bar at least once a second) and reloads only when the track's
path or the usable cover type changes. The play queue is only changed on the UI
thread, where this check runs.

## Status bar and titles

`systembar_showface` (`0x52f610`, run by `system_bar_init` and then a 1 s widget
timer) finds each status bar widget with a recursive `widget_lookup` from the bar,
so parents and order are free to change. Every tick it re-shows the volume,
EQ, Bluetooth, SyncLink and Wi-Fi widgets and sets their images and text, but
never their geometry. `system_bar.bin` (iPod) therefore keeps the play state
alone in `view_left` and puts EQ, Bluetooth/codec, Wi-Fi and the battery icon in
`view_right`. The volume icon and number, SyncLink and the battery percentage
move to `x = -200`, where they draw off-screen. A new `label_title`
(`s_scrlabel_white20c`, an ellipsis when too long) is centred on the screen,
clear of the right icon group. Both groups use the list rows' 8-pixel edge margin
instead of stock's 50; stock pages already place controls 3 pixels from the edge.
The margin and the minimum title width, checked at build, are constants in
`tools/compact.py`.

The navbar is hidden, as on the local pages, on the settings pages
(`systemset/*`, `playset/*`), `audiosetting_page` and `stream_page`, listed in
`navbar_only` in `compact.json`. Their native
inits destroy the navbar's children and create an unnamed title `hscroll_label`,
back, Home and Now Playing buttons; none has a control the keys lack. Lists move
up 50 pixels and reach `BOTTOM`, keeping the stock 78-pixel settings rows; other
panels move up and keep their size. The settings inits never move or resize
these widgets. Left out: `wifitransport_page` (its image starts above the
navbar's bottom edge), `fwdownload_page` (no navbar), the PEQ page (it replaces
all children) and every Tidal page, whose navbars hold the search and sort
buttons. A page with a visible navbar keeps its own title and the status bar
shows none.

Native local row-pool constructors are at 0x523038 (folder), 0x4aa2cc (songs),
0x4b0efc (local categories) and 0x4a4ae8 (album list/grid). The album grid branch
is unchanged. Album detail, artist track and playlist constructors have their own
explicit sites in the audit. Folder reset at 0x5217d4, return offset division at
0x521a84 and scrolling cover division at 0x5228f8 all use the same compact pitch.
The category cover callback originally divides by 120 despite using 78-pixel
rows; iPod corrects its audited divisor at 0x4b0608 to 72. Rebinding and delayed
cover callbacks keep the same widget geometry and saved cover preferences.

Seven audited row-constructor calls install a per-instance children layouter for
folder, song, album-list, category, album-track, artist-track and playlist rows.
Before the stock horizontal layout runs, it gives the title (and its containing
view, where present) the row width minus the existing side margins, visible sibling
widths and gaps. Hidden artwork and controls reserve no space. The stock layouter
still positions the children, preserving the title's left edge, artwork, row height
and padding. Its clone/destruction and parameter functions remain native; neither
the shared widget implementation nor album grids are hooked. The folder rebind's
140/190-pixel resize call is disabled so recycled titles retain their computed
width. Title styles and scrolling/ellipsis settings are untouched.

The stock long-key function at 0x4e873c retains all instructions except the final
Home call at 0x4e8924. Stock power, lock, test and key-lock gates and its release
latch execute first. iPod cancels centre confirmation and spin state, checks
the shared screen/navigation restrictions, and then either calls the stock Home
destination when Now Playing is already the top window, or calls the stock switch
function with `playing_page` and `{0, 0, 0xff, 2}`. The `0xff` context skips
player_start, so playback is not restarted. The switch keeps the hold's key-up
from reaching the stock release filter, which would leave the latch that filter
shares armed and swallow the next Return, so the payload clears that latch once
the switch has landed. The hold's release therefore leaves the unit on Now
Playing and the first short Return reaches the stock Back path, with position
memory restoring the browsing page and its selection. No short-Return callback or
other long-key destination changes.

## Chevrons

Stock draws `list_into` on Local Music's categories, the `localclass_page` rows (artists, genres,
composers), the album list and folder rows that are not songs, hidden in multi-select. iPod adds
it, aligned with those (see [internals.md](internals.md#drawing)), only on the `DRILL` windows in
`patch/contexts.inc`: Home and the playlist list, whose rows open their tracks. Tiles narrower
than half the list (playlist Import/Export) get none. The artist page's Albums tab drills but has
no stock chevron or payload row layouter, so it has none.

## Fast-scroll letter

Spinning quickly through a list of more than 16 rows shows the first character of the selected
row's title in a large white letter, centred over the list on a rounded dark square. It appears
once the wheel moves more than one row per detent and disappears 400 ms after the last fast
detent, or at once on a slow detent, a touch or the end of the list. Latin letters show in
capitals; leading spaces are skipped and any other character shows as it is. Home, settings and
other short lists never show it. Values are in `patch/offsets.inc` (`LETTER_*`); see
[internals.md](internals.md#drawing).

## Now Playing

`playing_page.bin` follows Rockbox's iVideo Now Playing in the 375x290 client area, below the
status bar's "Now Playing" title:

```
  0 +---------------------------------------------------------+
    | 3 of 12 (8,0 217x40)          fav 225  more 275  mode 325|  icons 50x40
 40 +---------------------------------------------------------+
    |  +-----------+                                          |  slide_view 0,40 375x186
    |  |    art    |   Title   (190,97 177x24, white 20)      |
    |  | 8,48      |   Artist  (190,125 177x20, grey 16)      |
    |  | 170x170   |   Album   (190,149 177x20, grey 16)      |
    |  +-----------+                                          |
228 |                     . o .   (page dots)                 |
251 |  [=========================-------------------------]  |  bar 8,251 359x8
262 |  01:23 (8 80x16)                  -02:34 (287 80x16)    |
290 +---------------------------------------------------------+
```

The art, title, artist and album are the slide_view's first page, so a swipe replaces all of them
with the stock lyrics or info page. Those keep their stock 225-pixel column, centred: stock creates
each lyric line 225 pixels wide. The big play/pause icon stays centred on the art and the loading
spinner moves with it. The on-screen Return icon moves off-screen, as on the pages whose navbars are
hidden; the hardware Return does the same. Favourite, More and the play mode icon keep their stock
images and handlers in the top row.

The bar is plain colour: a `#1C1C1C` track (`BAR_BOTTOM`) and a fill in the accent's light
tone (Graphite `#6E6E6E`, 3.3:1; see [Display settings](#display-settings)), with no thumb.
The asset holds Graphite's; `ringnav_playing` sets the current accent's. Tap or drag anywhere on it to seek, as stock. The elapsed time
is stock's label; the remaining time replaces stock's total. Sizes are `NP_*` constants in
`tools/compact.py`; see [internals.md](internals.md#now-playing-ipod).

**Scrub.** The centre button starts scrubbing, as on an iPod classic, and the bar fill turns white
while it lasts. Each wheel tick moves 5 seconds, times the same ramp as a long list (up to 40
seconds a tick while spinning), within the track. Both times and the bar follow the target, and the
track jumps there 150 ms after the last tick. Centre again, Return, a touch or 3 seconds without a
tick give the wheel back to the volume; Return then stays on the page. A double press still turns
the screen off. Values are `SCRUB_*` and `SEEK_MS` in `patch/offsets.inc`; see
[internals.md](internals.md#scrub-ipod).

## Display settings

`systemset_display_page_init` (`0x4c1d04`) destroys the children of `scroll_view_display` and
builds three rows with `0x4c19bc`: a `list_item_create(view, 0, 0, 0, 0)` in `s_listitem_black`
(the list view lays it out 78 pixels high), holding a `button_create(item, 20, 0, 335, 70)` in
`s_btn_listitem` with a click handler, and in it a 52-pixel icon at x 10, a
`s_scrlabel_white24l` `hscroll_label` at (72, 0, 210, 70) and `list_into` at x 282. The rows
show no value; each opens a sub-page. iPod runs the stock init, then adds two rows the same way:
"Accent: Graphite" and "Home: Split", the value in the label (260 pixels wide, to where the
chevron ends), with no icon and no chevron, since Centre or a tap changes them in place. The
page is `CTX_FIXED`, so the wheel walks onto them like the stock rows.

A change is saved at once with the stock `write_int_config(value, "IPOD", key)` (`0x4f3f4c`):
`sprintf("%d")`, then `toolsWriteConfig("/mnt/data/config.ini", section, key, text)`, which
rewrites the key or appends `[IPOD]` with it (`"[%s]\n%s=%s\n"`). Both values are read once,
on the payload's first use (after stock `config_init`: `application_init` runs `platform_init`, which
calls it, before it opens any window), with `toolsReadConfig` (`0x5bd464`), in the order stock `config_init`
calls it: `(path, section, key, out, default)`. It reads the file line by line
(`strcasecmp` on the section and the key), copies the trimmed value to `out` and returns 1; a
missing key copies the default and returns -1. The default must not be null (stock reads its
first byte). The payload passes `"0"`, so a missing or unreadable entry, or any value that is not
one valid digit, is Graphite and Split.

| Accent | Selection bar | White on top / bottom | Light tone (on `#1C1C1C`) | Red tone (white on it) |
|---|---|---|---|---|
| Graphite (0, default) | `#5A5A5A` to `#363636` | 6.9:1 / 12.1:1 | `#6E6E6E` (3.3:1) | `#D8D8D8` (1.4:1) |
| Crimson (1) | `#E8123F` to `#A60025` | 4.6:1 / 7.9:1 | `#EB2F56` (4.1:1) | stock `#FF1448` (3.9:1) |
| Tidal (2) | `#13838D` to `#095158` | 4.5:1 / 9.0:1 | `#30929B` (4.6:1) | `#30929B` (3.7:1) |
| Champagne (3) | `#8C732C` to `#5D4A18` | 4.6:1 / 8.5:1 | `#9A8446` (4.7:1) | `#9A8446` (3.6:1) |

The light tone is the top lightened 12% toward white, as Graphite's `#6E6E6E` is: the bar's
one-pixel highlight and the progress fill. Tidal and Champagne tops are darkened in hue (and
their bottoms by the same factor) so white text holds 4.5:1 at the top; their light tone also
serves as the red tone. One rule picks the tone for stock red: red text (`text_color`,
`highlight_text_color`) and red pixels in images take the red tone, and every other red color
(fills, borders, slider and progress fills, gradient stops) takes the light tone. Graphite's red
tone is silver `#D8D8D8`, so lit switches, ticks and red text stand out (14.7:1 on black), while
stock's red buttons with white text become white on `#6E6E6E` (5.1:1) and the download bar a
`#6E6E6E` fill on its `#D8D8D8` track. The presets are `ACCENTS` in `patch/offsets.inc`; see [internals.md](internals.md#accent) for the recolouring.

## Device checklist

Every check below has been hardware-tested on both builds and confirmed by the
user. Their parameters remain unchanged; the list stays as the regression guide.

- **pull to search**: iPod Local Songs only: start at the list top, pull
  47/48/49 pixels and release. Check both prompts, backing below the threshold,
  horizontal swipes, ordinary taps, mid-list starts and empty lists. No row should
  open after a claimed pull. Close search and confirm the same category/tab context.
  Folder view must not respond. Interrupt a pull with wheel, buttons, navigation or
  screen-off; the prompt must disappear without opening search. A pull starting at
  screen y=30 belongs to quick settings; y=31 inside the list may start search.
  Wheel end wrapping stays unchanged. Normal keeps its stock search toolbar.

- **readability**: Browse Folder and Local Songs, artists, genres, albums, album
  tracks, artist tracks/albums and playlists. Check all four complete ordinary
  rows, long filenames, two-line metadata, non-Latin text and the selection
  outline. Titles should use the formerly empty right-hand space up to the row's
  padding or visible trailing control, without overlap. Repeat after scrolling,
  page reopening and artwork/control visibility changes; short titles should stay
  at the same left position and overflowing titles should still scroll/ellipsize.
  Touch and centre must activate the same item at every row and edge.
- **toolbar**: iPod hides the entire primary toolbar (including Home,
  search/multi-select and Now Playing icons), keeps the status bar, and reclaims
  its space after page recreation and nested folder returns. Normal stays stock.
- **artwork**: Toggle folder icons/covers off/on, restart to verify saved settings,
  and try missing covers, square/non-square art, fast scrolling and recycled rows.
  Check late-arriving covers, the even inset and sharpness around artwork, alignment, no overlap
  and correct artwork indexing after child/grandchild returns. Test both saved
  album display modes.
- **return**: Short Return traverses folders and other pages as stock. Hold Return
  from browsing and release: iPod opens Now Playing without restarting audio
  and stays there; the next short Return goes back to the same page, selection and
  scroll position. Hold Return while already on Now Playing: the stock Home
  shortcut runs. Normal opens Home as before. Repeat holds and visits, try already
  playing and an empty playback queue, and confirm the next short Return still
  works after each visit. Arm centre confirmation then hold Return; no delayed
  item should open. Repeat screen-off, locked, power-off/USB/BT restrictions and
  modal-blocked navigation. Other long keys must remain stock.
- **scrollbar**: Turn the wheel in Folder, Local Songs and a long settings list.
  Confirm the player's own right-edge scrollbar appears as the list moves, tracks
  the position and fades on its own; check lists without a native bar stay
  unchanged. Touch-scroll and then turn the wheel to confirm the handoff, and
  leave a wheel-scrolled page to confirm no bar or timer returns on the next
  screen.
- **retained_controls**: Use tabs, Play All, sorting, playlist import/export,
  rename/delete and all separately retained action/editing controls. Verify
  remembered selection after sorting and folder/album/query returns.
- **excluded_screens**: Verify settings, online services, dialogs
  and scanning/editing screens retain stock layouts and work.

Emulator tests validate native constructors, stock input gates and the shared
navigation behavior with mocked toolkit services. They do not establish visual
readability, actual touch hit-testing, rendering or playback behavior on hardware.
