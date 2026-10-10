# iPod UI

The Stock and iPod builds share one navigation payload. `--ipod` enables the compact layout
payload helpers and build-time edits in `tools/ipod.py`; Stock receives no
compact executable sites or UI assets. `patch/ipod.json` records the original
asset hashes and full MIPS instructions. The builder also pins the complete stock
ZIP and executable, rejects mismatches, and records every changed asset/site.

AWTK binary UI files contain a four-byte magic, recursive widgets with a 32-byte
type and four signed geometry fields, NUL-separated properties and child/end
markers. Decode/encode must round-trip exactly before editing. Only the assets
pinned in `ipod.json` are accepted: nine local browsing pages, the settings
and streaming pages, Home, the status bar, Now Playing, the quick settings
pull-down, the confirm and volume pop-ups, the equalizer page (its [transition](#transitions) only) and the
theme (`styles/default.bin`). The primary `view_navbar` stays allocated but invisible
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

## Flat rows and selection

The iPod theme uses black surfaces, white titles and subdued secondary text with the stock
multilingual font. The existing 72-pixel browsing pitch, 52-pixel covers and 68-pixel settings
rows remain calibrated to the glass. Settings icons are resized as before and keep their colours;
**Theme: Minimal** greys them, and turns `list_into`'s glyph neutral grey (`MINIMAL_CHEVRON`), as
the image manager loads them (`ringnav_image_add`), so it is visible on both row surfaces.
The pinned style edits in `patch/ipod.json` remove list fills and corners and make pressed
feedback neutral grey. Playing titles keep the separate playing glyph.

In Minimal, wheel selection is consistently off-white (`#EEEEEC`), with no accent. **Theme:
Classic** draws the accent's full-width bar instead and leaves the rows' own (white) ink. The background
hook resolves the selected row; the color hook maps its title to `#171717` and metadata to
`#484848`, preserving alpha. Paint ancestry determines the colors, so no style overrides can
remain on recycled rows or stale scrolling labels. Selected backgrounds stay transparent over
the selection. Touch hides wheel selection until wheel/centre input; the native pressed state
remains visible. The same hooks cover settings, streaming, dialogs, PEQ rows and media browser
chrome. Photos, video, book content, EQ plots and visualizers keep their own drawing.

## Home

Home uses a full-width menu over the current local track's subdued artwork. Artwork is
centre-cropped, with black as the missing-art fallback. Selection is a small white dot and bright
text; other destinations use `#AAAAAA`. There is no selection rectangle or chevron. **Theme:
Classic** lays Home out as before 1.0.1 instead (below).

The seven destinations remain Now Playing, Library, Coverflow, Folder, Rockbox, Streaming and
Settings. Rockbox is visible only when its binary is on the card. Settings opens Playback and
System; Return restores the menu's previous selection. The native stock handlers, translation
keys, full-row tap targets, wheel hard ends and submenu animation remain intact.

`HOME_ROW=39` and `HOME_TOP=8` retain corner clearance. The 6-pixel dot sits at x 25, clear of the
bottom row's corner, and labels start 8 pixels after it (x 39) and end 33 pixels from the right. Both menus
are 375 pixels wide. Long translated labels ellipsize and scroll using the stock font.
The background view paints before the transparent menus, and both menus are clipped to the
window while sliding.

Display settings offers **Home: Artwork / Plain**. Stored `IPOD/HOME=0` (formerly Split) means
Artwork; `1` (formerly Full) means Plain. Plain uses the identical menu on black. No migration
or new preference format is needed. Invalid or absent values still mean zero.

Classic reads the same value as **Home: Split / Full**, and `coverflow_home_layout` moves the
asset's widgets at runtime: Split narrows both menus to `HOME_SPLIT_W` (187) and shows the cover
itself, undimmed, in the right 188×290 panel (`img_homeart` is an `image` for this, fitted to the
cover's proportions and clipped to the panel, the menus clipped left of it; `default_album_home`
without a cover); Full widens the menus to the screen, their rows to `HOME_CLASSIC_ROW` (369), and
hides the art. Labels start at `HOME_CLASSIC_TEXT_X` (33) and end 10 pixels before the chevron,
which rides the accent's selection bar alone. No backdrop is prepared or painted in Classic.

Home and local Now Playing share one backdrop; Spotify has a second. Each is a 375×290 BGRA
bitmap, the size painted below the status bar, so 435,000 pixel bytes a slot and 870,000 for both,
plus bitmap headers. It is prepared once per artwork change from a validated 32-bit decoded
image: the centre crop is area-averaged over black to a 20×16 grid (`BD_GW`, `BD_GH`: about
19 pixels a cell, the blur's size), softened with two [1 2 1] / 4 passes each way, dimmed to
one-fifth and scaled up bilinearly with a 4×4 ordered dither, so it is a soft blur without blocks
or dark-gradient banding. The image manager's pixels are left untouched. A paint is one 1:1 blit;
there is no recurring decode, blur or pixel processing. Allocation or decode failure clears the
previous image and falls back to black.

Home paints it under its menus; Now Playing and Spotify's page paint it over the whole window,
under their children (all transparent but the art), so it shows behind the top row, the page
dots, the bar and the times, and behind the lyrics, info and visualizer pages too. Now Playing
is found by its window name, not the last page opened. The art's rounded corners take the
backdrop's color there instead of black. The reload runs from a paint hook, and AWTK drops what a
paint invalidates when its frame ends, so a reload repaints the screen from a 0 ms timer
afterwards (`home_repaint`); Spotify's page repaints when its backdrop changes. Without that, a
new backdrop reached only the regions something else repainted, and the rest kept the old one or
black until the page was left and entered again.

The local artwork key includes the queue path, usable player-cover type and parsed album tags.
A player cover is accepted only when `g_lastcover_url` matches the current queue path; otherwise
the current album's Coverflow thumbnail is tried. The previous track's player file is never used
as a fallback. `g_playcover_finishflag` remains stock-owned. Home does not load art in Plain mode;
local Now Playing still does. Streaming sources without a matching local cover use black;
Spotify prepares its own backdrop when its foreground cover changes.

## Status bar and clock

`systembar_showface` (`0x52f610`, run by `system_bar_init` and then a 1 s widget
timer) finds each status bar widget with a recursive `widget_lookup` from the bar,
so parents and order are free to change. Every tick it re-shows the volume,
EQ, Bluetooth, SyncLink and Wi-Fi widgets and sets their images and text, but
never their geometry. `system_bar.bin` (iPod) therefore keeps the play state
and EQ in `view_left`, as stock does, and puts Bluetooth/codec, Wi-Fi and the
battery in `view_right`. The volume icon and number and SyncLink move to `x = -200`, where they
draw off-screen. Both groups sit 54 pixels
from the edges (`STATUS_MARGIN`): the 50 where the 16-pixel icons clear the top corners
([Rounded corners](#rounded-corners)) plus 2 (`STATUS_PAD`) so they don't crowd the glass. A new
`label_clock` (`s_scrlabel_white20c`, overridden to 16 px) is centred on the screen. It has the width left in the
narrowest case, 109 pixels at x 133, clear of either group with every icon shown (left 94
pixels, right 133); the build fails if that would be under `CLOCK_MIN` (105). The payload paints
the bar and writes the time into `label_clock` (see
[internals.md](internals.md#status-bar-ipod)); the widest text, `12:59 PM`, is 69 pixels in the
stock font at 16 pixels.

**Codec.** The Bluetooth images are 42-pixel canvases with their ink at the right: the glyph takes
10 pixels, while stock's codec badges take up to 40 (aptX HD). A new badge shows for a second
(`CODEC_MS`), then fades out and the white Bluetooth glyph (`bar_btcon`) fades in at the same place,
150 ms each way; the glyph then stays until the codec changes or Bluetooth goes off.

**Battery.** The Battery setting (see [Display settings](#display-settings)) shows one of three
widgets at the right end, and the layout skips the other two:

- Icon: a clean 16×11 charge-level outline and a 2-pixel nub, drawn in `view_battery`.
- Percent: stock's `label_battery`, 14 px, right-aligned in a 36-pixel slot.
- Icon + Percent: the same charge-level icon with a readable 14 px percentage beside it, in a 56-pixel slot.

Charging fills the icon solid green (`BATT_CHARGE_RGB`); low battery always uses
`BATT_LOW_RGB` (`#FF1448`) under every accent. Saved Battery values keep their existing meanings.
The bar surface is black. Every mode fits with ordinary Bluetooth and Wi-Fi, with at least
4 pixels (`CLOCK_GAP`) before the widest clock text (`BATT_ROOM`, 94 pixels from the margin).
Wide codec badges temporarily show the icon alone until they fade.

The navbar is hidden, as on the local pages, on the settings pages
(`systemset/*`, `playset/*`), `audiosetting_page` and `stream_page`, listed in
`navbar_only` in `ipod.json` with their pinned hashes. Their native
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
- After it, each stock button (x 20, 335 wide) in a visible row spans its row, 375 by 68, so the
  selection bar and the tap target are the whole row. The stock layout skips hidden rows
  (`widget_get_children_for_layout` without `keep_invisible`, `0x5ea1e4`) and leaves them unsized,
  so a hidden row is mapped once it is shown and laid out. Its icon box shrinks to 40 pixels (`SET_ICON`, drawn
  `scale_down`, value 5 in the stock draw type table at `0x9272c0`, which draws a bitmap that
  already fits 1:1; see [Settings icons](#settings-icons)), centred on the row at x 28
  (`SET_ICON_X`). Text starts 12 pixels (`SET_GAP`) after the icon, at x 80, or at x 20
  (`SET_TEXT_X`) without one.
  Trailing images end 24 pixels (`SET_EDGE`) from the right, at x 351; value labels and the text's
  right edge move with them, never nearer the edge than 20. Full-height children fill the row and
  shorter ones keep their centre. A mapped button no longer matches the stock geometry, so a later
  layout leaves it alone.

With these values the text, icons and trailing images of the first and the last visible row clear
the rounded glass (`test/patch.py` runs the Language, Bluetooth quality, System Settings and
Wi-Fi builders and the Display rows, then checks both positions).

### Settings icons

Scaling the 52-pixel artwork down on the device left jagged edges, so the build pre-sizes it
instead. `settings_icons` in `ipod.json` pins the 39 settings icons by hash: `system_*`,
`playset_*`, `display_*`, `wifiset_*`, `netservice_*`, `usb_chargeswitch` and `bt_adjvol`, 52-pixel
RGBA PNGs that only native settings code names (top level and nested pages such as Display,
Wi-Fi, Bluetooth and Network services); no UI asset or other screen uses them. For each one the
iPod build runs ImageMagick (`magick`, else `convert`) with an alpha-weighted Lanczos resize to
40x40, strips metadata and date chunks so the bytes are reproducible, and replaces the file in
place, keeping its inode metadata. The build fails if an input's hash or format differs, or if an
output is not 40-pixel 8-bit RGBA with the same transparency; the manifest records both hashes
and the ImageMagick version under `changed_assets` and `tools`. `test/build.py` checks the
packaged bytes, the sizes, and that each icon's average colour on black and on the Graphite
selection grey matches the stock icon's, and that Minimal's runtime grey (Rec. 709 luma, in 1/256)
matches ImageMagick's `Gray` on black and on the off-white selection. Other 52-pixel images that land in settings rows, such as
Streaming's Tidal logo (`list_tidal`, which the folder root may also use) and the Spotify row's
build-added icon ([internals.md](internals.md#spotify)), keep their bytes and still scale down. The
Spotify row's Now Playing page uses Now Playing's layout (`NP_*`), rounded art included. The Stock build keeps every icon stock. The recolouring of accent-red artwork
(`ringnav_image_add`) works on the decoded bitmap, so it applies at either size.

## Quick settings

The pull-down (`dialog/statusbar_dialog.bin`) covers the whole screen when open. Its eight 60-pixel
controls keep their four columns in two rows from y 20. Every label is the stock 16-pixel white
style (`s_label_white16c`), 80 pixels wide and 40 high (two lines), top-aligned so one- and
two-line labels start on the same line, 6 pixels under its icon and 12 above the next row. The
brightness slider becomes a 6-pixel track (`#3A3A3A`, white fill) in a 48-pixel-high slider that
still takes a tap or drag anywhere on it (`slide_with_bar`), from x 68 to 307. The stock dim and
bright suns stay at its ends, in line with the first and last icon columns. Sizes are `QS_*` in
`tools/ipod.py`. `dialog_statusbar_dialog_init` (`0x4a0d88`) finds every widget by name and
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
scroll within that. The Refresh card uses the album line.
Values are `CF_*` in `patch/offsets.inc`; Stock keeps its track list layout.

## Rounded corners

The panel's glass rounds its corners and hides what is drawn under them. `CORNER_R` in
`tools/ipod.py` (80 pixels) is the calibration knob: the radius, fitted to V5.4I photos and
to stock's 50-pixel status bar margins. `corner_inset(y)` gives the width hidden at each end of
screen row `y`, and `corner_x` adds `CORNER_SLACK` (4). The status bar groups, the Home labels
and Now Playing's top and bottom rows take their insets from it; settings notes moved under the
hidden navbar end their text clear of the top-right corner. With the defaults: status bar 52
pixels plus `STATUS_PAD` (2), the clock at least 57, Home dot 25 and text 39, "3 of 12" 16, Now Playing icons
ending at 353, the bar 21 and the times 46 pixels from the edges. The runtime layouts' values
(`SET_*`, `CF_*`, `CLOCK_EDGE`, `HOME_FULL_ROW` in `patch/offsets.inc`) are checked against the
same calibration by the tests.

`test/build.py` fails an iPod build when any fixed text or icon in a changed asset reaches
under the glass (screen coordinates: the bar at y 0 to 30, windows at 30 to 320, the quick settings
and confirm pop-ups at 0 to 320): a label's font-high band, an image drawn centred at its size, a
slider's bar, else the widget. Backgrounds, tap targets and list rows, which scroll, are not
checked there; `test/patch.py` checks the settings rows in the first and last visible slots,
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

## Transitions

Pages slide with stock's own window animator; the payload adds no animation code. The build sets
`anim_hint` to `SLIDE` (`tools/ipod.py`) on the window of the nine local browsing pages, the
settings and streaming pages and the equalizer page. A hinted page slides in from the right,
pushing the page below it out to the left, and Return reverses that; the status bar is not part
of either page and stays still.

Left immediate: Home (opened once, never closed), Now Playing (its open starts the player, which
can hold the UI thread), Coverflow (its open loads the albums and covers), the dialogs and quick
settings, the queue, More and jump pages over Now Playing, and the pages that keep their stock
assets: Tidal and the other online pages, Wi-Fi transfer and the firmware download. Moving between
folders reloads the folder page in place, so only opening and leaving that page slides. Stock
drops every key and touch while a page slides; none is queued
([internals.md](internals.md#page-transitions-ipod)).

## Chevrons

Stock draws `list_into` on Local Music's categories, the `localclass_page` rows (artists, genres,
composers), the album list and folder rows that are not songs, hidden in multi-select. iPod adds
it, aligned with those (see [internals.md](internals.md#drawing)), only on the `DRILL` windows in
`patch/contexts.inc`: Home and the playlist list, whose rows open their tracks. Classic's Home
draws only the highlighted row's, so it moves with the selection bar; Minimal's Home has none. Tiles narrower
than half the list (playlist Import/Export) get none. The artist page's Albums tab drills but has
no stock chevron or payload row layouter, so it has none.

## Fast-scroll letter

Spinning quickly through a list of more than 16 rows shows the first character of the selected
row's title in a large white letter, centred over the list on a rounded dark square. It appears
once a step moves more than one row, from 300 ms of continuous spin
([internals.md](internals.md#wheel-movement)), and disappears 400 ms after the last such step, or
at once on a slow tick, a touch or the end of the list. Latin letters show in
capitals; leading spaces are skipped, as is a leading "The", "A" or "An" in library lists
([internals.md](internals.md#sorting)), and any other character shows as it is. Home, settings and
other short lists never show it. Values are in `patch/offsets.inc` (`LETTER_*`); see
[internals.md](internals.md#drawing).

## Now Playing

`playing_page.bin` follows Rockbox's iVideo Now Playing in the 375x290 client area, below the
status bar and its clock, with Apple's finish: rounded art, a larger title over grey artist and
album, and a four-pixel progress line:

```
  0 +---------------------------------------------------------+
    | 3 of 12 (16,0 187x40)         fav 203  more 253  mode 303|  icons 50x40
 40 +---------------------------------------------------------+
    |  .-----------.                                          |  slide_view 0,40 375x186
    |  |    art    |  Title   (194,95 165x28, white 22)       |
    |  |   16,50   |  Artist  (194,127 165x20, grey 16)       |
    |  |  166x166  |  Album   (194,151 165x20, grey 16)       |
    |  '-----------'  (corners radius 12)                     |
228 |                     . o .   (page dots)                 |
253 |  (=========================------------------------)   |  line 21,253 333x4
265 |      01:23 (46 80x16)           -02:34 (249 80x16)      |  grey 14
290 +---------------------------------------------------------+
```

The art and the metadata keep 16 pixels from the sides (`NP_MARGIN`) and 12 from each other; the
art is 166 pixels, as large as that leaves while the text column keeps its 165 pixels, and
"3 of 12" starts in line with it. Each band has its own space: the top row, then the art 10
pixels below it, the page dots 12 pixels under the art, the bar with the stock A-B markers
(y 250 to 260) and the quiet time labels at y 265.

The art's corners are rounded at 12 pixels (`NP_ART_RADIUS`), the radius of stock's own
placeholder cover at this size, so real art and the placeholder match. The payload paints them
over the image in the backdrop's color at each corner (black without one), with an anti-aliased
edge pixel. The title is 22 pixels
white (`NP_TITLE_PX`); the artist is `#CCCCCC` (`NP_ARTIST_RGB`), while the album, "3 of 12"
and both times remain `#AAAAAA`. Spotify uses the same hierarchy in the iPod build; Stock
keeps its existing artist color. Long lines scroll, as stock.

The art, title, artist and album are the slide_view's first page, so a swipe replaces all of them
with the stock lyrics or info page. Those keep their stock 225-pixel column, centred: stock creates
each lyric line 225 pixels wide. The play/pause overlay has zero opacity, retaining its original gesture target without
a transport glyph; stock may update its visibility without making it appear. The loading
spinner stays centred on the artwork. The on-screen Return icon moves off-screen, as on the pages whose navbars are
hidden; the hardware Return does the same. Favourite, More and the play mode icon keep their stock
images and handlers in the top row.

The bar is a four-pixel plain-colour line inside the original 30-pixel seek target: a `#1C1C1C` track
(`TRACK_COLOR`) and an off-white `MINIMAL_FILL` fill, with no thumb. **Theme: Classic** makes it an
8-pixel capsule (`NP_BAR_CLASSIC`; `bar_size` and `round_radius` set on the slider at runtime,
`np_theme`) filled in the accent's light tone (Graphite `#6E6E6E`, 3.3:1; see [Display
settings](#display-settings)), shows stock's play/pause glyph on the art again, and paints no
backdrop. Spotify's bar follows the same theme.
The asset holds Graphite's; `ringnav_playing` sets the current accent's. Tap or drag anywhere on it to seek, as stock. The elapsed time
is stock's label; the remaining time replaces stock's total. Sizes are `NP_*` constants in
`tools/ipod.py`; see [internals.md](internals.md#now-playing-ipod).

**Scrub.** A double press of the centre button starts scrubbing, as on an iPod classic, and the bar fill turns white
while it lasts. Each wheel tick moves 5 seconds, times a ramp of one more step per 100 ms of spin
(up to 40 seconds a tick; the lists' gentler ramp and overshoot filter do not apply), within the
track. Both times and the bar follow the target at once;
the track jumps there once, when the scrub ends. A press of the centre button confirms it at once
and leaves the screen on (a double press does too), as do Return, a touch and
3 seconds without a tick, and each gives the wheel back to the volume; Return then stays on the
page. Ending without having moved the target does not seek. Outside a scrub a single press turns
the screen off, as on every other page. The jump is stock's key seek, which can pause the player briefly, but only once, when the
scrub ends, instead of after each pause between ticks. Values are `SCRUB_*` in
`patch/offsets.inc`; see [internals.md](internals.md#scrub-ipod).

The top row's text and icons, the bar's ends and the times keep clear of the corners
([Rounded corners](#rounded-corners)).

**Lyrics.** Stock already highlights the current line and scrolls to keep it in view. On the
lyrics page, while the track has lyrics, the wheel scrolls them a line (25 pixels, `LYRIC_STEP`)
per tick instead of changing the volume or scrubbing; a scrub under way ends first, as any other end
does. Both times, the bar and the highlight wait meanwhile, and 3 seconds (`SCRUB_MS`) after the
last tick, or at a touch, the page follows the current line again; see
[internals.md](internals.md#scrub-ipod).

### Visualizer

The slide_view gains a fourth page, after the art, lyrics and info pages, and the page dots a fourth
dot. It shows the music as heard, EQ included, in one of four styles on black, tinted with the
accent's light tone; a tap moves to the next, saved as `IPOD/VIS` in `config.ini`, and its name shows
at the bottom for a second and a half:

| Style            | After                     | Drawing                                                                                                                                      |
| ---------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **Spectrum**     | Rockbox FFT, log bars     | 32 capsule bars, from a dark shade of the accent to a bright tint with height, a cap on each peak that holds, then falls; a faint reflection |
| **Oscilloscope** | Rockbox Oscilloscope      | The left channel in the accent with a glow, the right a faint accent line; it starts on a rising zero crossing, so the wave stands still     |
| **VU Meters**    | Rockbox VU Meter (analog) | Left and right needles over an arc from -20 to +3 VU, heavier and brighter past 0, with 300 ms ballistics and a peak LED                     |
| **Halo**         | Apple's radial spectrum   | 64 mirrored bars around Now Playing's art in a circle, turning slowly, the bass pulsing the ring                                             |

Everything is anti-aliased vector drawing (AWTK's vgcanvas) within the 375x186 page: 16-pixel side
margins (`NP_MARGIN`), labels in the stock grey `#AAAAAA`. It animates at `VIS_FPS` only while the
page shows with the screen on, and comes to rest when playback pauses. Tunables are `VIS_*` in
`patch/offsets.inc`; `VIS_LATENCY_MS` sets how far the picture runs behind the decoder, to match
what you hear. See [internals.md](internals.md#visualizer-ipod).

## Pop-ups

The confirm and choice dialogs in `patch/contexts.inc` (flag `BUTTONS`) have no list: their buttons
sit directly in the dialog. For those, the dialog itself is the navigation surface, a kind that
never scrolls, and its clickable descendants are the rows in UI order. The wheel moves between
them with hard ends, Centre clicks the selected one after the usual double-press window, and the
bar is drawn in the dialog's background: the button's own rectangle for a button narrower than half
the dialog (the confirm pair), the full width otherwise. A new dialog starts on its first button,
Cancel on the confirm pair.

The confirm pair sits symmetrically, each 80-pixel tile centred in its half of the screen (x 53
and 242). Its stock discs are Shanling red with white glyphs, which the red-tone mapping would
turn light (Graphite's silver would leave the white check at 1.4:1), so the shared image hook
gives `confirm_ok`, `confirm_cancel` and their pressed images a dark surface under every
accent, Crimson included: the same red-blend mapping with `CONFIRM_SURFACE` (`#2B2B2B`) as the
tone, so the OK disc is `#2B2B2B` and Cancel's lighter tint `#595959`, while the glyphs stay
white and near white (`#E5E5E5`): 14.2:1 and 5.6:1. Every confirm prompt uses these images through
`s_img_confirmok`/`s_img_confirmcancel`, so all are covered. The wheel's focus is the off-white tile
behind the dark disc, with a two-pixel white frame. Callbacks, actions and the
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

The iPod build starts on Home with the remembered queue and track restored paused; In-Vehicle mode
keeps the stock start on Now Playing. See [internals.md](internals.md#boot-resume-ipod).

## Display settings

`systemset_display_page_init` (`0x4c1d04`) destroys the children of `scroll_view_display` and
builds three rows with `0x4c19bc`: a `list_item_create(view, 0, 0, 0, 0)` in `s_listitem_black`
(the list view lays it out 78 pixels high), holding a `button_create(item, 20, 0, 335, 70)` in
`s_btn_listitem` with a click handler, and in it a 52-pixel icon at x 10, a
`s_scrlabel_white24l` `hscroll_label` at (72, 0, 210, 70) and `list_into` at x 282. The rows
show no value; each opens a sub-page (iPod's [settings rows](#settings) then lay them out 68
pixels high). iPod runs the stock init, then adds four rows the same way: "Theme: Minimal" and
"Accent: Graphite" with the System settings Display icon (`system_display`), "Home: Artwork" with Play settings' cover
mode icon (`playset_covermode`), "Battery: Icon" (Icon, Percent, Icon + Percent; see
[Status bar and clock](#status-bar-and-clock)) with the power manager icon
(`system_powermanager`), all among the [settings icons](#settings-icons)
the build pre-sizes. The value is in the label (260 pixels wide, to where the chevron ends) and there is no
chevron, since Centre or a tap changes them in place.
Both variants also append **Boot to: Rockbox / Q2-Pod** to System settings when Rockbox is present; see [Boot](boot.md#rockbox).
The page is `CTX_FIXED`, so the wheel walks onto them like the stock rows.

A change is saved at once with the stock `write_int_config(value, "IPOD", key)` (`0x4f3f4c`):
`sprintf("%d")`, then `toolsWriteConfig("/mnt/data/config.ini", section, key, text)`, which
rewrites the key or appends `[IPOD]` with it (`"[%s]\n%s=%s\n"`). The keys are `ACCENT`, `HOME`, `BATTERY` and `THEME`. The values are read once,
on the payload's first use (after stock `config_init`: `application_init` runs `platform_init`, which
calls it, before it opens any window), with `toolsReadConfig` (`0x5bd464`), in the order stock `config_init`
calls it: `(path, section, key, out, default)`. It reads the file line by line
(`strcasecmp` on the section and the key), copies the trimmed value to `out` and returns 1; a
missing key copies the default and returns -1. The default must not be null (stock reads its
first byte). The payload passes `"0"`, so a missing or unreadable entry, or any value that is not
one valid digit, is Graphite, Artwork, Icon and Minimal: a card from 1.0.1 or earlier, which has
no `THEME`, keeps 1.0.1's look.

| Accent | Progress / active-control light tone | Red text / marks |
| --- | --- | --- |
| Graphite (0, default) | `#6E6E6E` | `#D8D8D8` |
| Crimson (1) | `#EB2F56` | stock `#FF1448` |
| Tidal (2) | `#30929B` | `#30929B` |
| Champagne (3) | `#9A8446` | `#9A8446` |

Existing accent preference values and the red-tone mapping stay compatible; greys and artwork
remain unchanged by the live accent mapper. See [internals.md](internals.md#accent) for the mapping.

Now Playing uses 24 px monochrome control glyphs on 28 px canvases inside the existing touch targets. Favourite keeps its outline/filled states; inactive dots are muted. Artwork, scrolling metadata and playback controls retain their existing behavior.

### Theme

**Theme: Minimal** (`THEME=0`, the default) is the look described above. **Theme: Classic**
(`1`) is the iPod look before 1.0.1, drawn at runtime over the same assets: the accent's
full-width selection bar under white text, Home's Split/Full layout with the cover beside the menu
and the chevron on its bar, coloured settings icons and the stock `list_into`, a `#242424` status
bar (`BAR_CLASSIC`), and Now Playing's 8-pixel capsule and play/pause glyph without a backdrop.

Minimal has no accent: the Accent row hides (the list's layout skips a hidden row, so it leaves
no gap) and the stored accent is kept for Classic. Its drawing takes Graphite's greys,
whatever `ACCENT` holds, and its own fills (the progress bars, Spotify's, the PEQ curve and the
visualizer) are `MINIMAL_FILL`, white on the dark track; a scrub's fill is pure white. In Classic
the Accent row follows Theme and every accent applies as before.

A change applies at once, as Accent does: the image cache is dropped and the screen repaints
(icons and chevrons reload in the new theme's colours), Home re-lays its menus and art, an open
Now Playing gets its bar and glyph, and the Display page shows or hides the Accent row and renames
the Home row. Nothing needs a restart.

What Classic does not restore: the pinned theme edit of `s_btn_listitem`'s pressed colour
(`#3D1920` to `#333333`), so a touched row flashes grey rather than an accent tint, and the
status bar asset's own background (`#000000`, not `#161616`), which the payload's fill covers.

## Review and device acceptance

The [review sheets](ui/sudo/README.md) are native-size **composed previews**, not firmware captures.
Host and MIPS checks cover geometry, clipping, cached dimming, selection contrast, recycled rows,
preferences, input and packaging. They do not establish panel readability or rendering speed.
Before release, check the real Q2 with bright/dark/missing covers, long multilingual labels,
all accents, both themes, Artwork/Plain and Split/Full, Rockbox present/absent, paused playback,
seeking and streaming. Switch Theme with Now Playing and Spotify open underneath.
Confirm wheel and touch behavior, transitions, frame responsiveness and the rounded-glass edges.
