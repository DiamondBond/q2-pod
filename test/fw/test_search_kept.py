"""Search keeps a tab's rows while a new query would list the same records (library_lists.c search_made, search_kept;
navigation.c ringnav_search_query, ringnav_search_foreground, ringnav_search_confirm). Stock's dialog builds the tab on
show (its rows destroyed, the query, a row a record) each time it comes back on top, twice for one confirm, and with
no text the whole library. On test_e2e_library's model: a real sqlite3 songtable behind the hooked toolsQueryDbTable,
with stock's handlers around the hooks as the dialog runs them, its refresh timer and the shared cover list."""
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
    """Stock's Search dialog: its text (g_historical_record), its list (p_deque_searchshowlist), a scroll view a tab,
    its 500 ms refresh timer (timer: running or not), the cover list the art thread works from (covers: the list it
    was last set up for, as that list's rows then; asked: the covers asked for), and the stock bodies the build hooks.
    fail makes the next query answer -1 once; during sees each query."""
    def __init__(self, q):
        self.q, self.fw = q, q.fw
        self.list = q.deques.new()
        q.fw.var('fw_ctx_p_deque_searchshowlist', C.c_uint).value = self.list
        self.text = (C.c_char * 256).in_dll(q.fw.lib, 'fw_ctx_g_historical_record')
        self.sql, self.builds, self.marks, self.asked, self.toasts = [], [], [], [], 0
        self.fail, self.during, self.tab, self.timer, self.covers, self.offset = False, None, SONGS, False, None, {}
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
        q.fw.mock('stock_search_foreground_trampoline', lambda win, event, *_: self.build(win) or self.timer_start(win))
        q.fw.mock('stock_search_confirm_trampoline', self.search_run_query)
        q.fw.mock('stock_search_init_trampoline', lambda *_: 7)
        q.fw.mock('search_track_highlight_playing', lambda win, *_: self.marks.append(win) or 0)
        q.fw.mock('search_timer_start', self.timer_start)
        q.fw.mock('albumcoverinfo_init', self.cover_init)
        q.fw.mock('get_albumcover_listsize', lambda *_: len(self.covers[1]) if self.covers else 0)
        q.fw.mock('local_songercover_task', lambda first, count, *_: self.asked.append(('songs', first, count)) or 0)
        q.fw.mock('local_albumsmallcover_task', lambda first, count, *_: self.asked.append(('albums', first, count)) or 0)
        q.fw.mock('widget_lookup', lambda w, name, deep, *_: self.views.get((w, C.string_at(name).decode()), 0))
        q.fw.mock('widget_count_children', lambda w, *_: len(q.children.get(w, [])))
        q.fw.mock('widget_get_prop_int', lambda w, name, default, *_: self.offset.get(w, default))
        self.open()

    def open(self):
        """A new dialog: stock's init clears the text and the list and starts the timer."""
        self.win = self.q.widget(0, 'window_create')
        self.views = {(self.win, name): self.q.widget(self.win, 'scroll_view_create') for name in VIEWS.values()}
        self.text.value = b''
        self.q.deques[self.list].clear()
        self.tab, self.timer = SONGS, True
        assert self.fw.fn('ringnav_search_init', *HANDLER)(self.win, None) == 7  # the build's hook on stock's init

    def view(self, tab=None):
        return self.views[(self.win, VIEWS[tab or self.tab])]

    def timer_start(self, win, *_):
        """Stock's search_timer_start (0x49dd94): the timer added if the dialog has none."""
        self.timer = True
        return 0

    def cover_init(self, lst, *_):
        """Stock's albumcoverinfo_init: the cover list made again from a list's rows."""
        self.covers = (lst & 0xffffffff, list(self.q.deques[lst]))
        return 0

    def search_load_results(self, kind, *_):
        """Stock's search_load_results (0x49c924): the tab's query into the staging deque, then the search list."""
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
        """A tab's builder and what follows it in stock's handlers: the tab's rows destroyed, the query (hooked), on
        Songs and Albums the cover list set up for the search list, a row a record and the first rows' covers asked
        for; then the playing row's mark, on Songs alone."""
        view = self.views[(win, VIEWS[self.tab])]
        self.q.children.pop(view, None)
        self.offset.pop(view, None)
        n = self.fw.fn('ringnav_search_query', C.c_int, C.c_int)(self.tab)
        if self.tab in (SONGS, ALBUMS):
            self.cover_init(self.list)
        for _ in range(n):
            self.q.widget(view, 'list_item_create')
        if n and self.tab in (SONGS, ALBUMS):
            self.asked.append(('songs' if self.tab == SONGS else 'albums', 0, 9))
        self.builds.append((self.tab, self.text.value.decode()))
        if self.tab == SONGS:
            self.marks.append(win)
        return 0

    def search_run_query(self, ctx, *_):
        """Stock's confirm (search_run_query, 0x49fc68): the box's text taken; none is a toast; else the keyboard
        closes, which brings the dialog to the foreground, and the tab is built and marked. It starts no timer."""
        self.text.value = self.typed.encode()
        if not self.typed:
            self.toasts += 1
            return 0
        self.foreground()
        return self.build(self.win)

    def confirm(self, typed):
        """The keyboard's OK with typed in the box."""
        self.typed = typed
        return self.fw.fn('ringnav_search_confirm', *HANDLER)(self.win, None)

    def background(self):
        """A page or a toast opens over the dialog: stock's background handler stops the timer."""
        self.timer = False

    def foreground(self):
        """The dialog comes back on top: a page, Now Playing or a toast closed over it, or the keyboard closed."""
        return self.fw.fn('ringnav_search_foreground', *HANDLER)(self.win, None)

    def away(self):
        """A page opened over the dialog and closed again."""
        self.background()
        return self.foreground()

    def click(self, tab):
        """A tab's click: with text the other tabs' rows go and the tab is built; with none the tab alone changes."""
        self.tab = tab
        if self.text.value:
            for name in VIEWS.values():
                if name != VIEWS[tab]:
                    self.q.children.pop(self.views[(self.win, name)], None)
            self.build(self.win)

    def rows(self):
        """The list, record by record, and how many rows the tab on show has."""
        records = [tuple(text_of(r, f) for f in ('title', 'album', 'artist', 'path')) for r in self.q.deques[self.list]]
        return records, len(self.q.children.get(self.view(), []))

    def take(self):
        """What ran since the last take: queries, builds, playing marks; and whether the timer runs now."""
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
    search.confirm('o')  # Noon, Other, Novel, Episode 1, Demo: stock builds them twice, the foreground's first
    records, rows = search.rows()
    assert len(records) == rows > 2 and search.take() == (1, 1, 1, True)


def test_a_confirm_leaves_the_timer_running(search):
    """Stock's confirm starts no timer: the foreground handler it raises does, also when it builds nothing."""
    search.timer = False
    search.confirm('o')
    assert search.take() == (1, 1, 1, True)


@pytest.mark.parametrize('tab', (SONGS, ALBUMS, ARTISTS, GENRES))
def test_the_dialog_back_on_top_keeps_the_tabs_rows(search, tab):
    search.confirm('e')
    search.click(tab)
    shown = search.rows()
    search.take()
    assert search.away() == 0 and search.rows() == shown
    # nothing read and nothing built; stock's two steps after a build run: the mark on Songs alone, the timer
    assert search.take() == (0, 0, tab == SONGS, True)
    assert search.away() == 0 and search.take() == (0, 0, tab == SONGS, True)


@pytest.mark.parametrize('tab, task', ((SONGS, 'songs'), (ALBUMS, 'albums')))
def test_rows_that_stay_get_their_cover_list_back(search, tab, task):
    search.confirm('e')  # seven songs; the albums Second, Demos, Kept and Novel
    search.click(tab)
    records = list(search.q.deques[search.list])
    assert len(records) > 1 and search.covers == (search.list, records)
    other = search.q.deques.new(records[:1])  # a page opened over Search set the cover list up for its own rows
    search.cover_init(other)
    search.offset[search.view()] = 3 * ROW + 5  # and the tab had been scrolled three rows down
    search.take()
    search.away()
    assert len(records) > 3 and search.covers == (search.list, records) and search.asked == [(task, 3, 9)]
    search.offset[search.view()] = -100  # pulled past its top: from the first row
    search.take()
    search.away()
    assert search.asked == [(task, 0, 9)]
    search.offset[search.view()] = len(records) * ROW  # past the last row: no cover to ask for
    search.take()
    search.away()
    assert search.covers == (search.list, records) and search.asked == []


@pytest.mark.parametrize('tab', (ARTISTS, GENRES))
def test_tabs_without_cover_art_leave_the_cover_list_alone(search, tab):
    search.confirm('a')
    search.click(tab)
    before = search.covers
    search.take()
    search.away()
    assert search.covers == before and search.asked == [] and search.take()[:2] == (0, 0)


def other_text(s):
    s.text.value = b'o'  # Tidal's search shares the buffer


def other_source(s):
    s.q.fw.var('fw_ctx_artist_type', C.c_int).value = 0


def library_write(s):
    s.q.fw.var('library_gen', C.c_uint).value += 2


def other_list(s):
    rows = s.q.deques[s.list]
    rows[:] = list(reversed(rows))


def rows_gone(s):
    s.q.children.pop(s.view(), None)


def one_row_gone(s):
    s.q.children[s.view()].pop()


CHANGES = (other_text, other_source, library_write, other_list, rows_gone, one_row_gone)


@pytest.mark.parametrize('change', CHANGES)
@pytest.mark.parametrize('tab', (SONGS, ARTISTS))
def test_what_a_query_depends_on_changing_builds_the_tab_again(search, tab, change):
    search.confirm('a')  # Dawn and Fall; Alpha, Beta, Gamma and Author
    search.click(tab)
    assert len(search.rows()[0]) > 1
    search.take()
    change(search)
    search.away()
    records, rows = search.rows()
    assert search.take() == (1, 1, tab == SONGS, True) and len(records) == rows
    search.away()  # and the rows that build made are kept in their turn
    assert search.take() == (0, 0, tab == SONGS, True)


def test_a_new_dialog_builds_its_own_rows(search):
    search.confirm('e')
    first = search.rows()
    search.open()
    search.take()
    search.confirm('e')
    assert search.rows() == first and search.take() == (1, 1, 1, True)


def test_another_dialogs_rows_are_not_kept(search):
    """Stock's opener makes a second dialog over the first, on the one list and text: back on the first, the list is
    the second's, as long as the first's rows when the two queries found as many."""
    search.confirm('e')
    first = search.win, search.views, search.rows()
    search.open()
    search.confirm('e')
    assert search.rows() == first[2]
    search.win, search.views = first[:2]  # the second closed: the first is back on top
    search.take()
    search.away()
    assert search.rows() == first[2] and search.take() == (1, 1, 1, True)
    search.away()  # stock's cost from here on: the note stays the last dialog's
    assert search.take() == (1, 1, 1, True)


def test_a_text_that_comes_back_without_a_query_builds(search):
    """An empty box's tab click shows another tab and asks nothing; rows kept under it are no text's."""
    search.confirm('e')
    search.click(ALBUMS)
    search.confirm('')
    assert search.away() == 0
    search.click(SONGS)
    search.text.value = b'e'  # Tidal's search shares the buffer
    search.take()
    search.away()
    records, rows = search.rows()
    assert search.take() == (1, 1, 1, True) and len(records) == rows > 4


def test_rows_built_from_a_failed_query_are_not_kept(search):
    search.fail = True
    search.confirm('e')
    assert search.rows() == ([], 0)
    search.take()
    search.away()
    records, rows = search.rows()
    assert search.take() == (1, 1, 1, True) and len(records) == rows > 1


@pytest.mark.parametrize('during, after', ((1, 1), (2, 0)), ids=('a write still running', 'a whole write'))
def test_rows_built_while_a_writer_ran_are_not_kept(search, during, after):
    """A writer steps library_gen before and after its write: the query's generation is the one read before it."""
    gen = search.q.fw.var('library_gen', C.c_uint)
    search.during = lambda: setattr(gen, 'value', gen.value + during)
    search.confirm('e')
    search.during = None
    gen.value += after
    search.take()
    search.away()
    assert search.take() == (1, 1, 1, True)


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


def test_rows_built_during_a_scan_are_not_kept(search):
    with scan():
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


@pytest.mark.parametrize('change', [c for c in CHANGES if c is not other_text])
def test_with_no_text_rows_that_are_no_longer_their_querys_go(search, change):
    """An empty box can ask for nothing in their place: the rows and their list go, where stock listed every song."""
    search.confirm('a')
    assert search.rows()[1] > 1
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
    assert search.take() == (1, 1, 1, True)
    search.confirm('o')  # OK again with the same text: stock's confirm builds, once
    assert search.take() == (1, 1, 1, True)


def test_a_text_as_long_as_the_buffer_is_kept(search):
    long = 'e' * 255
    search.confirm(long)
    search.take()
    search.away()
    assert search.take() == (0, 0, 1, True)
