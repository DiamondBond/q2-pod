/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef Q2_TILE2048_H
#define Q2_TILE2048_H

#include <stdint.h>

enum { Q2_2048_SIDE = 4, Q2_2048_CELLS = 16, Q2_2048_GOAL = 11, Q2_2048_MAX = 17 };
typedef enum { Q2_2048_UP, Q2_2048_RIGHT, Q2_2048_DOWN, Q2_2048_LEFT } Q22048Direction;

typedef struct {
    uint8_t tile[Q2_2048_CELLS]; /* 0 is empty, otherwise the exponent of two. */
    uint32_t score, best, rng;
    uint32_t won, continued;
} Q22048;

void q2_2048_new(Q22048 *game, uint32_t seed);
int q2_2048_slide(Q22048 *game, Q22048Direction direction);
int q2_2048_move(Q22048 *game, Q22048Direction direction);
int q2_2048_can_move(const Q22048 *game);
int q2_2048_valid(const Q22048 *game);

#endif
