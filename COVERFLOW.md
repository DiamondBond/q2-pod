# Coverflow: Home card over the stock library (PictureFlow model)

## Context

Add a Coverflow card after Local Music on the Home carousel, in both variants. It browses the albums in the **stock Local Music library**, reading it the way Rockbox PictureFlow reads its tagcache database. Coverflow never reads tags itself, so there is no scanner and no `coverflow.db`.

The only thing Coverflow owns is a thumbnail cache. Like PictureFlow's `.pfraw` cache, it is built once on a modal progress screen, and afterwards browsing only loads cached files.

The renderer is the **stock `slide_menu`**: neighbours are scaled and faded, with no tilt or reflection. That reuses the Home carousel's wheel, swipe, centre and animation handling, along with the ringnav code and tests that already cover it. Tilt and reflection can come later as a paint hook.

## Status: planned for V4.6

Implemented in V4.6: `patch/coverflow.c`, the Home card in both variants, `tools/test_coverflow.py` and the Coverflow cases in `tools/test_patch.py`; the §0 audit is in [docs/internals.md](docs/internals.md#coverflow). The card icon is the round-5 PIL pair (`assets/menu_coverflow*.png`, scored 7/10). It is quantised to 32 colours to fit the rootfs budget; since V4.7 the payload is built with `-Oz`, which leaves about 1.2 KB in compact.

The first design, with its own tag scanner and `coverflow.db`, failed the V4.5 audit gate (2026-09-28):

- **TagLib:** stock calls `toolsGetMusicInfo` on the UI thread with no mutex, for example on every track change. libtag_c keeps its strings in one global, unlocked list, so a scan thread reading tags would corrupt the heap.
- **Embedded art:** `toolsGetAlbumCover` writes the shared `/tmp/.tmp_picture`, and `player_parsecover_thd` calls it under `g_playcover_mutex` only.

The redesign avoids both problems:

- **No tag reads:** album and track data come from the stock library queries.
- **Embedded art:** extracted under **both** `parse_cover_mutex` and `g_playcover_mutex`, in that order, one short call at a time. Stock never nests the two.

### How PictureFlow does it (the model)

Source: Rockbox `apps/plugins/pictureflow/pictureflow.c`.

- **Albums** come from Rockbox's tagcache database (`tagcache_search(tag_album / tag_albumartist)`), never from its own tag scan. `check_database()` waits with a "tagcache busy" splash until the DB is initialized and ready.
- **First launch** runs in the foreground with a progress bar and a cancel prompt:
  - `create_album_index()` writes `pictureflow_album.idx`.
  - `create_albumart_cache()` handles one album per step: first track → `search_albumart_files()` (folder image or embedded) → resize → `<mfnv(album,artist)>.pfraw`.
  - Albums without art share `emptyslide.pfraw`.
- **Later launches** load the index. A background thread only loads `.pfraw` files near `center_index` into a 64-slide LRU cache and never reads tags.
- **New music** isn't detected automatically. The cache rebuilds only on a `CACHE_VERSION` change or the user's "Rebuild cache".
- **Tracks** come from a per-album DB query, sorted by disc and track.

### How we map it onto the Q2

| PictureFlow         | Coverflow on the Q2                                                                                                   |
| ------------------- | --------------------------------------------------------------------------------------------------------------------- |
| tagcache database   | the stock Local Music library (§0 finds the query)                                                                    |
| `check_database()`  | if the library is empty or not built, show "Update Local Music first"                                                 |
| `.pfraw` cache      | `/mnt/mmc/.coverflow/<fnv(album_artist,album)>.jpg` at 160×160; an empty file marks "no art" (the placeholder)        |
| modal first build   | a modal progress screen with Cancel; the art pthread touches only files, the two mutexes and volatile counters        |
| manual rebuild only | on open, build only the albums with no cache file, then a **Refresh library** card that clears the cache and rebuilds |

**Card icon.** Try a generated icon first, and fall back to reuse.

1. **Export the stock carousel icons.** They're in `release/assets/default/raw/images/xx/`, one pair per card: `menu_music.png` / `menu_musicdown.png`, `menu_folder`, `menu_playing`, `menu_stream`, `menu_playset`, `menu_sysset`. Each is a 190×190 RGBA PNG, and the `…down` variant is the pressed/selected state.
2. **Generate the new icons with Codex.** Feed the exported icons to the `codex` CLI (installed, 0.157.0) on the user's subscription. Use a top model at high reasoning, e.g. `codex exec -m <best gpt model> -c model_reasoning_effort="xhigh" -i menu_music.png -i menu_musicdown.png -i … "<prompt>"`, and ask it to use its image-generation tool or skill.
   - Output: a new `menu_coverflow.png` + `menu_coverflowdown.png` pair.
   - Motif: a fanned stack of album covers.
   - Match the Shanling set exactly: 190×190 RGBA with a transparent background, the same line weight, palette, glyph size, padding and normal/down styling.
   - If image generation isn't available through Codex, say so and use the fallback.
3. **Check the result.** Verify dimensions, mode and transparency with Python (PIL or `file`). Put the result next to the stock pair and look at it with the Read tool before accepting it.
4. **Add it to the build.** The build adds both PNGs to the rootfs `images/xx/`, and the `btn_coverflow` clone references `menu_coverflow`. Keep the rootfs no larger than stock by running `test_build.py`. Commit the PNGs under `assets/`.

**Fallback:** reuse the Local Music card's own image, so the only visible difference is the label "Coverflow". `album_covermode.png` is only 50×50 and would look tiny next to the 190×190 `menu_*` icons.

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
- **Tags** (why we don't read them):
  - `toolsGetMusicInfo(int want_props, MusicInfo *out, const char *path)` @0x5c5f40, prologue `46001c3c800d9c2721e09903`, 1632 bytes.
  - Always returns 1, even if `taglib_file_new` fails, so the caller must zero `out` first (stock memsets 0x698 bytes).
  - Forces `want_props` to 0 for `.mp3/.wma/.aac/.dff/.dsf/.iso`, and takes no lock.
  - All strings are inline arrays (after `toolsFixId3ErrorCode`), so the caller owns nothing. Layout:

    | Offset | Field        | Notes                                                         |
    | ------ | ------------ | ------------------------------------------------------------- |
    | +0x000 | album[256]   |                                                               |
    | +0x100 | artist[256]  |                                                               |
    | +0x200 | genre        | written after title, so a genre over 128 bytes clobbers title |
    | +0x280 | title        |                                                               |
    | +0x480 | composer     |                                                               |
    | +0x580 | album_artist |                                                               |
    | +0x680 | year         |                                                               |
    | +0x684 | disc         | `track>>16`                                                   |
    | +0x688 | track        | `track&0xffff`                                                |
    | +0x68c | flags        | bits, mqa<<8                                                  |
    | +0x690 | samplerate   |                                                               |

- **TagLib callers by thread.** Direct TagLib is used only inside `toolsGetMusicInfo` and `toolsGetAlbumCover`.

  | Thread              | Callers                                                                                                                      |
  | ------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
  | UI thread           | `player_get_id3info` ← `player_mainscheduling`, `player_start`, `player_change_music`, `player_play_pause`, `add_playrecord` |
  | UI timer            | `notifyPlayInfo`                                                                                                             |
  | Worker `tk_thread`s | `batch_add_file` (entries 0x4a86c0 and 0x4b1c34), `importPlayList`                                                           |
  | synclink / DLNA     | synclink and DLNA handlers                                                                                                   |
  | Stock scan          | thread handle 0xa271d8: `wait_scan` → `scanAllMusicFile` → `toolsLoadAllFile` → 0x5c73e4                                     |

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
    - Memory-play reloads the last track's _parent folder_ (`toolsLoadDirectory`). Album order is lost, but nothing crashes.
    - Caveat: `mclSetPlayM3uFlag(g_m3u_path[0] != 0)`. If the user last left Folder view inside an m3u, auto-advance changes.
    - classType 0 makes memory-play a silent no-op. Values 0xf001–0xf00b are stock-DB queries and must not be used.
- **SQLite:** the demo imports `sqlite3_open/exec/close/free` (GOT UND). These are only needed if §0 chooses a direct read-only query of the stock DB.
- **libc imports:**
  - Present: `pthread_create/join`, `pthread_mutex_lock/unlock`, `rename`, `unlink`, `access`, `mkdir`, `opendir/closedir`, `readdir` (32-bit; **no `readdir64`**), `strdup`, `strcasecmp`, `strrchr`.
  - **No `statvfs`:** use `statfs`. The MIPS o32 field order is `f_type, f_bsize, f_frsize, f_blocks, f_bfree, f_files, f_ffree, f_bavail`.
  - **No `stat`:** use `__xstat`/`__xstat64`/`__lxstat` with version 3.
- **Runtime slide_menu:**
  - Use `widget_factory_create_widget(widget_factory(), "slide_menu", parent, x, y, w, h)`. Both functions are exported (0x666f04, 0x666c68).
  - A bare `widget_create` with `g_slide_menu_vtable` (0x99cce0) skips the defaults that static `slide_menu_create` (0x5f383c) sets.
  - `slide_menu_set_value` @0x5f5228 and `slide_menu_scroll_to_next`/`_prev` @0x5f371c/0x5f3514 are exported.
- **Library queries** (from the V4.5 Queue Menu audit):
  - Album rows live in `*p_deque_showlist` @0xa3849c as stSongInfo records: +0 id (-1/-2 mean unknown), +0x14 album, +0x18 album artist.
  - An album's tracks come from `getMusicByAlbum(rec[0]==-1 ? NULL : rec+0x14)` @0x4ff7d8. Artist→album uses `getMusicByAlbumAndAlbumSonger` @0x4ffc84 or `getMusicByAlbumAndSonger` @0x4ff9b8.
  - These run SQLite plus `algo_sort_if` (stock order) and fill the staging deque `tools_pdeq_directory` @0xa269bc, so snapshot and restore it with `deque_init_copy`/`deque_assign`.
  - They're UI-thread only.
- **Payload:** V4.5 adds the Queue Menu, so re-measure the space left in the 60 KB window below `SCRATCH` before starting.

## Implementation

### 0. Audit gate (findings go in `docs/internals.md`)

Pin every address used, with prologue bytes and size, in the style of `DEMO_HOOKS`/`PRIVATE_FUNCTIONS`.

**How stock builds the Albums list** (class 0xf003):

- Find the function that fills `p_deque_showlist` with album rows.
- Or find the stock DB path and schema, for a direct read-only `sqlite3_exec`.
- Pick whichever needs no private state, and check it's safe while a Local Music page is open underneath (Coverflow is opened from Home, so normally none is).

**Reading the library:**

- How stock detects an empty or unbuilt library, and what "library being rebuilt" looks like (the update dialog is modal, but check anyway). Coverflow refuses in both cases, as `check_database()` does.
- Whether `getMusicByAlbum*` returns stock-ordered tracks for an album row taken from that list, including the unknown-album (-1) and unknown-artist (-2) rows.

**Play class:**

- Prefer the stock album-detail classType (e.g. 0xff10), so memory-play resumes the album.
- Confirm it survives queue refresh and memory-play with the deque we pass.
- Fall back to folder play `{dq, idx, 1, 2}` (see Play above).

**Art:**

- Re-check that no stock path calls `toolsGetAlbumCover` or `toolsThumbSpecCover` outside the two mutexes.
- If one does, drop embedded art (folder art plus placeholder only) rather than guess.

### 1. `patch/coverflow.c` (new; the only new source file)

**Album list** (UI thread, on open):

- Query the stock library (§0) into a `malloc`'d array of `{album, album_artist, first_track_path, id}`.
- Sort as stock's Albums list does.
- Keep the source record fields, so the tracks query can be re-run.

**Art build** (pthread, modal):

- Build on first open, then only for albums that have no cache file.
- Before starting, the UI thread copies each album's first-track path and folder into the job array, so the thread never touches stock deques.
- Per album:
  - `cover.jpg`, then `folder.jpg`, through `toolsThumbSpecCover` under `parse_cover_mutex`.
  - Otherwise embedded art through `toolsGetAlbumCover`, under `parse_cover_mutex` then `g_playcover_mutex`.
  - Write to `…/<fnv>.jpg.tmp`, then `rename`. On failure, write an empty `<fnv>.jpg` marker.
- Skip the build when the card's free space is below a named `ART_MIN_FREE_MB` (`statfs`).
- Progress (albums done) and the cancel flag are volatile ints in `.scratch`.
- Cancel stops after the current album. Finished thumbnails stay, so the next open resumes.

**Page** (UI thread):

- The card click creates a runtime window with `window_create`, named `coverflow_page`.
- If the library is empty, show "Update Local Music first".
- If albums need art, show "Preparing artwork… N/M" and a Cancel row, with a 250 ms `timer_add` poll.
- **Covers screen:**
  - A `slide_menu`, built with `widget_factory_create_widget(widget_factory(), "slide_menu", …)`, holding one child per album.
  - Each child is an image (stock `default_bigcover` placeholder) plus album/artist labels.
  - The last card is **Refresh library**, which deletes the cache files and rebuilds.
  - On value change, set real art only for index ±3 and clear the rest, like PictureFlow's slide cache.
  - `ponytail:` one child per album; if large libraries lag on hardware, virtualize to a recycled window of children.
- **Tracks screen:**
  - `getMusicByAlbum*` on the UI thread, with a snapshot/restore of `tools_pdeq_directory`.
  - Rows use the `peq_ui.c` `row()` pattern.
  - A click checks `access(path)`. If the file is missing, show "Storage unavailable". Otherwise hand the deque to `playing_page` with the §0 class.
- **Return** (`KEY_RETURN` 170, like the PEQ `keyup`):
  - tracks → covers, restoring `slide_menu` to the saved album index
  - covers → `navigator_back_to_home`
  - preparing → cancel, then covers, showing whatever is cached
- **On `EVT_DESTROY`:** cancel and `pthread_join` (bounded by one album's art), remove the timer, free the arrays, and clear the page pointers.

### 2. Home card and hook

- Edit `home_page.bin` in `tools/compact.py` for **both** variants. Normal currently patches only `ARTIST_PAGE`, so the builder loop needs `home_page` added.
- Clone `btn_localmusic` → `btn_coverflow` / `img_coverflow` / `label_coverflow` at index 2. Use the generated `menu_coverflow` icon pair (see Card icon); if generation failed, keep the Local Music image. The label text is the literal "Coverflow".
- Add a `home_page_init` entry to `DEMO_HOOKS` in `tools/peq.py` (checked prologue), plus a trampoline in `patch/trampoline.S`. Our init calls the stock one, then `widget_lookup(win, "img_coverflow", 1)` + `widget_on(EVT_CLICK, coverflow_open)`. The click must go on the image, as stock does.
- In `patch/contexts.inc`, add `{ "coverflow_page", CTX_DYNAMIC, 0 }`. In `tools/build.py`, exempt a `PAYLOAD_WINDOWS = {'coverflow_page'}` set from the rootfs window-name check.
- Also in `tools/build.py`:
  - Add imports through the existing `FUNCTIONS`/`LIBC`/`PRIVATE_FUNCTIONS` tables: `pthread_create/join`, `pthread_mutex_lock/unlock`, `rename`, `unlink`, `statfs`, `__lxstat`, the art functions, `getMusicByAlbum*`, window/image/deque functions, and `navigator_to_with_context`. Reuse anything the Queue Menu already imports.
  - Compile and link `coverflow.c` via `compile_common`, and add it to `--undefined`.
  - Add `patch/coverflow.c` to `source_sha256`.
- Keep the payload-overlap, scratch-page and rootfs-size checks unchanged. If the payload crosses `SCRATCH`, move it in both `build.py` and `link.ld` together.

### 3. ringnav routing

- Nothing new is expected. `coverflow_page` is allowlisted, and a non-home `slide_menu` already takes the wheel via `slide_menu_scroll_to_next/prev` and the centre via a synchronous click on the selected child. Tracks are an ordinary scroll_view list.
- The Queue Menu's hold-Play should stay stock (unsupported) on `coverflow_page` unless supporting it is trivial.
- Only if a test shows a gap, add the minimal case in `patch/ringnav.c`.

## Validation

- **Card icon:** if it's generated, both PNGs are 190×190 RGBA with transparent corners, look right next to the stock `menu_*` pair, and the rootfs is still no larger than stock.
- **`tools/test_coverflow.py`** (new; host cc, following the `tools/test_peq.py` pattern). It stubs the library query and the art functions, and records mutex order. Cases:
  - cover.jpg beats folder.jpg, which beats embedded art
  - missing art writes the empty marker, so the placeholder shows and the album isn't retried
  - embedded art takes both mutexes in order, and folder art takes only the parse mutex
  - on a later open, only uncached albums are built
  - cancel mid-build keeps finished thumbnails and leaves no `.tmp`
  - Refresh clears and rebuilds
  - low free space skips the build
  - an empty library shows the message
- **`tools/test_patch.py`** (MIPS):
  - Home has 7 cards, and index 2 opens `coverflow_page`.
  - The existing carousel fast/slow/reversal checks still pass with 7 cards.
  - The wheel and centre work on the Coverflow `slide_menu`, and a centre double-press still turns the screen off.
  - A track click hands `playing_page` a deque with the right index and class.
  - The tracks query restores `tools_pdeq_directory`.
  - Return from tracks → covers restores the album, and Return on covers goes Home.
  - Destroy removes the timer and joins the thread.
- Build normal and compact. Then run `test_peq.py`, `test_coverflow.py`, `test_build.py 'Q2 Firmware V1.32.zip'` (reproducible packages, size) and `test_patch.py` on both outputs.
- Docs: add a README Coverflow section, an internals section with the audit results, and a building-doc line for the new test.

## Final step (user request)

- Run a **ponytail-review subagent** on the full diff, fix its findings, then re-run all the tests above.
