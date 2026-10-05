#include "peq.h"

_Static_assert(sizeof(af_data) == 24, "audio ABI");
_Static_assert(__builtin_offsetof(af_instance, setup) == 16, "setup ABI");
_Static_assert(__builtin_offsetof(af_instance, mul) == 40, "multiplier ABI");

/* DSD (the vendor's dsdiff driver: dsf, dff, SACD iso; or FFmpeg's ffdsd*) reaches the chain as integer PCM,
 * possibly DoP, whose bits must arrive unchanged: detach (2); the player re-adds the filter at the next file.
 * Codec lookup: docs/internals.md. */
#ifdef PEQ_HOST
extern char *peq_mpctx;
#define MPCTX peq_mpctx
#else
#define MPCTX (*(char *volatile *)0xaf9e30u)
#endif
static int dsd(void) {
    char *mp = MPCTX, *sh = mp ? *(char **)(mp + 0x2c) : 0, *codec = sh ? *(char **)(sh + 4) : 0;
    if (!codec) return 0;
    const char *name = *(char **)(codec + 0x3d0), *drv = *(char **)(codec + 0x3e0);
    return (drv && !strcmp(drv, "dsdiff")) || (name && strlen(name) >= 5 && !memcmp(name, "ffdsd", 5));
}

static int control(af_instance *af, int command, void *arg) {
    player_state *s = af->setup;
    if (command == 0x10000100) {
        af_data *in = arg;
        if (!in || in->nch < 1 || in->nch > PEQ_CHANNELS) return -2;
        if (in->rate < 8000 || in->rate > 384000 || (in->format & ~63) || dsd()) return 2;
        peq_load_active(&s->preset);
        peq_reset(&s->dsp, in->rate, in->nch, &s->preset);
        *af->data = *in;
        af->data->format = 0x1d;
        af->data->bps = 4;
        if (in->format != 0x1d || in->bps != 4) { *in = *af->data; return 0; }
        return 1;
    }
    if (command == 0x40001d00 || command == 0x40001d01) {
        struct { float *gain; int channel; } *ext = arg;
        if (!ext || !ext->gain || ext->channel < 0 || ext->channel >= PEQ_CHANNELS) return -2;
        if (command & 1) {
            memset(ext->gain, 0, 10 * sizeof(float)); /* stock's ten graphic bands */
        } else if (!ext->channel) {
            peq_preset p;
            /* Control executes on the playback loop, outside the PCM callback. */
            if (peq_load(PEQ_ACTIVE, &p) && memcmp(&p, &s->preset, sizeof(p)) &&
                peq_update(&s->dsp, &p)) s->preset = p;
        }
        return 1; /* Stock graphic gains never reach the replacement DSP. */
    }
    if (command == 0x20000300) return 1;
    return -1;
}

/* The visualizer's tap (peq.h): what plays, after the filter, while the visualizer shows. The file
 * appears when it first opens; until then it is looked for once a second of audio. Counting frames,
 * not time, keeps an idle tap to a compare per block. */
static void tap(const float *a, unsigned frames, int nch, int rate) {
    static vis_tap *t;
    static unsigned wait = ~0u, seen, idle;
    if (!t) {
        if (wait < (unsigned)rate) {
            wait += frames;
            return;
        }
        wait = 0;
        int fd = open(VIS_FILE, 2); /* O_RDWR */
        if (fd >= 0) {
            void *p = mmap64(0, sizeof(vis_tap), 3, 1, fd, 0); /* PROT_READ | PROT_WRITE, MAP_SHARED */
            close(fd);
            if (p != (void *)-1) t = p;
        }
    }
    if (!t) return;
    if (t->want != seen) { /* watched again after a pause: no stale audio half a second back */
        if (idle > (unsigned)rate) memset(t->ring, 0, sizeof t->ring);
        seen = t->want, idle = 0;
    }
    else if (idle > (unsigned)rate || (idle += frames) > (unsigned)rate) return; /* nobody watching */
    long long now = now_ns();
    unsigned step = rate > 48000 ? (unsigned)rate / 44100 : 1, seq = t->seq;
    for (unsigned i = 0; i < frames; i += step, ++seq) {
        t->ring[seq % VIS_RING][0] = a[i * nch];
        t->ring[seq % VIS_RING][1] = a[i * nch + (nch > 1)];
    }
    t->rate = (unsigned)rate / step;
    t->stamp = now;
    __asm__ volatile("" ::: "memory"); /* the frames before seq; the reader tolerates a torn one */
    t->seq = seq;
}

static af_data *play(af_instance *af, af_data *data) {
    player_state *s = af->setup;
    if (data && data->len > 0 && data->format == 0x1d && data->bps == 4 &&
        data->nch == s->dsp.channels && data->rate == s->dsp.rate &&
        !(data->len % (4 * data->nch))) {
        unsigned frames = (unsigned)data->len / (4 * data->nch);
        peq_process(&s->dsp, data->audio, frames);
        tap(data->audio, frames, data->nch, data->rate);
    }
    return data;
}

static void uninit(af_instance *af) {
    free(af->data);
    free(af->setup);
    af->data = 0;
    af->setup = 0;
}

int peq_open(af_instance *af) {
    af->control = control;
    af->uninit = uninit;
    af->play = play;
    af->mul = 1;
    af->delay = 0;
    af->data = calloc(1, sizeof(af_data));
    af->setup = calloc(1, sizeof(player_state));
    if (!af->data || !af->setup) return -2; /* af_create calls uninit on failure. */
    return 1;
}

/* Exact VBR MP3 seeking (docs/internals.md#large-mp3s). A Xing header in the first frame h (n bytes)
 * gives the track length and a 100-point table of how far into the file each 1% of it starts. For
 * second t, *frac gets that place as a fraction of the file after the frame, read off the table
 * and interpolated between its points (t within 0..length); 0 without a VBR header that has both. */
int mp3_toc(const unsigned char *h, unsigned n, double t, double *frac, double *length) {
    static const int rates[3] = { 44100, 48000, 32000 };
    if (n < 4) return 0;
    unsigned head = (unsigned)h[0] << 24 | h[1] << 16 | h[2] << 8 | h[3];
    unsigned version = head >> 19 & 3, rate = head >> 10 & 3, mono = (head >> 6 & 3) == 3;
    if (head >> 21 != 0x7ff || version == 1 || (head >> 17 & 3) != 1 || rate == 3) return 0;
    unsigned at = 4 + (version == 3 ? (mono ? 17 : 32) : (mono ? 9 : 17));
    if (n < at + 8 + 4 + 4 + 100 || memcmp(h + at, "Xing", 4)) return 0; /* "Info": CBR, already exact */
    const unsigned char *p = h + at + 4;
    unsigned flags = p[3];
    if ((flags & 5) != 5) return 0;
    p += 4;
    unsigned frames = (unsigned)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3];
    p += 4 + (flags & 2 ? 4 : 0);
    if (!frames) return 0;
    *length = frames * (version == 3 ? 1152.0 : 576.0) / (rates[rate] >> (version == 3 ? 0 : version == 2 ? 1 : 2));
    double pct = t * 100 / *length;
    int i = pct >= 100 ? 99 : (int)pct;
    double a = p[i], b = i < 99 ? p[i + 1] : 256;
    *frac = (a + (b - a) * (pct - i)) / 256;
    return 1;
}

#ifndef PEQ_HOST
/* demux_audio_seek (0x48d1ac, the audio demuxer's seek slot). For an MP3 (priv->frmt 1, priv at
 * demuxer+0xc70) without hr_mp3_seek, stock lands at movi_start + seconds * average bytes per
 * second and sets priv->next_pts (a double at +8) from that place. With a Xing table this seeks to
 * the table's place for the second instead, as a fraction of movi_start..movi_end (stock's
 * SEEK_ABSOLUTE | SEEK_FACTOR), then sets next_pts to the second itself. Each seek reads the
 * first frame through the stream's fd (stream_t +0x14) and puts its offset back, since stock's
 * stream_seek may reuse its buffer without seeking. STOCK_SEEK is SEEK_SLOT's pinned stock value
 * in tools/peq.py. */
#define STOCK_SEEK ((void (*)(void *, float, float, int))0x48d1acu)
#define HR_MP3_SEEK (*(volatile int *)0xb152b8u)
#define AT(p, o, type) (*(type *)((char *)(p) + (o)))
void mp3_seek(void *demuxer, float rel, float delay, int flags) {
    unsigned char h[192];
    void *priv = AT(demuxer, 0xc70, void *), *s = AT(demuxer, 0x20, void *);
    long long movi_start = AT(demuxer, 0x10, long long), movi_end = AT(demuxer, 0x18, long long);
    double frac, length;
    if (priv && AT(priv, 0, int) == 1 && !HR_MP3_SEEK && !(flags & 2) && s && movi_end > movi_start) {
        int fd = AT(s, 0x14, int), got = 0;
        long long back = lseek64(fd, 0, 1);
        if (back >= 0) {
            if (lseek64(fd, movi_start, 0) == movi_start) got = read(fd, h, sizeof h);
            lseek64(fd, back, 0);
        }
        double t = flags & 1 ? rel : AT(priv, 8, double) + rel;
        if (t < 0) t = 0;
        if (got > 0 && mp3_toc(h, (unsigned)got, t, &frac, &length)) {
            if (t > length) t = length;
            STOCK_SEEK(demuxer, (float)frac, delay, 3);
            AT(priv, 8, double) = t;
            return;
        }
    }
    STOCK_SEEK(demuxer, rel, delay, flags);
}
#endif
