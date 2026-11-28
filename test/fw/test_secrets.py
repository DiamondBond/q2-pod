"""secrets.c and scrobble.c's secrets path (docs/internals.md#scrobbling): a card app whose q2app says secrets=1 keeps
the scrobbling logins, over /tmp/q2-<id>.sock (Q2VAULT/1, one request a connection), and without one the upload is
main's, call for call."""
import ctypes as C

import pytest

from test_addon import Ap
from test_nav_library_pages import Up
from test_scrobble import ACCOUNT, HEADER, INI, LB_ONLY, LOG, Card, Net, Upload, config, line

SOCK = b'/tmp/q2-vault.sock'
S_IFSOCK, S_IFLNK = 0o140000, 0o120000
CALL = 'fw_pthread_mutex_lock fw_fopen fw_fseek fw_ftell fw_fseek fw_fread fw_fclose fw_pthread_mutex_unlock'.split()
RETIRE = ('fw_pthread_mutex_lock fw_fopen fw_fread fw_fopen fw_fwrite fw_fread fw_ferror fw_fflush fw_fileno fw_fsync '
          'fw_fclose fw_fclose fw_fopen fw_fwrite fw_fflush fw_fileno fw_fsync fw_fclose fw_rename fw_pthread_mutex_unlock '
          'fw_pthread_join').split()


class App:
    """A secrets app in addon.c's table (id vault) and its socket: stat'd as mode and uid, each connection one request,
    answered from copy (None: none saved). up: False, nothing listens."""
    def __init__(self, fw, copy=None, mode=S_IFSOCK, uid=0, up=True, listed=True):
        self.copy, self.mode, self.uid, self.up, self.requests, self.now = copy, mode, uid, up, [], 0
        if listed:
            ap = fw.var('addon__ap', Ap)
            ap.n, ap.a[0].id, ap.a[0].name, ap.a[0].present, ap.a[0].secrets = 1, b'vault', b'Vault', 1, 1
        self.req = b''
        self.out: bytes | None = b''
        fw.mock('fw___lxstat', self.stat)
        fw.mock('fw_socket', lambda *_: 5)
        fw.mock('fw_connect', self.connect)
        fw.mock('fw_select', lambda *_: 1)
        fw.mock('fw_send', self.send)
        fw.mock('fw_recv', self.recv)
        fw.mock('fw_clock_gettime', self.clock)

    def clock(self, which, ts, *_):
        self.now += 1
        C.cast(ts, C.POINTER(C.c_long))[0] = self.now

    def stat(self, ver, path, st, *_):
        if C.string_at(path) != SOCK or not self.up:
            return -1
        words = C.cast(st, C.POINTER(C.c_uint))
        words[5], words[7] = self.mode, self.uid
        return 0

    def connect(self, fd, to, n, *_):
        assert C.string_at(to + 2) == SOCK
        self.req, self.out = b'', None
        return 0 if self.up else -1

    def send(self, fd, buf, n, *_):
        self.req += C.string_at(buf, n)
        return n

    def recv(self, fd, buf, n, *_):
        if self.out is None:
            head, op, body = self.req.split(b'\n', 2)
            assert head == b'Q2VAULT/1'
            self.requests.append((op.decode(), body))
            if op == b'put':
                self.copy = body
            self.out = b'Q2VAULT/1\n' + (b'ok\n' + (self.copy if op == b'get' else b'') if op == b'put' or self.copy is not None
                                         else b'none\n')
        piece, self.out = self.out[:n], self.out[n:]
        C.memmove(buf, piece, len(piece))
        return len(piece)


def ini(fw, card):
    """toolsReadConfig as stock's: card.files[path] read again at each call, lines trimmed, section and key in any case."""
    def lookup(path, section, key, out, default, *_):
        where, want = None, (C.string_at(section).decode().lower(), C.string_at(key).decode().lower())
        for raw in card.files.get(C.string_at(path).decode(), b'').decode().splitlines():
            s = raw.strip()
            if s.startswith('[') and s.endswith(']'):
                where = s[1:-1].strip().lower()
            elif '=' in s and (where, s.split('=', 1)[0].strip().lower()) == want:
                v = s.split('=', 1)[1].strip().encode()
                C.memmove(out, v + b'\0', len(v) + 1)
                return 1
        return -1
    fw.mock('toolsReadConfig', lookup)


def run(fw, file, copy=None, log=HEADER + line(), **app):
    card = Card(fw, {INI: file, LOG: log})
    ini(fw, card)
    net = Net(fw)
    vault = App(fw, copy, **app)
    return Upload(fw).run(), card, net, vault


def strip(fw):
    return fw.fn('scrobble_strip', C.c_int)()


FILE = b'[LISTENBRAINZ]\nTOKEN=tok\n\n[LASTFM]\nUSER=u\nPASSWORD=p&w\nAPI_KEY=key\nAPI_SECRET=sec\n[SCROBBLE]\nAUTO=1\n'
COPY = b'TOKEN=tok\nUSER=u\nAPI_KEY=key\nAPI_SECRET=sec\nSESSION_KEY=SK123\n'
STRIPPED = b'[LISTENBRAINZ]\nSECRETS=1\n\n[LASTFM]\nSECRETS=1\nUSER=u\n[SCROBBLE]\nAUTO=1\n'


# Without a secrets app: main's upload.

@pytest.mark.parametrize('values, reads', ((ACCOUNT, 6), (LB_ONLY, 7)))
def test_without_a_secrets_app_the_upload_is_main_s(fw, values, reads):
    """Main's calls in main's order: no socket, no stat, no wake, nothing written but the log's own files. A complete
    file reads what main reads; one without Last.fm reads its SECRETS key too."""
    read = config(fw, values)
    card, net = Card(fw, {LOG: HEADER + line()}), Net(fw)
    assert Upload(fw).run() == (1, 1, 1)
    names = [n for n, _ in fw.calls() if n not in ('tk_snprintf',) and not n.startswith(('fw_curl', 'fw_MD5'))]
    assert names == ['toolsReadConfig'] * reads + ['fw_pthread_create'] + CALL + RETIRE
    assert len(read) == reads and card.opened == [(LOG, 'rb'), (LOG, 'rb'), (LOG + '.tmp', 'wb'), (LOG + '.sent', 'ab')]
    assert len(net.to('listenbrainz')) == 1 and fw.var('scrobble__up', Up).app == b''


def secrets_app(fw, scan_first=True, **apps):
    from test_addon import card, scan
    card(fw, **apps)
    if scan_first:
        scan(fw)
    found = fw.fn('addon_secrets', C.c_int, C.c_char_p, C.c_char_p, C.c_int)
    id, name = C.create_string_buffer(16), C.create_string_buffer(32)
    return found(id, name, 0), id.value, name.value


def test_only_an_app_whose_q2app_says_secrets_1_is_one(fw):
    assert secrets_app(fw, plain=b'name=Plain\n', zero=b'secrets=0\nname=Zero\n') == (0, b'', b'')


def test_an_app_that_says_secrets_1_is_found(fw):
    assert secrets_app(fw, plain=b'name=Plain\n', vault=b'name=Vault\nsecrets=1\r\n') == (1, b'vault', b'Vault')


def test_no_scan_yet_reads_no_card(fw):
    assert secrets_app(fw, scan_first=False, vault=b'secrets=1\n') == (0, b'', b'')
    assert not fw.calls('fw_opendir')


def test_an_app_without_the_key_is_left_alone(fw):
    """An app on the card that didn't opt in: the upload is main's, no socket, the file as it was."""
    from test_addon import Ap
    ap = fw.var('addon__ap', Ap)
    ap.n, ap.a[0].id, ap.a[0].present = 1, b'other', 1
    result, card, net, vault = run(fw, FILE, listed=False)
    assert result == (1, 1, 1) and not vault.requests and card.files[INI] == FILE and not fw.calls('fw_socket')


def test_a_long_secrets_value_is_read_whole(fw):
    """toolsReadConfig takes no size: the marker's buffer is as big as any value it writes."""
    values = {**LB_ONLY, ('LASTFM', 'SECRETS'): 'x' * 255}
    config(fw, values)
    assert fw.fn('scrobble_ready', C.c_int, C.c_void_p)(None) == 1


# With one.

def test_an_upload_moves_the_working_logins_into_the_app(fw):
    """The sign-in's session key in the password's place, read back as put; the file is left as it was."""
    result, card, net, vault = run(fw, FILE)
    assert result == (1, 1, 1) and vault.copy == COPY
    assert [op for op, _ in vault.requests] == ['get', 'put', 'get']
    assert card.files[INI] == FILE
    assert strip(fw) == 1 and card.files[INI] == STRIPPED


def test_the_same_logins_aren_t_put_again(fw):
    result, card, net, vault = run(fw, FILE.replace(b'PASSWORD=p&w', b'SESSION_KEY=SK123'), copy=COPY)
    assert result == (1, 1, 1) and [op for op, _ in vault.requests] == ['get']


def test_a_marked_file_uploads_from_the_app_s_copy(fw):
    result, card, net, vault = run(fw, STRIPPED, copy=COPY)
    assert result == (1, 1, 1) and net.forms()[-1]['sk'] == 'SK123' and net.listens()
    assert fw.var('scrobble__up', Up).ask == 0 and card.files[INI] == STRIPPED  # nothing of the file's to take off


def test_nothing_to_upload_moves_nothing(fw):
    result, card, net, vault = run(fw, FILE, log=HEADER)
    assert result == (1, 1, 0) and not vault.requests


@pytest.mark.parametrize('why', ['no app', 'none saved', 'not answering', "Last.fm's gone", 'another user'])
def test_a_marked_section_left_without_its_logins_sends_nothing(fw, why):
    """Nothing goes, not even to ListenBrainz with its token in the file, so no listen leaves the log for one service."""
    file = {'another user': STRIPPED.replace(b'USER=u', b'USER=v'),
            "Last.fm's gone": STRIPPED.replace(b'[LISTENBRAINZ]\nSECRETS=1', b'[LISTENBRAINZ]\nTOKEN=tok')}.get(why, STRIPPED)
    copy = None if why in ('none saved', "Last.fm's gone") else COPY
    result, card, net, vault = run(fw, file, copy=copy, listed=why != 'no app', up=why != 'not answering')
    assert result[:2] == (1, -1) and not net.requests and card.files[LOG] == HEADER + line()
    assert fw.fn('scrobble_missing', C.c_int)() == 1
    if why == 'no app':
        assert not fw.calls('fw_socket') and not fw.calls('fw___lxstat')


def test_a_session_key_link_last_fm_saved_wins_and_moves_in(fw):
    """Link Last.fm writes SESSION_KEY into the file (with the pair it read there): the file's lines win over the copy's,
    go into the app, and come off the card at Remove."""
    file = STRIPPED.replace(b'USER=u\n', b'USER=u\nAPI_KEY=key\nAPI_SECRET=sec\nSESSION_KEY=NEW\n')
    result, card, net, vault = run(fw, file, copy=COPY)
    assert result == (1, 1, 1) and net.forms()[-1]['sk'] == 'NEW' and b'SESSION_KEY=NEW' in vault.copy
    assert strip(fw) == 1 and card.files[INI] == STRIPPED


@pytest.mark.parametrize('mode, uid', [(S_IFLNK, 0), (S_IFSOCK, 1000)])
def test_only_a_socket_root_owns_is_asked(fw, mode, uid):
    sleeps = []
    fw.mock('fw_usleep', lambda us, *_: sleeps.append(us) or 0)
    result, card, net, vault = run(fw, STRIPPED, copy=COPY, mode=mode, uid=uid)
    assert result[:2] == (1, -1) and not fw.calls('fw_connect')
    assert len(sleeps) == 19  # 20 tries, no wait after the last


# Remove.

@pytest.mark.parametrize('file', [
    b'[listenbrainz]\r\n  token = tok\r\n[ LastFM ]\r\nuser=u\r\nPassword=p&w\r\napi_key=key\r\nApi_Secret = sec\r\n',
    b'  [LISTENBRAINZ]\nTOKEN=tok\n\t[LASTFM]  \nUSER=u\nPASSWORD=p&w\nAPI_KEY=key\nAPI_SECRET=sec'])
def test_remove_takes_every_line_stock_reads_off_the_card(fw, file):
    result, card, net, vault = run(fw, file)
    assert result == (1, 1, 1) and strip(fw) == 1
    left = card.files[INI]
    assert b'tok' not in left and b'p&w' not in left and b'key' not in left and b'sec' not in left
    assert left.count(b'SECRETS=1') == 2 and b'u' in left


@pytest.mark.parametrize('fail', ['write:/mnt/mmc/.scrobble.ini.tmp', 'sync', 'rename'])
def test_a_remove_that_fails_leaves_the_file(fw, fail):
    result, card, net, vault = run(fw, FILE)
    card.fail.add(fail)
    assert strip(fw) == 0 and card.files[INI] == FILE and INI + '.tmp' not in card.files


def test_remove_fails_when_stock_still_reads_a_login_there(fw):
    """The read-back: a login the rewrite left (here, stock's reader shown one the rewrite can't see) fails it."""
    result, card, net, vault = run(fw, FILE)
    real = card.files

    class Leaky(dict):
        def get(self, path, default=None):
            data = dict.get(self, path, default)
            return data + b'[LISTENBRAINZ]\nTOKEN=tok\n' if path == INI + '.tmp' and data is not None else data
    card.files = Leaky(real)
    ini(fw, card)
    assert strip(fw) == 0 and card.files[INI] == FILE and INI + '.tmp' not in card.files


def test_only_sections_the_app_keeps_come_off(fw):
    """A Last.fm the upload couldn't use (no secret) stays in the file whole; ListenBrainz's token moves."""
    file = b'[LISTENBRAINZ]\nTOKEN=tok\n[LASTFM]\nUSER=u\nPASSWORD=p&w\nAPI_KEY=key\n'
    result, card, net, vault = run(fw, file)
    assert result == (1, 1, 1) and vault.copy == b'TOKEN=tok\n'
    assert strip(fw) == 1 and card.files[INI] == b'[LISTENBRAINZ]\nSECRETS=1\n[LASTFM]\nUSER=u\nPASSWORD=p&w\nAPI_KEY=key\n'
