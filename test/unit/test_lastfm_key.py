"""tools/lastfm_key.py with no Last.fm: a stand-in urlopen answers, and every account here is made up."""
import email.message
import hashlib
import http.client
import io
import os
import stat
import urllib.error
import urllib.parse

import pytest

import lastfm_key

FILE = ('[SCROBBLE]\nAUTO=1\nPASSWORD=not-this-one\n\n'
        '[LASTFM]\nUSER=q2listener\nPASSWORD=Example Pass&word\nAPI_KEY=0123abcd\nAPI_SECRET=fedc9876\n\n'
        '[LISTENBRAINZ]\nTOKEN=1234-abcd\n')
KEY = 'd580d57f32848f5dcf574d1ce18d78b2'
TOKEN = '0123456789abcdef0123456789abcdef'
KEYED = FILE.replace('PASSWORD=Example Pass&word', f'SESSION_KEY={KEY}')
OK = b'{"session":{"subscriber":0,"name":"q2listener","key":"' + KEY.encode() + b'"}}'
ODD = 'its answer was not the one expected'


class Net:
    """urlopen: each request as (url, its form's pairs, timeout); the reply's bytes, or the exception raised."""
    def __init__(self, reply=OK, token_reply=b'{"token":"' + TOKEN.encode() + b'"}'):
        self.reply, self.token_reply, self.calls = reply, token_reply, []

    def __call__(self, request, timeout=None):
        pairs = urllib.parse.parse_qsl(request.data.decode(), strict_parsing=True)
        self.calls.append((request.full_url, pairs, timeout))
        reply = self.token_reply if dict(pairs)['method'] == 'auth.getToken' else self.reply
        if isinstance(reply, urllib.error.HTTPError):
            reply.fp.seek(0)  # a parametrized refusal is one object, read again in each of mutmut's sessions and forks
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(reply)


def refusal(text=b'{"message":"Authentication Failed - You do not have permissions to access the service","error":4}'):
    return urllib.error.HTTPError(lastfm_key.URL, 403, 'Forbidden', email.message.Message(), io.BytesIO(text))


class Cut(io.BytesIO):
    """A refusal whose body can't be read."""
    def read(self, *_):
        raise ConnectionResetError('connection reset')


@pytest.fixture(autouse=True)
def browser(monkeypatch):
    opened = []
    monkeypatch.setattr(lastfm_key.webbrowser, 'open', opened.append)
    return opened


def run(tmp_path, text, net=None):
    """Return the file, network calls and prompts from one run on a card."""
    path, net, asked = tmp_path/'.scrobble.ini', net or Net(), []
    path.write_bytes(text.encode('utf-8', 'surrogateescape'))
    lastfm_key.main(['lastfm_key.py', str(path)], net, asked.append)
    return path.read_bytes().decode('utf-8', 'surrogateescape'), net, asked


def left(tmp_path):
    return sorted(p.name for p in tmp_path.iterdir())


# The file.

def test_fields_are_every_last_fm_section_s_lines_trimmed():
    lines = ['[OTHER]\n', 'USER=no\n', ' [LASTFM] \r\n', ' USER = me \n', 'note\n', 'API_KEY=a=b\n', 'USER=later\n',
             '[NEXT]\n', 'API_SECRET=no\n', '[LASTFM]\n', 'PASSWORD=second section\n']
    assert lastfm_key.fields(lines) == (2, [(3, 'USER', 'me'), (5, 'API_KEY', 'a=b'), (6, 'USER', 'later'),
                                            (10, 'PASSWORD', 'second section')])
    assert lastfm_key.fields(['USER=x\n']) == (None, [])


def test_the_key_takes_the_password_s_line_and_every_other_byte_stays():
    assert lastfm_key.swap(FILE, KEY) == KEYED
    assert lastfm_key.swap(FILE.replace('\n', '\r\n'), KEY) == KEYED.replace('\n', '\r\n')


def test_with_no_password_line_the_key_goes_under_the_heading():
    bare = FILE.replace('PASSWORD=Example Pass&word\n', '')
    assert lastfm_key.swap(bare, KEY) == bare.replace('[LASTFM]\n', f'[LASTFM]\nSESSION_KEY={KEY}\n')


def test_a_new_key_replaces_the_old_one_and_a_password_beside_it_goes():
    both = FILE.replace('API_SECRET=fedc9876\n', 'API_SECRET=fedc9876\nSESSION_KEY=old\n')
    assert lastfm_key.swap(both, KEY) == KEYED
    last = '[LASTFM]\nUSER=u\nSESSION_KEY=old'  # no line ending after it
    assert lastfm_key.swap(last, KEY) == f'[LASTFM]\nUSER=u\nSESSION_KEY={KEY}\n'


def test_every_password_line_of_last_fm_goes_a_repeated_one_and_a_second_section_s_too():
    twice = (FILE.replace('API_KEY=0123abcd\n', 'API_KEY=0123abcd\nPASSWORD=Example Pass&word\n')
             + '\n[LASTFM]\nPASSWORD=Example Pass&word\nNOTE=kept\n')
    assert lastfm_key.swap(twice, KEY) == KEYED + '\n[LASTFM]\nNOTE=kept\n'  # [SCROBBLE]'s is not Last.fm's


# The call.

def test_the_form_is_signed_as_last_fm_and_the_q2_sign_it():
    pairs = urllib.parse.parse_qsl(lastfm_key.form({'method': 'm', 'username': 'u é', 'api_key': 'k&='}, 'sec').decode(),
                                   strict_parsing=True)
    *signed, sig, fmt = pairs
    assert signed == [('api_key', 'k&='), ('method', 'm'), ('username', 'u é')] and fmt == ('format', 'json')
    assert sig == ('api_sig', hashlib.md5('api_keyk&=methodmusernameu ésec'.encode()).hexdigest())


def test_a_byte_that_is_not_utf_8_is_signed_and_sent_as_the_q2_sends_it():
    password = b'caf\xe9'.decode('utf-8', 'surrogateescape')  # Latin-1 in the file
    body = lastfm_key.form({'password': password}, 's')
    assert body.startswith(b'password=caf%E9&api_sig=' + hashlib.md5(b'passwordcaf\xe9s').hexdigest().encode())


def test_the_browser_approval_precedes_the_signed_session_request(tmp_path, browser):
    path, net = tmp_path/'.scrobble.ini', Net()
    path.write_text(FILE)

    def approve(prompt):
        assert 'Enter' in prompt and len(net.calls) == 1
        assert browser == [f'https://www.last.fm/api/auth/?api_key=0123abcd&token={TOKEN}']
        assert path.read_text() == FILE

    lastfm_key.main(['lastfm_key.py', str(path)], net, approve)
    calls = [{'method': 'auth.getToken', 'api_key': '0123abcd'},
             {'method': 'auth.getSession', 'api_key': '0123abcd', 'token': TOKEN}]
    assert len(net.calls) == 2
    for (url, pairs, timeout), params in zip(net.calls, calls):
        assert url == 'https://ws.audioscrobbler.com/2.0/' and timeout == 30
        assert urllib.parse.urlencode(pairs).encode() == lastfm_key.form(params, 'fedc9876')


@pytest.mark.parametrize('key', ('a', 'Ab_9-' * 12 + 'xyz'))  # to the 63 characters the Q2 keeps of one it fetches
def test_a_key_of_letters_digits_dash_and_underscore_is_taken(key):
    assert lastfm_key.auth_key('k', 's', Net(b'{"session":{"key":"%s"}}' % key.encode()), TOKEN) == key


@pytest.mark.parametrize('reply, said', (
    (refusal(), 'Last.fm gave no session key: Authentication Failed - You do not have permissions to access the service'),
    (refusal(b'<html>busy</html>'), f'Last.fm gave no session key: {ODD}'),
    (b'{"session":{"name":"q2listener"}}', f'Last.fm gave no session key: {ODD}'),
    (b'{"session":{"key":""}}', f'Last.fm gave no session key: {ODD}'),
    (b'{"session":{"key":7}}', f'Last.fm gave no session key: {ODD}'),
    (b'["session"]', f'Last.fm gave no session key: {ODD}'),
    # a key that would not sit on one line of the file as one value, or that the Q2 would cut
    (b'{"session":{"key":"abc\\nPASSWORD=x"}}', f'Last.fm gave no session key: {ODD}'),
    (b'{"session":{"key":"ab=cd"}}', f'Last.fm gave no session key: {ODD}'),
    (b'{"session":{"key":"' + b'a' * 64 + b'"}}', f'Last.fm gave no session key: {ODD}'),
    (b'{"error":29,"message":"Rate Limit Exceeded"}', 'Last.fm gave no session key: Rate Limit Exceeded'),
    (b'{"error":4,"message":"bad\\u001b[31m"}', f'Last.fm gave no session key: {ODD}'),  # nothing unprintable is shown
    (b'{"error":4,"message":["x"]}', f'Last.fm gave no session key: {ODD}'),
    (b'{"error":4,"message":"' + b'm' * 300 + b'"}', 'Last.fm gave no session key: ' + 'm' * 200),
    # only the first 64 KB of an answer are read: these are whole, and a key and a reason, past that
    (b'{"session":{"key":"' + KEY.encode() + b'"},"pad":"' + b'x' * (1 << 16) + b'"}', f'Last.fm gave no session key: {ODD}'),
    (refusal(b'{"message":"Rate Limit Exceeded","pad":"' + b'x' * (1 << 16) + b'"}'), f'Last.fm gave no session key: {ODD}'),
    (urllib.error.URLError('no route to host'), "Couldn't reach Last.fm: no route to host"),
    (TimeoutError('timed out'), "Couldn't reach Last.fm: timed out"),
    (http.client.IncompleteRead(b'{"sess'), "Couldn't reach Last.fm: IncompleteRead(6 bytes read)"),
    (urllib.error.HTTPError(lastfm_key.URL, 403, 'Forbidden', email.message.Message(), Cut()),
     "Couldn't reach Last.fm: connection reset")))
def test_no_key_says_why(reply, said):
    with pytest.raises(SystemExit) as e:
        lastfm_key.auth_key('k', 's', Net(reply), TOKEN)
    assert str(e.value) == said


# The whole run.

def test_a_run_swaps_the_file_s_password_for_the_key_after_approval(tmp_path, capsys):
    after, _, asked = run(tmp_path, FILE)
    assert after == KEYED and len(asked) == 1
    assert left(tmp_path) == ['.scrobble.ini']  # no .tmp left
    out, err = capsys.readouterr()
    assert 'SESSION_KEY is in, and the PASSWORD lines are out of [LASTFM].' in out and not err
    assert f'https://www.last.fm/api/auth/?api_key=0123abcd&token={TOKEN}' in out
    assert KEY not in out and 'Example' not in out and 'fedc9876' not in out  # neither secret nor the key is shown


def test_an_api_key_and_secret_are_enough_to_link_an_account(tmp_path):
    bare = FILE.replace('USER=q2listener\nPASSWORD=Example Pass&word\n', '')
    assert run(tmp_path, bare)[0] == bare.replace('[LASTFM]\n', f'[LASTFM]\nSESSION_KEY={KEY}\n')


def test_a_key_s_first_line_is_the_one_used_as_on_the_q2(tmp_path):
    _, net, _ = run(tmp_path, FILE.replace('API_KEY=0123abcd\n', 'API_KEY=0123abcd\nAPI_KEY=other\n'))
    assert dict(net.calls[0][1])['api_key'] == '0123abcd'


def test_a_byte_that_is_not_utf_8_elsewhere_in_the_file_goes_back_as_it_came(tmp_path):
    odd = b'[NOTES]\nNAME=caf\xe9\n'.decode('utf-8', 'surrogateescape') + FILE
    assert run(tmp_path, odd)[0] == odd.replace('PASSWORD=Example Pass&word', f'SESSION_KEY={KEY}')


def test_the_new_file_is_its_owner_s_alone_until_it_is_whole_then_has_the_old_one_s_mode(tmp_path, monkeypatch):
    seen, replace = [], os.replace
    monkeypatch.setattr(lastfm_key.os, 'replace', lambda a, b: (seen.append(stat.S_IMODE(os.stat(a).st_mode)), replace(a, b)))
    path = tmp_path/'.scrobble.ini'
    path.write_text(FILE)
    path.chmod(0o640)
    (tmp_path/'.scrobble.ini.tmp').write_text('left by something else')  # replaced, not written through
    (tmp_path/'.scrobble.ini.tmp').chmod(0o666)
    lastfm_key.main(['lastfm_key.py', str(path)], Net(), lambda _: '')
    assert seen == [0o600] and stat.S_IMODE(path.stat().st_mode) == 0o640
    assert path.read_text() == KEYED and left(tmp_path) == ['.scrobble.ini']


def test_a_link_to_the_file_has_the_file_it_names_changed_and_stays_a_link(tmp_path):
    (tmp_path/'card').mkdir()
    (tmp_path/'card/.scrobble.ini').write_text(FILE)
    (tmp_path/'link.ini').symlink_to(tmp_path/'card/.scrobble.ini')
    lastfm_key.main(['lastfm_key.py', str(tmp_path/'link.ini')], Net(), lambda _: '')
    assert (tmp_path/'link.ini').is_symlink() and (tmp_path/'card/.scrobble.ini').read_text() == KEYED
    assert left(tmp_path) == ['card', 'link.ini'] and left(tmp_path/'card') == ['.scrobble.ini']


# What goes wrong leaves the file as it was.

@pytest.mark.parametrize('text, said', (
    (FILE.replace('API_SECRET=fedc9876\n', ''), '[LASTFM] needs API_SECRET'),
    (FILE.replace('API_KEY=0123abcd\n', ''), '[LASTFM] needs API_KEY'),
    ('[LISTENBRAINZ]\nTOKEN=1234-abcd\n', '[LASTFM] needs API_KEY, API_SECRET')))
def test_a_file_missing_a_field_is_named_and_nothing_is_sent(tmp_path, text, said):
    net = Net()
    with pytest.raises(SystemExit) as e:
        run(tmp_path, text, net)
    assert str(e.value) == f"{os.path.realpath(tmp_path/'.scrobble.ini')}: {said}" and not net.calls


def test_a_file_that_can_t_be_read_says_so_and_nothing_is_sent(tmp_path):
    net = Net()
    with pytest.raises(SystemExit) as e:
        lastfm_key.main(['lastfm_key.py', str(tmp_path/'none.ini')], net, None)
    assert str(e.value) == f"Can't read {os.path.realpath(tmp_path/'none.ini')}: No such file or directory"
    assert not net.calls and not left(tmp_path)


def test_a_refusal_leaves_the_file_as_it_was(tmp_path):
    with pytest.raises(SystemExit):
        run(tmp_path, FILE, Net(refusal()))
    assert (tmp_path/'.scrobble.ini').read_text() == FILE and left(tmp_path) == ['.scrobble.ini']


def test_a_missing_request_token_stops_before_opening_the_browser(tmp_path, browser):
    net = Net(token_reply=b'{"token":null}')
    with pytest.raises(SystemExit, match='no request token'):
        run(tmp_path, FILE, net)
    assert not browser and len(net.calls) == 1 and (tmp_path/'.scrobble.ini').read_text() == FILE


@pytest.mark.parametrize('call, error, said', (
    ('open', OSError(28, 'No space left on device'), 'No space left on device'),  # the new file can't be made
    ('fsync', OSError(5, 'Input/output error'), 'Input/output error'),  # or written whole
    ('replace', PermissionError(13, 'Permission denied'), 'Permission denied'),  # or put in the old one's place
    ('replace', OSError('card gone'), 'card gone')))
def test_a_new_file_that_can_t_be_written_leaves_the_old_one_and_no_copy_of_the_key(tmp_path, monkeypatch, call, error, said):
    def fail(*_, **__):
        raise error
    monkeypatch.setattr(lastfm_key.os, call, fail)
    with pytest.raises(SystemExit) as e:
        run(tmp_path, FILE)
    monkeypatch.undo()
    assert str(e.value) == (f"{os.path.realpath(tmp_path/'.scrobble.ini')} is as it was: "
                            f"the new file couldn't be written ({said})")
    assert (tmp_path/'.scrobble.ini').read_text() == FILE and left(tmp_path) == ['.scrobble.ini']


def test_a_mode_that_can_t_be_put_back_is_no_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(lastfm_key.os, 'chmod', lambda *_: (_ for _ in ()).throw(PermissionError(1, 'Operation not permitted')))
    assert run(tmp_path, FILE)[0] == KEYED


@pytest.mark.parametrize('argv', (['lastfm_key.py'], ['lastfm_key.py', 'a', 'b']))
def test_any_other_command_line_gets_the_usage(argv):
    with pytest.raises(SystemExit) as e:
        lastfm_key.main(argv, Net(), None)
    assert str(e.value) == lastfm_key.__doc__ and 'python3 lastfm_key.py /path/to/card/.scrobble.ini' in lastfm_key.__doc__
