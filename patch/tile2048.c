/* SPDX-License-Identifier: GPL-3.0-or-later
 * 2048 rules by Gabriele Cirulli. Byte-sized exponents as used by
 * Maurits van der Schee's 2048.c. */
#include "tile2048.h"

static uint32_t random_word(Q22048 *game) {
    uint32_t value = game->rng;
    value ^= value << 13;
    value ^= value >> 17;
    value ^= value << 5;
    game->rng = value;
    return value;
}

static void spawn(Q22048 *game) {
    uint8_t empty[Q2_2048_CELLS];
    unsigned count = 0;
    for (unsigned i = 0; i < Q2_2048_CELLS; ++i)
        if (!game->tile[i]) empty[count++] = (uint8_t)i;
    if (!count) return;
    unsigned index = empty[random_word(game) % count];
    game->tile[index] = random_word(game) % 10 == 0 ? 2 : 1;
}

void q2_2048_new(Q22048 *game, uint32_t seed) {
    *game = (Q22048){ .best = game->best, .rng = seed ? seed : 1 };
    spawn(game);
    spawn(game);
}

static unsigned cell(Q22048Direction direction, unsigned line, unsigned offset) {
    switch (direction) {
    case Q2_2048_UP: return offset * Q2_2048_SIDE + line;
    case Q2_2048_RIGHT: return line * Q2_2048_SIDE + Q2_2048_SIDE - 1 - offset;
    case Q2_2048_DOWN: return (Q2_2048_SIDE - 1 - offset) * Q2_2048_SIDE + line;
    default: return line * Q2_2048_SIDE + offset;
    }
}

int q2_2048_slide(Q22048 *game, Q22048Direction direction) {
    int moved = 0;
    for (unsigned line = 0; line < Q2_2048_SIDE; ++line) {
        uint8_t packed[Q2_2048_SIDE], result[Q2_2048_SIDE] = {0};
        unsigned count = 0, output = 0;
        for (unsigned i = 0; i < Q2_2048_SIDE; ++i) {
            uint8_t tile = game->tile[cell(direction, line, i)];
            if (tile) packed[count++] = tile;
        }
        for (unsigned i = 0; i < count; ++i) {
            uint8_t tile = packed[i];
            if (i + 1 < count && tile == packed[i + 1] && tile < Q2_2048_MAX) {
                ++tile;
                ++i;
                game->score += 1u << tile;
                if (tile == Q2_2048_GOAL) game->won = 1;
            }
            result[output++] = tile;
        }
        for (unsigned i = 0; i < Q2_2048_SIDE; ++i) {
            unsigned index = cell(direction, line, i);
            moved |= game->tile[index] != result[i];
            game->tile[index] = result[i];
        }
    }
    if (game->score > game->best) game->best = game->score;
    return moved;
}

int q2_2048_move(Q22048 *game, Q22048Direction direction) {
    if ((game->won && !game->continued) || !q2_2048_slide(game, direction)) return 0;
    spawn(game);
    return 1;
}

int q2_2048_can_move(const Q22048 *game) {
    for (unsigned i = 0; i < Q2_2048_CELLS; ++i) {
        uint8_t tile = game->tile[i];
        if (!tile) return 1;
        if (tile == Q2_2048_MAX) continue;
        if (i % Q2_2048_SIDE != Q2_2048_SIDE - 1 && game->tile[i + 1] == tile) return 1;
        if (i + Q2_2048_SIDE < Q2_2048_CELLS && game->tile[i + Q2_2048_SIDE] == tile) return 1;
    }
    return 0;
}

int q2_2048_valid(const Q22048 *game) {
    unsigned count = 0;
    if (!game->rng || game->score > game->best || game->won > 1 || game->continued > game->won)
        return 0;
    for (unsigned i = 0; i < Q2_2048_CELLS; ++i) {
        uint8_t tile = game->tile[i];
        if (tile > Q2_2048_MAX || (tile >= Q2_2048_GOAL && !game->won)) return 0;
        count += tile != 0;
    }
    return count >= 2;
}
