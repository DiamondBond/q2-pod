"""Desktop drawing for Snake and Vortex, based on the sheets in patch/games.c."""

from PIL import Image, ImageDraw

SCREEN = (375, 320)


def draw_snake(state, classic):
    image = Image.new('RGB', SCREEN, '#171717')
    draw = ImageDraw.Draw(image)
    x, y, size = 77, 36, 11
    width = size * 20
    lcd, dot = '#c3cdb4', '#2a3324'
    if classic:
        draw.rounded_rectangle((x - 6, y - 6, x + width + 5, y + width + 5), 8, '#8f968a')
        draw.rounded_rectangle((x - 4, y - 4, x + width + 3, y + width + 3), 6, lcd)
        for cell in range(400):
            left, top = x + cell % 20 * size, y + cell // 20 * size
            draw.rectangle((left + 1, top + 1, left + 9, top + 9), fill='#b9c3ab')
    else:
        draw.rounded_rectangle((x - 4, y - 4, x + width + 3, y + width + 3), 8, '#111111', '#333333')
    for i in range(state.len):
        cell = state.body[(state.tail + i) % 400]
        left, top = x + cell % 20 * size, y + cell // 20 * size
        bounds = (left + 1, top + 1, left + 9, top + 9)
        if classic:
            draw.rectangle(bounds, fill=dot)
        else:
            draw.rounded_rectangle(bounds, 3, '#a6cdf5' if i == state.len - 1 else '#58a6ee')
    if state.state == 1:
        left, top = x + state.food % 20 * size, y + state.food // 20 * size
        if classic:
            draw.rectangle((left + 1, top + 1, left + 9, top + 9), fill=dot)
            draw.rectangle((left + 3, top + 3, left + 7, top + 7), fill=lcd)
        else:
            draw.ellipse((left + 1, top + 1, left + 9, top + 9), fill='#e04848')
    return image


def draw_vortex(state, classic):
    image = Image.new('RGB', SCREEN, '#0c1735' if classic else '#171717')
    draw = ImageDraw.Draw(image)
    cx, cy = 187.5, 160

    def arc(radius, start, end, width, fill):
        draw.arc((cx - radius, cy - radius, cx + radius, cy + radius),
                 start * 360 / 1024, end * 360 / 1024, fill=fill, width=width)

    if classic:
        for k in range(32):
            draw.point((k * 97 % 375, k * 61 % 320), fill=('#50617c', '#8092ad', '#afbcd4', '#dde6f4')[k % 4])
    arc(118, 0, 1024, 1, '#3a4a78' if classic else '#333333')
    colors = ('#f0a020', '#36b24a', '#2f86f0') if classic else ('#78b7ef', '#5590c3', '#366b96')
    shine = ('#f8ca78', '#8cd59b', '#8eb9f8')
    for ring, mask in enumerate(state.brick):
        for segment in range(16):
            if mask & (1 << segment):
                start = segment * 64
                arc(51 + ring * 12, start + 2, start + 62, 10, colors[ring])
                if classic:
                    arc(53 + ring * 12, start + 5, start + 59, 3, shine[ring])
    arc(120, state.pa - 64, state.pa + 64, 6, '#ffffff')
    x, y = cx + state.x / 65536, cy + state.y / 65536
    if classic:
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill='#42658a')
    draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill='#ffffff')
    for i in range(state.lives):
        life_x = 296 + (i - (state.lives - 1) / 2) * 14
        draw.ellipse((life_x - 4, 298, life_x + 4, 306), fill='#c8d4e4')
    return image
