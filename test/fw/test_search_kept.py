"""Search keeps a tab's rows while a new query would list the same records (library_lists.c search_made, search_kept
and the ringnav_search_* hooks). On test_e2e_library's model, with a model of stock's dialog handlers around the hooks."""
import contextlib
import ctypes as C

import pytest

from conftest import O, claim
from test_e2e_library import music_card, q2, text_of  # noqa: F401 (q2: a fixture)

SONGS, ALBUMS, ARTISTS, GENRES = 0xff15, 0xff16, 0xff17, 0xff18  # search_load_results' types
VIEWS = {SONGS: 'scroll_view_track', ALBUMS: 'scroll_view_album', ARTISTS: 'scroll_view_artist', GENRES: 'scroll_view_genre'}
HANDLER = (C.c_int, C.c_void_p, C.c_void_p)
ROW = 78  # a result row's pitch, stock's own division at its scroll end


class Search:
    """Stock's Search dialog around the hooks: text, list, a scroll view a tab, the refresh timer, the cover list
    (covers: its list and that list's rows then; asked: covers asked for). fail makes the next query answer -1;
    during runs in each query."""
    def __init__(self, q):
        self.q, self.fw = q, q.fw
        self.list = q.deques.new()
        q.fw.var('fw_ctx_p_deque_searchshowlist', C.c_uint).value = self.list
        self.text = (C.c_char * 256).in_dll(q.fw.lib, 'fw_ctx_g_historical_record')
        self.sql, self.builds, self.marks, self.asked, self.toasts = [], [], [], [], 0
        self.fail, self.during, self.timer, self.covers, self.offset = False, None, False, None, {}
        run = q.library.query

        def query(sql, row, ctx):
            self.sql.append(sql)
            if self.during:
                self.during()
            if self.fail:
                self.fail = False
                return -1
            return run(sql, row, ctx)
        q.library.query = query
        q.fw.mock('stock_search_query_trampoline', self.search_load_results)
        q.fw.mock('stock_search_foreground_trampoline', lambda win, event, *_: self.build(win) or self.timer_start())
        q.fw.mock('stock_search_confirm_trampoline', self.search_run_query)
        q.fw.mock('search_track_highlight_playing', lambda win, *_: self.marks.append(win) or 0)
        q.fw.mock('search_timer_start', lambda *_: self.timer_start())
        q.fw.mock('albumcoverinfo_init', self.cover_init)
        q.fw.mock('get_albumcover_listsize', lambda *_: len(self.covers[1]) if self.covers else 0)
        q.fw.mock('local_songercover_task', lambda first, count, *_: self.asked.append(('songs', first, count)) or 0)
        q.fw.mock('local_albumsmallcover_task', lambda first, count, *_: self.asked.append(('albums', first, count)) or 0)
        q.fw.mock('widget_lookup', lambda w, name, deep, *_: self.views.get((w, C.string_at(name).decode()), 0))
        q.fw.mock('widget_count_children', lambda w, *_: len(q.children.get(w, [])))
        q.fw.mock('widget_get_prop_int', lambda w, name, default, *_: self.offset.get(w, default))
        self.open()

    def open(self):
        self.win = self.q.widget(0, 'window_create')
        self.views = {(self.win, name): self.q.widget(self.win, 'scroll_view_create') for name in VIEWS.values()}
        self.text.value = b''
        self.q.deques[self.list].clear()
        self.tab, self.timer = SONGS, True

    def view(self):
        return self.views[(self.win, VIEWS[self.tab])]

    def timer_start(self):
        self.timer = True
        return 0

    def cover_init(self, lst, *_):
        self.covers = (lst & 0xffffffff, list(self.q.deques[lst]))
        return 0

    def search_load_results(self, kind, *_):
        q, term = self.q, self.text.value.decode().replace("'", "''")
        staging = q.deques[q.directory()]
        staging.clear()
        if kind == SONGS:
            q.query(f"select * from songtable where title like '%{term}%' order by title collate nocase", q.song_row)
        else:
            column = {ALBUMS: 'album', GENRES: 'genre',
                      ARTISTS: 'albumsonger' if q.fw.var('fw_ctx_artist_type', C.c_int).value == 1 else 'songer'}[kind]
            q.query(f"select id,{column},songer,fileurl from songtable where {column} like '%{term}%' "
                    f'group by {column} COLLATE NOCASE', q.album_row)
        q.deques[self.list][:] = staging
        staging.clear()
        return len(q.deques[self.list])

    def build(self, win):
        """The tab's builder: rows destroyed, the query, the cover list and first covers (Songs, Albums), a row a
        record, then the playing row's mark on Songs."""
        view = self.view()
        self.q.children.pop(view, None)
        self.offset.pop(view, None)
        n = self.fw.fn('ringnav_search_query', C.c_int, C.c_int)(self.tab)
        covered = self.tab in (SONGS, ALBUMS)
        if covered:
            self.cover_init(self.list)
        for _ in range(n):
            self.q.widget(view, 'list_item_create')
        if n and covered:
            self.asked.append(('songs' if self.tab == SONGS else 'albums', 0, 9))
        self.builds.append(self.tab)
        if self.tab == SONGS:
            self.marks.append(win)
        return 0

    def search_run_query(self, ctx, *_):
        """No text is a toast; else the keyboard closes, bringing the dialog to the foreground, and the tab is built."""
        self.text.value = self.typed.encode()
        if not self.typed:
            self.toasts += 1
            return 0
        self.foreground()
        return self.build(self.win)

    def confirm(self, typed):
        self.typed = typed
        return self.fw.fn('ringnav_search_confirm', *HANDLER)(self.win, None)

    def foreground(self):
        return self.fw.fn('ringnav_search_foreground', *HANDLER)(self.win, None)

    def away(self):
        """A page opened over the dialog and closed again: the background handler stops the timer."""
        self.timer = False
        return self.foreground()

    def click(self, tab):
        self.tab = tab
        if self.text.value:
            self.build(self.win)

    def rows(self):
        """The list's records, and how many rows the tab on show has."""
        records = [tuple(text_of(r, f) for f in ('title', 'album', 'artist', 'path')) for r in self.q.deques[self.list]]
        return records, len(self.q.children.get(self.view(), []))

    def take(self):
        """Queries, builds and playing marks since the last take, and whether the timer runs."""
        got = (len(self.sql), len(self.builds), len(self.marks), self.timer)
        self.sql.clear(), self.builds.clear(), self.marks.clear(), self.asked.clear()
        return got


@pytest.fixture
def search(q2):
    claim(O['SCAN_THREAD'])
    files, tags = music_card()
    q = q2(files, tags)
    q.update()
    q.fw.var('fw_ctx_artist_type', C.c_int).value = 1
    return Search(q)


def test_a_confirm_builds_its_tab_once(search):
    search.timer = False  # stock's confirm starts no timer: the foreground it raises does
    search.confirm('o')
    records, rows = search.rows()
    assert len(records) == rows > 2 and search.take() == (1, 1, 1, True)


@pytest.mark.parametrize('tab', (SONGS, ALBUMS, ARTISTS, GENRES))
def test_the_dialog_back_on_top_keeps_the_tabs_rows(search, tab):
    search.confirm('e')
    search.click(tab)
    shown, covers = search.rows(), search.covers
    search.take()
    for _ in range(2):  # nothing read or built; the mark on Songs alone, the timer started
        assert search.away() == 0 and search.rows() == shown and search.take() == (0, 0, tab == SONGS, True)
        assert search.covers == covers  # Artists and Genres leave the cover list as the last tab with art set it


@pytest.mark.parametrize('tab, task', ((SONGS, 'songs'), (ALBUMS, 'albums')))
def test_rows_that_stay_get_their_cover_list_back(search, tab, task):
    search.confirm('e')
    search.click(tab)
    records = list(search.q.deques[search.list])
    assert len(records) > 3
    search.cover_init(search.q.deques.new(records[:1]))  # a page opened over Search set it up for its own rows
    # scrolled three rows down; pulled past the top; past the last row
    for offset, asked in ((3 * ROW + 5, [(task, 3, 9)]), (-100, [(task, 0, 9)]), (len(records) * ROW, [])):
        search.offset[search.view()] = offset
        search.take()
        search.away()
        assert search.asked == asked and search.covers == (search.list, records)


def bump_gen(s):
    s.q.fw.var('library_gen', C.c_uint).value += 2


CHANGES = (lambda s: setattr(s.text, 'value', b'o'),  # Tidal's search shares the buffer
           lambda s: setattr(s.q.fw.var('fw_ctx_artist_type', C.c_int), 'value', 0),
           bump_gen,
           lambda s: s.q.deques[s.list].__setitem__(slice(None), list(reversed(s.q.deques[s.list]))),
           lambda s: s.q.children.pop(s.view(), None),
           lambda s: s.q.children[s.view()].pop())


@pytest.mark.parametrize('change', CHANGES, ids=range(len(CHANGES)))
@pytest.mark.parametrize('tab', (SONGS, ARTISTS))
def test_what_a_query_depends_on_changing_builds_the_tab_again(search, tab, change):
    search.confirm('a')
    search.click(tab)
    search.take()
    change(search)
    search.away()
    records, rows = search.rows()
    assert search.take() == (1, 1, tab == SONGS, True) and len(records) == rows > 1
    search.away()  # and the rows that build made are kept in their turn
    assert search.take() == (0, 0, tab == SONGS, True)


def test_a_new_dialog_builds_its_own_rows(search):
    search.confirm('e')
    first = search.rows()
    search.open()
    search.take()
    search.confirm('e')
    assert search.rows() == first and search.take() == (1, 1, 1, True)


@contextlib.contextmanager
def scan():
    """A scan running: library_scanning() reads stock's scan thread and its done flag."""
    saved = C.string_at(O['SCAN_THREAD'], 4), C.string_at(O['SCAN_DONE'], 4)
    C.c_int.from_address(O['SCAN_THREAD']).value, C.c_int.from_address(O['SCAN_DONE']).value = 1, 0
    try:
        yield
    finally:
        C.memmove(O['SCAN_THREAD'], saved[0], 4)
        C.memmove(O['SCAN_DONE'], saved[1], 4)


@contextlib.contextmanager
def failed_read(s):
    s.fail = True
    yield


@contextlib.contextmanager
def writer(s, during=1, after=1):
    """A writer steps library_gen before and after its write: the query's generation is the one read before."""
    gen = s.q.fw.var('library_gen', C.c_uint)
    s.during = lambda: setattr(gen, 'value', gen.value + during)
    yield
    s.during = None
    gen.value += after


@pytest.mark.parametrize('noting', (failed_read, writer, lambda s: writer(s, 2, 0), lambda s: scan()),
                         ids=('failed read', 'writer running', 'whole write', 'scan'))
def test_rows_built_when_the_query_is_not_whole_are_not_kept(search, noting):
    with noting(search):
        search.confirm('e')
    search.take()
    search.away()
    assert search.take() == (1, 1, 1, True)


def test_rows_kept_before_a_scan_are_built_again_while_it_runs(search):
    search.confirm('e')
    search.take()
    with scan():
        search.away()
        assert search.take() == (1, 1, 1, True)


def test_with_no_text_nothing_is_read_or_built(search):
    assert search.away() == 0  # a window closed over the empty box of a new dialog: stock lists every song
    assert search.rows() == ([], 0) and search.take() == (0, 0, 0, True)
    search.confirm('e')
    shown = search.rows()
    search.take()
    search.confirm('')  # the keyword toast, which closes over the dialog
    assert search.toasts == 1 and search.away() == 0
    assert search.rows() == shown and search.take() == (0, 0, 1, True)  # the rows stay, marked as after a build
    search.click(ALBUMS)  # stock's own tab click reads nothing either
    assert search.away() == 0 and search.take() == (0, 0, 1, True)
    search.click(SONGS)
    search.text.value = b'e'  # a text back without a query: rows kept under no text are not its
    search.take()
    search.away()
    records, rows = search.rows()
    assert search.take() == (1, 1, 1, True) and len(records) == rows > 4


@pytest.mark.parametrize('change', CHANGES[1:], ids=range(1, len(CHANGES)))
def test_with_no_text_rows_that_are_no_longer_their_querys_go(search, change):
    search.confirm('a')
    search.confirm('')
    change(search)
    search.take()
    assert search.away() == 0
    assert search.rows() == ([], 0) and search.take() == (0, 0, 0, True)
    assert search.covers == (search.list, [])  # as stock's builder leaves the cover list for no results
    search.confirm('a')  # and the next search is an ordinary one
    records, rows = search.rows()
    assert len(records) == rows > 1 and search.take() == (1, 1, 1, True)


def test_a_tab_click_and_a_new_text_build(search):
    search.confirm('e')
    search.take()
    search.click(ALBUMS)
    assert search.take() == (1, 1, 0, True)
    search.click(SONGS)  # stock keeps one tab's rows: back on Songs is a build
    assert search.take() == (1, 1, 1, True)
    search.confirm('o')
    search.confirm('o')  # the same text again: stock's confirm builds
    assert search.take() == (2, 2, 2, True)


def test_a_text_as_long_as_the_buffer_is_kept(search):
    search.confirm('e' * 255)
    search.take()
    search.away()
    assert search.take() == (0, 0, 1, True)
