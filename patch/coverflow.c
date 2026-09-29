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

extern int stock_home_trampoline(void *win, void *ctx);
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
    unsigned saved_album;
    int screen, album, running;
    volatile int done, total, cancel;
} cf __attribute__((section(".scratch")));

static int pick(void *ctx, void *event);

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

static void drop(void) {
    stop();
    if (cf.albums) deque_destroy(cf.albums);
    if (cf.tracks) deque_destroy(cf.tracks);
    cf.albums = cf.tracks = 0;
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
 * as for the empty "no art" marker. */
static int show(void *img, const char *url) {
    unsigned bitmap[64]; /* bitmap_t */
    if (widget_load_image(img, url, bitmap)) return 0;
    image_base_set_image(img, url);
    widget_unload_image(img, bitmap);
    return 1;
}

static void cover(void *img, unsigned i, int near) {
    char url[600] = "file://";
    near = near && i < deque_size(cf.albums);
    if (near) art_path(url + 7, album_key(deque_at(cf.albums, i)), "");
    if (tk_strcmp(widget_get_prop_str(img, "image", ""), near ? url : PLACEHOLDER) &&
        (!near || !show(img, url)))
        image_base_set_image(img, PLACEHOLDER);
}

static int changed(void *ctx, void *event) {
    (void)ctx;
    (void)event;
    unsigned n = widget_count_children(cf.slide), c = (unsigned)I(cf.slide, SLIDE_INDEX);
    for (unsigned i = 0; i < n; ++i) {
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
 * before the slide_menu sees the release, where the finger left them; taps still reach stock. */
static int released(void *ctx, void *event) {
    (void)ctx;
    (void)event;
    return snap() ? 11 : 0; /* RET_STOP */
}

/* Some releases never reach the page or the slide_menu, leaving the covers between two albums,
 * so while Covers shows a repeating check also finishes any drag at rest. */
static int settle(const void *unused) {
    (void)unused;
    if (!window_manager_get_pointer_pressed(window_manager())) snap();
    return 8; /* RET_REPEAT */
}

/* One image per album plus a last Refresh card. ponytail: one child per album; if large
 * libraries lag on hardware, virtualize to a recycled window of children. */
static void covers(void) {
    cf.screen = COVERS;
    widget_set_visible(cf.body, 0, 0);
    if (!cf.covers) {
        void *f = widget_factory();
        cf.covers = widget_factory_create_widget(f, "view", cf.page, 0, 0, 375, 290);
        cf.slide = widget_factory_create_widget(f, "slide_menu", cf.covers, 0, 24, 375, ART_SIZE);
        for (unsigned i = 0, n = deque_size(cf.albums); i <= n; ++i) {
            void *img = image_create(cf.slide, 0, 0, 0, 0);
            image_set_draw_type(img, 4); /* scale_auto, as the stock cover rows */
            image_base_set_image(img, PLACEHOLDER);
            widget_set_prop_int(img, "clickable", 1);
            widget_on(img, EVT_CLICK, pick, (void *)(long)i);
        }
#if IPOD /* album over artist: white and larger, then grey (docs/ipod.md#coverflow) */
        int y = 24 + ART_SIZE + CF_GAP;
        cf.name = text(cf.covers, CF_X, y, CF_W, CF_NAME_H);
        widget_set_prop_int(cf.name, "style:normal:font_size", CF_NAME_PX);
        cf.artist = text(cf.covers, CF_X, y + CF_NAME_H + CF_LINE_GAP, CF_W, CF_ARTIST_H);
        widget_set_prop_int(cf.artist, "style:normal:font_size", CF_ARTIST_PX);
        widget_set_prop_int(cf.artist, "style:normal:text_color", (int)CF_GREY);
#else
        cf.name = text(cf.covers, 0, ART_SIZE + 38, 375, 36);
        widget_set_prop_int(cf.name, "style:normal:font_size", 28);
        cf.artist = text(cf.covers, 0, ART_SIZE + 74, 375, 28);
#endif
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

/* On open and Refresh: the albums, then art for the ones with no cache file (PictureFlow's
 * first-launch build; later opens resume). check_database(): refuse an empty, unbuilt or
 * scanning library. */
static void load(void) {
    drop();
    widget_destroy_children(cf.page);
    cf.covers = 0;
    cf.album = 0;
    cf.body = widget_factory_create_widget(widget_factory(), "view", cf.page, 0, 0, 375, 290);
    int n = 0;
    if (!*(volatile int *)SCAN_THREAD || *(volatile int *)SCAN_DONE)
        cf.albums = staged(albums, 0, &n);
    if (n <= 0) {
        cf.screen = COVERS; /* Return goes Home */
        list("Update Local Music first", 0);
        return;
    }
    unsigned count = deque_size(cf.albums), fs[32] = { 0 };
    char path[512];
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
    int split_w; /* the list's width in the asset */
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
    int shown = cover && show(home.art, cover);
    if (!shown && r) {
        char url[600] = "file://";
        art_path(url + 7, album_key(r), "");
        shown = show(home.art, url);
    }
    if (!shown) image_base_set_image(home.art, PLACEHOLDER);
    widget_invalidate_force(home.art, 0);
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
    home.art = widget_lookup(win, "img_homeart", 1);
    void *list = widget_lookup(win, "list_view_home", 1);
    home.list = list; /* a new Home window's own, so still the asset's width */
    home.split_w = list ? I(list, W_W) : 0;
    coverflow_home_layout();
#endif
    return result;
}
