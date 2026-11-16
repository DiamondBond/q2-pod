/* Render adapters for the integer-only game rules; no extra bitmaps or buffers. */
static void pong_paint(void *canvas, unsigned tone) {
    const Q2Pong *p = &g->pong;
    int h = g->h - 65;
    if (h < 140) h = 140;
    box(canvas, 18, 35, 339, h, 0x111722);
    for (int y = 47; y < 35 + h - 8; y += 24)
        box(canvas, 187, y, 2, 12, 0x636c77);
    int py = 35 + p->player_y * (h - 6) / 240;
    int cy = 35 + p->cpu_y * (h - 6) / 240;
    box(canvas, 26, py, 7, 48 * (h - 6) / 240, tone);
    box(canvas, 343, cy, 7, 48 * (h - 6) / 240, 0xffffff);
    int bx = 18 + p->ball_x * 339 / 320;
    int by = 35 + p->ball_y * (h - 6) / 240;
    box(canvas, bx - 4, by - 4, 8, 8, 0xffffff);
    hud(canvas, "You", p->player_score, HUD_X, 4, 0, rgba(0xffffff, 255), SPOT_GREY);
    hud(canvas, "CPU", p->cpu_score, 375 - HUD_X, 4, 1, rgba(0xffffff, 255), SPOT_GREY);
    paused_popup(canvas, p->player_score >= 7 || p->cpu_score >= 7);
}
static void blocks_paint(void *canvas, unsigned tone) {
    const Q2Blocks *b = &g->blocks;
    int size = (g->h - 48) / Q2_BOARD_H;
    if (size > 13) size = 13;
    if (size < 7) size = 7;
    int x0 = (375 - Q2_BOARD_W * size) / 2;
    int y0 = 37;
    box(canvas, x0 - 3, y0 - 3, Q2_BOARD_W * size + 6, Q2_BOARD_H * size + 6, 0x555555);
    box(canvas, x0, y0, Q2_BOARD_W * size, Q2_BOARD_H * size, 0x0d1320);
    static const unsigned colors[7] =
        {0x30c8e8, 0xe8d030, 0xac70d8, 0x48bc76, 0xe85e60, 0x5387db, 0xef9b3a};
    for (int y = 0; y < Q2_BOARD_H; ++y)
        for (int x = 0; x < Q2_BOARD_W; ++x) {
            int cell = q2_blocks_cell(b, x, y);
            if (cell) box(canvas, x0 + x * size + 1, y0 + y * size + 1,
                          size - 2, size - 2, colors[cell - 1]);
            else box(canvas, x0 + x * size + 1, y0 + y * size + 1,
                     size - 2, size - 2, 0x1b2531);
        }
    hud(canvas, "Score", b->score, HUD_X, 4, 0, rgba(0xffffff, 255), SPOT_GREY);
    hud(canvas, "Level", b->level, 375 - HUD_X, 4, 1, rgba(0xffffff, 255), SPOT_GREY);
    (void)tone;
    paused_popup(canvas, b->game_over);
}
