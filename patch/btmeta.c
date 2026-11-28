/* Bluetooth track information (docs/internals.md#bluetooth-track-information): the record q2mpris
 * (patch/mpris.c) sends to bluetoothd. With Bluetooth on, each UI pass, at most four a second,
 * reads what stock's own send reads: the play status, g_play_id3_info's tags (the file's name for
 * an empty title), the queue place and the play time. A change, or a position away from the one
 * expected (a seek), writes the record whole. Between records q2mpris runs the clock on from the
 * record's CLOCK_MONOTONIC stamp. */
#include "navigation.h"

#define RECORD "/tmp/q2-bt/nowplaying" /* S90play makes the folder (tools/build.py BOOT_HOOK) */
#define ID3_GENRE 0x604
#define SEEK_S 3 /* a position this far from the one expected is a seek */
#define FIELD 200

static struct {
    unsigned key, at;    /* fnv of the last record without its position, 0 none; when it went */
    int sec, playing;    /* the position it gave, and whether it was playing */
    unsigned seek_track; /* np_track() at a seek, 0 none */
    int seek_to, seek_pending, seek_paused;
} bm;

/* Stock reports the old position until Play: a seek while paused gives its target until then, or
 * until another track. */
void btmeta_seek(int target) {
    bm.seek_track = np_track();
    bm.seek_paused = mclGetPlayStatus() == 3;
    bm.seek_to = target;
    bm.seek_pending = 1;
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

/* Each UI pass (playback_poll). */
void btmeta_poll(void) {
    static unsigned next;
    unsigned t = time_now_ms(), at, n;
    if (!(g_bluetoothflag || bt_linkstatus)) {
        bm.key = 0;
        bm.seek_pending = 0;
        return;
    }
    if ((int)(t - next) < 0) return;
    next = t + 250;
    int status = mclGetPlayStatus(); /* 1 stopped, 2 playing, 3 paused */
    const char *id3 = (const char *)g_play_id3_info, *name = 0;
    void *r = queue_now(&at, &n);
    if (r) name = P(r, REC_NAME);
    char title[FIELD], artist[FIELD], album[FIELD], genre[FIELD];
    bm_field(title, id3[ID3_TITLE] || !name ? id3 + ID3_TITLE : name);
    bm_field(artist, id3 + ID3_ARTIST);
    bm_field(album, id3 + ID3_ALBUM);
    bm_field(genre, id3 + ID3_GENRE);
    int sec = 0, total = 0;
    if (player_playtime_and_length(&sec, &total) < 0 || status == 1) sec = total = 0;
    if (bm.seek_track && (status == 1 || np_track() != bm.seek_track)) {
        bm.seek_track = 0;
        bm.seek_pending = bm.seek_paused = 0;
    }
    if (status != 3) bm.seek_paused = 0;
    if (bm.seek_pending || bm.seek_paused) sec = bm.seek_to;
    char text[2048]; /* mpris.c RECORD_MAX: four fields and the numbers fit with room to spare */
    int k =
        tk_snprintf(text, sizeof text,
                    "status=%s\ntitle=%s\nartist=%s\nalbum=%s\ngenre=%s\nduration=%d\ntrack=%u\n",
                    status == 2   ? "Playing"
                    : status == 3 ? "Paused"
                                  : "Stopped",
                    title, artist, album, genre, total * 1000, at + 1);
    unsigned key = fnv(FNV_SEED, (const unsigned char *)text);
    int expected = bm.sec + (bm.playing ? (int)((t - bm.at) / 1000) : 0);
    if (key == bm.key && sec <= expected + SEEK_S && sec + SEEK_S >= expected && !bm.seek_pending)
        return;
    tk_snprintf(text + k, sizeof text - (unsigned)k, "position=%d\nnow=%u\n", sec * 1000,
                (unsigned)(now_ns() / 1000000));
    if (!blob_io(RECORD, RECORD ".tmp", text, strlen(text), 1)) return; /* again next pass */
    bm.key = key;
    bm.seek_pending = 0;
    bm.sec = sec;
    bm.at = t;
    bm.playing = status == 2;
}
