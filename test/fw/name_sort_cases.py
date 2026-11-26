"""Pairs of records for the library's name order (patch/name_sort.c), with stock's own answers: each pair was asked of
stock's two name comparators on the Q2's libc. test/fw/test_name_sort.py asks the hook for them; test/patch.py's
scenarios/name_sort.py asks the hook and stock's own body.

Each case: what the pair shows, record a, record b, stock's answers in the default order and the Japanese one (each
"a before b" then "b before a", 1 for yes), and the orders in which the hook hands the pair to stock's body (for such a
pair the recorded answers in that order are kept for reference and not asserted). A record is a name, with file name F
(a) or G (b), or (name, file name, record type), None for no string. Numbers past 2^31 - 1 are scenarios/name_sort.py's
own: the Q2's 32-bit atoi saturates there, a 64-bit host's does not."""
F, G = b'a.flac', b'b.flac'

CASES = [
    # numbers: the same text up to a number in each, then by the numbers, ten digits at most
    ('2 before 10', 'Track 2', 'Track 10', '10', '10', ''),
    ('leading zeros: equal numbers, then the text', 'Track 007', 'Track 7', '10', '10', ''),
    ('ten digits read', 'Track 1234567890', 'Track 12345678901', '10', '10', ''),
    ('a tenth digit counts', 'x 1000000000', 'x 999999999', '01', '01', ''),
    ('only the first number', 'Disc 1 Track 10', 'Disc 1 Track 9', '10', '10', ''),
    ('equal numbers, then the letters', 'Track 2b', 'Track 2a', '01', '01', ''),
    ('numbers at different places', 'x10', 'x 9', '01', '01', ''),
    ('a digit against a letter', 'Part 1', 'Part One', '10', '10', ''),
    ('numbers at the start: no number rule', '2 Unlimited', '10cc', '01', '00', ''),
    ('the same number at the start', '10 Years', '10 years', '00', '00', ''),
    ('the largest int', 'Track 2147483647', 'Track 2147483646', '01', '01', ''),
    ('zero', 'Track 0', 'Track 00', '10', '10', ''),
    # stock's order is not transitive: a prefix that differs in case only switches the number rule off
    ('cycle: by the numbers', 'ab9', 'ab10', '10', '10', ''),
    ('cycle: by strcasecmp', 'ab10', 'AB5', '10', '10', ''),
    ('cycle: by strcasecmp again', 'AB5', 'ab9', '10', '10', ''),
    # letters and case
    ('case only', 'abba', 'ABBA', '00', '00', ''),
    ('case and letters', 'Abc', 'abd', '10', '10', ''),
    ('letters', 'Zebra', 'apple', '01', '01', ''),
    ('a prefix', 'Love', 'Love Song', '10', '10', ''),
    # blanks, articles and the file name
    ('blanks and an article', '  The Cure', 'Cure', '00', '00', ''),
    ('a tab', '\tCure', 'Cure', '00', '00', ''),
    ('return and line feed', '\r\nCure', 'Cure', '00', '00', ''),
    ('a vertical tab stays', '\vCure', 'Cure', '01', '01', ''),
    ('an article dropped', 'The Beatles', 'Beatles, The', '10', '10', ''),
    ('a bare article stays', 'The', 'Thee', '10', '10', ''),
    ('A', 'A Tribe', 'Tribe', '00', '00', ''),
    ('An', 'An Orchestra', 'Orchestra', '00', '00', ''),
    ('Them is a name', 'Them', 'Them Crooked', '10', '10', ''),
    ('two blanks after The', 'The  Cure', 'Cure', '01', '01', ''),
    ('an article in any case', 'tHe cure', 'Cure', '00', '00', ''),
    ('an article, then numbers at the start', 'The 2', 'The 10', '01', '00', ''),
    ('an empty name: the file name', ('', 'b.flac', 0), 'a', '01', '01', ''),
    ('a blank name: the file name', ('   ', 'Zed.mp3', 0), 'Alpha', '01', '01', ''),
    ('an empty name and file name', ('', '', 0), 'x', '01', '01', ''),
    ('the file name untrimmed', ('', ' a.flac', 0), 'b', '01', '01', ''),
    ('the file name keeps its article', ('', 'The b.flac', 0), 'b', '01', '01', ''),
    # first bytes: each order's classes
    ('below 0 against a letter', '(What)', 'What', '01', '01', ''),
    ('[ to ` against { to ~', '[Intro]', '{Intro}', '01', '01', ''),
    ('two below 0', '!Bang', '#Hash', '10', '10', ''),
    (': to @', ':Colon', '@At', '10', '10', ''),
    ('a digit against a letter first', '99 Luftballons', 'Luftballons', '10', '01', ''),
    ('a digit against below 0', '99', '(99)', '10', '10', ''),
    ('accented against a letter', '\u00c9mile', 'Zoe', '01', '01', ''),
    ('accented against a digit', '\u00c9mile', '1984', '01', '10', ''),
    ('two accented', '\u00c9mile', '\u00c9a', '01', '01', ''),
    ('0x7f against ~', b'\x7f', '~', '10', '10', ''),
    ('0xff bytes', b'\xff\xfe', b'\xff\xfd', '01', '01', ''),
    ('0x80 bytes', b'\x80abc', b'\x80abd', '10', '10', ''),
    ('a control byte against a trimmed blank', b'\x01x', ' x', '01', '01', ''),
    ('Thai against below 0', '\u0e01', '!', '10', '01', ''),
    ('Korean against Thai', '\uac00', '\u0e01', '10', '10', ''),
    ('0xed against Korean', '\ud55c', '\uac00', '10', '10', ''),
    # kana and Chinese
    ('kana against a letter', '\u3042', 'Z', '01', '01', ''),
    ('two kana', '\u3042', '\u3044', '10', '10', 'J'),
    ('kana, then numbers', '\u30421', '\u304210', '10', '10', 'J'),
    ('the same kana', '\u3042\u3044', '\u3042\u3044', '00', '11', 'J'),
    ('two Chinese', '\u4e2d', '\u4eba', '01', '01', 'PJ'),
    ('Chinese, then numbers', '\u7b2c1\u7ae0', '\u7b2c10\u7ae0', '10', '10', 'PJ'),
    ('Chinese against a letter', '\u4e2d', 'Z', '01', '01', 'P'),
    ('Chinese against a digit', '\u4e2d', '9', '01', '10', ''),
    ('kana against Chinese', '\u3042', '\u4e2d', '01', '10', ''),
    ('an ideographic space (0xe3) against a letter', '\u3000Space', 'a', '01', '01', ''),
    ('blanks, then Chinese', '  \u4e2d', '\u4e2d\u6587', '10', '10', 'PJ'),
    ('an article, then Chinese', 'The \u4e2d', '\u4e2d', '00', '00', 'PJ'),
    # record types: 4 before 8, whatever the names
    ('types 4 and 8', ('b', F, 4), ('a', G, 8), '10', '10', ''),
    ('types 4 and 8, no names', (None, None, 4), (None, None, 8), '10', '10', ''),
    ('types 4 and 4: the names', ('b', F, 4), ('a', G, 4), '01', '01', ''),
    ('types 8 and 0: the names', ('b', F, 8), ('a', G, 0), '01', '01', ''),
    ('types 6 and 6: the names', ('b', F, 6), ('a', G, 6), '01', '01', ''),
    ('types -4 and 16: the names', ('b', F, 0xfffffffc), ('a', G, 16), '01', '01', ''),
    ('types past 2^31: the names', ('b', F, 0x7fffffff), ('a', G, 0x7fffffff), '01', '01', ''),
    # missing strings
    ('no name', (None, F, 0), 'a', '01', '01', 'PJ'),
    ('an empty name and no file name', ('', None, 0), 'a', '01', '01', 'PJ'),
    ('no file name, not needed', ('x', None, 0), ('y', None, 0), '10', '10', ''),
    # long names: stock compares copies of 1,023 bytes, the hook the first 960 bytes of each
    ('a difference at byte 959', 'a' * 959 + 'b', 'a' * 959 + 'c', '10', '10', ''),
    ('a difference at byte 960', 'a' * 960 + 'b', 'a' * 960 + 'c', '10', '10', 'PJ'),
    ("a difference past stock's copy", 'x' * 1100 + 'a', 'x' * 1100 + 'b', '00', '00', 'PJ'),
    ('24 blanks', ' ' * 24 + 'a', 'a', '00', '00', 'PJ'),
    ('23 blanks', ' ' * 23 + 'a', 'b', '10', '10', ''),
    ('a number at byte 950', 'x' * 950 + '5', 'x' * 950 + '12', '10', '10', ''),
    ('a number at byte 959', 'x' * 959 + '9', 'x' * 959 + '10', '10', '10', ''),
    ('an article and 956 bytes', 'The ' + 'a' * 956 + 'b', 'a' * 956 + 'c', '10', '10', ''),
]

# A name for each range of first bytes the two orders tell apart, and stock's answers for every pair of them: row i,
# column j says whether name i sorts before name j, 1 for yes; '.' is a pair the hook hands to stock's body.
CLASSES = [b'!x', b'1x', b':x', b'Ax', b'[x', b'ax', b'{x', '\u00c9x'.encode(), '\u0e01x'.encode(), '\u1000x'.encode(),
           '\u3042x'.encode(), '\u4e2dx'.encode(), '\uac00x'.encode(), '\ud55cx'.encode()]
DEFAULT = [
    '00000000000000',  # below 0
    '10111111111111',  # digits
    '10000000000000',  # : to @
    '10101011111.11',  # A to Z
    '10100000000000',  # [ to `
    '10101011111.11',  # a to z
    '10101000000000',  # { to ~
    '10101010111011',  # 0x7f to 0xdf
    '10101010000000',  # 0xe0, Thai
    '10101010101011',  # 0xe1 and 0xe2
    '10101010100010',  # 0xe3, kana
    '101.1.11111.11',  # 0xe4 to 0xe9, Chinese
    '10101010100000',  # 0xea to 0xec, Korean
    '10101010101010',  # 0xed to 0xff
]
JAPANESE = [
    '00000000100010',  # below 0
    '10101010100010',  # digits
    '10000000100010',  # : to @
    '11101011111111',  # A to Z
    '10100000100010',  # [ to `
    '11101011111111',  # a to z
    '10101000100010',  # { to ~
    '11101010110011',  # 0x7f to 0xdf
    '00000000000000',  # 0xe0, Thai
    '11101010100011',  # 0xe1 and 0xe2
    '1110101111.111',  # 0xe3, kana
    '11101011110.11',  # 0xe4 to 0xe9, Chinese
    '00000000100000',  # 0xea to 0xec, Korean
    '11101010100010',  # 0xed to 0xff
]


def record(r, file):
    """(name, file name, record type) as bytes, None for no string: a case's record, its file name file if it names
    none."""
    name, file, kind = r if isinstance(r, tuple) else (r, file, 0)
    return tuple(s if s is None or isinstance(s, bytes) else s.encode() for s in (name, file)) + (kind,)
