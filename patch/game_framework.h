/* SPDX-License-Identifier: GPL-3.0-or-later
 * Portable, allocation-free helpers for Q2 Pod built-in games.
 * Firmware owns hardware input, drawing and timer scheduling.
 */
#ifndef Q2_GAME_FRAMEWORK_H
#define Q2_GAME_FRAMEWORK_H
#include <stdint.h>
typedef enum {
    Q2_GAME_WHEEL, Q2_GAME_CENTER, Q2_GAME_RETURN, Q2_GAME_PLAY,
    Q2_GAME_PREV, Q2_GAME_NEXT, Q2_GAME_TOUCH_DOWN,
    Q2_GAME_TOUCH_MOVE, Q2_GAME_TOUCH_UP
} Q2GameAction;
typedef enum { Q2_GAME_RUNNING, Q2_GAME_PAUSED, Q2_GAME_OVER } Q2GameStatus;
typedef struct {
    Q2GameAction action;
    int value; /* signed raw travel for wheel */
    int x, y; /* view coordinates for touch */
} Q2GameInput;
typedef struct {
    int (*input)(void *context, Q2GameInput event);
    void (*step)(void *context, unsigned step_ms);
    void (*paint)(const void *context, void *canvas);
    void (*reset)(void *context);
} Q2GameHooks;
typedef struct {
    const Q2GameHooks *hooks;
    void *context;
    uint32_t remainder_ms;
    unsigned step_ms;
    Q2GameStatus status;
    unsigned touch_active : 1;
} Q2GameRunner;
void q2_game_init(Q2GameRunner *runner, const Q2GameHooks *hooks, void *context,
                  unsigned step_ms);
void q2_game_pause(Q2GameRunner *runner);
void q2_game_resume(Q2GameRunner *runner);
void q2_game_over(Q2GameRunner *runner);
void q2_game_restart(Q2GameRunner *runner);
int q2_game_input(Q2GameRunner *runner, Q2GameInput event);
unsigned q2_game_advance(Q2GameRunner *runner, unsigned elapsed_ms);
void q2_game_paint(const Q2GameRunner *runner, void *canvas);
#endif
