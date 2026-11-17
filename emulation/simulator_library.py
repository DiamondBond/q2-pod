"""Library menu order and SD card discovery for the desktop simulator."""
import re
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from simulator_apps import card_path


class LibraryRow(NamedTuple):
    name: str
    route: str
    tracks: tuple[int, ...] = ()


# patch/home.c preserves the stock order for Shanling firmware.
STOCK_LIBRARY = tuple(LibraryRow(name, route) for name, route in (
    ('Update Library', 'scan'), ('All Songs', 'songs'), ('Album', 'albums'),
    ('Artist', 'artists'), ('Genre', 'genres'), ('Hi-Res', 'hires'),
    ('My Fav', 'rated'), ('Frequent', 'most'), ('Recent', 'recent'),
    ('Recently Added', 'added'), ('Playlist', 'playlists'),
))
POD_LIBRARY = tuple(LibraryRow(name, route) for name, route in (
    ('Shuffle', 'shuffle'), ('Artists', 'artists'), ('Albums', 'albums'),
    ('Songs', 'songs'), ('Genres', 'genres'), ('Era', 'era'), ('Playlists', 'playlists'),
    ('Ratings', 'ratings'), ('Recently Added', 'added'), ('Recent', 'recent'),
    ('Most Played', 'most'), ('Hi-Res', 'hires'), ('Long Songs', 'long'),
))
MEDIA_NAMES = ('Podcasts', 'Audiobooks', 'Photos', 'Books', 'Videos')


def card_media(card: Path | None) -> dict[str, Path]:
    if card is None:
        return {}
    try:
        names = {entry.name.casefold(): entry.name for entry in card.iterdir()}
    except OSError:
        return {}
    media = {}
    for name in MEDIA_NAMES:
        if entry := names.get(name.casefold()):
            try:
                path = card_path(card, entry)
                if path.is_dir():
                    media[name] = path
            except (OSError, ValueError):
                continue
    return media


def card_app_entries(card: Path | None, *, games: bool) -> list[tuple[str, str]]:
    if card is None:
        return []
    try:
        directories = sorted(card.iterdir())
    except OSError:
        return []
    apps = []
    for entry in directories:
        if not entry.name.startswith('.') or not re.fullmatch(r'[a-z0-9-]{1,15}', ident := entry.name[1:]):
            continue
        try:
            binary = card_path(card, f'{entry.name}/q2-{ident}')
            manifest = card_path(card, f'{entry.name}/q2app')
            if not binary.is_file() or not manifest.is_file():
                continue
            with manifest.open('rb') as source:
                fields = dict(line.split('=', 1) for line in source.read(511).decode('utf-8').splitlines()
                              if '=' in line)
        except (OSError, ValueError):
            continue
        if (fields.get('game') == '1') == games and fields.get('hidden') != '1':
            apps.append((fields.get('name') or ident, ident))
    return sorted(apps, key=lambda app: app[0].casefold())[:8]


def card_game_entries(card: Path | None) -> list[tuple[str, str]]:
    return card_app_entries(card, games=True)


def card_games(card: Path | None) -> list[str]:
    return [name for name, _ in card_game_entries(card)]


def library_menu(card: Path | None, custom: bool, classic: bool) -> list[LibraryRow]:
    if not custom:
        return list(STOCK_LIBRARY)
    rows = [LibraryRow('Search', 'search')] if classic else []
    rows.extend(POD_LIBRARY)
    rows.extend(LibraryRow(name, 'media') for name in card_media(card))
    rows.extend((LibraryRow('Games', 'games'), LibraryRow('Update Library', 'scan')))
    return rows


def imported_playlists(card: Path | None, track_paths: dict[str, int]) -> dict[str, tuple[int, ...]]:
    if card is None:
        return {}
    try:
        directory = card_path(card, '_explaylist_data')
        playlists = sorted(directory.iterdir(), key=lambda path: path.name.casefold())
    except (OSError, ValueError):
        return {}
    result = {}
    for path in playlists:
        if path.suffix.casefold() != '.m3u' or path.is_symlink() or not path.is_file():
            continue
        try:
            with path.open(encoding='utf-8-sig', errors='replace') as source:
                data = source.read((1 << 20) + 1)
        except OSError:
            continue
        if len(data) > 1 << 20:
            continue
        indices = []
        for line in data.splitlines():
            line = line.strip().replace('\\', '/')
            if not line or line.startswith('#'):
                continue
            line = re.sub(r'^[A-Za-z]:/', '', line).removeprefix('/mnt/mmc/').lstrip('/')
            index = track_paths.get(PurePosixPath(line).as_posix().casefold())
            if index is not None:
                indices.append(index)
        result[path.stem] = tuple(indices)
    return result
