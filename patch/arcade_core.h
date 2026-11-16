/* SPDX-License-Identifier: GPL-3.0-or-later
 * Portable game rules for Q2 Pod built-in Pong and falling-block game.
 * No framebuffer, audio, allocation, or platform dependencies.
 */
#ifndef Q2_ARCADE_CORE_H
#define Q2_ARCADE_CORE_H
#include <stdint.h>
#define Q2_BOARD_W 10
#define Q2_BOARD_H 20
typedef struct {
    int ball_x, ball_y, vel_x, vel_y;
    int player_y, cpu_y;
    unsigned player_score, cpu_score;
    unsigned rallies;
} Q2Pong;
void q2_pong_init(Q2Pong *p);
void q2_pong_move(Q2Pong *p, int steps);
void q2_pong_tick(Q2Pong *p);

typedef struct {
    uint8_t board[Q2_BOARD_H][Q2_BOARD_W];
    uint8_t piece, next, rotation;
    uint8_t bag[7], bag_pos;
    int x, y;
    uint32_t rng;
    unsigned score, lines, level;
    int game_over;
} Q2Blocks;
void q2_blocks_init(Q2Blocks *g, uint32_t seed);
int q2_blocks_move(Q2Blocks *g, int dx);
int q2_blocks_rotate(Q2Blocks *g);
int q2_blocks_tick(Q2Blocks *g); /* 0 moved, 1 locked, -1 game over */
int q2_blocks_drop(Q2Blocks *g); /* hard drop, returns rows travelled */
int q2_blocks_next_cell(const Q2Blocks *g, int x, int y); /* next-piece preview */
int q2_blocks_cell(const Q2Blocks *g, int x, int y); /* settled or active colour 1..7 */
#endif
