#ifndef Q2_CHAPTERS_H
#define Q2_CHAPTERS_H
#define CHAPTER_MAX 512
#define CHAPTER_BYTES (256 * 1024)
typedef struct { int sec; char title[256]; } chapter;
typedef struct {
    int pid, fd, used, done, failed, count;
    unsigned long long at;
    chapter rows[CHAPTER_MAX];
    char raw[CHAPTER_BYTES + 1];
} chapters;
int chapters_parse(char *raw, chapter *rows);
chapters *chapters_start(const char *path, unsigned long long now);
int chapters_poll(chapters *c, unsigned long long now); /* 0 running, 1 done */
void chapters_cancel(chapters *c); /* poll until reaped, then free */
#endif
