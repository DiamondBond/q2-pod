/* The Vault card app's socket (docs/internals.md#scrobbling): the Vault
 * (github.com/js-surya/q2-vault) keeps logins sealed on the card under a key in internal storage,
 * and serves each caller its own over /tmp/q2-vault.sock: Q2 Pod's own program as the id q2pod. One
 * Q2VAULT/1 request a connection (spot_exchange): "Q2VAULT/1\n<op>\n[body]", answered
 * "Q2VAULT/1\n<status>\n[body]". Only on the upload's thread, never the UI's: an answer can take
 * VAULT_WAIT_MS. */
#include "peq.h"
#ifndef PEQ_HOST
#include "stock.h"
#endif

#define VAULT_SOCK "/tmp/q2-vault.sock"
#define VAULT_BIN PEQ_ROOT "/mnt/mmc/.vault/q2-vault"
#define VAULT_WAIT_MS 5000
#define VAULT_HEAD "Q2VAULT/1\n"

int vault_installed(void) { return !access(VAULT_BIN, 0); }

/* The socket is one root owns, so nothing else (an app, while the Vault is closed) can stand in
 * for it and take a login. ponytail: stock imports stat, not lstat, so a link is followed: what it
 * names must still be a socket root owns that answers Q2VAULT/1; only root can make one. */
static int root_socket(void) {
    unsigned st[36] = { 0 }; /* o32 struct stat: st_mode word 5, st_uid word 7 */
    return !__xstat(3, VAULT_SOCK, st) && (st[5] & 0170000) == 0140000 && st[7] == 0;
}

/* op with body's len bytes; the answer's status ("ok", "none", ...) and, for out, its body in out
 * (NUL-terminated, max bytes with the NUL). 1 ok, 0 none, -1 anything else: no Vault, not now, a
 * refusal, a body that doesn't fit. */
static int ask(const char *op, const char *body, unsigned len, char *out, unsigned max) {
    if (len > VAULT_MAX || !root_socket()) return -1;
    unsigned cap = VAULT_MAX + 64, n = 0;
    char *buf = calloc(1, cap + 1);
    if (!buf) return -1;
    int head = tk_snprintf(buf, cap, VAULT_HEAD "%s\n", op);
    if (body && len) memcpy(buf + head, body, len);
    volatile int cancel = 0;
    int r = -1;
    if (spot_exchange(VAULT_SOCK, VAULT_WAIT_MS, cap, buf, (unsigned)head + len, &n, &cancel) ==
            SPOT_OK &&
        n <= cap) {
        buf[n] = 0;
        char *status =
            strncmp(buf, VAULT_HEAD, sizeof VAULT_HEAD - 1) ? 0 : buf + sizeof VAULT_HEAD - 1;
        char *end = status;
        while (end && *end && *end != '\n') ++end; /* stock imports no strchr */
        if (end && !*end) end = 0;
        if (end) {
            *end = 0;
            unsigned got = n - (unsigned)(end + 1 - buf);
            if (!strcmp(status, "none"))
                r = 0;
            else if (!strcmp(status, "ok") && (!out || got < max)) {
                if (out) memcpy(out, end + 1, got), out[got] = 0;
                r = 1;
            }
        }
    }
    memset(buf, 0, cap + 1); /* the secret, off the heap */
    free(buf);
    return r;
}

int vault_get(char *out, unsigned max) { return ask("get", 0, 0, out, max); }
int vault_put(const char *body, unsigned len) { return len ? ask("put", body, len, 0, 0) : -1; }
int vault_delete(void) { return ask("delete", 0, 0, 0, 0) > 0 ? 1 : -1; }
