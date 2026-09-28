"""AWTK binary UI layout (ui/*.bin) <-> Python tree. Round-trips byte-for-byte."""
import struct
MAGIC = 0x11221212

def _cstr(b, i):
    j = b.index(0, i)
    return b[i:j].decode('utf-8'), j + 1

def _widget(b, i):
    t = b[i:i+32].split(b'\0')[0].decode()
    x, y, w, h = struct.unpack_from('<4i', b, i + 32)
    i += 48
    props = []
    while b[i]:
        k, i = _cstr(b, i)
        v, i = _cstr(b, i)
        props.append([k, v])
    i += 1
    kids = []
    while b[i]:
        k, i = _widget(b, i)
        kids.append(k)
    return dict(type=t, rect=[x, y, w, h], props=props, children=kids), i + 1

def load(data):
    assert struct.unpack_from('<I', data)[0] == MAGIC, 'not an AWTK ui bin'
    root, end = _widget(data, 4)
    assert end == len(data), (end, len(data))
    return root

def _dump(n, out):
    out += n['type'].encode().ljust(32, b'\0') + struct.pack('<4i', *n['rect'])
    for k, v in n['props']:
        out += k.encode() + b'\0' + v.encode() + b'\0'
    out += b'\0'
    for c in n['children']:
        _dump(c, out)
    out += b'\0'

def dump(root):
    out = bytearray(struct.pack('<I', MAGIC))
    _dump(root, out)
    return bytes(out)

def show(n, depth=0):
    p = dict(n['props'])
    extra = ' '.join(f'{k}={v}' for k, v in n['props'] if not k.startswith('style:'))
    print('  ' * depth + f"{n['type']} {extra}")
    for c in n['children']:
        show(c, depth + 1)
