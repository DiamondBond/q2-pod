/* Bluetooth track info for the car: the now-playing record for q2mpris (patch/mpris.c).
 *
 * The stock player store needs an explicit publisher for AVRCP track information.
 *
 * Each UI pass with Bluetooth on (at most four times a second) reads what stock reads for its own
 * send: the play status, the playing record's index and count, g_play_id3_info's title, artist,
 * album and genre (the file's name when the title is empty, as stock sends it), and the play time.
 * A change of any of those, or a jump in the position (a seek), makes a new record, formatted here
 * in RAM. A worker thread writes it to RECORD_PATH, whole and renamed into place: the UI thread
 * never opens a file for it. The position goes out only with a new record; media.c keeps its own
 * clock between them, so the car's timeline runs on its own while playing. */
#include "navigation.h"

#define RECORD_PATH "/tmp/q2-bt/nowplaying"
#define RECORD_TMP "/tmp/q2-bt/nowplaying.tmp"
#define O_SAVE 0x80301 /* MIPS O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC */
#define ID3_GENRE 0x604
#define SEEK_S 3 /* a position this far from the one expected is a seek */
#define FIELD 200

/* glibc 2.28 o32 timespec, also used by stock's clock_gettime import. */
struct bm_stamp {
    long sec, nsec;
};
#ifdef __mips__
_Static_assert(sizeof(struct bm_stamp) == 8, "o32 timespec");
#endif

#define RECORD 2048 /* five 200-byte fields, the numbers and the keys fit with room to spare */
static unsigned bm_guard; /* a try-lock between the UI thread's writer and the worker's reader */
static char bm_record[RECORD]; /* the record, by the UI thread under the guard */
static unsigned bm_gen, bm_written;
static volatile unsigned bm_worker;
static char bm_key[RECORD]; /* UI: the last record without its position */
static int bm_pub_sec;
static unsigned bm_pub_at; /* UI: the position published, and when */
static int bm_playing;

static int bm_take(void) { return !__atomic_exchange_n(&bm_guard, 1, __ATOMIC_ACQUIRE); }
static void bm_release(void) { __atomic_store_n(&bm_guard, 0, __ATOMIC_RELEASE); }

/* A tag as one line: control characters become spaces, and a cut falls on a UTF-8 character
 * boundary (a continuation byte is 10xxxxxx), so q2mpris never gets a torn character. */
static void bm_field(char *out, const char *in) {
    unsigned n = 0;
    for (; in[n] && n < FIELD - 1; n++) out[n] = (unsigned char)in[n] < 32 ? ' ' : in[n];
    if (in[n]) /* cut: back over any continuation bytes to the start of the torn character */
        while (n && ((unsigned char)in[n] & 0xc0) == 0x80) n--;
    out[n] = 0;
}

static const char *bm_id3(int field) { return (const char *)g_play_id3_info + field; }

/* The worker: the latest record to RAM, whole, then renamed over the last. */
static void *bm_write_worker(void *arg) {
    char copy[sizeof bm_record];
    for (;;) {
        usleep(250000);
        if (__atomic_load_n(&bm_gen, __ATOMIC_ACQUIRE) == bm_written) continue;
        if (!bm_take()) continue;
        unsigned gen = bm_gen;
        memcpy(copy, bm_record, sizeof copy);
        bm_release();
        unsigned n = 0;
        while (copy[n]) n++;
        if (access("/tmp/q2-bt/ready", 0)) continue;
        int fd = open(RECORD_TMP, O_SAVE, 0644);
        if (fd < 0) continue;
        int ok = write(fd, copy, n) == (int)n;
        close(fd);
        if (ok && !rename(RECORD_TMP, RECORD_PATH)) bm_written = gen;
    }
    return 0;
}

/* Each UI pass (playback_poll), with Bluetooth on. */
void btmeta_poll(void) {
    static unsigned next;
    unsigned t = time_now_ms();
    if (!(g_bluetoothflag || bt_linkstatus) || (int)(t - next) < 0) return;
    next = t + 250;
    if (!bm_worker) {
        unsigned long tid;
        bm_worker = 1;
        if (pthread_create(&tid, 0, bm_write_worker, 0))
            bm_worker = 0;
        else
            pthread_detach(tid);
    }
    int status = mclGetPlayStatus(); /* 1 stopped, 2 playing, 3 paused */
    const char *state = status == 2 ? "Playing" : status == 3 ? "Paused" : "Stopped";
    void *queue = *(void *const *)mcl_pdeqplaylist;
    unsigned n = queue ? deque_size(queue) : 0;
    int pos = mclGetPlayPos(), sec = 0, total = 0;
    char title[FIELD], artist[FIELD], album[FIELD], genre[FIELD], file[FIELD] = "";
    bm_field(title, bm_id3(ID3_TITLE));
    bm_field(artist, bm_id3(ID3_ARTIST));
    bm_field(album, bm_id3(ID3_ALBUM));
    bm_field(genre, bm_id3(ID3_GENRE));
    if (queue && pos >= 0 && (unsigned)pos < n) {
        const char *record = deque_at(queue, (unsigned)pos);
        const char *path = record ? *(const char *const *)(record + 8) : 0;
        if (path) {
            const char *slash = strrchr(path, '/');
            bm_field(file, slash ? slash + 1 : path);
        }
    }
    mclGetPlayTime(&sec, &total);
    char key[sizeof bm_key];
    int k = tk_snprintf(key, sizeof key,
                        "v=1\nstatus=%s\ntitle=%s\nartist=%s\nalbum=%s\ngenre=%s\nduration=%"
                        "d\ntrack=%d\ntracks=%u\nfile=%s\n",
                        state, title[0] ? title : file, artist, album, genre, total * 1000, pos + 1,
                        n, file);
    if (k <= 0 || (unsigned)k >= sizeof key - 64)
        return; /* cannot happen with the field bounds; never a torn record */
    /* The position expected now from the last one published; a seek is a jump away from it. */
    int expected = bm_playing ? bm_pub_sec + (int)((t - bm_pub_at) / 1000) : bm_pub_sec;
    int seek = sec > expected + SEEK_S || sec + SEEK_S < expected;
    if (!tk_strcmp(key, bm_key) && !seek) return;
    struct bm_stamp stamp;
    if (clock_gettime(1 /* CLOCK_MONOTONIC */, &stamp) || stamp.sec < 0 || stamp.nsec < 0 ||
        stamp.nsec >= 1000000000)
        return; /* no invented timestamp; retry next poll */
    unsigned written = (unsigned)stamp.sec * 1000u + (unsigned)stamp.nsec / 1000000u;
    if (!bm_take()) return; /* the worker is copying; next pass */
    /* The helper uses absolute CLOCK_MONOTONIC. Toolkit time_now_ms has its own origin,
     * so only the local throttle/seek bookkeeping above uses it. Wire now wraps at 32 bits. */
    int r = tk_snprintf(bm_record, sizeof bm_record, "%snow=%u\nposition=%d\ngen=%u\n", key,
                        written, sec * 1000, bm_gen + 1);
    if (r > 0 && (unsigned)r < sizeof bm_record)
        __atomic_store_n(&bm_gen, bm_gen + 1, __ATOMIC_RELEASE);
    else
        bm_record[0] = 0; /* not published */
    bm_release();
    tk_snprintf(bm_key, sizeof bm_key, "%s", key);
    bm_pub_sec = sec;
    bm_pub_at = t;
    bm_playing = status == 2;
}
