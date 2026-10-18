#ifndef Q2_PLAYBACK_H
#define Q2_PLAYBACK_H
int playback_option(int kind); /* 0 shuffle, 1 repeat, 2 grouping */
unsigned rand_below(unsigned n);
int playback_set(int kind, int value);
int playback_groups(void *all, int folder);
int playback_unshuffle(void);   /* the stock mode Shuffle Songs replaces */
int playback_shuffle(int mode); /* the queue as Shuffle Songs, Repeat All; the next restores mode */
int playback_group_skip(int forward);
int playback_back(void); /* the track stock Shuffle's Previous left, once; else -1 */
unsigned playback_upcoming(unsigned *out, unsigned max); /* Up Next: queue indices, in play order */
void playback_insert(unsigned at, unsigned n, int next);
void playback_poll(void);
void playback_speed_start(void);
void xfade_poll(int next); /* crossfade.c */
int playback_resumed(void *r);
void playback_save(void);
void playback_clear(void);
int wheel_pct(void); /* Wheel sensitivity, 50-200% */
void wheel_set_pct(int n);
void wheel_guard_reset(void);
extern int wheel_guard; /* Volume guard: the screen-off wheel's half-turn guard, 0 off */
#endif
