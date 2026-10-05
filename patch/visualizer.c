/* iPod Now Playing's fourth page (docs/ipod.md#visualizer): the music as heard, read from
 * hciplayer's tap (peq.h), in one of four styles after Rockbox's FFT, Oscilloscope and VU Meter
 * plugins; a tap moves to the next style. */
#include "peq.h"
#include "offsets.inc"
#if IPOD

#define VIS_N 1024           /* frames each frame analyses */
#define VIS_HALO 64          /* log-spaced bands, 40 Hz to 16 kHz: the Halo's bars, pairs the spectrum's */
#define VIS_X 16             /* tools/ipod.py NP_MARGIN */
#define VIS_W (375 - 2 * VIS_X)
#define VIS_H 186            /* tools/ipod.py NP_SLIDE_H, the page's height */
#define VIS_ART 88           /* the Halo's centre */
#define TAU 6.2831853f
enum { SPECTRUM, SCOPE, METERS, HALO, STYLES };

static struct {
    float re[VIS_N], im[VIS_N], pcm[VIS_N][2];
    float level[VIS_HALO], peak[VIS_BARS], fall[VIS_BARS], wave[2][VIS_W], vu[2], spin, bass;
    unsigned held[VIS_BARS], lit[2];
#ifndef PEQ_HOST
    void *win, *slide, *page, *art, *cover;
    vis_tap *tap;
    unsigned timer, last, named;
    int style, tapped; /* tapped: the filter was put in the chain this boot */
#endif
} vz __attribute__((section(".scratch")));

/* In-place radix-2 FFT of n complex values, n a power of two. */
static void fft(float *re, float *im, int n) {
    for (int i = 1, j = 0; i < n; ++i) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) {
            float t = re[i]; re[i] = re[j]; re[j] = t;
            t = im[i]; im[i] = im[j]; im[j] = t;
        }
    }
    for (int len = 2; len <= n; len <<= 1) {
        float wr = cosf(TAU / len), wi = -sinf(TAU / len);
        for (int i = 0; i < n; i += len) {
            float cr = 1, ci = 0;
            for (int k = i; k < i + len / 2; ++k) {
                float tr = re[k + len / 2] * cr - im[k + len / 2] * ci, ti = re[k + len / 2] * ci + im[k + len / 2] * cr;
                re[k + len / 2] = re[k] - tr; im[k + len / 2] = im[k] - ti;
                re[k] += tr; im[k] += ti;
                float t = cr * wr - ci * wi;
                ci = cr * wi + ci * wr;
                cr = t;
            }
        }
    }
}

static float db(double power) { return (float)(10 * log(power) / 2.302585092994046); }

static int band_bin(int b, unsigned rate) { return (int)(40 * pow(400, (double)b / VIS_HALO) * VIS_N / rate + 0.5); }

/* level[VIS_HALO]: each band's loudest bin of the Hann-windowed mono mix of VIS_N frames at rate, 0
 * at VIS_FLOOR_DB below a full-scale sine to 1 at it. */
void vis_bands(const float (*pcm)[2], unsigned rate, float *level) {
    for (int i = 0; i < VIS_N; ++i) {
        vz.re[i] = (pcm[i][0] + pcm[i][1]) * 0.5f * (0.5f - 0.5f * cosf(TAU * i / (VIS_N - 1)));
        vz.im[i] = 0;
    }
    fft(vz.re, vz.im, VIS_N);
    for (int b = 0; b < VIS_HALO; ++b) {
        int lo = band_bin(b, rate), hi = band_bin(b + 1, rate);
        float m = 0;
        for (int k = lo; k < (hi > lo ? hi : lo + 1) && k < VIS_N / 2; ++k) {
            float p = vz.re[k] * vz.re[k] + vz.im[k] * vz.im[k];
            if (p > m) m = p;
        }
        /* A full-scale sine peaks at N / 4 under the Hann window. */
        float v = m > 0 ? 1 + db(m * 16 / ((float)VIS_N * VIS_N)) / VIS_FLOOR_DB : 0;
        level[b] = v < 0 ? 0 : v > 1 ? 1 : v;
    }
}

#ifndef PEQ_HOST
extern int config_digit(const char *key, int n);
extern void peq_attach(void);
/* The accent's palette: its light tone, a dark shade of it and a bright tint, never washed to white. */
#define DARK(tone) mix(tone, 0, 55, 100)
#define BRIGHT(tone) mix(tone, 0xffffff, 30, 100)
static float bar(int i) { return (vz.level[2 * i] + vz.level[2 * i + 1]) / 2; }

/* Now Playing is on top, on this page, with the screen on. */
static int showing(void) {
    return vz.page && g_backlight_status && window_manager_get_top_window(window_manager()) == vz.win &&
           widget_get_prop_int(vz.slide, "value", 0) == (int)widget_count_children(vz.slide) - 1;
}

/* The tap, mapped read-only; demo makes the file whole under another name first (peq.h). */
static vis_tap *tap(void) {
    if (vz.tap) return vz.tap;
    int fd = open(VIS_FILE, 2); /* O_RDWR */
    if (fd < 0) {
        fd = open(VIS_FILE ".tmp", 0x302, 0644); /* O_RDWR | O_CREAT | O_TRUNC (MIPS) */
        if (fd < 0) return 0;
        if (ftruncate(fd, sizeof(vis_tap)) || rename(VIS_FILE ".tmp", VIS_FILE)) {
            close(fd);
            return 0;
        }
    }
    void *p = mmap(0, sizeof(vis_tap), 1, 1, fd, 0); /* PROT_READ, MAP_SHARED */
    close(fd);
    return vz.tap = p == (void *)-1 ? 0 : p;
}

/* The VIS_N frames heard now, into vz.pcm: VIS_LATENCY_MS behind the tap's last write, moved on by
 * the time since it. Their rate, or 0 when nothing plays. */
static unsigned capture(void) {
    vis_tap *t = tap();
    if (!t || mclGetPlayStatus() != 2) return 0;
    unsigned seq = t->seq, rate = t->rate;
    long long age = now_ns() - t->stamp;
    /* nothing written lately (DSD, or the filter is off), or a stamp read torn mid-write: one frame at rest */
    if (!rate || age < 0 || age > 1000000000LL) return 0;
    int lag = (int)(rate * (VIS_LATENCY_MS / 1000.0f - (int)age * 1e-9f));
    lag = lag < 0 ? 0 : lag > VIS_RING / 2 ? VIS_RING / 2 : lag; /* well clear of the next write */
    for (unsigned i = 0, at = seq - (unsigned)lag - VIS_N; i < VIS_N; ++i) {
        vz.pcm[i][0] = t->ring[(at + i) % VIS_RING][0];
        vz.pcm[i][1] = t->ring[(at + i) % VIS_RING][1];
    }
    return rate;
}

/* VU position 0 to 1 of a level in VU (dB): proportional to voltage, +3 at the end, as the meter's scale. */
static float vu_at(float vu) { return (float)pow(10, (vu - 3) / 20); }

/* Each 1000 / VIS_FPS ms while showing: the levels rise fast and fall at VIS_DECAY a second, a cap
 * holds VIS_HOLD_MS over each spectrum bar's peak, then falls under VIS_GRAVITY; the scope starts on a
 * rising zero crossing so the wave stands still; the VU needles integrate over 300 ms. With nothing
 * playing every one comes to rest. */
static int tick(const void *unused) {
    (void)unused;
    if (!showing()) {
        vz.timer = 0;
        return 7; /* RET_REMOVE */
    }
    /* The tap lives in hciplayer's PEQ filter, which boot leaves out of the chain when PEQ is off: the
     * first tick (outside the paint) puts it in, in bypass, as the editor's switch does. */
    if (!vz.tapped && !g_equalizer_flag) peq_attach();
    vz.tapped = 1;
    unsigned now = time_now_ms(), rate = capture();
    float dt = (now - vz.last) / 1000.0f, target[VIS_HALO] = { 0 };
    vz.last = now;
    if (dt > 0.1f) dt = 0.1f;
    if (rate) vis_bands(vz.pcm, rate, target);
    for (int b = 0; b < VIS_HALO; ++b) {
        float fall = vz.level[b] - VIS_DECAY * dt;
        vz.level[b] = target[b] > vz.level[b] ? vz.level[b] + (target[b] - vz.level[b]) * 0.6f : target[b] > fall ? target[b] : fall;
    }
    for (int i = 0; i < VIS_BARS; ++i) {
        if (bar(i) >= vz.peak[i]) {
            vz.peak[i] = bar(i);
            vz.fall[i] = 0;
            vz.held[i] = now + VIS_HOLD_MS;
        } else if ((int)(now - vz.held[i]) > 0) {
            vz.fall[i] += VIS_GRAVITY * dt;
            vz.peak[i] -= vz.fall[i] * dt;
            if (vz.peak[i] < bar(i)) vz.peak[i] = bar(i);
        }
    }
    int at = 0;
    for (int i = 1; rate && i < VIS_N - VIS_W && !at; ++i)
        if (vz.pcm[i - 1][0] + vz.pcm[i - 1][1] < 0 && vz.pcm[i][0] + vz.pcm[i][1] >= 0) at = i;
    for (int ch = 0; ch < 2; ++ch) {
        float sum = 0, peak = 0;
        for (int i = 0; i < VIS_W; ++i) vz.wave[ch][i] = rate ? vz.pcm[at + i][ch] : vz.wave[ch][i] * 0.8f;
        for (int i = 0; rate && i < VIS_N; ++i) {
            float v = vz.pcm[i][ch];
            sum += v * v;
            if (__builtin_fabsf(v) > peak) peak = __builtin_fabsf(v);
        }
        float to = sum > 0 ? vu_at(db(sum / VIS_N) - VIS_VU_REF_DB) : 0;
        vz.vu[ch] += ((to > 1 ? 1 : to) - vz.vu[ch]) * dt / (dt + 0.065f);
        if (peak >= (float)pow(10, VIS_LED_DB / 20.0)) vz.lit[ch] = now + VIS_HOLD_MS;
    }
    float bass = (vz.level[0] + vz.level[2] + vz.level[4] + vz.level[6]) / 4;
    vz.bass += (bass - vz.bass) * 0.5f;
    vz.spin += dt * 0.2f; /* radians a second */
    widget_invalidate_force(vz.page, 0);
    return 8; /* RET_REPEAT */
}

static void arm(void) {
    if (vz.timer || !showing()) return;
    vz.last = time_now_ms();
    vz.timer = timer_add(tick, 0, 1000 / VIS_FPS);
}

/* The Halo's centre shows Now Playing's own art: the same image, so stock's reload of it reaches both. */
static void halo_art(void) {
    if (!vz.art) return;
    widget_set_visible(vz.art, vz.style == HALO, 0);
    const char *src = vz.cover ? widget_get_prop_str(vz.cover, "image", "") : "";
    if (vz.style == HALO && tk_strcmp(src, widget_get_prop_str(vz.art, "image", ""))) {
        image_set_draw_type(vz.art, widget_get_prop_int(vz.cover, "draw_type", IMAGE_DRAW_SCALE_DOWN));
        image_base_set_image(vz.art, src);
    }
}

static void line(void *vg, float x0, float y0, float x1, float y1) {
    vgcanvas_begin_path(vg);
    vgcanvas_move_to(vg, x0, y0);
    vgcanvas_line_to(vg, x1, y1);
    vgcanvas_stroke(vg);
}

static void disc(void *vg, float x, float y, float r, unsigned color) {
    vgcanvas_begin_path(vg);
    vgcanvas_arc(vg, x, y, r, 0, TAU, 0);
    vgcanvas_set_fill_color(vg, color);
    vgcanvas_fill(vg);
}

/* Rockbox FFT's log bars, Apple's finish: capsules in a gradient from the accent's dark shade to its
 * bright tint at full height, a cap on each peak, and a faint reflection under the baseline. */
#define BASE 142
#define TALL 126
static void spectrum(void *vg, unsigned tone) {
    float pitch = (float)VIS_W / VIS_BARS, w = pitch * 0.66f;
    for (int i = 0; i < VIS_BARS; ++i) {
        float x = VIS_X + i * pitch + (pitch - w) / 2, h = 3 + bar(i) * (TALL - 3);
        vgcanvas_begin_path(vg);
        vgcanvas_rounded_rect(vg, x, BASE - h, w, h, w / 2);
        vgcanvas_set_fill_linear_gradient(vg, 0, BASE, 0, BASE - TALL, rgba(DARK(tone), 255), rgba(BRIGHT(tone), 255));
        vgcanvas_fill(vg);
        vgcanvas_begin_path(vg);
        vgcanvas_rounded_rect(vg, x, BASE + 4, w, h * 0.3f, w / 2);
        vgcanvas_set_fill_linear_gradient(vg, 0, BASE + 4, 0, BASE + 4 + TALL * 0.3f, rgba(tone, 0x38), rgba(tone, 0));
        vgcanvas_fill(vg);
        vgcanvas_begin_path(vg);
        vgcanvas_rounded_rect(vg, x, BASE - 3 - vz.peak[i] * (TALL - 3) - 4, w, 3, 1.5f);
        vgcanvas_set_fill_color(vg, rgba(BRIGHT(tone), 255));
        vgcanvas_fill(vg);
    }
}

/* Rockbox's oscilloscope: the right channel a faint accent line, the left over it with a glow, three
 * strokes from wide and faint to fine and bright. */
static void scope(void *vg, unsigned tone) {
    static const struct { float width; unsigned alpha; } pass[] = { { 1.5f, 0x50 }, { 7, 0x28 }, { 3.5f, 0x60 }, { 1.5f, 0xff } };
    for (int k = 0; k < 4; ++k) {
        const float *w = vz.wave[!k ? 1 : 0];
        vgcanvas_begin_path(vg);
        for (int x = 0; x < VIS_W; ++x) {
            float y = VIS_H / 2 + (k ? 0 : 3) - w[x] * (VIS_H / 2 - 16);
            if (x) vgcanvas_line_to(vg, VIS_X + x, y);
            else vgcanvas_move_to(vg, VIS_X, y);
        }
        vgcanvas_set_line_width(vg, pass[k].width);
        vgcanvas_set_stroke_color(vg, rgba(k == 3 ? BRIGHT(tone) : tone, pass[k].alpha));
        vgcanvas_stroke(vg);
    }
}

/* Rockbox's analog VU meters, left and right, in the accent's palette: an arc from -20 to +3 VU,
 * heavier and brighter past 0, ticks and labels, the needle on its pivot and a peak LED. */
static void meters(void *vg, void *canvas, unsigned tone, unsigned now) {
    static const signed char marks[] = { -20, -10, -7, -5, -3, -2, -1, 0, 1, 2, 3 };
    static const char *const labels[] = { "-20", "-10", "", "-5", "-3", "", "", "0", "", "", "+3" };
    /* 80 degrees of arc: the end labels of the two meters stay apart, and the face centres on the page. */
    const float r = 94, py = 150, spread = 1.4f;
    for (int ch = 0; ch < 2; ++ch) {
        float cx = VIS_X + (VIS_W / 4.0f) * (1 + 2 * ch), zero = -TAU / 4 - spread / 2;
        vgcanvas_set_line_width(vg, 2);
        vgcanvas_begin_path(vg);
        vgcanvas_arc(vg, cx, py, r, zero, zero + spread * vu_at(0), 0);
        vgcanvas_set_stroke_color(vg, rgba(tone, 255));
        vgcanvas_stroke(vg);
        vgcanvas_set_line_width(vg, 3);
        vgcanvas_begin_path(vg);
        vgcanvas_arc(vg, cx, py, r, zero + spread * vu_at(0), zero + spread, 0);
        vgcanvas_set_stroke_color(vg, rgba(BRIGHT(tone), 255));
        vgcanvas_stroke(vg);
        vgcanvas_set_line_width(vg, 1.5f);
        for (unsigned i = 0; i < sizeof marks; ++i) {
            float a = zero + spread * vu_at(marks[i]), c = cosf(a), s = sinf(a), out = labels[i][0] ? 8 : 5;
            vgcanvas_set_stroke_color(vg, rgba(marks[i] > 0 ? BRIGHT(tone) : tone, 255));
            line(vg, cx + c * r, py + s * r, cx + c * (r + out), py + s * (r + out));
            if (labels[i][0]) caption(canvas, labels[i], (int)(cx + c * (r + 16)) - 14, (int)(py + s * (r + 16)) - 8, 28, 16, 12, CF_GREY);
        }
        caption(canvas, ch ? "R" : "L", (int)cx - 48, (int)py - 20, 24, 20, 14, CF_GREY); /* clear of the needle */
        float a = zero + spread * vz.vu[ch];
        vgcanvas_set_line_width(vg, 2);
        vgcanvas_set_stroke_color(vg, rgba(BRIGHT(tone), 255));
        line(vg, cx, py, cx + cosf(a) * (r + 4), py + sinf(a) * (r + 4));
        disc(vg, cx, py, 7, rgba(tone, 255));
        disc(vg, cx, py, 5, rgba(DARK(tone), 255));
        disc(vg, cx + r * 0.62f, py - r * 0.62f - 8, 4, rgba((int)(vz.lit[ch] - now) > 0 ? BRIGHT(tone) : DARK(DARK(tone)), 255));
    }
}

/* Apple's radial spectrum: VIS_HALO bars, mirrored left and right, radiating from Now Playing's art
 * in a circle, turning slowly, with the bass pulsing the ring. */
static void halo(void *vg, unsigned tone) {
    float cx = 375 / 2.0f, cy = VIS_H / 2.0f, art = VIS_ART / 2.0f, r0 = art + 7 + 5 * vz.bass;
    vgcanvas_set_line_width(vg, art * 0.42f + 2); /* round the art: black over its corners */
    vgcanvas_begin_path(vg);
    vgcanvas_arc(vg, cx, cy, art * 1.21f + 1, 0, TAU, 0);
    vgcanvas_set_stroke_color(vg, rgba(0, 255));
    vgcanvas_stroke(vg);
    vgcanvas_set_line_width(vg, 2);
    vgcanvas_begin_path(vg);
    vgcanvas_arc(vg, cx, cy, art + 3, 0, TAU, 0);
    vgcanvas_set_stroke_color(vg, rgba(tone, 0x50 + (unsigned)(0xaf * vz.bass)));
    vgcanvas_stroke(vg);
    vgcanvas_set_line_cap(vg, "round");
    for (int pass = 0; pass < 2; ++pass) { /* a soft accent glow, then the bar */
        vgcanvas_set_line_width(vg, pass ? 2.5f : 5);
        for (int i = 0; i < VIS_HALO; ++i) {
            float v = bar(i < VIS_HALO / 2 ? i : VIS_HALO - 1 - i), a = vz.spin + TAU * i / VIS_HALO;
            float c = cosf(a), s = sinf(a), len = 3 + v * (cy - r0 - 6);
            vgcanvas_set_stroke_color(vg, pass ? rgba(mix(DARK(tone), BRIGHT(tone), 35 + (int)(65 * v), 100), 255) : rgba(tone, 0x30));
            line(vg, cx + c * r0, cy + s * r0, cx + c * (r0 + len), cy + s * (r0 + len));
        }
    }
    vgcanvas_set_line_cap(vg, "butt");
}

/* ringnav_paint, after stock: the page in the current style on black, and for 1.5 s after a change
 * the style's name, fading over its last half second. Painting the page starts its timer. */
void visualizer_paint(void *w, void *canvas) {
    static const char *const names[] = { "Spectrum", "Oscilloscope", "VU Meters", "Halo" };
    if (!w || w != vz.page || !P(canvas, CANVAS_LCD)) return;
    arm();
    void *vg = canvas_get_vgcanvas(canvas);
    unsigned tone = accent_tone(2), now = time_now_ms();
    if (vg) {
        vgcanvas_save(vg);
        vgcanvas_translate(vg, (float)I(canvas, CANVAS_X), (float)I(canvas, CANVAS_Y));
        if (vz.style == SPECTRUM) spectrum(vg, tone);
        else if (vz.style == SCOPE) scope(vg, tone);
        else if (vz.style == METERS) meters(vg, canvas, tone, now);
        else halo(vg, tone);
        vgcanvas_restore(vg);
    }
    unsigned shown = now - vz.named;
    if (vz.named && shown < 1500)
        caption(canvas, names[vz.style], 0, VIS_H - 22, 375, 20, 14,
             rgba(0xaaaaaa, shown < 1000 ? 255 : 255 * (1500 - shown) / 500));
}

static int next_style(void *ctx, void *event) {
    (void)ctx; (void)event;
    vz.style = (vz.style + 1) % STYLES;
    vz.named = time_now_ms() | 1; /* never 0, which is none */
    write_int_config(vz.style, "IPOD", "VIS");
    halo_art();
    widget_invalidate_force(vz.page, 0);
    return 0;
}

static int slid(void *ctx, void *event) {
    (void)ctx; (void)event;
    halo_art();
    arm();
    return 0;
}

static int gone(void *win, void *event) {
    (void)event;
    if (win == vz.win) {
        stop_timer(&vz.timer);
        vz.win = vz.slide = vz.page = vz.art = vz.cover = 0;
    }
    return 0;
}

/* ringnav_playing: the page joins the slide_view's art, lyrics and info pages, and its dots. */
void visualizer_attach(void *win) {
    void *slide = widget_lookup(win, "slide_view", 1), *dots = widget_lookup(win, "slide_indicator1", 1);
    if (!slide) return;
    vz.style = config_digit("VIS", STYLES);
    vz.win = win;
    vz.slide = slide;
    vz.cover = widget_lookup(win, "img_cover", 1);
    vz.page = list_item_create(slide, 0, 0, I(slide, W_W), I(slide, W_H));
    widget_use_style(vz.page, "s_listitem_black");
    widget_on(vz.page, EVT_CLICK, next_style, 0);
    vz.art = image_create(vz.page, (I(slide, W_W) - VIS_ART) / 2, (I(slide, W_H) - VIS_ART) / 2, VIS_ART, VIS_ART);
    widget_set_sensitive(vz.art, 0);
    if (dots) widget_set_prop_int(dots, "max", (int)widget_count_children(slide));
    widget_on(slide, EVT_VALUE_CHANGED, slid, 0);
    widget_on(win, EVT_DESTROY, gone, win);
    halo_art();
}
#endif
#endif
