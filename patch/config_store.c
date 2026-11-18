/* Atomic replacement of the internal preferences, including Bluetooth's switch.
 * Never truncate the live file. Fail before rename on any incomplete read/write.
 * Other stock config files retain their original writer and format. */
#ifdef Q2_CONFIG_HOST
#include "config_store_test.h"
#else
#include "navigation.h"
#endif

#define CFG_PATH "/mnt/data/config.ini"
#define CFG_TMP "/mnt/data/.q2-config.new"
#define CFG_DIR "/mnt/data"
#define CFG_MAX 65536
#define CFG_FIELD 1024
#ifdef Q2_CONFIG_HOST
#define CFG_READ (O_RDONLY | O_CLOEXEC | O_NOFOLLOW)
#define CFG_WRITE (O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC | O_NOFOLLOW)
#define CFG_DIRECTORY (O_RDONLY | O_DIRECTORY | O_CLOEXEC)
#else
/* Linux MIPS o32 flags, not the host's asm-generic values. */
#define CFG_READ 0xa0000
#define CFG_WRITE 0xa0301
#define CFG_DIRECTORY 0x90000
#endif

static unsigned config_busy;
static unsigned config_bytes; /* guarded with the whole transaction */

static int cfg_space(char c) { return c == ' ' || c == '\t' || c == '\r'; }

static int cfg_field(const char *s, int name) {
    if (!s || (name && !*s)) return 0;
    unsigned n = 0;
    for (; s[n]; ++n)
        if (n >= CFG_FIELD || s[n] == '\n' || s[n] == '\r' ||
            (name && (s[n] == '=' || s[n] == '[' || s[n] == ']')))
            return 0;
    return !name || (!cfg_space(s[0]) && !cfg_space(s[n - 1]));
}

static int cfg_write(int fd, const char *s, unsigned n) {
    if (n > CFG_MAX - config_bytes) return -1;
    while (n) {
        int r = write(fd, s, n);
        if (r < 0 && *__errno_location() == 4 /* EINTR */) continue;
        if (r <= 0 || (unsigned)r > n) return -1;
        s += r;
        n -= (unsigned)r;
        config_bytes += (unsigned)r;
    }
    return 0;
}

static int cfg_pair(int fd, const char *key, const char *value) {
    return cfg_write(fd, key, strlen(key)) || cfg_write(fd, "=", 1) ||
                   cfg_write(fd, value, strlen(value)) || cfg_write(fd, "\n", 1)
               ? -1
               : 0;
}

/* Preserve unknown keys, comments, ordering and bytes outside the requested key.
 * Duplicate matching sections/keys receive the same value; either reader policy
 * then sees the requested value. Missing keys are added within their section. */
static int cfg_render(int fd, const char *in, unsigned n, const char *section, const char *key,
                      const char *value) {
    unsigned sl = strlen(section), kl = strlen(key), at = 0;
    int inside = 0, seen = 0, found = 0;
    while (at < n) {
        unsigned start = at;
        while (at < n && in[at] != '\n') ++at;
        unsigned end = at;
        if (at < n) ++at;
        unsigned a = start, b = end;
        while (a < b && cfg_space(in[a])) ++a;
        while (b > a && cfg_space(in[b - 1])) --b;
        if (a < b && in[a] == '[') {
            if (b - a < 3 || in[b - 1] != ']') return -1;
            if (inside && !found && cfg_pair(fd, key, value)) return -1;
            inside = b - a == sl + 2 && !memcmp(in + a + 1, section, sl);
            seen |= inside;
            found = 0;
        } else if (inside && b - a > kl && !memcmp(in + a, key, kl)) {
            unsigned eq = a + kl;
            while (eq < b && cfg_space(in[eq])) ++eq;
            if (eq < b && in[eq] == '=') {
                if (cfg_pair(fd, key, value)) return -1;
                found = 1;
                continue;
            }
        }
        if (cfg_write(fd, in + start, at - start)) return -1;
        if (at == n && in[n - 1] != '\n' && cfg_write(fd, "\n", 1)) return -1;
    }
    if (!seen && (cfg_write(fd, "[", 1) || cfg_write(fd, section, sl) || cfg_write(fd, "]\n", 2)))
        return -1;
    return ((!seen || (inside && !found)) && cfg_pair(fd, key, value)) ? -1 : 0;
}

static int cfg_save(const char *section, const char *key, const char *value) {
    int dir = -1, src = -1, dst = -1, result = -1, touched = 0;
    unsigned n = 0;
    config_bytes = 0;
    char *in = calloc(1, CFG_MAX + 1);
    if (!in) return -1;
    dir = open(CFG_DIR, CFG_DIRECTORY);
    if (dir < 0) goto done;
    src = open(CFG_PATH, CFG_READ);
    /* An absent file is legitimate on first use. Other open errors must never
     * turn an existing but unreadable config into a one-key default file. */
    if (src < 0 && *__errno_location() != 2 /* ENOENT */) goto done;
    if (src >= 0) {
        for (;;) {
            int r = read(src, in + n, CFG_MAX + 1 - n);
            if (r < 0 && *__errno_location() == 4) continue;
            if (r < 0) goto done;
            if (!r) break;
            n += (unsigned)r;
            if (n > CFG_MAX) goto done;
        }
        int r = close(src);
        src = -1;
        if (r) goto done;
    }
    for (unsigned i = 0; i < n; ++i)
        if (!in[i]) goto done; /* binary/corrupt input: keep it for diagnosis */
    dst = open(CFG_TMP, CFG_WRITE, 0644);
    if (dst < 0) goto done;
    touched = 1;
    if (cfg_render(dst, in, n, section, key, value) || fsync(dst)) goto done;
    int r = close(dst);
    dst = -1;
    if (r || rename(CFG_TMP, CFG_PATH)) goto done;
    touched = 0;
    /* Once renamed, either old or new complete content can survive an abrupt
     * reset. Report success only after the directory entry is durable too. */
    result = fsync(dir) ? -1 : 0;
done:
    if (src >= 0) close(src);
    if (dst >= 0) close(dst);
    if (touched) unlink(CFG_TMP);
    if (dir >= 0) close(dir);
    free(in);
    return result;
}

int ringnav_config_store(const char *path, const char *section, const char *key,
                         const char *value) {
    if (!path || strcmp(path, CFG_PATH))
        return stock_config_store_trampoline(path, section, key, value);
    if (!cfg_field(section, 1) || !cfg_field(key, 1) || !cfg_field(value, 0)) return -1;
    /* Serialize the complete read/modify/replace across demo's threads. Bound
     * waiting rather than hang the UI forever if another writer gets stuck. */
    unsigned tries = 0;
    while (__atomic_exchange_n(&config_busy, 1, __ATOMIC_ACQUIRE)) {
        if (++tries >= 2000) return -1;
        usleep(1000);
    }
    int result = cfg_save(section, key, value);
    __atomic_store_n(&config_busy, 0, __ATOMIC_RELEASE);
    return result;
}
