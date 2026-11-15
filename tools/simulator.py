#!/usr/bin/env python3
"""Interactive host preview of Q2 Pod's Now Playing screen."""
import argparse
import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
from mutagen import File, MutagenError
from mutagen.id3 import APIC
from PIL import Image, ImageDraw, ImageFont, ImageOps

import build
import ipod
import theme

SIZE = (375, 320)
THEMES = ('classic-light', 'modern', 'minimal')
FACES = ('default', 'bold', 'classic-light')


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    album: str
    art: bytes | None = None


SAMPLES = (
    Track('Thử ư â ă — Mưa Trên Phố Huế', 'Nguyễn Thị Hương', 'Kỷ Niệm Mùa Thu'),
    Track('夜の音楽', 'アーティスト', 'アルバム'),
    Track('Lo que la música me enseñó', 'Artista', 'Álbum'),
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
        (tag.data for tag in (raw.tags or {}).values() if isinstance(tag, APIC)), None)
    title = (tags.get('title') or [path.stem])[0]
    artist = (tags.get('artist') or [''])[0]
    album = (tags.get('album') or [''])[0]
    return Track(title, artist, album, art)


class Fonts:
    def __init__(self, stock=None, packaged=None):
        self.data = {}
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
        return all(ord(char) in self.cmaps[face] for char in text)

    @lru_cache(maxsize=32)
    def font(self, face, size):
        if face == 'default' and face not in self.data:
            return self.font('bold', size)
        with TTFont(io.BytesIO(self.data[face])) as font:
            metrics = font['hhea']
            size = size * font['head'].unitsPerEm / (metrics.ascent - metrics.descent)
        return ImageFont.truetype(io.BytesIO(self.data[face]), max(1, round(size)))


def label(image, fonts, face, text, box, size, color, scroll=0):
    x, y, w, h = box
    tile = Image.new('RGBA', (w, h))
    draw = ImageDraw.Draw(tile)
    font = fonts.font(face, size)
    width = draw.textlength(text, font=font)
    offset = 0
    if width > w - 4:
        offset = max(0, scroll - 24) % (int(width) + 28)
    draw.text((2 - offset, h // 2), text, font=font, anchor='lm', fill=color)
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


def render(track, fonts, style, position=1, count=1, scroll=0, paused=False):
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


def desktop(fonts, style, tracks):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    from PIL import ImageTk

    window = tk.Tk()
    window.title('Q2 Pod Simulator')
    current, scroll, paused = 0, 0, False
    selected = tk.StringVar(value=style)
    screen = ttk.Label(window)
    screen.pack()
    controls = ttk.Frame(window, padding=8)
    controls.pack(fill='x')
    status = ttk.Label(window, padding=(8, 0, 8, 8), wraplength=355)
    status.pack()

    def move(step):
        nonlocal current, scroll
        current = (current + step) % len(tracks)
        scroll = 0

    def toggle():
        nonlocal paused
        paused = not paused

    def open_tracks():
        nonlocal tracks, current, scroll
        paths = filedialog.askopenfilenames(filetypes=[('Audio', '*.mp3 *.flac'), ('All files', '*')])
        if not paths:
            return
        loaded, failures = [], []
        for path in paths:
            try:
                loaded.append(read_track(path))
            except (OSError, ValueError, MutagenError) as exc:
                failures.append(f'{Path(path).name}: {exc}')
        if loaded:
            tracks, current, scroll = loaded, 0, 0
        if failures:
            messagebox.showwarning('Could not open tracks', '\n'.join(failures), parent=window)
        screen.focus_set()

    def refresh():
        nonlocal scroll
        frame, face = render(tracks[current], fonts, selected.get(), current + 1,
                             len(tracks), scroll, paused)
        screen.image = ImageTk.PhotoImage(frame)
        screen.configure(image=screen.image)
        fallback = '' if 'default' in fonts.data else ' · Stock font unavailable, preview uses bundled bold'
        status.configure(text=f'Title font: {face}{fallback}')
        scroll += 2
        window.after(100, refresh)

    ttk.Button(controls, text='Open tracks', command=open_tracks).pack(side='left')
    for text, callback in (('‹', lambda: move(-1)), ('›', lambda: move(1)),
                           ('Play/Pause', toggle)):
        ttk.Button(controls, text=text, width=10 if text == 'Play/Pause' else 3,
                   command=callback).pack(side='left', padx=(4, 0))
    themes = ttk.Combobox(controls, textvariable=selected, values=THEMES, state='readonly', width=12)
    themes.pack(side='right')
    themes.bind('<<ComboboxSelected>>', lambda _: screen.focus_set())
    for key in ('<Up>', '<Left>', '<Button-4>'):
        screen.bind(key, lambda _: move(-1))
    for key in ('<Down>', '<Right>', '<Button-5>'):
        screen.bind(key, lambda _: move(1))
    screen.bind('<MouseWheel>', lambda event: move(-1 if event.delta > 0 else 1))
    screen.bind('<space>', lambda _: toggle())
    screen.bind('<Return>', lambda _: toggle())
    screen.bind('<Button-1>', lambda _: screen.focus_set())
    window.after_idle(screen.focus_set)
    refresh()
    window.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tracks', nargs='*', type=Path, help='MP3 or FLAC files')
    parser.add_argument('--theme', choices=THEMES, default=THEMES[0])
    parser.add_argument('--stock-font', type=Path, help='extracted Shanling default.ttf')
    parser.add_argument('--fonts-dir', type=Path, help='directory holding packaged bold.ttf and classic-light.ttf')
    parser.add_argument('--snapshot', type=Path, help='save one PNG and exit without opening a window')
    args = parser.parse_args()
    try:
        fonts = Fonts(args.stock_font, args.fonts_dir)
        tracks = [read_track(path) for path in args.tracks] or list(SAMPLES)
        if args.snapshot:
            image, face = render(tracks[0], fonts, args.theme, count=len(tracks))
            image.save(args.snapshot)
            print(f'{args.snapshot} (title font: {face})')
        else:
            desktop(fonts, args.theme, tracks)
    except (OSError, ValueError, MutagenError) as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')


if __name__ == '__main__':
    main()
