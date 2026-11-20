/* Quick Settings, stock's pull-down: its holds (Wi-Fi's, Bluetooth's and the EQ's settings), the
 * key lock's button, the wheel's choice of brightness or volume, a stuck pull-down's release, and
 * Classic's page, buttons and brightness bar. */
#include "navigation.h"
extern int stock_quicksettings_trampoline(void *, void *);

static void quick_lock_text(void *win) {
    widget_set_text_utf8(widget_lookup(win, "label_lock", 1), lock_names[lock_choice()]);
    image_base_set_image(widget_lookup(win, "img_lock", 1),
                         g_keylock_flag ? "drop_keylockopen" : "drop_keylock");
}
int ringnav_quick_lock(void *win, void *event) {
    lock_set((lock_choice() + 1) % 4);
    quick_lock_text(win);
    return 0;
}
#define QUICK_HOLD "_quick_hold"
#define SLIDE_PX 10 /* the brightness slider's sideways move before it takes the touch */
static struct {
    void *win, *icon, *slider, *pressed; /* pressed: Classic's button under the finger */
    unsigned timer;
    int x, y, sx, sy, slide; /* slide: the slider's touch, 0 undecided, 1 its own, -1 the swipe's */
    int wheel;               /* the wheel: 1 + Q2POD QSVOLUME once read (quick_volume) */
} quick __attribute__((section(".scratch")));

static int quick_cancel(void *ctx, void *event) {
    stop_timer(&quick.timer);
    quick.win = quick.icon = quick.slider = 0;
    if (ctx) quick.pressed = 0; /* the window's going */
    return 0;
}
static int quick_long(const void *unused) {
    quick.timer = 0;
    void *win = quick.win, *icon = quick.icon;
    if (!win || window_manager_get_top_window(window_manager()) != win || !pointer_down()) return 0;
    int page = widget_get_prop_int(icon, QUICK_HOLD, 0);
    /* Abort the image's press before closing, so its release cannot click the icon. */
    prop(icon, QUICK_HOLD, -page);
    unsigned abort_event[12];
    pointer_event_init(abort_event, EVT_POINTER_ABORT, win, 0, 0);
    widget_dispatch_event_to_target_recursive(win, abort_event);
    quick_cancel(0, 0);
    dialog_quit(win, 0);
    /* The EQ page as the top window, under the dialog, is already the goal. One further down
     * (Return's hold opened Now Playing over it, #397) closes and the new one opens over the page
     * on top, as from any other page: a second would share peq_ui.c's one state. Dialogs and the
     * status bar are no windows. */
    if (page == 3) {
        void *wm = window_manager(), *eq = 0;
        int top = 1;
        for (unsigned i = widget_count_children(wm); !eq && i-- > 0;) {
            void *w = widget_get_child(wm, i);
            if (tk_strcmp(widget_get_type(w), "window")) continue;
            if (!tk_strcmp(widget_get_prop_str(w, "name", ""), "equalizer_page"))
                eq = w;
            else
                top = 0;
        }
        if (eq && top) return 0;
        if (eq) peq_page_replace(eq);
    }
    navigator_to(page == 1   ? "systemset/wifi_page"
                 : page == 2 ? "systemset/bluetooth_page"
                             : "playset/equalizer_page"); /* as Playback's EQ row (0x4bd114) */
    return 0;
}
static void quick_press(void *icon) {
    if (quick.pressed) widget_invalidate_force(quick.pressed, (void *)0);
    if (icon) widget_invalidate_force(icon, (void *)0);
    quick.pressed = icon;
}
static int quick_down(void *icon, void *event) {
    int page = widget_get_prop_int(icon, QUICK_HOLD, 0);
    if (classic_pages()) quick_press(icon);
    if (!page) return 0; /* a button with no hold */
    prop(icon, QUICK_HOLD, page < 0 ? -page : page);
    quick.win = window_manager_get_top_window(window_manager());
    quick.icon = icon;
    quick.x = I(event, EVENT_X), quick.y = I(event, EVENT_Y);
    rearm(&quick.timer, quick_long, RATE_HOLD_MS);
    return 0;
}
/* Classic's page (quick_page, quick_scrub), in the window's
 * coordinates: each icon at opacity 0 keeps stock's image name, tap and hold, and paints nothing.
 */
static const char *const quick_icons[] = { "img_wifiswitch", "img_btswitch", "img_lock",
                                           "img_gain",       "img_usbmode",  "img_po",
                                           "img_playset",    "img_sysset" },
                         *const quick_labels[] = { "label_wifi",    "label_bt",
                                                   "label_lock",    "label_gain",
                                                   "label_usbmode", "label_outputway",
                                                   "label_playset", "label_sysset" };
/* The bar's ends reach past what the slider repaints of itself. */
static int quick_moved(void *view, void *event) {
    widget_invalidate_force(view, (void *)0);
    return 0;
}
/* The brightness bar, in the window: its box, which the slider takes, its own 48 rows about it. */
#define QS_BAR_X 33
#define QS_BAR_Y 239
#define QS_BAR_W 309
#define QS_BAR_H 36
static void quick_open(void *win) {
    void *c = widget_lookup(win, "view_menu", 1);
    if (c) widget_move_resize(c, 0, 0, I(c, W_W), 226); /* the buttons' card and the gap under it */
    static const short column[] = { 33, 118, 203, 288 }; /* 31 apart, 15 in from the card's sides */
    for (unsigned i = 0; i < sizeof quick_icons / sizeof *quick_icons; ++i) {
        if (!(c = widget_lookup(win, quick_icons[i], 1))) continue;
        widget_move_resize(c, column[i % 4], i < 4 ? 34 : 122, 54, 54);
        widget_set_opacity(c, 0);
        if (!widget_get_prop_int(c, QUICK_HOLD, 0)) widget_on(c, EVT_POINTER_DOWN, quick_down, c);
    }
    if ((c = widget_lookup(win, "image0", 1))) widget_set_visible(c, 0, 0);
    if ((c = widget_lookup(win, "image1", 1))) widget_set_visible(c, 0, 0);
    if ((c = widget_lookup(win, "slider_backlight", 1))) {
        void *view = P(c, W_PARENT);
        widget_move_resize(view, 0, QS_BAR_Y + QS_BAR_H / 2 - 24, I(view, W_W), 48);
        widget_move_resize(c, QS_BAR_X, 0, QS_BAR_W, 48);
        widget_on(c, EVT_VALUE_CHANGING, quick_moved, view);
        widget_on(c, EVT_VALUE_CHANGED, quick_moved, view);
    }
}
int ringnav_quick_settings(void *win, void *ctx) {
    int result = stock_quicksettings_trampoline(win, ctx);
    if (win) {
        quick_lock_text(win);
        /* held: 1 Wi-Fi's settings, 2 Bluetooth's, 3 the EQ page (Playback's) */
        static const char *const names[] = { "img_wifiswitch", "img_btswitch", "img_playset" };
        for (int i = 0; i < 3; ++i) {
            void *icon = widget_lookup(win, names[i], 1);
            if (!icon) continue;
            prop(icon, QUICK_HOLD, i + 1);
            widget_on(icon, EVT_POINTER_DOWN, quick_down, icon);
        }
        if (classic_pages()) quick_open(win);
        widget_on(win, EVT_DESTROY, quick_cancel, win);
        widget_on(win, EVT_WINDOW_CLOSE, quick_cancel, win);
        widget_on(win, EVT_WINDOW_BACKGROUND, quick_cancel, win);
    }
    return result;
}

/* Quick Settings' brightness slider fills as Now Playing's bar does (np_fill), set before its
 * paint; QFILL holds the fill it last got, so a new accent or Light Mode reaches it. */
#define QFILL "_ringnav_fill"
static int quick_slider(void *w) {
    void *win = w && !tk_strcmp(widget_get_prop_str(w, "name", ""), "slider_backlight")
                    ? window_of(w)
                    : (void *)0;
    return win && !tk_strcmp(widget_get_prop_str(win, "name", ""), "statusbar_dialog");
}
void quick_fill(void *w) {
    if (!quick_slider(w)) return;
    /* Classic's bar is quick_scrub's: stock's goes clear, and 1 says it went */
    int clear = classic_pages();
    int color = clear ? 1 : (int)RGBA(accent_tone(TONE_LIGHT));
    if (widget_get_prop_int(w, QFILL, 0) == color) return;
    widget_set_prop_int(w, QFILL, color);
    slider_fill(w, clear ? 0 : (unsigned)color);
    if (clear) {
        static const char *const track[] = { "style:normal:bg_color", "style:pressed:bg_color",
                                             "style:over:bg_color", "style:focused:bg_color" };
        for (unsigned i = 0; i < sizeof track / sizeof *track; ++i)
            widget_set_prop_int(w, track[i], 0);
    }
}
#define QS_TEXT_W 86
#define QS_TEXT_PX 14
#define QS_TEXT_LINE 14 /* a line's pitch */
#define QS_TEXT_BOX 16  /* each line's box, holding the font */
/* Quick Settings under Classic, flat, in final colours, [0] dark, [1] light: the ground, the two
 * cards on it, a button at rest and a label. */
static const unsigned qs_ground[2] = { 0x000000, 0xf2f2f7 }, qs_card[2] = { 0x1c1c1e, 0xffffff },
                      qs_rest[2] = { 0x3a3a3c, 0xe9e9ec }, qs_quiet[2] = { 0x98989d, 0x6e6e73 };
/* What is on, final: Classic Blue's own blue (the theme's labelled scheme), or another accent's red
 * tone, as Minimal's lit discs take it. */
unsigned quick_on(void) {
    return theme()->schemes[accent()].label ? 0x207cde
                                            : flip_if(ipod_light(), accent_tone(TONE_RED));
}
/* One line of a label, the first n of s, quiet in x, y's box, in the system's face. */
static void quick_line(void *canvas, const unsigned *s, unsigned n, int x, int y) {
    unsigned line[32];
    rect_t r = { x, y, QS_TEXT_W, QS_TEXT_BOX };
    if (n > sizeof line / sizeof *line - 1) n = sizeof line / sizeof *line - 1;
    for (unsigned i = 0; i < n; ++i) line[i] = s[i];
    line[n] = 0;
    final_text(canvas, (void *)0, line, &r, QS_TEXT_PX, 0xff000000u | qs_quiet[ipod_light()]);
}
/* A label under its button, x, y its first line's box. The page draws its lines: stock's label
 * keeps the text and, for its repaint, a box round them, with its own ink clear. */
static void quick_label(void *canvas, void *label, int x, int y) {
    const unsigned *s = widget_get_text(label);
    unsigned n = wide_len(s), cut = 0, k = 1;
    if (!n) return;
    canvas_set_font(canvas, (void *)0, QS_TEXT_PX);
    int wrap = canvas_measure_text(canvas, s, n) > QS_TEXT_W, h = QS_TEXT_BOX + wrap * QS_TEXT_LINE;
    if (widget_get_prop_int(label, "_ringnav_box", 0) != h) {
        widget_set_prop_int(label, "_ringnav_box", h);
        slider_label(label, x, y, QS_TEXT_W, h, QS_TEXT_PX, "default");
        widget_set_prop_int(label, "style:normal:text_color", 0);
    }
    for (; wrap && k < n && canvas_measure_text(canvas, s, k) <= QS_TEXT_W; ++k)
        if (s[k] == ' ') cut = k;
    if (!wrap) cut = n;
    if (!cut) cut = k > 1 ? k - 1 : 1;
    quick_line(canvas, s, cut, x, y);
    if (wrap) {
        unsigned skip = cut + (s[cut] == ' ');
        quick_line(canvas, s + skip, n - skip, x, y + QS_TEXT_LINE);
    }
}
/* The page, in its window's coordinates: the ground and its two cards, then each button by the
 * image stock last gave its icon: a 54 px disc, at rest or on (QS_LIT, tools/art.py), a sixth
 * darker while pressed, its glyph in the disc's ink (white, or _l at rest in the light half and on
 * a bright accent), and its label. */
void quick_page(void *win, void *canvas) {
    int light = ipod_light();
    unsigned fill = (unsigned)I(P(canvas, CANVAS_LCD), LCD_FILL_COLOR), on = quick_on();
    rect_t buttons = { 18, 20, 339, 196 }, bar = { 18, 226, 339, 62 };
    stops_t card = { 2, { 0, 100 }, { qs_card[light], qs_card[light] } };
    bar_rect(canvas, RGBA(qs_ground[light]), 0, 0, I(win, W_W), I(win, W_H));
    paint_round_rows(canvas, &buttons, &card, 26);
    paint_round_rows(canvas, &bar, &card, 26);
    for (unsigned i = 0; i < sizeof quick_icons / sizeof *quick_icons; ++i) {
        void *icon = widget_lookup(win, quick_icons[i], 1);
        void *label = widget_lookup(win, quick_labels[i], 1);
        if (!icon) continue;
        char name[40];
        const char *image = widget_get_prop_str(icon, "image", "");
        int lit = named_in(QS_LIT, image);
        unsigned c = lit ? on : qs_rest[light];
        const char *ink = (lit ? bright_tone(c) : light) ? "_l" : "";
        if (icon == quick.pressed) c = mix(c, 0, 1, 6);
        rect_t r = { I(icon, W_X), I(icon, W_Y), 54, 54 };
        stops_t face = { 2, { 0, 100 }, { c, c } };
        paint_round_rows(canvas, &r, &face, 27);
        tk_snprintf(name, sizeof name, "classic_light_%s%s", image, ink);
        paint_art(win, canvas, name, r.x, r.y);
        if (label) quick_label(canvas, label, r.x - (QS_TEXT_W - 54) / 2, r.y + 57);
    }
    stock_canvas_set_fill_color(canvas, fill);
}
/* A 36 px bar, flat: r at rest, its first part px in what is on, and its marks in its ends
 * (BAR_SUNS, BAR_SPEAKERS, or none): the near one on the fill, white, or dark on a bright accent,
 * and the far one quiet until the fill reaches it. */
void flat_bar(void *w, void *canvas, const rect_t *r, int part, unsigned rest, int marks) {
    unsigned on = quick_on();
    int light = ipod_light(), dark = bright_tone(on), reached = part > r->w - r->h / 2;
    rect_t f = { r->x, r->y, part, r->h };
    stops_t under = { 2, { 0, 100 }, { rest, rest } }, lit = { 2, { 0, 100 }, { on, on } };
    paint_round_rows(canvas, r, &under, 18);
    paint_round_rows(canvas, &f, &lit, 18);
    if (marks == BAR_SUNS) {
        paint_art(w, canvas, dark ? "classic_light_drop_dim_l" : "classic_light_drop_dim", r->x + 6,
                  r->y + 6);
        paint_art(w, canvas,
                  reached ? dark ? "classic_light_drop_bright_l" : "classic_light_drop_bright"
                  : light ? "classic_light_drop_bright_ql"
                          : "classic_light_drop_bright_qd",
                  r->x + r->w - 33, r->y + 3);
    } else if (marks == BAR_SPEAKERS) {
        paint_art(w, canvas, dark ? "classic_light_spk_quiet_l" : "classic_light_spk_quiet_w",
                  r->x + 12, r->y + 11);
        paint_art(w, canvas,
                  reached ? dark ? "classic_light_spk_loud_l" : "classic_light_spk_loud_w"
                  : light ? "classic_light_spk_loud_l"
                          : "classic_light_spk_loud_d",
                  r->x + r->w - 34, r->y + 11);
    }
}
/* ringnav_paint, after stock's slider, whose bar quick_fill cleared: the bar, its fill never less
 * than its own round end, the suns in it; in the window's coordinates less the slider's. */
void quick_scrub(void *w, void *canvas) {
    if (!classic_pages() || !quick_slider(w) || !P(canvas, CANVAS_LCD)) return;
    unsigned fill = (unsigned)I(P(canvas, CANVAS_LCD), LCD_FILL_COLOR);
    void *view = P(w, W_PARENT);
    int ox = -I(view, W_X) - I(w, W_X), oy = -I(view, W_Y) - I(w, W_Y);
    int min = widget_get_prop_int(w, "min", 0), max = widget_get_prop_int(w, "max", 100);
    int part = QS_BAR_H;
    if (max > min)
        part += (QS_BAR_W - QS_BAR_H) *
                clamp_step(0, max - min, widget_get_prop_int(w, "value", 0) - min) / (max - min);
    rect_t r = { QS_BAR_X + ox, QS_BAR_Y + oy, QS_BAR_W, QS_BAR_H };
    flat_bar(w, canvas, &r, part, qs_rest[ipod_light()], BAR_SUNS);
    stock_canvas_set_fill_color(canvas, fill);
}

/* Quick Settings' swipe up under Classic: a touch from QS_SWIPE_Y that has gone SLIDE_PX up,
 * and isn't the slider's by then, counts for stock's handler as one from its line. */
static void quick_swipe(void *target, void *event) {
    int from = I(g_pressdown_y, 0);
    if (from < QS_SWIPE_Y || from >= QS_SWIPE_STOCK || from - I(event, EVENT_Y) < SLIDE_PX ||
        I(g_dropdown_menu_state, 0) != 3 || (quick.slider && quick.slide > 0) || !classic_pages() ||
        tk_strcmp(widget_get_prop_str(target, "name", ""), "statusbar_dialog"))
        return;
    I(g_pressdown_y, 0) = QS_SWIPE_STOCK;
}

/* ringnav_dispatch's Quick Settings part, for each event: a hold's timer and Classic's pressed
 * button, and the brightness slider's touch. What ringnav_dispatch returns, or -1 to go on. */
int quick_dispatch(void *target, void *event) {
    int type = I(event, EVENT_TYPE);
    if (quick.timer &&
        (type == EVT_POINTER_UP_BEFORE || type == EVT_POINTER_UP_BEFORE - 1 ||
         type == EVT_POINTER_ABORT || type == EVT_CLICK || type == EVT_KEY_DOWN_BEFORE ||
         ((type == EVT_POINTER_MOVE_BEFORE || type == EVT_POINTER_MOVE_BEFORE - 1) &&
          ((unsigned)(I(event, EVENT_X) - quick.x + 10) > 20 ||
           (unsigned)(I(event, EVENT_Y) - quick.y + 10) > 20))))
        quick_cancel(0, 0);
    if (quick.pressed && (type == EVT_POINTER_UP_BEFORE || type == EVT_POINTER_UP_BEFORE - 1 ||
                          type == EVT_POINTER_ABORT))
        quick_press(0);
    if (target && type == EVT_CLICK && widget_get_prop_int(target, QUICK_HOLD, 0) < 0) return STOP;
    /* Quick Settings' swipe up to close may start on its brightness slider. The slider gets
     * its press only once the touch has moved SLIDE_PX more sideways than up or down, or on a
     * tap's release; a touch that moves up or down first, or while stock slides the pull-down
     * (g_dropdown_menu_state 1, 2), never reaches it, and one it already has is aborted. A
     * withheld event returns 0, not STOP, which would end its parents' handling too: the
     * window manager's pointer-down keeps the touch's start (g_pressdown_y) for the swipe. */
    void *qs = target;
    if (type == EVT_POINTER_DOWN - 1 && target &&
        !tk_strcmp(widget_get_prop_str(target, "name", ""), "slider_backlight"))
        while (qs && tk_strcmp(widget_get_prop_str(qs, "name", ""), "statusbar_dialog"))
            qs = P(qs, W_PARENT); /* Quick Settings', not Settings' Brightness page */
    else
        qs = 0;
    if (qs) {
        quick.slider = target, quick.slide = 0;
        quick.sx = I(event, EVENT_X), quick.sy = I(event, EVENT_Y);
        return 0;
    }
    int move = type == EVT_POINTER_MOVE_BEFORE - 1, up = type == EVT_POINTER_UP_BEFORE - 1;
    if (move && target) quick_swipe(target, event);
    if (target && target == quick.slider && (move || up)) {
        int dx = I(event, EVENT_X) - quick.sx, dy = I(event, EVENT_Y) - quick.sy;
        dx = dx < 0 ? -dx : dx, dy = dy < 0 ? -dy : dy;
        unsigned ev[12];
        if ((unsigned)(I(g_dropdown_menu_state, 0) - 1) < 2) {
            if (quick.slide > 0)
                stock_dispatch_trampoline(target,
                                          pointer_event_init(ev, EVT_POINTER_ABORT, target, 0, 0));
            quick.slide = -1;
        } else if (!quick.slide && (up || (dx >= SLIDE_PX && dx > dy))) {
            quick.slide = 1;
            stock_dispatch_trampoline(
                target, pointer_event_init(ev, EVT_POINTER_DOWN - 1, target, quick.sx, quick.sy));
        } else if (!quick.slide && dy >= SLIDE_PX)
            quick.slide = -1;
        if (up) quick.slider = 0;
        if (quick.slide <= 0) return 0;
    } else if (up) /* a release the slider doesn't see, its press never given */
        quick.slider = 0;
    return -1;
}

/* Quick Settings' wheel: 0 its brightness slider, 1 stock's volume (Q2POD QSVOLUME). A held
 * Play/Pause there switches it (ringnav_keylong) and says so in the theme's own toast, over the
 * pull-down as stock's own messages are.
 * ponytail: the toast is modal, so it takes the wheel and Centre for its 2 s; a floating band kept
 * them live (until 1.8.2) but had no theme's look. */
int quick_volume(void) {
    if (!quick.wheel) quick.wheel = 1 + config_value("Q2POD", "QSVOLUME", 2, 0);
    return quick.wheel - 1;
}
/* The words for ringnav_keylong's toast; 0 when the hold is not Quick Settings'. */
const char *quick_wheel_toggle(void *top) {
    if (!usable() || !top || tk_strcmp(widget_get_prop_str(top, "name", ""), "statusbar_dialog"))
        return 0;
    int volume = !quick_volume();
    quick.wheel = 1 + volume;
    write_int_config(volume, "Q2POD", "QSVOLUME");
    return volume ? "Wheel: Volume" : "Wheel: Brightness";
}

/* Stock's swipe down opens Quick Settings at g_dropdown_menu_state 1 and starts its slide only on
 * the touch's release reaching the dialog (its pointer-up handler adds the timer_idex timer). The
 * dialog is modal, opened inside the swipe's pointer move, and above the screen it catches a touch
 * only once opened (window_manager_find_target, stage 3), in an idle its nested loop runs after
 * draining the queue. So a release already queued, by a flick quicker than the dialog loads or a
 * swipe queued behind a track start, goes to the page under it: the dialog stays on top off screen
 * with that page sent to the background, Now Playing's timer stopped (#189). With no touch down
 * and no slide running, the next UI pass hands it the release through ringnav_dispatch: stock's
 * handler (0x4a1e6c, bound at dialog_statusbar_dialog_init) ignores the event's place and at states
 * 1 and 2 with timer_idex -1 always adds its slide timer (0x4a1f4c), which always ends, so one pass
 * does it. */
static int quick_stuck(void *top) {
    return usable() && top &&
           !tk_strcmp(widget_get_prop_str(top, "name", ""), "statusbar_dialog") &&
           (unsigned)(I(g_dropdown_menu_state, 0) - 1) < 2 && !pointer_down() &&
           widget_get_prop_int(top, "timer_idex", -1) == -1;
}
void quick_poll(void) {
    void *wm = window_manager(), *top = window_manager_get_top_window(wm);
    unsigned up[12];
    if (quick_stuck(top))
        ringnav_dispatch(top, pointer_event_init(up, EVT_POINTER_UP_BEFORE - 1, top, 0, 0));
    /* Return's hold over Quick Settings (compact_now_playing), once the dialog has gone: its own
     * idle closes it, a pass or two on. One still up QS_HOLD_MS later was no hold's to wait for. */
    if (st.qs_hold && (unsigned)time_now_ms() - st.qs_hold >= QS_HOLD_MS) st.qs_hold = 0;
    if (st.qs_hold && top && !window_manager_is_animating(wm) &&
        tk_strcmp(widget_get_prop_str(top, "name", ""), "statusbar_dialog")) {
        st.qs_hold = 0;
        compact_now_playing();
    }
}
