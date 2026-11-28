/* A secrets app (docs/internals.md#scrobbling): a card app whose q2app says secrets=1 keeps Q2
 * Pod's logins, sealed, and gives them back over /tmp/q2-<id>.sock to Q2 Pod's own program only.
 * One request a connection (spot_exchange): "Q2VAULT/1\n<op>\n[body]", answered
 * "Q2VAULT/1\n<status>\n[body]", the protocol q2-vault speaks. Only on the upload's thread: an
 * answer can take SECRETS_WAIT_MS, and a start SECRETS_TRIES tries. */
#include "peq.h"
#ifndef PEQ_HOST
#include "stock.h"
#endif

#define SECRETS_HEAD "Q2VAULT/1\n"
#define SECRETS_WAIT_MS 5000
#define SECRETS_TRIES 20 /* 250 ms apart: an app starting gets 5 s */

/* app's socket path, when root owns the socket there: lstat, so a link another app leaves in
 * sticky /tmp while the app is down is none, and only root can bind the real one. */
static int root_socket(const char *app, char *path, unsigned n) {
    unsigned st[36] = { 0 }; /* o32 struct stat: st_mode word 5, st_uid word 7 */
    tk_snprintf(path, n, "/tmp/q2-%s.sock", app);
    return !__lxstat(3, path, st) && (st[5] & 0170000) == 0140000 && st[7] == 0;
}

/* op with body's len bytes; an "ok" answer's body into out (NUL-terminated within max). 1 ok,
 * 0 none saved, -1 anything else: no socket, a refusal, an answer that doesn't fit. */
static int ask(const char *app, const char *op, const char *body, unsigned len, char *out,
               unsigned max) {
    char path[48], buf[SECRETS_MAX + 64];
    unsigned n = 0;
    volatile int cancel = 0;
    int head = tk_snprintf(buf, sizeof buf, SECRETS_HEAD "%s\n", op), r = -1;
    if (len > SECRETS_MAX || !root_socket(app, path, sizeof path)) return -1;
    memcpy(buf + head, body, len);
    if (spot_exchange(path, SECRETS_WAIT_MS, sizeof buf - 1, buf, (unsigned)head + len, &n,
                      &cancel) == SPOT_OK) {
        buf[n] = 0;
        char *status = strncmp(buf, SECRETS_HEAD, sizeof SECRETS_HEAD - 1)
                           ? 0
                           : buf + sizeof SECRETS_HEAD - 1,
             *end = status;
        while (end && *end && *end != '\n') ++end; /* stock imports no strchr */
        if (end && *end) {
            *end++ = 0;
            unsigned got = n - (unsigned)(end - buf);
            if (!strcmp(status, "none"))
                r = 0;
            else if (!strcmp(status, "ok") && (!out || got < max)) {
                if (out) memcpy(out, end, got), out[got] = 0;
                r = 1;
            }
        }
    }
    memset(buf, 0, sizeof buf); /* the logins, off the stack */
    return r;
}

/* The app's copy into out: started first (addon_wake) when it doesn't answer. */
int secrets_get(const char *app, char *out, unsigned max) {
    int r = -1;
    for (int i = 0; i < SECRETS_TRIES && (r = ask(app, "get", "", 0, out, max)) < 0; i++) {
        if (!i) addon_wake(app);
        if (i + 1 < SECRETS_TRIES) usleep(250000);
    }
    return r;
}

/* body as the app's copy, then read back: 1 only when it gives back what was put. */
int secrets_put(const char *app, const char *body, unsigned len) {
    char back[SECRETS_MAX];
    int ok = ask(app, "put", body, len, 0, 0) > 0 &&
             ask(app, "get", "", 0, back, sizeof back) > 0 && strlen(back) == len &&
             !memcmp(back, body, len);
    memset(back, 0, sizeof back);
    return ok;
}
