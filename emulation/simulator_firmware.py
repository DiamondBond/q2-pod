"""Read the Q2 Now Playing assets directly from Shanling and Q2 Pod update packages."""

import re
import shutil
import struct
import sys
import subprocess
import tarfile
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

sys.path.append(str(Path(__file__).resolve().parents[1] / "tools"))

import ipod
from game_catalog import LEGACY_NAMES, manifest_names

RAW = 'release/assets/default/raw/'
ROOTFS = 'recovery-update/rootfs.squashfs'
DEMO = 'release/bin/demo'
BUILTIN_GAMES = LEGACY_NAMES
GAME_MANIFEST = 'release/assets/default/raw/q2pod-games.json'
FONT_FILES = ('default', 'bold', 'classic-light', 'folder-regular')


@dataclass(frozen=True)
class Widget:
    kind: str
    box: tuple[int, int, int, int]
    props: dict[str, str]

    def style_value(self, styles, name):
        return self.props.get(f'style:normal:{name}', styles.get(
            (self.kind, self.props.get('style', 'default'), name)))


@dataclass(frozen=True)
class HomeEntry:
    key: str
    label: str
    image: str
    row: Widget
    text: Widget
    art: Widget


@dataclass(frozen=True)
class Firmware:
    version: str
    custom: bool
    page: dict[str, Widget]
    fonts: dict[str, bytes]
    images: dict[str, bytes]
    styles: dict[tuple[str, str, str], bytes]
    home: tuple[HomeEntry, ...]
    lists: dict[str, dict[str, Widget]]
    playing_layouts: dict[str, dict[str, Widget]] = field(default_factory=dict)

    builtin_games: tuple[str, ...] = BUILTIN_GAMES
    game_manifest_found: bool = False

    def now_playing(self, geometry):
        if self.custom and geometry in self.playing_layouts:
            return self.playing_layouts[geometry]
        return self.page

    @property
    def name(self):
        return f'{"Q2 Pod" if self.custom else "Shanling Q2"} {self.version}'


@contextmanager
def update_file(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            candidates = [entry for entry in archive.infolist()
                          if not entry.is_dir() and PurePosixPath(entry.filename).name == 'update.tar']
            if len(candidates) != 1:
                raise ValueError('The ZIP must contain exactly one update.tar')
            with archive.open(candidates[0]) as update:
                yield update
    else:
        with path.open('rb') as update:
            yield update


def read_rootfs(path, target):
    with update_file(path) as update, tarfile.open(fileobj=update, mode='r|*') as archive:
        version = None
        for member in archive:
            if member.name not in ('firmware_v20.info', ROOTFS):
                continue
            content = archive.extractfile(member) if member.isfile() else None
            if content is None:
                raise ValueError(f'Expected a regular file: {member.name}')
            if member.name == 'firmware_v20.info':
                if member.size > 4096:
                    raise ValueError('Invalid firmware_v20.info')
                with content:
                    lines = content.read().decode('utf-8').splitlines()
                if len(lines) < 2 or lines[0] != 'Shanling Q2' or not lines[1].strip():
                    raise ValueError('This package is not a Shanling Q2 firmware update')
                version = lines[1].strip()
            else:
                if member.size < 96:
                    raise ValueError('Invalid SquashFS member')
                with content, target.open('wb') as output:
                    if content.read(4) != b'hsqs':
                        raise ValueError('The firmware root filesystem is not SquashFS')
                    output.write(b'hsqs')
                    shutil.copyfileobj(content, output)
        if version is None or not target.is_file():
            raise ValueError('The update needs firmware_v20.info and recovery-update/rootfs.squashfs')
        return version


def page_widgets(data, page_name, required=()):
    root = ipod.decode(data)
    if root[2].get('name') != page_name:
        raise ValueError(f'Unexpected AWTK page (expected {page_name})')
    widgets = {}

    def visit(node, left=0, top=0):
        kind, (x, y, w, h), props, children = node
        name = props.get('name')
        if name:
            widgets[name] = Widget(kind, (left + x, top + y, w, h), props)
        for child in children:
            visit(child, left + x, top + y)

    visit(root)
    for name in required:
        widget = widgets.get(name)
        if not widget or not all(0 < size <= 4096 for size in widget.box[2:]):
            raise ValueError(f'Missing or unsupported widget in {page_name}: {name}')
    return widgets


def home_entries(data, custom):
    root = ipod.decode(data)
    names = {'playing': 'Now Playing', 'localmusic': 'Library' if custom else 'Local Music',
             'coverflow': 'Cover Flow' if custom else 'Album Wall', 'folder': 'Folders',
             'rockbox': 'Rockbox', 'stream': 'Streaming', 'settings': 'Settings',
             'playset': 'Playback Settings', 'sysset': 'System Settings'}
    menu = next((node for node in root[3] if node[2].get('name') == 'slide_menu'), None)
    listing = next((node for node in root[3] if node[2].get('name') == 'list_view_home'), None)
    if menu is None:
        raise ValueError('Missing Home menu layout')
    cards = {node[2]['name']: node for node in menu[3] if 'name' in node[2]}
    if custom:
        if listing is None:
            raise ValueError('Missing Q2 Pod Home list')
        rows, top = listing[3][0][3], listing[1][1]
    else:
        rows, top = menu[3], 0
    entries = []
    for row in rows:
        key = row[2].get('name', '').removeprefix('btn_')
        if key not in names:
            continue
        label = next(child for child in row[3] if child[0] in ('label', 'hscroll_label'))
        card = cards.get(f'btn_{key}')
        art = next((child for child in card[3] if child[0] == 'image'), None) if card else None
        art_widget = (Widget(art[0], tuple(art[1]), art[2]) if art is not None else
                      Widget('image', (0, 0, 0, 0), {}))
        x, y, w, h = row[1]
        entries.append(HomeEntry(key, names[key], art_widget.props.get('style:normal:bg_image', ''),
                                 Widget(row[0], (x, y + top, w, h), row[2]),
                                 Widget(label[0], tuple(label[1]), label[2]),
                                 art_widget))
    if not entries:
        raise ValueError('Home menu has no supported rows')
    return tuple(entries)


def firmware_builtin_games(demo):
    # Existing Q2 Pod packages keep the chooser in the compiled payload.
    # Require both the menu label and the save path to identify newer games.
    if b'Breakout\0' in demo and b'/mnt/data/ringnav-breakout\0' in demo:
        return (*BUILTIN_GAMES, 'Breakout')
    return BUILTIN_GAMES


def load_firmware(path, unsquashfs='unsquashfs'):
    """Materialize just the filesystem image, then read named assets without extracting a tree."""
    try:
        with tempfile.TemporaryDirectory(prefix='q2-simulator-') as directory:
            rootfs = Path(directory) / 'rootfs.squashfs'
            version = read_rootfs(path, rootfs)

            def run(*args):
                result = subprocess.run([unsquashfs, *args], capture_output=True, check=True)
                return result.stdout

            files = {line.removeprefix('squashfs-root/') for line in
                     run('-ls', str(rootfs)).decode('utf-8', errors='replace').splitlines()}

            def read(name):
                key = RAW + name
                if key not in files:
                    raise ValueError(f'Firmware is missing {key}')
                return run('-cat', '-no-wildcards', str(rootfs), key)

            fonts = {name: read(f'fonts/{name}.ttf') for name in FONT_FILES
                     if name == 'default' or RAW + f'fonts/{name}.ttf' in files}
            required = ('scrlabel_title', 'scrlabel_artist', 'img_cover', 'slider_play')
            page = page_widgets(read('ui/playing_page.bin'), 'playing_page', required)
            custom = (RAW + f'ui/{ipod.PLAYING_STOCK}' in files or 'label_ipod_album' in page)
            playing_layouts = {}
            if custom:
                for key in sorted(files):
                    match = re.fullmatch(re.escape(RAW) + r'ui/([a-z0-9-]+)_playing_page\.bin', key)
                    if match:
                        playing_layouts[match[1]] = page_widgets(
                            read(key.removeprefix(RAW)), 'playing_page', required)
            home = home_entries(read('ui/home_page.bin'), custom)
            lists = {'folder': page_widgets(read('ui/folder_page.bin'), 'folder_page')}
            library = 'ui/localmusic/allmusic_page.bin'
            if RAW + library in files:
                lists['localmusic'] = page_widgets(read(library), 'allmusic_page')
            styles = {}
            if RAW + 'styles/default.bin' in files:
                styles = {(kind, style, prop): value for kind, style, state, prop, _, value in
                          ipod.style_props(read('styles/default.bin')) if state == 'normal'}
            names = {'play_plandot', 'play_bigplay', 'play_bigpause', 'play_return',
                     'default_album_flow', 'default_album_coverflow', 'default_album_big',
                     'bar_battery', 'bar_charge', 'bar_lowcharge', 'bar_wifi4', 'classic_light_bolt'}
            names.update(entry.image for entry in home)
            for layout in (page, *playing_layouts.values()):
                for widget in layout.values():
                    for value in (widget.props.get('image'), widget.style_value(styles, 'bg_image'),
                                  widget.style_value(styles, 'fg_image')):
                        if isinstance(value, bytes):
                            value = value.rstrip(b'\0').decode('utf-8')
                        if value:
                            names.add(value)
            images = {name: read(f'images/xx/{name}.png') for name in names
                      if re.fullmatch(r'[A-Za-z0-9_-]+', name) and RAW + f'images/xx/{name}.png' in files}
            games = ()
            manifest_found = False
            if custom:
                if GAME_MANIFEST in files:
                    manifest_found = True
                    games = manifest_names(run('-cat', '-no-wildcards', str(rootfs), GAME_MANIFEST))
                else:
                    demo = run('-cat', '-no-wildcards', str(rootfs), DEMO) if DEMO in files else b''
                    games = firmware_builtin_games(demo)
            return Firmware(version, custom, page, fonts, images, styles, home, lists, playing_layouts, games, manifest_found)
    except FileNotFoundError as exc:
        if exc.filename == unsquashfs:
            raise ValueError('Install squashfs-tools or pass --unsquashfs with the executable path') from exc
        raise
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors='replace').strip()
        raise ValueError(f'Could not read firmware SquashFS with unsquashfs: {detail or exc.returncode}') from exc
    except (tarfile.TarError, zipfile.BadZipFile, struct.error, IndexError, StopIteration, RecursionError, RuntimeError) as exc:
        raise ValueError(f'Invalid Q2 firmware package or assets: {exc}') from exc
