// SPDX-License-Identifier: GPL-3.0-only
// Part of Q2 Theme Studio, which holds work from DiamondBond/q2-pod (GPL-3.0-only): see LICENSE at the repository root.
// Home (DRAWING.md section 5): the menu in its three layouts. Split has the list on the left 187 px and
// the art panel right of it (the playing track's cover, or with none the theme's pane or the "no cover"
// plate); Full has the list alone across the screen; Carousel is stock's own card strip, which no theme
// reaches. Adds Q2Draw.screens.home.
//
// State keys of this screen, beside Q2Draw.STATE's:
//   layout    'split' | 'full' | 'carousel': stands in for the Home setting (env.set.home) when given
//   selected  the highlighted row (a card in Carousel), from 0; null or -1 highlights none
//   play      'none' leaves the panel without a cover; 'playing' and 'paused' show the track's
//   cover     the playing track's cover: an album of env.sample.albums (left out: the sample track's),
//             or null for a track that has none
//   queue     the songs in the queue, which the pane's caption counts (left out: the sample track's count
//             while a track plays, none when nothing does)
(function (root, add) {
  if (typeof module === 'object' && module.exports) module.exports = add(require('./draw_core.js'));
  else add(root.Q2Draw);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (Q2Draw) {
  'use strict';

  const div = Q2Draw.div;
  const W = Q2Draw.W;
  const H = Q2Draw.H;

  // The firmware's own numbers for Home (patch/offsets.inc, patch/coverflow.c): no theme key or geometry
  // field changes them.
  const SPLIT_W = 187; // HOME_SPLIT_W: the list's width in Split; the panel is the rest
  const CAPS_PX = 18; // HOME_CAPS_PX: the small capitals' size
  const CAPS_GREY = 0x8c8c8c; // SUDO_MUTED: the capitals' grey, in stock terms
  const LABEL_PX = 20; // stock's own Home label style (s_scrlabel_white20l)
  const CHEVRON_W = 58; // stock's chevron image starts this far before the row's right edge
  const INTO = 50; // stock's chevron image, square
  const SHIFT_SPLIT = 15; // HOME_CHEVRON_SHIFT
  const SHIFT_FULL = 10; // HOME_FULL_CHEVRON_SHIFT
  const OWN_CHEVRON = [12, 16]; // the theme's own chevron image
  const ZOOM_PCT = 110; // DRIFT_ZOOM_PCT: a cover is drawn this much larger than its fit, to pan
  const CAPTION_H = 24; // the pane caption's box
  const LAYOUTS = ['split', 'full', 'carousel'];

  // What the pane shows for a highlighted row (coverflow.c pane_icons, pane_caption): the image, whether it
  // sits at the note's place, what its caption counts, and whether a cover takes the pane's place.
  const PANES = {
    now: { image: 'note', note: true, count: 'queue', cover: true },
    library: { image: 'note', note: true, count: 'songs', cover: true },
    shuffle: { image: 'icon-note', note: true, count: 'songs' },
    coverflow: { image: 'stack', count: 'albums' },
    folder: { image: 'folder' },
    games: { image: 'game', count: 'games' },
    rockbox: { image: 'game' },
    stream: { image: 'wave', count: 'services' },
    settings: { image: 'gear', count: 'free' },
  };
  // The Shortcut row's pane by what it opens; any other shortcut shows the Library's.
  const SHORTCUT_PANES = { games: 'games', rockbox: 'rockbox', groovebox: 'rockbox', shuffle: 'shuffle', podcasts: 'folder', audiobooks: 'folder' };
  const ROW_PANES = { playing: 'now', library: 'library', coverflow: 'coverflow', folder: 'folder', streaming: 'stream', settings: 'settings' };
  const CAPTIONS = { queue: ['1 Song', ' Songs'], songs: ['1 Song', ' Songs'], albums: ['1 Album', ' Albums'], games: ['1 Game', ' Games'], services: ['1 Service', ' Services'] };

  // Carousel's stand-in cards by row: a disc name of Q2Draw.DISCS, and the repository's own picture
  // where it has one (the host may have loaded it, see env.image).
  const CARDS = {
    playing: ['note'], library: ['list'], coverflow: ['disc', 'menu_coverflow'], folder: ['folder'], streaming: ['radio'],
    playback: ['speaker'], system: ['gear'],
  };
  const SHORTCUT_CARDS = {
    artists: 'person', albums: 'disc', favorites: 'heart', rated_albums: 'star', shuffle: 'shuffle', games: 'game', playlists: 'list', podcasts: 'mic',
    audiobooks: 'book',
  };

  // Which layout is drawn, and the list as laid out (5.1): each row's rectangle and its label's box.
  // Returns { mode, full, outer (the list's and the selection's width), inner (a row's), top, rowH, rows,
  // selected, panel }; rows are [{ id, title, shortcut, x, y, w, h, label: { x, y, w, h } }].
  function layout(env, state = {}) {
    const mode = LAYOUTS.includes(state.layout) ? state.layout : env.set.home;
    const full = mode === 'full';
    const outer = full ? W : SPLIT_W;
    const inner = full ? env.T('home.rows.full_row') : SPLIT_W;
    const rowH = env.G.home_row;
    const top = env.bar + env.T('home.rows.top');
    const textX = env.T('home.rows.text_x');
    const end = env.T(full ? 'home.rows.label_end_full' : 'home.rows.label_end_split');
    const rows = env.homeRows().map((row, i) => {
      const y = top + i * rowH;
      return Object.assign({}, row, { x: 0, y, w: inner, h: rowH, label: { x: textX, y, w: inner - textX - end, h: rowH } });
    });
    const count = mode === 'carousel' ? cards(env).length : rows.length;
    // null or a negative row: none highlighted (Carousel always has a card in front)
    const none = mode !== 'carousel' && (state.selected === null || Number(state.selected) < 0);
    const selected = none ? -1 : Q2Draw.clamp(Math.floor(Number(state.selected) || 0), 0, count - 1);
    const panel = mode === 'split' ? { x: SPLIT_W, y: env.bar, w: W - SPLIT_W, h: H - env.bar } : null;
    return { mode, full, outer, inner, top, rowH, rows, selected, panel };
  }

  // ---- the list (5.3 to 5.5)

  // A row's label: Minimal's small capitals, or stock's own label in the Home role.
  function label(ctx, env, row, selected) {
    const b = row.label;
    if (b.w <= 0) return;
    if (env.T('home.rows.caps')) {
      // white only on the card painter's selected row; every other label the grey, whatever the painter
      const lit = selected && env.choice('list.selection.painter') === 'card';
      env.caps(ctx, row.title, b.x, b.y + div(b.h - CAPS_PX, 2), CAPS_PX, env.INK(lit ? 0xffffff : CAPS_GREY), b.w);
      return;
    }
    env.label(ctx, row.title, b.x, b.y, b.w, b.h, { role: 'home', px: LABEL_PX, colour: env.rowText({ selected, home: true }) });
  }

  // The selected row's chevron (5.5), when the theme shows one on Home. accented: whether the selection
  // counts as accented (its marks stay white in the light half).
  function chevron(ctx, env, L, row, accented) {
    if (!env.T('home.chevron.visible')) return;
    const box = env.T(L.full ? 'list.chevron.x' : 'home.chevron.x');
    const selectedOnly = Boolean(env.T('list.chevron.selected'));
    const cy = row.y + div(row.h, 2);
    // The white copy is asked for on a selected-only theme and on an accented row in the light half: the
    // theme's own image where a box places it, else stock's. The build draws the theme's own image only
    // for a theme with list.chevron.x, so without it there is none to load.
    const white = (selectedOnly || (env.light && accented)) && (box === 0 || env.T('list.chevron.x') !== 0);
    if (white && box !== 0) {
      env.art.chevron(ctx, row.x + box, cy - div(OWN_CHEVRON[1], 2));
      return;
    }
    if (selectedOnly && !white) return; // stock's own image is emptied for such a theme
    const cx = box !== 0 ? row.x + box + div(INTO, 2) : row.x + row.w - CHEVRON_W + div(INTO, 2) + (L.full ? SHIFT_FULL : SHIFT_SPLIT);
    let colour; // left out: white, flipped to ink in the light half
    if (white) colour = 0xffffff;
    else if (env.T('list.icons.mono') && env.S.card) {
      const grey = (env.S.chevron || 0) & 255; // a card scheme inks stock's chevron in the icons' grey
      colour = Q2Draw.pack(grey, grey, grey);
    }
    env.art.listInto(ctx, cx - div(INTO, 2), cy - div(INTO, 2), colour);
  }

  function list(ctx, env, L) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, env.bar, L.outer, H - env.bar);
    ctx.clip();
    const row = L.rows[L.selected];
    const painted = row ? env.selection(ctx, 0, row.y, L.outer, row.h, { home: true }) : null;
    L.rows.forEach((r, i) => label(ctx, env, r, i === L.selected));
    if (row) chevron(ctx, env, L, row, painted.accent);
    ctx.restore();
  }

  // ---- Split's art panel (5.6)

  // Which pane the highlighted row asks for: a key of PANES. The pane follows the row only when the theme
  // places an icon (home.pane.icon_x) and its Row Preview option is on; else it is Now Playing's.
  function paneKind(env, row) {
    if (!row || !env.T('home.pane.icon_x') || env.own.ROWPREVIEW !== 1) return 'now';
    if (row.shortcut) return SHORTCUT_PANES[row.id] || 'library';
    return ROW_PANES[row.id] || 'library';
  }

  // The pane's caption for what it counts; empty when there is nothing to count.
  function caption(env, what, queue) {
    if (!what) return '';
    if (what === 'free') return env.sample.counts.free || '';
    const n = what === 'queue' ? queue : env.sample.counts[what];
    if (!n) return '';
    return n === 1 ? CAPTIONS[what][0] : n + CAPTIONS[what][1];
  }

  // The shadow down the panel's left edge: drawn over the pane, and over a cover too.
  function shadow(ctx, env, p) {
    const alphas = env.T('home.pane.shadow_a');
    const colour = env.T('home.pane.shadow');
    for (let i = 0; i < env.T('home.pane.shadow_w'); i += 1) env.fill(ctx, p.x + i, p.y, 1, p.h, colour, alphas[i] || 0);
  }

  // The theme's pane (coverflow.c home_pane_paint): its stops, its light, its shadow, the row's image and
  // caption. Every colour is final but the caption's. Under a flat pages painter (DRAWING.md 15.3) the image
  // is the flat look's, in the half's flat ink, and the caption is in the system face in the quiet grey.
  function pane(ctx, env, p, kind, queue) {
    const T = env.T;
    env.stops(ctx, p.x, p.y, p.w, p.h, T('home.pane.stops'));
    const light = T('home.pane.light_a');
    for (let k = 0; k < light; k += 1) { // a band of white per alpha, fading to the right
      const x0 = div(p.w * k, light);
      env.fill(ctx, p.x + x0, p.y, div(p.w * (k + 1), light) - x0, p.h, 0xffffff, light - k);
    }
    shadow(ctx, env, p);
    const at = kind.note ? [T('home.pane.note_x'), T('home.pane.note_y')] : [T('home.pane.icon_x'), T('home.pane.icon_y')];
    const notes = kind.image === 'note' || kind.image === 'icon-note';
    if (env.flatPages) env.art.flatPaneIcon(ctx, notes ? 'note' : kind.image, p.x + at[0], p.y + at[1]);
    else if (kind.image === 'note') env.art.note(ctx, p.x + at[0], p.y + at[1]);
    else env.art.paneIcon(ctx, kind.image === 'icon-note' ? 'note' : kind.image, p.x + at[0], p.y + at[1]);
    const text = caption(env, kind.count, queue);
    const px = T('home.pane.count_px');
    if (!text || px <= 0) return;
    const y = p.y + T('home.pane.count_y');
    // flat: stock's face whatever list.row.font says, quiet grey, final
    if (env.flatPages) env.text(ctx, text, p.x, y, T('home.pane.count_w'), CAPTION_H, { face: 'regular', px, align: 'center', colour: env.flatQuiet });
    // dark half white; light half black through the flip, which is the light half's paper
    else env.canvasText(ctx, text, p.x, y, T('home.pane.count_w'), CAPTION_H, px, env.light ? env.INK(0x000000) : 0xffffff);
  }

  function panel(ctx, env, state, L) {
    const p = L.panel;
    const track = state.play !== 'none';
    const cover = !track ? null : state.cover === undefined ? env.sample.playing.cover : state.cover;
    const hasCover = cover !== null && cover !== undefined;
    const kind = PANES[paneKind(env, L.rows[L.selected])];
    const themed = !hasCover && env.T('home.pane.stops').length > 0; // no cover: the theme's pane, if it has one
    const covers = Boolean(kind.cover) && !themed; // a row that shows the cover (or the plate) rather than its pane
    ctx.save();
    ctx.beginPath();
    ctx.rect(p.x, p.y, p.w, p.h);
    ctx.clip();
    // The sample covers and the plate are square, so each one's fit is the panel's height: centred across
    // the panel, cropped by it (coverflow.c home_fit).
    const side = p.h;
    const left = p.x + div(p.w - side, 2);
    if (!hasCover && !themed) env.art.placeholder(ctx, left, p.y, side, false); // still, at its fit; the same in both halves
    if (covers) {
      if (hasCover) {
        // The cover pans slowly on the device: it is drawn larger than its fit and the panel starts at
        // the fit's own centred crop. This is the pan's first frame.
        const zoomed = div(side * ZOOM_PCT, 100);
        env.cover(ctx, cover, p.x - div(side - p.w, 2), p.y, zoomed, zoomed);
      }
      if (env.T('home.pane.shadow_w')) shadow(ctx, env, p);
    } else pane(ctx, env, p, kind, state.queue === undefined || state.queue === null ? (track ? env.sample.playing.count : 0) : Math.max(0, Math.floor(Number(state.queue) || 0)));
    ctx.restore();
  }

  // ---- Carousel (5.8)

  // Carousel's cards: Home's rows with none hidden (the hide switches and Shortcut None leave their cards)
  // and Settings as its two pages.
  function cards(env) {
    const shortcut = env.set.shortcut === 'none' ? 'rockbox' : env.set.shortcut;
    const name = (env.homeRows().find((r) => r.shortcut) || {}).title || 'Rockbox';
    return [
      { id: 'playing', title: 'Now Playing' }, { id: 'library', title: 'Library' }, { id: 'coverflow', title: 'Cover Flow' }, { id: 'folder', title: 'Folder' },
      { id: shortcut, title: name, shortcut: true }, { id: 'streaming', title: 'Streaming' }, { id: 'playback', title: 'Playback Settings' },
      { id: 'system', title: 'System Settings' },
    ];
  }

  // A plain approximation: stock's own strip is not known beyond its boxes, and nothing in a theme moves
  // or colours it. One centred card (190 px, 23 px down its 290 px button), its name under it (28 px,
  // from 232 px down), and the two arrows in their 70 px cells. Only the name and the arrows turn to ink
  // in the light half.
  function carousel(ctx, env, L) {
    const top = env.bar;
    const card = cards(env)[L.selected];
    const button = { x: div(W - 290, 2) + 3, w: 290 }; // the strip's middle is 3 px right of the screen's
    const x = button.x + 50;
    const [disc, file] = card.shortcut ? [SHORTCUT_CARDS[card.id] || 'game', 'menu_rockbox'] : CARDS[card.id];
    if (!file || !env.image(ctx, file, x, top + 23, 190, 190)) env.art.card(ctx, disc, x, top + 23, 190);
    env.text(ctx, card.title, button.x, top + 232, button.w, 28, { face: 'regular', px: 28, align: 'center', ellipsis: true, colour: env.fg });
    // the arrows' ink sits 18 px in from each side, 108 to 131 px down the window
    env.strokePath(ctx, 'M30.5 108.5 L19.5 120 L30.5 131.5', 0, top, 2.4, env.fg, 255, 'butt');
    env.strokePath(ctx, 'M-30.5 108.5 L-19.5 120 L-30.5 131.5', W, top, 2.4, env.fg, 255, 'butt');
  }

  // ---- the screen

  function draw(ctx, env, state) {
    const L = layout(env, state);
    if (L.mode === 'carousel') carousel(ctx, env, L);
    else {
      if (L.panel) panel(ctx, env, state, L); // the art first: it paints only inside its panel,
      list(ctx, env, L); // and the list only left of it
    }
    if (Q2Draw.bar) Q2Draw.bar(ctx, env, state);
    return L;
  }

  Q2Draw.screens.home = {
    title: 'Home',
    draw,
    layout, // layout(env, state): where each row is, for a page that wants to point at them
    states: [
      // the first leaves layout out, so the Home setting of env picks it
      { id: 'playing', label: 'Playing', state: { play: 'playing', selected: 0 } },
      { id: 'idle', label: 'Nothing playing', state: { play: 'none', selected: 0 } },
      { id: 'split', label: 'Split', state: { layout: 'split', play: 'playing', selected: 0 } },
      { id: 'split-idle', label: 'Split, nothing playing', state: { layout: 'split', play: 'none', selected: 0 } },
      { id: 'split-row', label: 'Split, another row', state: { layout: 'split', play: 'none', selected: 2 } },
      { id: 'full', label: 'Full', state: { layout: 'full', play: 'playing', selected: 0 } },
      { id: 'full-idle', label: 'Full, nothing playing', state: { layout: 'full', play: 'none', selected: 0 } },
      // stock's own page: no theme key shows here but the paper, the ink and the bar
      { id: 'carousel', label: 'Carousel', state: { layout: 'carousel', play: 'playing', selected: 0 }, themable: false },
    ],
  };
  return Q2Draw;
});
