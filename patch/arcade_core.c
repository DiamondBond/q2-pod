/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "arcade_core.h"
/* Freestanding MIPS payload: avoid host-only libc headers. */
static void clear_bytes(void *dest, unsigned n) {
    unsigned char *p = dest;
    for (unsigned i = 0; i < n; ++i) p[i] = 0;
}
static void copy_bytes(void *dest, const void *src, unsigned n) {
    unsigned char *d = dest;
    const unsigned char *p = src;
    for (unsigned i = 0; i < n; ++i) d[i] = p[i];
}

static int clamp(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }

/* Fixed-size integer-only Pong arena, 320 x 240 coordinates. */
static void pong_serve(Q2Pong *p, int direction)
{
    p->ball_x = 160; p->ball_y = 120;
    p->vel_x = direction * 3;
    p->vel_y = (p->rallies & 1u) ? -2 : 2;
}
void q2_pong_init(Q2Pong *p)
{
    clear_bytes(p, sizeof *p);
    p->player_y = p->cpu_y = 96; /* 48-pixel paddle */
    pong_serve(p, -1);
}
void q2_pong_move(Q2Pong *p, int steps)
{
    p->player_y = clamp(p->player_y + steps, 0, 192);
}
void q2_pong_tick(Q2Pong *p)
{
    /* CPU reacts gradually; there are no sleeps or frame allocations. */
    int target = clamp(p->ball_y - 24, 0, 192);
    p->cpu_y += clamp(target - p->cpu_y, -2, 2);
    p->ball_x += p->vel_x;
    p->ball_y += p->vel_y;
    if (p->ball_y < 4) { p->ball_y = 4; p->vel_y = -p->vel_y; }
    if (p->ball_y > 235) { p->ball_y = 235; p->vel_y = -p->vel_y; }
    if (p->vel_x < 0 && p->ball_x <= 22 &&
        p->ball_y + 4 >= p->player_y && p->ball_y - 4 <= p->player_y + 48) {
        p->ball_x = 22; p->vel_x = -p->vel_x;
        p->vel_y = clamp((p->ball_y - p->player_y - 24) / 5, -5, 5);
        if (!p->vel_y) p->vel_y = 1;
        ++p->rallies;
    }
    if (p->vel_x > 0 && p->ball_x >= 298 &&
        p->ball_y + 4 >= p->cpu_y && p->ball_y - 4 <= p->cpu_y + 48) {
        p->ball_x = 298; p->vel_x = -p->vel_x;
        p->vel_y = clamp((p->ball_y - p->cpu_y - 24) / 6, -4, 4);
        if (!p->vel_y) p->vel_y = -1;
        ++p->rallies;
    }
    if (p->ball_x < -4) { ++p->cpu_score; pong_serve(p, -1); }
    if (p->ball_x > 324) { ++p->player_score; pong_serve(p, 1); }
}

/* Bits are a 4x4 grid, with the low nibble as the first row. */
static const uint16_t shapes[7] = {
    0x00f0, /* I */ 0x0660, /* O */ 0x0270, /* T */
    0x0360, /* S */ 0x0630, /* Z */ 0x0710, /* J */ 0x0740 /* L */
};
static uint32_t next_random(Q2Blocks *g)
{
    uint32_t x = g->rng;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    return g->rng = x;
}
static int piece_bit(unsigned piece, unsigned rotation, int x, int y)
{
    if (piece == 1) rotation = 0; /* O has no visible rotation */
    for (unsigned i = 0; i < rotation % 4; ++i) {
        int old_x = x;
        x = y; y = 3 - old_x;
    }
    return (shapes[piece] >> (y * 4 + x)) & 1u;
}
static int can_place(const Q2Blocks *g, int x, int y, unsigned rotation)
{
    for (int row = 0; row < 4; ++row)
        for (int col = 0; col < 4; ++col) {
            if (!piece_bit(g->piece, rotation, col, row)) continue;
            int bx = x + col, by = y + row;
            if (bx < 0 || bx >= Q2_BOARD_W || by >= Q2_BOARD_H) return 0;
            if (by >= 0 && g->board[by][bx]) return 0;
        }
    return 1;
}
static unsigned bag_next(Q2Blocks *g)
{
    if (g->bag_pos == 7) {
        for (unsigned i = 0; i < 7; ++i) g->bag[i] = (uint8_t)i;
        for (unsigned i = 6; i > 0; --i) {
            unsigned j = next_random(g) % (i + 1);
            uint8_t tmp = g->bag[i]; g->bag[i] = g->bag[j]; g->bag[j] = tmp;
        }
        g->bag_pos = 0;
    }
    return g->bag[g->bag_pos++];
}
static void spawn(Q2Blocks *g)
{
    g->piece = g->next;
    g->next = (uint8_t)bag_next(g);
    g->rotation = 0; g->x = 3; g->y = -1;
    if (!can_place(g, g->x, g->y, 0)) g->game_over = 1;
}
void q2_blocks_init(Q2Blocks *g, uint32_t seed)
{
    clear_bytes(g, sizeof *g);
    g->rng = seed ? seed : 0x12345678u;
    g->bag_pos = 7;
    g->level = 1;
    g->next = (uint8_t)bag_next(g);
    spawn(g);
}
int q2_blocks_move(Q2Blocks *g, int dx)
{
    if (g->game_over || !can_place(g, g->x + dx, g->y, g->rotation)) return 0;
    g->x += dx;
    return 1;
}
int q2_blocks_rotate_dir(Q2Blocks *g, int direction)
{
    if (g->game_over || !direction) return 0;
    unsigned rot = (g->rotation + (direction > 0 ? 1u : 3u)) % 4;
    const int kicks[] = {0, -1, 1, -2, 2};
    for (unsigned i = 0; i < sizeof kicks / sizeof kicks[0]; ++i)
        if (can_place(g, g->x + kicks[i], g->y, rot)) {
            g->x += kicks[i]; g->rotation = (uint8_t)rot;
            return 1;
        }
    return 0;
}
int q2_blocks_rotate(Q2Blocks *g) { return q2_blocks_rotate_dir(g, 1); }
int q2_blocks_tick(Q2Blocks *g)
{
    if (g->game_over) return -1;
    if (can_place(g, g->x, g->y + 1, g->rotation)) { ++g->y; return 0; }
    for (int row = 0; row < 4; ++row)
        for (int col = 0; col < 4; ++col)
            if (piece_bit(g->piece, g->rotation, col, row)) {
                int by = g->y + row, bx = g->x + col;
                if (by < 0) { g->game_over = 1; return -1; }
                g->board[by][bx] = (uint8_t)(g->piece + 1);
            }
    unsigned cleared = 0;
    for (int y = Q2_BOARD_H - 1; y >= 0; --y) {
        int full = 1;
        for (int x = 0; x < Q2_BOARD_W; ++x)
            if (!g->board[y][x]) { full = 0; break; }
        if (!full) continue;
        for (int row = y; row > 0; --row)
            copy_bytes(g->board[row], g->board[row - 1], Q2_BOARD_W);
        clear_bytes(g->board[0], Q2_BOARD_W);
        ++cleared; ++y; /* examine shifted row again */
    }
    static const unsigned points[] = {0, 100, 300, 500, 800};
    g->score += points[cleared <= 4 ? cleared : 4] * g->level;
    g->lines += cleared;
    g->level = 1 + g->lines / 10;
    spawn(g);
    return g->game_over ? -1 : 1;
}
int q2_blocks_drop(Q2Blocks *g)
{
    if (g->game_over) return 0;
    int rows = 0;
    while (can_place(g, g->x, g->y + 1, g->rotation)) {
        ++g->y; ++rows;
    }
    g->score += (unsigned)rows * 2u;
    (void)q2_blocks_tick(g);
    return rows;
}
int q2_blocks_next_cell(const Q2Blocks *g, int x, int y)
{
    if (x < 0 || x > 3 || y < 0 || y > 3) return 0;
    return piece_bit(g->next, 0, x, y) ? g->next + 1 : 0;
}
int q2_blocks_cell(const Q2Blocks *g, int x, int y)
{
    if (x < 0 || x >= Q2_BOARD_W || y < 0 || y >= Q2_BOARD_H) return 0;
    if (!g->game_over && x >= g->x && x < g->x + 4 &&
        y >= g->y && y < g->y + 4 &&
        piece_bit(g->piece, g->rotation, x - g->x, y - g->y))
        return g->piece + 1;
    return g->board[y][x];
}
