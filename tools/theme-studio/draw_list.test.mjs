// node --test draw_list.test.mjs
// The list pages (draw_list.js) against DRAWING.md section 6: where each row's parts go, what every
// selection painter fills, separators, the scroll thumb, chevrons and the fast-scroll letter, and that each
// schema key section 11 lists as shown on these screens changes what is drawn. A recording stand-in for the
// canvas context writes every call down; the last test draws real pixels against the reference pictures and
// runs only where the dev harness's canvas and the pictures are.
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import official from './official.js';
import Q2Draw from './draw_core.js';
import './draw_bar.js';
import './draw_list.js';

const require = createRequire(import.meta.url);
const data = JSON.parse(readFileSync(new URL('./official.json', import.meta.url), 'utf8'));
const o = official.open(data);
const builtin = (id) => data.themes.find((b) => b.id === id).resolved;
const SCREENS = ['list-library', 'list-albums', 'list-songs', 'settings'];
if (!globalThis.Path2D) globalThis.Path2D = class { constructor(d) { this.d = d; } };

// A canvas context that draws nothing and writes down every call: [name, ...arguments], and for a call that
// puts ink down the styles in force. Text widths are made up (half the font's size a character).
function recorder() {
  const calls = [];
  const style = { fillStyle: '', strokeStyle: '', font: '', lineWidth: 1, globalAlpha: 1 };
  const plain = (a) => (a && typeof a === 'object' ? (a.d !== undefined ? `path ${a.d}` : a.stops ? `gradient ${JSON.stringify(a.stops)}` : 'object') : a);
  const own = {
    calls,
    measureText: (s) => ({ width: s.length * parseFloat(style.font.split(' ')[1]) * 0.5 }),
    createLinearGradient: (...at) => ({ at, stops: [], addColorStop(p, c) { this.stops.push([p, c]); } }),
    getTransform: undefined, // so text is drawn straight: one fillText a glyph
  };
  return new Proxy(own, {
    get(t, k) {
      if (k in t) return t[k];
      if (k in style) return style[k];
      return (...args) => {
        const call = [k, ...args.map(plain)];
        if (k === 'fillRect' || k === 'fill' || k === 'fillText') call.push(plain(style.fillStyle));
        if (k === 'stroke') call.push(plain(style.strokeStyle), style.lineWidth);
        if (k === 'fillText') call.push(style.font);
        calls.push(call);
      };
    },
    set(t, k, v) {
      style[k] = v;
      return true;
    },
  });
}

// Draws a screen for a resolved theme (or a built-in's id) and returns the recorder.
function draw(theme, choices, screen, state = {}) {
  const ctx = recorder();
  const env = Q2Draw.env(o, typeof theme === 'string' ? builtin(theme) : theme, choices);
  Q2Draw.render(ctx, screen, env, state);
  ctx.env = env;
  return ctx;
}
const sig = (ctx) => JSON.stringify(ctx.calls);
// the style of the last rectangle filled over a pixel
const at = (ctx, x, y) => {
  let style = null;
  for (const c of ctx.calls) if (c[0] === 'fillRect' && x >= c[1] && x < c[1] + c[3] && y >= c[2] && y < c[2] + c[4]) style = c[5];
  return style;
};
// where a text was drawn: its first glyph's x, its baseline, colour and font; null when it was not
const word = (ctx, str) => {
  const glyphs = ctx.calls.filter((c) => c[0] === 'fillText');
  const chars = Array.from(str);
  for (let i = 0; i + chars.length <= glyphs.length; i += 1) {
    if (chars.every((ch, j) => glyphs[i + j][1] === ch && glyphs[i + j][3] === glyphs[i][3])) return { x: glyphs[i][2], y: glyphs[i][3], colour: glyphs[i][4], font: glyphs[i][5] };
  }
  return null;
};
const px = (w) => parseFloat(w.font.split(' ')[1]); // a drawn text's CSS size
const cssPx = (face, size) => { const f = Q2Draw.FACES[face]; return (size * f.em) / (f.ascent - f.descent); };
const near = (a, b) => Math.abs(a - b) < 1e-6;
const count = (ctx, test) => ctx.calls.filter(test).length;
const translatedTo = (ctx, x, y) => count(ctx, (c) => c[0] === 'translate' && c[1] === x && c[2] === y);

// A new theme over a built-in, and the same with a change: [resolved, resolved changed].
function pair(base, change, both = () => {}) {
  const make = (fn) => {
    const t = o.newTheme({ extends: base, id: 'trial', name: 'Trial' });
    both(t);
    fn(t);
    return o.resolve(t);
  };
  return [make(() => {}), make(change)];
}

// ---- loading ----

test('a page loads the files with script tags; the four screens register as the contract says', async () => {
  const { runInNewContext } = await import('node:vm');
  const window = {};
  Object.assign(window, { globalThis: window });
  for (const f of ['draw_core.js', 'draw_bar.js', 'draw_list.js']) runInNewContext(readFileSync(new URL(`./${f}`, import.meta.url), 'utf8'), window);
  for (const id of SCREENS) {
    const s = window.Q2Draw.screens[id];
    assert.equal(typeof s.draw, 'function', id);
    assert.equal(typeof s.title, 'string', id);
    assert.ok(Array.isArray(s.states) && s.states.length >= 2 && s.states.every((x) => x.id && x.label && typeof x.state === 'object'), `${id}: named states`);
    assert.equal(s.states[0].state.selected, 0, `${id}: the first state is the first row selected`);
    assert.ok(Q2Draw.PAGES[id], `${id} is a page the core knows`);
  }
  assert.ok(Q2Draw.screens['list-albums'].states.some((s) => s.state.letter), 'the fast-scroll letter is a state of Albums');
  assert.ok(Q2Draw.screens['list-songs'].states.some((s) => s.state.letter), 'and of Songs');
});

test('the script holds no embedded picture, no eval and no page of its own', () => {
  const text = readFileSync(new URL('./draw_list.js', import.meta.url), 'utf8');
  assert.ok(!/data:image|base64|\beval\(|new Function|<script|fillText|https?:/.test(text));
});

test('drawing leaves no clip or transform behind, and ends with the status bar', () => {
  for (const id of SCREENS) {
    const ctx = draw('classic-light', {}, id, { selected: 1, letter: true });
    assert.equal(count(ctx, (c) => c[0] === 'save'), count(ctx, (c) => c[0] === 'restore'), id);
    assert.ok(word(ctx, '9:41'), `${id}: the bar is drawn`);
  }
});

// ---- rows: DRAWING.md 6.6 ----

test('the Library (6.6): icon, title and chevron under the stock set; text alone with Search first under Classic', () => {
  const m = draw('minimal', { half: 'dark' }, 'list-library');
  const title = word(m, 'Shuffle');
  assert.equal(title.x, 94, 'the title box starts at 92: text from 94');
  assert.ok(near(px(title), cssPx('regular', 24)), 'stock 24 px');
  assert.equal(title.y, 30 + 22 + 18, 'the 24 px line centred in the 68 px body');
  assert.equal(word(m, 'Artists').y, title.y + 72, 'rows 72 apart');
  assert.equal(word(m, 'Search'), null);
  // a 52 px disc centred in the icon box (28, y0, 52, 68): its circle about (54, y0 + 34)
  assert.ok(count(m, (c) => c[0] === 'arc' && c[1] === 54 && c[2] === 64 && c[3] === 26) >= 1);
  // stock's chevron image centred in its box (302, y0, 50, 68) on every row in sight
  for (const y0 of [30, 102, 174, 246]) assert.equal(translatedTo(m, 302, y0 + 9), 1, `chevron of the row at ${y0}`);

  const c = draw('classic-light', { half: 'light' }, 'list-library');
  const search = word(c, 'Search');
  assert.deepEqual([search.x, search.y], [22, 26 + 23], 'Classic: ink from x 22, baseline y0 + 23');
  assert.ok(near(px(search), cssPx('classic-light', 27)) && /TeX Gyre Heros/.test(search.font));
  assert.equal(word(c, 'Shuffle').y, 26 + 32 + 23, 'rows 32 apart');
  assert.equal(count(c, (call) => call[0] === 'arc' && call[2] >= 26), 0, 'no icons');
  assert.equal(translatedTo(c, 317, 26 + 16 - 8), 1, "the selected row's chevron at list.chevron.x");
  assert.equal(count(c, (call) => call[0] === 'translate' && call[1] === 317), 1, 'and on no other row');
});

test('Albums (6.6): cover and two lines; Classic on its own columns; Row Art off is one line of text', () => {
  const m = draw('modern', { half: 'dark' }, 'list-albums');
  const title = word(m, 'Dusk on the Ridge');
  const artist = word(m, 'The Reference Band');
  assert.deepEqual([title.x, title.y], [96, 30 + 13 + 18], 'title box (94, y0 + 13, 189, 24)');
  assert.deepEqual([artist.x, artist.y], [96, 30 + 39 + 12], 'second line box (94, y0 + 39, 151, 16)');
  assert.ok(near(px(title), cssPx('regular', 24)) && near(px(artist), cssPx('regular', 16)));
  assert.equal(count(m, (c) => c[0] === 'rect' && c[1] === 28 && c[2] === 38 && c[3] === 52 && c[4] === 52), 1, 'the cover at (28, y0 + 8)');
  assert.equal(translatedTo(m, 297, 39), 1, 'the chevron box at x 297');

  const c = draw('classic-light', { half: 'light' }, 'list-albums');
  const t = word(c, 'Dusk on the Ridge');
  const a = word(c, 'The Reference Band');
  assert.equal(t.x, 82, 'text from list.art.text_x');
  assert.ok(near(px(t), cssPx('classic-light', 28)), 'the tall role, 28 px');
  assert.ok(near(px(a), cssPx('regular', 17)), 'the meta role, 17 px');
  // each label centred on its box's middle: centre lines y0 + 13 and y0 + 37
  assert.equal(t.y, 26 + 1 + Math.floor((24 - 28) / 2) + Q2Draw.metrics('classic-light', 28).ascent);
  assert.equal(a.y, 26 + 29 + Math.floor((16 - 17) / 2) + Q2Draw.metrics('regular', 17).ascent);
  assert.equal(count(c, (call) => call[0] === 'rect' && call[1] === 22 && call[2] === 26 && call[3] === 52), 1, 'the cover at (list.art.x, y0)');
  assert.equal(word(c, 'Afterglow').y, t.y + 52);
  assert.equal(translatedTo(c, 317, 26 + 26 - 8), 1);

  const off = draw('classic-light', { half: 'light', ROWART: 'Off' }, 'list-albums');
  assert.equal(off.env.setName, 'classic-light-text');
  const one = word(off, 'Dusk on the Ridge');
  assert.deepEqual([one.x, one.y], [22, 26 + 4 + Math.floor((24 - 27) / 2) + Q2Draw.metrics('classic-light', 27).ascent], 'box (20, y0 + 4, 292, 24), 27 px');
  assert.equal(word(off, 'The Reference Band'), null, 'the second line hides');
  assert.equal(count(off, (call) => call[0] === 'rect' && call[3] === 52 && call[4] === 52), 0, 'no covers');
  assert.equal(word(off, 'Afterglow').y, one.y + 32);
});

test('Songs (6.6): Play All as stock\'s bar or as a plain row, the tile, the two lines', () => {
  const m = draw('minimal', { half: 'dark' }, 'list-songs');
  const play = word(m, 'Play All');
  assert.equal(play.x, 72, 'box (70, 30, 130, 50)');
  assert.ok(near(px(play), cssPx('regular', 20)));
  assert.equal(translatedTo(m, 16, 30), 1, 'Play All\'s mark in (16, 30, 50, 50)');
  assert.equal(translatedTo(m, 306, 30), 1, 'the Sort mark in (306, 30, 50, 50)');
  assert.deepEqual([word(m, 'Evening Signal').x, word(m, 'Evening Signal').y], [96, 80 + 13 + 18], 'the list starts under the 50 px bar');
  assert.equal(word(m, 'Above the Tree Line').y, 80 + 72 + 13 + 18);
  assert.equal(count(m, (c) => c[0] === 'translate' && (c[1] === 297 || c[1] === 302)), 0, 'no chevrons');

  const c = draw('classic-light', { half: 'light' }, 'list-songs');
  assert.equal(word(c, 'Play All').x, 22, 'the row\'s label at the set\'s text x');
  assert.ok(near(px(word(c, 'Play All')), cssPx('classic-light', 27)));
  assert.equal(translatedTo(c, 317, 36), 1, 'the Sort mark centred in (301, 26, 48, 32)');
  const song = word(c, 'Evening Signal');
  assert.equal(song.x, 22);
  assert.equal(song.y, 58 + 1 + Math.floor((24 - 28) / 2) + Q2Draw.metrics('classic-light', 28).ascent, 'the list starts at screen y 58');
  assert.equal(word(c, 'Above the Tree Line').y, song.y + 52);
  assert.equal(count(c, (call) => call[0] === 'translate' && call[1] === 317 && call[2] !== 36), 0, 'no chevron on a song');
});

test('settings (6.6): the list\'s top, icons, "Title: value", switches; Classic\'s right-aligned values', () => {
  const m = draw('minimal', { half: 'dark' }, 'settings');
  assert.equal(at(m, 187, 37), '#000000', 'Minimal\'s list starts at y 38');
  assert.ok(count(m, (c) => c[0] === 'arcTo') > 0, 'its selection is a capsule');
  const first = word(m, 'Theme: Minimal');
  assert.deepEqual([first.x, first.y], [82, 38 + 22 + 18], 'text box from x 80, the row\'s full height');
  assert.equal(word(m, 'Status Bar: Theme').y, first.y + 68);
  assert.ok(count(m, (c) => c[0] === 'arc' && c[1] === 48 && c[2] === 38 + 34 && c[3] === 20) >= 1, 'a 40 px icon at (28, y0 + 14)');
  assert.ok(word(m, 'Time in Title') && !word(m, 'Time in Title: On'), 'a switch row has its title alone');
  // the switch: its 50 x 24 pill centred in (301, y0, 50, 68), filled the accent's light tone when on
  const row = 38 + 2 * 68;
  assert.ok(count(m, (c) => c[0] === 'moveTo' && c[1] === 301 + 12 && c[2] === row + 22) >= 1, 'the pill at (301, y0 + 22)');
  assert.ok(count(m, (c) => c[0] === 'fill' && c[c.length - 1] === '#6e6e6e') >= 1, 'Graphite, on');
  const modern = draw('modern', { half: 'dark' }, 'settings');
  assert.equal(at(modern, 187, 30), '#447cdd', 'Modern\'s list starts at y 30');
  assert.ok(count(modern, (c) => c[0] === 'fill' && c[c.length - 1] === '#777777') >= 1, 'Time in Title off: stock\'s grey');
  assert.equal(count(draw('modern', { half: 'dark', time_title: 'on' }, 'settings'), (c) => c[0] === 'fill' && c[c.length - 1] === '#447cdd'), 1, 'on: Cobalt\'s light tone');
  assert.equal(count(draw('modern', { half: 'dark', time_title: 'on', accent: 'crimson' }, 'settings'), (c) => c[0] === 'fill' && c[c.length - 1] === '#ff1448'), 1, 'Crimson keeps stock red in the dark half');
  assert.ok(count(draw('modern', { half: 'light', time_title: 'on', accent: 'graphite' }, 'settings'), (c) => c[0] === 'fill' && c[c.length - 1] === '#383838') >= 1, 'Graphite in the light half');

  const c = draw('classic-light', { half: 'light' }, 'settings');
  const title = word(c, 'Theme');
  assert.deepEqual([title.x, title.y], [22, 26 + 23]);
  const value = word(c, 'Classic');
  assert.equal(value.x + Q2Draw.measure(c, 'Classic', 'classic-light', 27), 353, 'the value right-aligned in (219, y0, 136, 32)');
  assert.equal(value.colour, title.colour);
  const on = word(c, 'On');
  assert.equal(on.x + Q2Draw.measure(c, 'On', 'classic-light', 27), 353, '"On" right-aligned in (313, y0, 42, 32)');
  assert.equal(word(c, 'Accent').y, 26 + 5 * 32 + 23);
  assert.ok(word(c, 'Classic Blue'));
  assert.equal(count(c, (call) => call[0] === 'arc' && call[2] >= 26), 0, 'no icons');
  assert.equal(count(c, (call) => call[0] === 'arcTo'), 0, 'no switches: nothing rounded');
  assert.equal(count(c, (call) => call[0] === 'translate' && call[1] === 317), 0, 'a picker row has no chevron');
});

// ---- the selection: 6.2 ----

test('every selection painter over a list row (6.2)', () => {
  // card: a capsule inset 6 under Rounded Corners on Library rows, square on cover rows; square without it
  const lib = draw('minimal', { half: 'dark' }, 'list-library');
  assert.equal(at(lib, 187, 60), '#000000', 'a rounded card is a path, not a rectangle');
  assert.ok(count(lib, (c) => c[0] === 'fill' && c[c.length - 1] === '#424242') >= 1);
  assert.ok(count(lib, (c) => c[0] === 'moveTo' && c[1] === 6 + 36 && c[2] === 30) >= 1, 'radius 36 from x 6');
  const albums = draw('minimal', { half: 'dark' }, 'list-albums');
  assert.deepEqual([at(albums, 6, 30), at(albums, 5, 30), at(albums, 368, 101), at(albums, 369, 101), at(albums, 187, 102)], ['#424242', '#000000', '#424242', '#000000', '#000000'], 'square, (6, y0, 363, 72)');
  const square = draw('minimal', { half: 'light', corners: 'square' }, 'list-library');
  assert.deepEqual([at(square, 0, 30), at(square, 374, 101)], ['#bbbbbb', '#bbbbbb'], 'Graphite flips with the half');
  assert.equal(word(square, 'Shuffle').colour, '#161616');
  assert.equal(at(draw('minimal', { half: 'dark', accent: 'ivory', corners: 'square' }, 'list-songs'), 187, 100), '#eeeeec', 'a card scheme: scheme.fill');
  assert.equal(word(draw('minimal', { half: 'dark', accent: 'ivory' }, 'list-songs'), 'The Reference Band').colour, '#171717');
  // bar: the highlight row, then the accent, full width
  const bar = draw('modern', { half: 'light' }, 'list-albums');
  assert.deepEqual([at(bar, 0, 30), at(bar, 374, 31), at(bar, 187, 101), at(bar, 187, 102)], ['#447cdd', '#2a6ad8', '#2a6ad8', '#f4f4f4']);
  assert.equal(word(bar, 'The Reference Band').colour, '#ffffff', 'text stays white on a coloured bar in the light half');
  assert.equal(word(bar, 'Mira Vale').colour, '#161616', 'an unselected second line is ink');
  const second = draw('modern', { half: 'dark' }, 'list-songs', { selected: 1 });
  assert.deepEqual([at(second, 187, 80), at(second, 187, 152), at(second, 187, 153)], ['#000000', '#447cdd', '#2a6ad8'], 'the selected row is the state\'s');
  // stops: top, the band, edge; the tall form on rows higher than the set's pitch
  const stops = draw('classic-light', { half: 'light' }, 'list-library');
  assert.deepEqual([at(stops, 0, 26), at(stops, 374, 27), at(stops, 187, 56), at(stops, 187, 57), at(stops, 187, 58)], ['#94c7de', '#08a6e7', '#0065d6', '#004184', '#ffffff']);
  assert.equal(word(stops, 'Search').colour, '#ffffff', 'sel.text');
  const tall = draw('classic-light', { half: 'light' }, 'list-albums');
  assert.deepEqual([at(tall, 187, 26), at(tall, 187, 27), at(tall, 187, 76), at(tall, 187, 77)], ['#94c7de', '#27ade5', '#004aa3', '#688db3']);
  assert.equal(word(tall, 'The Reference Band').colour, '#ffffff');
  assert.equal(word(tall, 'Mira Vale').colour, '#6b6d6b', 'scheme.muted through the half');
  assert.equal(word(draw('classic-light', { half: 'dark' }, 'list-albums'), 'Mira Vale').colour, '#949294');
  // no row selected: no selection
  assert.equal(at(draw('classic-light', { half: 'light' }, 'list-library', { selected: null }), 187, 40), '#ffffff');
});

// ---- separators, thumb, chevrons, letter: 6.3 to 6.5, 6.8 ----

test('separators (6.3): the last rows of two-line rows and of Play All\'s row, never the selected row', () => {
  const c = draw('classic-light', { half: 'light' }, 'list-songs');
  assert.deepEqual([55, 56, 57].map((y) => at(c, 187, y)), ['#fcfcfc', '#e2e3e2', '#f7f7f7'], 'Play All\'s row');
  assert.deepEqual([159, 160, 161].map((y) => at(c, 0, y)), ['#fcfcfc', '#e2e3e2', '#f7f7f7'], 'the second song');
  assert.deepEqual([at(c, 187, 108), at(c, 187, 109)], ['#004aa3', '#688db3'], 'the selected row keeps its band');
  const d = draw('classic-light', { half: 'dark' }, 'list-songs', { selected: 1 });
  assert.deepEqual([107, 108, 109].map((y) => at(d, 374, y)), ['#000000', '#2c2c2c', '#000000']);
  for (const [theme, screen] of [['classic-light', 'list-albums'], ['classic-light', 'list-library'], ['classic-light', 'settings'], ['minimal', 'list-songs']]) {
    const x = draw(theme, { half: 'dark' }, screen, { selected: null });
    assert.equal(count(x, (call) => call[0] === 'fillRect' && call[1] === 0 && call[3] === 375 && call[4] === 1 && call[2] > x.env.bar && call[5] !== '#000000'), 0, `${theme} ${screen}: none`);
  }
});

test('the scroll thumb (6.5): Classic\'s track, length and place; none under the stock set', () => {
  const albums = draw('classic-light', { half: 'light' }, 'list-albums');
  // 12 rows of 52 in 294: 95 of the track's 202 rows, from row 59
  assert.deepEqual([at(albums, 368, 100), at(albums, 369, 100), at(albums, 372, 100), at(albums, 373, 100)], ['#ffffff', '#8f98a8', '#8f98a8', '#ffffff']);
  assert.equal(at(albums, 370, 61), '#8f98a8');
  assert.notEqual(at(albums, 370, 58), '#8f98a8');
  assert.equal(at(albums, 370, 151), '#8f98a8');
  assert.ok(/^rgba\(143,152,168/.test(at(albums, 369, 59)) && /^rgba\(143,152,168/.test(at(albums, 369, 153)), 'both ends rounded');
  assert.notEqual(String(at(albums, 370, 154)).slice(0, 16), 'rgba(143,152,168');
  assert.equal(at(draw('classic-light', { half: 'dark' }, 'list-albums'), 370, 100), '#6e7380', 'the dark half\'s thumb');
  // scrolled: row 9 selected stops at list_end (256), 264 px down; the thumb moves (202 - 95) * 264 / 624
  const down = draw('classic-light', { half: 'light' }, 'list-albums', { selected: 9 });
  assert.equal(at(down, 187, 26 + 256 - 2), '#004aa3', 'the selected row ends at list_end');
  const thumb = (ctx, x, y) => /^(#8f98a8|rgba\(143,152,168)/.test(String(at(ctx, x, y)));
  assert.deepEqual([103, 104, 198, 199].map((y) => thumb(down, 370, y)), [false, true, true, false], 'rows 104..198');
  assert.deepEqual([at(down, 370, 106), at(down, 370, 196)], ['#8f98a8', '#8f98a8']);
  // the Library: 16 rows of 32, 115 rows of thumb; Songs: the table under Play All's row
  const lib = draw('classic-light', { half: 'light' }, 'list-library', { selected: null });
  assert.deepEqual([at(lib, 370, 171), at(lib, 370, 174)], ['#8f98a8', '#ffffff']);
  const songs = draw('classic-light', { half: 'light' }, 'list-songs', { selected: null });
  assert.deepEqual([at(songs, 370, 61), at(songs, 370, 140), at(songs, 370, 144)], ['#8f98a8', '#8f98a8', '#ffffff'], '202 * 262 / 624 = 84 rows');
  for (const id of SCREENS) assert.equal(count(draw('modern', { half: 'dark' }, id, { selected: 5 }), (c) => c[0] === 'fillRect' && c[1] >= 360 && c[3] <= 8 && c[2] >= 30), 0, `modern ${id}: stock's own bar is not drawn`);
});

test('chevrons (6.4): stock\'s on every row, white on a coloured selection in the light half; the theme\'s on the selected row', () => {
  const stroke = (ctx, x, y) => {
    const i = ctx.calls.findIndex((c) => c[0] === 'translate' && c[1] === x && c[2] === y);
    return ctx.calls.slice(i).find((c) => c[0] === 'stroke')[2];
  };
  const dark = draw('modern', { half: 'dark' }, 'list-library');
  assert.equal(stroke(dark, 302, 39), '#ffffff');
  const light = draw('modern', { half: 'light' }, 'list-library');
  assert.equal(stroke(light, 302, 39), '#ffffff', 'the selected row\'s stays white');
  assert.equal(at(light, 302 + 25, 30 + 34), '#2a6ad8', 'over a patch of the accent');
  assert.equal(stroke(light, 302, 111), '#161616', 'the others flip to ink');
  assert.equal(stroke(draw('modern', { half: 'light', accent: 'graphite' }, 'list-library'), 302, 39), '#161616', 'a neutral accent is not a coloured selection');
  assert.equal(stroke(draw('minimal', { half: 'dark', accent: 'ivory' }, 'list-library'), 302, 39), '#777777', 'a card scheme inks it scheme.chevron');
  assert.equal(stroke(draw('minimal', { half: 'light', accent: 'ivory' }, 'list-library'), 302, 39), '#8d8d8d');
  const classic = draw('classic-light', { half: 'light' }, 'list-library', { selected: 3 });
  assert.equal(stroke(classic, 317, 26 + 3 * 32 + 8), '#ffffff', 'final white in the light half');
  assert.equal(count(classic, (c) => c[0] === 'translate' && c[1] === 317), 1);
});

test('the fast-scroll letter (6.8) is a state of Albums and Songs', () => {
  const letter = (ctx) => ctx.calls.filter((c) => c[0] === 'fillText' && near(parseFloat(c[5].split(' ')[1]), cssPx(/Heros/.test(c[5]) ? 'classic-light' : 'regular', 60)));
  const m = draw('minimal', { half: 'dark' }, 'list-albums', { selected: 3, letter: true });
  assert.deepEqual(letter(m).map((c) => [c[1], c[4]]), [['C', '#ffffff']], 'the selected row\'s first letter, white, 60 px');
  assert.ok(count(m, (c) => c[0] === 'moveTo' && c[1] === 147 + 12 && c[2] === 30 + 105) >= 1, 'an 80 px box centred on the list, radius 12');
  assert.ok(count(m, (c) => c[0] === 'fill' && /^rgba\(43,43,43,0\.85/.test(c[c.length - 1])) >= 1, '#2b2b2b at alpha 217');
  const light = draw('minimal', { half: 'light' }, 'list-songs', { selected: 2, letter: true });
  assert.deepEqual(letter(light).map((c) => [c[1], c[4]]), [['B', '#161616']], 'through the half');
  assert.ok(count(light, (c) => c[0] === 'fill' && /^rgba\(207,207,207/.test(c[c.length - 1])) >= 1);
  assert.ok(count(light, (c) => c[0] === 'moveTo' && c[1] === 147 + 12 && c[2] === 80 + 80) >= 1, 'centred on Songs\' list (80, 240)');
  const c = draw('classic-light', { half: 'light' }, 'list-albums', { selected: 1, letter: true });
  assert.deepEqual(letter(c).map((x) => [x[1], x[4], /Heros/.test(x[5])]), [['A', '#ffffff', true]], 'Classic: its own face, final colours');
  assert.ok(count(c, (x) => x[0] === 'fill' && /^rgba\(43,43,43/.test(x[x.length - 1])) >= 1);
  assert.equal(letter(draw('classic-light', { half: 'light' }, 'list-albums', { selected: 1 })).length, 0);
  for (const id of ['list-library', 'settings']) assert.ok(sig(draw('minimal', {}, id, { selected: 2, letter: true })) === sig(draw('minimal', {}, id, { selected: 2 })), `${id} never shows one`);
});

// ---- every key of section 11 these screens show ----

// [key, the built-in the trial theme extends, the change, the screens that must change, the viewer's choices,
// the state, what both themes share]. A screen listed with ! must stay as it was.
const noRowArt = (t) => o.removeOption(t, 'ROWART');
const KEYS = [
  ['geometry.set', 'classic-light', (t) => { o.addGeometry(t, 'roomy', 'classic-light', { pitch: 40, body: 40, lib_pitch: 44, lib_body: 44, set_row: 40, set_rows: 7, art_pitch: 60, art_body: 60, song_pitch: 60, song_body: 60, text_x: 30, action_row: 40 }); o.useGeometry(t, 'roomy'); }, SCREENS, {}, {}, noRowArt],
  ['list.selection.painter', 'modern', (t) => o.set(t, 'list.selection.painter', 'card'), SCREENS],
  ['list.chevron.selected', 'modern', (t) => o.set(t, 'list.chevron.selected', 1), ['list-library', 'list-albums', '!list-songs', '!settings']],
  ['list.chevron.x', 'classic-light', (t) => o.set(t, 'list.chevron.x', 330), ['list-library', 'list-albums', '!list-songs', '!settings']],
  ['list.art.x', 'classic-light', (t) => o.set(t, 'list.art.x', 30), ['list-albums', '!list-library', '!settings']],
  ['list.art.text_x', 'classic-light', (t) => o.set(t, 'list.art.text_x', 96), ['list-albums', '!list-library', '!list-songs', '!settings']],
  ['list.art.text_end', 'classic-light', (t) => o.set(t, 'list.art.text_end', 200), ['list-albums', '!list-library', '!list-songs', '!settings']],
  ['list.art.placeholder', 'modern', (t) => o.set(t, 'list.art.placeholder', 30), ['list-songs', '!list-library', '!list-albums', '!settings']],
  ['list.row.text_end', 'classic-light', (t) => o.set(t, 'list.row.text_end', 120), ['list-songs', '!list-library', '!list-albums', '!settings']],
  ['list.row.font', 'modern', (t) => o.set(t, 'list.row.font', 'bold'), SCREENS],
  ['list.row.title_px', 'modern', (t) => o.set(t, 'list.row.title_px', 20), SCREENS],
  ['list.row.meta_font', 'modern', (t) => o.set(t, 'list.row.meta_font', 'bold'), ['list-albums', 'list-songs', '!list-library', '!settings']],
  ['list.row.meta_px', 'modern', (t) => o.set(t, 'list.row.meta_px', 14), ['list-albums', 'list-songs', '!list-library', '!settings']],
  ['list.row.tall_font', 'classic-light', (t) => o.set(t, 'list.row.tall_font', 'regular'), ['list-albums', 'list-songs', '!list-library', '!settings']],
  ['list.row.tall_px', 'classic-light', (t) => o.set(t, 'list.row.tall_px', 24), ['list-albums', 'list-songs', '!list-library', '!settings']],
  ['list.separator.stops', 'classic-light', (t) => o.set(t, 'list.separator.stops', '#ff0000 0, #00ff00 100'), ['list-songs', '!list-library', '!list-albums', '!settings'], { half: 'dark' }],
  ['list.scrollbar.w', 'classic-light', (t) => o.set(t, 'list.scrollbar.w', 8), SCREENS],
  ['list.scrollbar.right', 'classic-light', (t) => o.set(t, 'list.scrollbar.right', 9), SCREENS],
  ['list.scrollbar.top', 'classic-light', (t) => o.set(t, 'list.scrollbar.top', 90), SCREENS],
  ['list.scrollbar.bottom', 'classic-light', (t) => o.set(t, 'list.scrollbar.bottom', 200), SCREENS],
  ['list.scrollbar.min', 'classic-light', (t) => o.set(t, 'list.scrollbar.min', 150), SCREENS],
  ['list.scrollbar.thumb', 'classic-light', (t) => o.set(t, 'list.scrollbar.thumb', '#ff0000', 'light'), SCREENS, { half: 'light' }],
  ['list.icons.mono', 'modern', (t) => o.set(t, 'list.icons.mono', 1), ['list-library', 'settings', '!list-albums']],
  ['list.letter.raw', 'modern', (t) => o.set(t, 'list.letter.raw', 1), ['list-albums', 'list-songs', '!list-library', '!settings'], { half: 'light' }, { selected: 2, letter: true }],
  ['list.letter.px', 'modern', (t) => o.set(t, 'list.letter.px', 40), ['list-albums', 'list-songs', '!list-library', '!settings'], {}, { selected: 2, letter: true }],
  ['settings.rows.top', 'modern', (t) => o.set(t, 'settings.rows.top', 12), ['settings', '!list-library', '!list-albums', '!list-songs']],
  ['settings.values.text', 'modern', (t) => o.set(t, 'settings.values.text', 1), ['settings', '!list-library', '!list-albums', '!list-songs']],
  ['playing.art.square', 'modern', (t) => o.set(t, 'playing.art.square', 0), ['list-albums', '!list-library', '!settings']],
  ['scheme.paper', 'modern', (t) => o.setScheme(t, null, 'paper', '#e0e0e0'), SCREENS, { half: 'light' }],
  ['scheme.ink', 'modern', (t) => o.setScheme(t, null, 'ink', '#404040'), SCREENS, { half: 'light' }],
  ['scheme.mode', 'modern', (t) => o.setScheme(t, null, 'mode', 'light'), SCREENS, { half: 'dark' }],
  ['scheme.card', 'minimal', (t) => o.setScheme(t, 'graphite', 'card', 1), SCREENS, { accent: 'graphite' }],
  ['scheme.fill', 'minimal', (t) => o.setScheme(t, null, 'fill', '#d0e0f0'), SCREENS, { accent: 'ivory' }],
  ['scheme.chevron', 'minimal', (t) => o.setScheme(t, null, 'chevron', '#505050'), ['list-library', 'settings', '!list-songs']],
  ['scheme.muted', 'classic-light', (t) => o.setScheme(t, null, 'muted', '#40a040'), ['list-albums', 'list-songs', '!list-library', '!settings']],
  ['scheme.raw_red', 'modern', (t) => o.setScheme(t, 'crimson', 'raw_red', 0), ['list-library', 'settings', '!list-albums', '!list-songs'], { half: 'dark', accent: 'crimson', time_title: 'on' }],
  ['scheme.sel.stops', 'classic-light', (t) => o.setScheme(t, 'classic-blue', 'sel.stops', '#ffd040 0, #c07000 100'), SCREENS],
  ['scheme.sel.top', 'classic-light', (t) => o.setScheme(t, 'classic-blue', 'sel.top', '#ff0000', 'light'), SCREENS, { half: 'light' }],
  ['scheme.sel.edge', 'classic-light', (t) => o.setScheme(t, 'classic-blue', 'sel.edge', '#ff0000'), ['list-library', 'settings', '!list-albums', '!list-songs']],
  ['scheme.sel.text', 'classic-light', (t) => o.setScheme(t, 'classic-blue', 'sel.text', '#ffff00'), SCREENS, { half: 'dark' }],
  ['scheme.sel.tall_edge', 'classic-light', (t) => o.setScheme(t, 'classic-blue', 'sel.tall_edge', '#ff0000'), ['list-albums', 'list-songs', '!list-library', '!settings']],
  ['scheme.sel.tall_line', 'classic-light', (t) => o.setScheme(t, 'classic-blue', 'sel.tall_line', '#ff0000', 'light'), ['list-albums', 'list-songs', '!list-library', '!settings'], { half: 'light' }],
  ['scheme.sel.tall_top', 'classic-light', (t) => o.setScheme(t, 'classic-blue', 'sel.tall_top', '#ff0000', 'light'), ['list-albums', 'list-songs', '!list-library', '!settings'], { half: 'light' }],
];

test('each key section 11 lists for the list pages changes the drawing, and only where it should', () => {
  for (const [key, base, change, screens, choices = {}, state = {}, both] of KEYS) {
    const [a, b] = pair(base, change, both);
    for (const entry of screens) {
      const same = entry.startsWith('!');
      const id = same ? entry.slice(1) : entry;
      const before = sig(draw(a, choices, id, state));
      const after = sig(draw(b, choices, id, state));
      assert.ok((after === before) === same, same ? `${key} leaves ${id} alone` : `${key} changes ${id}`);
    }
  }
});

test('pages.own.art_final (section 11): with 0 the theme\'s chevron turns to ink in the light half', () => {
  // only the built-in may state 1: a theme over it states 0
  const [mine] = pair('classic-light', () => {});
  const stroke = (theme, half) => {
    const ctx = draw(theme, { half }, 'list-library');
    const i = ctx.calls.findIndex((c) => c[0] === 'translate' && c[1] === 317);
    return ctx.calls.slice(i).find((c) => c[0] === 'stroke')[2];
  };
  assert.equal(mine.art_final, 0);
  assert.deepEqual([stroke('classic-light', 'light'), stroke(mine, 'light'), stroke('classic-light', 'dark'), stroke(mine, 'dark')], ['#ffffff', '#000000', '#ffffff', '#ffffff']);
});

test('keys section 11 marks "No" leave the list pages as they were', () => {
  const none = [
    ['modern', (t) => o.set(t, 'list.icons.badge_muted', 1)], ['modern', (t) => o.set(t, 'list.icons.addon_mono', 1)], ['modern', (t) => o.set(t, 'list.icons.badge_ink', 1)],
    ['classic-light', (t) => o.set(t, 'page.rows.height', 40)], ['classic-light', (t) => o.set(t, 'playing.info.font', 'regular')], ['modern', (t) => o.set(t, 'playing.layout', 'centred')],
  ];
  for (const [base, change] of none) {
    const [a, b] = pair(base, change);
    for (const id of SCREENS) assert.ok(sig(draw(b, {}, id, { selected: 1, letter: true })) === sig(draw(a, {}, id, { selected: 1, letter: true })), id);
  }
});

test('the viewer\'s switches reach the rows: accent, Rounded Corners, Row Art, the settings\' own values', () => {
  for (const id of SCREENS) {
    assert.ok(sig(draw('modern', { accent: 'tidal' }, id)) !== sig(draw('modern', { accent: 'cobalt' }, id)), `${id}: accent`);
    assert.ok(sig(draw('minimal', { corners: 'square' }, id)) !== sig(draw('minimal', { corners: 'round' }, id)), `${id}: corners`);
  }
  assert.ok(sig(draw('classic-light', { ROWART: 'Off' }, 'list-albums')) !== sig(draw('classic-light', { ROWART: 'On' }, 'list-albums')), 'Row Art');
  const s = draw('minimal', { accent: 'tidal', home: 'full' }, 'settings', { selected: 7 });
  assert.ok(word(s, 'Accent: Tidal') && word(s, 'Home: Full'), 'Appearance shows the values chosen');
  assert.ok(word(draw('classic-light', { half: 'dark' }, 'settings'), 'Off'), 'Classic: Light Mode Off in the dark half');
});

// ---- real pixels against the reference pictures: only where the dev harness and the pictures are ----

const dir = fileURLToPath(new URL('./', import.meta.url));
const canvasAt = `${dir}node_modules/@napi-rs/canvas`;
const fonts = [`${dir}../../assets/fonts/LiberationSans-Bold.ttf`, `${dir}../../assets/fonts/texgyreheros-bold.otf`];
const refs = fileURLToPath(new URL('./reference/', import.meta.url));
const real = existsSync(canvasAt) && fonts.every((f) => existsSync(f)) && existsSync(`${refs}classic-light-list-albums.png`);

test('the 24 reference pictures of the list pages: what differs stays within antialiasing and the stand-ins', { skip: real ? false : 'needs @napi-rs/canvas and reference pictures in reference/, which hold stock art and are not in the repository' }, async () => {
  const { createCanvas, GlobalFonts, Path2D, loadImage } = require(canvasAt);
  const stub = globalThis.Path2D;
  globalThis.Path2D = Path2D;
  GlobalFonts.registerFromPath(fonts[0], 'Q2 Liberation Sans Bold');
  GlobalFonts.registerFromPath(fonts[1], 'Q2 TeX Gyre Heros Bold');
  Q2Draw.makeCanvas = (w, h) => createCanvas(w, h);
  Q2Draw.resetText();
  const W = 375;
  const H = 320;
  const far = (a, i, b, j) => Math.abs(a[i] - b[j]) > 48 || Math.abs(a[i + 1] - b[j + 1]) > 48 || Math.abs(a[i + 2] - b[j + 2]) > 48;
  const match = (a, b, x, y) => {
    for (let dy = -1; dy <= 1; dy += 1) {
      for (let dx = -1; dx <= 1; dx += 1) {
        const u = x + dx;
        const v = y + dy;
        if (u >= 0 && v >= 0 && u < W && v < H && !far(a, (y * W + x) * 4, b, (v * W + u) * 4)) return true;
      }
    }
    return false;
  };
  try {
    for (const [name, id] of [['minimal', 'minimal'], ['classic', 'classic-light'], ['modern', 'modern']]) {
      for (const half of ['dark', 'light']) {
        for (const screen of SCREENS) {
          const c = createCanvas(W, H);
          const g = c.getContext('2d');
          const env = Q2Draw.env(o, builtin(id), { half });
          Q2Draw.render(g, screen, env, {});
          const ours = g.getImageData(0, 0, W, H).data;
          const r = createCanvas(W, H).getContext('2d');
          r.drawImage(await loadImage(`${refs}${name}-${half}-${screen}.png`), 0, 0);
          const ref = r.getImageData(0, 0, W, H).data;
          // pixels with no match within a pixel either way, outside the thumb's columns (the reference
          // tool's scroll state is not a device's: DRAWING.md 13 item 3)
          let off = 0;
          let stray = 0;
          for (let y = env.bar; y < H; y += 1) {
            for (let x = 0; x < W; x += 1) {
              const i = (y * W + x) * 4;
              if (!far(ref, i, ours, i) || (match(ours, ref, x, y) && match(ref, ours, x, y))) continue;
              if (x >= 369 && x <= 372 && env.T('list.scrollbar.w')) continue;
              off += 1;
              // nothing may be off outside the rows' own columns: the glass's side margins stay paper
              if (x < 16 || (x > 356 && !(x >= 369 && x <= 372))) stray += 1;
            }
          }
          assert.ok((100 * off) / (W * H) < 1, `${name} ${half} ${screen}: ${((100 * off) / (W * H)).toFixed(2)} % off`);
          assert.equal(stray, 0, `${name} ${half} ${screen}: nothing off in the side margins`);
        }
      }
    }
  } finally {
    globalThis.Path2D = stub;
    Q2Draw.resetText();
  }
});
