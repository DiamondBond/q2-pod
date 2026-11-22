// SPDX-License-Identifier: GPL-3.0-only
// Part of Q2 Theme Studio, which holds work from DiamondBond/q2-pod (GPL-3.0-only): see LICENSE at the repository root.
// Q2 Theme Studio preview: the list pages (DRAWING.md section 6). Four screens share one list painter:
//   list-library  the Library, one-line rows with an icon (Classic's sets: text alone, Search first)
//   list-albums   Albums as a list, cover rows (Classic with Row Art off: one-line text rows)
//   list-songs    Songs, two-line rows under Play All's bar or row
//   settings      Settings > Display > Appearance, rows with values and switches
// The painter does the selection (card, bar, stops), separators, the rows, the scroll thumb, chevrons and
// the fast-scroll letter, in the firmware's paint order.
//
// state, beside what the status bar reads (Q2Draw.STATE):
//   selected  the selected row, counted from the list's first (Songs: the first song); null or -1: none
//   scroll    the list's scroll offset in px; left out, the list scrolls just far enough to show the
//             selected row
//   letter    true shows the fast-scroll letter of the selected row (Albums and Songs only: the Library's
//             categories and settings menus never show one)
// What is stored on the device (Row Art, Rounded Corners, the accent, ...) is env's, not state's.
(function (root, add) {
  if (typeof module === 'object' && module.exports) module.exports = add(require('./draw_core.js'));
  else add(root.Q2Draw);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (Q2Draw) {
  'use strict';

  const { W, H, div, clamp } = Q2Draw;

  // Stock's row shape, the same under every theme (DRAWING.md 2.3, 6.6): a row holds a button at x 20,
  // 335 wide; a table row's button lays its children out left to right with a side margin and a gap.
  const ROW_X = 20;
  const ROW_W = 335;
  const ROW_MARGIN = 8;
  const ROW_GAP = 14;
  const INTO = 50; // stock's trailing image: the chevron's box
  const TITLE_H = 24; // the title's and the second line's label boxes in a two-line row
  const META_H = 16;
  const META_W = 151;
  const TITLE_PX = 24; // stock's own sizes, used where the theme's role states none
  const META_PX = 16;
  // a Library row's button: the icon's box is 52 wide, then the label, then the chevron's box
  const LIB_ICON_W = 52;
  const LIB_TEXT_X = 72;
  const LIB_TEXT_W = 220;
  const LIB_INTO_X = 282;
  // stock's Play All bar over Songs, where the set keeps it (action_row 0)
  const ACTION_BAR = 50;
  const ACTION_PX = 20;
  const ACTION_PLAY = [16, 50]; // the Play All image's box: x, width
  const ACTION_TEXT = [70, 130];
  const ACTION_SORT = [306, 50];
  // Play All as a plain row (a set with action_row): the label's width, the Sort mark's box
  const ACTION_ROW_TEXT_W = 280;
  const ACTION_ROW_SORT = [301, 48];
  // settings rows (patch/offsets.inc SET_*): the icon's x, the gap to the text, the text's x without an
  // icon and its margin to the right edge, the trailing image's distance from the right edge
  const SET_ICON_X = 28;
  const SET_GAP = 12;
  const SET_TEXT_X = 20;
  const SET_EDGE = 24;
  const SET_VALUE_W = 136; // a value's box under settings.values.text
  const SET_ONOFF_W = 42; // "On" / "Off" there
  // the fast-scroll letter (patch/offsets.inc LETTER_*, FILL_RGB)
  const LETTER_BOX = 80;
  const LETTER_RADIUS = 12;
  const LETTER_ALPHA = 0xd9;
  const LETTER_PX = 60;
  const LETTER_FILL = 0x2b2b2b;
  const SWITCH = [50, 24]; // a settings switch's image (env.art.switch)

  // A radius r corner's coverage of its r x r pixels out of 255, the outermost row first, as the firmware's
  // build tabulates it (tools/art.py corner_cover: 16 x 16 samples a pixel).
  function cornerCover(r) {
    const n = 16;
    const out = [];
    for (let y = 0; y < r; y += 1) {
      for (let x = 0; x < r; x += 1) {
        let inside = 0;
        for (let i = 0; i < n; i += 1) for (let j = 0; j < n; j += 1) if (Math.hypot(r - x - (i + 0.5) / n, r - y - (j + 0.5) / n) <= r) inside += 1;
        out.push(Math.round((inside * 255) / (n * n)));
      }
    }
    return out;
  }
  const THUMB_R = 2; // the scroll thumb's end radius
  const THUMB_COVER = cornerCover(THUMB_R);

  // ------------------------------------------------------------------------------------ small pieces

  // The chevron of a row that opens something. box: stock's image box on screen, [x, y, w, h].
  function drawChevron(ctx, env, box, selected) {
    const T = env.T;
    const [bx, by, bw, bh] = box;
    const [x, y] = env.centre('list_into', bx, by, bw, bh);
    if (T('list.chevron.selected')) {
      // stock's image is emptied: the selected row alone has one, drawn over an accented selection
      if (!selected || !env.selAccent()) return;
      const cx = T('list.chevron.x');
      if (cx) env.art.chevron(ctx, cx, by + div(bh, 2) - 8);
      else env.art.listInto(ctx, x, y, 0xffffff);
      return;
    }
    if (selected && env.light && env.selAccent()) {
      // Light Mode: on the coloured bar or card it is drawn again white, over a patch of the accent
      env.fill(ctx, bx + div(bw, 2) - div(INTO, 4), by + div(bh, 2) - div(INTO, 4), div(INTO, 2), div(INTO, 2), env.tone(0));
      env.art.listInto(ctx, x, y, 0xffffff);
      return;
    }
    // stock's white mark through the half; a card scheme's is inked the scheme's grey under mono icons
    const grey = (env.S.chevron || 0) & 255;
    const mark = env.S.card && T('list.icons.mono') ? Q2Draw.pack(grey, grey, grey) : 0xffffff;
    env.art.listInto(ctx, x, y, env.INK(mark));
  }

  // The theme's separator: one pixel row per stop, ending at bottom (DRAWING.md 6.3). Final colours.
  function drawSeparator(ctx, env, bottom) {
    const lines = env.T('list.separator.stops');
    for (let j = 0; j < lines.length; j += 1) env.fill(ctx, 0, bottom - lines.length + j, W, 1, lines[j][1]);
  }

  // The theme's scroll thumb over a list at y, h whose rows are content px high in all, scrolled by value
  // (navigation.c paint_scrollbar). Nothing at list.scrollbar.w 0 (stock's own fading bar), or where the
  // content fits.
  function drawThumb(ctx, env, y, h, content, value) {
    const T = env.T;
    const w = T('list.scrollbar.w');
    if (!w || content <= h) return;
    const top = Math.max(y, T('list.scrollbar.top'));
    const track = Math.min(y + h, T('list.scrollbar.bottom')) - top;
    if (track <= 0) return;
    let len = div(track * h, content);
    if (len < T('list.scrollbar.min')) len = T('list.scrollbar.min');
    if (len > track) len = track;
    const at = top + div((track - len) * clamp(value, 0, content), content);
    const x = W - T('list.scrollbar.right') - w;
    const colour = T('list.scrollbar.thumb');
    // both ends rounded by 2: each corner pixel takes the colour at its coverage (navigation.c round_row)
    for (let i = 0; i < len; i += 1) {
      const row = i < THUMB_R ? i : i >= len - THUMB_R ? len - 1 - i : -1;
      let n = 0;
      for (; row >= 0 && n < THUMB_R && THUMB_COVER[row * THUMB_R + n] < 255; n += 1) {
        const a = THUMB_COVER[row * THUMB_R + n];
        env.fill(ctx, x + n, at + i, 1, 1, colour, a);
        env.fill(ctx, x + w - 1 - n, at + i, 1, 1, colour, a);
      }
      env.fill(ctx, x + n, at + i, w - 2 * n, 1, colour);
    }
  }

  // The letter a row sorts under: its title's first character past spaces and, in the library's lists, a
  // leading article; a to z as capitals.
  function sortLetter(title) {
    const s = String(title).replace(/^ +/, '').replace(/^(the|an|a) +/i, '');
    const ch = Array.from(s)[0] || '';
    return ch >= 'a' && ch <= 'z' ? ch.toUpperCase() : ch;
  }

  // The fast-scroll letter over a list at y, h (DRAWING.md 6.8).
  function drawLetter(ctx, env, y, h, title) {
    const ch = sortLetter(title);
    if (!ch) return;
    const raw = Boolean(env.T('list.letter.raw'));
    const x = div(W - LETTER_BOX, 2);
    const top = y + div(h - LETTER_BOX, 2);
    env.box(ctx, x, top, LETTER_BOX, LETTER_BOX, LETTER_RADIUS, raw ? LETTER_FILL : env.INK(LETTER_FILL), LETTER_ALPHA);
    env.canvasText(ctx, ch, x, top, LETTER_BOX, LETTER_BOX, env.T('list.letter.px') || LETTER_PX, raw ? 0xffffff : env.INK(0xffffff));
  }

  // --------------------------------------------------------------------------------- the list painter

  // The selected row of n, or -1.
  function selectedRow(state, n) {
    const s = state.selected;
    if (s === null || s === undefined || s === false || !(s >= 0) || !n) return -1;
    return Math.min(Math.floor(s), n - 1);
  }

  // Paints a list in the firmware's order (DRAWING.md 6.1). L:
  //   y, h       the list's box on screen (375 wide)
  //   pitch      a row's height
  //   rows       its rows
  //   images     the row button's leading images, for a pill's radius (env.selection)
  //   separated  true: every row but the selected one ends in the theme's separator
  //   row(ctx, r, y0, selected, i)   draws row i's icon or cover and its texts
  //   into(r, y0, i)                 the chevron's image box of a row that opens something, else null
  //   letter     true: the fast-scroll letter may show (state.letter)
  // Returns { selected, scroll }.
  function paintList(ctx, env, state, L) {
    const n = L.rows.length;
    const sel = selectedRow(state, n);
    const content = n * L.pitch;
    // a selected row is never left under the set's list_end (a window y), nor under the list's end; the
    // rows below it draw on (navigation.c sel_height, max_top)
    const end = Math.max(L.pitch, env.G.list_end ? Math.min(L.h, env.G.list_end - (L.y - env.bar)) : L.h);
    let scroll = 0;
    if (typeof state.scroll === 'number') scroll = state.scroll;
    else if (sel >= 0) scroll = (sel + 1) * L.pitch - end;
    scroll = clamp(Math.round(scroll), 0, Math.max(0, content - end));
    const first = div(scroll, L.pitch);
    const last = Math.min(n - 1, div(scroll + L.h - 1, L.pitch));
    const top = (i) => L.y + i * L.pitch - scroll;

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, L.y, W, L.h);
    ctx.clip();
    // behind the rows: the selection, then the separators
    if (sel >= first && sel <= last) env.selection(ctx, 0, top(sel), W, L.pitch, { images: L.images });
    if (L.separated) for (let i = first; i <= last; i += 1) if (i !== sel) drawSeparator(ctx, env, top(i) + L.pitch);
    // the rows
    for (let i = first; i <= last; i += 1) L.row(ctx, L.rows[i], top(i), i === sel, i);
    // after the rows: the thumb, the chevrons, the letter
    drawThumb(ctx, env, L.y, L.h, content, scroll);
    if (L.into) {
      for (let i = first; i <= last; i += 1) {
        const box = L.into(L.rows[i], top(i), i);
        if (box) drawChevron(ctx, env, box, i === sel);
      }
    }
    if (L.letter && state.letter && sel >= 0) drawLetter(ctx, env, L.y, L.h, L.rows[sel].title);
    ctx.restore();
    return { selected: sel, scroll };
  }

  // ------------------------------------------------------------------------------------- the Library

  // The Library's rows: the sample library's, with Search first in a set without Library icons.
  function libraryRows(env) {
    const rows = env.sample.library.slice();
    if (!env.G.lib_art) rows.unshift({ title: 'Search', icon: null });
    return rows;
  }

  function drawLibrary(ctx, env, state) {
    const G = env.G;
    const body = G.lib_body;
    const bare = !G.lib_art; // no icons: the label starts at the set's text inset, its right end kept
    const textX = bare ? G.text_x : ROW_X + LIB_TEXT_X;
    const textW = ROW_X + LIB_TEXT_X + LIB_TEXT_W - textX;
    paintList(ctx, env, state, {
      y: env.win.y,
      h: env.win.h,
      pitch: G.lib_pitch,
      rows: libraryRows(env),
      images: bare ? [] : [{ x: G.lib_inset, y: 0, w: LIB_ICON_W, h: body, centre: true }],
      row(c, r, y0, selected) {
        if (!bare) {
          const x = ROW_X + G.lib_inset + div(LIB_ICON_W - G.lib_art, 2);
          const y = y0 + div(body - G.lib_art, 2);
          env.art.disc(c, r.icon, x, y, G.lib_art);
        }
        env.label(c, r.title, textX, y0, textW, body, { role: 'title', px: TITLE_PX, colour: env.rowText({ selected }) });
      },
      into: (r, y0) => [ROW_X + LIB_INTO_X, y0, INTO, body],
    });
    Q2Draw.bar(ctx, env, state);
  }

  // ---------------------------------------------------------------------------------- table rows

  // Where stock's row layout and the payload's layouter over it (navigation.c compact_row_layout) put a
  // table row's children. body: the row button's height; lead: its leading image's width (a cover or a
  // tile; 0: none); into: stock's chevron image is its last child. Every x is on screen.
  //   shown     the leading image shows        leadX   its x
  //   textX, textW   the text container        metaW   the second line's width
  //   tall      a theme's art row: the title takes the tall role      second: the second line shows
  //   plain     two lines of text and no artwork (these rows take the separators)
  //   intoX     stock's chevron box
  function tableLayout(env, body, lead, into) {
    const G = env.G;
    const T = env.T;
    const high = body > G.pitch;
    const tall = T('list.art.x') > 0 && high;
    const bare = !G.text_art; // a set without text-row artwork
    const oneLine = bare && !high;
    const plain = bare && high && !lead;
    const shown = !oneLine && !plain;
    const before = shown ? lead + ROW_GAP : 0;
    let x = ROW_MARGIN + before; // in the button, as stock's layout leaves it
    let w = ROW_W - 2 * ROW_MARGIN - before - (into ? INTO + ROW_GAP : 0);
    if (tall && !plain) w = T('list.art.text_end') - T('list.art.text_x') + 4;
    const fixed = plain || (into && oneLine); // the text ends at a column of the theme's
    if (fixed) w = (into ? T('list.art.text_end') : T('list.row.text_end')) - G.text_x + 2;
    if (w < 0) w = 0;
    const intoX = ROW_X + x + w + ROW_GAP;
    let leadX = ROW_X + ROW_MARGIN;
    if (tall && shown) { // the art and the text on the theme's columns
      leadX = T('list.art.x');
      x = T('list.art.text_x') - 2 - ROW_X;
    }
    if (G.text_x && x <= ROW_MARGIN) { // text leading the row starts at the set's inset
      const to = Math.max(G.text_x - ROW_X, 0);
      if (!fixed) w = Math.max(0, w - (to - x));
      x = to;
    }
    return { shown: shown && lead > 0, leadX, textX: ROW_X + x, textW: w, metaW: tall ? w : Math.min(META_W, w), tall, second: !oneLine, plain, intoX };
  }

  // A table row's two labels at their set's y in the row.
  function drawTexts(ctx, env, lay, title, meta, y0, titleY, metaY, selected) {
    env.label(ctx, title, lay.textX, y0 + titleY, lay.textW, TITLE_H, { role: lay.tall ? 'tall' : 'title', px: TITLE_PX, colour: env.rowText({ selected }) });
    if (lay.second && meta) env.label(ctx, meta, lay.textX, y0 + metaY, lay.metaW, META_H, { role: 'meta', px: META_PX, colour: env.rowText({ selected, second: true }) });
  }

  // ---------------------------------------------------------------------------------------- Albums

  function drawAlbums(ctx, env, state) {
    const G = env.G;
    const body = G.art_body;
    const lay = tableLayout(env, body, G.art, true);
    paintList(ctx, env, state, {
      y: env.win.y,
      h: env.win.h,
      pitch: G.art_pitch,
      rows: env.sample.albums,
      images: lay.shown ? [{ x: lay.leadX - ROW_X, y: 0, w: G.art, h: body }] : [],
      row(c, r, y0, selected) {
        if (lay.shown) env.artwork(c, r.cover, lay.leadX, y0 + G.art_inset, G.art);
        drawTexts(c, env, lay, r.title, r.artist, y0, G.art_title24_y, G.art_meta_y, selected);
      },
      into: (r, y0) => [lay.intoX, y0, INTO, body],
      letter: true,
    });
    Q2Draw.bar(ctx, env, state);
  }

  // ----------------------------------------------------------------------------------------- Songs

  // Play All above the songs: stock's 50 px bar, or under a set with action_row a plain row that high with
  // the theme's separator at its bottom. Not selectable. Returns its height.
  function drawPlayAll(ctx, env) {
    const G = env.G;
    const y = env.win.y;
    if (!G.action_row) {
      env.art.playAll(ctx, ACTION_PLAY[0], y);
      env.label(ctx, 'Play All', ACTION_TEXT[0], y, ACTION_TEXT[1], ACTION_BAR, { face: 'regular', px: ACTION_PX, colour: env.fg });
      env.art.songOrder(ctx, ACTION_SORT[0], y);
      return ACTION_BAR;
    }
    const h = G.action_row;
    drawSeparator(ctx, env, y + h);
    env.label(ctx, 'Play All', G.text_x, y, ACTION_ROW_TEXT_W, h, { role: 'title', px: ACTION_PX, colour: env.fg });
    const [sx, sy] = env.centre('sort_bars', ACTION_ROW_SORT[0], y, ACTION_ROW_SORT[1], h);
    env.art.sortBars(ctx, sx, sy);
    return h;
  }

  function drawSongs(ctx, env, state) {
    const G = env.G;
    const body = G.song_body;
    const lay = tableLayout(env, body, G.text_art, false);
    const y = env.win.y + drawPlayAll(ctx, env);
    paintList(ctx, env, state, {
      y,
      h: H - y,
      pitch: G.song_pitch,
      rows: env.sample.songs,
      images: lay.shown ? [{ x: lay.leadX - ROW_X, y: 0, w: G.text_art, h: body }] : [],
      separated: lay.plain,
      row(c, r, y0, selected) {
        if (lay.shown) env.art.tile(c, 'note', lay.leadX, y0 + G.text_art_inset, G.text_art);
        // an untagged song: stock's "Unknown Artist" where the set keeps stock's row, else nothing
        drawTexts(c, env, lay, r.title, r.artist || (G.text_art ? 'Unknown Artist' : ''), y0, G.song_title24_y, G.song_meta_y, selected);
      },
      letter: true,
    });
    Q2Draw.bar(ctx, env, state);
  }

  // -------------------------------------------------------------------------------------- settings

  function drawSettings(ctx, env, state) {
    const G = env.G;
    const T = env.T;
    const h = G.set_row;
    const icon = G.set_icon;
    const text = Boolean(T('settings.values.text')); // values as their own right-aligned text
    const textX = icon ? SET_ICON_X + icon + SET_GAP : SET_TEXT_X;
    const end = W - SET_TEXT_X; // no text passes this column
    const trail = W - SET_EDGE - INTO; // the trailing image's box
    const y = env.win.y + T('settings.rows.top');
    paintList(ctx, env, state, {
      y,
      // the stock set's list holds set_rows rows; a set with list_end runs to the window's end
      h: G.list_end ? H - y : Math.min(H - y, G.set_rows * h),
      pitch: h,
      rows: env.appearanceRows(),
      images: icon ? [{ x: SET_ICON_X, y: div(h - icon, 2), w: icon, h: icon }] : [],
      row(c, r, y0, selected) {
        const colour = env.rowText({ selected });
        const label = (str, x, w, o) => env.label(c, str, x, y0, Math.max(0, w), h, Object.assign({ role: 'title', px: TITLE_PX, colour }, o));
        if (icon) env.art.disc(c, 'display', SET_ICON_X, y0 + div(h - icon, 2), icon);
        if (r.kind === 'switch') {
          if (text) {
            label(r.title, textX, end - SET_ONOFF_W - textX);
            label(r.value, end - SET_ONOFF_W, SET_ONOFF_W, { align: 'right' });
          } else {
            label(r.title, textX, trail - 8 - textX);
            env.art.switch(c, trail + div(INTO - SWITCH[0], 2), y0 + div(h - SWITCH[1], 2), r.value === 'On');
          }
        } else if (r.kind === 'page') {
          // the text ends before the chevron: at stock's box, or a column short of the theme's own
          const cx = T('list.chevron.x');
          label(r.title, textX, (cx && T('list.chevron.selected') ? cx - 1 : trail + 10) - textX);
        } else if (text) {
          label(r.title, textX, end - SET_VALUE_W - textX);
          label(r.value, end - SET_VALUE_W, SET_VALUE_W, { align: 'right' });
        } else label(`${r.title}: ${r.value}`, textX, end - textX);
      },
      into: (r, y0) => (r.kind === 'page' ? [trail, y0, INTO, h] : null),
    });
    Q2Draw.bar(ctx, env, state);
  }

  // ------------------------------------------------------------------------------------ the screens

  Q2Draw.screens['list-library'] = {
    title: 'Library',
    draw: drawLibrary,
    states: [
      { id: 'top', label: 'First row', state: { selected: 0 } },
      { id: 'lower', label: 'Further down', state: { selected: 9 } },
    ],
  };
  Q2Draw.screens['list-albums'] = {
    title: 'Albums',
    draw: drawAlbums,
    states: [
      { id: 'top', label: 'First row', state: { selected: 0 } },
      { id: 'lower', label: 'Further down', state: { selected: 6 } },
      { id: 'letter', label: 'Fast scroll', state: { selected: 6, letter: true } },
    ],
  };
  Q2Draw.screens['list-songs'] = {
    title: 'Songs',
    draw: drawSongs,
    states: [
      { id: 'top', label: 'First song', state: { selected: 0 } },
      { id: 'lower', label: 'Further down', state: { selected: 6 } },
      { id: 'letter', label: 'Fast scroll', state: { selected: 6, letter: true } },
    ],
  };
  Q2Draw.screens.settings = {
    title: 'Settings',
    draw: drawSettings,
    states: [
      { id: 'top', label: 'First row', state: { selected: 0 } },
      { id: 'switch', label: 'A switch', state: { selected: 2 } },
      { id: 'lower', label: 'Further down', state: { selected: 9 } },
    ],
  };
  return Q2Draw;
});
