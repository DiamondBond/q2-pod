// node --test draw_home.test.mjs
// Home's drawing against DRAWING.md section 5, with a canvas that only writes down what is drawn on it.
// The main check: every schema key that section 11 lists as shown on Home changes the drawing calls when
// its value changes, in the state the section names. Themes are changed through official.js, as the
// editor changes them. No picture is compared here (the pixel tests in the other files do that).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import official from './official.js';
import Q2Draw from './draw_core.js';
import './draw_bar.js';
import './draw_home.js';

const data = JSON.parse(readFileSync(new URL('./official.json', import.meta.url), 'utf8'));
const o = official.open(data);
const builtin = (id) => data.themes.find((b) => b.id === id).resolved;
const hex = (c) => Q2Draw.hex(c);
if (!globalThis.Path2D) globalThis.Path2D = class { constructor(d) { this.d = d; } };

// A canvas context that draws nothing and lists every call with the styles in force. It has no
// getTransform, so text goes straight to fillText, one glyph a call.
function recorder() {
  const calls = [];
  const show = (v) => (v && v.d !== undefined ? `path(${v.d})` : v && v.stops ? `gradient(${v.at}: ${v.stops.join(' ')})` : typeof v === 'number' ? String(Math.round(v * 1000) / 1000) : String(v));
  const ctx = { calls, fillStyle: '', strokeStyle: '', font: '', lineWidth: 1, globalAlpha: 1, lineCap: 'butt', lineJoin: 'miter' };
  const styles = { fill: ['fillStyle', 'globalAlpha'], fillRect: ['fillStyle', 'globalAlpha'], fillText: ['fillStyle', 'font', 'globalAlpha'], stroke: ['strokeStyle', 'lineWidth', 'lineCap', 'globalAlpha'] };
  for (const name of ['save', 'restore', 'beginPath', 'closePath', 'rect', 'clip', 'moveTo', 'lineTo', 'arcTo', 'arc', 'ellipse', 'fill', 'stroke', 'translate', 'scale',
    'clearRect', 'bezierCurveTo', 'quadraticCurveTo', 'fillRect', 'fillText', 'drawImage']) {
    ctx[name] = (...args) => { calls.push([name, ...args.map(show), ...(styles[name] || []).map((s) => show(ctx[s]))].join(' ')); };
  }
  const glyph = ctx.fillText; // a space is written as a middle dot, so a call still splits on spaces
  ctx.fillText = (ch, x, y) => glyph(ch === ' ' ? '·' : ch, x, y);
  ctx.measureText = (s) => ({ width: s.length * parseFloat(ctx.font.split(' ')[1]) * 0.5 });
  ctx.createLinearGradient = (...at) => { const g = { at: at.join(','), stops: [], addColorStop(p, c) { g.stops.push(`${p}:${c}`); } }; return g; };
  return ctx;
}

// What Home itself draws for a resolved theme: the calls up to the status bar's, as text lines.
function drawn(theme, choices = {}, state = {}) {
  const env = Q2Draw.env(o, theme, choices);
  const ctx = recorder();
  const bar = Q2Draw.bar;
  let cut = -1;
  Q2Draw.bar = () => { cut = ctx.calls.length; };
  try {
    Q2Draw.render(ctx, 'home', env, state);
  } finally {
    Q2Draw.bar = bar;
  }
  assert.ok(cut >= 0, 'Home draws the status bar');
  return ctx.calls.slice(0, cut);
}
// the text drawn, in order, without its spaces
const text = (calls) => calls.filter((c) => c.startsWith('fillText ')).map((c) => c.split(' ')[1]).join('').replace(/·/g, '');
const count = (calls, start) => calls.filter((c) => c.startsWith(start)).length;
const layout = (id, choices, state) => Q2Draw.screens.home.layout(Q2Draw.env(o, builtin(id), choices), state);

// A theme of the editor's over a built-in, changed by fn.
let made = 0;
function theme(base, fn) {
  made += 1;
  const t = o.newTheme({ extends: base, id: `test${made}`, name: `Test ${made}` });
  if (fn) fn(t);
  return t;
}
const set = (pairs) => (t) => { for (const [k, v, half] of pairs) o.set(t, k, v, half); };
// Whether a change to a theme changes Home's calls: before and after are functions that change a fresh
// theme over base (before may be null), drawn with the same choices and state.
function changes(base, before, after, choices, state) {
  const a = drawn(o.resolve(theme(base, before)), choices, state);
  const b = drawn(o.resolve(theme(base, (t) => { if (before) before(t); after(t); })), choices, state);
  return a.join('\n') !== b.join('\n');
}

// ---- loading ----

test('a page loads the file with a script tag, after draw_core.js and draw_bar.js', async () => {
  const { runInNewContext } = await import('node:vm');
  const window = {};
  Object.assign(window, { globalThis: window });
  for (const f of ['draw_core.js', 'draw_bar.js', 'draw_home.js']) runInNewContext(readFileSync(new URL(`./${f}`, import.meta.url), 'utf8'), window);
  const screen = window.Q2Draw.screens.home;
  assert.equal(screen.title, 'Home');
  assert.equal(typeof screen.draw, 'function');
  assert.ok(Array.isArray(screen.states) && screen.states.length > 0);
});

test('the script holds no embedded picture, no eval and no request', () => {
  const source = readFileSync(new URL('./draw_home.js', import.meta.url), 'utf8');
  assert.ok(!/data:image|base64|\beval\(|new Function|fetch\(|XMLHttpRequest|https?:/.test(source));
});

test('every listed state draws in each built-in and half, and leaves no clip or transform behind', () => {
  for (const b of data.themes) {
    for (const half of ['dark', 'light']) {
      for (const s of Q2Draw.screens.home.states) {
        const calls = drawn(b.resolved, { half }, s.state);
        assert.equal(count(calls, 'save'), count(calls, 'restore') + 1, `${b.id} ${half} ${s.id}: every save but render's own is restored before the bar`);
        assert.ok(!calls.some((c) => /NaN|undefined/.test(c)), `${b.id} ${half} ${s.id}: every number is a number`);
      }
    }
  }
});

test('the first state leaves the layout to the Home setting; state.layout stands in for it', () => {
  assert.equal(Q2Draw.screens.home.states[0].state.layout, undefined);
  assert.equal(layout('modern', {}, {}).mode, 'split');
  assert.equal(layout('modern', { home: 'full' }, {}).mode, 'full');
  assert.equal(layout('modern', { home: 'full' }, { layout: 'carousel' }).mode, 'carousel');
  assert.notDeepEqual(drawn(builtin('modern'), { home: 'full' }), drawn(builtin('modern'), { home: 'split' }));
  assert.deepEqual(drawn(builtin('modern'), { home: 'full' }), drawn(builtin('modern'), {}, { layout: 'full' }));
});

// ---- the list: DRAWING.md 5.1 to 5.5, the numbers of section 10 ----

test('rows and label boxes of the four built-ins (section 10)', () => {
  const table = { // first row y, row height, label box x0..x1 in Split and in Full, a Full row's width
    minimal: [38, 39, [39, 178], [39, 341], 375],
    'classic-light': [26, 32, [20, 166], [20, 341], 375],
    modern: [30, 39, [33, 153], [33, 335], 369],
    'classic-modern': [26, 32, [20, 166], [20, 341], 375], // Classic's list
  };
  assert.deepEqual(Object.keys(table).sort(), data.themes.map((b) => b.id).sort());
  // none highlighted (state.selected null or -1): no selection and no chevron, every label plain
  const none = drawn(builtin('modern'), { half: 'dark' }, { layout: 'split', selected: null });
  assert.equal(layout('modern', {}, { selected: -1 }).selected, -1);
  assert.ok(!none.some((c) => c.startsWith('stroke ')), 'no chevron');
  assert.notDeepEqual(none, drawn(builtin('modern'), { half: 'dark' }, { layout: 'split', selected: 0 }));
  assert.equal(layout('modern', {}, { layout: 'carousel', selected: null }).selected, 0, 'Carousel always has a card');
  for (const [id, [y, h, split, full, fullRow]] of Object.entries(table)) {
    const s = layout(id, {}, { layout: 'split' });
    const f = layout(id, {}, { layout: 'full' });
    assert.deepEqual([s.rows[0].y, s.rowH, s.rows.length], [y, h, 7], `${id}: rows`);
    assert.deepEqual([s.rows[0].label.x, s.rows[0].label.x + s.rows[0].label.w - 1], split, `${id}: Split's label box`);
    assert.deepEqual([f.rows[0].label.x, f.rows[0].label.x + f.rows[0].label.w - 1], full, `${id}: Full's label box`);
    assert.deepEqual([s.outer, s.inner, f.outer, f.inner], [187, 187, 375, fullRow], `${id}: widths`);
    assert.deepEqual(s.panel, { x: 187, y: s.top - Q2Draw.env(o, builtin(id)).T('home.rows.top'), w: 188, h: 320 - (s.top - Q2Draw.env(o, builtin(id)).T('home.rows.top')) });
    assert.equal(f.panel, null, `${id}: Full has no panel`);
    assert.equal(s.rows[3].y, y + 3 * h);
  }
  assert.deepEqual(layout('modern').rows.map((r) => r.title), ['Now Playing', 'Library', 'Cover Flow', 'Folder', 'Rockbox', 'Streaming', 'Settings']);
});

test('hidden rows close up; the Shortcut names its row; the selection stays on a row', () => {
  assert.deepEqual(layout('minimal', { hide_folder: true, hide_streaming: true, shortcut: 'none' }).rows.map((r) => r.title), ['Now Playing', 'Library', 'Cover Flow', 'Settings']);
  assert.equal(layout('minimal', { shortcut: 'rated_albums' }).rows[4].title, 'Rated Albums');
  assert.equal(layout('minimal', { hide_folder: true }, { selected: 9 }).selected, 5);
  assert.equal(layout('minimal', {}, { selected: -3 }).selected, -1, 'a negative row: none highlighted');
  assert.match(text(drawn(builtin('modern'), { shortcut: 'games' })), /Games/);
});

test('the selection: Classic\'s band, Modern\'s bar and capsule, Minimal\'s dot (5.4)', () => {
  const classic = drawn(builtin('classic-light'), { half: 'light' }, { layout: 'split' });
  assert.ok(classic.includes('fillRect 0 26 187 1 #94c7de 1'), 'the lid on the row\'s first line');
  assert.ok(classic.includes('fillRect 0 57 187 1 #004184 1'), 'the edge on its last');
  assert.ok(classic.includes('fillRect 0 27 187 1 #08a6e7 1') && classic.includes('fillRect 0 56 187 1 #0065d6 1'), 'the stops between');
  const full = drawn(builtin('classic-light'), { half: 'light' }, { layout: 'full', selected: 2 });
  assert.ok(full.includes('fillRect 0 90 375 1 #94c7de 1'), 'Full: 375 wide, on the third row');
  const modern = drawn(builtin('modern'), { half: 'light' }, { layout: 'full' });
  assert.ok(modern.includes('fillRect 0 30 375 1 #447cdd 1') && modern.includes('fillRect 0 68 375 1 #2a6ad8 1'), 'the bar spans the screen, wider than the 369 px rows');
  const round = drawn(builtin('modern'), { half: 'light', corners: 'round' }, { layout: 'split' });
  assert.ok(round.includes('fillRect 6 49 175 1 #2a6ad8 1'), 'Rounded Corners: inset 6 px each side at the row\'s middle');
  assert.ok(!round.some((c) => c.startsWith('fillRect 0 30 187 1 ')), 'and shorter at its ends');
  const dot = drawn(builtin('minimal'), { half: 'dark' }, { layout: 'split' });
  assert.ok(!dot.some((c) => /^fillRect 0 38 187 /.test(c)), 'Minimal: no card on Home');
  assert.ok(dot.some((c) => c === 'fill #ffffff 1'), 'a white dot');
});

test('label colours (5.3, 1.8)', () => {
  const styles = (calls) => [...new Set(calls.filter((c) => c.startsWith('fillText ')).map((c) => c.split(' ')[4]))];
  const first = (calls) => calls.find((c) => c.startsWith('fillText ')).split(' ')[4];
  assert.deepEqual(styles(drawn(builtin('minimal'), { half: 'dark' })), ['#ffffff', '#8c8c8c'], 'Minimal: white on the dot\'s row, else the grey');
  assert.deepEqual(styles(drawn(builtin('minimal'), { half: 'light' })), ['#161616', '#7b7b7b']);
  assert.deepEqual(styles(drawn(o.resolve(theme('minimal', set([['list.selection.painter', 'bar']]))), { half: 'dark' })), ['#8c8c8c'], 'capitals under another painter: all grey');
  assert.equal(first(drawn(builtin('modern'), { half: 'light', accent: 'cobalt' })), '#ffffff', 'Modern: white on a coloured bar in the light half');
  assert.equal(first(drawn(builtin('modern'), { half: 'light', accent: 'graphite' })), '#161616', 'ink on Graphite\'s');
  assert.equal(first(drawn(builtin('modern'), { half: 'light' }, { selected: 3 })), '#161616', 'an unselected row');
  assert.equal(first(drawn(builtin('classic-light'), { half: 'light' })), '#ffffff', 'Classic: sel.text');
  assert.equal(first(drawn(builtin('classic-light'), { half: 'light' }, { selected: 3 })), '#000000');
  const card = o.resolve(theme('modern', set([['list.selection.painter', 'card']])));
  assert.deepEqual(styles(drawn(card, { half: 'dark' })), ['#ffffff', '#aaaaaa'], 'the card painter without capitals');
});

test('label text: capitals under home.rows.caps, the Home role\'s face and size otherwise', () => {
  assert.match(text(drawn(builtin('minimal'))), /^NOWPLAYINGLIBRARY/);
  assert.match(text(drawn(builtin('modern'))), /^NowPlayingLibrary/);
  const font = (calls) => calls.find((c) => c.startsWith('fillText ')).split(' ').slice(5, 7).join(' ');
  assert.equal(font(drawn(builtin('classic-light'))), `700 ${(27 * 1000) / 1432}px`, 'Classic: its own face at 27 px');
  assert.equal(font(drawn(builtin('modern'))), `400 ${(20 * 256) / 299}px`, 'Modern: stock\'s 20 px');
  assert.equal(font(drawn(builtin('minimal'))), `400 ${(18 * 256) / 299}px`, 'Minimal: 18 px capitals');
});

test('the chevron (5.5)', () => {
  const at = (calls) => { // the translate just before the chevron's stroke: its image's top left
    const i = calls.findIndex((c) => /^stroke path\(M(2\.9|21) /.test(c));
    return i < 0 ? null : calls.slice(0, i).reverse().find((c) => c.startsWith('translate ')).split(' ').slice(1).map(Number);
  };
  const colour = (calls) => calls.find((c) => /^stroke path\(M(2\.9|21) /.test(c)).split(' ').slice(-4)[0];
  assert.equal(at(drawn(builtin('minimal'))), null, 'Minimal shows none');
  assert.deepEqual(at(drawn(builtin('classic-light'), {}, { layout: 'split' })), [168, 34], 'Classic, Split: its own image at home.chevron.x');
  assert.deepEqual(at(drawn(builtin('classic-light'), {}, { layout: 'full', selected: 1 })), [317, 66], 'Full: at list.chevron.x, on the selected row');
  assert.deepEqual(at(drawn(builtin('modern'), {}, { layout: 'split' })), [169 - 25, 30 + 19 - 25], 'Modern, Split: stock\'s image centred on x 169');
  assert.deepEqual(at(drawn(builtin('modern'), {}, { layout: 'full' })), [346 - 25, 30 + 19 - 25], 'Full: on x 346');
  assert.equal(colour(drawn(builtin('modern'), { half: 'light', accent: 'cobalt' })), '#ffffff', 'white on a coloured bar');
  assert.equal(colour(drawn(builtin('modern'), { half: 'light', accent: 'graphite' })), '#161616', 'ink on Graphite\'s in the light half');
  assert.equal(colour(drawn(builtin('classic-light'), { half: 'light' })), '#ffffff', 'Classic\'s own art is final');
});

// ---- Split's panel: 5.6 ----

test('the panel: a cover while something plays, else the theme\'s pane or the plate', () => {
  const covers = (calls) => count(calls, 'ellipse');
  const playing = drawn(builtin('classic-light'), {}, { layout: 'split', play: 'playing' });
  assert.equal(covers(playing), 1);
  assert.ok(playing.includes('rect 134 26 323 323'), 'Classic: the 294 px fit at 110 %, from the fit\'s centred crop');
  assert.ok(drawn(builtin('minimal'), {}, { layout: 'split', play: 'paused' }).includes('rect 136 30 319 319'), 'Minimal: 290 px at 110 %');
  assert.ok(playing.includes('rect 187 26 188 294'), 'clipped to the panel');
  const idle = drawn(builtin('classic-light'), { half: 'light' }, { layout: 'split', play: 'none' });
  assert.equal(covers(idle), 0);
  assert.ok(idle.includes('fillRect 187 26 188 1 #63717b 1') && idle.includes('fillRect 187 319 188 1 #63717b 1'), 'Classic: its pane\'s fill down the panel');
  assert.ok(drawn(builtin('classic-light'), { half: 'dark' }, { layout: 'split', play: 'none' }).includes('fillRect 187 26 188 1 #1c1c1c 1'));
  assert.equal(text(idle).replace('NowPlayingLibraryCoverFlowFolderRockboxStreamingSettings', ''), '', 'Now Playing with an empty queue: no caption');
  const plate = drawn(builtin('minimal'), {}, { layout: 'split', play: 'none' });
  assert.equal(covers(plate), 0);
  assert.ok(plate.some((c) => c.endsWith('#777777 1')), 'Minimal: the grey plate');
  // Modern states home.pane.stops at 6ceb519a: its pane, not the plate (DRAWING.md 15.3)
  const modern = drawn(builtin('modern'), { half: 'light' }, { layout: 'split', play: 'none' });
  assert.ok(!modern.some((c) => c.endsWith('#777777 1')), 'Modern: no plate');
  assert.ok(modern.includes('fillRect 187 30 188 1 #f2f2f7 1') && modern.includes('fillRect 187 319 188 1 #f2f2f7 1'), 'Modern: its pane\'s fill down the panel');
  assert.equal(covers(drawn(builtin('modern'), {}, { layout: 'full', play: 'playing' })), 0, 'Full has no panel');
  assert.equal(covers(drawn(builtin('modern'), {}, { layout: 'split', play: 'playing', cover: null })), 0, 'a track without a cover');
});

test('Classic\'s pane follows the highlighted row while Row Preview is on', () => {
  const caption = (choices, state) => text(drawn(builtin('classic-light'), choices, Object.assign({ layout: 'split', play: 'none' }, state))).replace(/NowPlayingLibraryCoverFlowFolder[A-Za-z]*StreamingSettings$/, ''); // the panel is painted first
  assert.equal(caption({}, { selected: 1 }), '148Songs');
  assert.equal(caption({}, { selected: 2 }), '12Albums');
  assert.equal(caption({}, { selected: 3 }), '', 'Folder: no caption');
  assert.equal(caption({}, { selected: 4 }), '', 'Rockbox: no caption');
  assert.equal(caption({ shortcut: 'games' }, { selected: 4 }), '3Games');
  assert.equal(caption({}, { selected: 5 }), '4Services');
  assert.equal(caption({}, { selected: 6 }), '21.4GBFree');
  assert.equal(caption({ ROWPREVIEW: 'Off' }, { selected: 6 }), '', 'Row Preview off: Now Playing\'s pane on every row');
  const playing = (state) => drawn(builtin('classic-light'), {}, Object.assign({ layout: 'split', play: 'playing' }, state));
  assert.equal(count(playing({ selected: 1 }), 'ellipse'), 1, 'Library keeps the cover');
  assert.equal(count(playing({ selected: 2 }), 'ellipse'), 0, 'Cover Flow shows its pane even over a cover');
  // the caption is white in the dark half and the paper in the light half
  const first = (calls) => calls.find((c) => c.startsWith('fillText ')).split(' ')[4];
  const style = (half) => first(drawn(builtin('classic-light'), { half }, { layout: 'split', play: 'none', selected: 1 }));
  assert.deepEqual([style('dark'), style('light')], ['#ffffff', '#ffffff']);
  const paper = o.resolve(theme('classic-light', (t) => o.setScheme(t, null, 'paper', '#e0e0e0')));
  assert.equal(first(drawn(paper, { half: 'light' }, { layout: 'split', play: 'none', selected: 1 })), '#e0e0e0');
});

// ---- the flat look's pane: DRAWING.md 15.3 ----

test('the flat pane: Modern\'s note and queue count, one colour a half, the system face in the quiet grey', () => {
  const pane = (half, state = {}) => drawn(builtin('modern'), { half }, Object.assign({ layout: 'split', play: 'none', queue: 3 }, state));
  const dark = pane('dark');
  assert.ok(dark.includes('fillRect 187 30 188 1 #1c1c1c 1') && dark.includes('fillRect 187 319 188 1 #1c1c1c 1'));
  // no light bands and no shadow: every panel row is the one colour
  assert.equal(dark.filter((c) => c.startsWith('fillRect 187 ')).length, 290);
  // flat_pane_note at (187 + 40, 30 + 57): note.svg's shape from its own (222, 66), white, filled flat
  const at = dark.indexOf('translate 5 21');
  assert.ok(at > 0 && dark[at + 1].startsWith('fill path(M254 82.5 317 71.5V156') && dark[at + 1].endsWith('evenodd #ffffff 1'), 'the note, flat white');
  assert.ok(!dark.some((c) => c.startsWith('stroke ') && c.includes('path(M254')), 'no outline: the flat note is one fill');
  // "3 Songs" in (187, 215, 182, 24) at 17 px, stock's face, #98989d; the light half #6e6e73 and the note #1c1c1e
  const caption = dark.filter((c) => c.startsWith('fillText '));
  assert.equal(text(caption.filter((c) => c.includes('#98989d'))), '3Songs');
  assert.ok(caption.filter((c) => c.includes('#98989d')).every((c) => c.includes(`400 ${(17 * 256) / 299}px Arial`)), 'stock face at 17 px');
  const light = pane('light');
  assert.ok(light.some((c) => c.endsWith('evenodd #1c1c1e 1')));
  assert.equal(text(light.filter((c) => c.includes('#6e6e73'))), '3Songs');
  // nothing playing and no queue: no caption; a track without a cover: the sample's 12
  assert.equal(text(pane('dark', { queue: undefined }).filter((c) => c.includes('#98989d'))), '');
  assert.equal(text(pane('dark', { play: 'playing', cover: null, queue: undefined }).filter((c) => c.includes('#98989d'))), '12Songs');
  // icon_x 0: the pane never follows the row
  const row = pane('dark', { selected: 2 });
  assert.ok(row.includes('translate 5 21'), 'Cover Flow\'s row still shows the note');
  assert.equal(text(row.filter((c) => c.includes('#98989d'))), '3Songs');
  // a cover hides it, as before
  assert.equal(count(drawn(builtin('modern'), {}, { layout: 'split', play: 'playing' }), 'ellipse'), 1);
});

test('the flat pane over Classic: Classic Modern\'s follows the row with flat icons; captions in the system face', () => {
  const pane = (selected, half = 'dark', choices = {}) => drawn(builtin('classic-modern'), Object.assign({ half }, choices), { layout: 'split', play: 'none', selected });
  const stack = pane(2, 'light');
  // flat_pane_icon_stack at (187 + 43, 26 + 67): the drawing fitted to 92 px about (278, 124) of a 96 px image at (230, 76)
  const at = stack.indexOf('translate 278 141');
  assert.ok(at > 0 && stack[at + 1].startsWith('scale ') && stack[at + 3].startsWith('fill path(M246 94h60v60h-60Z') && stack[at + 3].endsWith('evenodd #1c1c1e 1'));
  assert.equal(text(stack.filter((c) => c.includes('#6e6e73'))), '12Albums');
  assert.ok(stack.filter((c) => c.includes('#6e6e73')).every((c) => c.includes('Arial')), 'not Classic\'s face, whatever list.row.font says');
  assert.ok(stack.includes('fillRect 187 26 188 1 #f2f2f7 1'));
  assert.equal(text(pane(6).filter((c) => c.includes('#98989d'))), '21.4GBFree');
  assert.ok(pane(1).includes('translate 5 17'), 'Library: the flat note at (227, 83)');
  assert.ok(pane(4, 'dark', { shortcut: 'shuffle' }).includes('translate 5 17'), 'the Shuffle shortcut: the flat note at the note\'s place');
  assert.ok(!pane(5).some((c) => c.startsWith('fill path') && c.includes('gradient(')), 'no gradient: the flat icons are one colour');
  // Classic itself keeps its own pane (gradient art, its face's caption in white)
  assert.ok(drawn(builtin('classic-light'), { half: 'dark' }, { layout: 'split', play: 'none', selected: 2 }).some((c) => c.startsWith('fill path') && c.includes('gradient(')));
});

test('the flat pane needs the flat bit; without art_final its art turns with the half', () => {
  const over = (fn) => o.resolve(theme('modern', fn));
  const plain = drawn(over(set([['pages.own.painter', 'stock']])), { half: 'light' }, { layout: 'split', play: 'none', queue: 3 });
  assert.ok(plain.some((c) => c.startsWith('fill path') && c.includes('gradient(')), 'pages not flat: Classic\'s pane recipe');
  const unfinal = drawn(over(set([['pages.own.art_final', 0]])), { half: 'light' }, { layout: 'split', play: 'none', queue: 3 });
  const env = Q2Draw.env(o, builtin('modern'), { half: 'light' });
  assert.ok(unfinal.some((c) => c.endsWith(`evenodd ${hex(env.INK(0x1c1c1e))} 1`)), 'the _l ink flipped by the image hook');
});

// ---- Carousel: 5.8 ----

test('Carousel: one card, its name, two arrows; eight cards whatever is hidden; no theme key reaches it', () => {
  const names = [0, 1, 2, 3, 4, 5, 6, 7, 8].map((selected) => text(drawn(builtin('minimal'), { hide_folder: true, shortcut: 'none' }, { layout: 'carousel', selected })));
  assert.deepEqual(names, ['NowPlaying', 'Library', 'CoverFlow', 'Folder', 'Rockbox', 'Streaming', 'PlaybackSettings', 'SystemSettings', 'SystemSettings']);
  const calls = drawn(builtin('modern'), { half: 'dark' }, { layout: 'carousel' });
  assert.equal(count(calls, 'stroke path(M30.5 108.5') + count(calls, 'stroke path(M-30.5 108.5'), 2, 'the two arrows');
  const moved = o.resolve(theme('modern', set([['home.rows.text_x', 80], ['home.rows.top', 20], ['home.rows.font_px', 30], ['list.selection.painter', 'card'], ['home.chevron.visible', 0]])));
  assert.deepEqual(drawn(moved, { half: 'dark' }, { layout: 'carousel' }), drawn(o.resolve(theme('modern')), { half: 'dark' }, { layout: 'carousel' }));
  assert.equal(Q2Draw.screens.home.states.find((s) => s.id === 'carousel').themable, false);
});

// ---- every key of DRAWING.md section 11 that Home shows ----

const SPLIT = { layout: 'split', play: 'playing' };
const FULL = { layout: 'full', play: 'playing' };
const IDLE = { layout: 'split', play: 'none' };
const shadowed = set([['home.pane.shadow_w', 8]]);
const KEYS = [
  // key, base, what is set first (or null), the change, env choices, state
  ['list.selection.painter', 'modern', null, set([['list.selection.painter', 'card']]), {}, SPLIT],
  ['list.chevron.selected', 'classic-light', null, set([['list.chevron.selected', 0]]), { half: 'dark' }, FULL],
  ['list.chevron.x', 'classic-light', null, set([['list.chevron.x', 300]]), {}, FULL],
  ['home.rows.top', 'modern', null, set([['home.rows.top', 12]]), {}, SPLIT],
  ['home.rows.full_row', 'modern', null, set([['home.rows.full_row', 340]]), {}, FULL],
  ['home.rows.text_x', 'modern', null, set([['home.rows.text_x', 50]]), {}, SPLIT],
  ['home.rows.label_end_split', 'modern', null, set([['home.rows.label_end_split', 90]]), {}, SPLIT],
  ['home.rows.label_end_full', 'modern', null, set([['home.rows.label_end_full', 280]]), {}, FULL],
  ['home.rows.font', 'modern', null, set([['home.rows.font', 'bold']]), {}, SPLIT],
  ['home.rows.font_px', 'modern', null, set([['home.rows.font_px', 24]]), {}, SPLIT],
  ['home.rows.caps', 'modern', null, set([['home.rows.caps', 1]]), {}, SPLIT],
  ['home.chevron.visible', 'modern', null, set([['home.chevron.visible', 0]]), {}, SPLIT],
  ['home.chevron.x', 'classic-light', null, set([['home.chevron.x', 150]]), {}, SPLIT],
  ['home.pane.stops', 'classic-light', null, set([['home.pane.stops', [[0, 0x203040], [100, 0x102030]]]]), { half: 'dark' }, IDLE],
  ['home.pane.stops (light)', 'classic-light', null, set([['home.pane.stops', [[0, 0x8090a0], [100, 0x607080]], 'light']]), { half: 'light' }, IDLE],
  ['home.pane.icon_x', 'classic-light', null, set([['home.pane.icon_x', 60]]), {}, Object.assign({ selected: 2 }, IDLE)],
  ['home.pane.icon_y', 'classic-light', null, set([['home.pane.icon_y', 40]]), {}, Object.assign({ selected: 2 }, IDLE)],
  ['home.pane.note_x', 'classic-light', null, set([['home.pane.note_x', 60]]), {}, IDLE],
  ['home.pane.note_y', 'classic-light', null, set([['home.pane.note_y', 30]]), {}, IDLE],
  ['home.pane.count_y', 'classic-light', null, set([['home.pane.count_y', 200]]), {}, Object.assign({ selected: 1 }, IDLE)],
  ['home.pane.count_w', 'classic-light', null, set([['home.pane.count_w', 150]]), {}, Object.assign({ selected: 1 }, IDLE)],
  ['home.pane.count_px', 'classic-light', null, set([['home.pane.count_px', 20]]), {}, Object.assign({ selected: 1 }, IDLE)],
  ['home.pane.light_a', 'classic-light', null, set([['home.pane.light_a', 40]]), {}, IDLE],
  ['home.pane.shadow_w', 'classic-light', null, shadowed, {}, IDLE],
  ['home.pane.shadow_w (over a cover)', 'classic-light', null, shadowed, {}, SPLIT],
  ['home.pane.shadow', 'classic-light', shadowed, set([['home.pane.shadow', '#102030']]), {}, IDLE],
  ['home.pane.shadow (over a cover)', 'classic-light', shadowed, set([['home.pane.shadow', '#102030']]), {}, SPLIT],
  ['home.pane.shadow_a', 'classic-light', shadowed, set([['home.pane.shadow_a', [200, 180, 160, 140, 120, 100, 80, 60]]]), {}, IDLE],
  ['scheme.paper', 'modern', null, (t) => o.setScheme(t, null, 'paper', '#e8e0d0'), { half: 'light' }, SPLIT],
  ['scheme.ink', 'modern', null, (t) => o.setScheme(t, null, 'ink', '#302010'), { half: 'light' }, SPLIT],
  ['scheme.mode', 'modern', null, (t) => o.setScheme(t, null, 'mode', 'dark'), { half: 'light' }, SPLIT],
  ['scheme.card', 'modern', null, (t) => o.setScheme(t, 'cobalt', 'card', 1), { accent: 'cobalt', half: 'dark' }, SPLIT],
  ['scheme.chevron', 'minimal', set([['home.chevron.visible', 1]]), (t) => o.setScheme(t, 'ivory', 'chevron', '#333333'), { accent: 'ivory', half: 'dark' }, SPLIT],
  ['scheme.sel.stops', 'classic-light', null, (t) => o.setScheme(t, 'classic-blue', 'sel.stops', [[0, 0x40c0f0], [100, 0x0050c0]]), {}, SPLIT],
  ['scheme.sel.top', 'classic-light', null, (t) => o.setScheme(t, 'classic-blue', 'sel.top', '#ffffff', 'light'), { half: 'light' }, SPLIT],
  ['scheme.sel.edge', 'classic-light', null, (t) => o.setScheme(t, 'classic-blue', 'sel.edge', '#102030'), {}, SPLIT],
  ['scheme.sel.text', 'classic-light', null, (t) => o.setScheme(t, 'classic-blue', 'sel.text', '#ffff00'), { half: 'dark' }, SPLIT],
  ['scheme.sel.text (light)', 'classic-light', null, (t) => o.setScheme(t, 'classic-blue', 'sel.text', '#ffff00', 'light'), { half: 'light' }, SPLIT],
];

for (const [key, base, before, after, choices, state] of KEYS) {
  test(`${key} changes Home's drawing`, () => {
    assert.ok(changes(base, before, after, choices, state), `${key}: the calls differ`);
  });
}

test('geometry.set: the set that is booted moves the rows', () => {
  const tall = (t) => { o.addGeometry(t, 'tall', null, { bar: 34, home_row: 34 }); o.useGeometry(t, 'tall'); };
  assert.ok(changes('modern', null, tall, {}, SPLIT));
  assert.ok(changes('modern', null, tall, {}, FULL));
  const env = Q2Draw.env(o, o.resolve(theme('modern', tall)));
  const L = Q2Draw.screens.home.layout(env, SPLIT);
  assert.deepEqual([L.rows[0].y, L.rows[1].y, L.panel.y, L.panel.h], [34, 68, 34, 286]);
  // Classic's Row Art picks the set: Home reads nothing that its two sets state differently
  assert.deepEqual(drawn(builtin('classic-light'), { ROWART: 'Off' }, SPLIT), drawn(builtin('classic-light'), { ROWART: 'On' }, SPLIT));
});

test('pages.own.art_final: without it the theme\'s white art turns to ink in the light half', () => {
  // a theme over Classic differs from it on Home by this key alone (only the id classic-light may state 1)
  const own = o.resolve(theme('classic-light'));
  assert.equal(Q2Draw.env(o, own).T('pages.own.art_final'), 0);
  assert.equal(Q2Draw.env(o, builtin('classic-light')).T('pages.own.art_final'), 1);
  for (const state of [SPLIT, FULL, IDLE]) {
    assert.deepEqual(drawn(own, { half: 'dark' }, state), drawn(builtin('classic-light'), { half: 'dark' }, state), 'the dark half is the same');
    assert.notDeepEqual(drawn(own, { half: 'light' }, state), drawn(builtin('classic-light'), { half: 'light' }, state), 'the light half differs');
  }
});

test('the accent and Rounded Corners change the selection; keys Home does not read change nothing', () => {
  assert.notDeepEqual(drawn(builtin('modern'), { accent: 'tidal' }, SPLIT), drawn(builtin('modern'), { accent: 'plum' }, SPLIT));
  assert.notDeepEqual(drawn(builtin('classic-light'), { accent: 'tidal' }, SPLIT), drawn(builtin('classic-light'), { accent: 'plum' }, SPLIT));
  assert.notDeepEqual(drawn(builtin('modern'), { corners: 'round' }, SPLIT), drawn(builtin('modern'), { corners: 'square' }, SPLIT));
  assert.deepEqual(drawn(builtin('minimal'), { corners: 'round' }, SPLIT), drawn(builtin('minimal'), { corners: 'square' }, SPLIT), 'the dot and the cover have no corners to round');
  for (const pairs of [[['list.row.title_px', 30]], [['playing.art.square', 1]], [['home.pane.svc_x', 80]], [['list.scrollbar.w', 6]]]) {
    assert.ok(!changes('modern', null, set(pairs), {}, IDLE), `${pairs[0][0]} is not Home's`);
  }
});
