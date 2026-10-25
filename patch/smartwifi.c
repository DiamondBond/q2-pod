/* Network-demand policy. Stock/UI integration lives in navigation.c. No hardware
 * writes here: host tests execute exactly this state machine with a fake clock. */
#include "smartwifi.h"
#ifdef SMARTWIFI_HOST
#include <pthread.h>
#include <string.h>
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
#define LOCK() pthread_mutex_lock(&lock)
#define UNLOCK() pthread_mutex_unlock(&lock)
#else
#include "peq.h"
static unsigned lock[16] __attribute__((section(".scratch")));
#define LOCK() pthread_mutex_lock(lock)
#define UNLOCK() pthread_mutex_unlock(lock)
#endif
#ifdef SMARTWIFI_HOST
extern unsigned time_now_ms(void);
#endif
#define SLOTS 32
typedef struct {
    unsigned token, at;
    int owner, active, error;
} lease;
static struct {
    lease leases[SLOTS];
    unsigned generation, hold, fault, busy_at;
    int initialized, enabled, manual_on, wifi_on, linked, owned_off, transition;
} sw __attribute__((section(".scratch")));

static lease *find(unsigned token) {
    if (!token) return 0;
    unsigned slot = (token & 63u) - 1u;
    return slot < SLOTS && sw.leases[slot].token == token ? &sw.leases[slot] : 0;
}
static int owner_ok(int owner) {
    if (owner >= 0 && owner < SW_OWNER_COUNT) return 1;
    sw.fault |= SW_DIAG_OWNER;
    return 0;
}
static int demand(unsigned now) {
    int needed = sw.hold || sw.fault;
    for (unsigned i = 0; i < SLOTS; ++i) {
        lease *p = &sw.leases[i];
        if (!p->token || p->error) continue;
        if (!p->active && now - p->at >= SMART_CONNECT_MS) p->error = SW_TIMEOUT;
        else needed = 1;
    }
    return needed;
}
unsigned smart_wifi_acquire(enum smart_wifi_owner owner) {
    unsigned token = 0, now = time_now_ms();
    LOCK();
    if (!owner_ok(owner)) owner = SW_UNKNOWN;
    for (unsigned i = 0; i < SLOTS; ++i) {
        lease *p = &sw.leases[i];
        if (p->token) continue;
        sw.generation = (sw.generation + 1u) & 0x03ffffffu;
        if (!sw.generation) sw.generation = 1;
        token = sw.generation << 6 | (i + 1u);
        *p = (lease){ .token = token, .at = now, .owner = owner };
        sw.busy_at = now;
        break;
    }
    if (!token) sw.fault |= SW_DIAG_CAPACITY;
    UNLOCK();
    return token;
}
int smart_wifi_ready(unsigned token) {
    unsigned now = time_now_ms();
    int result = SW_WAIT;
    LOCK();
    lease *p = find(token);
    if (!p) result = SW_INVALID;
    else if (p->error) result = p->error;
    else if (sw.initialized && !sw.manual_on) result = p->error = SW_USER_OFF;
    else if (!p->active && now - p->at >= SMART_CONNECT_MS)
        result = p->error = SW_TIMEOUT;
    else if (!sw.transition && (!sw.initialized || p->active ||
             !sw.enabled || (sw.wifi_on && !sw.owned_off && sw.linked))) {
        p->active = 1;
        result = SW_READY;
    }
    UNLOCK();
    return result;
}
void smart_wifi_release(unsigned token) {
    LOCK();
    lease *p = find(token);
    if (p) {
        p->token = 0;
        sw.busy_at = time_now_ms(); /* a full idle interval after the final release */
    }
    UNLOCK();
}
void smart_wifi_hold(enum smart_wifi_owner owner, int on) {
    LOCK();
    if (owner_ok(owner)) {
        unsigned bit = 1u << owner;
        if (on) sw.hold |= bit;
        else if (sw.hold & bit) sw.hold &= ~bit, sw.busy_at = time_now_ms();
    }
    UNLOCK();
}
int smart_wifi_step(int enabled, int can_switch, int wifi_on, int linked) {
    unsigned now = time_now_ms();
    int action = SW_NONE;
    LOCK();
    if (sw.transition) { UNLOCK(); return SW_NONE; }
    if (!sw.initialized) {
        sw.initialized = 1;
        sw.manual_on = !!wifi_on;
        sw.busy_at = now;
    }
    if (!!enabled != sw.enabled || (linked && !sw.linked)) sw.busy_at = now;
    sw.enabled = !!enabled;
    sw.wifi_on = !!wifi_on;
    sw.linked = !!linked;
    /* Any unowned off state is manual/stock-owned: never auto-enable it. */
    if (!wifi_on && !sw.owned_off) sw.manual_on = 0;
    if (wifi_on && !sw.owned_off) sw.manual_on = 1;
    int needed = demand(now);
    if (needed) sw.busy_at = now;
    if (can_switch && sw.manual_on) {
        if (sw.owned_off && (!enabled || needed)) action = SW_TURN_ON;
        else if (enabled && !sw.owned_off && wifi_on && !needed &&
                 now - sw.busy_at >= SMART_IDLE_MS) action = SW_TURN_OFF;
    }
    sw.transition = action;
    UNLOCK();
    return action;
}
void smart_wifi_done(int wifi_on, int linked) {
    LOCK();
    if (sw.transition) {
        /* Only a successful policy OFF owns the off state. A failed switch leaves
         * the radio alone and waits a full idle interval before another attempt. */
        if (sw.transition == SW_TURN_OFF) sw.owned_off = !wifi_on;
        else if (wifi_on) sw.owned_off = 0;
        sw.wifi_on = !!wifi_on;
        sw.linked = !!linked;
        sw.transition = 0;
        sw.busy_at = time_now_ms();
    }
    UNLOCK();
}
void smart_wifi_manual(int on) {
    LOCK();
    sw.initialized = 1;
    sw.manual_on = sw.wifi_on = !!on;
    sw.owned_off = 0;
    sw.linked = 0;
    sw.busy_at = time_now_ms();
    /* Never revive a pending request after the user explicitly cancels Wi-Fi. */
    if (!on)
        for (unsigned i = 0; i < SLOTS; ++i)
            if (sw.leases[i].token) sw.leases[i].error = SW_USER_OFF;
    UNLOCK();
}
unsigned smart_wifi_diagnostic(void) {
    LOCK();
    unsigned flags = sw.fault;
    if (sw.transition) flags |= SW_DIAG_TRANSITION;
    if (sw.owned_off) flags |= SW_DIAG_ASLEEP;
    if (sw.hold & (1u << SW_UNKNOWN)) flags |= SW_DIAG_UNKNOWN;
    for (unsigned i = 0; i < SLOTS; ++i)
        if (sw.leases[i].token && !sw.leases[i].error && sw.leases[i].owner == SW_UNKNOWN)
            flags |= SW_DIAG_UNKNOWN;
    UNLOCK();
    return flags;
}
#ifdef SMARTWIFI_HOST
void smart_wifi_test_reset(void) {
    LOCK();
    memset(&sw, 0, sizeof sw);
    UNLOCK();
}
#endif
