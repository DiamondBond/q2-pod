#!/usr/bin/env python3
"""Host check of Q2's actual PCM writer recovery loop (sibling Rockbox checkout)."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]/'rockbox'
source = (root/'firmware/target/hosted/pcm-alsa.c').read_text()
writer = source[source.index('static int writer_reopen(void)'):source.index('static void writer_start(void)')]
with tempfile.TemporaryDirectory() as directory:
    tmp = Path(directory)
    (tmp/'test.c').write_text(r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#define SHANLING_Q2
#define HZ 100
#define WRITER_POLL_US 2000
#define TIME_BEFORE(a,b) ((long)(a) - (long)(b) < 0)
#define logf(...) ((void)0)
#define SND_PCM_STREAM_PLAYBACK 0
#define SND_PCM_STATE_XRUN 1
#define SND_PCM_STATE_DISCONNECTED 2
#define SND_PCM_STATE_DRAINING 3
#define SND_PCM_STATE_SETUP 4
#define SND_PCM_STATE_PREPARED 5
#define SND_PCM_STATE_RUNNING 6
typedef int snd_pcm_t;
typedef int snd_pcm_state_t;
static int pcm, pcm_mtx, xruns, closed, opened, checks, preinits, params;
static int state = SND_PCM_STATE_RUNNING;
static long current_tick;
static bool writer_run, dma_playing = true, changed;
static snd_pcm_t *handle = &pcm;
static const char *current_alsa_device = "dac", *playback_dev = "dac";
static int last_sample_rate = 44100;
static int pthread_mutex_lock(int *m) { (void)m; return 0; }
static int pthread_mutex_unlock(int *m) { (void)m; return 0; }
static int snd_pcm_close(snd_pcm_t *p) { assert(p == &pcm); closed++; return 0; }
static int snd_pcm_open(snd_pcm_t **p, const char *d, int stream, int flags)
{ (void)d; (void)stream; (void)flags; *p = &pcm; opened++; return 0; }
static void audiohw_preinit(void) { preinits++; playback_dev = "new output"; }
static void set_hwparams(snd_pcm_t *p, int rate) { assert(p == &pcm && rate == 44100); params++; }
static void set_swparams(snd_pcm_t *p) { assert(p == &pcm); }
static bool audiohw_output_changed(void) { checks++; return changed; }
static int snd_pcm_state(snd_pcm_t *p) { assert(p == &pcm); return state; }
static int snd_pcm_recover(snd_pcm_t *p, int err, int silent)
{ (void)p; (void)err; (void)silent; return -ENODEV; }
static int snd_pcm_start(snd_pcm_t *p) { (void)p; return 0; }
static int playback_fill(snd_pcm_t *p) { (void)p; return 0; }
static int usleep(unsigned delay)
{ (void)delay; if (++current_tick >= 250) writer_run = false; return 0; }
''' + writer + r'''
int main(void)
{
    writer_run = true;
    writer_main(NULL);
    assert(checks == 3 && opened == 0); /* 0, 1 and 2 seconds */
    current_tick = 249;
    changed = writer_run = true;
    writer_main(NULL);
    assert(opened == 1 && closed == 1 && preinits == 1 && params == 1);
    assert(dma_playing && last_sample_rate == 44100 && handle == &pcm);
    changed = false;
    state = SND_PCM_STATE_DISCONNECTED;
    current_tick = 249;
    writer_run = true;
    writer_main(NULL);
    assert(opened == 2 && closed == 2 && preinits == 2 && params == 2);
    assert(dma_playing && last_sample_rate == 44100);
}
''')
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(tmp/'test.c'), '-o', str(tmp/'test')], check=True)
    subprocess.run([str(tmp/'test')], check=True)
print('PCM writer: one-second output polling, reopen and disconnect recovery passed.')
