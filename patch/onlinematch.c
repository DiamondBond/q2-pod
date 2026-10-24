/* Online match (docs/internals.md#lyrics-search, #cover-search): Now Playing's ⋯ lyrics and cover
 * match ask LRCLIB, and MusicBrainz's Cover Art Archive and iTunes, before stock's Kugou search;
 * NetEase, stock's next source, no longer answers. */
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

/* LRCLIB's one exact match for title, artist, album and the track's seconds, which it takes to
 * within 2; 0 if it does not fit in n. */
int lrclib_get_url(char *out, unsigned n, const char *title, const char *artist, const char *album,
                   int seconds) {
    char sec[12];
    snprintf(sec, sizeof sec, "%d", seconds);
    const char *part[] = { "https://lrclib.net/api/get?track_name=", title, "&artist_name=", artist,
                           "&album_name=", album, "&duration=", sec };
    return url_join(out, n, part, 8, 0);
}

/* Of n results' lengths (secs, 0 or less unknown), the index of the nearest to the track's seconds,
 * the first of equals and an unknown one last; without the track's (0), the first. -1 if n is 0. */
int lrc_nearest(const int *secs, int n, int seconds) {
    int best = -1;
    unsigned gap = 0;
    for (int i = 0; i < n; ++i) {
        unsigned d = seconds <= 0  ? 0
                     : secs[i] <= 0 ? ~0u
                                    : (unsigned)(secs[i] > seconds ? secs[i] - seconds : seconds - secs[i]);
        if (best < 0 || d < gap) best = i, gap = d;
    }
    return best;
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

/* url's reply, NUL-terminated, under max bytes, to free; 0 if the transfer failed. */
static char *get(const char *url, unsigned max) {
    body_t b = { calloc(1, max), 0, max };
    void *c = b.buf ? easy(url) : 0;
    int bad = !c;
    if (c) {
        curl_easy_setopt(c, 20011, got); /* WRITEFUNCTION */
        curl_easy_setopt(c, 10001, &b);  /* WRITEDATA */
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

/* A number member of a cJSON object, or 0. */
static int num(void *json, const char *name) {
    void *v = json ? cJSON_GetObjectItem(json, name) : 0;
    return v ? *(int *)((char *)v + 20) : 0; /* cJSON valueint: a number's, 1 for true, else 0 */
}

/* text, less its opening credits, to out, UTF-8 with a BOM as Kugou's; 1 if written. */
static int save(const char *out, const char *text) {
    void *f = text && *(text = lrc_body(text)) ? fopen(out, "w") : 0;
    if (!f) return 0;
    fputs("\xef\xbb\xbf", f), fputs(text, f);
    return !fclose(f); /* a failed write shows at close */
}

#define LRC_RESULTS 20 /* LRCLIB's search answers 20 at most */

/* LRCLIB's synced lyrics for a track to out: its exact match by title, artist, album and length
 * (seconds, 0 unknown), else the search result by title and artist nearest that length. 1 if
 * written, 0 if none, -1 if none worth asking elsewhere for: LRCLIB unreachable (likely offline),
 * or the track instrumental (its exact match, or every search result). */
static int lrclib(const char *title, const char *artist, const char *album, int seconds, const char *out) {
    char url[3 * 0x400 + 128]; /* keyinfo's title, album and artist, a byte encoding to at most 3 */
    char *body;
    void *json;
    int found = 0;
    if (!*title) return 0;
    if (seconds > 0 && *album && lrclib_get_url(url, sizeof url, title, artist, album, seconds)) {
        if (!(body = get(url, LRCLIB_MAX))) return -1;
        json = cJSON_Parse(body); /* a miss is a 404's {"code":404,...} */
        found = num(json, "instrumental") ? -1 : save(out, str(json, "syncedLyrics"));
        cJSON_Delete(json);
        free(body);
        if (found) return found;
    }
    if (!lrclib_url(url, sizeof url, title, artist)) return 0;
    if (!(body = get(url, LRCLIB_MAX))) return -1;
    json = cJSON_Parse(body);
    const char *text[LRC_RESULTS];
    int secs[LRC_RESULTS], n = 0, k = json ? cJSON_GetArraySize(json) : 0, instrumental = 0;
    for (int i = 0; i < k && n < LRC_RESULTS; ++i) {
        void *r = cJSON_GetArrayItem(json, i);
        const char *t = str(r, "syncedLyrics");
        instrumental += num(r, "instrumental") != 0;
        if (t && *lrc_body(t)) text[n] = t, secs[n++] = num(r, "duration"); /* something sung */
    }
    int pick = lrc_nearest(secs, n, seconds);
    found = pick >= 0 ? save(out, text[pick]) : k && instrumental == k ? -1 : 0;
    cJSON_Delete(json);
    free(body);
    return found;
}

/* r's length in seconds: a CUE track's own span (its file's rest for the last), else its file's,
 * probed as Long Songs does (AudioProperties::length, vtable +0xc); 0 if unknown. */
static int song_seconds(void *r) {
    int start = I(r, REC_CUE_START), end = I(r, REC_CUE_END);
    if (end > start) return end - start;
    const char *path = I(r, REC_TYPE) == 8 ? P(r, REC_PATH) : 0;
    void *f = path && *path == '/' ? taglib_file_new(path, 1) : 0;
    void *p = f ? taglib_file_audioproperties(f) : 0;
    int sec = p ? ((int (*)(void *))(*(void ***)p)[3])(p) : 0;
    if (f) taglib_file_free(f);
    return sec > start ? sec - start : 0;
}

/* The playing song's length for the lyrics search, found on the UI thread as its keywords are set,
 * so the search's thread never reads the queue; 0 if unknown. */
static volatile int om_seconds;

/* online_setkeyword_info(name, title, album, artist), from stock's ⋯ Download Cover & Lyrics: the
 * playing record's REC_NAME and the player's tags into keyinfo, then the onlinematching_page. */
extern void stock_lyrickeys_trampoline(const char *name, const char *title, const char *album, const char *artist);
void ringnav_lyric_keys(const char *name, const char *title, const char *album, const char *artist) {
    stock_lyrickeys_trampoline(name, title, album, artist);
    void *q = P(mcl_pdeqplaylist, 0), *r = 0;
    unsigned pos = (unsigned)I(MCL_POS, 0);
    if (q && pos < deque_size(q)) r = deque_at(q, pos);
    om_seconds = r && name && P(r, REC_NAME) && !strcmp(P(r, REC_NAME), name) ? song_seconds(r) : 0;
}

/* kugou_obtainlyric(keyword, out), online_lyricthd's first source: nonzero once out is written.
 * LRCLIB first; Kugou only when LRCLIB answered without lyrics, so an instrumental track gets none
 * and an offline search waits one connect timeout, not two. */
extern int stock_kugou_trampoline(const char *keyword, const char *out);
int ringnav_lyric_search(const char *keyword, const char *out) {
    /* stock's keyinfo, copied under its lock: file name, title (+0x200), album (+0x400), artist (+0x500) */
    char key[0x600];
    online_getkeyword_info(key);
    int found = lrclib(key + 0x200, key + 0x500, key + 0x400, om_seconds, out);
    return found > 0 || (!found && stock_kugou_trampoline(keyword, out));
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
    char *body = mb ? get(url, COVER_MAX) : 0;
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
    body = itunes_url(url, sizeof url, album, artist) ? get(url, COVER_MAX) : 0;
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
