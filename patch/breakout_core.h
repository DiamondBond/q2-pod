/* SPDX-License-Identifier: GPL-3.0-or-later
 * Original, portable Breakout rules; no heap, OS APIs or floating point.
 */
#ifndef Q2_BREAKOUT_CORE_H
#define Q2_BREAKOUT_CORE_H
#include <stdint.h>
#define Q2_BREAKOUT_COLUMNS 8
#define Q2_BREAKOUT_ROWS 5
#define Q2_BREAKOUT_PADDLE_W 48
typedef struct {
    uint8_t bricks[Q2_BREAKOUT_ROWS][Q2_BREAKOUT_COLUMNS];
    int ball_x, ball_y, dx, dy, paddle_x;
    unsigned score, level, lives, remaining;
    int waiting, game_over;
} Q2Breakout;
void q2_breakout_init(Q2Breakout *b);
void q2_breakout_move(Q2Breakout *b, int pixels);
void q2_breakout_launch(Q2Breakout *b);
void q2_breakout_tick(Q2Breakout *b);
#endif
