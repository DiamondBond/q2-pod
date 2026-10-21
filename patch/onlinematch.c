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

/* The first result's synced lyrics to out, UTF-8 with a BOM as Kugou's; 1 if written. */
static int lrclib(const char *out) {
    /* stock's keyinfo, copied under its lock: file name, title (+0x200), album, artist (+0x500) */
    char key[0x600], url[3 * 0x300 + 64]; /* a byte encodes to at most 3 */
    char *body;
    int ok = 0;
    online_getkeyword_info(key);
    if (!key[0x200] || !lrclib_url(url, sizeof url, key + 0x200, key + 0x500) || !(body = get(url, LRCLIB_MAX)))
        return 0;
    void *json = cJSON_Parse(body);
    for (int i = 0, n = json ? cJSON_GetArraySize(json) : 0; i < n && !ok; ++i) {
        const char *text = str(cJSON_GetArrayItem(json, i), "syncedLyrics");
        void *f = text && *text ? fopen(out, "w") : 0;
        if (f) {
            fputs("\xef\xbb\xbf", f), fputs(text, f);
            ok = !fclose(f); /* a failed write shows at close */
        }
    }
    cJSON_Delete(json);
    free(body);
    return ok;
}

/* kugou_obtainlyric(keyword, out), online_lyricthd's first source: nonzero once out is written.
 * ponytail: LRCLIB's first synced result by title and artist, no duration check; pass the track's
 * length (/api/get) if wrong versions come back. */
extern int stock_kugou_trampoline(const char *keyword, const char *out);
int ringnav_lyric_search(const char *keyword, const char *out) {
    return lrclib(out) || stock_kugou_trampoline(keyword, out);
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
