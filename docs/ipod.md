# iPod UI

Normal and iPod share one navigation payload. `--ipod` enables the compact layout
payload helpers and build-time edits in `tools/compact.py`; normal receives no
compact executable sites or UI assets. `patch/compact.json` records the original
asset hashes and full MIPS instructions. The builder also pins the complete stock
ZIP and executable, rejects mismatches, and records every changed asset/site.

AWTK binary UI files contain a four-byte magic, recursive widgets with a 32-byte
type and four signed geometry fields, NUL-separated properties and child/end
markers. Decode/encode must round-trip exactly before editing. Only the assets
pinned in `compact.json` are accepted: nine local browsing pages, the settings
and streaming pages, Home, the status bar, Now Playing, the quick settings
pull-down, the confirm pop-up and the theme (`styles/default.bin`). The primary `view_navbar` stays allocated but invisible
and disabled, including dynamically recreated children. Separate action bars are
moved into its space.

## Rows

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

## Flat rows and selection bar

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

With the rows transparent, the payload draws the selection bar behind them: a full-width
gradient in the accent colour, or the tile's own rectangle in a grid (see
[internals.md](internals.md#drawing)). A touch hides it until the next wheel or centre input.

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

iPod's `home_page.bin` is a `list_view` (39-pixel `item_height`, `HOME_ROW`) holding a
`scroll_view` of seven 39-pixel rows (`btn_*` views), in stock order with Coverflow third: Now
Playing, Local Songs, Coverflow, Folder, Streaming, Playback Setting, System Setting. The list
starts `HOME_TOP` (8) pixels below the status bar and ends 9 above the bottom, so the first row
no longer touches the bar and the last clears the glass. Each row holds a white 20-pixel
`label_*` (an ellipsis when too long) inset 33 pixels (see [Rounded corners](#rounded-corners)),
under a full-row transparent `img_*` that takes the tap and is the wheel's click target, so
the stock visitor binds and translates the rows as it did the cards. Coverflow's label is
literal. The wheel moves through the rows with hard ends, and the selection bar spans the
list. The scroll view sets `yslidable`: a `list_view`'s layout (`0x5ea3a4`) turns it on only
for a list with a mobile scroll bar, which Home has none of, and the payload navigates vertical
scroll views only (V5.4I showed no bar or chevrons on Home). The 14 `menu_*` images are named only by the stock `home_page.bin` (every UI asset and
the executable were checked; the inputs are SHA-pinned), so iPod removes them.

The list is 230 pixels wide. Labels start 33 pixels in, where the last row's text clears the
bottom-left corner, and end 10 pixels before the chevron's glyph, 149 pixels wide, so the longest
English label ("Playback Setting") fits. Every label shares that left edge and every chevron the
column 58 pixels from the row's end. `img_homeart` fills the right panel edge to edge: x 230 to
the screen edge and the whole window height under the status bar (145x290, `HOME_ART_RECT`). Sizes
are `HOME_*` constants in `tools/compact.py`.

The art is cropped to fill the panel, never stretched. Stock's own `fill` draw type (`8`,
`canvas_draw_image_fill` `0x63856c`) scales proportionally but anchors its crop at the image's
top-left, so on its own a square cover would show only its left half. Each time the art changes,
the payload sizes `img_homeart` to the decoded image's proportions, just covering the panel and
centred on it (a square cover becomes 290x290 at x 158), so `fill` draws the whole image; the
background hook narrows the canvas clip to the panel before the image paints and the border hook
restores it, so the overflow is cropped evenly from both sides. An image whose size is unknown
(the placeholder when it does not decode) fills the panel as it is. A fitted cover reaches under
the list, so Home makes the art insensitive (`widget_set_sensitive`) and taps there still find
the rows. The rounded glass hides the
panel's two right-hand corners, like any background.

The Home setting (see [Display settings](#display-settings)) picks the layout. Split is the asset
as built. Full resizes `list_view_home` and its scroll view to 375 pixels, so the selection bar
spans the screen, and the rows and their tap images to `HOME_FULL_ROW` (369, `patch/offsets.inc`)
with `widget_move_resize` (`0x65ea44`, which also marks the children for relayout), and hides the
art. The labels keep their width. The chevrons' glyphs then end 33 pixels from the right edge, as
the labels start 33 from the left: at the screen edge the last row's chevron would sit under the
bottom-right corner. Split puts back the list's asset width, recorded at init. Home is
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

## Status bar and clock

`systembar_showface` (`0x52f610`, run by `system_bar_init` and then a 1 s widget
timer) finds each status bar widget with a recursive `widget_lookup` from the bar,
so parents and order are free to change. Every tick it re-shows the volume,
EQ, Bluetooth, SyncLink and Wi-Fi widgets and sets their images and text, but
never their geometry. `system_bar.bin` (iPod) therefore keeps the play state
and EQ in `view_left`, as stock does, and puts Bluetooth/codec, Wi-Fi and the
battery icon in `view_right`. The volume icon and number, SyncLink and the battery
percentage move to `x = -200`, where they draw off-screen. Both groups sit 54 pixels
from the edges (`STATUS_MARGIN`): the 50 where the 16-pixel icons clear the top corners
([Rounded corners](#rounded-corners)) plus 2 (`STATUS_PAD`) so they don't crowd the glass;
V5.4I's 8 pixels put the play state and the battery under the glass, so no icon showed. A new
`label_clock` (`s_scrlabel_white20c`) is centred on the screen. It has the width left in the
narrowest case, 109 pixels at x 133, clear of either group with every icon shown (left 94
pixels, right 133); the build fails if that would be under `CLOCK_MIN` (105). The payload paints
the bar's graphite gradient and shows the device's local time in `label_clock` as a 12-hour
clock without seconds or a leading zero (`6:14 PM`), or `--:--` if the time cannot be read, on
every page and under every dialog (see [internals.md](internals.md#status-bar-ipod)). The widest
text, `12:59 PM`, is 86 pixels in the stock font at 20 pixels; `tools/test_build.py` measures
every time against the label.

The navbar is hidden, as on the local pages, on the settings pages
(`systemset/*`, `playset/*`), `audiosetting_page` and `stream_page`, listed in
`navbar_only` in `compact.json` with their pinned hashes. Their native
inits destroy the navbar's children and create an unnamed title `hscroll_label`,
back, Home and Now Playing buttons; none has a control the keys lack. Lists hold
settings rows (see [Settings](#settings)); other panels move up 50 pixels and keep
their size. The settings inits never move or resize
these widgets. Left out: `wifitransport_page` (its image starts above the
navbar's bottom edge), `fwdownload_page` (no navbar), the PEQ page (it replaces
all children) and every Tidal page, whose navbars hold the search and sort
buttons. A page with a visible navbar keeps its own title.

## Settings

Settings, Playback Setting, Audio settings and Streaming lists hold four complete 68-pixel rows
(`SET_ROW`, `SET_ROWS`), starting 8 pixels (`SET_TOP`) below the status bar: the list is
272 pixels high at y 8 and ends 10 pixels above the bottom. The `navbar_only` assets set their
`list_view`'s `default_item_height` from 78 to 68, which no stock asset uses, and nothing else.
Constants are `SET_*` in `patch/offsets.inc`.

Every row is built natively, about 60 builders in all, one pattern throughout: a
`list_item_create(view, 0, 0, 0, 0)` (some pass 78 as the height) holding a `button_create(item,
20, 0, 335, 70)`, and in the button an optional 52-pixel icon at x 10, a 24-pixel `hscroll_label`
at x 72 (x 10 without an icon) and a 50-pixel trailing image (chevron, tick or switch) at x 276
or 282. Two-line rows put a 20-pixel label at y 25; USB volume shows a value label at x 176. The
builders never move, resize or scroll their widgets afterwards (the stock equalizer page, which
the PEQ editor replaces, is the only settings code that calls `widget_move`), so one layout hook
owns the geometry:

- iPod points the `list_view` children layouter's vtable layout slot (`0x926930`, vtable
  `0x926928` + 8, stock `0x5e9eb4`) at `ipod_list_layout`. Every list lays out through it; only a
  list with no `item_height` and a `default_item_height` of 68 gets settings rows, so Home (an
  `item_height` of 39), the local lists (72) and every stock list are untouched.
- Before the stock layout it sets list items that stock made 78 high to 68: the stock layout keeps
  an item's own height over `default_item_height` (`0x5ea5c4` onward). The stock layout then
  stacks the rows and sizes the scroll view, so scrolling, the scroll bar and the payload's
  selection all see 68-pixel rows.
- After it, each stock button (x 20, 335 wide) spans its row, 375 by 68, so the selection bar and
  the tap target are the whole row. Its icon box shrinks to 40 pixels (`SET_ICON`, drawn
  `scale_down`, value 5 in the stock draw type table at `0x9272c0`, which draws a bitmap that
  already fits 1:1; see [Settings icons](#settings-icons)), centred on the row at x 28
  (`SET_ICON_X`). Text starts 12 pixels (`SET_GAP`) after the icon, at x 80, or at x 20
  (`SET_TEXT_X`) without one; the Display page's Accent and Home rows keep the icon rows' column.
  Trailing images end 24 pixels (`SET_EDGE`) from the right, at x 351; value labels and the text's
  right edge move with them, never nearer the edge than 20. Full-height children fill the row and
  shorter ones keep their centre. A mapped button no longer matches the stock geometry, so a later
  layout leaves it alone.

With these values the text, icons and trailing images of the first and the last visible row clear
the rounded glass (`tools/test_patch.py` runs the Language, Bluetooth quality, System Settings and
Wi-Fi builders and the Display rows, then checks both positions).

### Settings icons

Scaling the 52-pixel artwork down on the device left jagged edges, so the build pre-sizes it
instead. `settings_icons` in `compact.json` pins the 39 settings icons by hash: `system_*`,
`playset_*`, `display_*`, `wifiset_*`, `netservice_*`, `usb_chargeswitch` and `bt_adjvol`, 52-pixel
RGBA PNGs that only native settings code names (top level and nested pages such as Display,
Wi-Fi, Bluetooth and Network services); no UI asset or other screen uses them. For each one the
iPod build runs ImageMagick (`magick`, else `convert`) with an alpha-weighted Lanczos resize to
40x40, strips metadata and date chunks so the bytes are reproducible, and replaces the file in
place, keeping its inode metadata. The build fails if an input's hash or format differs, or if an
output is not 40-pixel 8-bit RGBA with the same transparency; the manifest records both hashes
and the ImageMagick version under `changed_assets` and `tools`. `tools/test_build.py` checks the
packaged bytes, the sizes, and that each icon's average colour on black and on the Graphite
selection grey matches the stock icon's. Other 52-pixel images that land in settings rows, such as
Streaming's Tidal logo (`list_tidal`, which the folder root may also use), keep their stock bytes
and still scale down. Normal keeps every icon stock. The recolouring of accent-red artwork
(`ringnav_image_add`) works on the decoded bitmap, so it applies at either size.

## Quick settings

The pull-down (`dialog/statusbar_dialog.bin`) covers the whole screen when open. Its eight 60-pixel
controls keep their four columns in two rows from y 20. Every label is the stock 16-pixel white
style (`s_label_white16c`), 80 pixels wide and 40 high (two lines), top-aligned so one- and
two-line labels start on the same line, 6 pixels under its icon and 12 above the next row. The
brightness slider becomes a 6-pixel track (`#3A3A3A`, white fill) in a 48-pixel-high slider that
still takes a tap or drag anywhere on it (`slide_with_bar`), from x 68 to 307. The stock dim and
bright suns stay at its ends, in line with the first and last icon columns. Sizes are `QS_*` in
`tools/compact.py`. `dialog_statusbar_dialog_init` (`0x4a0d88`) finds every widget by name and
never moves or resizes one.

The controls' stock images are 60-pixel discs: `#444444` with a white glyph when off, stock red
(`#FF1448`) with a white glyph when on (`drop_wifiopen`, `drop_btopen`, `drop_keylockopen`,
`drop_highgain`, `drop_lo`, `drop_usbaudio`, `drop_usbdac`), grey glyphs when disabled. An active
disc takes the accent's red tone, as everything else red does, so it stands clearly apart from the
grey inactive discs. On a tone brighter than `GLYPH_LIGHT_MAX` (perceived brightness 160 of 255),
which is Graphite's silver, the white glyph and its anti-aliased edges turn `CONFIRM_SURFACE`
(`#2B2B2B`) so the glyph stays legible; Crimson, Tidal and Champagne keep the white glyph (3:1 or
more). Only an image that holds the red disc gets the dark glyph, so inactive discs keep their white
glyphs; off and disabled discs contain no red and keep their stock look, and alpha is untouched.
The brightness suns (`drop_lighleft`, `drop_lightright`) sit on black, not a disc, and keep the
accent's red tone (`DROPDOWN_SUN`).

## Coverflow

The covers are drawn with depth in both builds ([internals](internals.md#coverflow-depth)): the
selected cover at its native 160 pixels, two angled neighbours a side and a faint reflection, all
in the top 210 pixels of the page. The album name sits under them (`CF_TEXT_Y`) in 24-pixel white,
the artist under that in 20-pixel grey (`#AAAAAA`, stock secondary text), and both, like the
track list's title and rows and the progress and empty messages, keep 36 pixels (`CF_EDGE`) from
each side, where the lowest visible track row's text clears the bottom corners. Long names still
scroll within that. The Refresh card uses the album line. The status bar shows "Coverflow".
Values are `CF_*` in `patch/offsets.inc`; normal keeps its track list layout.

## Rounded corners

The panel's glass rounds its corners and hides what is drawn under them. `CORNER_R` in
`tools/compact.py` (80 pixels) is the calibration knob: the radius, fitted to V5.4I photos and
to stock's 50-pixel status bar margins. `corner_inset(y)` gives the width hidden at each end of
screen row `y`, and `corner_x` adds `CORNER_SLACK` (4). The status bar groups, the Home labels
and Now Playing's top and bottom rows take their insets from it; settings notes moved under the
hidden navbar end their text clear of the top-right corner. With the defaults: status bar 52
pixels plus `STATUS_PAD` (2), the clock at least 57, Home text and Full's chevrons 33, "3 of 12" 16, Now Playing icons
ending at 353, the bar 21 and the times 46 pixels from the edges. The runtime layouts' values
(`SET_*`, `CF_*`, `CLOCK_EDGE`, `HOME_FULL_ROW` in `patch/offsets.inc`) are checked against the
same calibration by the tests.

`tools/test_build.py` fails an iPod build when any fixed text or icon in a changed asset reaches
under the glass (screen coordinates: the bar at y 0 to 30, windows at 30 to 320, the quick settings
and confirm pop-ups at 0 to 320): a label's font-high band, an image drawn centred at its size, a
slider's bar, else the widget. Backgrounds, tap targets and list rows, which scroll, are not
checked there; `tools/test_patch.py` checks the settings rows in the first and last visible slots,
Coverflow's labels and lowest track row, and the status bar clock against every combination of
icons. Raising `CORNER_R` until the clock drops
under `CLOCK_MIN` fails the build.

## Hold Return

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
status bar and its clock:

```
  0 +---------------------------------------------------------+
    | 3 of 12 (16,0 187x40)         fav 203  more 253  mode 303|  icons 50x40
 40 +---------------------------------------------------------+
    |   +---------+                                           |  slide_view 0,40 375x186
    |   |   art   |   Title   (182,97 177x24, white 20)       |
    |   | 16,56   |   Artist  (182,125 177x20, grey 16)       |
    |   | 154x154 |   Album   (182,149 177x20, grey 16)       |
    |   +---------+                                           |
228 |                     . o .   (page dots)                 |
251 |  [=========================-------------------------]  |  bar 21,251 333x8
265 |      01:23 (46 80x16)           -02:34 (249 80x16)      |
290 +---------------------------------------------------------+
```

The art and the metadata keep 16 pixels from the sides (`NP_MARGIN`) and 12 from each other; the
art is 154 pixels, as large as that leaves while the text column keeps its 177 pixels, and
"3 of 12" starts in line with it. Each band has its own space: the top row, then the art 16
pixels below it, the page dots 18 pixels under the art, the bar with the stock A-B markers
(y 250 to 260) and the times 6 pixels under the bar.

The art, title, artist and album are the slide_view's first page, so a swipe replaces all of them
with the stock lyrics or info page. Those keep their stock 225-pixel column, centred: stock creates
each lyric line 225 pixels wide. The big play/pause icon stays centred on the art and the loading
spinner moves with it. The on-screen Return icon moves off-screen, as on the pages whose navbars are
hidden; the hardware Return does the same. Favourite, More and the play mode icon keep their stock
images and handlers in the top row.

The bar is plain colour: a `#1C1C1C` track (`TRACK_COLOR`) and a fill in the accent's light
tone (Graphite `#6E6E6E`, 3.3:1; see [Display settings](#display-settings)), with no thumb.
The asset holds Graphite's; `ringnav_playing` sets the current accent's. Tap or drag anywhere on it to seek, as stock. The elapsed time
is stock's label; the remaining time replaces stock's total. Sizes are `NP_*` constants in
`tools/compact.py`; see [internals.md](internals.md#now-playing-ipod).

**Scrub.** The centre button starts scrubbing, as on an iPod classic, and the bar fill turns white
while it lasts. Each wheel tick moves 5 seconds, times the same ramp as a long list (up to 40
seconds a tick while spinning), within the track. Both times and the bar follow the target at once;
the track jumps there once, when the scrub ends. Centre again or Return ends it, as do a touch and
3 seconds without a tick, and each gives the wheel back to the volume; Return then stays on the
page. Ending without having moved the target does not seek. A double press still turns the screen
off. The jump is stock's key seek, which can pause the player briefly, but only once, when the
scrub ends, instead of after each pause between ticks. Values are `SCRUB_*` in
`patch/offsets.inc`; see [internals.md](internals.md#scrub-ipod).

The top row's text and icons, the bar's ends and the times keep clear of the corners
([Rounded corners](#rounded-corners)).

**Lyrics.** Stock already highlights the current line and scrolls to keep it in view.

## Pop-ups

The confirm and choice dialogs in `patch/contexts.inc` (flag `BUTTONS`) have no list: their buttons
sit directly in the dialog. For those, the dialog itself is the navigation surface, a kind that
never scrolls, and its clickable descendants are the rows in UI order. The wheel moves between
them with hard ends, Centre clicks the selected one after the usual double-press window, and the
bar is drawn in the dialog's background: the button's own rectangle for a button narrower than half
the dialog (the confirm pair), the full width otherwise. A new dialog starts on its first button,
Cancel on the confirm pair.

The confirm pair sits symmetrically, each 80-pixel tile centred in its half of the screen (x 53
and 242). Its stock discs are Shanling red with white glyphs, which every accent but Crimson
turned into a light tone (Graphite's silver left the white check at 1.4:1). The shared image hook
now gives `confirm_ok`, `confirm_cancel` and their pressed images a dark surface under every
accent, Crimson included: the same red-blend mapping with `CONFIRM_SURFACE` (`#2B2B2B`) as the
tone, so the OK disc is `#2B2B2B` and Cancel's lighter tint `#595959`, while the glyphs stay
white and near white (`#E5E5E5`): 14.2:1 and 5.6:1. Every confirm prompt uses these images through
`s_img_confirmok`/`s_img_confirmcancel`, so all are covered. The wheel's focus is the accent tile
behind the disc with a two-pixel white frame, visible on any accent. Callbacks, actions and the
initial Cancel are stock. Tidal's own confirm pop-up (cyan, black glyphs) keeps its look.

| Dialog                                           | Buttons                                         |
| ------------------------------------------------ | ----------------------------------------------- |
| `confirminfo_dialog`, `tidal_confirminfo_dialog` | `img_cancel`, `img_enter` (80x80, side by side) |
| `autoshutdown_dialog`                            | `btn_cancel`                                    |
| `tidal_quality_select_dialog`                    | four quality rows, `btn_ok`                     |
| `tidal_sortmode_dialog`                          | three sort rows, `btn_cancel`                   |

`sortselect_dialog` and the search result dialogs already navigate their lists. Left out, so the
wheel stays on the volume: the text-entry dialogs (`addplaylist`, `editwifi`, `kbwifiadd`,
`kbwifipass`, `renameplaylist`, `searchbox`, `tidal_searchbox` and Baidu's `edit_dialog`), the Update
Local Music progress (`updatemusic_dialog`, whose only button cancels a scan that can run for
minutes), the pull-down quick settings (`statusbar_dialog`), and the dialogs without buttons
(`volume_dialog`, `msginfo_dialog`, `checkfw_dialog`, `showsn_dialog`, `dialog_wifibt_test`).

## Boot

The iPod build starts on Home. **Playback Setting → Memory playback** has three
options: **Off**, **Track** (restore the queue and song from its beginning), and
**Location** (also restore the saved time within the song). With Track or Location,
the restored player is paused. Opening Now Playing shows it; press Play/Pause to
resume audio. Opening that page alone does not resume playback.

**System Setting → In-Vehicle mode** is the car-mode exception: it keeps the stock
behavior, opening Now Playing and starting playback from the saved position.
With both Memory playback and In-Vehicle mode off, boot does not restore playback.
See [internals.md](internals.md#boot-resume-ipod).

To check boot/resume on the device (a full shutdown/start, not screen off/on):

1. Turn In-Vehicle mode off and set Memory playback to Location. Play a local
   track from an album/queue to an obvious point, such as 01:00, then shut down
   normally. Power on: Home should appear without audio. Open Now Playing and
   check the same queue, song and saved position; press Play/Pause to continue.
2. Repeat with Track. The same song should be restored paused at its beginning.
3. Repeat with Memory playback Off and In-Vehicle mode still off. Home should
   appear without restoring playback.
4. Enable In-Vehicle mode and repeat. Now Playing should open and audio should
   start automatically. Restore the preferred settings after this check.
5. Check the missing-track error separately using a disposable local track:
   save it with Location, shut down normally, temporarily rename that file on
   the card, then power on with In-Vehicle mode off. The stock error toast should
   appear on Home. Restore the filename afterwards.

## Display settings

`systemset_display_page_init` (`0x4c1d04`) destroys the children of `scroll_view_display` and
builds three rows with `0x4c19bc`: a `list_item_create(view, 0, 0, 0, 0)` in `s_listitem_black`
(the list view lays it out 78 pixels high), holding a `button_create(item, 20, 0, 335, 70)` in
`s_btn_listitem` with a click handler, and in it a 52-pixel icon at x 10, a
`s_scrlabel_white24l` `hscroll_label` at (72, 0, 210, 70) and `list_into` at x 282. The rows
show no value; each opens a sub-page (iPod's [settings rows](#settings) then lay them out 68
pixels high). iPod runs the stock init, then adds two rows the same way:
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

| Accent                | Selection bar          | White on top / bottom | Light tone (on `#1C1C1C`) | Red tone (white on it)  |
| --------------------- | ---------------------- | --------------------- | ------------------------- | ----------------------- |
| Graphite (0, default) | solid `#424242`        | 10.0:1 / 10.0:1       | `#6E6E6E` (3.3:1)         | `#D8D8D8` (1.4:1)       |
| Crimson (1)           | `#E8123F` to `#A60025` | 4.6:1 / 7.9:1         | `#EB2F56` (4.1:1)         | stock `#FF1448` (3.9:1) |
| Tidal (2)             | `#13838D` to `#095158` | 4.5:1 / 9.0:1         | `#30929B` (4.6:1)         | `#30929B` (3.7:1)       |
| Champagne (3)         | `#8C732C` to `#5D4A18` | 4.6:1 / 8.5:1         | `#9A8446` (4.7:1)         | `#9A8446` (3.6:1)       |

The light tone is the top lightened 12% toward white (Graphite keeps `#6E6E6E`): the progress
fill and, except on Graphite, the bar's one-pixel highlight; Graphite's bar is solid with a
restrained `#555555` top edge. Tidal and Champagne tops are darkened in hue (and
their bottoms by the same factor) so white text holds 4.5:1 at the top; their light tone also
serves as the red tone. One rule picks the tone for stock red: red text (`text_color`,
`highlight_text_color`) and red pixels in images take the red tone, and every other red color
(fills, borders, slider and progress fills, gradient stops) takes the light tone. Graphite's red
tone is silver `#D8D8D8`, so lit switches, ticks and red text stand out (14.7:1 on black), while
stock's red buttons with white text become white on `#6E6E6E` (5.1:1) and the download bar a
`#6E6E6E` fill on its `#D8D8D8` track. The presets are `ACCENTS` in `patch/offsets.inc`; see [internals.md](internals.md#accent) for the recolouring.

## Device checklist

The regression guide for device tests of the iPod build. Entries that name
Normal also apply to it.

**Validation status:** the iPod checklist, shared navigation checks and Coverflow
visual/audio checks pass on hardware, including boot/resume. Numerical Coverflow
frame-rate measurement remains pending. These results cover existing iPod
behavior; planned features require their own regression checks.

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
  bar. Titles should use the formerly empty right-hand space up to the row's
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
- **flat_rows**: Browse lists, grids and settings. Rows show no grey card or
  black fill; the playing song keeps its glyph with a white title. The bar spans
  the list at the selected row, follows the end bump, and fills only its own
  rectangle on album grid tiles. A touch hides it until the next wheel or centre
  input. Pressed rows still show touch feedback.
- **status_bar**: Check the play state and EQ on the left; Bluetooth/codec, Wi-Fi
  and battery on the right, each following its state, none cut by the corners and each
  group a little in from the glass rather than touching it. The centred clock shows the
  device's local time as `6:14 PM` (no seconds, no leading zero, `12:00 AM` at midnight,
  `12:00 PM` at noon) on every page and under dialogs, and turns over within a second of the
  minute changing. Set the time in System settings and confirm it follows. Let the screen turn
  off for a few minutes and wake it: the clock is current. Volume turns still open the stock
  volume pop-up. Switch Bluetooth, Wi-Fi and PEQ on and off in turn (connect a codec so its label
  shows) at 12:59: the clock stays centred and never overlaps an icon in any combination.
- **home**: Wheel through all seven rows (hard ends) and open each with centre
  and tap; Coverflow is third. Switch the language and confirm the labels follow.
  The first row has room under the status bar and the last row's text and chevron
  clear the bottom corners; labels share one left edge and chevrons one column, with
  the gap before the art kept.
  In Split, the art fills the whole right panel under the status bar with no gap
  or border, cropped evenly and never stretched: try a square cover, a portrait
  folder image and a landscape one. It follows the playing track across track
  changes: embedded art, a folder image, no art (Coverflow thumbnail, then the
  default), Tidal and a stopped player. The list and its selection bar are not
  covered by the art. Switch to Full: the selection bar spans the screen, the chevrons end
  as far from the right edge as the labels start from the left (the last row's is not
  cut), the row takes a tap to its chevron and no art shows; switch back to Split and
  the current cover fills the panel again.
- **chevrons**: `>` shows on every Home row and playlist row, lined up with the
  stock chevrons of categories, artists and albums. None on song lists, grid
  tiles, playlist Import/Export or in multi-select.
- **fast_scroll_letter**: Spin through a list of more than 16 rows: the letter
  shows once the step passes one row, matches the selected title (capitals for
  Latin, other scripts as they are, leading spaces skipped) and clears 400 ms
  after the last fast detent, on a slow detent, a touch or the list end. Short
  lists, Home and settings never show it. Repeat in a virtual song list.
- **now_playing**: The art and "n of m" start 16 pixels in, the text column 12 pixels
  after the art ends 16 pixels from the edge, and the top row, art, page dots, bar and
  times each keep their own space. Check "n of m" against the queue, the album line, and the
  remaining time against the elapsed time and a touch drag. Repeat across track
  changes, a CUE track, an empty queue and a stopped player. Tap and drag the bar
  to seek; set A-B and confirm the markers sit on the bar. Swipe to lyrics and
  info and back; favourite, More and play mode work.
- **scrub**: On Now Playing, centre starts the scrub (white fill). Wheel ticks
  move 5 s, more while spinning, clamped to the track. Turn slowly, pausing about
  half a second between ticks: the bar and both times follow every tick at once and
  playback neither jumps nor stutters until the scrub ends. Centre and Return
  (staying on the page) jump once to the target, as do a touch and 3 s idle; each
  returns the wheel to volume. Centre twice without turning: no jump. A double press
  still turns the screen off, jumping first if the target moved. A track change
  mid-scrub does not seek the new track. Try a CUE track: the jump lands within that
  track. Outside the scrub the wheel changes volume.
- **accent**: In System settings → Display, cycle all four accents with the
  wheel, centre and tap. Each colours the bar, the progress fill, switches,
  ticks, red text and display icons at once; Crimson looks stock; album covers
  keep their colours. Restart and confirm the choice and the Home layout stay.
- **popups**: Delete something: the confirm pop-up starts on Cancel, the wheel
  moves between the two buttons and centre picks one. Under all four accents both
  discs are dark with a clearly legible check and cross, the focused one sits on an
  accent tile with a white frame, and both confirming and cancelling (wheel and tap)
  do what they did. Repeat with the auto
  shut-down warning and Tidal's quality and sort pop-ups. Text-entry pop-ups and
  Update Local Music keep the wheel on the volume.
- **settings**: Open System Setting, Playback Setting, Audio settings, Streaming,
  Display, Language, Wi-Fi (with networks listed) and Bluetooth quality. Four complete
  rows show under an 8-pixel gap, the fourth row's icon and text are not cut by the
  bottom-left corner, icons are 40 pixels and centred with smooth edges (no jagged
  or dark fringes, on black and on the selection bar in each accent), text lines up, and chevrons,
  ticks and switches keep clear of the right edge. Wheel to the end and back (the
  list scrolls whole rows into view, the bar spans each row), tap rows, toggle
  switches, and reopen pages: nothing jumps back to the old 78-pixel rows.
- **quick_settings**: Pull down quick settings. Eight controls in a 4x2 grid; every
  label (Wi-Fi, Buttons lock, USB Storage, Output Options...) starts on the same line
  under its icon, wraps to two lines at most and clears the next row. The brightness
  track is slim, a tap or drag anywhere along it changes the brightness, and the dim and
  bright suns mark its ends. Repeat in another language. Under all four accents, turn
  Wi-Fi, Bluetooth, Buttons lock, gain, output and USB modes on and off: an active control
  is a disc in the accent's colour (silver with a dark symbol in Graphite, a white symbol
  in the others), clearly apart from the grey off disc, and a disabled gain option keeps
  its grey symbol.
- **settings_icons**: Under every accent, System Setting's Network Service and Language,
  Wireless Setting's Wi-Fi, Network Service's DLNA and Display's backlight keep their stock
  red and pink category colours, like the purple and orange icons.
- **coverflow**: Album names are larger and white, artists grey, both clear of the
  corners; long names scroll. Check the Refresh card, "Preparing artwork" with Cancel,
  an empty library, and the track list's last visible row. Then the depth checks in
  [internals](internals.md#device-checks), with music playing.
- **six_screens**: Compare Home (both layouts), Settings, Quick settings, Now Playing,
  Coverflow and a confirm pop-up on the device, with each of the four accents: nothing
  in the bottom rows is cut by the glass, and button glyphs and labels read clearly.
  Only the device shows readability through the rounded glass.
- **boot**: Follow the [boot/resume procedure](#boot). Location
  restores the queue, song and time paused on Home; Track restores the song from
  its beginning. Opening Now Playing does not start audio; Play/Pause resumes it.
  In-Vehicle mode starts playback on Now Playing. With both settings off, nothing
  resumes. A missing restored track still shows its toast on Home.
- **aac**: Normal and iPod: let AirPods or another AAC headset connect by
  itself (taken out of the case) and play; the audio is not choppy.
- **excluded_screens**: Verify Tidal and other online pages, text-entry and
  progress dialogs, and scanning/editing screens keep stock layouts and work.

Emulator tests validate native constructors, stock input gates and the shared
navigation behavior with mocked toolkit services. They do not establish visual
readability, actual touch hit-testing, rendering or playback behavior on hardware.
