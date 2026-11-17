#include "../patch/tile2048.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    Q22048 game = { .tile = {1, 1, 1, 1, 1, 1, 2}, .rng = 9 };
    assert(q2_2048_slide(&game, Q2_2048_LEFT));
    assert(game.tile[0] == 2 && game.tile[1] == 2 && game.tile[2] == 0);
    assert(game.tile[4] == 2 && game.tile[5] == 2 && game.tile[6] == 0);
    assert(game.score == 12 && game.best == 12);
    game = (Q22048){ .tile = {1, 0, 1, 1}, .rng = 9 };
    assert(q2_2048_slide(&game, Q2_2048_RIGHT));
    assert(game.tile[1] == 0 && game.tile[2] == 1 && game.tile[3] == 2);
    game = (Q22048){ .tile = {[4] = 3, [12] = 3}, .rng = 9 };
    assert(q2_2048_slide(&game, Q2_2048_UP) && game.tile[0] == 4);
    assert(q2_2048_slide(&game, Q2_2048_DOWN) && game.tile[12] == 4);
    assert(!q2_2048_move(&game, Q2_2048_DOWN) && game.rng == 9);
    assert(q2_2048_move(&game, Q2_2048_UP) && game.rng != 9);
    unsigned count = 0;
    for (unsigned i = 0; i < Q2_2048_CELLS; ++i) count += game.tile[i] != 0;
    assert(count == 2);

    game = (Q22048){ .tile = {10, 10}, .rng = 9 };
    assert(q2_2048_move(&game, Q2_2048_LEFT) && game.won && game.score == 2048);
    Q22048 won = game;
    assert(!q2_2048_move(&game, Q2_2048_RIGHT) && !memcmp(&game, &won, sizeof game));
    game.continued = 1;
    assert(q2_2048_move(&game, Q2_2048_RIGHT) && q2_2048_valid(&game));

    game = (Q22048){ .tile = {1,2,1,2, 2,1,2,1, 1,2,1,2, 2,1,2,1}, .rng = 9, .best = 2048 };
    assert(!q2_2048_can_move(&game) && q2_2048_valid(&game));
    q2_2048_new(&game, 0);
    assert(q2_2048_valid(&game) && game.score == 0 && game.best == 2048);
    game.tile[0] = 32;
    assert(!q2_2048_valid(&game));
    puts("2048 rules passed");
}
