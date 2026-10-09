/* Spotify (docs/internals.md#spotify): librespot, built from the q2-librespot fork, runs from the
 * card's SPOT_DIR as a Spotify Connect receiver beside the stock player. It writes its state, the
 * track and position to SPOT_STATE (and the cover to SPOT_COVER) and takes commands on SPOT_SOCK;
 * this file is the other end. Like Videos' q2video, while it plays it holds the standby timers and
 * the DAC, which it sets up as stock's AirPlay receiver does, and it hands the DAC over with local
 * music both ways. Streaming's Spotify row opens a Now Playing page for it. */
#include "offsets.inc"
#include "peq.h"
#include "stock.h"

#define SPOT_DIR "/mnt/mmc/.spotify"
#define SPOT_BIN SPOT_DIR "/librespot"
#define SPOT_RUN "/bin/sh " SPOT_DIR "/run" /* backgrounds itself, once per boot */
#define SPOT_DEBUG SPOT_DIR "/debug"        /* present: SPOT_LOG records every hand-over */
#define SPOT_LOG SPOT_DIR "/q2pod.log"
#define SPOT_STATE "/tmp/q2-librespot.state" /* the fork's --status-file */
#define SPOT_COVER SPOT_STATE ".jpg"
#define SPOT_SOCK "/tmp/q2-librespot.sock" /* its --control-socket */
#define SPOT_ART "/tmp/q2spot.jpg"         /* the cover at the page's size */
#define SPOT_POLL_MS 500
#define SPOT_YIELD_MS 1500 /* local music waits at most this long for librespot to let the DAC go  \
                            */
#define SPOT_STEP_MS 5000  /* a scrub tick, as Now Playing's */
#define SPOT_IDLE_MS 30000 /* not playing this long after it has played: librespot is stopped */

extern int image_show(void *img, const char *url, unsigned *size),
    center_press(unsigned *timer, unsigned *at, int (*single)(const void *), int scrubbing);

/* librespot as last read; kept for the life of demo. */
static struct {
    int launched, debug, sock, playing, paused, local, active, played;
    unsigned polled, idle_at, duration, position, cover;
    unsigned long long at;
    char raw[1536]; /* the file as last read, behind a '\n' so every key follows one */
    char state[12], track[64], title[256], artist[256], album[256];
} sp __attribute__((section(".scratch")));

/* The page, while open. */
static struct {
    void *page, *info, *msg, *art, *bar, *glyph, *title, *artist, *album, *elapsed, *remain, *note,
        *sub;
    unsigned timer, leave, scrub_at, shown, playing, press, press_at;
    int scrub, scrub_ms;
    char art_track[64];
} ui __attribute__((section(".scratch")));

unsigned long long now_ms(void) { /* shared with radio.c */
    int ts[2];            /* o32 timespec */
    clock_gettime(1, ts); /* CLOCK_MONOTONIC, librespot's at= clock */
    return (unsigned long long)(unsigned)ts[0] * 1000 + (unsigned)ts[1] / 1000000;
}

/* With SPOT_DEBUG on the card, one line a hand-over step: the step and two numbers. */
static void spot_log(const char *what, int a, int b) {
    if (!sp.debug) return;
    char line[160];
    int n = tk_snprintf(line, sizeof line, "%u %s %d %d play=%d dacoff=%d light=%d\n",
                        time_now_ms() / 1000, what, a, b, mclGetPlayStatus(), I(g_dacoff_time, 0),
                        g_backlight_status);
    void *f = fopen(SPOT_LOG, "a");
    if (!f) return;
    fwrite(line, 1, (unsigned)n, f);
    fclose(f);
}

static void spot_send(const char *c, unsigned n) {
    if (sp.sock <= 0) sp.sock = socket(1, 1, 0); /* AF_UNIX, SOCK_DGRAM (MIPS numbering) */
    struct {
        unsigned short family;
        char path[108];
    } to = { 1, SPOT_SOCK };
    sendto(sp.sock, c, n, 0x40, &to, sizeof to); /* MSG_DONTWAIT */
    spot_log("send", c[0], (int)n);
}

/* The value of key in raw into out (n bytes), "" without one. Shared with radio.c. */
void field(const char *raw, const char *key, char *out, unsigned n) {
    char k[16];
    tk_snprintf(k, sizeof k, "\n%s=", key);
    const char *v = strstr(raw, k), *e;
    unsigned len = 0;
    if (v)
        for (v += strlen(k), e = v; *e && *e != '\n' && len + 1 < n; ++e) ++len;
    if (len) memcpy(out, v, len);
    out[len] = 0;
}

unsigned long long number(const char *raw, const char *key) {
    char v[24];
    unsigned long long x = 0;
    field(raw, key, v, sizeof v);
    for (const char *c = v; *c >= '0' && *c <= '9'; ++c) x = x * 10 + (unsigned)(*c - '0');
    return x;
}

/* The state file into raw; 1 when it changed. Gone (librespot not up yet) reads as no session. */
static int spot_read(char *raw, unsigned size) {
    void *f = fopen(SPOT_STATE, "rb");
    unsigned n = f ? fread(raw + 1, 1, size - 2, f) : 0;
    if (f) fclose(f);
    raw[0] = '\n';
    raw[n + 1] = 0;
    return strcmp(raw, sp.raw) != 0;
}

/* The track's position now: the last one read, moved on by the time since while playing. */
static unsigned spot_position(void) {
    unsigned p = sp.position;
    if (sp.playing) p += (unsigned)(now_ms() - sp.at);
    return p < sp.duration ? p : sp.duration;
}

/* librespot starts playing: what stock's AirPlay page (airplay_page_init, on_airplayset_onclick)
 * does for its receiver. Local music stops (hciplayer holds the PCM even paused), the headphone
 * output is set up as a headset insert sets it (config_outputchannel: the headset mode, the DAC
 * powered with its firmware, g_dacoff_time 0), the DAC is put in PCM mode and unmuted (player_stop
 * mutes it), and the volume applied. Bluetooth and USB outputs are left alone: librespot plays on
 * the headphone DAC only. */
static void spot_take(void) {
    spot_log("take", g_headset_output, mclGetOutputWay());
    radio_stop(); /* Internet Radio's q2video holds the PCM */
    if (mclGetPlayStatus() != 1) player_stop(); /* 1 stopped */
    if (g_headset_output < 2)
        config_outputchannel(g_headset_output, 2);
    else if (I(g_dacoff_time, 0) < 0)
        mclSetDacPwr(1);
    mclSetPcmMode();
    mclSetMute(0);
    device_set_volume(g_volume, 1);
}

static void spot_parse(void) {
    field(sp.raw, "state", sp.state, sizeof sp.state);
    field(sp.raw, "track", sp.track, sizeof sp.track);
    field(sp.raw, "title", sp.title, sizeof sp.title);
    field(sp.raw, "artist", sp.artist, sizeof sp.artist);
    field(sp.raw, "album", sp.album, sizeof sp.album);
    sp.duration = (unsigned)number(sp.raw, "duration");
    sp.position = (unsigned)number(sp.raw, "position");
    sp.at = number(sp.raw, "at");
    sp.cover = (unsigned)number(sp.raw, "cover");
}

static void spot_launch(void) {
    if (sp.launched || access(SPOT_BIN, 0)) return;
    sp.launched = 1;
    sp.debug = !access(SPOT_DEBUG, 0);
    spot_log("launch", 0, 0);
    system(SPOT_RUN);
}

static void scrub_commit(void) {
    char c[16];
    int n = tk_snprintf(c, sizeof c, "S%d", ui.scrub_ms);
    ui.scrub = 0;
    spot_send(c, (unsigned)n);
}

static void spot_refresh(void);

/* SPOT_IDLE_MS after playback ended: librespot and its restart loop killed, as Home's Rockbox row
 * does, and the keys local music's. Streaming's Spotify row starts it again. */
static void spot_stop(void) {
    int sock = sp.sock;
    spot_log("stop", 0, 0);
    system(SPOT_KILL);
    memset(&sp, 0, sizeof sp);
    sp.sock = sock;
    ui.scrub = 0; /* a scrub cut short: its Return (keyup) would commit it instead of leaving */
}

/* ringnav_sleep, every UI loop pass: nothing until Streaming's Spotify row started librespot; then,
 * paced to SPOT_POLL_MS, its state, and while it plays the standby and auto-power-off timers held
 * and the DAC kept on (check_dacoff_state). The screen's own timer runs, so the screen still turns
 * off. */
void spot_poll(void) {
    if (!sp.launched) return;
    unsigned now = time_now_ms();
    if (now - sp.polled < SPOT_POLL_MS) return;
    sp.polled = now;
    char raw[sizeof sp.raw];
    if (spot_read(raw, sizeof raw)) {
        memcpy(sp.raw, raw, sizeof raw);
        spot_parse();
    }
    int playing = !strcmp(sp.state, "playing");
    if (playing && !sp.playing) {
        sp.playing = 1;
        spot_take();
    }
    if (playing != sp.playing || sp.paused != !strcmp(sp.state, "paused"))
        spot_log(sp.state, (int)sp.position, sp.local);
    sp.playing = playing;
    sp.paused = !strcmp(sp.state, "paused");
    if (playing) {
        reset_poweroptions_timer(1, 1, 0); /* standby, auto power-off; not the screen's */
        if (I(g_dacoff_time, 0) > 0) I(g_dacoff_time, 0) = 0;
        sp.local = 0;
    } else if (mclGetPlayStatus() == 2)
        sp.local = 1; /* local music plays: the keys are its again */
    sp.active = (playing || sp.paused) && !sp.local;
    if (playing || !sp.played)
        sp.played |= playing, sp.idle_at = now;
    else if (now - sp.idle_at >= SPOT_IDLE_MS)
        spot_stop();
    if (ui.scrub && now - ui.scrub_at >= SCRUB_MS) scrub_commit();
}

/* mclStartPlayer's hook (navigation.c): local music is about to open the PCM. A playing librespot
 * is paused first and given up to SPOT_YIELD_MS to say so, which it does once its aplay has ended
 * (the fork's sink stops before the Paused event). May run on the player's thread: no widgets. */
void spot_yield(void) {
    if (!sp.playing) return;
    sp.local = 1;
    sp.active = 0;
    spot_send("s", 1);
    char raw[sizeof sp.raw], state[12] = "playing";
    unsigned start = time_now_ms();
    while (!strcmp(state, "playing") && time_now_ms() - start < SPOT_YIELD_MS) {
        sleep_ms(20);
        spot_read(raw, sizeof raw);
        field(raw, "state", state, sizeof state);
    }
    sp.playing = !strcmp(state, "playing"); /* the next track's start need not ask again */
    spot_log("yield", (int)(time_now_ms() - start), 0);
}

/* ringnav(), any page, after stock's key-lock filter: while Spotify is the last thing played,
 * Play/Pause and the side buttons are its. */
int spot_media(unsigned key) {
    const char *c = key == KEY_PLAY       ? "p"
                    : key == KEY_FWD_BTN  ? "n"
                    : key == KEY_BACK_BTN ? "b"
                                          : 0;
    if (!c || !sp.active) return 0;
    spot_send(c, 1);
    return 1;
}

/* A single centre press, DOUBLE_CLICK_MS on, never while scrubbing: it replays the release to stock
 * on_wm_keyup_fun, which turns the screen off, as Now Playing's np_single. */
static int spot_single(const void *info) {
    static const unsigned release[EVENT_KEY / 4 + 1] = { [EVENT_KEY / 4] = KEY_CENTER };
    (void)info;
    ui.press = 0;
    if (g_backlight_status) on_wm_keyup_fun((void *)0, (void *)release);
    return 0;
}

/* ringnav(), the page on top, as Now Playing: a centre press waits DOUBLE_CLICK_MS (center_press); a second one
 * starts a scrub, else it turns the screen off. While scrubbing one press seeks it at once, the wheel moves
 * it SPOT_STEP_MS a tick, and SCRUB_MS without a tick seeks there (spot_poll). Otherwise the wheel
 * stays stock's volume. */
int spot_key(void *top, unsigned key) {
    if (!ui.page || top != ui.page || !sp.track[0] || !sp.duration) return 0;
    if (key == KEY_CENTER) {
        int press = center_press(&ui.press, &ui.press_at, spot_single, ui.scrub);
        if (press != 2) return press;
        if (ui.scrub)
            scrub_commit();
        else
            ui.scrub = 1, ui.scrub_ms = (int)spot_position();
    } else if (ui.scrub && (key == KEY_NEXT || key == KEY_PREV)) {
        int ms = ui.scrub_ms + (key == KEY_NEXT ? SPOT_STEP_MS : -SPOT_STEP_MS);
        ui.scrub_ms = ms<0 ? 0 : ms>(int) sp.duration ? (int)sp.duration : ms;
    } else
        return 0;
    ui.scrub_at = time_now_ms();
    spot_refresh();
    return 1;
}

static void times(unsigned ms) {
    char t[24];
    toolsTimeItoa(t, (int)(ms / 1000));
    widget_set_text_utf8(ui.elapsed, t);
    t[0] = '-'; /* Now Playing's remaining time: whole seconds less whole seconds */
    toolsTimeItoa(t + 1, (int)(sp.duration / 1000 - ms / 1000));
    widget_set_text_utf8(ui.remain, t);
}

/* The page from sp: the track, or why there is none. Labels are written only when they change. */
static void spot_refresh(void) {
    int track = sp.track[0] && strcmp(sp.state, "none");
    int installed = sp.launched || !access(SPOT_BIN, 0), stopped = !sp.launched && installed;
    widget_set_visible(ui.info, track, 0);
    widget_set_visible(ui.msg, !track, 0);
    if (!track) {
        widget_set_text_utf8(ui.note, stopped     ? "Spotify stopped after a pause"
                                      : installed ? "Open Spotify on your phone"
                                                  : "Spotify isn't on the card");
        widget_set_text_utf8(ui.sub, stopped     ? "Open Streaming, then Spotify"
                                     : installed ? "and choose Q2"
                                                 : "See the Q2 Pod guide to add it");
        return;
    }
    if (tk_strcmp(widget_get_prop_str(ui.title, "text", ""), sp.title)) {
        widget_set_text_utf8(ui.title, sp.title);
        widget_set_text_utf8(ui.artist, sp.artist);
        widget_set_text_utf8(ui.album, sp.album);
    }
    /* ponytail: the cover is sized on the UI thread, one decode a track; a worker if it stutters */
    if (sp.cover && tk_strcmp(ui.art_track, sp.track)) {
        tk_snprintf(ui.art_track, sizeof ui.art_track, "%s", sp.track);
        int shown = thumb(SPOT_COVER, SPOT_ART, SPOT_ART_PX, SPOT_ART_PX) &&
                    image_show(ui.art, "file://" SPOT_ART, 0);
        if (!shown) image_base_set_image(ui.art, "default_album_big");
#if IPOD
        ipod_backdrop_set(1, ui.art, shown ? "file://" SPOT_ART : 0);
#endif
    } else if (!sp.cover && ui.art_track[0]) {
        ui.art_track[0] = 0;
        image_base_set_image(ui.art, "default_album_big");
#if IPOD
        ipod_backdrop_set(1, ui.art, 0);
#endif
    }
    unsigned ms = ui.scrub ? (unsigned)ui.scrub_ms : spot_position();
    if (ms / 1000 + 1 != ui.shown) {
        ui.shown = ms / 1000 + 1;
        times(ms);
    }
    widget_invalidate_force(ui.bar, 0);
    if (ui.playing != (unsigned)sp.playing + 1) {
        ui.playing = (unsigned)sp.playing + 1;
        widget_invalidate_force(ui.glyph, 0);
    }
}

static int tick(const void *unused) {
    (void)unused;
    if (g_backlight_status) spot_refresh();
    return 8; /* RET_REPEAT */
}

static void box(void *canvas, int x, int y, int w, int h, unsigned color, unsigned radius) {
    int r[4] = { x, y, w, h };
    if (canvas_fill_rounded_rect(canvas, r, (void *)0, &color, radius)) {
        canvas_set_fill_color(canvas, color);
        canvas_fill_rect(canvas, x, y, w, h);
    }
}

/* ringnav_paint, every widget after stock painted it: the bar, as Now Playing's capsule (the
 * accent's light tone in iPod, stock red in Stock), and the play state in the top row. */
void spot_paint(void *w, void *canvas) {
    if (!ui.page || !w || !P(canvas, CANVAS_LCD) || (w != ui.bar && w != ui.glyph)) return;
    unsigned fill = (unsigned)I(P(canvas, CANVAS_LCD), LCD_FILL_COLOR);
#if IPOD
    unsigned tone = rgba(accent_tone(2), 255);
#else
    unsigned tone = rgba(STOCK_RED, 255);
#endif
    if (w == ui.bar) {
        unsigned ms = ui.scrub ? (unsigned)ui.scrub_ms : spot_position();
        int x = (int)((ms >> 4) * SPOT_BAR_W / ((sp.duration >> 4) | 1)); /* 32-bit to 57 h */
        box(canvas, 0, 0, SPOT_BAR_W, SPOT_BAR_H, rgba(TRACK_COLOR, 255), SPOT_BAR_H / 2);
        if (x)
            box(canvas, 0, 0, x < SPOT_BAR_H ? SPOT_BAR_H : x, SPOT_BAR_H,
                ui.scrub ? 0xffffffffu : tone, SPOT_BAR_H / 2);
    } else { /* a triangle playing, two bars otherwise */
        canvas_set_fill_color(canvas, 0xffffffffu);
        if (sp.playing)
            for (int i = 0; i < 7; ++i) canvas_fill_rect(canvas, 2 * i, i, 2, 14 - 2 * i);
        else
            canvas_fill_rect(canvas, 0, 0, 4, 14), canvas_fill_rect(canvas, 8, 0, 4, 14);
    }
    canvas_set_fill_color(canvas, fill);
}

static int leave(const void *unused) {
    (void)unused;
    ui.leave = 0;
    navigator_back();
    return 0;
}

/* Return: a scrub seeks first, as on Now Playing; then back to Streaming. */
static int keyup(void *ctx, void *event) {
    (void)ctx;
    if (I(event, EVENT_KEY) != KEY_RETURN) return 0;
    if (ui.scrub)
        scrub_commit();
    else
        rearm(&ui.leave, leave, 0);
    return 11; /* RET_STOP */
}

static int closed(void *ctx, void *event) {
    (void)ctx;
    (void)event;
    stop_timer(&ui.timer);
    stop_timer(&ui.leave);
    stop_timer(&ui.press);
    if (ui.scrub) scrub_commit();
#if IPOD
    ipod_backdrop_set(1, ui.art, 0);
#endif
    memset(&ui, 0, sizeof ui);
    return 0;
}

void *label(void *parent, int x, int y, int w, int h, const char *style, int px,
                   unsigned color) {
    void *l = text(parent, x, y, w, h);
    widget_use_style(l, style);
    widget_set_prop_int(l, "style:normal:font_size", px);
    widget_set_prop_int(l, "style:normal:text_color", (int)color);
    return l;
}

/* Streaming's Spotify row (navigation.c ringnav_stream): librespot started if it is not, and its
 * Now Playing page. */
int spot_open(void *ctx, void *event) {
    (void)ctx;
    (void)event;
    spot_launch();
    if (ui.page || !(ui.page = page_open("spotify_page", closed, keyup))) return 0;
    void *f = widget_factory(), *page = ui.page;
    int h = widget_get_prop_int(page, "h", 290);
    ui.info = widget_factory_create_widget(f, "view", page, 0, 0, 375, h);
    ui.msg = widget_factory_create_widget(f, "view", page, 0, 0, 375, h);
    widget_set_text_utf8(label(ui.info, 16, 12, 200, 16, "s_scrlabel_white20l", 16, SPOT_GREY),
                         "Spotify");
    ui.glyph = widget_factory_create_widget(f, "view", ui.info, 337, 13, 14, 14); /* NP's top row */
    ui.art = image_create(ui.info, SPOT_ART_X, SPOT_ART_Y, SPOT_ART_PX, SPOT_ART_PX);
    image_set_draw_type(ui.art, 4); /* as Coverflow's covers */
    image_base_set_image(ui.art, "default_album_big");
    ui.title =
        label(ui.info, SPOT_TEXT_X, 95, SPOT_TEXT_W, 28, "s_scrlabel_white20l", 22, 0xffffffffu);
    ui.artist =
        label(ui.info, SPOT_TEXT_X, 127, SPOT_TEXT_W, 20, "s_scrlabel_white20l", 16,
              IPOD ? (0xff000000u | NP_ARTIST_RGB) : SPOT_GREY);
    ui.album =
        label(ui.info, SPOT_TEXT_X, 151, SPOT_TEXT_W, 20, "s_scrlabel_white20l", 16, SPOT_GREY);
    ui.bar = widget_factory_create_widget(f, "view", ui.info, SPOT_BAR_X, SPOT_BAR_Y, SPOT_BAR_W,
                                          SPOT_BAR_H);
    ui.elapsed =
        label(ui.info, SPOT_TIME_X, SPOT_TIMES_Y, 80, 16, "s_scrlabel_white20l", 14, SPOT_GREY);
    ui.remain = label(ui.info, 375 - SPOT_TIME_X - 80, SPOT_TIMES_Y, 80, 16, "s_scrlabel_white20r",
                      14, SPOT_GREY);
    ui.note =
        label(ui.msg, CF_EDGE, 100, 375 - 2 * CF_EDGE, 30, "s_scrlabel_white20c", 20, 0xffffffffu);
    ui.sub =
        label(ui.msg, CF_EDGE, 134, 375 - 2 * CF_EDGE, 24, "s_scrlabel_white20c", 16, SPOT_GREY);
    ui.timer = timer_add(tick, 0, 250);
    spot_refresh();
    return 0;
}

/* iPod's Now Playing corners (navigation.c paint_cover) round the art too. */
void *spot_art(void) { return ui.art; }

#if IPOD
void spot_background(void *w, void *canvas) {
    if (w && w == ui.info) ipod_backdrop_paint(1, canvas, 0);
}
#endif
