#include "navigation.h"

int bt_handover_route(void) {
    return g_bluetoothflag && bt_linkstatus && !bt__recv_pageflag && mclGetOutputWay() == 1;
}

/* Stock has no timeout applet. Keep the finite silence write in its own session, before the
 * existing gain increase, and give up on it after 3 s: quieting must never prevent a takeover. */
void bt_handover_quiet(int routed) {
    if (!routed || !bt_handover_route()) return;
    int saved = *__errno_location(), pid = fork();
    if (!pid) {
        child_oom_first();
        execl("/usr/bin/setsid", "setsid", "/bin/sh", "-c",
              "head -c 32768 /dev/zero | aplay -q -D bluealsa -t raw -f S16_LE -r 48000 -c 2",
              (char *)0);
        child_exit(127);
    }
    if (pid > 0) {
        int done = 0, status;
        for (unsigned n = 0; n < 150; ++n) {
            int got = waitpid(pid, &status, 1); /* WNOHANG; EINTR consumes the budget too */
            if (got == pid || (got < 0 && *__errno_location() == 10)) {
                if (got == pid && status) chapter_kill(-pid, 9); /* a dead shell may leave aplay */
                done = 1; /* reaped, or ECHILD: never signal a pid which could have been reused */
                break;
            }
            if (got < 0 && *__errno_location() != 4) break;
            sleep_ms(20);
        }
        if (!done) {
            chapter_kill(-pid, 9); /* the shell, head and aplay */
            chapter_kill(pid, 9);  /* also before setsid has made the child's session */
            for (unsigned n = 0; n < FF_GRACE_MS / 20; ++n) {
                int got = waitpid(pid, &status, 1);
                if (got == pid || (got < 0 && *__errno_location() != 4)) break;
                sleep_ms(20);
            }
            /* ponytail: uninterruptible I/O can outlast the grace, as in ff_reap; demo exits
             * immediately after this, leaving any later zombie for init to reap. */
        }
    }
    *__errno_location() = saved;
}
