#!/usr/bin/env python3
"""Actual publisher position math with deterministic absolute monotonic timestamps."""
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
C = r'''
#include <time.h>
#include <assert.h>
static unsigned long long ms;
static int test_clock(clockid_t which,struct timespec *ts){
    assert(which==CLOCK_MONOTONIC);ts->tv_sec=ms/1000;ts->tv_nsec=(ms%1000)*1000000;return 0;
}
#define clock_gettime test_clock
#define main publisher_main
#include "mpris.c"
#undef main
int main(void){
    /* Toolkit-relative origin 123ms is deliberately absent from the wire stamp. */
    ms=9000123;
    char text[256];
    snprintf(text,sizeof text,"v=1\nstatus=Playing\nnow=%u\nposition=5000\nduration=200000\ngen=1\n",(unsigned)(ms-3000));
    assert(bm_parse(text));rec_read_at=ms;assert(position_now()==8000000);
    /* A new helper reading an old Playing record uses the producer stamp, not receipt time. */
    rec_read_at=ms+2000;ms+=2000;assert(position_now()==10000000);
    snprintf(rec.status,sizeof rec.status,"Paused");ms+=9000;assert(position_now()==5000000);
    snprintf(rec.status,sizeof rec.status,"Playing");
    rec.written_ms=0xfffffff0u;ms=0x100000010ULL;assert(position_now()==5032000);
    rec.length_us=5010000;assert(position_now()==5010000);
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='q2-btclock-') as tmp:
    path = pathlib.Path(tmp)
    (path/'clock.c').write_text(C)
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'dbus-1'], text=True).split()
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-I'+str(ROOT/'patch'), str(path/'clock.c'), '-o', str(path/'clock'), *flags], check=True)
    subprocess.run([str(path/'clock')], check=True)
print('Publisher absolute-clock old Playing/paused/wrap/duration cases passed.')
