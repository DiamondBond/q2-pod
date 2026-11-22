// SPDX-License-Identifier: GPL-3.0-only
// Part of Q2 Theme Studio, which holds work from DiamondBond/q2-pod (GPL-3.0-only): see LICENSE at the repository root.
// Q2 Theme Studio: the editor page for the official Q2 Pod theme format (studio.html). Two parts in one file.
// The first is the page's own logic with no page in it: what each key is called and where it is grouped,
// whether the preview shows it, where a value comes from (this theme or its base), undo and redo, starting
// a theme, exporting it, and which control a problem points at. studio.test.mjs runs that part under node.
// The second, page(), is the page itself: it builds the controls, sends every edit through official.js
// (which refuses what the firmware's build would) and draws the preview with Q2Draw.
//
// Loaded by studio.html as window.Q2Studio after official.js and the draw_*.js files, and by the tests as a
// module (page() is then never called).
(function (root, make) {
  const studio = make();
  if (typeof module === 'object' && module.exports) module.exports = studio;
  else {
    root.Q2Studio = studio;
    if (root.document) studio.page(root);
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  // A count in words, as the page's sentences say it: 'four', or '11' past ten.
  const COUNT_WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
  const countWords = (n) => COUNT_WORDS[n] || String(n);
  // The built-in themes in a sentence, from official.json: 'Q2 Pod has four themes, Minimal, Classic, Modern
  // and Classic Modern. A new one starts from one of them.'
  function startLead(official) {
    const names = official.data.themes.map((b) => b.resolved.name);
    const list = names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names.join('');
    return `Q2 Pod has ${countWords(names.length)} theme${names.length === 1 ? '' : 's'}, ${list}. A new one starts from one of them.`;
  }
  // Whether a theme's pages painter has the flat look's bit (theme.h flat_pages; validate's flat): then
  // pages.own.art_final may be 1 under any id.
  function flatPages(official, resolved) {
    const k = official.key('pages.own.painter');
    return Boolean(resolved[k.field] & Math.max(0, k.choices.indexOf('flat')));
  }
  // An enum value's words in a picker, where its name alone does not say it.
  const CHOICE_TITLES = { 'classic-light+flat': 'classic-light+flat (both looks)' };
  const clone = (data) => JSON.parse(JSON.stringify(data));
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

  // ------------------------------------------------------------------------------- names and grouping

  // The editor's groups, in the order of its list. views: the theme.xml views whose keys a group holds;
  // screens: the preview screens that show them (the page turns to one when the group is opened).
  const GROUPS = [
    { id: 'bar', title: 'Status bar', views: ['bar'], screens: null },
    { id: 'home', title: 'Home', views: ['home'], screens: ['home'] },
    { id: 'lists', title: 'Lists and Settings', views: ['list', 'settings'], screens: ['list-library', 'list-albums', 'list-songs', 'settings'] },
    { id: 'playing', title: 'Now Playing', views: ['playing'], screens: ['now-playing', 'volume'] },
    { id: 'panels', title: 'Volume, dialogs, pages', views: ['volume', 'dialog', 'pages', 'page'], screens: ['volume', 'confirm'] },
    { id: 'schemes', title: 'Colour schemes', views: [], screens: null },
    { id: 'geometry', title: 'Geometry', views: [], screens: null },
    { id: 'advanced', title: 'Advanced', views: ['coverflow', 'motion'], screens: null, folded: true },
  ];

  // A section is one element of a view (or a part of a colour scheme): its heading in plain words.
  const SECTIONS = {
    'bar.fill': 'Fill', 'bar.title': 'Title and clock', 'bar.battery': 'Battery', 'bar.icons': 'Bluetooth and Wi-Fi', 'bar.state': 'Play mark',
    'home.rows': 'Rows', 'home.chevron': 'Chevron', 'home.pane': 'The art panel in Split',
    'list.selection': 'Selection', 'list.row': 'Row text', 'list.art': 'Cover rows', 'list.chevron': 'Chevron', 'list.separator': 'Separators',
    'list.icons': 'Icons', 'list.scrollbar': 'Scroll indicator', 'list.letter': 'Fast-scroll letter',
    'settings.rows': 'Settings rows', 'settings.values': 'Settings values',
    'playing.': 'Page', 'playing.art': 'Cover art', 'playing.title': 'Title', 'playing.album': 'Album line', 'playing.state': 'Play-state glyph',
    'playing.scrubber': 'Progress bar', 'playing.info': 'Info page and small captions', 'playing.station': 'Internet Radio cover',
    'volume.panel': 'Volume panel', 'dialog.confirm': 'Confirm dialog', 'pages.own': 'The firmware’s own pages',
    'pages.quick': 'Quick Settings, flat look', 'pages.date': 'Set Date, flat look',
    'page.rows': 'Own list pages: rows', 'page.title': 'Own list pages: title',
    'scheme.sel': 'Selection band', 'scheme.bar': 'Status bar', 'scheme.marks': 'Text and marks', 'scheme.light': 'The light half',
    'geometry.': 'Geometry set',
    'coverflow.shelf': 'Cover Flow: the shelf', 'coverflow.caption': 'Cover Flow: the caption', 'coverflow.land': 'Cover Flow: landing on Now Playing',
    'motion.page': 'Motion: a page opens', 'motion.playing': 'Motion: Now Playing opens', 'motion.coverflow': 'Motion: Cover Flow opens',
    'motion.inplace': 'Motion: a change in place', 'motion.swap': 'Motion: a swap', 'motion.step': 'Motion: the selection steps',
    'motion.step_fast': 'Motion: the selection steps fast', 'motion.coverflow_step': 'Motion: Cover Flow steps',
    'motion.coverflow_step_fast': 'Motion: Cover Flow steps fast', 'motion.recall': 'Motion: recall', 'motion.bump': 'Motion: the bump at a list’s end',
  };

  // Every schema key: [path, label, hint]. The order here is the order in the editor; a key's group and
  // section come from its view and element. studio.test.mjs checks that each schema key is here once.
  const LABELS = [
    // ---- status bar
    ['bar.fill.painter', 'Fill style', 'flat: one colour; gloss: the scheme’s status bar gradient'],
    ['bar.title.font', 'Font', ''],
    ['bar.title.font_size', 'Size', 'must equal the geometry set’s bar_px'],
    ['bar.title.caps', 'Idle mark in small capitals', ''],
    ['bar.battery.painter', 'Style', 'stock: the firmware’s icon; classic-light: drawn from the values below'],
    ['bar.battery.stops', 'Level gradient', 'top to bottom'],
    ['bar.battery.empty', 'Empty part gradient', 'past the level'],
    ['bar.battery.line', 'Outline', ''],
    ['bar.battery.edge', 'Bottom row inside the outline', ''],
    ['bar.battery.low', 'Colour when low', ''],
    ['bar.battery.low_w', 'Width when low', 'columns'],
    ['bar.battery.corner_a', 'Top corners alpha', '0 to 255'],
    ['bar.battery.foot_a', 'Bottom corners alpha', '0 to 255'],
    ['bar.battery.shade_a', 'Shade on the level’s last column', 'alpha, 0 to 255'],
    ['bar.battery.soft_a', 'Soft outer edge, light half', 'alpha, 0 to 255'],
    ['bar.battery.soft_top_a', 'Soft top edge, light half', 'alpha, 0 to 255'],
    ['bar.battery.emboss_a', 'White row under the body, light half', 'alpha, 0 to 255'],
    ['bar.battery.emboss_nub_a', 'White row under the nub, light half', 'alpha, 0 to 255'],
    ['bar.battery.bolt', 'Bolt and plug colour', ''],
    ['bar.battery.bolt_halo_a', 'Bolt halo alpha', '0 to 255'],
    ['bar.icons.bt_dy', 'Bluetooth, rows down', 'negative moves it up'],
    ['bar.icons.wifi_dy', 'Wi-Fi, rows down', 'negative moves it up'],
    ['bar.state.stops', 'Fill gradient', 'top to bottom'],
    ['bar.state.edge', 'Edge gradient', ''],
    ['bar.state.halo_light', 'Halo alpha, light half', '0 to 255'],
    ['bar.state.halo_dark', 'Halo alpha, dark half', '0 to 255'],
    // ---- Home
    ['home.rows.top', 'First row’s top', 'px under the status bar'],
    ['home.rows.full_row', 'Row width in Full', ''],
    ['home.rows.text_x', 'Label’s left edge', ''],
    ['home.rows.label_end_split', 'Label’s right margin in Split', ''],
    ['home.rows.label_end_full', 'Label’s right margin in Full', ''],
    ['home.rows.font', 'Label font', ''],
    ['home.rows.font_px', 'Label size', '0: the firmware’s'],
    ['home.rows.caps', 'Labels in small capitals', ''],
    ['home.chevron.visible', 'Show a chevron', ''],
    ['home.chevron.x', 'Chevron’s left edge in Split', '0: stock’s place'],
    ['home.pane.stops', 'Fill when no cover shows', 'none: the placeholder picture'],
    ['home.pane.light_a', 'Light across the panel', 'white at this alpha on the left, fading to none'],
    ['home.pane.shadow', 'Left shadow colour', ''],
    ['home.pane.shadow_w', 'Left shadow width', 'columns'],
    ['home.pane.shadow_a', 'Left shadow alphas', 'one per column, 0 to 255'],
    ['home.pane.icon_x', 'Row icon x', '0: the panel does not follow the row'],
    ['home.pane.icon_y', 'Row icon y', ''],
    ['home.pane.note_x', 'Note x', ''],
    ['home.pane.note_y', 'Note y', ''],
    ['home.pane.count_y', 'Caption y', ''],
    ['home.pane.count_w', 'Caption width', 'the caption is centred on it'],
    ['home.pane.count_px', 'Caption size', ''],
    ['home.pane.svc_x', 'Streaming service icon x', ''],
    ['home.pane.svc_y', 'Streaming service icon y', ''],
    ['home.pane.svc_px', 'Streaming service icon size', ''],
    // ---- lists
    ['list.selection.painter', 'Style', 'card: a soft card; stops: the scheme’s gradient band; bar: the accent’s flat bar'],
    ['list.row.font', 'Title font', ''],
    ['list.row.title_px', 'Title size', '0: the firmware’s'],
    ['list.row.meta_font', 'Second line font', ''],
    ['list.row.meta_px', 'Second line size', '0: the firmware’s'],
    ['list.row.tall_font', 'Tall row title font', 'rows taller than the set’s pitch'],
    ['list.row.tall_px', 'Tall row title size', ''],
    ['list.row.text_end', 'Two-line text’s right edge', 'a row without a cover'],
    ['list.art.x', 'Cover’s left edge', '0: stock’s layout'],
    ['list.art.text_x', 'Text’s left edge beside a cover', ''],
    ['list.art.text_end', 'Text’s right edge beside a cover', ''],
    ['list.art.placeholder', 'Grey tile size', '0: stock’s'],
    ['list.chevron.selected', 'Only on the selected row', ''],
    ['list.chevron.x', 'Left edge', 'the theme’s own chevron; 0: stock’s'],
    ['list.separator.stops', 'Rows at a two-line row’s end', 'one stop per pixel row'],
    ['list.icons.mono', 'Grey Library and settings icons', ''],
    ['list.icons.badge_muted', 'Muted file-type badges', ''],
    ['list.icons.addon_mono', 'Grey card-app icon', ''],
    ['list.icons.badge_ink', 'Codec badge in the half’s ink', ''],
    ['list.scrollbar.w', 'Thumb width', '0: stock’s indicator'],
    ['list.scrollbar.right', 'Gap from the right edge', ''],
    ['list.scrollbar.top', 'Top row', 'on screen'],
    ['list.scrollbar.bottom', 'Bottom row', 'on screen'],
    ['list.scrollbar.min', 'Shortest thumb', ''],
    ['list.scrollbar.thumb', 'Thumb colour', ''],
    ['list.letter.raw', 'Same colours in both halves', ''],
    ['list.letter.px', 'Size', '0: the firmware’s'],
    ['settings.rows.top', 'First row’s top', 'px under the status bar'],
    ['settings.values.text', 'Value as text at the right', 'off: "Title: value"'],
    // ---- Now Playing
    ['playing.layout', 'Layout', 'the layout a theme without the Now Playing option shows'],
    ['playing.art.square', 'Square covers', 'off: rounded'],
    ['playing.title.font', 'Font', ''],
    ['playing.title.font_px', 'Size', '0: the firmware’s'],
    ['playing.album.caps', 'Small capitals', ''],
    ['playing.album.opacity', 'Opacity', '0 to 255'],
    ['playing.state.opacity', 'Opacity over the art', '0 hides it'],
    ['playing.scrubber.height', 'Height', ''],
    ['playing.scrubber.scrub_height', 'Height while scrubbing', ''],
    ['playing.scrubber.stops', 'Track gradient', 'given: the gloss bar, with a set whose np_ipod is 1'],
    ['playing.scrubber.fill', 'Played part gradient', 'under the theme’s own scheme; none: the scheme’s band'],
    ['playing.scrubber.painter', 'A card app’s progress row', ''],
    ['playing.scrubber.dark_track', 'Volume panel track, dark', 'pixel rows, top to bottom'],
    ['playing.scrubber.dark_fill', 'Volume panel fill, dark', 'pixel rows, top to bottom'],
    ['playing.scrubber.light_track', 'Volume panel track, light', 'pixel rows, top to bottom'],
    ['playing.scrubber.light_fill', 'Volume panel fill, light', 'pixel rows, top to bottom'],
    ['playing.info.font', 'Font', ''],
    ['playing.info.font_size', 'Size', ''],
    ['playing.info.value', 'Colour of the values', ''],
    ['playing.station.stops', 'Background gradient', ''],
    ['playing.station.mast', 'Mast gradient', ''],
    ['playing.station.band_a', 'Light band alpha', '0 to 255'],
    ['playing.station.shadow_a', 'Shadow alpha', '0 to 255'],
    // ---- volume, dialogs, pages
    ['volume.panel.painter', 'Style', 'over a page other than Now Playing. stock: a grey panel with the number; classic-light: Classic’s gloss panel; flat: a dark panel, a thin bar, no number'],
    ['dialog.confirm.painter', 'Style', 'stock: two full-width rows; classic-light: Classic’s two cells; flat: two round cells; classic-light+flat: the flat cells'],
    ['pages.own.painter', 'Style', 'the look of the firmware’s own pages (Quick Settings, sliders, messages, Set Date and Time). flat also gives Home’s pane and Now Playing’s marks the flat look; classic-light+flat: both looks, Classic’s colour for what is on'],
    ['pages.own.art_final', 'The theme’s art keeps its colours in the light half', 'on only for the theme whose id is classic-light, or with a flat style above'],
    ['pages.own.fill', 'Background of Classic’s own pages', 'the lock screen’s info page; none: Home’s pane colour'],
    ['pages.quick.light_ground', 'Ground round the cards, light half', 'none: the paper; flat style only'],
    ['pages.date.gap', 'Space between the date’s fields', 'px; 0: Classic’s places; flat style only'],
    ['page.rows.height', 'Row height', ''],
    ['page.rows.detail_height', 'Two-line row height', ''],
    ['page.rows.text_x', 'Text’s left edge', ''],
    ['page.rows.title_y', 'Title box y', ''],
    ['page.rows.title_h', 'Title box height', 'at least the tall title’s size'],
    ['page.rows.detail_y', 'Detail box y', ''],
    ['page.rows.detail_h', 'Detail box height', 'at least the second line’s size'],
    ['page.title.height', 'Title row height', '0: none, the bar holds the title'],
    // ---- colour schemes
    ['scheme.sel.stops', 'Band gradient', 'the stops selection, top to bottom'],
    ['scheme.sel.top', 'Top line', ''],
    ['scheme.sel.edge', 'Bottom edge', ''],
    ['scheme.sel.text', 'Text on the selection', ''],
    ['scheme.sel.tall_top', 'Tall row: second line', 'none: the gradient'],
    ['scheme.sel.tall_line', 'Tall row: line above the edge', ''],
    ['scheme.sel.tall_edge', 'Tall row: bottom edge', 'none: the band’s edge'],
    ['scheme.bar.stops', 'Gloss gradient', 'under the gloss fill style'],
    ['scheme.bar.line', 'Line under the bar', ''],
    ['scheme.bar.line2', 'Second line, light half', 'none: no line'],
    ['scheme.bar_light', 'Flat bar in the light half', ''],
    ['scheme.fill', 'Card and progress fill', ''],
    ['scheme.card', 'Card look: dark ink on the selection', ''],
    ['scheme.chevron', 'Chevron and grey icons', ''],
    ['scheme.muted', 'Muted text', 'second lines, "3 of 12", the times'],
    ['scheme.raw_red', 'Leave stock’s red as it is', 'dark half'],
    ['scheme.mode', 'Light or dark', 'derive: Light Mode decides'],
    ['scheme.paper', 'Paper', 'a grey, lighter than the ink'],
    ['scheme.ink', 'Ink', 'a grey'],
    // ---- geometry
    ['geometry.set', 'Set in use', 'takes effect at a restart'],
    // ---- Cover Flow
    ['coverflow.shelf.top', 'Shelf top', ''],
    ['coverflow.shelf.view_h', 'Frame height', ''],
    ['coverflow.shelf.x1', 'First side cover: x', ''],
    ['coverflow.shelf.xs', 'Side covers: x spacing', ''],
    ['coverflow.shelf.z1', 'First side cover: depth', ''],
    ['coverflow.shelf.zs', 'Side covers: depth spacing', ''],
    ['coverflow.shelf.eye', 'Eye distance', ''],
    ['coverflow.shelf.eye_turn', 'Eye distance added while turning', ''],
    ['coverflow.shelf.tilt', 'Side cover tilt', 'degrees, 30 to 90'],
    ['coverflow.shelf.horizon', 'Horizon', 'percent'],
    ['coverflow.shelf.art_persp', 'Perspective within a cover', 'percent; 0: even'],
    ['coverflow.shelf.bright1', 'First side cover brightness', 'of 256'],
    ['coverflow.shelf.bright2', 'Far covers brightness', 'of 256, not above the first'],
    ['coverflow.shelf.third', 'Unshaded out to the third cover', '0 or 1'],
    ['coverflow.shelf.reflect', 'Reflection height', ''],
    ['coverflow.shelf.reflect_top', 'Reflection strength at its top', 'of 256'],
    ['coverflow.shelf.stride', 'Stride', ''],
    ['coverflow.shelf.radius', 'Cover corner radius', ''],
    ['coverflow.shelf.swing', 'Swing', '0, 1 or 2'],
    ['coverflow.shelf.lift', 'Lift while turning', ''],
    ['coverflow.shelf.thumb', 'The wheel holds the covers', '0 or 1; the numbers below are its'],
    ['coverflow.shelf.ticks_turn', 'Wheel ticks per turn', ''],
    ['coverflow.shelf.ticks_album', 'Wheel ticks per album', ''],
    ['coverflow.shelf.fast_at', 'Fast from', 'ticks per second'],
    ['coverflow.shelf.fast_full', 'Fully fast at', 'ticks per second'],
    ['coverflow.shelf.top_speed', 'Top speed', ''],
    ['coverflow.shelf.track', 'Track', ''],
    ['coverflow.shelf.snap', 'Snap', ''],
    ['coverflow.shelf.spin', 'Spin', ''],
    ['coverflow.shelf.far_left', 'Far left', ''],
    ['coverflow.shelf.detent', 'Detent', ''],
    ['coverflow.shelf.hold_ms', 'Hold', 'ms'],
    ['coverflow.shelf.stop_ms', 'Stop', 'ms'],
    ['coverflow.shelf.stop_left', 'Stop left', ''],
    ['coverflow.shelf.rate_up', 'Rate up', ''],
    ['coverflow.shelf.rate_down', 'Rate down', ''],
    ['coverflow.shelf.back', 'Back', ''],
    ['coverflow.shelf.dead', 'Dead zone', ''],
    ['coverflow.shelf.contact_ms', 'Contact', 'ms'],
    ['coverflow.shelf.aim_snap', 'Aim snap', ''],
    ['coverflow.shelf.lead_from', 'Lead from', ''],
    ['coverflow.shelf.lead_full', 'Full lead at', 'past Lead from'],
    ['coverflow.shelf.lead_ms', 'Lead', 'ms'],
    ['coverflow.shelf.row_shift', 'Held row: shift', ''],
    ['coverflow.shelf.row_from', 'Held row: from', ''],
    ['coverflow.shelf.row_full', 'Held row: full at', 'past Held row: from'],
    ['coverflow.shelf.row_shrink', 'Held row: shrink', 'percent'],
    ['coverflow.shelf.row_flat', 'Held row: flat', ''],
    ['coverflow.shelf.row_out', 'Held row: spacing', ''],
    ['coverflow.shelf.row_edge', 'Held row: edge', ''],
    ['coverflow.shelf.row_width', 'Held row: width', 'percent'],
    ['coverflow.shelf.row_key', 'Held row: key', ''],
    ['coverflow.shelf.jump_ms', 'Letter jump: after', 'ms at speed, Fast Navigation off'],
    ['coverflow.shelf.jump_ticks', 'Letter jump: ticks per letter', '0: never'],
    ['coverflow.shelf.jump_at', 'Letter jump: from', 'ticks per second'],
    ['coverflow.shelf.jump_pace', 'Letter jump: pace', ''],
    ['coverflow.shelf.big_jump_at', 'Fast Navigation jump: from', 'ticks per second'],
    ['coverflow.shelf.big_jump_ms', 'Fast Navigation jump: after', 'ms'],
    ['coverflow.shelf.enter_albums', 'Letter row comes in over', 'albums'],
    ['coverflow.shelf.slide_ms', 'Letter to letter slide', 'ms'],
    ['coverflow.shelf.fold_near', 'Letter row folds within', ''],
    ['coverflow.shelf.arch_at', 'Arch: from', 'albums per second'],
    ['coverflow.shelf.arch_full', 'Arch: full at', 'albums per second, past Arch: from'],
    ['coverflow.shelf.arch_span', 'Arch: span', '0: none; else 100 or more'],
    ['coverflow.shelf.arch_in', 'Arch: forms over', 'ms'],
    ['coverflow.shelf.arch_out', 'Arch: relaxes over', 'ms'],
    ['coverflow.shelf.arch_tau', 'Arch: covers follow by', 'ms'],
    ['coverflow.caption.name_px', 'Album name size', ''],
    ['coverflow.caption.artist_px', 'Artist size', ''],
    ['coverflow.caption.text_y', 'Caption y', ''],
    ['coverflow.caption.artist_y', 'Artist line, px under the name', ''],
    ['coverflow.land.ms', 'Flight time', 'ms; 0: no landing'],
    ['coverflow.land.travel', 'Travel', 'percent of the way'],
    ['coverflow.land.press', 'Press', ''],
    ['coverflow.land.out_at', 'Panel fades out from', 'ms'],
    ['coverflow.land.out_ms', 'Panel fade-out time', 'ms'],
    ['coverflow.land.np_at', 'Now Playing fades in from', 'ms'],
    ['coverflow.land.np_ms', 'Now Playing fade-in time', 'ms'],
    ['coverflow.land.hold', 'Landed art held at most', 'ms'],
    // ---- motion
    ['motion.page.ms', 'Time', 'ms'],
    ['motion.page.easing', 'Easing', ''],
    ['motion.page.anim', 'Animation', ''],
    ['motion.playing.ms', 'Time', 'ms'],
    ['motion.playing.easing', 'Easing', ''],
    ['motion.playing.anim', 'Animation', ''],
    ['motion.coverflow.ms', 'Time', 'ms'],
    ['motion.coverflow.easing', 'Easing', ''],
    ['motion.coverflow.anim', 'Animation', ''],
    ['motion.inplace.ms', 'Time', 'ms'],
    ['motion.inplace.easing', 'Easing', ''],
    ['motion.swap.ms', 'Time', 'ms'],
    ['motion.swap.easing', 'Easing', ''],
    ['motion.step.ms', 'Time', 'ms'],
    ['motion.step.easing', 'Easing', ''],
    ['motion.step_fast.ms', 'Time', 'ms'],
    ['motion.step_fast.easing', 'Easing', ''],
    ['motion.coverflow_step.ms', 'Time', 'ms; under follow, its time constant'],
    ['motion.coverflow_step.easing', 'Easing', 'follow is only for Cover Flow’s steps'],
    ['motion.coverflow_step_fast.ms', 'Time', 'ms; under follow, its time constant'],
    ['motion.coverflow_step_fast.easing', 'Easing', 'follow is only for Cover Flow’s steps'],
    ['motion.recall.ms', 'Time', 'ms'],
    ['motion.bump.px', 'Distance', 'px; 0: none'],
  ];
  const LABEL_OF = new Map(LABELS.map((row) => [row[0], row]));

  // Whether the preview shows a key (DRAWING.md section 11): [kind, where, prefix, attributes, also]. also: what
  // else the key does on the Q2 that no preview screen shows (the editor says so beside it). kind 'shown':
  // a screen changes with it; 'state': only in the state named; 'no': nothing the preview draws reads it.
  // Cover Flow's and motion's keys are 'no' by their prefix.
  const PREVIEW = [
    ['shown', 'every screen', 'geometry.', 'set'],
    ['shown', 'Home, the lists and the stock confirm', 'list.selection.', 'painter'],
    ['shown', 'the lists, and Home in Full', 'list.chevron.', 'selected x'],
    ['shown', 'a cover list on a set whose cover rows are taller than its pitch (Classic’s)', 'list.art.', 'x text_x text_end'],
    ['shown', 'the grey tile in Songs’ rows under the built-in set', 'list.art.', 'placeholder'],
    ['shown', 'a two-line list on a set without text artwork', 'list.row.', 'text_end'],
    ['shown', 'the lists; it also picks the face of text the firmware draws itself', 'list.row.', 'font title_px'],
    ['shown', 'second lines; stating either also turns them grey', 'list.row.', 'meta_font meta_px'],
    ['shown', 'titles of rows taller than the set’s pitch', 'list.row.', 'tall_font tall_px'],
    ['shown', 'a two-line list', 'list.separator.', 'stops'],
    ['shown', 'lists longer than the window', 'list.scrollbar.', 'w right top bottom min thumb'],
    ['shown', 'the Library’s and the settings’ icons', 'list.icons.', 'mono'],
    ['state', 'the fast-scroll letter', 'list.letter.', 'raw px'],
    ['no', 'file-type badges (Folder view, album tracks)', 'list.icons.', 'badge_muted'],
    ['no', 'a card app’s Streaming icon', 'list.icons.', 'addon_mono'],
    ['no', 'the Bluetooth codec badge', 'list.icons.', 'badge_ink'],
    ['shown', 'the settings list', 'settings.', 'rows.top values.text'],
    ['shown', 'Home', 'home.rows.', 'top full_row text_x label_end_split label_end_full font font_px caps'],
    ['shown', 'Home', 'home.chevron.', 'visible x'],
    ['state', 'Home in Split with nothing playing', 'home.pane.', 'stops icon_x icon_y note_x note_y count_y count_w count_px light_a'],
    ['state', 'Home in Split', 'home.pane.', 'shadow shadow_w shadow_a'],
    ['no', 'Home’s Streaming list', 'home.pane.', 'svc_x svc_y svc_px'],
    ['shown', 'the status bar', 'bar.fill.', 'painter'],
    ['shown', 'the status bar on a set with bar_px; no effect on the built-in set', 'bar.title.', 'font font_size'],
    ['state', 'the idle "Q2" mark: the built-in set, nothing playing', 'bar.title.', 'caps'],
    ['shown', 'the battery', 'bar.battery.', 'painter stops line empty edge corner_a foot_a shade_a soft_a soft_top_a emboss_a emboss_nub_a'],
    ['state', 'a low battery', 'bar.battery.', 'low low_w'],
    ['state', 'charging, or full on power', 'bar.battery.', 'bolt bolt_halo_a'],
    ['state', 'playing or paused, under the classic-light battery', 'bar.state.', 'stops edge halo_light halo_dark'],
    ['state', 'Bluetooth or Wi-Fi showing', 'bar.icons.', 'bt_dy wifi_dy'],
    ['shown', 'Now Playing', 'playing.', 'layout'],
    ['shown', 'Now Playing’s title; the built-in set’s bar title with Time in Title off', 'playing.title.', 'font font_px'],
    ['shown', 'Now Playing in the iPod layout', 'playing.album.', 'caps opacity'],
    ['shown', 'Now Playing', 'playing.state.', 'opacity'],
    ['shown', 'Now Playing’s art and the lists’ covers', 'playing.art.', 'square'],
    ['shown', 'Now Playing’s bar', 'playing.scrubber.', 'height stops fill'],
    ['state', 'scrubbing', 'playing.scrubber.', 'scrub_height'],
    ['state', 'the classic-light volume panel', 'playing.scrubber.', 'dark_track dark_fill light_track light_fill'],
    ['no', 'a card app’s progress row', 'playing.scrubber.', 'painter'],
    ['no', 'Now Playing’s info page and other small captions', 'playing.info.', 'font font_size value'],
    ['no', 'Internet Radio’s cover', 'playing.station.', 'stops mast band_a shadow_a'],
    ['state', 'the volume over a page other than Now Playing', 'volume.panel.', 'painter'],
    ['shown', 'the confirm dialog', 'dialog.confirm.', 'painter'],
    ['shown', 'the light half: at 0 the theme’s white art (Classic’s, or the flat look’s pane and Now Playing marks) turns to ink', 'pages.own.', 'art_final'],
    // its own pages are on no preview screen; what the flat bit and the classic bit change elsewhere is
    ['shown', 'Home’s pane where no cover shows, Now Playing’s marks and the flat confirm’s lit cell', 'pages.own.', 'painter',
      'Its own pages are not on a preview screen: on the Q2 it gives Quick Settings, the slider pages, the message screens and Set Date and Time Classic’s look, the flat look, or both'],
    ['no', 'Classic’s own full-screen pages on the Q2 (the lock screen’s info page)', 'pages.own.', 'fill'],
    ['no', 'the flat Quick Settings on the Q2: the ground round its cards in the light half', 'pages.quick.', 'light_ground'],
    ['no', 'the flat Set Date on the Q2: the space between its fields', 'pages.date.', 'gap'],
    ['no', 'the firmware’s own list pages (Spotify, Games, Photos, ...)', 'page.',
      'rows.height rows.detail_height rows.text_x rows.title_y rows.title_h rows.detail_y rows.detail_h title.height'],
    ['shown', 'everything, in the light half', 'scheme.', 'paper ink mode'],
    ['shown', 'the card selection, text on it, and the progress fill', 'scheme.', 'card fill'],
    ['shown', 'grey icons; under a card scheme the chevron', 'scheme.', 'chevron'],
    ['shown', 'Classic-style second lines, "3 of 12" and the times', 'scheme.', 'muted'],
    ['shown', 'the dark half: stock’s red stays red', 'scheme.', 'raw_red'],
    ['shown', 'the status bar', 'scheme.', 'bar_light bar.stops bar.line bar.line2'],
    ['shown', 'the stops selection, the gloss bar’s played part and the confirm cell', 'scheme.sel.', 'stops top edge text'],
    ['shown', 'the selection on rows taller than the set’s pitch', 'scheme.sel.', 'tall_edge tall_line tall_top'],
  ];
  const PREVIEW_OF = new Map();
  for (const [kind, where, prefix, attrs, also] of PREVIEW) for (const a of attrs.split(' ')) PREVIEW_OF.set(prefix + a, also ? { kind, where, also } : { kind, where });

  // { kind: 'shown' | 'state' | 'no', where, also? } for a key's path.
  function preview(path) {
    if (PREVIEW_OF.has(path)) return PREVIEW_OF.get(path);
    if (path.startsWith('coverflow.')) return { kind: 'no', where: 'Cover Flow' };
    if (path.startsWith('motion.')) return { kind: 'no', where: 'animation; a still preview shows none' };
    return { kind: 'no', where: 'not known to the preview' };
  }

  const SCHEME_SECTION = { 'sel.': 'scheme.sel', 'bar.': 'scheme.bar', bar_light: 'scheme.bar', paper: 'scheme.light', ink: 'scheme.light', mode: 'scheme.light' };
  const humanise = (word) => word.replace(/[_.]/g, ' ').replace(/^./, (c) => c.toUpperCase());

  // A key's group id and section id, from where theme.xml states it.
  function placeOf(k) {
    if (k.xml.tag === 'colorScheme') {
      const hit = Object.keys(SCHEME_SECTION).find((p) => k.xml.attr === p || (p.endsWith('.') && k.xml.attr.startsWith(p)));
      return { group: 'schemes', section: hit ? SCHEME_SECTION[hit] : 'scheme.marks' };
    }
    if (k.xml.tag === 'geometry') return { group: 'geometry', section: 'geometry.' };
    const group = GROUPS.find((g) => g.views.includes(k.xml.view));
    return { group: group ? group.id : 'advanced', section: `${k.xml.view}.${k.xml.element || ''}` };
  }

  // The schema's keys as the editor lists them: [{ id, title, views, screens, folded, sections: [{ id, title, keys:
  // [{ path, label, hint, kind, where }] }] }]. A key this file has no label for (a newer official.json) is
  // still listed, last in its section, under its attribute's name.
  function groups(official) {
    const out = GROUPS.map((g) => ({ id: g.id, title: g.title, views: g.views, screens: g.screens, folded: Boolean(g.folded), sections: [] }));
    const add = (k, label, hint) => {
      const place = placeOf(k);
      const group = out.find((g) => g.id === place.group);
      let section = group.sections.find((s) => s.id === place.section);
      if (!section) group.sections.push(section = { id: place.section, title: SECTIONS[place.section] || humanise(place.section), keys: [] });
      section.keys.push(Object.assign({ path: k.path, label, hint }, preview(k.path)));
    };
    const seen = new Set();
    for (const [path, label, hint] of LABELS) {
      const k = official.key(path);
      if (!k || seen.has(path)) continue;
      seen.add(path);
      add(k, label, hint);
    }
    for (const k of official.keys) if (!seen.has(k.path)) add(k, humanise(k.xml.attr), '');
    return out;
  }

  // A key's label alone.
  const label = (path) => (LABEL_OF.has(path) ? LABEL_OF.get(path)[1] : humanise(path.split('.').pop()));

  // The fields of a geometry set: [heading, [[field, label], ...]]. UNREAD: fields no preview screen reads.
  const GEOMETRY = [
    ['Status bar', [['bar', 'Bar height'], ['bar_px', 'Title and clock size (0: stock’s bar, no title)'], ['bar_title_w', 'Title width'],
      ['bar_right', 'Right group’s margin'], ['batt_w', 'Battery body width'], ['batt_h', 'Battery body height']]],
    ['Rows', [['pitch', 'Row pitch'], ['body', 'Row body'], ['text_x', 'Text’s left edge (0: stock’s)'], ['title24_y', 'Large title y'],
      ['title_y', 'Title y'], ['meta_y', 'Second line y'], ['count_y', 'Playlist count y'], ['list_end', 'Row where a selected row’s scroll stops (0: stock’s)']]],
    ['Cover rows', [['art', 'Cover size (0: text rows)'], ['art_inset', 'Cover inset'], ['art_pitch', 'Cover row pitch'], ['art_body', 'Cover row body'],
      ['art_title24_y', 'Cover row title y'], ['art_meta_y', 'Cover row second line y'], ['text_art', 'Text page artwork size (0 hides it)'],
      ['text_art_inset', 'Text page artwork inset']]],
    ['Library', [['lib_pitch', 'Row pitch'], ['lib_body', 'Row body'], ['lib_art', 'Icon size (0 hides it)'], ['lib_inset', 'Icon inset']]],
    ['Songs', [['song_pitch', 'Row pitch'], ['song_body', 'Row body'], ['song_title24_y', 'Title y'], ['song_meta_y', 'Second line y'],
      ['action_row', 'Play All as a plain row this high (0: stock’s 50 px bar)']]],
    ['Settings', [['set_row', 'Row height'], ['set_top', 'List top'], ['set_rows', 'Rows on a page'], ['set_icon', 'Icon size (0 hides it)'],
      ['stream_row', 'Streaming settings row height']]],
    ['Home and Now Playing', [['home_row', 'Home row height'], ['home_lib', 'Library slides in on Home (0 or 1)'],
      ['np_ipod', 'Now Playing as an iPod classic’s (0 or 1)']]],
    ['Stock’s own list pages', [['stock_row', 'Row pitch'], ['stock_body', 'Row body'], ['stock_title_y', 'Title y'], ['stock_title_h', 'Title box height'],
      ['toolbar', 'Toolbars (0 hides them)']]],
    ['Search', [['search_row', 'Row pitch'], ['search_body', 'Row body'], ['search_art', 'Artwork size (0: two lines of text)'], ['search_title_y', 'Title y'],
      ['search_title24_y', 'Large title y'], ['search_title_h', 'Title box height'], ['search_meta_y', 'Second line y'], ['search_meta_h', 'Second line box height']]],
  ];
  const UNREAD = new Set(['count_y', 'title_y', 'stream_row', 'stock_row', 'stock_body', 'stock_title_y', 'stock_title_h', 'search_row', 'search_body',
    'search_art', 'search_title_y', 'search_title24_y', 'search_title_h', 'search_meta_y', 'search_meta_h', 'toolbar', 'set_top', 'body', 'title24_y', 'meta_y',
    'home_lib']);

  // A set's fields as the editor lists them: [{ title, fields: [{ name, label, read }] }]; read: a preview
  // screen reads it. A field with no label here is listed last, under its name.
  function geometryGroups(official) {
    const names = official.data.geometry.fields.map((f) => f.name);
    const out = GEOMETRY.map(([title, fields]) => ({
      title, fields: fields.filter(([name]) => names.includes(name)).map(([name, text]) => ({ name, label: text, read: !UNREAD.has(name) })),
    }));
    const listed = new Set(out.flatMap((g) => g.fields.map((f) => f.name)));
    const rest = names.filter((n) => !listed.has(n));
    if (rest.length) out.push({ title: 'Other', fields: rest.map((name) => ({ name, label: humanise(name), read: false })) });
    return out;
  }

  // ------------------------------------------------------------------------------- the viewer's switches

  const SETTING_TITLES = { light: 'Light Mode', accent: 'Accent', corners: 'Rounded Corners', home: 'Home Layout', battery: 'Battery',
    shortcut: 'Home Shortcut', time_title: 'Time in Title', np_layout: 'Now Playing' };
  const VALUE_TITLES = { 'corners.square': 'Off', 'corners.round': 'On', 'battery.both': 'Icon + Percent', 'battery.inside': 'Percent Inside',
    'np_layout.ipod': 'iPod', 'np_layout.centred': 'Centred', 'shortcut.rockbox': 'Rockbox' };
  const settingTitle = (name) => SETTING_TITLES[name] || humanise(name);
  const valueTitle = (setting, value) => VALUE_TITLES[`${setting}.${value}`] || String(value).split('_').map((w) => humanise(w)).join(' ');
  const bit = (mask, i) => Math.floor(Number(mask) / 2 ** i) % 2 === 1;

  // The Appearance settings that change the drawing, for a resolved theme, in its own rows' order:
  // [{ id, title, own, values: [{ value, title }] }]. Light Mode and the accent have controls of their own.
  function viewerControls(official, resolved) {
    const settings = official.data.settings;
    const out = [];
    for (const o of resolved.opts) {
      if (o.setting === 'SETTING_OWN') {
        out.push({ id: o.key, title: o.label, own: true, values: o.names.map((n) => ({ value: n, title: n })) });
        continue;
      }
      const name = Object.keys(settings).find((s) => settings[s].macro === o.setting);
      if (!name || name === 'light' || name === 'accent') continue;
      const values = settings[name].values.filter((v, i) => !o.values || bit(o.values, i));
      out.push({ id: name, title: settingTitle(name), own: false, values: values.map((v) => ({ value: v, title: valueTitle(name, v) })) });
    }
    return out;
  }

  // The schemes a resolved theme offers: [{ name, title, index, colour }]; colour: a swatch for the picker.
  function accents(official, resolved) {
    const data = official.data;
    return official.schemeNames(resolved).map((name, index) => {
      const s = resolved.schemes[index];
      const tones = data.accents[index < data.accents.length ? index : s.base || 0].tones;
      const band = (s.sel && s.sel.length && s.sel[Math.floor(s.sel.length / 2)][1]) || 0;
      return { name, index, title: s.label || humanise(name), colour: band || (s.card ? s.fill : 0) || tones[2] || tones[0] };
    }).filter((a) => bit(resolved.accents, a.index));
  }

  // ------------------------------------------------------------------------------- where a value comes from

  const blanks = new WeakMap();
  // The format's defaults, resolved: what a theme that extends nothing starts from.
  function blank(official) {
    if (!blanks.has(official)) {
      blanks.set(official, official.resolve({ id: 'blank', name: 'Blank', index: 0, extends: null, geometry: { sets: [], set: null },
        schemes: { all: { values: {}, light: {} }, named: [], offered: null, derive: false }, values: {}, light: {}, options: null }));
    }
    return blanks.get(official);
  }

  // A theme with everything the value-source questions need: its resolved values, what each half draws, and
  // the same of what it starts from (the theme it extends, or the format's defaults).
  function context(official, theme) {
    const resolved = official.resolve(theme);
    const builtin = theme.extends === null ? null : official.data.themes.find((b) => b.id === theme.extends);
    const base = builtin ? builtin.resolved : blank(official);
    return {
      theme, resolved, drawn: official.drawn(resolved), names: official.schemeNames(resolved),
      base, baseDrawn: official.drawn(base), baseNames: official.schemeNames(base), baseName: builtin ? builtin.resolved.name : null,
      supplied: official.supplied(theme.id),
    };
  }

  // 'theme': this theme states it; 'firmware': the firmware's sources give it (a built-in's id) and it
  // cannot be stated; 'base': the theme it extends has this value; 'default': the format's own; 'derived':
  // worked out from other values (the other half's flipped, a gloss turned to the accent).
  const origin = (stated, fixed, value, baseValue, hasBase) => (stated ? 'theme' : fixed ? 'firmware' : same(value, baseValue) ? (hasBase ? 'base' : 'default') : 'derived');

  // Where a view key's value comes from. half: 'dark' or 'light' for a final key (dark when left out), not
  // given for the rest. Returns { path, half, value, baseValue, stated, fixed, from }: value is what the
  // firmware draws in that half; stated: this theme states that slot itself, so it can be reset.
  function valueSource(official, ctx, path, half) {
    const k = official.key(path);
    if (k.xml.tag === 'geometry') {
      const stated = ctx.theme.geometry.set !== null;
      return { path, half: null, value: ctx.resolved.geom_set, baseValue: ctx.base.geom_set, stated, fixed: false,
        from: origin(stated, false, ctx.resolved.geom_set, ctx.base.geom_set, ctx.baseName !== null) };
    }
    const light = k.final && half === 'light';
    const pick = (t, d) => (k.final ? d.theme[k.field][light ? 1 : 0] : t[k.field]);
    const value = pick(ctx.resolved, ctx.drawn);
    const baseValue = pick(ctx.base, ctx.baseDrawn);
    const stated = own(light ? ctx.theme.light : ctx.theme.values, path);
    const fixed = own(ctx.supplied, path);
    return { path, half: k.final ? (light ? 'light' : 'dark') : null, value, baseValue, stated, fixed, from: origin(stated, fixed, value, baseValue, ctx.baseName !== null) };
  }

  // Where a scheme's value comes from. name: a scheme, or null for "every scheme" (shown: the scheme whose
  // value stands for them all). attr: 'sel.stops', 'paper'. Returns valueSource's shape plus fromName; from
  // may also be 'all' (this theme states it for every scheme), 'accent' (an own scheme's base accent has it)
  // or 'each' (every scheme: nothing stated for them all).
  function schemeSource(official, ctx, name, attr, half, shown) {
    const k = official.key(`scheme.${attr}`);
    const lightOnly = !k.xml.forms.includes('plain'); // paper and ink
    const light = k.final && half === 'light';
    const slot = light || lightOnly ? 'light' : 'values';
    const painted = (t, d, names, n) => {
      const i = names.indexOf(n);
      return i < 0 ? undefined : k.final ? d.schemes[i][light ? 1 : 0][k.field] : t.schemes[i][k.field];
    };
    const shownHalf = k.final ? (light ? 'light' : 'dark') : lightOnly ? 'light' : null;
    const fixed = own(ctx.supplied, k.path);
    const all = own(ctx.theme.schemes.all[slot], attr);
    if (name === null || name === undefined) {
      const value = painted(ctx.resolved, ctx.drawn, ctx.names, shown === undefined ? ctx.names[0] : shown);
      return { path: k.path, half: shownHalf, value, baseValue: undefined, stated: all, fixed, from: all ? 'theme' : fixed ? 'firmware' : 'each', fromName: null };
    }
    const entry = ctx.theme.schemes.named.find((s) => s.name === name);
    const stated = Boolean(entry) && own(entry[slot], attr);
    const value = painted(ctx.resolved, ctx.drawn, ctx.names, name);
    const index = ctx.names.indexOf(name);
    const inBase = ctx.baseNames.includes(name);
    // a scheme of the theme's own starts from the accent it names as its base
    const accent = !inBase && index >= 0 && ctx.resolved.schemes[index].base !== undefined ? official.accentNames[ctx.resolved.schemes[index].base] : null;
    const baseValue = inBase ? painted(ctx.base, ctx.baseDrawn, ctx.baseNames, name) : accent ? painted(ctx.resolved, ctx.drawn, ctx.names, accent) : undefined;
    let from = origin(stated, fixed, value, baseValue, ctx.baseName !== null);
    if (!stated && all) from = 'all';
    else if (from === 'base' && accent) from = 'accent';
    else if (from === 'default' && accent) from = 'accent';
    return { path: k.path, half: shownHalf, value, baseValue, stated, fixed, from, fromName: from === 'accent' ? accent : null };
  }

  // A source in a few words, for the mark beside a control.
  function fromWords(source, ctx) {
    if (source.from === 'theme') return 'this theme';
    if (source.from === 'all') return 'this theme, every scheme';
    if (source.from === 'firmware') return 'the firmware’s sources';
    if (source.from === 'base') return `${ctx.baseName}’s`;
    if (source.from === 'accent') return `${humanise(source.fromName)}’s`;
    if (source.from === 'each') return 'each scheme’s own';
    if (source.from === 'default') return 'the format’s default';
    return source.half === 'light' ? 'follows the dark half' : source.half === 'dark' ? 'follows the light half' : 'worked out';
  }

  // ------------------------------------------------------------------------------- undo and redo

  const LIMIT = 200; // undo steps kept
  const MERGE_MS = 1000; // edits of one control this close together are one step (a colour picker's drag)

  // A theme with its past and future: { present, past, future, saved }. present is only ever replaced.
  function history(theme) {
    return { present: clone(theme), past: [], future: [], saved: JSON.stringify(theme), tag: null, at: 0 };
  }

  // Changes the present theme by fn(theme), which edits a copy through official.js. A refusal thrown by fn
  // leaves everything as it was and is thrown on. tag and now: a change with the tag of the one before it,
  // within MERGE_MS, joins that step. Returns whether anything changed.
  function change(h, fn, tag = null, now = 0) {
    const next = clone(h.present);
    fn(next);
    if (same(next, h.present)) return false;
    const joins = tag !== null && tag === h.tag && now - h.at < MERGE_MS && h.past.length > 0;
    if (!joins) {
      h.past.push(h.present);
      if (h.past.length > LIMIT) h.past.shift();
    }
    h.present = next;
    h.future = [];
    h.tag = tag;
    h.at = now;
    return true;
  }

  function undo(h) {
    if (!h.past.length) return false;
    h.future.push(h.present);
    h.present = h.past.pop();
    h.tag = null;
    return true;
  }

  function redo(h) {
    if (!h.future.length) return false;
    h.past.push(h.present);
    h.present = h.future.pop();
    h.tag = null;
    return true;
  }

  const canUndo = (h) => h.past.length > 0;
  const canRedo = (h) => h.future.length > 0;
  // Whether the theme differs from what was last saved or opened (undoing back to it is clean again).
  const dirty = (h) => JSON.stringify(h.present) !== h.saved;
  const markSaved = (h) => { h.saved = JSON.stringify(h.present); h.tag = null; };

  // ------------------------------------------------------------------------------- starting and exporting

  class StudioError extends Error {}

  // An id made from a name: 'Dusk Blue' -> 'dusk-blue'. Empty when the name has no letter or digit to use.
  function suggestId(name) {
    const id = String(name).normalize('NFKD').toLowerCase().replace(/[^a-z0-9_]+/g, '-').replace(/^[-_]+|[-_]+$/g, '');
    return /^[a-z]/.test(id) ? id : id ? `t-${id}` : '';
  }

  // A new theme from a built-in. mode 'extend': a theme that extends it and states nothing yet. mode 'copy':
  // the built-in's own statements under the new id (with what the firmware's sources supply that built-in
  // stated too), so the theme no longer follows it; it extends what the built-in extended. Either is
  // refused in official.js's words; an id that is a built-in's is refused here.
  function startTheme(official, { base, mode, id, name }) {
    const builtin = official.data.themes.find((b) => b.id === base);
    if (!builtin) throw new StudioError(`There is no built-in theme "${base}".`);
    if (official.builtinIds.includes(id)) throw new StudioError(`"${id}" is a built-in theme’s id. Choose another.`);
    const index = official.data.themes.length;
    if (mode !== 'copy') return official.newTheme({ extends: base, id, name, index });
    const theme = official.read(builtin.text);
    official.rename(theme, { id, name, index });
    for (const [path, value] of Object.entries(official.supplied(base))) {
      if (path.startsWith('scheme.')) official.setScheme(theme, null, path, value);
      else official.set(theme, path, value);
    }
    // Classic's art_final is its id's alone; the flat look's (Modern's, Classic Modern's) is any theme's
    const resolved = official.resolve(theme);
    if (resolved.art_final && !flatPages(official, resolved)) official.set(theme, 'pages.own.art_final', 0);
    return theme;
  }

  // The theme.xml the page exports: official.js's write() and nothing else.
  const exportText = (official, theme) => official.write(theme);
  // Where the file belongs in a q2-pod checkout.
  const repoPath = (theme) => `assets/themes/${theme.id}/theme.xml`;

  // A refusal in plain words: official.js's own where it has them.
  function refusalWords(official, error) {
    const detail = error && (error.detail || error.message);
    return official && error && error.detail ? official.explain(detail) : String(detail);
  }

  // ------------------------------------------------------------------------------- problems

  const TARGETS = [
    [/^selection: painter stops/, () => ({ path: 'list.selection.painter' })],
    [/^battery: this painter needs stops/, () => ({ path: 'bar.battery.stops' })],
    [/^pages\.own: art_final/, () => ({ path: 'pages.own.art_final' })],
    [/^list\.scrollbar: (top|bottom)\b/, (m) => ({ path: `list.scrollbar.${m[1]}` })],
    [/^list\.scrollbar: no min/, () => ({ path: 'list.scrollbar.min' })],
    [/^list\.scrollbar: no thumb/, () => ({ path: 'list.scrollbar.thumb' })],
    [/^coverflow\.shelf: (?:thumb|arch_span) needs (\w+)/, (m) => ({ path: `coverflow.shelf.${m[1]}` })],
    [/^coverflow\.shelf: (\w+)\b/, (m) => ({ path: `coverflow.shelf.${m[1]}` })],
    [/^coverflow\.land: ms needs travel/, () => ({ path: 'coverflow.land.travel' })],
    [/^coverflow\.land: (\w+)_at\b/, (m) => ({ path: `coverflow.land.${m[1]}_ms` })],
    [/^coverflow\.caption: text_y/, () => ({ path: 'coverflow.caption.text_y' })],
    [/^page\.rows: (title|detail) box/, (m) => ({ path: `page.rows.${m[1]}_h` })],
    [/^light: a scheme with its own mode/, () => ({ path: 'scheme.mode' })],
    // the set's np_ipod and the bar's stops come together: a built-in set cannot change, the stops can
    [/^set \S+'s np_ipod needs playing\.scrubber\.stops/, () => ({ path: 'playing.scrubber.stops' })],
    [/^geometry set |geometry sets: |^set .*np_ipod|^unknown geometry set/, () => ({ panel: 'geometry' })],
    [/^(?:no accent option|accent: no key|accent (?:default|preset) |accent: slot 0|accent key )/, () => ({ panel: 'options', option: 'accent' })],
    [/^colorSchemes is empty|^\d+ accents, at most|^scheme .* is not in colorSchemes|^unknown scheme /, () => ({ panel: 'schemes' })],
    [/^([A-Z][A-Z0-9_]*): (?:default .* boots|set .* has a )/, (m) => ({ panel: 'options', option: m[1] })],
    [/^(\S+) declared twice$/, (m) => ({ panel: 'options', option: m[1] })],
    [/^(SETTING_\w+): default has no effect/, (m, official) => ({ panel: 'options', option: Object.keys(official.data.settings).find((n) => official.data.settings[n].macro === m[1]) })],
    [/^(\S+): default has no effect/, () => ({ panel: 'options' })],
    [/^([A-Z][A-Z0-9_]*) is .*'s, with other values or default$/, (m) => ({ panel: 'options', option: m[1] })],
    [/^one option per theme| runs on .*'s set, with other options$| is .*'s, with other values or default$/, () => ({ panel: 'options' })],
    [/^(?:index |id |name: |extends )/, () => ({ panel: 'theme' })],
  ];

  // The control a problem is about: { panel, path?, section?, option? }. panel: a group's id, or 'theme' or
  // 'options'. problem: one of official.problems()'s, or the tool's message itself.
  function problemTarget(official, problem) {
    const message = String(typeof problem === 'string' ? problem : problem.tool).replace(/^[^:\s]*:\d+: /, '');
    const of = (path) => {
      const k = official.key(path);
      return k ? { panel: placeOf(k).group, path, section: placeOf(k).section } : null;
    };
    for (const [pattern, make] of TARGETS) {
      const m = pattern.exec(message);
      if (!m) continue;
      const hit = make(m, official);
      if (hit.path) {
        const found = of(hit.path);
        if (found) return found;
        continue;
      }
      return hit;
    }
    let best = null;
    for (const k of official.keys) {
      const at = message.indexOf(k.path);
      const after = at < 0 ? '' : message[at + k.path.length] || '';
      if (at >= 0 && !/[\w.]/.test(after) && (!best || k.path.length > best.length)) best = k.path;
    }
    if (best) return of(best);
    const element = official.data.xml.elements.filter((e) => message.includes(e)).sort((a, b) => b.length - a.length)[0];
    if (element) {
      const k = official.keys.find((x) => x.xml.tag === 'view' && `${x.xml.view}.${x.xml.element}` === element);
      if (k) return { panel: placeOf(k).group, section: element };
    }
    if (/geometry\.|\bset\b/.test(message)) return { panel: 'geometry' };
    if (/option|SETTING_/.test(message)) return { panel: 'options' };
    return { panel: 'theme' };
  }

  // ------------------------------------------------------------------------------- colours and stops

  const hex = (c) => `#${(Number(c) % 0x1000000).toString(16).padStart(6, '0')}`;
  // A stops list as a CSS gradient along a strip; an empty list is no picture.
  const stopsCss = (stops) => (stops && stops.length ? `linear-gradient(to right, ${stops.map(([p, c]) => `${hex(c)} ${p}%`).join(', ')})` : 'none');
  // A rows list (0xAARRGGBB each) as a strip of equal bands.
  function rowsCss(rows) {
    if (!rows || !rows.length) return 'none';
    const rgba = (r) => `rgba(${(r >> 16) & 255}, ${(r >> 8) & 255}, ${r & 255}, ${(Math.floor(r / 0x1000000) / 255).toFixed(3)})`;
    return `linear-gradient(to right, ${rows.map((r, i) => `${rgba(r)} ${(i * 100) / rows.length}% ${((i + 1) * 100) / rows.length}%`).join(', ')})`;
  }
  const mixColour = (a, b) => [16, 8, 0].reduce((sum, s) => sum + (Math.round((((a >> s) & 255) + ((b >> s) & 255)) / 2) << s), 0);

  // A stops list with one more stop, in the middle of its widest gap; unchanged when no whole position is free.
  function stopsAdd(stops) {
    let at = -1;
    let gap = 1;
    stops.forEach((s, i) => {
      if (i + 1 < stops.length && stops[i + 1][0] - s[0] > gap) {
        gap = stops[i + 1][0] - s[0];
        at = i;
      }
    });
    if (at < 0) return stops.map((s) => s.slice());
    const made = [Math.floor((stops[at][0] + stops[at + 1][0]) / 2), mixColour(stops[at][1], stops[at + 1][1])];
    return [...stops.slice(0, at + 1), made, ...stops.slice(at + 1)].map((s) => s.slice());
  }
  const stopsRemove = (stops, i) => stops.filter((s, n) => n !== i).map((s) => s.slice());
  const stopsSet = (stops, i, position, colour) => stops.map((s, n) => (n === i ? [position === undefined ? s[0] : position, colour === undefined ? s[1] : colour] : s.slice()));

  // =============================================================================== the page

  function page(window) {
    const document = window.document;
    const Q2Official = window.Q2Official;
    const Q2Draw = window.Q2Draw;
    const $ = (id) => document.getElementById(id);

    let official = null;
    let tree = []; // groups(official)
    // What the page shows. hist: the theme and its undo steps (null on the start page). ctx: context() of
    // the present theme. nav: the open editor group. choices: the viewer's switches, as Q2Draw.env takes
    // them. show: the status bar's state. refusal: the last refused edit, { ctl, words }.
    const S = {
      hist: null, ctx: null, nav: 'theme', screen: 'home', stateOf: {}, choices: {},
      show: { play: 'playing', battery: 'normal', bt: 'off', glass: false },
      scheme: null, set: null, refusal: null, open: new Set(), problems: [], size: { s: 1.5, k: 2 },
      start: { base: 'minimal', mode: 'extend', name: '', id: '', idTouched: false, error: '' },
      flash: null, drawQueued: false, problemsTimer: 0, status: '', comments: false,
    };

    // ---- small DOM helpers

    const PROPS = new Set(['value', 'checked', 'disabled', 'selected', 'readOnly', 'hidden', 'open', 'htmlFor', 'type', 'min', 'max', 'step', 'title',
      'placeholder', 'rows', 'spellcheck', 'id', 'name', 'tabIndex', 'width', 'height', 'accept', 'autocomplete']);
    // An element: el('button', { class: 'small', text: 'Add', onclick: fn }, child, ...). No markup is ever
    // parsed from text, so nothing a theme file holds can become page content.
    function el(tag, props, ...kids) {
      const node = document.createElement(tag);
      for (const [k, v] of Object.entries(props || {})) {
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class') node.className = v;
        else if (k === 'text') node.textContent = v;
        else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
        else if (k === 'value' && 'defaultValue' in node) {
          // a box's committed value stays its defaultValue, so typing not yet committed can be told apart
          node.defaultValue = v;
          node.value = v;
        } else if (PROPS.has(k)) node[k] = v;
        else node.setAttribute(k, v === true ? '' : v);
      }
      return add(node, ...kids);
    }
    const clear = (node) => { while (node.firstChild) node.removeChild(node.firstChild); };
    // Appends what there is: a part that was left out (null or false) adds nothing.
    function add(node, ...kids) {
      for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) node.append(kid);
      return node;
    }
    const button = (ctl, text, onclick, props) => el('button', Object.assign({ type: 'button', class: 'small', 'data-ctl': ctl, text, onclick }, props));
    function select(ctl, options, current, disabled, onchange, labelText) {
      const node = el('select', { 'data-ctl': ctl, disabled, 'aria-label': labelText, onchange: () => onchange(node.value) },
        options.map((o) => el('option', { value: String(o.value), text: o.title })));
      node.value = String(current);
      return node;
    }

    // Rebuilds part of the page by fn and puts the keyboard focus back on the control it was on.
    function keepFocus(fn) {
      const active = document.activeElement;
      const ctl = active && active.getAttribute ? active.getAttribute('data-ctl') : null;
      fn();
      if (!ctl) return;
      const again = [...document.querySelectorAll('[data-ctl]')].find((n) => n.getAttribute('data-ctl') === ctl);
      if (again && !again.disabled) again.focus({ preventScroll: true });
    }

    function say(text) {
      S.status = text;
      $('status').textContent = text;
    }

    // Whether a text or number box holds typing that has not been committed yet (its change event has not
    // fired): its value differs from the value it was built with.
    const typingIn = (node) => Boolean(node) && (node.tagName === 'TEXTAREA' || (node.tagName === 'INPUT' && /^(text|number|search|)$/.test(node.type)))
      && !node.readOnly && node.value !== node.defaultValue;

    // Commits what is being typed in the focused box, as leaving it would.
    function commitTyping() {
      const node = document.activeElement;
      if (typingIn(node) && node.getAttribute('data-ctl')) node.dispatchEvent(new window.Event('change', { bubbles: true }));
    }

    // ---- edits

    // One edit, through official.js. fn(theme) changes a copy; when official.js refuses, the theme stays as
    // it was and the refusal's words are shown by the control ctl. soft: the control is still being moved (a
    // colour picker), so only the preview follows and the edit joins the step before it.
    function edit(ctl, fn, soft = false) {
      let ok = true;
      try {
        change(S.hist, fn, soft ? ctl : null, Date.now());
        S.refusal = null;
      } catch (e) {
        if (!(e instanceof Q2Official.ThemeError) && !(e instanceof StudioError)) throw e;
        S.refusal = { ctl, words: refusalWords(official, e) };
        ok = false;
      }
      refresh(soft && ok);
      return ok;
    }

    // After the theme changed: everything that shows it. soft: leave the controls alone.
    function refresh(soft = false) {
      S.ctx = context(official, S.hist.present);
      if (S.status) say(''); // a word about the last save or open no longer holds once the theme changes
      queueDraw();
      renderTop();
      window.clearTimeout(S.problemsTimer);
      if (soft) {
        S.problemsTimer = window.setTimeout(() => { findProblems(); renderProblems(); }, 250);
        return;
      }
      findProblems();
      keepFocus(() => {
        renderNav();
        renderPanel();
        renderViewer();
        renderProblems();
      });
    }

    function findProblems() {
      try {
        S.problems = official.problems(S.hist.present);
      } catch (e) {
        S.problems = [{ message: `The theme could not be checked: ${e.message}`, tool: e.message }];
      }
    }

    // ---- the preview

    // How large the screen is shown (s times its 375 x 320) and how many canvas pixels a screen pixel gets
    // (k, whole, so hairlines stay sharp): 2x where the window has room, 1.5x at 1100 x 700.
    function measure() {
      const dpr = window.devicePixelRatio || 1;
      const roomW = window.innerWidth - 536;
      const roomH = window.innerHeight - 216;
      const s = [3, 2.5, 2, 1.5, 1.25].find((x) => 375 * x <= roomW && 320 * x <= roomH) || 1;
      const exact = s * dpr;
      const k = Number.isInteger(exact) ? exact : Number.isInteger(exact * 2) ? exact * 2 : Math.ceil(exact);
      S.size = { s, k: Math.min(Math.max(k, 1), 8) };
      document.documentElement.style.setProperty('--screen-w', `${Math.round(375 * s)}px`);
    }

    function queueDraw() {
      if (S.drawQueued) return;
      S.drawQueued = true;
      window.requestAnimationFrame(() => {
        S.drawQueued = false;
        draw();
      });
    }

    const BATTERY = { normal: { battery: 80 }, low: { battery: 9, low: true }, charging: { battery: 55, charging: true }, full: { battery: 100, plugged: true } };

    // The named states a screen offers, and the one that is chosen (its first until one is picked).
    function statesOf(id) {
      const screen = Q2Draw && Q2Draw.screens[id];
      const list = (screen && Array.isArray(screen.states) && screen.states) || [];
      return { list, chosen: list.find((x) => x.id === S.stateOf[id]) || list[0] || null };
    }

    // The state the shown screen is drawn in: its chosen named state, then the status bar's switches. What a
    // named state says of the layout wins over the viewer's setting (it is what the state is called after).
    function screenState() {
      const { chosen } = statesOf(S.screen);
      return Object.assign({}, chosen ? chosen.state : null, BATTERY[S.show.battery], { play: S.show.play, bt: S.show.bt === 'off' ? null : S.show.bt });
    }

    // Turns the preview to a screen, and optionally to one of its states. The Player switch takes what the
    // state says is playing, so the two never disagree; it can be changed again afterwards.
    function showScreen(id, stateId) {
      S.screen = id;
      if (stateId !== undefined) S.stateOf[id] = stateId;
      const { chosen } = statesOf(id);
      if (chosen && chosen.state && chosen.state.play !== undefined) S.show.play = chosen.state.play;
      keepFocus(() => { renderTabs(); renderViewer(); });
      queueDraw();
    }

    // The drawing environment for the theme as it stands and the viewer's switches; null when it cannot be made.
    function envNow() {
      if (!Q2Draw || !S.ctx) return null;
      try {
        return Q2Draw.env(official, S.ctx.resolved, Object.assign({}, S.choices, { glass: S.show.glass }));
      } catch (e) {
        return null;
      }
    }

    function draw() {
      const canvas = $('screen');
      if (!S.hist || !S.ctx) return;
      const note = $('undrawn');
      if (!Q2Draw) {
        note.hidden = false;
        note.textContent = 'The preview’s scripts did not load.';
        return;
      }
      const { s, k } = S.size;
      canvas.width = 375 * k; // also clears it and forgets any state a failed drawing left behind
      canvas.height = 320 * k;
      canvas.style.width = `${375 * s}px`;
      canvas.style.height = `${320 * s}px`;
      const g = canvas.getContext('2d');
      g.setTransform(k, 0, 0, k, 0, 0);
      try {
        Q2Draw.render(g, S.screen, Q2Draw.env(official, S.ctx.resolved, Object.assign({}, S.choices, { glass: S.show.glass })), screenState());
        note.hidden = Boolean(Q2Draw.screens[S.screen]);
        note.textContent = `${pageName(S.screen)} is not drawn yet: only the status bar is.`;
      } catch (e) {
        note.hidden = false;
        note.textContent = `The preview could not draw this screen: ${e.message}`;
      }
    }

    const pageName = (id) => (Q2Draw.screens[id] && Q2Draw.screens[id].title) || (Q2Draw.PAGES[id] && Q2Draw.PAGES[id].name) || id;

    function renderTabs() {
      const tabs = $('tabs');
      clear(tabs);
      if (!Q2Draw) return;
      for (const id of Object.keys(Q2Draw.PAGES)) {
        const drawn = Boolean(Q2Draw.screens[id]);
        add(tabs, el('button', { type: 'button', class: `tab${id === S.screen ? ' on' : ''}${drawn ? '' : ' missing'}`, 'data-ctl': `tab:${id}`,
          'aria-pressed': String(id === S.screen), title: drawn ? null : 'Not drawn yet', text: pageName(id),
          onclick: () => showScreen(id) }));
      }
      const states = $('states');
      clear(states);
      const { list, chosen } = statesOf(S.screen);
      if (list.length < 2) return;
      add(states, el('label', { class: 'state' }, el('span', { class: 'dim', text: 'State' }),
        select('state', list.map((x) => ({ value: x.id, title: `${x.label || x.id}${x.themable === false ? ' (not themable)' : ''}` })), chosen.id, false,
          (v) => showScreen(S.screen, v), 'State of the screen'),
        chosen.themable === false ? el('span', { class: 'dim', text: 'No theme key changes this screen.' }) : null));
    }

    // The viewer's switches under the screen: the half, the accent, the Appearance settings the theme lists
    // and the status bar's state. They change the drawing only, never the theme.
    function renderViewer() {
      const box = $('viewer');
      const look = $('look');
      clear(box);
      clear(look);
      if (!Q2Draw || !S.ctx) return;
      const env = envNow();
      if (!env) return;
      const choose = (key, value) => {
        S.choices[key] = value;
        // a state that fixes the layout would hide the setting just chosen: go to one that leaves the layout
        // to the setting, with the same thing playing
        const screen = { home: 'home', np_layout: 'now-playing' }[key];
        const { list, chosen } = statesOf(screen);
        if (screen && chosen && chosen.state && chosen.state.layout !== undefined) {
          const free = list.filter((x) => !x.state || x.state.layout === undefined);
          const next = free.find((x) => x.state && x.state.play === S.show.play) || free[0];
          if (next) S.stateOf[screen] = next.id;
          else delete S.stateOf[screen];
        }
        keepFocus(() => { renderViewer(); renderTabs(); });
        queueDraw();
      };
      const half = el('div', { class: 'seg', role: 'group', 'aria-label': 'Half' }, ['dark', 'light'].map((h) => el('button', { type: 'button',
        class: `chip${env.half === h ? ' on' : ''}`, 'data-ctl': `view:half:${h}`, 'aria-pressed': String(env.half === h), text: humanise(h), onclick: () => choose('half', h) })));
      const swatches = el('div', { class: 'swatches', role: 'group', 'aria-label': 'Accent' }, accents(official, S.ctx.resolved).map((a) => {
        const b = el('button', { type: 'button', class: `swatch${a.index === env.accent ? ' on' : ''}`, 'data-ctl': `view:accent:${a.name}`, title: a.title,
          'aria-label': `Accent ${a.title}`, 'aria-pressed': String(a.index === env.accent), onclick: () => choose('accent', a.name) });
        b.style.backgroundColor = hex(a.colour);
        return b;
      }));
      add(look, half, swatches);
      const fields = el('div', { class: 'viewer-fields' });
      const field = (title, node) => add(fields, el('label', { class: 'vf' }, el('span', { text: title }), node));
      for (const c of viewerControls(official, S.ctx.resolved)) {
        const current = c.own ? c.values[env.own[c.id]] && c.values[env.own[c.id]].value : env.set[c.id];
        field(c.title, select(`view:${c.id}`, c.values, current, false, (v) => choose(c.id, v), c.title));
      }
      const show = (key, title, options) => field(title, select(`show:${key}`, options, S.show[key], false, (v) => {
        S.show[key] = v;
        queueDraw();
      }, title));
      show('play', 'Player', [{ value: 'playing', title: 'Playing' }, { value: 'paused', title: 'Paused' }, { value: 'none', title: 'Nothing playing' }]);
      show('battery', 'Battery state', [{ value: 'normal', title: '80 %' }, { value: 'low', title: 'Low' }, { value: 'charging', title: 'Charging' },
        { value: 'full', title: 'Full on power' }]);
      show('bt', 'Bluetooth', [{ value: 'off', title: 'Off' }, { value: 'on', title: 'On' }, { value: 'linked', title: 'Linked' }]);
      add(fields, el('label', { class: 'vf check' }, el('input', { type: 'checkbox', checked: S.show.glass, 'data-ctl': 'show:glass',
        onchange: (e) => { S.show.glass = e.target.checked; queueDraw(); } }), el('span', { text: 'Glass corners' })));
      add(box, fields);
    }

    // ---- the top bar

    function renderTop() {
      const has = Boolean(S.hist);
      const t = has ? S.hist.present : null;
      $('theme-name').textContent = has ? t.name : '';
      $('theme-id').textContent = has ? t.id : '';
      $('dirty').hidden = !(has && dirty(S.hist));
      $('undo').disabled = !(has && canUndo(S.hist));
      $('redo').disabled = !(has && canRedo(S.hist));
      $('save').disabled = !has;
      $('new').disabled = !has;
      document.title = `${has && dirty(S.hist) ? '• ' : ''}${has ? `${t.name} – ` : ''}Q2 Theme Studio`;
    }

    // ---- the editor's list of groups

    const NAV = () => [{ id: 'theme', title: 'Theme' }, ...tree.map((g) => ({ id: g.id, title: g.title })).filter((g) => g.id !== 'advanced'),
      { id: 'options', title: 'Options' }, { id: 'advanced', title: 'Advanced' }, { id: 'export', title: 'Export' }];

    // How many statements of its own the theme makes in a group (shown beside the group's name).
    function statedIn(id) {
      const t = S.hist.present;
      const group = tree.find((g) => g.id === id);
      if (id === 'schemes') {
        return [t.schemes.all, ...t.schemes.named].reduce((n, s) => n + Object.keys(s.values).length + Object.keys(s.light).length, 0) + (t.schemes.offered === null ? 0 : 1);
      }
      if (id === 'geometry') return t.geometry.sets.length + (t.geometry.set === null ? 0 : 1);
      if (id === 'options') return t.options === null ? 0 : t.options.length;
      if (!group) return 0;
      return group.sections.reduce((n, s) => n + s.keys.filter((k) => own(t.values, k.path) || own(t.light, k.path)).length, 0);
    }

    function go(id) {
      S.nav = id;
      S.refusal = null;
      const group = tree.find((g) => g.id === id);
      if (Q2Draw && group && group.screens && !group.screens.includes(S.screen)) showScreen(group.screens[0]);
      keepFocus(() => { renderNav(); renderPanel(); });
      $('panel').scrollTop = 0;
    }

    function renderNav() {
      const nav = $('nav');
      clear(nav);
      for (const item of NAV()) {
        const n = statedIn(item.id);
        add(nav, el('button', { type: 'button', class: `nav${item.id === S.nav ? ' on' : ''}`, 'data-ctl': `nav:${item.id}`, 'aria-current': item.id === S.nav ? 'page' : null,
          onclick: () => go(item.id) }, el('span', { text: item.title }), n ? el('span', { class: 'count', title: `${n} of this theme’s own`, text: String(n) }) : null));
      }
    }

    // ---- controls, one per type of value

    const refusalNote = (ctl) => (S.refusal && S.refusal.ctl === ctl ? el('p', { class: 'refusal', role: 'alert', text: S.refusal.words }) : null);

    function numberControl(ctl, value, lo, hi, disabled, commit, labelText) {
      const input = el('input', { type: 'number', min: String(lo), max: String(hi), step: '1', value: String(value), disabled, 'data-ctl': ctl, 'aria-label': labelText,
        onchange: () => commit(input.value.trim()) });
      return el('span', { class: 'num' }, input, el('span', { class: 'range', text: `${lo}–${hi}` }));
    }

    function switchControl(ctl, value, disabled, commit, labelText) {
      return el('label', { class: 'switch' }, el('input', { type: 'checkbox', role: 'switch', checked: Boolean(value), disabled, 'data-ctl': ctl, 'aria-label': labelText,
        onchange: (e) => commit(e.target.checked ? 1 : 0) }), el('span', { class: 'dim', text: value ? 'on' : 'off' }));
    }

    // A colour: a picker and a hex box. commit(text, soft). empty: what an unset 0 reads as ('none').
    function colourControl(ctl, value, disabled, commit, labelText, empty) {
      const unset = Boolean(empty) && !value;
      const text = el('input', { type: 'text', class: 'hex', value: unset ? '' : hex(value), placeholder: unset ? empty : '#rrggbb', disabled, spellcheck: false,
        autocomplete: 'off', 'data-ctl': `${ctl}:hex`, 'aria-label': `${labelText}, hex`, onchange: () => commit(text.value.trim().toLowerCase(), false) });
      const pick = el('input', { type: 'color', value: hex(value || 0), disabled, 'data-ctl': `${ctl}:pick`, 'aria-label': `${labelText}, picker`,
        oninput: () => { text.value = pick.value; commit(pick.value, true); }, onchange: () => commit(pick.value, false) });
      return el('span', { class: 'colour' }, pick, text);
    }

    // A stops list: a strip, then a row per stop (its position and colour), and a button to add one.
    function stopsControl(ctl, stops, disabled, commit, labelText) {
      const box = el('div', { class: 'stops' });
      let now = (stops || []).map((s) => s.slice());
      if (!now.length) {
        add(box, el('span', { class: 'dim', text: 'none' }), button(`${ctl}:add`, 'Add a gradient', () => commit([[0, 0x8a8a8a], [100, 0x5a5a5a]], false), { disabled }));
        return box;
      }
      const strip = el('div', { class: 'strip', role: 'img', 'aria-label': `${labelText}: the gradient` });
      strip.style.backgroundImage = stopsCss(now);
      add(box, strip);
      now.forEach(([position, colour], i) => {
        const end = i === 0 || i === now.length - 1;
        const at = el('input', { type: 'number', class: 'pos', min: '0', max: '100', step: '1', value: String(position), disabled: disabled || end, 'data-ctl': `${ctl}:pos${i}`,
          'aria-label': `${labelText}, stop ${i + 1} position`, onchange: () => commit(stopsSet(now, i, Number(at.value)), false) });
        const paint = colourControl(`${ctl}:c${i}`, colour, disabled, (text, soft) => {
          if (!/^#[0-9a-f]{6}$/.test(text)) return commit(now.map((s, n) => (n === i ? `${text} ${s[0]}` : `${hex(s[1])} ${s[0]}`)).join(', '), false);
          now = stopsSet(now, i, undefined, parseInt(text.slice(1), 16));
          strip.style.backgroundImage = stopsCss(now);
          return commit(now, soft);
        }, `${labelText}, stop ${i + 1} colour`);
        add(box, el('div', { class: 'stop' }, at, paint, button(`${ctl}:del${i}`, '×', () => commit(stopsRemove(now, i), false),
          { disabled: disabled || end || now.length <= 2, 'aria-label': `Remove stop ${i + 1}`, title: 'Remove this stop', class: 'small icon' })));
      });
      add(box, button(`${ctl}:add`, 'Add a stop', () => commit(stopsAdd(now), false), { disabled: disabled || now.length >= 13 }));
      return box;
    }

    // A list written as text: alphas ("116 100 93") or pixel rows ("#rrggbb #rrggbbaa ...").
    function listControl(ctl, k, value, disabled, commit, labelText) {
      const text = official.text(k.path, value || []);
      const area = el('textarea', { class: 'list', rows: k.type === 'rows' ? 3 : 2, value: text, disabled, spellcheck: false, 'data-ctl': ctl, 'aria-label': labelText,
        placeholder: k.type === 'rows' ? '#rrggbb or #rrggbbaa, up to 31' : 'up to 32 alphas, 0 to 255', onchange: () => commit(area.value.trim().replace(/\s+/g, ' '), false) });
      const box = el('div', { class: 'stops' });
      if (k.type === 'rows' && value && value.length) {
        const strip = el('div', { class: 'strip', role: 'img', 'aria-label': `${labelText}: the rows` });
        strip.style.backgroundImage = rowsCss(value);
        add(box, strip);
      }
      add(box, area, el('span', { class: 'range', text: `${(value || []).length} ${k.type === 'rows' ? 'rows' : 'alphas'}` }));
      return box;
    }

    // The control for a schema key's type. commit(value, soft) gets what official.js's set() takes.
    function control(ctl, k, value, disabled, commit, labelText) {
      if (k.type === 'bool') return switchControl(ctl, value, disabled, commit, labelText);
      if (k.choices) return select(ctl, k.choices.map((c) => ({ value: c, title: CHOICE_TITLES[c] || c })), k.choices[value], disabled, (v) => commit(v, false), labelText);
      if (k.type === 'color') return colourControl(ctl, value, disabled, commit, labelText, k.final ? 'none' : '');
      if (k.type === 'stops') return stopsControl(ctl, value, disabled, commit, labelText);
      if (k.type === 'alphas' || k.type === 'rows') return listControl(ctl, k, value, disabled, commit, labelText);
      return numberControl(ctl, value, k.lo, k.hi, disabled, commit, labelText);
    }

    // One value's line: its control, where the value comes from, and a reset when the theme states it.
    function slot(ctl, k, source, commit, reset, labelText) {
      const mine = source.from === 'theme';
      const words = fromWords(source, S.ctx);
      const line = el('div', { class: `slot${mine ? ' mine' : ''}` });
      if (source.half) add(line, el('span', { class: 'half', text: humanise(source.half) }));
      add(line, control(ctl, k, source.value === undefined ? k.default : source.value, source.fixed, commit, labelText));
      add(line, el('span', { class: `src from-${source.from}`, title: mine ? 'This theme states this value' : 'This theme does not state this value', text: words }));
      if (source.stated && reset) {
        add(line, button(`${ctl}:reset`, '↺', reset, { class: 'small icon', title: 'Reset: stop stating it', 'aria-label': `Reset ${labelText}` }));
      } else if (source.stated && source.note) add(line, el('span', { class: 'dim', text: source.note }));
      const refused = refusalNote(ctl);
      return refused ? el('div', { class: 'slot-wrap' }, line, refused) : line;
    }

    const CLASS_WORDS = { open: 'Takes effect when a page opens.', boot: 'Takes effect at a restart.', art: 'Drawn into the theme’s images when the firmware is built.',
      motion: 'How things move.' };

    // A key's row: its name, what it is, and a line per value (two for a key with a value per half).
    function row(item, slots) {
      const k = official.key(item.path);
      const title = [item.kind === 'shown' ? `The preview shows it: ${item.where}.` : '', CLASS_WORDS[k.cls] || ''].filter(Boolean).join(' ');
      return rowOf(item.path, item.label, item.path, item.hint, [
        item.kind === 'no' ? el('span', { class: 'tag no', title: `It is for ${item.where}.`, text: 'not shown in the preview' }) : null,
        item.kind === 'state' ? el('span', { class: 'tag state', text: `preview: only with ${item.where}` }) : null,
        item.also ? el('span', { class: 'tag no', title: item.also, text: 'its own pages: not in the preview' }) : null,
      ], slots, title);
    }

    // The row's parts: the label beside the values, and under them the key's name in the file, a hint and
    // whether the preview shows it.
    function rowOf(key, labelText, path, hint, tags, slots, title) {
      const name = el('div', { class: 'name', title: title || null }, el('span', { class: 'label', text: labelText }));
      const meta = el('div', { class: 'meta' }, el('code', { class: 'path', text: path }), hint ? el('span', { class: 'hint', text: hint }) : null, tags);
      return el('div', { class: `row${S.flash === key ? ' flash' : ''}`, 'data-key': key }, name, el('div', { class: 'slots' }, slots), meta);
    }

    function keyRow(item) {
      const k = official.key(item.path);
      const halves = k.final ? ['dark', 'light'] : [null];
      return row(item, halves.map((half) => {
        const ctl = `key:${k.path}${half ? `:${half}` : ''}`;
        const source = valueSource(official, S.ctx, k.path, half);
        const words = half ? `${item.label}, ${half}` : item.label;
        // Classic's art_final 1 is refused for any other id: a theme over Classic states 0 and keeps it
        const pinned = k.path === 'pages.own.art_final' && source.stated && source.value === 0 && source.baseValue === 1 && S.hist.present.id !== 'classic-light'
          && !flatPages(official, S.ctx.resolved);
        if (pinned) source.note = 'stays 0: Classic’s 1 is refused for any other theme without a flat pages style';
        return slot(ctl, k, source,
          (v, soft) => edit(ctl, (t) => official.set(t, k.path, v, half === 'light' ? 'light' : undefined), soft),
          pinned ? null : () => edit(ctl, (t) => official.unset(t, k.path, half || undefined)), words);
      }));
    }

    // A group of view keys: a heading per element, a row per key. Folded groups (Advanced) open a section
    // at a time.
    function keysPanel(group) {
      const box = el('div', { class: 'keys' });
      const t = S.hist.present;
      if (group.id === 'advanced') {
        add(box, el('p', { class: 'lead', text: 'Cover Flow’s and the motion’s numbers. The preview shows none of them.' }));
      }
      for (const section of group.sections) {
        const mine = section.keys.filter((k) => own(t.values, k.path) || own(t.light, k.path)).length;
        const heading = [el('span', { text: section.title }), mine ? el('span', { class: 'count', text: String(mine) }) : null];
        if (!group.folded) {
          add(box, el('section', { class: 'section', 'data-section': section.id }, el('h3', null, heading), section.keys.map(keyRow)));
          continue;
        }
        const open = S.open.has(section.id);
        const details = el('details', { class: 'section', 'data-section': section.id, open },
          el('summary', { 'data-ctl': `fold:${section.id}` }, heading, el('span', { class: 'dim', text: ` ${section.keys.length} values` })),
          open ? section.keys.map(keyRow) : null);
        details.addEventListener('toggle', () => {
          if (details.open === S.open.has(section.id)) return;
          if (details.open) S.open.add(section.id);
          else S.open.delete(section.id);
          keepFocus(renderPanel);
        });
        add(box, details);
      }
      return box;
    }

    // ---- the Theme panel

    function textField(ctl, title, value, commit, props) {
      const input = el('input', Object.assign({ type: 'text', value, spellcheck: false, autocomplete: 'off', 'data-ctl': ctl, onchange: () => commit(input.value) }, props));
      return el('div', { class: 'field' }, el('label', null, el('span', { class: 'label', text: title }), input), refusalNote(ctl));
    }

    function themePanel() {
      const t = S.hist.present;
      const base = t.extends === null ? null : official.data.themes.find((b) => b.id === t.extends);
      const box = el('div', { class: 'keys' });
      add(box, el('section', { class: 'section' }, el('h3', { text: 'This theme' }),
        textField('head:name', 'Name, as the Theme picker shows it', t.name, (v) => edit('head:name', (x) => official.rename(x, { name: v }))),
        textField('head:id', 'Id: its folder under assets/themes', t.id, (v) => edit('head:id', (x) => {
          // as on the start page: a built-in's id is refused, unless the theme already has it (that built-in's own file)
          if (official.builtinIds.includes(v.trim()) && x.id !== v.trim()) throw new StudioError(`"${v.trim()}" is a built-in theme’s id. Choose another.`);
          official.rename(x, { id: v.trim() });
        })),
        el('div', { class: 'field' }, el('label', null, el('span', { class: 'label', text: `Index: its place among the themes (the next free one is ${official.data.themes.length})` }),
          el('input', { type: 'number', min: '0', max: '9', value: String(t.index), 'data-ctl': 'head:index',
            onchange: (e) => edit('head:index', (x) => official.rename(x, { index: e.target.value.trim() === '' ? NaN : Number(e.target.value) })) })), refusalNote('head:index')),
        el('p', { class: 'lead', text: base ? `It extends ${base.resolved.name}: what it does not state itself is ${base.resolved.name}’s, now and after ${base.resolved.name} changes.`
          : 'It extends no theme: what it does not state is the format’s default.' })));
      const n = (id) => statedIn(id);
      const views = tree.filter((g) => g.views.length).reduce((sum, g) => sum + n(g.id), 0);
      add(box, el('section', { class: 'section' }, el('h3', { text: 'What it states itself' }),
        el('ul', { class: 'plain' },
          el('li', { text: `${views} value${views === 1 ? '' : 's'} of the screens` }),
          el('li', { text: `${n('schemes')} statements about colour schemes` }),
          el('li', { text: `${t.geometry.sets.length} geometry sets of its own${t.geometry.set === null ? '' : `, and it boots ${t.geometry.set}`}` }),
          el('li', { text: t.options === null ? 'no Appearance rows: its base’s are used' : `${t.options.length} Appearance rows` })),
        el('p', { class: 'lead', text: 'A mark beside each value says whose it is. The amber ones are this theme’s; the arrow beside one takes it back.' })));
      if (t.extends === 'classic-light') {
        add(box, el('section', { class: 'section' }, el('h3', { text: 'Over Classic' }), el('ul', { class: 'plain' }, classicLimits(flatPages(official, S.ctx.resolved)).map((text) => el('li', { text })))));
      }
      return box;
    }

    // NOTES.md: what a theme that extends Classic cannot do. flat: its pages painter is flat (a copy of
    // Classic Modern), so the flat look's art keeps its colours under any id.
    const classicLimits = (flat) => [
      'Classic already holds ten colour schemes, the most a theme can: a theme that extends it cannot add one, and cannot rename Classic Blue.',
      flat ? 'Its pages are in the flat look, whose art keeps its colours in the light half in any theme (pages.own.art_final may stay 1).'
        : 'Classic’s white art (chevron, pane note and icons) keeps its colours in the light half only for Classic itself; here it turns to ink (pages.own.art_final is 0).',
      'For a Classic look with a scheme of its own, start again from Classic as a stand-alone copy.',
    ];

    // ---- the Colour schemes panel

    // Removes a scheme of the theme's own, or takes back what it states about an accent. A scheme the Accent
    // row still names (default, preset or keep) is refused in words that say where to change that.
    function removeScheme(x, name, whole) {
      if (whole) {
        const row = official.options(x).find((o) => o.setting === 'accent');
        const named = row ? ['default', 'preset', 'keep'].filter((w) => row[w] === name) : [];
        if (named.length) {
          throw new StudioError(`Options > Accent names this scheme as its ${named.join(' and ')}. Choose another scheme there first, then remove this one.`);
        }
      }
      official.removeScheme(x, name);
    }

    function schemesPanel() {
      const t = S.hist.present;
      const r = S.ctx.resolved;
      const names = S.ctx.names;
      const on = (n) => bit(r.accents, names.indexOf(n));
      const offered = names.filter(on);
      const group = tree.find((g) => g.id === 'schemes');
      const box = el('div', { class: 'keys' });
      const titleOf = (n) => r.schemes[names.indexOf(n)].label || humanise(n);

      // which accents the theme offers
      const ownList = t.schemes.offered !== null;
      const chips = el('div', { class: 'chips' }, names.map((n) => el('label', { class: `check-chip${on(n) ? ' on' : ''}` },
        el('input', { type: 'checkbox', checked: on(n), 'data-ctl': `schemes:offer:${n}`, onchange: (e) => edit('schemes:offer', (x) => {
          official.offer(x, names.filter((m) => (m === n ? e.target.checked : on(m))), Boolean(r.derive));
        }) }), el('span', { text: titleOf(n) }))));
      const derive = el('label', { class: 'check-line' }, el('input', { type: 'checkbox', checked: Boolean(r.derive), 'data-ctl': 'schemes:derive',
        onchange: (e) => edit('schemes:offer', (x) => official.offer(x, x.schemes.offered === null ? offered : x.schemes.offered, e.target.checked)) }),
      el('span', { text: 'Give an offered accent with no band Classic Blue’s, turned to its own tone (derive: gloss)' }));
      add(box, el('section', { class: 'section', 'data-section': 'schemes.offered' }, el('h3', { text: 'Offered accents' }),
        el('div', { class: `slot${ownList ? ' mine' : ''}` }, el('span', { class: `src from-${ownList ? 'theme' : 'base'}`, text: ownList ? 'this theme’s list' : S.ctx.baseName ? `${S.ctx.baseName}’s list` : 'every accent' }),
          ownList ? button('schemes:offer:reset', '↺', () => edit('schemes:offer', (x) => official.offer(x, null)), { class: 'small icon', title: 'Reset: the base’s list', 'aria-label': 'Reset the offered accents' }) : null),
        chips, derive, refusalNote('schemes:offer'),
        el('p', { class: 'lead', text: 'The Accent row of Appearance offers these. A theme that stores its accent under the same key as another must offer the same ones (Options: the Accent row’s key).' })));

      // which scheme the rows below edit
      if (S.scheme !== null && !names.includes(S.scheme)) S.scheme = null;
      const entry = S.scheme === null ? null : t.schemes.named.find((s) => s.name === S.scheme);
      const picker = select('schemes:which', [{ value: '', title: 'Every scheme' }, ...names.map((n) => ({ value: n, title: `${titleOf(n)}${on(n) ? '' : ' (not offered)'}` }))],
        S.scheme === null ? '' : S.scheme, false, (v) => {
          S.scheme = v === '' ? null : v;
          S.refusal = null;
          if (S.scheme !== null && on(S.scheme)) S.choices.accent = S.scheme;
          keepFocus(() => { renderPanel(); renderViewer(); });
          queueDraw();
        }, 'Scheme to edit');
      const env = envNow();
      const shown = env ? env.accentName : offered[0];
      add(box, el('section', { class: 'section', 'data-section': 'schemes.which' }, el('h3', { text: 'Edit' }),
        el('div', { class: 'slot' }, picker, entry ? button('schemes:remove', entry.base !== undefined ? 'Remove this scheme' : 'Take back all it states here',
          () => { const gone = S.scheme; if (edit('schemes:remove', (x) => removeScheme(x, gone, entry.base !== undefined)) && entry.base !== undefined) { S.scheme = null; refresh(); } }) : null),
        refusalNote('schemes:remove'),
        entry && entry.base !== undefined ? el('p', { class: 'lead', text: 'Its name, label and base accent are fixed once added: to change them, remove it and add it again.' }) : null,
        el('p', { class: 'lead', text: S.scheme === null
          ? `A value stated here is every scheme’s at once; a scheme’s own statement still wins. The values shown are ${titleOf(shown)}’s, the accent in the preview.`
          : `Values of ${titleOf(S.scheme)} alone.` })));

      for (const section of group.sections) {
        add(box, el('section', { class: 'section', 'data-section': section.id }, el('h3', { text: section.title }), section.keys.map((item) => {
          const k = official.key(item.path);
          const attr = k.xml.attr;
          const halves = k.final ? ['dark', 'light'] : [null];
          return row(item, halves.map((half) => {
            const ctl = `scheme:${S.scheme === null ? '*' : S.scheme}:${attr}${half ? `:${half}` : ''}`;
            const source = schemeSource(official, S.ctx, S.scheme, attr, half, shown);
            const which = S.scheme;
            return slot(ctl, k, source,
              (v, soft) => edit(ctl, (x) => official.setScheme(x, which, attr, v, half === 'light' ? 'light' : undefined), soft),
              () => edit(ctl, (x) => official.unsetScheme(x, which, attr, half || undefined)), half ? `${item.label}, ${half}` : item.label);
          }));
        })));
      }

      // a scheme of the theme's own
      const form = { name: el('input', { type: 'text', placeholder: 'dusk', spellcheck: false, 'data-ctl': 'schemes:add:name', 'aria-label': 'New scheme’s name' }),
        label: el('input', { type: 'text', placeholder: 'Dusk', 'data-ctl': 'schemes:add:label', 'aria-label': 'New scheme’s label' }) };
      const baseAccent = select('schemes:add:base', official.accentNames.map((n) => ({ value: n, title: humanise(n) })), 'cobalt', false, () => {}, 'New scheme’s base accent');
      add(box, el('section', { class: 'section', 'data-section': 'schemes.add' }, el('h3', { text: 'A scheme of this theme’s own' }),
        el('div', { class: 'form' }, el('label', null, el('span', { text: 'Name' }), form.name), el('label', null, el('span', { text: 'Label in the Accent row' }), form.label),
          el('label', null, el('span', { text: 'Tones and starting values from' }), baseAccent),
          button('schemes:add', 'Add the scheme', () => {
            const name = form.name.value.trim();
            if (edit('schemes:add', (x) => official.addScheme(x, { name, base: baseAccent.value, label: form.label.value.trim() }))) {
              S.scheme = name;
              S.choices.accent = name;
              refresh();
            }
          })),
        refusalNote('schemes:add'),
        el('p', { class: 'lead', text: `A theme holds ${Q2Official.SCHEMES_MAX} schemes at most, the nine accents among them: so one of its own. This theme has ${r.schemes.length}.` })));
      return box;
    }

    // ---- the Geometry panel

    // Removes one of the theme's own sets. One that another of its sets extends is refused in words that say
    // so (official.js would say the set is not there).
    function removeSet(x, name) {
      const child = x.geometry.sets.find((g) => g.extends === name);
      if (child) throw new StudioError(`The set ${child.name} extends ${name}. Remove ${child.name} first.`);
      official.removeGeometry(x, name);
    }

    function geometryPanel() {
      const t = S.hist.present;
      const r = S.ctx.resolved;
      const all = Object.keys(Object.assign({}, official.data.geometry.sets, r.geoms));
      const box = el('div', { class: 'keys' });
      const item = tree.find((g) => g.id === 'geometry').sections[0].keys[0];
      const source = valueSource(official, S.ctx, 'geometry.set');
      const use = select('key:geometry.set', all.map((n) => ({ value: n, title: n })), r.geom_set, false, (v) => edit('key:geometry.set', (x) => official.useGeometry(x, v)), 'Set in use');
      const line = el('div', { class: `slot${source.stated ? ' mine' : ''}` }, use, el('span', { class: `src from-${source.from}`, text: fromWords(source, S.ctx) }),
        source.stated ? button('key:geometry.set:reset', '↺', () => edit('key:geometry.set', (x) => official.useGeometry(x, null)),
          { class: 'small icon', title: 'Reset: the base’s set', 'aria-label': 'Reset the set in use' }) : null);
      // an own option whose values name sets picks the set at start-up, over this choice
      const picker = official.options(t).find((o) => o.choices && o.choices.some((c) => c.set !== undefined));
      add(box, el('section', { class: 'section', 'data-section': 'geometry.' }, el('h3', { text: 'Set in use' }),
        row(item, [el('div', { class: 'slot-wrap' }, line, refusalNote('key:geometry.set'))]),
        picker ? el('p', { class: 'lead', text: `The option ${picker.label || picker.key} (Options) picks the set at start-up by its value, so the preview shows its set, not this one, while that row is there.` }) : null,
        el('p', { class: 'lead', text: 'A geometry set is the layout’s numbers: the bar’s height, the rows’ pitch, where text sits. The Q2 loads one at start-up. An own option whose values name sets (Classic’s Row Art) chooses between them.' })));

      const name = all.includes(S.set) ? S.set : r.geom_set;
      const mine = t.geometry.sets.find((g) => g.name === name);
      const info = official.geometryOf(t, name);
      const parent = mine ? mine.extends || 'ipod' : null;
      const head = el('div', { class: 'slot' }, select('geom:which', all.map((n) => ({ value: n, title: n === r.geom_set ? `${n} (in use)` : n })), name, false, (v) => {
        S.set = v;
        S.refusal = null;
        keepFocus(renderPanel);
      }, 'Set to look at'), el('span', { class: `src from-${mine ? 'theme' : 'base'}`, text: mine ? `this theme’s, over ${parent}` : name === 'ipod' ? 'the built-in set' : `${S.ctx.baseName || 'the base'}’s` }),
      mine ? button('geom:remove', 'Remove this set', () => { if (edit('geom:remove', (x) => removeSet(x, name))) { S.set = null; refresh(); } }) : null);
      const fields = el('section', { class: 'section', 'data-section': 'geometry.fields' }, el('h3', { text: 'A set’s numbers' }), head, refusalNote('geom:remove'),
        mine ? el('p', { class: 'lead', text: 'Its name and the set it extends are fixed once added: to change them, remove it and add it again.' }) : null,
        mine ? null : el('p', { class: 'lead', text: 'This set is not this theme’s, so its numbers cannot be changed here. Make a set of the theme’s own that extends it, below.' }));
      for (const g of geometryGroups(official)) {
        add(fields, el('h4', { text: g.title }));
        for (const f of g.fields) {
          const v = info.fields[f.name];
          const ctl = `geom:${name}:${f.name}`;
          const stated = Boolean(mine) && own(mine.fields, f.name);
          const lineOf = el('div', { class: `slot${stated ? ' mine' : ''}` },
            numberControl(ctl, v.value, v.lo, v.hi, !mine, (text) => edit(ctl, (x) => official.setGeometry(x, name, { [f.name]: /^-?\d+$/.test(text) ? Number(text) : text })), f.label),
            mine ? el('span', { class: `src from-${stated ? 'theme' : 'base'}`, text: stated ? 'this theme' : `${parent}’s` }) : null,
            stated ? button(`${ctl}:reset`, '↺', () => edit(ctl, (x) => official.setGeometry(x, name, { [f.name]: null })),
              { class: 'small icon', title: 'Reset: the set it extends', 'aria-label': `Reset ${f.label}` }) : null);
          add(fields, rowOf(`geometry.${f.name}`, f.label, f.name, '', [f.read ? null : el('span', { class: 'tag no', text: 'not shown in the preview' })],
            [el('div', { class: 'slot-wrap' }, lineOf, refusalNote(ctl))]));
        }
      }
      add(box, fields);

      const newName = el('input', { type: 'text', placeholder: 'roomy', spellcheck: false, 'data-ctl': 'geom:add:name', 'aria-label': 'New set’s name' });
      const over = select('geom:add:base', all.map((n) => ({ value: n, title: n })), name, false, () => {}, 'The set it extends');
      const useIt = el('input', { type: 'checkbox', checked: true, 'data-ctl': 'geom:add:use' });
      add(box, el('section', { class: 'section', 'data-section': 'geometry.add' }, el('h3', { text: 'A new set' }),
        el('div', { class: 'form' }, el('label', null, el('span', { text: 'Name' }), newName), el('label', null, el('span', { text: 'Starts from' }), over),
          el('label', { class: 'check-line' }, useIt, el('span', { text: 'and the theme boots it' })),
          button('geom:add', 'Add the set', () => {
            const made = newName.value.trim();
            if (edit('geom:add', (x) => {
              official.addGeometry(x, made, over.value === 'ipod' ? null : over.value);
              if (useIt.checked) official.useGeometry(x, made);
            })) {
              S.set = made;
              refresh();
            }
          })),
        refusalNote('geom:add'),
        el('p', { class: 'lead', text: `All themes together may use ${Q2Official.SETS_MAX} sets. A set’s name is one set across every theme.` })));
      return box;
    }

    // ---- the Options panel

    function optionsPanel() {
      const t = S.hist.present;
      const rows = official.options(t);
      const settings = official.data.settings;
      const idOf = (o) => o.setting || o.key;
      const box = el('div', { class: 'keys' });
      const mine = t.options !== null;
      add(box, el('section', { class: 'section', 'data-section': 'options.head' }, el('h3', { text: 'Appearance rows' }),
        el('div', { class: `slot${mine ? ' mine' : ''}` }, el('span', { class: `src from-${mine ? 'theme' : 'base'}`, text: mine ? 'this theme’s rows' : S.ctx.baseName ? `${S.ctx.baseName}’s rows` : 'none' }),
          mine ? button('options:inherit', 'Back to the base’s rows', () => edit('options:inherit', (x) => official.inheritOptions(x))) : null),
        refusalNote('options:inherit'),
        el('p', { class: 'lead', text: 'The rows Display > Appearance shows under this theme, in order. The first change here makes them all the theme’s own. Themes on the same geometry set switch without a restart, so they must list the same rows in the same order: a theme over Minimal or Modern keeps their ten, one on Classic’s sets its eleven.' }),
        el('p', { class: 'lead', text: 'Default: what a stored value outside the offered ones reads as. Preset: what choosing the theme stores. Keep: a stored value the preset leaves alone.' })));

      rows.forEach((o, i) => {
        const id = idOf(o);
        const names = o.choices ? o.choices.map((c) => c.label) : o.setting === 'accent' ? S.ctx.names : settings[o.setting].values;
        const title = o.choices ? o.label : settingTitle(o.setting);
        const ctl = `option:${id}`;
        const change1 = (changes) => edit(ctl, (x) => official.setOption(x, id, changes));
        const pickOne = (word, text) => el('label', null, el('span', { text }), select(`${ctl}:${word}`, [{ value: '', title: '(none)' }, ...names.map((n) => ({ value: n, title: o.choices ? n : o.setting === 'accent' ? humanise(n) : valueTitle(o.setting, n) }))],
          o[word] === undefined ? '' : o[word], false, (v) => change1({ [word]: v === '' ? null : v }), `${title}: ${text}`));
        const move = (to) => edit(ctl, (x) => {
          official.removeOption(x, id);
          official.addOption(x, o, to);
        });
        const card = el('div', { class: `card${S.flash === ctl ? ' flash' : ''}`, 'data-option': id },
          el('div', { class: 'card-head' }, el('strong', { text: title }), el('code', { class: 'path', text: o.choices ? `key ${o.key}` : `setting ${o.setting}` }),
            el('span', { class: 'spacer' }),
            button(`${ctl}:up`, '↑', () => move(i - 1), { class: 'small icon', disabled: i === 0, 'aria-label': `Move ${title} up`, title: 'Move up' }),
            button(`${ctl}:down`, '↓', () => move(i + 1), { class: 'small icon', disabled: i === rows.length - 1, 'aria-label': `Move ${title} down`, title: 'Move down' }),
            button(`${ctl}:remove`, 'Remove', () => edit(ctl, (x) => official.removeOption(x, id)))));
        const body = el('div', { class: 'form' });
        if (o.choices) {
          const withSets = o.choices.some((c) => c.set !== undefined);
          const allSets = Object.keys(Object.assign({}, official.data.geometry.sets, S.ctx.resolved.geoms));
          add(body, el('label', null, el('span', { text: 'Label' }), el('input', { type: 'text', value: o.label || '', 'data-ctl': `${ctl}:label`,
            onchange: (e) => change1({ label: e.target.value }) })));
          const list = el('div', { class: 'choices' });
          o.choices.forEach((c, n) => {
            const setChoices = (next) => change1({ choices: next });
            add(list, el('div', { class: 'stop' },
              el('input', { type: 'text', value: c.label, 'data-ctl': `${ctl}:v${n}`, 'aria-label': `${title}, value ${n + 1}`,
                onchange: (e) => {
                  // a renamed value keeps its place as default, preset or keep: they name it by its label
                  const next = { choices: o.choices.map((d, m) => (m === n ? Object.assign({}, d, { label: e.target.value }) : d)) };
                  for (const word of ['default', 'preset', 'keep']) if (o[word] === c.label) next[word] = e.target.value;
                  change1(next);
                } }),
              withSets ? select(`${ctl}:s${n}`, allSets.map((s) => ({ value: s, title: `boots ${s}` })), c.set, false,
                (v) => setChoices(o.choices.map((d, m) => (m === n ? Object.assign({}, d, { set: v }) : d))), `${title}, value ${n + 1}: its set`) : null,
              button(`${ctl}:x${n}`, '×', () => setChoices(o.choices.filter((d, m) => m !== n)), { class: 'small icon', 'aria-label': `Remove value ${c.label}`, title: 'Remove this value' })));
          });
          add(body, el('p', { class: 'lead wide', text: 'Its key is fixed once added: to change it, remove the row and add it again.' }));
          add(list, button(`${ctl}:addv`, 'Add a value', () => change1({ choices: [...o.choices, withSets ? { label: `Value ${o.choices.length + 1}`, set: S.ctx.resolved.geom_set } : { label: `Value ${o.choices.length + 1}` }] })));
          add(body, el('div', { class: 'wide' }, el('span', { class: 'label', text: 'Values' }), list));
        } else if (o.setting === 'accent') {
          add(body, el('label', null, el('span', { text: 'Key the chosen accent is stored under' }), el('input', { type: 'text', value: o.key || '', spellcheck: false, 'data-ctl': `${ctl}:key`,
            onchange: (e) => change1({ key: e.target.value.trim() === '' ? null : e.target.value.trim() }) })));
        } else {
          const listed = o.values || names;
          add(body, el('div', { class: 'wide' }, el('span', { class: 'label', text: o.values ? 'Values offered' : 'Values offered: all' }),
            el('div', { class: 'chips' }, names.map((n) => el('label', { class: `check-chip${listed.includes(n) ? ' on' : ''}` },
              el('input', { type: 'checkbox', checked: listed.includes(n), 'data-ctl': `${ctl}:val:${n}`, onchange: (e) => {
                const next = names.filter((m) => (m === n ? e.target.checked : listed.includes(m)));
                change1({ values: next.length === names.length ? null : next });
              } }), el('span', { text: valueTitle(o.setting, n) }))))));
        }
        add(body, el('div', { class: 'wide trio' }, pickOne('default', 'Default'), pickOne('preset', 'Preset'), pickOne('keep', 'Keep')));
        add(card, body, refusalNote(ctl));
        add(box, card);
      });

      const unlisted = Object.keys(settings).filter((s) => !rows.some((o) => o.setting === s));
      const which = select('options:add:setting', unlisted.map((s) => ({ value: s, title: settingTitle(s) })), unlisted[0] || '', !unlisted.length, () => {}, 'Firmware setting to add');
      const key = el('input', { type: 'text', placeholder: 'ROWPREVIEW', spellcheck: false, 'data-ctl': 'options:add:key', 'aria-label': 'Own option’s key' });
      const text = el('input', { type: 'text', placeholder: 'Row Preview', 'data-ctl': 'options:add:label', 'aria-label': 'Own option’s label' });
      const values = el('input', { type: 'text', value: 'Off, On', 'data-ctl': 'options:add:values', 'aria-label': 'Own option’s values' });
      const picksSet = el('input', { type: 'checkbox', 'data-ctl': 'options:add:sets' });
      // An own option of the theme's: each value boots the set in use until changed on its card when it picks
      // the set. A key already listed would make two cards share their controls: refused.
      const addOwn = (x) => {
        const name = key.value.trim();
        if (official.options(x).some((o) => o.key === name)) throw new StudioError(`There is already a row with the key ${name}. Give the new option another key.`);
        const labels = values.value.split(',').map((v) => v.trim()).filter(Boolean);
        official.addOption(x, { key: name, label: text.value.trim(), choices: labels.map((v) => (picksSet.checked ? { label: v, set: S.ctx.resolved.geom_set } : { label: v })),
          default: labels[0] || '' });
      };
      add(box, el('section', { class: 'section', 'data-section': 'options.add' }, el('h3', { text: 'Add a row' }),
        el('div', { class: 'form' }, el('label', null, el('span', { text: 'A firmware setting' }), which),
          button('options:add', 'Add it', () => edit('options:add', (x) => official.addOption(x, { setting: which.value })), { disabled: !unlisted.length })),
        refusalNote('options:add'),
        el('div', { class: 'form' }, el('label', null, el('span', { text: 'An option of the theme’s own: key' }), key), el('label', null, el('span', { text: 'Label' }), text),
          el('label', null, el('span', { text: 'Values, with commas' }), values),
          el('label', { class: 'check-line' }, picksSet, el('span', { text: 'it chooses the geometry set (each value boots one, set on its card)' })),
          button('options:addown', 'Add it', () => edit('options:addown', addOwn))),
        refusalNote('options:addown'),
        el('p', { class: 'lead', text: `An own option either chooses the geometry set (each value names one) or is one the firmware reads: ${official.data.plain_keys.join(', ')}.` })));
      return box;
    }

    // ---- the Export panel

    function exportPanel() {
      const t = S.hist.present;
      const text = exportText(official, t);
      const area = el('textarea', { class: 'xml', readOnly: true, spellcheck: false, rows: 18, value: text, 'data-ctl': 'export:text', 'aria-label': 'theme.xml' });
      const source = official.data.source || {};
      const box = el('div', { class: 'keys' });
      add(box, el('section', { class: 'section' }, el('h3', { text: 'theme.xml' }),
        el('div', { class: 'slot' }, button('export:save', 'Save theme.xml', save, { class: 'small primary' }), button('export:copy', 'Copy as text', () => copy(area)),
          el('span', { class: 'dim', text: `${new window.TextEncoder().encode(text).length} bytes of 32768` })),
        area,
        S.comments ? el('p', { class: 'refusal', text: 'The file this theme was opened from had comments. They are not kept: the saved theme.xml holds its values alone.' }) : null,
        el('p', { class: 'lead' }, 'It belongs at ', el('code', { text: repoPath(t) }), ' in a q2-pod checkout. Only what this theme states itself is written.')));
      add(box, el('section', { class: 'section' }, el('h3', { text: 'How this gets onto a Q2' }),
        el('p', { text: 'Official Q2 Pod builds its themes into the firmware. A theme.xml is not read from the card, so there is no way today to copy this file to a Q2 and pick it.' }),
        el('p', { text: 'The way a theme reaches a Q2 is a pull request to DiamondBond/q2-pod that adds it as one more built-in theme:' }),
        el('ol', { class: 'plain' },
          el('li', null, 'Add the file as ', el('code', { text: repoPath(t) }), `. Its index must be the next one (${official.data.themes.length} today), and its id the folder’s name.`),
          el('li', null, 'In ', el('code', { text: 'patch/theme_engine.c' }), ', give ', el('code', { text: 'theme_rows[]' }), ' the new index: the picker’s order. The build does not compile until it has one entry per theme.'),
          el('li', null, 'Some tests name the built-in themes and need a line each: ', el('code', { text: 'test/unit/test_theme.py' }), ', ', el('code', { text: 'test/fw/test_nav_playing.py' }), ', ',
            el('code', { text: 'test/fw/test_nav_display_library.py' }), ', ', el('code', { text: 'test/coverflow.py' }), ' and ', el('code', { text: 'test/patch.py' }), '; ',
            el('code', { text: 'docs/ipod.md' }), ' lists the themes in prose.'),
          el('li', { text: 'Every theme declares the Status Bar option with the same four values. A new theme works without one of its own; offering its bar to the others means a fifth value in every theme.xml.' })),
        el('p', { text: 'Whether such a theme is wanted upstream is the maintainers’ call: ask in an issue before the work.' }),
        el('p', { class: 'lead', text: `The Problems list is what the firmware’s build tool (tools/theme.py${source.commit ? ` at ${String(source.commit).slice(0, 8)}` : ''}) would refuse. It does not run the build: art, the C compile and the tests come after.` })));
      add(box, el('section', { class: 'section' }, el('h3', { text: 'Licence' }),
        el('p', { class: 'lead' }, 'This page is under the GNU GPL version 3 (', el('a', { href: '../../LICENSE', target: '_blank', rel: 'noopener', text: 'LICENSE' }),
          '): it holds work from DiamondBond/q2-pod, which is GPL-3.0-only. Its two fonts are under their own licences: ',
          el('a', { href: '../../assets/fonts/LiberationSans-OFL.txt', target: '_blank', rel: 'noopener', text: 'SIL OFL 1.1' }), ' and ', el('a', { href: '../../assets/fonts/GUST-FONT-LICENSE.txt', target: '_blank', rel: 'noopener', text: 'the GUST Font License' }), '.')));
      return box;
    }

    function saved(how) {
      markSaved(S.hist);
      renderTop();
      say(how);
    }

    // Saves theme.xml: the browser's save dialog where it has one, else a download.
    async function save() {
      if (!S.hist) return;
      commitTyping(); // a value still in its box is part of what is saved
      const text = exportText(official, S.hist.present);
      if (typeof window.showSaveFilePicker === 'function') {
        try {
          const handle = await window.showSaveFilePicker({ suggestedName: 'theme.xml', types: [{ description: 'Q2 Pod theme', accept: { 'application/xml': ['.xml'] } }] });
          const writer = await handle.createWritable();
          await writer.write(text);
          await writer.close();
          saved('Saved theme.xml.');
          return;
        } catch (e) {
          if (e && e.name === 'AbortError') {
            say('');
            return;
          }
          // the dialog is there but not usable here (a frame, a policy): fall through to a download
        }
      }
      const url = window.URL.createObjectURL(new window.Blob([text], { type: 'application/xml' }));
      const link = el('a', { href: url, download: 'theme.xml' });
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
      saved('Downloaded theme.xml.');
    }

    async function copy(area) {
      const text = exportText(official, S.hist.present);
      try {
        await window.navigator.clipboard.writeText(text);
        say('Copied theme.xml as text.');
      } catch (e) {
        area.focus();
        area.select();
        say(document.execCommand && document.execCommand('copy') ? 'Copied theme.xml as text.' : 'Could not copy: select the text and copy it by hand.');
      }
    }

    // ---- the editor's panel and the problems under it

    function renderPanel() {
      const panel = $('panel');
      const top = panel.scrollTop;
      clear(panel);
      const group = tree.find((g) => g.id === S.nav);
      const title = NAV().find((n) => n.id === S.nav);
      add(panel, el('h2', { text: title ? title.title : '' }));
      if (S.nav === 'theme') add(panel, themePanel());
      else if (S.nav === 'schemes') add(panel, schemesPanel());
      else if (S.nav === 'geometry') add(panel, geometryPanel());
      else if (S.nav === 'options') add(panel, optionsPanel());
      else if (S.nav === 'export') add(panel, exportPanel());
      else if (group) add(panel, keysPanel(group));
      panel.scrollTop = top;
    }

    function renderProblems() {
      const box = $('problems');
      clear(box);
      const n = S.problems.length;
      const list = el('ul', { class: 'problem-list' }, S.problems.map((p, i) => el('li', null, el('button', { type: 'button', class: 'problem', 'data-ctl': `problem:${i}`, title: p.tool,
        onclick: () => reveal(problemTarget(official, p)) }, p.message))));
      add(box, el('details', { open: n > 0, class: n ? 'bad' : 'good' },
        el('summary', { 'data-ctl': 'problems' }, n ? `Problems (${n}): the firmware’s build would refuse this theme` : 'No problems: the build tool would accept this theme'),
        n ? list : el('p', { class: 'lead', text: `Checked beside the ${countWords(official.data.themes.length)} built-in themes, as the build has them.` })));
    }

    // Goes to the control a problem is about and marks it for a moment.
    function reveal(target) {
      S.nav = NAV().some((n) => n.id === target.panel) ? target.panel : 'theme';
      S.refusal = null;
      if (target.section && tree.find((g) => g.id === S.nav && g.folded)) S.open.add(target.section);
      if (target.path && target.path.startsWith('scheme.') && S.scheme !== null && !S.ctx.names.includes(S.scheme)) S.scheme = null;
      S.flash = target.path || (target.option ? `option:${target.option}` : null);
      renderNav();
      renderPanel();
      const panel = $('panel');
      const find = (attr, value) => [...panel.querySelectorAll(`[${attr}]`)].find((n) => n.getAttribute(attr) === value);
      const node = (target.path && find('data-key', target.path)) || (target.option && find('data-option', target.option)) || (target.section && find('data-section', target.section)) || panel;
      if (node.scrollIntoView) node.scrollIntoView({ block: 'center' });
      const first = node.querySelector('input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])');
      if (first) first.focus({ preventScroll: true });
      S.flash = null;
    }

    // ---- the start page

    function showStart() {
      $('start').hidden = false;
      $('work').hidden = true;
      renderTop();
      renderStart();
    }

    const START_WORDS = {
      extend: 'A new theme that extends it. The file states only what you change; the rest is the base’s, and follows the base when it changes upstream.',
      copy: 'A stand-alone copy. The base’s own statements under your id, so a later change to the base does not move your theme.',
    };

    function renderStart() {
      const st = S.start;
      const box = $('start-body');
      const lead = $('start-lead'); // how many built-ins there are comes from official.json
      if (lead) lead.textContent = startLead(official);
      keepFocus(() => {
        clear(box);
        const cards = el('div', { class: 'bases', role: 'radiogroup', 'aria-label': 'Start from' }, official.data.themes.map((b) => {
          const canvas = el('canvas', { width: 375, height: 320, class: 'thumb' });
          if (Q2Draw) {
            try {
              Q2Draw.render(canvas.getContext('2d'), 'home', Q2Draw.env(official, b.resolved, {}), {});
            } catch (e) { /* a thumbnail only */ }
          }
          return el('label', { class: `base${st.base === b.id ? ' on' : ''}` },
            el('input', { type: 'radio', name: 'base', value: b.id, checked: st.base === b.id, 'data-ctl': `start:base:${b.id}`, onchange: () => { st.base = b.id; st.error = ''; renderStart(); } }),
            canvas, el('strong', { text: b.resolved.name }));
        }));
        const modes = el('div', { class: 'modes', role: 'radiogroup', 'aria-label': 'How' }, ['extend', 'copy'].map((m) => el('label', { class: `mode${st.mode === m ? ' on' : ''}` },
          el('input', { type: 'radio', name: 'mode', value: m, checked: st.mode === m, 'data-ctl': `start:mode:${m}`, onchange: () => { st.mode = m; st.error = ''; renderStart(); } }),
          el('span', { text: START_WORDS[m] }))));
        const baseName = official.data.themes.find((b) => b.id === st.base).resolved.name;
        const notes = [];
        if (st.base === 'classic-light' && st.mode === 'extend') notes.push(...classicLimits(false));
        if (st.mode === 'copy') {
          const parent = official.data.themes.find((b) => b.id === st.base).resolved;
          const over = official.read(official.data.themes.find((b) => b.id === st.base).text).extends;
          const overName = over ? official.data.themes.find((b) => b.id === over).resolved.name : '';
          notes.push(over ? `${baseName} itself extends ${overName}, and so will the copy: it holds ${baseName}’s own statements, not ${overName}’s.`
            : `${baseName} extends nothing, and neither will the copy.`);
          if (parent.id === 'classic-light') notes.push('The copy can have a colour scheme of its own in Classic Blue’s place. Its white art turns to ink in the light half, as for any theme but Classic.');
          notes.push('The copy stores its accent under the same key as its base, so it must offer the same accents until you give its Accent row a key of its own (Options).');
        }
        const name = el('input', { type: 'text', value: st.name, placeholder: 'Dusk', 'data-ctl': 'start:name', autocomplete: 'off', oninput: () => {
          st.name = name.value;
          if (!st.idTouched) { st.id = suggestId(st.name); id.value = st.id; }
        } });
        // an Id box emptied by hand takes the name's suggestion again when it is left
        const suggestAgain = () => { if (id.value.trim() === '') { st.idTouched = false; st.id = suggestId(st.name); id.value = st.id; } };
        const id = el('input', { type: 'text', value: st.id, placeholder: 'dusk', spellcheck: false, autocomplete: 'off', 'data-ctl': 'start:id',
          oninput: () => { st.id = id.value; st.idTouched = id.value !== ''; }, onblur: suggestAgain });
        const create = () => {
          suggestAgain();
          try {
            begin(startTheme(official, { base: st.base, mode: st.mode, id: st.id.trim(), name: st.name }), `${st.mode === 'copy' ? 'A copy of' : 'A theme over'} ${baseName}.`);
          } catch (e) {
            if (!(e instanceof Q2Official.ThemeError) && !(e instanceof StudioError)) throw e;
            st.error = refusalWords(official, e);
            renderStart();
          }
        };
        const form = el('form', { class: 'start-form', onsubmit: (e) => { e.preventDefault(); create(); } },
          el('label', null, el('span', { text: 'Name, as the Theme picker will show it' }), name),
          el('label', null, el('span', { text: 'Id: lowercase letters, digits, - and _, starting with a letter' }), id),
          el('button', { type: 'submit', class: 'primary', 'data-ctl': 'start:create', text: 'Start the theme' }));
        add(box, el('h3', { text: '1. Start from' }), cards, el('h3', { text: '2. As' }), modes,
          notes.length ? el('ul', { class: 'plain notes' }, notes.map((text) => el('li', { text }))) : null,
          el('h3', { text: '3. Call it' }), form, st.error ? el('p', { class: 'refusal', role: 'alert', text: st.error }) : null,
          el('h3', { text: 'Or open one' }),
          el('p', null, button('start:open', 'Open a theme.xml…', () => $('file').click(), { class: 'small' }), el('span', { class: 'dim', text: ' from your disk. Nothing is uploaded: the page works in this browser alone.' })),
          S.hist ? el('p', null, button('start:back', 'Back to the theme being edited', () => { $('start').hidden = true; $('work').hidden = false; })) : null);
      });
    }

    // Starts editing a theme. comments: it was opened from a file that had comments.
    function begin(theme, words, comments = false) {
      S.hist = history(theme);
      S.nav = 'theme';
      S.scheme = null;
      S.set = null;
      S.refusal = null;
      S.choices = {};
      S.stateOf = {};
      S.open = new Set();
      S.start.error = '';
      S.comments = comments; // the opened file had comments, which saving drops
      $('start').hidden = true;
      $('work').hidden = false;
      measure();
      renderTabs();
      refresh();
      $('panel').scrollTop = 0;
      say(words);
    }

    const sure = () => !S.hist || !dirty(S.hist) || window.confirm('This theme has changes that were not saved. Leave it?');

    // Refusals about the whole file, whose line number points at nothing.
    const WHOLE_FILE = /^(larger than 32 KB|not UTF-8)$/;

    async function openFile(file) {
      if (!file) return;
      try {
        // too large is refused before the file is read into memory at all
        if (file.size > Q2Official.MAX_BYTES) throw new StudioError('The theme file is larger than 32 KB.');
        const bytes = new Uint8Array(await file.arrayBuffer());
        if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
          throw new StudioError('The file starts with a byte-order mark (BOM), which the firmware’s build tool refuses too. Save it as UTF-8 without one.');
        }
        const theme = official.read(bytes);
        if (!sure()) return;
        // official.js keeps the values, not the comments: say so where saving would drop them
        const comments = new window.TextDecoder().decode(bytes).includes('<!--');
        begin(theme, `Opened ${file.name}.${comments ? ' Its comments are not kept: a saved copy holds the values alone.' : ''}`, comments);
      } catch (e) {
        const line = e.line && !WHOLE_FILE.test(e.detail || '') ? ` (line ${e.line})` : '';
        const words = `${file.name} was not opened. ${refusalWords(official, e)}${line}`;
        S.start.error = words;
        if (!$('start').hidden) renderStart();
        say(words);
      }
    }

    // ---- wiring

    function step(back) {
      if (!S.hist || !(back ? undo(S.hist) : redo(S.hist))) return;
      S.refusal = null;
      refresh();
      say(back ? 'Undone.' : 'Redone.');
    }

    function wire() {
      $('undo').addEventListener('click', () => step(true));
      $('redo').addEventListener('click', () => step(false));
      $('save').addEventListener('click', save);
      $('new').addEventListener('click', () => { if (sure()) showStart(); });
      $('open').addEventListener('click', () => $('file').click());
      $('file').addEventListener('change', (e) => {
        const file = e.target.files[0];
        e.target.value = '';
        openFile(file);
      });
      window.addEventListener('beforeunload', (e) => {
        if (!S.hist || !dirty(S.hist)) return;
        e.preventDefault();
        e.returnValue = '';
      });
      window.addEventListener('resize', () => {
        measure();
        queueDraw();
      });
      document.addEventListener('keydown', (e) => {
        if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
        const key = e.key.toLowerCase();
        if (key === 's') {
          e.preventDefault();
          save();
          return;
        }
        // in a box with typing not yet committed the browser's own undo of the typing comes first; once the
        // box is committed (Enter, or a rebuilt control) the theme's undo takes the key
        if (typingIn(e.target) || !S.hist) return;
        if (key === 'z') {
          e.preventDefault();
          step(!e.shiftKey);
        } else if (key === 'y') {
          e.preventDefault();
          step(false);
        }
      });
    }

    function fail(words) {
      $('loading').textContent = words;
      $('loading').hidden = false;
    }

    function boot() {
      if (!Q2Official) {
        fail('official.js did not load: the page cannot work without it.');
        return;
      }
      window.fetch('official.json').then((r) => {
        if (!r.ok) throw new Error(`official.json: ${r.status}`);
        return r.json();
      }).then(async (data) => {
        official = Q2Official.open(data);
        tree = groups(official);
        if (Q2Draw) await Q2Draw.loadFonts();
        wire();
        measure();
        $('loading').hidden = true;
        showStart();
      }).catch((e) => {
        fail(`The page could not start: ${e.message}.${window.location.protocol === 'file:' ? ' It needs to be served over http (a static host, or a local server), not opened as a file.' : ''}`);
      });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();
  }

  return {
    GROUPS, SECTIONS, LABELS, PREVIEW, GEOMETRY, UNREAD, CHOICE_TITLES,
    countWords, startLead, flatPages,
    groups, label, preview, placeOf, geometryGroups, settingTitle, valueTitle, viewerControls, accents,
    context, valueSource, schemeSource, fromWords,
    history, change, undo, redo, canUndo, canRedo, dirty, markSaved, LIMIT, MERGE_MS,
    StudioError, suggestId, startTheme, exportText, repoPath, refusalWords, problemTarget,
    hex, stopsCss, rowsCss, stopsAdd, stopsRemove, stopsSet,
    page,
  };
});
