"""The library's name order (patch/name_sort.c): name_less, which the two hooked comparators (0x5cc870, the default
order, and 0x5cd188, the Japanese one) call for every pair their CJK rule leaves to stock, against stock's own bodies
through their trampolines, on the same records, each pair both ways round in both orders: test/fw/test_name_sort.py's
cases (stock's recorded answers checked too where name_less answers), numbers past 2^31 - 1, which the Q2's atoi
saturates, and a few thousand generated names of every kind, half of the pairs alike but for one change. Which pairs
reach stock's body; what a pair costs through the entry."""
import random
from q2emu import *

sys.path.append(str(ROOT/'test/fw'))  # name_sort_cases.py: test/fw/test_name_sort.py's pairs, with stock's answers
from name_sort_cases import CASES, CLASSES, DEFAULT, JAPANESE, F, G, record

NAMES = ('name_cmp_pinyin', 'name_cmp')  # by order: the default one, the Japanese one
ENTRY = [HOOKS['library_' + n][0] for n in NAMES]
STOCK = [int(manifest['patch_symbols'][f'stock_{n}_trampoline'], 16) for n in NAMES]
FAST = payload_syms['name_less']  # name_less(a, b, less, jp): stock's order, jp the order
for at, n in zip(ENTRY, NAMES):  # each entry jumps to its hook; stock's body is reached through the trampoline
    assert struct.unpack_from('<II', demo, fileoff(demo, at)) == (j(payload_syms[f'ringnav_{n}']), 0), n


class NameMachine(SortMachine):
    """SortMachine's libc with glibc's own answers where these names need them: snprintf's %s copies the bytes as they
    are (no pointer as "(null)"), atoi stops at 32 bits; stock's two pinyin calls copy their input, a stand-in, so a
    pair the hook leaves to stock is answered by stock's own body both ways. Records and strings stay where they are,
    rewritten for each pair; entries to stock's bodies and instructions are counted."""
    def __init__(self):
        super().__init__()
        for n in ('snprintf@GLIBC_2.0', 'atoi@GLIBC_2.0', 'utf8_to_pinyin', 'utf8_2_pinyin'): self.handlers[syms[n]] = 'n:' + n
        self.stock_runs = self.insns = 0
        for at in STOCK: self.u.hook_add(UC_HOOK_CODE, lambda *_: setattr(self, 'stock_runs', self.stock_runs + 1), begin=at, end=at)
        self.u.hook_add(UC_HOOK_BLOCK, lambda u, a, size, x: setattr(self, 'insns', self.insns + size // 4))
        self.recs = [self.alloc(0x58) for _ in range(2)]; self.out = self.alloc(4)
        self.strs = [self.alloc(0x1000) for _ in range(4)]  # each record's name and file name

    def hook(self, u, address, size, unused):
        name = self.handlers.get(address, '')
        if not name.startswith('n:'): return super().hook(u, address, size, unused)
        a, b, c, d = [u.reg_read(r) for r in REGS]
        name = name[2:].split('@')[0]
        if name == 'snprintf':
            assert self.raw(c) == b'%s'; s = self.raw(d) if d else b'(null)'
            u.mem_write(a, s[:b - 1] + b'\0'); ret = len(s)
        elif name == 'atoi':
            n = re.match(rb'[ \t\n\v\f\r]*([+-]?[0-9]+)', self.raw(a)); ret = max(-2**31, min(2**31 - 1, int(n[1]))) if n else 0
        else:  # utf8_to_pinyin(text, out) and utf8_2_pinyin(text, out, ...)
            s = self.raw(a); u.mem_write(b, s + b'\0'); ret = len(s)
        self.returns(ret, clobber=True)

    def records(self, *pair):
        """Two records, each (name, file name, type) with None for no string, written over the last pair's."""
        for k, (name, file, kind) in enumerate(pair):
            r = self.recs[k]; self.u.mem_write(r, bytes(0x58)); self.word(r + 0x34, kind)
            for off, s, at in ((8, file, self.strs[2 * k + 1]), (0x10, name, self.strs[2 * k])):
                if s is not None: assert len(s) < 0x1000; self.u.mem_write(at, s + b'\0'); self.word(r + off, at)
        return self.recs

    def less(self, at, x, y, jp=0):
        self.word(self.out, 0x5a5a5a5a)
        self.call(address=at, args=(x, y, self.out, jp), gap=0, count=20_000_000)
        assert self.get(self.out) in (0, 1); return self.get(self.out)

    def both(self, jp, a, b):
        """((stock's answer, name_less's), ...) for a before b and b before a, and the asks stock's body had from
        name_less."""
        x, y = self.records(a, b); out = []; runs = 0
        for p, q in ((x, y), (y, x)):
            want = self.less(STOCK[jp], p, q); n = self.stock_runs
            out.append((want, self.less(FAST, p, q, jp))); runs += self.stock_runs - n
        return out, runs


m = NameMachine()
assert len(CASES) > 60
for label, a, b, default, japanese, handed in CASES:
    for jp in (0, 1):
        got, runs = m.both(jp, record(a, F), record(b, G))
        assert all(w == h for w, h in got), (label, jp, got)
        if 'PJ'[jp] in handed: assert runs == 2, (label, jp, runs)  # a pinyin stand-in answered: stock's own answer isn't checked
        else: assert runs == 0 and ''.join(str(w) for w, _ in got) == (default, japanese)[jp], (label, jp, got)
for jp, matrix in enumerate((DEFAULT, JAPANESE)):  # every pair of first-byte classes
    for i, a in enumerate(CLASSES):
        for k, b in enumerate(CLASSES[i:], i):
            got, runs = m.both(jp, (a, F, 0), (b, G, 0))
            assert all(w == h for w, h in got) and runs == 2 * (matrix[i][k] == '.'), (jp, i, k, got, runs)
            assert matrix[i][k] == '.' or [w for w, _ in got] == [int(matrix[i][k]), int(matrix[k][i])], (jp, i, k, got)
passed()
# numbers past 2^31 - 1: the Q2's atoi saturates, so these are equal numbers, then the text
for a, b in (('Track 9999999999', 'Track 2147483647'), ('Track 2147483648', 'Track 2147483647'), ('Track 99999999999', 'Track 9999999999'),
             ('Vol 4294967296', 'Vol 1'), ('Part 3000000000', 'Part 2999999999'), ('x 00000000009', 'x 9')):
    for jp in (0, 1):
        got, runs = m.both(jp, record(a, F), record(b, G))
        assert runs == 0 and all(w == h for w, h in got), (a, b, jp, got)
passed()
# generated names: words, numbers, punctuation, blanks, every script's first bytes, bytes of any value and names past
# 960 bytes; half of the pairs a name and a variation of it
rnd = random.Random(0x5cc870)
WORDS = ['The', 'the', 'A', 'a', 'An', 'Love', 'Track', 'TRACK', 'Disc', 'Vol.', 'No.', 'Them', 'Anthrax', 'ab', 'AB', 'x', 'X']
NUMS = ['0', '1', '2', '9', '10', '007', '0010', '99', '2147483647', '2147483648', '9999999999', '00000000001', '123456789012']
MB = [s.encode() for s in ('\u00c9', '\u00e9', '\u0410', '\u03c9', '\u0e01', '\u3042', '\u30a2', '\u3001', '\u3000', '\u4e2d', '\u7231',
                          '\u9f99', '\uac00', '\ud55c', '\uff21', '\ufeff', '\ue000', '\U0001f3b5')]
PUNCT = b'!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~\x7f'


def word():
    r = rnd.randrange(10)
    if r < 3: return rnd.choice(WORDS).encode()
    if r == 3: return rnd.choice(NUMS).encode()
    if r == 4: return rnd.choice(MB)
    if r == 5: return bytes([rnd.choice(PUNCT)])
    return bytes((65 if rnd.randrange(4) == 0 else 97) + rnd.randrange(26) for _ in range(rnd.randint(1, 8)))


def name():
    r = rnd.randrange(100)
    if r < 40: return b' '.join(word() for _ in range(rnd.randint(1, 4)))
    if r < 55: return rnd.choice(WORDS).encode() + rnd.choice([b'', b' ']) + rnd.choice(NUMS).encode() + rnd.choice([b'', b' ' + word()])
    if r < 62: return rnd.choice(NUMS).encode() + rnd.choice([b'', b' ', b'. ']) + word()
    if r < 70: return bytes(rnd.choice(b' \t\n\r\v\f') for _ in range(rnd.choice([1, 2, 3, 23, 24, 30]))) + word()
    if r < 73: return bytes(rnd.choice(b' \t') for _ in range(rnd.randrange(3)))
    if r < 85: return b''.join(rnd.choice(MB) for _ in range(rnd.randint(1, 4))) + rnd.choice([b'', word()])
    if r < 94: return bytes(rnd.randint(1, 255) for _ in range(rnd.randint(1, 12)))
    fill = bytes([rnd.choice(b'abc')]) * rnd.choice([950, 958, 959, 960, 961, 1000, 1022, 1023, 1030])
    return rnd.choice([b'', b'The ', b'  ']) + fill + rnd.choice([b'', b'1', b'12', b'x'])


def vary(s):
    k = rnd.randrange(7)
    if k == 0 or not s: return s
    if k == 1: return s.swapcase()
    if k == 2: return s + bytes([rnd.randint(1, 255)])
    if k == 3: return s[:-1]
    if k == 4: i = rnd.randrange(len(s)); return s[:i] + bytes([rnd.randint(1, 255)]) + s[i + 1:]
    if k == 5: return rnd.choice([b' ', b'\t', b'The ']) + s
    return re.sub(rb'[0-9]+', lambda d: rnd.choice(NUMS).encode(), s, count=1)


asked = handed = 0
for n in range(1500):
    a = name(); b = vary(a) if n % 2 else name()
    ra = (a if rnd.randrange(40) else None, rnd.choice([F, b'', b'  x.mp3', name()]) if rnd.randrange(40) else None, rnd.choice([0, 0, 0, 1, 4, 8]))
    rb = (b if rnd.randrange(40) else None, rnd.choice([G, b'', name()]) if rnd.randrange(40) else None, rnd.choice([0, 0, 0, 1, 4, 8]))
    for jp in (0, 1):
        got, runs = m.both(jp, ra, rb)
        assert all(w == h for w, h in got), (ra, rb, jp, got)
        asked += 2; handed += runs
assert 0.02 < handed / asked < 0.5, (handed, asked)  # most pairs answered by the hook, some by stock's body
passed()
# A pair of 40-byte titles alike but for their last byte: the cost line is the entry's, the CJK rule's look and
# name_less's, what a sort pays for the pair
x, y = m.records(record('Midnight City (Extended Mix) Live 2019 A', F), record('Midnight City (Extended Mix) Live 2019 B', G))
n = m.insns; m.less(ENTRY[0], x, y); n = m.insns - n
cost_line('name order pair 40 bytes', n); passed()
