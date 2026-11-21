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
 *     Bluetooth off/on). It blocks on record and bus events while healthy.
 *
 * Plain libdbus, no GLib or helper threads. Text buffers are fixed. Built by tools/build.py
 * against the stock rootfs's libdbus-1. */
#define _GNU_SOURCE
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
typedef struct {
    unsigned long bits[32];
} sigset_t;
int sigemptyset(sigset_t *), sigaddset(sigset_t *, int);
int sigprocmask(int, const sigset_t *, sigset_t *);
void (*signal(int, void (*)(int)))(int);
int ppoll(struct bm_pollfd *, unsigned long, const void *, const sigset_t *);
#define SIGTERM 15
#define SIG_BLOCK 1 /* glibc MIPS o32; sigset_t is 1024 bits */
#define SIG_SETMASK 3
typedef int sig_atomic_t;
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
#include <signal.h>
#include <sys/inotify.h>
#define bm_pollfd pollfd
struct bm_timespec {
    long sec, nsec;
}; /* the host's timespec is two 64-bit words: the same layout */
#define BM_CLOCK(ts) clock_gettime(CLOCK_MONOTONIC, (struct timespec *)(ts))
#endif

/* An OOM in a writer invalidates its subiterator. Do not continue assembling a partial
 * message, or silently consume the only snapshot event: end the helper, releasing its bus
 * connection. */
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
#define RECORD_MAX 2048
#define FIELD_MAX 256

static const char *record_path = RECORD_PATH, *record_dir = "/tmp/q2-bt",
                  *record_leaf = "nowplaying", *bluez_name = BLUEZ, *adapter_path = ADAPTER;
static DBusBusType bus_type = DBUS_BUS_SYSTEM;

/* The record as last read: strings and numbers the signals and property replies are built from. */
static struct {
    char status[16], title[FIELD_MAX], artist[FIELD_MAX], album[FIELD_MAX], genre[FIELD_MAX];
    long long length_us, position_us; /* mpris:length and Position */
    unsigned written_ms; /* the payload's CLOCK_MONOTONIC milliseconds, wrapping at 32 bits */
    int track, tracks;
    unsigned generation; /* the payload's counter, so an unchanged file is not re-sent */
} rec;
static int registered, bluez_up, register_pending;
static volatile sig_atomic_t stopping;
static void stop(int sig) {
    (void)sig;
    stopping = 1;
}

/* Validate the complete bounded string once; the writer already cuts UTF-8 boundaries. */
static int bm_field(char *out, unsigned size, const char *value) {
    const char *end = strchr(value, '\n');
    unsigned n = end ? (unsigned)(end - value) : strlen(value);
    if (n >= size) return 0;
    memcpy(out, value, n);
    out[n] = 0;
    return dbus_validate_utf8(out, 0);
}
static int bm_parse(const char *text) {
    typeof(rec) next = { 0 };
    char *fields[] = { next.status, next.title, next.artist, next.album, next.genre };
    static const char *const keys[] = {
        "status", "title",    "artist",   "album", "genre",  "v",
        "gen",    "duration", "position", "track", "tracks", "now"
    };
    long long numbers[7] = { 0 };
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
                if (i < 5) {
                    if (!bm_field(fields[i], i ? FIELD_MAX : sizeof next.status, eq + 1)) return 0;
                } else {
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
        HAVE_POSITION = 1u << 8,
        HAVE_NOW = 1u << 11
    };
    unsigned required = HAVE_STATUS | HAVE_VERSION | HAVE_GENERATION | HAVE_POSITION | HAVE_NOW;
    if ((seen & required) != required || numbers[0] != 1 || !numbers[1]) return 0;
    if (strcmp(next.status, "Playing") && strcmp(next.status, "Paused") &&
        strcmp(next.status, "Stopped"))
        return 0;
    next.generation = (unsigned)numbers[1];
    next.length_us = numbers[2] * 1000;
    next.position_us = numbers[3] * 1000;
    next.track = (int)numbers[4];
    next.tracks = (int)numbers[5];
    next.written_ms = (unsigned)numbers[6];
    rec = next; /* Commit only a complete, validated record. */
    return 1;
}

/* The position now: the record's, plus the time since it was read while playing (media.c keeps
 * the same clock, but a registration after a bluetoothd restart starts from a record that may be
 * minutes old). */
static long long now_ms(void) {
    struct bm_timespec ts;
    /* A failed clock cannot supply a truthful position. */
    if (BM_CLOCK(&ts) || ts.sec < 0 || ts.nsec < 0 || ts.nsec >= 1000000000) _exit(1);
    return ts.sec * 1000LL + ts.nsec / 1000000;
}
static long long position_now(void) {
    long long p = rec.position_us;
    /* Project the producer's monotonic anchor, including a 32-bit millisecond wrap. */
    long long elapsed = (unsigned)((unsigned)now_ms() - rec.written_ms);
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
    /* Generation can repeat after demo restarts; compare the complete metadata. */
    int same = !strcmp(was.title, rec.title) && !strcmp(was.artist, rec.artist) &&
               !strcmp(was.album, rec.album) && !strcmp(was.genre, rec.genre) &&
               was.length_us == rec.length_us && was.track == rec.track;
    return !same || !was.generation ? 2 : 1; /* 2: metadata; 1: status/position */
}

/* Registration and change signals share the property writer. */
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
static void append_property(DBusMessageIter *iter, unsigned property) {
    const char *text = property == 0 ? "Q2 Pod" : property == 2 ? rec.status : "None";
    dbus_int64_t position = property == 4 ? position_now() : 0;
    const char *type = property == 1 ? "a{sv}" : property == 4 ? "x" : "s";
    const void *value = property == 4 ? (const void *)&position : (const void *)&text;
    append_entry(iter, property_names[property], type, value);
}
static void append_properties(DBusMessageIter *dict, int with_metadata) {
    for (unsigned i = 0; i < sizeof property_names / sizeof *property_names; i++)
        if (i != 1 || with_metadata) append_property(dict, i);
}

static DBusConnection *conn;

static void bm_changed(int track_changed);
static int bm_register_attempt(void) {
    if (registered) return 0;
    bm_read(); /* Recovery registration must carry the latest snapshot, even while paused. */
    if (!rec.generation || stopping || !bluez_up) return 0;
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
/* PropertiesChanged(interface, changed a{sv}, invalidated as): the track's properties when the
 * track changed, else the status and position alone. */
static void bm_changed(int track_changed) {
    if (!registered || stopping) return;
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

/* BlueZ owns the properties supplied at registration and through change signals. */
static DBusHandlerResult send_reply(DBusConnection *c, DBusMessage *reply) {
    dbus_connection_send(c, reply, 0);
    dbus_message_unref(reply);
    return DBUS_HANDLER_RESULT_HANDLED;
}
static DBusHandlerResult on_message(DBusConnection *c, DBusMessage *m, void *user) {
    (void)user;
    if (!dbus_message_is_method_call(m, PLAYER_IFACE, "Release"))
        return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
    registered = 0;
    register_pending = bluez_up;
    return send_reply(c, dbus_message_new_method_return(m));
}
static const DBusObjectPathVTable vtable = { 0, on_message, 0, 0, 0, 0 };

/* A renamed record preserves the directory watch; overflow rereads the current file. */
static int notify_fd;
#define IN_CLOSE_WRITE 0x00000008
#define IN_MOVED_TO 0x00000080
#define IN_DELETE_SELF 0x00000400
#define IN_MOVE_SELF 0x00000800
#define IN_Q_OVERFLOW 0x00004000
#define IN_IGNORED 0x00008000
static int read_notifications(void) {
    struct event {
        int wd;
        unsigned mask, cookie, len;
    };
    union {
        unsigned alignment;
        char bytes[4096];
    } buffer;
    int changed = 0, n;
    while ((n = read(notify_fd, buffer.bytes, sizeof buffer.bytes)) > 0) {
        for (unsigned at = 0; at + sizeof(struct event) <= (unsigned)n;) {
            struct event *e = (void *)(buffer.bytes + at);
            if (e->len > (unsigned)n - at - sizeof *e) return -1;
            if (e->mask & (IN_DELETE_SELF | IN_MOVE_SELF | IN_IGNORED)) return -1;
            if (e->mask & IN_Q_OVERFLOW) changed = 1;
            if (e->len && memchr(e + 1, 0, e->len) && !strcmp((char *)(e + 1), record_leaf))
                changed = 1;
            at += sizeof *e + e->len;
        }
    }
    return n < 0 && errno != EAGAIN && errno != EINTR ? -1 : changed;
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
            register_pending = added;
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
    register_pending = bluez_up;
    return DBUS_HANDLER_RESULT_HANDLED;
}

/* ponytail: a full bus failure ends metadata until the next demo run; no restart service. */
static int bm_connect(void) {
    DBusError err;
    dbus_error_init(&err);
    conn = dbus_bus_get_private(bus_type, &err);
    if (!conn) _exit(1);
    dbus_connection_set_exit_on_disconnect(conn, FALSE);
    if (!dbus_connection_register_object_path(conn, PLAYER_PATH, &vtable, 0)) _exit(1);
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
    register_pending = bluez_up;
    return 1;
}

/* Block SIGTERM across the stop check and ppoll: no signal can be lost before sleep.
 * Outside that atomic wait, a signal interrupts work and only sets the flag. */
int main(void) {
    sigset_t blocked, prior;
    /* Authentication may block without a player to withdraw. Keep termination immediate. */
    signal(SIGTERM, 0);
    notify_fd = inotify_init1(O_CLOEXEC | O_NONBLOCK);
    if (notify_fd < 0 ||
        inotify_add_watch(notify_fd, record_dir,
                          IN_MOVED_TO | IN_CLOSE_WRITE | IN_DELETE_SELF | IN_MOVE_SELF) < 0)
        return 1;
    bm_read();
    bm_connect();
    int bus_fd;
    if (!dbus_connection_get_unix_fd(conn, &bus_fd)) return 1;
    sigemptyset(&blocked);
    sigaddset(&blocked, SIGTERM);
    if (sigprocmask(SIG_BLOCK, &blocked, &prior)) return 1;
    signal(SIGTERM, stop);
    if (sigprocmask(SIG_SETMASK, &prior, 0)) return 1;
    while (!stopping) {
        /* A synchronous reply may already have consumed the socket's readiness. */
        do {
            if (!dbus_connection_read_write_dispatch(conn, 0)) goto done;
        } while (dbus_connection_get_dispatch_status(conn) == DBUS_DISPATCH_DATA_REMAINS);
        if (stopping) break;
        if (register_pending) {
            register_pending = 0;
            bm_register_attempt();
            continue;
        }
        dbus_connection_flush(conn);
        struct bm_pollfd fds[] = { { notify_fd, POLLIN, 0 }, { bus_fd, POLLIN, 0 } };
        if (sigprocmask(SIG_BLOCK, &blocked, 0)) break;
        if (stopping) {
            sigprocmask(SIG_SETMASK, &prior, 0);
            break;
        }
        int ready = ppoll(fds, 2, 0, &prior);
        int error = errno;
        if (sigprocmask(SIG_SETMASK, &prior, 0)) break;
        if (stopping) break;
        if (ready < 0) {
            if (error == EINTR) continue;
            break;
        }
        if ((fds[0].revents | fds[1].revents) & (POLLERR | POLLHUP | POLLNVAL)) break;
        if (fds[0].revents & POLLIN) {
            int event = read_notifications();
            if (event < 0) break;
            int changed = event ? bm_read() : 0;
            if (changed && registered)
                bm_changed(changed == 2);
            else if (changed)
                register_pending = bluez_up;
        }
    }
done:
    /* A successful reply proves removal before S90play's wait lets Rockbox start.
     * Even a timeout releases the owning connection; no stale helper can restart. */
    if (registered && dbus_connection_get_is_connected(conn)) {
        DBusMessage *m =
            dbus_message_new_method_call(bluez_name, adapter_path, MEDIA_IFACE, "UnregisterPlayer");
        const char *path = PLAYER_PATH;
        dbus_message_append_args(m, DBUS_TYPE_OBJECT_PATH, &path, DBUS_TYPE_INVALID);
        DBusMessage *reply = dbus_connection_send_with_reply_and_block(conn, m, 2000, 0);
        if (reply) dbus_message_unref(reply);
        dbus_message_unref(m);
    }
    dbus_connection_close(conn);
    dbus_connection_unref(conn);
    close(notify_fd);
    return 0;
}
