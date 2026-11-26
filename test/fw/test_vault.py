"""vault.c (docs/internals.md#scrobbling): the Vault card app's socket, /tmp/q2-vault.sock, through spot_exchange: one
Q2VAULT/1 request a connection, only to a socket root owns."""
import ctypes as C

import pytest

SOCK, BIN = b'/tmp/q2-vault.sock', b'/mnt/mmc/.vault/q2-vault'
S_IFSOCK, S_IFLNK, S_IFREG = 0o140000, 0o120000, 0o100000


class Vault:
    """The socket's stat, and the exchange on it: replies a script of byte strings read in turn."""
    def __init__(self, fw, replies=(), mode=S_IFSOCK, uid=0, installed=True, connect=0):
        self.sent, self.connects, self.script = b'', 0, list(replies)
        self.mode, self.uid, self.installed, self.now = mode, uid, installed, 0

        def stat(ver, path, st, *_):
            if C.string_at(path) != SOCK or self.mode is None:
                return -1
            words = C.cast(st, C.POINTER(C.c_uint))
            words[5], words[7] = self.mode, self.uid
            return 0

        def clock(which, ts, *_):
            self.now += 1
            t = C.cast(ts, C.POINTER(C.c_long))
            t[0], t[1] = self.now, 0

        def on_connect(fd, to, n, *_):
            self.connects += 1
            assert C.string_at(to + 2) == SOCK
            return connect

        def send(fd, buf, n, *_):
            self.sent += C.string_at(buf, n)
            return n

        def recv(fd, buf, n, *_):
            piece = self.script.pop(0) if self.script else b''
            piece = piece[:n]
            C.memmove(buf, piece, len(piece))
            return len(piece)

        fw.mock('fw___xstat', stat)
        fw.mock('fw_access', lambda path, *_: 0 if self.installed and C.string_at(path) == BIN else -1)
        fw.mock('fw_clock_gettime', clock)
        fw.mock('fw_socket', lambda *_: 5)
        fw.mock('fw_connect', on_connect)
        fw.mock('fw_select', lambda *_: 1)
        fw.mock('fw_send', send)
        fw.mock('fw_recv', recv)


def get(fw, size=64):
    out = C.create_string_buffer(size)
    return fw.fn('vault_get', C.c_int, C.c_char_p, C.c_uint)(out, size), out.value


def put(fw, body):
    return fw.fn('vault_put', C.c_int, C.c_char_p, C.c_uint)(body, len(body))


def test_get_ok(fw):
    v = Vault(fw, [b'Q2VAULT/1\nok\n', b'abc'])
    assert get(fw) == (1, b'abc')
    assert v.sent == b'Q2VAULT/1\nget\n'


def test_get_none(fw):
    Vault(fw, [b'Q2VAULT/1\nnone\n'])
    assert get(fw)[0] == 0


def test_put_sends_its_body(fw):
    v = Vault(fw, [b'Q2VAULT/1\nok\n'])
    assert put(fw, b'[LISTENBRAINZ]\nTOKEN=t\n') == 1
    assert v.sent == b'Q2VAULT/1\nput\n[LISTENBRAINZ]\nTOKEN=t\n'


def test_delete(fw):
    v = Vault(fw, [b'Q2VAULT/1\nok\n'])
    assert fw.fn('vault_delete', C.c_int)() == 1
    assert v.sent == b'Q2VAULT/1\ndelete\n'


@pytest.mark.parametrize('mode,uid', [(S_IFSOCK, 1000), (S_IFREG, 0), (None, 0)])
def test_a_socket_root_doesnt_own_is_never_asked(fw, mode, uid):
    v = Vault(fw, [b'Q2VAULT/1\nok\n', b'abc'], mode=mode, uid=uid)
    assert get(fw)[0] == -1 and put(fw, b'x') == -1
    assert v.connects == 0 and v.sent == b''


def test_no_connection(fw):
    Vault(fw, connect=-1)
    assert get(fw)[0] == -1


@pytest.mark.parametrize('status', [b'refused', b'card-away', b'too-large', b'bad-request', b'what'])
def test_any_other_answer_is_not_now(fw, status):
    Vault(fw, [b'Q2VAULT/1\n' + status + b'\n'])
    assert get(fw)[0] == -1
    Vault(fw, [b'Q2VAULT/1\n' + status + b'\n'])
    assert put(fw, b'x') == -1


def test_not_the_vaults_protocol(fw):
    Vault(fw, [b'Q2SPOT/1\nok\n', b'abc'])
    assert get(fw)[0] == -1


def test_a_secret_past_the_buffer_is_refused(fw):
    Vault(fw, [b'Q2VAULT/1\nok\n', b'x' * 100])
    assert get(fw, size=64)[0] == -1


def test_a_put_over_the_vaults_limit_isnt_sent(fw):
    v = Vault(fw, [b'Q2VAULT/1\nok\n'])
    assert put(fw, b'x' * 16385) == -1 and v.connects == 0


def test_installed(fw):
    Vault(fw, installed=True)
    assert fw.fn('vault_installed', C.c_int)() == 1
    Vault(fw, installed=False)
    assert fw.fn('vault_installed', C.c_int)() == 0
