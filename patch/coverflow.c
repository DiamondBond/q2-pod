/* Coverflow (docs/internals.md): the stock Local Music albums on a stock slide_menu, the way
 * PictureFlow reads Rockbox's database. No tag reads: albums and tracks come from the stock library
 * queries, and the only thing Coverflow owns is a thumbnail cache, built on a modal screen by one
 * pthread that touches only files, the two stock art locks and the volatile counters below. */
#include "offsets.inc"
#include "peq.h"
#ifndef PEQ_HOST
#include "stock.h"
#endif

/* On the card, beside stock's own cover cache (/mnt/mmc/.sldp). */
#define ART_DIR PEQ_ROOT "/mnt/mmc/.coverflow"
#define ART_SIZE 160
#define LAST_ALBUM ART_DIR "/album" /* the centre album's key, so a reboot opens on it */
#if IPOD /* iPod insets its text from the rounded glass (offsets.inc CF_*); normal keeps its layout */
#define CF_X CF_EDGE
#define CF_W (375 - 2 * CF_EDGE)
#define CF_ROW_X CF_X /* one text column throughout */
#define CF_ROW_W CF_W
#else
#define CF_X 8
#define CF_W 359
#define CF_ROW_X 12
#define CF_ROW_W 350
#endif
#define ART_MIN_FREE_MB 16 /* no build below this much free space on the card */
#define ART_NEAR 3 /* real art only this many covers either side, like PictureFlow's cache */
#define PLACEHOLDER "default_album_big"

extern int stock_home_trampoline(void *win, void *ctx), stock_scan_all_trampoline(void *, void *),
    stock_scan_folder_trampoline(void *, void *), stock_delete_song_trampoline(void *, void *);
extern void stop_timer(unsigned *timer), rearm(unsigned *timer, int (*fn)(const void *), unsigned ms);

enum { PREPARING, COVERS, TRACKS };
typedef struct {
    char *track; /* the album's first track, copied so the thread never reads stock deques */
    unsigned key;
} job_t;
static struct {
    void *page, *body, *covers, *slide, *name, *artist, *title;
    void *albums, *tracks; /* our copies of the stock query results */
    job_t *jobs;
    unsigned long thread;
    unsigned timer;
    unsigned saved_album, albums_gen; /* albums_gen: library_gen when albums was queried */
    int screen, album, running;
    volatile int done, total, cancel;
} cf __attribute__((section(".scratch")));

static int pick(void *ctx, void *event);

/* The album list is kept across opens until songtable changes. Only these three stock functions
 * write it; each moves the generation before and after it runs, so a list queried meanwhile is
 * never kept. The scans run on stock's scan thread. */
static volatile unsigned library_gen __attribute__((section(".scratch")));
static int library_write(int (*stock)(void *, void *), void *a, void *b) {
    ++library_gen;
    int result = stock(a, b);
    ++library_gen;
    return result;
}
int coverflow_scan_all(void *a, void *b) { return library_write(stock_scan_all_trampoline, a, b); }
int coverflow_scan_folder(void *a, void *b) { return library_write(stock_scan_folder_trampoline, a, b); }
int coverflow_delete_song(void *a, void *b) { return library_write(stock_delete_song_trampoline, a, b); }

/* The queue menu resolves the live track list again after its dialog closes. */
void *coverflow_tracks(void *page) {
    return page == cf.page && cf.screen == TRACKS ? cf.tracks : 0;
}

/* FNV-1a, shared with ringnav.c */
unsigned hash_bytes(unsigned h, const unsigned char *s, unsigned n) {
    for (unsigned i = 0; i < n; ++i) h = (h ^ s[i]) * 16777619u;
    return h;
}

unsigned fnv(unsigned h, const unsigned char *s) {
    while (s && *s) h = hash_bytes(h, s++, 1);
    return h * 16777619u; /* a separator, so "ab"+"c" and "a"+"bc" differ */
}

static unsigned album_key(void *r) {
    return fnv(fnv(FNV_SEED, P(r, REC_ARTIST)), P(r, REC_ALBUM));
}

/* Track selection uses ringnav's existing position memory, keyed by this album. */
unsigned coverflow_scope(void *page) {
    return coverflow_tracks(page) ? album_key(deque_at(cf.albums, (unsigned)cf.album)) : 0;
}

/* ART_DIR/<key>.jpg<suffix>; out holds at least 512 bytes. */
static char *art_path(char *out, unsigned key, const char *suffix) {
    tk_snprintf(out, 512, ART_DIR "/%08x.jpg%s", key, suffix);
    return out;
}

static int thumb(const char *src, const char *dst) {
    pthread_mutex_lock((void *)parse_cover_mutex);
    int ok = toolsThumbSpecCover(src, dst, ART_SIZE, ART_SIZE) == 1;
    pthread_mutex_unlock((void *)parse_cover_mutex);
    return ok;
}

/* One album: cover.jpg, folder.jpg, then embedded art, written to .tmp and renamed. An empty
 * file marks "no art", so the placeholder shows and the album is not retried until Refresh. */
static void build_art(const job_t *j) {
    char dst[512], tmp[512], src[1024];
    if (access(j->track, 0)) return; /* storage gone: no marker, the next open retries */
    art_path(dst, j->key, "");
    art_path(tmp, j->key, ".tmp");
    int folder = 0, ok = 0;
    for (int i = 0; j->track[i]; ++i)
        if (j->track[i] == '/') folder = i;
    static const char *const names[] = { "cover.jpg", "folder.jpg" };
    for (int i = 0; i < 2 && !ok; ++i) {
        snprintf(src, sizeof(src), "%.*s/%s", folder, j->track, names[i]);
        ok = !access(src, 4) && thumb(src, tmp);
    }
    if (!ok) {
        /* toolsGetAlbumCover goes through the shared /tmp/.tmp_picture, which stock guards with
         * either lock (parse_albumcovertask_thd, player_parsecover_thd); hold both. Stock never
         * nests them, so this order cannot deadlock. */
        pthread_mutex_lock((void *)parse_cover_mutex);
        pthread_mutex_lock((void *)g_playcover_mutex);
        ok = toolsGetAlbumCover(j->track, tmp, ART_SIZE, ART_SIZE) == 1;
        pthread_mutex_unlock((void *)g_playcover_mutex);
        pthread_mutex_unlock((void *)parse_cover_mutex);
    }
    if (ok && !rename(tmp, dst)) return;
    unlink(tmp);
    if (access(j->track, 0)) return;
    void *f = fopen(dst, "w");
    if (f) fclose(f);
}

static void *worker(void *unused) {
    (void)unused;
    while (cf.done < cf.total && !cf.cancel) {
        build_art(&cf.jobs[cf.done]);
        ++cf.done;
    }
    return 0;
}

/* Cancel stops after the current album; finished thumbnails stay, so the next open resumes. */
static void stop(void) {
    if (cf.running) {
        cf.cancel = 1;
        pthread_join(cf.thread, 0);
        cf.running = 0;
    }
    stop_timer(&cf.timer);
    for (int i = 0; i < cf.total; ++i) free(cf.jobs[i].track);
    free(cf.jobs);
    cf.jobs = 0;
    cf.total = cf.done = 0;
}

static void fx_close(void);

static void drop(void) {
    stop();
    fx_close();
    if (cf.tracks) deque_destroy(cf.tracks);
    cf.tracks = 0;
}

static void drop_albums(void) {
    if (cf.albums) deque_destroy(cf.albums);
    cf.albums = 0;
}

/* A stock library query's rows (*count its result) copied out of the staging deque, which is
 * restored so the query leaves no trace; shared with ringnav.c's queue menu. */
void *staged(int (*query)(void *), void *arg, int *count) {
    void *dir = P(tools_pdeq_directory, 0), *save = _create_deque("stSongInfo"),
         *out = _create_deque("stSongInfo");
    deque_init_copy(save, dir);
    *count = query(arg);
    deque_init_copy(out, dir);
    deque_clear(dir);
    deque_assign(dir, save);
    deque_destroy(save);
    return out;
}

/* getAllAlbum, as load_localclass_list 0xf003 runs it, or the album's getMusicByAlbum, as its row
 * opens it. Stock order, including the trailing "Unknown Album" (id -1) row. */
static int albums(void *album) {
    return album ? getMusicByAlbum(I(album, REC_ID) == -1 ? (const char *)0 : P(album, REC_ALBUM))
                 : getAllAlbum();
}

static void *text(void *parent, int x, int y, int w, int h) {
    void *label = hscroll_label_create(parent, x, y, w, h);
    widget_use_style(label, "s_scrlabel_white20c");
    set_hscroll_label_attribute(label);
    widget_set_prop_int(label, "loop", 1);
    return label;
}

/* The peq_ui.c page: a title bar over whole 48px rows, shrunk so the list's white background
 * never shows below a short list. */
static void *list(const char *title, int n) {
    int h = widget_get_prop_int(cf.page, "h", 290), rows = (h - 48) / 48 * 48;
    if (n * 48 < rows) rows = n * 48;
    widget_destroy_children(cf.body);
    widget_set_visible(cf.body, 1, 0);
    cf.title = text(cf.body, CF_X, 0, CF_W, 48);
    widget_set_text_utf8(cf.title, title);
    void *lv = list_view_create(cf.body, 0, 48, 375, rows);
    widget_set_prop_int(lv, "item_height", 48);
    /* The theme's default list_view is a light card; stock pages paint theirs black inline. */
    widget_set_prop_int(lv, "style:normal:bg_color", (int)0xff000000u);
    widget_set_prop_int(lv, "style:normal:border_color", 0);
    void *view = scroll_view_create(lv, 0, 0, 375, rows);
    widget_set_prop_int(view, "yslidable", 1);
    widget_set_prop_int(view, "xslidable", 0);
    widget_set_prop_int(view, "virtual_h", n * 48);
    widget_invalidate_force(cf.page, 0);
    return view;
}

static void row(void *view, int index, const char *caption, int (*click)(void *, void *)) {
    void *item = list_item_create(view, 0, index * 48, 375, 48);
    widget_use_style(item, "s_listitem_black");
    void *label = text(item, CF_ROW_X, 0, CF_ROW_W, 48);
    widget_set_text_utf8(label, caption ? caption : "");
    widget_on(item, EVT_CLICK, click, (void *)(long)index);
}

/* Stock pattern (album rows, Now Playing): load the file, set it, drop the load's reference, so the
 * next paint decodes the file again rather than a stale cached copy. Returns 0 when the load fails,
 * as for the empty "no art" marker. size, if given, gets the image's width and height (bitmap_t
 * w @0, h @4). */
static int show(void *img, const char *url, unsigned *size) {
    unsigned bitmap[64]; /* bitmap_t */
    if (widget_load_image(img, url, bitmap)) return 0;
    if (size) size[0] = bitmap[0], size[1] = bitmap[1];
    image_base_set_image(img, url);
    widget_unload_image(img, bitmap);
    return 1;
}

/* Depth (docs/internals.md#coverflow-depth), after PictureFlow's renderer: every cover within reach
 * of the visual position is projected column by column into one frame bitmap, farthest first, with
 * its reflection, then the frame is drawn over the slide_menu, whose own children stay empty. All
 * integer: 16.16 turns and rotations, geometry in 1/16 px, row spans in 1/256 px. */
#define CF_ONE 65536
#define CF_REACH 3 /* ring slots either side of the centre that can show (fading in) or preload */
#define CF_RING (2 * CF_REACH + 1)
#define CF_TEXELS (ART_SIZE * ART_SIZE)
#define CF_MISS 99
#define CF_EYE16 (16 * CF_EYE)
#define CF_HALF16 (16 * ART_SIZE / 2)
#define CF_MID256 (256 * (CF_TOP + ART_SIZE / 2)) /* the horizon every cover centres on */

/* cos and sin of 0 to CF_ANGLE (60) degrees in 16 steps, 16.16 */
static const int cf_cos[17] = { 65536, 65396, 64975, 64277, 63303, 62058, 60547, 58777, 56756,
                                54491, 51993, 49273, 46341, 43211, 39896, 36410, 32768 };
static const int cf_sin[17] = { 0,     4286,  8554,  12785, 16962, 21066, 25080, 28986, 32768,
                                36410, 39896, 43211, 46341, 49273, 51993, 54491, 56756 };

/* A right-hand cover t (16.16, >= 0) from the visual position: centre xc and depth zc (1/16 px),
 * rotation c, s (16.16) and brightness (of 256). Left covers mirror it. */
typedef struct {
    int xc, zc, c, s, bright;
} pose_t;

static void pose(int t, pose_t *p) {
    int a = t < CF_ONE ? t : CF_ONE, i = a >> 12, f = a & 4095;
    p->c = cf_cos[i] + (i < 16 ? (cf_cos[i + 1] - cf_cos[i]) * f >> 12 : 0);
    p->s = cf_sin[i] + (i < 16 ? (cf_sin[i + 1] - cf_sin[i]) * f >> 12 : 0);
    if (t < CF_ONE) {
        /* xc = A t + B t^2: CF_X1 at t = 1, arriving at the stack's CF_XS slope, and quick at
         * first, so the covers turning in and out mid-step keep clear of each other. */
        int sq = (int)((unsigned)t * (unsigned)t >> 16);
        p->xc = (16 * (2 * CF_X1 - CF_XS) * t + 16 * (CF_XS - CF_X1) * sq) >> 16;
        p->zc = 16 * CF_Z1 * t >> 16;
        p->bright = 256 - ((256 - CF_BRIGHT1) * t >> 16);
    } else {
        int e = t - CF_ONE;
        p->xc = 16 * CF_X1 + (16 * CF_XS * e >> 16);
        p->zc = 16 * CF_Z1 + (16 * CF_ZS * e >> 16);
        p->bright = e < CF_ONE ? CF_BRIGHT1 - ((CF_BRIGHT1 - CF_BRIGHT2) * e >> 16)
                    : e < 2 * CF_ONE ? CF_BRIGHT2 * (2 * CF_ONE - e) >> 16 : 0;
    }
}

/* Screen x (1/16 px right of the centre line) of the cover point u (1/16 px from its middle). */
static int project(const pose_t *p, int u) {
    return (p->xc + (u * p->c >> 16)) * CF_EYE16 / (CF_EYE16 + p->zc - (u * p->s >> 16));
}

/* The cover point under screen x dx (1/16 px right of the centre line), the inverse of project;
 * 0 when the column misses the cover. *h gets the cover's projected height there (1/256 px). */
static int unproject(const pose_t *p, int dx, int *u, int *h) {
    int den = (CF_EYE16 * p->c + dx * p->s) >> 16;
    if (den <= 0) return 0;
    *u = (dx * (CF_EYE16 + p->zc) - CF_EYE16 * p->xc) / den;
    if (*u < -CF_HALF16 || *u >= CF_HALF16) return 0;
    *h = ART_SIZE * 256 * CF_EYE16 / (CF_EYE16 + p->zc - (*u * p->s >> 16));
    return 1;
}

#define HOT static inline __attribute__((always_inline)) /* -Oz would call these per pixel */

/* p scaled by b (of 256), per 8-bit channel; alpha is left 0. */
HOT unsigned shade(unsigned p, unsigned b) {
    return ((p & 0xff00ffu) * b >> 8 & 0xff00ffu) | ((p & 0xff00u) * b >> 8 & 0xff00u);
}

/* The frame being drawn, nearest cover first: each pixel's alpha byte holds the coverage so far
 * (255 opaque), and a layer only fills what is left, which composites as drawing back to front
 * would. Per column, rows solid_top to solid_bottom are known opaque and skipped outright, so the
 * hidden parts of side covers cost nothing. */
typedef struct {
    unsigned *d;
    int pitch;
    short solid_top[CF_VIEW_W], solid_bottom[CF_VIEW_W];
} shelf_t;

/* colour (alpha ignored) under what is already at px, covering cov (of 256) of the pixel */
HOT void put(unsigned *px, unsigned colour, unsigned cov) {
    unsigned a = *px >> 24, have = a + (a >> 7), w = cov * (256 - have) >> 8;
    if (!a && cov == 256) {
        *px = colour | 0xff000000u;
        return;
    }
    if (!w) return;
    have += w;
    *px = ((*px & 0xffffffu) + shade(colour, w)) | (have > 255 ? 255u : have) << 24;
}

/* One texture column (texels ART_SIZE apart) h high (1/256 px) on the horizon at frame column col,
 * its partial end rows by coverage, then its reflection fading out below. */
static void column(shelf_t *f, int col, const unsigned *tex, int h, int bright) {
    if (h < 16) return;
    unsigned *d = f->d + col;
    int top = CF_MID256 - h / 2, bottom = top + h, step = (ART_SIZE << 20) / (h >> 4);
    int solid_top = f->solid_top[col], solid_bottom = f->solid_bottom[col];
    int y = top >> 8, end = (bottom + 255) >> 8, last = end < CF_VIEW_H ? end : CF_VIEW_H;
    int first = y, final = end - 1; /* the rows the edges cross */
    int v = (((y << 8) + 128 - top) >> 4) * step >> 4, pitch = f->pitch; /* v: 16.16 texel row */
    if (y < 0) v -= y * step, y = 0;
    unsigned *px = d + y * pitch;
    while (y < last) {
        if (y >= solid_top && y < solid_bottom) {
            int skip = solid_bottom - y;
            v += skip * step, px += skip * pitch, y = solid_bottom;
            continue;
        }
        int run = y < solid_top && solid_top < last ? solid_top : last; /* up to the opaque span */
        for (; y < run; ++y, v += step, px += pitch) {
            int row = v < 0 ? 0 : v >> 16 >= ART_SIZE ? ART_SIZE - 1 : v >> 16;
            unsigned cov = 256;
            if (y == first || y == final) {
                int from = y << 8 > top ? y << 8 : top, to = (y + 1) << 8 < bottom ? (y + 1) << 8 : bottom;
                cov = (unsigned)(to - from);
            }
            put(px, shade(tex[row * ART_SIZE], (unsigned)bright), cov);
        }
    }
    /* The reflection starts where the body ends, sharing the row the body only partly covers. */
    int reflect = h * CF_REFLECT / ART_SIZE, stop = (bottom + reflect + 255) >> 8;
    int fade = (256 << 16) / reflect; /* fading per 1/256 px, 16.16 */
    unsigned dim = (unsigned)bright * CF_REFLECT_TOP >> 8;
    if (stop > CF_VIEW_H) stop = CF_VIEW_H;
    for (y = bottom >> 8, px = d + y * pitch; y < stop; ++y, px += pitch) {
        int from = y << 8 > bottom ? y << 8 : bottom, dist = ((from + ((y + 1) << 8)) >> 1) - bottom;
        if (dist >= reflect) break;
        if (y < 0 || (y >= solid_top && y < solid_bottom)) continue;
        int mirrored = dist * step >> 8 >> 16; /* texel rows up from the bottom edge */
        int row = ART_SIZE - 1 - (mirrored >= ART_SIZE ? ART_SIZE - 1 : mirrored);
        unsigned cov = (unsigned)(((y + 1) << 8) - from) * (256u - (unsigned)(dist * fade >> 16)) >> 8;
        put(px, shade(tex[row * ART_SIZE], dim), cov);
    }
    /* The rows this body covers whole are opaque now: join them to the known span, or keep the
     * longer of the two. */
    int s0 = (top + 255) >> 8, s1 = bottom >> 8;
    s0 = s0 < 0 ? 0 : s0, s1 = s1 > CF_VIEW_H ? CF_VIEW_H : s1;
    if (s1 <= s0) return;
    if (solid_bottom > solid_top && s0 <= solid_bottom && s1 >= solid_top) {
        s0 = s0 < solid_top ? s0 : solid_top;
        s1 = s1 > solid_bottom ? s1 : solid_bottom;
    } else if (s1 - s0 <= solid_bottom - solid_top)
        return;
    f->solid_top[col] = (short)s0, f->solid_bottom[col] = (short)s1;
}

/* The cover t (16.16, signed) turns from the visual position, under what is drawn. */
static void draw_cover(shelf_t *f, int t, const unsigned *tex) {
    pose_t p;
    int side = t < 0 ? -1 : 1;
    pose(t * side, &p);
    if (p.bright <= 0 || !tex) return;
    int a = project(&p, -CF_HALF16), b = project(&p, CF_HALF16);
    int lo = (16 * CF_CX + (a < b ? a : b)) >> 4, hi = (16 * CF_CX + (a < b ? b : a)) >> 4;
    for (int v = lo; v <= hi; ++v) { /* v: the column as if the cover were on the right */
        int col = side > 0 ? v : 2 * CF_CX - 1 - v, u, h;
        if (col < 0 || col >= CF_VIEW_W || !unproject(&p, (2 * v + 1 - 2 * CF_CX) * 8, &u, &h)) continue;
        int k = (u + CF_HALF16) >> 4;
        column(f, col, tex + (side > 0 ? k : ART_SIZE - 1 - k), h, p.bright);
    }
}

/* The ring slot of the k-th nearest pair's nearer (i 0) or farther (i 1) cover at frac: the side
 * the position is moving away from is farther. */
static int slot(int frac, int k, int i) {
    return (i == 0) == (frac < 0) ? CF_REACH - k : CF_REACH + k;
}

/* The shelf at frac (16.16, -CF_ONE/2 to under CF_ONE/2) past its centre cover: ring[j] is the
 * texture of the cover j - CF_REACH from the centre, or 0 to leave it out. Nearest first; nearer
 * covers and their reflections overlap farther ones. */
void coverflow_render(unsigned *d, int pitch, int frac, const unsigned *const ring[CF_RING]) {
    shelf_t f;
    f.d = d, f.pitch = pitch;
    for (int x = 0; x < CF_VIEW_W; ++x) f.solid_top[x] = f.solid_bottom[x] = 0;
    for (int y = 0; y < CF_VIEW_H; ++y) memset(d + y * pitch, 0, CF_VIEW_W * 4);
    for (int k = 0; k <= CF_REACH; ++k)
        for (int i = 0; i < (k ? 2 : 1); ++i) {
            int j = slot(frac, k, i);
            draw_cover(&f, (j - CF_REACH) * CF_ONE - frac, ring[j]);
        }
    for (int y = 0; y < CF_VIEW_H; ++y) { /* over black; a count-down loop, which -Oz keeps tight */
        unsigned *p = d + y * pitch;
        int x = CF_VIEW_W;
        do *p++ |= 0xff000000u;
        while (--x);
    }
}

/* The ring offset of the frontmost cover (not its reflection) at frame pixel x, y, as drawn at
 * frac, or CF_MISS. Nearest first, in the drawing order. */
int coverflow_hit(int frac, int x, int y) {
    for (int k = 0; k <= CF_REACH; ++k)
        for (int i = 0; i < (k ? 2 : 1); ++i) {
            int j = slot(frac, k, i), t = (j - CF_REACH) * CF_ONE - frac;
            pose_t p;
            int side = t < 0 ? -1 : 1, v = side > 0 ? x : 2 * CF_CX - 1 - x, u, h;
            pose(t * side, &p);
            if (p.bright > 0 && unproject(&p, (2 * v + 1 - 2 * CF_CX) * 8, &u, &h) &&
                (y << 8) + 128 >= CF_MID256 - h / 2 && (y << 8) + 128 < CF_MID256 - h / 2 + h)
                return j - CF_REACH;
        }
    return CF_MISS;
}

/* The depth renderer's state: the frame, the textures of the covers around the visual position
 * and the placeholder's. No frame: the flat fallback (stock images on the slide_menu). */
static struct {
    void *frame;                  /* bitmap_t *, CF_VIEW_W x CF_VIEW_H RGBA8888 */
    unsigned *tex;                /* CF_RING texture slots, then the placeholder */
    int album[CF_RING];           /* each slot's album + 1; 0 is empty */
    const unsigned *art[CF_RING]; /* its texture: the slot's own, or the placeholder */
    int c, frac, drawn;           /* the position the frame holds, once drawn */
} fx __attribute__((section(".scratch")));

/* A decoded image copied into a texture: its centred square, nearest sampled to ART_SIZE, over
 * black. Only 32-bit formats (BITMAP_RGBA_AT); stock decodes covers to RGBA8888 with straight
 * alpha. The image manager's copy is only
 * read, and a cover's load is dropped again at once, as stock does. */
static int decode(const char *url, unsigned *out, int unload) {
    static const unsigned char at[4][4] = BITMAP_RGBA_AT;
    unsigned bitmap[64]; /* bitmap_t */
    if (widget_load_image(cf.page, url, bitmap)) return 0;
    unsigned w = bitmap[0], h = bitmap[1], format = ((unsigned short *)bitmap)[7] - 1u;
    const unsigned char *data =
        format < 4 && w && h && w <= 4096 && h <= 4096 ? bitmap_lock_buffer_for_read(bitmap) : 0;
    if (data) {
        const unsigned char *o = at[format];
        unsigned stride = bitmap_get_line_length(bitmap), side = w < h ? w : h, xoff[ART_SIZE];
        const unsigned char *base = data + (h - side) / 2 * stride + (w - side) / 2 * 4;
        for (unsigned x = 0; x < ART_SIZE; ++x) xoff[x] = x * side / ART_SIZE * 4;
        for (unsigned y = 0; y < ART_SIZE; ++y) {
            const unsigned char *line = base + y * side / ART_SIZE * stride;
            for (unsigned x = 0; x < ART_SIZE; ++x) {
                const unsigned char *px = line + xoff[x];
                unsigned a = px[o[3]], r = px[o[0]], g = px[o[1]], b = px[o[2]];
                if (a < 255) r = r * a / 255, g = g * a / 255, b = b * a / 255; /* over black */
                *out++ = 0xff000000u | r | g << 8 | b << 16;
            }
        }
        bitmap_unlock_buffer(bitmap);
    }
    if (unload) widget_unload_image(cf.page, bitmap);
    return data != 0;
}

static void fx_close(void) {
    if (fx.frame) bitmap_destroy(fx.frame);
    free(fx.tex);
    memset(&fx, 0, sizeof(fx));
}

/* The frame and every texture at once, or neither: the flat covers then stand in. */
static int fx_open(void) {
    fx.frame = bitmap_create_ex(CF_VIEW_W, CF_VIEW_H, CF_VIEW_W * 4, 1 /* RGBA8888 */);
    fx.tex = fx.frame ? calloc(CF_RING + 1, CF_TEXELS * 4) : 0;
    if (!fx.tex) {
        fx_close();
        return 0;
    }
    *(unsigned short *)((char *)fx.frame + 0xc) |= 1; /* BITMAP_FLAG_OPAQUE: every pixel is */
    unsigned *placeholder = fx.tex + CF_RING * CF_TEXELS;
    if (!decode(PLACEHOLDER, placeholder, 0)) /* a theme image: the manager keeps it */
        for (int i = 0; i < CF_TEXELS; ++i) placeholder[i] = 0xff3a3a3au;
    return 1;
}

/* Album a's cached art in buf, else the placeholder (no art, or the Refresh card). */
static const unsigned *fx_load(int a, unsigned *buf) {
    char url[600] = "file://";
    if ((unsigned)a < deque_size(cf.albums)) {
        art_path(url + 7, album_key(deque_at(cf.albums, (unsigned)a)), "");
        if (decode(url, buf, 1)) return buf;
    }
    return fx.tex + CF_RING * CF_TEXELS;
}

/* The CF_RING covers around album c of n stay decoded, others are dropped as movement crosses
 * albums; ring gets each ring slot's texture. A small library repeats albums round the ring, as
 * the slide_menu wraps. */
static void fx_window(int c, int n, const unsigned *ring[CF_RING]) {
    int want[CF_RING];
    for (int j = 0; j < CF_RING; ++j) want[j] = ((c + j - CF_REACH) % n + n) % n + 1;
    for (int i = 0; i < CF_RING; ++i) {
        int keep = 0;
        for (int j = 0; j < CF_RING; ++j) keep |= fx.album[i] == want[j];
        if (!keep) fx.album[i] = 0;
    }
    for (int j = 0; j < CF_RING; ++j) {
        int i = 0;
        while (i < CF_RING && fx.album[i] != want[j]) ++i;
        if (i == CF_RING) { /* at most CF_RING albums are wanted, so a slot is free */
            for (i = 0; fx.album[i]; ++i) {}
            fx.album[i] = want[j];
            fx.art[i] = fx_load(want[j] - 1, fx.tex + i * CF_TEXELS);
            fx.drawn = 0;
        }
        ring[j] = fx.art[i];
    }
}

static int floor_div(int a, int b) { /* floor division, b > 0 */
    return a / b - (a % b < 0);
}

/* The visual position from the slide_menu's index and live offset (the wheel's animator, a snap or
 * a finger): album c (of n) at the centre, frac past it and the offset q in albums that it is from
 * the index. Stock completion commits index - offset / stride. */
static int visual(void *s, int n, int *c, int *frac, int *q) {
    int stride = slide_menu_item_width(s) + I(s, SLIDE_SPACER), d = -I(s, SLIDE_OFFSET);
    if (n <= 0 || stride <= 0) return 0;
    *q = floor_div(2 * d + stride, 2 * stride);
    *frac = (d - *q * stride) * CF_ONE / stride;
    *c = ((I(s, SLIDE_INDEX) + *q) % n + n) % n;
    return stride;
}

/* ringnav_paint (the border hook, after stock painted the slide_menu's empty children) calls this
 * for every widget: over Coverflow's slide_menu it draws the frame, rendered again only when the
 * position or a texture has changed. */
void coverflow_paint(void *w, void *canvas) {
    int c, frac, q, n;
    if (!w || w != cf.slide || !fx.frame || cf.screen != COVERS ||
        !visual(w, n = (int)widget_count_children(w), &c, &frac, &q))
        return;
    const unsigned *ring[CF_RING];
    fx_window(c, n, ring);
    if (!fx.drawn || c != fx.c || frac != fx.frac) {
        unsigned *d = (unsigned *)bitmap_lock_buffer_for_write(fx.frame);
        if (!d) return;
        coverflow_render(d, (int)(bitmap_get_line_length(fx.frame) / 4), frac, ring);
        bitmap_unlock_buffer(fx.frame);
        fx.c = c, fx.frac = frac, fx.drawn = 1;
    }
    int r[4] = { 0, 0, CF_VIEW_W, CF_VIEW_H };
    canvas_draw_image(canvas, fx.frame, r, r);
}

/* A tap on the covers (pressed, not dragged): the frontmost projected cover under the finger. The
 * centre one at rest opens, as a click on it would; a side one scrolls to the centre through stock
 * scroll_to and completion. A tap while the covers move only ends the press. */
static int tap(void *event) {
    void *s = cf.slide;
    unsigned char *drag = s ? (unsigned char *)s + SLIDE_DRAG : 0;
    if (!drag || !fx.frame || cf.screen != COVERS || !drag[1] || drag[0]) return 0;
    widget_ungrab(P(s, W_PARENT), s);
    drag[1] = 0;
    int c, frac, q, point[2] = { I(event, EVENT_X), I(event, EVENT_Y) };
    int stride = visual(s, (int)widget_count_children(s), &c, &frac, &q);
    if (!stride || P(s, SLIDE_ANIMATOR)) return 1;
    widget_to_local(s, point);
    int j = coverflow_hit(frac, point[0], point[1]), goal = -(q + j) * stride;
    if (j == CF_MISS) return 1;
    if (!j && !frac)
        pick((void *)(long)c, 0);
    else if (goal == I(s, SLIDE_OFFSET))
        slide_menu_on_scroll_done(s, 0);
    else
        slide_menu_scroll_to(s, goal);
    return 1;
}

static void cover(void *img, unsigned i, int near) {
    char url[600] = "file://";
    near = near && i < deque_size(cf.albums);
    if (near) art_path(url + 7, album_key(deque_at(cf.albums, i)), "");
    if (tk_strcmp(widget_get_prop_str(img, "image", ""), near ? url : PLACEHOLDER) &&
        (!near || !show(img, url, 0)))
        image_base_set_image(img, PLACEHOLDER);
}

static int changed(void *ctx, void *event) {
    (void)ctx;
    (void)event;
    unsigned n = widget_count_children(cf.slide), c = (unsigned)I(cf.slide, SLIDE_INDEX);
    for (unsigned i = 0; !fx.frame && i < n; ++i) { /* the flat fallback's own images */
        unsigned d = i > c ? i - c : c - i;
        cover(widget_get_child(cf.slide, i), i, d <= ART_NEAR || n - d <= ART_NEAR);
    }
    void *r = c + 1 < n ? deque_at(cf.albums, c) : (void *)0;
    if (r) cf.saved_album = album_key(r);
    widget_set_text_utf8(cf.name, r ? P(r, REC_ALBUM) : "Refresh library");
    widget_set_text_utf8(cf.artist, r && P(r, REC_ARTIST) ? P(r, REC_ARTIST) : "");
    return 0;
}

/* Finish a drag on the nearest cover as stock scroll_to (0x5f3400) would: 150 ms, then stock
 * completion commits the index. The stale drag flags and grab that pointer-up would have cleared
 * go first. Returns whether there was a drag to finish. */
static int snap(void) {
    void *s = cf.slide;
    if (!s || cf.screen != COVERS || P(s, SLIDE_ANIMATOR)) return 0;
    unsigned char *drag = (unsigned char *)s + SLIDE_DRAG;
    int live = I(s, SLIDE_OFFSET), stride = slide_menu_item_width(s) + I(s, SLIDE_SPACER);
    if ((!live && !drag[0]) || stride <= 0) return 0;
    if (drag[1]) widget_ungrab(P(s, W_PARENT), s);
    drag[0] = drag[1] = 0;
    int goal = (live + (live < 0 ? -stride : stride) / 2) / stride * stride;
    if (goal == live) /* stock scroll_to returns without an animator here */
        slide_menu_on_scroll_done(s, 0);
    else
        slide_menu_scroll_to(s, goal);
    return 1;
}

/* Stock's pointer-up (0x5f3c80) throws a drag on by its velocity: a whole cover past the finger
 * for a swipe under 200 ms, else velocity % cover width. So drags finish here first, on the page
 * before the slide_menu sees the release, where the finger left them. Taps on the drawn covers
 * are hit-tested first (tap), so one on covers resting between albums still picks the cover under
 * the finger; in the flat fallback taps still reach stock. */
static int released(void *ctx, void *event) {
    (void)ctx;
    return tap(event) || snap() ? 11 : 0; /* RET_STOP; a tap even while the covers rest off-grid */
}

/* Some releases never reach the page or the slide_menu, leaving the covers between two albums,
 * so while Covers shows a repeating check also finishes any drag at rest. */
static int settle(const void *unused) {
    (void)unused;
    if (!window_manager_get_pointer_pressed(window_manager())) snap();
    return 8; /* RET_REPEAT */
}

/* One child per album plus a last Refresh card. With depth the slide_menu spans the frame, so
 * every step and drag repaints all of it, and its CF_VIEW_H square items with a negative spacer
 * move one album per CF_STRIDE px; the children stay empty under the frame. The flat fallback is
 * the stock images, 160 px, as before. ponytail: one child per album; if large libraries lag on
 * hardware, virtualize to a recycled window of children. */
static void covers(void) {
    cf.screen = COVERS;
    widget_set_visible(cf.body, 0, 0);
    if (!cf.covers) {
        void *f = widget_factory();
        int depth = fx_open();
        cf.covers = widget_factory_create_widget(f, "view", cf.page, 0, 0, 375, 290);
        cf.slide = widget_factory_create_widget(f, "slide_menu", cf.covers, 0, depth ? 0 : 24, 375,
                                                depth ? CF_VIEW_H : ART_SIZE);
        if (depth) slide_menu_set_spacer(cf.slide, CF_STRIDE - CF_VIEW_H);
        for (unsigned i = 0, n = deque_size(cf.albums); i <= n; ++i) {
            void *img = image_create(cf.slide, 0, 0, 0, 0);
            image_set_draw_type(img, 4); /* scale_auto, as the stock cover rows */
            if (!depth) image_base_set_image(img, PLACEHOLDER);
            widget_set_prop_int(img, "clickable", 1);
            widget_on(img, EVT_CLICK, pick, (void *)(long)i);
        }
        /* Album over artist under the frame, white and larger, then grey, clear of the rounded
         * glass (docs/ipod.md#coverflow); the same in both builds. */
        cf.name = text(cf.covers, CF_EDGE, CF_TEXT_Y, 375 - 2 * CF_EDGE, CF_NAME_H);
        widget_set_prop_int(cf.name, "style:normal:font_size", CF_NAME_PX);
        cf.artist = text(cf.covers, CF_EDGE, CF_TEXT_Y + CF_NAME_H, 375 - 2 * CF_EDGE, CF_ARTIST_H);
        widget_set_prop_int(cf.artist, "style:normal:font_size", CF_ARTIST_PX);
        widget_set_prop_int(cf.artist, "style:normal:text_color", (int)CF_GREY);
        slide_menu_set_value(cf.slide, cf.album);
        widget_on(cf.slide, EVT_VALUE_CHANGED, changed, 0);
        changed(0, 0);
    }
    widget_set_visible(cf.covers, 1, 0);
    widget_invalidate_force(cf.page, 0);
    rearm(&cf.timer, settle, 100);
}

static int to_covers(const void *unused) {
    (void)unused;
    cf.timer = 0;
    stop();
    covers();
    return 0;
}

static int cancel_row(void *ctx, void *event) {
    (void)ctx;
    (void)event;
    rearm(&cf.timer, to_covers, 0);
    return 0;
}

static int poll(const void *unused) {
    (void)unused;
    cf.timer = 0;
    if (cf.done == cf.total) return to_covers(0); /* stop() joins the thread's last steps */
    char progress[64];
    tk_snprintf(progress, sizeof(progress), "Preparing artwork\xe2\x80\xa6 %d/%d", cf.done,
                cf.total);
    widget_set_text_utf8(cf.title, progress);
    cf.timer = timer_add(poll, 0, 250);
    return 0;
}

/* The centre album outlives a reboot: read once while unknown, written on
 * leaving the covers. */
static void remember(int write) {
    void *f = fopen(LAST_ALBUM, write ? "wb" : "rb");
    if (!f) return;
    if (write)
        fwrite(&cf.saved_album, sizeof(cf.saved_album), 1, f);
    else if (fread(&cf.saved_album, sizeof(cf.saved_album), 1, f) != 1)
        cf.saved_album = 0;
    fclose(f);
}

/* On open and Refresh: the albums, then art for the ones with no cache file (PictureFlow's
 * first-launch build; later opens resume). The albums are queried again only on Refresh or after
 * the library changed: stock's sort converts both names to pinyin on every comparison.
 * check_database(): refuse an empty, unbuilt or scanning library. */
static void load(void) {
    drop();
    widget_destroy_children(cf.page);
    cf.covers = cf.slide = cf.name = cf.artist = 0; /* destroyed with the page's children */
    cf.album = 0;
    cf.body = widget_factory_create_widget(widget_factory(), "view", cf.page, 0, 0, 375, 290);
    int n = 0;
    unsigned gen = library_gen;
    if (cf.albums_gen != gen) drop_albums();
    if (cf.albums)
        n = (int)deque_size(cf.albums);
    else if (!*(volatile int *)SCAN_THREAD || *(volatile int *)SCAN_DONE) {
        cf.albums = staged(albums, 0, &n);
        cf.albums_gen = gen;
    }
    if (n <= 0) {
        drop_albums(); /* only a real list is kept */
        cf.screen = COVERS; /* Return goes Home */
        list("Update Local Music first", 0);
        return;
    }
    unsigned count = deque_size(cf.albums), fs[32] = { 0 };
    char path[512];
    if (!cf.saved_album) remember(0);
    cf.jobs = calloc(count, sizeof(job_t));
    for (unsigned i = 0; i < count; ++i) {
        void *r = deque_at(cf.albums, i);
        unsigned key = album_key(r);
        if (key == cf.saved_album) cf.album = (int)i;
        if (cf.jobs && P(r, REC_PATH) && access(art_path(path, key, ""), 0) &&
            (cf.jobs[cf.total].track = strdup(P(r, REC_PATH))))
            cf.jobs[cf.total++].key = key;
    }
    mkdir(ART_DIR, 0755);
    cf.done = cf.cancel = 0;
    /* statfs, MIPS o32 layout: f_bsize is word 1, f_bavail word 7. */
    if (cf.total && !statfs(ART_DIR, fs) &&
        (unsigned long long)fs[7] * fs[1] >= (unsigned long long)ART_MIN_FREE_MB << 20 &&
        !pthread_create(&cf.thread, 0, worker, 0)) {
        cf.running = 1;
        cf.screen = PREPARING;
        row(list("", 1), 0, "Cancel", cancel_row);
        poll(0);
    } else
        to_covers(0);
}

/* Folder play (startPlayFolderSong): classType 1 over our deque. playing_page's mclLoadPlayList
 * copies it synchronously, and memory-play later reloads the last track's folder. */
static int play(void *ctx, void *event) {
    (void)event;
    int i = (int)(long)ctx;
    void *t = deque_at(cf.tracks, (unsigned)i);
    if (!t || access(P(t, REC_PATH), 0)) {
        widget_set_text_utf8(cf.title, "Storage unavailable");
        return 0;
    }
    struct {
        void *dq;
        int idx, cls, mode;
    } context = { cf.tracks, i, 1, 2 };
    navigator_to_with_context("playing_page", &context);
    return 0;
}

static int to_tracks(const void *unused) {
    (void)unused;
    cf.timer = 0;
    int n;
    void *r = deque_at(cf.albums, (unsigned)cf.album);
    cf.saved_album = album_key(r);
    remember(1); /* a power-off on the tracks keeps it too */
    if (cf.tracks) deque_destroy(cf.tracks);
    cf.tracks = staged(albums, r, &n);
    n = (int)deque_size(cf.tracks);
    cf.screen = TRACKS;
    widget_set_visible(cf.covers, 0, 0);
    void *view = list(P(r, REC_ALBUM), n);
    for (int i = 0; i < n; ++i) row(view, i, P(deque_at(cf.tracks, (unsigned)i), REC_NAME), play);
    return 0;
}

static int refresh(const void *unused) {
    (void)unused;
    cf.timer = 0;
    void *dir = opendir(ART_DIR);
    for (struct dirent *e; dir && (e = readdir(dir));) {
        char path[600];
        snprintf(path, sizeof(path), ART_DIR "/%s", e->d_name);
        unlink(path); /* "." and ".." fail harmlessly */
    }
    if (dir) closedir(dir);
    drop_albums();
    load();
    return 0;
}

/* Clicks only schedule: a screen change never destroys the widget whose click is running. */
static int pick(void *ctx, void *event) {
    (void)event;
    int i = (int)(long)ctx;
    if (i == (int)deque_size(cf.albums))
        rearm(&cf.timer, refresh, 0);
    else {
        cf.album = i;
        rearm(&cf.timer, to_tracks, 0);
    }
    return 0;
}

/* Return: tracks -> covers (the slide_menu kept its album), preparing -> cancel and covers,
 * covers or the message -> Home. */
static int keyup(void *ctx, void *event) {
    (void)ctx;
    if (I(event, EVENT_KEY) != KEY_RETURN) return 0;
    if (cf.screen == TRACKS || cf.screen == PREPARING)
        rearm(&cf.timer, to_covers, 0);
    else
        navigator_back_to_home();
    return 11; /* RET_STOP */
}

static int closed(void *ctx, void *event) {
    (void)ctx;
    (void)event;
    if (cf.saved_album) remember(1);
    drop();
    cf.page = cf.body = cf.covers = cf.slide = 0;
    return 0;
}

static int coverflow_open(void *ctx, void *event) {
    (void)ctx;
    (void)event;
    if (cf.page) return 0;
    void *page = window_create(0, 0, 0, 0, 0);
    if (!page) return 0;
    cf.page = page;
    widget_set_name(page, "coverflow_page");
    widget_set_prop_int(page, "style:normal:bg_color", (int)0xff000000u);
    widget_on(page, EVT_DESTROY, closed, 0);
    widget_on(page, EVT_KEY_UP, keyup, 0);
    widget_on(page, EVT_POINTER_UP_BEFORE, released, 0);
    load();
    return 0;
}

#if IPOD
/* iPod Home (docs/ipod.md): the playing track's art beside the list. */
static struct {
    void *win, *art, *list;
    unsigned key;
    int split_w;  /* the list's width in the asset */
    int panel[4]; /* the art's x, y, w, h in the asset: the right panel it fills */
    int clip[4];  /* the canvas clip while the art paints, restored after */
    int clipped;
} home __attribute__((section(".scratch")));
extern int ipod_home_full(void);

/* player_parsecover_thd writes the playing track's cover and then sets g_playcover_type, as Now
 * Playing reads it: 1 embedded, 2 folder image, 4 downloaded; 0 while parsing or stopped, 3 none.
 * Tidal's (5) is keyed by its online URL, never a queue path, so Home leaves it out. */
static const char *const player_covers[] = { 0, "file://" PEQ_ROOT "/tmp/coverpic.jpg",
                                             "file://" PEQ_ROOT "/tmp/externpic.jpg", 0,
                                             "file://" PEQ_ROOT "/tmp/externpic.jpg" };

/* The queue's playing record, or 0; *pos and *n get its index and the queue length. */
void *queue_now(unsigned *pos, unsigned *n) {
    void *queue = P(mcl_pdeqplaylist, 0);
    *pos = *(volatile unsigned *)MCL_POS;
    *n = queue ? deque_size(queue) : 0;
    return *pos < *n ? deque_at(queue, *pos) : (void *)0;
}

/* Sizes the art to a w x h bitmap's proportions, just covering the panel and centred on it, so
 * the native fill draws it whole and the clip crops it evenly; unknown sizes fill the panel. */
static void home_fit(unsigned w, unsigned h) {
    int pw = home.panel[2], ph = home.panel[3], fw = pw, fh = ph;
    if (w && h && w <= 8192 && h <= 8192) {
        if ((unsigned)pw * h > (unsigned)ph * w)
            fh = (int)(((unsigned)pw * h + w - 1) / w);
        else
            fw = (int)(((unsigned)ph * w + h - 1) / h);
    }
    widget_move_resize(home.art, home.panel[0] + (pw - fw) / 2, home.panel[1] + (ph - fh) / 2, fw, fh);
}

/* The player's cover, else the Coverflow cache of the track's album, else the placeholder. The
 * player's files belong to the track whose path it copies to g_lastcover_url after writing them,
 * so right after a track change they count only once that is this track. Runs whenever Home or
 * the status bar paints (at least once a second) and reloads only when the track or the cover it
 * can use changes. */
void coverflow_home_art(void *top) {
    if (!home.art || top != home.win || !widget_get_visible(home.art)) return;
    unsigned pos, n;
    void *r = queue_now(&pos, &n);
    const char *path = r ? P(r, REC_PATH) : (void *)0;
    unsigned char type = path && !tk_strcmp((const char *)g_lastcover_url, path) ? g_playcover_type : 0;
    unsigned key = hash_bytes(fnv(FNV_SEED, (const unsigned char *)path), &type, 1);
    if (key == home.key) return;
    home.key = key;
    const char *cover = type < sizeof(player_covers) / sizeof(*player_covers) ? player_covers[type] : 0;
    unsigned size[2] = { 0, 0 };
    int shown = cover && show(home.art, cover, size);
    if (!shown && r) {
        char url[600] = "file://";
        art_path(url + 7, album_key(r), "");
        shown = show(home.art, url, size);
    }
    if (!shown && !show(home.art, PLACEHOLDER, size)) image_base_set_image(home.art, PLACEHOLDER);
    home_fit(size[0], size[1]);
    widget_invalidate_force(home.art, 0);
}

/* The art paints only inside the panel: ringnav_paint_bg narrows the canvas clip (screen
 * coordinates; the canvas origin is the art's) before stock draws it, and ringnav_paint puts the
 * old clip back after. */
void coverflow_home_clip(void *w, void *canvas, int begin) {
    if (!w || w != home.art) return;
    if (!begin) {
        if (home.clipped) canvas_set_clip_rect(canvas, home.clip);
        home.clipped = 0;
        return;
    }
    int *old = home.clip, clip[4];
    canvas_get_clip_rect(canvas, old);
    int x = I(canvas, CANVAS_X) - I(w, W_X) + home.panel[0];
    int y = I(canvas, CANVAS_Y) - I(w, W_Y) + home.panel[1];
    int right = x + home.panel[2], bottom = y + home.panel[3];
    clip[0] = old[0] > x ? old[0] : x;
    clip[1] = old[1] > y ? old[1] : y;
    clip[2] = (old[0] + old[2] < right ? old[0] + old[2] : right) - clip[0];
    clip[3] = (old[1] + old[3] < bottom ? old[1] + old[3] : bottom) - clip[1];
    if (clip[2] < 0) clip[2] = 0;
    if (clip[3] < 0) clip[3] = 0;
    canvas_set_clip_rect(canvas, clip);
    home.clipped = 1;
}

/* A widget and its descendants other than labels take the width, the list and its scroll view
 * `outer` and the rows and their tap images `inner`; labels keep theirs. */
static void home_width(void *w, int outer, int inner, int depth) {
    widget_move_resize(w, I(w, W_X), I(w, W_Y), depth < 2 ? outer : inner, I(w, W_H));
    for (unsigned i = 0, n = widget_count_children(w); i < n; ++i) {
        void *child = widget_get_child(w, i);
        if (tk_strcmp(widget_get_type(child), "hscroll_label")) home_width(child, outer, inner, depth + 1);
    }
}

/* The Home setting: Split keeps the asset's list and art; Full widens the list, so the selection
 * bar spans the window, and its rows and tap targets to HOME_FULL_ROW, so the chevrons mirror the
 * labels' margin clear of the corners, and hides the art. */
void coverflow_home_layout(void) {
    if (!home.list) return;
    int full = ipod_home_full();
    home_width(home.list, full ? 375 : home.split_w, full ? HOME_FULL_ROW : home.split_w, 0);
    widget_set_visible(home.art, !full, 0);
    home.key = ~0u; /* Split shows the current art again */
}
#endif

/* home_page_init: stock binds the name-matched img_* cards, then the Coverflow card binds here,
 * on its image as stock does, whatever stock returned. */
int coverflow_home(void *win, void *ctx) {
    int result = stock_home_trampoline(win, ctx);
    widget_on(widget_lookup(win, "img_coverflow", 1), EVT_CLICK, coverflow_open, 0);
#if IPOD
    home.win = win;
    void *art = widget_lookup(win, "img_homeart", 1);
    home.art = art;
    home.clipped = 0;
    for (int i = 0; art && i < 4; ++i) home.panel[i] = I(art, W_X + 4 * i); /* x, y, w, h */
    /* A fitted cover reaches under the list; taps there must still find the rows. */
    if (art) widget_set_sensitive(art, 0);
    void *list = widget_lookup(win, "list_view_home", 1);
    home.list = list; /* a new Home window's own, so still the asset's width */
    home.split_w = list ? I(list, W_W) : 0;
    coverflow_home_layout();
#endif
    return result;
}
