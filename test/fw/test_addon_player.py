"""patch/addon_player.c: a card app with q2app's player=1 ("player" in /tmp/q2-addon.caps) reads what the Q2 plays in
/tmp/q2-player and its queue in /tmp/q2-player.queue, kept while such an app runs and gone otherwise, and controls
the player through /tmp/q2-<id>.player, answered in its .done."""
import ctypes as C

import pytest

from conftest import O, Files, Rows, st  # noqa: F401  st: navigation.c's state by field
from test_addon import ap, card, scan
from test_onlinematch import records  # noqa: F401  the queue's songs

STATE, QUEUE, REQ, DONE, LIST = '/tmp/q2-player', '/tmp/q2-player.queue', '/tmp/q2-foo.player', '/tmp/q2-foo.player.done', '/tmp/q2-foo.list'
STOPPED, PLAYING, PAUSED = 1, 2, 3  # mclGetPlayStatus
A, B, C3, D = b'/mnt/mmc/A/01 One.flac', b'/mnt/mmc/A/02 Two.flac', b'/mnt/mmc/B/03 Three.flac', b'/mnt/mmc/B/04 Four.flac'


class Player:
    """The player as stock keeps it (its queue in a libcstl deque of rows, its shuffle pool, MCL_POS, its status,
    times and output), /tmp as Files, the card's folders as stock lists them (toolsLoadDirectory), and the two
    entry points addon_poll calls."""
    def __init__(self, fw, mcl, records, paths=(A, B, C3), pos=0, kind=0xf001):
        self.fw, self.mcl, self.records = fw, mcl, records
        self.songs = {p: records.song(p, album=b'Album', title=b'Title %d' % k, artist=b'Artist', album_artist=b'AA',
                                      track=k + 1, disc=1, genre=b'Rock') for k, p in enumerate((A, B, C3, D))}
        self.tmp = Files(fw)
        self.now = {'ms': 1000, 'status': PLAYING, 'sec': 12, 'len': 200, 'fav': 0, 'way': 0, 'forbid': 0}
        self.deques, self.cells, self.started = Rows(fw), [], []
        self.queue, self.pool = self.deques.rows([self.songs[p] for p in paths]), self.deques.new()
        fw.var('fw_ctx_mcl_pdeqplaylist', C.c_uint).value = self.queue
        C.c_uint.from_address(O['MCL_POOL']).value = self.pool
        for k in range(len(paths)):
            self.push(self.pool, k)
        mcl.pos, mcl.type, mcl.lastpos = pos, kind, -1
        fw.var('g_volume', C.c_ubyte).value, fw.var('g_maxvolume', C.c_ubyte).value = 40, 100
        fw.mock('fw__deque_push_back', self.push)
        fw.mock('fw_deque_pop_back', self.pop)
        fw.mock('time_now_ms', lambda *_: self.now['ms'])
        fw.mock('mclGetPlayStatus', lambda *_: self.now['status'])
        fw.mock('mclGetOutputWay', lambda *_: self.now['way'])
        fw.mock('checkFavExist', lambda *_: self.now['fav'])
        fw.mock('check_forbid_play_no_headset', lambda *_: self.now['forbid'])
        fw.mock('player_playtime_and_length', self.times)
        fw.mock('tk_str_start_with', lambda s, p, *_: C.string_at(s).startswith(C.string_at(p)))
        fw.mock('tk_strcmp', lambda a, b, *_: 0 if a and b and C.string_at(a) == C.string_at(b) else 1)
        fw.mock('toolsLoadDirectory', self.listing)
        fw.mock('fw___xstat', lambda v, path, info, *_: 0 if C.string_at(path) in self.songs else -1)
        fw.mock('player_start', self.start)

    def push(self, q, value, *_):
        if q & 0xffffffff == self.pool:  # a deque of ints: deque_at gives an element's address
            self.cells.append(C.c_int(value))
            value = C.addressof(self.cells[-1])
            self.deques[q].append(value)
        else:
            self.deques.push(q, value)

    def pop(self, q, *_):
        v = self.deques[q].pop()
        if (q & 0xffffffff) in self.deques.held:
            del self.deques.copies[v]

    def times(self, sec, length, *_):
        C.c_int.from_address(sec).value, C.c_int.from_address(length).value = self.now['sec'], self.now['len']

    def listing(self, path, *_):
        folder = C.string_at(path) + b'/'
        into = self.fw.var('fw_ctx_tools_pdeq_directory', C.c_uint).value
        for p, r in self.songs.items():
            if p.startswith(folder) and b'/' not in p[len(folder):]:
                self.deques.push(into, r)
        return len(self.deques[into])

    def start(self, q, at, cls, mode, *_):
        self.started.append((self.paths(q), at, cls, mode))

    def paths(self, q=None):
        return [C.string_at(C.c_uint64.from_address(r + O['REC_PATH']).value) for r in self.deques[q or self.queue]]

    def poll(self, on=1, ms=100):
        self.now['ms'] += ms
        self.fw.fn('addon_player_poll', None, C.c_int)(on)
        return self.tmp.files.get(STATE)

    def state(self):
        self.poll()
        return dict(line.split('=', 1) for line in self.tmp.files[STATE].decode().splitlines())

    def ask(self, raw, ms=30):
        self.tmp.files[REQ] = raw
        self.now['ms'] += ms
        self.fw.fn('addon_player_ask', None, C.c_int, C.c_char_p)(0, b'foo')
        return self.tmp.files.get(DONE)

    def hash(self):
        return '%x' % self.fw.fn('queue_hash', C.c_uint, C.c_void_p)(self.queue)


def accent(fw):
    return '%06x' % (fw.fn('accent_tone', C.c_uint, C.c_int)(0) & 0xffffff)


@pytest.fixture
def player(fw, mcl, records):
    return Player(fw, mcl, records)


def test_the_state_says_what_plays(player):
    assert player.poll() == ('status=playing\nowner=player\nkind=f001\npath=/mnt/mmc/A/01 One.flac\ntitle=Title 0\n'
                             'artist=Artist\nalbum=Album\nalbumartist=AA\ngenre=Rock\ntrack=1\ndisc=1\ncuestart=0\ncueend=0\n'
                             'sec=12\nlen=200\nvolume=40\nmaxvolume=100\noutput=jack\nshuffle=0\nrepeat=2\ngroup=0\nheart=0\n'
                             f'pos=0\ncount=3\nqueue={player.hash()}\naccent={accent(player.fw)}\nupnext=\n').encode()


def test_the_accent_is_the_theme_s_and_a_change_rewrites(fw, player, st):
    player.poll()
    was = player.state()['accent']
    player.tmp.files[STATE] = b'kept'
    st('minimal_accent').value = st('accent').value = 2  # Tidal's, from Minimal's Graphite
    assert accent(fw) != was
    assert b'accent=%s\n' % accent(fw).encode() in player.poll()


@pytest.mark.parametrize('status, word', [(PLAYING, 'playing'), (PAUSED, 'paused'), (STOPPED, 'stopped')])
def test_the_status_is_the_player_s(player, status, word):
    player.now['status'] = status
    assert player.state()['status'] == word


def test_a_value_s_tabs_and_line_ends_are_spaces_and_a_cue_range_is_in_ms(fw, mcl, records):
    p = Player(fw, mcl, records)
    track = records.song(b'/mnt/mmc/A/x.cue.flac', title=b'a\tb\r\nc', cue=(30, 95), genre=b'')
    p.deques[p.queue][0] = track
    s = p.state()
    assert (s['title'], s['cuestart'], s['cueend']) == ('a b  c', '30000', '95000')


def test_a_song_off_the_card_has_no_path_and_nothing_loaded_is_no_one_s(player):
    player.mcl.pos = 7
    s = player.state()
    assert (s['owner'], s['path'], s['title'], s['sec'], s['count']) == ('none', '', '', '-1', '3')
    url = player.records.song(b'http://127.0.0.1:8096/s?token=t', genre=b'')
    player.deques[player.queue][0] = url
    player.mcl.pos = 0
    assert player.state()['path'] == ''  # an address can carry an app's token


@pytest.mark.parametrize('way, word', [(0, 'jack'), (1, 'bluetooth'), (2, 'usb')])
def test_the_output(player, way, word):
    player.now['way'] = way
    assert player.state()['output'] == word


def test_written_only_on_a_change_and_looked_at_every_100_ms(player):
    player.poll()
    player.tmp.files[STATE] = b'kept'
    assert player.poll() == b'kept'  # nothing changed
    player.now['sec'] = 13
    assert player.poll(ms=50) == b'kept'  # 50 ms since the last look
    assert player.poll(ms=49) == b'kept'
    assert b'sec=13\n' in player.poll(ms=1)


def test_the_files_go_when_no_player_app_runs(player):
    player.tmp.files[STATE], player.tmp.files[QUEUE] = b'stale', b'stale'
    assert player.poll(on=0) is None and QUEUE not in player.tmp.files  # a crashed run's, at the first look
    assert player.poll() and QUEUE in player.tmp.files
    assert player.poll(on=0) is None and QUEUE not in player.tmp.files
    player.tmp.files[STATE] = b'not ours'
    assert player.poll(on=0) == b'not ours'  # removed once, not every pass


def test_the_heart_is_asked_once_a_track(fw, player):
    player.now['fav'] = 1
    assert player.state()['heart'] == '1'
    player.now['sec'] = 13
    player.poll()
    assert len(fw.calls('checkFavExist')) == 1
    player.mcl.pos = 1
    assert player.state()['heart'] == '1' and len(fw.calls('checkFavExist')) == 2


def test_the_queue_file_holds_each_record_s_own_text(player):
    player.poll()
    assert player.tmp.files[QUEUE] == (f'{player.hash()}\n'.encode() +
                                       b'/mnt/mmc/A/01 One.flac\tTitle 0\tArtist\tAlbum\tAA\t1\t0\t0\n'
                                       b'/mnt/mmc/A/02 Two.flac\tTitle 1\tArtist\tAlbum\tAA\t2\t0\t0\n'
                                       b'/mnt/mmc/B/03 Three.flac\tTitle 2\tArtist\tAlbum\tAA\t3\t0\t0\n')


def test_the_queue_file_is_written_again_only_when_the_queue_changes(player):
    player.poll()
    player.tmp.files[QUEUE] = b'kept'
    player.now['sec'] = 50
    player.poll()
    assert player.tmp.files[QUEUE] == b'kept'
    player.deques[player.queue].pop()
    player.poll()
    assert player.tmp.files[QUEUE].count(b'\n') == 3 and player.state()['queue'] == player.hash()


def test_a_queue_past_5000_ends_with_more(player):
    player.deques[player.queue][:] = [player.deques[player.queue][0]] * 5003
    player.poll()
    lines = player.tmp.files[QUEUE].split(b'\n')
    assert len(lines) == 1 + 5000 + 2 and lines[-2] == b'more\t5003' and lines[-1] == b''


def test_upnext_is_empty_in_the_queue_s_own_order_and_lists_any_other(player):
    assert player.state()['upnext'] == ''
    assert player.ask(b'a1\nplaynext 2\n') == b'a1 ok\n'
    assert player.state()['upnext'] == '2,1'


def test_a_request_is_answered_and_the_state_follows_at_once(fw, player):
    player.poll()
    player.now['status'] = PAUSED
    assert player.ask(b'a1\nplay\n') == b'a1 ok\n' and len(fw.calls('player_play_pause')) == 1
    assert player.poll(ms=0).startswith(b'status=paused\n')  # the stub doesn't play: written at once all the same
    assert player.ask(b'a2\nplay\n', ms=29) == b'a1 ok\n'  # within 30 ms of the last look
    assert player.ask(b'a2\nplay\n', ms=1) == b'a2 ok\n' and len(fw.calls('player_play_pause')) == 2


@pytest.mark.parametrize('cmd, status, presses', [
    (b'play', PAUSED, 1), (b'play', PLAYING, 0), (b'pause', PLAYING, 1), (b'pause', PAUSED, 0),
    (b'toggle', PLAYING, 1), (b'toggle', STOPPED, 1),
])
def test_play_pause_and_toggle(fw, player, cmd, status, presses):
    player.now['status'] = status
    assert player.ask(b'x\n' + cmd) == b'x ok\n'
    assert len(fw.calls('player_play_pause')) == presses


def test_a_start_asks_for_an_output_first(fw, player):
    player.now['status'], player.now['forbid'] = PAUSED, 1
    assert player.ask(b'x\nplay\n') == b'x error 1: No output connected\n' and not fw.calls('player_play_pause')
    assert player.ask(b'y\nnext\n') == b'y error 1: No output connected\n' and not fw.calls('player_next_music')
    assert player.ask(b'z\npause\njump 2\n') == b'z error 2: No output connected\n' and not fw.calls('player_start_queue')


def test_nothing_to_play(fw, player):
    player.mcl.pos, player.now['status'] = 9, STOPPED
    assert player.ask(b'x\nplay\n') == b'x error 1: Nothing is playing\n'
    assert player.ask(b'y\nseek 1000\n') == b'y error 1: Nothing is playing\n'
    assert player.ask(b'z\nheart 1\n') == b'z error 1: Nothing is playing\n'


def test_next_and_prev_are_the_side_buttons(fw, player):
    assert player.ask(b'x\nnext\nprev\n') == b'x ok\n'
    assert len(fw.calls('player_next_music')) == len(fw.calls('player_prev_music')) == 1


@pytest.mark.parametrize('status, ms, call, sec', [
    (PLAYING, 61499, 'player_seek_time', 61), (PLAYING, 61500, 'player_seek_time', 62), (PAUSED, 5000, 'mclSetSeek', 5),
    (PLAYING, 999000, 'player_seek_time', 200),  # past the end: to the end
])
def test_seek_rounds_to_the_second_and_a_pause_stays(fw, player, status, ms, call, sec):
    player.now['status'] = status
    assert player.ask(b'x\nseek %d\n' % ms) == b'x ok\n'
    assert [a[0] for _, a in fw.calls(call)] == [sec]


def test_seek_in_a_cue_track_is_from_its_start_while_paused(fw, mcl, records):
    p = Player(fw, mcl, records)
    p.deques[p.queue][0] = records.song(b'/mnt/mmc/A/x.flac', cue=(30, 95), genre=b'')
    p.now['status'] = PAUSED
    assert p.ask(b'x\nseek 5000\n') == b'x ok\n' and [a[0] for _, a in fw.calls('mclSetSeek')] == [35]


@pytest.mark.parametrize('level, kept', [(55, 55), (0, 0), (100, 80)])
def test_volume_is_held_to_maximum_volume_and_saved(fw, player, level, kept):
    fw.var('g_maxvolume', C.c_ubyte).value = 80
    assert player.ask(b'x\nvolume %d\n' % level) == b'x ok\n'
    assert fw.var('g_volume', C.c_ubyte).value == kept and [a[0] for _, a in fw.calls('device_set_volume')] == [kept]
    assert [(a[0], C.string_at(a[1]), C.string_at(a[2])) for _, a in fw.calls('write_int_config')] == [(kept, b'PLAYSET', b'VOLUME')]


@pytest.mark.parametrize('line', [b'volume 101', b'volume -1', b'volume', b'volume 5x', b'shuffle 5', b'repeat 6', b'heart 2',
                                  b'seek', b'jump x', b'play now', b'insert middle', b'load'])
def test_a_bad_value(fw, player, line):
    assert player.ask(b'x\n' + line + b'\n') == b'x error 1: Bad value\n'
    assert not fw.calls('device_set_volume')


def test_shuffle_and_repeat_on_a_local_queue_only(player):
    assert player.ask(b'x\nshuffle 1\nrepeat 4\n') == b'x ok\n'
    s = player.state()
    assert (s['shuffle'], s['repeat']) == ('1', '4')
    player.mcl.type = 0xf1  # an online queue
    assert player.ask(b'y\nrepeat 0\n') == b'y error 1: Not a local queue\n'


def test_heart_in_and_out_of_my_favourites(fw, player):
    assert player.state()['heart'] == '0'
    assert player.ask(b'x\nheart 1\n') == b'x ok\n'
    (cls, into, songs, *_), = [a for _, a in fw.calls('batch_add_file')]
    assert (cls, into) == (0xf001, 0xf00a) and not fw.calls('deleteMusicFromFav')
    player.now['fav'] = 1
    assert player.state()['heart'] == '1'  # asked again after the command
    assert player.ask(b'y\nheart 1\nheart 0\n') == b'y ok\n'
    assert len(fw.calls('batch_add_file')) == 1 and len(fw.calls('deleteMusicFromFav')) == 1


def test_jump_plays_a_queue_row(fw, player):
    assert player.ask(b'x\njump 2\n') == b'x ok\n' and [a[0] for _, a in fw.calls('player_start_queue')] == [2]
    assert player.ask(b'y\njump 3\n') == b'y error 1: No such song in the queue\n'


def test_remove_takes_a_row_out_and_every_index_after_it_down(player):
    player.mcl.pos = 1
    assert player.ask(b'x\nremove 0\n') == b'x ok\n'
    assert player.paths() == [B, C3] and player.mcl.pos == 0
    assert [C.c_int.from_address(c).value for c in player.deques[player.pool]] == [0, 1]
    assert player.ask(b'y\nremove 0\n') == b'y error 1: Bad value\n'  # the playing one stays
    assert player.ask(b'z\nremove 2\n') == b'z error 1: No such song in the queue\n'
    player.mcl.type = 0xf1
    assert player.ask(b'w\nremove 1\n') == b'w error 1: Not a local queue\n' and player.paths() == [B, C3]


def test_a_remove_under_advanced_play_keeps_its_play_next(fw, mcl, records):
    p = Player(fw, mcl, records, paths=(A, B, C3, D))
    assert p.ask(b'x\nplaynext 3\n') == b'x ok\n' and p.state()['upnext'] == '3,1,2'
    assert p.ask(b'y\nremove 1\n') == b'y ok\n' and p.paths() == [A, C3, D] and p.state()['upnext'] == '2,1'


def test_load_plays_the_list_from_its_index(fw, player):
    player.tmp.files[LIST] = b'/mnt/mmc/B/03 Three.flac\r\n\n/mnt/mmc/missing.flac\n/mnt/mmc/A/02 Two.flac\n/mnt/mmc/A/01 One.flac'
    assert player.ask(b'x\nload 2\n') == b'x ok\n'
    assert player.started == [([C3, B, A], 1, 0xf001, 2)] and not fw.calls('navigator_to_with_context')
    assert player.ask(b'y\nload 4\n') == b'y error 1: No such song in the queue\n'


def test_the_list_s_paths_stay_on_the_card(player):
    player.tmp.files[LIST] = b'/mnt/mmc/A/../A/01 One.flac\n/tmp/x.flac\nmnt/mmc/A/01 One.flac\n/mnt/mmc/A/02 Two.flac\n'
    assert player.ask(b'x\nload 0\n') == b'x ok\n' and player.started == [([B], 0, 0xf001, 2)]
    player.tmp.files[LIST] = b'/mnt/mmc/A/../A/01 One.flac\n'
    assert player.ask(b'y\nload 0\n') == b'y error 1: Bad value\n'
    del player.tmp.files[LIST]
    assert player.ask(b'z\ninsert end\n') == b'z error 1: Bad value\n'


@pytest.mark.parametrize('where, order', [(b'next', [A, C3, B]), (b'end', [A, B, C3])])
def test_insert_after_the_playing_song_or_at_the_end(fw, mcl, records, where, order):
    p = Player(fw, mcl, records, paths=(A, B))
    p.tmp.files[LIST] = C3 + b'\n'
    assert p.ask(b'x\ninsert ' + where + b'\n') == b'x ok\n' and p.paths() == order and not p.started


def test_insert_into_no_queue_loads_it_without_playing(fw, mcl, records):
    p = Player(fw, mcl, records, paths=())
    p.tmp.files[LIST] = A + b'\n' + B + b'\n'
    assert p.ask(b'x\ninsert end\n') == b'x ok\n' and not p.started
    (q, at, cls, *_), = [a for _, a in fw.calls('mclLoadPlayList')]
    assert (at, cls) == (0, 0xf001)


def test_an_error_names_its_line_and_stops_the_rest(fw, player):
    player.now['status'] = PAUSED
    assert player.ask(b'a1\nplay\n\nbogus\nnext\n') == b'a1 error 3: Unknown command\n'
    assert len(fw.calls('player_play_pause')) == 1 and not fw.calls('player_next_music')


def test_more_than_16_commands(fw, player):
    assert player.ask(b'a1\n' + b'pause\n' * 17) == b'a1 error 17: Bad value\n'


def test_a_request_runs_once(fw, player):
    player.now['status'] = PAUSED
    assert player.ask(b'a1\nplay\n') == b'a1 ok\n'
    player.tmp.files[DONE] = b'gone'
    assert player.ask(b'a1\nplay\n') == b'gone'  # the same file, not read again
    player.tmp.files[DONE] = b'a1 ok\n'
    assert player.ask(b'a1\nplay\r\n') == b'a1 ok\n'  # demo restarted: a seq .done answers is done
    assert len(fw.calls('player_play_pause')) == 1
    assert player.ask(b'a2\r\nplay\n') == b'a1 ok\n'


@pytest.mark.parametrize('raw', [b'\nplay\n', b'a b\nplay\n', b'a-1\nplay\n', b'a' * 24 + b'\nplay\n', b'play'])
def test_a_first_line_that_isn_t_a_seq_is_never_answered(fw, player, raw):
    player.now['status'] = PAUSED
    assert player.ask(raw) is None and not fw.calls('player_play_pause')


def test_an_app_s_q2app_turns_it_on(fw, mcl):
    world = card(fw, foo=b'name=Foo\nplayer=1\n', bar=b'name=Bar\n')
    scan(fw)
    fw.mock('mclGetPlayStatus', lambda *_: STOPPED)
    poll = fw.fn('addon_poll', None)
    foo, bar = sorted(ap(fw).a[:2], key=lambda a: a.id != b'foo')
    for a in foo, bar:
        world.files[a.pid] = b'1'  # its loop running
    bar.launched = 1
    poll()
    assert b'/tmp/q2-player' not in world.files
    foo.restart = 1  # Retry's restart, its old loop not gone yet
    world.ms += 500
    poll()
    assert world.files[b'/tmp/q2-player'].startswith(b'status=stopped\n')
    foo.restart = 0
    poll()
    assert b'/tmp/q2-player' not in world.files
