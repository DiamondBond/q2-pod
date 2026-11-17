/* A sample independent game that runs in the generic MIPS emulator. */
#include "q2_game_abi.h"
/* Freestanding guest: compiler may emit these for struct assignments. */
void *memset(void *dst, int value, unsigned long count) {
    unsigned char *p = dst;
    for (unsigned long i = 0; i < count; ++i) p[i] = (unsigned char)value;
    return dst;
}
void *memcpy(void *dst, const void *src, unsigned long count) {
    unsigned char *p = dst;
    const unsigned char *q = src;
    for (unsigned long i = 0; i < count; ++i) p[i] = q[i];
    return dst;
}
static int x = 180;
static int y = 155;
static int paused;
static Q2GDrawList display;
uint32_t q2g_version(void) { return Q2G_ABI_VERSION; }
const char *q2g_name(void) { return "Universal game example"; }
void q2g_init(uint32_t seed) { x = 40 + (int)(seed % 250u); y = 155; paused = 0; }
void q2g_input(uint32_t action, int32_t value) {
    if (action == Q2G_PLAY) { paused = !paused; return; }
    if (paused) return;
    if (action == Q2G_WHEEL) x += value;
    else if (action == Q2G_PREV) x -= 10;
    else if (action == Q2G_NEXT) x += 10;
    else if (action == Q2G_CENTER) y = 155;
    if (x < 0) x = 0;
    if (x > 350) x = 350;
}
void q2g_step(uint32_t ms) {
    if (!paused && ms && y < 275) ++y;
    if (y >= 275) y = 50;
}
const Q2GDrawList *q2g_render(void) {
    display.count = 3;
    display.commands[0] = (Q2GDrawCommand){.type=Q2G_CLEAR,.color=0x10141c};
    display.commands[1] = (Q2GDrawCommand){.type=Q2G_RECT,.x=x,.y=y,.w=24,.h=24,.color=0x41c9cf};
    display.commands[2] = (Q2GDrawCommand){.type=Q2G_TEXT,.x=14,.y=20,.color=0xffffff,
      .text="Generic ABI: Wheel to move | Play to pause"};
    return &display;
}
