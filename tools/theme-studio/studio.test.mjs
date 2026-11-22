// node --test studio.test.mjs
// The editor page's own logic (studio.js, the part with no page in it): names and grouping, what the preview
// shows, where a value comes from, undo and redo, starting a theme, the export, and where a problem points.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import official from './official.js';
import studio from './studio.js';

const data = JSON.parse(readFileSync(new URL('./official.json', import.meta.url), 'utf8'));
const o = official.open(data);
const fresh = (base = 'minimal') => o.newTheme({ extends: base, id: 'dusk', name: 'Dusk' });
const stops = (...list) => list;

// ---- names and grouping ----

test('every schema key is in one group and one section, once, with a label of its own', () => {
  const tree = studio.groups(o);
  const listed = tree.flatMap((g) => g.sections.flatMap((s) => s.keys.map((k) => k.path)));
  assert.equal(listed.length, data.schema.length);
  assert.deepEqual([...listed].sort(), data.schema.map((k) => k.path).sort());
  assert.equal(new Set(listed).size, listed.length, 'a key is listed twice');
  // the label table itself: no key twice, none the schema does not have, each with words
  const paths = studio.LABELS.map((row) => row[0]);
  assert.equal(new Set(paths).size, paths.length);
  assert.deepEqual(paths.filter((p) => !o.key(p)), []);
  assert.deepEqual(data.schema.map((k) => k.path).filter((p) => !paths.includes(p)), [], 'a schema key has no label');
  for (const [path, label, hint] of studio.LABELS) {
    assert.ok(label.length > 1 && label !== path && !label.includes('_'), `${path}: a label in plain words`);
    assert.equal(typeof hint, 'string');
    assert.equal(studio.label(path), label);
  }
  // labels are told apart within a section
  for (const g of tree) for (const s of g.sections) assert.equal(new Set(s.keys.map((k) => k.label)).size, s.keys.length, `${s.id}: two keys with one label`);
});

test('a key is grouped by its view and element, and every section has a heading', () => {
  const tree = studio.groups(o);
  const where = new Map(tree.flatMap((g) => g.sections.flatMap((s) => s.keys.map((k) => [k.path, [g.id, s.id]]))));
  assert.deepEqual(where.get('bar.battery.low'), ['bar', 'bar.battery']);
  assert.deepEqual(where.get('home.pane.stops'), ['home', 'home.pane']);
  assert.deepEqual(where.get('settings.values.text'), ['lists', 'settings.values']);
  assert.deepEqual(where.get('playing.layout'), ['playing', 'playing.']);
  assert.deepEqual(where.get('scheme.sel.tall_top'), ['schemes', 'scheme.sel']);
  assert.deepEqual(where.get('scheme.paper'), ['schemes', 'scheme.light']);
  assert.deepEqual(where.get('scheme.muted'), ['schemes', 'scheme.marks']);
  assert.deepEqual(where.get('scheme.bar_light'), ['schemes', 'scheme.bar']);
  assert.deepEqual(where.get('geometry.set'), ['geometry', 'geometry.']);
  for (const k of data.schema) {
    if (k.xml.tag !== 'view') continue;
    assert.equal(where.get(k.path)[1], `${k.xml.view}.${k.xml.element ?? ''}`);
    assert.ok(studio.GROUPS.find((g) => g.id === where.get(k.path)[0]).views.includes(k.xml.view));
  }
  for (const g of tree) for (const s of g.sections) assert.ok(studio.SECTIONS[s.id], `${s.id} has no heading`);
  // Cover Flow's and motion's numbers are folded away under Advanced, and nothing else is
  const advanced = tree.find((g) => g.id === 'advanced');
  assert.ok(advanced.folded);
  assert.deepEqual([...new Set(advanced.sections.flatMap((s) => s.keys.map((k) => k.path.split('.')[0])))].sort(), ['coverflow', 'motion']);
  assert.equal(advanced.sections.reduce((n, s) => n + s.keys.length, 0), 79 + 23);
  assert.deepEqual(tree.filter((g) => g.folded).map((g) => g.id), ['advanced']);
});

test('what the preview shows is DRAWING.md section 11: 127 keys it does not, 113 it does', () => {
  const kinds = data.schema.map((k) => studio.preview(k.path).kind);
  assert.equal(kinds.filter((k) => k === 'no').length, 127);
  assert.equal(kinds.filter((k) => k !== 'no').length, 113);
  for (const k of data.schema) assert.ok(studio.preview(k.path).where.length > 3, k.path);
  // the table names real keys, each once
  const named = studio.PREVIEW.flatMap(([, , prefix, attrs]) => attrs.split(' ').map((a) => prefix + a));
  assert.deepEqual(named.filter((p) => !o.key(p)), []);
  assert.equal(new Set(named).size, named.length);
  assert.equal(named.length + 79 + 23, data.schema.length);
  const no = ['list.icons.badge_muted', 'list.icons.addon_mono', 'list.icons.badge_ink', 'home.pane.svc_x', 'home.pane.svc_y', 'home.pane.svc_px',
    'playing.scrubber.painter', 'playing.info.font', 'playing.info.font_size', 'playing.info.value', 'playing.station.stops', 'playing.station.mast',
    'playing.station.band_a', 'playing.station.shadow_a', 'pages.own.fill', 'pages.quick.light_ground', 'pages.date.gap', 'page.rows.height', 'page.rows.detail_height', 'page.title.height',
    'page.rows.text_x', 'page.rows.title_y', 'page.rows.title_h', 'page.rows.detail_y', 'page.rows.detail_h'];
  assert.deepEqual(data.schema.map((k) => k.path).filter((p) => studio.preview(p).kind === 'no' && !/^(coverflow|motion)\./.test(p)).sort(), no.sort());
  assert.equal(studio.preview('bar.battery.low').kind, 'state');
  assert.equal(studio.preview('list.row.title_px').kind, 'shown');
  assert.equal(studio.preview('coverflow.shelf.tilt').kind, 'no');
  // the groups carry it to the page
  const item = studio.groups(o).flatMap((g) => g.sections.flatMap((s) => s.keys)).find((k) => k.path === 'home.pane.svc_px');
  assert.equal(item.kind, 'no');
});

test('every geometry field has a label, once', () => {
  const groups = studio.geometryGroups(o);
  const fields = groups.flatMap((g) => g.fields.map((f) => f.name));
  assert.deepEqual([...fields].sort(), data.geometry.fields.map((f) => f.name).sort());
  assert.equal(new Set(fields).size, fields.length);
  assert.ok(!groups.some((g) => g.title === 'Other'), 'a field has no label');
  const unread = groups.flatMap((g) => g.fields.filter((f) => !f.read).map((f) => f.name));
  assert.equal(unread.length, 21);
  assert.ok(unread.includes('set_top') && unread.includes('search_meta_h') && !unread.includes('pitch'));
  // list_end changes the lists (draw_list.js); body, title24_y, meta_y and home_lib are read by no screen
  assert.ok(!unread.includes('list_end') && ['body', 'title24_y', 'meta_y', 'home_lib'].every((f) => unread.includes(f)));
  for (const f of studio.UNREAD) assert.ok(fields.includes(f), f);
});

// ---- the viewer's switches ----

test('the viewer offers the settings a theme lists, with the values it offers', () => {
  const of = (id) => studio.viewerControls(o, data.themes.find((b) => b.id === id).resolved);
  const minimal = of('minimal');
  assert.deepEqual(minimal.map((c) => c.id), ['STATUSBAR', 'time_title', 'SHOWQ2POD', 'corners', 'home', 'shortcut', 'battery', 'np_layout']);
  assert.deepEqual(minimal.find((c) => c.id === 'battery').values.map((v) => v.value), ['icon', 'percent', 'both', 'inside']);
  const classic = of('classic-light');
  assert.ok(!classic.some((c) => c.id === 'corners' || c.id === 'np_layout'), 'Classic lists neither');
  assert.deepEqual(classic.find((c) => c.id === 'battery').values.map((v) => v.value), ['icon', 'percent', 'inside']);
  assert.deepEqual(classic.find((c) => c.id === 'ROWART').values.map((v) => v.value), ['Off', 'On']);
  assert.equal(classic.find((c) => c.id === 'ROWART').title, 'Row Art');
  assert.equal(minimal.find((c) => c.id === 'home').title, 'Home Layout');
  assert.ok(!minimal.some((c) => c.id === 'light' || c.id === 'accent'));
});

test('the accent picker lists the schemes a theme offers', () => {
  const of = (id) => studio.accents(o, data.themes.find((b) => b.id === id).resolved);
  assert.deepEqual(of('minimal').map((a) => a.name), data.accents.map((a) => a.name));
  assert.deepEqual(of('modern').map((a) => a.name), data.accents.map((a) => a.name).filter((n) => n !== 'ivory'));
  const classic = of('classic-light');
  assert.equal(classic.length, 9);
  assert.equal(classic.at(-1).name, 'classic-blue');
  assert.equal(classic.at(-1).title, 'Classic Blue');
  assert.ok(!classic.some((a) => a.name === 'ivory'));
  for (const a of [...of('minimal'), ...classic]) assert.ok(Number.isInteger(a.colour) && a.colour > 0, a.name);
});

// ---- where a value comes from ----

test('a value is the base\'s until the theme states it, and the base\'s again after a reset', () => {
  const t = fresh('modern');
  let c = studio.context(o, t);
  let s = studio.valueSource(o, c, 'list.row.title_px');
  assert.deepEqual([s.from, s.stated, s.value, s.half], ['base', false, 0, null]);
  assert.equal(studio.fromWords(s, c), 'Modern’s');
  o.set(t, 'list.row.title_px', 27);
  c = studio.context(o, t);
  s = studio.valueSource(o, c, 'list.row.title_px');
  assert.deepEqual([s.from, s.stated, s.value, s.baseValue], ['theme', true, 27, 0]);
  assert.equal(studio.fromWords(s, c), 'this theme');
  // stating the base's own value is still the theme's statement
  o.set(t, 'list.row.title_px', 0);
  assert.equal(studio.valueSource(o, studio.context(o, t), 'list.row.title_px').from, 'theme');
  o.unset(t, 'list.row.title_px');
  assert.equal(studio.valueSource(o, studio.context(o, t), 'list.row.title_px').from, 'base');
  // a choice and a switch
  assert.equal(studio.valueSource(o, studio.context(o, t), 'list.selection.painter').value, o.key('list.selection.painter').choices.indexOf('bar'));
});

test('a key with a value per half has a source per half', () => {
  // over Minimal nothing states playing.info.value: stating the dark half leaves the light one following it
  const t = fresh('minimal');
  let c = studio.context(o, t);
  assert.deepEqual(['dark', 'light'].map((h) => studio.valueSource(o, c, 'playing.info.value', h).from), ['base', 'base']);
  o.set(t, 'playing.info.value', '#8a8a8a');
  c = studio.context(o, t);
  const [dark, light] = ['dark', 'light'].map((h) => studio.valueSource(o, c, 'playing.info.value', h));
  assert.deepEqual([dark.from, dark.stated, dark.value, dark.half], ['theme', true, 0x8a8a8a, 'dark']);
  assert.deepEqual([light.from, light.stated, light.half], ['derived', false, 'light']);
  assert.equal(light.value, o.flip(0x8a8a8a, 0xf4f4f4, 0x161616));
  assert.equal(studio.fromWords(light, c), 'follows the dark half');
  o.set(t, 'playing.info.value', '#707070', 'light');
  c = studio.context(o, t);
  assert.deepEqual(studio.valueSource(o, c, 'playing.info.value', 'light').from, 'theme');
  assert.equal(studio.valueSource(o, c, 'playing.info.value', 'light').value, 0x707070);
  o.unset(t, 'playing.info.value', 'dark');
  c = studio.context(o, t);
  assert.deepEqual(['dark', 'light'].map((h) => studio.valueSource(o, c, 'playing.info.value', h).from), ['derived', 'theme']);
  assert.equal(studio.fromWords(studio.valueSource(o, c, 'playing.info.value', 'dark'), c), 'follows the light half');

  // over Classic, which states both halves of the scroll bar's thumb: a dark statement leaves light Classic's
  const u = fresh('classic-light');
  o.set(u, 'list.scrollbar.thumb', '#505560');
  c = studio.context(o, u);
  assert.deepEqual(['dark', 'light'].map((h) => studio.valueSource(o, c, 'list.scrollbar.thumb', h).from), ['theme', 'base']);
  assert.equal(studio.valueSource(o, c, 'list.scrollbar.thumb', 'light').value, 0x8f98a8);
  assert.equal(studio.fromWords(studio.valueSource(o, c, 'list.scrollbar.thumb', 'light'), c), 'Classic’s');
});

test('a theme that extends nothing has the format\'s defaults; a built-in id has the firmware\'s values', () => {
  const copy = studio.startTheme(o, { base: 'minimal', mode: 'copy', id: 'dusk', name: 'Dusk' });
  const c = studio.context(o, copy);
  assert.equal(c.baseName, null);
  assert.equal(studio.valueSource(o, c, 'list.row.title_px').from, 'default');
  assert.equal(studio.fromWords(studio.valueSource(o, c, 'list.row.title_px'), c), 'the format’s default');
  assert.equal(studio.valueSource(o, c, 'list.selection.painter').from, 'theme');
  assert.equal(studio.valueSource(o, c, 'home.rows.top').from, 'theme', 'what the sources gave Minimal is stated in the copy');
  // Minimal's own file, opened: the keys its id gets from the sources cannot be stated
  const minimal = o.read(data.themes[0].text);
  const m = studio.context(o, minimal);
  const top = studio.valueSource(o, m, 'home.rows.top');
  assert.deepEqual([top.from, top.fixed, top.value], ['firmware', true, 8]);
  assert.equal(studio.valueSource(o, m, 'home.rows.caps').from, 'theme');
});

test('the geometry set in use has a source too', () => {
  const t = fresh('classic-light');
  let s = studio.valueSource(o, studio.context(o, t), 'geometry.set');
  assert.deepEqual([s.from, s.value, s.stated], ['base', 'classic-light', false]);
  o.useGeometry(t, 'classic-light-text');
  s = studio.valueSource(o, studio.context(o, t), 'geometry.set');
  assert.deepEqual([s.from, s.value, s.stated], ['theme', 'classic-light-text', true]);
});

test('a scheme\'s value is the scheme\'s own, every scheme\'s, or the base\'s', () => {
  const t = fresh('classic-light');
  let c = studio.context(o, t);
  let s = studio.schemeSource(o, c, 'classic-blue', 'sel.edge', 'dark');
  assert.deepEqual([s.from, s.value, s.stated, s.half], ['base', 0x004184, false, 'dark']);
  assert.equal(studio.schemeSource(o, c, 'cobalt', 'muted').value, 0x949294);
  assert.equal(studio.schemeSource(o, c, 'cobalt', 'muted').half, null);
  assert.equal(studio.schemeSource(o, c, 'cobalt', 'paper').half, 'light');
  // every scheme at once
  o.setScheme(t, null, 'muted', '#808890');
  c = studio.context(o, t);
  s = studio.schemeSource(o, c, 'cobalt', 'muted');
  assert.deepEqual([s.from, s.value, s.stated], ['all', 0x808890, false]);
  assert.equal(studio.fromWords(s, c), 'this theme, every scheme');
  s = studio.schemeSource(o, c, null, 'muted', undefined, 'cobalt');
  assert.deepEqual([s.from, s.value, s.stated], ['theme', 0x808890, true]);
  assert.equal(studio.schemeSource(o, c, null, 'sel.edge', 'dark', 'classic-blue').from, 'each');
  assert.equal(studio.schemeSource(o, c, null, 'sel.edge', 'dark', 'classic-blue').value, 0x004184);
  // one scheme's own statement wins over every scheme's
  o.setScheme(t, 'cobalt', 'muted', '#606870');
  c = studio.context(o, t);
  assert.deepEqual([studio.schemeSource(o, c, 'cobalt', 'muted').from, studio.schemeSource(o, c, 'cobalt', 'muted').value], ['theme', 0x606870]);
  assert.equal(studio.schemeSource(o, c, 'plum', 'muted').from, 'all');
  // a final value per half; paper is the light half's alone
  o.setScheme(t, 'classic-blue', 'sel.top', '#b0d0e8', 'light');
  o.setScheme(t, null, 'paper', '#f0f0f0');
  c = studio.context(o, t);
  assert.deepEqual(['dark', 'light'].map((h) => studio.schemeSource(o, c, 'classic-blue', 'sel.top', h).from), ['base', 'theme']);
  assert.deepEqual([studio.schemeSource(o, c, null, 'paper').from, studio.schemeSource(o, c, 'plum', 'paper').from], ['theme', 'all']);
  assert.equal(studio.schemeSource(o, c, 'plum', 'paper').value, 0xf0f0f0);
  // Classic turns Classic Blue's band to each accent: the same in the theme over it
  assert.equal(studio.schemeSource(o, c, 'plum', 'sel.stops', 'dark').from, 'base');
});

test('a scheme of the theme\'s own starts from the accent it names', () => {
  const t = studio.startTheme(o, { base: 'minimal', mode: 'copy', id: 'dusk', name: 'Dusk' });
  o.setOption(t, 'accent', { key: 'DUSK_ACCENT' });
  o.addScheme(t, { name: 'dusk', base: 'plum', label: 'Dusk' });
  let c = studio.context(o, t);
  let s = studio.schemeSource(o, c, 'dusk', 'fill');
  assert.deepEqual([s.from, s.fromName], ['all', null], 'the copy states what the sources gave Minimal for every scheme');
  s = studio.schemeSource(o, c, 'dusk', 'card');
  assert.deepEqual([s.from, s.fromName, s.value], ['accent', 'plum', 0]);
  assert.equal(studio.fromWords(s, c), 'Plum’s');
  o.setScheme(t, 'dusk', 'card', 1);
  c = studio.context(o, t);
  assert.equal(studio.schemeSource(o, c, 'dusk', 'card').from, 'theme');
  assert.deepEqual(studio.accents(o, c.resolved).at(-1).title, 'Dusk');
});

// ---- undo and redo ----

test('undo and redo walk the edits; a refused edit is no step', () => {
  const h = studio.history(fresh());
  assert.ok(!studio.canUndo(h) && !studio.canRedo(h) && !studio.dirty(h));
  assert.equal(studio.change(h, (t) => o.set(t, 'list.row.title_px', 27)), true);
  assert.equal(studio.change(h, (t) => o.set(t, 'home.rows.caps', 0)), true);
  assert.equal(studio.change(h, (t) => o.setScheme(t, 'cobalt', 'sel.text', '#ffffff')), true);
  assert.equal(h.past.length, 3);
  assert.ok(studio.dirty(h));
  const three = o.write(h.present);
  // refused: official.js throws, and nothing moves
  assert.throws(() => studio.change(h, (t) => o.set(t, 'list.row.title_px', 99)), (e) => e instanceof official.ThemeError && /outside 0\.\.64/.test(e.message));
  assert.throws(() => studio.change(h, (t) => { o.set(t, 'list.row.meta_px', 17); o.set(t, 'list.row.title_px', -1); }), official.ThemeError);
  assert.equal(h.past.length, 3);
  assert.equal(o.write(h.present), three, 'an edit refused half way leaves the theme whole');
  // an edit that changes nothing is no step either
  assert.equal(studio.change(h, (t) => o.set(t, 'list.row.title_px', 27)), false);
  assert.equal(h.past.length, 3);

  assert.ok(studio.undo(h));
  assert.equal(o.get(h.present, 'home.rows.caps'), 0);
  assert.equal(h.present.schemes.named.length, 0);
  assert.ok(studio.undo(h) && studio.undo(h));
  assert.equal(studio.undo(h), false);
  assert.ok(!studio.dirty(h), 'back where it was opened');
  assert.equal(o.write(h.present), o.write(fresh()));
  assert.ok(studio.redo(h) && studio.redo(h) && studio.redo(h));
  assert.equal(studio.redo(h), false);
  assert.equal(o.write(h.present), three);
  // a new edit after an undo drops what was undone
  studio.undo(h);
  studio.change(h, (t) => o.set(t, 'playing.art.square', 1));
  assert.ok(!studio.canRedo(h));
  assert.equal(h.past.length, 3);
});

test('the present theme is only ever replaced, so an undo step cannot be changed after the fact', () => {
  const h = studio.history(fresh());
  const before = h.present;
  studio.change(h, (t) => o.set(t, 'list.row.title_px', 27));
  assert.notEqual(h.present, before);
  assert.equal(o.get(before, 'list.row.title_px'), undefined);
  assert.equal(h.past[0], before);
});

test('the unsaved mark follows the saved text', () => {
  const h = studio.history(fresh());
  studio.change(h, (t) => o.set(t, 'list.row.title_px', 27));
  assert.ok(studio.dirty(h));
  studio.markSaved(h);
  assert.ok(!studio.dirty(h));
  studio.change(h, (t) => o.set(t, 'list.row.title_px', 28));
  assert.ok(studio.dirty(h));
  studio.undo(h);
  assert.ok(!studio.dirty(h), 'undone back to what was saved');
  studio.undo(h);
  assert.ok(studio.dirty(h), 'undone past what was saved');
});

test('a control that is dragged makes one step, not one per move', () => {
  const h = studio.history(fresh());
  const pick = (c, now) => studio.change(h, (t) => o.setScheme(t, 'cobalt', 'fill', c), 'scheme:cobalt:fill', now);
  pick('#101010', 1000);
  pick('#202020', 1100);
  pick('#303030', 1900);
  assert.equal(h.past.length, 1);
  assert.equal(h.present.schemes.named[0].values.fill, 0x303030);
  pick('#404040', 5000); // after a pause: a new step
  assert.equal(h.past.length, 2);
  studio.change(h, (t) => o.set(t, 'list.row.title_px', 27), 'key:list.row.title_px', 5100); // another control
  studio.change(h, (t) => o.set(t, 'list.row.title_px', 28), null, 5200); // no tag: its own step
  assert.equal(h.past.length, 4);
  studio.undo(h);
  pick('#505050', 5300); // an undo ends the run
  assert.equal(h.past.length, 4);
  for (let i = 0; i < studio.LIMIT + 20; i += 1) studio.change(h, (t) => o.set(t, 'list.row.title_px', i % 60));
  assert.equal(h.past.length, studio.LIMIT);
});

// ---- starting and exporting ----

test('a new theme extends a built-in, or is a copy of its statements, with no problems either way', () => {
  for (const base of o.builtinIds) {
    const over = studio.startTheme(o, { base, mode: 'extend', id: 'dusk', name: 'Dusk' });
    assert.equal(o.write(over), o.write(o.newTheme({ extends: base, id: 'dusk', name: 'Dusk' })));
    assert.deepEqual(o.problems(over), [], `over ${base}`);
    const copy = studio.startTheme(o, { base, mode: 'copy', id: 'dusk', name: 'Dusk' });
    assert.deepEqual(o.problems(copy), [], `a copy of ${base}`);
    const builtin = data.themes.find((b) => b.id === base);
    assert.equal(copy.extends, o.read(builtin.text).extends, 'it extends what the built-in extended');
    assert.equal(copy.index, data.themes.length);
    // the copy draws as the built-in does: every schema value, but for what only Classic's id may have
    const [a, b] = [o.resolve(copy), builtin.resolved];
    for (const k of data.schema) {
      if (k.path.startsWith('scheme.') || k.path === 'pages.own.art_final') continue;
      assert.deepEqual(a[k.field], b[k.field], `${base}: ${k.path}`);
    }
    assert.deepEqual(a.light, b.light);
    assert.deepEqual(a.schemes, b.schemes);
    assert.deepEqual(a.opts, b.opts);
    // Classic's art_final is its id's alone; the flat look's (Modern's, Classic Modern's) stays
    assert.equal(a.art_final, studio.flatPages(o, b) ? b.art_final : 0, `${base}: art_final`);
    if (base === 'classic-modern' || base === 'modern') assert.equal(a.art_final, 1, `a copy of ${base} keeps the flat look's final art`);
  }
});

test('the start page offers every built-in from official.json, four at 6ceb519a, and no text counts them by hand', () => {
  assert.deepEqual(o.builtinIds, ['minimal', 'classic-light', 'modern', 'classic-modern']);
  assert.equal(studio.startLead(o), 'Q2 Pod has four themes, Minimal, Classic, Modern and Classic Modern. A new one starts from one of them.');
  assert.equal(studio.countWords(4), 'four');
  assert.equal(studio.countWords(11), '11');
  // a fifth built-in in official.json is named at once
  const five = official.open(Object.assign({}, data, { themes: [...data.themes, Object.assign({}, data.themes[0], { resolved: Object.assign({}, data.themes[0].resolved, { name: 'Dusk' }) })] }));
  assert.match(studio.startLead(five), /^Q2 Pod has five themes, .* Classic Modern and Dusk\./);
  const html = readFileSync(new URL('./studio.html', import.meta.url), 'utf8');
  const js = readFileSync(new URL('./studio.js', import.meta.url), 'utf8');
  for (const text of [html, js]) assert.doesNotMatch(text, /\b(three|fourth) (built-in |)themes?\b|has three themes|a fourth built-in/i);
  // a new theme takes the next index after the built-ins
  for (const mode of ['extend', 'copy']) assert.equal(studio.startTheme(o, { base: 'classic-modern', mode, id: 'dusk', name: 'Dusk' }).index, data.themes.length);
});

test('the flat look\'s choices and keys have plain words', () => {
  assert.equal(studio.CHOICE_TITLES['classic-light+flat'], 'classic-light+flat (both looks)');
  for (const path of ['pages.own.painter', 'dialog.confirm.painter']) assert.ok(o.key(path).choices.includes('classic-light+flat'), path);
  assert.deepEqual(o.key('volume.panel.painter').choices, ['stock', 'classic-light', 'flat']);
  for (const path of ['pages.own.fill', 'pages.quick.light_ground', 'pages.date.gap']) {
    assert.ok(studio.label(path) && !studio.label(path).includes('_'), path);
    assert.equal(studio.preview(path).kind, 'no');
    assert.match(studio.preview(path).where, /on the Q2|Classic’s own/);
  }
  const painter = studio.preview('pages.own.painter');
  assert.equal(painter.kind, 'shown');
  assert.match(painter.where, /Home’s pane/);
  assert.match(painter.also, /not on a preview screen: on the Q2 it gives Quick Settings/);
  assert.equal(studio.groups(o).flatMap((g) => g.sections.flatMap((s) => s.keys)).find((k) => k.path === 'pages.own.painter').also, painter.also, 'the editor carries the note');
  assert.equal(studio.SECTIONS['pages.quick'], 'Quick Settings, flat look');
  assert.equal(studio.SECTIONS['pages.date'], 'Set Date, flat look');
  // the flat bit: flat and classic-light+flat, not stock or classic-light
  const by = (id) => data.themes.find((b) => b.id === id).resolved;
  assert.deepEqual(['minimal', 'classic-light', 'modern', 'classic-modern'].map((id) => studio.flatPages(o, by(id))), [false, false, true, true]);
});

test('a start that official.js refuses is refused in its words; a built-in\'s id is not taken', () => {
  const start = (id, name = 'Dusk', mode = 'extend') => studio.startTheme(o, { base: 'minimal', mode, id, name });
  for (const mode of ['extend', 'copy']) {
    assert.throws(() => start('Dusk', 'Dusk', mode), (e) => e instanceof official.ThemeError && /^id: expected/.test(e.detail));
    assert.throws(() => start('dusk', '', mode), (e) => e instanceof official.ThemeError && /^name: expected/.test(e.detail));
    assert.throws(() => start('modern', 'Dusk', mode), (e) => e instanceof studio.StudioError && /built-in/.test(e.message));
  }
  assert.throws(() => studio.startTheme(o, { base: 'nope', mode: 'extend', id: 'dusk', name: 'Dusk' }), studio.StudioError);
  assert.match(studio.refusalWords(o, (() => { try { start('9'); } catch (e) { return e; } return null; })()), /must start with a lowercase letter/);
  assert.match(studio.refusalWords(o, new studio.StudioError('plain words')), /^plain words$/);
});

test('an id is suggested from the name', () => {
  assert.equal(studio.suggestId('Dusk'), 'dusk');
  assert.equal(studio.suggestId('  Dusk  Blue! '), 'dusk-blue');
  assert.equal(studio.suggestId('Café au lait'), 'cafe-au-lait');
  assert.equal(studio.suggestId('80s'), 't-80s');
  assert.equal(studio.suggestId('暗'), '');
  for (const name of ['Dusk', 'a_b', 'X 1', '80s']) assert.match(studio.suggestId(name), /^[a-z][a-z0-9_-]*$/);
});

test('the export is official.js\'s write(), and reads back as the same theme', () => {
  const h = studio.history(fresh('classic-light'));
  studio.change(h, (t) => o.set(t, 'home.pane.stops', stops([0, 0x3a4048], [100, 0x2a3038]), 'light'));
  studio.change(h, (t) => o.setScheme(t, 'classic-blue', 'sel.edge', '#181c22'));
  studio.change(h, (t) => o.addGeometry(t, 'roomy', 'classic-light', { text_x: 24 }));
  studio.change(h, (t) => o.setOption(t, 'light', { preset: 'off' }));
  const text = studio.exportText(o, h.present);
  assert.equal(text, o.write(h.present));
  assert.deepEqual(o.read(text), h.present);
  assert.equal(studio.repoPath(h.present), 'assets/themes/dusk/theme.xml');
  // every step of the way back writes what official.js writes of it
  while (studio.undo(h)) assert.equal(studio.exportText(o, h.present), o.write(h.present));
  assert.equal(studio.exportText(o, h.present), `<theme format="1" id="dusk" name="Dusk" index="${data.themes.length}" extends="classic-light">\n  <view name="pages">\n    <element name="own" art_final="0"/>\n  </view>\n</theme>\n`);
});

// ---- problems ----

test('a problem points at the control it is about', () => {
  const tree = studio.groups(o);
  const at = (base, change) => {
    const t = fresh(base);
    change(t);
    const found = o.problems(t);
    assert.ok(found.length > 0, 'the change makes a problem');
    return studio.problemTarget(o, found[0]);
  };
  const key = (target) => [target.panel, target.path];
  assert.deepEqual(key(at('modern', (t) => o.set(t, 'list.selection.painter', 'stops'))), ['lists', 'list.selection.painter']);
  assert.deepEqual(key(at('classic-light', (t) => o.set(t, 'bar.title.font_size', 24))), ['bar', 'bar.title.font_size']);
  assert.deepEqual(key(at('classic-light', (t) => o.unset(t, 'pages.own.art_final'))), ['panels', 'pages.own.art_final']);
  assert.deepEqual(key(at('minimal', (t) => o.setScheme(t, null, 'paper', '#f4f0e8'))), ['schemes', 'scheme.paper']);
  assert.deepEqual(key(at('minimal', (t) => o.set(t, 'list.row.title_px', 60))), ['panels', 'page.rows.height']);
  assert.deepEqual(key(at('minimal', (t) => o.set(t, 'motion.step.easing', 'follow'))), ['advanced', 'motion.step.easing']);
  assert.deepEqual(key(at('minimal', (t) => o.set(t, 'coverflow.shelf.row_out', 1))), ['advanced', 'coverflow.shelf.row_out']);
  assert.deepEqual(key(at('classic-light', (t) => o.set(t, 'coverflow.land.out_ms', 500))), ['advanced', 'coverflow.land.out_ms']);
  assert.deepEqual(key(at('minimal', (t) => { o.set(t, 'coverflow.shelf.eye', 1); o.set(t, 'coverflow.shelf.z1', 0); })), ['advanced', 'coverflow.shelf.eye']);
  const scroll = at('minimal', (t) => { o.set(t, 'list.scrollbar.w', 4); o.set(t, 'list.scrollbar.top', 59); o.set(t, 'list.scrollbar.bottom', 261); o.set(t, 'list.scrollbar.right', 2); });
  assert.equal(scroll.panel, 'lists');
  assert.match(scroll.path, /^list\.scrollbar\./);
  assert.equal(at('minimal', (t) => o.removeOption(t, 'corners')).panel, 'options');
  assert.deepEqual(at('minimal', (t) => o.setOption(t, 'home', { default: 'full' })), { panel: 'options', option: 'home' });
  // a built-in set's np_ipod cannot change: the stops are what to take back
  assert.deepEqual(key(studio.problemTarget(o, { tool: "x/theme.xml:1: set ipod's np_ipod needs playing.scrubber.stops, and they it" })), ['playing', 'playing.scrubber.stops']);
  assert.deepEqual(studio.problemTarget(o, { tool: "x/theme.xml:1: ROWPREVIEW is classic-light's, with other values or default" }), { panel: 'options', option: 'ROWPREVIEW' });
  assert.deepEqual(at('minimal', (t) => { o.setOption(t, 'accent', { key: 'DUSK_ACCENT' }); o.offer(t, ['cobalt', 'plum']); }), { panel: 'options', option: 'accent' });
  assert.deepEqual(at('minimal', (t) => o.addScheme(t, { name: 'dusk', base: 'plum', label: 'Dusk' })), { panel: 'options', option: 'accent' });
  assert.equal(at('minimal', (t) => o.rename(t, { index: 5 })).panel, 'theme');
  assert.equal(at('classic-light', (t) => { o.addGeometry(t, 'roomy', 'classic-light', { pitch: 36, body: 36 }); o.useGeometry(t, 'roomy'); }).panel, 'options');
  assert.equal(at('minimal', (t) => { o.addGeometry(t, 'classic-light', null, { bar: 28 }); }).panel, 'geometry');
  // every target is a place the page has: a group, or Theme or Options, and a key of that group
  const panels = new Set([...tree.map((g) => g.id), 'theme', 'options']);
  for (const message of ['x/theme.xml:3: no accent option', 'x/theme.xml:1: 11 accents, at most 10', 'x/theme.xml:1: colorSchemes is empty', 'x/theme.xml:1: STATUSBAR declared twice',
    'x/theme.xml:1: 9 geometry sets: ui_redirect_t.sets holds 8', 'x/theme.xml:1: something new the tool says', 'x/theme.xml:1: battery: this painter needs stops',
    'x/theme.xml:1: light: a scheme with its own mode has no Light Mode option', 'x/theme.xml:1: coverflow.shelf: swing\'s near edge reaches the eye mid-step']) {
    const target = studio.problemTarget(o, { tool: message });
    assert.ok(panels.has(target.panel), message);
    if (target.path) assert.ok(tree.find((g) => g.id === target.panel).sections.some((s) => s.keys.some((k) => k.path === target.path)), message);
  }
  assert.deepEqual(key(studio.problemTarget(o, 'x/theme.xml:1: battery: this painter needs stops')), ['bar', 'bar.battery.stops']);
  assert.deepEqual(key(studio.problemTarget(o, 'x/theme.xml:1: coverflow.shelf: swing\'s near edge reaches the eye mid-step')), ['advanced', 'coverflow.shelf.swing']);
  assert.equal(studio.problemTarget(o, 'x/theme.xml:1: 11 accents, at most 10').panel, 'schemes');
});

// ---- colours and stops ----

test('stops lists are edited as whole lists official.js accepts', () => {
  const two = stops([0, 0x000000], [100, 0xffffff]);
  const three = studio.stopsAdd(two);
  assert.deepEqual(three, [[0, 0], [50, 0x808080], [100, 0xffffff]]);
  assert.deepEqual(two, [[0, 0], [100, 0xffffff]], 'the list given is not changed');
  assert.deepEqual(studio.stopsAdd(three).map((s) => s[0]), [0, 25, 50, 100]);
  assert.deepEqual(studio.stopsRemove(three, 1), two);
  assert.deepEqual(studio.stopsSet(three, 1, 40), [[0, 0], [40, 0x808080], [100, 0xffffff]]);
  assert.deepEqual(studio.stopsSet(three, 1, undefined, 0x112233), [[0, 0], [50, 0x112233], [100, 0xffffff]]);
  const full = [[0, 1], [1, 2], [2, 3], [100, 4]];
  assert.deepEqual(studio.stopsAdd(full).map((s) => s[0]), [0, 1, 2, 51, 100]);
  assert.deepEqual(studio.stopsAdd([[0, 1], [1, 2]]), [[0, 1], [1, 2]], 'no whole position is free');
  let list = two;
  const t = fresh();
  while (list.length < 13) {
    list = studio.stopsAdd(list);
    o.set(t, 'home.pane.stops', list);
  }
  assert.equal(o.resolve(t).home_pane.length, 13);
  assert.equal(studio.hex(0x0a0b0c), '#0a0b0c');
  assert.equal(studio.stopsCss(two), 'linear-gradient(to right, #000000 0%, #ffffff 100%)');
  assert.equal(studio.stopsCss([]), 'none');
  assert.match(studio.rowsCss([0xff102030, 0x80405060]), /^linear-gradient\(to right, rgba\(16, 32, 48, 1\.000\) 0% 50%, rgba\(64, 80, 96, 0\.502\) 50% 100%\)$/);
});

// ---- the file itself ----

test('a page loads studio.js with a script tag, as window.Q2Studio, and nothing ships that should not', async () => {
  const { runInNewContext } = await import('node:vm');
  const source = readFileSync(new URL('./studio.js', import.meta.url), 'utf8');
  const window = {};
  runInNewContext(source, Object.assign(window, { globalThis: window }));
  assert.equal(typeof window.Q2Studio.page, 'function');
  assert.equal(window.Q2Studio.groups(o).length, studio.GROUPS.length);
  const html = readFileSync(new URL('./studio.html', import.meta.url), 'utf8');
  const css = readFileSync(new URL('./studio.css', import.meta.url), 'utf8');
  // the strict policy: no inline script or style, nothing from another host
  assert.match(html, /<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; /);
  assert.ok(!/<script(?![^>]*\bsrc=)[^>]*>/.test(html), 'an inline script');
  assert.ok(!/<style\b|\sstyle="|\son[a-z]+="/.test(html), 'an inline style or handler');
  assert.ok(!/(?:src|href)="(?:https?:)?\/\//.test(html) && !/url\(['"]?(?:https?:)?\/\//.test(css), 'a file from another host');
  for (const file of [source, html, css]) {
    assert.ok(!/\beval\(|new Function\(|innerHTML|insertAdjacentHTML|document\.write/.test(file), 'markup or code made from text');
  }
  // the scripts the page names, in the order they need each other
  const scripts = [...html.matchAll(/<script src="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(scripts.slice(0, 3), ['official.js', 'draw_core.js', 'draw_bar.js']);
  assert.equal(scripts.at(-1), 'studio.js');
  // every element the page's script looks up by id is in the page
  const ids = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]));
  for (const [, id] of source.matchAll(/\$\('([^']+)'\)/g)) assert.ok(ids.has(id), `#${id} is not in studio.html`);
});
