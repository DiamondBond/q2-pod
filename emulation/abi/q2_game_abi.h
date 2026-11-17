/* SPDX-License-Identifier: GPL-3.0-or-later
 * Experimental Q2 game guest ABI v1. All members use MIPS little-endian layout.
 * Host draws generic commands; it does NOT call a game-specific Python adapter.
 */
#ifndef Q2_GAME_ABI_H
#define Q2_GAME_ABI_H
#include <stdint.h>
#define Q2G_ABI_VERSION 1u
#define Q2G_MAX_COMMANDS 128u
#define Q2G_CLEAR 1u
#define Q2G_RECT 2u
#define Q2G_TEXT 3u
#define Q2G_CIRCLE 4u
#define Q2G_WHEEL 1u
#define Q2G_CENTER 2u
#define Q2G_PREV 3u
#define Q2G_NEXT 4u
#define Q2G_PLAY 5u
#define Q2G_RETURN 6u
typedef struct {
    uint32_t type;
    int32_t x, y, w, h;
    uint32_t color; /* RRGGBB */
    char text[64]; /* UTF-8, NUL-terminated, only for Q2G_TEXT */
} Q2GDrawCommand;
typedef struct {
    uint32_t count;
    Q2GDrawCommand commands[Q2G_MAX_COMMANDS];
} Q2GDrawList;
/* Each game exports exactly these six functions; no Python modifications. */
uint32_t q2g_version(void);
const char *q2g_name(void);
void q2g_init(uint32_t seed);
void q2g_input(uint32_t action, int32_t value);
void q2g_step(uint32_t elapsed_ms);
const Q2GDrawList *q2g_render(void);
#endif
