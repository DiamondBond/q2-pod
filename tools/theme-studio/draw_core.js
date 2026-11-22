// SPDX-License-Identifier: GPL-3.0-only
// Part of Q2 Theme Studio, which holds work from DiamondBond/q2-pod (GPL-3.0-only): see LICENSE at the repository root.
// Q2 Theme Studio preview: the drawing environment every screen file builds on. From a theme's resolved
// values (official.js's resolve()) and the viewer's choices it makes one object, env, that answers DRAWING.md
// sections 0 to 3: any colour, any geometry field, the fonts and where text sits, the repository's own art
// and the redrawn stand-ins for stock's. PREVIEW_API.md is the contract; DRAWING.md says what to draw.
//
// Loaded by a page as window.Q2Draw and under node as a module. Screen files add themselves to the same
// object (Q2Draw.bar, Q2Draw.screens[id]). Everything draws into a CanvasRenderingContext2D in the Q2's own
// 375 x 320 pixels; the caller scales the canvas.
//
// Conventions: a colour is an integer 0xRRGGBB (col() also takes '#rrggbb'); an alpha is 0..255 as the
// firmware states it; rectangles are x, y, w, h in screen pixels; integer division truncates as C's.
//
// The path data of the bar's marks, Classic's art and Home's pane icons is the firmware project's own
// (DiamondBond/q2-pod, tools/ipod.py, tools/art.py and assets/themes/classic-light/note.svg, GPL-3.0-only).
// No stock Shanling image or font is in this file: stock's pictures are redrawn here as plain stand-ins.
(function (root, make) {
  if (typeof module === 'object' && module.exports) module.exports = make();
  else root.Q2Draw = make();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const W = 375;
  const H = 320;
  const GLASS_R = 80; // the glass's corner radius (patch/offsets.inc GLASS_R)
  const SEL_INSET = 6; // a card's or pill's inset from the screen's sides
  const STOCK_RED = 0xff1448;

  const div = (a, b) => Math.trunc(a / b); // C's integer division
  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

  // ------------------------------------------------------------------------------------------- colour

  // A colour as 0xRRGGBB, from that or from '#rrggbb'.
  const col = (c) => (typeof c === 'string' ? parseInt(c.replace('#', ''), 16) : c);
  const rgb = (c) => [(c >> 16) & 255, (c >> 8) & 255, c & 255];
  const pack = (r, g, b) => ((r << 16) | (g << 8) | b) >>> 0;
  const hex = (c) => '#' + col(c).toString(16).padStart(6, '0');
  // A canvas fill style: the colour at alpha 0..255.
  function css(c, alpha = 255) {
    if (alpha >= 255) return hex(c);
    const [r, g, b] = rgb(col(c));
    return `rgba(${r},${g},${b},${Math.max(alpha, 0) / 255})`;
  }
  // A row list's entry 0xAARRGGBB as { colour, alpha }.
  const argb = (v) => ({ colour: v & 0xffffff, alpha: (v >>> 24) & 255 });

  // j / n of the way from a to b, per channel (theme_engine.c mix).
  function mix(a, b, j, n) {
    const x = rgb(a);
    const y = rgb(b);
    return pack(...x.map((v, i) => div(v * (n - j) + y[i] * j, n)));
  }

  // Whether a colour is a grey as Light Mode sees it: its channels within spread (LIGHT_SPREAD, 16).
  function neutral(c, spread = 16) {
    const ch = rgb(c);
    return Math.max(...ch) - Math.min(...ch) <= spread;
  }

  // Light Mode's flip of a grey between the light half's paper and ink; any other hue as it is.
  function flip(c, paper, ink, spread = 16) {
    if (!neutral(c, spread)) return c;
    const p = paper & 255;
    const i = ink & 255;
    return pack(...rgb(c).map((v) => p - div(v * (p - i), 255)));
  }

  // The colours of a band h rows high painted from a stops list [[position %, colour], ...]: one per row
  // (navigation.c stops_row). As many stops as rows: each row its own. Fewer than two stops: no rows.
  function stopsRows(stops, h) {
    const out = [];
    if (!stops || stops.length < 2) return out;
    const n = stops.length;
    for (let j = 0; j < h; j += 1) {
      if (n === h) {
        out.push(stops[j][1]);
        continue;
      }
      const p = h > 1 ? div(j * 25600, h - 1) : 0;
      let k = 0;
      while (k + 2 < n && p > stops[k + 1][0] * 256) k += 1;
      const lo = stops[k][0] * 256;
      out.push(mix(stops[k][1], stops[k + 1][1], p - lo, stops[k + 1][0] * 256 - lo));
    }
    return out;
  }

  // Stock red blended with a neutral becomes the same blend of tone (theme_engine.c red_map). glyph is the
  // colour the white part takes; light puts the red share over the paper. Any other colour comes back as is.
  function redMap(c, tone, glyph, light, paper = 0, ink = 0) {
    const red = rgb(STOCK_RED);
    const sum = red[0] + red[1] + red[2];
    const ch = rgb(c);
    const s = ch[0] + ch[1] + ch[2];
    let d = 0;
    let dd = 0;
    for (let i = 0; i < 3; i += 1) {
      d += (3 * ch[i] - s) * (3 * red[i] - sum);
      dd += (3 * red[i] - sum) * (3 * red[i] - sum);
    }
    let t = div(d * 4096, dd);
    if (t < 256 && glyph !== 0xffffff) t = 0;
    const k = div(s * 4096 - t * sum, 3 * 4096);
    if ((t && t < 256) || t > 4096 + 256 || k < -8) return c;
    const p = light ? paper & 255 : 0;
    const q = light ? ink & 255 : 0;
    const to = rgb(tone);
    const gl = rgb(glyph);
    const out = [];
    for (let i = 0; i < 3; i += 1) {
      const miss = ch[i] - (div(t * red[i], 4096) + k);
      if (miss > 8 || miss < -8) return c;
      const v = div(t * to[i], 4096) + (light ? div((t < 4096 ? 4096 - t : 0) * p, 4096) - div(k * (p - q), 255) : div(k * gl[i], 255));
      out.push(clamp(v, 0, 255));
    }
    return pack(...out);
  }

  // --------------------------------------------------------------------------------------------- frame

  // The width the glass hides at each end of screen row y (tools/ipod.py corner_inset).
  function glassInset(y) {
    const d = Math.min(Math.max(GLASS_R - y, y - (H - GLASS_R), 0), GLASS_R);
    return Math.ceil(GLASS_R - Math.sqrt(GLASS_R * GLASS_R - d * d));
  }

  // Clears what the glass hides: the screen's four corners, row by row by glassInset, so every row loses
  // exactly the firmware's width (a smooth path would hide fewer columns on the rows near a corner). Apply
  // last; the reference pictures have none.
  function glass(ctx) {
    for (let y = 0; y < H; y += 1) {
      const n = glassInset(y);
      if (!n) continue;
      ctx.clearRect(0, y, n, 1);
      ctx.clearRect(W - n, y, n, 1);
    }
  }

  // ------------------------------------------------------------------------------------------- shapes

  function fill(ctx, x, y, w, h, c, alpha = 255) {
    if (w <= 0 || h <= 0 || alpha <= 0) return;
    ctx.fillStyle = css(c, alpha);
    ctx.fillRect(x, y, w, h);
  }

  // One 1 px row per colour, from y down.
  function rows(ctx, x, y, w, colours) {
    for (let j = 0; j < colours.length; j += 1) fill(ctx, x, y + j, w, 1, colours[j]);
  }

  // A stops list over a band, final colours (navigation.c paint_stops).
  function paintStops(ctx, x, y, w, h, stops) {
    rows(ctx, x, y, w, stopsRows(stops, h));
  }

  // A vertical canvas gradient of a stops list from y0 to y1, for paths a row painter cannot fill.
  function gradient(ctx, stops, y0, y1, alpha = 255) {
    const g = ctx.createLinearGradient(0, y0, 0, y1);
    for (const [p, c] of stops) g.addColorStop(clamp(p / 100, 0, 1), css(c, alpha));
    return g;
  }

  function roundRectPath(ctx, x, y, w, h, r) {
    const q = Math.max(0, Math.min(r, w / 2, h / 2));
    ctx.moveTo(x + q, y);
    ctx.lineTo(x + w - q, y);
    ctx.arcTo(x + w, y, x + w, y + q, q);
    ctx.lineTo(x + w, y + h - q);
    ctx.arcTo(x + w, y + h, x + w - q, y + h, q);
    ctx.lineTo(x + q, y + h);
    ctx.arcTo(x, y + h, x, y + h - q, q);
    ctx.lineTo(x, y + q);
    ctx.arcTo(x, y, x + q, y, q);
    ctx.closePath();
  }

  // A filled rounded rectangle; style is a colour or a canvas gradient. r 0 is a plain rectangle.
  function rrect(ctx, x, y, w, h, r, style, alpha = 255) {
    if (w <= 0 || h <= 0) return;
    ctx.fillStyle = typeof style === 'number' || typeof style === 'string' ? css(style, alpha) : style;
    if (r <= 0) {
      ctx.fillRect(x, y, w, h);
      return;
    }
    ctx.beginPath();
    roundRectPath(ctx, x, y, w, h, r);
    ctx.fill();
  }

  // The firmware's fill_box: rounded at radius 3 and over, square under it (stock declines a smaller one).
  function box(ctx, x, y, w, h, r, c, alpha = 255) {
    rrect(ctx, x, y, w, h, r < 3 ? 0 : r, c, alpha);
  }

  // A 1 px ring just inside a rounded rectangle.
  function ring(ctx, x, y, w, h, r, c, alpha = 255, width = 1) {
    ctx.save();
    ctx.strokeStyle = css(c, alpha);
    ctx.lineWidth = lineWidth(width);
    ctx.beginPath();
    roundRectPath(ctx, x + width / 2, y + width / 2, w - width, h - width, Math.max(0, r - width / 2));
    ctx.stroke();
    ctx.restore();
  }

  function disc(ctx, cx, cy, r, c, alpha = 255) {
    ctx.fillStyle = css(c, alpha);
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fill();
  }

  // Rows whose ends follow a circle of the given radius, one antialiased pixel at each end: the firmware's
  // own pill (navigation.c gradient). colours: one per row. radius 0 is square.
  function pillRows(ctx, x, y, w, colours, radius) {
    const h = colours.length;
    const D = 2 * radius;
    for (let j = 0; j < h; j += 1) {
      let out = 0;
      let d = 2 * j + 1 - h;
      d = (d < 0 ? -d : d) - (h - D);
      if (radius && d > 0) {
        const v = (D * D - d * d) * 64;
        const k = Math.min(Math.floor(Math.sqrt(Math.max(v, 0))), 8 * D);
        out = 8 * D - k;
      }
      const inset = (out + 15) >> 4;
      fill(ctx, x + inset, y + j, w - 2 * inset, 1, colours[j]);
      if (out & 15) {
        const a = (16 - (out & 15)) * 17;
        fill(ctx, x + inset - 1, y + j, 1, 1, colours[j], a);
        fill(ctx, x + w - inset, y + j, 1, 1, colours[j], a);
      }
    }
  }

  // A pill's end radius on a row h high whose card is inset px from the row's left, kept clear of the
  // row's leading images (navigation.c pill_radius). images: [{ x, y, w, h, centre }] in the row button's
  // coordinates; centre marks an image drawn centred in its box (a disc: not tested).
  function pillRadius(h, images = [], inset = SEL_INSET) {
    let r = div(h, 2);
    for (const im of images) {
      if (im.centre) continue;
      const x = im.x - inset;
      let y = im.y;
      if (im.w <= 0 || im.h <= 0 || x < 0 || x >= r) continue;
      if (h - y - im.h < y) y = h - y - im.h;
      while (r > 2 && y >= 0 && y < r && (r - x) * (r - x) + (r - y) * (r - y) > r * r) r -= 1;
    }
    return r;
  }

  // Path helpers for art given as SVG path data. Under node the host supplies a global Path2D.
  const path2d = (d) => new globalThis.Path2D(d);
  // A 1 px stroke is drawn a hair wider: at exactly one device pixel a browser's canvas takes a short cut
  // that leaves out the joins and caps.
  const lineWidth = (w) => (w === 1 ? 1.001 : w);
  function strokePath(ctx, d, x, y, width, c, alpha = 255, cap = 'round') {
    ctx.save();
    ctx.translate(x, y);
    ctx.strokeStyle = typeof c === 'number' ? css(c, alpha) : c;
    ctx.lineWidth = lineWidth(width);
    ctx.lineCap = cap;
    ctx.lineJoin = 'round';
    ctx.stroke(path2d(d));
    ctx.restore();
  }
  function fillPath(ctx, d, x, y, c, alpha = 255, rule = 'evenodd') {
    ctx.save();
    ctx.translate(x, y);
    ctx.fillStyle = typeof c === 'number' ? css(c, alpha) : c;
    ctx.fill(path2d(d), rule);
    ctx.restore();
  }

  // A scratch canvas of w x h for a screen that needs pixels of its own (the slanted art). The harness
  // replaces this under node.
  function makeCanvas(w, h) {
    if (typeof OffscreenCanvas === 'function') return new OffscreenCanvas(w, h);
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    return c;
  }

  // -------------------------------------------------------------------------------------------- fonts

  // The three faces (DRAWING.md 3.1, 3.2). family is what the page's @font-face rules (and the harness)
  // name the two open fonts; regular is a stand-in for stock's font, which may not be shipped. The numbers
  // are each font's unitsPerEm and hhea ascent and descent; has lists the code points the device's cut of
  // the face holds (the build's BOLD_RANGES and CLASSIC_LIGHT_RANGES), null for every character.
  const FACES = {
    // Stock's font keeps Arial's advances cut down to its own 256-unit em, but for the space and the
    // underscore: grid and adv make the stand-in step the same (numbers only; no part of the font).
    regular: { family: 'Arial, "Liberation Sans", Helvetica, sans-serif', weight: 400, em: 256, ascent: 230, descent: -69, cap: 183, xh: 133, has: null, grid: 256, adv: { ' ': 75, _: 128 } },
    bold: {
      family: '"Q2 Liberation Sans Bold", "Liberation Sans", Arial, Helvetica, sans-serif', weight: 700, em: 2048, ascent: 1854, descent: -434, cap: 1409, xh: 1082,
      has: [0x20, 0x7e, 0xa0, 0x36f, 0x374, 0x375, 0x37a, 0x37e, 0x384, 0x38a, 0x38c, 0x38c, 0x38e, 0x3a1, 0x3a3, 0x3ce, 0x3d0, 0x513, 0x51a, 0x51d, 0x1ea0, 0x1ef9,
        0x2000, 0x2010, 0x2012, 0x2022, 0x2026, 0x2026, 0x202a, 0x2030, 0x2032, 0x2034, 0x2039, 0x203a, 0x203c, 0x203c, 0x203e, 0x203e, 0x2044, 0x2044, 0x205e, 0x205e,
        0x206a, 0x206f, 0x2074, 0x2079, 0x207f, 0x2089, 0x2090, 0x2094, 0x20a0, 0x20b5, 0x20bf, 0x20bf, 0x20f0, 0x20f0, 0x2105, 0x2105, 0x2113, 0x2113, 0x2116, 0x2117,
        0x2122, 0x2122, 0x2126, 0x2126, 0x212e, 0x212e, 0x214d, 0x214e, 0x2153, 0x2154, 0x215b, 0x215e, 0x2184, 0x2184, 0x2190, 0x2195, 0x21a8, 0x21a8, 0x21d4, 0x21d4,
        0x25b6, 0x25b6],
    },
    'classic-light': {
      family: '"Q2 TeX Gyre Heros Bold", "TeX Gyre Heros", Arial, Helvetica, sans-serif', weight: 700, em: 1000, ascent: 1125, descent: -307, cap: 729, xh: 540,
      has: [0x20, 0x7e, 0xa0, 0x137, 0x139, 0x148, 0x14a, 0x165, 0x168, 0x17f, 0x18e, 0x18e, 0x192, 0x192, 0x1a0, 0x1a1, 0x1af, 0x1b0, 0x1cd, 0x1d4, 0x1d7, 0x1dd,
        0x1e6, 0x1e7, 0x1ea, 0x1eb, 0x1f0, 0x1f0, 0x1f4, 0x1f5, 0x1fa, 0x201, 0x204, 0x205, 0x208, 0x209, 0x20c, 0x20d, 0x210, 0x211, 0x214, 0x215, 0x218, 0x21b,
        0x237, 0x237, 0x258, 0x259, 0x2be, 0x2bf, 0x2c6, 0x2c7, 0x2d8, 0x2dd, 0x300, 0x304, 0x306, 0x30c, 0x30f, 0x30f, 0x311, 0x311, 0x323, 0x323, 0x326, 0x326,
        0x32e, 0x332, 0x391, 0x3a1, 0x3a3, 0x3a9, 0x3b1, 0x3c9, 0x3d1, 0x3d1, 0x3d5, 0x3d6, 0x3f1, 0x3f1, 0x3f5, 0x3f5, 0x1ea0, 0x1ef9, 0x2010, 0x2011, 0x2013, 0x2014,
        0x2016, 0x2016, 0x2018, 0x201a, 0x201c, 0x201e, 0x2020, 0x2022, 0x2026, 0x2026, 0x2030, 0x2031, 0x2039, 0x203b, 0x203d, 0x203d, 0x203f, 0x2040, 0x2044, 0x2046,
        0x2052, 0x2052, 0x2054, 0x2054, 0x20a1, 0x20a1, 0x20a4, 0x20a4, 0x20a6, 0x20a6, 0x20a9, 0x20a9, 0x20ab, 0x20ac, 0x20b1, 0x20b1, 0x2103, 0x2103, 0x2113, 0x2113,
        0x2116, 0x2118, 0x211e, 0x211e, 0x2120, 0x2120, 0x2122, 0x2122, 0x2126, 0x2127, 0x212e, 0x212e, 0x2190, 0x2193, 0x25b6, 0x25b6],
    },
  };
  const FACE_NAMES = ['regular', 'bold', 'classic-light']; // the order of a font key's stored value
  // A text role's two keys, and no more: the widget's own style size is the caller's to give.
  const ROLES = {
    title: ['list.row.font', 'list.row.title_px'],
    meta: ['list.row.meta_font', 'list.row.meta_px'],
    tall: ['list.row.tall_font', 'list.row.tall_px'],
    bar: ['bar.title.font', 'bar.title.font_size'],
    np: ['playing.title.font', 'playing.title.font_px'],
    home: ['home.rows.font', 'home.rows.font_px'],
    info: ['playing.info.font', 'playing.info.font_size'],
  };

  // Whether a face's device cut holds every character of the text.
  function faceHas(face, text) {
    const ranges = FACES[face].has;
    if (!ranges) return true;
    for (const ch of text) {
      const u = ch.codePointAt(0);
      let i = 0;
      while (i < ranges.length && (u < ranges[i] || u > ranges[i + 1])) i += 2;
      if (i >= ranges.length) return false;
    }
    return true;
  }

  // The face and px a text is really drawn in when its role's face lacks a character (script.c script_face):
  // Classic's falls to bold, or to stock's with a second pass, at 83 % of the px; bold falls to stock's at
  // the same px with the second pass. A px of 0 stays 0.
  function fallback(face, px, text) {
    if (faceHas(face, text)) return { face, px, faux: false };
    if (face !== 'classic-light') return { face: 'regular', px, faux: true };
    const less = px ? div(px * 83 + 50, 100) : 0;
    return faceHas('bold', text) ? { face: 'bold', px: less, faux: false } : { face: 'regular', px: less, faux: true };
  }

  // A face at a firmware px: the CSS font to set, and where the line sits. The device scales a face so that
  // ascent minus descent is the px, and puts the baseline the rounded ascent under the line box's top.
  function metrics(face, px) {
    const f = FACES[face];
    const span = f.ascent - f.descent;
    return {
      font: `${f.weight} ${(px * f.em) / span}px ${f.family}`,
      ascent: Math.floor((px * f.ascent) / span + 0.5),
      cap: (px * f.cap) / span,
      xh: (px * f.xh) / span,
    };
  }

  const advances = new Map(); // font -> Map(character -> rounded advance)
  const MEASURE_AT = 32; // advances are measured this many times larger, where no hinting rounds them
  const larger = (font) => font.replace(/ ([0-9.]+)px /, (m, size) => ` ${size * MEASURE_AT}px `);
  // One character's advance as the device steps it: its plain advance at the size rounded to a whole
  // pixel, no kerning.
  function advance(ctx, face, px, ch) {
    const f = FACES[face];
    const m = metrics(face, px);
    let table = advances.get(m.font);
    if (!table) advances.set(m.font, (table = new Map()));
    let w = table.get(ch);
    if (w === undefined) {
      const size = (px * f.em) / (f.ascent - f.descent);
      ctx.font = larger(m.font);
      let wide = ctx.measureText(ch).width / MEASURE_AT;
      if (f.grid) wide = ((f.adv && f.adv[ch]) || Math.floor((wide / size) * f.grid + 0.01)) * (size / f.grid);
      w = Math.floor(wide + 0.5);
      table.set(ch, w);
    }
    return w;
  }

  // Forgets every measured advance: call when a font has finished loading after text was measured.
  function resetText() {
    advances.clear();
  }

  // In a page: waits for the two open fonts (the page's @font-face rules name them as FACES does), then
  // forgets what was measured before they came. Resolves at once where there is no document.
  function loadFonts() {
    if (typeof document === 'undefined' || !document.fonts || !document.fonts.load) return Promise.resolve(resetText());
    const first = (face) => `${FACES[face].weight} 16px ${FACES[face].family.split(',')[0]}`;
    return Promise.all([document.fonts.load(first('bold')), document.fonts.load(first('classic-light'))]).then(resetText, resetText);
  }

  // A text's width in a face at a px, as the device lays it out.
  function measure(ctx, text, face = 'regular', px = 16) {
    let w = 0;
    for (const ch of String(text)) w += advance(ctx, face, px, ch);
    return w;
  }

  // The sum of a text's unrounded advances (the build tool's own measure, used for layout only).
  function measureExact(ctx, text, face, px) {
    const m = metrics(face, px);
    ctx.font = larger(m.font);
    let w = 0;
    for (const ch of String(text)) w += ctx.measureText(ch).width / MEASURE_AT;
    return w;
  }

  // Puts glyphs on the canvas: list is [[character, x], ...] on one baseline. The device's rasteriser fits
  // nothing to the pixel grid and blends a glyph's coverage plainly, where a browser may snap small text's
  // heights and thickens light text on a dark ground. So the glyphs are drawn black and several times larger
  // on a scratch canvas, tinted there, and laid over reduced: the same soft edges in every browser and in
  // both halves. Any transform but a scale and a shift, or no scratch canvas, draws them straight.
  const scratch = [null, null];
  function scratchCanvas(n, w, h) {
    const c = scratch[n];
    if (!c || c.width < w || c.height < h) scratch[n] = Q2Draw.makeCanvas(Math.max(w, c ? c.width : 512), Math.max(h, c ? c.height : 128));
    return scratch[n];
  }
  function stamp(ctx, font, list, base, c, alpha) {
    if (!list.length || alpha <= 0) return;
    const direct = () => {
      ctx.font = font;
      ctx.textBaseline = 'alphabetic';
      ctx.textAlign = 'left';
      ctx.fillStyle = css(c, alpha);
      for (const [ch, x] of list) ctx.fillText(ch, x, base);
    };
    const t = typeof ctx.getTransform === 'function' ? ctx.getTransform() : null;
    if (!t || t.b || t.c || t.a !== t.d || t.a <= 0 || Q2Draw.plainText) {
      direct();
      return;
    }
    const k = t.a;
    const over = Q2Draw.textOver || (k >= 3 ? 1 : k >= 1.5 ? 2 : 4); // how many times larger the glyphs are drawn
    const px = parseFloat(font.split(' ')[1]) * 1.4; // room around the glyphs, in screen pixels
    const x0 = list[0][1] - px;
    const x1 = list[list.length - 1][1] + 2 * px;
    const left = Math.floor(x0 * k + t.e);
    const top = Math.floor((base - 1.5 * px) * k + t.f);
    const w = Math.ceil((x1 - x0) * k) + 2;
    const h = Math.ceil(2.5 * px * k) + 2;
    let big;
    let half = null;
    try {
      big = scratchCanvas(0, w * over, h * over);
      if (over === 4) half = scratchCanvas(1, w * 2, h * 2);
    } catch (e) {
      direct();
      return;
    }
    const g = big.getContext('2d');
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.globalCompositeOperation = 'source-over';
    g.clearRect(0, 0, w * over, h * over);
    g.setTransform(k * over, 0, 0, k * over, (t.e - left) * over, (t.f - top) * over);
    g.font = font;
    g.textBaseline = 'alphabetic';
    g.textAlign = 'left';
    g.fillStyle = '#000000';
    for (const [ch, x] of list) g.fillText(ch, x, base);
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.globalCompositeOperation = 'source-in';
    g.fillStyle = hex(c);
    g.fillRect(0, 0, w * over, h * over);
    let from = big;
    let size = over;
    if (half) { // 4x to 2x here, 2x to 1x below: each halving averages four pixels into one
      const m = half.getContext('2d');
      m.setTransform(1, 0, 0, 1, 0, 0);
      m.globalCompositeOperation = 'source-over';
      m.imageSmoothingEnabled = true;
      m.clearRect(0, 0, w * 2, h * 2);
      m.drawImage(big, 0, 0, w * 4, h * 4, 0, 0, w * 2, h * 2);
      from = half;
      size = 2;
    }
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.globalAlpha = Math.min(alpha, 255) / 255;
    ctx.drawImage(from, 0, 0, w * size, h * size, left, top, w, h);
    ctx.restore();
  }

  // Draws glyph by glyph from x with the line box's top at top. faux: a second pass 1 px right (the
  // firmware's stand-in for a bold it lacks). track: extra px after each glyph. Returns the width.
  function run(ctx, text, x, top, face, px, c, alpha = 255, faux = false, track = 0) {
    const m = metrics(face, px);
    const list = [];
    let at = x;
    for (const ch of String(text)) {
      list.push([ch, at]);
      if (faux) list.push([ch, at + 1]);
      at += advance(ctx, face, px, ch) + track;
    }
    stamp(ctx, m.font, list, top + m.ascent, c, alpha);
    return at - x;
  }

  // Text in a box, the way a stock label or the payload's canvas places it (DRAWING.md 3.2): the line box
  // (px high) centred on the box's height, the text left, centred or right in the box less pad at each side.
  // o: { face, px, colour, alpha, align: 'left' | 'center' | 'right', pad, ellipsis, faux, clip }.
  // Returns { x, y, w, baseline, text }: where the line box went and what was drawn.
  function text(ctx, str, x, y, w, h, o = {}) {
    const face = o.face || 'regular';
    const px = o.px || 16;
    const pad = o.pad || 0;
    const room = w - 2 * pad;
    let s = String(str == null ? '' : str);
    let tw = measure(ctx, s, face, px);
    let align = o.align || 'left';
    if (tw > room && o.ellipsis) {
      align = 'left';
      const chars = Array.from(s);
      while (chars.length && measure(ctx, chars.join('') + '...', face, px) > room) chars.pop();
      s = chars.join('') + '...';
      tw = measure(ctx, s, face, px);
    }
    const tx = x + pad + (align === 'center' ? Math.floor((room - tw) / 2) : align === 'right' ? room - tw : 0);
    const top = y + Math.floor((h - px) / 2);
    const m = metrics(face, px);
    if (s) {
      if (o.clip) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(x, o.clip === 'box' ? y : top - px, w, o.clip === 'box' ? h : 3 * px);
        ctx.clip();
      }
      run(ctx, s, tx, top, face, px, o.colour === undefined ? 0xffffff : o.colour, o.alpha === undefined ? 255 : o.alpha, o.faux);
      if (o.clip) ctx.restore();
    }
    return { x: tx, y: top, w: tw, baseline: top + m.ascent, text: s };
  }

  // Minimal's small capitals (navigation.c draw_spaced): upper-cased, stock's face, each character stepped
  // by its width plus 2 px, from x with the text's top at top, cut off (not ellipsed) at max px. Returns the
  // whole text's width, a trailing 2 px included.
  function caps(ctx, str, x, top, px, c, max = W, alpha = 255) {
    const m = metrics('regular', px);
    const list = [];
    let at = 0;
    let room = max;
    for (const raw of String(str)) {
      const ch = raw.toUpperCase();
      const cw = measure(ctx, ch, 'regular', px);
      if (at + cw > room) room = -1; // cut off: the rest is only measured
      else list.push([ch, x + at]);
      at += cw + 2;
    }
    stamp(ctx, m.font, list, top + m.ascent, c, alpha);
    return at;
  }

  // ------------------------------------------------------------------------------------ sample content

  // The made-up library every screen shows: the reference pictures' own names (tools/ref_screens.py), so a
  // preview and its reference read alike. Nothing here is a real release.
  const ALBUMS = [
    ['Dusk on the Ridge', 'The Reference Band'], ['Afterglow', 'Mira Vale'], ['Blue Hours', 'Northline'], ['Cartography', 'Oslo Field'],
    ['Daylight Saving', 'The Reference Band'], ['Echo Park', 'June Arden'], ['Fieldnotes', 'Mira Vale'], ['Glasshouse', 'Northline'],
    ['Harbour Lights', 'Sable & Co.'], ['Inland', 'Oslo Field'], ['Juniper', 'June Arden'], ['Kite Season', 'Sable & Co.'],
  ].map(([title, artist], cover) => ({ title, artist, cover }));
  const SONGS = [
    ['Evening Signal', 'The Reference Band', 245], ['Above the Tree Line', 'Mira Vale', 198], ['Blue Hours', 'Northline', 312], ['Crosswind', 'Oslo Field', 224],
    ['Distant Radio', 'June Arden', 187], ['Every Other Light', 'The Reference Band', 263], ['First Frost', 'Sable & Co.', 201], ['Glass and Gravel', 'Mira Vale', 276],
    ['Hollow Hill', 'Northline', 233], ['In the Wires', 'Oslo Field', 219], ['Just Past Nine', 'June Arden', 254], ['Kept Time', 'Sable & Co.', 208],
  ].map(([title, artist, length]) => ({ title, artist, length }));
  // The Library's rows under the stock set, in upstream's order (patch/home.c ringnav_localmusic, with no
  // media folders and no card apps on the card); icon names a disc of art.disc. Classic's sets put Search
  // first and show no icons.
  const LIBRARY = [
    ['Shuffle', 'shuffle'], ['Artists', 'person'], ['Albums', 'disc'], ['Songs', 'note'], ['Genres', 'tag'], ['Era', 'clock'], ['Playlists', 'list'],
    ['Ratings', 'star'], ['Recently Added', 'plus'], ['Recent', 'recent'], ['Most Played', 'chart'], ['Hi-Res', 'hires'], ['Long Songs', 'hourglass'],
    ['Games', 'game'], ['Update Library', 'update'],
  ].map(([title, icon]) => ({ title, icon }));
  const SHORTCUTS = {
    rockbox: 'Rockbox', artists: 'Artists', albums: 'Albums', favorites: 'Favorites', rated_albums: 'Rated Albums', shuffle: 'Shuffle', games: 'Games',
    playlists: 'Playlists', podcasts: 'Podcasts', audiobooks: 'Audiobooks', groovebox: 'Groovebox',
  };
  const SETTING_LABELS = {
    light: ['Light Mode', { off: 'Off', on: 'On', auto: 'Auto' }],
    accent: ['Accent', null],
    corners: ['Rounded Corners', 'switch'],
    home: ['Home', { split: 'Split', full: 'Full', carousel: 'Carousel' }],
    battery: ['Battery', { icon: 'Icon', percent: 'Percent', both: 'Icon + Percent', inside: 'Percent Inside' }],
    shortcut: ['Shortcut', Object.assign({ none: 'None' }, SHORTCUTS)],
    time_title: ['Time in Title', 'switch'],
    np_layout: ['Centred Now Playing', 'switch'],
  };
  const SAMPLE = {
    albums: ALBUMS,
    songs: SONGS,
    library: LIBRARY,
    // the track on Now Playing: track 3 of 12, 1:23 of 4:05
    playing: { title: 'Evening Signal', artist: 'The Reference Band', album: 'Dusk on the Ridge', cover: 0, index: 3, count: 12, elapsed: 83, length: 245 },
    // what Home's pane captions count
    counts: { songs: 148, albums: 12, games: 3, services: 4, free: '21.4 GB Free' },
    // a time as stock writes it: M:SS, H:MM:SS from an hour
    time(seconds) {
      const s = Math.max(0, Math.floor(seconds));
      const two = (n) => String(n).padStart(2, '0');
      return s >= 3600 ? `${div(s, 3600)}:${two(div(s % 3600, 60))}:${two(s % 60)}` : `${div(s, 60)}:${two(s % 60)}`;
    },
  };

  // The stand-in album cover the reference pictures use (tools/ref_screens.py cover and tinted): a dusk
  // sky, a sun and three hills, drawn here; album i's has its channels turned. No real artwork.
  const COVER_TURNS = [[0, 1, 2], [1, 2, 0], [2, 0, 1], [0, 2, 1], [1, 0, 2], [2, 1, 0]];
  function cover(ctx, i, x, y, w, h) {
    const order = COVER_TURNS[((i % 6) + 6) % 6];
    const turn = (r, g, b) => { const c = [r, g, b]; return css(pack(c[order[0]], c[order[1]], c[order[2]])); };
    const kx = w / 320;
    const ky = h / 320;
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.clip();
    const sky = ctx.createLinearGradient(0, y, 0, y + h);
    sky.addColorStop(0, turn(40, 50, 120));
    sky.addColorStop(1, turn(240, 140, 80));
    ctx.fillStyle = sky;
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = turn(255, 226, 150);
    ctx.beginPath();
    ctx.ellipse(x + 235 * kx, y + 105 * ky, 35 * kx, 35 * ky, 0, 0, Math.PI * 2);
    ctx.fill();
    [[210, [60, 44, 84]], [245, [40, 30, 60]], [280, [22, 18, 36]]].forEach(([top, c], n) => {
      ctx.fillStyle = turn(...c);
      ctx.beginPath();
      ctx.moveTo(x, y + h);
      ctx.lineTo(x, y + top * ky);
      ctx.lineTo(x + (90 + 60 * n) * kx, y + (top - 50) * ky);
      ctx.lineTo(x + (200 + 30 * n) * kx, y + (top + 10) * ky);
      ctx.lineTo(x + w, y + (top - 30) * ky);
      ctx.lineTo(x + w, y + h);
      ctx.closePath();
      ctx.fill();
    });
    ctx.restore();
  }

  // ---------------------------------------------------------------------------------------------- art

  // Image sizes, for centring one in its cell (DRAWING.md 2.3: an image smaller than its cell is centred).
  const ART_SIZE = {
    bar_play: [12, 16], bar_pause: [12, 16], bar_wifi: [14, 16], bar_bt: [42, 16], chevron: [12, 16], sort_bars: [16, 12], state: [18, 22],
    bolt: [24, 11], plug: [24, 11], vol_lo: [8, 13], vol_hi: [18, 13], spk_quiet: [12, 14], spk_loud: [22, 14], note: [100, 115], pane_icon: [96, 96],
    list_into: [50, 50], switch: [50, 24], more: [24, 24], heart: [24, 24], mode: [24, 24], play_all: [50, 50], song_order: [50, 50], back: [24, 24],
    flat_mark: [32, 32], flat_note: [100, 115], flat_icon: [96, 96],
  };
  const ICON_SHIFT = 0.125;
  const WIFI_ARCS = ['M0.88,6.27 A8.8,8.8 0 0,1 13.12,6.27', 'M2.76,8.21 A6.1,6.1 0 0,1 11.24,8.21', 'M4.64,10.15 A3.4,3.4 0 0,1 9.36,10.15'];
  const BT_PATH = 'M34.2,4 L41.2,11 L37.2,14 L37.2,2 L41.2,5 L34.2,12';
  const CHEVRON_PATH = 'M2.9 3 L8.4 8.5 L2.9 14';
  const SORT_PATH = 'M0 0H16V2H0ZM0 5H11V7H0ZM0 10H6V12H0Z';
  const STATE_PATHS = { play: 'M4.5 4.5 16.5 11.5 4.5 18.5Z', pause: 'M4.5 4.5H9V18.5H4.5ZM12 4.5H16.5V18.5H12Z' };
  const BOLT_PATH = 'M11.67 1 8.56 6.24 10.85 6.24 10.2 10.16 13.64 4.76 11.35 4.76 12.49 1Z';
  const PLUG_PATH = 'M5.45 3.78h2.78v1.23H5.45ZM5.45 5.99h2.78v1.23H5.45ZM8.07 2.47h3.52a3.03 3.03 0 0 1 0 6.05h-3.52ZM13.64 4.93h4.09v1.23h-4.09Z';
  const SPEAKER_PATH = 'M0 4.5h3.5L9 .5v13L3.5 9.5H0Z';
  const VOL_WAVES = ['M9.14 4.12A3.2 3.2 0 0 1 9.14 8.88', 'M11.42 1.60A6.6 6.6 0 0 1 11.42 11.40', 'M15.28 0.90A10 10 0 0 1 15.28 12.10'];
  const SPEAKER_ARCS = ['M12 4.5a3.5 3.5 0 0 1 0 5', 'M14.5 2.5a7 7 0 0 1 0 9', 'M17 .8a10 10 0 0 1 0 12.4'];
  // Now Playing's heart and play modes (stand-ins of this file's own for stock's marks)
  const HEART_PATH = 'M12 20 C2 13.3 0.9 9.5 0.9 7.2 C0.9 4 3.3 1.9 6.2 1.9 C8.6 1.9 10.6 3.3 12 5.5 C13.4 3.3 15.4 1.9 17.8 1.9 C20.7 1.9 23.1 4 23.1 7.2 C23.1 9.5 22 13.3 12 20 Z';
  const MODE_PATHS = {
    random: 'M1 6 H6 L15 18 H22 M1 18 H6 L9 14 M12 10 L15 6 H22 M19 3 L22.5 6 L19 9 M19 15 L22.5 18 L19 21',
    cycle: 'M4 12 V9 Q4 6 7 6 H20 M17 3 L20.5 6 L17 9 M20 12 V15 Q20 18 17 18 H4 M7 15 L3.5 18 L7 21',
    cycle1: 'M4 12 V9 Q4 6 7 6 H20 M17 3 L20.5 6 L17 9 M20 12 V15 Q20 18 17 18 H4 M7 15 L3.5 18 L7 21 M11 11 L12.5 10 V15',
  };
  const MODE_ORDER = 'M0 2H23V4H0Z M0 9H23V11H0Z M0 16H23V18H0Z M16.5 12.8 L23 17 L16.5 21.2 Z'; // three lines, the last an arrow
  // Home's pane (tools/art.py PANE_ICONS): each but the note is fitted into a 92 px square centred on
  // (278, 124) of the drawing, in a 96 x 96 image at (230, 76); box is the path's own bounds.
  const NOTE_SHAPE = 'M254 82.5 317 71.5V156A16 12.5 -12 1 1 308.5 145.5V101L262 109.5V165A17 12.5 -12 1 1 254 153.5Z';
  const NOTE_GLOSS = 'M254 70H320V73C300 82 275 95 262 112V178H254Z';
  const PANE_ICONS = {
    note: { d: NOTE_SHAPE, box: [228.458, 71.5, 317, 177.855] },
    folder: { d: 'M230 92q0-6 6-6h24l8 9h43q6 0 6 6v60q0 6-6 6h-75q-6 0-6-6Z', box: [230, 86, 317, 167] },
    stack: { d: 'M246 94h60v60h-60ZM228 104l14-4v48l-14-4ZM324 104l-14-4v48l14-4Z', box: [228, 94, 324, 154] },
    game: {
      d: 'M251 96h44c16 0 25 15 27 35 2 17-3 28-11 28-7 0-11-6-16-13-3-4-6-6-11-6h-22c-5 0-8 2-11 6-5 7-9 13-16 13-8 0-13-11-11-28 2-20 11-35 27-35Z'
        + 'M243 109v9h-9v8h9v9h8v-9h9v-8h-9v-9ZM296 108a6 6 0 1 0 .01 0ZM284 120a6 6 0 1 0 .01 0Z',
      box: [223.565, 96, 322.435, 159],
    },
    wave: {
      d: 'M273 113a11 11 0 1 0 .01 0ZM293.1 105.9A27 27 0 0 1 293.1 142.1L287.9 137.4A20 20 0 0 0 287.9 110.6Z'
        + 'M304.2 95.9A42 42 0 0 1 304.2 152.1L299.0 147.4A35 35 0 0 0 299.0 100.6ZM252.9 142.1A27 27 0 0 1 252.9 105.9L258.1 110.6A20 20 0 0 0 258.1 137.4Z'
        + 'M241.8 152.1A42 42 0 0 1 241.8 95.9L247.0 100.6A35 35 0 0 0 247.0 147.4Z',
      box: [231.015, 95.9, 314.985, 152.1],
    },
    gear: {
      d: 'M313.7 140.8L309.6 148.4L296.3 147.3L291.3 151.4L289.8 164.7L281.6 167.2L273.0 157.0L266.6 156.4L256.2 164.7L248.6 160.6L249.7 147.3'
        + 'L245.6 142.3L232.3 140.8L229.8 132.6L240.0 124.0L240.6 117.6L232.3 107.2L236.4 99.6L249.7 100.7L254.7 96.6L256.2 83.3L264.4 80.8L273.0 91.0'
        + 'L279.4 91.6L289.8 83.3L297.4 87.4L296.3 100.7L300.4 105.7L313.7 107.2L316.2 115.4L306.0 124.0L305.4 130.4ZM273 108a16 16 0 1 0 .01 0Z',
      box: [229.8, 80.8, 316.2, 167.2],
    },
  };
  // The flat look's own images (tools/art.py FLAT_GLYPHS, np_heart, flat_images; DRAWING.md 15.6), drawn from
  // the repository's path data. Now Playing's marks are 32 px squares with their drawing about the middle:
  // line, open paths stroked FLAT_LINE wide with round ends; fill, shapes (later subpaths their holes); dots,
  // discs [x, y, r].
  const FLAT_BOX = 32;
  const FLAT_LINE = 2.3;
  const NP_HEADS = ['M8.5 -10.2 13.5 -6 8.5 -1.8Z', 'M8.5 1.8 13.5 6 8.5 10.2Z'];
  const NP_LOOP = ['M-11 -1V-2.5A3.5 3.5 0 0 1 -7.5 -6H9', 'M11 1V2.5A3.5 3.5 0 0 1 7.5 6H-9'];
  const NP_TURNS = ['M8.5 -10.2 13.5 -6 8.5 -1.8Z', 'M-8.5 1.8 -13.5 6 -8.5 10.2Z'];
  const FLAT_MARKS = {
    more: { dots: [[-9, 0, 2.6], [0, 0, 2.6], [9, 0, 2.6]] },
    order: { line: ['M-12 -6H9', 'M-12 6H9'], fill: NP_HEADS },
    shuffle: { line: ['M-12 -6H-7L5 6H9', 'M-12 6H-7L5 -6H9'], fill: NP_HEADS },
    repeat: { line: NP_LOOP, fill: NP_TURNS },
    repeat1: { line: NP_LOOP, fill: [...NP_TURNS, 'M-0.3 -3.4H1.5V3.4H-0.5V-1.3L-2 -0.7V-2.4Z'] },
  };
  // the play modes' names on Now Playing, as np_marks.c maps stock's
  const FLAT_MODES = { order: 'order', random: 'shuffle', cycle: 'repeat', cycle1: 'repeat1' };
  // The rating panel's heart (tools/art.py RATE_HEART), drawn at 0.8 of its size in the middle of the square,
  // its outline 2.4 wide at that size; filled too when on.
  const RATE_HEART = 'M16 28C6 20 2 15 2 9.6 2 2 12 0 16 7.2 20 0 30 2 30 9.6 30 15 26 20 16 28Z';
  // flat.c's final colours, [dark, light]: a control at rest, the ink, a quiet line
  const FLAT_REST = [0x2c2c2e, 0xe9e9ec];
  const FLAT_INK = [0xffffff, 0x1c1c1e];
  const FLAT_QUIET = [0x98989d, 0x6e6e73];
  const CLASSIC_BLUE_ON = 0x207cde; // flat_on over Classic's own pages, under the theme's own named scheme
  // Whether a colour is bright (navigation.c bright_tone, GLYPH_LIGHT_MAX 160): words on it take the ink.
  const bright = (c) => {
    const [r, g, b] = rgb(col(c));
    return div(299 * r + 587 * g + 114 * b, 1000) > 160;
  };

  // The stand-in discs for stock's Library and settings icons: a colour and a glyph drawn in code. shuffle,
  // disc, note and display are the flat colours measured on the reference pictures; person is stock red,
  // which the accent recolours (art.disc), and the rest are guesses no reference shows.
  const DISCS = {
    shuffle: 0xff751c, person: STOCK_RED, disc: 0xc425ff, note: 0xff5246, tag: 0x2fa8a0, clock: 0x8a6fe0, list: 0x3f9be8, star: 0xe0a92c, heart: 0xe8527a,
    plus: 0x57b85a, recent: 0x5d7fc4, chart: 0xd2503c, hires: 0xc59a2a, mic: 0x9b59c9, book: 0xb5793c, hourglass: 0x6c8cae, photo: 0x38a9c4, film: 0xd9603b,
    game: 0x6aa84f, update: 0x4f9a8c, folder: 0x7a8794, gear: 0x6e7781, display: 0xff751c, speaker: 0x47a36b, wifi: 0x3d8fe0, lock: 0x8d7b68, info: 0x7f8c9b,
    radio: 0xc76a2f,
  };
  // Under list.icons.mono a disc's grey is 255 - (255 - g) * sat / most (navigation.c:5618-5637), where sat
  // is its flat colour's saturation and most its icon's most saturated pixel's: this is sat / most, measured
  // on the reference pictures where one shows the disc, 1 elsewhere.
  const MONO_RATIO = { display: 0.89, shuffle: 0.963, note: 0.963, person: 0.985, disc: 0.985 };

  // The glyph of a disc or tile, white strokes in a box of half-width u about (cx, cy). Plain shapes of
  // this file's own: they say what the row is, they copy no stock picture.
  function glyph(ctx, name, cx, cy, u, c, alpha = 255) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.scale(u, u);
    ctx.strokeStyle = css(c, alpha);
    ctx.fillStyle = css(c, alpha);
    ctx.lineWidth = 0.14;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    const line = (...p) => { ctx.beginPath(); ctx.moveTo(p[0], p[1]); for (let i = 2; i < p.length; i += 2) ctx.lineTo(p[i], p[i + 1]); ctx.stroke(); };
    const circle = (x, y, r, solid) => { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); if (solid) ctx.fill(); else ctx.stroke(); };
    const arc = (x, y, r, a0, a1) => { ctx.beginPath(); ctx.arc(x, y, r, a0, a1); ctx.stroke(); };
    switch (name) {
      case 'note':
        line(-0.25, 0.45, -0.25, -0.5, 0.5, -0.65, 0.5, 0.3);
        line(-0.25, -0.2, 0.5, -0.35);
        circle(-0.42, 0.47, 0.17);
        circle(0.33, 0.32, 0.17);
        break;
      case 'person':
        circle(0, -0.3, 0.3);
        arc(0, 0.75, 0.6, Math.PI * 1.1, Math.PI * 1.9);
        line(-0.57, 0.57, 0.57, 0.57);
        break;
      case 'disc':
        circle(0, 0, 0.62);
        circle(0, 0, 0.14);
        arc(0, 0, 0.38, Math.PI * 1.55, Math.PI * 1.95);
        arc(0, 0, 0.38, Math.PI * 0.55, Math.PI * 0.95);
        break;
      case 'shuffle':
        arc(0, 0, 0.55, Math.PI * 1.15, Math.PI * 1.9);
        arc(0, 0, 0.55, Math.PI * 0.15, Math.PI * 0.9);
        line(0.36, -0.52, 0.56, -0.2, 0.74, -0.5);
        line(-0.36, 0.52, -0.56, 0.2, -0.74, 0.5);
        ctx.beginPath(); ctx.moveTo(-0.12, -0.2); ctx.lineTo(0.2, 0); ctx.lineTo(-0.12, 0.2); ctx.closePath(); ctx.fill();
        break;
      case 'tag':
        line(-0.55, -0.55, 0.05, -0.55, 0.6, 0, 0.05, 0.55, -0.55, 0.55, -0.55, -0.55);
        circle(-0.28, -0.28, 0.09, true);
        break;
      case 'clock':
        circle(0, 0, 0.6);
        line(0, -0.34, 0, 0, 0.25, 0.14);
        break;
      case 'list':
        line(-0.5, -0.35, 0.5, -0.35);
        line(-0.5, 0, 0.5, 0);
        line(-0.5, 0.35, 0.15, 0.35);
        break;
      case 'star':
        ctx.beginPath();
        for (let i = 0; i < 10; i += 1) {
          const r = i % 2 ? 0.28 : 0.66;
          const a = -Math.PI / 2 + (i * Math.PI) / 5;
          ctx[i ? 'lineTo' : 'moveTo'](r * Math.cos(a), r * Math.sin(a));
        }
        ctx.closePath();
        ctx.stroke();
        break;
      case 'heart':
        ctx.beginPath();
        ctx.moveTo(0, 0.55);
        ctx.bezierCurveTo(-0.95, -0.05, -0.6, -0.75, 0, -0.3);
        ctx.bezierCurveTo(0.6, -0.75, 0.95, -0.05, 0, 0.55);
        ctx.closePath();
        ctx.stroke();
        break;
      case 'plus':
        line(-0.45, 0, 0.45, 0);
        line(0, -0.45, 0, 0.45);
        break;
      case 'mic':
        ctx.beginPath(); roundRectPath(ctx, -0.2, -0.65, 0.4, 0.75, 0.2); ctx.stroke();
        arc(0, -0.1, 0.42, 0, Math.PI);
        line(0, 0.32, 0, 0.62);
        break;
      case 'book':
        line(0, -0.4, 0, 0.5);
        line(0, -0.4, -0.6, -0.52, -0.6, 0.38, 0, 0.5, 0.6, 0.38, 0.6, -0.52, 0, -0.4);
        break;
      case 'hourglass':
        line(-0.4, -0.6, 0.4, -0.6, -0.4, 0.6, 0.4, 0.6, -0.4, -0.6);
        break;
      case 'photo':
        ctx.beginPath(); roundRectPath(ctx, -0.6, -0.45, 1.2, 0.9, 0.12); ctx.stroke();
        line(-0.5, 0.3, -0.15, -0.05, 0.1, 0.18, 0.28, 0.02, 0.5, 0.3);
        circle(0.28, -0.2, 0.08, true);
        break;
      case 'film':
        ctx.beginPath(); roundRectPath(ctx, -0.6, -0.42, 1.2, 0.84, 0.12); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(-0.14, -0.2); ctx.lineTo(0.22, 0); ctx.lineTo(-0.14, 0.2); ctx.closePath(); ctx.fill();
        break;
      case 'game':
        ctx.beginPath(); roundRectPath(ctx, -0.65, -0.32, 1.3, 0.64, 0.3); ctx.stroke();
        line(-0.42, 0, -0.18, 0);
        line(-0.3, -0.12, -0.3, 0.12);
        circle(0.34, 0, 0.07, true);
        break;
      case 'folder':
        line(-0.6, -0.4, -0.15, -0.4, 0, -0.25, 0.6, -0.25, 0.6, 0.45, -0.6, 0.45, -0.6, -0.4);
        break;
      case 'gear':
        circle(0, 0, 0.26);
        for (let i = 0; i < 8; i += 1) {
          const a = (i * Math.PI) / 4;
          line(0.46 * Math.cos(a), 0.46 * Math.sin(a), 0.64 * Math.cos(a), 0.64 * Math.sin(a));
        }
        break;
      case 'display':
        circle(0, 0, 0.26);
        ctx.beginPath(); ctx.arc(0, 0, 0.26, Math.PI / 2, Math.PI * 1.5); ctx.fill();
        for (let i = 0; i < 8; i += 1) {
          const a = (i * Math.PI) / 4;
          line(0.44 * Math.cos(a), 0.44 * Math.sin(a), 0.56 * Math.cos(a), 0.56 * Math.sin(a));
        }
        break;
      case 'speaker':
        line(-0.55, -0.15, -0.3, -0.15, 0, -0.42, 0, 0.42, -0.3, 0.15, -0.55, 0.15, -0.55, -0.15);
        arc(0, 0, 0.3, -Math.PI / 4, Math.PI / 4);
        arc(0, 0, 0.55, -Math.PI / 4, Math.PI / 4);
        break;
      case 'wifi':
        arc(0, 0.4, 0.75, Math.PI * 1.25, Math.PI * 1.75);
        arc(0, 0.4, 0.45, Math.PI * 1.25, Math.PI * 1.75);
        circle(0, 0.36, 0.09, true);
        break;
      case 'lock':
        ctx.beginPath(); roundRectPath(ctx, -0.4, -0.08, 0.8, 0.6, 0.1); ctx.stroke();
        arc(0, -0.1, 0.26, Math.PI, 0);
        break;
      case 'info':
        circle(0, 0, 0.6);
        line(0, -0.05, 0, 0.3);
        circle(0, -0.28, 0.07, true);
        break;
      case 'recent': // a clock face with an arrow round it
        arc(0, 0, 0.6, -Math.PI * 0.35, Math.PI * 1.35);
        line(-0.62, -0.62, -0.5, -0.3, -0.2, -0.45);
        line(0, -0.3, 0, 0, 0.22, 0.12);
        break;
      case 'chart': // three bars
        line(-0.42, 0.5, -0.42, 0.05);
        line(0, 0.5, 0, -0.5);
        line(0.42, 0.5, 0.42, -0.2);
        break;
      case 'hires': // a wave
        ctx.beginPath();
        ctx.moveTo(-0.65, 0);
        ctx.bezierCurveTo(-0.45, -0.75, -0.25, -0.75, 0, 0);
        ctx.bezierCurveTo(0.25, 0.75, 0.45, 0.75, 0.65, 0);
        ctx.stroke();
        break;
      case 'update': // two arrows round a circle
        arc(0, 0, 0.5, Math.PI * 1.1, Math.PI * 1.85);
        arc(0, 0, 0.5, Math.PI * 0.1, Math.PI * 0.85);
        line(0.2, -0.62, 0.45, -0.47, 0.32, -0.2);
        line(-0.2, 0.62, -0.45, 0.47, -0.32, 0.2);
        break;
      case 'radio':
        circle(0, 0, 0.14, true);
        arc(0, 0, 0.36, -Math.PI / 3, Math.PI / 3);
        arc(0, 0, 0.36, Math.PI * (2 / 3), Math.PI * (4 / 3));
        arc(0, 0, 0.6, -Math.PI / 3, Math.PI / 3);
        arc(0, 0, 0.6, Math.PI * (2 / 3), Math.PI * (4 / 3));
        break;
      default:
        circle(0, 0, 0.2, true);
    }
    ctx.restore();
  }

  // ---------------------------------------------------------------------------------------- the pages

  // The eight screens: each one's name and what the status bar calls it. A screen file fills
  // Q2Draw.screens[id]; until it does, render() draws the page's paper and the bar alone.
  const PAGES = {
    home: { name: 'Home', title: 'Q2 Pod', home: true },
    'list-library': { name: 'Library', title: 'Library' },
    'list-albums': { name: 'Albums', title: 'Albums' },
    'list-songs': { name: 'Songs', title: 'Songs' },
    settings: { name: 'Settings', title: 'Appearance' },
    'now-playing': { name: 'Now Playing', title: 'Now Playing' },
    volume: { name: 'Volume', title: 'Now Playing' },
    confirm: { name: 'Confirm', title: '' },
  };

  // What every screen's state starts from: the status bar's side of it, as the reference pictures have it
  // (9:41, Wi-Fi 3 bars, no Bluetooth, battery 80 %, playing), and the first row selected.
  const STATE = {
    title: '', // the page's name in the bar; render() fills it from PAGES
    home: false, // Home is in front (its title is the wordmark)
    play: 'playing', // 'none', 'playing', 'paused'
    wifi: 3, // 0..4, or null to hide
    bt: null, // null hidden, 'on' not linked, 'linked'
    eq: '', // the EQ mark's text ('' hides it; stock's own, DRAWING.md 13 item 8)
    battery: 80, // level 0..100
    charging: false,
    low: false,
    plugged: false, // full on power
    hour: 9,
    minute: 41,
    clock24: false,
    selected: 0, // the selected row
  };

  const screens = {};

  // ---------------------------------------------------------------------------------- the environment

  // Makes the drawing environment. official: Q2Official.open(official.json). theme: a resolved theme
  // (official.resolve(theme), or a built-in's themes[].resolved). choices: the viewer's switches, each
  // optional (the theme's preset, then its default, stands in):
  //   half 'dark' | 'light'; accent: a scheme's name or stored index;
  //   corners 'square' | 'round'; home 'split' | 'full' | 'carousel'; battery 'icon' | 'percent' | 'both' |
  //   'inside'; shortcut; time_title 'off' | 'on'; np_layout 'ipod' | 'centred' (each also takes its index);
  //   the theme's own options by key (STATUSBAR, SHOWQ2POD, HOMELIB, ROWPREVIEW, ROWART, ...): a value's
  //   label or index; hide_streaming, hide_folder: booleans; glass: true to mask the screen's corners.
  function makeEnv(official, theme, choices = {}) {
    const data = official.data;
    const schema = new Map(data.schema.map((k) => [k.path, k]));
    const drawn = official.drawn(theme);
    const names = official.schemeNames(theme);
    const consts = data.constants;
    const env = { official, theme, data, W, H };

    // ---- settings
    const opts = theme.opts || [];
    const set = {};
    const offered = {};
    const pick = (o, values, given) => {
      let v = given;
      if (typeof v === 'string') {
        const i = values.findIndex((n) => String(n).toLowerCase() === v.toLowerCase());
        v = i >= 0 ? i : undefined;
      }
      if (typeof v === 'boolean') v = v ? 1 : 0;
      // what choosing the theme stores (its preset), else the stored value's own start: an own option's
      // default, a firmware setting's first value. default is also what a value not offered reads as.
      if (v === undefined || v === null) v = o.preset >= 0 ? o.preset : o.setting === 'SETTING_OWN' && o.def >= 0 ? o.def : 0;
      if (o.values && !((o.values >> v) & 1) && o.def >= 0) v = o.def;
      return v;
    };
    for (const [name, s] of Object.entries(data.settings)) {
      const o = opts.find((row) => row.setting === s.macro);
      offered[name] = Boolean(o);
      if (name === 'accent' || name === 'light') continue;
      set[name] = s.values[o ? clamp(pick(o, s.values, choices[name]), 0, s.values.length - 1) : 0];
    }
    const own = {};
    for (const o of opts) {
      if (o.setting !== 'SETTING_OWN') continue;
      own[o.key] = clamp(pick(o, o.names, choices[o.key]), 0, o.names.length - 1);
    }
    env.set = set; // corners, home, battery, shortcut, time_title, np_layout: each its value's name
    env.own = own; // the theme's own options by key: each its value's index
    env.offered = offered; // which firmware settings the theme lists
    env.opts = opts;
    env.round = set.corners === 'round'; // Rounded Corners on (never when the theme does not offer it)
    env.timeTitle = set.time_title === 'on';
    env.npCentred = set.np_layout === 'centred'; // Centred Now Playing on (never when not offered)
    env.wordmark = own.SHOWQ2POD === undefined ? true : own.SHOWQ2POD === 1;
    env.hideStreaming = Boolean(choices.hide_streaming);
    env.hideFolder = Boolean(choices.hide_folder);
    env.glass = Boolean(choices.glass);

    // ---- the accent, the scheme and the half
    const accentRow = opts.find((row) => row.setting === data.settings.accent.macro) || { def: 0, preset: -1, values: 0 };
    let accent = choices.accent;
    if (typeof accent === 'string') accent = names.indexOf(accent.toLowerCase());
    if (accent === undefined || accent === null || accent < 0 || accent >= theme.schemes.length) accent = accentRow.preset >= 0 ? accentRow.preset : Math.max(accentRow.def, 0);
    if (!((theme.accents >> accent) & 1)) accent = Math.max(accentRow.def, 0);
    env.accent = accent; // the stored accent value: the scheme's index
    env.accentName = names[accent];
    const lightRow = opts.find((row) => row.setting === data.settings.light.macro);
    let light = choices.half ? choices.half === 'light' : Boolean(lightRow && lightRow.preset === 1);
    const mode = data.schema.find((k) => k.path === 'scheme.mode').choices[theme.schemes[accent].mode];
    if (mode === 'light') light = true;
    if (mode === 'dark') light = false;
    env.light = light;
    env.half = light ? 'light' : 'dark';
    const S = drawn.schemes[accent][light ? 1 : 0];
    const lightS = drawn.schemes[accent][1];
    env.S = S; // the scheme as drawn in this half, by field: sel, sel_top, bar, bar_line, fill, muted, ...
    env.ownScheme = accent >= data.accents.length; // the theme's own named scheme (Classic Blue)
    const base = theme.schemes[accent].base;
    env.tones = data.accents[accent < data.accents.length ? accent : base === undefined ? 0 : base].tones.slice();
    const spread = consts.LIGHT_SPREAD;
    const paper = lightS.paper;
    const inkOf = lightS.ink;
    env.lightPaper = paper; // the light half's paper and ink, which the flip runs between
    env.lightInk = inkOf;

    // ---- colour (DRAWING.md section 1)
    env.neutral = (c) => neutral(col(c), spread);
    env.flip = (c) => flip(col(c), paper, inkOf, spread);
    // INK(c): a colour stated in stock terms, as this half shows it.
    env.INK = (c) => (light ? env.flip(c) : col(c));
    env.page = env.INK(0x000000); // the page's paper
    env.fg = env.INK(0xffffff); // plain text
    // The theme's value for a schema key, as painted in this half: a final key gives the half's own, a
    // scheme key the chosen scheme's. Enums and fonts are their stored index (see choice()).
    env.T = (path) => {
      const k = schema.get(path);
      if (!k) throw new Error(`Q2Draw: unknown key ${path}`);
      if (path.startsWith('scheme.')) return S[k.field];
      if (k.final) return drawn.theme[k.field][light ? 1 : 0];
      return theme[k.field];
    };
    // An enum key's value by name ('gloss', 'classic-light', 'centred').
    env.choice = (path) => schema.get(path).choices[env.T(path)];
    env.tone = (i) => env.tones[i];
    // Light Mode: a neutral accent's every tone is its red tone, which then flips dark (tone_of).
    env.toneOf = (i) => (light && env.neutral(env.tones[0]) ? env.tones[3] : env.tones[i]);
    // The accent's light tone as the progress fill and the volume bar take it, before INK (accent_tone).
    env.accentTone = () => (S.card ? S.fill : env.toneOf(2));
    const accentMap = (c, tone) => {
      if (light) return env.neutral(c) ? env.flip(c) : redMap(c, env.flip(env.toneOf(tone)), 0xffffff, 1, paper, inkOf);
      return S.raw_red ? c : redMap(c, env.tones[tone], 0xffffff, 0);
    };
    // A stock style colour as the firmware's style hook leaves it: the red mapping, then INK. text: the
    // colour is a label's text (it takes the red tone where anything else takes the light tone).
    env.style = (c, text = false) => {
      const v = col(c);
      if (S.raw_red && !light) return v;
      const out = accentMap(v, 2);
      return out !== v && text ? accentMap(v, 3) : out;
    };
    // A red pixel of a stock image that also holds white (a switch's fill, the Artists disc): the accent's
    // light tone, through tone_of and flipped in the light half; a raw_red scheme keeps stock's red in the
    // dark half (navigation.c ringnav_image_add: tone = light where the image has a white part).
    env.imageRed = (c = STOCK_RED) => {
      if (S.raw_red && !light) return col(c);
      return light ? redMap(col(c), env.flip(env.toneOf(2)), 0xffffff, 1, paper, inkOf) : redMap(col(c), env.tones[2], 0xffffff, 0);
    };
    env.progressFill = () => env.style(env.accentTone()); // Now Playing's plain fill (1.5)
    env.volumeFill = () => env.INK(env.accentTone()); // the volume bar over Now Playing (8.1)
    env.rows = (stops, h) => stopsRows(stops, h);

    // ---- the flat look (DRAWING.md section 15). pages.own.painter and dialog.confirm.painter are bit sets
    // (patch/theme.h): their stored value's bit of 'classic-light' is Classic's pages, of 'flat' the flat look's.
    const bitOf = (path, name) => {
      const k = schema.get(path);
      const i = k && k.choices ? k.choices.indexOf(name) : -1;
      return i > 0 ? i : 0;
    };
    const pagesPainter = env.T('pages.own.painter');
    env.flatPages = Boolean(pagesPainter & bitOf('pages.own.painter', 'flat')); // flat_pages(): Home's pane, Now Playing's marks
    env.classicPages = Boolean(pagesPainter & bitOf('pages.own.painter', 'classic-light')); // classic_pages(): the lit colour
    env.flatDialogs = Boolean(env.T('dialog.confirm.painter') & bitOf('dialog.confirm.painter', 'flat')); // flat_dialogs()
    env.flatVolume = env.choice('volume.panel.painter') === 'flat';
    env.flatRest = FLAT_REST[light ? 1 : 0];
    env.flatInk = FLAT_INK[light ? 1 : 0];
    env.flatQuiet = FLAT_QUIET[light ? 1 : 0];
    env.flatPage = light ? S.paper : 0x000000; // flat_page(): a flat page's ground, the half's paper
    // What is on (flat_on): Classic Blue over Classic's own pages under the theme's own named scheme; else the
    // red tone over Classic's pages or for a neutral accent, the selection bar's middle row otherwise; greys
    // flipped in the light half. Final.
    env.flatOn = () => {
      if (env.classicPages && (theme.schemes[accent].label || env.ownScheme)) return CLASSIC_BLUE_ON;
      const t = env.tones;
      return env.INK(env.classicPages || env.neutral(t[0]) ? t[3] : mix(t[0], t[1], 1, 2));
    };
    // Whether the theme's own images are final (navigation.c final_art): art_final with the pages bit
    // that owns the name, classic_light_ under the classic-light bit, flat_ under the flat bit; and so too
    // when the Status Bar's theme (env.barTheme, set below) has them final (ringnav_image_add, 3.7).
    const finalOwn = (e, flat) => Boolean(e.T('pages.own.art_final')) && (flat ? e.flatPages : e.classicPages);
    env.finalArt = (flat) => finalOwn(env, flat) || Boolean(env.barTheme && env.barTheme !== env && finalOwn(env.barTheme, flat));
    // A flat image's colour: final when env.finalArt(true), else through INK (3.7, 15.6).
    env.flatArt = (c) => (env.finalArt(true) ? col(c) : env.INK(c));

    // ---- geometry (DRAWING.md section 2)
    let setName = theme.geom_set;
    for (const o of opts) if (o.setting === 'SETTING_OWN' && o.sets) setName = o.sets[own[o.key]] || setName;
    env.setName = setName; // the geometry set that was booted (Row Art picks Classic's)
    const G = (theme.geoms && theme.geoms[setName]) || data.geometry.sets[setName] || data.geometry.sets.ipod;
    env.G = G;
    env.bar = G.bar; // the status bar's height; a page window starts under it
    env.win = { x: 0, y: G.bar, w: W, h: H - G.bar };
    env.glassInset = glassInset;

    // ---- painters and the selection (DRAWING.md 1.8, 5.4, 6.2)
    const painter = env.choice('list.selection.painter');
    // Whether a selected row counts as "accented" (its text stays white in the light half).
    env.selAccent = (home = false) => (painter === 'stops' || (!env.neutral(env.tones[0]) && !S.card)) && !(home && painter === 'card');
    // The colour of a row's text. o: { selected, second (a list row's second line), home (a Home row),
    // colour (stock's own, white unless given) }.
    env.rowText = (o = {}) => {
      let c = o.colour === undefined ? 0xffffff : col(o.colour);
      if (o.second && (env.T('list.row.meta_font') || env.T('list.row.meta_px'))) c = 0xaaaaaa;
      const homeCard = Boolean(o.home) && painter === 'card';
      if (o.selected && env.selAccent(o.home) && (light || S.sel_text)) return S.sel_text ? S.sel_text : c;
      if (o.selected && (homeCard || S.card)) return env.INK(homeCard ? 0xffffff : c === 0xffffff ? 0x171717 : 0x484848);
      if (homeCard) return env.INK(0xaaaaaa);
      if (S.muted && !o.selected && c === 0xaaaaaa) c = S.muted;
      return env.style(c, true);
    };
    // Paints the selection behind a row at x, y, w, h by list.selection.painter. o: { home (a Home row:
    // the card painter draws its dot), images (the row button's leading images, for the pill's radius; see
    // pillRadius), radius (a pill radius to use instead) }. Returns { painter, accent, radius }.
    env.selection = (ctx, x, y, w, h, o = {}) => {
      const out = { painter, accent: env.selAccent(o.home), radius: 0 };
      if (painter === 'stops') {
        const lid = S.sel_top ? 1 : 0;
        const tall = Boolean(S.sel_tall_edge) && h > G.pitch;
        if (tall) paintStops(ctx, x, y, w, h, S.sel);
        if (lid) fill(ctx, x, y, w, 1, S.sel_top);
        if (tall && S.sel_tall_top) fill(ctx, x, y + lid, w, 1, S.sel_tall_top);
        if (!tall) paintStops(ctx, x, y + lid, w, h - lid - (S.sel_edge ? 1 : 0), S.sel);
        if (tall) {
          fill(ctx, x, y + h - 2, w, 1, S.sel_tall_edge);
          fill(ctx, x, y + h - 1, w, 1, S.sel_tall_line);
        } else if (S.sel_edge) fill(ctx, x, y + h - 1, w, 1, S.sel_edge);
        out.tall = tall;
      } else if (painter === 'bar') {
        const pill = env.round ? (o.radius === undefined ? pillRadius(h, o.images, SEL_INSET) : o.radius) : 0;
        const colours = [];
        for (let j = 0; j < h; j += 1) colours.push(env.INK(j ? mix(env.tones[0], env.tones[1], j, h - 1) : env.tones[4]));
        pillRows(ctx, pill ? x + SEL_INSET : x, y, pill ? w - 2 * SEL_INSET : w, colours, pill);
        out.radius = pill;
      } else if (o.home) {
        box(ctx, x + 25, y + div(h - 6, 2), 6, 6, 3, env.INK(0xffffff));
      } else {
        const inset = env.round ? SEL_INSET : 0;
        const radius = env.round ? (o.radius === undefined ? pillRadius(h, o.images, inset) : o.radius) : 0;
        box(ctx, x + inset, y, w - 2 * inset, h, radius, env.INK(S.card ? S.fill : env.tones[0]));
        out.radius = radius < 3 ? 0 : radius;
      }
      return out;
    };

    // ---- fonts and text (DRAWING.md section 3)
    // A role's face and px for a text, after the fallback: role one of title, meta, tall, bar, np, home,
    // info; stockPx the widget's own style size, used where the role states no px.
    env.role = (role, stockPx, str = '') => {
      const [fontKey, pxKey] = ROLES[role];
      const face = FACE_NAMES[env.T(fontKey)] || 'regular';
      const px = env.T(pxKey);
      const f = fallback(face, px, String(str));
      return { face: f.face, px: f.px || stockPx, faux: f.faux };
    };
    // The face the payload's own canvas text takes: Classic's only when list.row.font is classic-light.
    env.canvasFace = (px, str = '') => {
      if (FACE_NAMES[env.T('list.row.font')] !== 'classic-light') return { face: 'regular', px, faux: false };
      const f = fallback('classic-light', px, String(str));
      return { face: f.face, px: f.px, faux: false };
    };
    env.measure = measure;
    env.text = text;
    // A stock scrolling label (row titles, Home labels, the bar's title and clock, Now Playing's title,
    // artist and album): text 2 px inside its box, an ellipsis when too wide. o as text()'s, and role with
    // px as the style's own size to draw in a theme role.
    env.label = (ctx, str, x, y, w, h, o = {}) => {
      const f = o.role ? env.role(o.role, o.px || 16, str) : { face: o.face || 'regular', px: o.px || 16, faux: o.faux };
      return text(ctx, str, x, y, w, h, Object.assign({ pad: 2, ellipsis: true, colour: env.fg }, o, f));
    };
    // A stock plain label ("3 of 12", the times): text from its box's edge, no ellipsis.
    env.plain = (ctx, str, x, y, w, h, o = {}) => text(ctx, str, x, y, w, h, Object.assign({ colour: env.fg }, o));
    // The payload's canvas text (draw_centred): centred both ways in the payload's face.
    env.canvasText = (ctx, str, x, y, w, h, px, c, o = {}) => text(ctx, str, x, y, w, h, Object.assign({ align: 'center', colour: c }, o, env.canvasFace(px, str)));
    env.caps = caps;

    // ---- images (DRAWING.md 3.6, 3.7)
    // Art is square unless Rounded Corners rounds it (navigation.c:1832).
    env.artSquare = Boolean(env.T('playing.art.square')) && !env.round;
    env.artRadius = (w, h = w) => (env.artSquare ? 0 : div(Math.min(w, h) * 12, 166));
    // White classic_light_ art of the theme's own: final when env.finalArt(false), else flipped with the half.
    const ownWhite = () => (env.finalArt(false) ? 0xffffff : env.INK(0xffffff));
    // An image's top left when centred in a cell.
    env.centre = (name, x, y, w, h) => {
      const [iw, ih] = ART_SIZE[name];
      return [x + Math.floor((w - iw) / 2), y + Math.floor((h - ih) / 2)];
    };
    const mark = (c) => (c === undefined ? env.INK(0xffffff) : c);
    env.art = {
      // -- the project's own, from its path data. x, y: the image's top left.
      // The bar's four marks are built at 4x by a tool that counts from a pixel's middle and then reduced,
      // which lands them an eighth of a pixel right and down of their path data (ICON_SHIFT).
      // The bar's play and pause marks, 12 x 16.
      barPlay(ctx, x, y, c) {
        fillPath(ctx, 'M2,2.5 L10,8 L2,13.5 Z', x + ICON_SHIFT, y + ICON_SHIFT, mark(c));
        strokePath(ctx, 'M2,2.5 L10,8 L2,13.5 Z', x + ICON_SHIFT, y + ICON_SHIFT, 1, mark(c));
      },
      barPause(ctx, x, y, c) {
        strokePath(ctx, 'M3,3 L3,13 M9,3 L9,13', x + ICON_SHIFT, y + ICON_SHIFT, 2.5, mark(c));
      },
      // Wi-Fi at a level 0..4, 14 x 16: arc i (0 the outer) is lit when level >= 4 - i.
      wifi(ctx, x, y, level) {
        WIFI_ARCS.forEach((d, i) => strokePath(ctx, d, x + ICON_SHIFT, y + ICON_SHIFT, 1.5, env.INK(level >= 4 - i ? 0xffffff : 0x666666)));
        disc(ctx, x + 7 + ICON_SHIFT, y + 12.6 + ICON_SHIFT, 1.2, env.INK(level > 0 ? 0xffffff : 0x666666));
      },
      // Bluetooth, 42 x 16 (its ink is columns 33..41): grey until linked.
      bt(ctx, x, y, linked) {
        strokePath(ctx, BT_PATH, x + ICON_SHIFT, y + ICON_SHIFT, 1.6, env.INK(linked ? 0xffffff : 0x666666));
      },
      // The theme's own row chevron, 12 x 16, white.
      chevron(ctx, x, y, c) {
        strokePath(ctx, CHEVRON_PATH, x, y, 3.2, c === undefined ? ownWhite() : c);
      },
      // Songs' Sort mark, 16 x 12: white through INK (never final).
      sortBars(ctx, x, y, c) {
        fillPath(ctx, SORT_PATH, x, y, mark(c));
      },
      // Classic's play state, 18 x 22: kind 'play' or 'pause'; T the theme whose bar.state.* colours it.
      state(ctx, x, y, kind, T = env.T) {
        const d = STATE_PATHS[kind === 'pause' ? 'pause' : 'play'];
        const halo = T(light ? 'bar.state.halo_light' : 'bar.state.halo_dark');
        if (halo > 0) strokePath(ctx, d, x, y, 2.6, 0xffffff, halo);
        ctx.save();
        ctx.translate(x, y);
        ctx.fillStyle = gradient(ctx, T('bar.state.stops'), 4, 19);
        ctx.fill(path2d(d), 'evenodd');
        ctx.strokeStyle = gradient(ctx, T('bar.state.edge'), 4, 19);
        ctx.lineWidth = lineWidth(1);
        ctx.lineJoin = 'round';
        ctx.stroke(path2d(d));
        ctx.restore();
      },
      // The battery's bolt (charging) and plug (full on power), 24 x 11, in bar.battery.bolt.
      bolt(ctx, x, y, T = env.T) {
        strokePath(ctx, BOLT_PATH, x, y, 1.6, 0xffffff, T('bar.battery.bolt_halo_a'));
        fillPath(ctx, BOLT_PATH, x, y, T('bar.battery.bolt'));
      },
      plug(ctx, x, y, T = env.T) {
        fillPath(ctx, PLUG_PATH, x, y, T('bar.battery.bolt'));
      },
      // The volume bar's ends over Classic's Now Playing: 8 x 13 and 18 x 13, white through INK.
      volLo(ctx, x, y, c) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(x, y, 8, 13);
        ctx.clip();
        fillPath(ctx, SPEAKER_PATH, x, y, mark(c));
        ctx.restore();
      },
      volHi(ctx, x, y, c) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(x, y, 18, 13);
        ctx.clip();
        fillPath(ctx, SPEAKER_PATH, x, y, mark(c));
        for (const d of VOL_WAVES) strokePath(ctx, d, x, y, 1.5, mark(c));
        ctx.restore();
      },
      // The classic-light volume panel's speakers, 12 x 14 and 22 x 14, in their own inks; c another
      // colour (the flat panel's white flat_spk_*, the same drawing).
      spkQuiet(ctx, x, y, c) {
        fillPath(ctx, SPEAKER_PATH, x, y, c === undefined ? (light ? 0x393c39 : 0xc6c3c6) : c);
      },
      spkLoud(ctx, x, y, c) {
        const v = c === undefined ? (light ? 0x393c39 : 0xc6c3c6) : c;
        fillPath(ctx, SPEAKER_PATH, x, y, v);
        for (const d of SPEAKER_ARCS) strokePath(ctx, d, x, y, 1.5, v);
      },
      // -- the flat look's (DRAWING.md 15.6). Each takes the half's flat ink unless c is given.
      // Home's pane note, flat (flat_pane_note), 100 x 115: note.svg's shape in one colour.
      flatNote(ctx, x, y, c) {
        fillPath(ctx, NOTE_SHAPE, x - 222, y - 66, c === undefined ? env.flatArt(FLAT_INK[light ? 1 : 0]) : c);
      },
      // A pane icon, flat (flat_pane_icon_*), 96 x 96: 'stack', 'folder', 'game', 'wave', 'gear', fitted as
      // paneIcon's, in one colour. 'note' is flatNote, at the note's place.
      flatPaneIcon(ctx, name, x, y, c) {
        if (name === 'note') return env.art.flatNote(ctx, x, y, c);
        const icon = PANE_ICONS[name];
        const [x0, y0, x1, y1] = icon.box;
        const k = Math.min(92 / (x1 - x0), 92 / (y1 - y0));
        ctx.save();
        ctx.translate(x - 230 + 278, y - 76 + 124);
        ctx.scale(k, k);
        ctx.translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
        ctx.fillStyle = css(c === undefined ? env.flatArt(FLAT_INK[light ? 1 : 0]) : c);
        ctx.fill(path2d(icon.d), 'evenodd');
        ctx.restore();
        return undefined;
      },
      // Now Playing's marks, flat (flat_np_*), 32 x 32: kind 'more', a play mode ('order', 'random',
      // 'cycle', 'cycle1'), or 'heart-on' / 'heart-off'.
      flatMark(ctx, kind, x, y, c) {
        const v = c === undefined ? env.flatArt(FLAT_INK[light ? 1 : 0]) : c;
        const mid = FLAT_BOX / 2;
        if (kind === 'heart-on' || kind === 'heart-off') {
          ctx.save();
          ctx.translate(x + mid, y + mid);
          ctx.scale(0.8, 0.8);
          ctx.translate(-16, -14.5);
          const shape = path2d(RATE_HEART);
          ctx.fillStyle = css(v);
          if (kind === 'heart-on') ctx.fill(shape, 'nonzero');
          ctx.strokeStyle = css(v);
          ctx.lineWidth = 2.4;
          ctx.lineJoin = 'round';
          ctx.stroke(shape);
          ctx.restore();
          return;
        }
        const g = FLAT_MARKS[FLAT_MODES[kind] || kind];
        if (!g) return;
        for (const d of g.fill || []) fillPath(ctx, d, x + mid, y + mid, v);
        for (const d of g.line || []) strokePath(ctx, d, x + mid, y + mid, FLAT_LINE, v);
        for (const [cx, cy, r] of g.dots || []) disc(ctx, x + mid + cx, y + mid + cy, r, v);
      },
      // Home's no-cover note (classic_light_note), 100 x 115: the drawing of note.svg.
      note(ctx, x, y) {
        const c = ownWhite();
        const white = (a) => css(c, Math.round(a * 255));
        const shape = path2d(NOTE_SHAPE);
        const gloss = path2d(NOTE_GLOSS);
        ctx.save();
        ctx.translate(x - 222, y - 66);
        const body = ctx.createLinearGradient(0, 70, 0, 178);
        body.addColorStop(0, white(0.52));
        body.addColorStop(0.45, white(0.38));
        body.addColorStop(1, white(0.3));
        ctx.fillStyle = body;
        ctx.fill(shape);
        ctx.save();
        ctx.clip(shape);
        const shine = ctx.createLinearGradient(0, 70, 0, 160);
        shine.addColorStop(0, white(1));
        shine.addColorStop(0.58, white(1));
        shine.addColorStop(0.8, white(0.45));
        shine.addColorStop(1, white(0));
        ctx.fillStyle = shine;
        for (let cx = 254; cx < 320; cx += 1) { // the gloss fades across, from x 285 to 317
          const t = clamp((cx + 0.5 - 285) / 32, 0, 1);
          ctx.save();
          ctx.beginPath();
          ctx.rect(cx, 66, 1, 115);
          ctx.clip();
          ctx.globalAlpha = 1 - t * (1 - 7 / 15);
          ctx.fill(gloss);
          ctx.restore();
        }
        ctx.restore();
        ctx.strokeStyle = white(0.42);
        ctx.lineWidth = lineWidth(1);
        ctx.stroke(shape);
        ctx.restore();
      },
      // A pane icon: 'stack', 'folder', 'game', 'wave', 'gear' (96 x 96) or 'note' (the Shuffle shortcut's,
      // 100 x 115, drawn at the note's place).
      paneIcon(ctx, name, x, y) {
        const icon = PANE_ICONS[name];
        const c = ownWhite();
        const white = (a) => css(c, Math.round(a * 255));
        const fit = name !== 'note';
        const [x0, y0, x1, y1] = icon.box;
        const k = fit ? Math.min(92 / (x1 - x0), 92 / (y1 - y0)) : 1;
        ctx.save();
        if (fit) {
          ctx.translate(x - 230 + 278, y - 76 + 124);
          ctx.scale(k, k);
          ctx.translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
        } else ctx.translate(x - 222, y - 66);
        const g = ctx.createLinearGradient(232, 74, 310, 168);
        [[0, 1], [0.42, 0.9], [0.52, 0.5], [1, 0.3]].forEach(([p, a]) => g.addColorStop(p, white(a)));
        ctx.fillStyle = g;
        ctx.fill(path2d(icon.d), 'evenodd');
        ctx.strokeStyle = white(0.42);
        ctx.lineWidth = lineWidth(1);
        ctx.lineJoin = 'round';
        ctx.stroke(path2d(icon.d));
        ctx.restore();
      },
      // The "no cover" placeholder (assets/icons/default_album_home.png, redrawn): a grey plate with a
      // white disc outline, at any size. square fills the plate's own clear corners.
      placeholder(ctx, x, y, size, square = false) {
        const u = size / 290;
        rrect(ctx, x, y, size, size, square ? 0 : 24 * u, 0x777777);
        ctx.save();
        ctx.translate(x + size / 2, y + size / 2);
        ctx.strokeStyle = '#ffffff';
        ctx.lineCap = 'round';
        ctx.lineWidth = Math.max(1, 5 * u);
        ctx.beginPath(); ctx.arc(0, 0, 71.5 * u, 0, Math.PI * 2); ctx.stroke();
        ctx.beginPath(); ctx.arc(0, 0, 16 * u, 0, Math.PI * 2); ctx.stroke();
        ctx.beginPath(); ctx.arc(0, 0, 45 * u, -Math.PI * 0.45, Math.PI * 0.08); ctx.stroke();
        ctx.beginPath(); ctx.arc(0, 0, 45 * u, Math.PI * 0.55, Math.PI * 1.08); ctx.stroke();
        ctx.restore();
      },

      // -- stand-ins for stock's pictures, redrawn here (DRAWING.md 3.6, "Stock")
      // list_into, the row chevron: a thin > in a 50 x 50 image, ink in columns 20..30, rows 16..33.
      listInto(ctx, x, y, c) {
        strokePath(ctx, 'M21 17 L30.4 24.9 L21 32.8', x, y, 1.9, mark(c), 255, 'butt');
      },
      // A Library or settings disc, size px across: stock's colour, or scheme.chevron's grey with a white
      // glyph under list.icons.mono. name: a key of Q2Draw.DISCS.
      // c: a colour to use instead (final). Under mono a disc whose icon is stock red (person) is grey too.
      disc(ctx, name, x, y, size, c) {
        let v = c;
        if (v === undefined && env.T('list.icons.mono')) {
          const g = (env.S.chevron === undefined ? 0x777777 : env.S.chevron) & 255;
          const n = clamp(Math.round(255 - (255 - g) * (MONO_RATIO[name] || 1)), 0, 255);
          v = pack(n, n, n);
        }
        if (v === undefined) v = DISCS[name] === STOCK_RED ? env.imageRed() : DISCS[name] === undefined ? 0x7f8c9b : DISCS[name];
        disc(ctx, x + size / 2, y + size / 2, size / 2, v);
        glyph(ctx, name, x + size / 2, y + size / 2, size * 0.36, 0xffffff);
      },
      // The grey tile of a Songs row or a folder (list_song, list_folder): size px, or
      // list.art.placeholder px centred in size. kind 'note' or 'folder'. Stock's #777777 in every theme:
      // the mono pass leaves an already grey picture as it is (navigation.c:5630).
      tile(ctx, kind, x, y, size = 52) {
        const n = env.T('list.art.placeholder') || size;
        const at = Math.floor((size - n) / 2);
        rrect(ctx, x + at, y + at, n, n, Math.max(2, n / 9), 0x777777);
        glyph(ctx, kind === 'folder' ? 'folder' : 'note', x + size / 2, y + size / 2, n * 0.34, 0xffffff);
      },
      // A settings switch, 50 x 24 with a 28 x 20 knob 2 px in: on is stock red in an image that also holds
      // white, so it takes the accent's light tone (imageRed); off is stock's #777777 and never flips.
      switch(ctx, x, y, on) {
        rrect(ctx, x, y, 50, 24, 12, on ? env.imageRed() : 0x777777);
        rrect(ctx, x + (on ? 20 : 2), y + 2, 28, 20, 10, 0xffffff);
      },
      // Songs' Play All mark and Sort mark under the stock set, each in a 50 x 50 box.
      playAll(ctx, x, y, c) {
        ctx.save();
        ctx.strokeStyle = css(mark(c));
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(x + 25, y + 25, 11, 0, Math.PI * 2); ctx.stroke();
        ctx.restore();
        fillPath(ctx, 'M22 20.5 L30 25 L22 29.5 Z', x, y, mark(c));
      },
      songOrder(ctx, x, y, c) {
        strokePath(ctx, 'M14 18 H31 M14 25 H26 M14 32 H22 M33 17 V33 M29.5 29.5 L33 33 L36.5 29.5', x, y, 1.8, mark(c), 255, 'butt');
      },
      // Now Playing's marks, each 24 x 24 on the canvas given: more (three dots), the heart (filled when
      // on), the play mode ('order', 'random', 'cycle', 'cycle1'). Flat #eeeeee through INK.
      more(ctx, x, y, c) {
        const v = c === undefined ? env.INK(0xeeeeee) : c;
        for (const cx of [2, 12, 22]) disc(ctx, x + cx, y + 12, 2, v);
      },
      // The heart's ink is rows 1..20 of its image and the play mode's columns 0..22 and rows 2..20
      // (DRAWING.md 7.2, the reference pictures' boxes).
      heart(ctx, x, y, on, c) {
        const v = c === undefined ? env.INK(0xeeeeee) : c;
        if (on) fillPath(ctx, HEART_PATH, x, y, v, 255, 'nonzero');
        strokePath(ctx, HEART_PATH, x, y, 1.8, v);
      },
      mode(ctx, x, y, kind = 'order', c) {
        const v = c === undefined ? env.INK(0xeeeeee) : c;
        if (MODE_PATHS[kind]) strokePath(ctx, MODE_PATHS[kind], x - 1, y - 1, 1.8, v, 255, 'butt');
        else fillPath(ctx, MODE_ORDER, x, y, v, 255, 'nonzero');
      },
      // The play-state glyph stock lays over the art (Modern): a dark disc and two bars (paused: a
      // triangle), size px across, at an opacity 0..255.
      overlay(ctx, x, y, size, kind = 'playing', opacity = 255) {
        if (opacity <= 0) return;
        ctx.save();
        ctx.globalAlpha = opacity / 255;
        disc(ctx, x + size / 2, y + size / 2, size / 2, 0x000000, 128);
        const u = size / 120;
        if (kind === 'paused') fillPath(ctx, `M${48 * u} ${34 * u} L${90 * u} ${60 * u} L${48 * u} ${86 * u} Z`, x, y, 0xffffff);
        else {
          rrect(ctx, x + 42 * u, y + 32 * u, 7 * u, 56 * u, 3.5 * u, 0xffffff);
          rrect(ctx, x + 71 * u, y + 32 * u, 7 * u, 56 * u, 3.5 * u, 0xffffff);
        }
        ctx.restore();
      },
      // The Centred page's Return mark, 24 x 24.
      back(ctx, x, y, c) {
        strokePath(ctx, 'M15 4 L7 12 L15 20', x, y, 2, c === undefined ? env.INK(0xeeeeee) : c, 255, 'butt');
      },
      // A Carousel card, size px: a coloured tile with a glyph (no stock card is copied).
      card(ctx, name, x, y, size = 190) {
        const c = DISCS[name] === undefined ? 0x5b6b7b : DISCS[name];
        rrect(ctx, x, y, size, size, size * 0.14, c);
        glyph(ctx, name, x + size / 2, y + size / 2, size * 0.3, 0xffffff);
      },
    };
    // A cover from the sample library, or the placeholder when i is null, in the theme's finish: square,
    // or its corners rounded (DRAWING.md 3.7).
    env.cover = cover;
    env.artwork = (ctx, i, x, y, size) => {
      const r = env.artRadius(size);
      ctx.save();
      if (r) {
        ctx.beginPath();
        roundRectPath(ctx, x, y, size, size, r);
        ctx.clip();
      }
      if (i === null || i === undefined) env.art.placeholder(ctx, x, y, size, env.artSquare);
      else cover(ctx, i, x, y, size, size);
      ctx.restore();
    };
    // A picture the host loaded for the repository's own art files (Q2Draw.images[name], see
    // PREVIEW_API.md), drawn into x, y, w, h. Returns false when there is none: draw a stand-in instead.
    env.image = (ctx, name, x, y, w, h) => {
      const im = Q2Draw.images[name];
      if (!im) return false;
      ctx.drawImage(im, x, y, w, h);
      return true;
    };

    // ---- shapes
    env.fill = fill;
    env.paintRows = rows;
    env.stops = paintStops;
    env.gradient = gradient;
    env.rrect = rrect;
    env.box = box;
    env.ring = ring;
    env.disc = disc;
    env.pillRows = pillRows;
    env.pillRadius = pillRadius;
    env.strokePath = strokePath;
    env.fillPath = fillPath;
    env.glyph = glyph;

    // ---- the status bar's theme (DRAWING.md section 4): the live theme unless Status Bar names another
    let barEnv = env;
    const which = opts.find((o) => o.setting === 'SETTING_OWN' && o.key === 'STATUSBAR');
    if (which && own.STATUSBAR > 0 && !choices.barOf) {
      const name = which.names[own.STATUSBAR];
      const other = data.themes.find((b) => b.resolved.name === name);
      if (other && other.resolved.id !== theme.id) barEnv = makeEnv(official, other.resolved, { half: env.half, barOf: true });
    }
    env.barTheme = barEnv; // its T, S, G and tones give the bar's look; INK stays the live theme's

    // ---- sample content that depends on the settings
    // Home's rows, hidden ones closed up: [{ id, title }].
    env.homeRows = () => {
      const out = [{ id: 'playing', title: 'Now Playing' }, { id: 'library', title: 'Library' }, { id: 'coverflow', title: 'Cover Flow' }];
      if (!env.hideFolder) out.push({ id: 'folder', title: 'Folder' });
      if (set.shortcut !== 'none') out.push({ id: set.shortcut, title: SHORTCUTS[set.shortcut] || 'Rockbox', shortcut: true });
      if (!env.hideStreaming) out.push({ id: 'streaming', title: 'Streaming' });
      out.push({ id: 'settings', title: 'Settings' });
      return out;
    };
    // Display > Appearance's rows for this theme and these settings: [{ title, value, kind }], kind
    // 'value' (a picker), 'switch' or 'page'; value is the shown value ('On' / 'Off' for a switch).
    env.appearanceRows = () => {
      const out = [{ title: 'Theme', value: theme.name, kind: 'value' }];
      const label = (n) => n.replace(/(^|[-_ ])([a-z])/g, (m, a, b) => (a ? ' ' : '') + b.toUpperCase());
      for (const o of opts) {
        if (o.setting === 'SETTING_OWN') {
          out.push({ title: o.label, value: o.names[own[o.key]], kind: 'value', key: o.key });
          continue;
        }
        const name = Object.keys(data.settings).find((n) => data.settings[n].macro === o.setting);
        const [title, values] = SETTING_LABELS[name] || [name, null];
        if (name === 'accent') out.push({ title, value: theme.schemes[accent].label || label(names[accent]), kind: 'value', key: name });
        else if (name === 'light') out.push({ title, value: light ? 'On' : 'Off', kind: 'value', key: name });
        else if (values === 'switch') out.push({ title, value: ['on', 'round', 'centred'].includes(set[name]) ? 'On' : 'Off', kind: 'switch', key: name });
        else out.push({ title, value: (values && values[set[name]]) || label(set[name]), kind: 'value', key: name });
      }
      out.push({ title: 'Hide Streaming', value: env.hideStreaming ? 'On' : 'Off', kind: 'switch' });
      out.push({ title: 'Hide Folder', value: env.hideFolder ? 'On' : 'Off', kind: 'switch' });
      return out;
    };
    env.sample = SAMPLE;
    return env;
  }

  // Draws one screen whole: clears the 375 x 320 frame, fills the page's paper, calls the screen (which
  // draws the status bar itself), then masks the glass's corners when env.glass. Returns the state used:
  // STATE, then the page's title, then the screen's first listed state, then the caller's.
  function render(ctx, id, env, state = {}) {
    const page = PAGES[id] || {};
    const screen = screens[id];
    const first = screen && Array.isArray(screen.states) && screen.states[0] ? screen.states[0].state : null;
    const s = Object.assign({}, STATE, { title: page.title || '', home: Boolean(page.home) }, first, state);
    ctx.save();
    ctx.clearRect(0, 0, W, H);
    ctx.beginPath();
    ctx.rect(0, 0, W, H);
    ctx.clip();
    fill(ctx, 0, 0, W, H, env.page);
    if (screen) screen.draw(ctx, env, s);
    else if (Q2Draw.bar) Q2Draw.bar(ctx, env, s);
    if (env.glass) glass(ctx);
    ctx.restore();
    return s;
  }

  const Q2Draw = {
    W, H, SEL_INSET, STOCK_RED,
    col, rgb, pack, hex, css, argb, mix, neutral, flip, stopsRows, redMap, div, clamp,
    glassInset, glass,
    fill, rows, paintStops, gradient, rrect, box, ring, disc, pillRows, pillRadius, roundRectPath, strokePath, fillPath, glyph, makeCanvas,
    FACES, FACE_NAMES, ROLES, faceHas, fallback, metrics, measure, measureExact, run, text, caps, resetText, loadFonts,
    sample: SAMPLE, cover, ART_SIZE, DISCS, PANE_ICONS, FLAT_MARKS, FLAT_REST, FLAT_INK, FLAT_QUIET, bright,
    images: {}, // the host's loaded pictures of the repository's own art files, by name
    plainText: false, // true draws text straight onto the canvas (no scratch canvas): see stamp()
    textOver: 0, // 1, 2 or 4 fixes how many times larger text is drawn before it is reduced; 0 picks by the scale
    PAGES, STATE, screens,
    env: makeEnv, render,
    bar: null, // draw_bar.js
  };
  return Q2Draw;
});
