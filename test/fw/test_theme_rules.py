"""theme_rules.c: a theme's rules for stock's widgets, from the hooks where each screen passes through the payload. A
hide is not drawn and takes no taps, a move keeps the whole widget in its box, Home's rows hide last in their order and
take their words, the status bar's come back each second with nothing written while they hold, and with no rules,
every built-in's case, nothing is read or written."""
import ctypes as C
import functools

import host
import test_coverflow as cf
from conftest import libc
from test_nav_playing import MODERN, THEMES, Now, theme, ui, st  # noqa: F401 (fixtures)

SCREEN = {s: i for i, s in enumerate(host.tools_theme.WIDGET_RULES)}  # theme.h's SCREEN_*
HIDE, MOVE, TEXT = 1, 2, 4  # rule_t.flags
HOME_ROWS = list(host.tools_theme.WIDGET_RULES['home']['widgets'])
WRITES = ('widget_set_visible', 'widget_set_opacity', 'widget_set_sensitive', 'widget_move_resize', 'widget_set_text_utf8',
          'widget_restack')


class Rule(C.Structure):  # theme.h's rule_t, as this build lays it out (checked against its debug info)
    _fields_ = [('screen', C.c_ubyte), ('flags', C.c_ubyte), ('x', C.c_short), ('y', C.c_short), ('box', C.c_short * 4),
                ('widget', C.c_char_p), ('text', C.c_char_p)]


@functools.cache
def layout(folder):
    """theme_t's rules and n_rules offsets in this build, with rule_t checked against Rule."""
    assert host.offsets(folder/'theme_rules.o', 'rule_t') == {f[0]: getattr(Rule, f[0]).offset for f in Rule._fields_}
    at = host.offsets(folder/'theme_engine.o', 'theme_t')
    return at['rules'], at['n_rules']


def rule(screen, widget, hide=False, at=None, box=None, text=None):
    """One rule_t row as tools/theme.py compiles a <widget>: at (x, y) in its WIDGET_RULES box, unless box says."""
    flags = HIDE * hide | MOVE * (at is not None) | TEXT * (text is not None)
    move = box or host.tools_theme.WIDGET_RULES[screen]['widgets'][widget].get('move', (0, 0, 0, 0))
    return Rule(SCREEN[screen], flags, *(at or (0, 0)), (C.c_short * 4)(*move), widget.encode(), text.encode() if text else None)


def give(fw, library, *rows):
    """The active theme's rules are rows. themes[] is the C's read-only table: its page is opened to write them."""
    rules, n_rules = layout(library.parent)
    T = fw.fn('theme', C.c_void_p)()
    assert not libc.mprotect((T + rules) & ~0xfff, 0x2000, 3)
    table = (Rule * len(rows))(*rows)
    fw.keep.append(table)
    C.c_void_p.from_address(T + rules).value = C.addressof(table)
    C.c_ubyte.from_address(T + n_rules).value = len(rows)


def apply(fw, win, screen):
    fw.fn('theme_rules', None, C.c_void_p, C.c_int)(win, SCREEN[screen])


def writes(fw, since=0):
    return [(name, args[0]) for name, args in fw.calls()[since:] if name in WRITES]


def opacity(fw, ui):
    """widget_set_opacity into the props widget_get_prop_int reads, as AWTK's opacity is read."""
    fw.mock('widget_set_opacity', lambda w, v, *_: ui[w].props.__setitem__('opacity', v))


def hidden(ui, w):
    return (ui[w].visible, ui[w].props.get('opacity', 255), ui[w].sensitive) == (0, 0, 0)


class Page:
    """Now Playing's iPod page as tools/ipod.py lays it out: the art page in the slide column under the top row, the art's
    play-state glyph beside it, the buffering spinner the window's, "3 of 12" in the top row left of More."""
    def __init__(self, ui):
        self.win = ui.make(0, 'window', 0, 30, 375, 290, name='playing_page')
        buttons = ui.make(self.win, 'view', 0, 0, 375, 40, name='view_buttons')
        self.pos = ui.make(buttons, 'label', 22, 0, 281, 40, name='label_ipod_pos')
        col = ui.make(self.win, 'view', 0, 40, 375, 192, name='slide_view_view')
        page = ui.make(ui.make(col, 'slide_view', 0, 0, 375, 186, name='slide_view'), 'view', 0, 0, 375, 186, name='view_album')
        self.cover = ui.make(page, 'image', 16, 2, 166, 166, name='img_cover')
        self.glyph = ui.make(page, 'image', 39, 25, 120, 120, name='img_playstate')
        self.title = ui.make(page, 'hscroll_label', 194, 18, 165, 28, name='scrlabel_title')
        self.wait = ui.make(self.win, 'image_animation', 72, 98, 54, 54, name='image_wait')


def test_no_rules_read_or_write_nothing(fw, st):
    """Every built-in states none: each screen's call reads and writes nothing."""
    ui = cf.Ui(fw)
    win = ui.make(0, 'window', name='w')
    for name in ('img_cover', 'img_bt', 'btn_folder', 'img_slide'):
        ui.make(win, 'image', name=name)
    for t in THEMES:
        theme(fw, st, t)
        since = len(fw.calls())
        for screen in SCREEN:
            apply(fw, win, screen)
        assert fw.calls()[since:] == [], t['id']


def test_now_playing_hides_and_moves_inside_the_box(fw, library):
    cf.themed(fw, cf.MODERN)
    ui = cf.Ui(fw)
    opacity(fw, ui)
    p = Page(ui)
    give(fw, library, rule('playing', 'img_cover', at=(300, 100)), rule('playing', 'label_ipod_pos', hide=True),
         rule('playing', 'scrlabel_title', at=(-40, 5), box=(10, 0, 375, 230)))
    apply(fw, p.win, 'playing')
    assert cf.rect(p.cover) == (375 - 166, 230 - 166, 166, 166)  # the whole art in the art page's box
    assert cf.rect(p.title)[:2] == (10, 5)  # and from the box's start
    # the glyph centred on the art's square, and the spinner on it in the window, through the column and page above it
    assert cf.rect(p.glyph) == (209 + 83 - 60, 64 + 83 - 60, 120, 120)
    assert cf.rect(p.wait) == (209 + 83 - 27, 40 + 64 + 83 - 27, 54, 54)
    assert hidden(ui, p.pos)
    since = len(fw.calls())
    apply(fw, p.win, 'playing')  # again: all holds, so nothing is written
    assert writes(fw, since) == []


def test_a_box_too_small_for_the_widget_keeps_it_on_that_axis(fw, library):
    cf.themed(fw, cf.MODERN)
    ui = cf.Ui(fw)
    p = Page(ui)
    give(fw, library, rule('playing', 'img_cover', at=(50, 50), box=(0, 0, 100, 230)))
    apply(fw, p.win, 'playing')
    assert cf.rect(p.cover) == (16, 50, 166, 166)
    give(fw, library, rule('playing', 'img_cover', at=(50, 50), box=(0, 0, 375, 100)))
    apply(fw, p.win, 'playing')
    assert cf.rect(p.cover) == (50, 50, 166, 166)


def test_a_rule_finds_its_own_screen_s_widget_alone(fw, library):
    """The lock screen's scrlabel_title is not Now Playing's."""
    cf.themed(fw, cf.MODERN)
    ui = cf.Ui(fw)
    p = Page(ui)
    give(fw, library, rule('lock', 'scrlabel_title', hide=True))
    since = len(fw.calls())
    apply(fw, p.win, 'playing')
    assert ui[p.title].visible and fw.calls()[since:] == []


def test_centred_now_playing_takes_none(fw, library):
    cf.themed(fw, cf.MODERN, NPCENTRED='1')
    ui = cf.Ui(fw)
    p = Page(ui)
    give(fw, library, rule('playing', 'img_cover', hide=True, at=(0, 0)))
    since = len(fw.calls())
    apply(fw, p.win, 'playing')
    assert writes(fw, since) == [] and ui[p.cover].visible


def test_now_playing_s_rules_run_as_the_page_opens_before_the_heart_s_badge(fw, ui, mcl, st, library):
    """ringnav_playing's hook: the art moved and "3 of 12" hidden, ahead of rate_bind's look for the heart."""
    theme(fw, st, MODERN)
    sensitive = {}
    fw.mock('widget_set_opacity', lambda w, v, *_: ui.ints.__setitem__((w, b'opacity'), v))
    fw.mock('widget_set_sensitive', lambda w, v, *_: sensitive.__setitem__(w, v))
    now = Now(fw, ui, mcl, st, opened=False)
    give(fw, library, rule('playing', 'img_cover', at=(30, 4)), rule('playing', 'label_ipod_pos', hide=True))
    assert now.open() == 41
    assert ui.box(now.cover)[:2] == (30, 4) and ui.box(now.state)[:2] == (30 + 89 - 20, 4 + 89 - 20)
    assert (ui.shown[now.pos], ui.ints[now.pos, b'opacity'], sensitive[now.pos]) == (0, 0, 0)
    looked = [C.string_at(args[1]) for _, args in fw.calls('widget_lookup')]
    assert looked.index(b'img_cover') < looked.index(b'img_fav')


class Bar:
    """The status bar's row as stock's tick leaves it: Bluetooth shown while connected, the clock at the bar's middle."""
    def __init__(self, fw, ui):
        self.bar = ui.make(0, 'system_bar', 0, 0, 375, 30, name='system_bar')
        row = ui.make(self.bar, 'view', 175, 0, 200, 30, name='view_right')
        self.bt = ui.make(row, 'image', 0, 6, 14, 18, name='img_bt')
        self.wifi = ui.make(row, 'image', 20, 6, 14, 18, name='img_wifi')
        self.clock = ui.make(self.bar, 'hscroll_label', 129, 0, 117, 30, name='label_clock')
        self.bt_on = 1
        fw.mock('stock_showface_trampoline', lambda *_: setattr(ui[self.bt], 'visible', self.bt_on))
        self.tick = lambda: fw.fn('ringnav_showface', C.c_int, C.c_void_p)(self.bar)


def test_the_status_bar_s_rules_come_back_each_second_with_nothing_written_while_they_hold(fw, library):
    cf.themed(fw, cf.MODERN)
    ui = cf.Ui(fw)
    opacity(fw, ui)
    b = Bar(fw, ui)
    give(fw, library, rule('bar', 'img_bt', hide=True), rule('bar', 'label_clock', at=(200, 2)))
    per_tick = []
    for bt_on in (1, 1, 0, 0):  # stock's tick shows Bluetooth again each second while it is on
        b.bt_on = bt_on
        since = len(fw.calls())
        b.tick()
        per_tick.append(sorted({name for name, w in writes(fw, since) if w in (b.bt, b.clock)}))
        assert hidden(ui, b.bt) and cf.rect(b.clock) == (200, 2, 117, 30)
    assert per_tick == [['widget_move_resize', 'widget_set_opacity', 'widget_set_sensitive', 'widget_set_visible'],
                        ['widget_set_opacity', 'widget_set_sensitive', 'widget_set_visible'], [], []]
    assert ui[b.wifi].visible  # what no rule names stays stock's


def test_the_clock_s_move_keeps_it_in_the_bar_s_box(fw, library):
    cf.themed(fw, cf.MODERN)
    ui = cf.Ui(fw)
    b = Bar(fw, ui)
    give(fw, library, rule('bar', 'label_clock', at=(374, 39)))
    b.tick()
    assert cf.rect(b.clock) == (375 - 117, 40 - 30, 117, 30)


def home_window(ui):
    """Home as tools/ipod.py lays it out: the art, then the main list's rows, each a label under a full-row image."""
    win = ui.make(0, 'window', 0, 30, 375, 290)
    ui.make(win, 'image', 0, 0, 375, 290, name='img_homeart')
    main = ui.make(win, 'list_view', 0, 8, 375, 273, name='list_view_home')
    view = ui.make(main, 'scroll_view', 0, 0, 375, 273, name='scroll_view_home')
    rows = {}
    for i, name in enumerate(HOME_ROWS):
        rows[name] = ui.make(view, 'view', 0, 39 * i, 375, 39, name=name)
        ui[ui.make(rows[name], 'hscroll_label', 39, 0, 303, 39, name='label_' + name[4:])].text = name[4:].title()
        ui.make(rows[name], 'image', 0, 0, 375, 39, name='img_' + name[4:])
    ui.top = win
    return win, main, view, rows


def home_order_holds(ui, view, rows):
    """The shown rows in Home's order, then the hidden ones in it."""
    order = [ui[w].name for w in ui[view].kids]
    shown = [n for n in HOME_ROWS if ui[rows[n]].visible]
    return order == shown + [n for n in HOME_ROWS if n not in shown]


def test_home_rows_hide_last_in_their_order_and_take_their_words(fw, library):
    """The theme hides Now Playing and Cover Flow, and Shortcut None hides the Shortcut row (coverflow_home_layout's)."""
    cf.themed(fw, cf.MODERN, SHORTCUT='11')
    ui = cf.Ui(fw)
    opacity(fw, ui)
    win, main, view, rows = home_window(ui)
    give(fw, library, rule('home', 'btn_playing', hide=True), rule('home', 'btn_folder', text='Albums é'),
         rule('home', 'btn_coverflow', hide=True))
    fw.mock('stock_home_trampoline', lambda *_: 0)
    fw.fn('coverflow_home', C.c_int, C.c_void_p, C.c_void_p)(win, 0)  # its layout, then the rules at its end
    assert [ui[w].name for w in ui[view].kids] == ['btn_localmusic', 'btn_folder', 'btn_stream', 'btn_settings',
                                                   'btn_playing', 'btn_coverflow', 'btn_rockbox']
    assert hidden(ui, rows['btn_playing']) and hidden(ui, rows['btn_coverflow']) and not ui[rows['btn_rockbox']].visible
    assert ui[ui[rows['btn_folder']].kids[0]].text == 'Albums é' and ui[ui[rows['btn_settings']].kids[0]].text == 'Settings'
    # the layout again (a card with Rockbox put in, a setting): it puts Folder, Rockbox and Streaming back by place
    # in the order the rules left, and the rules put the order right; the words hold, so none are written
    since, folder = len(fw.calls()), rows['btn_folder']
    fw.fn('coverflow_home_layout', None)()
    assert home_order_holds(ui, view, rows) and ui[folder].visible
    assert ('widget_set_text_utf8', ui[folder].kids[0]) not in writes(fw, since)


def test_home_with_words_alone_keeps_its_order(fw, library):
    cf.themed(fw, cf.MODERN)
    ui = cf.Ui(fw)
    win, main, view, rows = home_window(ui)
    give(fw, library, rule('home', 'btn_settings', text='Setup'))
    since = len(fw.calls())
    apply(fw, main, 'home')
    assert writes(fw, since) == [('widget_set_text_utf8', ui[rows['btn_settings']].kids[0])]
    assert [ui[w].name for w in ui[view].kids] == HOME_ROWS and ui[ui[rows['btn_settings']].kids[0]].text == 'Setup'


def test_the_lock_screen_s_rules_run_after_its_init(fw, library):
    cf.themed(fw, cf.MODERN)
    ui = cf.Ui(fw)
    opacity(fw, ui)
    win = ui.make(0, 'window', 0, 0, 375, 320, name='saverscreen_page')
    gesture = ui.make(win, 'gesture', 0, 0, 375, 320, name='app_gesture')
    card = ui.make(gesture, 'view', 20, 190, 335, 80, name='view_playinfo')
    hint = ui.make(gesture, 'image', 172, 285, 30, 16, name='img_slide')
    give(fw, library, rule('lock', 'view_playinfo', at=(20, 250)), rule('lock', 'img_slide', hide=True))
    fw.mock('stock_saver_trampoline', lambda *_: 31)
    assert fw.fn('lockscreen_init', C.c_int, C.c_void_p, C.c_void_p)(win, 0) == 31
    assert cf.rect(card) == (20, 280 - 80, 335, 80)  # clear of the hint's box, so the hint never takes its taps
    assert hidden(ui, hint)


def test_a_switch_to_or_from_other_rules_restarts(fw, library):
    """Home and the status bar keep a rule until a restart, so a theme on the same set with other rules asks for one."""
    cf.themed(fw, cf.MINIMAL)
    restart = fw.fn('theme_restart', C.c_int, C.c_int)
    modern = next(i for i, t in enumerate(THEMES) if t['id'] == 'modern')
    assert restart(modern) == 0  # Minimal and Modern share a set
    give(fw, library, rule('bar', 'img_bt', hide=True))
    assert restart(modern) == 1
