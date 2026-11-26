/* Split: an iPod classic's Cover Flow open and close, as the window animation a theme names with
 * anim="split" (docs/internals.md#themes, Motion). The page underneath parts at Home's split line
 * (HOME_SPLIT_W, between its list and its art): its left half slides off to the left and its right
 * half off to the right, each by its own width, and the page opening, which stays still, shows
 * between them; a close runs it back. Stock's window manager does the rest as for its own slides:
 * it builds the animation from the window's hint through its animator factory, paints both windows
 * into snapshots first (window_animator_prepare), times and eases it, drops input while it runs and
 * paints the status bar over each frame. */
#include "navigation.h"

/* lcd_draw_image's rectangles */
typedef struct {
    float x, y, w, h;
} rectf_t;

/* Columns x to x + w of a snapshot (img, wa's offset of one) over win's rows, drawn dx along: the
 * one call stock's slides draw with (window_animator_htranslate_draw_prev @0x696d90), the source
 * in the lcd's pixels. */
static void blit(window_animator_t *wa, int img, widget_t *win, int x, int w, int dx) {
    if (w <= 0) return;
    float k = *(float *)((char *)wa + WA_RATIO), y = (float)I(win, W_Y), h = (float)I(win, W_H);
    rectf_t src = { (float)x * k, y * k, (float)w * k, h * k };
    rectf_t dst = { (float)(x + dx), y, (float)w, h };
    lcd_draw_image(P(P(wa, WA_CANVAS), CANVAS_LCD), (char *)wa + img, &src, &dst);
}

/* The split line in a window w wide, and how far a half of w pixels has gone, rounded as stock's
 * slides round. */
static int split_at(int w) { return w < HOME_SPLIT_W ? w : HOME_SPLIT_W; }
static int gone(window_animator_t *wa, int w) {
    return (int)(*(float *)((char *)wa + WA_PERCENT) * (float)w + 0.5f);
}

/* The page underneath, its halves apart. */
static int split_halves(window_animator_t *wa) {
    widget_t *under = P(wa, WA_PREV_WIN);
    int w = I(under, W_W), s = split_at(w), l = gone(wa, s), r = gone(wa, w - s);
    blit(wa, WA_PREV_IMG, under, l, s - l, -l);
    blit(wa, WA_PREV_IMG, under, s, w - s - r, r);
    return 0;
}

/* The page opening or closing, between them. */
static int split_between(window_animator_t *wa) {
    widget_t *under = P(wa, WA_PREV_WIN);
    int w = I(under, W_W), s = split_at(w), l = gone(wa, s), r = gone(wa, w - s);
    blit(wa, WA_CURR_IMG, P(wa, WA_CURR_WIN), s - l, l + r, 0);
    return 0;
}

/* Stock's window_animator_vtable_t, laid out as its slides' (htranslate's @0x93b234):
 * window_animator_create sizes the animation from it, prepare calls init and update the rest. With
 * no update_percent, update eases percent itself, 0 to 1 opening and 1 to 0 closing. */
static const struct {
    const char *type, *desc;
    unsigned size, overlap;
    void *init, *update_percent;
    int (*draw_prev)(window_animator_t *), (*draw_curr)(window_animator_t *);
    void *dimmed; /* under a dialog's dimming: no dialog takes this */
} split_vt = { .type = "split",
               .desc = "split",
               .size = WA_SIZE,
               .draw_prev = split_halves,
               .draw_curr = split_between };

static window_animator_t *split_create(int open, void *args) {
    return window_animator_create(open, &split_vt);
}

/* Once the factory has it, a hint may name it; a factory not made yet is asked again next time. */
void window_split_register(void) {
    static int registered;
    if (registered) return;
    window_animator_factory_t *factory = window_animator_factory();
    if (factory && !window_animator_factory_register(factory, "split", split_create))
        registered = 1;
}
