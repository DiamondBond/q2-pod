#!/usr/bin/env python3
"""Release failure paths without network access or proprietary firmware."""
import json
import pathlib
import subprocess
import tempfile
from unittest.mock import patch
import sys; sys.path.insert(0, sys.path[0] + '/../tools')  # tools/ first: test/build.py must import tools/build.py
import release

with tempfile.TemporaryDirectory() as tmp:
    out = pathlib.Path(tmp)/'package'
    # This version's changelog entry, in the format since V7.7; older entries are history.
    (pathlib.Path(tmp)/'docs').mkdir()
    (pathlib.Path(tmp)/'docs/changelog.md').write_text(
        f'# Changelog\n\n- **V{release.VERSION}**: One. iPod: two.\n- **V7.6R / V7.6I**: Old.\n')
    patch('release.ROOT', pathlib.Path(tmp)).start()
    def fail_ipod(stock, directory, logo, ipod=False):
        if ipod:
            raise ValueError('simulated ipod build failure')
        directory.mkdir()
        (directory/'update.tar').write_bytes(b'stock')
        (directory/'manifest.json').write_text('{}')
    with patch('release.build', side_effect=fail_ipod), patch('release.validate'), patch('release.run', return_value='revision'):
        try:
            release.package(pathlib.Path('stock.zip'), out)
        except ValueError as e:
            assert 'ipod build failure' in str(e)
        else:
            raise AssertionError('Accepted a failed variant')
    assert not (out/'release.json').exists()
    assets = {}
    for variant, name in release.ASSETS.items():
        d = out/variant
        d.mkdir(exist_ok=True)
        (d/'update.tar').write_bytes(variant.encode())
        (d/'manifest.json').write_text(json.dumps(dict(
            variant=variant, version=release.VERSIONS[variant], update_sha256=release.sha(variant.encode()))))
        data = release.archive_bytes(d)
        (out/name).write_bytes(data)
        assets[name] = release.sha(data)
    record = dict(tag=release.VERSION, revision='revision', source_sha256=release.source_sha256(), assets=assets)
    (out/'release.json').write_text(json.dumps(record))
    (out/'release-notes.md').write_text(release.release_body(out, record))
    # The heading, then bullets, for this version only.
    body = (out/'release-notes.md').read_text()
    assert body.startswith(f'**V{release.VERSION}**\n- One.\n- iPod: two.\n\nSHA-256:\n- {release.ASSETS["ipod"]}: ')
    assert release.ASSETS['ipod'] == f'Q2.Firmware.V{release.VERSION}.zip'
    (out/'SHA256SUMS').write_text(''.join(f'{v}  {k}\n' for k, v in assets.items()))
    for failure in ('upload', 'download', 'corrupt', None):
        calls = []
        def gh(*args):
            calls.append(args)
            command = args[4]
            if command == 'list': return '[]'
            if command == failure:
                raise subprocess.CalledProcessError(1, args)
            if command == 'download':
                target = pathlib.Path(args[-1])
                for name in assets:
                    (target/name).write_bytes((out/name).read_bytes() if failure != 'corrupt' else b'bad')
            return ''
        with patch('release.run', side_effect=gh):
            try:
                release.upload(out, 'owner/repo', True)
            except (ValueError, subprocess.CalledProcessError):
                assert failure
            else:
                assert failure is None
        assert any('--draft=false' in c for c in calls) == (failure is None)
    # A missing variant must fail before contacting GitHub.
    (out/release.ASSETS['ipod']).unlink()
    with patch('release.run') as gh:
        try: release.upload(out, 'owner/repo')
        except OSError: pass
        else: raise AssertionError('Accepted a missing variant')
        gh.assert_not_called()
print('Dual-variant build/upload failure checks passed.')
