# Q2 Theme Studio

A web page for making a theme in the firmware's own format (`assets/themes/<id>/theme.xml`). You start
from one of the built-in themes, either extending it or as a stand-alone copy, change its values with a
live preview of the Q2's 375 x 320 screen, and save a `theme.xml` that `tools/theme.py` accepts. A Problems
list shows, as you go, everything that tool would refuse.

Everything runs in the browser: no build step, no server code, no request to another host. The page's
content policy (in `studio.html`) allows only its own files.

## Running it

The page fetches `official.json` and takes its two fonts from `assets/fonts`, so serve the repository's
root over http:

```
python3 -m http.server 8000
```

then open `http://localhost:8000/tools/theme-studio/studio.html`.

## Files

| File | What it is |
| --- | --- |
| `studio.html`, `studio.css`, `studio.js` | the page: the editor, its controls, the Problems list, saving and opening |
| `official.js` | the theme format: reading and writing `theme.xml`, the theme model with checked edits, resolve, problems |
| `official.json` | the format's tables and the built-in themes, written by `official_data.py` from `tools/theme.py` |
| `official_data.py` | writes `official.json` from this checkout |
| `draw_core.js`, `draw_bar.js` | the preview's drawing environment and the status bar |
| `draw_home.js`, `draw_list.js`, `draw_playing.js` | the screens: Home; Library, Albums, Songs and Settings; Now Playing, the volume and the confirm dialog |
| `*.test.mjs` | the tests |

The preview draws with the repository's own art and its two open fonts. It holds no stock picture or
font: text in a stock face is drawn in a stand-in, and stock icons are redrawn as stand-ins.

## After a change to `tools/theme.py` or a built-in theme

```
python3 tools/theme-studio/official_data.py
```

writes `official.json` again. Where the tool keeps a rule in code (the tokenizer, resolve, validate),
`official.js` mirrors it, and `official.json` holds a hash of each such function. `official.test.mjs`
fails when a mirrored function has changed, and names it.

## Tests

```
cd tools/theme-studio
node --test
```

The tests that draw real pixels need `@napi-rs/canvas` (`npm install @napi-rs/canvas` in this folder)
and are skipped without it.
