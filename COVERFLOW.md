# Coverflow: Home card with its own album index

## Context
Add a Coverflow card after Local Music on the Home carousel, in both variants. It browses tagged albums on SD and USB from its own index at `/mnt/data/coverflow.db`, and the stock Local Songs DB is left alone. The user chose the **stock `slide_menu`** renderer: neighbours are scaled and faded, with no tilt or reflection. That choice reuses the Home carousel's wheel, swipe, centre and animation handling, and the ringnav code and tests that already cover it. Tilt and reflection can be added later as a paint hook.

## Status: deferred (V4.5 audit gate was NO-GO)
The §0 audit (2026-09-28) found that the threading model below is unsafe as written. V4.5 shipped without Coverflow.

**Blocker: TagLib.** Stock calls `toolsGetMusicInfo` from the UI thread without holding any mutex, for example on every track change via `player_get_id3info`. libtag_c's `strdup`'d strings live in one global, unlocked `std::list`, and `taglib_tag_free_strings()` frees all of it. A scan pthread reading tags concurrently with the UI thread would therefore corrupt the heap. Holding `parse_cover_mutex` does not prevent this.

**Blocker: embedded art.** `toolsGetAlbumCover` writes `/tmp/.tmp_picture`. `player_parsecover_thd` calls it under `g_playcover_mutex` @0xa39c18 only, not `parse_cover_mutex`.

Amendments that would make it GO:
- **Tags on the UI thread only.** The pthread only walks directories and writes SQL. `toolsGetMusicInfo` runs in small `timer_add`/`idle_add` batches on the UI thread. The remaining exposure is to stock worker threads (`batch_add_file`, `importPlayList`, and the stock scan), which already race the UI thread in stock.
- **Embedded art under both mutexes.** Take `parse_cover_mutex` then `g_playcover_mutex`, one short call at a time. Stock never nests the two, and 0x524f20 takes `parse_cover_mutex` on the UI thread.
- **Folder art.** `toolsThumbSpecCover` (`cover.jpg`/`folder.jpg`) is fine from the pthread under `parse_cover_mutex` alone, because it doesn't use `/tmp/.tmp_picture`.
- Alternatively, drop embedded art and use only folder art plus the placeholder.

**Card icon (decided):** reuse the Local Music card's own 190×190 image, so the only visible difference is the label "Coverflow". `album_covermode.png` is only 50×50 and would look tiny next to the 190×190 `menu_*` icons. No new assets are needed.

## Stock facts (audited 2026-09-28, V1.32 pinned)
- **Home:**
  - `home_page_init(win, ctx)` @0x523c84, prologue `50001c3c3c309c2721e09903`, 1028 bytes.
  - Returns 0x10 if `win` is NULL, and returns 0 early (nothing bound) if `strlen(g_product_sncode) != 14`. A wrapper calls stock, then binds its card regardless of the return value.
  - It also runs memory-play: `memeory_startplayer`, then `navigator_to_with_context("playing_page", …)`.
  - Clicks are bound by `widget_foreach(win, 0x5239b4, win)`. Visitor 0x5239b4 is static, prologue `50001c3c0c339c2721e09903`, 720 bytes. It matches `widget->name` (+0x10):
    - `img_*` names get `widget_on(EVT_CLICK 0x10c, …)`.
    - `label_*` names get `widget_set_tr_text`.
    - Unknown names are ignored, and nothing assumes exactly 6 cards.
  - **The click lives on the `img_*` image, not `btn_*`**, so bind `widget_lookup(win, "img_coverflow", 1)`. `label_coverflow` gets no translation, so literal text is fine.
- **Tags:**
  - `toolsGetMusicInfo(int want_props, MusicInfo *out, const char *path)` @0x5c5f40, prologue `46001c3c800d9c2721e09903`, 1632 bytes.
  - Always returns 1, even if `taglib_file_new` fails, so the caller must zero `out` first (stock memsets 0x698 bytes).
  - Forces `want_props` to 0 for `.mp3/.wma/.aac/.dff/.dsf/.iso`, and takes no lock.
  - All strings are inline arrays (after `toolsFixId3ErrorCode`), so the caller owns nothing. Layout:

    | Offset | Field | Notes |
    |---|---|---|
    | +0x000 | album[256] | |
    | +0x100 | artist[256] | |
    | +0x200 | genre | written after title, so a genre over 128 bytes clobbers title |
    | +0x280 | title | |
    | +0x480 | composer | |
    | +0x580 | album_artist | |
    | +0x680 | year | |
    | +0x684 | disc | `track>>16` |
    | +0x688 | track | `track&0xffff` |
    | +0x68c | flags | bits, mqa<<8 |
    | +0x690 | samplerate | |
- **TagLib callers by thread.** Direct TagLib is used only inside `toolsGetMusicInfo` and `toolsGetAlbumCover`.

  | Thread | Callers |
  |---|---|
  | UI thread | `player_get_id3info` ← `player_mainscheduling`, `player_start`, `player_change_music`, `player_play_pause`, `add_playrecord` |
  | UI timer | `notifyPlayInfo` |
  | Worker `tk_thread`s | `batch_add_file` (entries 0x4a86c0 and 0x4b1c34), `importPlayList` |
  | synclink / DLNA | synclink and DLNA handlers |
  | Stock scan | thread handle 0xa271d8: `wait_scan` → `scanAllMusicFile` → `toolsLoadAllFile` → 0x5c73e4 |

  None of these hold a mutex.
- **Art:**
  - **`toolsThumbSpecCover(src, dst, w, h)`** @0x5c4550, prologue `46001c3c70279c2721e09903`, 264 bytes.
    - `toolsGetPictureInfo` type 1 (≤1 MB) goes to 0x5b83e8; type 2 (≤6 MB) goes to 0x5b891c. Anything else returns 0.
    - Doesn't use `/tmp/.tmp_picture`.
  - **`toolsGetAlbumCover(audio, dst, w, h)`** @0x5c4444, prologue `46001c3c7c289c2721e09903`, 268 bytes.
    - Goes through `taglib_album_picture` → a hard-coded `/tmp/.tmp_picture` → thumbnail helper, then `remove`s the temp file.
    - Returns 1 on success and 0 on failure.
  - **Locks:**
    - `parse_albumcovertask_thd` and the UI-thread 0x524f20 hold `parse_cover_mutex` @0xa37cb8.
    - `player_parsecover_thd` (0x512fe0) holds only `g_playcover_mutex` @0xa39c18.
  - Display pattern: `"file://"+path` → `widget_load_image` (about 0x88-byte bitmap on the stack) → `image_base_set_image` → `widget_unload_image`.
- **Play:**
  - **`stSongInfo` type:** 0x58 bytes. init 0x5b2e0c, copy **0x5b3b1c** (prologue `47001c3ca4319c2721e09903`, 1156 bytes), destroy 0x5b32b0.
    - +0x04…+0x2c are 11 heap `char *` fields that are deep-copied.
    - +0x8 is the name and +0xc is the full path, both malloc'd.
    - +0x34 is `d_type`; 8 means a file.
    - +0x48 and +0x4c are cue flags and must be 0.
  - **Building the deque:** use `_deque_push_back(dq, &elem)`. The deque owns its copies. The pusher frees its local element with `toolsFreeStSongInfo` @0x5c01b8.
  - **Handing off:** the ctx is `{void *dq; int idx; int classType; int mode}`, where mode 2 plays and 3 loads paused. `navigator_to_with_context("playing_page", &ctx)` runs `playing_page_init` @0x52ca88, then `player_start` @0x515e38, then `mclLoadPlayList` synchronously (`deque_assign` into `mcl_pdeqplaylist` @0xa269a4). The caller can `deque_destroy` right after.
  - **The stock album row (0x4a8974) re-queries the DB** via `player_load_songlist`, so it's the wrong model. **Model this on folder play** (`startPlayFolderSong`): `{dq, idx, 1, 2}`.
  - **classType 1 with arbitrary paths:**
    - Tags come via `toolsGetMusicInfo(elem+0xc)`, and the queue page lists `mcl_pdeqplaylist`. Both are safe.
    - Memory-play reloads the last track's *parent folder* (`toolsLoadDirectory`). Album order is lost, but nothing crashes.
    - Caveat: `mclSetPlayM3uFlag(g_m3u_path[0] != 0)`. If the user last left Folder view inside an m3u, auto-advance changes.
    - classType 0 makes memory-play a silent no-op. Values 0xf001–0xf00b are stock-DB queries and must not be used.
- **SQLite:** the demo imports `sqlite3_open/exec/close/free` (GOT UND). `exec` with a callback is enough.
- **libc imports:**
  - Present: `pthread_create/join`, `pthread_mutex_lock/unlock`, `rename`, `unlink`, `access`, `mkdir`, `opendir/closedir`, `readdir` (32-bit; **no `readdir64`**), `strdup`, `strcasecmp`, `strrchr`.
  - **No `statvfs`:** use `statfs`. The MIPS o32 field order is `f_type, f_bsize, f_frsize, f_blocks, f_bfree, f_files, f_ffree, f_bavail`.
  - **No `stat`:** use `__xstat`/`__xstat64`/`__lxstat` with version 3.
- **Runtime slide_menu:**
  - Use `widget_factory_create_widget(widget_factory(), "slide_menu", parent, x, y, w, h)`. Both functions are exported (0x666f04, 0x666c68).
  - A bare `widget_create` with `g_slide_menu_vtable` (0x99cce0) skips the defaults that static `slide_menu_create` (0x5f383c) sets.
  - `slide_menu_set_value` @0x5f5228 and `slide_menu_scroll_to_next`/`_prev` @0x5f371c/0x5f3514 are exported.
- **Scanner rules:**
  - 0x5c38c8 is the stock **per-directory lister** (static, 2940 bytes, prologue `46001c3cf8339c2721e09903`), not an extension helper. It shares scanner globals, so don't call it.
    - It uses `lstat` when `d_type == 0`, so symlinks are never treated as directories.
    - It skips `._*` files.
  - **Extension list:** 0x778d70 (273 bytes), matched by `strstr` on the last 4–5 characters. Case variants are enumerated explicitly: `.mp3 .wav .wma .ape .flac .aiff .aif .m4a .aac .dff .dsf .ogg .dts .iso .mp2 .ac3 .opus .tak`, each in three casings. 0x767160 is the same list without ISO, used only by `parse_category_list_response`. Copy 0x778d70 without the ISO entries.
  - **Skipped directory names:** `.`, `..`, `lost+found`, `System Volume Information`, `RECYCLER`, `$RECYCLE.BIN`, `.LOST.DIR`, `.fseventsd`, `.Spotlight-V100`, `.Trashes`. Also the exact paths `/mnt/mmc/Android/data` and `/mnt/usb/Android/data`.
- **Stock scan:** it runs only inside the modal update dialog, with thread handle 0xa271d8, and walks only `/mnt/mmc`.
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
- Per file (tag reads on the UI thread in timer batches; see Status): `toolsGetMusicInfo` → `INSERT` into `tracks(path, title, artist, album_artist, album, disc, track, folder)` in `coverflow.db.tmp`, inside one transaction. SQL strings use a small quote helper (`'` → `''`).
- Grouping is one SQL statement: `albums` = `GROUP BY coalesce(nullif(album_artist,''), artist), coalesce(nullif(album,''), folder)`. A missing album uses the folder as its identity and folder name as its display name. Ordering is done in SQL: albums by artist then title (NOCASE); tracks by disc, track, then filename.
- Artwork per album: try `cover.jpg`, then `folder.jpg` (`toolsThumbSpecCover`), then the first track's embedded art (`toolsGetAlbumCover` under `parse_cover_mutex` then `g_playcover_mutex`). Output is `/mnt/data/coverflow-art/<fnv(source path+size+mtime)>.jpg` at 160×160, and an existing file is reused. Skip thumbnails when `/mnt/data` free space is below a named `ART_MIN_FREE_MB` (`statfs`; `statvfs` isn't imported). A failed thumbnail stores an empty art path, so the album still shows with a placeholder.
- Finish: set `PRAGMA user_version=1`, commit, close, then `rename(tmp, coverflow.db)`. On cancel or error, `unlink(tmp)`; the old DB is untouched.
- Progress (files and albums counted) and the cancel flag are volatile ints in `.scratch`.

**Page** (UI thread):
- The card click creates a runtime window with `window_create`, named `coverflow_page`.
- Opening with no valid DB (missing, or `user_version` ≠ 1) starts a scan. The page then shows "Scanning… N files" and a Cancel row, with a 250 ms `timer_add` poll.
- Covers screen:
  - A `slide_menu`, built with `widget_factory_create_widget(widget_factory(), "slide_menu", …)`, holding one child per album. Each child is an image (stock `default_bigcover` placeholder) plus album/artist labels.
  - The last card is **Refresh library**.
  - On value change, set real art only for index ±3 and clear the rest, so only nearby covers stay decoded.
  - `ponytail:` one child per album; if large libraries lag on hardware, virtualize to a recycled window of children.
- Tracks screen: a scroll_view row list reusing the `peq_ui.c` `row()` pattern. Clicking a track checks `access(path)`; if it's missing it shows "Storage unavailable". Otherwise it builds the deque from the album's rows and hands off to `playing_page` as stock folder play does (`{dq, idx, 1, 2}`).
- Return (`EVT_KEY_UP` 170, like the PEQ `keyup`):
  - tracks → covers, restoring `slide_menu` value to the saved album index
  - covers → `navigator_back_to_home`
  - scanning → cancel
- On `EVT_DESTROY`: cancel and `pthread_join` (bounded by one file's work), remove the timer, free album arrays, and clear the page pointers.

### 2. Home card and hook
- Edit `home_page.bin` in `tools/compact.py` for **both** variants. Normal currently patches only `ARTIST_PAGE`, so the builder loop needs `home_page` added. Clone `btn_localmusic` → `btn_coverflow` / `img_coverflow` / `label_coverflow` at index 2. Keep the Local Music card's own image and change only the label text to the literal "Coverflow". No new image files are added.
- Add a `home_page_init` entry to `DEMO_HOOKS` in `tools/peq.py` (checked prologue), plus a trampoline in `patch/trampoline.S`. Our init calls the stock one, then `widget_lookup(win, "img_coverflow", 1)` + `widget_on(EVT_CLICK, coverflow_open)`. The click must go on the image, as stock does.
- `patch/contexts.inc`: add `{ "coverflow_page", CTX_DYNAMIC, 0 }`. In `tools/build.py`, exempt a `PAYLOAD_WINDOWS = {'coverflow_page'}` set from the rootfs window-name check.
- Also in `tools/build.py`:
  - add the new libc/UI imports (`pthread_create/join`, `pthread_mutex_lock/unlock`, `rename`, `statfs`, `__lxstat`, `sqlite3_*`, window/image/deque, `navigator_to_with_context`), using the existing `FUNCTIONS`/`LIBC`/`PRIVATE_FUNCTIONS` tables
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
