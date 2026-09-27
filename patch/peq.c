#include "peq.h"

static int between(double x, double lo, double hi) {
    return PEQ_FINITE(x) && x >= lo && x <= hi;
}

void peq_default(peq_preset *p) {
    static const double frequencies[10] = {31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000};
    memset(p, 0, sizeof(*p));
    p->count = 10;
    p->bypass = 1;
    for (int i = 0; i < 10; ++i) {
        p->bands[i].frequency = frequencies[i];
        p->bands[i].q = 0.7071067811865476;
    }
}

static int valid_band(const peq_band *b) {
    return (b->enabled == 0 || b->enabled == 1) && b->type >= 0 && b->type <= 2 &&
           between(b->frequency, 20, 20000) && between(b->gain, -24, 24) && between(b->q, 0.1, 10);
}

int peq_valid(const peq_preset *p) {
    if (!p || p->count < 0 || p->count > 10 || (p->bypass != 0 && p->bypass != 1) ||
        !between(p->preamp, -60, 24)) return 0;
    for (int i = 0; i < p->count; ++i) if (!valid_band(&p->bands[i])) return 0;
    return 1;
}

static int error_at(peq_error *e, unsigned line, const char *reason) {
    if (e) { e->line = line; e->reason = reason; }
    return 0;
}

/* Decimal only; no locale, hex floats, expressions, NaN or infinity. */
static int number(const char *s, double *out) {
    double v = 0, scale = 1;
    int sign = 1, digits = 0, exponent = 0, esign = 1;
    if (*s == '+' || *s == '-') { if (*s == '-') sign = -1; ++s; }
    while (*s >= '0' && *s <= '9') { v = v * 10 + *s++ - '0'; ++digits; }
    if (*s == '.') {
        ++s;
        while (*s >= '0' && *s <= '9') { scale *= 0.1; v += (*s++ - '0') * scale; ++digits; }
    }
    if (!digits) return 0;
    if (*s == 'e' || *s == 'E') {
        ++s;
        if (*s == '+' || *s == '-') { if (*s == '-') esign = -1; ++s; }
        if (*s < '0' || *s > '9') return 0;
        while (*s >= '0' && *s <= '9') {
            exponent = exponent * 10 + *s++ - '0';
            if (exponent > 308) return 0;
        }
    }
    if (*s) return 0;
    while (exponent--) v *= esign < 0 ? 0.1 : 10;
    *out = sign * v;
    return PEQ_FINITE(*out);
}

int peq_parse(const char *text, unsigned size, peq_preset *out, peq_error *error) {
    peq_preset p;
    peq_default(&p);
    p.count = 0;
    p.bypass = 0;
    unsigned pos = 0, line = 0, preamp_line = 1;
    if (size > PEQ_FILE_LIMIT) return error_at(error, 1, "file exceeds 16384 bytes");
    if (size >= 3 && (unsigned char)text[0] == 239 && (unsigned char)text[1] == 187 &&
        (unsigned char)text[2] == 191) pos = 3;
    while (pos < size) {
        char buf[PEQ_LINE_LIMIT + 1], *t[16];
        unsigned length = 0;
        ++line;
        while (pos < size && text[pos] != '\n') {
            if (length == PEQ_LINE_LIMIT) return error_at(error, line, "line exceeds 512 bytes");
            if (!text[pos]) return error_at(error, line, "embedded NUL");
            buf[length++] = text[pos++];
        }
        if (pos < size) ++pos;
        buf[length] = 0;
        int n = 0;
        char *s = buf;
        while (*s && *s != '#') {
            if (*s == ' ' || *s == '\t' || *s == '\r') { ++s; continue; }
            if (n == 16) return error_at(error, line, "unsupported filter form");
            /* A colon is a separate token, even in "Filter 1:" and "Preamp:". */
            if (*s == ':') { t[n++] = ":"; ++s; continue; }
            t[n++] = s;
            while (*s && *s != ' ' && *s != '\t' && *s != '\r' && *s != ':' && *s != '#') ++s;
            char delimiter = *s;
            if (*s) *s++ = 0;
            if (delimiter == ':') {
                if (n == 16) return error_at(error, line, "unsupported filter form");
                t[n++] = ":";
            }
            if (delimiter == '#') break;
        }
        if (!n) continue;
        if (!strcmp(t[0], "Preamp")) {
            double gain;
            if (n != 4 || strcmp(t[1], ":") || strcmp(t[3], "dB"))
                return error_at(error, line, "expected Preamp: <gain> dB");
            if (!number(t[2], &gain) || !between(gain, -60, 24))
                return error_at(error, line, "preamp outside -60..24 dB or invalid number");
            p.preamp += gain;
            preamp_line = line;
            continue;
        }
        if (strcmp(t[0], "Filter")) return error_at(error, line, "unsupported command");
        int k = 1;
        if (n > 1 && strcmp(t[1], ":")) {
            for (s = t[1]; *s; ++s) if (*s < '0' || *s > '9')
                return error_at(error, line, "invalid filter label");
            ++k;
        }
        if (n <= k || strcmp(t[k++], ":")) return error_at(error, line, "expected Filter [number]:");
        if (n - k != 8 && n - k != 10) return error_at(error, line, "unsupported filter form");
        if (p.count == 10) return error_at(error, line, "more than ten bands");
        peq_band b = {0, 0, 0, 0, 0.7071067811865476};
        if (!strcmp(t[k], "ON")) b.enabled = 1;
        else if (strcmp(t[k], "OFF")) return error_at(error, line, "expected ON or OFF");
        ++k;
        if (!strcmp(t[k], "PK") || !strcmp(t[k], "PEQ")) b.type = 0;
        else if (!strcmp(t[k], "LS") || !strcmp(t[k], "LSC")) b.type = 1;
        else if (!strcmp(t[k], "HS") || !strcmp(t[k], "HSC")) b.type = 2;
        else return error_at(error, line, "unsupported filter type");
        ++k;
        if (strcmp(t[k], "Fc") || strcmp(t[k+2], "Hz") || strcmp(t[k+3], "Gain") ||
            strcmp(t[k+5], "dB")) return error_at(error, line, "expected Fc <Hz> Hz Gain <dB> dB");
        if (!number(t[k+1], &b.frequency) || !number(t[k+4], &b.gain))
            return error_at(error, line, "invalid frequency or gain number");
        k += 6;
        if (k < n) {
            if (strcmp(t[k], "Q") || !number(t[k+1], &b.q))
                return error_at(error, line, "expected Q <number>");
        } else if (!b.type) return error_at(error, line, "peaking filter requires Q");
        if (!valid_band(&b)) return error_at(error, line, "range: 20..20000 Hz, -24..24 dB, Q 0.1..10");
        p.bands[p.count++] = b;
    }
    if (!between(p.preamp, -60, 24)) return error_at(error, preamp_line, "summed preamp outside -60..24 dB");
    *out = p; /* Commit only after the complete file validates. */
    return 1;
}

int peq_import_file(const char *path, peq_preset *out, peq_error *error) {
    char *text = calloc(1, PEQ_FILE_LIMIT + 1);
    if (!text) return error_at(error, 1, "out of memory");
    void *f = fopen(path, "rb");
    if (!f) { free(text); return error_at(error, 1, "cannot open file"); }
    unsigned n = fread(text, 1, PEQ_FILE_LIMIT + 1, f);
    int bad = ferror(f);
    if (fclose(f)) bad = 1;
    int ok = bad ? error_at(error, 1, "file read failed") : peq_parse(text, n, out, error);
    free(text);
    return ok;
}

int peq_load(const char *path, peq_preset *out) {
    struct { char magic[8]; peq_preset preset; } file;
    void *f = fopen(path, "rb");
    if (!f) return 0;
    char extra;
    int ok = fread(&file, 1, sizeof(file), f) == sizeof(file) && fread(&extra, 1, 1, f) == 0 && !ferror(f);
    if (fclose(f)) ok = 0;
    if (!ok || memcmp(file.magic, "Q2PEQ01", 8) || !peq_valid(&file.preset)) return 0;
    *out = file.preset;
    return 1;
}

int peq_save(const char *path, const peq_preset *p, int replace) {
    char tmp[600];
    if (!peq_valid(p) || strlen(path) > 580) return 0;
    if (!replace && !access(path, 0)) return 2;
    snprintf(tmp, sizeof(tmp), "%s.tmp", path);
    void *f = fopen(tmp, "wb");
    if (!f) return 0;
    int ok = fwrite("Q2PEQ01", 1, 8, f) == 8 && fwrite(p, 1, sizeof(*p), f) == sizeof(*p);
    if (fflush(f) || fsync(fileno(f))) ok = 0;
    if (fclose(f)) ok = 0;
    if (ok && !rename(tmp, path)) return 1;
    unlink(tmp);
    return 0;
}

/* RBJ peaking and Q-form shelves. All design work is outside the PCM callback. */
int peq_compile(const peq_preset *p, int rate, peq_engine *out) {
    peq_engine e;
    memset(&e, 0, sizeof(e));
    if (!peq_valid(p) || rate < 8000 || rate > 384000) return 0;
    e.gain = pow(10, p->preamp / 20);
    e.bypass = p->bypass;
    for (int i = 0; i < 10; ++i) {
        e.c[i].b0 = 1;
        if (i >= p->count || !p->bands[i].enabled || !p->bands[i].gain) continue;
        const peq_band *b = &p->bands[i];
        /* Keep the preset intact when a low-rate track cannot represent a band. */
        if (b->frequency >= rate * 0.5) { e.bypass = 1; continue; }
        double a = pow(10, b->gain / 40), w = 6.283185307179586 * b->frequency / rate;
        double c = cos(w), alpha = sin(w) / (2 * b->q), r = 2 * __builtin_sqrt(a) * alpha;
        double b0, b1, b2, a0, a1, a2;
        if (!b->type) {
            b0 = 1 + alpha * a; b1 = -2 * c; b2 = 1 - alpha * a;
            a0 = 1 + alpha / a; a1 = -2 * c; a2 = 1 - alpha / a;
        } else if (b->type == 1) {
            b0 = a * ((a+1) - (a-1)*c + r); b1 = 2*a*((a-1) - (a+1)*c);
            b2 = a*((a+1) - (a-1)*c - r); a0 = (a+1) + (a-1)*c + r;
            a1 = -2*((a-1) + (a+1)*c); a2 = (a+1) + (a-1)*c - r;
        } else {
            b0 = a*((a+1) + (a-1)*c + r); b1 = -2*a*((a-1) + (a+1)*c);
            b2 = a*((a+1) + (a-1)*c - r); a0 = (a+1) - (a-1)*c + r;
            a1 = 2*((a-1) - (a+1)*c); a2 = (a+1) - (a-1)*c - r;
        }
        e.c[i] = (peq_coeff){b0/a0, b1/a0, b2/a0, a1/a0, a2/a0};
    }
    *out = e;
    return 1;
}

void peq_reset(peq_dsp *d, int rate, int channels, const peq_preset *p) {
    memset(d, 0, sizeof(*d));
    d->rate = rate;
    d->channels = channels;
    d->ramp_length = rate / 50; /* 20 ms */
    if (!peq_compile(p, rate, &d->current)) d->current.bypass = 1;
}

int peq_update(peq_dsp *d, const peq_preset *p) {
    if (!peq_compile(p, d->rate, &d->pending)) return 0;
    d->waiting = 1; /* Latest complete update wins; never interrupt an in-flight crossfade. */
    return 1;
}

static double sample(peq_engine *e, double x, int ch) {
    if (e->bypass) return x;
    x *= e->gain;
    for (int i = 0; i < 10; ++i) {
        const peq_coeff *c = &e->c[i];
        double *z = e->z[ch][i], y = c->b0 * x + z[0];
        z[0] = c->b1 * x - c->a1 * y + z[1];
        z[1] = c->b2 * x - c->a2 * y;
        x = y;
    }
    return x;
}

void peq_process(peq_dsp *d, float *audio, unsigned frames) {
    if (!audio || d->channels < 1 || d->channels > 8) return;
    for (unsigned i = 0; i < frames; ++i) {
        if (!d->ramp && d->waiting) {
            d->next = d->pending;
            d->waiting = 0;
            d->ramp = d->ramp_length;
        }
        for (int ch = 0; ch < d->channels; ++ch, ++audio) {
            if (!d->ramp && d->current.bypass) continue; /* bit-exact steady bypass */
            double x = *audio;
            if (!PEQ_FINITE(x)) x = 0;
            double y = sample(&d->current, x, ch);
            if (d->ramp) {
                double wet = sample(&d->next, x, ch);
                double mix = (double)(d->ramp_length - d->ramp + 1) / d->ramp_length;
                y += (wet - y) * mix;
            }
            *audio = (float)(y > 1 ? 1 : y < -1 ? -1 : y);
        }
        if (d->ramp && !--d->ramp) d->current = d->next;
    }
}
