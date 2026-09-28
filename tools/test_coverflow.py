#!/usr/bin/env python3
"""Run patch/coverflow.c's art cache on the host: the library query, the modal art build on a real
pthread, the stock art calls and their locks. Built 32-bit (-m32, like test_peq.py's player) so the
stSongInfo pointer offsets hold. The stock calls are stubbed; UI widgets are plain records."""
import pathlib
import subprocess
import tempfile

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
int getAllAlbum(void);
int getMusicByAlbum(const char *);
int toolsThumbSpecCover(const char *, const char *, int, int);
int toolsGetAlbumCover(const char *, const char *, int, int);
void *_create_deque(const char *);
void deque_init_copy(void *, const void *), deque_clear(void *), deque_assign(void *, const void *);
void deque_destroy(void *);
unsigned deque_size(const void *);
void *deque_at(const void *, unsigned);
void *window_create(void *, int, int, int, int);
void *widget_factory(void);
void *widget_factory_create_widget(void *, const char *, void *, int, int, int, int);
void *image_create(void *, int, int, int, int);
void *hscroll_label_create(void *, int, int, int, int);
void set_hscroll_label_attribute(void *);
int slide_menu_set_value(void *, int), slide_menu_item_width(void *), slide_menu_on_scroll_done(void *, void *);
int slide_menu_scroll_to(void *, int), widget_ungrab(void *, void *);
void *list_view_create(void *, int, int, int, int);
void *scroll_view_create(void *, int, int, int, int);
void *list_item_create(void *, int, int, int, int);
int image_set_draw_type(void *, int), image_base_set_image(void *, const char *);
int widget_load_image(void *, const char *, void *), widget_unload_image(void *, void *);
int widget_set_name(void *, const char *), widget_use_style(void *, const char *);
int widget_set_text_utf8(void *, const char *), widget_set_visible(void *, int, int);
int widget_get_prop_int(void *, const char *, int), widget_set_prop_int(void *, const char *, int);
const char *widget_get_prop_str(void *, const char *, const char *);
unsigned widget_on(void *, unsigned, handler, void *);
int widget_destroy_children(void *), widget_invalidate_force(void *, void *);
unsigned widget_count_children(void *);
void *widget_get_child(void *, unsigned);
void *widget_lookup(void *, const char *, int);
int tk_strcmp(const char *, const char *);
unsigned timer_add(int (*)(const void *), void *, unsigned);
int timer_remove(unsigned);
int navigator_back_to_home(void), navigator_to_with_context(const char *, const void *);
void *window_manager(void);
int window_manager_get_pointer_pressed(void *);
"""

TEST = r"""
#include <assert.h>
#include <sys/mman.h>
#include "peq.h"
#include "offsets.inc"
#undef pthread_mutex_lock /* the stubs below record, then take the real lock */
#undef pthread_mutex_unlock
int coverflow_home(void *, void *);

/* Widgets: raw memory first, so the payload's field reads (SLIDE_INDEX) land in it. */
typedef struct { char raw[0x100]; int parent, visible, kids[512], nkids; char type[32], text[160], image[600];
                 handler click; void *ctx; } widget;
static widget w[8192];
static int nw;
static widget *W(void *p) { return (widget *)p; }
static void *make(void *parent, const char *type) {
    widget *x = &w[++nw];
    memset(x, 0, sizeof(*x));
    x->visible = 1;
    snprintf(x->type, sizeof(x->type), "%s", type);
    if (parent) { x->parent = (int)(W(parent) - w); W(parent)->kids[W(parent)->nkids++] = nw; }
    return x;
}
void *window_create(void *p, int x, int y, int ww, int h) { (void)p; (void)x; (void)y; (void)ww; (void)h; return make(0, "window"); }
void *widget_factory(void) { return (void *)1; }
void *widget_factory_create_widget(void *f, const char *t, void *p, int x, int y, int ww, int h) { (void)f; (void)x; (void)y; (void)ww; (void)h; return make(p, t); }
#define CREATE(name, type) void *name(void *p, int x, int y, int ww, int h) { (void)x; (void)y; (void)ww; (void)h; return make(p, type); }
CREATE(image_create, "image") CREATE(list_view_create, "list_view")
CREATE(hscroll_label_create, "hscroll_label")
CREATE(scroll_view_create, "scroll_view") CREATE(list_item_create, "list_item")
int image_set_draw_type(void *x, int t) { (void)x; (void)t; return 0; }
int image_base_set_image(void *x, const char *s) { snprintf(W(x)->image, 600, "%s", s); return 0; }
/* A zero-length "no art" marker does not decode. Every successful load is unloaded again. */
static int loads, unloads;
int widget_load_image(void *x, const char *url, void *b) {
    (void)x; (void)b; struct stat s;
    int failed = strncmp(url, "file://", 7) || stat(url + 7, &s) || !s.st_size;
    loads += !failed;
    return failed;
}
int widget_unload_image(void *x, void *b) { (void)x; (void)b; ++unloads; return 0; }
void set_hscroll_label_attribute(void *x) { assert(!strcmp(W(x)->type, "hscroll_label")); }
int slide_menu_set_value(void *x, int value) { *(int *)(W(x)->raw + SLIDE_INDEX) = value; return 0; }
int widget_set_name(void *x, const char *s) { snprintf(W(x)->type, 32, "%s", s); return 0; }
int widget_use_style(void *x, const char *s) { (void)x; (void)s; return 0; }
int widget_set_text_utf8(void *x, const char *s) { snprintf(W(x)->text, 160, "%s", s); return 0; }
int widget_set_visible(void *x, int v, int r) { (void)r; W(x)->visible = v; return 0; }
int widget_get_prop_int(void *x, const char *k, int d) { (void)x; (void)k; return d; }
int widget_set_prop_int(void *x, const char *k, int v) { (void)x; (void)k; (void)v; return 0; }
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
static void *home_art; /* iPod Home's art; none in the carousel tests */
void *widget_lookup(void *x, const char *n, int r) {
    (void)r;
    return !x ? 0 : !strcmp(n, "img_coverflow") ? x : !strcmp(n, "img_homeart") ? home_art : 0;
}
int tk_strcmp(const char *a, const char *b) { return strcmp(a ? a : "", b ? b : ""); }
int navigator_back_to_home(void) { return 0; }
int navigator_to_with_context(const char *n, const void *c) { (void)n; (void)c; return 0; }
/* slide_menu: 160 px covers, no spacer; scroll_to records its goal and holds the animator slot. */
static int anim_from, anim_to, anims, ungrabs;
int slide_menu_item_width(void *x) { (void)x; return 160; }
int slide_menu_on_scroll_done(void *x, void *e) {
    (void)e; char *r = W(x)->raw;
    *(int *)(r + SLIDE_INDEX) -= *(int *)(r + SLIDE_OFFSET) / 160;
    *(int *)(r + SLIDE_OFFSET) = 0; *(void **)(r + SLIDE_ANIMATOR) = 0;
    return 0;
}
int slide_menu_scroll_to(void *x, int to) {
    ++anims; anim_from = *(int *)(W(x)->raw + SLIDE_OFFSET); anim_to = to;
    *(void **)(W(x)->raw + SLIDE_ANIMATOR) = &anim_from;
    return 0;
}
int widget_ungrab(void *p, void *c) { assert(W(c)->parent == W(p) - w); ++ungrabs; return 0; }
static int pressed;
void *window_manager(void) { return &pressed; }
int window_manager_get_pointer_pressed(void *wm) { return *(int *)wm; }
int stock_home_trampoline(void *win, void *ctx) { (void)win; (void)ctx; return 0; }

static int (*timer_fn)(const void *), (*last_fn)(const void *);
unsigned timer_add(int (*f)(const void *), void *ctx, unsigned ms) { (void)ctx; (void)ms; timer_fn = last_fn = f; return 1; }
int timer_remove(unsigned id) { (void)id; timer_fn = 0; return 0; }
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

int main(void) {
    /* The stock scan flags are raw addresses in the device ABI; map them here. */
    assert(mmap((void *)(SCAN_THREAD & ~4095), 4096, PROT_READ | PROT_WRITE,
                MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0) != MAP_FAILED);
    deque staging = {0};
    shim_dir = &staging;
    mkdir(PEQ_ROOT, 0755); mkdir(PEQ_ROOT "/mnt", 0755); mkdir(PEQ_ROOT "/mnt/mmc", 0755); mkdir(PEQ_ROOT "/music", 0755);

    /* An empty library, or one being scanned, shows the message and builds nothing. */
    open_page();
    assert(!strcmp(title(), "Update Local Music first") && !slide() && queries == 1);
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
    open_page();
    assert(calls == 3 && !strcmp(made[0], "cover.jpg") && !strcmp(made[1], "folder.jpg") && !strcmp(made[2], "embedded"));
    assert(norder == 4 && order[0] == 1 && order[1] == 1 && order[2] == 1 && order[3] == 2);
    assert(size("Cover") == 9 && size("Folder") == 10 && size("Embedded") == 8 && !tmp_files());
    widget *s = slide();
    assert(s && s->nkids == 4 && !strncmp(w[s->kids[0]].image, "file://", 7));
    close_page();
    embedded_fails = 1;
    album("None", 0);
    open_page();
    assert(calls == 3 && size("None") == 0 && !tmp_files());
    s = slide();
    assert(!strcmp(w[s->kids[3]].image, "default_album_big") && !strncmp(w[s->kids[2]].image, "file://", 7));
    assert(!strcmp(w[s->kids[4]].image, "default_album_big")); /* the Refresh card */
    close_page();

    /* A later open builds only the albums with no cache file; the marker is not retried. */
    album("New", "cover.jpg");
    open_page();
    assert(calls == 4 && !strcmp(made[3], "cover.jpg") && size("New") == 9);
    close_page();

    /* Cancel mid-build (Return on the progress screen) keeps the finished thumbnails, leaves no
       .tmp, and shows the covers; the next open resumes with the rest. */
    album("A", "cover.jpg"); album("B", "cover.jpg"); album("C", "cover.jpg");
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
    int before = calls;
    s = slide();
    w[s->kids[s->nkids - 1]].click(w[s->kids[s->nkids - 1]].ctx, 0);
    run();
    assert(calls == before + albums - 2 && size("None") == 0 && size("Embedded") == 0 && size("Cover") == 9);
    close_page();

    /* Low free space on the card skips the build: placeholders, no thread. */
    album("Tight", "cover.jpg");
    free_blocks = 4000; /* under 16 MB of 4 KB blocks */
    before = calls;
    open_page();
    assert(calls == before && size("Tight") == -1 && slide() && !strcmp(w[slide()->kids[albums - 1]].image, "default_album_big"));
    close_page();
    assert(loads == unloads);
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
    widget *win = make(0, "window");
    const char *art = W(home_art)->image, *player = "file://" PEQ_ROOT "/tmp/coverpic.jpg";
    mkdir(PEQ_ROOT "/tmp", 0755);
    FILE *f = fopen(PEQ_ROOT "/tmp/coverpic.jpg", "w"); fputs("jpg", f); fclose(f);
    coverflow_home(win, 0);
    coverflow_home_art(page);
    assert(!*art);
    coverflow_home_art(win);
    assert(!strcmp(art, "default_album_big"));
    queue.n = 2; queue.at[0] = records[0]; queue.at[1] = records[3]; /* "Cover" is cached, "None" is not */
    *(volatile int *)MCL_POS = 0;
    shim_covertype = 1;
    coverflow_home_art(win); /* the cover is still the previous track's */
    assert(strstr(art, "/mnt/mmc/.coverflow/") && size("Cover") > 0);
    snprintf(shim_lastcover, sizeof(shim_lastcover), "%s", paths[0]);
    coverflow_home_art(win);
    assert(!strcmp(art, player));
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
#endif
    return 0;
}
"""


def main():
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
            subprocess.run([str(binary)], check=True)
    print('Coverflow: art order, locks, markers, resume, cancel, Refresh, low space and empty library passed;'
          ' iPod Home art sources passed.')


if __name__ == '__main__':
    main()
