#!/usr/bin/env python3
"""Find every raw stock address the patches use in another Shanling Q2 firmware ZIP.

Each address is looked up by a signature cut from the audited V1.32 binary itself: the
instruction words around the site with relocatable fields (branch and jump targets, lui, GOT and
other base-register offsets) masked, grown until it matches once there. A bss or pointer-only
data address is found through the code that loads it instead (its GOT page load and low half).
Symbol-resolved entries (FUNCTIONS, GLOBALS, CONTEXT_DATA, the hooks) only need their name.

    python3 tools/port.py 'Q2 Firmware V1.32.zip' NEW.zip --out /tmp/port  # table, and rewritten sources in /tmp/port
    python3 tools/port.py 'Q2 Firmware V1.32.zip' --self-check  # V1.32 against itself: every address back
"""
import argparse, collections, io, json, pathlib, re, struct, subprocess, sys, tarfile, tempfile, zipfile
from build import (ROOT, HOOKS, IPOD_HOOKS, IPOD_LEAF, WM_PAINT_LEAF, PRIVATE_FUNCTIONS, FUNCTIONS, GLOBALS, CONTEXT_DATA,
                   SHUFFLE_CALL, SORT_TRIMS, DROP_CACHES, BLUEALSA, AAC_44K1, ZIP_SHA, check, run, segments, sha, symbols)
import compact, peq

# Raw addresses in patch/offsets.inc; every other define there inside the image is a value.
# ponytail: widget/struct field offsets (W_*, REC_*, ...) are not addresses and stay manual.
OFFSETS = ['DEFAULT_LAYOUT_VTABLE', 'STYLE_COLOR_GRADIENT_RET', 'LIST_VIEW_LAYOUT', 'LIST_VIEW_LAYOUT_SLOT',
           'KEY_LOCKOUT', 'BOOT_KEY_GUARD', 'RETURN_RELEASE_LATCH', 'MCL_POOL', 'MCL_LASTPOS', 'MCL_PRELOAD',
           'MCL_TYPE', 'MCL_POS', 'MCL_MODE', 'MCL_FD', 'SORTSELECT_KEYUP', 'SORTSELECT_CLOSE',
           'SCAN_THREAD', 'SCAN_DONE']
NOT_ADDRESSES = {'VOL_PANEL_TRACK'}  # a colour that happens to fall inside the image
# Each source and the binaries whose addresses it holds.
SOURCES = {'tools/build.py': ('demo', 'bluealsa'), 'tools/compact.py': ('demo',), 'tools/peq.py': ('hciplayer',),
           'patch/compact.json': ('demo',), 'patch/offsets.inc': ('demo',), 'patch/trampoline.S': ('demo',)}
BRANCHES = {1, 4, 5, 6, 7, 0x14, 0x15, 0x16, 0x17}
MEMORY = {0x09, *range(0x20, 0x2f), *range(0x30, 0x40)}  # addiu, loads and stores
SIZES = (8, 16, 32, 64, 128)  # 128: SORT_TRIMS, in two name comparators that open alike


def stock_files(zip_path, tmp):
    with zipfile.ZipFile(zip_path) as z:
        name = next(n for n in z.namelist() if n.rsplit('/', 1)[-1] == 'update.tar')
        with tarfile.open(fileobj=io.BytesIO(z.read(name))) as t:
            (tmp/'rootfs').write_bytes(t.extractfile('recovery-update/rootfs.squashfs').read())
    files = {}
    for key, path in (('demo', 'release/bin/demo'), ('hciplayer', 'usr/bin/hciplayer'), ('bluealsa', BLUEALSA)):
        files[key] = tmp/key
        files[key].write_bytes(subprocess.check_output(['unsquashfs', '-cat', str(tmp/'rootfs'), path]))
    return files


class Image:
    def __init__(self, path, raw=False):
        self.data = path.read_bytes()
        self.raw = raw  # bluealsa: file offsets and plain bytes
        self.loads = [] if raw else [(o, v, f, m) for _, (t, o, v, _, f, m, _, _) in segments(self.data) if t == 1]
        self.text = (0, 0)
        if not raw:
            for line in run('readelf', '-SW', path).splitlines():
                s = line.replace('[ ', '[').split()
                if len(s) > 4 and s[1] == '.text': self.text = (int(s[3], 16), int(s[3], 16) + int(s[5], 16))
            pltgot = re.search(r'\(PLTGOT\)\s+0x([0-9a-f]+)', run('readelf', '-d', path))
            self.gp = int(pltgot[1], 16) + 0x7ff0  # MIPS: gp is the GOT start plus 0x7ff0
            self.syms = symbols(path)
        self.counts = {}
        self._refs = None

    def off(self, a):
        if self.raw: return a
        return next((o + a - v for o, v, f, _ in self.loads if v <= a < v + f), None)
    def addr(self, off):
        if self.raw: return off
        return next(v + off - o for o, v, f, _ in self.loads if o <= off < o + f)
    def word(self, a): return struct.unpack_from('<I', self.data, self.off(a))[0]
    def code(self, a): return self.text[0] <= a < self.text[1]
    def pointer(self, w): return any(v <= w < v + m for _, v, _, m in self.loads)

    def mask(self, w, code):
        if not code: return 0 if self.pointer(w) else 0xffffffff
        op, rs = w >> 26, w >> 21 & 31
        if op in (2, 3): return 0xfc000000
        if op in BRANCHES or op == 0x0f or (op == 0x11 and rs == 8) or (op in MEMORY and rs not in (0, 29)):
            return 0xffff0000
        return 0xffffffff

    def window(self, a, before, after):
        """(file offset of the first word, [(word, mask)]) around a, or None off the file."""
        start = (self.off(a) & ~3) - 4 * before
        if start < 0 or start + 4 * (before + after) > len(self.data): return None
        words = struct.unpack_from(f'<{before + after}I', self.data, start)
        code = not self.raw and self.code(a)
        return start, [(w, self.mask(w, code)) for w in words]

    def find(self, words):
        """File offsets where the masked words match, at most three."""
        full = [(i, w) for i, (w, m) in enumerate(words) if m == 0xffffffff]
        if len(full) < 2: return [0, 0, 0]  # too little left to identify anything
        for _, w in full:
            if w not in self.counts: self.counts[w] = self.data.count(struct.pack('<I', w))
        i, w = min(full, key=lambda iw: self.counts[iw[1]])
        needle, out, p = struct.pack('<I', w), [], self.data.find(struct.pack('<I', w))
        while p >= 0 and len(out) < 3:
            base = p - 4 * i
            if p % 4 == 0 and base >= 0 and base + 4 * len(words) <= len(self.data) and all(
                    (x ^ v) & m == 0 for x, (v, m) in zip(struct.unpack_from(f'<{len(words)}I', self.data, base), words)):
                out.append(base)
            p = self.data.find(needle, p + 1)
        return out

    def refs(self):
        """{address reached: [(GOT load address, use address)]}: a GOT page load, then the first
        addiu/load/store based on that register (or the GOT entry itself, use None)."""
        if self._refs is None:
            self._refs = collections.defaultdict(list)
            lo, hi = self.text
            words = struct.unpack_from(f'<{(hi - lo) // 4}I', self.data, self.off(lo))
            got = lambda a: self.word(a) if self.off(a) is not None else None
            for i, w in enumerate(words):
                if w >> 26 != 0x23 or w >> 21 & 31 != 28: continue
                rt, page = w >> 16 & 31, got(self.gp + simm(w))
                if page is None: continue
                self._refs[page].append((lo + 4 * i, None))
                for j, u in enumerate(words[i + 1:i + 17], i + 1):
                    if u >> 26 in MEMORY and u >> 21 & 31 == rt:
                        self._refs[page + simm(u)].append((lo + 4 * i, lo + 4 * j))
                        break
        return self._refs


def simm(w): return (w & 0xffff) - ((w & 0x8000) << 1)


def shapes(old, a):
    for n in SIZES:
        for before, after in ((n // 2, n // 2), (0, n), (n, 0)):
            if after == 0: before, after = n - 1, 1
            w = old.window(a, before, after)
            if w and old.find(w[1]) == [w[0]]: yield w


def by_signature(old, new, a):
    """(new address, status) for the site at a."""
    seen = 0
    for start, words in shapes(old, a):
        hits = new.find(words)
        if len(hits) == 1: return new.addr(hits[0] + (old.off(a) - start)), 'found'
        seen = max(seen, len(hits))
    return None, 'ambiguous' if seen > 1 else 'missing'


def by_reference(old, new, a):
    """A bss or pointer-only data address: through the nearest code reference at or below it."""
    refs = old.refs()
    near = sorted((a - r, r) for r in refs if 0 <= a - r < 256)
    status = 'missing'
    for delta, r in near[:4]:
        for load, use in refs[r][:6]:
            got, how = by_signature(old, new, use or load)
            if not got: status = how if how == 'ambiguous' else status; continue
            if use: got -= use - load
            w = new.word(got)
            if w >> 26 != 0x23 or w >> 21 & 31 != 28: continue
            reached = new.word(new.gp + simm(w)) + (simm(new.word(got + use - load)) if use else 0)
            return reached + delta, f'found via {load:#x}' + (f'+{delta:#x}' if delta else '')
    return None, status


def by_string(old, new, a):
    """Pointer-only data no code loads (an MPlayer descriptor of string and function pointers):
    through a pointer in it to a string found once in both images."""
    start, words = old.window(a, 8, 8)
    for i, (w, _) in enumerate(words):
        o = old.off(w) if old.pointer(w) else None
        s = old.data[o:old.data.find(b'\0', o)] if o else b''
        if not (4 <= len(s) <= 64 and s.isascii() and old.data[o - 1] == 0) or old.data.count(b'\0'+s+b'\0') != 1: continue
        at = new.data.find(b'\0'+s+b'\0')
        if at < 0 or new.data.count(b'\0'+s+b'\0') != 1: continue
        needle, hits, p = struct.pack('<I', new.addr(at + 1)), [], -1
        while (p := new.data.find(needle, p + 1)) >= 0:
            base = p - 4 * i
            if p % 4 == 0 and base >= 0 and all((x ^ v) & m == 0 for x, (v, m) in
                                                zip(struct.unpack_from(f'<{len(words)}I', new.data, base), words)):
                hits.append(base)
        if len(hits) == 1: return new.addr(hits[0] + old.off(a) - start), f'found via "{s.decode()}"'
    return None, 'missing'


def inventory(images):
    """(name, image key, address, pinned stock word or None) for every raw address, from the
    tables build.py, compact.py and peq.py patch from."""
    demo = images['demo']
    items = [(f'PRIVATE_FUNCTIONS {n}', 'demo', a, None) for n, a in PRIVATE_FUNCTIONS.items()]
    for m in re.finditer(r'^resume (\w+), (0x[0-9a-f]+)$', (ROOT/'patch/trampoline.S').read_text(), re.M):
        items.append((f'trampoline.S {m[1]}', 'demo', int(m[2], 16), None))
    items += [('SHUFFLE_CALL', 'demo', SHUFFLE_CALL[0], demo.word(SHUFFLE_CALL[0])),
              ('DROP_CACHES', 'demo', DROP_CACHES[0], DROP_CACHES[1])]
    items += [('SORT_TRIMS', 'demo', a, demo.word(a)) for a in SORT_TRIMS]
    items += [('ARTIST_ALBUMS', 'demo', a, old) for a, old, _ in compact.ARTIST_ALBUMS]
    items += [('event_abi_words', 'demo', int(a, 16), struct.unpack('<I', bytes.fromhex(w))[0])
              for a, w in compact.AUDIT['event_abi_words'].items()]
    # Every word compact.patch_code changes, as recorded in the manifest's compact_code.
    for c in compact.patch_code(bytearray(demo.data), collections.defaultdict(int)):
        items.append((f'compact {c["purpose"][:40]}', 'demo', int(c['address'], 16), int(c['original'], 16)))
    defines = {m[1]: int(m[2], 16) for m in re.finditer(r'^#define (\w+) (0x[0-9a-fA-F]+)', compact.INC, re.M)}
    inside = {n for n, v in defines.items() if demo.off(v) is not None or demo.pointer(v)}
    check(inside - NOT_ADDRESSES == set(OFFSETS), f'offsets.inc addresses not in port.py OFFSETS: {sorted(inside - NOT_ADDRESSES ^ set(OFFSETS))}')
    items += [(f'offsets.inc {n}', 'demo', defines[n], None) for n in OFFSETS]
    items += [('peq VBR_SCAN', 'hciplayer', peq.VBR_SCAN, None), ('peq SEEK_SLOT', 'hciplayer', peq.SEEK_SLOT, None),
              ('peq STOCK_SEEK', 'hciplayer', peq.STOCK_SEEK, None), ('peq EQ_DESC', 'hciplayer', peq.EQ_DESC, None),
              ('peq EQ_OPEN_SLOT', 'hciplayer', peq.EQ_OPEN_SLOT, None)]
    items += [('peq EQ_RATE_GATES', 'hciplayer', a, old) for a, old, _ in peq.EQ_RATE_GATES]
    items.append(('AAC_44K1 (file offset)', 'bluealsa', AAC_44K1, None))
    return items


def port(old_zip, new_zip):
    with tempfile.TemporaryDirectory(prefix='q2-port-') as tmp:
        tmp = pathlib.Path(tmp)
        (tmp/'old').mkdir(); (tmp/'new').mkdir()
        of, nf = stock_files(old_zip, tmp/'old'), stock_files(new_zip, tmp/'new')
        old = {k: Image(p, raw=k == 'bluealsa') for k, p in of.items()}
        new = {k: Image(p, raw=k == 'bluealsa') for k, p in nf.items()}
    rows = [('GOT base (gp)', 'demo', old['demo'].gp, new['demo'].gp, 'derived'),
            ('hciplayer GOT base (gp)', 'hciplayer', old['hciplayer'].gp, new['hciplayer'].gp, 'derived')]
    for name, (a, _) in {**HOOKS, **IPOD_HOOKS, IPOD_LEAF[0]: IPOD_LEAF[1:3], WM_PAINT_LEAF[0]: WM_PAINT_LEAF[1:3]}.items():
        n = new['demo'].syms.get(name)
        rows.append((f'hook {name}', 'demo', a, n, 'symbol' if n else 'missing'))
    lost = [n for n in [*FUNCTIONS, *GLOBALS, *CONTEXT_DATA] if n not in PRIVATE_FUNCTIONS and n not in new['demo'].syms]
    rows.append(('FUNCTIONS/GLOBALS/CONTEXT_DATA', 'demo', 0, None if lost else 0, 'missing: ' + ' '.join(lost) if lost else 'symbol'))
    for name, key, a, pinned in inventory(old):
        o, n = old[key], new[key]
        # bss, or a data pointer: nothing at the site itself to match
        unsigned = o.off(a) is None or (not o.raw and not o.code(a) and o.pointer(o.word(a)))
        got, status = (None, 'missing') if unsigned else by_signature(o, n, a)
        if got is None and not o.raw: got, status = by_reference(o, n, a)
        if got is None and not o.raw and o.off(a) is not None: got, status = by_string(o, n, a)
        if got is not None and pinned is not None and n.word(got) != pinned:
            status += f', word {n.word(got):#010x} (was {pinned:#010x})'
        rows.append((name, key, a, got, status))
    return rows


def rewrite(rows, out):
    """Copies of the sources with each found address substituted, for review with diff."""
    for rel, keys in SOURCES.items():
        moved = {old: new for _, key, old, new, status in rows if key in keys and new not in (None, old) and status != 'derived'}
        text = (ROOT/rel).read_text()
        text = re.sub(r'\b0x([0-9a-fA-F]{5,8})\b', lambda m: f'0x{moved[int(m[1], 16)]:x}' if int(m[1], 16) in moved else m[0], text)
        (out/rel).parent.mkdir(parents=True, exist_ok=True)
        (out/rel).write_text(text)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('stock', type=pathlib.Path, help='the audited V1.32 ZIP')
    ap.add_argument('new', type=pathlib.Path, nargs='?', help='the firmware ZIP to port to')
    ap.add_argument('--out', type=pathlib.Path, help='write the rewritten sources here')
    ap.add_argument('--self-check', action='store_true', help='port V1.32 to itself: every address must come back')
    a = ap.parse_args()
    check(sha(a.stock.read_bytes()) == ZIP_SHA, 'The first ZIP must be the audited V1.32')
    rows = port(a.stock, a.stock if a.self_check else a.new)
    for name, key, old, new, status in rows:
        print(f'{name[:48]:48} {key:9} {old:#9x} {"-" if new is None else f"{new:#x}":>9}  {status}')
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        rewrite(rows, a.out)
    if a.self_check:
        bad = [r for r in rows if r[3] != r[2] or not r[4].startswith(('found', 'symbol', 'derived')) or ', word' in r[4]]
        check(not bad, f'Self-check failed: {bad}')
        print(f'Self-check: all {len(rows)} entries map back to V1.32.')
