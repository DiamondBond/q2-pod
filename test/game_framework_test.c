/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "../patch/game_framework.h"
#include <assert.h>
#include <stdio.h>
typedef struct { unsigned steps, resets, paints, inputs, elapsed; } Fake;
static int input(void *ctx, Q2GameInput e)
{
    Fake *f = ctx;
    assert(e.action == Q2_GAME_WHEEL || e.action == Q2_GAME_TOUCH_MOVE ||
           e.action == Q2_GAME_TOUCH_DOWN || e.action == Q2_GAME_TOUCH_UP);
    f->inputs++;
    return 1;
}
static void step(void *ctx, unsigned ms)
{
    Fake *f = ctx;
    f->steps++;
    f->elapsed += ms;
}
static void paint(const void *ctx, void *canvas)
{
    (void)canvas;
    ((Fake *)ctx)->paints++;
}
static void reset(void *ctx) { ((Fake *)ctx)->resets++; }
int main(void)
{
    Fake f = {0};
    const Q2GameHooks hooks = {input, step, paint, reset};
    Q2GameRunner g;
    q2_game_init(&g, &hooks, &f, 20);
    assert(f.resets == 1 && g.status == Q2_GAME_RUNNING);
    assert(q2_game_advance(&g, 15) == 0);
    assert(q2_game_advance(&g, 10) == 1 && f.elapsed == 20);
    assert(q2_game_input(&g, (Q2GameInput){.action=Q2_GAME_WHEEL,.value=-20}) == 1);
    assert(q2_game_input(&g, (Q2GameInput){.action=Q2_GAME_TOUCH_MOVE}) == 0);
    assert(q2_game_input(&g, (Q2GameInput){.action=Q2_GAME_TOUCH_DOWN}) == 1);
    assert(q2_game_input(&g, (Q2GameInput){.action=Q2_GAME_TOUCH_MOVE}) == 1);
    assert(q2_game_input(&g, (Q2GameInput){.action=Q2_GAME_TOUCH_UP}) == 1);
    assert(q2_game_input(&g, (Q2GameInput){.action=Q2_GAME_PLAY}) == 1);
    assert(g.status == Q2_GAME_PAUSED && q2_game_advance(&g, 500) == 0);
    assert(q2_game_input(&g, (Q2GameInput){.action=Q2_GAME_WHEEL}) == 0);
    assert(q2_game_input(&g, (Q2GameInput){.action=Q2_GAME_PLAY}) == 1);
    assert(q2_game_advance(&g, 10000) == 4);
    q2_game_over(&g);
    assert(q2_game_advance(&g, 20) == 0);
    q2_game_restart(&g);
    assert(f.resets == 2 && g.status == Q2_GAME_RUNNING);
    q2_game_paint(&g, 0);
    assert(f.paints == 1);
    puts("game_framework: all tests passed");
    return 0;
}
