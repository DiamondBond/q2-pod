/* Logical menu selection is independent of native touch focus. Stock code owns gestures. */
#include "stock.h"
#define STOP 11
#define EVT_CLICK 0x10c
#define KEY_CENTER 218
#define KEY_PREV 172
#define KEY_NEXT 173
#define GLIDE_MS 300
#define DOUBLE_CLICK_MS 250
#define DUPLICATE_MS 80
#define RET_OK 0
#define RET_REMOVE 7
#define RET_REPEAT 8
#define MAX_ENTRIES 256
#define I(p, o) (*(int *)((char *)(p) + (o)))
#define P(p, o) (*(void **)((char *)(p) + (o)))
#define B(p, o) (*(unsigned char *)((char *)(p) + (o)))

static int eq(const char *a, const char *b) {
    if (!a || !b) return 0;
    while (*a && *a == *b) {
        ++a;
        ++b;
    }
    return *a == *b;
}

static int allowed(const char *name) {
    static const char *const names[] = {
#include "contexts.inc"
#ifdef RINGNAV_IPOD
        /* Its rows only look right once re-laid out as iPod rows, which needs a supported page. */
        "updatemusic_page",
        "ipod_accent_page", /* Display setting > Theme Colour (built in code) */
#endif
    };
    for (unsigned i = 0; i < sizeof(names) / sizeof(*names); ++i)
        if (eq(name, names[i])) return 1;
    return 0;
}

/* Only one visible navigation surface: never guess between two panes.
 * ponytail: bounded tree walk per detent; cache only if measured UI cost warrants it. */
static void find_surface(void *w, void **found, int *count, int depth, int *budget) {
    if (!w || !widget_get_visible(w) || !widget_get_prop_bool(w, "enable", 1)) return;
    if (depth == 16 || --*budget < 0) {
        *count = 2;
        return;
    }
    const char *type = widget_get_type(w);
    if (eq(type, "scroll_view") || eq(type, "table_client") || eq(type, "slide_menu")) {
        *found = w;
        ++*count;
        return;
    }
    if (eq(type, "pages")) {
        int active = widget_get_prop_int(w, "active", -1);
        if (active >= 0) find_surface(widget_get_child(w, active), found, count, depth + 1, budget);
        return;
    }
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n && *count < 2; ++i)
        find_surface(widget_get_child(w, i), found, count, depth + 1, budget);
}

static int clamp_step(int offset, int maximum, int delta) {
    if (maximum < 0) maximum = 0;
    if (offset < 0) offset = 0;
    if (offset > maximum) offset = maximum;
    if (delta > 0) return maximum - offset < delta ? maximum : offset + delta;
    return offset < -delta ? 0 : offset + delta;
}

/* A tap target has an EVT_CLICK handler. V1.32 widget emitter @0x60; emitter_on_with_tag items are
 * {ctx, id, type @8, handler, tag, working @0x14, pending_remove @0x15, next @0x20}. */
static int clickable(void *w) {
    void *emitter = P(w, 0x60);
    for (void *item = emitter ? P(emitter, 0) : (void *)0; item; item = P(item, 0x20))
        if (I(item, 8) == EVT_CLICK && !B(item, 0x15)) return 1;
    return 0;
}

typedef struct {
    void **at;
    int n, cap, budget;
} entries_t;

/* Visible, enabled tap targets in pre-order; a target's descendants belong to it.
 * ponytail: capped walk; raise MAX_ENTRIES if a real list outgrows it. */
static void collect(void *w, entries_t *s, int depth) {
    if (!w || !widget_get_visible(w) || !widget_get_prop_bool(w, "enable", 1)) return;
    if (depth == 16 || s->n == s->cap || --s->budget < 0) return;
    if (clickable(w)) {
        s->at[s->n++] = w;
        return;
    }
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n; ++i) collect(widget_get_child(w, i), s, depth + 1);
}

static void *first_entry(void *w) {
    void *one = (void *)0;
    entries_t s = { &one, 0, 1, 256 };
    collect(w, &s, 0);
    return one;
}

/* Widget-owned properties die with the surface; never retain recycled row pointers. */
#define SEL "_ringnav_index"
#define TOUCH "_ringnav_touch"
#define COUNT "_ringnav_count"

/* Release time of the last centre press and the timer holding its click until the double-press
 * window closes; both zero when idle. External linkage keeps the compiler from splitting it. */
struct {
    unsigned last, timer;
} center __attribute__((section(".scratch")));

static void cancel_click(void) {
    if (center.timer) timer_remove(center.timer);
    center.timer = 0;
}

typedef struct {
    int x, y, w, h;
} rect_t;
typedef struct {
    void *w, *at[MAX_ENTRIES];
    int id[MAX_ENTRIES], n, kind, rows, row, top, height;
#ifdef RINGNAV_IPOD
    int per; /* selectable entries per table row: GRID_N in the album grid, else 1 */
#endif
} menu_t;
#ifdef RINGNAV_IPOD
/* Album grid view: 160 px table rows of three album tiles (img_icon1..3), each its own entry;
 * entry ids are row * GRID_N + tile. */
#define GRID_H 160
#define GRID_N 3
#define PER(m) ((m)->per)
#else
#define PER(m) 1
#endif

#ifdef RINGNAV_IPOD
/* usable() without the USB-link check: pop-ups (Scan music? after USB storage) take the wheel even
 * while the cable is in. */
static int dialog_usable(void) {
    return g_backlight_status && !g_lockscreen_pageflag && !g_testmode_flag && !g_guideflag &&
           !g_poweroff_state && !bt__recv_pageflag;
}
#endif

static int usable(void) {
    return g_backlight_status && !g_lockscreen_pageflag && !g_testmode_flag && !g_guideflag &&
           !g_poweroff_state && g_usblink_status != 2 && !bt__recv_pageflag;
}

static void *surface(void) {
    if (!usable()) return (void *)0;
    void *wm = window_manager(), *top = window_manager_get_top_window(wm);
    if (!top || window_manager_is_animating(wm) ||
        !allowed(widget_get_prop_str(top, "name", (void *)0)))
        return (void *)0;
    void *w = (void *)0;
    int count = 0, budget = 512;
    find_surface(top, &w, &count, 0, &budget);
    return count == 1 ? w : (void *)0;
}

#ifdef RINGNAV_IPOD
/* surface() for a given window, also while it animates (see ringnav_prepare). */
static void *surface_of(void *top) {
    if (!top || !allowed(widget_get_prop_str(top, "name", (void *)0))) return (void *)0;
    void *w = (void *)0;
    int count = 0, budget = 512;
    find_surface(top, &w, &count, 0, &budget);
    return count == 1 ? w : (void *)0;
}
#endif

static int kind(void *w) {
    const char *t = widget_get_type(w);
    if (eq(t, "slide_menu")) return 3;
    if (eq(t, "table_client")) return 2;
    return eq(t, "scroll_view") && B(w, 0x91) && !B(w, 0x92) ? 1 : 0;
}

static void prop(void *w, const char *name, int value) {
    if (widget_get_prop_int(w, name, -1) != value) widget_set_prop_int(w, name, value);
}

#ifdef RINGNAV_IPOD
static const char *window_name(void *w);
#endif

static int load(menu_t *m, void *w) {
    m->w = w;
    m->n = 0;
    m->kind = kind(w);
    m->height = I(w, 0x0c);
    if (!m->kind || m->height <= 0) return 0;
    m->top = m->kind == 3 ? 0 : I(w, m->kind == 2 ? 0x80 : 0x84);
    m->row = m->kind == 2 ? I(w, 0x78) : 0;
    m->rows = m->kind == 2 ? I(w, 0x7c) : 0;
    if (m->kind == 2 && (m->row <= 0 || m->rows < 0 || m->rows > 0x7fffffff / m->row)) return 0;
#ifdef RINGNAV_IPOD
    m->per = m->kind == 2 && m->row == GRID_H && eq(window_name(w), "album_page") ? GRID_N : 1;
#endif
    if (m->kind == 1 && I(w, 0x7c) < 0) return 0;
    unsigned n = widget_count_children(w);
    if (m->kind == 1) {
        entries_t s = { m->at, 0, MAX_ENTRIES, 2048 };
        for (unsigned i = 0; i < n; ++i) collect(widget_get_child(w, i), &s, 1);
        m->n = s.n;
        m->rows = s.n;
        for (int i = 0; i < m->n; ++i) m->id[i] = i;
    } else {
        if (m->kind == 3) m->rows = (int)n;
        for (unsigned i = 0; i < n && m->n < MAX_ENTRIES; ++i) {
#ifdef RINGNAV_IPOD
            if (PER(m) > 1) { /* grid row: each tile is an entry */
                void *tiles[GRID_N], *r = widget_get_child(w, i);
                entries_t s = { tiles, 0, GRID_N, 64 };
                int base = r ? I(r, 0x78) : -1;
                if (base < 0 || base >= m->rows) continue;
                collect(r, &s, 0);
                for (int t = 0; t < s.n && m->n < MAX_ENTRIES; ++t) {
                    m->at[m->n] = tiles[t];
                    m->id[m->n++] = base * GRID_N + t;
                }
                continue;
            }
#endif
            void *r = widget_get_child(w, i), *e = first_entry(r);
            int id = m->kind == 2 ? I(r, 0x78) : (int)i;
            if (e && id >= 0 && id < m->rows) {
                m->at[m->n] = e;
                m->id[m->n++] = id;
            }
        }
    }
#ifdef RINGNAV_IPOD
    m->rows *= PER(m);
#endif
    if (widget_get_prop_int(w, COUNT, -1) != m->rows) {
        prop(w, SEL, -1);
        prop(w, COUNT, m->rows);
    }
    return 1;
}

static rect_t bounds(menu_t *m, int i) {
    void *e = m->at[i];
    rect_t r = { 0, 0, I(e, 8), I(e, 0x0c) };
    for (void *p = e; p && p != m->w; p = P(p, 0x48)) {
        r.x += I(p, 0);
        r.y += I(p, 4);
    }
    if (m->kind != 3) r.y -= m->top;
    if (m->kind == 1) r.x -= I(m->w, 0x80);
    return r;
}

static int index_of(menu_t *m, int id) {
    for (int i = 0; i < m->n; ++i)
        if (m->id[i] == id) return i;
    return -1;
}

static int moving(menu_t *m) {
    return m->kind == 1 ? P(m->w, 0xe8) != 0 : m->kind == 2 ? P(m->w, 0xd0) != 0 : 0;
}

static void stop_scroll(menu_t *m) {
    if (m->kind == 2)
        table_client_stop_animator_scroll(m->w);
    else if (m->kind == 1 && P(m->w, 0xe8)) {
        /* Same pause/destroy/null sequence as stock table_client_stop_animator_scroll. */
        void *a = P(m->w, 0xe8);
        widget_animator_pause(a);
        widget_animator_destroy(a);
        P(m->w, 0xe8) = (void *)0;
    }
}

/* Keep selection during native momentum and wheel glides. Once settled, repair an offscreen
 * selection using the first fully visible target (partially visible only for oversized rows). */
static int reconcile(menu_t *m, int settle) {
    int id = m->kind == 3 ? I(m->w, 0x78) : widget_get_prop_int(m->w, SEL, -1);
    int cur = index_of(m, id), first = -1, partial = -1;
    if (m->kind == 3) return cur;
    /* A virtual table binds rows only when it next lays out, so a wheel jump (acceleration) can
     * land on a row that has no widget yet. It is still a valid selection if it is logically in
     * view; repairing it to the first visible row would undo the jump. */
#ifdef RINGNAV_ACCEL
    if (m->kind == 2 && cur < 0 && id >= 0 && id < m->rows) {
        int y = id / PER(m) * m->row - m->top;
        if (y + m->row > 0 && y < m->height) return -1;
    }
#endif
    for (int i = 0; i < m->n; ++i) {
        rect_t r = bounds(m, i);
        if (r.y < m->height && r.y + r.h > 0) {
            if (partial < 0) partial = i;
            if (r.y >= 0 && r.y + r.h <= m->height && first < 0) first = i;
        }
    }
    if (cur >= 0) {
        rect_t r = bounds(m, cur);
        if ((r.y < m->height && r.y + r.h > 0) || !settle) return cur;
    } else if (id >= 0 && id < m->rows && !settle)
        return -1;
    cur = first >= 0 ? first : partial;
    prop(m->w, SEL, cur >= 0 ? m->id[cur] : -1);
    return cur;
}

#ifdef RINGNAV_DUMP
/* Debug aid: write each new top window's live widget tree to the SD card two seconds after it
 * opens, so runtime-built rows can be studied. Read-only; behaviour is otherwise unchanged. */
#define DUMP_DELAY_MS 2000
#define DUMP_BYTES 24576
struct {
    void *top;
    unsigned timer;
} dump __attribute__((section(".scratch")));

typedef struct {
    char *buf;
    int len;
} out_t;

static void node(out_t *o, void *w, int depth, int *budget) {
    if (!w || depth > 24 || --*budget < 0 || o->len > DUMP_BYTES - 256) return;
    const char *name = widget_get_prop_str(w, "name", (void *)0);
    const char *style = widget_get_prop_str(w, "style", (void *)0);
    const char *image = widget_get_prop_str(w, "image", (void *)0);
    char text[44];
    const int *wt = widget_get_text(w);
    int k = 0;
    for (; wt && wt[k] && k < 40; ++k) text[k] = wt[k] < 128 ? (char)wt[k] : '?';
    text[k] = 0;
    o->len += tk_snprintf(o->buf + o->len, DUMP_BYTES - o->len,
                          "%*s%s name=%s rect=%d,%d,%d,%d vis=%d style=%s image=%s row_h=%d item_h=%d text='%s'\n",
                          depth * 2, "", widget_get_type(w), name ? name : "-", I(w, 0), I(w, 4),
                          I(w, 8), I(w, 0x0c), widget_get_visible(w), style ? style : "-",
                          image ? image : "-", widget_get_prop_int(w, "row_height", -1),
                          widget_get_prop_int(w, "item_height", -1), text);
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n; ++i) node(o, widget_get_child(w, i), depth + 1, budget);
}

static int dump_now(const void *info) {
    (void)info;
    dump.timer = 0;
    void *top = window_manager_get_top_window(window_manager());
    if (!top) return RET_REMOVE;
    char buf[DUMP_BYTES], path[96];
    out_t o = { buf, 0 };
    int budget = 1500;
    node(&o, top, 0, &budget);
    const char *name = widget_get_prop_str(top, "name", (void *)0);
    tk_snprintf(path, sizeof(path), "/mnt/mmc/q2dump_%s.txt", name ? name : "unnamed");
    file_write(path, buf, (unsigned)o.len);
    return RET_REMOVE;
}

static void dump_watch(void) {
    void *top = window_manager_get_top_window(window_manager());
    if (!top || top == dump.top) return;
    dump.top = top;
    if (dump.timer) timer_remove(dump.timer);
    dump.timer = timer_add(dump_now, (void *)0, DUMP_DELAY_MS);
}

#endif

#ifdef RINGNAV_IPOD
/* iPod classic list rows. Stock rows are 78 px cards (row > button > icon, title, details, arrow)
 * built by app callbacks. Each paint re-lays them out as flat 30 px text rows; the selected entry
 * and its title switch to the theme's "ipod_sel" styles, and switch back to whatever the app had
 * set (remembered on the widget) once deselected. Only mutates when a value differs. */
#define ROW_H 30
#ifndef ROW_INSET
#define ROW_INSET 0 /* >0: the row's button becomes an inset pill (modern theme) */
#endif
#define ROW2_H 40 /* two-line rows: title over artist, like the iPod's song lists */
#define ROWART_H 46 /* Up Next and Albums: a rounded cover left of the two lines, like Apple Music */
#define ART_S 36
#define FLAT_H(h) ((h) <= ROW2_H || (h) == ROWART_H) /* rows made by the height hook, not stock */
#define IPOD_ART "_ipod_art" /* on the entry: the paint hook draws its img_icon cover, rounded */
#define IPOD_SEL "ipod_sel"
#define IPOD_SEL2 "ipod_sel2"
#define IPOD_SAVED "_ipod_style"

static const char *window_name(void *w) {
    for (void *p = w; p; p = P(p, 0x48))
        if (eq(widget_get_type(p), "window")) return widget_get_prop_str(p, "name", (void *)0);
    return (void *)0;
}

int ringnav_rowh(void *client, void *height) {
    /* Tables ask for their row height once, before creating rows: stock 78 px list rows become
     * 30 px, 40 px two-line rows on Songs, or 46 px cover rows on Albums and Up Next. */
    if ((unsigned long)height == 78) {
        const char *win = window_name(client);
        height = (void *)(eq(win, "playerqueue_page") || eq(win, "album_page") ? ROWART_H
                          : eq(win, "allmusic_page")                          ? ROW2_H
                                                                              : ROW_H);
    }
    return stock_rowh(client, height);
}

static int place(void *w, int x, int y, int ww, int h) {
    if (I(w, 0) == x && I(w, 4) == y && I(w, 8) == ww && I(w, 0x0c) == h) return 0;
    widget_move_resize(w, x, y, ww, h);
    return 1;
}

static int hide(void *w) {
    if (!widget_get_visible(w)) return 0;
    widget_set_prop_int(w, "visible", 0);
    return 1;
}

static int restyle(void *w, int selected, const char *sel) {
    const char *cur = widget_get_prop_str(w, "style", (void *)0);
    int is_sel = eq(cur, sel);
    if (selected == is_sel) return 0;
    if (selected) {
        widget_set_prop_str(w, IPOD_SAVED, cur ? cur : "");
        widget_use_style(w, sel);
    } else
        widget_use_style(w, widget_get_prop_str(w, IPOD_SAVED, ""));
    return 1;
}

static int is_label(void *w) {
    const char *t = widget_get_type(w);
    return eq(t, "hscroll_label") || eq(t, "label");
}

/* First visible label in pre-order other than skip: the title, then the second line. */
static void *find_label(void *w, void *skip, int depth) {
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n && depth < 6; ++i) {
        void *c = widget_get_child(w, i), *t;
        if (!c || !widget_get_visible(c)) continue;
        if (is_label(c) && c != skip) return c;
        if ((t = find_label(c, skip, depth + 1))) return t;
    }
    return (void *)0;
}

static int holds(void *outer, void *w) {
    for (void *p = w; p; p = P(p, 0x48))
        if (p == outer) return 1;
    return 0;
}

static int starts(const char *s, const char *prefix) {
    if (!s) return 0;
    while (*prefix)
        if (*s++ != *prefix++) return 0;
    return 1;
}

typedef struct {
    void *entry, *title, *sub, *art, *pick; /* sub: second line; art: cover (Up Next); pick: multi-select */
    int width, h, tw, tx;            /* tw/tx: title width and x, around the chevron, state, art */
} row_t;

/* A right-hand state image (gain level, switch): not the chevron, tick or a tap target. */
static int has_state(void *w, int width, int depth) {
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n && depth < 6; ++i) {
        void *c = widget_get_child(w, i);
        if (!c) continue;
        if (eq(widget_get_type(c), "image")) {
            const char *img = widget_get_prop_str(c, "image", (void *)0);
            if (!eq(img, "list_into") && !eq(img, "list_intodown") && !clickable(c) &&
                !starts(widget_get_prop_str(c, "name", (void *)0), "img_choice") && I(c, 0) >= width / 2)
                return 1;
        } else if (has_state(c, width, depth + 1))
            return 1;
    }
    return 0;
}

/* Tappable option images inside a row (the playback speed chips), not full-row tap targets. */
static int is_chip(void *c, int width) {
    return eq(widget_get_type(c), "image") && widget_get_visible(c) && clickable(c) && I(c, 0) >= 100 &&
           I(c, 8) < width / 3;
}

#define CHIP_GAP 4
/* Chips are packed against the row's right edge in child order, leaving the title room. Returns
 * the packed x of chip c (or of the first chip when c is null); width when the row has none. */
static int chip_x(void *entry, void *c, int width) {
    int total = 0, before = 0, n = 0, seen = 0;
    for (unsigned i = 0, m = widget_count_children(entry); i < m; ++i) {
        void *k = widget_get_child(entry, i);
        if (!k || !is_chip(k, width)) continue;
        if (k == c) seen = 1;
        if (!seen && c) before += I(k, 8) + CHIP_GAP;
        total += I(k, 8);
        ++n;
    }
    return n ? width - 8 - total - (n - 1) * CHIP_GAP + before : width;
}

static int flatten(row_t *r, void *w, int depth) {
    int changed = 0, two = r->sub != 0, x = w == r->entry ? r->tx : 0, tw = r->tw;
    int ty = r->h > ROW2_H ? (r->h - ROW2_H) / 2 : 0; /* two lines centred in taller rows */
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n && depth < 6; ++i) {
        void *c = widget_get_child(w, i);
        if (!c) continue;
        const char *t = widget_get_type(c);
        if (c == r->title)
            changed |= place(c, x, two ? ty + 1 : 0, tw, two ? 22 : r->h);
        else if (two && c == r->sub)
            /* In the artist's own view (with the format badge) it sits at that view's origin. */
            changed |= holds(w, r->title) || w == r->entry ? place(c, x, ty + 21, tw, 18) : place(c, 0, 0, tw, 18);
        else if (is_label(c))
            changed |= hide(c);
        else if (eq(t, "view")) {
            if (holds(c, r->title)) {
                changed |= place(c, r->tx, 0, tw, r->h);
                changed |= flatten(r, c, depth + 1);
            } else if (two && holds(c, r->sub)) {
                changed |= place(c, x, ty + 21, tw, 18);
                changed |= flatten(r, c, depth + 1);
            } else
                changed |= hide(c);
        } else if (eq(t, "image")) {
            const char *img = widget_get_prop_str(c, "image", (void *)0);
            if (starts(widget_get_prop_str(c, "name", (void *)0), "img_choice") && I(c, 0) >= r->width / 2) {
                changed |= place(c, r->width - 40, 0, 32, r->h); /* single-choice radio (sort order) */
                continue;
            }
            if (c == r->pick) {
                changed |= place(c, 10, 0, 26, r->h); /* multi-select circle, left of the title */
                continue;
            }
            if (is_chip(c, r->width)) {
                changed |= place(c, chip_x(w, c, r->width), 0, I(c, 8), r->h); /* option chip (speed) */
                continue;
            }
            if (starts(widget_get_prop_str(c, "name", (void *)0), "img_choice") || clickable(c) ||
                ((!img || !*img) && I(c, 8) >= r->width * 3 / 4))
                continue; /* multi-select tick, or a tap target (Home rows; its handler may come later) */
            if (c == r->art) {
                /* The cover keeps a place, drawn by the paint hook (smooth, rounded); the stock
                 * nearest-neighbour draw is skipped with opacity 0. */
                changed |= place(c, 10, (r->h - ART_S) / 2, ART_S, ART_S);
                if (!widget_get_visible(c)) widget_set_prop_int(c, "visible", 1), changed = 1;
                if (widget_get_prop_int(c, "opacity", 255)) widget_set_prop_int(c, "opacity", 0), changed = 1;
                continue;
            }
            if (eq(img, "list_into") || eq(img, "list_intodown"))
                changed |= place(c, r->width - 30, 0, 24, r->h);
            else if (I(c, 0) >= r->width / 2) {
                /* Right-hand state (gain level, on/off switch) stays, shrunk into the row. */
                if (place(c, r->width - 56, 0, 50, r->h)) {
                    widget_set_prop_str(c, "draw_type", "icon");
                    changed = 1;
                }
            } else
                changed |= hide(c); /* icons, covers, format badges */
        }
    }
    return changed;
}

#if defined(RINGNAV_IPOD) && defined(RINGNAV_ACCEL)
/* Fast-scroll letter, like the iPod classic: while detents jump LETTER_STEP+ rows, the theme's hidden
 * "ipod_letter" label shows the first character of the selected title, and hides LETTER_MS after
 * the last fast detent. The letter is read after rows are bound (idle pass), since a jump lands
 * on rows the table has not created yet. */
#define LETTER_STEP 8
#define LETTER_MS 800
struct {
    unsigned timer;
    int on;
} letter __attribute__((section(".scratch")));

static void *letter_label(void) {
    void *top = window_manager_get_top_window(window_manager());
    return top ? widget_lookup(top, "ipod_letter", 1) : (void *)0;
}

static int letter_hide(const void *info) {
    (void)info;
    letter.timer = 0;
    letter.on = 0;
    void *l = letter_label();
    if (l) hide(l);
    return RET_REMOVE;
}

static void letter_poke(void) {
    letter.on = 1;
    if (letter.timer) timer_remove(letter.timer);
    letter.timer = timer_add(letter_hide, (void *)0, LETTER_MS);
}

static int letter_update(menu_t *m, int cur) {
    if (!letter.on || cur < 0) return 0;
    void *l = letter_label(), *title = find_label(m->at[cur], (void *)0, 0);
    const int *t = title ? widget_get_text(title) : (void *)0, *shown;
    if (!l || !t || !t[0]) return 0;
    int c = t[0], changed = 0;
    if (c >= 'a' && c <= 'z') c -= 'a' - 'A';
    else if (c >= '0' && c <= '9') c = '#';
    shown = widget_get_text(l);
    if (!shown || shown[0] != c || shown[1]) {
        int buf[2] = { c, 0 };
        widget_set_text(l, buf);
        changed = 1;
    }
    if (!widget_get_visible(l)) {
        widget_set_prop_int(l, "visible", 1);
        changed = 1;
    }
    return changed;
}
#endif

/* Restyling while the frame paints loses the invalidation and leaves stale fragments, so paints
 * only schedule an idle pass; it applies any changes and invalidates outside the paint. */
struct {
    unsigned idle, album, dialog;
} ipod __attribute__((section(".scratch")));

/* Now Playing's album line reads "Album:<name>" and the app keeps re-setting it, so the theme hides
 * label_album and shows label_album_ipod; this copies the text across without the prefix, only
 * when it changes. Exact known prefixes only, so an album called "Star Wars: ..." is safe. */
static const int album_en[] = { 'A', 'l', 'b', 'u', 'm', ':', 0 };
static const int album_zh[] = { 0x4e13, 0x8f91, ':', 0 };
static const int album_zh2[] = { 0x4e13, 0x8f91, 0xff1a, 0 };

static int album_prefix(const int *t) {
    const int *const all[] = { album_en, album_zh, album_zh2 };
    for (unsigned k = 0; t && k < 3; ++k) {
        int i = 0;
        while (all[k][i] && t[i] == all[k][i]) ++i;
        if (!all[k][i]) return i;
    }
    return 0;
}

/* Rounded Now Playing art. The theme gives img_cover opacity 0 (the toolkit skips drawing it but it
 * stays tappable, and the app keeps setting its image); when its page (view_album) paints, this
 * fills a rounded rectangle with the same image on the vector canvas, the way the stock
 * widget_draw_arc_at_center paints with an image. vgcanvas_paint patterns the image at
 * (0,0,w,h) in the current transform, so: translate to the cover, scale to its box, fill. */
#define ART_RADIUS 12
static void round_art(void *view, void *canvas) {
    void *cover = widget_lookup(view, "img_cover", 1);
    const char *name = cover ? widget_get_prop_str(cover, "image", (void *)0) : (void *)0;
    if (!name || !*name) return;
    int bmp[0x60 / 4]; /* bitmap_t, filled by widget_load_image: w @0, h @4 (stock reserves 0x48) */
    if (widget_load_image(cover, name, bmp) || bmp[0] <= 0 || bmp[1] <= 0) return;
    void *vg = canvas_get_vgcanvas(canvas);
    if (!vg) return;
    float sx = (float)I(cover, 8) / (float)bmp[0], sy = (float)I(cover, 0x0c) / (float)bmp[1];
    vgcanvas_save(vg);
    vgcanvas_translate(vg, (float)(I(canvas, 0) + I(cover, 0)), (float)(I(canvas, 4) + I(cover, 4)));
    vgcanvas_scale(vg, sx, sy);
    vgcanvas_begin_path(vg);
    vgcanvas_rounded_rect(vg, 0.0f, 0.0f, (float)bmp[0], (float)bmp[1], (float)ART_RADIUS / sx);
    vgcanvas_paint(vg, 0, bmp);
    vgcanvas_restore(vg);
}

/* Home split screen: the theme's "view_homeart" pane shows the current cover (a track is loaded:
 * the status bar shows play or pause) drawn larger than the pane and panned, or else a wall of
 * the library's cached thumbnails (/mnt/mmc/.sldp, 52-80 px) at about their own size. Motion is a
 * continuous drift: each PAN_MS cycle eases from where the art is to a new random point, so a
 * cycle ends where the next begins; an idle wall fades out and a new random one fades in across
 * the boundary. Drawn on the vector canvas
 * clipped to the pane (as round_art); an ART_TICK_MS timer repaints the pane only while Home is
 * on screen. */
#define ART_TICK_MS 80
#define PAN_MS 9000
#define FADE_MS 700
#define WALL_N 24
#define WALL_COLS 4
#define TILE 60
#define SLDP "/mnt/mmc/.sldp"
struct {
    unsigned timer, start, rng;
    unsigned key, fresh_until, fresh_at; /* current track, and the cover re-read window after a change */
    int nwall;
    float x0, y0, x1, y1; /* drift from (x0,y0) to (x1,y1), as fractions of the overscan */
    char wall[WALL_N][24];
} home __attribute__((section(".scratch")));

static unsigned rnd(void) {
    if (!home.rng) home.rng = (unsigned)time_now_ms() | 1;
    home.rng = home.rng * 1103515245u + 12345u;
    return home.rng >> 16;
}

static int track_loaded(void) {
    void *wm = window_manager();
    for (unsigned i = 0, n = widget_count_children(wm); i < n; ++i) {
        void *c = widget_get_child(wm, i);
        if (c && eq(widget_get_type(c), "system_bar")) {
            void *s = widget_lookup(c, "img_state", 1);
            const char *img = s ? widget_get_prop_str(s, "image", (void *)0) : (void *)0;
            return s && widget_get_visible(s) && (eq(img, "bar_play") || eq(img, "bar_pause"));
        }
    }
    return 0;
}

/* Reservoir-sample WALL_N thumbnail names. fs_item_t: flags at 0..2 (dir, link, regular file),
 * name at 3 (0x103 bytes; see the readdir wrapper in os_fs). */
/* The previous wall's thumbnails leave the image cache when a new wall is picked (every cycle);
 * kept, an idle Home would slowly decode the whole cover library into memory. */
static void wall_release(void) {
    char path[64];
    for (int i = 0; i < home.nwall; ++i) {
        int k = 0;
        for (const char *p = "file://" SLDP "/"; *p; ++p) path[k++] = *p;
        for (const char *p = home.wall[i]; *p && k < 63; ++p) path[k++] = *p;
        path[k] = 0;
        image_manager_unload_bitmap_by_name(image_manager(), path);
    }
}

static void wall_scan(void) {
    void *dir = fs_open_dir(os_fs(), SLDP);
    char item[0x104];
    int seen = 0;
    home.nwall = 0;
    if (!dir) return;
    for (int guard = 0; guard < 4000 && !fs_dir_read(dir, item); ++guard) {
        const char *name = item + 3;
        int len = 0;
        while (name[len]) ++len;
        if (!item[2] || len < 5 || len > 22 || !eq(name + len - 4, ".jpg")) continue;
        ++seen; /* reservoir: the k-th name takes a random slot with probability WALL_N/k */
        int slot = home.nwall < WALL_N ? home.nwall++ : (int)(rnd() % (unsigned)seen);
        if (slot < WALL_N)
            for (int k = 0; k <= len; ++k) home.wall[slot][k] = name[k];
    }
    fs_dir_close(dir);
}

static float frand(void) {
    return (float)(int)(rnd() % 1001u) / 1000.0f;
}

/* Next leg of the drift starts where the last one ended and heads somewhere clearly different. */
static void new_cycle(unsigned now) {
    int first = !home.start;
    home.start = now;
    home.x0 = first ? frand() : home.x1;
    home.y0 = first ? frand() : home.y1;
    for (int tries = 0; tries < 8; ++tries) {
        home.x1 = frand();
        home.y1 = frand();
        float dx = home.x1 - home.x0, dy = home.y1 - home.y0;
        if ((dx < 0 ? -dx : dx) + (dy < 0 ? -dy : dy) >= 0.6f) break;
    }
    wall_release();
    home.nwall = 0; /* a fresh random wall next time it is needed (faded in) */
}

static float pan_pos(float extra, float from, float to, float e) {
    if (extra <= 0.0f) return extra / 2.0f; /* smaller than the pane: centred */
    return extra * (from + (to - from) * e);
}

/* Fill the part (x0,y0,w,h) of the pane with a bitmap drawn at (bx,by) scaled (sx,sy). */
static void blit(void *vg, int *bmp, float bx, float by, float sx, float sy, float x0, float y0,
                 float w, float h, float r) {
    vgcanvas_save(vg);
    vgcanvas_translate(vg, bx, by);
    vgcanvas_scale(vg, sx, sy);
    vgcanvas_begin_path(vg);
    vgcanvas_rounded_rect(vg, (x0 - bx) / sx, (y0 - by) / sy, w / sx, h / sy, r / sx);
    vgcanvas_paint(vg, 0, bmp);
    vgcanvas_restore(vg);
}

static int home_tick(const void *info) {
    (void)info;
    void *top = usable() ? window_manager_get_top_window(window_manager()) : (void *)0;
    void *pane = top && eq(widget_get_prop_str(top, "name", (void *)0), "home_page")
                     ? widget_lookup(top, "view_homeart", 1) : (void *)0;
    if (!pane) {
        home.timer = 0;
        return RET_REMOVE;
    }
    widget_invalidate_force(pane, (void *)0);
    return RET_REPEAT;
}

/* The app rewrites /tmp/coverpic.jpg when the track changes, but the image cache keeps the old
 * decode (Now Playing refreshes it; Home would not). On a new track (queue position, queue, size)
 * the cached cover is dropped and re-read every COVER_RETRY_MS for COVER_FRESH_MS, since the file
 * lands a moment after the skip. */
#define COVER "file:///tmp/coverpic.jpg"
#define COVER_FRESH_MS 3000
#define COVER_RETRY_MS 500
static void cover_fresh(void *pane, unsigned now) {
    void *q = mcl_pdeqplaylist;
    unsigned key = (unsigned)mclGetPlayPos() * 2654435761u ^ (unsigned)q ^ (unsigned)(q ? deque_size(q) : 0) << 24;
    if (key != home.key) {
        home.key = key;
        home.fresh_until = now + COVER_FRESH_MS;
        home.fresh_at = now - COVER_RETRY_MS;
    }
    if ((int)(home.fresh_until - now) <= 0 || now - home.fresh_at < COVER_RETRY_MS) return;
    home.fresh_at = now;
    int bmp[0x60 / 4];
    if (!widget_load_image(pane, COVER, bmp)) widget_unload_image(pane, bmp); /* next load re-reads */
}

static void homeart_draw(void *pane, void *canvas) {
    unsigned now = (unsigned)time_now_ms();
    if (!home.start || now - home.start >= PAN_MS) new_cycle(now);
    float f = (float)(int)(now - home.start) / (float)PAN_MS, e = f * f * (3.0f - 2.0f * f);
    float px = (float)I(canvas, 0), py = (float)I(canvas, 4);
    float pw = (float)I(pane, 8), ph = (float)I(pane, 0x0c);
    void *vg = canvas_get_vgcanvas(canvas);
    int bmp[0x60 / 4];
    if (!home.timer) home.timer = timer_add(home_tick, (void *)0, ART_TICK_MS);
    if (!vg) return;
    if (track_loaded()) cover_fresh(pane, now);
    if (track_loaded() && !widget_load_image(pane, COVER, bmp) && bmp[0] > 0 && bmp[1] > 0) {
        float s = pw / (float)bmp[0] > ph / (float)bmp[1] ? pw / (float)bmp[0] : ph / (float)bmp[1];
        s *= 1.25f;
        float ox = pan_pos((float)bmp[0] * s - pw, home.x0, home.x1, e);
        float oy = pan_pos((float)bmp[1] * s - ph, home.y0, home.y1, e);
        blit(vg, bmp, px - ox, py - oy, s, s, px, py, pw, ph, (float)ART_RADIUS);
        return;
    }
    if (!home.nwall) wall_scan();
    if (!home.nwall) return;
    int rows = (home.nwall + WALL_COLS - 1) / WALL_COLS;
    float ox = pan_pos((float)(WALL_COLS * TILE) - pw, home.x0, home.x1, e);
    float oy = pan_pos((float)(rows * TILE) - ph, home.y0, home.y1, e);
    unsigned t_in = now - home.start, t_out = PAN_MS - t_in;
    float alpha = (float)(int)(t_in < t_out ? t_in : t_out) / (float)FADE_MS;
    if (alpha > 1.0f) alpha = 1.0f;
    char path[64];
    for (int i = 0; i < home.nwall; ++i) {
        float tx = (float)((i % WALL_COLS) * TILE) - ox, ty = (float)((i / WALL_COLS) * TILE) - oy;
        float t = (float)(TILE - 2);
        float x0 = tx > 0.0f ? tx : 0.0f, y0 = ty > 0.0f ? ty : 0.0f;
        float x1 = tx + t < pw ? tx + t : pw, y1 = ty + t < ph ? ty + t : ph;
        if (x1 <= x0 || y1 <= y0) continue;
        int k = 0;
        for (const char *p = "file://" SLDP "/"; *p; ++p) path[k++] = *p;
        for (const char *p = home.wall[i]; *p && k < 63; ++p) path[k++] = *p;
        path[k] = 0;
        if (widget_load_image(pane, path, bmp) || bmp[0] <= 0 || bmp[1] <= 0) continue;
        int whole = x0 == tx && y0 == ty && x1 == tx + t && y1 == ty + t;
        vgcanvas_save(vg);
        vgcanvas_set_global_alpha(vg, alpha); /* the wall fades across a change of covers */
        blit(vg, bmp, px + tx, py + ty, t / (float)bmp[0], t / (float)bmp[1], px + x0, py + y0,
             x1 - x0, y1 - y0, whole ? 4.0f : 0.0f);
        vgcanvas_restore(vg);
    }
}

/* Tinted Now Playing: the theme's dimmed full-screen "img_artbg" shows the current cover
 * (file:// art only; a default cover leaves it empty). */
static void artbg_sync(void *top) {
    void *cover = widget_lookup(top, "img_cover", 1), *bg = widget_lookup(top, "img_artbg", 1);
    if (!cover || !bg) return;
    const char *art = widget_get_prop_str(cover, "image", (void *)0);
    if (!starts(art, "file://")) art = "";
    if (!eq(widget_get_prop_str(bg, "image", (void *)0), art)) widget_set_prop_str(bg, "image", art);
}

static int album_sync(void *top);

static int album_idle(const void *info) {
    (void)info;
    ipod.album = 0;
    return album_sync(window_manager_get_top_window(window_manager()));
}

/* Now Playing extras: "3 of 12" in the header, and the time left (-m:ss) in place of the length,
 * written to theme labels (the stock length label stays hidden and app-updated). */
static int wtime(const int *t) { /* "01:23" or "1:02:03" -> seconds; -1 if not a time */
    int v = 0, part = 0, any = 0;
    for (; t && *t; ++t) {
        if (*t >= '0' && *t <= '9')
            part = part * 10 + (*t - '0'), any = 1;
        else if (*t == ':')
            v = v * 60 + part, part = 0;
        else
            return -1;
    }
    return any ? v * 60 + part : -1;
}

static void wset(void *w, const char *s) { /* ASCII text, set only when it differs */
    int buf[32], i = 0;
    while (s[i] && i < 31) buf[i] = (unsigned char)s[i], ++i;
    buf[i] = 0;
    const int *cur = widget_get_text(w);
    for (i = 0; cur && cur[i] && cur[i] == buf[i]; ++i) {}
    if (!cur || cur[i] != buf[i]) widget_set_text(w, buf);
}


static void np_extras(void *top) {
    char s[32];
    /* Long title, artist and album lines scroll to the end and back (yoyo), not wrap round. */
    static const char *const scrollers[] = { "scrlabel_title", "scrlabel_artist", "label_album_ipod" };
    for (unsigned i = 0; i < sizeof(scrollers) / sizeof(*scrollers); ++i) {
        void *l = widget_lookup(top, scrollers[i], 1);
        if (l && !widget_get_prop_bool(l, "yoyo", 0)) widget_set_prop_int(l, "yoyo", 1);
    }
    void *count = widget_lookup(top, "label_npcount", 1);
    if (count) {
        void *q = mcl_pdeqplaylist;
        int n = q ? deque_size(q) : 0, pos = mclGetPlayPos();
        if (n > 0 && pos >= 0 && pos < n)
            tk_snprintf(s, sizeof(s), "%d of %d", pos + 1, n);
        else
            tk_snprintf(s, sizeof(s), "Now Playing");
        wset(count, s);
    }
    void *rem = widget_lookup(top, "label_remain_ipod", 1), *cur = widget_lookup(top, "label_playtime", 1),
         *len = widget_lookup(top, "label_playlen", 1);
    if (rem && cur && len) {
        int a = wtime(widget_get_text(cur)), b = wtime(widget_get_text(len)), r = b - (a < 0 ? 0 : a);
        if (r < 0) r = 0;
        if (b < 0)
            s[0] = 0;
        else if (b >= 3600)
            tk_snprintf(s, sizeof(s), "-%02d:%02d:%02d", r / 3600, r / 60 % 60, r % 60);
        else
            tk_snprintf(s, sizeof(s), "-%02d:%02d", r / 60, r % 60);
        wset(rem, s);
    }
}

static int album_sync(void *top) {
    if (top) artbg_sync(top);
    if (top) np_extras(top);
    void *src = top ? widget_lookup(top, "label_album", 1) : (void *)0;
    void *dst = top ? widget_lookup(top, "label_album_ipod", 1) : (void *)0;
    const int *t = src ? widget_get_text(src) : (void *)0, *d = dst ? widget_get_text(dst) : (void *)0;
    if (!t || !dst) return RET_REMOVE;
    int n = album_prefix(t), buf[128], i = 0;
    while (n && t[n] == ' ') ++n;
    while (t[n + i] && i < 127) buf[i] = t[n + i], ++i;
    buf[i] = 0;
    for (i = 0; d && buf[i] && d[i] == buf[i]; ++i) {}
    if (d && buf[i] == d[i]) return RET_REMOVE; /* unchanged: no set, no repaint */
    widget_set_text(dst, buf);
    return RET_REMOVE;
}


static int ipod_rows(menu_t *m, int cur);
static int np_rows(menu_t *m);

/* "Play All" bar above song lists (Songs, Album info): at the top of the list a detent up moves on
 * to it, except in the first HEAD_SETTLE_MS after a spin up reached the first song, so the spin's
 * overshoot stops there; turning on past that (or resting and turning again) goes to Play All. A
 * rest at the first song (HEAD_REST_MS) then a separate detent (HEAD_STEP_MS apart, within
 * HEAD_ARM_MS) also goes there sooner. While it is focused the list shows no pill, the bar gets a
 * pink ring, centre plays all, and a detent down (or a touch) returns to the first song. */
#define HEAD "_ipod_head"
#define HEAD_SETTLE_MS 500 /* logged: a deliberate push up at the top kept turning for over a second */
#define HEAD_REST_MS 200   /* logged: deliberate pauses ran ~260 ms; spin detents 68-126 ms */
#define HEAD_ARM_MS 1000
#define HEAD_STEP_MS 110 /* ...as a separate turn: a spin's detents come ~80 ms apart */
struct {
    unsigned last, armed, moved; /* moved: the last detent that moved the list's selection */
} hd __attribute__((section(".scratch")));

static void *head_bar(void *w) {
    void *win = w;
    while (win && !eq(widget_get_type(win), "window")) win = P(win, 0x48);
    void *bar = win ? widget_lookup(win, "view_navbar_allplay", 1) : (void *)0;
    return bar && widget_get_visible(bar) ? bar : (void *)0;
}

static void *head_target(void *w) {
    void *bar = head_bar(w);
    return bar ? first_entry(bar) : (void *)0;
}

/* A wheel detent on a list: 1 if it moved onto, stayed on or left the bar (consumed). */
static int head_key(menu_t *m, int dir) {
    unsigned now = (unsigned)time_now_ms(), gap = now - hd.last;
    hd.last = now;
    if (widget_get_prop_int(m->w, HEAD, 0)) {
        if (dir > 0) widget_set_prop_int(m->w, HEAD, 0); /* back down to the first song */
        return 1;
    }
    int id = widget_get_prop_int(m->w, SEL, -1);
    void *target = dir < 0 && id <= 0 ? head_target(m->w) : (void *)0;
    if (dir > 0 || id > 0 || m->top > 0 || !target) {
        hd.armed = 0;
        hd.moved = now;
        return 0;
    }
    if (now - hd.moved >= HEAD_SETTLE_MS || (hd.armed && now - hd.armed <= HEAD_ARM_MS && gap >= HEAD_STEP_MS)) {
        hd.armed = 0;
        widget_set_prop_int(m->w, HEAD, 1);
        return 1;
    }
    hd.armed = gap >= HEAD_REST_MS ? now : 0; /* resting at the top arms it; a spin does not */
    return 1;                                  /* nothing above the first song otherwise */
}

/* Play All's look: the theme's hidden pink pill (ipod_allsel) behind it and a white icon while the
 * wheel is on it, like a selected row. The app sizes the icon and label 50 px tall in the 40 px bar,
 * which drew them low; they are fitted to the bar. */
#define HEAD_PILL "ipod_allsel"
#define HEAD_ICON_STYLE "ipod_allplayfocus"
#define HEAD_ORDER "s_img_order_navbar"
#define HEAD_ORDER_STYLE "ipod_orderfocus" /* the sort icon, white on the pill */
static int head_style(void *bar, void *target, int on) {
    int changed = 0, h = I(bar, 0x0c);
    for (unsigned i = 0, n = widget_count_children(bar); i < n; ++i) {
        void *c = widget_get_child(bar, i);
        if (!c) continue;
        int ch = I(c, 0x0c);
        if (eq(widget_get_type(c), "image")) {
            /* 50 px PNGs with the glyph in the middle, drawn from the top-left: centre the box on the
             * bar (its transparent top overhangs) so the glyph lines up with the text. */
            if (ch > h) changed |= place(c, I(c, 0), (h - ch) / 2, I(c, 8), ch);
            const char *st = widget_get_prop_str(c, "style", (void *)0);
            if (c != target && (eq(st, HEAD_ORDER) || eq(st, HEAD_ORDER_STYLE)))
                changed |= restyle(c, on, HEAD_ORDER_STYLE);
        } else if (ch > h)
            changed |= place(c, I(c, 0), 0, I(c, 8), h);
    }
    void *pill = widget_lookup(P(bar, 0x48), HEAD_PILL, 0); /* the bar's sibling, drawn behind it */
    if (pill && widget_get_visible(pill) != on) {
        widget_set_prop_int(pill, "visible", on);
        changed = 1;
    }
    if (target) changed |= restyle(target, on, HEAD_ICON_STYLE);
    return changed;
}

static void cover_request(menu_t *m);

#define STYLED "_ipod_styled"
static int ipod_apply_on(void *w, menu_t *m) {
    if (!w || !load(m, w) || m->kind == 3) return -1;
    if (!widget_get_prop_int(w, STYLED, 0)) widget_set_prop_int(w, STYLED, 1);
    int cur = reconcile(m, !moving(m) && !window_manager_get_pointer_pressed(window_manager()));
    int head = widget_get_prop_int(w, HEAD, 0);
    if (ipod_rows(m, head ? -1 : cur) | np_rows(m)) widget_invalidate_force(w, (void *)0);
    void *bar = head_bar(w);
    if (bar && head_style(bar, first_entry(bar), head)) widget_invalidate_force(bar, (void *)0);
    cover_request(m);
    return cur;
}

static void accent_row(void *win);

static void ipod_apply(void) {
    accent_row(window_manager_get_top_window(window_manager()));
    menu_t m;
    int cur = ipod_apply_on(surface(), &m);
#ifdef RINGNAV_ACCEL
    if (cur >= 0) letter_update(&m, cur);
#else
    (void)cur;
#endif
}

/* Pop-ups (confirmations, the scan and auto-shutdown prompts): the wheel moves a focus between
 * their buttons, left to right, starting on the left one (Cancel); the centre button clicks it
 * (held for the double-press window like a list click). Buttons take the pink pill; the confirm
 * pills switch to ringed images. Dialogs with a list (sort order) are lists instead. */
#define DIALOG_MAX 6
#define DSEL "_ipod_dsel"

static int dialog_targets(void *w, void **out, int n, int depth) {
    unsigned c = widget_count_children(w);
    for (unsigned i = 0; i < c && n < DIALOG_MAX && depth < 3; ++i) {
        void *k = widget_get_child(w, i);
        if (!k || !widget_get_visible(k)) continue;
        const char *t = widget_get_type(k), *name = widget_get_prop_str(k, "name", (void *)0);
        if ((eq(t, "button") || ((eq(name, "img_enter") || eq(name, "img_cancel")) && clickable(k))) &&
            widget_get_prop_bool(k, "enable", 1)) {
            int j = n++; /* insertion sort, left to right then top to bottom */
            while (j > 0 && (I(out[j - 1], 4) > I(k, 4) + 8 ||
                             (I(out[j - 1], 4) + 8 >= I(k, 4) && I(out[j - 1], 0) > I(k, 0)))) {
                out[j] = out[j - 1];
                --j;
            }
            out[j] = k;
        } else if (!eq(t, "list_view") && !eq(t, "table_view"))
            n = dialog_targets(k, out, n, depth + 1);
    }
    return n;
}

static void *dialog_of(void *top) {
    if (!top || !eq(widget_get_type(top), "dialog") || allowed(widget_get_prop_str(top, "name", (void *)0)))
        return (void *)0;
    return top;
}

static const char *focus_style(void *k) {
    const char *name = widget_get_prop_str(k, "name", (void *)0);
    return eq(name, "img_enter") ? "ipod_okfocus" : eq(name, "img_cancel") ? "ipod_cancelfocus" : IPOD_SEL;
}

/* Restyle the focused target; returns the target count. */
static int dialog_apply(void *d, void **out) {
    int n = dialog_targets(d, out, 0, 0), sel = widget_get_prop_int(d, DSEL, 0), changed = 0;
    if (sel >= n) sel = n - 1;
    for (int i = 0; i < n; ++i) changed |= restyle(out[i], i == sel, focus_style(out[i]));
    if (changed) widget_invalidate_force(d, (void *)0);
    return n;
}

static int dialog_idle(const void *info) {
    (void)info;
    ipod.dialog = 0;
    void *out[DIALOG_MAX], *d = dialog_usable() ? dialog_of(window_manager_get_top_window(window_manager())) : (void *)0;
    if (d) dialog_apply(d, out);
    return RET_REMOVE;
}

/* Lyrics: the app scrolls to (current line - 4) x the list's default item height (60), sized for
 * its old narrow column where lines wrapped. Full width, most lines are one 20 px row, so that
 * overshot ~3x and raced to the end. Its scroll requests for scroll_lrc are replaced by the real
 * position of the current line (the last whose lrc_time has passed), centred, with a short glide.
 * Lyrics without timings stay where the user put them. */
#define LRC_GLIDE_MS 300
#define LRC_HOLD_MS 4000 /* after a touch, timed lyrics stop following so they can be dragged */
struct {
    unsigned touch_at;
} lrc __attribute__((section(".scratch")));

static int lyric_y(void *sv, int y) {
    unsigned n = widget_count_children(sv);
    int t = player_playtime(), cur = -1, timed = 0;
    for (unsigned i = 0; i < n; ++i) {
        void *c = widget_get_child(sv, i);
        int at = c ? widget_get_prop_int(c, "lrc_time", -1) : -1;
        if (at > 0) timed = 1;
        if (c && at >= 0 && at <= t) cur = (int)i;
    }
    if (!timed) return I(sv, 0x84); /* untimed: leave the user's scroll alone */
    if (cur < 0) return 0;
    void *c = widget_get_child(sv, (unsigned)cur);
    int view = I(sv, 0x0c), max = I(sv, 0x7c) - view;
    y = I(c, 4) + I(c, 0x0c) / 2 - view / 2;
    return y < 0 ? 0 : max < 0 ? 0 : y > max ? max : y;
}

int ringnav_scrollto(void *w, int x, int y, int ms) {
    if (w && eq(widget_get_prop_str(w, "name", (void *)0), "scroll_lrc")) {
        if ((unsigned)time_now_ms() - lrc.touch_at < LRC_HOLD_MS) return 0; /* the user is reading */
        int want = lyric_y(w, y);
        if (want == I(w, 0x84)) return 0;
        return stock_scrollto(w, x, want, LRC_GLIDE_MS);
    }
    return stock_scrollto(w, x, y, ms);
}

/* Pages that rebuild their rows in code (Bluetooth while pairing: destroy and recreate on a
 * status timer) showed each new set of rows in stock layout for a frame before the paint-time
 * pass restyled them: a flicker. The toolkit lays a list out before painting it, so right after
 * the stock layout of the page's list, the rows are restyled: no stock frame reaches the screen. */
struct {
    int busy;
} lay __attribute__((section(".scratch")));

int ringnav_layout(void *w) {
    int r = stock_layout(w);
    int k = w && !lay.busy ? kind(w) : 0;
    if (k == 1 || k == 2) {
        void *top = usable() ? window_manager_get_top_window(window_manager()) : (void *)0;
        menu_t m;
        /* Only lists the paint-time pass has styled: while a page is still being built the app has
         * not attached its tap handlers, and those targets would look like plain images. */
        if (top && widget_get_prop_int(w, STYLED, 0) && surface_of(top) == w && load(&m, w)) {
            /* Rows only, with the selection as it stands: selection repair, the now-playing marker
             * and cover requests stay with the paint-time pass. */
            int cur = widget_get_prop_int(w, HEAD, 0) ? -1 : index_of(&m, widget_get_prop_int(w, SEL, -1));
            lay.busy = 1; /* our own moves lay children out again */
            ipod_rows(&m, cur);
            lay.busy = 0;
        }
    }
    return r;
}

/* DVC-style Bluetooth volume. Stock keeps two volumes: the player's digital gain on the Bluetooth
 * stream (mclSetBtVol, 0-100, set by the wheel) and the headset's own volume (AVRCP absolute
 * volume, 0-127, only from the Bluetooth settings page). When the headset takes absolute volume
 * (the same checks as that page: Bluetooth on, linked, a codec streaming, not receiver mode, a
 * valid reading), the stream stays at full scale and the requested level goes to the headset, so
 * the wheel drives the headset's amplifier (AirPods and the like) at full resolution. */
#define DVC_FULL 100
/* The headset's last absolute volume (0-127) as the Q2 set or saw it (known: read on this link);
 * and whether the Q2 is following a headset change (then the hook must not send it back). */
struct {
    int last_abs, known, syncing;
} hsv __attribute__((section(".scratch")));

int ringnav_btvol(int left, int right) {
    if (g_bluetoothflag && bt_linkstatus && bt_showcoding > 0 && !bt__recv_pageflag) {
        unsigned cur = (unsigned)btctl_transport_get_volume();
        if (cur < 0x80) {
            int v = left > right ? left : right;
            v = v < 0 ? 0 : v > 100 ? 100 : v;
            int want = (v * 127 + 50) / 100;
            if ((int)cur != want && !hsv.syncing) {
                btctl_transport_set_volume(want);
                hsv.last_abs = want;
            }
            return stock_btvol(DVC_FULL, DVC_FULL);
        }
    }
    return stock_btvol(left, right);
}

/* Headset connect card, like an iPhone's: when a Bluetooth headset links, a rounded card rises with
 * its picture (AirPods, or generic headphones), its name and "Connected"; it closes after
 * BTCARD_MS, on a tap, or on any key (which it takes). The link is polled once a second from a
 * timer started by the first paint. Name: the current link's MAC (getBtLinkItem) looked up in the
 * paired list (records: MAC at +4, name at +0x24). Art is theme images at retired Tidal paths. */
#define BTCARD "ipod_btcard"
#define BTCARD_SUB "ipod_btcard_sub"
#define BTCARD_MS 5000 /* long enough for the first battery report (~2 s after linking) */
#define BTCARD_TICK_MS 300
struct {
    volatile int running, reports;
    volatile int level[3], status[3]; /* left, right, case; status 0 unknown, 1 charging, 2 in use, 4 absent */
    volatile int ear[2], ear_reports; /* each bud: 0 in ear, 1 out, 2 in the case */
} aap __attribute__((section(".scratch")));
struct {
    unsigned shown;
    int reports;
} cardst __attribute__((section(".scratch")));
#define BTPOLL_MS 400 /* also how soon a removed AirPod pauses */
#define CARD_ART 130
/* A bottom sheet, like an iPhone's AirPods card: full width on the bottom edge, its corners the
 * screen's own radius, so the bottom ones vanish into the display's curve and the top ones mirror
 * them (a card inset from the edges looked out of place against the rounded screen). */
#define CARD_W 375
#define CARD_H 224
#define SCREEN_RADIUS "40" /* the Q2 display's corner radius, measured from a photo */
#define CARD_AIRPODS "tidal_shangling_big" /* theme: AirPods Pro 2 in the open case */
struct {
    unsigned timer;
    int was;
} btc __attribute__((section(".scratch")));

static int contains(const char *s, const char *sub) {
    for (; s && *s; ++s) {
        int i = 0;
        while (sub[i] && s[i] == sub[i]) ++i;
        if (!sub[i]) return 1;
    }
    return 0;
}

static void bt_name(char *out, int cap) {
    out[0] = 0;
    int n = getBtLinkSize(), st = 0;
    char mac[64];
    mac[0] = 0;
    if (n > 0) getBtLinkItem(n - 1, &st, mac);
    void *pairs = pdeq_btpairlist;
    for (int i = 0, m = pairs && mac[0] ? deque_size(pairs) : 0; i < m && i < 64; ++i) {
        const char *it = (const char *)deque_at(pairs, i);
        if (it && eq(it + 4, mac)) {
            int k = 0;
            for (const char *p = it + 0x24; *p && k < cap - 1; ++p) out[k++] = *p;
            out[k] = 0;
            return;
        }
    }
}

static void *btcard_find(void) {
    return widget_lookup(window_manager(), BTCARD, 0);
}

/* "L 100%⚡ · R 97% · Case 90%": the parts the AirPods report present, ⚡ when charging. */
static void battery_text(char *out, int cap) {
    static const char *const part[3] = { "L", "R", "Case" };
    int k = 0;
    out[0] = 0;
    for (int i = 0; i < 3; ++i) {
        if (aap.status[i] != 1 && aap.status[i] != 2) continue;
        k += tk_snprintf(out + k, cap - k, "%s%s %d%%%s", k ? "  \xc2\xb7  " : "", part[i], aap.level[i],
                         aap.status[i] == 1 ? "\xe2\x9a\xa1" : "");
    }
}

/* The card's own tick: shows battery once reported, and closes it after BTCARD_MS. */
static int btcard_tick_card(const void *info) {
    (void)info;
    void *card = btcard_find();
    if (!card) return RET_REMOVE;
    if ((unsigned)time_now_ms() - cardst.shown >= BTCARD_MS) {
        window_close(card);
        return RET_REMOVE;
    }
    if (aap.reports != cardst.reports) {
        char text[64];
        battery_text(text, sizeof(text));
        void *sub = widget_lookup(card, BTCARD_SUB, 1);
        if (text[0] && sub) widget_set_text_utf8(sub, text);
        cardst.reports = aap.reports;
    }
    return RET_REPEAT;
}

static void *card_label(void *parent, int y, int h, const char *size, const char *color, const char *text) {
    void *l = label_create(parent, 0, y, CARD_W, h);
    widget_set_prop_str(l, "style:normal:font_size", size);
    widget_set_prop_str(l, "style:normal:text_color", color);
    widget_set_text_utf8(l, text);
    return l;
}

#ifdef RINGNAV_DUMP
/* Debug: the Bluetooth state the card watches, logged when it changes, to /mnt/mmc/q2bt.txt. */
#define BTLOG_N 24
struct {
    int last, n;
    char line[BTLOG_N][64];
} btlog __attribute__((section(".scratch")));

static void bt_log(const char *what) {
    tk_snprintf(btlog.line[btlog.n++ % BTLOG_N], 64, "%u %s flag=%d link=%d conn=%d recv=%d code=%d",
                (unsigned)time_now_ms() / 100 % 100000, what, g_bluetoothflag, bt_linkstatus, bt_connectstatus,
                bt__recv_pageflag, bt_showcoding);
    char buf[BTLOG_N * 66];
    int k = 0;
    for (int i = 0; i < BTLOG_N && i < btlog.n; ++i) {
        const char *l = btlog.line[(btlog.n - (btlog.n < BTLOG_N ? btlog.n : BTLOG_N) + i) % BTLOG_N];
        while (*l) buf[k++] = *l++;
        buf[k++] = '\n';
    }
    file_write("/mnt/mmc/q2bt.txt", buf, (unsigned)k);
}
#endif

static void btcard_show(void) {
    char name[96];
    bt_name(name, sizeof(name));
    if (btcard_find()) return;
    void *card = popup_create((void *)0, 0, 320 - CARD_H, CARD_W, CARD_H);
#ifdef RINGNAV_DUMP
    char what[40];
    tk_snprintf(what, sizeof(what), "show %s card=%x", name[0] ? name : "-", (unsigned)card);
    bt_log(what);
#endif
    if (!card) return;
    widget_set_prop_str(card, "name", BTCARD);
    widget_set_prop_str(card, "style:normal:bg_color", "#2c2c2eff");
    widget_set_prop_str(card, "style:normal:border_color", "#00000000");
    widget_set_prop_str(card, "style:normal:round_radius", SCREEN_RADIUS);
    widget_set_prop_str(card, "close_when_click", "true");
    widget_set_prop_str(card, "close_when_click_outside", "true");
    widget_set_prop_str(card, "anim_hint", "popup(duration=250)");
    void *art = image_create(card, (CARD_W - CARD_ART) / 2, 20, CARD_ART, CARD_ART);
    image_base_set_image(art, contains(name, "AirPods") ? CARD_AIRPODS : "tidal_shanling");
    widget_set_prop_str(art, "draw_type", "center");
    card_label(card, 158, 28, "20", "#ffffffff", name[0] ? name : "Headphones");
    widget_set_prop_str(card_label(card, 186, 22, "15", "#8e8e93ff", "Connected"), "name", BTCARD_SUB);
    cardst.shown = (unsigned)time_now_ms();
    cardst.reports = -1;
    timer_add(btcard_tick_card, (void *)0, BTCARD_TICK_MS);
}


/* AirPods battery over Apple's accessory protocol (AACP; packets as in LibrePods): an L2CAP
 * seqpacket connection to the AirPods on PSM 0x1001, a handshake, feature flags and a notification
 * request; the AirPods then report battery as 04 00 04 00 04 00 <n> then n x <part 02 right,
 * 04 left, 08 case> 01 <level> <status 1 charging, 2 in use, 4 absent> 01, and ear detection as
 * 04 00 04 00 06 00 <bud> <bud> (0 in ear, 1 out, 2 in the case). Runs on its own thread (connect
 * blocks) for a headset named AirPods, reading until the link drops; the UI thread acts on what
 * it records. (Link drops once blamed on holding this channel were the 44.1 kHz AAC bug, fixed by
 * build.py --aac48.) Debug builds log to /mnt/mmc/q2aap.txt. */
#define AAP_PSM 0x1001

#ifdef RINGNAV_DUMP
#define AAPLOG_N 24
struct {
    volatile int n, flushed;
    unsigned seen[8];
    char line[AAPLOG_N][60];
} aaplog __attribute__((section(".scratch")));

/* Called on the battery thread: only records the line (file writes stay on the UI thread). */
static void aap_log(const char *text) {
    char *l = aaplog.line[aaplog.n % AAPLOG_N];
    int k = 0;
    while (text[k] && k < 59) l[k] = text[k], ++k;
    l[k] = 0;
    ++aaplog.n;
}

/* UI thread (the Bluetooth poll): writes the recorded lines when there are new ones. */
static void aap_flush(void) {
    if (aaplog.flushed == aaplog.n) return;
    aaplog.flushed = aaplog.n;
    char buf[AAPLOG_N * 62];
    int m = 0;
    for (int i = 0; i < AAPLOG_N && i < aaplog.n; ++i) {
        const char *s = aaplog.line[(aaplog.n - (aaplog.n < AAPLOG_N ? aaplog.n : AAPLOG_N) + i) % AAPLOG_N];
        while (*s) buf[m++] = *s++;
        buf[m++] = '\n';
    }
    file_write("/mnt/mmc/q2aap.txt", buf, (unsigned)m);
}
#define AAP_LOG(...)                                                                                      \
    do {                                                                                                   \
        char t_[60];                                                                                       \
        tk_snprintf(t_, sizeof(t_), __VA_ARGS__);                                                          \
        aap_log(t_);                                                                                       \
    } while (0)
#else
#define AAP_LOG(...) ((void)0)
#endif

static int hexv(char c) {
    return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}

/* "AA:BB:CC:DD:EE:FF" -> bdaddr_t (little-endian, last byte first). */
static int mac_parse(const char *s, unsigned char *b) {
    for (int i = 0; i < 6; ++i) {
        int hi = hexv(s[0]), lo = hexv(s[1]);
        if (hi < 0 || lo < 0 || (i < 5 && s[2] != ':')) return 0;
        b[5 - i] = (unsigned char)(hi * 16 + lo);
        s += 3;
    }
    return 1;
}

/* One report: 1 battery, 2 ear detection, 0 anything else. */
int ringnav_aap_parse(const unsigned char *p, int n) {
    if (n == 8 && p[0] == 4 && !p[1] && p[2] == 4 && !p[3] && p[4] == 6 && !p[5]) {
        aap.ear[0] = p[6];
        aap.ear[1] = p[7];
        ++aap.ear_reports;
        return 2;
    }
    if (n < 7 || p[0] != 4 || p[1] || p[2] != 4 || p[3] || p[4] != 4 || n != 7 + 5 * p[6]) return 0;
    for (int i = 0; i < p[6]; ++i) {
        const unsigned char *c = p + 7 + 5 * i;
        int slot = c[0] == 0x04 ? 0 : c[0] == 0x02 ? 1 : c[0] == 0x08 ? 2 : -1;
        if (slot < 0 || c[1] != 1 || c[4] != 1) continue;
        aap.level[slot] = c[2];
        aap.status[slot] = c[3];
    }
    ++aap.reports;
    return 1;
}

static const unsigned char AAP_HELLO[16] = { 0x00, 0x00, 0x04, 0x00, 0x01, 0x00, 0x02, 0x00 };
/* LibrePods' feature flags: without them the AirPods send no ear-detection reports (V1.7d, logged;
 * V9.3d, which sent them, got 04 00 04 00 06 00 ...). Dropped in V9.4d as a suspect in the link
 * drops, which were the 44.1 kHz AAC bug. */
static const unsigned char AAP_FLAGS[14] = { 0x04, 0x00, 0x04, 0x00, 0x4d, 0x00, 0xd7 };
static const unsigned char AAP_NOTIFY[10] = { 0x04, 0x00, 0x04, 0x00, 0x0f, 0x00, 0xff, 0xff, 0xff, 0xff };

void *ringnav_aap_thread(void *arg) {
    (void)arg;
    /* A new thread starts with libc's $gp; the demo's PLT stubs (socket, send...) need its own. */
    __asm__ volatile("lui $gp, 0xa2\n\tori $gp, $gp, 0x6cc0");
    usleep(500000); /* let the link settle; sooner is better: the first ear report stops an autoplay in the case */
    int n = getBtLinkSize(), st = 0;
    char mac[64];
    mac[0] = 0;
    if (n > 0) getBtLinkItem(n - 1, &st, mac);
    unsigned char sa[14] = { 31, 0, AAP_PSM & 0xff, AAP_PSM >> 8 }; /* sockaddr_l2: AF_BLUETOOTH, PSM */
    if (!mac_parse(mac, sa + 4)) {
        AAP_LOG("no mac '%s'", mac);
        aap.running = 0;
        return (void *)0;
    }
    int fd = socket(31, 5, 0); /* AF_BLUETOOTH, SOCK_SEQPACKET, BTPROTO_L2CAP */
    int r = fd < 0 ? -1 : connect(fd, sa, sizeof(sa));
    AAP_LOG("%s fd=%d connect=%d errno=%d", mac, fd, r, r < 0 ? *__errno_location() : 0);
    if (r == 0) {
        /* Battery needs only these two; LibrePods' feature-flags packet (0x4D) enables extras that
         * expect an Apple host and may unsettle the link, so it is not sent. */
        int a = send(fd, AAP_HELLO, sizeof(AAP_HELLO), 0), b = send(fd, AAP_FLAGS, sizeof(AAP_FLAGS), 0),
            c = send(fd, AAP_NOTIFY, sizeof(AAP_NOTIFY), 0);
        AAP_LOG("sent %d %d %d", a, b, c);
        (void)a, (void)b, (void)c; /* logged only in debug builds */
        unsigned char buf[256];
        while (bt_linkstatus) {
            volatile unsigned long set[32]; /* fd_set; volatile: no memset call to link */
            for (int i = 0; i < 32; ++i) set[i] = 0;
            long tv[2] = { 1, 0 };
            set[fd / 32] |= 1ul << (fd % 32);
            if (select(fd + 1, (void *)set, (void *)0, (void *)0, tv) <= 0) continue;
            int got = recv(fd, buf, sizeof(buf), 0);
            if (got <= 0) {
                AAP_LOG("recv %d errno=%d", got, got < 0 ? *__errno_location() : 0);
                break;
            }
            int kind = ringnav_aap_parse(buf, got);
            if (kind == 1)
                AAP_LOG("battery L%d/%d R%d/%d C%d/%d", aap.level[0], aap.status[0], aap.level[1], aap.status[1],
                        aap.level[2], aap.status[2]);
            else if (kind == 2)
                AAP_LOG("ear %d %d", aap.ear[0], aap.ear[1]);
#ifdef RINGNAV_DUMP
            else if (!(aaplog.seen[buf[4] >> 5] & 1u << (buf[4] & 31))) { /* each other opcode once: the
                listening-mode and head-tracking reports flooded the ring and hid the ear reports */
                aaplog.seen[buf[4] >> 5] |= 1u << (buf[4] & 31);
                char hex[60];
                int k = 0;
                for (int i = 0; i < got && k < 56; ++i) {
                    static const char d[] = "0123456789abcdef";
                    hex[k++] = d[buf[i] >> 4];
                    hex[k++] = d[buf[i] & 15];
                }
                hex[k] = 0;
                AAP_LOG("%d:%s", got, hex);
            }
#endif
        }
    }
    if (fd >= 0) close(fd);
    AAP_LOG("closed");
    aap.running = 0;
    return (void *)0;
}

static void aap_start(void) {
    if (aap.running) return;
    aap.running = 1;
#ifdef RINGNAV_DUMP
    for (int i = 0; i < 8; ++i) aaplog.seen[i] = 0;
#endif
    aap.reports = 0;
    for (int i = 0; i < 3; ++i) aap.status[i] = 0;
    unsigned long tid = 0;
    if (pthread_create(&tid, (void *)0, ringnav_aap_thread, (void *)0) == 0)
        pthread_detach(tid);
    else
        aap.running = 0;
}

/* Ear detection: taking an AirPod out while playing pauses; once every bud that was in is back, it
 * resumes (also after both came out, unlike an iPhone), and nothing plays while no bud is in
 * an ear. The AirPods pause by themselves
 * (an AVRCP pause, see avrcp_idle) and resume after one bud, but not after both; their pause often
 * lands before their ear report, so a pause they sent in the last EAR_AVRCP_MS counts as "was
 * playing". Acts on the reports the battery thread records, through the stock play/pause toggle
 * (player_play_pause: status 2 playing, 3 paused); a play or pause by hand in between wins. */
#define EAR_AVRCP_MS 3000
struct {
    int seen, known, in, paused, want;
    unsigned avrcp_pause; /* when the headset last paused playback (avrcp_idle) */
} earst __attribute__((section(".scratch")));

static void ear_tick(int on) {
    if (!on) {
        earst.known = earst.paused = 0;
        earst.seen = aap.ear_reports;
        return;
    }
    if (aap.ear_reports != earst.seen) {
        earst.seen = aap.ear_reports;
        int in = (aap.ear[0] == 0) + (aap.ear[1] == 0), was = earst.in;
        earst.in = in;
        if (!earst.known) { /* the first report is just where things stand */
            earst.known = 1;
        } else {
            int status = mclGetPlayStatus();
            if (earst.paused && status != 3) earst.paused = 0; /* played or stopped by hand meanwhile */
            int was_playing = status == 2 || (unsigned)time_now_ms() - earst.avrcp_pause < EAR_AVRCP_MS;
            if (in < was && was_playing) {
                if (status == 2) player_play_pause();
                if (!earst.paused) earst.want = was; /* resume when these are all back */
                earst.paused = 1;
            } else if (earst.paused && in >= earst.want) {
                player_play_pause();
                earst.paused = 0;
            }
            AAP_LOG("ears %d -> %d, status %d, paused %d", was, in, status, earst.paused);
        }
    }
    /* A headset with no bud in an ear (in the case, or out) doesn't play. The stock restarts
     * playback when the output switches to it (player_reconfig replays a saved "playing" status),
     * which reached AirPods still in their case (V2.0d, logged: ear 2 2 with status 2). It stays
     * paused until played: putting them in doesn't start it, as with an iPhone. */
    if (earst.known && !earst.in && mclGetPlayStatus() == 2) {
        player_play_pause();
        earst.paused = 0;
        AAP_LOG("no bud in an ear: paused");
    }
}

/* Headset buttons (AirPods: press = play/pause, double = next, triple = previous). BlueZ turns
 * AVRCP pass-through commands into key presses on a uinput device named "<headset> (AVRCP)",
 * which the app never reads (it opens event1-3). Per link, a thread finds it (EVIOCGNAME) and
 * reads its presses into a ring; idle_queue has the UI thread act on them with the stock player
 * calls (play/pause only when that changes something, so a second path can't undo it). */
#define EVIOCGNAME64 0x40404506u /* _IOC(_IOC_READ, 'E', 0x06, 64), MIPS encoding */
#define KEY_PAUSE 119
#define KEY_NEXTSONG 163
#define KEY_PLAYPAUSE 164
#define KEY_PREVIOUSSONG 165
#define KEY_STOPCD 166
#define KEY_PLAYCD 200
#define KEY_PAUSECD 201
#define KEY_PLAY 207
#define AVRCP_RING 8
struct {
    volatile int running, head, tail;
    volatile int code[AVRCP_RING];
} avrcp __attribute__((section(".scratch")));

static int avrcp_idle(const void *info) {
    (void)info;
    while (avrcp.tail != avrcp.head) {
        int code = avrcp.code[avrcp.tail % AVRCP_RING], status = mclGetPlayStatus(); /* 2 playing, 3 paused */
        avrcp.tail = avrcp.tail + 1;
        if (code == KEY_NEXTSONG)
            player_next_music();
        else if (code == KEY_PREVIOUSSONG)
            player_prev_music();
        else if (code == KEY_PLAYPAUSE || ((code == KEY_PLAYCD || code == KEY_PLAY) && status != 2) ||
                 ((code == KEY_PAUSECD || code == KEY_PAUSE || code == KEY_STOPCD) && status == 2)) {
            if (status == 2) earst.avrcp_pause = (unsigned)time_now_ms(); /* maybe a bud out: ear_tick */
            player_play_pause();
        }
#ifdef RINGNAV_DUMP
        char what[24];
        tk_snprintf(what, sizeof(what), "key %d st=%d", code, status);
        bt_log(what);
#endif
    }
    return RET_REMOVE;
}

static int avrcp_open(void) {
    static const char base[] = "/dev/input/event";
    char path[20], name[64];
    for (int k = 0; k < 16; ++k) path[k] = base[k]; /* no initialiser: clang would call memcpy */
    path[17] = 0;
    for (int i = 0; i < 10; ++i) {
        path[16] = (char)('0' + i);
        int fd = open(path, 0); /* O_RDONLY */
        if (fd < 0) continue;
        for (int k = 0; k < 64; ++k) name[k] = 0;
        if (ioctl(fd, EVIOCGNAME64, name) > 0 && contains(name, "(AVRCP)")) return fd;
        close(fd);
    }
    return -1;
}

void *ringnav_avrcp_thread(void *arg) {
    (void)arg;
    __asm__ volatile("lui $gp, 0xa2\n\tori $gp, $gp, 0x6cc0"); /* libc PLT stubs need the demo's $gp */
    int fd = -1;
    for (int tries = 0; tries < 20 && bt_linkstatus && fd < 0; ++tries) /* it appears with AVRCP */
        if ((fd = avrcp_open()) < 0) usleep(500000);
    if (fd >= 0) {
        struct {
            unsigned sec, usec;
            unsigned short type, code;
            int value;
        } ev[8];
        while (bt_linkstatus) {
            int got = read(fd, ev, sizeof(ev));
            if (got <= 0) break; /* the device goes when the headset does */
            int queued = 0;
            for (int i = 0; i < got / (int)sizeof(ev[0]); ++i)
                if (ev[i].type == 1 && ev[i].value == 1 && avrcp.head - avrcp.tail < AVRCP_RING) { /* EV_KEY press */
                    avrcp.code[avrcp.head % AVRCP_RING] = ev[i].code;
                    avrcp.head = avrcp.head + 1;
                    queued = 1;
                }
            if (queued) idle_queue(avrcp_idle, (void *)0);
        }
        close(fd);
    }
    avrcp.running = 0;
    return (void *)0;
}

static void avrcp_start(void) {
    if (avrcp.running) return;
    avrcp.running = 1;
    unsigned long tid = 0;
    if (pthread_create(&tid, (void *)0, ringnav_avrcp_thread, (void *)0) == 0)
        pthread_detach(tid);
    else
        avrcp.running = 0;
}

/* Headset volume (AirPods stem swipes): the headset changes its own absolute volume and reports it
 * (logged in V1.7d: 100, 76, 100, 124...). The Q2 follows: a change it did not make sets the app's
 * volume level (the static byte responseSetVolume, the stock remote volume, stores) via
 * device_set_volume, and with the screen on the volume HUD shows it (or its slider moves). */
#define g_vol_level (*(volatile signed char *)0xa38c41u)
#define VOLUME_DIALOG "volume_dialog"

static void hs_volume_tick(int on) {
    if (!on || bt_showcoding <= 0) {
        hsv.known = 0;
        return;
    }
    int cur = btctl_transport_get_volume();
    if (cur < 0 || cur > 127 || (hsv.known && cur == hsv.last_abs)) return;
    int first = !hsv.known;
    hsv.known = 1;
    hsv.last_abs = cur;
    int v = (cur * 100 + 63) / 127;
    if (first || v == g_vol_level) return; /* a new link starts from where the headset is */
    hsv.syncing = 1;
    g_vol_level = (signed char)v;
    device_set_volume(v, 1);
    void *top = window_manager_get_top_window(window_manager());
    if (top && eq(widget_get_prop_str(top, "name", (void *)0), VOLUME_DIALOG)) {
        void *slider = widget_lookup(top, "slider_vol", 1);
        if (slider) widget_set_prop_int(slider, "value", v);
    } else if (usable() && !(top && dialog_of(top)))
        navigator_to("dialog/" VOLUME_DIALOG);
    hsv.syncing = 0;
#ifdef RINGNAV_DUMP
    char what[20];
    tk_snprintf(what, sizeof(what), "hsvol %d -> %d", cur, v);
    bt_log(what);
#endif
}

#ifdef RINGNAV_DUMP
static void theme_flush(void);
#endif

static int btcard_tick(const void *info) {
    (void)info;
#ifdef RINGNAV_DUMP
    theme_flush();
    int sig = g_bluetoothflag | bt_linkstatus << 4 | bt_connectstatus << 8 | bt__recv_pageflag << 12 | bt_showcoding << 16;
    if (sig != btlog.last) {
        btlog.last = sig;
        bt_log("state");
    }
#endif
    /* bt_linkstatus is the connection (logged: 0 -> 1 about 1.5 s after the AirPods leave the case,
     * the codec follows ~1 s later); bt_connectstatus stays 0 while linked. */
    int on = g_bluetoothflag && bt_linkstatus && !bt__recv_pageflag;
    if (on && !btc.was && usable()) btcard_show();
    if (on && !btc.was) {
        char name[64];
        bt_name(name, sizeof(name));
        if (contains(name, "AirPods")) aap_start();
    }
    if (on && !btc.was) avrcp_start();
    /* The headset went (AirPods into the case, or Bluetooth off): pause, as an iPhone does. The Q2
     * played on, and AirPods reconnecting in the open case got the music (V1.9d, logged). */
    if (!on && btc.was && mclGetPlayStatus() == 2) player_play_pause();
    ear_tick(on);
    hs_volume_tick(on);
#ifdef RINGNAV_DUMP
    aap_flush();
#endif
    btc.was = on;
    return RET_REPEAT;
}

/* Theme colour: Apple dark-mode accents in place of Apple Music pink, chosen in Display setting >
 * Theme Colour (a picker page) and kept in ACCENT_FILE. Applied live, from one set of
 * theme assets: every themed colour is pink blended with a neutral (white/grey/black/transparent),
 * so a colour or pixel C is split as p * pink + w * white (least squares; A_P/A_W are the pseudo-
 * inverse rows, x 65536) and, if that explains it (residual <= ACCENT_TOL per channel), rebuilt as
 * p * accent + w * white. Style colours are mapped as style_get_color returns them; images as they
 * are decoded (image_manager_add, before caching; not file:// covers); image_manager_unload_all
 * makes a change reach images already loaded. The patch's own pink drawing uses accent_abgr(). */
#define ACCENT_FILE "/mnt/data/ipod_accent"
#define ACCENT_N 9
#define ACCENT_TOL 10
#define ACCENT_ROW "ipod_accent"
#define ACCENT_SWATCH "tidal_album" /* theme: a pink dot, recoloured like everything else */
static const unsigned char ACCENTS[ACCENT_N][3] = {
    { 0xfa, 0x2d, 0x48 }, /* pink (Apple Music), the theme's own */
    { 0xff, 0x45, 0x3a }, /* red */
    { 0xff, 0x9f, 0x0a }, /* orange */
    { 0x30, 0xd1, 0x58 }, /* green */
    { 0x2e, 0xc4, 0xa7 }, /* seafoam */
    { 0x40, 0xc8, 0xe0 }, /* teal */
    { 0x0a, 0x84, 0xff }, /* blue */
    { 0x5e, 0x5c, 0xe6 }, /* indigo */
    { 0xbf, 0x5a, 0xf2 }, /* purple */
};
struct {
    int index, loaded;
} accent __attribute__((section(".scratch")));

static int clamp255(int v) {
    return v < 0 ? 0 : v > 255 ? 255 : v;
}

/* c = r, g, b (straight or premultiplied): 1 if it was a pink blend, now in the accent. */
static int accent_map(unsigned char *c) {
    int r = c[0], g = c[1], b = c[2];
    int p = 337 * r - 204 * g - 133 * b, w = -76 * r + 184 * g + 149 * b; /* A_P, A_W for #fa2d48 */
    if (p < 3277 || w < -1311) return 0;                                     /* p >= 0.05, w >= -0.02 */
    int d0 = r - ((p * 250 + w * 255) >> 16), d1 = g - ((p * 45 + w * 255) >> 16), d2 = b - ((p * 72 + w * 255) >> 16);
    if (d0 > ACCENT_TOL || d0 < -ACCENT_TOL || d1 > ACCENT_TOL || d1 < -ACCENT_TOL || d2 > ACCENT_TOL || d2 < -ACCENT_TOL)
        return 0;
    const unsigned char *a = ACCENTS[accent.index];
    c[0] = (unsigned char)clamp255((p * a[0] + w * 255) >> 16);
    c[1] = (unsigned char)clamp255((p * a[1] + w * 255) >> 16);
    c[2] = (unsigned char)clamp255((p * a[2] + w * 255) >> 16);
    return 1;
}

#ifdef RINGNAV_DUMP
/* Debug: what the theme engine did, to /mnt/mmc/q2theme.txt (from the Bluetooth poll, on change). */
struct {
    int color, color_mapped, grad, grad_mapped, img, img_mapped, n, last;
    char line[8][60];
} thlog __attribute__((section(".scratch")));
#define TH(field) (++thlog.field)
#else
#define TH(field) ((void)0)
#endif

/* A colour_t (r @0 .. a @24) mapped in place; 1 if it was a pink blend. */
static int accent_map_u32(unsigned *v) {
    unsigned char c[3] = { (unsigned char)*v, (unsigned char)(*v >> 8), (unsigned char)(*v >> 16) };
    if (!accent_map(c)) return 0;
    *v = (*v & 0xff000000u) | (unsigned)c[2] << 16 | (unsigned)c[1] << 8 | c[0];
    return 1;
}

static void accent_load(void) {
    if (accent.loaded) return;
    accent.loaded = 1;
    unsigned size = 0;
    char *saved = (char *)file_read(ACCENT_FILE, &size);
    if (!saved) return;
    int i = size ? saved[0] - '0' : 0;
    tk_free(saved);
    /* No reload needed (and none from inside image_manager_add): the first of the two hooks to run
     * loads this before any image is cached. */
    if (i > 0 && i < ACCENT_N) accent.index = i;
}

static unsigned accent_abgr(void) {
    const unsigned char *a = ACCENTS[accent.index];
    return 0xff000000u | (unsigned)a[2] << 16 | (unsigned)a[1] << 8 | a[0];
}

unsigned *ringnav_style_color(unsigned *ret, void *style, const char *name, unsigned def) {
    unsigned *out = (unsigned *)stock_stylecolor(ret, style, name, def); /* returns ret, as stock */
    accent_load();
    TH(color);
    if (accent.index && ret && accent_map_u32(ret)) TH(color_mapped);
    return out;
}

/* Backgrounds (widget_fill_rect: pills, rows, cards) come as gradients, not through
 * style_get_color: style_get_gradient, a leaf calling the style's get_gradient (vtable +0x18) into
 * the caller's gradient_t (nr @8; stops @0xc, 8 bytes: colour, offset). build.py points it here: the
 * same call, then the stops mapped. Only the caller's copy is touched (the theme keeps its pink). */
void *ringnav_style_gradient(void *style, const char *name, void *out) {
    void *vt = style ? P(style, 0) : (void *)0;
    void *(*get)(void *, const char *, void *) = vt ? (void *(*)(void *, const char *, void *))P(vt, 0x18) : (void *)0;
    if (!get) return (void *)0;
    void *g = get(style, name, out);
    accent_load();
    TH(grad);
    if (g && g == out && accent.index) {
        int mapped = 0;
        for (int i = 0; i < I(g, 8) && i < 8; ++i) mapped |= accent_map_u32((unsigned *)((char *)g + 0xc + 8 * i));
        if (mapped) TH(grad_mapped);
    }
    return g;
}

/* bitmap_t: w @0, h @4, line_length @8, flags @0xc, format @0xe. Every decoded image carries the
 * immutable flag (2) (V2.4d log: 127 of 127), but its pixels are the loader's heap buffer, and this
 * runs once, before it is cached or drawn. */
static void accent_bitmap(void *bm) {
    int fmt = *(unsigned short *)((char *)bm + 0xe), ri, gi, bi;
    if (fmt == 1) ri = 0, gi = 1, bi = 2;      /* RGBA8888 */
    else if (fmt == 3) ri = 2, gi = 1, bi = 0; /* BGRA8888 */
    else if (fmt == 2) ri = 3, gi = 2, bi = 1; /* ABGR8888 */
    else if (fmt == 4) ri = 1, gi = 2, bi = 3; /* ARGB8888 */
    else return;
    int w = I(bm, 0), h = I(bm, 4), stride = I(bm, 8) ? I(bm, 8) : w * 4;
    unsigned char *data = bitmap_lock_buffer_for_write(bm);
    if (!data) return;
    int mapped = 0;
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            unsigned char *px = data + y * stride + x * 4, c[3] = { px[ri], px[gi], px[bi] };
            if (accent_map(c)) px[ri] = c[0], px[gi] = c[1], px[bi] = c[2], ++mapped;
        }
    bitmap_unlock_buffer(bm);
    if (mapped) TH(img_mapped);
}

int ringnav_image_add(void *imm, const char *name, void *bitmap) {
    accent_load();
#ifdef RINGNAV_DUMP
    TH(img);
    if (bitmap && name)
        tk_snprintf(thlog.line[thlog.n++ % 8], 60, "img %s fmt=%d fl=%d %dx%d", name, *(unsigned short *)((char *)bitmap + 0xe),
                    *(unsigned short *)((char *)bitmap + 0xc), I(bitmap, 0), I(bitmap, 4));
#endif
    if (accent.index && bitmap && !(name && name[0] == 'f' && name[1] == 'i' && name[2] == 'l' && name[3] == 'e' && name[4] == ':'))
        accent_bitmap(bitmap);
    return stock_imgadd(imm, name, bitmap);
}

#ifdef RINGNAV_DUMP
static void theme_flush(void) {
    int sum = thlog.color + thlog.grad + thlog.img + accent.index;
    if (sum == thlog.last) return;
    thlog.last = sum;
    char buf[8 * 62 + 160];
    int k = tk_snprintf(buf, 160, "accent %d loaded %d\ncolor %d/%d grad %d/%d img %d/%d\n", accent.index, accent.loaded,
                        thlog.color_mapped, thlog.color, thlog.grad_mapped, thlog.grad, thlog.img_mapped, thlog.img);
    for (int i = 0; i < 8 && i < thlog.n; ++i) {
        const char *l = thlog.line[(thlog.n - (thlog.n < 8 ? thlog.n : 8) + i) % 8];
        while (*l) buf[k++] = *l++;
        buf[k++] = '\n';
    }
    file_write("/mnt/mmc/q2theme.txt", buf, (unsigned)k);
}
#endif

static void accent_set(int i) {
    accent.index = i;
    char b = (char)('0' + i);
    file_write(ACCENT_FILE, &b, 1);
    image_manager_unload_all(image_manager());
    widget_invalidate_force(window_manager(), (void *)0);
}

static const char *const ACCENT_NAMES[ACCENT_N] = { "Pink", "Red", "Orange", "Green", "Seafoam", "Teal", "Blue", "Indigo", "Purple" };
#define ACCENT_PAGE "ipod_accent_page"
#define SWATCH "_ipod_swatch" /* on a picker row: 1 + its accent; the paint hook draws its dot */

static unsigned accent_abgr_of(int i) {
    const unsigned char *a = ACCENTS[i];
    return 0xff000000u | (unsigned)a[2] << 16 | (unsigned)a[1] << 8 | a[0];
}

/* A picker row's dot: its own colour, exactly (drawn, not a themed image, which would follow the
 * accent); the current accent ringed in white. */
static void swatch_draw(void *row, void *canvas) {
    int i = widget_get_prop_int(row, SWATCH, 0) - 1;
    void *vg = canvas_get_vgcanvas(canvas);
    if (i < 0 || i >= ACCENT_N || !vg) return;
    /* at on_paint_border the canvas is already at the row's own origin */
    float cx = (float)(I(canvas, 0) + I(row, 8) - 30), cy = (float)(I(canvas, 4) + I(row, 0x0c) / 2);
    vgcanvas_save(vg);
    vgcanvas_begin_path(vg);
    vgcanvas_rounded_rect(vg, cx - 9.0f, cy - 9.0f, 18.0f, 18.0f, 9.0f);
    vgcanvas_set_fill_color(vg, accent_abgr_of(i));
    vgcanvas_fill(vg);
    if (i == accent.index) {
        vgcanvas_begin_path(vg);
        vgcanvas_rounded_rect(vg, cx - 12.0f, cy - 12.0f, 24.0f, 24.0f, 12.0f);
        vgcanvas_set_line_width(vg, 2.0f);
        vgcanvas_set_stroke_color(vg, 0xffffffffu);
        vgcanvas_stroke(vg);
    }
    vgcanvas_restore(vg);
}

static void *accent_page(void) {
    return widget_lookup(window_manager(), ACCENT_PAGE, 0);
}

static int accent_back(void *ctx, void *e) {
    (void)ctx, (void)e;
    void *page = accent_page();
    if (page) window_close(page);
    return RET_OK;
}

/* Picking a colour applies and keeps it at once (the page recolours too, so colours can be compared
 * in place); picking the current one again goes back, for the wheel. */
static int accent_pick(void *ctx, void *e) {
    int i = (int)(long)ctx;
    if (i == accent.index) return accent_back(ctx, e);
    accent_set(i);
    return RET_OK;
}

#define KEY_BACK 0xaa /* the wheel's back key: on_common_keyup (stock pages) returns on it */
#define EVT_KEYUP 0x114
static int accent_key(void *ctx, void *e) {
    if (e && I(e, 0x18) == KEY_BACK) accent_back(ctx, e);
    return RET_OK;
}

static void *page_style(void *w) { /* new lists: AWTK's default list look is light grey */
    widget_set_prop_str(w, "style:normal:bg_color", "#000000ff");
    widget_set_prop_str(w, "style:normal:border_color", "#00000000");
    return w;
}

/* The picker: a page like Shanling's settings pages, built in code: the back arrow and title, then a
 * list of the accents with their dots, the current one selected. */
static void accent_open(void) {
    if (accent_page()) return;
    void *win = window_create((void *)0, 0, 30, 375, 290);
    if (!win) return;
    widget_set_prop_str(win, "name", ACCENT_PAGE);
    widget_set_prop_str(win, "style:normal:bg_color", "#000000ff");
    widget_set_prop_str(win, "open_anim_hint", "htranslate(duration=200)");
    widget_on(win, EVT_KEYUP, accent_key, (void *)0);
    void *back = image_create(win, 20, 0, 100, 42);
    widget_use_style(back, "s_img_return");
    widget_set_prop_str(back, "clickable", "true");
    widget_on(back, EVT_CLICK, accent_back, (void *)0);
    void *title = hscroll_label_create(win, 70, 0, 200, 42);
    widget_use_style(title, "s_scrlabel_white24l");
    widget_set_text_utf8(title, "Theme Colour");
    /* 16 px short of the bottom, like the themed lists: the screen's rounded corners hide it */
    void *list = page_style(list_view_create(win, 0, 42, 375, 232));
    widget_set_prop_int(list, "default_item_height", 30);
    void *sv = page_style(scroll_view_create(list, 0, 0, 375, 232));
    widget_set_prop_str(sv, "yslidable", "true"); /* scroll_view_create leaves it off */
    for (int i = 0; i < ACCENT_N; ++i) {
        void *item = list_item_create(sv, 0, i * 30, 375, 30);
        widget_use_style(item, "s_listitem_black");
        void *btn = button_create(item, 6, 1, 363, 28);
        widget_use_style(btn, "s_btn_listitem");
        widget_set_prop_int(btn, SWATCH, i + 1);
        void *name = hscroll_label_create(btn, 12, 0, 279, 28);
        widget_use_style(name, "s_scrlabel_white24l");
        widget_set_text_utf8(name, ACCENT_NAMES[i]);
        widget_on(btn, EVT_CLICK, accent_pick, (void *)(long)i);
    }
    widget_set_prop_int(sv, SEL, accent.index);
    widget_layout(win);
}

static int accent_click(void *ctx, void *e) {
    (void)ctx, (void)e;
    accent_open();
    return RET_OK;
}

/* Display setting's rows are built in code; the theme colour row is added after them, like theirs:
 * a title and, on the right, a dot in the current colour (the themed pink dot); it opens the picker. */
static void accent_row(void *win) {
    if (!win || !eq(widget_get_prop_str(win, "name", (void *)0), "display_page")) return;
    void *sv = widget_lookup(win, "scroll_view_display", 1);
    if (!sv || widget_lookup(sv, ACCENT_ROW, 1)) return;
    void *item = list_item_create(sv, 0, (int)widget_count_children(sv) * 30, 375, 30);
    if (!item) return;
    widget_use_style(item, "s_listitem_black");
    void *btn = button_create(item, 6, 1, 363, 28);
    widget_set_prop_str(btn, "name", ACCENT_ROW);
    widget_use_style(btn, "s_btn_listitem");
    void *title = hscroll_label_create(btn, 12, 0, 279, 28);
    widget_use_style(title, "s_scrlabel_white24l");
    widget_set_text_utf8(title, "Theme Colour");
    void *swatch = image_create(btn, 307, 0, 50, 28);
    image_base_set_image(swatch, ACCENT_SWATCH);
    widget_set_prop_str(swatch, "draw_type", "icon");
    widget_on(btn, EVT_CLICK, accent_click, (void *)0);
    widget_layout(P(sv, 0x48) ? P(sv, 0x48) : sv);
}

/* Boot to Home, like an iPod: home_page_init resumes the last queue by opening Now Playing with it
 * (navigator_to_with_context("playing_page", {queue, pos, source, mode})); that page's init sets
 * two globals and calls player_start(queue, pos, source, mode) unless source is 0xff. build.py
 * points that call here instead: the same resume, and the Home screen stays. Mode 2 plays, anything
 * else starts paused (player_start calls mclSetPause); stock passes 2 if it was playing at power-off,
 * which with Home on screen played unseen until a headset connected (AirPods still in the case).
 * An iPod comes back paused, so always 3. */
#define BOOT_MODE_PAUSED 3
int ringnav_boot_play(const char *page, int *ctx) {
    (void)page;
    *(volatile unsigned char *)0xa3a6c1u = 0;
    *(volatile unsigned char *)0x99f660u = 0x28;
    if (ctx[2] != 0xff) player_start((void *)ctx[0], ctx[1], ctx[2], BOOT_MODE_PAUSED);
    return 0;
}

/* Page slides draw snapshots of both windows, taken here before the first frame. The paint-time
 * restyle stands down while a window animates, so without this the slide showed the stock rows
 * and the iPod layout snapped in once it ended. Lay out and restyle both windows first. */
int ringnav_prepare(void *wa, void *canvas, void *prev, void *curr) {
    accent_row(curr);
    if (dialog_usable()) {
        void *wins[2] = { curr, prev };
        for (int i = 0; i < 2; ++i) {
            if (!wins[i]) continue;
            menu_t m;
            if (i == 0) widget_layout(wins[i]);
            if (usable()) {
                ipod_apply_on(surface_of(wins[i]), &m);
                album_sync(wins[i]);
            }
            void *out[DIALOG_MAX];
            if (dialog_of(wins[i])) dialog_apply(wins[i], out);
        }
    }
    return stock_prepare(wa, canvas, prev, curr);
}

static int ipod_idle(const void *info) {
    (void)info;
    ipod.idle = 0;
    ipod_apply();
    return RET_REMOVE;
}

/* Now-playing marker. Stock rows show an animated gif inside the cover thumbnail (hidden here with
 * the thumbnail) and switch the title to a green style; either marks the row, and the paint hook
 * draws Apple Music style bars at its right edge (pink, or white on the selected pill). */
#define IPOD_NP "_ipod_np"
static int is_playing(void *w, void *title, int depth) {
    const char *style = title ? widget_get_prop_str(title, "style", (void *)0) : (void *)0;
    if (eq(style, IPOD_SEL)) style = widget_get_prop_str(title, IPOD_SAVED, (void *)0);
    if (!depth && starts(style, "s_scrlabel_green")) return 1;
    unsigned n = widget_count_children(w);
    for (unsigned i = 0; i < n && depth < 6; ++i) {
        void *c = widget_get_child(w, i);
        const char *name = c ? widget_get_prop_str(c, "name", (void *)0) : (void *)0;
        if (starts(name, "img_gifbg") || starts(name, "imggifbg")) {
            if (widget_get_visible(c)) return 1; /* its own flag: the thumbnail parent is hidden */
        } else if (c && is_playing(c, (void *)0, depth + 1))
            return 1;
    }
    return 0;
}

/* The bars bounce: heights step through FRAMES every NP_TICK_MS, each bar out of phase. A
 * repeating timer advances the frame and repaints the playing row while a marker is on screen and
 * playback runs (paused: the bars freeze); it re-finds the row every tick (rows recycle) and
 * stops when none is visible. */
#define NP_TICK_MS 120
#define NP_TITLE 48
struct {
    unsigned timer, frame;
    int has, title[NP_TITLE]; /* last playing song's title: paused rows lose the stock badge */
} np __attribute__((section(".scratch")));

/* Playing vs paused, from the status bar's play-state icon ("bar_play" while playing). No status
 * bar found: assume playing, so the bars never stick. */
static int np_playing(void) {
    void *wm = window_manager();
    for (unsigned i = 0, n = widget_count_children(wm); i < n; ++i) {
        void *c = widget_get_child(wm, i);
        if (c && eq(widget_get_type(c), "system_bar")) {
            void *s = widget_lookup(c, "img_state", 1);
            return s && widget_get_visible(s) && eq(widget_get_prop_str(s, "image", (void *)0), "bar_play");
        }
    }
    return 1;
}

static int np_tick(const void *info) {
    (void)info;
    if (!np_playing()) return RET_REPEAT; /* paused: bars hold their frame; cheap check only */
    ++np.frame;
    void *w = surface();
    menu_t m;
    int found = 0;
    if (w && load(&m, w))
        for (unsigned i = 0, n = widget_count_children(m.w); i < n; ++i) {
            void *row = widget_get_child(m.w, i), *e = row && widget_count_children(row)
                                                         ? widget_get_child(row, 0) : row;
            if (e && widget_get_visible(row) && widget_get_prop_int(e, IPOD_NP, 0)) {
                widget_invalidate_force(e, (void *)0);
                found = 1;
            }
        }
    if (found) return RET_REPEAT;
    np.timer = 0;
    return RET_REMOVE;
}

static int same_text(const int *a, const int *b) {
    int i = 0;
    while (i < NP_TITLE - 1 && a[i] && a[i] == b[i]) ++i;
    return a[i] == b[i] || i == NP_TITLE - 1;
}

/* Flag the playing row. Paused, the app switches its badge off, so the row whose title matches the
 * last playing song keeps the (frozen) marker. Final flags are decided before any is set, so a row
 * never flips back and forth between passes. */
static void np_remember(void *title) {
    const int *t = widget_get_text(title);
    int k = 0;
    for (; t && t[k] && k < NP_TITLE - 1; ++k) np.title[k] = t[k];
    np.title[k] = 0;
    np.has = 1;
}

/* One row's marker flag: its own badge, else (paused) the last playing title. */
static int np_flag(void *entry, void *title) {
    int v = is_playing(entry, title, 0);
    if (v && title) np_remember(title);
    else if (!v && np.has && title && !np_playing()) {
        const int *t = widget_get_text(title);
        v = t && t[0] && same_text(t, np.title);
    }
    if (widget_get_prop_int(entry, IPOD_NP, 0) == v) return 0;
    widget_set_prop_int(entry, IPOD_NP, v);
    return 1;
}

static int np_rows(menu_t *m) {
    void *rows[48];
    int play[48], n = 0, any = 0, changed = 0;
    for (unsigned i = 0, c = widget_count_children(m->w); i < c && n < 48; ++i) {
        void *row = widget_get_child(m->w, i);
        if (!row || !widget_get_visible(row) || !FLAT_H(I(row, 0x0c))) continue;
        void *e = widget_count_children(row) ? widget_get_child(row, 0) : row, *title;
        if (!e) continue;
        title = find_label(e, (void *)0, 0);
        play[n] = is_playing(e, title, 0);
        if (play[n] && title) {
            np_remember(title);
            any = 1;
        }
        rows[n++] = e;
    }
    int paused = !any && np.has && !np_playing();
    for (int i = 0; i < n; ++i) {
        int v = play[i];
        if (!v && paused) {
            void *title = find_label(rows[i], (void *)0, 0);
            const int *t = title ? widget_get_text(title) : (void *)0;
            v = t && t[0] && same_text(t, np.title);
        }
        if (widget_get_prop_int(rows[i], IPOD_NP, 0) != v) {
            widget_set_prop_int(rows[i], IPOD_NP, v);
            changed = 1;
        }
    }
    return changed;
}

/* Up Next cover: the row's img_icon image, scaled into its 36 px box with 6 px corners. */
static void row_art(void *entry, void *canvas) {
    void *art = widget_lookup(entry, "img_icon", 1);
    const char *name = art ? widget_get_prop_str(art, "image", (void *)0) : (void *)0;
    if (!name || !*name) return;
    int bmp[0x60 / 4];
    if (widget_load_image(art, name, bmp) || bmp[0] <= 0 || bmp[1] <= 0) return;
    void *vg = canvas_get_vgcanvas(canvas);
    if (!vg) return;
    float x = (float)(I(canvas, 0) + I(art, 0)), y = (float)(I(canvas, 4) + I(art, 4));
    float w = (float)I(art, 8), h = (float)I(art, 0x0c);
    blit(vg, bmp, x, y, w / (float)bmp[0], h / (float)bmp[1], x, y, w, h, 6.0f);
}

static void np_marker(void *w, void *canvas) {
    static const int frames[8] = { 5, 9, 13, 15, 11, 7, 10, 14 };
    int x = I(w, 8) - 26, base = I(w, 0x0c) / 2 + 7, f = (int)np.frame;
    canvas_set_fill_color(canvas, eq(widget_get_prop_str(w, "style", (void *)0), IPOD_SEL)
                                      ? 0xffffffffu : accent_abgr()); /* white / the theme colour */
    for (int i = 0; i < 3; ++i) {
        int h = frames[(f + i * 3) & 7];
        canvas_fill_rect(canvas, x + i * 5, base - h, 3, h);
    }
    if (!np.timer) np.timer = timer_add(np_tick, (void *)0, NP_TICK_MS);
}

/* Every row, not only selectable entries: disabled rows need the same flat layout. */
/* One visible list/table row: flat layout plus the selected styles. Grids (tall rows) keep stock. */
/* Chip rows show the wheel's focus on the chips: the focused one bright, the others dimmed. */
#define CHIP_DIM 110
static int chip_focus(void *entry, int width, void *sel) {
    int changed = 0, focus = sel && sel != entry && is_chip(sel, width) && holds(entry, sel);
    for (unsigned i = 0, n = widget_count_children(entry); i < n; ++i) {
        void *c = widget_get_child(entry, i);
        if (!c || !is_chip(c, width)) continue;
        int want = !focus || c == sel ? 255 : CHIP_DIM;
        if (widget_get_prop_int(c, "opacity", 255) != want) {
            widget_set_prop_int(c, "opacity", want);
            changed = 1;
        }
    }
    return changed;
}

/* One entry of a row, laid out as a pill w wide at x (the whole row, or its share of it). */
static int ipod_entry(void *row, void *entry, int x, int w, int on, void *sel) {
    int changed = 0, inset = entry != row ? ROW_INSET : 0, h = I(row, 0x0c);
    row_t r = { entry, find_label(entry, (void *)0, 0), (void *)0, (void *)0, (void *)0,
                w, h - (inset ? 2 : 0), 0, 12 };
    if (h >= ROWART_H) r.art = widget_lookup(entry, "img_icon", 1);
    if (r.art) r.tx = 10 + ART_S + 10;
    r.pick = widget_lookup(entry, "img_choice", 1);
    if (r.pick && !widget_get_visible(r.pick)) r.pick = (void *)0;
    if (r.pick) r.tx += 34;
    r.tw = r.width - (has_state(entry, r.width, 0) ? 84 : 48) - (r.tx - 12);
    int chips = chip_x(entry, (void *)0, r.width);
    if (chips < r.width && r.tw > chips - r.tx - 8) r.tw = chips - r.tx - 8; /* title stops before them */
    if (h >= ROW2_H && r.title) r.sub = find_label(entry, r.title, 0);
    if (!!r.art != !!widget_get_prop_int(entry, IPOD_ART, 0)) {
        widget_set_prop_int(entry, IPOD_ART, r.art != 0);
        changed = 1;
    }
    if (entry != row) changed |= place(entry, x, inset ? 1 : 0, r.width, r.h);
    changed |= flatten(&r, entry, 0);
    int pill = on && chips >= r.width; /* a chip row shows its focus on the chips instead */
    changed |= restyle(entry, pill, IPOD_SEL);
    if (r.title) changed |= restyle(r.title, pill, IPOD_SEL);
    if (r.sub) changed |= restyle(r.sub, pill, IPOD_SEL2);
    if (chips < r.width) changed |= chip_focus(entry, r.width, on ? sel : (void *)0);
    return changed;
}

/* A row: one entry becomes a full-width pill; several buttons (playlist Import | Export) share
 * the row as side-by-side pills. all: the whole row is selected (table rows by index). */
#define PAIR_GAP 6
static int ipod_row(void *row, void *sel, int all) {
    if (!row || !widget_get_visible(row) || !FLAT_H(I(row, 0x0c))) return 0;
    int width = I(row, 8), k = 0;
    unsigned n = widget_count_children(row);
    if (!n) return ipod_entry(row, row, 0, width, all || (sel && holds(row, sel)), sel);
    for (unsigned i = 0; i < n; ++i) {
        void *c = widget_get_child(row, i);
        if (c && widget_get_visible(c) && eq(widget_get_type(c), "button")) ++k;
    }
    if (k <= 1) {
        void *entry = widget_get_child(row, 0);
        return entry ? ipod_entry(row, entry, ROW_INSET, width - 2 * ROW_INSET, all || (sel && holds(row, sel)), sel)
                     : 0;
    }
    int changed = 0, each = (width - 2 * ROW_INSET - (k - 1) * PAIR_GAP) / k, x = ROW_INSET;
    for (unsigned i = 0; i < n; ++i) {
        void *c = widget_get_child(row, i);
        if (!c || !widget_get_visible(c) || !eq(widget_get_type(c), "button")) continue;
        changed |= ipod_entry(row, c, x, each, all || (sel && holds(c, sel)), sel);
        x += each + PAIR_GAP;
    }
    return changed;
}

/* Grid tiles: the selected one is marked (GSEL) and the paint hook frames its cover in pink. */
#define GSEL "_ipod_gsel"
static int grid_mark(void *row, void *sel) {
    int changed = 0;
    for (unsigned i = 0, n = widget_count_children(row); i < n; ++i) {
        void *tile = widget_get_child(row, i);
        int want = tile && sel && holds(tile, sel);
        if (tile && widget_get_prop_int(tile, GSEL, 0) != want) {
            widget_set_prop_int(tile, GSEL, want);
            changed = 1;
        }
    }
    return changed;
}

#define FRAME_W 4
static void grid_frame(void *tile, void *canvas) {
    void *cover = (void *)0;
    for (unsigned i = 0, n = widget_count_children(tile); i < n && !cover; ++i) {
        void *c = widget_get_child(tile, i);
        if (c && eq(widget_get_type(c), "image")) cover = c;
    }
    int x = cover ? I(cover, 0) : 0, y = cover ? I(cover, 4) : 0;
    int w = cover ? I(cover, 8) : I(tile, 8), h = cover ? I(cover, 0x0c) : I(tile, 0x0c);
    canvas_set_fill_color(canvas, accent_abgr()); /* the theme colour */
    canvas_fill_rect(canvas, x, y, w, FRAME_W);
    canvas_fill_rect(canvas, x, y + h - FRAME_W, w, FRAME_W);
    canvas_fill_rect(canvas, x, y, FRAME_W, h);
    canvas_fill_rect(canvas, x + w - FRAME_W, y, FRAME_W, h);
}

static int ipod_rows(menu_t *m, int cur) {
    int changed = 0;
    void *sel = cur >= 0 ? m->at[cur] : (void *)0;
    unsigned n = widget_count_children(m->w);
    for (unsigned i = 0; i < n && i < MAX_ENTRIES; ++i) {
        void *row = widget_get_child(m->w, i);
        if (row && I(row, 0x0c) == GRID_H && PER(m) > 1)
            changed |= grid_mark(row, sel);
        else
            changed |= ipod_row(row, sel, 0);
    }
    return changed;
}

/* Tables bind a row's data through on_load_data(ctx, index, row) as they scroll or refresh (play
 * and pause refresh every row). That restores the stock card for a frame before the idle pass, a
 * visible flicker, so the registration is hooked: the app's callback runs, then the row is made
 * an iPod row right away. The app's fn/ctx live on the table itself (no shared list). */
#define LOAD_FN "_ipod_load_fn"
#define LOAD_CTX "_ipod_load_ctx"
typedef int (*load_fn_t)(void *, int, void *);

static int np_flag(void *entry, void *title);

/* Cover rows draw their thumbnail from the image cache, which the stock image widget would have
 * released after use. Kept, every album scrolled past stayed decoded (bitmap and vg texture) until
 * the app ran out of memory: covers fell back to grey, file writes failed. So when a recycled row
 * is bound to another album, its previous cover is dropped from the cache. */
static void cover_name(void *icon, char *out, int cap) {
    const char *n = icon ? widget_get_prop_str(icon, "image", (void *)0) : (void *)0;
    int i = 0;
    while (n && n[i] && i < cap - 1) out[i] = n[i], ++i;
    out[i] = 0;
}

int ringnav_load(void *client, int index, void *row) {
    load_fn_t fn = (load_fn_t)widget_get_prop_int(client, LOAD_FN, 0);
    char before[128];
    void *icon = row && I(row, 0x0c) == ROWART_H ? widget_lookup(row, "img_icon", 1) : (void *)0;
    cover_name(icon, before, sizeof(before));
    int ret = fn ? fn((void *)widget_get_prop_int(client, LOAD_CTX, 0), index, row) : 0;
    if (icon && starts(before, "file://") && !eq(widget_get_prop_str(icon, "image", (void *)0), before))
        image_manager_unload_bitmap_by_name(image_manager(), before);
    if (row && widget_get_visible(row) && FLAT_H(I(row, 0x0c))) {
        ipod_row(row, (void *)0, index == widget_get_prop_int(client, SEL, -1));
        void *entry = widget_count_children(row) ? widget_get_child(row, 0) : row;
        if (entry) np_flag(entry, find_label(entry, (void *)0, 0));
    }
    return ret;
}

/* Album covers. The app prepares small covers 12 albums at a time from a start index it computes
 * as offset / 78 (the stock row height), on a scroll event; a row shows its cover only if its album
 * was ready when it was bound, and nothing re-binds it once the cover is ready. With 46 px rows
 * (and wheel scrolling) albums past the first screen never got covers. So after the list moves,
 * the covers from just above the first visible row are requested, and for a few seconds visible
 * rows still on the placeholder are re-bound once their album is ready. */
#define COVER_BATCH 12
#define COVER_TICK_MS 200
#define COVER_WAIT_MS 10000 /* big covers are extracted from the audio files: slower */
#define COVER_START "_ipod_cover_start"
struct {
    unsigned timer, until;
} covq __attribute__((section(".scratch")));

static int cover_rows(void *w) {
    int filled = 0;
    for (unsigned i = 0, n = widget_count_children(w); i < n; ++i) {
        void *row = widget_get_child(w, i);
        int idx = row ? I(row, 0x78) : -1;
        if (!row || !widget_get_visible(row) || idx < 0) continue;
        int stale = 0;
        if (I(row, 0x0c) == GRID_H) {
            char name[12];
            for (int t = 0; t < GRID_N && !stale; ++t) {
                tk_snprintf(name, sizeof(name), "img_icon%d", t + 1);
                void *icon = widget_lookup(row, name, 1);
                stale = icon && eq(widget_get_prop_str(icon, "image", (void *)0), "default_album_big") &&
                        check_albumcover_flag(idx * GRID_N + t, 1);
            }
        } else {
            void *icon = widget_lookup(row, "img_icon", 1);
            stale = icon && eq(widget_get_prop_str(icon, "image", (void *)0), "default_album_small") &&
                    check_albumcover_flag(idx, 0);
        }
        if (!stale) continue;
        ringnav_load(w, idx, row); /* the app's own binding: it now picks the cover file */
        filled = 1;
    }
    return filled;
}

static int cover_tick(const void *info) {
    (void)info;
    void *w = surface();
    void *top = window_manager_get_top_window(window_manager());
    if (!w || !eq(widget_get_prop_str(top, "name", (void *)0), "album_page") ||
        (int)(covq.until - (unsigned)time_now_ms()) <= 0) {
        covq.timer = 0;
        return RET_REMOVE;
    }
    if (cover_rows(w)) widget_invalidate_force(w, (void *)0);
    return RET_REPEAT;
}

static void cover_request(menu_t *m) {
    int grid = m->row == GRID_H;
    if (m->kind != 2 || (!grid && m->row != ROWART_H) || !eq(window_name(m->w), "album_page")) return;
    int first = m->top / m->row;
    int start = grid ? (first > 1 ? first - 1 : 0) * GRID_N : first > 2 ? first - 2 : 0;
    if (widget_get_prop_int(m->w, COVER_START, -1) == start * 2 + grid) return;
    widget_set_prop_int(m->w, COVER_START, start * 2 + grid);
    if (grid)
        local_albumcover_task(start, COVER_BATCH); /* big covers, extracted and kept in .sldp */
    else
        local_albumsmallcover_task(start, COVER_BATCH);
    covq.until = (unsigned)time_now_ms() + COVER_WAIT_MS;
    if (!covq.timer) covq.timer = timer_add(cover_tick, (void *)0, COVER_TICK_MS);
}

int ringnav_set_load(void *client, void *fn, void *ctx) {
    widget_set_prop_int(client, LOAD_FN, (int)fn);
    widget_set_prop_int(client, LOAD_CTX, (int)ctx);
    return stock_loaddata(client, (void *)ringnav_load, client);
}
#endif

/* Stock paints children first and calls this with the surface's canvas origin restored.
 * Explicit outline avoids theme-dependent focus and doesn't overwrite playing/pressed styles. */
int ringnav_paint(void *w, void *canvas) {
    int result = stock_paint(w, canvas);
#ifdef RINGNAV_DUMP
    dump_watch();
#endif
#ifdef RINGNAV_IPOD
    if (w && canvas && eq(widget_get_prop_str(w, "name", (void *)0), "view_album")) round_art(w, canvas);
    if (w && canvas && eq(widget_get_prop_str(w, "name", (void *)0), "view_homeart")) homeart_draw(w, canvas);
    if (w && canvas && eq(widget_get_type(w), "button") && widget_get_prop_int(w, IPOD_ART, 0))
        row_art(w, canvas);
    if (w && canvas && widget_get_prop_int(w, GSEL, 0)) grid_frame(w, canvas);
    if (w && canvas && eq(widget_get_type(w), "button") && widget_get_prop_int(w, SWATCH, 0)) swatch_draw(w, canvas);
    if (!btc.timer) {
        int bmp[0x60 / 4];
        widget_load_image(w, CARD_AIRPODS, bmp); /* decoded now, kept: the first card opens smoothly */
        btc.timer = timer_add(btcard_tick, (void *)0, BTPOLL_MS);
    }
    if (w && canvas && eq(widget_get_type(w), "button") && widget_get_prop_int(w, IPOD_NP, 0))
        np_marker(w, canvas);
    if (w && !ipod.dialog && dialog_usable() && dialog_of(w) && w == window_manager_get_top_window(window_manager()))
        ipod.dialog = idle_add(dialog_idle, (void *)0);
    /* The elapsed time and progress bar repaint every second: a cheap moment to sync the album line,
     * the "3 of 12" counter and the time left. */
    if (w && !ipod.album && (eq(widget_get_prop_str(w, "name", (void *)0), "slider_play") ||
                             eq(widget_get_prop_str(w, "name", (void *)0), "label_playtime")))
        ipod.album = idle_add(album_idle, (void *)0);
#endif
    if (!w || !canvas || !kind(w) || surface() != w) return result;
    menu_t m;
    if (!load(&m, w) || m.kind == 3) return result; /* Home already shows its selected card. */
    int i = reconcile(&m, !moving(&m) && !window_manager_get_pointer_pressed(window_manager()));
#ifdef RINGNAV_IPOD
    (void)i;
    if (!ipod.idle) ipod.idle = idle_add(ipod_idle, (void *)0);
    return result; /* The selected row's own style is the highlight: no outline. */
#endif
    if (i < 0) return result;
    rect_t r = bounds(&m, i), old, clip;
    if (r.w < 5 || r.h < 5 || !P(canvas, 0x38)) return result;
    canvas_get_clip_rect(canvas, &old);
    int x = I(canvas, 0), y = I(canvas, 4);
    clip.x = old.x > x ? old.x : x;
    clip.y = old.y > y ? old.y : y;
    int right = old.x + old.w < x + I(w, 8) ? old.x + old.w : x + I(w, 8);
    int bottom = old.y + old.h < y + m.height ? old.y + old.h : y + m.height;
    clip.w = right - clip.x;
    clip.h = bottom - clip.y;
    if (clip.w <= 0 || clip.h <= 0) return result;
    unsigned color = (unsigned)I(P(canvas, 0x38), 0xc0);
    canvas_set_clip_rect(canvas, &clip);
    canvas_set_stroke_color(canvas, RING_COLOR);
    canvas_stroke_rect(canvas, r.x + 1, r.y + 1, r.w - 2, r.h - 2);
    canvas_stroke_rect(canvas, r.x + 2, r.y + 2, r.w - 4, r.h - 4);
    canvas_set_stroke_color(canvas, color);
    canvas_set_clip_rect(canvas, &old);
    return result;
}

int ringnav_touch(void *ctx, void *event) {
    int result = stock_touch(ctx, event);
#ifdef RINGNAV_IPOD
    lrc.touch_at = (unsigned)time_now_ms();
#endif
    void *w = surface();
    menu_t m;
    cancel_click(); /* A touch overrides a centre click still waiting on its double-press window. */
    center.last = 0;
    if (!result && w && load(&m, w)) {
        stop_scroll(&m);
        prop(w, TOUCH, 1);
#ifdef RINGNAV_IPOD
        prop(w, HEAD, 0);
#endif
        widget_invalidate_force(w, (void *)0);
    }
    return result; /* The very same touch continues through the stock tap/drag handlers. */
}

/* Observe actual clicks BEFORE app callbacks can navigate or destroy/rebind their widgets.
 * Do not turn pointer-down into selection: a swipe is not a tap. */
int ringnav_dispatch(void *target, void *event) {
    if (target && event && I(event, 0) == EVT_CLICK) {
        void *w = surface();
        menu_t m;
        if (w && load(&m, w)) {
            for (int i = 0; i < m.n; ++i) {
                if (m.at[i] == target) {
                    prop(w, SEL, m.id[i]);
                    widget_invalidate_force(w, (void *)0);
                    break;
                }
            }
        }
    }
    return stock_dispatch(target, event);
}

/* No second release arrived: open whatever is selected now. Nothing is retained across the wait,
 * so the surface and entry are resolved afresh; any change of page simply drops the click. */
static int click_later(const void *info) {
    (void)info;
    center.timer = 0;
#ifdef RINGNAV_IPOD
    void *out[DIALOG_MAX], *d = dialog_usable() ? dialog_of(window_manager_get_top_window(window_manager())) : (void *)0;
    int dn = d && !window_manager_get_pointer_pressed(window_manager()) ? dialog_apply(d, out) : 0;
    if (dn) {
        int sel = widget_get_prop_int(d, DSEL, 0);
        void *k = out[sel < dn ? sel : dn - 1];
        char click[0x30];
        ringnav_dispatch(k, pointer_event_init(click, EVT_CLICK, k, 0, 0));
        return RET_REMOVE;
    }
#endif
    void *w = surface();
    menu_t m;
    if (!w || window_manager_get_pointer_pressed(window_manager()) || !load(&m, w)) return RET_REMOVE;
    char click[0x30];
#ifdef RINGNAV_IPOD
    void *all = widget_get_prop_int(w, HEAD, 0) ? head_target(w) : (void *)0;
    if (all) { /* Play All focused */
        ringnav_dispatch(all, pointer_event_init(click, EVT_CLICK, all, 0, 0));
        return RET_REMOVE;
    }
#endif
    int cur = reconcile(&m, !moving(&m));
    if (cur < 0) return RET_REMOVE;
    /* Synchronous native click: no queued recycled row can change the activated item. */
    ringnav_dispatch(m.at[cur], pointer_event_init(click, EVT_CLICK, m.at[cur], 0, 0));
    return RET_REMOVE; /* No widget access after the app callback. */
}

#ifdef RINGNAV_ACCEL
/* Wheel acceleration, like the iPod. The knob is polled every ~83 ms and a fast spin still skips a
 * poll every few detents (165-185 ms gaps, measured), so: under ACCEL_MS apart in one direction
 * builds the streak, a gap up to ACCEL_DECAY_MS halves it, longer or a reversal resets it.
 * Step doubles with the streak (2 at 2, 4 at 5, 8 at 10, 16 at 16, 32 at 22, 64 at 30) and is capped
 * at 1/16 of the list, so short lists (under 32 rows: menus, settings) never skip entries while a
 * 6,000-song library crosses in seconds. */
#define ACCEL_MS 200
#define ACCEL_DECAY_MS 400
struct {
    unsigned last;
    int streak, dir;
} accel __attribute__((section(".scratch")));

/* The knob thread polls the ring (200 counts per turn) about every 83 ms and emits at most one
 * detent per poll, however far it turned; the distance is the real speed signal. get_direction()
 * is replaced by this copy (same result: +/-1 past the threshold, 0 at the half-turn ambiguity),
 * which also records that distance for the UI thread's next detent. */
struct {
    int mag;
} wheel __attribute__((section(".scratch")));

int ringnav_direction(int cur, int prev, int threshold) {
    int d = cur - prev;
    if (d < -100) d += 200;
    if (d > 100) d -= 200;
    int a = d < 0 ? -d : d;
    if (a <= threshold || a == 100) return 0;
    wheel.mag = a;
    return d > 0 ? -1 : 1;
}

static int accel_step(int dir, int rows) {
    unsigned now = (unsigned)time_now_ms();
    unsigned gap = now - accel.last;
    accel.streak = dir != accel.dir || gap >= ACCEL_DECAY_MS ? 0
                   : gap >= ACCEL_MS                       ? accel.streak / 2
                                                           : accel.streak + 1;
    accel.dir = dir;
    accel.last = now;
    int k = accel.streak;
    int streak = k >= 30 ? 64 : k >= 22 ? 32 : k >= 16 ? 16 : k >= 10 ? 8 : k >= 5 ? 4 : k >= 2 ? 2 : 1;
    /* ~20 counts per detent: one poll's distance of 2, 3 or 4+ detents' worth jumps 2, 4 or 8. */
    int mag = wheel.mag, flick = mag >= 80 ? 8 : mag >= 60 ? 4 : mag >= 40 ? 2 : 1;
    wheel.mag = 0; /* consumed: a stale distance must not boost a later slow detent */
    int step = flick > streak ? flick : streak, cap = rows / 16;
    return step > cap ? (cap > 1 ? cap : 1) : step;
}
#endif

int ringnav(void *ctx, void *event) {
    int result = stock_keyup(ctx, event);
    if (result || !event) return result;
    unsigned key = (unsigned)I(event, 0x18);
    if (key != KEY_CENTER && key != KEY_PREV && key != KEY_NEXT) return result;
#ifdef RINGNAV_IPOD
    void *card = btcard_find();
    if (card) { /* the connect card takes the press: it only closes */
        window_close(card);
        return STOP;
    }
#endif
#ifdef RINGNAV_IPOD
    if (!dialog_usable() || (!usable() && !dialog_of(window_manager_get_top_window(window_manager()))))
        return result; /* pop-ups also work while the USB cable is in */
#else
    if (!usable()) return result;
#endif
    /* Match the stock power-key release exclusions, including release after long press. */
    if (key == KEY_CENTER &&
        (g_power_longkey || g_ingore_bootkey_flag || *(volatile unsigned char *)0xa37c8a))
        return result;
    unsigned now = key == KEY_CENTER ? (unsigned)time_now_ms() : 0;
    /* Second release of a double click: the stock short press toggles the screen. Checked before
     * the animation guard, because the first press usually opened a page that is still sliding in. */
    if (now && center.last) {
        unsigned gap = now - center.last;
        /* Faster than any human double press: the same physical release delivered again. */
        if (gap < DUPLICATE_MS) return STOP;
        /* Second release while the first click still waits: drop it, stock toggles the screen. A
         * timer that somehow never fired can't turn every later press into a double. */
        if (center.timer && gap <= 2 * DOUBLE_CLICK_MS) {
            cancel_click();
            center.last = 0;
            return result;
        }
    }
    void *wm = window_manager(), *top = window_manager_get_top_window(wm);
#ifdef RINGNAV_IPOD
    void *out[DIALOG_MAX], *d = dialog_of(top);
    int dn = d ? dialog_targets(d, out, 0, 0) : 0;
    if (dn) {
        if (window_manager_is_animating(wm) || window_manager_get_pointer_pressed(wm)) return STOP;
        cancel_click();
        if (key == KEY_CENTER) {
            center.last = now;
            center.timer = timer_add(click_later, (void *)0, DOUBLE_CLICK_MS);
            return STOP;
        }
        center.last = 0;
        int sel = widget_get_prop_int(d, DSEL, 0) + (key == KEY_NEXT ? 1 : -1);
        widget_set_prop_int(d, DSEL, sel < 0 ? 0 : sel >= dn ? dn - 1 : sel);
        dialog_apply(d, out);
        return STOP;
    }
    if (!usable()) return result;
#endif
    if (!top || !allowed(widget_get_prop_str(top, "name", (void *)0))) return result;
    if (window_manager_is_animating(wm) || window_manager_get_pointer_pressed(wm)) return STOP;
    void *w = surface();
    int dir = key == KEY_NEXT ? 1 : key == KEY_PREV ? -1 : 0;
    if (!w) return dir ? STOP : result;
    menu_t m;
    if (!load(&m, w)) return dir ? STOP : result;
    int touch = widget_get_prop_int(w, TOUCH, 0);
    if (touch) stop_scroll(&m);
    int cur = reconcile(&m, touch || !moving(&m));
    if (!dir) {
        /* Hold the click for the double-press window; armed even with nothing to select, so a
         * double press always reaches stock. */
        cancel_click();
        center.last = now;
        center.timer = timer_add(click_later, (void *)0, DOUBLE_CLICK_MS);
        return STOP;
    }
    /* A wheel detent ends the double-press window and drops a click still waiting on it. */
    cancel_click();
    center.last = 0;
    prop(w, TOUCH, 0);
#ifdef RINGNAV_IPOD
    if (m.kind != 3 && head_key(&m, dir)) {
        ipod_apply();
        widget_invalidate_force(w, (void *)0);
        return STOP;
    }
#endif
    int step = 1;
#ifdef RINGNAV_ACCEL
    step = accel_step(dir, m.n ? m.rows : 0);
#ifdef RINGNAV_IPOD
    if (step >= LETTER_STEP) letter_poke();
#endif
#endif
    if (m.kind == 3) {
        if (dir > 0)
            slide_menu_scroll_to_next(w);
        else
            slide_menu_scroll_to_prev(w);
    } else if (m.n) {
        int id = widget_get_prop_int(w, SEL, -1);
        int next = id < 0 ? (cur >= 0 ? m.id[cur] : 0) : id + dir * step;
        if (step > 1) /* an accelerated jump stops at the end instead of being refused */
            next = next < 0 ? 0 : next >= m.rows ? m.rows - 1 : next;
        if (next < 0 || next >= m.rows || (step > 1 && next == id)) return STOP;
        int y, h;
        if (m.kind == 2) {
            y = next / PER(&m) * m.row;
            h = m.row;
        } else {
            rect_t r = bounds(&m, next);
            y = r.y + m.top;
            h = r.h;
        }
        int want = y < m.top ? y : y + h > m.top + m.height ? y + h - m.height : m.top;
        want = clamp_step(want, (m.kind == 2 ? m.rows / PER(&m) * m.row : I(w, 0x7c)) - m.height, 0);
        prop(w, SEL, next);
        /* Reversing into the current viewport must cancel the previous glide away from it. */
        if (want == m.top && moving(&m)) stop_scroll(&m);
        if (want != m.top) {
            if (m.kind == 2) {
                stop_scroll(&m);
                table_client_set_yoffset(w, want);
            } else
                scroll_view_scroll_delta_to(w, 0, want - m.top, GLIDE_MS);
        }
    } else {
        int max = (m.kind == 2 ? m.rows / PER(&m) * m.row : I(w, 0x7c)) - m.height;
        int next = clamp_step(m.top, max, dir * RING_STEP * step);
        if (m.kind == 2) {
            stop_scroll(&m);
            table_client_set_yoffset(w, next);
        } else if (next != m.top)
            scroll_view_scroll_delta_to(w, 0, next - m.top, GLIDE_MS);
    }
#ifdef RINGNAV_IPOD
    ipod_apply(); /* Move the blue bar before this detent's frame paints. */
#endif
    widget_invalidate_force(w, (void *)0);
    return STOP;
}
