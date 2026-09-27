/* Stock V1.32 layout and ABI constants shared by patch/ringnav.c and tools/test_patch.py.
 * The test harness parses this file, so a field change cannot leave the mocks behind.
 * Fields marked "same slot" are class-specific views of one offset. */
#define W_X 0x00
#define W_Y 0x04
#define W_W 0x08
#define W_H 0x0c
#define W_FOCUS 0x24            /* stock focused flag byte (tests) */
#define W_PARENT 0x48
#define W_EMITTER 0x60
#define W_CHILDREN_LAYOUT 0x68
#define CHILDREN_LAYOUT_VTABLE 0x10
#define DEFAULT_LAYOUT_X_MARGIN 0x18
#define DEFAULT_LAYOUT_SPACING 0x1a
#define DEFAULT_LAYOUT_VTABLE 0x926b20
#define EMIT_TYPE 0x08
#define EMIT_PENDING_REMOVE 0x15
#define EMIT_NEXT 0x20
#define ROW_HEIGHT 0x78         /* table_client row height */
#define ROW_INDEX 0x78          /* table_row logical index (same slot) */
#define SLIDE_INDEX 0x78        /* slide_menu current index (same slot) */
#define TABLE_ROWS 0x7c         /* table_client logical row count */
#define VIEW_CONTENT_H 0x7c     /* scroll_view content height (same slot) */
#define SCROLL_X 0x80           /* scroll_view horizontal offset */
#define TABLE_TOP 0x80          /* table_client viewport top (same slot) */
#define SCROLL_Y 0x84           /* scroll_view viewport top */
#define VIEW_HORIZONTAL 0x90    /* scroll_view xslidable */
#define VIEW_VERTICAL 0x91      /* scroll_view yslidable */
#define VIEW_SNAP 0x92          /* scroll_view snap_to_page */
#define TABLE_ANIMATOR 0xd0
#define VIEW_ANIMATOR 0xe8
#define EVENT_TYPE 0x00
#define EVENT_KEY 0x18
#define EVENT_TARGET 0x10
#define EVENT_X 0x18           /* pointer_event_init @0x640298 */
#define EVENT_Y 0x1c
#define EVT_POINTER_DOWN 0x100 /* wm registers on_wm_tsdown_before_fun for this type @0x523ef0 */
#define EVT_POINTER_MOVE_BEFORE 0x102 /* wm move-before forwards this type to the down hook @0x523ed4 */
#define EVT_POINTER_UP_BEFORE 0x104
#define EVT_POINTER_ABORT 0x107
#define EVT_DESTROY 0x0c
#define EVT_KEY_DOWN_BEFORE 0x112 /* wm keydown-before dispatch @0x523e6c */
#define EVT_KEY_UP 0x114          /* wm keyup dispatch @0x523eb8 */
#define EVT_KEY_UP_BEFORE 0x115   /* wm keyup-before dispatch @0x523e80 */
#define EVT_WINDOW_BACKGROUND 0x12a
#define EVT_WINDOW_CLOSE 0x12c
#define PULL_SEARCH_PX 48       /* device tuning: release distance from the initial touch */
#define PULL_CLAIM_PX 8
#define QUICK_EDGE_PX 31        /* stock on_wm_tsmove_fun @0x4e8d10 */
#define EVT_CLICK 0x10c
#define CANVAS_X 0x00
#define CANVAS_Y 0x04
#define CANVAS_LCD 0x38
#define LCD_FILL_COLOR 0xbc
#define LCD_STROKE_COLOR 0xc0
/* Selection outline tuning. RADIUS > 2 or the stock rounded path squares off; tests read these.
 * The shade uses the same stock dark surface as the fill at an alpha that keeps the outline
 * above 3:1 on pure white art (0x99 is the floor); on dark rows it matches the stock background
 * exactly and disappears. The line is translucent white at OUTLINE_ALPHA, so it reads as a soft
 * grey on the dark theme instead of a hard white edge; lower OUTLINE_ALPHA or SHADE_ALPHA
 * together and the contrast margin over bright art erodes. */
#define RADIUS 9
#define FILL_RGB 0x2b2b2b
#define FILL_ALPHA 0x40
#define SHADE_ALPHA 0xb3
#define OUTLINE_RGB 0xffffff
#define OUTLINE_ALPHA 0xb3
/* End bump and wrap, audited row lists only (see ring_list in patch/ringnav.c). A detent past an
 * end nudges the outline; further detents stop there while the wheel keeps turning, and the first
 * same-direction detent after a pause of EDGE_PAUSE_MS moves to the other end of the same list. */
#define BUMP_PX 6
#define BUMP_MS 120
#define EDGE_PAUSE_MS 300 /* well above WHEEL_RUN_MS, so a spin never counts as a pause */
#define BAR_VALUE 0x7c /* scroll_bar native value, maintained by list/table setters */
#define KEY_CENTER 218
#define KEY_PREV 172
#define KEY_NEXT 173
#define KEY_PLAY 171
#define KEY_RETURN 170 /* on_common_keyup @0x4e8124 */
#define BOOT_KEY_GUARD 0xa37c8a /* raw flag address, no symbol in the audited binary */
#define RETURN_RELEASE_LATCH 0xa37c8b /* stock long Return arms it; the key-up filter consumes it */

/* slide_menu_scroll_to @0x5f3400 and completion @0x5f3654; animator
 * start @0x665ab0, time_elapse @0x6660d4, scroll_set_params @0x682124. */
#define SLIDE_SPACER 0x84
#define SLIDE_OFFSET 0x94
#define SLIDE_ANIMATOR 0xc8
#define ANIM_ELAPSED 0x10
#define ANIM_START_TIME 0x18
#define ANIM_DURATION 0x20
#define ANIM_X_TO 0x60
#define SLIDE_EASING 8          /* stock scroll_to easing */
#define EVT_ANIM_END 0x125
