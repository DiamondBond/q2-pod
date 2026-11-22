// node --test official.test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import official from './official.js';

const data = JSON.parse(readFileSync(new URL('./official.json', import.meta.url), 'utf8'));
const o = official.open(data);
const { parse, load, ThemeError } = official;
const builtin = (id) => data.themes.find((b) => b.id === id);
const theme = (body = '', head = 'id="t" name="T" index="3"') => `<theme format="1" ${head}>${body}</theme>`;
const over = (base, body = '') => theme(body, `id="t" name="T" index="3" extends="${base}"`);
const refused = (fn, words) => assert.throws(fn, (e) => e instanceof ThemeError && (words instanceof RegExp ? words.test(e.message) : e.message === words), String(words));
const fresh = (base = 'minimal') => o.newTheme({ extends: base, id: 'dusk', name: 'Dusk' });
const tools = (list) => list.map((p) => p.tool);

// ---- the tool this was written against ----

test('official.js mirrors the theme.py that official.json was made from', () => {
  const changed = Object.entries(official.MIRRORED).filter(([name, hash]) => data.mirrored[name] !== hash).map(([name]) => name);
  assert.deepEqual(changed, [], `tools/theme.py changed these since official.js mirrored them: check each against official.js, then update MIRRORED in official.js from official.json`);
  assert.equal(official.TOKEN, data.xml.token, 'the tokenizer');
  assert.deepEqual({ amp: '&', lt: '<', gt: '>', quot: '"' }, data.xml.entities);
});

test('a page loads official.js with a script tag, as window.Q2Official', async () => {
  const { runInNewContext } = await import('node:vm');
  const window = { TextEncoder, TextDecoder };
  runInNewContext(readFileSync(new URL('./official.js', import.meta.url), 'utf8'), Object.assign(window, { globalThis: window }));
  const page = window.Q2Official.open(data);
  assert.equal(page.write(page.newTheme({ extends: 'modern', id: 'dusk', name: 'Dusk' })), o.write(fresh('modern')));
  assert.equal(page.problems(builtin('classic-light').text).length, 0);
});

// ---- the XML subset ----

test('a file is elements, attributes in order, comments and space', () => {
  const root = parse('<!-- a\n comment -->\n<theme format="1" id="a">\n  <view name="list" b.c_1="x"><element name="row"/></view>\n\t<option/>\r\n</theme>\n', 'a/theme.xml');
  assert.equal(root.tag, 'theme');
  assert.equal(root.line, 3);
  assert.deepEqual([...root.attrs], [['format', '1'], ['id', 'a']]);
  assert.deepEqual(root.children.map((c) => [c.tag, c.line, c.file]), [['view', 4, 'a/theme.xml'], ['option', 5, 'a/theme.xml']]);
  assert.deepEqual([...root.children[0].attrs], [['name', 'list'], ['b.c_1', 'x']]);
  assert.equal(root.children[0].children[0].tag, 'element');
});

test('the four entities are read, and nothing else after an ampersand', () => {
  assert.equal(parse(theme().replace('name="T"', 'name="a &amp; b &lt;&gt; &quot;c&quot; &amp;lt;"')).attrs.get('name'), 'a & b <> "c" &lt;');
  for (const bad of ['&apos;', '&#65;', 'a & b', '&amp']) refused(() => parse(theme().replace('"T"', `"${bad}"`)), 'theme.xml:1: unknown entity');
});

test('what is not the subset is refused, with its line', () => {
  const cases = [
    ['<theme format="1">\nhello</theme>', 'f:2: text between tags'],
    ['<theme format="1">\n </theme>', 'f:2: text between tags'],
    ['﻿<theme format="1"/>', 'f:1: text between tags'],
    ['<theme format="1">\n<!-- never closed</theme>', 'f:2: unclosed comment'],
    ['<theme format="1"><!-- a -- b --></theme>', 'f:1: unclosed comment'],
    ["<theme format='1'/>", 'f:1: malformed tag'],
    ['<theme format="1" Id="a"/>', 'f:1: malformed tag'],
    ['<theme format="1" id=a/>', 'f:1: malformed tag'],
    ['<theme format="1" id="a<b"/>', 'f:1: malformed tag'],
    ['<theme format="1" id="a\tb"/>', 'f:1: malformed tag'],
    ['<theme format="1"id="a"/>', 'f:1: malformed tag'],
    ['<theme format="1"></theme id="a">', 'f:1: malformed tag'],
    ['<theme format="1"><a/></theme/>', 'f:1: malformed tag'],
    ['<?xml version="1.0"?><theme format="1"/>', 'f:1: malformed tag'],
    ['<theme format="1" id="a" id="b"/>', 'f:1: duplicate attribute id'],
    ['<theme format="1">\n<view>\n</option></theme>', 'f:3: mismatched </option>'],
    ['</theme>', 'f:1: mismatched </theme>'],
    ['<theme format="1">\n<view>', 'f:2: unclosed <view>'],
    ['<theme format="1"/>\n<theme format="1"/>', 'f:2: more than one root element'],
    ['<theme format="1"></theme></theme>', 'f:1: more than one root element'],
    ['<theme format="2"/>', 'f:1: root must be <theme format="1">'],
    ['<themes format="1"/>', 'f:1: root must be <theme format="1">'],
    ['', 'f:1: root must be <theme format="1">'],
    ['  <!-- only a comment -->\n', 'f:1: root must be <theme format="1">'],
  ];
  for (const [text, words] of cases) refused(() => parse(text, 'f'), words);
});

test('a file is at most 32 KB of UTF-8', () => {
  const sized = (bytes, fill = ' ') => theme().padEnd(bytes - (fill.length > 1 ? 0 : 0), fill);
  assert.equal(load(sized(32768)).tag, 'theme');
  refused(() => load(sized(32769), 'f'), 'f:1: larger than 32 KB');
  const wide = `<!--${'é'.repeat(16380)}-->${theme()}`; // 16 thousand characters, 32 thousand bytes
  assert.ok(wide.length < 32768);
  refused(() => load(wide, 'f'), 'f:1: larger than 32 KB');
  const bytes = new TextEncoder().encode(theme());
  assert.equal(load(bytes).attrs.get('id'), 't');
  refused(() => load(Uint8Array.from([...bytes, 0xff]), 'f'), 'f:1: not UTF-8');
  refused(() => load(Uint8Array.from([0xef, 0xbb, 0xbf, ...bytes]), 'f'), 'f:1: text between tags'); // a BOM is text
  refused(() => load(new Uint8Array(32769), 'f'), 'f:1: larger than 32 KB');
});

// ---- one value ----

test('every key is written where official.json says, in the forms the tool takes', () => {
  const samples = { bool: '1', color: '#808080', stops: '#808080 0, #808080 100', alphas: '1', rows: '#808080' };
  let seen = 0;
  for (const k of o.keys) {
    const stated = samples[k.type] ?? (k.choices ? k.choices[0] : k.type === 'set' ? Object.keys(data.geometry.sets)[0] : String(k.lo));
    for (const [form, prefix] of [['plain', ''], ['light', 'light.'], ['dark', 'dark.']]) {
      const attr = `${prefix}${k.xml.attr}="${stated}"`;
      const body = k.xml.element ? `<view name="${k.xml.view}"><element name="${k.xml.element}" ${attr}/></view>`
        : k.xml.tag === 'view' ? `<view name="${k.xml.view}" ${attr}/>` : `<${k.xml.tag} ${attr}/>`;
      let taken = true;
      try {
        o.resolveNode(parse(theme(body)), new Map());
      } catch (e) {
        assert.ok(e instanceof ThemeError, e.stack);
        taken = false;
      }
      assert.equal(taken, k.xml.forms.includes(form), `${k.path} as ${attr}`);
      seen += 1;
    }
  }
  assert.equal(seen, 3 * data.schema.length);
});

test('a value is held to its type', () => {
  assert.equal(o.value('list.icons.mono', '1'), 1);
  refused(() => o.value('list.icons.mono', 'true'), 'list.icons.mono: expected 0 or 1');
  assert.equal(o.value('list.selection.painter', 'bar'), o.key('list.selection.painter').choices.indexOf('bar'));
  refused(() => o.value('list.selection.painter', 'Bar'), 'list.selection.painter: unknown value Bar');
  assert.equal(o.value('motion.step.easing', 'sin_inout'), 8);
  refused(() => o.value('motion.step.easing', 'sine'), /^motion.step.easing: sine is not one of linear, /);
  assert.equal(o.value('home.pane.shadow', '#0A0b0C'), 0x0a0b0c);
  assert.equal(o.value('home.pane.shadow', '#000000'), 0, 'black is a colour where 0 is not "unset"');
  for (const bad of ['0a0b0c', '#abc', '#0a0b0cff', 'red']) refused(() => o.value('home.pane.shadow', bad), 'home.pane.shadow: expected #rrggbb');
  refused(() => o.value('list.scrollbar.thumb', '#000000'), 'list.scrollbar.thumb: #000000 reads as unset; use #010101');
  refused(() => o.value('list.nothing.here', '1'), 'unknown key list.nothing.here');
});

test('a number is held to its range, whatever its size', () => {
  for (const k of o.keys.filter((x) => x.type === 'int')) {
    assert.equal(o.value(k.path, String(k.lo)), k.lo);
    assert.equal(o.value(k.path, String(k.hi)), k.hi);
    refused(() => o.value(k.path, String(k.lo - 1)), `${k.path}: ${k.lo - 1} outside ${k.lo}..${k.hi}`);
    refused(() => o.value(k.path, String(k.hi + 1)), `${k.path}: ${k.hi + 1} outside ${k.lo}..${k.hi}`);
  }
  assert.equal(o.value('bar.icons.bt_dy', '-0'), 0);
  assert.equal(o.value('list.row.title_px', '007'), 7);
  refused(() => o.value('list.row.title_px', '123456789012345678901234567890'), 'list.row.title_px: 123456789012345678901234567890 outside 0..64');
  for (const bad of ['', '1.5', '+1', '1e2', ' 1', '0x10']) refused(() => o.value('list.row.title_px', bad), 'list.row.title_px: expected an integer');
});

test('stops rise from 0 to 100, 2 to 13 of them', () => {
  const path = 'bar.battery.stops';
  assert.deepEqual(o.value(path, '#000000 0,#ffffff 40 ,  #0000ff 100'), [[0, 0], [40, 0xffffff], [100, 0xff]]);
  const many = (n) => Array.from({ length: n }, (_, i) => `#101010 ${i === n - 1 ? 100 : i}`).join(', ');
  assert.equal(o.value(path, many(13)).length, 13);
  refused(() => o.value(path, many(14)), `${path}: 2 to 13 stops`);
  refused(() => o.value(path, '#101010 0'), `${path}: 2 to 13 stops`);
  for (const bad of ['#101010 0, #101010 50', '#101010 10, #101010 100', '#101010 0, #101010 60, #101010 60, #101010 100']) {
    refused(() => o.value(path, bad), `${path}: positions must rise from 0 to 100`);
  }
  for (const bad of ['', '#101010 0; #101010 100', '#101010, #202020', '#101010 0, #101010  100', '#101010 0, #101010 1000']) {
    refused(() => o.value(path, bad), `${path}: expected "#rrggbb N, ..."`);
  }
});

test('alphas and pixel rows', () => {
  assert.deepEqual(o.value('home.pane.shadow_a', '255 0 16'), [255, 0, 16]);
  assert.equal(o.value('home.pane.shadow_a', Array(32).fill('1').join(' ')).length, 32);
  for (const bad of ['', '256', '1  2', '1,2', Array(33).fill('1').join(' ')]) refused(() => o.value('home.pane.shadow_a', bad), 'home.pane.shadow_a: expected up to 32 alphas 0..255');
  assert.deepEqual(o.value('playing.scrubber.dark_track', '#102030 #10203040'), [0xff102030, 0x40102030]);
  assert.equal(o.value('playing.scrubber.dark_track', Array(31).fill('#000000').join(' ')).length, 31);
  for (const bad of ['', '#1020', '#102030, #102030', Array(32).fill('#000000').join(' ')]) {
    refused(() => o.value('playing.scrubber.dark_track', bad), 'playing.scrubber.dark_track: expected up to 31 of #rrggbb or #rrggbbaa');
  }
});

test('a value writes as the text that reads back to it', () => {
  assert.equal(o.text('list.icons.mono', true), '1');
  assert.equal(o.text('list.selection.painter', 2), 'bar');
  assert.equal(o.text('list.selection.painter', 'bar'), 'bar');
  assert.equal(o.text('home.pane.shadow', 0x0a0b0c), '#0a0b0c');
  assert.equal(o.text('bar.battery.stops', [[0, 0x101010], [100, 0xffffff]]), '#101010 0, #ffffff 100');
  assert.equal(o.text('home.pane.shadow_a', [1, 2, 3]), '1 2 3');
  assert.equal(o.text('playing.scrubber.dark_track', [0xff102030, 0x40102030, 0x00102030]), '#102030 #10203040 #10203000');
  for (const b of data.themes) { // every value the built-ins end with
    for (const k of o.keys.filter((x) => x.xml.tag === 'view' && !['stops', 'alphas', 'rows'].includes(x.type) && !(x.final && !b.resolved[x.field]))) {
      assert.equal(o.value(k.path, o.text(k.path, b.resolved[k.field])), b.resolved[k.field], k.path);
    }
    for (const k of o.keys.filter((x) => ['stops', 'alphas', 'rows'].includes(x.type) && x.xml.tag === 'view' && b.resolved[x.field].length)) {
      assert.deepEqual(o.value(k.path, o.text(k.path, b.resolved[k.field])), b.resolved[k.field], k.path);
    }
  }
});

// ---- resolve ----

test('each built-in resolves to the values the tool gave', () => {
  for (const b of data.themes) {
    assert.deepEqual([...parse(b.text, b.file).attrs], b.written.attrs);
    const t = o.resolve(b.text, b.file);
    assert.deepStrictEqual(t, b.resolved, b.id);
    assert.deepStrictEqual(o.drawn(t), b.drawn, `${b.id}, as drawn`);
  }
});

test('each built-in file reads as the elements and attributes the tool read', () => {
  const tree = (n) => ({ tag: n.tag, line: n.line, attrs: [...n.attrs], children: n.children.map(tree) });
  for (const b of data.themes) assert.deepStrictEqual(tree(parse(b.text, b.file)), b.written);
});

test('a theme with no base starts from the defaults, with every accent', () => {
  const t = o.resolve(theme());
  for (const k of o.keys.filter((x) => !x.path.startsWith('scheme.'))) assert.deepEqual(t[k.field], k.default, k.path);
  assert.equal(t.schemes.length, data.accents.length);
  assert.equal(t.accents, 2 ** data.accents.length - 1);
  assert.deepEqual([t.id, t.name, t.index, t.opts, t.geoms, t.light], ['t', 'T', 3, [], {}, {}]);
  assert.equal(t.undeclared.length, Object.keys(data.settings).length);
});

test('a theme takes its base\'s values, then its own', () => {
  const base = builtin('classic-light').resolved;
  const t = o.resolve(over('classic-light', '<view name="list"><element name="row" title_px="30"/></view><colorScheme name="plum" muted="#123456"/>'));
  assert.equal(t['font_px[ROLE_TITLE]'], 30);
  assert.equal(t['font_px[ROLE_META]'], base['font_px[ROLE_META]']);
  assert.equal(t.schemes[6].muted, 0x123456);
  assert.equal(t.schemes[4].muted, base.schemes[4].muted);
  assert.deepEqual(t.opts, base.opts);
  assert.deepEqual(t.geoms, base.geoms);
  assert.equal(t.geom_set, 'classic-light');
});

test('what the firmware\'s sources supply, a built-in cannot state and another theme can', () => {
  const supplied = o.supplied('minimal');
  assert.equal(supplied['home.rows.top'], builtin('minimal').resolved.home_top);
  assert.deepEqual(o.supplied('dusk'), {});
  refused(() => o.resolve(builtin('minimal').text.replace('<view name="bar">', '<view name="home"><element name="rows" top="9"/></view><view name="bar">')),
          /^minimal\/theme.xml:\d+: home.rows.top comes from patch\/offsets.inc$/);
  const t = o.resolve(over('minimal', '<view name="home"><element name="rows" top="9"/></view>'));
  assert.equal(t.home_top, 9);
  assert.equal(t.home_full_row, builtin('minimal').resolved.home_full_row, 'the rest is still the base\'s');
});

test('a final key has a light half; the rest have one value', () => {
  const t = o.resolve(over('minimal', '<view name="list"><element name="scrollbar" thumb="#111111" light.thumb="#eeeeee"/></view>'
    + '<colorScheme light.sel.text="#222222" light.paper="#fefefe"/>'));
  assert.equal(t.sb_thumb, 0x111111);
  assert.equal(t.light.sb_thumb, 0xeeeeee);
  assert.ok(t.schemes.every((s) => s.light.sel_text === 0x222222 && s.paper === 0xfefefe && s.sel_text === 0));
  refused(() => o.resolve(over('minimal', '<view name="list"><element name="scrollbar" light.w="4"/></view>')), 't/theme.xml:1: list.scrollbar.w: one value for both halves');
  refused(() => o.resolve(over('minimal', '<view name="list"><element name="scrollbar" thumb="#111111" dark.thumb="#111111"/></view>')),
          't/theme.xml:1: list.scrollbar.thumb: stated twice (thumb and dark.thumb)');
  refused(() => o.resolve(over('minimal', '<colorScheme paper="#fefefe"/>')), "t/theme.xml:1: scheme.paper: the dark half's is #000000; write light.paper");
});

test('what is drawn: a half that states nothing takes the other\'s, turned between paper and ink', () => {
  const [paper, ink] = [0xf4f4f4, 0x161616];
  assert.equal(o.flip(0xffffff, paper, ink), 0x161616);
  assert.equal(o.flip(0x000000, paper, ink), 0xf4f4f4);
  assert.equal(o.flip(0xe8123f, paper, ink), 0xe8123f, 'a colour stays');
  assert.equal(o.unflip(o.flip(0x808080, paper, ink), paper, ink), 0x7f7f7f, 'the way back is approximate');
  const t = o.resolve(over('minimal', '<view name="list"><element name="scrollbar" thumb="#ffffff"/><element name="separator" light.stops="#000000 0, #e8123f 100"/></view>'));
  const d = o.drawn(t);
  const s = t.schemes[0];
  assert.deepEqual(d.theme.sb_thumb, [0xffffff, o.flip(0xffffff, s.paper, s.ink)]);
  assert.deepEqual(d.theme.sep, [[[0, o.unflip(0, s.paper, s.ink)], [100, 0xe8123f]], [[0, 0], [100, 0xe8123f]]]);
  assert.deepEqual([d.schemes[0][0].paper, d.schemes[0][0].ink, d.schemes[0][1].paper], [0, 0xffffff, s.paper]);
});

test('derive="gloss" gives an accent with no band Classic Blue\'s, turned to its tone', () => {
  const blue = data.gloss.stops[2][1];
  assert.equal(o.turn(blue, data.accents[4].tones[0]), data.accents[4].tones[0], 'the 38 % stop becomes the tone');
  const t = o.resolve(over('minimal', `<colorSchemes accents="${data.accents.map((a) => a.name).join(' ')}" derive="gloss"/><colorScheme name="plum" sel.stops="#111111 0, #222222 100"/>`));
  assert.deepEqual(t.schemes[6].sel, [[0, 0x111111], [100, 0x222222]], 'a stated band is kept');
  assert.deepEqual(t.schemes[4].sel.map((x) => x[0]), data.gloss.stops.map((x) => x[0]));
  assert.equal(t.schemes[4].sel[2][1], data.accents[4].tones[0]);
  assert.deepEqual(t.schemes[4].light.sel, t.schemes[4].sel, 'the band is both halves\'');
});

// ---- a theme to edit ----

test('a new theme over each built-in is one line of its own and builds', () => {
  for (const b of data.themes) {
    const t = o.newTheme({ extends: b.id, id: 'dusk', name: 'Dusk' });
    assert.equal(t.index, data.themes.length);
    assert.deepEqual(o.problems(t), [], b.id);
    const r = o.resolve(t);
    for (const k of o.keys.filter((x) => x.path !== 'pages.own.art_final' && !x.path.startsWith('scheme.'))) assert.deepEqual(r[k.field], b.resolved[k.field], `${b.id} ${k.path}`);
    assert.deepEqual(r.opts, b.resolved.opts);
  }
  assert.equal(o.write(fresh()), '<theme format="1" id="dusk" name="Dusk" index="4" extends="minimal">\n</theme>\n');
  assert.equal(fresh('classic-light').values['pages.own.art_final'], 0, 'what only the theme named classic-light may have');
  for (const id of ['modern', 'classic-modern']) {
    assert.equal(o.write(fresh(id)), `<theme format="1" id="dusk" name="Dusk" index="4" extends="${id}">\n</theme>\n`, `${id}: a flat painter's art_final is any theme's`);
    assert.equal(o.resolve(fresh(id)).art_final, 1);
  }
});

test('a new theme needs an id, a name and a base the tool takes', () => {
  refused(() => o.newTheme({ extends: 'minimal', id: 'Dusk', name: 'Dusk' }), 'id: expected [a-z][a-z0-9_-]*');
  refused(() => o.newTheme({ extends: 'minimal', id: 'dusk', name: '' }), 'name: expected 1..48 bytes, no control characters');
  refused(() => o.newTheme({ extends: 'minimal', id: 'dusk', name: 'é'.repeat(25) }), 'name: expected 1..48 bytes, no control characters');
  assert.equal(o.newTheme({ extends: 'minimal', id: 'dusk', name: 'é'.repeat(24) }).name.length, 24);
  refused(() => o.newTheme({ extends: 'minimal', id: 'dusk', name: 'Dusk', index: 10 }), 'index: expected a digit');
  refused(() => o.newTheme({ extends: 'nothing', id: 'dusk', name: 'Dusk' }), 'extends unknown theme nothing');
  const t = fresh();
  o.rename(t, { name: 'Dusk & Dawn', id: 'dusk-2' });
  assert.match(o.write(t), /id="dusk-2" name="Dusk &amp; Dawn"/);
  assert.equal(o.read(o.write(t)).name, 'Dusk & Dawn');
});

test('set states a value in the tool\'s terms, however it is given', () => {
  const t = fresh();
  o.set(t, 'list.selection.painter', 'bar');
  o.set(t, 'list.icons.mono', false);
  o.set(t, 'list.row.title_px', 30);
  o.set(t, 'home.pane.shadow', '#0A0B0C');
  o.set(t, 'bar.battery.stops', [[0, 0x101010], [100, '#ffffff']]);
  o.set(t, 'list.scrollbar.thumb', 0x6e7380);
  o.set(t, 'list.scrollbar.thumb', '#8f98a8', 'light');
  assert.deepEqual(t.values, { 'list.selection.painter': 2, 'list.icons.mono': 0, 'list.row.title_px': 30, 'home.pane.shadow': 0x0a0b0c,
                               'bar.battery.stops': [[0, 0x101010], [100, 0xffffff]], 'list.scrollbar.thumb': 0x6e7380 });
  assert.deepEqual(t.light, { 'list.scrollbar.thumb': 0x8f98a8 });
  assert.equal(o.get(t, 'list.row.title_px'), 30);
  assert.equal(o.get(t, 'list.scrollbar.thumb', 'light'), 0x8f98a8);
  assert.equal(o.get(t, 'list.row.meta_px'), undefined, 'not its own: the base\'s');
  const r = o.resolve(t);
  assert.deepEqual([r['painter[PAINT_SELECTION]'], r.icons_mono, r['font_px[ROLE_TITLE]'], r.sb_thumb, r.light.sb_thumb], [2, 0, 30, 0x6e7380, 0x8f98a8]);
});

test('set refuses what the key does not take, and leaves the theme as it was', () => {
  const t = fresh();
  o.set(t, 'list.row.title_px', 30);
  const before = JSON.stringify(t);
  refused(() => o.set(t, 'list.row.title_px', 65), 'list.row.title_px: 65 outside 0..64');
  refused(() => o.set(t, 'list.row.title_px', 1.5), 'list.row.title_px: expected an integer');
  refused(() => o.set(t, 'list.row.title_px', 30, 'light'), 'list.row.title_px: one value for both halves');
  refused(() => o.set(t, 'list.selection.painter', 'glow'), 'list.selection.painter: unknown value glow');
  refused(() => o.set(t, 'list.selection.painter', 7), 'list.selection.painter: unknown value 7');
  refused(() => o.set(t, 'list.scrollbar.thumb', 0), 'list.scrollbar.thumb: #000000 reads as unset; use #010101');
  refused(() => o.set(t, 'list.row.size', 3), 'unknown key list.row.size');
  refused(() => o.set(t, 'scheme.fill', '#101010'), /^scheme.fill is not a view's value/);
  assert.equal(JSON.stringify(t), before);
  const minimal = o.read(builtin('minimal').text);
  refused(() => o.set(minimal, 'home.rows.top', 9), 'home.rows.top comes from patch/offsets.inc');
});

test('unset gives a value back to the base, one half or both', () => {
  const t = fresh();
  o.set(t, 'list.scrollbar.thumb', '#6e7380');
  o.set(t, 'list.scrollbar.thumb', '#8f98a8', 'light');
  o.unset(t, 'list.scrollbar.thumb', 'light');
  assert.deepEqual([t.values, t.light], [{ 'list.scrollbar.thumb': 0x6e7380 }, {}]);
  o.set(t, 'list.scrollbar.thumb', '#8f98a8', 'light');
  o.unset(t, 'list.scrollbar.thumb');
  assert.deepEqual([t.values, t.light], [{}, {}]);
  assert.equal(o.write(t), o.write(fresh()));
});

test('a scheme\'s values: every scheme\'s, then a named one\'s over them', () => {
  const t = fresh();
  o.setScheme(t, null, 'muted', '#949294');
  o.setScheme(t, null, 'paper', '#ffffff');
  o.setScheme(t, 'cobalt', 'muted', '#101010');
  o.setScheme(t, 'cobalt', 'scheme.sel.text', '#fefefe', 'light');
  o.setScheme(t, 'cobalt', 'card', true);
  const r = o.resolve(t);
  assert.deepEqual([r.schemes[0].muted, r.schemes[4].muted, r.schemes[4].light.sel_text, r.schemes[4].card, r.schemes[0].card], [0x949294, 0x101010, 0xfefefe, 1, 0]);
  assert.ok(r.schemes.every((s) => s.paper === 0xffffff));
  assert.match(o.write(t), /<colorScheme muted="#949294" light.paper="#ffffff"\/>\n  <colorScheme name="cobalt" card="1" muted="#101010" light.sel.text="#fefefe"\/>/);
  refused(() => o.setScheme(t, 'cobalt', 'muted', '#101010', 'light'), 'scheme.muted: one value for both halves');
  refused(() => o.setScheme(t, 'mauve', 'muted', '#101010'), 'unknown scheme mauve');
  refused(() => o.setScheme(t, 'cobalt', 'sparkle', '1'), 'unknown key scheme.sparkle');
  refused(() => o.setScheme(t, null, 'paper', '#ff0000ff'), 'scheme.paper: expected #rrggbb');
  o.unsetScheme(t, 'cobalt', 'muted');
  o.unsetScheme(t, 'cobalt', 'sel.text');
  o.unsetScheme(t, 'cobalt', 'card');
  assert.deepEqual(t.schemes.named, [], 'an entry with nothing left to say goes');
  assert.equal(o.resolve(t).schemes[4].muted, 0x949294);
});

test('a scheme of the theme\'s own comes after the accents and is offered', () => {
  const t = fresh();
  o.addScheme(t, { name: 'dusk', base: 'plum', label: 'Dusk' });
  o.setScheme(t, 'dusk', 'sel.stops', [[0, 0x302040], [100, 0x201030]]);
  const r = o.resolve(t);
  assert.deepEqual(o.schemeNames(r), [...o.accentNames, 'dusk']);
  const s = r.schemes[data.accents.length];
  assert.deepEqual([s.name, s.label, s.base, s.sel], ['dusk', 'Dusk', 6, [[0, 0x302040], [100, 0x201030]]]);
  assert.equal(s.fill, builtin('minimal').resolved.schemes[6].fill, 'it starts from its base accent\'s values');
  assert.equal(r.accents, 2 ** (data.accents.length + 1) - 1);
  refused(() => o.addScheme(t, { name: 'dusk', base: 'plum', label: 'Again' }), 'scheme dusk declared twice');
  refused(() => o.addScheme(t, { name: 'cobalt', base: 'plum', label: 'Cobalt' }), 'scheme cobalt declared twice');
  refused(() => o.addScheme(t, { name: 'dawn', base: 'mauve', label: 'Dawn' }), 'dawn: unknown base mauve');
  refused(() => o.addScheme(t, { name: 'dawn', base: 'plum', label: '' }), 'dawn: an own scheme needs a label');
  refused(() => o.addScheme(t, { name: 'Dawn 2', base: 'plum', label: 'Dawn' }), "a scheme's name: expected [a-z][a-z0-9-]*");
  o.offer(t, ['graphite', 'dusk']);
  assert.equal(o.resolve(t).accents, 1 + 2 ** data.accents.length);
  refused(() => o.offer(t, ['graphite']), 'scheme dusk is not in colorSchemes');
  refused(() => o.offer(t, ['graphite', 'dusk', 'mauve']), 'unknown scheme mauve');
  o.removeScheme(t, 'dusk');
  assert.deepEqual([t.schemes.named, t.schemes.offered], [[], ['graphite']]);
  o.offer(t, null);
  assert.equal(o.write(t), o.write(fresh()));
});

test('a geometry set of the theme\'s own starts from another and stays in its ranges', () => {
  const t = fresh();
  o.addGeometry(t, 'compact', null, { pitch: 60, body: 56, text_art_inset: 2 });
  o.useGeometry(t, 'compact');
  let r = o.resolve(t);
  assert.deepEqual(r.geoms.compact, { ...data.geometry.sets.ipod, name: 'compact', pitch: 60, body: 56, text_art_inset: 2 });
  assert.equal(r.geom_set, 'compact');
  assert.deepEqual(o.geometryOf(t, 'compact').fields.body, { value: 56, lo: 24, hi: 60 }, 'a body fits its pitch');
  assert.deepEqual(o.geometryOf(t, 'compact').fields.text_art_inset, { value: 2, lo: 0, hi: 2 }, 'and the art its body');
  assert.deepEqual(o.geometryOf(t, 'ipod').fields.bar, { value: 30, lo: 26, hi: 40 });
  refused(() => o.setGeometry(t, 'compact', { pitch: 50 }), 'geometry.body: 56 outside 24..50');
  o.setGeometry(t, 'compact', { pitch: 58 });
  refused(() => o.setGeometry(t, 'compact', { bar: 41 }), 'geometry.bar: 41 outside 26..40');
  refused(() => o.setGeometry(t, 'compact', { depth: 3 }), 'unknown key geometry.depth');
  refused(() => o.setGeometry(t, 'compact', { pitch: 'tall' }), 'geometry.pitch: expected an integer');
  refused(() => o.setGeometry(t, 'ipod', { pitch: 50 }), 'ipod is not a geometry set this theme declares');
  refused(() => o.setGeometry(t, 'compact', { text_art_inset: null }), 'geometry.text_art_inset: 8 outside 0..2'); // back to the built-in's
  refused(() => o.setGeometry(t, 'compact', { pitch: 80 }), 'geometry.pitch: 80 outside 28..78');
  assert.equal(o.resolve(t).geoms.compact.pitch, 58, 'a refused change changes nothing');
  o.addGeometry(t, 'compact-text', 'compact', { text_art: 0, text_art_inset: 0 });
  r = o.resolve(t);
  assert.deepEqual([r.geoms['compact-text'].pitch, r.geoms['compact-text'].text_art, r.geoms.compact.text_art], [58, 0, 52]);
  refused(() => o.addGeometry(t, 'compact'), 'geometry set compact declared twice');
  refused(() => o.addGeometry(t, 'ipod'), 'geometry set ipod declared twice');
  refused(() => o.addGeometry(t, 'n'), 'geometry.name: expected [a-z][a-z0-9-]*, 1..24 bytes, not n');
  refused(() => o.addGeometry(t, 'wide', 'nowhere'), 'unknown geometry set "nowhere"');
  refused(() => o.useGeometry(t, 'nowhere'), 'unknown geometry set "nowhere"');
  refused(() => o.removeGeometry(t, 'compact'), 'unknown geometry set "compact"'); // compact-text stands on it, and the theme boots it
  o.useGeometry(t, null);
  o.removeGeometry(t, 'compact-text');
  o.removeGeometry(t, 'compact');
  assert.equal(o.write(t), o.write(fresh()));
  refused(() => o.addGeometry(fresh('classic-light'), 'classic-light-text'), 'geometry set classic-light-text declared twice'); // its base's
});

test('every geometry range in official.json works out to a number for every set', () => {
  const classic = builtin('classic-light').resolved.geoms;
  for (const g of [data.geometry.sets.ipod, ...Object.values(classic)]) {
    assert.deepEqual(o.setFaults(g), []);
    for (const f of data.geometry.fields) {
      const [lo, hi] = o.geometryBounds(g, f.name);
      assert.ok(Number.isInteger(lo) && Number.isInteger(hi) && lo <= g[f.name] && g[f.name] <= hi, `${g.name}.${f.name}`);
    }
  }
  assert.deepEqual(o.geometryBounds(classic['classic-light'], 'set_rows'), [1, 9]);
  assert.deepEqual(o.setFaults({ ...data.geometry.sets.ipod, pitch: 30, bar: 99 }).slice(0, 2), ['geometry.bar: 99 outside 26..40', 'geometry.body: 68 outside 24..30']);
});

test('a theme\'s options are its base\'s until it changes one; then all are its own', () => {
  const t = fresh();
  assert.equal(t.options, null);
  assert.deepEqual(o.options(t).map((x) => x.setting ?? x.key), ['STATUSBAR', 'time_title', 'SHOWQ2POD', 'light', 'accent', 'corners', 'home', 'shortcut', 'battery', 'np_layout']);
  assert.deepEqual(o.options(t)[4], { setting: 'accent', key: 'MINIMAL_ACCENT', default: 'graphite', preset: 'graphite' });
  o.setOption(t, 'light', { preset: 'on', keep: null });
  o.setOption(t, 'battery', { values: ['icon', 'inside'], default: 'inside' });
  const base = builtin('minimal').resolved;
  const r = o.resolve(t);
  assert.equal(r.opts.length, base.opts.length);
  assert.deepEqual(r.opts[3], { ...base.opts[3], preset: 1, keep: -1 });
  assert.deepEqual(r.opts[8], { ...base.opts[8], def: 3, values: 0b1001 });
  assert.deepEqual(r.opts.filter((x, i) => i !== 3 && i !== 8), base.opts.filter((x, i) => i !== 3 && i !== 8), 'the rows it did not touch are as they were');
  refused(() => o.setOption(t, 'light', { preset: 'dim' }), 'light: unknown value dim');
  refused(() => o.setOption(t, 'battery', { default: 'percent' }), 'battery: default percent is not in values');
  refused(() => o.setOption(t, 'volume', { preset: 'on' }), 'the theme has no option volume');
  refused(() => o.setOption(t, 'accent', { key: 'THEME' }), "THEME: the payload's key");
  refused(() => o.setOption(t, 'light', { label: 'Light' }), 'light: a payload setting takes no label');
  refused(() => o.setOption(t, 'light', { colour: 'red' }), 'unknown key option.colour');
  refused(() => o.addOption(t, { setting: 'brightness' }), 'unknown setting brightness');
  o.setOption(t, 'accent', { key: 'DUSK_ACCENT' });
  assert.equal(o.resolve(t).accent_key, 'DUSK_ACCENT');
  o.inheritOptions(t);
  assert.equal(o.write(t), o.write(fresh()));
});

test('the base\'s options, made the theme\'s own unchanged, are the same options', () => {
  for (const b of data.themes) {
    const t = o.newTheme({ extends: b.id, id: 'dusk', name: 'Dusk' });
    o.addOption(t, { setting: 'np_layout' }, 0);
    o.removeOption(t, 'np_layout');
    if (b.resolved.opts.some((x) => x.setting === 'SETTING_NPCENTRED')) o.addOption(t, { setting: 'np_layout' });
    assert.notEqual(t.options, null);
    const r = o.resolve(t);
    assert.deepEqual(r.opts, b.resolved.opts, b.id);
    assert.equal(r.accent_key, b.resolved.accent_key);
  }
});

test('an option of the theme\'s own names its values, each a geometry set or none', () => {
  const t = fresh('classic-light');
  o.addGeometry(t, 'roomy', 'classic-light', { pitch: 36, body: 36 });
  o.addOption(t, { key: 'ROOMY', label: 'Roomy Rows', default: 'On', choices: [{ label: 'Off', set: 'classic-light' }, { label: 'On', set: 'roomy' }] });
  const added = o.resolve(t).opts.at(-1);
  assert.deepEqual(added, { setting: 'SETTING_OWN', key: 'ROOMY', label: 'Roomy Rows', names: ['Off', 'On'], sets: ['classic-light', 'roomy'], def: 1, preset: -1, keep: -1, values: 0 });
  assert.match(o.write(t), /<option key="ROOMY" label="Roomy Rows" default="On">\n    <value label="Off" set="classic-light"\/>\n    <value label="On" set="roomy"\/>\n  <\/option>/);
  refused(() => o.setOption(t, 'ROOMY', { choices: [{ label: 'Off', set: 'classic-light' }, { label: 'On' }] }), 'ROOMY: every value names a set, or none does');
  refused(() => o.setOption(t, 'ROOMY', { choices: [{ label: 'Off' }, { label: 'On' }] }), 'ROOMY: a plain choice the payload does not read (PLAIN_KEYS)');
  refused(() => o.setOption(t, 'ROOMY', { choices: [{ label: 'On', set: 'roomy' }] }), 'ROOMY: 2 to 10 values expected');
  refused(() => o.setOption(t, 'ROOMY', { default: 'Sometimes' }), 'ROOMY: unknown value Sometimes');
  refused(() => o.setOption(t, 'ROOMY', { label: 'x'.repeat(25) }), 'ROOMY: label expected 1..24 bytes, no control characters');
  refused(() => o.addOption(t, { key: 'roomy2', label: 'Roomy', choices: [{ label: 'Off' }, { label: 'On' }] }), 'option.key: expected [A-Z][A-Z0-9_]*');
});

// ---- writing and reading ----

test('a written theme holds its own values only, in one order and layout', () => {
  const t = fresh('classic-light');
  o.set(t, 'playing.layout', 'centred');
  o.set(t, 'list.scrollbar.thumb', '#8f98a8', 'light');
  o.set(t, 'list.scrollbar.thumb', '#6e7380');
  o.set(t, 'list.selection.painter', 'bar');
  o.setScheme(t, 'plum', 'bar.stops', [[0, 0x1c1c1c], [100, 0x1c1c1c]]);
  o.setScheme(t, null, 'ink', '#101010');
  o.offer(t, ['classic-blue', 'plum', 'graphite'], true);
  o.setOption(t, 'light', { preset: 'off' });
  o.inheritOptions(t);
  assert.equal(o.write(t), `<theme format="1" id="dusk" name="Dusk" index="4" extends="classic-light">
  <colorScheme light.ink="#101010"/>
  <colorScheme name="plum" bar.stops="#1c1c1c 0, #1c1c1c 100"/>
  <colorSchemes accents="classic-blue plum graphite" derive="gloss"/>
  <view name="list">
    <element name="selection" painter="bar"/>
    <element name="scrollbar" dark.thumb="#6e7380" light.thumb="#8f98a8"/>
  </view>
  <view name="pages">
    <element name="own" art_final="0"/>
  </view>
  <view name="playing" layout="centred"/>
</theme>
`);
});

test('what is written reads back as the same theme, and writes the same again', () => {
  const t = fresh('classic-light');
  o.set(t, 'home.pane.shadow_a', [9, 8, 7]);
  o.set(t, 'playing.scrubber.dark_track', [0xff101010, 0x80202020]);
  o.set(t, 'motion.step.easing', 'bounce_out');
  o.setScheme(t, null, 'sel.text', '#fefefe', 'light');
  o.setScheme(t, 'classic-blue', 'sel.top', '#123456');
  o.addGeometry(t, 'roomy', 'classic-light', { pitch: 36, body: 36 });
  o.setOption(t, 'STATUSBAR', { preset: 'Classic' });
  o.rename(t, { name: 'A "quoted" <name> & more' });
  const text = o.write(t);
  assert.deepEqual(o.read(text), t);
  assert.equal(o.write(o.read(text)), text);
  assert.ok(new TextEncoder().encode(text).length < official.MAX_BYTES);
});

test('each built-in survives reading and writing: the same theme, the same values', () => {
  for (const b of data.themes) {
    const t = o.read(b.text);
    const text = o.write(t);
    assert.deepEqual(o.read(text), t, b.id);
    assert.equal(o.write(o.read(text)), text);
    assert.deepStrictEqual({ ...o.resolve(text), line: 0 }, { ...b.resolved, line: 0 }, b.id);
    assert.deepEqual(o.problems(t), []);
  }
});

test('reading keeps what a file states, however it orders it', () => {
  const text = over('minimal', '<option setting="accent" key="T_ACCENT" default="plum"/><view name="list"><element name="row" title_px="20"/></view>'
    + '<colorScheme name="plum" muted="#111111" fill="#222222"/><colorScheme muted="#333333"/><view name="list"><element name="row" title_px="22" meta_px="12"/></view>'
    + '<colorSchemes accents="plum"/><colorScheme name="own" base="plum" label="Own"/><geometry set="ipod"/>');
  const t = o.read(text);
  assert.deepEqual(t.values, { 'list.row.title_px': 22, 'list.row.meta_px': 12 });
  assert.deepEqual(t.schemes, { all: { values: { muted: 0x333333 }, light: {} },
                                named: [{ name: 'plum', values: { fill: 0x222222 }, light: {} }, { name: 'own', base: 'plum', label: 'Own', values: {}, light: {} }],
                                offered: ['plum', 'own'], derive: false });
  assert.deepEqual(t.options, [{ setting: 'accent', key: 'T_ACCENT', default: 'plum' }]);
  assert.equal(t.geometry.set, 'ipod');
  assert.deepStrictEqual({ ...o.resolve(t), line: 0 }, { ...o.resolve(text), line: 0 });
});

test('reading refuses a file the tool refuses, and one whose order it cannot keep', () => {
  refused(() => o.read(over('minimal', '<view name="list"><element name="row" title_px="99"/></view>')), 't/theme.xml:1: list.row.title_px: 99 outside 0..64');
  refused(() => o.read('<theme format="1" id="t">'), 'theme.xml:1: unclosed <theme>');
  // own copies cobalt's fill when it is made; cobalt's muted comes after
  const ordered = over('minimal', '<colorScheme name="cobalt" fill="#111111"/><colorScheme name="own" base="cobalt" label="Own"/><colorScheme name="cobalt" muted="#222222"/>');
  assert.equal(o.resolve(ordered).schemes.at(-1).muted, builtin('minimal').resolved.schemes[4].muted);
  refused(() => o.read(ordered), /its statements depend on their order/);
});

// ---- what the build would refuse ----

test('the built-ins have no problems, and one changed for the worse is caught in the others\' company', () => {
  for (const b of data.themes) assert.deepEqual(o.problems(b.text), []);
  const broken = builtin('minimal').text.replace('index="0"', 'index="4"');
  assert.deepEqual(tools(o.problems(broken)), ['classic-light/theme.xml:4: index 1, expected 0', 'modern/theme.xml:3: index 2, expected 1',
                                                   'classic-modern/theme.xml:6: index 3, expected 2', 'minimal/theme.xml:3: index 4, expected 3']);
});

test('a file that cannot be read is one problem, in plain words', () => {
  assert.deepEqual(o.problems('<theme format="1" id="dusk" name="Dusk" index="3">\n  <view name="list" title="a & b"/>\n</theme>'),
                   [{ message: 'An attribute uses "&" other than as &amp; &lt; &gt; or &quot;.', tool: 'dusk/theme.xml:2: unknown entity', file: 'dusk/theme.xml', line: 2 }]);
  assert.deepEqual(tools(o.problems('nothing')), ['theme/theme.xml:1: text between tags']);
  const far = o.problems(over('minimal', '\n<view name="list">\n<element name="row" title_px="99"/></view>'));
  assert.deepEqual(far.map((p) => [p.tool, p.message]), [['t/theme.xml:3: list.row.title_px: 99 outside 0..64', 'list.row.title_px is 99; it must be from 0 to 64.']]);
});

test('whole-theme rules are all listed, where the tool stops at the first', () => {
  const t = fresh();
  o.set(t, 'list.scrollbar.w', 4);
  o.set(t, 'list.scrollbar.top', 10);
  const found = o.problems(t);
  assert.deepEqual(tools(found), ['dusk/theme.xml:1: list.scrollbar: top 10 is under the glass (inset 42 > right 0 + 1)',
                                  'dusk/theme.xml:1: list.scrollbar: bottom 0 is under the glass (inset 80 > right 0 + 1)', 'dusk/theme.xml:1: list.scrollbar: top 10 is not above bottom 0',
                                  'dusk/theme.xml:1: list.scrollbar: no min', 'dusk/theme.xml:1: list.scrollbar: no thumb colour']);
  assert.ok(found.every((p) => p.message !== p.tool && /scroll bar/.test(p.message)));
  o.set(t, 'list.scrollbar.top', 59);
  o.set(t, 'list.scrollbar.bottom', 261);
  o.set(t, 'list.scrollbar.right', 2);
  o.set(t, 'list.scrollbar.min', 16);
  o.set(t, 'list.scrollbar.thumb', '#8f98a8', 'light');
  assert.deepEqual(o.problems(t), []);
});

test('what a theme owes the other themes is a problem too', () => {
  const t = fresh();
  o.addScheme(t, { name: 'dusk', base: 'plum', label: 'Dusk' });
  assert.deepEqual(tools(o.problems(t)), ['dusk/theme.xml:1: accent key MINIMAL_ACCENT is minimal\'s, with other colorSchemes or default']);
  assert.match(o.problems(t)[0].message, /Give its Accent option a key of its own/);
  o.setOption(t, 'accent', { key: 'DUSK_ACCENT' });
  assert.deepEqual(o.problems(t), []);
  o.removeOption(t, 'corners');
  assert.deepEqual(tools(o.problems(t)), ['dusk/theme.xml:1: dusk runs on minimal\'s set, with other options', 'dusk/theme.xml:1: dusk runs on modern\'s set, with other options']);
  o.addGeometry(t, 'compact', null, { pitch: 60, body: 56, text_art_inset: 2 });
  o.useGeometry(t, 'compact');
  assert.deepEqual(o.problems(t), [], 'on a set of its own, its rows are its own');
  o.rename(t, { index: 5 });
  assert.deepEqual(tools(o.problems(t)), ['dusk/theme.xml:1: index 5, expected 4']);
  o.rename(t, { index: 4 });
  o.setOption(t, 'STATUSBAR', { choices: ['Theme', 'Minimal', 'Modern', 'Classic', 'Dusk'].map((label) => ({ label })) });
  assert.deepEqual(tools(o.problems(t)), ['dusk/theme.xml:1: STATUSBAR is minimal\'s, with other values or default']);
});

test('a theme over Classic cannot keep what is Classic\'s alone', () => {
  const t = fresh('classic-light');
  o.unset(t, 'pages.own.art_final');
  assert.deepEqual(tools(o.problems(t)), ["dusk/theme.xml:1: pages.own: art_final is for classic-light's own images and the flat look's only"]);
  o.set(t, 'pages.own.art_final', 0);
  o.addScheme(t, { name: 'dusk', base: 'plum', label: 'Dusk' });
  assert.deepEqual(tools(o.problems(t)).slice(0, 1), ['dusk/theme.xml:1: 11 accents, at most 10']);
  o.removeScheme(t, 'dusk');
  o.addGeometry(t, 'roomy', 'classic-light', { pitch: 36, body: 36, bar: 28, bar_px: 22 });
  o.useGeometry(t, 'roomy');
  assert.deepEqual(tools(o.problems(t)), ["dusk/theme.xml:1: bar.title.font_size 21 is not set roomy's bar_px 22",
                                         "dusk/theme.xml:1: ROWART: default On boots classic-light, the theme's geometry is roomy",
                                         "dusk/theme.xml:1: ROWART: set classic-light-text has a 26 px bar, the theme's is 28",
                                         "dusk/theme.xml:1: ROWART: set classic-light has a 26 px bar, the theme's is 28"]);
});

test('more themes than the built-ins can be checked together', () => {
  const a = fresh();
  const b = o.newTheme({ extends: 'modern', id: 'dawn', name: 'Dawn', index: 5 });
  assert.deepEqual(o.problems(b), [{ message: "The themes' indexes must count up from 0 with none missing: this one has 5 where 4 is due.", tool: 'dawn/theme.xml:1: index 5, expected 4', file: 'dawn/theme.xml', line: 1 }]);
  assert.deepEqual(o.problems(b, [{ folder: 'dusk', source: o.write(a) }]), []);
  o.rename(b, { id: 'dusk' });
  assert.deepEqual(tools(o.problems(o.write(b), [{ folder: 'elsewhere', source: o.write(a) }])), ["elsewhere/theme.xml:1: id dusk is dusk/theme.xml's too"]);
});

// ---- the flat look and Classic Modern ----

test('Classic Modern is Classic but for the flat look\'s painters and keys', () => {
  assert.deepEqual(o.builtinIds, ['minimal', 'classic-light', 'modern', 'classic-modern']);
  const c = builtin('classic-light').resolved;
  const cm = o.resolve(builtin('classic-modern').text);
  const differs = Object.keys(cm).filter((k) => JSON.stringify(cm[k]) !== JSON.stringify(c[k]));
  assert.deepEqual(differs.sort(), ['date_gap', 'id', 'index', 'light', 'line', 'name', 'page_fill', 'painter[PAINT_CONFIRM]', 'painter[PAINT_PAGES]',
                                    'painter[PAINT_VOLUME]', 'pane_count_px', 'qs_ground'].sort());
  assert.deepEqual([cm['painter[PAINT_PAGES]'], cm['painter[PAINT_CONFIRM]'], cm['painter[PAINT_VOLUME]'], cm.art_final], [3, 3, 2, 1]);
  assert.deepEqual([cm.qs_ground, cm.date_gap, cm.pane_count_px], [0xf2f2f7, 6, 17]);
});

test('the flat painters: volume, confirm and own pages take flat, the last two classic-light+flat (both bits)', () => {
  assert.deepEqual(o.key('volume.panel.painter').choices, ['stock', 'classic-light', 'flat']);
  for (const p of ['dialog.confirm.painter', 'pages.own.painter']) assert.deepEqual(o.key(p).choices, ['stock', 'classic-light', 'flat', 'classic-light+flat'], p);
  const t = fresh();
  o.set(t, 'pages.own.painter', 'classic-light+flat');
  o.set(t, 'dialog.confirm.painter', 'flat');
  o.set(t, 'volume.panel.painter', 'flat');
  const r = o.resolve(t);
  assert.deepEqual([r['painter[PAINT_PAGES]'], r['painter[PAINT_CONFIRM]'], r['painter[PAINT_VOLUME]']], [3, 2, 2]);
  assert.match(o.write(t), /<element name="panel" painter="flat"\/>[\s\S]*<element name="confirm" painter="flat"\/>[\s\S]*<element name="own" painter="classic-light\+flat"\/>/);
  assert.deepEqual(o.read(o.write(t)), t);
  refused(() => o.set(t, 'volume.panel.painter', 'classic-light+flat'), 'volume.panel.painter: unknown value classic-light+flat');
  refused(() => o.read(over('minimal', '<view name="volume"><element name="panel" painter="classic-light+flat"/></view>')),
          't/theme.xml:1: volume.panel.painter: unknown value classic-light+flat');
});

test('Quick Settings\' ground and Set Date\'s gap are the flat look\'s, and its art_final is any theme\'s', () => {
  const t = fresh();
  o.set(t, 'pages.quick.light_ground', '#f2f2f7');
  o.set(t, 'pages.date.gap', 6);
  assert.deepEqual(tools(o.problems(t)), ["dusk/theme.xml:1: pages.quick.light_ground and pages.date.gap are the flat look's"]);
  assert.match(o.problems(t)[0].message, /set pages\.own\.painter to flat or classic-light\+flat/);
  refused(() => o.set(t, 'pages.date.gap', 21), 'pages.date.gap: 21 outside 0..20');
  refused(() => o.set(t, 'pages.quick.light_ground', '#f2f2f7', 'light'), 'pages.quick.light_ground: one value for both halves');
  for (const painter of ['flat', 'classic-light+flat']) {
    o.set(t, 'pages.own.painter', painter);
    assert.deepEqual(o.problems(t), [], painter);
  }
  o.set(t, 'pages.own.art_final', 1);
  assert.deepEqual(o.problems(t), [], 'a flat theme of any id');
  o.set(t, 'pages.own.painter', 'classic-light');
  assert.deepEqual(tools(o.problems(t)), ["dusk/theme.xml:1: pages.own: art_final is for classic-light's own images and the flat look's only",
                                         "dusk/theme.xml:1: pages.quick.light_ground and pages.date.gap are the flat look's"]);
  assert.ok(o.problems(t).every((p) => p.message !== p.tool));
  const u = fresh('modern');
  o.set(u, 'pages.own.painter', 'stock');
  assert.deepEqual(tools(o.problems(u)), ["dusk/theme.xml:1: pages.own: art_final is for classic-light's own images and the flat look's only"], 'Modern\'s art_final without its painter');
});

test('pages.own.fill is final: Classic Modern\'s own pages keep Classic\'s slate in the light half and #1c1c1c on black', () => {
  const t = o.read(builtin('classic-modern').text);
  assert.deepEqual([t.values['pages.own.fill'], t.light['pages.own.fill']], [0x1c1c1c, 0x63717b]);
  assert.deepEqual(o.drawn(o.resolve(t)).theme.page_fill, [0x1c1c1c, 0x63717b]);
  assert.deepEqual(o.drawn(builtin('classic-light').resolved).theme.page_fill, [0, 0], 'unset: Home pane\'s colour');
  const u = fresh('classic-modern');
  o.set(u, 'pages.own.fill', '#202020', 'light');
  assert.match(o.write(u), /<element name="own" light\.fill="#202020"\/>/);
  assert.deepEqual(o.drawn(o.resolve(u)).theme.page_fill, [0x1c1c1c, 0x202020]);
  refused(() => o.set(u, 'pages.own.fill', '#000000'), 'pages.own.fill: #000000 reads as unset; use #010101');
});

test('Modern\'s and Classic Modern\'s Home pane where no cover shows is flat', () => {
  const m = builtin('modern').resolved;
  const cm = builtin('classic-modern').resolved;
  assert.deepEqual(o.drawn(m).theme.home_pane, [[[0, 0x1c1c1c], [100, 0x1c1c1c]], [[0, 0xf2f2f7], [100, 0xf2f2f7]]]);
  assert.deepEqual([m.pane_icon_x, m.pane_light_a, m.pane_shadow_w, m.pane_note_x, m.pane_note_y, m.pane_count_y, m.pane_count_w, m.pane_count_px],
                   [0, 0, 0, 40, 57, 185, 182, 17]);
  assert.deepEqual(o.drawn(cm).theme.home_pane[1], [[0, 0xf2f2f7], [100, 0xf2f2f7]]);
  assert.equal(cm.pane_icon_x, builtin('classic-light').resolved.pane_icon_x, 'it keeps Classic\'s icon_x: it follows the rows');
  for (const b of data.themes) assert.deepEqual(o.drawn(o.resolve(b.text)), b.drawn, b.id);
});

test('a theme repeating another\'s schemes points at its arrays, as emit() writes them', () => {
  const themes = data.themes.map((b) => b.resolved);
  const a = o.schemeArrays(themes);
  assert.deepEqual(a.written, ['minimal_schemes', 'classic_light_schemes', 'classic_light_light', 'modern_schemes']);
  assert.deepEqual(a.themes, [{ schemes: 'minimal_schemes', light: 'minimal_schemes' }, { schemes: 'classic_light_schemes', light: 'classic_light_light' },
                              { schemes: 'modern_schemes', light: 'modern_schemes' }, { schemes: 'classic_light_schemes', light: 'classic_light_light' }]);
  const t = fresh('classic-modern');
  assert.deepEqual(o.schemeArrays([...themes, o.resolve(t)]).themes.at(-1), { schemes: 'classic_light_schemes', light: 'classic_light_light' });
  o.setScheme(t, 'plum', 'muted', '#123456');
  assert.deepEqual(o.schemeArrays([...themes, o.resolve(t)]).written.slice(4), ['dusk_schemes', 'dusk_light']);
  const u = fresh('modern');
  o.rename(u, { id: 'dusk-2' });
  assert.deepEqual(o.schemeArrays([...themes, o.resolve(u)]).themes.at(-1), { schemes: 'modern_schemes', light: 'modern_schemes' });
});
