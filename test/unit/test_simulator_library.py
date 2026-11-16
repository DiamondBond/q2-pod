import simulator_library as library


def test_library_uses_firmware_order_and_conditional_rows(tmp_path):
    (tmp_path / 'audiobooks').mkdir()
    (tmp_path / 'Photos').mkdir()
    (tmp_path / 'Books').write_text('not a folder')
    names = [row.name for row in library.library_menu(tmp_path, custom=True, classic=True)]
    assert names[:6] == ['Search', 'Shuffle', 'Artists', 'Albums', 'Songs', 'Genres']
    assert names[-4:] == ['Audiobooks', 'Photos', 'Games', 'Update Library']
    assert library.library_menu(tmp_path, custom=True, classic=False)[0].name == 'Shuffle'
    stock = [row.name for row in library.library_menu(tmp_path, custom=False, classic=False)]
    assert stock[:3] == ['Update Library', 'All Songs', 'Album']
    assert 'Games' not in stock


def test_games_require_a_binary_and_visible_game_manifest(tmp_path):
    def make_app(ident, manifest, binary=True):
        path = tmp_path / f'.{ident}'
        path.mkdir()
        (path / 'q2app').write_bytes(manifest)
        if binary:
            (path / f'q2-{ident}').touch()
        return path

    buddy = make_app('buddy', b'name=Buddy\r\ngame=1\r\n')
    make_app('another', b'game=1')
    make_app('no-binary', b'name=Broken\ngame=1', binary=False)
    make_app('stream', b'name=Streamer\ngame=0')
    make_app('hidden', b'name=Hidden\ngame=1\nhidden=1')
    assert library.card_games(tmp_path) == ['another', 'Buddy']
    (buddy / 'q2-buddy').unlink()
    assert library.card_games(tmp_path) == ['another']


def test_import_reads_only_card_playlists_and_preserves_the_track_order(tmp_path):
    directory = tmp_path / '_explaylist_data'
    directory.mkdir()
    (directory / 'Road Trip.m3u').write_text(
        '#EXTM3U\n/mnt/mmc/Music/second.flac\nA:\\music\\first.mp3\nMissing.flac\n', encoding='utf-8')
    paths = {'music/first.mp3': 0, 'music/second.flac': 7}
    assert library.imported_playlists(tmp_path, paths) == {'Road Trip': (7, 0)}
