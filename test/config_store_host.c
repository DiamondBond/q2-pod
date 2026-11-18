#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static char root[1024];
static int step, fail, cut, short_io, interrupted, passed;
void cfg_test_setup(const char *p, int f, int c, int s, int i) {
    snprintf(root, sizeof root, "%s", p);
    step = passed = 0;
    fail = f;
    cut = c;
    short_io = s;
    interrupted = i;
}
int cfg_test_steps(void) { return step; }
int cfg_test_passed(void) { return passed; }
static int tick(void) {
    ++step;
    if (step == cut) _exit(77);
    if (step == fail) {
        errno = EIO;
        return 1;
    }
    return 0;
}
static void mapped(char *out, const char *p) {
    if (!strcmp(p, "/mnt/data"))
        snprintf(out, 1200, "%s", root);
    else
        snprintf(out, 1200, "%s/%s", root, strrchr(p, '/') + 1);
}
int cfg_test_open(const char *p, int flags, ...) {
    if (tick()) return -1;
    char out[1200];
    mapped(out, p);
    return open(out, flags, 0644);
}
ssize_t cfg_test_read(int fd, void *p, size_t n) {
    if (tick()) return -1;
    if (interrupted == 1) {
        interrupted = 0;
        errno = EINTR;
        return -1;
    }
    if (short_io && n > 7) n = 7;
    return read(fd, p, n);
}
ssize_t cfg_test_write(int fd, const void *p, size_t n) {
    if (tick()) return -1;
    if (interrupted == 2) {
        interrupted = 0;
        errno = EINTR;
        return -1;
    }
    if (short_io == 2) return 0;
    if (short_io && n > 3) n = 3;
    return write(fd, p, n);
}
int cfg_test_close(int fd) {
    int bad = tick(), result = close(fd);
    return bad ? -1 : result;
}
int cfg_test_fsync(int fd) { return tick() ? -1 : fsync(fd); }
int cfg_test_rename(const char *a, const char *b) {
    if (tick()) return -1;
    char aa[1200], bb[1200];
    mapped(aa, a);
    mapped(bb, b);
    return rename(aa, bb);
}
int cfg_test_unlink(const char *p) {
    char out[1200];
    mapped(out, p);
    return unlink(out);
}
int stock_config_store_trampoline(const char *p, const char *s, const char *k, const char *v) {
    (void)p;
    (void)s;
    (void)k;
    (void)v;
    ++passed;
    return 42;
}
