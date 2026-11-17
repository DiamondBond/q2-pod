#!/usr/bin/env python3
# mypy: disable-error-code="import-not-found,import-untyped"
"""Interactive desktop UI preview for Shanling Q2 and Q2 Pod firmware."""
import argparse
import bisect
import io
import math
import random
import subprocess
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError
from mutagen import File, MutagenError
from mutagen.id3 import APIC
from PIL import Image, ImageDraw, ImageFont, ImageOps

sys.path.append(str(Path(__file__).resolve().parents[1] / "tools"))

import art
import build
import ipod
import theme
from simulator_apps import AppStore
from simulator_audio import FFplayAudio
from simulator_device import (CENTRE, DEFAULT_SHELL, DETENT, DEVICE_SIZE, SCREEN_AT, SHELL_FINISHES, WHEEL,
                              device_frame, wheel_angle, wheel_button, wheel_delta)
from simulator_firmware import BUILTIN_GAMES, load_firmware
from game_catalog import checkout_can_preview
from simulator_library import (MEDIA_NAMES, LibraryRow, card_app_entries, card_game_entries, card_media, imported_playlists,
                               library_menu)
from simulator_settings import PAGES, PLAY_MODES, SETTINGS, STOCK_ROWS, THEME_KEYS

SIZE = (375, 320)
THEMES = ('classic-light', 'modern', 'minimal')
FACES = ('default', 'bold', 'classic-light')
ERRORS = (OSError, ValueError, MutagenError, TTLibError)
TIMESTAMP = re.compile(r'\[(\d+):([0-5]\d)(?:[.:](\d{1,3}))?\]')


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    album: str
    art: bytes | None = None
    filename: str = ''
    path: Path | None = None
    album_artist: str = ''
    duration: float = 0.0
    lyrics: tuple[tuple[float, str], ...] = ()
    genres: tuple[str, ...] = ()
    year: int = 0
    disc: int = 0
    number: int = 0
    hi_res: bool = False
    modified: float = 0


def read_lyrics(path):
    try:
        data = path.with_suffix('.lrc').read_bytes()
        source = data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
    except (OSError, UnicodeError):
        return ()
    offset = re.search(r'^\[offset:([+-]?\d+)\]', source, re.MULTILINE | re.IGNORECASE)
    delay = int(offset[1]) / 1000 if offset else 0
    stamps = []
    for line in source.splitlines():
        for match in TIMESTAMP.finditer(line):
            minutes, seconds, fraction = match.groups()
            seconds = int(minutes) * 60 + int(seconds) + float('0.' + (fraction or '0'))
            text = TIMESTAMP.sub('', line).strip()
            stamps.append((max(0, seconds + delay), unicodedata.normalize('NFC', text)))
    return tuple(sorted(stamps, key=lambda entry: entry[0]))


SAMPLES = (
    Track('Thử ư â ă — Mưa Trên Phố Huế', 'Nguyễn Thị Hương', 'Kỷ Niệm Mùa Thu',
          filename='1. a\u0309.flac', duration=257,
          lyrics=((0, 'Thử hiển thị tiếng Việt'), (8, 'Ngày ấy đôi môi đậm đà'), (18, 'Mưa rơi trên phố Huế'))),
    Track('夜の音楽', 'アーティスト', 'アルバム', filename='夜の音楽.flac'),
    Track('Lo que la música me enseñó', 'Artista', 'Álbum', filename='Álbum.mp3'),
)


def read_track(path):
    path = Path(path)
    audio = File(path, easy=True)
    if audio is None:
        raise ValueError(f'Unsupported audio file: {path}')
    tags = audio.tags or {}
    raw = File(path)
    if raw is None:
        raise ValueError(f'Unsupported audio file: {path}')
    pictures = getattr(raw, 'pictures', ())
    art = pictures[0].data if pictures else next(
        (getattr(tag, 'data', None) for tag in (raw.tags or {}).values() if isinstance(tag, APIC)), None)
    if art is None:
        for name in ('cover.jpg', 'folder.jpg', 'cover.png'):
            candidate = path.with_name(name)
            try:
                if candidate.stat().st_size <= 12 * 1024 * 1024:
                    art = candidate.read_bytes()
                    break
            except OSError:
                continue
    title = (tags.get('title') or [path.stem])[0]
    artist = (tags.get('artist') or [''])[0]
    album = (tags.get('album') or [''])[0]
    album_artist = (tags.get('albumartist') or [''])[0]
    def number(key, size):
        value = re.match(rf'[0-9]{{1,{size}}}', (tags.get(key) or [''])[0])
        return int(value[0]) if value else 0

    return Track(title, artist, album, art, path.name, path.resolve(), album_artist,
                 float(getattr(audio.info, 'length', 0)), read_lyrics(path),
                 tuple(tags.get('genre') or ()), number('date', 4), number('discnumber', 3),
                 number('tracknumber', 4), int(getattr(audio.info, 'bits_per_sample', 0)) > 16 and
                 int(getattr(audio.info, 'sample_rate', 0)) > 48000, path.stat().st_mtime)


def scan_card(root):
    if not root.is_dir():
        raise ValueError(f'Choose an existing SD card folder: {root}')
    tracks, failures = [], []
    for path in sorted(root.rglob('*'), key=lambda item: str(item.relative_to(root)).casefold()):
        if path.suffix.lower() not in ('.mp3', '.flac') or path.is_symlink() or not path.is_file():
            continue
        try:
            tracks.append(read_track(path))
        except ERRORS as exc:
            failures.append(f'{path.relative_to(root)}: {exc}')
    return tracks, failures


def folder_rows(tracks, directory):
    if directory is None:
        return [(track.filename or track.title, i) for i, track in enumerate(tracks)]
    folders: set[Path] = set()
    songs = []
    for index, track in enumerate(tracks):
        if track.path is None or not track.path.is_relative_to(directory):
            continue
        relative = track.path.relative_to(directory)
        if len(relative.parts) == 1:
            songs.append((relative.name, index))
        else:
            folders.add(directory / relative.parts[0])
    return ([(path.name, path) for path in sorted(folders, key=lambda path: path.name.casefold())] +
            sorted(songs, key=lambda song: song[0].casefold()))


@dataclass(frozen=True)
class Album:
    name: str
    artist: str
    tracks: tuple[int, ...]
    cover: int


def albums_for(tracks, sort='Album'):
    grouped = defaultdict(list)
    for i, track in enumerate(tracks):
        folder = track.path.parent if track.path else None
        if folder and re.fullmatch(r'(?:cd|disc)[ _-]*\d+', folder.name, re.IGNORECASE):
            folder = folder.parent
        name = track.album or (folder.name if folder else 'Unknown Album')
        key = track.album_artist or folder or track.artist
        grouped[name, key].append(i)
    albums = [Album(name, tracks[indices[0]].album_artist or tracks[indices[0]].artist,
                    tuple(sorted(indices, key=lambda i: (tracks[i].disc, tracks[i].number))),
                    next((i for i in indices if tracks[i].art), indices[0]))
              for (name, _key), indices in grouped.items()]
    return sorted(albums, key=lambda album: tuple(value.casefold() for value in
                  ((album.artist, album.name) if sort == 'Artist' else (album.name, album.artist))))


class Fonts:
    def __init__(self, stock=None, packaged=None, firmware=None):
        self.data = {}
        if firmware is not None:
            self.data = firmware.fonts
        else:
            for face, builder in zip(FACES[1:], (build.bold_font, build.classic_light_font)):
                path = packaged / f'{face}.ttf' if packaged else None
                self.data[face] = path.read_bytes() if path else builder()[0]
            if stock:
                self.data['default'] = stock.read_bytes()
            elif packaged and (packaged / 'default.ttf').is_file():
                self.data['default'] = (packaged / 'default.ttf').read_bytes()
        self.cmaps = {}
        for face, data in self.data.items():
            with TTFont(io.BytesIO(data)) as font:
                self.cmaps[face] = set(font.getBestCmap())

    def face(self, preferred, text, size):
        # The order and scaling follow theme_font in patch/navigation.c.
        if preferred == 'classic-light' and not self.supports(preferred, text):
            preferred, size = 'bold', (size * 83 + 50) // 100
        if preferred == 'bold' and not self.supports(preferred, text):
            preferred = 'default'
        return preferred, size

    def supports(self, face, text):
        return face in self.cmaps and all(ord(char) in self.cmaps[face] for char in text)

    def artist(self, text):
        if 'folder-regular' in self.data:
            text = unicodedata.normalize('NFC', text)
            vietnamese = any(0x1ea0 <= ord(char) <= 0x1ef9 or char in 'ĂăĐđƠơƯư' for char in text)
            if vietnamese and self.supports('folder-regular', text):
                return text, 'folder-regular'
        return text, 'default'

    @lru_cache(maxsize=32)
    def font(self, face, size):
        if face == 'default' and face not in self.data:
            return self.font('bold', size)
        with TTFont(io.BytesIO(self.data[face])) as font:
            metrics = font['hhea']
            size = size * font['head'].unitsPerEm / (metrics.ascent - metrics.descent)
        return ImageFont.truetype(io.BytesIO(self.data[face]), max(1, round(size)))


def label(image, fonts, face, text, box, size, color, scroll=0, align='left'):
    x, y, w, h = box
    tile = Image.new('RGBA', (w, h))
    draw = ImageDraw.Draw(tile)
    font = fonts.font(face, size)
    width = draw.textlength(text, font=font)
    offset = 0
    if width > w - 4:
        offset = max(0, scroll - 24) % (int(width) + 28)
    left = {'center': (w - width) / 2, 'right': w - width - 2}.get(align, 2) if width <= w - 4 else 2
    draw.text((left - offset, h // 2), text, font=font, anchor='lm', fill=color)
    if offset:
        draw.text((2 + int(width) + 28 - offset, h // 2), text,
                  font=font, anchor='lm', fill=color)
    image.paste(tile, (x, y), tile)


@lru_cache(maxsize=8)
def cover(track, side, classic):
    art = Image.new('RGB', (side, side), '#424955')
    if track.art:
        try:
            with Image.open(io.BytesIO(track.art)) as source:
                art = ImageOps.fit(source.convert('RGB'), (side, side))
        except (OSError, ValueError, Image.DecompressionBombError):
            pass
    mask = Image.new('L', (side, side))
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, side - 1, side - 1), 0 if classic else 12, fill=255)
    return art, mask


@lru_cache(maxsize=3)
def theme_config(style):
    return next(item for item in theme.builtins() if item['id'] == style)


@lru_cache(maxsize=40)
def firmware_image(data):
    with Image.open(io.BytesIO(data)) as source:
        return source.convert('RGBA')


@dataclass(frozen=True)
class BatteryStatus:
    percent: int = 61
    charging: bool = False
    wifi: bool = True


DEFAULT_BATTERY = BatteryStatus()


@lru_cache(maxsize=1)
def classic_bolt():
    return art.images(theme_config('classic-light'))['classic_light_bolt']


def draw_battery(frame, draw, battery, color, firmware, classic):
    """Preview the firmware's Icon + Percent battery treatment."""
    low = battery.percent < 15 and not battery.charging
    if firmware is not None and not firmware.custom:
        asset = 'bar_charge' if battery.charging else 'bar_lowcharge' if low else 'bar_battery'
        if data := firmware.images.get(asset):
            icon = firmware_image(data)
            x, y = 310 - icon.width, (30 - icon.height) // 2
            frame.paste(icon, (x, y), icon)
            # Stock leaves the vertical progress bar empty while showing bar_charge.
            level = (icon.height - 3) * battery.percent // 100
            if level and not battery.charging:
                draw.rectangle((x + 1, y + icon.height - 1 - level,
                                x + icon.width - 2, y + icon.height - 2), fill=color)
        return color

    offset = ipod.O
    ink = f"#{offset['BATT_CHARGE_RGB' if battery.charging else 'BATT_LOW_RGB']:06x}" if (
        battery.charging or low) else color
    percent = 100 if battery.charging else battery.percent
    nub_w, nub_h = offset['BATT_NUB_W'], offset['BATT_NUB_H']
    if classic:
        config = theme_config('classic-light')
        inner_w, inner_h = art.BOLT_BOX[2:]
        w, h = inner_w + 2, inner_h + 2
        x, y = 311 - w - nub_w, (30 - h) // 2
        edge = f"#{config['batt_line']:06x}"
        draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), 2, outline=edge)
        tip = y + (h - nub_h) // 2
        draw.rectangle((x + w, tip, x + w + nub_w - 1, tip + nub_h - 1), outline=edge)
        level = config['batt_low_w'] if low else inner_w * percent // 100
        empty, filled = (art.gradient(config[key], 0, inner_h - 1) for key in ('batt_empty', 'batt'))
        for row in range(inner_h):
            sy = y + 1 + row
            draw.line((x + 1, sy, x + inner_w, sy), fill=f'#{empty(row):06x}')
            if level:
                rgb = config['batt_low'] if low else filled(row)
                draw.line((x + 1, sy, x + level, sy), fill=f'#{rgb:06x}')
        if battery.charging:
            data = firmware.images.get('classic_light_bolt') if firmware else None
            bolt = firmware_image(data or classic_bolt())
            frame.paste(bolt, (x + 1, y + 1), bolt)
    else:
        w, h = offset['BATT_BODY_W'], offset['BATT_BODY_H']
        x, y = 311 - w - nub_w, (30 - h) // 2 - offset['BATT_PCT_DY']
        draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), 2, outline=ink)
        tip = y + (h - nub_h) // 2
        draw.rectangle((x + w, tip, x + w + nub_w - 1, tip + nub_h - 1), fill=ink)
        level = (w - 4) * percent // 100
        if level:
            draw.rectangle((x + 2, y + 2, x + 1 + level, y + h - 3), fill=ink)
    return ink


def status_bar(frame, fonts, title, color, background, paused=None, battery=DEFAULT_BATTERY,
               firmware=None, classic=False):
    draw = ImageDraw.Draw(frame)
    draw.rectangle((0, 0, SIZE[0] - 1, 29), fill=background)
    if paused is True:
        draw.rectangle((25, 10, 27, 19), fill=color)
        draw.rectangle((31, 10, 33, 19), fill=color)
    elif paused is False:
        draw.polygon(((25, 10), (25, 20), (34, 15)), fill=color)
    title_x = 42 if paused is not None else 24
    label(frame, fonts, 'default', title, (title_x, 0, 146 - title_x, 30), 18, color)
    label(frame, fonts, 'default', time.strftime('%H:%M'), (149, 0, 77, 30), 18, color, align='center')

    if battery.wifi:
        if firmware and not firmware.custom and (data := firmware.images.get('bar_wifi4')):
            wifi = firmware_image(data)
            frame.paste(wifi, (255, (30 - wifi.height) // 2), wifi)
        else:
            for radius in (8, 5):
                draw.arc((263 - radius, 18 - radius, 263 + radius, 18 + radius), 222, 318, fill=color, width=2)
            draw.ellipse((262, 17, 264, 19), fill=color)
    percent_color = draw_battery(frame, draw, battery, color, firmware, classic)
    label(frame, fonts, 'default', f'{battery.percent}%', (314, 0, 39, 30), 16, percent_color)


def display_page(fonts, title, light, paused=None, battery=DEFAULT_BATTERY, firmware=None, classic=None):
    paper, ink, muted = ('#f7f7f7', '#171717', '#696969') if light else ('#161722', '#f7f4f4', '#a4a4b3')
    frame = Image.new('RGB', SIZE, paper)
    draw = ImageDraw.Draw(frame)
    status_bar(frame, fonts, title, ink, '#e5e5e5' if light else '#222431', paused, battery,
               firmware, light if classic is None else classic)
    return frame, draw, ink, muted


def render_menu(fonts, title, rows, selected, light, paused=None, battery=DEFAULT_BATTERY, firmware=None,
                app_store=False):
    frame, draw, ink, muted = display_page(fonts, title, light, paused, battery, firmware)
    hits = []
    if not rows:
        label(frame, fonts, 'default', 'No tracks', (24, 113, 327, 58), 20, muted, align='center')
    row_step = 64 if app_store else 45
    visible = (SIZE[1] - 38) // row_step
    start = max(0, selected - visible + 1)
    for index, (text, value, face) in enumerate(rows[start:start + visible], start):
        y = 38 + row_step * (index - start)
        height = row_step - 4
        if index == selected:
            draw.rounded_rectangle((12, y, 362, y + height), 8, '#cfe7fb' if light else '#344565')
        if app_store and value:
            label(frame, fonts, face, text, (22, y + 5, 323, 28), 21, ink)
            label(frame, fonts, 'default', value, (22, y + 32, 323, 23), 15, muted)
        else:
            if value:
                label(frame, fonts, 'default', value, (220, y, 127, height), 16, muted, align='right')
            label(frame, fonts, face, text, (22, y, 200 if value else 323, height), 21, ink)
        hits.append((index, y, y + height + 1))
    return frame, hits


def album_image(album, tracks, firmware, side):
    sample = tracks[album.cover]
    if not sample.art and firmware:
        for name in ('default_album_flow', 'default_album_coverflow', 'default_album_big'):
            if name in firmware.images:
                return ImageOps.fit(firmware_image(firmware.images[name]), (side, side)).convert('RGB')
    return cover(sample, side, False)[0]


def render_albums(fonts, tracks, albums, selected, firmware, light, paused=None, battery=DEFAULT_BATTERY):
    grid = firmware is not None and not firmware.custom
    frame, draw, ink, muted = display_page(fonts, 'Album Wall' if grid else 'Cover Flow',
                                           light, paused, battery, firmware)
    if not albums:
        label(frame, fonts, 'default', 'No albums', (24, 112, 327, 62), 22, muted, align='center')
        return frame, []
    hits = []
    if grid:
        start = (selected // 9) * 9
        for index, album in enumerate(albums[start:start + 9], start):
            col, row = (index - start) % 3, (index - start) // 3
            x, y = 55 + col * 91, 38 + row * 89
            frame.paste(album_image(album, tracks, firmware, 77), (x, y))
            if index == selected:
                draw.rounded_rectangle((x - 3, y - 3, x + 79, y + 79), 4, outline='#82bcff', width=3)
            hits.append((index, x, y, x + 77, y + 77))
        return frame, hits
    for distance in (3, 2, 1, 0):
        for step in (-distance, distance) if distance else (0,):
            index = selected + step
            if not 0 <= index < len(albums):
                continue
            side = 162 if not step else 114 - distance * 9
            art = album_image(albums[index], tracks, firmware, side)
            x = round((375 - side) / 2 + step * 61)
            y = 58 if not step else 88 + distance * 5
            if step:
                art = art.resize((round(side * .72), side))
                art = Image.blend(art, Image.new('RGB', art.size), min(.12 * distance, .55))
            frame.paste(art, (x, y))
            if not step:
                reflection = ImageOps.flip(art).crop((0, 0, side, 25))
                alpha = Image.new('L', reflection.size)
                shade = ImageDraw.Draw(alpha)
                for row in range(reflection.height):
                    shade.line((0, row, side, row), fill=94 - row * 3)
                frame.paste(reflection, (x, y + side + 2), alpha)
            hits.append((index, x, y, x + art.width, y + art.height))
    album = albums[selected]
    label(frame, fonts, 'default', album.name, (22, 248, 331, 30), 24, ink, align='center')
    label(frame, fonts, 'default', album.artist, (22, 279, 331, 24), 17, muted, align='center')
    return frame, hits[::-1]  # frontmost cover wins


def format_time(seconds):
    minutes, seconds = divmod(int(max(0, seconds)), 60)
    return f'{minutes}:{seconds:02d}'


def render_lyrics(track, fonts, elapsed, position, count, paused=False, battery=DEFAULT_BATTERY,
                  firmware=None, classic=False):
    frame, draw, ink, muted = display_page(fonts, 'Lyrics', False, paused, battery, firmware, classic)
    label(frame, fonts, 'default', f'{position} of {count}', (26, 44, 115, 23), 16, ink)
    index = bisect.bisect_right(track.lyrics, elapsed, key=lambda line: line[0]) - 1
    if not track.lyrics:
        label(frame, fonts, 'default', 'No synced lyrics', (26, 121, 323, 52), 23, muted, align='center')
    else:
        current = max(0, index)
        for at, y in ((current - 1, 87), (current, 144), (current + 1, 220)):
            if not 0 <= at < len(track.lyrics):
                continue
            text, face = fonts.artist(track.lyrics[at][1])
            if face == 'default' and fonts.supports('bold', text):
                face = 'bold'
            size = 30 if at == current else 23
            font = fonts.font(face, size)
            lines = ['']
            for word in text.split():
                candidate = f'{lines[-1]} {word}'.strip()
                if lines[-1] and font.getlength(candidate) > 316:
                    lines.append(word)
                else:
                    lines[-1] = candidate
            for row, line in enumerate(lines[:2]):
                label(frame, fonts, face, line, (26, y + row * 30, 323, 32), size,
                      ink if at == current else '#55576a')
    for i in range(4):
        x = 166 + i * 14
        draw.ellipse((x, 261, x + 7, 268), fill=ink if i == 1 else '#777a8b')
    progress = min(1, elapsed / track.duration) if track.duration > 0 else 0
    draw.rounded_rectangle((26, 280, 349, 285), 3, '#565968')
    draw.rounded_rectangle((26, 279, 26 + max(6, round(323 * progress)), 286), 3, '#ff416e')
    label(frame, fonts, 'default', format_time(elapsed), (26, 290, 95, 23), 15, muted)
    label(frame, fonts, 'default', '-' + format_time(track.duration - elapsed),
          (255, 290, 94, 23), 15, muted, align='right')
    return frame


def packaged_style(firmware, widget, name, default):
    value = widget.style_value(firmware.styles, name)
    if value is None:
        return default
    if isinstance(value, bytes):
        if name.endswith('_image'):
            return value.rstrip(b'\0').decode('utf-8')
        if len(value) != 4:
            return default
        if name.endswith('_color'):
            return '#' + value.hex()
        code = int.from_bytes(value, 'little')
        if name == 'text_align_h':
            return {1: 'center', 2: 'left', 3: 'right'}.get(code, default)
        return code
    if name == 'font_size':
        return int(value)
    return value


def render_browse(firmware, fonts, style, page, selected, tracks, paused=None, battery=DEFAULT_BATTERY,
                  home_entries=None):
    """Draw the selected Home card or list. Return rows with mouse hit targets."""
    light = firmware.custom and style == 'classic-light'
    paper, ink, muted = ('#f7f7f7', '#171717', '#707070') if light else ('#000000', '#ffffff', '#a0a0a0')
    frame = Image.new('RGB', SIZE, paper)
    draw = ImageDraw.Draw(frame)
    title = {'home': 'Home', 'folder': 'Folders', 'localmusic': 'Songs'}[page]
    status_bar(frame, fonts, title, ink, '#e5e5e5' if light else '#171717', paused, battery, firmware, light)
    hits = []
    if page == 'home' and not firmware.custom:
        entry = firmware.home[selected]
        _, y, w, h = entry.art.box
        if entry.image in firmware.images and w > 0 and h > 0:
            art = ImageOps.contain(firmware_image(firmware.images[entry.image]), (w, h))
            frame.paste(art, ((SIZE[0] - art.width) // 2, 30 + y + (h - art.height) // 2), art)
        _, y, _, h = entry.text.box
        label(frame, fonts, 'default', entry.label, (20, 30 + y, 335, h), h, ink, align='center')
        for marker, x in (('‹', 18), ('›', 326)):
            label(frame, fonts, 'default', marker, (x, 132, 31, 36), 30, ink, align='center')
        hits.append((selected, 30, SIZE[1]))
        return frame, hits

    if page == 'home':
        top = firmware.home[0].row.box[1] + 30
        rows = []
        for entry in home_entries if home_entries is not None else firmware.home:
            height = entry.row.box[3]
            rows.append((entry.label, 'default', entry.image, top, height))
            top += height
    else:
        page_widgets = firmware.lists.get(page, firmware.lists['folder'])
        table = next((widget for widget in page_widgets.values() if widget.kind == 'table_view'), None)
        _, y, _, height = table.box if table else (0, 0, SIZE[0], 290)
        row_height = 42 if firmware.custom else 46
        visible = max(1, min(height, SIZE[1] - 30 - y) // row_height)
        start = min(max(0, selected - visible + 1), max(0, len(tracks) - visible))
        rows = []
        for i, track in enumerate(tracks[start:start + visible]):
            text, face = fonts.artist(track.filename or track.title) if page == 'folder' else (track.title, 'default')
            rows.append((text, face, '', 30 + y + i * row_height, row_height))
    for index, (text, face, image_name, y, height) in enumerate(rows, 0 if page == 'home' else start):
        if not 0 < height <= SIZE[1] or y >= SIZE[1]:
            continue
        selected_row = index == selected
        if selected_row:
            draw.rounded_rectangle((8, y + 1, 366, y + height - 2), radius=7,
                                   fill='#cfe7fb' if light else '#28527d')
        if image_name in firmware.images:
            icon = ImageOps.contain(firmware_image(firmware.images[image_name]), (24, 24))
            frame.paste(icon, (13, y + (height - icon.height) // 2), icon)
        x = 41 if page == 'home' else 18
        label(frame, fonts, face, text, (x, y, 350 - x, height), 20, ink if selected_row else muted)
        if page == 'home':
            label(frame, fonts, 'default', '›', (341, y, 20, height), 20, muted)
        hits.append((index, y, y + height))
    return frame, hits


def render_firmware(track, fonts, firmware, style, position, count, scroll, paused, elapsed, battery):
    config = theme_config(style) if firmware.custom else None
    geometry = theme.geometry(config) if config else ipod.SET0
    page = firmware.now_playing(geometry.name)
    themed = firmware.custom and geometry.name in firmware.playing_layouts
    light = firmware.custom and style == 'classic-light'
    offset = geometry.bar if themed else 30
    paper = '#f7f7f7' if light else packaged_style(firmware, page['playing_page'], 'bg_color', '#000000')
    ink, secondary = ('#171717', '#555555') if light else ('#ffffff', '#cccccc')
    frame = Image.new('RGB', SIZE, paper)
    draw = ImageDraw.Draw(frame)
    bar = Image.new('RGB', (SIZE[0], 30), paper)
    status_bar(bar, fonts, 'Now Playing', ink, '#e5e5e5' if light else '#171717', paused, battery, firmware, light)
    frame.paste(bar if offset == 30 else bar.resize((SIZE[0], offset), Image.Resampling.LANCZOS), (0, 0))

    def icon(name, box, fit=False, tint=None):
        if name not in firmware.images:
            return
        x, y, w, h = box
        asset = firmware_image(firmware.images[name])
        if fit:
            asset = ImageOps.contain(asset, (w, h))
        if tint is not None:
            tinted = Image.new('RGBA', asset.size, tint)
            tinted.putalpha(asset.getchannel('A'))
            asset = tinted
        frame.paste(asset, (x + (w - asset.width) // 2, offset + y + (h - asset.height) // 2), asset)

    x, y, w, h = page['img_cover'].box
    if themed and geometry.np_ipod:
        h = w  # The remaining cover-widget height is reserved for the firmware's reflection.
    if track.art:
        art, mask = cover(track, min(w, h), not firmware.custom or light)
        frame.paste(art, (x + (w - art.width) // 2, offset + y + (h - art.height) // 2), mask)
    else:
        icon(page['img_cover'].props.get('image'), (x, y, w, h), fit=True)

    for name in ('img_return', 'img_more', 'img_fav', 'img_playmode', 'img_spectrum', 'img_vu'):
        if widget := page.get(name):
            icon(widget.props.get('image') or packaged_style(firmware, widget, 'bg_image', ''), widget.box,
                 tint=secondary if light else None)
    if paused and (state := page.get('img_playstate')):
        icon('play_bigplay' if 'play_bigplay' in firmware.images else state.props.get('image'), state.box)

    def text(name, value, face='default', color=secondary, size=None, shift=0):
        if (widget := page.get(name)) and value:
            x, y, w, h = widget.box
            if not (0 < w <= 4096 and 0 < h <= 4096):
                return
            pixels = size or packaged_style(firmware, widget, 'font_size', h)
            align = packaged_style(firmware, widget, 'text_align_h', 'left')
            foreground = color if light else packaged_style(firmware, widget, 'text_color', color)
            label(frame, fonts, face, value, (x, offset + y, w, h), pixels, foreground, shift, align)

    title = page['scrlabel_title']
    size = packaged_style(firmware, title, 'font_size', title.box[3])
    preferred = 'default'
    if config:
        preferred = FACES[config['font[ROLE_NP]']]
        size = config['font_px[ROLE_NP]'] or size
    face, size = fonts.face(preferred, track.title, size)
    artist, artist_face = fonts.artist(track.artist)
    text('scrlabel_title', track.title, face, ink, size, scroll)
    text('scrlabel_artist', artist, artist_face, shift=scroll)
    text('label_ipod_album', track.album, shift=scroll)
    text('label_ipod_pos', f'{position} of {count}')
    text('label_playtime', format_time(elapsed))
    if 'label_ipod_remain' in page:
        text('label_ipod_remain', '-' + format_time(track.duration - elapsed))
    else:
        text('label_playlen', format_time(track.duration))

    slider = page['slider_play']
    track_image = packaged_style(firmware, slider, 'bg_image', '')
    if track_image in firmware.images:
        icon(track_image, slider.box)
    else:
        x, y, w, h = slider.box
        y += offset + h // 2
        draw.rounded_rectangle((x, y - 3, x + w - 1, y + 3), 3, fill='#777777')
    if track.duration > 0 and elapsed > 0:
        x, y, w, h = slider.box
        y += offset + h // 2 + int(packaged_style(firmware, slider, 'y_offset', 0))
        end = x + max(4, min(w - 1, round(w * elapsed / track.duration)))
        draw.rounded_rectangle((x, y - 3, end, y + 3), 3, fill='#258ed8' if light else '#ff416e')
    return frame, face


def render(track, fonts, style, position=1, count=1, scroll=0, paused=False, firmware=None, elapsed=0.0,
           battery=DEFAULT_BATTERY):
    if firmware is not None:
        return render_firmware(track, fonts, firmware, style, position, count, scroll, paused, elapsed, battery)
    classic = style == 'classic-light'
    config = theme_config(style)
    paper, ink, secondary = ('#f7f7f7', '#171717', '#555555') if classic else (
        '#141414', '#ffffff', '#aaaaaa')
    image = Image.new('RGB', SIZE, paper)
    draw = ImageDraw.Draw(image)
    status_bar(image, fonts, 'Now Playing', ink, '#e5e5e5' if classic else '#202020', paused, battery,
               classic=classic)
    art = ipod.NP_IPOD_ART if classic else ipod.NP_ART
    slide_y = 30 + ipod.NP_TOP
    art_y = 30 + ipod.inc('NP_IPOD_ART_Y') if classic else slide_y + ipod.NP_ART_Y
    artwork, mask = cover(track, art, classic)
    image.paste(artwork, (ipod.NP_MARGIN, art_y), mask)
    x = ipod.inc('NP_IPOD_TEXT_X') if classic else ipod.NP_TEXT_X
    y = (30 + ipod.inc('NP_IPOD_TEXT_Y') if classic else
         art_y + (art - ipod.NP_ICON - (28 + 6 + 22 + 6 + 22)) // 2)
    w = SIZE[0] - ipod.NP_MARGIN - x
    face, size = fonts.face(FACES[config['font[ROLE_NP]']], track.title,
                            config['font_px[ROLE_NP]'] or ipod.NP_TITLE_PX)
    label(image, fonts, face, track.title, (x, y, w, 28), size, ink, scroll)
    for index, text in enumerate((track.artist, track.album)):
        label(image, fonts, 'default', text, (x, y + 34 + index * 28, w, 22),
              ipod.NP_META_PX, secondary, scroll)
    label(image, fonts, 'default', f'{position} of {count}', (x, y + 91, w, 20), 16, secondary)
    draw.rounded_rectangle((21, 267, 353, 273), 3, fill='#777777')
    draw.rounded_rectangle((21, 267, 151, 273), 3, fill='#258ed8' if classic else '#eeeeec')
    state = 'Paused' if paused else 'Playing'
    label(image, fonts, 'default', state, (21, 285, 135, 23), 16, secondary)
    return image, face


MEDIA_FOLDERS = frozenset(name.casefold() for name in MEDIA_NAMES)


HOME_ROUTES = (('playing', 'Now Playing'), ('localmusic', 'Library'), ('coverflow', 'Cover Flow'),
               ('folder', 'Folders'), ('stream', 'Streaming'), ('settings', 'Settings'))


class Simulator:
    def __init__(self, style, tracks, firmware=None, sd_card=None):
        self.style, self.tracks, self.firmware, self.sd_card = style, tracks, firmware, sd_card
        self.page, self.cursor = 'home', 0
        self.shell = DEFAULT_SHELL
        self.arcade = None
        self.buddy = None
        self.buddy_wheel = 0.0
        self.game_bests: dict[str, int] = {}
        self.current, self.scroll, self.paused, self.elapsed = 0, 0, True, 0.0
        self.directory, self.album = sd_card, None
        self.folder_cache: dict[Path | None, list[tuple[str, Path | int]]] = {}
        self.history = []
        self.library_title = 'Library'
        self.library_rows: list[LibraryRow] = []
        self.plays: Counter[int] = Counter()
        self.recent: dict[int, None] = {}
        self.playlists: dict[str, tuple[int, ...]] = {}
        self.search_query = None
        self.artist_group = 'Album Artist'
        self.queue = tuple(range(len(tracks)))
        self.queue_shuffle = ''
        self.albums = albums_for(tracks)
        self.brightness, self.shuffle, self.repeat, self.sort = '100%', 'Off', 'Off', 'Album'
        self.battery = DEFAULT_BATTERY
        self.hint = ''
        self.store = AppStore((Path(__file__).resolve().parent.parent / 'sources.list').read_text(encoding='utf-8'))
        self.rockbox_installed = self.store.has_rockbox(sd_card)
        self.folder_root = None
        self.wheel_sensitivity = 50

    @property
    def custom(self):
        return self.firmware is None or self.firmware.custom

    @property
    def light(self):
        return (self.firmware is None or self.firmware.custom) and self.style == 'classic-light'

    def firmware_home(self):
        entries = self.firmware.home
        if not self.firmware.custom:
            return entries
        if not self.rockbox_installed:
            return tuple(entry for entry in entries if entry.key != 'rockbox')
        if not any(entry.key == 'rockbox' for entry in entries):
            index = next((i for i, entry in enumerate(entries) if entry.key == 'stream'), len(entries) - 1)
            shortcut = replace(entries[index], key='rockbox', label='Rockbox', image='')
            return (*entries[:index], shortcut, *entries[index:])
        return entries

    def home_items(self):
        if self.firmware:
            return tuple((entry.key, entry.label) for entry in self.firmware_home())
        if self.rockbox_installed:
            return (*HOME_ROUTES[:4], ('rockbox', 'Rockbox'), *HOME_ROUTES[4:])
        return HOME_ROUTES

    def refresh_rockbox(self):
        installed = self.store.has_rockbox(self.sd_card)
        if installed == self.rockbox_installed:
            return
        before = self.home_items()
        self.rockbox_installed = installed
        after = self.home_items()

        def relocate(cursor):
            if cursor < len(before) and before[cursor] in after:
                return after.index(before[cursor])
            return min(cursor, len(after) - 1)

        if self.page == 'home':
            self.cursor = relocate(self.cursor)
        for index, entry in enumerate(self.history):
            if entry[0] == 'home':
                self.history[index] = (entry[0], relocate(entry[1]), *entry[2:])

    def viewing_games(self):
        builtins = self.builtin_game_rows()
        return (self.page == 'library' and self.library_title == 'Games'
                and self.library_rows[:len(builtins)] == builtins)

    def builtin_game_rows(self):
        names = self.firmware.builtin_games if self.firmware else BUILTIN_GAMES
        return [LibraryRow(name, 'device') for name in names]

    def game_rows(self):
        installed = (LibraryRow(name, f'card-game:{ident}')
                     for name, ident in card_game_entries(self.sd_card))
        return [*self.builtin_game_rows(), *installed]

    def mount_card(self, tracks, root):
        games_open = self.viewing_games()
        self.close_arcade()
        self.replace_tracks(tracks, root)
        if games_open and self.custom:
            self.page, self.history = 'home', []
            self.open_library()
            self.cursor = next(i for i, row in enumerate(self.library_rows) if row.route == 'games')
            self.show_library('Games', self.game_rows())

    def replace_tracks(self, tracks, root=None):
        self.tracks, self.sd_card, self.directory = tracks, root, root
        self.rockbox_installed = self.store.has_rockbox(root)
        self.albums, self.album = albums_for(tracks, self.sort), None
        self.folder_cache.clear()
        self.plays.clear()
        self.recent.clear()
        self.playlists.clear()
        self.library_rows = []
        self.folder_root = None
        self.queue = tuple(range(len(tracks)))
        self.queue_shuffle = ''
        self.current, self.cursor, self.scroll, self.elapsed, self.paused = 0, 0, 0, 0.0, True
        self.page = 'folder' if root else 'home'
        self.history = [('home', 0, root, None, 'Library', [])] if root else []

    def menu(self):
        rows: list[tuple[str, str, str | None]] = []
        if self.page == 'store':
            if not self.custom:
                return []
            check = self.store.stage if self.store.item == 'check' else ''
            rows.append(('Check for Updates', check, 'check'))
            rows.extend((app.name, self.store.row_status(self.sd_card, app), app.ident)
                        for app in self.store.visible(self.sd_card))
            return rows
        if self.page not in SETTINGS:
            return []

        names = SETTINGS[self.page][1]
        if not self.custom:
            names = STOCK_ROWS.get(self.page, names)
        links = PAGES.get(self.page, {})
        if self.page == 'power' and not self.store.has_rockbox(self.sd_card):
            names = tuple(name for name in names if name != 'Boot to')
        if self.page == 'controls':
            names = tuple(name for name in names if name != 'Click With Headphones')
        if self.page == 'appearance':
            hidden = ('Rounded Corners', 'Centred Now Playing') if self.style == 'classic-light' else (
                'Library on Home', 'Row Preview', 'Row Art', 'Show Wordmark')
            names = tuple(name for name in names if name not in hidden)
        for name in names:
            if name in links:
                rows.append((name, self.setting_value(name), links[name]))
            else:
                rows.append((name, self.setting_value(name), None))
        return rows

    def setting_value(self, name):
        if self.page == 'theme':
            return '✓' if self.style == THEME_KEYS[name] else ''
        if self.page == 'playmode':
            return '✓' if (self.shuffle, self.repeat) == PLAY_MODES[name] else ''
        return {
            'Theme': next((label for label, style in THEME_KEYS.items() if style == self.style), ''),
            'Brightness': self.brightness,
            'Sort': self.sort,
            'Wheel Sensitivity': f'{self.wheel_sensitivity}%',
            'Artists': self.artist_group,
            'Folder Root': self.folder_root.name if self.folder_root else 'Card',
            'Wi-Fi': ('On' if self.battery.wifi else 'Off') if self.page == 'wifi' else '',
            'Firmware Version': self.firmware.version if self.firmware else 'Checkout',
            'SD Card': self.sd_card.name if self.sd_card else 'No SD card',
        }.get(name, '')

    def select_setting(self, name, target):
        if self.page == 'store':
            try:
                self.store.select(self.sd_card, target, online=self.battery.wifi)
            except (OSError, ValueError) as exc:
                self.hint = str(exc)
            else:
                self.hint = self.store.message
        elif target:
            self.open(target)
        elif self.page == 'theme':
            self.style = THEME_KEYS[name]
            self.back()
        elif self.page == 'playmode':
            self.shuffle, self.repeat = PLAY_MODES[name]
            self.back()
        elif name == 'Brightness':
            self.cycle('brightness')
        elif name == 'Sort':
            self.cycle('sort')
        elif name == 'Refresh Cover Flow':
            self.albums = albums_for(self.tracks, self.sort)
            self.hint = 'Cover Flow refreshed'
        elif name == 'Wi-Fi' and self.page == 'wifi':
            self.battery = replace(self.battery, wifi=not self.battery.wifi)
        elif name == 'Artists':
            self.artist_group = 'Artist' if self.artist_group == 'Album Artist' else 'Album Artist'
        elif name == 'Wheel Sensitivity':
            self.wheel_sensitivity = 10 if self.wheel_sensitivity == 200 else self.wheel_sensitivity + 10
        elif name == 'Folder Root' and self.sd_card:
            roots = [None, *[target for _, target in folder_rows(self.tracks, self.sd_card)
                             if isinstance(target, Path)]]
            self.folder_root = roots[(roots.index(self.folder_root) + 1) % len(roots)]
        elif self.page != 'about':
            self.hint = f'{name} requires the Q2 hardware'

    def open(self, page):
        self.history.append((self.page, self.cursor, self.directory, self.album, self.library_title, self.library_rows))
        self.page, self.cursor, self.scroll, self.hint = page, 0, 0, ''
        if page == 'store' and self.battery.wifi and self.sd_card and (
                not self.store.checked or time.monotonic() - self.store.checked >= 600):
            self.store.select(self.sd_card, 'check', background=True)

    def close_arcade(self):
        if self.buddy is not None:
            self.buddy.close()
            self.buddy = None
        if self.arcade is not None:
            self.arcade.machine.close()
            self.arcade = None

    def back(self):
        if self.page == 'buddy' and self.buddy is not None:
            self.buddy_key(170)
            return
        if self.page == 'arcade' and self.arcade is not None:
            if self.arcade.scene != 'games':
                self.arcade.back()
                if self.arcade.scene != 'games':
                    return
            self.close_arcade()
        self.store.armed = ''
        if self.history:
            self.page, self.cursor, self.directory, self.album, self.library_title, self.library_rows = self.history.pop()
        else:
            self.page, self.cursor = 'home', 0
        self.hint, self.scroll = '', 0

    def buddy_key(self, code):
        if self.buddy is not None:
            self.buddy.send(f'k d {code}')
            self.buddy.send(f'k u {code}')

    def buddy_drag_wheel(self, radians):
        if self.buddy is not None:
            self.buddy_wheel -= radians * 200 / math.tau
            travel = math.trunc(self.buddy_wheel)
            if travel:
                self.buddy_wheel -= travel
                self.buddy.send(f'w {travel}')

    def move(self, step):
        if self.page == 'buddy' and self.buddy is not None:
            self.buddy.send(f'w {-step * 28}')
            return
        if self.page == 'arcade' and self.arcade is not None:
            self.arcade.scroll(step)
            return
        if self.page in ('playing', 'lyrics'):
            self.step_track(step)
        else:
            count = (len(self.albums) if self.page == 'coverflow' else
                     len(self.home_items()) if self.page == 'home' else
                     len(self.rows()))
            if count:
                self.cursor = (self.cursor + step) % count
        self.hint, self.scroll = '', 0
        self.store.armed = ''

    def step_track(self, step, automatic=False):
        if not self.queue:
            return
        position = self.queue.index(self.current)
        if self.queue_shuffle:
            if automatic and position == len(self.queue) - 1:
                if self.queue_shuffle != 'shuffle_songs':
                    self.paused = True
                    return
                self.queue = tuple(random.sample(self.queue, len(self.queue)))
                position = -1
            self.current = self.queue[(position + step) % len(self.queue)]
            self.elapsed, self.scroll = 0.0, 0
            self.record_play(self.current)
            return
        if automatic and self.repeat == 'One':
            self.elapsed = 0.0
            return
        if self.shuffle == 'On' and len(self.queue) > 1:
            self.current = random.choice([index for index in self.queue if index != self.current])
        elif automatic and position == len(self.queue) - 1 and self.repeat == 'Off':
            self.paused = True
            return
        else:
            self.current = self.queue[(position + step) % len(self.queue)]
        self.elapsed, self.scroll = 0.0, 0
        self.record_play(self.current)

    def advance(self, delta):
        if self.page == 'buddy' and self.buddy is not None:
            try:
                self.buddy.frame()
                if self.buddy.stopped:
                    code = self.buddy.exit_code
                    self.close_arcade()
                    self.back()
                    if code:
                        self.hint = f'Q2 game exited (code {code})'
            except (OSError, ValueError) as exc:
                self.close_arcade()
                self.back()
                self.hint = f'Q2 game stopped: {exc}'
        if self.page == 'arcade' and self.arcade is not None:
            self.arcade.advance(delta * 1000)
        if self.store.poll():
            self.refresh_rockbox()
            if self.viewing_games():
                self.library_rows = self.game_rows()
                self.cursor = min(self.cursor, len(self.library_rows) - 1)
            if self.store.message:
                self.hint = self.store.message
        if not self.paused and self.tracks:
            self.elapsed += delta
            duration = self.tracks[self.current].duration
            if duration > 0 and self.elapsed >= duration:
                self.elapsed = duration
                self.step_track(1, automatic=True)

    def cycle(self, key):
        choices = {'brightness': ('brightness', ('100%', '75%', '50%', '25%')),
                   'sort': ('sort', ('Album', 'Artist'))}
        name, values = choices[key]
        setattr(self, name, values[(values.index(getattr(self, name)) + 1) % len(values)])
        if key == 'sort':
            self.albums = albums_for(self.tracks, self.sort)

    def show_library(self, title, rows):
        self.open('library')
        self.library_title, self.library_rows = title, list(rows)

    def open_library(self):
        self.show_library('Library' if self.custom else 'Local Music',
                          library_menu(self.sd_card, self.custom, self.light))

    def in_music_library(self, index):
        path = self.tracks[index].path
        if not self.sd_card or not path or not path.is_relative_to(self.sd_card):
            return True
        parts = path.relative_to(self.sd_card).parts
        return (not any(part.startswith('.') for part in parts)
                and (not self.custom or parts[0].casefold() not in MEDIA_FOLDERS))

    def music_indices(self):
        return tuple(i for i in range(len(self.tracks)) if self.in_music_library(i))

    def song_library_rows(self, indices):
        return [LibraryRow(self.tracks[index].title, 'track', (index,)) for index in indices]

    def play_from_library(self, queue):
        if queue:
            self.play(queue[0], queue)
        else:
            self.hint = 'No tracks'

    def confirm_library_scan(self):
        if not self.sd_card:
            self.hint = 'No SD card'
            return
        try:
            tracks, failures = scan_card(self.sd_card)
        except ERRORS as exc:
            self.hint = str(exc)
            return
        self.replace_tracks(tracks, self.sd_card)
        self.page, self.history = 'home', []
        self.open_library()
        self.hint = f'{len(tracks)} tracks' + (f' · {len(failures)} skipped' if failures else '')

    def select_library(self, row):
        name, route, selected = row
        if route == 'games':
            self.show_library(name, self.game_rows())
        elif route.startswith('card-game:') and self.sd_card is not None:
            try:
                from simulator_buddy import CardGame
                self.buddy = CardGame(self.sd_card, route.removeprefix('card-game:'))
                self.buddy_wheel = 0.0
                self.open('buddy')
            except (ImportError, OSError, ValueError) as exc:
                self.hint = f'Could not open {name}: {exc}'
        elif route == 'card-app':
            self.hint = f'{name} requires the Q2 hardware'
        elif route == 'track':
            self.play(selected[0], [entry.tracks[0] for entry in self.library_rows if entry.route == 'track'])
        elif route == 'album':
            self.play_from_library(selected)
        elif route == 'group':
            self.show_library(name, self.song_library_rows(selected))
        elif route == 'device':
            if checkout_can_preview(name):
                try:
                    from arcade_emulator import ArcadeWindow, MipsArcade
                    view = object.__new__(ArcadeWindow)  # reuse the actual MIPS runner; no second Tk window
                    view.machine = MipsArcade()
                    view.theme = self.style
                    view.scene, view.selection, view.game = 'games', 0, None
                    view.paused = view.menu = view.quit_selected = False
                    view.best_scores = self.game_bests
                    view.start(name.lower())
                    self.arcade = view
                    if self.firmware is not None:
                        self.hint = ('Game preview uses checkout-built MIPS code, NOT '
                                     'the game binary inside the selected firmware.')
                    if name in ('Pong', 'Blocks'):
                        self.paused = True
                    self.open('arcade')
                except Exception as exc:  # toolchain, Unicorn, or incompatible MIPS build
                    self.hint = f'Could not open MIPS game: {exc}'
                    print(f'Q2 MIPS game failed to launch: {exc}', file=sys.stderr)
            else:
                self.hint = (f'{name} is listed in the firmware but has no '
                             'compatible desktop game runtime. The Q2 hardware '
                             'may be required.')
        elif route == 'media':
            directory = card_media(self.sd_card).get(name)
            if directory is not None and name in ('Podcasts', 'Audiobooks'):
                self.open('folder')
                self.directory = directory
            elif directory is not None:
                extensions = {'Photos': {'.jpg', '.jpeg', '.png'}, 'Books': {'.txt', '.epub'},
                              'Videos': {'.mp4', '.m4v', '.mkv', '.avi', '.mov', '.mpg'}}
                self.show_library(name, (LibraryRow(path.stem, 'device') for path in sorted(directory.rglob('*'))
                                         if path.suffix.casefold() in extensions[name] and path.is_file()))
        elif route == 'scan':
            self.show_library(name, (LibraryRow('Scan music now', 'scan_now'),
                                     LibraryRow('Scan specified folders', 'device')))
        elif route == 'scan_now':
            self.confirm_library_scan()
        else:
            self.select_music_library(row)

    def select_music_library(self, row):
        name, route, selected = row
        indices = sorted(self.music_indices(), key=lambda i: self.tracks[i].title.casefold())
        if route in ('albums', 'artist', 'decade'):
            allowed = set(selected) if route == 'artist' else set(indices)
            rows = []
            for album in sorted(self.albums, key=lambda value: value.name.casefold()):
                queue = tuple(i for i in album.tracks if i in allowed)
                if route == 'decade' and max((self.tracks[i].year for i in queue), default=0) // 10 != selected[0]:
                    continue
                if queue:
                    rows.append(LibraryRow(album.name, 'album', queue))
            if route == 'artist':
                rows.insert(0, LibraryRow('Songs', 'group', tuple(i for i in indices if i in allowed)))
            self.show_library(name, rows)
            return
        if route in ('artists', 'genres'):
            groups = defaultdict(list)
            for i in indices:
                track = self.tracks[i]
                artist = (track.album_artist or track.artist) if self.artist_group == 'Album Artist' else track.artist
                keys = (artist or 'Unknown Artist',) if route == 'artists' else track.genres
                for key in dict.fromkeys(keys):
                    groups[key].append(i)
            self.show_library(name, (LibraryRow(key, 'artist' if route == 'artists' else 'group', tuple(groups[key]))
                                     for key in sorted(groups, key=str.casefold)))
        elif route == 'era':
            music = set(indices)
            years = {max((self.tracks[i].year for i in album.tracks if i in music), default=0) // 10
                     for album in self.albums}
            self.show_library(name, (LibraryRow(f'{decade * 10}s', 'decade', (decade,))
                                     for decade in sorted(years - {0})))
        elif route == 'ratings':
            self.show_library(name, [LibraryRow(label, 'rated')
                                     for label in ('Top Rated', 'Loved', 'All Rated', 'Disliked', 'Albums')])
        elif route == 'playlists':
            self.show_library(name, [LibraryRow('New Playlist…', 'device'), LibraryRow('Import', 'import'),
                                     *(LibraryRow(label, 'group', queue) for label, queue in self.playlists.items())])
        elif route == 'import':
            paths = {track.path.relative_to(self.sd_card).as_posix().casefold(): i
                     for i, track in enumerate(self.tracks)
                     if self.sd_card and track.path and track.path.is_relative_to(self.sd_card)}
            title = self.library_title
            self.playlists.update(imported_playlists(self.sd_card, paths))
            self.back()
            self.select_music_library(LibraryRow(title, 'playlists'))
        elif route == 'shuffle':
            self.show_library(name, (LibraryRow('Shuffle Songs', 'shuffle_songs'),
                                     LibraryRow('Shuffle Albums', 'shuffle_albums'),
                                     LibraryRow('Shuffle Folders', 'shuffle_folders')))
        elif route in ('shuffle_songs', 'shuffle_albums', 'shuffle_folders'):
            self.shuffle_library(route, indices)
        else:
            if route == 'added':
                indices.sort(key=lambda i: self.tracks[i].modified, reverse=True)
            elif route == 'recent':
                indices = list(reversed(self.recent))
            elif route == 'most':
                indices = [i for i, _ in self.plays.most_common(100)]
            elif route == 'long':
                indices = sorted((i for i in indices if self.tracks[i].duration > 600),
                                 key=lambda i: -self.tracks[i].duration)
            elif route == 'hires':
                indices = [i for i in indices if self.tracks[i].hi_res]
            elif route == 'rated':
                indices = []
            elif route == 'search':
                if self.search_query is None or not (query := self.search_query()):
                    return
                indices = [i for i in indices if query.casefold() in ' '.join((
                    self.tracks[i].title, self.tracks[i].album, self.tracks[i].artist,
                    self.tracks[i].album_artist, *self.tracks[i].genres)).casefold()]
            self.show_library(name, self.song_library_rows(indices))

    def shuffle_library(self, route, indices):
        if route == 'shuffle_songs':
            sets = [(i,) for i in indices]
        elif route == 'shuffle_albums':
            included = set(indices)
            sets = [tuple(i for i in album.tracks if i in included) for album in self.albums]
        else:
            folders = defaultdict(list)
            for index in sorted(indices, key=lambda i: str(self.tracks[i].path).casefold()):
                path = self.tracks[index].path
                folders[path.parent if path else None].append(index)
            sets = list(folders.values())
        random.shuffle(sets)
        queue = [index for group in sets for index in group]
        if queue:
            self.play(queue[0], queue, route)
        else:
            self.hint = 'No tracks'

    def record_play(self, index):
        if not self.in_music_library(index):
            return
        self.plays[index] += 1
        self.recent.pop(index, None)
        self.recent[index] = None

    def rows(self):
        if self.page == 'library':
            return self.library_rows
        if self.page == 'folder':
            if self.directory not in self.folder_cache:
                self.folder_cache[self.directory] = folder_rows(self.tracks, self.directory)
            return self.folder_cache[self.directory]
        if self.page == 'album' and self.album is not None:
            return [(self.tracks[index].title, index) for index in self.album.tracks]
        if self.page == 'localmusic':
            return [(track.title, i) for i, track in enumerate(self.tracks)]
        return self.menu()

    def play(self, index, queue, queue_shuffle=''):
        self.queue_shuffle = queue_shuffle
        self.current, self.queue, self.elapsed, self.paused = index, tuple(queue), 0.0, False
        self.record_play(index)
        self.open('playing')

    def enter(self):
        if self.page == 'buddy' and self.buddy is not None:
            self.buddy_key(218)
            return
        if self.page == 'arcade' and self.arcade is not None:
            game = self.arcade.game
            self.arcade.center()
            if game in ('vortex', 'snake', 'breakout') and self.arcade.scene == 'games':
                self.back()
            return
        if self.page == 'home':
            key, title = self.home_items()[self.cursor]
            if key == 'localmusic':
                self.open_library()
            elif key == 'stream' and self.custom:
                rows = (LibraryRow(name, 'card-app') for name, _ in card_app_entries(self.sd_card, games=False))
                self.show_library(title, rows)
                if not self.library_rows:
                    self.hint = 'No installed streaming apps'
            elif key == 'rockbox':
                self.hint = 'Rockbox is installed on the SD card. Start it on the Q2.'
            elif key in ('playing', 'coverflow', 'folder', 'settings', 'playset'):
                self.open(key)
                self.directory = (self.folder_root or self.sd_card) if key == 'folder' else self.sd_card
            elif key == 'sysset':
                self.open('system')
            else:
                self.hint = f'{title} requires the device'
        elif self.page == 'library':
            if self.cursor < len(self.library_rows):
                self.select_library(self.library_rows[self.cursor])
        elif self.page == 'coverflow':
            if self.albums:
                self.open('album')
                # open resets the cursor; history retains the selected cover.
                self.album = self.albums[self.history[-1][1]]
        elif self.page in ('folder', 'localmusic', 'album'):
            rows = self.rows()
            if rows:
                target = rows[self.cursor][1]
                if isinstance(target, Path):
                    self.open('folder')
                    self.directory = target
                else:
                    self.play(target, [index for _, index in rows if isinstance(index, int)])
        elif self.page in SETTINGS:
            rows = self.menu()
            if self.cursor < len(rows):
                name, _, target = rows[self.cursor]
                self.select_setting(name, target)
        elif self.page in ('playing', 'lyrics'):
            self.toggle()

    def toggle(self):
        if self.page == 'arcade' and self.arcade is not None:
            self.arcade.button('down')
            return
        if self.tracks:
            self.paused = not self.paused

    def lyrics_page(self):
        if self.page == 'playing':
            self.open('lyrics')
        elif self.page == 'lyrics':
            self.back()

    def button(self, button):
        if self.page == 'buddy':
            if button in ('left', 'right'):
                self.step_track(-1 if button == 'left' else 1)
            elif button == 'center':
                self.enter()
            elif button == 'up':
                self.back()
            elif button == 'down':
                self.toggle()
            return
        if self.page == 'arcade' and self.arcade is not None:
            if button == 'up':
                self.back()
            elif button == 'center':
                self.enter()
            else:
                self.arcade.button(button)
            return
        actions = {'up': self.back, 'down': self.toggle, 'center': self.enter,
                   'left': lambda: self.move(-1), 'right': lambda: self.move(1)}
        if button in actions:
            actions[button]()

    def frame(self, fonts):
        if self.page == 'buddy' and self.buddy is not None:
            return self.buddy.image, []
        if self.page == 'arcade' and self.arcade is not None:
            return self.arcade.render_screen(), []
        background_playback = None if self.paused else False
        if self.page == 'home' and self.firmware:
            frame, hits = render_browse(self.firmware, fonts, self.style, self.page, self.cursor,
                                        self.tracks, background_playback, self.battery, self.firmware_home())
            return frame, [(i, 0, y, SIZE[0], end) for i, y, end in hits]
        if self.page == 'coverflow':
            return render_albums(fonts, self.tracks, self.albums, self.cursor, self.firmware,
                                 self.light, background_playback, self.battery)
        if self.page in ('playing', 'lyrics') and self.tracks:
            track = self.tracks[self.current]
            position = self.queue.index(self.current) + 1
            if self.page == 'lyrics':
                return render_lyrics(track, fonts, self.elapsed, position, len(self.queue),
                                     self.paused, self.battery, self.firmware, self.light), []
            frame, _face = render(track, fonts, self.style, position, len(self.queue),
                                  self.scroll, self.paused, self.firmware, self.elapsed, self.battery)
            return frame, []
        title = SETTINGS[self.page][0] if self.page in SETTINGS else {
            'home': 'Home', 'folder': 'Folders', 'localmusic': 'Songs'}.get(self.page, 'Now Playing')
        if self.page == 'home':
            rows = [(label, '›', 'default') for _key, label in self.home_items()]
        elif self.page == 'library':
            title = self.library_title
            rows = [(row.name, '›' if row.route not in ('track', 'album') else '', 'default')
                    for row in self.library_rows]
        elif self.page in ('folder', 'localmusic', 'album'):
            if self.page == 'folder' and self.directory and self.directory != self.sd_card:
                title = self.directory.name
            if self.page == 'album' and self.album is not None:
                title = self.album.name
            rows = []
            for name, target in self.rows():
                name, face = fonts.artist(name) if self.page == 'folder' else (name, 'default')
                rows.append((name, '›' if isinstance(target, Path) else '', face))
        elif self.page in ('playing', 'lyrics'):
            rows = []
        else:
            rows = [(name, value or ('›' if key in SETTINGS else ''), 'default')
                    for name, value, key in self.menu()]
            self.cursor = min(self.cursor, max(0, len(rows) - 1))
        frame, hits = render_menu(fonts, title, rows, self.cursor, self.light, background_playback,
                                  self.battery, self.firmware, self.page == 'store')
        return frame, [(i, 0, y, SIZE[0], end) for i, y, end in hits]


def desktop(fonts, style, tracks, firmware=None, unsquashfs='unsquashfs', sd_card=None, shell=DEFAULT_SHELL,
            enable_audio=True, ffplay=None):
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk

    from PIL import ImageTk

    ui = Simulator(style, tracks, firmware, sd_card)
    ui.shell = shell
    audio = FFplayAudio(ffplay) if enable_audio else None
    window = tk.Tk()
    window.title('Shanling Q2 Simulator')
    ui.search_query = lambda: simpledialog.askstring('Search', 'Search the library', parent=window)
    window.configure(background='#242122')
    screen = tk.Canvas(window, width=DEVICE_SIZE[0], height=DEVICE_SIZE[1], highlightthickness=0,
                       background='#242122', takefocus=True)
    screen.pack()
    picture = screen.create_image(0, 0, anchor='nw')
    status = ttk.Label(window, wraplength=395, padding=(9, 4, 9, 4))
    status.pack(fill='x')
    controls = ttk.Frame(window, padding=8)
    controls.pack(fill='x')
    finishes = tuple(SHELL_FINISHES)
    finish_index = finishes.index(shell)
    photo: ImageTk.PhotoImage | None = None
    hits: list[tuple[int, int, int, int, int]] = []
    pressed, angle, accumulated, dragged = None, None, 0.0, False
    last_tick = time.monotonic()

    def open_firmware():
        nonlocal fonts
        path = filedialog.askopenfilename(filetypes=[('Q2 firmware', '*.zip *.tar'), ('All files', '*')])
        if path:
            try:
                package = load_firmware(Path(path), unsquashfs)
                loaded_fonts = Fonts(firmware=package)
            except ERRORS as exc:
                messagebox.showerror('Could not open firmware', str(exc), parent=window)
            else:
                ui.close_arcade()
                ui.firmware, fonts = package, loaded_fonts
                ui.page, ui.cursor, ui.history, ui.hint = 'home', 0, [], ''
        screen.focus_set()

    def open_card():
        path = filedialog.askdirectory(mustexist=True, initialdir=ui.sd_card or Path.cwd())
        if path:
            root = Path(path).resolve()
            try:
                loaded, failures = scan_card(root)
            except ERRORS as exc:
                messagebox.showerror('Could not open SD folder', str(exc), parent=window)
            else:
                ui.mount_card(loaded, root)
                if failures:
                    skipped_tracks(failures)
        screen.focus_set()

    def skipped_tracks(failures):
        preview = failures[:8] + ([f'… and {len(failures) - 8} more'] if len(failures) > 8 else [])
        messagebox.showwarning('Could not open some tracks', '\n'.join(preview), parent=window)

    def tap(x, y):
        if not (0 <= x < SIZE[0] and 0 <= y < SIZE[1]):
            return
        if ui.page in ('playing', 'lyrics'):
            ui.lyrics_page()
            return
        if ui.page == 'home' and ui.firmware and not ui.firmware.custom and (x < 60 or x > SIZE[0] - 60):
            ui.move(-1 if x < 60 else 1)
            return
        for index, left, top, right, bottom in hits:
            if left <= x < right and top <= y < bottom:
                ui.cursor = index
                ui.enter()
                return

    buddy_touch = False

    def touch(kind, event):
        x = max(0, min(SIZE[0] - 1, event.x - SCREEN_AT[0]))
        y = max(0, min(SIZE[1] - 1, event.y - SCREEN_AT[1]))
        if ui.buddy is not None:
            ui.buddy.send(f't {kind} {x} {y}')

    def press(event):
        nonlocal pressed, angle, accumulated, dragged, buddy_touch
        buddy_touch = (ui.buddy is not None and SCREEN_AT[0] <= event.x < SCREEN_AT[0] + SIZE[0]
                       and SCREEN_AT[1] <= event.y < SCREEN_AT[1] + SIZE[1])
        if buddy_touch:
            touch('d', event)
        screen.focus_set()
        pressed = wheel_button(event.x, event.y)
        angle = wheel_angle(event.x, event.y) if pressed and pressed != 'center' else None
        accumulated, dragged = 0.0, False

    def drag(event):
        nonlocal angle, accumulated, dragged
        if buddy_touch:
            touch('m', event)
            return
        if angle is None or math.hypot(event.x - WHEEL[0], event.y - WHEEL[1]) < CENTRE:
            return
        new_angle = wheel_angle(event.x, event.y)
        if ui.buddy is not None:
            accumulated += wheel_delta(angle, new_angle)
            angle = new_angle
            if dragged or abs(accumulated) >= math.pi / 45:
                ui.buddy_drag_wheel(accumulated)
                accumulated, dragged = 0.0, True
            return
        if ui.page == 'arcade' and ui.arcade is not None:
            accumulated += wheel_delta(angle, new_angle)
            angle = new_angle
            if dragged or abs(accumulated) >= math.pi / 45:
                ui.arcade.on_wheel(accumulated)
                accumulated, dragged = 0.0, True
            return
        accumulated += wheel_delta(angle, new_angle)
        angle = new_angle
        detent = DETENT * 50 / ui.wheel_sensitivity
        if abs(accumulated) >= detent / 3:
            dragged = True
        ticks = math.trunc(accumulated / detent)
        if ticks:
            ui.move(ticks)
            accumulated -= ticks * detent

    def release(event):
        nonlocal buddy_touch
        if buddy_touch:
            touch('u', event)
            buddy_touch = False
            return
        if pressed:
            if not dragged and pressed == wheel_button(event.x, event.y):
                ui.button(pressed)
        else:
            tap(event.x - SCREEN_AT[0], event.y - SCREEN_AT[1])

    def refresh():
        nonlocal photo, hits, last_tick
        now = time.monotonic()
        ui.advance(now - last_tick)
        last_tick = now
        if audio is not None:
            audio.sync(ui)
        frame, hits = ui.frame(fonts)
        gain = int(ui.brightness.rstrip('%')) / 100
        if gain < 1:
            frame = Image.blend(Image.new('RGB', SIZE), frame, gain)
        photo = ImageTk.PhotoImage(device_frame(frame, finishes[finish_index]))
        screen.itemconfigure(picture, image=photo)
        source = ui.firmware.name if ui.firmware else 'Checkout preview'
        if ui.page in ('playing', 'lyrics') and ui.tracks:
            detail = ui.hint or f'Artist font: {fonts.artist(ui.tracks[ui.current].artist)[1]} · Click display to switch lyrics'
        elif ui.page == 'buddy':
            detail = 'Click or drag Buddy · Wheel to spin · Enter to act · Esc opens its menu'
        elif ui.page == 'arcade' and ui.arcade is not None and ui.arcade.game in ('sudoku', 'solitaire'):
            detail = 'Wheel or arrows to move · Enter to select · Space for new game · Esc to go back'
        elif ui.page == 'arcade' and ui.arcade is not None and ui.arcade.game in ('snake', 'vortex', 'breakout'):
            detail = ('Left/Right to turn' if ui.arcade.game == 'snake' else 'Drag wheel or press Left/Right · Enter to launch')
            detail += ' · Space to pause · Esc for menu'
        else:
            detail = ui.hint or (f'SD: {ui.sd_card.name} · {len(ui.tracks)} tracks' if ui.sd_card else
                                 'Drag the wheel or use the arrow keys · Enter to select')
        if audio is not None and audio.notice:
            detail += f' · {audio.notice}'
        status.configure(text=f'{source} · {detail}')
        ui.scroll += 2
        window.after(16 if ui.page in ('arcade', 'buddy') else 90, refresh)

    def cycle_shell():
        nonlocal finish_index
        finish_index = (finish_index + 1) % len(finishes)
        ui.shell = finishes[finish_index]
        color_button.configure(text=f'Shell color: {finishes[finish_index]}')
        screen.focus_set()

    ttk.Button(controls, text='Open firmware', command=open_firmware).pack(side='left', padx=(0, 5))
    ttk.Button(controls, text='Mount SD folder', command=open_card).pack(side='left', padx=(0, 5))
    color_button = ttk.Button(controls, text=f'Shell color: {shell}', command=cycle_shell, width=25)
    color_button.pack(side='left')

    battery_controls = ttk.Frame(window, padding=(8, 0, 8, 8))
    battery_controls.pack(fill='x')
    battery_text = tk.StringVar(value=str(ui.battery.percent))
    charging = tk.BooleanVar(value=ui.battery.charging)

    def valid_battery(value):
        return not value or (len(value) <= 3 and value.isascii() and value.isdecimal() and int(value) <= 100)

    def update_battery(*_):
        if value := battery_text.get():
            ui.battery = replace(ui.battery, percent=int(value))

    def end_battery_edit(_):
        battery_text.set(str(ui.battery.percent))

    def toggle_charging():
        ui.battery = replace(ui.battery, charging=charging.get())

    ttk.Label(battery_controls, text='Battery %').pack(side='left', padx=(0, 6))
    battery_entry = ttk.Entry(battery_controls, textvariable=battery_text, width=5, validate='key',
                              validatecommand=(window.register(valid_battery), '%P'))
    battery_entry.pack(side='left')
    battery_text.trace_add('write', update_battery)
    battery_entry.bind('<FocusOut>', end_battery_edit)
    battery_entry.bind('<Return>', lambda _: screen.focus_set())
    ttk.Checkbutton(battery_controls, text='Charging', variable=charging, command=toggle_charging).pack(
        side='left', padx=(12, 0))

    screen.bind('<ButtonPress-1>', press)
    screen.bind('<B1-Motion>', drag)
    screen.bind('<ButtonRelease-1>', release)
    def vertical(step):
        if ui.page == 'arcade' and ui.arcade is not None and ui.arcade.game in ('sudoku', 'solitaire'):
            ui.arcade.puzzle.move(step, vertical=True)
        else:
            ui.move(step)

    screen.bind('<Up>', lambda _: vertical(-1))
    screen.bind('<Down>', lambda _: vertical(1))
    screen.bind('<Button-4>', lambda _: ui.move(-1))
    screen.bind('<Button-5>', lambda _: ui.move(1))

    def direction(button, step):
        if ui.page == 'arcade' and ui.arcade is not None and ui.arcade.game == 'snake':
            ui.button(button)
        else:
            ui.move(step)

    screen.bind('<Left>', lambda _: direction('left', -1))
    screen.bind('<Right>', lambda _: direction('right', 1))
    screen.bind('<MouseWheel>', lambda event: ui.move(-1 if event.delta > 0 else 1))
    screen.bind('<Return>', lambda _: ui.enter())
    screen.bind('<space>', lambda _: ui.toggle() if ui.page in ('playing', 'lyrics', 'arcade', 'buddy') else ui.enter())
    for key in ('<Escape>', '<BackSpace>'):
        screen.bind(key, lambda _: ui.back())
    screen.bind('<Key-l>', lambda _: ui.lyrics_page())
    def close_window():
        ui.close_arcade()
        if audio is not None:
            audio.close()
        window.destroy()

    window.protocol('WM_DELETE_WINDOW', close_window)
    window.after_idle(screen.focus_set)
    refresh()
    window.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tracks', nargs='*', type=Path, help='MP3 or FLAC files')
    parser.add_argument('--theme', choices=THEMES, default=THEMES[0])
    parser.add_argument('--stock-font', type=Path, help='extracted Shanling default.ttf')
    parser.add_argument('--fonts-dir', type=Path, help='directory holding packaged bold.ttf and classic-light.ttf')
    parser.add_argument('--firmware', type=Path, help='official Q2 firmware ZIP or an update.tar')
    parser.add_argument('--game-elf', type=Path, help='run an ABI v1 MIPS game in the generic game runner (not a firmware image)')
    parser.add_argument('--unsquashfs', default='unsquashfs', help='squashfs-tools executable (defaults to PATH)')
    parser.add_argument('--sd-card', type=Path, help='directory to mount as the simulated SD card')
    parser.add_argument('--snapshot', type=Path, help='save one PNG and exit without opening a window')
    parser.add_argument('--no-audio', action='store_true', help='disable ffplay host audio')
    parser.add_argument('--ffplay', help='path to ffplay executable (from FFmpeg)')
    parser.add_argument('--screen', choices=('home', 'folder', 'library', 'localmusic', 'coverflow', 'playing', 'lyrics', *SETTINGS),
                        default='playing', help='screen to capture with --snapshot')
    parser.add_argument('--with-device', action='store_true', help='include the enclosure and wheel in the screenshot')
    parser.add_argument('--shell', choices=tuple(SHELL_FINISHES), default=DEFAULT_SHELL,
                        help='shell color for the window or a screenshot with --with-device')
    args = parser.parse_args()
    if args.game_elf:
        if args.firmware or args.sd_card or args.tracks:
            parser.error('--game-elf is a standalone ABI game; do not combine with firmware or music')
        from universal_game import UniversalGame
        try:
            game = UniversalGame(args.game_elf)
            if args.snapshot:
                image = game.image()
                if args.with_device:
                    image = device_frame(image, args.shell)
                image.save(args.snapshot)
                print(f'{args.snapshot} (ABI v1 game: {game.name})')
            else:
                from universal_game import main as run_generic
                old_args = sys.argv
                try:
                    sys.argv = [old_args[0], '--elf', str(args.game_elf)]
                    run_generic()
                finally:
                    sys.argv = old_args
        except Exception as exc:
            parser.exit(1, f'{parser.prog}: generic game failed: {exc}\n')
        return
    if args.firmware and (args.stock_font or args.fonts_dir):
        parser.error('--firmware supplies the fonts itself; use --stock-font and --fonts-dir in checkout preview mode')
    if (args.screen != 'playing' or args.with_device) and not args.snapshot:
        parser.error('--screen and --with-device require --snapshot')
    if args.sd_card and args.tracks:
        parser.error('choose an SD card folder or individual tracks')
    try:
        firmware = load_firmware(args.firmware, args.unsquashfs) if args.firmware else None
        fonts = Fonts(args.stock_font, args.fonts_dir, firmware)
        root = args.sd_card.resolve() if args.sd_card else None
        if root is not None:
            tracks, failures = scan_card(root)
            for failure in failures:
                print(f'Skipped track: {failure}', file=sys.stderr)
        else:
            tracks = [read_track(path) for path in args.tracks] or list(SAMPLES)
        if args.snapshot:
            if args.screen == 'playing' and tracks:
                image, face = render(tracks[0], fonts, args.theme, count=len(tracks), firmware=firmware)
                detail = f'title font: {face}; artist font: {fonts.artist(tracks[0].artist)[1]}'
            else:
                preview = Simulator(args.theme, tracks, firmware, root)
                if args.screen == 'library':
                    preview.open_library()
                else:
                    preview.page = args.screen
                image, _ = preview.frame(fonts)
                detail = args.screen
            if args.with_device:
                image = device_frame(image, args.shell)
            image.save(args.snapshot)
            source = firmware.name if firmware else 'checkout preview'
            print(f'{args.snapshot} ({source}; {detail})')
        else:
            desktop(fonts, args.theme, tracks, firmware, args.unsquashfs, root, args.shell,
                    enable_audio=not args.no_audio, ffplay=args.ffplay)
    except ERRORS as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')


if __name__ == '__main__':
    main()
