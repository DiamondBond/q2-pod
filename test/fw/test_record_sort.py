"""record_sort.c: stock's three library-query calls of libcstl's algo_sort_if (tools/build.py RECORD_SORTS) sort with
libcstl 2.2.0's own algorithm, each row moved by its 88 bytes. record_sort_cases.py's lists were sorted by stock's own
algo_sort_if on the Q2's libcstl: this sort must ask the comparator the same questions in the same order, with the answer
word as stock's left it, and leave the rows in stock's order, each row's bytes its own; and hand a list it does not
cover to stock's algo_sort_if before moving a row. test/patch.py runs the MIPS build with stock's album order."""
import ctypes as C

import pytest

from record_sort_cases import CASES

REC = 0x58  # REC_SIZE: an stSongInfo
DEQUE_TYPE = 0x100  # offsets.inc: a libcstl deque's element type record (its size, then its name)


class It(C.Structure):
    _fields_ = [('w', C.c_void_p * 7)]


LESS = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.POINTER(C.c_uint))


def fnv(h, words):
    for w in words:
        for b in (w & 0xffffffff).to_bytes(4, 'little'):
            h = ((h ^ b) * 16777619) & 0xffffffff
    return h


class Rows:
    """A deque as record_sort.c reads one: its element type's record at DEQUE_TYPE, the rows deque_at answers, and the
    iterators deque_begin and deque_end write (the element, then three words, the map slot fourth, the deque fifth).
    Row i holds its serial i at +0, its key at +0x3c and bytes of its own elsewhere."""
    def __init__(self, fw, keys, size=REC, name=b'stSongInfo', discs=None):
        self.n = len(keys)
        self.type = (C.c_ubyte * 264)()
        C.c_int.from_buffer(self.type).value = size
        self.type[4:4 + len(name)] = name
        self.head = (C.c_ubyte * 0x140)()
        C.c_void_p.from_buffer(self.head, DEQUE_TYPE).value = C.addressof(self.type)
        self.buf = (C.c_ubyte * (REC * self.n + REC))()
        for i, k in enumerate(keys):
            row = self.at(i)
            C.memmove(row, bytes((i * 7 + j * 13) & 255 for j in range(REC)), REC)
            C.c_uint32.from_address(row).value = i
            C.c_int32.from_address(row + 0x3c).value = k
            if discs: C.c_int32.from_address(row + 0x40).value = discs[i]
        self.before = {i: self.bytes(i) for i in range(self.n)}
        self.begin, self.end = self.it(0, 0x1000), self.it(self.n, 0x1000 + 8 * (self.n // 16))
        fw.mock('fw_deque_size', lambda d, *_: self.n if d == C.addressof(self.head) else 0)
        fw.mock('fw_deque_at', lambda d, i, *_: self.at(i))
        fw.mock('fw_deque_begin', lambda out, d, *_: C.memmove(out, C.addressof(self.begin), C.sizeof(It)) and 0)
        fw.mock('fw_deque_end', lambda out, d, *_: C.memmove(out, C.addressof(self.end), C.sizeof(It)) and 0)

    def at(self, i): return C.addressof(self.buf) + REC * i
    def it(self, i, slot): return It((self.at(i), 0, 0, slot, C.addressof(self.head), 0, 0))
    def bytes(self, i): return C.string_at(self.at(i), REC)
    def serials(self): return [C.c_uint32.from_address(self.at(i)).value for i in range(self.n)]

    def whole(self):
        """Every row is one row of the list, whole, and each once."""
        serials = self.serials()
        assert sorted(serials) == list(range(self.n))
        assert all(self.bytes(i) == self.before[s] for i, s in enumerate(serials))


def sort(fw, rows, less, first=None, last=None):
    fw.fn('ringnav_record_sort', None, It, It, LESS)(first or rows.begin, last or rows.end, less)


def asker(rows, rule):
    """A comparator by rule (serial, key, serial, key, the word as found) -> the answer or None to leave the word, that
    keeps each question as (serial, serial, word found, word left), every address it is handed that is no row's, and
    for each question which of its two is a row."""
    asked, others, kinds = [], set(), []
    rowset = {rows.at(i) for i in range(rows.n)}

    def less(a, b, out):
        for p in (a, b):
            if p not in rowset: others.add(p)
        kinds.append((a in rowset, b in rowset))
        sa, sb, was = C.c_uint32.from_address(a).value, C.c_uint32.from_address(b).value, out[0]
        got = rule(sa, C.c_int32.from_address(a + 0x3c).value, sb, C.c_int32.from_address(b + 0x3c).value, was)
        if got is not None: out[0] = got
        asked.append((sa, sb, was, out[0]))
    return LESS(less), asked, others, kinds


RULES = {'key': lambda sa, ka, sb, kb, was: int(ka < kb), 'killer': lambda sa, ka, sb, kb, was: int(ka < kb),
         'skip': lambda sa, ka, sb, kb, was: int(ka < kb) if (sa ^ sb) & 3 else None}


@pytest.mark.parametrize('case', CASES, ids=[f"{c['cmp']}-{c['n']}-{c['trace']:08x}" for c in CASES])
def test_the_same_questions_and_order_as_stocks_sort(fw, case):
    rows = Rows(fw, case['keys'])
    less, asked, others, kinds = asker(rows, RULES[case['cmp']])
    sort(fw, rows, less)
    assert len(asked) == case['count']
    assert fnv(2166136261, [w for q in asked for w in q]) == case['trace']
    assert fnv(2166136261, rows.serials()) == case['order']
    rows.whole()
    assert len(others) <= 1  # the row being placed, or the pivot: one spare, as stock's
    # stock's insertion sort asks with its spare first and a row second; nothing asks the spare of itself
    assert (False, False) not in kinds
    if case['n'] <= 200: assert set(kinds) <= {(False, True)}
    assert not fw.calls('fw_algo_sort_if')


def test_the_depth_limit_cases_are_there():
    """The heap sort below the depth limit, the 200-row insertion sort's last size and the introsort's first."""
    assert any(c['depth_limit'] for c in CASES if c['cmp'] == 'killer') and any(c['depth_limit'] for c in CASES if c['cmp'] == 'skip')
    assert {200, 201} <= {c['n'] for c in CASES}


@pytest.mark.parametrize('n', [50, 200, 201, 300])
@pytest.mark.parametrize('how', ['before', 'flip'])
def test_a_comparator_stock_cannot_sort_with_stays_in_the_list(fw, n, how):
    """Every row before every other, itself too, or answers that turn over each time: stock's scans would leave the
    list. Here every question is of the list's rows or its one spare, and each row ends whole, once."""
    rows = Rows(fw, list(range(n)))
    flips = iter(range(10 ** 9))
    rule = {'before': lambda *_: 1, 'flip': lambda *_: next(flips) & 1}[how]
    less, asked, others, kinds = asker(rows, rule)
    sort(fw, rows, less)
    assert asked and len(others) <= 1 and (False, False) not in kinds  # one below row 0 is ~0u, the spare's index
    rows.whole()


@pytest.mark.parametrize('n', [201, 300])
def test_each_partition_starts_with_a_cleared_word(fw, n):
    """libcstl's _algo_intro_sort_if clears its answer word on entry and is called again for the right part (here the
    loop); its median of three has a word of its own and asks rows only. With the pivot before every row and a row
    against the pivot left to the word, stock's backward scan would read the row before row 0, so each partition ends
    on the guard with the word at 1: the next partition's first forward question must still find it cleared."""
    rows = Rows(fw, list(range(n)))
    rowset, found, kinds = {rows.at(i) for i in range(n)}, [], []

    def less(a, b, out):
        kinds.append((a in rowset, b in rowset))
        found.append(out[0])
        if kinds[-1] == (False, True): out[0] = 1
        elif kinds[-1] == (True, True): out[0] = int(C.c_int32.from_address(a + 0x3c).value < C.c_int32.from_address(b + 0x3c).value)
    sort(fw, rows, LESS(less))
    firsts = [found[i] for i in range(1, len(found)) if kinds[i] == (True, False) and kinds[i - 1] == (True, True)]
    assert len(firsts) > 1 and set(firsts) == {0}
    rows.whole()


@pytest.mark.parametrize('n', [0, 1])
def test_no_rows_to_order_ask_nothing(fw, n):
    rows = Rows(fw, list(range(n)))
    less, asked, _, _ = asker(rows, RULES['key'])
    sort(fw, rows, less)
    assert not asked and not fw.calls('fw_algo_sort_if') and not fw.calls('fw_deque_at')


@pytest.mark.parametrize('kind', ['size', 'name', 'first', 'last', 'no comparator', 'no deque', 'no type record', 'first map slot',
                                  'last map slot'])
def test_a_list_it_does_not_cover_is_stocks_before_a_row_moves(fw, kind):
    """Another element type, part of a deque, no comparator or no type record: stock's algo_sort_if gets the call as it
    came (the six words a host stub sees), and no row was read."""
    rows = Rows(fw, [3, 1, 2, 0, 5, 4], size=0x50 if kind == 'size' else REC, name=b'stLyricInfo' if kind == 'name' else b'stSongInfo')
    deque = C.addressof(rows.head)  # every word its own, so a word handed on in another's place shows
    first = {'first': rows.it(1, 0x1000), 'no deque': It((rows.at(0), 0x11, 0x22, 0x1000, 0, 0x55, 0x66)),
             'first map slot': It((rows.at(0), 0x11, 0x22, 0x1008, deque, 0x55, 0x66))}.get(kind)
    last = {'last': rows.it(rows.n - 1, 0x1000), 'last map slot': It((rows.end.w[0], 0, 0, rows.end.w[3] + 8, deque, 0, 0))}.get(kind)
    if kind == 'no type record': C.c_void_p.from_buffer(rows.head, DEQUE_TYPE).value = None
    less, asked, _, _ = asker(rows, RULES['key'])
    sort(fw, rows, LESS() if kind == 'no comparator' else less, first, last)
    (call,) = fw.calls('fw_algo_sort_if')
    head = first or rows.begin
    assert list(call[1]) == [head.w[k] or 0 for k in range(6)]
    assert not asked and not fw.calls('fw_deque_at') and rows.serials() == list(range(rows.n))
