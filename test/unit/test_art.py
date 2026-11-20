"""tools/art.py: the theme images it draws, from the shipped theme's values."""
import functools
import math
import os
import pathlib
import re
import struct
import sys
import zlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[2]/'tools'))
import art
import ipod
import theme


@functools.cache
def classic():
    """Classic's images without the pane's icons, which take most of the drawing time. Every art.py
    mutant runs these tests, so only the two that read the icons draw them, and the rest share one
    drawing a session (conftest's uncached clears it for each mutant). Read it, don't change it."""
    return art.images({**theme.builtins()[1], 'pane_icon_x': 0})


@pytest.fixture(autouse=True)
def afresh():
    """mutmut's stats pass gives a test the art.py functions it calls. With the drawing cached by the first test, the
    rest call none, and no art.py mutant would run them; so there each test draws afresh. Anywhere else, one drawing."""
    if os.environ.get('MUTANT_UNDER_TEST') == 'stats':
        for f in [classic, *(f for f in vars(art).values() if hasattr(f, 'cache_clear'))]:
            f.cache_clear()


def pixels(data):
    w, h = struct.unpack('>II', data[16:24])
    idat = data.index(b'IDAT')
    raw = zlib.decompress(data[idat + 4:idat + 4 + struct.unpack('>I', data[idat - 4:idat])[0]])
    return w, h, lambda x, y: tuple(raw[y * (4 * w + 1) + 1 + 4 * x + i] for i in range(4))


# Stock's quick settings images, every drop_ name its demo sets (strings demo | grep '^drop_').
QS_LIT = {'wifiopen', 'btopen', 'keylockopen', 'highgain', 'lo', 'usbaudio', 'usbdac'}
QS_INKS = ('', '_l')  # white; dark, at rest in the light half and on a bright accent
QS_NAMES = ('wifi', 'wifiopen', 'bt', 'btopen', 'keylock', 'keylockopen', 'lowgain', 'lowgaindisable', 'highgain', 'highgaindisable', 'lo', 'po', 'sa', 'usbstorage', 'usbaudio', 'usbdac', 'playset', 'sysset')


def test_classic_draws_its_images_and_the_others_none():
    themes = theme.builtins()
    assert not art.images(themes[0]) and not art.images(themes[2])
    # the bar's speakers come with a track stated in one half alone
    for half in ({'np_track': themes[1]['np_track']}, {'light': {'np_track': themes[1]['light']['np_track']}}):
        assert set(art.images({**themes[0], **half})) == {'minimal_vol_lo', 'minimal_vol_hi'}
    full = art.images(themes[1])
    assert {k: v for k, v in full.items() if '_icon_' not in k} == classic()  # what the other tests draw
    assert set(full) == {f'classic_light_{n}' for n in ('sort_bars', *(f'icon_{n}{k}' for n in ('note', 'folder', 'stack', 'game', 'wave', 'gear') for k in ('', '_l')), 'chevron', 'bolt', 'plug', 'note', 'note_l', 'play_l', 'play_d', 'pause_l', 'pause_d', 'vol_lo', 'vol_hi', *(f'spk_{v}_{h}' for v in ('quiet', 'loud') for h in 'ldw'), *(f'drop_{n}{k}' for n in QS_NAMES for k in QS_INKS), 'drop_dim', 'drop_dim_l', 'drop_bright', 'drop_bright_l', 'drop_bright_ql', 'drop_bright_qd', *(f'msg_{n}_{h}' for n in ('usb', 'note') for h in 'ld'), 'clock_face_l', 'clock_face_d', 'hint_shadow', 'clock_dark', 'kb_del', 'kb_shift', 'kb_back', 'field_glass', 'field', 'rate_shadow', 'heart_on_l', 'heart_on_d', 'heart_off_l', 'heart_off_d', 'station')}


# The approved rendered rows, within 1 per channel: the fill down column 272 of the pause bars
# (the gradient's stops sampled at pixel centres), the edge down column 270.
REF_FILL = {4: 0x114c8f, 5: 0x1462a3, 6: 0x1870ae, 7: 0x1f83bf, 8: 0x299cd6, 9: 0x31b0e7, 10: 0x36bff2, 11: 0x38c7f6, 12: 0x35bbef,
              13: 0x2ca6e0, 14: 0x238fcd, 15: 0x1e7cba, 16: 0x196dab, 17: 0x1563a2, 18: 0x135999}
REF_EDGE = {5: 0x114d90, 6: 0x114e91, 7: 0x114f91, 8: 0x125092, 9: 0x125193, 10: 0x125293, 11: 0x125294, 12: 0x125395, 13: 0x125495,
              14: 0x125596, 15: 0x135697, 16: 0x135797, 17: 0x135898}


def test_the_play_state_stands_on_its_approved_rows():
    got = classic()
    w, h, at = pixels(got['classic_light_pause_l'])
    x0, y0 = art.STATE_BOX[:2]
    assert (w, h) == (ipod.STATE_W, 22)  # the bar's box and the art's are one number
    near = lambda p, rgb: p[3] == 255 and all(abs(p[i] - (rgb >> s & 255)) <= 1 for i, s in enumerate((16, 8, 0)))
    for y, rgb in REF_FILL.items():
        assert near(at(272 - x0, y - y0), rgb), y
    for y, rgb in REF_EDGE.items():
        assert near(at(270 - x0, y - y0), rgb), y
    # its extents: the bars' rows and columns, nothing past them; no halo, as an iPod's
    ink = {(x, y) for x in range(w) for y in range(h) if at(x, y)[3]}
    assert {y for _, y in ink} == set(range(4, 19)) and {x for x, _ in ink} == {*range(270 - x0, 276 - x0), *range(277 - x0, 283 - x0)}
    assert at(276 - x0, 11 - y0)[3] == 0  # between the bars: clear
    assert got['classic_light_play_l'] == got['classic_light_play_d']


def test_the_bolt_and_the_plug_fill_the_batterys_inside():
    t = theme.builtins()[1]
    got = classic()
    x0, y0 = art.BOLT_BOX[:2]
    g = theme.sets(t)['classic-light']
    for name in ('classic_light_bolt', 'classic_light_plug'):
        assert pixels(got[name])[:2] == tuple(art.BOLT_BOX[2:]) == (g.batt_w - 2, g.batt_h - 2) == (24, 11)  # the inside, BOLT_BOX's frame: x 290 to 313, rows 5 to 15
    at = pixels(got['classic_light_bolt'])[2]
    assert at(301 - x0, 10 - y0) == (0x3c, 0x4a, 0x34, 255)  # its colour, opaque
    assert t['bolt'] == 0x3c4a34 and t['bolt_halo_a'] == 102
    halo = at(304 - x0, 10 - y0)  # past the bolt's edge: white, no stronger than its alpha
    assert halo[:3] == (255, 255, 255) and 0 < halo[3] <= 102
    assert at(290 - x0, 10 - y0)[3] == 0 and at(313 - x0, 10 - y0)[3] == 0
    plug = pixels(got['classic_light_plug'])[2]
    assert plug(300 - x0, 10 - y0) == (0x3c, 0x4a, 0x34, 255) and plug(290 - x0, 11 - y0)[3] == 0


def test_the_volume_s_and_slider_pages_speakers():
    got = classic()
    size = {'spk_quiet': (12, 14), 'spk_loud': (22, 14)}
    for name, wh in size.items():
        for n in ([f'{name}_{h}' for h in 'ldw'] if name.startswith('spk') else [name]):
            w, h, at = pixels(got[f'classic_light_{n}'])
            assert (w, h) == wh
            assert not all(at(x, y)[3] == 255 for x in (0, w - 1) for y in (0, h - 1))
    inks = {'l': (0x39, 0x3c, 0x39), 'd': (0xc6, 0xc3, 0xc6), 'w': (255, 255, 255)}
    for half, rgb in inks.items():
        for n in ('quiet', 'loud'):
            w, h, at = pixels(got[f'classic_light_spk_{n}_{half}'])
            assert at(5, 7) == (*rgb, 255) and {at(x, y)[:3] for x in range(w) for y in range(h) if at(x, y)[3]} == {rgb}  # the cone; no other colour
            assert any(at(x, y)[3] for x in range(11, w) for y in range(h)) == (n == 'loud')  # only loud has arcs


def test_the_message_marks_are_the_glyphs_enlarged_in_the_halfs_ink():
    got = classic()
    for half, rgb in (('l', (0x1c, 0x1c, 0x1e)), ('d', (255, 255, 255))):
        for name in ('usb', 'note'):
            w, h, at = pixels(got[f'classic_light_msg_{name}_{half}'])
            assert (w, h) == (84, 84) and [at(x, y)[3] for x in (0, 83) for y in (0, 83)] == [0, 0, 0, 0]
            assert {at(x, y)[:3] for x in range(84) for y in range(84) if at(x, y)[3]} == {rgb}  # one ink, flat
    usb, note = pixels(got['classic_light_msg_usb_d'])[2], pixels(got['classic_light_msg_note_d'])[2]
    assert usb(42, 42)[3] == 255 and usb(42, 71)[3] == 255 and usb(38, 42)[3] < 64  # the trident's stem, 6.4 px wide, and its foot
    assert note(42, 42)[3] == 0 and note(20, 70)[3] == 255 and note(62, 62)[3] == 255 and note(42, 12)[3] == 255  # between the stems; each head; the beam
    # the button's own drawing, MSG_SCALE times about the centre: each of its solid pixels is solid here
    w, h, small = pixels(got['classic_light_drop_usbaudio'])
    solid = [(x, y) for x in range(w) for y in range(h) if small(x, y)[3] == 255]
    assert len(solid) > 100 and all(usb(int(42 + (x + .5 - 27) * art.MSG_SCALE), int(42 + (y + .5 - 27) * art.MSG_SCALE))[3] == 255 for x, y in solid)


def test_the_soft_shadows_are_their_boxes_blurred():
    got = classic()
    tail = lambda d, sigma: .5 * math.erfc(d / (sigma * 2**.5))  # a straight edge's blur, d past it
    for name, (bw, bh, blur, alpha) in {'rate_shadow': (304, 110, 6, 0x33)}.items():
        w, h, at = pixels(got[f'classic_light_{name}'])
        pad = blur + 2
        assert (w, h) == (bw + 2 * pad, bh + 2 * pad)
        assert {at(x, y)[:3] for x in range(w) for y in range(h) if at(x, y)[3]} == {(0, 0, 0)}  # black in either half
        assert max(at(x, y)[3] for x in range(w) for y in (0, h - 1)) <= 1 and max(at(x, y)[3] for x in (0, w - 1) for y in range(h)) <= 1  # nothing cut at the image's edge
        for y in range(pad + bh - 2, h):  # under the box's foot (its y offset is 2), down the middle
            assert abs(at(w // 2, y)[3] - alpha * tail(y + .5 - pad - bh, blur / 2)) <= 1, (name, y)
        assert at(w // 2, pad + bh // 2)[3] == 0 and at(w // 2, pad + bh - 3)[3] == 0  # none under the box, as CSS clips it
        assert at(w // 2, pad - 4)[3] < at(w // 2, h - pad + 1)[3] and at(pad - 1, h // 2)[3] == at(w - pad, h // 2)[3]  # the foot darker than the head; the sides alike


def test_blurred_spreads_a_point_by_its_kernel_and_carries_the_edges_on():
    k = [math.exp(-i * i / 8) for i in range(-6, 7)]  # sigma 2: thirteen taps
    k = [v / sum(k) for v in k]
    point = [0.0] * 35
    point[2 * 7 + 4] = 1.0  # row 2, column 4 of 7 x 5
    assert art.blurred(point, 7, 5, 2) == [k[y + 4] * k[x + 2] for y in range(5) for x in range(7)]
    ends = art.blurred([1.0] + [0.0] * 11 + [1.0], 13, 1, 2)  # each end's value carried on past it, six taps a side
    assert abs(ends[0] - sum(k[:7])) < 1e-12 and abs(ends[12] - sum(k[6:])) < 1e-12 and abs(ends[6] - 2 * k[0]) < 1e-12


def test_quick_settings_glyphs_are_flat_marks_on_clear():
    # quick_settings.c paints each 54 px button; its art is the glyph alone in the button's ink: white, or #1c1c1e
    got = classic()
    inks = {'': (255, 255, 255), '_l': (0x1c, 0x1c, 0x1e)}
    for n in QS_NAMES:
        for k in QS_INKS:
            w, h, at = pixels(got[f'classic_light_drop_{n}{k}'])
            assert (w, h) == (54, 54)
            drawn = [(x, y) for x in range(54) for y in range(54) if at(x, y)[3]]
            assert {at(x, y)[:3] for x, y in drawn} == {inks[k]}, n  # one ink, flat
            assert max(math.hypot(x - 26.5, y - 26.5) for x, y in drawn) < 17, n  # well inside the button's 27


def test_quick_settings_glyphs_dim_only_when_disabled():
    got = classic()
    mark = lambda n: got[f'classic_light_drop_{n}']
    at = lambda n: pixels(mark(n))[2]
    alpha = lambda n: max(at(n)(x, y)[3] for x in range(54) for y in range(54))
    assert {n for n in QS_NAMES if alpha(n) < 255} == {'lowgaindisable', 'highgaindisable'}
    assert alpha('highgaindisable') == round(255 * art.QS_DIM)
    # gain's three bars, 3.6 wide: all solid when high; low keeps the first and leaves the others faint
    assert [at('highgain')(x, 33)[3] for x in (19, 26, 34)] == [255, 255, 255]
    assert [at('lowgain')(x, 33)[3] for x in (19, 26, 34)] == [255, round(255 * art.QS_FAINT), round(255 * art.QS_FAINT)]
    assert at('highgain')(23, 33)[3] == 0 and at('highgain')(26, 20)[3] == 0  # clear between them, and above the middle one
    # the output is one mark, its label saying which; stock's three USB modes are three: storage off, as stock's grey disc
    assert mark('lo') == mark('po') == mark('sa') and mark('lowgain') != mark('highgaindisable')
    assert len({mark(n) for n in ('usbstorage', 'usbaudio', 'usbdac')}) == 3 and 'usbstorage' not in QS_LIT
    # a shape keeps its holes: the port's slot and the gear's middle are clear, the shape round them solid
    assert (at('usbdac')(27, 27)[3], at('usbdac')(27, 23)[3], at('sysset')(27, 27)[3], at('sysset')(27, 20)[3]) == (0, 255, 0, 255)
    # a line's ends are round: Wi-Fi's outer arc ends in half a disc, not a square cut
    w, h, wifi = pixels(mark('wifi'))
    left = min(x for x in range(54) for y in range(54) if wifi(x, y)[3] >= 128)
    assert sum(wifi(left, y)[3] >= 128 for y in range(54)) < sum(wifi(left + 1, y)[3] >= 128 for y in range(54))


def test_quick_settings_lit_names_are_the_on_buttons():
    assert art.qs_lit() == ''.join(f'drop_{n}\\0' for n in art.QS_BUTTONS if n in QS_LIT) and set(art.QS_BUTTONS) == set(QS_NAMES)


def test_the_brightness_bars_suns():
    # quick_scrub's: the small one on the fill, the large one past it, quiet on the bar at rest in each half
    got = classic()
    inks = {'': (255, 255, 255), '_l': (0x1c, 0x1c, 0x1e), '_ql': (0x6e, 0x6e, 0x73), '_qd': (0x98, 0x98, 0x9d)}
    for name, px, keys, side in (('dim', 24, ('', '_l'), 14), ('bright', 30, tuple(inks), 20)):
        for k in keys:
            w, h, at = pixels(got[f'classic_light_drop_{name}{k}'])
            assert (w, h) == (px, px) and at(px // 2, px // 2)[3] == 255
            assert {at(x, y)[:3] for x in range(w) for y in range(h) if at(x, y)[3]} == {inks[k]}
            inked = [(x, y) for x in range(w) for y in range(h) if at(x, y)[3] >= 64]  # the ink's bounding box, a quarter's alpha or more
            assert max(p[0] for p in inked) - min(p[0] for p in inked) + 1 == side and max(p[1] for p in inked) - min(p[1] for p in inked) + 1 == side, name
    row = [pixels(got['classic_light_drop_bright'])[2](x, 15)[3] for x in range(30)]
    assert row[9] < 16 and row[10] == 0 and row[12] == 255 and row[6] == 255  # a ray stands clear of the disc
    assert set(got) >= {f'classic_light_drop_bright{k}' for k in inks} and 'classic_light_drop_dim_ql' not in got


def test_the_dark_clock_face():
    w, h, at = pixels(classic()['classic_light_clock_dark'])
    assert (w, h) == (96, 96) and at(0, 0)[3] == 0 and at(95, 95)[3] == 0 and at(48, 48) == (0x0c, 0x0f, 0x15, 255)
    k = .96
    ink = lambda x, y: at(int((x + 50) * k), int((y + 50) * k))
    assert max(ink(x, y)[0] for x in range(-4, 5) for y in range(-38, -30)) > 200  # the 12
    assert max(ink(x, y)[0] for x in range(30, 42) for y in range(-3, 5)) > 200  # the 3
    assert at(48, 1)[3] > 0 and at(48, 1)[0] > 0x0c  # the rim's stroke over the disc


def test_the_keyboard_glyphs_and_the_field():
    got = classic()
    for name, size in (('kb_del', (22, 18)), ('kb_shift', (22, 18)), ('kb_back', (13, 24)), ('field_glass', (16, 16)), ('field', (32, 31))):
        assert pixels(got[f'classic_light_{name}'])[:2] == size
    at = pixels(got['classic_light_kb_del'])[2]
    assert at(16, 2)[:3] == (255, 255, 255) and at(0, 0)[3] == 0 and at(14, 9)[2] < 200  # the body; the cross's slate
    assert pixels(got['classic_light_kb_shift'])[2](11, 9)[:3] == (255, 255, 255)
    at = pixels(got['classic_light_kb_back'])[2]
    assert at(1, 12)[3] > 128 and at(12, 12)[3] == 0
    at = pixels(got['classic_light_field_glass'])[2]
    assert at(6, 2)[:3] == (0x8a, 0x8f, 0x96) and at(6, 6)[3] == 0 and at(13, 13)[3] > 128
    at = pixels(got['classic_light_field'])[2]
    assert at(16, 20) == (255, 255, 255, 255) and at(16, 1)[0] < at(16, 8)[0] and at(0, 0)[3] == 0  # white, its top soft, its corner out
    assert at(16, 30)[:3] == (255, 255, 255) and 0x50 <= at(16, 30)[3] <= 0x60  # the row below


def test_set_time_s_face_and_the_hint_s_shadow():
    got = classic()
    rgba = lambda v: (v >> 16, v >> 8 & 255, v & 255, 255)
    for half, (rest, quiet) in art.CLOCK_FACE.items():
        w, h, face = pixels(got[f'classic_light_clock_face_{half}'])
        assert (w, h) == (110, 110) and face(55, 55) == rgba(rest) and face(0, 0)[3] == 0  # a flat disc; nothing outside it
        assert {face(x, 55) for x in range(20, 91)} == {rgba(rest)} and {face(55, y) for y in range(20, 91)} == {rgba(rest)}  # the hands' ground is clear
        inked = {(x, y) for x in range(110) for y in range(110) if face(x, y)[3] == 255 and face(x, y) != rgba(rest)}
        assert any(50 <= x < 60 and 6 <= y < 20 for x, y in inked) and any(6 <= x < 18 and 50 <= y < 60 for x, y in inked)  # the 12 and the 9, from the font's outlines
        assert all(30 * 1.1 < math.hypot(x - 54.5, y - 54.5) < 48 * 1.1 for x, y in inked)  # in a ring the hands end short of
        mix = lambda p: all(min(a, b) - 1 <= c <= max(a, b) + 1 for a, b, c in zip(rgba(rest), rgba(quiet), p))
        assert all(mix(face(x, y)) for x, y in inked)  # the quiet ink over the disc, nothing else
    w, h, hint = pixels(got['classic_light_hint_shadow'])  # stock's marks, a row down, blurred: 0 1px 2px #00000080
    assert (w, h) == (29, 15) and hint(0, 0)[3] == 0 and hint(28, 14)[3] == 0 and hint(8, 8)[:3] == (0, 0, 0)
    assert 0x20 < hint(8, 8)[3] <= 0x80 and hint(8, 1)[3] == 0


def test_the_note_is_its_drawing_s_shape_flat_in_each_half_s_ink():
    got = classic()
    for k, rgb in (('', (255, 255, 255)), ('_l', (0x1c, 0x1c, 0x1e))):
        w, h, at = pixels(got[f'classic_light_note{k}'])
        assert (w, h) == (100, 115)
        assert at(0, 0) == (0, 0, 0, 0)  # outside the drawing
        assert at(36, 30) == (*rgb, 255) and at(90, 60) == (*rgb, 255)  # the left stem's top and the right stem: one opaque colour
        assert {at(x, y)[:3] for x in range(w) for y in range(h) if at(x, y)[3]} == {rgb}


def test_the_chevron_is_a_white_rounded_stroke_on_its_box():
    w, h, at = pixels(classic()['classic_light_chevron'])
    assert (w, h) == (12, 16)
    assert at(8, 8) == (255, 255, 255, 255)  # the point's centreline
    assert at(0, 15)[3] == 0 and at(11, 0)[3] == 0  # outside the stroke
    assert 0 < at(1, 1)[3] < 255  # a rounded end's edge


def test_sort_is_three_white_bars():
    w, h, at = pixels(classic()['classic_light_sort_bars'])
    assert (w, h) == (16, 12)
    for y in range(h):
        ink = [x for x in range(w) if at(x, y) == (255, 255, 255, 255)]
        assert ink == list(range({0: 16, 1: 16, 5: 11, 6: 11, 10: 6, 11: 6}.get(y, 0))), y
        assert all(at(x, y)[3] == 0 for x in range(w) if x not in ink), y


def test_the_volume_ends_are_white_speakers_the_loud_one_with_waves():
    got = classic()
    (lw, lh, lo), (hw, hh, hi) = (pixels(got[f'classic_light_vol_{n}']) for n in ('lo', 'hi'))
    assert (lw, lh, hw, hh) == (8, 13, 18, 13)
    assert all(lo(x, y)[:3] == (255, 255, 255) for x in range(lw) for y in range(lh) if lo(x, y)[3])
    assert all(hi(x, y) == lo(x, y) for x in range(7) for y in range(lh))  # the same speaker
    waves = [x for x in range(9, hw) if any(hi(x, y)[3] for y in range(hh))]
    assert waves and max(waves) == hw - 1


def test_the_pane_icons_fit_their_box_and_keep_their_holes():
    got = art.images(theme.builtins()[1])
    for name, side in (('folder', 96), ('stack', 96), ('game', 96), ('wave', 96), ('gear', 96), ('note', 100)):
        w, h, at = pixels(got[f'classic_light_icon_{name}'])
        assert w == side
        ink = [(x, y) for x in range(w) for y in range(h) if at(x, y)[3]]
        assert {at(x, y)[:3] for x, y in ink} == {(255, 255, 255)} and any(at(x, y)[3] == 255 for x, y in ink)  # flat white, opaque inside
        _, _, light = pixels(got[f'classic_light_icon_{name}_l'])  # the light pane's: the same shape in the ink
        assert all(light(x, y)[3] == at(x, y)[3] for x in range(w) for y in range(h)), name
        assert {light(x, y)[:3] for x, y in ink if at(x, y)[3] == 255} == {(0x1c, 0x1c, 0x1e)}, name
        xs, ys = [p[0] for p in ink], [p[1] for p in ink]
        if name != 'note':  # 92 px on its longer side, centred on (278, 124)
            assert max(max(xs) - min(xs), max(ys) - min(ys)) in range(91, 96), name
            assert abs((min(xs) + max(xs)) / 2 + 230 - 278) <= 1 and abs((min(ys) + max(ys)) / 2 + 76 - 124) <= 1, name
    x, y = 278 - 230, 124 - 76
    assert pixels(got['classic_light_icon_gear'])[2](x, y)[3] == 0  # the gear's hole, even-odd
    assert pixels(got['classic_light_icon_folder'])[2](x, y)[3] > 0
    assert pixels(got['classic_light_icon_folder'])[2](x, y)[:3] == (255, 255, 255)


def test_path_reads_arcs_and_further_subpaths():
    polys = art.path('M0 0H10V10H0ZM20 0H30V10H20Z')
    assert len(polys) == 2 and polys[1][0] == (20, 0)
    arc = art.path('M0 0A5 5 0 1 1 10 0Z')[0]
    assert min(y for _, y in arc) >= -5.01 and max(abs(x - 5) for x, _ in arc) <= 5.01 and len(arc) > 40
    assert art.coverage([[(0, 0), (2, 0), (2, 2), (0, 2)]], (0, 0, 3, 1)) == [1.0, 1.0, 0.0]
    # a span inside another adds nothing: the union, not a sum
    assert art.coverage([[(0, 0), (3, 0), (3, 1), (0, 1)], [(1, 0), (1.5, 0), (1.5, 1), (1, 1)]], (0, 0, 3, 1)) == [1.0, 1.0, 1.0]


def test_coverage_counts_the_sub_rows_each_polygon_crosses():
    rect = lambda x0, y0, x1, y1: [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    ring = [*rect(1, 2, 7, 3), (1, 2), *rect(3, 2.25, 5, 2.75), (3, 2.25)]  # one polygon: its hole joined by a seam walked twice
    polys = [rect(.5, .0625, 5.25, .5625), rect(-1, 1, 4, 2), rect(2.25, 1, 2.75, 2), rect(4.25, 1, 4.75, 2), ring, rect(0, 5, 8, 6)]
    assert art.coverage(polys, (0, 0, 8, 3)) == [
        .25, .5, .5, .5, .5, .125, 0, 0,  # half the sub-rows, from the one at the shape's top (y 1/16); the ends in part
        1, 1, 1, 1, .5, 0, 0, 0,  # cut at the box; a span inside the union adds nothing, one within a pixel after it does
        0, 1, 1, .5, .5, 1, 1, 0]  # even-odd: the hole clear in its half of the sub-rows; the shape off the box, nothing


@pytest.mark.parametrize('rx, ry, sweep', [(1, 1, 1), (1, 2, 1), (2, 1, 0)])
def test_path_arc_too_small_for_its_chord_grows_to_fit(rx, ry, sweep):
    # SVG's rule (F.6.6): radii that can't span the ends scale up, in proportion, until they just do: half an
    # ellipse about the chord's middle, on the side sweep says (1: the positive angles, up in SVG's y-down space)
    arc, = art.path(f'M0 0A{rx} {ry} 0 0 {sweep} 10 0')
    rx, ry = 5, 5 * ry / rx  # the chord is 10 along x
    assert math.dist(arc[-1], (10, 0)) < 1e-9
    assert all(abs(((x - 5) / rx)**2 + (y / ry)**2 - 1) < 1e-9 for x, y in arc)
    assert all(y * (1 if sweep else -1) < 1e-9 for _, y in arc) and abs(max(abs(y) for _, y in arc) - ry) < 1e-9


def test_gradient_holds_the_last_stops_colour_past_it():
    g = art.gradient(((0, 0x000000), (50, 0x2080ff)), 10, 20)  # as an SVG linearGradient's: its end pads
    assert g(10) == 0 and g(15) == g(17.5) == g(20) == g(30) == 0x2080ff


def test_gradient_holds_the_first_stops_colour_before_it():
    g = art.gradient(((50, 0x204060), (100, 0xffffff)), 0, 100)
    assert g(10) == g(50) == 0x204060


def test_holed_joins_a_shapes_subpaths_so_the_later_ones_are_holes():
    ring = art.holed('M0 0H8V8H0ZM2 2H6V6H2Z')
    cov = art.coverage([ring], (0, 0, 8, 8))
    assert cov[0] == 1 and cov[3 * 8 + 3] == 0 and cov[7 * 8 + 7] == 1 and sum(cov) == 64 - 16
    assert art.coverage([art.holed('M0 0H8V8H0Z')], (0, 0, 8, 8)) == [1] * 64  # one subpath: itself


def test_a_pane_glyph_is_homes_own_drawing_at_another_size():
    for name, size in (('gear', 27), ('note', 28)):
        polys, home = art.path(art.pane_glyph(name, size)), art.path(art.PANE_ICONS[name])
        xs, ys = [x for poly in polys for x, _ in poly], [y for poly in polys for _, y in poly]
        assert abs(max(max(xs) - min(xs), max(ys) - min(ys)) - size) < .02  # its larger side
        assert abs(min(xs) + max(xs)) < .02 and abs(min(ys) + max(ys)) < .02  # about 0, 0
        assert [len(poly) for poly in polys] == [len(poly) for poly in home]  # every subpath, its hole too
    # the System button's gear is Home's Settings gear, and the message screen's note Home's note
    assert art.QS_GLYPHS['gear']['fill'] == (art.pane_glyph('gear', 27),) and art.QS_GLYPHS['note']['fill'] == (art.pane_glyph('note', 28),)


def test_outlines_a_space_is_an_advance_with_no_polygon():
    font = art.classic_light_font()
    glyphs, cmap, k = font.getGlyphSet(), font.getBestCmap(), 20 / font['head'].unitsPerEm
    one, space = (glyphs[cmap[ord(c)]].width * k for c in '1 ')
    single, = art.outlines('1', 20, 0, 50)
    first, second = art.outlines('1 1', 20, 0, 50)
    # the line centred on x 0: each 1 half its own advance and the space's from the middle
    for poly, dx in ((first, -(one + space) / 2), (second, (one + space) / 2)):
        assert len(poly) == len(single) and all(math.dist(p, (x + dx, y)) < 1e-9 for p, (x, y) in zip(poly, single))


def test_every_literal_corner_radius_is_in_the_table():
    source = ''.join(p.read_text() for p in sorted((pathlib.Path(__file__).parents[2] / 'patch').glob('*.c')))
    def literal(names):
        return {int(r) for r in re.findall(rf'(?:{names})\([^;]*?,\s*(\d+)(?:,[^;]*?)?\);', source)}
    radii = literal('paint_round_rows|round_row|row_below|inset_top|round_ring')
    assert radii and radii <= set(art.CORNERS)
    assert {r - 1 for r in literal('round_ring')} <= set(art.CORNERS)  # a ring reads its radius less one too


def test_the_round_corners_cover_their_arcs():
    for r in art.CORNERS:
        cover = art.corner_cover(r)
        assert len(cover) == r * r and cover == bytes(cover[x * r + y] for y in range(r) for x in range(r))  # about its diagonal
        assert cover[0] == {2: 81, 3: 6}.get(r, 0) and cover[-1] == 255  # the small corners' outer pixels keep some cover
        for y, x, drawn in ((y, x, v) for y in range(r) for x, v in enumerate(art.rounded(r, r, 0, 0, 2 * r, 2 * r, r)[y * r:(y + 1) * r])):
            assert abs(cover[y * r + x] - drawn * 255) <= 16, (r, x, y)  # the images' own corners, their sampling apart
    assert all(f'[{r}] = ' in art.corner_table() for r in art.CORNERS)


def test_the_rating_hearts_are_the_panels_size_and_ink():
    got = classic()
    for half, ink in (('l', (0, 0, 0)), ('d', (255, 255, 255))):
        w, h, on = pixels(got[f'classic_light_heart_on_{half}'])
        assert (w, h) == (32, 30) and on(16, 16) == (*ink, 255)  # filled
        _, _, off = pixels(got[f'classic_light_heart_off_{half}'])
        assert off(16, 16)[3] == 0 and off(16, 26)[:3] == ink and off(16, 26)[3] > 200  # its outline: the stroke at the point
        assert on(0, 0)[3] == 0 == off(0, 0)[3]
        assert max(x for x in range(32) if any(off(x, y)[3] for y in range(30))) == 31  # the stroke reaches its box's width


def test_the_station_cover_fills_the_slanted_arts_square():
    w, h, at = pixels(classic()['classic_light_station'])
    a = art.inc('NP_IPOD_ART')
    assert (w, h) == (a, a) and at(0, 0)[3] == at(a - 1, a - 1)[3] == 255  # opaque: the slant's paper never shows
    assert at(a // 2, a - 1)[:3] != at(a // 2, 0)[:3]  # its gradient, top to bottom
    assert min(at(54, 87)[:3]) > 200  # the left wave's white, at its widest
