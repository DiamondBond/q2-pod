/* Coverflow (COVERFLOW.md): the stock Local Music albums on a stock slide_menu, the way
 * PictureFlow reads Rockbox's database. No tag reads: albums and tracks come from the stock library
 * queries, and the only thing Coverflow owns is a thumbnail cache, built on a modal screen by one
 * pthread that touches only files, the two stock art locks and the volatile counters below. */
#include "offsets.inc"
#include "peq.h"
#ifndef PEQ_HOST
#include "stock.h"
#endif

#define ART_DIR PEQ_ROOT "/mnt/data/coverflow-art"
#define ART_SIZE 160
#define ART_MIN_FREE_MB 16 /* no build below this much free space on /mnt/data */
#define ART_NEAR 3 /* real art only this many covers either side, like PictureFlow's cache */
#define PLACEHOLDER "default_album_big"
#define STOP 11
#define I(p, o) (*(int *)((char *)(p) + (o)))
#define P(p, o) (*(void **)((char *)(p) + (o)))

extern int stock_home_trampoline(void *win, void *ctx);

enum { MESSAGE, PREPARING, COVERS, TRACKS };
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
    int screen, album, running;
    volatile int done, total, cancel, finished;
} cf __attribute__((section(".scratch")));

static int changed(void *ctx, void *event);
static int pick(void *ctx, void *event);
static int play(void *ctx, void *event);
static int cancel_row(void *ctx, void *event);

static unsigned fnv(unsigned h, const unsigned char *s) {
    while (s && *s) h = (h ^ *s++) * 16777619u;
    return h * 16777619u; /* a separator, so "ab"+"c" and "a"+"bc" differ */
}

static unsigned album_key(void *r) {
    return fnv(fnv(2166136261u, P(r, REC_ARTIST)), P(r, REC_ALBUM));
}

/* ART_DIR/<key>.jpg<suffix>, formatted by hand so the UI thread needs no libc for it. */
static char *art_path(char *out, unsigned key, const char *suffix) {
    char *p = out;
    for (const char *s = ART_DIR "/"; *s;) *p++ = *s++;
    for (int i = 28; i >= 0; i -= 4) *p++ = "0123456789abcdef"[key >> i & 15];
    for (const char *s = ".jpg"; *s;) *p++ = *s++;
    while ((*p++ = *suffix++)) {}
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
    void *f = fopen(dst, "w");
    if (f) fclose(f);
}

static void *worker(void *unused) {
    (void)unused;
    while (cf.done < cf.total && !cf.cancel) {
        build_art(&cf.jobs[cf.done]);
        ++cf.done;
    }
    cf.finished = 1;
    return 0;
}

/* Cancel stops after the current album; finished thumbnails stay, so the next open resumes. */
static void stop(void) {
    if (cf.running) {
        cf.cancel = 1;
        pthread_join(cf.thread, 0);
        cf.running = 0;
    }
    if (cf.timer) timer_remove(cf.timer);
    cf.timer = 0;
    for (int i = 0; i < cf.total; ++i) free(cf.jobs[i].track);
    free(cf.jobs);
    cf.jobs = 0;
    cf.total = cf.done = 0;
}

/* A stock library query (getAllAlbum, as load_localclass_list 0xf003 runs it, or the album's
 * getMusicByAlbum, as its row opens it) copied out of the staging deque, which is restored so
 * the query leaves no trace. Stock order, including the trailing "Unknown Album" (id -1) row. */
static void *query(void *album, int *count) {
    void *dir = P(tools_pdeq_directory, 0), *save = _create_deque("stSongInfo"),
         *out = _create_deque("stSongInfo");
    deque_init_copy(save, dir);
    *count = album ? getMusicByAlbum(I(album, REC_ID) == -1 ? (const char *)0 : P(album, REC_ALBUM))
                   : getAllAlbum();
    deque_init_copy(out, dir);
    deque_clear(dir);
    deque_assign(dir, save);
    deque_destroy(save);
    return out;
}

static void later(int (*step)(const void *), unsigned ms) {
    if (cf.timer) timer_remove(cf.timer);
    cf.timer = timer_add(step, 0, ms);
}

/* The peq_ui.c page: a title bar over whole 48px rows, shrunk so the list's white background
 * never shows below a short list. */
static void *list(const char *title, int n) {
    int h = widget_get_prop_int(cf.page, "h", 290), rows = (h - 48) / 48 * 48;
    if (n * 48 < rows) rows = n * 48;
    widget_destroy_children(cf.body);
    widget_set_visible(cf.body, 1, 0);
    cf.title = label_create(cf.body, 8, 0, 359, 48);
    widget_use_style(cf.title, "s_label_white20c");
    widget_set_text_utf8(cf.title, title);
    void *lv = list_view_create(cf.body, 0, 48, 375, rows);
    widget_set_prop_int(lv, "item_height", 48);
    void *view = scroll_view_create(lv, 0, 0, 375, rows);
    widget_set_prop_int(view, "yslidable", 1);
    widget_set_prop_int(view, "xslidable", 0);
    widget_set_prop_int(view, "virtual_h", n * 48);
    widget_invalidate_force(cf.page, 0);
    return view;
}

static void row(void *view, int index, const char *text, int (*click)(void *, void *)) {
    void *item = list_item_create(view, 0, index * 48, 375, 48);
    widget_use_style(item, "s_listitem_black");
    void *label = label_create(item, 12, 0, 350, 48);
    widget_use_style(label, "s_label_white20c");
    widget_set_text_utf8(label, text ? text : "");
    widget_on(item, EVT_CLICK, click, (void *)(long)index);
}

static void *text(void *parent, int y, int h, const char *style) {
    void *label = label_create(parent, 0, y, 375, h);
    widget_use_style(label, style);
    return label;
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
        cf.name = text(cf.covers, ART_SIZE + 38, 36, "s_label_white28c");
        cf.artist = text(cf.covers, ART_SIZE + 74, 28, "s_label_white20c");
        widget_on(cf.slide, EVT_VALUE_CHANGED, changed, 0);
        changed(0, 0);
    }
    widget_set_visible(cf.covers, 1, 0);
    widget_invalidate_force(cf.page, 0);
}

/* Stock pattern (album rows): load the file, set it, drop the load's reference. A failed load,
 * such as the empty "no art" marker, shows the placeholder. */
static void cover(void *img, unsigned i, int near) {
    char url[600] = "file://";
    near = near && i < deque_size(cf.albums);
    if (near) art_path(url + 7, album_key(deque_at(cf.albums, i)), "");
    const char *image = near ? url : PLACEHOLDER;
    if (!tk_strcmp(widget_get_prop_str(img, "image", ""), image)) return;
    unsigned bitmap[64]; /* bitmap_t */
    int loaded = near && !widget_load_image(img, url, bitmap);
    image_base_set_image(img, loaded ? url : PLACEHOLDER);
    if (loaded) widget_unload_image(img, bitmap);
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
    widget_set_text_utf8(cf.name, r ? P(r, REC_ALBUM) : "Refresh library");
    widget_set_text_utf8(cf.artist, r && P(r, REC_ARTIST) ? P(r, REC_ARTIST) : "");
    return 0;
}

static int poll(const void *unused) {
    (void)unused;
    cf.timer = 0;
    if (cf.finished) {
        stop();
        covers();
        return 0;
    }
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
    stop();
    if (cf.albums) deque_destroy(cf.albums);
    if (cf.tracks) deque_destroy(cf.tracks);
    cf.albums = cf.tracks = 0;
    widget_destroy_children(cf.page);
    cf.covers = 0;
    cf.album = 0;
    cf.body = widget_factory_create_widget(widget_factory(), "view", cf.page, 0, 0, 375, 290);
    int n = 0;
    if (!*(volatile int *)SCAN_THREAD || *(volatile int *)SCAN_DONE) cf.albums = query(0, &n);
    if (n <= 0) {
        cf.screen = MESSAGE;
        list("Update Local Music first", 0);
        return;
    }
    unsigned count = deque_size(cf.albums), fs[32] = { 0 };
    char path[512];
    cf.jobs = calloc(count, sizeof(job_t));
    for (unsigned i = 0; cf.jobs && i < count; ++i) {
        void *r = deque_at(cf.albums, i);
        unsigned key = album_key(r);
        if (P(r, REC_PATH) && access(art_path(path, key, ""), 0) &&
            (cf.jobs[cf.total].track = strdup(P(r, REC_PATH))))
            cf.jobs[cf.total++].key = key;
    }
    mkdir(ART_DIR, 0755);
    cf.done = cf.cancel = cf.finished = 0;
    /* statfs, MIPS o32 layout: f_bsize is word 1, f_bavail word 7. */
    if (cf.total && !statfs(PEQ_ROOT "/mnt/data", fs) &&
        (unsigned long long)fs[7] * fs[1] >= (unsigned long long)ART_MIN_FREE_MB << 20 &&
        !pthread_create(&cf.thread, 0, worker, 0)) {
        cf.running = 1;
        cf.screen = PREPARING;
        row(list("", 1), 0, "Cancel", cancel_row);
        poll(0);
    } else {
        stop();
        covers();
    }
}

static int to_covers(const void *unused) {
    (void)unused;
    cf.timer = 0;
    stop();
    covers();
    return 0;
}

static int to_tracks(const void *unused) {
    (void)unused;
    cf.timer = 0;
    int n;
    void *r = deque_at(cf.albums, (unsigned)cf.album);
    if (cf.tracks) deque_destroy(cf.tracks);
    cf.tracks = query(r, &n);
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
        later(refresh, 0);
    else {
        cf.album = i;
        later(to_tracks, 0);
    }
    return 0;
}

static int cancel_row(void *ctx, void *event) {
    (void)ctx;
    (void)event;
    later(to_covers, 0);
    return 0;
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

/* Return: tracks -> covers (the slide_menu kept its album), preparing -> cancel and covers,
 * covers or the message -> Home. */
static int keyup(void *ctx, void *event) {
    (void)ctx;
    if (I(event, EVENT_KEY) != KEY_RETURN) return 0;
    if (cf.screen == TRACKS || cf.screen == PREPARING)
        later(to_covers, 0);
    else
        navigator_back_to_home();
    return STOP;
}

static int closed(void *ctx, void *event) {
    (void)ctx;
    (void)event;
    stop();
    if (cf.albums) deque_destroy(cf.albums);
    if (cf.tracks) deque_destroy(cf.tracks);
    cf.albums = cf.tracks = 0;
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
    load();
    return 0;
}

/* home_page_init: stock binds the name-matched img_* cards, then the Coverflow card binds here,
 * on its image as stock does, whatever stock returned. */
int coverflow_home(void *win, void *ctx) {
    int result = stock_home_trampoline(win, ctx);
    widget_on(widget_lookup(win, "img_coverflow", 1), EVT_CLICK, coverflow_open, 0);
    return result;
}
