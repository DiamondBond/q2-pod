#ifndef Q2_PLAYBACK_H
#define Q2_PLAYBACK_H
int playback_option(int kind); /* 0 shuffle, 1 repeat, 2 grouping */
int playback_set(int kind, int value);
int playback_groups(void *all, int folder);
int playback_group_skip(int forward);
void playback_insert(unsigned at, unsigned n, int next);
void playback_poll(void);
void xfade_poll(int next); /* crossfade.c */
int playback_resumed(void *r);
void playback_save(void);
void wheel_load(void);
#endif
