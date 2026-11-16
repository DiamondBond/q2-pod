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
        if (g->pong.player_score >= 7 || g->pong.cpu_score >= 7) {
            g->frame = 0;
            hold(RUN);
            widget_invalidate_force(g->page, 0);
            return 0;
        }
    } else {
        unsigned steps = g->blocks.level < 13 ? g->blocks.level - 1 : 12;
        unsigned delay = 650u - steps * 45u;
        if (delay < 85u) delay = 85u;
        g->acc += elapsed;
        if (g->acc >= delay) {
            g->acc %= delay;
            q2_blocks_tick(&g->blocks);
        }
        if (g->blocks.game_over) {
            g->frame = 0;
            hold(RUN);
            widget_invalidate_force(g->page, 0);
            return 0;
        }
    }
    widget_invalidate_force(g->page, 0);
    return 8; /* RET_REPEAT */
}

/* The wheel generates discrete KEY_PREV/NEXT for Blocks, raw travel for Pong. */
static void arcade_new_key(unsigned key) {
    int over = g->screen == PONG
        ? g->pong.player_score >= 7 || g->pong.cpu_score >= 7
        : g->blocks.game_over;
    if (g->paused == MENU) {
        if (key == KEY_NEXT || key == KEY_PREV ||
            key == KEY_FWD_BTN || key == KEY_BACK_BTN)
            g->choice = !g->choice;
        else if (key == KEY_CENTER && g->choice)
            to(CHOOSER);
        else if (key == KEY_CENTER || key == KEY_RETURN || key == KEY_PLAY)
            run();
        return;
    }
    if (over) {
        if (key == KEY_CENTER) {
            if (g->screen == PONG) q2_pong_init(&g->pong);
            else q2_blocks_init(&g->blocks, (unsigned)time_now_ms());
            run();
        } else if (key == KEY_RETURN) to(CHOOSER);
        return;
    }
    if (key == KEY_RETURN) { hold(MENU); g->choice = 0; return; }
    if (g->paused) {
        if (key == KEY_PLAY || key == KEY_CENTER) run();
        return;
    }
    if (key == KEY_PLAY) { hold(HELD); return; }
    if (g->screen == PONG) {
        if (key == KEY_PREV || key == KEY_BACK_BTN) q2_pong_move(&g->pong, -14);
        else if (key == KEY_NEXT || key == KEY_FWD_BTN) q2_pong_move(&g->pong, 14);
    } else {
        if (key == KEY_PREV) q2_blocks_move(&g->blocks, -1);
        else if (key == KEY_NEXT) q2_blocks_move(&g->blocks, 1);
        else if (key == KEY_CENTER) q2_blocks_rotate(&g->blocks);
        else if (key == KEY_BACK_BTN) {
            if (!g->blocks.game_over) q2_blocks_tick(&g->blocks);
        } else if (key == KEY_FWD_BTN) q2_blocks_drop(&g->blocks);
    }
}
