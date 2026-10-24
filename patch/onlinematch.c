/* Online match (docs/internals.md#lyrics-search, #cover-search): Now Playing's ⋯ lyrics match asks
 * LRCLIB alone (no Kugou or NetEase), and its cover match MusicBrainz's Cover Art Archive and iTunes
 * before stock's Kugou search. */
#include "peq.h"

/* part joined into out, the odd ones percent-encoded and, with lucene, a backslash before each " and \
 * (MusicBrainz's query syntax); 0 if it does not fit in n. */
static int url_join(char *out, unsigned n, const char *const *part, int count, int lucene) {
    static const char hex[] = "0123456789ABCDEF";
    unsigned at = 0;
    for (int i = 0; i < count; ++i)
        for (const unsigned char *s = (const unsigned char *)part[i]; *s; ++s) {
            int keep = !(i & 1) || (*s >= '0' && *s <= '9') || ((*s | 32) >= 'a' && (*s | 32) <= 'z') ||
                       *s == '-' || *s == '.' || *s == '_' || *s == '~';
            int esc = (i & 1) && lucene && (*s == '"' || *s == '\\');
            if (at + (keep ? 1 : 3) + 3 * esc >= n) return 0;
            if (esc) out[at++] = '%', out[at++] = '5', out[at++] = 'C';
            if (keep)
                out[at++] = *s;
            else
                out[at++] = '%', out[at++] = hex[*s >> 4], out[at++] = hex[*s & 15];
        }
    out[at] = 0;
    return 1;
}

/* LRCLIB's search URL for title and artist; 0 if it does not fit in n. */
int lrclib_url(char *out, unsigned n, const char *title, const char *artist) {
    const char *part[] = { "https://lrclib.net/api/search?track_name=", title, "&artist_name=", artist };
    return url_join(out, n, part, 4, 0);
}

/* MusicBrainz's release search, release:"ALBUM" AND artist:"ARTIST" (no artist clause without one). */
int mb_url(char *out, unsigned n, const char *album, const char *artist) {
    const char *part[] = { "https://musicbrainz.org/ws/2/release/?fmt=json&limit=10&query=release%3A%22", album,
                           *artist ? "%22%20AND%20artist%3A%22" : "%22", artist, "%22" };
    return url_join(out, n, part, *artist ? 5 : 3, 1);
}

/* iTunes Search's albums for "ARTIST ALBUM". */
int itunes_url(char *out, unsigned n, const char *album, const char *artist) {
    const char *part[] = { "https://itunes.apple.com/search?entity=album&limit=5&term=", artist, "%20", album };
    return url_join(out, n, part, 4, 0);
}

/* An iTunes artworkUrl100 rewritten in place to its 600 px JPEG (the last "100x100"); 0 if none. */
int itunes_art(char *url) {
    char *last = 0;
    for (char *s = url; (s = strstr(s, "100x100")); ++s) last = s;
    if (last) memcpy(last, "600x600", 7);
    return last != 0;
}

/* t past its opening credit lines ("[00:01.00] Mix Engineer : Name", NetEase's style, which LRCLIB
 * keeps): each line, up to the first sung one, whose text holds " : ", and any blank line before
 * one. A tag line such as [offset:...] ends the search, so it stays; lyrics with no sung line at all
 * come back empty. */
const char *lrc_body(const char *t) {
    const char *line = t;
    while (*line) {
        const char *text = line, *end = line;
        while (*end && *end != '\n') ++end;
        while (*text == '[' && text[1] >= '0' && text[1] <= '9') { /* the line's [mm:ss.xx] times */
            const char *c = text;
            while (c < end && *c != ']') ++c;
            if (c == end) break;
            text = c + 1;
        }
        int credit = 0, blank = 1;
        for (const char *c = text; c < end; ++c) {
            if (*c != ' ' && *c != '\r') blank = 0;
            if (c[0] == ' ' && c + 2 < end && c[1] == ':' && c[2] == ' ') credit = 1;
        }
        if (!credit && !blank) return t; /* the first sung line, or a tag */
        line = *end ? end + 1 : end;
        if (credit) t = line;
    }
    return line;
}

/* A track's lyrics fetch: written, none, or why not. LRC_BUSY: LRCLIB answered, but not with
 * results (its 503 "ServerOverloaded", Retry-After: 1, which uncached searches meet at times). */
enum { LRC_CANCELLED = -4, LRC_CARD, LRC_OFFLINE, LRC_BUSY, LRC_NONE, LRC_SAVED };

/* path with its file name's extension (or none) replaced by ext: stock's .lrc beside a song; 0 if
 * it does not fit in n. */
int lrc_path(char *out, unsigned n, const char *path, const char *ext) {
    const char *name = strrchr(path, '/'), *dot;
    name = name ? name + 1 : path;
    dot = strrchr(name, '.');
    unsigned keep = (unsigned)(dot && dot > name ? dot - path : (long)strlen(path)), e = strlen(ext);
    if (keep + e >= n) return 0;
    memcpy(out, path, keep);
    memcpy(out + keep, ext, e + 1);
    return 1;
}

/* Download Album Lyrics (docs/internals.md#album-lyrics): the tracks it copies off stock's records,
 * and its job, which the row's timer reads while the worker runs. */
typedef struct {
    char path[0x200], title[0x200], artist[0x100]; /* keyinfo's sizes */
} lyr_track;
typedef struct {
    volatile int cancel, done; /* done: tracks finished */
    int total, saved, had, none, failed, state;
} lyr_job;
enum { LJ_DONE, LJ_OFFLINE, LJ_CARD, LJ_CANCELLED };
#define LJ_OFFLINE_RUN 2 /* tracks in a row LRCLIB never answered for: likely offline, so it ends */
#define LJ_BUSY_TRIES 3  /* requests for a track while LRCLIB answers busy */
#ifdef PEQ_HOST
#define LJ_RETRY_US 1000 /* test/peq.py: no real wait */
#else
#define LJ_RETRY_US 2000000 /* before a retry: twice the moment LRCLIB's busy reply asks for */
#endif

/* Each of n tracks' lyrics beside it, each on its own, as Download Cover & Lyrics would find them: a
 * file gone from the card since the library's scan is passed over; one with a .lrc (or .LRC) is left
 * as it is; one LRCLIB has none for, or never answered for, is counted and the next tried. fetch
 * writes to <name>.lrc.part, renamed once whole. A busy reply is asked again after a pause, up to
 * LJ_BUSY_TRIES in all; an unanswered request is retried once after LRCLIB has answered in this job
 * (before, a failure likely means offline). LJ_OFFLINE_RUN tracks unanswered (or still busy) in a
 * row end the job, as does a card that can't be written. job->cancel ends it between requests
 * (fetch's transfer stops at it too). Returns job->state. */
int album_lyrics(lyr_job *job, const lyr_track *t, int n,
                 int (*fetch)(const lyr_track *, const char *, volatile int *)) {
    char lrc[sizeof t->path + 8], upper[sizeof t->path + 8], part[sizeof t->path + 16];
    int unanswered = 0, answered = 0;
    job->total = n;
    job->state = LJ_DONE;
    for (int i = 0; i < n && !job->cancel; job->done = ++i) {
        int got = LRC_OFFLINE, busy = 0, lost = 0;
        if (!lrc_path(lrc, sizeof lrc, t[i].path, ".lrc") || !lrc_path(upper, sizeof upper, t[i].path, ".LRC")) {
            ++job->failed;
            continue;
        }
        if (access(t[i].path, 0)) continue; /* F_OK */
        if (!access(lrc, 0) || !access(upper, 0)) {
            ++job->had;
            continue;
        }
        snprintf(part, sizeof part, "%s.part", lrc);
        while (!job->cancel) {
            got = fetch(&t[i], part, &job->cancel);
            if (got == LRC_BUSY) answered = 1; /* there, just busy */
            int again = got == LRC_BUSY ? ++busy < LJ_BUSY_TRIES : got == LRC_OFFLINE && answered && !lost++;
            if (!again) break;
            usleep(LJ_RETRY_US);
        }
        if (got == LRC_SAVED && !rename(part, lrc)) {
            ++job->saved, answered = 1, unanswered = 0;
            continue;
        }
        unlink(part); /* what a failed, cancelled or unrenamed write left */
        if (got == LRC_SAVED || got == LRC_CARD) {
            job->state = LJ_CARD;
            break;
        }
        if (got == LRC_CANCELLED || job->cancel) break;
        if (got == LRC_OFFLINE || got == LRC_BUSY) {
            ++job->failed;
            if (++unanswered < LJ_OFFLINE_RUN) continue;
            job->state = LJ_OFFLINE;
            break;
        }
        ++job->none, answered = 1, unanswered = 0; /* LRCLIB has no synced lyrics for it */
    }
    if (job->cancel && job->state == LJ_DONE) job->state = LJ_CANCELLED;
    return job->state;
}

/* The toast that sums up job, into out. */
void album_note(char *out, unsigned n, const lyr_job *job) {
    static const char *const head[] = { "Album lyrics", "LRCLIB stopped answering", "Can't write to the card",
                                        "Cancelled" };
    static const char *const what[] = { "saved", "not found", "already had lyrics", "failed" };
    const int count[] = { job->saved, job->none, job->had, job->failed };
    int answered = job->saved || job->none, any = answered || job->had || job->failed;
    unsigned at = (unsigned)snprintf(out, n, "%s", job->state == LJ_OFFLINE && !answered ? "Can't reach LRCLIB"
                                                                                         : head[job->state]);
    for (int i = 0, first = 1; i < 4 && at < n && (job->state != LJ_OFFLINE || answered); ++i)
        if (count[i]) at += (unsigned)snprintf(out + at, n - at, "%s%d %s", first ? ": " : ", ", count[i], what[i]), first = 0;
    if (!any && job->state == LJ_DONE && at < n) snprintf(out + at, n - at, ": no songs on the card");
}

#ifndef PEQ_HOST
#include "offsets.inc"
#include "stock.h"

#define OM_CA "/etc/scrobble-ca.pem" /* scrobble.c's: GTS Root R4 signs LRCLIB, ISRG the Cover Art Archive,
                                       * DigiCert G2 MusicBrainz and iTunes */
#define LRCLIB_MAX (512 << 10)       /* up to 20 results, each with plain and synced text */
#define COVER_MAX (256 << 10)        /* 10 MusicBrainz releases or 5 iTunes albums: ~15 KB in all */
#define COVER_FILL 10                /* our candidates stop at this list size; stock's sources fill to 12 */

typedef struct { char *buf; unsigned len, max; } body_t;

static unsigned got(const char *data, unsigned size, unsigned n, void *ctx) {
    body_t *b = ctx;
    unsigned add = size * n;
    if (b->len + add >= b->max) return 0; /* too big: the transfer fails */
    memcpy(b->buf + b->len, data, add);
    b->len += add;
    return add;
}

/* A libcurl handle for url, verified with the bundled CA file (stock's curl_http_request turns
 * checks off), timed to keep stock's worker thread from hanging. */
static void *easy(const char *url) {
    void *c = curl_easy_init();
    if (!c) return 0;
    curl_easy_setopt(c, 10002, url);      /* CURLOPT_URL */
    curl_easy_setopt(c, 10018, Q2POD_UA); /* USERAGENT, as LRCLIB and MusicBrainz ask */
    curl_easy_setopt(c, 99, 1L);          /* NOSIGNAL: stock's match threads */
    curl_easy_setopt(c, 78, 10L);         /* CONNECTTIMEOUT */
    curl_easy_setopt(c, 13, 20L);         /* TIMEOUT */
    curl_easy_setopt(c, 10065, OM_CA);    /* CAINFO */
    return c;
}

/* curl's progress callback: a nonzero *cancel stops the transfer. */
static int stopped(void *cancel, long long total, long long now, long long up, long long sent) {
    return *(volatile int *)cancel;
}

/* url's reply, NUL-terminated, under max bytes, to free; 0 if the transfer failed or *cancel (when
 * given) stopped it. */
static char *get(const char *url, unsigned max, volatile int *cancel) {
    body_t b = { calloc(1, max), 0, max };
    void *c = b.buf ? easy(url) : 0;
    int bad = !c;
    if (c) {
        curl_easy_setopt(c, 20011, got); /* WRITEFUNCTION */
        curl_easy_setopt(c, 10001, &b);  /* WRITEDATA */
        if (cancel) {
            curl_easy_setopt(c, 20219, stopped);       /* XFERINFOFUNCTION */
            curl_easy_setopt(c, 10057, (void *)cancel); /* XFERINFODATA */
            curl_easy_setopt(c, 43, 0L);               /* NOPROGRESS off, for it */
        }
        bad = curl_easy_perform(c) != 0; /* an error reply parses to nothing we use */
        curl_easy_cleanup(c);
    }
    if (bad) free(b.buf), b.buf = 0;
    return b.buf;
}

/* A string member of a cJSON object, or 0. */
static const char *str(void *json, const char *name) {
    void *v = json ? cJSON_GetObjectItem(json, name) : 0;
    return v ? *(const char **)((char *)v + 16) : 0; /* cJSON valuestring, 0 unless a string */
}

/* The first result for title and artist with synced lyrics, less its opening credits, to out, UTF-8
 * with a BOM as Kugou's: LRC_SAVED, LRC_NONE, LRC_OFFLINE if LRCLIB never answered, LRC_BUSY if it
 * answered with no results array (an error object), LRC_CARD if out could not be written, or
 * LRC_CANCELLED once *cancel (when given) stopped the transfer. */
static int lrclib(const char *title, const char *artist, const char *out, volatile int *cancel) {
    char url[3 * 0x300 + 64]; /* keyinfo's title and artist; a byte encodes to at most 3 */
    char *body;
    int found = LRC_NONE;
    if (!*title || !lrclib_url(url, sizeof url, title, artist)) return LRC_NONE;
    if (!(body = get(url, LRCLIB_MAX, cancel))) return cancel && *cancel ? LRC_CANCELLED : LRC_OFFLINE;
    if (*body != '[') { /* the search's results are an array, even when empty */
        free(body);
        return LRC_BUSY;
    }
    void *json = cJSON_Parse(body);
    for (int i = 0, n = json ? cJSON_GetArraySize(json) : 0; i < n && found == LRC_NONE; ++i) {
        const char *text = str(cJSON_GetArrayItem(json, i), "syncedLyrics");
        void *f = text && *(text = lrc_body(text)) ? fopen(out, "w") : 0;
        if (text && *text && !f) found = LRC_CARD;
        if (f) {
            fputs("\xef\xbb\xbf", f), fputs(text, f);
            found = fclose(f) ? LRC_CARD : LRC_SAVED; /* a failed write shows at close */
        }
    }
    cJSON_Delete(json);
    free(body);
    return found;
}

/* kugou_obtainlyric(keyword, out), online_lyricthd's first source, in its place: LRCLIB alone, as
 * Kugou's often came back for another song. Nonzero ends the thread's search, so NetEase, its next
 * source, is skipped too (its search asks for a phone-bound account and finds nothing); the page
 * shows whatever out holds. ponytail: LRCLIB's first synced result by title and artist, no
 * duration check. */
int ringnav_lyric_search(const char *keyword, const char *out) {
    /* stock's keyinfo, copied under its lock: file name, title (+0x200), album, artist (+0x500) */
    char key[0x600];
    online_getkeyword_info(key);
    lrclib(key + 0x200, key + 0x500, out, 0);
    return 1;
}

/* Download Album Lyrics (docs/internals.md#album-lyrics): a row under stock's Download Cover &
 * Lyrics on Now Playing's ⋯ page saves LRCLIB's lyrics beside every song of the playing song's
 * album, found as that search finds them, on a thread of its own that outlives the page. */
extern void *list_row(void *view, const char *icon, int (*click)(void *, void *), void *ctx);
extern void *coverflow_album_tracks(void *r);
static const char AL_TITLE[] = "Download Album Lyrics";
static struct {
    lyr_job job;
    lyr_track *tracks;
    unsigned long thread; /* 0 once joined */
    volatile int running; /* the worker's, until it returns */
    void *label;          /* the row's while the page is open */
} al;

static int al_fetch(const lyr_track *t, const char *out, volatile int *cancel) {
    return lrclib(t->title, t->artist, out, cancel);
}

static void *al_worker(void *unused) {
    album_lyrics(&al.job, al.tracks, al.job.total, al_fetch);
    al.running = 0;
    return 0;
}

/* The playing song's record, a file on the card with an album tag; 0 otherwise. */
static void *al_playing(void) {
    void *q = P(mcl_pdeqplaylist, 0), *r;
    unsigned pos = (unsigned)I(MCL_POS, 0);
    if (!q || (unsigned)(I(MCL_TYPE, 0) - 0xf1) < 2 || pos >= deque_size(q) || !(r = deque_at(q, pos)) ||
        I(r, REC_TYPE) != 8)
        return 0; /* 0xf1/0xf2: an online queue */
    const char *path = P(r, REC_PATH), *album = P(r, REC_ALBUM);
    return path && *path == '/' && album && *album ? r : 0;
}

/* The row's label: its title, or the job's progress. */
static void al_show(void) {
    char s[48];
    if (!al.label) return;
    if (!al.thread) {
        widget_set_text_utf8(al.label, AL_TITLE);
        return;
    }
    if (al.job.cancel)
        snprintf(s, sizeof s, "Cancelling…");
    else
        snprintf(s, sizeof s, "Downloading %d of %d", al.job.done + (al.job.done < al.job.total), al.job.total);
    widget_set_text_utf8(al.label, s);
}

/* The worker joined, its tracks freed and, with say, its job summed up in a toast; once. */
static void al_finish(int say) {
    char note[96];
    if (!al.thread) return;
    pthread_join(al.thread, 0);
    al.thread = 0;
    free(al.tracks);
    al.tracks = 0;
    album_note(note, sizeof note, &al.job);
    al_show();
    if (say) toast(note);
}

/* Every 500 ms while the job runs: its progress on the row, and standby and auto power-off held
 * off, as Network Update's; then its summary. */
static int al_wait(const void *unused) {
    if (!al.thread) return 0; /* stopped for USB storage */
    if (al.running) {
        reset_poweroptions_timer(1, 1, 0);
        al_show();
        return 8; /* RET_REPEAT */
    }
    al_finish(1);
    return 0;
}

/* USB storage takes the card: the job stops first (its transfer at the next progress call), the
 * lyrics it finished kept (navigation.c ringnav_usbmode). */
void album_lyrics_stop(void) {
    al.job.cancel = 1;
    al_finish(0);
}

static void al_put(char *to, unsigned n, const char *s) { snprintf(to, n, "%s", s ? s : ""); }

/* A press starts the job, copying the album's tracks off stock's records first (a CUE track
 * shares its file's .lrc, so it is left out); a press while it runs cancels it. */
static int al_click(void *ctx, void *event) {
    if (al.thread) { /* ended, not yet joined: the timer's */
        if (al.running) al.job.cancel = 1, al_show();
        return 0;
    }
    if (get_wifisignal() <= 0) {
        toast("Connect to Wi-Fi first");
        return 0;
    }
    void *r = al_playing(), *list = r ? coverflow_album_tracks(r) : 0;
    unsigned n = list ? deque_size(list) : 0, k = 0;
    lyr_track *t = n ? calloc(n, sizeof *t) : 0;
    for (unsigned i = 0; t && i < n; ++i) {
        void *s = deque_at(list, i);
        const char *path = I(s, REC_TYPE) == 8 ? P(s, REC_PATH) : 0;
        if (!path || *path != '/' || strlen(path) >= sizeof t->path || I(s, REC_CUE_START) || I(s, REC_CUE_END))
            continue;
        al_put(t[k].path, sizeof t->path, path);
        al_put(t[k].title, sizeof t->title, P(s, REC_TITLE));
        al_put(t[k++].artist, sizeof t->artist, P(s, REC_ARTIST));
    }
    if (list) deque_destroy(list);
    if (!k) {
        free(t);
        toast("No album songs on the card");
        return 0;
    }
    memset(&al.job, 0, sizeof al.job);
    al.tracks = t, al.job.total = (int)k, al.running = 1;
    if (pthread_create(&al.thread, 0, al_worker, 0)) {
        al.thread = 0, al.running = 0;
        free(t), al.tracks = 0;
        toast("Can't start the download");
        return 0;
    }
    timer_add(al_wait, (void *)0, 500);
    al_show();
    return 0;
}

static int al_gone(void *ctx, void *event) {
    if (al.label == ctx) al.label = 0;
    return 0;
}

/* playermore_page_init: stock's PLAYMORE_COUNT rows (PLAYMORE_ROWS' kinds by position), then ours
 * under Download Cover & Lyrics, in stock's row widgets and 20 px label, and unnamed, so stock's
 * row click (an atoi of the name) never sees it. Only for a playing song on the card; a page
 * without stock's rows is left as it built it. */
extern int stock_playermore_trampoline(void *win, void *ctx);
int ringnav_playermore(void *win, void *ctx) {
    int result = stock_playermore_trampoline(win, ctx);
    void *view = win ? widget_lookup(win, "scroll_view_more", 1) : (void *)0;
    unsigned at = 0;
    if (!view || widget_count_children(view) != PLAYMORE_COUNT || !al_playing()) return result;
    while (at < PLAYMORE_COUNT && ((const int *)PLAYMORE_ROWS)[at] != PLAYMORE_SEARCH) ++at;
    if (at == PLAYMORE_COUNT) return result;
    void *label = list_row(view, "player_onlinesearch", al_click, 0);
    widget_use_style(label, "s_scrlabel_white20l");
    widget_resize(label, 253, I(label, W_H));
    widget_restack(P(P(label, W_PARENT), W_PARENT), at + 1);
    widget_on(label, EVT_DESTROY, al_gone, label);
    al.label = label;
    al_show();
    return result;
}

/* The Cover Art Archive's 500 px front (a JPEG thumbnail) of release group id, as the archive.org URL
 * its 307 names, to out (0x200, online_addcoverlist's size); 0 without one (404). */
static int caa(const char *id, char *out) {
    char url[128], *to = 0;
    long code = 0;
    int ok = 0;
    void *c;
    snprintf(url, sizeof url, "https://coverartarchive.org/release-group/%s/front-500", id);
    if (!(c = easy(url))) return 0;
    curl_easy_setopt(c, 44, 1L); /* NOBODY: the redirect alone; stock's download follows it */
    curl_easy_setopt(c, 13, 5L); /* TIMEOUT: four of these at most, so a slow search stays short */
    if (!curl_easy_perform(c) && !curl_easy_getinfo(c, 0x200002, &code) && code / 100 == 3 && /* RESPONSE_CODE */
        !curl_easy_getinfo(c, 0x10001f, &to) && to && strlen(to) < 0x200)            /* REDIRECT_URL */
        memcpy(out, to, strlen(to) + 1), ok = 1;
    curl_easy_cleanup(c);
    return ok;
}

/* Adds MusicBrainz's and iTunes's covers for the playing album (or title) to stock's cover list. */
static void covers(void) {
    char key[0x600], url[3 * 0x300 + 128], seen[4][37];
    int groups = 0, n;
    online_getkeyword_info(key);
    const char *album = key[0x400] ? key + 0x400 : key + 0x200, *artist = key + 0x500;
    if (!*album) return;
    int mb = mb_url(url, sizeof url, album, artist);
    char *body = mb ? get(url, COVER_MAX, 0) : 0;
    /* ponytail: MusicBrainz unreachable means likely offline, so iTunes isn't tried either (one
     * timeout, not two, before stock's sources); ask iTunes anyway if one service is down alone. */
    if (mb && !body) return;
    void *json = cJSON_Parse(body), *list = json ? cJSON_GetObjectItem(json, "releases") : 0;
    n = list ? cJSON_GetArraySize(list) : 0;
    /* a release group's chosen front once; at most 4 groups asked */
    for (int i = 0; i < n && groups < 4 && online_getsize_coverlist() < COVER_FILL; ++i) {
        const char *id = str(cJSON_GetObjectItem(cJSON_GetArrayItem(list, i), "release-group"), "id");
        int j = 0;
        if (!id || strlen(id) != 36) continue;
        while (j < groups && strcmp(seen[j], id)) ++j;
        if (j < groups) continue;
        memcpy(seen[groups++], id, 37);
        if (caa(id, url)) online_addcoverlist(url);
    }
    cJSON_Delete(json);
    free(body);
    body = itunes_url(url, sizeof url, album, artist) ? get(url, COVER_MAX, 0) : 0;
    json = body ? cJSON_Parse(body) : 0;
    list = json ? cJSON_GetObjectItem(json, "results") : 0;
    n = list ? cJSON_GetArraySize(list) : 0;
    for (int i = 0; i < n && online_getsize_coverlist() < COVER_FILL; ++i) {
        const char *art = str(cJSON_GetArrayItem(list, i), "artworkUrl100");
        if (!art || strlen(art) >= 0x200) continue;
        memcpy(url, art, strlen(art) + 1);
        if (itunes_art(url)) online_addcoverlist(url);
    }
    cJSON_Delete(json);
    free(body);
}

/* kugou_obtaincover(keyword), online_coverthd's first source, then com163's and Baidu's: each adds
 * image URLs to stock's list (online_addcoverlist), which the page downloads and shows. ours go first. */
extern void stock_kugoucover_trampoline(const char *keyword);
void ringnav_cover_search(const char *keyword) {
    covers();
    stock_kugoucover_trampoline(keyword);
}
#endif
