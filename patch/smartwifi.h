#ifndef Q2_SMARTWIFI_H
#define Q2_SMARTWIFI_H

/* Named demand owners. UNKNOWN is conservative; invalid owners and exhausted lease
 * storage latch a fail-open fault (radio kept available until demo restarts). */
enum smart_wifi_owner {
    SW_STOCK, SW_SPOTIFY, SW_RADIO, SW_SCROBBLE, SW_TIDAL, SW_NETUPDATE,
    SW_SHELF, SW_ADDON, SW_REMOTE, SW_USB, SW_SERVICES, SW_UNKNOWN, SW_OWNER_COUNT
};
enum { SW_WAIT = 0, SW_READY = 1, SW_USER_OFF = -1, SW_TIMEOUT = -2, SW_INVALID = -3 };
enum { SW_NONE = 0, SW_TURN_ON = 1, SW_TURN_OFF = 2 };
enum { SW_DIAG_CAPACITY = 1, SW_DIAG_OWNER = 2, SW_DIAG_UNKNOWN = 4,
       SW_DIAG_TRANSITION = 8, SW_DIAG_ASLEEP = 16 };
#define SMART_IDLE_MS 300000u
#define SMART_CONNECT_MS 15000u

/* Thread-safe. Acquire BEFORE starting a request, then poll readiness on a timer.
 * READY reserves the radio against policy shutdown until release; subsequent READY
 * calls keep that reservation, not a guarantee against external link loss. Disabled policy
 * preserves existing link checks; USER_OFF never turns the user's Wi-Fi back on.
 * WAIT is bounded to 15 s. A timeout stops holding demand; release its token anyway.
 * Release on every success/failure/cancel path, including thread/timer creation failure.
 * Token 0 and stale tokens are INVALID. Token storage exhaustion latches fail-open. */
unsigned smart_wifi_acquire(enum smart_wifi_owner owner);
int smart_wifi_ready(unsigned token);
void smart_wifi_release(unsigned token);
/* One aggregate boolean per named owner, not a reference count. Multiple independent
 * requests must use leases. An idle incoming server needs a hold to stay reachable. */
void smart_wifi_hold(enum smart_wifi_owner owner, int on);
unsigned smart_wifi_diagnostic(void);

/* UI-thread controller. step commits a transition under the same mutex used by acquire
 * and ready. Call stock's switch after step, then done; no other thread switches.
 * Acquire during a committed STOP sees WAIT, even before the stock link has dropped.
 * can_switch must reflect stock's module/scan/connect/test/power-off guards.
 * Manual changes call manual on that SAME UI thread; internal config writes are
 * suppressed by navigation. Workers may only acquire/ready/release/hold/diagnostic. */
int smart_wifi_step(int enabled, int can_switch, int wifi_on, int linked);
void smart_wifi_done(int wifi_on, int linked);
void smart_wifi_manual(int on);
#ifdef SMARTWIFI_HOST
void smart_wifi_test_reset(void);
#endif
#endif
