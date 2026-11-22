#!/usr/bin/env python3
"""Write official.json: what Q2 Theme Studio knows about q2-pod's theme format, read out of a checkout.

    official_data.py [q2-pod checkout] [-o official.json]

Every fact comes from the checkout's own tools/theme.py (and the tools/ipod.py it imports): its tables
as they stand, its functions asked for their answers. Nothing here is a copy, so running this again
after upstream changes brings the Studio's data up to date. Where the tool keeps a rule in code rather
than in a table (the tokenizer, resolve, validate), `mirrored` holds a hash of each function's source,
which official.test.mjs compares with the hashes official.js was written against.
"""
import argparse
import ast
import dataclasses
import hashlib
import inspect
import json
import math
import os
import pathlib
import re
import subprocess
import sys


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def plain(value):
    """value as JSON holds it: tuples as lists, a Geometry as its fields, a set sorted."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return value


def tree(node):
    """A parsed element as written: its attributes and children in file order."""
    return {'tag': node.tag, 'line': node.line, 'attrs': [[k, v] for k, v in node.attrs.items()],
            'children': [tree(c) for c in node.children]}


def bound(node, constants):
    """One end of a GEOM_RANGES range as data: an int, or {op, args} over ints and {field}."""
    if isinstance(node, ast.Lambda):
        return bound(node.body, constants)
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return {'op': '-', 'args': [0, bound(node.operand, constants)]}
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'g':
        return {'field': node.attr}
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == 'O':
        return constants[ast.literal_eval(node.slice)]
    if isinstance(node, ast.BinOp):
        ops = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.FloorDiv: '//'}
        if type(node.op) in ops:
            return {'op': ops[type(node.op)], 'args': [bound(node.left, constants), bound(node.right, constants)]}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('min', 'max') and not node.keywords:
        return {'op': node.func.id, 'args': [bound(a, constants) for a in node.args]}
    raise SystemExit(f'GEOM_RANGES: a bound this script cannot carry over: {ast.unparse(node)}')


def worked(b, g):
    """bound()'s data for the set g, as official.js works it out."""
    if isinstance(b, int):
        return b
    if 'field' in b:
        return getattr(g, b['field'])
    a = [worked(x, g) for x in b['args']]
    return {'+': lambda: a[0] + a[1], '-': lambda: a[0] - a[1], '*': lambda: a[0] * a[1], '//': lambda: a[0] // a[1],
            'min': lambda: min(a), 'max': lambda: max(a)}[b['op']]()


def geometry_ranges(theme, ipod, source, sets):
    """GEOM_RANGES, in Geometry's field order, each end an int or bound()'s data, checked against the tool's own on sets."""
    table = next(n.value for n in ast.parse(source).body
                 if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'GEOM_RANGES' for t in n.targets))
    if not isinstance(table, ast.Dict):
        raise SystemExit('GEOM_RANGES is not a dict literal')
    ends = {ast.literal_eval(k): v.elts for k, v in zip(table.keys, table.values) if k is not None and isinstance(v, ast.Tuple)}
    fields = [f.name for f in dataclasses.fields(ipod.Geometry)[1:]]
    if set(fields) != set(theme.GEOM_RANGES) or set(fields) != set(ends):
        raise SystemExit('GEOM_RANGES does not cover the Geometry fields')
    out = []
    for name in fields:
        lo, hi = (bound(e, theme.O) for e in ends[name])
        for g in sets:
            want = [b(g) if callable(b) else b for b in theme.GEOM_RANGES[name]]
            if [worked(lo, g), worked(hi, g)] != want:
                raise SystemExit(f'GEOM_RANGES.{name}: carried over wrongly for set {g.name}')
        text = [re.sub(r'\bg\.', '', ast.unparse(e.body if isinstance(e, ast.Lambda) else e)) for e in ends[name]]
        out.append({'name': name, 'lo': lo, 'hi': hi, 'text': text})
    return out


SAMPLES = {'bool': '1', 'color': '#808080', 'stops': '#808080 0, #808080 100', 'alphas': '1', 'rows': '#808080'}


def sample(theme, k):
    """A text the tool takes for key k."""
    if k.type in SAMPLES:
        return SAMPLES[k.type]
    if k.type == 'enum':
        return next(iter(theme.CHOICES[k.path]))
    if k.type in ('easing', 'anim'):
        return (theme.EASINGS if k.type == 'easing' else theme.ANIMS)[0]
    if k.type == 'set':
        return next(iter(theme.GEOMETRIES))
    return str(k.lo)


def place(theme, k):
    """Where key k is written in a theme.xml, and the forms of its attribute the tool takes there: asked of
    the tool with a one-attribute theme."""
    head, _, rest = k.path.partition('.')
    if k.path.startswith('scheme.'):
        where = {'tag': 'colorScheme', 'attr': rest}
    elif theme.view_attr(k.path):
        element, _, attr = rest.partition('.')
        where = {'tag': 'view', 'view': head, 'element': element, 'attr': attr}
    elif head in theme.VIEWS:
        where = {'tag': 'view', 'view': head, 'attr': rest}
    else:
        where = {'tag': head, 'attr': rest}
    text = sample(theme, k).replace('&', '&amp;').replace('"', '&quot;')
    forms = []
    for form, prefix in (('plain', ''), ('light', 'light.'), ('dark', 'dark.')):
        stated = f'{prefix}{where["attr"]}="{text}"'
        if where['tag'] == 'view' and 'element' in where:
            body = f'<view name="{where["view"]}"><element name="{where["element"]}" {stated}/></view>'
        elif where['tag'] == 'view':
            body = f'<view name="{where["view"]}" {stated}/>'
        else:
            body = f'<{where["tag"]} {stated}/>'
        try:
            theme.resolve(theme.parse(f'<theme format="1" id="probe" name="Probe" index="0">{body}</theme>', 'probe/theme.xml'), {})
            forms.append(form)
        except theme.ThemeError:
            pass
    return {**where, 'forms': forms}


def schema(theme):
    out = []
    for k in theme.SCHEMA.values():
        names = (list(theme.CHOICES[k.path]) if k.type == 'enum' else list(theme.EASINGS) if k.type == 'easing'
                 else list(theme.ANIMS) if k.type == 'anim' else None)
        out.append({'path': k.path, 'field': k.field, 'type': k.type, 'lo': k.lo, 'hi': k.hi, 'default': plain(k.default),
                    'final': k.final, 'cls': k.cls, 'choices': names, 'xml': place(theme, k)})
    return out


def drawn(theme, t):
    """What each half draws of t's final values (the tool's half() and scheme_half(), as emit() calls them):
    {field: [dark, light]}, and each scheme's two halves."""
    d = t['schemes'][max(theme.accent_default(t), 0)]
    halves = [theme.half(t, light, d['paper'], d['ink']) for light in (False, True)]
    return {'shared': theme.shared(t),
            'theme': {k.field: [h[k.field] for h in halves] for k in theme.FINAL if not k.path.startswith('scheme.')},
            'schemes': [[theme.scheme_half(s, light) for light in (False, True)] for s in t['schemes']]}


def pretty(value, depth=0, flat=3):
    """JSON with the first levels one entry a line and everything under them on its line."""
    if depth >= flat or not isinstance(value, (dict, list)) or not value:
        return json.dumps(value, ensure_ascii=False)
    pad, end = '\n' + ' ' * (depth + 1), '\n' + ' ' * depth
    if isinstance(value, dict):
        return '{' + ','.join(f'{pad}{json.dumps(k)}: {pretty(v, depth + 1, flat)}' for k, v in value.items()) + end + '}'
    return '[' + ','.join(f'{pad}{pretty(v, depth + 1, flat)}' for v in value) + end + ']'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('checkout', type=pathlib.Path, nargs='?', default=pathlib.Path(__file__).resolve().parents[2], help='a q2-pod checkout (default: this one)')
    ap.add_argument('-o', '--out', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent/'official.json')
    args = ap.parse_args()
    repo = args.checkout.resolve()
    args.out = args.out.resolve()  # before the chdir: a relative -o names a file here, not in the checkout
    os.chdir(repo)  # the tool reads its repository through relative and ROOT paths
    sys.path.insert(0, str(repo/'tools'))
    sys.dont_write_bytecode = True  # the checkout stays as it was
    import ipod
    import theme

    source = pathlib.Path(theme.__file__).read_text()
    root = repo/'assets/themes'
    nodes = {n.attrs.get('id'): (p, n) for p in sorted(root.glob('*/theme.xml')) for n in [theme.load(p)]}
    themes = theme.builtins(root)
    all_sets = list(dict.fromkeys([*theme.GEOMETRIES.values(), *(g for t in themes for g in t['geoms'].values())]))
    tilt = theme.SCHEMA['coverflow.shelf.tilt']
    rows = max(theme.SCHEMA[f'list.scrollbar.{e}'].hi for e in ('top', 'bottom'))
    functions = {n: f for n, f in vars(theme).items() if inspect.isfunction(f) and f.__module__ == theme.__name__}
    data = {
        'about': 'Written by tools/theme-studio/official_data.py from a q2-pod checkout; do not edit, run it again.',
        'source': {'repository': git(repo, 'remote', 'get-url', 'origin'), 'commit': git(repo, 'rev-parse', 'HEAD'),
                   'date': git(repo, 'log', '-1', '--format=%cI'), 'subject': git(repo, 'log', '-1', '--format=%s'),
                   'changed': git(repo, 'status', '--porcelain', '--', 'tools', 'patch', 'assets/themes').splitlines(),
                   'theme_py': hashlib.sha256(source.encode()).hexdigest()},
        'xml': {'token': theme.TOKEN.pattern, 'ws': theme.WS, 'entities': theme.ENTITIES, 'children': plain(theme.CHILDREN),
                'views': sorted(theme.VIEWS), 'elements': sorted(theme.ELEMENTS), 'option_attrs': sorted(theme.OPTION_ATTRS)},
        'mirrored': {n: hashlib.sha256(inspect.getsource(f).encode()).hexdigest()[:16] for n, f in sorted(functions.items())},
        'schema': schema(theme),
        'fonts': {'names': plain(theme.FONTS), 'keys': [p for p, c in theme.CHOICES.items() if c is theme.FONTS]},
        'choices': plain({p: c for p, c in theme.CHOICES.items()}),
        'geometry': {'name': theme.GEOM_NAME.pattern, 'fields': geometry_ranges(theme, ipod, source, all_sets),
                     'sets': plain(theme.GEOMETRIES), 'run_time': list(ipod.GEOM_VALS)},
        'accents': [{'name': n, 'tones': tones} for n, tones in zip(theme.ACCENT_NAMES, theme.ACCENT_TONES)],
        'gloss': {n[6:].lower() or 'stops': plain(v) for n, v in vars(theme).items() if n.startswith('GLOSS')},
        'settings': {n: {'macro': m, 'values': list(v)} for n, (m, v) in theme.SETTINGS.items()},
        'accent_keys': list(theme.ACCENT_KEYS),
        'payload_keys': sorted(theme.PAYLOAD_KEYS),
        'plain_keys': sorted(theme.PLAIN_KEYS),
        'motion': {'window': list(theme.MOTION_WINDOW), 'widget': list(theme.MOTION_WIDGET)},
        'role_macros': {i: [{'field': f, 'path': theme.FIELDS[f].path, 'from': e, 'value': eval(e, {'__builtins__': {}}, theme.O)}
                            for f, e in m.items()] for i, m in theme.ROLE_MACROS.items()},
        # the numbers validate() takes from the firmware's sources
        'constants': {**{n: theme.O[n] for n in dict.fromkeys(re.findall(r"O\['(\w+)'\]", source))}, 'CF_WIDE': theme.CF_WIDE},
        'corner_inset': [ipod.corner_inset(y) for y in range(rows + 1)],
        'trig': {str(a): [math.sin(math.radians(a)), math.cos(math.radians(a))] for a in range(tilt.lo, tilt.hi + 1)},
        'themes': [{'id': t['id'], 'file': nodes[t['id']][1].file, 'text': nodes[t['id']][0].read_text(),
                    'written': tree(nodes[t['id']][1]), 'resolved': plain(t), 'drawn': plain(drawn(theme, t))} for t in themes],
    }
    args.out.write_text(pretty(data) + '\n', encoding='utf-8')
    print(f'{args.out}: {data["source"]["commit"][:10]}, {len(data["schema"])} keys, {len(data["geometry"]["fields"])} geometry fields, '
          f'{len(data["themes"])} themes ({", ".join(t["id"] for t in data["themes"])})')


if __name__ == '__main__':
    main()
