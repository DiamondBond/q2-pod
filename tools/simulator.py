#!/usr/bin/env python3
"""Interactive desktop UI preview for Shanling Q2 and Q2 Pod firmware."""
import argparse
import io
import unicodedata
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
from simulator_firmware import load_firmware

SIZE = (375, 320)
THEMES = ('classic-light', 'modern', 'minimal')
FACES = ('default', 'bold', 'classic-light')
ERRORS = (OSError, ValueError, MutagenError, TTLibError)


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    album: str
    art: bytes | None = None
    filename: str = ''


SAMPLES = (
    Track('Thử ư â ă — Mưa Trên Phố Huế', 'Nguyễn Thị Hương', 'Kỷ Niệm Mùa Thu',
          filename='1. a\u0309.flac'),
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
    title = (tags.get('title') or [path.stem])[0]
    artist = (tags.get('artist') or [''])[0]
    album = (tags.get('album') or [''])[0]
    return Track(title, artist, album, art, path.name)


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


def render_firmware(track, fonts, firmware, style, position, count, scroll, paused):
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
    text('label_playtime', '00:00')
    text('label_ipod_remain' if 'label_ipod_remain' in page else 'label_playlen', '00:00')

    slider = page['slider_play']
    track_image = packaged_style(firmware, slider, 'bg_image', '')
    if track_image in firmware.images:
        icon(track_image, slider.box)
    else:
        x, y, w, h = slider.box
        y += offset + h // 2
        draw.rounded_rectangle((x, y - 3, x + w - 1, y + 3), 3, fill='#777777')
    return frame, face


def render(track, fonts, style, position=1, count=1, scroll=0, paused=False, firmware=None):
    if firmware is not None:
        return render_firmware(track, fonts, firmware, style, position, count, scroll, paused)
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


def desktop(fonts, style, tracks, firmware=None, unsquashfs='unsquashfs'):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    from PIL import ImageTk

    window = tk.Tk()
    window.title('Q2 Pod Simulator')
    current, scroll, paused = 0, 0, False
    page = 'home' if firmware else 'playing'
    home_index, row_index, return_page = 0, 0, 'home'
    hits: list[tuple[int, int, int]] = []
    hint = ''
    photo: ImageTk.PhotoImage | None = None
    selected = tk.StringVar(value=style)
    screen = ttk.Label(window)
    screen.pack()
    controls = ttk.Frame(window, padding=8)
    controls.pack(fill='x')
    status = ttk.Label(window, padding=(8, 0, 8, 8), wraplength=355)
    status.pack()

    def open_firmware():
        nonlocal firmware, fonts, scroll, page, home_index, row_index, return_page, hint
        path = filedialog.askopenfilename(filetypes=[('Q2 firmware', '*.zip *.tar'), ('All files', '*')])
        if not path:
            return
        try:
            package = load_firmware(Path(path), unsquashfs)
            package_fonts = Fonts(firmware=package)
            render(tracks[current], package_fonts, selected.get(), firmware=package)
        except ERRORS as exc:
            messagebox.showerror('Could not open firmware', str(exc), parent=window)
            return
        firmware, fonts, scroll = package, package_fonts, 0
        page, home_index, row_index, return_page, hint = 'home', 0, 0, 'home', ''
        themes.configure(state='readonly' if firmware.custom else 'disabled')
        screen.focus_set()

    def move(step):
        nonlocal current, scroll, home_index, row_index, hint
        if page == 'home' and firmware:
            home_index = (home_index + step) % len(firmware.home)
        elif page in ('folder', 'localmusic'):
            row_index = (row_index + step) % len(tracks)
        else:
            current = (current + step) % len(tracks)
        scroll = 0
        hint = ''

    def toggle():
        nonlocal paused
        paused = not paused

    def enter():
        nonlocal page, current, row_index, return_page, scroll, hint
        screen.focus_set()
        if page == 'home' and firmware:
            entry = firmware.home[home_index]
            if entry.key in ('folder', 'localmusic', 'playing'):
                page, row_index, return_page = entry.key, current, 'home'
            else:
                hint = f'{entry.label} is outside this simulator preview'
        elif page in ('folder', 'localmusic'):
            return_page, page, current, scroll = page, 'playing', row_index, 0
        else:
            toggle()

    def back():
        nonlocal page, hint
        if firmware:
            page = return_page if page == 'playing' else 'home'
            hint = ''
        screen.focus_set()

    def tap(event):
        nonlocal home_index, row_index
        screen.focus_set()
        if page == 'playing':
            return
        if page == 'home' and firmware and not firmware.custom:
            if event.x < 60 or event.x > SIZE[0] - 60:
                move(-1 if event.x < 60 else 1)
                return
        for index, y, end in hits:
            if y <= event.y < end:
                if page == 'home':
                    home_index = index
                else:
                    row_index = index
                enter()
                return

    def open_tracks():
        nonlocal tracks, current, scroll, row_index
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
            tracks, current, scroll, row_index = loaded, 0, 0, 0
        if failures:
            messagebox.showwarning('Could not open tracks', '\n'.join(failures), parent=window)
        screen.focus_set()

    def refresh():
        nonlocal photo, scroll, hits
        source = firmware.name if firmware is not None else 'Checkout preview'
        if firmware and page != 'playing':
            index = home_index if page == 'home' else row_index
            frame, hits = render_browse(firmware, fonts, selected.get(), page, index, tracks)
            detail = hint or 'Wheel or arrows to move · Enter to select · Esc to go back'
        else:
            frame, face = render(tracks[current], fonts, selected.get(), current + 1,
                                 len(tracks), scroll, paused, firmware)
            fallback = '' if 'default' in fonts.data else ' · Stock font unavailable, preview uses bundled bold'
            artist_face = f' · Artist font: {fonts.artist(tracks[current].artist)[1]}' if firmware else ''
            detail = f'Title font: {face}{artist_face}{fallback}'
        photo = ImageTk.PhotoImage(frame)
        screen.configure(image=photo)
        status.configure(text=f'{source} · {detail}')
        scroll += 2
        window.after(100, refresh)

    ttk.Button(controls, text='Open tracks', command=open_tracks).pack(side='left')
    for text, callback in (('‹', lambda: move(-1)), ('›', lambda: move(1)),
                           ('Select', enter)):
        ttk.Button(controls, text=text, width=7 if text == 'Select' else 3,
                   command=callback).pack(side='left', padx=(4, 0))
    themes = ttk.Combobox(controls, textvariable=selected, values=THEMES, width=12,
                          state='readonly' if firmware is None or firmware.custom else 'disabled')
    themes.pack(side='right')
    themes.bind('<<ComboboxSelected>>', lambda _: screen.focus_set())
    device = ttk.Frame(window, padding=(8, 0, 8, 8))
    device.pack(fill='x')
    ttk.Button(device, text='Open firmware', command=open_firmware).pack(side='left')
    ttk.Button(device, text='Back', command=back).pack(side='right')
    for key in ('<Up>', '<Left>', '<Button-4>'):
        screen.bind(key, lambda _: move(-1))
    for key in ('<Down>', '<Right>', '<Button-5>'):
        screen.bind(key, lambda _: move(1))
    screen.bind('<MouseWheel>', lambda event: move(-1 if event.delta > 0 else 1))
    screen.bind('<space>', lambda _: enter())
    screen.bind('<Return>', lambda _: enter())
    screen.bind('<Escape>', lambda _: back())
    screen.bind('<BackSpace>', lambda _: back())
    screen.bind('<Button-1>', tap)
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
    parser.add_argument('--snapshot', type=Path, help='save one PNG and exit without opening a window')
    parser.add_argument('--screen', choices=('home', 'folder', 'localmusic', 'playing'), default='playing',
                        help='screen to capture with --snapshot (browse screens require --firmware)')
    args = parser.parse_args()
    if args.firmware and (args.stock_font or args.fonts_dir):
        parser.error('--firmware supplies the fonts itself; use --stock-font and --fonts-dir in checkout preview mode')
    if args.screen != 'playing' and not (args.snapshot and args.firmware):
        parser.error('--screen requires --snapshot and --firmware')
    try:
        firmware = load_firmware(args.firmware, args.unsquashfs) if args.firmware else None
        fonts = Fonts(args.stock_font, args.fonts_dir, firmware)
        tracks = [read_track(path) for path in args.tracks] or list(SAMPLES)
        if args.snapshot:
            if args.screen == 'playing':
                image, face = render(tracks[0], fonts, args.theme, count=len(tracks), firmware=firmware)
                detail = f'title font: {face}; artist font: {fonts.artist(tracks[0].artist)[1]}'
            else:
                image, _ = render_browse(firmware, fonts, args.theme, args.screen, 0, tracks)
                detail = args.screen
            image.save(args.snapshot)
            source = firmware.name if firmware else 'checkout preview'
            print(f'{args.snapshot} ({source}; {detail})')
        else:
            desktop(fonts, args.theme, tracks, firmware, args.unsquashfs)
    except ERRORS as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')


if __name__ == '__main__':
    main()
