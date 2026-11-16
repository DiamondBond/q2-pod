/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "../patch/arcade_core.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static void test_pong(void)
{
    Q2Pong p;
    q2_pong_init(&p);
    assert(p.ball_x == 160 && p.player_y == 96);
    q2_pong_move(&p, -999);
    assert(p.player_y == 0);
    q2_pong_move(&p, 999);
    assert(p.player_y == 192);
    for (int i = 0; i < 2000; ++i) q2_pong_tick(&p);
    assert(p.player_score + p.cpu_score > 0);
    assert(p.player_y >= 0 && p.player_y <= 192);
    assert(p.cpu_y >= 0 && p.cpu_y <= 192);
}
static void test_blocks(void)
{
    Q2Blocks g;
    q2_blocks_init(&g, 42);
    assert(g.level == 1 && !g.game_over && g.piece < 7 && g.next < 7);
    int blocks = 0;
    for (int y = 0; y < Q2_BOARD_H; ++y)
        for (int x = 0; x < Q2_BOARD_W; ++x)
            blocks += q2_blocks_cell(&g, x, y) != 0;
    assert(blocks > 0);
    int preview = 0;
    for (int y = 0; y < 4; ++y)
        for (int x = 0; x < 4; ++x)
            preview += q2_blocks_next_cell(&g, x, y) != 0;
    assert(preview == 4);
    for (int i = 0; i < 100; ++i) q2_blocks_move(&g, -1);
    assert(g.x >= -1); /* some shapes have an empty leftmost column */
    q2_blocks_rotate(&g);
    assert(q2_blocks_drop(&g) >= 0);
    assert(g.score <= 1000); /* first hard drop, no arbitrary score spike */
    for (int i = 0; i < 100 && !g.game_over; ++i) q2_blocks_drop(&g);
    assert(g.game_over); /* stacking without moving must eventually lose */
}
static void test_bag(void)
{
    Q2Blocks g;
    q2_blocks_init(&g, 99);
    unsigned seen = 1u << g.piece;
    for (int i = 0; i < 6; ++i) {
        /* Force a new piece without testing internal functions. */
        memset(g.board, 0, sizeof g.board);
        q2_blocks_drop(&g);
        seen |= 1u << g.piece;
    }
    assert(seen == 0x7fu);
}
int main(void)
{
    test_pong();
    test_blocks();
    test_bag();
    puts("arcade_core: all tests passed");
    return 0;
}
