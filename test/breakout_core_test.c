/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "../patch/breakout_core.h"
#include <assert.h>
#include <stdio.h>

static void test_gameplay(void) {
    Q2Breakout b;
    q2_breakout_init(&b);
    assert(b.remaining == 40 && b.score == 0 && b.lives == 3);
    assert(b.waiting && b.level == 1 && !b.game_over);
    q2_breakout_move(&b, -100000);
    assert(b.paddle_x == 0 && b.ball_x == 24);
    q2_breakout_move(&b, 100000);
    assert(b.paddle_x == 272 && b.ball_x == 296);
    q2_breakout_launch(&b);
    assert(!b.waiting);
    /* A brick disappears and the running score increases. */
    b.ball_x = 20; b.ball_y = 41; b.dx = 0; b.dy = -3;
    q2_breakout_tick(&b);
    assert(b.bricks[0][0] == 0 && b.remaining == 39 && b.score == 50);
    /* Paddle collision reflects the descending ball. */
    b.ball_x = b.paddle_x + 24;
    b.ball_y = 216; b.dy = 3;
    q2_breakout_tick(&b);
    assert(b.dy < 0);
    /* A missed ball costs exactly one life and docks the next serve. */
    b.ball_y = 244; b.dy = 3;
    q2_breakout_tick(&b);
    assert(b.lives == 2 && b.waiting && !b.game_over);
    /* Clear the last brick to advance to the next level, indefinitely. */
    for (int r = 0; r < Q2_BREAKOUT_ROWS; ++r)
        for (int c = 0; c < Q2_BREAKOUT_COLUMNS; ++c)
            b.bricks[r][c] = 0;
    b.bricks[0][0] = 1;
    b.remaining = 1;
    q2_breakout_launch(&b);
    b.ball_x = 20; b.ball_y = 41; b.dx = 0; b.dy = -3;
    q2_breakout_tick(&b);
    assert(b.level == 2 && b.remaining == 40 && b.waiting);
    assert(b.score == 100);
    b.lives = 1;
    q2_breakout_launch(&b);
    b.ball_y = 244; b.dy = 3;
    q2_breakout_tick(&b);
    assert(b.game_over && b.lives == 0);
    q2_breakout_init(&b);
    assert(!b.game_over && b.score == 0 && b.lives == 3);
}

int main(void) {
    test_gameplay();
    puts("breakout_core: all tests passed");
    return 0;
}
