/* A theme's rules for stock's widgets (docs/internals.md#widget-rules): tools/theme.py checks a
 * theme.xml's <widgets> against its WIDGET_RULES and compiles them into theme_t.rules, and each
 * screen hands its window here where it already passes through the payload. A theme with none, as
 * every built-in, reads and writes nothing. A switch between themes whose rules differ restarts
 * (theme_restart): the status bar and Home are never rebuilt, and a rule keeps nothing to undo. */
#include "navigation.h"

/* Hidden: not drawn and no taps. Opacity 0 too, as stock's ticks write visible on some of these,
 * and not sensitive, as stock's hit test ignores visible. Nothing is written while it holds: the
 * status bar comes here each second. */
static void rule_hide(void *w) {
    if (!widget_get_visible(w) && !widget_get_prop_int(w, "opacity", 255)) return;
    widget_set_visible(w, 0, 0);
    widget_set_opacity(w, 0);
    widget_set_sensitive(w, 0);
}

/* v kept in lo..hi; past a box too small for the widget (hi < lo), was. */
static int rule_axis(int v, int lo, int hi, int was) {
    return hi < lo ? was : v < lo ? lo : v > hi ? hi : v;
}

/* w at x, y in its parent, its size kept, unless it's there. */
static void rule_place(void *w, int x, int y) {
    if (x != I(w, W_X) || y != I(w, W_Y)) widget_move_resize(w, x, y, I(w, W_W), I(w, W_H));
}

/* At the rule's x, y, the whole widget inside the rule's box. */
static void rule_move(void *w, const rule_t *r) {
    rule_place(w, rule_axis(r->x, r->box[0], r->box[2] - I(w, W_W), I(w, W_X)),
               rule_axis(r->y, r->box[1], r->box[3] - I(w, W_H), I(w, W_Y)));
}

/* A label's words, written only when they differ. */
static void rule_text(void *label, const char *text) {
    char had[48]; /* WIDGET_RULES' 40 bytes, and more: longer words differ anyway */
    if (label && (widget_get_text_utf8(label, had, sizeof had) || strcmp(had, text)))
        widget_set_text_utf8(label, text);
}

/* Now Playing's art moved: the play-state glyph, its sibling, and the buffering spinner, the
 * window's, centred on it again, on its square, as Classic's box holds the reflection below it. */
static void np_centre(void *win, void *art) {
    void *glyph = widget_lookup(win, "img_playstate", 1),
         *wait = widget_lookup(win, "image_wait", 1);
    int x = I(art, W_X) + I(art, W_W) / 2, y = I(art, W_Y) + I(art, W_W) / 2;
    if (glyph) rule_place(glyph, x - I(glyph, W_W) / 2, y - I(glyph, W_H) / 2);
    for (void *p = P(art, W_PARENT); p && p != win; p = P(p, W_PARENT))
        x += I(p, W_X), y += I(p, W_Y);
    if (wait) rule_place(wait, x - I(wait, W_W) / 2, y - I(wait, W_H) / 2);
}

/* Home's rows in their order, then every hidden one last, a theme's or coverflow_home_layout's:
 * the list lays out hidden rows too, and the layout puts Folder, Rockbox and Streaming back by
 * place, which a row a rule moved last would shift. */
static void home_order(void *list) {
    static const char *const rows[] = { RULE_HOME_ROWS };
    enum { N = sizeof rows / sizeof *rows };
    for (unsigned pass = 0; pass < 2; ++pass)
        for (unsigned i = 0; i < N; ++i) {
            void *row = widget_lookup(list, rows[i], 1);
            if (row && (!pass || !widget_get_visible(row))) widget_restack(row, pass ? N - 1 : i);
        }
}

/* screen's rules (SCREEN_*) on win: Now Playing's window (the iPod page's only), the status bar,
 * Home's main list or the lock window. */
void theme_rules(void *win, int screen) {
    const theme_t *T = theme();
    if (!T->n_rules || !win || (screen == SCREEN_PLAYING && np_layout() == NP_CENTRED)) return;
    int hid = 0;
    for (const rule_t *r = T->rules; r < T->rules + T->n_rules; ++r) {
        void *w = r->screen == screen ? widget_lookup(win, r->widget, 1) : (void *)0;
        if (!w) continue;
        if (r->flags & RULE_TEXT)
            rule_text(widget_get_child(w, 0), r->text); /* a Home row's label */
        if (r->flags & RULE_MOVE) {
            rule_move(w, r);
            if (screen == SCREEN_PLAYING && !strcmp(r->widget, "img_cover")) np_centre(win, w);
        }
        if (r->flags & RULE_HIDE) rule_hide(w), hid = 1;
    }
    if (hid && screen == SCREEN_HOME) home_order(win);
}
