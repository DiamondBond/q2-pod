// node --test draw_playing.test.mjs
// Now Playing, the volume and the confirm dialog against DRAWING.md sections 7, 8 and 9: the boxes, the
// colours and the forms, on a canvas that only writes down what is drawn on it; and that every schema key
// section 11 lists as shown on these screens changes what is drawn when a theme changes it. The last tests
// draw real pixels and run only where the dev harness's canvas is installed (npm install @napi-rs/canvas in this folder).
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import official from './official.js';
import Q2Draw from './draw_core.js';
import './draw_bar.js';
import './draw_playing.js';

const require = createRequire(import.meta.url);
const data = JSON.parse(readFileSync(new URL('./official.json', import.meta.url), 'utf8'));
const o = official.open(data);
const builtin = (id) => data.themes.find((b) => b.id === id).resolved;
const hex = (c) => Q2Draw.hex(c);
if (!globalThis.Path2D) globalThis.Path2D = class { constructor(d) { this.d = d; } };

// A canvas context that only writes down what is asked of it: every call with its arguments, every
// property as it is set. Text measures half its size a character, so layouts are whole numbers.
function recorder() {
  const log = [];
  const now = { fillStyle: '#000000', strokeStyle: '#000000', font: '10px sans-serif', globalAlpha: 1, lineWidth: 1 };
  const show = (v) => (v && v.stops ? { gradient: v.stops } : v && v.d !== undefined ? { path: v.d } : v);
  const own = {
    log,
    measureText: (s) => ({ width: s.length * parseFloat(/([0-9.]+)px/.exec(now.font)[1]) * 0.5 }),
    createLinearGradient: (...at) => ({ stops: [at], addColorStop(p, c) { this.stops.push([p, c]); } }),
  };
  return new Proxy(own, {
    get(t, name) {
      if (name in t) return t[name];
      if (name in now) return now[name];
      if (typeof name === 'symbol' || name === 'getTransform' || name === 'canvas') return undefined; // no transform: text is drawn straight
      return (...args) => { log.push([name, ...args.map(show)]); };
    },
    set(t, name, value) {
      now[name] = value;
      log.push(['=', name, show(value)]);
      return true;
    },
  });
}

// the style of the last rectangle filled over a pixel
function at(ctx, x, y) {
  let style = null;
  let seen = null;
  for (const e of ctx.log) {
    if (e[0] === '=' && e[1] === 'fillStyle') style = e[2];
    if (e[0] === 'fillRect' && x >= e[1] && x < e[1] + e[3] && y >= e[2] && y < e[2] + e[4]) seen = style;
  }
  return seen;
}
// every rectangle filled, as [x, y, w, h, style]
function rects(ctx) {
  const out = [];
  let style = null;
  for (const e of ctx.log) {
    if (e[0] === '=' && e[1] === 'fillStyle') style = e[2];
    if (e[0] === 'fillRect') out.push([e[1], e[2], e[3], e[4], style]);
  }
  return out;
}
const hasRect = (ctx, x, y, w, h, style) => rects(ctx).some((r) => r[0] === x && r[1] === y && r[2] === w && r[3] === h && (style === undefined || r[4] === style));
// the characters drawn, in order, with each one's place and colour
function glyphs(ctx) {
  const out = [];
  let style = null;
  let font = '';
  for (const e of ctx.log) {
    if (e[0] === '=' && e[1] === 'fillStyle') style = e[2];
    if (e[0] === '=' && e[1] === 'font') font = e[2];
    if (e[0] === 'fillText') out.push({ ch: e[1], x: e[2], y: e[3], style, font });
  }
  return out;
}
const written = (ctx) => glyphs(ctx).map((g) => g.ch).join('');
// where a text starts, and in what: the first place its characters are drawn in a row
function textAt(ctx, str) {
  const all = glyphs(ctx);
  const s = all.map((g) => g.ch).join('');
  const i = s.indexOf(str);
  return i < 0 ? null : all[i];
}
// the path fills: each [style, moveTo x, moveTo y] of a path that was filled
function pathFills(ctx) {
  const out = [];
  let style = null;
  let first = null;
  for (const e of ctx.log) {
    if (e[0] === '=' && e[1] === 'fillStyle') style = e[2];
    if (e[0] === 'beginPath') first = null;
    if (e[0] === 'moveTo' && !first) first = [e[1], e[2]];
    if (e[0] === 'fill' && first) out.push([style, ...first]);
  }
  return out;
}
// the circles filled: each [centre x, centre y, radius, style]
function circles(ctx) {
  const out = [];
  let style = null;
  let arc = null;
  for (const e of ctx.log) {
    if (e[0] === '=' && e[1] === 'fillStyle') style = e[2];
    if (e[0] === 'beginPath') arc = null;
    if (e[0] === 'arc') arc = [e[1], e[2], e[3]];
    if (e[0] === 'fill' && arc) out.push([...arc, style]);
  }
  return out;
}
const discs = (ctx) => circles(ctx).filter((c) => c[2] === 4).map((c) => [c[0], c[1]]);
// where a text is drawn, every time it is: [style, baseline] of its first character
function drawn(ctx, s) {
  const all = glyphs(ctx);
  return all.filter((g, i) => all.slice(i, i + s.length).map((x) => x.ch).join('') === s).map((g) => [g.style, g.y]);
}

const env = (theme, choices) => Q2Draw.env(o, typeof theme === 'string' ? builtin(theme) : theme, choices);
function draw(theme, choices, id, state) {
  const ctx = recorder();
  const e = env(theme, choices);
  Q2Draw.render(ctx, id, e, state);
  return Object.assign(ctx, { env: e });
}
// a theme of the user's own over a built-in, changed through official.js and resolved as the build would
function made(base, ...edits) {
  const t = o.newTheme({ extends: base, id: 'dusk', name: 'Dusk' });
  for (const edit of edits) if (edit) edit(t);
  assert.deepEqual(o.problems(t).map((p) => p.tool), [], 'the changed theme builds');
  return o.resolve(t);
}
const layout = (theme, choices, state, length) => Q2Draw.screens['now-playing'].layout(env(theme, choices), state, length);
const box = (b) => [b.x, b.y, b.w, b.h];

// ---- loading ----

test('a page loads the file with a script tag, and it adds its three screens', async () => {
  const { runInNewContext } = await import('node:vm');
  const window = {};
  Object.assign(window, { globalThis: window });
  for (const f of ['draw_core.js', 'draw_bar.js', 'draw_playing.js']) runInNewContext(readFileSync(new URL(`./${f}`, import.meta.url), 'utf8'), window);
  for (const id of ['now-playing', 'volume', 'confirm']) {
    const s = window.Q2Draw.screens[id];
    assert.equal(typeof s.draw, 'function', id);
    assert.ok(s.title && s.states.length && s.states.every((x) => x.id && x.label && x.state), `${id}: a title and named states`);
  }
});

test('the file holds no embedded picture, no eval and no stock art', () => {
  const text = readFileSync(new URL('./draw_playing.js', import.meta.url), 'utf8');
  assert.ok(!/data:image|base64|\beval\(|new Function|fetch\(|XMLHttpRequest|import\(/.test(text));
  assert.ok(!/fillText|\.font\s*=/.test(text), 'text goes through the core\'s helpers');
});

test('every named state draws in every built-in theme and half', () => {
  for (const b of data.themes) {
    for (const half of ['dark', 'light']) {
      for (const id of ['now-playing', 'volume', 'confirm']) {
        for (const s of Q2Draw.screens[id].states) {
          const ctx = draw(b.resolved, { half }, id, s.state);
          assert.ok(ctx.log.length > 20, `${b.id} ${half} ${id} ${s.id}`);
          assert.ok(!JSON.stringify(ctx.log).includes('undefined') && !JSON.stringify(ctx.log).includes('NaN'), `${b.id} ${half} ${id} ${s.id}: every colour and number is there`);
        }
      }
    }
  }
});

// ---- Now Playing: the boxes (7.2, 7.3, 7.4) ----

test('the iPod page of the stock set: the boxes of 7.2', () => {
  for (const id of ['minimal', 'modern']) {
    const L = layout(id, {}, {}, 245);
    assert.deepEqual([L.kind, L.gloss, L.beside], ['ipod', false, false]);
    assert.deepEqual(box(L.more), [303, 30, 50, 40]);
    assert.deepEqual(box(L.position), [22, 30, 281, 40]);
    assert.deepEqual(box(L.elapsed), [46, 295, 80, 16]);
    assert.deepEqual(box(L.remain), [249, 295, 80, 16]);
    assert.deepEqual(box(L.art), [16, 72, 166, 166]);
    assert.deepEqual(box(L.glyph), [39, 95, 120, 120]);
    assert.deepEqual(box(L.title), [194, 88, 165, 28]);
    assert.deepEqual(box(L.artist), [194, 122, 165, 22]);
    assert.deepEqual(box(L.album), [194, 150, 165, 22]);
    assert.deepEqual(box(L.mode), [247, 203, 50, 50]);
    assert.deepEqual(box(L.heart), [303, 203, 50, 50]);
    assert.deepEqual(box(L.dots), [0, 252, 375, 10]);
    assert.deepEqual(box(L.slider), [21, 263, 333, 44]);
  }
  assert.deepEqual(box(layout('minimal', {}, {}, 245).bar), [21, 283, 333, 4], '7.8: Minimal\'s line');
  assert.deepEqual(box(layout('modern', {}, {}, 245).bar), [21, 281, 333, 8], '7.8: Modern\'s capsule');
});

test('the iPod classic\'s page: the boxes of 7.3, the times and the bar fitted to the track', () => {
  const L = layout('classic-light', {}, {}, 245);
  assert.deepEqual([L.kind, L.gloss, L.beside], ['classic', true, true]);
  assert.deepEqual(box(L.art), [16, 48, 178, 218]);
  assert.deepEqual(box(L.glyph), [45, 77, 120, 120]);
  assert.deepEqual(box(L.title), [206, 64, 153, 28]);
  assert.deepEqual(box(L.artist), [206, 98, 153, 22]);
  assert.deepEqual(box(L.album), [206, 126, 153, 22]);
  assert.deepEqual(box(L.mode), [244, 191, 50, 50]);
  assert.deepEqual(box(L.heart), [300, 191, 50, 50]);
  assert.deepEqual(box(L.position), [208, 154, 151, 20]);
  assert.deepEqual(box(L.dots), [0, 248, 375, 10]);
  assert.deepEqual(box(L.elapsed), [23, 270, 35, 21]);
  assert.deepEqual(box(L.remain), [317, 270, 35, 21]);
  assert.deepEqual(box(L.bar), [66, 271, 243, 20]);
  assert.deepEqual(box(L.more), [300, 26, 50, 40]);
  for (const [length, tw, x, w, rx] of [[599, 35, 66, 243, 317], [600, 43, 74, 227, 309], [3599, 43, 74, 227, 309], [3600, 56, 87, 201, 296]]) {
    const F = layout('classic-light', {}, {}, length);
    assert.deepEqual([F.elapsed.w, F.bar.x, F.bar.w, F.remain.x, F.remain.w], [tw, x, w, rx, tw], `a track ${length} s long`);
    assert.deepEqual([F.elapsed.x, F.remain.x + F.remain.w], [23, 352], 'the outer edges stay');
  }
});

test('the Centred page: the boxes of 7.4, chosen by the setting, the theme or the viewer', () => {
  const L = layout('minimal', { np_layout: 'centred' }, {}, 245);
  assert.equal(L.kind, 'centred');
  assert.deepEqual(box(L.back), [3, 30, 85, 60]);
  assert.deepEqual(box(L.heart), [2, 162, 86, 73]);
  assert.deepEqual(box(L.more), [295, 30, 70, 60]);
  assert.deepEqual(box(L.mode), [287, 159, 86, 73]);
  assert.deepEqual(box(L.title), [10, 228, 355, 20]);
  assert.deepEqual(box(L.artist), [10, 254, 355, 16]);
  assert.deepEqual(box(L.elapsed), [52, 296, 48, 14]);
  assert.deepEqual(box(L.remain), [288, 296, 48, 14]);
  assert.deepEqual(box(L.art), [102, 38, 180, 180]);
  assert.deepEqual(box(L.glyph), [132, 68, 120, 120]);
  assert.deepEqual(box(L.dots), [80, 300, 225, 10]);
  assert.deepEqual(box(L.slider), [50, 263, 290, 44]);
  assert.deepEqual(box(L.bar), [50, 283, 290, 4]);
  assert.equal(layout('modern', {}, {}, 245).kind, 'ipod');
  assert.equal(layout('classic-light', { np_layout: 'centred' }, {}, 245).kind, 'classic', 'Classic does not offer the setting');
  assert.equal(layout(made('classic-light', (t) => o.set(t, 'playing.layout', 'centred')), {}, {}, 245).kind, 'centred', 'playing.layout');
  assert.equal(layout('classic-light', {}, { layout: 'centred' }, 245).kind, 'centred', 'the viewer\'s own switch');
  assert.equal(layout('minimal', { np_layout: 'centred' }, { layout: 'ipod' }, 245).kind, 'ipod');
});

test('a set with another bar height moves the whole page with it', () => {
  const tall = made('modern', (t) => { o.addGeometry(t, 'tall', null, { bar: 38 }); o.useGeometry(t, 'tall'); });
  const a = layout('modern', {}, {}, 245);
  const b = layout(tall, {}, {}, 245);
  for (const k of ['more', 'position', 'elapsed', 'remain', 'art', 'glyph', 'title', 'artist', 'album', 'mode', 'heart', 'dots', 'slider', 'bar']) {
    assert.deepEqual(box(b[k]), [a[k].x, a[k].y + 8, a[k].w, a[k].h], k);
  }
});

// ---- Now Playing: what is drawn ----

test('the texts and their colours (7.1, 7.2, 7.3, section 10)', () => {
  const grey = { 'minimal dark': '#8c8c8c', 'minimal light': '#7b7b7b', 'modern dark': '#aaaaaa', 'modern light': '#606060', 'classic-light dark': '#949294', 'classic-light light': '#6b6d6b' };
  for (const id of ['minimal', 'modern', 'classic-light']) {
    for (const half of ['dark', 'light']) {
      const ctx = draw(id, { half }, 'now-playing', {});
      const e = ctx.env;
      const all = written(ctx);
      for (const s of ['3 of 12', 'Evening Signal', 'The Reference Band', '1:23', '-2:42']) assert.ok(all.includes(s), `${id} ${half}: ${s}`);
      assert.equal(textAt(ctx, '3 of 12').style, grey[`${id} ${half}`], `${id} ${half}: "3 of 12"`);
      assert.equal(textAt(ctx, 'Evening Signal').style, hex(e.fg));
      assert.equal(textAt(ctx, 'The Reference Band').style, hex(e.INK(0xcccccc)));
      // the times: grey under the plain bar, the ink beside the gloss bar
      assert.equal(textAt(ctx, '-2:42').style, id === 'classic-light' ? hex(e.fg) : grey[`${id} ${half}`], `${id} ${half}: the times`);
      // a plain label draws from its box's edge: no 2 px margin (2.3)
      assert.equal(textAt(ctx, '3 of 12').x, id === 'classic-light' ? 208 : 22);
      assert.equal(textAt(ctx, 'Evening Signal').x, (id === 'classic-light' ? 206 : 194) + 2, 'a scrolling label keeps 2 px');
      // the album: Minimal's capitals from box.x + 2, the others' label
      if (id === 'minimal') {
        assert.ok(all.includes('DUSK ON THE RIDG') && !all.includes('Dusk on the Ridge'), 'capitals only: the label under them is hidden');
        assert.equal(textAt(ctx, 'DUSK').x, 196);
      } else assert.ok(all.includes('Dusk on the Ridge') && !all.includes('DUSK'));
      assert.equal(textAt(ctx, id === 'minimal' ? 'DUSK' : 'Dusk').style, hex(e.INK(0xbbbbbb)));
    }
  }
  // the title's face and size: the theme's role, else the page's 22 (20 on the Centred page)
  assert.match(textAt(draw('modern', {}, 'now-playing', {}), 'Evening').font, /^700 .*Liberation Sans Bold/);
  assert.match(textAt(draw('classic-light', {}, 'now-playing', {}), 'Evening').font, /^700 .*TeX Gyre Heros/);
  const size = (ctx) => parseFloat(/([0-9.]+)px/.exec(textAt(ctx, 'Evening').font)[1]);
  assert.ok(Math.abs(size(draw('minimal', {}, 'now-playing', {})) - (22 * 256) / 299) < 0.01);
  assert.ok(Math.abs(size(draw('minimal', { np_layout: 'centred' }, 'now-playing', {})) - (20 * 256) / 299) < 0.01);
  assert.ok(Math.abs(size(draw('classic-light', {}, 'now-playing', {})) - (27 * 1000) / 1432) < 0.01);
  // an hour and over reads H:MM:SS; the Centred page shows the length, not what is left
  assert.ok(written(draw('minimal', {}, 'now-playing', { elapsed: 3725, length: 5400 })).includes('1:02:05'));
  assert.ok(written(draw('minimal', {}, 'now-playing', { elapsed: 3725, length: 5400 })).includes('-27:55'));
  const centred = written(draw('modern', { np_layout: 'centred' }, 'now-playing', {}));
  assert.ok(centred.includes('4:05') && !centred.includes('-2:42') && !centred.includes('3 of 12') && !centred.includes('Dusk'), 'no position, no album, no time left');
});

test('the page dots (7.7, 7.4)', () => {
  for (const [id, y] of [['minimal', 252], ['modern', 252], ['classic-light', 248]]) {
    const ctx = draw(id, { half: 'dark' }, 'now-playing', {});
    assert.deepEqual(discs(ctx), [[163, y + 4], [179, y + 4], [195, y + 4], [211, y + 4]], `${id}: x 159..166, 175..182, 191..198, 207..214`);
    assert.deepEqual(circles(ctx).filter((c) => c[2] === 4).map((c) => c[3]), ['#eeeeee', '#555555', '#555555', '#555555']);
  }
  // the Centred page's: the first in stock red through the red mapping, the rest grey at alpha 100
  const dotsOf = (choices) => circles(draw('modern', Object.assign({ np_layout: 'centred' }, choices), 'now-playing', {})).filter((c) => c[2] === 4);
  const lit = (choices) => dotsOf(choices)[0][3];
  assert.deepEqual(dotsOf({}).map((c) => [c[0], c[1]]), [[168, 304], [184, 304], [200, 304], [216, 304]], 'centred across (80, 300, 225, 10)');
  assert.equal(lit({ half: 'dark', accent: 'cobalt' }), '#447cdd');
  assert.equal(lit({ half: 'dark', accent: 'crimson' }), '#ff1448', 'Crimson keeps stock red in the dark half');
  assert.equal(lit({ half: 'light', accent: 'crimson' }), '#eb2f56', 'and takes the light tone in the light half');
  assert.equal(lit({ half: 'light', accent: 'graphite' }), '#383838', 'a neutral accent: its red tone, flipped');
  assert.match(dotsOf({ half: 'dark' })[1][3], /^rgba\(102,102,102,0\.39/);
});

test('the plain bar (7.8): track, fill by 1.5\'s table, scrubbing', () => {
  // Minimal's line is square: both are rectangles
  const m = draw('minimal', { half: 'dark' }, 'now-playing', {});
  assert.ok(hasRect(m, 21, 283, 333, 4, '#1c1c1c'), 'the track');
  assert.ok(hasRect(m, 21, 283, Math.trunc((333 * 83) / 245), 4, '#6e6e6e'), 'the fill: w * elapsed / length');
  assert.ok(hasRect(draw('minimal', { half: 'light' }, 'now-playing', {}), 21, 283, 333, 4, '#dcdcdc'));
  const table = { graphite: ['#6e6e6e', '#383838'], crimson: ['#eb2f56', '#d23b5b'], tidal: ['#30929b', '#30929b'], champagne: ['#9a8446', '#9a8446'], cobalt: ['#447cdd', '#447cdd'],
    tangerine: ['#cb681e', '#cb681e'], plum: ['#9d4f7a', '#9d4f7a'], ivory: ['#eeeeec', '#252527'], green: ['#778e4c', '#778e4c'] };
  for (const [accent, [dark, light]] of Object.entries(table)) {
    assert.equal(at(draw('minimal', { half: 'dark', accent }, 'now-playing', {}), 30, 284), dark, `${accent} dark`);
    assert.equal(at(draw('minimal', { half: 'light', accent }, 'now-playing', {}), 30, 284), light, `${accent} light`);
    if (accent === 'ivory') continue; // Minimal's alone
    assert.ok(pathFills(draw('modern', { half: 'light', accent }, 'now-playing', {})).some((f) => f[0] === light && f[2] === 281), `Modern ${accent} light: a capsule from row 281`);
  }
  // scrubbing: a white fill, and Minimal's line at its scrub height, still centred on row 285
  const s = draw('minimal', { half: 'dark' }, 'now-playing', { scrubbing: true });
  assert.ok(hasRect(s, 21, 281, 333, 8, '#1c1c1c') && hasRect(s, 21, 281, 112, 8, '#ffffff'));
  assert.ok(hasRect(draw('minimal', { half: 'light' }, 'now-playing', { scrubbing: true }), 21, 281, 112, 8, '#161616'), 'white through INK');
  // nothing played: no fill; all of it: the whole bar
  assert.equal(at(draw('minimal', { half: 'dark' }, 'now-playing', { elapsed: 0 }), 22, 284), '#1c1c1c');
  assert.ok(hasRect(draw('minimal', { half: 'dark' }, 'now-playing', { elapsed: 999 }), 21, 283, 333, 4, '#6e6e6e'), 'elapsed never passes the length');
});

test('the gloss bar (7.9): Classic\'s rows, end columns, reflection and scrub mark', () => {
  const light = ['#e2e2e2', '#ffffff', '#ffffff', '#ffffff', '#ffffff', '#fdfdfd', '#fafafa', '#fafafa', '#f9f9f9', '#f7f7f7', '#f6f6f6', '#f6f6f6', '#f6f6f6', '#f5f5f5', '#f4f4f4', '#f4f4f4', '#f4f4f4', '#f4f4f4', '#f4f4f4', '#cecece'];
  const dark = ['#313131', '#373737', '#373737', '#373737', '#373737', '#363636', '#363636', '#353535', '#343434', '#323232', '#313131', '#313131', '#313131', '#323232', '#333333', '#343434', '#343434', '#343434', '#343434', '#2b2b2b'];
  const blue = ['#7d96d7', '#82a3f0', '#7fa5fc', '#729cf8', '#6e9bf5', '#6b9bf2', '#6b9df4', '#6ba1f7', '#68a2fb', '#5d9efb', '#438dee', '#3990f1', '#3599f8', '#32a1fd', '#34a9fe', '#38affd', '#3fb2fc', '#51b8fd', '#5bb1ed', '#5b9ecf'];
  const on = Math.trunc((243 * 83) / 245); // 82 columns played
  for (const [half, track, paper] of [['light', light, 0xffffff], ['dark', dark, 0x000000]]) {
    const ctx = draw('classic-light', { half }, 'now-playing', {});
    for (let j = 0; j < 20; j += 1) {
      assert.equal(at(ctx, 200, 271 + j), track[j], `${half} track row ${j}`);
      assert.equal(at(ctx, 100, 271 + j), blue[j], `${half} Classic Blue fill row ${j}`);
      assert.equal(at(ctx, 66, 271 + j), track[19], 'the left end column, over the fill');
      assert.equal(at(ctx, 308, 271 + j), track[19], 'the right end column');
    }
    assert.equal(at(ctx, 66 + on - 1, 280), blue[9]);
    assert.equal(at(ctx, 66 + on, 280), track[9], 'the fill ends after w * elapsed / length columns');
    [38, 31, 25, 19, 12, 6].forEach((a, k) => {
      assert.equal(at(ctx, 200, 291 + k), hex(Q2Draw.mix(paper, Q2Draw.col(track[19 - k]), a, 256)), `${half} reflection row ${k} of the track`);
      assert.equal(at(ctx, 100, 291 + k), hex(Q2Draw.mix(paper, Q2Draw.col(blue[19 - k]), a, 256)), `${half} reflection row ${k} of the fill`);
    });
    assert.equal(at(ctx, 200, 297), hex(paper), 'six rows and no more');
  }
  // another accent: its selection band over the 20 rows
  const tidal = draw('classic-light', { half: 'light', accent: 'tidal' }, 'now-playing', {});
  const rows = Q2Draw.stopsRows(tidal.env.S.sel, 20);
  for (let j = 0; j < 20; j += 1) assert.equal(at(tidal, 100, 271 + j), hex(rows[j]), `Tidal row ${j}`);
  assert.equal(hex(rows[0]), '#189392');
  // scrubbing: a diamond in the half's ink at the fill's end, 17 rows, kept inside the bar
  for (const [state, cx] of [[{ scrubbing: true }, on], [{ scrubbing: true, elapsed: 0 }, 8], [{ scrubbing: true, elapsed: 245 }, 243 - 9]]) {
    const ctx = draw('classic-light', { half: 'light' }, 'now-playing', state);
    for (let j = -8; j <= 8; j += 1) {
      const half = 8 - Math.abs(j);
      assert.ok(hasRect(ctx, 66 + cx - half, 280 + j, 2 * half + 1, 1, '#000000'), `row ${j} of the mark at column ${cx}`);
    }
  }
  assert.ok(hasRect(draw('classic-light', { half: 'dark' }, 'now-playing', { scrubbing: true }), 66 + on, 272, 1, 1, '#ffffff'), 'the dark half\'s ink');
  assert.ok(!hasRect(draw('classic-light', { half: 'light' }, 'now-playing', {}), 66 + on, 272, 1, 1), 'no mark while playing');
});

test('the art (7.5) and the glyph over it', () => {
  const clipArcs = (ctx) => ctx.log.filter((e) => e[0] === 'arcTo').map((e) => e[5]);
  // Minimal: rounded, radius min(w, h) * 12 / 166; Modern: square, rounded with Rounded Corners
  assert.ok(clipArcs(draw('minimal', {}, 'now-playing', {})).includes(12));
  assert.ok(!clipArcs(draw('modern', {}, 'now-playing', {})).includes(12));
  assert.ok(clipArcs(draw('modern', { corners: 'round' }, 'now-playing', {})).includes(12));
  assert.ok(clipArcs(draw('minimal', { np_layout: 'centred' }, 'now-playing', {})).includes(13), '13 at 180');
  // Classic: slanted. With no scratch canvas here, its outline: near edge y 48..226, far edge 178 * 224 / 256 high
  const c = draw('classic-light', {}, 'now-playing', {});
  const far = (178 * 224) / 256;
  const quad = c.log.filter((e) => e[0] === 'lineTo' && (e[1] === 16 || e[1] === 194)).map((e) => [e[1], e[2]]);
  assert.deepEqual(quad.slice(0, 3), [[194, 48 + (178 - far) / 2], [194, 48 + (178 + far) / 2], [16, 226]]);
  // the glyph over the art shows at playing.state.opacity: none in Minimal and Classic, whole in Modern
  const dim = (ctx) => ctx.log.some((e) => e[0] === '=' && e[1] === 'fillStyle' && /^rgba\(0,0,0,0\.50/.test(e[2]));
  assert.ok(!dim(draw('minimal', {}, 'now-playing', {})) && !dim(c));
  const modern = draw('modern', {}, 'now-playing', {});
  assert.ok(dim(modern));
  assert.deepEqual(modern.log.filter((e) => e[0] === 'arc' && e[3] === 60).map((e) => [e[1], e[2]]), [[99, 155]], 'a 120 px disc on the art\'s middle');
  // paused and playing draw different glyphs
  assert.notEqual(JSON.stringify(draw('modern', {}, 'now-playing', { play: 'paused' }).log.filter((e) => e[0] !== 'fillText')), JSON.stringify(modern.log.filter((e) => e[0] !== 'fillText')));
  // no cover: the placeholder plate
  assert.ok(pathFills(draw('minimal', {}, 'now-playing', { cover: null })).some((f) => f[0] === '#777777'));
});

// ---- the volume (section 8) ----

test('the volume over Now Playing with the plain bar (8.1)', () => {
  const m = draw('minimal', { half: 'dark' }, 'volume', { level: 40 });
  assert.ok(hasRect(m, 0, 263, 375, 48, '#000000'), 'the band, from the bar\'s box to the times\' foot');
  assert.ok(hasRect(m, 21, 283, 333, 4, '#1c1c1c'));
  assert.ok(hasRect(m, 21, 283, Math.trunc((333 * 40) / 100), 4, '#6e6e6e'));
  const text = textAt(m, 'Volume 40');
  assert.equal(text.style, '#ffffff');
  assert.ok(text.y > 295 && text.y < 311, 'in the times\' row');
  assert.ok(!written(m).includes('-2:42') || glyphs(m).findIndex((g) => g.ch === 'V') > written(m).indexOf('-2:42'), 'the band is laid over the times');
  assert.ok(hasRect(draw('minimal', { half: 'light' }, 'volume', {}), 0, 263, 375, 48, '#f4f4f4'));
  // a fill is never a sliver: at least as wide as the bar is high; none at 0
  assert.ok(hasRect(draw('minimal', {}, 'volume', { level: 1 }), 21, 283, 4, 4, '#6e6e6e'));
  assert.equal(at(draw('minimal', {}, 'volume', { level: 0 }), 22, 284), '#1c1c1c');
  // Crimson is the accent's light tone in both halves here, not the progress fill's mapped red (1.5)
  for (const half of ['dark', 'light']) assert.equal(at(draw('minimal', { half, accent: 'crimson' }, 'volume', {}), 30, 284), '#eb2f56', half);
  assert.equal(at(draw('minimal', { half: 'light', accent: 'ivory' }, 'volume', {}), 30, 284), '#252527', 'a card scheme: its fill');
  // the Centred page: the band is 47 high and the text sits in its times' row
  const c = draw('modern', { half: 'dark', np_layout: 'centred' }, 'volume', { level: 40 });
  assert.ok(hasRect(c, 0, 263, 375, 47, '#000000'));
  assert.ok(pathFills(c).some((f) => f[0] === '#447cdd' && f[2] === 281), 'Modern\'s capsule in the accent');
  // the payload's text takes Classic's face only under list.row.font classic-light
  assert.match(textAt(m, 'Volume').font, /^400 /);
  assert.match(textAt(draw(made('minimal', (t) => o.set(t, 'list.row.font', 'classic-light')), {}, 'volume', {}), 'Volume').font, /TeX Gyre Heros/);
  assert.ok(written(draw('minimal', {}, 'volume', { level: 250, max: 100 })).includes('Volume 100'), 'a level past the most is the most');
});

test('the volume over Now Playing with the times beside the bar (8.2)', () => {
  for (const half of ['light', 'dark']) {
    const ctx = draw('classic-light', { half }, 'volume', { level: 40 });
    const paper = half === 'light' ? '#ffffff' : '#000000';
    assert.ok(hasRect(ctx, 23, 270, 35, 21, paper) && hasRect(ctx, 317, 270, 35, 21, paper), 'both time boxes papered');
    assert.equal(discs(ctx).length, 0, 'the page dots are hidden');
    const pct = textAt(ctx, '40%');
    assert.equal(pct.style, half === 'light' ? '#000000' : '#ffffff');
    assert.ok(pct.y > 241 && pct.y < 265, 'in (0, 241, 375, 24)');
    assert.match(pct.font, /TeX Gyre Heros/);
    // the gloss bar with on = w * level / max, no mark
    const on = Math.trunc((243 * 40) / 100);
    assert.equal(at(ctx, 66 + on - 1, 280), '#5d9efb');
    assert.notEqual(at(ctx, 66 + on, 280), '#5d9efb');
    // the two speakers: clipped to (58 - 8, 274, 8, 13) and (317, 274, 18, 13)
    const clips = ctx.log.filter((e) => e[0] === 'rect').map((e) => e.slice(1));
    assert.ok(clips.some((r) => r.join() === '50,274,8,13') && clips.some((r) => r.join() === '317,274,18,13'));
  }
  assert.ok(written(draw('classic-light', {}, 'volume', { level: 33, max: 66 })).includes('50%'), 'N = 100 * level / max');
  assert.ok(discs(draw('classic-light', {}, 'now-playing', {})).length === 4, 'and the dots are there without the volume');
});

test('the volume over another page (8.3): stock\'s panel and the classic-light panel', () => {
  // Modern's panel is flat at 6ceb519a: stock's is tried on a theme over it that states stock
  const stockModern = () => made('modern', (t) => o.set(t, 'volume.panel.painter', 'stock'));
  for (const id of ['minimal', stockModern()]) {
    const ctx = draw(id, { half: 'dark' }, 'volume', { level: 40, over: 'home' });
    const fills = pathFills(ctx);
    assert.ok(fills.some((f) => /^rgba\(43,43,43,0\.85/.test(f[0]) && f[1] === 38 && f[2] === 256), 'the panel (26, 256, 323, 48), radius 12, at alpha 217');
    assert.ok(fills.some((f) => f[0] === '#5a5a5a' && f[1] === 51 && f[2] === 275), 'the track (46, 275, 231, 10), radius 5');
    assert.ok(fills.some((f) => f[0] === '#ffffff' && f[1] === 51 && f[2] === 275), 'the fill');
    const n = textAt(ctx, '40');
    assert.ok(n.x >= 277 && n.x < 329 && n.y > 256 && n.y < 304 && n.style === '#ffffff', 'the number in (277, 256, 52, 48)');
    assert.ok(!written(ctx).includes('Volume'));
    assert.ok(!pathFills(draw(id, {}, 'volume', { level: 0, over: 'home' })).some((f) => f[0] === '#ffffff' && f[1] === 51), 'no fill at 0');
  }
  assert.ok(pathFills(draw(stockModern(), { half: 'light' }, 'volume', { over: 'home' })).some((f) => /^rgba\(207,207,207,/.test(f[0])), 'the panel through INK');
  for (const half of ['light', 'dark']) {
    const ctx = draw('classic-light', { half }, 'volume', { level: 40, over: 'home' });
    const e = ctx.env;
    const track = e.T(`playing.scrubber.${half}_track`);
    const fill = e.T(`playing.scrubber.${half}_fill`);
    const css = (v) => Q2Draw.css(Q2Draw.argb(v).colour, Q2Draw.argb(v).alpha);
    for (let j = 0; j < 17; j += 1) {
      assert.equal(at(ctx, 250, 271 + j), css(track[j]), `${half} track row ${j}`);
      assert.equal(at(ctx, 100, 271 + j), css(fill[j]), `${half} fill row ${j}`);
    }
    assert.ok(hasRect(ctx, 68, 271, 243, 1) && hasRect(ctx, 68, 271, 97, 1), 'the bar (68, 271, 243, 17), 243 * level / max filled');
    assert.equal(at(ctx, 100, 288), at(ctx, 250, 288), 'seventeen rows and no more');
    const stops = Q2Draw.stopsRows(e.S.bar, 48);
    for (const j of [0, 10, 47]) assert.ok(hasRect(ctx, 28, 256 + j, 319, 1, hex(stops[j])), `the panel's gloss, row ${j}`);
    assert.ok(pathFills(ctx).some((f) => f[0] === hex(e.S.bar_line) && f[1] === 27 + 13 && f[2] === 255), 'its ring (27, 255, 321, 50), radius 13, in scheme.bar.line');
    assert.ok(ctx.log.some((e2) => e2[0] === '=' && e2[2] === (half === 'light' ? '#393c39' : '#c6c3c6')), 'the speakers\' ink');
    assert.ok(!written(ctx).includes('40'), 'no number');
    // another accent fills with its selection band over 17 rows
    const plum = draw('classic-light', { half, accent: 'plum' }, 'volume', { level: 40, over: 'home' });
    const band = Q2Draw.stopsRows(plum.env.S.sel, 17);
    for (let j = 0; j < 17; j += 1) assert.equal(at(plum, 100, 271 + j), hex(band[j]), `${half} Plum row ${j}`);
  }
});

// ---- the confirm (section 9) ----

test('the stock confirm (9.1)', () => {
  const m = draw('minimal', { half: 'dark' }, 'confirm', {});
  assert.ok(hasRect(m, 0, 0, 375, 320, '#000000'), 'its own full-screen paper');
  assert.deepEqual(written(m), 'Shut Down?CancelOK');
  const prompt = textAt(m, 'Shut');
  assert.ok(prompt.y > 92 && prompt.y < 116 + 8 && prompt.style === '#ffffff', 'centred in (0, 0, 375, 208)');
  assert.ok(textAt(m, 'Cancel').y > 208 && textAt(m, 'Cancel').y < 256 && textAt(m, 'OK').y > 256 && textAt(m, 'OK').y < 304);
  // Minimal's card: a capsule inset 6 with Rounded Corners on, the whole row with it off
  assert.ok(pathFills(m).some((f) => f[0] === '#424242' && f[1] === 6 + 24 && f[2] === 208), '(6, 208, 363, 48) radius 24');
  assert.ok(pathFills(draw('minimal', { half: 'dark' }, 'confirm', { selected: 1 })).some((f) => f[0] === '#424242' && f[2] === 256), 'OK\'s row');
  assert.ok(hasRect(draw('minimal', { half: 'dark', corners: 'square' }, 'confirm', {}), 0, 208, 375, 48, '#424242'));
  assert.ok(hasRect(draw('minimal', { half: 'light', corners: 'square' }, 'confirm', {}), 0, 208, 375, 48, '#bbbbbb'));
  // Modern's bar: the accent's rows, square; the selected row's text by 1.8
  // Modern's confirm is flat at 6ceb519a: stock's is tried on a theme over it that states stock
  const mod = draw(made('modern', stockConfirm), { half: 'light' }, 'confirm', {});
  assert.equal(at(mod, 100, 230), '#2a6ad8');
  assert.equal(at(mod, 100, 208), '#447cdd', 'the bar\'s first row is the highlight');
  assert.equal(textAt(mod, 'Cancel').style, '#ffffff', 'white on a coloured accent in the light half');
  assert.equal(textAt(mod, 'OK').style, '#161616');
  assert.equal(textAt(draw(made('modern', stockConfirm), { half: 'light', accent: 'graphite' }, 'confirm', {}), 'Cancel').style, '#161616');
  assert.equal(textAt(draw('minimal', { half: 'dark', accent: 'ivory' }, 'confirm', {}), 'Cancel').style, '#171717', 'on Ivory\'s card');
  // Delete File: the prompt's box ends at the check box
  const del = draw('minimal', { half: 'dark' }, 'confirm', { check: true, prompt: 'Delete?' });
  assert.ok(textAt(del, 'Delete?').y < 80 && written(del).includes('Also delete source file'));
});

test('the classic-light confirm, page form (9.2)', () => {
  const LIGHT = ['#7389a5', '#7b90a9', '#8094ac', '#8598af', '#8a9cb2', '#8fa0b5', '#94a4b9', '#98a8bc', '#9dacbf', '#a2b0c1', '#a5b2c3', '#a8b5c5', '#aab7c7', '#adb9c9', '#b0bccb', '#b3becd', '#b5c0ce',
    '#b7c1cf', '#b8c2d0', '#b9c3d1', '#bbc4d2', '#bcc5d3', '#bec7d4', '#bfc8d4', '#bfc8d4', '#c0c8d5', '#c0c8d5', '#bfc8d5', '#bfc7d4', '#bec7d4'];
  for (const half of ['light', 'dark']) {
    for (const selected of [0, 1]) {
      const ctx = draw('classic-light', { half }, 'confirm', { selected });
      const e = ctx.env;
      // the cells: 30 high, max(76, text + 36) wide at 23 px, the pair centred
      const widths = ['Cancel', 'OK'].map((s) => Math.max(76, Math.floor(e.measure(ctx, s, 'classic-light', 23) + 36.5)));
      const x0 = Math.trunc((375 - widths[0] - widths[1]) / 2);
      const cells = [[x0, widths[0]], [x0 + widths[0], widths[1]]];
      assert.ok(hasRect(ctx, 0, 26, 375, 294, half === 'light' ? '#ffffff' : '#000000'), 'the paper under the bar');
      assert.ok(written(ctx).includes('Now Playing'), 'the status bar as usual, naming the page under the dialog');
      const prompt = textAt(ctx, 'Shut Down?');
      assert.ok(prompt.y > 61 && prompt.y < 91 && prompt.style === (half === 'light' ? '#000000' : '#ffffff'), 'the prompt in (24, 61, 327, 30), in the ink');
      assert.match(prompt.font, /TeX Gyre Heros/);
      // the track under the cell not chosen
      if (half === 'light') for (let i = 0; i < 30; i += 1) assert.equal(rects(ctx).find((r) => r[1] === 258 + i && r[0] === x0 && r[2] === widths[0] + widths[1])[4], LIGHT[i], `light track row ${i}`);
      else assert.ok(hasRect(ctx, x0, 258, widths[0] + widths[1], 1, '#14171c') && hasRect(ctx, x0, 287, widths[0] + widths[1], 1, '#191c21'), 'dark track from its stops');
      // the chosen cell: the accent's band over its 30 rows, a light top row and a dark foot
      const [cx, cw] = cells[selected];
      const band = Q2Draw.stopsRows(e.S.sel, 30);
      for (const i of [0, 7, 29]) assert.ok(hasRect(ctx, cx, 258 + i, cw, 1, hex(band[i])), `the lit cell's row ${i}`);
      assert.ok(hasRect(ctx, cx, 258, cw, 1, 'rgba(255,255,255,0.45098039215686275)') && hasRect(ctx, cx, 287, cw, 1, 'rgba(0,0,0,0.34901960784313724)'));
      // a shade right of Cancel when it is the one chosen
      assert.equal(hasRect(ctx, cx + cw, 258, 1, 1, `rgba(0,0,0,${47 / 255})`), selected === 0, '0x36 * 7 / 8 on its first column, first row');
      // the texts: a shadow a row up at alpha 0x4d, then white, or #cfd6dc in the dark half's other cell
      for (const [k, s] of [[0, 'Cancel'], [1, 'OK']]) {
        const [shadow, face] = drawn(ctx, s);
        assert.equal(shadow[0], `rgba(0,0,0,${0x4d / 255})`);
        assert.equal(face[1] - shadow[1], 1);
        assert.equal(face[0], half === 'light' || k === selected ? '#ffffff' : '#cfd6dc', `${half} ${s}`);
      }
    }
  }
  // a prompt wider than 327 px breaks at the last space that fits, the rest a line lower
  const long = draw('classic-light', { half: 'light' }, 'confirm', { prompt: 'Delete this file from the library, for good?' });
  const first = textAt(long, 'Delete this');
  const second = glyphs(long).find((g) => g.y > first.y + 20 && g.y < first.y + 40);
  assert.ok(second && second.y - first.y === 30, 'lines 30 px apart');
  // Delete File's box: the painter's own ring and tick under settings.values.text
  const tick = draw('classic-light', { half: 'light' }, 'confirm', { check: true, prompt: 'Delete?' });
  const none = draw('classic-light', { half: 'light' }, 'confirm', { check: false, prompt: 'Delete?' });
  const rows = (ctx) => rects(ctx).filter((r) => r[3] === 1 && r[2] <= 3 && r[1] >= 140 && r[1] < 148 && r[4] === '#000000').length;
  assert.equal(rows(tick), 11, 'the tick\'s eleven lines');
  assert.equal(rows(none), 0);
});

test('the classic-light confirm, tray form (9.2)', () => {
  for (const half of ['light', 'dark']) {
    const ctx = draw('classic-light', { half }, 'confirm', { form: 'tray', selected: 1 });
    const all = written(ctx);
    assert.ok(all.includes('Evening Signal'), 'the page under it stays');
    assert.ok(all.includes('Cancel') && all.includes('Delete') && !all.includes('Shut Down?'), 'no prompt; the second cell reads the verb');
    const tray = Q2Draw.stopsRows([[0, 0x6a707a], [8, 0x565c66], [20, 0x464b54], [34, 0x343840], [44, 0x22252c], [49, 0x121419], [92, 0x111216], [100, 0x1b1f26]], 52);
    for (const j of [0, 20, 51]) assert.ok(hasRect(ctx, 38, 254 + j, 299, 1, hex(tray[j])), `the tray's row ${j}`);
    const cells = rects(ctx).filter((r) => r[1] === 265 && r[3] === 1);
    assert.ok(cells.length >= 2, 'the cells sit at y 265');
    for (const s of ['Cancel', 'Delete']) {
      const [shadow, face] = drawn(ctx, s);
      assert.deepEqual([shadow[0], face[0], face[1] - shadow[1]], [`rgba(0,0,0,${0x4d / 255})`, '#ffffff', 1], `${half} ${s}: white in both cells in both halves`);
      assert.ok(face[1] > 265 && face[1] < 295);
    }
  }
  // the stock painter has one form: asking for the tray changes nothing
  assert.equal(JSON.stringify(draw('minimal', {}, 'confirm', { form: 'tray' }).log), JSON.stringify(draw('minimal', {}, 'confirm', {}).log));
});

// ---- the flat look: DRAWING.md section 15 ----

// the path data filled or stroked after each translate: [op, x, y, d, style]
function paths(ctx) {
  const out = [];
  let fill = null;
  let stroke = null;
  let at = [0, 0];
  for (const e of ctx.log) {
    if (e[0] === '=' && e[1] === 'fillStyle') fill = e[2];
    if (e[0] === '=' && e[1] === 'strokeStyle') stroke = e[2];
    if (e[0] === 'translate') at = [e[1], e[2]];
    if (e[0] === 'restore') at = [0, 0];
    if ((e[0] === 'fill' || e[0] === 'stroke') && e[1] && e[1].path) out.push([e[0], at[0], at[1], e[1].path, e[0] === 'fill' ? fill : stroke]);
  }
  return out;
}

test('Now Playing\'s flat marks (15.4): 32 px glyphs centred on stock\'s boxes, in the half\'s flat ink', () => {
  const dots = (ctx) => { // the discs r 2.6: an arc filled as the current path (a path's own fill after it is not one)
    const out = [];
    let style = null;
    let arc = null;
    for (const e of ctx.log) {
      if (e[0] === '=' && e[1] === 'fillStyle') style = e[2];
      if (e[0] === 'beginPath') arc = null;
      if (e[0] === 'arc') arc = e.slice(1, 4);
      if (e[0] === 'fill' && e.length === 1 && arc && arc[2] === 2.6) out.push([arc[0], arc[1], style]);
    }
    return out;
  };
  // More: three discs r 2.6 about (16, 16) of the 32 px image at (312, 34) on Modern's page, (309, 30) on Classic Modern's
  assert.deepEqual(dots(draw('modern', { half: 'dark' }, 'now-playing', {})), [[319, 50, '#ffffff'], [328, 50, '#ffffff'], [337, 50, '#ffffff']]);
  assert.deepEqual(dots(draw('modern', { half: 'light' }, 'now-playing', {})).map((d) => d[2]), ['#1c1c1e', '#1c1c1e', '#1c1c1e']);
  assert.deepEqual(dots(draw('classic-modern', { half: 'light' }, 'now-playing', {})), [[316, 46, '#1c1c1e'], [325, 46, '#1c1c1e'], [334, 46, '#1c1c1e']]);
  assert.deepEqual(dots(draw('modern', { half: 'dark' }, 'now-playing', { layout: 'centred' })).map((d) => d.slice(0, 2)), [[321, 60], [330, 60], [339, 60]], 'Centred: (314, 44)');
  // the play mode at (256, 212) and the heart at (312, 212) on Modern's; (253, 200) and (309, 200) on Classic Modern's
  const modes = { order: 'M-12 -6H9', random: 'M-12 -6H-7L5 6H9', cycle: 'M-11 -1V-2.5A3.5', cycle1: 'M-0.3 -3.4H1.5' };
  for (const [mode, d] of Object.entries(modes)) {
    const ctx = draw('modern', { half: 'dark' }, 'now-playing', { mode });
    assert.ok(paths(ctx).some((p) => p[1] === 256 + 16 && p[2] === 212 + 16 && p[3].startsWith(d) && p[4] === '#ffffff'), `${mode}`);
  }
  const heart = (theme, favourite) => paths(draw(theme, { half: 'light' }, 'now-playing', { favourite })).filter((p) => p[3].startsWith('M16 28C6 20'));
  assert.deepEqual(heart('modern', false).map((p) => [p[0], p[4]]), [['stroke', '#1c1c1e']], 'off: the outline alone');
  const placed = (theme, x, y) => { const log = draw(theme, { half: 'light' }, 'now-playing', {}).log; const i = log.findIndex((e) => e[0] === 'translate' && e[1] === x && e[2] === y); return i >= 0 && log[i + 1][0] === 'scale' && log[i + 1][1] === 0.8; };
  assert.ok(placed('modern', 328, 228), 'the heart about (16, 16) of (312, 212), at 0.8');
  assert.deepEqual(heart('classic-modern', true).map((p) => p[0]), ['fill', 'stroke'], 'on: filled too');
  assert.ok(placed('classic-modern', 325, 216), 'Classic Modern\'s at (309, 200)');
  // stock's stand-ins stay for Minimal and Classic
  for (const id of ['minimal', 'classic-light']) {
    const ctx = draw(id, { half: 'dark' }, 'now-playing', {});
    assert.equal(dots(ctx).length, 0, id);
    assert.ok(!paths(ctx).some((p) => p[3].startsWith('M16 28C6 20') || p[3].startsWith('M-12')), id);
  }
  // without art_final the flat images turn with the half (3.7)
  const unfinal = made('modern', (t) => o.set(t, 'pages.own.art_final', 0));
  const e = env('modern', { half: 'light' });
  assert.deepEqual(dots(draw(unfinal, { half: 'light' }, 'now-playing', {})).map((d) => d[2]), Array(3).fill(hex(e.INK(0x1c1c1e))));
});

test('the flat volume panel (15.7): over another page, the same in both halves and accents, no number', () => {
  for (const id of ['modern', 'classic-modern']) {
    for (const half of ['dark', 'light']) {
      const ctx = draw(id, { half, accent: 'crimson' }, 'volume', { level: 40, over: 'home' });
      const fills = pathFills(ctx);
      assert.ok(fills.some((f) => /^rgba\(43,43,43,0\.93/.test(f[0]) && f[1] === 28 + 12 && f[2] === 256), `${id} ${half}: the panel (28, 256, 319, 48) r 12 at 0xee`);
      assert.ok(fills.some((f) => f[0] === '#6b6b6b' && f[1] === 70 && f[2] === 278), 'the track (68, 278, 227, 4) r 2');
      assert.ok(fills.some((f) => f[0] === '#ffffff' && f[1] === 70 && f[2] === 278), 'the fill');
      const ps = paths(ctx).filter((p) => p[3].startsWith('M0 4.5h3.5'));
      assert.deepEqual(ps.map((p) => p.slice(1, 3).concat(p[4])), [[44, 273, '#ffffff'], [309, 273, '#ffffff']], 'white speakers at (44, 273) and (309, 273)');
      assert.ok(!/40|Volume/.test(written(ctx).replace(/9:41/, '')), 'no number');
    }
  }
  // the fill's width: 227 * level / max, at least 4 when not 0, none when that width is 0 (volume.c tests on.w)
  const width = (level, max = 100) => {
    const ctx = draw('modern', {}, 'volume', { level, max, over: 'home' });
    const i = ctx.log.findIndex((e) => e[0] === '=' && e[1] === 'fillStyle' && e[2] === '#ffffff' && ctx.log.slice(ctx.log.indexOf(e)).some((x) => x[0] === 'moveTo' && x[1] === 70 && x[2] === 278));
    if (i < 0) return 0;
    const line = ctx.log.slice(i).find((x) => x[0] === 'lineTo' && x[2] === 278);
    return line[1] + 2 - 68;
  };
  assert.deepEqual([width(1), width(50), width(100), width(40, 80), width(0), width(1, 300)], [4, 113, 227, 113, 0, 0]);
  // over Now Playing the flat themes keep 8.1 (Modern) and 8.2 (Classic Modern)
  assert.ok(written(draw('modern', {}, 'volume', { level: 40 })).includes('Volume 40'));
  assert.ok(written(draw('classic-modern', {}, 'volume', { level: 40 })).includes('40%'));
});

test('the flat confirm (15.5): two capsules, the lit one in what is on, page and tray forms', () => {
  const cellsOf = (ctx, y) => pathFills(ctx).filter((f) => f[2] === y).map((f) => [f[0], f[1] - 18]);
  for (const [id, half, paper, other, prompt, face, on] of [
    ['modern', 'dark', '#000000', '#ffffff', '#ffffff', 'Arial', '#2a6ad8'],
    ['modern', 'light', '#f4f4f4', '#1c1c1e', '#161616', 'Arial', '#2a6ad8'],
    ['classic-modern', 'dark', '#000000', '#ffffff', '#ffffff', 'TeX Gyre Heros', '#207cde'],
    ['classic-modern', 'light', '#ffffff', '#1c1c1e', '#000000', 'TeX Gyre Heros', '#207cde'],
  ]) {
    const ctx = draw(id, { half }, 'confirm', { selected: 0 });
    const e = ctx.env;
    const f = (s) => e.canvasFace(21, s);
    const widths = ['Cancel', 'OK'].map((s) => Math.max(76, Math.floor(e.measure(ctx, s, f(s).face, f(s).px) + 36.5)));
    const x0 = Math.trunc((375 - widths[0] - widths[1] - 8) / 2);
    assert.ok(hasRect(ctx, 0, e.bar, 375, 320 - e.bar, paper), `${id} ${half}: the flat page's ground under the bar`);
    const rest = half === 'light' ? '#e9e9ec' : '#2c2c2e';
    assert.deepEqual(cellsOf(ctx, 250), [[rest, x0], [rest, x0 + widths[0] + 8], [on, x0]], 'both at rest, then Cancel lit, 36 high from y 250');
    assert.equal(textAt(ctx, 'Cancel').style, '#ffffff');
    assert.equal(textAt(ctx, 'OK').style, other);
    assert.match(textAt(ctx, 'OK').font, new RegExp(face));
    const p = textAt(ctx, 'Shut Down?');
    assert.ok(p.y > 61 && p.y < 91 && p.style === prompt, `${id} ${half}: the prompt in (24, 61, 327, 30)`);
    assert.match(p.font, new RegExp(face));
  }
  // what is on: the accent's red tone over Classic's pages, Graphite's silver bright: its word in the ink
  const graphite = draw('classic-modern', { half: 'dark', accent: 'graphite' }, 'confirm', {});
  assert.equal(cellsOf(graphite, 250)[2][0], '#d8d8d8');
  assert.equal(textAt(graphite, 'Cancel').style, '#1c1c1e');
  assert.equal(cellsOf(draw('classic-modern', { half: 'light', accent: 'crimson' }, 'confirm', {}), 250)[2][0], '#ff1448');
  assert.equal(cellsOf(draw('modern', { half: 'light', accent: 'graphite' }, 'confirm', {}), 250)[2][0], '#383838');
  // the tray: over the page that raised it, a dark tray, cells at y 258 at rest in #48484a, every word white
  for (const half of ['dark', 'light']) {
    const tray = draw('modern', { half }, 'confirm', { form: 'tray', selected: 1, verb: 'Delete' });
    assert.ok(written(tray).includes('Evening Signal'), 'the page under it stays');
    assert.ok(pathFills(tray).some((f) => /^rgba\(43,43,43,0\.93/.test(f[0]) && f[1] === 38 + 12 && f[2] === 248), 'the tray (38, 248, 299, 56) r 12');
    assert.deepEqual(cellsOf(tray, 258).map((c) => c[0]), ['#48484a', '#48484a', '#2a6ad8']);
    assert.deepEqual(['Cancel', 'Delete'].map((s) => textAt(tray, s).style), ['#ffffff', '#ffffff']);
    assert.ok(!written(tray).includes('Shut Down?'));
  }
  // classic-light+flat draws as flat; the dialog painter's flat bit wins over Classic's
  assert.ok(env('classic-modern').flatDialogs && env('modern').flatDialogs && !env('classic-light').flatDialogs);
  // state.page: the bar over the page form as the page under the dialog names it
  assert.ok(written(draw('classic-modern', {}, 'confirm', { over: 'home' })).includes('Q2 Pod'));
  assert.ok(!written(draw('classic-modern', {}, 'confirm', { over: 'home', page: { title: '', home: false } })).includes('Q2 Pod'));
});

// ---- every schema key section 11 lists as shown on these screens ----

// [key, the built-in the theme starts from, what is the same before and after, the change, env choices,
//  the screen, its state]
const stops = (a, b) => [[0, a], [100, b]];
const rowsOf = (id, key) => builtin(id)[data.schema.find((k) => k.path === key).field];
const bumped = (id, key) => rowsOf(id, key).map((v, i) => (i === 3 ? ((v & 0xff000000) | 0x123456) >>> 0 : v));
const stockConfirm = (t) => o.set(t, 'dialog.confirm.painter', 'stock');
const band = (t) => { o.set(t, 'list.selection.painter', 'stops'); o.setScheme(t, null, 'sel.stops', stops(0x406080, 0x203040)); };
// a scheme with a mode of its own has no Light Mode row, and a theme with other rows runs on a set of its own
const ownSet = (t) => { o.addGeometry(t, 'own', null, {}); o.useGeometry(t, 'own'); o.removeOption(t, 'light'); };
const SHOWN = [
  ['geometry.set', 'modern', null, (t) => { o.addGeometry(t, 'tall', null, { bar: 36 }); o.useGeometry(t, 'tall'); }, {}, 'now-playing', {}],
  ['geometry.set', 'modern', null, (t) => { o.addGeometry(t, 'tall', null, { bar: 36 }); o.useGeometry(t, 'tall'); }, {}, 'volume', {}],
  ['list.selection.painter', 'minimal', null, (t) => o.set(t, 'list.selection.painter', 'bar'), {}, 'confirm', {}],
  ['list.row.font', 'minimal', null, (t) => o.set(t, 'list.row.font', 'classic-light'), {}, 'volume', {}],
  ['list.row.font', 'minimal', null, (t) => o.set(t, 'list.row.font', 'classic-light'), {}, 'volume', { over: 'home' }],
  ['list.row.font', 'classic-light', null, (t) => o.set(t, 'list.row.font', 'regular'), {}, 'confirm', {}],
  ['settings.values.text', 'classic-light', null, (t) => o.set(t, 'settings.values.text', 0), {}, 'confirm', { check: true }],
  ['playing.layout', 'minimal', null, (t) => o.set(t, 'playing.layout', 'centred'), {}, 'now-playing', {}],
  ['playing.layout', 'minimal', null, (t) => o.set(t, 'playing.layout', 'centred'), {}, 'volume', {}],
  ['playing.title.font', 'minimal', null, (t) => o.set(t, 'playing.title.font', 'bold'), {}, 'now-playing', {}],
  ['playing.title.font_px', 'minimal', null, (t) => o.set(t, 'playing.title.font_px', 26), {}, 'now-playing', {}],
  ['playing.album.caps', 'minimal', null, (t) => o.set(t, 'playing.album.caps', 0), {}, 'now-playing', {}],
  ['playing.album.opacity', 'modern', null, (t) => o.set(t, 'playing.album.opacity', 100), {}, 'now-playing', {}],
  ['playing.album.opacity', 'minimal', null, (t) => o.set(t, 'playing.album.opacity', 255), {}, 'now-playing', {}],
  ['playing.state.opacity', 'minimal', null, (t) => o.set(t, 'playing.state.opacity', 255), {}, 'now-playing', {}],
  ['playing.state.opacity', 'modern', null, (t) => o.set(t, 'playing.state.opacity', 90), { np_layout: 'centred' }, 'now-playing', {}],
  ['playing.art.square', 'minimal', null, (t) => o.set(t, 'playing.art.square', 1), { corners: 'square' }, 'now-playing', {}],
  ['playing.scrubber.height', 'modern', null, (t) => o.set(t, 'playing.scrubber.height', 12), {}, 'now-playing', {}],
  ['playing.scrubber.height', 'modern', null, (t) => o.set(t, 'playing.scrubber.height', 12), {}, 'volume', {}],
  ['playing.scrubber.scrub_height', 'minimal', null, (t) => o.set(t, 'playing.scrubber.scrub_height', 12), {}, 'now-playing', { scrubbing: true }],
  ['playing.scrubber.stops', 'classic-light', null, (t) => o.set(t, 'playing.scrubber.stops', stops(0x402010, 0x201008)), { half: 'dark' }, 'now-playing', {}],
  ['playing.scrubber.stops', 'classic-light', null, (t) => o.set(t, 'playing.scrubber.stops', stops(0xfff0e0, 0xc09060), 'light'), { half: 'light' }, 'volume', {}],
  ['playing.scrubber.fill', 'classic-light', null, (t) => o.set(t, 'playing.scrubber.fill', stops(0x40c040, 0x106010)), {}, 'now-playing', {}],
  ['playing.scrubber.dark_track', 'classic-light', null, (t) => o.set(t, 'playing.scrubber.dark_track', bumped('classic-light', 'playing.scrubber.dark_track')), { half: 'dark' }, 'volume', { over: 'home' }],
  ['playing.scrubber.dark_fill', 'classic-light', null, (t) => o.set(t, 'playing.scrubber.dark_fill', bumped('classic-light', 'playing.scrubber.dark_fill')), { half: 'dark' }, 'volume', { over: 'home' }],
  ['playing.scrubber.light_track', 'classic-light', null, (t) => o.set(t, 'playing.scrubber.light_track', bumped('classic-light', 'playing.scrubber.light_track')), { half: 'light' }, 'volume', { over: 'home' }],
  ['playing.scrubber.light_fill', 'classic-light', null, (t) => o.set(t, 'playing.scrubber.light_fill', bumped('classic-light', 'playing.scrubber.light_fill')), { half: 'light' }, 'volume', { over: 'home' }],
  ['volume.panel.painter', 'classic-light', null, (t) => o.set(t, 'volume.panel.painter', 'stock'), {}, 'volume', { over: 'home' }],
  ['dialog.confirm.painter', 'classic-light', null, stockConfirm, {}, 'confirm', {}],
  ['dialog.confirm.painter', 'modern', null, (t) => o.set(t, 'dialog.confirm.painter', 'classic-light'), {}, 'confirm', {}],
  ['dialog.confirm.painter', 'minimal', null, (t) => o.set(t, 'dialog.confirm.painter', 'flat'), {}, 'confirm', {}],
  ['volume.panel.painter', 'minimal', null, (t) => o.set(t, 'volume.panel.painter', 'flat'), {}, 'volume', { over: 'home' }],
  ['pages.own.painter', 'modern', null, (t) => o.set(t, 'pages.own.painter', 'classic-light+flat'), {}, 'confirm', {}],
  ['pages.own.painter', 'modern', null, (t) => { o.set(t, 'pages.own.painter', 'stock'); o.set(t, 'pages.own.art_final', 0); }, {}, 'now-playing', {}],
  ['pages.own.art_final', 'modern', null, (t) => o.set(t, 'pages.own.art_final', 0), { half: 'light' }, 'now-playing', {}],
  ['scheme.paper', 'modern', null, (t) => o.setScheme(t, null, 'paper', '#d8d8d8'), { half: 'light' }, 'now-playing', {}],
  ['scheme.paper', 'classic-light', null, (t) => o.setScheme(t, null, 'paper', '#e8e8e8'), { half: 'light' }, 'confirm', {}],
  ['scheme.ink', 'modern', null, (t) => o.setScheme(t, null, 'ink', '#404040'), { half: 'light' }, 'now-playing', {}],
  ['scheme.ink', 'classic-light', null, (t) => o.setScheme(t, null, 'ink', '#303030'), { half: 'light' }, 'now-playing', { scrubbing: true }],
  ['scheme.mode', 'modern', ownSet, (t) => o.setScheme(t, null, 'mode', 'light'), { half: 'dark' }, 'now-playing', {}],
  ['scheme.card', 'minimal', null, (t) => o.setScheme(t, 'cobalt', 'card', true), { accent: 'cobalt' }, 'now-playing', {}],
  ['scheme.card', 'minimal', null, (t) => o.setScheme(t, 'cobalt', 'card', true), { accent: 'cobalt' }, 'confirm', {}],
  ['scheme.fill', 'minimal', null, (t) => o.setScheme(t, 'ivory', 'fill', '#c0d0e0'), { accent: 'ivory' }, 'now-playing', {}],
  ['scheme.fill', 'minimal', null, (t) => o.setScheme(t, 'ivory', 'fill', '#c0d0e0'), { accent: 'ivory' }, 'volume', {}],
  ['scheme.fill', 'minimal', null, (t) => o.setScheme(t, 'ivory', 'fill', '#c0d0e0'), { accent: 'ivory' }, 'confirm', {}],
  ['scheme.muted', 'modern', null, (t) => o.setScheme(t, null, 'muted', '#c08040'), {}, 'now-playing', {}],
  ['scheme.muted', 'classic-light', null, (t) => o.setScheme(t, null, 'muted', '#c08040'), {}, 'now-playing', {}],
  ['scheme.raw_red', 'modern', null, (t) => o.setScheme(t, 'crimson', 'raw_red', false), { half: 'dark', accent: 'crimson', np_layout: 'centred' }, 'now-playing', {}],
  ['scheme.bar.stops', 'classic-light', null, (t) => o.setScheme(t, null, 'bar.stops', stops(0x404850, 0x202428)), { half: 'dark' }, 'volume', { over: 'home' }],
  ['scheme.bar.line', 'classic-light', null, (t) => o.setScheme(t, null, 'bar.line', '#804020'), { half: 'dark' }, 'volume', { over: 'home' }],
  ['scheme.sel.stops', 'classic-light', null, (t) => o.setScheme(t, 'cobalt', 'sel.stops', stops(0x406080, 0x203040)), { accent: 'cobalt', half: 'dark' }, 'now-playing', {}],
  ['scheme.sel.stops', 'classic-light', null, (t) => o.setScheme(t, 'cobalt', 'sel.stops', stops(0x406080, 0x203040)), { accent: 'cobalt', half: 'dark' }, 'confirm', {}],
  ['scheme.sel.stops', 'classic-light', null, (t) => o.setScheme(t, 'cobalt', 'sel.stops', stops(0x406080, 0x203040)), { accent: 'cobalt', half: 'dark' }, 'volume', { over: 'home' }],
  ['scheme.sel.stops', 'classic-light', null, (t) => o.setScheme(t, 'cobalt', 'sel.stops', stops(0x406080, 0x203040)), { accent: 'cobalt', half: 'dark' }, 'volume', {}],
  ['scheme.sel.top', 'minimal', band, (t) => o.setScheme(t, null, 'sel.top', '#80a0c0'), {}, 'confirm', {}],
  ['scheme.sel.edge', 'minimal', band, (t) => o.setScheme(t, null, 'sel.edge', '#102030'), {}, 'confirm', {}],
  ['scheme.sel.text', 'minimal', band, (t) => o.setScheme(t, null, 'sel.text', '#ffe0a0'), {}, 'confirm', {}],
  ['scheme.sel.tall_edge', 'classic-light', stockConfirm, (t) => o.setScheme(t, null, 'sel.tall_edge', '#102030'), { half: 'dark' }, 'confirm', {}],
  ['scheme.sel.tall_line', 'classic-light', stockConfirm, (t) => o.setScheme(t, null, 'sel.tall_line', '#302010'), { half: 'dark' }, 'confirm', {}],
  ['scheme.sel.tall_top', 'classic-light', stockConfirm, (t) => o.setScheme(t, null, 'sel.tall_top', '#a0c0e0'), { half: 'dark' }, 'confirm', {}],
];

test('each schema key shown on these screens changes what is drawn (section 11)', () => {
  for (const [key, base, same, change, choices, id, state] of SHOWN) {
    assert.ok(o.key(key), `${key} is a schema key`);
    const before = JSON.stringify(draw(made(base, same), choices, id, state).log);
    const after = JSON.stringify(draw(made(base, same, change), choices, id, state).log);
    assert.ok(after !== before, `${key} on ${id} over ${base}`);
  }
  // the list is whole: every key section 11 gives these three screens
  const listed = new Set(SHOWN.map((row) => row[0]));
  for (const key of ['geometry.set', 'list.selection.painter', 'list.row.font', 'settings.values.text', 'playing.layout', 'playing.title.font', 'playing.title.font_px',
    'playing.album.caps', 'playing.album.opacity', 'playing.state.opacity', 'playing.art.square', 'playing.scrubber.height', 'playing.scrubber.stops', 'playing.scrubber.fill',
    'playing.scrubber.scrub_height', 'playing.scrubber.dark_track', 'playing.scrubber.dark_fill', 'playing.scrubber.light_track', 'playing.scrubber.light_fill',
    'volume.panel.painter', 'dialog.confirm.painter', 'pages.own.painter', 'pages.own.art_final', 'scheme.paper', 'scheme.ink', 'scheme.mode', 'scheme.card', 'scheme.fill', 'scheme.muted', 'scheme.raw_red',
    'scheme.bar.stops', 'scheme.bar.line', 'scheme.sel.stops', 'scheme.sel.top', 'scheme.sel.edge', 'scheme.sel.text', 'scheme.sel.tall_edge', 'scheme.sel.tall_line',
    'scheme.sel.tall_top']) assert.ok(listed.has(key), `${key} is tried`);
});

test('keys section 11 gives no effect here leave these screens as they were', () => {
  const quiet = [
    ['classic-light', (t) => o.set(t, 'playing.scrubber.painter', 'stock')],
    ['classic-light', (t) => o.set(t, 'playing.info.font_size', 15)],
    ['classic-light', (t) => o.set(t, 'playing.info.value', '#445566')],
    ['classic-light', (t) => o.set(t, 'playing.station.band_a', 40)],
    ['minimal', (t) => o.set(t, 'list.row.title_px', 30)],
    ['minimal', (t) => o.set(t, 'home.rows.font_px', 22)],
    ['modern', (t) => o.set(t, 'list.chevron.selected', 1)],
  ];
  for (const [base, change] of quiet) {
    for (const [id, state] of [['now-playing', {}], ['volume', {}], ['volume', { over: 'home' }], ['confirm', {}]]) {
      assert.equal(JSON.stringify(draw(made(base, change), {}, id, state).log), JSON.stringify(draw(made(base), {}, id, state).log), `${base} ${id}`);
    }
  }
});

// ---- with real glyphs and pixels: only where the dev harness's canvas is installed ----

const canvasDir = fileURLToPath(new URL('./', import.meta.url));
const canvasAt = `${canvasDir}node_modules/@napi-rs/canvas`;
const fonts = [`${canvasDir}../../assets/fonts/LiberationSans-Bold.ttf`, `${canvasDir}../../assets/fonts/texgyreheros-bold.otf`];
const real = existsSync(canvasAt) && fonts.every((f) => existsSync(f));
const needs = { skip: real ? false : 'needs @napi-rs/canvas (npm install @napi-rs/canvas in this folder)' };

function pixels(theme, choices, id, state) {
  const { createCanvas, GlobalFonts, Path2D } = require(canvasAt);
  globalThis.Path2D = Path2D;
  GlobalFonts.registerFromPath(fonts[0], 'Q2 Liberation Sans Bold');
  GlobalFonts.registerFromPath(fonts[1], 'Q2 TeX Gyre Heros Bold');
  Q2Draw.makeCanvas = (w, h) => createCanvas(w, h);
  Q2Draw.resetText();
  const c = createCanvas(375, 320);
  const g = c.getContext('2d');
  Q2Draw.render(g, id, env(theme, choices), state);
  const d = g.getImageData(0, 0, 375, 320).data;
  const px = (x, y) => hex(Q2Draw.pack(d[(y * 375 + x) * 4], d[(y * 375 + x) * 4 + 1], d[(y * 375 + x) * 4 + 2]));
  // the box of the pixels in a rectangle that stand off its top left pixel
  const ink = (x0, y0, x1, y1) => {
    let b = null;
    const o0 = (y0 * 375 + x0) * 4;
    for (let y = y0; y <= y1; y += 1) {
      for (let x = x0; x <= x1; x += 1) {
        const i = (y * 375 + x) * 4;
        if (Math.max(Math.abs(d[i] - d[o0]), Math.abs(d[i + 1] - d[o0 + 1]), Math.abs(d[i + 2] - d[o0 + 2])) > 60) b = b ? [Math.min(b[0], x), Math.min(b[1], y), Math.max(b[2], x), Math.max(b[3], y)] : [x, y, x, y];
      }
    }
    return b;
  };
  return { px, ink };
}

test('Now Playing as pixels: the places DRAWING.md measures (7.2, 7.3, 7.7)', needs, () => {
  const m = pixels('minimal', { half: 'dark' }, 'now-playing', {});
  assert.deepEqual(m.ink(305, 32, 352, 68), [316, 48, 339, 51], 'the More mark');
  assert.deepEqual(m.ink(250, 205, 300, 250), [260, 218, 282, 236], 'the play mode');
  assert.deepEqual(m.ink(305, 205, 352, 250), [316, 217, 339, 236], 'the heart');
  assert.deepEqual(m.ink(150, 250, 225, 262), [159, 252, 214, 259], 'the page dots');
  assert.deepEqual(m.ink(15, 262, 360, 292), [21, 283, 132, 286], 'the fill: rows 283..286, 333 * 83 / 245 columns from x 21');
  assert.equal(m.px(30, 284), '#6e6e6e');
  assert.equal(m.px(200, 284), '#1c1c1c');
  const title = m.ink(190, 86, 362, 118);
  assert.deepEqual([title[0], title[1], title[3]], [197, 94, 111], 'the title\'s ink from x 197, rows 94..111');
  const caps = m.ink(190, 148, 362, 174);
  assert.ok(caps[0] === 197 && caps[1] >= 155 && caps[1] <= 156 && caps[3] === 164, 'the album\'s capitals: from x 197, rows 155..164');
  assert.equal(m.px(16, 72), '#000000', 'the art\'s corner is rounded away');
  assert.notEqual(m.px(22, 78), '#000000');
  const modern = pixels('modern', { half: 'light' }, 'now-playing', {});
  assert.notEqual(modern.px(16, 72), '#f4f4f4', 'Modern\'s art is square');
  assert.equal(modern.px(84, 150), '#ffffff', 'the glyph\'s bar over the art, x 81..87');
  assert.equal(modern.px(30, 285), '#447cdd');
  const c = pixels('classic-light', { half: 'light' }, 'now-playing', {});
  const classicTitle = c.ink(204, 62, 360, 94);
  assert.deepEqual([classicTitle[1], classicTitle[3]], [71, 88], 'Classic\'s title on rows 71..88');
  assert.deepEqual(c.ink(150, 247, 225, 257).slice(0, 3).concat(255), [159, 248, 214, 255], 'the dots at row 248, over the reflection');
  assert.equal(c.px(100, 280), '#5d9efb');
  assert.equal(c.px(200, 272), '#ffffff');
  // the slanted art: its near edge is the frame's height, its far edge shorter, the reflection fades to the paper
  assert.notEqual(c.px(17, 49), '#ffffff', 'the cover\'s top left');
  assert.equal(c.px(192, 52), '#ffffff', 'paper above the far edge');
  assert.notEqual(c.px(192, 62), '#ffffff');
  assert.notEqual(c.px(20, 230), '#ffffff', 'the reflection under the near edge');
  assert.equal(c.px(20, 266), '#ffffff', 'and gone 22 % of the height down');
  const dark = pixels('classic-light', { half: 'dark' }, 'now-playing', {});
  assert.equal(dark.px(192, 52), '#000000');
});

test('the classic-light confirm as pixels: the cells of 9.2', needs, () => {
  const { createCanvas } = require(canvasAt);
  const g = createCanvas(8, 8).getContext('2d');
  Q2Draw.resetText();
  assert.deepEqual([Q2Draw.measure(g, 'Cancel', 'classic-light', 23), Q2Draw.measure(g, 'OK', 'classic-light', 23)], [53, 24]);
  // 89 and 76 wide, from x (375 - 165) / 2 = 105
  const c = pixels('classic-light', { half: 'light' }, 'confirm', { selected: 0 });
  assert.equal(c.px(110, 270), hex(Q2Draw.stopsRows(env('classic-light', { half: 'light' }).S.sel, 30)[12]), 'Cancel\'s cell is lit');
  assert.equal(c.px(240, 280), '#bec7d4', 'the track under OK, row 22');
  assert.equal(c.px(100, 270), '#ffffff', 'paper left of the cells');
  assert.equal(c.px(275, 270), '#ffffff', 'and right of them: the pair ends at x 269');
  assert.notEqual(c.px(268, 270), '#ffffff');
  const d = pixels('classic-light', { half: 'dark' }, 'confirm', { selected: 1 });
  assert.equal(d.px(200, 270), hex(Q2Draw.stopsRows(env('classic-light', { half: 'dark' }).S.sel, 30)[12]), 'OK\'s cell is lit');
});
