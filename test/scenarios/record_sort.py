"""The name sorts' moves (patch/record_sort.c, tools/build.py RECORD_SORTS): stock's three name-sorting calls of
libcstl's algo_sort_if go to ringnav_record_sort, libcstl 2.2.0's sort with each row moved by its 88 bytes. Here the MIPS
build runs it over rows in emulated memory with stock's own album order (0x5063f0: disc, then track) on
test/fw/record_sort_cases.py's ALBUM_ORDER lists, which stock's algo_sort_if sorted on the Q2's libcstl: the same number
of questions, the same order, every row's bytes its own, one list down to the depth limit's heap sort. A list of another
element type, part of a deque or no comparator goes to stock's algo_sort_if as it came, word for word, before a row
moves. The three calls are named here, and stock's seven other algo_sort_if calls stay stock's."""
from q2emu import *

sys.path.append(str(ROOT/'test/fw'))  # record_sort_cases.py: stock's answers, recorded by its own libcstl
from record_sort_cases import ALBUM_ORDER
from build import RECORD_SORTS

SORT = payload_syms['ringnav_record_sort']
ALBUM_LESS = 0x5063f0  # getMusicByAlbum's comparator: two loads each, one store of the answer, no call
# toolsQueryDbTable's, toolsQueryDbTableAndSort's and toolsQueryContentDbTable's calls, named here, not read back
NAME_SORTS = (0x5dae90, 0x5db0c8, 0x5db494)
# stock's other algo_sort_if calls (toolsLoadDirectory, getAllOftenRecord, getMusicByAlbum and its kin): stock's jalr
OTHER_SORTS = (0x5d5560, 0x509de4, 0x50a494, 0x50a6e8, 0x50a9b4, 0x50ac80, 0x50af4c)
assert tuple(RECORD_SORTS) == NAME_SORTS, RECORD_SORTS
for at in NAME_SORTS:  # the algo_sort_if import's load, then the payload's call where stock's jalr was
    assert struct.unpack_from('<II', demo, fileoff(demo, at - 4)) == (0x8f99fa34, jal(SORT)), hex(at)
for at in OTHER_SORTS:
    assert struct.unpack_from('<I', demo, fileoff(demo, at))[0] == 0x0320f809, hex(at)  # jalr t9
assert any(c['depth_limit'] for c in ALBUM_ORDER)


def fnv(words):
    h = 2166136261
    for w in words:
        for b in (w & 0xffffffff).to_bytes(4, 'little'): h = ((h ^ b) * 16777619) & 0xffffffff
    return h


class RowsMachine(Machine):
    """libcstl's deque as record_sort.c reads one: rows in emulated memory that deque_at answers, the element type's
    record at DEQUE_TYPE (0x100), the iterators deque_begin and deque_end write; algo_sort_if recorded, not run.
    Row i holds its serial i at +0, its track at +0x3c, its disc at +0x40 and bytes of its own elsewhere."""
    def __init__(self, tracks, discs, size=0x58, name=b'stSongInfo'):
        super().__init__()
        for n in ('deque_size', 'deque_at', 'deque_begin', 'deque_end', 'algo_sort_if'): self.handlers[syms[n]] = 'r:' + n
        self.asked = 0; self.stock = []
        self.u.hook_add(UC_HOOK_CODE, lambda *_: setattr(self, 'asked', self.asked + 1), begin=ALBUM_LESS, end=ALBUM_LESS)
        self.type = self.alloc(0x110); self.word(self.type, size); self.u.mem_write(self.type + 4, name + b'\0')
        self.deque = self.alloc(0x140); self.word(self.deque + 0x100, self.type)
        self.rows = [self.alloc(0x58) for _ in tracks]; self.past = self.alloc(0x58)
        for i, (track, disc) in enumerate(zip(tracks, discs)):
            self.u.mem_write(self.rows[i], bytes((i * 7 + k * 13) & 255 for k in range(0x58)))
            self.word(self.rows[i], i); self.word(self.rows[i] + 0x3c, track); self.word(self.rows[i] + 0x40, disc)
        self.before = {i: bytes(self.u.mem_read(r, 0x58)) for i, r in enumerate(self.rows)}
        # every word of an iterator its own, so a word handed on in another's place shows
        self.begin = self.it(self.rows[0] if self.rows else self.past, 0x5000, 0x11)
        self.end = self.it(self.past, 0x5004, 0x22)

    def it(self, row, slot, tag=0x33): return [row, 0x1000 + tag, 0x2000 + tag, slot, self.deque, 0x5000 + tag, 0x6000 + tag]

    def hook(self, u, address, size, unused):
        name = self.handlers.get(address, '')
        if not name.startswith('r:'): return super().hook(u, address, size, unused)
        assert u.reg_read(UC_MIPS_REG_T9) == address, name
        a, b = u.reg_read(REGS[0]), u.reg_read(REGS[1]); ret = 0
        if name == 'r:deque_size': ret = len(self.rows)
        elif name == 'r:deque_at': assert a == self.deque and b < len(self.rows), (a, b); ret = self.rows[b]
        elif name in ('r:deque_begin', 'r:deque_end'):
            for k, w in enumerate(self.begin if name == 'r:deque_begin' else self.end): self.word(a + 4 * k, w)
        else:  # o32: the first iterator's first four words in a0-a3, the rest of the call at sp+16 onwards
            sp = u.reg_read(UC_MIPS_REG_SP)
            self.stock.append([a, b, u.reg_read(REGS[2]), u.reg_read(REGS[3])] + [self.get(sp + 16 + 4 * k) for k in range(11)])
        self.returns(ret, clobber=True)

    def sort(self, first=None, last=None, less=ALBUM_LESS):
        first, last = first or self.begin, last or self.end
        self.call(address=SORT, args=first[:4], stack=(*first[4:], *last, less), gap=0, count=400_000_000)

    def serials(self): return [self.get(r) for r in self.rows]

    def whole(self):
        assert sorted(self.serials()) == list(range(len(self.rows)))
        assert all(bytes(self.u.mem_read(r, 0x58)) == self.before[self.get(r)] for r in self.rows)


for case in ALBUM_ORDER:  # stock's questions and order, every row whole, nothing handed to stock's sort
    m = RowsMachine(case['keys'], case['discs'])
    m.sort()
    assert m.asked == case['count'] and fnv(m.serials()) == case['order'] and not m.stock, (case['n'], m.asked)
    m.whole()
passed()
# another element type, part of a deque, or no comparator: stock's algo_sort_if gets the call as it came, word for word,
# with no row read or moved
for kind in ('size', 'name', 'first', 'last', 'no comparator'):
    m = RowsMachine([3, 1, 2, 0], [0] * 4, size=0x50 if kind == 'size' else 0x58, name=b'stLyricInfo' if kind == 'name' else b'stSongInfo')
    first = m.it(m.rows[1], 0x5000) if kind == 'first' else m.begin
    last = m.it(m.rows[3], 0x5000) if kind == 'last' else m.end
    less = 0 if kind == 'no comparator' else ALBUM_LESS
    m.sort(first, last, less)
    assert m.stock == [[*first, *last, less]] and not m.asked and m.serials() == [0, 1, 2, 3], (kind, m.stock)
passed()
