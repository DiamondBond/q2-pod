/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "breakout_core.h"

/* 320x240 arena; fixed 8x5 bricks and a 48px paddle at y=220. */
#define ARENA_W 320
#define ARENA_H 240
#define PADDLE_Y 220
#define BRICK_X 16
#define BRICK_Y 27
#define BRICK_W 33
#define BRICK_H 13
#define BRICK_GAP 3

static int clip(int v, int low, int high) {
    return v < low ? low : v > high ? high : v;
}

static void new_wall(Q2Breakout *b) {
    b->remaining = Q2_BREAKOUT_ROWS * Q2_BREAKOUT_COLUMNS;
    for (int r = 0; r < Q2_BREAKOUT_ROWS; ++r)
        for (int c = 0; c < Q2_BREAKOUT_COLUMNS; ++c)
            b->bricks[r][c] = (uint8_t)(r + 1);
}

static void serve(Q2Breakout *b) {
    b->waiting = 1;
    b->paddle_x = clip(b->paddle_x, 0, ARENA_W - Q2_BREAKOUT_PADDLE_W);
    b->ball_x = b->paddle_x + Q2_BREAKOUT_PADDLE_W / 2;
    b->ball_y = PADDLE_Y - 6;
    b->dx = b->level & 1u ? 2 : -2;
    b->dy = -3;
}

void q2_breakout_init(Q2Breakout *b) {
    /* Explicit init avoids platform-specific padding. */
    b->score = 0;
    b->level = 1;
    b->lives = 3;
    b->game_over = 0;
    b->paddle_x = (ARENA_W - Q2_BREAKOUT_PADDLE_W) / 2;
    new_wall(b);
    serve(b);
}

void q2_breakout_move(Q2Breakout *b, int pixels) {
    if (b->game_over) return;
    /* Avoid signed overflow on large wheel travel. */
    if (pixels > ARENA_W) pixels = ARENA_W;
    if (pixels < -ARENA_W) pixels = -ARENA_W;
    b->paddle_x = clip(b->paddle_x + pixels, 0, ARENA_W - Q2_BREAKOUT_PADDLE_W);
    if (b->waiting) b->ball_x = b->paddle_x + Q2_BREAKOUT_PADDLE_W / 2;
}

void q2_breakout_launch(Q2Breakout *b) {
    if (!b->game_over) b->waiting = 0;
}

void q2_breakout_tick(Q2Breakout *b) {
    if (b->game_over || b->waiting) return;
    const int last_x = b->ball_x, last_y = b->ball_y;
    b->ball_x += b->dx;
    b->ball_y += b->dy;

    if (b->ball_x < 4) { b->ball_x = 4; b->dx = -b->dx; }
    if (b->ball_x > ARENA_W - 5) { b->ball_x = ARENA_W - 5; b->dx = -b->dx; }
    if (b->ball_y < 4) { b->ball_y = 4; b->dy = -b->dy; }

    /* Resolve at most one brick per step; bounce along the face we crossed. */
    for (int row = 0; row < Q2_BREAKOUT_ROWS; ++row)
        for (int column = 0; column < Q2_BREAKOUT_COLUMNS; ++column) {
            if (!b->bricks[row][column]) continue;
            const int x = BRICK_X + column * (BRICK_W + BRICK_GAP);
            const int y = BRICK_Y + row * (BRICK_H + BRICK_GAP);
            if (b->ball_x + 3 < x || b->ball_x - 3 >= x + BRICK_W ||
                b->ball_y + 3 < y || b->ball_y - 3 >= y + BRICK_H)
                continue;
            b->bricks[row][column] = 0;
            --b->remaining;
            b->score += (unsigned)(Q2_BREAKOUT_ROWS - row) * 10u;
            if (last_x + 3 <= x || last_x - 3 >= x + BRICK_W)
                b->dx = -b->dx;
            else
                b->dy = -b->dy;
            if (!b->remaining) {
                ++b->level;
                new_wall(b);
                serve(b);
            }
            return;
        }

    if (b->dy > 0 && last_y + 3 <= PADDLE_Y &&
        b->ball_y + 3 >= PADDLE_Y &&
        b->ball_x + 3 >= b->paddle_x &&
        b->ball_x - 3 <= b->paddle_x + Q2_BREAKOUT_PADDLE_W) {
        const int relative = b->ball_x - b->paddle_x - Q2_BREAKOUT_PADDLE_W / 2;
        int vx = clip(relative / 7, -4, 4);
        if (!vx) vx = b->dx < 0 ? -1 : 1;
        b->dx = vx;
        b->dy = -3 - (int)((b->level - 1) / 3 > 2 ? 2 : (b->level - 1) / 3);
        b->ball_y = PADDLE_Y - 4;
    }

    if (b->ball_y > ARENA_H + 4) {
        if (--b->lives == 0) b->game_over = 1;
        else serve(b);
    }
}
