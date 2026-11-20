/* Bluetooth track info for the car: the now-playing record for q2mpris (patch/mpris.c).
 *
 * The stock player store needs an explicit publisher for AVRCP track information.
 *
 * Each UI pass with Bluetooth on (at most four times a second) reads what stock reads for its own
 * send: the play status, the playing record's index and count, g_play_id3_info's title, artist,
 * album and genre (the file's name when the title is empty, as stock sends it), and the play time.
 * A change of any of those, or a jump in the position (a seek), makes a new record, formatted here
 * in RAM and writes it whole, then renames it on the existing /tmp tmpfs. No worker or new timer.
 * ponytail: these change-only filesystem calls can still delay the UI under memory pressure;
 * tmpfs avoids card I/O, not all scheduling/allocation latency. The position goes out only with
 * a new record; media.c keeps its own
 * clock between them, so the car's timeline runs on its own while playing. */
#include "navigation.h"

#define RECORD_PATH "/tmp/q2-bt/nowplaying"
#define RECORD_TMP "/tmp/q2-bt/nowplaying.tmp"
#define O_SAVE 0xa0301 /* MIPS O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC | O_NOFOLLOW */
#define ID3_GENRE 0x604
#define SEEK_S 3            /* a position this far from the one expected is a seek */
#define SEEK_SETTLE_MS 2000 /* Now Playing's paused-seek grace while Playing */
#define FIELD 200

/* glibc 2.28 o32 timespec, also used by stock's clock_gettime import. */
struct bm_stamp {
    long sec, nsec;
};
#ifdef __mips__
_Static_assert(sizeof(struct bm_stamp) == 8, "o32 timespec");
#endif

#define RECORD 2048 /* five 200-byte fields, the numbers and the keys fit with room to spare */
static unsigned bm_gen;
static int bm_active;
static char bm_key[RECORD]; /* UI: the last record without its position */
static int bm_pub_sec;
static unsigned bm_pub_at; /* UI: the position published, and when */
static int bm_playing;
static unsigned bm_seek_track;
static int bm_seek_sec, bm_seek_target, bm_seek_pending;
static unsigned bm_seek_at, bm_seek_played;
static int bm_seek_playing;

/* Stock leaves its reported second unchanged until Play after a paused seek. Keep the
 * committed track-relative target, including changes smaller than SEEK_S, for the snapshot. */
void btmeta_paused_seek(unsigned track, int sec, int target) {
    bm_seek_track = track;
    bm_seek_sec = sec;
    bm_seek_target = target;
    bm_seek_pending = 1;
    bm_seek_at = time_now_ms();
    bm_seek_played = 0;
    bm_seek_playing = 0;
}

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

/* Each UI pass (playback_poll), with Bluetooth on. */
void btmeta_poll(void) {
    static unsigned next;
    unsigned t = time_now_ms();
    if (!(g_bluetoothflag || bt_linkstatus)) {
        bm_active = 0;
        return;
    }
    if ((int)(t - next) < 0) return;
    next = t + 250;
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
    if (player_playtime_and_length(&sec, &total) < 0 || status == 1) sec = total = 0;
    if (bm_seek_track) {
        unsigned elapsed = t - bm_seek_at;
        if (bm_seek_playing)
            bm_seek_played += elapsed < SEEK_SETTLE_MS - bm_seek_played
                                  ? elapsed
                                  : SEEK_SETTLE_MS - bm_seek_played;
        bm_seek_at = t;
        bm_seek_playing = status == 2;
        int target = bm_seek_target + (int)(bm_seek_played / 1000);
        if (total > 0 && target > total) target = total;
        /* Playing can precede the decoder's seek. Ignore its old clock, even if it
         * advances, until it enters the committed timeline or the bounded grace ends.
         * Re-anchor explicitly on retirement: a small correction is still a correction. */
        if ((status != 2 && status != 3) || np_track() != bm_seek_track ||
            (status == 3 && sec != bm_seek_sec) || bm_seek_played == SEEK_SETTLE_MS ||
            (status == 2 && sec != bm_seek_sec && sec >= bm_seek_target && sec <= target)) {
            bm_seek_track = 0;
            bm_seek_pending = 1;
        } else
            sec = target;
    }
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
    if (bm_active && !tk_strcmp(key, bm_key) && !seek && !bm_seek_pending) return;
    struct bm_stamp stamp;
    if (clock_gettime(1 /* CLOCK_MONOTONIC */, &stamp) || stamp.sec < 0 || stamp.nsec < 0 ||
        stamp.nsec >= 1000000000)
        return; /* no invented timestamp; retry next poll */
    unsigned written = (unsigned)stamp.sec * 1000u + (unsigned)stamp.nsec / 1000000u;
    unsigned fs[32]; /* o32 statfs starts with f_type; the full structure fits. */
    if (statfs("/tmp/q2-bt", fs) || fs[0] != 0x01021994u /* TMPFS_MAGIC */) return;
    /* The helper uses absolute CLOCK_MONOTONIC. Toolkit time_now_ms has its own origin,
     * so only the local throttle/seek bookkeeping above uses it. Wire now wraps at 32 bits. */
    int tail = tk_snprintf(key + k, sizeof key - (unsigned)k, "now=%u\nposition=%d\ngen=%u\n",
                           written, sec * 1000, bm_gen + 1);
    if (tail <= 0 || (unsigned)tail >= sizeof key - (unsigned)k) return;
    int r = k + tail;
    int fd = open(RECORD_TMP, O_SAVE, 0600);
    if (fd < 0) return;
    int ok = write(fd, key, (unsigned)r) == r;
    if (close(fd)) ok = 0;
    if (!ok || rename(RECORD_TMP, RECORD_PATH)) {
        unlink(RECORD_TMP);
        return; /* Includes short/interrupted writes: retry the complete change next eligible pass.
                 */
    }
    bm_gen++;
    bm_seek_pending = 0;
    bm_active = 1;
    key[k] = 0;
    tk_snprintf(bm_key, sizeof bm_key, "%s", key);
    bm_pub_sec = sec;
    bm_pub_at = t;
    bm_playing = status == 2;
}
