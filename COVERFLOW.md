# Coverflow: Home card with its own album index

## Context
Add a Coverflow card after Local Music on the Home carousel, in both variants. It browses tagged albums on SD and USB from its own index at `/mnt/data/coverflow.db`, and the stock Local Songs DB is left alone. The user chose the **stock `slide_menu`** renderer: neighbours are scaled and faded, with no tilt or reflection. That choice reuses the Home carousel's wheel, swipe, centre and animation handling, and the ringnav code and tests that already cover it. Tilt and reflection can be added later as a paint hook.

## Stock facts (audited, V1.32 pinned)
- **Home:** `home_page_init` @0x523c84 (prologue `50001c3c3c309c2721e09903`). The cards are 6 `button` children of `slide_menu` in `ui/home_page.bin`, and no code assumes there are exactly 6. A button's click is bound by name; unknown names are ignored.
- **Tags:** `toolsGetMusicInfo` @0x5c5f40 is what the stock scanner uses. It covers the Shanling 2-arg `taglib_file_new`, ID3 encoding repair, and `track>>16` / `cd_num` packing. `taglib_tag_free_strings()` frees a global list, so it is not thread-safe.
- **Art:**
  - `toolsThumbSpecCover(src, dst, w, h)` @0x5c4550 handles image files: JPEG/PNG to a resized JPEG.
  - `toolsGetAlbumCover(audio, dst, w, h)` @0x5c4444 handles embedded art. It goes through the shared `/tmp/.tmp_picture` and needs `parse_cover_mutex` @0xa37cb8.
  - Display pattern: `"file://"+path` → `widget_load_image` → `image_base_set_image` → `widget_unload_image`.
- **Play:** build a `stSongInfo` deque (`_create_deque("stSongInfo")`, `deque_init`; element 0x58 bytes, +0xc = path, copy fn 0x5b3b1c), then `navigator_to_with_context("playing_page", &{dq, idx, classType, 2})`, then `deque_destroy`. This is the stock album-row flow at 0x4a8974. Folder play uses classType 1.
- **SQLite:** demo imports only `open/exec/close/free`. `exec` with a callback is enough, so no private library offsets are needed.
- **Scanner rules:** the extension list at 0x767160 (via helper 0x5c38c8) and the stock skip-dir list (`$RECYCLE.BIN`, `lost+found`, `System Volume Information`, `.Spotlight-V100`, `*/Android/data`). Mounts are `/mnt/mmc` and `/mnt/usb`.
- **Stock scan:** it runs only inside the modal update dialog, with thread handle 0xa271d8. `pthread_create` and `rename` are imported.
- **Payload:** 33.7 KB in a 60 KB window below scratch at 0xb0f000.

## Implementation

### 0. Audit gate (before binding; findings go in `docs/internals.md`)
Disassemble and pin (prologue bytes and size, like DEMO_HOOKS/PRIVATE_FUNCTIONS) each of the following:
- the `toolsGetMusicInfo` output struct and its thread use
- the helper at 0x5c38c8 (extension check)
- the `stSongInfo` fields that 0x5b3b1c copies
- `toolsThumbSpecCover` and `toolsGetAlbumCover`

Also:
- List every stock TagLib caller and its thread. Our TagLib/art calls hold `parse_cover_mutex`. If a stock caller outside that mutex can run concurrently, report it and stop rather than guess.
- Confirm that classType 1 with an arbitrary path list survives queue refresh and memory-play. If it doesn't, use the class value that does.

### 1. `patch/coverflow.c` (new; the only new source file)
**Scan thread** (pthread; it never touches AWTK):
- Recursively walk `/mnt/mmc` and `/mnt/usb` (skipped if absent) using stock extension/skip rules. Recurse only into `DT_DIR` (symlinks are `DT_LNK`, so they're skipped), with bounded depth and path length.
- Per file: `toolsGetMusicInfo` → `INSERT` into `tracks(path, title, artist, album_artist, album, disc, track, folder)` in `coverflow.db.tmp`, inside one transaction. SQL strings use a small quote helper (`'` → `''`).
- Grouping is one SQL statement: `albums` = `GROUP BY coalesce(nullif(album_artist,''), artist), coalesce(nullif(album,''), folder)`. A missing album uses the folder as its identity and folder name as its display name. Ordering is done in SQL: albums by artist then title (NOCASE); tracks by disc, track, then filename.
- Artwork per album: try `cover.jpg`, then `folder.jpg` (`toolsThumbSpecCover`), then the first track's embedded art (`toolsGetAlbumCover` under the mutex). Output is `/mnt/data/coverflow-art/<fnv(source path+size+mtime)>.jpg` at 160×160, and an existing file is reused. Skip thumbnails when `/mnt/data` free space is below a named `ART_MIN_FREE_MB` (statvfs). A failed thumbnail stores an empty art path, so the album still shows with a placeholder.
- Finish: set `PRAGMA user_version=1`, commit, close, then `rename(tmp, coverflow.db)`. On cancel or error, `unlink(tmp)`; the old DB is untouched.
- Progress (files and albums counted) and the cancel flag are volatile ints in `.scratch`.

**Page** (UI thread):
- The card click creates a runtime window with `window_create`, named `coverflow_page`.
- Opening with no valid DB (missing, or `user_version` ≠ 1) starts a scan. The page then shows "Scanning… N files" and a Cancel row, with a 250 ms `timer_add` poll.
- Covers screen:
  - A `slide_menu`, built with `widget_create` + `g_slide_menu_vtable`, holding one child per album. Each child is an image (stock `default_bigcover` placeholder) plus album/artist labels.
  - The last card is **Refresh library**.
  - On value change, set real art only for index ±3 and clear the rest, so only nearby covers stay decoded.
  - `ponytail:` one child per album; if large libraries lag on hardware, virtualize to a recycled window of children.
- Tracks screen: a scroll_view row list reusing the `peq_ui.c` `row()` pattern. Clicking a track checks `access(path)`; if it's missing it shows "Storage unavailable". Otherwise it builds the deque from the album's rows and hands off to `playing_page` as stock does.
- Return (`EVT_KEY_UP` 170, like the PEQ `keyup`):
  - tracks → covers, restoring `slide_menu` value to the saved album index
  - covers → `navigator_back_to_home`
  - scanning → cancel
- On `EVT_DESTROY`: cancel and `pthread_join` (bounded by one file's work), remove the timer, free album arrays, and clear the page pointers.

### 2. Home card and hook
- Edit `home_page.bin` in `tools/compact.py` for **both** variants. Normal currently patches only `ARTIST_PAGE`, so the builder loop needs `home_page` added. Clone `btn_localmusic` → `btn_coverflow` / `img_coverflow` / `label_coverflow` at index 2, with literal label text "Coverflow" and the stock `album_covermode` icon, so no new image files are added.
- Add a `home_page_init` entry to `DEMO_HOOKS` in `tools/peq.py` (checked prologue), plus a trampoline in `patch/trampoline.S`. Our init calls the stock one, then `widget_lookup(win, "btn_coverflow")` + `widget_on(EVT_CLICK, coverflow_open)`.
- `patch/contexts.inc`: add `{ "coverflow_page", CTX_DYNAMIC, 0 }`. In `tools/build.py`, exempt a `PAYLOAD_WINDOWS = {'coverflow_page'}` set from the rootfs window-name check.
- Also in `tools/build.py`:
  - add the new libc/UI imports (`pthread_create/join`, `rename`, `statvfs`, `sqlite3_*`, window/image/deque, `navigator_to_with_context`), using the existing `FUNCTIONS`/`LIBC`/`PRIVATE_FUNCTIONS` tables
  - compile/link `coverflow.c` via `compile_common` and add it to `--undefined`
  - add `patch/coverflow.c` to `source_sha256`
- Keep the payload-overlap, scratch-page and rootfs-size checks unchanged. If the payload crosses 0xb0f000, move `SCRATCH` in both `build.py` and `link.ld` together.

### 3. ringnav routing
- Nothing new is expected. `coverflow_page` is allowlisted, and a non-home `slide_menu` already takes the wheel via `slide_menu_scroll_to_next/prev` and the centre via a synchronous click on the selected child. Tracks are an ordinary scroll_view list.
- Only if a test shows a gap: add the minimal case in `patch/ringnav.c`.

## Validation
- **`tools/test_coverflow.py`** (new, host cc + host libsqlite3 as a test-only library, following the `tools/test_peq.py` pattern). It stubs `toolsGetMusicInfo` from sidecar tag files and stubs the art functions. Cases:
  - nested folders
  - the same album title under different artists
  - a missing album tag grouping by folder
  - disc/track/filename ordering
  - cover.jpg over folder.jpg over embedded art, and missing art showing a placeholder
  - a malformed file skipped while the scan continues
  - cancel mid-scan leaving the old DB byte-identical and no tmp file
  - missing `/mnt/usb` and `/mnt/mmc`
  - a symlinked directory not followed
  - skip dirs
- **`tools/test_patch.py`** (MIPS):
  - Home has 7 cards and index 2 opens `coverflow_page`
  - the existing carousel fast/slow/reversal checks still pass with 7 cards
  - wheel and centre on the coverflow `slide_menu`, including the centre double-press still turning the screen off
  - the track click hands `playing_page` a deque with the right index
  - Return tracks→covers restores the album; Return on covers goes Home
  - destroy removes the timer and joins the thread
- Build normal and compact, then run `test_peq.py`, `test_build.py 'Q2 Firmware V1.32.zip'` (reproducible packages, size) and `test_patch.py` on both outputs.
- Docs: add a README Coverflow section, an internals section with the audit results, and a building-doc line for the new test.

## Final step (user request)
- Run a **ponytail-review subagent** on the full diff, fix its findings, then re-run all the tests above.
