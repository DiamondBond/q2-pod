#include "peq.h"

/* Audited against hciplayer 9c3f8c6d… and MPlayer 1.3.0 libaf/af.h. */
typedef struct { void *audio; int len, rate, nch, format, bps; } af_data;
typedef struct af_instance {
    const void *info;
    int (*control)(struct af_instance *, int, void *);
    void (*uninit)(struct af_instance *);
    af_data *(*play)(struct af_instance *, af_data *);
    void *setup;
    af_data *data;
    struct af_instance *next, *prev;
    double delay, mul;
} af_instance;
typedef struct { peq_dsp dsp; peq_preset preset; } player_state;
_Static_assert(sizeof(af_data) == 24, "audio ABI");
_Static_assert(__builtin_offsetof(af_instance, setup) == 16, "setup ABI");
_Static_assert(__builtin_offsetof(af_instance, mul) == 40, "multiplier ABI");

static int control(af_instance *af, int command, void *arg) {
    player_state *s = af->setup;
    if (command == 0x10000100) {
        af_data *in = arg;
        if (!in || in->nch < 1 || in->nch > 8) return -2;
        if (in->rate < 8000 || in->rate > 384000 || (in->format & ~63)) return 2;
        peq_default(&s->preset);
        peq_load(PEQ_ACTIVE, &s->preset);
        peq_reset(&s->dsp, in->rate, in->nch, &s->preset);
        *af->data = *in;
        af->data->format = 0x1d;
        af->data->bps = 4;
        if (in->format != 0x1d || in->bps != 4) { *in = *af->data; return 0; }
        return 1;
    }
    if (command == 0x40001d00 || command == 0x40001d01) {
        struct { float *gain; int channel; } *ext = arg;
        if (!ext || !ext->gain || ext->channel < 0 || ext->channel >= 8) return -2;
        if (command & 1) {
            memset(ext->gain, 0, 10 * sizeof(float));
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

static af_data *play(af_instance *af, af_data *data) {
    player_state *s = af->setup;
    if (data && data->len > 0 && data->format == 0x1d && data->bps == 4 &&
        data->nch == s->dsp.channels && data->rate == s->dsp.rate &&
        !(data->len % (4 * data->nch)))
        peq_process(&s->dsp, data->audio, (unsigned)data->len / (4 * data->nch));
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
