/* Mixtape (docs/internals.md#mixtape): Coverflow's "Craft a Mixtape" turns an album into a mix of
 * the library's music that sounds like it. Each song is heard once: stock ffmpeg decodes 30 s from
 * its middle at 22.05 kHz mono into /tmp, and the clip's MFCCs (13 coefficients' mean and spread)
 * are kept on the card as the song's profile. A craft scores every song against the album's own
 * (nearest of its tracks, so a varied album is not averaged away), adds what the tags agree on and
 * the user's hearts and plays, and fills about 45 minutes under a few variety rules. The user then
 * strikes what they don't want and re-rolls those slots before anything plays. */
#include "offsets.inc"
#include "peq.h"
#ifdef PEQ_HOST
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/wait.h>
#define mx_kill kill
#define mx_nice(n) setpriority(PRIO_PROCESS, 0, n)
#else
#include "stock.h"
/* demo imports neither kill() nor setpriority(): the o32 syscalls themselves. */
__asm__(".globl mx_kill\nmx_kill:\nli $v0, 4037\nsyscall\njr $ra\n");
__asm__(".globl mx_nice\nmx_nice:\nmove $a2, $a0\nli $a0, 0\nli $a1, 0\nli $v0, 4097\nsyscall\njr $ra\n");
int mx_kill(int pid, int sig);
int mx_nice(int prio);
#endif
#include "playback.h"

#define MX_DIR PEQ_ROOT "/mnt/mmc/.mixtape"
#define MX_FILE MX_DIR "/profiles"
#define MX_RAW PEQ_ROOT "/tmp/q2mix.raw"
#ifndef MX_FFMPEG
#define MX_FFMPEG "/usr/bin/ffmpeg"
#endif
#define MX_MAGIC 0x3154584du /* "MXT1" */
#define MX_VERSION 1         /* bump when the features change: every profile is heard again */
#define MX_RATE 22050
#define MX_CLIP_S 30
#define MX_N 1024 /* FFT frame, hop half of it */
#define MX_MELS 26
#define MX_CEPS 13
#define MX_DIMS (2 * MX_CEPS)
#define MX_MAX 20         /* songs in a mix */
#define MX_MIN 6          /* fewer and there is no mix */
#define MX_TARGET_S 2700  /* about 45 minutes */
#define MX_GUESS_S 240    /* a song of unknown length */
#define MX_SHORT_S 60     /* intros and interludes stay out */
#define MX_TOP 8          /* a slot draws from this many best */
#define MX_SAVE_EVERY 100 /* songs heard between cache writes */
#define MX_SHORT(s) ((s)->sec > 0 && (s)->sec < MX_SHORT_S) /* sec <= 0: unknown */

enum { MX_OK = 1, MX_FAILED };
typedef struct {
    unsigned key, size, mtime; /* listen_key; the file's size and mtime when heard */
    unsigned short sec;        /* the song's length, 0 unknown */
    unsigned char status, pad;
    float f[MX_DIMS];
} mx_prof;
typedef struct {
    unsigned magic, version, count;
} mx_head;
typedef struct {
    char *path;
    int start, len, cached; /* the CUE start; seconds, < 0 unknown; the profile is current */
    mx_prof p;
} mx_job;

enum { MX_USED = 1, MX_REJECTED = 2, MX_ASIDE = 4 };
typedef struct {
    unsigned key, artist, album_artist, album, title, genre[4]; /* lowercase hashes, 0 untagged */
    int year, sec, plays;
    unsigned char hearts, album_hearts, seed, flags;
    const mx_prof *prof;
    float score;
} mx_song;

/* ponytail: hand-tuned by listening; the knobs if mixes wander (sound) or stay too close (artist). */
static const struct {
    float sound, tags, artist, genre, year, length, floor;
} W = { 0.7f, 0.3f, 0.3f, 0.4f, 0.15f, 0.05f, 0.3f };
static const float HEARTS[6] = { 1, 0.3f, 0.8f, 1.05f, 1.15f, 1.25f }; /* unrated, then 1-5 */

static struct {
    void *page, *title, *note, *songs; /* songs: the library's records, v's */
    mx_song *v;
    mx_job *jobs;
    mx_head *head; /* the cache as written: the header, then tab */
    mx_prof *tab;  /* sorted by key */
    int n, ntab, njobs, merged, running, len, sel;
    unsigned long thread;
    unsigned timer, began, heard_at; /* when listening began, and how many were heard by then */
    volatile int checked, need, heard, cancel, finished, pid, at; /* at: jobs before it are done */
    int list[MX_MAX];
    unsigned char struck[MX_MAX];
    char album[128], said[160];
} mx __attribute__((section(".scratch")));

/* ---- Features ---------------------------------------------------------------------------- */

void vis_fft(float *re, float *im, int n); /* visualizer.c */

/* The MFCCs of n samples of 22.05 kHz mono into out: c1-c13's means, then their standard
 * deviations, over the frames above -60 dBFS. c0 is left out, so loudness doesn't count. 0 when
 * under a fifth of the frames (or ten) have sound. */
int mx_features(const short *pcm, int n, float *out) {
    static const float PI = 3.14159265f;
    float re[MX_N], im[MX_N], win[MX_N], dct[MX_CEPS][MX_MELS], t[MX_N / 2 + 1];
    double sum[MX_CEPS] = { 0 }, sq[MX_CEPS] = { 0 };
    int seg[MX_N / 2 + 1], frames = n < MX_N ? 0 : (n - MX_N) / (MX_N / 2) + 1, voiced = 0;
    /* 26 triangles evenly spaced in mel from 100 Hz to 8 kHz: bin k lies in segment seg[k],
     * rising into filter seg (t) and falling out of seg - 1 (1 - t) */
    double lo = log(1 + 100 / 700.0), hi = log(1 + 8000 / 700.0), edge[MX_MELS + 2];
    for (int i = 0; i < MX_MELS + 2; ++i) edge[i] = 700 * (pow(2.718281828, lo + (hi - lo) * i / (MX_MELS + 1)) - 1);
    for (int k = 0, s = 0; k <= MX_N / 2; ++k) {
        double f = (double)k * MX_RATE / MX_N;
        while (s < MX_MELS + 1 && f >= edge[s + 1]) ++s;
        seg[k] = f < edge[0] || f >= edge[MX_MELS + 1] ? -1 : s;
        t[k] = seg[k] < 0 ? 0 : (float)((f - edge[s]) / (edge[s + 1] - edge[s]));
    }
    for (int i = 0; i < MX_N; ++i) win[i] = 0.5f - 0.5f * (float)cos(2 * PI * i / (MX_N - 1));
    for (int c = 0; c < MX_CEPS; ++c)
        for (int m = 0; m < MX_MELS; ++m) dct[c][m] = (float)cos(PI * (c + 1) * (m + 0.5f) / MX_MELS);
    for (int fr = 0; fr < frames; ++fr) {
        const short *x = pcm + fr * (MX_N / 2);
        float power = 0, mel[MX_MELS] = { 0 };
        for (int i = 0; i < MX_N; ++i) {
            power += (float)x[i] * x[i];
            re[i] = x[i] * win[i] / 32768.0f;
            im[i] = 0;
        }
        if (power / MX_N < 1074) continue; /* -60 dBFS: 32768 / 1000, squared */
        ++voiced;
        vis_fft(re, im, MX_N);
        for (int k = 0; k <= MX_N / 2; ++k) {
            float p = re[k] * re[k] + im[k] * im[k];
            int s = seg[k];
            if (s < 0) continue;
            if (s < MX_MELS) mel[s] += t[k] * p;
            if (s > 0) mel[s - 1] += (1 - t[k]) * p;
        }
        float floor = 1e-30f; /* 60 dB under the frame's energy: relative, so loudness still cancels */
        for (int m = 0; m < MX_MELS; ++m) floor += mel[m] * 1e-6f;
        for (int m = 0; m < MX_MELS; ++m) mel[m] = (float)log(mel[m] + floor);
        for (int c = 0; c < MX_CEPS; ++c) {
            float v = 0;
            for (int m = 0; m < MX_MELS; ++m) v += dct[c][m] * mel[m];
            sum[c] += v;
            sq[c] += (double)v * v;
        }
    }
    if (voiced < 10 || voiced * 5 < frames) return 0;
    for (int c = 0; c < MX_CEPS; ++c) {
        double mean = sum[c] / voiced, var = sq[c] / voiced - mean * mean;
        out[c] = (float)mean;
        out[MX_CEPS + c] = var > 0 ? (float)__builtin_sqrt(var) : 0;
    }
    return 1;
}

/* ---- The profile cache ------------------------------------------------------------------- */

static int mx_stat(const char *path, unsigned *size, unsigned *mtime) {
#ifdef PEQ_HOST
    struct stat s;
    if (stat(path, &s)) return 0;
    *size = (unsigned)s.st_size, *mtime = (unsigned)s.st_mtime;
#else
    unsigned s[36]; /* o32 stat: st_size word 12, st_mtime word 16 (tidal.c) */
    if (__xstat(3, path, s)) return 0;
    *size = s[12], *mtime = s[16];
#endif
    return 1;
}

/* MX_FILE into mx.head and mx.tab: a bad header, version or length drops it whole, and every song
 * is heard again. */
static void mx_load(void) {
    free(mx.head);
    mx.head = 0, mx.tab = 0, mx.ntab = 0;
    mx_head h;
    void *f = fopen(MX_FILE, "rb");
    if (!f) return;
    if (fread(&h, sizeof h, 1, f) == 1 && h.magic == MX_MAGIC && h.version == MX_VERSION && h.count < 1u << 20 &&
        (mx.head = calloc(1, sizeof h + (h.count + 1) * sizeof *mx.tab)) &&
        fread(mx.tab = (mx_prof *)(mx.head + 1), sizeof *mx.tab, h.count, f) == h.count)
        mx.ntab = (int)h.count;
    fclose(f);
    for (int i = 1; i < mx.ntab; ++i) /* sorted, or none */
        if (mx.tab[i - 1].key >= mx.tab[i].key) mx.ntab = 0;
}

static const mx_prof *mx_find(unsigned key) {
    int lo = 0, hi = mx.ntab;
    while (lo < hi) {
        int mid = lo + (hi - lo) / 2;
        if (mx.tab[mid].key < key)
            lo = mid + 1;
        else
            hi = mid;
    }
    return lo < mx.ntab && mx.tab[lo].key == key ? &mx.tab[lo] : 0;
}

static int by_key(const void *a, const void *b) {
    const mx_prof *x = a, *y = b; /* then the old profile before the new (pad 1) */
    return x->key != y->key ? (x->key > y->key) - (x->key < y->key) : x->pad - y->pad;
}

/* The jobs heard since the last merge, up to upto, into the table (replacing a song's older
 * profile), and the whole written while the card is there. Out of memory, the jobs wait for the
 * next merge. ponytail: rewritten whole on the UI thread every MX_SAVE_EVERY songs (1.2 MB at 10k);
 * gone songs' profiles stay until the file is deleted. */
static void mx_merge(int upto) {
    mx_head *h = calloc(1, sizeof *h + (mx.ntab + upto - mx.merged + 1) * sizeof(mx_prof));
    if (!h) return;
    mx_prof *tab = (mx_prof *)(h + 1);
    int n = mx.ntab;
    if (n) memcpy(tab, mx.tab, n * sizeof *tab);
    for (int i = mx.merged; i < upto; ++i)
        if (mx.jobs[i].p.status && !mx.jobs[i].cached) tab[n] = mx.jobs[i].p, tab[n++].pad = 1;
    qsort(tab, n, sizeof *tab, by_key);
    int k = 0; /* a song heard again keeps its new profile, the last of its key */
    for (int i = 0; i < n; ++i) {
        if (k && tab[i].key == tab[k - 1].key) --k;
        tab[k] = tab[i];
        tab[k++].pad = 0;
    }
    *h = (mx_head){ MX_MAGIC, MX_VERSION, (unsigned)k };
    free(mx.head);
    mx.head = h, mx.tab = tab, mx.ntab = k, mx.merged = upto;
#ifndef PEQ_HOST
    if (g_usblink_status == 2) return; /* the card is the computer's */
#endif
    if (!access(MX_DIR, 0) && card_space(MX_DIR)) blob_io(MX_FILE, MX_FILE ".tmp", h, sizeof *h + k * sizeof *tab, 1);
}

/* ---- Listening (the worker thread: files and the jobs only) ------------------------------- */

int taglib_length(const char *path); /* navigation.c: TagLib's seconds, 0 unknown */

/* One song's clip through ffmpeg (nice 19) into pcm; its profile into j->p. Stays 0 when the run
 * was killed (Cancel), so the song is heard next time. */
static void mx_hear(mx_job *j, short *pcm) {
    int len = j->len > 0 ? j->len : taglib_length(j->path) - j->start;
    int at = j->start + (len > MX_CLIP_S ? (len - MX_CLIP_S) / 2 : 0), status = -1;
    char ss[16], dur[16];
    snprintf(ss, sizeof ss, "%d", at);
    snprintf(dur, sizeof dur, "%d", len > 0 && len < MX_CLIP_S ? len : MX_CLIP_S);
    int pid = fork();
    if (!pid) {
        mx_nice(19);
        execl(MX_FFMPEG, MX_FFMPEG, "-nostdin", "-v", "quiet", "-ss", ss, "-t", dur, "-i", j->path, "-map",
              "0:a:0", "-ac", "1", "-ar", "22050", "-f", "s16le", "-y", MX_RAW, (char *)0);
        child_exit(127);
    }
    mx.pid = pid;
    if (mx.cancel && pid > 0) mx_kill(pid, 9); /* cancelled before the pid was there to kill */
    while (pid > 0 && waitpid(pid, &status, 0) < 0 && *__errno_location() == 4) { /* EINTR */
    }
    mx.pid = 0;
    if (pid <= 0 || (status & 0x7f) || status >> 8 == 127) return; /* no fork, killed, or no ffmpeg */
    int n = 0;
    void *f = status ? 0 : fopen(MX_RAW, "rb");
    if (f) n = (int)fread(pcm, sizeof *pcm, MX_CLIP_S * MX_RATE, f), fclose(f);
    unlink(MX_RAW);
    if (n < MX_RATE && access(j->path, 0)) return; /* the card went: heard next time */
    j->p.sec = (unsigned short)(len > 0 && len < 65536 ? len : 0);
    j->p.status = n >= MX_RATE && mx_features(pcm, n, j->p.f) ? MX_OK : MX_FAILED;
}

/* First every song's file checked against its profile (mx.checked), then the rest heard in the
 * jobs' order (mx.heard of mx.need). */
static void *mx_worker(void *unused) {
    mx_nice(19); /* this thread alone (Linux): the MFCCs yield to the UI and the player */
    for (; mx.checked < mx.njobs && !mx.cancel; ++mx.checked) {
        mx_job *j = &mx.jobs[mx.checked];
        const mx_prof *old = mx_find(j->p.key);
        j->cached = !j->path || !mx_stat(j->path, &j->p.size, &j->p.mtime) || /* gone: nothing to hear */
                    (old && old->size == j->p.size && old->mtime == j->p.mtime);
        mx.need += !j->cached;
    }
    short *pcm = mx.cancel ? 0 : calloc(MX_CLIP_S * MX_RATE, sizeof *pcm);
    for (int i = 0; pcm && i < mx.njobs && !mx.cancel; ++i) {
        __sync_synchronize(); /* the jobs before i written before at says so */
        mx.at = i;
        if (mx.jobs[i].cached) continue;
        if (access(MX_DIR, 0)) break; /* the card went */
        mx_hear(&mx.jobs[i], pcm);
        if (!mx.cancel) mx.heard++;
    }
    free(pcm);
    mx.finished = 1;
    return 0;
}

/* The worker cancelled (its ffmpeg killed) and joined; what it heard merged and saved. */
static void mx_stop(void) {
    if (!mx.jobs) return; /* nothing listening (standby calls this every time) */
    if (mx.running) {
        mx.cancel = 1;
        int pid = mx.pid;
        if (pid > 0) mx_kill(pid, 9);
        pthread_join(mx.thread, 0);
        mx.running = 0;
    }
    mx_merge(mx.njobs);
    for (int i = 0; i < mx.njobs; ++i) free(mx.jobs[i].path);
    free(mx.jobs);
    mx.jobs = 0;
    mx.njobs = mx.merged = 0;
}

/* ---- Choosing ---------------------------------------------------------------------------- */

/* s lowercased (ASCII), FNV-hashed; 0 for none. */
static unsigned mx_hash(const char *s, unsigned n) {
    unsigned h = 2166136261u;
    for (unsigned i = 0; s && i < n && s[i]; ++i) {
        unsigned char c = (unsigned char)s[i];
        h = (h ^ ((unsigned)(c - 'A') < 26u ? c + 32u : c)) * 16777619u;
    }
    return s && n && *s ? h | !h : 0;
}

/* A genre tag's first four names (split at ; / , |, spaces trimmed), hashed. */
static void mx_genres(const char *s, unsigned *g) {
    for (int k = 0; s && *s && k < 4;) {
        while (*s == ' ') ++s;
        unsigned n = 0;
        while (s[n] && s[n] != ';' && s[n] != '/' && s[n] != ',' && s[n] != '|') ++n;
        unsigned e = n;
        while (e && s[e - 1] == ' ') --e;
        if (e) g[k++] = mx_hash(s, e);
        s += n + !!s[n];
    }
}

static float mx_prefs(const mx_song *s) {
    float m = HEARTS[s->hearts < 6 ? s->hearts : 0] * (1 + (HEARTS[s->album_hearts < 6 ? s->album_hearts : 0] - 1) / 2);
    float p = 1 + 0.04f * (float)(log(1 + s->plays) / log(2));
    return m * (p < 1.15f ? p : 1.15f);
}

static int by_float(const void *a, const void *b) {
    float x = *(const float *)a, y = *(const float *)b;
    return (x > y) - (x < y);
}

/* Every song's score: a seed (album) track's from the user's hearts and plays alone, any other's
 * from how near it sounds to the nearest album track and what the tags agree on, times the same
 * preferences. A song not heard counts as of middling sound and needs the tags' floor, so the mix
 * is never padded with unrelated music; under MX_SHORT_S scores 0. */
static void mx_rank(mx_song *v, int n) {
    unsigned artists[16], genres[16];
    int na = 0, ng = 0, years = 0, nyears = 0, secs = 0, nsecs = 0, nref = 0, nprof = 0;
    int *ref = calloc(n + 1, sizeof *ref);
    float *d = calloc(n + 1, sizeof *d), w[MX_DIMS] = { 0 }, mean[MX_DIMS] = { 0 }, sigma = 0;
    for (int i = 0; i < n; ++i) {
        const mx_song *s = &v[i];
        if (s->prof) {
            ++nprof;
            for (int k = 0; k < MX_DIMS; ++k) mean[k] += s->prof->f[k], w[k] += s->prof->f[k] * s->prof->f[k];
        }
        if (!s->seed) continue;
        for (int k = 0; k < 2; ++k) {
            unsigned a = k ? s->album_artist : s->artist;
            int seen = !a;
            for (int j = 0; j < na; ++j) seen |= artists[j] == a;
            if (!seen && na < 16) artists[na++] = a;
        }
        for (int k = 0; k < 4 && s->genre[k]; ++k) {
            int seen = 0;
            for (int j = 0; j < ng; ++j) seen |= genres[j] == s->genre[k];
            if (!seen && ng < 16) genres[ng++] = s->genre[k];
        }
        if (s->year > 0) years += s->year, ++nyears;
        if (s->sec > 0) secs += s->sec, ++nsecs;
        if (ref && s->prof && !MX_SHORT(s)) ref[nref++] = i;
    }
    for (int i = 0; ref && !nref && i < n; ++i) /* an album of short tracks: all of them */
        if (v[i].seed && v[i].prof) ref[nref++] = i;
    /* every dimension weighed by its spread across the library (z-scores; the means cancel) */
    for (int k = 0; nprof > 1 && k < MX_DIMS; ++k) {
        float m = mean[k] / nprof, var = w[k] / nprof - m * m;
        w[k] = var > 1e-6f ? 1 / var : 0;
    }
    int nd = 0;
    for (int i = 0; d && nref && nprof > 1 && i < n; ++i) {
        mx_song *s = &v[i];
        if (s->seed || !s->prof) continue;
        float best = 1e30f;
        for (int r = 0; r < nref; ++r) {
            const float *a = s->prof->f, *b = v[ref[r]].prof->f;
            float dist = 0;
            for (int k = 0; k < MX_DIMS; ++k) dist += w[k] * (a[k] - b[k]) * (a[k] - b[k]);
            if (dist < best) best = dist;
        }
        s->score = best; /* for now: the squared distance */
        d[nd++] = best;
    }
    if (nd) { /* the median distance is a similarity of one half */
        qsort(d, nd, sizeof *d, by_float);
        sigma = d[nd / 2] > 1e-6f ? d[nd / 2] : 1e-6f;
    }
    int year = nyears ? years / nyears : 0, sec = nsecs ? secs / nsecs : 0;
    for (int i = 0; i < n; ++i) {
        mx_song *s = &v[i];
        if (s->seed) {
            s->score = mx_prefs(s);
            continue;
        }
        float m = 0, sound = 0.5f;
        int same = 0, shared = 0, mine = 0;
        for (int j = 0; j < na; ++j) same |= (s->artist && artists[j] == s->artist) || (s->album_artist && artists[j] == s->album_artist);
        for (int k = 0; k < 4 && s->genre[k]; ++k, ++mine)
            for (int j = 0; j < ng; ++j) shared += genres[j] == s->genre[k];
        if (same) m += W.artist;
        if (mine + ng - shared) m += W.genre * shared / (mine + ng - shared);
        if (year && s->year > 0 && s->year - year <= 5 && year - s->year <= 5) m += W.year;
        if (sec && s->sec > 0 && 2 * s->sec >= sec && s->sec <= 2 * sec) m += W.length;
        if (sigma > 0 && s->prof)
            sound = 1 / (1 + s->score / sigma);
        else if (m < W.floor)
            m = -1; /* not heard, and the tags don't vouch for it */
        s->score = MX_SHORT(s) || m < 0 ? 0 : (W.sound * sound + W.tags * m) * mx_prefs(s);
    }
    free(ref);
    free(d);
}

/* The song for list[slot] (len slots, -1 empty): one of the MX_TOP best not yet used or struck,
 * drawn by score squared. Rules: a different artist from both neighbours, at most two songs by an
 * artist and one from an album besides the seed's, and no second copy of a title by the same
 * artist. -1 when none qualifies. */
static int mx_fill(mx_song *v, int n, const int *list, int len, int slot) {
    int top[MX_TOP], k = 0;
    const mx_song *prev = slot > 0 && list[slot - 1] >= 0 ? &v[list[slot - 1]] : 0,
                  *next = slot + 1 < len && list[slot + 1] >= 0 ? &v[list[slot + 1]] : 0;
    for (int i = 0; i < n; ++i) {
        const mx_song *c = &v[i];
        if (c->seed || c->flags || c->score <= 0) continue;
        if (c->artist && ((prev && prev->artist == c->artist) || (next && next->artist == c->artist))) continue;
        int artist = 0, album = 0, copy = 0;
        for (int j = 0; j < len; ++j) {
            if (j == slot || list[j] < 0) continue;
            const mx_song *o = &v[list[j]];
            if (!o->seed) artist += c->artist && o->artist == c->artist, album += o->album == c->album;
            copy |= c->title && o->title == c->title && o->artist == c->artist;
        }
        if (artist >= 2 || album || copy || (k == MX_TOP && v[top[MX_TOP - 1]].score >= c->score)) continue;
        int at = k < MX_TOP ? k++ : MX_TOP - 1;
        for (; at > 0 && v[top[at - 1]].score < c->score; --at) top[at] = top[at - 1];
        top[at] = i;
    }
    if (!k) return -1;
    float sum = 0;
    for (int i = 0; i < k; ++i) sum += v[top[i]].score * v[top[i]].score;
    float r = (float)rand_below(1u << 20) / (1 << 20) * sum;
    for (int i = 0; i < k; ++i)
        if ((r -= v[top[i]].score * v[top[i]].score) < 0) return top[i];
    return top[k - 1];
}

/* A seed track for a craft: not short (unless all are), unused; one of the best three by
 * preference when best, else any. -1 when none. */
static int mx_seed(mx_song *v, int n, int best) {
    int top[3], k = 0, any = 0, seen = 0, pick = -1;
    for (int i = 0; i < n; ++i) any |= v[i].seed && !MX_SHORT(&v[i]);
    for (int i = 0; i < n; ++i) {
        const mx_song *c = &v[i];
        if (!c->seed || c->flags || (any && MX_SHORT(c))) continue;
        if (!best) {
            if (!rand_below((unsigned)++seen)) pick = i; /* reservoir: each equally likely */
            continue;
        }
        if (k == 3 && v[top[2]].score >= c->score) continue;
        int at = k < 3 ? k++ : 2;
        for (; at > 0 && v[top[at - 1]].score < c->score; --at) top[at] = top[at - 1];
        top[at] = i;
    }
    return !best ? pick : k ? top[rand_below((unsigned)k)] : -1;
}

/* A new mix into list: the album's best-loved track first, two more of its tracks a third and two
 * thirds in when it has three or more, the rest filled in order until about MX_TARGET_S or
 * MX_MAX songs. Returns how many. */
static int mx_craft(mx_song *v, int n, int *list) {
    for (int i = 0; i < n; ++i) v[i].flags = 0;
    for (int i = 0; i < MX_MAX; ++i) list[i] = -1;
    int eligible = 0, total = 0, i;
    for (i = 0; i < n; ++i) eligible += v[i].seed && !MX_SHORT(&v[i]);
    if ((list[0] = mx_seed(v, n, 1)) < 0) return 0;
    v[list[0]].flags = MX_USED;
    for (int at = 4; eligible >= 3 && at <= 8; at += 4)
        if ((list[at] = mx_seed(v, n, 0)) >= 0) v[list[at]].flags = MX_USED;
    for (i = 0; i < MX_MAX; ++i) {
        if (list[i] < 0 && (list[i] = mx_fill(v, n, list, MX_MAX, i)) < 0) break;
        v[list[i]].flags = MX_USED;
        total += v[list[i]].sec > 0 ? v[list[i]].sec : MX_GUESS_S;
        if (total >= MX_TARGET_S) {
            ++i;
            break;
        }
    }
    for (int j = i; j < MX_MAX; ++j)
        if (list[j] >= 0) v[list[j]].flags = 0, list[j] = -1;
    return i;
}

/* Struck slots refilled (their songs never offered again this craft), or with none struck, every
 * slot but the album's own refilled with other picks. A slot nothing fits goes. Returns the new
 * length; struck cleared. */
static int mx_reroll(mx_song *v, int n, int *list, int len, unsigned char *struck) {
    int any = 0, k = 0;
    for (int i = 0; i < len; ++i) any |= struck[i];
    for (int i = 0; i < len; ++i)
        if (any ? struck[i] : !v[list[i]].seed) v[list[i]].flags = any ? MX_REJECTED : MX_ASIDE, list[i] = -1;
    for (int i = 0; i < len; ++i)
        if (list[i] < 0 && (list[i] = mx_fill(v, n, list, len, i)) >= 0) v[list[i]].flags = MX_USED;
    for (int i = 0; i < n; ++i)
        if (v[i].flags == MX_ASIDE) v[i].flags = 0;
    for (int i = 0; i < len; ++i)
        if (list[i] >= 0) list[k++] = list[i];
    memset(struck, 0, MX_MAX);
    return k;
}

#ifndef PEQ_HOST
/* ---- The pages --------------------------------------------------------------------------- */

void mixtape_play(void *list); /* navigation.c */
void mixtape_keep(void);
extern void *staged(int (*)(void *), void *, int *);
extern unsigned album_id(void *r);
extern const char *track_name(char *buf, unsigned size, void *t);
void toast(const char *text);

static void mx_free(void) {
    stop_timer(&mx.timer);
    mx_stop();
    if (mx.songs) deque_destroy(mx.songs);
    free(mx.v);
    free(mx.head);
    mx.songs = 0, mx.v = 0, mx.head = 0, mx.tab = 0;
    mx.n = mx.ntab = mx.len = 0;
    mx.page = mx.title = mx.note = 0;
}

static int mx_closed(void *ctx, void *event) {
    mx_free();
    return 0;
}

static int mx_leave(const void *unused) {
    mx.timer = 0;
    navigator_back();
    return 0;
}

static int mx_keyup(void *ctx, void *event) { return return_key(event, &mx.timer, mx_leave); }

static int mx_minutes(void) {
    int total = 0;
    for (int i = 0; i < mx.len; ++i)
        if (!mx.struck[i]) total += mx.v[mx.list[i]].sec > 0 ? mx.v[mx.list[i]].sec : MX_GUESS_S;
    return (total + 30) / 60;
}

static int mx_row(void *ctx, void *event);

/* The review page: Play, the songs (struck ones grey), Re-roll and Keep, row sel selected. */
static void mx_show(int sel) {
    int kept = 0, struck = 0, rows = mx.len + 3;
    for (int i = 0; i < mx.len; ++i) struck += mx.struck[i], kept += !mx.struck[i];
    void *view = page_list(mx.page, mx.page, &mx.title, "Mixtape", rows, 64);
    char name[512], detail[300], t[16];
    snprintf(detail, sizeof detail, "From %s \xc2\xb7 %d songs \xc2\xb7 %d min", mx.album, kept, mx_minutes());
    page_row_detail(view, 0, "Play Mixtape", detail, mx_row);
    for (int i = 0; i < mx.len; ++i) {
        const mx_song *s = &mx.v[mx.list[i]];
        void *r = deque_at(mx.songs, (unsigned)mx.list[i]);
        const char *artist = P(r, REC_ARTIST);
        int a = artist && *artist;
        if (s->sec > 0) toolsTimeItoa(t, s->sec);
        if (mx.struck[i])
            snprintf(detail, sizeof detail, "Removed \xc2\xb7 Re-roll replaces it");
        else
            snprintf(detail, sizeof detail, "%s%s%s", a ? artist : "", a && s->sec > 0 ? " \xc2\xb7 " : "", s->sec > 0 ? t : "");
        void *item = page_row_detail(view, i + 1, track_name(name, sizeof name, r), detail, mx_row);
        for (unsigned c = 0; mx.struck[i] && c < widget_count_children(item); ++c)
            widget_set_prop_int(widget_get_child(item, c), "style:normal:text_color", (int)0xff666666u);
    }
    page_row_detail(view, mx.len + 1, "Re-roll", struck ? "New songs for the removed ones" : "New songs around the album's own", mx_row);
    page_row_detail(view, mx.len + 2, "Keep Mixtape", "Play it and save it as a playlist", mx_row);
    ringnav_select(view, sel < rows ? sel : rows - 1, rows);
}

static int mx_refresh(const void *unused) {
    mx.timer = 0;
    if (mx.page) mx_show(mx.sel);
    return 0;
}

static int mx_said(const void *unused) {
    toast(mx.said);
    return 0;
}

/* Play (or Keep): the unstruck songs replace the queue in their order; the page goes from under
 * Now Playing, so Return lands on Coverflow. */
static int mx_go(const void *keep) {
    mx.timer = 0;
    void *list = _create_deque("stSongInfo");
    deque_init(list);
    for (int i = 0; i < mx.len; ++i)
        if (!mx.struck[i]) _deque_push_back(list, deque_at(mx.songs, (unsigned)mx.list[i]));
    int n = (int)deque_size(list);
    if (n) mixtape_play(list);
    deque_destroy(list);
    if (!n) {
        toast("Every song is removed");
        return 0;
    }
    void *page = mx.page;
    if (page) window_manager_close_window_force(window_manager(), page);
    if (keep)
        mixtape_keep();
    else
        timer_add(mx_said, 0, 0);
    return 0;
}

static int mx_row(void *ctx, void *event) {
    int i = (int)(long)ctx;
    if (mx.timer) return 0;
    if (!i || i == mx.len + 2) {
        mx.timer = timer_add(mx_go, (void *)(long)(i != 0), 0);
        return 0;
    }
    if (i <= mx.len)
        mx.struck[i - 1] ^= 1;
    else
        mx.len = mx_reroll(mx.v, mx.n, mx.list, mx.len, mx.struck);
    mx.sel = i <= mx.len ? i : mx.len + 1;
    rearm(&mx.timer, mx_refresh, 0); /* never rebuild the list under its own click */
    return 0;
}

/* Listening done or cut short: the profiles attached, the mix crafted and shown, or the page gone
 * with why. */
static int mx_craft_now(const void *unused) {
    mx.timer = 0;
    int unheard = mx.need - mx.heard;
    mx_stop();
    for (int i = 0; i < mx.n; ++i) {
        const mx_prof *p = mx_find(mx.v[i].key);
        mx.v[i].prof = p && p->status == MX_OK ? p : 0;
        if (mx.v[i].sec <= 0 && p && p->sec) mx.v[i].sec = p->sec;
    }
    mx_rank(mx.v, mx.n);
    mx.len = mx_craft(mx.v, mx.n, mx.list);
    memset(mx.struck, 0, sizeof mx.struck);
    if (mx.len >= MX_MIN) {
        mx_show(0);
        return 0;
    }
    navigator_back();
    toast(unheard > 0 ? "Not enough related music yet" : "Not enough related music");
    return 0;
}

static int mx_now(void *ctx, void *event) {
    if (!mx.timer) return 0;
    mx.cancel = 1; /* the poll crafts once the worker stops */
    return 0;
}

static int mx_poll(const void *unused) {
    if (g_usblink_status == 2 || access(MX_DIR, 0)) {
        mx.timer = 0;
        mx_stop();
        navigator_back();
        toast("Storage unavailable");
        return 0;
    }
    if (mx.finished || mx.cancel || !mx.running) return mx_craft_now(0);
    reset_poweroptions_timer(1, 1, 0); /* no standby or auto power-off while listening, as Radio */
    char s[96], left[48] = "";
    int checking = mx.checked < mx.njobs, heard = mx.heard, need = mx.need;
    if (!checking && mx.at - mx.merged >= MX_SAVE_EVERY) mx_merge(mx.at); /* a power loss keeps most */
    if (!checking && !mx.began) mx.began = (unsigned)time_now_ms(), mx.heard_at = (unsigned)heard;
    if (!checking && heard - (int)mx.heard_at >= 3) { /* the time per song so far */
        unsigned ms = ((unsigned)time_now_ms() - mx.began) / (unsigned)(heard - (int)mx.heard_at) * (unsigned)(need - heard);
        unsigned m = (ms + 59999) / 60000;
        if (m >= 60)
            snprintf(left, sizeof left, " \xc2\xb7 about %u h %u min left", m / 60, m % 60);
        else
            snprintf(left, sizeof left, " \xc2\xb7 about %u min left", m);
    }
    if (checking)
        snprintf(s, sizeof s, "Checking %d of %d songs", mx.checked, mx.njobs);
    else
        snprintf(s, sizeof s, "%d of %d songs%s", heard, need, left);
    widget_set_text_utf8(mx.title, checking ? "Checking your library\xe2\x80\xa6" : "Listening to your music\xe2\x80\xa6");
    widget_set_text_utf8(mx.note, s);
    return 8; /* RET_REPEAT */
}

static int by_score(const void *a, const void *b) {
    const mx_song *x = &mx.v[*(const int *)a], *y = &mx.v[*(const int *)b];
    if (x->seed != y->seed) return y->seed - x->seed;
    return (y->score > x->score) - (y->score < x->score);
}

/* Craft a Mixtape (navigation.c's hold menu): songs, the library's records, with what is known of
 * each in p; both taken. The page listens first to every song not yet heard, the album's first and
 * then the likeliest by their tags, so Craft Now is good early. */
void mixtape_start(void *songs, const mx_pref *p, int n, const char *album) {
    if (mx.page) {
        deque_destroy(songs);
        return;
    }
    if (!(mx.v = calloc(n + 1, sizeof *mx.v)) || !(mx.page = page_open("mixtape_page", mx_closed, mx_keyup))) {
        free(mx.v);
        mx.v = 0;
        deque_destroy(songs);
        return;
    }
    mx.songs = songs;
    mx.n = n;
    snprintf(mx.album, sizeof mx.album, "%s", album && *album ? album : "this album");
    snprintf(mx.said, sizeof mx.said, "Mixtape from %s", mx.album);
    for (int i = 0; i < n; ++i) {
        void *r = deque_at(songs, (unsigned)i);
        mx_song *s = &mx.v[i];
        const char *artist = P(r, REC_ARTIST), *aa = P(r, REC_ALBUM_ARTIST), *title = P(r, REC_TITLE);
        s->key = p[i].key, s->sec = p[i].sec, s->plays = p[i].plays, s->seed = p[i].seed;
        s->hearts = p[i].hearts, s->album_hearts = p[i].album_hearts;
        s->artist = mx_hash(artist, ~0u), s->album_artist = mx_hash(aa, ~0u), s->album = album_id(r);
        s->title = mx_hash(title, ~0u), s->year = I(r, REC_YEAR);
        mx_genres(P(r, REC_GENRE), s->genre);
    }
    mx_load();
    mx_rank(mx.v, n); /* the tags alone, for the listening order */
    int *order = calloc(n + 1, sizeof *order);
    mx.jobs = calloc(n + 1, sizeof *mx.jobs);
    for (int i = 0; order && i < n; ++i) order[i] = i;
    if (order) qsort(order, n, sizeof *order, by_score);
    for (int i = 0; order && mx.jobs && i < n; ++i) {
        void *r = deque_at(songs, (unsigned)order[i]);
        mx_job *j = &mx.jobs[mx.njobs++];
        j->path = P(r, REC_PATH) ? strdup(P(r, REC_PATH)) : 0;
        j->start = I(r, REC_CUE_START), j->len = mx.v[order[i]].sec;
        j->p.key = mx.v[order[i]].key;
    }
    free(order);
    mx.checked = mx.need = mx.heard = mx.cancel = mx.finished = mx.pid = mx.at = 0;
    mx.began = mx.heard_at = 0;
    mkdir(MX_DIR, 0755);
    void *view = page_list(mx.page, mx.page, &mx.title, "Checking your library\xe2\x80\xa6", 1, 64);
    page_row_detail(view, 0, "Craft Now", "Mix from the songs heard so far", mx_now);
    for (int k = 0; k < 2; ++k) {
        void *t = text(mx.page, 20, 130 + 30 * k, 335, 24);
        widget_set_prop_int(t, "style:normal:text_color", (int)0xffaaaaaau);
        widget_set_prop_int(t, "style:normal:font_size", 16);
        widget_set_text_utf8(t, k ? "Each song is heard once, then remembered" : "");
        if (!k) mx.note = t;
    }
    if (mx.jobs && !pthread_create(&mx.thread, 0, mx_worker, 0)) {
        mx.running = 1;
        mx.timer = timer_add(mx_poll, 0, 250);
    } else
        mx_craft_now(0);
}
#endif
