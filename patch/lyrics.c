/* iPod Now Playing's lyrics page (docs/ipod.md#lyrics, docs/internals.md#word-timed-lyrics): large
 * lines, the playing one in the middle, lit word by word as it is sung. Stock's rows
 * stay, one blank label a line as high as it, so its scroll view, the wheel and the follow move
 * them as before (navigation.c); each row's line is painted over it here. */
#include "offsets.inc"
#include "peq.h"
#if IPOD

/* Every line LYRIC_PX, as large as reads well in the page's width, as many rows as it takes up to
 * LYRIC_ROWS (the rest cut; so many still fit the page), LY_PITCH apart; its row on the page is
 * those rows plus LYRIC_GAP, LYRIC_SLOT for one. */
#define LYRIC_PX 34
#define LYRIC_ROWS 4
#define LY_PITCH(px) ((px) + (px) / 8)
#define LYRIC_GAP (LYRIC_SLOT - LY_PITCH(LYRIC_PX))

typedef struct {
    int ms;                       /* its start, LRC_FAR when unsynced */
    unsigned text, n;             /* its characters, text[text..text + n) */
    unsigned mark, marks;         /* its word stamps, mark[mark..mark + marks) */
    unsigned char px, rows, face; /* its layout (px 0 until then): rows of LYRIC_W; face, ly_face */
    unsigned short start[LYRIC_ROWS], len[LYRIC_ROWS], w[LYRIC_ROWS];
} ly_line;
typedef struct {
    int ms;
    unsigned at; /* a word from this character, at ms */
} ly_mark;
typedef struct {
    unsigned n, sum; /* sum: ly_sum of its lines, as the rows' labels hold them */
    ly_line *line;
    ly_mark *mark;
    unsigned *text;
    unsigned short *adv; /* each character's advance at its line's px */
} ly_tab;

/* The rows' table, their scroll view, their count and ly_sum; the position the last pass saw, its
 * line (the first of those starting then, -1 before the first) and that line's lit width; and the
 * clock (lyrics_now). next: the loader's latest table, until rows that match it take it. Zero
 * filled, as all the payload's state (patch/link.ld). */
static struct {
    ly_tab *tab, *next;
    void *lrc;
    unsigned rows, sum;
    int ms, cur, fill;
    int sec, run, guess, lo, hi, pos;
} ly;

/* A line's share of the rows' FNV-1a: its stock seconds and its characters. */
static unsigned ly_sum(unsigned h, int ms, const unsigned *s, unsigned n) {
    h = (h ^ (unsigned)(ms == LRC_FAR ? ms : ms / 1000)) * 16777619u;
    while (n--) h = (h ^ *s++) * 16777619u;
    return (h ^ 0x10000u) * 16777619u; /* the line's end */
}

static ly_tab *ly_alloc(unsigned n, unsigned marks, unsigned chars) {
    ly_tab *t = calloc(1, sizeof *t + n * sizeof *t->line + marks * sizeof *t->mark +
                              chars * (sizeof *t->text + sizeof *t->adv));
    if (!t) return 0;
    t->n = n, t->sum = 2166136261u;
    t->line = (ly_line *)(t + 1);
    t->mark = (ly_mark *)(t->line + n);
    t->text = (unsigned *)(t->mark + marks);
    t->adv = (unsigned short *)(t->text + chars);
    return t;
}

/* The loader's lines (navigation.c ringnav_lyric, on the player's thread), as it put them in
 * stock's list: the next table, for the rows built from them. */
void lyrics_publish(const lrc_line *l, unsigned n, const lrc_mark *m) {
    unsigned marks = 0, chars = 0;
    for (unsigned i = 0; i < n; ++i) {
        marks += l[i].marks;
        for (unsigned at = 0, len = strlen(l[i].text); at < len; ++chars)
            book_char((const unsigned char *)l[i].text, len, &at);
    }
    ly_tab *t = n ? ly_alloc(n, marks, chars) : 0;
    for (unsigned i = 0, c = 0, k = 0; t && i < n; ++i) {
        const unsigned char *s = (const unsigned char *)l[i].text;
        const lrc_mark *w = m + l[i].mark, *end = w + l[i].marks;
        ly_line *o = &t->line[i];
        o->ms = l[i].time, o->text = c, o->mark = k;
        for (unsigned at = 0, len = strlen((const char *)s);; ++o->n) {
            for (; w < end && w->at <= at; ++w) t->mark[k++] = (ly_mark){ w->ms, o->n };
            if (at >= len) break;
            t->text[c++] = book_char(s, len, &at);
        }
        o->marks = k - o->mark;
        t->sum = ly_sum(t->sum, o->ms, t->text + o->text, o->n);
    }
    pthread_mutex_lock((void *)MCL_LYRIC_LOCK);
    free(ly.next);
    ly.next = t;
    pthread_mutex_unlock((void *)MCL_LYRIC_LOCK);
}

/* The loader's table, when it is the rows': theirs from now on. */
static int ly_take(void) {
    ly_tab *t = 0;
    pthread_mutex_lock((void *)MCL_LYRIC_LOCK);
    if (ly.next && ly.next->n == ly.rows && ly.next->sum == ly.sum) t = ly.next, ly.next = 0;
    pthread_mutex_unlock((void *)MCL_LYRIC_LOCK);
    if (!t) return 0;
    free(ly.tab);
    ly.tab = t, ly.cur = -1;
    return 1;
}

/* Now Playing went: its rows' memory may hold the next page's, which have none of the page's own.
 */
void lyrics_gone(void) { ly.lrc = 0, ly.rows = 0, ly.cur = -1; }

int lyrics_on(void *lrc) {
    return lrc && lrc == ly.lrc && ly.tab && ly.rows &&
           (unsigned)widget_count_children(lrc) == ly.rows;
}

#define LYRIC_W (375 - 2 * LYRIC_X)
/* A line all of whose characters Inter Display ExtraBold holds, as tools/build.py's LYRIC_FONT
 * subsets it (Latin, its curly quotes, dashes, bullet and ellipsis), is drawn in it ("lyric"),
 * Apple Music's weight; any other line in the system font, drawn LYRIC_BOLD more times a pixel
 * right for weight. */
#define LYRIC_FACE "lyric"
#define LYRIC_BOLD 1
static int ly_inter(unsigned c) {
    return (c >= 0x20 && c < 0x7f) || (c >= 0xa0 && c < 0x180 && c != 0xad && c != 0x149) ||
           c == 0x2013 || c == 0x2014 || (c >= 0x2018 && c <= 0x201e) || c == 0x2022 ||
           c == 0x2026 || c == 0x2032 || c == 0x2033;
}
static const char *ly_face(const ly_line *l) { return l->face ? LYRIC_FACE : (const char *)0; }
static int ly_cjk(unsigned c) {
    return (c >= 0x2e80 && c < 0xa000) || (c >= 0xac00 && c < 0xd7b0) ||
           (c >= 0xff00 && c < 0xfff0);
}

/* Line l's rows at its advances: breaking before a space (which goes) or beside a CJK character,
 * else mid-word; up to LYRIC_ROWS kept. How many it takes. */
static int ly_wrap(ly_line *l, const unsigned *s, const unsigned short *adv) {
    int rows = 0;
    for (unsigned i = 0; i < l->n;) {
        while (i < l->n && s[i] == ' ') ++i;
        if (i >= l->n) break;
        unsigned start = i, brk = 0, resume = 0;
        int x = 0, wbrk = 0;
        for (; i < l->n; x += adv[i++]) {
            if (s[i] == ' ')
                brk = i, wbrk = x, resume = i + 1;
            else if (i > start && (ly_cjk(s[i]) || ly_cjk(s[i - 1])))
                brk = i, wbrk = x, resume = i;
            if (i > start && x + adv[i] + (l->face ? 0 : LYRIC_BOLD) > LYRIC_W) break;
        }
        unsigned end = i;
        if (i < l->n && brk > start) end = brk, x = wbrk, i = resume;
        while (end > start && s[end - 1] == ' ') x -= adv[--end];
        if (rows < LYRIC_ROWS) l->start[rows] = start, l->len[rows] = end - start, l->w[rows] = x;
        ++rows;
    }
    return rows;
}

static void ly_layout(void *canvas, ly_line *l) {
    const unsigned *s = ly.tab->text + l->text;
    unsigned short *adv = ly.tab->adv + l->text;
    l->face = 1;
    for (unsigned k = 0; k < l->n; ++k) l->face &= ly_inter(s[k]);
    canvas_set_font(canvas, ly_face(l), LYRIC_PX); /* else the system default font */
    for (unsigned k = 0; k < l->n; ++k)
        adv[k] = (unsigned short)(canvas_measure_text(canvas, s + k, 1) + 0.5f);
    int rows = ly_wrap(l, s, adv);
    l->px = LYRIC_PX, l->rows = rows < LYRIC_ROWS ? rows : LYRIC_ROWS;
}

/* Stock built lrc's rows (navigation.c ringnav_lyric_rows), a label a line: their table is the
 * loader's for those lines, else the last one, else one made from the labels (stock's text and
 * whole seconds, without word stamps). Each becomes a blank row as high as its line's rows plus
 * LYRIC_GAP, laid out with the canvas's font, which the list layout puts after a blank LYRIC_SLOT.
 */
int lyrics_rows(void *lrc) {
    unsigned n = widget_count_children(lrc), chars = 0, sum = 2166136261u;
    for (unsigned i = 0; i < n; ++i) {
        void *row = widget_get_child(lrc, i);
        const unsigned *s = widget_get_text(row);
        unsigned k = 0;
        while (s && s[k]) ++k;
        int sec = widget_get_prop_int(row, "lrc_time", LRC_FAR);
        sum = ly_sum(sum, sec >= LRC_FAR / 1000 ? LRC_FAR : sec * 1000, s, k);
        chars += k;
    }
    ly.lrc = lrc, ly.rows = n, ly.sum = sum, ly.cur = -1;
    if (n && !ly_take() && !(ly.tab && ly.tab->n == n && ly.tab->sum == sum)) {
        free(ly.tab);
        ly_tab *t = ly.tab = ly_alloc(n, 0, chars);
        for (unsigned i = 0, c = 0; t && i < n; ++i) {
            void *row = widget_get_child(lrc, i);
            int sec = widget_get_prop_int(row, "lrc_time", LRC_FAR);
            ly_line *o = &t->line[i];
            o->ms = sec >= LRC_FAR / 1000 ? LRC_FAR : sec * 1000, o->text = c;
            for (const unsigned *s = widget_get_text(row); s && *s; ++s, ++o->n) t->text[c++] = *s;
        }
        if (t) t->sum = sum;
    }
    if (!lyrics_on(lrc)) return 0; /* none, or out of memory: stock's rows stay */
    void *canvas = widget_get_canvas(lrc);
    for (unsigned i = 0; i < n; ++i) {
        void *row = widget_get_child(lrc, i);
        ly_line *l = &ly.tab->line[i];
        if (canvas && !l->px) ly_layout(canvas, l);
        widget_set_text_utf8(row, "");
        widget_resize(row, I(lrc, W_W),
                      (l->rows > 1 ? l->rows : 1) * LY_PITCH(LYRIC_PX) + LYRIC_GAP);
    }
    widget_layout_children(lrc);
    return 1;
}

/* The playing position, ms. The player reports whole seconds, which stock polls every 200 ms
 * (mclSyncPlayerStatus): the second's change one on from the last, while playing, puts the position
 * up to LYRIC_POLL_MS past it, and those bounds (of its offset from time_now_ms) narrow with each
 * change; another change (a seek, another song) starts them again, anywhere in that second. Paused,
 * it stays, and on Play goes on from there until the next change. Never more than a poll past its
 * second. */
#define LYRIC_POLL_MS 250
int lyrics_now(void) {
    int sec = -1, total = 0, playing = mclGetPlayStatus() == 2;
    unsigned now = (unsigned)time_now_ms();
    player_playtime_and_length(&sec, &total);
    if (sec < 0) {
        ly.sec = -1, ly.run = 0;
        return ly.pos = 0;
    }
    int lo = (int)((unsigned)sec * 1000u - now), base = sec * 1000;
    if (!playing) {
        ly.run = 0;
    } else if (ly.run && sec == ly.sec + 1) {
        int hi = lo + LYRIC_POLL_MS;
        if (ly.guess || lo > ly.hi || hi < ly.lo)
            ly.lo = lo, ly.hi = hi;
        else
            ly.lo = lo > ly.lo ? lo : ly.lo, ly.hi = hi < ly.hi ? hi : ly.hi;
        ly.guess = 0, ly.sec = sec;
    } else if (!ly.run && sec == ly.sec && ly.pos >= base) {
        ly.lo = ly.hi = (int)((unsigned)ly.pos - now);
        ly.guess = ly.run = 1;
    } else if (!ly.run || sec != ly.sec) {
        ly.lo = lo, ly.hi = lo + 999 + LYRIC_POLL_MS;
        ly.guess = 0, ly.run = 1;
    }
    ly.sec = sec;
    int pos = ly.run ? (int)(now + (unsigned)(ly.lo + (ly.hi - ly.lo) / 2)) : ly.pos,
        last = base + 999 + (ly.run ? LYRIC_POLL_MS : 0);
    return ly.pos = pos < base ? base : pos > last ? last : pos;
}

/* The line playing at ms: the first of those that start when the last started does; -1 before. */
static int ly_line_at(int ms) {
    int cur = -1;
    for (unsigned i = 0; i < ly.tab->n && ly.tab->line[i].ms <= ms; ++i)
        if (ly.tab->line[i].ms != LRC_FAR &&
            (cur < 0 || ly.tab->line[i].ms != ly.tab->line[cur].ms))
            cur = (int)i;
    return cur;
}

/* Character c's distance along line l's rows, laid end to end. */
static int ly_along(const ly_line *l, unsigned c) {
    const unsigned short *adv = ly.tab->adv + l->text;
    int x = 0;
    for (unsigned r = 0; r < l->rows; x += l->w[r++]) {
        if (c < l->start[r]) return x;
        if (c < (unsigned)l->start[r] + l->len[r]) {
            for (unsigned k = l->start[r]; k < c; ++k) x += adv[k];
            return x;
        }
    }
    return x;
}

/* How long line l takes sung from character a: LYRIC_UNIT_MS a letter, three a CJK character (a
 * syllable), LYRIC_MIN_MS at least: a word-timed line's last word, when no stamp ends it. */
#define LYRIC_UNIT_MS 90
#define LYRIC_MIN_MS 800
static int ly_sung(const ly_line *l, unsigned a) {
    int units = 0;
    for (const unsigned *s = ly.tab->text + l->text; a < l->n; ++a)
        units += ly_cjk(s[a]) ? 3 : s[a] > ' ' && s[a] != ',' && s[a] != '.' ? 1 : 0;
    return units * LYRIC_UNIT_MS > LYRIC_MIN_MS ? units * LYRIC_UNIT_MS : LYRIC_MIN_MS;
}

/* Line i's lit width at ms (laid out). A line timed by the word (A2's stamps) lights from stamp to
 * stamp, past the last at the sung pace, done by the time the next line starts; a line timed only
 * by itself lights whole as it starts. */
static int ly_lit(unsigned i, int ms) {
    const ly_line *l = &ly.tab->line[i];
    int full = 0, t0 = l->ms, x0 = 0, next = LRC_FAR;
    for (unsigned r = 0; r < l->rows; ++r) full += l->w[r];
    if (ms < t0) return 0;
    if (!l->marks) return full;
    for (unsigned k = i + 1; k < ly.tab->n && next == LRC_FAR; ++k)
        if (ly.tab->line[k].ms > l->ms) next = ly.tab->line[k].ms;
    for (unsigned k = 0, c = 0; k <= l->marks; ++k) {
        int t1, x1;
        if (k < l->marks) {
            const ly_mark *w = &ly.tab->mark[l->mark + k];
            t1 = w->ms < t0 ? t0 : w->ms, x1 = ly_along(l, w->at), c = w->at;
        } else {
            if (x0 >= full) break;
            t1 = t0 + ly_sung(l, c), x1 = full;
            if (t1 > next) t1 = next;
        }
        if (ms < t1) return x0 + (x1 - x0) * (ms - t0) / (t1 - t0);
        t0 = t1, x0 = x1;
    }
    return full;
}

/* Line k's rows and those of the lines starting with it, repainted. */
static void ly_dirty(void *lrc, int k) {
    for (int at = k; k >= 0 && (unsigned)k < ly.rows && ly.tab->line[k].ms == ly.tab->line[at].ms;
         ++k)
        widget_invalidate_force(widget_get_child(lrc, k), (void *)0);
}

/* Every UI pass on Now Playing (navigation.c lyric_poll), at ms: the loader's table if it came
 * after the rows, and the playing line, which the follow centres. While the lyrics page shows
 * (page) the playing rows repaint as their lit width moves, and the last ones as it moves on. */
int lyrics_line(void *lrc, int ms, int page) {
    if (ly.next && lrc == ly.lrc) ly_take();
    if (!lyrics_on(lrc)) return -1;
    int cur = ly_line_at(ms),
        fill = cur >= 0 && ly.tab->line[cur].px ? ly_lit((unsigned)cur, ms) : -1;
    if (page && (cur != ly.cur || fill != ly.fill || fill < 0)) {
        if (cur != ly.cur) ly_dirty(lrc, ly.cur);
        ly_dirty(lrc, cur);
    }
    ly.ms = ms, ly.cur = cur, ly.fill = fill;
    return cur;
}

/* One row of text clipped to from..to (the row's x) within its own clip (base). */
static void ly_ink(void *canvas, const int *base, const unsigned *s, unsigned n, int y, int from,
                   int to, unsigned color, int bold) {
    int x = I(canvas, CANVAS_X),
        clip[4] = { x + from > base[0] ? x + from : base[0], base[1], 0, base[3] };
    clip[2] = (x + to < base[0] + base[2] ? x + to : base[0] + base[2]) - clip[0];
    if (clip[2] <= 0 || clip[3] <= 0) return;
    canvas_set_clip_rect(canvas, clip);
    canvas_set_text_color(canvas, color);
    for (int b = 0; b <= bold; ++b) canvas_draw_text(canvas, s, n, LYRIC_X + b, y);
}

/* ringnav_paint, after stock painted a lyrics row (blank): its line, centred in it, in its face
 * (ly_face), LYRIC_LIT as far as it is sung while it plays and LYRIC_DIM past that; any other line
 * LYRIC_REST. A row the page's edge cuts fades with the square of the share of it out of view, so
 * no sliver of a line shows. The text color and clip are restored, the font is not. */
void lyrics_paint(void *row, void *canvas) {
    void *lrc = row ? P(row, W_PARENT) : (void *)0;
    int i = -1, base[4];
    if (!lyrics_on(lrc) || !P(canvas, CANVAS_LCD)) return;
    while (++i < (int)ly.rows && widget_get_child(lrc, i) != row) {}
    if (i >= (int)ly.rows) return;
    int top = I(row, W_Y) - I(lrc, SCROLL_Y), h = I(row, W_H), view = I(lrc, W_H),
        seen = (top + h < view ? top + h : view) - (top > 0 ? top : 0),
        alpha = seen >= h  ? 255
                : seen > 0 ? 255 * seen * seen / (h * h)
                           : 0;
    if (alpha < 8) return;
    ly_line *l = &ly.tab->line[i];
    if (!l->px) ly_layout(canvas, l);
    int on = ly.cur >= 0 && l->ms == ly.tab->line[ly.cur].ms,
        lit = on ? ly_lit((unsigned)i, ly.ms) : 0, pitch = LY_PITCH(l->px),
        y = (h - l->rows * pitch) / 2 + (pitch - l->px) / 2, w = I(row, W_W),
        bold = l->face ? 0 : LYRIC_BOLD;
    unsigned text = (unsigned)I(P(canvas, CANVAS_LCD), LCD_TEXT_COLOR);
    canvas_get_clip_rect(canvas, base);
    canvas_set_font(canvas, ly_face(l), l->px);
    for (unsigned r = 0; r < l->rows; lit -= l->w[r++], y += pitch) {
        const unsigned *s = ly.tab->text + l->text + l->start[r];
        int cut = lit <= 0 ? LYRIC_X : lit >= l->w[r] ? w : LYRIC_X + lit;
        if (cut < w)
            ly_ink(canvas, base, s, l->len[r], y, cut, w, rgba(on ? LYRIC_DIM : LYRIC_REST, alpha),
                   bold);
        if (cut > LYRIC_X)
            ly_ink(canvas, base, s, l->len[r], y, 0, cut, rgba(LYRIC_LIT, alpha), bold);
    }
    canvas_set_clip_rect(canvas, base);
    canvas_set_text_color(canvas, text);
}
#endif
