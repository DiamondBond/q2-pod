#!/usr/bin/env python3
"""Execute the actual Smart Wi-Fi C policy, including concurrent acquire/STOP races."""
import ctypes as C
import pathlib
import subprocess
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="q2-smartwifi-") as work:
    d = pathlib.Path(work)
    (d / "clock.c").write_text("""
#include <stdatomic.h>
static _Atomic unsigned tick;
unsigned time_now_ms(void) { return atomic_load(&tick); }
void test_clock(unsigned value) { atomic_store(&tick, value); }
""")
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                    "-pthread", "-DSMARTWIFI_HOST", str(ROOT / "patch/smartwifi.c"),
                    str(d / "clock.c"), "-o", str(d / "policy.so")], check=True)
    q = C.CDLL(str(d / "policy.so"))
    for name, args, result in (
        ("smart_wifi_acquire", [C.c_int], C.c_uint),
        ("smart_wifi_ready", [C.c_uint], C.c_int),
        ("smart_wifi_release", [C.c_uint], None),
        ("smart_wifi_hold", [C.c_int, C.c_int], None),
        ("smart_wifi_step", [C.c_int] * 4, C.c_int),
        ("smart_wifi_done", [C.c_int] * 2, None),
        ("smart_wifi_manual", [C.c_int], None),
        ("smart_wifi_diagnostic", [], C.c_uint),
        ("smart_wifi_test_reset", [], None),
        ("test_clock", [C.c_uint], None)):
        f = getattr(q, name)
        f.argtypes, f.restype = args, result
    checks = 0
    def check(value, message):
        global checks
        assert value, message
        checks += 1
    def reset(enabled=1, on=1, linked=1, start=10):
        q.smart_wifi_test_reset()
        q.test_clock(start)
        check(q.smart_wifi_step(enabled, 1, on, linked) == 0, "initialization never toggles")
    def idle():
        q.test_clock(300010)
        check(q.smart_wifi_step(1, 1, 1, 1) == 2, "idle commits OFF")
    def asleep():
        reset()
        idle()
        q.smart_wifi_done(0, 0)

    # Default policy is a passthrough even if an action precedes the first UI loop.
    q.smart_wifi_test_reset()
    q.test_clock(1)
    t = q.smart_wifi_acquire(0)
    check(q.smart_wifi_ready(t) == 1, "before first poll preserves old entry")
    q.smart_wifi_release(t)
    reset(enabled=0)
    q.test_clock(2000000)
    check(q.smart_wifi_step(0, 1, 1, 1) == 0, "disabled never idles")
    reset(on=0, linked=0)
    t = q.smart_wifi_acquire(0)
    check(q.smart_wifi_ready(t) == -1, "manual off remains off")
    check(q.smart_wifi_step(1, 1, 0, 0) == 0, "demand cannot override manual off")
    q.smart_wifi_release(t)

    # Last release, not acquire time, starts the full idle interval.
    reset()
    a, b = q.smart_wifi_acquire(5), q.smart_wifi_acquire(5)
    check(a != b, "same owner independent requests get distinct tokens")
    check(q.smart_wifi_ready(a) == q.smart_wifi_ready(b) == 1, "both reserve readiness")
    q.test_clock(900000)
    check(q.smart_wifi_step(1, 1, 1, 1) == 0, "live lease never expires during work")
    q.smart_wifi_release(a)
    check(q.smart_wifi_step(1, 1, 1, 1) == 0, "other lease keeps radio")
    q.smart_wifi_release(b)
    q.test_clock(1199999)
    check(q.smart_wifi_step(1, 1, 1, 1) == 0, "release grace")
    q.test_clock(1200000)
    check(q.smart_wifi_step(1, 1, 1, 1) == 2, "full release grace expires")

    # A committed stop and acquire/ready use one serialization point.
    asleep()
    t = q.smart_wifi_acquire(5)
    check(q.smart_wifi_ready(t) == 0, "sleeping request waits")
    check(q.smart_wifi_step(1, 1, 0, 0) == 1, "demand wakes owned off")
    check(q.smart_wifi_ready(t) == 0, "wake not yet complete")
    q.smart_wifi_done(1, 0)
    check(q.smart_wifi_ready(t) == 0, "association still pending")
    q.test_clock(300500)
    check(q.smart_wifi_step(1, 1, 1, 1) == 0, "association snapshot")
    check(q.smart_wifi_ready(t) == 1, "associated ready")
    q.smart_wifi_release(t)
    check(q.smart_wifi_ready(t) == -3, "released token invalid")

    # Timeout, late completion, manual cancellation and disabled restoration.
    asleep()
    t = q.smart_wifi_acquire(0)
    q.test_clock(315010)
    check(q.smart_wifi_ready(t) == -2, "wake deadline exact")
    check(q.smart_wifi_step(1, 0, 0, 0) == 0, "timed out demand no longer holds")
    q.smart_wifi_release(t)
    check(q.smart_wifi_step(0, 1, 0, 0) == 1, "disable restores policy-owned off")
    q.smart_wifi_done(1, 1)
    reset()
    t = q.smart_wifi_acquire(2)
    check(q.smart_wifi_ready(t) == 1, "active request")
    q.smart_wifi_manual(0)
    check(q.smart_wifi_ready(t) == -1, "manual off cancels request")
    q.smart_wifi_manual(1)
    q.smart_wifi_step(1, 1, 1, 1)
    check(q.smart_wifi_ready(t) == -1, "manual on never revives cancelled work")
    q.smart_wifi_release(t)

    # Every conservative hold inhibits sleep; clearing it restarts grace.
    for owner in range(12):
        reset()
        q.smart_wifi_hold(owner, 1)
        q.test_clock(400000)
        check(q.smart_wifi_step(1, 1, 1, 1) == 0, "named hold")
        q.smart_wifi_hold(owner, 0)
        q.test_clock(699999)
        check(q.smart_wifi_step(1, 1, 1, 1) == 0, "hold release grace")
        q.test_clock(700000)
        check(q.smart_wifi_step(1, 1, 1, 1) == 2, "hold release expires")
    reset()
    q.smart_wifi_hold(11, 1)
    check(q.smart_wifi_diagnostic() & 4, "unknown owner visible")
    q.smart_wifi_hold(11, 0)

    # Storage/owner faults fail open and are visible, but never override manual OFF.
    reset()
    tokens = [q.smart_wifi_acquire(0) for _ in range(32)]
    check(len(set(tokens)) == 32 and all(tokens), "lease capacity")
    check(q.smart_wifi_acquire(0) == 0, "capacity failure reported")
    check(q.smart_wifi_diagnostic() & 1, "capacity fault visible")
    for t in tokens: q.smart_wifi_release(t)
    q.test_clock(1000000)
    check(q.smart_wifi_step(1, 1, 1, 1) == 0, "capacity fault prevents lost-demand stop")
    q.smart_wifi_manual(0)
    check(q.smart_wifi_step(1, 1, 0, 0) == 0, "fault respects manual off")
    reset()
    t = q.smart_wifi_acquire(999)
    check(q.smart_wifi_diagnostic() & 2, "invalid owner fault visible")
    q.smart_wifi_release(t)
    q.test_clock(1000000)
    check(q.smart_wifi_step(1, 1, 1, 1) == 0, "invalid owner fails open")

    # Stale handles never release a reused slot, and uint32 clock wrap is safe.
    reset()
    old = q.smart_wifi_acquire(0)
    q.smart_wifi_release(old)
    new = q.smart_wifi_acquire(0)
    q.smart_wifi_release(old)
    check(q.smart_wifi_ready(new) == 1, "stale release cannot clear reused slot")
    q.smart_wifi_release(new)
    reset(start=0xfffffff0)
    q.test_clock((0xfffffff0 + 299999) & 0xffffffff)
    check(q.smart_wifi_step(1, 1, 1, 1) == 0, "wrap before threshold")
    q.test_clock((0xfffffff0 + 300000) & 0xffffffff)
    check(q.smart_wifi_step(1, 1, 1, 1) == 2, "wrap at threshold")
    reset()
    q.test_clock(300010)
    check(q.smart_wifi_step(1, 0, 1, 1) == 0, "stock guard prevents toggle")

    # Real parallel callers start after OFF has been committed but while the old
    # hardware snapshot is still connected. None may be told READY on that snapshot.
    for iteration in range(64):
        reset()
        idle()
        barrier = threading.Barrier(9)
        observed = []
        def race():
            barrier.wait()
            token = q.smart_wifi_acquire(5)
            observed.append((token, q.smart_wifi_ready(token)))
        workers = [threading.Thread(target=race) for _ in range(8)]
        for w in workers: w.start()
        barrier.wait()
        for w in workers: w.join()
        check(len(observed) == 8 and all(state == 0 for _, state in observed),
              "concurrent committed STOP cannot report stale-ready")
        q.smart_wifi_done(0, 0)
        check(q.smart_wifi_step(1, 1, 0, 0) == 1, "acquisitions survive STOP")
        q.smart_wifi_done(1, 1)
        for token, _ in observed:
            check(q.smart_wifi_ready(token) == 1, "all owners ready after wake")
            q.smart_wifi_release(token)
    print(f"Smart Wi-Fi policy: {checks} checks passed; 512 concurrent STOP acquisitions")
