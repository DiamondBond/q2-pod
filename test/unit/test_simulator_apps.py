import hashlib
import io
import threading
import zipfile

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
