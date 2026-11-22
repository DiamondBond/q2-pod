// SPDX-License-Identifier: GPL-3.0-only
// Part of Q2 Theme Studio, which holds work from DiamondBond/q2-pod (GPL-3.0-only): see LICENSE at the repository root.
// The official Q2 Pod theme format (DiamondBond/q2-pod, assets/themes/<id>/theme.xml) with no page in it:
// reading and writing theme.xml, a theme to edit, the values the firmware's build works out from it, and
// what that build would refuse. Loaded by a page as window.Q2Official and by official.test.mjs as a module.
//
// The format's tables (keys, ranges, choices, geometry, accents, settings, the built-in themes) are not in
// this file: open(data) takes them from official.json, which tools/official_data.py writes from a q2-pod
// checkout. What this file does hold is the tool's logic, mirrored function by function from
// tools/theme.py; MIRRORED names the source each mirror was written against, and official.test.mjs fails
// when official.json says one of them has changed upstream.
//
// A theme to edit is plain data, in the order write() puts it in a file:
//   { id, name, index, extends,                    extends: a built-in's id, or null
//     geometry: { sets: [{ name, extends, fields: { bar: 26, ... } }], set },
//     schemes: { all: { values, light }, named: [{ name, base, label, values, light }], offered, derive },
//     values: { 'list.row.title_px': 27, ... }, light: { 'list.scrollbar.thumb': 0x8f98a8 },
//     options: null | [{ setting, key, values, default, preset, keep } | { key, label, choices, default, preset, keep }] }
// Values are the tool's own: an int, 0 or 1 for a switch, a choice's index, a colour 0xRRGGBB, stops
// [[position, colour], ...], alphas [n, ...], rows [0xAARRGGBB, ...]. A final key has two slots: values
// (written plain, or dark. beside a light one) and light. A scheme's values are keyed by attribute
// ('sel.stops', 'paper'). options null keeps the base's rows. Change a theme through the functions below:
// each refuses what the tool's resolve() would, and leaves the theme as it was.
(function (root, make) {
  if (typeof module === 'object' && module.exports) module.exports = make();
  else root.Q2Official = make();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // tools/theme.py at DiamondBond/q2-pod 6ceb519a: the functions mirrored here, by official.json's hashes
  // (of emit, its scheme arrays and its 8-set limit; of c_name and stops_c, what schemeArrays relies on).
  const MIRRORED = {
    emit: '8f07e4e8bd6095f1', c_name: '50395479a9aa74a6', stops_c: 'afb8a878b5ff9535', tokenize: '696829eed7dc3aea',
    parse: 'f98a67ece7a64eba', load: '3cff81aad13466a8', check_tags: '3240c17d7fc62eaf', split_half: 'e47d680372ad0fcd',
    ranged: 'f5b49894aa6e044c', value: 'fc6688d9acd6ed1b', own_key: '3b0b63b4dbfa1553', label_ok: '25f36155729b7e18',
    presets: '5f99392f202bba19', offered: '6499cadcbcb89ca9', own_option: '847e2989974c5ec6', scheme_names: 'db85c212d0f7af35',
    zero_scheme: '38a03c3e29889bcf', sets: 'f4028dae5d6654b4', check_set: '1310cf7683827dcd', declare: '19e1958641c717fe',
    geometry: '7972b1e0d4ab1ad6', geometry_sets: 'a5900dab88130960', turn: 'cb03f2b09b43fcc0', derive_gloss: '14e51f732de23578',
    resolve: '74fc7dc3916ae52b', validate: '35952d3276c1003d', accent_default: '23519c42bff6ee4f', theme_keys: '0cee5895ac004633',
    builtins: 'b1d0dd5fdf576111', flip: '77de589a01b57422', unflip: 'b21f067932378925', half: '13c6531e4e50a589',
    scheme_half: 'cfca87494258005c', shared: '575fe02b47d0a8e5',
  };

  const MAX_BYTES = 32768; // load()
  const NAME_BYTES = 48; // a theme's name and an own scheme's label (resolve)
  const LABEL_BYTES = 24; // an own option's label and its values' (label_ok)
  const SCHEMES_MAX = 10; // validate: config_value reads one digit
  const SETS_MAX = 8; // emit: ui_redirect_t.sets
  const WS = '[ \t\r\n]';
  // TOKEN, as tools/theme.py builds it (official.test.mjs compares it with official.json's)
  const TOKEN = `<!--(?:(?!--).)*-->|<(/?)([A-Za-z][A-Za-z0-9]*)((?:${WS}+[a-z0-9_.]+="[^"<\\x00-\\x1f]*")*)${WS}*(/?)>|${WS}+`;
  const TOKEN_RE = new RegExp(TOKEN, 'sy');
  const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"' };
  const CONTROL = /[\x00-\x1f\x7f-\x9f]/;
  // what Python's str.split() and str.strip() call space, of the characters an attribute's value can hold
  const PY_SPACE = ' \\x1c-\\x1f\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
  const pySplit = (text) => text.split(new RegExp(`[${PY_SPACE}]+`)).filter(Boolean);
  const pyStrip = (text) => text.replace(new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, 'g'), '');
  const utf8 = (text) => new TextEncoder().encode(text).length;
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const truthy = (v) => (Array.isArray(v) ? v.length > 0 : Boolean(v)); // Python's, of a value or a tuple
  const hex6 = (c) => '#' + c.toString(16).padStart(6, '0');
  const copy = (data) => JSON.parse(JSON.stringify(data));

  class ThemeError extends Error {
    constructor(file, line, detail) {
      super(file ? `${file}:${line}: ${detail}` : detail);
      this.name = 'ThemeError';
      this.file = file;
      this.line = line;
      this.detail = detail;
    }
  }

  function fail(file, line, message) {
    throw new ThemeError(file, line, message);
  }

  // [kind, tag, attrs, line] for each tag, kind 'open', 'empty' or 'close'; attrs a Map in file order.
  function tokenize(text, file) {
    const tokens = [];
    let pos = 0;
    let line = 1;
    let counted = 0;
    while (pos < text.length) {
      for (let at = text.indexOf('\n', counted); at >= 0 && at < pos; at = text.indexOf('\n', at + 1)) line += 1;
      counted = pos;
      TOKEN_RE.lastIndex = pos;
      const m = TOKEN_RE.exec(text);
      if (!m) {
        fail(file, line, text.startsWith('<!--', pos) ? 'unclosed comment' : text[pos] === '<' ? 'malformed tag' : 'text between tags');
      }
      pos = TOKEN_RE.lastIndex;
      if (m[2] === undefined) continue; // a comment or whitespace
      if (m[1] && (m[3] || m[4])) fail(file, line, 'malformed tag');
      const attrs = new Map();
      for (const [, name, value] of m[3].matchAll(/([a-z0-9_.]+)="([^"]*)"/g)) {
        if (attrs.has(name)) fail(file, line, `duplicate attribute ${name}`);
        if (/&(?!(?:amp|lt|gt|quot);)/.test(value)) fail(file, line, 'unknown entity');
        attrs.set(name, value.replace(/&(amp|lt|gt|quot);/g, (_, e) => ENTITIES[e]));
      }
      tokens.push([m[1] ? 'close' : m[4] ? 'empty' : 'open', m[2], attrs, line]);
    }
    return tokens;
  }

  // The root <theme format="1"> of a theme file's text: { tag, attrs, children, line, file }.
  function parse(text, file = 'theme.xml') {
    let root = null;
    const stack = [];
    for (const [kind, tag, attrs, line] of tokenize(text, file)) {
      if (root && !stack.length) fail(file, line, 'more than one root element');
      if (kind === 'close') {
        if (!stack.length || stack[stack.length - 1].tag !== tag) fail(file, line, `mismatched </${tag}>`);
        stack.pop();
        continue;
      }
      const node = { tag, attrs, children: [], line, file };
      if (root) stack[stack.length - 1].children.push(node);
      else if (tag !== 'theme' || attrs.get('format') !== '1') fail(file, line, 'root must be <theme format="1">');
      else root = node;
      if (kind === 'open') stack.push(node);
    }
    if (stack.length) fail(file, stack[stack.length - 1].line, `unclosed <${stack[stack.length - 1].tag}>`);
    if (!root) fail(file, 1, 'root must be <theme format="1">');
    return root;
  }

  // parse() a theme.xml's bytes (a Uint8Array) or its text, within the tool's size and encoding.
  function load(source, file = 'theme.xml') {
    if (typeof source === 'string') {
      if (utf8(source) > MAX_BYTES) fail(file, 1, 'larger than 32 KB');
      if (/[\ud800-\udbff](?![\udc00-\udfff])|(?:^|[^\ud800-\udbff])[\udc00-\udfff]/.test(source)) fail(file, 1, 'not UTF-8');
      return parse(source, file);
    }
    if (source.length > MAX_BYTES) fail(file, 1, 'larger than 32 KB');
    let text;
    try {
      text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(source);
    } catch {
      fail(file, 1, 'not UTF-8');
    }
    return parse(text, file);
  }

  // Python's round() of a float: halves to the even neighbour.
  function pyRound(x) {
    const low = Math.floor(x);
    return x - low === 0.5 ? low + (low % 2) : Math.round(x);
  }

  // Python's f'{x:.{digits}f}' for digits 0 and 1: a half goes to the even digit, where toFixed takes the larger.
  function pyFixed(x, digits) {
    if (!Number.isFinite(x)) return Number.isNaN(x) ? 'nan' : x > 0 ? 'inf' : '-inf';
    const steps = Math.abs(x) * (digits ? 4 : 2); // a half is an odd count of quarters (one decimal) or halves (none)
    if (Number.isInteger(steps) && steps % 2 === 1) {
      const low = Math.floor(Math.abs(x) * 10 ** digits);
      const even = (low % 2 ? low + 1 : low) / 10 ** digits;
      return (x < 0 ? '-' : '') + even.toFixed(digits);
    }
    return x.toFixed(digits);
  }

  const pyMod1 = (x) => { const m = x % 1; return m && m < 0 ? m + 1 : m; };

  // colorsys.rgb_to_hsv and hsv_to_rgb, step for step.
  function rgbToHsv(r, g, b) {
    const maxc = Math.max(r, g, b);
    const minc = Math.min(r, g, b);
    const rangec = maxc - minc;
    if (minc === maxc) return [0, 0, maxc];
    const s = rangec / maxc;
    const rc = (maxc - r) / rangec;
    const gc = (maxc - g) / rangec;
    const bc = (maxc - b) / rangec;
    const h = r === maxc ? bc - gc : g === maxc ? 2 + rc - bc : 4 + gc - rc;
    return [pyMod1(h / 6), s, maxc];
  }

  function hsvToRgb(h, s, v) {
    if (s === 0) return [v, v, v];
    const i = Math.trunc(h * 6);
    const f = h * 6 - i;
    const p = v * (1 - s);
    const q = v * (1 - s * f);
    const t = v * (1 - s * (1 - f));
    return [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][i % 6];
  }

  // Everything that needs the format's tables: data is official.json.
  function open(data) {
    const KEYS = data.schema;
    const SCHEMA = new Map(KEYS.map((k) => [k.path, k]));
    const FIELDS = new Map(KEYS.map((k) => [k.field, k]));
    const FINAL = KEYS.filter((k) => k.final);
    const isScheme = (k) => k.path.startsWith('scheme.');
    const VIEWS = new Set(data.xml.views);
    const ELEMENTS = new Set(data.xml.elements);
    const CHILDREN = data.xml.children;
    const OPTION_ATTRS = new Set(data.xml.option_attrs);
    const ACCENT_NAMES = data.accents.map((a) => a.name);
    const ACCENT_TONES = data.accents.map((a) => a.tones);
    const ALL_ACCENTS = (1n << BigInt(ACCENT_NAMES.length)) - 1n;
    const SETTINGS = data.settings;
    const MACROS = Object.values(SETTINGS).map((s) => s.macro);
    const ACCENT_KEYS = data.accent_keys;
    const PAYLOAD_KEYS = new Set(data.payload_keys);
    const PLAIN_KEYS = new Set(data.plain_keys);
    const GEOM_FIELDS = data.geometry.fields;
    const GEOM_RANGES = new Map(GEOM_FIELDS.map((f) => [f.name, f]));
    const GEOM_NAME = new RegExp(`^(?:${data.geometry.name})$`);
    const GEOMETRIES = data.geometry.sets;
    const SET0 = Object.values(GEOMETRIES)[0];
    const GLOSS = data.gloss;
    const O = data.constants;
    const EASINGS = KEYS.find((k) => k.type === 'easing').choices;
    const MOTIONS = [...data.motion.window, ...data.motion.widget];
    const ROLE_MACROS = data.role_macros;
    const choices = (path) => SCHEMA.get(path).choices;

    // ---- one value ----

    function ranged(node, k, v) {
      if (!(k.lo <= v && v <= k.hi)) fail(node.file, node.line, `${k.path}: ${v} outside ${k.lo}..${k.hi}`);
      return v;
    }

    // An integer's text as a number; past what a number holds exactly, a BigInt (it is out of every range).
    function int(text) {
      const n = Number(text);
      return Number.isSafeInteger(n) ? n + 0 : BigInt(text);
    }

    // SCHEMA[path]'s value for an attribute's text; macros: the fields ROLE_MACROS supplies for this theme.
    function value(node, path, text, macros) {
      const err = (message) => fail(node.file, node.line, message);
      const k = SCHEMA.get(path);
      if (!k) err(`unknown key ${path}`);
      if (k.final && k.type === 'color' && text.toLowerCase() === '#000000') err(`${path}: #000000 reads as unset; use #010101`);
      if (macros.has(k.field)) err(`${path} comes from patch/offsets.inc`);
      let v;
      if (k.type === 'bool') {
        if (text !== '0' && text !== '1') err(`${path}: expected 0 or 1`);
        v = Number(text);
      } else if (k.type === 'enum') {
        v = k.choices.indexOf(text);
        if (v < 0) err(`${path}: unknown value ${text}`);
      } else if (k.type === 'easing' || k.type === 'anim') {
        v = k.choices.indexOf(text);
        if (v < 0) err(`${path}: ${text} is not one of ${k.choices.join(', ')}`);
      } else if (k.type === 'color') {
        if (!/^#[0-9a-fA-F]{6}$/.test(text)) err(`${path}: expected #rrggbb`);
        v = parseInt(text.slice(1), 16);
      } else if (k.type === 'alphas') {
        if (!/^[0-9]{1,3}( [0-9]{1,3}){0,31}$/.test(text) || pySplit(text).some((a) => Number(a) > 255)) {
          err(`${path}: expected up to 32 alphas 0..255`);
        }
        return pySplit(text).map(Number);
      } else if (k.type === 'rows') {
        const rows = pySplit(text);
        if (!(rows.length >= 1 && rows.length <= 31) || !rows.every((r) => /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(r))) {
          err(`${path}: expected up to 31 of #rrggbb or #rrggbbaa`);
        }
        return rows.map((r) => (r.length === 7 ? 0xff : parseInt(r.slice(7), 16)) * 0x1000000 + parseInt(r.slice(1, 7), 16));
      } else if (k.type === 'stops') {
        const stops = text.split(',').map((s) => /^#([0-9a-fA-F]{6}) ([0-9]{1,3})$/.exec(pyStrip(s)));
        if (!stops.every(Boolean)) err(`${path}: expected "#rrggbb N, ..."`);
        v = stops.map((m) => [Number(m[2]), parseInt(m[1], 16)]);
        if (!(v.length >= 2 && v.length <= 13)) err(`${path}: 2 to 13 stops`);
        if (v[0][0] !== 0 || v[v.length - 1][0] !== 100 || v.some((a, i) => i + 1 < v.length && a[0] >= v[i + 1][0])) {
          err(`${path}: positions must rise from 0 to 100`);
        }
        return v;
      } else {
        if (!/^-?[0-9]+$/.test(text)) err(`${path}: expected an integer`);
        v = int(text);
      }
      return ranged(node, k, v);
    }

    // The text write() gives a key's value. It takes the tool's own value, and a choice by name, a switch as
    // true or false, a colour as '#rrggbb', or the attribute's text itself.
    function text(path, v) {
      const k = SCHEMA.get(path);
      if (!k) throw new ThemeError(null, 0, `unknown key ${path}`);
      const colour = (c) => (typeof c === 'number' && Number.isInteger(c) && c >= 0 ? hex6(c) : String(c));
      if (typeof v === 'string') return v;
      if (k.type === 'bool') return typeof v === 'boolean' ? String(Number(v)) : String(v);
      if (k.choices) return k.choices[v] ?? String(v);
      if (k.type === 'color') return colour(v);
      if (!Array.isArray(v)) return String(v);
      if (k.type === 'stops') return v.map((s) => (Array.isArray(s) ? `${colour(s[1])} ${s[0]}` : String(s))).join(', ');
      if (k.type === 'rows') {
        return v.map((r) => {
          if (typeof r !== 'number' || !Number.isInteger(r) || r < 0) return String(r);
          const rgb = hex6(r % 0x1000000);
          const alpha = Math.floor(r / 0x1000000);
          return alpha === 0xff ? rgb : rgb + alpha.toString(16).padStart(2, '0');
        }).join(' ');
      }
      return v.join(' ');
    }

    // ---- geometry sets ----

    const sets = (t) => ({ ...GEOMETRIES, ...t.geoms });

    // One end of a field's range for the set g, in whole numbers of any size.
    function bound(b, g) {
      if (typeof b === 'number') return BigInt(b);
      if (b.field) return BigInt(g[b.field]);
      const a = b.args.map((x) => bound(x, g));
      if (b.op === '+') return a[0] + a[1];
      if (b.op === '-') return a[0] - a[1];
      if (b.op === '*') return a[0] * a[1];
      if (b.op === '//') return a[0] / a[1] - (a[0] % a[1] !== 0n && (a[0] < 0n) !== (a[1] < 0n) ? 1n : 0n);
      return a.reduce((m, x) => ((b.op === 'min' ? x < m : x > m) ? x : m));
    }

    // [lo, hi] of one field of the set g, given g's other fields.
    function geometryBounds(g, field) {
      const f = GEOM_RANGES.get(field);
      return [Number(bound(f.lo, g)), Number(bound(f.hi, g))];
    }

    // Every field of g outside its range, in Geometry's order, as the tool's message; the tool stops at the first.
    function setFaults(g) {
      const out = [];
      for (const f of GEOM_FIELDS) {
        const v = BigInt(g[f.name]);
        let lo;
        let hi;
        try {
          [lo, hi] = [bound(f.lo, g), bound(f.hi, g)];
        } catch {
          break; // a range that divides by a field already at fault
        }
        if (!(lo <= v && v <= hi)) out.push(`geometry.${f.name}: ${v} outside ${lo}..${hi}`);
      }
      return out;
    }

    // One <geometry name> over its extends= set, checked; known: the sets it can name.
    function declare(node, known) {
      const err = (message) => fail(node.file, node.line, message);
      const name = node.attrs.get('name');
      if (!GEOM_NAME.test(name)) err('geometry.name: expected [a-z][a-z0-9-]*, 1..24 bytes, not n');
      if (own(known, name)) err(`geometry set ${name} declared twice`);
      const ints = {};
      for (const [k, v] of node.attrs) {
        if (k === 'name' || k === 'extends') continue;
        if (!GEOM_RANGES.has(k)) err(`unknown key geometry.${k}`);
        if (!/^-?[0-9]+$/.test(v)) err(`geometry.${k}: expected an integer`);
        ints[k] = int(v);
      }
      const base = node.attrs.has('extends') ? node.attrs.get('extends') : SET0.name;
      if (!own(known, base)) err(`unknown geometry set "${base}"`);
      const g = { ...known[base], name, ...ints };
      const faults = setFaults(g);
      if (faults.length) err(faults[0]);
      return g;
    }

    // The set t boots.
    const geometry = (t) => sets(t)[t.geom_set];

    // ---- options ----

    function ownKey(node, key) {
      if (!/^[A-Z][A-Z0-9_]*$/.test(key)) fail(node.file, node.line, 'option.key: expected [A-Z][A-Z0-9_]*');
      if (PAYLOAD_KEYS.has(key)) fail(node.file, node.line, `${key}: the payload's key`);
      return key;
    }

    const labelOk = (label) => utf8(label) > 0 && utf8(label) <= LABEL_BYTES && !CONTROL.test(label);

    function presets(c, o, names, what) {
      for (const [attr, field] of [['default', 'def'], ['preset', 'preset'], ['keep', 'keep']]) {
        if (c.attrs.has(attr)) {
          if (!names.includes(c.attrs.get(attr))) fail(c.file, c.line, `${what}: unknown value ${c.attrs.get(attr)}`);
          o[field] = names.indexOf(c.attrs.get(attr));
        }
      }
      return o;
    }

    function offered(c, o, names, what) {
      const listed = pySplit(c.attrs.get('values'));
      if (new Set(listed).size < 2) fail(c.file, c.line, `${what}: 2 or more values expected`);
      for (const n of listed) if (!names.includes(n)) fail(c.file, c.line, `${what}: unknown value ${n}`);
      if (o.def < 0) fail(c.file, c.line, `${what}: values need a default, what a stored value outside them reads as`);
      for (const [attr, field] of [['default', 'def'], ['preset', 'preset'], ['keep', 'keep']]) {
        if (o[field] >= 0 && !listed.includes(names[o[field]])) fail(c.file, c.line, `${what}: ${attr} ${names[o[field]]} is not in values`);
      }
      return [...new Set(listed)].reduce((sum, n) => sum + 2 ** names.indexOf(n), 0);
    }

    function ownOption(c, known) {
      const err = (node, message) => fail(node.file, node.line, message);
      const key = ownKey(c, c.attrs.get('key'));
      if (c.attrs.has('values')) err(c, `${key}: its <value>s are its values`);
      if (!labelOk(c.attrs.get('label') ?? '')) err(c, `${key}: label expected 1..24 bytes, no control characters`);
      const names = [];
      const named = [];
      for (const v of c.children) {
        for (const k of v.attrs.keys()) if (k !== 'label' && k !== 'set') err(v, `unknown key value.${k}`);
        const x = v.attrs.get('label') ?? '';
        if (!labelOk(x)) err(v, `${key}: value label expected 1..24 bytes, no control characters`);
        if (names.includes(x)) err(v, `${key}: duplicate value ${x}`);
        if (v.attrs.has('set') !== c.children[0].attrs.has('set')) err(v, `${key}: every value names a set, or none does`);
        if (v.attrs.has('set') && !own(known, v.attrs.get('set'))) err(v, `unknown geometry set "${v.attrs.get('set')}"`);
        names.push(x);
        named.push(v.attrs.get('set') ?? null);
      }
      if (!(names.length >= 2 && names.length <= 10)) err(c, `${key}: 2 to 10 values expected`);
      if (!named[0] && !PLAIN_KEYS.has(key)) err(c, `${key}: a plain choice the payload does not read (PLAIN_KEYS)`);
      return presets(c, { setting: 'SETTING_OWN', key, label: c.attrs.get('label'), names, sets: named[0] ? named : null,
                          def: -1, preset: -1, keep: -1, values: 0 }, names, key);
    }

    // ---- resolve ----

    const zeroScheme = () => ({ ...Object.fromEntries(KEYS.filter(isScheme).map((k) => [k.field, k.default])), light: {} });
    // The names accent values index: the ACCENTS rows, then the theme's own schemes.
    const schemeNames = (t) => [...ACCENT_NAMES, ...t.schemes.slice(ACCENT_NAMES.length).map((s) => s.name)];
    const bit = (mask, i) => i >= 0 && Math.floor(Number(mask) / 2 ** i) % 2 === 1;

    function splitHalf(attr) {
      const dot = attr.indexOf('.');
      const h = dot < 0 ? '' : attr.slice(0, dot);
      return h === 'light' || h === 'dark' ? [h, attr.slice(dot + 1)] : [null, attr];
    }

    function checkTags(node) {
      for (const c of node.children) {
        if (!(own(CHILDREN, node.tag) && CHILDREN[node.tag].includes(c.tag))) fail(c.file, c.line, `unknown element <${c.tag}>`);
        checkTags(c);
      }
    }

    // c, a colour of Classic Blue's band, in the accent whose top tone is top.
    function turn(c, top) {
      const hsv = (x) => rgbToHsv((x >> 16 & 255) / 255, (x >> 8 & 255) / 255, (x & 255) / 255);
      const [h0, s0, v0] = hsv(GLOSS.stops[2][1]);
      const [h, s, v] = hsv(top);
      const [ch, cs, cv] = hsv(c);
      const least = (x) => (x < 1 ? x : 1);
      const rgb = hsvToRgb(pyMod1(ch + h - h0), least(cs * s / s0), least(cv * v / v0));
      return rgb.reduce((sum, x) => sum * 256 + pyRound(255 * x), 0);
    }

    // field -> value for one theme: the defaults or its base, then its body, then ROLE_MACROS. root: a
    // parsed theme; byId: a Map of every theme it can extend.
    function resolveNode(root, byId, seen = []) {
      const err = (node, message) => fail(node.file, node.line, message);
      const a = root.attrs;
      for (const k of a.keys()) if (!['format', 'id', 'name', 'index', 'extends'].includes(k)) err(root, `unknown key theme.${k}`);
      const tid = a.get('id') ?? '';
      if (!/^[a-z][a-z0-9_-]*$/.test(tid)) err(root, 'id: expected [a-z][a-z0-9_-]*');
      const name = a.get('name') ?? '';
      if (!(utf8(name) > 0 && utf8(name) <= NAME_BYTES) || CONTROL.test(name)) err(root, 'name: expected 1..48 bytes, no control characters');
      if (!/^[0-9]$/.test(a.get('index') ?? '')) err(root, 'index: expected a digit');
      if (seen.includes(tid)) err(root, `extends cycle at ${tid}`);
      checkTags(root);
      let t;
      if (a.has('extends')) {
        if (!byId.has(a.get('extends'))) err(root, `extends unknown theme ${a.get('extends')}`);
        t = resolveNode(byId.get(a.get('extends')), byId, [...seen, tid]);
      } else {
        t = { accents: Number(ALL_ACCENTS), accent_key: null, schemes: ACCENT_NAMES.map(zeroScheme), opts: [], geoms: {},
              ...Object.fromEntries(KEYS.filter((k) => !isScheme(k)).map((k) => [k.field, k.default])), light: {} };
      }
      Object.assign(t, { id: tid, name, index: Number(a.get('index')), line: root.line });
      let accents = BigInt(t.accents);
      const macros = new Map((own(ROLE_MACROS, tid) ? ROLE_MACROS[tid] : []).map((m) => [m.field, m.value]));
      let opts = null;
      const named = [];
      for (const c of root.children) {
        if (c.tag === 'colorSchemes') {
          accents = 0n;
          delete t.derive;
          for (const k of c.attrs.keys()) if (k !== 'accents' && k !== 'derive') err(c, `unknown key colorSchemes.${k}`);
          if ((c.attrs.get('derive') ?? 'gloss') !== 'gloss') err(c, `colorSchemes.derive: unknown value ${c.attrs.get('derive')}`);
          if (c.attrs.has('derive')) t.derive = 'gloss';
          const names = schemeNames(t);
          for (const n of pySplit(c.attrs.get('accents') ?? '')) {
            if (!names.includes(n)) err(c, `unknown scheme ${n}`);
            accents |= 1n << BigInt(names.indexOf(n));
          }
        } else if (c.tag === 'colorScheme') {
          const n = c.attrs.get('name'); // none: every scheme the theme has
          const mine = n !== undefined && c.attrs.has('base'); // a scheme of the theme's own, after the ACCENTS rows
          if (mine) {
            const label = c.attrs.get('label') ?? '';
            const base = c.attrs.get('base');
            if (ACCENT_NAMES.includes(n)) err(c, `${n}: an ACCENTS row takes no base`);
            if (!ACCENT_NAMES.includes(base)) err(c, `${n}: unknown base ${base}`);
            if (!label) err(c, `${n}: an own scheme needs a label`);
            if (utf8(label) > NAME_BYTES || CONTROL.test(label)) err(c, `${n}: label: expected 1..48 bytes, no control characters`);
            if (!schemeNames(t).includes(n)) {
              const b = t.schemes[ACCENT_NAMES.indexOf(base)];
              t.schemes.push({ ...b, name: n, label, base: ACCENT_NAMES.indexOf(base), light: { ...b.light } });
              accents |= 1n << BigInt(t.schemes.length - 1);
            }
          }
          const names = schemeNames(t);
          if (n !== undefined && !names.includes(n)) err(c, `unknown scheme ${n}`);
          if (n !== undefined) named.push([c, n]);
          const targets = n === undefined ? t.schemes : [t.schemes[names.indexOf(n)]];
          for (const [attr, stated] of c.attrs) {
            if (attr === 'name' || (mine && (attr === 'base' || attr === 'label'))) continue;
            const [h, k] = splitHalf(attr);
            const path = `scheme.${k}`;
            const x = value(c, path, stated, macros);
            const f = SCHEMA.get(path);
            if (k === 'paper' || k === 'ink') { // the light half's flip ends; the dark half's are fixed
              if (h !== 'light') err(c, `${path}: the dark half's is ${k === 'paper' ? '#000000' : '#ffffff'}; write light.${k}`);
            } else if (h && !f.final) {
              err(c, `${path}: one value for both halves`);
            } else if (h === 'dark' && c.attrs.has(k)) {
              err(c, `${path}: stated twice (${k} and dark.${k})`);
            }
            for (const s of targets) (h === 'light' && f.final ? s.light : s)[f.field] = x;
          }
        } else if (c.tag === 'geometry') {
          if (c.attrs.has('name')) {
            const g = declare(c, sets(t));
            t.geoms[g.name] = g;
            continue;
          }
          for (const [k, stated] of c.attrs) {
            if (k !== 'set') err(c, `unknown key geometry.${k}`);
            if (!own(sets(t), stated)) err(c, `unknown geometry set "${stated}"`);
            t.geom_set = stated;
          }
        } else if (c.tag === 'option') {
          if (opts === null) opts = t.opts = []; // this file's options replace the inherited list
          for (const k of c.attrs.keys()) if (!OPTION_ATTRS.has(k)) err(c, `unknown key option.${k}`);
          if (c.attrs.has('key') && !c.attrs.has('setting')) {
            opts.push(ownOption(c, sets(t)));
            continue;
          }
          const s = c.attrs.get('setting') ?? '';
          if (!own(SETTINGS, s)) err(c, `unknown setting ${s}`);
          if (c.children.length) err(c.children[0], `${s}: a payload setting takes no <value>`);
          if (c.attrs.has('label')) err(c, `${s}: a payload setting takes no label`);
          const names = s === 'accent' ? schemeNames(t) : SETTINGS[s].values;
          const o = presets(c, { setting: SETTINGS[s].macro, def: -1, preset: -1, keep: -1, values: 0 }, names, s);
          if (c.attrs.has('values')) {
            if (s === 'accent') err(c, 'accent: colorSchemes states its values');
            o.values = offered(c, o, names, s);
          }
          if (c.attrs.has('key')) {
            if (s !== 'accent') err(c, `${s}: unknown key ${c.attrs.get('key')}`);
            t.accent_key = ACCENT_KEYS.includes(c.attrs.get('key')) ? c.attrs.get('key') : ownKey(c, c.attrs.get('key'));
          }
          opts.push(o);
        } else { // view
          const v = c.attrs.get('name') ?? '';
          if (!VIEWS.has(v)) err(c, `unknown view ${v}`);
          for (const [k, stated] of c.attrs) {
            if (k === 'name') continue;
            if (!SCHEMA.has(`${v}.${k}`)) err(c, `unknown key view.${k}`);
            t[SCHEMA.get(`${v}.${k}`).field] = value(c, `${v}.${k}`, stated, macros);
          }
          for (const e of c.children) {
            const el = `${v}.${e.attrs.get('name') ?? ''}`;
            if (!ELEMENTS.has(el)) err(e, `unknown element ${el}`);
            for (const [attr, stated] of e.attrs) {
              if (attr === 'name') continue;
              const [h, k] = splitHalf(attr);
              const x = value(e, `${el}.${k}`, stated, macros);
              const f = SCHEMA.get(`${el}.${k}`);
              if (h && !f.final) err(e, `${el}.${k}: one value for both halves`);
              if (h === 'dark' && e.attrs.has(k)) err(e, `${el}.${k}: stated twice (${k} and dark.${k})`);
              (h === 'light' ? t.light : t)[f.field] = x;
            }
          }
        }
      }
      for (const [c, n] of named) {
        if (!bit(accents, schemeNames(t).indexOf(n))) err(c, `scheme ${n} is not in colorSchemes`);
      }
      for (const [field, stated] of macros) {
        const k = FIELDS.get(field);
        const v = ranged(root, k, stated);
        if (isScheme(k)) for (const s of t.schemes) s[field] = v;
        else t[field] = v;
      }
      if (t.derive) { // the gloss in each offered ACCENTS row that states none
        t.schemes.slice(0, ACCENT_NAMES.length).forEach((s, i) => {
          if (!bit(accents, i) || truthy(s.sel) || truthy(s.light.sel)) return;
          const top = ACCENT_TONES[i][0];
          s.sel = GLOSS.stops.map(([p, c]) => [p, turn(c, top)]);
          for (const [f, g] of [['sel_top', GLOSS.top], ['sel_tall_top', GLOSS.tall_top], ['sel_tall_line', GLOSS.tall_line]]) {
            if (!own(s.light, f)) s.light[f] = s[f] || turn(g, top);
          }
          s.sel_top = s.sel_top || s.sel[0][1];
          s.sel_tall_top = s.sel_tall_top || s.sel[0][1];
          s.sel_edge = s.sel_edge || turn(GLOSS.edge, top);
          s.sel_tall_edge = s.sel_tall_edge || turn(GLOSS.tall_edge, top);
          s.sel_tall_line = s.sel_tall_line || s.sel_tall_edge;
          for (const f of ['sel', 'sel_top', 'sel_edge', 'sel_tall_edge', 'sel_tall_line', 'sel_tall_top']) {
            if (!own(s.light, f)) s.light[f] = s[f];
          }
        });
      }
      t.schemes = t.schemes.map((s, i) => (i >= ACCENT_NAMES.length || bit(accents, i) ? s : zeroScheme()));
      t.accents = Number(accents);
      for (const o of t.opts) if (o.setting === 'SETTING_ACCENT') o.values = accents === ALL_ACCENTS ? 0 : t.accents;
      t.undeclared = MACROS.filter((m) => !t.opts.some((o) => o.setting === m));
      return t;
    }

    // ---- validate ----

    const trig = (degrees) => data.trig[degrees] ?? [Math.sin(degrees * (Math.PI / 180)), Math.cos(degrees * (Math.PI / 180))];
    const accentDefault = (t) => t.opts.find((o) => o.setting === 'SETTING_ACCENT')?.def ?? -1;
    // validate's flat: the pages painter's value is bits (theme.h), classic-light+flat both; nonzero when the flat one is set
    const flatPages = (t) => t['painter[PAINT_PAGES]'] & choices('pages.own.painter').indexOf('flat');

    // The whole-theme rules resolve() can't check per attribute: every one t breaks, in the tool's order (the
    // tool stops at the first), each { message: the tool's words, words: plain ones }.
    function validate(t) {
      const out = [];
      const err = (message, words) => { if (!out.some((p) => p.message === message)) out.push({ message, words: words ?? message }); };
      const settings = t.opts.map((o) => o.key || o.setting);
      const accent = t.opts.find((o) => o.setting === 'SETTING_ACCENT');
      const names = schemeNames(t);
      const on = (i) => bit(t.accents, i);
      if (!accent) err('no accent option', 'The theme has no Accent option. Its options need <option setting="accent" key="...">.');
      if (!t.accent_key) err('accent: no key', 'The Accent option names no key to store the chosen accent under.');
      for (const s of settings) {
        if (settings.filter((x) => x === s).length > 1) err(`${s} declared twice`, `The option ${s} is listed twice.`);
      }
      const flat = flatPages(t);
      if (t.art_final && t.id !== 'classic-light' && !flat) {
        err("pages.own: art_final is for classic-light's own images and the flat look's only",
            'pages.own.art_final only works for the theme whose id is classic-light, or with a flat pages.own.painter (flat, classic-light+flat): the firmware knows those images by name. Set it to 0.');
      }
      if ((t.qs_ground || t.date_gap) && !flat) {
        err("pages.quick.light_ground and pages.date.gap are the flat look's",
            'pages.quick.light_ground and pages.date.gap only change the flat look\'s pages: set pages.own.painter to flat or classic-light+flat, or set both to 0.');
      }
      if (t.sb_w) {
        for (const end of ['top', 'bottom']) {
          const y = t[`sb_${end}`];
          const inset = data.corner_inset[y];
          if (inset > t.sb_right + 1) {
            err(`list.scrollbar: ${end} ${y} is under the glass (inset ${inset} > right ${t.sb_right} + 1)`,
                `The scroll bar's ${end} at row ${y} is hidden by the screen's round corner, which covers ${inset} px there. Move it toward the middle or raise list.scrollbar.right.`);
          }
        }
        if (t.sb_top >= t.sb_bottom) {
          err(`list.scrollbar: top ${t.sb_top} is not above bottom ${t.sb_bottom}`, `The scroll bar's top (${t.sb_top}) must be above its bottom (${t.sb_bottom}).`);
        }
        if (!t.sb_min) err('list.scrollbar: no min', 'The scroll bar is on but its thumb has no smallest length (list.scrollbar.min).');
        if (!t.sb_thumb && !t.light.sb_thumb) err('list.scrollbar: no thumb colour', 'The scroll bar is on but has no colour (list.scrollbar.thumb).');
      }
      if (t.accent_key && t.opts.some((o) => o.key === t.accent_key)) {
        err(`${t.accent_key} declared twice`, `The accent's key ${t.accent_key} is also an own option's key.`);
      }
      if (!t.accents) err('colorSchemes is empty', 'The theme offers no accent: colorSchemes lists none.');
      if (t.schemes.length > SCHEMES_MAX) {
        err(`${t.schemes.length} accents, at most 10`, `A theme can hold ${SCHEMES_MAX} colour schemes; this one has ${t.schemes.length}.`);
      }
      if (t['painter[PAINT_SELECTION]'] === choices('list.selection.painter').indexOf('stops')
          && !t.schemes.every((s, i) => !on(i) || truthy(s.sel) || truthy(s.light.sel))) {
        err("selection: painter stops needs every offered scheme's sel.stops",
            `The selection is drawn from stops, and these offered schemes have none: ${names.filter((n, i) => on(i) && !truthy(t.schemes[i].sel) && !truthy(t.schemes[i].light.sel)).join(', ')}. Give each sel.stops, derive them with colorSchemes derive="gloss", or choose another selection painter.`);
      }
      if (t['painter[PAINT_BATTERY]'] === choices('bar.battery.painter').indexOf('classic-light') && !truthy(t.batt)) {
        err('battery: this painter needs stops', 'The classic-light battery is drawn from bar.battery.stops, and the theme has none.');
      }
      const booted = [...new Set([t.geom_set, ...t.opts.flatMap((o) => o.sets ?? [])])].sort();
      for (const n of booted) {
        const g = sets(t)[n];
        if (g.bar_px && t['font_px[ROLE_BAR]'] !== g.bar_px) {
          err(`bar.title.font_size ${t['font_px[ROLE_BAR]']} is not set ${n}'s bar_px ${g.bar_px}`,
              `The bar's title is laid out at geometry set ${n}'s bar_px (${g.bar_px}) and drawn at bar.title.font_size (${t['font_px[ROLE_BAR]']}): they must be equal.`);
        }
        if (Boolean(g.np_ipod) !== (truthy(t.np_track) || truthy(t.light.np_track))) {
          err(`set ${n}'s np_ipod needs playing.scrubber.stops, and they it`,
              `Geometry set ${n} has np_ipod ${g.np_ipod}, and the theme ${truthy(t.np_track) || truthy(t.light.np_track) ? 'has' : 'has no'} playing.scrubber.stops: the iPod Now Playing and its bar's stops come together or not at all.`);
        }
      }
      for (const o of t.opts) {
        if (o.setting !== 'SETTING_ACCENT' && !o.key && o.def >= 0 && !o.values) {
          err(`${o.setting}: default has no effect without values (settings_read holds a stock setting's default)`,
              `The option ${o.setting} states a default but no values: a default only says what a stored value outside the values reads as.`);
        }
      }
      if (accent) {
        for (const [field, word] of [['def', 'default'], ['preset', 'preset']]) {
          if (accent[field] >= 0 && !on(accent[field])) {
            err(`accent ${word} ${names[accent[field]]} is not in colorSchemes`, `The Accent option's ${word}, ${names[accent[field]]}, is not one of the offered schemes.`);
          }
        }
        if (accent.def < 0 && !on(0)) {
          err('accent: slot 0 is not offered, so a missing key needs a default',
              `The Accent option needs a default: with none, a Q2 that has never stored one would use ${names[0]}, which this theme does not offer.`);
        }
      }
      for (const k of KEYS) {
        if (['set', 'stops', 'alphas', 'rows'].includes(k.type)) continue;
        for (const v of isScheme(k) ? t.schemes.map((s) => s[k.field]) : [t[k.field], own(t.light, k.field) ? t.light[k.field] : k.lo]) {
          if (!(k.lo <= v && v <= k.hi)) {
            err(`${k.path}: ${v} outside ${k.lo}..${k.hi}`, `${k.path} is ${v}; it must be from ${k.lo} to ${k.hi}. Nothing in the theme or its base sets it.`);
          }
        }
      }
      if (t.pane_shadow_w > t.pane_shadow_a.length) {
        err(`home.pane.shadow_w: ${t.pane_shadow_w} past its ${t.pane_shadow_a.length} alphas`,
            `Home's pane shadow is ${t.pane_shadow_w} px wide but home.pane.shadow_a lists ${t.pane_shadow_a.length} alphas: one is needed per column.`);
      }
      for (const s of t.schemes) {
        for (const f of ['paper', 'ink']) {
          if (new Set([s[f] >> 16, s[f] >> 8 & 255, s[f] & 255]).size > 1) err(`scheme.${f}: expected a grey`, `A scheme's light ${f} must be a grey (equal red, green and blue).`);
        }
        if ((s.paper & 255) <= (s.ink & 255)) err('scheme.paper: must be lighter than ink', "A scheme's light paper must be lighter than its ink.");
      }
      if (settings.includes('SETTING_LIGHT') && t.schemes.some((s) => s.mode)) {
        err('light: a scheme with its own mode has no Light Mode option', 'A scheme fixes its own light or dark mode, so the theme cannot also list the Light Mode option.');
      }
      const cf = (a) => t[`cf.${a}`];
      const shelf = cf('top') + 160 + cf('reflect'); // 160: coverflow.c's ART_SIZE
      if (shelf > cf('view_h')) {
        err(`coverflow.shelf: top + 160 + reflect = ${shelf} exceeds ${cf('view_h')}`,
            `Cover Flow's shelf does not fit its frame: top + 160 + reflect is ${shelf}, and view_h is ${cf('view_h')}.`);
      }
      const [sin, cos] = trig(cf('tilt'));
      const near = 80 * sin; // half a side cover's width turned toward the eye
      if (cf('eye') + cf('z1') <= near) {
        err(`coverflow.shelf: eye + z1 = ${cf('eye') + cf('z1')} doesn't clear 80 sin(tilt) = ${pyFixed(near, 1)}`,
            `Cover Flow's first side cover would reach the eye: eye + z1 (${cf('eye') + cf('z1')}) must be more than ${pyFixed(near, 1)}.`);
      }
      if (cf('swing') === 1) {
        const clear = cf('eye') - Math.max(0, 80 - cf('z1') / sin) - cf('lift') / 4;
        if (clear <= 0) {
          err(`coverflow.shelf: swing's near edge reaches the eye mid-step: eye - max(0, 80 - z1 / sin(tilt)) - lift / 4 = ${pyFixed(clear, 1)}`,
              'With swing 1, a cover turning between places would reach the eye: raise eye or z1, or lower lift.');
        }
        const rest = (cf('x1') + 80 * cos) * cf('eye') / (cf('eye') + cf('z1') - near);
        if (rest >= 2048) {
          err(`coverflow.shelf: swing's near edge rests ${pyFixed(rest, 0)} px out, past 2048`, 'With swing 1, the first side cover\'s near edge lands too far out for the renderer (2048 px or more).');
        }
      }
      if (cf('eye') + cf('eye_turn') > 2046) {
        err(`coverflow.shelf: eye + eye_turn = ${cf('eye') + cf('eye_turn')} exceeds 2046`, `Cover Flow's eye + eye_turn is ${cf('eye') + cf('eye_turn')}; the renderer takes 2046 at most.`);
      }
      if (cf('thumb')) {
        for (const a of ['ticks_turn', 'ticks_album', 'track', 'snap', 'spin', 'far_left', 'rate_up', 'rate_down', 'lead_ms', 'row_edge', 'enter_albums', 'slide_ms']) {
          if (!cf(a)) err(`coverflow.shelf: thumb needs ${a}`, `Cover Flow's thumb is on, so coverflow.shelf.${a} cannot be 0.`);
        }
        if (cf('arch_span')) {
          for (const a of ['arch_in', 'arch_out', 'arch_tau']) {
            if (!cf(a)) err(`coverflow.shelf: arch_span needs ${a}`, `Cover Flow's arch is on (arch_span), so coverflow.shelf.${a} cannot be 0.`);
          }
          if (cf('arch_span') < 100 || cf('arch_full') <= cf('arch_at')) {
            err('coverflow.shelf: arch_span must be an album (100) or more, and arch_full must pass arch_at',
                "Cover Flow's arch_span must be 100 or more, and arch_full more than arch_at.");
          }
        }
        for (const [lo, hi] of [['fast_at', 'fast_full'], ['fast_at', 'jump_at'], ['fast_at', 'big_jump_at'], ['lead_from', 'lead_full'], ['row_from', 'row_full']]) {
          if (cf(hi) <= cf(lo)) err(`coverflow.shelf: ${hi} ${cf(hi)} must pass ${lo} ${cf(lo)}`, `Cover Flow's ${hi} (${cf(hi)}) must be more than ${lo} (${cf(lo)}).`);
        }
        const sh = 1 - cf('row_shrink') / 100;
        const f = Math.max(cf('row_flat') / 100, 1);
        const x = cf('x1') + cf('xs') * (f - 1);
        const z = cf('z1') + cf('zs') * (f - 1);
        const eye = cf('eye');
        const edge = [80, -80].map((u) => (x + u * cos) * eye / (eye + z - u * sin));
        const w = (edge[0] - edge[1]) * (1 - cf('row_width') / 100) * sh;
        const n = cf('row_out') ? Math.ceil((O.CF_VIEW_W + w) / (cf('row_out') * sh)) : Infinity;
        if (n > O.CF_WIDE) {
          err(`coverflow.shelf: row_out ${cf('row_out')} puts ${n === Infinity ? 'inf' : n} covers of the held row on the screen, past CF_WIDE ${O.CF_WIDE}`,
              `Cover Flow's held row would show more covers than the ${O.CF_WIDE} it draws: raise coverflow.shelf.row_out.`);
        }
      }
      if (cf('land_ms')) {
        if (!cf('land_travel')) err('coverflow.land: ms needs travel', "Cover Flow's landing has a time (ms) but no travel.");
        for (const a of ['out', 'np']) {
          const end = cf(`land_${a}_at`) + cf(`land_${a}_ms`);
          if (end > cf('land_ms')) {
            err(`coverflow.land: ${a}_at + ${a}_ms = ${end} exceeds ms ${cf('land_ms')}`, `Cover Flow's landing: ${a}_at + ${a}_ms (${end}) must end within ms (${cf('land_ms')}).`);
          }
        }
      }
      for (const k of MOTIONS) {
        if (!k.startsWith('coverflow_step') && EASINGS[t[`motion.${k}.easing`]] === 'follow') {
          err(`motion.${k}.easing: follow is only for coverflow_step and coverflow_step_fast`, `The easing "follow" only works for Cover Flow's steps, not motion.${k}.`);
        }
      }
      if (cf('bright2') > cf('bright1')) {
        err(`coverflow.shelf: bright2 ${cf('bright2')} exceeds bright1 ${cf('bright1')}`, `Cover Flow's bright2 (${cf('bright2')}) cannot be more than bright1 (${cf('bright1')}).`);
      }
      const captions = O.CF_NAME_H + O.CF_ARTIST_H;
      const bar = geometry(t).bar;
      if (cf('view_h') > 320 - bar) {
        err(`coverflow.shelf: view_h ${cf('view_h')} exceeds the client height ${320 - bar}`, `Cover Flow's frame (view_h ${cf('view_h')}) is taller than the ${320 - bar} px under the ${bar} px bar.`);
      }
      if (cf('text_y') + captions > 320 - bar) {
        err(`coverflow.caption: text_y + ${captions} = ${cf('text_y') + captions} exceeds the client height ${320 - bar}`,
            `Cover Flow's caption ends at ${cf('text_y') + captions}, past the ${320 - bar} px under the ${bar} px bar: lower coverflow.caption.text_y.`);
      }
      for (const [box, y, h] of [['title', t.page_cap_y, t.page_cap_h], ['detail', t.page_det_y, t.page_det_h]]) {
        if (y + h > t.page_detail) {
          err(`page.rows: ${box} box ends at ${y + h}, past the ${t.page_detail} px row`, `A page row's ${box} box ends at ${y + h}, past the row's ${t.page_detail} px (page.rows.detail_height).`);
        }
      }
      for (const [box, h, role, path] of [['title_h', t.page_cap_h, 'ROLE_TALL', 'list.row.tall_px'], ['detail_h', t.page_det_h, 'ROLE_META', 'list.row.meta_px'],
                                          ['height', t.page_row, 'ROLE_TITLE', 'list.row.title_px']]) {
        const px = t[`font_px[${role}]`];
        if (h < px) err(`page.rows.${box}: ${h} is shorter than its ${px} px font`, `page.rows.${box} (${h}) is shorter than the ${px} px text it holds (${path}), so nothing would be drawn.`);
      }
      const chooser = t.opts.filter((o) => o.sets);
      if (chooser.length > 1) err('one option per theme selects the geometry set', 'Only one own option may choose the geometry set.');
      for (const o of chooser) {
        const d = Math.max(o.def, 0);
        if (o.sets[d] !== t.geom_set) {
          err(`${o.key}: default ${o.names[d]} boots ${o.sets[d]}, the theme's geometry is ${t.geom_set}`,
              `The option ${o.key}'s default, ${o.names[d]}, chooses geometry set ${o.sets[d]}, but the theme's own set is ${t.geom_set}: they must agree.`);
        }
        for (const s of o.sets) {
          if (sets(t)[s].bar !== bar) {
            err(`${o.key}: set ${s} has a ${sets(t)[s].bar} px bar, the theme's is ${bar}`, `Every set the option ${o.key} chooses needs the theme's ${bar} px bar; ${s} has ${sets(t)[s].bar}.`);
          }
        }
      }
      return out;
    }

    // ---- every theme together ----

    const same = (a, b) => {
      if (a === b) return true;
      if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null || Array.isArray(a) !== Array.isArray(b)) return false;
      const keys = Object.keys(a);
      return keys.length === Object.keys(b).length && keys.every((k) => own(b, k) && same(a[k], b[k]));
    };

    // The themes' own IPOD keys: key -> [value count, default, the own option or null for an accent key].
    function themeKeys(themes) {
      const keys = new Map();
      for (const t of themes) {
        for (const o of t.opts) {
          if (o.key) {
            if (!keys.has(o.key)) keys.set(o.key, [o.names.length, Math.max(o.def, 0), o]);
          } else if (o.setting === 'SETTING_ACCENT' && !ACCENT_KEYS.includes(t.accent_key)) {
            if (!keys.has(t.accent_key)) keys.set(t.accent_key, [t.schemes.length, Math.max(accentDefault(t), 0), null]);
          }
        }
      }
      return keys;
    }

    // The distinct geometry sets of themes and their own options' values, the built-in first.
    function geometrySets(themes) {
      const found = [SET0];
      const add = (g) => { if (!found.some((x) => same(x, g))) found.push(g); };
      for (const t of themes) add(geometry(t));
      for (const t of themes) for (const o of t.opts) for (const s of o.sets ?? []) add(sets(t)[s]);
      return found;
    }

    // What the tool's builtins() makes of a folder of themes. files: [{ folder, source }], source a
    // theme.xml's text or bytes. Returns { themes: each resolved, by index, and problems: [{ message, words,
    // file, line }] in the order the tool would meet them }. The tool stops at its first; this goes on while
    // it can, so a file that cannot be read or resolved ends the list.
    function builtins(files) {
      const problems = [];
      const note = (file, line, message, words) => problems.push({ file, line, message, words: words ?? explain(message) });
      const sorted = [...files].sort((a, b) => (a.folder < b.folder ? -1 : a.folder > b.folder ? 1 : 0));
      let found = [];
      try {
        const nodes = sorted.map((f) => load(f.source, `${f.folder}/theme.xml`));
        const byId = new Map();
        for (const n of nodes) {
          const i = n.attrs.get('id');
          if (byId.has(i)) fail(n.file, n.line, `id ${i ?? 'None'} is ${byId.get(i).file}'s too`);
          byId.set(i, n);
        }
        for (const n of nodes) {
          const t = resolveNode(n, byId);
          for (const p of validate(t)) note(n.file, t.line, p.message, p.words);
          if (t.id !== n.file.split('/')[0]) note(n.file, n.line, `id ${t.id} is not its folder name`);
          found.push([t.index, n, t]);
        }
      } catch (e) {
        if (!(e instanceof ThemeError)) throw e;
        note(e.file, e.line, e.detail);
        return { themes: found.map((f) => f[2]), problems };
      }
      found = found.map((f, i) => [f, i]).sort((a, b) => a[0][0] - b[0][0] || a[1] - b[1]).map((f) => f[0]);
      const pairs = found.flatMap((a, i) => found.slice(i + 1).map((b) => [a, b]));
      const owners = new Map(); // a set name is one GEOM_* id and one <set>_<name>.bin prefix
      for (const [, n, t] of found) {
        for (const [name, g] of Object.entries(t.geoms)) {
          if (!owners.has(name)) owners.set(name, [t.id, g]);
          if (!same(g, owners.get(name)[1])) note(n.file, n.line, `geometry set ${name} is ${owners.get(name)[0]}'s, with other values`);
        }
      }
      // An accent key is one stored value, which the boot fixup forces into every sharing theme's colours.
      for (const [[, , t], [, n, u]] of pairs) {
        if (t.accent_key === u.accent_key && (t.accents !== u.accents || accentDefault(t) !== accentDefault(u))) {
          note(n.file, n.line, `accent key ${u.accent_key} is ${t.id}'s, with other colorSchemes or default`);
        }
      }
      // Themes on one set switch live, relabelling the booted one's Appearance rows: the same rows.
      const rows = (t) => t.opts.map((o) => (o.setting === 'SETTING_OWN' ? o.key : o.setting));
      for (const [[, , t], [, n, u]] of pairs) {
        if (t.geom_set === u.geom_set && !same(rows(t), rows(u))) note(n.file, n.line, `${u.id} runs on ${t.id}'s set, with other options`);
      }
      // An own key is one stored value too: its values and default alike; its preset is each theme's.
      const shape = ([count, def, o]) => [count, def, o && { ...o, preset: 0, keep: 0 }];
      const keyOwners = new Map();
      for (const [, n, t] of found) {
        for (const [key, e] of themeKeys([t])) {
          if (!keyOwners.has(key)) keyOwners.set(key, [t, e]);
          if (!same(shape(keyOwners.get(key)[1]), shape(e))) note(n.file, n.line, `${key} is ${keyOwners.get(key)[0].id}'s, with other values or default`);
        }
      }
      found.forEach(([index, n], i) => { if (index !== i) note(n.file, n.line, `index ${index}, expected ${i}`); });
      const themes = found.map((f) => f[2]);
      const count = geometrySets(themes).length;
      if (count > SETS_MAX && found.length) { // emit()
        note(found[found.length - 1][1].file, 1, `${count} geometry sets: ui_redirect_t.sets holds 8`,
             `The themes use ${count} geometry sets between them; the firmware holds ${SETS_MAX}.`);
      }
      return { themes, problems };
    }

    // The tool's message in plain words, where it has more to say than the message does.
    const PLAIN = [
      [/^larger than 32 KB$/, () => 'The theme file is larger than 32 KB.'],
      [/^not UTF-8$/, () => 'The theme file is not UTF-8 text.'],
      [/^unclosed comment$/, () => 'A comment (<!-- ... -->) is never closed, or holds "--".'],
      [/^malformed tag$/, () => 'A tag is not written as the format allows: lowercase attribute names, double-quoted values, no "<" or control characters in a value.'],
      [/^text between tags$/, () => 'There is text outside the tags; only tags, comments and spaces are allowed.'],
      [/^unknown entity$/, () => 'An attribute uses "&" other than as &amp; &lt; &gt; or &quot;.'],
      [/^root must be /, () => 'The file must be one <theme format="1"> element.'],
      [/^id: expected/, () => "The theme's id must start with a lowercase letter and hold only lowercase letters, digits, - and _."],
      [/^name: expected/, () => "The theme's name must be 1 to 48 bytes with no control characters."],
      [/^index: expected a digit$/, () => "The theme's index must be one digit, 0 to 9."],
      [/^extends unknown theme (.*)$/, (m) => `The theme extends "${m[1]}", which is not a theme.`],
      [/^(.*) comes from patch\/offsets\.inc$/, (m) => `${m[1]} cannot be stated by this built-in theme: the firmware's sources supply it.`],
      [/^(.*): #000000 reads as unset; use #010101$/, (m) => `${m[1]} cannot be pure black, which means "not set" there; use #010101.`],
      [/^(.*): (-?\d+) outside (-?\d+)\.\.(-?\d+)$/, (m) => `${m[1]} is ${m[2]}; it must be from ${m[3]} to ${m[4]}.`],
      [/^(.*): one value for both halves$/, (m) => `${m[1]} has one value for light and dark alike; it takes no light. or dark. form.`],
      [/^scheme (.*) is not in colorSchemes$/, (m) => `The scheme ${m[1]} has values but is not one of the offered accents.`],
      [/^unknown scheme (.*)$/, (m) => `"${m[1]}" is not an accent or one of the theme's own schemes.`],
      [/^geometry set (.*) declared twice$/, (m) => `The geometry set ${m[1]} already exists, here or in the theme this one extends; a new set needs a new name.`],
      [/^unknown geometry set "(.*)"$/, (m) => `There is no geometry set "${m[1]}" at this point in the theme.`],
      [/^(.*): the payload's key$/, (m) => `${m[1]} is a key the firmware stores a setting of its own under; choose another.`],
      [/^(.*): a plain choice the payload does not read \(PLAIN_KEYS\)$/,
       (m) => `The option ${m[1]} chooses no geometry set and is not one the firmware reads (${[...PLAIN_KEYS].join(', ')}), so it would do nothing.`],
      [/^id (.*) is not its folder name$/, (m) => `The theme's id, ${m[1]}, must be the name of its folder under assets/themes.`],
      [/^geometry set (.*) is (.*)'s, with other values$/, (m) => `The geometry set ${m[1]} is also ${m[2]}'s, with other numbers; a set's name is one set across all themes.`],
      [/^accent key (.*) is (.*)'s, with other colorSchemes or default$/,
       (m) => `The theme stores its accent under ${m[1]}, as ${m[2]} does, but offers other schemes or another default. Give its Accent option a key of its own.`],
      [/^(.*) runs on (.*)'s set, with other options$/,
       (m) => `${m[1]} uses the same geometry set as ${m[2]}, so the Q2 switches between them without a restart: both must list the same options in the same order.`],
      [/^(.*) is (.*)'s, with other values or default$/, (m) => `The key ${m[1]} is also ${m[2]}'s, with other values or another default; a key is one stored value across all themes.`],
      [/^index (\d+), expected (\d+)$/, (m) => `The themes' indexes must count up from 0 with none missing: this one has ${m[1]} where ${m[2]} is due.`],
    ];

    function explain(message) {
      for (const [pattern, words] of PLAIN) {
        const m = pattern.exec(message);
        if (m) return words(m);
      }
      return message;
    }

    // ---- what each half draws ----

    // theme_engine.c's flip(): a neutral per channel between paper and ink; a colour as it is.
    function flip(c, paper, ink) {
      const ch = [c & 255, c >> 8 & 255, c >> 16 & 255];
      if (Math.max(...ch) - Math.min(...ch) > O.LIGHT_SPREAD) return c;
      const p = paper & 255;
      const i = ink & 255;
      return ch.reduce((sum, v, n) => sum + (p - Math.floor(v * (p - i) / 255)) * 256 ** n, 0);
    }

    // flip's approximate inverse. Paper and ink alike have none: the colour as it is (the tool divides by zero).
    function unflip(c, paper, ink) {
      const ch = [c & 255, c >> 8 & 255, c >> 16 & 255];
      const p = paper & 255;
      const i = ink & 255;
      if (Math.max(...ch) - Math.min(...ch) > O.LIGHT_SPREAD || p === i) return c;
      return ch.reduce((sum, v, n) => sum + Math.min(255, Math.max(0, Math.floor((p - v) * 255 / (p - i)))) * 256 ** n, 0);
    }

    // d's final fields in one half: the stated value, else the other half's flipped (light) or unflipped (dark).
    function half(d, light, paper, ink) {
      const out = {};
      for (const f of Object.keys(d)) if (f !== 'light') out[f] = d[f];
      const turned = light ? flip : unflip;
      for (const k of FINAL) {
        if (!own(d, k.field)) continue;
        let v = light ? d.light[k.field] : truthy(d[k.field]) ? d[k.field] : undefined;
        if (v === undefined) {
          const o = light ? d[k.field] : own(d.light, k.field) ? d.light[k.field] : k.default;
          v = k.type === 'stops' ? o.map(([p, c]) => [p, turned(c, paper, ink)]) : o && turned(o, paper, ink);
        }
        out[k.field] = v;
      }
      return out;
    }

    const schemeHalf = (s, light) => ({ ...half(s, light, s.paper, s.ink), ...(light ? {} : { paper: 0, ink: 0xffffff }) });
    const shared = (t) => !t.schemes.some((s) => Object.keys(s.light).length || FINAL.some((k) => isScheme(k) && truthy(s[k.field])));

    // What the firmware draws of a resolved theme's final values: { shared, theme: { field: [dark, light] },
    // schemes: [[dark, light], ...] }, as the tool's emit() writes them.
    function drawn(t) {
      const d = t.schemes[Math.max(accentDefault(t), 0)];
      const halves = [false, true].map((light) => half(t, light, d.paper, d.ink));
      return { shared: shared(t),
               theme: Object.fromEntries(FINAL.filter((k) => !isScheme(k)).map((k) => [k.field, halves.map((h) => h[k.field])])),
               schemes: t.schemes.map((s) => [schemeHalf(s, false), schemeHalf(s, true)]) };
    }

    // The scheme_t arrays emit() writes for themes (resolved, in index order): a theme whose rows are an
    // earlier theme's points at that theme's array and adds none (Classic Modern at Classic's). Returns
    // { written: [array names in the order emit writes them], themes: [{ schemes, light }, ...] }.
    function schemeArrays(themes) {
      const row = (s, v) => [own(s, 'base') ? s.base : v, s.card | s.raw_red << 1, s.fill, s.chevron, s.muted, s.bar_light, s.sel,
        s.sel_top, s.sel_edge, s.sel_tall_edge, s.sel_tall_line, s.sel_tall_top, s.sel_text, s.mode, s.paper, s.ink, s.bar,
        s.bar_line, s.bar_line2, ...(own(s, 'label') ? [s.label] : [])];
      const rows = (t, light) => JSON.stringify(t.schemes.map((s, v) => row(schemeHalf(s, light), v)));
      const byRows = new Map();
      const written = [];
      const array = (name, body) => {
        if (!byRows.has(body)) { byRows.set(body, name); written.push(name); }
        return byRows.get(body);
      };
      const out = themes.map((t) => {
        const i = t.id.replace(/-/g, '_');
        const one = shared(t);
        const dark = array(`${i}_schemes`, rows(t, one));
        return { schemes: dark, light: one ? dark : array(`${i}_light`, rows(t, true)) };
      });
      return { written, themes: out };
    }

    // ---- a theme to edit ----

    const BUILTINS = data.themes.map((b) => ({ folder: b.id, source: b.text }));
    const builtinNodes = new Map(data.themes.map((b) => [b.id, parse(b.text, b.file)]));
    const fileOf = (theme) => `${theme.id}/theme.xml`;
    const suppliedFor = (id) => new Map((own(ROLE_MACROS, id) ? ROLE_MACROS[id] : []).map((m) => [m.field, m.value]));

    // Every theme a file can extend: the built-ins, and itself in place of the built-in whose id it has.
    function withBuiltins(root) {
      const byId = new Map(builtinNodes);
      byId.set(root.attrs.get('id'), root);
      return byId;
    }

    const esc = (v) => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

    // One tag's text, its attributes wrapped under the first.
    function tag(indent, name, attrs, end = '/>') {
      const words = attrs.filter(([, v]) => v !== undefined && v !== null).map(([k, v]) => `${k}="${esc(v)}"`);
      const pad = ' '.repeat(indent);
      const under = ' '.repeat(indent + name.length + 2);
      const lines = [];
      let line = `${pad}<${name}`;
      words.forEach((w, i) => {
        if (i && line.length + 1 + w.length > 118) {
          lines.push(line);
          line = under + w;
        } else {
          line += ` ${w}`;
        }
      });
      return [...lines, line + end].join('\n');
    }

    // A key's attributes from its two slots: plain, or dark. beside a light.
    function stated(k, attr, values, light, key) {
      const out = [];
      const lightOnly = !k.xml.forms.includes('plain');
      if (own(values, key) && !lightOnly) out.push([own(light, key) ? `dark.${attr}` : attr, text(k.path, values[key])]);
      if (own(light, key)) out.push([`light.${attr}`, text(k.path, light[key])]);
      return out;
    }

    const schemeAttrs = (entry) => KEYS.filter(isScheme).flatMap((k) => stated(k, k.xml.attr, entry.values, entry.light, k.xml.attr));

    // A theme's theme.xml: only what it states itself, in one fixed order and layout.
    function write(theme) {
      const out = [tag(0, 'theme', [['format', '1'], ['id', theme.id], ['name', theme.name], ['index', theme.index], ['extends', theme.extends]], '>')];
      for (const g of theme.geometry.sets) {
        const fields = [...GEOM_FIELDS.map((f) => f.name).filter((f) => own(g.fields, f)), ...Object.keys(g.fields).filter((f) => !GEOM_RANGES.has(f))];
        out.push(tag(2, 'geometry', [['name', g.name], ['extends', g.extends], ...fields.map((f) => [f, g.fields[f]])]));
      }
      if (theme.geometry.set !== null) out.push(tag(2, 'geometry', [['set', theme.geometry.set]]));
      const all = schemeAttrs(theme.schemes.all);
      if (all.length) out.push(tag(2, 'colorScheme', all));
      for (const s of theme.schemes.named) {
        const attrs = [['name', s.name], ['base', s.base], ['label', s.label], ...schemeAttrs(s)];
        if (attrs.filter(([, v]) => v !== undefined && v !== null).length > 1) out.push(tag(2, 'colorScheme', attrs));
      }
      if (theme.schemes.offered !== null) {
        out.push(tag(2, 'colorSchemes', [['accents', theme.schemes.offered.join(' ')], ['derive', theme.schemes.derive ? 'gloss' : null]]));
      }
      const views = new Map();
      for (const k of KEYS) {
        if (k.xml.tag !== 'view') continue;
        const attrs = stated(k, k.xml.attr, theme.values, theme.light, k.path);
        if (!attrs.length) continue;
        if (!views.has(k.xml.view)) views.set(k.xml.view, { attrs: [], elements: new Map() });
        const view = views.get(k.xml.view);
        if (!k.xml.element) view.attrs.push(...attrs);
        else view.elements.set(k.xml.element, [...(view.elements.get(k.xml.element) ?? []), ...attrs]);
      }
      for (const [name, view] of views) {
        out.push(tag(2, 'view', [['name', name], ...view.attrs], view.elements.size ? '>' : '/>'));
        for (const [element, attrs] of view.elements) out.push(tag(4, 'element', [['name', element], ...attrs]));
        if (view.elements.size) out.push('  </view>');
      }
      for (const o of theme.options ?? []) {
        const attrs = [['setting', o.setting], ['key', o.key], ['label', o.label], ['values', Array.isArray(o.values) ? o.values.join(' ') : o.values],
                       ['default', o.default], ['preset', o.preset], ['keep', o.keep]];
        if (!o.choices) {
          out.push(tag(2, 'option', attrs));
          continue;
        }
        const head = tag(2, 'option', attrs, '>');
        const rows = o.choices.map((c) => tag(0, 'value', [['label', c.label], ['set', c.set]]));
        const line = `${head}${rows.join('')}</option>`;
        const short = !line.includes('\n') && line.length <= 170 && !o.choices.some((c) => c.set);
        if (short) out.push(line);
        else out.push(head, ...rows.map((r) => `    ${r}`), '  </option>');
      }
      out.push('</theme>', '');
      return out.join('\n');
    }

    const emptyTheme = () => ({ id: '', name: '', index: 0, extends: null, geometry: { sets: [], set: null },
                                schemes: { all: { values: {}, light: {} }, named: [], offered: null, derive: false },
                                values: {}, light: {}, options: null });

    // A parsed theme as a theme to edit. Its own statements are kept; their order becomes write()'s.
    function gather(root) {
      const a = root.attrs;
      const theme = { ...emptyTheme(), id: a.get('id'), name: a.get('name'), index: Number(a.get('index')), extends: a.get('extends') ?? null };
      const macros = suppliedFor(theme.id);
      const base = theme.extends === null ? null : resolveNode(withBuiltins(root).get(theme.extends), withBuiltins(root));
      const known = new Set(base ? schemeNames(base) : ACCENT_NAMES);
      const entry = (name) => {
        let e = theme.schemes.named.find((s) => s.name === name);
        if (!e) theme.schemes.named.push(e = { name, values: {}, light: {} });
        return e;
      };
      const option = (c, o) => {
        for (const attr of ['default', 'preset', 'keep']) if (c.attrs.has(attr)) o[attr] = c.attrs.get(attr);
        return o;
      };
      for (const c of root.children) {
        if (c.tag === 'colorSchemes') {
          theme.schemes.offered = [...new Set(pySplit(c.attrs.get('accents') ?? ''))];
          theme.schemes.derive = c.attrs.has('derive');
        } else if (c.tag === 'colorScheme') {
          const n = c.attrs.get('name');
          const mine = n !== undefined && c.attrs.has('base');
          const e = n === undefined ? theme.schemes.all : entry(n);
          if (mine) {
            e.base ??= c.attrs.get('base');
            e.label ??= c.attrs.get('label');
            if (!known.has(n) && theme.schemes.offered !== null && !theme.schemes.offered.includes(n)) theme.schemes.offered.push(n);
            known.add(n);
          }
          for (const [attr, stated_] of c.attrs) {
            if (attr === 'name' || (mine && (attr === 'base' || attr === 'label'))) continue;
            const [h, k] = splitHalf(attr);
            const slot = h === 'light' ? 'light' : 'values';
            e[slot][k] = value(c, `scheme.${k}`, stated_, macros);
            if (n === undefined) for (const s of theme.schemes.named) delete s[slot][k]; // it overrides what they stated before it
          }
        } else if (c.tag === 'geometry') {
          if (c.attrs.has('name')) {
            const fields = {};
            for (const [k, v] of c.attrs) if (k !== 'name' && k !== 'extends') fields[k] = int(v);
            theme.geometry.sets.push({ name: c.attrs.get('name'), extends: c.attrs.get('extends') ?? null, fields });
          } else if (c.attrs.has('set')) {
            theme.geometry.set = c.attrs.get('set');
          }
        } else if (c.tag === 'option') {
          theme.options ??= [];
          if (c.attrs.has('key') && !c.attrs.has('setting')) {
            theme.options.push(option(c, { key: c.attrs.get('key'), label: c.attrs.get('label'),
                                           choices: c.children.map((v) => (v.attrs.has('set') ? { label: v.attrs.get('label'), set: v.attrs.get('set') } : { label: v.attrs.get('label') })) }));
          } else {
            const o = { setting: c.attrs.get('setting') };
            if (c.attrs.has('key')) o.key = c.attrs.get('key');
            if (c.attrs.has('values')) o.values = [...new Set(pySplit(c.attrs.get('values')))];
            theme.options.push(option(c, o));
          }
        } else {
          const v = c.attrs.get('name');
          for (const [k, stated_] of c.attrs) if (k !== 'name') theme.values[`${v}.${k}`] = value(c, `${v}.${k}`, stated_, macros);
          for (const e of c.children) {
            for (const [attr, stated_] of e.attrs) {
              if (attr === 'name') continue;
              const [h, k] = splitHalf(attr);
              const path = `${v}.${e.attrs.get('name')}.${k}`;
              (h === 'light' ? theme.light : theme.values)[path] = value(e, path, stated_, macros);
            }
          }
        }
      }
      theme.schemes.named = theme.schemes.named.filter((s) => s.base !== undefined || Object.keys(s.values).length || Object.keys(s.light).length);
      return theme;
    }

    const resolveRoot = (root) => resolveNode(root, withBuiltins(root));
    const unlined = (t) => ({ ...t, line: 0 });

    // A theme.xml (text or bytes) as a theme to edit. It throws the tool's error for a file the tool's
    // resolve() refuses, and one of its own for a file whose statements only mean what they do in their order.
    function read(source, file) {
      const from = file ?? `${load(source).attrs.get('id') ?? ''}/theme.xml`;
      const root = load(source, from);
      const t = resolveRoot(load(source, from));
      const theme = gather(root);
      let kept;
      try {
        kept = resolveRoot(load(write(theme), from));
      } catch (e) {
        if (!(e instanceof ThemeError)) throw e;
        kept = null;
      }
      if (!kept || !same(unlined(kept), unlined(t))) {
        throw new ThemeError(from, root.line, 'its statements depend on their order in a way the Studio does not keep');
      }
      return theme;
    }

    // The tool's resolve() of a theme to edit, or of a theme.xml's text: field -> value, with accents, schemes,
    // opts, geoms and light, as official.json's themes[].resolved.
    function resolve(theme, file) {
      if (typeof theme === 'string' || theme instanceof Uint8Array) {
        const root = load(theme, file ?? 'theme.xml');
        return resolveRoot(load(theme, file ?? `${root.attrs.get('id') ?? ''}/theme.xml`));
      }
      return resolveRoot(load(write(theme), fileOf(theme)));
    }

    // Everything the firmware's build would refuse about a theme (one to edit, or a theme.xml's text),
    // checked with the built-in themes beside it as the build has them: [{ message: plain words, tool: the
    // tool's own message, file, line }]. A theme with a built-in's id stands in that built-in's place.
    // others: more themes' texts to build with it, [{ folder, source }].
    function problems(theme, others = []) {
      const mine = typeof theme === 'string' || theme instanceof Uint8Array
        ? { folder: folderOf(theme), source: theme }
        : { folder: theme.id, source: write(theme) };
      const files = [...BUILTINS.filter((b) => b.folder !== mine.folder && !others.some((o) => o.folder === b.folder)), ...others, mine];
      return builtins(files).problems.map((p) => ({ message: p.words, tool: `${p.file}:${p.line}: ${p.message}`, file: p.file, line: p.line }));
    }

    // The folder a theme.xml's text belongs in: its id, when it can be read that far.
    function folderOf(source) {
      try {
        return load(source).attrs.get('id') ?? 'theme';
      } catch {
        return (typeof source === 'string' && /<theme\s[^>]*?\bid="([a-z][a-z0-9_-]*)"/.exec(source)?.[1]) || 'theme';
      }
    }

    // Change theme by fn, unless the tool's resolve() refuses the result: then theme stays as it was and
    // the refusal is thrown, in the tool's words.
    function edit(theme, fn) {
      const next = copy(theme);
      fn(next);
      try {
        resolve(next);
      } catch (e) {
        if (!(e instanceof ThemeError)) throw e;
        throw new ThemeError(null, 0, e.detail);
      }
      for (const k of Object.keys(theme)) delete theme[k];
      return Object.assign(theme, next);
    }

    const refuse = (message) => { throw new ThemeError(null, 0, message); };
    const baseOf = (theme) => (theme.extends === null ? null : resolveRoot(builtinNodes.get(theme.extends) ?? refuse(`extends unknown theme ${theme.extends}`)));

    // A new theme over a built-in: { extends: 'minimal', id, name, index }. index: the next free one. Where the
    // base has a value only that built-in may have (Classic's art_final, without a flat pages painter), the new
    // theme states its own. A flat painter's art_final (Modern's, Classic Modern's) is any theme's, so it is kept.
    function newTheme({ extends: base = data.themes[0].id, id, name, index = data.themes.length } = {}) {
      const theme = { ...emptyTheme(), id, name, index, extends: base };
      if (!builtinNodes.has(base)) refuse(`extends unknown theme ${base}`);
      const b = baseOf(theme);
      if (b.art_final && id !== 'classic-light' && !flatPages(b)) theme.values['pages.own.art_final'] = 0;
      return edit(theme, () => {});
    }

    // Change the theme's id, name, index or base: rename(theme, { name: 'Dusk' }).
    const rename = (theme, head) => edit(theme, (t) => {
      for (const k of ['id', 'name', 'index', 'extends']) if (own(head, k)) t[k] = head[k];
    });

    const viewKey = (path) => {
      const k = SCHEMA.get(path);
      if (!k) refuse(`unknown key ${path}`);
      if (k.xml.tag !== 'view') refuse(`${path} is not a view's value: use ${isScheme(k) ? 'setScheme' : 'useGeometry'}`);
      return k;
    };
    const node = (theme) => ({ file: null, line: 0, theme });

    // State a view key's value: set(theme, 'list.row.title_px', 27). A final key's light half:
    // set(theme, 'list.scrollbar.thumb', '#8f98a8', 'light'). Refused outside the key's type, range or choices.
    function set(theme, path, v, halfName) {
      const k = viewKey(path);
      if (halfName && !k.final) refuse(`${path}: one value for both halves`);
      const typed = value(node(theme), path, text(path, v), suppliedFor(theme.id));
      return edit(theme, (t) => { (halfName === 'light' ? t.light : t.values)[path] = typed; });
    }

    // Stop stating a view key: both halves, or the one named ('light' or 'dark').
    const unset = (theme, path, halfName) => edit(theme, (t) => {
      viewKey(path);
      if (halfName !== 'light') delete t.values[path];
      if (halfName !== 'dark') delete t.light[path];
    });

    // The value a theme states for a view key itself (not its base's): undefined when it states none.
    const get = (theme, path, halfName) => (halfName === 'light' ? theme.light : theme.values)[path];

    const schemeKey = (attr) => {
      const k = SCHEMA.get(attr.startsWith('scheme.') ? attr : `scheme.${attr}`);
      if (!k || !isScheme(k)) refuse(`unknown key scheme.${attr}`);
      return k;
    };
    const schemeEntry = (t, name, make) => {
      if (name === null || name === undefined) return t.schemes.all;
      let e = t.schemes.named.find((s) => s.name === name);
      if (!e && make) t.schemes.named.push(e = { name, values: {}, light: {} });
      return e;
    };
    const tidy = (t) => { t.schemes.named = t.schemes.named.filter((s) => s.base !== undefined || Object.keys(s.values).length || Object.keys(s.light).length); };

    // State a scheme's value: setScheme(theme, 'cobalt', 'sel.text', '#ffffff'), a final one's light half with
    // 'light' last; name null: every scheme the theme has. A named scheme's value wins over every scheme's.
    function setScheme(theme, name, attr, v, halfName) {
      const k = schemeKey(attr);
      const lightOnly = !k.xml.forms.includes('plain'); // paper and ink: the light half's alone
      if (halfName && !k.xml.forms.includes('light')) refuse(`${k.path}: one value for both halves`);
      const typed = value(node(theme), k.path, text(k.path, v), suppliedFor(theme.id));
      return edit(theme, (t) => { schemeEntry(t, name, true)[lightOnly || halfName === 'light' ? 'light' : 'values'][k.xml.attr] = typed; });
    }

    const unsetScheme = (theme, name, attr, halfName) => edit(theme, (t) => {
      const k = schemeKey(attr);
      const e = schemeEntry(t, name, false);
      if (!e) return;
      if (halfName !== 'light') delete e.values[k.xml.attr];
      if (halfName !== 'dark') delete e.light[k.xml.attr];
      tidy(t);
    });

    // A scheme of the theme's own, after the accents: addScheme(theme, { name: 'dusk', base: 'cobalt', label: 'Dusk' }).
    // base: the accent whose tones it has and whose values it starts from. It is offered at once.
    function addScheme(theme, { name, base, label }) {
      if (!/^[a-z][a-z0-9-]*$/.test(String(name))) refuse('a scheme\'s name: expected [a-z][a-z0-9-]*');
      if (schemeNames(resolve(theme)).includes(name)) refuse(`scheme ${name} declared twice`);
      return edit(theme, (t) => {
        t.schemes.named = t.schemes.named.filter((s) => s.name !== name);
        t.schemes.named.push({ name, base, label, values: {}, light: {} });
        if (t.schemes.offered !== null) t.schemes.offered.push(name);
      });
    }

    // Take back one of the theme's own schemes, or what it states about an accent.
    const removeScheme = (theme, name) => edit(theme, (t) => {
      t.schemes.named = t.schemes.named.filter((s) => s.name !== name);
      if (t.schemes.offered !== null) t.schemes.offered = t.schemes.offered.filter((n) => n !== name);
    });

    // The accents and own schemes the theme offers, by name; null: its base's. derive: an offered accent with
    // no sel.stops gets Classic Blue's band turned to its own tone.
    const offer = (theme, names, derive = false) => edit(theme, (t) => {
      t.schemes.offered = names === null ? null : [...new Set(names)];
      t.schemes.derive = names !== null && Boolean(derive);
    });

    const ownSet = (t, name) => t.geometry.sets.find((g) => g.name === name) ?? refuse(`${name} is not a geometry set this theme declares`);

    // A geometry set of the theme's own: addGeometry(theme, 'dusk', 'classic-light', { pitch: 36, body: 36 }).
    // base: the set whose numbers it starts from, the built-in when null.
    const addGeometry = (theme, name, base = null, fields = {}) => edit(theme, (t) => {
      t.geometry.sets.push({ name, extends: base, fields: { ...fields } });
    });

    // Change numbers of one of the theme's own sets: setGeometry(theme, 'dusk', { pitch: 40, body: 40 }); a
    // field given as null goes back to its base's. The set must end with every field in its range.
    const setGeometry = (theme, name, fields) => edit(theme, (t) => {
      const g = ownSet(t, name);
      for (const [f, v] of Object.entries(fields)) {
        if (v === null) delete g.fields[f];
        else g.fields[f] = v;
      }
    });

    const removeGeometry = (theme, name) => edit(theme, (t) => {
      ownSet(t, name);
      t.geometry.sets = t.geometry.sets.filter((g) => g.name !== name);
    });

    // The set the theme boots, by name; null: its base's.
    const useGeometry = (theme, name) => edit(theme, (t) => { t.geometry.set = name; });

    // A set's numbers as the theme has them (its own, its base's or the built-in), each field with its
    // range as the others stand: { name, fields: { bar: { value, lo, hi }, ... } }.
    function geometryOf(theme, name) {
      const g = sets(resolve(theme))[name] ?? refuse(`unknown geometry set "${name}"`);
      return { name, fields: Object.fromEntries(GEOM_FIELDS.map((f) => { const [lo, hi] = geometryBounds(g, f.name); return [f.name, { value: g[f.name], lo, hi }]; })) };
    }

    // The base's options as rows this theme can change. A theme's own options replace its base's, all of them.
    function inheritedOptions(theme) {
      const t = baseOf(theme);
      if (!t) return [];
      const picks = (o, names) => Object.fromEntries([['default', 'def'], ['preset', 'preset'], ['keep', 'keep']].filter(([, f]) => o[f] >= 0).map(([a, f]) => [a, names[o[f]]]));
      return t.opts.map((o) => {
        if (o.setting === 'SETTING_OWN') {
          return { key: o.key, label: o.label, choices: o.names.map((label, i) => (o.sets ? { label, set: o.sets[i] } : { label })), ...picks(o, o.names) };
        }
        const setting = Object.keys(SETTINGS).find((s) => SETTINGS[s].macro === o.setting);
        const names = setting === 'accent' ? schemeNames(t) : SETTINGS[setting].values;
        return { setting, ...(setting === 'accent' && t.accent_key ? { key: t.accent_key } : {}),
                 ...(setting !== 'accent' && o.values ? { values: names.filter((n, i) => bit(o.values, i)) } : {}), ...picks(o, names) };
      });
    }

    const optionId = (o) => o.setting ?? o.key;
    const ownOptions = (t) => { t.options ??= inheritedOptions(t); return t.options; };
    const OPTION_WORDS = ['setting', 'key', 'label', 'values', 'default', 'preset', 'keep', 'choices']; // what write() puts in a file
    const optionWords = (o) => { for (const k of Object.keys(o)) if (!OPTION_WORDS.includes(k)) refuse(`unknown key option.${k}`); };

    // The theme's Appearance rows, in order: its own, or its base's when it states none.
    const options = (theme) => copy(theme.options ?? inheritedOptions(theme));

    // Change one option, named by its setting or its own key: setOption(theme, 'light', { preset: 'off' }),
    // setOption(theme, 'accent', { key: 'DUSK_ACCENT' }). A property given as null is taken back. The first
    // change makes the base's options the theme's own.
    const setOption = (theme, id, changes) => edit(theme, (t) => {
      const o = ownOptions(t).find((x) => optionId(x) === id) ?? refuse(`the theme has no option ${id}`);
      for (const [k, v] of Object.entries(changes)) {
        if (v === null) delete o[k];
        else o[k] = copy(v);
      }
      optionWords(o);
    });

    // A new row: { setting: 'corners', preset: 'round' } or { key, label, choices: [{ label, set }], default };
    // at: its place, the end when left out.
    const addOption = (theme, option, at) => edit(theme, (t) => {
      const list = ownOptions(t);
      optionWords(option);
      list.splice(at ?? list.length, 0, copy(option));
    });

    const removeOption = (theme, id) => edit(theme, (t) => {
      const list = ownOptions(t);
      if (!list.some((x) => optionId(x) === id)) refuse(`the theme has no option ${id}`);
      t.options = list.filter((x) => optionId(x) !== id);
    });

    // Back to the base's options.
    const inheritOptions = (theme) => edit(theme, (t) => { t.options = null; });

    // The keys a theme with this id cannot state, with the values the firmware's sources give them: { path: value }.
    const supplied = (id) => Object.fromEntries((own(ROLE_MACROS, id) ? ROLE_MACROS[id] : []).map((m) => [m.path, m.value]));

    return {
      data, keys: KEYS, key: (path) => SCHEMA.get(path), builtinIds: data.themes.map((b) => b.id), accentNames: ACCENT_NAMES,
      value: (path, stated_, id = '') => value({ file: null, line: 0 }, path, stated_, suppliedFor(id)), text, supplied,
      resolveNode, validate, builtins, explain, schemeNames, drawn, schemeArrays, flip, unflip, turn, geometryBounds, setFaults,
      newTheme, read, write, resolve, problems, rename,
      get, set, unset, setScheme, unsetScheme, addScheme, removeScheme, offer,
      addGeometry, setGeometry, removeGeometry, useGeometry, geometryOf,
      options, setOption, addOption, removeOption, inheritOptions,
    };
  }

  return { MIRRORED, TOKEN, MAX_BYTES, NAME_BYTES, LABEL_BYTES, SCHEMES_MAX, SETS_MAX, ThemeError, tokenize, parse, load, open };
});
