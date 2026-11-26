"""Library -> Albums keeps its list across its page's returns (library_lists.c albums_again, albums_made): stock's album
page loads the list again each time it comes back on top, and while songtable is unchanged the list on show, or the one
an album's songs set aside, is the list that load would make. On test_e2e_library's model: a real sqlite3 songtable
behind the hooked toolsQueryDbTable, each Albums query counted by kind."""
import ctypes as C

import pytest

from conftest import O, claim
from test_e2e_library import ALBUM, ALBUMS, int_of, music_card, q2, text_of  # noqa: F401 (q2: a fixture)


def card():
    """music_card, and an untagged two-disc album (CD1, CD2), a music album sharing its tags with an audiobook,
    untagged songs (the Unknown row) and a name three albums share."""
    files, tags = music_card()

    def song(path, title, album, artist, track, album_artist=None, disc=0):
        tags[path] = dict(title=title, album=album, artist=artist, track=track, disc=disc, seconds=30,
                          album_artist=artist if album_artist is None else album_artist)
        files[path] = b'\0' * 64
    song('/mnt/mmc/Music/Delta/Live/CD1/01 A.flac', 'A', 'Live', 'Delta', 1, '', 1)
    song('/mnt/mmc/Music/Delta/Live/CD2/01 B.flac', 'B', 'Live', 'Delta', 1, '', 2)
    song('/mnt/mmc/Music/Eps/Live/01 C.flac', 'C', 'Live', 'Eps', 1, '')
    song('/mnt/mmc/Music/Zeta/Live/01 D.flac', 'D', 'Live', 'Zeta', 1)
    song('/mnt/mmc/Music/Story/01 Tale.flac', 'Tale', 'Story', 'Teller', 1)
    song('/mnt/mmc/Audiobooks/Story/01 Tale.mp3', 'Tale', 'Story', 'Teller', 1)
    song('/mnt/mmc/Music/Loose/x1.mp3', 'x1', '', '', 0)
    song('/mnt/mmc/Music/Loose/x2.mp3', 'x2', '', '', 0)
    return files, tags


FIELDS = ('name', 'path', 'title', 'album', 'artist', 'album_artist')  # the host's 8-byte reads: no genre, composer


def rows(q):
    """The list on show, row by row: what the page draws and its presses open."""
    return [(int_of(r, 'id'), int_of(r, 'type'), *(text_of(r, f) for f in FIELDS), int_of(r, 'track'),
             int_of(r, 'disc')) for r in q.rows()]


class Count:
    """The Albums queries q's library runs, by kind. fail names one to answer -1 once: before its rows, or with late
    after them, as a step error stops sqlite3_exec with rows already staged. during sees each query first."""
    KINDS = (('ALBUM_SQL', "ifnull(albumsonger,'') COLLATE NOCASE"), ('getAllAlbum', 'select id,album,songer,fileurl from'),
             ('unknown', "ifnull(album,'')=''"))

    def __init__(self, q):
        self.sql, self.fail, self.late, self.during = [], None, False, None
        run = q.library.query

        def query(sql, row, ctx):
            self.sql.append(sql)
            if self.during:
                self.during(sql)
            if self.fail and self.fail in sql:
                self.fail = None
                if self.late:
                    run(sql, row, ctx)
                return -1
            return run(sql, row, ctx)
        q.library.query = query

    def take(self):
        kinds = dict.fromkeys(('getAllAlbum', 'ALBUM_SQL', 'unknown', 'other'), 0)
        for s in self.sql:
            kinds[next((k for k, mark in self.KINDS if mark in s), 'other')] += 1
        self.sql.clear()
        return kinds


NONE = {'getAllAlbum': 0, 'ALBUM_SQL': 0, 'unknown': 0, 'other': 0}
WHOLE = {'getAllAlbum': 1, 'ALBUM_SQL': 1, 'unknown': 1, 'other': 0}


def load(q):
    """Library -> Albums (load_localclass_list 0xf003), as the album page's init and its foreground handler run it."""
    q.fw.var('fw_ctx_g_class_type', C.c_int).value = ALBUMS
    n = q.fw.fn('ringnav_localclass', C.c_int, C.c_int)(ALBUMS)
    assert n == len(q.rows())
    return rows(q)


def whole(q):
    """What a load reads from the library now: the generation moved, as a writer moves it, so nothing is kept."""
    q.fw.var('library_gen', C.c_uint).value += 2
    return load(q)


def copies(q):
    """The rows the model's deques have copied in so far: each push and assign."""
    return sum(len(q.fw.calls(n)) for n in ('fw__deque_push_back', 'fw_deque_assign', 'fw_deque_init_copy'))


def titled(q):
    """The classes music_nagvation_title has set the page title for, in order."""
    return [a[0] for _, a in q.fw.calls('music_nagvation_title')]


PAGE = 0x7e570000  # the Albums page's window, a stand-in: only its address is used


def page(q, window):
    """album_page as widget_lookup finds it among the window manager's windows: window, or 0 for none open."""
    q.fw.mock('widget_lookup', lambda w, name, deep, *_: window if C.string_at(name) == b'album_page' else 0)


def close_page(q):
    """The Albums page closing (Hold Return's Home closes every page): its EVT_DESTROY handler runs."""
    fn, ctx = q.handlers[(PAGE, O['EVT_DESTROY'])]
    C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p)(fn)(ctx, None)


@pytest.fixture
def lib(q2):
    claim(O['SCAN_THREAD'])
    files, tags = card()
    q = q2(files, tags)
    q.update()
    page(q, PAGE)
    return q, Count(q)


def test_the_first_open_reads_the_library(lib):
    q, count = lib
    first = load(q)
    assert count.take() == WHOLE
    assert first[-1][0] == -1  # untagged music: the Unknown row stays


def test_a_return_with_the_list_still_on_show_reads_nothing(lib):
    q, count = lib
    first = load(q)
    count.take()
    made = copies(q)
    assert load(q) == first  # the hold menu, a toast or Now Playing closed over the page
    assert count.take() == NONE and copies(q) == made and titled(q)[-1] == ALBUMS
    assert whole(q) == first


def test_an_albums_return_from_its_songs_reads_nothing_and_copies_no_row(lib):
    q, count = lib
    first = load(q)
    assert q.open_album('First', 'Alpha') == ['Dawn', 'Noon', 'Dusk']
    count.take()
    made, live = copies(q), len(q.deques.lists)
    assert load(q) == first  # its Return: the list set aside, and the page's title back from the album's
    assert count.take() == NONE and copies(q) == made and titled(q)[-1] == ALBUMS
    assert len(q.deques.lists) == live - 1  # the songs' deque is gone, the Albums list's is the showlist again
    assert q.open_album('Live', 'Delta') == ['A', 'B']  # the two discs, one album: a press of the list given back
    count.take()
    assert load(q) == first and count.take() == NONE
    assert [a[1] for _, a in q.fw.calls('widget_on')].count(O['EVT_DESTROY']) == 1  # one handler a page
    assert whole(q) == first


def test_an_albums_songs_loaded_again_keep_its_list_aside(lib):
    """The album's page back from Now Playing loads its songs again (0xff10): the Albums list waits on."""
    q, count = lib
    first = load(q)
    q.open_album('Second', 'Beta')
    assert q.fw.fn('ringnav_localclass', C.c_int, C.c_int)(ALBUM) == 2
    count.take()
    assert load(q) == first and count.take() == NONE


def test_another_list_loaded_lets_the_list_aside_go(lib):
    q, count = lib
    first = load(q)
    q.open_album('First', 'Alpha')
    live = len(q.deques.lists)
    q.songs()  # Library -> Songs: no Albums page waits for it
    assert len(q.deques.lists) == live - 1
    count.take()
    assert load(q) == first and count.take() == WHOLE


def test_the_albums_page_closing_frees_the_list_aside(lib):
    q, count = lib
    load(q)
    q.open_album('First', 'Alpha')
    live = len(q.deques.lists)
    close_page(q)
    assert len(q.deques.lists) == live - 1  # no Return will want it
    count.take()
    load(q)  # Library -> Albums opened again, the album's songs on show: the library is read
    assert count.take() == WHOLE


def test_with_no_albums_page_open_an_albums_songs_free_its_list(lib):
    """Now Playing's Go to Album with the Albums page closed: nothing comes back to the list, so stock's load frees it."""
    q, count = lib
    load(q)
    page(q, 0)
    shown = q.showlist
    q.open_album('First', 'Alpha')
    assert q.showlist == shown  # the songs took the shared list's deque: nothing set aside
    count.take()
    load(q)
    assert count.take() == WHOLE


def test_a_load_a_library_write_ran_across_is_not_kept(lib):
    q, count = lib
    gen = q.fw.var('library_gen', C.c_uint)
    count.during = lambda sql: 'select id,album,songer,fileurl from' in sql and setattr(gen, 'value', gen.value + 2)
    load(q)
    count.during = None
    count.take()
    load(q)
    assert count.take() == WHOLE


@pytest.mark.parametrize('opened', (False, True), ids=('on show', 'aside'))
def test_a_library_change_reads_the_library_again(lib, opened):
    q, count = lib
    first = load(q)
    if opened:
        q.open_album('Second', 'Beta')
    q.library.tags['/mnt/mmc/Music/Zeta/Live/01 D.flac']['album'] = 'Live!'
    q.update()
    if opened:  # its songs read again (their page back on top): the stale list aside goes then
        live = len(q.deques.lists)
        q.fw.fn('ringnav_localclass', C.c_int, C.c_int)(ALBUM)
        assert len(q.deques.lists) == live - 1
    count.take()
    after = load(q)
    assert count.take() == WHOLE and after != first and after == whole(q)


@pytest.mark.parametrize('fails, late', [("ifnull(albumsonger,'') COLLATE NOCASE", False),
                                         ("ifnull(album,'')=''", False), ('select id,album,songer,fileurl from', True)],
                         ids=('split', 'unknown check', 'stock after its rows'))
def test_a_load_a_failed_query_touched_is_not_kept(lib, fails, late):
    q, count = lib
    count.fail, count.late = fails, late
    load(q)
    count.take()
    good = load(q)
    assert count.take() == WHOLE and good == whole(q) and good[-1][0] == -1


def test_another_list_of_the_same_size_is_not_taken_for_it(lib):
    q, count = lib
    first = load(q)
    show = q.deques[q.showlist]
    show[:] = list(reversed(show))  # another list of as many rows (a page that fills the shared list itself)
    count.take()
    assert load(q) == first and count.take() == WHOLE


def test_another_list_of_the_same_size_set_aside_is_not_taken_for_it(lib):
    """An album's songs check the size only: a list of as many rows goes aside, and the Return hashes it."""
    q, count = lib
    load(q)
    show = q.deques[q.showlist]
    show[:] = list(reversed(show))
    shown = q.showlist
    q.open_album('First', 'Alpha')
    assert q.showlist != shown  # it went aside: the songs have a deque of their own
    count.take()
    after = load(q)
    assert count.take() == WHOLE and after == whole(q)


def test_a_playlists_load_keeps_the_list_aside(lib):
    """A song's Add to Playlist from an album: stock's playlist page loads 0xf00b into p_deque_playlist, not the
    showlist, so the Albums list waits on for its Return."""
    q, count = lib
    first = load(q)
    q.open_album('First', 'Alpha')
    live = len(q.deques.lists)
    q.fw.fn('albums_again', C.c_int, C.c_int)(0xf00b)
    assert len(q.deques.lists) == live  # nothing freed
    count.take()
    assert load(q) == first and count.take() == NONE
    assert len(q.deques.lists) == live - 1  # the songs' deque gone, the Albums list's the showlist again


def test_a_load_during_a_scan_is_not_kept(lib):
    q, count = lib
    saved = C.string_at(O['SCAN_DONE'], 8)
    C.c_int.from_address(O['SCAN_THREAD']).value, C.c_int.from_address(O['SCAN_DONE']).value = 1, 0
    try:
        load(q)
    finally:
        C.memmove(O['SCAN_DONE'], saved, 8)
    count.take()
    load(q)
    assert count.take() == WHOLE


def test_a_list_kept_before_a_scan_is_not_used_while_it_runs(lib):
    """A scan reads the card's folder markers again before its writer moves library_gen: while stock's scan thread runs,
    the generation still the kept list's, an Albums load reads the library and an album's songs set nothing aside."""
    q, count = lib
    first = load(q)
    count.take()
    saved = C.string_at(O['SCAN_DONE'], 8)
    C.c_int.from_address(O['SCAN_THREAD']).value, C.c_int.from_address(O['SCAN_DONE']).value = 1, 0
    try:
        shown = q.showlist
        q.open_album('First', 'Alpha')
        assert q.showlist == shown  # the songs took the shared list's deque: nothing set aside
        count.take()
        assert load(q) == first and count.take() == WHOLE
    finally:
        C.memmove(O['SCAN_DONE'], saved, 8)
