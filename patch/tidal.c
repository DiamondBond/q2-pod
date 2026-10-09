/* Tidal cache (docs/internals.md#tidal-cache): each stream stock's Tidal thread plays is also
 * downloaded to the card, and a track already there plays from the card instead. */
#include "peq.h"

/* The file's extension from the URL's path, without the query: ".flac", ".mp4"; 0 without one. */
const char *tidal_ext(const char *url, char *out, unsigned n) {
    const char *q = strstr(url, "?"), *end = q ? q : url + strlen(url), *dot = end;
    while (dot > url && *dot != '.' && *dot != '/') --dot;
    if (*dot != '.' || end - dot >= (int)n || end - dot < 2) return 0;
    memcpy(out, dot, end - dot);
    out[end - dot] = 0;
    return out;
}

#ifndef PEQ_HOST
#include "offsets.inc"
#include "stock.h"

#define TIDAL_DIR "/mnt/mmc/.tidal"
#define TIDAL_CAP_MB 2048 /* ponytail: fixed cap, oldest download goes first; a setting if asked */

extern int stock_tidal_trampoline(const char *url);

static struct {
    volatile int busy;
    unsigned long thread;
    char url[2048], tmp[96], path[96];
} td __attribute__((section(".scratch")));

/* mcl_tidalStartPlayer's only caller, the stream-URL thread (0x486d88), keeps its own copy of the
 * song id it fetched in $s2 from 0x48647c until it frees it after the call, so a skip that has
 * already rewritten tidalsongid can't file one track's stream under another's id. */
__asm__(".globl tidal_start\ntidal_start:\nmove $a1, $s2\nj tidal_play\n");

/* Deletes the oldest finished downloads until the rest fit TIDAL_CAP_MB. stat is o32's: st_size
 * word 12, st_mtime word 16. ponytail: a directory pass per deletion, fine for a few hundred files. */
static void trim(void) {
    for (;;) {
        unsigned long long total = 0;
        long oldest = 0;
        char victim[96] = "", path[96];
        unsigned st[36];
        void *d = opendir(TIDAL_DIR);
        for (struct dirent *e; d && (e = readdir(d));) {
            if (e->d_name[0] == '.' || strstr(e->d_name, ".tmp")) continue;
            tk_snprintf(path, sizeof path, TIDAL_DIR "/%s", e->d_name);
            if (__xstat(3, path, st)) continue;
            total += st[12];
            if (!*victim || (long)st[16] < oldest) oldest = (long)st[16], tk_snprintf(victim, sizeof victim, "%s", path);
        }
        if (d) closedir(d);
        if (total <= (unsigned long long)TIDAL_CAP_MB << 20 || !*victim) return;
        unlink(victim);
    }
}

static unsigned save(const void *data, unsigned size, unsigned n, void *file) {
    return fwrite(data, size, n, file) * size;
}

static void *download(void *unused) {
    (void)unused;
    long code = 0;
    int ok = 0;
    void *f = fopen(td.tmp, "wb"), *c = f ? curl_easy_init() : 0;
    if (c) {
        curl_easy_setopt(c, 10002, td.url); /* CURLOPT_URL */
        curl_easy_setopt(c, 20011, save);   /* WRITEFUNCTION */
        curl_easy_setopt(c, 10001, f);      /* WRITEDATA */
        curl_easy_setopt(c, 99, 1L);        /* NOSIGNAL: off the UI thread */
        curl_easy_setopt(c, 52, 1L);        /* FOLLOWLOCATION */
        curl_easy_setopt(c, 78, 15L);       /* CONNECTTIMEOUT */
        /* Tidal's CDN roots are not in the firmware's bundle; hciplayer streams the same URL
         * unverified (ffmpeg's tls_verify=0), so the copy is trusted exactly as the stream is. */
        curl_easy_setopt(c, 64, 0L); /* SSL_VERIFYPEER */
        curl_easy_setopt(c, 81, 0L); /* SSL_VERIFYHOST */
        ok = !curl_easy_perform(c) && !curl_easy_getinfo(c, 0x200002, &code) && code == 200; /* RESPONSE_CODE */
        curl_easy_cleanup(c);
    }
    if (f) {
        ok = ok && !fflush(f) && !fsync(fileno(f)) && !ferror(f);
        ok = !fclose(f) && ok;
    }
    if (ok && !rename(td.tmp, td.path))
        trim();
    else
        unlink(td.tmp);
    td.busy = 0;
    return 0;
}

int tidal_play(const char *url, const char *id) {
    char ext[8], path[96];
    int level = I(tidalStreamingLevelNow, 0);
    if (!url || !id || !*id || strstr(id, "/") || !tidal_ext(url, ext, sizeof ext))
        return stock_tidal_trampoline(url);
    /* Keyed by quality too, so a higher Streaming quality never gets a lower one's copy. */
    tk_snprintf(path, sizeof path, TIDAL_DIR "/%s-%d%s", id, level, ext);
    if (!access(path, 0)) return stock_tidal_trampoline(path);
    /* One download at a time; a track that starts meanwhile is cached on a later play. */
    if (!td.busy && strlen(url) < sizeof td.url && (mkdir(TIDAL_DIR, 0755), card_space(TIDAL_DIR))) {
        tk_snprintf(td.url, sizeof td.url, "%s", url);
        tk_snprintf(td.path, sizeof td.path, "%s", path);
        tk_snprintf(td.tmp, sizeof td.tmp, "%s.tmp", path);
        td.busy = 1;
        if (pthread_create(&td.thread, 0, download, 0))
            td.busy = 0;
        else
            pthread_detach(td.thread);
    }
    return stock_tidal_trampoline(url);
}
#endif
