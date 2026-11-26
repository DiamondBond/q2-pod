"""name_sort.c: the library's name comparators put CJK-leading names after A-Z, by code point, and answer every other
pair in stock's order (name_less). name_sort_cases.py's pairs were asked of stock's own body on the Q2's libc, and
their answers are the ones name_less must give, both ways round in both orders. A pair stock decides with its pinyin or kana
tables, a record with no name to compare, more than 23 leading blanks, or names alike for their first 960 bytes go to
stock's body itself, with name_less's own arguments, and its answer is name_less's. test/patch.py's
scenarios/name_sort.py runs name_less against stock's body with a stock build."""
import ctypes as C

import pytest

from conftest import Config, block, ui_name
from name_sort_cases import CASES, CLASSES, DEFAULT, JAPANESE, F, G, record
from test_nav_hold import recs  # noqa: F401 (fixture)
from test_language import COPY, chinese, lang, lines  # noqa: F401 (fixture)


@pytest.mark.parametrize('a, b, want', [
    ('Zebra', '你好', 1), ('你好', 'Zebra', 0), ('あ', 'ア', 1),
    ('ア', '世界', 1), ('世界', '가', 1), ('가', '𠮷', 1), ('𠮷', '가', 0),
    ('你好', '你好', 0), ('你好', '你好呀', 1), ('你好a', '你好A', 0),
    ('The 你好', '你好', 0), ('  さくら', 'ア', 1), ('\t\r\n さくら', 'ア', 1), ('A', 'An', -1),
    ('Été', 'Zebra', -1), ('Ánh', '世界', 1), ('A你好', 'Zebra', -1),
    ('ㄱ', '가', 1), ('ｱ', '𠮷', 1), ('', '你好', 1),
    (None, '你好', 1), ('Zebra', None, -1),
    ('\x01你好', 'Zebra', -1), ('\x1f 你好', '世界', 1),
    (b'\xe4\x00', '你好', 1), (b'\xed\xa0\x80', 'Zebra', -1),
    (b'\xf4\x90\x80\x80', 'Zebra', -1), (b'\xe0\x80\x80', 'Zebra', -1),
])
def test_cjk_title_sort(fw, a, b, want):
    encode = lambda s: s.encode() if isinstance(s, str) else s
    less = fw.fn(ui_name(fw.lib, 'sort_cjk_less'), C.c_int, C.c_char_p, C.c_char_p)
    assert less(encode(a), encode(b)) == want


@pytest.mark.parametrize('suffix', ['', '_pinyin'])
def test_cjk_library_comparator_preserves_stock_and_uses_title(fw, recs, suffix):
    cmp = fw.fn('ringnav_name_cmp' + suffix, None, C.c_void_p, C.c_void_p, C.POINTER(C.c_uint))
    stock = 'stock_name_cmp' + suffix + '_trampoline'
    def original(a, b, out, *_):
        C.c_uint.from_address(out).value = 1
        return 0
    fw.mock(stock, original)
    a = recs(title='Zebra', name='你好.flac')
    b = recs(title='世界', name='A.flac')
    c = recs(name='你好.flac')
    d = recs(title='Apple')
    for x, y, want in [(a, b, 1), (b, a, 0), (b, c, 1), (c, c, 0), (d, a, 1)]:
        out = C.c_uint(0xffffffff)
        cmp(x, y, C.byref(out))
        assert out.value == want
    assert not fw.calls(stock)  # Apple against Zebra: stock's order, from name_less


@pytest.mark.parametrize('suffix', ['', '_pinyin'])
def test_a_title_of_spaces_sorts_by_the_file_name_as_stock_does(fw, recs, suffix):
    cmp = fw.fn('ringnav_name_cmp' + suffix, None, C.c_void_p, C.c_void_p, C.POINTER(C.c_uint))
    stock = 'stock_name_cmp' + suffix + '_trampoline'
    fw.mock(stock, lambda a, b, out, *_: C.c_uint.from_address(out).__setattr__('value', 1))
    blank = recs(title=' \t\r\n ', name='你好.flac')
    latin = recs(title='Apple')
    out = C.c_uint(0xffffffff)
    cmp(latin, blank, C.byref(out))
    assert out.value == 1 and not fw.calls(stock)
    cmp(blank, latin, C.byref(out))
    assert out.value == 0 and not fw.calls(stock)


@pytest.mark.parametrize('suffix', ['', '_pinyin'])
def test_a_control_byte_is_not_trimmed_so_the_name_is_not_cjk(fw, recs, suffix):
    cmp = fw.fn('ringnav_name_cmp' + suffix, None, C.c_void_p, C.c_void_p, C.POINTER(C.c_uint))
    stock = 'stock_name_cmp' + suffix + '_trampoline'
    fw.mock(stock, lambda a, b, out, *_: C.c_uint.from_address(out).__setattr__('value', 1))
    out = C.c_uint(0xffffffff)
    cmp(recs(title='\x01你好'), recs(title='世界'), C.byref(out))
    assert out.value == 1 and not fw.calls(stock)  # not CJK, so before 世界; as CJK it would come after


@pytest.mark.parametrize('suffix', ['', '_pinyin'])
@pytest.mark.parametrize('pack', ['none', 'de', 'zh'])
def test_only_a_chinese_language_pack_keeps_stock_order(fw, recs, lang, suffix, pack):
    if pack == 'zh':
        chinese(fw, lang)
    if pack == 'de':
        lang.files[COPY] = lines(('OK', 'OK', 'Gut'))
        Config(fw, LANG='de')
    if pack != 'none':
        lang.tr('OK')
    cmp = fw.fn('ringnav_name_cmp' + suffix, None, C.c_void_p, C.c_void_p, C.POINTER(C.c_uint))
    stock = 'stock_name_cmp' + suffix + '_trampoline'
    fw.mock(stock, lambda a, b, out, *_: C.c_uint.from_address(out).__setattr__('value', 1))
    out = C.c_uint(0xffffffff)
    cmp(recs(title='你好'), recs(title='世界'), C.byref(out))  # two Han names, stock's pinyin with the pack
    assert (out.value, len(fw.calls(stock))) == ((1, 1) if pack == 'zh' else (0, 0))


STOCK = 0x5a  # what the stand-ins for stock's two bodies answer


class Names:
    """Records as stock's lists hold them (stSongInfo: the file name at +0x08, the name at +0x10, the type at +0x34),
    each string a heap block of its own exact size, stand-ins for stock's two bodies that note each call, and
    name_less(a, b, less, jp) itself, jp 0 for the default order (0x5cc870's), 1 for the Japanese one (0x5cd188's).
    name_less reads strcasecmp's lower-case table, the host libc's here (host.py's PURE), as strcasecmp is."""
    def __init__(self, fw):
        self.fw, self.calls, self.out = fw, [], C.c_int()
        for jp, name in enumerate(('stock_name_cmp_pinyin_trampoline', 'stock_name_cmp_trampoline')):
            fw.mock(name, lambda a, b, less, *_, jp=jp: self.stock(jp, a, b, less))
        self.less = fw.fn(ui_name(fw.lib, 'name_less'), None, C.c_void_p, C.c_void_p, C.c_void_p, C.c_int)

    def stock(self, jp, a, b, less):
        self.calls.append((jp, a, b, less))
        C.c_int.from_address(less).value = STOCK

    def record(self, r, file):
        name, file, kind = record(r, file)
        p = block(self.fw, size=0x58)
        for off, s in ((0x08, file), (0x10, name)):
            if s is not None:
                C.c_void_p.from_address(p + off).value = block(self.fw, s)
        C.c_uint.from_address(p + 0x34).value = kind
        return p

    def ask(self, jp, a, b):
        """name_less's answer for a against b, and the calls it made to stock's bodies."""
        self.calls, self.out.value = [], -1
        self.less(a, b, C.addressof(self.out), jp)
        return self.out.value, self.calls


@pytest.mark.parametrize('jp', (0, 1), ids=('default order', 'Japanese order'))
@pytest.mark.parametrize('label, a, b, default, japanese, handed', CASES, ids=[c[0] for c in CASES])
def test_answers_as_stock(fw, jp, label, a, b, default, japanese, handed):
    """Both ways round: stock's answer, from the records' own strings, with no call to stock's body; or, for a pair
    name_less leaves to stock, stock's body's answer, asked once with name_less's own arguments."""
    n = Names(fw)
    ra, rb = n.record(a, F), n.record(b, G)
    for (x, y), want in zip(((ra, rb), (rb, ra)), (default, japanese)[jp]):
        got, calls = n.ask(jp, x, y)
        if 'PJ'[jp] in handed:
            assert (got, calls) == (STOCK, [(jp, x, y, C.addressof(n.out))]), (label, x == ra)
        else:
            assert (got, calls) == (int(want), []), (label, x == ra)


@pytest.mark.parametrize('jp', (0, 1), ids=('default order', 'Japanese order'))
def test_each_first_byte_class(fw, jp):
    """A name for each range of first bytes, every pair of them both ways: stock's answers, or stock's body for the
    pairs its tables decide."""
    n = Names(fw)
    rows = [n.record(name, F) for name in CLASSES]
    for i, x in enumerate(rows):
        for k, y in enumerate(rows):
            want = (DEFAULT, JAPANESE)[jp][i][k]
            got, calls = n.ask(jp, x, y)
            assert (got, calls) == ((STOCK, [(jp, x, y, C.addressof(n.out))]) if want == '.' else (int(want), [])), (i, k)


@pytest.mark.parametrize('name, handed', [('Love Song', ''), ('Track 10', ''), ('', ''), ('Émile', ''),
                                          ('中文', 'PJ'), ('あい', 'J'), ('x' * 1000, 'PJ')])
def test_a_record_against_itself(fw, name, handed):
    """One record in both places, as a sort can ask: not before itself, from name_less; stock's body answers for the
    names it decides, and for names alike past 960 bytes."""
    n = Names(fw)
    r = n.record(name, F)
    for jp in (0, 1):
        got, calls = n.ask(jp, r, r)
        assert (got, calls) == ((STOCK, [(jp, r, r, C.addressof(n.out))]) if 'PJ'[jp] in handed else (0, [])), (name, jp)
