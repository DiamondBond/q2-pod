/* q2video, Videos' player (docs/internals.md#videos): /usr/bin/q2video DEVICE FILE, started by
 * demo (books.c video_play). Stock ffmpeg decodes FILE, fits it into the screen, turns it onto the
 * portrait panel as the boot logo is stored and converts it to the framebuffer's pixel format,
 * frames on one pipe and 48 kHz stereo on another; this plays the sound on ALSA DEVICE ("-" for
 * none) and puts each frame on /dev/fb0 when the sound reaches it, dropping late ones. demo sends
 * keys as single bytes to Q2VIDEO_SOCK: p pause, f and b seek SEEK_S, q quit. No MIPS sysroot:
 * the declarations below are glibc 2.28's and alsa-lib's, with MIPS o32 constants. */
#define FPS 25
#define RATE 48000
#define CHUNK 512      /* frames per ALSA write: the audio clock's step, about 11 ms */
#define LATENCY 200000 /* ALSA buffer, us */
#define SEEK_S 10
#define SEEK_WAIT_MS 400 /* a run of wheel ticks restarts ffmpeg once */
#define Q2VIDEO_SOCK "/tmp/q2video.sock"
#define FFMPEG "/usr/bin/ffmpeg"
#define DAC "/dev/shanling_dac"
#define DAC_PCM 0xc0044d1bu  /* hciplayer sets it to 0 for each PCM track: undoes a DSD one */
#define DAC_MUTE 0xc0044d1fu /* hciplayer sets it on pause and close, clears it on start */

#ifdef PEQ_HOST /* tools/test_peq.py */
#include <stdio.h>
#include <string.h>
#else
int snprintf(char *, unsigned, const char *, ...);
void *memcpy(void *, const void *, unsigned);
#endif

/* ffmpeg's pixel format for a bpp-bit framebuffer whose red field starts at bit red; 0 if none. */
const char *pixfmt(unsigned bpp, unsigned red) {
    if (bpp == 32) return red == 16 ? "bgra" : red == 0 ? "rgba" : 0;
    if (bpp == 24) return red == 16 ? "bgr24" : red == 0 ? "rgb24" : 0;
    if (bpp == 16) return red == 11 ? "rgb565le" : red == 0 ? "bgr565le" : 0;
    return 0;
}

/* ffmpeg's argv into a (27 slots) for frames w x h in fmt from second at; vf and ss hold its
 * filter and start. A portrait framebuffer gets the picture fitted into its landscape view, then
 * turned clockwise. Without audio there is no sound output. */
void ffmpeg_argv(const char **a, char *vf, char *ss, int w, int h, const char *fmt, int at,
                 const char *file, int audio) {
    int turn = w < h, vw = turn ? h : w, vh = turn ? w : h;
    snprintf(ss, 16, "%d", at);
    snprintf(vf, 256,
             "scale=%d:%d:force_original_aspect_ratio=decrease:flags=fast_bilinear,format=%s,"
             "pad=%d:%d:(ow-iw)/2:(oh-ih)/2%s",
             vw, vh, fmt, vw, vh, turn ? ",transpose=clock" : "");
    const char *v[27] = { FFMPEG, "-nostdin", "-loglevel", "quiet", "-ss", ss, "-i", file,
                          "-map", "0:v:0", "-vf", vf, "-r", "25", "-f", "rawvideo", "pipe:3",
                          "-map", "0:a:0", "-ac", "2", "-ar", "48000", "-f", "s16le", "pipe:4", 0 };
    memcpy(a, v, sizeof v);
    if (!audio) a[17] = 0;
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
int unlink(const char *), usleep(unsigned), clock_gettime(int, struct timespec *), strcmp(const char *, const char *);
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
    unsigned w = var[0], h = var[1], line = fix[11], row = w * (var[6] / 8), y0 = var[5];
    const char *fmt = pixfmt(var[6], var[8]);
    unsigned char *mem = mmap(0, fix[5], 3, 1, fb, 0), *frame = malloc(row * h);
    if (!fmt || mem == (void *)-1 || !frame || row > line) return 1;
    /* Two pages: draw the hidden one and pan, then leave demo's showing again. */
    unsigned back = var[3] >= 2 * h && 2 * h * line <= fix[5] ? (y0 ? 0 : h) : y0;
    int sock = socket(AF_UNIX, SOCK_DGRAM | O_CLOEXEC, 0);
    struct sockaddr_un addr = { AF_UNIX, Q2VIDEO_SOCK };
    unlink(Q2VIDEO_SOCK);
    bind(sock, &addr, sizeof addr);
    int dac = -1, off = 0, on = 1;
    if (strcmp(argv[1], "-")) {
        /* hciplayer lets go of the device, muting the DAC, a moment after demo's stop */
        for (int i = 0; i < 20 && snd_pcm_open(&au.pcm, argv[1], 0, 0); ++i) au.pcm = 0, usleep(100000);
        if (au.pcm && snd_pcm_set_params(au.pcm, 2, 3, 2, RATE, 1, LATENCY)) /* S16_LE, RW_INTERLEAVED */
            snd_pcm_close(au.pcm), au.pcm = 0;
        if (au.pcm && (dac = open(DAC, O_RDWR | O_CLOEXEC)) >= 0)
            ioctl(dac, DAC_PCM, &off), ioctl(dac, DAC_MUTE, &off);
    }
    int at = 0, audio = au.pcm != 0, first = 1, quit = 0, held = 0;
    while (!quit) {
        int vp[2], ap[2] = { -1, -1 };
        if (pipe2(vp, O_CLOEXEC) || (audio && pipe2(ap, O_CLOEXEC))) break;
        fcntl(vp[0], F_SETPIPE_SZ, 4 << 20); /* frames ahead, so the sound paces ffmpeg */
        const char *args[27];
        char vf[256], ss[16];
        ffmpeg_argv(args, vf, ss, (int)w, (int)h, fmt, at, argv[2], audio);
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
        unsigned have = 0, size = row * h;
        long long wall = 0, last = now_ms(), seek_at = 0;
        while (!ended && !quit) {
            long long t = now_ms(), clock;
            if (!au.paused) wall += t - last;
            last = t;
            if (paced && au.done) paced = 0, wall = (long long)au.played * 1000 / RATE;
            clock = paced ? (long long)au.played * 1000 / RATE : wall;
            int wait = 100, fate = have == size ? frame_due(n, clock) : 0;
            if (fate) {
                if (fate == 1) {
                    for (unsigned y = 0; y < h; ++y)
                        memcpy(mem + (back + y) * line, frame + y * row, row);
                    if (back != y0 || var[5] != y0) {
                        var[5] = back;
                        ioctl(fb, FBIOPAN_DISPLAY, var);
                        back = back ? 0 : h;
                    }
                }
                ++n, have = 0;
                continue;
            }
            if (have == size && !au.paused) wait = (int)((long long)n * 1000 / FPS - clock) + 1;
            if (seek && seek_at - t < wait) wait = (int)(seek_at - t);
            if (seek && wait <= 0) break;
            struct pollfd p[2] = { { sock, 1, 0 }, { vp[0], 1, 0 } }; /* POLLIN */
            poll(p, have < size ? 2 : 1, wait < 100 ? wait : 100);
            char c = 0;
            if (p[0].revents && recv(sock, &c, 1, 0) == 1) {
                if (c == 'p') au.paused = !au.paused;
                if (c == 'f' || c == 'b') seek += c == 'f' ? SEEK_S : -SEEK_S, seek_at = t + SEEK_WAIT_MS;
                quit = c == 'q';
            }
            if (have < size && p[1].revents) {
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
