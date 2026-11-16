# mypy: disable-error-code="import-not-found,import-untyped"
"""Draw the Q2 desktop enclosure and interpret its circular touch wheel."""

import math
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageColor, ImageDraw

DEVICE_SIZE = (435, 664)
SCREEN_AT = (30, 27)
SCREEN_SIZE = (375, 320)
WHEEL = (217.5, 501)
RADIUS = 117
CENTRE = 46
DETENT = math.pi / 9
DEFAULT_SHELL = 'Orange'


@dataclass(frozen=True)
class ShellFinish:
    top: str
    bottom: str
    trim: str
    wheel_shadow: str
    center: str
    center_edge: str
    center_glint: str
    wheel: str = '#ded0be'
    wheel_edge: str = '#fff0dc'
    wheel_ink: str = '#675951'


SHELL_FINISHES = {
    'Silver': ShellFinish('#d6d9dc', '#8b9299', '#eef1f4', '#727a83', '#a9b0b8',
                          '#67717a', '#dbe0e6', '#e1e3e6', '#f8fafc', '#525b63'),
    'Black': ShellFinish('#44474c', '#1e2024', '#676b71', '#121318', '#26292f',
                          '#14161a', '#5d626c', '#363940', '#5c6067', '#d0d2d6'),
    'Orange': ShellFinish('#bb6034', '#7c3515', '#ce8b67', '#6c3928', '#8f442d',
                           '#5d3027', '#cf8057'),
    'Champagne Gold': ShellFinish('#d8bb87', '#a98855', '#f3dcad', '#8e7049', '#b79a66',
                                 '#816342', '#edd3a1', '#e7d8be', '#fff4db', '#69553b'),
}


def wheel_button(x, y):
    dx, dy = x - WHEEL[0], y - WHEEL[1]
    distance = math.hypot(dx, dy)
    if distance > RADIUS:
        return None
    if distance < CENTRE:
        return 'center'
    if abs(dx) > abs(dy):
        return 'right' if dx > 0 else 'left'
    return 'down' if dy > 0 else 'up'


def wheel_angle(x, y):
    return math.atan2(y - WHEEL[1], x - WHEEL[0])


def wheel_delta(previous, angle):
    return (angle - previous + math.pi) % math.tau - math.pi


def wheel_glyphs(draw, ink):
    x, y = WHEEL
    draw.arc((x - 12, y - 95, x + 11, y - 76), -90, 125, fill=ink, width=3)
    draw.line((x - 1, y - 98, x - 8, y - 95, x - 1, y - 90), fill=ink, width=3)
    for sign in (-1, 1):
        mid = x + 85 * sign
        for shift in (-4, 4):
            draw.line((mid + shift - 3 * sign, y - 6, mid + shift + 2 * sign, y,
                       mid + shift - 3 * sign, y + 6), fill=ink, width=3)
    draw.polygon(((x - 11, y + 78), (x - 11, y + 92), (x, y + 85)), fill=ink)
    for bar in (x + 4, x + 10):
        draw.line((bar, y + 78, bar, y + 92), fill=ink, width=3)


@lru_cache(maxsize=len(SHELL_FINISHES))
def enclosure(shell=DEFAULT_SHELL):
    finish = SHELL_FINISHES[shell]
    frame = Image.new('RGB', DEVICE_SIZE, '#242122')
    draw = ImageDraw.Draw(frame)
    draw.rounded_rectangle((5, 1, 429, 659), 72, '#201a1a', outline='#120e0f', width=2)
    body = Image.new('RGB', DEVICE_SIZE)
    shade = ImageDraw.Draw(body)
    top, bottom = ImageColor.getrgb(finish.top), ImageColor.getrgb(finish.bottom)
    for y in range(DEVICE_SIZE[1]):
        fraction = y / DEVICE_SIZE[1]
        shade.line((0, y, DEVICE_SIZE[0], y),
                   fill=tuple(int(a + (b - a) * fraction) for a, b in zip(top, bottom)))
    mask = Image.new('L', DEVICE_SIZE)
    ImageDraw.Draw(mask).rounded_rectangle((10, 6, 424, 654), 68, fill=255)
    frame.paste(body, mask=mask)
    draw.rounded_rectangle((11, 7, 423, 653), 67, outline=finish.trim, width=2)
    draw.rounded_rectangle((17, 15, 417, 359), 64, '#151417', outline='#392222', width=2)
    draw.rounded_rectangle((22, 20, 412, 354), 60, '#0a090b', outline='#2e292b', width=2)
    x, y = WHEEL
    draw.ellipse((x - RADIUS - 3, y - RADIUS - 2, x + RADIUS + 3, y + RADIUS + 4), finish.wheel_shadow)
    draw.ellipse((x - RADIUS, y - RADIUS, x + RADIUS, y + RADIUS),
                 finish.wheel, outline=finish.wheel_edge, width=2)
    draw.ellipse((x - CENTRE, y - CENTRE, x + CENTRE, y + CENTRE),
                 finish.center, outline=finish.center_edge, width=3)
    draw.arc((x - CENTRE + 3, y - CENTRE + 3, x + CENTRE - 3, y + CENTRE - 3),
             190, 318, finish.center_glint, width=2)
    wheel_glyphs(draw, finish.wheel_ink)
    display_mask = Image.new('L', SCREEN_SIZE)
    ImageDraw.Draw(display_mask).rounded_rectangle((0, 0, 374, 319), 41, fill=255)
    return frame, display_mask


def device_frame(screen, shell=DEFAULT_SHELL):
    frame, mask = enclosure(shell)
    result = frame.copy()
    result.paste(screen, SCREEN_AT, mask)
    return result
