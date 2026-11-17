/* 2048 is turn-based: the shared runner needs no step callback or frame timer. */
static int tile2048_input(void *context, Q2GameInput event) {
    struct game *state = context;
    if (event.action == Q2_GAME_WHEEL) {
        state->tile_direction = (Q22048Direction)(((int)state->tile_direction + event.value + 4) % 4);
        return 1;
    }
    if (event.action == Q2_GAME_PREV) state->tile_direction = Q2_2048_LEFT;
    else if (event.action == Q2_GAME_NEXT) state->tile_direction = Q2_2048_RIGHT;
    else if (event.action != Q2_GAME_CENTER) return 0;
    if (!q2_2048_move(&state->tile2048.game, state->tile_direction)) return 0;
    changed(4);
    if (!q2_2048_can_move(&state->tile2048.game)) q2_game_over(&state->tile_runner);
    return 1;
}

static void tile2048_reset(void *context) {
    struct game *state = context;
    q2_2048_new(&state->tile2048.game, (unsigned)time_now_ms() ^ state->tile2048.game.rng);
    state->tile_direction = Q2_2048_LEFT;
}

static void tile2048_paint(const void *context, void *canvas);

static const Q2GameHooks tile2048_hooks = {
    .input = tile2048_input, .paint = tile2048_paint, .reset = tile2048_reset
};

enum { TILE_BOARD, TILE_PAUSE_MENU, TILE_OPTIONS, TILE_CONFIRM };

static void tile2048_key(unsigned key) {
    Q2GameRunner *runner = &g->tile_runner;
    Q22048 *game = &g->tile2048.game;
    if (g->tile_menu) {
        if (key == KEY_NEXT || key == KEY_PREV) g->choice = !g->choice;
        else if (key == KEY_RETURN || key == KEY_PLAY) {
            --g->tile_menu;
            g->choice = 0;
            if (!g->tile_menu) q2_game_resume(runner);
        } else if (key == KEY_CENTER) {
            if (g->tile_menu == TILE_PAUSE_MENU) {
                g->tile_menu = g->choice ? TILE_OPTIONS : TILE_BOARD;
                if (!g->tile_menu) q2_game_resume(runner);
            } else if (g->tile_menu == TILE_OPTIONS) {
                if (g->choice) to(CHOOSER);
                else g->tile_menu = TILE_CONFIRM;
            } else if (g->choice) {
                q2_game_restart(runner);
                changed(4);
                g->tile_menu = TILE_BOARD;
            } else g->tile_menu = TILE_OPTIONS;
            g->choice = 0;
        }
    } else if (runner->status == Q2_GAME_OVER) {
        if (key == KEY_CENTER) {
            q2_game_restart(runner);
            changed(4);
        }
        else if (key == KEY_RETURN) to(CHOOSER);
    } else if (game->won && !game->continued) {
        if (key == KEY_CENTER) {
            game->continued = 1;
            changed(4);
        } else if (key == KEY_RETURN) to(CHOOSER);
    } else if (key == KEY_RETURN) {
        q2_game_pause(runner);
        g->tile_menu = TILE_PAUSE_MENU;
        g->choice = 0;
    } else {
        Q2GameInput event = {0};
        switch (key) {
        case KEY_NEXT: event = (Q2GameInput){ .action = Q2_GAME_WHEEL, .value = 1 }; break;
        case KEY_PREV: event = (Q2GameInput){ .action = Q2_GAME_WHEEL, .value = -1 }; break;
        case KEY_CENTER:
            if (runner->status == Q2_GAME_PAUSED) {
                q2_game_resume(runner);
                return;
            }
            event.action = Q2_GAME_CENTER;
            break;
        case KEY_PLAY: event.action = Q2_GAME_PLAY; break;
        case KEY_BACK_BTN: event.action = Q2_GAME_PREV; break;
        case KEY_FWD_BTN: event.action = Q2_GAME_NEXT; break;
        default: return;
        }
        q2_game_input(runner, event);
    }
}
