/* q2mpris (docs/internals.md#bluetooth-track-information): the Q2's now-playing track, published
 * to bluetoothd as a media player, for AVRCP track information. No transport-control flags are
 * advertised: stock's own route keeps the buttons.
 *
 * patch/btmeta.c writes RECORD_PATH whole (renamed into place) when the track, the play status or
 * the position changes. Its arrival wakes this helper, which sends PropertiesChanged for
 * org.mpris.MediaPlayer2.Player (Metadata, PlaybackStatus, Position) as bluez's media.c parses
 * them, and registers again whenever org.bluez or its adapter comes back (stock restarts
 * bluetoothd at every Bluetooth off/on). It sleeps in ppoll between those events. */
#define _GNU_SOURCE
/* libdbus 1.12's, as the stock rootfs has it: what this file uses, with the structs a caller
 * allocates laid out as libdbus's own on 32 and 64 bits (no host libdbus headers needed). */
typedef unsigned dbus_bool_t;
typedef int dbus_int32_t;
typedef long long dbus_int64_t;
typedef struct DBusConnection DBusConnection;
typedef struct DBusMessage DBusMessage;
typedef struct {
    void *dummy1, *dummy2;
    unsigned dummy3;
    int dummy4[9];
    void *pad2, *pad3;
} DBusMessageIter;
typedef struct {
    const char *name, *message;
    unsigned dummy;
    void *padding1;
} DBusError;
typedef enum { DBUS_BUS_SESSION, DBUS_BUS_SYSTEM } DBusBusType;
typedef enum { DBUS_HANDLER_RESULT_HANDLED, DBUS_HANDLER_RESULT_NOT_YET_HANDLED } DBusHandlerResult;
typedef enum { DBUS_DISPATCH_DATA_REMAINS } DBusDispatchStatus;
typedef DBusHandlerResult (*DBusHandleMessageFunction)(DBusConnection *, DBusMessage *, void *);
typedef struct {
    void (*unregister_function)(DBusConnection *, void *);
    DBusHandleMessageFunction message_function;
    void (*pad[4])(void *);
} DBusObjectPathVTable;
#define FALSE 0
#define DBUS_TYPE_INVALID 0
#define DBUS_TYPE_ARRAY 'a'
#define DBUS_TYPE_DICT_ENTRY 'e'
#define DBUS_TYPE_OBJECT_PATH 'o'
#define DBUS_TYPE_STRING 's'
#define DBUS_TYPE_VARIANT 'v'
#define DBUS_SERVICE_DBUS "org.freedesktop.DBus"
#define DBUS_INTERFACE_DBUS "org.freedesktop.DBus"
#define DBUS_INTERFACE_PROPERTIES "org.freedesktop.DBus.Properties"
DBusConnection *dbus_bus_get_private(DBusBusType, DBusError *);
void dbus_bus_add_match(DBusConnection *, const char *, DBusError *);
dbus_bool_t dbus_bus_name_has_owner(DBusConnection *, const char *, DBusError *);
dbus_bool_t dbus_connection_add_filter(DBusConnection *, DBusHandleMessageFunction, void *,
                                       void (*)(void *));
dbus_bool_t dbus_connection_register_object_path(DBusConnection *, const char *,
                                                 const DBusObjectPathVTable *, void *);
void dbus_connection_set_exit_on_disconnect(DBusConnection *, dbus_bool_t);
dbus_bool_t dbus_connection_get_unix_fd(DBusConnection *, int *);
dbus_bool_t dbus_connection_read_write_dispatch(DBusConnection *, int);
DBusDispatchStatus dbus_connection_get_dispatch_status(DBusConnection *);
dbus_bool_t dbus_connection_send(DBusConnection *, DBusMessage *, unsigned *);
DBusMessage *dbus_connection_send_with_reply_and_block(DBusConnection *, DBusMessage *, int,
                                                       DBusError *);
void dbus_connection_flush(DBusConnection *), dbus_connection_close(DBusConnection *),
    dbus_connection_unref(DBusConnection *);
dbus_bool_t dbus_connection_get_is_connected(DBusConnection *);
void dbus_error_init(DBusError *), dbus_error_free(DBusError *);
dbus_bool_t dbus_error_is_set(const DBusError *),
    dbus_error_has_name(const DBusError *, const char *);
dbus_bool_t dbus_validate_utf8(const char *, DBusError *);
DBusMessage *dbus_message_new_method_call(const char *, const char *, const char *, const char *);
DBusMessage *dbus_message_new_method_return(DBusMessage *);
DBusMessage *dbus_message_new_signal(const char *, const char *, const char *);
void dbus_message_unref(DBusMessage *);
dbus_bool_t dbus_message_is_method_call(DBusMessage *, const char *, const char *);
dbus_bool_t dbus_message_is_signal(DBusMessage *, const char *, const char *);
dbus_bool_t dbus_message_has_sender(DBusMessage *, const char *);
const char *dbus_message_get_destination(DBusMessage *);
dbus_bool_t dbus_message_get_args(DBusMessage *, DBusError *, int, ...);
dbus_bool_t dbus_message_append_args(DBusMessage *, int, ...);
dbus_bool_t dbus_message_iter_init(DBusMessage *, DBusMessageIter *);
void dbus_message_iter_init_append(DBusMessage *, DBusMessageIter *);
int dbus_message_iter_get_arg_type(DBusMessageIter *);
void dbus_message_iter_get_basic(DBusMessageIter *, void *);
dbus_bool_t dbus_message_iter_next(DBusMessageIter *);
void dbus_message_iter_recurse(DBusMessageIter *, DBusMessageIter *);
dbus_bool_t dbus_message_iter_open_container(DBusMessageIter *, int, const char *,
                                             DBusMessageIter *);
dbus_bool_t dbus_message_iter_close_container(DBusMessageIter *, DBusMessageIter *);
dbus_bool_t dbus_message_iter_append_basic(DBusMessageIter *, int, const void *);
#ifdef __mips__ /* the Q2 build: no MIPS sysroot, so libc is declared here, as video.c's */
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
} sigset_t; /* glibc MIPS o32's 1024 bits */
int sigemptyset(sigset_t *), sigaddset(sigset_t *, int);
int sigprocmask(int, const sigset_t *, sigset_t *);
void (*signal(int, void (*)(int)))(int);
int ppoll(struct bm_pollfd *, unsigned long, const void *, const sigset_t *);
int clock_gettime(int, void *);
void _exit(int) __attribute__((noreturn));
unsigned strlen(const char *);
char *strchr(const char *, int);
int strcmp(const char *, const char *), memcmp(const void *, const void *, unsigned);
void *memcpy(void *, const void *, unsigned);
void *memchr(const void *, int, unsigned);
#define SIGTERM 15
#define SIG_BLOCK 1
#define O_RDONLY 0
#define O_CLOEXEC 0x80000 /* MIPS */
#define O_NONBLOCK 0x80   /* MIPS */
#define O_NOFOLLOW 0x20000
#define POLLIN 1
#define POLLERR 8
#define POLLHUP 16
#define POLLNVAL 32
#define EINTR 4
#define IN_MOVED_TO 0x80
#else /* test/mpris.py */
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <sys/inotify.h>
#define bm_pollfd pollfd
#endif

/* Out of memory, a message can't be finished: end the helper, which releases its bus name. */
#define NEED(x)                                                                                    \
    ({                                                                                             \
        __typeof__(x) need_ = (x);                                                                 \
        if (!need_) _exit(1);                                                                      \
        need_;                                                                                     \
    })
#define dbus_message_iter_open_container(...) NEED(dbus_message_iter_open_container(__VA_ARGS__))
#define dbus_message_iter_append_basic(...) NEED(dbus_message_iter_append_basic(__VA_ARGS__))
#define dbus_message_iter_close_container(...) NEED(dbus_message_iter_close_container(__VA_ARGS__))
#define dbus_message_append_args(...) NEED(dbus_message_append_args(__VA_ARGS__))
#define dbus_connection_send(...) NEED(dbus_connection_send(__VA_ARGS__))
#define dbus_message_new_method_call(...) NEED(dbus_message_new_method_call(__VA_ARGS__))
#define dbus_message_new_method_return(...) NEED(dbus_message_new_method_return(__VA_ARGS__))
#define dbus_message_new_signal(...) NEED(dbus_message_new_signal(__VA_ARGS__))

#define RECORD_DIR "/tmp/q2-bt"
#define RECORD_PATH RECORD_DIR "/nowplaying"
#define PLAYER_PATH "/q2pod/player"
#define PLAYER_IFACE "org.mpris.MediaPlayer2.Player"
#define BLUEZ "org.bluez"
#define ADAPTER "/org/bluez/hci0"
#define MEDIA_IFACE "org.bluez.Media1"
#define RECORD_MAX 2048
#define FIELD_MAX 256

/* The record as last read; status is empty before the first. */
static struct {
    char status[16], title[FIELD_MAX], artist[FIELD_MAX], album[FIELD_MAX], genre[FIELD_MAX];
    long long length_us, position_us; /* mpris:length and Position */
    unsigned written_ms; /* btmeta.c's CLOCK_MONOTONIC milliseconds, wrapping at 32 bits */
    int track;
} rec;
static int registered, bluez_up, register_pending;
static volatile int stopping;
static void stop(int sig) {
    (void)sig;
    stopping = 1;
}

/* btmeta.c's "key=value" lines into rec, each string checked once for UTF-8 (the writer cuts
 * on character boundaries); 0 leaves rec as it was. */
static int bm_parse(const char *text) {
    typeof(rec) next = { 0 };
    char *fields[] = { next.status, next.title, next.artist, next.album, next.genre };
    static const char *const keys[] = { "status",   "title", "artist",   "album", "genre",
                                        "duration", "track", "position", "now" };
    long long numbers[4] = { 0 };
    for (const char *line = text, *end; (end = strchr(line, '\n')); line = end + 1) {
        const char *eq = memchr(line, '=', (unsigned)(end - line));
        if (!eq) continue;
        const char *v = eq + 1;
        unsigned n = (unsigned)(end - v);
        for (unsigned i = 0; i < sizeof keys / sizeof *keys; i++) {
            if ((unsigned)(eq - line) != strlen(keys[i]) || memcmp(line, keys[i], strlen(keys[i])))
                continue;
            if (i < 5) {
                if (n >= (i ? FIELD_MAX : sizeof next.status)) return 0;
                memcpy(fields[i], v, n);
                fields[i][n] = 0;
                if (!dbus_validate_utf8(fields[i], 0)) return 0;
            } else
                for (; v < end; v++) {
                    if (*v < '0' || *v > '9') return 0;
                    numbers[i - 5] = numbers[i - 5] * 10 + (*v - '0');
                }
            break;
        }
    }
    if (!next.status[0]) return 0;
    next.length_us = numbers[0] * 1000;
    next.track = (int)numbers[1];
    next.position_us = numbers[2] * 1000;
    next.written_ms = (unsigned)numbers[3];
    rec = next;
    return 1;
}

/* The position now: the record's, plus the time since it was written while playing (media.c
 * keeps the same clock, but a registration after a bluetoothd restart can start from a record
 * minutes old). */
static long long position_now(void) {
    struct {
        long sec, nsec;
    } ts; /* struct timespec */
    clock_gettime(1 /* CLOCK_MONOTONIC */, (void *)&ts);
    unsigned elapsed = (unsigned)(ts.sec * 1000LL + ts.nsec / 1000000) - rec.written_ms;
    long long p = rec.position_us + (strcmp(rec.status, "Playing") ? 0 : elapsed * 1000LL);
    return rec.length_us && p > rec.length_us ? rec.length_us : p;
}

/* Reads the record into rec: 2 when its track changed, 1 its status or position alone, 0 none. */
static int bm_read(void) {
    char text[RECORD_MAX];
    int fd = open(RECORD_PATH, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return 0;
    int n = read(fd, text, sizeof text - 1);
    close(fd);
    if (n <= 0) return 0;
    text[n] = 0;
    typeof(rec) was = rec;
    if (!bm_parse(text)) return 0;
    int same = !strcmp(was.title, rec.title) && !strcmp(was.artist, rec.artist) &&
               !strcmp(was.album, rec.album) && !strcmp(was.genre, rec.genre) &&
               was.length_us == rec.length_us && was.track == rec.track;
    return !same || !was.status[0] ? 2 : 1;
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
/* BlueZ resets the position when Metadata arrives, so Metadata precedes Position. No
 * CanControl/CanPlay: stock's own route keeps the buttons. */
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
static void bm_register(void) {
    bm_read(); /* a registration carries the latest record, even while paused */
    if (!rec.status[0] || !bluez_up) return;
    DBusMessage *m = dbus_message_new_method_call(BLUEZ, ADAPTER, MEDIA_IFACE, "RegisterPlayer");
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
    if (reply) {
        dbus_message_unref(reply);
        registered = 1;
    } else if (dbus_error_has_name(&err, "org.bluez.Error.AlreadyExists")) {
        /* this bluetoothd has us already (an owner-up signal arriving after the registration
         * cleared it here), from an older record: send the current one */
        registered = 1;
        bm_changed(1);
    }
    dbus_error_free(&err);
}

/* BlueZ owns the properties supplied at registration and through change signals. */
static DBusHandlerResult on_message(DBusConnection *c, DBusMessage *m, void *user) {
    (void)user;
    if (!dbus_message_is_method_call(m, PLAYER_IFACE, "Release"))
        return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
    registered = 0;
    register_pending = bluez_up;
    DBusMessage *reply = dbus_message_new_method_return(m);
    dbus_connection_send(c, reply, 0);
    dbus_message_unref(reply);
    return DBUS_HANDLER_RESULT_HANDLED;
}
static const DBusObjectPathVTable vtable = { .message_function = on_message };

/* 1 when an InterfacesAdded/InterfacesRemoved signal names the adapter's Media1. */
static int media_interface_signal(DBusMessage *m, int added) {
    DBusMessageIter args, interfaces;
    const char *path = 0;
    if (!dbus_message_iter_init(m, &args) ||
        dbus_message_iter_get_arg_type(&args) != DBUS_TYPE_OBJECT_PATH)
        return 0;
    dbus_message_iter_get_basic(&args, &path);
    if (strcmp(path, ADAPTER) || !dbus_message_iter_next(&args) ||
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
/* org.bluez and its adapter coming and going: bluetoothd restarts at every Bluetooth off/on. */
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
                               DBUS_TYPE_STRING, &new, DBUS_TYPE_INVALID) ||
        strcmp(name, BLUEZ))
        return DBUS_HANDLER_RESULT_HANDLED;
    registered = 0; /* whatever was registered went with the old bluetoothd */
    bluez_up = *new != 0;
    register_pending = bluez_up;
    return DBUS_HANDLER_RESULT_HANDLED;
}

/* ponytail: a failed bus connection, or the bus going, ends metadata until the next demo run;
 * there is no restart. */
static void bm_connect(void) {
    DBusError err;
    dbus_error_init(&err);
    conn = dbus_bus_get_private(DBUS_BUS_SYSTEM, &err);
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
    bluez_up = dbus_bus_name_has_owner(conn, BLUEZ, &err);
    if (dbus_error_is_set(&err)) _exit(1);
    register_pending = bluez_up;
}

int main(void) {
    /* SIGTERM ends the helper at once until there is a player to withdraw (a bus connection's
     * authentication can block). */
    signal(SIGTERM, 0);
    int notify_fd = inotify_init1(O_CLOEXEC | O_NONBLOCK), bus_fd;
    if (notify_fd < 0 || inotify_add_watch(notify_fd, RECORD_DIR, IN_MOVED_TO) < 0) return 1;
    bm_read();
    bm_connect();
    if (!dbus_connection_get_unix_fd(conn, &bus_fd)) return 1;
    /* Then SIGTERM is blocked but inside ppoll: one sent while the loop works ends its next
     * wait, so none is lost between the stopping check and the sleep. S90play waits for this
     * exit before an app takes over. */
    sigset_t term, unblocked;
    sigemptyset(&term);
    sigaddset(&term, SIGTERM);
    sigprocmask(SIG_BLOCK, &term, &unblocked);
    signal(SIGTERM, stop);
    while (!stopping) {
        /* a blocking reply may already have taken the socket's readiness */
        do {
            if (!dbus_connection_read_write_dispatch(conn, 0)) goto done;
        } while (dbus_connection_get_dispatch_status(conn) == DBUS_DISPATCH_DATA_REMAINS);
        if (register_pending) {
            register_pending = 0;
            bm_register();
            continue;
        }
        dbus_connection_flush(conn);
        struct bm_pollfd fds[] = { { notify_fd, POLLIN, 0 }, { bus_fd, POLLIN, 0 } };
        if (ppoll(fds, 2, 0, &unblocked) < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if ((fds[0].revents | fds[1].revents) & (POLLERR | POLLHUP | POLLNVAL)) break;
        if (fds[0].revents & POLLIN) {
            char events[1024]; /* each one is a new record renamed into place */
            while (read(notify_fd, events, sizeof events) > 0) continue;
            int changed = bm_read();
            if (changed && registered)
                bm_changed(changed == 2);
            else if (changed)
                register_pending = bluez_up;
        }
    }
done:
    /* A reply proves the player is gone before S90play's wait lets an app take over; a timeout
     * still ends this connection, and the player with it. */
    if (registered && dbus_connection_get_is_connected(conn)) {
        DBusMessage *m =
            dbus_message_new_method_call(BLUEZ, ADAPTER, MEDIA_IFACE, "UnregisterPlayer");
        const char *path = PLAYER_PATH;
        dbus_message_append_args(m, DBUS_TYPE_OBJECT_PATH, &path, DBUS_TYPE_INVALID);
        DBusMessage *reply = dbus_connection_send_with_reply_and_block(conn, m, 2000, 0);
        if (reply) dbus_message_unref(reply);
    }
    return 0;
}
