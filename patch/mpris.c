/* q2mpris: the Q2's now-playing track, published to bluetoothd as a media player.
 *
 * The standard BlueZ player store needs this publisher for AVRCP track information.
 * No transport-control flags are advertised: stock keeps its existing key route.
 *
 *   - The payload (patch/btmeta.c) writes RECORD_PATH in RAM, whole and renamed into place, when
 *     the track, play status or position (a seek) changes: "key=value" lines, see bm_parse.
 *   - A directory notification wakes this helper, which sends org.freedesktop.DBus.Properties
 *     .PropertiesChanged for org.mpris.MediaPlayer2.Player, which media.c parses (Metadata:
 *     xesam:title, xesam:artist, xesam:album, xesam:genre, mpris:length; PlaybackStatus; Position).
 *   - It registers whenever org.bluez appears (stock kills and restarts bluetoothd at every
 *     Bluetooth off/on). It blocks on notifications and libdbus watches/timeouts while healthy.
 *
 * Plain libdbus, no GLib or helper threads. Text buffers are fixed. Built by tools/build.py
 * against the stock rootfs's libdbus-1. */
#include <dbus/dbus.h>
#ifdef __mips__ /* the Q2 build: the host's libc headers are x86's, so libc is declared here (as   \
                   video.c) */
int open(const char *, int, ...), close(int), read(int, void *, unsigned);
int inotify_init1(int), inotify_add_watch(int, const char *, unsigned);
int *__errno_location(void);
#define errno (*__errno_location())
struct bm_pollfd {
    int fd;
    short events, revents;
};
int poll(struct bm_pollfd *, unsigned long, int);
int clock_gettime(int, void *);
void _exit(int) __attribute__((noreturn));
struct bm_timespec {
    long sec, nsec;
}; /* o32 glibc 2.28's timespec: two 32-bit words */
#define BM_CLOCK(ts) clock_gettime(1 /* CLOCK_MONOTONIC */, (ts))
unsigned strlen(const char *);
char *strchr(const char *, int);
int strcmp(const char *, const char *), memcmp(const void *, const void *, unsigned);
void *memcpy(void *, const void *, unsigned);
void *memchr(const void *, int, unsigned);

#define O_RDONLY 0
#define O_CLOEXEC 0x80000  /* MIPS */
#define O_NONBLOCK 0x80    /* MIPS */
#define O_NOFOLLOW 0x20000 /* MIPS */
#define POLLIN 1
#define POLLOUT 4
#define POLLERR 8
#define POLLHUP 16
#define POLLNVAL 32
#define EINTR 4
#define EAGAIN 11
#define ENOSYS 89 /* MIPS */
#define EINVAL 22
#define EACCES 13
#define EPERM 1
#else
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <errno.h>
#include <poll.h>
#include <sys/inotify.h>
#define bm_pollfd pollfd
struct bm_timespec {
    long sec, nsec;
}; /* the host's timespec is two 64-bit words: the same layout */
#define BM_CLOCK(ts) clock_gettime(CLOCK_MONOTONIC, (struct timespec *)(ts))
#endif

/* An OOM in a writer invalidates its subiterator. Do not continue assembling a partial
 * message, or silently consume the only snapshot event: restart through the supervisor. */
static dbus_bool_t message_space(dbus_bool_t ok) {
    if (!ok) _exit(1);
    return ok;
}
static DBusMessage *message_new(DBusMessage *message) {
    if (!message) _exit(1);
    return message;
}
#define dbus_message_iter_open_container(...)                                                      \
    message_space(dbus_message_iter_open_container(__VA_ARGS__))
#define dbus_message_iter_append_basic(...)                                                        \
    message_space(dbus_message_iter_append_basic(__VA_ARGS__))
#define dbus_message_iter_close_container(...)                                                     \
    message_space(dbus_message_iter_close_container(__VA_ARGS__))
#define dbus_message_append_args(...) message_space(dbus_message_append_args(__VA_ARGS__))
#define dbus_connection_send(...) message_space(dbus_connection_send(__VA_ARGS__))
#define dbus_message_new_method_call(...) message_new(dbus_message_new_method_call(__VA_ARGS__))
#define dbus_message_new_method_return(...) message_new(dbus_message_new_method_return(__VA_ARGS__))
#define dbus_message_new_error(...) message_new(dbus_message_new_error(__VA_ARGS__))
#define dbus_message_new_signal(...) message_new(dbus_message_new_signal(__VA_ARGS__))

#define RECORD_PATH "/tmp/q2-bt/nowplaying"
#define PLAYER_PATH "/q2pod/player"
#define PLAYER_IFACE "org.mpris.MediaPlayer2.Player"
#define BLUEZ "org.bluez"
#define ADAPTER "/org/bluez/hci0"
#define MEDIA_IFACE "org.bluez.Media1"
#define RETRY_MS 2000
#define RECORD_MAX 2048
#define FIELD_MAX 256

static const char *record_path = RECORD_PATH, *record_dir = "/tmp/q2-bt",
                  *record_leaf = "nowplaying", *bluez_name = BLUEZ, *adapter_path = ADAPTER;
static DBusBusType bus_type = DBUS_BUS_SYSTEM;

/* The record as last read: strings and numbers the signals and property replies are built from. */
static struct {
    char status[16], title[FIELD_MAX], artist[FIELD_MAX], album[FIELD_MAX], genre[FIELD_MAX];
    long long length_us, position_us; /* mpris:length and Position */
    long long written_ms; /* the payload's CLOCK_MONOTONIC when it wrote the record, -1 if absent */
    int track, tracks;
    unsigned generation; /* the payload's counter, so an unchanged file is not re-sent */
} rec = { "Stopped", "", "", "", "", 0, 0, -1, 0, 0, 0 };
static int registered, bluez_up, register_tries;
static long long register_retry_at;

/* "key=value" lines, each once, unknown keys ignored, values cut to their field, and made valid
 * UTF-8 (libdbus refuses, or aborts on, an invalid string): a bad or torn sequence becomes '?'. */
static void bm_field(char *out, unsigned size, const char *value) {
    unsigned n = 0, o = 0;
    while (value[n] && value[n] != '\n' && value[n] != '\r') n++;
    for (unsigned i = 0; i < n && o < size - 1;) {
        unsigned char first = (unsigned char)value[i];
        unsigned len = first < 0x80 ? 1 : first < 0xe0 ? 2 : first < 0xf0 ? 3 : 4;
        char sequence[5] = { 0 };
        if (len <= n - i) memcpy(sequence, value + i, len);
        if (len > n - i || (first >= 0x80 && !dbus_validate_utf8(sequence, 0))) {
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
    typeof(rec) next = { .written_ms = -1 };
    char *fields[] = { next.status, next.title, next.artist, next.album, next.genre };
    static const char *const keys[] = {
        "status", "title",    "artist",   "album", "genre",  "v",
        "gen",    "duration", "position", "track", "tracks", "now"
    };
    long long numbers[7] = { 0, 0, 0, 0, 0, 0, -1 };
    static const unsigned limits[] = { 1,           0xffffffffu, 1000000000, 1000000000,
                                       0x7fffffffu, 0x7fffffffu, 0xffffffffu };
    unsigned seen = 0;
    for (const char *line = text; *line;) {
        const char *end = strchr(line, '\n'), *eq = strchr(line, '=');
        if (!end) return 0; /* publication always ends every line, including the generation */
        if (eq && eq < end) {
            for (unsigned i = 0; i < sizeof keys / sizeof *keys; i++) {
                unsigned len = strlen(keys[i]);
                if ((unsigned)(eq - line) != len || memcmp(line, keys[i], len)) continue;
                if (seen & (1u << i)) return 0;
                seen |= 1u << i;
                if (i < 5)
                    bm_field(fields[i], i ? FIELD_MAX : sizeof next.status, eq + 1);
                else {
                    long long n = 0;
                    if (eq + 1 == end) return 0;
                    for (const char *v = eq + 1; v < end; v++) {
                        if (*v < '0' || *v > '9') return 0;
                        n = n * 10 + (*v - '0');
                        if (n > limits[i - 5]) return 0;
                    }
                    numbers[i - 5] = n;
                }
                break;
            }
        }
        line = end + 1;
    }
    enum {
        HAVE_STATUS = 1u << 0,
        HAVE_VERSION = 1u << 5,
        HAVE_GENERATION = 1u << 6,
        HAVE_POSITION = 1u << 8
    };
    unsigned required = HAVE_STATUS | HAVE_VERSION | HAVE_GENERATION | HAVE_POSITION;
    if ((seen & required) != required || numbers[0] != 1 || !numbers[1]) return 0;
    if (strcmp(next.status, "Playing") && strcmp(next.status, "Paused") &&
        strcmp(next.status, "Stopped"))
        return 0;
    next.generation = (unsigned)numbers[1];
    next.length_us = numbers[2] * 1000;
    next.position_us = numbers[3] * 1000;
    next.track = (int)numbers[4];
    next.tracks = (int)numbers[5];
    next.written_ms = numbers[6];
    rec = next; /* Commit only a complete, validated record. */
    return 1;
}

/* The position now: the record's, plus the time since it was read while playing (media.c keeps
 * the same clock, but a registration after a bluetoothd restart starts from a record that may be
 * minutes old). */
static long long now_ms(void) {
    struct bm_timespec ts;
    /* Deadlines cannot progress without this clock. Exit rather than spin or
     * stop polling; the existing supervisor waits five seconds before retry. */
    if (BM_CLOCK(&ts) || ts.sec < 0 || ts.nsec < 0 || ts.nsec >= 1000000000) _exit(1);
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
    int fd;
    do fd = open(record_path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    while (fd < 0 && errno == EINTR);
    if (fd < 0) return 0;
    char text[RECORD_MAX + 1];
    int n = 0, bytes;
    while (n < RECORD_MAX) {
        bytes = read(fd, text + n, RECORD_MAX - (unsigned)n);
        if (bytes < 0 && errno == EINTR) continue;
        if (bytes < 0) {
            close(fd);
            _exit(1);
        }
        if (!bytes) break;
        n += bytes;
    }
    close(fd);
    if (n <= 0 || n >= RECORD_MAX || memchr(text, 0, (unsigned)n)) return 0;
    text[n] = 0;
    if (!strcmp(text, last)) return 0;
    typeof(rec) was = rec;
    if (!bm_parse(text)) return 0;
    memcpy(last, text, (unsigned)n + 1);
    rec_read_at = now_ms();
    /* Generation can repeat after demo restarts; compare the complete metadata. */
    int same = !strcmp(was.title, rec.title) && !strcmp(was.artist, rec.artist) &&
               !strcmp(was.album, rec.album) && !strcmp(was.genre, rec.genre) &&
               was.length_us == rec.length_us && was.track == rec.track;
    return !same || !was.generation ? 2 : 1; /* 2: metadata; 1: status/position */
}

/* The same value writer serves Get, GetAll, registration and change signals. */
static void append_metadata_value(DBusMessageIter *dict);
static void append_variant(DBusMessageIter *iter, const char *signature, const void *value) {
    DBusMessageIter variant, array;
    dbus_message_iter_open_container(iter, DBUS_TYPE_VARIANT, signature, &variant);
    if (!strcmp(signature, "a{sv}")) {
        dbus_message_iter_open_container(&variant, DBUS_TYPE_ARRAY, "{sv}", &array);
        append_metadata_value(&array);
        dbus_message_iter_close_container(&variant, &array);
    } else if (!strcmp(signature, "as")) {
        dbus_message_iter_open_container(&variant, DBUS_TYPE_ARRAY, "s", &array);
        dbus_message_iter_append_basic(&array, DBUS_TYPE_STRING, value);
        dbus_message_iter_close_container(&variant, &array);
    } else
        dbus_message_iter_append_basic(&variant, signature[0], value);
    dbus_message_iter_close_container(iter, &variant);
}
static void append_entry(DBusMessageIter *dict, const char *key, const char *signature,
                         const void *value) {
    DBusMessageIter entry;
    dbus_message_iter_open_container(dict, DBUS_TYPE_DICT_ENTRY, 0, &entry);
    dbus_message_iter_append_basic(&entry, DBUS_TYPE_STRING, &key);
    append_variant(&entry, signature, value);
    dbus_message_iter_close_container(dict, &entry);
}
static void append_metadata_value(DBusMessageIter *dict) {
    const char *strings[] = { "/q2pod/track", rec.title, rec.artist, rec.album, rec.genre };
    static const char *const keys[] = { "mpris:trackid", "xesam:title", "xesam:artist",
                                        "xesam:album", "xesam:genre" };
    static const char *const types[] = { "o", "s", "as", "s", "as" };
    for (unsigned i = 0; i < sizeof keys / sizeof *keys; i++)
        append_entry(dict, keys[i], types[i], &strings[i]);
    dbus_int64_t length = rec.length_us;
    dbus_int32_t track = rec.track;
    append_entry(dict, "mpris:length", "x", &length);
    append_entry(dict, "xesam:trackNumber", "i", &track);
}
/* BlueZ resets position when Metadata arrives, so it must precede Position.
 * No CanControl/CanPlay/etc: stock's existing uinput button route stays in charge. */
static const char *const property_names[] = { "Identity", "Metadata", "PlaybackStatus",
                                              "LoopStatus", "Position" };
static void append_property(DBusMessageIter *iter, unsigned property, int entry) {
    const char *text = property == 0 ? "Q2 Pod" : property == 2 ? rec.status : "None";
    dbus_int64_t position = property == 4 ? position_now() : 0;
    const char *type = property == 1 ? "a{sv}" : property == 4 ? "x" : "s";
    const void *value = property == 4 ? (const void *)&position : (const void *)&text;
    if (entry)
        append_entry(iter, property_names[property], type, value);
    else
        append_variant(iter, type, value);
}
static void append_properties(DBusMessageIter *dict, int with_metadata) {
    for (unsigned i = 0; i < sizeof property_names / sizeof *property_names; i++)
        if (i != 1 || with_metadata) append_property(dict, i, 1);
}

static DBusConnection *conn;

static void bm_changed(int track_changed);
static int bm_register_attempt(void) {
    if (registered) return 0;
    bm_read(); /* Recovery registration must carry the latest snapshot, even while paused. */
    if (!rec.generation) {
        register_tries = 0; /* No valid snapshot yet: wait for a record/owner/interface event. */
        return 0;
    }
    DBusMessage *m =
        dbus_message_new_method_call(bluez_name, adapter_path, MEDIA_IFACE, "RegisterPlayer");
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
            bm_changed(1); /* Send the full current record, which the error did not carry. */
            return 1;
        }
        dbus_error_free(&err);
        return 0;
    }
    dbus_message_unref(reply);
    registered = 1;
    return 1;
}
static int bm_register(void) {
    int result = bm_register_attempt();
    register_retry_at = now_ms() + RETRY_MS; /* include a gap after a slow owner-event attempt */
    if (register_tries) register_tries--;
    if (registered) register_tries = 0;
    return result;
}
/* PropertiesChanged(interface, changed a{sv}, invalidated as): the track's properties when the
 * track changed, else the status and position alone. */
static void bm_changed(int track_changed) {
    if (!registered) return;
    DBusMessage *s =
        dbus_message_new_signal(PLAYER_PATH, DBUS_INTERFACE_PROPERTIES, "PropertiesChanged");
    DBusMessageIter args, dict, invalidated;
    const char *iface = PLAYER_IFACE;
    dbus_message_iter_init_append(s, &args);
    dbus_message_iter_append_basic(&args, DBUS_TYPE_STRING, &iface);
    dbus_message_iter_open_container(&args, DBUS_TYPE_ARRAY, "{sv}", &dict);
    append_properties(&dict, track_changed);
    dbus_message_iter_close_container(&args, &dict);
    dbus_message_iter_open_container(&args, DBUS_TYPE_ARRAY, "s", &invalidated);
    dbus_message_iter_close_container(&args, &invalidated);
    dbus_connection_send(conn, s, 0);
    dbus_message_unref(s);
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

static DBusHandlerResult send_reply(DBusConnection *c, DBusMessage *reply) {
    dbus_connection_send(c, reply, 0);
    dbus_message_unref(reply);
    return DBUS_HANDLER_RESULT_HANDLED;
}
static DBusHandlerResult reply_error(DBusConnection *c, DBusMessage *m, const char *name,
                                     const char *text) {
    return send_reply(c, dbus_message_new_error(m, name, text));
}
static DBusHandlerResult on_message(DBusConnection *c, DBusMessage *m, void *user) {
    (void)user;
    if (dbus_message_is_method_call(m, DBUS_INTERFACE_INTROSPECTABLE, "Introspect")) {
        if (!dbus_message_has_signature(m, ""))
            return reply_error(c, m, DBUS_ERROR_INVALID_ARGS, "no arguments");
        DBusMessage *reply = dbus_message_new_method_return(m);
        const char *xml = introspection;
        dbus_message_append_args(reply, DBUS_TYPE_STRING, &xml, DBUS_TYPE_INVALID);
        return send_reply(c, reply);
    }
    int get = dbus_message_is_method_call(m, DBUS_INTERFACE_PROPERTIES, "Get");
    int all = dbus_message_is_method_call(m, DBUS_INTERFACE_PROPERTIES, "GetAll");
    if (get || all) {
        const char *iface = 0, *name = 0;
        if (!dbus_message_has_signature(m, get ? "ss" : "s") ||
            !(get ? dbus_message_get_args(m, 0, DBUS_TYPE_STRING, &iface, DBUS_TYPE_STRING, &name,
                                          DBUS_TYPE_INVALID)
                  : dbus_message_get_args(m, 0, DBUS_TYPE_STRING, &iface, DBUS_TYPE_INVALID)))
            return reply_error(c, m, DBUS_ERROR_INVALID_ARGS, "interface and property");
        if (strcmp(iface, PLAYER_IFACE))
            return reply_error(c, m, DBUS_ERROR_UNKNOWN_INTERFACE, iface);
        unsigned property = 0;
        if (get) {
            while (property < sizeof property_names / sizeof *property_names &&
                   strcmp(name, property_names[property]))
                property++;
            if (property == sizeof property_names / sizeof *property_names)
                return reply_error(c, m, DBUS_ERROR_UNKNOWN_PROPERTY, name);
        }
        DBusMessage *reply = dbus_message_new_method_return(m);
        DBusMessageIter args, dict;
        dbus_message_iter_init_append(reply, &args);
        if (get)
            append_property(&args, property, 0);
        else {
            dbus_message_iter_open_container(&args, DBUS_TYPE_ARRAY, "{sv}", &dict);
            append_properties(&dict, 1);
            dbus_message_iter_close_container(&args, &dict);
        }
        return send_reply(c, reply);
    }
    if (dbus_message_is_method_call(m, PLAYER_IFACE, "Release")) {
        if (!dbus_message_has_signature(m, ""))
            return reply_error(c, m, DBUS_ERROR_INVALID_ARGS, "no arguments");
        registered = 0;
        register_tries = 3;
        register_retry_at = now_ms();
        return send_reply(c, dbus_message_new_method_return(m));
    }
    if (dbus_message_has_interface(m, PLAYER_IFACE) &&
        dbus_message_get_type(m) == DBUS_MESSAGE_TYPE_METHOD_CALL)
        return reply_error(c, m, DBUS_ERROR_NOT_SUPPORTED, "the Q2's keys arrive another way");
    return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
}

static const DBusObjectPathVTable vtable = { 0, on_message, 0, 0, 0, 0 };

/* The helper has one notification source and libdbus's own watches/timeouts. Slots bound
 * memory; failure to install one is fatal rather than silently losing readiness. */
#define BUS_SLOTS 8
static DBusWatch *bus_watches[BUS_SLOTS];
static struct {
    DBusTimeout *timeout;
    long long at;
} bus_timeouts[BUS_SLOTS];
static dbus_bool_t add_watch(DBusWatch *watch, void *data) {
    (void)data;
    for (unsigned i = 0; i < BUS_SLOTS; i++)
        if (!bus_watches[i]) {
            bus_watches[i] = watch;
            return TRUE;
        }
    return FALSE;
}
static void remove_watch(DBusWatch *watch, void *data) {
    (void)data;
    for (unsigned i = 0; i < BUS_SLOTS; i++)
        if (bus_watches[i] == watch) bus_watches[i] = 0;
}
static dbus_bool_t add_timeout(DBusTimeout *timeout, void *data) {
    (void)data;
    for (unsigned i = 0; i < BUS_SLOTS; i++)
        if (!bus_timeouts[i].timeout) {
            bus_timeouts[i].timeout = timeout;
            bus_timeouts[i].at = now_ms() + dbus_timeout_get_interval(timeout);
            return TRUE;
        }
    return FALSE;
}
static void remove_timeout(DBusTimeout *timeout, void *data) {
    (void)data;
    for (unsigned i = 0; i < BUS_SLOTS; i++)
        if (bus_timeouts[i].timeout == timeout) bus_timeouts[i].timeout = 0;
}
static void toggle_timeout(DBusTimeout *timeout, void *data) {
    (void)data;
    for (unsigned i = 0; i < BUS_SLOTS; i++)
        if (bus_timeouts[i].timeout == timeout)
            bus_timeouts[i].at = now_ms() + dbus_timeout_get_interval(timeout);
}

/* Atomic rename changes the inode. Watch its directory before the initial read. */
#ifndef IN_CLOSE_WRITE
#define IN_CLOSE_WRITE 0x8
#define IN_MOVED_TO 0x80
#define IN_DELETE_SELF 0x400
#define IN_MOVE_SELF 0x800
#define IN_UNMOUNT 0x2000
#define IN_Q_OVERFLOW 0x4000
#define IN_IGNORED 0x8000
#endif
struct bm_event {
    int wd;
    unsigned mask, cookie, len;
    char name[];
};
static int notify_fd = -1;
/* Returns one resync per batch; invalidation exits for directory recreation by startup. */
static int notification_events(const char *buffer, unsigned bytes) {
    int changed = 0;
    for (unsigned at = 0; at + sizeof(struct bm_event) <= bytes;) {
        const struct bm_event *event = (const struct bm_event *)(buffer + at);
        if (event->len > bytes - at - sizeof *event) return -1;
        if (event->mask & (IN_DELETE_SELF | IN_MOVE_SELF | IN_UNMOUNT | IN_IGNORED)) return -1;
        if (event->mask & IN_Q_OVERFLOW) changed = 1;
        if (event->len && (event->mask & (IN_MOVED_TO | IN_CLOSE_WRITE))) {
            unsigned n = 0;
            while (n < event->len && event->name[n]) n++;
            if (n < event->len && n == strlen(record_leaf) && !memcmp(event->name, record_leaf, n))
                changed = 1;
        }
        at += sizeof *event + event->len;
    }
    return changed;
}
static int read_notifications(void) {
    union {
        unsigned alignment;
        char bytes[4096];
    } buffer;
    int changed = 0, n;
    while ((n = read(notify_fd, buffer.bytes, sizeof buffer.bytes)) > 0) {
        int result = notification_events(buffer.bytes, (unsigned)n);
        if (result < 0) _exit(1);
        changed |= result;
    }
    if (n < 0 && errno != EAGAIN && errno != EINTR) _exit(1);
    return changed;
}

/* org.bluez coming and going: bluetoothd restarts at every Bluetooth off/on. */
static int media_interface_signal(DBusMessage *m, int added) {
    DBusMessageIter args, interfaces;
    const char *path = 0;
    if (!dbus_message_iter_init(m, &args) ||
        dbus_message_iter_get_arg_type(&args) != DBUS_TYPE_OBJECT_PATH)
        return 0;
    dbus_message_iter_get_basic(&args, &path);
    if (strcmp(path, adapter_path) || !dbus_message_iter_next(&args) ||
        dbus_message_iter_get_arg_type(&args) != DBUS_TYPE_ARRAY)
        return 0;
    dbus_message_iter_recurse(&args, &interfaces);
    while (dbus_message_iter_get_arg_type(&interfaces) != DBUS_TYPE_INVALID) {
        DBusMessageIter item = interfaces;
        if (added) {
            if (dbus_message_iter_get_arg_type(&item) != DBUS_TYPE_DICT_ENTRY) return 0;
            dbus_message_iter_recurse(&interfaces, &item);
        }
        if (dbus_message_iter_get_arg_type(&item) != DBUS_TYPE_STRING) return 0;
        const char *name = 0;
        dbus_message_iter_get_basic(&item, &name);
        if (!strcmp(name, MEDIA_IFACE)) return 1;
        dbus_message_iter_next(&interfaces);
    }
    return 0;
}
static DBusHandlerResult on_signal(DBusConnection *c, DBusMessage *m, void *user) {
    (void)c;
    (void)user;
    int added = dbus_message_is_signal(m, "org.freedesktop.DBus.ObjectManager", "InterfacesAdded");
    int removed =
        dbus_message_is_signal(m, "org.freedesktop.DBus.ObjectManager", "InterfacesRemoved");
    if ((added || removed) && !dbus_message_get_destination(m)) {
        if (media_interface_signal(m, added) && bluez_up) {
            registered = 0;
            if (removed)
                register_tries = 0;
            else {
                register_tries = 3;
                bm_register();
            }
        }
        return DBUS_HANDLER_RESULT_HANDLED;
    }
    if (!dbus_message_is_signal(m, DBUS_INTERFACE_DBUS, "NameOwnerChanged") ||
        !dbus_message_has_sender(m, DBUS_SERVICE_DBUS))
        return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
    const char *name = 0, *old = 0, *new = 0;
    if (!dbus_message_get_args(m, 0, DBUS_TYPE_STRING, &name, DBUS_TYPE_STRING, &old,
                               DBUS_TYPE_STRING, &new, DBUS_TYPE_INVALID))
        return DBUS_HANDLER_RESULT_HANDLED;
    if (strcmp(name, bluez_name)) return DBUS_HANDLER_RESULT_HANDLED;
    registered = 0; /* whatever was registered went with the old bluetoothd */
    bluez_up = *new != 0;
    register_tries = bluez_up ? 3 : 0;
    if (bluez_up) bm_register();
    return DBUS_HANDLER_RESULT_HANDLED;
}

/* Setup and full-bus failures use the existing paced launcher, like a helper crash. */
static int bm_connect(void) {
    DBusError err;
    dbus_error_init(&err);
    conn = dbus_bus_get_private(bus_type, &err);
    if (!conn) _exit(1);
    dbus_connection_set_exit_on_disconnect(conn, FALSE);
    if (!dbus_connection_set_watch_functions(conn, add_watch, remove_watch, 0, 0, 0) ||
        !dbus_connection_set_timeout_functions(conn, add_timeout, remove_timeout, toggle_timeout, 0,
                                               0) ||
        !dbus_connection_register_object_path(conn, PLAYER_PATH, &vtable, 0))
        _exit(1);
    static const char *const rules[] = { "type='signal',sender='" DBUS_SERVICE_DBUS
                                         "',interface='" DBUS_INTERFACE_DBUS
                                         "',member='NameOwnerChanged',arg0='" BLUEZ "'",
                                         "type='signal',sender='" BLUEZ
                                         "',interface='org.freedesktop.DBus.ObjectManager'" };
    for (unsigned i = 0; i < sizeof rules / sizeof *rules; i++) {
        dbus_bus_add_match(conn, rules[i], &err);
        if (dbus_error_is_set(&err)) _exit(1);
    }
    if (!dbus_connection_add_filter(conn, on_signal, 0, 0)) _exit(1);
    bluez_up = dbus_bus_name_has_owner(conn, bluez_name, &err);
    if (dbus_error_is_set(&err)) _exit(1);
    register_tries = bluez_up ? 3 : 0;
    if (bluez_up) bm_register();
    return 1;
}

static int notification_failure(void) {
    return errno == ENOSYS || errno == EINVAL || errno == EACCES || errno == EPERM ? 2 : 1;
}

int main(void) {
    notify_fd = inotify_init1(O_CLOEXEC | O_NONBLOCK);
    if (notify_fd < 0) return notification_failure();
    if (inotify_add_watch(notify_fd, record_dir,
                          IN_MOVED_TO | IN_CLOSE_WRITE | IN_DELETE_SELF | IN_MOVE_SELF) < 0)
        return notification_failure();
    bm_read();
    bm_connect();
    /* The launcher waits five seconds after failure and replays the RAM snapshot.
     * It owns bus-outage and crash recovery; no duplicate reconnect loop here. */
    for (;;) {
        if (dbus_connection_get_dispatch_status(conn) == DBUS_DISPATCH_NEED_MEMORY) return 1;
        while (dbus_connection_get_dispatch_status(conn) == DBUS_DISPATCH_DATA_REMAINS)
            if (dbus_connection_dispatch(conn) == DBUS_DISPATCH_NEED_MEMORY) return 1;
        if (!dbus_connection_get_is_connected(conn)) return 1;
        long long now = now_ms();
        if (bluez_up && !registered && register_tries && now >= register_retry_at) {
            bm_register();
            continue; /* the synchronous reply may have queued signals or method calls */
        }
        struct bm_pollfd fds[BUS_SLOTS + 1] = { { notify_fd, POLLIN, 0 } };
        DBusWatch *selected[BUS_SLOTS] = { 0 };
        long long wait = -1;
        if (bluez_up && !registered && register_tries) {
            wait = register_retry_at - now_ms();
            if (wait < 0) wait = 0;
        }
        for (unsigned i = 0; i < BUS_SLOTS; i++) {
            fds[i + 1].fd = -1;
            DBusWatch *watch = bus_watches[i];
            if (watch && dbus_watch_get_enabled(watch)) {
                selected[i] = watch;
                fds[i + 1].fd = dbus_watch_get_unix_fd(watch);
                unsigned flags = dbus_watch_get_flags(watch);
                fds[i + 1].events = ((flags & DBUS_WATCH_READABLE) ? POLLIN : 0) |
                                    ((flags & DBUS_WATCH_WRITABLE) ? POLLOUT : 0);
            }
            DBusTimeout *timeout = bus_timeouts[i].timeout;
            if (timeout && dbus_timeout_get_enabled(timeout)) {
                long long left = bus_timeouts[i].at - now_ms();
                if (wait < 0 || left < wait) wait = left < 0 ? 0 : left;
            }
        }
        int delay = wait < 0 ? -1 : wait > 2147483647 ? 2147483647 : (int)wait;
        int ready = poll(fds, BUS_SLOTS + 1, delay);
        if (ready < 0) {
            if (errno == EINTR) continue;
            return 1;
        }
        if (fds[0].revents & (POLLERR | POLLHUP | POLLNVAL)) return 1;
        if ((fds[0].revents & POLLIN) && read_notifications()) {
            int changed = bm_read();
            if (changed && registered)
                bm_changed(changed == 2);
            else if (changed && bluez_up) {
                register_tries = 3;
                bm_register();
            }
        }
        for (unsigned i = 0; i < BUS_SLOTS; i++) {
            DBusWatch *watch = selected[i];
            short events = fds[i + 1].revents;
            /* Handling one watch can remove/toggle another (including a shared socket). */
            if (watch && bus_watches[i] == watch && dbus_watch_get_enabled(watch) && events) {
                unsigned flags = ((events & POLLIN) ? DBUS_WATCH_READABLE : 0) |
                                 ((events & POLLOUT) ? DBUS_WATCH_WRITABLE : 0) |
                                 ((events & (POLLERR | POLLNVAL)) ? DBUS_WATCH_ERROR : 0) |
                                 ((events & POLLHUP) ? DBUS_WATCH_HANGUP : 0);
                if (!dbus_watch_handle(watch, flags)) return 1;
            }
        }
        for (unsigned i = 0; i < BUS_SLOTS; i++) {
            DBusTimeout *timeout = bus_timeouts[i].timeout;
            if (timeout && dbus_timeout_get_enabled(timeout) && now_ms() >= bus_timeouts[i].at) {
                bus_timeouts[i].at = now_ms() + dbus_timeout_get_interval(timeout);
                if (!dbus_timeout_handle(timeout)) return 1;
            }
        }
    }
}
