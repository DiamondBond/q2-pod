/* Paint through the Games sheet and share its theme, font and popups. */
static void tile2048_paint(const void *context, void *canvas) {
    const struct game *state = context;
    const Q22048 *game = &state->tile2048.game;
    static const unsigned colors[] = {
        0x29323f, 0x414e5d, 0x4d5e70, 0x5a506f, 0x745575, 0x82515d,
        0x854639, 0x69592d, 0x776127, 0x7a6424, 0x72511e, 0x315c4d
    };
    static const char *const directions[] = {"Up", "Right", "Down", "Left"};
    int size = (state->h - 76) / Q2_2048_SIDE;
    if (size > 56) size = 56;
    int x0 = (375 - Q2_2048_SIDE * size) / 2, y0 = 33;
    int board = Q2_2048_SIDE * size;
    box(canvas, x0, y0, board, board, 0x151c26);
    for (int i = 0; i < Q2_2048_CELLS; ++i) {
        int x = x0 + i % Q2_2048_SIDE * size, y = y0 + i / Q2_2048_SIDE * size;
        unsigned power = game->tile[i];
        unsigned color = colors[power < Q2_2048_GOAL ? power : Q2_2048_GOAL];
        round_box(canvas, x + 2, y + 2, size - 4, size - 4, color, 4);
        if (power) {
            char number[8];
            tk_snprintf(number, sizeof number, "%u", 1u << power);
            text_at(canvas, number, x + size / 2, y, size, power >= 14 ? 12 : 17,
                    rgba(0xffffff, 255), MID);
        }
    }
    hud(canvas, "Score", game->score, HUD_X, 4, 0, rgba(0xffffff, 255), SPOT_GREY);
    hud(canvas, "Best", game->best, 375 - HUD_X, 4, 1, rgba(0xffffff, 255), SPOT_GREY);
    text_at(canvas, directions[state->tile_direction], 187, y0 + board + 2, 20, 17,
            rgba(accent_tone(2), 255), MID);
    text_at(canvas, "Wheel: choose   Centre: move", 187, y0 + board + 22, 18, 13,
            rgba(0xffffff, 255), MID);

    if (state->tile_menu == TILE_PAUSE_MENU)
        popup(canvas, "Paused", "Continue", "Game options", state->choice);
    else if (state->tile_menu == TILE_OPTIONS)
        popup(canvas, "Game options", "New game", "Quit", state->choice);
    else if (state->tile_menu == TILE_CONFIRM)
        popup(canvas, "Start over?", "Cancel", "New game", state->choice);
    else if (state->tile_runner.status == Q2_GAME_OVER)
        popup(canvas, "Game over", "Centre: play again", 0, 0);
    else if (game->won && !game->continued)
        popup(canvas, "You reached 2048!", "Centre: keep playing", 0, 0);
    else if (state->tile_runner.status == Q2_GAME_PAUSED)
        popup(canvas, "Paused", "Centre: resume", 0, 0);
}
