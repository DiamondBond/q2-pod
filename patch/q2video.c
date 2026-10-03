/* q2video, Videos' player (docs/internals.md#videos): /usr/bin/q2video DEVICE FILE [VOLUME],
 * started by demo (books.c play_video). Stock ffmpeg decodes FILE, fits it into the screen, turns
 * it onto the portrait panel as the boot logo is stored and converts it to the framebuffer's BGRA,
 * frames on one pipe and 48 kHz stereo on another; this plays the sound on ALSA DEVICE ("-"
 * for none; VOLUME, Bluetooth's 0-100, scales it as hciplayer does there) and puts each frame on
 * /dev/fb0 when the sound reaches it, dropping late ones. demo sends keys as datagrams to
 * Q2VIDEO_SOCK: p pause, f and b seek SEEK_S, s seek mode, v and a byte the volume set, q quit;
 * the last four show a bar along the bottom for OVERLAY_MS, the position or the volume. No MIPS sysroot: the declarations below are
 * glibc 2.28's and alsa-lib's, with MIPS o32 constants. */
#define W 320 /* /dev/fb0: 320 x 375, 32 bpp, red at bit 16, two pages (docs/internals.md#videos) */
#define H 375
#define FPS 25
#define RATE 48000
#define CHUNK 512      /* frames per ALSA write: the audio clock's step, about 11 ms */
#define LATENCY 200000 /* ALSA buffer, us */
#define SEEK_S 10
#define SEEK_WAIT_MS 400 /* a run of wheel ticks restarts ffmpeg once */
#define OVERLAY_MS 1500
#define BAR_X 40 /* the bar's ends from the picture's sides, clear of the 80 px glass corners */
#define BAR_Y 22 /* its bottom from the picture's */
#define BAR_H 8
#define Q2VIDEO_SOCK "/tmp/q2video.sock"
#define FFMPEG "/usr/bin/ffmpeg"
#define DAC "/dev/shanling_dac"
#define DAC_PCM 0xc0044d1bu  /* hciplayer sets it to 0 for each PCM track: undoes a DSD one */
#define DAC_MUTE 0xc0044d1fu /* hciplayer sets it on pause and close, clears it on start */

#ifdef PEQ_HOST /* tools/test_peq.py */
#include <stdio.h>
#include <string.h>
#else
int snprintf(char *, unsigned, const char *, ...), sscanf(const char *, const char *, ...);
void *memcpy(void *, const void *, unsigned), *memset(void *, int, unsigned);
char *strstr(const char *, const char *);
#endif

/* ffmpeg's argv into a (27 slots) for frames from second at; ss holds the start. The picture is
 * fitted into the landscape H x W view, then turned clockwise onto the portrait framebuffer. Without
 * audio there is no sound output. */
void ffmpeg_argv(const char **a, char *ss, int at, const char *file, int audio) {
    snprintf(ss, 16, "%d", at);
    const char *v[27] = { FFMPEG, "-nostdin", "-loglevel", "quiet", "-ss", ss, "-i", file,
                          "-map", "0:v:0", "-vf",
                          "scale=375:320:force_original_aspect_ratio=decrease:flags=fast_bilinear,"
                          "format=bgra,pad=375:320:(ow-iw)/2:(oh-ih)/2,transpose=clock",
                          "-r", "25", "-f", "rawvideo", "pipe:3",
                          "-map", "0:a:0", "-ac", "2", "-ar", "48000", "-f", "s16le", "pipe:4", 0 };
    memcpy(a, v, sizeof v);
    if (!audio) a[17] = 0;
}

/* hciplayer's Bluetooth soft volume (its mixer_setvolume, 0x428744) for demo's volume v, 0-100,
 * in 1/65536: 0.002 v under 50, then 0.1 + 0.018 (v - 50), 1 at 100. */
int bt_gain(int v) {
    v = v < 0 ? 0 : v > 100 ? 100 : v;
    return 65536 * (v < 50 ? 2 * v : 18 * v - 800) / 1000;
}

/* n samples times gain g (at most 65536, so no sample overflows). */
void scale(short *s, unsigned n, int g) {
    for (unsigned i = 0; i < n; ++i) s[i] = (short)(s[i] * g >> 16);
}

/* The seconds in ffmpeg's "Duration: HH:MM:SS.ss" line; 0 without one. */
int duration(const char *s) {
    int h, m, sec;
    s = strstr(s, "Duration: ");
    return s && sscanf(s + 10, "%d:%d:%d", &h, &m, &sec) == 3 ? h * 3600 + m * 60 + sec : 0;
}

/* The overlay on framebuffer page f, line bytes a row: a bar along the picture's bottom, white for
 * n of total, black for the rest. The picture is turned clockwise (picture x is panel y), so the
 * bar runs down the panel's columns BAR_Y to BAR_Y + BAR_H. */
void overlay(unsigned char *f, unsigned line, int n, int total) {
    int end = H - BAR_X;
    if (total <= 0) return;
    n = n < 0 ? 0 : n > total ? total : n;
    int fill = BAR_X + (end - BAR_X) * n / total; /* total: seconds, far below overflow */
    for (int y = BAR_X; y < end; ++y) memset(f + y * line + BAR_Y * 4, y < fill ? 0xff : 0, BAR_H * 4);
}

/* Frame n's fate at clock ms: 0 wait, 1 show, 2 drop (a whole frame late). */
int frame_due(int n, long long clock) {
    long long due = (long long)n * 1000 / FPS;
    return clock < due ? 0 : clock < due + 1000 / FPS ? 1 : 2;
}

#ifndef PEQ_HOST
struct timespec {
    long sec, nsec;
};
struct pollfd {
    int fd;
    short events, revents;
};
struct sockaddr_un {
    unsigned short family;
    char path[108];
};
int open(const char *, int, ...), close(int), read(int, void *, unsigned), ioctl(int, unsigned, ...);
int fork(void), execv(const char *, const char *const *), waitpid(int, int *, int), kill(int, int);
int dup2(int, int), pipe2(int *, int), fcntl(int, int, ...), poll(struct pollfd *, unsigned, int);
int socket(int, int, int), bind(int, const void *, unsigned), recv(int, void *, unsigned, int);
int atoi(const char *), unlink(const char *), usleep(unsigned), clock_gettime(int, struct timespec *), strcmp(const char *, const char *);
void *mmap(void *, unsigned, int, int, int, long), *malloc(unsigned), (*signal(int, void (*)(int)))(int);
void _exit(int) __attribute__((noreturn));
int pthread_create(unsigned long *, const void *, void *(*)(void *), void *), pthread_join(unsigned long, void **);
int snd_pcm_open(void **, const char *, int, int), snd_pcm_close(void *), snd_pcm_drop(void *);
int snd_pcm_set_params(void *, int, int, unsigned, unsigned, int, unsigned), snd_pcm_prepare(void *);
int snd_pcm_recover(void *, int, int), snd_pcm_delay(void *, long *);
long snd_pcm_writei(void *, const void *, unsigned long);
int __libc_start_main(int (*)(int, char **), int, char **, void *, void *, void *, void *);

#define O_RDWR 2
#define O_CLOEXEC 0x80000
#define SIGKILL 9
#define SIGCHLD 18
#define AF_UNIX 1
#define SOCK_DGRAM 1 /* MIPS swaps it with SOCK_STREAM */
#define F_SETPIPE_SZ 1031
#define FBIOGET_VSCREENINFO 0x4600
#define FBIOGET_FSCREENINFO 0x4602
#define FBIOPAN_DISPLAY 0x4606

static struct {
    void *pcm;
    int fd;                /* ffmpeg's sound */
    int gain;              /* bt_gain's, 65536 on the DAC */
    volatile int paused;   /* the main loop's; the writer holds back */
    volatile int done;     /* the sound ended: the rest goes on the monotonic clock */
    volatile long played;  /* frames heard since this ffmpeg started */
} au;

static void *writer(void *unused) {
    (void)unused;
    short buf[2 * CHUNK];
    long written = 0, delay;
    for (;;) {
        for (unsigned got = 0; got < sizeof buf;) {
            int r = read(au.fd, (char *)buf + got, sizeof buf - got);
            if (r <= 0) return au.played = written, au.done = 1, (void *)0;
            got += (unsigned)r;
        }
        while (au.paused) usleep(20000);
        if (au.gain < 65536) scale(buf, 2 * CHUNK, au.gain);
        long r = snd_pcm_writei(au.pcm, buf, CHUNK);
        if (r < 0 && !snd_pcm_recover(au.pcm, (int)r, 1)) r = snd_pcm_writei(au.pcm, buf, CHUNK);
        if (r > 0) written += r;
        au.played = !snd_pcm_delay(au.pcm, &delay) && delay > 0 && delay < written ? written - delay
                                                                                 : written;
    }
}

static long long now_ms(void) {
    struct timespec t;
    clock_gettime(1, &t); /* CLOCK_MONOTONIC */
    return (long long)t.sec * 1000 + t.nsec / 1000000;
}

int main(int argc, char **argv) {
    if (argc < 3) return 2;
    for (int fd = 3; fd < 1024; ++fd) close(fd); /* demo's, inherited */
    signal(SIGCHLD, 0); /* SIG_DFL, so waitpid sees ffmpeg */
    unsigned var[40], fix[17];
    int fb = open("/dev/fb0", O_RDWR | O_CLOEXEC);
    if (fb < 0 || ioctl(fb, FBIOGET_VSCREENINFO, var) || ioctl(fb, FBIOGET_FSCREENINFO, fix)) return 1;
    unsigned line = fix[11], row = W * 4, y0 = var[5], back = y0 ? 0 : H; /* demo's other page */
    /* anything but the Q2's xres, yres, yres_virtual, bpp and red offset: no drawing */
    if (var[0] != W || var[1] != H || var[3] < 2 * H || var[6] != 32 || var[8] != 16 || row > line ||
        2 * H * line > fix[5])
        return 1;
    unsigned char *mem = mmap(0, fix[5], 3, 1, fb, 0), *frame = malloc(row * H);
    if (mem == (void *)-1 || !frame) return 1;
    int sock = socket(AF_UNIX, SOCK_DGRAM | O_CLOEXEC, 0);
    struct sockaddr_un addr = { AF_UNIX, Q2VIDEO_SOCK };
    unlink(Q2VIDEO_SOCK);
    bind(sock, &addr, sizeof addr);
    int dac = -1, off = 0, on = 1;
    au.gain = argc > 3 ? bt_gain(atoi(argv[3])) : 65536; /* Bluetooth: hciplayer's soft volume, no DAC */
    if (strcmp(argv[1], "-")) {
        /* hciplayer lets go of the device, muting the DAC, a moment after demo's stop */
        for (int i = 0; i < 20 && snd_pcm_open(&au.pcm, argv[1], 0, 0); ++i) au.pcm = 0, usleep(100000);
        if (au.pcm && snd_pcm_set_params(au.pcm, 2, 3, 2, RATE, 1, LATENCY)) /* S16_LE, RW_INTERLEAVED */
            snd_pcm_close(au.pcm), au.pcm = 0;
        if (au.pcm && argc < 4 && (dac = open(DAC, O_RDWR | O_CLOEXEC)) >= 0)
            ioctl(dac, DAC_PCM, &off), ioctl(dac, DAC_MUTE, &off);
    }
    /* ffmpeg -i alone, meanwhile, for the length the position bar needs */
    char info[4096];
    int at = 0, audio = au.pcm != 0, first = 1, quit = 0, held = 0, pp[2] = { -1, -1 }, got = 0;
    int len = 0, vol = 0, pos_bar = 0, redraw = 0, probe = pipe2(pp, O_CLOEXEC) ? -1 : fork();
    long long until = 0;
    if (!probe) {
        const char *pa[] = { FFMPEG, "-nostdin", "-hide_banner", "-i", argv[2], 0 };
        dup2(pp[1], 2);
        execv(FFMPEG, pa);
        _exit(127);
    }
    close(pp[1]);
    while (!quit) {
        int vp[2], ap[2] = { -1, -1 };
        if (pipe2(vp, O_CLOEXEC) || (audio && pipe2(ap, O_CLOEXEC))) break;
        fcntl(vp[0], F_SETPIPE_SZ, 4 << 20); /* frames ahead, so the sound paces ffmpeg */
        const char *args[27];
        char ss[16];
        ffmpeg_argv(args, ss, at, argv[2], audio);
        int pid = fork();
        if (!pid) {
            dup2(vp[1], 3);
            if (audio) dup2(ap[1], 4);
            execv(FFMPEG, args);
            _exit(127);
        }
        close(vp[1]);
        unsigned long thread = 0;
        if (audio) {
            close(ap[1]);
            au.fd = ap[0];
            au.played = au.done = 0;
            if (pthread_create(&thread, 0, writer, 0)) thread = 0;
        }
        int n = 0, seek = 0, ended = pid < 0, paced = audio;
        au.paused = held;
        unsigned have = 0, size = row * H;
        long long wall = 0, last = now_ms(), seek_at = 0;
        while (!ended && !quit) {
            long long t = now_ms(), clock;
            if (!au.paused) wall += t - last;
            last = t;
            if (paced && au.done) paced = 0, wall = (long long)au.played * 1000 / RATE;
            clock = paced ? (long long)au.played * 1000 / RATE : wall;
            if (until && t >= until) until = 0, redraw = au.paused;
            int wait = 100, fate = have == size ? frame_due(n, clock) : 0;
            if (fate == 1 || (redraw && have == size)) { /* paused, the next frame shows the change */
                for (unsigned y = 0; y < H; ++y)
                    memcpy(mem + (back + y) * line, frame + y * row, row);
                if (until)
                    overlay(mem + back * line, line, pos_bar ? at + seek + n / FPS : vol,
                            pos_bar ? len : 100);
                var[5] = back; /* draw the hidden page and pan, as demo does */
                ioctl(fb, FBIOPAN_DISPLAY, var);
                back = back ? 0 : H;
                redraw = 0;
            }
            if (fate) {
                ++n, have = 0;
                continue;
            }
            if (have == size && !au.paused) wait = (int)((long long)n * 1000 / FPS - clock) + 1;
            if (seek && seek_at - t < wait) wait = (int)(seek_at - t);
            if (seek && wait <= 0) break;
            /* POLLIN; poll skips the probe's -1 once it is read */
            struct pollfd p[3] = { { sock, 1, 0 }, { pp[0], 1, 0 }, { vp[0], 1, 0 } };
            poll(p, have < size ? 3 : 2, wait < 100 ? wait : 100);
            char c[2] = { 0 };
            if (p[0].revents && recv(sock, c, 2, 0) > 0) {
                if (c[0] == 'p') au.paused = !au.paused;
                if (c[0] == 'f' || c[0] == 'b') seek += c[0] == 'f' ? SEEK_S : -SEEK_S, seek_at = t + SEEK_WAIT_MS;
                if (c[0] == 'v') vol = (unsigned char)c[1], au.gain = argc > 3 ? bt_gain(vol) : 65536;
                if (c[0] && c[0] != 'p' && c[0] != 'q') /* s, f, b, v: the bar */
                    pos_bar = c[0] != 'v', until = t + OVERLAY_MS, redraw = au.paused;
                quit = c[0] == 'q';
            }
            if (p[1].revents) {
                int r = read(pp[0], info + got, sizeof info - 1 - (unsigned)got);
                if (r > 0) got += r;
                if (r <= 0 || got == sizeof info - 1) {
                    info[got] = 0, len = duration(info);
                    close(pp[0]), pp[0] = -1;
                    if (probe > 0) kill(probe, SIGKILL), waitpid(probe, 0, 0);
                }
            }
            if (have < size && p[2].revents) {
                int r = read(vp[0], frame + have, size - have);
                ended = r <= 0;
                if (r > 0) have += (unsigned)r;
            }
        }
        if (pid > 0) kill(pid, SIGKILL), waitpid(pid, 0, 0);
        held = au.paused && !quit; /* a seek keeps the pause, showing its first frame */
        au.paused = 0;             /* so the writer reads to the end and stops */
        if (thread) pthread_join(thread, 0);
        close(vp[0]);
        if (audio) close(ap[0]), snd_pcm_drop(au.pcm), snd_pcm_prepare(au.pcm);
        if (seek) {
            at += n / FPS + seek;
            at = at < 0 ? 0 : at;
        } else if (!n && first && audio)
            audio = 0; /* no sound stream: once more, silent, on the clock */
        else
            break;
        first = 0;
    }
    if (au.pcm) snd_pcm_close(au.pcm);
    if (dac >= 0) ioctl(dac, DAC_MUTE, &on); /* as hciplayer leaves it stopped */
    if (var[5] != y0) var[5] = y0, ioctl(fb, FBIOPAN_DISPLAY, var);
    unlink(Q2VIDEO_SOCK);
    return 0;
}

/* glibc's MIPS __start: main, argc, argv, no init or fini, the loader's rtld_fini, stack_end. */
__asm__(".set noreorder\n.globl __start\n__start:\n"
        "lui $28, %hi(_gp)\naddiu $28, $28, %lo(_gp)\n"
        "move $31, $0\nlw $5, 0($29)\naddiu $6, $29, 4\n"
        "li $8, -8\nand $29, $29, $8\naddiu $29, $29, -32\n"
        "lui $4, %hi(main)\naddiu $4, $4, %lo(main)\nmove $7, $0\n"
        "sw $0, 16($29)\nsw $2, 20($29)\nsw $29, 24($29)\n"
        "jal __libc_start_main\nnop\n1: b 1b\nnop\n.set reorder\n");
#endif
