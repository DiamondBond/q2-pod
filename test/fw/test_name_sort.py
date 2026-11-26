"""name_sort.c: the library's name comparators put CJK-leading names after A-Z, by code point."""
import ctypes as C

import pytest

from conftest import Config, ui_name
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
    assert len(fw.calls(stock)) == 1


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
    cmp(recs(title='\x01你好'), recs(title='Zebra'), C.byref(out))
    assert out.value == 1 and len(fw.calls(stock)) == 1


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
    cmp(recs(title='你好'), recs(title='Zebra'), C.byref(out))
    assert (out.value, len(fw.calls(stock))) == ((1, 1) if pack == 'zh' else (0, 0))
