#ifndef Q2_REMOTELEASE_H
#define Q2_REMOTELEASE_H

/* A live daemon, and every command inheriting its fd, keeps the radio reachable.
 * Never unlink this file: replacing its inode would split concurrent lock holders.
 * An unlocked stale file has no demand; all probe errors fail open.
 * The UI retains its successful exclusive probe through policy commit/stock switch,
 * preventing a new listener from starting between the sample and radio shutdown. */
#ifndef Q2_REMOTE_LEASE_PATH
#define Q2_REMOTE_LEASE_PATH "/tmp/q2remote.wifi.lock"
#endif
#if defined(REMOTE_HOST) || defined(PEQ_HOST)
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#define REMOTE_LEASE_CREATE (O_RDWR | O_CREAT)
static inline int remote_lease_lock(int fd, int op) { return flock(fd, op); }
#else
#define REMOTE_LEASE_CREATE 0x102 /* MIPS O_RDWR | O_CREAT */
int open(const char *, int, ...), close(int), *__errno_location(void);
int fcntl(int, int, ...), usleep(unsigned);
/* Stock libc.so.6 flock: 0xdcd18 loads v0=0x102f, 0xdcd1c syscall,
 * 0xdcd20 tests a3. demo has no flock GOT entry, so use this verified o32 ABI.
 * Return -errno on error; callers only need success/failure. */
static inline int remote_lease_lock(int fd, int op) {
    register int v0 __asm__("$2") = 0x102f;
    register int a0 __asm__("$4") = fd;
    register int a1 __asm__("$5") = op;
    register int a3 __asm__("$7");
    __asm__ volatile("syscall" : "+r"(v0), "+r"(a0), "+r"(a1), "=r"(a3)
                     : : "$1", "$3", "$8", "$9", "$10", "$11", "$12", "$13",
                         "$14", "$15", "$24", "$25", "hi", "lo", "memory");
    return a3 ? -v0 : v0;
}
#endif

/* Shared locks let a restarted daemon coexist with commands from its predecessor.
 * open() omits O_CLOEXEC: fork+exec commands keep this exact open-file description. */
static inline int remote_lease_open(void) {
    int fd = open(Q2_REMOTE_LEASE_PATH, REMOTE_LEASE_CREATE, 0600);
    if (fd >= 0 && fd < 3) {
        int high = fcntl(fd, 0, 3); /* F_DUPFD: Linux uapi asm-generic/fcntl.h, also MIPS */
        close(fd);
        fd = high; /* serve's dup2 onto stdio must never overwrite the lease */
    }
    if (fd < 0) return -1;
    /* A poller's exclusive probe is brief. Retry that startup race for up to 15 s;
     * failure stops startup visibly rather than serving with no availability lease. */
    for (int tries = 0; tries < 1500; ++tries) {
        if (!remote_lease_lock(fd, 1 | 4)) return fd; /* LOCK_SH | LOCK_NB */
        usleep(10000);
    }
    close(fd);
    return -1;
}

/* On an idle result, retain *guard until the controller finishes any transition.
 * Creating the shared inode also covers the first-ever daemon startup. */
static inline int remote_lease_probe(int *guard) {
    *guard = -1;
    int fd = open(Q2_REMOTE_LEASE_PATH, REMOTE_LEASE_CREATE, 0600);
    if (fd < 0) return 1;
    if (remote_lease_lock(fd, 2 | 4)) { /* LOCK_EX | LOCK_NB */
        close(fd);
        return 1;
    }
    *guard = fd;
    return 0;
}

static inline int remote_lease_busy(void) {
    int guard;
    int busy = remote_lease_probe(&guard);
    if (guard >= 0) close(guard);
    return busy;
}
#endif
