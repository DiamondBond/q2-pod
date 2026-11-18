/* q2mpris: the Q2's now-playing track, published to bluetoothd as a media player.
 *
 * The standard BlueZ player store needs this publisher for AVRCP track information.
 * No transport-control flags are advertised: stock keeps its existing key route.
 *
 *   - The payload (patch/btmeta.c) writes RECORD_PATH in RAM, whole and renamed into place, when
 *     the track, play status or position (a seek) changes: "key=value" lines, see bm_parse.
 *   - This helper polls it four times a second and sends org.freedesktop.DBus.Properties
 *     .PropertiesChanged for org.mpris.MediaPlayer2.Player, which media.c parses (Metadata:
 *     xesam:title, xesam:artist, xesam:album, xesam:genre, mpris:length; PlaybackStatus; Position).
 *   - It registers whenever org.bluez appears (stock kills and restarts bluetoothd at every
 *     Bluetooth off/on), and unregisters while OFF_PATH exists, so the car can be compared with
 *     and without it on one firmware: create q2pod-btmeta-off on the card's root to turn it off.
 *
 * Plain libdbus, no GLib. Text buffers are fixed. Log lines go to stderr, each kind
 * at most LOG_EACH times a run. Built by tools/build.py compile_helper against the stock rootfs's
 * libdbus-1. */
#include <dbus/dbus.h>
#ifdef __mips__ /* the Q2 build: the host's libc headers are x86's, so libc is declared here (as   \
                   video.c) */
int open(const char *, int, ...), close(int), read(int, void *, unsigned),
    access(const char *, int), usleep(unsigned);
int clock_gettime(int, void *);
struct bm_timespec {
    long sec, nsec;
}; /* o32 glibc 2.28's timespec: two 32-bit words */
#define BM_CLOCK(ts) clock_gettime(1 /* CLOCK_MONOTONIC */, (ts))
unsigned strlen(const char *);
char *strchr(const char *, int);
int strcmp(const char *, const char *), memcmp(const void *, const void *, unsigned),
    atoi(const char *);
long long atoll(const char *);
unsigned long strtoul(const char *, char **, int);
void *memcpy(void *, const void *, unsigned);
int snprintf(char *, unsigned, const char *, ...), fprintf(void *, const char *, ...),
    fputc(int, void *), fflush(void *);
extern void *stderr;
#define O_RDONLY 0
#define O_CLOEXEC 0x80000 /* MIPS */
#define F_OK 0
#else
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
struct bm_timespec {
    long sec, nsec;
}; /* the host's timespec is two 64-bit words: the same layout */
#define BM_CLOCK(ts) clock_gettime(CLOCK_MONOTONIC, (struct timespec *)(ts))
#endif

#define RECORD_PATH "/tmp/q2-bt/nowplaying"
#define OFF_PATH "/mnt/mmc/q2pod-btmeta-off"
#define PLAYER_PATH "/q2pod/player"
#define PLAYER_IFACE "org.mpris.MediaPlayer2.Player"
#define BLUEZ "org.bluez"
#define ADAPTER "/org/bluez/hci0"
#define MEDIA_IFACE "org.bluez.Media1"
#define POLL_MS 250
#define LOG_EACH 20
#define RECORD_MAX 2048
#define FIELD_MAX 256

static const char *record_path = RECORD_PATH, *off_path = OFF_PATH, *bluez_name = BLUEZ,
                  *adapter_path = ADAPTER;
static DBusBusType bus_type = DBUS_BUS_SYSTEM;

/* The record as last read: strings and numbers the signals and property replies are built from. */
static struct {
    char status[16], title[FIELD_MAX], artist[FIELD_MAX], album[FIELD_MAX], genre[FIELD_MAX];
    long long length_us, position_us; /* mpris:length and Position */
    long long written_ms; /* the payload's CLOCK_MONOTONIC when it wrote the record, -1 if absent */
    int track, tracks;
    unsigned generation; /* the payload's counter, so an unchanged file is not re-sent */
} rec = { "Stopped", "", "", "", "", 0, 0, -1, 0, 0, 0 };
static long long num(const char *v, const char *end, int *bad) {
    long long n = 0;
    if (v == end) {
        *bad = 1;
        return -1;
    }
    for (const char *p = v; p < end; p++) {
        if (*p < '0' || *p > '9' || n > 99999999999LL) {
            *bad = 1;
            return -1;
        }
        n = n * 10 + (*p - '0');
    }
    return n;
}
static int registered, disabled;
static unsigned logged[8];

enum { L_BUS, L_REG, L_UNREG, L_RECORD, L_SIGNAL, L_OWNER, L_OFF, L_CALL };
static void say(int kind, const char *fmt, const char *a, long b) {
    char message[512];
    snprintf(message, sizeof message, fmt, a, b);
    if (logged[kind] >= LOG_EACH) return;
    logged[kind]++;
    fprintf(stderr, "q2mpris: %s\n", message);
    if (logged[kind] == LOG_EACH) fprintf(stderr, "q2mpris: (no more lines of this kind)\n");
    fflush(stderr);
}

/* "key=value" lines, each once, unknown keys ignored, values cut to their field, and made valid
 * UTF-8 (libdbus refuses, or aborts on, an invalid string): a bad or torn sequence becomes '?'. */
static unsigned utf8_len(const unsigned char *s,
                         unsigned n) { /* a valid sequence's length at s, 0 if none */
    unsigned len = s[0] < 0x80                             ? 1
                   : (s[0] & 0xe0) == 0xc0 && s[0] >= 0xc2 ? 2
                   : (s[0] & 0xf0) == 0xe0                 ? 3
                   : (s[0] & 0xf8) == 0xf0 && s[0] <= 0xf4 ? 4
                                                           : 0;
    if (!len || len > n) return 0;
    for (unsigned i = 1; i < len; i++)
        if ((s[i] & 0xc0) != 0x80) return 0;
    if (len == 3 && (s[0] == 0xe0 ? s[1] < 0xa0 : s[0] == 0xed && s[1] >= 0xa0))
        return 0; /* overlong, surrogates */
    if (len == 4 && (s[0] == 0xf0 ? s[1] < 0x90 : s[0] == 0xf4 && s[1] >= 0x90))
        return 0; /* overlong, > U+10FFFF */
    return len;
}
static void bm_field(char *out, unsigned size, const char *value) {
    unsigned n = 0, o = 0;
    while (value[n] && value[n] != '\n' && value[n] != '\r') n++;
    for (unsigned i = 0; i < n && o < size - 1;) {
        unsigned len = utf8_len((const unsigned char *)value + i, n - i);
        if (!len) {
            out[o++] = '?';
            i++;
            continue;
        }
        if (o + len > size - 1) break;
        memcpy(out + o, value + i, len);
        o += len;
        i += len;
    }
    out[o] = 0;
}
static int bm_parse(const char *text) {
    char status[16] = "", title[FIELD_MAX] = "", artist[FIELD_MAX] = "", album[FIELD_MAX] = "",
         genre[FIELD_MAX] = "";
    long long length_ms = 0, position_ms = 0, written_ms = -1;
    int track = 0, tracks = 0, version = 0, have_gen = 0, have_pos = 0, bad = 0;
    unsigned generation = 0;
    const char *line = text;
    /* A whole number up to the end of its line, else -1 (atoi/strtoul would take junk). */
#define NUM(v) num(v, end, &bad)
    while (*line) {
        const char *eq = strchr(line, '=');
        const char *end = strchr(line, '\n');
        if (!end) end = line + strlen(line);
        if (eq && eq < end) {
            unsigned klen = (unsigned)(eq - line);
            const char *v = eq + 1;
#define KEY(k) (klen == sizeof(k) - 1 && !memcmp(line, k, klen))
            if (KEY("v"))
                version = (int)NUM(v);
            else if (KEY("gen")) {
                generation = (unsigned)NUM(v);
                have_gen = *end == '\n';
            } else if (KEY("status"))
                bm_field(status, sizeof status, v);
            else if (KEY("title"))
                bm_field(title, sizeof title, v);
            else if (KEY("artist"))
                bm_field(artist, sizeof artist, v);
            else if (KEY("album"))
                bm_field(album, sizeof album, v);
            else if (KEY("genre"))
                bm_field(genre, sizeof genre, v);
            else if (KEY("duration"))
                length_ms = NUM(v);
            else if (KEY("position")) {
                position_ms = NUM(v);
                have_pos = *end == '\n';
            } else if (KEY("track"))
                track = (int)NUM(v);
            else if (KEY("tracks"))
                tracks = (int)NUM(v);
            else if (KEY("now"))
                written_ms = NUM(v);
#undef KEY
#undef NUM
        }
        line = *end ? end + 1 : end;
    }
    if (bad || version != 1 || !have_gen || !have_pos || !generation)
        return 0; /* junk numbers, or a torn record */
    if (strcmp(status, "Playing") && strcmp(status, "Paused") && strcmp(status, "Stopped"))
        return 0;
    if (length_ms < 0 || position_ms < 0 || length_ms > 1000000000LL || position_ms > 1000000000LL)
        return 0;
    memcpy(rec.status, status, sizeof status);
    memcpy(rec.title, title, sizeof title);
    memcpy(rec.artist, artist, sizeof artist);
    memcpy(rec.album, album, sizeof album);
    memcpy(rec.genre, genre, sizeof genre);
    rec.length_us = length_ms * 1000;
    rec.position_us = position_ms * 1000;
    rec.track = track;
    rec.tracks = tracks;
    rec.generation = generation;
    rec.written_ms = written_ms;
    return 1;
}

/* The position now: the record's, plus the time since it was read while playing (media.c keeps
 * the same clock, but a registration after a bluetoothd restart starts from a record that may be
 * minutes old). */
static long long now_ms(void) {
    struct bm_timespec ts;
    BM_CLOCK(&ts);
    return ts.sec * 1000LL + ts.nsec / 1000000;
}
static long long rec_read_at;
static long long position_now(void) {
    long long p = rec.position_us;
    /* from the payload's own CLOCK_MONOTONIC stamp when it has one (the low 32 bits of the ms; the
     * difference is taken in 32 bits, so a record older than this process, after a helper restart,
     * projects right too), else from the moment it was read; never more than a day */
    long long elapsed = rec.written_ms >= 0
                            ? (long long)(unsigned)((unsigned)now_ms() - (unsigned)rec.written_ms)
                            : now_ms() - rec_read_at;
    if (elapsed > 86400000LL) elapsed = 86400000LL;
    if (!strcmp(rec.status, "Playing")) p += elapsed * 1000;
    if (p < 0) p = 0;
    if (rec.length_us && p > rec.length_us) p = rec.length_us;
    return p;
}

/* Reads the record if its text changed since the last read (the payload renames a whole file into
 * place, so a read sees one record or the next). 1 when a new record is in `rec`. */
static int bm_read(void) {
    static char last[RECORD_MAX];
    int fd = open(record_path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    char text[RECORD_MAX];
    int n = (int)read(fd, text, sizeof text - 1);
    close(fd);
    if (n <= 0) return 0;
    text[n] = 0;
    if (!strcmp(text, last)) return 0;
    memcpy(last, text, sizeof last);
    unsigned before = rec.generation;
    struct {
        char title[FIELD_MAX], artist[FIELD_MAX], album[FIELD_MAX], genre[FIELD_MAX];
        long long length_us;
        int track;
    } was;
    memcpy(was.title, rec.title, sizeof was.title);
    memcpy(was.artist, rec.artist, sizeof was.artist);
    memcpy(was.album, rec.album, sizeof was.album);
    memcpy(was.genre, rec.genre, sizeof was.genre);
    was.length_us = rec.length_us;
    was.track = rec.track;
    if (!bm_parse(text)) {
        say(L_RECORD, "record %s not understood (%ld bytes)", record_path, n);
        return 0;
    }
    rec_read_at = now_ms();
    /* The producer restarts its generation after demo/Rockbox restarts. Complete text
     * was already deduplicated above; an equal generation can still carry a new track. */
    int same = !strcmp(was.title, rec.title) && !strcmp(was.artist, rec.artist) &&
               !strcmp(was.album, rec.album) && !strcmp(was.genre, rec.genre) &&
               was.length_us == rec.length_us && was.track == rec.track; /* field by field */
    return !same || !before ? 2 : 1; /* 2: the track changed; 1: status or position */
}

/* D-Bus marshalling of the player's properties. */
static void append_variant_string(DBusMessageIter *dict, const char *key, const char *value) {
    DBusMessageIter entry, variant;
    dbus_message_iter_open_container(dict, DBUS_TYPE_DICT_ENTRY, 0, &entry);
    dbus_message_iter_append_basic(&entry, DBUS_TYPE_STRING, &key);
    dbus_message_iter_open_container(&entry, DBUS_TYPE_VARIANT, "s", &variant);
    dbus_message_iter_append_basic(&variant, DBUS_TYPE_STRING, &value);
    dbus_message_iter_close_container(&entry, &variant);
    dbus_message_iter_close_container(dict, &entry);
}
static void append_variant_int64(DBusMessageIter *dict, const char *key, long long value) {
    DBusMessageIter entry, variant;
    dbus_int64_t v = value;
    dbus_message_iter_open_container(dict, DBUS_TYPE_DICT_ENTRY, 0, &entry);
    dbus_message_iter_append_basic(&entry, DBUS_TYPE_STRING, &key);
    dbus_message_iter_open_container(&entry, DBUS_TYPE_VARIANT, "x", &variant);
    dbus_message_iter_append_basic(&variant, DBUS_TYPE_INT64, &v);
    dbus_message_iter_close_container(&entry, &variant);
    dbus_message_iter_close_container(dict, &entry);
}
static void append_variant_int32(DBusMessageIter *dict, const char *key, int value) {
    DBusMessageIter entry, variant;
    dbus_int32_t v = value;
    dbus_message_iter_open_container(dict, DBUS_TYPE_DICT_ENTRY, 0, &entry);
    dbus_message_iter_append_basic(&entry, DBUS_TYPE_STRING, &key);
    dbus_message_iter_open_container(&entry, DBUS_TYPE_VARIANT, "i", &variant);
    dbus_message_iter_append_basic(&variant, DBUS_TYPE_INT32, &v);
    dbus_message_iter_close_container(&entry, &variant);
    dbus_message_iter_close_container(dict, &entry);
}
static void append_variant_strings(DBusMessageIter *dict, const char *key, const char *value) {
    DBusMessageIter entry, variant, array;
    dbus_message_iter_open_container(dict, DBUS_TYPE_DICT_ENTRY, 0, &entry);
    dbus_message_iter_append_basic(&entry, DBUS_TYPE_STRING, &key);
    dbus_message_iter_open_container(&entry, DBUS_TYPE_VARIANT, "as", &variant);
    dbus_message_iter_open_container(&variant, DBUS_TYPE_ARRAY, "s", &array);
    dbus_message_iter_append_basic(&array, DBUS_TYPE_STRING, &value);
    dbus_message_iter_close_container(&variant, &array);
    dbus_message_iter_close_container(&entry, &variant);
    dbus_message_iter_close_container(dict, &entry);
}
/* Metadata as media.c reads it: a{sv} with the xesam/mpris keys. */
static void append_metadata(DBusMessageIter *dict) {
    DBusMessageIter entry, variant, inner;
    const char *key = "Metadata", *id = "/q2pod/track";
    dbus_message_iter_open_container(dict, DBUS_TYPE_DICT_ENTRY, 0, &entry);
    dbus_message_iter_append_basic(&entry, DBUS_TYPE_STRING, &key);
    dbus_message_iter_open_container(&entry, DBUS_TYPE_VARIANT, "a{sv}", &variant);
    dbus_message_iter_open_container(&variant, DBUS_TYPE_ARRAY, "{sv}", &inner);
    {
        DBusMessageIter e, v;
        const char *k = "mpris:trackid";
        dbus_message_iter_open_container(&inner, DBUS_TYPE_DICT_ENTRY, 0, &e);
        dbus_message_iter_append_basic(&e, DBUS_TYPE_STRING, &k);
        dbus_message_iter_open_container(&e, DBUS_TYPE_VARIANT, "o", &v);
        dbus_message_iter_append_basic(&v, DBUS_TYPE_OBJECT_PATH, &id);
        dbus_message_iter_close_container(&e, &v);
        dbus_message_iter_close_container(&inner, &e);
    }
    append_variant_string(&inner, "xesam:title", rec.title);
    append_variant_strings(&inner, "xesam:artist", rec.artist);
    append_variant_string(&inner, "xesam:album", rec.album);
    append_variant_strings(&inner, "xesam:genre", rec.genre);
    append_variant_int64(&inner, "mpris:length", rec.length_us);
    append_variant_int32(&inner, "xesam:trackNumber", rec.track);
    dbus_message_iter_close_container(&variant, &inner);
    dbus_message_iter_close_container(&entry, &variant);
    dbus_message_iter_close_container(dict, &entry);
}
/* The properties, for RegisterPlayer, GetAll and the changed signal. media.c parses a dict in
 * order, and its Metadata parser resets the position to 0, so Metadata comes before Position; a
 * change of status or position alone carries no Metadata (that would re-announce the track).
 * No CanControl, CanPlay, CanPause, CanGoNext or CanGoPrevious: media.c then declines the car's
 * keys (returns false) and avctp passes them to uinput, as it does today. */
static void append_properties(DBusMessageIter *dict, int with_metadata) {
    append_variant_string(dict, "Identity", "Q2 Pod");
    if (with_metadata) append_metadata(dict);
    append_variant_string(dict, "PlaybackStatus", rec.status);
    append_variant_string(dict, "LoopStatus", "None");
    append_variant_int64(dict, "Position", position_now());
}

static DBusConnection *conn;

static void bm_changed(int track_changed);
static int bm_register(void) {
    if (registered || disabled) return 0;
    DBusMessage *m =
        dbus_message_new_method_call(bluez_name, adapter_path, MEDIA_IFACE, "RegisterPlayer");
    if (!m) return 0;
    DBusMessageIter args, dict;
    const char *path = PLAYER_PATH;
    dbus_message_iter_init_append(m, &args);
    dbus_message_iter_append_basic(&args, DBUS_TYPE_OBJECT_PATH, &path);
    dbus_message_iter_open_container(&args, DBUS_TYPE_ARRAY, "{sv}", &dict);
    append_properties(&dict, 1);
    dbus_message_iter_close_container(&args, &dict);
    DBusError err;
    dbus_error_init(&err);
    DBusMessage *reply = dbus_connection_send_with_reply_and_block(conn, m, 2000, &err);
    dbus_message_unref(m);
    if (!reply) {
        /* The pinned Media1 keys this error by adapter + our unique bus sender
         * + PLAYER_PATH. A delayed owner-up may have cleared local success after
         * that same daemon registered us. Its error did not parse these properties. */
        if (dbus_error_has_name(&err, "org.bluez.Error.AlreadyExists")) {
            dbus_error_free(&err);
            registered = 1;
            say(L_REG, "reconciled existing " PLAYER_PATH " with %s (%ld)", bluez_name,
                (long)rec.generation);
            bm_changed(1); /* Send the full current record, which the error did not carry. */
            return 1;
        }
        say(L_REG, "RegisterPlayer failed: %s", dbus_error_is_set(&err) ? err.name : "no reply", 0);
        dbus_error_free(&err);
        return 0;
    }
    dbus_message_unref(reply);
    registered = 1;
    say(L_REG, "registered " PLAYER_PATH " with %s (%ld)", bluez_name, (long)rec.generation);
    return 1;
}
static void bm_unregister(void) {
    if (!registered) return;
    registered = 0;
    DBusMessage *m =
        dbus_message_new_method_call(bluez_name, adapter_path, MEDIA_IFACE, "UnregisterPlayer");
    if (!m) return;
    const char *path = PLAYER_PATH;
    dbus_message_append_args(m, DBUS_TYPE_OBJECT_PATH, &path, DBUS_TYPE_INVALID);
    dbus_message_set_no_reply(m, TRUE);
    dbus_connection_send(conn, m, 0);
    dbus_message_unref(m);
    say(L_UNREG, "unregistered %s", PLAYER_PATH, 0);
}
/* PropertiesChanged(interface, changed a{sv}, invalidated as): the track's properties when the
 * track changed, else the status and position alone. */
static void bm_changed(int track_changed) {
    if (!registered) return;
    DBusMessage *s =
        dbus_message_new_signal(PLAYER_PATH, DBUS_INTERFACE_PROPERTIES, "PropertiesChanged");
    if (!s) return;
    DBusMessageIter args, dict, invalidated;
    const char *iface = PLAYER_IFACE;
    dbus_message_iter_init_append(s, &args);
    dbus_message_iter_append_basic(&args, DBUS_TYPE_STRING, &iface);
    dbus_message_iter_open_container(&args, DBUS_TYPE_ARRAY, "{sv}", &dict);
    append_properties(&dict, track_changed);
    dbus_message_iter_close_container(&args, &dict);
    dbus_message_iter_open_container(&args, DBUS_TYPE_ARRAY, "s", &invalidated);
    dbus_message_iter_close_container(&args, &invalidated);
    int queued = dbus_connection_send(conn, s, 0);
    dbus_message_unref(s);
    say(L_SIGNAL,
        queued ? (track_changed ? "queued track, %s gen %ld" : "queued %s gen %ld")
               : "QUEUE FAILED %s gen %ld",
        rec.status, (long)rec.generation);
}

/* The player object: introspection, property reads, and a refusal of every control. */
static const char introspection[] =
    "<!DOCTYPE node PUBLIC \"-//freedesktop//DTD D-BUS Object Introspection 1.0//EN\" "
    "\"http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd\">\n"
    "<node><interface name=\"org.freedesktop.DBus.Introspectable\"><method name=\"Introspect\">"
    "<arg name=\"xml\" type=\"s\" direction=\"out\"/></method></interface>"
    "<interface name=\"org.freedesktop.DBus.Properties\">"
    "<method name=\"Get\"><arg type=\"s\" direction=\"in\"/><arg type=\"s\" direction=\"in\"/><arg "
    "type=\"v\" direction=\"out\"/></method>"
    "<method name=\"GetAll\"><arg type=\"s\" direction=\"in\"/><arg type=\"a{sv}\" "
    "direction=\"out\"/></method>"
    "<signal name=\"PropertiesChanged\"><arg type=\"s\"/><arg type=\"a{sv}\"/><arg "
    "type=\"as\"/></signal></interface>"
    "<interface name=\"" PLAYER_IFACE "\">"
    "<property name=\"Identity\" type=\"s\" access=\"read\"/><property name=\"PlaybackStatus\" "
    "type=\"s\" access=\"read\"/>"
    "<property name=\"LoopStatus\" type=\"s\" access=\"read\"/><property name=\"Position\" "
    "type=\"x\" access=\"read\"/>"
    "<property name=\"Metadata\" type=\"a{sv}\" access=\"read\"/>"
    "<method name=\"Play\"/><method name=\"Pause\"/><method name=\"Stop\"/><method "
    "name=\"Next\"/><method name=\"Previous\"/>"
    "<method name=\"Release\"/></interface></node>\n";

static DBusHandlerResult reply_error(DBusConnection *c, DBusMessage *m, const char *name,
                                     const char *text) {
    DBusMessage *r = dbus_message_new_error(m, name, text);
    if (r) {
        dbus_connection_send(c, r, 0);
        dbus_message_unref(r);
    }
    return DBUS_HANDLER_RESULT_HANDLED;
}
static DBusHandlerResult on_message(DBusConnection *c, DBusMessage *m, void *user) {
    (void)user;
    say(L_CALL, "call on %s (%ld)",
        dbus_message_get_interface(m) ? dbus_message_get_interface(m) : "?",
        (long)dbus_message_get_type(m));
    if (dbus_message_is_method_call(m, DBUS_INTERFACE_INTROSPECTABLE, "Introspect")) {
        DBusMessage *r = dbus_message_new_method_return(m);
        const char *xml = introspection;
        if (r) {
            dbus_message_append_args(r, DBUS_TYPE_STRING, &xml, DBUS_TYPE_INVALID);
            dbus_connection_send(c, r, 0);
            dbus_message_unref(r);
        }
        return DBUS_HANDLER_RESULT_HANDLED;
    }
    if (dbus_message_is_method_call(m, DBUS_INTERFACE_PROPERTIES, "GetAll")) {
        DBusMessage *r = dbus_message_new_method_return(m);
        if (r) {
            DBusMessageIter args, dict;
            dbus_message_iter_init_append(r, &args);
            dbus_message_iter_open_container(&args, DBUS_TYPE_ARRAY, "{sv}", &dict);
            append_properties(&dict, 1);
            dbus_message_iter_close_container(&args, &dict);
            dbus_connection_send(c, r, 0);
            dbus_message_unref(r);
        }
        return DBUS_HANDLER_RESULT_HANDLED;
    }
    if (dbus_message_is_method_call(m, DBUS_INTERFACE_PROPERTIES, "Get")) {
        const char *iface = 0, *name = 0;
        if (!dbus_message_get_args(m, 0, DBUS_TYPE_STRING, &iface, DBUS_TYPE_STRING, &name,
                                   DBUS_TYPE_INVALID))
            return reply_error(c, m, DBUS_ERROR_INVALID_ARGS, "interface and property");
        DBusMessage *r = dbus_message_new_method_return(m);
        if (!r) return DBUS_HANDLER_RESULT_HANDLED;
        DBusMessageIter args, variant;
        dbus_message_iter_init_append(r, &args);
        if (!strcmp(name, "PlaybackStatus") || !strcmp(name, "Identity") ||
            !strcmp(name, "LoopStatus")) {
            const char *v = !strcmp(name, "PlaybackStatus") ? rec.status
                            : !strcmp(name, "Identity")     ? "Q2 Pod"
                                                            : "None";
            dbus_message_iter_open_container(&args, DBUS_TYPE_VARIANT, "s", &variant);
            dbus_message_iter_append_basic(&variant, DBUS_TYPE_STRING, &v);
            dbus_message_iter_close_container(&args, &variant);
        } else if (!strcmp(name, "Position")) {
            dbus_int64_t v = position_now();
            dbus_message_iter_open_container(&args, DBUS_TYPE_VARIANT, "x", &variant);
            dbus_message_iter_append_basic(&variant, DBUS_TYPE_INT64, &v);
            dbus_message_iter_close_container(&args, &variant);
        } else if (!strcmp(name, "Metadata")) {
            DBusMessageIter dict; /* append_metadata writes a dict entry; wrap its value alone */
            dbus_message_iter_open_container(&args, DBUS_TYPE_VARIANT, "a{sv}", &variant);
            dbus_message_iter_open_container(&variant, DBUS_TYPE_ARRAY, "{sv}", &dict);
            append_variant_string(&dict, "xesam:title", rec.title);
            append_variant_strings(&dict, "xesam:artist", rec.artist);
            append_variant_string(&dict, "xesam:album", rec.album);
            append_variant_strings(&dict, "xesam:genre", rec.genre);
            append_variant_int64(&dict, "mpris:length", rec.length_us);
            append_variant_int32(&dict, "xesam:trackNumber", rec.track);
            dbus_message_iter_close_container(&variant, &dict);
            dbus_message_iter_close_container(&args, &variant);
        } else {
            dbus_message_unref(r);
            return reply_error(c, m, DBUS_ERROR_UNKNOWN_PROPERTY, name);
        }
        dbus_connection_send(c, r, 0);
        dbus_message_unref(r);
        return DBUS_HANDLER_RESULT_HANDLED;
    }
    if (dbus_message_is_method_call(m, PLAYER_IFACE, "Release")) {
        DBusMessage *r = dbus_message_new_method_return(m);
        if (r) {
            dbus_connection_send(c, r, 0);
            dbus_message_unref(r);
        }
        registered = 0; /* bluetoothd let go of the player: register again when it is back */
        return DBUS_HANDLER_RESULT_HANDLED;
    }
    if (dbus_message_has_interface(m, PLAYER_IFACE) &&
        dbus_message_get_type(m) == DBUS_MESSAGE_TYPE_METHOD_CALL)
        return reply_error(c, m, DBUS_ERROR_NOT_SUPPORTED, "the Q2's keys arrive another way");
    return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
}
static const DBusObjectPathVTable vtable = { 0, on_message, 0, 0, 0, 0 };

/* org.bluez coming and going: bluetoothd restarts at every Bluetooth off/on. */
static DBusHandlerResult on_signal(DBusConnection *c, DBusMessage *m, void *user) {
    (void)c;
    (void)user;
    if (!dbus_message_is_signal(m, DBUS_INTERFACE_DBUS, "NameOwnerChanged") ||
        !dbus_message_has_sender(m, DBUS_SERVICE_DBUS))
        return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
    const char *name = 0, *old = 0, *new = 0;
    if (!dbus_message_get_args(m, 0, DBUS_TYPE_STRING, &name, DBUS_TYPE_STRING, &old,
                               DBUS_TYPE_STRING, &new, DBUS_TYPE_INVALID))
        return DBUS_HANDLER_RESULT_HANDLED;
    if (strcmp(name, bluez_name)) return DBUS_HANDLER_RESULT_HANDLED;
    say(L_OWNER, "%s owner changed (%ld: 1 up, 0 gone)", name, (long)(*new != 0));
    registered = 0; /* whatever was registered went with the old bluetoothd */
    if (*new) bm_register();
    return DBUS_HANDLER_RESULT_HANDLED;
}

static int bluez_present(void) {
    DBusMessage *m = dbus_message_new_method_call(DBUS_SERVICE_DBUS, DBUS_PATH_DBUS,
                                                  DBUS_INTERFACE_DBUS, "NameHasOwner");
    if (!m) return 0;
    dbus_message_append_args(m, DBUS_TYPE_STRING, &bluez_name, DBUS_TYPE_INVALID);
    DBusMessage *r = dbus_connection_send_with_reply_and_block(conn, m, 2000, 0);
    dbus_message_unref(m);
    if (!r) return 0;
    dbus_bool_t has = FALSE;
    dbus_message_get_args(r, 0, DBUS_TYPE_BOOLEAN, &has, DBUS_TYPE_INVALID);
    dbus_message_unref(r);
    return has;
}

static int bm_connect(void) {
    DBusError err;
    dbus_error_init(&err);
    conn = dbus_bus_get_private(bus_type, &err);
    if (!conn) {
        say(L_BUS, "no bus: %s", dbus_error_is_set(&err) ? err.message : "?", 0);
        dbus_error_free(&err);
        return 0;
    }
    dbus_connection_set_exit_on_disconnect(conn, FALSE);
    if (!dbus_connection_register_object_path(conn, PLAYER_PATH, &vtable, 0)) {
        say(L_BUS, "cannot register %s", PLAYER_PATH, 0);
        dbus_connection_close(conn);
        dbus_connection_unref(conn);
        conn = 0;
        return 0;
    }
    char rule[256];
    snprintf(rule, sizeof rule,
             "type='signal',sender='" DBUS_SERVICE_DBUS "',interface='" DBUS_INTERFACE_DBUS
             "',member='NameOwnerChanged',arg0='%s'",
             bluez_name);
    dbus_bus_add_match(conn, rule, 0);
    dbus_connection_add_filter(conn, on_signal, 0, 0);
    if (disabled) say(L_OFF, "off: %s exists", off_path, 0);
    if (bluez_present()) bm_register();
    return 1;
}

int main(int argc, char **argv) {
    /* Test hooks (test/mpris.py): a session bus and a fake org.bluez under other names and paths.
     */
    for (int i = 1; i + 1 < argc; i += 2) {
        if (!strcmp(argv[i], "--session")) {
            bus_type = DBUS_BUS_SESSION;
            i--;
        } else if (!strcmp(argv[i], "--record"))
            record_path = argv[i + 1];
        else if (!strcmp(argv[i], "--off"))
            off_path = argv[i + 1];
        else if (!strcmp(argv[i], "--bluez"))
            bluez_name = argv[i + 1];
        else if (!strcmp(argv[i], "--adapter"))
            adapter_path = argv[i + 1];
    }
    if (argc > 1 && !strcmp(argv[argc - 1], "--session")) bus_type = DBUS_BUS_SESSION;
    disabled = !access(off_path, F_OK);
    bm_read();
    long long retry_at = 0;
    unsigned tick = 0;
    for (;;) {
        if (!conn) {
            if (now_ms() >= retry_at) {
                retry_at = now_ms() + 2000;
                bm_connect();
            }
            usleep(POLL_MS * 1000);
            continue;
        }
        if (!dbus_connection_read_write_dispatch(conn, POLL_MS)) {
            say(L_BUS, "bus gone; retrying", "", 0);
            dbus_connection_close(conn);
            dbus_connection_unref(conn);
            conn = 0;
            registered = 0;
            continue;
        }
        int off = !access(off_path, F_OK);
        if (off != disabled) {
            disabled = off;
            say(L_OFF, "%s",
                off ? "off: the card's q2pod-btmeta-off appeared" : "on: q2pod-btmeta-off gone", 0);
            if (off)
                bm_unregister();
            else if (bluez_present())
                bm_register();
        }
        int changed = bm_read();
        if (!registered && !disabled && ++tick % 8 == 0 &&
            bluez_present())                /* every 2 s while nobody owns org.bluez */
            if (bm_register()) changed = 0; /* RegisterPlayer carried the record */
        if (changed) bm_changed(changed == 2);
    }
}
