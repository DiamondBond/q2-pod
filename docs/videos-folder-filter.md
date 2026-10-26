# Videos folder: show only videos (TODO)

Status: not started. Noted for the next agent on branch `videos-folder-browse`.

## Goal

Inside the Videos folder (Local Music → Videos, Folder view), list only subfolders and video files, so the folder shows the `.mp4` files and nothing else. Tapping a video opens the video player.

## Current state

- Library → Videos opens Folder view at the Videos folder (`media_click` in `patch/navigation.c`). Subfolders are rows.
- Tapping a video already plays it: `ringnav_folder_click` hands video records to `books_video` (`patch/books.c`), which starts `q2video`.
- Folder view still lists every file in the folder (`.txt`, `.epub`, `.mp3`, ...). Only the play path filters.

## Where to change

- Folder page list: `ringnav_folder` (`patch/navigation.c`, near `folder_page_init`), which runs stock's folder init. Stock's refresh is hooked as `folder_refresh` (`0x52176c`, see `tools/build.py`). Either place may be the right one. The filter has to change what the list shows, not only what a tap does.
- Video test: `book_kind()` in `patch/books.c` already classifies video extensions (`mp4`, `m4v`, `mkv`, `avi`, `mov`, `mpg`). Reuse it, don't duplicate the list.

## Constraints

- Apply only inside the Videos media root (`st.media_root` under `/mnt/mmc/Videos`, case aside). Podcasts, Audiobooks and normal folders keep showing every file.
- Keep folders at every depth so subfolders stay browsable.
- Don't change the click path. `ringnav_folder_click` / `books_video` already work for videos.

## Open questions

- Hide non-video files only in Videos, or everywhere? (Assumed: Videos only.)
- Should the filter also apply to the Library's Videos row count or Coverflow? (Assumed: no.)

## Tests

- `test/patch.py` around line 9067 still asserts the old flat Videos list. Update it with this change.
- The patch suite needs a fresh build first (`build/manifest.json` must match the sources).
- Device repro for "File Not Found" is still open; see the Videos section in `docs/internals.md`.
