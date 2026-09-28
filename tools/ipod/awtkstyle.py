"""AWTK binary theme (styles/*.bin) <-> Python. Round-trips byte-for-byte when layout is kept."""
import struct
MAGIC = 0xfafbfcfd

def _s(b):
    return b.split(b'\0')[0].decode()

def load(data):
    magic, ver, n = struct.unpack_from('<3I', data)
    assert magic == MAGIC
    entries, pos = [], 12
    for _ in range(n):
        off = struct.unpack_from('<I', data, pos)[0]
        state, name, wtype = (_s(data[pos+4+32*i:pos+36+32*i]) for i in range(3))
        entries.append(dict(offset=off, state=state, style=name, widget=wtype))
        pos += 100
    for e in entries:
        i = e['offset']
        cnt = struct.unpack_from('<I', data, i)[0]; i += 4
        props = []
        for _ in range(cnt):
            t, nl, vl = struct.unpack_from('<BBH', data, i); i += 4
            name = _s(data[i:i+nl]); i += nl
            props.append([name, t, data[i:i+vl]]); i += vl
        e['props'] = props
        e['end'] = i
    return dict(version=ver, entries=entries)

def dump(theme):
    """Rebuild in stock layout: header table, then one unshared block per entry."""
    ents = theme['entries']
    head = bytearray(struct.pack('<3I', MAGIC, theme['version'], len(ents)))
    body = bytearray(); base = 12 + 100 * len(ents); seen = {}
    for e in ents:
        blk = bytearray(struct.pack('<I', len(e['props'])))
        for name, t, raw in e['props']:
            nb = name.encode() + b'\0'
            blk += struct.pack('<BBH', t, len(nb), len(raw)) + nb + raw
        head += struct.pack('<I', base + len(body)); body += blk
        for s in (e['state'], e['style'], e['widget']):
            head += s.encode().ljust(32, b'\0')
    return bytes(head + body)
