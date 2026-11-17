import hashlib
import io
import threading
import zipfile
from email.message import Message

import pytest

import simulator_apps as store


def release_archive(monkeypatch, files, tag='v1'):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    raw = data.getvalue()
    monkeypatch.setattr(store, 'open_url', lambda url: io.BytesIO(raw))
    return store.Release(tag, 'https://github.com/example/download.zip', len(raw), hashlib.sha256(raw).hexdigest())


def test_install_and_update_preserve_rockbox_config(tmp_path, monkeypatch):
    app = store.parse_catalog('DiamondBond/q2-rockbox Rockbox')[0]
    config = tmp_path / '.rockbox/config.cfg'
    config.parent.mkdir()
    config.write_bytes(b'user settings')
    for tag in ('v1', 'v2'):
        release = release_archive(monkeypatch, {app.binary: tag.encode(), '.rockbox/config.cfg': b'stock'}, tag)
        stages = []
        store.install(tmp_path, app, release, threading.Event(), stages.append)
        assert stages == ['Downloading 0%', 'Downloading 100%', 'Unpacking…', 'Installing…']
        assert (tmp_path / app.binary).read_bytes() == tag.encode()
        assert store.installed_tag(tmp_path, app) == tag
        assert config.read_bytes() == b'user settings'
    store.remove(tmp_path, app, [app])
    assert not (tmp_path / app.binary).exists()
    assert not store.installed_tag(tmp_path, app)
    assert config.read_bytes() == b'user settings'


def test_cancel_app_download(tmp_path, monkeypatch):
    app = store.parse_catalog('example/q2-demo Demo')[0]
    release = release_archive(monkeypatch, {app.binary: b'payload' * 20000})
    cancel = threading.Event()
    stages = []

    def progress(stage):
        stages.append(stage)
        if stage != 'Downloading 0%':
            cancel.set()

    with pytest.raises(InterruptedError):
        store.install(tmp_path, app, release, cancel, progress)
    assert not (tmp_path / app.directory).exists()
    assert not any((tmp_path / '.q2/staging').iterdir())
    assert 'Installing…' not in stages


@pytest.mark.parametrize('name', ['../outside', '.demo/file:stream', '.demo/CON'])
def test_invalid_release_paths_refused(tmp_path, monkeypatch, name):
    app = store.parse_catalog('example/q2-demo Demo')[0]
    release = release_archive(monkeypatch, {app.binary: b'binary', name: b'extra'})
    with pytest.raises(ValueError, match='Invalid path'):
        store.install(tmp_path, app, release, threading.Event(), lambda stage: None)
    assert not (tmp_path / app.directory).exists()


def test_install_rollback_leaves_existing_app_files(tmp_path, monkeypatch):
    app = store.parse_catalog('example/q2-demo Demo')[0]
    binary = tmp_path / app.binary
    binary.parent.mkdir()
    binary.write_bytes(b'old')
    (binary.parent / 'first').write_bytes(b'old asset')
    (binary.parent / 'conflict').mkdir()
    release = release_archive(monkeypatch, {'.demo/first': b'replacement', '.demo/conflict': b'x', app.binary: b'new'})
    with pytest.raises(ValueError, match='conflicts'):
        store.install(tmp_path, app, release, threading.Event(), lambda stage: None)
    assert binary.read_bytes() == b'old'
    assert (binary.parent / 'first').read_bytes() == b'old asset'
    assert not (tmp_path / '.q2/apps/demo.tag').exists()


def test_rate_limit_uses_github_reset_time(monkeypatch):
    headers = Message()
    headers['X-RateLimit-Remaining'] = '0'
    headers['X-RateLimit-Reset'] = '1500'
    error = store.HTTPError('https://api.github.com', 403, 'Forbidden', headers, None)

    def fail(url):
        raise error

    monkeypatch.setattr(store.time, 'time', lambda: 1000)
    monkeypatch.setattr(store, 'open_url', fail)
    app = store.parse_catalog('example/q2-demo Demo')[0]
    with pytest.raises(store.GitHubRateLimit) as caught:
        store.latest_release(app)
    assert caught.value.retry_at == 1500
    assert store.rate_limit_deadline(store.HTTPError('', 403, 'Forbidden', Message(), None)) is None


def test_release_lookup_reuses_results_and_waits_before_retrying(monkeypatch):
    ui = store.AppStore('example/q2-demo Demo\nexample/q2-buddy Buddy')
    first, second = ui.apps
    release = store.Release('v1', 'https://github.com/example/download.zip', 1, None)
    now = [1000]
    calls = []

    def latest(app):
        calls.append(app)
        if app == second and now[0] < 1100:
            raise store.GitHubRateLimit(1100)
        return release

    monkeypatch.setattr(store.time, 'time', lambda: now[0])
    monkeypatch.setattr(store, 'latest_release', latest)
    assert ui.get_release(first) == release
    for _ in range(2):
        with pytest.raises(store.GitHubRateLimit):
            ui.get_release(second)
    assert ui.get_release(first) == release
    assert calls == [first, second]
    now[0] = 1101
    assert ui.get_release(second) == release
    assert calls == [first, second, second]


def test_update_check_queries_only_installed_apps(tmp_path, monkeypatch):
    ui = store.AppStore('example/q2-demo Demo\nexample/q2-buddy Buddy')
    release = store.Release('v2', 'https://github.com/example/download.zip', 1, None)
    monkeypatch.setattr(store, 'fetch_catalog', lambda: ui.apps)
    monkeypatch.setattr(store, 'installed_tag', lambda card, app: 'v1' if app.ident == 'demo' else '')
    calls = []

    def latest(app):
        calls.append(app.ident)
        return release

    jobs = []
    monkeypatch.setattr(store, 'latest_release', latest)
    monkeypatch.setattr(store.threading, 'Thread',
                        lambda target, daemon: type('Job', (), {'start': lambda self: jobs.append(target)})())
    ui.select(tmp_path, 'check')
    jobs[0]()
    assert ui.poll()
    assert calls == ['demo']
    assert ui.releases == {'demo': release}
