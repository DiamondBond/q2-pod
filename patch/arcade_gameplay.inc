/* Q2 built-in arcade adapters: reuse wheel sampling, AWTK timer and pause UI. */
static int arcade_frame(unsigned now) {
    unsigned elapsed = now - g->at;
    g->at = now;
    if (elapsed > 100) elapsed = 100; /* bounded catch-up after a delayed frame */
    if (g->screen == PONG) {
        int travel = __sync_lock_test_and_set(&wheel_travel, 0);
        if (travel) {
            q2_pong_move(&g->pong, -travel * 2);
            reset_poweroptions_timer(1, 1, 1);
        }
        g->acc += elapsed * 60;
        for (int n = 0; g->acc >= 1000 && n < 6; ++n) {
            g->acc -= 1000;
            q2_pong_tick(&g->pong);
        }
    } else if (g->screen == BREAKOUT) {
        int travel = __sync_lock_test_and_set(&wheel_travel, 0);
        if (travel) {
            q2_breakout_move(&g->breakout, travel * 2);
            reset_poweroptions_timer(1, 1, 1);
        }
        g->acc += elapsed * 60;
        for (int n = 0; g->acc >= 1000 && n < 6; ++n) {
            g->acc -= 1000;
            q2_breakout_tick(&g->breakout);
        }
        if (g->breakout.game_over) {
            breakout_record();
            g->frame = 0;
            hold(RUN);
            widget_invalidate_force(g->page, 0);
            return 0;
        }
    } else {
        /* Wheel travel is negative clockwise (same raw convention as Vortex).
         * Each 20 raw units rotates once, and a partial turn carries over.
         * Bound work on a fast flick; discard unused full turns if clamped. */
        int travel = __sync_lock_test_and_set(&wheel_travel, 0);
        if (travel) {
            g->carry += travel;
            reset_poweroptions_timer(1, 1, 1);
        }
        for (int n = 0; n < 4 && (g->carry >= 20 || g->carry <= -20); ++n) {
            int clockwise = g->carry < 0;
            (void)q2_blocks_rotate_dir(&g->blocks, clockwise ? 1 : -1);
            g->carry += clockwise ? 20 : -20;
        }
        if (g->carry >= 20 || g->carry <= -20) g->carry %= 20;
        unsigned steps = g->blocks.level < 13 ? g->blocks.level - 1 : 12;
        unsigned delay = 650u - steps * 45u;
        if (delay < 85u) delay = 85u;
        g->acc += elapsed;
        if (g->acc >= delay) {
            g->acc %= delay;
            q2_blocks_tick(&g->blocks);
        }
        if (g->blocks.game_over) {
            blocks_record();
            g->frame = 0;
            hold(RUN);
            widget_invalidate_force(g->page, 0);
            return 0;
        }
    }
    widget_invalidate_force(g->page, 0);
    return 8; /* RET_REPEAT */
}

/* Pong/Breakout use wheel travel for paddles; Blocks uses wheel travel for rotation.
 * The physical side Previous/Next keys move Blocks left/right. */
static void arcade_new_key(unsigned key) {
    /* Share pause, Return, game over, and restart with Snake and Vortex. */
    int over = (g->screen == BLOCKS && g->blocks.game_over) ||
        (g->screen == BREAKOUT && g->breakout.game_over);
    if (arcade_key(key, over) || g->paused || over) return;
    if (g->screen == PONG) {
        if (key == KEY_PREV || key == KEY_BACK_BTN) q2_pong_move(&g->pong, -14);
        else if (key == KEY_NEXT || key == KEY_FWD_BTN) q2_pong_move(&g->pong, 14);
    } else if (g->screen == BREAKOUT) {
        if (key == KEY_CENTER) q2_breakout_launch(&g->breakout);
        else if (key == KEY_PREV || key == KEY_BACK_BTN) q2_breakout_move(&g->breakout, -14);
        else if (key == KEY_NEXT || key == KEY_FWD_BTN) q2_breakout_move(&g->breakout, 14);
    } else {
        if (key == KEY_BACK_BTN) q2_blocks_move(&g->blocks, -1);
        else if (key == KEY_FWD_BTN) q2_blocks_move(&g->blocks, 1);
        else if (key == KEY_CENTER) (void)q2_blocks_drop(&g->blocks);
        else if (key == KEY_PLAY) {
            /* The bottom Play/Pause button is Down in Blocks: soft drop three
             * rows per press, stopping on lock/game over. Return opens the
             * existing Continue/Quit menu, with no extra state allocation. */
            for (int n = 0; n < 3 && !g->blocks.game_over; ++n)
                if (q2_blocks_tick(&g->blocks) != 0) break;
        }
    }
}
