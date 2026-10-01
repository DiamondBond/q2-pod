#ifndef Q2_PEQ_H
#define Q2_PEQ_H

#ifdef PEQ_HOST
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <unistd.h>
#else
#include "peq_platform.h"
#define PEQ_ROOT "" /* host tests pass a scratch directory */
#endif

#define PEQ_BANDS 30 /* 10 per side plus 10 shared, as L/R APO files use */
#define PEQ_CHANNELS 8
#define PEQ_FILE_LIMIT 16384
#define PEQ_LINE_LIMIT 512
#define PEQ_ACTIVE PEQ_ROOT "/mnt/data/peq-active"
#define PEQ_SAVED PEQ_ROOT "/mnt/data/peq-presets"
#define PEQ_IMPORT PEQ_ROOT "/mnt/mmc/EQ"

/* Versioned disk representation: fixed-width fields, no pointers or implicit padding.
 * enabled: 0 off, 1 both channels, 2 left only, 3 right only (v1 files hold 0 or 1).
 * balance: dB, above 0 turns the left channel down, below 0 the right (v2 only). */
typedef struct { int enabled, type; double frequency, gain, q; } peq_band;
typedef struct { int count, bypass; double preamp; peq_band bands[PEQ_BANDS]; double balance; } peq_preset;
typedef struct { unsigned line; const char *reason; } peq_error;
typedef struct { double b0, b1, b2, a1, a2; } peq_coeff;
typedef struct {
    peq_coeff c[PEQ_BANDS];
    double z[PEQ_CHANNELS][PEQ_BANDS][2], gain[PEQ_CHANNELS];
    int bypass, used, only[PEQ_BANDS]; /* used: bands past it are identity with zero memory; only: 0 every channel, else channel only-1 */
} peq_engine;
typedef struct {
    peq_engine current, next, pending;
    int rate, channels, ramp, ramp_length, waiting;
} peq_dsp;

void peq_default(peq_preset *p);
int peq_valid(const peq_preset *p);
int peq_parse(const char *text, unsigned size, peq_preset *out, peq_error *error);
int peq_import_file(const char *path, peq_preset *out, peq_error *error);
int peq_load(const char *path, peq_preset *out);
void peq_load_active(peq_preset *p);
int peq_save(const char *path, const peq_preset *p, int replace);
int peq_compile(const peq_preset *p, int rate, peq_engine *out);
void peq_reset(peq_dsp *d, int rate, int channels, const peq_preset *p);
int peq_update(peq_dsp *d, const peq_preset *p);
void peq_process(peq_dsp *d, float *audio, unsigned frames);

#endif
