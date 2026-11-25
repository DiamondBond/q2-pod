"""The takeover's best-effort silence: real caller, mocked child and stock audio boundaries."""
import ctypes as C
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Any

import pytest

from conftest import Files
from test_nav_loop import bt_link, hand_over, toasts

COMMAND = b'head -c 32768 /dev/zero | aplay -q -D bluealsa -t raw -f S16_LE -r 48000 -c 2'
PID = 4321


@pytest.mark.parametrize('enabled, linked, receiver, ways', [
    (0, 1, 0, [1]), (1, 0, 0, [1]), (1, 1, 1, [1]),
    (1, 1, 0, [0]), (1, 1, 0, [2]), (1, 1, 0, [0, 1]), (1, 1, 0, [1, 0]),
])
def test_handover_skips_quiet_without_the_same_connected_output(fw, power, enabled, linked, receiver, ways):
    Files(fw, {})
    bt_link(fw)
    fw.var('g_bluetoothflag', C.c_ubyte).value = enabled
    fw.var('bt_linkstatus', C.c_ubyte).value = linked
    fw.var('bt__recv_pageflag', C.c_ubyte).value = receiver
    route = iter(ways)
    fw.mock('mclGetOutputWay', lambda *_: next(route))
    hand_over(fw)
    assert not fw.calls('fw_fork') and power('ended').value == 1


@pytest.mark.parametrize('status', [0, 1 << 8, 127 << 8, 9, 14, 124 << 8])
def test_handover_waits_once_before_gain_and_exits_whatever_the_child_status(fw, st, power, status):
    Files(fw, {})
    seen = toasts(fw)
    bt_link(fw)
    st('charge_held').value = 1
    events: list[Any] = []
    fw.mock('player_stop', lambda *_: events.append('stop'))
    fw.mock('fw_fork', lambda *_: events.append('fork') or PID)
    fw.mock('btctl_transport_get_volume', lambda *_: events.append('get_volume') or 40)
    fw.mock('btctl_transport_set_volume', lambda *_: events.append('set_volume'))
    fw.mock('switch_charge_enable', lambda *_: events.append('charge'))
    fw.mock('fw_system', lambda cmd, *_: events.append(C.string_at(cmd)))
    errno = fw.fn('fw___errno_location', C.POINTER(C.c_int))()

    def wait(pid, out, options, *_):
        events.append(('wait', pid, options))
        C.c_int.from_address(out).value = status
        errno[0] = 99
        return pid
    fw.mock('fw_waitpid', wait)
    hand_over(fw)
    assert events[:6] == ['stop', 'fork', ('wait', PID, 1), 'charge', 'get_volume', 'set_volume']
    assert events[-1].endswith(b'kill -9 $PPID')
    assert len(fw.calls('fw_fork')) == 1 and len(fw.calls('fw_waitpid')) == 1
    assert [(C.c_int(c[1][0]).value, c[1][1]) for c in fw.calls('chapter_kill')] == ([(-PID, 9)] if status else [])
    assert not seen and power('ended').value == 1


@pytest.mark.parametrize('mode', ['fork', 'timeout', 'stuck', 'eintr', 'wait_error', 'no_child'])
def test_quiet_failures_are_bounded_and_still_hand_over(fw, power, mode):
    Files(fw, {})
    bt_link(fw)
    seen = toasts(fw)
    fw.mock('fw_fork', lambda *_: -1 if mode == 'fork' else PID)
    errno = fw.fn('fw___errno_location', C.POINTER(C.c_int))()
    slept, killed = [], []
    fw.mock('sleep_ms', lambda ms, *_: slept.append(ms))
    fw.mock('chapter_kill', lambda pid, sig, *_: killed.append((C.c_int(pid).value, sig)))

    def wait(pid, out, options, *_):
        if mode in ('wait_error', 'no_child', 'eintr'):
            errno[0] = {'wait_error': 5, 'no_child': 10, 'eintr': 4}[mode]
            return -1
        if killed and mode != 'stuck':
            C.c_int.from_address(out).value = 9
            return pid
        return 0
    fw.mock('fw_waitpid', wait)
    hand_over(fw)
    assert not seen and power('ended').value == 1
    assert sum(slept) <= 4000 and all(c[1][2] == 1 for c in fw.calls('fw_waitpid'))
    assert killed == ([] if mode in ('fork', 'no_child') else [(-PID, 9), (PID, 9)])
    if mode == 'fork':
        assert not fw.calls('fw_waitpid')
    if mode in ('timeout', 'stuck', 'eintr'):
        assert sum(slept) >= 3000


def test_quiet_keeps_the_callers_errno(fw):
    bt_link(fw)
    errno = fw.fn('fw___errno_location', C.POINTER(C.c_int))()
    errno[0] = 17
    def refused_fork(*_):
        errno[0] = 99
        return -1
    fw.mock('fw_fork', refused_fork)
    fw.fn('bt_handover_quiet', None, C.c_int)(1)
    assert errno[0] == 17


@pytest.mark.parametrize('mode', ['ok', 'failed', 'hung', 'shell_killed', 'exec_failed'])
def test_real_pipeline_has_finite_silence_and_cleans_up_its_process_group(tmp_path, mode):
    """Compile the real module with host calls; a fake aplay receives bytes without opening audio.
    Unlike firmware mocks this exercises fork, stock command arguments, session setup, wait and kill."""
    header = tmp_path/'host.h'
    header.write_text('''
#define Q2_NAVIGATION_H
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <sys/wait.h>
#define FF_GRACE_MS 1000
#define child_exit _exit
#define chapter_kill kill
#define execl handover_execl
extern int g_bluetoothflag, bt_linkstatus, bt__recv_pageflag;
int mclGetOutputWay(void), handover_execl(const char *, const char *, ...);
void child_oom_first(void), sleep_ms(unsigned), bt_handover_quiet(int);
''')
    harness = tmp_path/'main.c'
    harness.write_text('''
int g_bluetoothflag = 1, bt_linkstatus = 1, bt__recv_pageflag;
int mclGetOutputWay(void) { return 1; }
void child_oom_first(void) {}
void sleep_ms(unsigned ms) { usleep(ms * 1000); }
int handover_execl(const char *file, const char *arg, ...) {
    char *argv[6] = {(char *)arg};
    va_list ap;
    va_start(ap, arg);
    for (int i = 1; i < 5; ++i) argv[i] = va_arg(ap, char *);
    va_end(ap);
    FILE *f = fopen(getenv("PID_FILE"), "w");
    if (!f) _exit(126);
    fprintf(f, "%d", getpid()); fclose(f);
    f = fopen(getenv("EXEC_FILE"), "w");
    if (!f) _exit(126);
    fprintf(f, "%s\\n%s\\n%s\\n%s\\n%s\\n%s\\n", file, arg, argv[1], argv[2], argv[3], argv[4] ? "BAD" : "NULL");
    fclose(f);
    if (!strcmp(getenv("MODE"), "exec_failed")) { errno = ENOENT; return -1; }
    return execv(file, argv);
}
int main(void) { errno = 17; bt_handover_quiet(1); return errno != 17; }
''')
    executable = tmp_path/'handover'
    source = Path(__file__).resolve().parents[2]/'patch/bt_handover.c'
    flags = ['-fsanitize=address,undefined', '-fno-sanitize-recover=undefined', '-fno-omit-frame-pointer'] if os.environ.get('Q2_FW_SANITIZE') else []
    subprocess.run(['cc', '-O0', *flags, '-include', str(header), str(source), str(harness), '-o', str(executable)], check=True)
    aplay = tmp_path/'aplay'
    aplay.write_text('''#!/bin/sh
printf '%s\n' "$*" > "$ARGS_FILE"
cat > "$DATA_FILE"
case "$MODE" in
  failed) exit 1 ;;
  hung) exec sleep 30 ;;
  shell_killed) kill -KILL "$PPID"; exec sleep 30 ;;
esac
''')
    aplay.chmod(0o755)
    pid_file, args_file, data_file, exec_file = (tmp_path/n for n in ('pid', 'args', 'data', 'exec'))
    env = dict(os.environ, PATH=str(tmp_path)+os.pathsep+os.environ['PATH'], MODE=mode,
               PID_FILE=str(pid_file), ARGS_FILE=str(args_file), DATA_FILE=str(data_file), EXEC_FILE=str(exec_file))
    start = time.monotonic()
    try:
        result = subprocess.run([str(executable)], env=env, timeout=6, capture_output=True)
        elapsed = time.monotonic() - start
        assert result.returncode == 0, result.stderr
        assert exec_file.read_text().splitlines() == ['/usr/bin/setsid', 'setsid', '/bin/sh', '-c', COMMAND.decode(), 'NULL']
        if mode == 'exec_failed':
            assert not data_file.exists() and not args_file.exists()
            assert not Path('/proc', pid_file.read_text()).exists()  # real _exit(127), reaped
        else:
            assert data_file.read_bytes() == bytes(32768)
            assert args_file.read_text().strip() == '-q -D bluealsa -t raw -f S16_LE -r 48000 -c 2'
        if mode == 'hung':
            assert 2.8 <= elapsed < 5
        group = int(pid_file.read_text())
        # A killed grandchild can await container init's reap, but none may still be running.
        alive = []
        for p in Path('/proc').glob('[0-9]*/stat'):
            try:
                fields = p.read_text().rsplit(')', 1)[1].split()
                if int(fields[2]) == group and fields[0] != 'Z': alive.append(p)
            except (FileNotFoundError, ProcessLookupError):
                pass
        assert not alive
    finally:
        if pid_file.exists():
            try:
                os.killpg(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
