#!/usr/bin/env python3
# mypy: disable-error-code="import-not-found,import-untyped"
"""Interactive desktop UI preview for Shanling Q2 and Q2 Pod firmware."""
import argparse
import bisect
import io
import math
import random
import re
import sys
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError
from mutagen import File, MutagenError
from mutagen.id3 import APIC
from PIL import Image, ImageDraw, ImageFont, ImageOps

import build
import ipod
import theme
from simulator_device import (CENTRE, DEFAULT_SHELL, DETENT, DEVICE_SIZE, SCREEN_AT, SHELL_FINISHES, WHEEL,
                              device_frame, wheel_angle, wheel_button, wheel_delta)
from simulator_firmware import load_firmware

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
    album_artist = (tags.get('albumartist') or [artist])[0]
    return Track(title, artist, album, art, path.name, path.resolve(), album_artist,
                 float(getattr(audio.info, 'length', 0)), read_lyrics(path))


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
        artist = track.album_artist or track.artist
        name = track.album or (track.path.parent.name if track.path else 'Unknown Album')
        grouped[name, artist].append(i)
    albums = [Album(name, artist, tuple(indices),
                    next((i for i in indices if tracks[i].art), indices[0]))
              for (name, artist), indices in grouped.items()]
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


def display_page(fonts, title, light):
    paper, ink, muted = ('#f7f7f7', '#171717', '#696969') if light else ('#161722', '#f7f4f4', '#a4a4b3')
    frame = Image.new('RGB', SIZE, paper)
    draw = ImageDraw.Draw(frame)
    draw.rectangle((0, 0, SIZE[0], 29), fill='#e5e5e5' if light else '#222431')
    label(frame, fonts, 'default', title, (26, 0, 323, 30), 18, ink)
    return frame, draw, ink, muted


def render_menu(fonts, title, rows, selected, light):
    frame, draw, ink, muted = display_page(fonts, title, light)
    hits = []
    if not rows:
        label(frame, fonts, 'default', 'No tracks', (24, 113, 327, 58), 20, muted, align='center')
    start = max(0, selected - 5)
    for index, (text, value, face) in enumerate(rows[start:start + 6], start):
        y = 38 + 45 * (index - start)
        if index == selected:
            draw.rounded_rectangle((12, y, 362, y + 41), 8, '#cfe7fb' if light else '#344565')
        if value:
            label(frame, fonts, 'default', value, (220, y, 127, 41), 16, muted, align='right')
        label(frame, fonts, face, text, (22, y, 200 if value else 323, 41), 21, ink)
        hits.append((index, y, y + 42))
    return frame, hits


def album_image(album, tracks, firmware, side):
    sample = tracks[album.cover]
    if not sample.art and firmware:
        for name in ('default_album_flow', 'default_album_coverflow', 'default_album_big'):
            if name in firmware.images:
                return ImageOps.fit(firmware_image(firmware.images[name]), (side, side)).convert('RGB')
    return cover(sample, side, False)[0]


def render_albums(fonts, tracks, albums, selected, firmware, light):
    grid = firmware is not None and not firmware.custom
    frame, draw, ink, muted = display_page(fonts, 'Album Wall' if grid else 'Cover Flow', light)
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


def render_lyrics(track, fonts, elapsed, position, count):
    frame, draw, ink, muted = display_page(fonts, 'Lyrics', False)
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


def render_browse(firmware, fonts, style, page, selected, tracks):
    """Draw the selected Home card or list. Return rows with mouse hit targets."""
    light = firmware.custom and style == 'classic-light'
    paper, ink, muted = ('#f7f7f7', '#171717', '#707070') if light else ('#000000', '#ffffff', '#a0a0a0')
    frame = Image.new('RGB', SIZE, paper)
    draw = ImageDraw.Draw(frame)
    draw.rectangle((0, 0, SIZE[0], 29), fill='#e5e5e5' if light else '#171717')
    title = {'home': 'Home', 'folder': 'Folders', 'localmusic': 'Songs'}[page]
    label(frame, fonts, 'default', title, (14, 0, 180, 30), 18, ink)
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
        rows = [(entry.label, 'default', entry.image, entry.row.box[1] + 30, entry.row.box[3])
                for entry in firmware.home]
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


def render_firmware(track, fonts, firmware, style, position, count, scroll, paused, elapsed):
    page = firmware.page
    light = firmware.custom and style == 'classic-light'
    offset = 30  # the AWTK page sits below the system bar
    paper = '#f7f7f7' if light else packaged_style(firmware, page['playing_page'], 'bg_color', '#000000')
    ink, secondary = ('#171717', '#555555') if light else ('#ffffff', '#cccccc')
    frame = Image.new('RGB', SIZE, paper)
    draw = ImageDraw.Draw(frame)
    draw.rectangle((0, 0, SIZE[0], offset - 1), fill='#e5e5e5' if light else '#171717')
    label(frame, fonts, 'default', 'Now Playing', (14, 0, 180, offset), 18, ink)

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
    if firmware.custom:
        config = theme_config(style)
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


def render(track, fonts, style, position=1, count=1, scroll=0, paused=False, firmware=None, elapsed=0.0):
    if firmware is not None:
        return render_firmware(track, fonts, firmware, style, position, count, scroll, paused, elapsed)
    classic = style == 'classic-light'
    config = theme_config(style)
    paper, ink, secondary = ('#f7f7f7', '#171717', '#555555') if classic else (
        '#141414', '#ffffff', '#aaaaaa')
    image = Image.new('RGB', SIZE, paper)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 374, 29), fill='#e5e5e5' if classic else '#202020')
    label(image, fonts, 'default', 'Now Playing', (14, 0, 180, 30), 18, ink)
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


HOME_ROUTES = (('playing', 'Now Playing'), ('localmusic', 'Library'), ('coverflow', 'Cover Flow'),
               ('folder', 'Folders'), ('settings', 'Settings'))


class Simulator:
    def __init__(self, style, tracks, firmware=None, sd_card=None):
        self.style, self.tracks, self.firmware, self.sd_card = style, tracks, firmware, sd_card
        self.page, self.cursor = 'home', 0
        self.current, self.scroll, self.paused, self.elapsed = 0, 0, True, 0.0
        self.directory, self.album = sd_card, None
        self.folder_cache: dict[Path | None, list[tuple[str, Path | int]]] = {}
        self.history = []
        self.queue = tuple(range(len(tracks)))
        self.albums = albums_for(tracks)
        self.brightness, self.shuffle, self.repeat, self.sort = '100%', 'Off', 'Off', 'Album'
        self.hint = ''

    @property
    def light(self):
        return (self.firmware is None or self.firmware.custom) and self.style == 'classic-light'

    def replace_tracks(self, tracks, root=None):
        self.tracks, self.sd_card, self.directory = tracks, root, root
        self.albums, self.album = albums_for(tracks, self.sort), None
        self.folder_cache.clear()
        self.queue = tuple(range(len(tracks)))
        self.current, self.cursor, self.scroll, self.elapsed, self.paused = 0, 0, 0, 0.0, True
        self.page = 'folder' if root else 'home'
        self.history = [('home', 0, root, None)] if root else []

    def menu(self):
        if self.page == 'settings':
            return [('Display', '', 'display'), ('Playback', '', 'playset'), ('About', '', 'about')]
        if self.page == 'display':
            rows = [('Brightness', self.brightness, 'brightness'), ('Cover Flow sort', self.sort, 'sort')]
            if self.firmware is None or self.firmware.custom:
                rows.insert(0, ('Theme', self.style.replace('-', ' ').title(), 'theme'))
            return rows
        if self.page == 'playset':
            return [('Shuffle', self.shuffle, 'shuffle'), ('Repeat', self.repeat, 'repeat')]
        return [('Firmware', self.firmware.version if self.firmware else 'Checkout', None),
                ('Tracks', str(len(self.tracks)), None), ('Albums', str(len(self.albums)), None)]

    def open(self, page):
        self.history.append((self.page, self.cursor, self.directory, self.album))
        self.page, self.cursor, self.scroll, self.hint = page, 0, 0, ''

    def back(self):
        if self.history:
            self.page, self.cursor, self.directory, self.album = self.history.pop()
        else:
            self.page, self.cursor = 'home', 0
        self.hint, self.scroll = '', 0

    def move(self, step):
        if self.page in ('playing', 'lyrics'):
            self.step_track(step)
        else:
            count = (len(self.albums) if self.page == 'coverflow' else
                     len(self.firmware.home if self.firmware else HOME_ROUTES) if self.page == 'home' else
                     len(self.rows()))
            if count:
                self.cursor = (self.cursor + step) % count
        self.hint, self.scroll = '', 0

    def step_track(self, step, automatic=False):
        if not self.queue:
            return
        position = self.queue.index(self.current)
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

    def advance(self, delta):
        if not self.paused and self.tracks:
            self.elapsed += delta
            duration = self.tracks[self.current].duration
            if duration > 0 and self.elapsed >= duration:
                self.elapsed = duration
                self.step_track(1, automatic=True)

    def cycle(self, key):
        choices = {'theme': ('style', THEMES), 'brightness': ('brightness', ('100%', '75%', '50%', '25%')),
                   'sort': ('sort', ('Album', 'Artist')), 'shuffle': ('shuffle', ('Off', 'On')),
                   'repeat': ('repeat', ('Off', 'All', 'One'))}
        if key not in choices:
            return
        name, values = choices[key]
        setattr(self, name, values[(values.index(getattr(self, name)) + 1) % len(values)])
        if key == 'sort':
            self.albums = albums_for(self.tracks, self.sort)

    def rows(self):
        if self.page == 'folder':
            if self.directory not in self.folder_cache:
                self.folder_cache[self.directory] = folder_rows(self.tracks, self.directory)
            return self.folder_cache[self.directory]
        if self.page == 'album' and self.album is not None:
            return [(self.tracks[index].title, index) for index in self.album.tracks]
        if self.page == 'localmusic':
            return [(track.title, i) for i, track in enumerate(self.tracks)]
        return self.menu()

    def play(self, index, queue):
        self.current, self.queue, self.elapsed, self.paused = index, tuple(queue), 0.0, False
        self.open('playing')

    def enter(self):
        if self.page == 'home':
            if self.firmware:
                entry = self.firmware.home[self.cursor]
                key, title = entry.key, entry.label
            else:
                key, title = HOME_ROUTES[self.cursor]
            if key in ('playing', 'localmusic', 'coverflow', 'folder', 'settings', 'playset'):
                self.open(key)
                self.directory = self.sd_card
            elif key == 'sysset':
                self.open('settings')
            else:
                self.hint = f'{title} requires the device'
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
        elif self.page == 'settings':
            self.open(self.menu()[self.cursor][2])
        elif self.page in ('display', 'playset'):
            self.cycle(self.menu()[self.cursor][2])
        elif self.page in ('playing', 'lyrics'):
            self.toggle()

    def toggle(self):
        if self.tracks:
            self.paused = not self.paused

    def lyrics_page(self):
        if self.page == 'playing':
            self.open('lyrics')
        elif self.page == 'lyrics':
            self.back()

    def button(self, button):
        actions = {'up': self.back, 'down': self.toggle, 'center': self.enter,
                   'left': lambda: self.move(-1), 'right': lambda: self.move(1)}
        if button in actions:
            actions[button]()

    def frame(self, fonts):
        if self.page == 'home' and self.firmware:
            frame, hits = render_browse(self.firmware, fonts, self.style, self.page, self.cursor, self.tracks)
            return frame, [(i, 0, y, SIZE[0], end) for i, y, end in hits]
        if self.page == 'coverflow':
            return render_albums(fonts, self.tracks, self.albums, self.cursor, self.firmware, self.light)
        if self.page in ('playing', 'lyrics') and self.tracks:
            track = self.tracks[self.current]
            position = self.queue.index(self.current) + 1
            if self.page == 'lyrics':
                return render_lyrics(track, fonts, self.elapsed, position, len(self.queue)), []
            frame, _face = render(track, fonts, self.style, position, len(self.queue),
                                  self.scroll, self.paused, self.firmware, self.elapsed)
            return frame, []
        title = {'home': 'Home', 'folder': 'Folders', 'localmusic': 'Songs', 'settings': 'Settings',
                 'display': 'Display', 'playset': 'Playback', 'about': 'About'}.get(self.page, 'Now Playing')
        if self.page == 'home':
            rows = [(label, '›', 'default') for _key, label in HOME_ROUTES]
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
            rows = [(name, value or ('›' if key else ''), 'default') for name, value, key in self.menu()]
        frame, hits = render_menu(fonts, title, rows, self.cursor, self.light)
        return frame, [(i, 0, y, SIZE[0], end) for i, y, end in hits]


def desktop(fonts, style, tracks, firmware=None, unsquashfs='unsquashfs', sd_card=None, shell=DEFAULT_SHELL):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    from PIL import ImageTk

    ui = Simulator(style, tracks, firmware, sd_card)
    window = tk.Tk()
    window.title('Shanling Q2 Simulator')
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
                ui.replace_tracks(loaded, root)
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

    def press(event):
        nonlocal pressed, angle, accumulated, dragged
        screen.focus_set()
        pressed = wheel_button(event.x, event.y)
        angle = wheel_angle(event.x, event.y) if pressed and pressed != 'center' else None
        accumulated, dragged = 0.0, False

    def drag(event):
        nonlocal angle, accumulated, dragged
        if angle is None or math.hypot(event.x - WHEEL[0], event.y - WHEEL[1]) < CENTRE:
            return
        new_angle = wheel_angle(event.x, event.y)
        accumulated += wheel_delta(angle, new_angle)
        angle = new_angle
        if abs(accumulated) >= DETENT / 3:
            dragged = True
        ticks = math.trunc(accumulated / DETENT)
        if ticks:
            ui.move(ticks)
            accumulated -= ticks * DETENT

    def release(event):
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
        frame, hits = ui.frame(fonts)
        gain = int(ui.brightness.rstrip('%')) / 100
        if gain < 1:
            frame = Image.blend(Image.new('RGB', SIZE), frame, gain)
        photo = ImageTk.PhotoImage(device_frame(frame, finishes[finish_index]))
        screen.itemconfigure(picture, image=photo)
        source = ui.firmware.name if ui.firmware else 'Checkout preview'
        if ui.page in ('playing', 'lyrics') and ui.tracks:
            detail = f'Artist font: {fonts.artist(ui.tracks[ui.current].artist)[1]} · Click display to switch lyrics'
        else:
            detail = ui.hint or (f'SD: {ui.sd_card.name} · {len(ui.tracks)} tracks' if ui.sd_card else
                                 'Drag the wheel or use the arrow keys · Enter to select')
        status.configure(text=f'{source} · {detail}')
        ui.scroll += 2
        window.after(90, refresh)

    def cycle_shell():
        nonlocal finish_index
        finish_index = (finish_index + 1) % len(finishes)
        color_button.configure(text=f'Shell color: {finishes[finish_index]}')
        screen.focus_set()

    ttk.Button(controls, text='Open firmware', command=open_firmware).pack(side='left', padx=(0, 5))
    ttk.Button(controls, text='Mount SD folder', command=open_card).pack(side='left', padx=(0, 5))
    color_button = ttk.Button(controls, text=f'Shell color: {shell}', command=cycle_shell, width=25)
    color_button.pack(side='left')
    screen.bind('<ButtonPress-1>', press)
    screen.bind('<B1-Motion>', drag)
    screen.bind('<ButtonRelease-1>', release)
    for key in ('<Up>', '<Left>', '<Button-4>'):
        screen.bind(key, lambda _: ui.move(-1))
    for key in ('<Down>', '<Right>', '<Button-5>'):
        screen.bind(key, lambda _: ui.move(1))
    screen.bind('<MouseWheel>', lambda event: ui.move(-1 if event.delta > 0 else 1))
    screen.bind('<Return>', lambda _: ui.enter())
    screen.bind('<space>', lambda _: ui.toggle() if ui.page in ('playing', 'lyrics') else ui.enter())
    for key in ('<Escape>', '<BackSpace>'):
        screen.bind(key, lambda _: ui.back())
    screen.bind('<Key-l>', lambda _: ui.lyrics_page())
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
    parser.add_argument('--unsquashfs', default='unsquashfs', help='squashfs-tools executable (defaults to PATH)')
    parser.add_argument('--sd-card', type=Path, help='directory to mount as the simulated SD card')
    parser.add_argument('--snapshot', type=Path, help='save one PNG and exit without opening a window')
    parser.add_argument('--screen', choices=('home', 'folder', 'localmusic', 'coverflow', 'settings', 'playing', 'lyrics'),
                        default='playing', help='screen to capture with --snapshot')
    parser.add_argument('--with-device', action='store_true', help='include the enclosure and wheel in the screenshot')
    parser.add_argument('--shell', choices=tuple(SHELL_FINISHES), default=DEFAULT_SHELL,
                        help='shell color for the window or a screenshot with --with-device')
    args = parser.parse_args()
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
                preview.page = args.screen
                image, _ = preview.frame(fonts)
                detail = args.screen
            if args.with_device:
                image = device_frame(image, args.shell)
            image.save(args.snapshot)
            source = firmware.name if firmware else 'checkout preview'
            print(f'{args.snapshot} ({source}; {detail})')
        else:
            desktop(fonts, args.theme, tracks, firmware, args.unsquashfs, root, args.shell)
    except ERRORS as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')


if __name__ == '__main__':
    main()
