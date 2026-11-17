/* Freestanding MIPS image for the desktop game runner. */
#include <stddef.h>

void *memset(void *dest, int byte, size_t size) {
    unsigned char *out = dest;
    for (size_t i = 0; i < size; ++i) out[i] = (unsigned char)byte;
    return dest;
}

void *memcpy(void *dest, const void *src, size_t size) {
    unsigned char *out = dest;
    const unsigned char *in = src;
    for (size_t i = 0; i < size; ++i) out[i] = in[i];
    return dest;
}

#define PEQ_HOST
#define Q2_ARCADE_MIPS
#include "../patch/arcade_core.c"
#include "../patch/breakout_core.c"
#include "../patch/games.c"

/* These layouts are read by ctypes in arcade_mips.py. */
_Static_assert(sizeof(struct snake) == 816 && offsetof(struct snake, score) == 812,
               "Snake state layout");
_Static_assert(sizeof(struct vortex) == 44 && offsetof(struct vortex, brick) == 36,
               "Vortex state layout");

_Static_assert(sizeof(struct sudoku) == 92 && offsetof(struct sudoku, cell) == 4,
               "Sudoku state layout");
_Static_assert(sizeof(struct solitaire) == 336 && offsetof(struct solitaire, len) == 316,
               "Solitaire state layout");

void q2_snake_seed(unsigned seed) { games_seed = seed ? seed : 1; }

_Static_assert(sizeof(Q2Breakout) == 84 && offsetof(Q2Breakout, paddle_x) == 56,
               "Breakout state layout");
