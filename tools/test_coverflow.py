#!/usr/bin/env python3
"""Run patch/coverflow.c's art cache on the host: the library query, the modal art build on a real
pthread, the stock art calls and their locks. Built 32-bit (-m32, like test_peq.py's player) so the
stSongInfo pointer offsets hold. The stock calls are stubbed; UI widgets are plain records."""
import pathlib
import subprocess
import tempfile
from build import FUNCTIONS
from peq import LIBC

PROTOTYPES = {**FUNCTIONS, **LIBC}  # the stock calls the host shims stand in for

ROOT = pathlib.Path(__file__).resolve().parents[1]

SHIM_H = r"""
#include <dirent.h>
#include <pthread.h>
#include <sys/stat.h>
typedef int (*handler)(void *, void *);
extern pthread_mutex_t shim_parse, shim_play;
extern void *shim_dir;
#define parse_cover_mutex ((const unsigned char *)&shim_parse)
#define g_playcover_mutex ((const unsigned char *)&shim_play)
#define tools_pdeq_directory ((const unsigned char *)&shim_dir)
#define pthread_mutex_lock shim_lock
#define pthread_mutex_unlock shim_unlock
#define statfs shim_statfs
#define tk_snprintf snprintf
extern void *shim_queue;
extern unsigned char shim_covertype;
extern char shim_lastcover[1024];
#define mcl_pdeqplaylist ((const unsigned char *)&shim_queue)
#define g_lastcover_url ((const unsigned char *)shim_lastcover)
#define g_playcover_type shim_covertype
int shim_lock(void *), shim_unlock(void *), shim_statfs(const char *, void *);
""" + ''.join(f'{r} {n}({a});\n' for n in """
getAllAlbum getMusicByAlbum toolsThumbSpecCover toolsGetAlbumCover _create_deque deque_init_copy deque_clear
deque_assign deque_destroy deque_size deque_at window_create widget_factory
widget_factory_create_widget image_create hscroll_label_create set_hscroll_label_attribute
slide_menu_set_value slide_menu_item_width slide_menu_on_scroll_done slide_menu_scroll_to
widget_ungrab list_view_create scroll_view_create list_item_create image_set_draw_type
image_base_set_image widget_load_image widget_unload_image widget_set_name widget_use_style
widget_set_text_utf8 widget_set_visible widget_get_prop_int widget_set_prop_int
widget_get_prop_str widget_on widget_destroy_children widget_invalidate_force
widget_count_children widget_get_child widget_lookup widget_move_resize widget_get_visible
canvas_get_clip_rect canvas_set_clip_rect widget_set_sensitive widget_get_type tk_strcmp
timer_add timer_remove navigator_back_to_home navigator_to_with_context window_manager
window_manager_get_pointer_pressed bitmap_create_ex bitmap_destroy bitmap_unlock_buffer
bitmap_lock_buffer_for_read bitmap_lock_buffer_for_write bitmap_get_line_length
canvas_draw_image slide_menu_set_spacer widget_to_local
""".split() for r, a in [PROTOTYPES[n]]) + r"""
void *shim_calloc(size_t, size_t);
#define calloc shim_calloc
"""

TEST = r"""
#include <assert.h>
#include <sys/mman.h>
#include "peq.h"
#include "offsets.inc"
#include <stdint.h>
#undef pthread_mutex_lock /* the stubs below record, then take the real lock */
#undef pthread_mutex_unlock
int coverflow_home(void *, void *);

/* Widgets: raw memory first, so the payload's field reads (SLIDE_INDEX) land in it. */
typedef struct { char raw[0x100]; int parent, visible, kids[512], nkids, bg; char type[32], text[160], image[600];
                 handler click; void *ctx; } widget;
static widget w[8192];
static int nw;
static widget *W(void *p) { return (widget *)p; }
static void *make(void *parent, const char *type) {
    widget *x = &w[++nw];
    memset(x, 0, sizeof(*x));
    x->visible = 1;
    snprintf(x->type, sizeof(x->type), "%s", type);
    if (parent) { x->parent = (int)(W(parent) - w); W(parent)->kids[W(parent)->nkids++] = nw; *(void **)(x->raw + W_PARENT) = parent; }
    return x;
}
static void *placed(void *x, int left, int top, int ww, int h) {
    int *r = (int *)W(x)->raw; /* W_X, W_Y, W_W, W_H */
    r[0] = left; r[1] = top; r[2] = ww; r[3] = h;
    return x;
}
void *window_create(void *p, int x, int y, int ww, int h) { (void)p; (void)x; (void)y; (void)ww; (void)h; return make(0, "window"); }
void *widget_factory(void) { return (void *)1; }
void *widget_factory_create_widget(void *f, const char *t, void *p, int x, int y, int ww, int h) { (void)f; return placed(make(p, t), x, y, ww, h); }
#define CREATE(name, type) void *name(void *p, int x, int y, int ww, int h) { return placed(make(p, type), x, y, ww, h); }
CREATE(image_create, "image") CREATE(list_view_create, "list_view")
CREATE(hscroll_label_create, "hscroll_label")
CREATE(scroll_view_create, "scroll_view") CREATE(list_item_create, "list_item")
int image_set_draw_type(void *x, int t) { (void)x; (void)t; return 0; }
int image_base_set_image(void *x, const char *s) { snprintf(W(x)->image, 600, "%s", s); return 0; }
/* A zero-length "no art" marker does not decode. Every successful load is unloaded again and
   decodes to art_w x art_h (bitmap_t w @0, h @4). */
static int loads, unloads;
static unsigned art_w = 160, art_h = 160;
/* Decoded art (bitmap_t w @0, h @4, line length @8, format @0xe, and here the pixels @0x14):
   RGBA8888, a pattern whose colour comes from the file's path, so every album looks different. */
static unsigned char pixels[16][160 * 160 * 4];
static int next_pixels, reads;
static void pattern(unsigned char *px, unsigned seed) {
    static const unsigned char hue[8][3] = { { 214, 68, 58 }, { 58, 140, 214 }, { 236, 180, 50 }, { 90, 176, 96 },
                                             { 150, 90, 200 }, { 230, 120, 170 }, { 60, 190, 190 }, { 200, 200, 200 } };
    const unsigned char *c = hue[seed % 8];
    for (int y = 0; y < 160; ++y)
        for (int x = 0; x < 160; ++x) {
            int dx = x - 80, dy = y - 80, ring = dx * dx + dy * dy, k = 120 + (x + y) * 135 / 318;
            if (ring < 30 * 30 && ring > 22 * 22) k = 40; /* a ring, off-centre text-like bars */
            if (y > 118 && y < 128 && x > 20 && x < 20 + (int)(seed * 37 % 100)) k = 255;
            if (x < 4 || y < 4 || x > 155 || y > 155) k = 255 - k / 2;
            for (int i = 0; i < 3; ++i) px[4 * (y * 160 + x) + i] = c[i] * k / 255;
            px[4 * (y * 160 + x) + 3] = 255;
        }
}
int widget_load_image(void *x, const char *url, void *b) {
    (void)x; struct stat s;
    int failed = strncmp(url, "file://", 7) || stat(url + 7, &s) || !s.st_size;
    loads += !failed;
    if (!failed) {
        unsigned *bm = b, seed = 0;
        for (const char *c = strrchr(url, '/'); *c; ++c) seed = seed * 31 + (unsigned char)*c; /* the key, not the scratch path */
        unsigned char *px = pixels[next_pixels++ % 16];
        pattern(px, seed % 1000);
        bm[0] = art_w, bm[1] = art_h, bm[2] = art_w * 4;
        ((unsigned short *)b)[7] = 1; /* RGBA8888 */
        *(unsigned char **)((char *)b + 0x14) = px;
    }
    return failed;
}
const unsigned char *bitmap_lock_buffer_for_read(void *b) { ++reads; return *(unsigned char **)((char *)b + 0x14); }
int widget_unload_image(void *x, void *b) { (void)x; (void)b; ++unloads; return 0; }
void set_hscroll_label_attribute(void *x) { assert(!strcmp(W(x)->type, "hscroll_label")); }
int slide_menu_set_value(void *x, int value) { *(int *)(W(x)->raw + SLIDE_INDEX) = value; return 0; }
int widget_set_name(void *x, const char *s) { snprintf(W(x)->type, 32, "%s", s); return 0; }
int widget_use_style(void *x, const char *s) { (void)x; (void)s; return 0; }
int widget_set_text_utf8(void *x, const char *s) { snprintf(W(x)->text, 160, "%s", s); return 0; }
int widget_set_visible(void *x, int v, int r) { (void)r; W(x)->visible = v; return 0; }
int widget_get_prop_int(void *x, const char *k, int d) { (void)x; (void)k; return d; }
int widget_set_prop_int(void *x, const char *k, int v) { if (!strcmp(k, "style:normal:bg_color")) W(x)->bg = v; return 0; }
const char *widget_get_prop_str(void *x, const char *k, const char *d) { return strcmp(k, "image") ? d : W(x)->image; }
unsigned widget_on(void *x, unsigned type, handler f, void *ctx) {
    if (!x) return 0;
    if (type == EVT_CLICK || type == EVT_KEY_UP || type == EVT_DESTROY || type == EVT_POINTER_UP_BEFORE) {
        widget *h = type == EVT_CLICK ? W(x) : &w[0] + (type == EVT_KEY_UP ? 8190 : type == EVT_DESTROY ? 8191 : 8189); /* page handlers */
        h->click = f; h->ctx = ctx;
    }
    return 1;
}
int widget_destroy_children(void *x) { W(x)->nkids = 0; return 0; }
int widget_invalidate_force(void *x, void *y) { (void)x; (void)y; return 0; }
unsigned widget_count_children(void *x) { return W(x)->nkids; }
void *widget_get_child(void *x, unsigned i) { return &w[W(x)->kids[i]]; }
static void *home_art, *home_list; /* iPod Home's art and list; none in the carousel tests */
void *widget_lookup(void *x, const char *n, int r) {
    (void)r;
    return !x ? 0 : !strcmp(n, "img_coverflow") ? x : !strcmp(n, "img_homeart") ? home_art :
           !strcmp(n, "list_view_home") ? home_list : 0;
}
static int home_full;
int ipod_home_full(void) { return home_full; }
int widget_move_resize(void *x, int left, int top, int ww, int h) {
    int *r = (int *)W(x)->raw; /* W_X, W_Y, W_W, W_H */
    r[0] = left; r[1] = top; r[2] = ww; r[3] = h;
    return 0;
}
static int insensitive; /* the widget last made insensitive */
int widget_set_sensitive(void *x, int v) { if (!v) insensitive = W(x) - w; return 0; }
static int clip_rect[4] = { 0, 0, 375, 320 }; /* the canvas clip, screen x, y, w, h */
int canvas_get_clip_rect(void *c, void *r) { (void)c; memcpy(r, clip_rect, sizeof clip_rect); return 0; }
int canvas_set_clip_rect(void *c, const void *r) { (void)c; memcpy(clip_rect, r, sizeof clip_rect); return 0; }
const char *widget_get_type(void *x) { return W(x)->type; }
int widget_get_visible(void *x) { return W(x)->visible; }
int tk_strcmp(const char *a, const char *b) { return strcmp(a ? a : "", b ? b : ""); }
int navigator_back_to_home(void) { return 0; }
int navigator_to_with_context(const char *n, const void *c) { (void)n; (void)c; return 0; }
/* slide_menu: square items as high as the menu, plus the spacer; scroll_to records its goal and holds
   the animator slot. */
static int anim_from, anim_to, anims, ungrabs;
int slide_menu_item_width(void *x) { return *(int *)(W(x)->raw + W_H); }
int slide_menu_set_spacer(void *x, int v) { *(int *)(W(x)->raw + SLIDE_SPACER) = v; return 0; }
int slide_menu_on_scroll_done(void *x, void *e) {
    (void)e; char *r = W(x)->raw;
    int stride = slide_menu_item_width(x) + *(int *)(r + SLIDE_SPACER), n = (int)W(x)->nkids;
    *(int *)(r + SLIDE_INDEX) = ((*(int *)(r + SLIDE_INDEX) - *(int *)(r + SLIDE_OFFSET) / stride) % n + n) % n;
    *(int *)(r + SLIDE_OFFSET) = 0; *(void **)(r + SLIDE_ANIMATOR) = 0;
    return 0;
}
int slide_menu_scroll_to(void *x, int to) {
    ++anims; anim_from = *(int *)(W(x)->raw + SLIDE_OFFSET); anim_to = to;
    *(void **)(W(x)->raw + SLIDE_ANIMATOR) = &anim_from;
    return 0;
}
int widget_ungrab(void *p, void *c) { assert(W(c)->parent == W(p) - w); ++ungrabs; return 0; }
/* A point from the screen into the widget: less each ancestor's x, y. */
int widget_to_local(void *x, void *pt) {
    for (int *p = pt; x; x = *(void **)(W(x)->raw + W_PARENT)) p[0] -= *(int *)W(x)->raw, p[1] -= *(int *)(W(x)->raw + 4);
    return 0;
}
/* The frame bitmap (bitmap_t as above) and the canvas: canvas_draw_image keeps what it drew. */
static int frames, frame_fail, tex_fail, locks, draws, drawn[4];
static unsigned shown[CF_VIEW_H * CF_VIEW_W];
#undef calloc /* the payload's calloc is this shim; the tests' own is libc's */
void *calloc(size_t, size_t);
void *shim_calloc(size_t n, size_t size) { return tex_fail && size == 160 * 160 * 4 ? 0 : calloc(n, size); }
void *bitmap_create_ex(unsigned ww, unsigned h, unsigned line, unsigned format) {
    if (frame_fail) return 0;
    unsigned *b = calloc(1, 0x48);
    b[0] = ww, b[1] = h, b[2] = line, ((unsigned short *)b)[7] = format;
    *(unsigned char **)((char *)b + 0x14) = calloc(h, line);
    ++frames;
    return b;
}
int bitmap_destroy(void *b) { free(*(void **)((char *)b + 0x14)); free(b); --frames; return 0; }
unsigned char *bitmap_lock_buffer_for_write(void *b) { ++locks; return *(unsigned char **)((char *)b + 0x14); }
int bitmap_unlock_buffer(void *b) { (void)b; return 0; }
unsigned bitmap_get_line_length(void *b) { return ((unsigned *)b)[2]; }
int canvas_draw_image(void *c, void *b, const void *src, const void *dst) {
    (void)c; ++draws;
    const int *r = dst, *q = src;
    assert(!memcmp(r, q, 16) && ((unsigned short *)b)[6] & 1); /* 1:1, and marked opaque */
    memcpy(drawn, r, sizeof drawn);
    for (int y = 0; y < CF_VIEW_H; ++y) memcpy(shown + y * CF_VIEW_W, *(unsigned char **)((char *)b + 0x14) + y * ((unsigned *)b)[2], CF_VIEW_W * 4);
    return 0;
}
static int pressed;
void *window_manager(void) { return &pressed; }
int window_manager_get_pointer_pressed(void *wm) { return *(int *)wm; }
int stock_home_trampoline(void *win, void *ctx) { (void)win; (void)ctx; return 0; }
/* The songtable writers' stock bodies; during_write runs inside one, as an open mid-scan would. */
static void (*during_write)(void);
static int stock_write(void) { if (during_write) during_write(); return 0; }
int stock_scan_all_trampoline(void *a, void *b) { (void)a; (void)b; return stock_write(); }
int stock_scan_folder_trampoline(void *a, void *b) { (void)a; (void)b; return stock_write(); }
int stock_delete_song_trampoline(void *a, void *b) { (void)a; (void)b; return stock_write(); }
int coverflow_scan_all(void *, void *);
static void rescan(void) { coverflow_scan_all(0, 0); } /* the library changed, as only a scan changes it */

static int (*timer_fn)(const void *), (*last_fn)(const void *);
unsigned timer_add(int (*f)(const void *), void *ctx, unsigned ms) { (void)ctx; (void)ms; timer_fn = last_fn = f; return 1; }
int timer_remove(unsigned id) { (void)id; timer_fn = 0; return 0; }
void stop_timer(unsigned *t) { if (*t) timer_remove(*t); *t = 0; } /* ringnav.c's */
void rearm(unsigned *t, int (*f)(const void *), unsigned ms) { stop_timer(t); *t = timer_add(f, 0, ms); }
static void run(void) { while (timer_fn) { int (*f)(const void *) = timer_fn; timer_fn = 0; usleep(1000); f(0); } }

/* libcstl: a deque of record pointers; the query stubs fill the staging deque. */
typedef struct { unsigned n; void *at[64]; } deque;
void *shim_dir;
void *_create_deque(const char *t) { (void)t; return calloc(1, sizeof(deque)); }
void deque_init_copy(void *d, const void *s) { *(deque *)d = *(const deque *)s; }
void deque_assign(void *d, const void *s) { *(deque *)d = *(const deque *)s; }
void deque_clear(void *d) { ((deque *)d)->n = 0; }
void deque_destroy(void *d) { free(d); }
unsigned deque_size(const void *d) { return ((const deque *)d)->n; }
void *deque_at(const void *d, unsigned i) { return i < ((const deque *)d)->n ? ((const deque *)d)->at[i] : 0; }

static char records[64][0x60], names[64][64], paths[64][600];
static int albums, queries;
static void album(const char *name, const char *art) {
    char *r = records[albums], dir[500];
    snprintf(names[albums], 64, "%s", name);
    snprintf(dir, sizeof(dir), PEQ_ROOT "/music/%s", name);
    mkdir(dir, 0755);
    snprintf(paths[albums], 600, "%s/01.flac", dir);
    FILE *f = fopen(paths[albums], "w"); fclose(f);
    if (art) { snprintf(dir + strlen(dir), 100, "/%s", art); f = fopen(dir, "w"); fclose(f); }
    memset(r, 0, 0x60);
    *(int *)(r + REC_ID) = albums + 1;
    *(char **)(r + REC_ALBUM) = names[albums];
    *(char **)(r + REC_ARTIST) = "Artist";
    *(char **)(r + REC_PATH) = paths[albums++];
}
int getAllAlbum(void) {
    deque *d = shim_dir;
    ++queries;
    d->n = albums;
    for (int i = 0; i < albums; ++i) d->at[i] = records[i];
    return albums;
}
int getMusicByAlbum(const char *a) { (void)a; return 0; }

/* The stock art calls: each writes its source into dst, and checks the locks it runs under. */
pthread_mutex_t shim_parse = PTHREAD_MUTEX_INITIALIZER, shim_play = PTHREAD_MUTEX_INITIALIZER;
static int held[2], order[64], norder, calls, embedded_fails, block_at = -1, blocked;
static char made[64][600];
int shim_lock(void *m) {
    order[norder++] = m == &shim_parse ? 1 : 2;
    assert(!held[m == &shim_play]);
    held[m == &shim_play] = 1;
    return pthread_mutex_lock(m);
}
int shim_unlock(void *m) { held[m == &shim_play] = 0; return pthread_mutex_unlock(m); }
static int write_art(const char *dst, const char *what) {
    snprintf(made[calls++], 600, "%s", what);
    if (calls - 1 == block_at) { blocked = 1; while (blocked) usleep(1000); }
    FILE *f = fopen(dst, "w");
    fputs(what, f);
    return !fclose(f);
}
int toolsThumbSpecCover(const char *src, const char *dst, int ww, int h) {
    assert(ww == 160 && h == 160 && held[0] && !held[1] && strstr(dst, ".jpg.tmp"));
    return write_art(dst, strrchr(src, '/') + 1);
}
int toolsGetAlbumCover(const char *src, const char *dst, int ww, int h) {
    (void)src;
    assert(ww == 160 && h == 160 && held[0] && held[1] && strstr(dst, ".jpg.tmp"));
    return embedded_fails ? 0 : write_art(dst, "embedded");
}
static unsigned free_blocks = 1 << 20;
int shim_statfs(const char *p, void *out) {
    assert(!strcmp(p, PEQ_ROOT "/mnt/mmc/.coverflow"));
    unsigned *s = out;
    s[1] = 4096; s[7] = free_blocks; /* MIPS o32 statfs: f_bsize, f_bavail */
    return 0;
}

void *shim_queue;
unsigned char shim_covertype;
char shim_lastcover[1024];
static widget *page;
static void *release(void *unused) { (void)unused; usleep(50000); blocked = 0; return 0; }
static void open_page(void) {
    widget home;
    memset(&home, 0, sizeof(home));
    coverflow_home(&home, 0);
    page = &w[nw + 1];
    home.click(home.ctx, 0);
    run();
}
static void key(int k) { int e[16] = {0}; e[EVENT_KEY / 4] = k; w[8190].click(0, e); run(); }
static void close_page(void) { w[8191].click(0, 0); }
static void mid_write(void) { open_page(); close_page(); }
unsigned fnv(unsigned h, const unsigned char *s);
static int last_album(int i) { /* the card holds album i's key as the one to reopen on */
    unsigned key = 0;
    FILE *f = fopen(PEQ_ROOT "/mnt/mmc/.coverflow/album", "rb");
    int ok = f && fread(&key, sizeof(key), 1, f) == 1;
    if (f) fclose(f);
    return ok && key == fnv(fnv(FNV_SEED, (const unsigned char *)"Artist"), (const unsigned char *)names[i]);
}
static widget *slide(void) {
    for (int i = nw; i > page - w; --i) if (!strcmp(w[i].type, "slide_menu")) return &w[i];
    return 0;
}
static const char *title(void) {
    for (int i = nw; i > page - w; --i) if (!strcmp(w[i].type, "hscroll_label") && w[w[i].parent].parent == page - w) return w[i].text;
    return "";
}
static long size(const char *album_name) {
    char path[600];
    for (int i = 0; i < albums; ++i) {
        if (strcmp(names[i], album_name)) continue;
        unsigned h = 2166136261u;
        for (const unsigned char *s = (const unsigned char *)"Artist"; *s; ++s) h = (h ^ *s) * 16777619u;
        h *= 16777619u;
        for (const unsigned char *s = (const unsigned char *)names[i]; *s; ++s) h = (h ^ *s) * 16777619u;
        h *= 16777619u;
        snprintf(path, sizeof(path), PEQ_ROOT "/mnt/mmc/.coverflow/%08x.jpg", h);
        struct stat s;
        return stat(path, &s) ? -1 : s.st_size;
    }
    return -2;
}
static int tmp_files(void) {
    int n = 0;
    DIR *d = opendir(PEQ_ROOT "/mnt/mmc/.coverflow");
    for (struct dirent *e; d && (e = readdir(d));) n += strstr(e->d_name, ".tmp") != 0;
    if (d) closedir(d);
    return n;
}


/* ---- Depth: the renderer on its own, then on the page. ---- */
void coverflow_render(unsigned *, int, int, const unsigned *const[7]);
int coverflow_hit(int, int, int);
void coverflow_paint(void *, void *);
#define ONE 65536
#define PITCH (CF_VIEW_W + 5) /* guard columns, and guard rows below, to catch clipping errors */
static unsigned frame[(CF_VIEW_H + 3) * PITCH], flat[7][160 * 160], art[160 * 160];
static const unsigned colours[7] = { 0xff0000ffu, 0xff00ff00u, 0xffff0000u, 0xff00ffffu, 0xffffff00u, 0xffff00ffu, 0xff0080ffu };
static void render(int frac, const unsigned *const ring[7]) {
    for (unsigned i = 0; i < sizeof(frame) / 4; ++i) frame[i] = 0x12345678u;
    coverflow_render(frame, PITCH, frac, ring);
    for (int y = 0; y < CF_VIEW_H + 3; ++y)
        for (int x = 0; x < PITCH; ++x)
            assert((y < CF_VIEW_H && x < CF_VIEW_W) == (frame[y * PITCH + x] != 0x12345678u)); /* all of it, and only it */
}
static unsigned px(int x, int y) { return frame[y * PITCH + x]; }
static int ch(unsigned p, int i) { return (int)(p >> 8 * i & 255); }
/* The slot whose flat colour p is a shade of (by channel proportions), or -1. */
static int slot_of(unsigned p) {
    int m = ch(p, 0) > ch(p, 1) ? ch(p, 0) : ch(p, 1);
    m = m > ch(p, 2) ? m : ch(p, 2);
    for (int j = 0; m >= 24 && j < 7; ++j) {
        int ok = 1;
        for (int i = 0; i < 3; ++i) { int want = ch(colours[j], i) * m / 255; ok &= abs(ch(p, i) - want) <= 3 + m / 40; }
        if (ok) return j;
    }
    return -1;
}
static int differ(const unsigned *a, const unsigned *b, int tolerance) {
    int n = 0;
    for (int y = 0; y < CF_VIEW_H; ++y)
        for (int x = 0; x < CF_VIEW_W; ++x)
            for (int i = 0; i < 3; ++i) if (abs(ch(a[y * PITCH + x], i) - ch(b[y * PITCH + x], i)) > tolerance) { ++n; break; }
    return n;
}
static void capture(const char *name) {
    const char *dir = getenv("CF_CAPTURES");
    if (!dir) return;
    char path[600];
    snprintf(path, sizeof(path), "%s/%s.rgba", dir, name);
    FILE *f = fopen(path, "wb");
    fwrite(shown, 4, CF_VIEW_H * CF_VIEW_W, f);
    fclose(f);
}

static void renderer(void) {
    const unsigned *ring[7], *mirror[7];
    for (int j = 0; j < 7; ++j) {
        for (int i = 0; i < 160 * 160; ++i) flat[j][i] = colours[j];
        ring[j] = flat[j];
    }
    for (int i = 0; i < 160 * 160; ++i) art[i] = 0xff000000u | (unsigned)(i * 2654435761u >> 8 & 0xffffff);
    /* At rest the selected cover is the texture itself, 160 px square at CF_TOP, centred, full
       brightness; the neighbours at CF_BRIGHT1, then CF_BRIGHT2; the third out is not drawn. */
    const unsigned *rest[7] = { flat[0], flat[1], flat[2], art, flat[4], flat[5], flat[6] };
    render(0, rest);
    for (int y = 0; y < 160; ++y)
        for (int x = 0; x < 160; ++x) assert(px(CF_CX - 80 + x, CF_TOP + y) == art[y * 160 + x]);
    assert(px(CF_CX - 81, CF_TOP + 80) != art[80 * 160] && px(CF_CX, CF_TOP - 1) == 0xff000000u);
    /* Each neighbour's visible run on the horizon, sampled in its middle: its colour at its
       brightness, two a side, each run a real slice of cover. */
    for (int j = -2; j <= 2; ++j) {
        if (!j) continue;
        int first = -1, last = -1;
        for (int x = 0; x < CF_VIEW_W; ++x)
            if (coverflow_hit(0, x, CF_TOP + 80) == j) last = x, first = first < 0 ? x : first;
        assert(last - first >= (abs(j) == 1 ? 40 : 18));
        unsigned p = px((first + last) / 2, CF_TOP + 80), want = colours[j + 3];
        int b = abs(j) == 1 ? CF_BRIGHT1 : CF_BRIGHT2;
        for (int i = 0; i < 3; ++i) assert(abs(ch(p, i) - ch(want, i) * b / 256) <= 1);
    }
    static unsigned without[(CF_VIEW_H + 3) * PITCH];
    memcpy(without, frame, sizeof(frame));
    const unsigned *inner[7] = { 0, flat[1], flat[2], art, flat[4], flat[5], 0 };
    render(0, inner);
    assert(!memcmp(without, frame, sizeof(frame))); /* the third out is not drawn at rest */
    /* Everything, reflections included, fits the frame with room to spare. */
    for (int x = 0; x < CF_VIEW_W; ++x) assert(!(px(x, 0) & 0xffffff) && !(px(x, CF_VIEW_H - 1) & 0xffffff));
    /* The reflection: CF_REFLECT rows under the cover, from CF_REFLECT_TOP of its brightness down
       to black, never brighter going down; nothing after it. */
    render(0, ring);
    int prev = 256, rows = 0;
    for (int y = CF_TOP + 160; y < CF_VIEW_H; ++y) {
        int v = ch(px(CF_CX, y), 0); /* slot 3 is 0xff00ffff: red and green */
        assert(v <= prev);
        if (y == CF_TOP + 160) assert(abs(v - 255 * CF_REFLECT_TOP / 256) <= 3);
        rows += v > 0, prev = v;
    }
    assert(rows >= CF_REFLECT - 1 && rows <= CF_REFLECT);
    /* No seam where a body ends mid-row: down any column from a cover's middle, brightness never
       dips between the body, the row they share and the reflection. */
    const unsigned *alone[7] = { 0, 0, 0, flat[3], 0, 0, 0 };
    for (int frac = -ONE / 2; frac < ONE / 2; frac += ONE / 16 + 77) {
        render(frac, alone);
        for (int x = 0; x < CF_VIEW_W; ++x) {
            if (coverflow_hit(frac, x, CF_TOP + 80) != 0) continue;
            int body = 256, dipped = 0;
            for (int y = CF_TOP + 80; y < CF_VIEW_H; ++y) {
                int v = ch(px(x, y), 0);
                dipped |= v < body && v < ch(px(x, y + 1 < CF_VIEW_H ? y + 1 : y), 0) - 2;
                body = v;
            }
            assert(!dipped);
        }
    }
    /* Symmetry: a mirror-image ring renders the mirror image, at rest and mid-turn either way. */
    for (int j = 0; j < 7; ++j) mirror[j] = flat[j < 3 ? j : 6 - j];
    render(0, mirror);
    for (int y = 0; y < CF_VIEW_H; ++y)
        for (int x = 0; x < 2 * CF_CX; ++x) assert(px(x, y) == px(2 * CF_CX - 1 - x, y));
    static unsigned left[(CF_VIEW_H + 3) * PITCH];
    const unsigned *swapped[7];
    for (int j = 0; j < 7; ++j) swapped[j] = ring[6 - j];
    for (int frac = ONE / 8; frac < ONE / 2; frac += ONE / 8) {
        render(-frac, swapped);
        memcpy(left, frame, sizeof(frame));
        render(frac, ring);
        for (int y = 0; y < CF_VIEW_H; ++y)
            for (int x = 0; x < 2 * CF_CX; ++x) assert(px(x, y) == left[y * PITCH + 2 * CF_CX - 1 - x]);
    }
    /* Depth order and hit testing agree with what is drawn: wherever the frontmost projected cover
       is some slot (clear of its edges), the pixel is that slot's colour; nothing is hit where no
       cover is drawn, reflections included. Side covers overlap: one slot hides part of another. */
    for (int frac = -ONE / 2; frac < ONE / 2; frac += ONE / 16) {
        render(frac, ring);
        int hits = 0, covered[7] = { 0 };
        for (int y = 1; y < CF_VIEW_H - 1; ++y)
            for (int x = 1; x < CF_VIEW_W - 1; ++x) {
                int j = coverflow_hit(frac, x, y);
                if (j == 99) continue;
                if (j != coverflow_hit(frac, x - 1, y) || j != coverflow_hit(frac, x + 1, y) ||
                    j != coverflow_hit(frac, x, y - 1) || j != coverflow_hit(frac, x, y + 1)) continue;
                if ((px(x, y) & 0xffffff) && ch(px(x, y), 0) < 24 && ch(px(x, y), 1) < 24 && ch(px(x, y), 2) < 24) continue; /* fading in */
                assert(slot_of(px(x, y)) == j + 3);
                ++hits, ++covered[j + 3];
            }
        assert(hits > 160 * 150);
    }
    assert(coverflow_hit(0, CF_CX, CF_TOP + 80) == 0 && coverflow_hit(0, CF_CX, CF_TOP + 170) == 99);
    assert(coverflow_hit(0, 0, 0) == 99 && coverflow_hit(0, CF_VIEW_W - 1, 0) == 99);
    assert(coverflow_hit(0, CF_CX + 90, CF_TOP + 80) == 1 && coverflow_hit(0, CF_CX - 91, CF_TOP + 80) == -1);
    assert(coverflow_hit(0, CF_VIEW_W - 20, CF_TOP + 80) == 2 && coverflow_hit(0, 19, CF_TOP + 80) == -2);
    /* Continuity: covers move, turn and fade from one continuous position, so a small step changes
       only a little, including where the centre changes hands (frac -1/2 after c, +1/2 before). */
    static unsigned a[(CF_VIEW_H + 3) * PITCH];
    const unsigned *next[7];
    for (int j = 0; j < 7; ++j) next[j] = ring[(j + 1) % 7];
    render(ONE / 2 - 1, ring);
    memcpy(a, frame, sizeof(frame));
    render(-ONE / 2, next);
    assert(differ(a, frame, 6) < 200);
    int worst = 0;
    for (int f = -ONE / 2; f + ONE / 256 < ONE / 2; f += ONE / 256) {
        render(f, ring);
        memcpy(a, frame, sizeof(frame));
        render(f + ONE / 256, ring);
        int d = differ(a, frame, 24);
        worst = d > worst ? d : worst;
    }
    assert(worst < CF_VIEW_W * CF_VIEW_H / 50);
}

static void depth(void) {
    renderer();
    /* On the page: the slide_menu spans the frame, one album per CF_STRIDE px, with empty children
       under the drawn covers; the captions sit under the frame in both builds. */
    frame_fail = 0;
    open_page();
    widget *s = slide();
    char *raw = s->raw;
    int *geo = (int *)raw;
    assert(frames == 1 && geo[0] == 0 && geo[1] == 0 && geo[2] == CF_VIEW_W && geo[3] == 290); /* the whole page takes swipes */
    assert(slide_menu_item_width(s) + *(int *)(raw + SLIDE_SPACER) == CF_STRIDE);
    for (int i = 0; i < s->nkids; ++i) assert(!w[s->kids[i]].image[0]);
    widget *covers_view = &w[s->parent];
    int labels = 0;
    for (int i = 0; i < covers_view->nkids; ++i) {
        widget *l = &w[covers_view->kids[i]];
        if (strcmp(l->type, "hscroll_label")) continue;
        int *g = (int *)l->raw;
        assert(g[0] == CF_EDGE && g[2] == 375 - 2 * CF_EDGE && g[1] == CF_TEXT_Y + labels * CF_NAME_H && g[1] >= CF_VIEW_H);
        ++labels;
    }
    assert(labels == 2);
    /* Paint: the seven covers around the position decoded (each load released at once; albums 2
       and 3, Embedded and None, have only the empty marker and show the placeholder), one render,
       drawn 1:1 at the slide_menu's origin. A repaint in place only draws again. */
    int canvas[16] = { 0 };
    *(void **)(raw + W_PARENT) = covers_view;
    *(int *)(raw + SLIDE_INDEX) = 3; *(int *)(raw + SLIDE_OFFSET) = 0;
    loads = unloads = 0;
    coverflow_paint(s, canvas);
    assert(draws == 1 && locks == 1 && drawn[0] == 0 && drawn[1] == 0 && drawn[2] == CF_VIEW_W && drawn[3] == CF_VIEW_H);
    assert(loads == 5 && unloads == 5 && reads == 5);
    coverflow_paint(s, canvas);
    coverflow_paint(covers_view, canvas); /* other widgets: nothing */
    assert(draws == 2 && locks == 1 && loads == 5);
    capture("rest");
    /* Turning a quarter, a half and three quarters towards the next album draws from the live
       offset without loading; crossing into the next album loads just the one entering reach. */
    static const char *turns[] = { "quarter", "half", "three-quarter" };
    for (int q = 1; q < 4; ++q) {
        *(int *)(raw + SLIDE_OFFSET) = -CF_STRIDE * q / 4;
        coverflow_paint(s, canvas);
        assert(locks == 1 + q && loads == 5 + (q >= 2)); /* past half, album 7 comes into reach */
        capture(turns[q - 1]);
    }
    *(int *)(raw + SLIDE_OFFSET) = 0; *(int *)(raw + SLIDE_INDEX) = 4;
    coverflow_paint(s, canvas);
    assert(loads == 6 && unloads == 6);
    /* Taps: the frontmost projected cover. A side cover scrolls to the centre through stock
       scroll_to; the centre one opens its tracks; a miss or a tap while moving only ends the press.
       The window sits at y 30 under the status bar. */
    int (*release)(void *, void *) = w[8189].click;
    int e[16] = { 0 };
    *(int *)((char *)page->raw + 4) = 30;
    #define TAP(x, y) (e[EVENT_X / 4] = (x), e[EVENT_Y / 4] = 30 + (y), raw[SLIDE_DRAG + 1] = 1, release(0, e))
    int a0 = anims, u0 = ungrabs;
    assert(TAP(CF_VIEW_W - 20, CF_TOP + 80) == 11 && anims == a0 + 1 && anim_to == -2 * CF_STRIDE && ungrabs == u0 + 1 && !raw[SLIDE_DRAG + 1]);
    assert(TAP(CF_CX, CF_TOP + 80) == 11 && anims == a0 + 1); /* moving: ignored */
    *(int *)(raw + SLIDE_OFFSET) = anim_to; slide_menu_on_scroll_done(s, 0);
    assert(*(int *)(raw + SLIDE_INDEX) == 6);
    int (*waiting)(const void *) = timer_fn;
    assert(TAP(CF_CX, CF_TOP + 170) == 11 && TAP(5, 5) == 11 && anims == a0 + 1 && timer_fn == waiting); /* reflection, background */
    assert(TAP(CF_CX - 91, CF_TOP + 80) == 11 && anim_to == CF_STRIDE);
    *(void **)(raw + SLIDE_ANIMATOR) = 0;
    /* Covers resting between albums (a release that never reached the page): a tap still picks
       the cover under the finger rather than only snapping. */
    *(int *)(raw + SLIDE_OFFSET) = 30;
    assert(TAP(CF_VIEW_W - 20, CF_TOP + 80) == 11 && anim_to == -2 * CF_STRIDE);
    *(int *)(raw + SLIDE_OFFSET) = 0;
    *(void **)(raw + SLIDE_ANIMATOR) = 0;
    raw[SLIDE_DRAG + 1] = 0;
    assert(release(0, e) == 0); /* a release that did not press the covers passes on */
    assert(TAP(CF_CX, CF_TOP + 80) == 11 && timer_fn != waiting);
    run();
    assert(!strcmp(title(), names[6]) && !covers_view->visible && last_album(6)); /* kept for a reboot */
    key(KEY_RETURN); /* back to the same album, still drawn */
    assert(covers_view->visible && *(int *)(raw + SLIDE_INDEX) == 6);
    coverflow_paint(s, canvas);
    /* Refresh and close release the frame and every texture. */
    close_page();
    assert(frames == 0 && loads == unloads);
    /* Small libraries: two albums and the Refresh card wrap round the ring, each album decoded
       once however often it repeats; missing art shows the placeholder. */
    int keep = albums;
    albums = 2; rescan();
    open_page();
    s = slide(); raw = s->raw;
    *(void **)(raw + W_PARENT) = &w[s->parent];
    loads = unloads = 0;
    coverflow_paint(s, canvas);
    assert(s->nkids == 3 && loads <= 2 && loads == unloads);
    render(0, (const unsigned *const[7]){ 0 }); /* nothing to draw: all black */
    for (int i = 0; i < CF_VIEW_W; ++i) assert(px(i, CF_TOP + 80) == 0xff000000u);
    close_page();
    albums = 1; rescan();
    open_page(); s = slide(); *(void **)(s->raw + W_PARENT) = &w[s->parent];
    coverflow_paint(s, canvas);
    assert(s->nkids == 2);
    capture("one-album");
    close_page();
    albums = keep; rescan();
    /* Allocation failure: the flat covers, as before. */
    tex_fail = 1;
    open_page(); s = slide();
    int flat_images = 0;
    for (int i = 0; i < s->nkids; ++i) flat_images += !strncmp(w[s->kids[i]].image, "file://", 7);
    assert(frames == 0 && ((int *)s->raw)[1] == 24 && ((int *)s->raw)[3] == 160 && flat_images > 0);
    for (int i = 0; i < s->nkids; ++i) assert(w[s->kids[i]].image[0]); /* art or the placeholder, as before */
    int before = draws;
    coverflow_paint(s, canvas);
    assert(draws == before);
    close_page();
    assert(loads == unloads);
    tex_fail = 0;
}

int main(void) {
    /* The stock scan flags are raw addresses in the device ABI; map them here. */
    assert(mmap((void *)(SCAN_THREAD & ~4095), 4096, PROT_READ | PROT_WRITE,
                MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0) != MAP_FAILED);
    deque staging = {0};
    shim_dir = &staging;
    frame_fail = 1; /* the flat fallback first: stock images on the slide_menu */
    mkdir(PEQ_ROOT, 0755); mkdir(PEQ_ROOT "/mnt", 0755); mkdir(PEQ_ROOT "/mnt/mmc", 0755); mkdir(PEQ_ROOT "/music", 0755);

    /* An empty library, or one being scanned, shows the message and builds nothing. */
    open_page();
    assert(!strcmp(title(), "Update Local Music first") && !slide() && queries == 1);
    /* Every list (message, progress, tracks) comes from list(): iPod rows are transparent, so its
       list_view paints black itself rather than the theme's light card. */
    int lists = 0;
    for (int i = nw; i > page - w; --i) if (!strcmp(w[i].type, "list_view")) { assert((unsigned)w[i].bg == 0xff000000u); ++lists; }
    assert(lists == 1);
    key(KEY_RETURN); close_page();
    album("Cover", "cover.jpg");
    *(volatile int *)SCAN_THREAD = 1;
    open_page();
    assert(!strcmp(title(), "Update Local Music first") && queries == 1 && !calls);
    close_page();
    *(volatile int *)SCAN_DONE = 1;

    /* cover.jpg beats folder.jpg, which beats embedded art; with no art an empty marker makes
       the placeholder show. Folder art takes only the parse lock, embedded art both, in order. */
    char both[600];
    snprintf(both, sizeof(both), PEQ_ROOT "/music/Cover/folder.jpg");
    fclose(fopen(both, "w"));
    album("Folder", "folder.jpg");
    album("Embedded", 0);
    rescan();
    open_page();
    assert(calls == 3 && !strcmp(made[0], "cover.jpg") && !strcmp(made[1], "folder.jpg") && !strcmp(made[2], "embedded"));
    assert(norder == 4 && order[0] == 1 && order[1] == 1 && order[2] == 1 && order[3] == 2);
    assert(size("Cover") == 9 && size("Folder") == 10 && size("Embedded") == 8 && !tmp_files());
    widget *s = slide();
    assert(s && s->nkids == 4 && !strncmp(w[s->kids[0]].image, "file://", 7));
    close_page();
    embedded_fails = 1;
    album("None", 0);
    rescan();
    open_page();
    assert(calls == 3 && size("None") == 0 && !tmp_files());
    s = slide();
    assert(!strcmp(w[s->kids[3]].image, "default_album_big") && !strncmp(w[s->kids[2]].image, "file://", 7));
    assert(!strcmp(w[s->kids[4]].image, "default_album_big")); /* the Refresh card */
    close_page();

    /* A later open builds only the albums with no cache file; the marker is not retried. */
    album("New", "cover.jpg");
    rescan();
    open_page();
    assert(calls == 4 && !strcmp(made[3], "cover.jpg") && size("New") == 9);
    close_page();

    /* Cancel mid-build (Return on the progress screen) keeps the finished thumbnails, leaves no
       .tmp, and shows the covers; the next open resumes with the rest. */
    album("A", "cover.jpg"); album("B", "cover.jpg"); album("C", "cover.jpg");
    rescan();
    block_at = calls + 1;
    widget home;
    memset(&home, 0, sizeof(home));
    coverflow_home(&home, 0);
    page = &w[nw + 1];
    home.click(home.ctx, 0);
    while (!blocked) usleep(1000);
    assert(!strncmp(title(), "Preparing artwork", 17));
    int e[16] = {0}; e[EVENT_KEY / 4] = KEY_RETURN;
    w[8190].click(0, e);
    pthread_t t;
    pthread_create(&t, 0, release, 0); /* finish the album in hand once the cancel is set */
    run();
    pthread_join(t, 0);
    assert(size("A") == 9 && size("B") == 9 && size("C") == -1 && !tmp_files() && slide() && slide()->visible);
    close_page();
    block_at = -1;
    open_page();
    assert(size("C") == 9 && !strcmp(made[calls - 1], "cover.jpg"));

    /* Covers at rest between albums snap to the nearest one and drop the stale grab; a finger
       still down, a snap already running, or a settled menu is left alone. The check repeats. */
    s = slide();
    char *raw = s->raw;
    int (*settle)(const void *) = last_fn;
    *(void **)(raw + W_PARENT) = &w[s->parent];
    *(int *)(raw + SLIDE_INDEX) = 2; *(int *)(raw + SLIDE_OFFSET) = -250; raw[SLIDE_DRAG] = raw[SLIDE_DRAG + 1] = 1;
    pressed = 1; assert(settle(0) == 8 && !anims);
    pressed = 0; assert(settle(0) == 8);
    assert(anims == 1 && anim_from == -250 && anim_to == -320 && ungrabs == 1 && !raw[SLIDE_DRAG] && !raw[SLIDE_DRAG + 1]);
    settle(0); assert(anims == 1); /* the snap is running */
    *(int *)(raw + SLIDE_OFFSET) = anim_to; slide_menu_on_scroll_done(s, 0); /* the animator's end */
    assert(*(int *)(raw + SLIDE_INDEX) == 4);
    *(int *)(raw + SLIDE_OFFSET) = 70; settle(0);
    assert(anims == 2 && anim_to == 0);
    *(void **)(raw + SLIDE_ANIMATOR) = 0; *(int *)(raw + SLIDE_OFFSET) = 0; settle(0);
    assert(anims == 2 && ungrabs == 1);

    /* A release finishes the drag where the finger left it, before stock's velocity throw sees
       it; a tap passes through to stock. */
    int (*release)(void *, void *) = w[8189].click;
    *(int *)(raw + SLIDE_OFFSET) = 100; raw[SLIDE_DRAG] = raw[SLIDE_DRAG + 1] = 1;
    assert(release(0, 0) == 11 && anims == 3 && anim_to == 160 && ungrabs == 2 && !raw[SLIDE_DRAG]);
    *(void **)(raw + SLIDE_ANIMATOR) = 0; *(int *)(raw + SLIDE_OFFSET) = 0; raw[SLIDE_DRAG + 1] = 1;
    assert(release(0, 0) == 0 && anims == 3 && ungrabs == 2);
    raw[SLIDE_DRAG + 1] = 0;

    /* Refresh (the last card) clears the cache and rebuilds every album. */
    int before = calls, q = queries;
    s = slide();
    w[s->kids[s->nkids - 1]].click(w[s->kids[s->nkids - 1]].ctx, 0);
    run();
    assert(calls == before + albums - 2 && size("None") == 0 && size("Embedded") == 0 && size("Cover") == 9);
    assert(queries == q + 1); /* Refresh always queries again */
    close_page();

    /* The album list outlives the page: reopening queries nothing until a songtable writer runs,
       and a list queried while one runs is not kept. */
    q = queries;
    open_page(); assert(queries == q && slide()); close_page();
    rescan(); /* each writer's hook is checked on the MIPS build (test_patch.py) */
    open_page(); assert(queries == ++q && slide()); close_page();
    open_page(); assert(queries == q); close_page();
    during_write = mid_write; rescan(); during_write = 0;
    assert(queries == ++q);
    open_page(); assert(queries == ++q); close_page();

    /* Low free space on the card skips the build: placeholders, no thread. */
    album("Tight", "cover.jpg");
    rescan();
    free_blocks = 4000; /* under 16 MB of 4 KB blocks */
    before = calls;
    open_page();
    assert(calls == before && size("Tight") == -1 && slide() && !strcmp(w[slide()->kids[albums - 1]].image, "default_album_big"));
    close_page();
    assert(loads == unloads);
    depth();
#if IPOD
    /* iPod Home: the player's cover for its type, once the player has parsed the current track
       (g_lastcover_url is its path), else the track album's Coverflow thumbnail, else the
       placeholder; reloaded only when the track or the usable cover changes, and only while Home
       is the painted top window. */
    extern void coverflow_home_art(void *);
    assert(mmap((void *)(MCL_POS & ~4095), 4096, PROT_READ | PROT_WRITE,
                MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0) != MAP_FAILED);
    deque queue = {0};
    shim_queue = &queue;
    home_art = make(0, "image");
    int *geo = (int *)W(home_art)->raw, panel[4] = { 230, 0, 145, 290 }; /* W_X, W_Y, W_W, W_H */
    memcpy(geo, panel, sizeof panel);
    widget *win = make(0, "window");
    const char *art = W(home_art)->image, *player = "file://" PEQ_ROOT "/tmp/coverpic.jpg";
    mkdir(PEQ_ROOT "/tmp", 0755);
    FILE *f = fopen(PEQ_ROOT "/tmp/coverpic.jpg", "w"); fputs("jpg", f); fclose(f);
    coverflow_home(win, 0);
    assert(&w[insensitive] == W(home_art)); /* taps under a fitted cover still find the list */
    coverflow_home_art(page);
    assert(!*art);
    coverflow_home_art(win);
    assert(!strcmp(art, "default_album_big") && !memcmp(geo, panel, sizeof panel)); /* no size: the panel */
    queue.n = 2; queue.at[0] = records[0]; queue.at[1] = records[3]; /* "Cover" is cached, "None" is not */
    *(volatile int *)MCL_POS = 0;
    shim_covertype = 1;
    coverflow_home_art(win); /* the cover is still the previous track's */
    assert(strstr(art, "/mnt/mmc/.coverflow/") && size("Cover") > 0);
    snprintf(shim_lastcover, sizeof(shim_lastcover), "%s", paths[0]);
    coverflow_home_art(win);
    assert(!strcmp(art, player));
    /* Square, portrait and landscape covers keep their proportions, just cover the panel and are
       centred on it; C division leaves an odd overflow's extra pixel on the right or bottom. */
    static const unsigned covers[][6] = { { 160, 160, 158, 0, 290, 290 }, { 145, 290, 230, 0, 145, 290 },
                                         { 300, 200, 85, 0, 435, 290 }, { 100, 400, 230, -145, 145, 580 } };
    for (unsigned i = 0; i < 4; ++i) {
        art_w = covers[i][0], art_h = covers[i][1];
        *(volatile int *)MCL_POS = 1; coverflow_home_art(win); *(volatile int *)MCL_POS = 0; coverflow_home_art(win);
        for (int k = 0; k < 4; ++k) assert(geo[k] == (int)covers[i][2 + k]);
    }
    art_w = art_h = 160;
    /* The art's paint is clipped to the panel on screen (canvas origin at the art, window at y 30)
       from the background hook to the border hook; other widgets keep the clip. */
    extern void coverflow_home_clip(void *, void *, int);
    int canvas[2] = { geo[0], 30 + geo[1] }, full[4] = { 0, 0, 375, 320 }, want[4] = { 230, 30, 145, 290 };
    coverflow_home_clip(home_art, canvas, 1);
    assert(!memcmp(clip_rect, want, sizeof want));
    coverflow_home_clip(win, canvas, 0);
    assert(!memcmp(clip_rect, want, sizeof want));
    coverflow_home_clip(home_art, canvas, 0);
    assert(!memcmp(clip_rect, full, sizeof full));
    coverflow_home_clip(win, canvas, 1);
    assert(!memcmp(clip_rect, full, sizeof full));
    before = loads;
    coverflow_home_art(win);
    assert(loads == before);
    shim_covertype = 2; /* a folder image the player has not written: the cached thumbnail */
    coverflow_home_art(win);
    assert(strstr(art, "/mnt/mmc/.coverflow/"));
    *(volatile int *)MCL_POS = 1; shim_covertype = 1; /* next track, the old cover still in place */
    coverflow_home_art(win);
    assert(!strcmp(art, "default_album_big"));
    snprintf(shim_lastcover, sizeof(shim_lastcover), "%s", paths[3]);
    coverflow_home_art(win);
    assert(!strcmp(art, player) && loads == unloads);
    /* Home layout: Full widens the list to the screen and its rows and their tap targets to
       HOME_FULL_ROW, never the labels, and hides the art; Split puts the asset's width back and
       shows the art again. */
    extern void coverflow_home_layout(void);
    home_list = make(0, "list_view");
    widget *sv = make(home_list, "scroll_view"), *row = make(sv, "view"), *label = make(row, "hscroll_label"),
           *tap = make(row, "image"), *all[] = { home_list, sv, row, tap };
    for (int i = 0; i < 4; ++i) *(int *)(all[i]->raw + W_W) = 205;
    *(int *)(label->raw + W_W) = 149;
    home_full = 1;
    coverflow_home(win, 0);
    for (int i = 0; i < 4; ++i) assert(*(int *)(all[i]->raw + W_W) == (i < 2 ? 375 : HOME_FULL_ROW));
    assert(*(int *)(label->raw + W_W) == 149 && !W(home_art)->visible);
    before = loads;
    coverflow_home_art(win); /* hidden: nothing loads */
    assert(loads == before);
    home_full = 0;
    coverflow_home_layout();
    for (int i = 0; i < 4; ++i) assert(*(int *)(all[i]->raw + W_W) == 205);
    assert(*(int *)(label->raw + W_W) == 149 && W(home_art)->visible);
    coverflow_home_art(win);
    assert(loads == before + 1 && !strcmp(art, player));
#endif
    return 0;
}
"""


def main():
    import argparse, os
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--captures', type=pathlib.Path,
                    help='write the renderer\'s frames (rest, quarter, half, three-quarter turns, one album) as PNGs here')
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix='q2-coverflow-check-') as directory:
        tmp = pathlib.Path(directory)
        (tmp/'shim.h').write_text(SHIM_H)
        (tmp/'test.c').write_text(TEST)
        for ipod in (0, 1):  # a fresh card each run
            binary = tmp/f'coverflow_test{ipod}'
            subprocess.run(['cc', '-m32', '-pthread', '-DPEQ_HOST', f'-DPEQ_ROOT="{tmp}/root{ipod}"', f'-DIPOD={ipod}',
                            '-D_GNU_SOURCE', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                            '-I', str(ROOT/'patch'), '-include', str(tmp/'shim.h'), str(ROOT/'patch/coverflow.c'),
                            str(tmp/'test.c'), '-o', str(binary)], check=True)
            env = dict(os.environ)
            if a.captures and not ipod:  # the renderer is the same in both builds
                (tmp/'frames').mkdir()
                env['CF_CAPTURES'] = str(tmp/'frames')
            subprocess.run([str(binary)], check=True, env=env)
        if a.captures:
            a.captures.mkdir(parents=True, exist_ok=True)
            from compact import inc, imagemagick
            size = f"{inc('CF_VIEW_W')}x{inc('CF_VIEW_H')}"
            for raw in sorted((tmp/'frames').glob('*.rgba')):  # RGBA8888 rows, the frame's byte order
                (a.captures/(raw.stem + '.png')).write_bytes(imagemagick(
                    '-size', size, '-depth', '8', 'rgba:-', '-alpha', 'off', 'png:-', data=raw.read_bytes()))
    print('Coverflow: art order, locks, markers, resume, cancel, Refresh, album list reuse, low space and empty library passed;'
          ' depth renderer (exact centre, clipping, symmetry, depth order, hit testing, reflection, continuity),'
          ' its texture window, taps, small libraries and flat fallback passed;'
          ' iPod Home art sources, fit, clip and Split/Full layout passed.')


if __name__ == '__main__':
    main()
