/* Grouped queue traversal. Indices identify occurrences, including duplicate/CUE entries.
 * Stock still owns the queue, decoder and gapless handoff. */
#include "playback.h"
#include "offsets.inc"
#include "peq.h"
#include "stock.h"
#define M(a) (*(volatile int *)(a))
#define QUEUE_FILE "/mnt/data/ringnav-queue"
#define QUEUE_LIMIT 65536
#define HISTORY_LIMIT 4096
extern int stock_load_trampoline(void *, int, int), stock_next_trampoline(int),
    stock_prev_trampoline(void), stock_mode_trampoline(int), stock_preload_trampoline(void),
    stock_memory_trampoline(void *), stock_savequeue_trampoline(void),
    stock_change_trampoline(int);
extern void *staged(int (*)(void *), void *, int *);
extern int album_before(const void *, const void *), album_cmp(void *, void *), folder_cmp(void *, void *),
    album_only(void *, void *, int);

typedef struct {
    unsigned index, group, rank;
} entry;
typedef struct {
    int active, shuffle, repeat, folder, restoring, dirty;
    unsigned n, cursor, forced, force_end, hn, stamp;
    int saved_elapsed, save_failed, resume_pending, resume_elapsed, resume_wait;
    unsigned saved_pos;
    unsigned resume_key, resume_pos;
    entry *order, *cycle;
    unsigned *groups, *seen, *history;
} playback;
static playback s __attribute__((section(".scratch")));
static volatile int sensitivity __attribute__((section(".scratch")));
static int wheel_read __attribute__((section(".scratch")));

void wheel_load(void) {
    if (wheel_read) return;
    char buf[256] = "";
    toolsReadConfig("/mnt/data/config.ini", "Q2POD", "WHEELSENSITIVITY", buf, "100");
    int v = atoi(buf);
    char canonical[8];
    tk_snprintf(canonical, sizeof canonical, "%d", v);
    sensitivity = v >= 50 && v <= 200 && !(v % 10) && !strcmp(buf, canonical) ? v : 100;
    wheel_read = 1;
}
int wheel_value(void) {
    wheel_load();
    return sensitivity;
}
void wheel_set(int v) {
    if (v < 50 || v > 200 || v % 10) return;
    sensitivity = v;
    write_int_config(v, "Q2POD", "WHEELSENSITIVITY");
}
/* Same strict threshold and half-turn boundaries as stock get_direction. Called by the
 * encoder: no config, allocation, UI or volume work on this thread. */
int ringnav_direction(int now, int before, int threshold) {
    int v = sensitivity ? sensitivity : 100;
    threshold = (threshold * 100 + v / 2) / v;
    int d = now - before;
    if (d < -100)
        d += 200;
    else if (d > 100)
        d -= 200;
    if (d == -100 || d == 100 || (d < 0 ? -d : d) <= threshold) return 0;
    return d > 0 ? -1 : 1;
}
static void *queue(void) { return P(mcl_pdeqplaylist, 0); }
static void close_preload(void) {
    if (M(MCL_PRELOAD) == 1 && M(MCL_FD) != -1) send(M(MCL_FD), "{mcl-closegapless\\null}", 23, 0);
    M(MCL_PRELOAD) = 0;
    M(MCL_PREPOS) = -1;
}
static void release(void) {
    if (s.order) free(s.order);
    if (s.cycle) free(s.cycle);
    if (s.groups) free(s.groups);
    if (s.seen) free(s.seen);
    if (s.history) free(s.history);
    s.order = s.cycle = 0;
    s.groups = s.seen = s.history = 0;
    s.n = s.hn = s.cursor = s.forced = s.force_end = 0;
    s.resume_key = s.resume_pending = s.resume_wait = s.save_failed = 0;
}
/* Albums as Coverflow tells them apart (album_cmp: tagged albums first), or folders. */
static int group_cmp(void *a, void *b) { return s.folder ? folder_cmp(a, b) : album_cmp(a, b); }
/* Total order matching group_cmp, then index. */
static int group_before(const void *pa, const void *pb) {
    unsigned ia = ((const entry *)pa)->index, ib = ((const entry *)pb)->index;
    int d = group_cmp(deque_at(queue(), ia), deque_at(queue(), ib));
    return d ? d : ia < ib ? -1 : ia != ib;
}
static int compare(const void *pa, const void *pb) {
    const entry *a = pa, *b = pb;
    if (a->group != b->group) return a->group < b->group ? -1 : 1;
    if (a->rank != b->rank) return a->rank < b->rank ? -1 : 1;
    void *ra = deque_at(queue(), a->index), *rb = deque_at(queue(), b->index);
    int d = s.folder ? strcmp(P(ra, REC_PATH), P(rb, REC_PATH)) : album_before(&ra, &rb);
    if (!d) d = I(ra, REC_CUE_START) - I(rb, REC_CUE_START);
    return d ? d : a->index < b->index ? -1 : a->index != b->index;
}
static void shuffle(entry *v, unsigned n) {
    for (unsigned i = n; i > 1; --i) {
        unsigned j = (unsigned)toolsRandnum((int)i);
        entry t = v[i - 1];
        v[i - 1] = v[j];
        v[j] = t;
    }
}
static void make_order(entry *v) {
    for (unsigned i = 0; i < s.n; ++i) v[i] = (entry){ i, s.groups[i], 0 };
    qsort(v, s.n, sizeof *v, compare);
    if (s.shuffle == 1) {
        shuffle(v, s.n);
        return;
    }
    if (s.shuffle == 2 || s.shuffle == 4)
        for (unsigned i = 0, j; i < s.n; i = j) {
            for (j = i + 1; j < s.n && v[j].group == v[i].group; ++j) {}
            shuffle(v + i, j - i);
        }
    if (s.shuffle == 3 || s.shuffle == 4) {
        /* Rank groups with a shuffled permutation, so even random ties cannot split a group. */
        for (unsigned i = 0; i < s.n; ++i) s.cycle[i].rank = i;
        for (unsigned i = s.n; i > 1; --i) {
            unsigned j = (unsigned)toolsRandnum((int)i), t = s.cycle[i - 1].rank;
            s.cycle[i - 1].rank = s.cycle[j].rank;
            s.cycle[j].rank = t;
        }
        for (unsigned i = 0; i < s.n; ++i) v[i].group = s.cycle[s.groups[v[i].index]].rank;
        /* Stable group sort: rank is the within-group order just generated. */
        for (unsigned i = 0; i < s.n; ++i) v[i].rank = i;
        qsort(v, s.n, sizeof *v, compare);
    }
}
static void history(unsigned at) {
    /* ponytail: keep the last 4096 transitions; use an unbounded disk log if more is needed. */
    if (s.hn == HISTORY_LIMIT) {
        for (unsigned i = 1; i < s.hn; ++i) s.history[i - 1] = s.history[i];
        s.resume_key = s.resume_pending = 0;
        --s.hn;
    }
    s.history[s.hn++] = at;
}
static int rebuild(int keep) {
    unsigned n = queue() ? deque_size(queue()) : 0;
    unsigned *oldseen = s.seen, *oldhistory = s.history;
    unsigned oldn = s.n, oldhn = s.hn;
    entry *order = calloc(n + 1, sizeof *order), *cycle = calloc(n + 1, sizeof *cycle);
    unsigned *groups = calloc(n + 1, sizeof *groups), *seen = calloc(n + 1, sizeof *seen),
             *hist = calloc(HISTORY_LIMIT, sizeof *hist);
    if (!order || !cycle || !groups || !seen || !hist || n > QUEUE_LIMIT) {
        free(order);
        free(cycle);
        free(groups);
        free(seen);
        free(hist);
        return 0;
    }
    if (s.order) free(s.order);
    if (s.cycle) free(s.cycle);
    if (s.groups) free(s.groups);
    s.order = order;
    s.cycle = cycle;
    s.groups = groups;
    s.seen = seen;
    s.history = hist;
    s.n = n;
    s.hn = keep ? oldhn : 0;
    if (keep) {
        memcpy(hist, oldhistory, oldhn * sizeof *hist);
        memcpy(seen, oldseen, (oldn < n ? oldn : n) * sizeof *seen);
    }
    if (oldseen) free(oldseen);
    if (oldhistory) free(oldhistory);
    /* Sort by group_cmp; each run's group is its smallest index. cycle is scratch here. */
    for (unsigned i = 0; i < n; ++i) cycle[i].index = i;
    qsort(cycle, n, sizeof *cycle, group_before);
    for (unsigned i = 0, first = 0; i < n; ++i) {
        if (!i || group_cmp(deque_at(queue(), cycle[i - 1].index), deque_at(queue(), cycle[i].index)))
            first = cycle[i].index;
        groups[cycle[i].index] = first;
    }
    make_order(order);
    unsigned at = (unsigned)M(MCL_POS), k = 0;
    if (at < n) {
        if (!keep) history(at);
        if (s.shuffle == 1) {
            /* Shuffle All pins the current occurrence between visited and remaining entries. */
            for (unsigned i = 0; i < n; ++i)
                if (order[i].index != at && seen[order[i].index]) cycle[k++] = order[i];
            s.cursor = k;
            cycle[k++] = (entry){ at, groups[at], 0 };
            for (unsigned i = 0; i < n; ++i)
                if (order[i].index != at && !seen[order[i].index]) cycle[k++] = order[i];
            memcpy(order, cycle, n * sizeof *order);
        } else {
            if (s.shuffle >= 3) {
                /* Finish the current category before the other shuffled categories; keep its
                 * track order, even when the playing track is halfway through that category. */
                for (unsigned i = 0; i < n; ++i)
                    if (groups[order[i].index] == groups[at]) cycle[k++] = order[i];
                for (unsigned i = 0; i < n; ++i)
                    if (groups[order[i].index] != groups[at]) cycle[k++] = order[i];
                memcpy(order, cycle, n * sizeof *order);
            }
            if (s.shuffle == 2 || s.shuffle == 4) {
                unsigned first = 0, current = 0;
                while (first < n && groups[order[first].index] != groups[at]) ++first;
                while (current < n && order[current].index != at) ++current;
                entry playing = order[current];
                for (; current > first; --current) order[current] = order[current - 1];
                order[first] = playing;
            }
            for (unsigned i = 0; i < n; ++i)
                if (order[i].index == at) {
                    s.cursor = i;
                    break;
                }
            for (unsigned i = 0; i < s.cursor; ++i) seen[order[i].index] = 1;
        }
        seen[at] = 1;
    }
    /* Generate the following cycle on commit, never in the preload/peek path. */
    make_order(cycle);
    s.dirty = 1;
    return 1;
}
int playback_option(int kind) {
    return kind == 0 ? s.shuffle : kind == 1 ? (s.active ? s.repeat : 2) : s.folder;
}
int playback_set(int kind, int value) {
    if (kind < 0 || kind > 2 || value < 0 || value >= (kind == 0 ? 5 : kind == 1 ? 6 : 2)) return 0;
    if (s.active && playback_option(kind) == value) return 1;
    if (!s.active) {
        s.repeat = 2;
        s.shuffle = 0;
        s.folder = 0;
    }
    if (kind == 0)
        s.shuffle = value;
    else if (kind == 1)
        s.repeat = value;
    else
        s.folder = value;
    close_preload();
    s.forced = s.force_end = 0;
    s.active = rebuild(s.active);
    playback_save();
    return s.active;
}
int playback_groups(void *all, int folder) {
    if (!deque_size(all)) return 0;
    mclLoadPlayList(all, 0, 0xf001);
    s.folder = folder;
    s.shuffle = 3;
    s.repeat = 2;
    s.active = rebuild(0);
    if (!s.active) return 0;
    make_order(s.order);
    int at = (int)s.order[0].index;
    play_folder(all, at, 0xf001);
    playback_save();
    return 1;
}
/* Peek has no side effects, RNG or history writes. Manual next bypasses single-song rules. */
int playback_successor(int automatic) {
    unsigned at = (unsigned)M(MCL_POS);
    if (!s.active || at >= s.n) return -1;
    if (automatic && s.repeat == 0) return -1;
    if (automatic && s.repeat == 3) return (int)at;
    int category = s.repeat == 1 || s.repeat == 4;
    if (s.forced && s.forced <= s.n && (!category || s.groups[s.forced - 1] == s.groups[at]))
        return (int)s.forced - 1;
    for (unsigned i = s.cursor + 1; i < s.n; ++i)
        if (!s.seen[s.order[i].index] && (!category || s.groups[s.order[i].index] == s.groups[at]))
            return (int)s.order[i].index;
    if (s.repeat < 3) return -1;
    for (unsigned i = 0; i < s.n; ++i)
        if (!category || s.groups[s.cycle[i].index] == s.groups[at]) return (int)s.cycle[i].index;
    return -1;
}
static void commit(unsigned next) {
    s.resume_key = s.resume_pending = 0;
    if (s.forced && next == s.forced - 1) {
        s.forced = next + 1 < s.force_end ? next + 2 : 0;
        /* Move the priority occurrence immediately after the cursor, leaving other order intact. */
        unsigned i = 0;
        while (i < s.n && s.order[i].index != next) ++i;
        if (i > s.cursor && i < s.n) {
            entry t = s.order[i];
            for (; i > s.cursor + 1; --i) s.order[i] = s.order[i - 1];
            s.order[i] = t;
        }
    }
    unsigned i = s.cursor + 1;
    while (i < s.n && s.order[i].index != next) ++i;
    if ((i == s.n || s.seen[next]) && !(s.repeat == 3 && next == (unsigned)M(MCL_POS))) {
        memcpy(s.order, s.cycle, s.n * sizeof *s.order);
        memset(s.seen, 0, s.n * sizeof *s.seen);
        make_order(s.cycle);
        for (i = 0; i < s.n && s.order[i].index != next; ++i) {}
    }
    if (i < s.n) s.cursor = i;
    s.seen[next] = 1;
    history(next);
    s.dirty = 1;
}
int ringnav_load(void *q, int at, int type) {
    if (s.restoring == 2) type = M(MCL_TYPE);
    close_preload();
    int result = stock_load_trampoline(q, at, type);
    if (s.restoring == 2)
        s.restoring = 0;
    else if (!s.restoring) {
        s.resume_key = s.resume_pending = 0;
        s.forced = s.force_end = 0;
        if (s.active && (type == 1 || (type & 0xf000) == 0xf000))
            s.active = rebuild(0);
        else {
            s.active = 0;
            release();
            unlink(QUEUE_FILE);
        }
    }
    return result;
}
int ringnav_mode(int mode) {
    /* Stock keeps a preload when selecting List Play; an advanced repeat preload may wrap. */
    if (s.active) close_preload();
    s.active = 0;
    release();
    unlink(QUEUE_FILE);
    return stock_mode_trampoline(mode);
}
/* List Play on a library queue's last track. Stock stops there at a natural end, but its manual
 * Next wraps to the first track (player_change_music, without mclNextSong); both stop instead. */
static int list_end(void) {
    return M(MCL_MODE) == 0 && (M(MCL_TYPE) & 0xf000) == 0xf000 && queue() && M(MCL_POS) >= 0 &&
           (unsigned)M(MCL_POS) + 1 == deque_size(queue());
}
int ringnav_next(int automatic) {
    if (!s.active) {
        if (list_end()) {
            close_preload();
            mclStop();
            return -1;
        }
        return stock_next_trampoline(automatic);
    }
    int next = playback_successor(automatic);
    if (next < 0) {
        close_preload();
        mclStop();
        return -1;
    }
    commit((unsigned)next);
    if (automatic && M(MCL_PRELOAD) == 1 && M(MCL_PREPOS) == next)
        return stock_next_trampoline(automatic); /* stock consumes the preloaded decoder */
    close_preload();
    M(MCL_POS) = next;
    return mclStartPlayer();
}
int ringnav_prev(void) {
    if (!s.active) return stock_prev_trampoline();
    if (s.hn < 2) return 1;
    s.resume_key = s.resume_pending = 0;
    --s.hn;
    unsigned at = s.history[s.hn - 1];
    close_preload();
    M(MCL_POS) = (int)at;
    for (unsigned i = 0; i < s.n; ++i)
        if (s.order[i].index == at) {
            s.cursor = i;
            break;
        }
    s.dirty = 1;
    return mclStartPlayer();
}
/* Manual Next/Prev (player_change_music). List Play stops at a library queue's end, as above. At
 * queue index 0 or n-1 stock wraps or loads a sibling folder itself; in Repeat All without Folder
 * Skip every branch calls mclNextSong(0)/mclPrevSong, so advanced order applies. MCL_MODE is
 * written directly: mclSetPlayMode would end advanced play. */
int ringnav_change(int next) {
    if (!s.active) {
        if (!next || !list_end()) return stock_change_trampoline(next);
        ringnav_next(0); /* stops */
        return 0;        /* the caller toasts -1 (no storage) and -5 */
    }
    volatile unsigned char *skip = (volatile unsigned char *)MCL_JUMPFOLDER;
    int mode = M(MCL_MODE);
    unsigned char was = *skip;
    M(MCL_MODE) = 3;
    *skip = 0;
    int result = stock_change_trampoline(next);
    M(MCL_MODE) = mode;
    *skip = was;
    return result;
}
int playback_group_skip(int forward) {
    if (!s.active && !playback_set(2, s.folder)) return 0;
    unsigned at = (unsigned)M(MCL_POS), next = s.n;
    if (at >= s.n) return 0;
    unsigned group = s.groups[at];
    if (forward) {
        for (unsigned i = s.cursor + 1; i < s.n; ++i)
            if (!s.seen[s.order[i].index] && s.groups[s.order[i].index] != group) {
                next = s.order[i].index;
                break;
            }
        if (next == s.n && s.repeat >= 3)
            for (unsigned i = 0; i < s.n; ++i)
                if (s.groups[s.cycle[i].index] != group) {
                    next = s.cycle[i].index;
                    break;
                }
        if (next == s.n) return 0;
        for (unsigned i = 0; i < s.n; ++i)
            if (s.groups[i] == group) s.seen[i] = 1;
        s.forced = s.force_end = 0;
        commit(next);
    } else {
        unsigned h = s.hn;
        while (h && s.groups[s.history[h - 1]] == group) --h;
        if (!h) return 0;
        group = s.groups[s.history[h - 1]];
        for (unsigned i = 0; i < s.n; ++i)
            if (s.groups[s.order[i].index] == group) {
                next = s.order[i].index;
                s.cursor = i;
                break;
            }
        if (next == s.n) return 0;
        for (unsigned i = 0; i < s.n; ++i)
            if (s.groups[i] == group) s.seen[i] = 0;
        s.hn = h;
        history(next);
        s.seen[next] = 1;
        s.forced = s.force_end = s.resume_key = s.resume_pending = 0;
        s.dirty = 1;
    }
    close_preload();
    M(MCL_POS) = (int)next;
    mclStartPlayer();
    playback_save();
    return 1;
}
int ringnav_preload(void) {
    if (!s.active) return stock_preload_trampoline();
    int next = playback_successor(1);
    if (next < 0) return 1;
    M(MCL_PREPOS) = next;
    return mcl_open_preload();
}
void playback_insert(unsigned at, unsigned n, int next) {
    if (!s.active) return;
    close_preload();
    /* Remap occurrences before grouping is recomputed. */
    unsigned *seen = calloc(s.n + n + 1, sizeof *seen);
    if (!seen) {
        s.active = 0;
        release();
        unlink(QUEUE_FILE);
        return;
    }
    for (unsigned i = 0; i < s.n; ++i) seen[i >= at ? i + n : i] = s.seen[i];
    free(s.seen);
    s.seen = seen;
    s.n += n;
    for (unsigned i = 0; i < s.hn; ++i)
        if (s.history[i] >= at) s.history[i] += n;
    s.active = rebuild(1);
    if (next) {
        s.forced = at + 1;
        s.force_end = at + n;
    }
    playback_save();
}

/* Snapshot fields are little-endian uint32 on this MIPS target, no pointers. */
typedef struct {
    unsigned magic, version, size, checksum, n, pos, elapsed, shuffle, repeat, folder, cursor, hn,
        forced, force_end, type;
} snapshot;
static unsigned checksum(void *buf, unsigned size) { return hash_bytes(FNV_SEED, buf, size); }
void playback_save(void) {
    if (!s.active) return;
    if (!s.n) {
        unlink(QUEUE_FILE);
        return;
    }
    int sec = 0, total = 0;
    mclGetPlayTime(&sec, &total);
    if (!sec && s.resume_wait && s.resume_key && (unsigned)M(MCL_POS) == s.resume_pos)
        sec = s.resume_elapsed;
    else if (sec > 0)
        s.resume_wait = 0;
    if (sec < 0) sec = 0;
    if (!s.dirty && sec == s.saved_elapsed && (unsigned)M(MCL_POS) == s.saved_pos) return;
    /* Failed checkpoints stay pending, but the UI loop retries at most every five seconds. */
    s.dirty = s.save_failed = 1;
    s.stamp = time_now_ms();
    unsigned size = sizeof(snapshot) + (s.n * 3 + s.hn) * 4;
    for (unsigned i = 0; i < s.n; ++i) {
        const char *path = P(deque_at(queue(), i), REC_PATH);
        unsigned len = path ? strlen(path) : 0;
        if (!len || len >= 1024) return;
        size += 12 + len + 1;
    }
    unsigned char *buf = calloc(size, 1);
    if (!buf) return;
    snapshot h = { 0x5132524e,
                   2,
                   size,
                   0,
                   s.n,
                   (unsigned)M(MCL_POS),
                   (unsigned)sec,
                   (unsigned)s.shuffle,
                   (unsigned)s.repeat,
                   (unsigned)s.folder,
                   s.cursor,
                   s.hn,
                   s.forced,
                   s.force_end,
                   (unsigned)M(MCL_TYPE) };
    memcpy(buf, &h, sizeof h);
    unsigned char *p = buf + sizeof h;
    for (unsigned i = 0; i < s.n * 3 + s.hn; ++i) {
        unsigned index = i < s.n       ? s.order[i].index
                         : i < s.n * 2 ? s.cycle[i - s.n].index
                         : i < s.n * 3 ? s.seen[i - s.n * 2]
                                       : s.history[i - s.n * 3];
        memcpy(p, &index, 4);
        p += 4;
    }
    for (unsigned i = 0; i < s.n; ++i) {
        void *r = deque_at(queue(), i);
        const char *path = P(r, REC_PATH);
        unsigned identity[] = { strlen(path) + 1, (unsigned)I(r, REC_CUE_START),
                                (unsigned)I(r, REC_CUE_END) };
        memcpy(p, identity, sizeof identity);
        p += sizeof identity;
        memcpy(p, path, identity[0]);
        p += identity[0];
    }
    ((snapshot *)buf)->checksum = checksum(buf, size);
    int ok = blob_io(QUEUE_FILE, QUEUE_FILE ".tmp", buf, size, 1);
    free(buf);
    if (ok) {
        s.saved_elapsed = sec;
        s.saved_pos = (unsigned)M(MCL_POS);
        s.dirty = s.save_failed = 0;
    }
}
static int library(void *unused) {
    (void)unused;
    return getAllMusic(0);
}
static int directory(void *path) { return toolsLoadDirectory(path); }
/* Stock resume rebuilds an album queue (0xff10) from every album of its name (getMusicByAlbum):
 * the playing track's album alone. */
static int stock_memory(void *out) {
    int at = stock_memory_trampoline(out);
    return at >= 0 && I(g_memory_info, 0) == 0xff10 ? album_only(out, deque_at(out, (unsigned)at), at) : at;
}
int ringnav_memory(void *out) {
    wheel_load();
    if (!g_memory_play && !g_carmode) return stock_memory(out);
    void *f = fopen(QUEUE_FILE, "rb");
    if (!f) return stock_memory(out);
    /* V1 omitted queue provenance. Treat those queues as local lists rather than allowing
     * Folder Skip to escape the saved queue after the user selects a stock play mode. */
    snapshot h = { 0 };
    unsigned header_size = sizeof h - sizeof h.type;
    int ok = fread(&h, header_size, 1, f) == 1 && h.magic == 0x5132524e &&
             (h.version == 1 || h.version == 2);
    h.type = 0xf001;
    if (ok && h.version == 2) {
        ok = fread(&h.type, sizeof h.type, 1, f) == 1;
        header_size = sizeof h;
    }
    ok = ok && (h.type == 1 || (h.type & 0xf000) == 0xf000) && h.type <= 0xffff && h.n &&
         h.n <= QUEUE_LIMIT && h.pos < h.n && h.cursor < h.n && h.hn <= HISTORY_LIMIT &&
         h.shuffle < 5 && h.repeat < 6 && h.folder < 2 && h.elapsed <= 0x7fffffff &&
         h.forced <= h.n && h.force_end <= h.n && (!h.forced || h.forced <= h.force_end) &&
         h.size >= header_size + (h.n * 3 + h.hn) * 4 + h.n * 14 &&
         h.size <= header_size + (h.n * 3 + h.hn) * 4 + h.n * 1036;
    unsigned char *buf = ok ? calloc(h.size, 1) : 0;
    if (buf) {
        memcpy(buf, &h, header_size);
        ok = fread(buf + header_size, h.size - header_size, 1, f) == 1;
        unsigned char extra;
        if (fread(&extra, 1, 1, f)) ok = 0;
        ((snapshot *)buf)->checksum = 0;
        if (checksum(buf, h.size) != h.checksum) ok = 0;
    } else
        ok = 0;
    if (fclose(f)) ok = 0;
    /* Validate the entire snapshot before queries or mutations. */
    unsigned *indices = (unsigned *)(buf ? buf + header_size : 0);
    unsigned char *p = buf ? buf + header_size + (h.n * 3 + h.hn) * 4 : 0;
    unsigned *map = ok ? calloc(h.n, sizeof *map) : 0;
    if (!map) ok = 0;
    for (unsigned i = 0; ok && i < h.n * 3 + h.hn; ++i)
        if (i >= h.n * 2 && i < h.n * 3 ? indices[i] > 1 : indices[i] >= h.n) ok = 0;
    for (unsigned cycle = 0; ok && cycle < 2; ++cycle) {
        memset(map, 0, h.n * 4);
        for (unsigned i = 0; i < h.n; ++i)
            if (map[indices[cycle * h.n + i]]++) ok = 0;
    }
    if (ok && indices[h.cursor] != h.pos) ok = 0;
    for (unsigned i = 0; ok && i < h.n; ++i) {
        unsigned identity[3];
        if ((unsigned)(buf + h.size - p) < 12) {
            ok = 0;
            break;
        }
        memcpy(identity, p, 12);
        p += 12;
        unsigned len = identity[0];
        if (len < 2 || len > 1024 || len > (unsigned)(buf + h.size - p) || p[len - 1] ||
            strlen((const char *)p) != len - 1 || identity[1] > 0x7fffffff ||
            identity[2] > 0x7fffffff) {
            ok = 0;
            break;
        }
        p += len;
    }
    if (ok && p != buf + h.size) ok = 0;
    void *rows = 0, *q = 0, *all = 0;
    if (ok) {
        q = _create_deque("stSongInfo");
        deque_init(q);
        int count;
        all = staged(library, 0, &count);
        char folder[1024] = "";
        p = buf + header_size + (h.n * 3 + h.hn) * 4;
        for (unsigned i = 0; i < h.n; ++i) {
            unsigned id[3];
            memcpy(id, p, 12);
            p += 12;
            const char *path = (const char *)p;
            p += id[0];
            map[i] = ~0u;
            if (access(path, 0)) continue;
            for (unsigned j = 0; j < deque_size(all); ++j) {
                void *r = deque_at(all, j);
                if (I(r, REC_TYPE) == 8 && !strcmp(P(r, REC_PATH), path) &&
                    (unsigned)I(r, REC_CUE_START) == id[1] &&
                    (unsigned)I(r, REC_CUE_END) == id[2]) {
                    map[i] = deque_size(q);
                    _deque_push_back(q, r);
                    break;
                }
            }
            if (map[i] != ~0u) continue;
            char parent[1024];
            memcpy(parent, path, id[0]);
            char *slash = strrchr(parent, '/');
            if (!slash) continue;
            *slash = 0;
            if (strcmp(folder, parent) || !rows) {
                if (rows) deque_destroy(rows);
                int count;
                rows = staged(directory, parent, &count);
                memcpy(folder, parent, strlen(parent) + 1);
            }
            for (unsigned j = 0; j < deque_size(rows); ++j) {
                void *r = deque_at(rows, j);
                if (I(r, REC_TYPE) == 8 && !strcmp(P(r, REC_PATH), path) &&
                    (unsigned)I(r, REC_CUE_START) == id[1] &&
                    (unsigned)I(r, REC_CUE_END) == id[2]) {
                    map[i] = deque_size(q);
                    _deque_push_back(q, r);
                    break;
                }
            }
        }
        if (rows) deque_destroy(rows);
        deque_destroy(all);
        ok = deque_size(q) != 0;
    }
    int result = -1;
    if (ok) {
        unsigned pos = map[h.pos];
        if (pos == ~0u) {
            for (unsigned i = h.cursor; i < h.n && pos == ~0u; ++i) pos = map[indices[i]];
            if (pos == ~0u) pos = 0;
            h.elapsed = 0;
        }
        s.restoring = 1;
        mclLoadPlayList(q, (int)pos, (int)h.type);
        s.shuffle = (int)h.shuffle;
        s.repeat = (int)h.repeat;
        s.folder = (int)h.folder;
        s.active = rebuild(0);
        if (s.active) {
            unsigned k = 0;
            for (unsigned i = 0; i < h.n; ++i)
                if (map[indices[i]] != ~0u) s.order[k++].index = map[indices[i]];
            k = 0;
            for (unsigned i = 0; i < h.n; ++i)
                if (map[indices[h.n + i]] != ~0u) s.cycle[k++].index = map[indices[h.n + i]];
            s.hn = 0;
            for (unsigned i = 0; i < h.hn; ++i)
                if (map[indices[h.n * 3 + i]] != ~0u) history(map[indices[h.n * 3 + i]]);
            if (!s.hn || s.history[s.hn - 1] != pos) history(pos);
            memset(s.seen, 0, s.n * 4);
            for (unsigned i = 0; i < h.n; ++i)
                if (map[i] != ~0u) s.seen[map[i]] = indices[h.n * 2 + i];
            s.seen[pos] = 1;
            for (unsigned i = 0; i < s.n; ++i)
                if (s.order[i].index == pos) {
                    s.cursor = i;
                    break;
                }
            s.forced = s.force_end = 0;
            if (h.forced)
                for (unsigned i = h.forced - 1; i < h.force_end; ++i)
                    if (map[i] != ~0u) {
                        if (!s.forced) s.forced = map[i] + 1;
                        s.force_end = map[i] + 1;
                    }
            deque_assign(out, q);
            I(g_memory_info, 0) = (int)h.type;
            mclSetStartSeekTime(g_memory_play == 2 || g_carmode ? (int)h.elapsed : 0);
            s.resume_key = fnv(FNV_SEED, P(deque_at(queue(), pos), REC_PATH));
            s.resume_pos = pos;
            s.resume_pending = s.resume_wait = 1;
            s.resume_elapsed = g_memory_play == 2 || g_carmode ? (int)h.elapsed : 0;
            result = (int)pos;
        }
        s.restoring = result >= 0 ? 2 : 0;
    }
    if (q) deque_destroy(q);
    free(map);
    free(buf);
    return result >= 0 ? result : stock_memory(out);
}
/* The queue snapshot's startup position takes precedence over per-track long-song resume. */
int playback_resumed(void *r) {
    int pending = s.resume_pending;
    s.resume_pending = 0;
    return pending && (unsigned)M(MCL_POS) == s.resume_pos &&
           fnv(FNV_SEED, P(r, REC_PATH)) == s.resume_key;
}
void playback_poll(void) {
    wheel_load();
    unsigned now = time_now_ms();
    if (s.active && ((s.dirty && !s.save_failed) || now - s.stamp >= 5000)) {
        int sec = 0, total = 0;
        mclGetPlayTime(&sec, &total);
        if (s.dirty || sec != s.saved_elapsed) playback_save();
        s.stamp = now;
    }
}

int ringnav_savequeue(void) {
    playback_save();
    return stock_savequeue_trampoline();
}
