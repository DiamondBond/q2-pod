// node --test draw_core.test.mjs
// The preview's colour, geometry and layout answers against official.json and the tables of DRAWING.md.
// Tests that need real glyphs run only where the dev harness's canvas is installed (npm install @napi-rs/canvas in this folder).
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import official from './official.js';
import Q2Draw from './draw_core.js';
import './draw_bar.js';

const require = createRequire(import.meta.url);
const data = JSON.parse(readFileSync(new URL('./official.json', import.meta.url), 'utf8'));
const o = official.open(data);
const builtin = (id) => data.themes.find((b) => b.id === id).resolved;
const env = (id, choices) => Q2Draw.env(o, builtin(id), choices);
const hex = (c) => Q2Draw.hex(c);
const stops = (list) => list.map(([p, c]) => `${hex(c)} ${p}`).join(', ');

// A canvas that only writes down what is drawn on it: enough for every rectangle a painter fills.
function recorder() {
  const calls = [];
  const ctx = {
    calls,
    fillStyle: '',
    font: '',
    fillRect(x, y, w, h) { calls.push({ op: 'rect', x, y, w, h, style: this.fillStyle }); },
    fillText(s, x, y) { calls.push({ op: 'text', s, x, y, style: this.fillStyle, font: this.font }); },
    measureText(s) { return { width: s.length * parseFloat(this.font.split(' ')[1]) * 0.5 }; },
    drawImage() {},
  };
  for (const name of ['save', 'restore', 'beginPath', 'closePath', 'rect', 'clip', 'moveTo', 'lineTo', 'arcTo', 'arc', 'ellipse', 'fill', 'stroke', 'translate', 'scale', 'clearRect', 'bezierCurveTo']) ctx[name] = () => {};
  ctx.createLinearGradient = () => ({ addColorStop() {} });
  return ctx;
}
// the colour of the last rectangle a recorder filled over a pixel
const at = (ctx, x, y) => {
  let style = null;
  for (const c of ctx.calls) if (c.op === 'rect' && x >= c.x && x < c.x + c.w && y >= c.y && y < c.y + c.h) style = c.style;
  return style;
};
if (!globalThis.Path2D) globalThis.Path2D = class { constructor(d) { this.d = d; } };

// ---- loading ----

test('a page loads the two files with script tags, as window.Q2Draw', async () => {
  const { runInNewContext } = await import('node:vm');
  const window = {};
  Object.assign(window, { globalThis: window });
  for (const f of ['draw_core.js', 'draw_bar.js']) runInNewContext(readFileSync(new URL(`./${f}`, import.meta.url), 'utf8'), window);
  assert.equal(typeof window.Q2Draw.env, 'function');
  assert.equal(typeof window.Q2Draw.bar, 'function');
  assert.equal(typeof window.Q2Draw.render, 'function');
});

test('the scripts hold no embedded picture and no eval', () => {
  for (const f of ['draw_core.js', 'draw_bar.js']) {
    const text = readFileSync(new URL(`./${f}`, import.meta.url), 'utf8');
    assert.ok(!/data:image|base64|\beval\(|new Function/.test(text), `${f}: no embedded pictures, no eval`);
  }
});

// ---- colour: DRAWING.md section 1 ----

test('the two halves (1.1) and the flip (1.2)', () => {
  const minimal = env('minimal', { half: 'light' });
  const classic = env('classic-light', { half: 'light' });
  assert.deepEqual([hex(minimal.page), hex(minimal.fg)], ['#f4f4f4', '#161616']);
  assert.deepEqual([hex(classic.page), hex(classic.fg)], ['#ffffff', '#000000']);
  assert.deepEqual([hex(env('modern', { half: 'dark' }).page), hex(env('modern', { half: 'dark' }).fg)], ['#000000', '#ffffff']);
  const table = [ // stock terms, Minimal / Modern light, Classic light
    ['#000000', '#f4f4f4', '#ffffff'], ['#ffffff', '#161616', '#000000'], ['#eeeeee', '#252525', '#111111'], ['#cccccc', '#434343', '#333333'],
    ['#bbbbbb', '#525252', '#444444'], ['#aaaaaa', '#606060', '#555555'], ['#8c8c8c', '#7b7b7b', null], ['#949294', null, '#6b6d6b'],
    ['#777777', '#8d8d8d', null], ['#666666', '#9c9c9c', '#999999'], ['#555555', '#aaaaaa', '#aaaaaa'], ['#5a5a5a', '#a6a6a6', '#a5a5a5'],
    ['#424242', '#bbbbbb', '#bdbdbd'], ['#2b2b2b', '#cfcfcf', '#d4d4d4'], ['#1c1c1c', '#dcdcdc', '#e3e3e3'], ['#d8d8d8', '#383838', '#272727'],
    ['#eeeeec', '#252527', null], ['#171717', '#e0e0e0', null],
  ];
  for (const [c, m, k] of table) {
    if (m) assert.equal(hex(minimal.INK(c)), m, `${c} on Minimal's paper`);
    if (k) assert.equal(hex(classic.INK(c)), k, `${c} on Classic's paper`);
  }
  assert.equal(hex(minimal.INK('#2a6ad8')), '#2a6ad8', 'a hue is the same in both halves');
  assert.equal(hex(env('minimal', { half: 'dark' }).INK('#aaaaaa')), '#aaaaaa', 'the dark half states stock terms as they are');
});

test('accents and tones (1.4): the presets, what each theme offers, the tones by row', () => {
  assert.deepEqual([env('minimal').accentName, env('classic-light').accentName, env('modern').accentName], ['graphite', 'classic-blue', 'cobalt']);
  assert.deepEqual([env('minimal').half, env('classic-light').half, env('modern').half], ['dark', 'light', 'light']);
  assert.deepEqual(env('modern', { accent: 'crimson' }).tones.map(hex), ['#e8123f', '#e8123f', '#eb2f56', '#ff1448', '#eb2f56']);
  assert.deepEqual(env('classic-light').tones.map(hex), env('modern', { accent: 'cobalt' }).tones.map(hex), "Classic Blue has cobalt's tones");
  assert.equal(env('modern', { accent: 'ivory' }).accentName, 'graphite', 'Modern does not offer Ivory: its default');
  assert.equal(env('classic-light', { accent: 9 }).ownScheme, true);
  const graphite = env('minimal', { half: 'light' });
  assert.equal(hex(graphite.toneOf(0)), '#d8d8d8', 'Light Mode: a neutral accent asks for its red tone');
  assert.equal(hex(env('minimal', { half: 'light', accent: 'tidal' }).toneOf(0)), '#13838d');
});

test('the plain progress fill and the volume bar, per accent and half (1.5)', () => {
  const table = {
    graphite: ['#6e6e6e', '#383838'], crimson: ['#eb2f56', '#d23b5b'], tidal: ['#30929b', '#30929b'], champagne: ['#9a8446', '#9a8446'],
    cobalt: ['#447cdd', '#447cdd'], tangerine: ['#cb681e', '#cb681e'], plum: ['#9d4f7a', '#9d4f7a'], ivory: ['#eeeeec', '#252527'], green: ['#778e4c', '#778e4c'],
  };
  for (const [accent, [dark, light]] of Object.entries(table)) {
    assert.equal(hex(env('minimal', { accent, half: 'dark' }).progressFill()), dark, `${accent}, dark`);
    assert.equal(hex(env('minimal', { accent, half: 'light' }).progressFill()), light, `${accent}, light`);
    if (accent !== 'ivory') assert.equal(hex(env('modern', { accent, half: 'light' }).progressFill()), light, `Modern ${accent}, light`);
  }
  assert.equal(hex(env('modern', { accent: 'crimson', half: 'light' }).volumeFill()), '#eb2f56', 'the volume bar is not a style colour');
  assert.equal(hex(env('minimal', { accent: 'graphite', half: 'light' }).volumeFill()), '#383838');
});

test('the red mapping (1.6): the worked example, and what it leaves alone', () => {
  assert.equal(hex(Q2Draw.redMap(0xeb2f56, 0xeb2f56, 0xffffff, 1, 244, 22)), '#d23b5b');
  assert.equal(hex(Q2Draw.redMap(0xff1448, 0x447cdd, 0xffffff, 0)), '#447cdd', 'stock red becomes the tone');
  assert.equal(hex(Q2Draw.redMap(0x30929b, 0x447cdd, 0xffffff, 0)), '#30929b', 'another hue is unchanged');
  assert.equal(hex(env('modern', { accent: 'cobalt', half: 'dark' }).imageRed()), '#447cdd');
  assert.equal(hex(env('modern', { accent: 'crimson', half: 'dark' }).imageRed()), '#ff1448', 'a raw_red scheme keeps stock red in the dark half');
  // an image that also holds white takes the light tone, through tone_of in the light half (the references' switch)
  assert.equal(hex(env('minimal', { accent: 'graphite', half: 'dark' }).imageRed()), '#6e6e6e');
  assert.equal(hex(env('minimal', { accent: 'graphite', half: 'light' }).imageRed()), '#383838');
});

test('stand-in art colours measured on the reference pictures (3.6, 3.7)', () => {
  const fills = (e, draw) => {
    const ctx = recorder();
    ctx.arc = () => {};
    const seen = [];
    ctx.fill = function () { seen.push(this.fillStyle); };
    draw(e, ctx);
    return seen;
  };
  const modern = env('modern', { half: 'dark' });
  assert.deepEqual(['shuffle', 'disc', 'note', 'display', 'person'].map((n) => fills(modern, (e, c) => e.art.disc(c, n, 0, 0, 52))[0]),
    ['#ff751c', '#c425ff', '#ff5246', '#ff751c', '#447cdd']);
  const minimal = env('minimal', { half: 'dark' });
  assert.deepEqual(['display', 'shuffle', 'person', 'tag'].map((n) => fills(minimal, (e, c) => e.art.disc(c, n, 0, 0, 52))[0]), ['#868686', '#7c7c7c', '#797979', '#777777']);
  assert.equal(fills(modern, (e, c) => e.art.tile(c, 'note', 0, 0, 52))[0], '#777777', 'the tile is stock grey in every theme');
  assert.deepEqual(fills(modern, (e, c) => e.art.switch(c, 0, 0, false)).slice(0, 1), ['#777777'], 'the off switch never flips');
  assert.equal(Q2Draw.DISCS.spotify, undefined, 'no third party look-alike');
  assert.deepEqual(Q2Draw.sample.library.map((r) => r.title), ['Shuffle', 'Artists', 'Albums', 'Songs', 'Genres', 'Era', 'Playlists', 'Ratings', 'Recently Added',
    'Recent', 'Most Played', 'Hi-Res', 'Long Songs', 'Games', 'Update Library']);
});

test('painting a stops list (1.7): the bar\'s gloss rows of 4.2, the scrubber rows of 7.9', () => {
  const light = env('classic-light', { half: 'light' });
  const dark = env('classic-light', { half: 'dark' });
  const want = 'ffffff fbfbfb f7f7f7 f3f3f3 efefef ebebeb e7e7e7 e4e3e4 e0dfe0 dcdbdc d8d6d8 d4d2d4 d0ced0 ccc9cc c7c4c7 c1bec1 bcb9bc b7b4b7 b2afb2 aca9ac a9a7a9 a6a5a6 a2a2a2 9fa09f 9c9e9c';
  assert.equal(light.rows(light.T('scheme.bar.stops'), 25).map((c) => hex(c).slice(1)).join(' '), want);
  assert.deepEqual([hex(light.T('scheme.bar.line2')), hex(light.T('scheme.bar.line')), hex(dark.T('scheme.bar.line'))], ['#848584', '#5a595a', '#333333']);
  assert.deepEqual([...new Set(dark.rows(dark.T('scheme.bar.stops'), 25).map(hex))], ['#1c1c1c']);
  const track = 'e2e2e2 ffffff ffffff ffffff ffffff fdfdfd fafafa fafafa f9f9f9 f7f7f7 f6f6f6 f6f6f6 f6f6f6 f5f5f5 f4f4f4 f4f4f4 f4f4f4 f4f4f4 f4f4f4 cecece';
  const night = '313131 373737 373737 373737 373737 363636 363636 353535 343434 323232 313131 313131 313131 323232 333333 343434 343434 343434 343434 2b2b2b';
  const fill = '7d96d7 82a3f0 7fa5fc 729cf8 6e9bf5 6b9bf2 6b9df4 6ba1f7 68a2fb 5d9efb 438dee 3990f1 3599f8 32a1fd 34a9fe 38affd 3fb2fc 51b8fd 5bb1ed 5b9ecf';
  const row = (e, key) => e.rows(e.T(key), 20).map((c) => hex(c).slice(1)).join(' ');
  assert.equal(row(light, 'playing.scrubber.stops'), track);
  assert.equal(row(dark, 'playing.scrubber.stops'), night);
  assert.equal(row(light, 'playing.scrubber.fill'), fill);
  assert.deepEqual(Q2Draw.stopsRows([[0, 1], [50, 2], [100, 3]], 3), [1, 2, 3], 'as many stops as rows: one a row');
  assert.deepEqual(Q2Draw.stopsRows([[0, 1]], 5), [], 'fewer than two stops draw nothing');
});

test('text colour on a row (1.8): the two-line rows\' table', () => {
  const text = (id, choices, o) => hex(env(id, choices).rowText(o));
  const both = (id, choices, o) => [text(id, choices, o), text(id, choices, Object.assign({ second: true }, o))];
  assert.deepEqual(both('minimal', { half: 'dark' }, {}), ['#ffffff', '#ffffff']);
  assert.deepEqual(both('minimal', { half: 'light' }, {}), ['#161616', '#161616']);
  assert.deepEqual(both('modern', { half: 'light' }, {}), ['#161616', '#161616']);
  assert.deepEqual(both('classic-light', { half: 'dark' }, {}), ['#ffffff', '#949294']);
  assert.deepEqual(both('classic-light', { half: 'light' }, {}), ['#000000', '#6b6d6b']);
  // selected, a coloured accent: both lines white in both halves
  for (const half of ['dark', 'light']) {
    assert.deepEqual(both('minimal', { half, accent: 'cobalt' }, { selected: true }), ['#ffffff', '#ffffff']);
    assert.deepEqual(both('modern', { half, accent: 'cobalt' }, { selected: true }), ['#ffffff', '#ffffff']);
    assert.deepEqual(both('classic-light', { half }, { selected: true }), ['#ffffff', '#ffffff']);
    assert.deepEqual(both('classic-light', { half, accent: 'graphite' }, { selected: true }), ['#ffffff', '#ffffff']);
  }
  // selected, Graphite: the half's ink; Ivory: the card's dark ink
  assert.deepEqual(both('minimal', { half: 'light', accent: 'graphite' }, { selected: true }), ['#161616', '#161616']);
  assert.deepEqual(both('modern', { half: 'light', accent: 'graphite' }, { selected: true }), ['#161616', '#161616']);
  assert.deepEqual(both('minimal', { half: 'dark', accent: 'ivory' }, { selected: true }), ['#171717', '#171717']);
  assert.deepEqual(both('minimal', { half: 'light', accent: 'ivory' }, { selected: true }), ['#e0e0e0', '#e0e0e0']);
  // labels that really are #aaaaaa take scheme.muted (Now Playing's "3 of 12" and times)
  assert.equal(text('minimal', { half: 'dark' }, { colour: '#aaaaaa' }), '#8c8c8c');
  assert.equal(text('minimal', { half: 'light' }, { colour: '#aaaaaa' }), '#7b7b7b');
  assert.equal(text('modern', { half: 'light' }, { colour: '#aaaaaa' }), '#606060');
  assert.equal(text('classic-light', { half: 'light' }, { colour: '#aaaaaa' }), '#6b6d6b');
});

test('the built-ins\' schemes (1.9)', () => {
  const sel = { // sel.stops, sel.edge, sel.tall_edge; dark top, dark tall_line; light top, tall_top, tall_line
    'classic-blue': ['#08a6e7 #009ade #008ade #007dde #006dd6 #0065d6', '#004184', '#004aa3', '#08a6e7', '#004aa3', '#94c7de', '#27ade5', '#688db3'],
    graphite: ['#454545 #424242 #424242 #424242 #404040 #404040', '#272727', '#303030', '#454545', '#303030', '#424242', '#444444', '#353535'],
    crimson: ['#f11a5a #e8124e #e8123f #e81232 #e01126 #e0111e', '#8a0b15', '#aa0d14', '#f11a5a', '#aa0d14', '#e8a1b4', '#ef386e', '#bb7379'],
    tangerine: ['#cc4a07 #c44600 #c45400 #c45f00 #bd6600 #bd6d00', '#754100', '#905600', '#cc4a07', '#905600', '#c49a83', '#ca5c22', '#9e815c'],
    green: ['#708439 #697f34 #647f34 #607f34 #587a32 #567a32', '#364c1f', '#405d26', '#708439', '#405d26', '#787f66', '#718343', '#5a664d'],
  };
  for (const [accent, [band, edge, tallEdge, top, tallLine, lightTop, lightTallTop, lightTallLine]] of Object.entries(sel)) {
    const d = env('classic-light', { accent, half: 'dark' });
    const l = env('classic-light', { accent, half: 'light' });
    for (const e of [d, l]) {
      assert.equal(e.T('scheme.sel.stops').map(([, c]) => hex(c)).join(' '), band, `${accent} band`);
      assert.deepEqual(e.T('scheme.sel.stops').map(([p]) => p), [0, 17, 38, 58, 79, 100]);
      assert.deepEqual([hex(e.T('scheme.sel.edge')), hex(e.T('scheme.sel.tall_edge')), hex(e.T('scheme.sel.text'))], [edge, tallEdge, '#ffffff'], accent);
    }
    assert.deepEqual([hex(d.S.sel_top), hex(d.S.sel_tall_top), hex(d.S.sel_tall_line)], [top, top, tallLine], `${accent}, dark`);
    assert.deepEqual([hex(l.S.sel_top), hex(l.S.sel_tall_top), hex(l.S.sel_tall_line)], [lightTop, lightTallTop, lightTallLine], `${accent}, light`);
  }
  const m = env('minimal');
  assert.deepEqual([hex(m.S.fill), hex(m.S.chevron), hex(m.S.muted), m.S.bar_light, m.S.card], ['#eeeeec', '#777777', '#8c8c8c', 0, 0]);
  assert.equal(env('minimal', { accent: 'ivory' }).S.card, 1);
  assert.equal(env('minimal', { accent: 'crimson' }).S.raw_red, 1);
  assert.equal(hex(env('modern').S.bar_light), '#dedede');
  const light = env('classic-light', { half: 'light' });
  const dark = env('classic-light', { half: 'dark' });
  assert.equal(stops(light.T('list.separator.stops')), '#fcfcfc 0, #e2e3e2 50, #f7f7f7 100');
  assert.equal(stops(dark.T('list.separator.stops')), '#000000 0, #2c2c2c 50, #000000 100');
  assert.deepEqual([hex(dark.T('list.scrollbar.thumb')), hex(light.T('list.scrollbar.thumb'))], ['#6e7380', '#8f98a8']);
  assert.deepEqual([stops(dark.T('home.pane.stops')), stops(light.T('home.pane.stops'))], ['#1c1c1c 0, #1c1c1c 100', '#63717b 0, #63717b 100']);
  assert.deepEqual([hex(dark.T('playing.info.value')), hex(light.T('playing.info.value'))], ['#8a8a8a', '#8e9196']);
  assert.equal(hex(light.T('bar.battery.line')), '#717070');
});

// ---- geometry: DRAWING.md section 2 and 10 ----

test('the frame and the glass (2.1)', () => {
  for (let y = 0; y < 320; y += 1) assert.equal(Q2Draw.glassInset(y), data.corner_inset[y], `row ${y}`);
  assert.deepEqual([Q2Draw.glassInset(0), Q2Draw.glassInset(6), Q2Draw.glassInset(80), Q2Draw.glassInset(200)], [80, 50, 0, 0]);
  // the mask clears exactly the firmware's width on every row, at both ends
  const cleared = [];
  Q2Draw.glass({ clearRect: (x, y, w, h) => cleared.push([x, y, w, h]) });
  for (const [x, y, w, h] of cleared) {
    assert.equal(h, 1);
    assert.equal(w, data.corner_inset[y], `row ${y}`);
    assert.ok(x === 0 || x === 375 - w);
  }
  assert.equal(cleared.length, 2 * data.corner_inset.slice(0, 320).filter(Boolean).length);
  assert.deepEqual(env('minimal').win, { x: 0, y: 30, w: 375, h: 290 });
  assert.deepEqual(env('classic-light').win, { x: 0, y: 26, w: 375, h: 294 });
});

test('geometry sets (2.2): the table, and Row Art picking Classic\'s set', () => {
  const fields = ['bar', 'bar_px', 'bar_title_w', 'bar_right', 'batt_w', 'batt_h', 'home_row', 'home_lib', 'np_ipod', 'lib_pitch', 'lib_body', 'lib_art', 'lib_inset', 'art_pitch',
    'art_body', 'art', 'art_inset', 'art_title24_y', 'art_meta_y', 'song_pitch', 'song_body', 'song_title24_y', 'song_meta_y', 'pitch', 'body', 'text_art', 'text_art_inset',
    'title24_y', 'meta_y', 'text_x', 'action_row', 'list_end', 'set_row', 'set_rows', 'set_icon', 'stream_row', 'toolbar'];
  const table = {
    ipod: [30, 0, 0, 0, 16, 11, 39, 0, 0, 72, 68, 52, 8, 72, 68, 52, 8, 13, 39, 72, 68, 13, 39, 72, 68, 52, 8, 13, 39, 0, 0, 0, 68, 4, 40, 68, 1],
    'classic-light': [26, 21, 91, 60, 26, 13, 32, 1, 1, 32, 32, 0, 0, 52, 52, 52, 0, 1, 29, 52, 52, 1, 29, 32, 32, 0, 0, 4, 8, 20, 32, 256, 32, 9, 0, 52, 0],
    'classic-light-text': [26, 21, 91, 60, 26, 13, 32, 1, 1, 32, 32, 0, 0, 32, 32, 0, 0, 4, 8, 52, 52, 1, 29, 32, 32, 0, 0, 4, 8, 20, 32, 256, 32, 9, 0, 32, 0],
  };
  const sets = { ipod: env('minimal'), 'classic-light': env('classic-light'), 'classic-light-text': env('classic-light', { ROWART: 'Off' }) };
  for (const [name, e] of Object.entries(sets)) {
    assert.equal(e.setName, name);
    assert.deepEqual(fields.map((f) => e.G[f]), table[name], name);
  }
  assert.equal(env('modern').setName, 'ipod');
  assert.equal(env('classic-light', { ROWART: 0 }).setName, 'classic-light-text', 'an own option also takes its index');
});

test('the flat look\'s colours (15.1, 15.2): who takes what, and what is on per accent and half', () => {
  const bits = (id) => { const e = env(id); return [e.flatPages, e.classicPages, e.flatDialogs, e.flatVolume]; };
  assert.deepEqual(bits('minimal'), [false, false, false, false]);
  assert.deepEqual(bits('classic-light'), [false, true, false, false]);
  assert.deepEqual(bits('modern'), [true, false, true, true]);
  assert.deepEqual(bits('classic-modern'), [true, true, true, true]);
  // 15.2's table: [accent, Modern dark, Modern light, Classic Modern dark, Classic Modern light]
  const table = [
    ['classic-blue', null, null, 0x207cde, 0x207cde], ['graphite', 0xd8d8d8, 0x383838, 0xd8d8d8, 0x272727], ['crimson', 0xe8123f, 0xe8123f, 0xff1448, 0xff1448],
    ['tidal', 0x13838d, 0x13838d, 0x30929b, 0x30929b], ['champagne', 0x8c732c, 0x8c732c, 0x9a8446, 0x9a8446], ['cobalt', 0x2a6ad8, 0x2a6ad8, 0x447cdd, 0x447cdd],
    ['tangerine', 0xc45400, 0xc45400, 0xcb681e, 0xcb681e], ['plum', 0x903868, 0x903868, 0x9d4f7a, 0x9d4f7a], ['green', 0x647f34, 0x647f34, 0x778e4c, 0x778e4c],
  ];
  for (const [accent, ...want] of table) {
    const got = [['modern', 'dark'], ['modern', 'light'], ['classic-modern', 'dark'], ['classic-modern', 'light']].map(([id, half]) => {
      const e = env(id, { half, accent });
      return e.accentName === accent ? e.flatOn() : null;
    });
    assert.deepEqual(got.map((c) => (c === null ? null : hex(c))), want.map((c) => (c === null ? null : hex(c))), accent);
  }
  // only Graphite's dark half is bright (its words take the ink)
  assert.deepEqual([0xd8d8d8, 0x778e4c, 0x207cde, 0x383838].map(Q2Draw.bright), [true, false, false, false]);
  // the rest, the ink, the quiet grey and the ground, per half
  const d = env('modern', { half: 'dark' });
  const l = env('classic-modern', { half: 'light' });
  assert.deepEqual([d.flatRest, d.flatInk, d.flatQuiet, d.flatPage].map(hex), ['#2c2c2e', '#ffffff', '#98989d', '#000000']);
  assert.deepEqual([l.flatRest, l.flatInk, l.flatQuiet, l.flatPage].map(hex), ['#e9e9ec', '#1c1c1e', '#6e6e73', '#ffffff']);
  assert.equal(hex(env('modern', { half: 'light' }).flatPage), '#f4f4f4');
  // flat art is final under the flat pages painter with art_final; Classic's own art_final does not make it so
  assert.equal(hex(env('modern', { half: 'light' }).flatArt(0x1c1c1e)), '#1c1c1e');
  assert.notEqual(hex(env('classic-light', { half: 'light' }).flatArt(0x1c1c1e)), '#1c1c1e');
});

test('own art is final by art_final and the pages bit that owns its name, or by the Status Bar\'s theme (3.7)', () => {
  const made = (base, edit) => {
    const t = o.newTheme({ extends: base, id: 'dusk', name: 'Dusk' });
    edit(t);
    assert.deepEqual(o.problems(t).map((p) => p.tool), [], 'the changed theme builds');
    return o.resolve(t);
  };
  const final = (e) => [e.finalArt(false), e.finalArt(true)];
  assert.deepEqual(final(env('classic-light')), [true, false]);
  assert.deepEqual(final(env('modern')), [false, true]);
  assert.deepEqual(final(env('classic-modern')), [true, true]);
  assert.deepEqual(final(env('minimal')), [false, false]);
  // over Modern (art_final 1, flat pages), Classic's chevron is not final: it turns to the ink in the light half
  const chevron = made('modern', (t) => { o.set(t, 'home.chevron.visible', 1); o.set(t, 'home.chevron.x', 317); });
  const strokes = (e) => {
    const ctx = recorder();
    ctx.stroke = function () { ctx.calls.push({ op: 'stroke', style: this.strokeStyle }); };
    e.art.chevron(ctx, 0, 0);
    return ctx.calls.filter((c) => c.op === 'stroke').map((c) => c.style);
  };
  const light = Q2Draw.env(o, chevron, { half: 'light' });
  assert.deepEqual(strokes(light), [Q2Draw.css(light.INK(0xffffff))]);
  assert.notEqual(Q2Draw.hex(light.INK(0xffffff)), '#ffffff');
  const classic = env('classic-light', { half: 'light' });
  assert.deepEqual(strokes(classic), [Q2Draw.css(0xffffff)]);
  // a flat theme without art_final, shown with Status Bar: Modern, keeps its flat_ images final as Modern does
  const flat = made('minimal', (t) => o.set(t, 'pages.own.painter', 'flat'));
  assert.equal(flat.art_final, 0);
  const own = Q2Draw.env(o, flat, { half: 'light' });
  const underModern = Q2Draw.env(o, flat, { half: 'light', STATUSBAR: 'Modern' });
  assert.equal(underModern.barTheme.theme.id, 'modern');
  assert.deepEqual([final(own), final(underModern)], [[false, false], [false, true]]);
  assert.notEqual(hex(own.flatArt(0x1c1c1e)), '#1c1c1e');
  assert.equal(hex(underModern.flatArt(0x1c1c1e)), '#1c1c1e');
  // and Status Bar: Classic makes Classic's classic_light_ art final under any theme
  assert.deepEqual(final(Q2Draw.env(o, flat, { STATUSBAR: 'Classic' })), [true, false]);
});

test('the numbers per theme (section 10) that the environment answers', () => {
  const m = env('minimal');
  const c = env('classic-light');
  const d = env('modern');
  assert.deepEqual([m.bar, c.bar, d.bar], [30, 26, 30]);
  assert.deepEqual([m.choice('bar.fill.painter'), c.choice('bar.fill.painter'), d.choice('bar.fill.painter')], ['flat', 'gloss', 'flat']);
  assert.deepEqual([m.choice('bar.battery.painter'), c.choice('bar.battery.painter')], ['stock', 'classic-light']);
  assert.deepEqual([m.choice('list.selection.painter'), c.choice('list.selection.painter'), d.choice('list.selection.painter')], ['card', 'stops', 'bar']);
  assert.deepEqual([m.T('home.rows.top'), c.T('home.rows.top'), d.T('home.rows.top')].map((top, i) => [m, c, d][i].bar + top), [38, 26, 30], "Home's first row");
  assert.deepEqual([m.T('home.rows.full_row'), c.T('home.rows.full_row'), d.T('home.rows.full_row')], [375, 375, 369]);
  assert.deepEqual([m.T('home.rows.text_x'), c.T('home.rows.text_x'), d.T('home.rows.text_x')], [39, 20, 33]);
  assert.deepEqual([c.T('home.chevron.x'), c.T('list.chevron.x'), c.T('list.chevron.selected')], [168, 317, 1]);
  assert.deepEqual([m.T('playing.scrubber.height'), c.T('playing.scrubber.height'), d.T('playing.scrubber.height')], [4, 20, 8]);
  assert.deepEqual([m.T('settings.rows.top') + m.bar, c.T('settings.rows.top') + c.bar, d.T('settings.rows.top') + d.bar], [38, 26, 30], "the settings list's top");
  assert.deepEqual([c.choice('volume.panel.painter'), c.choice('dialog.confirm.painter'), m.choice('dialog.confirm.painter')], ['classic-light', 'classic-light', 'stock']);
  assert.deepEqual([c.T('list.scrollbar.w'), c.T('list.scrollbar.right'), c.T('list.scrollbar.top'), c.T('list.scrollbar.bottom'), c.T('list.scrollbar.min')], [4, 2, 59, 261, 16]);
  assert.deepEqual([m.artRadius(52), m.artRadius(166), m.artRadius(180)], [3, 12, 13], 'Minimal rounds its art');
  assert.deepEqual([d.artSquare, env('modern', { corners: 'round' }).artSquare, c.artSquare], [true, false, true]);
});

test('the viewer\'s switches: presets, what a theme does not offer, what a value not offered reads as', () => {
  const m = env('minimal');
  const c = env('classic-light');
  const d = env('modern');
  assert.deepEqual([m.round, c.round, d.round], [true, false, false]);
  assert.deepEqual([m.timeTitle, c.timeTitle, d.timeTitle], [true, true, false]);
  assert.deepEqual([m.set.home, m.set.battery, m.set.shortcut, m.set.np_layout], ['split', 'icon', 'rockbox', 'ipod']);
  assert.equal(c.set.battery, 'icon', 'Battery starts at the icon, whatever default= says');
  assert.equal(env('classic-light', { battery: 'both' }).set.battery, 'inside', 'Classic reads Icon + Percent as Percent Inside');
  assert.equal(env('classic-light', { corners: 'round' }).round, false, 'Classic does not offer Rounded Corners');
  assert.equal(env('classic-light', { np_layout: 'centred' }).npCentred, false, 'nor the Centred page');
  assert.equal(env('minimal', { np_layout: 'centred' }).npCentred, true);
  assert.deepEqual([c.own.STATUSBAR, c.own.SHOWQ2POD, c.own.HOMELIB, c.own.ROWPREVIEW, c.own.ROWART], [0, 1, 1, 1, 1]);
  assert.equal(env('minimal', { STATUSBAR: 'Classic' }).barTheme.theme.id, 'classic-light');
  assert.equal(env('minimal', { STATUSBAR: 'Minimal' }).barTheme.theme.id, 'minimal');
  assert.equal(m.barTheme, m);
  assert.deepEqual(m.homeRows().map((r) => r.title), ['Now Playing', 'Library', 'Cover Flow', 'Folder', 'Rockbox', 'Streaming', 'Settings']);
  assert.deepEqual(env('minimal', { shortcut: 'none', hide_folder: true }).homeRows().map((r) => r.title), ['Now Playing', 'Library', 'Cover Flow', 'Streaming', 'Settings']);
  assert.deepEqual(m.appearanceRows().map((r) => (r.kind === 'switch' ? r.title : `${r.title}: ${r.value}`)), ['Theme: Minimal', 'Status Bar: Theme', 'Time in Title',
    'Show Wordmark: On', 'Light Mode: Off', 'Accent: Graphite', 'Rounded Corners', 'Home: Split', 'Shortcut: Rockbox', 'Battery: Icon', 'Centred Now Playing', 'Hide Streaming', 'Hide Folder']);
  assert.deepEqual(c.appearanceRows().map((r) => `${r.title} / ${r.value}`), ['Theme / Classic', 'Status Bar / Theme', 'Time in Title / On', 'Show Wordmark / On',
    'Light Mode / On', 'Accent / Classic Blue', 'Home / Split', 'Shortcut / Rockbox', 'Battery / Icon', 'Library on Home / On', 'Row Preview / On', 'Row Art / On',
    'Hide Streaming / Off', 'Hide Folder / Off']);
});

// ---- fonts: DRAWING.md section 3 ----

test('which face and size each text takes (3.3), and the fallback (3.4)', () => {
  const m = env('minimal');
  const c = env('classic-light');
  const d = env('modern');
  assert.deepEqual(m.role('title', 24), { face: 'regular', px: 24, faux: false });
  assert.deepEqual(c.role('title', 24), { face: 'classic-light', px: 27, faux: false });
  assert.deepEqual(c.role('tall', 24), { face: 'classic-light', px: 28, faux: false });
  assert.deepEqual(c.role('meta', 16), { face: 'regular', px: 17, faux: false });
  assert.deepEqual(c.role('bar', 16), { face: 'classic-light', px: 21, faux: false });
  assert.deepEqual(c.role('home', 20), { face: 'classic-light', px: 27, faux: false });
  assert.deepEqual(d.role('np', 22), { face: 'bold', px: 22, faux: false });
  assert.deepEqual(d.role('np', 16), { face: 'bold', px: 16, faux: false }, "the stock-style bar's title: the Now Playing role at 16");
  assert.deepEqual([27, 28, 21, 23, 17].map((px) => Q2Draw.fallback('classic-light', px, '日本').px), [22, 23, 17, 19, 14]);
  assert.deepEqual(Q2Draw.fallback('classic-light', 27, 'Музыка'), { face: 'bold', px: 22, faux: false }, 'Cyrillic: still bold');
  assert.deepEqual(Q2Draw.fallback('classic-light', 27, '日本'), { face: 'regular', px: 22, faux: true });
  assert.deepEqual(Q2Draw.fallback('bold', 22, '日本'), { face: 'regular', px: 22, faux: true }, 'bold falls to stock at the same px');
  assert.deepEqual(Q2Draw.fallback('classic-light', 0, '日本').px, 0, 'a px of 0 stays 0');
  assert.deepEqual(c.canvasFace(27, 'N Songs'), { face: 'classic-light', px: 27, faux: false });
  assert.deepEqual(m.canvasFace(16, '80%'), { face: 'regular', px: 16, faux: false });
});

test('size and baseline (3.2): the css factor and the rounded ascent', () => {
  const factor = (face) => Q2Draw.FACES[face].em / (Q2Draw.FACES[face].ascent - Q2Draw.FACES[face].descent);
  assert.deepEqual(['classic-light', 'bold', 'regular'].map((f) => factor(f).toFixed(4)), ['0.6983', '0.8951', '0.8562']);
  // Classic's 27 px Home label in a 32 px row: line top y + 2, baseline y + 23; the bar's 21 px title: baseline row 17
  assert.equal(Math.floor((32 - 27) / 2) + Q2Draw.metrics('classic-light', 27).ascent, 23);
  assert.equal(-1 + Math.floor((25 - 21) / 2) + Q2Draw.metrics('classic-light', 21).ascent, 17);
  // Modern's 20 px Home label in a 39 px row: line top y + 9, baseline y + 24; the stock bar's 16 px clock: baseline 19
  assert.equal(Math.floor((39 - 20) / 2) + Q2Draw.metrics('regular', 20).ascent, 24);
  assert.equal(Math.floor((30 - 16) / 2) + Q2Draw.metrics('regular', 16).ascent, 19);
});

// ---- shapes ----

test('a pill\'s radius on a row (6.2)', () => {
  assert.equal(Q2Draw.pillRadius(72, [{ x: 8, y: 0, w: 52, h: 68, centre: true }]), 36, 'Library: a centred disc is not tested');
  assert.equal(Q2Draw.pillRadius(68, [{ x: 28, y: 14, w: 40, h: 40 }]), 34, 'settings: the icon is inside the circle');
  assert.equal(Q2Draw.pillRadius(72, [{ x: 8, y: 0, w: 52, h: 68 }]), 2, 'a cover row: down to the floor');
  assert.equal(Q2Draw.pillRadius(48), 24, 'the confirm dialog\'s row');
});

test('the selection painters (5.4, 6.2)', () => {
  // Classic's first Home row: a line at y 26, the stops over 27..56, the edge at 57
  let ctx = recorder();
  const c = env('classic-light');
  let out = c.selection(ctx, 0, 26, 187, 32, { home: true });
  assert.deepEqual([at(ctx, 0, 26), at(ctx, 100, 27), at(ctx, 186, 56), at(ctx, 0, 57), at(ctx, 187, 30), at(ctx, 0, 58)], ['#94c7de', '#08a6e7', '#0065d6', '#004184', null, null]);
  assert.equal(out.accent, true);
  // a 52 px row is tall: the stops over all of it, then its four lines
  ctx = recorder();
  out = c.selection(ctx, 0, 58, 375, 52);
  assert.deepEqual([at(ctx, 0, 58), at(ctx, 0, 59), at(ctx, 0, 108), at(ctx, 0, 109)], ['#94c7de', '#27ade5', '#004aa3', '#688db3']);
  assert.equal(out.tall, true);
  // Modern's bar: tone [4] on the first row, then tone [0]; square without Rounded Corners
  ctx = recorder();
  env('modern', { half: 'dark' }).selection(ctx, 0, 30, 187, 39, { home: true });
  assert.deepEqual([at(ctx, 0, 30), at(ctx, 0, 31), at(ctx, 186, 68)], ['#447cdd', '#2a6ad8', '#2a6ad8']);
  // with Rounded Corners: inset 6, the ends a circle of radius 19
  ctx = recorder();
  out = env('modern', { half: 'dark', corners: 'round' }).selection(ctx, 0, 30, 187, 39, { home: true });
  assert.equal(out.radius, 19);
  assert.deepEqual([at(ctx, 5, 49), at(ctx, 6, 49), at(ctx, 180, 49), at(ctx, 181, 49)], [null, '#2a6ad8', '#2a6ad8', null]);
  // Minimal on Home: a 6 px dot at x 25; in a list: its card in tone [0], flipped in the light half
  ctx = recorder();
  const dot = [];
  ctx.arcTo = () => dot.push(1);
  env('minimal', { half: 'dark' }).selection(ctx, 0, 38, 187, 39, { home: true });
  assert.ok(dot.length > 0, 'the dot is a rounded box');
  ctx = recorder();
  env('minimal', { half: 'light', corners: 'square' }).selection(ctx, 0, 30, 375, 72);
  assert.equal(at(ctx, 0, 30), '#bbbbbb');
  ctx = recorder();
  out = env('minimal', { half: 'dark' }).selection(ctx, 0, 30, 375, 72, { images: [{ x: 8, y: 0, w: 52, h: 68 }] });
  assert.deepEqual([out.radius, at(ctx, 6, 30), at(ctx, 5, 30)], [0, '#424242', null], 'a cover row\'s card is square, inset 6');
});

// ---- the status bar: DRAWING.md section 4 ----

test('the bar\'s fill (4.2)', () => {
  const rows = (id, choices) => {
    const ctx = recorder();
    const e = env(id, choices);
    Q2Draw.bar(ctx, e, { play: 'none', wifi: null });
    return Array.from({ length: e.bar }, (_, y) => at(ctx, 0, y));
  };
  assert.deepEqual([...new Set(rows('minimal', { half: 'dark' }))], ['#000000']);
  assert.deepEqual([...new Set(rows('minimal', { half: 'light' }))], ['#f4f4f4']);
  assert.deepEqual([...new Set(rows('modern', { half: 'light' }))], ['#dedede']);
  const light = rows('classic-light', { half: 'light' });
  assert.deepEqual([light.length, light[0], light[23], light[24], light[25]], [26, '#ffffff', '#9fa09f', '#848584', '#5a595a']);
  const dark = rows('classic-light', { half: 'dark' });
  assert.deepEqual([dark[0], dark[24], dark[25]], ['#1c1c1c', '#1c1c1c', '#333333']);
  // gloss on a 30 px bar: the stops over rows 0..28, the line on row 29
  const other = rows('minimal', { half: 'light', STATUSBAR: 'Classic' });
  assert.deepEqual([other.length, other[0], other[28], other[29]], [30, '#ffffff', '#848584', '#5a595a']);
});

test('the bar\'s layout: the stock-style bar (4.3) and the bar with a title (4.4)', () => {
  const ctx = recorder();
  const box = (r) => r && [r.x, r.y, r.w, r.h];
  let L = Q2Draw.barLayout(ctx, env('minimal'), { bt: 'linked' });
  assert.deepEqual(box(L.slot), [303, 0, 18, 30]);
  assert.deepEqual(box(L.wifi), [285, 0, 14, 30]);
  assert.deepEqual([L.bt.x, L.bt.x + L.bt.w - 1], [238, 280]);
  assert.deepEqual(box(L.play), [54, 0, 15, 30]);
  assert.deepEqual(box(L.centre), [129, 0, 117, 30]);
  assert.deepEqual([L.centre.text, L.centre.face, L.centre.px], ['9:41 AM', 'regular', 16]);
  assert.equal(Q2Draw.barLayout(ctx, env('minimal'), { hour: 21, minute: 5, clock24: true }).centre.text, '21:05');
  assert.equal(Q2Draw.barLayout(ctx, env('minimal'), { hour: 0, minute: 7 }).centre.text, '12:07 AM');
  L = Q2Draw.barLayout(ctx, env('minimal'), { play: 'none' });
  assert.deepEqual([box(L.idle), L.idle.caps, L.play], [[54, 0, 28, 30], true, undefined]);
  L = Q2Draw.barLayout(ctx, env('modern'), { title: 'Library' });
  assert.deepEqual([L.centre.text, L.centre.face, L.centre.px], ['Library', 'bold', 16], 'Time in Title off: the page name in the Now Playing role');
  assert.equal(Q2Draw.barLayout(ctx, env('modern', { SHOWQ2POD: 'Off' }), { home: true, title: 'Q2 Pod' }).centre.text, '', 'no wordmark: no title and no clock');
  assert.equal(Q2Draw.barLayout(ctx, env('modern'), { title: '' }).centre.text, '9:41 AM', 'a page without a title keeps the clock');

  L = Q2Draw.barLayout(ctx, env('classic-light'), { bt: 'on', title: 'Library' });
  assert.deepEqual(box(L.slot), [286, 0, 29, 22]);
  assert.deepEqual(box(L.play), [264, 0, 18, 22]);
  assert.deepEqual([L.wifi.x, L.wifi.y + (L.wifi.h - 16) / 2], [246, 2], "Wi-Fi's image top: 3 + wifi_dy");
  assert.deepEqual([L.bt.x, L.bt.x + L.bt.w - 1, L.bt.y + (L.bt.h - 16) / 2], [199, 241, 4]);
  assert.deepEqual(box(L.title), [57, -1, 95, 25]);
  assert.deepEqual(box(L.clock), [135, -1, 105, 25]);
  assert.deepEqual([L.title.text, L.title.face, L.title.px, L.clock.text], ['Library', 'classic-light', 21, '9:41']);
  assert.equal(Q2Draw.barLayout(ctx, env('classic-light'), { play: 'none' }).wifi.x, 268, 'without the play state the row closes up');
});

test('the battery\'s mode and slot (4.6)', () => {
  const ctx = recorder(); // its digits are 8 px and its % 8 px at 16 px: pct(100) is 32
  const slot = (id, choices, state) => {
    const L = Q2Draw.barLayout(ctx, env(id, choices), state);
    return [L.battery.mode, L.slot.w];
  };
  assert.deepEqual(slot('minimal', {}, {}), [0, 18]);
  assert.deepEqual(slot('minimal', { battery: 'inside' }, {}), [3, 30]);
  assert.deepEqual(slot('minimal', { battery: 'percent' }, { battery: 7 })[0], 1);
  assert.deepEqual(slot('classic-light', {}, {}), [0, 29]);
  assert.deepEqual(slot('classic-light', { battery: 'inside' }, {}), [3, 29]);
  assert.deepEqual(slot('minimal', { STATUSBAR: 'Classic' }, {}), [0, 29], "the bar theme's battery in the live theme's row");
  assert.deepEqual(slot('classic-light', { STATUSBAR: 'Minimal' }, {}), [0, 18]);
});

// ---- with real glyphs: only where the dev harness's canvas is installed ----

const canvasDir = fileURLToPath(new URL('./', import.meta.url));
const canvasAt = `${canvasDir}node_modules/@napi-rs/canvas`;
const fonts = [`${canvasDir}../../assets/fonts/LiberationSans-Bold.ttf`, `${canvasDir}../../assets/fonts/texgyreheros-bold.otf`];
const real = existsSync(canvasAt) && fonts.every((f) => existsSync(f));

test('text widths as the device lays them out (3.2)', { skip: real ? false : 'needs @napi-rs/canvas (npm install @napi-rs/canvas in this folder)' }, () => {
  const { createCanvas, GlobalFonts, Path2D } = require(canvasAt);
  globalThis.Path2D = Path2D;
  GlobalFonts.registerFromPath(fonts[0], 'Q2 Liberation Sans Bold');
  GlobalFonts.registerFromPath(fonts[1], 'Q2 TeX Gyre Heros Bold');
  Q2Draw.resetText();
  const g = createCanvas(375, 320).getContext('2d');
  const table = [['classic-light', 27, 'Now Playing', 113], ['classic-light', 21, 'Q2 Pod', 51], ['classic-light', 27, 'Library', 63], ['classic-light', 21, '12:59', 37],
    ['classic-light', 21, '100%', 37], ['classic-light', 23, 'Cancel', 53], ['classic-light', 23, 'OK', 24], ['bold', 16, 'Now Playing', 86], ['bold', 16, 'Q2 Pod', 51],
    ['bold', 16, 'Library', 50]];
  for (const [face, px, s, w] of table) assert.equal(Q2Draw.measure(g, s, face, px), w, `${s} in ${face} at ${px}`);
  // the stand-in for stock's face steps like it only where the stand-in is Arial or a face with its advances
  const arial = GlobalFonts.families.some((f) => f.family === 'Arial' || f.family === 'Liberation Sans');
  if (arial) {
    const stock = [[20, 'Now Playing', 93], [16, 'Q2 Pod', 48], [24, 'Library', 61], [16, '9:41 AM', 52], [16, '12:59 PM', 60], [16, '100%', 36], [16, '3 of 12', 44],
      [24, 'Theme: Minimal', 143], [20, 'Cancel', 52], [20, 'OK', 24]];
    for (const [px, s, w] of stock) assert.equal(Q2Draw.measure(g, s, 'regular', px), w, `${s} in the stand-in at ${px}`);
  }
  // with the clock out of the way Classic's title box is 165 px wide (x 57..221)
  const L = Q2Draw.barLayout(g, env('classic-light', { time_title: 'off' }), { title: 'Library' });
  assert.deepEqual([L.title.x, L.title.w, L.clock.text], [57, 165, '']);
  // Battery modes fitted with the real digits: Classic's 100% is 37 px
  assert.deepEqual(Q2Draw.barLayout(g, env('classic-light', { battery: 'percent' }), { battery: 100 }).slot.w, 37);
  assert.equal(Q2Draw.barLayout(g, env('minimal', { battery: 'both' }), { bt: 'on' }).battery.mode, 2, 'icon + percent beside Wi-Fi and Bluetooth: 93 of 94 px');
});

test('the bar as pixels: places DRAWING.md states (4.3, 4.4, 4.6)', { skip: real ? false : 'needs @napi-rs/canvas (npm install @napi-rs/canvas in this folder)' }, () => {
  const { createCanvas } = require(canvasAt);
  Q2Draw.makeCanvas = (w, h) => createCanvas(w, h);
  const draw = (id, choices, state) => {
    const c = createCanvas(375, 320);
    const g = c.getContext('2d');
    const e = env(id, choices);
    Q2Draw.render(g, 'list-library', e, state);
    return { d: g.getImageData(0, 0, 375, 320).data, e };
  };
  // the box of the pixels in a rectangle that stand off their row's first pixel
  const ink = ({ d }, x0, y0, x1, y1) => {
    let box = null;
    for (let y = y0; y <= y1; y += 1) {
      for (let x = x0; x <= x1; x += 1) {
        const i = (y * 375 + x) * 4;
        const b = (y * 375 + x0) * 4;
        if (Math.max(Math.abs(d[i] - d[b]), Math.abs(d[i + 1] - d[b + 1]), Math.abs(d[i + 2] - d[b + 2])) > 60) box = box ? [Math.min(box[0], x), Math.min(box[1], y), Math.max(box[2], x), Math.max(box[3], y)] : [x, y, x, y];
      }
    }
    return box;
  };
  const m = draw('minimal', { half: 'dark' }, { bt: 'linked' });
  assert.deepEqual(ink(m, 300, 0, 325, 29), [303, 10, 320, 20], 'the stock icon: body x 303..318, rows 10..20, and its nub');
  assert.deepEqual(ink(m, 262, 0, 282, 29), [271, 8, 279, 21], "Bluetooth's ink");
  assert.deepEqual(ink(m, 54, 0, 70, 29), [56, 9, 65, 20], 'the play mark');
  assert.deepEqual(ink(draw('minimal', { half: 'dark', battery: 'inside' }, { wifi: null }), 286, 0, 325, 29), [291, 8, 320, 22], 'percent inside: body x 291..318, rows 8..22');
  const c = draw('classic-light', { half: 'dark' }, { bt: 'linked', title: 'Library' });
  assert.deepEqual(ink(c, 225, 0, 243, 23), [232, 5, 240, 18], "Classic: Bluetooth's ink");
  assert.deepEqual(ink(c, 284, 0, 320, 23), [287, 5, 314, 17], 'Classic: the body (287, 5, 26, 13) and its nub to x 314');
  const title = ink(c, 50, 0, 130, 23);
  assert.ok(title[0] === 59 || title[0] === 60, "Classic's title: text from x 59 (its first letter's ink a pixel in at most)");
  assert.deepEqual([title[1], title[3]], [6, 19], "Classic's title: capitals from row 6, descenders to row 19");
});
