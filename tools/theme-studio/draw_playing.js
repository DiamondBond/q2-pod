// SPDX-License-Identifier: GPL-3.0-only
// Part of Q2 Theme Studio, which holds work from DiamondBond/q2-pod (GPL-3.0-only): see LICENSE at the repository root.
// Q2 Theme Studio preview: Now Playing in its three layouts (the iPod page, the iPod classic's page of a
// set with np_ipod, the Centred page), the volume as it shows over Now Playing or over another page, and
// the confirm dialog in each painter's forms. DRAWING.md sections 7, 8 and 9 say what is drawn; this file
// only places it, with every colour, size and face taken from env (PREVIEW_API.md).
//
// Screens added: now-playing, volume, confirm. State keys of their own, beside Q2Draw.STATE's:
//   now-playing  elapsed, length (seconds), index, count, song, artist, album, cover (an album's number, or
//                null for the "no cover" plate), favourite, mode ('order', 'random', 'cycle', 'cycle1'),
//                scrubbing, layout ('ipod' / 'centred': stands in for the theme's and the setting's)
//   volume       level, max, over (the screen id it shows over; 'now-playing' unless given), and
//                now-playing's keys for the page under it; page (an object: that page's own state keys,
//                and title and home for the bar, over its first state)
//   confirm      form ('page' / 'tray': the classic-light and flat painters' two), prompt, verb (the tray's
//                second cell), check (null: none; false / true: Delete File's box), over, page (as the
//                volume's), selected (0 Cancel, 1 OK)
// Under a flat pages painter Now Playing's marks are the flat look's; volume.panel.painter flat and a flat
// dialog.confirm.painter draw the flat look's panel and prompt (DRAWING.md section 15).
//
// The positions are the firmware's own constants (tools/ipod.py, patch/offsets.inc), stated from the page
// window's top so that a set with another bar height moves them with it.
(function (root, add) {
  if (typeof module === 'object' && module.exports) module.exports = add(require('./draw_core.js'));
  else add(root.Q2Draw);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (Q2Draw) {
  'use strict';

  const W = Q2Draw.W;
  const H = Q2Draw.H;
  const div = Q2Draw.div;
  const clamp = Q2Draw.clamp;

  const BAR_MID = 255; // the window row every progress bar is centred on (the slider's 44 px touch box)
  const TOUCH = 44; // that box's height
  const REFLECT = [38, 31, 25, 19, 12, 6]; // the gloss bar's mirror, of 256, row by row under it
  const SCRUB_MARK = 8; // half the scrub diamond's width
  const SLANT_FAR = 224; // the slanted art's far edge, of 256 of its near one
  const SLANT_MIRROR = 84; // its reflection's strength at the fold, of 256
  const SLANT_FADE = 22; // and how far down it reaches, in percent of the column's height
  const TIMES_PX = 14; // the times under a plain bar, and "Volume N" in their place
  const IPOD_TIME_PX = 21; // the times beside the gloss bar
  const VOL_PCT_PX = 20; // "N%" where the page dots were
  const PROMPT_PX = 24; // the stock confirm's prompt
  const CELL_PX = 23; // the classic-light confirm's cells
  const CONFIRM_TOP = 208; // the stock confirm's first row
  const CONFIRM_ROW = 48;
  // The classic-light confirm's track on the light half, one colour a row (patch/navigation.c).
  const CONFIRM_LIGHT = [0x7389a5, 0x7b90a9, 0x8094ac, 0x8598af, 0x8a9cb2, 0x8fa0b5, 0x94a4b9, 0x98a8bc, 0x9dacbf, 0xa2b0c1, 0xa5b2c3, 0xa8b5c5, 0xaab7c7, 0xadb9c9, 0xb0bccb,
    0xb3becd, 0xb5c0ce, 0xb7c1cf, 0xb8c2d0, 0xb9c3d1, 0xbbc4d2, 0xbcc5d3, 0xbec7d4, 0xbfc8d4, 0xbfc8d4, 0xc0c8d5, 0xc0c8d5, 0xbfc8d5, 0xbfc7d4, 0xbec7d4];
  const CONFIRM_DARK = [[0, 0x14171c], [30, 0x1d2127], [85, 0x2a2f36], [100, 0x191c21]];
  const CONFIRM_TRAY = [[0, 0x6a707a], [8, 0x565c66], [20, 0x464b54], [34, 0x343840], [44, 0x22252c], [49, 0x121419], [92, 0x111216], [100, 0x1b1f26]];
  const CONFIRM_WELL = [[0, 0x07090d], [25, 0x0e1015], [70, 0x15181e], [90, 0x1c1f26], [100, 0x0b0d12]];
  const INSET_TOP = [239, 177, 79, 17]; // an inset shadow's four rows, of 256 of its alpha
  const SHADE_FADE = [255, 255, 255, 255, 255, 242, 230, 217, 204, 191, 178, 166, 153, 140, 127, 115, 102, 92, 83, 73, 63, 53, 44, 34, 24, 15, 5, 0, 0, 0];
  const SHADE_PART = [7, 5, 3, 1];
  const FLAT_MARK = 32; // NP_BOX: Now Playing's flat glyphs, square
  const FLAT_CELL_H = 36; // CONFIRM_FLAT_H: the flat confirm's cells, capsules
  const FLAT_CELL_PX = 21; // CONFIRM_FLAT_PX
  const FLAT_CELL_GAP = 8; // between the two cells
  const TOAST = 0x2b2b2b; // TOAST_RGBA: the flat volume panel and the confirm's tray, at TOAST_A
  const TOAST_A = 0xee;
  const TRAY_REST = 0x48484a; // CONFIRM_TRAY_REST: a tray cell at rest
  const FLAT_TRACK = 0x6b6b6b; // the flat volume panel's track
  const TICK = [[0, 11, 2], [1, 10, 2], [2, 9, 2], [3, 8, 2], [4, 0, 2], [4, 7, 2], [5, 1, 2], [5, 6, 2], [6, 2, 2], [6, 5, 2], [7, 3, 3]]; // dy, x, w of each line

  // ------------------------------------------------------------------------------------------ helpers

  // A rounded rectangle's outline as the current path's next part (core's).
  const roundPath = Q2Draw.roundRectPath;

  // Runs paint with the canvas clipped to a rounded rectangle: the firmware's rounded rows.
  function rounded(ctx, x, y, w, h, r, paint) {
    ctx.save();
    ctx.beginPath();
    roundPath(ctx, x, y, w, h, r);
    ctx.clip();
    paint();
    ctx.restore();
  }

  // The same, clipped to everything but the rounded rectangle.
  function outside(ctx, x, y, w, h, r, paint) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, W, H);
    roundPath(ctx, x, y, w, h, r);
    ctx.clip('evenodd');
    paint();
    ctx.restore();
  }

  // The share of a Gaussian of deviation 1 that lies past z.
  function tail(z) {
    const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
    const erf = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-(z * z) / 2);
    return z >= 0 ? (1 - erf) / 2 : (1 + erf) / 2;
  }

  // A box's soft shadow as tools/art.py draws one into an image: the box's shape `drop` px lower, blurred
  // by a Gaussian of deviation sigma, black at alpha, and nothing under the box itself. Drawn as rings of
  // rounded rectangles, each a pixel further in, that add up to the blur's fall-off.
  function softShadow(ctx, env, x, y, w, h, r, drop, sigma, alpha) {
    const reach = Math.ceil(3 * sigma);
    outside(ctx, x, y, w, h, r, () => {
      let laid = 0; // the share already laid down by the rings outside this one
      for (let e = reach; e > -reach; e -= 1) {
        const want = (alpha / 255) * tail((e - 0.5) / sigma);
        const a = laid < 1 ? 1 - (1 - want) / (1 - laid) : 0;
        if (w + 2 * e > 0 && h + 2 * e > 0 && a > 0) env.rrect(ctx, x - e, y + drop - e, w + 2 * e, h + 2 * e, Math.max(0, r + e), 0x000000, a * 255);
        laid = want;
      }
    });
  }

  // The accent's selection band over h rows, as the classic-light painters lay it on a bar or a cell. A
  // scheme with no band (fewer than two scheme.sel.stops) reads as black there, as the firmware's does.
  function band(env, h) {
    const rows = env.rows(env.S.sel, h);
    return rows.length ? rows : new Array(h).fill(0x000000);
  }

  // The caller's state for the page under a pop-up (state.page), or none.
  const pageState = (state) => (state.page && typeof state.page === 'object' ? state.page : null);

  // The page under a pop-up: the screen named, drawn in its first state with the caller's bar, then
  // state.page over that (a plain object of the page's own state keys, and title and home for the bar);
  // with no screen file for it, the paper and the bar alone.
  function under(ctx, env, state, id) {
    const page = Q2Draw.PAGES[id] || {};
    const screen = id !== 'volume' && id !== 'confirm' ? Q2Draw.screens[id] : null;
    const first = screen && screen.states && screen.states[0] ? screen.states[0].state : null;
    const s = Object.assign({}, state, { title: page.title || '', home: Boolean(page.home) }, first, pageState(state));
    env.fill(ctx, 0, 0, W, H, env.page);
    if (screen) screen.draw(ctx, env, s);
    else Q2Draw.bar(ctx, env, s);
    return s;
  }

  // ---------------------------------------------------------------------------------- Now Playing: what

  // The track on the page: the sample library's, with whatever the state replaces.
  function track(env, state) {
    const p = env.sample.playing;
    const pick = (key, was) => (state[key] === undefined ? was : state[key]);
    const length = Math.max(0, Number(pick('length', p.length)) || 0);
    return {
      title: String(pick('song', p.title)),
      artist: String(pick('artist', p.artist)),
      album: String(pick('album', p.album)),
      cover: pick('cover', p.cover),
      index: pick('index', p.index),
      count: pick('count', p.count),
      length,
      elapsed: clamp(Number(pick('elapsed', p.elapsed)) || 0, 0, length),
    };
  }

  // Where everything on the page is, in screen pixels, for a track `length` seconds long.
  //   kind     'centred', 'classic' (a set with np_ipod: slanted art, the times beside the bar) or 'ipod'
  //   gloss    the theme's gloss bar is drawn (playing.scrubber.stops has stops), else the plain one
  //   beside   the times share the bar's rows
  //   slider   the bar's touch box; bar: the bar itself at the theme's height; bh: that height
  function layout(env, state = {}, length = 0) {
    const top = env.bar;
    const at = (x, y, w, h) => ({ x, y: top + y, w, h });
    const asked = state.layout === 'centred' || state.layout === 'ipod' ? state.layout : null;
    const centred = asked ? asked === 'centred' : env.npCentred || env.choice('playing.layout') === 'centred';
    const kind = centred ? 'centred' : env.G.np_ipod ? 'classic' : 'ipod';
    const stops = env.T('playing.scrubber.stops');
    const bh = env.T('playing.scrubber.height');
    const L = { kind, top, bh, gloss: Boolean(stops && stops.length >= 2), beside: kind === 'classic' };
    if (kind === 'centred') {
      Object.assign(L, {
        back: at(3, 0, 85, 60), heart: at(2, 132, 86, 73), more: at(295, 0, 70, 60), mode: at(287, 129, 86, 73), lift: 5,
        title: at(10, 198, 355, 20), artist: at(10, 224, 355, 16), elapsed: at(52, 266, 48, 14), remain: at(288, 266, 48, 14),
        art: at(102, 8, 180, 180), glyph: at(132, 38, 120, 120), dots: at(80, 270, 225, 10), slider: at(50, BAR_MID - TOUCH / 2, 290, TOUCH),
      });
    } else if (kind === 'classic') {
      // the times' boxes and the bar are fitted to the track: "-9:59", "-59:59" or "-9:59:59" wide
      const tw = length < 600 ? 35 : length < 3600 ? 43 : 56;
      const x = 66 - 35 + tw;
      const bw = W - 2 * x;
      Object.assign(L, {
        art: at(16, 22, 178, 218), glyph: at(45, 51, 120, 120), title: at(206, 38, 153, 28), artist: at(206, 72, 153, 22), album: at(206, 100, 153, 22),
        mode: at(244, 165, 50, 50), heart: at(300, 165, 50, 50), position: at(208, 128, 151, 20), dots: at(0, 222, W, 10),
        elapsed: at(x - 8 - tw, 244, tw, 21), remain: at(x + bw + 8, 244, tw, 21), more: at(300, 0, 50, 40), lift: 0,
        slider: at(x, BAR_MID - div(bh, 2), bw, bh),
      });
    } else {
      Object.assign(L, {
        more: at(303, 0, 50, 40), position: at(22, 0, 281, 40), elapsed: at(46, 265, 80, 16), remain: at(249, 265, 80, 16),
        art: at(16, 42, 166, 166), glyph: at(39, 65, 120, 120), title: at(194, 58, 165, 28), artist: at(194, 92, 165, 22), album: at(194, 120, 165, 22),
        mode: at(247, 173, 50, 50), heart: at(303, 173, 50, 50), dots: at(0, 222, W, 10), lift: 0, slider: at(21, BAR_MID - TOUCH / 2, 333, TOUCH),
      });
    }
    L.bar = { x: L.slider.x, y: L.slider.y + div(L.slider.h - bh, 2), w: L.slider.w, h: bh };
    return L;
  }

  // ------------------------------------------------------------------------------------------ the art

  // The cover turned as an iPod classic's, with its reflection, as pixels: the firmware's own sums
  // (patch/coverflow.c slant_render). Into a frame side x rows, k times finer for a scaled canvas. The
  // cover's near (left) edge is the frame's width high, its far edge SLANT_FAR / 256 of that; under each
  // column its mirror, fading to the paper.
  function slantPixels(tex, t, side, rows, paper) {
    const out = new Uint8ClampedArray(side * rows * 4);
    const near = side;
    const far = (side * SLANT_FAR) / 256;
    const end = t - 1 - 1 / 256;
    const px = [0, 0, 0];
    for (let x = 0; x < side; x += 1) {
      for (let half = 0; half < 2; half += 1) {
        const c = x + 0.25 + 0.5 * half;
        const h = near - ((near - far) * c) / near;
        const colTop = (near - h) / 2;
        const bot = colTop + h;
        const fade = (h * SLANT_FADE) / 100;
        const k = t / h;
        const fu = clamp((t * (near - h) * far) / (h * (near - far)) - 0.5, 0, end); // linear in depth: in 1 / h
        const iu = Math.floor(fu);
        const wu = fu - iu;
        // one texel of the column, two taps across and two down
        const tap = (v) => {
          const fv = clamp(v - 0.5, 0, end);
          const iv = Math.floor(fv);
          const wv = fv - iv;
          const p = (iv * t + iu) * 4;
          const q = p + t * 4;
          for (let n = 0; n < 3; n += 1) px[n] = (tex[p + n] * (1 - wu) + tex[p + 4 + n] * wu) * (1 - wv) + (tex[q + n] * (1 - wu) + tex[q + 4 + n] * wu) * wv;
        };
        for (let y = 0; y < rows; y += 1) {
          const rgb = [0, 0, 0];
          let left = 1; // the pixel's share that is still paper
          let a = Math.max(y, colTop);
          let b = Math.min(y + 1, bot);
          if (b > a) { // the cover
            const q = (b - a) / 4;
            tap((a + q - colTop) * k);
            for (let n = 0; n < 3; n += 1) rgb[n] += (px[n] * (b - a)) / 2;
            tap((b - q - colTop) * k);
            for (let n = 0; n < 3; n += 1) rgb[n] += (px[n] * (b - a)) / 2;
            left -= b - a;
          }
          a = Math.max(y, bot);
          b = Math.min(y + 1, bot + fade);
          if (b > a) { // its mirror
            const q = (b - a) / 4;
            const m = (SLANT_MIRROR / 256) * (1 - ((a + b) / 2 - bot) / fade);
            tap(t - (a + q - bot) * k);
            for (let n = 0; n < 3; n += 1) rgb[n] += ((paper + (px[n] - paper) * m) * (b - a)) / 2;
            tap(t - (b - q - bot) * k);
            for (let n = 0; n < 3; n += 1) rgb[n] += ((paper + (px[n] - paper) * m) * (b - a)) / 2;
            left -= b - a;
          }
          const o = (y * side + x) * 4;
          for (let n = 0; n < 3; n += 1) {
            const v = rgb[n] + paper * left;
            out[o + n] = half ? (out[o + n] + v) / 2 : v; // each pixel is two half columns
          }
          out[o + 3] = 255;
        }
      }
    }
    return out;
  }

  const slant = { key: '', frame: null }; // the last frame made, kept while the cover and the paper stay

  // The slanted art into x, y, w, h (taller than wide: the reflection's room is under it). Without a
  // scratch canvas to work the pixels on, the cover's outline alone is turned.
  function slantedArt(ctx, env, cover, x, y, w, h) {
    const paper = env.S.paper & 255; // the frame is opaque, on the paper's grey
    const t = typeof ctx.getTransform === 'function' ? ctx.getTransform() : null;
    const k = t && !t.b && !t.c && t.a === t.d ? clamp(Math.ceil(t.a), 1, 4) : 1;
    const key = [cover, paper, w, h, k, env.artSquare].join(' ');
    try {
      if (slant.key !== key || !slant.frame) {
        const side = w * k;
        const size = 2 * side; // the cover is filtered to twice the art before it is turned
        const tex = Q2Draw.makeCanvas(size, size);
        const g = tex.getContext('2d');
        env.fill(g, 0, 0, size, size, Q2Draw.pack(paper, paper, paper));
        if (cover === null || cover === undefined) env.art.placeholder(g, 0, 0, size, env.artSquare); // squared under square art (DRAWING.md 3.7)
        else env.cover(g, cover, 0, 0, size, size);
        const frame = Q2Draw.makeCanvas(side, h * k);
        const f = frame.getContext('2d');
        const image = f.createImageData(side, h * k);
        image.data.set(slantPixels(g.getImageData(0, 0, size, size).data, size, side, h * k, paper));
        f.putImageData(image, 0, 0);
        slant.key = key;
        slant.frame = frame;
      }
      ctx.drawImage(slant.frame, x, y, w, h);
    } catch (e) {
      const far = (w * SLANT_FAR) / 256;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + w, y + (w - far) / 2);
      ctx.lineTo(x + w, y + (w + far) / 2);
      ctx.lineTo(x, y + w);
      ctx.closePath();
      ctx.clip();
      if (cover === null || cover === undefined) env.art.placeholder(ctx, x, y, w, env.artSquare);
      else env.cover(ctx, cover, x, y, w, w);
      ctx.restore();
    }
  }

  // The art in its box: slanted where the box is taller than wide, else square or rounded as the theme
  // and Rounded Corners say (env.artwork).
  function art(ctx, env, cover, box) {
    if (box.h > box.w) slantedArt(ctx, env, cover, box.x, box.y, box.w, box.h);
    else env.artwork(ctx, cover, box.x, box.y, box.w);
  }

  // ------------------------------------------------------------------------------------ progress bars

  // The plain bar (7.8): stock's slider, a track and a fill of the accent, no knob. Scrubbing turns the
  // fill white and, where the theme states another height for it, the bar that high.
  function plainBar(ctx, env, L, on, scrubbing) {
    const tall = env.T('playing.scrubber.scrub_height');
    const h = scrubbing && tall && tall !== L.bh ? tall : L.bh;
    const y = L.slider.y + div(L.slider.h - h, 2);
    const radius = div(L.bh, 2); // set once, from the theme's height: a radius under 3 is square
    env.box(ctx, L.bar.x, y, L.bar.w, h, radius, env.INK(0x1c1c1c));
    env.box(ctx, L.bar.x, y, on, h, radius, scrubbing ? env.INK(0xffffff) : env.progressFill());
  }

  // One part of the gloss bar: a stops list's rows, then its last rows mirrored under it over the paper.
  function glossPart(ctx, env, stops, x, y, w, h) {
    if (w <= 0) return;
    const rows = env.rows(stops, h);
    if (!rows.length) return;
    env.paintRows(ctx, x, y, w, rows);
    REFLECT.forEach((a, k) => env.fill(ctx, x, y + h + k, w, 1, Q2Draw.mix(env.S.paper, rows[h - 1 - k], a, 256)));
  }

  // The gloss bar (7.9), bw wide at x, y with its first `on` columns played: the theme's own fill under
  // its own named scheme, another accent's selection band; the track; a column at each end in the
  // track's last colour; scrub: the scrub's diamond in the ink. All final colours.
  function glossBar(ctx, env, x, y, bw, on, scrub) {
    const h = env.T('playing.scrubber.height');
    const stops = env.T('playing.scrubber.stops');
    const own = env.T('playing.scrubber.fill');
    const line = stops[stops.length - 1][1];
    const side = [[0, line], [100, line]];
    glossPart(ctx, env, own && own.length >= 2 && env.ownScheme ? own : env.S.sel, x, y, on, h);
    glossPart(ctx, env, stops, x + on, y, bw - on, h);
    glossPart(ctx, env, side, x, y, 1, h);
    glossPart(ctx, env, side, x + bw - 1, y, 1, h);
    if (!scrub) return;
    const cx = clamp(on, SCRUB_MARK, bw - 1 - SCRUB_MARK);
    const cy = y + div(h - 1, 2);
    for (let j = -SCRUB_MARK; j <= SCRUB_MARK; j += 1) {
      const half = SCRUB_MARK - Math.abs(j);
      env.fill(ctx, x + cx - half, cy + j, 2 * half + 1, 1, env.S.ink);
    }
  }

  // --------------------------------------------------------------------------------- Now Playing: draw

  // A mark's image centred in its box, `lift` px up.
  function mark(env, name, box, lift = 0) {
    const [x, y] = env.centre(name, box.x, box.y, box.w, box.h);
    return [x, y - lift];
  }

  // More, the play mode and the favourite mark in their boxes: core's stand-ins for stock's pictures
  // (env.art.more, mode, heart), centred and lifted as stock's; or under a flat pages painter the flat look's
  // 32 px glyphs centred on the same boxes (np_marks.c; DRAWING.md 15.4).
  function flatMark(ctx, env, kind, box) {
    env.art.flatMark(ctx, kind, box.x + div(box.w - FLAT_MARK, 2), box.y + div(box.h - FLAT_MARK, 2));
  }
  function moreMark(ctx, env, box, lift = 0) {
    if (env.flatPages) flatMark(ctx, env, 'more', box);
    else env.art.more(ctx, ...mark(env, 'more', box, lift));
  }
  function modeMark(ctx, env, box, kind) {
    if (env.flatPages) flatMark(ctx, env, kind, box);
    else env.art.mode(ctx, ...mark(env, 'mode', box), kind);
  }
  function heartMark(ctx, env, box, on) {
    if (env.flatPages) flatMark(ctx, env, on ? 'heart-on' : 'heart-off', box);
    else env.art.heart(ctx, ...mark(env, 'heart', box), on);
  }

  // The page dots: four, the first lit, 8 px across and 16 apart, centred across their row from its top.
  function dots(ctx, env, row, lit, rest, alpha = 255) {
    const x0 = row.x + Math.floor((row.w - 56) / 2);
    for (let i = 0; i < 4; i += 1) env.disc(ctx, x0 + 16 * i + 4, row.y + 4, 4, i ? rest : lit, i ? alpha : 255);
  }

  // The album line (7.6): the label at the theme's opacity, and over it Minimal's small capitals.
  function album(ctx, env, text, box) {
    const ink = env.INK(0xbbbbbb);
    const opacity = env.T('playing.album.opacity');
    if (opacity > 0) env.label(ctx, text, box.x, box.y, box.w, box.h, { px: 18, colour: ink, alpha: opacity });
    if (env.T('playing.album.caps')) env.caps(ctx, text, box.x + 2, box.y + div(box.h - 15, 2), 15, ink, box.w - 2);
  }

  // Now Playing, everything under the status bar. volume: the page dots make way for the volume's
  // number (8.2). Returns the layout.
  function page(ctx, env, state, volume = false) {
    const song = track(env, state);
    const L = layout(env, state, song.length);
    const time = env.sample.time;
    const grey = env.rowText({ colour: 0xaaaaaa }); // stock's grey: the scheme's muted where it has one
    const glyphs = env.INK(0xeeeeee);
    const position = song.count ? `${song.index} of ${song.count}` : '';
    const kind = state.play === 'playing' ? 'playing' : 'paused';
    const on = song.length > 0 ? div(L.bar.w * song.elapsed, song.length) : 0;
    env.fill(ctx, 0, L.top, W, H - L.top, env.page);

    if (L.kind === 'centred') {
      env.art.back(ctx, ...mark(env, 'back', L.back, L.lift));
      heartMark(ctx, env, L.heart, Boolean(state.favourite));
      moreMark(ctx, env, L.more, L.lift);
      modeMark(ctx, env, L.mode, state.mode || 'order');
      env.label(ctx, song.title, L.title.x, L.title.y, L.title.w, L.title.h, { role: 'np', px: 20, align: 'center', colour: env.fg });
      env.label(ctx, song.artist, L.artist.x, L.artist.y, L.artist.w, L.artist.h, { px: 16, align: 'center', colour: env.fg });
      env.plain(ctx, time(song.elapsed), L.elapsed.x, L.elapsed.y, L.elapsed.w, L.elapsed.h, { px: TIMES_PX, colour: env.fg });
      env.plain(ctx, time(song.length), L.remain.x, L.remain.y, L.remain.w, L.remain.h, { px: TIMES_PX, align: 'right', colour: env.fg });
      art(ctx, env, song.cover, L.art);
      env.art.overlay(ctx, L.glyph.x, L.glyph.y, L.glyph.w, kind, env.T('playing.state.opacity'));
      dots(ctx, env, L.dots, env.style(Q2Draw.STOCK_RED), env.INK(0x666666), 100);
    } else if (L.kind === 'classic') {
      art(ctx, env, song.cover, L.art);
      env.art.overlay(ctx, L.glyph.x, L.glyph.y, L.glyph.w, kind, env.T('playing.state.opacity'));
      env.label(ctx, song.title, L.title.x, L.title.y, L.title.w, L.title.h, { role: 'np', px: 22, colour: env.fg });
      env.label(ctx, song.artist, L.artist.x, L.artist.y, L.artist.w, L.artist.h, { px: 18, colour: env.INK(0xcccccc) });
      album(ctx, env, song.album, L.album);
      modeMark(ctx, env, L.mode, state.mode || 'order');
      heartMark(ctx, env, L.heart, Boolean(state.favourite));
      env.plain(ctx, position, L.position.x, L.position.y, L.position.w, L.position.h, { px: 16, colour: grey });
      if (!volume) dots(ctx, env, L.dots, glyphs, env.INK(0x555555));
      // the times beside the bar are in Classic's face whatever the theme's roles say
      env.plain(ctx, time(song.elapsed), L.elapsed.x, L.elapsed.y, L.elapsed.w, L.elapsed.h, { face: 'classic-light', px: IPOD_TIME_PX, align: 'right', colour: env.fg });
      env.plain(ctx, '-' + time(song.length - song.elapsed), L.remain.x, L.remain.y, L.remain.w, L.remain.h, { face: 'classic-light', px: IPOD_TIME_PX, colour: env.fg });
    } else {
      moreMark(ctx, env, L.more);
      env.plain(ctx, position, L.position.x, L.position.y, L.position.w, L.position.h, { px: 16, colour: grey });
      env.plain(ctx, time(song.elapsed), L.elapsed.x, L.elapsed.y, L.elapsed.w, L.elapsed.h, { px: TIMES_PX, colour: grey });
      env.plain(ctx, '-' + time(song.length - song.elapsed), L.remain.x, L.remain.y, L.remain.w, L.remain.h, { px: TIMES_PX, align: 'right', colour: grey });
      art(ctx, env, song.cover, L.art);
      env.art.overlay(ctx, L.glyph.x, L.glyph.y, L.glyph.w, kind, env.T('playing.state.opacity'));
      env.label(ctx, song.title, L.title.x, L.title.y, L.title.w, L.title.h, { role: 'np', px: 22, colour: env.fg });
      env.label(ctx, song.artist, L.artist.x, L.artist.y, L.artist.w, L.artist.h, { px: 18, colour: env.INK(0xcccccc) });
      album(ctx, env, song.album, L.album);
      modeMark(ctx, env, L.mode, state.mode || 'order');
      heartMark(ctx, env, L.heart, Boolean(state.favourite));
      dots(ctx, env, L.dots, glyphs, env.INK(0x555555));
    }

    if (L.gloss) glossBar(ctx, env, L.bar.x, L.bar.y, L.bar.w, on, Boolean(state.scrubbing));
    else plainBar(ctx, env, L, on, Boolean(state.scrubbing));
    if (L.kind === 'classic') moreMark(ctx, env, L.more);
    return L;
  }

  function drawPlaying(ctx, env, state) {
    page(ctx, env, state);
    Q2Draw.bar(ctx, env, state);
  }

  // ------------------------------------------------------------------------------------------- volume

  // The volume over Now Playing (8.1, 8.2): the bar in the progress bar's place, the number where the
  // times or the page dots were.
  function volumeOverPlaying(ctx, env, state, level, max) {
    const L = page(ctx, env, state, true);
    const bar = L.bar;
    const w = max > 0 ? div(bar.w * level, max) : 0;
    if (L.beside) { // the times make way for two speakers, the dots for "N%"
      env.fill(ctx, L.elapsed.x, L.elapsed.y, L.elapsed.w, L.elapsed.h, env.page);
      env.fill(ctx, L.remain.x, L.remain.y, L.remain.w, L.remain.h, env.page);
    } else env.fill(ctx, 0, L.slider.y, W, L.elapsed.y + L.elapsed.h - L.slider.y, env.page);
    if (L.gloss) glossBar(ctx, env, bar.x, bar.y, bar.w, w, false);
    else {
      env.box(ctx, bar.x, bar.y, bar.w, bar.h, div(bar.h, 2), env.INK(0x1c1c1c));
      if (w) env.box(ctx, bar.x, bar.y, Math.max(w, bar.h), bar.h, div(bar.h, 2), env.volumeFill()); // never a sliver
    }
    if (L.beside) {
      const y = bar.y + div(bar.h - Q2Draw.ART_SIZE.vol_lo[1], 2);
      env.art.volLo(ctx, L.elapsed.x + L.elapsed.w - Q2Draw.ART_SIZE.vol_lo[0], y);
      env.art.volHi(ctx, L.remain.x, y);
      const pct = `${max > 0 ? div(100 * level, max) : 0}%`;
      env.canvasText(ctx, pct, 0, L.dots.y + div(L.dots.h, 2) - div(VOL_PCT_PX, 2) - 2, W, VOL_PCT_PX + 4, VOL_PCT_PX, env.INK(0xffffff));
    } else env.canvasText(ctx, `Volume ${level}`, 0, L.elapsed.y, W, L.elapsed.h, TIMES_PX, env.INK(0xffffff));
    Q2Draw.bar(ctx, env, state);
  }

  // The volume over any other page (8.3), by volume.panel.painter: stock's panel with a pill bar and
  // the number, or the classic-light panel with the gloss rows between two speakers.
  function volumePanel(ctx, env, level, max) {
    if (env.flatVolume) { // DRAWING.md 15.7: the same in both halves and every accent, no number
      const r = { x: 28, y: 256, w: W - 2 * 28, h: 48 };
      const track = { x: r.x + 40, y: r.y + div(r.h, 2) - 2, w: r.w - 92, h: 4 };
      env.box(ctx, r.x, r.y, r.w, r.h, 12, TOAST, TOAST_A);
      env.rrect(ctx, track.x, track.y, track.w, track.h, 2, FLAT_TRACK);
      const on = max > 0 ? div(track.w * level, max) : 0;
      if (on > 0) env.rrect(ctx, track.x, track.y, Math.max(on, track.h), track.h, 2, 0xffffff);
      // flat_spk_* are white and final under the flat pages painter; with another, the image hook's flip
      const ink = env.flatArt(0xffffff);
      env.art.spkQuiet(ctx, r.x + 16, r.y + 17, ink);
      env.art.spkLoud(ctx, r.x + r.w - 38, r.y + 17, ink);
      return;
    }
    if (env.choice('volume.panel.painter') === 'classic-light') {
      const S = env.S;
      const r = { x: 28, y: 256, w: W - 2 * 28, h: 48 };
      softShadow(ctx, env, r.x, r.y, r.w, r.h, 12, 2, 3, 0x33);
      env.rrect(ctx, r.x - 1, r.y - 1, r.w + 2, r.h + 2, 13, S.bar_line);
      rounded(ctx, r.x, r.y, r.w, r.h, 12, () => env.stops(ctx, r.x, r.y, r.w, r.h, S.bar));
      const rows = (key) => env.T(`playing.scrubber.${env.light ? 'light' : 'dark'}_${key}`) || [];
      const tracks = rows('track');
      const fills = rows('fill');
      const other = env.ownScheme ? null : band(env, 17); // another accent: its selection band
      const on = max > 0 ? Math.min(div(243 * level, max), 243) : 0;
      for (let j = 0; j < 17; j += 1) {
        if (j < tracks.length) env.fill(ctx, 68, 271 + j, 243, 1, Q2Draw.argb(tracks[j]).colour, Q2Draw.argb(tracks[j]).alpha);
        if (on <= 0) continue;
        if (other) env.fill(ctx, 68, 271 + j, on, 1, other[j]);
        else if (j < fills.length) env.fill(ctx, 68, 271 + j, on, 1, Q2Draw.argb(fills[j]).colour, Q2Draw.argb(fills[j]).alpha);
      }
      env.art.spkQuiet(ctx, 52, 273);
      env.art.spkLoud(ctx, 317, 273);
      return;
    }
    const area = { x: 26, y: 256, w: W - 2 * 26, h: 48 };
    const bar = { x: area.x + 20, y: area.y + div(area.h - 10, 2), w: area.w - 2 * 20 - 52, h: 10 };
    const w = max > 0 ? div(bar.w * level, max) : 0;
    env.box(ctx, area.x, area.y, area.w, area.h, 12, env.INK(0x2b2b2b), 0xd9);
    env.box(ctx, bar.x, bar.y, bar.w, bar.h, 5, env.INK(0x5a5a5a));
    if (w) env.box(ctx, bar.x, bar.y, Math.max(w, bar.h), bar.h, 5, env.INK(0xffffff));
    env.canvasText(ctx, String(clamp(level, 0, 999)), bar.x + bar.w, area.y, 52, area.h, 20, env.INK(0xffffff));
  }

  function drawVolume(ctx, env, state) {
    const max = state.max > 0 ? Math.floor(state.max) : 100;
    const level = clamp(Math.floor(Number(state.level) || 0), 0, max);
    const over = state.over || 'now-playing';
    if (over === 'now-playing') volumeOverPlaying(ctx, env, state, level, max);
    else {
      under(ctx, env, state, over);
      volumePanel(ctx, env, level, max);
    }
  }

  // ------------------------------------------------------------------------------------------ confirm

  // Delete File's "Also delete source file" box, where stock puts it.
  const CHECK = { x: 40, y: 124, w: 295, h: 40, text: 'Also delete source file' };

  // Stock's check button: a 26 px icon, 10 px and the text, centred together. box: the classic-light
  // painter's own ring and tick in the ink (it empties stock's icons under settings.values.text).
  function checkBox(ctx, env, checked, box) {
    const tw = env.measure(ctx, CHECK.text, 'regular', 20);
    const x0 = CHECK.x + div(CHECK.w - 36 - tw, 2);
    const mid = CHECK.y + div(CHECK.h, 2);
    if (box) {
      const ink = env.S.ink;
      env.ring(ctx, x0 + 3, mid - 10, 20, 20, 6, ink);
      if (checked) for (const [dy, dx, w] of TICK) env.fill(ctx, x0 + 3 + 4 + dx, mid - 10 + 6 + dy, w, 1, ink);
    } else { // a stand-in for stock's own ring and tick
      env.ring(ctx, x0, mid - 13, 26, 26, 13, env.INK(0xffffff), 255, 2);
      if (checked) env.disc(ctx, x0 + 13, mid, 7, env.INK(0xffffff));
    }
    env.plain(ctx, CHECK.text, x0 + 36, CHECK.y, tw, CHECK.h, { px: 20, colour: env.fg });
  }

  // The stock confirm (9.1): the dialog's own full-screen paper, the prompt over two full-width rows,
  // the list's selection behind the one chosen.
  function confirmStock(ctx, env, state) {
    const check = state.check === true || state.check === false;
    env.fill(ctx, 0, 0, W, H, env.page);
    env.text(ctx, state.prompt, 0, 0, W, check ? CHECK.y : CONFIRM_TOP, { px: PROMPT_PX, align: 'center', colour: env.fg });
    if (check) checkBox(ctx, env, state.check, false);
    const chosen = state.selected ? 1 : 0;
    env.selection(ctx, 0, CONFIRM_TOP + chosen * CONFIRM_ROW, W, CONFIRM_ROW, { images: [] });
    ['Cancel', 'OK'].forEach((text, k) => {
      env.text(ctx, text, 0, CONFIRM_TOP + k * CONFIRM_ROW, W, CONFIRM_ROW, { px: 20, align: 'center', colour: env.rowText({ selected: k === chosen }) });
    });
  }

  // A prompt's lines for the classic-light page: a line wider than its box stops at the last space or
  // comma that fits, the rest under it.
  function wrap(ctx, env, text, width) {
    const f = env.canvasFace(28, text);
    const wide = (s) => env.measure(ctx, s, f.face, f.px);
    if (wide(text) <= width) return [text];
    const chars = Array.from(text);
    let cut = 0;
    for (let k = 1; k < chars.length && wide(chars.slice(0, k).join('')) <= width; k += 1) if (chars[k] === ' ' || chars[k - 1] === ',') cut = k;
    if (!cut) return [text];
    return [chars.slice(0, cut).join(''), chars.slice(cut + (chars[cut] === ' ' ? 1 : 0)).join('')];
  }

  // The selected cell of the classic-light confirm: the accent's selection band, a light top row and a
  // dark foot row.
  function litCell(ctx, env, c) {
    rounded(ctx, c.x, c.y, c.w, c.h, 6, () => {
      env.paintRows(ctx, c.x, c.y, c.w, band(env, c.h));
      env.fill(ctx, c.x, c.y, c.w, 1, 0xffffff, 0x73);
      env.fill(ctx, c.x, c.y + c.h - 1, c.w, 1, 0x000000, 0x59);
    });
  }

  // The classic-light confirm (9.2), all in final colours. The page form papers the window and keeps the
  // bar; the tray form sits over the page that raised it.
  function confirmClassic(ctx, env, state) {
    const tray = state.form === 'tray';
    const light = env.light;
    const texts = ['Cancel', tray ? String(state.verb || 'Delete') : 'OK'];
    const widths = texts.map((s) => {
      const f = env.canvasFace(CELL_PX, s);
      return Math.max(76, Math.floor(env.measure(ctx, s, f.face, f.px) + 36.5));
    });
    const y = tray ? 265 : 258;
    const x0 = div(W - widths[0] - widths[1], 2);
    const cells = [{ x: x0, y, w: widths[0], h: 30 }, { x: x0 + widths[0], y, w: widths[1], h: 30 }];
    const t = { x: x0, y, w: widths[0] + widths[1], h: 30 };
    const chosen = state.selected ? 1 : 0;
    const check = state.check === true || state.check === false;

    if (tray) {
      softShadow(ctx, env, 38, 254, 299, 52, 9, 2, 3, 0x77);
      env.ring(ctx, 37, 253, 301, 54, 10, 0x000000, 0x66);
      rounded(ctx, 38, 254, 299, 52, 9, () => env.stops(ctx, 38, 254, 299, 52, CONFIRM_TRAY));
      rounded(ctx, t.x, t.y, t.w, t.h, 6, () => {
        env.stops(ctx, t.x, t.y, t.w, t.h, CONFIRM_WELL);
        INSET_TOP.forEach((part, i) => env.fill(ctx, t.x, t.y + i, t.w, 1, 0x000000, (0xdd * part) >> 8));
      });
    } else {
      env.fill(ctx, 0, env.bar, W, H - env.bar, env.S.paper);
      Q2Draw.bar(ctx, env, state);
      wrap(ctx, env, String(state.prompt), 327).forEach((line, i) => {
        const f = env.canvasFace(28, line);
        env.text(ctx, line, 24, 61 + 30 * i, 327, 30, { face: f.face, px: f.px, align: 'center', pad: 2, ellipsis: true, colour: env.S.ink });
      });
      if (check) checkBox(ctx, env, state.check, Boolean(env.T('settings.values.text')));
      rounded(ctx, t.x, t.y, t.w, t.h, 6, () => {
        if (light) {
          env.paintRows(ctx, t.x, t.y, t.w, CONFIRM_LIGHT);
          [0x02, 0x06, 0x0e, 0x18].forEach((a, c) => env.fill(ctx, t.x + t.w - 4 + c, t.y, 1, t.h, 0x000000, a)); // a shade from the right
        } else {
          env.stops(ctx, t.x, t.y, t.w, t.h, CONFIRM_DARK);
          INSET_TOP.forEach((part, i) => env.fill(ctx, t.x, t.y + i, t.w, 1, 0x000000, (0xaa * part) >> 8));
        }
      });
    }
    env.ring(ctx, t.x, t.y, t.w, t.h, 6, 0x000000, tray || !light ? 0x88 : 0x1a);
    // a light row just under the track: its own bottom row, a pixel lower
    ctx.save();
    ctx.beginPath();
    ctx.rect(t.x, t.y + t.h, t.w, 1);
    ctx.clip();
    env.rrect(ctx, t.x, t.y + 1, t.w, t.h, 6, 0xffffff, !tray && light ? 0xb0 : 0x29);
    ctx.restore();

    const c = cells[chosen];
    if (tray) {
      env.ring(ctx, c.x - 1, c.y - 1, c.w + 2, c.h + 2, 7, 0x000000, 0x77);
      litCell(ctx, env, c);
    } else {
      litCell(ctx, env, c);
      // its light right edge: what the cell's shape leaves a pixel left of itself
      rounded(ctx, c.x, c.y, c.w, c.h, 6, () => outside(ctx, c.x - 1, c.y, c.w, c.h, 6, () => env.fill(ctx, c.x + c.w - 6, c.y, 6, c.h, 0xffffff, 0x4d)));
      // with a cell to its right, a shade over that one's first columns, fading down the rows
      for (let i = 0; !chosen && i < c.h; i += 1) {
        SHADE_PART.forEach((part, k) => {
          const a = div(div(0x36 * part, 8) * (SHADE_FADE[i] || 0), 255);
          env.fill(ctx, c.x + c.w + k, c.y + i, 1, 1, 0x000000, a);
        });
      }
    }
    cells.forEach((cell, k) => {
      env.canvasText(ctx, texts[k], cell.x, cell.y - 1, cell.w, cell.h, CELL_PX, 0x000000, { alpha: 0x4d }); // the text's shadow, a row up
      env.canvasText(ctx, texts[k], cell.x, cell.y, cell.w, cell.h, CELL_PX, light || tray || k === chosen ? 0xffffff : 0xcfd6dc);
    });
  }

  // The flat confirm (DRAWING.md 15.5), dialog.confirm.painter flat or classic-light+flat: two capsules,
  // Cancel and OK, at rest in the flat look's grey and the chosen one in what is on (env.flatOn). The page
  // form papers the window with the flat page's ground, keeps the bar and wraps the prompt as Classic's
  // does; the tray form lays a dark tray over the page that raised it. All colours final.
  function confirmFlat(ctx, env, state) {
    const tray = state.form === 'tray';
    const texts = ['Cancel', tray ? String(state.verb || 'Delete') : 'OK'];
    const widths = texts.map((s) => {
      const f = env.canvasFace(FLAT_CELL_PX, s);
      return Math.max(76, Math.floor(env.measure(ctx, s, f.face, f.px) + 36.5));
    });
    const y = tray ? 258 : 250;
    const x0 = div(W - widths[0] - widths[1] - FLAT_CELL_GAP, 2);
    const cells = [{ x: x0, y, w: widths[0], h: FLAT_CELL_H }, { x: x0 + widths[0] + FLAT_CELL_GAP, y, w: widths[1], h: FLAT_CELL_H }];
    const chosen = state.selected ? 1 : 0;
    const on = env.flatOn();
    if (tray) env.box(ctx, 38, 248, 299, 56, 12, TOAST, TOAST_A);
    else {
      env.fill(ctx, 0, env.bar, W, H - env.bar, env.flatPage);
      Q2Draw.bar(ctx, env, state);
    }
    const rest = tray ? TRAY_REST : env.flatRest;
    for (const c of cells) env.rrect(ctx, c.x, c.y, c.w, c.h, FLAT_CELL_H / 2, rest);
    if (!tray && (state.check === true || state.check === false)) checkBox(ctx, env, state.check, Boolean(env.T('settings.values.text')));
    const lit = cells[chosen];
    env.rrect(ctx, lit.x, lit.y, lit.w, lit.h, FLAT_CELL_H / 2, on);
    cells.forEach((c, k) => {
      const ink = k === chosen ? (Q2Draw.bright(on) ? Q2Draw.FLAT_INK[1] : 0xffffff) : tray ? 0xffffff : env.flatInk;
      env.canvasText(ctx, texts[k], c.x, c.y, c.w, c.h, FLAT_CELL_PX, ink);
    });
    if (tray) return;
    // the prompt: stock's own labels, restyled as Classic's page form (its face, 28 px), white through INK
    wrap(ctx, env, String(state.prompt), 327).forEach((line, i) => {
      const f = env.canvasFace(28, line);
      env.text(ctx, line, 24, 61 + 30 * i, 327, 30, { face: f.face, px: f.px, align: 'center', pad: 2, ellipsis: true, colour: env.INK(0xffffff) });
    });
  }

  function drawConfirm(ctx, env, state) {
    const s = Object.assign({ prompt: 'Shut Down?', form: 'page', check: null }, state);
    const painter = env.choice('dialog.confirm.painter');
    if (!env.flatDialogs && painter !== 'classic-light') {
      confirmStock(ctx, env, s); // its paper covers the page and the bar
      return;
    }
    const over = s.over || 'now-playing';
    const page = Object.assign({}, Q2Draw.PAGES[over] || {}, pageState(s));
    // a pop-up keeps the bar's title of the page under it (state.page may say otherwise)
    if (s.form === 'tray') under(ctx, env, s, over);
    const bar = { title: pageState(s) && page.title !== undefined ? page.title : s.title || page.title || '', home: Boolean(page.home) };
    if (env.flatDialogs) confirmFlat(ctx, env, Object.assign({}, s, bar));
    else confirmClassic(ctx, env, Object.assign({}, s, bar));
  }

  // ------------------------------------------------------------------------------------------ screens

  Q2Draw.screens['now-playing'] = {
    title: 'Now Playing',
    draw: drawPlaying,
    layout, // layout(env, state, length): every box of the page, for a caller that wants them
    states: [
      { id: 'playing', label: 'Playing', state: { play: 'playing' } },
      { id: 'paused', label: 'Paused', state: { play: 'paused' } },
      { id: 'scrubbing', label: 'Scrubbing', state: { play: 'playing', scrubbing: true } },
      { id: 'long', label: 'Long track', state: { play: 'playing', elapsed: 1754, length: 4521 } },
      { id: 'no-cover', label: 'No cover', state: { play: 'playing', cover: null } },
      { id: 'centred', label: 'Centred', state: { play: 'playing', layout: 'centred' } },
    ],
  };

  Q2Draw.screens.volume = {
    title: 'Volume',
    draw: drawVolume,
    states: [
      { id: 'playing', label: 'Over Now Playing', state: { level: 40, over: 'now-playing' } },
      { id: 'page', label: 'Over another page', state: { level: 40, over: 'home' } },
      { id: 'mute', label: 'Muted', state: { level: 0, over: 'now-playing' } },
      { id: 'full', label: 'Full', state: { level: 100, over: 'now-playing' } },
    ],
  };

  Q2Draw.screens.confirm = {
    title: 'Confirm',
    draw: drawConfirm,
    states: [
      { id: 'cancel', label: 'Cancel selected', state: { form: 'page', selected: 0, prompt: 'Shut Down?', over: 'now-playing' } },
      { id: 'ok', label: 'OK selected', state: { form: 'page', selected: 1, prompt: 'Shut Down?', over: 'now-playing' } },
      { id: 'check', label: 'Delete File', state: { form: 'page', selected: 0, prompt: 'Delete this file?', check: true, over: 'now-playing' } },
      { id: 'tray', label: 'Over its page', state: { form: 'tray', selected: 0, verb: 'Delete', over: 'now-playing' } },
    ],
  };
  return Q2Draw;
});
